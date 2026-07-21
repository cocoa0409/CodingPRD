"""CIM valuation, activation gating on a published CIM, and per-seller exclusivity windows."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_broker_headers,
    create_cim_payload,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Design: Difficulty/dual_variant_calc/valuation_sde_multiple_vs_asset_based
# ---------------------------------------------------------------------------
class TestCIMValuationVariants:
    """Same listing inputs, two valuation methods yield divergent recommended prices."""

    def _listing_with_two_cims(self, api):
        broker = fx.onboard_broker(api)
        seller = fx.onboard_seller(api)
        listing = fx.create_listing(
            api, broker["id"], seller["id"],
            annual_sde_cents=40_000_000, industry_multiple=3.0,
            ffe_value_cents=20_000_000, inventory_value_cents=10_000_000,
        )
        hdr = make_broker_headers(broker["id"])
        cim_sde = validate_success(api.create_cim(listing["id"], create_cim_payload("SDE_MULTIPLE"), hdr), 201)
        cim_asset = validate_success(api.create_cim(listing["id"], create_cim_payload("ASSET_BASED"), hdr), 201)
        return hdr, cim_sde, cim_asset

    def test_sde_multiple_recommended_price(self, api):
        """PRD §3.2: "Under `SDE_MULTIPLE`, the recommended price is the listing's `annual_sde_cents`
        multiplied by its `industry_multiple`, rounded half up to whole cents — an
        earnings-capitalization value."

        Design: Difficulty/dual_variant_calc/valuation_sde_multiple_vs_asset_based
        """
        hdr, cim_sde, _cim_asset = self._listing_with_two_cims(api)
        data = validate_success(api.publish_cim(cim_sde["id"], hdr))
        assert data["status"] == "PUBLISHED"
        assert data["recommended_price_cents"] == 120_000_000

    def test_asset_based_recommended_price_diverges(self, api):
        """PRD §3.2: "Under `ASSET_BASED`, the recommended price is the sum of the listing's
        `ffe_value_cents` and `inventory_value_cents` — the tangible net asset value, with
        goodwill excluded — and for identical listing inputs this deliberately diverges from
        the `SDE_MULTIPLE` figure."

        Design: Difficulty/dual_variant_calc/valuation_sde_multiple_vs_asset_based
        """
        hdr, cim_sde, cim_asset = self._listing_with_two_cims(api)
        sde = validate_success(api.publish_cim(cim_sde["id"], hdr))
        asset = validate_success(api.publish_cim(cim_asset["id"], hdr))
        assert asset["recommended_price_cents"] == 30_000_000
        assert asset["recommended_price_cents"] != sde["recommended_price_cents"]


# ---------------------------------------------------------------------------
# Design: Difficulty/cross_entity_state_dependency/listing_activate_requires_published_cim
# ---------------------------------------------------------------------------
class TestActivationRequiresPublishedCIM:
    def _listing_with_draft_cim(self, api):
        broker = fx.onboard_broker(api)
        seller = fx.onboard_seller(api)
        listing = fx.create_listing(api, broker["id"], seller["id"])
        hdr = make_broker_headers(broker["id"])
        cim = validate_success(api.create_cim(listing["id"], create_cim_payload("SDE_MULTIPLE"), hdr), 201)
        return broker, listing, cim, hdr

    def test_activate_with_only_draft_cim_rejected(self, api):
        """PRD §3.2: "**Activation** by the listing's broker transitions the listing from `DRAFT`
        to `ACTIVE`, and it requires that the listing already have at least one CIM in
        `PUBLISHED` status; otherwise activation is rejected with `ERR_CIM_NOT_PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/listing_activate_requires_published_cim
        """
        _broker, listing, _cim, hdr = self._listing_with_draft_cim(api)
        resp = api.activate_listing(listing["id"], hdr)
        validate_error(resp, ApiErrorId.ERR_CIM_NOT_PUBLISHED.value)
        current = validate_success(api.get_listing(listing["id"], hdr))
        assert current["status"] == "DRAFT"

    def test_activate_succeeds_once_cim_published(self, api):
        """PRD §3.2: "**Activation** by the listing's broker transitions the listing from `DRAFT`
        to `ACTIVE`, and it requires that the listing already have at least one CIM in
        `PUBLISHED` status; otherwise activation is rejected with `ERR_CIM_NOT_PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/listing_activate_requires_published_cim
        """
        _broker, listing, cim, hdr = self._listing_with_draft_cim(api)
        validate_success(api.publish_cim(cim["id"], hdr))
        data = validate_success(api.activate_listing(listing["id"], hdr))
        assert data["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Design: Difficulty/resource_temporal_overlap/listing_exclusivity_halfopen_overlap
# ---------------------------------------------------------------------------
class TestListingExclusivityWindows:
    def _seller_with_first_window(self, api, start, end):
        broker = fx.onboard_broker(api)
        seller = fx.onboard_seller(api)
        hdr = make_broker_headers(broker["id"])
        first = fx.create_listing(
            api, broker["id"], seller["id"],
            business_name="Diner One", exclusive_start_date=start, exclusive_end_date=end,
        )
        return broker, seller, hdr, first

    def test_overlapping_window_same_seller_rejected(self, api):
        """PRD §3.2: "Exclusivity is enforced per seller: a new listing whose window overlaps that
        of another non-`WITHDRAWN` listing for the same seller is rejected with
        `ERR_LISTING_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/listing_exclusivity_halfopen_overlap
        """
        broker, seller, hdr, _first = self._seller_with_first_window(api, "2026-01-01", "2026-06-01")
        from test_helpers import create_listing_payload
        payload = create_listing_payload(
            seller["id"], business_name="Diner One Re-list",
            exclusive_start_date="2026-05-01", exclusive_end_date="2026-12-01",
        )
        resp = api.create_listing(payload, hdr)
        validate_error(resp, ApiErrorId.ERR_LISTING_PERIOD_OVERLAP.value)

    def test_touching_windows_same_seller_allowed(self, api):
        """PRD §3.2: "Because the interval is half-open, two windows that merely touch — where one
        ends exactly when the next begins — do not overlap and are both allowed."

        Design: Difficulty/resource_temporal_overlap/listing_exclusivity_halfopen_overlap
        """
        broker, seller, hdr, _first = self._seller_with_first_window(api, "2026-01-01", "2026-06-01")
        from test_helpers import create_listing_payload
        payload = create_listing_payload(
            seller["id"], business_name="Diner One Phase Two",
            exclusive_start_date="2026-06-01", exclusive_end_date="2026-12-01",
        )
        data = validate_success(api.create_listing(payload, hdr), expected_status=201)
        assert data["status"] == "DRAFT"


def test_publish_already_published_cim_rejected(api):
    """PRD §3.2: "Publishing is only permitted on a CIM in `DRAFT`; a publish attempt against a
    CIM that has already been published is rejected with `ERR_CIM_INVALID_STATE`."

    Design: Corner/state_machines/cim_publish_twice_returns_invalid_state
    """
    broker = fx.onboard_broker(api)
    seller = fx.onboard_seller(api)
    listing = fx.create_listing(api, broker["id"], seller["id"])
    hdr = make_broker_headers(broker["id"])
    cim = validate_success(api.create_cim(listing["id"], create_cim_payload("SDE_MULTIPLE"), hdr), 201)
    validate_success(api.publish_cim(cim["id"], hdr))
    resp = api.publish_cim(cim["id"], hdr)
    validate_error(resp, ApiErrorId.ERR_CIM_INVALID_STATE.value)
