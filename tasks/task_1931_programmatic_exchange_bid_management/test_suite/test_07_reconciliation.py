"""Discrepancy reporting: the auto-flag boundary and the branching entry into
DISPUTED; resolution input contract and terminal-state lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_reconciliation_report,
    confirm_record,
    create_deal_for,
    create_package_for,
    create_partner,
    create_publisher,
    create_reconciliation_report_payload,
    create_report,
    fill_auction,
    resolve_report,
    resolve_report_payload,
    setup_active_deal,
    submit_and_approve_deal,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def _two_publisher_reports():
    """P_HI's deal gets a 1000-impression unconfirmed fill plus a
    980-impression confirmed fill (ssp 1980 vs dsp 980). P_LO's deal gets a
    single confirmed 500-impression fill (ssp 500 vs dsp 500)."""
    pub_hi = create_publisher("Pub HI", "phi.com")
    pub_lo = create_publisher("Pub LO", "plo.com")
    partner = create_partner()
    pkg_hi = create_package_for(pub_hi["id"])
    pkg_lo = create_package_for(pub_lo["id"])
    deal_hi = submit_and_approve_deal(
        create_deal_for(pub_hi["id"], pkg_hi["id"], partner["id"])["id"],
        pub_hi["id"])
    deal_lo = submit_and_approve_deal(
        create_deal_for(pub_lo["id"], pkg_lo["id"], partner["id"])["id"],
        pub_lo["id"])
    fill_auction(pub_hi["id"], impression_count=1000)
    rec_hi = fill_auction(pub_hi["id"], impression_count=980)
    confirm_record(rec_hi["id"])
    rec_lo = fill_auction(pub_lo["id"], impression_count=500)
    confirm_record(rec_lo["id"])
    return deal_hi, deal_lo


class TestBranchingEntryIntoDisputed:
    def test_auto_flagged_report_is_born_disputed(self, api):
        """PRD §3.7: "The headline figure, `discrepancy_pct`, is the absolute
        difference between `ssp_impressions` and `dsp_impressions`, multiplied
        by 100, divided by `ssp_impressions` — or by 1 when `ssp_impressions` is
        zero — and rounded half-up to three decimal places. When the discrepancy
        is strictly greater than 2.000 percent, the report is `auto_flagged` and
        is born directly in `DISPUTED`; otherwise it opens in `OPEN`."

        Design: Difficulty/non_linear_state_machine/reconciliation_report_branching_entry_into_disputed
        """
        deal_hi, _deal_lo = _two_publisher_reports()
        report = create_report(deal_hi["id"], "2026-08-01", "2026-08-02")
        assert_reconciliation_report(report)
        assert report["ssp_impressions"] == 1980
        assert report["dsp_impressions"] == 980
        assert report["discrepancy_pct"] == pytest.approx(50.505), (
            "|1980 - 980| x 100 / 1980, rounded half-up to three decimals")
        assert report["auto_flagged"] is True
        assert report["status"] == "DISPUTED", "Born DISPUTED via the auto-flag branch"

    def test_zero_discrepancy_report_walks_manual_branch_to_disputed(self, api):
        """PRD §3.7: "otherwise it opens in `OPEN`. From `OPEN`, an
        `ExchangeAdmin` or `FinanceOfficer` acknowledges it to `ACKNOWLEDGED`;
        from `ACKNOWLEDGED` it can be escalated to `DISPUTED`, converging with
        the auto-flagged path."

        Design: Difficulty/non_linear_state_machine/reconciliation_report_branching_entry_into_disputed
        """
        _deal_hi, deal_lo = _two_publisher_reports()
        report = create_report(deal_lo["id"], "2026-08-01", "2026-08-02")
        assert report["discrepancy_pct"] == pytest.approx(0.0)
        assert report["auto_flagged"] is False
        assert report["status"] == "OPEN"

        acked = validate_success(api.acknowledge_report(report["id"], ADMIN))
        assert acked["status"] == "ACKNOWLEDGED"
        disputed = validate_success(api.dispute_report(report["id"], FINANCE))
        assert disputed["status"] == "DISPUTED", (
            "Same DISPUTED state, reached through the manual branch")


class TestDiscrepancyThreshold:
    def _threshold_scenario(self, api, unconfirmed_imps, confirmed_imps):
        sc = setup_active_deal()
        fill_auction(sc["pub"]["id"], impression_count=unconfirmed_imps)
        rec = fill_auction(sc["pub"]["id"], impression_count=confirmed_imps)
        confirm_record(rec["id"])
        return sc

    def test_discrepancy_exactly_at_threshold_not_flagged(self, api):
        """PRD §3.7: "When the discrepancy is strictly greater than 2.000
        percent, the report is `auto_flagged` and is born directly in
        `DISPUTED`; otherwise it opens in `OPEN`."

        Design: Difficulty/boundary_precision_check/discrepancy_exactly_at_threshold_not_flagged
        """
        sc = self._threshold_scenario(api, 20, 980)
        report = create_report(sc["deal"]["id"], "2026-08-01", "2026-08-02")
        assert report["ssp_impressions"] == 1000
        assert report["dsp_impressions"] == 980
        assert report["discrepancy_pct"] == pytest.approx(2.0), (
            "|1000 - 980| x 100 / 1000 == 2.000 exactly")
        assert report["auto_flagged"] is False, (
            "2.000 is NOT > 2.000 — the boundary is strict")
        assert report["status"] == "OPEN"

    def test_discrepancy_above_threshold_is_flagged(self, api):
        """PRD §3.7: "When the discrepancy is strictly greater than 2.000
        percent, the report is `auto_flagged` and is born directly in
        `DISPUTED`"

        Design: Difficulty/boundary_precision_check/discrepancy_exactly_at_threshold_not_flagged
        """
        sc = self._threshold_scenario(api, 21, 979)
        report = create_report(sc["deal"]["id"], "2026-08-01", "2026-08-02")
        assert report["ssp_impressions"] == 1000
        assert report["dsp_impressions"] == 979
        assert report["discrepancy_pct"] == pytest.approx(2.1), (
            "|1000 - 979| x 100 / 1000 == 2.100")
        assert report["auto_flagged"] is True
        assert report["status"] == "DISPUTED"


class TestResolutionContract:
    def test_report_resolve_twice_rejected(self, api):
        """PRD §3.7: "Resolution stamps `resolved_at` with the logical time and
        moves the report to the terminal `RESOLVED`; any attempt to acknowledge,
        dispute, or resolve a resolved report is rejected with
        `ERR_REPORT_ALREADY_TERMINAL`."

        Design: Corner/state_machines/report_resolve_twice_rejected
        """
        sc = setup_active_deal()
        rec = fill_auction(sc["pub"]["id"], impression_count=500)
        confirm_record(rec["id"])
        report = create_report(sc["deal"]["id"], "2026-08-01", "2026-08-02")
        resolved = resolve_report(report["id"], "ACCEPT_SSP")
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"] is not None

        resp = api.resolve_report(report["id"], resolve_report_payload("ACCEPT_DSP"),
                                  FINANCE)
        validate_error(resp, ApiErrorId.ERR_REPORT_ALREADY_TERMINAL)
        after = validate_success(api.get_reconciliation_report(report["id"], ADMIN))
        assert after["status"] == "RESOLVED"
        assert after["resolution_type"] == "ACCEPT_SSP"

    def test_recon_makegood_without_adjustment_rejected(self, api):
        """PRD §3.7: "A make-good requires `adjustment_micros` greater than
        zero; the two accept resolutions forbid it outright — mixing these up is
        rejected with `ERR_RECONCILIATION_INPUT_MISMATCH`."

        Design: Corner/validations/recon_makegood_without_adjustment_rejected
        """
        sc = setup_active_deal()
        rec = fill_auction(sc["pub"]["id"], impression_count=500)
        confirm_record(rec["id"])
        r1 = validate_success(api.create_reconciliation_report(
            create_reconciliation_report_payload(sc["deal"]["id"], "2026-08-01",
                                                 "2026-08-02"), FINANCE), 201)
        r2 = validate_success(api.create_reconciliation_report(
            create_reconciliation_report_payload(sc["deal"]["id"], "2026-08-02",
                                                 "2026-08-03"), FINANCE), 201)
        assert r1["status"] == "OPEN"
        assert r2["status"] == "OPEN"

        # MAKE_GOOD without adjustment_micros.
        resp = api.resolve_report(r1["id"], resolve_report_payload("MAKE_GOOD"),
                                  ADMIN)
        validate_error(resp, ApiErrorId.ERR_RECONCILIATION_INPUT_MISMATCH)
        assert validate_success(
            api.get_reconciliation_report(r1["id"], ADMIN))["status"] == "OPEN"

        # ACCEPT_SSP carrying adjustment_micros.
        resp = api.resolve_report(
            r2["id"], resolve_report_payload("ACCEPT_SSP", adjustment_micros=5000),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_RECONCILIATION_INPUT_MISMATCH)
        assert validate_success(
            api.get_reconciliation_report(r2["id"], ADMIN))["status"] == "OPEN"
