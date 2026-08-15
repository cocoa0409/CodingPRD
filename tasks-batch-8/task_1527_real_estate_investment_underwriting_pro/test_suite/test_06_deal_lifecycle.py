"""Deal lifecycle: reopen loop, supersede cascades, terminal states (PRD §3.1,
§3.4, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_deal,
    assert_scenario,
    create_memo_fresh,
    create_scenario_fresh,
    make_asset_manager_headers,
    setup_approved_deal,
    setup_computed_scenario,
    setup_underwriting_env,
    validate_error,
    validate_success,
)


def test_reopen_loop_returns_to_draft_and_back(api, analyst_headers):
    """PRD §3.1: "If the team decides to step back, the analyst may reopen the
    deal, transitioning it `UNDERWRITING → DRAFT`."
    PRD §3.1: "Submitting for underwriting — transitioning the deal `DRAFT →
    UNDERWRITING` — is an analyst-only action that requires `X-User-ID` to equal
    `deal.analyst_id`."
    The lifecycle is a loop, not a pipeline: the deal can re-enter UNDERWRITING
    after a reopen.

    Design: Difficulty/non_linear_state_machine/deal_reopen_loop_underwriting_to_draft_and_back
    """
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-SM1"})
    deal_id = env["deal"]["id"]
    assert env["deal"]["status"] == "UNDERWRITING"

    reopened = validate_success(api.reopen_deal(deal_id, analyst_headers), 200)
    assert_deal(reopened)
    assert reopened["status"] == "DRAFT", (
        f"reopen must loop back to DRAFT, got {reopened['status']}"
    )

    resubmitted = validate_success(
        api.submit_underwriting(
            deal_id,
            {**analyst_headers, "X-AssetManager-ID": env["asset_manager_id"]},
        ),
        200,
    )
    assert resubmitted["status"] == "UNDERWRITING", (
        f"cycle must complete back at UNDERWRITING, got {resubmitted['status']}"
    )


def test_reopen_loop_increments_version_each_step(api, analyst_headers):
    """PRD §2.4: "`version` is an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of the resource."
    PRD §3.1: "On a successful reopen, every `Scenario` belonging to the deal
    that is currently in `COMPUTED` status is cascaded to `SUPERSEDED` with
    `superseded_by_id` set to null — marking them for re-compute — and the
    deal's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/deal_reopen_loop_underwriting_to_draft_and_back
    """
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-SM1V"})
    deal_id = env["deal"]["id"]
    v_underwriting = env["deal"]["version"]

    reopened = validate_success(api.reopen_deal(deal_id, analyst_headers), 200)
    assert reopened["version"] == v_underwriting + 1, (
        f"reopen must increment version by exactly 1: {v_underwriting} -> {reopened['version']}"
    )

    resubmitted = validate_success(
        api.submit_underwriting(
            deal_id,
            {**analyst_headers, "X-AssetManager-ID": env["asset_manager_id"]},
        ),
        200,
    )
    assert resubmitted["version"] == v_underwriting + 2, (
        f"second submit must increment version by exactly 1 more: "
        f"{v_underwriting} -> {resubmitted['version']}"
    )


def test_reopen_supersedes_computed_scenarios(api, analyst_headers):
    """PRD §3.1: "On a successful reopen, every `Scenario` belonging to the deal
    that is currently in `COMPUTED` status is cascaded to `SUPERSEDED` with
    `superseded_by_id` set to null — marking them for re-compute — and the
    deal's `version` increments by 1."
    PRD §3.4: "A scenario in `COMPUTED` status may later be cascaded to
    `SUPERSEDED` (the terminal state for a scenario) by one of three events: a
    deal reopen, a deal submit-to-IC (which supersedes every other `COMPUTED`
    scenario besides the one pinned to the memo), or the computation of a newer
    `BASE` scenario on the same deal."

    Design: Difficulty/non_linear_state_machine/scenario_supersede_cascade_from_deal_reopen
    """
    env = setup_computed_scenario(deal_overrides={"deal_code": "D-SM2"})
    scenario_id = env["scenario"]["id"]
    assert env["scenario"]["status"] == "COMPUTED"

    deal = validate_success(api.reopen_deal(env["deal"]["id"], analyst_headers), 200)
    assert deal["status"] == "DRAFT"

    after = validate_success(api.get_scenario(scenario_id, analyst_headers), 200)
    assert_scenario(after)
    assert after["status"] == "SUPERSEDED", (
        f"computed scenario must cascade to SUPERSEDED on reopen, got {after['status']}"
    )


def test_reopen_sets_superseded_by_null(api, analyst_headers):
    """PRD §3.4: "The cascade sets `superseded_by_id` per the triggering event —
    null on reopen, or the pinned scenario's id on submit-to-IC — and increments
    `Scenario.version` by 1."
    PRD §3.1: "On a successful reopen, every `Scenario` belonging to the deal
    that is currently in `COMPUTED` status is cascaded to `SUPERSEDED` with
    `superseded_by_id` set to null — marking them for re-compute — and the
    deal's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/scenario_supersede_cascade_from_deal_reopen
    """
    env = setup_computed_scenario(deal_overrides={"deal_code": "D-SM2N"})
    scenario_id = env["scenario"]["id"]
    v_computed = env["scenario"]["version"]

    validate_success(api.reopen_deal(env["deal"]["id"], analyst_headers), 200)
    after = validate_success(api.get_scenario(scenario_id, analyst_headers), 200)
    assert after["status"] == "SUPERSEDED"
    assert after["superseded_by_id"] is None, (
        f"reopen cascade leaves superseded_by_id null, got {after['superseded_by_id']!r}"
    )
    assert after["version"] == v_computed + 1, (
        f"cascade increments Scenario.version by 1: {v_computed} -> {after['version']}"
    )


def test_submit_underwriting_twice_rejected(api, analyst_headers):
    """PRD §3.1: "Submitting for underwriting — transitioning the deal `DRAFT →
    UNDERWRITING` — is an analyst-only action that requires `X-User-ID` to equal
    `deal.analyst_id`."
    PRD §2.8: "6. Target entity is in a state from which the requested transition
    is valid — otherwise `ERR_INVALID_STATE` (409)." — an already-UNDERWRITING
    deal is not in DRAFT, so the transition is not valid.

    Design: Corner/state_machines/deal_submit_underwriting_twice_returns_invalid_state
    """
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-INV1"})
    res = api.submit_underwriting(env["deal"]["id"], analyst_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_approved_deal_is_terminal(api, analyst_headers):
    """PRD §3.8: "`APPROVED` and `DEAD` are the terminal states of a deal."
    PRD §2.8: "6. Target entity is in a state from which the requested transition
    is valid — otherwise `ERR_INVALID_STATE` (409)." — reopen is defined from
    `UNDERWRITING` or `REJECTED` only, so an APPROVED deal cannot reopen.

    Design: Corner/state_machines/deal_approved_is_terminal_no_further_transitions
    """
    env = setup_approved_deal(deal_overrides={"deal_code": "D-TERM"})
    assert env["deal"]["status"] == "APPROVED"
    res = api.reopen_deal(env["deal"]["id"], analyst_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_mark_dead_from_underwriting_rejected(api, asset_manager_headers):
    """PRD §3.8: "Alternatively, the `AssetManager` may mark a rejected deal dead,
    transitioning it `REJECTED → DEAD`."
    PRD §2.8: "6. Target entity is in a state from which the requested transition
    is valid — otherwise `ERR_INVALID_STATE` (409)." — mark-dead is defined from
    `REJECTED` only, so an UNDERWRITING deal cannot be marked dead.

    Design: Corner/state_machines/deal_mark_dead_from_underwriting_returns_invalid_state
    """
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-MD"})
    res = api.mark_dead(env["deal"]["id"], asset_manager_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_submit_ic_pins_scenario_and_supersedes_others(api, analyst_headers):
    """PRD §3.7: "On success, three cascades fire: the deal's
    `current_scenario_id` is set to the memo's `scenario_id` (this is the
    version-pinning step — the scenario's outputs are now locked in as the basis
    for the IC decision); every other `COMPUTED` scenario on the same deal is
    transitioned to `SUPERSEDED` with `superseded_by_id` set to the pinned
    scenario's id; and the memo itself transitions `SUBMITTED → UNDER_VOTE`."

    Design: Corner/cross_cutting_complexity_layers/cascade_side_effects_deal_submit_ic_supersedes_other_scenarios
    """
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-CSC"})
    s1 = create_scenario_fresh(env["deal"]["id"], env["assumption"]["id"],
                               scenario_kind="BASE", occupancy_stress_pct=90)
    s1 = validate_success(api.compute_scenario(s1["id"], analyst_headers), 200)
    s2 = create_scenario_fresh(env["deal"]["id"], env["assumption"]["id"],
                               scenario_kind="DOWNSIDE", occupancy_stress_pct=80)
    s2 = validate_success(api.compute_scenario(s2["id"], analyst_headers), 200)
    assert s1["status"] == "COMPUTED" and s2["status"] == "COMPUTED"

    memo = create_memo_fresh(env["deal"]["id"], s1["id"])
    validate_success(api.submit_ic_memo(memo["id"], analyst_headers), 200)
    deal = validate_success(
        api.submit_ic(env["deal"]["id"],
                      make_asset_manager_headers(env["asset_manager_id"])),
        200,
    )

    assert deal["status"] == "IC_REVIEW"
    assert deal["current_scenario_id"] == s1["id"], (
        f"submit-ic must pin the memo's scenario, got {deal['current_scenario_id']!r}"
    )
    s2_after = validate_success(api.get_scenario(s2["id"], analyst_headers), 200)
    assert s2_after["status"] == "SUPERSEDED", (
        f"other computed scenario must be superseded, got {s2_after['status']}"
    )
    assert s2_after["superseded_by_id"] == s1["id"], (
        f"superseded_by_id must point at the pinned scenario, got {s2_after['superseded_by_id']!r}"
    )
    s1_after = validate_success(api.get_scenario(s1["id"], analyst_headers), 200)
    assert s1_after["status"] == "COMPUTED", "pinned scenario stays COMPUTED"
    memo_after = validate_success(api.get_ic_memo(memo["id"], analyst_headers), 200)
    assert memo_after["status"] == "UNDER_VOTE"


def test_write_then_read_immediately_consistent(api, analyst_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.1: "Submitting for underwriting — transitioning the deal `DRAFT →
    UNDERWRITING` — is an analyst-only action that requires `X-User-ID` to equal
    `deal.analyst_id`. As part of that transition the server reads the
    `X-AssetManager-ID` header and writes it onto `deal.asset_manager_id`,
    formally handing the deal off to a senior reviewer."

    Design: Corner/consistency_model/write_then_read_returns_updated_value_immediately
    """
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-IMM2"}, submit=False)
    deal_id = env["deal"]["id"]
    in_response = validate_success(
        api.submit_underwriting(
            deal_id, {**analyst_headers, "X-AssetManager-ID": env["asset_manager_id"]}
        ),
        200,
    )
    assert in_response["status"] == "UNDERWRITING", (
        f"mutation response must carry the updated resource, got {in_response['status']}"
    )
    assert in_response["asset_manager_id"] == env["asset_manager_id"]
    on_read = validate_success(api.get_deal(deal_id, analyst_headers), 200)
    assert on_read["status"] == "UNDERWRITING", (
        f"subsequent read must reflect the write immediately, got {on_read['status']}"
    )
    assert on_read["version"] == in_response["version"]
