"""ChangeOrder approval, segregation-of-duties, and Settlement workflow.
Covers PRD §3.4 (and the calculation final_settlement_amount).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    AUDITOR_ID,
    AUDITOR_ID_ALT,
    PLANNER_ID,
    PLANNER_ID_ALT,
    add_two_change_orders_with_known_order,
    approve_change_order,
    confirm_settlement,
    create_change_order,
    create_change_order_payload,
    create_settlement_for_contract,
    create_settlement_payload,
    drive_settlement_to_finalized,
    finalize_settlement,
    get_settlement,
    list_audit_entries,
    make_planner_headers,
    make_vendor_rep_headers,
    setup_project_with_one_contract_accepted,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.4 -- Change order: requested_by_user_id recorded.
# ===========================================================================
class TestChangeOrderCreation:

    def test_create_change_order_records_requester(self, api):
        """PRD §3.4: "the server records the acting planner's X-User-ID as
        requested_by_user_id and gives the change order a status of PENDING."

        Claim: POST /change-orders by planner X -> requested_by_user_id == X
        and status == PENDING.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted()
        planner_headers = make_planner_headers(PLANNER_ID)
        res = api.create_change_order(
            project["id"], contract["id"],
            create_change_order_payload(delta_amount_cents=10_000),
            planner_headers,
        )
        co = validate_success(res, expected_status=201)
        assert co["status"] == "PENDING"
        assert co["requested_by_user_id"] == PLANNER_ID


# ===========================================================================
# §3.4 -- ChangeOrder approval: segregation, state, contract-bound,
# budget gates.
# ===========================================================================
class TestChangeOrderApproval:

    def test_self_approval_rejected(self, api):
        """PRD §3.4: "the acting planner's X-User-ID MUST differ from
        requested_by_user_id (otherwise ERR_SEGREGATION_OF_DUTIES, HTTP
        403)."

        Claim: same planner approves own change order ->
        ERR_SEGREGATION_OF_DUTIES / 403.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted()
        co = create_change_order(
            project["id"], contract["id"],
            delta_amount_cents=10_000,
            requester_planner_id=PLANNER_ID,
        )
        # Same planner attempts approve.
        same_headers = make_planner_headers(PLANNER_ID)
        res = api.approve_change_order(
            project["id"], contract["id"], co["id"], same_headers,
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_segregation_beats_budget_overcommit(self, api):
        """PRD §2.9: "the segregation-of-duties checks run before the
        budget overcommit check on change-order approval -- a
        self-approving planner is rejected with ERR_SEGREGATION_OF_DUTIES
        (HTTP 403) even when the budget would have permitted the change."

        Claim: change order with a tiny non-overcommitting positive delta,
        self-approval -> ERR_SEGREGATION_OF_DUTIES (NOT ERR_BUDGET_OVERCOMMITTED).
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            total_budget_cents=10_000_000,
            quote_amount_cents=300_000,
        )
        co = create_change_order(
            project["id"], contract["id"],
            delta_amount_cents=100,  # easily fits
            requester_planner_id=PLANNER_ID,
        )
        same_headers = make_planner_headers(PLANNER_ID)
        res = api.approve_change_order(
            project["id"], contract["id"], co["id"], same_headers,
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_approval_succeeds_with_distinct_planner(self, api):
        """PRD §3.4: "A second planner -- one whose X-User-ID differs from
        requested_by_user_id -- then either approves or rejects the change
        order."

        Claim: distinct planner approval -> status APPROVED, approved_by_user_id
        is the new planner.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted()
        co = create_change_order(
            project["id"], contract["id"],
            delta_amount_cents=20_000,
            requester_planner_id=PLANNER_ID,
        )
        approver_headers = make_planner_headers(PLANNER_ID_ALT)
        res = api.approve_change_order(
            project["id"], contract["id"], co["id"], approver_headers,
        )
        approved = validate_success(res)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == PLANNER_ID_ALT

    def test_approval_appends_audit_entry(self, api):
        """PRD §3.4: "On success, the server records approved_by_user_id
        as the acting planner's X-User-ID, appends an AuditEntry with
        event_kind of CHANGE_ORDER_APPROVED."

        Claim: each successful approval appends a CHANGE_ORDER_APPROVED entry.
        """
        from test_helpers import find_audit_entries
        project, _v, _q, contract = setup_project_with_one_contract_accepted()
        co = create_change_order(
            project["id"], contract["id"],
            delta_amount_cents=20_000,
            requester_planner_id=PLANNER_ID,
        )
        approve_change_order(
            project["id"], contract["id"], co["id"],
            approver_planner_id=PLANNER_ID_ALT,
        )
        entries = list_audit_entries(project["id"])
        coa_entries = find_audit_entries(
            entries, event_kind="CHANGE_ORDER_APPROVED"
        )
        assert len(coa_entries) >= 1


# ===========================================================================
# §3.4 -- Settlement creation, confirmation, finalize.
# ===========================================================================
class TestSettlementWorkflow:

    def test_create_settlement_in_draft(self, api):
        """PRD §3.4: "After a contract reaches ACCEPTED, the planner
        creates the contract's single Settlement row, optionally seeding
        breach_deduction_cents and refund_cents (both default to 0 and
        both must remain non-negative). The server records the acting
        planner as confirmed_by_user_id and computes provisional_total_cents
        as pinned_amount_cents plus the sum of approved change-order deltas.
        The settlement is created in status DRAFT."

        Claim: POST /settlement on ACCEPTED contract w/ no change orders
        -> status DRAFT, provisional_total_cents == pinned_amount_cents.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            quote_amount_cents=300_000,
        )
        s = create_settlement_for_contract(project["id"], contract["id"])
        assert s["status"] == "DRAFT"
        assert s["provisional_total_cents"] == 300_000
        assert s["breach_deduction_cents"] == 0
        assert s["refund_cents"] == 0

    def test_confirm_by_other_vendor_rejected(self, api):
        """PRD §3.4: "the acting VendorRep's X-User-ID to equal the bound
        Vendor.id (otherwise ERR_NOT_OWNING_VENDOR)."

        Claim: VendorRep with X-User-ID != Vendor.id -> confirm fails with
        ERR_NOT_OWNING_VENDOR.
        """
        from test_helpers import create_approved_vendor
        project, _v, _q, contract = setup_project_with_one_contract_accepted()
        create_settlement_for_contract(project["id"], contract["id"])
        # Build a different vendor's headers.
        other = create_approved_vendor(category="MC")
        other_vrep = make_vendor_rep_headers(other["id"])
        res = api.confirm_settlement(
            project["id"], contract["id"], other_vrep,
        )
        validate_error(res, ApiErrorId.ERR_NOT_OWNING_VENDOR.value)

    def test_finalize_segregation_planner_cannot_finalize(self, api):
        """PRD §3.4: "the acting role to be Auditor (otherwise
        ERR_AUDITOR_REQUIRED), and the acting auditor's X-User-ID to
        differ from confirmed_by_user_id (otherwise ERR_SEGREGATION_OF_DUTIES)."

        Claim: Planner attempts /settlement/finalize -> ERR_AUDITOR_REQUIRED.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted()
        create_settlement_for_contract(project["id"], contract["id"])
        confirm_settlement(
            project["id"], contract["id"], contract["vendor_id"],
        )
        # Planner attempts finalize.
        planner_headers = make_planner_headers(PLANNER_ID)
        res = api.finalize_settlement(
            project["id"], contract["id"], planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_AUDITOR_REQUIRED.value)


# ===========================================================================
# §3.4 -- Final-settlement-amount calculation: ascending + per-step clamp.
# ===========================================================================
class TestFinalSettlementAmount:

    def test_finalize_simple_no_change_orders(self, api):
        """PRD §3.4: "The committed final_amount_cents is then the larger
        of zero and provisional_total_cents minus breach_deduction_cents
        minus refund_cents."

        Claim: ACCEPTED contract pinned=300_000, breach=0, refund=0, no
        change orders -> final_amount_cents == 300_000 after FINALIZED.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            quote_amount_cents=300_000,
        )
        final = drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=0, refund_cents=0,
        )
        assert final["final_amount_cents"] == 300_000

    def test_finalize_with_breach_deduction(self, api):
        """PRD §3.4: "The committed final_amount_cents is then the larger
        of zero and provisional_total_cents minus breach_deduction_cents
        minus refund_cents."

        Claim: pinned=300_000, breach=50_000, refund=0 ->
        final_amount_cents == 250_000.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            quote_amount_cents=300_000,
        )
        final = drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=50_000, refund_cents=0,
        )
        assert final["final_amount_cents"] == 250_000

    def test_finalize_with_refund_only_yields_refunded_payment(self, api):
        """PRD §3.4: "if refund_cents is greater than zero and
        final_amount_cents equals zero, payment_status becomes REFUNDED."

        Claim: pinned=100_000, breach=100_000, refund=50_000 -> final=0
        and payment_status == REFUNDED.
        """
        from test_helpers import get_contract
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            quote_amount_cents=100_000,
        )
        final = drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=100_000, refund_cents=50_000,
        )
        assert final["final_amount_cents"] == 0
        c_after = get_contract(project["id"], contract["id"])
        assert c_after["payment_status"] == "REFUNDED"

    def test_finalize_with_change_orders_ascending_clamp(self, api):
        """PRD §3.4: "it walks the contract's approved change orders in
        ascending order of the created_at of their CHANGE_ORDER_APPROVED
        audit entry, beginning with a running base equal to
        pinned_amount_cents. After each delta, the running base is replaced
        by the larger of zero and the post-delta base -- that is, the
        running base is clamped at zero before the next delta is applied,
        so a deeply negative interim total cannot subsequently be lifted
        back above zero."

        Claim: pinned=100_000, two deltas approved in order [-150_000,
        +200_000] -> ascending+clamp produces 200_000:
            base=100_000; +(-150_000) = -50_000 -> clamp 0; +200_000 = 200_000.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            total_budget_cents=2_000_000,
            quote_amount_cents=100_000,
            vendor_category="CATERING",
        )
        # Approve two change orders in order [-150_000, +200_000].
        add_two_change_orders_with_known_order(
            project["id"], contract["id"],
            deltas_in_approval_order=[-150_000, 200_000],
        )
        final = drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=0, refund_cents=0,
        )
        assert final["final_amount_cents"] == 200_000, (
            f"PRD §3.4 ascending+clamp: expected 200_000, "
            f"got {final['final_amount_cents']}"
        )
        # provisional_total_cents persisted at finalize is the running base.
        assert final["provisional_total_cents"] == 200_000


# ===========================================================================
# §3.4 -- Settlement preview variant: descending + no clamp.
# ===========================================================================
class TestSettlementPreview:

    def test_preview_uses_descending_no_clamp(self, api):
        """PRD §3.4: "the preview applies the contract's approved
        change-order deltas in **descending** order of their approval time
        (so the latest revisions dominate first) **without** the per-step
        clamp at zero, then deducts `breach_deduction_cents` and
        `refund_cents`."

        Claim: pinned=100_000, deltas approved in order [-150_000,
        +200_000] -> preview while DRAFT applies in descending order
        [+200_000, -150_000]: 100_000 + 200_000 = 300_000;
        300_000 + (-150_000) = 150_000; minus breach 0, refund 0
        -> 150_000.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            total_budget_cents=2_000_000,
            quote_amount_cents=100_000,
            vendor_category="CATERING",
        )
        add_two_change_orders_with_known_order(
            project["id"], contract["id"],
            deltas_in_approval_order=[-150_000, 200_000],
        )
        # Create the settlement (status DRAFT) and read its preview.
        create_settlement_for_contract(project["id"], contract["id"])
        s = get_settlement(project["id"], contract["id"])
        assert s["status"] == "DRAFT"
        assert s["final_amount_cents"] == 150_000, (
            f"PRD §3.4 descending+no-clamp preview: expected 150_000, "
            f"got {s['final_amount_cents']}"
        )


# ===========================================================================
# §3.4 -- Performance rating recomputation.
# ===========================================================================
class TestPerformanceRating:

    def test_attach_rating_recomputes_avg(self, api):
        """PRD §3.4: "A planner may then attach a PerformanceRating to the
        finalized settlement by supplying an integer score between 1 and 5
        inclusive and an optional comment; the rating triggers another
        recomputation of the vendor's avg_performance_rating and
        rating_count."

        Claim: after attaching one rating with score=4 to a vendor's only
        FINALIZED settlement -> Vendor.avg_performance_rating == 4.0 and
        Vendor.rating_count == 1.
        """
        from test_helpers import (
            create_performance_rating_payload,
            get_vendor,
        )
        project, vendor, _q, contract = (
            setup_project_with_one_contract_accepted()
        )
        drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=0, refund_cents=0,
        )
        planner_headers = make_planner_headers(PLANNER_ID)
        api.create_performance_rating(
            project["id"], contract["id"],
            create_performance_rating_payload(score=4),
            planner_headers,
        )
        v_after = get_vendor(vendor["id"])
        assert v_after["rating_count"] == 1
        assert v_after["avg_performance_rating"] == 4.0
