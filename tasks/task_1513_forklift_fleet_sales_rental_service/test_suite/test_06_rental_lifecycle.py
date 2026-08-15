"""Rental lifecycle gates: checkout availability, PM gate, invalid returns,
and the return -> posture -> auto-PM-call cascade."""
from test_helpers import (
    ApiErrorId,
    get_customer,
    get_rental_contract,
    get_unit,
    make_checked_out_contract,
    make_customer,
    make_rental_contract,
    make_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCheckoutCrossEntityGate:
    def test_checkout_blocked_when_unit_on_rent(self, api,
                                                rental_coordinator_headers):
        """PRD §3.3: "the unit must currently be `AVAILABLE` (note the
        asymmetry with reservation, which tolerates `ON_RENT`; the desk can
        only hand over a physically present unit), else
        `ERR_UNIT_NOT_AVAILABLE`" — contract B cannot check out while contract
        A's checkout has the unit ON_RENT.

        Design: Difficulty/cross_entity_state_dependency/checkout_requires_unit_available
        """
        customer = make_customer(name="Dep Co")
        unit = make_unit(serial_number="SN-CE1")
        contract_a = make_rental_contract(customer["id"], unit["id"],
                                          start_date="2026-08-01",
                                          end_date="2026-08-05")
        validate_success(api.checkout_rental_contract(contract_a["id"],
                                                      rental_coordinator_headers))
        contract_b = make_rental_contract(customer["id"], unit["id"],
                                          start_date="2026-08-06",
                                          end_date="2026-08-10")
        resp = api.checkout_rental_contract(contract_b["id"],
                                            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE, 409)

    def test_blocked_checkout_leaves_states_unchanged(
            self, api, rental_coordinator_headers):
        """PRD §3.3: checkout "moves a `RESERVED` contract to `ON_RENT`" only
        on success; a rejected checkout leaves contract B `RESERVED` while
        contract A remains `ON_RENT` with the unit.

        Design: Difficulty/cross_entity_state_dependency/checkout_requires_unit_available
        """
        customer = make_customer(name="Dep Co")
        unit = make_unit(serial_number="SN-CE1B")
        contract_a = make_rental_contract(customer["id"], unit["id"],
                                          start_date="2026-08-01",
                                          end_date="2026-08-05")
        validate_success(api.checkout_rental_contract(contract_a["id"],
                                                      rental_coordinator_headers))
        contract_b = make_rental_contract(customer["id"], unit["id"],
                                          start_date="2026-08-06",
                                          end_date="2026-08-10")
        validate_error(api.checkout_rental_contract(contract_b["id"],
                                                    rental_coordinator_headers),
                       ApiErrorId.ERR_UNIT_NOT_AVAILABLE, 409)
        assert get_rental_contract(contract_b["id"])["status"] == "RESERVED"
        assert get_rental_contract(contract_a["id"])["status"] == "ON_RENT"
        assert get_unit(unit["id"])["availability_status"] == "ON_RENT"


class TestInvalidReturn:
    def test_return_reserved_contract_returns_invalid_state(
            self, api, rental_coordinator_headers):
        """PRD §3.3: return "moves from `ON_RENT` to `RETURNED`" — returning a
        `RESERVED` (never checked out) contract is not a valid transition and
        fails the state-validity rung with `ERR_INVALID_STATE` (PRD §5);
        the contract keeps its provisional hold and `final_charge_cents`
        stays null (PRD §3.3: a new reservation begins "with `checkout_hours`,
        `return_hours`, `actual_return_date`, and `final_charge_cents` all
        null").

        Design: Corner/state_machines/return_reserved_contract_returns_invalid_state
        """
        customer = make_customer(name="SM2 Co")
        unit = make_unit(serial_number="SN-SM2")
        contract = make_rental_contract(customer["id"], unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-08-03")
        resp = api.return_rental_contract(
            contract["id"], {"return_date": "2026-08-03", "return_hours": 10},
            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        data = get_rental_contract(contract["id"])
        assert data["status"] == "RESERVED"
        assert data["final_charge_cents"] is None
        assert get_customer(customer["id"])["credit_holds_cents"] == 30000


class TestCheckoutPmGate:
    def test_checkout_pm_overdue_rejected(self, api, fleet_manager_headers,
                                          rental_coordinator_headers):
        """PRD §3.3: "the unit's `maintenance_posture` must be `PM_OK` — a
        `PM_DUE` unit may not go out the door and the attempt is rejected with
        `ERR_PM_OVERDUE`". The availability dimension is untouched: the unit
        stays AVAILABLE (PM_DUE) while the contract stays RESERVED.

        Design: Corner/validations/checkout_pm_overdue_rejected
        """
        customer = make_customer(name="PM Gate")
        unit = make_unit(serial_number="SN-V9")
        validate_success(api.create_meter_reading(unit["id"],
                                                  {"reading_hours": 500},
                                                  fleet_manager_headers), 201)
        assert get_unit(unit["id"])["maintenance_posture"] == "PM_DUE"
        contract = make_rental_contract(customer["id"], unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-08-03")
        resp = api.checkout_rental_contract(contract["id"],
                                            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_PM_OVERDUE, 422)
        assert get_rental_contract(contract["id"])["status"] == "RESERVED"
        unit_after = get_unit(unit["id"])
        assert unit_after["availability_status"] == "AVAILABLE"
        assert unit_after["maintenance_posture"] == "PM_DUE"


class TestRentalReturnPmCascade:
    def _returned_at_pm_threshold(self, api, rental_coordinator_headers,
                                  serial):
        """4-day DAILY contract (provisional 60000) returned on time with
        return_hours 500, exactly the PM threshold."""
        customer = make_customer(name="Cascade Co")
        unit = make_unit(serial_number=serial)
        _c, _u, contract = make_checked_out_contract(
            customer_id=customer["id"], unit=unit,
            start_date="2026-08-01", end_date="2026-08-05")
        contract = validate_success(api.return_rental_contract(
            contract["id"], {"return_date": "2026-08-05", "return_hours": 500},
            rental_coordinator_headers))
        return customer, unit, contract

    def test_return_drives_unit_pm_due_and_in_shop(
            self, api, rental_coordinator_headers):
        """PRD §3.3: "the unit's `hour_meter` is set to `return_hours`, and if
        that reading is greater than or equal to `next_pm_due_hours` the unit's
        `maintenance_posture` flips to `PM_DUE`" and "the unit's availability
        moves to `IN_SHOP` if the posture flipped to `PM_DUE`".

        Design: Difficulty/transitive_cascade/rental_return_pm_cascade
        """
        _customer, unit, contract = self._returned_at_pm_threshold(
            api, rental_coordinator_headers, "SN-TC1")
        unit_after = get_unit(unit["id"])
        assert unit_after["hour_meter"] == 500
        assert unit_after["maintenance_posture"] == "PM_DUE"  # 500 >= 500
        assert unit_after["availability_status"] == "IN_SHOP"
        assert contract["status"] == "RETURNED"
        assert contract["final_charge_cents"] == 60000

    def test_return_auto_creates_pm_service_call(
            self, api, rental_coordinator_headers, service_dispatcher_headers):
        """PRD §3.3: "when the posture becomes `PM_DUE`, the system
        automatically opens a service call with `call_type` `PM`, the
        contract's customer, `priority` `STANDARD`, an empty `required_parts`
        list, `auto_created` set to true, and status `OPEN`."

        Design: Difficulty/transitive_cascade/rental_return_pm_cascade
        """
        customer, unit, _contract = self._returned_at_pm_threshold(
            api, rental_coordinator_headers, "SN-TC1C")
        resp = api.list_service_calls(service_dispatcher_headers,
                                      params={"unit_id": unit["id"]})
        calls, meta = validate_paginated(resp)
        assert meta["total_count"] >= 1
        auto = [c for c in calls if c.get("auto_created")]
        assert len(auto) == 1, "exactly one auto-created PM call expected"
        call = auto[0]
        assert call["call_type"] == "PM"
        assert call["status"] == "OPEN"
        assert call["auto_created"] is True
        assert call["priority"] == "STANDARD"
        assert call["required_parts"] == []
        assert call["customer_id"] == customer["id"]
