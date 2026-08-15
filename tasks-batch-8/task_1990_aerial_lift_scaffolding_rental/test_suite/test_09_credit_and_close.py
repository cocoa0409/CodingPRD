"""Credit standing, suspension cascades, activation gates, and close-out."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, create_customer_account_payload, create_rental_contract_payload,
    create_customer, create_equipment_class, create_equipment_unit,
    create_contract, add_line, activate_contract, set_clock,
    setup_draft_contract_with_line, setup_active_rental, setup_returned_line,
    setup_suspended_customer, off_rent, create_claim, assess_claim,
    charge_claim, dispute_claim, resolve_claim,
    get_contract, get_customer, get_invoice,
    assert_customer_account, assert_rental_contract, assert_invoice,
)


class TestCustomerCreation:
    def test_customer_create_defaults(self, api, branch_manager_headers):
        """PRD §3.1: "New accounts start in `ACTIVE` status with
        `outstanding_balance_cents` equal to zero."

        Design: Corner/entities/customer_create_defaults
        """
        res = api.create_customer_account(
            create_customer_account_payload("Default Check Co",
                                            "d@default.example", 250000),
            branch_manager_headers)
        customer = validate_success(res, 201)
        assert_customer_account(customer)
        assert customer["status"] == "ACTIVE"
        assert customer["outstanding_balance_cents"] == 0


class TestClaimChargeSuspendsCustomer:
    def test_charge_pushes_balance_over_limit_and_suspends(self, api):
        """PRD §3.8: "the customer's outstanding balance is recomputed and may
        trigger the suspension cascade". PRD §3.1: "When a recompute yields an
        `outstanding_balance_cents` that exceeds `credit_limit_cents`, the
        customer cascades from `ACTIVE` to `SUSPENDED` and the account's
        `version` increments." and "it is the sum of the invoice totals of
        exactly those of the customer's rental contracts currently in `ACTIVE`
        status".

        Design: Difficulty/transitive_cascade/claim_charge_suspends_customer
        """
        ctx = setup_suspended_customer(credit_limit_cents=100_000,
                                       repair_estimate_cents=500_000)
        assert ctx["claim"]["chargeback_cents"] == 500000, "no waiver: full estimate"
        contract = get_contract(ctx["contract"]["id"])
        assert contract["damage_subtotal_cents"] == 500000, "link 1"
        customer = ctx["customer"]
        # Rental 10000 (1 day) + logistics 15000 + damage 500000.
        assert customer["outstanding_balance_cents"] == 525000, "link 2"
        assert customer["status"] == "SUSPENDED", (
            "link 3: 525000 > credit_limit 100000")

    def test_charge_within_credit_limit_does_not_suspend(self, api):
        """PRD §3.1: "When a recompute yields an `outstanding_balance_cents`
        that exceeds `credit_limit_cents`, the customer cascades from `ACTIVE`
        to `SUSPENDED`" — a recompute that stays within the limit leaves the
        account `ACTIVE`.

        Design: Difficulty/transitive_cascade/claim_charge_suspends_customer
        """
        ctx = setup_suspended_customer(credit_limit_cents=100_000,
                                       repair_estimate_cents=70_000)
        assert ctx["claim"]["chargeback_cents"] == 70000
        customer = ctx["customer"]
        # 10000 + 15000 + 70000 = 95000 <= 100000.
        assert customer["outstanding_balance_cents"] == 95000
        assert customer["status"] == "ACTIVE", "no cascade below the limit"


class TestStateBeatsFiscalOnActivate:
    def test_reactivate_active_contract_with_suspended_customer(
            self, api, rental_coordinator_headers):
        """PRD §2.8: "Every request is validated against a fixed pipeline, and
        the first failing check determines the error returned" — step
        "**State-machine preconditions**" (`ERR_INVALID_STATE`) precedes step
        "**Fiscal gates**: customer suspension (`ERR_CUSTOMER_SUSPENDED`)".
        PRD §3.3: "A `RentalCoordinator` may activate a contract only while it
        is in `DRAFT` status".

        Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_suspended_fiscal
        """
        ctx = setup_suspended_customer(credit_limit_cents=100_000,
                                       repair_estimate_cents=500_000)
        assert ctx["customer"]["status"] == "SUSPENDED"
        res = api.activate_rental_contract(ctx["contract"]["id"],
                                           rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_activate_empty_draft_with_suspended_customer(
            self, api, rental_coordinator_headers):
        """PRD §3.3: "A `RentalCoordinator` may activate a contract only while
        it is in `DRAFT` status and only when at least one of its lines is in
        `RESERVED` status; violations of either are rejected with
        `ERR_INVALID_STATE`. Two fiscal gates then apply in order: the
        customer must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`)" — the state
        violation is reported before the fiscal gate.

        Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_suspended_fiscal
        """
        ctx = setup_active_rental(
            credit_limit_cents=100_000,
            class_kwargs={"class_code": "LFT9", "max_working_height_ft": 30,
                          "daily_rate_cents": 10000, "weekly_rate_cents": 70000,
                          "monthly_rate_cents": 200000,
                          "replacement_value_cents": 2_000_000},
            requested_start_date="2026-08-05", requested_end_date="2026-08-06",
            required_working_height_ft=25,
            planned_start_utc="2026-08-05T08:00:00Z",
            planned_end_utc="2026-08-05T10:00:00Z",
            deliver_at="2026-08-05T09:00:00Z")
        # A second, empty DRAFT contract exists before the suspension.
        contract2 = create_contract(ctx["customer"]["id"], "9 Extra Rd")

        set_clock("2026-08-06T09:00:00Z")
        off_rent(ctx["line"]["id"])
        claim = create_claim(ctx["line"]["id"], "DAMAGE", "crushed platform")
        assess_claim(claim["id"], 500_000)
        charge_claim(claim["id"])
        assert get_customer(ctx["customer"]["id"])["status"] == "SUSPENDED"

        res = api.activate_rental_contract(contract2["id"],
                                           rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_contract(contract2["id"])["status"] == "DRAFT"


class TestSuspendedAndCreditGates:
    def test_suspended_customer_contract_create_rejected(
            self, api, rental_coordinator_headers):
        """PRD §3.1: "A suspended customer is shut out of new business:
        creating a contract for them, adding a line to one of their contracts,
        or activating one of their contracts is rejected with
        `ERR_CUSTOMER_SUSPENDED` (HTTP 402)."

        Design: Corner/validations/suspended_customer_contract_create_rejected
        """
        ctx = setup_suspended_customer(credit_limit_cents=100_000,
                                       repair_estimate_cents=500_000)
        res = api.create_rental_contract(
            create_rental_contract_payload(ctx["customer"]["id"],
                                           "9 New Job Rd"),
            rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_CUSTOMER_SUSPENDED)

    def test_credit_limit_exceeded_on_activate(self, api,
                                               rental_coordinator_headers):
        """PRD §3.3: "the customer's current `outstanding_balance_cents` plus
        the sum of `provisional_charge_cents` across the contract's
        non-`CANCELLED` lines must not exceed the customer's
        `credit_limit_cents` — otherwise activation is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/credit_limit_exceeded_on_activate
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Over Limit Co", "ops@ol.example",
                                   credit_limit_cents=50_000)
        cls = create_equipment_class(
            class_code="LFT4", max_working_height_ft=30, daily_rate_cents=10000,
            weekly_rate_cents=70000, monthly_rate_cents=200000,
            replacement_value_cents=2_000_000)
        unit = create_equipment_unit(cls["id"], "LFT4-001")
        contract = create_contract(customer["id"], "5 Budget Blvd")
        # 16 reserved days: min(10000*16=160000, 70000*3=210000, 200000).
        add_line(contract["id"], unit["id"], "2026-08-05", "2026-08-20", 25)

        res = api.activate_rental_contract(contract["id"],
                                           rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_contract(contract["id"])["status"] == "DRAFT", (
            "rejected activation leaves the contract DRAFT")

    def test_activate_without_lines_rejected(self, api,
                                             rental_coordinator_headers):
        """PRD §3.3: "A `RentalCoordinator` may activate a contract only while
        it is in `DRAFT` status and only when at least one of its lines is in
        `RESERVED` status; violations of either are rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/endpoints/activate_without_lines_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Empty Contract Co", "ops@empty.example")
        contract = create_contract(customer["id"], "0 Nowhere Rd")
        res = api.activate_rental_contract(contract["id"],
                                           rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_contract(contract["id"])["status"] == "DRAFT"


class TestCloseOut:
    def test_close_blocked_by_disputed_claim_then_succeeds_after_waive(
            self, api, rental_coordinator_headers):
        """PRD §3.9: "then no claim of the contract may remain in `OPEN`,
        `ASSESSED`, or `DISPUTED` status — otherwise `ERR_OPEN_CLAIMS_EXIST`
        (HTTP 409)." and "On success the contract moves from `ACTIVE` to
        `CLOSED` — its terminal state — `closed_at` is stamped from the
        logical clock".

        Design: Difficulty/cross_entity_state_dependency/close_blocked_by_disputed_claim
        """
        ctx = setup_returned_line()
        contract_id = ctx["contract"]["id"]
        claim = create_claim(ctx["line"]["id"], "DAMAGE", "scratched cowling")
        assess_claim(claim["id"], 50_000)
        charge_claim(claim["id"])
        dispute_claim(claim["id"], ctx["customer"]["id"])

        blocked = api.close_rental_contract(contract_id,
                                            rental_coordinator_headers)
        validate_error(blocked, ApiErrorId.ERR_OPEN_CLAIMS_EXIST)

        resolve_claim(claim["id"], "WAIVE")
        closed = validate_success(api.close_rental_contract(
            contract_id, rental_coordinator_headers))
        assert_rental_contract(closed)
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] is not None

    def test_closed_contract_final_invoice_total(self, api,
                                                 rental_coordinator_headers):
        """PRD §3.9: "the invoice is finalized: with all lines returned or
        cancelled, the rental subtotal now rests entirely on final charges"
        and "Its body carries the `contract_id`, the contract's `status`, and
        four integer-cent figures".

        Design: Difficulty/cross_entity_state_dependency/close_blocked_by_disputed_claim
        """
        ctx = setup_returned_line()
        contract_id = ctx["contract"]["id"]
        claim = create_claim(ctx["line"]["id"], "DAMAGE", "scratched cowling")
        assess_claim(claim["id"], 50_000)
        charge_claim(claim["id"])
        dispute_claim(claim["id"], ctx["customer"]["id"])
        resolve_claim(claim["id"], "WAIVE")

        closed = validate_success(api.close_rental_contract(
            contract_id, rental_coordinator_headers))
        assert closed["status"] == "CLOSED"

        invoice = get_invoice(contract_id)
        assert_invoice(invoice)
        # 1 elapsed day -> 14500; delivery + pickup fees 2 x 15000; waive
        # removed the 50000 chargeback.
        assert invoice["rental_subtotal_cents"] == 14500
        assert invoice["logistics_subtotal_cents"] == 30000
        assert invoice["damage_subtotal_cents"] == 0
        assert invoice["invoice_total_cents"] == 44500

    def test_close_with_outstanding_lines_rejected(
            self, api, rental_coordinator_headers):
        """PRD §3.9: "then every line of the contract must be in `RETURNED` or
        `CANCELLED` status — a line anywhere else is rejected with
        `ERR_LINES_OUTSTANDING` (HTTP 409)".

        Design: Corner/validations/close_with_outstanding_lines_rejected
        """
        ctx = setup_active_rental()
        assert ctx["line"]["status"] == "OUT_ON_RENT"
        res = api.close_rental_contract(ctx["contract"]["id"],
                                        rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_LINES_OUTSTANDING)
        assert get_contract(ctx["contract"]["id"])["status"] == "ACTIVE"
