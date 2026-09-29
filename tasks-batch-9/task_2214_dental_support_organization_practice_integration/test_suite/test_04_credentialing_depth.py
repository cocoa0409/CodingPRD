"""Credentialing depth: the referential check that outranks the lead-time
check, the ninety-day lead-time boundary, the posture gate over fee-schedule
activation, the denial-dominates rollup and the half-open participation
interval."""

import pytest

from test_helpers import (
    LEAD,
    ApiErrorId,
    activate_fee_schedule,
    api_client,
    approve_enrollment,
    assert_credentialing_rollup,
    assert_practice,
    build_closed_deal,
    build_contract_ready_for_activation,
    build_priced_contract,
    build_scheduled_batch,
    create_payer_enrollment,
    create_payer_enrollment_payload,
    deny_enrollment,
    read_employment,
    read_payer_contract,
    read_payer_enrollment,
    read_practice,
    remediate_batch,
    set_clock,
    submit_enrollment,
    validate_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

SUBMIT_CLOCK = "2026-11-15T00:00:00Z"
NINETY_DAY_EFFECTIVE = "2027-02-13T00:00:00Z"
EIGHTY_NINE_DAY_EFFECTIVE = "2027-02-12T00:00:00Z"
D0120_LINE_IMPACT = -39_195


def test_unapproved_enrollment_is_reported_before_the_short_lead_time():
    """PRD §2.11: "The payer contract has at least one enrollment and all of them are approved — `ERR_ENROLLMENTS_NOT_APPROVED` (422). Deliberately ordered above the lead-time check at position 34, so that a contract that is both un-credentialed and short on lead time reports the referential failure."

    Design: Difficulty/priority_pair_validation_conflict/enrollments_not_approved_beats_credentialing_lead_time_short
    """
    ctx = build_closed_deal()
    contract, enrollment = build_contract_ready_for_activation(
        ctx,
        lead_effective_date=EIGHTY_NINE_DAY_EFFECTIVE,
        submit_clock=SUBMIT_CLOCK,
    )
    assert enrollment["status"] == "SUBMITTED"
    assert enrollment["lead_days"] == 89

    validate_error(
        activate_fee_schedule(contract["id"], NINETY_DAY_EFFECTIVE),
        ApiErrorId.ERR_ENROLLMENTS_NOT_APPROVED.value,
    )
    unchanged = read_payer_contract(contract["id"])
    assert unchanged["transition_state"] == "PENDING_CREDENTIALING"
    assert unchanged["dso_schedule_effective_date"] is None


def test_short_lead_time_surfaces_only_once_every_enrollment_is_approved():
    """PRD §3.6: "every enrollment of the contract must show `lead_days` of at least 90 whole days, where exactly 90 passes and 89 fails with `ERR_CREDENTIALING_LEAD_TIME_SHORT`"
    PRD §3.6: "Because the all-approved check sits above the lead-time check, a contract that is simultaneously un-credentialed and short on lead time reports the referential failure rather than the temporal one."

    Design: Difficulty/priority_pair_validation_conflict/enrollments_not_approved_beats_credentialing_lead_time_short
    """
    ctx = build_closed_deal()
    contract, enrollment = build_contract_ready_for_activation(
        ctx,
        lead_effective_date=EIGHTY_NINE_DAY_EFFECTIVE,
        submit_clock=SUBMIT_CLOCK,
    )
    approved = approve_enrollment(enrollment["id"])
    assert approved["status"] == "APPROVED"

    validate_error(
        activate_fee_schedule(contract["id"], NINETY_DAY_EFFECTIVE),
        ApiErrorId.ERR_CREDENTIALING_LEAD_TIME_SHORT.value,
    )
    unchanged = read_payer_contract(contract["id"])
    assert unchanged["transition_state"] == "PENDING_CREDENTIALING"
    assert unchanged["dso_schedule_effective_date"] is None
    assert unchanged["blended_impact_cents"] == D0120_LINE_IMPACT


def test_lead_time_of_exactly_ninety_days_activates_the_dso_schedule():
    """PRD §3.6: "**Activating the DSO fee schedule** carries a contract `PENDING_CREDENTIALING → DSO_SCHEDULE_ACTIVE` and stores the contracted `dso_schedule_effective_date`."
    PRD §3.6: "every enrollment of the contract must show `lead_days` of at least 90 whole days, where exactly 90 passes and 89 fails with `ERR_CREDENTIALING_LEAD_TIME_SHORT`"

    Design: Difficulty/boundary_precision_check/credentialing_lead_time_at_exactly_ninety_days
    """
    ctx = build_closed_deal()
    contract, enrollment = build_contract_ready_for_activation(
        ctx,
        lead_effective_date=NINETY_DAY_EFFECTIVE,
        submit_clock=SUBMIT_CLOCK,
        payer_name="Statewide Dental Plan",
    )
    assert enrollment["lead_days"] == 90
    approve_enrollment(enrollment["id"])

    activated = validate_success(
        activate_fee_schedule(contract["id"], NINETY_DAY_EFFECTIVE)
    )
    assert activated["transition_state"] == "DSO_SCHEDULE_ACTIVE"
    assert activated["dso_schedule_effective_date"] == NINETY_DAY_EFFECTIVE
    assert activated["blended_impact_cents"] == D0120_LINE_IMPACT


def test_lead_time_of_eighty_nine_days_fails_the_same_activation():
    """PRD §3.6: "`lead_days` is the whole-day gap between submission and the requested participation start: the difference between `effective_date` and `submitted_at` divided by 86,400 seconds, taking the floor."
    PRD §3.6: "every enrollment of the contract must show `lead_days` of at least 90 whole days, where exactly 90 passes and 89 fails with `ERR_CREDENTIALING_LEAD_TIME_SHORT`"

    Design: Difficulty/boundary_precision_check/credentialing_lead_time_at_exactly_ninety_days
    """
    ctx = build_closed_deal()
    passing, passing_enrollment = build_contract_ready_for_activation(
        ctx,
        lead_effective_date=NINETY_DAY_EFFECTIVE,
        submit_clock=SUBMIT_CLOCK,
        payer_name="Statewide Dental Plan",
    )
    failing = build_priced_contract(
        ctx["practice_id"], lines=[{}], payer_name="Lakeside Dental Benefits"
    )
    failing_enrollment = create_payer_enrollment(
        failing["id"], ctx["employment_id"], EIGHTY_NINE_DAY_EFFECTIVE
    )
    submit_enrollment(failing_enrollment["id"])
    approve_enrollment(passing_enrollment["id"])
    approve_enrollment(failing_enrollment["id"])

    assert read_payer_enrollment(passing_enrollment["id"])["lead_days"] == 90
    assert read_payer_enrollment(failing_enrollment["id"])["lead_days"] == 89

    activated = validate_success(
        activate_fee_schedule(passing["id"], NINETY_DAY_EFFECTIVE)
    )
    assert activated["transition_state"] == "DSO_SCHEDULE_ACTIVE"

    validate_error(
        activate_fee_schedule(failing["id"], NINETY_DAY_EFFECTIVE),
        ApiErrorId.ERR_CREDENTIALING_LEAD_TIME_SHORT.value,
    )
    blocked = read_payer_contract(failing["id"])
    assert blocked["transition_state"] == "PENDING_CREDENTIALING"
    assert blocked["dso_schedule_effective_date"] is None


@pytest.fixture
def credentialed_contract_with_quarantine():
    """An approved contract at a practice demoted by one quarantined batch."""
    ctx = build_closed_deal()
    contract, enrollment = build_contract_ready_for_activation(
        ctx,
        lead_effective_date=NINETY_DAY_EFFECTIVE,
        submit_clock=SUBMIT_CLOCK,
    )
    approve_enrollment(enrollment["id"])
    batch = build_scheduled_batch(
        ctx["practice_id"],
        "2026-11-20T00:00:00Z",
        "2026-11-21T00:00:00Z",
        batch_label="CHART-WAVE-1",
    )
    set_clock("2026-11-20T00:00:00Z")
    ctx["batch"] = validate_batch(batch["id"], 101)
    ctx["batch_id"] = batch["id"]
    ctx["contract"] = contract
    ctx["enrollment"] = enrollment
    return ctx


def test_quarantined_batch_posture_blocks_fee_schedule_activation(
    credentialed_contract_with_quarantine
):
    """PRD §2.6: "Scheduling a cutover, activating a fee schedule, finalizing a consolidation, standardizing staffing and harmonizing compensation all require the practice to be `STABILIZING` or `INTEGRATED`; a posture of `PRE_CLOSE`, `RESTRICTED` or `FROZEN` rejects them with `ERR_PRACTICE_POSTURE_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/quarantined_batch_posture_blocks_payer_contract_activation
    """
    ctx = credentialed_contract_with_quarantine
    practice = read_practice(ctx["practice_id"])
    assert practice["quarantined_batch_count"] == 1
    assert practice["integration_posture"] == "RESTRICTED"
    assert_practice(practice)

    validate_error(
        activate_fee_schedule(ctx["contract"]["id"], NINETY_DAY_EFFECTIVE),
        ApiErrorId.ERR_PRACTICE_POSTURE_BLOCKED.value,
    )
    blocked = read_payer_contract(ctx["contract"]["id"])
    assert blocked["transition_state"] == "PENDING_CREDENTIALING"
    assert blocked["dso_schedule_effective_date"] is None
    assert read_payer_enrollment(ctx["enrollment"]["id"])["status"] == "APPROVED"


def test_remediating_the_batch_releases_the_blocked_activation(
    credentialed_contract_with_quarantine
):
    """PRD §3.5: "decrements the practice's `quarantined_batch_count` by one and recomputes the posture — which carries the practice `RESTRICTED → STABILIZING` when that batch was the last blocker and at least one doctor remains active and the practice has not yet migrated all its expected charts"
    PRD §3.6: "the practice's posture must be `STABILIZING` or `INTEGRATED`; `fee_schedule_item_count` must be at least one, or the request is refused with `ERR_FEE_SCHEDULE_EMPTY`"

    Design: Difficulty/cross_entity_state_dependency/quarantined_batch_posture_blocks_payer_contract_activation
    """
    ctx = credentialed_contract_with_quarantine
    remediated = remediate_batch(
        ctx["batch_id"], remediation_note="re-extract accepted by vendor"
    )
    assert remediated["status"] == "SCHEDULED"

    practice = read_practice(ctx["practice_id"])
    assert practice["quarantined_batch_count"] == 0
    assert practice["integration_posture"] == "STABILIZING"

    activated = validate_success(
        activate_fee_schedule(ctx["contract"]["id"], NINETY_DAY_EFFECTIVE)
    )
    assert activated["transition_state"] == "DSO_SCHEDULE_ACTIVE"
    assert activated["dso_schedule_effective_date"] == NINETY_DAY_EFFECTIVE
    assert activated["blended_impact_cents"] == D0120_LINE_IMPACT


@pytest.fixture
def two_submitted_enrollments():
    """One employment credentialed against two contracts, both submitted."""
    ctx = build_closed_deal()
    first = build_priced_contract(
        ctx["practice_id"], lines=[{}], payer_name="Statewide Dental Plan"
    )
    second = build_priced_contract(
        ctx["practice_id"], lines=[{}], payer_name="Lakeside Dental Benefits"
    )
    ctx["first_contract"] = first
    ctx["second_contract"] = second
    ctx["first_enrollment"] = create_payer_enrollment(
        first["id"], ctx["employment_id"], NINETY_DAY_EFFECTIVE
    )
    ctx["second_enrollment"] = create_payer_enrollment(
        second["id"], ctx["employment_id"], NINETY_DAY_EFFECTIVE
    )
    set_clock(SUBMIT_CLOCK)
    submit_enrollment(ctx["first_enrollment"]["id"])
    submit_enrollment(ctx["second_enrollment"]["id"])
    return ctx


def test_one_denial_dominates_any_number_of_approvals(two_submitted_enrollments):
    """PRD §3.4: "The precedence ladder is: if the employment has no enrollments at all, the rollup is `PENDING`; otherwise, if any one enrollment is `DENIED`, the rollup is `DENIED`; otherwise, if every enrollment is `APPROVED`, the rollup is `APPROVED`; otherwise, if any enrollment is `SUBMITTED`, the rollup is `SUBMITTED`; otherwise the rollup is `PENDING`."
    PRD §3.4: "A single denial therefore dominates any number of approvals, because the denial clause is evaluated before the all-approved clause."

    Design: Difficulty/cross_entity_state_dependency/enrollment_denial_dominates_employment_credentialing_rollup
    """
    ctx = two_submitted_enrollments
    assert_credentialing_rollup(
        read_employment(ctx["employment_id"]), ["SUBMITTED", "SUBMITTED"]
    )

    approve_enrollment(ctx["first_enrollment"]["id"])
    assert_credentialing_rollup(
        read_employment(ctx["employment_id"]), ["APPROVED", "SUBMITTED"]
    )

    deny_enrollment(ctx["second_enrollment"]["id"], "roster attestation missing")
    employment = read_employment(ctx["employment_id"])
    assert employment["credentialing_status"] == "DENIED"
    assert_credentialing_rollup(employment, ["APPROVED", "DENIED"])

    practice = read_practice(ctx["practice_id"])
    assert practice["denied_enrollment_count"] == 1
    assert practice["integration_posture"] == "RESTRICTED"
    assert_practice(practice)


def test_resubmission_clears_the_denial_from_the_rollup_and_the_posture(
    two_submitted_enrollments
):
    """PRD §3.6: "A resubmission after denial is the same operation traversing the cycle edge `DENIED → SUBMITTED`: it additionally clears `denial_reason`, decrements the practice's `denied_enrollment_count` by one alongside incrementing `pending_credentialing_count`, and then recomputes the posture — which carries the practice `RESTRICTED → STABILIZING` when that denial was the last blocker — incrementing the practice's `version` as well."

    Design: Difficulty/cross_entity_state_dependency/enrollment_denial_dominates_employment_credentialing_rollup
    """
    ctx = two_submitted_enrollments
    approve_enrollment(ctx["first_enrollment"]["id"])
    deny_enrollment(ctx["second_enrollment"]["id"], "roster attestation missing")

    resubmitted = submit_enrollment(ctx["second_enrollment"]["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["denial_reason"] is None
    assert resubmitted["submission_round"] == 2

    employment = read_employment(ctx["employment_id"])
    assert_credentialing_rollup(employment, ["APPROVED", "SUBMITTED"])
    practice = read_practice(ctx["practice_id"])
    assert practice["denied_enrollment_count"] == 0
    assert practice["integration_posture"] == "STABILIZING"

    approve_enrollment(ctx["second_enrollment"]["id"])
    final_employment = read_employment(ctx["employment_id"])
    assert final_employment["credentialing_status"] == "APPROVED"
    final_practice = read_practice(ctx["practice_id"])
    assert final_practice["pending_credentialing_count"] == 0
    assert final_practice["integration_posture"] == "STABILIZING"


def test_participation_intervals_may_abut_but_may_not_overlap():
    """PRD §3.6: "Participation intervals are half-open, running from `effective_date` inclusive to `term_date` exclusive, and no two enrollments for the same payer-contract-and-employment pair may overlap when the existing one is `SUBMITTED` or `APPROVED`; adjacency is fine, so a new interval starting exactly at an existing interval's `term_date` is accepted, while a genuine overlap is refused with `ERR_ENROLLMENT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/enrollment_half_open_interval_adjacency_and_occupancy_set
    """
    ctx = build_closed_deal()
    contract = build_priced_contract(ctx["practice_id"], lines=[{}])

    first = create_payer_enrollment(
        contract["id"],
        ctx["employment_id"],
        "2026-10-01T00:00:00Z",
        term_date="2027-01-01T00:00:00Z",
    )
    submit_enrollment(first["id"])
    approve_enrollment(first["id"])

    adjacent = create_payer_enrollment(
        contract["id"],
        ctx["employment_id"],
        "2027-01-01T00:00:00Z",
        term_date="2027-06-01T00:00:00Z",
    )
    assert adjacent["status"] == "NOT_STARTED"
    submitted = submit_enrollment(adjacent["id"])
    assert submitted["status"] == "SUBMITTED"

    validate_error(
        api_client.create_payer_enrollment(
            create_payer_enrollment_payload(
                contract["id"],
                ctx["employment_id"],
                "2027-05-01T00:00:00Z",
                term_date="2027-08-01T00:00:00Z",
            ),
            LEAD,
        ),
        ApiErrorId.ERR_ENROLLMENT_PERIOD_OVERLAP.value,
    )


def test_only_submitted_and_approved_rows_occupy_the_interval():
    """PRD §3.6: "Rows in `NOT_STARTED`, `DENIED` or `SUSPENDED` status are excluded from the occupancy set entirely."
    PRD §3.6: "an absent `term_date` means open-ended and is compared as `9999-12-31T00:00:00Z`"

    Design: Difficulty/resource_temporal_overlap/enrollment_half_open_interval_adjacency_and_occupancy_set
    """
    ctx = build_closed_deal()
    contract = build_priced_contract(ctx["practice_id"], lines=[{}])

    first = create_payer_enrollment(
        contract["id"],
        ctx["employment_id"],
        "2026-10-01T00:00:00Z",
        term_date="2027-01-01T00:00:00Z",
    )
    submit_enrollment(first["id"])
    approve_enrollment(first["id"])

    second = create_payer_enrollment(
        contract["id"],
        ctx["employment_id"],
        "2027-01-01T00:00:00Z",
        term_date="2027-06-01T00:00:00Z",
    )
    submit_enrollment(second["id"])
    deny_enrollment(second["id"], "duplicate roster row")

    third = create_payer_enrollment(
        contract["id"],
        ctx["employment_id"],
        "2027-05-01T00:00:00Z",
        term_date="2027-08-01T00:00:00Z",
    )
    assert third["status"] == "NOT_STARTED"

    fourth = create_payer_enrollment(
        contract["id"],
        ctx["employment_id"],
        "2027-06-01T00:00:00Z",
        term_date="2027-09-01T00:00:00Z",
    )
    assert fourth["status"] == "NOT_STARTED"

    rows, meta = validate_paginated(
        api_client.list_payer_enrollments(
            LEAD,
            {
                "payer_contract_id": contract["id"],
                "doctor_employment_id": ctx["employment_id"],
            },
        )
    )
    assert meta["total_count"] == 4
    approved = [row for row in rows if row["status"] == "APPROVED"]
    assert len(approved) == 1
    assert approved[0]["id"] == first["id"]
    assert read_payer_contract(contract["id"])["transition_state"] == (
        "PENDING_CREDENTIALING"
    )
