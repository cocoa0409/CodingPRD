"""Requests that fail two different checks at once.

Each scenario arranges for two rejection conditions to hold simultaneously on
one call, pins which error comes back, and then fires a second call that proves
the losing condition was genuinely live rather than absent.
"""

from test_helpers import (
    ChamberSpec,
    EquipmentSpec,
    LineSpec,
    LotSpec,
    RecipeSpec,
    StepSpec,
    USER_DUAL_ROLE,
    USER_QUALITY_MANAGER,
    build_line,
    complete_step,
    make_operator_headers,
    quality_manager_headers,
    two_recipe_line_spec,
)
from test_helpers.api_errors import (
    ERR_LOT_ON_HOLD,
    ERR_NO_QUALIFIED_CHAMBER,
    ERR_PM_PURGE_ACTIVE,
    ERR_SOD_SELF_APPROVAL,
    ERR_STALE_RECIPE_VERSION,
    ERR_STEP_SEQUENCE_VIOLATION,
    assert_wins_over,
)
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_timestamp_equals,
)
from test_helpers.factories import approve_payload, step_run_payload
from prd_bench_local_runner.testing.validators import validate_error, validate_success


# --------------------------------------------------------------------------
# A held lot inside an open purge window
# --------------------------------------------------------------------------


def _purge_window_over_a_held_split(fab):
    """A born-held split lot whose next tool has just come out of maintenance."""
    env = build_line(fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 6, "STANDARD")]))
    env.child = fab.split_lot(env.lots[0]["id"], 2, "LOT-001-E1", "HOT")

    fab.set_clock("2026-08-02T00:00:00Z")
    fab.pm_start(env.equipments[0]["id"], "Scheduled 168-hour PM")
    env.tool = fab.pm_complete(env.equipments[0]["id"])
    return env


class TestHoldStateOutranksPurgeWindow:
    def test_the_hold_is_reported_and_the_purge_window_is_not(self, fab):
        """One track-in trips both rule 17 and rule 37; only rule 17 is answered.

        PRD: "When several checks could reject the same request, the server
        evaluates them in a fixed order and returns the error of the **first**
        failing check."

        Design: Difficulty/priority_pair_validation_conflict/lot_hold_state_outranks_pm_purge_window_on_track_in
        """
        env = _purge_window_over_a_held_split(fab)
        operator_id = env.operators[0]["id"]

        # Born held, and the litho tool it needs is inside its purge window.
        assert_lot_state(env.child, flow_state="RELEASED", hold_state="ENGINEERING_HOLD")
        assert_timestamp_equals(
            env.tool["purge_until"], "2026-08-03T00:00:00Z", "purge_until"
        )

        response = fab.client.create_step_run(
            step_run_payload(env.child["id"], env.steps[0]["id"], operator_id),
            make_operator_headers(operator_id),
        )

        body = validate_error(response, ERR_LOT_ON_HOLD, 409)
        assert body["error_id"] != ERR_PM_PURGE_ACTIVE
        assert_wins_over(ERR_LOT_ON_HOLD, ERR_PM_PURGE_ACTIVE)

    def test_the_purge_window_really_was_the_losing_check(self, fab):
        """The unheld parent, on the same tool at the same instant, trips rule 37.

        PRD: "During the purge window no run may open on any of the tool's
        chambers: the interval is closed, so a track-in at exactly `purge_until`
        is still rejected with `ERR_PM_PURGE_ACTIVE`, and only a strictly later
        instant is admitted."

        Design: Difficulty/priority_pair_validation_conflict/lot_hold_state_outranks_pm_purge_window_on_track_in
        """
        env = _purge_window_over_a_held_split(fab)
        operator_id = env.operators[0]["id"]
        litho_step = env.steps[0]["id"]

        fab.client.create_step_run(
            step_run_payload(env.child["id"], litho_step, operator_id),
            make_operator_headers(operator_id),
        )

        # The parent is RELEASED with hold_state NONE, so rule 17 cannot fire.
        parent_attempt = fab.client.create_step_run(
            step_run_payload(env.lots[0]["id"], litho_step, operator_id),
            make_operator_headers(operator_id),
        )
        validate_error(parent_attempt, ERR_PM_PURGE_ACTIVE, 409)

        # Neither rejection left a run behind or moved anything.
        assert fab.count(
            fab.client.list_step_runs(
                make_operator_headers(operator_id), {"lot_id": env.child["id"]}
            )
        ) == 0
        assert_lot_state(
            fab.read_lot(env.child["id"]),
            flow_state="RELEASED",
            hold_state="ENGINEERING_HOLD",
            current_step_seq=0,
        )
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"
        assert fab.read_equipment(env.equipments[0]["id"])["state"] == "IDLE"


# --------------------------------------------------------------------------
# A self-approval carrying the wrong recipe version
# --------------------------------------------------------------------------


def _self_authored_notice(fab):
    """A notice authored by the dual-role user, plus a version the recipe never had."""
    recipe = fab.recipe("ETCH-100", "ETCH", 100.0, 100)
    notice = fab.change_request(
        recipe["id"], "MAJOR", 110.0, "Widen etch depth by ten percent",
        author_user_id=USER_DUAL_ROLE,
    )
    return recipe, notice


class TestSelfApprovalOutranksStaleRecipeVersion:
    def test_the_separation_of_duties_breach_is_reported_first(self, fab):
        """One approval trips both rule 7 and rule 10; only rule 7 is answered.

        PRD: "An approval whose `X-User-ID` equals that value is rejected with
        `ERR_SOD_SELF_APPROVAL` (HTTP 409), even though the caller holds the
        `QualityManager` role."

        Design: Difficulty/priority_pair_validation_conflict/self_approval_outranks_stale_recipe_version_on_ecn_approve
        """
        recipe, notice = _self_authored_notice(fab)
        assert notice["author_user_id"] == USER_DUAL_ROLE
        assert_hours(notice["risk_score"], 60.00, "risk_score")
        wrong_version = recipe["version"] + 1

        response = fab.client.approve_change_request(
            notice["id"],
            approve_payload(wrong_version),
            quality_manager_headers(USER_DUAL_ROLE),
        )

        body = validate_error(response, ERR_SOD_SELF_APPROVAL, 409)
        assert body["error_id"] != ERR_STALE_RECIPE_VERSION
        assert_wins_over(ERR_SOD_SELF_APPROVAL, ERR_STALE_RECIPE_VERSION)

        stored = fab.read_change_request(notice["id"])
        assert stored["status"] == "SUBMITTED"
        assert_nulls(stored, "approver_user_id", "pinned_recipe_revision")
        assert_fields(
            fab.read_recipe(recipe["id"]),
            status="QUALIFIED",
            version=recipe["version"],
        )

    def test_the_version_disagreement_really_was_the_losing_check(self, fab):
        """The same body from a second reviewer trips rule 10 instead.

        PRD: "A mismatch with the recipe's current `version` is rejected with
        `ERR_STALE_RECIPE_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/self_approval_outranks_stale_recipe_version_on_ecn_approve
        """
        recipe, notice = _self_authored_notice(fab)
        wrong_version = recipe["version"] + 1

        # A reviewer who did not author the notice clears rule 7 entirely.
        response = fab.client.approve_change_request(
            notice["id"],
            approve_payload(wrong_version),
            quality_manager_headers(USER_QUALITY_MANAGER),
        )
        validate_error(response, ERR_STALE_RECIPE_VERSION, 412)
        assert fab.read_change_request(notice["id"])["status"] == "SUBMITTED"

        # With the observed version the very same call is accepted.
        accepted = validate_success(
            fab.client.approve_change_request(
                notice["id"],
                approve_payload(recipe["version"]),
                quality_manager_headers(USER_QUALITY_MANAGER),
            ),
            200,
        )
        assert_fields(
            accepted,
            status="APPROVED",
            approver_user_id=USER_QUALITY_MANAGER,
            pinned_recipe_revision=1,
        )


# --------------------------------------------------------------------------
# An out-of-sequence step whose tool type does not exist
# --------------------------------------------------------------------------


def _flow_whose_second_step_has_no_tool(fab):
    """A two-step flow whose polish step has no tool anywhere in the fab."""
    spec = LineSpec(
        recipes=[
            RecipeSpec("LITHO-100", "LITHO", 50.0, 100),
            RecipeSpec("CMP-100", "CMP", 30.0, 100),
        ],
        flow_code="FLOW-C",
        product_family="MEMORY_D1",
        steps=[
            StepSpec(10, "LITHO-1", 2.0, recipe_ix=0),
            StepSpec(20, "CMP-1", 2.0, recipe_ix=1),
        ],
        equipments=[EquipmentSpec("LITHO-1", "LITHO", 168.0, 0.0, 0.0)],
        chambers=[ChamberSpec("CH_L1", equipment_ix=0, recipe_ix=0)],
        planned_wafer_starts=10,
        capacity_budget_hours=100.0,
        lots=[LotSpec("LOT-003", 3, "STANDARD")],
    )
    return build_line(fab, spec)


class TestStepSequenceOutranksEmptyChamberPool:
    def test_the_sequence_violation_is_reported_before_the_pool_is_built(self, fab):
        """One track-in trips both rule 31 and rule 39; only rule 31 is answered.

        PRD: "And the step must be the lot's *next* operation: its `step_seq`
        must be the lowest `step_seq` in the lot's flow that is strictly greater
        than the lot's `current_step_seq`. Skipping ahead or repeating a
        completed step is rejected with `ERR_STEP_SEQUENCE_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/step_sequence_violation_outranks_empty_chamber_pool
        """
        env = _flow_whose_second_step_has_no_tool(fab)
        operator_id = env.operators[0]["id"]

        assert_hours(env.flow["total_standard_hours"], 4.0, "total_standard_hours")
        assert env.plan["commitment_tier"] == "TIER_0"
        assert_hours(env.plan["committed_hours"], 40.00, "committed_hours")
        # Nothing in the fab is set up on the polish recipe.
        assert fab.count(
            fab.client.list_chambers(
                quality_manager_headers(),
                {"qualified_recipe_id": env.recipes[1]["id"]},
            )
        ) == 0

        response = fab.client.create_step_run(
            step_run_payload(env.lots[0]["id"], env.steps[1]["id"], operator_id),
            make_operator_headers(operator_id),
        )

        body = validate_error(response, ERR_STEP_SEQUENCE_VIOLATION, 422)
        assert body["error_id"] != ERR_NO_QUALIFIED_CHAMBER
        assert_wins_over(ERR_STEP_SEQUENCE_VIOLATION, ERR_NO_QUALIFIED_CHAMBER)

        assert fab.count(
            fab.client.list_step_runs(
                make_operator_headers(operator_id), {"lot_id": env.lots[0]["id"]}
            )
        ) == 0
        assert_lot_state(
            fab.read_lot(env.lots[0]["id"]), flow_state="RELEASED", current_step_seq=0
        )

    def test_the_empty_pool_really_was_the_losing_check(self, fab):
        """Once the same step is in sequence, the missing tool answers instead.

        PRD: "If the candidate set is empty because every otherwise-eligible
        chamber's qualification has lapsed, the rejection is
        `ERR_CHAMBER_QUAL_EXPIRED`; if it is empty for any other reason, the
        rejection is `ERR_NO_QUALIFIED_CHAMBER`, and in either case no run is
        created."

        Design: Difficulty/priority_pair_validation_conflict/step_sequence_violation_outranks_empty_chamber_pool
        """
        env = _flow_whose_second_step_has_no_tool(fab)
        operator_id = env.operators[0]["id"]

        # Walk the lot legitimately through the litho step first.
        complete_step(fab, env, step_ix=0, lot_ix=0)
        assert_lot_state(
            fab.read_lot(env.lots[0]["id"]), flow_state="IN_PROCESS", current_step_seq=10
        )

        response = fab.client.create_step_run(
            step_run_payload(env.lots[0]["id"], env.steps[1]["id"], operator_id),
            make_operator_headers(operator_id),
        )

        validate_error(response, ERR_NO_QUALIFIED_CHAMBER, 409)
        # Only the completed litho run exists; the polish step created nothing.
        assert fab.count(
            fab.client.list_step_runs(
                make_operator_headers(operator_id), {"step_id": env.steps[1]["id"]}
            )
        ) == 0
        assert_lot_state(
            fab.read_lot(env.lots[0]["id"]), flow_state="IN_PROCESS", current_step_seq=10
        )
