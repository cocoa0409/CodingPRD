"""Damage assessments: estimate vs assessed variants, pinned rounding, disputes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_building_turn_active,
    create_damage_assessment_payload,
    create_damage_line_item,
    get_success_data,
    make_coordinator_headers,
    set_clock,
    setup_checked_in_group,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
FACILITIES = TEST_USERS["facilities_headers"]
FINANCE = TEST_USERS["finance_headers"]

HEADBOARD = {"description": "Headboard replacement", "quantity": 1,
             "unit_replacement_cost_cents": 100000, "fixture_age_months": 0}
LAMP = {"description": "Desk lamp", "quantity": 2,
        "unit_replacement_cost_cents": 8250, "fixture_age_months": 30}


def _group_with_checked_out_stay(api, name, client_name):
    """Group IN_HOUSE whose single assignment already checked out (room NEEDS_TURN)."""
    building, rooms = create_building_turn_active(name=name, key_pool_size=10,
                                                  rooms=(("R1", 1),))
    group, participants, assignments, invoice_id = setup_checked_in_group(
        building, rooms, client_name=client_name,
        arrival_date="2026-06-15", departure_date="2026-06-19",
        checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-06-19T11:00:00Z",
        deposit_paid_cents=5000)
    set_clock("2026-06-19T09:00:00Z")
    get_success_data(api.check_out_assignment(assignments[0]["id"], ADMIN))
    return building, rooms, get_success_data(
        api.get_conference_group(group["id"], ADMIN))


class TestEstimateVsAssessed:
    def test_damage_estimate_vs_assessed_charge(self, api):
        """PRD: "At report time the system computes estimate_total_cents — a
        straight sum of quantity times unit replacement cost over the lines, with
        no depreciation and no fee"
        PRD: "For each line, the depreciation factor is the larger of 0.40 and
        one minus two percent times the fixture's age in months; the depreciated
        unit value is the unit replacement cost times that factor, rounded
        half-up to whole cents per unit; and the line total is the depreciated
        unit value multiplied by the quantity. The assessed charge is the sum of
        the line totals plus one flat administrative fee of 2,500 cents"

        Design: Difficulty/dual_variant_calc/damage_estimate_vs_assessed_charge
        """
        building, rooms, group = _group_with_checked_out_stay(
            api, "Carter Hall", "Debate Camp")
        reported = validate_success(api.create_damage_assessment(
            rooms["R1"]["id"],
            create_damage_assessment_payload(group["id"], [dict(HEADBOARD), dict(LAMP)]),
            FACILITIES), expected_status=201)
        assert reported["status"] == "REPORTED"
        assert reported["estimate_total_cents"] == 116500, \
            "100000 + 2*8250 straight replacement sum"
        assert reported["assessed_total_cents"] is None, "null until ASSESSED"

        assessed = validate_success(api.assess_damage(reported["id"], FACILITIES))
        assert assessed["status"] == "ASSESSED"
        assert assessed["assessed_total_cents"] == 109100, (
            "line1 100000 * max(0.40, 1 - 0) = 100000; line2 round_half_up(8250 * "
            "max(0.40, 1 - 0.60)) = 3300, *2 = 6600; + 2500 admin fee")
        assert assessed["estimate_total_cents"] != assessed["assessed_total_cents"]

    def test_estimate_never_below_assessed_when_fixtures_aged(self, api):
        """PRD: "Because only the assessed variant depreciates and the estimate
        never does, the estimate is never lower than the assessed total for the
        same lines whenever any fixture has a positive age."

        Design: Difficulty/dual_variant_calc/damage_estimate_vs_assessed_charge
        """
        building, rooms, group = _group_with_checked_out_stay(
            api, "Carter Hall", "Debate Camp")
        reported = get_success_data(api.create_damage_assessment(
            rooms["R1"]["id"],
            create_damage_assessment_payload(group["id"], [dict(HEADBOARD), dict(LAMP)]),
            FACILITIES))
        assessed = get_success_data(api.assess_damage(reported["id"], FACILITIES))
        assert assessed["estimate_total_cents"] > assessed["assessed_total_cents"], \
            "aged fixtures depreciate only in the assessed variant"
        assert assessed["assessed_at"] is not None, "assess stamps assessed_at from the clock"


class TestPerLineRounding:
    def test_per_line_rounding_damage_charge(self, api):
        """PRD: "the depreciated unit value is the unit replacement cost times
        that factor, rounded half-up to whole cents per unit; and the line total
        is the depreciated unit value multiplied by the quantity."
        PRD §2.9: "per unit for damage depreciation (before multiplying by
        quantity)".

        Design: Difficulty/combinatorial_formula/per_line_rounding_damage_charge
        """
        building, rooms, group = _group_with_checked_out_stay(
            api, "Eaton Hall", "Robotics Camp")
        reported = get_success_data(api.create_damage_assessment(
            rooms["R1"]["id"],
            create_damage_assessment_payload(
                group["id"],
                [create_damage_line_item("Chair caster", quantity=3,
                                         unit_replacement_cost_cents=3333,
                                         fixture_age_months=25)]),
            FACILITIES))
        assessed = validate_success(api.assess_damage(reported["id"], FACILITIES))
        # Per-unit-first order: round_half_up(3333 * 0.5) = 1667; 1667*3 = 5001;
        # + 2500 fee = 7501. Sum-then-round would give round_half_up(4999.5)=5000.
        assert assessed["assessed_total_cents"] == 7501
        assert assessed["assessed_total_cents"] != 7500, \
            "the pinned per-unit rounding order is falsifiable against sum-then-round"

    def test_depreciation_floor_binds_on_very_old_fixture(self, api):
        """PRD: "the depreciation factor is the larger of 0.40 and one minus two
        percent times the fixture's age in months"

        Design: Difficulty/combinatorial_formula/per_line_rounding_damage_charge
        """
        building, rooms, group = _group_with_checked_out_stay(
            api, "Eaton Hall", "Robotics Camp")
        reported = get_success_data(api.create_damage_assessment(
            rooms["R1"]["id"],
            create_damage_assessment_payload(
                group["id"],
                [create_damage_line_item("Ancient fixture", quantity=1,
                                         unit_replacement_cost_cents=10000,
                                         fixture_age_months=100)]),
            FACILITIES))
        # At 100 months, 1 - 0.02*100 = -1.0, but the floor pins the factor at
        # 0.40: round_half_up(10000 * 0.40) * 1 + 2500 fee = 6500.
        assessed = get_success_data(api.assess_damage(reported["id"], FACILITIES))
        assert assessed["assessed_total_cents"] == 6500


class TestDisputeFlow:
    def _assessed_assessment(self, api, name, client_name, line_items):
        building, rooms, group = _group_with_checked_out_stay(api, name, client_name)
        reported = get_success_data(api.create_damage_assessment(
            rooms["R1"]["id"],
            create_damage_assessment_payload(group["id"], line_items), FACILITIES))
        assessed = get_success_data(api.assess_damage(reported["id"], FACILITIES))
        return building, rooms, group, assessed

    def test_dispute_resolve_with_adjusted_lines_recomputes(self, api):
        """PRD: "`ACCEPT` moves the assessment to `BILLED`, and if the resolution
        carries optional `adjusted_line_items`, those replace the assessment's
        lines and `assessed_total_cents` is recomputed by the same
        assessed-variant rule"

        Design: Corner/calculations/dispute_resolve_with_adjusted_lines_recomputes
        """
        building, rooms, group, assessed = self._assessed_assessment(
            api, "Ryan Hall", "Adjust Camp", [dict(HEADBOARD), dict(LAMP)])
        assert assessed["assessed_total_cents"] == 109100
        set_clock("2026-06-20T09:00:00Z")
        disputed = get_success_data(api.dispute_damage(
            assessed["id"], "lamp was already broken",
            make_coordinator_headers(group["id"])))
        assert disputed["status"] == "DISPUTED"
        resolved = validate_success(api.resolve_damage(
            disputed["id"], "ACCEPT", FINANCE,
            adjusted_line_items=[dict(HEADBOARD)]))
        assert resolved["status"] == "BILLED"
        assert resolved["assessed_total_cents"] == 102500, \
            "single remaining line 100000 * 1.0 + 2500 admin fee"

    def test_dispute_window_seventh_day_passes_eighth_fails(self, api):
        """PRD: "The dispute must arrive within seven calendar days of
        assessed_at, inclusive of the seventh day; later attempts fail with
        ERR_DISPUTE_WINDOW_CLOSED."

        Design: Corner/validations/dispute_window_seventh_day_passes_eighth_fails
        """
        building, rooms = create_building_turn_active(name="Alpha Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, assignments, _inv = setup_checked_in_group(
            building, rooms, client_name="Dispute Window",
            arrival_date="2026-06-15", departure_date="2026-06-19",
            checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-06-19T11:00:00Z",
            deposit_paid_cents=5000)
        set_clock("2026-06-19T09:00:00Z")
        get_success_data(api.check_out_assignment(assignments[0]["id"], ADMIN))
        da1 = get_success_data(api.create_damage_assessment(
            rooms["R1"]["id"],
            create_damage_assessment_payload(
                group["id"], [create_damage_line_item("Blinds", 1, 20000, 6)]),
            FACILITIES))
        da2 = get_success_data(api.create_damage_assessment(
            rooms["R1"]["id"],
            create_damage_assessment_payload(
                group["id"], [create_damage_line_item("Carpet stain", 1, 30000, 12)]),
            FACILITIES))
        set_clock("2026-06-19T09:30:00Z")  # both assessments stamped on 2026-06-19
        get_success_data(api.assess_damage(da1["id"], FACILITIES))
        get_success_data(api.assess_damage(da2["id"], FACILITIES))

        headers = make_coordinator_headers(group["id"])
        set_clock("2026-06-26T23:59:00Z")  # the seventh day, inclusive
        disputed = validate_success(
            api.dispute_damage(da1["id"], "day 7 dispute", headers))
        assert disputed["status"] == "DISPUTED"
        set_clock("2026-06-27T00:01:00Z")  # the eighth day
        resp = api.dispute_damage(da2["id"], "day 8 dispute", headers)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)
        da2_after = get_success_data(api.get_damage_assessment(da2["id"], ADMIN))
        assert da2_after["status"] == "ASSESSED"


class TestDamageStateGate:
    def test_damage_bill_before_assess_rejected(self, api):
        """PRD: "Any of these four operations — assess, bill, dispute, resolve —
        attempted from a state that does not permit it is rejected with
        ERR_DAMAGE_NOT_ASSESSED."

        Design: Corner/validations/damage_bill_before_assess_rejected
        """
        building, rooms = create_building_turn_active(name="Hotel Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        from test_helpers import create_group
        group = create_group(building["id"], client_name="Damage Early",
                             deposit_paid_cents=0)
        reported = get_success_data(api.create_damage_assessment(
            rooms["R1"]["id"],
            create_damage_assessment_payload(
                group["id"], [create_damage_line_item("Mirror", 1, 15000, 12)]),
            FACILITIES))
        assert reported["status"] == "REPORTED"
        validate_error(api.bill_damage(reported["id"], FINANCE),
                       ApiErrorId.ERR_DAMAGE_NOT_ASSESSED)
        validate_error(api.dispute_damage(reported["id"], "not assessed yet",
                                          make_coordinator_headers(group["id"])),
                       ApiErrorId.ERR_DAMAGE_NOT_ASSESSED)
