"""Boundary precision (partner backlog, sample item_count) and temporal
overlap (payout window, partner backlog capacity)."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    get_success_data,
    api_client,
    make_platform_admin_headers,
    make_anonymous_headers,
    make_creator_headers,
    set_clock,
    setup_basic_scenario,
    create_verified_creator,
    create_creator,
    create_active_partner,
    create_product_and_variant,
    create_storefront,
    upload_and_approve_design,
    create_and_publish_listing,
    create_order_and_authorize,
    create_and_capture_order,
    create_payout_cycle,
    order_payload,
    payout_cycle_payload,
)


# =============================================================================
# Rule 6 — boundary_precision: partner backlog == max is excluded
# =============================================================================

def test_partner_at_max_backlog_hours_excluded_from_routing(api):
    """PRD §3.7: "A partner whose `current_backlog_hours` equals its
    `max_backlog_hours` is excluded — equality means excluded."
    PRD §3.7: "If the fallback set is also empty, the routing attempt fails
    with `ERR_NO_ELIGIBLE_PARTNER`."

    Sole US partner has max_backlog_hours=1. First order (item_count=2) pushes
    backlog to 1. Second order's capture then finds no eligible partner because
    backlog == max (equality excluded).

    Design: Difficulty/boundary_precision_check/partner_backlog_at_max_strictly_less_than_excludes_from_routing
    """
    set_clock("2026-06-01T00:00:00Z")
    create_active_partner(name="US Cap1", country_code="US", max_backlog_hours=1)
    product, variant = create_product_and_variant(sku="T-B1", category="APPAREL")
    creator = create_verified_creator(email="b1@example.com", display_name="B1")
    storefront = create_storefront(creator["id"], slug="b1-sf", markup_bps=5000)
    design = upload_and_approve_design(creator["id"], file_hash="hash_b1")
    listing = create_and_publish_listing(
        storefront["id"], design["id"], variant["id"], creator["id"], title="B1 Tee",
    )
    # First order: item_count=2 -> backlog becomes 1
    first = get_success_data(api.create_order(
        order_payload(storefront["id"], listing["id"], item_count=2,
                      buyer_email="first@example.com"),
        make_anonymous_headers(),
    ))
    api.authorize_order(first["id"], make_platform_admin_headers())
    api.capture_order(first["id"], make_platform_admin_headers())

    # Second order: backlog is now 1 == max=1 so partner is excluded.
    second = get_success_data(api.create_order(
        order_payload(storefront["id"], listing["id"], item_count=1,
                      buyer_email="second@example.com"),
        make_anonymous_headers(),
    ))
    api.authorize_order(second["id"], make_platform_admin_headers())
    resp = api.capture_order(second["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PARTNER)


def test_partner_zero_max_backlog_excluded_immediately(api):
    """PRD §3.7: "A partner whose `current_backlog_hours` equals its
    `max_backlog_hours` is excluded — equality means excluded."
    PRD §3.7: "If the fallback set is also empty, the routing attempt fails
    with `ERR_NO_ELIGIBLE_PARTNER`."

    A partner minted with max_backlog_hours=0 starts at current=0. Since
    current (0) is not strictly less than max (0), it is immediately excluded.

    Design: Difficulty/boundary_precision_check/partner_backlog_at_max_strictly_less_than_excludes_from_routing
    """
    set_clock("2026-06-01T00:00:00Z")
    create_active_partner(name="US Cap0", country_code="US", max_backlog_hours=0)
    product, variant = create_product_and_variant(sku="T-B2", category="APPAREL")
    creator = create_verified_creator(email="b2@example.com", display_name="B2")
    storefront = create_storefront(creator["id"], slug="b2-sf", markup_bps=5000)
    design = upload_and_approve_design(creator["id"], file_hash="hash_b2")
    listing = create_and_publish_listing(
        storefront["id"], design["id"], variant["id"], creator["id"], title="B2 Tee",
    )
    order = get_success_data(api.create_order(
        order_payload(storefront["id"], listing["id"], item_count=1),
        make_anonymous_headers(),
    ))
    api.authorize_order(order["id"], make_platform_admin_headers())
    resp = api.capture_order(order["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PARTNER)


# =============================================================================
# Rule 6 — boundary: sample item_count upper bound off-by-one
# =============================================================================

def test_sample_order_item_count_four_rejected(api):
    """PRD §3.7: "Sample orders are bounded: `item_count` must fall in the
    inclusive range 1 to 3, and a submission with `item_count` strictly greater
    than 3 is rejected with `ERR_SAMPLE_LIMIT_EXCEEDED`."

    is_sample=true, item_count=4 -> ERR_SAMPLE_LIMIT_EXCEEDED.

    Design: Difficulty/boundary_precision_check/sample_item_count_upper_bound_off_by_one
    """
    scenario = setup_basic_scenario(
        creator_email="b3@example.com", display_name="B3", slug="b3-sf",
        sku="T-B3", markup_bps=5000, file_hash="hash_b3",
    )
    creator_id = scenario["creator"]["id"]
    resp = api.create_order(
        order_payload(
            scenario["storefront"]["id"], scenario["listing"]["id"],
            item_count=4, is_sample=True,
            buyer_email="sample@x.com",
        ),
        make_creator_headers(creator_id),
    )
    validate_error(resp, ApiErrorId.ERR_SAMPLE_LIMIT_EXCEEDED)


def test_sample_order_item_count_three_is_accepted_upper_bound_inclusive(api):
    """PRD §3.7: "Sample orders are bounded: `item_count` must fall in the
    inclusive range 1 to 3, and a submission with `item_count` strictly greater
    than 3 is rejected with `ERR_SAMPLE_LIMIT_EXCEEDED`."

    The upper bound is inclusive: item_count=3 is accepted (proving the
    off-by-one boundary at 4).

    Design: Difficulty/boundary_precision_check/sample_item_count_upper_bound_off_by_one
    """
    scenario = setup_basic_scenario(
        creator_email="b4@example.com", display_name="B4", slug="b4-sf",
        sku="T-B4", markup_bps=5000, file_hash="hash_b4",
    )
    creator_id = scenario["creator"]["id"]
    resp = api.create_order(
        order_payload(
            scenario["storefront"]["id"], scenario["listing"]["id"],
            item_count=3, is_sample=True,
            buyer_email="sample3@x.com",
        ),
        make_creator_headers(creator_id),
    )
    from test_helpers import validate_success
    data = validate_success(resp, expected_status=201)
    assert data["item_count"] == 3
    assert data["is_sample"] is True


# =============================================================================
# Rule 8 — resource_temporal_overlap: PayoutCycle half-open windows
# =============================================================================

def test_overlapping_draft_payout_cycles_rejected_for_same_creator(api):
    """PRD §3.9: "In addition, a new draft cycle whose window overlaps any other
    cycle already in `DRAFT` for the same creator is rejected. Both
    length-non-positive and window-overlap failures surface as
    `ERR_PAYOUT_WINDOW_OVERLAP`."

    Cycle A [2026-04-01, 2026-05-01) exists as DRAFT. Cycle B
    [2026-04-15, 2026-05-15) overlaps in [2026-04-15, 2026-05-01) -> rejected.

    Design: Difficulty/resource_temporal_overlap/payout_cycle_windows_overlap_on_same_creator_half_open
    """
    set_clock("2026-05-15T00:00:00Z")
    creator = create_creator(email="ov1@example.com", display_name="OV1")
    # First cycle DRAFT
    create_payout_cycle(
        creator["id"],
        cycle_start="2026-04-01T00:00:00Z",
        cycle_end="2026-05-01T00:00:00Z",
    )
    # Second cycle overlaps
    resp = api.create_payout_cycle(
        creator["id"],
        payout_cycle_payload(
            cycle_start="2026-04-15T00:00:00Z",
            cycle_end="2026-05-15T00:00:00Z",
        ),
        make_platform_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_PAYOUT_WINDOW_OVERLAP)


def test_zero_length_payout_cycle_rejected(api):
    """PRD §3.9: "The window is half-open: the interval covered is inclusive of
    `cycle_start` and exclusive of `cycle_end`, and the cycle duration
    (`cycle_end` minus `cycle_start`) must be strictly greater than zero. In
    addition, a new draft cycle whose window overlaps any other cycle already in
    `DRAFT` for the same creator is rejected. Both length-non-positive and
    window-overlap failures surface as `ERR_PAYOUT_WINDOW_OVERLAP`."

    cycle_start == cycle_end (zero-length) is length-non-positive -> rejected.

    Design: Difficulty/resource_temporal_overlap/payout_cycle_windows_overlap_on_same_creator_half_open
    """
    set_clock("2026-05-15T00:00:00Z")
    creator = create_creator(email="ov2@example.com", display_name="OV2")
    resp = api.create_payout_cycle(
        creator["id"],
        payout_cycle_payload(
            cycle_start="2026-05-10T00:00:00Z",
            cycle_end="2026-05-10T00:00:00Z",
        ),
        make_platform_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_PAYOUT_WINDOW_OVERLAP)


# =============================================================================
# Rule 8 — resource_temporal_overlap: partner backlog aggregate capacity
# =============================================================================

def test_partner_backlog_at_capacity_blocks_next_route(api):
    """PRD §3.7: "A partner whose `current_backlog_hours` equals its
    `max_backlog_hours` is excluded — equality means excluded."
    PRD §3.7: "the selected partner's `current_backlog_hours` is increased by
    the ceiling of `item_count` multiplied by 0.5."
    PRD §3.7: "If the fallback set is also empty, the routing attempt fails
    with `ERR_NO_ELIGIBLE_PARTNER`."

    Partner max=1. Prior order (item_count=2) fills backlog to 1. A second
    capture finds no eligible partner (aggregate backlog capacity exhausted).

    Design: Difficulty/resource_temporal_overlap/partner_backlog_aggregate_capacity_overload
    """
    set_clock("2026-06-01T00:00:00Z")
    create_active_partner(name="US Cap1B", country_code="US", max_backlog_hours=1)
    product, variant = create_product_and_variant(sku="T-B5", category="APPAREL")
    creator = create_verified_creator(email="b5@example.com", display_name="B5")
    storefront = create_storefront(creator["id"], slug="b5-sf", markup_bps=5000)
    design = upload_and_approve_design(creator["id"], file_hash="hash_b5")
    listing = create_and_publish_listing(
        storefront["id"], design["id"], variant["id"], creator["id"], title="B5 Tee",
    )
    first = get_success_data(api.create_order(
        order_payload(storefront["id"], listing["id"], item_count=2,
                      buyer_email="first_b5@x.com"),
        make_anonymous_headers(),
    ))
    api.authorize_order(first["id"], make_platform_admin_headers())
    api.capture_order(first["id"], make_platform_admin_headers())

    second = get_success_data(api.create_order(
        order_payload(storefront["id"], listing["id"], item_count=1,
                      buyer_email="second_b5@x.com"),
        make_anonymous_headers(),
    ))
    api.authorize_order(second["id"], make_platform_admin_headers())
    resp = api.capture_order(second["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PARTNER)


def test_partner_backlog_increases_by_ceil_of_item_count_half(api):
    """PRD §3.7: "the selected partner's `current_backlog_hours` is increased by
    the ceiling of `item_count` multiplied by 0.5."

    For item_count=2 the delta is ceil(1.0)=1 — verifying the aggregate-hours
    capacity accounting that Rule 8 exhausts against the partner's max.

    Design: Difficulty/resource_temporal_overlap/partner_backlog_aggregate_capacity_overload
    """
    scenario = setup_basic_scenario(
        creator_email="b6@example.com", display_name="B6", slug="b6-sf",
        sku="T-B6", markup_bps=5000, file_hash="hash_b6",
    )
    partner_before = get_success_data(
        api.get_fulfillment_partner(scenario["partner"]["id"], make_platform_admin_headers())
    )
    _order, _ = create_and_capture_order(scenario, item_count=2)
    partner_after = get_success_data(
        api.get_fulfillment_partner(scenario["partner"]["id"], make_platform_admin_headers())
    )
    delta = partner_after["current_backlog_hours"] - partner_before["current_backlog_hours"]
    assert delta == 1, f"Expected backlog delta=ceil(2*0.5)=1, got {delta}"
