"""Consignment pipeline: sell/settle rules, advance clawback, reject cascade,
duplicate-open guard, pool statement rounding, pool fee tiers."""
from test_helpers import (
    ApiErrorId,
    assert_consignment,
    assert_pool_statement,
    consign_lot,
    grade_lot,
    setup_advanced_consignment,
    setup_clip_with_lot,
    setup_consigned_lot,
    setup_graded_lot,
    transition_consignment,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestConsignmentStateRules:

    def test_consignment_sell_from_tendered_rejected(self, api, wool_pool_operator_headers, ranch_manager_headers):
        """PRD §3.5: "The pool operator records the auction outcome on an
        `ADVANCED` consignment by submitting `sale_gross_cents` (zero or more),
        moving the consignment to `SOLD`".
        PRD §3.5: "Every undefined consignment transition is rejected with
        `ERR_CONSIGNMENT_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/consignment_sell_from_tendered_rejected
        """
        flock, clip, lot, con = setup_consigned_lot(
            estimated_micron=20.0, pool_ref="WWPA-S", flock_name="Sell Ranch",
            crew_name="Crew SE")
        assert con["consignment_status"] == "TENDERED"
        resp = api.sell_consignment(con["id"], {"sale_gross_cents": 50000}, wool_pool_operator_headers)
        validate_error(resp, ApiErrorId.ERR_CONSIGNMENT_INVALID_STATE.value, expected_status=409)
        con = validate_success(api.get_consignment(con["id"], ranch_manager_headers))
        assert con["consignment_status"] == "TENDERED"
        assert con["sale_gross_cents"] is None

    def test_consignment_reject_returns_lot_to_graded(self, api, wool_pool_operator_headers, ranch_manager_headers):
        """PRD §3.5: "From `TENDERED`, the pool operator either accepts
        (`TENDERED -> ACCEPTED`) or rejects (`TENDERED -> REJECTED`); rejection
        is cross-entity, returning the lot from `CONSIGNED` to `GRADED` and
        incrementing the lot's `version`."

        Design: Corner/state_machines/consignment_reject_returns_lot_to_graded
        """
        flock, clip, lot, con = setup_consigned_lot(
            estimated_micron=20.0, pool_ref="WWPA-RJ", flock_name="Reject Ranch",
            crew_name="Crew RJ")
        con = validate_success(api.transition_consignment(
            con["id"], {"to": "REJECTED"}, wool_pool_operator_headers))
        assert con["consignment_status"] == "REJECTED"
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["lot_status"] == "GRADED", "rejection returns the lot to GRADED"
        # The lot is consignable again after the rejection.
        con2 = validate_success(api.create_consignment(
            {"lot_id": lot["id"], "pool_ref": "WWPA-RJ2"}, ranch_manager_headers), expected_status=201)
        assert con2["consignment_status"] == "TENDERED"

    def test_duplicate_open_consignment_rejected(self, api, ranch_manager_headers):
        """PRD §3.5: "A lot may have only one open consignment at a time —
        creating one while another consignment of the same lot is `TENDERED`,
        `ACCEPTED`, `ADVANCED`, or `SOLD` is rejected with
        `ERR_CONSIGNMENT_ALREADY_OPEN` (HTTP 409)."
        PRD §3.5: "The manager tenders a `GRADED` or `WITHDRAWN` lot to a wool
        pool by creating a consignment with `lot_id` and a `pool_ref`
        sale-season identifier such as `WWPA-2026A`; tendering moves the lot
        to `CONSIGNED`."

        With an open consignment the lot sits in `CONSIGNED`/`SOLD`, so the
        §2.8 pipeline also admits the layer-6 lot-state rejection
        (`ERR_LOT_INVALID_STATE`, HTTP 409) ahead of the layer-9
        one-open-consignment rule; both readings honor the quoted sentences.

        Design: Corner/validations/duplicate_open_consignment_rejected
        """
        flock, clip, lot, con = setup_consigned_lot(
            estimated_micron=20.0, pool_ref="WWPA-DC", flock_name="DupCon Ranch",
            crew_name="Crew DC")
        resp = api.create_consignment(
            {"lot_id": lot["id"], "pool_ref": "WWPA-DC2"}, ranch_manager_headers)
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_CONSIGNMENT_ALREADY_OPEN.value,
            ApiErrorId.ERR_LOT_INVALID_STATE.value,
        ])
        assert resp.status_code == 409
        _, meta = validate_paginated(
            api.list_consignments(ranch_manager_headers, params={"lot_id": lot["id"]}))
        assert meta["total_count"] == 1, "only one consignment exists for the lot"

    def test_consignment_withdraw_as_pool_operator_forbidden(self, api, wool_pool_operator_headers, ranch_manager_headers):
        """PRD §3.5: "Withdrawal is the manager's exit".
        PRD §2.1: "the same `ERR_FORBIDDEN` applies when a state transition
        exists but the caller's role is not the transition's designated actor."

        Design: Corner/rbac/consignment_withdraw_as_pool_operator_forbidden
        """
        flock, clip, lot, con = setup_consigned_lot(
            estimated_micron=20.0, pool_ref="WWPA-AC", flock_name="Actor Ranch",
            crew_name="Crew AC")
        transition_consignment(con["id"], "ACCEPTED")
        resp = api.transition_consignment(
            con["id"], {"to": "WITHDRAWN"}, wool_pool_operator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
        con = validate_success(api.get_consignment(con["id"], ranch_manager_headers))
        assert con["consignment_status"] == "ACCEPTED"


class TestAdvanceClawback:

    def test_consignment_advance_clawback_zero_net_cash(self, api, ranch_manager_headers, wool_pool_operator_headers):
        """PRD §3.5: "from `ADVANCED` it additionally performs the full
        clawback, setting `clawback_cents` equal to `advance_cents` as the
        compensating action for the advance invariant, with the same lot
        transition."
        PRD §3.5: "`advance_cents` becomes 70 percent of the lot's
        `effective_value_cents` at that moment — certified when a locked core
        test exists, provisional otherwise — rounded half-up to a whole cent."

        Design: Difficulty/compensating_invariant/consignment_advance_clawback_zero_net_cash
        """
        flock, clip, lot, con = setup_advanced_consignment(
            estimated_micron=20.0, pool_ref="WWPA-CB", flock_name="Clawback Ranch",
            crew_name="Crew CB", lot_weight_lbs=100.0,
            greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0)
        con = validate_success(api.get_consignment(con["id"], ranch_manager_headers))
        assert con["advance_cents"] == 23100, "round_half_up(0.70 * 33000)"
        assert con["clawback_cents"] == 0

        con = validate_success(api.transition_consignment(
            con["id"], {"to": "WITHDRAWN"}, ranch_manager_headers))
        assert con["consignment_status"] == "WITHDRAWN"
        assert con["clawback_cents"] == 23100, "full clawback equals the advance"
        assert con["advance_cents"] - con["clawback_cents"] == 0, (
            "net pool cash movement for the lot is exactly zero"
        )
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["lot_status"] == "WITHDRAWN"

    def test_advance_is_seventy_percent_of_effective_value(self, api, ranch_manager_headers):
        """PRD §3.5: "`advance_cents` becomes 70 percent of the lot's
        `effective_value_cents` at that moment — certified when a locked core
        test exists, provisional otherwise — rounded half-up to a whole cent."

        Design: Difficulty/compensating_invariant/consignment_advance_clawback_zero_net_cash
        """
        # STRONG grade: 100.0 * 190 = 19000 provisional; advance = 13300.
        flock, clip, lot, con = setup_advanced_consignment(
            estimated_micron=26.0, pool_ref="WWPA-CB2", flock_name="Clawback2 Ranch",
            crew_name="Crew CB2", lot_weight_lbs=100.0,
            greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0)
        con = validate_success(api.get_consignment(con["id"], ranch_manager_headers))
        assert con["advance_cents"] == 13300, "round_half_up(0.70 * 19000)"


class TestPoolSettlement:

    def test_pool_statement_rounds_per_lot_then_sums(self, api, ranch_manager_headers, wool_pool_operator_headers):
        """PRD §3.5: "`pool_fee_cents` is then `sale_gross_cents` multiplied by
        the tier percentage divided by 100, rounded half-up to a whole cent,
        and `settlement_cents` is `sale_gross_cents` minus `pool_fee_cents`
        minus `advance_cents` in integer arithmetic".
        PRD §3.5: "Rounding order is pinned: each lot's fee and settlement are
        rounded to whole cents first, and the statement sums those
        already-rounded per-lot figures — never sum-then-round."

        Design: Difficulty/combinatorial_formula/pool_statement_rounds_per_lot_then_sums
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Rounding Ranch", species="SHEEP", baseline_headcount=500)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=120.0, skirtings_weight_lbs=10.0, crew_name="Crew R")
        lot_a = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "RA", "weight_lbs": 50.0}, ranch_manager_headers), expected_status=201)
        lot_b = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "RB", "weight_lbs": 40.0}, ranch_manager_headers), expected_status=201)
        grade_lot(lot_a["id"], 20.0)  # FINE -> provisional 16500
        grade_lot(lot_b["id"], 23.0)  # MEDIUM -> provisional 10400

        con_a = consign_lot(lot_a["id"], "WWPA-R2")
        con_b = consign_lot(lot_b["id"], "WWPA-R2")
        for cid in (con_a["id"], con_b["id"]):
            transition_consignment(cid, "ACCEPTED")
            transition_consignment(cid, "ADVANCED")
        validate_success(api.sell_consignment(con_a["id"], {"sale_gross_cents": 101333}, wool_pool_operator_headers))
        validate_success(api.sell_consignment(con_b["id"], {"sale_gross_cents": 100101}, wool_pool_operator_headers))
        transition_consignment(con_a["id"], "SETTLED")
        transition_consignment(con_b["id"], "SETTLED")

        con_a = validate_success(api.get_consignment(con_a["id"], ranch_manager_headers))
        assert con_a["advance_cents"] == 11550, "round_half_up(0.70 * 16500)"
        # Pool total 90.0 lbs < 10000 -> 6.5%; fee = round_half_up(101333 * 0.065) = 6587
        assert con_a["pool_fee_cents"] == 6587
        assert con_a["settlement_cents"] == 83196, "101333 - 6587 - 11550"

        con_b = validate_success(api.get_consignment(con_b["id"], ranch_manager_headers))
        assert con_b["advance_cents"] == 7280, "round_half_up(0.70 * 10400)"
        # fee = round_half_up(100101 * 0.065) = 6507
        assert con_b["pool_fee_cents"] == 6507
        assert con_b["settlement_cents"] == 86314, "100101 - 6507 - 7280"

        stmt = validate_success(api.get_pool_statement("WWPA-R2", ranch_manager_headers))
        assert_pool_statement(stmt)
        assert stmt["consignment_count"] == 2
        assert stmt["total_sale_gross_cents"] == 201434
        assert stmt["total_pool_fee_cents"] == 13094, "6587 + 6507 (per-lot rounded, then summed)"
        assert stmt["total_advance_cents"] == 18830
        assert stmt["total_settlement_cents"] == 169510
        assert stmt["total_settlement_cents"] != 169511, (
            "169511 would be the sum-then-round trap value"
        )

    def test_pool_statement_aggregates_only_settled_rows(self, api, ranch_manager_headers, wool_pool_operator_headers):
        """PRD §3.5: "It aggregates only the pool's `SETTLED` consignments and
        reports `pool_ref`, `consignment_count`, `total_sale_gross_cents`,
        `total_pool_fee_cents`, `total_advance_cents`, and
        `total_settlement_cents`."
        PRD §3.5: "Rounding order is pinned: each lot's fee and settlement are
        rounded to whole cents first, and the statement sums those
        already-rounded per-lot figures — never sum-then-round."

        Design: Difficulty/combinatorial_formula/pool_statement_rounds_per_lot_then_sums
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Stmt Ranch", species="SHEEP", baseline_headcount=500)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=120.0, skirtings_weight_lbs=10.0, crew_name="Crew ST")
        lot_a = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "SA", "weight_lbs": 50.0}, ranch_manager_headers), expected_status=201)
        lot_b = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "SB", "weight_lbs": 40.0}, ranch_manager_headers), expected_status=201)
        grade_lot(lot_a["id"], 20.0)
        grade_lot(lot_b["id"], 23.0)

        # Settle only lot A; leave lot B at ADVANCED (sold but not settled).
        con_a = consign_lot(lot_a["id"], "WWPA-ST")
        con_b = consign_lot(lot_b["id"], "WWPA-ST")
        for cid in (con_a["id"], con_b["id"]):
            transition_consignment(cid, "ACCEPTED")
            transition_consignment(cid, "ADVANCED")
        validate_success(api.sell_consignment(con_a["id"], {"sale_gross_cents": 101333}, wool_pool_operator_headers))
        validate_success(api.sell_consignment(con_b["id"], {"sale_gross_cents": 100101}, wool_pool_operator_headers))
        transition_consignment(con_a["id"], "SETTLED")

        stmt = validate_success(api.get_pool_statement("WWPA-ST", ranch_manager_headers))
        assert_pool_statement(stmt)
        assert stmt["consignment_count"] == 1, "only SETTLED consignments aggregate"
        assert stmt["total_sale_gross_cents"] == 101333
        assert stmt["total_pool_fee_cents"] == 6587, "per-lot rounded fee of the settled lot"
        assert stmt["total_advance_cents"] == 11550
        assert stmt["total_settlement_cents"] == 83196

    def test_pool_statement_unknown_pool_not_found(self, api, ranch_manager_headers):
        """PRD §3.5: "A `pool_ref` with no consignments at all is rejected with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/endpoints/pool_statement_unknown_pool_not_found
        """
        resp = api.get_pool_statement("WWPA-NONE", ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)

    def test_pool_fee_tier_counts_own_weight(self, api, ranch_manager_headers, wool_pool_operator_headers):
        """PRD §3.5: "the system first sums `weight_lbs` over every consignment
        sharing the same `pool_ref` whose status is `ACCEPTED`, `ADVANCED`,
        `SOLD`, or `SETTLED`, including the lot being settled; that total
        determines the tier — strictly below 10,000 pounds the fee is 6.5
        percent, from 10,000 pounds up to but not including 25,000 pounds it is
        5.0 percent (so a pool total of exactly 10,000 pounds lands in the 5.0
        percent band), and at 25,000 pounds or more it is 4.0 percent."

        Design: Difficulty/combinatorial_formula/pool_fee_tier_counts_own_weight
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Tier Ranch", species="SHEEP", baseline_headcount=2000)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=10500.0, skirtings_weight_lbs=0.0,
            shorn_head_count=2000, expected_head=2000, crew_capacity=1000,
            crew_daily_rate=90000, crew_name="Crew T")
        lot_c = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "TC", "weight_lbs": 9500.0}, ranch_manager_headers), expected_status=201)
        lot_d = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "TD", "weight_lbs": 600.0}, ranch_manager_headers), expected_status=201)
        grade_lot(lot_c["id"], 23.0)  # MEDIUM -> 9500 * 260 = 2470000 provisional
        grade_lot(lot_d["id"], 23.0)  # MEDIUM -> 600 * 260 = 156000 provisional

        # lotC settles FIRST: pool total at that moment is 9500 (< 10000) -> 6.5%.
        con_c = consign_lot(lot_c["id"], "WWPA-T")
        transition_consignment(con_c["id"], "ACCEPTED")
        transition_consignment(con_c["id"], "ADVANCED")
        validate_success(api.sell_consignment(con_c["id"], {"sale_gross_cents": 2000000}, wool_pool_operator_headers))
        transition_consignment(con_c["id"], "SETTLED")

        # lotD settles SECOND: pool total now includes both lots (10100) -> 5.0%.
        con_d = consign_lot(lot_d["id"], "WWPA-T")
        transition_consignment(con_d["id"], "ACCEPTED")
        transition_consignment(con_d["id"], "ADVANCED")
        validate_success(api.sell_consignment(con_d["id"], {"sale_gross_cents": 130000}, wool_pool_operator_headers))
        transition_consignment(con_d["id"], "SETTLED")

        con_c = validate_success(api.get_consignment(con_c["id"], ranch_manager_headers))
        assert con_c["advance_cents"] == 1729000, "round_half_up(0.70 * 2470000)"
        assert con_c["pool_fee_cents"] == 130000, "9500 lbs alone -> 6.5% of 2000000"
        assert con_c["settlement_cents"] == 141000, "2000000 - 130000 - 1729000"

        con_d = validate_success(api.get_consignment(con_d["id"], ranch_manager_headers))
        assert con_d["advance_cents"] == 109200, "round_half_up(0.70 * 156000)"
        assert con_d["pool_fee_cents"] == 6500, (
            "9500 + 600 == 10100 lbs INCLUDING itself -> 5.0% of 130000"
        )
        assert con_d["pool_fee_cents"] != 8450, (
            "8450 would be the 6.5% fee that excluding-own-weight produces"
        )
        assert con_d["settlement_cents"] == 14300, "130000 - 6500 - 109200"

    def test_pool_fee_tier_own_weight_second_pool(self, api, ranch_manager_headers, wool_pool_operator_headers):
        """PRD §3.5: "the system first sums `weight_lbs` over every consignment
        sharing the same `pool_ref` whose status is `ACCEPTED`, `ADVANCED`,
        `SOLD`, or `SETTLED`, including the lot being settled; that total
        determines the tier".

        Design: Difficulty/combinatorial_formula/pool_fee_tier_counts_own_weight
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Tier2 Ranch", species="SHEEP", baseline_headcount=2000)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=10100.0, skirtings_weight_lbs=0.0,
            shorn_head_count=2000, expected_head=2000, crew_capacity=1000,
            crew_daily_rate=90000, crew_name="Crew T2")
        lot_big = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "TB", "weight_lbs": 9800.0},
            ranch_manager_headers), expected_status=201)
        lot_small = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "TS", "weight_lbs": 300.0},
            ranch_manager_headers), expected_status=201)
        grade_lot(lot_big["id"], 23.0)
        grade_lot(lot_small["id"], 23.0)

        # Small lot settles first: 300 lbs alone -> 6.5%.
        con_s = consign_lot(lot_small["id"], "WWPA-T2")
        transition_consignment(con_s["id"], "ACCEPTED")
        transition_consignment(con_s["id"], "ADVANCED")
        validate_success(api.sell_consignment(con_s["id"], {"sale_gross_cents": 100000}, wool_pool_operator_headers))
        transition_consignment(con_s["id"], "SETTLED")
        con_s = validate_success(api.get_consignment(con_s["id"], ranch_manager_headers))
        assert con_s["pool_fee_cents"] == 6500, "300 lbs < 10000 -> 6.5% of 100000"

        # Big lot settles second: 9800 + 300 == 10100 including itself -> 5.0%.
        con_b = consign_lot(lot_big["id"], "WWPA-T2")
        transition_consignment(con_b["id"], "ACCEPTED")
        transition_consignment(con_b["id"], "ADVANCED")
        validate_success(api.sell_consignment(con_b["id"], {"sale_gross_cents": 400000}, wool_pool_operator_headers))
        transition_consignment(con_b["id"], "SETTLED")
        con_b = validate_success(api.get_consignment(con_b["id"], ranch_manager_headers))
        assert con_b["pool_fee_cents"] == 20000, "10100 lbs -> 5.0% of 400000 (own weight counts)"

    def test_pool_fee_tier_exactly_10000_lbs(self, api, ranch_manager_headers, wool_pool_operator_headers):
        """PRD §3.5: "from 10,000 pounds up to but not including 25,000 pounds
        it is 5.0 percent (so a pool total of exactly 10,000 pounds lands in
        the 5.0 percent band)".
        PRD §3.5: "`settlement_cents` is `sale_gross_cents` minus
        `pool_fee_cents` minus `advance_cents` in integer arithmetic — which
        may be negative, in which case the grower repays the difference."

        Design: Difficulty/boundary_precision_check/pool_fee_tier_exactly_10000_lbs
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Boundary Ranch", species="SHEEP", baseline_headcount=2000)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=10200.0, skirtings_weight_lbs=0.0,
            shorn_head_count=2000, expected_head=2000, crew_capacity=1000,
            crew_daily_rate=90000, crew_name="Crew B")
        lot_e = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "BE", "weight_lbs": 6000.0}, ranch_manager_headers), expected_status=201)
        lot_f = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "BF", "weight_lbs": 4000.0}, ranch_manager_headers), expected_status=201)
        grade_lot(lot_e["id"], 23.0)  # MEDIUM -> 6000 * 260 = 1560000 provisional
        grade_lot(lot_f["id"], 23.0)  # MEDIUM -> 4000 * 260 = 1040000 provisional

        con_e = consign_lot(lot_e["id"], "WWPA-B1")
        transition_consignment(con_e["id"], "ACCEPTED")
        transition_consignment(con_e["id"], "ADVANCED")
        validate_success(api.sell_consignment(con_e["id"], {"sale_gross_cents": 1700000}, wool_pool_operator_headers))
        transition_consignment(con_e["id"], "SETTLED")

        con_f = consign_lot(lot_f["id"], "WWPA-B1")
        transition_consignment(con_f["id"], "ACCEPTED")
        transition_consignment(con_f["id"], "ADVANCED")
        validate_success(api.sell_consignment(con_f["id"], {"sale_gross_cents": 100000}, wool_pool_operator_headers))
        transition_consignment(con_f["id"], "SETTLED")

        con_e = validate_success(api.get_consignment(con_e["id"], ranch_manager_headers))
        assert con_e["pool_fee_cents"] == 110500, "6000 lbs alone -> 6.5% of 1700000"
        assert con_e["advance_cents"] == 1092000, "round_half_up(0.70 * 1560000)"
        assert con_e["settlement_cents"] == 497500, "1700000 - 110500 - 1092000"

        con_f = validate_success(api.get_consignment(con_f["id"], ranch_manager_headers))
        assert con_f["pool_fee_cents"] == 5000, "6000 + 4000 == 10000 exactly -> 5.0% of 100000"
        assert con_f["advance_cents"] == 728000, "round_half_up(0.70 * 1040000)"
        assert con_f["settlement_cents"] == -633000, (
            "100000 - 5000 - 728000; negative means the grower repays"
        )

    def test_pool_fee_9999_lbs_stays_in_top_tier(self, api, ranch_manager_headers, wool_pool_operator_headers):
        """PRD §3.5: "strictly below 10,000 pounds the fee is 6.5 percent, from
        10,000 pounds up to but not including 25,000 pounds it is 5.0 percent
        (so a pool total of exactly 10,000 pounds lands in the 5.0 percent
        band)".

        Design: Difficulty/boundary_precision_check/pool_fee_tier_exactly_10000_lbs
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Boundary2 Ranch", species="SHEEP", baseline_headcount=2000)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=10100.0, skirtings_weight_lbs=0.0,
            shorn_head_count=2000, expected_head=2000, crew_capacity=1000,
            crew_daily_rate=90000, crew_name="Crew B2")
        lot = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "B9", "weight_lbs": 9999.0},
            ranch_manager_headers), expected_status=201)
        grade_lot(lot["id"], 23.0)
        con = consign_lot(lot["id"], "WWPA-B2")
        transition_consignment(con["id"], "ACCEPTED")
        transition_consignment(con["id"], "ADVANCED")
        validate_success(api.sell_consignment(con["id"], {"sale_gross_cents": 200000}, wool_pool_operator_headers))
        transition_consignment(con["id"], "SETTLED")
        con = validate_success(api.get_consignment(con["id"], ranch_manager_headers))
        assert con["pool_fee_cents"] == 13000, "9999 lbs < 10000 -> 6.5% of 200000"
