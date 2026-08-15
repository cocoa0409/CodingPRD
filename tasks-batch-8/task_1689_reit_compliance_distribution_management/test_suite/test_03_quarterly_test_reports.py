"""Quarterly asset/income test reports: ratios, boundaries, lock semantics,
and the compliance kill-switch (PRD §2.11, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_asset_test_report,
    assert_income_test_report,
    create_approved_dividend,
    create_asset_holding,
    create_asset_test_report,
    create_income_item,
    create_income_test_report,
    create_posted_requirement,
    create_quarter,
    create_reit,
    current_reit_version,
    get_reit,
    lock_asset_test_report,
    lock_income_test_report,
    validate_error,
    validate_success,
)


class TestAssetTestBoundary:
    def test_exactly_75_percent_locks_passed(
            self, api, compliance_officer_headers):
        """PRD §2.5: "Threshold comparisons are inclusive at the stated
        boundary unless otherwise noted: a qualifying percentage of exactly
        75.0000 passes the 75% test".
        PRD §3.3: "If both ratios pass, the report transitions `DRAFT →
        LOCKED`, the four computed values are persisted, the parent quarter
        transitions to `LOCKED`, and both the report's and the quarter's
        `version` increment by one."

        Design: Difficulty/boundary_precision_check/asset_test_exactly_75_percent_passes
        """
        reit = create_reit(legal_name="BND REIT")
        quarter = create_quarter(reit["id"])
        create_asset_holding(reit["id"], asset_name="Tower",
                             asset_class="REAL_ESTATE",
                             value_cents=75_000_000)
        create_asset_holding(reit["id"], asset_name="Paintings",
                             asset_class="NON_QUALIFYING",
                             value_cents=25_000_000)
        report = create_asset_test_report(reit["id"], quarter["id"])

        locked = validate_success(
            api.lock_asset_test_report(report["id"], compliance_officer_headers),
            200,
        )
        assert_asset_test_report(locked)
        assert locked["qualifying_75_pct"] == pytest.approx(75.0, abs=1e-9)
        assert locked["test_75_passed"] is True
        assert locked["trs_test_passed"] is True
        assert locked["status"] == "LOCKED"
        assert get_reit(reit["id"])["status"] == "ACTIVE"
        quarter_after = validate_success(
            api.get_quarter(quarter["id"], compliance_officer_headers), 200
        )
        assert quarter_after["status"] == "LOCKED"

    def test_74_9999_percent_breaches(self, api, compliance_officer_headers):
        """PRD §3.3: "The `test_75_passed` boolean is true when
        `qualifying_75_pct` is at least 75.0000 (the boundary is inclusive)."
        PRD §2.5: "Anything strictly outside the boundary fails."

        Design: Difficulty/boundary_precision_check/asset_test_exactly_75_percent_passes
        """
        reit = create_reit(legal_name="BND REIT 2")
        quarter = create_quarter(reit["id"])
        create_asset_holding(reit["id"], asset_name="Tower",
                             asset_class="REAL_ESTATE",
                             value_cents=74_999_900)
        create_asset_holding(reit["id"], asset_name="Paintings",
                             asset_class="NON_QUALIFYING",
                             value_cents=25_000_100)
        report = create_asset_test_report(reit["id"], quarter["id"])

        locked = validate_success(
            api.lock_asset_test_report(report["id"], compliance_officer_headers),
            200,
        )
        assert_asset_test_report(locked)
        assert locked["qualifying_75_pct"] == pytest.approx(74.9999, abs=1e-9)
        assert locked["test_75_passed"] is False
        assert locked["status"] == "BREACHED"
        assert get_reit(reit["id"])["status"] == "SUSPENDED"


def test_income_test_dual_ratios_at_boundaries(api, compliance_officer_headers):
    """PRD §3.3: "The `qualifying_75_pct` is the percentage of that total
    attributable to `RENTS`; the `qualifying_95_pct` is the percentage
    attributable to `RENTS` plus `MORTGAGE_INTEREST`."
    PRD §3.3: "The `test_75_passed` boolean requires at least 75.0000;
    `test_95_passed` requires at least 95.0000."

    Design: Corner/calculations/income_test_dual_ratios_at_boundaries
    """
    reit = create_reit(legal_name="C1 REIT")
    quarter = create_quarter(reit["id"])
    create_income_item(reit["id"], quarter["id"], income_class="RENTS",
                       amount_cents=750_000, accrued_at="2026-01-15")
    create_income_item(reit["id"], quarter["id"],
                       income_class="MORTGAGE_INTEREST",
                       amount_cents=200_000, accrued_at="2026-02-15")
    create_income_item(reit["id"], quarter["id"], income_class="NON_QUALIFYING",
                       amount_cents=50_000, accrued_at="2026-03-15")
    report = create_income_test_report(reit["id"], quarter["id"])

    locked = validate_success(
        api.lock_income_test_report(report["id"], compliance_officer_headers),
        200,
    )
    assert_income_test_report(locked)
    assert locked["qualifying_75_pct"] == pytest.approx(75.0, abs=1e-9)
    assert locked["qualifying_95_pct"] == pytest.approx(95.0, abs=1e-9)
    assert locked["test_75_passed"] is True
    assert locked["test_95_passed"] is True
    assert locked["status"] == "LOCKED"


def test_income_test_empty_quarter_fails_both(api, compliance_officer_headers):
    """PRD §3.3: "The empty-set rule applies here too: zero income yields
    0.0000 on both ratios and fails both tests."
    PRD §3.3: "fail transitions `DRAFT → BREACHED` and fires the same
    kill-switch."

    Design: Corner/calculations/income_test_empty_quarter_fails_both
    """
    reit = create_reit(legal_name="C2 REIT")
    quarter = create_quarter(reit["id"])
    report = create_income_test_report(reit["id"], quarter["id"])

    locked = validate_success(
        api.lock_income_test_report(report["id"], compliance_officer_headers),
        200,
    )
    assert_income_test_report(locked)
    assert locked["qualifying_75_pct"] == pytest.approx(0.0, abs=1e-9)
    assert locked["qualifying_95_pct"] == pytest.approx(0.0, abs=1e-9)
    assert locked["test_75_passed"] is False
    assert locked["test_95_passed"] is False
    assert locked["status"] == "BREACHED"
    assert get_reit(reit["id"])["status"] == "SUSPENDED"


def test_trs_concentration_boundary_pair(api, compliance_officer_headers):
    """PRD §3.3: "The `trs_test_passed` boolean is true when
    `trs_concentration_pct` is at most 20.0000 — again inclusive, so a
    concentration of 20.0001 breaches."

    Design: Corner/calculations/trs_concentration_exactly_20_passes_and_20_0001_breaches
    """
    # RA: exactly 20.0000% TRS-held -> passes.
    reit_a = create_reit(legal_name="TRA")
    quarter_a = create_quarter(reit_a["id"])
    create_asset_holding(reit_a["id"], asset_name="TRS Tower",
                         asset_class="REAL_ESTATE", held_by_trs=True,
                         value_cents=20_000_000)
    create_asset_holding(reit_a["id"], asset_name="Direct Tower",
                         asset_class="REAL_ESTATE", held_by_trs=False,
                         value_cents=80_000_000)
    report_a = create_asset_test_report(reit_a["id"], quarter_a["id"])

    # RB: 20.0001% TRS-held -> breaches.
    reit_b = create_reit(legal_name="TRB")
    quarter_b = create_quarter(reit_b["id"])
    create_asset_holding(reit_b["id"], asset_name="TRS Annex",
                         asset_class="REAL_ESTATE", held_by_trs=True,
                         value_cents=20_000_100)
    create_asset_holding(reit_b["id"], asset_name="Direct Annex",
                         asset_class="REAL_ESTATE", held_by_trs=False,
                         value_cents=79_999_900)
    report_b = create_asset_test_report(reit_b["id"], quarter_b["id"])

    locked_a = validate_success(
        api.lock_asset_test_report(report_a["id"], compliance_officer_headers),
        200,
    )
    assert locked_a["trs_concentration_pct"] == pytest.approx(20.0, abs=1e-9)
    assert locked_a["trs_test_passed"] is True
    assert locked_a["status"] == "LOCKED"

    locked_b = validate_success(
        api.lock_asset_test_report(report_b["id"], compliance_officer_headers),
        200,
    )
    assert locked_b["trs_concentration_pct"] == pytest.approx(20.0001, abs=1e-9)
    assert locked_b["trs_test_passed"] is False
    assert locked_b["status"] == "BREACHED"
    assert get_reit(reit_b["id"])["status"] == "SUSPENDED"


def test_lock_locked_asset_report_returns_invalid_state(
        api, compliance_officer_headers):
    """PRD §3.3: "A lock request against a report not in `DRAFT` is rejected
    with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/lock_locked_asset_report_returns_invalid_state
    """
    reit = create_reit(legal_name="SM1 REIT")
    quarter = create_quarter(reit["id"])
    create_asset_holding(reit["id"], asset_name="HQ",
                         asset_class="REAL_ESTATE", value_cents=100_000_000)
    report = create_asset_test_report(reit["id"], quarter["id"])
    first = lock_asset_test_report(report["id"])
    assert first["status"] == "LOCKED"

    resp = api.lock_asset_test_report(report["id"], compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_reit(reit["id"])["status"] == "ACTIVE"


def test_breached_report_is_terminal(api, compliance_officer_headers):
    """PRD §3.3: "A lock request against a report not in `DRAFT` is rejected
    with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/breached_report_is_terminal
    """
    reit = create_reit(legal_name="SM2 REIT")
    quarter = create_quarter(reit["id"])
    create_asset_holding(reit["id"], asset_name="Small lot",
                         asset_class="REAL_ESTATE", value_cents=10_000_000)
    create_asset_holding(reit["id"], asset_name="Bullion",
                         asset_class="NON_QUALIFYING", value_cents=90_000_000)
    report = create_asset_test_report(reit["id"], quarter["id"])
    first = lock_asset_test_report(report["id"])
    assert first["status"] == "BREACHED"

    resp = api.lock_asset_test_report(report["id"], compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_second_asset_test_report_same_quarter_rejected(
        api, compliance_officer_headers):
    """PRD §3.3: "Each quarter supports at most one report of each type; a
    second request of the same type for the same quarter yields
    `ERR_DUPLICATE`."

    Design: Corner/validations/second_asset_test_report_same_quarter_rejected
    """
    reit = create_reit(legal_name="DUP2")
    quarter = create_quarter(reit["id"])
    first = api.create_asset_test_report(
        {"reit_id": reit["id"], "quarter_id": quarter["id"]},
        compliance_officer_headers,
    )
    validate_success(first, 201)
    resp = api.create_asset_test_report(
        {"reit_id": reit["id"], "quarter_id": quarter["id"]},
        compliance_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestIncomeItemRequiresQuarterOpen:
    def test_create_income_item_on_locked_quarter_rejected(
            self, api, compliance_officer_headers):
        """PRD §3.2: "Income items may only be created against a quarter that
        is still `OPEN`, and an existing item may be amended (its
        `amount_cents` or `income_class` updated) only while its quarter
        remains `OPEN`; either operation against a locked quarter is rejected
        with `ERR_QUARTER_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/income_item_requires_quarter_open
        """
        reit = create_reit(legal_name="X1 REIT")
        quarter = create_quarter(reit["id"])
        create_asset_holding(reit["id"], asset_name="Mall",
                             asset_class="REAL_ESTATE", value_cents=100_000_000)
        report = create_asset_test_report(reit["id"], quarter["id"])
        lock_asset_test_report(report["id"])

        resp = api.create_income_item(
            {
                "reit_id": reit["id"],
                "quarter_id": quarter["id"],
                "income_class": "RENTS",
                "amount_cents": 5000,
                "source_is_trs": False,
                "accrued_at": "2026-02-01",
            },
            compliance_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_QUARTER_LOCKED)

    def test_amend_income_item_on_locked_quarter_rejected(
            self, api, compliance_officer_headers):
        """PRD §3.2: "Income items may only be created against a quarter that
        is still `OPEN`, and an existing item may be amended (its
        `amount_cents` or `income_class` updated) only while its quarter
        remains `OPEN`; either operation against a locked quarter is rejected
        with `ERR_QUARTER_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/income_item_requires_quarter_open
        """
        reit = create_reit(legal_name="X1 REIT 2")
        quarter = create_quarter(reit["id"])
        item = create_income_item(reit["id"], quarter["id"],
                                  income_class="RENTS", amount_cents=5000)
        create_asset_holding(reit["id"], asset_name="Mall",
                             asset_class="REAL_ESTATE", value_cents=100_000_000)
        report = create_asset_test_report(reit["id"], quarter["id"])
        lock_asset_test_report(report["id"])

        resp = api.update_income_item(item["id"], {"amount_cents": 6000},
                                      compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_QUARTER_LOCKED)


class TestAssetBreachKillSwitch:
    """Depth-3 cascade of PRD §2.11: breach -> suspend -> auto-void."""

    def _setup_suspended_reit_with_approved_dividend(self):
        reit = create_reit(legal_name="CASC REIT")
        quarter = create_quarter(reit["id"])
        create_asset_holding(reit["id"], asset_name="Office Park",
                             asset_class="REAL_ESTATE",
                             acquisition_date="2024-06-01",
                             value_cents=74_000_000)
        create_asset_holding(reit["id"], asset_name="Art Collection",
                             asset_class="NON_QUALIFYING",
                             acquisition_date="2024-06-01",
                             value_cents=26_000_000)
        create_posted_requirement(reit["id"], taxable_year=2026,
                                  taxable_income_cents=500_000,
                                  net_capital_gain_cents=0)
        dividend = create_approved_dividend(
            reit["id"], taxable_year=2026, amount_cents=50_000,
            declaration_date="2026-02-01", record_date="2026-02-10",
            payable_date="2026-02-20",
        )
        report = create_asset_test_report(reit["id"], quarter["id"])
        return reit, quarter, dividend, report

    def test_breach_suspends_reit_and_locks_quarter(
            self, api, compliance_officer_headers):
        """PRD §2.11: "When an asset test report or income test report locks
        with a failing ratio, the consequence is not local. The report
        transitions to `BREACHED`, its quarter locks, the parent REIT
        transitions to `SUSPENDED`".

        Design: Difficulty/transitive_cascade/asset_test_breach_suspends_reit_and_voids_dividends
        """
        reit, quarter, _dividend, report = (
            self._setup_suspended_reit_with_approved_dividend()
        )
        locked = validate_success(
            api.lock_asset_test_report(report["id"], compliance_officer_headers),
            200,
        )
        assert locked["status"] == "BREACHED"
        assert locked["qualifying_75_pct"] == pytest.approx(74.0, abs=1e-9)
        assert get_reit(reit["id"])["status"] == "SUSPENDED"
        quarter_after = validate_success(
            api.get_quarter(quarter["id"], compliance_officer_headers), 200
        )
        assert quarter_after["status"] == "LOCKED"

    def test_breach_auto_voids_approved_dividend(
            self, api, compliance_officer_headers):
        """PRD §2.11: "every `DividendDeclaration` of that REIT still sitting
        in `PENDING_APPROVAL` or `APPROVED` is auto-voided in the same sweep.
        Declarations already in `DECLARED` or `PAID` are left untouched; the
        kill-switch only cancels dividends that have not yet been executed."

        Design: Difficulty/transitive_cascade/asset_test_breach_suspends_reit_and_voids_dividends
        """
        reit, _quarter, dividend, report = (
            self._setup_suspended_reit_with_approved_dividend()
        )
        validate_success(
            api.lock_asset_test_report(report["id"], compliance_officer_headers),
            200,
        )
        dividend_after = validate_success(
            api.get_dividend_declaration(dividend["id"],
                                         compliance_officer_headers),
            200,
        )
        assert dividend_after["status"] == "VOID"


def test_suspended_reit_blocks_dividend_create(api, compliance_officer_headers):
    """PRD §3.6: "The REIT must be `ACTIVE` — drafting against a suspended
    REIT yields `ERR_REIT_SUSPENDED`."

    Design: Corner/validations/suspended_reit_blocks_dividend_create
    """
    reit = create_reit(legal_name="SUS REIT")
    quarter = create_quarter(reit["id"])
    create_income_item(reit["id"], quarter["id"], income_class="NON_QUALIFYING",
                       amount_cents=100_000, accrued_at="2026-02-01")
    report = create_income_test_report(reit["id"], quarter["id"])
    lock_income_test_report(report["id"])
    assert get_reit(reit["id"])["status"] == "SUSPENDED"

    resp = api.create_dividend_declaration(
        {
            "reit_id": reit["id"],
            "taxable_year": 2026,
            "amount_cents": 1000,
            "declaration_date": "2026-04-01",
            "record_date": "2026-04-10",
            "payable_date": "2026-04-20",
            "expected_reit_version": current_reit_version(reit["id"]),
        },
        compliance_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REIT_SUSPENDED)
