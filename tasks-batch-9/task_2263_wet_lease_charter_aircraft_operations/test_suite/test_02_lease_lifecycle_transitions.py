"""Lease, docket, airframe, insurance and crew-qualification state transitions.

Each test drives the real API from an empty database and asserts the transitions, guards
and side effects the PRD declares over the lease lifecycle: the authority determination,
the activation gate and its non-idempotency, withdrawal, AOG grounding and the explicit
reactivation that follows it, checkride validity, and the lessee credit-control cycle.
"""

from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    complete_checkride_payload,
    create_crew_qualification_payload,
    create_lessee_payload,
    determination_payload,
    get_success_data,
    qualify_crew_member,
    record_maintenance_event,
    schedule_leg,
    setup_active_lease,
    setup_approved_lease,
    setup_filed_lease,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_lease_payload,
)

OPS = TEST_USERS["lessor_ops_headers"]
AUTHORITY = TEST_USERS["regulatory_authority_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable datetime."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC timestamp, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# The authority determination                                                  #
# --------------------------------------------------------------------------- #


def test_approved_determination_stamps_decided_at_and_advances_the_lease(api):
    """PRD §3.2: Every determination sets `decided_at` to the current logical instant.

    PRD §3.2: An `APPROVED` ruling requires the `conditions` payload to be absent or empty.

    PRD §3.2: Both `APPROVED` and `CONDITIONAL` advance the lease from `PENDING_REGULATORY_APPROVAL` to `APPROVED` — the same lease outcome, the difference being that a conditional lease carries open conditions to clear before its term ends.

    PRD §3.2: When the lease owns no prior docket, a `RegulatoryApproval` row is created against it with `determination` `UNDER_REVIEW`, `review_round` 1, and both `conditions` and `open_condition_codes` empty.

    PRD §2.4: - `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.

    Design: Corner/state_machines/docket_decision_approved_sets_decided_at_and_advances_the_lease
    """
    scenario = setup_filed_lease(api, clock="2026-09-05T12:00:00Z")
    approval = scenario["approval"]
    assert approval["determination"] == "UNDER_REVIEW", (
        "a freshly filed docket must be UNDER_REVIEW, got "
        f"{approval['determination']}"
    )

    docket = validate_success(
        api.record_determination(
            approval["id"], determination_payload("APPROVED"), AUTHORITY
        ),
        200,
    )

    assert docket["determination"] == "APPROVED", (
        f"an APPROVED ruling must move the docket to APPROVED, got {docket['determination']}"
    )
    assert _instant(docket["decided_at"]) == _instant("2026-09-05T12:00:00Z"), (
        "decided_at must be stamped with the current logical instant "
        f"2026-09-05T12:00:00Z, got {docket['decided_at']}"
    )
    assert docket["conditions"] == [], (
        f"an APPROVED ruling must leave conditions empty, got {docket['conditions']}"
    )
    assert docket["open_condition_codes"] == [], (
        "an APPROVED ruling must leave open_condition_codes empty, got "
        f"{docket['open_condition_codes']}"
    )
    assert docket["review_round"] == 1, (
        f"the first review round must be 1, got {docket['review_round']}"
    )

    lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS), 200)
    assert lease["status"] == "APPROVED", (
        "the determination must advance the lease from PENDING_REGULATORY_APPROVAL to "
        f"APPROVED, got {lease['status']}"
    )
    assert lease["version"] == 3, (
        "the lease must be at version 3 after draft, filing and the determination "
        f"cascade, got {lease['version']}"
    )

    aircraft = validate_success(api.get_aircraft(scenario["aircraft"]["id"], TECH), 200)
    assert aircraft["status"] == "AVAILABLE", (
        f"the determination must not assign the airframe, got {aircraft['status']}"
    )
    assert aircraft["assigned_lease_id"] is None, (
        "the determination must leave assigned_lease_id null, got "
        f"{aircraft['assigned_lease_id']}"
    )


# --------------------------------------------------------------------------- #
# Activation: the gate, the side effects and the second attempt                #
# --------------------------------------------------------------------------- #


def test_activation_without_any_insurance_certificate_is_refused(api):
    """PRD §3.5: The lease must carry at least one `InsuranceCertificate` with `status` `ACTIVE`, `additional_insured_lessee` true, `breach_of_warranty_endorsed` true, `hull_limit_usd_cents` at or above the USD 50 million floor, `liability_limit_usd_cents` at or above the USD 500 million floor, and a closed coverage interval containing midnight UTC at the start of `term_start_date`; otherwise `ERR_INSURANCE_COVERAGE_MISSING` (HTTP 409).

    PRD §3.5: It sets the primary airframe from `AVAILABLE` to `ASSIGNED` and writes `assigned_lease_id` to the lease.

    PRD §3.5: And it opens the first monthly settlement window: a `UtilizationPeriod` for this lease with `status` `OPEN` and `period_month` equal to the `YYYY-MM` month of whichever is later, `term_start_date` or the current logical date, with its prorated minimum guarantee computed as described in §3.8 — but only when no period already exists for that lease and month.

    Design: Corner/state_machines/activation_without_any_insurance_certificate_returns_coverage_missing
    """
    scenario = setup_approved_lease(api, with_certificate=False, with_first_officer=False)
    lease_id = scenario["lease"]["id"]
    qualify_crew_member(api, scenario["captain"]["id"], lease_id)

    validate_error(
        api.activate_lease(lease_id, OPS), ApiErrorId.ERR_INSURANCE_COVERAGE_MISSING
    )

    lease = validate_success(api.get_lease(lease_id, OPS), 200)
    assert lease["status"] == "APPROVED", (
        f"a refused activation must leave the lease APPROVED, got {lease['status']}"
    )

    aircraft = validate_success(api.get_aircraft(scenario["aircraft"]["id"], TECH), 200)
    assert aircraft["status"] == "AVAILABLE", (
        "a refused activation must not assign the airframe, got "
        f"{aircraft['status']}"
    )
    assert aircraft["assigned_lease_id"] is None, (
        "a refused activation must leave assigned_lease_id null, got "
        f"{aircraft['assigned_lease_id']}"
    )

    periods, meta = validate_paginated(
        api.list_utilization_periods(BILLING, params={"lease_id": lease_id})
    )
    assert meta["total_count"] == 0, (
        f"a refused activation must open no utilization period, got {meta['total_count']}"
    )
    assert periods == [], f"expected no utilization period rows, got {periods}"


def test_first_activation_assigns_the_airframe_and_seeds_the_deposit(api):
    """PRD §3.5: A first activation moves the lease from `APPROVED` to `ACTIVE` and does three things besides.

    PRD §3.5: It sets the primary airframe from `AVAILABLE` to `ASSIGNED` and writes `assigned_lease_id` to the lease.

    PRD §3.5: It initialises the deposit split, setting `return_deposit_remaining_cents` to `return_deposit_cents` and `return_deposit_applied_cents` to 0.

    PRD §2.4: - `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.

    Design: Corner/state_machines/lease_activation_assigns_airframe_seeds_deposit_and_opens_first_period
    """
    scenario = setup_approved_lease(api, with_first_officer=False)
    lease_id = scenario["lease"]["id"]
    qualify_crew_member(api, scenario["captain"]["id"], lease_id)

    lease = validate_success(api.activate_lease(lease_id, OPS), 200)

    assert lease["status"] == "ACTIVE", (
        f"a first activation must move the lease to ACTIVE, got {lease['status']}"
    )
    assert lease["suspension_reason"] is None, (
        "suspension_reason must be null on an ACTIVE lease, got "
        f"{lease['suspension_reason']}"
    )
    assert lease["return_deposit_applied_cents"] == 0, (
        "activation must set return_deposit_applied_cents to 0, got "
        f"{lease['return_deposit_applied_cents']}"
    )
    assert lease["return_deposit_remaining_cents"] == 500000, (
        "activation must set return_deposit_remaining_cents to the full deposit of "
        f"500000 cents, got {lease['return_deposit_remaining_cents']}"
    )
    assert lease["version"] == 4, (
        "the lease must be at version 4 after draft, filing, the determination cascade "
        f"and activation, got {lease['version']}"
    )

    aircraft = validate_success(api.get_aircraft(scenario["aircraft"]["id"], TECH), 200)
    assert aircraft["status"] == "ASSIGNED", (
        f"activation must move the primary airframe to ASSIGNED, got {aircraft['status']}"
    )
    assert aircraft["assigned_lease_id"] == lease_id, (
        "activation must write assigned_lease_id to the activated lease, got "
        f"{aircraft['assigned_lease_id']}"
    )


def test_first_activation_opens_exactly_one_prorated_open_month(api):
    """PRD §3.5: And it opens the first monthly settlement window: a `UtilizationPeriod` for this lease with `status` `OPEN` and `period_month` equal to the `YYYY-MM` month of whichever is later, `term_start_date` or the current logical date, with its prorated minimum guarantee computed as described in §3.8 — but only when no period already exists for that lease and month.

    PRD §3.8: `mgh_effective_hours` is the lease's `min_guaranteed_block_hours_per_month` multiplied by the number of covered days and divided by the number of calendar days in `period_month`, rounded half up to four decimal places.

    PRD §3.8: When `credited_hours` is strictly less than `mgh_effective_hours`, `shortfall_hours` is their difference rounded half up to four decimal places and `overrun_hours` is 0.

    PRD §3.8: `base_charge_cents` is `mgh_effective_hours` multiplied by the lease's `block_hour_rate_usd_cents`, rounded half up to whole cents.

    PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.

    PRD §3.8: Under the `PROVISIONAL` variant that net figure is written to `provisional_charge_cents`; under the `FINAL` variant it is written to `final_charge_cents`.

    Design: Corner/state_machines/lease_activation_assigns_airframe_seeds_deposit_and_opens_first_period
    """
    scenario = setup_approved_lease(api, with_first_officer=False)
    lease_id = scenario["lease"]["id"]
    qualify_crew_member(api, scenario["captain"]["id"], lease_id)

    validate_success(api.activate_lease(lease_id, OPS), 200)

    periods, meta = validate_paginated(
        api.list_utilization_periods(BILLING, params={"lease_id": lease_id})
    )
    assert meta["total_count"] == 1, (
        "activation must open exactly one utilization period for the term-start month, "
        f"got {meta['total_count']}"
    )
    period = periods[0]
    assert period["period_month"] == "2026-09", (
        f"the first window must be the 2026-09 month, got {period['period_month']}"
    )
    assert period["status"] == "OPEN", (
        f"the first window must be OPEN, got {period['status']}"
    )
    assert float(period["mgh_effective_hours"]) == pytest.approx(5.0000, abs=0.0001), (
        "a lease covering all thirty days of September carries its full guarantee of "
        f"5.0000 hours, got {period['mgh_effective_hours']}"
    )
    assert period["credited_block_minutes"] == 0, (
        f"no leg has been flown, so credited_block_minutes must be 0, got "
        f"{period['credited_block_minutes']}"
    )
    assert float(period["credited_hours"]) == pytest.approx(0.0000, abs=0.0001), (
        f"no leg has been flown, so credited_hours must be 0.0000, got "
        f"{period['credited_hours']}"
    )
    assert float(period["shortfall_hours"]) == pytest.approx(5.0000, abs=0.0001), (
        "zero credited hours against a 5.0000-hour guarantee is a 5.0000-hour "
        f"shortfall, got {period['shortfall_hours']}"
    )
    assert period["base_charge_cents"] == 2400000, (
        "5.0000 hours at 480000 cents per block hour is 2400000 cents, got "
        f"{period['base_charge_cents']}"
    )
    assert period["gross_charge_cents"] == 2400000, (
        "with no lessor-attributable shortfall and no overrun the gross charge is "
        f"2400000 cents, got {period['gross_charge_cents']}"
    )
    assert period["provisional_charge_cents"] == 2400000, (
        "the provisional variant must write 2400000 cents to provisional_charge_cents, "
        f"got {period['provisional_charge_cents']}"
    )
    assert period["variant_applied"] == "PROVISIONAL", (
        "the provisional variant last wrote the credited and shortfall fields, got "
        f"{period['variant_applied']}"
    )


def test_second_activation_on_an_active_lease_is_refused_on_lease_state(api):
    """PRD §3.5: Any lease transition requested from a status that is not a declared source of that transition is refused with `ERR_LEASE_INVALID_STATE` (HTTP 409).

    PRD §2.8: 9. **State guards**, in this order: lessee state (`ERR_LESSEE_INVALID_STATE`), period readiness for settlement (`ERR_PERIOD_NOT_READY_FOR_SETTLEMENT`), lease state (`ERR_LEASE_INVALID_STATE`), docket determination state (`ERR_APPROVAL_INVALID_STATE`), leg state (`ERR_LEG_INVALID_STATE`), substitution state (`ERR_SUBSTITUTION_INVALID_STATE`), invoice state (`ERR_INVOICE_INVALID_STATE`), period state (`ERR_PERIOD_INVALID_STATE`), return-condition state (`ERR_RETURN_CONDITION_INVALID_STATE`), and finally airframe availability (`ERR_AIRCRAFT_UNAVAILABLE`).

    PRD §3.5: And it opens the first monthly settlement window: a `UtilizationPeriod` for this lease with `status` `OPEN` and `period_month` equal to the `YYYY-MM` month of whichever is later, `term_start_date` or the current logical date, with its prorated minimum guarantee computed as described in §3.8 — but only when no period already exists for that lease and month.

    Design: Corner/state_machines/second_activate_on_an_active_lease_returns_lease_invalid_state
    """
    scenario = setup_active_lease(api, with_first_officer=False)
    lease_id = scenario["lease"]["id"]

    validate_error(
        api.activate_lease(lease_id, OPS), ApiErrorId.ERR_LEASE_INVALID_STATE
    )

    lease = validate_success(api.get_lease(lease_id, OPS), 200)
    assert lease["status"] == "ACTIVE", (
        f"the replayed activation must leave the lease ACTIVE, got {lease['status']}"
    )
    assert lease["version"] == 4, (
        "a refused activation must not mutate the lease, so its version stays at 4, "
        f"got {lease['version']}"
    )

    periods, meta = validate_paginated(
        api.list_utilization_periods(BILLING, params={"lease_id": lease_id})
    )
    assert meta["total_count"] == 1, (
        "a refused activation must not open a second period for the same month, got "
        f"{meta['total_count']}"
    )
    assert periods[0]["period_month"] == "2026-09", (
        f"the single window must remain 2026-09, got {periods[0]['period_month']}"
    )


# --------------------------------------------------------------------------- #
# Withdrawal from the pre-operational side of the lifecycle                     #
# --------------------------------------------------------------------------- #


def test_withdrawal_from_approved_revokes_the_docket_and_the_qualifications(api):
    """PRD §3.2: A lease that never entered service may be withdrawn by operations control with a `withdrawal_reason`, from `DRAFT`, from `PENDING_REGULATORY_APPROVAL` or from `APPROVED`, moving it to the terminal `WITHDRAWN`.

    PRD §3.2: Withdrawal sets every docket on the lease whose `determination` is `UNDER_REVIEW`, `CONDITIONAL` or `APPROVED` to `REVOKED`, sets every `CrewQualification` on the lease that is `QUALIFIED` to the terminal `REVOKED`, and releases any airframe assigned to the lease by clearing `assigned_lease_id` and moving its `status` from `ASSIGNED` to `AVAILABLE`.

    Design: Corner/state_machines/withdrawal_from_approved_is_terminal_and_revokes_the_docket_and_the_crew_qualifications
    """
    scenario = setup_approved_lease(api, with_first_officer=False)
    lease_id = scenario["lease"]["id"]
    qualify_crew_member(api, scenario["captain"]["id"], lease_id)

    lease = validate_success(
        api.withdraw_lease(
            lease_id,
            withdraw_lease_payload(withdrawal_reason="LESSEE_CANCELLED_THE_SEASON"),
            OPS,
        ),
        200,
    )
    assert lease["status"] == "WITHDRAWN", (
        f"withdrawal from APPROVED must land in WITHDRAWN, got {lease['status']}"
    )

    docket = validate_success(
        api.get_regulatory_approval(scenario["approval"]["id"], OPS), 200
    )
    assert docket["determination"] == "REVOKED", (
        f"withdrawal must pull the APPROVED docket to REVOKED, got {docket['determination']}"
    )

    qualifications, meta = validate_paginated(
        api.list_crew_qualifications(OPS, params={"lease_id": lease_id})
    )
    assert meta["total_count"] == 1, (
        f"the lease owns exactly one crew qualification, got {meta['total_count']}"
    )
    assert qualifications[0]["status"] == "REVOKED", (
        "withdrawal must revoke every QUALIFIED crew qualification on the lease, got "
        f"{qualifications[0]['status']}"
    )

    aircraft = validate_success(api.get_aircraft(scenario["aircraft"]["id"], TECH), 200)
    assert aircraft["status"] == "AVAILABLE", (
        "the airframe was never assigned, so it must still read AVAILABLE, got "
        f"{aircraft['status']}"
    )
    assert aircraft["assigned_lease_id"] is None, (
        f"assigned_lease_id must stay null, got {aircraft['assigned_lease_id']}"
    )


def test_withdrawn_lease_admits_neither_activation_nor_a_second_withdrawal(api):
    """PRD §3.2: A lease that never entered service may be withdrawn by operations control with a `withdrawal_reason`, from `DRAFT`, from `PENDING_REGULATORY_APPROVAL` or from `APPROVED`, moving it to the terminal `WITHDRAWN`.

    PRD §3.5: Any lease transition requested from a status that is not a declared source of that transition is refused with `ERR_LEASE_INVALID_STATE` (HTTP 409).

    Design: Corner/state_machines/withdrawal_from_approved_is_terminal_and_revokes_the_docket_and_the_crew_qualifications
    """
    scenario = setup_approved_lease(api, with_first_officer=False)
    lease_id = scenario["lease"]["id"]
    qualify_crew_member(api, scenario["captain"]["id"], lease_id)
    get_success_data(
        api.withdraw_lease(
            lease_id,
            withdraw_lease_payload(withdrawal_reason="LESSEE_CANCELLED_THE_SEASON"),
            OPS,
        )
    )

    validate_error(
        api.activate_lease(lease_id, OPS), ApiErrorId.ERR_LEASE_INVALID_STATE
    )
    validate_error(
        api.withdraw_lease(
            lease_id, withdraw_lease_payload(withdrawal_reason="DUPLICATE_WITHDRAWAL"), OPS
        ),
        ApiErrorId.ERR_LEASE_INVALID_STATE,
    )

    lease = validate_success(api.get_lease(lease_id, OPS), 200)
    assert lease["status"] == "WITHDRAWN", (
        f"WITHDRAWN is terminal, so the lease must still read WITHDRAWN, got {lease['status']}"
    )


# --------------------------------------------------------------------------- #
# AOG grounding and the explicit reactivation that follows it                   #
# --------------------------------------------------------------------------- #


def test_aog_grounding_suspends_the_lease_and_cancels_the_open_leg(api):
    """PRD §3.1: A `GROUND_AOG` event is likewise accepted from `AVAILABLE` or `ASSIGNED` and sets `status` to `AOG`; on an airframe with a non-null `assigned_lease_id` it heads its own cascade, described in §3.7.

    PRD §3.7: A `GROUND_AOG` maintenance event on an airframe with a non-null `assigned_lease_id` cancels every leg on that airframe still `SCHEDULED` or `DISPATCHED` into `CANCELLED_LESSOR` with `cancelling_party` `LESSOR` and `cancel_reason` `TECHNICAL`, drives the owning lease from `ACTIVE` to `SUSPENDED` with `suspension_reason` `AIRFRAME_AOG`, and recomputes crew exposure and the covering open month's charge for each cancelled leg.

    PRD §2.9: Because cancelled and diverted legs are excluded from the aggregate, cancelling a leg is an exact compensation for having scheduled it.

    Design: Corner/state_machines/aog_grounding_suspends_the_lease_and_return_to_service_permits_reactivation
    """
    scenario = setup_active_lease(api)
    lease_id = scenario["lease"]["id"]
    leg = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:25:00Z",
    )

    aircraft = validate_success(
        api.record_maintenance_event(
            scenario["aircraft"]["id"],
            {"event_type": "GROUND_AOG", "note": "engine 2 borescope finding"},
            TECH,
        ),
        200,
    )
    assert aircraft["status"] == "AOG", (
        f"a GROUND_AOG event must set the airframe status to AOG, got {aircraft['status']}"
    )
    assert aircraft["assigned_lease_id"] == lease_id, (
        "the grounding must not clear assigned_lease_id, got "
        f"{aircraft['assigned_lease_id']}"
    )

    lease = validate_success(api.get_lease(lease_id, OPS), 200)
    assert lease["status"] == "SUSPENDED", (
        f"the grounding must drive the lease from ACTIVE to SUSPENDED, got {lease['status']}"
    )
    assert lease["suspension_reason"] == "AIRFRAME_AOG", (
        "the suspension_reason stamped by a technical grounding is AIRFRAME_AOG, got "
        f"{lease['suspension_reason']}"
    )

    cancelled = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert cancelled["status"] == "CANCELLED_LESSOR", (
        f"the SCHEDULED leg must be cancelled into CANCELLED_LESSOR, got {cancelled['status']}"
    )
    assert cancelled["cancel_reason"] == "TECHNICAL", (
        f"the cancel_reason matched to a grounding is TECHNICAL, got {cancelled['cancel_reason']}"
    )
    assert cancelled["cancelling_party"] == "LESSOR", (
        f"the cancelling_party must be LESSOR, got {cancelled['cancelling_party']}"
    )

    captain = validate_success(api.get_crew_member(scenario["captain"]["id"], OPS), 200)
    assert captain["rolling_duty_minutes_7d"] == 0, (
        "the cancelled leg must be excluded from the rolling duty aggregate, got "
        f"{captain['rolling_duty_minutes_7d']}"
    )
    assert captain["rolling_block_minutes_28d"] == 0, (
        "the cancelled leg must be excluded from the rolling block aggregate, got "
        f"{captain['rolling_block_minutes_28d']}"
    )


def test_return_to_service_resets_counters_and_permits_explicit_reactivation(api):
    """PRD §3.1: A `RETURN_TO_SERVICE` event is accepted from `IN_MAINTENANCE` or `AOG`; it resets `hours_since_last_check` and `cycles_since_last_check` to 0, and lands the airframe in `ASSIGNED` when `assigned_lease_id` is non-null or `AVAILABLE` when it is null.

    PRD §3.5: An `AIRFRAME_AOG` suspension does not lift automatically: after technical control has returned the airframe to service, so that it is `ASSIGNED` with `assigned_lease_id` equal to this lease, operations control must explicitly activate the lease again, which is admissible only while `suspension_reason` is `AIRFRAME_AOG` and at least one `ACTIVE` certificate on the lease covers the current logical instant.

    PRD §3.5: That reactivation clears `suspension_reason` to null, creates no further utilization period, and restores no cancelled leg.

    Design: Corner/state_machines/aog_grounding_suspends_the_lease_and_return_to_service_permits_reactivation
    """
    scenario = setup_active_lease(api)
    lease_id = scenario["lease"]["id"]
    schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:25:00Z",
    )
    record_maintenance_event(
        api, scenario["aircraft"]["id"], "GROUND_AOG", note="engine 2 borescope finding"
    )

    aircraft = validate_success(
        api.record_maintenance_event(
            scenario["aircraft"]["id"],
            {
                "event_type": "RETURN_TO_SERVICE",
                "note": "engine 2 replaced, borescope clear",
            },
            TECH,
        ),
        200,
    )
    assert aircraft["status"] == "ASSIGNED", (
        "a return to service on an airframe whose assigned_lease_id is non-null lands "
        f"in ASSIGNED, got {aircraft['status']}"
    )
    assert float(aircraft["hours_since_last_check"]) == pytest.approx(0.0, abs=0.0001), (
        "a return to service must reset hours_since_last_check to 0, got "
        f"{aircraft['hours_since_last_check']}"
    )
    assert aircraft["cycles_since_last_check"] == 0, (
        "a return to service must reset cycles_since_last_check to 0, got "
        f"{aircraft['cycles_since_last_check']}"
    )
    assert float(aircraft["airframe_hours_total"]) == pytest.approx(
        24000.00, abs=0.0001
    ), (
        "a return to service must leave airframe_hours_total untouched at 24000.00, got "
        f"{aircraft['airframe_hours_total']}"
    )

    lease = validate_success(api.activate_lease(lease_id, OPS), 200)
    assert lease["status"] == "ACTIVE", (
        f"the explicit reactivation must return the lease to ACTIVE, got {lease['status']}"
    )
    assert lease["suspension_reason"] is None, (
        "reactivation must clear suspension_reason to null, got "
        f"{lease['suspension_reason']}"
    )

    periods, meta = validate_paginated(
        api.list_utilization_periods(BILLING, params={"lease_id": lease_id})
    )
    assert meta["total_count"] == 1, (
        f"reactivation must create no further utilization period, got {meta['total_count']}"
    )
    assert periods[0]["period_month"] == "2026-09", (
        f"the single window must remain 2026-09, got {periods[0]['period_month']}"
    )
    assert periods[0]["status"] == "OPEN", (
        f"the 2026-09 window must still be OPEN, got {periods[0]['status']}"
    )


# --------------------------------------------------------------------------- #
# Checkride validity and the recurrent line-check cycle                        #
# --------------------------------------------------------------------------- #


def _training_qualification(api):
    """An APPROVED lease with one captain qualification still in TRAINING."""
    scenario = setup_approved_lease(api, with_first_officer=False)
    scenario["qualification"] = get_success_data(
        api.create_crew_qualification(
            create_crew_qualification_payload(
                scenario["captain"]["id"], scenario["lease"]["id"]
            ),
            OPS,
        )
    )
    return scenario


def test_checkride_validity_boundary_decides_qualified_against_expired(api):
    """PRD §3.4: The record is admissible from `TRAINING` or from `EXPIRED`, and the crew member must be `ACTIVE`.

    PRD §3.4: If `checkride_valid_until` is strictly later than the current logical date the qualification becomes `QUALIFIED`; otherwise the record is stored and the qualification is set to `EXPIRED` instead.

    Design: Corner/state_machines/checkride_validity_is_a_closed_boundary_and_requalification_cycles_expired_back_to_qualified
    """
    scenario = _training_qualification(api)
    qualification_id = scenario["qualification"]["id"]
    assert scenario["qualification"]["status"] == "TRAINING", (
        "a fresh enrolment starts in TRAINING, got "
        f"{scenario['qualification']['status']}"
    )

    lapsed = validate_success(
        api.complete_checkride(
            qualification_id,
            complete_checkride_payload(
                differences_training_completed_on="2026-08-20",
                checkride_valid_until="2026-08-31",
            ),
            OPS,
        ),
        200,
    )
    assert lapsed["status"] == "EXPIRED", (
        "a checkride valid only until 2026-08-31 is not strictly later than the logical "
        f"date 2026-09-01, so the record must land EXPIRED, got {lapsed['status']}"
    )
    assert lapsed["checkride_valid_until"] == "2026-08-31", (
        "the supplied checkride_valid_until must be stored even when the record "
        f"expires, got {lapsed['checkride_valid_until']}"
    )

    on_the_boundary = validate_success(
        api.complete_checkride(
            qualification_id,
            complete_checkride_payload(
                differences_training_completed_on="2026-08-20",
                checkride_valid_until="2026-09-01",
            ),
            OPS,
        ),
        200,
    )
    assert on_the_boundary["status"] == "EXPIRED", (
        "a checkride valid until exactly the current logical date 2026-09-01 is not "
        f"strictly later than it, so the record must land EXPIRED, got "
        f"{on_the_boundary['status']}"
    )
    assert on_the_boundary["checkride_valid_until"] == "2026-09-01", (
        "every attempt overwrites the stored checkride_valid_until, got "
        f"{on_the_boundary['checkride_valid_until']}"
    )

    qualified = validate_success(
        api.complete_checkride(
            qualification_id,
            complete_checkride_payload(
                differences_training_completed_on="2026-08-20",
                checkride_valid_until="2026-09-02",
            ),
            OPS,
        ),
        200,
    )
    assert qualified["status"] == "QUALIFIED", (
        "a checkride valid until 2026-09-02 is strictly later than the logical date "
        f"2026-09-01, so the record must land QUALIFIED, got {qualified['status']}"
    )
    assert qualified["checkride_valid_until"] == "2026-09-02", (
        "every attempt overwrites the stored checkride_valid_until, got "
        f"{qualified['checkride_valid_until']}"
    )
    assert qualified["differences_training_completed_on"] == "2026-08-20", (
        "the supplied differences_training_completed_on must be stored, got "
        f"{qualified['differences_training_completed_on']}"
    )


def test_clock_advance_expires_the_checkride_and_a_fresh_one_requalifies_it(api):
    """PRD §2.4: Advancing the clock has consequences: an `ACTIVE` certificate whose `expires_at` now lies in the past moves to `EXPIRED`, a `QUALIFIED` crew qualification whose `checkride_valid_until` date now lies in the past moves to `EXPIRED`, and every crew member's rolling duty and block exposure is recomputed against the new window.

    PRD §3.4: When the logical clock is later advanced past a `QUALIFIED` record's `checkride_valid_until`, the qualification lapses from `QUALIFIED` to `EXPIRED` and legs that would use that crew member on that lease are refused with `ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES`.

    PRD §3.4: Recording a fresh checkride on an `EXPIRED` record returns it to `QUALIFIED`, which is the recurrent-line-check cycle `QUALIFIED → EXPIRED → QUALIFIED`.

    Design: Corner/state_machines/checkride_validity_is_a_closed_boundary_and_requalification_cycles_expired_back_to_qualified
    """
    scenario = _training_qualification(api)
    qualification_id = scenario["qualification"]["id"]
    qualified = get_success_data(
        api.complete_checkride(
            qualification_id,
            complete_checkride_payload(
                differences_training_completed_on="2026-08-20",
                checkride_valid_until="2026-09-02",
            ),
            OPS,
        )
    )
    assert qualified["status"] == "QUALIFIED", (
        f"the record must be QUALIFIED before the clock advances, got {qualified['status']}"
    )

    validate_success(api.set_current_utc("2026-09-03T00:00:00Z", OPS), 200)

    lapsed = validate_success(api.get_crew_qualification(qualification_id, OPS), 200)
    assert lapsed["status"] == "EXPIRED", (
        "with the clock past 2026-09-02 the qualification must lapse from QUALIFIED to "
        f"EXPIRED without any request against it, got {lapsed['status']}"
    )

    requalified = validate_success(
        api.complete_checkride(
            qualification_id,
            complete_checkride_payload(
                differences_training_completed_on="2026-09-02",
                checkride_valid_until="2027-08-31",
            ),
            OPS,
        ),
        200,
    )
    assert requalified["status"] == "QUALIFIED", (
        "a fresh checkride on an EXPIRED record must return it to QUALIFIED, got "
        f"{requalified['status']}"
    )
    assert requalified["checkride_valid_until"] == "2027-08-31", (
        "the fresh checkride must overwrite checkride_valid_until, got "
        f"{requalified['checkride_valid_until']}"
    )
    assert requalified["differences_training_completed_on"] == "2026-09-02", (
        "the fresh checkride must overwrite differences_training_completed_on, got "
        f"{requalified['differences_training_completed_on']}"
    )


# --------------------------------------------------------------------------- #
# The lessee credit-control cycle                                              #
# --------------------------------------------------------------------------- #


def test_credit_control_suspension_cycles_the_lessee_active_suspended_active(api):
    """PRD §3.1: A `BillingAdmin` may suspend an `ACTIVE` lessee, moving `status` from `ACTIVE` to `SUSPENDED`, and may reinstate a `SUSPENDED` one, moving it back from `SUSPENDED` to `ACTIVE`.

    PRD §3.1: Neither leg of the cycle touches `outstanding_balance_usd_cents` or `credit_limit_usd_cents`.

    PRD §2.4: - `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.

    Design: Corner/state_machines/lessee_credit_control_suspension_cycles_active_suspended_active
    """
    lessee = validate_success(api.create_lessee(create_lessee_payload(), BILLING), 201)
    assert lessee["status"] == "ACTIVE", (
        f"a new lessee starts ACTIVE, got {lessee['status']}"
    )

    suspended = validate_success(api.suspend_lessee(lessee["id"], BILLING), 200)
    assert suspended["status"] == "SUSPENDED", (
        f"suspending an ACTIVE lessee must move it to SUSPENDED, got {suspended['status']}"
    )
    assert suspended["version"] == 2, (
        f"the suspension is the lessee's second version, got {suspended['version']}"
    )
    assert suspended["outstanding_balance_usd_cents"] == 0, (
        "suspension must not touch outstanding_balance_usd_cents, got "
        f"{suspended['outstanding_balance_usd_cents']}"
    )
    assert suspended["credit_limit_usd_cents"] == 500000000, (
        "suspension must not touch credit_limit_usd_cents, got "
        f"{suspended['credit_limit_usd_cents']}"
    )

    reinstated = validate_success(api.reinstate_lessee(lessee["id"], BILLING), 200)
    assert reinstated["status"] == "ACTIVE", (
        f"reinstating a SUSPENDED lessee must move it back to ACTIVE, got {reinstated['status']}"
    )
    assert reinstated["version"] == 3, (
        f"the reinstatement is the lessee's third version, got {reinstated['version']}"
    )
    assert reinstated["outstanding_balance_usd_cents"] == 0, (
        "reinstatement must not touch outstanding_balance_usd_cents, got "
        f"{reinstated['outstanding_balance_usd_cents']}"
    )
    assert reinstated["credit_limit_usd_cents"] == 500000000, (
        "reinstatement must not touch credit_limit_usd_cents, got "
        f"{reinstated['credit_limit_usd_cents']}"
    )


def test_reinstating_an_already_active_lessee_is_refused(api):
    """PRD §3.1: Suspending a lessee that is not `ACTIVE`, or reinstating one that is not `SUSPENDED`, is rejected with `ERR_LESSEE_INVALID_STATE` (HTTP 409).

    Design: Corner/state_machines/lessee_credit_control_suspension_cycles_active_suspended_active
    """
    lessee = validate_success(api.create_lessee(create_lessee_payload(), BILLING), 201)

    validate_error(
        api.reinstate_lessee(lessee["id"], BILLING), ApiErrorId.ERR_LESSEE_INVALID_STATE
    )

    unchanged = validate_success(api.get_lessee(lessee["id"], BILLING), 200)
    assert unchanged["status"] == "ACTIVE", (
        f"the refused reinstatement must leave the lessee ACTIVE, got {unchanged['status']}"
    )
    assert unchanged["version"] == 1, (
        f"a refused transition must not mutate the lessee, got version {unchanged['version']}"
    )
