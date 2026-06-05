"""Options-approval and margin-upgrade workflow branching, suitability, and precedence."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    open_and_activate_account, grant_options_level, submit_options_approval,
    draft_options_approval, submit_margin_upgrade, upgrade_margin, get_account,
    CO_SUBMITTER, CO_DECIDER,
    make_compliance_officer_headers,
)


def test_options_approval_branching_approve_vs_reject(api):
    """PRD §3.3: "When approval succeeds the application moves to `APPROVED`,
    the deciding officer is recorded as `decided_by_user_id`, the parent
    account's `options_level` is set to the `requested_level` as a cross-entity
    write, and the account's `version` increments by one." PRD §3.3: "Rejecting
    a submitted application moves it to `REJECTED`, records the deciding officer
    as `decided_by_user_id`, and sets `rejection_reason` from the request body.
    Rejection enforces only the segregation-of-duties check and does not touch
    the account's options level or version."

    Design: Difficulty/non_linear_state_machine/options_approval_branching_approve_vs_reject
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    grant_options_level(acct["id"], 1)  # one approval approved -> level 1

    oa2 = submit_options_approval(acct["id"], 2)
    resp = api.reject_options_approval(oa2["id"], {"rejection_reason": "documentation incomplete"}, CO_DECIDER)
    rejected = validate_success(resp)
    assert rejected["status"] == "REJECTED"

    approved = validate_success(api.list_options_approvals(CO_SUBMITTER, {"account_id": acct["id"]}))
    statuses = {a["status"] for a in approved}
    assert "APPROVED" in statuses and "REJECTED" in statuses
    assert get_account(acct["id"])["options_level"] == 1


def test_options_approve_sets_account_level(api):
    """PRD §3.3: "the parent account's `options_level` is set to the
    `requested_level` as a cross-entity write, and the account's `version`
    increments by one."

    Design: Difficulty/non_linear_state_machine/options_approval_branching_approve_vs_reject
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    oa1 = submit_options_approval(acct["id"], 1)
    resp = api.approve_options_approval(oa1["id"], CO_DECIDER)
    data = validate_success(resp)
    assert data["status"] == "APPROVED"
    assert get_account(acct["id"])["options_level"] == 1


def test_immediate_visibility_of_options_level_after_approve(api):
    """PRD §3.3: "the parent account's `options_level` is set to the
    `requested_level` as a cross-entity write, and the account's `version`
    increments by one."

    GET /accounts/{id} immediately after approve shows options_level==1.

    Design: Corner/consistency_model/immediate_visibility_of_options_level_after_approve
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    oa1 = submit_options_approval(acct["id"], 1)
    validate_success(api.approve_options_approval(oa1["id"], CO_DECIDER))
    data = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert data["options_level"] == 1


def test_segregation_beats_suitability_on_approve(api):
    """PRD §3.3: "the deciding officer's `X-User-ID` must differ from the
    recorded `submitted_by_user_id`; if the same user who submitted attempts to
    decide, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`." PRD §3.3:
    "On these two parallel decisions the precedence is segregation of duties
    first, then — for approval only — the suitability gate."

    The level-4 submitter (combined 12000000, experience GOOD also fails the L4
    suitability gate) approving their own application gets
    ERR_SEGREGATION_OF_DUTIES, not ERR_SUITABILITY_NOT_MET.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_suitability_on_approve
    """
    acct = open_and_activate_account(
        liquid_net_worth_cents=6_000_000, annual_income_cents=6_000_000,
        investment_experience="GOOD", cash_balance_cents=1_000_000)
    grant_options_level(acct["id"], 3)  # L1-L3 pass for combined 12000000, exp GOOD

    oa4 = submit_options_approval(acct["id"], 4)
    # co_1 is the submitter (CO_SUBMITTER); approving as co_1 violates segregation.
    resp = api.approve_options_approval(oa4["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_suitability_gate_passes_at_exact_threshold(api):
    """PRD §3.7: "the combined figure of `liquid_net_worth_cents` plus
    `annual_income_cents` must be at least the level's minimum combined
    threshold: $0 for level 1, $50,000.00 (5,000,000 cents) for level 2". PRD
    §3.7: "the holder's `investment_experience`, ranked as `NONE` = 0,
    `LIMITED` = 1, `GOOD` = 2, and `EXTENSIVE` = 3, must be at least the level's
    minimum experience rank: 0 for level 1, 1 for level 2".

    combined==5000000 and exp_rank==1 (LIMITED) passes level 2: approval
    succeeds and options_level becomes 2.

    Design: Corner/calculations/suitability_gate_passes_at_exact_threshold
    """
    acct = open_and_activate_account(
        liquid_net_worth_cents=2_500_000, annual_income_cents=2_500_000,
        investment_experience="LIMITED", cash_balance_cents=1_000_000)
    grant_options_level(acct["id"], 1)
    oa2 = submit_options_approval(acct["id"], 2)
    resp = api.approve_options_approval(oa2["id"], CO_DECIDER)
    data = validate_success(resp)
    assert data["status"] == "APPROVED"
    assert get_account(acct["id"])["options_level"] == 2


def test_suitability_gate_fails_below_combined_threshold(api):
    """PRD §3.7: "the combined figure of `liquid_net_worth_cents` plus
    `annual_income_cents` must be at least the level's minimum combined
    threshold: $0 for level 1, $50,000.00 (5,000,000 cents) for level 2". PRD
    §3.7: "If either condition fails, the approval is rejected with
    `ERR_SUITABILITY_NOT_MET`."

    combined 4999999 (one cent below 5000000) for level 2 returns
    ERR_SUITABILITY_NOT_MET.

    Design: Corner/calculations/suitability_gate_fails_below_combined_threshold
    """
    acct = open_and_activate_account(
        liquid_net_worth_cents=2_499_999, annual_income_cents=2_500_000,
        investment_experience="EXTENSIVE", cash_balance_cents=1_000_000)
    grant_options_level(acct["id"], 1)
    oa2 = submit_options_approval(acct["id"], 2)
    resp = api.approve_options_approval(oa2["id"], CO_DECIDER)
    validate_error(resp, ApiErrorId.ERR_SUITABILITY_NOT_MET.value)


def test_options_approval_level_skip_rejected(api):
    """PRD §3.3: "the requested level must be exactly one rung above the
    account's current `options_level` — that is, `requested_level` must equal
    the account's `options_level` plus one — because levels are never skipped; a
    request that is not the next rung is rejected with `ERR_LEVEL_SKIP`."

    Submitting a level-2 approval on an account at options_level 0 returns
    ERR_LEVEL_SKIP.

    Design: Corner/state_machines/options_approval_level_skip_rejected
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    oa2 = draft_options_approval(acct["id"], 2)
    resp = api.submit_options_approval(oa2["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_LEVEL_SKIP.value)


def test_margin_upgrade_noop_same_type_rejected(api):
    """PRD §3.4: "The `requested_margin_type` must differ from the account's
    current `margin_type`, since upgrading to the agreement already in force is
    a no-op rejected with `ERR_MARGIN_NOOP`."

    After the account is already REG_T, a new REG_T upgrade submit returns
    ERR_MARGIN_NOOP.

    Design: Corner/state_machines/margin_upgrade_noop_same_type_rejected
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    upgrade_margin(acct["id"], "REG_T")
    mu2 = validate_success(api.create_margin_upgrade(
        {"account_id": acct["id"], "requested_margin_type": "REG_T"}, CO_SUBMITTER),
        expected_status=201)
    resp = api.submit_margin_upgrade(mu2["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_MARGIN_NOOP.value)


def test_pma_upgrade_below_equity_minimum_rejected(api):
    """PRD §3.4: "if the requested type is `PMA`, the account's `equity_cents`
    must be at least the Portfolio Margin equity floor of $150,000.00
    (15,000,000 cents); an account below that floor is rejected with
    `ERR_PMA_EQUITY_MINIMUM`."

    A PMA submit with equity 1000000 (< 15000000) returns
    ERR_PMA_EQUITY_MINIMUM.

    Design: Corner/state_machines/pma_upgrade_below_equity_minimum_rejected
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    mu = validate_success(api.create_margin_upgrade(
        {"account_id": acct["id"], "requested_margin_type": "PMA"}, CO_SUBMITTER),
        expected_status=201)
    resp = api.submit_margin_upgrade(mu["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_PMA_EQUITY_MINIMUM.value)


def test_segregation_blocks_self_approval_even_when_suitable(api):
    """PRD §3.3: "the deciding officer's `X-User-ID` must differ from the
    recorded `submitted_by_user_id`; if the same user who submitted attempts to
    decide, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    A level-1 application (suitability trivially met: combined threshold $0,
    exp_rank 0) still cannot be self-approved by its submitter — segregation of
    duties fires first.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_suitability_on_approve
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    oa1 = submit_options_approval(acct["id"], 1)
    # CO_SUBMITTER submitted; approving as the same user violates segregation.
    resp = api.approve_options_approval(oa1["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
