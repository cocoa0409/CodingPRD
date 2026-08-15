"""Validation priority on transfer creation, OCC on element reclassification,
initial states, terminal lockdowns, read-after-write consistency, and the
activate/retire risk-total invariant (PRD §2.4, §2.7, §2.8, §3)."""
from test_helpers import (
    ApiErrorId,
    BO1,
    DS,
    LC1,
    LC2,
    PA,
    VM,
    assert_activity,
    assert_rights_request,
    create_activity_payload,
    create_activity_with_manual_assessment,
    create_consumer,
    create_consumer_and_request,
    create_contract_payload,
    create_data_element_payload,
    create_data_system_payload,
    create_element,
    create_notice_payload,
    create_purpose_payload,
    create_retention_policy,
    create_transfer_payload,
    create_vendor_payload,
    get_success_data,
    make_consumer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestValidationPriorityOnTransferCreate:
    def test_referential_vs_temporal_on_transfer_create(self, api):
        """PRD §2.8: "then referenced-entity state checks (ERR_NO_PUBLISHED_NOTICE,
        ERR_ELEMENT_RETIRED, ERR_VENDOR_NOT_APPROVED, ERR_SYSTEM_DECOMMISSIONED,
        ERR_CONTRACT_NOT_EXECUTED, ERR_NO_EXECUTED_CONTRACT), then temporal
        window validity (ERR_INVALID_WINDOW, ERR_NOTICE_WINDOW_OVERLAP)"

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_transfer_create
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=["FINANCIAL"]), VM))
        submitted = get_success_data(api.submit_vendor_assessment(vendor["id"], VM))
        contract = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=submitted["version"]), VM))
        system = get_success_data(api.create_data_system(
            create_data_system_payload(system_key="sys-crm", hosting_region="US",
                                       stores_categories=["FINANCIAL"]), PA))
        element = create_element()
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Billing", business_unit="Finance",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))

        # Vendor is ASSESSMENT (not APPROVED) AND the window is inverted; the
        # referenced-entity state check outranks temporal window validity.
        resp = api.create_transfer(
            create_transfer_payload(
                source_system_id=system["id"], vendor_id=vendor["id"],
                vendor_contract_id=contract["id"], activity_id=activity["id"],
                dest_region="EU", mechanism="SCC_2021",
                effective_from="2026-09-01T00:00:00Z", effective_to="2026-03-01T00:00:00Z"),
            PA)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_APPROVED)

        transfers, _ = validate_paginated(api.list_transfers(PA))
        assert transfers == [], "no CrossBorderTransfer row may be created"

    def test_rejected_vendor_beats_inverted_window(self, api):
        """PRD §2.8: "then referenced-entity state checks (ERR_NO_PUBLISHED_NOTICE,
        ERR_ELEMENT_RETIRED, ERR_VENDOR_NOT_APPROVED, ERR_SYSTEM_DECOMMISSIONED,
        ERR_CONTRACT_NOT_EXECUTED, ERR_NO_EXECUTED_CONTRACT), then temporal
        window validity (ERR_INVALID_WINDOW, ERR_NOTICE_WINDOW_OVERLAP)"
        PRD §3.7: "the referenced vendor must be in APPROVED status — otherwise
        ERR_VENDOR_NOT_APPROVED"

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_transfer_create
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=["FINANCIAL"]), VM))
        submitted = get_success_data(api.submit_vendor_assessment(vendor["id"], VM))
        contract = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=submitted["version"]), VM))
        rejected = get_success_data(api.reject_vendor(vendor["id"], PA))
        assert rejected["status"] == "REJECTED"

        system = get_success_data(api.create_data_system(
            create_data_system_payload(system_key="sys-crm", hosting_region="US",
                                       stores_categories=["FINANCIAL"]), PA))
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
                effective_from="2026-09-01T00:00:00Z", effective_to="2026-03-01T00:00:00Z"),
            PA)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_APPROVED)


class TestOccReclassify:
    def test_occ_reclassify_stale_version(self, api):
        """PRD §2.7: "A reclassification request on a data element must carry
        expected_element_version matching the element's current version; if
        another writer has advanced the element's version since the client last
        read it, the request is rejected with ERR_STALE_VERSION (HTTP 412),
        because reclassification legitimately overwrites the category and
        classification and cascades into activity risk, and a stale writer would
        silently undo a reclassification it never observed."

        Design: Corner/complexity_layers/occ_reclassify_stale_version
        """
        element = create_element(element_key="email", category="BASIC_CONTACT",
                                 classification="INTERNAL")
        v1 = element["version"]

        first = get_success_data(api.reclassify_data_element(
            element["id"],
            {"category": "FINANCIAL", "classification": "CONFIDENTIAL",
             "expected_element_version": v1}, DS))
        assert first["version"] == v1 + 1
        assert first["category"] == "FINANCIAL"

        resp = api.reclassify_data_element(
            element["id"],
            {"category": "HEALTH", "classification": "PUBLIC",
             "expected_element_version": v1}, DS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = get_success_data(api.get_data_element(element["id"], DS))
        assert after["category"] == "FINANCIAL", "the losing writer changes nothing"
        assert after["classification"] == "CONFIDENTIAL"
        assert after["version"] == v1 + 1


class TestTerminalLockdowns:
    def test_submit_in_review_assessment_returns_invalid_state(self, api):
        """PRD §3.5: "A BusinessOwner submits an assessment in TRIGGERED or
        CHANGES_REQUESTED status; the assessment moves to IN_REVIEW"
        PRD §2.9: "A state machine's terminal state is a lockdown: once a
        resource reaches a terminal state, no further trigger is valid against
        it, and any attempt is rejected with ERR_INVALID_STATE_TRANSITION."

        Design: Corner/state_machines/submit_in_review_assessment_returns_invalid_state
        """
        _activity, pia = create_activity_with_manual_assessment(submitter_headers=BO1)
        assert pia["status"] == "IN_REVIEW"

        resp = api.submit_assessment(pia["id"], BO1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_assessment(pia["id"], LC1))
        assert after["status"] == "IN_REVIEW"

    def test_approve_rejected_assessment_returns_invalid_state(self, api):
        """PRD §3.5: "Reject moves the assessment to the terminal REJECTED
        status."
        PRD §2.9: "A state machine's terminal state is a lockdown: once a
        resource reaches a terminal state, no further trigger is valid against
        it, and any attempt is rejected with ERR_INVALID_STATE_TRANSITION."

        Design: Corner/state_machines/approve_rejected_assessment_returns_invalid_state
        """
        _activity, pia = create_activity_with_manual_assessment(submitter_headers=BO1)
        rejected = get_success_data(api.reject_assessment(pia["id"], LC1))
        assert rejected["status"] == "REJECTED"

        # a fresh reviewer id keeps the SoD check green, isolating the state gate
        resp = api.approve_assessment(pia["id"], LC2)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_assessment(pia["id"], LC1))
        assert after["status"] == "REJECTED"
        assert after["final_score"] is None


class TestNoticeWindowValidity:
    def test_inverted_notice_window_rejected_at_publish(self, api):
        """PRD §3.2: "When a PrivacyAdmin publishes a draft notice, the server
        first checks the window itself: if effective_to is present it must be
        strictly after effective_from, otherwise the publish is rejected with
        ERR_INVALID_WINDOW."

        Design: Corner/validations/inverted_notice_window_rejected_at_publish
        """
        notice = get_success_data(api.create_notice(
            create_notice_payload(scope="WEBSITE", title="bad",
                                  effective_from="2027-01-01T00:00:00Z",
                                  effective_to="2026-01-01T00:00:00Z"), PA))
        assert notice["status"] == "DRAFT"

        resp = api.publish_notice(notice["id"], PA)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)
        after = get_success_data(api.get_notice(notice["id"], PA))
        assert after["status"] == "DRAFT"

    def test_notices_filter_by_scope_and_status(self, api):
        """PRD §3.2: "When all checks pass, the notice's status becomes
        PUBLISHED, published_at is set to the logical clock, and the notice's
        version increments."
        PRD §4: the notices list endpoint is documented as "List notices
        (paginated, filterable)" — here filtered by scope and status.

        Design: Corner/endpoints/notices_filter_by_scope_and_status
        """
        n1 = get_success_data(api.create_notice(
            create_notice_payload(scope="WEBSITE", title="w1",
                                  effective_from="2026-01-01T00:00:00Z",
                                  effective_to="2027-01-01T00:00:00Z"), PA))
        get_success_data(api.publish_notice(n1["id"], PA))
        get_success_data(api.create_notice(
            create_notice_payload(scope="WEBSITE", title="w2",
                                  effective_from="2027-01-01T00:00:00Z"), PA))
        n3 = get_success_data(api.create_notice(
            create_notice_payload(scope="EMPLOYEE", title="e1",
                                  effective_from="2026-01-01T00:00:00Z",
                                  effective_to="2027-01-01T00:00:00Z"), PA))
        get_success_data(api.publish_notice(n3["id"], PA))

        hits, meta = validate_paginated(api.list_notices(
            PA, params={"scope": "WEBSITE", "status": "PUBLISHED"}))
        assert len(hits) == 1, "n2 has the wrong status, n3 the wrong scope"
        assert hits[0]["id"] == n1["id"]


class TestInitialStatesAndConsistency:
    def test_new_entities_start_in_initial_states(self, api):
        """PRD §3.1: "An element is created in ACTIVE status."
        PRD §3.2: "A new notice is created in DRAFT status, with published_at and
        superseded_by_notice_id both null."
        PRD §3.3: "The vendor is created in ONBOARDING status." and "The new
        contract is created in DRAFT status with verification_status set to
        UNVERIFIED."
        PRD §3.4: "The new activity itself is created in DRAFT status."
        PRD §3.6: "The new request is created with verification_status UNVERIFIED
        and fulfillment_status INTAKE, and final_due_at stays null until
        verification."

        Design: Corner/state_machines/new_entities_start_in_initial_states
        """
        element = create_element(element_key="email")
        assert element["status"] == "ACTIVE"
        policy = create_retention_policy()
        consumer = create_consumer(email="tx@x.com", state_code="TX")
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=[]), VM))
        assert vendor["status"] == "ONBOARDING"

        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))
        assert activity["status"] == "DRAFT"

        contract = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=vendor["version"]), VM))
        assert contract["status"] == "DRAFT"
        assert contract["verification_status"] == "UNVERIFIED"

        notice = get_success_data(api.create_notice(create_notice_payload(title="t"), PA))
        assert notice["status"] == "DRAFT"

        request = get_success_data(api.create_rights_request(
            consumer["id"],
            {"request_type": "ACCESS", "requested_categories": ["BASIC_CONTACT"]},
            make_consumer_headers(consumer["id"])))
        assert_rights_request(request)
        assert request["verification_status"] == "UNVERIFIED"
        assert request["fulfillment_status"] == "INTAKE"
        assert request["final_due_at"] is None

    def test_immediate_consistency_read_after_write(self, api):
        """PRD §2.4: "version starts at its initial value on creation and
        increments by exactly 1 on every mutation"
        PRD §3.4: "Activation by a DataSteward requires that the activity be in
        DRAFT ... and that at least one Purpose with status DOCUMENTED exist for
        the activity — otherwise ERR_NO_DOCUMENTED_PURPOSE."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        element = create_element(element_key="email")
        policy = create_retention_policy()
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))
        assert activity["version"] == 1
        get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="MARKETING", legal_basis="CONTRACT",
                                   retention_policy_id=policy["id"]), DS))

        activated = get_success_data(api.activate_activity(activity["id"], DS))
        assert activated["status"] == "ACTIVE", "the mutate response carries the new state"
        assert activated["version"] == 2

        fetched = get_success_data(api.get_activity(activity["id"], DS))
        assert fetched["status"] == "ACTIVE", "an immediate GET sees the mutation"
        assert fetched["version"] == 2
        assert_activity(fetched)


class TestRiskTotalConservation:
    def test_activity_activate_retire_conserves_risk_total(self, api):
        """PRD §3.4: "Activation by a DataSteward requires that the activity be
        in DRAFT, that any pia_required activity already have an APPROVED
        assessment — otherwise ERR_PIA_NOT_APPROVED — and that at least one
        Purpose with status DOCUMENTED exist for the activity — otherwise
        ERR_NO_DOCUMENTED_PURPOSE."
        PRD §3.4: "Retirement by a DataSteward is valid from either ACTIVE or
        COMPLIANCE_HOLD and moves the activity to the terminal RETIRED status"
        PRD §3.4: "The screening score takes the maximum element value across the
        linked set — the maximum over an empty set is 0 — adds 25 for each
        element beyond the first, adds the vendor exposure (0 for LOW, 75 for
        STANDARD, 150 for HIGH, and 0 when no vendor is linked), applies
        round-half-up to the max term before the surcharges, and caps the result
        at 1000."

        Design: Difficulty/compensating_invariant/activity_activate_retire_conserves_risk_total
        """
        e_mail = create_element(element_key="email", category="BASIC_CONTACT",
                                classification="INTERNAL")                          # 50
        e_bank = create_element(element_key="bank_acct", category="FINANCIAL",
                                classification="CONFIDENTIAL")                      # 300
        policy = create_retention_policy()
        a1 = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_mail["id"]]), DS))
        a2 = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Billing", business_unit="Finance",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_bank["id"]]), DS))
        get_success_data(api.create_purpose(
            a1["id"], create_purpose_payload(purpose_type="MARKETING",
                                             legal_basis="LEGITIMATE_INTEREST",
                                             retention_policy_id=policy["id"]), DS))
        get_success_data(api.create_purpose(
            a2["id"], create_purpose_payload(purpose_type="SERVICE_DELIVERY",
                                             legal_basis="CONTRACT",
                                             retention_policy_id=policy["id"]), DS))

        get_success_data(api.activate_activity(a2["id"], DS))
        get_success_data(api.activate_activity(a1["id"], DS))
        active, _ = validate_paginated(api.list_activities(DS, params={"status": "ACTIVE"}))
        assert {a["id"] for a in active} == {a1["id"], a2["id"]}
        assert sum(a["risk_score"] for a in active) == 350, "risk total is 50 + 300"

        retired = get_success_data(api.retire_activity(a1["id"], DS))
        assert retired["status"] == "RETIRED"

        active_after, _ = validate_paginated(
            api.list_activities(DS, params={"status": "ACTIVE"}))
        assert [a["id"] for a in active_after] == [a2["id"]]
        assert active_after[0]["risk_score"] == 300, (
            "activate(A1) + retire(A1) leaves the ACTIVE risk total unchanged at 300"
        )

    def test_retire_removes_exactly_its_own_risk(self, api):
        """PRD §3.4: "Retirement by a DataSteward is valid from either ACTIVE or
        COMPLIANCE_HOLD and moves the activity to the terminal RETIRED status"
        PRD §3.4: "The screening score takes the maximum element value across the
        linked set — the maximum over an empty set is 0 — adds 25 for each
        element beyond the first, adds the vendor exposure (0 for LOW, 75 for
        STANDARD, 150 for HIGH, and 0 when no vendor is linked), applies
        round-half-up to the max term before the surcharges, and caps the result
        at 1000."

        Design: Difficulty/compensating_invariant/activity_activate_retire_conserves_risk_total
        """
        e_mail = create_element(element_key="email", category="BASIC_CONTACT",
                                classification="INTERNAL")                          # 50
        e_bank = create_element(element_key="bank_acct", category="FINANCIAL",
                                classification="CONFIDENTIAL")                      # 300
        policy = create_retention_policy()
        a1 = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_mail["id"]]), DS))
        a2 = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Billing", business_unit="Finance",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_bank["id"]]), DS))
        for act, basis, ptype in ((a1, "LEGITIMATE_INTEREST", "MARKETING"),
                                  (a2, "CONTRACT", "SERVICE_DELIVERY")):
            get_success_data(api.create_purpose(
                act["id"], create_purpose_payload(purpose_type=ptype, legal_basis=basis,
                                                  retention_policy_id=policy["id"]), DS))
            get_success_data(api.activate_activity(act["id"], DS))

        # retiring A2 removes exactly its 300; A1's 50 remains
        get_success_data(api.retire_activity(a2["id"], DS))
        active, _ = validate_paginated(api.list_activities(DS, params={"status": "ACTIVE"}))
        assert [a["id"] for a in active] == [a1["id"]]
        assert sum(a["risk_score"] for a in active) == 50
