"""Capital improvements: cost-share validation, completion side effects
(tile drainage), early-termination reimbursement in both variants, the
DUE -> PAID payout, and the approval gate on the linked lease's state."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_improvement,
    assert_iso_instant_equal,
    create_improvement_payload,
    create_notice_payload,
    get_field,
    get_improvement,
    get_lease,
    make_landlord_headers,
    serve_notice,
    setup_active_lease,
    setup_field,
    setup_landlord,
    setup_terminated_lease_with_improvements,
    set_clock,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


class TestImprovementCreation:
    def test_improvement_cost_share_invalid_rejected(self, api):
        """PRD §3.8: "The economics are the positive `total_cost_cents`, a `landlord_share_pct` and a `tenant_share_pct` each between 0 and 1 that must sum to exactly 1.0 — any other split is rejected with `ERR_COST_SHARE_INVALID`"

        Design: Corner/validations/improvement_cost_share_invalid_rejected
        """
        landlord = setup_landlord(name="L CS", contact_email="lcs@x.com")
        field = setup_field(landlord["id"], name="FCS")
        resp = api.create_improvement(
            create_improvement_payload(
                field["id"], landlord_share_pct=0.5, tenant_share_pct=0.4
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_COST_SHARE_INVALID)

    def test_tile_drainage_completion_updates_field_drainage(self, api):
        """PRD §3.8: "The tenant's contribution, `tenant_paid_cents`, is computed at creation as the total cost multiplied by the tenant share, rounded half up to whole cents."
        PRD §3.8: "A manager then marks an approved project completed, moving it to the terminal `COMPLETED` state and stamping `completed_at` from the clock — the amortization epoch — and when the project is a `TILE_DRAINAGE`, completion also sets the field's `drainage_status` to `TILED`."

        Design: Corner/state_machines/tile_drainage_completion_updates_field_drainage
        """
        landlord = setup_landlord(name="L TD", contact_email="ltd@x.com")
        field = setup_field(landlord["id"], name="FTD", drainage_status="POOR")
        improvement = validate_success(
            api.create_improvement(
                create_improvement_payload(
                    field["id"],
                    project_type="TILE_DRAINAGE",
                    total_cost_cents=4000000,
                    landlord_share_pct=0.7,
                    tenant_share_pct=0.3,
                    amortization_years=10,
                ),
                MGR,
            ),
            201,
        )
        assert_improvement(improvement)
        assert improvement["tenant_paid_cents"] == 1200000, (
            "round_half_up(4000000 * 0.3)"
        )
        assert improvement["status"] == "PROPOSED"
        assert improvement["reimbursement_status"] == "NONE"

        validate_success(
            api.approve_improvement(
                improvement["id"], make_landlord_headers(landlord["id"])
            )
        )
        set_clock("2027-05-01T00:00:00Z")
        completed = validate_success(api.complete_improvement(improvement["id"], MGR))
        assert completed["status"] == "COMPLETED"
        assert_iso_instant_equal(completed["completed_at"], "2027-05-01T00:00:00Z")
        assert get_field(field["id"])["drainage_status"] == "TILED"


class TestApprovalGateOnLinkedLease:
    def test_improvement_approval_blocked_by_termination_pending_lease(self, api):
        """PRD §3.8: "Owner consent is required for capital works, so approval belongs to the landlord: the caller must own the field — the field's `landlord_id` must equal `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER` — and when the proposal links a `lease_id`, that lease must be `ACTIVE`, else `ERR_IMPROVEMENT_LEASE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/improvement_approval_blocked_by_termination_pending_lease
        """
        ctx = setup_active_lease("CASH")
        improvement = validate_success(
            api.create_improvement(
                create_improvement_payload(
                    ctx["field"]["id"],
                    lease_id=ctx["lease"]["id"],
                    project_type="TILE_DRAINAGE",
                    total_cost_cents=3000000,
                    landlord_share_pct=0.6,
                    tenant_share_pct=0.4,
                    amortization_years=8,
                ),
                MGR,
            ),
            201,
        )
        serve_notice(ctx, "LANDLORD")
        assert get_lease(ctx["lease"]["id"])["status"] == "TERMINATION_PENDING"

        resp = api.approve_improvement(
            improvement["id"], make_landlord_headers(ctx["landlord"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_IMPROVEMENT_LEASE_NOT_ACTIVE)
        assert get_improvement(improvement["id"])["status"] == "PROPOSED"

    def test_improvement_approval_passes_once_lease_active_again(self, api):
        """PRD §3.8: "when the proposal links a `lease_id`, that lease must be `ACTIVE`, else `ERR_IMPROVEMENT_LEASE_NOT_ACTIVE`"
        PRD §3.9: "Withdrawal moves the notice to the terminal `WITHDRAWN` state and returns the lease from `TERMINATION_PENDING` to `ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/improvement_approval_blocked_by_termination_pending_lease
        """
        ctx = setup_active_lease("CASH")
        improvement = validate_success(
            api.create_improvement(
                create_improvement_payload(
                    ctx["field"]["id"],
                    lease_id=ctx["lease"]["id"],
                    project_type="TILE_DRAINAGE",
                    total_cost_cents=3000000,
                    landlord_share_pct=0.6,
                    tenant_share_pct=0.4,
                    amortization_years=8,
                ),
                MGR,
            ),
            201,
        )
        notice = serve_notice(ctx, "LANDLORD")
        blocked = api.approve_improvement(
            improvement["id"], make_landlord_headers(ctx["landlord"]["id"])
        )
        validate_error(blocked, ApiErrorId.ERR_IMPROVEMENT_LEASE_NOT_ACTIVE)

        validate_success(
            api.withdraw_notice(
                notice["id"], make_landlord_headers(ctx["landlord"]["id"])
            )
        )
        assert get_lease(ctx["lease"]["id"])["status"] == "ACTIVE"
        approved = validate_success(
            api.approve_improvement(
                improvement["id"], make_landlord_headers(ctx["landlord"]["id"])
            )
        )
        assert approved["status"] == "APPROVED"


class TestEarlyTerminationReimbursement:
    def test_straight_line_reimbursement_amount_and_due_status(self, api):
        """PRD §3.8: "Under `STRAIGHT_LINE`, the amortization horizon is the `amortization_years` multiplied by 365 — fixed 365-day years, with no leap handling — the remaining days are the horizon minus the elapsed days, floored at zero, and the reimbursement is the `tenant_paid_cents` multiplied by the ratio of remaining days to total days, rounded half up to whole cents."
        PRD §3.9: "every completed improvement linked to the lease whose `reimbursement_status` is `NONE` computes its `reimbursement_due_cents` per §3.8 and flips to `DUE`"

        Design: Difficulty/dual_variant_calc/improvement_reimbursement_straight_line_vs_agreed_value
        """
        ctx = setup_terminated_lease_with_improvements()
        straight_line, _ = ctx["improvements"]
        # completed_at 2027-03-01, effective 2028-03-01: elapsed 366 days of
        # 1825; round_half_up(1000000 * 1459 / 1825) = 799452.
        assert straight_line["tenant_paid_cents"] == 1000000
        assert straight_line["reimbursement_due_cents"] == 799452
        assert straight_line["reimbursement_status"] == "DUE"
        assert ctx["lease"]["status"] == "TERMINATED"

    def test_agreed_value_reimbursement_amount_differs(self, api):
        """PRD §3.8: "Under `AGREED_VALUE`, a contractual residual schedule applies by elapsed-year bucket — the elapsed days divided by 365 and rounded down: bucket zero returns 100 percent, bucket one 75 percent, bucket two 55 percent, bucket three 35 percent, bucket four 15 percent, and bucket five or beyond 0 percent — and the reimbursement is the `tenant_paid_cents` multiplied by that residual percentage, rounded half up."
        PRD §3.8: "Whatever the computed amount — even zero — the project's `reimbursement_status` flips from `NONE` to `DUE`."

        Design: Difficulty/dual_variant_calc/improvement_reimbursement_straight_line_vs_agreed_value
        """
        ctx = setup_terminated_lease_with_improvements()
        straight_line, agreed_value = ctx["improvements"]
        # elapsed 366 days -> bucket floor(366/365) = 1 -> 75% of 1000000.
        assert agreed_value["reimbursement_due_cents"] == 750000
        assert agreed_value["reimbursement_status"] == "DUE"
        assert straight_line["reimbursement_due_cents"] == 799452
        assert (
            straight_line["reimbursement_due_cents"]
            != agreed_value["reimbursement_due_cents"]
        ), "two valid methods, different cents for identical inputs"

    def test_improvement_reimbursement_marked_paid(self, api):
        """PRD §3.8: "Whatever the computed amount — even zero — the project's `reimbursement_status` flips from `NONE` to `DUE`. A manager later marks the payout, moving `reimbursement_status` from `DUE` to `PAID`."
        PRD §3.8: "its `reimbursement_status` starts at `NONE` — a second state dimension that evolves independently of the lifecycle status once the project is completed."

        Design: Corner/state_machines/improvement_reimbursement_marked_paid
        """
        ctx = setup_terminated_lease_with_improvements(
            methods=("STRAIGHT_LINE",), project_types=("IRRIGATION",)
        )
        improvement = ctx["improvements"][0]
        assert improvement["reimbursement_status"] == "DUE"
        assert improvement["reimbursement_due_cents"] == 799452

        paid = validate_success(api.mark_reimbursed(improvement["id"], MGR))
        assert paid["reimbursement_status"] == "PAID"
        assert paid["status"] == "COMPLETED", (
            "the lifecycle status dimension stays COMPLETED"
        )
