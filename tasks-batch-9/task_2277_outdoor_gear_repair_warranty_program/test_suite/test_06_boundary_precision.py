"""Boundary precision: the exact edges the PRD pins twice on purpose.

Five inclusive/exclusive edges are exercised here, each from both sides:
the repair-versus-replace ratio landing exactly on `decision_threshold_pct`
(PRD §3.5), a parts draw taking exactly the lot's last available unit
(PRD §2.10, §3.8), the routing selector's candidate pool emptying at exactly
zero (PRD §3.8), an estimate approved at exactly its `valid_until` instant
(PRD §3.7) and open exposure landing exactly on the centre's liability cap
(PRD §2.9).
"""

import pytest

from test_helpers import (
    ERR_ESTIMATE_EXPIRED,
    ERR_INSUFFICIENT_PART_UNITS,
    ERR_NO_ELIGIBLE_TECHNICIAN,
    PARTS_COORDINATOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SERVICE_AGENT_HEADERS,
    assert_center_posture,
    assert_claim_decision,
    assert_estimate_breakdown,
    assert_part_lot_counts,
    factories,
    get_success_data,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# The ratio boundary is one hundredth of a percent wide, so the two-decimal
# percentage is compared at half that width to keep the two sides apart.
RATIO_TOLERANCE = 0.005


def _warranty_repair_claim_at_cap(scenario, liability_cap_cents):
    """Adjudicate one WARRANTY_REPAIR claim at a centre with the given cap.

    The bench finding is FABRIC 120 minutes with 4200 cents of parts on a
    37-month-old TENT_SHELTER unit, so the claim's repair cost sits under the
    55 percent cap and the reservation is the repair cost itself.
    """
    scenario.set_clock()
    center = scenario.center(liability_cap_cents=liability_cap_cents)
    model = scenario.model()
    scenario.part_lot(model["id"])
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    technician = scenario.technician(center["id"])
    claim = scenario.claim(center["id"], item["id"])
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        technician["id"],
        expected_claim_version=submitted["version"],
    )
    decided = scenario.decide(claim["id"], decision_note="Defect confirmed.")
    return center["id"], decided


class TestRepairRatioExactlyAtThreshold:
    """PRD §3.5 — a ratio landing exactly on the threshold replaces."""

    @pytest.mark.parametrize(
        (
            "parts_cents, repair_cost_cents, ratio_pct, decision, claim_status, "
            "disposition, basis, valuation_variant, reserved_cents"
        ),
        [
            (
                31257,
                49447,
                55.00,
                "WARRANTY_REPLACE",
                "REPLACEMENT_AUTHORIZED",
                "IRREPARABLE_HOLD",
                "REPLACEMENT",
                "SUCCESSOR_MSRP",
                89910,
            ),
            (
                31256,
                49446,
                54.99,
                "WARRANTY_REPAIR",
                "WARRANTY_APPROVED",
                "AT_CENTER",
                "REPAIR",
                "DEPRECIATED_PURCHASE",
                49446,
            ),
        ],
        ids=["ratio_55.00_at_threshold_replaces", "ratio_54.99_below_threshold_repairs"],
    )
    def test_one_cent_of_parts_flips_the_repair_versus_replace_outcome(
        self,
        catalogue,
        parts_cents,
        repair_cost_cents,
        ratio_pct,
        decision,
        claim_status,
        disposition,
        basis,
        valuation_variant,
        reserved_cents,
    ):
        """31257 cents of parts ratios to 55.00 and replaces; 31256 ratios to 54.99 and repairs.

        "If `repair_ratio_pct` is greater than **or equal to** `decision_threshold_pct`,
        the outcome is `WARRANTY_REPLACE`; a ratio landing exactly on the threshold
        replaces rather than repairs."
        "`repair_ratio_pct` is one hundred multiplied by the claim's
        `latest_repair_cost_cents`, divided by the unit's
        `replacement_value_successor_cents`, rounded half up to two decimal places."
        "a `reserved_amount_cents` equal to the unit's full
        `replacement_value_successor_cents`"
        "a `reserved_amount_cents` equal to the lesser of the claim's
        `latest_repair_cost_cents` and the unit's `replacement_value_depreciated_cents`"
        "The unit moves `AT_CENTER` → `IRREPARABLE_HOLD` and thereby skips the bench
        entirely"

        Design: Difficulty/boundary_precision_check/repair_ratio_exactly_at_threshold_replaces
        """
        scenario = catalogue.scenario
        claim = scenario.claim(catalogue.center_id, catalogue.item_id)
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            catalogue.technician_id,
            expected_claim_version=submitted["version"],
            estimated_parts_cents=parts_cents,
        )

        decided = get_success_data(
            catalogue.scenario.api.decide_claim(
                claim["id"], SERVICE_AGENT_HEADERS, {"decision_note": "Adjudicated."}
            ),
            200,
        )

        assert decided["latest_repair_cost_cents"] == repair_cost_cents, decided
        assert_claim_decision(
            decided, decision, claim_status, threshold_pct=55, ratio_pct=ratio_pct
        )
        assert decided["repair_ratio_pct"] == pytest.approx(
            ratio_pct, abs=RATIO_TOLERANCE
        ), decided

        item = scenario.read_item(catalogue.item_id)
        assert item["disposition_status"] == disposition, item

        entries = scenario.liability_entries(claim["id"])
        assert len(entries) == 1, entries
        entry = entries[0]
        assert entry["basis"] == basis, entry
        assert entry["valuation_variant"] == valuation_variant, entry
        assert entry["status"] == "OPEN", entry
        assert entry["reserved_amount_cents"] == reserved_cents, entry

        assert_center_posture(
            scenario.read_center(catalogue.center_id),
            reserved_cents,
            posture="OPEN",
        )

    def test_both_sides_of_the_threshold_roll_up_into_one_centre_exposure(
        self, catalogue
    ):
        """The 55.00 replacement reserves 89910 and the 54.99 repair 49446, summing to 139356.

        "If `repair_ratio_pct` is greater than **or equal to** `decision_threshold_pct`,
        the outcome is `WARRANTY_REPLACE`; a ratio landing exactly on the threshold
        replaces rather than repairs."
        "`open_liability_cents` is the sum of `reserved_amount_cents` over every
        liability entry whose `status` is `OPEN` and whose claim's `service_center_id` is
        this centre."
        "Otherwise, if `open_liability_cents` multiplied by one hundred is strictly
        greater than sixty multiplied by `liability_cap_cents`, the posture is
        `CONSTRAINED`."

        Design: Difficulty/boundary_precision_check/repair_ratio_exactly_at_threshold_replaces
        """
        scenario = catalogue.scenario
        item_b = scenario.gear_item(
            catalogue.model_id,
            catalogue.customer_id,
            serial_number=factories.SERIAL_B,
            proof_of_purchase_ref="POS-88214",
        )

        claim_a = scenario.claim(catalogue.center_id, catalogue.item_id)
        submitted_a = scenario.submit(claim_a["id"])
        scenario.assess(
            claim_a["id"],
            catalogue.technician_id,
            expected_claim_version=submitted_a["version"],
            estimated_parts_cents=31257,
        )

        claim_b = scenario.claim(catalogue.center_id, item_b["id"])
        submitted_b = scenario.submit(claim_b["id"])
        scenario.assess(
            claim_b["id"],
            catalogue.technician_id,
            expected_claim_version=submitted_b["version"],
            estimated_parts_cents=31256,
        )

        decided_a = scenario.decide(claim_a["id"], decision_note="At-threshold case.")
        decided_b = scenario.decide(
            claim_b["id"], decision_note="One cent below threshold."
        )

        assert_claim_decision(
            decided_a,
            "WARRANTY_REPLACE",
            "REPLACEMENT_AUTHORIZED",
            threshold_pct=55,
            ratio_pct=55.00,
        )
        assert decided_a["repair_ratio_pct"] == pytest.approx(
            55.00, abs=RATIO_TOLERANCE
        ), decided_a
        assert_claim_decision(
            decided_b,
            "WARRANTY_REPAIR",
            "WARRANTY_APPROVED",
            threshold_pct=55,
            ratio_pct=54.99,
        )
        assert decided_b["repair_ratio_pct"] == pytest.approx(
            54.99, abs=RATIO_TOLERANCE
        ), decided_b

        assert (
            scenario.read_item(catalogue.item_id)["disposition_status"]
            == "IRREPARABLE_HOLD"
        )
        assert scenario.read_item(item_b["id"])["disposition_status"] == "AT_CENTER"

        assert_center_posture(
            scenario.read_center(catalogue.center_id), 139356, posture="OPEN"
        )


class TestReservationTakesLastAvailableUnit:
    """PRD §2.10 / §3.8 — a draw equal to `available_units` is the inclusive edge."""

    @staticmethod
    def _clip_lot(scenario, model_id):
        """A dedicated lot with a single on-hand unit and a watermark of one."""
        return scenario.part_lot(
            model_id,
            part_code=factories.CLIP_PART_CODE,
            part_kind="FRAME_SEGMENT",
            on_hand_units=1,
            unit_price_cents=900,
            low_watermark_units=1,
        )

    def test_draw_of_exactly_available_units_is_accepted_and_depletes_the_lot(
        self, open_order, api
    ):
        """One unit drawn against exactly one available reserves and jumps the lot to DEPLETED.

        "Beyond eligibility, `units` below one is refused with `ERR_INVALID_UNITS` and
        `units` exceeding the lot's `available_units` is refused with
        `ERR_INSUFFICIENT_PART_UNITS`; a draw exactly equal to `available_units` is
        allowed and depletes the lot."
        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is
        at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."
        "it may jump `AVAILABLE` → `DEPLETED` directly when one draw takes every
        available unit and so crosses the whole `LOW` band in a single step"
        "That model-level field is `SUPPORTED` when some part lot for the model has a
        `status` of `AVAILABLE` or `LOW`."

        Design: Difficulty/boundary_precision_check/reservation_takes_last_available_unit_depletes_lot
        """
        scenario = open_order.scenario
        lot = self._clip_lot(scenario, open_order.model_id)
        assert_part_lot_counts(lot, 1, 0, 1, status="LOW")

        reservation = validate_success(
            api.create_parts_reservation(
                open_order.order_id,
                factories.parts_reservation_payload(
                    lot["id"], factories.CLIP_PART_CODE, 1
                ),
                PARTS_COORDINATOR_HEADERS,
            ),
            201,
        )
        assert reservation["status"] == "RESERVED", reservation
        assert reservation["units"] == 1, reservation
        assert reservation["is_substitution"] is False, reservation

        assert_part_lot_counts(
            scenario.read_lot(lot["id"]), 1, 1, 0, status="DEPLETED"
        )
        # The floor-panel lot is untouched, so the model still reports usable stock.
        assert (
            scenario.read_model(open_order.model_id)["parts_support_status"]
            == "SUPPORTED"
        )

    def test_draw_of_two_units_against_one_available_is_refused(self, open_order, api):
        """Two units against exactly one available exceeds availability and reserves nothing.

        "Beyond eligibility, `units` below one is refused with `ERR_INVALID_UNITS` and
        `units` exceeding the lot's `available_units` is refused with
        `ERR_INSUFFICIENT_PART_UNITS`; a draw exactly equal to `available_units` is
        allowed and depletes the lot."
        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is
        at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."

        Design: Difficulty/boundary_precision_check/reservation_takes_last_available_unit_depletes_lot
        """
        scenario = open_order.scenario
        lot = self._clip_lot(scenario, open_order.model_id)

        validate_error(
            api.create_parts_reservation(
                open_order.order_id,
                factories.parts_reservation_payload(
                    lot["id"], factories.CLIP_PART_CODE, 2
                ),
                PARTS_COORDINATOR_HEADERS,
            ),
            ERR_INSUFFICIENT_PART_UNITS,
        )

        assert_part_lot_counts(scenario.read_lot(lot["id"]), 1, 0, 1, status="LOW")
        rows, meta = validate_paginated(
            api.list_parts_reservations(
                PARTS_COORDINATOR_HEADERS, part_lot_id=lot["id"]
            )
        )
        assert rows == [], rows
        assert meta["total_count"] == 0, meta

    def test_second_draw_against_the_depleted_lot_is_refused_without_double_booking(
        self, open_order, api
    ):
        """Once availability is zero a further single unit is refused and reserved_units stays 1.

        "Beyond eligibility, `units` below one is refused with `ERR_INVALID_UNITS` and
        `units` exceeding the lot's `available_units` is refused with
        `ERR_INSUFFICIENT_PART_UNITS`; a draw exactly equal to `available_units` is
        allowed and depletes the lot."
        "A successful reservation begins with `status` `RESERVED` and a null
        `settled_at`, increases the lot's `reserved_units` by `units`, recomputes the
        lot's `available_units`, re-derives the lot's `status`, and then re-derives
        `parts_support_status` on the lot's model."

        Design: Difficulty/boundary_precision_check/reservation_takes_last_available_unit_depletes_lot
        """
        scenario = open_order.scenario
        lot = self._clip_lot(scenario, open_order.model_id)

        first = validate_success(
            api.create_parts_reservation(
                open_order.order_id,
                factories.parts_reservation_payload(
                    lot["id"], factories.CLIP_PART_CODE, 1
                ),
                PARTS_COORDINATOR_HEADERS,
            ),
            201,
        )
        assert first["status"] == "RESERVED", first

        validate_error(
            api.create_parts_reservation(
                open_order.order_id,
                factories.parts_reservation_payload(
                    lot["id"], factories.CLIP_PART_CODE, 1
                ),
                PARTS_COORDINATOR_HEADERS,
            ),
            ERR_INSUFFICIENT_PART_UNITS,
        )

        assert_part_lot_counts(
            scenario.read_lot(lot["id"]), 1, 1, 0, status="DEPLETED"
        )
        rows, meta = validate_paginated(
            api.list_parts_reservations(
                PARTS_COORDINATOR_HEADERS, part_lot_id=lot["id"]
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [first["id"]], rows


class TestSelectorEmptyCandidatePool:
    """PRD §3.8 — the routing pool empties at exactly zero eligible technicians."""

    def test_pool_empty_one_level_short_of_the_lane_minimum_creates_no_block(
        self, open_order, api
    ):
        """An INSULATION grant at level 1 clears no candidate, so the block is refused.

        "The candidate pool is drawn only from technicians of the order's own centre
        whose roster `status` is `ACTIVE`, who hold a certification whose `work_type`
        equals the requested `work_type` at a `level` at or above that lane's minimum —
        level 1 for fabric, level 2 for zipper, frame and insulation — and who have no
        block in `status` `SCHEDULED` overlapping the requested interval on the same
        half-open test."
        "If the candidate pool is empty the request is refused with
        `ERR_NO_ELIGIBLE_TECHNICIAN` and no block row is created at all."

        Design: Difficulty/boundary_precision_check/selector_empty_candidate_pool_returns_no_eligible_technician
        """
        scenario = open_order.scenario
        get_success_data(
            api.patch_technician(
                open_order.second_technician_id,
                {"certifications": [factories.certification("INSULATION", 1)]},
                PROGRAM_ADMIN_HEADERS,
            ),
            200,
        )

        validate_error(
            api.create_work_block(
                factories.work_block_payload(
                    open_order.order_id, work_type="INSULATION"
                ),
                SERVICE_AGENT_HEADERS,
            ),
            ERR_NO_ELIGIBLE_TECHNICIAN,
        )

        rows, meta = validate_paginated(
            api.list_work_blocks(
                SERVICE_AGENT_HEADERS, repair_order_id=open_order.order_id
            )
        )
        assert rows == [], rows
        assert meta["total_count"] == 0, meta

        assert scenario.read_order(open_order.order_id)["work_status"] == "QUEUED"
        assert (
            scenario.read_technician(open_order.technician_id)[
                "scheduled_minutes_open"
            ]
            == 0
        )
        assert (
            scenario.read_technician(open_order.second_technician_id)[
                "scheduled_minutes_open"
            ]
            == 0
        )

    def test_pool_of_exactly_one_at_the_lane_minimum_routes_the_block(
        self, open_order, api
    ):
        """An INSULATION grant at exactly level 2 clears the filter and wins the routing.

        "The candidate pool is drawn only from technicians of the order's own centre
        whose roster `status` is `ACTIVE`, who hold a certification whose `work_type`
        equals the requested `work_type` at a `level` at or above that lane's minimum —
        level 1 for fabric, level 2 for zipper, frame and insulation — and who have no
        block in `status` `SCHEDULED` overlapping the requested interval on the same
        half-open test."
        "The winner is stamped onto the block's `technician_id` and the block's
        `routed_by_selector` flag is set to true; a block whose technician was supplied
        by the caller keeps `routed_by_selector` false."
        "On success the block's `duration_minutes` is the whole number of minutes
        between `start_at` and `end_at`, its `status` is `SCHEDULED`, its
        `actual_minutes` is null, the assigned technician's `scheduled_minutes_open`
        increases by `duration_minutes`, and — if this is the first block on the order —
        the order's `work_status` moves `QUEUED` → `IN_WORK`."

        Design: Difficulty/boundary_precision_check/selector_empty_candidate_pool_returns_no_eligible_technician
        """
        scenario = open_order.scenario
        get_success_data(
            api.patch_technician(
                open_order.second_technician_id,
                {"certifications": [factories.certification("INSULATION", 2)]},
                PROGRAM_ADMIN_HEADERS,
            ),
            200,
        )

        block = validate_success(
            api.create_work_block(
                factories.work_block_payload(
                    open_order.order_id, work_type="INSULATION"
                ),
                SERVICE_AGENT_HEADERS,
            ),
            201,
        )
        assert block["technician_id"] == open_order.second_technician_id, block
        assert block["routed_by_selector"] is True, block
        assert block["status"] == "SCHEDULED", block

        assert scenario.read_order(open_order.order_id)["work_status"] == "IN_WORK"


class TestEstimateApprovalAtExactValidityInstant:
    """PRD §3.7 — approval at exactly `valid_until` is still inside the window."""

    @staticmethod
    def _zipper_estimate(world):
        """A SENT provisional quote of ZIPPER 35 minutes plus one 1800-cent slider."""
        return world.scenario.estimate(
            world.order_id,
            labor_lines=[factories.labor_line("ZIPPER", 35)],
            parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
        )

    def test_approval_at_exactly_valid_until_is_accepted(self, paid_repair_order, api):
        """A quote issued at 09:00 on 06-15 is still approvable at 09:00 on 06-22.

        "The new row's `valid_until` is the logical clock instant advanced by seven days,
        and its `decided_at` is null until the customer answers."
        "Approval requires the estimate's `status` to be `SENT` and the logical clock
        instant to be at or before its `valid_until`, refusing a late approval with
        `ERR_ESTIMATE_EXPIRED`."
        "(35) The logical clock instant is at or before an estimate's `valid_until` when
        approving, else `ERR_ESTIMATE_EXPIRED` (409)."
        "On approval the estimate moves `SENT` → `APPROVED`, its `decided_at` is
        stamped, the order's `provisional_estimate_total_cents` is set from the
        estimate's `total_cents`, and the order's `billing_status` moves
        `ESTIMATE_SENT` → `ESTIMATE_APPROVED`"
        "**Step five** applies loyalty: `loyalty_discount_cents` is `subtotal_cents`
        multiplied by the owner's tier rate, rounded half up, where a `STANDARD` owner's
        rate is zero percent and a `PRO` owner's rate is ten percent."
        "a `PROVISIONAL` row always carries zero here, even on an expedited order"

        Design: Difficulty/boundary_precision_check/estimate_approval_at_exact_validity_instant_accepted
        """
        scenario = paid_repair_order.scenario
        estimate = self._zipper_estimate(paid_repair_order)
        assert estimate["status"] == "SENT", estimate
        assert estimate["variant"] == "PROVISIONAL", estimate
        assert estimate["valid_until"].startswith("2026-06-22T09:00:00"), estimate
        assert_estimate_breakdown(estimate, 5542, 1800, 388, 7730, 773, 0, 574, 7531)

        get_success_data(
            api.set_clock("2026-06-22T09:00:00Z", PROGRAM_ADMIN_HEADERS), 200
        )

        approved = validate_success(
            api.approve_estimate(
                estimate["id"], make_customer_headers(paid_repair_order.customer_id)
            ),
            200,
        )
        assert approved["status"] == "APPROVED", approved
        assert approved["decided_at"].startswith("2026-06-22T09:00:00"), approved

        order = scenario.read_order(paid_repair_order.order_id)
        assert order["billing_status"] == "ESTIMATE_APPROVED", order
        assert order["provisional_estimate_total_cents"] == 7531, order

    @pytest.mark.parametrize(
        "clock_utc",
        ["2026-06-22T09:00:00.001Z", "2026-06-22T09:00:01Z"],
        ids=["one_millisecond_past_valid_until", "one_second_past_valid_until"],
    )
    def test_approval_past_valid_until_is_refused(
        self, paid_repair_order, api, clock_utc
    ):
        """An instant strictly after 2026-06-22T09:00:00Z falls outside the quote window.

        "The new row's `valid_until` is the logical clock instant advanced by seven days,
        and its `decided_at` is null until the customer answers."
        "Approval requires the estimate's `status` to be `SENT` and the logical clock
        instant to be at or before its `valid_until`, refusing a late approval with
        `ERR_ESTIMATE_EXPIRED`."
        "(35) The logical clock instant is at or before an estimate's `valid_until` when
        approving, else `ERR_ESTIMATE_EXPIRED` (409)."

        Design: Difficulty/boundary_precision_check/estimate_approval_at_exact_validity_instant_accepted
        """
        scenario = paid_repair_order.scenario
        estimate = self._zipper_estimate(paid_repair_order)
        assert estimate["valid_until"].startswith("2026-06-22T09:00:00"), estimate

        get_success_data(api.set_clock(clock_utc, PROGRAM_ADMIN_HEADERS), 200)

        validate_error(
            api.approve_estimate(
                estimate["id"], make_customer_headers(paid_repair_order.customer_id)
            ),
            ERR_ESTIMATE_EXPIRED,
        )

        still_sent = scenario.read_estimate(estimate["id"])
        assert still_sent["status"] == "SENT", still_sent
        assert still_sent["decided_at"] is None, still_sent

        order = scenario.read_order(paid_repair_order.order_id)
        assert order["billing_status"] == "ESTIMATE_SENT", order
        assert order["provisional_estimate_total_cents"] is None, order


class TestLiabilityOpenExactlyEqualsCap:
    """PRD §2.9 — exposure exactly at the cap is CONSTRAINED, not FROZEN."""

    @pytest.mark.parametrize(
        "liability_cap_cents, posture",
        [(22390, "CONSTRAINED"), (22389, "FROZEN")],
        ids=["open_exactly_equals_cap_constrained", "open_one_cent_over_cap_frozen"],
    )
    def test_posture_at_and_past_the_cap(self, scenario, liability_cap_cents, posture):
        """A single 22390-cent reservation is CONSTRAINED against a 22390 cap and FROZEN against 22389.

        "If `open_liability_cents` is strictly greater than `liability_cap_cents`, the
        posture is `FROZEN`."
        "Otherwise, if `open_liability_cents` multiplied by one hundred is strictly
        greater than sixty multiplied by `liability_cap_cents`, the posture is
        `CONSTRAINED`."
        "Two boundaries are pinned by that wording: open exposure exactly equal to the
        cap is `CONSTRAINED`, not `FROZEN`, and open exposure at exactly sixty percent of
        the cap is `OPEN`, not `CONSTRAINED`."
        "Every posture comparison is performed on integer cents by cross-multiplication,
        so no floating-point representation can move a boundary."

        Design: Difficulty/boundary_precision_check/liability_open_exactly_equals_cap_stays_constrained
        """
        center_id, decided = _warranty_repair_claim_at_cap(
            scenario, liability_cap_cents
        )
        assert_claim_decision(decided, "WARRANTY_REPAIR", "WARRANTY_APPROVED")

        entries = scenario.liability_entries(decided["id"])
        assert len(entries) == 1, entries
        assert entries[0]["status"] == "OPEN", entries[0]
        assert entries[0]["reserved_amount_cents"] == 22390, entries[0]

        center = scenario.read_center(center_id)
        assert center["liability_cap_cents"] == liability_cap_cents, center
        assert_center_posture(center, 22390, posture=posture)

    def test_utilization_reads_100_percent_while_posture_stays_constrained(
        self, scenario
    ):
        """Open exposure of 22390 against a cap of 22390 displays 100.00 and stays CONSTRAINED.

        "`liability_utilization_pct` is one hundred multiplied by `open_liability_cents`
        divided by `liability_cap_cents`, rounded half up to two decimal places, and is
        display-only."
        "If `open_liability_cents` is strictly greater than `liability_cap_cents`, the
        posture is `FROZEN`."
        "Two boundaries are pinned by that wording: open exposure exactly equal to the
        cap is `CONSTRAINED`, not `FROZEN`, and open exposure at exactly sixty percent of
        the cap is `OPEN`, not `CONSTRAINED`."

        Design: Difficulty/boundary_precision_check/liability_open_exactly_equals_cap_stays_constrained
        """
        center_id, _ = _warranty_repair_claim_at_cap(scenario, 22390)

        center = scenario.read_center(center_id)
        assert center["liability_cap_cents"] == 22390, center
        assert_center_posture(center, 22390, utilization_pct=100.00, posture="CONSTRAINED")

    def test_queue_review_is_idempotent_at_the_exact_equality_point(self, scenario):
        """The checkpoint re-derives the same CONSTRAINED posture on 22390 against 22390.

        "`open_liability_cents` and `liability_utilization_pct` are rolled up afresh, and
        `liability_posture` is re-derived on the bands of §2.9 — so a checkpoint alone
        can move a centre's posture in either direction."
        "Two boundaries are pinned by that wording: open exposure exactly equal to the
        cap is `CONSTRAINED`, not `FROZEN`, and open exposure at exactly sixty percent of
        the cap is `OPEN`, not `CONSTRAINED`."
        "Every posture comparison is performed on integer cents by cross-multiplication,
        so no floating-point representation can move a boundary."

        Design: Difficulty/boundary_precision_check/liability_open_exactly_equals_cap_stays_constrained
        """
        center_id, _ = _warranty_repair_claim_at_cap(scenario, 22390)
        assert_center_posture(
            scenario.read_center(center_id),
            22390,
            utilization_pct=100.00,
            posture="CONSTRAINED",
        )

        scenario.queue_review(center_id)

        after = scenario.read_center(center_id)
        assert_center_posture(
            after, 22390, utilization_pct=100.00, posture="CONSTRAINED"
        )
