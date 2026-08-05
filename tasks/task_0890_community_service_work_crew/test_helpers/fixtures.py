"""Composite setup helpers.

Every test runs against a freshly restarted, empty server, so each helper builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use the lenient
``get_success_data`` so a broken precondition surfaces as a clear "setup failed" error.

Identity threading: after creating an entity-backed Supervisor / Participant, ownership-gated
calls use ``make_supervisor_headers(id)`` / ``make_participant_headers(id)`` with that entity's
real id — never the shared unbound constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_participant_payload, create_site_payload, create_insurance_policy_payload,
    create_supervisor_payload, create_referral_payload, create_placement_payload,
    create_work_session_payload, create_fee_conversion_payload,
    create_compliance_action_payload,
)
from .test_users import (
    TEST_USERS, make_supervisor_headers, make_participant_headers,
)
from .constants import DEFAULT_CLOCK, DEFAULT_POLICY_EXPIRY

COORD = TEST_USERS["coordinator_headers"]
COORD2 = TEST_USERS["coordinator2_headers"]
CLERK = TEST_USERS["clerk_headers"]


# ------------------------------------------------------------- clock & primitives
def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


def new_participant(full_name="Pat Doe", email="pat@example.org", **overrides) -> dict:
    payload = create_participant_payload(full_name=full_name, contact_email=email,
                                         **overrides)
    return get_success_data(api_client.create_participant(payload, COORD))


def new_site(capacity_slots=5, name="Green Park", **overrides) -> dict:
    payload = create_site_payload(name=name, capacity_slots=capacity_slots, **overrides)
    return get_success_data(api_client.create_site(payload, COORD))


def new_policy(site_id, expiry=DEFAULT_POLICY_EXPIRY, **overrides) -> dict:
    payload = create_insurance_policy_payload(site_id, expiry_date=expiry, **overrides)
    return get_success_data(api_client.create_insurance_policy(payload, COORD))


def verify_policy(policy_id) -> dict:
    return get_success_data(api_client.verify_insurance_policy(policy_id, COORD))


def activate_site(site_id) -> dict:
    return get_success_data(api_client.activate_site(site_id, COORD))


def new_supervisor(site_id, full_name="Sam Sup", **overrides) -> dict:
    payload = create_supervisor_payload(site_id, full_name=full_name, **overrides)
    return get_success_data(api_client.create_supervisor(payload, COORD))


def new_referral(participant_id, hours_ordered=40, indigency="NONE",
                 court_case_number="CR-1", offense_class="MISDEMEANOR", **overrides) -> dict:
    payload = create_referral_payload(
        participant_id, hours_ordered=hours_ordered, indigency_status=indigency,
        court_case_number=court_case_number, offense_class=offense_class, **overrides)
    return get_success_data(api_client.create_referral(payload, CLERK))


def new_placement(referral_id, site_id, supervisor_id) -> dict:
    payload = create_placement_payload(referral_id, site_id, supervisor_id)
    return get_success_data(api_client.create_placement(payload, COORD))


def sign_waiver(placement_id, participant_id, signature_name="Pat Doe") -> dict:
    return get_success_data(api_client.sign_waiver(
        placement_id, {"signature_name": signature_name},
        make_participant_headers(participant_id)))


def activate_placement(placement_id) -> dict:
    return get_success_data(api_client.activate_placement(placement_id, COORD))


def new_session(placement_id, start, end, category=None) -> dict:
    payload = create_work_session_payload(placement_id, start, end)
    if category is not None:
        payload["session_category"] = category
    return get_success_data(api_client.create_work_session(payload, COORD))


def check_in(session_id, supervisor_id, at) -> dict:
    return get_success_data(api_client.check_in(
        session_id, make_supervisor_headers(supervisor_id), {"check_in_at": at}))


def check_out(session_id, supervisor_id, at) -> dict:
    return get_success_data(api_client.check_out(
        session_id, make_supervisor_headers(supervisor_id), {"check_out_at": at}))


def verify_session(session_id, supervisor_id, outcome="VERIFIED", attested=None) -> dict:
    payload = {"outcome": outcome}
    if attested is not None:
        payload["attested_hours"] = attested
    return get_success_data(api_client.verify_work_session(
        session_id, payload, make_supervisor_headers(supervisor_id)))


def referral_version(referral_id) -> int:
    ref = get_success_data(api_client.get_referral(referral_id, COORD))
    return ref["version"]


def new_fee_conversion(referral_id, hours_to_convert, participant_id,
                       expected_version=None) -> dict:
    if expected_version is None:
        expected_version = referral_version(referral_id)
    payload = create_fee_conversion_payload(referral_id, hours_to_convert, expected_version)
    return get_success_data(api_client.create_fee_conversion(
        payload, make_participant_headers(participant_id)))


def approve_fee(fee_id, approver_headers=COORD2) -> dict:
    return get_success_data(api_client.approve_fee_conversion(fee_id, approver_headers))


def pay_fee(fee_id, amount_cents, participant_id) -> dict:
    return get_success_data(api_client.pay_fee_conversion(
        fee_id, {"amount_cents": amount_cents}, make_participant_headers(participant_id)))


def report_back(referral_id, reason="Missed sessions") -> dict:
    payload = create_compliance_action_payload(referral_id, "REPORT_BACK", reason)
    return get_success_data(api_client.create_compliance_action(payload, CLERK))


# --------------------------------------------------------------- composite scenarios
def accepting_site_with_supervisor(capacity_slots=5, policy_expiry=DEFAULT_POLICY_EXPIRY,
                                   set_clock_first=True):
    """Insured, ACCEPTING site plus one supervisor on staff.

    Returns dict: site, policy, supervisor.
    """
    if set_clock_first:
        set_clock(DEFAULT_CLOCK)
    site = new_site(capacity_slots=capacity_slots)
    policy = new_policy(site["id"], expiry=policy_expiry)
    verify_policy(policy["id"])
    activate_site(site["id"])
    supervisor = new_supervisor(site["id"])
    return {"site": site, "policy": policy, "supervisor": supervisor}


def active_placement_scenario(hours_ordered=40, indigency="NONE", capacity_slots=5,
                              policy_expiry=DEFAULT_POLICY_EXPIRY,
                              court_case_number="CR-1"):
    """Full field-ops preamble: insured ACCEPTING site + supervisor + participant +
    ACTIVE referral + ACTIVE placement (waiver signed).

    Returns dict with keys: site, policy, supervisor, participant, referral, placement,
    plus convenience id fields (site_id, supervisor_id, participant_id, referral_id,
    placement_id).
    """
    base = accepting_site_with_supervisor(capacity_slots=capacity_slots,
                                          policy_expiry=policy_expiry)
    participant = new_participant()
    referral = new_referral(participant["id"], hours_ordered=hours_ordered,
                            indigency=indigency, court_case_number=court_case_number)
    placement = new_placement(referral["id"], base["site"]["id"], base["supervisor"]["id"])
    sign_waiver(placement["id"], participant["id"])
    placement = activate_placement(placement["id"])
    return {
        "site": base["site"],
        "policy": base["policy"],
        "supervisor": base["supervisor"],
        "participant": participant,
        "referral": referral,
        "placement": placement,
        "site_id": base["site"]["id"],
        "supervisor_id": base["supervisor"]["id"],
        "participant_id": participant["id"],
        "referral_id": referral["id"],
        "placement_id": placement["id"],
    }


def two_placements_same_site(capacity_slots=5, policy_expiry=DEFAULT_POLICY_EXPIRY,
                             same_supervisor=True):
    """Insured ACCEPTING site + two participants each on an ACTIVE placement at that site.

    When ``same_supervisor`` is True (default) both placements share one supervisor — used
    to exercise the supervisor double-booking guard. When False, each placement gets its own
    supervisor at the same site — used to isolate the site-capacity guard (which counts
    across supervisors) from the earlier-precedence supervisor double-booking guard.

    Returns dict: site_id, supervisor_id (placement1's supervisor), supervisor2_id,
    participant1_id, placement1_id, participant2_id, placement2_id.
    """
    base = accepting_site_with_supervisor(capacity_slots=capacity_slots,
                                          policy_expiry=policy_expiry)
    site_id = base["site"]["id"]
    sup_id = base["supervisor"]["id"]
    if same_supervisor:
        sup2_id = sup_id
    else:
        sup2_id = new_supervisor(site_id, full_name="Sam Sup Two")["id"]

    p1 = new_participant(full_name="P One", email="p1@example.org")
    r1 = new_referral(p1["id"], court_case_number="CR-A")
    plc1 = new_placement(r1["id"], site_id, sup_id)
    sign_waiver(plc1["id"], p1["id"], signature_name="P One")
    activate_placement(plc1["id"])

    p2 = new_participant(full_name="P Two", email="p2@example.org")
    r2 = new_referral(p2["id"], court_case_number="CR-B")
    plc2 = new_placement(r2["id"], site_id, sup2_id)
    sign_waiver(plc2["id"], p2["id"], signature_name="P Two")
    activate_placement(plc2["id"])

    return {
        "site_id": site_id,
        "supervisor_id": sup_id,
        "supervisor2_id": sup2_id,
        "participant1_id": p1["id"],
        "placement1_id": plc1["id"],
        "participant2_id": p2["id"],
        "placement2_id": plc2["id"],
    }


def completed_session(scenario, start, end, outcome="VERIFIED", attested=None,
                      category=None):
    """Schedule -> check-in -> check-out -> verify a single session inside an existing
    active_placement_scenario. Returns the verified WorkSession dict."""
    ws = new_session(scenario["placement_id"], start, end, category=category)
    check_in(ws["id"], scenario["supervisor_id"], start)
    check_out(ws["id"], scenario["supervisor_id"], end)
    return verify_session(ws["id"], scenario["supervisor_id"], outcome=outcome,
                          attested=attested)


def checked_out_session(scenario, start, end):
    """Schedule -> check-in -> check-out (attendance COMPLETED, verification PENDING).
    Returns the WorkSession dict (not yet verified)."""
    ws = new_session(scenario["placement_id"], start, end)
    check_in(ws["id"], scenario["supervisor_id"], start)
    return check_out(ws["id"], scenario["supervisor_id"], end)
