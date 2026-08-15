"""Vintage gates, expiry sweep, and retention purge (PRD §2.9, §2.10)."""
from test_helpers import (
    ApiErrorId,
    CM,
    OPS,
    create_account,
    create_generated_lot,
    create_price_quote,
    create_rin_lot_payload,
    get_success_data,
    separate_lot,
    set_clock,
    validate_error,
    validate_success,
    api_client,
)


class TestRetentionPurgeCutoff:
    def _setup(self, api, epa_id):
        """PriceQuote created at default clock 2026-08-01; retention_until =
        2031-07-31T00:00:00Z (created_at + 1825 days)."""
        acct = create_account(epa_registration_id=epa_id)
        pq = create_price_quote(
            acct["id"], d_code="D6", vintage_year=2026, price_cents=150,
            effective_start="2026-08-01T00:00:00Z",
            effective_end="2026-08-31T23:59:59Z",
        )
        return acct, pq

    def test_purge_one_second_before_cutoff_fails(self, api):
        """PRD §2.9: "A record is purgeable when its `retention_until` is equal to or earlier than the current logical clock — a record exactly at its retention instant is purgeable, while one second before it is not."
        PRD §2.9: "If any record the purge targets is still within its retention window, the request fails entirely with `ERR_RETENTION_ACTIVE` and nothing is deleted"

        Design: Difficulty/boundary_precision_check/retention_purge_exact_cutoff_second
        """
        acct, _pq = self._setup(api, "EPA-ACME-12")
        set_clock("2031-07-30T23:59:59Z")
        resp = api.purge_records(acct["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_RETENTION_ACTIVE)

    def test_purge_at_exact_cutoff_succeeds_and_hard_deletes(self, api):
        """PRD §2.9: "otherwise the eligible records are hard-deleted and the response reports the counts as `purged_blending_records` and `purged_price_quotes`."

        Design: Difficulty/boundary_precision_check/retention_purge_exact_cutoff_second
        """
        acct, pq = self._setup(api, "EPA-ACME-12B")
        set_clock("2031-07-30T23:59:59Z")
        validate_error(api.purge_records(acct["id"], OPS),
                       ApiErrorId.ERR_RETENTION_ACTIVE)
        set_clock("2031-07-31T00:00:00Z")
        data = get_success_data(api.purge_records(acct["id"], OPS))
        assert data["purged_price_quotes"] == 1
        resp = api.get_price_quote(pq["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestLotExpirySweep:
    def _setup(self, api, epa_id):
        """Vintage-2025 lot (100 RINs, 60 separated / 40 attached), then clock
        advanced past (2025+2)-03-31T23:59:59Z."""
        acct = create_account(epa_registration_id=epa_id)
        lot = create_generated_lot(acct["id"], d_code="D6", vintage_year=2025,
                                   gallon_qty=100)
        separate_lot(lot["id"], 60)
        set_clock("2028-04-01T00:00:00Z")
        return lot

    def test_active_lot_expires_on_clock_advance(self, api):
        """PRD §2.10: "Once the logical clock passes 23:59:59 UTC on March 31 of the year two years after a lot's vintage, every still-`ACTIVE` lot of that vintage expires in the sweep."

        Design: Corner/state_machines/lot_expiry_sweep_on_clock_advance
        """
        lot = self._setup(api, "EPA-SM-8")
        after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert after["status"] == "EXPIRED"

    def test_expiry_absorbs_all_remaining_buckets(self, api):
        """PRD §2.10: "The lot's status becomes `EXPIRED`; its `expired_qty` rises to absorb every RIN not already retired or invalidated — the available, pending, and still-attached balances alike; and `attached_qty`, `separated_qty`, `pending_retired_qty`, and `available_qty` all fall to zero."

        Design: Corner/state_machines/lot_expiry_sweep_on_clock_advance
        """
        lot = self._setup(api, "EPA-SM-8B")
        after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert after["expired_qty"] == 100
        assert after["available_qty"] == 0
        assert after["attached_qty"] == 0
        assert after["separated_qty"] == 0


class TestInvalidVintageWindow:
    def test_vintage_two_years_before_clock_rejected(self, api):
        """PRD §2.10: "Generation is bounded accordingly: a new lot's `vintage_year` must be the logical clock's current calendar year or the year immediately before it, otherwise creation is rejected with `ERR_INVALID_VINTAGE`."

        Design: Corner/validations/invalid_vintage_year_window
        """
        acct = create_account(epa_registration_id="EPA-VAL-2")
        payload = create_rin_lot_payload(account_id=acct["id"], vintage_year=2024)
        resp = api.create_rin_lot(payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_VINTAGE)

    def test_future_vintage_rejected(self, api):
        """PRD §2.10: "Generation is bounded accordingly: a new lot's `vintage_year` must be the logical clock's current calendar year or the year immediately before it, otherwise creation is rejected with `ERR_INVALID_VINTAGE`."

        Design: Corner/validations/invalid_vintage_year_window
        """
        acct = create_account(epa_registration_id="EPA-VAL-2B")
        payload = create_rin_lot_payload(account_id=acct["id"], vintage_year=2027)
        resp = api.create_rin_lot(payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_VINTAGE)
