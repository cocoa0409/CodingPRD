"""Legionella risk plans: validation cycle, suspend/return-to-draft cycle,
the corrective-approval posture gate, and the delinquency grace boundary."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_legionella_plan,
    make_chemist_headers,
    set_clock,
    setup_commissioned_asset,
    setup_pending_corrective_action,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]


def _commissioned_with_active_plan(account_name, interval_days=10):
    subtree = setup_commissioned_asset(account_name=account_name)
    plan = create_legionella_plan(subtree["asset"]["id"],
                                  validation_interval_days=interval_days)
    plan = validate_success(api_client.activate_legionella_plan(plan["id"], CHEMIST))
    assert plan["status"] == "ACTIVE"
    return subtree, plan


def test_plan_validate_returns_to_active_and_refreshes_due_date(api):
    """PRD §3.7: "validating a plan in `VALIDATION_DUE` or `DELINQUENT`
    returns it to `ACTIVE`, stamps `last_validated_at` with the current
    clock, refreshes `validation_due_at` to the current clock plus
    `validation_interval_days` days". "When the logical clock reaches or
    passes `validation_due_at`, the sweep of §2.4 moves the plan from
    `ACTIVE` to `VALIDATION_DUE` automatically."

    Design: Difficulty/non_linear_state_machine/legionella_plan_cyclic_validate_and_return_to_draft
    """
    subtree, plan = _commissioned_with_active_plan("Legio Co", interval_days=10)
    # Activated at 2026-08-01 -> due 2026-08-11; advancing past it sweeps to VALIDATION_DUE.
    set_clock("2026-08-12T00:00:00Z")
    due = validate_success(api_client.get_legionella_plan(plan["id"], CHEMIST))
    assert due["status"] == "VALIDATION_DUE"

    validated = validate_success(api_client.validate_legionella_plan(plan["id"], CHEMIST))
    assert validated["status"] == "ACTIVE"
    assert validated["last_validated_at"].startswith("2026-08-12T00:00:00")
    assert validated["validation_due_at"].startswith("2026-08-22T00:00:00")


def test_plan_suspend_and_return_to_draft_clears_frozen_posture(api):
    """PRD §3.7: "Suspension is the `AccountManager`'s instrument and applies
    from `ACTIVE`, `VALIDATION_DUE`, or `DELINQUENT` (any other state is
    `ERR_INVALID_STATE`): the plan moves to `SUSPENDED` and the asset's
    posture is recomputed to `FROZEN`". "a `WaterChemist` may return it to
    `DRAFT`, which recomputes the asset's posture and may clear the `FROZEN`
    hold."

    Design: Difficulty/non_linear_state_machine/legionella_plan_cyclic_validate_and_return_to_draft
    """
    subtree, plan = _commissioned_with_active_plan("Legio Co 2", interval_days=10)
    set_clock("2026-08-12T00:00:00Z")
    validate_success(api_client.validate_legionella_plan(plan["id"], CHEMIST))

    suspended = validate_success(api_client.suspend_legionella_plan(plan["id"], MANAGER))
    assert suspended["status"] == "SUSPENDED"
    frozen = validate_success(api_client.get_asset(subtree["asset"]["id"], CHEMIST))
    assert frozen["posture"] == "FROZEN"

    drafted = validate_success(api_client.return_plan_to_draft(plan["id"], CHEMIST))
    assert drafted["status"] == "DRAFT"
    assert drafted["last_validated_at"].startswith("2026-08-12T00:00:00")
    asset_after = validate_success(api_client.get_asset(subtree["asset"]["id"], CHEMIST))
    assert asset_after["posture"] == "COMPLIANT", (
        "with no other driver holding it down, return-to-draft recomputes posture to COMPLIANT"
    )


def test_corrective_approve_blocked_while_plan_suspended(api):
    """PRD §2.6 tier 7: "any operation gated by a `FROZEN` asset posture —
    arriving at a stop, approving a corrective action, recording a water test
    result — fails with `ERR_ASSET_FROZEN`." PRD §3.7: "the plan moves to
    `SUSPENDED` and the asset's posture is recomputed to `FROZEN`".

    Design: Difficulty/cross_entity_state_dependency/corrective_approve_requires_legionella_plan_not_suspended
    """
    subtree = setup_pending_corrective_action(recorder_id="chemist-recorder-1")
    action, station = subtree["action"], subtree["station"]
    plan = create_legionella_plan(subtree["asset"]["id"], validation_interval_days=10)
    validate_success(api_client.activate_legionella_plan(plan["id"], CHEMIST))
    validate_success(api_client.suspend_legionella_plan(plan["id"], MANAGER))

    station = validate_success(
        api_client.get_feed_station(subtree["station"]["id"], CHEMIST)
    )
    resp = api_client.approve_corrective_action(
        action["id"],
        {
            "setpoint_delta_ml_per_min": 1.0,
            "rationale": "x",
            "expected_feed_station_version": station["version"],
        },
        make_chemist_headers("chemist-approver-2"),
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_FROZEN)
    assert resp.status_code == 409

    after = validate_success(api_client.get_corrective_action(action["id"], CHEMIST))
    assert after["status"] == "PENDING"


def test_corrective_approve_succeeds_after_plan_returned_to_draft(api):
    """PRD §3.7: "a `WaterChemist` may return it to `DRAFT`, which recomputes
    the asset's posture and may clear the `FROZEN` hold." PRD §3.5:
    "Approval — `PENDING` → `APPROVED`".

    Design: Difficulty/cross_entity_state_dependency/corrective_approve_requires_legionella_plan_not_suspended
    """
    subtree = setup_pending_corrective_action(recorder_id="chemist-recorder-1")
    action = subtree["action"]
    plan = create_legionella_plan(subtree["asset"]["id"], validation_interval_days=10)
    validate_success(api_client.activate_legionella_plan(plan["id"], CHEMIST))
    validate_success(api_client.suspend_legionella_plan(plan["id"], MANAGER))

    station = validate_success(api_client.get_feed_station(subtree["station"]["id"], CHEMIST))
    blocked = api_client.approve_corrective_action(
        action["id"],
        {
            "setpoint_delta_ml_per_min": 1.0,
            "rationale": "x",
            "expected_feed_station_version": station["version"],
        },
        make_chemist_headers("chemist-approver-2"),
    )
    validate_error(blocked, ApiErrorId.ERR_ASSET_FROZEN)

    validate_success(api_client.return_plan_to_draft(plan["id"], CHEMIST))
    station = validate_success(api_client.get_feed_station(subtree["station"]["id"], CHEMIST))
    approved = validate_success(
        api_client.approve_corrective_action(
            action["id"],
            {
                "setpoint_delta_ml_per_min": 1.0,
                "rationale": "x",
                "expected_feed_station_version": station["version"],
            },
            make_chemist_headers("chemist-approver-2"),
        )
    )
    assert approved["status"] == "APPROVED"


def test_legionella_delinquent_requires_grace_elapsed(api):
    """PRD §3.7: "a `WaterChemist` may declare the plan delinquent —
    `VALIDATION_DUE` → `DELINQUENT` — but only after a fourteen-day grace
    period: the current clock must be strictly later than `validation_due_at`
    plus 14 days, failing earlier with `ERR_GRACE_NOT_ELAPSED`. Declaring
    delinquency recomputes the asset's posture to `NON_COMPLIANT`."

    Design: Corner/validations/legionella_delinquent_requires_grace_elapsed
    """
    subtree, plan = _commissioned_with_active_plan("Grace Co", interval_days=10)
    # Due 2026-08-11; clock 2026-08-21 sweeps the plan to VALIDATION_DUE but
    # is only 10 days past due — the 14-day grace has not elapsed.
    set_clock("2026-08-21T00:00:00Z")
    due = validate_success(api_client.get_legionella_plan(plan["id"], CHEMIST))
    assert due["status"] == "VALIDATION_DUE"

    resp = api_client.declare_plan_delinquent(plan["id"], CHEMIST)
    validate_error(resp, ApiErrorId.ERR_GRACE_NOT_ELAPSED)
    assert resp.status_code == 422

    # 2026-08-26 is strictly later than due + 14 days (2026-08-25).
    set_clock("2026-08-26T00:00:00Z")
    delinquent = validate_success(api_client.declare_plan_delinquent(plan["id"], CHEMIST))
    assert delinquent["status"] == "DELINQUENT"
    asset_after = validate_success(api_client.get_asset(subtree["asset"]["id"], CHEMIST))
    assert asset_after["posture"] == "NON_COMPLIANT"
