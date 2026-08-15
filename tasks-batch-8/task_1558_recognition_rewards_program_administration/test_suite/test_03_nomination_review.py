"""Nomination review workflow: self-approval, scope, invalid transitions,
revision cycle, auto-expiry, and approval side effects."""
from test_helpers import (
    ApiErrorId,
    create_employee,
    create_nomination_payload,
    get_success_data,
    make_employee_headers,
    make_manager_headers,
    setup_program_with_budget,
    submit_nomination,
    validate_error,
    validate_paginated,
    validate_success,
)


def _ctx(allocated_points=50000, **program_overrides):
    defaults = {"max_points_per_nomination": 5000}
    defaults.update(program_overrides)
    return setup_program_with_budget(
        program_overrides=defaults, allocated_points=allocated_points,
        num_extra_employees=1,
    )


class TestReviewConductRules:
    def test_self_approval_rejected(self, api, hr_admin_headers):
        """PRD §3.3: "Whatever the role, the approver must not be the
        nominator; self-approval on approval, rejection, or return-for-revision
        is `ERR_SELF_APPROVAL`."

        Design: Corner/validations/self_approval_rejected
        """
        ctx = _ctx()
        manager, employee = ctx["manager"], ctx["employee"]
        nomination = submit_nomination(
            ctx["program"]["id"], employee["id"], manager, 100,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="val-sa-1",
        )
        res = api.approve_nomination(
            nomination["id"], nomination["version"],
            make_manager_headers(manager["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SELF_APPROVAL)
        current = validate_success(
            api.get_nomination(nomination["id"], hr_admin_headers), 200
        )
        assert current["status"] == "PENDING_REVIEW"

    def test_manager_out_of_chain_approval_rejected_but_hr_admin_succeeds(
        self, api, hr_admin_headers
    ):
        """PRD §3.3: "Review decisions belong to a `Manager` or an `HRAdmin`,
        with one asymmetry: a `Manager` approver must sit in the nominee's
        manager chain (`ERR_NOMINEE_NOT_IN_SCOPE` otherwise), while an
        `HRAdmin` is never scope-limited."

        Design: Corner/validations/manager_out_of_chain_approval_rejected
        """
        ctx = _ctx()
        program_id = ctx["program"]["id"]
        mgr_a = ctx["manager"]
        mgr_b = create_employee(ctx["dept"]["id"], employee_ref="MGRB",
                                hire_date="2020-03-01")
        employee = ctx["employee"]  # reports to mgr_a
        nomination = submit_nomination(
            program_id, employee["id"], mgr_a, 100,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="val-scope-1",
        )
        res = api.approve_nomination(
            nomination["id"], nomination["version"],
            make_manager_headers(mgr_b["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOMINEE_NOT_IN_SCOPE)

        approved = validate_success(api.approve_nomination(
            nomination["id"], nomination["version"], hr_admin_headers
        ), 200)
        assert approved["status"] == "APPROVED"


class TestInvalidTransitions:
    def test_approve_rejected_nomination_returns_invalid_state(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §2.8 stage 5: "The target resource's current state permits the
        requested transition — approval only from `PENDING_REVIEW`, shipping
        only from `SUBMITTED`, reconciliation only from `OPEN`, and so on
        (`ERR_INVALID_STATE_TRANSITION`)."
        PRD §3.3: "`APPROVED`, `REJECTED`, `CANCELLED`, and `EXPIRED` are
        terminal".

        Design: Corner/state_machines/approve_rejected_nomination_returns_invalid_state
        """
        ctx = _ctx(allocated_points=10000)
        nominator, nominee = ctx["extras"][0], ctx["employee"]
        nomination = submit_nomination(
            ctx["program"]["id"], nominee["id"], nominator, 100,
            type="PEER", reason_code="TEAMWORK", idempotency_key="sm-inv-1",
        )
        get_success_data(api.reject_nomination(
            nomination["id"], hr_admin_headers, reason="no"
        ))

        res = api.approve_nomination(
            nomination["id"], nomination["version"], hr_admin_headers
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        # No award was created and the reservation stayed released.
        _, meta = validate_paginated(api.list_awards(
            hr_admin_headers, params={"nomination_id": nomination["id"]}
        ))
        assert meta["total_count"] == 0
        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["reserved_points"] == 0


class TestRevisionCycle:
    def test_revision_cycle_third_return_auto_rejects(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.3: "When `revision_count` is already 2, the same action
        auto-rejects instead: the nomination lands in `REJECTED`,
        `revision_count` stays at 2, the budget reservation is released with
        posture recomputed, and the response returns the rejected nomination —
        the third return is an outcome, not an error."

        Design: Difficulty/non_linear_state_machine/nomination_revision_cycle_with_version_bump
        """
        ctx = _ctx()
        mgr, nominee, nominator = ctx["manager"], ctx["employee"], ctx["extras"][0]
        nomination = submit_nomination(
            ctx["program"]["id"], nominee["id"], nominator, 500,
            type="PEER", reason_code="TEAMWORK", idempotency_key="nl1-n1",
        )
        nom_id = nomination["id"]
        mgr_headers = make_manager_headers(mgr["id"])
        nominator_headers = make_employee_headers(nominator["id"])

        returned = validate_success(api.return_nomination_for_revision(
            nom_id, "add detail", mgr_headers
        ), 200)
        assert returned["status"] == "RETURNED_FOR_REVISION"
        assert returned["revision_count"] == 1

        resubmitted = validate_success(api.resubmit_nomination(
            nom_id, {"points_requested": 600, "message": "v2"}, nominator_headers
        ), 200)
        assert resubmitted["status"] == "PENDING_REVIEW"

        returned2 = validate_success(api.return_nomination_for_revision(
            nom_id, "still not enough", mgr_headers
        ), 200)
        assert returned2["status"] == "RETURNED_FOR_REVISION"
        assert returned2["revision_count"] == 2

        resubmitted2 = validate_success(api.resubmit_nomination(
            nom_id, {"message": "v3"}, nominator_headers
        ), 200)
        assert resubmitted2["status"] == "PENDING_REVIEW"

        final = validate_success(api.return_nomination_for_revision(
            nom_id, "final", mgr_headers
        ), 200)
        assert final["status"] == "REJECTED"

        current = validate_success(api.get_nomination(nom_id, hr_admin_headers), 200)
        assert current["revision_count"] == 2
        assert current["version"] == 6

        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["reserved_points"] == 0

    def test_resubmission_points_delta_moves_budget_reservation(
        self, api, finance_admin_headers
    ):
        """PRD §3.3: "on success the budget's `reserved_points` adjusts by the
        difference between the new and old amounts and posture is recomputed.
        Either way the `review_deadline` resets, and the nomination's `version`
        increments — which is exactly what invalidates an approver's previously
        observed `expected_nomination_version`."

        Design: Difficulty/non_linear_state_machine/nomination_revision_cycle_with_version_bump
        """
        ctx = _ctx()
        mgr, nominee, nominator = ctx["manager"], ctx["employee"], ctx["extras"][0]
        nomination = submit_nomination(
            ctx["program"]["id"], nominee["id"], nominator, 500,
            type="PEER", reason_code="TEAMWORK", idempotency_key="nl1b-n1",
        )
        get_success_data(api.return_nomination_for_revision(
            nomination["id"], "more", make_manager_headers(mgr["id"])
        ))
        resubmitted = validate_success(api.resubmit_nomination(
            nomination["id"], {"points_requested": 600, "message": "v2"},
            make_employee_headers(nominator["id"]),
        ), 200)
        assert resubmitted["status"] == "PENDING_REVIEW"
        assert resubmitted["version"] == nomination["version"] + 2

        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        # 500 returned-for-revision keeps the reservation; +100 delta on resubmit.
        assert budget["reserved_points"] == 600


class TestAutoExpiry:
    def test_nomination_auto_expires_past_deadline_and_releases_reservation(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.3: "nominations that outlive their `review_deadline` —
        whether still `PENDING_REVIEW` or sitting `RETURNED_FOR_REVISION` —
        are moved to `EXPIRED` by the first step of the clock-advance sweep,
        releasing the reservation and recomputing posture."

        Design: Corner/state_machines/nomination_auto_expiry_releases_reservation
        """
        ctx = setup_program_with_budget(
            program_overrides={"nomination_review_sla_days": 14},
            allocated_points=10000, num_extra_employees=1,
        )
        nomination = submit_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], ctx["extras"][0], 400,
            type="PEER", reason_code="TEAMWORK", idempotency_key="sm-exp-1",
        )
        # Submitted at 2026-08-01T00:00:00Z with a 14-day SLA -> deadline
        # 2026-08-15T00:00:00Z; advancing past it expires the nomination.
        get_success_data(api.set_clock("2026-08-16T00:00:00Z", hr_admin_headers))

        current = validate_success(
            api.get_nomination(nomination["id"], hr_admin_headers), 200
        )
        assert current["status"] == "EXPIRED"
        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["reserved_points"] == 0


class TestApprovalCascade:
    def test_approve_creates_award_grants_points_and_promotes_tier(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.3: "On success the nomination moves from `PENDING_REVIEW` to
        `APPROVED` and the server, in one logical step: creates an `Award` with
        `source` `NOMINATION`, `points` equal to `points_requested`,
        `employee_id` equal to the nominee, `nomination_id` pointing back at
        the nomination, `granted_at` at the current logical instant,
        `expires_at` twelve months later, and `points_remaining` equal to the
        granted points, then writes the award's id into the nomination's
        `award_id`; writes a `GRANT_NOMINATION` ledger entry crediting the
        nominee; moves the budget's `reserved_points` down and its
        `committed_points` up by `points_requested` and recomputes posture; and
        recomputes the nominee's `available_points`, `lifetime_granted_points`,
        and `recognition_tier`".
        PRD §3.4: "The lower bounds are inclusive, so exactly 1000 lifetime
        points is already `SILVER`."

        Design: Difficulty/transitive_cascade/nomination_approval_tier_promotion_chain
        """
        ctx = _ctx(allocated_points=100000, max_points_per_nomination=10000)
        nomination, award_id = None, None
        nomination = submit_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], ctx["manager"], 1000,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="tc1-n1",
        )
        approved = validate_success(api.approve_nomination(
            nomination["id"], nomination["version"], hr_admin_headers
        ), 200)
        award_id = approved["award_id"]
        assert award_id

        award = validate_success(api.get_award(award_id, hr_admin_headers), 200)
        assert award["points"] == 1000
        assert award["status"] == "ACTIVE"
        assert award["source"] == "NOMINATION"

        entries, meta = validate_paginated(api.list_ledger_entries(
            ctx["employee"]["id"], hr_admin_headers
        ))
        assert meta["total_count"] == 1
        assert entries[0]["entry_type"] == "GRANT_NOMINATION"
        assert entries[0]["points"] == 1000

        employee = validate_success(
            api.get_employee(ctx["employee"]["id"], hr_admin_headers), 200
        )
        assert employee["available_points"] == 1000
        assert employee["lifetime_granted_points"] == 1000
        assert employee["recognition_tier"] == "SILVER"

        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["reserved_points"] == 0
        assert budget["committed_points"] == 1000

    def test_approve_stamps_decision_fields_and_bumps_version(
        self, api, hr_admin_headers
    ):
        """PRD §3.3: "Every decision stamps `decided_at` with the logical
        timestamp and `reviewer_id` with the deciding manager's employee id —
        or the opaque `HRAdmin` identifier when an administrator decides — and
        increments the nomination's `version`."

        Design: Difficulty/transitive_cascade/nomination_approval_tier_promotion_chain
        """
        ctx = _ctx(allocated_points=100000, max_points_per_nomination=10000)
        nomination = submit_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], ctx["manager"], 1000,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="tc1b-n1",
        )
        approved = validate_success(api.approve_nomination(
            nomination["id"], nomination["version"], hr_admin_headers
        ), 200)
        assert approved["status"] == "APPROVED"
        assert approved["version"] == nomination["version"] + 1
        assert approved["reviewer_id"] == "hr-admin-1"
        assert approved["decided_at"]


class TestImmediateConsistency:
    def test_approve_response_and_followup_reads_are_immediately_consistent(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.3: "On success the nomination moves from `PENDING_REVIEW` to
        `APPROVED` and the server, in one logical step: creates an `Award` with
        `source` `NOMINATION`, `points` equal to `points_requested`,
        `employee_id` equal to the nominee, `nomination_id` pointing back at
        the nomination, `granted_at` at the current logical instant,
        `expires_at` twelve months later, and `points_remaining` equal to the
        granted points, then writes the award's id into the nomination's
        `award_id`".
        PRD §3.2: "From these counters the budget derives its `posture`, a
        stored column recomputed after every mutation of `reserved_points`,
        `committed_points`, or `allocated_points`, and on clock advance."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 1000},
            allocated_points=10000,
        )
        nomination = submit_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], ctx["manager"], 250,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="cons-1",
        )
        approved = validate_success(api.approve_nomination(
            nomination["id"], nomination["version"], hr_admin_headers
        ), 200)
        # Same-response visibility.
        assert approved["status"] == "APPROVED"
        assert approved["award_id"]

        # Immediate read-after-write on the budget and the employee.
        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["committed_points"] == 250
        employee = validate_success(
            api.get_employee(ctx["employee"]["id"], hr_admin_headers), 200
        )
        assert employee["available_points"] == 250
