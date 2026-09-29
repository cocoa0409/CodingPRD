"""Every derived number is already settled in the body that caused it.

One case is carried from a nurse's acceptance to a logged home visit, and after
each mutation the response itself is checked before anything is re-read: the
acceptance already carries the entitlement it just resolved, the finalization
already carries the score, the band and the sixty-day expiry, the acceptance of an
assignment already carries the allocated minutes, and the log already carries the
rounded credit. Each following read of the parent case, the teacher, the ledger
and the funding summary returns exactly what the mutating response implied, with
no intermediate value visible anywhere in between.
"""

from test_helpers import (
    CM_HEADERS,
    DEFAULT_TEACHER,
    MIDDLE_IN_HOME_RULE,
    PA_HEADERS,
    accept_assignment,
    activate_case,
    api_client,
    entries_for_session,
    log_session_delivered,
    open_case,
    propose_assignment,
    publish_entitlement_rule,
    read_case,
    read_teacher,
    record_safety_review,
    register_student,
    register_teacher,
    review_certification,
    schedule_session,
    set_clock,
    submit_certification,
    validate_success,
)

CLOCK = "2026-09-01T00:00:00Z"
ACTIVATION_CLOCK = "2026-09-07T08:00:00Z"
SERVICE_CLOCK = "2026-09-08T12:00:00Z"

CERT_WINDOW = {
    "expected_absence_days": 30,
    "certified_start_date": "2026-09-07",
    "certified_end_date": "2026-10-07",
    "signature_date": "2026-09-01",
}

ESCORTED_SAFETY_REVIEW = {
    "evidence_source": "ONSITE_WALKTHROUGH",
    "review_date": "2026-09-02",
    "hazard_findings": ["AGGRESSIVE_ANIMAL", "UNLIT_ACCESS"],
    "escort_available": True,
}


class TestNoReadAfterWriteLagAnywhereInTheChain:
    """Four mutations, each answering with the values its own rules produced."""

    def test_each_mutating_response_already_carries_what_the_next_read_reports(self):
        """The nurse's acceptance answers with an accepted, current certification and the
        case read straight afterwards already names the resolved rule and the 390-minute
        entitlement. The finalization answers with the escort-mitigated score, its band and
        its expiry, and the case read straight afterwards already requires an escort, which
        is why the very next scheduling call has to confirm one. The assignment acceptance
        answers with the allocated minutes and the teacher read straight afterwards already
        carries the same aggregate. The log answers with the rounded credit and both the
        ledger row and the funding summary read straight afterwards already agree with it.

        The PRD states: "When a rule's inputs change, the server recomputes the derived
        field, re-evaluates any guard that reads it, and applies the resulting
        transition inside the same request — the client sees the settled result, not an
        intermediate one."

        The PRD states: "On acceptance the certification's `status` becomes `ACCEPTED`
        and its `is_current` becomes true, and any certification of the same case that
        previously held `is_current` true is moved to `SUPERSEDED` with its `is_current`
        set false; exactly one accepted certification per case is current at any
        moment."

        The PRD states: "Next the case's `entitlement_rule_id` is resolved by matching
        the student's `grade_band` and the case's `delivery_mode` against the
        `PUBLISHED` entitlement catalogue, failing with
        `ERR_NO_PUBLISHED_ENTITLEMENT_RULE` if no such rule exists."

        The PRD states: "Take that rule's `base_weekly_minutes` and multiply it by a
        diagnosis factor determined by the case's `diagnosis_category`: the factor is
        1.00 for `MEDICAL_ACUTE`, 1.00 for `MEDICAL_CHRONIC`, 0.80 for `PSYCHIATRIC`,
        0.90 for `PREGNANCY_POSTPARTUM`, and 1.00 for `INJURY_REHAB`."

        The PRD states: "An effective duration of at least 60 calendar days earns a
        bonus of 60 minutes; failing that, an effective duration of at least 30 calendar
        days earns a bonus of 30 minutes; a shorter effective duration earns no bonus."

        The PRD states: "The server also derives `expires_on` as the `review_date`
        advanced by sixty days, and computes an initial `risk_score`."

        The PRD states: "The risk score begins as the sum of hazard weights over the
        review's distinct findings: `AGGRESSIVE_ANIMAL` weighs 25 points,
        `NO_SECONDARY_EXIT` 15, `WEAPON_PRESENT_UNSECURED` 40, `SMOKE_OR_AIR_QUALITY`
        10, `ACTIVE_INFECTION_RISK` 30, `UNLIT_ACCESS` 5, and `NO_ADULT_PRESENT` 20."

        The PRD states: "Under `ONSITE_VERIFIED`, the raw sum is used undiscounted, a
        flat 10 points of escort mitigation is subtracted when `escort_available` is
        true and nothing is subtracted when it is false, the result is floored at 0, and
        it is capped at 100."

        The PRD states: "`clearance` is banded from `risk_score` with inclusive lower
        bounds: `BLOCKED` at 60 points or above, otherwise `VIRTUAL_ONLY` at 35 points
        or above, otherwise `CLEARED_WITH_ESCORT` at 15 points or above, otherwise
        `CLEARED`."

        The PRD states: "Finalization refreshes the case's `escort_required`, setting it
        true when the resulting `clearance` is `CLEARED_WITH_ESCORT` and false
        otherwise, and increments the case's `version` by one."

        The PRD states: "On a successful acceptance the case's weekly allocation is
        recomputed across its active assignments including the new one, and every
        teacher whose allocation changed has `committed_weekly_minutes` and `over_cap`
        recomputed."

        The PRD states: "`credited_minutes` is computed from the rule the case's
        `entitlement_rule_id` names: take the lesser of the reported `actual_minutes`
        and the rule's `max_session_minutes`; multiply that capped figure by 0.90 when
        the session's `delivery_mode` is `VIRTUAL_SYNC` and leave it unchanged when the
        mode is `IN_HOME`; then divide by five, round half up to a whole number, and
        multiply back by five."

        The PRD states: "A ledger row is appended carrying `attendance_code`
        `HB_PRESENT` when the session's `delivery_mode` is `IN_HOME` and
        `HB_VIRTUAL_PRESENT` when it is `VIRTUAL_SYNC`, with `apportionment_minutes`
        equal to the session's `credited_minutes`."

        The PRD states: "The final input set is that case's sessions whose `status` is
        `DELIVERED` *and* which carry a non-null `verified_at`, whose `service_date`
        falls between `service_start_date` and `certified_end_date` inclusive on both
        ends."

        The PRD states: "Each `DELIVERED` session contributes its `credited_minutes`."

        Design: Corner/consistency_model/every_derived_value_is_already_correct_in_the_mutating_response
        """
        set_clock(CLOCK)
        rule = publish_entitlement_rule(**MIDDLE_IN_HOME_RULE)
        student = register_student()
        teacher = register_teacher(**DEFAULT_TEACHER)
        case_id = open_case(student["id"])["id"]
        certification = submit_certification(case_id, **CERT_WINDOW)
        assert certification["status"] == "SUBMITTED"

        accepted = review_certification(certification["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"
        assert accepted["is_current"] is True, (
            "the accepted document is the current one in the very body that accepts it"
        )
        eligible = read_case(case_id)
        assert eligible["service_status"] == "ELIGIBLE"
        assert eligible["entitlement_rule_id"] == rule["id"], (
            "the rule was resolved during the acceptance, not on a later write"
        )
        assert eligible["weekly_entitled_minutes"] == 390, (
            "360 base minutes at the 1.00 factor for MEDICAL_ACUTE plus the 30-minute "
            "bonus a 30-day expected absence earns"
        )

        review = record_safety_review(case_id, **ESCORTED_SAFETY_REVIEW)
        assert review["clearance"] == "PENDING", "a draft review governs nothing yet"
        finalized = validate_success(
            api_client.finalize_safety_review(review["id"], CM_HEADERS)
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["risk_score"] == 20, (
            "25 for the animal and 5 for the unlit access, less the flat 10 points an "
            "available escort mitigates under the on-site variant"
        )
        assert finalized["clearance"] == "CLEARED_WITH_ESCORT", (
            "20 points clears the 15-point escort band without reaching the 35-point "
            "virtual-only band"
        )
        assert finalized["expires_on"] == "2026-11-01", (
            "the review date of 2026-09-02 advanced by sixty days"
        )
        assert read_case(case_id)["escort_required"] is True, (
            "the band the finalization just derived is already binding on the case"
        )

        proposed = propose_assignment(case_id, "PRIMARY", teacher["id"])
        assert proposed["weekly_committed_minutes"] == 0, (
            "a proposal commits nothing until the teacher answers it"
        )
        accepted_assignment = accept_assignment(proposed["id"], teacher["id"])
        assert accepted_assignment["status"] == "ACTIVE"
        assert accepted_assignment["weekly_committed_minutes"] == 390, (
            "the sole active assignment carries the whole weekly entitlement"
        )
        committed_teacher = read_teacher(teacher["id"])
        assert committed_teacher["committed_weekly_minutes"] == 390, (
            "the aggregate was re-summed inside the acceptance"
        )
        assert committed_teacher["over_cap"] is False, (
            "390 committed minutes sit well under the 1200-minute contractual ceiling"
        )

        set_clock(ACTIVATION_CLOCK)
        activate_case(case_id)
        session = schedule_session(
            case_id,
            accepted_assignment["id"],
            scheduled_start="2026-09-08T09:00:00Z",
            scheduled_end="2026-09-08T10:58:00Z",
            escort_confirmed=True,
        )
        assert session["scheduled_minutes"] == 118
        assert session["credited_minutes"] == 0, "a scheduled visit has earned nothing"

        set_clock(SERVICE_CLOCK)
        logged = log_session_delivered(session["id"], teacher["id"], 118)
        assert logged["status"] == "DELIVERED"
        assert logged["credited_minutes"] == 120, (
            "118 minutes are under the 120-minute session ceiling and round half up "
            "to the nearest five as 120"
        )

        rows = entries_for_session(session["id"])
        assert len(rows) == 1, "one logged outcome writes exactly one ledger row"
        assert rows[0]["attendance_code"] == "HB_PRESENT"
        assert rows[0]["apportionment_minutes"] == 120, (
            "the ledger row already carries the credit the log response reported"
        )

        summary = validate_success(api_client.get_funding_summary(case_id, PA_HEADERS))
        assert summary["reported_apportionment_minutes"] == 120
        assert summary["provisional_minutes"] == 120, (
            "the delivered visit contributes its credited minutes to the forward-looking "
            "variant"
        )
        assert summary["final_verified_minutes"] == 0, (
            "nobody has verified the visit, so the narrower variant sees nothing"
        )
        assert summary["service_gap_minutes"] == 0, (
            "no whole seven-day span has closed since service started on 2026-09-07"
        )
