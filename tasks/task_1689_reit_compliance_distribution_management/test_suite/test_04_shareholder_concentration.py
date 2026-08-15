"""Shareholder concentration snapshots: half-year grid, 5/50 boundary,
violator freeze cascade, and the five_fifty_blocked gate (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_position,
    assert_shareholder_snapshot,
    create_approved_dividend,
    create_dividend,
    create_posted_requirement,
    create_reit,
    create_shareholder,
    create_shareholder_snapshot_payload,
    create_snapshot,
    declare_dividend,
    finalize_failing_snapshot,
    finalize_snapshot,
    get_reit,
    setup_snapshot_with_positions,
    validate_error,
    validate_success,
)


class TestSnapshotDateGrid:
    def test_duplicate_snapshot_date_rejected(self, api,
                                              compliance_officer_headers):
        """PRD §2.10: "A shareholder snapshot's `snapshot_date` must be unique
        within its REIT." and "Violating any of these yields `ERR_DUPLICATE`."

        Design: Difficulty/resource_temporal_overlap/snapshot_point_date_collision_on_half_year_grid
        """
        reit = create_reit(legal_name="OV2 REIT")
        first = api.create_shareholder_snapshot(
            create_shareholder_snapshot_payload(
                reit["id"], snapshot_date="2026-06-30",
                total_shares_outstanding=1000,
            ),
            compliance_officer_headers,
        )
        validate_success(first, 201)
        resp = api.create_shareholder_snapshot(
            create_shareholder_snapshot_payload(
                reit["id"], snapshot_date="2026-06-30",
                total_shares_outstanding=2000,
            ),
            compliance_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_off_grid_snapshot_date_rejected(self, api,
                                             compliance_officer_headers):
        """PRD §3.4: "A `snapshot_date` that is not a half-year last day is
        rejected with `ERR_INVALID_DATE_RANGE`."

        Design: Difficulty/resource_temporal_overlap/snapshot_point_date_collision_on_half_year_grid
        """
        reit = create_reit(legal_name="OV2 REIT 2")
        resp = api.create_shareholder_snapshot(
            create_shareholder_snapshot_payload(
                reit["id"], snapshot_date="2026-06-29",
                total_shares_outstanding=1000,
            ),
            compliance_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestFiveFiftyBoundary:
    def _setup_five_individuals(self, shares_each):
        reit = create_reit(legal_name="B55 REIT")
        holders = [
            create_shareholder(reit["id"], f"I{i}", "INDIVIDUAL")
            for i in range(1, 6)
        ]
        snapshot = setup_snapshot_with_positions(
            reit["id"],
            [(h["id"], shares_each) for h in holders],
            snapshot_date="2026-06-30", total_shares_outstanding=1000,
        )
        return reit, holders, snapshot

    def test_exactly_50_percent_passes(self, api, compliance_officer_headers):
        """PRD §2.5: "a top-five individual concentration of exactly 50.0000
        passes the 5/50 test".
        PRD §3.4: "The `five_fifty_passed` boolean is true when that sum is at
        most 50.0000, inclusive."

        Design: Difficulty/boundary_precision_check/five_fifty_exactly_50_percent_passes
        """
        reit, _holders, snapshot = self._setup_five_individuals(100)
        finalized = validate_success(
            api.finalize_shareholder_snapshot(snapshot["id"],
                                              compliance_officer_headers),
            200,
        )
        assert_shareholder_snapshot(finalized)
        assert finalized["top5_individual_pct"] == pytest.approx(50.0, abs=1e-9)
        assert finalized["five_fifty_passed"] is True
        assert get_reit(reit["id"])["five_fifty_blocked"] is False

    def test_above_50_percent_fails_and_blocks(self, api,
                                               compliance_officer_headers):
        """PRD §3.4: "The `five_fifty_passed` boolean is true when that sum is
        at most 50.0000, inclusive."
        PRD §3.4: "The REIT's `five_fifty_blocked` flag is set to the negation
        of `five_fifty_passed` — a failing snapshot sets it true, and a later
        passing snapshot clears it".

        Design: Difficulty/boundary_precision_check/five_fifty_exactly_50_percent_passes
        """
        reit, _holders, snapshot = self._setup_five_individuals(101)
        finalized = validate_success(
            api.finalize_shareholder_snapshot(snapshot["id"],
                                              compliance_officer_headers),
            200,
        )
        assert finalized["top5_individual_pct"] == pytest.approx(50.5, abs=1e-9)
        assert finalized["five_fifty_passed"] is False
        assert get_reit(reit["id"])["five_fifty_blocked"] is True


def test_five_fifty_ignores_entity_holders(api, compliance_officer_headers):
    """PRD §3.4: "Only `INDIVIDUAL` holders count toward the five-or-fewer
    test; `ENTITY` holders do not."

    Design: Corner/calculations/five_fifty_ignores_entity_holders
    """
    reit = create_reit(legal_name="C5 REIT")
    indi = create_shareholder(reit["id"], "Indi", "INDIVIDUAL")
    fund = create_shareholder(reit["id"], "Fund", "ENTITY")
    snapshot = setup_snapshot_with_positions(
        reit["id"], [(indi["id"], 450), (fund["id"], 550)],
        snapshot_date="2026-06-30", total_shares_outstanding=1000,
    )
    finalized = validate_success(
        api.finalize_shareholder_snapshot(snapshot["id"],
                                          compliance_officer_headers),
        200,
    )
    assert finalized["top5_individual_pct"] == pytest.approx(45.0, abs=1e-9)
    assert finalized["five_fifty_passed"] is True


class TestFinalizeCascade:
    def _setup_six_holder_snapshot(self):
        reit = create_reit(legal_name="FF REIT", charter_ownership_limit_pct=9.8)
        names = ["Alice", "Bob", "Cara", "Dan", "Eve", "Frank"]
        holders = {
            name: create_shareholder(reit["id"], name, "INDIVIDUAL")
            for name in names
        }
        shares = {"Alice": 130, "Bob": 120, "Cara": 110,
                  "Dan": 100, "Eve": 90, "Frank": 50}
        snapshot = setup_snapshot_with_positions(
            reit["id"],
            [(holders[name]["id"], shares[name]) for name in names],
            snapshot_date="2026-06-30", total_shares_outstanding=1000,
        )
        return reit, holders, snapshot

    def test_finalize_sets_block_and_fails(self, api,
                                           compliance_officer_headers):
        """PRD §3.4: "The `top5_individual_pct` is the sum of those top-five
        concentration percentages, again rounded half-up to four decimals."
        PRD §3.4: "The REIT's `five_fifty_blocked` flag is set to the negation
        of `five_fifty_passed` — a failing snapshot sets it true, and a later
        passing snapshot clears it".

        Design: Difficulty/transitive_cascade/snapshot_finalize_freezes_violators_and_blocks_reit
        """
        reit, _holders, snapshot = self._setup_six_holder_snapshot()
        finalized = validate_success(
            api.finalize_shareholder_snapshot(snapshot["id"],
                                              compliance_officer_headers),
            200,
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["top5_individual_pct"] == pytest.approx(55.0, abs=1e-9)
        assert finalized["five_fifty_passed"] is False
        assert get_reit(reit["id"])["five_fifty_blocked"] is True

    def test_finalize_freezes_violator_shareholders(
            self, api, compliance_officer_headers):
        """PRD §3.4: "In parallel, the system computes
        `violator_shareholder_ids`: every position whose `concentration_pct`
        strictly exceeds the REIT's `charter_ownership_limit_pct`, ordered by
        `shares_held` descending with the same `created_at` ascending
        tie-break."
        PRD §3.4: "Every shareholder appearing in `violator_shareholder_ids`
        transitions `ACTIVE → FROZEN`, with the shareholder's `version`
        incrementing by one."

        Design: Difficulty/transitive_cascade/snapshot_finalize_freezes_violators_and_blocks_reit
        """
        reit, holders, snapshot = self._setup_six_holder_snapshot()
        finalized = validate_success(
            api.finalize_shareholder_snapshot(snapshot["id"],
                                              compliance_officer_headers),
            200,
        )
        expected_violators = [
            holders["Alice"]["id"], holders["Bob"]["id"],
            holders["Cara"]["id"], holders["Dan"]["id"],
        ]
        assert finalized["violator_shareholder_ids"] == expected_violators
        for name in ("Alice", "Bob", "Cara", "Dan"):
            holder = validate_success(
                api.get_shareholder(holders[name]["id"],
                                    compliance_officer_headers),
                200,
            )
            assert holder["status"] == "FROZEN", (
                f"{name} at >9.8% concentration must be FROZEN"
            )
        for name in ("Eve", "Frank"):
            holder = validate_success(
                api.get_shareholder(holders[name]["id"],
                                    compliance_officer_headers),
                200,
            )
            assert holder["status"] == "ACTIVE", (
                f"{name} at <=9.8% concentration must stay ACTIVE"
            )


class TestFiveFiftyBlockCompensation:
    def _setup_reit_with_two_holders(self):
        reit = create_reit(legal_name="INV2 REIT")
        dom = create_shareholder(reit["id"], "Dom", "INDIVIDUAL")
        pub = create_shareholder(reit["id"], "Pub", "ENTITY")
        return reit, dom, pub

    def test_block_set_then_cleared_by_later_passing_snapshot(
            self, api, compliance_officer_headers):
        """PRD §3.4: "The REIT's `five_fifty_blocked` flag is set to the
        negation of `five_fifty_passed` — a failing snapshot sets it true, and
        a later passing snapshot clears it, so the flag always reflects the
        most recent finalized snapshot covering a half-year end."

        Design: Difficulty/compensating_invariant/five_fifty_block_set_and_cleared_by_later_passing_snapshot
        """
        reit, dom, pub = self._setup_reit_with_two_holders()
        h1 = setup_snapshot_with_positions(
            reit["id"], [(dom["id"], 600), (pub["id"], 400)],
            snapshot_date="2026-06-30", total_shares_outstanding=1000,
        )
        finalize_snapshot(h1["id"])
        assert get_reit(reit["id"])["five_fifty_blocked"] is True

        h2 = setup_snapshot_with_positions(
            reit["id"], [(dom["id"], 400), (pub["id"], 600)],
            snapshot_date="2026-12-31", total_shares_outstanding=1000,
        )
        finalized_h2 = validate_success(
            api.finalize_shareholder_snapshot(h2["id"],
                                              compliance_officer_headers),
            200,
        )
        assert finalized_h2["five_fifty_passed"] is True
        assert finalized_h2["top5_individual_pct"] == pytest.approx(40.0,
                                                                    abs=1e-9)
        assert get_reit(reit["id"])["five_fifty_blocked"] is False

    def test_block_gates_declare_until_cleared(self, api,
                                               compliance_officer_headers):
        """PRD §3.4: "While `five_fifty_blocked` is true, dividend approval
        and dividend declaration are both rejected with
        `ERR_FIVE_FIFTY_BLOCKED` until a later snapshot clears the block."

        Design: Difficulty/compensating_invariant/five_fifty_block_set_and_cleared_by_later_passing_snapshot
        """
        reit, dom, pub = self._setup_reit_with_two_holders()
        create_posted_requirement(reit["id"], taxable_year=2026,
                                  taxable_income_cents=500_000,
                                  net_capital_gain_cents=0)
        dividend = create_approved_dividend(reit["id"], taxable_year=2026,
                                            amount_cents=10_000)

        h1 = setup_snapshot_with_positions(
            reit["id"], [(dom["id"], 600), (pub["id"], 400)],
            snapshot_date="2026-06-30", total_shares_outstanding=1000,
        )
        finalize_snapshot(h1["id"])

        blocked = api.declare_dividend_declaration(
            dividend["id"], compliance_officer_headers
        )
        validate_error(blocked, ApiErrorId.ERR_FIVE_FIFTY_BLOCKED)

        h2 = setup_snapshot_with_positions(
            reit["id"], [(dom["id"], 400), (pub["id"], 600)],
            snapshot_date="2026-12-31", total_shares_outstanding=1000,
        )
        finalize_snapshot(h2["id"])

        declared = declare_dividend(dividend["id"], officer_id="officer-1")
        assert declared["status"] == "DECLARED"


def test_finalize_empty_snapshot_rejected(api, compliance_officer_headers):
    """PRD §3.4: "a finalize request against an empty snapshot is rejected
    with `ERR_SNAPSHOT_EMPTY`, and one against a snapshot already `FINALIZED`
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/validations/finalize_empty_snapshot_rejected
    """
    reit = create_reit(legal_name="EMP REIT")
    snapshot = create_snapshot(reit["id"], snapshot_date="2026-06-30",
                               total_shares_outstanding=1000)
    resp = api.finalize_shareholder_snapshot(snapshot["id"],
                                             compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_SNAPSHOT_EMPTY)
    after = validate_success(
        api.get_shareholder_snapshot(snapshot["id"], compliance_officer_headers),
        200,
    )
    assert after["status"] == "DRAFT"


def test_unfreeze_restores_active_status(api, tax_director_headers):
    """PRD §3.4: "A `TaxDirector` may unfreeze a holder currently in `FROZEN`
    status, returning it to `ACTIVE` and incrementing its `version` by one.
    Unfreezing a holder who is not `FROZEN` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/cross_cutting_layers/unfreeze_restores_active_status
    """
    reit = create_reit(legal_name="UF REIT")
    dom = create_shareholder(reit["id"], "Dom", "INDIVIDUAL")
    minh = create_shareholder(reit["id"], "Min", "INDIVIDUAL")
    snapshot = setup_snapshot_with_positions(
        reit["id"], [(dom["id"], 97), (minh["id"], 3)],
        snapshot_date="2026-06-30", total_shares_outstanding=100,
    )
    finalize_snapshot(snapshot["id"])
    frozen = validate_success(
        api.get_shareholder(dom["id"], tax_director_headers), 200
    )
    assert frozen["status"] == "FROZEN"

    restored = validate_success(
        api.unfreeze_shareholder(dom["id"], tax_director_headers), 200
    )
    assert restored["status"] == "ACTIVE"

    resp = api.unfreeze_shareholder(minh["id"], tax_director_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_five_fifty_blocked_on_approve(api, board_director_headers):
    """PRD §3.4: "While `five_fifty_blocked` is true, dividend approval and
    dividend declaration are both rejected with `ERR_FIVE_FIFTY_BLOCKED` until
    a later snapshot clears the block."

    Design: Corner/errors/error_five_fifty_blocked_on_approve
    """
    reit = create_reit(legal_name="FFB REIT")
    dividend = create_dividend(reit["id"], taxable_year=2026,
                               amount_cents=10_000)
    finalize_failing_snapshot(reit["id"])
    assert get_reit(reit["id"])["five_fifty_blocked"] is True

    resp = api.approve_dividend_declaration(dividend["id"],
                                            board_director_headers)
    validate_error(resp, ApiErrorId.ERR_FIVE_FIFTY_BLOCKED)
