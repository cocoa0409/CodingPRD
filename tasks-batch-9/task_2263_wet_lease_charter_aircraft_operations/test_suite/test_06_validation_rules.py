"""Field-level and gate-level validation rules, including the boundaries either side of
each threshold and the two orderings the PRD pins so a specific diagnosis surfaces
instead of a generic state error.
"""

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    activate_lease,
    add_substitute_candidate,
    approve_invoice,
    close_month,
    close_return_payload,
    consent_to_substitution,
    create_aircraft,
    create_aircraft_payload,
    create_first_officer,
    create_flight_leg_payload,
    create_insurance_certificate_payload,
    create_lease_payload,
    create_lessee,
    create_settlement_invoice_payload,
    create_substitution_payload,
    dispute_payload,
    file_reliability_report,
    fly_leg,
    get_success_data,
    inspect_return,
    issue_invoice,
    make_billing_admin_headers,
    period_for_month,
    prepare_invoice,
    qualify_crew_member,
    request_substitution,
    schedule_leg,
    set_clock,
    setup_active_lease,
    setup_approved_lease,
    setup_settled_month,
    terminate_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
UNDERWRITER = TEST_USERS["insurance_underwriter_headers"]

PREPARER = make_billing_admin_headers("billing-clerk-01")
APPROVER = make_billing_admin_headers("billing-supervisor-02")

CLOCK = TEST_DEFAULTS["CLOCK_AT_TERM_START"]

MIN_HULL_LIMIT = 5_000_000_000
MIN_LIABILITY_LIMIT = 50_000_000_000


# --------------------------------------------------------------------------- #
# Crew gates on scheduling                                                     #
# --------------------------------------------------------------------------- #


class TestCrewAdmissionGates:
    def test_scheduling_with_an_unqualified_first_officer_is_refused(self, api):
        """PRD §3.6: Both pilots must hold a `QUALIFIED` qualification for this lease, else `ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES` (HTTP 409).
        PRD §3.5: And at least one `CrewQualification` on the lease must be `QUALIFIED` for a crew member whose `crew_role` is `CAPTAIN` — a lease cannot come into force without a qualified commander.
        PRD §2.9: `CrewMember.rolling_duty_minutes_7d` and `CrewMember.rolling_block_minutes_28d` are aggregates over the crew member's own legs, recomputed rather than adjusted.

        Design: Corner/validations/leg_with_unqualified_first_officer_returns_crew_not_qualified
        """
        scenario = setup_approved_lease(api)
        lease_id = scenario["lease"]["id"]
        # Only the commander is enrolled and checked out on the lessee's procedures.
        qualify_crew_member(api, scenario["captain"]["id"], lease_id)
        activate_lease(api, lease_id)

        first_officer = scenario["first_officer"]
        payload = create_flight_leg_payload(
            lease_id,
            scenario["aircraft"]["id"],
            scenario["captain"]["id"],
            first_officer["id"],
            scheduled_out="2026-09-08T06:00:00Z",
            scheduled_in="2026-09-08T08:35:30Z",
        )
        validate_error(
            api.create_flight_leg(payload, OPS),
            ApiErrorId.ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES,
            409,
        )

        legs, meta = validate_paginated(
            api.list_flight_legs(OPS, params={"lease_id": lease_id})
        )
        assert meta["total_count"] == 0, (
            "a refused scheduling attempt must not persist a leg, expected total_count 0, "
            f"got {meta['total_count']}"
        )

        fo = get_success_data(api.get_crew_member(first_officer["id"], OPS))
        assert fo["rolling_duty_minutes_7d"] == 0, (
            "the unqualified first officer must carry no duty exposure, expected 0, got "
            f"{fo['rolling_duty_minutes_7d']}"
        )
        assert fo["rolling_block_minutes_28d"] == 0, (
            "the unqualified first officer must carry no block exposure, expected 0, got "
            f"{fo['rolling_block_minutes_28d']}"
        )

    def test_scheduling_with_a_first_officer_rated_on_another_type_is_refused(self, api):
        """PRD §3.6: Both pilots must hold the operating airframe's exact `type_designator` in their `type_ratings` array and must themselves be `ACTIVE`, else `ERR_CREW_NOT_TYPE_RATED` (HTTP 422).
        PRD §2.8: **Crew safety**, in this order: type rating and crew standing (`ERR_CREW_NOT_TYPE_RATED`), rolling seven-day duty exposure (`ERR_CREW_DUTY_LIMIT_EXCEEDED`), rolling twenty-eight-day block exposure (`ERR_CREW_BLOCK_LIMIT_EXCEEDED`), and lessee-procedures qualification (`ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES`).

        Design: Corner/validations/leg_with_first_officer_not_rated_on_the_operating_type_returns_not_type_rated
        """
        scenario = setup_approved_lease(api, with_first_officer=False)
        lease_id = scenario["lease"]["id"]
        # Fully trained on the lessee's procedures, but rated on the wrong variant.
        first_officer = create_first_officer(api, type_ratings=["A320"])
        qualify_crew_member(api, scenario["captain"]["id"], lease_id)
        qualify_crew_member(api, first_officer["id"], lease_id)
        activate_lease(api, lease_id)

        payload = create_flight_leg_payload(
            lease_id,
            scenario["aircraft"]["id"],
            scenario["captain"]["id"],
            first_officer["id"],
            scheduled_out="2026-09-08T06:00:00Z",
            scheduled_in="2026-09-08T08:35:30Z",
        )
        validate_error(
            api.create_flight_leg(payload, OPS),
            ApiErrorId.ERR_CREW_NOT_TYPE_RATED,
            422,
        )

    def test_fifth_long_haul_leg_breaching_the_28_day_block_ceiling_is_refused(self, api):
        """PRD §3.4: The limits are 3,600 minutes of projected seven-day duty — sixty hours — and 5,400 minutes of projected twenty-eight-day block time — ninety hours.
        PRD §3.4: The projected twenty-eight-day block exposure is the candidate leg's scheduled block minutes plus the scheduled block minutes of that same restricted set of legs whose `scheduled_out` falls at or after 672 hours before the candidate's off-blocks instant and strictly before it.
        PRD §3.4: The boundary is inclusive on the admissible side: a projection landing exactly on 3,600 or exactly on 5,400 minutes is admitted, and only a strictly greater projection is refused.
        PRD §3.4: Exceeding the duty limit yields `ERR_CREW_DUTY_LIMIT_EXCEEDED` (HTTP 409); exceeding the block limit yields `ERR_CREW_BLOCK_LIMIT_EXCEEDED` (HTTP 409).

        Design: Corner/validations/rolling_28_day_block_limit_rejects_the_fifth_long_haul_leg
        """
        scenario = setup_active_lease(api)
        lease_id = scenario["lease"]["id"]

        # Four transatlantic rotations of 1,200 scheduled block minutes each.
        for day in ("02", "06", "10", "14"):
            next_day = f"{int(day) + 1:02d}"
            schedule_leg(
                api,
                scenario,
                f"2026-09-{day}T06:00:00Z",
                f"2026-09-{next_day}T02:00:00Z",
                origin_icao="EGSS",
                dest_icao="KJFK",
            )

        # 4 x 1200 stored block minutes plus a 700-minute candidate projects 5,500.
        candidate = create_flight_leg_payload(
            lease_id,
            scenario["aircraft"]["id"],
            scenario["captain"]["id"],
            scenario["first_officer"]["id"],
            scheduled_out="2026-09-18T06:00:00Z",
            scheduled_in="2026-09-18T17:40:00Z",
            origin_icao="EGSS",
            dest_icao="KEWR",
        )
        validate_error(
            api.create_flight_leg(candidate, OPS),
            ApiErrorId.ERR_CREW_BLOCK_LIMIT_EXCEEDED,
            409,
        )

        legs, meta = validate_paginated(
            api.list_flight_legs(OPS, params={"lease_id": lease_id})
        )
        assert meta["total_count"] == 4, (
            "the refused fifth leg must not be persisted, expected total_count 4, got "
            f"{meta['total_count']}"
        )


# --------------------------------------------------------------------------- #
# Activation: maintenance-programme alignment                                  #
# --------------------------------------------------------------------------- #


def test_activation_refused_when_airframe_is_on_a_different_maintenance_programme(api):
    """PRD §3.5: The airframe named by `primary_aircraft_id` must have a `maintenance_program_ref` equal to the lease's `required_maintenance_program_ref`; otherwise `ERR_MAINTENANCE_PROGRAM_MISALIGNED` (HTTP 422).
    PRD §3.5: It sets the primary airframe from `AVAILABLE` to `ASSIGNED` and writes `assigned_lease_id` to the lease.
    PRD §3.1: A new airframe starts with `status` `AVAILABLE` and `assigned_lease_id` null; that field is non-null exactly while the airframe is the airframe of record for a lease.

    Design: Corner/validations/activation_with_airframe_on_the_wrong_maintenance_programme_returns_misaligned
    """
    scenario = setup_approved_lease(
        api,
        aircraft_overrides={"maintenance_program_ref": "MP-B738-REV11"},
        with_first_officer=False,
    )
    lease_id = scenario["lease"]["id"]
    qualify_crew_member(api, scenario["captain"]["id"], lease_id)

    validate_error(
        api.activate_lease(lease_id, OPS),
        ApiErrorId.ERR_MAINTENANCE_PROGRAM_MISALIGNED,
        422,
    )

    lease = get_success_data(api.get_lease(lease_id, OPS))
    assert lease["status"] == "APPROVED", (
        f"a refused activation must leave the lease APPROVED, got {lease['status']}"
    )

    aircraft = get_success_data(api.get_aircraft(scenario["aircraft"]["id"], TECH))
    assert aircraft["status"] == "AVAILABLE", (
        "a refused activation must not assign the airframe, expected AVAILABLE, got "
        f"{aircraft['status']}"
    )
    assert aircraft["assigned_lease_id"] is None, (
        "a refused activation must leave assigned_lease_id null, got "
        f"{aircraft['assigned_lease_id']}"
    )


# --------------------------------------------------------------------------- #
# Insurance minimum limits                                                     #
# --------------------------------------------------------------------------- #


class TestInsuranceLimitFloors:
    ONE_CENT_SHORT_ON_HULL = {
        "certificate_no": "COI-LOW-1",
        "hull_limit_usd_cents": 4_999_999_999,
        "liability_limit_usd_cents": 75_000_000_000,
    }
    ONE_CENT_SHORT_ON_LIABILITY = {
        "certificate_no": "COI-LOW-2",
        "hull_limit_usd_cents": 6_000_000_000,
        "liability_limit_usd_cents": 49_999_999_999,
    }
    EXACTLY_ON_BOTH_FLOORS = {
        "certificate_no": "COI-MIN-3",
        "hull_limit_usd_cents": MIN_HULL_LIMIT,
        "liability_limit_usd_cents": MIN_LIABILITY_LIMIT,
    }

    @pytest.mark.parametrize(
        "limits",
        [ONE_CENT_SHORT_ON_HULL, ONE_CENT_SHORT_ON_LIABILITY],
        ids=["hull_one_cent_short", "liability_one_cent_short"],
    )
    def test_certificate_one_cent_below_a_limit_floor_is_refused(self, api, limits):
        """PRD §3.3: `hull_limit_usd_cents` must be at least 5,000,000,000 cents — USD 50 million — and `liability_limit_usd_cents` at least 50,000,000,000 cents — USD 500 million; a certificate falling below either floor is refused with `ERR_INSURANCE_LIMIT_BELOW_MINIMUM` (HTTP 422).

        Design: Corner/validations/insurance_minimum_limits_reject_one_cent_short_and_admit_exact_equality
        """
        scenario = setup_approved_lease(api, with_certificate=False)
        lease_id = scenario["lease"]["id"]

        payload = create_insurance_certificate_payload(lease_id, **limits)
        validate_error(
            api.create_insurance_certificate(payload, UNDERWRITER),
            ApiErrorId.ERR_INSURANCE_LIMIT_BELOW_MINIMUM,
            422,
        )

        certificates, meta = validate_paginated(
            api.list_lease_insurance_certificates(lease_id, OPS)
        )
        assert meta["total_count"] == 0, (
            "a certificate below a limit floor must not be persisted, expected "
            f"total_count 0, got {meta['total_count']}"
        )

    def test_certificate_exactly_on_both_limit_floors_is_admitted(self, api):
        """PRD §3.3: `hull_limit_usd_cents` must be at least 5,000,000,000 cents — USD 50 million — and `liability_limit_usd_cents` at least 50,000,000,000 cents — USD 500 million; a certificate falling below either floor is refused with `ERR_INSURANCE_LIMIT_BELOW_MINIMUM` (HTTP 422).
        PRD §3.3: A new certificate is created with `status` `ACTIVE` and `revocation_reason` null.

        Design: Corner/validations/insurance_minimum_limits_reject_one_cent_short_and_admit_exact_equality
        """
        scenario = setup_approved_lease(api, with_certificate=False)
        lease_id = scenario["lease"]["id"]

        for limits in (self.ONE_CENT_SHORT_ON_HULL, self.ONE_CENT_SHORT_ON_LIABILITY):
            validate_error(
                api.create_insurance_certificate(
                    create_insurance_certificate_payload(lease_id, **limits), UNDERWRITER
                ),
                ApiErrorId.ERR_INSURANCE_LIMIT_BELOW_MINIMUM,
                422,
            )

        certificate = validate_success(
            api.create_insurance_certificate(
                create_insurance_certificate_payload(
                    lease_id, **self.EXACTLY_ON_BOTH_FLOORS
                ),
                UNDERWRITER,
            ),
            201,
        )
        assert certificate["status"] == "ACTIVE", (
            "a certificate sitting exactly on both floors must be admitted ACTIVE, got "
            f"{certificate['status']}"
        )
        assert certificate["hull_limit_usd_cents"] == MIN_HULL_LIMIT, (
            f"expected hull limit {MIN_HULL_LIMIT}, got "
            f"{certificate['hull_limit_usd_cents']}"
        )
        assert certificate["liability_limit_usd_cents"] == MIN_LIABILITY_LIMIT, (
            f"expected liability limit {MIN_LIABILITY_LIMIT}, got "
            f"{certificate['liability_limit_usd_cents']}"
        )

        certificates, meta = validate_paginated(
            api.list_lease_insurance_certificates(lease_id, OPS)
        )
        assert meta["total_count"] == 1, (
            "only the admitted certificate may exist on the lease, expected total_count "
            f"1, got {meta['total_count']}"
        )
        assert certificates[0]["certificate_no"] == "COI-MIN-3", (
            "the surviving certificate must be the one on the floors, expected "
            f"COI-MIN-3, got {certificates[0]['certificate_no']}"
        )


# --------------------------------------------------------------------------- #
# Fleet registration uniqueness                                                #
# --------------------------------------------------------------------------- #


def test_second_airframe_reusing_a_registration_mark_is_refused(api):
    """PRD §3.1: Airframes are registered by technical control with a `tail_number` (the registration mark, five to seven characters, unique across the fleet — a repeat is rejected with `ERR_DUPLICATE_TAIL_NUMBER`), a `type_designator` naming the exact ICAO variant, a `type_family` naming the commercial family that variant belongs to, a certified `seat_count` of at least 1, an `mtow_kg` maximum take-off weight of at least 1, the `maintenance_program_ref` identifying the continuous-airworthiness programme the airframe is enrolled in, and three opening counters: `airframe_hours_total`, `hours_since_last_check` and `cycles_since_last_check`.
    PRD §2.3: Airframes may be filtered by `assigned_lease_id`, `status`, `type_designator` and `type_family`.

    Design: Corner/validations/second_aircraft_with_an_existing_tail_number_returns_duplicate_tail_number
    """
    set_clock(api, CLOCK)
    first = create_aircraft(api)

    # Same registration mark, every other field different.
    duplicate = create_aircraft_payload(
        tail_number="G-ACMI",
        type_designator="B739",
        type_family="B737",
        seat_count=186,
        mtow_kg=85000,
        maintenance_program_ref="MP-B738-REV12",
        airframe_hours_total=100.00,
        hours_since_last_check=10.00,
        cycles_since_last_check=3,
    )
    validate_error(
        api.create_aircraft(duplicate, TECH),
        ApiErrorId.ERR_DUPLICATE_TAIL_NUMBER,
        409,
    )

    fleet, meta = validate_paginated(
        api.list_aircraft(OPS, params={"type_family": "B737"})
    )
    assert meta["total_count"] == 1, (
        "the duplicate registration must not be persisted, expected total_count 1, got "
        f"{meta['total_count']}"
    )
    assert fleet[0]["type_designator"] == "B738", (
        f"the surviving airframe must be the original B738, got {fleet[0]['type_designator']}"
    )
    assert fleet[0]["id"] == first["id"], (
        f"the surviving airframe must be the first row, expected {first['id']}, got {fleet[0]['id']}"
    )


# --------------------------------------------------------------------------- #
# The operational-control structural rule                                      #
# --------------------------------------------------------------------------- #


class TestOperationalControlStructure:
    def _parties(self, api):
        set_clock(api, CLOCK)
        lessee = create_lessee(api)
        aircraft = create_aircraft(api)
        return lessee, aircraft

    def test_lessor_crew_and_maintenance_with_lessee_operational_control_refused(self, api):
        """PRD §3.2: The structural rule is unconditional: whenever the lessor furnishes both crew and maintenance, `operational_control` must be `LESSOR`, because a lessor-crewed and lessor-maintained arrangement in which the lessee holds operational control is not a lawful wet lease.
        PRD §3.2: The mixture is refused with `ERR_OPERATIONAL_CONTROL_MISMATCH` (HTTP 422), both when the lease is drafted and again when it is filed with the authority.
        PRD §3.2: `operational_control` declares who holds operational control and is likewise `LESSOR` or `LESSEE`.

        Design: Corner/validations/lessor_crew_and_maintenance_with_lessee_operational_control_returns_mismatch
        """
        lessee, aircraft = self._parties(api)

        payload = create_lease_payload(
            lessee["id"],
            aircraft["id"],
            crew_provided_by="LESSOR",
            maintenance_provided_by="LESSOR",
            operational_control="LESSEE",
        )
        validate_error(
            api.create_lease(payload, OPS),
            ApiErrorId.ERR_OPERATIONAL_CONTROL_MISMATCH,
            422,
        )

        leases, meta = validate_paginated(
            api.list_leases(OPS, params={"lessee_id": lessee["id"]})
        )
        assert meta["total_count"] == 0, (
            "an unlawful responsibility split must not persist a lease, expected "
            f"total_count 0, got {meta['total_count']}"
        )

    def test_lessor_crew_and_maintenance_with_lessor_operational_control_admitted(self, api):
        """PRD §3.2: The structural rule is unconditional: whenever the lessor furnishes both crew and maintenance, `operational_control` must be `LESSOR`, because a lessor-crewed and lessor-maintained arrangement in which the lessee holds operational control is not a lawful wet lease.
        PRD §3.2: A freshly drafted lease has `status` `DRAFT`, `suspension_reason` null, `lifetime_credited_block_minutes` 0, `return_deposit_applied_cents` 0 and `return_deposit_remaining_cents` equal to `return_deposit_cents`.

        Design: Corner/validations/lessor_crew_and_maintenance_with_lessee_operational_control_returns_mismatch
        """
        lessee, aircraft = self._parties(api)

        payload = create_lease_payload(
            lessee["id"],
            aircraft["id"],
            crew_provided_by="LESSOR",
            maintenance_provided_by="LESSOR",
            operational_control="LESSOR",
        )
        lease = validate_success(api.create_lease(payload, OPS), 201)
        assert lease["operational_control"] == "LESSOR", (
            "the admitted lease must record lessor operational control, got "
            f"{lease['operational_control']}"
        )
        assert lease["status"] == "DRAFT", (
            f"a freshly drafted lease must be DRAFT, got {lease['status']}"
        )


# --------------------------------------------------------------------------- #
# Dispute amount bounds                                                        #
# --------------------------------------------------------------------------- #


class TestDisputedAmountBounds:
    SETTLED_CHARGE_CENTS = 2_400_000

    @pytest.mark.parametrize(
        "disputed_amount_cents",
        [2_400_001, 0],
        ids=["one_cent_above_the_settled_charge", "zero"],
    )
    def test_disputed_amount_outside_the_settled_range_is_refused(
        self, api, disputed_amount_cents
    ):
        """PRD §3.9: The contested amount must be strictly greater than 0 and no greater than the period's `final_charge_cents`; anything outside that half-open range is refused with `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/validations/disputed_amount_above_the_settled_charge_or_at_zero_returns_invalid_request
        """
        scenario = setup_settled_month(api, leg_plan=[])
        period = scenario["period"]
        assert period["final_charge_cents"] == self.SETTLED_CHARGE_CENTS, (
            f"setup expected a settled charge of {self.SETTLED_CHARGE_CENTS} cents, got "
            f"{period['final_charge_cents']}"
        )

        validate_error(
            api.dispute_utilization_period(
                period["id"],
                dispute_payload(
                    dispute_reason="MGH_PRORATION_CHALLENGED",
                    disputed_amount_cents=disputed_amount_cents,
                ),
                scenario["lessee_headers"],
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        unchanged = get_success_data(api.get_utilization_period(period["id"], BILLING))
        assert unchanged["status"] == "SETTLED", (
            "a refused dispute must leave the month SETTLED, got "
            f"{unchanged['status']}"
        )

    def test_disputed_amount_equal_to_the_settled_charge_is_admitted(self, api):
        """PRD §3.9: The contested amount must be strictly greater than 0 and no greater than the period's `final_charge_cents`; anything outside that half-open range is refused with `ERR_INVALID_REQUEST` (HTTP 400).
        PRD §3.9: The dispute moves the period from `SETTLED` to `DISPUTED`, records both fields, and increments the period's `version`.

        Design: Corner/validations/disputed_amount_above_the_settled_charge_or_at_zero_returns_invalid_request
        """
        scenario = setup_settled_month(api, leg_plan=[])
        period = scenario["period"]

        for rejected in (2_400_001, 0):
            validate_error(
                api.dispute_utilization_period(
                    period["id"],
                    dispute_payload(
                        dispute_reason="MGH_PRORATION_CHALLENGED",
                        disputed_amount_cents=rejected,
                    ),
                    scenario["lessee_headers"],
                ),
                ApiErrorId.ERR_INVALID_REQUEST,
                400,
            )

        disputed = validate_success(
            api.dispute_utilization_period(
                period["id"],
                dispute_payload(
                    dispute_reason="MGH_PRORATION_CHALLENGED",
                    disputed_amount_cents=self.SETTLED_CHARGE_CENTS,
                ),
                scenario["lessee_headers"],
            )
        )
        assert disputed["status"] == "DISPUTED", (
            f"a dispute at the settled charge must be admitted, got {disputed['status']}"
        )
        assert disputed["disputed_amount_cents"] == self.SETTLED_CHARGE_CENTS, (
            f"expected disputed_amount_cents {self.SETTLED_CHARGE_CENTS}, got "
            f"{disputed['disputed_amount_cents']}"
        )
        assert disputed["dispute_reason"] == "MGH_PRORATION_CHALLENGED", (
            f"expected the supplied dispute_reason, got {disputed['dispute_reason']}"
        )
        assert disputed["final_charge_cents"] == self.SETTLED_CHARGE_CENTS, (
            f"expected final_charge_cents {self.SETTLED_CHARGE_CENTS}, got "
            f"{disputed['final_charge_cents']}"
        )


# --------------------------------------------------------------------------- #
# Redelivery closure gates                                                     #
# --------------------------------------------------------------------------- #


def _terminating_lease_with_repositioning_leg(api, fly: bool):
    """Lease TERMINATING with a LEPA-EGSS repositioning leg, flown or still scheduled."""
    scenario = setup_active_lease(api)
    leg_kwargs = dict(
        leg_class="REPOSITIONING",
        origin_icao="LEPA",
        dest_icao="EGSS",
    )
    if fly:
        leg = fly_leg(
            api,
            scenario,
            "2026-09-20T06:00:00Z",
            "2026-09-20T08:00:00Z",
            **leg_kwargs,
        )
    else:
        leg = schedule_leg(
            api,
            scenario,
            "2026-09-20T06:00:00Z",
            "2026-09-20T08:00:00Z",
            **leg_kwargs,
        )
    return_condition = terminate_lease(api, scenario["lease"]["id"])
    return scenario, leg, return_condition


class TestReturnClosureGates:
    def test_closing_a_return_with_open_discrepancies_reports_discrepancies_open(self, api):
        """PRD §3.10: Closure is admissible only once the record is `CLEARED`: attempted while it is still `DISCREPANCIES_OPEN` it is refused with `ERR_RETURN_DISCREPANCIES_OPEN` (HTTP 409), and attempted while it is still `PENDING_INSPECTION` or already `CLOSED` it is refused with `ERR_RETURN_CONDITION_INVALID_STATE` (HTTP 409).
        PRD §2.8: Likewise, a closure attempted on a return record with discrepancies still open deliberately passes the return-condition state guard and falls through to `ERR_RETURN_DISCREPANCIES_OPEN`, whereas a closure attempted while the record is still awaiting inspection, or is already closed, is reported as `ERR_RETURN_CONDITION_INVALID_STATE`.
        PRD §3.10: A first inspection producing a non-empty `discrepancy_codes` array moves the record from `PENDING_INSPECTION` to `DISCREPANCIES_OPEN`.

        Design: Corner/validations/closing_a_return_with_open_discrepancies_returns_discrepancies_open_not_invalid_state
        """
        scenario, leg, return_condition = _terminating_lease_with_repositioning_leg(
            api, fly=True
        )
        inspected = inspect_return(
            api,
            return_condition["id"],
            hours_since_check_at_return=355.50,
            cycles_since_check_at_return=138,
            fuel_on_board_kg=3600,
            discrepancy_codes=["CABIN_TRIM_DAMAGE"],
        )
        assert inspected["status"] == "DISCREPANCIES_OPEN", (
            "an inspection recording a discrepancy code must open discrepancies, got "
            f"{inspected['status']}"
        )

        validate_error(
            api.close_return_condition(
                return_condition["id"], close_return_payload(leg["id"]), OPS
            ),
            ApiErrorId.ERR_RETURN_DISCREPANCIES_OPEN,
            409,
        )

        record = get_success_data(
            api.get_return_condition(return_condition["id"], TECH)
        )
        assert record["status"] == "DISCREPANCIES_OPEN", (
            f"the refused closure must leave discrepancies open, got {record['status']}"
        )
        assert record["repositioning_leg_id"] is None, (
            "a refused closure must not store the ferry leg, got "
            f"{record['repositioning_leg_id']}"
        )

        lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["status"] == "TERMINATING", (
            f"the lease must remain TERMINATING, got {lease['status']}"
        )
        aircraft = get_success_data(api.get_aircraft(scenario["aircraft"]["id"], TECH))
        assert aircraft["status"] == "ASSIGNED", (
            "the airframe is only released on closure, expected ASSIGNED, got "
            f"{aircraft['status']}"
        )

    def test_closure_refused_while_the_repositioning_leg_is_still_scheduled(self, api):
        """PRD §3.10: The named leg must be a leg on the same lease whose `leg_class` is `REPOSITIONING`, whose `status` is `COMPLETED` and whose `dest_icao` equals the lease's `redelivery_icao`; anything else is refused with `ERR_REPOSITIONING_LEG_INCOMPLETE` (HTTP 409).

        Design: Corner/validations/return_closure_waits_for_the_repositioning_leg_to_actually_fly
        """
        scenario, leg, return_condition = _terminating_lease_with_repositioning_leg(
            api, fly=False
        )
        cleared = inspect_return(
            api,
            return_condition["id"],
            hours_since_check_at_return=280.00,
            cycles_since_check_at_return=100,
            fuel_on_board_kg=4200,
            discrepancy_codes=[],
        )
        assert cleared["status"] == "CLEARED", (
            f"a clean inspection must clear the record, got {cleared['status']}"
        )

        validate_error(
            api.close_return_condition(
                return_condition["id"], close_return_payload(leg["id"]), OPS
            ),
            ApiErrorId.ERR_REPOSITIONING_LEG_INCOMPLETE,
            409,
        )

        record = get_success_data(
            api.get_return_condition(return_condition["id"], TECH)
        )
        assert record["status"] == "CLEARED", (
            f"the refused closure must leave the record CLEARED, got {record['status']}"
        )

    def test_closure_admitted_once_the_repositioning_leg_has_flown(self, api):
        """PRD §3.10: The named leg must be a leg on the same lease whose `leg_class` is `REPOSITIONING`, whose `status` is `COMPLETED` and whose `dest_icao` equals the lease's `redelivery_icao`; anything else is refused with `ERR_REPOSITIONING_LEG_INCOMPLETE` (HTTP 409).
        PRD §3.10: Closure stores `repositioning_leg_id`, moves the record from `CLEARED` to the terminal `CLOSED`, and drives the lease from `TERMINATING` to the terminal `RETURNED`.
        PRD §3.10: That final lease transition releases the airframe — clearing its `assigned_lease_id` and moving its `status` from `ASSIGNED` to `AVAILABLE` — and sets every `CrewQualification` on the lease to `REVOKED`.
        PRD §3.6: A `REPOSITIONING` leg takes its `block_minutes` exactly, with no floor applied.

        Design: Corner/validations/return_closure_waits_for_the_repositioning_leg_to_actually_fly
        """
        scenario = setup_active_lease(api)
        lease_id = scenario["lease"]["id"]
        ferry_kwargs = dict(
            leg_class="REPOSITIONING",
            origin_icao="LEPA",
            dest_icao="EGSS",
        )
        # The ferry is flown while the lease is still ACTIVE, because PRD §3.6 makes
        # `the lease must be ACTIVE` a dispatch-time gate.
        flown = fly_leg(
            api,
            scenario,
            "2026-09-20T06:00:00Z",
            "2026-09-20T08:00:00Z",
            actual_out="2026-09-20T06:05:00Z",
            actual_in="2026-09-20T08:05:00Z",
            **ferry_kwargs,
        )
        # A second ferry stays SCHEDULED through termination (PRD §3.10 spares
        # repositioning legs), so closure naming it is still incomplete.
        unflown = schedule_leg(
            api,
            scenario,
            "2026-09-21T06:00:00Z",
            "2026-09-21T08:00:00Z",
            **ferry_kwargs,
        )
        return_condition = terminate_lease(api, lease_id)
        inspect_return(
            api,
            return_condition["id"],
            hours_since_check_at_return=280.00,
            cycles_since_check_at_return=100,
            fuel_on_board_kg=4200,
            discrepancy_codes=[],
        )

        validate_error(
            api.close_return_condition(
                return_condition["id"], close_return_payload(unflown["id"]), OPS
            ),
            ApiErrorId.ERR_REPOSITIONING_LEG_INCOMPLETE,
            409,
        )

        assert flown["status"] == "COMPLETED", (
            f"the ferry must close out COMPLETED, got {flown['status']}"
        )
        assert flown["billable_block_minutes"] == 120, (
            "a repositioning leg bills its block minutes exactly, expected 120, got "
            f"{flown['billable_block_minutes']}"
        )

        closed = validate_success(
            api.close_return_condition(
                return_condition["id"], close_return_payload(flown["id"]), OPS
            )
        )
        assert closed["status"] == "CLOSED", (
            f"closure must land the record in CLOSED, got {closed['status']}"
        )
        assert closed["repositioning_leg_id"] == flown["id"], (
            f"closure must store the ferry leg id {flown['id']}, got "
            f"{closed['repositioning_leg_id']}"
        )

        lease = get_success_data(api.get_lease(lease_id, OPS))
        assert lease["status"] == "RETURNED", (
            f"closure must drive the lease to RETURNED, got {lease['status']}"
        )

        aircraft = get_success_data(api.get_aircraft(scenario["aircraft"]["id"], TECH))
        assert aircraft["status"] == "AVAILABLE", (
            f"closure must release the airframe to AVAILABLE, got {aircraft['status']}"
        )
        assert aircraft["assigned_lease_id"] is None, (
            "closure must clear assigned_lease_id, got "
            f"{aircraft['assigned_lease_id']}"
        )

        qualifications, meta = validate_paginated(
            api.list_crew_qualifications(OPS, params={"lease_id": lease_id})
        )
        assert meta["total_count"] == 2, (
            f"both pilots' qualifications must be listed, expected 2, got {meta['total_count']}"
        )
        for qualification in qualifications:
            assert qualification["status"] == "REVOKED", (
                "closure must revoke every qualification on the lease, got "
                f"{qualification['status']}"
            )


# --------------------------------------------------------------------------- #
# Lessee commercial standing                                                   #
# --------------------------------------------------------------------------- #


def test_scheduling_a_leg_for_a_suspended_lessee_is_refused(api):
    """PRD §3.1: Suspension is deliberately forward-looking: while it holds, no lease of that lessee may be submitted for approval or activated and no new leg may be scheduled — each such attempt is rejected with `ERR_LESSEE_SUSPENDED` — but flying already rostered continues, no already-`ACTIVE` lease is suspended or terminated, and no already-`SCHEDULED` leg is cancelled.
    PRD §2.8: **Lessee commercial standing** — the lease's lessee must be `ACTIVE`, else `ERR_LESSEE_SUSPENDED` (HTTP 403). This guards exactly three operations: submitting a lease for approval, activating a lease, and scheduling a flight leg.
    PRD §3.5: `suspension_reason` is null in every state other than `SUSPENDED`.

    Design: Corner/validations/suspended_lessee_cannot_schedule_a_new_flight_leg
    """
    scenario = setup_active_lease(api)
    lease_id = scenario["lease"]["id"]
    suspended = validate_success(api.suspend_lessee(scenario["lessee"]["id"], BILLING))
    assert suspended["status"] == "SUSPENDED", (
        f"setup expected the lessee SUSPENDED, got {suspended['status']}"
    )

    payload = create_flight_leg_payload(
        lease_id,
        scenario["aircraft"]["id"],
        scenario["captain"]["id"],
        scenario["first_officer"]["id"],
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:35:30Z",
    )
    validate_error(
        api.create_flight_leg(payload, OPS),
        ApiErrorId.ERR_LESSEE_SUSPENDED,
        403,
    )

    lease = get_success_data(api.get_lease(lease_id, OPS))
    assert lease["status"] == "ACTIVE", (
        "a credit-control suspension is not a lease suspension, expected ACTIVE, got "
        f"{lease['status']}"
    )
    assert lease["suspension_reason"] is None, (
        f"an ACTIVE lease must carry a null suspension_reason, got {lease['suspension_reason']}"
    )
    aircraft = get_success_data(api.get_aircraft(scenario["aircraft"]["id"], TECH))
    assert aircraft["status"] == "ASSIGNED", (
        f"the airframe must stay on the lease, expected ASSIGNED, got {aircraft['status']}"
    )


# --------------------------------------------------------------------------- #
# Substitution gates                                                           #
# --------------------------------------------------------------------------- #


def _consent_required_lease_with_candidate(api):
    """ACTIVE consent-required lease plus one eligible B739 substitute, G-SUBA."""
    scenario = setup_active_lease(
        api, lease_overrides={"substitution_rights": "LESSEE_CONSENT_REQUIRED"}
    )
    substitute = add_substitute_candidate(
        api,
        tail_number="G-SUBA",
        type_designator="B739",
        type_family="B737",
        seat_count=189,
        mtow_kg=85000,
        airframe_hours_total=12000.00,
        hours_since_last_check=90.00,
        cycles_since_last_check=20,
    )
    scenario["lease"] = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
    substitution = request_substitution(
        api,
        scenario,
        substitute_aircraft_id=substitute["id"],
        effective_from="2026-09-20T00:00:00Z",
    )
    return scenario, substitute, substitution


class TestSubstitutionConsentGate:
    def test_effectuation_before_lessee_consent_reports_consent_required(self, api):
        """PRD §3.7: An effectuation attempted while the request is still awaiting lessee consent on a consent-required lease is refused with `ERR_SUBSTITUTION_CONSENT_REQUIRED` (HTTP 403) — a lessor operator may never move a pending request to `APPROVED` by this route.
        PRD §2.8: An effectuation attempted on a substitution still awaiting lessee consent, on a lease whose substitution rights require that consent, deliberately *passes* the substitution state guard and falls through to the consent gate, so the caller receives `ERR_SUBSTITUTION_CONSENT_REQUIRED` rather than `ERR_SUBSTITUTION_INVALID_STATE`; every other undeclared source state for effectuation — a request still `REQUESTED`, or already `REJECTED`, `EFFECTIVE` or `WITHDRAWN` — and every source state other than awaiting-consent for a consent decision, is reported as `ERR_SUBSTITUTION_INVALID_STATE`.
        PRD §3.7: On a lease whose rights are `LESSEE_CONSENT_REQUIRED` the request lands in `LESSEE_CONSENT_PENDING`, `seat_delta` is written, no airframe is touched yet, and no prior request on the lease is disturbed.

        Design: Corner/validations/effectuating_before_lessee_consent_returns_consent_required_not_invalid_state
        """
        scenario, substitute, substitution = _consent_required_lease_with_candidate(api)

        validate_error(
            api.effectuate_substitution(substitution["id"], OPS),
            ApiErrorId.ERR_SUBSTITUTION_CONSENT_REQUIRED,
            403,
        )

        pending = get_success_data(api.get_substitution(substitution["id"], OPS))
        assert pending["status"] == "LESSEE_CONSENT_PENDING", (
            "the refused effectuation must leave the request awaiting consent, got "
            f"{pending['status']}"
        )
        lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["primary_aircraft_id"] == scenario["aircraft"]["id"], (
            "no airframe may be touched before consent, expected the original "
            f"{scenario['aircraft']['id']}, got {lease['primary_aircraft_id']}"
        )

    def test_effectuation_admitted_after_the_lessee_grants_consent(self, api):
        """PRD §3.7: An effectuation attempted while the request is still awaiting lessee consent on a consent-required lease is refused with `ERR_SUBSTITUTION_CONSENT_REQUIRED` (HTTP 403) — a lessor operator may never move a pending request to `APPROVED` by this route.
        PRD §3.7: `GRANT` moves the request from `LESSEE_CONSENT_PENDING` to `APPROVED`; `WITHHOLD` moves it to the terminal `REJECTED` and the original airframe stays on the lease.
        PRD §3.7: Level one: the substitute's `status` becomes `ASSIGNED` and its `assigned_lease_id` the lease; the original airframe has `assigned_lease_id` cleared and its `status` moved from `ASSIGNED` to `AVAILABLE`, except that an original already `IN_MAINTENANCE` or `AOG` keeps that status; and the lease's `primary_aircraft_id` is re-pointed to the substitute.

        Design: Corner/validations/effectuating_before_lessee_consent_returns_consent_required_not_invalid_state
        """
        scenario, substitute, substitution = _consent_required_lease_with_candidate(api)
        lease_id = scenario["lease"]["id"]

        validate_error(
            api.effectuate_substitution(substitution["id"], OPS),
            ApiErrorId.ERR_SUBSTITUTION_CONSENT_REQUIRED,
            403,
        )

        granted = consent_to_substitution(
            api,
            scenario,
            substitution["id"],
            decision="GRANT",
            consent_note="acceptable for the Palma rotation",
        )
        assert granted["status"] == "APPROVED", (
            f"a GRANT must move the request to APPROVED, got {granted['status']}"
        )
        assert granted["consent_note"] == "acceptable for the Palma rotation", (
            f"the consent note must be recorded, got {granted['consent_note']}"
        )

        effective = validate_success(
            api.effectuate_substitution(substitution["id"], OPS)
        )
        assert effective["status"] == "EFFECTIVE", (
            f"effectuation must land the request in EFFECTIVE, got {effective['status']}"
        )
        assert effective["repointed_leg_count"] == 0, (
            "no leg exists to re-point, expected repointed_leg_count 0, got "
            f"{effective['repointed_leg_count']}"
        )

        lease = get_success_data(api.get_lease(lease_id, OPS))
        assert lease["primary_aircraft_id"] == substitute["id"], (
            "the lease's airframe of record must be re-pointed to the substitute, "
            f"expected {substitute['id']}, got {lease['primary_aircraft_id']}"
        )
        swapped_in = get_success_data(api.get_aircraft(substitute["id"], TECH))
        assert swapped_in["status"] == "ASSIGNED", (
            f"the substitute must become ASSIGNED, got {swapped_in['status']}"
        )
        swapped_out = get_success_data(
            api.get_aircraft(scenario["aircraft"]["id"], TECH)
        )
        assert swapped_out["status"] == "AVAILABLE", (
            f"the original must return to AVAILABLE, got {swapped_out['status']}"
        )
        assert swapped_out["assigned_lease_id"] is None, (
            "the original's assigned_lease_id must be cleared, got "
            f"{swapped_out['assigned_lease_id']}"
        )


class TestClientSpecifiedSubstituteEligibility:
    WRONG_FAMILY = {
        "tail_number": "G-OTHR",
        "type_designator": "A321",
        "type_family": "A320",
        "seat_count": 220,
        "mtow_kg": 93000,
        "airframe_hours_total": 6000.00,
        "hours_since_last_check": 5.00,
        "cycles_since_last_check": 2,
    }
    ONE_SEAT_TOO_FEW = {
        "tail_number": "G-SMLL",
        "type_designator": "B737",
        "type_family": "B737",
        "seat_count": 183,
        "mtow_kg": 66000,
        "airframe_hours_total": 9000.00,
        "hours_since_last_check": 5.00,
        "cycles_since_last_check": 2,
    }

    @pytest.mark.parametrize(
        "candidate",
        [WRONG_FAMILY, ONE_SEAT_TOO_FEW],
        ids=["wrong_type_family", "one_seat_below_the_tolerance_floor"],
    )
    def test_client_specified_substitute_failing_an_eligibility_clause_is_refused(
        self, api, candidate
    ):
        """PRD §3.7: When `substitute_aircraft_id` is supplied, `selection_basis` is recorded as `CLIENT_SPECIFIED` and the named airframe must satisfy every eligibility test: its `type_family` must equal the original's `type_family` (the exact `type_designator` may differ, which is what makes the crew-rating cascade reachable), its `seat_count` must be at least the original's `seat_count` less a tolerance of five seats, its `status` must be `AVAILABLE`, its `assigned_lease_id` must be null, and its `hours_since_last_check` must not exceed 400.00 hours.
        PRD §3.7: A failure on any of these is refused with `ERR_SUBSTITUTION_TYPE_MISMATCH` (HTTP 422).
        PRD §3.7: Either way the request records `seat_delta` as the substitute's `seat_count` less the original's `seat_count` — a figure the lessee needs for its consent decision — and `repointed_leg_count` as 0 at creation, and the lease's `version` increments by 1.

        Design: Corner/validations/client_specified_substitute_of_the_wrong_family_or_too_few_seats_is_rejected
        """
        scenario = setup_active_lease(api)
        lease_id = scenario["lease"]["id"]
        ineligible = create_aircraft(
            api, maintenance_program_ref=TEST_DEFAULTS["MAINTENANCE_PROGRAM_REF"], **candidate
        )
        lease = get_success_data(api.get_lease(lease_id, OPS))
        lease_version = lease["version"]

        payload = create_substitution_payload(
            lease_id,
            scenario["aircraft"]["id"],
            lease_version,
            substitute_aircraft_id=ineligible["id"],
            effective_from="2026-09-20T00:00:00Z",
        )
        validate_error(
            api.create_substitution(payload, OPS),
            ApiErrorId.ERR_SUBSTITUTION_TYPE_MISMATCH,
            422,
        )

        substitutions, meta = validate_paginated(
            api.list_substitutions(OPS, params={"lease_id": lease_id})
        )
        assert meta["total_count"] == 0, (
            "a refused request must leave no substitution row, expected total_count 0, "
            f"got {meta['total_count']}"
        )

        after = get_success_data(api.get_lease(lease_id, OPS))
        assert after["primary_aircraft_id"] == scenario["aircraft"]["id"], (
            "the lease's airframe of record must not move, expected "
            f"{scenario['aircraft']['id']}, got {after['primary_aircraft_id']}"
        )
        assert after["version"] == lease_version, (
            "a refused request must not increment the lease version, expected "
            f"{lease_version}, got {after['version']}"
        )


# --------------------------------------------------------------------------- #
# Credit ceiling on settlement                                                 #
# --------------------------------------------------------------------------- #


def test_invoice_beyond_the_credit_limit_is_refused_with_payment_required(api):
    """PRD §3.9: Issue is admissible only from `APPROVED` and requires that the lessee's `outstanding_balance_usd_cents` plus the invoice's `amount_cents` not exceed the lessee's `credit_limit_usd_cents`; a breach is refused with `ERR_LESSEE_CREDIT_LIMIT_EXCEEDED` (HTTP 402).
    PRD §3.9: The same ceiling is tested at preparation time against the amount about to be invoiced.
    PRD §2.9: `Lessee.outstanding_balance_usd_cents` equals the sum of `amount_cents` over every `SettlementInvoice` whose `status` is `ISSUED` and whose lease belongs to that lessee.
    PRD §3.8: It also opens the following month's period with `status` `OPEN`, but only when that next month still falls inside the lease term and the lease's `status` is `ACTIVE` or `SUSPENDED`.

    Design: Corner/validations/second_invoice_beyond_the_credit_limit_returns_payment_required
    """
    limit = 2_400_000
    scenario = setup_active_lease(
        api,
        lessee_overrides={"credit_limit_usd_cents": limit},
        with_first_officer=False,
    )
    lease_id = scenario["lease"]["id"]

    # September: one month's guarantee, invoiced at exact equality with the ceiling.
    september = close_month(api, scenario["period"]["id"])
    september_invoice = prepare_invoice(
        api, september, due_on="2026-10-15", variant="FINAL", headers=PREPARER
    )
    file_reliability_report(api, scenario, period_month="2026-09")
    approve_invoice(api, september_invoice["id"], headers=APPROVER)
    issued = issue_invoice(api, september_invoice["id"], headers=APPROVER)
    assert issued["status"] == "ISSUED", (
        f"the September invoice must issue at exact equality, got {issued['status']}"
    )
    assert issued["amount_cents"] == limit, (
        f"expected an invoice of {limit} cents, got {issued['amount_cents']}"
    )
    assert issued["variant"] == "FINAL", (
        f"expected a FINAL invoice, got {issued['variant']}"
    )

    # October opened on the September close; closing it prices a second full guarantee.
    october = close_month(api, period_for_month(api, lease_id, "2026-10")["id"])
    assert october["status"] == "PENDING_SETTLEMENT", (
        f"the October close must land in PENDING_SETTLEMENT, got {october['status']}"
    )
    assert october["final_charge_cents"] == limit, (
        f"expected an October final charge of {limit} cents, got "
        f"{october['final_charge_cents']}"
    )

    validate_error(
        api.create_settlement_invoice(
            create_settlement_invoice_payload(
                october["id"], october["version"], "2026-11-15", variant="FINAL"
            ),
            PREPARER,
        ),
        ApiErrorId.ERR_LESSEE_CREDIT_LIMIT_EXCEEDED,
        402,
    )

    lessee = get_success_data(api.get_lessee(scenario["lessee"]["id"], BILLING))
    assert lessee["outstanding_balance_usd_cents"] == limit, (
        f"the receivable must stand at {limit} cents, got "
        f"{lessee['outstanding_balance_usd_cents']}"
    )
    assert lessee["credit_limit_usd_cents"] == limit, (
        f"expected a credit limit of {limit} cents, got {lessee['credit_limit_usd_cents']}"
    )

    invoices, meta = validate_paginated(
        api.list_settlement_invoices(BILLING, params={"period_id": october["id"]})
    )
    assert meta["total_count"] == 0, (
        "a refused preparation must leave no invoice row for October, expected "
        f"total_count 0, got {meta['total_count']}"
    )
