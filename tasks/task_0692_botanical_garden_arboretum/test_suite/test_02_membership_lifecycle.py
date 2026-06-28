"""Membership lifecycle tests: the cyclic renew self-loop, reinstatement,
invalid transitions, terminal lockdown, and activation preconditions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_visitor_headers,
    set_clock,
    create_garden,
    create_plan,
    create_pending_membership,
)

STAFF = TEST_USERS["staff_headers"]


# =============================================================================
# non_linear_state_machine — Membership cyclic ACTIVE -> ACTIVE via renew
# =============================================================================
def test_membership_renews_twice_self_loop_extends_term(api):
    """PRD §3.2: "an `ACTIVE` membership renews back to `ACTIVE`, extending
    rather than restarting its term." PRD §3.2: "The new `term_start` becomes the
    old `term_end` and the new `term_end` becomes the old `term_end` plus 365
    days — an extension, not a reset to now... `renewal_count` increases by one."

    auto_renew=true allows renewing at any time. After two renewals
    renewal_count==2, status stays ACTIVE, term_end extends to 2029-03-31.

    Design: Difficulty/non_linear_state_machine/nlsm_membership_cyclic_active_to_active
    """
    garden = create_garden(name="Foxglove Walk")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Gus", auto_renew=True)
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    validate_success(api.activate_membership(m_id, h))
    validate_success(api.renew_membership(m_id, h))
    renewed = validate_success(api.renew_membership(m_id, h))
    assert renewed["renewal_count"] == 2, f"expected renewal_count 2, got {renewed['renewal_count']}"
    assert renewed["status"] == "ACTIVE"
    assert renewed["term_end"].startswith("2029-03-31T00:00:00")


def test_membership_renew_keeps_active_and_increments_count(api):
    """PRD §3.2: "Renewal is the cyclic heart of the lifecycle: an `ACTIVE`
    membership renews back to `ACTIVE`". PRD §3.2: "The guest-pass allotment is
    reset to the tier grant for the new term, and `renewal_count` increases by
    one."

    A single renewal on an auto-renew membership returns ACTIVE with
    renewal_count 1 (the self-loop fires once).

    Design: Difficulty/non_linear_state_machine/nlsm_membership_cyclic_active_to_active
    """
    garden = create_garden(name="Foxglove Walk One")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Gus", auto_renew=True)
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    validate_success(api.activate_membership(m_id, h))
    renewed = validate_success(api.renew_membership(m_id, h))
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewal_count"] == 1


# =============================================================================
# Corner: state_machines section
# =============================================================================
def test_activate_already_active_returns_invalid_state(api):
    """PRD §3.2: "Activation is permitted only when the membership is in
    `PENDING` status — otherwise `ERR_INVALID_STATE`".

    A second activate on an ACTIVE membership is rejected; no second charge
    (paid_total_cents stays 12000).

    Design: Corner/state_machines/activate_already_active_membership_returns_invalid_state
    """
    garden = create_garden(name="Wisteria Way")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Wes", auto_renew=False)
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    validate_success(api.activate_membership(m_id, h))
    resp = api.activate_membership(m_id, h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    refreshed = validate_success(api.get_membership(m_id, h))
    assert refreshed["paid_total_cents"] == 12000, "no second charge on a failed re-activation"


def test_cancel_already_cancelled_returns_invalid_state(api):
    """PRD §3.2: "A membership not in one of those three states cannot be
    cancelled and yields `ERR_INVALID_STATE`."

    Cancelling a CANCELLED (terminal) membership is rejected.

    Design: Corner/state_machines/cancel_already_cancelled_membership_returns_invalid_state
    """
    garden = create_garden(name="Xeranthemum Yard")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Xan", auto_renew=False)
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    validate_success(api.cancel_membership(m_id, h))
    resp = api.cancel_membership(m_id, h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_renew_before_window_without_auto_renew_rejected(api):
    """PRD §3.2: "A renewal attempted before the 30-day window with `auto_renew`
    false is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`."

    Activated at default clock (term_end ~1 year out), auto_renew false, clock
    not advanced -> renew far before the window fails.

    Design: Corner/state_machines/renew_before_window_without_auto_renew_returns_window_not_open
    """
    garden = create_garden(name="Yarrow Yonder")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Yul", auto_renew=False)
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    validate_success(api.activate_membership(m_id, h))
    resp = api.renew_membership(m_id, h)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value, expected_status=409)


def test_activate_against_inactive_plan_rejected(api):
    """PRD §3.2: "Activation moves a membership from `PENDING` to `ACTIVE`...
    only when the referenced plan's `active` flag is true; an inactive plan
    yields `ERR_PLAN_INACTIVE`."

    Plan created with active=false -> activation fails.

    Design: Corner/state_machines/activate_against_inactive_plan_returns_plan_inactive
    """
    garden = create_garden(name="Zinnia Zone")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000, active=False)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Zoe", auto_renew=False)
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    resp = api.activate_membership(m_id, h)
    validate_error(resp, ApiErrorId.ERR_PLAN_INACTIVE.value, expected_status=409)


def test_reinstate_lapsed_membership_fresh_term_full_fee(api):
    """PRD §3.2: "a reinstatement returns a `LAPSED` membership to `ACTIVE`...
    Reinstatement is treated on the same fresh-term, full-fee basis as a first
    activation — the lapsed time is forfeited with no credit: the full
    `annual_fee_cents` is charged and added to `paid_total_cents`, `term_start`
    is set to now, `term_end` to 365 days after now... and `renewal_count`
    increases by one."

    Activate (12000), advance past term_end to lapse, reinstate at 2027-04-01 ->
    ACTIVE, term_end 2028-03-31 (365 days after 2027-04-01, which crosses the
    2028 leap day), paid_total 24000, renewal_count 1.

    Design: Corner/state_machines/reinstate_lapsed_membership_returns_active_fresh_term
    """
    garden = create_garden(name="Acanthus Annex")
    plan = create_plan(garden["id"], tier="INDIVIDUAL", annual_fee_cents=12000)
    membership = create_pending_membership(garden["id"], plan["id"], primary_member_name="Abe", auto_renew=False)
    m_id = membership["id"]
    h = make_visitor_headers(m_id)
    validate_success(api.activate_membership(m_id, h))
    set_clock("2027-04-01T00:00:00Z")  # past term_end -> LAPSED
    reinstated = validate_success(api.reinstate_membership(m_id, h))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["term_end"].startswith("2028-03-31T00:00:00")
    assert reinstated["paid_total_cents"] == 24000, f"expected 24000, got {reinstated['paid_total_cents']}"
    assert reinstated["renewal_count"] == 1
