"""
Composite setup helpers for multi-step test prerequisites (PRD §3).

Uses get_success_data() (lenient) internally so a broken precondition surfaces
as a clear "setup failed", not a confusing assertion failure. Every fixture
builds its state from scratch — the server DB is empty before each test.

Identity threading: entity_backed actors (Inspector, Contractor) always act via
make_inspector_headers(id) / make_contractor_headers(id) so ownership checks pass.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_dwelling_payload, create_child_payload, create_blood_lead_test_payload,
    create_case_payload, create_inspector_payload, create_investigation_payload,
    create_finding_payload, create_clearance_test_payload, create_relocation_unit_payload,
    create_relocation_placement_payload, create_contractor_payload, create_grant_fund_payload,
    create_remediation_project_payload,
)
from .test_users import TEST_USERS, make_inspector_headers, make_contractor_headers


IC = TEST_USERS["intake_headers"]
CM = TEST_USERS["case_manager_headers"]
PA = TEST_USERS["program_admin_headers"]


# ─── Granular building blocks ──────────────────────────────────────────
def create_dwelling(**overrides) -> dict:
    return get_success_data(api_client.create_dwelling(create_dwelling_payload(**overrides), PA))


def create_child(dwelling_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_child(create_child_payload(dwelling_id, **overrides), IC)
    )


def record_blood_lead_test(child_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_blood_lead_test(create_blood_lead_test_payload(child_id, **overrides), IC)
    )


def open_case(child_id: str, dwelling_id: str, qualifying_test_id: str) -> dict:
    return get_success_data(
        api_client.create_case(create_case_payload(child_id, dwelling_id, qualifying_test_id), IC)
    )


def create_inspector(**overrides) -> dict:
    return get_success_data(api_client.create_inspector(create_inspector_payload(**overrides), PA))


def schedule_investigation(case_id: str, dwelling_id: str, inspector_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_investigation(
            create_investigation_payload(case_id, dwelling_id, inspector_id, **overrides), CM
        )
    )


def record_finding(investigation_id: str, inspector_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_finding(
            investigation_id, create_finding_payload(**overrides),
            make_inspector_headers(inspector_id),
        )
    )


def complete_investigation(investigation_id: str, inspector_id: str) -> dict:
    return get_success_data(
        api_client.complete_investigation(investigation_id, make_inspector_headers(inspector_id))
    )


def order_for_case(case_id: str) -> dict:
    data, _ = _list(api_client.list_orders(CM, params={"case_id": case_id}))
    assert data, f"no order found for case {case_id}"
    return data[0]


def activate_contractor(expires_at: str = "2027-01-01T00:00:00Z", **overrides) -> dict:
    con = get_success_data(api_client.create_contractor(create_contractor_payload(**overrides), PA))
    get_success_data(
        api_client.contractor_certification(
            con["id"], {"action": "ACTIVATE", "expires_at": expires_at}, PA
        )
    )
    return con


def create_grant_fund(total_budget_cents: int = 5000000, **overrides) -> dict:
    return get_success_data(
        api_client.create_grant_fund(
            create_grant_fund_payload(total_budget_cents=total_budget_cents, **overrides), PA
        )
    )


def _list(response):
    data = get_success_data(response)
    # get_success_data returns the data payload (list for array responses)
    return data, None


# ─── Simple case builders ──────────────────────────────────────────────
def setup_case(income_tier: str = "LOW", bll: float = 22.0,
               specimen_type: str = "VENOUS", test_kind: str = "DIAGNOSTIC",
               collected_at: str = "2026-05-02T10:00:00Z", **dwelling_overrides) -> dict:
    """Dwelling + child + one qualifying blood-lead test + an OPEN case.

    Returns ctx: d_id, ch_id, t1_id, case_id, case.
    """
    dwelling = create_dwelling(**dwelling_overrides)
    child = create_child(dwelling["id"], income_tier=income_tier)
    test = record_blood_lead_test(
        child["id"], bll_ug_dl=bll, specimen_type=specimen_type,
        test_kind=test_kind, collected_at=collected_at,
    )
    case = open_case(child["id"], dwelling["id"], test["id"])
    return {
        "d_id": dwelling["id"], "ch_id": child["id"], "t1_id": test["id"],
        "case_id": case["id"], "case": case, "dwelling": dwelling, "child": child,
    }


def setup_relocation_unit(status: str = "AVAILABLE", bedroom_count: int = 2, **overrides) -> dict:
    payload = create_relocation_unit_payload(bedroom_count=bedroom_count, **overrides)
    if status != "AVAILABLE":
        payload["status"] = status
    return get_success_data(api_client.create_relocation_unit(payload, PA))


def create_placement(case_id: str, unit_id: str, start_date: str, end_date: str,
                     occupant_count: int = 2) -> dict:
    return get_success_data(
        api_client.create_relocation_placement(
            create_relocation_placement_payload(
                case_id, unit_id, start_date=start_date, end_date=end_date,
                occupant_count=occupant_count,
            ), CM,
        )
    )


# ─── The full remediation scenario builder ─────────────────────────────
_STAGES = [
    "case", "investigation", "in_progress", "order",
    "proposed", "approved", "started", "clearance_pending", "cleared",
]


def build_remediation_scenario(stage: str = "order", income_tier: str = "VERY_LOW",
                               num_hazards: int = 2, grant_budget: int = 5000000,
                               bll: float = 22.0, second_inspector: bool = False) -> dict:
    """Walk the case -> investigation -> order -> project lifecycle up to `stage`.

    Stages (in order): case, investigation, in_progress, order, proposed,
    approved, started, clearance_pending, cleared.

    Returns ctx with (as reached): d_id, ch_id, t1_id, case_id, insp_id,
    insp2_id, inv_id, order_id, con_id, gf_id, gf_v, proj_id, and the latest
    case/order/project/grant objects. `second_inspector` (or any stage that
    signs a clearance) creates a distinct clearing inspector (insp2_id).
    """
    assert stage in _STAGES, f"unknown stage {stage}"
    target = _STAGES.index(stage)
    ctx: dict = {}

    # --- case ---
    base = setup_case(income_tier=income_tier, bll=bll)
    ctx.update({k: base[k] for k in ("d_id", "ch_id", "t1_id", "case_id", "case")})
    if target == _STAGES.index("case"):
        return ctx

    # --- investigation ---
    insp = create_inspector(full_name="Ivy Inspector", certification_id_number="RA-001")
    ctx["insp_id"] = insp["id"]
    if second_inspector or target >= _STAGES.index("cleared"):
        insp2 = create_inspector(full_name="Cade Clearer", certification_id_number="RA-002")
        ctx["insp2_id"] = insp2["id"]
    inv = schedule_investigation(ctx["case_id"], ctx["d_id"], ctx["insp_id"])
    ctx["inv_id"] = inv["id"]
    if target == _STAGES.index("investigation"):
        return ctx

    # --- in_progress (record findings) ---
    for i in range(num_hazards):
        record_finding(ctx["inv_id"], ctx["insp_id"], location=f"loc-{i}")
    if target == _STAGES.index("in_progress"):
        return ctx

    # --- order (complete investigation -> ISSUED order, case ENFORCEMENT) ---
    complete_investigation(ctx["inv_id"], ctx["insp_id"])
    order = order_for_case(ctx["case_id"])
    ctx["order_id"] = order["id"]
    ctx["order"] = order
    if target == _STAGES.index("order"):
        return ctx

    # --- proposed (contractor + grant + project) ---
    con = activate_contractor()
    ctx["con_id"] = con["id"]
    gf = create_grant_fund(total_budget_cents=grant_budget)
    ctx["gf_id"] = gf["id"]
    ctx["gf_v"] = gf["version"]
    proj = get_success_data(
        api_client.create_remediation_project(
            create_remediation_project_payload(ctx["order_id"], ctx["con_id"], ctx["gf_id"]), CM
        )
    )
    ctx["proj_id"] = proj["id"]
    ctx["project"] = proj
    if target == _STAGES.index("proposed"):
        return ctx

    # --- approved (reserve subsidy; OCC on grant version) ---
    proj = get_success_data(
        api_client.approve_project(
            ctx["proj_id"], {"expected_grant_fund_version": ctx["gf_v"]}, CM
        )
    )
    ctx["project"] = proj
    if target == _STAGES.index("approved"):
        return ctx

    # --- started (contractor starts; order ISSUED -> IN_REMEDIATION) ---
    proj = get_success_data(
        api_client.start_project(ctx["proj_id"], make_contractor_headers(ctx["con_id"]))
    )
    ctx["project"] = proj
    if target == _STAGES.index("started"):
        return ctx

    # --- clearance_pending (contractor requests clearance) ---
    order = get_success_data(
        api_client.request_clearance(ctx["order_id"], make_contractor_headers(ctx["con_id"]))
    )
    ctx["order"] = order
    if target == _STAGES.index("clearance_pending"):
        return ctx

    # --- cleared (independent inspector signs a PASS clearance) ---
    get_success_data(
        api_client.create_clearance_test(
            create_clearance_test_payload(ctx["order_id"]),
            make_inspector_headers(ctx["insp2_id"]),
        )
    )
    ctx["order"] = get_success_data(api_client.get_order(ctx["order_id"], CM))
    return ctx
