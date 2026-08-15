"""Charge ledger, payroll deduction caps, voids, and delinquency aging."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_statement_invariants,
    create_authorization,
    create_work_order,
    set_clock,
    setup_active_tenancy,
    setup_pending_tenancy,
    validate_error,
    validate_paginated,
    validate_success,
    verify_work_order,
    walk_work_order_to_completed,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["operator_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


def _post_entry(api, payload):
    return api.create_charge_ledger_entry(payload, ADMIN)


def _statement(api, tenancy_id):
    return validate_success(api.get_tenancy_statement(tenancy_id, ADMIN))


def _pay(api, tenancy_id, gross_wages_cents, start="2026-08-01",
         end="2026-08-15"):
    return api.create_tenancy_payment(
        tenancy_id, {"gross_wages_cents": gross_wages_cents,
                     "pay_period_start": start, "pay_period_end": end},
        INTAKE)


class TestUtilityOveragePricing:
    """Difficulty instance: per-line rounding then sum (126, not 125)."""

    def _setup(self, api):
        return setup_active_tenancy(site_name="Site U",
                                    household_name="Fam U")

    def test_utility_overage_rounds_per_line_then_sums(
            self, api, operator_admin_headers):
        """PRD §3.5: "the line total is rounded half up to whole cents, and
        only then are the already-rounded lines summed into the entry's
        `amount_cents`. Summing first and rounding once is explicitly not the
        rule: two lines of five overage units each bill 126 cents in total,
        not 125."

        Design: Difficulty/combinatorial_formula/utility_overage_per_line_rounding_order
        """
        ctx = self._setup(api)
        entry = validate_success(_post_entry(api, {
            "tenancy_id": ctx["tenancy"]["id"],
            "entry_type": "UTILITY_OVERAGE",
            "usage_lines": [
                {"utility_type": "ELECTRIC", "usage_units": 205},
                {"utility_type": "GAS", "usage_units": 105},
            ]}), expected_status=201)
        # ELECTRIC overage 5 -> 62.5 -> 63; GAS overage 5 -> 62.5 -> 63.
        assert entry["amount_cents"] == 126
        assert entry["amount_cents"] != 125, (
            "Sum-then-round (62.5 + 62.5 = 125) is explicitly not the rule")

    def test_utility_overage_buckets_into_utility_balance(
            self, api, operator_admin_headers):
        """PRD §3.5: "The utility bucket, `utility_bucket_balance_cents`, nets
        `UTILITY_OVERAGE` debits against the utility overflow of
        rent-and-utilities payments. ... The tenancy's `balance_cents` is the
        sum of the three."

        Design: Difficulty/combinatorial_formula/utility_overage_per_line_rounding_order
        """
        ctx = self._setup(api)
        entry = validate_success(_post_entry(api, {
            "tenancy_id": ctx["tenancy"]["id"],
            "entry_type": "UTILITY_OVERAGE",
            "usage_lines": [
                {"utility_type": "ELECTRIC", "usage_units": 205},
                {"utility_type": "GAS", "usage_units": 105},
            ]}), expected_status=201)
        assert entry["amount_cents"] == 126, "Setup failed"

        statement = _statement(api, ctx["tenancy"]["id"])
        assert statement["utility_bucket_balance_cents"] == 126
        assert statement["balance_cents"] == 61094, "60968 rent + 126 utility"
        assert_statement_invariants(statement)

    def test_utility_tier_straddle_water(self, api, operator_admin_headers):
        """PRD §3.5: "Each line is priced independently: consumption beyond
        the allowance — 200 units for `ELECTRIC`, 100 for `GAS`, 150 for
        `WATER` — is the overage; the first 100 overage units on the line bill
        at 12.5 cents each and any further units at 18.75 cents each; the line
        total is rounded half up to whole cents"

        Design: Corner/calculations/utility_tier_straddle_water
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam W")
        entry = validate_success(_post_entry(api, {
            "tenancy_id": ctx["tenancy"]["id"],
            "entry_type": "UTILITY_OVERAGE",
            "usage_lines": [
                {"utility_type": "WATER", "usage_units": 400},
            ]}), expected_status=201)
        # overage 250 = 100 @ 12.5 + 150 @ 18.75 = 1250 + 2812.5 = 4062.5
        # -> round_half_up 4063 (marginal, not average, rates).
        assert entry["amount_cents"] == 4063

    def test_utility_overage_forbids_amount_cents(self, api,
                                                  operator_admin_headers):
        """PRD §2.8: "the conditional field rules: a `UTILITY_OVERAGE` entry
        must carry `usage_lines` and must not carry `amount_cents`"

        Design: Corner/validations/utility_overage_forbids_amount_cents
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam UC")
        resp = _post_entry(api, {
            "tenancy_id": ctx["tenancy"]["id"],
            "entry_type": "UTILITY_OVERAGE",
            "amount_cents": 100,
            "usage_lines": [
                {"utility_type": "ELECTRIC", "usage_units": 205},
            ]})
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDamageChargeGate:
    def test_damage_charge_requires_verified_work_order(
            self, api, operator_admin_headers):
        """PRD §3.5: "A `DAMAGE` entry, conversely, requires `amount_cents`
        like any manual charge and additionally requires
        `source_work_order_id` citing the work order the damage was
        remediated under — and that work order must stand in `VERIFIED` or
        `CLOSED` (`ERR_WORK_ORDER_NOT_VERIFIED`)."

        Design: Corner/validations/damage_charge_requires_verified_work_order
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam DM")
        tenancy_id = ctx["tenancy"]["id"]
        wo = create_work_order(ctx["unit"]["id"], category="STRUCTURAL",
                               severity="MAJOR",
                               description="door frame damaged by resident")
        assert wo["status"] == "REPORTED"

        # Citing a REPORTED work order is refused.
        unverified = _post_entry(api, {
            "tenancy_id": tenancy_id, "entry_type": "DAMAGE",
            "amount_cents": 5000, "source_work_order_id": wo["id"]})
        validate_error(unverified, ApiErrorId.ERR_WORK_ORDER_NOT_VERIFIED)

        # Omitting the source is a shape violation.
        missing = _post_entry(api, {
            "tenancy_id": tenancy_id, "entry_type": "DAMAGE",
            "amount_cents": 5000})
        validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST)

        # Once VERIFIED, the same post succeeds into the damage bucket.
        walk_work_order_to_completed(wo["id"], completed_by="ml-1")
        verify_work_order(wo["id"], verified_by="sm-1")
        entry = validate_success(_post_entry(api, {
            "tenancy_id": tenancy_id, "entry_type": "DAMAGE",
            "amount_cents": 5000, "source_work_order_id": wo["id"]}),
            expected_status=201)
        assert entry["entry_type"] == "DAMAGE"
        statement = _statement(api, tenancy_id)
        assert statement["damage_bucket_balance_cents"] == 5000


class TestDeductionCapNestedMin:
    """Difficulty instance: nested min with the purpose branch. Auth A1
    0.25 RENT_AND_UTILITIES (household cap binds at 25000); superseded by A2
    0.35 RENT (federal 30% binds at 30000; utility bucket excluded)."""

    def _setup(self, api):
        ctx = setup_active_tenancy(site_name="Site D", household_name="Fam D",
                                   members=(("D One", "1980-01-01", "HEAD"),
                                            ("D Two", "1982-02-02", "SPOUSE")))
        tenancy_id = ctx["tenancy"]["id"]
        util = validate_success(_post_entry(api, {
            "tenancy_id": tenancy_id, "entry_type": "UTILITY_OVERAGE",
            "usage_lines": [
                {"utility_type": "ELECTRIC", "usage_units": 250}]}),
            expected_status=201)
        ctx["util_entry"] = util
        ctx["auth1"] = create_authorization(
            ctx["household"]["id"], cap_percent=0.25,
            purpose="RENT_AND_UTILITIES", effective_date="2026-08-01")
        return ctx

    def test_household_cap_binds_first_payment(self, api,
                                               intake_coordinator_headers):
        """PRD §3.5: "The collectible amount is the smallest of four
        candidates, each rounded half up to whole cents before the comparison:
        the authorization's `cap_percent` of gross wages; thirty percent of
        gross wages, the federal ceiling; gross wages minus a protected
        net-wage floor of 40,000 cents — the worker always takes home at least
        four hundred dollars; and the covered balance itself."
        PRD §3.5: "consumption beyond the allowance — 200 units for
        `ELECTRIC`, 100 for `GAS`, 150 for `WATER` — is the overage; the
        first 100 overage units on the line bill at 12.5 cents each"

        Design: Difficulty/combinatorial_formula/deduction_cap_nested_min_with_purpose_branch
        """
        ctx = self._setup(api)
        # 250 ELECTRIC -> 50 overage units at 12.5c -> 625.
        assert ctx["util_entry"]["amount_cents"] == 625

        pay1 = validate_success(
            _pay(api, ctx["tenancy"]["id"], 100000), expected_status=201)
        # min(25000, 30000, 60000, 61593): household cap binds.
        assert pay1["entry_type"] == "PAYMENT"
        assert pay1["amount_cents"] == 25000

    def test_federal_cap_binds_after_supersede_and_rent_only_purpose(
            self, api, intake_coordinator_headers):
        """PRD §3.5: "Consent replaces consent: creating an authorization
        supersedes the household's existing `ACTIVE` one, which moves `ACTIVE
        → SUPERSEDED` with its `superseded_by_id` pointing at the newcomer"
        PRD §3.5: "The covered balance is the rent bucket, plus the utility
        bucket when the authorization's `purpose` is `RENT_AND_UTILITIES`."
        PRD §3.5: "applies the credit as a waterfall: the rent bucket first,
        down to zero, with overflow into the utility bucket only when the
        authorization's `purpose` is `RENT_AND_UTILITIES`; the damage bucket
        is never touched by payroll money."

        Design: Difficulty/combinatorial_formula/deduction_cap_nested_min_with_purpose_branch
        """
        ctx = self._setup(api)
        tenancy_id = ctx["tenancy"]["id"]
        pay1 = validate_success(
            _pay(api, tenancy_id, 100000), expected_status=201)
        assert pay1["amount_cents"] == 25000, "Setup failed"

        auth2 = create_authorization(
            ctx["household"]["id"], cap_percent=0.35, purpose="RENT",
            effective_date="2026-08-16")
        auth1_after = validate_success(api.get_deduction_authorization(
            ctx["auth1"]["id"], intake_coordinator_headers))
        assert auth1_after["status"] == "SUPERSEDED"
        assert auth1_after["superseded_by_id"] == auth2["id"]

        pay2 = validate_success(
            _pay(api, tenancy_id, 100000, "2026-08-16", "2026-08-31"),
            expected_status=201)
        # min(round(0.35*100000), round(0.30*100000), 60000, rent-only
        # covered 35968): federal cap binds; purpose RENT excludes the 625
        # utility balance.
        assert pay2["amount_cents"] == 30000

        statement = _statement(api, tenancy_id)
        assert statement["rent_bucket_balance_cents"] == 5968, (
            "60968 - 25000 - 30000")
        assert statement["utility_bucket_balance_cents"] == 625, (
            "pay1's waterfall exhausted the rent bucket only down to 35968 "
            "and never overflowed; pay2's purpose RENT cannot touch utility")
        assert statement["balance_cents"] == 6593
        assert_statement_invariants(statement)


class TestPaymentBoundaries:
    def test_payment_wage_floor_binds(self, api, intake_coordinator_headers):
        """PRD §3.5: "gross wages minus a protected net-wage floor of 40,000
        cents — the worker always takes home at least four hundred dollars"

        Design: Corner/calculations/payment_wage_floor_binds
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam WF")
        create_authorization(ctx["household"]["id"], cap_percent=0.25,
                             purpose="RENT_AND_UTILITIES")
        payment = validate_success(
            _pay(api, ctx["tenancy"]["id"], 50000), expected_status=201)
        # min(12500, 15000, 50000 - 40000 = 10000, 60968): floor binds.
        assert payment["amount_cents"] == 10000

    def test_payment_exact_payoff_then_nothing_to_collect(
            self, api, intake_coordinator_headers):
        """PRD §3.5: "and the covered balance itself. When the smallest
        candidate is zero or negative there is nothing to collect and the
        payment is rejected with `ERR_NOTHING_TO_COLLECT` (HTTP 422)."
        PRD §3.5: "`oldest_unpaid_charge_date` is the earliest `charge_date`
        among debits with residual remaining, across all buckets, and is null
        when the balance is zero"

        Design: Corner/calculations/payment_exact_payoff_then_nothing_to_collect
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam EP")
        create_authorization(ctx["household"]["id"], cap_percent=1.0,
                             purpose="RENT_AND_UTILITIES")
        payment = validate_success(
            _pay(api, ctx["tenancy"]["id"], 1000000), expected_status=201)
        # min(1000000, 300000, 960000, 60968): covered balance binds exactly.
        assert payment["amount_cents"] == 60968

        statement = _statement(api, ctx["tenancy"]["id"])
        assert statement["balance_cents"] == 0
        assert statement["is_delinquent"] is False
        assert statement["oldest_unpaid_charge_date"] is None

        empty = _pay(api, ctx["tenancy"]["id"], 1000000,
                     "2026-08-16", "2026-08-31")
        validate_error(empty, ApiErrorId.ERR_NOTHING_TO_COLLECT)


class TestLedgerVoidInvariant:
    """Difficulty instance: post + void conserves the balance exactly."""

    def _setup(self, api):
        ctx = setup_active_tenancy(site_name="Site LI",
                                   household_name="Fam LI")
        before = _statement(api, ctx["tenancy"]["id"])
        assert before["balance_cents"] == 60968, "Setup failed"
        return ctx

    def test_post_moves_balance(self, api, operator_admin_headers):
        """PRD §3.5: "The `amount_cents` is always positive, with the sign
        derived from the type: `RENT`, `UTILITY_OVERAGE`, and `DAMAGE` are
        debits; `SUBSIDY_CREDIT` and `PAYMENT` are credits."
        PRD §3.5: "The tenancy's `balance_cents` is the sum of the three."

        Design: Difficulty/compensating_invariant/ledger_post_void_balance_invariant
        """
        ctx = self._setup(api)
        entry = validate_success(_post_entry(api, {
            "tenancy_id": ctx["tenancy"]["id"], "entry_type": "RENT",
            "amount_cents": 90000,
            "description": "September rent posted in error"}),
            expected_status=201)
        assert entry["status"] == "POSTED"
        mid = _statement(api, ctx["tenancy"]["id"])
        assert mid["balance_cents"] == 150968, "60968 + 90000"

    def test_void_returns_balance_to_pre_post_value(
            self, api, operator_admin_headers):
        """PRD §3.5: "Balances are kept in three buckets and always recomputed
        from `POSTED` entries — `VOIDED` ones are excluded from every sum."
        PRD §3.5: "The void records the reason, moves the entry `POSTED →
        VOIDED`, excludes it from every sum, recomputes the tenancy's balances
        and delinquency, and increments the tenancy's `version` by one."

        Design: Difficulty/compensating_invariant/ledger_post_void_balance_invariant
        """
        ctx = self._setup(api)
        entry = validate_success(_post_entry(api, {
            "tenancy_id": ctx["tenancy"]["id"], "entry_type": "RENT",
            "amount_cents": 90000,
            "description": "September rent posted in error"}),
            expected_status=201)
        assert _statement(api, ctx["tenancy"]["id"])["balance_cents"] == 150968

        voided = validate_success(api.void_charge_ledger_entry(
            entry["id"], {"void_reason": "duplicate posting"}, ADMIN))
        assert voided["status"] == "VOIDED"
        after = _statement(api, ctx["tenancy"]["id"])
        assert after["balance_cents"] == 60968, (
            "Post + void conserves the ledger balance exactly")
        assert_statement_invariants(after)

    def test_ledger_double_void_rejected(self, api, operator_admin_headers):
        """PRD §3.5: "the target must still be `POSTED`, and voiding an
        already-voided entry is rejected with `ERR_ENTRY_ALREADY_VOIDED`."

        Design: Corner/state_machines/ledger_double_void_rejected
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam DV")
        entries, _ = validate_paginated(api.list_charge_ledger_entries(
            operator_admin_headers,
            params={"tenancy_id": ctx["tenancy"]["id"]}))
        entry_id = entries[0]["id"]

        first = validate_success(api.void_charge_ledger_entry(
            entry_id, {"void_reason": "first void"}, ADMIN))
        assert first["status"] == "VOIDED"

        second = api.void_charge_ledger_entry(
            entry_id, {"void_reason": "second void"}, ADMIN)
        validate_error(second, ApiErrorId.ERR_ENTRY_ALREADY_VOIDED)

        statement = _statement(api, ctx["tenancy"]["id"])
        assert statement["balance_cents"] == 0, (
            "The second void did not double-subtract")

    def test_void_missing_reason_invalid_request(self, api,
                                                 operator_admin_headers):
        """PRD §3.5: "An `OperatorAdmin` voids a ledger entry with a
        `void_reason`"
        PRD §2.8: "Third, request-body shape — required fields present, types
        correct, enum values inside their declared sets"

        Design: Corner/validations/void_missing_reason_invalid_request
        """
        ctx = setup_active_tenancy(site_name="S", household_name="Fam VR")
        entries, _ = validate_paginated(api.list_charge_ledger_entries(
            operator_admin_headers,
            params={"tenancy_id": ctx["tenancy"]["id"]}))
        resp = api.void_charge_ledger_entry(entries[0]["id"], {}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDelinquencyGraceBoundary:
    def test_delinquency_grace_boundary(self, api, operator_admin_headers):
        """PRD §3.5: "`is_delinquent` is true when the balance is positive and
        the oldest unpaid charge is more than ten days old — a charge exactly
        ten days old is not yet delinquent."
        PRD §2.4: "Until that capability is first invoked, the clock reads
        exactly 2026-08-01T00:00:00Z, and the implementation must never fall
        back to wall-clock time."

        Design: Corner/calculations/delinquency_grace_boundary
        """
        # Activation posts its RENT charge at the default clock 2026-08-01.
        ctx = setup_active_tenancy(site_name="S", household_name="Fam DL")

        set_clock("2026-08-11T00:00:00Z")
        at_ten = _statement(api, ctx["tenancy"]["id"])
        assert at_ten["oldest_unpaid_charge_date"] == "2026-08-01"
        assert at_ten["is_delinquent"] is False, (
            "Exactly GRACE_DAYS (10) old is not yet delinquent (strict >)")

        set_clock("2026-08-12T00:00:00Z")
        at_eleven = _statement(api, ctx["tenancy"]["id"])
        assert at_eleven["is_delinquent"] is True, (
            "Eleven days crosses the grace boundary")


class TestPaymentStateGatePriority:
    """Difficulty instance: a payment against a CANCELLED tenancy with no
    authorization violates both the state gate and the fiscal gate; the
    fixed global order reports the state error."""

    def test_state_error_beats_fiscal_error(self, api,
                                            intake_coordinator_headers):
        """PRD §2.8: "A half-step later, the ledger-and-complaint gate:
        recording a payment, posting a ledger entry directly, or filing a
        complaint each require the tenancy to stand in `ACTIVE` or `NOTICE`
        (`ERR_INVALID_STATE`)."
        PRD §2.8: "Seventeenth, the payment gates: an `ACTIVE` authorization
        must exist (`ERR_NO_ACTIVE_DEDUCTION_AUTHORIZATION`) and the capped
        amount must be positive (`ERR_NOTHING_TO_COLLECT`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_tenancy_payment
        """
        ctx = setup_pending_tenancy(site_name="Site PF",
                                    household_name="Fam PF")
        cancelled = validate_success(api.update_tenancy(
            ctx["tenancy"]["id"], {"status": "CANCELLED"}, INTAKE))
        assert cancelled["status"] == "CANCELLED", "Setup failed"

        resp = _pay(api, ctx["tenancy"]["id"], 100000)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_payment_persists_no_entry(self, api,
                                                intake_coordinator_headers,
                                                operator_admin_headers):
        """PRD §3.5: "Otherwise the system creates a `POSTED` `PAYMENT` entry
        at that amount" — a rejected request creates no entry.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_tenancy_payment
        """
        ctx = setup_pending_tenancy(site_name="Site PF",
                                    household_name="Fam PF")
        validate_success(api.update_tenancy(
            ctx["tenancy"]["id"], {"status": "CANCELLED"}, INTAKE))

        resp = _pay(api, ctx["tenancy"]["id"], 100000)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        entries, meta = validate_paginated(api.list_charge_ledger_entries(
            operator_admin_headers,
            params={"tenancy_id": ctx["tenancy"]["id"]}))
        assert entries == [], (
            "No PAYMENT entry may be persisted by the rejected request")
