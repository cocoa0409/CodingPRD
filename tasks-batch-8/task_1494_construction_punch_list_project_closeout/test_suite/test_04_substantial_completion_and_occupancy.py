"""Substantial-completion gates and ordering, the SC rejection loop, and beneficial occupancy."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_timestamp_instant_equals,
    begin_punch,
    complete_walk,
    get_project,
    new_project,
    new_trade,
    schedule_walk,
    set_clock,
    setup_substantially_complete_project,
    setup_walked_project,
    validate_error,
    validate_success,
)

PM = TEST_USERS["gc_pm_headers"]
INSP = TEST_USERS["gc_inspector_headers"]
OWNER = TEST_USERS["owner_rep_headers"]


class TestScRequestGates:

    def test_sc_request_walk_incomplete_returns_error(self):
        """PRD §3.4: "The four gates are enforced in a fixed, safety-first order: any blocking life-safety item rejects the request with `ERR_OPEN_LIFE_SAFETY_ITEMS`; then any blocking major item rejects it with `ERR_OPEN_MAJOR_ITEMS`; then an open minor count above the allowance rejects it with `ERR_TOO_MANY_OPEN_MINOR_ITEMS`; and only then does walk completion surface, with any unwalked trade rejecting the request as `ERR_WALK_INCOMPLETE`."

        Design: Corner/state_machines/sc_request_walk_incomplete_returns_error
        """
        project = new_project(name="Proj")
        trade_a = new_trade(project["id"], trade_name="ELECTRICAL", subcontractor_org="SparkyCo")
        new_trade(project["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        begin_punch(project["id"])
        walk_a = schedule_walk(project["id"], trade_a["id"], "insp-1",
                               "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
        set_clock("2026-08-03T10:00:00Z")
        complete_walk(walk_a["id"])
        # Zero punch items: only the walk-completion gate can fail (trade B unwalked).
        resp = api_client.request_sc_review(project["id"], PM)
        validate_error(resp, ApiErrorId.ERR_WALK_INCOMPLETE)
        assert get_project(project["id"])["status"] == "PUNCH_ACTIVE"

    def test_sc_request_open_major_returns_error(self):
        """PRD §3.4: "The four gates are enforced in a fixed, safety-first order: any blocking life-safety item rejects the request with `ERR_OPEN_LIFE_SAFETY_ITEMS`; then any blocking major item rejects it with `ERR_OPEN_MAJOR_ITEMS`; then an open minor count above the allowance rejects it with `ERR_TOO_MANY_OPEN_MINOR_ITEMS`; and only then does walk completion surface, with any unwalked trade rejecting the request as `ERR_WALK_INCOMPLETE`."

        Design: Corner/state_machines/sc_request_open_major_returns_error
        """
        ctx = setup_walked_project(name="Proj", item_severities=("MAJOR",))
        resp = api_client.request_sc_review(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_MAJOR_ITEMS)
        assert get_project(ctx["project"]["id"])["status"] == "PUNCH_ACTIVE"


class TestMinorAllowanceBoundary:

    def test_five_open_minors_pass(self):
        """PRD §3.4: "The project's `sc_eligible` flag tracks readiness continuously — true exactly when `open_life_safety_count` is zero, `open_major_count` is zero, `open_minor_count` is no more than five (five open minor items pass; a sixth fails), and every trade package of the project has completed its pre-punch walk."

        Design: Difficulty/boundary_precision_check/sc_minor_allowance_exactly_five_passes_six_fails
        """
        ctx = setup_walked_project(name="P5", item_severities=["MINOR"] * 5)
        granted = validate_success(api_client.request_sc_review(ctx["project"]["id"], PM), 200)
        assert granted["status"] == "SC_REVIEW"

    def test_six_open_minors_fail(self):
        """PRD §3.4: "The project's `sc_eligible` flag tracks readiness continuously — true exactly when `open_life_safety_count` is zero, `open_major_count` is zero, `open_minor_count` is no more than five (five open minor items pass; a sixth fails), and every trade package of the project has completed its pre-punch walk."
        PRD §3.4: "then an open minor count above the allowance rejects it with `ERR_TOO_MANY_OPEN_MINOR_ITEMS`"

        Design: Difficulty/boundary_precision_check/sc_minor_allowance_exactly_five_passes_six_fails
        """
        ctx = setup_walked_project(name="P6", item_severities=["MINOR"] * 6)
        resp = api_client.request_sc_review(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_TOO_MANY_OPEN_MINOR_ITEMS)
        assert get_project(ctx["project"]["id"])["status"] == "PUNCH_ACTIVE"


class TestScGatePriorityOrdering:

    def test_life_safety_error_beats_minor_count_constraint(self):
        """PRD §3.4: "The four gates are enforced in a fixed, safety-first order: any blocking life-safety item rejects the request with `ERR_OPEN_LIFE_SAFETY_ITEMS`; then any blocking major item rejects it with `ERR_OPEN_MAJOR_ITEMS`; then an open minor count above the allowance rejects it with `ERR_TOO_MANY_OPEN_MINOR_ITEMS`; and only then does walk completion surface, with any unwalked trade rejecting the request as `ERR_WALK_INCOMPLETE`."

        Design: Difficulty/priority_pair_validation_conflict/sc_request_safety_error_beats_minor_count_constraint
        """
        ctx = setup_walked_project(
            name="Proj P1", item_severities=["LIFE_SAFETY"] + ["MINOR"] * 6,
        )
        resp = api_client.request_sc_review(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_LIFE_SAFETY_ITEMS)
        assert get_project(ctx["project"]["id"])["status"] == "PUNCH_ACTIVE"

    def test_life_safety_error_beats_major_and_minor_constraints(self):
        """PRD §3.4: "The four gates are enforced in a fixed, safety-first order: any blocking life-safety item rejects the request with `ERR_OPEN_LIFE_SAFETY_ITEMS`; then any blocking major item rejects it with `ERR_OPEN_MAJOR_ITEMS`; then an open minor count above the allowance rejects it with `ERR_TOO_MANY_OPEN_MINOR_ITEMS`; and only then does walk completion surface, with any unwalked trade rejecting the request as `ERR_WALK_INCOMPLETE`."

        Design: Difficulty/priority_pair_validation_conflict/sc_request_safety_error_beats_minor_count_constraint
        """
        ctx = setup_walked_project(
            name="Proj P2", item_severities=["LIFE_SAFETY", "MAJOR"] + ["MINOR"] * 6,
        )
        resp = api_client.request_sc_review(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_LIFE_SAFETY_ITEMS)
        assert get_project(ctx["project"]["id"])["status"] == "PUNCH_ACTIVE"


class TestScDeterminationCycle:

    def test_rejection_returns_to_punch_active_then_reentry(self):
        """PRD §3.4: "A rejection requires a `rejection_note` (its absence is an `ERR_INVALID_REQUEST`), returns the project to `PUNCH_ACTIVE` for another correction cycle, and increases `sc_rejection_count` by one."
        PRD §3.4: "on success the project moves to `SUBSTANTIALLY_COMPLETE` and both `substantial_completion_date` and `warranty_start_date` are stamped with the current logical clock, so the warranty clock starts at the SC instant."

        Design: Difficulty/non_linear_state_machine/project_sc_review_rejection_cycle
        """
        ctx = setup_walked_project(name="Proj SC")
        validate_success(api_client.request_sc_review(ctx["project"]["id"], PM), 200)

        rejected = validate_success(api_client.determine_substantial_completion(
            ctx["project"]["id"],
            {"approved": False, "rejection_note": "Owner wants corridor re-checked"},
            OWNER,
        ), 200)
        assert rejected["status"] == "PUNCH_ACTIVE"
        assert rejected["sc_rejection_count"] == 1

        # Re-entry: eligibility is re-evaluated and a second request succeeds.
        validate_success(api_client.request_sc_review(ctx["project"]["id"], PM), 200)
        approved = validate_success(api_client.determine_substantial_completion(
            ctx["project"]["id"], {"approved": True}, OWNER,
        ), 200)
        assert approved["status"] == "SUBSTANTIALLY_COMPLETE"
        assert approved["sc_rejection_count"] == 1
        # The walk was completed at the pinned clock 2026-08-03T10:00:00Z; the
        # clock has not moved since, so the determination stamps that instant.
        assert_timestamp_instant_equals(
            approved["substantial_completion_date"], "2026-08-03T10:00:00Z"
        )

    def test_rejection_requires_note(self):
        """PRD §3.4: "A rejection requires a `rejection_note` (its absence is an `ERR_INVALID_REQUEST`), returns the project to `PUNCH_ACTIVE` for another correction cycle, and increases `sc_rejection_count` by one."

        Design: Difficulty/non_linear_state_machine/project_sc_review_rejection_cycle
        """
        ctx = setup_walked_project(name="Proj")
        validate_success(api_client.request_sc_review(ctx["project"]["id"], PM), 200)
        resp = api_client.determine_substantial_completion(
            ctx["project"]["id"], {"approved": False}, OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = get_project(ctx["project"]["id"])
        assert after["status"] == "SC_REVIEW"
        assert after["sc_rejection_count"] == 0


class TestScStampsAndOccupancy:

    def test_sc_determination_sets_sc_date_and_warranty_start(self):
        """PRD §3.4: "on success the project moves to `SUBSTANTIALLY_COMPLETE` and both `substantial_completion_date` and `warranty_start_date` are stamped with the current logical clock, so the warranty clock starts at the SC instant."

        Design: Corner/state_machines/sc_determination_sets_sc_date_and_warranty_start
        """
        ctx = setup_walked_project(name="Proj")
        validate_success(api_client.request_sc_review(ctx["project"]["id"], PM), 200)
        approved = validate_success(api_client.determine_substantial_completion(
            ctx["project"]["id"], {"approved": True}, OWNER,
        ), 200)
        assert_timestamp_instant_equals(
            approved["substantial_completion_date"], "2026-08-03T10:00:00Z"
        )
        assert_timestamp_instant_equals(
            approved["warranty_start_date"], "2026-08-03T10:00:00Z"
        )

    def test_occupancy_before_sc_date_returns_error(self):
        """PRD §3.4: "Registration is single-shot — a second call is rejected with `ERR_OCCUPANCY_ALREADY_REGISTERED` — and the supplied date may not fall earlier than `substantial_completion_date` (`ERR_OCCUPANCY_BEFORE_SC`, HTTP 422)."

        Design: Corner/validations/occupancy_before_sc_date_returns_error
        """
        ctx = setup_substantially_complete_project(name="Proj")
        project_id = ctx["project"]["id"]
        early = api_client.register_beneficial_occupancy(
            project_id, {"occupancy_date": "2026-08-01T00:00:00Z"}, OWNER,
        )
        validate_error(early, ApiErrorId.ERR_OCCUPANCY_BEFORE_SC)

        # A date equal to the SC instant is accepted ("may not fall earlier than").
        ok = validate_success(api_client.register_beneficial_occupancy(
            project_id, {"occupancy_date": "2026-08-03T10:00:00Z"}, OWNER,
        ), 200)
        assert ok["beneficial_occupancy_registered"] is True

    def test_double_occupancy_registration_returns_error(self):
        """PRD §3.4: "Registration is single-shot — a second call is rejected with `ERR_OCCUPANCY_ALREADY_REGISTERED` — and the supplied date may not fall earlier than `substantial_completion_date` (`ERR_OCCUPANCY_BEFORE_SC`, HTTP 422)."

        Design: Corner/validations/double_occupancy_registration_returns_error
        """
        ctx = setup_substantially_complete_project(name="Proj")
        project_id = ctx["project"]["id"]
        first = validate_success(api_client.register_beneficial_occupancy(
            project_id, {"occupancy_date": "2026-08-04T00:00:00Z"}, OWNER,
        ), 200)
        assert first["beneficial_occupancy_date"].startswith("2026-08-04")

        second = api_client.register_beneficial_occupancy(
            project_id, {"occupancy_date": "2026-08-05T00:00:00Z"}, OWNER,
        )
        validate_error(second, ApiErrorId.ERR_OCCUPANCY_ALREADY_REGISTERED)
        after = get_project(project_id)
        assert after["beneficial_occupancy_date"].startswith("2026-08-04")

    def test_start_closeout_without_occupancy_returns_error(self):
        """PRD §3.4: "The move requires occupancy to be registered first; without it the request fails with `ERR_OCCUPANCY_NOT_REGISTERED`, and as always the transition increments the project's `version`."

        Design: Corner/validations/start_closeout_without_occupancy_returns_error
        """
        ctx = setup_substantially_complete_project(name="Proj")
        resp = api_client.start_closeout(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_OCCUPANCY_NOT_REGISTERED)
        assert get_project(ctx["project"]["id"])["status"] == "SUBSTANTIALLY_COMPLETE"
