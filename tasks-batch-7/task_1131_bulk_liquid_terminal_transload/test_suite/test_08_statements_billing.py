"""Monthly statement aggregation: tiered throughput fee, minimum-commitment
shortfall, per-line rounding order, input-set filtering, and the close/invoice
lifecycle (PRD §2.10, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    certify_transfer,
    collect_sample,
    get_movement,
    record_sample_result,
    setup_certified_custody,
    setup_completed_movement,
    setup_lease_with_allocation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    CLERK,
    MANAGER,
    create_resource,
    create_statement,
    drive_movement_to_completed,
    get_movement_custody_transfer,
    get_tank,
    nominate_movement,
    schedule_movement,
    set_clock,
)


def _certify_movement(movement_id, specific_gravity=0.85):
    sample = collect_sample(movement_id, collector_id="qi-1")
    record_sample_result(sample["id"], lab_result="PASSED",
                         specific_gravity=specific_gravity, recorder_id="qi-2")
    custody = get_movement_custody_transfer(movement_id)
    return certify_transfer(custody["id"], certifier_id="tm-1")


def _close_and_get(api, statement_id):
    closed = validate_success(api.close_statement(statement_id, CLERK))
    assert closed["status"] == "CLOSED"
    return validate_success(api.get_monthly_statement(statement_id, CLERK))


class TestTieredThroughputFee:
    def _straddle_scenario(self):
        """One RECEIPT certified at exactly 60000 bbl in 2026-05 (gauges
        0 -> 60000 @60F, sample sg 0.85 == DIESEL standard); base fee 0.50."""
        bundle = setup_certified_custody(
            declared_volume_bbl=60000, opening_volume=0, closing_volume=60000,
            specific_gravity=0.85, capacity_bbl=200000, heel_bbl=100,
            allocated_bbl=100000, sample_type="ALL_LEVELS",
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T20:00:00Z",
            customer_name="Coastal Energy",
            lease_overrides={"committed_capacity_bbl": 200000,
                             "min_monthly_throughput_bbl": 55000,
                             "throughput_fee_per_bbl": 0.50,
                             "shortfall_fee_per_bbl": 0.50},
            statement_period="2026-05")
        set_clock("2026-06-01T00:00:00Z")
        return bundle

    def test_fee_straddles_tier_boundary(self, api):
        """PRD §3.8: "The first tier covers throughput from zero up to but not
        including 50,000 barrels at the lease's full `throughput_fee_per_bbl`
        rate. The second tier covers throughput from 50,000 up to but not
        including 200,000 barrels at 0.90 times the base rate. The third tier
        covers throughput at or beyond 200,000 barrels at 0.75 times the base
        rate." 60000 bbl at base 0.50: 50000*0.50 + 10000*0.45 == 29500.00 —
        not 30000.00 (no discount) nor 27000.00 (discount on all).

        Design: Difficulty/combinatorial_formula/tiered_throughput_fee_straddling
        """
        bundle = self._straddle_scenario()
        statement = _close_and_get(api, bundle["statement"]["id"])
        assert statement["total_throughput_bbl"] == 60000
        assert statement["throughput_fee_amount"] == pytest.approx(29500.00, abs=0.01), (
            f"marginal tier pricing must yield 29500.00, got {statement['throughput_fee_amount']}"
        )

    def test_straddle_month_has_no_shortfall(self, api):
        """PRD §3.8: "`shortfall_bbl` is the greater of zero and the lease's
        `min_monthly_throughput_bbl` minus `total_throughput_bbl`; throughput
        at or above the commitment yields no shortfall." 60000 >= 55000 yields
        shortfall 0; the statement closes CLOSED.

        Design: Difficulty/combinatorial_formula/tiered_throughput_fee_straddling
        """
        bundle = self._straddle_scenario()
        statement = _close_and_get(api, bundle["statement"]["id"])
        assert statement["shortfall_bbl"] == 0
        assert statement["shortfall_fee_amount"] == pytest.approx(0.00, abs=0.01)
        assert statement["status"] == "CLOSED"


class TestPerLineRoundingOrder:
    def _two_transfer_scenario(self):
        """Two RECEIPT movements in 2026-05, each declared 1000 and certified
        at 997 (sg == standard): shrinkage 3, allowed round_half_up(1000*0.002)
        == 2, excess 1, line charge round_half_up(55.555) == 55.56."""
        bundle = setup_lease_with_allocation(
            customer_name="Delta Petrochem", capacity_bbl=200000, heel_bbl=100,
            allocated_bbl=50000,
            lease_overrides={"committed_capacity_bbl": 100000,
                             "min_monthly_throughput_bbl": 100,
                             "loss_allowance_pct": 0.002,
                             "excess_loss_rate_per_bbl": 55.555})
        bundle["statement"] = create_statement(bundle["lease"]["id"], "2026-05")
        bundle["resource"] = create_resource("DOCK")
        specs = [
            ("2026-05-10", 0, 997),
            ("2026-05-11", 997, 1994),
        ]
        custodies = []
        for day, opening, closing in specs:
            movement = nominate_movement(
                bundle["lease"]["id"], bundle["tank"]["id"], declared_volume_bbl=1000,
                window_start=f"{day}T08:00:00Z", window_end=f"{day}T12:00:00Z")
            drive_movement_to_completed(
                movement["id"], bundle["resource"]["id"],
                opening_volume=opening, closing_volume=closing,
                arrive_clock=f"{day}T08:00:00Z", complete_clock=f"{day}T10:05:00Z",
                open_observed_at=f"{day}T08:05:00Z", close_observed_at=f"{day}T10:00:00Z")
            custodies.append(_certify_movement(movement["id"]))
        set_clock("2026-06-01T00:00:00Z")
        return bundle, custodies

    def test_round_per_line_then_sum(self, api):
        """PRD §2.10: "Across a monthly statement's excess-loss and demurrage
        lines, each line is already rounded to 2 decimal places at the moment
        it is computed — at certify time for excess loss, at complete time for
        demurrage — and the statement sums those pre-rounded line values
        exactly (round-per-line-then-sum). Summing unrounded raw line values
        and rounding the total is forbidden, because the two orders produce
        different cents."
        Two lines of 55.56 sum to 111.12; the forbidden sum-then-round of the
        raw 55.555 values would give 111.11.

        Design: Difficulty/combinatorial_formula/statement_per_line_rounding_order
        """
        bundle, _ = self._two_transfer_scenario()
        statement = _close_and_get(api, bundle["statement"]["id"])
        assert statement["total_excess_loss_bbl"] == 2
        assert statement["excess_loss_amount"] == pytest.approx(111.12, abs=0.01), (
            f"round-per-line-then-sum must yield 111.12, got {statement['excess_loss_amount']}"
        )
        assert abs(statement["excess_loss_amount"] - 111.11) > 0.005, (
            "111.11 is the forbidden sum-then-round result"
        )

    def test_each_line_charge_is_pre_rounded(self, api):
        """PRD §3.7: "`excess_loss_charge` is the excess loss barrels
        multiplied by the lease's `excess_loss_rate_per_bbl`, rounded half-up
        to 2 decimal places, with the rounding applied per custody transfer at
        certify time." Each 1-bbl excess line at 55.555/bbl reads back as
        55.56, and the statement total is the exact sum of those pre-rounded
        lines.

        Design: Difficulty/combinatorial_formula/statement_per_line_rounding_order
        """
        bundle, custodies = self._two_transfer_scenario()
        for custody in custodies:
            reread = validate_success(api.get_custody_transfer(custody["id"], MANAGER))
            assert reread["excess_loss_charge"] == pytest.approx(55.56, abs=0.01), (
                f"per-line charge must be 55.56, got {reread['excess_loss_charge']}"
            )
        statement = _close_and_get(api, bundle["statement"]["id"])
        assert statement["excess_loss_amount"] == pytest.approx(111.12, abs=0.01)


class TestShortfallBoundary:
    def _exact_commitment_scenario(self):
        """One RECEIPT certified at exactly 50000 bbl in 2026-05; minimum
        commitment 50000, base fee 0.50, shortfall fee 0.75."""
        bundle = setup_certified_custody(
            declared_volume_bbl=50000, opening_volume=0, closing_volume=50000,
            specific_gravity=0.85, capacity_bbl=200000, heel_bbl=100,
            allocated_bbl=100000,
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T20:00:00Z",
            customer_name="Summit Midstream",
            lease_overrides={"committed_capacity_bbl": 200000,
                             "min_monthly_throughput_bbl": 50000,
                             "throughput_fee_per_bbl": 0.50,
                             "shortfall_fee_per_bbl": 0.75},
            statement_period="2026-05")
        set_clock("2026-06-01T00:00:00Z")
        return bundle

    def test_zero_shortfall_at_exact_commitment(self, api):
        """PRD §3.8: "`shortfall_bbl` is the greater of zero and the lease's
        `min_monthly_throughput_bbl` minus `total_throughput_bbl`; throughput
        at or above the commitment yields no shortfall."
        total_throughput_bbl exactly == 50000 == min_monthly_throughput_bbl:
        shortfall_bbl == 0 and shortfall_fee_amount == 0.00.

        Design: Difficulty/boundary_precision_check/shortfall_zero_at_exact_minimum_commitment
        """
        bundle = self._exact_commitment_scenario()
        statement = _close_and_get(api, bundle["statement"]["id"])
        assert statement["total_throughput_bbl"] == 50000
        assert statement["shortfall_bbl"] == 0
        assert statement["shortfall_fee_amount"] == pytest.approx(0.00, abs=0.01)

    def test_exact_cap_prices_entirely_in_tier_one(self, api):
        """PRD §3.8: "Because the tiers are half-open, a month landing on
        exactly 50,000 barrels prices every barrel in the first tier."
        50000 * 0.50 == 25000.00, with no tier-2 discount leaking in.

        Design: Difficulty/boundary_precision_check/shortfall_zero_at_exact_minimum_commitment
        """
        bundle = self._exact_commitment_scenario()
        statement = _close_and_get(api, bundle["statement"]["id"])
        assert statement["throughput_fee_amount"] == pytest.approx(25000.00, abs=0.01)
        assert statement["status"] == "CLOSED"


class TestSingleTier:
    def test_sub_cap_volume_prices_in_tier_one(self, api):
        """PRD §3.8: "The first tier covers throughput from zero up to but not
        including 50,000 barrels at the lease's full `throughput_fee_per_bbl`
        rate." 40000 certified barrels at base 0.50 price entirely in tier 1:
        fee == 20000.00 exactly; and 40000 >= 10000 commitment yields no
        shortfall.

        Design: Corner/calculations/throughput_fee_exact_single_tier
        """
        bundle = setup_certified_custody(
            declared_volume_bbl=40000, opening_volume=0, closing_volume=40000,
            specific_gravity=0.85, capacity_bbl=200000, heel_bbl=100,
            allocated_bbl=100000,
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T20:00:00Z",
            customer_name="Single Tier Co",
            lease_overrides={"committed_capacity_bbl": 100000,
                             "min_monthly_throughput_bbl": 10000,
                             "throughput_fee_per_bbl": 0.50,
                             "shortfall_fee_per_bbl": 0.75},
            statement_period="2026-05")
        set_clock("2026-06-01T00:00:00Z")
        statement = _close_and_get(api, bundle["statement"]["id"])
        assert statement["total_throughput_bbl"] == 40000
        assert statement["throughput_fee_amount"] == pytest.approx(20000.00, abs=0.01)
        assert statement["shortfall_bbl"] == 0


class TestStatementInputSet:
    def test_provisional_and_void_excluded(self, api):
        """PRD §3.8: "Throughput and loss figures draw from custody transfers
        in `CERTIFIED` or `DISPUTED` status whose movement's
        `actual_complete_at` falls within the period; `PROVISIONAL` and `VOID`
        transfers are excluded."
        m1 certified 1000; m2 completed but never certified (PROVISIONAL);
        m3 certified 3000 then voided. The closed statement reads
        total_throughput_bbl == 1000 and fee == 500.00, and the tank's
        certified inventory reads 1000 (the void reversed m3's +3000).

        Design: Corner/calculations/statement_excludes_provisional_and_void_volumes
        """
        bundle = setup_lease_with_allocation(
            customer_name="Filter Co", allocated_bbl=50000,
            lease_overrides={"min_monthly_throughput_bbl": 10,
                             "throughput_fee_per_bbl": 0.50,
                             "shortfall_fee_per_bbl": 0.75})
        bundle["statement"] = create_statement(bundle["lease"]["id"], "2026-05")
        bundle["resource"] = create_resource("DOCK")

        def run_movement(day, declared, opening, closing, certify=False, void=False):
            movement = nominate_movement(
                bundle["lease"]["id"], bundle["tank"]["id"], declared_volume_bbl=declared,
                window_start=f"{day}T08:00:00Z", window_end=f"{day}T12:00:00Z")
            drive_movement_to_completed(
                movement["id"], bundle["resource"]["id"],
                opening_volume=opening, closing_volume=closing,
                arrive_clock=f"{day}T08:00:00Z", complete_clock=f"{day}T10:05:00Z",
                open_observed_at=f"{day}T08:05:00Z", close_observed_at=f"{day}T10:00:00Z")
            custody = get_movement_custody_transfer(movement["id"])
            if certify:
                custody = _certify_movement(movement["id"])
            if void:
                validate_success(api.void_custody_transfer(custody["id"], MANAGER))
            return custody

        run_movement("2026-05-10", 1000, 0, 1000, certify=True)
        run_movement("2026-05-11", 2000, 1000, 3000)                     # stays PROVISIONAL
        run_movement("2026-05-12", 3000, 3000, 6000, certify=True, void=True)
        set_clock("2026-06-01T00:00:00Z")
        statement = _close_and_get(api, bundle["statement"]["id"])
        assert statement["total_throughput_bbl"] == 1000, (
            f"PROVISIONAL and VOID transfers must be excluded, got {statement['total_throughput_bbl']}"
        )
        assert statement["throughput_fee_amount"] == pytest.approx(500.00, abs=0.01)
        tank = get_tank(bundle["tank"]["id"])
        assert tank["current_inventory_bbl"] == 1000, (
            f"void must reverse m3's +3000 from certified inventory, got {tank['current_inventory_bbl']}"
        )


class TestStatementLifecycle:
    def test_close_marks_period_movements_accrued(self, api):
        """PRD §3.8: "Closing performs a full deterministic recompute over the
        pinned input set, transitions the statement from `OPEN` to `CLOSED`,
        and sweeps every `COMPLETED` movement of the lease completing in the
        period from `UNBILLED` to `ACCRUED` in `billing_status`." The billing
        dimension flips while the operations dimension stays COMPLETED.

        Design: Corner/state_machines/statement_close_marks_movements_accrued
        """
        bundle = setup_completed_movement(
            customer_name="Accrual Co",
            lease_overrides={"shortfall_fee_per_bbl": 0.75},
            statement_period="2026-05")
        assert bundle["movement"]["billing_status"] == "UNBILLED"
        set_clock("2026-06-01T00:00:00Z")
        closed = validate_success(api.close_statement(bundle["statement"]["id"], CLERK))
        assert closed["status"] == "CLOSED"
        movement = get_movement(bundle["movement"]["id"])
        assert movement["billing_status"] == "ACCRUED"
        assert movement["status"] == "COMPLETED", "parallel dimensions evolve independently"

    def test_close_before_period_end_rejected(self, api):
        """PRD §3.8: "A `BillingClerk` closes the statement once the logical
        clock has reached `period_end_exclusive`; an early close is rejected
        with `ERR_STATEMENT_PERIOD_NOT_ENDED` (HTTP 409)."

        Design: Corner/validations/statement_close_before_period_end_rejected
        """
        bundle = setup_lease_with_allocation(customer_name="Early Close Co")
        statement = create_statement(bundle["lease"]["id"], "2026-05")
        set_clock("2026-05-15T00:00:00Z")
        resp = api.close_statement(statement["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_NOT_ENDED)
        assert resp.status_code == 409
        after = validate_success(api.get_monthly_statement(statement["id"], CLERK))
        assert after["status"] == "OPEN"

    def test_duplicate_period_rejected(self, api):
        """PRD §3.8: "A `BillingClerk` creates a `MonthlyStatement` for a lease
        by supplying a `period` in `YYYY-MM` format; the period is unique per
        lease, and a duplicate is rejected with `ERR_STATEMENT_EXISTS`
        (HTTP 409)."

        Design: Corner/validations/duplicate_statement_period_rejected
        """
        bundle = setup_lease_with_allocation(customer_name="Dupe Stmt Co")
        create_statement(bundle["lease"]["id"], "2026-05")
        resp = api.create_monthly_statement(bundle["lease"]["id"], {"period": "2026-05"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_EXISTS)
        assert resp.status_code == 409
