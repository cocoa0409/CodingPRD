"""Approval gates, segregation of duties, validation-priority masks."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_and_submit_requisition,
    create_competitive_requisition,
    create_department,
    create_grant,
    create_open_solicitation,
    create_requisition_draft,
    create_vendor,
    get_success_data,
    make_requester_headers,
    make_role_headers,
    read_ledger,
    requisition_line,
    submit_requisition_ok,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, BUYER, DEPT_APPROVER, DIRECTOR, GRANT_OFFICER

ADMIN_H = ADMIN
BUYER_H = BUYER
DEPT_H = DEPT_APPROVER
GRANT_OFFICER_H = GRANT_OFFICER


class TestApproverLimitAndSelfApproval:
    def test_approver_limit_and_self_approval_forbidden(self, api):
        """PRD §3.3: "at a `DEPARTMENT` step, the department's
        `default_approval_limit_cents` must cover the requisition's `total_cents`,
        or the decision is rejected with `ERR_APPROVER_LIMIT_EXCEEDED`".
        PRD §3.3: "any approver whose `X-User-ID` equals the requisition's
        `requester_id` is refused with `ERR_SELF_APPROVAL_FORBIDDEN` on both
        decisions".

        Design: Corner/validations/approver_limit_and_self_approval_forbidden
        """
        dept = create_department(
            name="SmallDept", default_approval_limit_cents=450000
        )
        vendor = create_vendor(legal_name="OfficeCo")
        r1 = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="OFF", description="copier",
                unit_price_cents=500000, cost_category="EQUIPMENT",
            )],
        )
        r2 = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="OFF", description="paper",
                unit_price_cents=400000, cost_category="SUPPLIES",
            )],
        )

        over_limit = api.approve_requisition_step(r1["id"], {}, DEPT_H)
        validate_error(over_limit, ApiErrorId.ERR_APPROVER_LIMIT_EXCEEDED, 422)
        live = get_success_data(api.get_requisition(r1["id"], ADMIN_H))
        assert live["current_step_index"] == 0, "failed gate must not advance"

        self_approve = api.approve_requisition_step(
            r2["id"], {}, make_role_headers("req-user-1", "DepartmentApprover")
        )
        validate_error(self_approve, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN, 403)


class TestSoleSourceConditionals:
    def test_sole_source_amount_conditional_rules(self, api):
        """PRD §3.3: "when `sole_source_requested` is set and the total reaches
        5,000 dollars (500,000 cents), a non-empty `sole_source_justification` is
        mandatory (otherwise `ERR_SOLE_SOURCE_JUSTIFICATION_REQUIRED`); when the
        total is below that mark, requesting sole source at all is malformed and
        rejected with `ERR_INVALID_REQUEST`."
        PRD §3.3: "A `SOLE_SOURCE` step is added when the requester asked to waive
        competition and the total reaches 500,000 cents. A `PURCHASING` step is
        added whenever the total reaches 500,000 cents."

        Design: Corner/validations/sole_source_justification_conditional_rules
        """
        dept = create_department(name="Music3")
        vendor = create_vendor(legal_name="UniqueCo")

        r1 = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"],
            sole_source_requested=True,
            lines=[requisition_line(
                commodity_code="MUS", description="harp",
                unit_price_cents=600000, cost_category="EQUIPMENT",
            )],
        )
        missing = api.submit_requisition(
            r1["id"], make_requester_headers("req-user-1")
        )
        validate_error(
            missing, ApiErrorId.ERR_SOLE_SOURCE_JUSTIFICATION_REQUIRED, 422
        )

        r2 = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"],
            sole_source_requested=True, sole_source_justification="only maker",
            lines=[requisition_line(
                commodity_code="MUS", description="harp2",
                unit_price_cents=600000, cost_category="EQUIPMENT",
            )],
        )
        ok = submit_requisition_ok(r2["id"])
        assert ok["required_chain"] == ["DEPARTMENT", "SOLE_SOURCE", "PURCHASING"]

        r3 = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"],
            sole_source_requested=True,
            sole_source_justification="n/a at this size",
            lines=[requisition_line(
                commodity_code="MUS", description="strings",
                unit_price_cents=400000, cost_category="SUPPLIES",
            )],
        )
        below = api.submit_requisition(
            r3["id"], make_requester_headers("req-user-1")
        )
        validate_error(below, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestPurchasingGate:
    def test_purchasing_step_requires_awarded_solicitation(self, api):
        """PRD §3.3: "at a `PURCHASING` step, when the total is at least
        2,500,000 cents and the requisition neither rides a contract nor carries
        an approved sole source, an awarded solicitation for this requisition must
        already exist, or the decision is rejected with `ERR_SOURCING_REQUIRED`."

        Design: Corner/validations/purchasing_gate_requires_award_before_step
        """
        req = create_competitive_requisition(total_cents=3000000)
        create_open_solicitation(req["id"])  # OPEN, not yet awarded
        gate = api.approve_requisition_step(req["id"], {}, BUYER_H)
        validate_error(gate, ApiErrorId.ERR_SOURCING_REQUIRED, 409)
        live = get_success_data(api.get_requisition(req["id"], ADMIN_H))
        assert live["status"] == "SUBMITTED"
        assert live["current_step_index"] == 1


class TestPriorityStateMasksFiscal:
    def _returned_unaffordable_grant_req(self, api):
        dept = create_department(name="Geology")
        vendor = create_vendor(legal_name="RockCo")
        grant = create_grant(
            grant_code="G-SM", sponsor="NASA", total_award_cents=500000,
            allowed_categories=["SUPPLIES"],
        )
        req = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[requisition_line(
                commodity_code="GEO", description="cores",
                unit_price_cents=400000, cost_category="SUPPLIES",
            )],
        )
        get_success_data(api.approve_requisition_step(req["id"], {}, DEPT_H))
        get_success_data(
            api.return_requisition_step(
                req["id"], {"reason": "scope question"}, GRANT_OFFICER_H
            )
        )
        return grant, req

    def test_approve_on_returned_reports_state_error_not_fiscal(self, api):
        """PRD §2.8: "Every request passes through a fixed validation ladder, and
        the rungs are evaluated in the following order — a failure on an earlier
        rung prevents any later rung from being evaluated, so the error a client
        observes is always the earliest applicable one" (lifecycle preconditions
        on rung 6 precede money ceilings on rung 11).
        PRD §3.3: "Approving or returning from a status other than `SUBMITTED` is
        rejected with `ERR_REQUISITION_NOT_IN_APPROVAL`".

        Design: Difficulty/priority_pair_validation_conflict/priority_state_mask_fiscal_on_returned_requisition
        """
        _, req = self._returned_unaffordable_grant_req(api)
        resp = api.approve_requisition_step(req["id"], {}, GRANT_OFFICER_H)
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_IN_APPROVAL, 409)

    def test_masked_fiscal_leaves_grant_ledger_untouched(self, api):
        """PRD §3.3: "on success the requisition becomes `APPROVED` and its
        `charge_cents` is added to the grant's `encumbered_cents`" — a rejected
        decision records nothing.
        PRD §2.8: "a failure on an earlier rung prevents any later rung from being
        evaluated".

        Design: Difficulty/priority_pair_validation_conflict/priority_state_mask_fiscal_on_returned_requisition
        """
        grant, req = self._returned_unaffordable_grant_req(api)
        resp = api.approve_requisition_step(req["id"], {}, GRANT_OFFICER_H)
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_IN_APPROVAL, 409)
        ledger = read_ledger(grant["id"])
        assert ledger["encumbered_cents"] == 0
        assert ledger["spent_cents"] == 0


class TestPrioritySafetyMasksReferential:
    def test_submit_reports_category_error_not_vendor_suspended(self, api):
        """PRD §2.8: "a failure on an earlier rung prevents any later rung from
        being evaluated, so the error a client observes is always the earliest
        applicable one" — rung 7 names "grant cost-category allowability
        (`ERR_GRANT_CATEGORY_NOT_ALLOWABLE`)" ahead of rung 10's
        "`ERR_VENDOR_SUSPENDED`".
        PRD §3.3: "every line's `cost_category` must appear in the grant's
        `allowed_categories` (otherwise `ERR_GRANT_CATEGORY_NOT_ALLOWABLE`)".

        Design: Difficulty/priority_pair_validation_conflict/priority_safety_mask_referential_on_submit
        """
        dept = create_department(name="History")
        vendor = create_vendor(legal_name="TravelCo")
        get_success_data(
            api.suspend_vendor(vendor["id"], {"reason": "audit hold"}, ADMIN_H)
        )
        grant = create_grant(
            grant_code="G-CAT", sponsor="Mellon", total_award_cents=5000000,
            allowed_categories=["SUPPLIES"],
        )
        req = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[requisition_line(
                commodity_code="HIS", description="archive trip",
                unit_price_cents=100000, cost_category="TRAVEL",
            )],
        )
        resp = api.submit_requisition(req["id"], make_requester_headers("req-user-1"))
        validate_error(resp, ApiErrorId.ERR_GRANT_CATEGORY_NOT_ALLOWABLE, 422)

    def test_failed_submit_leaves_requisition_draft_unstamped(self, api):
        """PRD §3.3: "Both `submitted_at` and `returned_reason` remain null until
        events fill them."
        PRD §3.3: "A successful submission stamps `submitted_at` with the logical
        clock and pins the approval route" — a rejected submission does neither.

        Design: Difficulty/priority_pair_validation_conflict/priority_safety_mask_referential_on_submit
        """
        dept = create_department(name="History")
        vendor = create_vendor(legal_name="TravelCo")
        get_success_data(
            api.suspend_vendor(vendor["id"], {"reason": "audit hold"}, ADMIN_H)
        )
        grant = create_grant(
            grant_code="G-CAT", sponsor="Mellon", total_award_cents=5000000,
            allowed_categories=["SUPPLIES"],
        )
        req = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[requisition_line(
                commodity_code="HIS", description="archive trip",
                unit_price_cents=100000, cost_category="TRAVEL",
            )],
        )
        resp = api.submit_requisition(req["id"], make_requester_headers("req-user-1"))
        validate_error(resp, ApiErrorId.ERR_GRANT_CATEGORY_NOT_ALLOWABLE, 422)
        live = get_success_data(api.get_requisition(req["id"], ADMIN_H))
        assert live["status"] == "DRAFT"
        assert live.get("submitted_at") is None


class TestPriorityExistenceMasksState:
    def _submitted_req_with_version(self):
        dept = create_department(name="Dance")
        vendor = create_vendor(legal_name="StageLights")
        req = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="DAN", description="floor",
                unit_price_cents=400000, cost_category="EQUIPMENT",
            )],
        )
        return req

    def test_patch_with_missing_grant_reports_404_not_state(self, api):
        """PRD §2.8 rung 3: "path identifiers exist, validated left to right, and
        identifiers referenced in the request body (such as `department_id`,
        `vendor_id`, `grant_id`, `contract_id`, or `claiming_department_id`)
        exist (the 404 family described in §2.9)" — evaluated ahead of the
        lifecycle rung.
        PRD §2.8: "a failure on an earlier rung prevents any later rung from
        being evaluated, so the error a client observes is always the earliest
        applicable one".

        Design: Difficulty/priority_pair_validation_conflict/priority_existence_mask_state_on_patch
        """
        req = self._submitted_req_with_version()
        resp = api.patch_requisition(
            req["id"],
            {
                "expected_requisition_version": req["version"],
                "grant_id": NON_EXISTENT_UUID,
            },
            make_requester_headers("req-user-1"),
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_NOT_FOUND, 404)

    def test_patch_submitted_with_valid_refs_reports_not_editable(self, api):
        """PRD §3.3: "While the requisition is `DRAFT` or `RETURNED`, the requester
        may edit it; editing from any other status is rejected with
        `ERR_REQUISITION_NOT_EDITABLE`."

        Design: Difficulty/priority_pair_validation_conflict/priority_existence_mask_state_on_patch
        """
        req = self._submitted_req_with_version()
        resp = api.patch_requisition(
            req["id"],
            {
                "expected_requisition_version": req["version"],
                "sole_source_justification": "still submitted",
            },
            make_requester_headers("req-user-1"),
        )
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_EDITABLE, 409)


class TestGrantChargePinnedOrder:
    def _setup_two_grants(self):
        dept = create_department(name="Engineering")
        vendor = create_vendor(legal_name="EquipCo")
        g1 = create_grant(
            grant_code="G1", sponsor="NIH", total_award_cents=1000000,
            allowed_categories=["SUPPLIES", "EQUIPMENT"],
        )
        g2 = create_grant(
            grant_code="G2", sponsor="NIH", total_award_cents=2000000,
            allowed_categories=["SUPPLIES", "EQUIPMENT"],
        )
        return dept, vendor, g1, g2

    def _equipment_req(self, dept, vendor, grant, unit_price, tag):
        req = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[
                requisition_line(
                    commodity_code="ENG", description="parts", quantity=2,
                    unit_price_cents=150000, cost_category="SUPPLIES",
                ),
                requisition_line(
                    commodity_code="ENG", description=tag, quantity=1,
                    unit_price_cents=unit_price, cost_category="EQUIPMENT",
                ),
            ],
        )
        return req

    def test_equipment_at_cap_not_excluded_and_budget_402(self, api):
        """PRD §3.3: "first the equipment exclusion, the sum of quantity times unit
        price over lines whose `cost_category` is `EQUIPMENT` and whose unit price
        is strictly greater than the grant's `equipment_cap_cents` — a unit price
        exactly equal to the cap is not excluded".
        PRD §3.3: "for a grant-funded requisition the grant's
        `provisional_remaining_cents` must cover the requisition's `charge_cents`
        — the full charge including indirect cost, not merely the direct total —
        or the decision is rejected with `ERR_GRANT_BUDGET_EXCEEDED` (HTTP 402)".

        Design: Difficulty/combinatorial_formula/grant_charge_pinned_evaluation_order
        """
        dept, vendor, g1, _ = self._setup_two_grants()
        r1 = self._equipment_req(dept, vendor, g1, 500000, "lathe")
        # direct 800,000; unit == cap is NOT excluded; indirect 416,000.
        assert r1["charge_cents"] == 1216000, (
            f"charge must be 800,000 + round_half_up(0.52*800,000), got "
            f"{r1['charge_cents']}"
        )
        get_success_data(api.approve_requisition_step(r1["id"], {}, DEPT_H))
        get_success_data(api.approve_requisition_step(r1["id"], {}, GRANT_OFFICER_H))
        final = api.approve_requisition_step(r1["id"], {}, BUYER_H)
        validate_error(final, ApiErrorId.ERR_GRANT_BUDGET_EXCEEDED, 402)
        live = get_success_data(api.get_requisition(r1["id"], ADMIN_H))
        assert live["status"] == "SUBMITTED"
        assert read_ledger(g1["id"])["encumbered_cents"] == 0

    def test_equipment_above_cap_excluded_and_approval_succeeds(self, api):
        """PRD §3.3: "a unit price exactly equal to the cap is not excluded" —
        conversely a unit price strictly above the cap leaves the indirect base.
        PRD §3.3: "on success the requisition becomes `APPROVED` and its
        `charge_cents` is added to the grant's `encumbered_cents`."

        Design: Difficulty/combinatorial_formula/grant_charge_pinned_evaluation_order
        """
        dept, vendor, _, g2 = self._setup_two_grants()
        r2 = self._equipment_req(dept, vendor, g2, 500001, "lathe+")
        # direct 800,001; equipment 500,001 excluded; indirect on 300,000.
        assert r2["charge_cents"] == 956001, (
            f"charge must be 800,001 + round_half_up(0.52*300,000), got "
            f"{r2['charge_cents']}"
        )
        get_success_data(api.approve_requisition_step(r2["id"], {}, DEPT_H))
        get_success_data(api.approve_requisition_step(r2["id"], {}, GRANT_OFFICER_H))
        final = get_success_data(api.approve_requisition_step(r2["id"], {}, BUYER_H))
        assert final["status"] == "APPROVED"
        assert read_ledger(g2["id"])["encumbered_cents"] == 956001
