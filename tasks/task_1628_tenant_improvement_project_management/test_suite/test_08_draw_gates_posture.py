"""Draw submission/approval gates, posture cascades, OCC, segregation of duties."""
from test_helpers import (
    ApiErrorId,
    create_approved_change_order,
    create_approved_draw,
    create_change_order_record,
    create_draw_record,
    create_submitted_draw,
    fresh_project_version,
    get_success_data,
    make_contractor_rep_headers,
    make_landlord_approver_headers,
    make_tenant_rep_headers,
    set_logical_clock,
    setup_project_in_construction,
    validate_error,
    validate_success,
)

MID = "2026-08-15T00:00:00Z"


def _construction_with_clock(api):
    sc = setup_project_in_construction()
    set_logical_clock(MID)
    return sc


def _consume_35m(api, project_id, ctr):
    """Approve draws of 10M, 15M, 10M: consumed 35000000, remaining 15000000."""
    create_approved_draw(project_id, ctr, 10_000_000)
    create_approved_draw(project_id, ctr, 15_000_000)
    create_approved_draw(project_id, ctr, 10_000_000)


class TestExhaustionHoldCascade:
    def test_draw_approval_exhaustion_hold_cascade(self, api, landlord_pm_headers):
        """PRD 3.6: "it is `ALLOWANCE_EXHAUSTED` when the pool is funded (a
        total above zero) and consumption has reached or passed it —
        consumption exactly equal to the pool already exhausts it". PRD 3.6:
        "Posture flips are themselves cascades: entering
        `ALLOWANCE_EXHAUSTED` moves every `SUBMITTED` draw of the project to
        `ON_HOLD`, and leaving it back to `OPEN` returns every `ON_HOLD` draw
        to `SUBMITTED`."

        Design: Difficulty/transitive_cascade/draw_approval_exhaustion_hold_cascade
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        _consume_35m(api, sc["project"]["id"], ctr)

        d4 = create_submitted_draw(
            sc["project"]["id"], ctr, 15_000_000, waiver_type="UNCONDITIONAL_FINAL"
        )["draw"]
        d5 = create_submitted_draw(
            sc["project"]["id"], ctr, 3_000_000, waiver_action="none"
        )["draw"]
        assert d5["status"] == "SUBMITTED"

        d4 = validate_success(
            api.approve_draw(
                d4["id"],
                {"approved_amount_cents": 15_000_000},
                make_landlord_approver_headers("approver-1"),
            ),
            200,
        )
        # cum_before 35000000 >= 25000000 -> late 5% tier on the fourth draw.
        assert d4["retainage_held_cents"] == 750_000

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_consumed_cents"] == 50_000_000
        assert project["allowance_remaining_cents"] == 0
        assert project["posture"] == "ALLOWANCE_EXHAUSTED", (
            "consumption exactly equal to the pool exhausts it"
        )
        d5_after = get_success_data(api.get_draw(d5["id"], landlord_pm_headers))
        assert d5_after["status"] == "ON_HOLD", (
            "the posture flip force-holds the still-SUBMITTED sibling draw"
        )

    def test_void_of_approved_draw_releases_held_siblings(self, api, landlord_pm_headers):
        """PRD 3.6: "voiding an `APPROVED` draw is the approver's compensation
        path — the draw's `approved_amount_cents` comes back out of
        `allowance_consumed_cents`, its withholding comes back out of the
        project's `retainage_held_cents`, the remaining allowance is
        recomputed, and the posture re-evaluation may return `ON_HOLD` draws to
        `SUBMITTED`." PRD 3.6: "leaving it back to `OPEN` returns every
        `ON_HOLD` draw to `SUBMITTED`."

        Design: Difficulty/transitive_cascade/draw_approval_exhaustion_hold_cascade
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        _consume_35m(api, sc["project"]["id"], ctr)

        d4 = create_submitted_draw(
            sc["project"]["id"], ctr, 15_000_000, waiver_type="UNCONDITIONAL_FINAL"
        )["draw"]
        d5 = create_submitted_draw(
            sc["project"]["id"], ctr, 3_000_000, waiver_action="none"
        )["draw"]
        d4 = get_success_data(
            api.approve_draw(
                d4["id"],
                {"approved_amount_cents": 15_000_000},
                make_landlord_approver_headers("approver-1"),
            )
        )
        assert get_success_data(api.get_draw(d5["id"], landlord_pm_headers))["status"] == "ON_HOLD"

        voided = get_success_data(
            api.void_draw(d4["id"], make_landlord_approver_headers("approver-1"))
        )
        assert voided["status"] == "VOIDED"

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_consumed_cents"] == 35_000_000
        assert project["allowance_remaining_cents"] == 15_000_000
        assert project["posture"] == "OPEN"
        d5_after = get_success_data(api.get_draw(d5["id"], landlord_pm_headers))
        assert d5_after["status"] == "SUBMITTED", (
            "leaving ALLOWANCE_EXHAUSTED returns the held draw to SUBMITTED"
        )


class TestStateVersusFiscalPriority:
    def test_state_vs_fiscal_on_draw_approve(self, api, landlord_pm_headers):
        """PRD 2.7: "Inbound requests pass through a fixed screening funnel,
        and when several checks could fail at once the earlier stage's error is
        the one returned." PRD 2.7: "6. **Lifecycle guard.** The targeted
        entity must be in a state from which the requested transition exists —
        including the parent-phase gates named throughout §3 — and terminal
        states reject every transition, else `ERR_INVALID_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_draw_approve
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        _consume_35m(api, sc["project"]["id"], ctr)

        # A DRAFT draw whose amount would also exceed the remaining 15000000.
        d4 = create_draw_record(sc["project"]["id"], ctr, 15_000_001)
        assert d4["status"] == "DRAFT"

        resp = api.approve_draw(
            d4["id"],
            {"approved_amount_cents": 15_000_001},
            make_landlord_approver_headers("approver-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_consumed_cents"] == 35_000_000, (
            "the rejected approval must not touch the ledger"
        )

    def test_fiscal_check_fires_when_state_is_valid(self, api, landlord_pm_headers):
        """PRD 3.6: "and it may not exceed the project's
        `allowance_remaining_cents`, else `ERR_DRAW_EXCEEDS_REMAINING` (HTTP
        422) — an approval exactly equal to the remaining allowance is
        permitted."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_draw_approve
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        _consume_35m(api, sc["project"]["id"], ctr)

        # Same over-remaining amount, but the draw is properly SUBMITTED with a
        # verified waiver: the fiscal check is now the one that fires.
        d4 = create_submitted_draw(sc["project"]["id"], ctr, 15_000_001)["draw"]
        resp = api.approve_draw(
            d4["id"],
            {"approved_amount_cents": 15_000_001},
            make_landlord_approver_headers("approver-1"),
        )
        validate_error(resp, ApiErrorId.ERR_DRAW_EXCEEDS_REMAINING)
        after = get_success_data(api.get_draw(d4["id"], landlord_pm_headers))
        assert after["status"] == "SUBMITTED"


class TestTemporalVersusReferentialPriority:
    def test_temporal_vs_referential_on_draw_submit(self, api, landlord_pm_headers):
        """PRD 2.7: "Draw submission checks the work-period date
        (`ERR_DISBURSEMENT_PERIOD_IN_FUTURE`), then the active-engagement
        requirement (`ERR_NO_ACTIVE_ENGAGEMENT`), then project posture
        (`ERR_PROJECT_NOT_OPEN`)." PRD 2.7: "Inbound requests pass through a
        fixed screening funnel, and when several checks could fail at once the
        earlier stage's error is the one returned."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_draw_submit
        """
        sc = setup_project_in_construction()
        # Remove the only ACTIVE engagement so both gates fail together.
        suspended = get_success_data(api.suspend_engagement(sc["engagement"]["id"], landlord_pm_headers))
        assert suspended["status"] == "SUSPENDED"
        set_logical_clock(MID)

        d1 = create_draw_record(
            sc["project"]["id"],
            sc["contractor"]["id"],
            1_000_000,
            period_end_date="2026-08-20T00:00:00Z",  # after the logical clock
        )
        resp = api.submit_draw(d1["id"], make_contractor_rep_headers(sc["contractor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_PERIOD_IN_FUTURE)
        after = get_success_data(api.get_draw(d1["id"], landlord_pm_headers))
        assert after["status"] == "DRAFT", "the rejected submission must leave the draw in DRAFT"

    def test_referential_gate_fires_when_period_is_valid(self, api, landlord_pm_headers):
        """PRD 3.6: "at least one engagement of the project must be `ACTIVE`,
        else `ERR_NO_ACTIVE_ENGAGEMENT` (HTTP 422)". PRD 2.7: "Draw submission
        checks the work-period date (`ERR_DISBURSEMENT_PERIOD_IN_FUTURE`), then
        the active-engagement requirement (`ERR_NO_ACTIVE_ENGAGEMENT`), then
        project posture (`ERR_PROJECT_NOT_OPEN`)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_draw_submit
        """
        sc = setup_project_in_construction()
        get_success_data(api.suspend_engagement(sc["engagement"]["id"], landlord_pm_headers))
        set_logical_clock(MID)

        d1 = create_draw_record(sc["project"]["id"], sc["contractor"]["id"], 1_000_000)
        resp = api.submit_draw(d1["id"], make_contractor_rep_headers(sc["contractor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ENGAGEMENT)


class TestExactRemainingBoundary:
    def test_draw_approval_exactly_remaining_allowance(self, api, landlord_pm_headers):
        """PRD 3.6: "and it may not exceed the project's
        `allowance_remaining_cents`, else `ERR_DRAW_EXCEEDS_REMAINING` (HTTP
        422) — an approval exactly equal to the remaining allowance is
        permitted." PRD 3.6: "it is `ALLOWANCE_EXHAUSTED` when the pool is
        funded (a total above zero) and consumption has reached or passed it —
        consumption exactly equal to the pool already exhausts it".

        Design: Difficulty/boundary_precision_check/draw_approval_exactly_remaining_allowance
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        _consume_35m(api, sc["project"]["id"], ctr)

        d4 = create_submitted_draw(
            sc["project"]["id"], ctr, 15_000_000, waiver_type="UNCONDITIONAL_FINAL"
        )["draw"]
        approved = validate_success(
            api.approve_draw(
                d4["id"],
                {"approved_amount_cents": 15_000_000},
                make_landlord_approver_headers("approver-1"),
            ),
            200,
        )
        assert approved["status"] == "APPROVED", (
            "an approval exactly equal to the remaining allowance is permitted"
        )
        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_remaining_cents"] == 0
        assert project["posture"] == "ALLOWANCE_EXHAUSTED"

    def test_draw_approval_one_cent_over_remaining_rejected(self, api, landlord_pm_headers):
        """PRD 3.6: "and it may not exceed the project's
        `allowance_remaining_cents`, else `ERR_DRAW_EXCEEDS_REMAINING` (HTTP
        422) — an approval exactly equal to the remaining allowance is
        permitted."

        Design: Difficulty/boundary_precision_check/draw_approval_exactly_remaining_allowance
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        _consume_35m(api, sc["project"]["id"], ctr)

        d4 = create_submitted_draw(
            sc["project"]["id"], ctr, 15_000_001, waiver_type="UNCONDITIONAL_FINAL"
        )["draw"]
        resp = api.approve_draw(
            d4["id"],
            {"approved_amount_cents": 15_000_001},
            make_landlord_approver_headers("approver-1"),
        )
        validate_error(resp, ApiErrorId.ERR_DRAW_EXCEEDS_REMAINING)
        assert resp.status_code == 422
        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_remaining_cents"] == 15_000_000, (
            "the rejected approval must leave the remaining allowance unchanged"
        )

    def test_draw_approval_below_remaining_keeps_posture_open(self, api, landlord_pm_headers):
        """PRD 3.6: "it is `ALLOWANCE_EXHAUSTED` when the pool is funded (a
        total above zero) and consumption has reached or passed it —
        consumption exactly equal to the pool already exhausts it; otherwise it
        is `ON_HOLD` when any draw of the project sits in `ON_HOLD`; otherwise
        it is `OPEN`."

        Design: Difficulty/boundary_precision_check/draw_approval_exactly_remaining_allowance
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        _consume_35m(api, sc["project"]["id"], ctr)

        d4 = create_submitted_draw(sc["project"]["id"], ctr, 14_000_000)["draw"]
        approved = validate_success(
            api.approve_draw(
                d4["id"],
                {"approved_amount_cents": 14_000_000},
                make_landlord_approver_headers("approver-1"),
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["allowance_remaining_cents"] == 1_000_000
        assert project["posture"] == "OPEN", (
            "consumption still below the pool leaves the posture OPEN"
        )


class TestActiveEngagementGate:
    def test_draw_submit_requires_active_engagement(self, api, landlord_pm_headers):
        """PRD 3.4: "A qualified firm may later be suspended (`QUALIFIED` →
        `SUSPENDED`), which immediately cascades every `ACTIVE` engagement of
        that contractor into `SUSPENDED` as well". PRD 3.6: "at least one
        engagement of the project must be `ACTIVE`, else
        `ERR_NO_ACTIVE_ENGAGEMENT` (HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/draw_submit_requires_active_engagement
        """
        sc = setup_project_in_construction()
        # Suspending the contractor cascades the engagement to SUSPENDED.
        get_success_data(api.suspend_contractor(sc["contractor"]["id"], landlord_pm_headers))
        engagement = get_success_data(
            api.get_engagement(sc["engagement"]["id"], landlord_pm_headers)
        )
        assert engagement["status"] == "SUSPENDED", (
            "the contractor suspend cascades to its ACTIVE engagements"
        )
        set_logical_clock(MID)

        d1 = create_draw_record(sc["project"]["id"], sc["contractor"]["id"], 1_000_000)
        resp = api.submit_draw(d1["id"], make_contractor_rep_headers(sc["contractor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ENGAGEMENT)
        after = get_success_data(api.get_draw(d1["id"], landlord_pm_headers))
        assert after["status"] == "DRAFT"

    def test_submit_succeeds_after_engagement_reinstated(self, api, landlord_pm_headers):
        """PRD 3.4: "reinstatement (`SUSPENDED` → `QUALIFIED`) again requires
        unexpired insurance at the clock, and it pointedly does not resurrect
        the cascaded engagements — each one needs its own reinstatement."
        PRD 3.4: "The landlord may suspend an `ACTIVE` engagement and later
        reinstate it (`SUSPENDED` → `ACTIVE`), which requires the contractor to
        be `QUALIFIED` at that moment".

        Design: Difficulty/cross_entity_state_dependency/draw_submit_requires_active_engagement
        """
        sc = setup_project_in_construction()
        get_success_data(api.suspend_contractor(sc["contractor"]["id"], landlord_pm_headers))
        set_logical_clock(MID)

        # Reinstating the contractor leaves the cascaded engagement SUSPENDED.
        contractor = get_success_data(
            api.reinstate_contractor(sc["contractor"]["id"], landlord_pm_headers)
        )
        assert contractor["qualification_status"] == "QUALIFIED"
        engagement = get_success_data(
            api.get_engagement(sc["engagement"]["id"], landlord_pm_headers)
        )
        assert engagement["status"] == "SUSPENDED", (
            "contractor reinstatement does not resurrect cascaded engagements"
        )

        # The engagement's own reinstatement restores submit eligibility.
        engagement = get_success_data(
            api.reinstate_engagement(sc["engagement"]["id"], landlord_pm_headers)
        )
        assert engagement["status"] == "ACTIVE"
        d1 = create_draw_record(sc["project"]["id"], sc["contractor"]["id"], 1_000_000)
        submitted = validate_success(
            api.submit_draw(d1["id"], make_contractor_rep_headers(sc["contractor"]["id"])), 200
        )
        assert submitted["status"] == "SUBMITTED"


class TestDrawOccAndSegregation:
    def test_occ_disbursement_create_stale_project_rejected(self, api, landlord_pm_headers):
        """PRD 2.8: "Creating a disbursement request against a project (`POST
        /api/ti-projects/{id}/disbursement-requests`) likewise requires
        `expected_ti_project_version` matching the project's current `version`,
        with mismatches rejected as `ERR_STALE_VERSION` (HTTP 412) — a
        change-order approval that recomputed `total_cost_cents` and flipped
        `posture` in the interim leaves the draw writer's view of
        `allowance_remaining_cents` stale." PRD 3.5: "Creating the draft
        already advances the project's `version`, since the project aggregate
        now includes the new record."

        Design: Corner/cross_cutting_layers/occ_disbursement_create_stale_project_rejected
        """
        sc = setup_project_in_construction()
        observed = fresh_project_version(sc["project"]["id"])

        # An intervening change-order draft advances the project's version.
        co = create_change_order_record(
            sc["project"]["id"],
            make_tenant_rep_headers(sc["tenant"]["id"]),
            lines=[{"description": "x", "amount_cents": 100_000}],
        )
        assert co["status"] == "DRAFT"

        # The draw drafted against the pre-CO project version is stale.
        resp = api.create_draw(
            sc["project"]["id"],
            {
                "period_end_date": "2026-08-14T00:00:00Z",
                "requested_amount_cents": 1_000_000,
                "expected_ti_project_version": observed,
            },
            make_contractor_rep_headers(sc["contractor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_segregation_of_duties_co_approver_cannot_approve_draw(
        self, api, landlord_pm_headers
    ):
        """PRD 3.6: "the approver's `X-User-ID` must differ from the
        `approved_by_user_id` stamped on every `APPROVED` change order of the
        same project, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)". PRD 3.5:
        "Approval stamps `approved_by_user_id` with the approver's `X-User-ID`".

        Design: Corner/roles/segregation_of_duties_co_approver_cannot_approve_draw
        """
        sc = _construction_with_clock(api)
        ctr = sc["contractor"]["id"]
        tenant_headers = make_tenant_rep_headers(sc["tenant"]["id"])

        co = create_approved_change_order(
            sc["project"]["id"],
            tenant_headers,
            lines=[{"description": "x", "amount_cents": 100_000}],
            approver_id="approver-2",
        )
        assert co["approved_by_user_id"] == "approver-2"

        draw = create_submitted_draw(sc["project"]["id"], ctr, 1_000_000)["draw"]

        # The same X-User-ID that approved the CO may not approve the draw.
        resp = api.approve_draw(
            draw["id"],
            {"approved_amount_cents": 1_000_000},
            make_landlord_approver_headers("approver-2"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        # A different approver id passes the segregation check.
        approved = validate_success(
            api.approve_draw(
                draw["id"],
                {"approved_amount_cents": 1_000_000},
                make_landlord_approver_headers("approver-1"),
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
