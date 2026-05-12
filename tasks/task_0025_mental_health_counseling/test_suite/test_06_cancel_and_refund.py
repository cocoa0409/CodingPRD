"""Cancellation, refund-tier calculation, and the forward refund estimate
(PRD §3.5)."""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_refund_breakdown_full_pps,
    assert_refund_breakdown_partial_pps,
    cancel_appointment,
    DEFAULT_T0,
    DEFAULT_LIST_PRICE_CENTS,
    find_ledger_row,
    get_appointment,
    get_client,
    list_settlement_ledger_for_appointment,
    make_admin_headers,
    make_client_headers,
    make_counselor_headers,
    setup_appointment_at_24h_boundary,
    setup_confirmed_appointment,
    shift,
    validate_error,
    validate_success,
)


class TestRefundTierFullCancelClient:
    def test_full_refund_when_at_least_24h_out(self, api):
        """PRD §3.5: "if the reason is `CLIENT_CANCEL`, hours-to-start at
        least twenty-four yields `FULL_REFUNDED` with gross equal to
        `list_price_cents`..."
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30,    # well past the 24h floor
            payment_mode="PAY_PER_SESSION",
        )
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "FULL_REFUNDED"
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        refund = find_ledger_row(rows, confirmed["id"], "REFUND")
        assert refund is not None, "PRD §3.5: REFUND row must be written"
        assert_refund_breakdown_full_pps(refund)


class TestRefundBoundary24h:
    def test_at_exactly_24h_cancel_yields_full(self):
        """PRD §3.5: "hours-to-start at least twenty-four yields
        `FULL_REFUNDED`..."

        difficulty: boundary_precision_check/refund_boundary_24h_inclusive
        """
        counselor, client, confirmed = setup_appointment_at_24h_boundary(
            payment_mode="PAY_PER_SESSION",
        )
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "FULL_REFUNDED", \
            "PRD §3.5: at exactly 24h hours-to-start, the inclusive >=24 final transition yields FULL"
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        refund = find_ledger_row(rows, confirmed["id"], "REFUND")
        assert refund is not None
        assert refund["gross_amount_cents"] == -DEFAULT_LIST_PRICE_CENTS

    def test_estimate_at_exactly_24h_yields_partial(self, api):
        """PRD §3.5: "The platform also exposes a forward-looking refund
        estimate. A read-only forecast computes the same decision tree but
        uses strict greater-than comparisons rather than the inclusive
        comparisons of the final transition: hours-to-start strictly
        greater than twenty-four returns `FULL`, strictly greater than two
        returns `PARTIAL`, otherwise `NON_REFUNDABLE`. The boundary case is
        intentional: at hours-to-start of exactly 24.0, the forward
        estimate reports `PARTIAL_REFUNDED` while the actual cancellation
        transition would land on `FULL_REFUNDED`."

        difficulty: dual_variant_calc/refund_estimate_vs_final_boundary_at_24h
        """
        counselor, client, confirmed = setup_appointment_at_24h_boundary(
            payment_mode="PAY_PER_SESSION",
        )
        res = api.get_refund_estimate(
            confirmed["id"], make_client_headers(client["id"]),
        )
        body = validate_success(res, expected_status=200)
        assert body["refund_state"] == "PARTIAL_REFUNDED", \
            "PRD §3.5: at exactly 24h, forward estimate uses strict > so reports PARTIAL"


class TestRefundTierPartial:
    def test_partial_refund_between_2_and_24h(self):
        """PRD §3.5: "hours-to-start less than twenty-four but at least two
        yields `PARTIAL_REFUNDED` with gross equal to `list_price_cents`
        multiplied by one half and rounded half up to the nearest cent..."
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=10,    # 10 hours out — partial
            payment_mode="PAY_PER_SESSION",
        )
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "PARTIAL_REFUNDED"
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        refund = find_ledger_row(rows, confirmed["id"], "REFUND")
        assert refund is not None
        assert_refund_breakdown_partial_pps(refund)


class TestRefundTierNonRefundable:
    def test_non_refundable_under_2h(self, api):
        """PRD §3.5: "hours-to-start less than two yields `NON_REFUNDABLE`
        with gross of zero."
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=3,    # later we advance clock to <2h
            payment_mode="PAY_PER_SESSION",
        )
        # Advance clock so hours_to_start < 2 (e.g., now() = start_at - 90m).
        slot_start = confirmed.get("started_at") or None
        # We need to anchor against the slot's start_at; fetch the appointment.
        appt = get_appointment(confirmed["id"])
        from test_helpers import parse_iso, iso_z
        from datetime import timedelta
        start_dt = parse_iso(_get_slot_start(appt))
        target_now = iso_z(start_dt - timedelta(minutes=90))
        advance_clock(target_now)
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "NON_REFUNDABLE"
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        # PRD §3.5: NON_REFUNDABLE means refund gross is zero. Whether a
        # zero-gross REFUND row is written is implementer-discretion (PRD
        # §3.5 prose says "the refund's gross amount is the appointment's
        # frozen list_price_cents" but only for FULL/PARTIAL; for NON, it
        # says "yields NON_REFUNDABLE with gross of zero" without
        # explicitly stating a row is created). Don't assert presence; do
        # assert: if a REFUND row exists, its gross is 0.
        refund_rows = [r for r in rows if r["direction"] == "REFUND"]
        for r in refund_rows:
            assert r["gross_amount_cents"] == 0


class TestRefundFullCounselorOrCrisis:
    def test_counselor_cancel_yields_full_refund_regardless_of_time(self):
        """PRD §3.5: "if the reason is `COUNSELOR_CANCEL` or
        `CRISIS_HANDOVER`, `refund_state` is `FULL_REFUNDED` and the
        refund's gross amount is the appointment's frozen `list_price_cents`..."
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=3,    # < 24h, would normally be partial
            payment_mode="PAY_PER_SESSION",
        )
        cancelled = cancel_appointment(
            actor_headers=make_counselor_headers(counselor["id"]),
            appointment=confirmed, reason="COUNSELOR_CANCEL",
        )
        assert cancelled["refund_state"] == "FULL_REFUNDED"


class TestPackageRefundCreditBack:
    def test_full_refund_package_credits_balance(self):
        """PRD §3.5: "When `refund_state` is `FULL_REFUNDED` or
        `PARTIAL_REFUNDED` and the appointment had been paid by `PACKAGE`,
        the client's `package_balance_sessions` is incremented by one as
        part of the same operation."
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PACKAGE",
            package_balance_sessions=3,
        )
        balance_after_confirm = get_client(client["id"])["package_balance_sessions"]
        cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        balance_after_cancel = get_client(client["id"])["package_balance_sessions"]
        assert balance_after_cancel == balance_after_confirm + 1, \
            "PRD §3.5: FULL_REFUNDED PACKAGE refund credits package_balance_sessions by 1"


class TestCashLedgerInvariant:
    def test_pps_full_refund_round_trip_sums_to_zero(self):
        """PRD §3.8: "For `PAY_PER_SESSION`, `gross_amount_cents` equals
        the appointment's frozen `list_price_cents`..."
        PRD §3.5: "All three components are recorded with negative sign on
        the REFUND row of `SettlementLedger`."

        Invariant from difficulty: compensating_invariant/cash_ledger_invariant_under_full_refund
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
            revenue_share_bps=7000,
        )
        cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        # Each component sums to 0.
        assert sum(r["gross_amount_cents"] for r in rows) == 0
        assert sum(r["tax_cents"] for r in rows) == 0
        assert sum(r["counselor_share_cents"] for r in rows) == 0
        assert sum(r["platform_share_cents"] for r in rows) == 0
        # Exactly two ledger rows: one CHARGE, one REFUND.
        directions = sorted(r["direction"] for r in rows)
        assert directions == ["CHARGE", "REFUND"]


class TestPackageBalanceInvariant:
    def test_package_round_trip_returns_balance_to_original(self):
        """PRD §3.5: "the client's `package_balance_sessions` is incremented
        by one as part of the same operation."
        PRD §3.4: "if the payment mode is `PACKAGE` the client's
        `package_balance_sessions` is decremented by one."

        Invariant from difficulty: compensating_invariant/package_balance_invariant_under_full_refund
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PACKAGE",
            package_balance_sessions=5,
        )
        balance_after_confirm = get_client(client["id"])["package_balance_sessions"]
        cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        balance_after_cancel = get_client(client["id"])["package_balance_sessions"]
        # Originally credited 5 + 1 (extra setup) = 6; confirm debits 1 -> 5;
        # then cancel credits +1 -> 6. Just check round-trip recovers from
        # the post-confirm value.
        assert balance_after_cancel == balance_after_confirm + 1


# ---------------------------------------------------------------------------
# Helper extracted from test code
# ---------------------------------------------------------------------------
def _get_slot_start(appt: dict) -> str:
    """Fetch the start_at of the slot referenced by an appointment."""
    from test_helpers import TEST_USERS, api_client
    res = api_client.list_availability_slots(
        TEST_USERS["admin_headers"],
        params={"counselor_id": appt["counselor_id"], "limit": 100},
    ).json()
    for s in res["data"]:
        if s["id"] == appt["slot_id"]:
            return s["start_at"]
    raise AssertionError(
        f"slot {appt['slot_id']} not found in counselor's slots"
    )
