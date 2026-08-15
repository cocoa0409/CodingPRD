"""Lease lifecycle: return, inspection, settlement math, the settle ->
credit-hold -> rental-cancel cascade, and validation-ladder conflicts."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_customer,
    get_lease_contract,
    get_rental_contract,
    get_unit,
    make_customer,
    make_lease,
    make_lease_with_approved_inspection,
    make_rental_contract,
    make_returned_lease,
    make_settled_lease,
    make_unit,
    validate_error,
    validate_success,
)

LEASE_MGR = TEST_USERS["lease_manager_headers"]


class TestLeaseSettlementTier:
    def test_settlement_keys_tier_on_prediscount_total(self, api):
        """PRD §3.7: "The evaluation order is pinned: components first, then
        the sum, then the tier, then the discount — the tier is never
        re-derived from the discounted result, even when the discount pulls
        the total back below the threshold that earned it (a 520000-cent
        pre-discount total settles at 468000 cents under the ten-percent tier,
        not at 494000 cents under a wrongly re-derived five-percent tier)."

        Design: Difficulty/combinatorial_formula/lease_settlement_prediscount_tier
        """
        _customer, _unit, lease, inspection = \
            make_lease_with_approved_inspection()
        assert inspection["wear_charge_cents"] == 150000, "grade B wear charge"
        settled = validate_success(api.settle_lease_contract(lease["id"],
                                                             LEASE_MGR))
        # overage (1200-1000)*500=100000 + wear 150000 + shortfall 270000
        # = 520000 pre-discount -> 10% tier -> 468000
        assert settled["settlement_total_cents"] == 468000
        assert settled["status"] == "SETTLED"

    def test_settlement_posts_to_customer_balance(self, api):
        """PRD §3.7: "Settlement posts `settlement_total_cents` to the
        customer's `outstanding_balance_cents`."

        Design: Difficulty/combinatorial_formula/lease_settlement_prediscount_tier
        """
        customer, _unit, lease, _inspection = make_settled_lease()
        assert lease["status"] == "SETTLED"
        assert lease["settlement_total_cents"] == 468000
        assert customer["outstanding_balance_cents"] == 468000


class TestSettleCreditHoldCascade:
    def _scenario(self, api):
        """Customer (credit_limit 400000) with a RESERVED 3-day rental (hold
        45000) and a RETURNED lease whose approved inspection settles at
        468000."""
        customer = make_customer(name="Leverage Co", credit_limit_cents=400000)
        rental_unit = make_unit(serial_number="SN-TC2R")
        contract = make_rental_contract(customer["id"], rental_unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-08-04")
        lease_unit = make_unit(serial_number="SN-TC2L", disposition="NEW_SALE")
        _c, _u, lease = make_returned_lease(customer_id=customer["id"],
                                            unit=lease_unit)
        inspection = validate_success(api.create_lease_inspection(
            lease["id"], {"condition_grade": "B", "hours_at_return": 1200,
                          "appraised_value_cents": 530000},
            LEASE_MGR), 201)
        validate_success(api.approve_inspection(inspection["id"],
                                                LEASE_MGR))
        return customer, contract, lease

    def test_settle_flips_account_to_credit_hold(self, api):
        """PRD §2.10: "Whenever a posting raises `outstanding_balance_cents`
        to strictly more than `credit_limit_cents`, the customer's
        `account_status` flips from `ACTIVE` to `CREDIT_HOLD`." Settlement
        posts 468000 against a 400000 limit.

        Design: Difficulty/transitive_cascade/lease_settle_credit_hold_cascade
        """
        customer, _contract, lease = self._scenario(api)
        validate_success(api.settle_lease_contract(lease["id"], LEASE_MGR))
        data = get_customer(customer["id"])
        assert data["outstanding_balance_cents"] == 468000
        assert data["account_status"] == "CREDIT_HOLD"  # 468000 > 400000

    def test_credit_hold_flip_auto_cancels_reserved_rentals(self, api):
        """PRD §2.10: "The flip is itself a cascade trigger: every rental
        contract of that customer still in `RESERVED` status is automatically
        cancelled and its credit hold is released from `credit_holds_cents`."

        Design: Difficulty/transitive_cascade/lease_settle_credit_hold_cascade
        """
        customer, contract, lease = self._scenario(api)
        validate_success(api.settle_lease_contract(lease["id"], LEASE_MGR))
        assert get_rental_contract(contract["id"])["status"] == "CANCELLED"
        assert get_customer(customer["id"])["credit_holds_cents"] == 0


class TestLeaseReturnAndInspectionGates:
    def test_lease_return_flips_unit_to_used_inventory(self, api):
        """PRD §3.7: "Recording the lease return — with a `return_date` —
        moves the lease from `ACTIVE` to `RETURNED` and works two changes on
        the unit: its availability moves from `ON_LEASE` back to `AVAILABLE`,
        and its `disposition` flips to `USED_SALE`".

        Design: Corner/endpoints/lease_return_flips_unit_to_used_inventory
        """
        customer = make_customer(name="Offlease Co")
        unit = make_unit(serial_number="SN-EP1", disposition="NEW_SALE")
        lease = make_lease(customer["id"], unit["id"])
        assert get_unit(unit["id"])["availability_status"] == "ON_LEASE"
        returned = validate_success(api.return_lease_contract(
            lease["id"], {"return_date": "2026-08-01"}, LEASE_MGR))
        assert returned["status"] == "RETURNED"
        unit_after = get_unit(unit["id"])
        assert unit_after["availability_status"] == "AVAILABLE"
        assert unit_after["disposition"] == "USED_SALE"

    def test_second_inspection_approve_rejected(self, api):
        """PRD §3.7: "At most one inspection per lease may be `APPROVED` —
        approving a second while an approved inspection already exists for
        that lease is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/second_inspection_approve_rejected
        """
        customer = make_customer(name="Insp Co")
        unit = make_unit(serial_number="SN-IN1", disposition="NEW_SALE")
        _c, _u, lease = make_returned_lease(customer_id=customer["id"],
                                            unit=unit)
        first = validate_success(api.create_lease_inspection(
            lease["id"], {"condition_grade": "A", "hours_at_return": 900,
                          "appraised_value_cents": 850000},
            LEASE_MGR), 201)
        second = validate_success(api.create_lease_inspection(
            lease["id"], {"condition_grade": "D", "hours_at_return": 900,
                          "appraised_value_cents": 100000},
            LEASE_MGR), 201)
        validate_success(api.approve_inspection(first["id"], LEASE_MGR))
        resp = api.approve_inspection(second["id"], LEASE_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        listed = validate_success(api.list_lease_inspections(lease["id"],
                                                             LEASE_MGR))
        second_after = [i for i in listed if i["id"] == second["id"]][0]
        assert second_after["status"] == "SUBMITTED"

    def test_settle_without_approved_inspection_rejected(self, api):
        """PRD §2.6: "Only once the lease is known to be `RETURNED` does the
        system ask whether exactly one inspection has been approved for it; a
        returned lease without an approved inspection fails with
        `ERR_INSPECTION_NOT_APPROVED`."

        Design: Corner/state_machines/settle_without_approved_inspection_rejected
        """
        customer = make_customer(name="Settle Co")
        unit = make_unit(serial_number="SN-ST1", disposition="NEW_SALE")
        _c, _u, lease = make_returned_lease(customer_id=customer["id"],
                                            unit=unit)
        validate_success(api.create_lease_inspection(
            lease["id"], {"condition_grade": "B", "hours_at_return": 1200,
                          "appraised_value_cents": 530000},
            LEASE_MGR), 201)
        resp = api.settle_lease_contract(lease["id"], LEASE_MGR)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_APPROVED, 409)
        data = get_lease_contract(lease["id"])
        assert data["status"] == "RETURNED"
        assert data["settlement_total_cents"] is None


class TestCreditHoldBlocksRentalDesk:
    def test_account_credit_hold_blocks_new_rental(self, api):
        """PRD §2.10: "While a customer is on `CREDIT_HOLD`, the rental desk
        is closed to them — both creating a reservation and checking out a
        unit are rejected with `ERR_ACCOUNT_CREDIT_HOLD`."

        Design: Corner/errors/account_credit_hold_blocks_new_rental
        """
        customer = make_customer(name="Hold Co", credit_limit_cents=100000)
        lease_unit = make_unit(serial_number="SN-E1L", disposition="NEW_SALE")
        make_settled_lease(customer_id=customer["id"], unit=lease_unit)
        assert get_customer(customer["id"])["account_status"] == "CREDIT_HOLD"
        rental_unit = make_unit(serial_number="SN-E1R")
        resp = api.create_rental_contract(
            {"unit_id": rental_unit["id"], "customer_id": customer["id"],
             "start_date": "2026-08-01", "end_date": "2026-08-03",
             "expected_unit_version": rental_unit["version"]},
            TEST_USERS["rental_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CREDIT_HOLD, 422)


class TestCheckoutStateVsFiscalConflict:
    def _scenario(self, api, rental_coordinator_headers):
        """Cancelled rental contract on a customer who then flips to
        CREDIT_HOLD via a lease settlement."""
        customer = make_customer(name="Conflict Co", credit_limit_cents=100000)
        rental_unit = make_unit(serial_number="SN-PP1R")
        contract = make_rental_contract(customer["id"], rental_unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-08-04")
        validate_success(api.cancel_rental_contract(contract["id"],
                                                    rental_coordinator_headers))
        lease_unit = make_unit(serial_number="SN-PP1L", disposition="NEW_SALE")
        make_settled_lease(customer_id=customer["id"], unit=lease_unit)
        return customer, contract

    def test_cancelled_checkout_reports_state_error(
            self, api, rental_coordinator_headers):
        """PRD §2.6: "the system evaluates them in one fixed precedence
        ladder, and the first failing check determines the error returned"
        with "state validity of the requested transition; and then the
        business gates in this exact order" ahead of "the customer's account
        standing" — a CANCELLED contract fails state validity before the
        account-standing gate is reached.

        Design: Difficulty/priority_pair_validation_conflict/checkout_cancelled_vs_credit_hold
        """
        customer, contract = self._scenario(api, rental_coordinator_headers)
        assert get_customer(customer["id"])["account_status"] == "CREDIT_HOLD"
        resp = api.checkout_rental_contract(contract["id"],
                                            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_conflict_leaves_contract_cancelled(
            self, api, rental_coordinator_headers):
        """PRD §3.3: "`RETURNED` and `CANCELLED` are terminal." The rejected
        checkout (state rung beating the fiscal rung per the §2.6 ladder)
        changes nothing: the contract stays CANCELLED and the customer stays
        on CREDIT_HOLD.

        Design: Difficulty/priority_pair_validation_conflict/checkout_cancelled_vs_credit_hold
        """
        customer, contract = self._scenario(api, rental_coordinator_headers)
        resp = api.checkout_rental_contract(contract["id"],
                                            rental_coordinator_headers)
        error = resp.json()["data"]["error_id"]
        assert error == "ERR_INVALID_STATE"
        assert error != "ERR_ACCOUNT_CREDIT_HOLD"
        assert get_rental_contract(contract["id"])["status"] == "CANCELLED"
        assert get_customer(customer["id"])["account_status"] == "CREDIT_HOLD"
