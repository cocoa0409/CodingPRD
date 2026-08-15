"""Regulatory directives, retrofit orders, penalty variants, and the
cleaning re-clean cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    certify_retrofit_order,
    create_cleaning,
    create_directive,
    create_railcar,
    create_lease_assignment_payload,
    create_retrofit,
    get_assignment,
    get_railcar,
    get_success_data,
    promote_directive,
    set_clock,
    setup_active_lease_scenario,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["fleet_planner_headers"]
MAINT = TEST_USERS["maintenance_controller_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestRetrofitPenaltyVariants:
    def _setup_non_compliant_car(self, api):
        car = create_railcar(car_mark="GATX3001", car_type="TANK_GENERAL",
                             built_year=2015)
        directive = create_directive(
            directive_code="DOT-117R", description="Tank car retrofit",
            applies_to_car_types=["TANK_GENERAL"],
            retrofit_deadline="2026-12-31", grace_days=30,
            daily_penalty_cents=25000, penalty_cap_cents=500000,
        )
        promote_directive(directive["id"])  # effective at 2026-08-01 default
        set_clock("2026-09-15T00:00:00Z")
        return car, directive

    def test_accrued_variant_ignores_grace_and_cap(self, api):
        """PRD §3.11: "The **accrued** variant — forward-looking exposure —
        is simply the days since effective multiplied by
        `daily_penalty_cents`, ignoring grace and cap entirely." and "the
        days since effective is the calendar-day difference from
        `effective_date` to the current date, floored at zero."

        Design: Difficulty/dual_variant_calc/retrofit_penalty_accrued_vs_assessed
        """
        car, _directive = self._setup_non_compliant_car(api)
        view = validate_success(api.get_railcar_compliance(car["id"], COMPLIANCE))
        assert view["posture"] == "NON_COMPLIANT"
        assert view["days_since_oldest_effective"] == 45, (
            "2026-08-01 to 2026-09-15"
        )
        assert view["accrued_penalty_cents"] == 1125000, "45 x 25000"

    def test_assessed_variant_applies_grace_and_cap(self, api):
        """PRD §3.11: "The **assessed** variant — the billing basis — counts
        only the days beyond `grace_days` (days since effective minus
        `grace_days`, floored at zero), multiplies by `daily_penalty_cents`,
        and caps the result at `penalty_cap_cents`; a car certified within
        its grace period assesses zero."

        Design: Difficulty/dual_variant_calc/retrofit_penalty_accrued_vs_assessed
        """
        car, _directive = self._setup_non_compliant_car(api)
        view = validate_success(api.get_railcar_compliance(car["id"], COMPLIANCE))
        # (45 - 30) x 25000 = 375000, under the 500000 cap.
        assert view["assessed_penalty_cents"] == 375000
        assert view["accrued_penalty_cents"] - view["assessed_penalty_cents"] == 750000, (
            "The delta is exactly the 30 grace days x 25000 daily penalty"
        )


class TestDirectivePromoteCascade:
    def _setup(self, api):
        scenario = setup_active_lease_scenario(
            car_mark="GATX8001", car_type="TANK_GENERAL", built_year=2018,
            commodity="CRUDE_OIL", base_daily_rate_cents=6000,
            hire_rate=12000, mileage_rate=60,
            window_start="2026-08-10", window_end="2026-09-10",
            company_name="PetroTrans",
        )
        directive = create_directive(
            directive_code="DOT-117R", description="Tank car retrofit",
            applies_to_car_types=["TANK_GENERAL"],
            retrofit_deadline="2026-12-31", grace_days=30,
            daily_penalty_cents=25000, penalty_cap_cents=500000,
        )
        return scenario, directive

    def test_promote_marks_covered_cars_non_compliant(self, api):
        """PRD §3.11: "Promoting a directive (`ANNOUNCED → EFFECTIVE`, a
        `ComplianceOfficer` action) stamps `effective_date` with the current
        logical date and fires a cascade. First hop: every railcar whose
        `car_type` is in `applies_to_car_types` and which has no `CERTIFIED`
        retrofit order for this directive becomes `NON_COMPLIANT`."
        PRD §2.5: "Before any client sets it, the logical clock reads exactly
        2026-08-01T00:00:00Z."

        Design: Difficulty/transitive_cascade/directive_promote_two_hop_cascade
        """
        scenario, directive = self._setup(api)
        promoted = validate_success(
            api.promote_directive(directive["id"], COMPLIANCE)
        )
        assert promoted["status"] == "EFFECTIVE"
        assert promoted["effective_date"] == "2026-08-01"
        car = get_railcar(scenario["railcar"]["id"])
        assert car["compliance_posture"] == "NON_COMPLIANT"

    def test_promote_cancels_scheduled_assignments_on_covered_cars(self, api):
        """PRD §3.11: "Second hop: every `SCHEDULED` lease assignment on each
        such railcar is cancelled with `cancellation_reason`
        `DIRECTIVE_EFFECTIVE`."

        Design: Difficulty/transitive_cascade/directive_promote_two_hop_cascade
        """
        scenario, directive = self._setup(api)
        get_success_data(api.promote_directive(directive["id"], COMPLIANCE))
        assignment = get_assignment(scenario["assignment"]["id"])
        assert assignment["status"] == "CANCELLED"
        assert assignment["cancellation_reason"] == "DIRECTIVE_EFFECTIVE"


class TestRetrofitUngatesAssignment:
    def _setup_non_compliant_tank(self, api):
        scenario = setup_active_lease_scenario(
            car_mark="GATX9203", car_type="TANK_GENERAL", built_year=2018,
            base_daily_rate_cents=6000, hire_rate=12000, mileage_rate=60,
            with_assignment=False,
        )
        directive = create_directive(
            directive_code="DOT-117P", description="Pressure retrofit",
            applies_to_car_types=["TANK_GENERAL"],
            retrofit_deadline="2026-12-31", grace_days=30,
            daily_penalty_cents=25000, penalty_cap_cents=500000,
        )
        promote_directive(directive["id"])
        return scenario, directive

    def test_non_compliant_car_rejected_from_assignment(self, api):
        """PRD §2.10: "Second, regulatory posture: a car whose
        `compliance_posture` is `NON_COMPLIANT` is rejected with
        `ERR_TANK_CAR_NONCOMPLIANT`."

        Design: Difficulty/cross_entity_state_dependency/retrofit_certification_ungates_tank_assignment
        """
        scenario, _directive = self._setup_non_compliant_tank(api)
        car = get_railcar(scenario["railcar"]["id"])
        assert car["compliance_posture"] == "NON_COMPLIANT"
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=scenario["lease"]["id"],
                railcar_id=scenario["railcar"]["id"],
                planned_commodity="ETHANOL",
                scheduled_start="2026-08-10",
                scheduled_end="2026-09-10",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_TANK_CAR_NONCOMPLIANT, 422)

    def test_certified_retrofit_restores_assignment_eligibility(self, api):
        """PRD §3.11: "Certification recomputes the car's
        `compliance_posture`: the car is `COMPLIANT` exactly when every
        `EFFECTIVE` directive covering its car type has a `CERTIFIED`
        retrofit for the car."
        PRD §3.4: "When coverage exists, the two rates effective at
        `scheduled_start` are snapshotted onto the assignment as
        `pinned_car_hire_daily_cents` and `pinned_mileage_credit_cents` —
        these pinned values, not the live grid, later price the final
        settlement variant."

        Design: Difficulty/cross_entity_state_dependency/retrofit_certification_ungates_tank_assignment
        """
        scenario, directive = self._setup_non_compliant_tank(api)
        order = create_retrofit(scenario["railcar"]["id"], directive["id"],
                                "2026-08-10")
        certify_retrofit_order(order["id"], "CERT-9203")
        car = get_railcar(scenario["railcar"]["id"])
        assert car["compliance_posture"] == "COMPLIANT"
        created = validate_success(
            api.create_lease_assignment(
                create_lease_assignment_payload(
                    lease_id=scenario["lease"]["id"],
                    railcar_id=scenario["railcar"]["id"],
                    planned_commodity="ETHANOL",
                    scheduled_start="2026-08-10",
                    scheduled_end="2026-09-10",
                ),
                PLANNER,
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["pinned_car_hire_daily_cents"] == 12000
        assert created["pinned_mileage_credit_cents"] == 60


class TestRetrofitScheduling:
    def test_retrofit_scheduled_past_deadline_rejected(self, api):
        """PRD §3.11: "A `MaintenanceController` schedules the per-car
        remediation as a retrofit order naming `railcar_id`, `directive_id`,
        and a `scheduled_date` that must be on or before the directive's
        `retrofit_deadline` (`ERR_RETROFIT_DEADLINE_PASSED`, 422)."

        Design: Corner/validations/retrofit_scheduled_past_deadline_rejected
        """
        car = create_railcar(car_mark="GATX1406", car_type="TANK_GENERAL",
                             built_year=2015)
        directive = create_directive(
            directive_code="DOT-111X", description="d",
            applies_to_car_types=["TANK_GENERAL"],
            retrofit_deadline="2026-08-31", grace_days=30,
            daily_penalty_cents=10000, penalty_cap_cents=300000,
        )
        resp = api.create_retrofit_order(
            {
                "railcar_id": car["id"],
                "directive_id": directive["id"],
                "scheduled_date": "2026-09-01",
            },
            MAINT,
        )
        validate_error(resp, ApiErrorId.ERR_RETROFIT_DEADLINE_PASSED, 422)


class TestDirectiveUniqueness:
    def test_duplicate_directive_code_rejected(self, api):
        """PRD §3.11: "A `ComplianceOfficer` announces a directive with a
        unique `directive_code` such as DOT-117R (duplicates fail with
        `ERR_DUPLICATE_DIRECTIVE_CODE`, 409)".

        Design: Corner/validations/duplicate_directive_code_rejected
        """
        create_directive(
            directive_code="DOT-999", description="d1",
            applies_to_car_types=["TANK_PRESSURE"],
            retrofit_deadline="2027-01-01", grace_days=30,
            daily_penalty_cents=10000, penalty_cap_cents=100000,
        )
        resp = api.create_compliance_directive(
            {
                "directive_code": "DOT-999",
                "description": "d2",
                "applies_to_car_types": ["TANK_GENERAL"],
                "retrofit_deadline": "2027-06-01",
                "grace_days": 15,
                "daily_penalty_cents": 5000,
                "penalty_cap_cents": 50000,
            },
            COMPLIANCE,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DIRECTIVE_CODE, 409)


class TestCleaningRecleanCycle:
    def test_cleaning_fail_reclean_cycle_to_certified(self, api):
        """PRD §3.10: "Recording a performed cleaning (from `SCHEDULED`, or
        from `FAILED` for a re-clean cycle) carries the
        `cleaning_grade_performed` and the non-negative `cost_cents`. ... On
        completion the record is `COMPLETED` and the cost is recorded
        (replaced, in a re-clean cycle)." and "`CERTIFIED` is terminal;
        `FAILED` loops back through completion."
        PRD §3.10: "`cleaning_grade_required` is `STEAM_CLEAN` when the prior
        commodity is `CRUDE_OIL`, `GASOLINE`, or `CHEMICAL_SOLVENT`, and
        `WASH` otherwise; `bill_to` is `LESSEE` when `attributable_to_lessee`
        is true and `LESSOR` otherwise."

        Design: Corner/state_machines/cleaning_fail_reclean_cycle_to_certified
        """
        car = create_railcar(car_mark="GATX1205", built_year=2015)
        cleaning = create_cleaning(car["id"], prior_commodity="GRAIN",
                                   next_commodity="COAL",
                                   planned_date="2026-08-16")
        assert cleaning["cleaning_grade_required"] == "WASH"
        assert cleaning["bill_to"] == "LESSOR"
        get_success_data(api.complete_cleaning(cleaning["id"], "WASH", 50000,
                                               MAINT))
        get_success_data(api.fail_cleaning(cleaning["id"], "residue found",
                                           COMPLIANCE))
        # FAILED is not terminal: the re-clean cycle completes with a
        # STEAM_CLEAN (which also satisfies the WASH requirement).
        recompleted = validate_success(
            api.complete_cleaning(cleaning["id"], "STEAM_CLEAN", 90000, MAINT)
        )
        assert recompleted["status"] == "COMPLETED"
        assert recompleted["cost_cents"] == 90000, "Cost replaced on re-clean"
        assert recompleted["cleaning_grade_performed"] == "STEAM_CLEAN"
        certified = validate_success(
            api.certify_cleaning(cleaning["id"], "CLN-1205", COMPLIANCE)
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["certificate_ref"] == "CLN-1205"
