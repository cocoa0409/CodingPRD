"""Payer registration, contract lifecycle, and rate materialization."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_active_contract,
    create_contract,
    create_facility,
    create_payer,
    create_rate,
    create_service_item,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    create_contract_payload,
    create_payer_payload,
    create_service_item_payload,
)
from test_helpers.fixtures import ADMIN, AUDITOR, CONSUMER, MANAGER, OFFICER


class TestPayerCreateValidation:
    def test_payer_create_missing_required_field_rejected(self, api):
        """PRD section 3.2: "A `rate_percent` from 0 to 200 inclusive is required exactly when the type is `PERCENT_OF_GROSS` or `PERCENT_OF_MEDICARE`, and `flat_amount_cents` is required exactly when the type is `FEE_SCHEDULE_FLAT`; omitting the required input, or sending the wrong type or an unknown enum value anywhere in a payload, is rejected with `ERR_INVALID_REQUEST`."
        PRD section 3.1: "A `ContractManager` then registers payer organizations with a `name`, a `payer_type` of `COMMERCIAL`, `MEDICARE_ADVANTAGE`, or `MEDICAID_MANAGED`, and a `confidentiality_tier` of `STANDARD` or `PROPRIETARY` (default `STANDARD`)."

        Design: Corner/entities/payer_create_missing_required_field_rejected
        """
        resp = api.create_payer({"name": "PA"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_payer_create_invalid_enum_rejected(self, api):
        """PRD section 3.2: "A `rate_percent` from 0 to 200 inclusive is required exactly when the type is `PERCENT_OF_GROSS` or `PERCENT_OF_MEDICARE`, and `flat_amount_cents` is required exactly when the type is `FEE_SCHEDULE_FLAT`; omitting the required input, or sending the wrong type or an unknown enum value anywhere in a payload, is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/payer_create_invalid_enum_rejected
        """
        resp = api.create_payer({"name": "PA", "payer_type": "TRICARE"},
                                MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestContractWindow:
    def test_contract_inverted_window_rejected(self, api):
        """PRD section 3.1: "The contract window is a closed interval — both endpoints are inclusive — and `effective_start` must not fall after `effective_end`, or creation is rejected with `ERR_INVALID_WINDOW`."

        Design: Corner/validations/contract_inverted_window_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-H3",
                              bed_count=50)
        payer = create_payer(name="PA")
        resp = api.create_payer_contract(
            create_contract_payload(
                fac["id"], payer["id"],
                effective_start="2026-12-31T00:00:00Z",
                effective_end="2026-01-01T00:00:00Z"),
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_contract_window_touching_endpoints_conflict(self, api):
        """PRD section 3.8: "Activation re-checks the window (`effective_start` must not fall after `effective_end`, else `ERR_INVALID_WINDOW`) and enforces single active coverage: no other `ACTIVE` contract may exist for the same `facility_id` and `payer_id` whose closed window intersects this one, and because contract windows are closed intervals, windows that touch at an endpoint count as intersecting; a violation is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_window_touching_endpoints_conflict
        """
        fac = create_facility(name="F", cms_certification_number="CCN-T1",
                              bed_count=100)
        payer = create_payer(name="PA")
        c1 = create_active_contract(
            fac["id"], payer["id"],
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-06-30T00:00:00Z")
        assert c1["status"] == "ACTIVE"
        # C2 touches C1 at 2026-06-30; closed intervals make that an overlap.
        c2 = create_contract(fac["id"], payer["id"],
                             effective_start="2026-06-30T00:00:00Z",
                             effective_end="2026-12-31T00:00:00Z")
        resp = api.activate_contract(c2["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)
        c2_after = _get_contract(api, fac["id"], c2["id"])
        assert c2_after["status"] == "DRAFT", \
            "C2 must remain DRAFT after the failed activation"

    def test_contract_window_gap_activates_cleanly(self, api):
        """PRD section 3.8: "Activation re-checks the window (`effective_start` must not fall after `effective_end`, else `ERR_INVALID_WINDOW`) and enforces single active coverage: no other `ACTIVE` contract may exist for the same `facility_id` and `payer_id` whose closed window intersects this one, and because contract windows are closed intervals, windows that touch at an endpoint count as intersecting; a violation is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_window_touching_endpoints_conflict
        """
        fac = create_facility(name="F", cms_certification_number="CCN-T1",
                              bed_count=100)
        payer = create_payer(name="PA")
        create_active_contract(fac["id"], payer["id"],
                               effective_start="2026-01-01T00:00:00Z",
                               effective_end="2026-06-30T00:00:00Z")
        # C3 starts one day strictly after C1's inclusive end: no intersection.
        c3 = create_contract(fac["id"], payer["id"],
                             effective_start="2026-07-01T00:00:00Z",
                             effective_end="2026-12-31T00:00:00Z")
        c3 = get_success_data(api.activate_contract(c3["id"], MANAGER))
        assert c3["status"] == "ACTIVE"


class TestContractTerminalAndExpiry:
    def test_contract_terminal_lockdown_activate_after_terminate(self, api):
        """PRD section 3.8: "Activation is defined from `DRAFT` and from `RENEGOTIATING`; attempting it — or renegotiation or termination — from `TERMINATED` or `EXPIRED`, or attempting renegotiation or termination from anything but `ACTIVE`, is rejected with `ERR_CONTRACT_ALREADY_TERMINAL`."

        Design: Corner/state_machines/contract_terminal_lockdown_activate_after_terminate
        """
        fac = create_facility(name="F", cms_certification_number="CCN-SM1",
                              bed_count=50)
        payer = create_payer(name="PA")
        c = create_active_contract(fac["id"], payer["id"])
        c = get_success_data(api.terminate_contract(c["id"], MANAGER))
        assert c["status"] == "TERMINATED"
        resp = api.activate_contract(c["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_ALREADY_TERMINAL)
        c_after = _get_contract(api, fac["id"], c["id"])
        assert c_after["status"] == "TERMINATED"

    def test_contract_renegotiate_from_draft_rejected(self, api):
        """PRD section 3.8: "Activation is defined from `DRAFT` and from `RENEGOTIATING`; attempting it — or renegotiation or termination — from `TERMINATED` or `EXPIRED`, or attempting renegotiation or termination from anything but `ACTIVE`, is rejected with `ERR_CONTRACT_ALREADY_TERMINAL`."

        Design: Corner/state_machines/contract_renegotiate_from_draft_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-SM2",
                              bed_count=50)
        payer = create_payer(name="PA")
        c = create_contract(fac["id"], payer["id"])
        assert c["status"] == "DRAFT"
        resp = api.renegotiate_contract(c["id"], {}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_ALREADY_TERMINAL)
        c_after = _get_contract(api, fac["id"], c["id"])
        assert c_after["status"] == "DRAFT"

    def test_contract_expiry_via_clock_cascades_rates_inactive(self, api):
        """PRD section 2.5: "Advancing the clock is a system event with three scheduled consequences: every `ACTIVE` payer contract whose `effective_end` date now lies strictly before the new current date transitions to `EXPIRED` (firing the same rate cascade as a termination); every facility whose `attestation_status` is `REJECTED` and whose `plan_due_date` now lies strictly before the new clock transitions to `ESCALATED`; and `penalty_accrued_cents` is recomputed for every facility sitting in `REJECTED` or `ESCALATED`."
        PRD section 3.8: "Rate states therefore mirror their contract's lifecycle without any direct write to the rate: drafts activate with the contract, actives return to draft on renegotiation, and actives go inactive on termination or expiry; only the create-with-supersede of §3.2 moves a rate on its own."

        Design: Corner/state_machines/contract_expiry_via_clock_cascades_rates_inactive
        """
        fac = create_facility(name="F", cms_certification_number="CCN-SM7",
                              bed_count=50)
        payer = create_payer(name="PA")
        contract = create_contract(
            fac["id"], payer["id"],
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-08-15T00:00:00Z")
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000)
        rate = create_rate(contract["id"], item["id"], rate_percent=40)
        contract = get_success_data(
            api.activate_contract(contract["id"], MANAGER))
        assert contract["status"] == "ACTIVE"
        # 2026-08-16 is strictly after the inclusive end 2026-08-15.
        get_success_data(api.set_clock(
            {"to_iso8601": "2026-08-16T00:00:00Z"}, ADMIN))
        contracts, _ = validate_paginated(
            api.list_payer_contracts(payer["id"], MANAGER))
        assert len(contracts) == 1
        assert contracts[0]["status"] == "EXPIRED"
        rate_after = get_success_data(api.get_rate(rate["id"], MANAGER))
        assert rate_after["status"] == "INACTIVE"


class TestRenegotiationCycle:
    def test_rate_patch_locked_while_contract_active(self, api):
        """PRD section 3.2: "A rate amendment — a `ContractManager` changing `rate_percent` or `flat_amount_cents` — is permitted only while the rate itself is `DRAFT`; amending a rate in any other status is rejected with `ERR_RATE_LOCKED`."
        PRD section 3.8: "Renegotiation moves an `ACTIVE` contract to `RENEGOTIATING`, optionally applying a new `effective_end` or a new `confidentiality_clause` from the request, and fires the mirror cascade: the contract's `ACTIVE` rates return to `DRAFT` so they can be edited again, affected records recompute with those draft rates now excluded from their input sets, and affected cycles recompute and increment."

        Design: Difficulty/non_linear_state_machine/contract_renegotiation_cycle_restores_editable_rates
        """
        fac = create_facility(name="F", cms_certification_number="CCN-S1",
                              bed_count=100)
        payer = create_payer(name="PA")
        contract = create_contract(fac["id"], payer["id"])
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000)
        rate = create_rate(contract["id"], item["id"], rate_percent=40)
        get_success_data(api.activate_contract(contract["id"], MANAGER))
        # While ACTIVE, the rate is locked against amendment.
        resp = api.patch_rate(rate["id"], {"rate_percent": 50}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_RATE_LOCKED)
        # Renegotiation returns the rate to DRAFT and the same patch succeeds.
        contract = get_success_data(api.renegotiate_contract(
            contract["id"], {"effective_end": "2027-06-30T00:00:00Z"},
            MANAGER))
        assert contract["status"] == "RENEGOTIATING"
        rate = get_success_data(
            api.patch_rate(rate["id"], {"rate_percent": 50}, MANAGER))
        # floor(100000 * 50 / 100) re-materialized on the draft amendment.
        assert rate["negotiated_amount_cents"] == 50000

    def test_renegotiation_cycle_reactivates_amended_rate(self, api):
        """PRD section 3.2: "The amendment recomputes `negotiated_amount_cents` and increments the rate's `version`, but it does not run the charge-record recompute cascade, because `DRAFT` rates are excluded from every record's input set to begin with."
        PRD section 3.8: "Contracts move through `DRAFT → ACTIVE → RENEGOTIATING → ACTIVE`, with `TERMINATED` and `EXPIRED` as terminal states, and every move ripples down the cascade chain of §2.8."

        Design: Difficulty/non_linear_state_machine/contract_renegotiation_cycle_restores_editable_rates
        """
        fac = create_facility(name="F", cms_certification_number="CCN-S1",
                              bed_count=100)
        payer = create_payer(name="PA")
        contract = create_contract(fac["id"], payer["id"])
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000)
        rate = create_rate(contract["id"], item["id"], rate_percent=40)
        get_success_data(api.activate_contract(contract["id"], MANAGER))
        get_success_data(api.renegotiate_contract(
            contract["id"], {"effective_end": "2027-06-30T00:00:00Z"},
            MANAGER))
        get_success_data(api.patch_rate(rate["id"], {"rate_percent": 50},
                                        MANAGER))
        # Re-activation closes the ACTIVE -> RENEGOTIATING -> ACTIVE loop and
        # materializes the amended percentage.
        contract = get_success_data(
            api.activate_contract(contract["id"], MANAGER))
        assert contract["status"] == "ACTIVE"
        rate = get_success_data(api.get_rate(rate["id"], MANAGER))
        assert rate["status"] == "ACTIVE"
        assert rate["negotiated_amount_cents"] == 50000


class TestRateCreateGuards:
    def test_rate_create_on_terminated_contract_rejected(self, api):
        """PRD section 3.2: "Rates may only be created while the owning contract is `DRAFT` or `RENEGOTIATING`; against any other contract status the attempt is rejected with `ERR_CONTRACT_NOT_EDITABLE`."

        Design: Corner/errors/rate_create_on_terminated_contract_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-ER4",
                              bed_count=50)
        payer = create_payer(name="PA")
        contract = create_active_contract(fac["id"], payer["id"])
        get_success_data(api.terminate_contract(contract["id"], MANAGER))
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000)
        resp = api.create_rate(
            {"contract_id": contract["id"], "service_item_id": item["id"],
             "rate_type": "FEE_SCHEDULE_FLAT", "flat_amount_cents": 1000},
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EDITABLE)

    def test_rate_create_missing_item_and_locked_contract_returns_not_found(
            self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung."
        PRD section 2.9: "Consequently, a state error always masks a temporal error on the same request, and a missing resource always masks both."

        Design: Difficulty/priority_pair_validation_conflict/rate_create_missing_item_and_locked_contract_returns_not_found
        """
        fac = create_facility(name="F", cms_certification_number="CCN-V1",
                              bed_count=100)
        payer = create_payer(name="PA")
        contract = create_active_contract(fac["id"], payer["id"])
        # The body FK (service_item_id) does not exist AND the contract is in
        # a non-editable state; the existence rung fires first.
        resp = api.create_rate(
            {"contract_id": contract["id"],
             "service_item_id": NON_EXISTENT_UUID,
             "rate_type": "FEE_SCHEDULE_FLAT", "flat_amount_cents": 1000},
            MANAGER)
        err = validate_error(resp, ApiErrorId.ERR_SERVICE_ITEM_NOT_FOUND)
        assert resp.status_code == 404
        assert err["error_id"] != ApiErrorId.ERR_CONTRACT_NOT_EDITABLE

    def test_rate_create_missing_item_persists_nothing(self, api):
        """PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung."

        Design: Difficulty/priority_pair_validation_conflict/rate_create_missing_item_and_locked_contract_returns_not_found
        """
        fac = create_facility(name="F", cms_certification_number="CCN-V1",
                              bed_count=100)
        payer = create_payer(name="PA")
        contract = create_active_contract(fac["id"], payer["id"])
        resp = api.create_rate(
            {"contract_id": contract["id"],
             "service_item_id": NON_EXISTENT_UUID,
             "rate_type": "FEE_SCHEDULE_FLAT", "flat_amount_cents": 1000},
            MANAGER)
        assert resp.status_code == 404
        # The rejected request left no rate behind for the contract.
        rates, meta = validate_paginated(
            api.list_rates(MANAGER, params={"contract_id": contract["id"]}))
        assert rates == []
        assert meta["total_count"] == 0


class TestRateMaterialization:
    def test_flat_fee_schedule_materialization_ignores_item_gross(self, api):
        """PRD section 3.2: "A `FEE_SCHEDULE_FLAT` rate materializes to its `flat_amount_cents` verbatim and is item-independent."
        PRD section 3.2: "Every rate carries a materialized `negotiated_amount_cents`, recomputed on creation, on any rate amendment, and whenever the underlying item's `gross_charge_cents` or `medicare_base_cents` changes."

        Design: Corner/calculations/flat_fee_schedule_materialization_ignores_item_gross
        """
        fac = create_facility(name="F", cms_certification_number="CCN-K1",
                              bed_count=50)
        payer = create_payer(name="PA")
        contract = create_contract(fac["id"], payer["id"])
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000)
        rate = create_rate(contract["id"], item["id"],
                           rate_type="FEE_SCHEDULE_FLAT",
                           flat_amount_cents=12345)
        assert rate["negotiated_amount_cents"] == 12345
        get_success_data(api.activate_contract(contract["id"], MANAGER))
        # A gross PATCH re-materializes percent-based rates but not this one.
        get_success_data(api.patch_service_item(
            item["id"], {"gross_charge_cents": 200000,
                         "expected_service_item_version": item["version"]},
            OFFICER))
        rate = get_success_data(api.get_rate(rate["id"], MANAGER))
        assert rate["negotiated_amount_cents"] == 12345

    def test_percent_of_medicare_tracks_medicare_base_only(self, api):
        """PRD section 3.2: "A `PERCENT_OF_MEDICARE` rate materializes to the item's current `medicare_base_cents` multiplied by `rate_percent` and divided by 100, truncated down to a whole cent."
        PRD section 3.2: "The materialization reads the item's current field values — never a snapshot — and branches on the rate type."

        Design: Corner/calculations/percent_of_medicare_tracks_medicare_base_only
        """
        fac = create_facility(name="F", cms_certification_number="CCN-K2",
                              bed_count=50)
        payer = create_payer(name="PA")
        contract = create_contract(fac["id"], payer["id"])
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000,
                                   medicare_base_cents=20000)
        rate = create_rate(contract["id"], item["id"],
                           rate_type="PERCENT_OF_MEDICARE", rate_percent=150)
        # floor(20000 * 150 / 100)
        assert rate["negotiated_amount_cents"] == 30000
        get_success_data(api.activate_contract(contract["id"], MANAGER))
        get_success_data(api.patch_service_item(
            item["id"], {"medicare_base_cents": 30000,
                         "expected_service_item_version": item["version"]},
            OFFICER))
        rate = get_success_data(api.get_rate(rate["id"], MANAGER))
        # floor(30000 * 150 / 100)
        assert rate["negotiated_amount_cents"] == 45000
        items, _ = validate_paginated(
            api.list_service_items(fac["id"], OFFICER))
        assert items[0]["gross_charge_cents"] == 100000, \
            "the medicare-base patch must leave gross untouched"


class TestImmediateConsistency:
    def test_immediate_consistency_read_after_write(self, api):
        """PRD section 2.4: "All mutations and their cascades are applied atomically within the triggering request: the system never exposes a half-applied cascade."
        PRD section 3.1: "Each negotiated relationship becomes a `PayerContract`, created in `DRAFT` status with the contracting `facility_id` and `payer_id`, a `confidentiality_clause` of `DISCLOSE_ALLOWED`, `DERIVED_ONLY`, or `AGGREGATE_ONLY`, a projected `annual_volume` used later as the weight in weighted derivation, and a contract window from `effective_start` through `effective_end`."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        fac = create_facility(name="F", cms_certification_number="CCN-CM1",
                              bed_count=50)
        payer = create_payer(name="PA")
        contract = create_contract(fac["id"], payer["id"])
        contracts, _ = validate_paginated(
            api.list_payer_contracts(payer["id"], CONSUMER))
        assert len(contracts) == 1
        assert contracts[0]["status"] == "DRAFT"
        get_success_data(api.activate_contract(contract["id"], MANAGER))
        contracts, _ = validate_paginated(
            api.list_payer_contracts(payer["id"], CONSUMER))
        assert contracts[0]["status"] == "ACTIVE"


def _get_contract(api, facility_id, contract_id):
    contracts, _ = validate_paginated(
        api.list_facility_contracts(facility_id, MANAGER))
    for c in contracts:
        if c["id"] == contract_id:
            return c
    raise AssertionError(f"contract {contract_id} not found in facility list")
