"""Withdrawal, consolidation and the terminal cascade that follows a settlement."""

from test_helpers import (
    ApiErrorId,
    assert_instant,
    authorize_offer,
    draft_offer,
    file_grievance,
    grievance_step_payload,
    read_grievance,
    schedule_step,
    setup_base,
    setup_grievance,
    setup_selected_arbitrator_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_consolidation_folds_the_remedy_figures_into_the_surviving_case(api, analyst_headers):
    """PRD §3.5: "On consolidation the withdrawing grievance's `consolidated_into_id` is set
    to the survivor's identifier, the survivor **absorbs** the remedy figures — its
    `remedy_requested_cents` grows by the consolidated grievance's `remedy_requested_cents`
    and its `back_pay_hours_claimed` grows by the consolidated grievance's
    `back_pay_hours_claimed` — and the survivor's own `version` increments by 1."

    Design: Corner/state_machines/consolidation_moves_remedy_cancels_steps_and_voids_offers
    """
    ctx = setup_base()
    lead = file_grievance(
        ctx, statement="Lead case", remedy_requested_cents=100_000, back_pay_hours_claimed=10
    )
    companion = file_grievance(
        ctx, statement="Companion case", remedy_requested_cents=40_000, back_pay_hours_claimed=6
    )

    consolidated = validate_success(
        api.withdraw_grievance(
            companion["id"],
            {"reason": "Same facts as the lead case", "consolidated_into_grievance_id": lead["id"]},
            ctx["steward_headers"],
        ),
        200,
    )

    assert consolidated["status"] == "CONSOLIDATED"
    assert consolidated["consolidated_into_id"] == lead["id"]

    survivor = read_grievance(lead["id"])
    assert survivor["remedy_requested_cents"] == 140_000
    assert survivor["back_pay_hours_claimed"] == 16
    assert survivor["version"] == lead["version"] + 1

    rows, meta = validate_paginated(
        api.list_grievances(analyst_headers, params={"consolidated_into_id": lead["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == companion["id"]


def test_consolidation_cancels_open_steps_voids_offers_and_leaves_the_clause_counters(
    api, analyst_headers
):
    """PRD §3.5: "Whichever exit is taken, the same cascade runs. Every step of the
    grievance standing at `SCHEDULED` or `HELD` is transitioned to `CANCELLED`. Every
    settlement offer standing at `DRAFT` or `AUTHORIZED` is transitioned to `VOIDED`, which
    drops `cited_count` on any precedent those offers named."
    PRD §3.5: "Consolidated grievances are excluded from every clause counter and from both
    supervisor counters — the case is accounted for on the surviving grievance only — so the
    cited clause's `filed_count` observably drops by 1 on the next read after a
    consolidation."

    Design: Corner/state_machines/consolidation_moves_remedy_cancels_steps_and_voids_offers
    """
    ctx = setup_base()
    lead = file_grievance(ctx, statement="Lead case", remedy_requested_cents=100_000)
    companion = file_grievance(ctx, statement="Companion case", remedy_requested_cents=40_000)
    step = schedule_step(companion["id"], "2026-08-05T00:00:00Z")
    offer = draft_offer(
        companion["id"], headers=ctx["steward_headers"],
        offering_party="UNION", monetary_cents=30_000,
    )

    validate_success(
        api.withdraw_grievance(
            companion["id"],
            {"reason": "Same facts as the lead case", "consolidated_into_grievance_id": lead["id"]},
            ctx["steward_headers"],
        ),
        200,
    )

    steps, _ = validate_paginated(api.list_grievance_steps(companion["id"], analyst_headers))
    assert steps[0]["id"] == step["id"]
    assert steps[0]["status"] == "CANCELLED"

    assert validate_success(
        api.get_settlement_offer(offer["id"], analyst_headers), 200
    )["status"] == "VOIDED"

    clauses, _ = validate_paginated(
        api.list_contract_clauses(ctx["unit"]["id"], analyst_headers)
    )
    assert clauses[0]["filed_count"] == 1, "CONSOLIDATED rows leave the clause counters"

    supervisor = validate_success(
        api.get_employee(ctx["supervisor"]["id"], analyst_headers), 200
    )
    assert supervisor["open_grievance_count"] == 1
    assert supervisor["closed_grievance_count"] == 0


def test_a_withdrawn_grievance_refuses_every_further_act(api, analyst_headers):
    """PRD §3.5: "Once a grievance is `SETTLED`, `WITHDRAWN`, `CONSOLIDATED` or `CLOSED`,
    it is terminal. Its timeliness posture is frozen at the value it held at that moment,
    and any attempt to act on it — schedule a step, appeal it, demand arbitration, withdraw
    it again, or post an operator cost entry against it — is rejected with
    `ERR_INVALID_GRIEVANCE_STATE`."

    Design: Corner/state_machines/withdrawing_an_already_withdrawn_grievance_is_refused
    """
    ctx = setup_grievance()
    withdrawn = validate_success(
        api.withdraw_grievance(
            ctx["grievance"]["id"], {"reason": "Grievant resigned"}, ctx["steward_headers"]
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN"

    second_withdrawal = api.withdraw_grievance(
        ctx["grievance"]["id"], {"reason": "Withdrawing again"}, ctx["steward_headers"]
    )
    validate_error(second_withdrawal, ApiErrorId.ERR_INVALID_GRIEVANCE_STATE.value)

    step_attempt = api.create_grievance_step(
        ctx["grievance"]["id"], grievance_step_payload("2026-08-05T00:00:00Z"), analyst_headers
    )
    validate_error(step_attempt, ApiErrorId.ERR_INVALID_GRIEVANCE_STATE.value)

    assert read_grievance(ctx["grievance"]["id"])["status"] == "WITHDRAWN"
    _, meta = validate_paginated(
        api.list_grievance_steps(ctx["grievance"]["id"], analyst_headers)
    )
    assert meta["total_count"] == 0


def test_selection_saturates_the_arbitrator_at_the_engagement_ceiling(api, administrator_headers):
    """PRD §3.6: "Because the demand entered `ARBITRATOR_SELECTED`, the selected
    arbitrator's `active_case_count` rises by 1 and their `status` is re-derived, which
    flips them from `AVAILABLE` to `FULL` when the ceiling is reached."

    Design: Difficulty/compensating_invariant/arbitrator_capacity_restored_on_pre_hearing_settlement
    """
    ctx = setup_selected_arbitrator_case(chan_overrides={"max_concurrent_cases": 1})

    engaged = validate_success(
        api.get_arbitrator(ctx["chan"]["id"], administrator_headers), 200
    )
    assert engaged["active_case_count"] == 1
    assert engaged["status"] == "FULL"

    assert ctx["demand"]["status"] == "ARBITRATOR_SELECTED"
    assert ctx["demand"]["selected_arbitrator_id"] == ctx["chan"]["id"]

    rows, meta = validate_paginated(
        api.list_arbitration_demands(
            administrator_headers, params={"status": "ARBITRATOR_SELECTED"}
        )
    )
    assert meta["total_count"] == 1, "exactly one demand holds an engagement"
    assert rows[0]["id"] == ctx["demand"]["id"]


def test_accepting_a_settlement_settles_the_case_and_the_pending_demand(api, analyst_headers):
    """PRD §3.4: "`ACCEPT` moves the offer to `ACCEPTED` and settles the case: the grievance
    moves to `SETTLED` from whichever of `FILED`, `STEP_MEETING_SCHEDULED`,
    `AWAITING_RESPONSE`, `ANSWERED`, `APPEALED` or `ARBITRATION_DEMANDED` it occupied, its
    `settled_amount_cents` is set to the accepted offer's `exposure_cents`, and the terminal
    cascade of §3.5 fires."
    PRD §3.5: "The grievance goes to `SETTLED` rather than `WITHDRAWN` or `CONSOLIDATED`;
    every **other** offer standing at `DRAFT` or `AUTHORIZED` is voided while the accepted
    one stands at `ACCEPTED`; and any live arbitration demand goes to `SETTLED_PRE_HEARING`
    rather than to `WITHDRAWN`, again releasing the selected arbitrator and re-deriving that
    arbitrator's status."

    Design: Difficulty/compensating_invariant/arbitrator_capacity_restored_on_pre_hearing_settlement
    """
    ctx = setup_selected_arbitrator_case(chan_overrides={"max_concurrent_cases": 1})
    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    offer = authorize_offer(
        offer["id"], ctx["grievance"]["id"], authorization_note="Within director authority"
    )

    assert offer["exposure_cents"] == 40_000
    assert offer["authority_tier"] == "ANALYST"
    assert_instant(offer["expires_at"], "2026-08-24T00:00:00Z", "expires_at")

    accepted = validate_success(
        api.respond_settlement_offer(
            offer["id"],
            {"decision": "ACCEPT", "response_note": "Union accepts"},
            ctx["steward_headers"],
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED"

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["status"] == "SETTLED"
    assert grievance["settled_amount_cents"] == 40_000

    demand = validate_success(
        api.get_arbitration_demand(ctx["demand"]["id"], analyst_headers), 200
    )
    assert demand["status"] == "SETTLED_PRE_HEARING"


def test_pre_hearing_settlement_returns_the_arbitrator_capacity_to_zero(api, administrator_headers):
    """PRD §3.5: "Any arbitration demand on the grievance standing at `DEMANDED`,
    `PANEL_ISSUED`, `STRIKING`, `ARBITRATOR_SELECTED` or `HEARING_SCHEDULED` is transitioned
    to `WITHDRAWN`, and where that demand had already fixed a `selected_arbitrator_id`, the
    arbitrator is released: `active_case_count` drops by 1 and the arbitrator's `status` is
    re-derived, which is how a `FULL` arbitrator becomes `AVAILABLE` again."

    Design: Difficulty/compensating_invariant/arbitrator_capacity_restored_on_pre_hearing_settlement
    """
    ctx = setup_selected_arbitrator_case(chan_overrides={"max_concurrent_cases": 1})
    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    offer = authorize_offer(offer["id"], ctx["grievance"]["id"])
    validate_success(
        api.respond_settlement_offer(
            offer["id"], {"decision": "ACCEPT"}, ctx["steward_headers"]
        ),
        200,
    )

    released = validate_success(
        api.get_arbitrator(ctx["chan"]["id"], administrator_headers), 200
    )
    assert released["active_case_count"] == 0
    assert released["status"] == "AVAILABLE"

    for name in ("alvarez", "dowd"):
        untouched = validate_success(
            api.get_arbitrator(ctx[name]["id"], administrator_headers), 200
        )
        assert untouched["active_case_count"] == 0, (
            f"{name} was struck, so their engagement count never moved"
        )

    _, meta = validate_paginated(
        api.list_arbitration_demands(
            administrator_headers, params={"status": "ARBITRATOR_SELECTED"}
        )
    )
    assert meta["total_count"] == 0, "no demand holds an engagement once the case settles"
