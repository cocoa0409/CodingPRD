"""Contract pipeline tests: submit/withdraw/activate gating (PRD §3.3, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, ADMIN,
    create_landlord, create_property, create_unit, create_voucher_family,
    setup_priced_unit,
    create_draft_contract, create_and_submit_contract, create_and_approve_contract,
    make_landlord_headers,
)


class TestSubmitWithdrawRestoresZeroPortions:
    def test_submit_then_withdraw_restores_draft_and_zero_portions(self, api):
        """PRD §3.3: "If the landlord thinks better of the submission before the
        inspector records a result, withdrawing the contract moves
        `PENDING_INSPECTION` back to `DRAFT`, closes the scheduled `INITIAL`
        inspection by moving it from `SCHEDULED` to `CLOSED`, resets
        `approved_rent_cents`, `hap_portion_cents`, and `tenant_portion_cents`
        all to 0, and bumps the contract's `version`."

        Design: Difficulty/compensating_invariant/submit_withdraw_restores_zero_portions
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90018", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="FH",
        )
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date="2026-08-01",
        )
        headers = make_landlord_headers(landlord["id"])
        submitted = validate_success(api.submit_contract(contract["id"], headers))
        assert submitted["approved_rent_cents"] > 0, (
            "Setup: submit must set a positive approved rent"
        )
        withdrawn = validate_success(api.withdraw_contract(contract["id"], headers))
        assert withdrawn["status"] == "DRAFT"
        assert withdrawn["approved_rent_cents"] == 0, (
            f"withdraw must reset approved_rent_cents to 0, got "
            f"{withdrawn['approved_rent_cents']}"
        )
        assert withdrawn["hap_portion_cents"] == 0
        assert withdrawn["tenant_portion_cents"] == 0

    def test_withdraw_closes_initial_inspection(self, api):
        """PRD §3.3: "withdrawing the contract moves `PENDING_INSPECTION` back
        to `DRAFT`, closes the scheduled `INITIAL` inspection by moving it from
        `SCHEDULED` to `CLOSED`, resets `approved_rent_cents`,
        `hap_portion_cents`, and `tenant_portion_cents` all to 0, and bumps the
        contract's `version`."

        Design: Difficulty/compensating_invariant/submit_withdraw_restores_zero_portions
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90018", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="FH2",
        )
        contract = create_and_submit_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date="2026-08-01",
        )
        headers = make_landlord_headers(landlord["id"])
        validate_success(api.withdraw_contract(contract["id"], headers))
        inspections = get_success_data(api.list_contract_inspections(contract["id"], ADMIN))
        initial = [i for i in inspections if i.get("inspection_type") == "INITIAL"]
        assert initial, "the auto-created INITIAL inspection must exist"
        assert initial[0]["status"] == "CLOSED", (
            f"withdraw must close the INITIAL inspection, got {initial[0]['status']}"
        )


class TestActivateGatedByStateAndLeaseDate:
    def test_activate_before_lease_start_rejected(self, api):
        """PRD §3.5: "An admin activates the contract once the current logical
        date is on or after `lease_start_date`; attempting activation before the
        lease start is rejected with `ERR_INVALID_STATE` because the transition
        is only defined when the contract is `APPROVED` and the lease start has
        arrived."

        Design: Difficulty/cross_entity_state_dependency/contract_activate_requires_approved_and_lease_date_reached
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90014", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="FD",
        )
        # Clock default is 2026-08-01; lease starts 2026-09-01 (in the future).
        contract = create_and_approve_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date="2026-09-01",
        )
        assert contract["status"] == "APPROVED", "Setup: contract must be APPROVED"
        resp = api.activate_contract(contract["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_activate_succeeds_once_lease_start_reached(self, api):
        """PRD §3.5: "An admin activates the contract once the current logical
        date is on or after `lease_start_date`; attempting activation before the
        lease start is rejected with `ERR_INVALID_STATE` because the transition
        is only defined when the contract is `APPROVED` and the lease start has
        arrived."

        Design: Difficulty/cross_entity_state_dependency/contract_activate_requires_approved_and_lease_date_reached
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90014", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="FD2",
        )
        contract = create_and_approve_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date="2026-09-01",
        )
        # Advance the logical clock to the lease start date (PRD §2.7).
        get_success_data(api.set_current_utc("2026-09-01T00:00:00Z", ADMIN))
        data = validate_success(api.activate_contract(contract["id"], ADMIN))
        assert data["status"] == "ACTIVE"


class TestSecondSubmitRejected:
    def test_resubmit_pending_inspection_rejected_invalid_state(self, api):
        """PRD §3.3: "Submission is only defined from `DRAFT`, is owner-only,
        and requires `contract_rent_cents` to be greater than zero."
        PRD §2.5: "then whether the target resource is in a state from which the
        requested transition is defined (`ERR_INVALID_STATE`); then the
        optimistic-concurrency version match (`ERR_STALE_VERSION`); then the
        landlord-ownership check (`ERR_NOT_OWNER`); then the landlord-active
        check (`ERR_LANDLORD_SUSPENDED`); then the rent-increase timing check
        (`ERR_INCREASE_TOO_EARLY`); then the inspection-schedule timing check
        (`ERR_SCHEDULE_IN_PAST`); then the voucher-size match
        (`ERR_VOUCHER_SIZE_MISMATCH`); then the one-live-contract-per-unit check
        (`ERR_UNIT_ALREADY_UNDER_CONTRACT`); then amount positivity
        (`ERR_INVALID_AMOUNT`)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_contract_submit
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90010", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="F9",
        )
        contract = create_and_submit_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date="2026-08-01",
        )
        assert contract["status"] == "PENDING_INSPECTION"
        resp = api.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_resubmit_after_withdraw_succeeds(self, api):
        """PRD §3.3: "Submission is only defined from `DRAFT`, is owner-only,
        and requires `contract_rent_cents` to be greater than zero."
        PRD §3.3: "withdrawing the contract moves `PENDING_INSPECTION` back to
        `DRAFT`, closes the scheduled `INITIAL` inspection by moving it from
        `SCHEDULED` to `CLOSED`, resets `approved_rent_cents`,
        `hap_portion_cents`, and `tenant_portion_cents` all to 0, and bumps the
        contract's `version`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_contract_submit
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90010", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="F9b",
        )
        headers = make_landlord_headers(landlord["id"])
        contract = create_and_submit_contract(
            unit, family, landlord,
            contract_rent_cents=150_000, lease_start_date="2026-08-01",
        )
        withdrawn = validate_success(api.withdraw_contract(contract["id"], headers))
        assert withdrawn["status"] == "DRAFT"
        resubmitted = validate_success(api.submit_contract(contract["id"], headers))
        assert resubmitted["status"] == "PENDING_INSPECTION"


class TestSuspendedLandlordContractCreate:
    def test_create_contract_while_suspended_rejected(self, api):
        """PRD §2.6: "A landlord whose `status` is `SUSPENDED` or `TERMINATED`
        may not create a property, may not create a unit within a property, and
        may not initiate a new HAP contract; any of those attempts is rejected
        with `ERR_LANDLORD_SUSPENDED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/contract_create_blocked_by_suspended_landlord
        """
        landlord = create_landlord(legal_name="L 14", tax_id="T14")
        prop = create_property(landlord["id"], address="14 N St", zip_code="90015")
        unit = create_unit(prop["id"], unit_label="UE", bedroom_count=1)
        family = create_voucher_family(
            family_code="FE", voucher_bedroom_size=1, annual_income_cents=2_400_000,
        )
        get_success_data(api.suspend_landlord(landlord["id"], ADMIN))
        resp = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": unit["version"],
            },
            make_landlord_headers(landlord["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LANDLORD_SUSPENDED)

    def test_create_property_while_suspended_rejected(self, api):
        """PRD §3.1: "Either an admin or the owning landlord may create
        properties and units, but only while the landlord's `status` is `ACTIVE`
        — a suspended landlord is blocked from adding inventory with
        `ERR_LANDLORD_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/contract_create_blocked_by_suspended_landlord
        """
        landlord = create_landlord(legal_name="L 14b", tax_id="T14b")
        get_success_data(api.suspend_landlord(landlord["id"], ADMIN))
        resp = api.create_property(
            {"landlord_id": landlord["id"], "address": "14 N St", "zip_code": "90015"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_LANDLORD_SUSPENDED)


class TestSuspendedVsVoucherSizePriority:
    def test_suspended_beats_voucher_size_mismatch(self, api):
        """PRD §2.5: "then the landlord-ownership check (`ERR_NOT_OWNER`); then
        the landlord-active check (`ERR_LANDLORD_SUSPENDED`); then the
        rent-increase timing check (`ERR_INCREASE_TOO_EARLY`); then the
        inspection-schedule timing check (`ERR_SCHEDULE_IN_PAST`); then the
        voucher-size match (`ERR_VOUCHER_SIZE_MISMATCH`)"

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_contract_create
        """
        landlord = create_landlord(legal_name="L Ten", tax_id="T10")
        prop = create_property(landlord["id"], address="10 J St", zip_code="90011")
        unit = create_unit(prop["id"], unit_label="U10", bedroom_count=1)
        family = create_voucher_family(
            family_code="F10", voucher_bedroom_size=0, annual_income_cents=2_400_000,
        )
        get_success_data(api.suspend_landlord(landlord["id"], ADMIN))
        # Both ERR_LANDLORD_SUSPENDED and ERR_VOUCHER_SIZE_MISMATCH are
        # triggered; the fixed priority order resolves to ERR_LANDLORD_SUSPENDED.
        resp = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": unit["version"],
            },
            make_landlord_headers(landlord["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LANDLORD_SUSPENDED)

    def test_active_landlord_with_size_mismatch_reports_mismatch(self, api):
        """PRD §3.3: "the family's `voucher_bedroom_size` must be at least the
        unit's `bedroom_count`, since a family may under-occupy a smaller unit
        but may not over-occupy a larger one (`ERR_VOUCHER_SIZE_MISMATCH`)"

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_contract_create
        """
        landlord = create_landlord(legal_name="L Ten b", tax_id="T10b")
        prop = create_property(landlord["id"], address="10 J St", zip_code="90011")
        unit = create_unit(prop["id"], unit_label="U10b", bedroom_count=1)
        family = create_voucher_family(
            family_code="F10b", voucher_bedroom_size=0, annual_income_cents=2_400_000,
        )
        # Landlord ACTIVE here: only the size-mismatch rule fires.
        resp = api.create_contract(
            {
                "unit_id": unit["id"],
                "family_id": family["id"],
                "contract_rent_cents": 150_000,
                "lease_start_date": "2026-08-01",
                "expected_unit_version": unit["version"],
            },
            make_landlord_headers(landlord["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOUCHER_SIZE_MISMATCH)
