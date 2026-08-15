"""Vendor register, contract clause verification, OCC on vendor contracts,
cross-border transfer gates and cascades (PRD §2.7, §3.3, §3.7)."""
from test_helpers import (
    ApiErrorId,
    DS,
    LC1,
    NON_EXISTENT_UUID,
    PA,
    VM,
    assert_transfer,
    assert_vendor_contract,
    create_active_activity,
    create_activity_payload,
    create_approved_vendor,
    create_contract_payload,
    create_data_system,
    create_element,
    create_purpose_payload,
    create_retention_policy,
    create_transfer_payload,
    create_vendor_payload,
    get_success_data,
    publish_superseding_notice,
    setup_notice_supersede_landscape,
    setup_transfer_landscape,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVendorOffboardCascade:
    def test_vendor_offboard_cascade_depth2(self, api):
        """PRD §3.3: "Offboarding cascades. Every VendorContract of the vendor in
        DRAFT, VERIFIED, or EXECUTED status transitions to SUPERSEDED, processed
        in created_at ascending order. Every CrossBorderTransfer whose
        vendor_contract_id is one of those formerly-executed contracts and whose
        status is APPROVED transitions to SUSPENDED with suspension_reason set to
        CONTRACT_SUPERSEDED. In a direct fan-out that is not part of the hop
        chain, every CrossBorderTransfer whose vendor_id is this vendor and whose
        status is PROPOSED or UNDER_ASSESSMENT transitions to REJECTED."

        Design: Difficulty/transitive_cascade/vendor_offboard_cascade_depth2
        """
        landscape = setup_transfer_landscape()
        vendor, contract, system, activity = (landscape["vendor"], landscape["contract"],
                                              landscape["system"], landscape["activity"])
        t1 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z"),
            PA))
        get_success_data(api.assess_transfer(t1["id"], LC1))
        t1 = get_success_data(api.approve_transfer(t1["id"], LC1))
        assert t1["status"] == "APPROVED"

        # t2 is proposed against the same contract but never assessed
        t2 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-10-01T00:00:00Z", effective_to="2027-02-01T00:00:00Z"),
            PA))
        assert t2["status"] == "PROPOSED"

        offboarded = get_success_data(api.offboard_vendor(vendor["id"], PA))
        assert offboarded["status"] == "OFFBOARDED"

        contracts, _ = validate_paginated(api.list_contracts(vendor["id"], VM))
        assert contracts[0]["status"] == "SUPERSEDED", (
            "hop 1: the formerly EXECUTED contract is superseded"
        )

        t1_after = get_success_data(api.get_transfer(t1["id"], LC1))
        assert t1_after["status"] == "SUSPENDED"
        assert t1_after["suspension_reason"] == "CONTRACT_SUPERSEDED", (
            "hop 2: the APPROVED transfer on the superseded contract is suspended"
        )

        t2_after = get_success_data(api.get_transfer(t2["id"], LC1))
        assert t2_after["status"] == "REJECTED", (
            "conditional fan-out: a PROPOSED transfer is rejected, not suspended"
        )

    def test_vendor_offboard_supersedes_dormant_contracts(self, api):
        """PRD §3.3: "Offboarding cascades. Every VendorContract of the vendor in
        DRAFT, VERIFIED, or EXECUTED status transitions to SUPERSEDED, processed
        in created_at ascending order. Every CrossBorderTransfer whose
        vendor_contract_id is one of those formerly-executed contracts and whose
        status is APPROVED transitions to SUSPENDED with suspension_reason set to
        CONTRACT_SUPERSEDED."

        Design: Difficulty/transitive_cascade/vendor_offboard_cascade_depth2
        """
        landscape = setup_transfer_landscape()
        vendor, contract, system, activity = (landscape["vendor"], landscape["contract"],
                                              landscape["system"], landscape["activity"])
        t1 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z"),
            PA))
        get_success_data(api.assess_transfer(t1["id"], LC1))
        get_success_data(api.approve_transfer(t1["id"], LC1))

        # A second, dormant DRAFT contract exists alongside the EXECUTED one.
        current = get_success_data(api.get_vendor(vendor["id"], VM))
        dormant = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=current["version"]), VM))
        assert dormant["status"] == "DRAFT"

        get_success_data(api.offboard_vendor(vendor["id"], PA))

        contracts, _ = validate_paginated(api.list_contracts(vendor["id"], VM))
        by_id = {c["id"]: c for c in contracts}
        assert by_id[contract["id"]]["status"] == "SUPERSEDED", "EXECUTED -> SUPERSEDED"
        assert by_id[dormant["id"]]["status"] == "SUPERSEDED", "DRAFT -> SUPERSEDED"

        t1_after = get_success_data(api.get_transfer(t1["id"], LC1))
        assert t1_after["status"] == "SUSPENDED"
        assert t1_after["suspension_reason"] == "CONTRACT_SUPERSEDED"


class TestTransferSuspendReinstate:
    def test_transfer_suspend_reinstate_cycle(self, api):
        """PRD §3.7: "An APPROVED transfer transitions to SUSPENDED when its
        activity is placed on hold or retired — with suspension_reason set to
        ACTIVITY_HOLD — or when its contract is superseded by vendor offboarding
        — with suspension_reason set to CONTRACT_SUPERSEDED. A SUSPENDED transfer
        whose suspension_reason is ACTIVITY_HOLD transitions back to APPROVED
        with suspension_reason cleared when its owning activity resumes to
        ACTIVE."
        PRD §3.2: "Every CrossBorderTransfer in SUSPENDED with suspension_reason
        equal to ACTIVITY_HOLD whose owning activity just resumed transitions
        back to APPROVED with suspension_reason cleared to null."

        Design: Difficulty/non_linear_state_machine/transfer_suspend_reinstate_cycle
        """
        landscape = setup_notice_supersede_landscape()
        n1, purpose, activity, transfer = (landscape["n1"], landscape["purpose"],
                                           landscape["activity"], landscape["transfer"])
        assert purpose["pinned_notice_id"] == n1["id"]
        assert transfer["status"] == "APPROVED"

        n2 = publish_superseding_notice(n1["id"])
        mid = get_success_data(api.get_transfer(transfer["id"], LC1))
        assert mid["status"] == "SUSPENDED"
        assert mid["suspension_reason"] == "ACTIVITY_HOLD"

        get_success_data(api.retract_notice(n2["id"], PA))
        end = get_success_data(api.get_transfer(transfer["id"], LC1))
        assert end["status"] == "APPROVED", (
            "full cycle APPROVED -> SUSPENDED -> APPROVED driven by cascades"
        )
        assert end["suspension_reason"] is None

    def test_activity_resume_reinstates_suspended_transfer(self, api):
        """PRD §3.4: "When a resume succeeds, every CrossBorderTransfer whose
        activity_id is this activity and whose status is SUSPENDED with
        suspension_reason equal to ACTIVITY_HOLD transitions back to APPROVED
        with suspension_reason cleared."

        Design: Difficulty/non_linear_state_machine/transfer_suspend_reinstate_cycle
        """
        landscape = setup_notice_supersede_landscape()
        n1, purpose, activity, transfer = (landscape["n1"], landscape["purpose"],
                                           landscape["activity"], landscape["transfer"])
        publish_superseding_notice(n1["id"])
        assert get_success_data(api.get_activity(activity["id"], DS))["status"] == "COMPLIANCE_HOLD"
        assert get_success_data(api.get_transfer(transfer["id"], LC1))["status"] == "SUSPENDED"

        # Relink re-pins the purpose to the current PUBLISHED notice (n2); with
        # no stale purposes and no open assessments left, the activity
        # auto-resumes and reinstates its ACTIVITY_HOLD-suspended transfer.
        relinked = get_success_data(api.relink_purpose(purpose["id"], DS))
        assert relinked["status"] == "DOCUMENTED"

        a_after = get_success_data(api.get_activity(activity["id"], DS))
        assert a_after["status"] == "ACTIVE"
        t_after = get_success_data(api.get_transfer(transfer["id"], LC1))
        assert t_after["status"] == "APPROVED"
        assert t_after["suspension_reason"] is None


class TestContractLifecycle:
    def test_execute_draft_contract_returns_invalid_state(self, api):
        """PRD §3.3: "A VendorManager may then execute a VERIFIED contract,
        moving it to EXECUTED"
        PRD §2.9: "A state machine's terminal state is a lockdown: once a
        resource reaches a terminal state, no further trigger is valid against
        it, and any attempt is rejected with ERR_INVALID_STATE_TRANSITION."

        Design: Corner/endpoints/execute_draft_contract_returns_invalid_state
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=[]), VM))
        contract = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=vendor["version"]), VM))
        assert contract["status"] == "DRAFT"

        resp = api.execute_contract(contract["id"], VM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        contracts, _ = validate_paginated(api.list_contracts(vendor["id"], VM))
        assert contracts[0]["status"] == "DRAFT"

    def test_err_no_executed_contract_on_vendor_approve(self, api):
        """PRD §3.3: "Approval requires that the vendor already have at least one
        VendorContract in EXECUTED status; without one, the approve is rejected
        with ERR_NO_EXECUTED_CONTRACT."

        Design: Corner/errors/err_no_executed_contract_on_vendor_approve
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=[]), VM))
        submitted = get_success_data(api.submit_vendor_assessment(vendor["id"], VM))
        contract = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=submitted["version"]), VM))
        verified = get_success_data(api.verify_contract(contract["id"], LC1))
        assert verified["verification_status"] == "PASSED"
        assert verified["status"] == "VERIFIED"

        resp = api.approve_vendor(vendor["id"], PA)
        validate_error(resp, ApiErrorId.ERR_NO_EXECUTED_CONTRACT)
        after = get_success_data(api.get_vendor(vendor["id"], VM))
        assert after["status"] == "ASSESSMENT"

    def test_occ_contract_create_stale_vendor(self, api):
        """PRD §2.7: "A contract-creation request against a vendor must carry
        expected_vendor_version matching that vendor's current version; if the
        vendor's version has advanced since the client last read it, the create
        is rejected with ERR_STALE_VERSION (HTTP 412), because contract creation
        legitimately supersedes the vendor's existing draft and verified
        contracts, and a stale writer would supersede contracts it never
        observed."
        PRD §3.3: "Creating a newer contract for the same vendor supersedes every
        prior DRAFT or VERIFIED contract of that vendor, each of which
        transitions to SUPERSEDED."

        Design: Corner/complexity_layers/occ_contract_create_stale_vendor
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=[]), VM))
        v1 = vendor["version"]

        c1 = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=v1), VM))
        after_first = get_success_data(api.get_vendor(vendor["id"], VM))
        assert after_first["version"] == v1 + 1, "contract creation bumps Vendor.version"

        resp = api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=v1), VM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        c2 = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA", "BREACH_NOTICE_72H"],
                                    expected_vendor_version=after_first["version"]), VM))
        assert_vendor_contract(c2)

        contracts, _ = validate_paginated(api.list_contracts(vendor["id"], VM))
        by_id = {c["id"]: c for c in contracts}
        assert by_id[c1["id"]]["status"] == "SUPERSEDED", (
            "the first DRAFT contract is superseded by the newer create"
        )
        assert by_id[c2["id"]]["status"] == "DRAFT"

    def test_offboard_rejected_vendor_returns_invalid_state(self, api):
        """PRD §3.3: "Rejection moves the vendor to the terminal REJECTED
        status."
        PRD §2.9: "A state machine's terminal state is a lockdown: once a
        resource reaches a terminal state, no further trigger is valid against
        it, and any attempt is rejected with ERR_INVALID_STATE_TRANSITION."

        Design: Corner/state_machines/offboard_rejected_vendor_returns_invalid_state
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=["FINANCIAL"]), VM))
        get_success_data(api.submit_vendor_assessment(vendor["id"], VM))
        rejected = get_success_data(api.reject_vendor(vendor["id"], PA))
        assert rejected["status"] == "REJECTED"

        resp = api.offboard_vendor(vendor["id"], PA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_vendor(vendor["id"], VM))
        assert after["status"] == "REJECTED"


class TestTransferGates:
    def test_transfer_approve_requires_executed_contract(self, api):
        """PRD §3.7: "The contract gate: the contract referenced by
        vendor_contract_id must be in EXECUTED status, otherwise
        ERR_CONTRACT_NOT_EXECUTED."

        Design: Difficulty/cross_entity_state_dependency/transfer_approve_requires_executed_contract
        """
        landscape = setup_transfer_landscape()
        vendor, system, activity = (landscape["vendor"], landscape["system"],
                                    landscape["activity"])
        # Second contract: VERIFIED but never executed.
        current = get_success_data(api.get_vendor(vendor["id"], VM))
        c2 = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(
                provided_clauses=["DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT"],
                expected_vendor_version=current["version"]), VM))
        get_success_data(api.verify_contract(c2["id"], LC1))
        contracts, _ = validate_paginated(api.list_contracts(vendor["id"], VM))
        c2_state = [c for c in contracts if c["id"] == c2["id"]][0]
        assert c2_state["status"] == "VERIFIED"

        t1 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=c2["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z"),
            PA))
        get_success_data(api.assess_transfer(t1["id"], LC1))

        resp = api.approve_transfer(t1["id"], LC1)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EXECUTED)

        get_success_data(api.execute_contract(c2["id"], VM))
        approved = get_success_data(api.approve_transfer(t1["id"], LC1))
        assert approved["status"] == "APPROVED"
        assert_transfer(approved)

    def test_transfer_approve_rejects_draft_contract(self, api):
        """PRD §3.7: "The contract gate: the contract referenced by
        vendor_contract_id must be in EXECUTED status, otherwise
        ERR_CONTRACT_NOT_EXECUTED."

        Design: Difficulty/cross_entity_state_dependency/transfer_approve_requires_executed_contract
        """
        landscape = setup_transfer_landscape()
        vendor, system, activity = (landscape["vendor"], landscape["system"],
                                    landscape["activity"])
        # Second contract stays DRAFT (never verified, never executed).
        current = get_success_data(api.get_vendor(vendor["id"], VM))
        c2 = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(
                provided_clauses=["DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT"],
                expected_vendor_version=current["version"]), VM))
        assert c2["status"] == "DRAFT"

        t1 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=c2["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z"),
            PA))
        get_success_data(api.assess_transfer(t1["id"], LC1))
        resp = api.approve_transfer(t1["id"], LC1)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EXECUTED)
        after = get_success_data(api.get_transfer(t1["id"], LC1))
        assert after["status"] == "UNDER_ASSESSMENT"

    def test_mechanism_adequacy_conditional_validation(self, api):
        """PRD §3.7: "The mechanism-adequacy gate: if the source system's
        hosting_region is EU or UK and the dest_region is US, the mechanism must
        be SCC_2021 or BCR, otherwise ERR_MECHANISM_NOT_ADEQUATE."

        Design: Corner/validations/mechanism_adequacy_conditional_validation
        """
        landscape = setup_transfer_landscape(source_region="EU")
        vendor, contract, system, activity = (landscape["vendor"], landscape["contract"],
                                              landscape["system"], landscape["activity"])
        assert system["hosting_region"] == "EU"

        t1 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="US", mechanism="ADEQUACY",
                effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z"),
            PA))
        t2 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="US", mechanism="SCC_2021",
                effective_from="2026-10-01T00:00:00Z", effective_to="2027-02-01T00:00:00Z"),
            PA))

        get_success_data(api.assess_transfer(t1["id"], LC1))
        resp = api.approve_transfer(t1["id"], LC1)
        validate_error(resp, ApiErrorId.ERR_MECHANISM_NOT_ADEQUATE)
        assert get_success_data(api.get_transfer(t1["id"], LC1))["status"] == "UNDER_ASSESSMENT"

        # Same EU -> US lane with an adequate mechanism approves.
        get_success_data(api.assess_transfer(t2["id"], LC1))
        approved = get_success_data(api.approve_transfer(t2["id"], LC1))
        assert approved["status"] == "APPROVED"

    def test_transfer_window_buffer_gap(self, api):
        """PRD §3.7: "The buffer gate: no other transfer with the same
        source_system_id and vendor_id and a status of APPROVED or SUSPENDED may
        have a window within 30 days of this window on either side — the new
        transfer's effective_from must be at or after the existing transfer's
        effective_to plus 30 days, or the new transfer's effective_to must be at
        or before the existing transfer's effective_from minus 30 days —
        otherwise ERR_TRANSFER_WINDOW_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/transfer_window_buffer_gap
        """
        landscape = setup_transfer_landscape()
        vendor, contract, system, activity = (landscape["vendor"], landscape["contract"],
                                              landscape["system"], landscape["activity"])
        t1 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z"),
            PA))
        get_success_data(api.assess_transfer(t1["id"], LC1))
        get_success_data(api.approve_transfer(t1["id"], LC1))

        # 14-day gap after t1's window: inside the 30-day buffer -> conflict
        t2 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="UK", mechanism="BCR",
                effective_from="2026-09-15T00:00:00Z", effective_to="2027-01-01T00:00:00Z"),
            PA))
        get_success_data(api.assess_transfer(t2["id"], LC1))
        resp = api.approve_transfer(t2["id"], LC1)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_WINDOW_CONFLICT)
        assert get_success_data(api.get_transfer(t2["id"], LC1))["status"] == "UNDER_ASSESSMENT"

        # exactly 30 days after t1's effective_to: boundary inclusive -> approves
        t3 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="UK", mechanism="BCR",
                effective_from="2026-10-01T00:00:00Z", effective_to="2027-02-01T00:00:00Z"),
            PA))
        get_success_data(api.assess_transfer(t3["id"], LC1))
        approved = get_success_data(api.approve_transfer(t3["id"], LC1))
        assert approved["status"] == "APPROVED"

    def test_transfer_buffer_ignores_proposed_sibling(self, api):
        """PRD §3.7: "The buffer gate: no other transfer with the same
        source_system_id and vendor_id and a status of APPROVED or SUSPENDED may
        have a window within 30 days of this window on either side"

        Design: Difficulty/resource_temporal_overlap/transfer_window_buffer_gap
        """
        landscape = setup_transfer_landscape()
        vendor, contract, system, activity = (landscape["vendor"], landscape["contract"],
                                              landscape["system"], landscape["activity"])
        t1 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z"),
            PA))
        get_success_data(api.assess_transfer(t1["id"], LC1))
        get_success_data(api.approve_transfer(t1["id"], LC1))

        # An overlapping PROPOSED sibling exists but is never assessed; it is
        # neither APPROVED nor SUSPENDED so the buffer gate ignores it.
        t2 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-04-01T00:00:00Z", effective_to="2026-08-01T00:00:00Z"),
            PA))
        assert t2["status"] == "PROPOSED"

        t3 = get_success_data(api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="UK", mechanism="BCR",
                effective_from="2026-10-01T00:00:00Z", effective_to="2027-02-01T00:00:00Z"),
            PA))
        get_success_data(api.assess_transfer(t3["id"], LC1))
        approved = get_success_data(api.approve_transfer(t3["id"], LC1))
        assert approved["status"] == "APPROVED"


class TestTransferCreationReferences:
    def test_transfer_create_bad_system_fk_not_found(self, api):
        """PRD §2.8: "Path-id and body-supplied foreign-key existence
        (ERR_NOT_FOUND) comes next, with path identifiers validated
        left-to-right."
        PRD §3.7: "A PrivacyAdmin proposes a cross-border transfer by supplying a
        source_system_id, a vendor_id, a vendor_contract_id, an activity_id"

        Design: Corner/endpoints/transfer_create_bad_system_fk_not_found
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=[]), VM))
        contract = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=vendor["version"]), VM))
        element = create_element()
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Billing", business_unit="Finance",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))

        resp = api.create_transfer(
            create_transfer_payload(
                source_system_id=NON_EXISTENT_UUID, vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z"),
            PA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        transfers, _ = validate_paginated(api.list_transfers(PA))
        assert transfers == [], "no transfer row may be created"

    def test_err_system_decommissioned_on_transfer_create(self, api):
        """PRD §3.7: "The referenced source system must be in ACTIVE status —
        otherwise ERR_SYSTEM_DECOMMISSIONED — and the referenced vendor must be
        in APPROVED status — otherwise ERR_VENDOR_NOT_APPROVED."

        Design: Corner/errors/err_system_decommissioned_on_transfer_create
        """
        vendor, contract = create_approved_vendor()
        system = create_data_system(system_key="sys-old", stores_categories=["FINANCIAL"])
        get_success_data(api.decommission_data_system(system["id"], PA))
        element = create_element()
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Billing", business_unit="Finance",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))

        resp = api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-03-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z"),
            PA)
        validate_error(resp, ApiErrorId.ERR_SYSTEM_DECOMMISSIONED)
