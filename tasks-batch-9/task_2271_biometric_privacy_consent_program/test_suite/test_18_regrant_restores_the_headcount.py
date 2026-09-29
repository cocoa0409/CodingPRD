"""The enrolled headcount is conserved across a revoke-and-regrant cycle.

Revoking drops the individual out of the enrolled tally and hands them a manual
process; granting afresh restores the tally to exactly one and closes the manual
process rather than leaving both standing.
"""

from test_helpers import (
    HR_ADMIN,
    PRIVACY_OFFICER,
    accommodations_for_consent,
    assert_asset_state,
    assert_instant_equals,
    assert_program_state,
    baseline_with_granted_consent,
    read_asset,
    read_program,
    read_subject,
    validate_success,
)

REVOCATION = {"to_status": "REVOKED", "revocation_reason": "employee withdrew consent"}
REGRANT = {
    "to_status": "GRANTED",
    "written_release_acknowledged": True,
    "signature_ref": "sig-emp1-r2",
}


def _enrolled_employee_at_a_live_timekeeping_point(api):
    """One enrolled employee, with the clock held at the grant instant."""
    return baseline_with_granted_consent(api, activation_clock="2026-08-15T00:00:00Z")


def test_revoking_drops_the_headcount_and_hands_over_a_manual_process(api):
    """The revocation both decrements the tally and compensates the individual.

    PRD §3.6: "It then decrements the point's `enrolled_subject_count`, recomputes
    its `consent_gap_count`, re-derives the subject's `enrollment_status` to
    `OPTED_OUT`, and recomputes the program's `consent_gap_count` and `posture`."

    A revoked record is a lawful outcome and not a gap, so the point still shows a
    zero gap immediately after the revocation; the gap only opens when the officer
    puts the individual back into the re-solicitation loop, which restricts the
    program.

    Design: Difficulty/compensating_invariant/regranting_consent_ends_the_auto_accommodation_and_restores_enrollment_count
    """
    ctx = _enrolled_employee_at_a_live_timekeeping_point(api)
    assert_asset_state(
        read_asset(api, ctx["asset_id"]), enrolled_subject_count=1, consent_gap_count=0
    )
    assert_program_state(read_program(api, ctx["program_id"]), posture="OPEN")
    assert_instant_equals(
        ctx["consent"]["record_retention_until"], "2029-08-14T00:00:00.000Z", "record_retention_until"
    )

    validate_success(api.transition_consent_record(ctx["consent_id"], REVOCATION, HR_ADMIN))

    assert_asset_state(read_asset(api, ctx["asset_id"]), enrolled_subject_count=0)
    rows = accommodations_for_consent(api, ctx["consent_id"])
    assert len(rows) == 1
    assert rows[0]["origin"] == "AUTO_REVOKE"
    assert rows[0]["status"] == "REQUESTED"
    assert read_subject(api, ctx["subject_id"])["enrollment_status"] == "OPTED_OUT"

    validate_success(
        api.transition_consent_record(
            ctx["consent_id"], {"to_status": "RESOLICIT_REQUIRED"}, PRIVACY_OFFICER
        )
    )

    assert_asset_state(read_asset(api, ctx["asset_id"]), consent_gap_count=1)
    assert_program_state(read_program(api, ctx["program_id"]), posture="RESTRICTED")


def test_regranting_restores_the_headcount_to_one_and_ends_the_accommodation(api):
    """The tally comes back to exactly one and the bypass is closed out.

    PRD §3.6: "As a compensating action, every accommodation whose
    `created_from_consent_id` is this record and whose status is `REQUESTED`,
    `PROVISIONED` or `ACTIVE` transitions to `ENDED`, so that an individual who
    declined, was given a manual workaround, and later changed their mind does not
    retain both an enrollment and a bypass; this restores the point's
    `enrolled_subject_count` to its pre-decline value."

    The clock never moves, so the fresh grant re-stamps the same three-year record
    retention date, and the individual has now been asked twice.

    Design: Difficulty/compensating_invariant/regranting_consent_ends_the_auto_accommodation_and_restores_enrollment_count
    """
    ctx = _enrolled_employee_at_a_live_timekeeping_point(api)
    first_round = ctx["consent"]["solicitation_round"]

    validate_success(api.transition_consent_record(ctx["consent_id"], REVOCATION, HR_ADMIN))
    validate_success(
        api.transition_consent_record(
            ctx["consent_id"], {"to_status": "RESOLICIT_REQUIRED"}, PRIVACY_OFFICER
        )
    )
    resolicited = validate_success(
        api.transition_consent_record(ctx["consent_id"], {"to_status": "SOLICITED"}, HR_ADMIN)
    )
    assert resolicited["solicitation_round"] == first_round + 1

    regranted = validate_success(
        api.transition_consent_record(ctx["consent_id"], REGRANT, HR_ADMIN)
    )

    assert regranted["status"] == "GRANTED"
    assert regranted["solicitation_round"] == first_round + 1
    assert_instant_equals(
        regranted["record_retention_until"], "2029-08-14T00:00:00.000Z", "record_retention_until"
    )
    assert_asset_state(
        read_asset(api, ctx["asset_id"]), enrolled_subject_count=1, consent_gap_count=0
    )

    rows = accommodations_for_consent(api, ctx["consent_id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "ENDED", "the bypass created by the revocation is closed out"

    subject = read_subject(api, ctx["subject_id"])
    assert subject["active_accommodation_count"] == 0
    assert subject["enrollment_status"] == "ENROLLED"
    assert_program_state(read_program(api, ctx["program_id"]), posture="OPEN")
