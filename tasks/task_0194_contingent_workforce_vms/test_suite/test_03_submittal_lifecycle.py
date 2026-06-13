"""Submittal hiring funnel: rate-negotiation cycle, state preconditions,
priority conflicts, and terminal-state lockdown (§3.3).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    get_success_data, make_supplier_headers, TEST_USERS,
    create_program, create_supplier, create_worker, create_requisition,
    distribute, create_submittal, setup_distributed_requisition,
    setup_submitted_submittal,
)
from test_helpers import factories as F

PM = TEST_USERS["program_manager_headers"]
HM = TEST_USERS["hiring_manager_headers"]


def _interviewing_submittal(api, req_overrides=None):
    """Build a submittal walked to INTERVIEWING. Returns (base, submittal_id, sh)."""
    base = setup_submitted_submittal(req_overrides=req_overrides)
    sid = base["submittal"]["id"]
    get_success_data(api.shortlist_submittal(sid, HM))
    get_success_data(api.start_interview(sid, HM))
    return base, sid, base["supplier_headers"]


# ===========================================================================
# Queue A: non_linear_state_machine / submittal_rate_negotiation_cycle
# ===========================================================================

def test_negotiation_cycle_returns_to_interviewing_with_rounds_incremented(api):
    """PRD §3.3: "The first is to counter the rate, which returns the submittal
    from `RATE_PROPOSED` to `INTERVIEWING` for another round and increments
    `rounds` by one"

    Two laps of propose_rate -> counter_rate land back at INTERVIEWING with
    rounds == 2.

    Design: Difficulty/non_linear_state_machine/submittal_rate_negotiation_cycle
    """
    base, sid, sh = _interviewing_submittal(api)
    get_success_data(api.propose_rate(sid, {"pay_rate_cents": 9000}, sh))
    get_success_data(api.counter_rate(sid, HM))
    get_success_data(api.propose_rate(sid, {"pay_rate_cents": 9500}, sh))
    data = validate_success(api.counter_rate(sid, HM))
    assert data["status"] == "INTERVIEWING", f"got {data['status']}"
    assert data["rounds"] == 2, f"got {data['rounds']}"


def test_first_counter_round_sets_interviewing_and_rounds_one(api):
    """PRD §3.3: "The first is to counter the rate, which returns the submittal
    from `RATE_PROPOSED` to `INTERVIEWING` for another round and increments
    `rounds` by one"

    A single propose_rate -> counter_rate lap yields INTERVIEWING with rounds==1.

    Design: Difficulty/non_linear_state_machine/submittal_rate_negotiation_cycle
    """
    base, sid, sh = _interviewing_submittal(api)
    proposed = validate_success(api.propose_rate(sid, {"pay_rate_cents": 9000}, sh))
    assert proposed["status"] == "RATE_PROPOSED"
    data = validate_success(api.counter_rate(sid, HM))
    assert data["status"] == "INTERVIEWING"
    assert data["rounds"] == 1, f"got {data['rounds']}"


# ===========================================================================
# Queue A: priority_pair_validation_conflict / state_beats_fiscal_on_propose_rate
# ===========================================================================

def test_invalid_state_beats_pay_rate_ceiling_on_propose_rate(api):
    """PRD §3.3: "From `INTERVIEWING`, the `Supplier` may propose a new rate
    (see §3.4), which moves the submittal to `RATE_PROPOSED`."
    PRD §3.11: "The state-machine precondition (that the target is in a state
    from which the requested transition is defined) is checked fifth. Domain
    rules follow in this order: distribution-release timing, then the
    co-employment tenure safety stop, then milestone sequencing, then the
    negotiation-rounds cap, then remaining-openings, then the pay-rate ceiling"

    SHORTLISTED (not INTERVIEWING) submittal + pay 99999 over max 10000: the
    lower-priority state check wins -> ERR_INVALID_STATE, not pay-rate error.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_propose_rate
    """
    base = setup_submitted_submittal(req_overrides={"max_pay_rate_cents": 10000})
    sid = base["submittal"]["id"]
    get_success_data(api.shortlist_submittal(sid, HM))  # now SHORTLISTED, not INTERVIEWING
    validate_error(
        api.propose_rate(sid, {"pay_rate_cents": 99999}, base["supplier_headers"]),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_propose_rate_above_max_from_interviewing_hits_pay_rate_error(api):
    """PRD §3.4: "The pay rate may not exceed the requisition's
    `max_pay_rate_cents`; a `pay_rate_cents` greater than that ceiling is
    rejected with `ERR_PAY_RATE_EXCEEDS_MAX`."
    PRD §3.4: "both apply identically at submittal creation and at rate proposal."

    From INTERVIEWING (state precondition satisfied), an over-max propose_rate
    surfaces the fiscal error, isolating the rule the priority test masks.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_propose_rate
    """
    base, sid, sh = _interviewing_submittal(api, req_overrides={"max_pay_rate_cents": 10000})
    validate_error(
        api.propose_rate(sid, {"pay_rate_cents": 99999}, sh),
        ApiErrorId.ERR_PAY_RATE_EXCEEDS_MAX.value,
    )


# ===========================================================================
# Queue A: cross_entity_state_dependency / submittal_shortlist_requires_requisition_distributed
# ===========================================================================

def test_shortlist_fails_after_requisition_closed(api):
    """PRD §3.3: "Shortlisting moves it from `SUBMITTED` to `SHORTLISTED`, and is
    permitted only while the parent requisition is `DISTRIBUTED`; attempting it
    otherwise yields `ERR_INVALID_STATE`."
    PRD §3.2: "Closing a `DISTRIBUTED` requisition moves it to `CLOSED`, revokes
    every non-terminal distribution (setting their `status` to `REVOKED`), and
    rejects every non-terminal submittal on it (setting their `status` to
    `REJECTED`)."

    After the requisition is CLOSED its submittal is auto-REJECTED; shortlist
    then fails ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/submittal_shortlist_requires_requisition_distributed
    """
    base = setup_submitted_submittal()
    sid = base["submittal"]["id"]
    get_success_data(api.close_requisition(base["requisition"]["id"], PM))
    validate_error(api.shortlist_submittal(sid, HM), ApiErrorId.ERR_INVALID_STATE.value)


def test_shortlist_succeeds_while_requisition_distributed(api):
    """PRD §3.3: "Shortlisting moves it from `SUBMITTED` to `SHORTLISTED`, and is
    permitted only while the parent requisition is `DISTRIBUTED`; attempting it
    otherwise yields `ERR_INVALID_STATE`."

    With the requisition still DISTRIBUTED the shortlist succeeds (SHORTLISTED).

    Design: Difficulty/cross_entity_state_dependency/submittal_shortlist_requires_requisition_distributed
    """
    base = setup_submitted_submittal()
    data = validate_success(api.shortlist_submittal(base["submittal"]["id"], HM))
    assert data["status"] == "SHORTLISTED"


# ===========================================================================
# Queue B: state_machines / shortlist_from_already_shortlisted_returns_invalid_state
# ===========================================================================

def test_shortlist_twice_returns_invalid_state(api):
    """PRD §3.3: "Shortlisting moves it from `SUBMITTED` to `SHORTLISTED`, and is
    permitted only while the parent requisition is `DISTRIBUTED`; attempting it
    otherwise yields `ERR_INVALID_STATE`."

    The second shortlist finds the submittal already SHORTLISTED (no
    SHORTLISTED->SHORTLISTED transition) -> ERR_INVALID_STATE.

    Design: Corner/state_machines/shortlist_from_already_shortlisted_returns_invalid_state
    """
    base = setup_submitted_submittal()
    sid = base["submittal"]["id"]
    get_success_data(api.shortlist_submittal(sid, HM))
    validate_error(api.shortlist_submittal(sid, HM), ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B: state_machines / hire_from_non_offered_returns_invalid_state
# ===========================================================================

def test_hire_from_submitted_returns_invalid_state(api):
    """PRD §3.5: "Hiring is the `ProgramManager`'s act of converting an
    `OFFERED` submittal into a live engagement"
    PRD §2.4: "The `version` field underpins the optimistic-concurrency
    mechanism described in §2.7."

    hire on a SUBMITTED (not OFFERED) submittal -> ERR_INVALID_STATE.

    Design: Corner/state_machines/hire_from_non_offered_returns_invalid_state
    """
    base = setup_submitted_submittal()
    validate_error(
        api.hire_submittal(
            base["submittal"]["id"],
            F.hire_payload(base["req_version"], "2026-01-01T00:00:00.000Z",
                           "2026-06-01T00:00:00.000Z"),
            PM,
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


# ===========================================================================
# Queue B: state_machines / counter_rate_rounds_cap_exceeded_at_five
# ===========================================================================

def test_sixth_counter_rate_exceeds_rounds_cap(api):
    """PRD §3.3: "this counter is permitted only while `rounds` is below 5, and a
    counter attempted once `rounds` has already reached 5 is rejected with
    `ERR_NEGOTIATION_ROUNDS_EXCEEDED`."

    After 5 completed counter rounds (rounds==5), a 6th counter from
    RATE_PROPOSED -> ERR_NEGOTIATION_ROUNDS_EXCEEDED.

    Design: Corner/state_machines/counter_rate_rounds_cap_exceeded_at_five
    """
    base, sid, sh = _interviewing_submittal(api)
    for i in range(5):
        get_success_data(api.propose_rate(sid, {"pay_rate_cents": 8001 + i}, sh))
        get_success_data(api.counter_rate(sid, HM))
    # rounds now 5, currently INTERVIEWING; propose once more then counter.
    get_success_data(api.propose_rate(sid, {"pay_rate_cents": 8006}, sh))
    validate_error(api.counter_rate(sid, HM), ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXCEEDED.value)
