"""Contracts: negotiation loop, exclusivity, execution gates, cascades, OCC."""
from test_helpers import (
    ApiErrorId,
    assert_purchase_order,
    assert_requisition,
    create_approved_requisition,
    create_contract_draft,
    create_department,
    create_executed_contract,
    create_requisition_draft,
    create_vendor,
    get_success_data,
    issue_po_ok,
    make_requester_headers,
    post_invoice,
    post_receipt,
    requisition_line,
    set_clock,
    submit_requisition_ok,
    validate_error,
)
from test_helpers.fixtures import ADMIN, BUYER, CONTRACT_OFFICER, DIRECTOR

ADMIN_H = ADMIN
CO = CONTRACT_OFFICER
DIR_H = DIRECTOR


class TestNegotiationLoop:
    def test_negotiation_round_increments_on_loop_entry(self, api):
        """PRD §3.2: "From `UNDER_REVIEW` the officer may open a negotiation round,
        moving the contract to `IN_NEGOTIATION` and incrementing
        `negotiation_round` by one each time".

        Design: Difficulty/non_linear_state_machine/contract_negotiation_round_cycle
        """
        vendor = create_vendor(legal_name="ContractorCo")
        contract = create_contract_draft(vendor["id"], commodity_code="LAB")
        cid = contract["id"]
        get_success_data(api.submit_contract_review(cid, CO))
        round1 = get_success_data(
            api.negotiate_contract(cid, {"note": "round 1: liability cap"}, CO)
        )
        assert round1["negotiation_round"] == 1
        get_success_data(api.submit_contract_review(cid, CO))
        round2 = get_success_data(
            api.negotiate_contract(cid, {"note": "round 2: payment terms"}, CO)
        )
        assert round2["negotiation_round"] == 2, (
            "increments on loop entry only, not on resubmission"
        )

    def test_negotiate_rejected_after_execute(self, api):
        """PRD §3.2: "Every one of these transitions attempted from a state where
        it does not exist is rejected with `ERR_CONTRACT_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/contract_negotiation_round_cycle
        """
        vendor = create_vendor(legal_name="ContractorCo")
        contract = create_contract_draft(vendor["id"], commodity_code="LAB")
        cid = contract["id"]
        get_success_data(api.submit_contract_review(cid, CO))
        get_success_data(
            api.negotiate_contract(cid, {"note": "round 1: liability cap"}, CO)
        )
        get_success_data(api.submit_contract_review(cid, CO))
        get_success_data(api.approve_contract_review(cid, CO))
        executed = get_success_data(api.execute_contract(cid, DIR_H))
        assert executed["status"] == "EXECUTED"
        late = api.negotiate_contract(cid, {"note": "round 3 attempt"}, CO)
        validate_error(late, ApiErrorId.ERR_CONTRACT_STATE_INVALID, 409)


class TestContractPeriodOverlap:
    def _setup_three_contracts(self, api):
        vendor = create_vendor(legal_name="LabVendor")
        c1 = create_executed_contract(
            vendor["id"], commodity_code="LAB",
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2027-01-01T00:00:00Z",
        )
        c2 = create_contract_draft(
            vendor["id"], commodity_code="LAB", value_cents=3000000,
            effective_start="2026-06-01T00:00:00Z",
            effective_end="2027-06-01T00:00:00Z",
        )
        get_success_data(api.submit_contract_review(c2["id"], CO))
        get_success_data(api.approve_contract_review(c2["id"], CO))
        c3 = create_contract_draft(
            vendor["id"], commodity_code="LAB", value_cents=4000000,
            effective_start="2027-01-01T00:00:00Z",
            effective_end="2028-01-01T00:00:00Z",
        )
        get_success_data(api.submit_contract_review(c3["id"], CO))
        get_success_data(api.approve_contract_review(c3["id"], CO))
        return c1, c2, c3

    def test_overlapping_execute_rejected(self, api):
        """PRD §3.2: "no other `EXECUTED` contract may exist for the same pairing
        of `vendor_id` and `commodity_code` whose half-open period overlaps this
        one, excepting the contract this one is explicitly superseding (otherwise
        `ERR_CONTRACT_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/contract_period_half_open_overlap
        """
        _, c2, _ = self._setup_three_contracts(api)
        resp = api.execute_contract(c2["id"], DIR_H)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_OVERLAP, 409)
        live = get_success_data(api.get_contract(c2["id"], ADMIN_H))
        assert live["status"] == "REVIEW_APPROVED"

    def test_adjacent_period_execute_succeeds(self, api):
        """PRD §3.2: "The period is half-open: the start is inclusive and the end
        is exclusive." — a contract starting exactly at the incumbent's
        `effective_end` is adjacent, not overlapping.

        Design: Difficulty/resource_temporal_overlap/contract_period_half_open_overlap
        """
        _, c2, c3 = self._setup_three_contracts(api)
        blocked = api.execute_contract(c2["id"], DIR_H)
        validate_error(blocked, ApiErrorId.ERR_CONTRACT_OVERLAP, 409)
        executed = get_success_data(api.execute_contract(c3["id"], DIR_H))
        assert executed["status"] == "EXECUTED"


class TestExecuteRequiresActiveVendor:
    def _review_approved_then_suspend(self, api):
        vendor = create_vendor(legal_name="RiskyVendor")
        contract = create_contract_draft(vendor["id"], commodity_code="SEC")
        cid = contract["id"]
        get_success_data(api.submit_contract_review(cid, CO))
        get_success_data(api.approve_contract_review(cid, CO))
        get_success_data(
            api.suspend_vendor(vendor["id"], {"reason": "insurance lapsed"}, ADMIN_H)
        )
        return vendor, cid

    def test_execute_rejected_while_vendor_suspended(self, api):
        """PRD §3.2: "the counterparty vendor must be `ACTIVE` (otherwise
        `ERR_VENDOR_SUSPENDED`)".

        Design: Difficulty/cross_entity_state_dependency/contract_execute_requires_active_vendor
        """
        _, cid = self._review_approved_then_suspend(api)
        resp = api.execute_contract(cid, DIR_H)
        validate_error(resp, ApiErrorId.ERR_VENDOR_SUSPENDED, 409)
        live = get_success_data(api.get_contract(cid, ADMIN_H))
        assert live["status"] == "REVIEW_APPROVED"

    def test_execute_succeeds_after_reinstate(self, api):
        """PRD §3.1: "A `ProcurementAdmin` may suspend an `ACTIVE` vendor — an
        optional `reason` may accompany the suspension — or reinstate a
        `SUSPENDED` one".
        PRD §3.2: "On execution the contract becomes `EXECUTED`, `executed_at` is
        stamped with the logical clock".

        Design: Difficulty/cross_entity_state_dependency/contract_execute_requires_active_vendor
        """
        vendor, cid = self._review_approved_then_suspend(api)
        blocked = api.execute_contract(cid, DIR_H)
        validate_error(blocked, ApiErrorId.ERR_VENDOR_SUSPENDED, 409)
        get_success_data(api.reinstate_vendor(vendor["id"], ADMIN_H))
        executed = get_success_data(api.execute_contract(cid, DIR_H))
        assert executed["status"] == "EXECUTED"
        assert executed["executed_at"] is not None


class TestContractTerminationCascade:
    def _cascade_setup(self, api):
        """EXECUTED contract; PO1 (invoice PAYABLE); R2 APPROVED on contract."""
        dept = create_department(name="Medicine")
        vendor = create_vendor(legal_name="MedSupply")
        contract = create_executed_contract(vendor["id"], commodity_code="LAB")
        cid = contract["id"]

        r1 = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], contract_id=cid,
            lines=[requisition_line(
                commodity_code="LAB", description="gloves",
                unit_price_cents=400000, cost_category="SUPPLIES",
            )],
        )
        po1 = issue_po_ok(r1["id"])
        post_receipt(po1["id"], [{"line_no": 0, "quantity": 1}])
        inv1 = post_invoice(
            po1["id"], [{"line_no": 0, "quantity": 1, "unit_price_cents": 400000}],
            invoice_number="INV-C1",
        )
        assert inv1["status"] == "PAYABLE", f"setup invoice: {inv1['status']}"

        r2 = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], contract_id=cid,
            lines=[requisition_line(
                commodity_code="LAB", description="masks",
                unit_price_cents=300000, cost_category="SUPPLIES",
            )],
        )
        return contract, po1, inv1, r2

    def test_termination_cascades_to_po_invoice_and_requisition(self, api):
        """PRD §3.2: "every purchase order riding this contract whose fulfillment
        is still `ISSUED` or `PARTIALLY_RECEIVED` has its
        `contract_terminated_flag` set to true, which forces its match posture to
        `EXCEPTION` regardless of invoices; every invoice on such a purchase order
        that is currently `PAYABLE` flips to `EXCEPTION` with `exception_reason`
        `CONTRACT_TERMINATED`; and every requisition riding this contract that is
        `APPROVED` but has not yet issued its purchase order is moved to
        `RETURNED` with `returned_reason` `CONTRACT_TERMINATED`."

        Design: Difficulty/transitive_cascade/contract_termination_four_hop_cascade
        """
        contract, po1, inv1, r2 = self._cascade_setup(api)
        terminated = get_success_data(
            api.terminate_contract(contract["id"], {"reason": "vendor breach"}, DIR_H)
        )
        assert terminated["status"] == "TERMINATED"

        po_after = get_success_data(api.get_purchase_order(po1["id"], ADMIN_H))
        assert po_after["contract_terminated_flag"] is True
        assert po_after["match_status"] == "EXCEPTION"

        inv_after = get_success_data(api.get_invoice(inv1["id"], ADMIN_H))
        assert inv_after["status"] == "EXCEPTION"
        assert inv_after["exception_reason"] == "CONTRACT_TERMINATED"

        r2_after = get_success_data(api.get_requisition(r2["id"], ADMIN_H))
        assert r2_after["status"] == "RETURNED"
        assert r2_after["returned_reason"] == "CONTRACT_TERMINATED"

    def test_terminated_contract_pin_survives_and_payment_blocked(self, api):
        """PRD §3.5: "`contract_version_pinned` recording the contract's `version`
        observed at issue, null for contract-free orders".
        PRD §3.6: "Payment, also by an `APClerk`, requires a `PAYABLE` invoice
        (otherwise `ERR_INVOICE_NOT_PAYABLE`)".

        Design: Difficulty/transitive_cascade/contract_termination_four_hop_cascade
        """
        contract, po1, inv1, _ = self._cascade_setup(api)
        get_success_data(
            api.terminate_contract(contract["id"], {"reason": "vendor breach"}, DIR_H)
        )
        po_after = get_success_data(api.get_purchase_order(po1["id"], ADMIN_H))
        assert_purchase_order(po_after)
        assert po_after["contract_version_pinned"] == contract["version"], (
            "the version observed at issue survives the terminate"
        )
        from test_helpers.fixtures import AP_CLERK
        pay = api.pay_invoice(inv1["id"], AP_CLERK)
        validate_error(pay, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, 409)


class TestAmendmentChainAndPin:
    def test_issue_po_pin_and_amend_supersede(self, api):
        """PRD §3.5: "`contract_version_pinned` recording the contract's `version`
        observed at issue, null for contract-free orders".
        PRD §3.2: "The amendment is created in `DRAFT` with its
        `supersedes_contract_id` pointing at the contract it will replace, and the
        act of creating it increments the amended contract's `version` by one".
        PRD §3.3: "A requisition naming a contract requires that contract to be
        `EXECUTED` (otherwise `ERR_CONTRACT_NOT_EXECUTED`)".

        Design: Corner/endpoints/issue_po_version_pin_and_amend_supersede_chain
        """
        dept = create_department(name="Pin")
        vendor = create_vendor(legal_name="PinCo")
        contract = create_executed_contract(vendor["id"], commodity_code="PIN")
        cid = contract["id"]
        pinned_version = contract["version"]

        r1 = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], contract_id=cid,
            lines=[requisition_line(
                commodity_code="PIN", description="paper",
                unit_price_cents=300000, cost_category="SUPPLIES",
            )],
        )
        po = issue_po_ok(r1["id"])
        assert po["contract_version_pinned"] == pinned_version

        amendment = get_success_data(
            api.amend_contract(
                cid,
                {
                    "expected_contract_version": pinned_version,
                    "effective_start": "2026-01-01T00:00:00Z",
                    "effective_end": "2028-01-01T00:00:00Z",
                    "terms_text": "extended one year",
                },
                CO,
            )
        )
        assert amendment["status"] == "DRAFT"
        assert amendment["supersedes_contract_id"] == cid
        bumped = get_success_data(api.get_contract(cid, ADMIN_H))
        assert bumped["version"] == pinned_version + 1

        aid = amendment["id"]
        get_success_data(api.submit_contract_review(aid, CO))
        get_success_data(api.approve_contract_review(aid, CO))
        executed_amendment = get_success_data(api.execute_contract(aid, DIR_H))
        assert executed_amendment["status"] == "EXECUTED"
        original = get_success_data(api.get_contract(cid, ADMIN_H))
        assert original["status"] == "SUPERSEDED"

        po_after = get_success_data(api.get_purchase_order(po["id"], ADMIN_H))
        assert po_after["contract_version_pinned"] == pinned_version

        r2 = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"], contract_id=cid,
            lines=[requisition_line(
                commodity_code="PIN", description="toner",
                unit_price_cents=200000, cost_category="SUPPLIES",
            )],
        )
        late = api.submit_requisition(r2["id"], make_requester_headers("req-user-1"))
        validate_error(late, ApiErrorId.ERR_CONTRACT_NOT_EXECUTED, 409)


class TestContractExpiredAtIssue:
    def test_contract_expired_at_issue_po(self, api):
        """PRD §3.5: "when the requisition rides a contract, the contract must
        still be `EXECUTED` (otherwise `ERR_CONTRACT_NOT_EXECUTED`) with the
        logical clock inside the half-open effective period — on or after
        `effective_start` and strictly before `effective_end` (otherwise
        `ERR_CONTRACT_EXPIRED`)."

        Design: Corner/errors/contract_expired_at_issue_po
        """
        set_clock("2026-07-01T00:00:00Z")
        dept = create_department(name="Exp")
        vendor = create_vendor(legal_name="ExpCo")
        contract = create_executed_contract(
            vendor["id"], commodity_code="EXP", value_cents=1000000,
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-08-01T00:00:00Z",
        )
        req = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            contract_id=contract["id"],
            lines=[requisition_line(
                commodity_code="EXP", description="supplies",
                unit_price_cents=300000, cost_category="SUPPLIES",
            )],
        )
        assert req["status"] == "APPROVED"
        set_clock("2026-08-01T00:00:00Z")  # exactly the exclusive end
        resp = api.issue_po(req["id"], BUYER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_EXPIRED, 409)
        live = get_success_data(api.get_requisition(req["id"], ADMIN_H))
        assert live["status"] == "APPROVED", (
            "the failure does not consume the approval"
        )
        assert_requisition(live)
