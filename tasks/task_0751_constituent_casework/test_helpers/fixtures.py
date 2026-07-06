"""Composite setup helpers.

Every test starts against an empty database (the harness relaunches the server
before each test), so these helpers build all preconditions from scratch using
only PRD-declared endpoints. Setup calls use the lenient get_success_data()
validator so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import TEST_USERS, make_constituent_headers
from . import factories as f

ADMIN = TEST_USERS["office_admin_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# ----------------------------------------------------------------------------
# Primitive builders
# ----------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Advance the logical clock to the supplied ISO 8601 instant (OfficeAdmin only)."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


def new_representative(api, **overrides) -> dict:
    return get_success_data(api.create_representative(f.create_representative_payload(**overrides), ADMIN))


def new_constituent(api, representative_id, **overrides) -> dict:
    return get_success_data(
        api.create_constituent(f.create_constituent_payload(representative_id, **overrides), ADMIN)
    )


def new_agency(api, **overrides) -> dict:
    return get_success_data(api.create_agency(f.create_agency_payload(**overrides), ADMIN))


def new_template(api, category, response_window_hours=100, **overrides) -> dict:
    return get_success_data(
        api.create_template(f.create_template_payload(category, response_window_hours, **overrides), ADMIN)
    )


def new_case(api, constituent_id, category="OTHER", **overrides) -> dict:
    return get_success_data(
        api.create_case(f.create_case_payload(constituent_id, category, **overrides), CASEWORKER)
    )


def triage(api, case_id, template_id, priority="NORMAL", assignee_staff_id="s1") -> dict:
    payload = {"template_id": template_id, "priority": priority, "assignee_staff_id": assignee_staff_id}
    return get_success_data(api.triage_case(case_id, payload, CASEWORKER))


def new_venue(api, capacity=50, **overrides) -> dict:
    return get_success_data(api.create_venue(f.create_venue_payload(capacity, **overrides), ADMIN))


def new_event(api, representative_id, venue_id, start_at, end_at, capacity=10, **overrides) -> dict:
    return get_success_data(
        api.create_event(
            f.create_event_payload(representative_id, venue_id, start_at, end_at, capacity, **overrides), ADMIN
        )
    )


def open_registration(api, event_id) -> dict:
    return get_success_data(api.open_registration(event_id, ADMIN))


def register(api, event_id, constituent_id, headers=None) -> dict:
    return get_success_data(
        api.create_registration(event_id, {"constituent_id": constituent_id}, headers or ADMIN)
    )


# ----------------------------------------------------------------------------
# Composite scenarios
# ----------------------------------------------------------------------------
def triaged_case(api, category="OTHER", priority="NORMAL", window=100, consent=True):
    """Representative + constituent + active template + a case triaged to IN_PROGRESS.

    Returns a dict of the created ids / entities. `consent` controls the
    constituent's data_sharing_consent flag.
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"], data_sharing_consent=consent)
    tmpl = new_template(api, category, response_window_hours=window)
    case = new_case(api, con["id"], category=category)
    triaged = triage(api, case["id"], tmpl["id"], priority=priority)
    return {
        "rep_id": rep["id"],
        "con_id": con["id"],
        "tmpl_id": tmpl["id"],
        "case_id": case["id"],
        "case": triaged,
        "con_headers": make_constituent_headers(con["id"]),
    }


def new_case_scenario(api, category="OTHER", consent=True):
    """Representative + constituent + a NEW (un-triaged) case. Returns ids dict."""
    rep = new_representative(api)
    con = new_constituent(api, rep["id"], data_sharing_consent=consent)
    case = new_case(api, con["id"], category=category)
    return {
        "rep_id": rep["id"],
        "con_id": con["id"],
        "case_id": case["id"],
        "case": case,
        "con_headers": make_constituent_headers(con["id"]),
    }


def referred_case(api, category="OTHER", priority="NORMAL", window=100, agency_status="ACTIVE"):
    """Triaged case + an ACTIVE agency + a DRAFT referral (case in AWAITING_AGENCY)."""
    base = triaged_case(api, category=category, priority=priority, window=window, consent=True)
    agency = new_agency(api, status=agency_status)
    referral = get_success_data(
        api.create_referral(base["case_id"], {"agency_id": agency["id"]}, CASEWORKER)
    )
    base["agency_id"] = agency["id"]
    base["ref_id"] = referral["id"]
    base["referral"] = referral
    return base


def sent_referral(api, category="OTHER", priority="NORMAL", window=100):
    """Triaged case + ACTIVE agency + referral created and SENT (agency.open_referral_count == 1)."""
    base = referred_case(api, category=category, priority=priority, window=window)
    sent = get_success_data(api.send_referral(base["ref_id"], CASEWORKER))
    base["referral"] = sent
    return base


def open_event(api, event_capacity=10, venue_capacity=50,
               start_at="2026-05-01T18:00:00Z", end_at="2026-05-01T19:00:00Z"):
    """Representative + venue + a SCHEDULED event with registration OPEN."""
    rep = new_representative(api)
    venue = new_venue(api, capacity=venue_capacity)
    event = new_event(api, rep["id"], venue["id"], start_at, end_at, capacity=event_capacity)
    open_registration(api, event["id"])
    return {"rep_id": rep["id"], "venue_id": venue["id"], "event_id": event["id"], "event": event}


def open_event_with_registration(api, event_capacity=10, venue_capacity=50):
    """Open event + one ACTIVE constituent registered (registered_count == 1)."""
    scenario = open_event(api, event_capacity=event_capacity, venue_capacity=venue_capacity)
    con = new_constituent(api, scenario["rep_id"])
    reg = register(api, scenario["event_id"], con["id"])
    scenario["con_id"] = con["id"]
    scenario["reg_id"] = reg["id"]
    scenario["registration"] = reg
    scenario["con_headers"] = make_constituent_headers(con["id"])
    return scenario
