"""Pinned arithmetic on the pricing side of the contract.

Bundle allocation and its residual member, the effective advertised price with
its single-largest-discount rule and its truncated attribution cap, governing
policy selection across a supersession, the two override-floor branches, and
the half-open exception windows behind the computed floor read.  Every figure is
re-derived from an independent oracle and compared against the pinned literal.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ANALYST_HEADERS, BCM_HEADERS, COUNSEL_HEADERS, api_client
from test_helpers.assertions import (
    allocate_bundle,
    clearance_override_floor,
    deviation_cents,
    deviation_pct,
    effective_advertised_price,
    floor_to_int,
    override_floor_lower_bound,
    round_half_up,
    violation_points,
)
from test_helpers.factories import clearance_exception_payload, exception_decision_payload
from test_helpers.fixtures import (
    approve_exception,
    capture_observation,
    create_authorized_reseller,
    create_product,
    create_published_policy,
    evaluate_observation,
    pin_clock,
    read_effective_floor,
    read_exception,
    read_observation,
    read_policy,
    read_product,
    request_exception,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_16 = "2026-08-16T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_10 = "2026-08-10T00:00:00Z"
OBSERVED_AUG_14 = "2026-08-14T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"

STANDARD_FLOOR = 15000
MSRP = 20000

WINDOW_STARTS = "2026-08-10T00:00:00Z"
WINDOW_ENDS = "2026-08-25T00:00:00Z"
ADJACENT_SPLIT = "2026-08-20T00:00:00Z"
ADJACENT_ENDS = "2026-08-30T00:00:00Z"
MARKETING_PLAN = "BRAND_MARKETING_PLAN"

SKU_AUDIO = "SKU-AUDIO-1"


# --------------------------------------------------------------------------- #
# Shared setup
# --------------------------------------------------------------------------- #
def _setup_catalogue(sku=SKU_AUDIO, name="Studio Headphones", policy_overrides=None, **product):
    """Publish one policy effective at the pinned clock and register one product."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, **(policy_overrides or {}))
    fields = {
        "sku": sku,
        "name": name,
        "msrp_cents": MSRP,
        "standard_map_floor_cents": STANDARD_FLOOR,
    }
    fields.update(product)
    return policy, create_product(policy["id"], **fields)


def _setup_matched_marketplace_channel():
    """A published policy, a product and one AUTHORIZED marketplace reseller."""
    policy, product = _setup_catalogue()
    reseller, _agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={
            "legal_name": "Acme Retail LLC",
            "contact_email": "ops@acme.example",
            "primary_channel": "MARKETPLACE",
        },
        agreement_overrides={"permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"]},
    )
    return policy, product, reseller


def _capture_bundle(product_id, total_cents, components, listing_url):
    """Capture a bundle listing whose component array carries the observed sku."""
    pin_clock(CLOCK_AUG_20)
    return capture_observation(
        product_id,
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url=listing_url,
        listed_price_cents=total_cents,
        observed_at=OBSERVED_AUG_18,
        is_bundle=True,
        bundle_total_price_cents=total_cents,
        bundle_components=components,
    )


# --------------------------------------------------------------------------- #
# Bundle component allocation
# --------------------------------------------------------------------------- #
THREE_COMPONENTS = [
    {"sku": SKU_AUDIO, "msrp_cents": 20000},
    {"sku": "SKU-CABLE-1", "msrp_cents": 5000},
    {"sku": "SKU-CASE-1", "msrp_cents": 3000},
]


def test_a_three_component_bundle_hands_the_residual_to_the_last_member():
    """Each non-last share rounds first; the last member absorbs the drift.

    PRD: "Walk that ordering, and for every component except the last, set its
    share to the advertised bundle price multiplied by that component's
    `msrp_cents`, divided by the total component MSRP, rounded half up to a whole
    number of cents; keep a running total of the shares assigned so far. The last
    component in the ordering receives the residual: the advertised bundle price
    minus the running total of every earlier share. Because the residual absorbs
    all the rounding drift, the component shares add up to
    `bundle_total_price_cents` exactly."

    Design: Corner/calculations/bundle_allocation_three_components_residual_to_last_member
    """
    _policy, product = _setup_catalogue()
    observation = _capture_bundle(
        product["id"], 10000, THREE_COMPONENTS, "https://mkt.example/b/3"
    )
    evaluation = evaluate_observation(observation["id"])

    shares = allocate_bundle(10000, THREE_COMPONENTS)
    assert shares[SKU_AUDIO] == 7143
    assert shares["SKU-CABLE-1"] == 1786
    assert shares["SKU-CASE-1"] == 1071
    assert sum(shares.values()) == 10000

    assert evaluation["allocated_component_price_cents"] == shares[SKU_AUDIO] == 7143
    assert evaluation["effective_advertised_price_cents"] == effective_advertised_price(7143) == 7143
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 7143) == 7857
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 7857) == 0.5238
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 7143, "MARKETPLACE", 0)
        == 9
    )
    assert read_observation(observation["id"])["effective_map_floor_cents"] == STANDARD_FLOOR


TIE_COMPONENTS = [
    {"sku": SKU_AUDIO, "msrp_cents": 20000},
    {"sku": "SKU-BASS-1", "msrp_cents": 20000},
]


def test_equal_msrps_break_the_ordering_tie_on_sku_ascending():
    """With identical MSRPs the alphabetically later sku is the residual member.

    PRD: "Order the components by `msrp_cents` descending, breaking ties by `sku`
    ascending — never by any row identifier."

    Design: Corner/calculations/bundle_allocation_residual_recipient_is_the_sku_ascending_tie_break
    """
    _policy, product = _setup_catalogue()
    observation = _capture_bundle(
        product["id"], 10001, TIE_COMPONENTS, "https://mkt.example/b/tie"
    )
    evaluation = evaluate_observation(observation["id"])

    shares = allocate_bundle(10001, TIE_COMPONENTS)
    # 10001 * 20000 / 40000 is exactly 5000.5, which rounds half up to 5001.
    assert shares[SKU_AUDIO] == round_half_up(5000.5) == 5001
    assert shares["SKU-BASS-1"] == 5000

    assert evaluation["allocated_component_price_cents"] == shares[SKU_AUDIO] == 5001
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 5001) == 9999
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 9999) == 0.6666
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 5001, "MARKETPLACE", 0)
        == 9
    )


TWO_COMPONENTS = [
    {"sku": SKU_AUDIO, "msrp_cents": 20000},
    {"sku": "SKU-CABLE-1", "msrp_cents": 5000},
]


def test_the_observed_share_is_read_off_the_matching_component_sku():
    """An exact 18000 split leaves the observed component 600 cents short.

    PRD: "The observation's `allocated_component_price_cents` is the share
    belonging to the component whose `sku` matches the observed product's `sku`."

    Design: Corner/calculations/bundle_allocation_observed_sku_can_be_the_residual_recipient
    """
    _policy, product = _setup_catalogue()
    observation = _capture_bundle(
        product["id"], 18000, TWO_COMPONENTS, "https://mkt.example/b/2"
    )
    evaluation = evaluate_observation(observation["id"])

    shares = allocate_bundle(18000, TWO_COMPONENTS)
    assert shares[SKU_AUDIO] == 14400
    assert shares["SKU-CABLE-1"] == 3600

    assert evaluation["allocated_component_price_cents"] == shares[SKU_AUDIO] == 14400
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 14400) == 600
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 600) == 0.0400
    # base tier 1 times the marketplace weight 1.5 is 1.5, which rounds up to 2.
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 14400, "MARKETPLACE", 0)
        == 2
    )


# --------------------------------------------------------------------------- #
# The effective advertised price
# --------------------------------------------------------------------------- #
def test_only_the_auto_coupon_qualifies_under_the_default_policy_switches():
    """Shipping and the promo code stay out of the qualifying set entirely.

    PRD: "Next, assemble the set of qualifying discounts: the `auto_coupon_cents`
    amount qualifies when the policy has `auto_coupon_counts_as_advertised` set to
    true, and the `promo_code_cents` amount qualifies when the policy has
    `promo_code_counts_as_advertised` set to true."

    Design: Corner/calculations/advertised_price_deducts_the_auto_coupon_only
    """
    _policy, product, reseller = _setup_matched_marketplace_channel()
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/c",
        listed_price_cents=15000,
        observed_at=OBSERVED_AUG_18,
        shipping_cents=900,
        auto_coupon_cents=2000,
        promo_code_cents=4000,
        matched_reseller_id=reseller["id"],
    )
    evaluation = evaluate_observation(observation["id"])

    expected = effective_advertised_price(
        15000, shipping_cents=900, auto_coupon_cents=2000, promo_code_cents=4000
    )
    assert evaluation["effective_advertised_price_cents"] == expected == 13000
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 13000) == 2000
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 2000) == 0.1333
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 13000, "MARKETPLACE", 0)
        == 3
    )


def test_shipping_joins_the_gross_price_when_the_policy_switch_is_on():
    """A policy that counts shipping lifts the same listing back to compliant.

    PRD: "Add the `shipping_cents` to the base when the governing policy has
    `shipping_counts_as_advertised` set to true, and add nothing otherwise; call
    the result the gross price."

    Design: Corner/calculations/advertised_price_ignores_shipping_when_the_policy_says_so
    """
    policy, product = _setup_catalogue(
        sku="SKU-SHIP-1",
        name="Portable Speaker",
        policy_overrides={"shipping_counts_as_advertised": True},
    )
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/s",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        shipping_cents=2000,
    )
    evaluation = evaluate_observation(observation["id"])

    expected = effective_advertised_price(14000, shipping_cents=2000, shipping_counts=True)
    assert evaluation["evaluation_status"] == "EVALUATED_COMPLIANT"
    assert evaluation["effective_advertised_price_cents"] == expected == 16000
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 16000) == 0
    assert evaluation["cited_policy_id"] == policy["id"]


def test_two_qualifying_discounts_contribute_only_the_larger_one():
    """The candidate is the maximum of the qualifying amounts, never their sum.

    PRD: "Only the **single largest** qualifying amount is a candidate for
    attribution; qualifying discounts are never added together, so a listing with
    a qualifying auto-coupon of 500 cents and a qualifying promo code of 800 cents
    offers a candidate of 800 cents, not 1300."

    Design: Corner/calculations/advertised_price_takes_the_largest_discount_never_the_sum
    """
    _policy, product = _setup_catalogue(
        sku="SKU-PROMO-1",
        name="Wireless Earbuds",
        policy_overrides={"promo_code_counts_as_advertised": True},
    )
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/p",
        listed_price_cents=15000,
        observed_at=OBSERVED_AUG_18,
        auto_coupon_cents=2000,
        promo_code_cents=3000,
    )
    evaluation = evaluate_observation(observation["id"])

    expected = effective_advertised_price(
        15000, auto_coupon_cents=2000, promo_code_cents=3000, promo_code_counts=True
    )
    assert evaluation["effective_advertised_price_cents"] == expected == 12000
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 12000) == 3000
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 3000) == 0.2000
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 12000, "MARKETPLACE", 0)
        == 6
    )


def test_the_attribution_cap_truncates_and_trims_an_oversized_coupon():
    """Forty percent of a 10000 gross is 4000, so 1000 of the coupon is ignored.

    PRD: "Separately, compute the attribution cap as the gross price multiplied by
    the policy's `max_discount_attribution_pct`, truncated downward to a whole
    number of cents. The `effective_advertised_price_cents` is the gross price
    minus the smaller of the discount candidate and the attribution cap."

    Design: Corner/calculations/advertised_price_caps_the_discount_at_forty_percent_of_gross
    """
    _policy, product = _setup_catalogue()
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/cap",
        listed_price_cents=10000,
        observed_at=OBSERVED_AUG_18,
        auto_coupon_cents=5000,
    )
    evaluation = evaluate_observation(observation["id"])

    assert floor_to_int(10000 * 0.40) == 4000
    expected = effective_advertised_price(10000, auto_coupon_cents=5000)
    assert evaluation["effective_advertised_price_cents"] == expected == 6000
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 6000) == 9000
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 9000) == 0.6000
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 6000, "MARKETPLACE", 0)
        == 9
    )


# --------------------------------------------------------------------------- #
# Governing policy selection
# --------------------------------------------------------------------------- #
def test_an_older_listing_is_judged_by_the_policy_that_has_since_been_superseded():
    """The candidate pool keeps SUPERSEDED rows, so the older definition wins.

    PRD: "Note that superseded and withdrawn policies remain candidates: a listing
    observed last month is judged by the definition that was in force last month,
    even if that document has since been replaced."

    Design: Corner/calculations/policy_selection_picks_a_superseded_policy_for_an_older_observation
    """
    first, product = _setup_catalogue()
    second = create_published_policy("2026-08-15T00:00:00Z")

    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/old",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_10,
    )
    evaluation = evaluate_observation(observation["id"])

    assert evaluation["cited_policy_id"] == first["id"]
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 14000) == 1000
    assert read_policy(first["id"])["status"] == "SUPERSEDED"
    assert read_policy(second["id"])["status"] == "PUBLISHED"


def test_a_listing_seen_before_the_only_policy_took_effect_has_no_governing_policy():
    """An effective_from later than observed_at empties the candidate pool.

    PRD: "If no policy qualifies, the caller is rejected with
    `ERR_NO_GOVERNING_POLICY`."

    Design: Corner/calculations/policy_selection_with_no_candidate_in_force_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy("2026-08-15T00:00:00Z")
    product = create_product(
        policy["id"],
        sku="SKU-LATE-1",
        name="Bookshelf Monitor",
        msrp_cents=MSRP,
        standard_map_floor_cents=STANDARD_FLOOR,
    )
    pin_clock(CLOCK_AUG_16)
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/np",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_14,
    )

    validate_error(
        api_client.evaluate_observation(observation["id"], ANALYST_HEADERS),
        "ERR_NO_GOVERNING_POLICY",
    )
    assert read_observation(observation["id"])["evaluation_status"] == "CAPTURED"


# --------------------------------------------------------------------------- #
# The override floor installed at approval
# --------------------------------------------------------------------------- #
def _request_clearance_exception(product_id, **overrides):
    """A REQUESTED CLEARANCE exception over the mid-August window."""
    payload = clearance_exception_payload(
        product_id,
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        dealer_input_source=MARKETING_PLAN,
        **overrides,
    )
    return get_success_data(api_client.create_exception(payload, BCM_HEADERS))


def test_the_clearance_branch_discards_the_requested_figure():
    """A clearance floor comes from the product discount, not from the request.

    PRD: "For a `CLEARANCE` exception the requested figure is ignored entirely:
    the installed floor is the product's `standard_map_floor_cents` multiplied by
    one minus the product's `clearance_discount_pct`, rounded half up to whole
    cents."

    Design: Corner/calculations/override_floor_clearance_variant_ignores_the_requested_amount
    """
    _policy, product = _setup_catalogue(
        sku="SKU-CLR-1",
        name="Legacy Turntable",
        lifecycle_status="CLEARANCE",
        clearance_discount_pct=0.20,
    )
    requested = _request_clearance_exception(
        product["id"], requested_override_floor_cents=9000
    )
    decided = approve_exception(
        requested["id"], decision_reason="End-of-life clearance authorized"
    )

    assert decided["status"] == "APPROVED"
    assert (
        decided["override_floor_cents"]
        == clearance_override_floor(STANDARD_FLOOR, 0.20)
        == 12000
    )
    assert read_product(product["id"])["open_exception_count"] == 1


def test_the_clearance_floor_rounds_a_fractional_cent_half_up():
    """14999 times 0.85 is 12749.15, which rounds up rather than truncating.

    PRD: "For a `CLEARANCE` exception the requested figure is ignored entirely:
    the installed floor is the product's `standard_map_floor_cents` multiplied by
    one minus the product's `clearance_discount_pct`, rounded half up to whole
    cents."

    Design: Corner/calculations/override_floor_clearance_rounds_half_up_to_whole_cents
    """
    _policy, product = _setup_catalogue(
        sku="SKU-CLR-2",
        name="Legacy Amplifier",
        msrp_cents=19999,
        standard_map_floor_cents=14999,
        lifecycle_status="CLEARANCE",
        clearance_discount_pct=0.15,
    )
    requested = _request_clearance_exception(product["id"])
    decided = approve_exception(requested["id"], decision_reason="Clearance pricing approved")

    assert round_half_up(12749.15) == 12749
    assert decided["override_floor_cents"] == clearance_override_floor(14999, 0.15) == 12749


def test_the_lowest_legal_override_floor_is_accepted_at_the_bound():
    """Half of the standard floor, truncated down, is inside the band.

    PRD: "For a `BUNDLE` or `PROMOTIONAL_EVENT` exception the installed floor is
    exactly the `requested_override_floor_cents` supplied on the request, but it
    must sit inside a permitted band: it must be strictly less than the product's
    `standard_map_floor_cents` — an "exception" that raises the floor is not an
    exception — and it must be at least the product's `standard_map_floor_cents`
    multiplied by 0.50 and truncated downward to whole cents, so no exception may
    cut the floor by more than half."

    Design: Corner/calculations/override_floor_accepts_exactly_the_min_floor_ratio_bound
    """
    _policy, product = _setup_catalogue()
    assert override_floor_lower_bound(STANDARD_FLOOR) == 7500

    requested = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=7500,
        dealer_input_source=MARKETING_PLAN,
    )
    decided = approve_exception(
        requested["id"], decision_reason="Deep promotional floor authorized"
    )

    assert decided["status"] == "APPROVED"
    assert decided["override_floor_cents"] == override_floor_lower_bound(STANDARD_FLOOR) == 7500
    assert read_product(product["id"])["open_exception_count"] == 1


def test_one_cent_below_the_band_is_refused_and_installs_nothing():
    """7499 is outside the band, so the exception stays REQUESTED.

    PRD: "A figure outside that band is rejected with
    `ERR_OVERRIDE_FLOOR_OUT_OF_RANGE`."

    Design: Corner/calculations/override_floor_one_cent_below_the_min_ratio_rejected
    """
    _policy, product = _setup_catalogue()
    assert override_floor_lower_bound(STANDARD_FLOOR) == 7500

    requested = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=7499,
        dealer_input_source=MARKETING_PLAN,
    )
    validate_error(
        api_client.decide_exception(
            requested["id"],
            exception_decision_payload("APPROVE", decision_reason="Attempted deep discount"),
            COUNSEL_HEADERS,
        ),
        "ERR_OVERRIDE_FLOOR_OUT_OF_RANGE",
    )

    stored = read_exception(requested["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["override_floor_cents"] is None
    assert read_product(product["id"])["open_exception_count"] == 0


# --------------------------------------------------------------------------- #
# The computed floor read
# --------------------------------------------------------------------------- #
def _approved_all_scope_exception(product_id, floor_cents=13000, exception_type="PROMOTIONAL_EVENT"):
    """An APPROVED exception over [2026-08-10, 2026-08-25) covering every channel."""
    requested = request_exception(
        product_id,
        exception_type=exception_type,
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=floor_cents,
        dealer_input_source=MARKETING_PLAN,
    )
    return approve_exception(
        requested["id"], decision_reason="Back-to-school campaign authorized retroactively"
    )


def _request_physical_retail_leg(product_id, starts_at, ends_at, floor_cents):
    """One leg of a back-to-back physical-retail promotion."""
    return request_exception(
        product_id,
        exception_type="PROMOTIONAL_EVENT",
        starts_at=starts_at,
        ends_at=ends_at,
        channel_scope="PHYSICAL_RETAIL",
        requested_override_floor_cents=floor_cents,
        dealer_input_source=MARKETING_PLAN,
    )


def test_an_approved_exception_supplies_the_floor_and_names_itself_as_the_source():
    """The read reports EXCEPTION, the applied id and the untouched standard floor.

    PRD: "The first candidate in that ordering supplies the floor from its
    `override_floor_cents`, the floor source is `EXCEPTION`, and its identifier is
    what the computed floor read reports as `applied_exception_id`."

    Design: Corner/calculations/effective_floor_reads_the_approved_exception_as_the_source
    """
    _policy, product = _setup_catalogue()
    exception = _approved_all_scope_exception(product["id"])

    read = read_effective_floor(product["id"], channel="MARKETPLACE", as_of=OBSERVED_AUG_18)
    assert read["effective_map_floor_cents"] == 13000
    assert read["floor_source"] == "EXCEPTION"
    assert read["applied_exception_id"] == exception["id"]
    assert read["standard_map_floor_cents"] == STANDARD_FLOOR


def test_the_instant_a_window_ends_belongs_to_the_next_window():
    """Adjacent legs never overlap and the shared endpoint selects the later one.

    PRD: "Consider every exception on that product whose status is `APPROVED`,
    whose window contains the instant under half-open semantics — `starts_at` at or
    before the instant and the instant strictly before `ends_at` — whose
    `channel_scope` is either `ALL` or exactly the channel in question, and which
    is either not a `BUNDLE` exception or else is being applied to a listing where
    `is_bundle` is true, since bundle exceptions only cover bundle listings."

    Design: Corner/calculations/effective_floor_treats_adjacent_windows_as_half_open
    """
    _policy, product = _setup_catalogue()
    first_leg = _request_physical_retail_leg(
        product["id"], WINDOW_STARTS, ADJACENT_SPLIT, 13000
    )
    approve_exception(first_leg["id"], decision_reason="First promo leg")
    second_leg = _request_physical_retail_leg(
        product["id"], ADJACENT_SPLIT, ADJACENT_ENDS, 14000
    )
    approve_exception(second_leg["id"], decision_reason="Second promo leg")

    read = read_effective_floor(
        product["id"], channel="PHYSICAL_RETAIL", as_of=ADJACENT_SPLIT
    )
    assert read["effective_map_floor_cents"] == 14000
    assert read["applied_exception_id"] == second_leg["id"]
    assert read["floor_source"] == "EXCEPTION"

    assert read_exception(first_leg["id"])["status"] == "APPROVED"
    assert read_exception(second_leg["id"])["status"] == "APPROVED"
    assert read_product(product["id"])["open_exception_count"] == 2


def test_a_still_requested_exception_never_reaches_the_floor_read():
    """Eligibility demands APPROVED, so an unapproved window changes nothing.

    PRD: "If nothing qualifies, the floor is the product's
    `standard_map_floor_cents` and the floor source is `STANDARD`."

    Design: Corner/calculations/effective_floor_excludes_a_requested_exception
    """
    _policy, product = _setup_catalogue()
    requested = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=13000,
        dealer_input_source=MARKETING_PLAN,
    )

    read = read_effective_floor(product["id"], channel="MARKETPLACE", as_of=OBSERVED_AUG_18)
    assert read["effective_map_floor_cents"] == STANDARD_FLOOR
    assert read["floor_source"] == "STANDARD"
    assert read["applied_exception_id"] is None
    assert read_exception(requested["id"])["status"] == "REQUESTED"


def test_a_channel_scoped_exception_stays_on_its_own_channel():
    """The same instant answers 13000 on one channel and the standard floor on another.

    PRD: "Consider every exception on that product whose status is `APPROVED`,
    whose window contains the instant under half-open semantics — `starts_at` at or
    before the instant and the instant strictly before `ends_at` — whose
    `channel_scope` is either `ALL` or exactly the channel in question, and which
    is either not a `BUNDLE` exception or else is being applied to a listing where
    `is_bundle` is true, since bundle exceptions only cover bundle listings."

    Design: Corner/calculations/effective_floor_excludes_a_channel_scoped_exception_on_another_channel
    """
    _policy, product = _setup_catalogue()
    leg = _request_physical_retail_leg(product["id"], WINDOW_STARTS, ADJACENT_SPLIT, 13000)
    approve_exception(leg["id"], decision_reason="Physical retail promo")

    physical = read_effective_floor(
        product["id"], channel="PHYSICAL_RETAIL", as_of=OBSERVED_AUG_18
    )
    assert physical["effective_map_floor_cents"] == 13000

    marketplace = read_effective_floor(
        product["id"], channel="MARKETPLACE", as_of=OBSERVED_AUG_18
    )
    assert marketplace["effective_map_floor_cents"] == STANDARD_FLOOR
    assert marketplace["floor_source"] == "STANDARD"
    assert marketplace["applied_exception_id"] is None


def test_a_bundle_exception_is_gated_on_the_bundle_flag():
    """The same product, channel and instant answer differently per is_bundle.

    PRD: "Consider every exception on that product whose status is `APPROVED`,
    whose window contains the instant under half-open semantics — `starts_at` at or
    before the instant and the instant strictly before `ends_at` — whose
    `channel_scope` is either `ALL` or exactly the channel in question, and which
    is either not a `BUNDLE` exception or else is being applied to a listing where
    `is_bundle` is true, since bundle exceptions only cover bundle listings."

    Design: Corner/calculations/effective_floor_bundle_exception_applies_only_to_bundle_listings
    """
    _policy, product = _setup_catalogue()
    exception = _approved_all_scope_exception(
        product["id"], floor_cents=13000, exception_type="BUNDLE"
    )

    solo = read_effective_floor(
        product["id"], channel="MARKETPLACE", as_of=OBSERVED_AUG_18, is_bundle=False
    )
    assert solo["effective_map_floor_cents"] == STANDARD_FLOOR
    assert solo["floor_source"] == "STANDARD"

    bundled = read_effective_floor(
        product["id"], channel="MARKETPLACE", as_of=OBSERVED_AUG_18, is_bundle=True
    )
    assert bundled["effective_map_floor_cents"] == 13000
    assert bundled["floor_source"] == "EXCEPTION"
    assert bundled["applied_exception_id"] == exception["id"]


def test_an_instant_exactly_at_the_end_of_the_window_falls_back_to_standard():
    """The exception is still APPROVED but no longer covers the instant.

    PRD: "If nothing qualifies, the floor is the product's
    `standard_map_floor_cents` and the floor source is `STANDARD`."

    Design: Corner/calculations/effective_floor_outside_the_window_falls_back_to_standard
    """
    _policy, product = _setup_catalogue()
    exception = _approved_all_scope_exception(product["id"])

    read = read_effective_floor(product["id"], channel="MARKETPLACE", as_of=WINDOW_ENDS)
    assert read["effective_map_floor_cents"] == STANDARD_FLOOR
    assert read["floor_source"] == "STANDARD"
    assert read["applied_exception_id"] is None
    assert read_exception(exception["id"])["status"] == "APPROVED"
