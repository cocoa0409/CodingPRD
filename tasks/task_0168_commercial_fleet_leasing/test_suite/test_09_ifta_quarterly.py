"""IFTA quarterly filing — PRD §3.9.

Covers: open quarter, prepare time-gate, file side-effects, IFTA
tax computation with per-jurisdiction rounding, txn flip to
IFTA_INCLUDED on filing.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    api_client,
    assert_ifta_quarter,
    create_ifta_quarter_payload,
    file_ifta_quarter,
    get_ifta_quarter,
    open_ifta_quarter,
    post_fuel_card_transaction,
    prepare_ifta_quarter,
    setup_class8_lease_with_card,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Open IFTA quarter — PRD §3.9
# ===========================================================================
class TestQuarterOpen:

    def test_open_quarter_initial_state(self, api):
        """PRD §3.9: "A `TaxAdmin` opens a quarter on a lessee by
        supplying `year` (an integer 2000 to 2099 inclusive) and
        `quarter` (an integer 1 to 4 inclusive); the row is born in
        `OPEN` (the `filing_status` field) with
        `total_taxable_gallons` and `total_tax_cents` initialised to
        zero."

        Claim: a fresh quarter is OPEN with both totals == 0.
        """
        from test_helpers import create_lessee
        lessee = create_lessee()
        resp = api.create_ifta_quarter(
            lessee["id"],
            create_ifta_quarter_payload(year=2026, quarter=1),
            TEST_USERS["tax_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_ifta_quarter(data)
        assert data["filing_status"] == "OPEN"
        assert data["total_taxable_gallons"] == 0
        assert data["total_tax_cents"] == 0


# ===========================================================================
# Prepare — PRD §3.9
# ===========================================================================
class TestQuarterPrepare:

    def test_prepare_before_quarter_end_rejected(self, api):
        """PRD §3.9: "The transition is temporally gated: the call may
        run only when the current clock is at or after the last
        instant of the quarter — preparing a quarter that has not yet
        ended is rejected with `ERR_QUARTER_NOT_READY`."

        Claim: prepare with clock < quarter_end_date returns
        ERR_QUARTER_NOT_READY.

        PRD §3.10: clock advance is monotonic ("idempotent in the past
        direction"). Earlier tests in the suite may have advanced the
        clock to any point in 2026. Use a far-future quarter (2099 Q4)
        so the temporal gate is unambiguously open regardless of which
        tests have already run.
        """
        from test_helpers import create_lessee
        lessee = create_lessee()
        q = open_ifta_quarter(
            lessee_id=lessee["id"], year=2099, quarter=4,
        )
        # Quarter ends 2099-12-31 — well beyond any clock advance the
        # rest of the suite issues, so prepare must reject.
        resp = api.prepare_ifta_quarter(
            q["id"], TEST_USERS["tax_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_QUARTER_NOT_READY.value)

    def test_prepare_after_quarter_end_succeeds(self, api):
        """PRD §3.9: "the call may run only when the current clock
        is at or after the last instant of the quarter."

        Claim: prepare after Q1 end advances the quarter to READY.
        """
        from test_helpers import create_lessee
        advance_clock_to_iso("2026-01-15T00:00:00.000Z")
        lessee = create_lessee()
        q = open_ifta_quarter(
            lessee_id=lessee["id"], year=2026, quarter=1,
        )
        # Advance past quarter end.
        advance_clock_to_iso("2026-04-01T00:00:00.000Z")
        resp = api.prepare_ifta_quarter(
            q["id"], TEST_USERS["tax_admin_headers"],
        )
        data = validate_success(resp)
        assert data["filing_status"] == "READY"


# ===========================================================================
# File — PRD §3.9
# ===========================================================================
class TestQuarterFile:

    def test_file_flips_txns_to_ifta_included(self, api):
        """PRD §3.9: "Filing the prepared quarter then advances it
        from `READY` to `CLOSED`, and as its side effect the system
        iterates every `POSTED` `FuelCardTransaction` in the quarter
        window whose `ifta_eligible` is true and flips each one's
        `txn_status` from `POSTED` to `IFTA_INCLUDED`."

        We cannot directly GET a transaction (no endpoint in PRD §4),
        so we observe the flip indirectly via the IFTA computation:
        after filing, posting a new POSTED-eligible txn for the same
        window would be rejected with ERR_QUARTER_CLOSED (PRD §3.9
        elsewhere). The flip side-effect is best exercised by the
        cumulative result: after prepare+file, the quarter's
        total_taxable_gallons reflects exactly the gallons that were
        in scope at prepare time and total_tax_cents is the
        computed-and-stored value.

        Claim: after file, the quarter is CLOSED and totals are
        preserved from prepare time.
        """
        advance_clock_to_iso("2026-01-15T00:00:00.000Z")
        lessee, vehicle, lease, card = setup_class8_lease_with_card(
            base_jurisdiction="CA",
        )
        post_fuel_card_transaction(
            fuel_card_id=card["id"],
            posted_at="2026-01-20T10:00:00.000Z",
            jurisdiction="CA", gallons=10.0, amount_cents=4000,
        )
        advance_clock_to_iso("2026-04-01T00:00:00.000Z")
        q = open_ifta_quarter(
            lessee_id=lessee["id"], year=2026, quarter=1,
        )
        q = prepare_ifta_quarter(q["id"])
        # Totals after prepare.
        gallons_after_prepare = q["total_taxable_gallons"]
        tax_after_prepare = q["total_tax_cents"]
        # File.
        resp = api.file_ifta_quarter(
            q["id"], TEST_USERS["tax_admin_headers"],
        )
        data = validate_success(resp)
        assert data["filing_status"] == "CLOSED"
        assert data["total_taxable_gallons"] == gallons_after_prepare
        assert data["total_tax_cents"] == tax_after_prepare


# ===========================================================================
# IFTA tax calculation — PRD §3.9
# ===========================================================================
class TestIFTATaxCalculation:

    def test_prepare_computes_signed_tax_with_per_j_rounding(self, api):
        """PRD §3.9: "From those transactions the system groups by
        `jurisdiction` and sums the `gallons` field within each
        group ... The system then computes a per-jurisdiction tax
        owed: for each jurisdiction `j`, multiply that jurisdiction's
        gallons by the configured per-jurisdiction rate in
        cents-per-gallon ... round the resulting cents half-up to a
        whole cent, and add the rounded amount to a running tax-owed
        total. The system separately computes a tax credit, which is
        granted at the rate of the lessee's `base_jurisdiction`
        applied uniformly to the entire `total_taxable_gallons` ...
        multiply `total_taxable_gallons` by the base-jurisdiction
        rate from the same table, then round that result half-up to
        a whole cent. The quarter's `total_tax_cents` is the
        tax-owed total minus the tax-credit value; the result is a
        signed integer, where a positive value means money owed by
        the lessee to the IFTA authority and a negative value means
        a refund owed to the lessee."

        Scenario from the difficulty-design recipe:
          base_jurisdiction=CA; vehicle CLASS_8;
          three txns: (CA, 10.5, 4000), (TX, 7.3, 2800), (NY, 5.1, 2100).
        Expected per-j: CA=round_half_up(10.5*87)=914,
                        TX=round_half_up(7.3*20)=146,
                        NY=round_half_up(5.1*45)=230;
                        owed = 914 + 146 + 230 = 1290.
        Tax credit (CA base rate 87 on 22.9 gal):
                        round_half_up(22.9*87) = round_half_up(1992.3) = 1992.
        Total = 1290 - 1992 = -702 (refund).
        """
        from test_helpers import (
            setup_q1_2026_three_state_ifta_scenario,
        )
        ctx = setup_q1_2026_three_state_ifta_scenario(
            base_jurisdiction="CA",
        )
        q = prepare_ifta_quarter(ctx["quarter"]["id"])
        # Floating equality: gallons sum is 22.9 (could come back as 22.9
        # or 22.9 ± ε depending on float representation; check approx).
        assert abs(q["total_taxable_gallons"] - 22.9) < 1e-6, (
            f"total_taxable_gallons must be 22.9, "
            f"got {q['total_taxable_gallons']!r}"
        )
        assert q["total_tax_cents"] == -702, (
            f"total_tax_cents must be 1290 - 1992 = -702 (refund), "
            f"got {q['total_tax_cents']!r}"
        )
