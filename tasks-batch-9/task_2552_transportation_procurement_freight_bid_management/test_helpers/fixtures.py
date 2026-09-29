"""Composite setup helpers.

The procurement chain in this PRD is long: a rate record cannot go live until a
carrier has been registered, qualified, invited, has accepted, has bid into a
closed round, has been optimised into a routing guide, has had its allocation
approved, has had the award committed into a contract, and has had that contract
signed by both parties. These helpers walk that chain so each test can start at
the state it actually cares about.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_GO_LIVE,
    CONTRACT_EFFECTIVE_FROM,
    CONTRACT_EFFECTIVE_TO,
    DEFAULT_CLOCK,
    TEST_DEFAULTS,
)
from .factories import (
    bid_event_payload,
    bid_round_payload,
    carrier_payload,
    decision_payload,
    insurance_verification_payload,
    invitation_payload,
    invitation_response_payload,
    lane_bid_payload,
    lane_payload,
    mini_bid_apply_payload,
    mini_bid_payload,
    mini_bid_proposal_payload,
    optimization_run_payload,
    qualification_review_payload,
    rate_record_payload,
    scorecard_payload,
    tender_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_carrier_rep_headers,
)

ANALYST = TEST_USERS["analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
CATEGORY_MANAGER = TEST_USERS["category_manager_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]


# ─── The logical clock ────────────────────────────────────────────────────────

def set_clock(instant: str = DEFAULT_CLOCK) -> Dict[str, Any]:
    """Pins the server-side logical clock to an absolute UTC instant."""
    return get_success_data(api_client.set_clock(instant))


# ─── Tier 1: carriers and qualification standing ──────────────────────────────

def create_carrier(**overrides) -> Dict[str, Any]:
    """Registers a carrier and returns it in `REGISTERED` standing."""
    return get_success_data(
        api_client.create_carrier(carrier_payload(**overrides), ANALYST)
    )


def open_qualification_review(carrier_id: str, **overrides) -> Dict[str, Any]:
    """Opens a qualification review, moving the carrier into `SCREENING`."""
    return get_success_data(
        api_client.create_qualification_review(
            carrier_id, qualification_review_payload(**overrides), COMPLIANCE
        )
    )


def screen_review(
    review_id: str,
    insurance_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolves both arms of a review, leaving it `SCREENED` (or `REMEDIATION`)."""
    get_success_data(
        api_client.verify_insurance(
            review_id,
            insurance_verification_payload(**(insurance_overrides or {})),
            COMPLIANCE,
        )
    )
    return get_success_data(api_client.screen_capability(review_id, COMPLIANCE, {}))


def create_qualified_carrier(
    carrier_overrides: Optional[Dict[str, Any]] = None,
    review_overrides: Optional[Dict[str, Any]] = None,
    insurance_overrides: Optional[Dict[str, Any]] = None,
    outcome: str = "APPROVE",
) -> Dict[str, Any]:
    """Registers, screens and decides a carrier, returning it in final standing.

    Walks registration -> qualification review -> insurance verification ->
    capability screening -> decision, then re-reads the carrier so the caller
    sees its post-decision `status`, `capability_score` and `composite_score`.
    """
    carrier = create_carrier(**(carrier_overrides or {}))
    review = open_qualification_review(carrier["id"], **(review_overrides or {}))
    screen_review(review["id"], insurance_overrides)
    get_success_data(
        api_client.decide_qualification_review(
            review["id"], decision_payload(outcome=outcome), COMPLIANCE
        )
    )
    return get_success_data(api_client.get_carrier(carrier["id"], ANALYST))


def create_qualified_carrier_with_review(
    carrier_overrides: Optional[Dict[str, Any]] = None,
    review_overrides: Optional[Dict[str, Any]] = None,
    insurance_overrides: Optional[Dict[str, Any]] = None,
    outcome: str = "APPROVE",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """As `create_qualified_carrier`, but also returns the decided review."""
    carrier = create_carrier(**(carrier_overrides or {}))
    review = open_qualification_review(carrier["id"], **(review_overrides or {}))
    screen_review(review["id"], insurance_overrides)
    decided = get_success_data(
        api_client.decide_qualification_review(
            review["id"], decision_payload(outcome=outcome), COMPLIANCE
        )
    )
    carrier = get_success_data(api_client.get_carrier(carrier["id"], ANALYST))
    return carrier, decided


def create_screened_review(
    carrier_overrides: Optional[Dict[str, Any]] = None,
    review_overrides: Optional[Dict[str, Any]] = None,
    insurance_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (carrier, review) with the review resolved but not yet decided."""
    carrier = create_carrier(**(carrier_overrides or {}))
    review = open_qualification_review(carrier["id"], **(review_overrides or {}))
    review = screen_review(review["id"], insurance_overrides)
    return carrier, review


def publish_scorecard(carrier_id: str, **overrides) -> Dict[str, Any]:
    """Drafts a period scorecard and publishes it, re-scoring the carrier."""
    scorecard = get_success_data(
        api_client.create_scorecard(carrier_id, scorecard_payload(**overrides), CATEGORY_MANAGER)
    )
    return get_success_data(
        api_client.publish_scorecard(scorecard["id"], CATEGORY_MANAGER)
    )


def draft_scorecard(carrier_id: str, **overrides) -> Dict[str, Any]:
    """Drafts a period scorecard and leaves it in `DRAFT`."""
    return get_success_data(
        api_client.create_scorecard(carrier_id, scorecard_payload(**overrides), CATEGORY_MANAGER)
    )


# ─── Tier 2: bid events, lane scope and invitations ───────────────────────────

#: Placeholder a caller may put in lane overrides to name the bidding carrier as
#: the lane's incumbent; it is replaced with the real carrier id once that carrier
#: has been registered.
CARRIER_ID_REF = "<bidding-carrier-id>"


def resolve_carrier_reference(overrides, carrier_id: str):
    """Substitutes `CARRIER_ID_REF` for a real carrier id inside lane overrides."""
    if overrides is None:
        return None
    resolved = []
    for entry in overrides:
        entry = dict(entry or {})
        for key, value in list(entry.items()):
            if value == CARRIER_ID_REF:
                entry[key] = carrier_id
        resolved.append(entry)
    return resolved


def create_bid_event(**overrides) -> Dict[str, Any]:
    """Opens a bid event in `DRAFT`."""
    return get_success_data(
        api_client.create_bid_event(bid_event_payload(**overrides), ANALYST)
    )


def add_lane(event_id: str, **overrides) -> Dict[str, Any]:
    """Adds one lane to a draft event, leaving it in `DRAFT`."""
    return get_success_data(
        api_client.create_lane(event_id, lane_payload(**overrides), ANALYST)
    )


def add_validated_lane(event_id: str, **overrides) -> Dict[str, Any]:
    """Adds a lane and validates it, recomputing its flags and baseline."""
    lane = add_lane(event_id, **overrides)
    return get_success_data(api_client.validate_lane(lane["id"], ANALYST))


def create_event_with_locked_lanes(
    lane_overrides: Optional[List[Dict[str, Any]]] = None,
    **event_overrides,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Creates an event, adds and validates each lane, then locks the scope.

    Returns the re-read event (so its frozen `baseline_cost_usd` and
    `total_scope_volume_loads` are visible) and the validated lanes.
    """
    event = create_bid_event(**event_overrides)
    lanes = [
        add_validated_lane(event["id"], **(overrides or {}))
        for overrides in (lane_overrides if lane_overrides is not None else [{}])
    ]
    event = get_success_data(api_client.lock_lanes(event["id"], ANALYST))
    return event, lanes


def invite_carrier(event_id: str, carrier_id: str, **overrides) -> Dict[str, Any]:
    """Issues an invitation to a fit carrier, freezing its qualification snapshot."""
    return get_success_data(
        api_client.create_invitation(
            event_id, invitation_payload(carrier_id, **overrides), ANALYST
        )
    )


def invite_and_accept(event_id: str, carrier_id: str, **overrides) -> Dict[str, Any]:
    """Invites a carrier and accepts on that carrier's own behalf."""
    invitation = invite_carrier(event_id, carrier_id, **overrides)
    return get_success_data(
        api_client.respond_to_invitation(
            invitation["id"],
            invitation_response_payload(accept=True),
            make_carrier_rep_headers(carrier_id),
        )
    )


def open_round(event_id: str, **overrides) -> Dict[str, Any]:
    """Opens the next negotiation round on an event whose lanes are locked."""
    return get_success_data(
        api_client.create_bid_round(event_id, bid_round_payload(**overrides), ANALYST)
    )


def submit_bid(
    round_id: str, lane_id: str, carrier_id: str, **overrides
) -> Dict[str, Any]:
    """Submits one lane bid as the owning carrier representative."""
    return get_success_data(
        api_client.create_lane_bid(
            round_id,
            lane_bid_payload(lane_id, carrier_id, **overrides),
            make_carrier_rep_headers(carrier_id),
        )
    )


def close_round(round_id: str) -> Dict[str, Any]:
    """Closes an open round, re-evaluating and re-ranking every submitted bid."""
    return get_success_data(api_client.close_bid_round(round_id, ANALYST))


def setup_open_round_with_bidder(
    carrier_overrides: Optional[Dict[str, Any]] = None,
    lane_overrides: Optional[List[Dict[str, Any]]] = None,
    round_overrides: Optional[Dict[str, Any]] = None,
    **event_overrides,
) -> Dict[str, Any]:
    """Qualified carrier + locked lane scope + accepted invitation + open round.

    Returns a context dict with keys ``carrier``, ``event``, ``lanes``, ``lane``,
    ``invitation`` and ``bid_round``.
    """
    set_clock(DEFAULT_CLOCK)
    carrier = create_qualified_carrier(carrier_overrides=carrier_overrides)
    event, lanes = create_event_with_locked_lanes(
        lane_overrides=resolve_carrier_reference(lane_overrides, carrier["id"]),
        **event_overrides,
    )
    invitation = invite_and_accept(event["id"], carrier["id"])
    bid_round = open_round(event["id"], **(round_overrides or {}))
    return {
        "carrier": carrier,
        "event": event,
        "lanes": lanes,
        "lane": lanes[0],
        "invitation": invitation,
        "bid_round": bid_round,
    }


def setup_closed_round_with_bid(
    bid_overrides: Any = None,
    carrier_overrides: Optional[Dict[str, Any]] = None,
    lane_overrides: Optional[List[Dict[str, Any]]] = None,
    round_overrides: Optional[Dict[str, Any]] = None,
    **event_overrides,
) -> Dict[str, Any]:
    """As `setup_open_round_with_bidder`, plus one bid per lane and a closed round.

    Adds ``bids`` (in lane order), ``bid`` (the first) and refreshes ``bid_round``.
    """
    ctx = setup_open_round_with_bidder(
        carrier_overrides=carrier_overrides,
        lane_overrides=lane_overrides,
        round_overrides=round_overrides,
        **event_overrides,
    )
    if isinstance(bid_overrides, list):
        per_lane = list(bid_overrides)
    else:
        per_lane = [dict(bid_overrides or {})]
    while len(per_lane) < len(ctx["lanes"]):
        per_lane.append({})
    bids = []
    for index, lane in enumerate(ctx["lanes"]):
        overrides = dict(per_lane[index] or {})
        bids.append(
            submit_bid(
                ctx["bid_round"]["id"], lane["id"], ctx["carrier"]["id"], **overrides
            )
        )
    ctx["bid_round"] = close_round(ctx["bid_round"]["id"])
    ctx["bids"] = [
        get_success_data(api_client.get_lane_bid(bid["id"], ANALYST)) for bid in bids
    ]
    ctx["bid"] = ctx["bids"][0]
    return ctx


# ─── Tier 3: optimisation, routing guide and award ────────────────────────────

def run_optimization(event_id: str, **overrides) -> Dict[str, Any]:
    """Runs a scenario, reading the event's current `version` for the guard."""
    event = get_success_data(api_client.get_bid_event(event_id, ANALYST))
    payload = optimization_run_payload(event_id, event["version"], **overrides)
    return get_success_data(api_client.create_optimization_run(payload, ANALYST))


def publish_guide(run_id: str) -> Dict[str, Any]:
    """Publishes a completed run as proposed primary and backup allocations."""
    return get_success_data(api_client.publish_routing_guide(run_id, ANALYST))


def list_allocations(**params) -> List[Dict[str, Any]]:
    """Lists award allocations under the given filters."""
    response = api_client.list_award_allocations(ANALYST, params or None)
    body = get_success_data(response)
    return body["data"] if isinstance(body, dict) and "data" in body else body


def setup_published_routing_guide(
    bid_overrides: Any = None,
    carrier_overrides: Optional[Dict[str, Any]] = None,
    lane_overrides: Optional[List[Dict[str, Any]]] = None,
    round_overrides: Optional[Dict[str, Any]] = None,
    run_overrides: Optional[Dict[str, Any]] = None,
    **event_overrides,
) -> Dict[str, Any]:
    """Closed round -> optimisation run -> published routing guide.

    Adds ``run`` (re-read after publication), ``allocations`` (in lane order) and
    ``allocation`` (the first lane's) to the closed-round context.
    """
    ctx = setup_closed_round_with_bid(
        bid_overrides=bid_overrides,
        carrier_overrides=carrier_overrides,
        lane_overrides=lane_overrides,
        round_overrides=round_overrides,
        **event_overrides,
    )
    run = run_optimization(ctx["event"]["id"], **(run_overrides or {}))
    ctx["run"] = publish_guide(run["id"])
    ctx["allocations"] = [
        allocation
        for lane in ctx["lanes"]
        for allocation in list_allocations(lane_id=lane["id"])
    ]
    ctx["allocation"] = ctx["allocations"][0] if ctx["allocations"] else None
    ctx["event"] = get_success_data(api_client.get_bid_event(ctx["event"]["id"], ANALYST))
    return ctx


def approve_allocation(allocation_id: str) -> Dict[str, Any]:
    """Approves a proposed allocation, reserving its volume against the lane."""
    return get_success_data(
        api_client.approve_award_allocation(allocation_id, CATEGORY_MANAGER)
    )


def commit_award(event_id: str) -> Dict[str, Any]:
    """Commits the award, executing allocations and minting one contract per carrier."""
    return get_success_data(api_client.award_bid_event(event_id, CATEGORY_MANAGER))


def list_contracts(**params) -> List[Dict[str, Any]]:
    """Lists contracts under the given filters."""
    body = get_success_data(api_client.list_contracts(CONTRACT_ADMIN, params or None))
    return body["data"] if isinstance(body, dict) and "data" in body else body


def setup_awarded_event(
    bid_overrides: Any = None,
    carrier_overrides: Optional[Dict[str, Any]] = None,
    lane_overrides: Optional[List[Dict[str, Any]]] = None,
    round_overrides: Optional[Dict[str, Any]] = None,
    run_overrides: Optional[Dict[str, Any]] = None,
    **event_overrides,
) -> Dict[str, Any]:
    """Published guide -> every allocation approved -> award committed.

    Adds ``contract`` (the awarded carrier's) and refreshes ``event``, ``lanes``,
    ``allocations`` and ``carrier``.
    """
    ctx = setup_published_routing_guide(
        bid_overrides=bid_overrides,
        carrier_overrides=carrier_overrides,
        lane_overrides=lane_overrides,
        round_overrides=round_overrides,
        run_overrides=run_overrides,
        **event_overrides,
    )
    for allocation in ctx["allocations"]:
        approve_allocation(allocation["id"])
    ctx["event"] = commit_award(ctx["event"]["id"])
    contracts = list_contracts(
        bid_event_id=ctx["event"]["id"], carrier_id=ctx["carrier"]["id"]
    )
    ctx["contract"] = contracts[0] if contracts else None
    ctx["allocations"] = [
        get_success_data(api_client.get_award_allocation(allocation["id"], ANALYST))
        for allocation in ctx["allocations"]
    ]
    ctx["allocation"] = ctx["allocations"][0] if ctx["allocations"] else None
    ctx["lanes"] = [
        get_success_data(api_client.get_lane(lane["id"], ANALYST)) for lane in ctx["lanes"]
    ]
    ctx["lane"] = ctx["lanes"][0]
    ctx["carrier"] = get_success_data(
        api_client.get_carrier(ctx["carrier"]["id"], ANALYST)
    )
    return ctx


# ─── Tier 4: contract execution, rate loading and go-live ─────────────────────

def sign_as_carrier(contract_id: str, carrier_id: str) -> Dict[str, Any]:
    """Applies the carrier's own signature to its contract."""
    return get_success_data(
        api_client.sign_contract_as_carrier(
            contract_id, make_carrier_rep_headers(carrier_id)
        )
    )


def sign_as_shipper(contract_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Applies the shipper's countersignature as a contract administrator."""
    return get_success_data(
        api_client.sign_contract_as_shipper(
            contract_id, headers if headers is not None else CONTRACT_ADMIN
        )
    )


def fully_sign_contract(
    contract_id: str, carrier_id: str, shipper_headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Carrier signs, then the shipper countersigns, completing execution."""
    sign_as_carrier(contract_id, carrier_id)
    return sign_as_shipper(contract_id, shipper_headers)


def stage_rate_record(
    contract_id: str, lane_id: str, carrier_id: str, allocation_id: str, **overrides
) -> Dict[str, Any]:
    """Stages one rate record against a contract."""
    return get_success_data(
        api_client.create_rate_record(
            contract_id,
            rate_record_payload(lane_id, carrier_id, allocation_id, **overrides),
            CONTRACT_ADMIN,
        )
    )


def load_rate_record(rate_record_id: str) -> Dict[str, Any]:
    """Loads a staged rate record after the interval-collision check."""
    return get_success_data(api_client.load_rate_record(rate_record_id, CONTRACT_ADMIN))


def go_live(rate_record_id: str) -> Dict[str, Any]:
    """Takes a loaded rate record live on a fully signed contract."""
    return get_success_data(
        api_client.go_live_rate_record(rate_record_id, CONTRACT_ADMIN)
    )


def setup_staged_rate_record(
    rate_overrides: Optional[Dict[str, Any]] = None, **award_kwargs
) -> Dict[str, Any]:
    """Awarded event plus one staged rate record on the first lane.

    Adds ``rate_record`` and refreshes ``contract``.
    """
    ctx = setup_awarded_event(**award_kwargs)
    ctx["rate_record"] = stage_rate_record(
        ctx["contract"]["id"],
        ctx["lane"]["id"],
        ctx["carrier"]["id"],
        ctx["allocation"]["id"],
        **(rate_overrides or {}),
    )
    ctx["contract"] = get_success_data(
        api_client.get_contract(ctx["contract"]["id"], CONTRACT_ADMIN)
    )
    return ctx


def setup_live_rate_record(
    rate_overrides: Optional[Dict[str, Any]] = None,
    go_live_clock: str = CLOCK_GO_LIVE,
    shipper_headers: Optional[Dict] = None,
    **award_kwargs
) -> Dict[str, Any]:
    """Staged rate record -> both signatures -> loaded -> live.

    The clock is advanced to `go_live_clock` before the cutover so the instant
    falls inside the record's half-open effective interval. Adds ``rate_record``
    (LIVE) and refreshes ``contract``, ``allocation``, ``lane`` and ``event``.
    """
    ctx = setup_staged_rate_record(rate_overrides=rate_overrides, **award_kwargs)
    ctx["contract"] = fully_sign_contract(
        ctx["contract"]["id"], ctx["carrier"]["id"], shipper_headers
    )
    load_rate_record(ctx["rate_record"]["id"])
    set_clock(go_live_clock)
    ctx["rate_record"] = go_live(ctx["rate_record"]["id"])
    ctx["contract"] = get_success_data(
        api_client.get_contract(ctx["contract"]["id"], CONTRACT_ADMIN)
    )
    ctx["allocation"] = get_success_data(
        api_client.get_award_allocation(ctx["allocation"]["id"], ANALYST)
    )
    ctx["lane"] = get_success_data(api_client.get_lane(ctx["lane"]["id"], ANALYST))
    ctx["event"] = get_success_data(
        api_client.get_bid_event(ctx["event"]["id"], ANALYST)
    )
    return ctx


# ─── Tier 5: tendering and mini-bids ──────────────────────────────────────────

def append_tender(
    rate_record_id: str, load_reference: str, outcome: str = "ACCEPTED", **overrides
) -> Dict[str, Any]:
    """Appends one tender outcome to a live rate record."""
    return get_success_data(
        api_client.create_tender_event(
            rate_record_id,
            tender_event_payload(load_reference, outcome=outcome, **overrides),
            ANALYST,
        )
    )


def append_tenders(rate_record_id: str, outcomes: List[str]) -> List[Dict[str, Any]]:
    """Appends one tender per entry of `outcomes`, numbering the load references."""
    appended = []
    for index, outcome in enumerate(outcomes, start=1):
        overrides = {"reject_reason": "No capacity"} if outcome == "REJECTED" else {}
        appended.append(
            append_tender(
                rate_record_id, f"LD-{index:04d}", outcome=outcome, **overrides
            )
        )
    return appended


def setup_tendered_rate_record(
    outcomes: List[str],
    rate_overrides: Optional[Dict[str, Any]] = None,
    **award_kwargs
) -> Dict[str, Any]:
    """Live rate record with `outcomes` already appended to its tender log.

    Adds ``tenders`` and refreshes ``rate_record``, ``allocation`` and ``lane``.
    """
    ctx = setup_live_rate_record(rate_overrides=rate_overrides, **award_kwargs)
    ctx["tenders"] = append_tenders(ctx["rate_record"]["id"], outcomes)
    ctx["rate_record"] = get_success_data(
        api_client.get_rate_record(ctx["rate_record"]["id"], CONTRACT_ADMIN)
    )
    ctx["allocation"] = get_success_data(
        api_client.get_award_allocation(ctx["allocation"]["id"], ANALYST)
    )
    ctx["lane"] = get_success_data(api_client.get_lane(ctx["lane"]["id"], ANALYST))
    return ctx


def request_mini_bid(
    event_id: str, lane_id: str, rate_record_id: str, **overrides
) -> Dict[str, Any]:
    """Opens a mini-bid window by hand as a category manager."""
    return get_success_data(
        api_client.create_mini_bid(
            mini_bid_payload(event_id, lane_id, rate_record_id, **overrides),
            CATEGORY_MANAGER,
        )
    )


def propose_mini_bid_rate(
    mini_bid_id: str, carrier_id: str, **overrides
) -> Dict[str, Any]:
    """Proposes a replacement rate as the owning carrier representative."""
    return get_success_data(
        api_client.propose_mini_bid_rate(
            mini_bid_id,
            mini_bid_proposal_payload(carrier_id, **overrides),
            make_carrier_rep_headers(carrier_id),
        )
    )


def apply_mini_bid(mini_bid_id: str, contract_version: int, **overrides) -> Dict[str, Any]:
    """Applies an open mini-bid under the contract version guard."""
    return get_success_data(
        api_client.apply_mini_bid(
            mini_bid_id,
            mini_bid_apply_payload(contract_version, **overrides),
            CONTRACT_ADMIN,
        )
    )


def setup_open_mini_bid(
    proposed_rate_per_mile: float = 2.1000,
    mini_bid_overrides: Optional[Dict[str, Any]] = None,
    proposal_clock: str = "2026-09-05T00:00:00Z",
    tender_outcomes: Optional[List[str]] = None,
    **live_kwargs
) -> Dict[str, Any]:
    """Live rate record -> requested mini-bid -> carrier proposal (status `OPEN`).

    The clock is moved to `proposal_clock`, which must sit inside the mini-bid's
    closed window. Adds ``mini_bid`` and refreshes ``contract``.
    """
    if tender_outcomes is not None:
        ctx = setup_tendered_rate_record(tender_outcomes, **live_kwargs)
    else:
        ctx = setup_live_rate_record(**live_kwargs)
    mini_bid = request_mini_bid(
        ctx["event"]["id"],
        ctx["lane"]["id"],
        ctx["rate_record"]["id"],
        **(mini_bid_overrides or {}),
    )
    set_clock(proposal_clock)
    ctx["mini_bid"] = propose_mini_bid_rate(
        mini_bid["id"],
        ctx["carrier"]["id"],
        proposed_rate_per_mile=proposed_rate_per_mile,
    )
    ctx["contract"] = get_success_data(
        api_client.get_contract(ctx["contract"]["id"], CONTRACT_ADMIN)
    )
    return ctx


def setup_applied_mini_bid(
    proposed_rate_per_mile: float = 2.1000,
    apply_overrides: Optional[Dict[str, Any]] = None,
    **open_kwargs
) -> Dict[str, Any]:
    """Open mini-bid -> applied, superseding the old rate and amending the contract.

    Adds ``replacement_record``, ``value_before`` and refreshes ``mini_bid``,
    ``contract`` and ``rate_record`` (now `SUPERSEDED`).
    """
    ctx = setup_open_mini_bid(
        proposed_rate_per_mile=proposed_rate_per_mile, **open_kwargs
    )
    ctx["value_before"] = ctx["contract"]["total_committed_value_usd"]
    ctx["mini_bid"] = apply_mini_bid(
        ctx["mini_bid"]["id"],
        ctx["contract"]["version"],
        **(apply_overrides or {}),
    )
    ctx["contract"] = get_success_data(
        api_client.get_contract(ctx["contract"]["id"], CONTRACT_ADMIN)
    )
    ctx["rate_record"] = get_success_data(
        api_client.get_rate_record(ctx["rate_record"]["id"], CONTRACT_ADMIN)
    )
    if ctx["mini_bid"].get("applied_rate_record_id"):
        ctx["replacement_record"] = get_success_data(
            api_client.get_rate_record(
                ctx["mini_bid"]["applied_rate_record_id"], CONTRACT_ADMIN
            )
        )
    return ctx


# ─── Shared literal helpers ───────────────────────────────────────────────────

def second_carrier_overrides(**extra) -> Dict[str, Any]:
    """Registration overrides for a distinct second carrier ("Beta Trucking")."""
    overrides = {
        "legal_name": TEST_DEFAULTS["CARRIER_B_LEGAL_NAME"],
        "scac_code": TEST_DEFAULTS["CARRIER_B_SCAC"],
    }
    overrides.update(extra)
    return overrides


def full_contract_window() -> Dict[str, str]:
    """The event-wide contract window, as copied onto contracts and rates."""
    return {
        "effective_from": CONTRACT_EFFECTIVE_FROM,
        "effective_to": CONTRACT_EFFECTIVE_TO,
    }


def read_event(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_bid_event(event_id, ANALYST))


def read_lane(lane_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_lane(lane_id, ANALYST))


def read_carrier(carrier_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_carrier(carrier_id, ANALYST))


def read_contract(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_contract(contract_id, CONTRACT_ADMIN))


def read_rate_record(rate_record_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_rate_record(rate_record_id, CONTRACT_ADMIN))


def read_mini_bid(mini_bid_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_mini_bid(mini_bid_id, CATEGORY_MANAGER))


def read_allocation(allocation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_award_allocation(allocation_id, ANALYST))


def read_lane_bid(bid_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_lane_bid(bid_id, ANALYST))


# ─── The canonical two-lane portfolio ─────────────────────────────────────────

#: Lane A: 1147 dry-van miles, 550 planned loads, incumbent at 2.4000 per mile.
LANE_A_WITH_INCUMBENT = {
    "seasonality_peak_index": TEST_DEFAULTS["LANE_A_SEASONALITY_PEAK_INDEX"],
    "incumbent_carrier_id": CARRIER_ID_REF,
    "incumbent_rate_per_mile": TEST_DEFAULTS["LANE_A_INCUMBENT_RATE_PER_MILE"],
}

#: Lane B: 600 reefer miles, 120 planned loads, no incumbent baseline.
LANE_B_REEFER = {
    "lane_code": TEST_DEFAULTS["LANE_B_CODE"],
    "origin_zip3": "606",
    "dest_zip3": "802",
    "equipment_type": "REEFER",
    "mileage": TEST_DEFAULTS["LANE_B_MILEAGE"],
    "annual_volume_loads": TEST_DEFAULTS["LANE_B_ANNUAL_VOLUME_LOADS"],
    "service_days_required": TEST_DEFAULTS["LANE_B_SERVICE_DAYS_REQUIRED"],
    "accessorial_history_usd_per_load": TEST_DEFAULTS["LANE_B_ACCESSORIAL_USD_PER_LOAD"],
    "trailing_12m_actual_loads": TEST_DEFAULTS["LANE_B_TRAILING_12M_ACTUAL_LOADS"],
    "seasonality_peak_index": TEST_DEFAULTS["LANE_B_SEASONALITY_PEAK_INDEX"],
}

#: The bid on lane A: 2.1152 per mile, 600 loads committed, three transit days.
BID_A = {
    "rate_per_mile": TEST_DEFAULTS["BID_A_RATE_PER_MILE"],
    "fuel_surcharge_included": True,
    "committed_volume_loads": TEST_DEFAULTS["BID_A_COMMITTED_VOLUME_LOADS"],
    "transit_days_offered": TEST_DEFAULTS["BID_A_TRANSIT_DAYS_OFFERED"],
}

#: The bid on lane B: 1.9000 per mile, 150 loads committed, two transit days.
BID_B = {
    "rate_per_mile": TEST_DEFAULTS["BID_B_RATE_PER_MILE"],
    "fuel_surcharge_included": True,
    "committed_volume_loads": TEST_DEFAULTS["BID_B_COMMITTED_VOLUME_LOADS"],
    "transit_days_offered": TEST_DEFAULTS["BID_B_TRANSIT_DAYS_OFFERED"],
}

#: A carrier able to haul both of the two lanes' equipment types.
DUAL_MODE_CARRIER = {"service_modes": ["DRY_VAN", "REEFER"]}


def two_lane_awarded_event(**kwargs) -> Dict[str, Any]:
    """The canonical two-lane portfolio carried all the way to a committed award."""
    return setup_awarded_event(
        bid_overrides=[dict(BID_A), dict(BID_B)],
        carrier_overrides=dict(DUAL_MODE_CARRIER),
        lane_overrides=[dict(LANE_A_WITH_INCUMBENT), dict(LANE_B_REEFER)],
        **kwargs,
    )


def two_lane_closed_round(**kwargs) -> Dict[str, Any]:
    """The canonical two-lane portfolio with its single round closed."""
    return setup_closed_round_with_bid(
        bid_overrides=[dict(BID_A), dict(BID_B)],
        carrier_overrides=dict(DUAL_MODE_CARRIER),
        lane_overrides=[dict(LANE_A_WITH_INCUMBENT), dict(LANE_B_REEFER)],
        **kwargs,
    )


def two_lane_published_guide(**kwargs) -> Dict[str, Any]:
    """The canonical two-lane portfolio with its routing guide published."""
    return setup_published_routing_guide(
        bid_overrides=[dict(BID_A), dict(BID_B)],
        carrier_overrides=dict(DUAL_MODE_CARRIER),
        lane_overrides=[dict(LANE_A_WITH_INCUMBENT), dict(LANE_B_REEFER)],
        **kwargs,
    )
