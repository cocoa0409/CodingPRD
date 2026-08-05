"""Verification schedule reset, overdue boundary, and the cascade it triggers."""
from test_helpers import (
    validate_success, get_success_data, assert_same_instant,
    setup_active_registrant, set_clock, record_verification, get_registrant,
    file_petition, get_petition, TEST_USERS,
)

OFFICER = TEST_USERS["registration_officer_headers"]


def test_recording_periodic_verification_resets_next_due(api):
    """PRD 3.4: "Recording a verification resets the schedule: the registrant's
    `last_verified_date` becomes that completed date, and `next_verification_due`
    is recomputed."
    PRD 3.4: "The `next_verification_due` is that anchor plus the registrant's
    `verification_interval_days`."

    Design: Corner/calculations/verification_reset_advances_next_due
    """
    jur, reg = setup_active_registrant()  # CLASS_B -> TIER_1 -> interval 365
    set_clock("2026-08-01T00:00:00Z")
    record_verification(reg["id"], verification_type="PERIODIC", officer_ref="off-9")
    refreshed = get_registrant(reg["id"])
    assert_same_instant(refreshed["last_verified_date"], "2026-08-01T00:00:00Z")
    assert_same_instant(refreshed["next_verification_due"], "2027-08-01T00:00:00Z")


def test_registrant_overdue_at_exact_due_plus_grace(api):
    """PRD 3.4: "A registrant is overdue once the clock reaches or passes the due
    date plus the owning jurisdiction's `verification_grace_days` — that is, the
    overdue condition holds when the clock is greater than or equal to
    `next_verification_due` plus the grace days."
    PRD 3.4: "If the registrant is overdue by the rule above, the check opens a
    `MAJOR` `LATE_VERIFICATION` compliance flag, which recomputes `risk_score` and
    may drive the registrant from `ACTIVE` to `DELINQUENT`".

    Design: Difficulty/boundary_precision_check/verification_overdue_at_exact_due_plus_grace
    """
    jur, reg = setup_active_registrant(jurisdiction_overrides={"verification_grace_days": 3})
    # next_verification_due = 2026-05-01 + 365 = 2027-05-01; +grace 3 => overdue at 2027-05-04.
    set_clock("2027-05-04T00:00:00Z")
    resp = api.verification_check(reg["id"], OFFICER)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "DELINQUENT"


def test_registrant_not_overdue_one_day_before_boundary(api):
    """PRD 3.4: "A registrant is overdue once the clock reaches or passes the due
    date plus the owning jurisdiction's `verification_grace_days` — that is, the
    overdue condition holds when the clock is greater than or equal to
    `next_verification_due` plus the grace days."

    Design: Difficulty/boundary_precision_check/verification_overdue_at_exact_due_plus_grace
    """
    jur, reg = setup_active_registrant(jurisdiction_overrides={"verification_grace_days": 3})
    # One day before the due+grace boundary (2027-05-03 < 2027-05-04): not overdue.
    set_clock("2027-05-03T00:00:00Z")
    resp = api.verification_check(reg["id"], OFFICER)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "ACTIVE"


def test_missed_verification_flips_registrant_delinquent(api):
    """PRD 3.4: "If the registrant is overdue by the rule above, the check opens a
    `MAJOR` `LATE_VERIFICATION` compliance flag, which recomputes `risk_score` and
    may drive the registrant from `ACTIVE` to `DELINQUENT` (and, as a consequence,
    deny any pending petition) exactly as described in Section 3.5."

    Design: Difficulty/transitive_cascade/missed_verification_cascades_to_petition_denial
    """
    jur, reg = setup_active_registrant(jurisdiction_overrides={"verification_grace_days": 3})
    file_petition(reg["id"], petition_type="DEREGISTER")
    set_clock("2027-05-04T00:00:00Z")
    resp = api.verification_check(reg["id"], OFFICER)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "DELINQUENT"


def test_missed_verification_denies_pending_petition(api):
    """PRD 3.5: "If the recomputed `risk_score` reaches or passes 15 while the
    registrant is `ACTIVE`, the registrant transitions `ACTIVE → DELINQUENT`; as a
    cascade, any petition of that registrant still in `PENDING` decision is
    transitioned to `DENIED` (its deregistration eligibility is lost) with its
    `decided_date` set to the clock."

    Design: Difficulty/transitive_cascade/missed_verification_cascades_to_petition_denial
    """
    jur, reg = setup_active_registrant(jurisdiction_overrides={"verification_grace_days": 3})
    pet = file_petition(reg["id"], petition_type="DEREGISTER")
    set_clock("2027-05-04T00:00:00Z")
    api.verification_check(reg["id"], OFFICER)
    decided = get_petition(pet["id"])
    assert decided["decision"] == "DENIED"
