"""The catalog, house stock, the ordered size ladder and the box-fill selector."""

from test_helpers import (
    ADMIN,
    PLANNER,
    WAREHOUSE,
    ApiErrorId,
    assert_garment_style,
    assert_garment_unit,
    assert_unit_conservation,
    create_active_member,
    create_box,
    create_garment_style_payload,
    create_garment_unit_payload,
    create_open_cycle,
    create_plan,
    create_style,
    create_unit,
    get_box,
    get_style,
    get_unit,
    list_units,
    set_clock,
    setup_plan_and_member,
    validate_error,
    validate_paginated,
    validate_success,
)


def _member_with_draft_box(child_size_code="5", slots_per_box=1):
    plan, member = setup_plan_and_member(
        plan={"slots_per_box": slots_per_box},
        member={"child_size_code": child_size_code},
    )
    cycle = create_open_cycle(member["id"])
    box = create_box(cycle["id"])
    return plan, member, cycle, box


class TestCatalog:
    def test_duplicate_sku_is_refused_across_the_whole_catalog(self, api):
        """PRD §2.9: "A member whose `email` duplicates an existing member's is
        refused with `ERR_DUPLICATE_EMAIL` (HTTP 409), and a garment style whose
        `sku` duplicates an existing style's is refused with `ERR_DUPLICATE_SKU`
        (HTTP 409)."
        PRD §3.3: "it carries a `sku` that must be unique across styles"

        Design: Corner/entities/corner_garment_style_duplicate_sku_is_rejected
        """
        create_style(sku="SKU-UNIQ-1", name="Unique One", brand_tier="STANDARD",
                     retail_price_cents=3000, size_code="5", season="SS", category="TOP")
        resp = api.create_garment_style(
            create_garment_style_payload(sku="SKU-UNIQ-1", name="Unique Two",
                                         brand_tier="PREMIUM", retail_price_cents=4000,
                                         size_code="8", season="AW", category="BOTTOM"),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU.value, 409)
        _, meta = validate_paginated(api.list_garment_styles(PLANNER, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 1

    def test_demand_band_defaults_to_medium_and_the_unit_counter_starts_at_zero(self, api):
        """PRD §3.3: "a free-text `category` such as OUTERWEAR, TOP, BOTTOM or
        DRESS, and a `demand_band` of `HIGH`, `MEDIUM` or `LOW` that defaults to
        `MEDIUM`."
        PRD §3.3: "Its `units_ever_acquired` counter starts at 0 and counts
        every physical unit ever created for that style from either acquisition
        source."
        PRD §3.3: "A style is born `ACTIVE` and may be moved to `DISCONTINUED`"

        Design: Corner/entities/corner_garment_style_demand_band_defaults_to_medium
        """
        set_clock("2026-05-01T00:00:00Z")
        style = validate_success(
            api.create_garment_style(
                create_garment_style_payload(sku="SKU-DEF-1", name="Default Band",
                                             brand_tier="VALUE", retail_price_cents=1500,
                                             size_code="3T", season="SS", category="TOP"),
                PLANNER,
            ),
            201,
        )
        assert_garment_style(style)
        assert style["demand_band"] == "MEDIUM"
        assert style["units_ever_acquired"] == 0
        assert style["status"] == "ACTIVE"

    def test_acquiring_units_stamps_their_defaults_and_raises_the_style_counter(self, api):
        """PRD §3.3: "Every acquired unit begins with `state` `IN_STOCK`,
        `acquisition_source` `PURCHASED`, `current_grade` `A` when none is
        supplied, `cycles_completed` and `cumulative_cleaning_cost_cents` at 0,
        `retirement_eligible` false, `retired_reason` null and `capsule_id`
        null, and it increments its style's `units_ever_acquired` by 1."
        PRD §2.10: "For each `GarmentStyle`, its `units_ever_acquired` equals the
        total number of that style's units counted across all eight circulation
        states: `IN_STOCK`, `RESERVED`, `OUT`, `INBOUND`, `PROCESSING`,
        `LOST_IN_TRANSIT`, `RETIRED` and `SOLD`."

        Design: Corner/entities/corner_garment_unit_creation_increments_style_acquisition_counter
        """
        style = create_style(sku="SKU-ACQ-1", name="Acq Style")
        first = validate_success(
            api.create_garment_unit(
                create_garment_unit_payload(style["id"], acquired_at="2026-02-01T00:00:00Z"),
                PLANNER,
            ),
            201,
        )
        create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")

        assert_garment_unit(first)
        assert first["state"] == "IN_STOCK"
        assert first["acquisition_source"] == "PURCHASED"
        assert first["cycles_completed"] == 0
        assert first["cumulative_cleaning_cost_cents"] == 0
        assert first["current_grade"] == "A"
        assert first["retirement_eligible"] is False

        refreshed = get_style(style["id"])
        assert refreshed["units_ever_acquired"] == 2
        assert_unit_conservation(refreshed, list_units(style_id=style["id"]))

    def test_acquiring_against_an_unknown_style_is_not_found(self, api):
        """PRD §2.6 rung 8: "The `GarmentStyle` or `GarmentUnit` identifier in the
        path or body resolves. Otherwise `ERR_STYLE_NOT_FOUND` (404). Applies to
        garment-style, garment-unit, box allocation and trade-in absorption
        endpoints."

        Design: Corner/entities/corner_garment_unit_creation_against_unknown_style_returns_not_found
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_garment_unit(
            {"style_id": "11111111-2222-3333-4444-555555555555",
             "acquired_at": "2026-02-01T00:00:00Z"},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_STYLE_NOT_FOUND.value, 404)
        _, meta = validate_paginated(api.list_garment_units(PLANNER, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_acquiring_against_a_discontinued_style_is_refused(self, api):
        """PRD §3.3: "a unit acquired against a `DISCONTINUED` style is refused
        with `ERR_STYLE_DISCONTINUED`."
        PRD §3.3: "only `demand_band` and `status` may be updated later, and the
        planner should know that `demand_band` is a live input to the trade-in
        credit multiplier, so editing it changes what future trade-ins are
        worth."

        Design: Corner/errors/corner_err_unit_acquired_against_a_discontinued_style_is_rejected
        """
        style = create_style(sku="SKU-X-DISC", name="Discontinued Tee")
        create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        validate_success(
            api.update_garment_style(style["id"], {"status": "DISCONTINUED"}, PLANNER)
        )

        resp = api.create_garment_unit(
            create_garment_unit_payload(style["id"], acquired_at="2026-03-01T00:00:00Z"),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_STYLE_DISCONTINUED.value, 409)
        assert get_style(style["id"])["units_ever_acquired"] == 1


class TestSizeCompatibility:
    def test_a_unit_one_rung_above_the_child_is_allocatable(self, api):
        """PRD §3.1: "a unit is compatible when its style's size ordinal minus
        the member's `child_size_code` ordinal is at least 0 — a unit may never
        sit *below* the child's size, because `SIZE_COMPAT_STEPS_BELOW_MAX` is 0
        — and at most 1, because `SIZE_COMPAT_STEPS_ABOVE_MAX` is 1."
        PRD §3.1: "A difference of exactly 0 and a difference of exactly 1 are
        both compatible; a difference of 2 is not, and a difference of −1 is
        not."

        Design: Corner/calculations/corner_calc_size_one_step_above_member_is_allocatable
        """
        _, member, _, box = _member_with_draft_box(child_size_code="5")
        style = create_style(sku="SKU-K1-6", name="One Up Tee", size_code="6")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")

        item = validate_success(api.allocate_into_box(box["id"], {"unit_id": unit["id"]},
                                                      WAREHOUSE), 201)
        assert item["fulfillment_status"] == "ALLOCATED"
        assert get_unit(unit["id"])["state"] == "RESERVED"
        assert get_box(box["id"])["slots_free"] == 0

    def test_a_unit_below_the_child_size_is_incompatible(self, api):
        """PRD §2.6 rung 53: "The unit's size ordinal minus the member's size
        ordinal lies within the closed range from 0 to 1; the comparison is an
        ordered ladder comparison, never an equality test. Otherwise
        `ERR_SIZE_INCOMPATIBLE` (409)."
        PRD §3.1: "A difference of exactly 0 and a difference of exactly 1 are
        both compatible; a difference of 2 is not, and a difference of −1 is
        not."

        Design: Corner/calculations/corner_calc_size_below_member_is_rejected
        """
        _, member, _, box = _member_with_draft_box(child_size_code="6")
        style = create_style(sku="SKU-K2-5", name="One Down Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")

        resp = api.allocate_into_box(box["id"], {"unit_id": unit["id"]}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_SIZE_INCOMPATIBLE.value, 409)
        assert get_unit(unit["id"])["state"] == "IN_STOCK"
        assert get_box(box["id"])["slots_free"] == 1

    def test_a_unit_two_rungs_above_the_child_is_incompatible(self, api):
        """PRD §3.1: "a unit is compatible when its style's size ordinal minus
        the member's `child_size_code` ordinal is at least 0 — a unit may never
        sit *below* the child's size, because `SIZE_COMPAT_STEPS_BELOW_MAX` is 0
        — and at most 1, because `SIZE_COMPAT_STEPS_ABOVE_MAX` is 1."
        PRD §3.3: "allocating a unit whose size fails the ladder test is refused
        with `ERR_SIZE_INCOMPATIBLE`"

        Design: Corner/calculations/corner_calc_size_two_steps_above_is_rejected
        """
        _, member, _, box = _member_with_draft_box(child_size_code="5")
        style = create_style(sku="SKU-K3-6X", name="Two Up Tee", size_code="6X")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")

        resp = api.allocate_into_box(box["id"], {"unit_id": unit["id"]}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_SIZE_INCOMPATIBLE.value, 409)
        assert get_unit(unit["id"])["state"] == "IN_STOCK"


class TestBoxFillSelector:
    def test_the_selector_reserves_the_least_worn_unit(self, api):
        """PRD §3.3: "The **standard fill** variant applies when the requested
        style carries no capsule membership; it restricts the pool to units
        whose `capsule_id` is null and ranks them by `cycles_completed`
        ascending, then by `cumulative_cleaning_cost_cents` ascending, breaking
        ties by `created_at` ascending — least-worn first, spreading wear evenly
        across stock."
        PRD §3.3: "Neither variant ever uses a row's `id` as a decision input;
        selection is fully deterministic from the declared ranking."

        Design: Corner/calculations/corner_calc_selector_picks_the_least_worn_unit_first
        """
        _, member, _, box = _member_with_draft_box(child_size_code="5")
        style = create_style(sku="SKU-K16-5", name="Selector Tee", size_code="5")
        worn = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z",
                           current_grade="B", cycles_completed=3)
        fresh = create_unit(style["id"], acquired_at="2026-01-02T00:00:00Z",
                            current_grade="B", cycles_completed=1)

        item = validate_success(
            api.allocate_into_box(box["id"], {"style_id": style["id"]}, WAREHOUSE), 201
        )
        assert get_unit(fresh["id"])["state"] == "RESERVED"
        assert get_unit(worn["id"])["state"] == "IN_STOCK"
        assert item["unit_id"] == fresh["id"]
        assert get_box(box["id"])["slots_free"] == 0

    def test_allocation_by_style_with_no_stock_at_all_is_refused(self, api):
        """PRD §3.3: "If either variant's pool is empty, the whole request is
        refused with `ERR_NO_ELIGIBLE_STOCK`."
        PRD §2.6 rung 54: "At least one `GarmentUnit` satisfies the selector's
        eligibility filter for each requested style. Otherwise
        `ERR_NO_ELIGIBLE_STOCK` (409). Applies to
        `POST /kidswear/boxes/{box_id}/allocate` and
        `POST /kidswear/swap-requests/{swap_request_id}/approve`."

        Design: Difficulty/boundary_precision_check/allocate_by_style_with_empty_candidate_pool_rejects
        """
        _, member, _, box = _member_with_draft_box(child_size_code="5")
        style = create_style(sku="SKU-EMPTY-5", name="Never Stocked", size_code="5")

        resp = api.allocate_into_box(box["id"], {"style_id": style["id"]}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_STOCK.value, 409)
        assert get_style(style["id"])["units_ever_acquired"] == 0

    def test_the_empty_pool_refusal_leaves_the_draft_box_untouched(self, api):
        """PRD §3.3: "If either variant's pool is empty, the whole request is
        refused with `ERR_NO_ELIGIBLE_STOCK`."
        PRD §3.3: "The `slots_free` figure is always `slot_capacity` minus the
        count of the box's items whose `fulfillment_status` is `ALLOCATED`,
        `SHIPPED`, `WITH_MEMBER` or `RETURNING`, minus the count of items whose
        `settlement_status` is `BOUGHT_OUT`."

        Design: Difficulty/boundary_precision_check/allocate_by_style_with_empty_candidate_pool_rejects
        """
        _, member, _, box = _member_with_draft_box(child_size_code="5")
        style = create_style(sku="SKU-EMPTY-5B", name="Never Stocked Two", size_code="5")

        resp = api.allocate_into_box(box["id"], {"style_id": style["id"]}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_STOCK.value, 409)

        after = get_box(box["id"])
        assert after["slots_free"] == 1
        assert after["status"] == "DRAFT"

    def test_a_retire_graded_unit_may_never_be_allocated(self, api):
        """PRD §2.6 rung 55: "A `GarmentUnit` whose `current_grade` is `RETIRE`,
        or whose `retirement_eligible` is true, may never be allocated, shipped,
        swapped in, or bought out. Otherwise `ERR_UNIT_RETIRE_GRADED` (409)."
        PRD §3.3: "Every acquired unit begins with `state` `IN_STOCK`, ...
        `retirement_eligible` false, `retired_reason` null and `capsule_id`
        null" — so the *first* disjunct of rung 55 is what refuses this
        allocation; the stored `retirement_eligible` flag is only re-evaluated
        by a passing processing job (§3.6) and is not asserted here.

        Design: Corner/validations/corner_val_retire_graded_unit_cannot_be_allocated
        """
        _, member, _, box = _member_with_draft_box(child_size_code="5")
        style = create_style(sku="SKU-V13-5", name="Written Off Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z",
                           current_grade="RETIRE", cycles_completed=0)

        resp = api.allocate_into_box(box["id"], {"unit_id": unit["id"]}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_UNIT_RETIRE_GRADED.value, 409)

        after_unit = get_unit(unit["id"])
        assert after_unit["current_grade"] == "RETIRE"
        assert after_unit["state"] == "IN_STOCK"
        assert get_box(box["id"])["slots_free"] == 1

    def test_a_reserved_unit_may_not_be_retired_out_of_stock(self, api):
        """PRD §3.3: "A `MerchandisePlanner` may also retire a unit directly out
        of stock by supplying a `reason`, which moves it `IN_STOCK → RETIRED`
        and bumps its `version`; that is the only edge into `RETIRED` that does
        not pass through processing or a claim."
        PRD §2.6 rung 27: "`GarmentUnit.state` is a declared from-state for the
        requested circulation transition. Otherwise `ERR_UNIT_INVALID_STATE`
        (409). Applies to allocation, shipping, return-start, receiving,
        retirement and processing endpoints."

        Design: Corner/errors/corner_err_retiring_a_reserved_unit_is_rejected
        """
        _, member, _, box = _member_with_draft_box(child_size_code="5", slots_per_box=2)
        style = create_style(sku="SKU-Y4-5", name="State Four Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        validate_success(api.allocate_into_box(box["id"], {"unit_id": unit["id"]},
                                               WAREHOUSE), 201)

        resp = api.retire_garment_unit(unit["id"], {"reason": "COST_CAP"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_UNIT_INVALID_STATE.value, 409)

        after = get_unit(unit["id"])
        assert after["state"] == "RESERVED"
        assert after["retired_reason"] is None
        assert get_style(style["id"])["units_ever_acquired"] == 1
