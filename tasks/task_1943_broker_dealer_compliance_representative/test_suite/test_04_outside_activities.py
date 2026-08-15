"""Outside business activities and private securities transactions:
decision gates, PST fee accrual rounding order, compensating reversal,
suspension/resume, and validation priority (PRD §3.4, §2.10).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_activity_payload,
    create_plan_for_rep,
    decide_payload,
    get_rep,
    make_active_plan,
    make_activity,
    make_branch_with_rep,
    make_registered_rep_headers,
    make_sd_disclosure,
    acknowledge_disclosure,
    make_sd_rep,
    make_sd_rep_with_active_plan,
    make_suspended_oba,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
PRINCIPAL_A = TEST_USERS["principal_a_headers"]
ANY = TEST_USERS["any_headers"]

PST = "PRIVATE_SECURITIES_TRANSACTION"
OBA = "OUTSIDE_BUSINESS_ACTIVITY"


# ─── PST supervisory fee rounding order ───────────────

class TestPstFeeRoundingOrder:
    def test_per_approval_fee_rounded_half_up(self, api, any_headers):
        """PRD §3.4: "The per-approval fee is the estimated gross compensation
        multiplied by 2.5 percent, rounded half-up to whole cents and
        recorded on the request as `supervisory_fee_cents`".
        round_half_up(33333 * 0.025) = round_half_up(833.325) = 833 on each
        approval.

        Design: Difficulty/combinatorial_formula/combo_pst_fee_rounding_order
        """
        _branch, rep = make_branch_with_rep(region="NE", crd_number="100003")
        fees = []
        for label in ("PST A", "PST B"):
            activity = make_activity(
                rep, activity_type=PST, description=label,
                compensation_expected=True, estimated_gross_comp_cents=33333,
            )
            approved = validate_success(
                api.decide_outside_activity(activity["id"], decide_payload("APPROVE"),
                                            PRINCIPAL_A),
                200,
            )
            fees.append(approved["supervisory_fee_cents"])
        assert fees == [833, 833], f"per-approval rounding must give 833: {fees}"

    def test_total_is_sum_of_rounded_fees_not_rounded_sum(self, api, any_headers):
        """PRD §3.4: "each approval's fee is rounded to whole cents before
        any summation, and the representative's total is the sum of those
        per-approval rounded fees — summing gross amounts and rounding once
        at the end is forbidden, because the orders genuinely differ (two
        transactions of 33333 cents each yield 833 plus 833, totaling 1666
        cents, versus 1667 under sum-then-round)".

        Design: Difficulty/combinatorial_formula/combo_pst_fee_rounding_order
        """
        _branch, rep = make_branch_with_rep(region="NE", crd_number="100003")
        for label in ("PST A", "PST B"):
            activity = make_activity(
                rep, activity_type=PST, description=label,
                compensation_expected=True, estimated_gross_comp_cents=33333,
            )
            validate_success(
                api.decide_outside_activity(activity["id"], decide_payload("APPROVE"),
                                            PRINCIPAL_A),
                200,
            )
        rep_after = get_rep(rep["id"])
        assert rep_after["pst_fee_total_cents"] == 1666
        assert rep_after["active_approved_activity_count"] == 2


# ─── SD gate on decisions ─────────────────────────────

class TestSdGateOnObaDecision:
    def _setup_sd_rep_with_pending_oba(self):
        """Rep with a first OBA auto-suspended by the SD ack, plus a second
        OBA submitted after the ack that stays SUBMITTED."""
        branch, rep = make_branch_with_rep(region="N", crd_number="500001")
        first = make_activity(rep, activity_type=OBA, description="consulting")
        event = make_sd_disclosure(rep["id"], event_type="SECURITIES_MISDEMEANOR",
                                   event_date="2026-08-02")
        acknowledge_disclosure(event["id"])
        second = make_activity(rep, activity_type=OBA, description="second gig")
        return branch, get_rep(rep["id"]), first, second

    def test_decide_rejected_without_active_heightened_plan(self, api,
                                                            any_headers):
        """PRD §3.4: "if the representative is statutorily disqualified, they
        must have a heightened supervision plan in `ACTIVE`, else
        `ERR_SD_REP_REQUIRES_HEIGHTENED_PLAN` (HTTP 403)". The request is
        still SUBMITTED, so the safety gate — not the state check — fires.

        Design: Difficulty/cross_entity_state_dependency/cross_rep_sd_gates_oba_decision
        """
        _branch, rep, _first, second = self._setup_sd_rep_with_pending_oba()
        assert second["status"] == "SUBMITTED"

        res = api.decide_outside_activity(second["id"], decide_payload("APPROVE"),
                                          PRINCIPAL_A)
        validate_error(res, ApiErrorId.ERR_SD_REP_REQUIRES_HEIGHTENED_PLAN)

    def test_decide_succeeds_after_plan_activation(self, api, any_headers):
        """PRD §3.7: "An activated plan is the key that unlocks the gates of
        §3.4: approval decisions for a disqualified representative, and
        resumption of suspended requests, both consult it." PRD §3.4: "An
        approval stamps `decided_by`, increments the representative's
        `active_approved_activity_count` by one". The first request, moved to
        SUSPENDED_REVIEW by the §3.6 fan-out, is untouched by the gate.

        Design: Difficulty/cross_entity_state_dependency/cross_rep_sd_gates_oba_decision
        """
        _branch, rep, first, second = self._setup_sd_rep_with_pending_oba()
        make_active_plan(rep["id"], start_date="2026-08-03",
                         end_date="2027-08-02")

        approved = validate_success(
            api.decide_outside_activity(second["id"], decide_payload("APPROVE"),
                                        PRINCIPAL_A),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved.get("decided_by") == "principal-a"
        assert get_rep(rep["id"])["active_approved_activity_count"] == 1

        first_after = validate_success(
            api.get_outside_activity(first["id"], ANY), 200
        )
        assert first_after["status"] == "SUSPENDED_REVIEW"


# ─── resume gate ──────────────────────────────────────

class TestResumeRequiresActivePlan:
    def test_resume_rejected_while_plan_is_draft(self, api, any_headers):
        """PRD §3.4: "A principal may later resume such a request, returning
        it from `SUSPENDED_REVIEW` to `SUBMITTED`, but only while the
        representative has a heightened supervision plan in `ACTIVE` —
        resuming without one is rejected with
        `ERR_NO_ACTIVE_HEIGHTENED_PLAN`". A merely-DRAFT plan does not
        satisfy the gate.

        Design: Difficulty/cross_entity_state_dependency/cross_oba_resume_requires_active_plan
        """
        _branch, rep, activity = make_suspended_oba(
            crd_number="500002", event_type="REGULATORY_BAR"
        )
        plan = validate_success(
            create_plan_for_rep(rep["id"], start_date="2026-08-03",
                                end_date="2027-08-02"),
            201,
        )
        assert plan["status"] == "DRAFT"

        res = api.resume_outside_activity(activity["id"], PRINCIPAL_A)
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_HEIGHTENED_PLAN)

    def test_resume_succeeds_after_plan_activation(self, api, any_headers):
        """PRD §3.4: "A principal may later resume such a request, returning
        it from `SUSPENDED_REVIEW` to `SUBMITTED`, but only while the
        representative has a heightened supervision plan in `ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/cross_oba_resume_requires_active_plan
        """
        _branch, rep, activity = make_suspended_oba(
            crd_number="500002", event_type="REGULATORY_BAR"
        )
        make_active_plan(rep["id"], start_date="2026-08-03",
                         end_date="2027-08-02")

        resumed = validate_success(
            api.resume_outside_activity(activity["id"], PRINCIPAL_A), 200
        )
        assert resumed["status"] == "SUBMITTED"


# ─── approve/revoke conservation ──────────────────────

class TestApproveRevokeConservation:
    def test_approve_increments_active_count(self, api, any_headers):
        """PRD §3.4: "An approval stamps `decided_by`, increments the
        representative's `active_approved_activity_count` by one, and
        increments the representative's `version` by one."

        Design: Difficulty/compensating_invariant/compensating_oba_approve_revoke_count
        """
        _branch, rep = make_branch_with_rep(region="N", crd_number="700001")
        activity = make_activity(rep, activity_type=OBA, description="board")
        approved = validate_success(
            api.decide_outside_activity(activity["id"], decide_payload("APPROVE"),
                                        PRINCIPAL_A),
            200,
        )
        assert approved["status"] == "APPROVED"
        rep_after = get_rep(rep["id"])
        assert rep_after["active_approved_activity_count"] == 1
        assert rep_after["version"] == rep["version"] + 1

    def test_revoke_nets_approval_back_to_zero(self, api, any_headers):
        """PRD §3.4: "The conservation invariant follows directly: an
        approval's increment paired with its own withdrawal or revocation
        nets to zero on both the count and the fee total."

        Design: Difficulty/compensating_invariant/compensating_oba_approve_revoke_count
        """
        _branch, rep = make_branch_with_rep(region="N", crd_number="700001")
        activity = make_activity(rep, activity_type=OBA, description="board")
        validate_success(
            api.decide_outside_activity(activity["id"], decide_payload("APPROVE"),
                                        PRINCIPAL_A),
            200,
        )
        assert get_rep(rep["id"])["active_approved_activity_count"] == 1

        revoked = validate_success(
            api.revoke_outside_activity(activity["id"], {"reason": "policy change"},
                                        PRINCIPAL_A),
            200,
        )
        assert revoked["status"] == "REVOKED"
        assert get_rep(rep["id"])["active_approved_activity_count"] == 0


# ─── validation priority: state before safety ─────────

class TestStateBeforeSafetyOnDecide:
    def test_decide_on_suspended_activity_reports_state_error(self, api,
                                                              any_headers):
        """PRD §2.10: "The target resource must be in a state from which the
        requested transition exists" (state preconditions) and the
        supervisory gates "are evaluated next". Deciding a request the
        §3.6 cascade moved to SUSPENDED_REVIEW violates both the state rule
        and the heightened-plan gate; the state rule surfaces:
        "the activity must be in `SUBMITTED` — deciding in any other state is
        rejected with `ERR_ACTIVITY_NOT_PENDING_DECISION`".

        Design: Difficulty/priority_pair_validation_conflict/priority_state_before_safety_oba
        """
        _branch, rep, activity = make_suspended_oba(
            crd_number="300001", event_type="FELONY_CONVICTION",
            activity_overrides={"activity_type": OBA,
                                "description": "board seat",
                                "compensation_expected": True},
        )
        res = api.decide_outside_activity(activity["id"], decide_payload("APPROVE"),
                                          PRINCIPAL_A)
        validate_error(res, ApiErrorId.ERR_ACTIVITY_NOT_PENDING_DECISION)

    def test_rejected_decide_leaves_suspension_untouched(self, api, any_headers):
        """PRD §3.4: "the activity must be in `SUBMITTED` — deciding in any
        other state is rejected with `ERR_ACTIVITY_NOT_PENDING_DECISION`".
        A rejected decision mutates nothing: the request stays in
        SUSPENDED_REVIEW per the §3.6 fan-out ("every request in `SUBMITTED`
        moves to `SUSPENDED_REVIEW`").

        Design: Difficulty/priority_pair_validation_conflict/priority_state_before_safety_oba
        """
        _branch, rep, activity = make_suspended_oba(
            crd_number="300001", event_type="FELONY_CONVICTION",
            activity_overrides={"activity_type": OBA,
                                "description": "board seat",
                                "compensation_expected": True},
        )
        res = api.decide_outside_activity(activity["id"], decide_payload("APPROVE"),
                                          PRINCIPAL_A)
        validate_error(res, ApiErrorId.ERR_ACTIVITY_NOT_PENDING_DECISION)

        after = validate_success(
            api.get_outside_activity(activity["id"], ANY), 200
        )
        assert after["status"] == "SUSPENDED_REVIEW"


# ─── simple state guards ──────────────────────────────

def test_decide_on_approved_activity_rejected(api, any_headers):
    """PRD §3.4: "the activity must be in `SUBMITTED` — deciding in any other
    state is rejected with `ERR_ACTIVITY_NOT_PENDING_DECISION`".

    Design: Corner/state_machines/decide_on_approved_activity_rejected
    """
    _branch, rep = make_branch_with_rep(region="W", crd_number="910003")
    activity = make_activity(rep, activity_type=OBA, description="x")
    approved = validate_success(
        api.decide_outside_activity(activity["id"], decide_payload("APPROVE"),
                                    PRINCIPAL_A),
        200,
    )
    assert approved["status"] == "APPROVED"

    res = api.decide_outside_activity(activity["id"], decide_payload("REJECT"),
                                      PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_ACTIVITY_NOT_PENDING_DECISION)
    after = validate_success(api.get_outside_activity(activity["id"], ANY), 200)
    assert after["status"] == "APPROVED"


def test_create_for_terminated_rep_rejected(api, any_headers):
    """PRD §3.4: "Submission requires the representative to be `ACTIVE`; a
    request by or for a `TERMINATED` representative is rejected with
    `ERR_REP_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/oba_create_for_terminated_rep_rejected
    """
    _branch, rep = make_branch_with_rep(region="S", crd_number="910004")
    terminated = validate_success(
        api.terminate_representative(rep["id"], PRINCIPAL_A), 200
    )
    assert terminated["status"] == "TERMINATED"

    res = api.create_outside_activity(
        create_activity_payload(activity_type=OBA, description="late"),
        make_registered_rep_headers(rep["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REP_NOT_ACTIVE)


def test_compensated_pst_without_comp_details_rejected(api, any_headers):
    """PRD §3.4: "if the request is a compensated private securities
    transaction — `activity_type` of `PRIVATE_SECURITIES_TRANSACTION` with
    `compensation_expected` true — then `estimated_gross_comp_cents` must be
    present and greater than zero, else `ERR_PST_COMP_DETAILS_REQUIRED`
    (HTTP 422)." The rule is conditional: an uncompensated OBA approves
    without the estimate.

    Design: Corner/validations/pst_approve_without_comp_details_rejected
    """
    _branch, rep = make_branch_with_rep(region="W", crd_number="930006")
    pst = make_activity(rep, activity_type=PST, description="pst",
                        compensation_expected=True)
    oba = make_activity(rep, activity_type=OBA, description="oba",
                        compensation_expected=False)

    res = api.decide_outside_activity(pst["id"], decide_payload("APPROVE"),
                                      PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_PST_COMP_DETAILS_REQUIRED)

    approved = validate_success(
        api.decide_outside_activity(oba["id"], decide_payload("APPROVE"),
                                    PRINCIPAL_A),
        200,
    )
    assert approved["status"] == "APPROVED"
