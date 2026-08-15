"""Provision lifecycle: the lock gate, mark-returns-filed, close, and the
dual-variant effective tax rate reconciliation.
"""
from test_helpers import (
    ApiErrorId,
    approve_zero_allowance,
    create_reviewed_difference,
    file_ready_filing,
    get_tax_year,
    set_logical_clock,
    setup_dual_variant_etr_scenario,
    setup_locked_year_with_filing,
    setup_open_year_with_jurisdiction,
    validate_error,
    validate_success,
)


class TestProvisionLockGate:
    def test_lock_provision_rejected_with_unresolved_items(
            self, api, tax_manager_headers, tax_director_headers):
        """PRD §3.8: "Locking the provision (`OPEN → PROVISION_LOCKED`) is
        permitted only when every difference of the year is terminal —
        `LOCKED` or `REJECTED` — when some valuation allowance of the year is
        `APPROVED`, and when no position of the year is still `IDENTIFIED`; a
        breach of any leg is `ERR_UNRESOLVED_PROVISION_ITEMS`."

        Design: Difficulty/cross_entity_state_dependency/provision_lock_blocked_by_unlocked_differences
        """
        ty, jur = setup_open_year_with_jurisdiction()
        # A difference stuck in REVIEWED (non-terminal) blocks the lock.
        create_reviewed_difference(
            ty["id"], jur["id"], book_amount_cents=2000000,
            tax_amount_cents=0, difference_type="PERMANENT",
            description="meals 50pct limitation")
        approve_zero_allowance(ty["id"])

        res = api.lock_provision(ty["id"], tax_director_headers)
        validate_error(res, ApiErrorId.ERR_UNRESOLVED_PROVISION_ITEMS,
                       expected_status=422)

        year = get_tax_year(ty["id"])
        assert year["status"] == "OPEN"

    def test_lock_provision_succeeds_once_differences_terminal(
            self, api, tax_manager_headers, tax_director_headers):
        """PRD §3.8: "Locking the provision (`OPEN → PROVISION_LOCKED`) is
        permitted only when every difference of the year is terminal —
        `LOCKED` or `REJECTED` — when some valuation allowance of the year is
        `APPROVED`, and when no position of the year is still `IDENTIFIED`; a
        breach of any leg is `ERR_UNRESOLVED_PROVISION_ITEMS`."

        Design: Difficulty/cross_entity_state_dependency/provision_lock_blocked_by_unlocked_differences
        """
        ty, jur = setup_open_year_with_jurisdiction()
        diff = create_reviewed_difference(
            ty["id"], jur["id"], book_amount_cents=2000000,
            tax_amount_cents=0, difference_type="PERMANENT",
            description="meals 50pct limitation")
        approve_zero_allowance(ty["id"])

        res = api.lock_provision(ty["id"], tax_director_headers)
        validate_error(res, ApiErrorId.ERR_UNRESOLVED_PROVISION_ITEMS,
                       expected_status=422)

        # Transition the blocking child to terminal, then the gate passes.
        validate_success(api.lock_difference(diff["id"],
                                             tax_manager_headers), 200)
        locked = validate_success(api.lock_provision(ty["id"],
                                                     tax_director_headers),
                                  200)
        assert locked["status"] == "PROVISION_LOCKED"


class TestMarkReturnsFiled:
    def test_unfiled_returns_block_mark_returns_filed(
            self, api, tax_director_headers):
        """PRD §3.8: "Marking returns filed (`PROVISION_LOCKED →
        RETURNS_FILED`) requires every filing of the year to be `FILED` or
        `ACCEPTED`, otherwise `ERR_UNFILED_RETURNS`, and increments the
        version."

        Design: Corner/validations/unfiled_returns_block_mark_returns_filed
        """
        scenario = setup_locked_year_with_filing()  # filing stays PENDING
        ty = scenario["tax_year"]
        assert ty["status"] == "PROVISION_LOCKED"

        res = api.mark_returns_filed(ty["id"], tax_director_headers)
        validate_error(res, ApiErrorId.ERR_UNFILED_RETURNS,
                       expected_status=422)

        year = get_tax_year(ty["id"])
        assert year["status"] == "PROVISION_LOCKED"


class TestFullLifecycle:
    def test_full_year_lifecycle_to_closed(self, api, tax_manager_headers,
                                           tax_director_headers):
        """PRD §3.8: "Marking returns filed (`PROVISION_LOCKED →
        RETURNS_FILED`) requires every filing of the year to be `FILED` or
        `ACCEPTED`, otherwise `ERR_UNFILED_RETURNS`, and increments the
        version. Closing the year (`RETURNS_FILED → CLOSED`, terminal)
        requires every audit case of the year to be `CLOSED_AGREED` or
        `CLOSED_NO_CHANGE`, and every notice either joined via its
        `audit_case_id` to an audit case of the year or standing alone in a
        jurisdiction that has a filing in the year to be `RESOLVED`; the
        version increments again."
        PRD §3.7: "From `FILED`, a `TaxManager` accepts the return
        (`ACCEPTED`, terminal) or rejects it."

        Design: Corner/state_machines/full_year_lifecycle_to_closed
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        scenario = setup_locked_year_with_filing(mark_ready_liability=21000000)
        ty = scenario["tax_year"]
        filing = scenario["filing"]

        filed = file_ready_filing(filing["id"], ty["id"])
        # estimate 21,000,000 == filed liability, so the RTP delta is 0
        year = get_tax_year(ty["id"])
        assert year["return_to_provision_adjustment_cents"] == 0

        accepted = validate_success(
            api.accept_filing(filed["id"], tax_manager_headers), 200)
        assert accepted["status"] == "ACCEPTED"

        filed_year = validate_success(
            api.mark_returns_filed(ty["id"], tax_director_headers), 200)
        assert filed_year["status"] == "RETURNS_FILED"

        # No audits and no notices: the close preconditions hold vacuously.
        closed = validate_success(api.close_tax_year(ty["id"],
                                                     tax_director_headers),
                                  200)
        assert closed["status"] == "CLOSED"


class TestDualVariantEtr:
    def test_forecast_etr_consumes_provision_reserve_and_allowance(
            self, api):
        """PRD §3.6: "The forecast variant — the in-year planning view, always
        maintained — sets forecast total tax to `current_provision_cents` plus
        `deferred_expense_cents` plus `utp_liability_cents` plus
        `valuation_allowance_cents`, then `forecast_etr_bp` is that total
        multiplied by 10000 and divided by `pretax_book_income_cents`, rounded
        half up."

        Design: Difficulty/dual_variant_calc/etr_forecast_vs_actual_divergence
        """
        scenario = setup_dual_variant_etr_scenario()
        year = get_tax_year(scenario["tax_year"]["id"])

        # Pinned stack order: CA 2,254,200 first, FED 20,946,618 second.
        assert year["current_provision_cents"] == 23200818
        # (23,200,818 - 630,000 + 1,000,000 + 320,000) * 10000 / 100,000,000
        assert year["forecast_etr_bp"] == 2389

    def test_actual_etr_uses_filed_liabilities_and_diverges(
            self, api):
        """PRD §3.6: "The actual variant — the as-filed view, meaningful once
        filings exist — replaces the current-provision estimate and the UTP
        reserve with the sum of `return_tax_liability_cents` across the year's
        filings in `FILED` or `ACCEPTED`: actual total tax is that sum plus
        `deferred_expense_cents` plus `valuation_allowance_cents`, and
        `actual_etr_bp` is that total multiplied by 10000 and divided by
        `pretax_book_income_cents`, rounded half up. Identical underlying data
        yields a different rate whenever filed liabilities diverge from the
        estimate and reserve."
        PRD §3.7: "hop 1 recomputes the year's
        `return_to_provision_adjustment_cents` as the sum, across the year's
        filings in `FILED` or `ACCEPTED`, of each filing's
        `return_tax_liability_cents` minus its `estimated_liability_cents`"

        Design: Difficulty/dual_variant_calc/etr_forecast_vs_actual_divergence
        """
        scenario = setup_dual_variant_etr_scenario()
        year = get_tax_year(scenario["tax_year"]["id"])

        # (20,800,000 + 2,300,000 - 630,000 + 320,000) * 10000 / 100,000,000
        assert year["actual_etr_bp"] == 2279
        # (20,800,000 - 20,946,618) + (2,300,000 - 2,254,200)
        assert year["return_to_provision_adjustment_cents"] == -100818
        assert year["forecast_etr_bp"] != year["actual_etr_bp"], \
            "the two variants diverge on identical underlying data"
