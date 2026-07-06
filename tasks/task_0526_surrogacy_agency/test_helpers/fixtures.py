"""Composite setup helpers.

Most interesting claims require the system to be walked through a long
multi-party pipeline: intake + screening + clearance for both parties, match
proposal/accept/psych-clear, contract draft/ip-sign/carrier-sign (across the
3-day cooling-off window), journey start (which auto-opens an escrow account),
deposit, comp-schedule lines, milestones. These helpers encapsulate those
sequences so tests focus on the behavior under assertion.

Every helper uses get_success_data() (lenient 2xx) so setup problems surface as
clear "Setup failed" errors, and threads the entity_backed IntendedParentActor /
CarrierActor identities through their id-bearing headers on ownership-gated calls.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_case_manager_headers,
    make_intended_parent_actor_headers,
    make_carrier_actor_headers,
)
from . import factories as f

CM = TEST_USERS["case_manager_headers"]
SCREENER = TEST_USERS["screener_headers"]
FO = TEST_USERS["finance_officer_headers"]

# A clock instant safely past the 3-day cooling-off from the 2026-05-01 startup.
POST_COOLING_OFF_UTC = "2026-05-10T00:00:00Z"


# ==========================================================================
# Tier 1: single-entity state progression
# ==========================================================================
def create_cleared_intended_parent(budget_cents=6_000_000, state_code="CA", psych="PASSED"):
    """Create an IP and walk DRAFT -> SUBMITTED -> SCREENING -> (psych) -> CLEARED.
    Returns the cleared IntendedParent dict."""
    ip = get_success_data(api_client.create_intended_parent(
        f.create_intended_parent_payload(budget_cents=budget_cents, state_code=state_code), CM))
    ip_id = ip["id"]
    get_success_data(api_client.submit_intended_parent(ip_id, CM))
    get_success_data(api_client.start_screening_intended_parent(ip_id, SCREENER))
    get_success_data(api_client.set_psych_intended_parent(ip_id, f.set_psych_payload(psych), SCREENER))
    get_success_data(api_client.clear_intended_parent(ip_id, SCREENER))
    return get_success_data(api_client.get_intended_parent(ip_id, CM))


def create_carrier_in_screening(prior_deliveries=2, base_compensation_cents=4_000_000,
                                state_code="TX", psych="PASSED"):
    """Create a carrier and walk to SCREENING with psych set. Returns carrier dict."""
    car = get_success_data(api_client.create_carrier(
        f.create_carrier_payload(prior_deliveries=prior_deliveries,
                                 base_compensation_cents=base_compensation_cents,
                                 state_code=state_code), CM))
    car_id = car["id"]
    get_success_data(api_client.submit_carrier(car_id, CM))
    get_success_data(api_client.start_screening_carrier(car_id, SCREENER))
    if psych is not None:
        get_success_data(api_client.set_psych_carrier(car_id, f.set_psych_payload(psych), SCREENER))
    return get_success_data(api_client.get_carrier(car_id, CM))


def create_cleared_carrier(prior_deliveries=2, base_compensation_cents=4_000_000,
                           state_code="TX", psych="PASSED", policy_kind="SURROGACY_FRIENDLY"):
    """Create a carrier and walk to CLEARED, including a qualifying insurance review.
    Returns (carrier_dict, insurance_review_dict)."""
    car = create_carrier_in_screening(prior_deliveries, base_compensation_cents, state_code, psych)
    car_id = car["id"]
    ins = get_success_data(api_client.create_insurance_review(
        f.create_insurance_review_payload(car_id, policy_kind=policy_kind), SCREENER))
    if policy_kind == "SURROGACY_FRIENDLY":
        get_success_data(api_client.approve_insurance_review(ins["id"], SCREENER))
    elif policy_kind == "EXCLUSION":
        get_success_data(api_client.identify_gap_insurance_review(ins["id"], SCREENER))
    get_success_data(api_client.clear_carrier(car_id, SCREENER))
    car = get_success_data(api_client.get_carrier(car_id, CM))
    return car, ins


# ==========================================================================
# Tier 2/3: match + contract + journey lifecycle
# ==========================================================================
def create_proposed_match(proposed_carrier_comp_cents=4_000_000, ip_state_code="CA",
                          prior_deliveries=2, carrier_base_comp_cents=4_000_000,
                          fully_cleared=True):
    """Create a match in PROPOSED. If fully_cleared, both parties are CLEARED so
    accept can only fail on OCC. Returns dict with ip, carrier, match, match_version."""
    if fully_cleared:
        ip = create_cleared_intended_parent(state_code=ip_state_code)
        car, _ = create_cleared_carrier(prior_deliveries=prior_deliveries,
                                        base_compensation_cents=carrier_base_comp_cents)
    else:
        ip = get_success_data(api_client.create_intended_parent(
            f.create_intended_parent_payload(state_code=ip_state_code), CM))
        car = get_success_data(api_client.create_carrier(
            f.create_carrier_payload(prior_deliveries=prior_deliveries,
                                     base_compensation_cents=carrier_base_comp_cents), CM))
    match = get_success_data(api_client.create_match(
        f.create_match_payload(ip["id"], car["id"],
                               proposed_carrier_comp_cents=proposed_carrier_comp_cents), CM))
    return {"ip": ip, "carrier": car, "match": match, "match_version": match["version"]}


def create_psych_cleared_match(proposed_carrier_comp_cents=4_000_000, ip_state_code="CA",
                               prior_deliveries=2, carrier_base_comp_cents=4_000_000):
    """Walk a fully-cleared match through ACCEPT -> PSYCH_CLEARED.
    Returns dict with ip, carrier, match (PSYCH_CLEARED)."""
    ctx = create_proposed_match(proposed_carrier_comp_cents, ip_state_code,
                                prior_deliveries, carrier_base_comp_cents, fully_cleared=True)
    match_id = ctx["match"]["id"]
    accepted = get_success_data(api_client.accept_match(
        match_id, {"expected_match_version": ctx["match"]["version"]}, CM))
    get_success_data(api_client.psych_clear_match(match_id, SCREENER))
    ctx["match"] = get_success_data(api_client.get_match(match_id, CM))
    return ctx


def create_ip_signed_contract(ip_state_code="CA", prior_deliveries=2):
    """PSYCH_CLEARED match -> draft contract -> ip-sign (stamps ip_signed_at at the
    startup clock). Clock is NOT advanced. Returns dict with ip, carrier, match, contract."""
    ctx = create_psych_cleared_match(ip_state_code=ip_state_code, prior_deliveries=prior_deliveries)
    contract = get_success_data(api_client.create_contract(
        f.create_contract_payload(ctx["match"]["id"]), CM))
    ip_headers = make_intended_parent_actor_headers(ctx["ip"]["id"])
    contract = get_success_data(api_client.ip_sign_contract(contract["id"], ip_headers))
    ctx["contract"] = contract
    return ctx


def create_executed_contract(ip_state_code="CA", prior_deliveries=2):
    """IP_SIGNED contract -> advance clock past cooling-off -> carrier-sign -> EXECUTED.
    Returns dict with ip, carrier, match, contract (EXECUTED)."""
    ctx = create_ip_signed_contract(ip_state_code=ip_state_code, prior_deliveries=prior_deliveries)
    get_success_data(api_client.set_clock({"to_iso8601": POST_COOLING_OFF_UTC}, CM))
    carrier_headers = make_carrier_actor_headers(ctx["carrier"]["id"])
    contract = get_success_data(api_client.carrier_sign_contract(ctx["contract"]["id"], carrier_headers))
    ctx["contract"] = contract
    return ctx


def create_active_journey(ip_state_code="CA", prior_deliveries=2,
                          carrier_base_comp_cents=4_000_000):
    """Full pipeline to an ACTIVE journey with an auto-opened OPEN escrow account.
    Returns dict with ip, carrier, match, contract, journey, escrow."""
    ctx = create_executed_contract(ip_state_code=ip_state_code, prior_deliveries=prior_deliveries)
    journey = get_success_data(api_client.create_journey(
        f.create_journey_payload(ctx["match"]["id"]), CM))
    ctx["journey"] = journey
    escrows, _ = _list_escrows_for_journey(journey["id"])
    ctx["escrow"] = escrows[0]
    return ctx


def _list_escrows_for_journey(journey_id):
    resp = api_client.list_escrow_accounts(FO, params={"journey_id": journey_id})
    data = get_success_data(resp)
    # get_success_data returns the data payload (a list for array responses).
    return data, resp


# ==========================================================================
# Tier 4: funded escrow, schedule lines, milestones
# ==========================================================================
def create_funded_journey(deposit_cents=6_000_000, ip_budget_state="CA", prior_deliveries=2):
    """ACTIVE journey whose escrow has `deposit_cents` deposited (available == deposit).
    Returns dict with ip, carrier, match, contract, journey, escrow (refreshed)."""
    ctx = create_active_journey(ip_state_code=ip_budget_state, prior_deliveries=prior_deliveries)
    escrow = ctx["escrow"]
    ip_headers = make_intended_parent_actor_headers(ctx["ip"]["id"])
    escrow = get_success_data(api_client.deposit_escrow(
        escrow["id"], f.deposit_payload(deposit_cents, escrow["version"]), ip_headers))
    ctx["escrow"] = escrow
    return ctx


def add_comp_schedule_line(journey_id, trigger_milestone_type, amount_cents, recipient="CARRIER"):
    return get_success_data(api_client.create_comp_schedule(
        journey_id, f.create_comp_schedule_payload(trigger_milestone_type, recipient, amount_cents), CM))


def add_milestone(journey_id, milestone_type, scheduled_utc="2026-05-15T00:00:00Z"):
    return get_success_data(api_client.create_milestone(
        journey_id, f.create_milestone_payload(milestone_type, scheduled_utc), CM))


def add_and_achieve_milestone(journey_id, milestone_type, scheduled_utc="2026-05-15T00:00:00Z"):
    ms = add_milestone(journey_id, milestone_type, scheduled_utc)
    ms = get_success_data(api_client.achieve_milestone(journey_id, ms["id"], CM))
    return ms


def create_approved_disbursement(deposit_cents=6_000_000, schedule_amount_cents=1_000_000,
                                 trigger_milestone_type="EMBRYO_TRANSFER",
                                 approver_user_id="cm-approver"):
    """Funded journey -> one schedule line -> achieve its trigger milestone ->
    request + approve a disbursement (reserving schedule_amount_cents).
    Returns dict with ip, carrier, journey, escrow (refreshed), schedule,
    disbursement (APPROVED), approver_user_id."""
    ctx = create_funded_journey(deposit_cents=deposit_cents)
    jr_id = ctx["journey"]["id"]
    schedule = add_comp_schedule_line(jr_id, trigger_milestone_type, schedule_amount_cents)
    add_and_achieve_milestone(jr_id, trigger_milestone_type)
    disb = get_success_data(api_client.create_disbursement(
        jr_id, f.create_disbursement_payload(schedule["id"], ctx["escrow"]["id"]), CM))
    approver_headers = make_case_manager_headers(approver_user_id)
    disb = get_success_data(api_client.approve_disbursement(jr_id, disb["id"], approver_headers))
    ctx["schedule"] = schedule
    ctx["disbursement"] = disb
    ctx["approver_user_id"] = approver_user_id
    ctx["escrow"] = get_success_data(api_client.get_escrow_account(ctx["escrow"]["id"], FO))
    return ctx


def create_requested_disbursement(deposit_cents=6_000_000, schedule_amount_cents=1_000_000,
                                  trigger_milestone_type="EMBRYO_TRANSFER", achieve_milestone=True):
    """Funded journey -> one schedule line -> (optionally achieve trigger milestone)
    -> request a disbursement (REQUESTED, not approved).
    Returns dict with ip, carrier, journey, escrow, schedule, disbursement."""
    ctx = create_funded_journey(deposit_cents=deposit_cents)
    jr_id = ctx["journey"]["id"]
    schedule = add_comp_schedule_line(jr_id, trigger_milestone_type, schedule_amount_cents)
    if achieve_milestone:
        add_and_achieve_milestone(jr_id, trigger_milestone_type)
    disb = get_success_data(api_client.create_disbursement(
        jr_id, f.create_disbursement_payload(schedule["id"], ctx["escrow"]["id"]), CM))
    ctx["schedule"] = schedule
    ctx["disbursement"] = disb
    ctx["escrow"] = get_success_data(api_client.get_escrow_account(ctx["escrow"]["id"], FO))
    return ctx
