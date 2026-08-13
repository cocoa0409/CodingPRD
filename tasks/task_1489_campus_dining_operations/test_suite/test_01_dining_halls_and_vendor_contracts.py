"""Dining hall onboarding/defaults, vendor-contract exclusivity, contract
lifecycle sweeps, and the contract-active gate on statement finalization."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_dining_hall,
    assert_millis_timestamp,
    create_active_contract,
    create_dining_hall_payload,
    create_hall,
    create_statement,
    create_vendor_contract_payload,
    get_contract,
    get_statement,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["dining_admin_headers"]
CONTRACT_MANAGER = TEST_USERS["contract_manager_headers"]


class TestDiningHallCreation:
    def test_hall_created_active_with_server_minted_id(self, api):
        """PRD §3.1: "A new hall starts `ACTIVE`."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as
        a UUID, with no type prefix."

        Design: Corner/entities/dining_hall_creation_defaults_and_client_id_input_ignored
        """
        client_id = "00000000-0000-0000-0000-000000000000"
        payload = create_dining_hall_payload(
            name="Default Hall", service_model="HYBRID", dining_capacity=500,
            catering_kitchen_capacity=200)
        payload["id"] = client_id
        hall = validate_success(api.create_dining_hall(payload, ADMIN),
                                expected_status=201)
        assert_dining_hall(hall)
        assert hall["status"] == "ACTIVE"
        assert is_valid_uuid(hall["id"])
        assert hall["id"] != client_id, (
            "the server mints the id; a client-supplied id field is ignored")
        assert_millis_timestamp(hall["created_at"], "created_at")
        assert_millis_timestamp(hall["updated_at"], "updated_at")
        assert isinstance(hall["version"], int)

    def test_hall_create_missing_name_and_bad_enum_rejected(self, api):
        """PRD §2.7: "10. **Field shape** — required fields present, enum values
        in range, date intervals with start before end, swipe amounts consistent
        with entry type, worked-minutes bounds, invoice-total bounds; failures
        yield `ERR_VALIDATION`."

        Design: Corner/entities/dining_hall_field_validation_rejections
        """
        missing_name = create_dining_hall_payload(
            service_model="BOARD", dining_capacity=500, catering_kitchen_capacity=200)
        del missing_name["name"]
        resp1 = api.create_dining_hall(missing_name, ADMIN)
        validate_error(resp1, ApiErrorId.ERR_VALIDATION)

        bad_enum = create_dining_hall_payload(
            name="X", service_model="BUFFET", dining_capacity=500,
            catering_kitchen_capacity=200)
        resp2 = api.create_dining_hall(bad_enum, ADMIN)
        validate_error(resp2, ApiErrorId.ERR_VALIDATION)


class TestVendorContractLifecycle:
    def test_second_active_contract_rejected(self, api):
        """PRD §3.1: "activation is refused with `ERR_DUPLICATE_ACTIVE_CONTRACT`
        when another contract at the same hall is already `ACTIVE`, since a hall
        has at most one active vendor agreement."

        Design: Corner/errors/duplicate_active_contract_rejected
        """
        hall = create_hall(name="Hall E1")
        create_active_contract(hall["id"], vendor_name="VA")
        c2 = validate_success(api.create_vendor_contract(
            create_vendor_contract_payload(hall["id"], vendor_name="VB"),
            ADMIN), expected_status=201)
        assert c2["status"] == "NEGOTIATION"
        resp = api.activate_vendor_contract(c2["id"], CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CONTRACT)
        c2_after = get_contract(c2["id"])
        assert c2_after["status"] == "NEGOTIATION"

    def test_clock_sweep_expires_contract_at_end_date_boundary(self, api):
        """PRD §2.4: "First, every vendor contract in `ACTIVE` status whose
        `effective_end_date` is less than or equal to the new clock value
        transitions to `EXPIRED` — because the contract's effective interval is
        half-open, a contract whose end date equals the new clock value expires
        at that instant."

        Design: Corner/cross_cutting_layers/clock_sweep_expires_contract
        """
        hall = create_hall(name="Hall L3")
        contract = create_active_contract(hall["id"], vendor_name="SweepV",
                                          start="2026-08-01", end="2026-09-01")

        sweep1 = set_clock("2026-08-31T23:59:59Z")
        assert contract["id"] not in sweep1["expired_contract_ids"]
        assert get_contract(contract["id"])["status"] == "ACTIVE"

        sweep2 = set_clock("2026-09-01T00:00:00Z")
        assert contract["id"] in sweep2["expired_contract_ids"]
        assert get_contract(contract["id"])["status"] == "EXPIRED"


class TestFinalizeRequiresContractActive:
    def test_finalize_terminated_contract_rejected(self, api):
        """PRD §3.9: "Finalization (`PROVISIONAL` → `FINALIZED`) is a
        `ContractManager` act that again requires the contract to be `ACTIVE`
        (else `ERR_CONTRACT_NOT_ACTIVE`); it recomputes every monetary field
        under the final variant — stricter period inclusion, paid-only catering
        on final totals, and the guarantee top-up — and stamps `finalized_at`
        with the logical clock."

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_contract_active
        """
        hall = create_hall(name="Hall XE2", service_model="RETAIL")
        contract = create_active_contract(hall["id"], vendor_name="V")
        statement = create_statement(contract["id"], "2026-08")
        assert statement["status"] == "PROVISIONAL"

        term_resp = api.terminate_vendor_contract(contract["id"], CONTRACT_MANAGER)
        assert term_resp.status_code == 200

        resp = api.finalize_commission_statement(statement["id"], CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        after = get_statement(statement["id"])
        assert after["status"] == "PROVISIONAL"
        assert after["finalized_at"] is None

    def test_statement_create_on_negotiation_contract_rejected(self, api):
        """PRD §3.9: "A `DiningAdmin` generates a statement for a contract by
        naming the `period_month` in `YYYY-MM` form; the statement is bound to
        the contract through its `vendor_contract_id`, the contract must be
        `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`), and at most one statement may
        exist per contract and month (else `ERR_DUPLICATE_STATEMENT`)."

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_contract_active
        """
        hall = create_hall(name="Hall XE2b", service_model="RETAIL")
        contract = validate_success(api.create_vendor_contract(
            create_vendor_contract_payload(hall["id"], vendor_name="V-neg"),
            ADMIN), expected_status=201)
        assert contract["status"] == "NEGOTIATION"
        resp = api.create_commission_statement(
            contract["id"], {"period_month": "2026-08"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
