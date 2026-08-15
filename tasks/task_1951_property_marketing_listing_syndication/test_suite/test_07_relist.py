"""Relisting: fee computation (tier/volume/discount), quote-vs-execute parity,
safety-before-cooldown precedence, and the 30-day cooldown boundary (PRD §3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_relist_request,
    create_relist_payload,
    owner_headers, create_withdrawn_listing, submit_listing, approve_review,
    get_listing, set_clock,
    TEST_USERS,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]


def _quote(api, listing_id, new_list_price_cents=None):
    params = {}
    if new_list_price_cents is not None:
        params["new_list_price_cents"] = new_list_price_cents
    return get_success_data(api.get_relist_quote(listing_id, MC, params=params or None), 200)


class TestRelistFeeTierDiscountInteraction:
    def test_quote_combines_tier_discount_and_volume(self, api):
        """PRD §3.9: "The base fee is 20000 cents. The tier multiplier is 1.0 when
        `relist_count_before` is zero, 1.5 when it is one, and 2.0 when it is two or
        more."
        PRD §3.9: "The discount fraction is 0.25 when the `price_reduction_pct` is at
        least 5.0 and 0.0 otherwise, where `price_reduction_pct` is one hundred times
        the difference between `terminal_price_cents` and the effective price,
        divided by `terminal_price_cents`, rounded half up to two decimal places"
        PRD §3.9: "A relist quote capability reports the same computation without
        performing it"

        Design: Difficulty/combinatorial_formula/relist_fee_tier_discount_volume_interaction
        """
        agent, withdrawn = create_withdrawn_listing()  # terminal price 50000000
        set_clock("2026-09-02T00:00:00Z")  # 32 days past terminal entry

        quote = _quote(api, withdrawn["id"], new_list_price_cents=47000000)
        assert quote["eligible"] is True
        assert quote["relist_count_before"] == 0
        assert quote["price_reduction_pct"] == pytest.approx(6.0, abs=1e-9)
        # 20000 * 1.0 (tier) * 1.0 (volume) * (1 - 0.25) = 15000
        assert quote["fee_cents"] == 15000

    def test_relist_executes_with_quoted_fee_and_updates_listing(self, api):
        """PRD §3.9: "A successful relist creates a RelistRequest record and applies
        a bundle of effects. The record captures `relist_count_before` — the
        listing's `relist_count` before this relist — the computed
        `price_reduction_pct`, the `new_list_price_cents` actually applied (the
        payload value when supplied, otherwise the current price), and the computed
        `fee_cents`. The listing's `relist_count` increments by one; when a
        `new_list_price_cents` was supplied, `list_price_cents` updates to it and a
        `PRICE_CHANGE` event is appended"

        Design: Difficulty/combinatorial_formula/relist_fee_tier_discount_volume_interaction
        """
        agent, withdrawn = create_withdrawn_listing()
        set_clock("2026-09-02T00:00:00Z")

        relist = validate_success(api.relist_listing(
            withdrawn["id"], create_relist_payload(new_list_price_cents=47000000),
            owner_headers(agent)), 201)
        assert_relist_request(relist)
        assert relist["fee_cents"] == 15000
        assert relist["relist_count_before"] == 0
        assert relist["new_list_price_cents"] == 47000000
        assert relist["price_reduction_pct"] == pytest.approx(6.0, abs=1e-9)

        listing = get_listing(withdrawn["id"])
        assert listing["lifecycle_status"] == "DRAFT"
        assert listing["relist_count"] == 1
        assert listing["list_price_cents"] == 47000000

        events = get_success_data(
            api.list_listing_events(withdrawn["id"], MC, params={"event_type": "PRICE_CHANGE"}), 200)
        assert len(events) == 1 and events[0]["new_price_cents"] == 47000000


class TestRelistSafetyBeatsCooldown:
    def test_fair_housing_violation_fires_before_cooldown(self, api):
        """PRD §2.10: "Because the scan sits ahead of the endpoint-specific business
        checks in the global validation order, a relist whose remarks violate the
        policy fails with `ERR_FAIR_HOUSING_VIOLATION` even if the relist would also
        have failed the cooldown check."
        PRD §3.9: "Two preconditions guard the relist, and the safety check runs
        first: the fair-housing scan screens `new_marketing_remarks` when one is
        supplied in the request, or the stored `marketing_remarks` otherwise,
        failing with `ERR_FAIR_HOUSING_VIOLATION`"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_relist
        """
        agent, withdrawn = create_withdrawn_listing()
        set_clock("2026-08-11T00:00:00Z")  # only 10 days into the 30-day cooldown

        res = api.relist_listing(
            withdrawn["id"],
            create_relist_payload(new_marketing_remarks="Adults only community"),
            owner_headers(agent))
        validate_error(res, ApiErrorId.ERR_FAIR_HOUSING_VIOLATION, expected_status=422)

        listing = get_listing(withdrawn["id"])
        assert listing["lifecycle_status"] == "WITHDRAWN"
        assert listing["relist_count"] == 0

    def test_rejected_relist_creates_no_relist_request(self, api):
        """PRD §3.9: "A successful relist creates a RelistRequest record and applies
        a bundle of effects."
        PRD §3.9: "The full history of a listing's relist requests remains listable."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_relist
        """
        agent, withdrawn = create_withdrawn_listing()
        set_clock("2026-08-11T00:00:00Z")

        res = api.relist_listing(
            withdrawn["id"],
            create_relist_payload(new_marketing_remarks="Adults only community"),
            owner_headers(agent))
        validate_error(res, ApiErrorId.ERR_FAIR_HOUSING_VIOLATION, expected_status=422)

        history = get_success_data(api.list_relist_requests(withdrawn["id"], MC), 200)
        assert history == [], "a rejected relist creates no RelistRequest"


def test_relist_fee_exact_discount_threshold_boundary(api):
    """PRD §3.9: "The discount fraction is 0.25 when the `price_reduction_pct` is at
    least 5.0 and 0.0 otherwise, where `price_reduction_pct` is one hundred times the
    difference between `terminal_price_cents` and the effective price, divided by
    `terminal_price_cents`, rounded half up to two decimal places"
    PRD §3.9: "A relist quote capability reports the same computation without
    performing it"

    Design: Corner/calculations/relist_fee_exact_discount_threshold_boundary
    """
    agent, withdrawn = create_withdrawn_listing()  # terminal price 50000000
    set_clock("2026-09-02T00:00:00Z")

    at_threshold = _quote(api, withdrawn["id"], new_list_price_cents=47500000)
    assert at_threshold["price_reduction_pct"] == pytest.approx(5.0, abs=1e-9)
    assert at_threshold["fee_cents"] == 15000, "5.00 percent reduction earns the 0.25 discount"

    below_threshold = _quote(api, withdrawn["id"], new_list_price_cents=47600000)
    assert below_threshold["price_reduction_pct"] == pytest.approx(4.8, abs=1e-9)
    assert below_threshold["fee_cents"] == 20000, "4.80 percent reduction earns no discount"


def test_relist_fee_second_relist_tier_multiplier(api):
    """PRD §3.9: "The tier multiplier is 1.0 when `relist_count_before` is zero, 1.5
    when it is one, and 2.0 when it is two or more."
    PRD §3.9: "with a relist attempted exactly thirty days after terminal entry
    permitted"

    Design: Corner/calculations/relist_fee_second_relist_tier_multiplier
    """
    agent, withdrawn = create_withdrawn_listing()  # terminal entry 2026-08-01T00:00:00Z
    set_clock("2026-08-31T00:00:00Z")  # exactly 30 days: relist permitted

    validate_success(api.relist_listing(
        withdrawn["id"], create_relist_payload(new_list_price_cents=47000000),
        owner_headers(agent)), 201)
    # Drive the listing back to WITHDRAWN a second time.
    review2 = submit_listing(get_listing(withdrawn["id"]), agent)
    approve_review(review2)
    validate_success(api.activate_listing(withdrawn["id"], owner_headers(agent)), 200)
    validate_success(api.withdraw_listing(withdrawn["id"], owner_headers(agent)), 200)

    set_clock("2026-09-30T00:00:00Z")  # exactly 30 days after the second terminal entry
    quote = _quote(api, withdrawn["id"])
    assert quote["relist_count_before"] == 1
    # Effective price 47000000 == terminal_price_cents -> reduction 0 -> no discount.
    # fee = 20000 * 1.5 (tier) * 1.0 (volume) * (1 - 0.0) = 30000
    assert quote["fee_cents"] == 30000


def test_relist_before_cooldown_returns_cooldown_active(api):
    """PRD §3.9: "then the cooldown — at least thirty full days must have elapsed
    since `terminal_entered_at`, with a relist attempted exactly thirty days after
    terminal entry permitted, and an earlier attempt rejected with
    `ERR_RELIST_COOLDOWN_ACTIVE`."

    Design: Corner/validations/relist_before_cooldown_returns_cooldown_active
    """
    agent, withdrawn = create_withdrawn_listing()  # terminal entry 2026-08-01T00:00:00Z
    set_clock("2026-08-30T00:00:00Z")  # 29 days in

    res = api.relist_listing(withdrawn["id"], create_relist_payload(), owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_RELIST_COOLDOWN_ACTIVE, expected_status=422)

    assert get_listing(withdrawn["id"])["lifecycle_status"] == "WITHDRAWN"
    history = get_success_data(api.list_relist_requests(withdrawn["id"], MC), 200)
    assert history == []
