"""Plan lifecycle: publish segregation of duties, revise cascade and OCC,
archive guards, and the closed-interval plan window rule."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_CURVE_TIERS,
    PLAN_CREATOR_USER_ID,
    PLAN_PUBLISHER_USER_ID,
    TEST_USERS,
    accept_assignment,
    assert_plan_assignment,
    create_plan,
    create_program,
    create_rep,
    decline_assignment,
    get_assignment,
    get_success_data,
    make_comp_admin_headers,
    revise_plan,
    setup_assignment,
    setup_program_with_plan,
    terminate_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]


def _revise_payload(version, **fields):
    payload = {"expected_plan_version": version}
    payload.update(fields)
    return payload


class TestPublishSegregation:
    def test_publish_by_creator_segregation_forbidden(self, api):
        """PRD §2.8: "Publishing the plan, and later revising its document,
        must each be performed by a different operator than the creator; an
        attempt by the creator to publish or revise their own plan is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/roles/plan_publish_by_creator_forbidden
        """
        sc = setup_program_with_plan(program_name="Prog SD", plan_name="Plan SD",
                                     publish=False)
        plan = sc["plan"]

        resp = api.publish_plan(plan["id"],
                                make_comp_admin_headers(PLAN_CREATOR_USER_ID))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        assert get_success_data(api.get_plan(plan["id"], ADMIN))["status"] == "DRAFT"

        ok = api.publish_plan(plan["id"],
                              make_comp_admin_headers(PLAN_PUBLISHER_USER_ID))
        assert validate_success(ok, 200)["status"] == "PUBLISHED"


class TestReviseOccAndCascade:
    def test_revise_with_stale_plan_version_rejected(self, api):
        """PRD §2.7: "If another writer has advanced the plan's version since
        the client last read it — whether through a publish or an earlier
        revision — the mismatch is rejected with `ERR_STALE_PLAN_VERSION`
        (HTTP 412), preventing the client from unknowingly superseding a
        document it has not seen."

        Design: Corner/cross_cutting_layers/occ_stale_plan_version_on_revise
        """
        sc = setup_program_with_plan(program_name="Prog OC1",
                                     plan_name="Plan OC1")
        plan = sc["plan"]
        observed_version = plan["version"]

        first = api.revise_plan(plan["id"], _revise_payload(observed_version),
                                make_comp_admin_headers(PLAN_PUBLISHER_USER_ID))
        revised = validate_success(first, 200)
        assert revised["version"] == observed_version + 1
        assert revised["document_version"] == 2

        replay = api.revise_plan(plan["id"], _revise_payload(observed_version),
                                 make_comp_admin_headers(PLAN_PUBLISHER_USER_ID))
        validate_error(replay, ApiErrorId.ERR_STALE_PLAN_VERSION, 412)
        after = get_success_data(api.get_plan(plan["id"], ADMIN))
        assert after["document_version"] == 2

    def test_revise_reverts_accepted_assignment_to_offered(self, api):
        """PRD §3.1: "A successful revision leaves the plan in `PUBLISHED`,
        increments `document_version` by 1, increments the plan's `version` by
        1, and triggers a document re-offer cascade: every assignment of the
        plan whose lifecycle `status` is `ACTIVE` has its `acceptance_status`
        returned to `OFFERED`, whether it was `ACCEPTED` or `DECLINED`, while
        each assignment's `accepted_document_version` is deliberately left
        unchanged as historical record."

        Design: Difficulty/non_linear_state_machine/assignment_acceptance_cycle_on_plan_revise
        """
        sc = setup_program_with_plan(program_name="Prog Cyc",
                                     plan_name="Plan CY",
                                     curve_tiers=CANONICAL_CURVE_TIERS)
        plan = sc["plan"]
        rep = create_rep(sc["program"]["id"], "Rep CY", "CY-R1")
        assignment = setup_assignment(sc["program"], plan, rep, accept=True)
        assert assignment["accepted_document_version"] == 1

        revised = revise_plan(plan["id"], plan["version"],
                              curve_tiers=[{"attainment_floor_bps": 0,
                                            "rate_bps": 1100},
                                           {"attainment_floor_bps": 8000,
                                            "rate_bps": 1500},
                                           {"attainment_floor_bps": 10000,
                                            "rate_bps": 2500}])
        assert revised["document_version"] == 2

        reverted = get_assignment(assignment["id"])
        assert reverted["acceptance_status"] == "OFFERED"
        assert reverted["status"] == "ACTIVE", (
            "the lifecycle dimension stays ACTIVE through the document cycle"
        )
        assert reverted["accepted_document_version"] == 1, (
            "the historical acceptance version is retained while OFFERED"
        )

    def test_reaccept_after_revise_pins_new_document_version(self, api):
        """PRD §3.3: "Acceptance moves `acceptance_status` to `ACCEPTED`, pins
        `accepted_document_version` to the plan's current `document_version`,
        and — critically — releases every held credit: each `PENDING` credit
        entry of the assignment transitions to `POSTED` with
        `posted_period_index` set to the program's current period, and each
        such posting runs the full posting side effects of §3.4, earned
        increment and roll-up spawn included."

        Design: Difficulty/non_linear_state_machine/assignment_acceptance_cycle_on_plan_revise
        """
        sc = setup_program_with_plan(program_name="Prog Cyc2",
                                     plan_name="Plan CY2",
                                     curve_tiers=CANONICAL_CURVE_TIERS)
        plan = sc["plan"]
        rep = create_rep(sc["program"]["id"], "Rep CY2", "CY2-R1")
        assignment = setup_assignment(sc["program"], plan, rep, accept=True)

        revised = revise_plan(plan["id"], plan["version"],
                              rollup_rate_bps=250)
        assert revised["document_version"] == 2

        accepted = accept_assignment(assignment["id"], rep["id"])
        assert_plan_assignment(accepted)
        assert accepted["acceptance_status"] == "ACCEPTED"
        assert accepted["accepted_document_version"] == 2

    def test_declined_assignment_reoffered_on_revise(self, api):
        """PRD §3.1: "A successful revision leaves the plan in `PUBLISHED`,
        increments `document_version` by 1, increments the plan's `version` by
        1, and triggers a document re-offer cascade: every assignment of the
        plan whose lifecycle `status` is `ACTIVE` has its `acceptance_status`
        returned to `OFFERED`, whether it was `ACCEPTED` or `DECLINED`, while
        each assignment's `accepted_document_version` is deliberately left
        unchanged as historical record."

        Design: Corner/state_machines/decline_then_revise_reoffers_document
        """
        sc = setup_program_with_plan(program_name="Prog RO2",
                                     plan_name="Plan RO2")
        rep = create_rep(sc["program"]["id"], "Rep RO2", "RO2-R1")
        assignment = setup_assignment(sc["program"], sc["plan"], rep,
                                      accept=False)
        declined = decline_assignment(assignment["id"], rep["id"])
        assert declined["acceptance_status"] == "DECLINED"

        revise_plan(sc["plan"]["id"], sc["plan"]["version"])
        reoffered = get_assignment(assignment["id"])
        assert reoffered["acceptance_status"] == "OFFERED"


class TestArchiveAndTerminalLockdown:
    def test_revise_after_archive_rejected(self, api):
        """PRD §2.7: "The version check is evaluated only after the state
        precondition passes: a revise attempted on a plan that is no longer
        `PUBLISHED` fails with `ERR_INVALID_STATE_TRANSITION` regardless of the
        version carried."
        PRD §3.1: "Archival moves the plan to `ARCHIVED` — a terminal state —
        and increments the plan's `version` by 1."

        Design: Corner/state_machines/plan_revise_after_archive_rejected
        """
        sc = setup_program_with_plan(program_name="Prog TA", plan_name="Plan TA",
                                     effective_end_date="2026-06-30")
        plan = sc["plan"]
        resp = api.archive_plan(plan["id"], ADMIN)
        archived = validate_success(resp, 200)
        assert archived["status"] == "ARCHIVED"

        revise = api.revise_plan(
            plan["id"], _revise_payload(archived["version"]),
            make_comp_admin_headers(PLAN_PUBLISHER_USER_ID))
        validate_error(revise, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_plan(plan["id"], ADMIN))
        assert after["status"] == "ARCHIVED"
        assert after["document_version"] == 1

    def test_archive_with_active_assignment_blocked_then_succeeds(self, api):
        """PRD §3.1: "A plan in either `DRAFT` or `PUBLISHED` may be archived,
        but only while no assignment of the plan has lifecycle `status` equal
        to `ACTIVE`; archiving with active assignments is rejected with
        `ERR_PLAN_HAS_ACTIVE_ASSIGNMENTS`."

        Design: Corner/validations/archive_with_active_assignment_rejected
        """
        sc = setup_program_with_plan(program_name="Prog AA", plan_name="Plan AA")
        rep = create_rep(sc["program"]["id"], "Rep AA", "AA-R1")
        assignment = setup_assignment(sc["program"], sc["plan"], rep)

        blocked = api.archive_plan(sc["plan"]["id"], ADMIN)
        validate_error(blocked, ApiErrorId.ERR_PLAN_HAS_ACTIVE_ASSIGNMENTS, 409)

        terminate_assignment(assignment["id"])
        ok = api.archive_plan(sc["plan"]["id"], ADMIN)
        assert validate_success(ok, 200)["status"] == "ARCHIVED"


class TestPlanWindowClosedInterval:
    def test_plan_window_shared_boundary_date_overlaps(self, api):
        """PRD §3.1: "The window is a **closed interval**: the end date is
        inclusive, the end must not fall before the start (an inverted window
        is rejected with `ERR_INVALID_REQUEST`), and two plans of the same
        program whose closed intervals touch at all — a shared boundary date
        already counts as a collision — cannot coexist unless one of them is
        `ARCHIVED`; a colliding creation is rejected with
        `ERR_PLAN_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/plan_window_closed_interval_overlap
        """
        program = create_program("Prog Win")
        create_plan(program["id"], name="Plan WA",
                    effective_start_date="2026-01-01",
                    effective_end_date="2026-06-30")

        payload = {
            "program_id": program["id"],
            "name": "Plan WB",
            "effective_start_date": "2026-06-30",  # shared boundary date
            "effective_end_date": "2026-12-31",
            "curve_tiers": [{"attainment_floor_bps": 0, "rate_bps": 1000}],
        }
        resp = api.create_plan(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PLAN_WINDOW_OVERLAP, 409)

    def test_plan_window_first_non_overlapping_start_accepted(self, api):
        """PRD §3.1: "The window is a **closed interval**: the end date is
        inclusive, the end must not fall before the start (an inverted window
        is rejected with `ERR_INVALID_REQUEST`), and two plans of the same
        program whose closed intervals touch at all — a shared boundary date
        already counts as a collision — cannot coexist unless one of them is
        `ARCHIVED`; a colliding creation is rejected with
        `ERR_PLAN_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/plan_window_closed_interval_overlap
        """
        program = create_program("Prog Win2")
        create_plan(program["id"], name="Plan WA2",
                    effective_start_date="2026-01-01",
                    effective_end_date="2026-06-30")

        payload = {
            "program_id": program["id"],
            "name": "Plan WC2",
            "effective_start_date": "2026-07-01",  # first clear start
            "effective_end_date": "2026-12-31",
            "curve_tiers": [{"attainment_floor_bps": 0, "rate_bps": 1000}],
        }
        resp = api.create_plan(payload, ADMIN)
        plan = validate_success(resp, 201)
        assert plan["status"] == "DRAFT"
