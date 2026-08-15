"""Volunteer digitization program: claim selector policy, QC segregation of
duties, the fail loop, claim/release compensation, hour caps, and project
close."""
from test_helpers import (
    ApiErrorId,
    api_client,
    catalog_item,
    claim_next,
    create_item,
    get_item,
    make_item_available,
    create_active_project,
    create_request,
    create_ticket,
    get_project,
    get_ticket,
    make_volunteer_coordinator_headers,
    make_volunteer_headers,
    post_breach_run,
    register_researcher,
    setup_approved_assessment,
    setup_available_item,
    setup_claimed_ticket,
    setup_project_with_ticket,
    setup_qc_review_ticket,
    validate_error,
    validate_success,
    approve_request,
)

COORD = {"X-User-ID": "coord_1", "X-User-Role": "VolunteerCoordinator", "Content-Type": "application/json"}
VOL1 = {"X-User-ID": "vol_1", "X-User-Role": "Volunteer", "Content-Type": "application/json"}


class TestQcFailLoop:

    def test_qc_fail_loops_back_to_capture_with_counter(self):
        """PRD §3.5: "Quality control is performed by a `VolunteerCoordinator`
        under segregation of duties: the reviewer's `X-User-ID` must differ from
        the ticket's `claimed_by_user_id`, else `ERR_QC_SELF_REVIEW`. A pass
        moves `QC_REVIEW → COMPLETE` and decrements the project's
        `active_ticket_count`; a fail loops the ticket `QC_REVIEW → IN_CAPTURE`,
        increments its `qc_fail_count`, and leaves `active_ticket_count`
        unchanged because the ticket remains active."

        Design: Difficulty/non_linear_state_machine/digitization_qc_fail_loop
        """
        ctx = setup_available_item(title="Photos", condition_grade="GOOD",
                                   appraised_value_cents=15000,
                                   item_format="PHOTOGRAPH")
        project, ticket = setup_qc_review_ticket(ctx["item"]["id"],
                                                 volunteer_id="vol_1")
        assert ticket["status"] == "QC_REVIEW"

        failed1 = validate_success(
            api_client.qc_fail(ticket["id"], COORD))
        assert failed1["status"] == "IN_CAPTURE"
        assert failed1["qc_fail_count"] == 1

        validate_success(api_client.submit_qc(ticket["id"], VOL1))
        failed2 = validate_success(api_client.qc_fail(ticket["id"], COORD))
        assert failed2["status"] == "IN_CAPTURE"
        assert failed2["qc_fail_count"] == 2

    def test_qc_pass_after_fail_loop_completes_and_frees_project(self):
        """PRD §3.5: "A pass moves `QC_REVIEW → COMPLETE` and decrements the
        project's `active_ticket_count`; a fail loops the ticket `QC_REVIEW →
        IN_CAPTURE`, increments its `qc_fail_count`, and leaves
        `active_ticket_count` unchanged because the ticket remains active."

        Design: Difficulty/non_linear_state_machine/digitization_qc_fail_loop
        """
        ctx = setup_available_item(title="Photos", condition_grade="GOOD",
                                   appraised_value_cents=15000,
                                   item_format="PHOTOGRAPH")
        project, ticket = setup_qc_review_ticket(ctx["item"]["id"],
                                                 volunteer_id="vol_1")

        # One fail keeps the ticket active; then a pass completes it.
        validate_success(api_client.qc_fail(ticket["id"], COORD))
        assert get_project(project["id"])["active_ticket_count"] == 1
        validate_success(api_client.submit_qc(ticket["id"], VOL1))
        passed = validate_success(api_client.qc_pass(ticket["id"], COORD))
        assert passed["status"] == "COMPLETE"
        assert get_project(project["id"])["active_ticket_count"] == 0


class TestClaimReleaseCompensation:

    def test_claim_increments_active_count(self):
        """PRD §3.5: "The selected ticket moves `QUEUED → CLAIMED`, its
        `claimed_by_user_id` records the caller's `X-User-ID`, and the project's
        `active_ticket_count` increases by 1."

        Design: Difficulty/compensating_invariant/claim_then_release_restores_ticket_pool
        """
        ctx = setup_available_item(title="Photos", condition_grade="GOOD",
                                   appraised_value_cents=15000,
                                   item_format="PHOTOGRAPH")
        project, ticket = setup_project_with_ticket(ctx["item"]["id"])
        assert get_project(project["id"])["active_ticket_count"] == 0

        claimed = claim_next(project["id"], "vol_1")
        assert claimed["id"] == ticket["id"]
        assert claimed["status"] == "CLAIMED"
        assert claimed["claimed_by_user_id"] == "vol_1"
        assert get_project(project["id"])["active_ticket_count"] == 1

    def test_release_restores_pool_and_claimability(self):
        """PRD §3.5: "A volunteer may also release a ticket they hold — from
        `CLAIMED` or `IN_CAPTURE` back to `QUEUED`, claimant only — which nulls
        `claimed_by_user_id` and decrements `active_ticket_count`, exactly
        compensating the claim."

        Design: Difficulty/compensating_invariant/claim_then_release_restores_ticket_pool
        """
        ctx = setup_available_item(title="Photos", condition_grade="GOOD",
                                   appraised_value_cents=15000,
                                   item_format="PHOTOGRAPH")
        project, ticket = setup_claimed_ticket(ctx["item"]["id"],
                                               volunteer_id="vol_1")
        assert get_project(project["id"])["active_ticket_count"] == 1

        released = validate_success(api_client.release_ticket(ticket["id"], VOL1))
        assert released["status"] == "QUEUED"
        assert released["claimed_by_user_id"] is None
        assert get_project(project["id"])["active_ticket_count"] == 0, (
            "claim + release conserves the pool")

        # The released ticket is claimable again by anyone.
        reclaimed = claim_next(project["id"], "vol_2")
        assert reclaimed["id"] == ticket["id"]
        assert reclaimed["claimed_by_user_id"] == "vol_2"


class TestClaimSelector:

    def test_claim_next_selector_ranking_and_tiebreak(self):
        """PRD §3.5: "Claiming is a selector operation, not a pick-by-id
        operation: a `Volunteer` claims the next ticket under a project, and the
        system assigns from the claimable pool — the project's `QUEUED` tickets
        whose item is currently `AVAILABLE` — ranked by `priority_score`
        descending with ties broken by earliest `created_at`."

        Design: Corner/endpoints/claim_next_selector_ranking_and_tiebreak
        """
        ctx = setup_available_item(title="I1", condition_grade="POOR",
                                   appraised_value_cents=50000,
                                   item_format="ARTIFACT")
        i1 = ctx["item"]["id"]
        # Two plain items in the same collection/accession (no conservation
        # score, no approved requests): priority = 50 + 0 + 0 = 50.0.
        i2 = create_item(ctx["accession"]["id"], ctx["collection"]["id"],
                         title="I2")
        i3 = create_item(ctx["accession"]["id"], ctx["collection"]["id"],
                         title="I3")
        for it in (i2, i3):
            catalog_item(it["id"])
            make_item_available(it["id"])

        # One APPROVED request on I1, then an approved FRAGILE assessment:
        # confirmed score 0.5*100 + 0.3*25 + 0.2*50 = 67.5 ->
        # ticket priority 50 + 0.4*67.5 + 10*1 = 87.0.
        researcher = register_researcher()
        rq = create_request(researcher["id"], [i1], topic="t")
        approve_request(rq["id"])
        setup_approved_assessment(i1, condition_grade_observed="FRAGILE",
                                  urgency_score=80, treatment_estimate_hours=12)

        project = create_active_project("P1")
        t1 = create_ticket(project["id"], i1)
        t2 = create_ticket(project["id"], i2)
        t3 = create_ticket(project["id"], i3)
        assert t1["priority_score"] == 87.0
        assert t2["priority_score"] == 50.0
        assert t3["priority_score"] == 50.0

        c1 = claim_next(project["id"], "vol_1")
        assert c1["id"] == t1["id"], "highest priority claims first"
        c2 = claim_next(project["id"], "vol_2")
        assert c2["id"] == t2["id"], (
            "tie at 50.0 is broken by earliest created_at (t2 before t3)")
        c3 = claim_next(project["id"], "vol_3")
        assert c3["id"] == t3["id"]
        assert get_project(project["id"])["active_ticket_count"] == 3

    def test_claim_next_empty_pool_and_zone_exclusion(self):
        """PRD §3.5: "The project must be `ACTIVE` (`ERR_INVALID_STATE`), and an
        empty pool is rejected with `ERR_NO_CLAIMABLE_TICKETS`."
        PRD §3.5: "the system assigns from the claimable pool — the project's
        `QUEUED` tickets whose item is currently `AVAILABLE`"

        Design: Corner/endpoints/claim_next_empty_pool_and_zone_exclusion
        """
        ctx = setup_available_item()
        empty_project = create_active_project("Empty")
        held_project = create_active_project("Held")
        create_ticket(held_project["id"], ctx["item"]["id"])

        # Drive the item to ZONE_HOLD so the only QUEUED ticket is ineligible.
        post_breach_run(ctx["zone"]["id"], 3)
        assert get_item(ctx["item"]["id"])["status"] == "ZONE_HOLD"

        resp1 = api_client.claim_next_ticket(empty_project["id"], VOL1)
        validate_error(resp1, ApiErrorId.ERR_NO_CLAIMABLE_TICKETS)

        resp2 = api_client.claim_next_ticket(held_project["id"], VOL1)
        validate_error(resp2, ApiErrorId.ERR_NO_CLAIMABLE_TICKETS)


class TestProjectClose:

    def test_project_close_blocked_until_tickets_resolve(self):
        """PRD §3.5: "Activation moves `PLANNED → ACTIVE`; closing moves `ACTIVE
        → CLOSED` and is refused with `ERR_ACTIVE_TICKETS_REMAIN` while the
        project's `active_ticket_count` — the number of its tickets in
        `CLAIMED`, `IN_CAPTURE`, or `QC_REVIEW` — is anything other than zero."

        Design: Corner/endpoints/project_close_blocked_until_tickets_resolve
        """
        ctx = setup_available_item()
        project, ticket = setup_claimed_ticket(ctx["item"]["id"],
                                               volunteer_id="vol_1")

        resp = api_client.close_project(project["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_TICKETS_REMAIN)

        validate_success(api_client.release_ticket(ticket["id"], VOL1))
        closed = validate_success(api_client.close_project(project["id"], COORD))
        assert closed["status"] == "CLOSED"


class TestQcSegregation:

    def test_qc_self_review_forbidden(self):
        """PRD §3.5: "Quality control is performed by a `VolunteerCoordinator`
        under segregation of duties: the reviewer's `X-User-ID` must differ from
        the ticket's `claimed_by_user_id`, else `ERR_QC_SELF_REVIEW`."

        Design: Corner/errors/qc_self_review_forbidden
        """
        ctx = setup_available_item()
        _project, ticket = setup_qc_review_ticket(ctx["item"]["id"],
                                                  volunteer_id="vol_1")

        # The coordinator role is right, but the user id equals the claimant's.
        resp = api_client.qc_pass(
            ticket["id"],
            make_volunteer_coordinator_headers("vol_1"))
        validate_error(resp, ApiErrorId.ERR_QC_SELF_REVIEW)
        assert get_ticket(ticket["id"])["status"] == "QC_REVIEW"

        passed = validate_success(
            api_client.qc_pass(ticket["id"],
                               make_volunteer_coordinator_headers("coord_1")))
        assert passed["status"] == "COMPLETE"

    def test_volunteer_cannot_review_qc(self):
        """PRD §4: "| POST | `/digitization-tickets/{id}/qc-pass` | Pass QC
        (reviewer must differ from claimant) | VolunteerCoordinator |"
        PRD §2.8: "2. **Authorization** — the caller's role appears in the
        endpoint's authorized list, else `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §2.8: "Checks are evaluated in the following sequence, and the first
        failing tier determines the response"

        Design: Corner/rbac/volunteer_cannot_review_qc
        """
        ctx = setup_available_item()
        _project, ticket = setup_qc_review_ticket(ctx["item"]["id"],
                                                  volunteer_id="vol_1")

        # A Volunteer (even the ticket owner) is the wrong role: the tier-2
        # role gate fires before the tier-8 self-review gate.
        resp = api_client.qc_pass(ticket["id"], make_volunteer_headers("vol_1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403


class TestVolunteerHourCap:

    def test_volunteer_hour_cap_boundary(self):
        """PRD §3.5: "Hours are logged against a held ticket. The ticket must be
        `CLAIMED` or `IN_CAPTURE` (`ERR_INVALID_STATE`), the caller must be the
        claimant (`ERR_OWNERSHIP_MISMATCH`), and the posted `hours` must be a
        positive multiple of 0.25 (`ERR_INVALID_REQUEST`). The project's
        per-volunteer ledger then governs: if the caller's accumulated hours on
        this project plus the posted hours would land strictly above
        `max_hours_per_volunteer`, the logging is rejected with
        `ERR_VOLUNTEER_HOUR_CAP_EXCEEDED`; landing exactly on the cap is
        allowed."

        Design: Corner/complexity_layers/volunteer_hour_cap_boundary
        """
        ctx = setup_available_item()
        project, ticket = setup_claimed_ticket(ctx["item"]["id"],
                                               volunteer_id="vol_1")
        assert project["max_hours_per_volunteer"] == 40

        logged = validate_success(
            api_client.log_hours(ticket["id"], {"hours": 25.0}, VOL1))
        assert logged["hours_logged"] == 25.0

        # 1.3 is not a positive multiple of 0.25.
        resp1 = api_client.log_hours(ticket["id"], {"hours": 1.3}, VOL1)
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

        # 25.0 + 15.0 lands exactly on the 40-hour cap: allowed.
        logged2 = validate_success(
            api_client.log_hours(ticket["id"], {"hours": 15.0}, VOL1))
        assert logged2["hours_logged"] == 40.0

        # 40.0 + 0.25 lands strictly above the cap: rejected.
        resp2 = api_client.log_hours(ticket["id"], {"hours": 0.25}, VOL1)
        validate_error(resp2, ApiErrorId.ERR_VOLUNTEER_HOUR_CAP_EXCEEDED)
        assert get_ticket(ticket["id"])["hours_logged"] == 40.0
