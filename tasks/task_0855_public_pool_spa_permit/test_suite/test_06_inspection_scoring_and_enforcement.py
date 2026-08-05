"""Finalization scoring, the enforcement axis and the demerit-point invariant."""

from test_helpers import (
    ADMIN,
    INSPECTOR,
    ApiErrorId,
    assert_posture,
    correct_violation,
    escalate_enforcement,
    fee_balance,
    issue_enforcement_notice,
    list_all_violations,
    read_facility,
    read_inspection,
    read_permit,
    read_violation,
    schedule_inspection,
    setup_facility_with_issued_permit,
    setup_finalized_inspection,
    setup_operator_and_pool,
    validate_error,
    validate_paginated,
    validate_success,
    verify_violation,
    void_inspection,
)

CRITICAL_UNCORRECTED = {
    "code": "WQ-101",
    "severity": "CRITICAL",
    "description": "Free chlorine below minimum",
    "corrected_on_site": False,
}
NONCRITICAL_CORRECTED = {
    "code": "SN-201",
    "severity": "NONCRITICAL",
    "description": "Deck hose left uncoiled",
    "corrected_on_site": True,
}


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def test_an_inspection_with_no_findings_scores_one_hundred_and_passes(api):
    """PRD 3.5: The `score` is 100 less both capped subtotals, floored at zero so
    it never goes negative.
    PRD 3.5: When the result is `CONDITIONAL` or `FAIL`, `reinspection_due_on` is
    set to the date 10 days after the date part of `finalized_at`; when the
    result is `PASS` it stays null.
    PRD 3.5: **Hop two:** when the result is `FAIL`, the enforcement axis moves
    `NONE → NOTICE_ISSUED` automatically, and a ledger entry of `entry_type`
    `REINSPECTION_FEE` for a positive 15000 cents with a null `permit_id` is
    posted against the owning operator, refreshing `fee_balance_cents`.

    Design: Corner/calculations/inspection_with_no_findings_scores_one_hundred_and_passes
    """
    ctx = setup_operator_and_pool()

    finalized, _ = setup_finalized_inspection(ctx["facility_id"], findings=[])

    assert finalized["critical_demerits"] == 0
    assert finalized["noncritical_demerits"] == 0
    assert finalized["score"] == 100
    assert finalized["result"] == "PASS"
    assert finalized["reinspection_due_on"] is None
    assert finalized["enforcement_status"] == "NONE"
    assert read_facility(ctx["facility_id"])["open_demerit_points"] == 0
    assert fee_balance(ctx["operator_id"]) == 0


def test_corrected_on_site_credit_is_rounded_half_up_per_finding(api):
    """PRD 3.6: When `corrected_on_site` is true **and** the severity is anything
    other than `IMMINENT_HEALTH_HAZARD`, the base weight is halved and rounded
    half up — so a critical finding fixed on the spot is worth 5 points and a
    noncritical one 2 points.
    PRD 3.5: Otherwise, if the score is below 85, or the inspection carries at
    least one finding with `severity` of `CRITICAL` whose `corrected_on_site` is
    false, the result is `CONDITIONAL`. Otherwise the result is `PASS`.

    Design: Corner/calculations/corrected_on_site_credit_rounds_half_up_per_violation
    """
    ctx = setup_operator_and_pool()

    finalized, violations = setup_finalized_inspection(
        ctx["facility_id"],
        findings=[
            {
                "code": "WQ-101",
                "severity": "CRITICAL",
                "description": "Chlorine feeder restarted during the visit",
                "corrected_on_site": True,
            },
            {
                "code": "SN-201",
                "severity": "NONCRITICAL",
                "description": "Hose coiled during the visit",
                "corrected_on_site": True,
            },
        ],
    )

    assert violations[0]["points_assessed"] == 5
    assert violations[1]["points_assessed"] == 2
    assert finalized["critical_demerits"] == 5
    assert finalized["noncritical_demerits"] == 2
    assert finalized["score"] == 93
    assert finalized["result"] == "PASS"
    assert read_facility(ctx["facility_id"])["open_demerit_points"] == 7


def test_an_imminent_hazard_never_receives_the_corrected_on_site_credit(api):
    """PRD 3.6: An imminent hazard is never discounted: it is worth its full 25
    points even if the inspector watched it being corrected.
    PRD 3.5: If the inspection carries any finding at all with `severity` of
    `IMMINENT_HEALTH_HAZARD`, or the score is below 70, the result is `FAIL`.
    PRD 3.5: When the result is `CONDITIONAL` or `FAIL`, `reinspection_due_on` is
    set to the date 10 days after the date part of `finalized_at`; when the
    result is `PASS` it stays null.

    Design: Corner/calculations/imminent_finding_never_receives_the_corrected_on_site_credit
    """
    ctx = setup_operator_and_pool()

    finalized, violations = setup_finalized_inspection(
        ctx["facility_id"],
        findings=[
            {
                "code": "SF-900",
                "severity": "IMMINENT_HEALTH_HAZARD",
                "description": "Drain cover replaced during the visit",
                "corrected_on_site": True,
            }
        ],
    )

    assert violations[0]["points_assessed"] == 25
    assert finalized["score"] == 75
    assert finalized["result"] == "FAIL"
    assert finalized["enforcement_status"] == "NOTICE_ISSUED"
    assert finalized["reinspection_due_on"] == "2026-05-11"
    assert fee_balance(ctx["operator_id"]) == 15000


# --------------------------------------------------------------------------
# Violation lifecycle
# --------------------------------------------------------------------------


def test_verified_outcome_closes_the_finding_and_leaves_the_total_alone(api):
    """PRD 3.6: An `outcome` of `VERIFIED` advances `CORRECTED → VERIFIED`,
    stamps `verified_at`, and leaves `open_demerit_points` untouched, since the
    row had already left the open sum.
    PRD 2.6: **Violation state precondition**: correction requires `OPEN` status
    and a `FINALIZED` parent inspection, verification requires `CORRECTED` →
    `ERR_INVALID_VIOLATION_STATE` (409), on `POST /violations/{id}/correct` and
    `POST /violations/{id}/verify`.

    Design: Corner/state_machines/violation_verification_accepted_closes_the_finding
    """
    ctx = setup_operator_and_pool()
    finalized, violations = setup_finalized_inspection(
        ctx["facility_id"], findings=[CRITICAL_UNCORRECTED]
    )
    finding_id = violations[0]["id"]
    correct_violation(finding_id, ctx["op_headers"], "Chlorinator rebuilt")

    verified = validate_success(
        api.verify_violation(finding_id, {"outcome": "VERIFIED"}, INSPECTOR)
    )

    assert verified["status"] == "VERIFIED"
    assert verified["verified_at"] == "2026-05-01T00:00:00.000Z"
    assert verified["rejection_count"] == 0
    assert read_facility(ctx["facility_id"])["open_demerit_points"] == 0

    validate_error(
        api.verify_violation(finding_id, {"outcome": "VERIFIED"}, INSPECTOR),
        ApiErrorId.ERR_INVALID_VIOLATION_STATE.value, 409,
    )


def test_voiding_a_finalized_inspection_reverses_its_demerit_contribution(api):
    """PRD 3.5: Voiding a *finalized* inspection additionally compensates:
    `score`, `result`, `critical_demerits`, `noncritical_demerits` and
    `reinspection_due_on` are left exactly as they were computed, preserving the
    record of what was scored, but because the inspection is no longer
    `FINALIZED` its findings drop out of the facility's `open_demerit_points`
    sum, restoring the exact pre-finalization value and bumping the facility's
    `version`.
    PRD 3.5: all four edges behave the same way: `voided_at` is stamped from the
    logical clock and every child violation of the inspection moves to `VOIDED`.

    Design: Corner/state_machines/inspection_void_after_finalize_reverses_demerit_points
    """
    ctx = setup_operator_and_pool()
    finalized, violations = setup_finalized_inspection(
        ctx["facility_id"],
        findings=[
            CRITICAL_UNCORRECTED,
            {
                "code": "SN-201",
                "severity": "NONCRITICAL",
                "description": "Deck hose left uncoiled",
                "corrected_on_site": False,
            },
        ],
    )
    assert read_facility(ctx["facility_id"])["open_demerit_points"] == 13
    assert finalized["score"] == 87
    assert finalized["result"] == "CONDITIONAL"

    voided = void_inspection(finalized["id"])

    assert voided["workflow_status"] == "VOIDED"
    assert voided["voided_at"] == "2026-05-01T00:00:00.000Z"
    assert voided["score"] == 87, "The record of what was scored is preserved"

    rows = list_all_violations(finalized["id"], ADMIN)
    assert {row["id"] for row in rows} == {v["id"] for v in violations}
    assert all(row["status"] == "VOIDED" for row in rows)
    assert read_facility(ctx["facility_id"])["open_demerit_points"] == 0


# --------------------------------------------------------------------------
# Enforcement axis guards
# --------------------------------------------------------------------------


def test_issuing_a_notice_before_finalization_is_rejected(api):
    """PRD 3.6: The **enforcement axis** is driven separately, by a
    `HealthAuthorityAdmin`, and every one of its edges is guarded on the workflow
    axis having reached `FINALIZED`.
    PRD 2.6: **Enforcement state precondition**: the action is declared for the
    current `enforcement_status`, `workflow_status` is `FINALIZED`, `result` is
    `CONDITIONAL` or `FAIL` for a notice, and no violation of the inspection is
    still `OPEN` for a clear → `ERR_INVALID_ENFORCEMENT_STATE` (409), on
    `POST /inspections/{id}/enforcement`.

    Design: Corner/state_machines/enforcement_notice_before_finalize_rejected
    """
    ctx = setup_operator_and_pool()
    inspection = schedule_inspection(ctx["facility_id"], INSPECTOR)

    validate_error(
        api.enforce_inspection(inspection["id"], {"action": "ISSUE_NOTICE"}, ADMIN),
        ApiErrorId.ERR_INVALID_ENFORCEMENT_STATE.value, 409,
    )

    unchanged = read_inspection(inspection["id"])
    assert unchanged["enforcement_status"] == "NONE"
    assert unchanged["workflow_status"] == "SCHEDULED"


def test_clearing_is_blocked_while_a_finding_is_still_open(api):
    """PRD 3.6: **Clearing** moves either `NOTICE_ISSUED → CLEARED` or
    `ESCALATED → CLEARED`, with identical behaviour on both edges and no side
    effects. It requires that no violation of this inspection is still `OPEN`;
    otherwise `ERR_INVALID_ENFORCEMENT_STATE`.

    Design: Corner/state_machines/enforcement_clear_blocked_while_a_violation_stays_open
    """
    ctx = setup_operator_and_pool()
    finalized, violations = setup_finalized_inspection(
        ctx["facility_id"], findings=[CRITICAL_UNCORRECTED]
    )
    issue_enforcement_notice(finalized["id"])

    validate_error(
        api.enforce_inspection(finalized["id"], {"action": "CLEAR"}, ADMIN),
        ApiErrorId.ERR_INVALID_ENFORCEMENT_STATE.value, 409,
    )

    correct_violation(violations[0]["id"], ctx["op_headers"], "Chlorinator rebuilt")
    verified = verify_violation(violations[0]["id"], "VERIFIED", INSPECTOR)
    assert verified["status"] == "VERIFIED"

    cleared = validate_success(
        api.enforce_inspection(finalized["id"], {"action": "CLEAR"}, ADMIN)
    )
    assert cleared["enforcement_status"] == "CLEARED"
    assert cleared["workflow_status"] == "FINALIZED"
    assert read_facility(ctx["facility_id"])["open_demerit_points"] == 0


# --------------------------------------------------------------------------
# Nested caps, the corrected-on-site credit and the conditional result branches
# --------------------------------------------------------------------------

FIVE_CRITICALS_AND_TWO_CORRECTED_MINORS = [
    {"code": "WQ-101", "severity": "CRITICAL",
     "description": "Free chlorine below minimum", "corrected_on_site": False},
    {"code": "WQ-102", "severity": "CRITICAL",
     "description": "pH out of range", "corrected_on_site": False},
    {"code": "WQ-103", "severity": "CRITICAL",
     "description": "Combined chloramine above limit", "corrected_on_site": False},
    {"code": "SF-104", "severity": "CRITICAL",
     "description": "Rescue equipment missing", "corrected_on_site": False},
    {"code": "SF-105", "severity": "CRITICAL",
     "description": "Emergency phone inoperative", "corrected_on_site": False},
    {"code": "SN-201", "severity": "NONCRITICAL",
     "description": "Deck hose left uncoiled", "corrected_on_site": True},
    {"code": "SN-202", "severity": "NONCRITICAL",
     "description": "Log book entry missing", "corrected_on_site": True},
]


class TestScoreCapsAndResultBranches:
    """Two independent caps, a half-up credit and a floored score interact."""

    def test_critical_subtotal_is_capped_at_forty_before_the_score_is_taken(
        self, api
    ):
        """PRD 3.5: Each subtotal is then capped: `critical_demerits` is the
        smaller of the critical subtotal and 40, and `noncritical_demerits` is
        the smaller of the noncritical subtotal and 20. The `score` is 100 less
        both capped subtotals, floored at zero so it never goes negative.
        PRD 3.5: If the inspection carries any finding at all with `severity` of
        `IMMINENT_HEALTH_HAZARD`, or the score is below 70, the result is `FAIL`.
        PRD 3.6: When `corrected_on_site` is true **and** the severity is
        anything other than `IMMINENT_HEALTH_HAZARD`, the base weight is halved
        and rounded half up — so a critical finding fixed on the spot is worth 5
        points and a noncritical one 2 points.

        Design: Difficulty/combinatorial_formula/inspection_score_nested_caps_and_conditional_result
        """
        ctx = setup_operator_and_pool()

        finalized, _ = setup_finalized_inspection(
            ctx["facility_id"], findings=FIVE_CRITICALS_AND_TWO_CORRECTED_MINORS
        )

        assert finalized["critical_demerits"] == 40, "raw 50 capped at 40"
        assert finalized["noncritical_demerits"] == 4, "two corrected minors at 2 each"
        assert finalized["score"] == 56
        assert finalized["result"] == "FAIL"
        assert finalized["reinspection_due_on"] == "2026-05-11"

    def test_facility_demerit_total_uses_the_uncapped_points(self, api):
        """PRD 2.10: A facility's `open_demerit_points` is the sum of
        `points_assessed` over every violation whose own status is `OPEN` and
        whose parent inspection belongs to that facility and is currently in
        `FINALIZED`.
        PRD 3.5: **Hop two:** when the result is `FAIL`, the enforcement axis
        moves `NONE → NOTICE_ISSUED` automatically, and a ledger entry of
        `entry_type` `REINSPECTION_FEE` for a positive 15000 cents with a null
        `permit_id` is posted against the owning operator, refreshing
        `fee_balance_cents`.

        Design: Difficulty/combinatorial_formula/inspection_score_nested_caps_and_conditional_result
        """
        ctx = setup_operator_and_pool()

        finalized, _ = setup_finalized_inspection(
            ctx["facility_id"], findings=FIVE_CRITICALS_AND_TWO_CORRECTED_MINORS
        )

        assert finalized["enforcement_status"] == "NOTICE_ISSUED"
        assert read_facility(ctx["facility_id"])["open_demerit_points"] == 54, (
            "The facility total sums the uncapped points, unlike the capped score"
        )
        assert fee_balance(ctx["operator_id"]) == 15000


# --------------------------------------------------------------------------
# The two inspection state axes move independently
# --------------------------------------------------------------------------


class TestParallelWorkflowAndEnforcementAxes:
    """Enforcement advances twice while the workflow axis stays at FINALIZED."""

    @staticmethod
    def _setup():
        ctx = setup_operator_and_pool()
        finalized, violations = setup_finalized_inspection(
            ctx["facility_id"],
            findings=[
                {
                    "code": "WQ-110",
                    "severity": "CRITICAL",
                    "description": "Chlorinator offline at time of visit",
                    "corrected_on_site": False,
                }
            ],
        )
        ctx["inspection"] = finalized
        ctx["violations"] = violations
        return ctx

    def test_issuing_a_notice_leaves_the_workflow_axis_and_the_score_alone(
        self, api
    ):
        """PRD 3.5: Neither axis constrains the other's storage: an inspection
        can sit at `FINALIZED` on the workflow axis and `NONE` on the enforcement
        axis indefinitely.
        PRD 3.6: **Issuing a notice** moves `NONE → NOTICE_ISSUED` and
        additionally requires the inspection's `result` to be `CONDITIONAL` or
        `FAIL`; a notice on a passing inspection is
        `ERR_INVALID_ENFORCEMENT_STATE`.

        Design: Difficulty/non_linear_state_machine/inspection_workflow_and_enforcement_axes_advance_independently
        """
        ctx = self._setup()
        assert ctx["inspection"]["score"] == 90
        assert ctx["inspection"]["result"] == "CONDITIONAL"
        assert ctx["inspection"]["enforcement_status"] == "NONE"

        noticed = validate_success(
            api.enforce_inspection(
                ctx["inspection"]["id"],
                {"action": "ISSUE_NOTICE", "note": "Written notice served on site"},
                ADMIN,
            )
        )

        assert noticed["enforcement_status"] == "NOTICE_ISSUED"
        assert noticed["workflow_status"] == "FINALIZED"
        assert noticed["score"] == 90
        assert noticed["result"] == "CONDITIONAL"

    def test_escalation_opens_a_permit_action_closure_and_closes_the_venue(
        self, api
    ):
        """PRD 3.6: **Escalating** moves `NOTICE_ISSUED → ESCALATED` and requires
        that at least one violation of this inspection still has status `OPEN`.
        It creates a closure order for the facility in `OPEN` with
        `closure_reason` of `PERMIT_ACTION` and `ordered_by_role` of
        `HealthAuthorityAdmin`, which drives the facility's `operating_posture`
        to `CLOSED` with `posture_reason` of `CLOSURE_ORDER_OPEN` and bumps its
        `version`.
        PRD 2.9: The facility has at least one closure order whose status is
        `OPEN` or `REOPEN_REQUESTED` → `CLOSED` with reason `CLOSURE_ORDER_OPEN`.

        Design: Difficulty/non_linear_state_machine/inspection_workflow_and_enforcement_axes_advance_independently
        """
        ctx = self._setup()
        issue_enforcement_notice(ctx["inspection"]["id"], ADMIN)

        escalated = validate_success(
            api.enforce_inspection(
                ctx["inspection"]["id"], {"action": "ESCALATE"}, ADMIN
            )
        )

        assert escalated["enforcement_status"] == "ESCALATED"
        assert escalated["workflow_status"] == "FINALIZED"
        assert escalated["score"] == 90
        assert escalated["result"] == "CONDITIONAL"

        orders, orders_meta = validate_paginated(
            api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
        )
        assert orders_meta["total_count"] == 1
        assert orders[0]["closure_reason"] == "PERMIT_ACTION"
        assert orders[0]["status"] == "OPEN"

        facility = read_facility(ctx["facility_id"])
        assert_posture(facility, "CLOSED", "CLOSURE_ORDER_OPEN")
        assert facility["open_demerit_points"] == 10


# --------------------------------------------------------------------------
# Demerit points are conserved across correction and rejection
# --------------------------------------------------------------------------


class TestDemeritPointConservation:
    """A rejected verification restores exactly what the correction removed."""

    @staticmethod
    def _setup():
        ctx = setup_operator_and_pool()
        finalized, violations = setup_finalized_inspection(
            ctx["facility_id"],
            findings=[CRITICAL_UNCORRECTED, NONCRITICAL_CORRECTED],
        )
        ctx["inspection"] = finalized
        ctx["critical_violation"] = violations[0]
        ctx["minor_violation"] = violations[1]
        return ctx

    def test_rejected_verification_restores_the_pre_correction_total(self, api):
        """PRD 3.6: An `outcome` of `REJECTED` sends the row back
        `CORRECTED → OPEN`, increments `rejection_count` by 1, leaves
        `corrected_at` at its previous value rather than clearing it, and
        compensates the facility total: exactly this row's `points_assessed`
        re-enters `open_demerit_points`, restoring the value it held before the
        correction, and the facility's `version` climbs again.
        PRD 3.6: The correction stamps `corrected_at` from the logical clock, may
        carry an explanatory `correction_note` in the request body, and
        recomputes the facility's `open_demerit_points`, from which this row's
        `points_assessed` now drops out because its status is no longer `OPEN`;
        the facility's `version` climbs by 1.

        Design: Difficulty/compensating_invariant/violation_correction_then_rejection_restores_demerit_points_exactly
        """
        ctx = self._setup()
        assert read_facility(ctx["facility_id"])["open_demerit_points"] == 12

        corrected = correct_violation(
            ctx["critical_violation"]["id"], ctx["op_headers"],
            "Chlorinator repaired and residual restored",
        )
        assert corrected["status"] == "CORRECTED"
        assert read_facility(ctx["facility_id"])["open_demerit_points"] == 2

        rejected = validate_success(
            api.verify_violation(
                ctx["critical_violation"]["id"], {"outcome": "REJECTED"}, INSPECTOR
            )
        )

        assert rejected["status"] == "OPEN"
        assert rejected["rejection_count"] == 1
        assert rejected["verified_at"] is None
        assert rejected["corrected_at"] == "2026-05-01T00:00:00.000Z"
        assert read_facility(ctx["facility_id"])["open_demerit_points"] == 12, (
            "The compensating action restores the bit-for-bit pre-correction value"
        )

    def test_the_frozen_inspection_score_survives_the_correction_cycle(self, api):
        """PRD 3.6: `points_assessed` is computed at row creation and frozen
        forever after.
        PRD 3.5: **Scoring** runs exactly once, at finalization, and writes
        `critical_demerits`, `noncritical_demerits`, `score` and `result`.

        Design: Difficulty/compensating_invariant/violation_correction_then_rejection_restores_demerit_points_exactly
        """
        ctx = self._setup()
        assert ctx["critical_violation"]["points_assessed"] == 10
        assert ctx["minor_violation"]["points_assessed"] == 2
        assert ctx["inspection"]["score"] == 88
        assert ctx["inspection"]["result"] == "CONDITIONAL"

        correct_violation(ctx["critical_violation"]["id"], ctx["op_headers"])
        mid_cycle = read_inspection(ctx["inspection"]["id"])
        assert mid_cycle["score"] == 88
        assert mid_cycle["result"] == "CONDITIONAL"

        verify_violation(ctx["critical_violation"]["id"], "REJECTED", INSPECTOR)
        after_cycle = read_inspection(ctx["inspection"]["id"])
        assert after_cycle["score"] == 88
        assert after_cycle["result"] == "CONDITIONAL"

        reopened = read_violation(
            ctx["inspection"]["id"], ctx["critical_violation"]["id"], ADMIN
        )
        assert reopened["points_assessed"] == 10


# --------------------------------------------------------------------------
# The four-hop finalization cascade
# --------------------------------------------------------------------------


class TestFinalizeFailCascade:
    """FAIL -> notice -> permit suspension -> closed venue, in one request."""

    @staticmethod
    def _setup():
        ctx = setup_facility_with_issued_permit()
        finalized, violations = setup_finalized_inspection(
            ctx["facility_id"],
            findings=[
                {
                    "code": "SF-900",
                    "severity": "IMMINENT_HEALTH_HAZARD",
                    "description": "Main drain cover missing from the deep end",
                    "corrected_on_site": False,
                }
            ],
        )
        ctx["inspection"] = finalized
        ctx["violations"] = violations
        return ctx

    def test_a_failing_imminent_hazard_suspends_the_permit_and_closes_the_venue(
        self, api
    ):
        """PRD 3.5: **Hop three:** that automatic notice, when the inspection
        carries at least one violation with `severity` of
        `IMMINENT_HEALTH_HAZARD` whose own status is `OPEN`, moves the facility's
        `ISSUED` permit to `SUSPENDED` with `suspension_reason` of
        `IMMINENT_HEALTH_HAZARD`.
        PRD 3.5: **Hop four:** that suspension in turn recomputes the facility's
        posture to `CLOSED` with `posture_reason` of `PERMIT_NOT_ACTIVE`, bumping
        the facility's `version` a second time within the same request.

        Design: Difficulty/transitive_cascade/finalize_fail_notice_suspends_permit_and_closes_facility
        """
        ctx = self._setup()

        assert ctx["inspection"]["score"] == 75
        assert ctx["inspection"]["result"] == "FAIL"
        assert ctx["inspection"]["enforcement_status"] == "NOTICE_ISSUED"

        permit = read_permit(ctx["permit_id"])
        assert permit["status"] == "SUSPENDED"
        assert permit["suspension_reason"] == "IMMINENT_HEALTH_HAZARD"
        assert_posture(
            read_facility(ctx["facility_id"]), "CLOSED", "PERMIT_NOT_ACTIVE"
        )

    def test_the_cascade_charges_the_reinspection_fee_and_books_the_demerits(
        self, api
    ):
        """PRD 3.5: **Hop one:** the facility's `open_demerit_points` is
        recomputed and now includes every still-open violation of this
        inspection, because the parent is `FINALIZED` for the first time; the
        facility's `version` climbs by 1.
        PRD 3.5: A single failing inspection with an imminent hazard therefore
        charges a reinspection fee, issues a notice, suspends the permit and
        closes the venue in one atomic operation.

        Design: Difficulty/transitive_cascade/finalize_fail_notice_suspends_permit_and_closes_facility
        """
        ctx = self._setup()

        assert read_facility(ctx["facility_id"])["open_demerit_points"] == 25
        assert fee_balance(ctx["operator_id"]) == 55000

        rows, meta = validate_paginated(
            api.list_fee_ledger_entries(
                ADMIN, params={"operator_id": ctx["operator_id"]}
            )
        )
        assert meta["total_count"] == 2
        assert [(row["entry_type"], row["amount_cents"]) for row in rows] == [
            ("PERMIT_FEE", 40000),
            ("REINSPECTION_FEE", 15000),
        ]
