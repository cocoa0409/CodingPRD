"""Voucher issuance cap boundary and expiry window semantics."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_coordinator_headers,
    create_caretaker, create_voucher, get_voucher,
)


class TestMonthlyCapBoundary:
    """Difficulty/boundary_precision/monthly_cap_at_exact_boundary"""

    def test_issuance_landing_exactly_on_cap_admitted(self, api):
        """PRD §2.8: "An issuance request whose `face_value_cents` exceeds the
        remaining headroom is rejected with `ERR_MONTHLY_CAP_EXCEEDED` (HTTP 402);
        a request that lands exactly on the cap is admitted, since only a strict
        excess is rejected."

        Design: Difficulty/boundary_precision_check/monthly_cap_at_exact_boundary
        """
        ct, cth = create_caretaker()
        ch = make_coordinator_headers()
        v1 = validate_success(api.create_voucher(
            {"caretaker_id": ct["id"], "face_value_cents": 20000,
             "funding_source": "MUNICIPAL_GRANT"}, ch), expected_status=201)
        v2 = validate_success(api.create_voucher(
            {"caretaker_id": ct["id"], "face_value_cents": 10000,
             "funding_source": "DONATION_FUND"}, ch), expected_status=201)
        assert v1["status"] == "ISSUED" and v2["status"] == "ISSUED", \
            "20000 + 10000 lands exactly on the 30000-cent cap and must be admitted"

    def test_one_cent_over_cap_rejected(self, api):
        """PRD §2.8: "An issuance request whose `face_value_cents` exceeds the
        remaining headroom is rejected with `ERR_MONTHLY_CAP_EXCEEDED` (HTTP 402)"

        Design: Difficulty/boundary_precision_check/monthly_cap_at_exact_boundary
        """
        ct, cth = create_caretaker()
        ch = make_coordinator_headers()
        create_voucher(ct, face_value_cents=20000)
        create_voucher(ct, face_value_cents=10000, funding_source="DONATION_FUND")

        resp = api.create_voucher(
            {"caretaker_id": ct["id"], "face_value_cents": 1,
             "funding_source": "DONATION_FUND"}, ch)
        validate_error(resp, ApiErrorId.ERR_MONTHLY_CAP_EXCEEDED, expected_status=402)


class TestVoucherExpiryWindow:
    """Difficulty/resource_temporal_overlap/voucher_expiry_month_window"""

    def test_voucher_not_expired_two_months_on(self, api):
        """PRD §3.8: "A coordinator-run expiry sweep moves every `ISSUED` voucher
        whose `issued_month` is at least three months before the current logical
        month to `EXPIRED`; committed, redeemed, and voided vouchers are
        untouched."
        PRD §3.8: "If the sweep finds nothing old enough to expire, it is
        rejected with `ERR_NOTHING_TO_EXPIRE` (HTTP 422)."
        A voucher issued 2026-08 swept at 2026-10 has only two months of age, so
        the sweep finds nothing old enough and is rejected; the voucher must
        survive untouched.

        Design: Difficulty/resource_temporal_overlap/voucher_expiry_month_window
        """
        ch = make_coordinator_headers()
        get_success_data(api.set_clock("2026-08-31T12:00:00Z", ch))
        ct, cth = create_caretaker()
        v = create_voucher(ct, face_value_cents=4000)

        get_success_data(api.set_clock("2026-10-31T12:00:00Z", ch))
        resp = api.expire_sweep(ch)
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_EXPIRE, expected_status=422)
        assert get_voucher(v["id"])["status"] == "ISSUED", \
            "2 calendar months elapsed is less than 3 — voucher must survive"

    def test_voucher_expired_three_months_on(self, api):
        """PRD §3.8: "A coordinator-run expiry sweep moves every `ISSUED` voucher
        whose `issued_month` is at least three months before the current logical
        month to `EXPIRED`"
        A voucher issued 2026-08 swept at 2026-11 is exactly three months old and
        must expire.

        Design: Difficulty/resource_temporal_overlap/voucher_expiry_month_window
        """
        ch = make_coordinator_headers()
        get_success_data(api.set_clock("2026-08-31T12:00:00Z", ch))
        ct, cth = create_caretaker()
        v = create_voucher(ct, face_value_cents=4000)

        get_success_data(api.set_clock("2026-11-15T12:00:00Z", ch))
        get_success_data(api.expire_sweep(ch))
        assert get_voucher(v["id"])["status"] == "EXPIRED", \
            "3 calendar months elapsed meets the at-least-three-months threshold"


class TestExpireSweepEmpty:
    def test_expire_sweep_with_nothing_expirable(self, api):
        """PRD §3.8: "If the sweep finds nothing old enough to expire, it is
        rejected with `ERR_NOTHING_TO_EXPIRE` (HTTP 422)."

        Design: Corner/validations/expire_sweep_with_nothing_expirable
        """
        ct, cth = create_caretaker()
        create_voucher(ct, face_value_cents=1000, funding_source="DONATION_FUND")

        resp = api.expire_sweep(make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_EXPIRE, expected_status=422)
