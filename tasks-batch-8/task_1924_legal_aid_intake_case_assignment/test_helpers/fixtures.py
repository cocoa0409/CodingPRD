"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Fixtures use get_success_data() so setup
failures surface as clear errors rather than confusing assertion failures.

Identity threading: after creating a StaffMember, any ownership-gated or
SoD-anchored call in the same chain uses make_*_headers(member["id"]) so the
X-User-ID equals the persisted entity id the server compares against.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_client_payload,
    create_application_payload,
    create_grant_program_payload,
    create_staff_payload,
    create_venue_rule_payload,
)
from .test_users import (
    make_intake_specialist_headers,
    make_supervising_attorney_headers,
    make_program_director_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------

def create_venue_rule(**overrides):
    """Create a venue rule. Returns the rule dict."""
    payload = create_venue_rule_payload(**overrides)
    resp = api_client.create_venue_rule(payload, make_program_director_headers())
    return get_success_data(resp)


def create_staff(**overrides):
    """Create a staff member. Returns the member dict."""
    payload = create_staff_payload(**overrides)
    resp = api_client.create_staff_member(payload, make_program_director_headers())
    return get_success_data(resp)


def create_intake_specialist(**overrides):
    """Create an INTAKE_SPECIALIST staff member. Returns the member dict."""
    overrides.setdefault("full_name", "Intake One")
    overrides["staff_type"] = "INTAKE_SPECIALIST"
    return create_staff(**overrides)


def create_supervisor(**overrides):
    """Create the attorney who will act as SupervisingAttorney. Returns member."""
    overrides.setdefault("full_name", "Sup One")
    overrides["staff_type"] = "ATTORNEY"
    overrides.setdefault("max_units", 40)
    return create_staff(**overrides)


def create_attorney(**overrides):
    """Create an ATTORNEY staff member. Returns the member dict."""
    overrides["staff_type"] = "ATTORNEY"
    overrides.setdefault("max_units", 40)
    return create_staff(**overrides)


def create_paralegal(supervising_attorney_id, **overrides):
    """Create a PARALEGAL supervised by the given attorney. Returns member."""
    overrides["staff_type"] = "PARALEGAL"
    overrides["supervising_attorney_id"] = supervising_attorney_id
    return create_staff(**overrides)


def create_client(intake_id, **overrides):
    """Create a client as the given intake specialist. Returns client dict."""
    payload = create_client_payload(**overrides)
    resp = api_client.create_client(payload, make_intake_specialist_headers(intake_id))
    return get_success_data(resp)


def create_grant_program(**overrides):
    """Create a grant program. Returns the program dict."""
    payload = create_grant_program_payload(**overrides)
    resp = api_client.create_grant_program(payload, make_program_director_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: application state progression
# ---------------------------------------------------------------------------

def create_application(intake_id, client_id, **overrides):
    """Create an application in SUBMITTED. Returns the application dict."""
    payload = create_application_payload(client_id=client_id, **overrides)
    resp = api_client.create_application(payload, make_intake_specialist_headers(intake_id))
    return get_success_data(resp)


def screen_application(app_id, intake_id):
    resp = api_client.screen_application(app_id, make_intake_specialist_headers(intake_id))
    return get_success_data(resp)


def decide_application(app_id, determination, intake_id):
    resp = api_client.decide_eligibility(
        app_id, {"determination": determination}, make_intake_specialist_headers(intake_id)
    )
    return get_success_data(resp)


def conflict_check(app_id, intake_id, result="CLEAR", **overrides):
    payload = {"result": result}
    payload.update(overrides)
    resp = api_client.create_conflict_check(
        app_id, payload, make_intake_specialist_headers(intake_id)
    )
    return get_success_data(resp)


def create_screened_application(intake_id, client_id, **overrides):
    """Application walked SUBMITTED -> SCREENED. Returns the application dict."""
    app = create_application(intake_id, client_id, **overrides)
    return screen_application(app["id"], intake_id)


def create_eligible_application(intake_id, client_id, **overrides):
    """Application walked SUBMITTED -> SCREENED -> ELIGIBLE.

    Requires the screen to compute ELIGIBLE (income under the cap or benefits).
    Returns the application dict (post-decide version).
    """
    app = create_application(intake_id, client_id, **overrides)
    screen_application(app["id"], intake_id)
    return decide_application(app["id"], "ELIGIBLE", intake_id)


def create_openable_application(intake_id, client_id, **overrides):
    """ELIGIBLE application with a CLEAR conflict check on file. Returns app."""
    app = create_eligible_application(intake_id, client_id, **overrides)
    conflict_check(app["id"], intake_id, result="CLEAR")
    return app


# ---------------------------------------------------------------------------
# Tier 2: case creation
# ---------------------------------------------------------------------------

def open_case_from_application(app_id, sup_id, service_level="ADVICE_ONLY", grant_program_id=None):
    """Open a case from an ELIGIBLE application. Returns the Case dict."""
    payload = {"service_level": service_level}
    if grant_program_id is not None:
        payload["grant_program_id"] = grant_program_id
    resp = api_client.open_case(app_id, payload, make_supervising_attorney_headers(sup_id))
    return get_success_data(resp)


def setup_open_case(case_type="CONSUMER_DEBT", service_level="ADVICE_ONLY",
                    venue="MUNICIPAL_COURT", base_weight=30, extended_eligible=False,
                    client_overrides=None, grant_program_id=None):
    """Full chain: venue rule + intake worker + supervisor + client +
    application -> ELIGIBLE + CLEAR conflict + open-case.

    Returns (case, app, intake_member, sup_member, client).
    """
    create_venue_rule(county="CountyA", case_type=case_type, venue=venue,
                      priority_base_weight=base_weight, extended_eligible=extended_eligible)
    intake = create_intake_specialist(practice_areas=[case_type])
    sup = create_supervisor(practice_areas=[case_type])
    client = create_client(intake["id"], **(client_overrides or {}))
    app = create_openable_application(intake["id"], client["id"], case_type=case_type)
    case = open_case_from_application(app["id"], sup["id"], service_level=service_level,
                                      grant_program_id=grant_program_id)
    return case, app, intake, sup, client


def setup_assigned_case(case_type="CONSUMER_DEBT", service_level="ADVICE_ONLY",
                        venue="MUNICIPAL_COURT", base_weight=30, extended_eligible=False,
                        client_overrides=None, attorney_overrides=None,
                        grant_program_id=None):
    """Open case + assign attorney. Returns (case, app, intake, sup, attorney, client)."""
    create_venue_rule(county="CountyA", case_type=case_type, venue=venue,
                      priority_base_weight=base_weight, extended_eligible=extended_eligible)
    intake = create_intake_specialist(practice_areas=[case_type])
    sup = create_supervisor(practice_areas=[case_type])
    attorney = create_attorney(practice_areas=[case_type], **(attorney_overrides or {}))
    client = create_client(intake["id"], **(client_overrides or {}))
    app = create_openable_application(intake["id"], client["id"], case_type=case_type)
    case = open_case_from_application(app["id"], sup["id"], service_level=service_level,
                                      grant_program_id=grant_program_id)
    resp = api_client.assign_case(
        case["id"],
        {"attorney_id": attorney["id"], "expected_case_version": case["version"]},
        make_supervising_attorney_headers(sup["id"]),
    )
    case = get_success_data(resp)
    return case, app, intake, sup, attorney, client


def setup_closed_advice_case():
    """ADVICE_ONLY case closed by the supervisor. Returns (case, intake, sup)."""
    case, app, intake, sup, _client = setup_open_case()
    resp = api_client.close_case(
        case["id"], {"outcome_code": "ADVICE_GIVEN", "closure_reason": "advice complete"},
        make_supervising_attorney_headers(sup["id"]),
    )
    return get_success_data(resp), intake, sup


# ---------------------------------------------------------------------------
# Tier 3: clock control
# ---------------------------------------------------------------------------

def set_clock(iso_ts):
    resp = api_client.set_clock({"to_iso8601": iso_ts}, make_program_director_headers())
    return get_success_data(resp)


def run_sweep():
    resp = api_client.run_daily_sweep(make_program_director_headers())
    return get_success_data(resp)
