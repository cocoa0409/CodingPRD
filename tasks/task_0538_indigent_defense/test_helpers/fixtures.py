"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server before every test, so every
test starts against an empty database). Helpers use get_success_data() so a
setup failure surfaces as a clear "Setup failed" error rather than a confusing
assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_attorney_headers, make_supervising_attorney_headers
from . import factories as F

_SUPER = TEST_USERS["supervising_attorney_headers"]
_CLERK = TEST_USERS["intake_clerk_headers"]
_OFFICER = TEST_USERS["screening_officer_headers"]
_COORD = TEST_USERS["assignment_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators
# ---------------------------------------------------------------------------

def create_office(**overrides) -> dict:
    return get_success_data(api_client.create_defender_office(F.create_office_payload(**overrides), _SUPER))


def create_attorney(office_id, **overrides) -> dict:
    return get_success_data(api_client.create_attorney(F.create_attorney_payload(office_id, **overrides), _SUPER))


def create_courtroom(**overrides) -> dict:
    return get_success_data(api_client.create_courtroom(F.create_courtroom_payload(**overrides), _SUPER))


def create_case(office_id, **overrides) -> dict:
    return get_success_data(api_client.create_case(F.create_case_payload(office_id, **overrides), _CLERK))


def submit_screening(case_id, **overrides) -> dict:
    return get_success_data(api_client.create_financial_screening(F.create_screening_payload(case_id, **overrides), _CLERK))


def decide_screening(screening_id, officer_user_id="officer-1") -> dict:
    headers = TEST_USERS["screening_officer_headers"] if officer_user_id == "officer-1" \
        else {"X-User-ID": officer_user_id, "X-User-Role": "ScreeningOfficer"}
    return get_success_data(api_client.decide_screening(screening_id, headers))


def create_conflict_check(case_id, attorney_id, co_defendant_names=None) -> dict:
    payload = F.create_conflict_check_payload(case_id, attorney_id,
                                              co_defendant_names=co_defendant_names or [])
    return get_success_data(api_client.create_conflict_check(payload, _COORD))


def create_assignment(case_id, attorney_id) -> dict:
    return get_success_data(api_client.create_assignment(F.create_assignment_payload(case_id, attorney_id), _COORD))


def set_clock(to_iso8601) -> None:
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, _SUPER))


# ---------------------------------------------------------------------------
# Tier 1/2: case-lifecycle progression
# ---------------------------------------------------------------------------

def setup_screened_case(office_overrides=None, attorney_overrides=None,
                        case_overrides=None, screening_overrides=None,
                        officer_user_id="officer-1"):
    """Office + attorney + case walked to SCREENED (eligible screening decided)
    + a CLEAR ConflictCheck for (case, attorney).

    Returns dict: office, attorney, case, screening, conflict_check.
    Screening defaults (income 800000, size 2, asset 0) resolve to ELIGIBLE.
    """
    office = create_office(**(office_overrides or {}))
    attorney = create_attorney(office["id"], **(attorney_overrides or {}))
    case = create_case(office["id"], **(case_overrides or {}))
    screening = submit_screening(case["id"], **(screening_overrides or {}))
    decide_screening(screening["id"], officer_user_id=officer_user_id)
    cc = create_conflict_check(case["id"], attorney["id"])
    return {
        "office": office,
        "attorney": attorney,
        "case": case,
        "screening": screening,
        "conflict_check": cc,
    }


def setup_assigned_case(office_overrides=None, attorney_overrides=None,
                        case_overrides=None, screening_overrides=None,
                        officer_user_id="officer-1"):
    """Screened case then ASSIGNED. Returns dict with assignment added."""
    ctx = setup_screened_case(office_overrides, attorney_overrides,
                              case_overrides, screening_overrides,
                              officer_user_id=officer_user_id)
    ctx["assignment"] = create_assignment(ctx["case"]["id"], ctx["attorney"]["id"])
    return ctx


def setup_disposed_case(disposition_type="PLEA", office_overrides=None,
                        attorney_overrides=None, case_overrides=None,
                        screening_overrides=None, officer_user_id="officer-1"):
    """Assigned case then DISPOSED. Returns dict with disposed case reflected."""
    ctx = setup_assigned_case(office_overrides, attorney_overrides,
                              case_overrides, screening_overrides,
                              officer_user_id=officer_user_id)
    ctx["case"] = get_success_data(
        api_client.dispose_case(ctx["case"]["id"], {"disposition_type": disposition_type}, _COORD)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: voucher lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_draft_panel_voucher(claimed_hours=5.0, office_overrides=None,
                              attorney_overrides=None, case_overrides=None):
    """Disposed case + PANEL_FEE voucher in DRAFT (owned by the attorney).
    Returns dict with 'voucher'. Attorney is created PANEL by default."""
    attorney_overrides = {**{"attorney_type": "PANEL"}, **(attorney_overrides or {})}
    ctx = setup_disposed_case(office_overrides=office_overrides,
                              attorney_overrides=attorney_overrides,
                              case_overrides=case_overrides)
    att_id = ctx["attorney"]["id"]
    voucher = get_success_data(api_client.create_voucher(
        F.create_voucher_payload(ctx["case"]["id"], att_id, voucher_type="PANEL_FEE",
                                 claimed_hours=claimed_hours),
        make_attorney_headers(att_id),
    ))
    ctx["voucher"] = voucher
    return ctx


def setup_submitted_panel_voucher(claimed_hours=5.0, office_overrides=None,
                                  attorney_overrides=None, case_overrides=None):
    """Disposed case + PANEL_FEE voucher walked to SUBMITTED."""
    ctx = setup_draft_panel_voucher(claimed_hours, office_overrides,
                                    attorney_overrides, case_overrides)
    att_id = ctx["attorney"]["id"]
    ctx["voucher"] = get_success_data(
        api_client.submit_voucher(ctx["voucher"]["id"], make_attorney_headers(att_id))
    )
    return ctx


def setup_approved_panel_voucher(claimed_hours=5.0, office_overrides=None,
                                 attorney_overrides=None, case_overrides=None):
    """Disposed case + PANEL_FEE voucher walked to APPROVED."""
    ctx = setup_submitted_panel_voucher(claimed_hours, office_overrides,
                                        attorney_overrides, case_overrides)
    ctx["voucher"] = get_success_data(
        api_client.approve_voucher(ctx["voucher"]["id"], _SUPER)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: recoupment (via disposition of a PARTIAL case)
# ---------------------------------------------------------------------------

def setup_partial_case_recoupment(office_overrides=None, attorney_overrides=None,
                                  case_overrides=None, screening_overrides=None,
                                  officer_user_id="officer-1"):
    """PARTIAL case disposed so a RecoupmentOrder auto-exists (ASSESSED).

    Default screening (income 3000000, size 2, asset 500000) resolves PARTIAL
    with contribution 50000. Returns dict with 'recoupment_order'.
    """
    screening_overrides = screening_overrides or {
        "household_income_cents": 3_000_000, "household_size": 2, "asset_value_cents": 500_000,
    }
    ctx = setup_disposed_case(office_overrides=office_overrides,
                              attorney_overrides=attorney_overrides,
                              case_overrides=case_overrides,
                              screening_overrides=screening_overrides,
                              officer_user_id=officer_user_id)
    orders, _ = _list_recoupment_orders(ctx["case"]["id"])
    ctx["recoupment_order"] = orders[0] if orders else None
    return ctx


def _list_recoupment_orders(case_id):
    resp = api_client.list_recoupment_orders(_SUPER, params={"case_id": case_id})
    body = resp.json()
    return body.get("data", []), body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 5: budget-restricted office
# ---------------------------------------------------------------------------

def setup_restricted_office_with_assigned_case():
    """Office (budget 200000) driven to RESTRICTED via a 187500 approved panel
    voucher, plus a SECOND assigned case with a REQUESTED service request.

    Returns dict: office, service_request (on the second assigned case),
    plus the first case's voucher.
    """
    office = create_office(annual_voucher_budget_cents=200_000)
    attorney = create_attorney(office["id"], attorney_type="PANEL")

    # First case -> disposed -> panel voucher 12.5h @ 15000 = 187500 approved -> RESTRICTED.
    caseX = create_case(office["id"], defendant_name="RestrictX")
    scrX = submit_screening(caseX["id"])
    decide_screening(scrX["id"])
    create_conflict_check(caseX["id"], attorney["id"])
    create_assignment(caseX["id"], attorney["id"])
    get_success_data(api_client.dispose_case(caseX["id"], {"disposition_type": "PLEA"}, _COORD))
    voucher = get_success_data(api_client.create_voucher(
        F.create_voucher_payload(caseX["id"], attorney["id"], voucher_type="PANEL_FEE",
                                 claimed_hours=12.5),
        make_attorney_headers(attorney["id"]),
    ))
    get_success_data(api_client.submit_voucher(voucher["id"], make_attorney_headers(attorney["id"])))
    voucher = get_success_data(api_client.approve_voucher(voucher["id"], _SUPER))

    # Second case -> assigned -> service request REQUESTED.
    caseY = create_case(office["id"], defendant_name="RestrictY")
    scrY = submit_screening(caseY["id"])
    decide_screening(scrY["id"])
    create_conflict_check(caseY["id"], attorney["id"])
    create_assignment(caseY["id"], attorney["id"])
    sr = get_success_data(api_client.create_service_request(
        F.create_service_request_payload(caseY["id"], service_type="EXPERT_PSYCH",
                                         estimated_hours=5, estimated_rate_cents=20_000),
        _COORD,
    ))
    return {
        "office": office,
        "attorney": attorney,
        "case_x": caseX,
        "voucher": voucher,
        "case_y": caseY,
        "service_request": sr,
    }
