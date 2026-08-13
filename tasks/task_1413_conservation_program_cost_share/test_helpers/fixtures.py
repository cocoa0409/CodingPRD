"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and uses the lenient ``get_success_data``
validator so a setup failure surfaces as a clear "Setup failed" error.

The canonical happy-path chain is:
    program (SETUP) -> pool + rate + criterion -> OPEN -> applicant ->
    application (DRAFT) -> submit (SUBMITTED) -> screen SCREENED_IN ->
    close -> run-ranking (SELECTED) -> contract (DRAFT) -> practice items ->
    obligate (OBLIGATED) -> report-installed (INSTALLED) -> certify (CERTIFIED)
    -> payment request -> review -> approve -> disburse (DISBURSED).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADMIN_USER,
    DEFAULT_ITEM_DEADLINE,
    PAYMENT_OFFICER_USER,
    PLANNER_USER,
    QA_USER,
    TEST_DEFAULTS,
)
from .factories import (
    certify_payload,
    create_advance_payload,
    create_applicant_payload,
    create_application_payload,
    create_contract_payload,
    create_criterion_payload,
    create_modification_payload,
    create_payment_request_payload,
    create_pool_payload,
    create_practice_item_payload,
    create_program_payload,
    create_rate_payload,
    create_spot_check_payload,
    planned_practice,
    record_result_payload,
    screen_payload,
)
from .test_users import (
    make_admin_headers,
    make_applicant_headers,
    make_payment_officer_headers,
    make_planner_headers,
    make_qa_headers,
)

ADMIN = make_admin_headers(ADMIN_USER)


def _ok(response, label: str):
    assert response.status_code < 400, (
        f"Setup failed: {label} -> {response.status_code}: {response.text}"
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Primitive step helpers
# ---------------------------------------------------------------------------

def create_program(**program_kwargs) -> dict:
    """Create a program (lands in SETUP). Returns the program resource."""
    resp = api_client.create_program(create_program_payload(**program_kwargs), ADMIN)
    return _ok(resp, "create_program")


def add_pool(program_id, pool_type="GENERAL", allocated_cents=None) -> dict:
    resp = api_client.create_pool(
        program_id,
        create_pool_payload(
            pool_type=pool_type,
            allocated_cents=(
                allocated_cents
                if allocated_cents is not None
                else TEST_DEFAULTS["POOL_GENERAL_ALLOCATED"]
            ),
        ),
        ADMIN,
    )
    return _ok(resp, "add_pool")


def add_rate(
    program_id,
    practice_code="FENCE",
    unit="FOOT",
    standard_rate_cents=None,
    hu_rate_cents=None,
    lifespan_years=None,
) -> dict:
    resp = api_client.create_rate(
        program_id,
        create_rate_payload(
            practice_code=practice_code,
            unit=unit,
            standard_rate_cents=(
                standard_rate_cents
                if standard_rate_cents is not None
                else TEST_DEFAULTS["FENCE_STANDARD_RATE"]
            ),
            hu_rate_cents=(
                hu_rate_cents
                if hu_rate_cents is not None
                else TEST_DEFAULTS["FENCE_HU_RATE"]
            ),
            lifespan_years=(
                lifespan_years
                if lifespan_years is not None
                else TEST_DEFAULTS["FENCE_LIFESPAN_YEARS"]
            ),
        ),
        ADMIN,
    )
    return _ok(resp, "add_rate")


def add_criterion(program_id, criterion_code="SOIL_HEALTH", weight=1.0, max_points=40) -> dict:
    resp = api_client.create_criterion(
        program_id,
        create_criterion_payload(
            criterion_code=criterion_code, weight=weight, max_points=max_points
        ),
        ADMIN,
    )
    return _ok(resp, "add_criterion")


def open_program(program_id) -> dict:
    return _ok(api_client.open_program(program_id, ADMIN), "open_program")


def close_program(program_id) -> dict:
    return _ok(api_client.close_program(program_id, ADMIN), "close_program")


def run_ranking(program_id) -> dict:
    return _ok(api_client.run_ranking(program_id, ADMIN), "run_ranking")


def register_applicant(legal_name="Test Producer", hu_category="NONE",
                       parcel_ids=("P-100",), registrar="admin") -> dict:
    headers = ADMIN if registrar == "admin" else make_planner_headers()
    resp = api_client.create_applicant(
        create_applicant_payload(
            legal_name=legal_name, hu_category=hu_category, parcel_ids=list(parcel_ids)
        ),
        headers,
    )
    return _ok(resp, "register_applicant")


def draft_application(program_id, applicant, parcel_id=None, planned=(("FENCE", 1000),),
                      self_reported_answers=None) -> dict:
    parcel = parcel_id if parcel_id is not None else applicant["parcel_ids"][0]
    answers = (
        self_reported_answers if self_reported_answers is not None else {"SOIL_HEALTH": 10}
    )
    resp = api_client.create_application(
        create_application_payload(
            program_id,
            applicant["id"],
            parcel_id=parcel,
            planned_practices=[planned_practice(code, qty) for code, qty in planned],
            self_reported_answers=answers,
        ),
        make_applicant_headers(applicant["id"]),
    )
    return _ok(resp, "draft_application")


def submit_application(application_id, applicant_id) -> dict:
    resp = api_client.submit_application(
        application_id, make_applicant_headers(applicant_id)
    )
    return _ok(resp, "submit_application")


def withdraw_application(application_id, applicant_id) -> dict:
    resp = api_client.withdraw_application(
        application_id, make_applicant_headers(applicant_id)
    )
    return _ok(resp, "withdraw_application")


def screen_in(application_id, verified_answers=None, planner_user=PLANNER_USER) -> dict:
    answers = verified_answers if verified_answers is not None else {"SOIL_HEALTH": 10}
    resp = api_client.screen_application(
        application_id,
        screen_payload("SCREENED_IN", answers),
        make_planner_headers(planner_user),
    )
    return _ok(resp, "screen_in")


def create_contract_for(application_id, planner_user=PLANNER_USER) -> dict:
    resp = api_client.create_contract(
        create_contract_payload(application_id), make_planner_headers(planner_user)
    )
    return _ok(resp, "create_contract_for")


def add_item(contract_id, practice_code="FENCE", planned_quantity=1000,
             implementation_deadline=DEFAULT_ITEM_DEADLINE,
             planner_user=PLANNER_USER) -> dict:
    resp = api_client.add_practice_item(
        contract_id,
        create_practice_item_payload(
            practice_code=practice_code,
            planned_quantity=planned_quantity,
            implementation_deadline=implementation_deadline,
        ),
        make_planner_headers(planner_user),
    )
    return _ok(resp, "add_item")


def obligate(contract_id) -> dict:
    return _ok(api_client.obligate_contract(contract_id, ADMIN), "obligate")


def install(item_id, applicant_id) -> dict:
    resp = api_client.report_installed(item_id, make_applicant_headers(applicant_id))
    return _ok(resp, "report_installed")


def certify(item_id, certified_quantity, planner_user=PLANNER_USER) -> dict:
    resp = api_client.certify_item(
        item_id, certify_payload(certified_quantity), make_planner_headers(planner_user)
    )
    return _ok(resp, "certify")


def fail_certification(item_id, planner_user=PLANNER_USER) -> dict:
    resp = api_client.fail_certification(item_id, make_planner_headers(planner_user))
    return _ok(resp, "fail_certification")


def create_request(contract_id, item_id, applicant_id, documented_cost_cents=300000,
                   documentation_refs=("receipt-1",)) -> dict:
    resp = api_client.create_payment_request(
        create_payment_request_payload(
            contract_id,
            item_id,
            documented_cost_cents=documented_cost_cents,
            documentation_refs=list(documentation_refs),
        ),
        make_applicant_headers(applicant_id),
    )
    return _ok(resp, "create_payment_request")


def review_request(request_id, officer=PAYMENT_OFFICER_USER) -> dict:
    resp = api_client.review_payment_request(
        request_id, make_payment_officer_headers(officer)
    )
    return _ok(resp, "review_request")


def approve_request(request_id, officer=PAYMENT_OFFICER_USER) -> dict:
    resp = api_client.approve_payment_request(
        request_id, make_payment_officer_headers(officer)
    )
    return _ok(resp, "approve_request")


def disburse_request(request_id, officer=PAYMENT_OFFICER_USER) -> dict:
    resp = api_client.disburse_payment_request(
        request_id, make_payment_officer_headers(officer)
    )
    return _ok(resp, "disburse_request")


def issue_advance(contract_id, item_id, issued_cents, officer=PAYMENT_OFFICER_USER) -> dict:
    resp = api_client.issue_advance(
        contract_id,
        create_advance_payload(item_id, issued_cents),
        make_payment_officer_headers(officer),
    )
    return _ok(resp, "issue_advance")


def set_clock(to_iso8601) -> dict:
    return _ok(api_client.set_clock(to_iso8601, ADMIN), "set_clock")


def get_pool(pool_id) -> dict:
    return _ok(api_client.get_pool(pool_id, ADMIN), "get_pool")


def get_item(item_id) -> dict:
    return _ok(api_client.get_practice_item(item_id, ADMIN), "get_practice_item")


def get_contract(contract_id) -> dict:
    return _ok(api_client.get_contract(contract_id, ADMIN), "get_contract")


def get_application(application_id) -> dict:
    return _ok(api_client.get_application(application_id, ADMIN), "get_application")


def get_advance(advance_id) -> dict:
    return _ok(api_client.get_advance(advance_id, ADMIN), "get_advance")


def get_request(request_id) -> dict:
    return _ok(api_client.get_payment_request(request_id, ADMIN), "get_payment_request")


def list_obligations_for_item(item_id) -> list:
    data = _ok(
        api_client.list_maintenance_obligations(ADMIN, params={"practice_item_id": item_id}),
        "list_maintenance_obligations",
    )
    return data if isinstance(data, list) else data.get("items", data)


def list_demands(**filters) -> list:
    data = _ok(
        api_client.list_recoupment_demands(ADMIN, params=filters),
        "list_recoupment_demands",
    )
    return data if isinstance(data, list) else data.get("items", data)


def open_spot_check(contract_id, item_id, payment_request_id=None, qa_user=QA_USER) -> dict:
    resp = api_client.create_spot_check(
        create_spot_check_payload(contract_id, item_id, payment_request_id),
        make_qa_headers(qa_user),
    )
    return _ok(resp, "create_spot_check")


def record_spot_result(spot_check_id, result="PASS", failure_reason=None,
                       qa_user=QA_USER) -> dict:
    resp = api_client.record_spot_check_result(
        spot_check_id,
        record_result_payload(result, failure_reason),
        make_qa_headers(qa_user),
    )
    return _ok(resp, "record_spot_check_result")


def request_modification(contract_id, applicant_id, kind, **fields) -> dict:
    resp = api_client.request_modification(
        contract_id,
        create_modification_payload(kind, **fields),
        make_applicant_headers(applicant_id),
    )
    return _ok(resp, "request_modification")


# ---------------------------------------------------------------------------
# Composite helpers
# ---------------------------------------------------------------------------

def setup_open_program(pools=(("GENERAL", None),), rates=(("FENCE", "FOOT", None, None, None),),
                       criteria=(("SOIL_HEALTH", 1.0, 40),), **program_kwargs) -> dict:
    """Program in OPEN with pools, rates, and ranking criteria configured.

    pools:   iterable of (pool_type, allocated_cents) — None uses the default.
    rates:   iterable of (practice_code, unit, standard, hu, lifespan) — None uses defaults.
    criteria: iterable of (criterion_code, weight, max_points).
    """
    program = create_program(**program_kwargs)
    pool_rows = [add_pool(program["id"], pt, cents) for pt, cents in pools]
    rate_rows = [
        add_rate(program["id"], code, unit, std, hu, life)
        for code, unit, std, hu, life in rates
    ]
    criterion_rows = [
        add_criterion(program["id"], code, weight, mp) for code, weight, mp in criteria
    ]
    opened = open_program(program["id"])
    return {
        "program": opened,
        "pools": pool_rows,
        "pool": pool_rows[0] if pool_rows else None,
        "rates": rate_rows,
        "criteria": criterion_rows,
    }


def setup_screened_application(ctx, applicant=None, parcel_id=None,
                               planned=(("FENCE", 1000),),
                               self_reported_answers=None,
                               verified_answers=None,
                               hu_category="NONE", parcel_ids=("P-100",),
                               legal_name="Test Producer") -> dict:
    """Add an applicant + application to an OPEN program ctx; submit and screen in."""
    if applicant is None:
        applicant = register_applicant(
            legal_name=legal_name, hu_category=hu_category, parcel_ids=parcel_ids
        )
    application = draft_application(
        ctx["program"]["id"], applicant, parcel_id=parcel_id, planned=planned,
        self_reported_answers=self_reported_answers,
    )
    submitted = submit_application(application["id"], applicant["id"])
    screened = screen_in(submitted["id"], verified_answers)
    ctx.setdefault("applicants", []).append(applicant)
    ctx.setdefault("applications", []).append(screened)
    ctx["applicant"] = applicant
    ctx["application"] = screened
    return ctx


def setup_selected_application(**kwargs) -> dict:
    """Open program + one SCREENED_IN application, then close + run-ranking."""
    ctx = setup_open_program(**{
        k: v for k, v in kwargs.items()
        if k in ("pools", "rates", "criteria", "program_name", "fiscal_year",
                 "state_code", "window_start", "window_end",
                 "spot_check_modulus", "advance_cap_pct")
    })
    app_kwargs = {k: v for k, v in kwargs.items() if k in (
        "parcel_id", "planned", "self_reported_answers", "verified_answers",
        "hu_category", "parcel_ids", "legal_name")}
    ctx = setup_screened_application(ctx, **app_kwargs)
    ctx["program"] = close_program(ctx["program"]["id"])
    ctx["ranking"] = run_ranking(ctx["program"]["id"])
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


def build_contract(ctx, application_id, items=(("FENCE", 1000),),
                   item_deadline=DEFAULT_ITEM_DEADLINE) -> dict:
    """Create a DRAFT contract from a SELECTED application and add practice items.

    items: iterable of (practice_code, planned_quantity) or
           (practice_code, planned_quantity, deadline).
    """
    contract = create_contract_for(application_id)
    item_rows = []
    for spec in items:
        code, qty = spec[0], spec[1]
        deadline = spec[2] if len(spec) > 2 else item_deadline
        item_rows.append(add_item(contract["id"], code, qty, deadline))
    ctx["contract"] = contract
    ctx["items"] = item_rows
    ctx["item"] = item_rows[0] if item_rows else None
    return ctx


def setup_obligated_contract(items=(("FENCE", 1000),),
                             item_deadline=DEFAULT_ITEM_DEADLINE, **kwargs) -> dict:
    """Full happy path through an OBLIGATED contract. Returns the context dict:
    program, pools/pool, rates, criteria, applicant, application, contract, items/item.
    """
    ctx = setup_selected_application(**kwargs)
    ctx = build_contract(ctx, ctx["application"]["id"], items=items,
                         item_deadline=item_deadline)
    ctx["contract"] = obligate(ctx["contract"]["id"])
    return ctx


def setup_certified_item(certified_quantity=1000, item_index=0, **kwargs) -> dict:
    """OBLIGATED contract with the chosen item INSTALLED then CERTIFIED."""
    ctx = setup_obligated_contract(**kwargs)
    item = ctx["items"][item_index]
    ctx["items"][item_index] = install(item["id"], ctx["applicant"]["id"])
    ctx["items"][item_index] = certify(item["id"], certified_quantity)
    ctx["item"] = ctx["items"][item_index]
    return ctx


def setup_disbursed_request(certified_quantity=1000, documented_cost_cents=300000,
                            officer=PAYMENT_OFFICER_USER, certifier=PLANNER_USER,
                            **kwargs) -> dict:
    """Full pipeline through a DISBURSED payment request (request stored as ctx['request'])."""
    ctx = setup_certified_item(certified_quantity=certified_quantity, **kwargs)
    request = create_request(
        ctx["contract"]["id"], ctx["item"]["id"], ctx["applicant"]["id"],
        documented_cost_cents=documented_cost_cents,
    )
    ctx["request"] = review_request(request["id"], officer)
    ctx["request"] = approve_request(request["id"], officer)
    ctx["request"] = disburse_request(request["id"], officer)
    return ctx


def setup_hu_contract_with_advance(issued_cents=180000,
                                   pools=(("HU_LIMITED_RESOURCE", 500000),),
                                   hu_category="LIMITED_RESOURCE",
                                   parcel_ids=("P-200",), **kwargs) -> dict:
    """HU contract OBLIGATED (FENCE 1000 default) with an advance already ISSUED."""
    ctx = setup_obligated_contract(
        pools=pools, hu_category=hu_category, parcel_ids=parcel_ids, **kwargs
    )
    advance = issue_advance(ctx["contract"]["id"], ctx["item"]["id"], issued_cents)
    ctx["advance"] = advance
    return ctx


def applicant_headers_for(ctx) -> dict:
    """Ownership-correct headers for the context's primary applicant."""
    return make_applicant_headers(ctx["applicant"]["id"])
