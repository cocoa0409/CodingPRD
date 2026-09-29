"""Two interval rules with deliberately different semantics.

Markdown-stage windows are half-open and constrained pairwise, so back-to-back
stages that share a boundary date are legal; delivery windows are closed intervals
constrained by an aggregate per-day count, so a shared boundary day is counted
twice and a third cover of it is refused.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    assert_augmentation_consignment,
    assert_markdown_stage,
    consignment_payload,
    create_engagement,
    create_jurisdiction,
    decide_license,
    make_consultant_headers,
    markdown_stage_payload,
    pin_clock,
    propose_consignment,
    read_store,
    store_version,
    submit_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}
ELECTRONICS_LOT = {
    "category": "ELECTRONICS", "source": "ORIGINAL", "units_initial": 200,
    "unit_cost_cents": 15000, "unit_retail_cents": 30000,
}
NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
FEE_BASED_LIQUIDATOR = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "LIQUIDATOR",
    "shared_expense_liquidator_pct": 0, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}
THIRD_STAGE = {
    "stage_index": 3, "discount_pct": 0.5, "sell_through_target_pct": 0.75,
    "window_start_date": "2026-10-12", "window_end_date": "2026-10-26",
}


def _read_stage(stage_id):
    return validate_success(
        api_client.get_markdown_stage(stage_id, make_consultant_headers())
    )


def _licensed_selling_store(store_code, address, license_number):
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code=store_code, address_line=address,
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_inventory_lot(store["id"], **ELECTRONICS_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number=license_number,
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    return {"engagement": engagement, "store": store}


def _store_with_two_back_to_back_armed_stages():
    """Stage 1 over [2026-09-15,2026-09-29) and stage 2 over [2026-09-29,2026-10-13).

    Neither stage is ever activated, so both stay ARMED and both remain candidates
    for the overlap test.
    """
    scenario = _licensed_selling_store("S-1201", "8 Foundry St", "NY-GOB-1201")
    store = scenario["store"]
    scenario["stage_one"] = add_markdown_stage(
        store["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.3,
        window_start_date="2026-09-15", window_end_date="2026-09-29",
    )
    scenario["stage_two"] = add_markdown_stage(
        store["id"], stage_index=2, discount_pct=0.4, sell_through_target_pct=0.6,
        window_start_date="2026-09-29", window_end_date="2026-10-13",
    )
    return scenario


def _propose_third_stage(store_id, **extra):
    payload = markdown_stage_payload(store_version(store_id), **THIRD_STAGE)
    payload.update(extra)
    return api_client.create_markdown_stage(
        store_id, payload, make_consultant_headers()
    )


class TestMarkdownStageWindowsAreHalfOpen:
    def test_a_shared_boundary_date_is_not_an_overlap(self):
        """Stage 2 starts on the very day stage 1's window excludes.

        The PRD says: "A new stage whose half-open window overlaps the window of an
        existing `ARMED` or `ACTIVE` stage of the same store is refused with
        `ERR_STAGE_WINDOW_OVERLAP` — but because the interval is half-open, two
        back-to-back stages that share a boundary date do not overlap, and the second
        may be authored freely."

        Design: Difficulty/resource_temporal_overlap/markdown_stage_windows_are_half_open_so_shared_boundary_dates_do_not_overlap
        """
        scenario = _store_with_two_back_to_back_armed_stages()
        stage_one, stage_two = scenario["stage_one"], scenario["stage_two"]
        assert stage_one["window_end_date"] == "2026-09-29"
        assert stage_two["window_start_date"] == "2026-09-29"
        assert_markdown_stage(stage_two)
        assert stage_two["stage_status"] == "ARMED"

    def test_one_day_of_true_overlap_is_refused_and_persists_nothing(self):
        """A window starting 2026-10-12 falls inside [2026-09-29,2026-10-13).

        The PRD says: "Stage window overlap on authoring a stage — otherwise
        `ERR_STAGE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/markdown_stage_windows_are_half_open_so_shared_boundary_dates_do_not_overlap
        """
        scenario = _store_with_two_back_to_back_armed_stages()
        store_id = scenario["store"]["id"]
        response = _propose_third_stage(store_id)
        validate_error(response, ApiErrorId.ERR_STAGE_WINDOW_OVERLAP.value, 409)
        rows, _meta = validate_paginated(
            api_client.list_markdown_stages(store_id, make_consultant_headers())
        )
        assert len(rows) == 2
        assert sorted(row["stage_index"] for row in rows) == [1, 2]

    def test_the_supersede_flag_voids_the_overlapped_stage_instead_of_refusing(self):
        """The identical create succeeds and retires stage 2 as SUPERSEDED.

        The PRD says: "Overlap is permitted in exactly one circumstance: when the
        request sets `supersede_overlapping` to true, every overlapped `ARMED` stage
        moves `ARMED → VOIDED` with `closed_reason` of `SUPERSEDED` and its own
        `version` incremented."

        Design: Difficulty/resource_temporal_overlap/markdown_stage_windows_are_half_open_so_shared_boundary_dates_do_not_overlap
        """
        scenario = _store_with_two_back_to_back_armed_stages()
        store_id = scenario["store"]["id"]
        _propose_third_stage(store_id)
        stage_three = validate_success(
            _propose_third_stage(store_id, supersede_overlapping=True), 201
        )
        assert stage_three["stage_status"] == "ARMED"
        assert stage_three["discount_pct"] == pytest.approx(0.5000, abs=0.00001)
        stage_two = _read_stage(scenario["stage_two"]["id"])
        assert stage_two["stage_status"] == "VOIDED"
        assert stage_two["closed_reason"] == "SUPERSEDED"
        assert stage_two["activated_at"] is None
        stage_one = _read_stage(scenario["stage_one"]["id"])
        assert stage_one["stage_status"] == "ARMED"

    def test_the_voided_stage_leaves_the_planned_set_and_moves_the_projection(self):
        """The planned discount becomes the average of the surviving 0.20 and 0.50.

        The PRD says: "The supersede branch diverges from the ordinary activation
        branch in three ways worth naming: a voided stage never receives an
        `activated_at`, it never participates in escalation, and it leaves the
        armed-and-active set, so the store's `planned_avg_discount_pct` and the whole
        projected-recovery chain of §3.2 are recomputed as a direct consequence."

        Design: Difficulty/resource_temporal_overlap/markdown_stage_windows_are_half_open_so_shared_boundary_dates_do_not_overlap
        """
        scenario = _store_with_two_back_to_back_armed_stages()
        store_id = scenario["store"]["id"]
        _propose_third_stage(store_id)
        _propose_third_stage(store_id, supersede_overlapping=True)
        store = read_store(store_id)
        assert store["planned_avg_discount_pct"] == pytest.approx(0.3500, abs=0.00001)
        assert store["projected_gross_recovery_cents"] == 6467500
        assert store["projected_recovery_ratio"] == pytest.approx(1.2935, abs=0.00001)


HOME_CONSIGNMENT = {
    "category": "HOME", "units_supplied": 100,
    "unit_cost_cents": 1000, "unit_retail_cents": 2500,
}


def _read_consignment(consignment_id):
    return validate_success(
        api_client.get_augmentation_consignment(
            consignment_id, make_consultant_headers()
        )
    )


def _store_whose_dock_is_already_booked_twice_on_one_day():
    """Two closed delivery windows that both cover 2026-09-22.

    Consignment A runs 2026-09-20..2026-09-22 and consignment B runs
    2026-09-22..2026-09-24, so the shared boundary day is covered twice while both
    rows are still merely PROPOSED.
    """
    scenario = _licensed_selling_store("S-1301", "14 Dock St", "NY-GOB-1301")
    store = scenario["store"]
    scenario["consignment_a"] = propose_consignment(
        store["id"], supplier_name="Overstock Partners",
        delivery_window_start_date="2026-09-20",
        delivery_window_end_date="2026-09-22", **HOME_CONSIGNMENT
    )
    scenario["consignment_b"] = propose_consignment(
        store["id"], supplier_name="Clearance Depot",
        delivery_window_start_date="2026-09-22",
        delivery_window_end_date="2026-09-24", **HOME_CONSIGNMENT
    )
    return scenario


def _propose_raw(store_id, start_date, end_date):
    payload = consignment_payload(
        supplier_name="Third Supplier", category="HOME", units_supplied=50,
        unit_cost_cents=1000, unit_retail_cents=2500,
        delivery_window_start_date=start_date,
        delivery_window_end_date=end_date,
    )
    return api_client.create_augmentation_consignment(
        store_id, payload, make_consultant_headers()
    )


class TestDeliveryWindowsAreClosedIntervalsWithCapacityTwo:
    def test_two_windows_may_share_their_boundary_day(self):
        """Both endpoint days belong to a delivery window, so 2026-09-22 is covered
        twice.

        The PRD says: "That window — `delivery_window_start_date` through
        `delivery_window_end_date` — is a closed interval, unlike a markdown window:
        both endpoint days belong to it, and the end may not precede the start."

        Design: Difficulty/resource_temporal_overlap/augmentation_delivery_windows_are_closed_intervals_with_per_day_capacity_two
        """
        scenario = _store_whose_dock_is_already_booked_twice_on_one_day()
        consignment_a = scenario["consignment_a"]
        consignment_b = scenario["consignment_b"]
        assert_augmentation_consignment(consignment_a)
        assert_augmentation_consignment(consignment_b)
        assert consignment_a["consignment_status"] == "PROPOSED"
        assert consignment_b["consignment_status"] == "PROPOSED"
        assert consignment_a["delivery_window_end_date"] == "2026-09-22"
        assert consignment_b["delivery_window_start_date"] == "2026-09-22"

    def test_a_third_single_day_cover_of_that_day_is_refused(self):
        """A one-day window is still a third cover of an already twice-booked day.

        The PRD says: "And the receiving dock has finite capacity: a store may have at
        most two consignments whose closed delivery windows both cover any single
        calendar day, counting consignments in `PROPOSED`, `DISCLOSURE_FILED`, and
        `RECEIVED`; a third overlapping window is refused with
        `ERR_DELIVERY_SLOT_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/augmentation_delivery_windows_are_closed_intervals_with_per_day_capacity_two
        """
        scenario = _store_whose_dock_is_already_booked_twice_on_one_day()
        response = _propose_raw(
            scenario["store"]["id"], "2026-09-22", "2026-09-22"
        )
        validate_error(response, ApiErrorId.ERR_DELIVERY_SLOT_CAPACITY.value, 409)

    def test_a_disjoint_window_is_still_accepted_after_the_refusal(self):
        """The limit binds per calendar day, not per store.

        The PRD says: "Delivery slot capacity on proposing a consignment — otherwise
        `ERR_DELIVERY_SLOT_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/augmentation_delivery_windows_are_closed_intervals_with_per_day_capacity_two
        """
        scenario = _store_whose_dock_is_already_booked_twice_on_one_day()
        store_id = scenario["store"]["id"]
        _propose_raw(store_id, "2026-09-22", "2026-09-22")
        accepted = validate_success(
            _propose_raw(store_id, "2026-09-25", "2026-09-26"), 201
        )
        assert accepted["consignment_status"] == "PROPOSED"
        assert accepted["delivery_window_start_date"] == "2026-09-25"
        rows, _meta = validate_paginated(
            api_client.list_augmentation_consignments(
                store_id, make_consultant_headers()
            )
        )
        assert len(rows) == 3

    def test_the_limit_binds_on_proposed_rows_that_hold_no_inventory_at_all(self):
        """Nothing was received, so the store's augmentation figures are still empty.

        The PRD says: "A proposal opens at `consignment_status` of `PROPOSED` with
        `units_returned` at 0, `disclosure_reference` and `disclosure_filed_at` unset,
        and `cost_value_cents` computed as `units_supplied` multiplied by
        `unit_cost_cents`."

        Design: Difficulty/resource_temporal_overlap/augmentation_delivery_windows_are_closed_intervals_with_per_day_capacity_two
        """
        scenario = _store_whose_dock_is_already_booked_twice_on_one_day()
        store_id = scenario["store"]["id"]
        _propose_raw(store_id, "2026-09-22", "2026-09-22")
        _propose_raw(store_id, "2026-09-25", "2026-09-26")
        for key in ("consignment_a", "consignment_b"):
            consignment = _read_consignment(scenario[key]["id"])
            assert consignment["consignment_status"] == "PROPOSED"
            assert consignment["units_returned"] == 0
            assert consignment["cost_value_cents"] == 100000
        store = read_store(store_id)
        assert store["augmentation_cost_value_cents"] == 0
        assert store["units_initial_total"] == 1200
