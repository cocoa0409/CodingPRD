"""Invoice intake gates, approval-matrix routing (brackets, scopes, bumps),
tier discipline, and approval segregation of duties."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_invoice,
    create_vendor,
    onboard_vendor_to_active,
    add_verified_primary_bank_account,
    get_vendor,
    set_clock,
    create_matrix_rule,
    create_invoice,
    submit_invoice,
    get_invoice,
    approve_invoice_fully,
    list_invoice_approvals,
    suspend_vendor,
    create_invoice_payload,
    create_payment_run_payload,
    make_role_headers,
    USER_FLOATER,
)

VS1 = TEST_USERS["vendor_specialist_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
CLERK = TEST_USERS["ap_clerk_headers"]
SUP1 = TEST_USERS["ap_supervisor_headers"]
SUP2 = TEST_USERS["ap_supervisor_2_headers"]
MGR = TEST_USERS["ap_manager_headers"]
CTL = TEST_USERS["controller_headers"]
TA = TEST_USERS["treasury_analyst_headers"]
AUD = TEST_USERS["auditor_headers"]


def _aged_vendor_with_rule(api, **vendor_overrides):
    """Matrix t1 rule + vendor activated at 2026-06-01 (no routing bumps apply
    to invoices submitted at the default 2026-08-01 clock)."""
    set_clock("2026-06-01T00:00:00Z")
    create_matrix_rule()
    vendor = onboard_vendor_to_active(**vendor_overrides)
    set_clock("2026-08-01T00:00:00Z")
    return vendor


class TestMatrixRuleOverlap:
    def test_matrix_rule_adjacent_brackets_allowed(self, api):
        """Half-open brackets: one's min equaling the other's max is adjacency,
        not overlap.

        PRD §3.5: "Within one `cost_center` scope, the `ACTIVE` rules' half-open brackets must not overlap; two rules merely touching — one's `min_amount_cents` equaling the other's `max_amount_cents` — is adjacency and is allowed."

        Design: Difficulty/resource_temporal_overlap/matrix_brackets_half_open_adjacency
        """
        rule_a = validate_success(api.create_matrix_rule({
            "cost_center": "GLOBAL", "min_amount_cents": 0,
            "max_amount_cents": 500000, "tier": 1}, CTL), expected_status=201)
        assert rule_a["status"] == "ACTIVE"
        rule_b = validate_success(api.create_matrix_rule({
            "cost_center": "GLOBAL", "min_amount_cents": 500000,
            "max_amount_cents": 1000000, "tier": 2}, CTL), expected_status=201)
        assert rule_b["min_amount_cents"] == 500000

    def test_matrix_rule_overlap_rejected_and_scoped_per_cost_center(self, api):
        """[499999,600000) collides with the existing GLOBAL brackets, while a
        different cost_center scope may overlap freely.

        PRD §3.5: "Within one `cost_center` scope, the `ACTIVE` rules' half-open brackets must not overlap; two rules merely touching — one's `min_amount_cents` equaling the other's `max_amount_cents` — is adjacency and is allowed."
        PRD §3.5: "A violating creation is rejected with `ERR_RULE_RANGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/matrix_brackets_half_open_adjacency
        """
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=500000,
                           max_amount_cents=1000000, tier=2)
        resp = api.create_matrix_rule({
            "cost_center": "GLOBAL", "min_amount_cents": 499999,
            "max_amount_cents": 600000, "tier": 2}, CTL)
        validate_error(resp, ApiErrorId.ERR_RULE_RANGE_OVERLAP.value)

        other_scope = validate_success(api.create_matrix_rule({
            "cost_center": "CC-900", "min_amount_cents": 0,
            "max_amount_cents": 500000, "tier": 2}, CTL), expected_status=201)
        assert other_scope["cost_center"] == "CC-900"


class TestRoutingTiers:
    def test_matrix_bracket_max_exclusive_boundary_below(self, api):
        """499999 stays in bracket [0,500000): max is exclusive.

        PRD §3.5: "The covering rule is the unique scope rule whose `min_amount_cents` is no greater than the invoice's `amount_cents` and whose `max_amount_cents` is either unset or strictly greater than the amount; when no rule covers the amount in either scope, submission is rejected with `ERR_NO_APPROVAL_RULE`."

        Design: Difficulty/boundary_precision_check/matrix_bracket_max_exclusive_boundary
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=500000,
                           max_amount_cents=1000000, tier=2)
        vendor = onboard_vendor_to_active(
            legal_name="Boundary Box", tax_id="10-0000010")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_invoice(vendor["id"], amount_cents=499999,
                                 invoice_number="INV-7101",
                                 received_date="2026-08-01")
        submitted = submit_invoice(invoice["id"])
        assert submitted["required_tier"] == 1, "499999 < 500000 stays in bracket 1"

    def test_matrix_bracket_max_exclusive_boundary_at(self, api):
        """Exactly 500000 hits the inclusive min of the next bracket.

        PRD §3.5: "The covering rule is the unique scope rule whose `min_amount_cents` is no greater than the invoice's `amount_cents` and whose `max_amount_cents` is either unset or strictly greater than the amount; when no rule covers the amount in either scope, submission is rejected with `ERR_NO_APPROVAL_RULE`."

        Design: Difficulty/boundary_precision_check/matrix_bracket_max_exclusive_boundary
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=500000,
                           max_amount_cents=1000000, tier=2)
        vendor = onboard_vendor_to_active(
            legal_name="Boundary Box", tax_id="10-0000010")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_invoice(vendor["id"], amount_cents=500000,
                                 invoice_number="INV-7102",
                                 received_date="2026-08-01")
        submitted = submit_invoice(invoice["id"])
        assert submitted["required_tier"] == 2, \
            "500000 hits the inclusive min of bracket 2; bracket 1's max is exclusive"

    def test_new_vendor_bump_exactly_30_days_boundary(self, api):
        """The new-vendor bump window is strict: one second before the 30-day
        mark bumps the tier; exactly thirty days does not.

        PRD §3.5: "The required tier starts at the covering rule's base `tier` and receives two possible bumps: one when the vendor's `first_activated_at` is set and the submit time falls strictly before the instant thirty days after it — a vendor exactly thirty days active earns no bump — and one when the vendor has a primary `VERIFIED` bank account whose `verified_at` lies strictly less than 72 hours before the submit time."

        Design: Corner/calculations/new_vendor_bump_exactly_30_days_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        create_matrix_rule()
        vendor = onboard_vendor_to_active(
            legal_name="Bump Boundary", tax_id="20-0000019")

        set_clock("2026-08-30T23:59:59Z")  # one second before activated + 30d
        early = create_invoice(vendor["id"], amount_cents=100000,
                               invoice_number="INV-9861", received_date="2026-08-30")
        assert submit_invoice(early["id"])["required_tier"] == 2

        set_clock("2026-08-31T00:00:00Z")  # exactly thirty days after activation
        late = create_invoice(vendor["id"], amount_cents=100000,
                              invoice_number="INV-9862", received_date="2026-08-31")
        assert submit_invoice(late["id"])["required_tier"] == 1

    def test_cost_center_rule_beats_global_fallback(self, api):
        """Scope precedence: the cost-center rule wins where one exists; other
        cost centers fall through to GLOBAL.

        PRD §3.5: "Routing selects among `ACTIVE` matrix rules: the scope is the rules whose `cost_center` equals the invoice's `cost_center`, or, when no such rule exists, the rules in the `GLOBAL` scope."

        Design: Corner/calculations/cost_center_rule_beats_global_fallback
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        create_matrix_rule(cost_center="CC-900", min_amount_cents=0,
                           max_amount_cents=500000, tier=2)
        vendor = onboard_vendor_to_active(
            legal_name="Scoped Supplies", tax_id="20-0000020")
        # Age the vendor past the strict 30-day new-vendor bump window (§3.5)
        # so required_tier reflects the base tier alone.
        set_clock("2026-08-01T00:00:00Z")

        inv_cc = create_invoice(vendor["id"], amount_cents=100000,
                                cost_center="CC-900", invoice_number="INV-9871",
                                received_date="2026-06-01")
        inv_gl = create_invoice(vendor["id"], amount_cents=100000,
                                cost_center="CC-100", invoice_number="INV-9872",
                                received_date="2026-06-01")
        assert submit_invoice(inv_cc["id"])["required_tier"] == 2, \
            "cost-center rule wins"
        assert submit_invoice(inv_gl["id"])["required_tier"] == 1, \
            "GLOBAL fallback applies"

    def test_tier_routing_compound_bumps_capped_at_submit(self, api):
        """Base 2 + new-vendor bump + recent-bank bump = raw 4, capped at the
        maximum tier 3.

        PRD §3.5: "The required tier starts at the covering rule's base `tier` and receives two possible bumps: one when the vendor's `first_activated_at` is set and the submit time falls strictly before the instant thirty days after it — a vendor exactly thirty days active earns no bump — and one when the vendor has a primary `VERIFIED` bank account whose `verified_at` lies strictly less than 72 hours before the submit time."
        PRD §3.5: "The sum of the base tier and both bumps is capped at a maximum tier of 3, and the result is pinned onto the invoice as `required_tier`, a snapshot that later matrix edits do not disturb."

        Design: Difficulty/combinatorial_formula/tier_routing_compound_bumps_capped
        """
        set_clock("2026-08-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=500000,
                           max_amount_cents=1000000, tier=2)
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=1000000,
                           max_amount_cents=None, tier=3)
        vendor = onboard_vendor_to_active(
            legal_name="Capstone Materials", tax_id="10-0000002")

        # Bank account created and confirmed at 2026-08-10 -> verified_at 24h
        # before the 2026-08-11 submit; vendor activated 2026-08-01 (10 days).
        set_clock("2026-08-10T00:00:00Z")
        add_verified_primary_bank_account(
            vendor["id"], account_holder_name="Capstone Materials")

        set_clock("2026-08-11T00:00:00Z")
        invoice = create_invoice(vendor["id"], amount_cents=750000,
                                 invoice_number="INV-7501",
                                 received_date="2026-08-11")
        submitted = submit_invoice(invoice["id"])
        assert submitted["required_tier"] == 3, \
            "raw base2 + bump1 + bump1 = 4 is capped at the maximum tier 3"

    def test_tier_routing_compound_bumps_capped_full_chain(self, api):
        """The capped tier-3 invoice approves through three ordered tiers held
        by their designated roles and lands APPROVED.

        PRD §3.5: "Approval proceeds tier by tier, with each tier reserved to its designated role: tier 1 belongs to an `APSupervisor`, tier 2 to an `APManager`, and tier 3 to a `Controller`."
        PRD §3.5: "When the approved tier equals the invoice's `required_tier`, the approval is final: the invoice moves to `APPROVED`, the approval row is appended as usual, and the provisional discount snapshot is taken (§3.6)."
        PRD §3.5: "A valid intermediate-tier approval appends an `InvoiceApproval` row recording the `invoice_id`, the `round_no` equal to the invoice's `approval_round` at approval time, the `tier`, the `approver_user_id`, and the `approver_role` used for that tier, and the invoice remains `PENDING_APPROVAL`."

        Design: Difficulty/combinatorial_formula/tier_routing_compound_bumps_capped
        """
        set_clock("2026-08-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=500000,
                           max_amount_cents=1000000, tier=2)
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=1000000,
                           max_amount_cents=None, tier=3)
        vendor = onboard_vendor_to_active(
            legal_name="Capstone Materials", tax_id="10-0000002")
        set_clock("2026-08-10T00:00:00Z")
        add_verified_primary_bank_account(
            vendor["id"], account_holder_name="Capstone Materials")

        set_clock("2026-08-11T00:00:00Z")
        invoice = create_invoice(vendor["id"], amount_cents=750000,
                                 invoice_number="INV-7501",
                                 received_date="2026-08-11")
        submit_invoice(invoice["id"])
        approved = approve_invoice_fully(invoice["id"])
        assert approved["status"] == "APPROVED"

        rows, meta = list_invoice_approvals(invoice["id"])
        assert meta["total_count"] == 3
        assert [r["tier"] for r in rows] == [1, 2, 3]
        assert [r["approver_role"] for r in rows] == [
            "APSupervisor", "APManager", "Controller"]
        assert all(r["round_no"] == 1 for r in rows)


class TestSubmitGates:
    def test_vendor_not_active_beats_no_approval_rule(self, api):
        """On a doubly-doomed submit (vendor SUSPENDED and no matrix rule at
        all), the vendor-activity guard surfaces first.

        PRD §3.5: "Submitting an invoice — from `RECEIVED` to `PENDING_APPROVAL`, open to the three intake roles — first requires the vendor to be `ACTIVE`, else `ERR_VENDOR_NOT_ACTIVE`, and then snapshots the routing."

        Design: Corner/validations/vendor_not_active_beats_no_approval_rule
        """
        vendor = onboard_vendor_to_active(
            legal_name="Double Doom", tax_id="20-0000027")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-9910",
                                 received_date="2026-08-01")
        suspend_vendor(vendor["id"], reason="hold")
        resp = api.submit_invoice(invoice["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE.value)

    def test_invoice_submit_gated_by_vendor_status_rejected(self, api):
        """Suspending the vendor after invoice creation makes the submit fail.

        PRD §3.5: "Submitting an invoice — from `RECEIVED` to `PENDING_APPROVAL`, open to the three intake roles — first requires the vendor to be `ACTIVE`, else `ERR_VENDOR_NOT_ACTIVE`, and then snapshots the routing."

        Design: Difficulty/cross_entity_state_dependency/invoice_submit_gated_by_vendor_status
        """
        vendor = _aged_vendor_with_rule(
            api, legal_name="Gated Goods", tax_id="10-0000011")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-8101",
                                 received_date="2026-06-01")
        suspend_vendor(vendor["id"], reason="audit")
        resp = api.submit_invoice(invoice["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE.value)

    def test_invoice_submit_gated_by_vendor_status_no_partial_transition(self, api):
        """The rejected submit leaves the invoice untouched: still RECEIVED with
        approval_round 0.

        PRD §3.5: "Submitting an invoice — from `RECEIVED` to `PENDING_APPROVAL`, open to the three intake roles — first requires the vendor to be `ACTIVE`, else `ERR_VENDOR_NOT_ACTIVE`, and then snapshots the routing."
        PRD §3.5: "A registered invoice is born in `RECEIVED` status with `approval_round` at zero."

        Design: Difficulty/cross_entity_state_dependency/invoice_submit_gated_by_vendor_status
        """
        vendor = _aged_vendor_with_rule(
            api, legal_name="Gated Goods", tax_id="10-0000011")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-8101",
                                 received_date="2026-06-01")
        suspend_vendor(vendor["id"], reason="audit")
        validate_error(api.submit_invoice(invoice["id"], CLERK),
                       ApiErrorId.ERR_VENDOR_NOT_ACTIVE.value)
        reloaded = get_invoice(invoice["id"])
        assert reloaded["status"] == "RECEIVED"
        assert reloaded["approval_round"] == 0
        assert reloaded.get("required_tier") is None

    def test_submit_without_matching_rule_rejected(self, api):
        """Only a CC-900 rule exists: a CC-100 invoice finds neither a scoped
        rule nor a GLOBAL fallback.

        PRD §3.5: "The covering rule is the unique scope rule whose `min_amount_cents` is no greater than the invoice's `amount_cents` and whose `max_amount_cents` is either unset or strictly greater than the amount; when no rule covers the amount in either scope, submission is rejected with `ERR_NO_APPROVAL_RULE`."

        Design: Corner/validations/submit_without_matching_rule_rejected
        """
        create_matrix_rule(cost_center="CC-900", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        vendor = onboard_vendor_to_active(
            legal_name="Orphan Invoice Co", tax_id="20-0000042")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 cost_center="CC-100", invoice_number="INV-9991",
                                 received_date="2026-08-01")
        resp = api.submit_invoice(invoice["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_NO_APPROVAL_RULE.value)
        reloaded = get_invoice(invoice["id"])
        assert reloaded["status"] == "RECEIVED"
        assert reloaded.get("required_tier") is None

    def test_invoice_approve_before_submit_rejected(self, api):
        """Approve on a RECEIVED (never submitted) invoice is a state error.

        PRD §2.11: "State legality follows — a transition whose source state does not permit it, an edit outside its allowed status window, or an acknowledgement aimed at an already-terminal resource is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), with the more specific state guards `ERR_CALLBACK_LOCKED`, `ERR_CALLBACK_EXPIRED`, and `ERR_PAYMENT_ALREADY_TERMINAL` applied where they exist."
        PRD §3.5: "A registered invoice is born in `RECEIVED` status with `approval_round` at zero."

        Design: Corner/state_machines/invoice_approve_before_submit_rejected
        """
        vendor = _aged_vendor_with_rule(
            api, legal_name="Early Eagle", tax_id="20-0000012")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-9601",
                                 received_date="2026-08-01")
        resp = api.approve_invoice(invoice["id"], {"tier": 1}, SUP1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        reloaded = get_invoice(invoice["id"])
        assert reloaded["status"] == "RECEIVED"
        assert reloaded["approval_round"] == 0
        assert reloaded.get("required_tier") is None


class TestApprovalDisciplineAndSoD:
    def test_approve_skip_tier_rejected(self, api):
        """On a tier-2 invoice, approving tier 2 first skips the pending tier 1.

        PRD §3.5: "Finally, a presented tier that skips ahead of the next pending tier is rejected with `ERR_APPROVAL_TIER_OUT_OF_ORDER`."

        Design: Corner/validations/approve_skip_tier_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=2)
        vendor = onboard_vendor_to_active(
            legal_name="Skip Step", tax_id="20-0000043")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-9992",
                                 received_date="2026-08-01")
        submitted = submit_invoice(invoice["id"])
        assert submitted["required_tier"] == 2

        resp = api.approve_invoice(invoice["id"], {"tier": 2}, MGR)
        validate_error(resp, ApiErrorId.ERR_APPROVAL_TIER_OUT_OF_ORDER.value)
        _rows, meta = list_invoice_approvals(invoice["id"])
        assert meta["total_count"] == 0

    def test_tier_role_mismatch_forbidden(self, api):
        """APManager naming tier 1 is refused: the role must equal the tier's
        designated role.

        PRD §3.5: "The caller's role must equal the role designated for the presented tier, else `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §3.5: "Approval proceeds tier by tier, with each tier reserved to its designated role: tier 1 belongs to an `APSupervisor`, tier 2 to an `APManager`, and tier 3 to a `Controller`."

        Design: Corner/rbac/tier_role_mismatch_forbidden
        """
        vendor = _aged_vendor_with_rule(
            api, legal_name="Role Rule", tax_id="20-0000057")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-9006",
                                 received_date="2026-08-01")
        submit_invoice(invoice["id"])
        resp = api.approve_invoice(invoice["id"], {"tier": 1}, MGR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_sod_invoice_submitter_cannot_approve(self, api):
        """The operator who submitted the current round cannot approve it.

        PRD §2.6: "The approver of an invoice must not be the operator recorded as `submitted_by_user_id` for the invoice's current approval round."
        PRD §2.6: "A violation is rejected with `ERR_SOD_INVOICE_SUBMITTER_CANNOT_APPROVE`."

        Design: Corner/validations/sod_invoice_submitter_cannot_approve_forbidden
        """
        vendor = _aged_vendor_with_rule(
            api, legal_name="Submitter Springs", tax_id="20-0000030")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-9920",
                                 received_date="2026-08-01", headers=SUP1)
        get_success_data(api.submit_invoice(invoice["id"], SUP1))
        resp = api.approve_invoice(invoice["id"], {"tier": 1}, SUP1)
        validate_error(resp, ApiErrorId.ERR_SOD_INVOICE_SUBMITTER_CANNOT_APPROVE.value)
        reloaded = get_invoice(invoice["id"])
        assert reloaded["status"] == "PENDING_APPROVAL"
        _rows, meta = list_invoice_approvals(invoice["id"])
        assert meta["total_count"] == 0

    def test_sod_same_user_two_tiers_across_roles_forbidden(self, api):
        """The same operator id may not approve two tiers of one round, even
        wearing the correct role hat for each tier.

        PRD §2.6: "Within a single approval round of an invoice, one operator may approve at most one tier."
        PRD §2.6: "An operator who already holds an approval row in the current round and attempts another tier is rejected with `ERR_SOD_SAME_APPROVER_TWO_TIERS`."

        Design: Corner/validations/sod_same_user_two_tiers_across_roles_forbidden
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=2)
        vendor = onboard_vendor_to_active(
            legal_name="Two Tier Tools", tax_id="20-0000031")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-9930",
                                 received_date="2026-08-01")
        submit_invoice(invoice["id"])
        floater_sup = make_role_headers(USER_FLOATER, "APSupervisor")
        floater_mgr = make_role_headers(USER_FLOATER, "APManager")
        validate_success(api.approve_invoice(invoice["id"], {"tier": 1}, floater_sup))

        resp = api.approve_invoice(invoice["id"], {"tier": 2}, floater_mgr)
        validate_error(resp, ApiErrorId.ERR_SOD_SAME_APPROVER_TWO_TIERS.value)
        reloaded = get_invoice(invoice["id"])
        assert reloaded["status"] == "PENDING_APPROVAL"
        rows, meta = list_invoice_approvals(invoice["id"])
        assert meta["total_count"] == 1
        assert rows[0]["tier"] == 1
        assert rows[0]["approver_user_id"] == USER_FLOATER

    def test_approve_state_beats_submitter_sod_error(self, api):
        """On an already-APPROVED invoice the state guard fires even though the
        caller is also the round's submitter (state outranks SoD).

        PRD §2.11: "State legality follows — a transition whose source state does not permit it, an edit outside its allowed status window, or an acknowledgement aimed at an already-terminal resource is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), with the more specific state guards `ERR_CALLBACK_LOCKED`, `ERR_CALLBACK_EXPIRED`, and `ERR_PAYMENT_ALREADY_TERMINAL` applied where they exist."
        PRD §2.11: "Domain guards run last, in their declared order: business-safety rules (a blocked vendor, a pending sanctions review, duplicate-vendor enforcement, and the segregation-of-duties rules), then business constraints (vendor activity, documents, matrix coverage, merge gates, uniqueness, run contents, and callback codes), then temporal rules (cooling-off, document expiry, snapshot freshness), and finally the fiscal daily-release limit."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_submitter_sod
        """
        vendor = _aged_vendor_with_rule(
            api, legal_name="Priority Parts", tax_id="10-0000008")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-6001",
                                 received_date="2026-08-01", headers=SUP1)
        get_success_data(api.submit_invoice(invoice["id"], SUP1))
        validate_success(api.approve_invoice(invoice["id"], {"tier": 1}, SUP2))
        assert get_invoice(invoice["id"])["status"] == "APPROVED"

        # The caller IS the submitter (SoD-2 applies) but the state guard wins.
        resp = api.approve_invoice(invoice["id"], {"tier": 1}, SUP1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    def test_approve_state_beats_submitter_sod_state_unchanged(self, api):
        """After the rejected approve, the invoice is still APPROVED with
        exactly the one legitimate approval row.

        PRD §2.11: "State legality follows — a transition whose source state does not permit it, an edit outside its allowed status window, or an acknowledgement aimed at an already-terminal resource is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), with the more specific state guards `ERR_CALLBACK_LOCKED`, `ERR_CALLBACK_EXPIRED`, and `ERR_PAYMENT_ALREADY_TERMINAL` applied where they exist."
        PRD §3.5: "When the approved tier equals the invoice's `required_tier`, the approval is final: the invoice moves to `APPROVED`, the approval row is appended as usual, and the provisional discount snapshot is taken (§3.6)."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_submitter_sod
        """
        vendor = _aged_vendor_with_rule(
            api, legal_name="Priority Parts", tax_id="10-0000008")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-6001",
                                 received_date="2026-08-01", headers=SUP1)
        get_success_data(api.submit_invoice(invoice["id"], SUP1))
        validate_success(api.approve_invoice(invoice["id"], {"tier": 1}, SUP2))

        validate_error(api.approve_invoice(invoice["id"], {"tier": 1}, SUP1),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert get_invoice(invoice["id"])["status"] == "APPROVED"
        _rows, meta = list_invoice_approvals(invoice["id"])
        assert meta["total_count"] == 1


class TestRejectResubmitCycle:
    def _setup_reject_resubmit(self, api):
        """Tier-2 rule; aged vendor; round 1: submit, approve tier 1, reject at
        tier 2. Returns (vendor, invoice, rule_id)."""
        set_clock("2026-06-01T00:00:00Z")
        rule = create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                                  max_amount_cents=500000, tier=2)
        vendor = onboard_vendor_to_active(
            legal_name="Resubmit Traders", tax_id="10-0000005")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_invoice(vendor["id"], amount_cents=100000,
                                 invoice_number="INV-7701",
                                 received_date="2026-08-01")
        submitted = submit_invoice(invoice["id"])
        assert submitted["required_tier"] == 2
        validate_success(api.approve_invoice(invoice["id"], {"tier": 1}, SUP1))
        rejected = validate_success(api.reject_invoice(
            invoice["id"], {"tier": 2, "reason": "wrong cost center"}, MGR))
        assert rejected["status"] == "REJECTED"
        return vendor, invoice, rule["id"]

    def test_invoice_resubmit_resnapshots_required_tier(self, api):
        """Resubmit re-snapshots required_tier against the CURRENT matrix: after
        the tier-2 rule is retired and replaced by tier-1, round 2 needs one
        approval.

        PRD §3.5: "A rejected invoice can be resubmitted by the intake roles, moving from `REJECTED` back to `PENDING_APPROVAL`: the vendor must again be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`), a covering matrix rule must again exist (`ERR_NO_APPROVAL_RULE`), `approval_round` increments, the caller becomes the new `submitted_by_user_id`, and — critically — `required_tier` is re-snapshotted against the current matrix and the current activation and bank-verification timestamps, so matrix edits and vendor aging since the first submit take effect now."

        Design: Difficulty/non_linear_state_machine/invoice_reject_resubmit_resnapshots_tier
        """
        _vendor, invoice, rule_id = self._setup_reject_resubmit(api)
        get_success_data(api.retire_matrix_rule(rule_id, CTL))
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        resubmitted = validate_success(api.resubmit_invoice(invoice["id"], CLERK))
        assert resubmitted["status"] == "PENDING_APPROVAL"
        assert resubmitted["approval_round"] == 2
        assert resubmitted["required_tier"] == 1, \
            "re-snapshot against the replacement tier-1 rule"
        assert resubmitted["submitted_by_user_id"] == "u-ap-01"

    def test_sod5_is_per_round_so_round1_approver_may_approve_round2(self, api):
        """SoD-5 scopes to the current round: the operator who approved tier 1
        in round 1 may approve tier 1 again in round 2.

        PRD §2.6: "Within a single approval round of an invoice, one operator may approve at most one tier."
        PRD §3.5: "A valid intermediate-tier approval appends an `InvoiceApproval` row recording the `invoice_id`, the `round_no` equal to the invoice's `approval_round` at approval time, the `tier`, the `approver_user_id`, and the `approver_role` used for that tier, and the invoice remains `PENDING_APPROVAL`."

        Design: Difficulty/non_linear_state_machine/invoice_reject_resubmit_resnapshots_tier
        """
        _vendor, invoice, rule_id = self._setup_reject_resubmit(api)
        get_success_data(api.retire_matrix_rule(rule_id, CTL))
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        get_success_data(api.resubmit_invoice(invoice["id"], CLERK))

        approved = validate_success(api.approve_invoice(
            invoice["id"], {"tier": 1}, SUP1))
        assert approved["status"] == "APPROVED"
        rows, meta = list_invoice_approvals(invoice["id"])
        assert meta["total_count"] == 2
        assert sorted(r["round_no"] for r in rows) == [1, 2]
        assert all(r["approver_user_id"] == "u-sup-01" for r in rows)


class TestInvoiceNumberAndShape:
    def test_duplicate_invoice_number_rejected_and_freed_by_cancel(self, api):
        """invoice_number uniqueness is per vendor among non-CANCELLED invoices;
        cancelling frees the number.

        PRD §3.5: "The vendor gates fire before the invoice exists: a `BLOCKED` vendor rejects the intake with `ERR_VENDOR_BLOCKED`, a vendor in any status other than `ACTIVE` rejects it with `ERR_VENDOR_NOT_ACTIVE`, and an `invoice_number` already present on that vendor among invoices not in `CANCELLED` status rejects it with `ERR_DUPLICATE_INVOICE_NUMBER` — a cancelled invoice's number is free to be reused."
        PRD §3.5: "An `APClerk` may cancel an invoice from `RECEIVED`, `PENDING_APPROVAL`, or `REJECTED`, supplying an optional `reason`; the invoice becomes `CANCELLED`, and when it was cancelled mid-approval, that round's approval rows remain as history."

        Design: Corner/validations/duplicate_invoice_number_rejected_and_freed_by_cancel
        """
        vendor = onboard_vendor_to_active(
            legal_name="Number Nest", tax_id="20-0000034")
        first = create_invoice(vendor["id"], amount_cents=100000,
                               invoice_number="INV-X", received_date="2026-08-01")
        resp = api.create_invoice(create_invoice_payload(
            vendor_id=vendor["id"], invoice_number="INV-X", amount_cents=50000,
            cost_center="CC-100", received_date="2026-08-01"), CLERK)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE_NUMBER.value)

        cancelled = validate_success(api.cancel_invoice(
            first["id"], {"reason": "duplicate keyed"}, CLERK))
        assert cancelled["status"] == "CANCELLED"
        second = validate_success(api.create_invoice(create_invoice_payload(
            vendor_id=vendor["id"], invoice_number="INV-X", amount_cents=50000,
            cost_center="CC-100", received_date="2026-08-01"), CLERK),
            expected_status=201)
        assert second["status"] == "RECEIVED"
        assert second["invoice_number"] == "INV-X"

    def test_invalid_enum_and_nonpositive_amount_return_invalid_request(self, api):
        """Two request-shape violations: an undeclared payment_method enum value
        and a zero amount_cents both fail with ERR_INVALID_REQUEST.

        PRD §2.11: "Request-shape validity comes next — an unparsable body, a missing required field, an invalid enum value, a non-positive `amount_cents`, a negative `min_amount_cents`, a `tax_id` supplied in a vendor edit, or a document window whose `valid_from` falls after its `valid_until` are all rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/errors/invalid_enum_and_nonpositive_amount_return_invalid_request
        """
        vendor = create_vendor(legal_name="Shape Ship", tax_id="20-0000051")
        resp1 = api.create_payment_run({
            "scheduled_date": "2026-08-05", "payment_method": "PIGEON"}, TA)
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST.value)
        resp2 = api.create_invoice(create_invoice_payload(
            vendor_id=vendor["id"], invoice_number="INV-9004", amount_cents=0,
            cost_center="CC-100", received_date="2026-08-01"), CLERK)
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST.value)
