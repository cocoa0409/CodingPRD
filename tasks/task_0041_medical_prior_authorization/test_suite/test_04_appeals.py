"""Three-tier appeal process: escalation cycle, overturn cascade, expedited vs
standard appeal-window deadlines, terminal-state lockdown, withdraw, tier-3
external decide, appeal eligibility, and the appeal past-deadline check.

Translates queue A (non_linear_state_machine appeals, transitive_cascade,
dual_variant_calc appeal deadline, cross_entity_state_dependency appeal) and
queue B (state_machines appeals, errors past-deadline) instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    register_actors,
    set_clock,
    create_denied_request,
    create_approved_request,
    create_draft_request,
    create_open_tier1_appeal,
    create_tier3_open_appeal,
    escalate_to_tier,
    file_appeal,
    decide_appeal,
    external_decide,
    make_provider_headers,
    make_payer_headers,
    make_external_reviewer_headers,
)


# --------------------------------------------------------------------------
# non-linear state machine: appeal UPHELD -> ESCALATED cycle (queue A)
# --------------------------------------------------------------------------

def test_appeal_uphold_escalate_cycle_across_tiers(api):
    """PRD §3.6: "Escalation sets the prior appeal's `status` to `ESCALATED`,
    increments the prior appeal's `version` by one, and creates a new `Appeal`
    whose `tier` is the prior tier plus one, in the `OPEN` state, with `filed_at`
    at the current clock and a freshly computed `appeal_deadline_at`."

    Design: Difficulty/non_linear_state_machine/appeal_uphold_escalate_cycle_across_tiers
    """
    actors = register_actors(provider_overrides={"specialty": "ORTHOPEDICS"},
                             reviewer_overrides={"specialty": "ORTHOPEDICS"})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    denied, appeal_t1 = create_open_tier1_appeal(
        actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-O",
                                   "requested_units": 1, "unit_cost_cents": 5000}
    )
    get_success_data(decide_appeal(actors, appeal_t1["id"], "UPHELD", "Stands"))
    appeal_t2 = get_success_data(file_appeal(actors, denied["id"]))
    prov_h = make_provider_headers(actors["provider"]["id"])
    refreshed_t1 = get_success_data(api.get_appeal(appeal_t1["id"], prov_h))
    assert refreshed_t1["status"] == "ESCALATED", (
        f"prior appeal must be ESCALATED, got {refreshed_t1['status']}"
    )
    assert appeal_t2["tier"] == 2, f"new appeal tier must be 2, got {appeal_t2['tier']}"
    assert appeal_t2["status"] == "OPEN", f"new appeal must be OPEN, got {appeal_t2['status']}"


def test_appeal_escalation_reaches_tier3_open(api):
    """PRD §3.6: "Escalation sets the prior appeal's `status` to `ESCALATED`,
    increments the prior appeal's `version` by one, and creates a new `Appeal`
    whose `tier` is the prior tier plus one, in the `OPEN` state, with `filed_at`
    at the current clock and a freshly computed `appeal_deadline_at`."

    Design: Difficulty/non_linear_state_machine/appeal_uphold_escalate_cycle_across_tiers
    """
    actors = register_actors(provider_overrides={"specialty": "ORTHOPEDICS"},
                             reviewer_overrides={"specialty": "ORTHOPEDICS"})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    denied = create_denied_request(
        actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-O3",
                                   "requested_units": 1, "unit_cost_cents": 5000}
    )
    appeal_t3 = escalate_to_tier(actors, denied["id"], 3)
    assert appeal_t3["tier"] == 3, f"escalated chain must reach tier 3, got {appeal_t3['tier']}"
    assert appeal_t3["status"] == "OPEN", f"tier-3 appeal must be OPEN, got {appeal_t3['status']}"


# --------------------------------------------------------------------------
# transitive cascade: overturn -> request APPROVED -> member counter (queue A)
# --------------------------------------------------------------------------

def test_overturn_cascades_request_then_member_counter_depth3(api):
    """PRD §3.6: "An `OVERTURNED` decision sets the appeal's `status` to
    `OVERTURNED` and cascades back to the underlying request: the request
    transitions from `DENIED` to `APPROVED`, its `approved_units` is set to
    `requested_units`, its `authorization_expires_at` is set to the current clock
    plus 365 days, its `member_cost_share_cents` is recomputed, and the referenced
    member's `active_authorization_count` is incremented by one."

    Design: Difficulty/transitive_cascade/overturn_cascades_request_then_member_counter_depth3
    """
    actors = register_actors(provider_overrides={"specialty": "CARDIOLOGY"},
                             reviewer_overrides={"specialty": "CARDIOLOGY"})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    denied, appeal = create_open_tier1_appeal(
        actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-C",
                                   "requested_units": 3, "unit_cost_cents": 5000}
    )
    decided = validate_success(
        api.decide_appeal(
            appeal["id"], {"decision": "OVERTURNED", "decision_rationale": "Medically necessary on review"},
            make_payer_headers(actors["payer"]["id"]),
        )
    )
    assert decided["status"] == "OVERTURNED"
    prov_h = make_provider_headers(actors["provider"]["id"])
    req = get_success_data(api.get_authorization_request(denied["id"], prov_h))
    assert req["status"] == "APPROVED", f"hop2: request must be APPROVED, got {req['status']}"
    assert req["approved_units"] == 3, f"approved_units = requested 3, got {req['approved_units']}"
    member = get_success_data(api.get_member(actors["member"]["id"], prov_h))
    assert member["active_authorization_count"] == 1, (
        f"hop3: member counter must be 1, got {member['active_authorization_count']}"
    )


def test_overturn_sets_request_authorization_expiry_cascade(api):
    """PRD §3.6: "the request transitions from `DENIED` to `APPROVED`, its
    `approved_units` is set to `requested_units`, its `authorization_expires_at`
    is set to the current clock plus 365 days, its `member_cost_share_cents` is
    recomputed, and the referenced member's `active_authorization_count` is
    incremented by one."

    Design: Difficulty/transitive_cascade/overturn_cascades_request_then_member_counter_depth3
    """
    actors = register_actors(provider_overrides={"specialty": "CARDIOLOGY"},
                             reviewer_overrides={"specialty": "CARDIOLOGY"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    denied, appeal = create_open_tier1_appeal(
        actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-CX",
                                   "requested_units": 3, "unit_cost_cents": 5000}
    )
    get_success_data(
        api.decide_appeal(
            appeal["id"], {"decision": "OVERTURNED", "decision_rationale": "necessary"}, payer_h
        )
    )
    req = get_success_data(
        api.get_authorization_request(denied["id"], make_provider_headers(actors["provider"]["id"]))
    )
    assert req["status"] == "APPROVED"
    assert req["authorization_expires_at"] == "2027-06-01T00:00:00Z", (
        f"overturn sets expiry to clock + 365 days; got {req['authorization_expires_at']}"
    )


# --------------------------------------------------------------------------
# dual-variant appeal deadline: standard vs expedited window (queue A)
# --------------------------------------------------------------------------

def test_appeal_deadline_expedited_window(api):
    """PRD §3.6: "Each tier has a base window in days — 30 days for tier 1, 30 days
    for tier 2, and 45 days for tier 3. Expedited requests compress this window:
    when the underlying request's `is_expedited` flag is true the window is
    multiplied by 0.25, and when it is false the full tier window applies. The
    `appeal_deadline_at` is the appeal's `filed_at` advanced by the resulting
    number of days; the window may be fractional, and the deadline datetime is
    resolved to the second."

    Design: Difficulty/dual_variant_calc/appeal_deadline_standard_vs_expedited_window
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        provider_overrides={"specialty": "ONCOLOGY"},
        reviewer_overrides={"specialty": "ONCOLOGY"},
    )
    payer_h = make_payer_headers(actors["payer"]["id"])
    prov_h = make_provider_headers(actors["provider"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    denied = create_denied_request(
        actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-EXP",
                                   "requested_units": 1, "unit_cost_cents": 5000, "is_expedited": True}
    )
    # Escalate to tier-3 OPEN, filing the tier-3 at 2026-06-10.
    appeal_t1 = get_success_data(file_appeal(actors, denied["id"]))
    get_success_data(decide_appeal(actors, appeal_t1["id"], "UPHELD", "Denial stands t1"))
    appeal_t2 = get_success_data(file_appeal(actors, denied["id"]))
    get_success_data(decide_appeal(actors, appeal_t2["id"], "UPHELD", "Denial stands t2"))
    set_clock("2026-06-10T00:00:00Z", prov_h)
    appeal_t3 = get_success_data(file_appeal(actors, denied["id"]))
    fetched = get_success_data(api.get_appeal(appeal_t3["id"], prov_h))
    assert fetched["tier"] == 3
    assert fetched["appeal_deadline_at"] == "2026-06-21T06:00:00Z", (
        f"45 * 0.25 = 11.25 days after 2026-06-10; got {fetched['appeal_deadline_at']}"
    )


def test_appeal_deadline_standard_window(api):
    """PRD §3.6: "Each tier has a base window in days — 30 days for tier 1, 30 days
    for tier 2, and 45 days for tier 3. Expedited requests compress this window:
    when the underlying request's `is_expedited` flag is true the window is
    multiplied by 0.25, and when it is false the full tier window applies. The
    `appeal_deadline_at` is the appeal's `filed_at` advanced by the resulting
    number of days; the window may be fractional, and the deadline datetime is
    resolved to the second."

    Design: Difficulty/dual_variant_calc/appeal_deadline_standard_vs_expedited_window
    """
    actors = register_actors(provider_overrides={"specialty": "ONCOLOGY"},
                             reviewer_overrides={"specialty": "ONCOLOGY"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    prov_h = make_provider_headers(actors["provider"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    denied = create_denied_request(
        actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-STD",
                                   "requested_units": 1, "unit_cost_cents": 5000, "is_expedited": False}
    )
    appeal_t1 = get_success_data(file_appeal(actors, denied["id"]))
    get_success_data(decide_appeal(actors, appeal_t1["id"], "UPHELD", "stands t1"))
    appeal_t2 = get_success_data(file_appeal(actors, denied["id"]))
    get_success_data(decide_appeal(actors, appeal_t2["id"], "UPHELD", "stands t2"))
    set_clock("2026-06-10T00:00:00Z", prov_h)
    appeal_t3 = get_success_data(file_appeal(actors, denied["id"]))
    fetched = get_success_data(api.get_appeal(appeal_t3["id"], prov_h))
    assert fetched["tier"] == 3
    assert fetched["appeal_deadline_at"] == "2026-07-25T00:00:00Z", (
        f"45 days after 2026-06-10; got {fetched['appeal_deadline_at']}"
    )


# --------------------------------------------------------------------------
# cross-entity state dependency: appeal only on DENIED request (queue A)
# --------------------------------------------------------------------------

def test_appeal_only_on_denied_request(api):
    """PRD §3.6: "A `Provider` files an `Appeal` by supplying the `request_id` of a
    request currently in `DENIED` status. ... Filing an appeal on a request that
    is not `DENIED`, or filing when the eligibility conditions for escalation are
    not met, is rejected with `ERR_APPEAL_NOT_ELIGIBLE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/appeal_only_on_denied_request
    """
    actors = register_actors(provider_overrides={"specialty": "ONCOLOGY"},
                             reviewer_overrides={"specialty": "ONCOLOGY"})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    approved = create_approved_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-2",
                                   "requested_units": 1, "unit_cost_cents": 5000},
        approved_units=1,
    )
    resp = file_appeal(actors, approved["id"])
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_ELIGIBLE.value)


def test_appeal_on_draft_request_not_eligible(api):
    """PRD §3.6: "A `Provider` files an `Appeal` by supplying the `request_id` of a
    request currently in `DENIED` status. ... Filing an appeal on a request that
    is not `DENIED`, or filing when the eligibility conditions for escalation are
    not met, is rejected with `ERR_APPEAL_NOT_ELIGIBLE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/appeal_only_on_denied_request
    """
    actors = register_actors(provider_overrides={"specialty": "ONCOLOGY"}, with_reviewer=False)
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    # A DRAFT request (never denied) is not eligible for appeal.
    draft = create_draft_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-3",
                                   "requested_units": 1, "unit_cost_cents": 5000}
    )
    resp = file_appeal(actors, draft["id"])
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_ELIGIBLE.value)


# --------------------------------------------------------------------------
# appeal state-machine corners (queue B)
# --------------------------------------------------------------------------

def test_decide_on_terminal_overturned_appeal_locked(api):
    """PRD §3.6: "An `OVERTURNED` decision sets the appeal's `status` to
    `OVERTURNED`". PRD §3.9: "then whether the target resource is in a state from
    which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/decide_on_terminal_overturned_appeal_locked
    """
    actors = register_actors(provider_overrides={"specialty": "CARDIOLOGY"},
                             reviewer_overrides={"specialty": "CARDIOLOGY"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    denied, appeal = create_open_tier1_appeal(
        actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-1",
                                   "requested_units": 1, "unit_cost_cents": 5000}
    )
    get_success_data(decide_appeal(actors, appeal["id"], "OVERTURNED", "necessary"))
    resp = api.decide_appeal(
        appeal["id"], {"decision": "UPHELD", "decision_rationale": "second try"}, payer_h
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_withdraw_open_appeal_succeeds(api):
    """PRD §3.6: "A provider may also withdraw an `OPEN` appeal, moving it to
    `WITHDRAWN`, provided the appeal belongs to the request's owning provider —
    the request's `provider_id` must equal `X-User-ID`."

    Design: Corner/state_machines/withdraw_open_appeal_succeeds
    """
    actors = register_actors(provider_overrides={"specialty": "ONCOLOGY"},
                             reviewer_overrides={"specialty": "ONCOLOGY"})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    denied, appeal = create_open_tier1_appeal(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                                   "requested_units": 1, "unit_cost_cents": 5000}
    )
    prov_h = make_provider_headers(actors["provider"]["id"])
    withdrawn = validate_success(api.withdraw_appeal(appeal["id"], prov_h))
    assert withdrawn["status"] == "WITHDRAWN"
    req = get_success_data(api.get_authorization_request(denied["id"], prov_h))
    assert req["status"] == "DENIED", f"underlying request stays DENIED, got {req['status']}"


def test_tier3_external_overturn_cascades_request(api):
    """PRD §3.6: "An `OVERTURNED` external decision sets the appeal's `status` to
    `OVERTURNED` and applies the identical cascade — the underlying request moves
    from `DENIED` to `APPROVED`, `approved_units` is set to `requested_units`,
    `authorization_expires_at` is set to the current clock plus 365 days,
    `member_cost_share_cents` is recomputed, and the member's
    `active_authorization_count` is incremented by one".

    Design: Corner/state_machines/tier3_external_overturn_cascades_request
    """
    actors = register_actors(provider_overrides={"specialty": "ORTHOPEDICS"},
                             reviewer_overrides={"specialty": "ORTHOPEDICS"})
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    denied, appeal_t3 = create_tier3_open_appeal(
        actors, request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-1",
                                   "requested_units": 2, "unit_cost_cents": 5000}
    )
    decided = validate_success(
        external_decide(actors, appeal_t3["id"], "OVERTURNED", "IRO finds medically necessary")
    )
    assert decided["status"] == "OVERTURNED"
    prov_h = make_provider_headers(actors["provider"]["id"])
    req = get_success_data(api.get_authorization_request(denied["id"], prov_h))
    assert req["status"] == "APPROVED", f"request must be APPROVED, got {req['status']}"
    member = get_success_data(api.get_member(actors["member"]["id"], prov_h))
    assert member["active_authorization_count"] == 1, (
        f"member counter must be 1, got {member['active_authorization_count']}"
    )


# --------------------------------------------------------------------------
# appeal past-deadline (queue B)
# --------------------------------------------------------------------------

def test_error_past_deadline_on_appeal_decision(api):
    """PRD §3.6: "A review or appeal decision rendered after its deadline — past
    `sla_due_at` for a review decision, or past `appeal_deadline_at` for an appeal
    decision — is rejected with `ERR_PAST_DEADLINE` (HTTP 409)." PRD §3.6: "Each
    tier has a base window in days — 30 days for tier 1, 30 days for tier 2, and
    45 days for tier 3."

    Design: Corner/errors/error_past_deadline_on_appeal_decision
    """
    actors = register_actors(provider_overrides={"specialty": "ONCOLOGY"},
                             reviewer_overrides={"specialty": "ONCOLOGY"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    prov_h = make_provider_headers(actors["provider"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    denied = create_denied_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                                   "requested_units": 1, "unit_cost_cents": 5000, "is_expedited": False}
    )
    # File tier-1 at 2026-06-10 (standard window 30 days -> deadline 2026-07-10).
    set_clock("2026-06-10T00:00:00Z", prov_h)
    appeal = get_success_data(file_appeal(actors, denied["id"]))
    # Advance past the 30-day deadline.
    set_clock("2026-07-11T00:00:00Z", payer_h)
    resp = api.decide_appeal(
        appeal["id"], {"decision": "UPHELD", "decision_rationale": "late"}, payer_h
    )
    validate_error(resp, ApiErrorId.ERR_PAST_DEADLINE.value)
