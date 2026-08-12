"""Assignment lifecycle: rework cycle, capacity rules, validation-ladder
precedence, credential gating, and productivity accounting."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_assignment,
    make_coder,
    make_coder_headers,
    setup_assigned,
    setup_ready_chart,
    setup_submitted_case,
    validate_error,
    validate_success,
)


class TestAssignmentReworkCycle:
    def test_return_moves_back_to_in_coding(self, api, manager_headers):
        """PRD §3.5: "Returning requires a non-empty `return_reason`; it moves
        the assignment from `SUBMITTED` to `RETURNED`, pushes the chart back
        from `SUBMITTED` to `IN_CODING`, and increments the assignment's
        `returned_count`."

        Design: Difficulty/non_linear_state_machine/assignment_rework_cycle
        """
        ctx = setup_submitted_case(
            "MRN-NL1", "E-NL1",
            acuity="MEDICAL_LOW", credential="CCS", total_charges_cents=900000,
            financial_class="MEDICAID",
        )
        returned = validate_success(
            api.return_assignment(
                ctx["assignment"]["id"], {"return_reason": "query physician on specificity"},
                manager_headers,
            ),
            200,
        )
        assert returned["status"] == "RETURNED"
        assert returned["returned_count"] == 1
        chart = get_success_data(api.get_chart(ctx["chart"]["id"], manager_headers))
        assert chart["status"] == "IN_CODING"

    def test_rework_cycle_reenters_and_completes(self, api, manager_headers):
        """PRD §3.5: "The same coder then re-enters through the start action —
        `RETURNED` to `IN_PROGRESS` under the same caller, credential, and
        capacity checks as a first start — edits lines while the chart is
        `IN_CODING`, and submits again. The rework loop may repeat as often as
        needed."

        Design: Difficulty/non_linear_state_machine/assignment_rework_cycle
        """
        ctx = setup_submitted_case(
            "MRN-NL1B", "E-NL1B",
            acuity="MEDICAL_LOW", credential="CCS", total_charges_cents=900000,
            financial_class="MEDICAID",
        )
        coder_id = ctx["coder"]["id"]
        returned = get_success_data(
            api.return_assignment(
                ctx["assignment"]["id"], {"return_reason": "rework"}, manager_headers
            )
        )
        assert returned["status"] == "RETURNED"

        restarted = validate_success(
            api.start_assignment(ctx["assignment"]["id"], make_coder_headers(coder_id)), 200
        )
        assert restarted["status"] == "IN_PROGRESS"

        resubmitted = validate_success(
            api.submit_assignment(ctx["assignment"]["id"], make_coder_headers(coder_id)), 200
        )
        assert resubmitted["status"] == "SUBMITTED"

        accepted = validate_success(
            api.accept_assignment(ctx["assignment"]["id"], manager_headers), 200
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["returned_count"] == 1
        chart = get_success_data(api.get_chart(ctx["chart"]["id"], manager_headers))
        assert chart["status"] == "CODED"


class TestSingleInProgressCapacity:
    def _two_assignments_one_started(self, api, tag):
        coder = make_coder(f"E-TO1{tag}", credential="CCS", full_name="Cap Acity")
        acct_a, chart_a = setup_ready_chart(f"MRN-TO1{tag}A", acuity="MEDICAL_HIGH")
        acct_b, chart_b = setup_ready_chart(f"MRN-TO1{tag}B", acuity="MEDICAL_HIGH")
        asg_a = make_assignment(chart_a["id"], coder_id=coder["id"])
        asg_b = make_assignment(chart_b["id"], coder_id=coder["id"])
        get_success_data(api.start_assignment(asg_a["id"], make_coder_headers(coder["id"])))
        return coder, asg_a, asg_b

    def test_second_start_rejected_workload_overlap(self, api, manager_headers):
        """PRD §3.3: "A coder may hold at most one `IN_PROGRESS` assignment —
        an aggregate capacity of one — so starting while another assignment is
        already in progress is rejected with `ERR_WORKLOAD_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/coder_single_in_progress_capacity
        """
        coder, asg_a, asg_b = self._two_assignments_one_started(api, "X")
        res = api.start_assignment(asg_b["id"], make_coder_headers(coder["id"]))
        validate_error(res, ApiErrorId.ERR_WORKLOAD_OVERLAP, expected_status=409)

    def test_overlap_rejection_leaves_both_assignments_unchanged(self, api, manager_headers):
        """PRD §3.3: "starting while another assignment is already in progress
        is rejected with `ERR_WORKLOAD_OVERLAP`" — a rejected start mutates
        nothing.

        Design: Difficulty/resource_temporal_overlap/coder_single_in_progress_capacity
        """
        coder, asg_a, asg_b = self._two_assignments_one_started(api, "Y")
        validate_error(
            api.start_assignment(asg_b["id"], make_coder_headers(coder["id"])),
            ApiErrorId.ERR_WORKLOAD_OVERLAP,
            expected_status=409,
        )
        b_after = get_success_data(api.get_assignment(asg_b["id"], manager_headers))
        a_after = get_success_data(api.get_assignment(asg_a["id"], manager_headers))
        assert b_after["status"] == "ASSIGNED"
        assert a_after["status"] == "IN_PROGRESS"


class TestCredentialBeatsWorkloadOverlap:
    def _setup_downgraded_busy_coder(self, api, manager_headers, tag):
        coder = make_coder(f"E-PC2{tag}", credential="CCS", full_name="Prio Two")
        acct_a, chart_a = setup_ready_chart(f"MRN-PC2{tag}A", acuity="MEDICAL_HIGH")
        acct_b, chart_b = setup_ready_chart(f"MRN-PC2{tag}B", acuity="MEDICAL_HIGH")
        asg_a = make_assignment(chart_a["id"], coder_id=coder["id"])
        asg_b = make_assignment(chart_b["id"], coder_id=coder["id"])
        get_success_data(api.start_assignment(asg_a["id"], make_coder_headers(coder["id"])))
        get_success_data(api.patch_coder(coder["id"], {"credential": "CCA"}, manager_headers))
        return coder, asg_a, asg_b

    def test_credential_error_wins_over_overlap(self, api, manager_headers):
        """PRD §2.8: "when a coder starts an assignment, the credential-rank
        check (tier 6) is evaluated before the one-assignment-in-progress
        workload rule (tier 8), so an under-credentialed coder who is also busy
        sees `ERR_CODER_CREDENTIAL_INSUFFICIENT`, not `ERR_WORKLOAD_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/start_credential_beats_workload_overlap
        """
        coder, asg_a, asg_b = self._setup_downgraded_busy_coder(api, manager_headers, "X")
        res = api.start_assignment(asg_b["id"], make_coder_headers(coder["id"]))
        validate_error(res, ApiErrorId.ERR_CODER_CREDENTIAL_INSUFFICIENT, expected_status=422)

    def test_losing_assignment_state_unchanged(self, api, manager_headers):
        """PRD §2.8: "Because of this ordering, checks at a lower number mask
        those at a higher one." The masked request must leave state untouched.

        Design: Difficulty/priority_pair_validation_conflict/start_credential_beats_workload_overlap
        """
        coder, asg_a, asg_b = self._setup_downgraded_busy_coder(api, manager_headers, "Z")
        validate_error(
            api.start_assignment(asg_b["id"], make_coder_headers(coder["id"])),
            ApiErrorId.ERR_CODER_CREDENTIAL_INSUFFICIENT,
            expected_status=422,
        )
        b_after = get_success_data(api.get_assignment(asg_b["id"], manager_headers))
        assert b_after["status"] == "ASSIGNED"


class TestStartRequiresActiveCoder:
    def test_start_by_inactive_coder_rejected(self, api, manager_headers):
        """PRD §3.3: "The caller must be the assignment's own coder (anyone
        else is refused with `ERR_FORBIDDEN`), the coder must be `ACTIVE`
        (`ERR_CODER_INACTIVE` otherwise), and the credential-rank check is
        applied again (`ERR_CODER_CREDENTIAL_INSUFFICIENT`)."

        Design: Difficulty/cross_entity_state_dependency/assignment_start_requires_active_coder
        """
        ctx = setup_assigned("MRN-CE2", "E-CE2", acuity="MEDICAL_LOW", credential="CCS")
        get_success_data(
            api.patch_coder(ctx["coder"]["id"], {"status": "INACTIVE"}, manager_headers)
        )
        res = api.start_assignment(
            ctx["assignment"]["id"], make_coder_headers(ctx["coder"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_CODER_INACTIVE, expected_status=409)

    def test_inactive_rejection_keeps_assignment_assigned(self, api, manager_headers):
        """PRD §2.8: "the target resource must be in a state that permits the
        requested transition; generic state-precondition failures yield
        `ERR_INVALID_STATE` (HTTP 409)" — the rejected start is not a
        transition, so the assignment stays ASSIGNED. PRD §3.3: "the coder
        must be `ACTIVE` (`ERR_CODER_INACTIVE` otherwise)".

        Design: Difficulty/cross_entity_state_dependency/assignment_start_requires_active_coder
        """
        ctx = setup_assigned("MRN-CE2B", "E-CE2B", acuity="MEDICAL_LOW", credential="CCS")
        get_success_data(
            api.patch_coder(ctx["coder"]["id"], {"status": "INACTIVE"}, manager_headers)
        )
        validate_error(
            api.start_assignment(ctx["assignment"]["id"], make_coder_headers(ctx["coder"]["id"])),
            ApiErrorId.ERR_CODER_INACTIVE,
            expected_status=409,
        )
        after = get_success_data(api.get_assignment(ctx["assignment"]["id"], manager_headers))
        assert after["status"] == "ASSIGNED"


class TestSubmitFromReturnedBeatsMissingPrincipal:
    def test_state_error_wins_over_principal_check(self, api, manager_headers):
        """PRD §2.8: "State admissibility — the target resource must be in a
        state that permits the requested transition; generic state-precondition
        failures yield `ERR_INVALID_STATE` (HTTP 409). This covers, for
        example, submitting from `RETURNED`", and tier 4 precedes the tier-7
        business constraints because "checks at a lower number mask those at a
        higher one."

        Design: Difficulty/priority_pair_validation_conflict/submit_from_returned_state_beats_missing_principal
        """
        ctx = setup_submitted_case(
            "MRN-PC1", "E-PC1", acuity="MEDICAL_LOW", credential="CCS"
        )
        coder_id = ctx["coder"]["id"]
        pdx_id = ctx["dx_line_ids"][0]
        get_success_data(
            api.return_assignment(ctx["assignment"]["id"], {"return_reason": "rework"}, manager_headers)
        )
        # chart is IN_CODING again; void the only principal
        get_success_data(
            api.patch_diagnosis_line(pdx_id, {"status": "VOID"}, make_coder_headers(coder_id))
        )
        res = api.submit_assignment(ctx["assignment"]["id"], make_coder_headers(coder_id))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_assignment_stays_returned_after_masked_submit(self, api, manager_headers):
        """PRD §2.8: "Because of this ordering, checks at a lower number mask
        those at a higher one." The masked submit from RETURNED cannot move
        the assignment.

        Design: Difficulty/priority_pair_validation_conflict/submit_from_returned_state_beats_missing_principal
        """
        ctx = setup_submitted_case(
            "MRN-PC1B", "E-PC1B", acuity="MEDICAL_LOW", credential="CCS"
        )
        coder_id = ctx["coder"]["id"]
        pdx_id = ctx["dx_line_ids"][0]
        get_success_data(
            api.return_assignment(ctx["assignment"]["id"], {"return_reason": "rework"}, manager_headers)
        )
        get_success_data(
            api.patch_diagnosis_line(pdx_id, {"status": "VOID"}, make_coder_headers(coder_id))
        )
        validate_error(
            api.submit_assignment(ctx["assignment"]["id"], make_coder_headers(coder_id)),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )
        after = get_success_data(api.get_assignment(ctx["assignment"]["id"], manager_headers))
        assert after["status"] == "RETURNED"


def test_accept_assignment_as_coder_forbidden(api, manager_headers):
    """PRD §3.5: "Acceptance is the terminal act of the coding workflow and
    belongs to the `CodingManager`." PRD §2.1: "an attempt to perform an
    action outside of the caller's designated role is rejected with
    `ERR_FORBIDDEN` (HTTP 403)".

    Design: Corner/rbac/accept_assignment_as_coder_forbidden
    """
    ctx = setup_submitted_case("MRN-RB1", "E-RB1", acuity="MEDICAL_LOW", credential="CCS")
    res = api.accept_assignment(
        ctx["assignment"]["id"], make_coder_headers(ctx["coder"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    after = get_success_data(api.get_assignment(ctx["assignment"]["id"], manager_headers))
    assert after["status"] == "SUBMITTED"


class TestProductivityAfterAccept:
    def test_productivity_weighted_units_after_accept(self, api, manager_headers):
        """PRD §3.5: "the coder's `workload_units` is credited back by the
        chart's acuity weight, `accepted_count` increases by one,
        `accepted_weighted_units` grows by the same acuity weight, and the
        coder's `productivity_units_per_day` is recomputed." PRD §3.6 (coder
        profile): "`productivity_units_per_day` is `accepted_weighted_units`
        divided by a 30-day productivity basis, rounded half up to two decimal
        places."

        SURGICAL accept: 3 / 30 = 0.10.

        Design: Corner/calculations/productivity_weighted_units_after_accept
        """
        ctx = setup_submitted_case(
            "MRN-CL2", "E-CL2",
            acuity="SURGICAL", credential="RHIA", total_charges_cents=900000,
            financial_class="COMMERCIAL",
            proc_lines=[{"pcs_code": "0210093", "is_or": True}],
        )
        validate_success(api.accept_assignment(ctx["assignment"]["id"], manager_headers), 200)
        coder = validate_success(api.get_coder(ctx["coder"]["id"], manager_headers), 200)
        assert coder["accepted_count"] == 1
        assert coder["accepted_weighted_units"] == 3
        assert coder["productivity_units_per_day"] == pytest.approx(0.10, abs=1e-9)
        assert coder["workload_units"] == 0
