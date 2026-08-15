"""Property condition scoring variants, posture gate, and conveyance lockdown."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.factories import create_work_order_payload
from test_helpers.fixtures import (
    create_code_violation,
    create_damage_report,
    create_inspection,
    create_work_order,
    record_inspection,
    setup_portfolio,
)
from test_helpers.test_users import TEST_USERS, make_servicer_headers

ADMIN = TEST_USERS["vendor_admin_headers"]


def _scored_property_with_interior_damage(ctx):
    """One MINOR violation (-15), no ACTIVE registration (-20), two open interior
    damage reports; no completed inspection yet."""
    create_code_violation(ctx["property_id"], citation_number="CV-100",
                          violation_class="MINOR", daily_fine_cents=500,
                          fine_cap_cents=50000, cure_deadline="2026-09-01")
    create_damage_report(ctx["property_id"], ctx["crew_id"], damage_type="WATER",
                         severity="MODERATE", is_interior=True, description="kitchen leak")
    create_damage_report(ctx["property_id"], ctx["crew_id"], damage_type="WATER",
                         severity="MINOR", is_interior=True, description="bath leak")


class TestConditionScoreVariants:
    def test_condition_score_exterior_only_variant(self, api):
        """PRD: "The score starts at 100. From it are deducted: for each of the
        property's code violations in `OPEN`, `CURE_IN_PROGRESS`, `CURE_SUBMITTED`,
        or `ESCALATED`, 15 points for a `MINOR` violation, 25 for a `MAJOR`, and 40
        for a `HAZARDOUS`, with the total violation deduction capped at 45 points;
        20 points when no `ACTIVE` municipal registration covers the property's
        `municipality_code` at the clock date" and "under the exterior-only variant
        — the latest completed inspection lacked interior access, or no completed
        inspection exists — interior damage is ignored entirely" and "a score from
        50 through 79 inclusive yields `AT_RISK`".

        Design: Difficulty/dual_variant_calc/property_condition_score_interior_variants
        """
        ctx = setup_portfolio(with_allowable=False,
                              property_overrides={"heating_system": "NONE", "fixture_count": 4,
                                                  "lot_size_sqft": 7000})
        _scored_property_with_interior_damage(ctx)
        ins = create_inspection(ctx["property_id"], due_date="2026-08-02")
        record_inspection(ins["id"], ctx["crew_id"], occupancy_determination="VACANT",
                          interior_access=False)
        prop = validate_success(api.get_property(ctx["property_id"], ADMIN))
        assert prop["condition_score"] == 65, (
            f"exterior-only score is 100 - 15 violation - 20 lapsed registration, got {prop['condition_score']}")
        assert prop["compliance_posture"] == "AT_RISK", f"65 lands AT_RISK, got {prop['compliance_posture']}"

    def test_condition_score_interior_inclusive_variant(self, api):
        """PRD: "The variant is chosen by interior access: when the latest
        `COMPLETED` inspection has `interior_access` true (the interior-inclusive
        variant), a further 15 points are deducted per open interior damage report —
        one with `is_interior` true in those same open statuses — capped at 30
        points" and "a score below 50 yields `NON_COMPLIANT`".

        Design: Difficulty/dual_variant_calc/property_condition_score_interior_variants
        """
        ctx = setup_portfolio(with_allowable=False,
                              property_overrides={"heating_system": "NONE", "fixture_count": 4,
                                                  "lot_size_sqft": 7000})
        _scored_property_with_interior_damage(ctx)
        ins1 = create_inspection(ctx["property_id"], due_date="2026-08-02")
        record_inspection(ins1["id"], ctx["crew_id"], occupancy_determination="VACANT",
                          interior_access=False)
        ins2 = create_inspection(ctx["property_id"], due_date="2026-08-03")
        record_inspection(ins2["id"], ctx["crew_id"], occupancy_determination="VACANT",
                          interior_access=True)
        prop = validate_success(api.get_property(ctx["property_id"], ADMIN))
        assert prop["condition_score"] == 35, (
            f"interior-inclusive score is 65 - 30 for two open interior damages, got {prop['condition_score']}")
        assert prop["compliance_posture"] == "NON_COMPLIANT", (
            f"35 lands NON_COMPLIANT, got {prop['compliance_posture']}")


class TestPostureGate:
    def test_posture_noncompliant_blocks_grass_cut(self, api):
        """PRD: "A property whose `compliance_posture` is `NON_COMPLIANT` may not
        receive new `GRASS_CUT` or `SNOW_REMOVAL` work orders — creation of such an
        order is rejected with `ERR_POSTURE_BLOCKS_ORDER` — until the score
        recovers." Scoring per "40 for a `HAZARDOUS`" violation, "20 points when no
        `ACTIVE` municipal registration covers", and "10 points for each of the
        property's damage reports in `REPORTED`, `TRIAGED`, `BID_REQUESTED`, or
        `REPAIR_IN_PROGRESS` whose `is_interior` is false, capped at 20 points".

        Design: Corner/errors/posture_noncompliant_blocks_grass_cut
        """
        ctx = setup_portfolio(item_code="GRASS_CUT",
                              property_overrides={"heating_system": "NONE", "fixture_count": 4})
        # Second allowable: SECURING maps to LOCK_CHANGE and is not posture-gated.
        from test_helpers.fixtures import create_allowable
        create_allowable(item_code="LOCK_CHANGE", max_per_occurrence_cents=20000,
                         max_occurrences_per_calendar_year=4,
                         aggregate_cap_cents_per_property_year=80000)
        create_code_violation(ctx["property_id"], citation_number="CV-600",
                              violation_class="HAZARDOUS", daily_fine_cents=2000,
                              fine_cap_cents=80000, cure_deadline="2026-09-01")
        create_damage_report(ctx["property_id"], ctx["crew_id"], damage_type="VANDALISM",
                             severity="MODERATE", is_interior=False, description="fence broken")
        create_damage_report(ctx["property_id"], ctx["crew_id"], damage_type="VANDALISM",
                             severity="MINOR", is_interior=False, description="window smashed")
        prop = validate_success(api.get_property(ctx["property_id"], ADMIN))
        assert prop["condition_score"] == 20, f"score 20, got {prop['condition_score']}"
        assert prop["compliance_posture"] == "NON_COMPLIANT"
        blocked = api.create_work_order(
            create_work_order_payload(ctx["property_id"], order_type="GRASS_CUT",
                                      due_date="2026-08-10"),
            make_servicer_headers(ctx["servicer_id"]))
        validate_error(blocked, ApiErrorId.ERR_POSTURE_BLOCKS_ORDER)
        allowed = api.create_work_order(
            create_work_order_payload(ctx["property_id"], order_type="SECURING",
                                      due_date="2026-08-10"),
            make_servicer_headers(ctx["servicer_id"]))
        assert validate_success(allowed, expected_status=201)["status"] == "ISSUED", (
            "the gate is order-type specific: SECURING creation succeeds")


class TestConveyanceLockdown:
    def test_conveyed_property_rejects_work_order_creation(self, api):
        """PRD: "Once `CONVEYED`, the property rejects further work order creation
        with `ERR_PROPERTY_NOT_ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/work_order_create_blocked_when_property_conveyed
        """
        ctx = setup_portfolio(item_code="GRASS_CUT", with_crew=False,
                              property_overrides={"heating_system": "NONE", "fixture_count": 4})
        conveyed = validate_success(api.convey_property(
            ctx["property_id"], make_servicer_headers(ctx["servicer_id"])))
        assert conveyed["status"] == "CONVEYED"
        resp = api.create_work_order(
            create_work_order_payload(ctx["property_id"], order_type="GRASS_CUT",
                                      due_date="2026-08-20"),
            make_servicer_headers(ctx["servicer_id"]))
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_ACTIVE)

    def test_active_property_accepts_then_conveyed_rejects(self, api):
        """PRD: "the property must be `ACTIVE` (`ERR_PROPERTY_NOT_ACTIVE`)" gates
        creation, and "A `Servicer` may cancel an order in `ISSUED`, `ASSIGNED`, or
        `IN_PROGRESS`" lets the portfolio reach a conveyable state first.

        Design: Difficulty/cross_entity_state_dependency/work_order_create_blocked_when_property_conveyed
        """
        ctx = setup_portfolio(item_code="GRASS_CUT", with_crew=False,
                              property_overrides={"heating_system": "NONE", "fixture_count": 4})
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="GRASS_CUT", due_date="2026-08-20")
        assert wo["status"] == "ISSUED", "creation succeeds while the property is ACTIVE"
        validate_success(api.cancel_work_order(wo["id"], {"reason": "not needed"},
                                               make_servicer_headers(ctx["servicer_id"])))
        validate_success(api.convey_property(ctx["property_id"],
                                             make_servicer_headers(ctx["servicer_id"])))
        resp = api.create_work_order(
            create_work_order_payload(ctx["property_id"], order_type="GRASS_CUT",
                                      due_date="2026-08-20"),
            make_servicer_headers(ctx["servicer_id"]))
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_ACTIVE)
