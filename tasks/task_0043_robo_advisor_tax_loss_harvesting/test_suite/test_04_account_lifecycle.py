"""Account state machine, questionnaire acceptance, re-profile, and closure.

Queue A: non_linear_state_machine/account_active_rebalance_due_freeze_branch_cycle,
transitive_cascade/questionnaire_accept_supersede_then_reassign_model_depth2,
cross_entity_state_dependency/questionnaire_accept_blocked_by_retired_model.
Queue B (state_machines): accept_already_accepted_questionnaire_returns_invalid_state,
harvest_execute_on_closed_account_terminal_lockdown, account_close_with_open_lots_rejected.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_account_payload,
    create_questionnaire_payload,
    create_harvest_event_payload,
    set_clock,
    create_model,
    create_security,
    create_active_account,
    open_tax_lot,
    get_account,
    setup_rebalance_due_account,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ─── account_active_rebalance_due_freeze_branch_cycle ───────────────
def test_drift_at_threshold_flips_active_to_rebalance_due(api):
    """PRD §2.7: "An account becomes `REBALANCE_DUE` exactly when its `max_drift_pct` is greater than or equal to the model's `drift_threshold_pct`. The boundary is inclusive: a drift equal to the threshold triggers the flag, a drift one point below it does not."

    Design: Difficulty/non_linear_state_machine/account_active_rebalance_due_freeze_branch_cycle
    """
    s = setup_rebalance_due_account("2026-04-01T00:00:00.000Z", "cyc@x.com")
    acct = s["account"]
    # US 70000 of 100000 invested = 70% vs target 60 -> drift 10 >= 5.
    assert acct["max_drift_pct"] == 10
    assert acct["status"] == "REBALANCE_DUE"


def test_freeze_then_unfreeze_restores_rebalance_due(api):
    """PRD §3.7: "A compliance operator may freeze an `ACTIVE` or `REBALANCE_DUE` account, setting its `status` to `FROZEN` and incrementing its `version`; while frozen, an account blocks all harvests and rebalances." PRD §3.7: "Unfreezing a frozen account recomputes its `max_drift_pct` and lands it in `REBALANCE_DUE` if that drift is at or above the model's `drift_threshold_pct`, otherwise in `ACTIVE`, again incrementing the account's `version`."

    Design: Difficulty/non_linear_state_machine/account_active_rebalance_due_freeze_branch_cycle
    """
    s = setup_rebalance_due_account("2026-04-01T00:00:00.000Z", "cyc2@x.com")
    acct_id = s["account"]["id"]
    frozen = get_success_data(api.freeze_account(acct_id, COMPLIANCE))
    assert frozen["status"] == "FROZEN"
    unfrozen = get_success_data(api.unfreeze_account(acct_id, COMPLIANCE))
    # Drift still 10 >= 5, so unfreeze lands back in REBALANCE_DUE, not ACTIVE.
    assert unfrozen["status"] == "REBALANCE_DUE"


# ─── questionnaire_accept_supersede_then_reassign_model_depth2 ───────
def _setup_reprofiled_account(api, email):
    set_clock("2026-07-01T00:00:00.000Z")
    create_model(
        name="Aggressive",
        min_risk_score=70,
        max_risk_score=100,
        targets=[{"asset_class": "US_EQUITY", "target_pct": 100}],
    )
    con = create_model(
        name="Conservative",
        min_risk_score=0,
        max_risk_score=40,
        targets=[{"asset_class": "BOND", "target_pct": 100}],
    )
    acct = get_success_data(
        api.create_account(create_account_payload(client_email=email), ADVISOR)
    )
    q1 = get_success_data(
        api.create_questionnaire(
            create_questionnaire_payload(
                account_id=acct["id"], horizon_years=30, loss_tolerance=9, liquidity_need=1, income_band=8
            ),
            ADVISOR,
        )
    )
    get_success_data(api.accept_questionnaire(q1["id"], ADVISOR))
    q2 = get_success_data(
        api.create_questionnaire(
            create_questionnaire_payload(
                account_id=acct["id"], horizon_years=5, loss_tolerance=2, liquidity_need=8, income_band=3
            ),
            ADVISOR,
        )
    )
    return acct, q1, q2, con


def test_reprofile_accept_supersedes_prior_questionnaire(api):
    """PRD §3.2: "When a questionnaire is accepted for an account that is already `ACTIVE` (a re-profile), any prior `ACCEPTED` questionnaire for that account is moved to `SUPERSEDED`, the account's `model_portfolio_id` and `risk_score` are updated from the new questionnaire".

    Design: Difficulty/transitive_cascade/questionnaire_accept_supersede_then_reassign_model_depth2
    """
    acct, q1, q2, con = _setup_reprofiled_account(api, "reprof@x.com")
    accepted_q2 = get_success_data(api.accept_questionnaire(q2["id"], ADVISOR))
    assert accepted_q2["status"] == "ACCEPTED"
    q1_after = get_success_data(api.get_questionnaire(q1["id"], ADVISOR))
    assert q1_after["status"] == "SUPERSEDED"


def test_reprofile_accept_repoints_account_model_and_risk_score(api):
    """PRD §3.2: "When a questionnaire is accepted for an account that is already `ACTIVE` (a re-profile), any prior `ACCEPTED` questionnaire for that account is moved to `SUPERSEDED`, the account's `model_portfolio_id` and `risk_score` are updated from the new questionnaire".

    Design: Difficulty/transitive_cascade/questionnaire_accept_supersede_then_reassign_model_depth2
    """
    acct, q1, q2, con = _setup_reprofiled_account(api, "reprof2@x.com")
    get_success_data(api.accept_questionnaire(q2["id"], ADVISOR))
    acct_after = get_account(acct["id"])
    # q2 scores 11 (raw 10.8333 -> 11), assigned to the conservative [0,40] model.
    assert acct_after["model_portfolio_id"] == con["id"]
    assert acct_after["risk_score"] == 11


# ─── questionnaire_accept_blocked_by_retired_model ──────────────────
def _setup_retired_model_questionnaire(api, email):
    set_clock("2026-03-15T00:00:00.000Z")
    model = create_model(name="RetMe", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    acct = get_success_data(
        api.create_account(create_account_payload(client_email=email), ADVISOR)
    )
    q = get_success_data(
        api.create_questionnaire(create_questionnaire_payload(account_id=acct["id"]), ADVISOR)
    )
    get_success_data(api.retire_model_portfolio(model["id"], ADVISOR))
    return acct, q, model


def test_accept_questionnaire_with_retired_model_rejected(api):
    """PRD §3.2: "Acceptance is permitted ... only while the model named by its `assigned_model_portfolio_id` is still active; accepting a questionnaire whose assigned model has been retired is rejected with `ERR_MODEL_RETIRED`."

    Design: Difficulty/cross_entity_state_dependency/questionnaire_accept_blocked_by_retired_model
    """
    acct, q, model = _setup_retired_model_questionnaire(api, "xdep2@x.com")
    res = api.accept_questionnaire(q["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_MODEL_RETIRED.value)


def test_retired_model_accept_leaves_account_pending_profile(api):
    """PRD §3.2: "accepting a questionnaire whose assigned model has been retired is rejected with `ERR_MODEL_RETIRED`." PRD §3.2: "A freshly opened account starts in `PENDING_PROFILE` status".

    Design: Difficulty/cross_entity_state_dependency/questionnaire_accept_blocked_by_retired_model
    """
    acct, q, model = _setup_retired_model_questionnaire(api, "xdep2b@x.com")
    api.accept_questionnaire(q["id"], ADVISOR)
    acct_after = get_account(acct["id"])
    assert acct_after["status"] == "PENDING_PROFILE"


# ─── Queue B state_machine corners ──────────────────────────────────
def test_accept_already_accepted_questionnaire_returns_invalid_state(api):
    """PRD §3.2: "Acceptance is permitted only while the questionnaire is in `SCORED` status — accepting a questionnaire that is not `SCORED` is rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/accept_already_accepted_questionnaire_returns_invalid_state
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(name="AA", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="aa@x.com"), ADVISOR)
    )
    q = get_success_data(
        api.create_questionnaire(create_questionnaire_payload(account_id=acct["id"]), ADVISOR)
    )
    get_success_data(api.accept_questionnaire(q["id"], ADVISOR))
    res = api.accept_questionnaire(q["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_harvest_propose_on_closed_account_blocked(api):
    """PRD §3.8: "`CLOSED` is terminal and blocks all further mutation of the account." PRD §3.4: "an account that is `FROZEN`, `CLOSED`, or `PENDING_PROFILE` cannot be harvested, and the attempt is rejected with `ERR_ACCOUNT_NOT_OPERABLE`."

    Design: Corner/state_machines/harvest_execute_on_closed_account_terminal_lockdown
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(name="CL", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    sec1 = create_security("CL1", "US_EQUITY", 10000)
    sec2 = create_security(
        "CL2", "US_EQUITY", 4000, correlated_with=[{"ticker": "CL1", "correlation": 0.05}]
    )
    acct = create_active_account("closed@x.com")
    closed = get_success_data(api.close_account(acct["id"], ADVISOR))
    assert closed["status"] == "CLOSED"
    # A real source lot on a separate operable account: existence resolves
    # (PRD §2.5) so the closed-account operability gate (PRD §2.10) fires
    # before the §3.4 lot-belongs-to-account screen.
    other = create_active_account("closed-other@x.com")
    src_lot = open_tax_lot(other["id"], sec1["id"], 5, 60000)
    res = api.create_harvest_event(
        create_harvest_event_payload(
            account_id=acct["id"],
            source_lot_id=src_lot["id"],
            replacement_security_id=sec2["id"],
            expected_account_version=closed["version"],
        ),
        ADVISOR,
    )
    validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_OPERABLE.value)


def test_close_account_with_open_lots_rejected(api):
    """PRD §3.8: "Closing requires that no `OPEN` tax lot remains for the account; an attempt to close while any open lot survives is rejected with `ERR_OPEN_LOTS_REMAIN`."

    Design: Corner/state_machines/account_close_with_open_lots_rejected
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(name="OL", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    sec = create_security("OL1", "US_EQUITY", 10000)
    acct = create_active_account("openlots@x.com")
    open_tax_lot(acct["id"], sec["id"], 2, 20000)
    res = api.close_account(acct["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_OPEN_LOTS_REMAIN.value)
    after = get_account(acct["id"])
    assert after["status"] == "ACTIVE"
