"""Validation gates: the refusals that guard travel exceptions, the prescriber
chase, adjudication's cross-entity reference and the reissue window, plus the
precedence of authentication over an unknown path identifier.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    adjudicate_payload,
    api_client,
    assert_cycle_state,
    assert_line_state,
    assert_total_count,
    create_patient,
    create_plan,
    create_rx,
    decide_vacation,
    do_adjudicate,
    do_chase,
    do_respond,
    get_success_data,
    metformin_payload,
    open_authorization,
    ops_headers,
    oxycodone_payload,
    pharmacist_headers,
    read_cycle,
    read_lines,
    read_patient,
    read_prescription,
    refill_authorization_payload,
    reissue_payload,
    request_vacation,
    set_clock,
    setup_adjudicated_cycle,
    setup_draft_cycle,
    setup_rolled_cycle,
    setup_saturated_chase,
    validate_error,
    vacation_decision_payload,
    vacation_exception_payload,
)

CLOCK = "2026-08-10T00:00:00Z"
UNKNOWN_CYCLE_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_VACATION_ID = "11111111-1111-4111-8111-111111111111"


def _controlled_regimen_patient():
    """A patient holding one plain tablet and one ACTIVE controlled tablet."""
    set_clock(CLOCK)
    plan = create_plan(vacation_overrides_per_year=1, allows_payer_vacation_override=True)
    patient = create_patient(plan["id"])
    create_rx(patient["id"], metformin_payload)
    create_rx(
        patient["id"],
        lambda pid: oxycodone_payload(
            pid,
            refills_authorized=1,
            written_date="2026-07-01",
            expiration_date="2027-01-01",
            last_dispensed_date="2026-07-18",
            last_dispensed_days_supply=30,
        ),
    )
    return plan, patient


def _patient_with_one_tablet(**plan_overrides):
    """A patient with a single non-controlled tablet on a plan of the given shape."""
    set_clock(CLOCK)
    plan = create_plan(**plan_overrides)
    patient = create_patient(plan["id"])
    create_rx(patient["id"], metformin_payload)
    return plan, patient


def _held_auth_scenario():
    """An adjudicated cycle whose only line is on an authorization hold."""
    return setup_adjudicated_cycle(
        prescriptions=[lambda pid: metformin_payload(pid, refills_authorized=0)]
    )


class TestTravelExceptionDecisionGates:
    """Deciding a travel exception: the controlled-substance and payer-override gates."""

    @pytest.mark.parametrize("decision", ["APPROVE_PHARMACIST", "APPROVE_PAYER_OVERRIDE"])
    def test_active_controlled_prescription_blocks_both_approval_branches(self, decision):
        """An ACTIVE controlled drug in the regimen refuses either approving decision.

        If the decision is either approving kind and the patient has at least one prescription with `status` `ACTIVE` and `is_controlled` true, the decision fails with `ERR_CONTROLLED_SUBSTANCE_NO_OVERRIDE`. An active controlled substance blocks **both** approval branches, not merely the payer branch.
        The new request starts with `status` `SUBMITTED`, `approved_extra_days` null, `waives_refill_too_soon` false, `denial_reason` null, `decided_by_user_id` null, `decided_at` null and `version` 1.
        Both approvals raise the patient's `vacation_exceptions_used_this_year` by 1 and increment the patient's `version`.

        Design: Corner/validations/controlled_substance_blocks_any_vacation_override
        """
        plan, patient = _controlled_regimen_patient()
        assert plan["allows_payer_vacation_override"] is True
        exception = request_vacation(
            patient["id"],
            travel_start_date="2026-08-20",
            travel_end_date="2026-08-27",
            requested_extra_days=5,
        )

        response = api_client.decide_vacation_exception(
            exception["id"],
            vacation_decision_payload(decision, 5),
            pharmacist_headers("rph-01"),
        )

        validate_error(response, ApiErrorId.CONTROLLED_SUBSTANCE_NO_OVERRIDE)
        after = get_success_data(
            api_client.get_vacation_exception(exception["id"], pharmacist_headers())
        )
        assert after["status"] == "SUBMITTED"
        assert after["approved_extra_days"] is None
        assert after["decided_by_user_id"] is None
        assert after["version"] == 1
        assert read_patient(patient["id"])["vacation_exceptions_used_this_year"] == 0

    def test_payer_override_refused_when_plan_disallows_it(self):
        """A plan left at its default flag refuses the payer-override branch.

        If the decision is `APPROVE_PAYER_OVERRIDE` and the patient's plan has `allows_payer_vacation_override` false, the decision fails with `ERR_PAYER_OVERRIDE_NOT_ALLOWED`.
        The boolean `allows_payer_vacation_override` defaults to false, and when false the payer refuses payer-level travel overrides entirely, leaving only a pharmacist-level approval possible.
        The new request starts with `status` `SUBMITTED`, `approved_extra_days` null, `waives_refill_too_soon` false, `denial_reason` null, `decided_by_user_id` null, `decided_at` null and `version` 1.

        Design: Corner/validations/payer_override_refused_when_the_plan_disallows_it
        """
        plan, patient = _patient_with_one_tablet(vacation_overrides_per_year=1)
        assert plan["allows_payer_vacation_override"] is False
        exception = request_vacation(
            patient["id"],
            travel_start_date="2026-08-20",
            travel_end_date="2026-08-27",
            requested_extra_days=5,
        )

        response = api_client.decide_vacation_exception(
            exception["id"],
            vacation_decision_payload("APPROVE_PAYER_OVERRIDE", 5),
            pharmacist_headers("rph-01"),
        )

        validate_error(response, ApiErrorId.PAYER_OVERRIDE_NOT_ALLOWED)
        after = get_success_data(
            api_client.get_vacation_exception(exception["id"], pharmacist_headers())
        )
        assert after["status"] == "SUBMITTED"
        assert after["waives_refill_too_soon"] is False
        assert after["version"] == 1
        assert read_patient(patient["id"])["vacation_exceptions_used_this_year"] == 0

    def test_pharmacist_branch_of_the_same_request_is_legal(self):
        """The pharmacist branch of the very same request succeeds without the flag.

        If the decision is `APPROVE_PAYER_OVERRIDE` and the patient's plan has `allows_payer_vacation_override` false, the decision fails with `ERR_PAYER_OVERRIDE_NOT_ALLOWED`.
        `APPROVE_PHARMACIST` sets `status` `PHARMACIST_APPROVED`, stores `approved_extra_days` and leaves `waives_refill_too_soon` false: the exception extends the day-supply allowance but does **not** waive the payer's refill-too-soon edit.

        Design: Corner/validations/payer_override_refused_when_the_plan_disallows_it
        """
        _, patient = _patient_with_one_tablet(vacation_overrides_per_year=1)
        exception = request_vacation(
            patient["id"],
            travel_start_date="2026-08-20",
            travel_end_date="2026-08-27",
            requested_extra_days=5,
        )

        decided = decide_vacation(exception["id"], "APPROVE_PHARMACIST", 5)

        assert decided["status"] == "PHARMACIST_APPROVED"
        assert decided["approved_extra_days"] == 5
        assert decided["waives_refill_too_soon"] is False


class TestTravelExceptionYearlyAllowance:
    """Requesting a travel exception against the plan's per-year allowance."""

    def test_second_request_exceeds_the_yearly_allowance(self):
        """A decided first exception consumes the single funded override.

        The patient must also have an unused allowance: if `vacation_exceptions_used_this_year` is already greater than or equal to the plan's `vacation_overrides_per_year`, the request fails with `ERR_VACATION_LIMIT_EXCEEDED`.
        Both approvals raise the patient's `vacation_exceptions_used_this_year` by 1 and increment the patient's `version`.

        Design: Corner/validations/second_travel_request_exceeds_the_yearly_allowance
        """
        _, patient = _patient_with_one_tablet(vacation_overrides_per_year=1)
        first = request_vacation(
            patient["id"],
            travel_start_date="2026-08-20",
            travel_end_date="2026-08-27",
            requested_extra_days=5,
        )
        decided = decide_vacation(first["id"], "APPROVE_PHARMACIST", 5)
        assert decided["approved_extra_days"] == 5
        assert read_patient(patient["id"])["vacation_exceptions_used_this_year"] == 1

        response = api_client.create_vacation_exception(
            vacation_exception_payload(
                patient["id"],
                travel_start_date="2026-11-01",
                travel_end_date="2026-11-14",
                requested_extra_days=7,
            ),
            ops_headers(),
        )

        validate_error(response, ApiErrorId.VACATION_LIMIT_EXCEEDED)
        assert_total_count(
            api_client.list_vacation_exceptions(
                ops_headers(), {"patient_id": patient["id"]}
            ),
            1,
        )

    def test_wider_allowance_admits_the_second_request(self):
        """A plan funding two overrides accepts the identical second request.

        The patient must also have an unused allowance: if `vacation_exceptions_used_this_year` is already greater than or equal to the plan's `vacation_overrides_per_year`, the request fails with `ERR_VACATION_LIMIT_EXCEEDED`.
        The new request starts with `status` `SUBMITTED`, `approved_extra_days` null, `waives_refill_too_soon` false, `denial_reason` null, `decided_by_user_id` null, `decided_at` null and `version` 1.

        Design: Corner/validations/second_travel_request_exceeds_the_yearly_allowance
        """
        _, patient = _patient_with_one_tablet(vacation_overrides_per_year=2)
        first = request_vacation(
            patient["id"],
            travel_start_date="2026-08-20",
            travel_end_date="2026-08-27",
            requested_extra_days=5,
        )
        decide_vacation(first["id"], "APPROVE_PHARMACIST", 5)

        second = request_vacation(
            patient["id"],
            travel_start_date="2026-11-01",
            travel_end_date="2026-11-14",
            requested_extra_days=7,
        )

        assert second["status"] == "SUBMITTED"
        assert second["version"] == 1


class TestAdjudicationVacationReference:
    """Adjudication reading a travel exception named in its body."""

    def test_undecided_travel_exception_is_refused(self):
        """A SUBMITTED travel exception cannot be consumed by adjudication.

        When `vacation_exception_id` is supplied, the referenced travel exception's `patient_id` must equal the cycle's `patient_id` and its `status` must be `PHARMACIST_APPROVED` or `PAYER_OVERRIDE_APPROVED`, otherwise `ERR_NO_APPROVED_VACATION_EXCEPTION`.
        Cascades are never partial: if a validation rejects a request, no part of its cascade is applied.
        The new cycle is created with `cycle_end_date` computed as `cycle_start_date` advanced by `day_supply_days` days, exclusive; `packaging_status` `DRAFT`; `insurance_status` `NOT_ADJUDICATED`; `is_partial_reissue` false; `reissue_of_cycle_id` null; `vacation_exception_id` null; `approved_vacation_extra_days` 0; `reissue_required` false; `roll_pouch_count` 0; `total_copay_cents` 0; `final_copay_cents` null; `reissue_fee_cents` 0; `credit_applied_cents` 0; `rounding_delta_cents` null; and `version` 1.
        Each staged line records its `cycle_id` and `prescription_id` and starts with `line_status` `PLANNED`, `hold_reason` null, and every computed figure at its zero default — `days_supply_filled`, `bridge_days_applied`, `trim_days_applied`, `quantity_dispensed`, `refill_pct_used`, `allowance_days` and `copay_cents` all 0, with `packable_route`, `line_start_date` and `line_end_date` not yet determined.

        Design: Corner/validations/adjudicate_with_an_undecided_vacation_exception_rejected
        """
        scenario = setup_draft_cycle(
            plan_overrides={"vacation_overrides_per_year": 1},
            cycle_start_date="2026-08-15",
            day_supply_days=28,
        )
        exception = request_vacation(
            scenario.patient_id,
            travel_start_date="2026-08-20",
            travel_end_date="2026-08-27",
            requested_extra_days=5,
        )
        assert exception["status"] == "SUBMITTED"

        response = api_client.adjudicate_fill_cycle(
            scenario.cycle_id,
            pharmacist_headers(),
            adjudicate_payload(vacation_exception_id=exception["id"]),
        )

        validate_error(response, ApiErrorId.NO_APPROVED_VACATION_EXCEPTION)
        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(
            cycle,
            packaging_status="DRAFT",
            insurance_status="NOT_ADJUDICATED",
            version=1,
        )
        assert cycle["total_copay_cents"] == 0
        assert cycle["approved_vacation_extra_days"] == 0
        lines = read_lines(scenario.cycle_id)
        assert_line_state(lines[0], line_status="PLANNED")

    def test_approved_travel_exception_widens_the_allowance(self):
        """Once the pharmacist approves it, the identical adjudication succeeds.

        When `vacation_exception_id` is supplied, the referenced travel exception's `patient_id` must equal the cycle's `patient_id` and its `status` must be `PHARMACIST_APPROVED` or `PAYER_OVERRIDE_APPROVED`, otherwise `ERR_NO_APPROVED_VACATION_EXCEPTION`.
        When a valid `vacation_exception_id` is supplied, the cycle stamps that identifier and sets `approved_vacation_extra_days` to the exception's `approved_extra_days`.
        Start with the smallest of three values: the plan's `max_day_supply_days`; the prescription's `days_supply_written` multiplied by one more than its `refills_remaining`; and the cycle's `day_supply_days` plus the line's `bridge_days_applied` plus the cycle's `approved_vacation_extra_days`.
        Under `BRIDGE_TO_START`, the fill is **lengthened** so the patient is covered from the day their current supply runs out through the end of the common cycle. `bridge_days_applied` is the gap, `trim_days_applied` is zero, and `days_supply_filled` is the cycle's `day_supply_days` plus the gap.

        Design: Corner/validations/adjudicate_with_an_undecided_vacation_exception_rejected
        """
        scenario = setup_draft_cycle(
            plan_overrides={"vacation_overrides_per_year": 1},
            cycle_start_date="2026-08-15",
            day_supply_days=28,
        )
        exception = request_vacation(
            scenario.patient_id,
            travel_start_date="2026-08-20",
            travel_end_date="2026-08-27",
            requested_extra_days=5,
        )
        decide_vacation(exception["id"], "APPROVE_PHARMACIST", 5)

        cycle = do_adjudicate(scenario.cycle_id, vacation_exception_id=exception["id"])

        assert cycle["approved_vacation_extra_days"] == 5
        line = read_lines(scenario.cycle_id)[0]
        assert line["days_supply_filled"] == 28
        assert line["allowance_days"] == 33

    def test_unknown_vacation_exception_id_is_not_found(self):
        """An unknown body reference surfaces as not-found, never as the state error.

        Validation rules are evaluated in strict ascending priority order. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied.
        When `vacation_exception_id` is supplied, the referenced travel exception's `patient_id` must equal the cycle's `patient_id` and its `status` must be `PHARMACIST_APPROVED` or `PAYER_OVERRIDE_APPROVED`, otherwise `ERR_NO_APPROVED_VACATION_EXCEPTION`.
        The new cycle is created with `cycle_end_date` computed as `cycle_start_date` advanced by `day_supply_days` days, exclusive; `packaging_status` `DRAFT`; `insurance_status` `NOT_ADJUDICATED`; `is_partial_reissue` false; `reissue_of_cycle_id` null; `vacation_exception_id` null; `approved_vacation_extra_days` 0; `reissue_required` false; `roll_pouch_count` 0; `total_copay_cents` 0; `final_copay_cents` null; `reissue_fee_cents` 0; `credit_applied_cents` 0; `rounding_delta_cents` null; and `version` 1.

        Design: Corner/validations/unknown_vacation_exception_id_not_found_before_its_status_is_read
        """
        scenario = setup_draft_cycle(cycle_start_date="2026-08-15", day_supply_days=28)

        response = api_client.adjudicate_fill_cycle(
            scenario.cycle_id,
            pharmacist_headers(),
            adjudicate_payload(vacation_exception_id=UNKNOWN_VACATION_ID),
        )

        validate_error(response, ApiErrorId.VACATION_EXCEPTION_NOT_FOUND)
        assert_cycle_state(
            read_cycle(scenario.cycle_id),
            packaging_status="DRAFT",
            insurance_status="NOT_ADJUDICATED",
            version=1,
        )
        assert_line_state(read_lines(scenario.cycle_id)[0], line_status="PLANNED")


class TestChaseResponseWindow:
    """The 72-hour prescriber response window on the silence-recording chase."""

    def test_chase_at_exactly_the_due_instant_is_allowed(self):
        """The clock standing exactly on the due instant satisfies the window.

        From `SENT` it records the prescriber's silence. The clock must have reached `next_chase_due_at`; if the clock is strictly earlier, the request fails with `ERR_CHASE_TOO_EARLY`, because the 72-hour response window has not elapsed.
        The new request copies `prescriber_npi` from the prescription and starts with `status` `SENT`, `chase_round` 0, `escalation_level` 0, `first_sent_at` and `last_sent_at` both at the clock, `next_chase_due_at` at the clock advanced by 72 hours, `no_response_recorded_at` null, `approved_refills` null, `denial_reason` null and `version` 1.
        On success `status` becomes `NO_RESPONSE`, `chase_round` rises by 1 and `no_response_recorded_at` is set to the clock.
        The request's `version` increments on either effect.
        It advances only on payer and authorization triggers: adjudication, a prescriber's answer to an authorization request, an escalation that drops a held line.

        Design: Corner/validations/chase_at_exactly_seventy_two_hours_is_allowed
        """
        scenario = _held_auth_scenario()
        authorization = open_authorization(scenario.rx_id(0), 3)
        assert authorization["next_chase_due_at"].startswith("2026-08-13T00:00:00")
        set_clock("2026-08-13T00:00:00Z")

        response = api_client.chase_refill_authorization(
            authorization["id"], ops_headers()
        )

        chased = get_success_data(response, expected_status=200)
        assert chased["chase_round"] == 1
        assert chased["version"] == 2
        assert_cycle_state(
            read_cycle(scenario.cycle_id), insurance_status="EDITS_PENDING"
        )

    def test_chase_one_second_early_is_refused(self):
        """One second before the due instant the chase is still too early.

        From `SENT` it records the prescriber's silence. The clock must have reached `next_chase_due_at`; if the clock is strictly earlier, the request fails with `ERR_CHASE_TOO_EARLY`, because the 72-hour response window has not elapsed.
        The new request copies `prescriber_npi` from the prescription and starts with `status` `SENT`, `chase_round` 0, `escalation_level` 0, `first_sent_at` and `last_sent_at` both at the clock, `next_chase_due_at` at the clock advanced by 72 hours, `no_response_recorded_at` null, `approved_refills` null, `denial_reason` null and `version` 1.

        Design: Corner/validations/chase_at_exactly_seventy_two_hours_is_allowed
        """
        scenario = _held_auth_scenario()
        authorization = open_authorization(scenario.rx_id(0), 3)
        set_clock("2026-08-12T23:59:59Z")

        response = api_client.chase_refill_authorization(
            authorization["id"], ops_headers()
        )

        validate_error(response, ApiErrorId.CHASE_TOO_EARLY)
        unchanged = get_success_data(
            api_client.get_refill_authorization(authorization["id"], ops_headers())
        )
        assert unchanged["chase_round"] == 0


class TestAuthorizationRequestUniqueness:
    """At most one chase may be open against a prescription at a time."""

    def test_second_open_request_for_the_same_prescription_is_refused(self):
        """A chase already in flight blocks a second request for that prescription.

        No other request for the same `prescription_id` may currently have `status` `SENT`, `NO_RESPONSE` or `ESCALATED`, otherwise `ERR_DUPLICATE_AUTH_REQUEST`; at most one chase is open per prescription at a time.
        The new request copies `prescriber_npi` from the prescription and starts with `status` `SENT`, `chase_round` 0, `escalation_level` 0, `first_sent_at` and `last_sent_at` both at the clock, `next_chase_due_at` at the clock advanced by 72 hours, `no_response_recorded_at` null, `approved_refills` null, `denial_reason` null and `version` 1.

        Design: Corner/validations/duplicate_open_authorization_request_rejected
        """
        scenario = _held_auth_scenario()
        prescription_id = scenario.rx_id(0)
        first = open_authorization(prescription_id, 3)
        assert first["status"] == "SENT"
        assert first["chase_round"] == 0
        assert first["requested_refills"] == 3

        response = api_client.create_refill_authorization(
            refill_authorization_payload(prescription_id, 2), ops_headers()
        )

        validate_error(response, ApiErrorId.DUPLICATE_AUTH_REQUEST)
        assert_total_count(
            api_client.list_refill_authorizations(
                ops_headers(), {"prescription_id": prescription_id}
            ),
            1,
        )

    def test_after_a_denial_the_prescription_state_blocks_a_fresh_request(self):
        """A closed request no longer blocks; the discontinued prescription does.

        A denial sets `status` `DENIED` and stores `denial_reason`. The prescription moves from `PENDING_AUTHORIZATION` to `DISCONTINUED`, and every line of that prescription whose `line_status` is `HELD_AUTH` becomes `EXCLUDED_HELD` with `hold_reason` `AUTH_DENIED`.
        The prescription's `status` must be `ACTIVE` or `PENDING_AUTHORIZATION`, otherwise `ERR_INVALID_PRESCRIPTION_STATE` — a superseded, discontinued or expired prescription cannot be chased.

        Design: Corner/validations/duplicate_open_authorization_request_rejected
        """
        scenario = _held_auth_scenario()
        prescription_id = scenario.rx_id(0)
        first = open_authorization(prescription_id, 3)
        do_respond(first["id"], "DENY", denial_reason="Therapy discontinued")
        assert read_prescription(prescription_id)["status"] == "DISCONTINUED"

        response = api_client.create_refill_authorization(
            refill_authorization_payload(prescription_id, 2), ops_headers()
        )

        validate_error(response, ApiErrorId.INVALID_PRESCRIPTION_STATE)


class TestEscalationChaseCeiling:
    """Escalation is gated on the chase counter having saturated."""

    def test_escalation_before_the_chase_ceiling_is_refused(self):
        """A single recorded silence is not enough to escalate.

        Escalation is available only from `NO_RESPONSE`, otherwise `ERR_INVALID_AUTH_STATE`, and only once `chase_round` has reached 3, otherwise `ERR_ESCALATION_PREMATURE`.
        On success `status` becomes `NO_RESPONSE`, `chase_round` rises by 1 and `no_response_recorded_at` is set to the clock.
        The new request copies `prescriber_npi` from the prescription and starts with `status` `SENT`, `chase_round` 0, `escalation_level` 0, `first_sent_at` and `last_sent_at` both at the clock, `next_chase_due_at` at the clock advanced by 72 hours, `no_response_recorded_at` null, `approved_refills` null, `denial_reason` null and `version` 1.

        Design: Corner/validations/escalation_before_the_chase_ceiling_rejected
        """
        scenario = _held_auth_scenario()
        authorization = open_authorization(scenario.rx_id(0), 3)
        set_clock("2026-08-13T00:00:00Z")
        chased = do_chase(authorization["id"])
        assert chased["chase_round"] == 1

        response = api_client.escalate_refill_authorization(
            authorization["id"], ops_headers()
        )

        validate_error(response, ApiErrorId.ESCALATION_PREMATURE)
        unchanged = get_success_data(
            api_client.get_refill_authorization(authorization["id"], ops_headers())
        )
        assert unchanged["chase_round"] == 1
        assert unchanged["escalation_level"] == 0

    def test_escalation_is_legal_once_the_chase_counter_saturates(self):
        """The mirror case: at three recorded silences escalation is the legal move.

        Escalation is available only from `NO_RESPONSE`, otherwise `ERR_INVALID_AUTH_STATE`, and only once `chase_round` has reached 3, otherwise `ERR_ESCALATION_PREMATURE`.
        On success `status` becomes `ESCALATED` and `escalation_level` becomes 1.

        Design: Corner/validations/escalation_before_the_chase_ceiling_rejected
        """
        scenario = setup_saturated_chase()
        assert scenario.authorization["chase_round"] == 3

        escalated = get_success_data(
            api_client.escalate_refill_authorization(
                scenario.authorization["id"], ops_headers()
            ),
            expected_status=200,
        )

        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_level"] == 1


class TestReissueEffectiveDateWindow:
    """The reissue effective date must sit strictly inside the cycle window."""

    @pytest.mark.parametrize("effective_date", ["2026-09-12", "2026-08-15"])
    def test_effective_date_on_either_cycle_boundary_is_refused(self, effective_date):
        """Neither the inclusive start nor the exclusive end is a legal effective date.

        Its gates are evaluated in this order: the stale-version check on `expected_cycle_version`, otherwise `ERR_STALE_CYCLE_VERSION`; the patient's `autoship_status` must be `ACTIVE`, otherwise `ERR_AUTOSHIP_PAUSED`; the cycle's `packaging_status` must be `ROLL_GENERATED`, `PACKED` or `VERIFIED`, otherwise `ERR_INVALID_CYCLE_STATE`; `effective_date` must be strictly after the cycle's `cycle_start_date` and strictly before its `cycle_end_date`, otherwise `ERR_REISSUE_DATE_OUT_OF_WINDOW`; and the cycle must have something to reissue — at least one line with `line_status` `SUPERSEDED_PENDING_REISSUE`, or at least one `ADJUDICATED` line whose prescription is named in `replacement_prescription_ids` — otherwise `ERR_NOTHING_TO_REISSUE`.
        A fill cycle covers `cycle_start_date` inclusive through `cycle_end_date` exclusive, where `cycle_end_date` is `cycle_start_date` advanced by `day_supply_days` calendar days.
        Cascades are never partial: if a validation rejects a request, no part of its cascade is applied.

        Design: Corner/validations/reissue_effective_date_on_the_exclusive_end_rejected
        """
        scenario = setup_rolled_cycle(cycle_start_date="2026-08-15", day_supply_days=28)
        cycle_version = read_cycle(scenario.cycle_id)["version"]
        assert scenario.cycle["cycle_end_date"] == "2026-09-12"

        response = api_client.reissue_fill_cycle(
            scenario.cycle_id,
            reissue_payload(effective_date, [scenario.rx_id(0)], cycle_version),
            ops_headers(),
        )

        validate_error(response, ApiErrorId.REISSUE_DATE_OUT_OF_WINDOW)
        cycle = read_cycle(scenario.cycle_id)
        assert cycle["version"] == cycle_version
        assert cycle["reissue_required"] is False
        assert cycle["reissue_fee_cents"] == 0
        assert_total_count(
            api_client.list_fill_cycles(
                ops_headers(), {"reissue_of_cycle_id": scenario.cycle_id}
            ),
            0,
        )

    def test_effective_date_inside_the_window_is_accepted(self):
        """The day after the cycle start is inside the band and reissues the tail.

        Its gates are evaluated in this order: the stale-version check on `expected_cycle_version`, otherwise `ERR_STALE_CYCLE_VERSION`; the patient's `autoship_status` must be `ACTIVE`, otherwise `ERR_AUTOSHIP_PAUSED`; the cycle's `packaging_status` must be `ROLL_GENERATED`, `PACKED` or `VERIFIED`, otherwise `ERR_INVALID_CYCLE_STATE`; `effective_date` must be strictly after the cycle's `cycle_start_date` and strictly before its `cycle_end_date`, otherwise `ERR_REISSUE_DATE_OUT_OF_WINDOW`; and the cycle must have something to reissue — at least one line with `line_status` `SUPERSEDED_PENDING_REISSUE`, or at least one `ADJUDICATED` line whose prescription is named in `replacement_prescription_ids` — otherwise `ERR_NOTHING_TO_REISSUE`.
        A new fill cycle is created with `is_partial_reissue` true, `reissue_of_cycle_id` naming the original cycle, `cycle_start_date` equal to `effective_date`, `day_supply_days` equal to the number of days from `effective_date` to the original cycle's `cycle_end_date`, `packaging_status` `DRAFT`, `insurance_status` `NOT_ADJUDICATED`, and one `PLANNED` cycle line per prescription named in `replacement_prescription_ids`.

        Design: Corner/validations/reissue_effective_date_on_the_exclusive_end_rejected
        """
        scenario = setup_rolled_cycle(cycle_start_date="2026-08-15", day_supply_days=28)
        cycle_version = read_cycle(scenario.cycle_id)["version"]

        successor = get_success_data(
            api_client.reissue_fill_cycle(
                scenario.cycle_id,
                reissue_payload("2026-08-16", [scenario.rx_id(0)], cycle_version),
                ops_headers(),
            ),
            expected_status=201,
        )

        assert successor["is_partial_reissue"] is True
        assert successor["reissue_of_cycle_id"] == scenario.cycle_id
        assert successor["cycle_start_date"] == "2026-08-16"
        assert_cycle_state(
            successor, packaging_status="DRAFT", insurance_status="NOT_ADJUDICATED"
        )


class TestAuthenticationPrecedence:
    """Authentication runs before the path-identifier lookup."""

    def test_missing_identity_header_outranks_an_unknown_cycle_id(self):
        """A header-less read of a non-existent cycle must not leak its absence.

        Validation rules are evaluated in strict ascending priority order. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied.
        If either header is absent or empty on any endpoint other than the logical-clock setter, the request fails with `ERR_UNAUTHENTICATED` and HTTP 401.

        Design: Corner/validations/missing_x_user_header_outranks_unknown_path_id_unauthenticated
        """
        set_clock(CLOCK)
        role_only_headers = {
            "Content-Type": "application/json",
            "X-User-Role": "PharmacyOperations",
        }

        response = api_client.get_fill_cycle(UNKNOWN_CYCLE_ID, role_only_headers)

        validate_error(response, ApiErrorId.UNAUTHENTICATED)
        with_both_headers = api_client.get_fill_cycle(UNKNOWN_CYCLE_ID, ops_headers())
        validate_error(with_both_headers, ApiErrorId.FILL_CYCLE_NOT_FOUND)
