"""The conserved member-month ledger: termination debits and appeal-reinstatement
re-credits must leave the conserved quantities at net-zero drift.
"""
from test_helpers import (
    api_client as api,
    TEST_USERS,
    validate_success,
    make_hearing_officer_headers,
    setup_heard_appeal,
)

CW = TEST_USERS["caseworker_headers"]


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================
def test_member_months_conserved_terminate_then_reinstate():
    """PRD §2.6: "When that enrollment is terminated, the very same `member_months`
    quantity is debited back out and the active count falls by one. When a
    terminated enrollment is reinstated through a successful appeal, the same
    `member_months` quantity is re-credited and the active count rises by one
    again — restoring the earlier debit so that the ledger experiences net-zero
    drift across a termination-then-reinstatement cycle."

    Design: Difficulty/compensating_invariant/member_months_conserved_terminate_then_reinstate
    """
    # Terminated size-2 enrollment (member_months 24, covered currently 0) with a HEARD appeal.
    hh, enr, redet, appeal = setup_heard_appeal(state="CA", cw_id="cw-7", ho_id="ho-3")
    debited = validate_success(api.get_household(hh["id"], CW))
    assert debited["covered_member_months"] == 0  # debited by termination

    ho = make_hearing_officer_headers("ho-3")
    api.rule_appeal(appeal["id"], {"target_status": "OVERTURNED"}, ho)

    hh_after = validate_success(api.get_household(hh["id"], CW))
    enr_after = validate_success(api.get_enrollment(enr["id"], CW))
    assert hh_after["covered_member_months"] == 24  # re-credited, net-zero drift
    assert enr_after["member_months"] == 24


def test_member_months_uses_same_quantity_on_recredit():
    """PRD §2.6: "When a terminated enrollment is reinstated through a successful
    appeal, the same `member_months` quantity is re-credited and the active count
    rises by one again — restoring the earlier debit so that the ledger
    experiences net-zero drift across a termination-then-reinstatement cycle."
    PRD §2.6: "The concrete `member_months` value an enrollment carries is fixed
    at the moment it first becomes active".

    The re-credited amount equals the enrollment's fixed member_months (24), not a
    recomputed value — so the household total returns exactly to its activated
    level.

    Design: Difficulty/compensating_invariant/member_months_conserved_terminate_then_reinstate
    """
    hh, enr, redet, appeal = setup_heard_appeal(state="CA", cw_id="cw-77", ho_id="ho-33")
    enr_terminated = validate_success(api.get_enrollment(enr["id"], CW))
    fixed_member_months = enr_terminated["member_months"]
    assert fixed_member_months == 24

    ho = make_hearing_officer_headers("ho-33")
    api.rule_appeal(appeal["id"], {"target_status": "OVERTURNED"}, ho)

    hh_after = validate_success(api.get_household(hh["id"], CW))
    assert hh_after["covered_member_months"] == fixed_member_months


def test_active_enrollment_count_conserved_terminate_then_reinstate():
    """PRD §2.6: "When an enrollment is activated ... the active count rises by
    one. When that enrollment is terminated ... the active count falls by one.
    When a terminated enrollment is reinstated through a successful appeal ... the
    active count rises by one again — restoring the earlier debit so that the
    ledger experiences net-zero drift across a termination-then-reinstatement
    cycle."

    Design: Difficulty/compensating_invariant/active_enrollment_count_conserved_terminate_then_reinstate
    """
    hh, enr, redet, appeal = setup_heard_appeal(state="CA", cw_id="cw-5", ho_id="ho-4")
    debited = validate_success(api.get_household(hh["id"], CW))
    assert debited["active_enrollment_count"] == 0  # decremented by termination

    ho = make_hearing_officer_headers("ho-4")
    api.rule_appeal(appeal["id"], {"target_status": "OVERTURNED"}, ho)

    hh_after = validate_success(api.get_household(hh["id"], CW))
    enr_after = validate_success(api.get_enrollment(enr["id"], CW))
    assert hh_after["active_enrollment_count"] == 1  # incremented back to 1
    assert enr_after["coverage_status"] == "ACTIVE"


def test_active_enrollment_count_matches_active_invariant_after_round_trip():
    """PRD §2.6: "The second invariant: `active_enrollment_count` always equals
    the count of the household's enrollments whose `coverage_status` is either
    `ACTIVE` or `IN_REDETERMINATION`."

    After the terminate-then-overturn round trip the single enrollment is ACTIVE
    again, so the count invariant holds at exactly 1.

    Design: Difficulty/compensating_invariant/active_enrollment_count_conserved_terminate_then_reinstate
    """
    hh, enr, redet, appeal = setup_heard_appeal(state="CA", cw_id="cw-66", ho_id="ho-22")
    ho = make_hearing_officer_headers("ho-22")
    api.rule_appeal(appeal["id"], {"target_status": "OVERTURNED"}, ho)

    enr_after = validate_success(api.get_enrollment(enr["id"], CW))
    hh_after = validate_success(api.get_household(hh["id"], CW))
    assert enr_after["coverage_status"] == "ACTIVE"
    # Exactly one ACTIVE/IN_REDETERMINATION enrollment → count == 1.
    assert hh_after["active_enrollment_count"] == 1
