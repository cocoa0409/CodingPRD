"""Art leases: buyout accrual against the clock and the convert-when-not-active
guard."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_active_lease, setup_gallery_artist_artwork,
    create_lease, create_sale, set_clock,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
SALES = TEST_USERS["sales_associate_headers"]


class TestLeaseBuyout:
    def test_buyout_credit_after_five_months(self, api):
        """PRD §3.8: "The `months_accrued` is the whole months elapsed since
        `starts_utc`, computed by taking the time since the start, dividing into
        30-day blocks and discarding the fraction, then capping the result at
        `term_months`. The `rent_accrued_cents` is `months_accrued` multiplied by
        `monthly_rate_cents`. The `buyout_price_cents` is the artwork's
        `list_price_cents` minus the credited rent, where the credited rent is
        `rent_accrued_cents` multiplied by `purchase_credit_bps` divided by 10000
        and rounded half up; the buyout is floored at zero and never goes negative."

        Design: Corner/state_machines/lease_buyout_credit_after_five_months
        """
        gallery, artist, artwork, lease = setup_active_lease(
            starts_utc="2026-04-01T00:00:00Z", list_price=1_000_000,
            monthly_rate=50_000, term_months=12, purchase_credit_bps=2000)
        # Clock 2026-09-01 is 153 days after start -> floor(153/30) = 5 months.
        set_clock("2026-09-01T00:00:00Z")
        live = get_success_data(api.get_lease(lease["id"], SALES))
        assert live["months_accrued"] == 5, "five whole 30-day blocks elapsed"
        assert live["rent_accrued_cents"] == 250000, "5 * 50000"
        # credit = round(250000 * 2000 / 10000) = 50000; buyout = 1000000 - 50000.
        assert live["buyout_price_cents"] == 950000, "list price minus credited rent"


class TestLeaseConvertGuard:
    def test_convert_after_return_rejected_invalid_state(self, api):
        """PRD §3.8: "A lease ends one of three ways while it is `ACTIVE`.
        Converting it — by a `SalesAssociate` or `GalleryAdmin` — moves it
        `ACTIVE → CONVERTED` and requires the leased artwork to be `ON_LOAN` under
        the lease".

        Design: Difficulty/cross_entity_state_dependency/lease_convert_blocked_when_artwork_not_on_loan
        """
        gallery, artist, artwork, lease = setup_active_lease(
            starts_utc="2026-04-01T00:00:00Z", list_price=500_000,
            monthly_rate=50_000, term_months=12, purchase_credit_bps=2000)
        # Return the lease: artwork CONSIGNED, lease RETURNED (no longer ACTIVE).
        returned = validate_success(api.return_lease(lease["id"], SALES))
        assert returned["status"] == "RETURNED"
        resp = api.convert_lease(lease["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        aw_after = get_success_data(api.get_artwork(artwork["id"], ADMIN))
        assert aw_after["status"] == "CONSIGNED"

    def test_convert_requires_active_lease(self, api):
        """PRD §3.8: "A lease ends one of three ways while it is `ACTIVE`.
        Converting it — by a `SalesAssociate` or `GalleryAdmin` — moves it
        `ACTIVE → CONVERTED` and requires the leased artwork to be `ON_LOAN` under
        the lease; a convert attempted when the artwork is not out under the lease
        is rejected with `ERR_LEASE_ARTWORK_NOT_OUT`."

        Design: Difficulty/cross_entity_state_dependency/lease_convert_blocked_when_artwork_not_on_loan
        """
        # Distinct setup reaching the same observable: lease no longer ACTIVE.
        gallery, artist, artwork, lease = setup_active_lease(
            starts_utc="2026-04-01T00:00:00Z", list_price=500_000,
            monthly_rate=50_000, term_months=12, purchase_credit_bps=2000)
        validate_success(api.terminate_lease(lease["id"], ADMIN))  # ACTIVE -> TERMINATED
        resp = api.convert_lease(lease["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_convert_on_returned_lease_with_artwork_resold_rejected(self, api):
        """PRD §3.8: "Converting it — by a `SalesAssociate` or `GalleryAdmin` —
        moves it `ACTIVE → CONVERTED` and requires the leased artwork to be
        `ON_LOAN` under the lease".

        Design: Corner/errors/lease_artwork_not_out_error
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 500_000, "insured_value_cents": 500_000})
        lease = create_lease(artwork["id"], starts_utc="2026-04-01T00:00:00Z",
                             monthly_rate_cents=50_000, term_months=12,
                             purchase_credit_bps=2000)
        # Return the lease (artwork CONSIGNED), then reserve it via a separate sale.
        validate_success(api.return_lease(lease["id"], SALES))
        create_sale(gallery["id"], artwork["id"], buyer_state_code="NY",
                    gross_amount_cents=500_000)
        # Lease is no longer ACTIVE; convert is rejected.
        resp = api.convert_lease(lease["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        aw_after = get_success_data(api.get_artwork(artwork["id"], ADMIN))
        assert aw_after["status"] == "RESERVED"
