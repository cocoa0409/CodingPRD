"""Requisition pipeline: chain assembly, thresholds, return/resubmit, audit."""
from test_helpers import (
    ApiErrorId,
    assert_approval_record,
    assert_requisition,
    create_and_submit_requisition,
    create_approved_requisition,
    create_department,
    create_grant,
    create_requisition_draft,
    create_vendor,
    get_success_data,
    issue_po_ok,
    make_requester_headers,
    requisition_line,
    submit_requisition_ok,
    validate_error,
    validate_paginated,
    validate_success,
    walk_approval_chain,
)
from test_helpers.fixtures import (
    ADMIN,
    BUYER,
    CONTRACT_OFFICER,
    DEPT_APPROVER,
    DIRECTOR,
    GRANT_OFFICER,
    RECEIVING,
)

ADMIN_H = ADMIN
BUYER_H = BUYER
DEPT_H = DEPT_APPROVER
DIRECTOR_H = DIRECTOR
GRANT_OFFICER_H = GRANT_OFFICER


def _physics_sole_source_setup():
    """Grant-funded sole-source requisition at exactly 2,500,000 cents."""
    dept = create_department(name="Physics")
    vendor = create_vendor(legal_name="SoleSourceInc")
    grant = create_grant(
        grant_code="DOE-7", sponsor="DOE", total_award_cents=10000000,
        allowed_categories=["SUPPLIES", "EQUIPMENT"],
    )
    req = create_requisition_draft(
        department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
        sole_source_requested=True,
        sole_source_justification="only manufacturer of the cryostat",
        lines=[requisition_line(
            commodity_code="PHY", description="cryostat", quantity=5,
            unit_price_cents=500000, cost_category="EQUIPMENT",
        )],
    )
    return dept, vendor, grant, req


class TestApprovalChainAssembly:
    def test_chain_assembles_in_pinned_order_and_rejects_wrong_role(self, api):
        """PRD §3.3: "The chain always opens with a `DEPARTMENT` step. A
        `GRANT_COMPLIANCE` step follows whenever the requisition is grant-funded.
        A `SOLE_SOURCE` step is added when the requester asked to waive competition
        and the total reaches 500,000 cents. A `PURCHASING` step is added whenever
        the total reaches 500,000 cents. A `DIRECTOR` step is added when the total
        reaches 2,500,000 cents, and a `CONTRACT_REVIEW` step when it reaches
        10,000,000 cents."
        PRD §3.3: "acting with a role that does not match the step named by
        `required_chain` at `current_step_index` is rejected with
        `ERR_APPROVAL_STEP_MISMATCH`".

        Design: Difficulty/combinatorial_formula/approval_chain_multi_input_assembly
        """
        _, _, _, req = _physics_sole_source_setup()
        submitted = submit_requisition_ok(req["id"])
        assert submitted["required_chain"] == [
            "DEPARTMENT", "GRANT_COMPLIANCE", "SOLE_SOURCE", "PURCHASING",
            "DIRECTOR",
        ], f"pinned chain order wrong: {submitted['required_chain']}"
        assert submitted["current_step_index"] == 0

        wrong_role = api.approve_requisition_step(req["id"], {}, BUYER_H)
        validate_error(wrong_role, ApiErrorId.ERR_APPROVAL_STEP_MISMATCH, 409)

    def test_full_chain_walk_sets_sole_source_flag_and_encumbrance(self, api):
        """PRD §3.3: "Approving a `SOLE_SOURCE` step additionally sets
        `sole_source_approved` to true (a flag that, once set, is never reset)
        and moves `sourcing_method` to `SOLE_SOURCE`."
        PRD §3.3: "on success the requisition becomes `APPROVED` and its
        `charge_cents` is added to the grant's `encumbered_cents`."

        Design: Difficulty/combinatorial_formula/approval_chain_multi_input_assembly
        """
        _, _, grant, req = _physics_sole_source_setup()
        submit_requisition_ok(req["id"])
        get_success_data(api.approve_requisition_step(req["id"], {}, DEPT_H))
        get_success_data(api.approve_requisition_step(req["id"], {}, GRANT_OFFICER_H))
        after_ss = get_success_data(
            api.approve_requisition_step(req["id"], {}, DIRECTOR_H)
        )
        assert after_ss["sole_source_approved"] is True
        assert after_ss["sourcing_method"] == "SOLE_SOURCE"

        # Remaining steps: PURCHASING (Buyer) then DIRECTOR (ProcurementDirector).
        get_success_data(api.approve_requisition_step(req["id"], {}, BUYER_H))
        final = get_success_data(
            api.approve_requisition_step(req["id"], {}, DIRECTOR_H)
        )
        assert final["status"] == "APPROVED", f"got {final['status']}"
        # charge = 2,500,000 + round_half_up(0.52 * 2,500,000); the 500,000-unit
        # equipment line equals the default cap and is NOT excluded.
        assert final["charge_cents"] == 3800000
        from test_helpers import read_ledger
        ledger = read_ledger(grant["id"])
        assert ledger["encumbered_cents"] == 3800000


class TestApprovalThresholdBoundary:
    def test_total_at_t1_includes_purchasing_step(self, api):
        """PRD §3.3: "All thresholds are inclusive: a total of exactly 500,000
        cents includes the `PURCHASING` step."

        Design: Difficulty/boundary_precision_check/approval_threshold_inclusive_boundary
        """
        dept = create_department(name="Math")
        vendor = create_vendor(legal_name="CalcCo")
        req = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="MTH", description="server",
                unit_price_cents=500000, cost_category="EQUIPMENT",
            )],
        )
        submitted = submit_requisition_ok(req["id"])
        assert submitted["required_chain"] == ["DEPARTMENT", "PURCHASING"]

    def test_total_one_cent_below_t1_excludes_purchasing(self, api):
        """PRD §3.3: "A `PURCHASING` step is added whenever the total reaches
        500,000 cents." and "All thresholds are inclusive: a total of exactly
        500,000 cents includes the `PURCHASING` step."

        Design: Difficulty/boundary_precision_check/approval_threshold_inclusive_boundary
        """
        dept = create_department(name="Math")
        vendor = create_vendor(legal_name="CalcCo")
        req = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="MTH", description="server-lite",
                unit_price_cents=499999, cost_category="EQUIPMENT",
            )],
        )
        submitted = submit_requisition_ok(req["id"])
        assert submitted["required_chain"] == ["DEPARTMENT"]


class TestReturnResubmitCycle:
    def _returned_setup(self, api):
        dept = create_department(name="Music")
        vendor = create_vendor(legal_name="SoundCo")
        req = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="MUS", description="mixer",
                unit_price_cents=600000, cost_category="EQUIPMENT",
            )],
        )
        chain_v1 = req["required_chain"]
        returned = get_success_data(
            api.return_requisition_step(
                req["id"], {"reason": "wrong model"}, DEPT_H
            )
        )
        return req, chain_v1, returned

    def test_resubmit_repins_chain_after_total_drop(self, api):
        """PRD §3.3: "A resubmission from `RETURNED` re-runs the entire submission
        gate, recomputes and re-pins the chain snapshot and the charge, and
        retains the earlier audit records as history."

        Design: Difficulty/non_linear_state_machine/requisition_return_resubmit_cycle_resets_chain
        """
        req, chain_v1, returned = self._returned_setup(api)
        assert chain_v1 == ["DEPARTMENT", "PURCHASING"]
        assert returned["status"] == "RETURNED"

        edited = get_success_data(
            api.patch_requisition(
                req["id"],
                {
                    "expected_requisition_version": returned["version"],
                    "lines": [requisition_line(
                        commodity_code="MUS", description="mixer-compact",
                        unit_price_cents=400000, cost_category="EQUIPMENT",
                    )],
                },
                make_requester_headers("req-user-1"),
            )
        )
        assert edited["total_cents"] == 400000
        resubmitted = submit_requisition_ok(req["id"])
        assert resubmitted["required_chain"] == ["DEPARTMENT"], (
            "chain must be re-pinned from the edited total"
        )
        assert resubmitted["current_step_index"] == 0
        final = walk_approval_chain(req["id"])
        assert final["status"] == "APPROVED"

    def test_audit_retains_both_cycles_and_version_monotonic(self, api):
        """PRD §3.3: "A resubmission from `RETURNED` re-runs the entire submission
        gate, recomputes and re-pins the chain snapshot and the charge, and
        retains the earlier audit records as history."
        PRD §2.5: "`version` — a system-managed integer that increments on every
        mutation".

        Design: Difficulty/non_linear_state_machine/requisition_return_resubmit_cycle_resets_chain
        """
        req, _, returned = self._returned_setup(api)
        get_success_data(
            api.patch_requisition(
                req["id"],
                {
                    "expected_requisition_version": returned["version"],
                    "lines": [requisition_line(
                        commodity_code="MUS", description="mixer-compact",
                        unit_price_cents=400000, cost_category="EQUIPMENT",
                    )],
                },
                make_requester_headers("req-user-1"),
            )
        )
        resubmitted = submit_requisition_ok(req["id"])
        final = walk_approval_chain(req["id"])
        assert final["status"] == "APPROVED"
        assert final["version"] > resubmitted["version"], (
            "the approving mutation increments the version"
        )
        # req was read after the first submit; return, edit, resubmit, and the
        # final approve are four further mutations of the requisition.
        assert final["version"] >= req["version"] + 4

        records, _ = validate_paginated(
            api.list_requisition_approvals(req["id"], ADMIN_H)
        )
        assert len(records) == 2
        for record in records:
            assert_approval_record(record)
        assert records[0]["decision"] == "RETURNED"
        assert records[0]["step_role"] == "DEPARTMENT"
        assert records[0]["actor_id"] == "dept-approver-1"
        assert records[1]["decision"] == "APPROVED"


class TestApprovalRecordImmutability:
    def test_approval_records_append_only_without_version(self, api):
        """PRD §2.5: "The single exception is the approval audit record, which is
        immutable once written: it carries only `id` and `created_at`, and both
        `updated_at` and `version` are absent from it."
        PRD §3.3: "the full chronological trail is listable per requisition".

        Design: Corner/entities/approval_record_append_only_immutability
        """
        dept = create_department(name="Linguistics")
        vendor = create_vendor(legal_name="BookCo")
        req = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="LIN", description="corpus",
                unit_price_cents=400000, cost_category="SERVICES",
            )],
        )
        get_success_data(
            api.return_requisition_step(
                req["id"], {"reason": "clarify scope"}, DEPT_H
            )
        )
        submit_requisition_ok(req["id"])
        get_success_data(api.approve_requisition_step(req["id"], {}, DEPT_H))

        records, _ = validate_paginated(
            api.list_requisition_approvals(req["id"], ADMIN_H)
        )
        assert len(records) == 2
        for record in records:
            assert_approval_record(record)
        assert records[0]["step_role"] == "DEPARTMENT"
        assert records[0]["decision"] == "RETURNED"
        assert records[0]["actor_id"] == "dept-approver-1"
        assert records[1]["step_role"] == "DEPARTMENT"
        assert records[1]["decision"] == "APPROVED"
        assert records[0]["created_at"] <= records[1]["created_at"]


class TestInvalidFromStates:
    def test_requisition_submitted_and_terminal_invalid_froms(self, api):
        """PRD §3.3: "The requester may cancel their own requisition from `DRAFT`,
        `RETURNED`, or `APPROVED`; from any other status — including `SUBMITTED`,
        where an approver holds the pen — cancellation is rejected with
        `ERR_REQUISITION_NOT_CANCELLABLE`".
        PRD §3.3: "The requisition must be `DRAFT` or `RETURNED` (otherwise
        `ERR_REQUISITION_NOT_SUBMITTABLE`)".
        PRD §3.3: "Approving or returning from a status other than `SUBMITTED` is
        rejected with `ERR_REQUISITION_NOT_IN_APPROVAL`".

        Design: Corner/state_machines/requisition_terminal_and_submitted_invalid_froms
        """
        dept = create_department(name="Botany")
        vendor = create_vendor(legal_name="SeedCo")
        req = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="BOT", description="seeds",
                unit_price_cents=400000, cost_category="SUPPLIES",
            )],
        )
        cancel_mid = api.cancel_requisition(
            req["id"], make_requester_headers("req-user-1")
        )
        validate_error(cancel_mid, ApiErrorId.ERR_REQUISITION_NOT_CANCELLABLE, 409)

        get_success_data(api.approve_requisition_step(req["id"], {}, DEPT_H))
        issue_po_ok(req["id"])  # terminal PO_ISSUED

        submit_again = api.submit_requisition(
            req["id"], make_requester_headers("req-user-1")
        )
        validate_error(submit_again, ApiErrorId.ERR_REQUISITION_NOT_SUBMITTABLE, 409)
        approve_terminal = api.approve_requisition_step(req["id"], {}, DEPT_H)
        validate_error(
            approve_terminal, ApiErrorId.ERR_REQUISITION_NOT_IN_APPROVAL, 409
        )
        cancel_terminal = api.cancel_requisition(
            req["id"], make_requester_headers("req-user-1")
        )
        validate_error(
            cancel_terminal, ApiErrorId.ERR_REQUISITION_NOT_CANCELLABLE, 409
        )
