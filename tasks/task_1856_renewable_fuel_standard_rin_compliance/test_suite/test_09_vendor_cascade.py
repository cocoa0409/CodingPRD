"""Vendor-revocation invalidation cascade (PRD §3.4)."""
from test_helpers import (
    CM,
    create_account_and_year,
    create_approved_vendor,
    create_batch,
    create_report,
    create_verified_trade,
    decide_batch,
    decide_report,
    get_purchased_lot_for_trade,
    get_success_data,
    make_compliance_manager_headers,
    make_trader_headers,
    submit_batch,
    submit_report,
    validate_success,
    api_client,
)


def _setup_revocation_scenario(api, epa_id):
    """Year (provisional TOTAL RVO 400) + APPROVED vendor + verified trade of
    500 D6/2026 RINs + ACCEPTED batch of 400 + ACCEPTED QUARTERLY report."""
    acct, yr = create_account_and_year(epa_registration_id=epa_id)
    tr1 = make_trader_headers("tr-1")
    ven = create_approved_vendor(acct["id"], headers=tr1)
    trd, lot = create_verified_trade(
        acct["id"], ven["id"], trader_headers=tr1,
        verifier_headers=make_compliance_manager_headers("cm-1"),
        rin_qty=500, price_per_rin_cents=100,
    )
    batch = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                         rin_qty=400)
    submit_batch(batch["id"])
    decide_batch(batch["id"], "ACCEPT")
    rep = create_report(yr["id"], report_type="QUARTERLY",
                        quarter_end_date="2026-06-30T00:00:00Z")
    submit_report(rep["id"])
    decide_report(rep["id"], "ACCEPT")
    return yr, ven, trd, lot, rep


class TestVendorRevocationCascade:
    def test_revocation_invalidates_trades_and_lots(self, api):
        """PRD §3.4: "Revoking a vendor fires the same cascade at portfolio scale. Every trade of the revoked vendor whose transfer stands `DELIVERED` or `VERIFIED` becomes `INVALIDATED`, and each per-trade cascade — lot invalidation, year counter re-derivation, posture re-derivation, accepted-report reflagging — fires exactly as declared above."
        PRD §3.4: "Either way, the purchased lot is invalidated alongside: the lot's status becomes `INVALIDATED`, its `invalidated_qty` absorbs everything not already retired or expired (the available, pending, and attached balances alike), and `attached_qty`, `separated_qty`, `pending_retired_qty`, and `available_qty` all fall to zero."

        Design: Difficulty/transitive_cascade/vendor_revocation_invalidation_cascade
        """
        _yr, ven, trd, lot, _rep = _setup_revocation_scenario(api, "EPA-ACME-7")
        data = get_success_data(
            api.record_diligence(ven["id"], {"outcome": "REVOKED"}, CM),
        )
        assert data["diligence_status"] == "REVOKED"
        trd_after = validate_success(api.get_rin_trade(trd["id"], CM))
        assert trd_after["transfer_status"] == "INVALIDATED"
        lot_after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert lot_after["status"] == "INVALIDATED"
        # 500 rin_qty - 400 already retired = 100 clawed into invalidated_qty.
        assert lot_after["invalidated_qty"] == 100

    def test_revocation_rederives_year_counters_and_reflages_reports(self, api):
        """PRD §3.4: "Invalidating a `VERIFIED` trade additionally claws back any of the lot's RINs already retired: the obligation year's retired counters are not decremented by a delta but re-derived from scratch over the year's `ACCEPTED` batches, excluding RINs that sit on invalidated lots, and the year's posture is re-derived with them."
        PRD §3.4: "When a lot invalidation mutates a year's retired counters beneath a report EPA has already accepted, every `ACCEPTED` report for that year is driven back to `REJECTED` with `amendment_required` set to true"

        Design: Difficulty/transitive_cascade/vendor_revocation_invalidation_cascade
        """
        yr, ven, _trd, _lot, rep = _setup_revocation_scenario(
            api, "EPA-ACME-7B",
        )
        get_success_data(api.record_diligence(ven["id"], {"outcome": "REVOKED"}, CM))
        yr_after = validate_success(api.get_obligation_year(yr["id"], CM))
        assert yr_after["retired_total_rins"] == 0
        rep_after = validate_success(api.get_compliance_report(rep["id"], CM))
        assert rep_after["status"] == "REJECTED"
        assert rep_after["amendment_required"] is True
