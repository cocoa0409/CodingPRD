"""Composite setup helpers that build every precondition from scratch.

The harness restarts the API server and empties the database before every
individual test, and PRD section 2.4 fixes the logical clock at startup to
"exactly 2026-08-01T00:00:00Z".  No helper below caches anything across tests:
each one drives the public API from an empty database.

Every write guarded by an optimistic-concurrency token re-reads its parent
first, so the token is always the version the server currently holds rather
than a number this module tracked arithmetically.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import INITIAL_CLOCK
from .test_users import (
    CREDIT_OFFICER,
    DEAL_COMMITTEE,
    ORIGINATOR,
    REGISTRY_AGENT,
    SETTLEMENT_ANALYST,
    make_offtaker_rep_headers,
)

# ---------------------------------------------------------------------------
# Instant arithmetic on the logical clock
# ---------------------------------------------------------------------------


def _parse(instant: str) -> datetime:
    body = instant.strip()
    assert body.endswith("Z"), f"expected a UTC instant, got {instant!r}"
    return datetime.fromisoformat(body[:-1]).replace(tzinfo=timezone.utc)


def _render(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_plus(instant: str, days: int = 0, hours: int = 0,
             seconds: int = 0) -> str:
    """The instant shifted by the offset, a day being exactly 86,400 seconds."""
    return _render(_parse(instant) + timedelta(days=days, hours=hours,
                                               seconds=seconds))


def date_of(instant: str) -> str:
    """The calendar date part of an instant, as YYYY-MM-DD."""
    return instant[:10]


# The condition-precedent template deadlines a deal executed at the startup
# clock receives: 270, 540 and 720 days on from 2026-08-01T00:00:00Z.
CP_PERMITTING_DEADLINE = iso_plus(INITIAL_CLOCK, days=270)
CP_INTERCONNECTION_DEADLINE = iso_plus(INITIAL_CLOCK, days=540)
CP_NOTICE_TO_PROCEED_DEADLINE = iso_plus(INITIAL_CLOCK, days=720)
CP_REGISTRY_ACCOUNT_DEADLINE = iso_plus(INITIAL_CLOCK, days=60)

#: Ten days on from the startup clock: the support cure deadline.
SUPPORT_CURE_DEADLINE = iso_plus(INITIAL_CLOCK, days=10)
#: Fifteen days on from the startup clock: a failed condition's cure deadline.
CP_CURE_DEADLINE = iso_plus(INITIAL_CLOCK, days=15)

#: The default deal's outside date, and that date extended by one waiver.
DEFAULT_COD = "2029-12-31T00:00:00Z"
DEFAULT_COD_AFTER_ONE_WAIVER = iso_plus(DEFAULT_COD, days=30)


def set_clock(api, instant: str) -> Dict[str, Any]:
    """Move the logical clock, which mutates no entity."""
    response = api.set_current_utc(f.clock_payload(instant), ORIGINATOR)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def read_deal(api, deal_id: str, headers=ORIGINATOR) -> Dict[str, Any]:
    """A fresh read of the deal, the source of every concurrency token."""
    return get_success_data(api.get_deal(deal_id, headers), 200)


def deal_version(api, deal_id: str) -> int:
    return read_deal(api, deal_id)["version"]


def read_project(api, project_id: str, headers=ORIGINATOR) -> Dict[str, Any]:
    return get_success_data(api.get_project(project_id, headers), 200)


def read_offtaker(api, offtaker_id: str, headers=ORIGINATOR) -> Dict[str, Any]:
    return get_success_data(api.get_offtaker(offtaker_id, headers), 200)


def read_period(api, period_id: str, headers=SETTLEMENT_ANALYST) -> Dict[str, Any]:
    return get_success_data(api.get_settlement_period(period_id, headers), 200)


def period_version(api, period_id: str) -> int:
    return read_period(api, period_id)["version"]


def list_all(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 1 — single entities
# ---------------------------------------------------------------------------


def create_node(api, **overrides) -> Dict[str, Any]:
    """One CAISO settlement node."""
    response = api.create_pricing_node(f.pricing_node_payload(**overrides),
                                       ORIGINATOR)
    return get_success_data(response, 201)


def create_hub(api, **overrides) -> Dict[str, Any]:
    """One CAISO trading hub."""
    response = api.create_pricing_node(f.hub_payload(**overrides), ORIGINATOR)
    return get_success_data(response, 201)


def create_offtaker(api, **overrides) -> Dict[str, Any]:
    """A buyer in `DRAFT`, for which "no scoring runs at creation"."""
    response = api.create_offtaker(f.offtaker_payload(**overrides), ORIGINATOR)
    return get_success_data(response, 201)


def create_anchor_offtaker(api, **overrides) -> Dict[str, Any]:
    """The fully sustainable anchor buyer in `DRAFT`."""
    response = api.create_offtaker(f.anchor_offtaker_payload(**overrides),
                                   ORIGINATOR)
    return get_success_data(response, 201)


def submit_offtaker(api, offtaker_id: str) -> Dict[str, Any]:
    """Run the whole scoring chain, moving the buyer `DRAFT → UNDER_REVIEW`."""
    response = api.submit_offtaker_qualification(offtaker_id, ORIGINATOR)
    return get_success_data(response, 200)


def create_submitted_offtaker(api, anchor: bool = True,
                              **overrides) -> Dict[str, Any]:
    """A scored buyer sitting in `UNDER_REVIEW`."""
    builder = create_anchor_offtaker if anchor else create_offtaker
    buyer = builder(api, **overrides)
    return submit_offtaker(api, buyer["id"])


def decide_offtaker(api, offtaker_id: str, decision: str,
                    conditions: Optional[list] = None) -> Dict[str, Any]:
    response = api.decide_offtaker_qualification(
        offtaker_id, f.qualification_decision_payload(decision, conditions),
        CREDIT_OFFICER)
    return get_success_data(response, 200)


def create_qualified_offtaker(api, anchor: bool = True,
                              **overrides) -> Dict[str, Any]:
    """A buyer carried all the way to `QUALIFIED`."""
    buyer = create_submitted_offtaker(api, anchor=anchor, **overrides)
    return decide_offtaker(api, buyer["id"], "QUALIFY")


def create_conditional_offtaker(api, conditions: Optional[list] = None,
                                anchor: bool = True,
                                **overrides) -> Dict[str, Any]:
    """A buyer decided `CONDITIONAL`, which may be structured but not signed."""
    buyer = create_submitted_offtaker(api, anchor=anchor, **overrides)
    return decide_offtaker(api, buyer["id"], "CONDITIONAL",
                           conditions or ["Quarterly covenant certificate",
                                          "Parent support letter"])


def create_rejected_offtaker(api, anchor: bool = False,
                             **overrides) -> Dict[str, Any]:
    """A buyer decided `REJECT`, which is terminal."""
    buyer = create_submitted_offtaker(api, anchor=anchor, **overrides)
    return decide_offtaker(api, buyer["id"], "REJECT")


def create_project(api, node_id: str, **overrides) -> Dict[str, Any]:
    """A generation project, which "always begin[s] in `PRE_DEVELOPMENT`"."""
    response = api.create_project(f.project_payload(node_id, **overrides),
                                  ORIGINATOR)
    return get_success_data(response, 201)


MILESTONE_CHAIN = [
    ("PERMITTED", "CUP-2026-0442"),
    ("INTERCONNECTION_APPROVED", "LGIA-CAISO-2026-088"),
    ("NOTICE_TO_PROCEED", "NTP-KJ1-2026-11"),
    ("OPERATIONAL", "COD-KJ1-2027-06-28"),
]

#: The development status each milestone request lands in.  The notice-to-
#: proceed request word and the resulting state name are deliberately different.
MILESTONE_TARGET_STATUS = {
    "PERMITTED": "PERMITTED",
    "INTERCONNECTION_APPROVED": "INTERCONNECTION_APPROVED",
    "NOTICE_TO_PROCEED": "NTP_ISSUED",
    "OPERATIONAL": "OPERATIONAL",
}


def advance_milestone(api, project_id: str, milestone: str,
                      evidence_ref: Optional[str] = None,
                      headers=ORIGINATOR) -> Dict[str, Any]:
    response = api.advance_project_milestone(
        project_id, f.advance_milestone_payload(milestone, evidence_ref), headers)
    return get_success_data(response, 200)


def advance_project_to(api, project_id: str, target_status: str) -> Dict[str, Any]:
    """Walk the milestone chain until the project sits in `target_status`."""
    project = read_project(api, project_id)
    if project["status"] == target_status:
        return project
    for milestone, evidence in MILESTONE_CHAIN:
        project = advance_milestone(api, project_id, milestone, evidence)
        if project["status"] == target_status:
            return project
    raise AssertionError(f"{target_status} is not on the milestone chain")


def create_operational_project(api, node_id: str, **overrides) -> Dict[str, Any]:
    """A project walked through all four milestones to `OPERATIONAL`."""
    project = create_project(api, node_id, **overrides)
    return advance_project_to(api, project["id"], "OPERATIONAL")


# ---------------------------------------------------------------------------
# Tier 2 — the deal and its negotiation
# ---------------------------------------------------------------------------


def create_deal(api, project_id: str, anchor_offtaker_id: str,
                settlement_point_id: str, **overrides) -> Dict[str, Any]:
    """A new agreement in `DRAFT`, priced at creation."""
    response = api.create_deal(
        f.deal_payload(project_id, anchor_offtaker_id, settlement_point_id,
                       **overrides), ORIGINATOR)
    return get_success_data(response, 201)


def table_round(api, deal_id: str, **overrides) -> Dict[str, Any]:
    """Table a developer round, moving `DRAFT → TERM_SHEET_ISSUED`."""
    response = api.create_round(deal_id, f.round_payload(**overrides), ORIGINATOR)
    return get_success_data(response, 201)


def respond_accept(api, round_id: str, offtaker_id: str) -> Dict[str, Any]:
    """The buyer accepts, which "returns the answered round itself"."""
    response = api.respond_to_round(round_id, f.round_response_payload("ACCEPT"),
                                    make_offtaker_rep_headers(offtaker_id))
    return get_success_data(response, 200)


def respond_counter(api, round_id: str, offtaker_id: str,
                    counter_fixed_price_usd_per_mwh: float = 23.00,
                    **overrides) -> Dict[str, Any]:
    """The buyer counters, which "returns the newly created successor round"."""
    payload = f.round_response_payload(
        "COUNTER",
        **f.counter_terms(counter_fixed_price_usd_per_mwh, **overrides))
    response = api.respond_to_round(round_id, payload,
                                    make_offtaker_rep_headers(offtaker_id))
    return get_success_data(response, 200)


def propose_allocation(api, deal_id: str, offtaker_id: str, allocated_mw: float,
                       **overrides) -> Dict[str, Any]:
    """Propose one slice, reading the deal first for its concurrency token."""
    token = deal_version(api, deal_id)
    response = api.create_allocation(
        deal_id, f.allocation_payload(offtaker_id, allocated_mw, token,
                                      **overrides), ORIGINATOR)
    return get_success_data(response, 201)


def confirm_allocation(api, allocation_id: str, offtaker_id: str) -> Dict[str, Any]:
    """Each buyer decides on its own slice, and only its own."""
    response = api.decide_allocation(
        allocation_id, f.allocation_decision_payload("CONFIRM"),
        make_offtaker_rep_headers(offtaker_id))
    return get_success_data(response, 200)


def withdraw_allocation(api, allocation_id: str, offtaker_id: str) -> Dict[str, Any]:
    response = api.decide_allocation(
        allocation_id, f.allocation_decision_payload("WITHDRAW"),
        make_offtaker_rep_headers(offtaker_id))
    return get_success_data(response, 200)


def confirmed_allocation(api, deal_id: str, offtaker_id: str,
                         allocated_mw: float, **overrides) -> Dict[str, Any]:
    """Propose and confirm one slice in a single step."""
    slice_row = propose_allocation(api, deal_id, offtaker_id, allocated_mw,
                                   **overrides)
    return confirm_allocation(api, slice_row["id"], offtaker_id)


# ---------------------------------------------------------------------------
# Tier 2 — credit
# ---------------------------------------------------------------------------


def submit_credit(api, deal_id: str) -> Dict[str, Any]:
    """Submit for underwriting, which sizes `credit_support_required_usd`."""
    response = api.submit_deal_credit(deal_id, ORIGINATOR)
    return get_success_data(response, 200)


def decide_credit(api, deal_id: str, decision: str = "APPROVE",
                  headers=CREDIT_OFFICER) -> Dict[str, Any]:
    response = api.decide_deal_credit(deal_id,
                                      f.credit_decision_payload(decision),
                                      headers)
    return get_success_data(response, 200)


def register_cash(api, deal_id: str, face_amount_usd: float,
                  **overrides) -> Dict[str, Any]:
    """Register cash collateral, which "computes nothing"."""
    response = api.register_credit_support(
        deal_id, f.cash_collateral_payload(face_amount_usd, **overrides),
        ORIGINATOR)
    return get_success_data(response, 201)


def register_letter_of_credit(api, deal_id: str, face_amount_usd: float,
                              **overrides) -> Dict[str, Any]:
    response = api.register_credit_support(
        deal_id, f.letter_of_credit_payload(face_amount_usd, **overrides),
        ORIGINATOR)
    return get_success_data(response, 201)


def register_parent_guarantee(api, deal_id: str, face_amount_usd: float,
                              guarantor_offtaker_id: str,
                              **overrides) -> Dict[str, Any]:
    response = api.register_credit_support(
        deal_id,
        f.parent_guarantee_payload(face_amount_usd, guarantor_offtaker_id,
                                   **overrides), ORIGINATOR)
    return get_success_data(response, 201)


def post_instrument(api, deal_id: str, instrument_id: str) -> Dict[str, Any]:
    """Post an instrument, reading the deal first for its concurrency token."""
    token = deal_version(api, deal_id)
    response = api.post_credit_support(
        instrument_id, f.post_credit_support_payload(token), CREDIT_OFFICER)
    return get_success_data(response, 200)


def post_cash(api, deal_id: str, face_amount_usd: float,
              **overrides) -> Dict[str, Any]:
    """Register and post cash collateral in one step."""
    instrument = register_cash(api, deal_id, face_amount_usd, **overrides)
    return post_instrument(api, deal_id, instrument["id"])


def release_instrument(api, instrument_id: str) -> Dict[str, Any]:
    response = api.release_credit_support(instrument_id, CREDIT_OFFICER)
    return get_success_data(response, 200)


def approve_credit(api, deal_id: str) -> Dict[str, Any]:
    """Submit and approve, posting nothing where the requirement is 0.00."""
    submit_credit(api, deal_id)
    return decide_credit(api, deal_id, "APPROVE")


# ---------------------------------------------------------------------------
# Tier 3 — execution, conditions precedent and termination
# ---------------------------------------------------------------------------


def execute_deal(api, deal_id: str, headers=DEAL_COMMITTEE) -> Dict[str, Any]:
    """Sign the agreement, generating its condition-precedent template."""
    response = api.execute_deal(deal_id, headers)
    return get_success_data(response, 200)


def conditions_of(api, deal_id: str, headers=ORIGINATOR,
                  params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    rows, _ = list_all(api.list_conditions_precedent(deal_id, headers, params))
    return rows


def condition_by_type(api, deal_id: str, cp_type: str) -> Dict[str, Any]:
    matches = [row for row in conditions_of(api, deal_id)
               if row["cp_type"] == cp_type]
    assert len(matches) == 1, (
        f"expected exactly one {cp_type} condition, got {len(matches)}"
    )
    return matches[0]


def satisfy_condition(api, condition_id: str, evidence_ref: str = "EV-0001",
                      headers=ORIGINATOR) -> Dict[str, Any]:
    response = api.resolve_condition_precedent(
        condition_id, f.cp_resolution_payload("SATISFY",
                                              evidence_ref=evidence_ref),
        headers)
    return get_success_data(response, 200)


def waive_condition(api, condition_id: str,
                    waiver_justification: str = "Committee waiver granted.",
                    headers=DEAL_COMMITTEE) -> Dict[str, Any]:
    response = api.resolve_condition_precedent(
        condition_id,
        f.cp_resolution_payload("WAIVE",
                                waiver_justification=waiver_justification),
        headers)
    return get_success_data(response, 200)


def fail_condition(api, condition_id: str, headers=ORIGINATOR) -> Dict[str, Any]:
    response = api.resolve_condition_precedent(
        condition_id, f.cp_resolution_payload("FAIL"), headers)
    return get_success_data(response, 200)


def recure_condition(api, condition_id: str, headers=ORIGINATOR) -> Dict[str, Any]:
    response = api.resolve_condition_precedent(
        condition_id, f.cp_resolution_payload("RECURE"), headers)
    return get_success_data(response, 200)


def terminate_deal(api, deal_id: str, termination_reason: str,
                   headers=DEAL_COMMITTEE) -> Dict[str, Any]:
    response = api.terminate_deal(deal_id,
                                  f.termination_payload(termination_reason),
                                  headers)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Tier 3 — settlement
# ---------------------------------------------------------------------------


def open_period(api, deal_id: str, period_start: str,
                period_end: str) -> Dict[str, Any]:
    """Open a period over a half-open window, snapshotting the netting method."""
    response = api.create_settlement_period(
        deal_id, f.settlement_period_payload(period_start, period_end),
        SETTLEMENT_ANALYST)
    return get_success_data(response, 201)


def post_interval(api, period_id: str, hour_start: str, metered_mwh: float,
                  node_price_usd_per_mwh: float = 30.00,
                  hub_price_usd_per_mwh: float = 30.00,
                  **overrides) -> Dict[str, Any]:
    """Post one hour, reading the period first for its concurrency token."""
    token = period_version(api, period_id)
    response = api.create_meter_interval(
        period_id,
        f.meter_interval_payload(hour_start, metered_mwh,
                                 node_price_usd_per_mwh,
                                 hub_price_usd_per_mwh, token, **overrides),
        SETTLEMENT_ANALYST)
    return get_success_data(response, 201)


def calculate_period(api, period_id: str) -> Dict[str, Any]:
    response = api.calculate_settlement_period(period_id, SETTLEMENT_ANALYST)
    return get_success_data(response, 200)


def advance_period(api, period_id: str, action: str,
                   dispute_reason: Optional[str] = None,
                   headers=SETTLEMENT_ANALYST) -> Dict[str, Any]:
    response = api.advance_settlement_period(
        period_id, f.period_advance_payload(action, dispute_reason), headers)
    return get_success_data(response, 200)


def intervals_of(api, period_id: str, headers=SETTLEMENT_ANALYST,
                 params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    rows, _ = list_all(api.list_meter_intervals(period_id, headers, params))
    return rows


# ---------------------------------------------------------------------------
# Tier 3 — environmental attributes
# ---------------------------------------------------------------------------


def mint_batch(api, period_id: str, quantity_mwh: int,
               registry: str = "WREGIS") -> Dict[str, Any]:
    response = api.mint_attributes(
        period_id, f.mint_attributes_payload(quantity_mwh, registry),
        REGISTRY_AGENT)
    return get_success_data(response, 201)


def transfer_batch(api, batch_id: str, transferred_to_offtaker_id: str,
                   **overrides) -> Dict[str, Any]:
    response = api.transfer_attribute_batch(
        batch_id, f.transfer_payload(transferred_to_offtaker_id, **overrides),
        REGISTRY_AGENT)
    return get_success_data(response, 200)


def cancel_batch_transfer(api, batch_id: str) -> Dict[str, Any]:
    response = api.cancel_attribute_transfer(batch_id, REGISTRY_AGENT)
    return get_success_data(response, 200)


def retire_batch(api, batch_id: str, claim_year: int) -> Dict[str, Any]:
    response = api.retire_attribute_batch(batch_id,
                                          f.retire_payload(claim_year),
                                          REGISTRY_AGENT)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Tier 3 — risk events
# ---------------------------------------------------------------------------


def file_risk_event(api, deal_id: str, event_type: str, window_start: str,
                    window_end: str, headers=ORIGINATOR,
                    **overrides) -> Dict[str, Any]:
    response = api.create_risk_event(
        deal_id,
        f.risk_event_payload(event_type, window_start, window_end, **overrides),
        headers)
    return get_success_data(response, 201)


def review_risk_event(api, event_id: str, decision: str,
                      allocation_outcome: Optional[str] = None,
                      price_adjustment_usd_per_mwh: Optional[float] = None
                      ) -> Dict[str, Any]:
    response = api.review_risk_event(
        event_id,
        f.risk_review_payload(decision, allocation_outcome,
                              price_adjustment_usd_per_mwh), DEAL_COMMITTEE)
    return get_success_data(response, 200)


def accepted_curtailment_claim(api, deal_id: str, window_start: str,
                               window_end: str,
                               allocation_outcome: str = "BUYER_BEARS"
                               ) -> Dict[str, Any]:
    """A closed-window curtailment claim carried through to `ACCEPTED`."""
    claim = file_risk_event(api, deal_id, "CURTAILMENT", window_start,
                            window_end)
    return review_risk_event(api, claim["id"], "ACCEPT", allocation_outcome)


# ---------------------------------------------------------------------------
# Tier 4 — the three reusable origination chains
#
# Each returns a mapping of the rows it built so that a test can name any of
# them.  Every chain rebuilds itself from an empty database.
# ---------------------------------------------------------------------------


def origination_chain(api, project_status: str = "PRE_DEVELOPMENT",
                      deal_overrides: Optional[Dict[str, Any]] = None,
                      project_overrides: Optional[Dict[str, Any]] = None,
                      buyer_overrides: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, Any]:
    """A node, a hub, a `QUALIFIED` anchor buyer, a project and a `DRAFT` deal.

    The deal is 25.000 MW at a 22.00 base with no escalation and shared basis,
    so its escalated base is 22.0000, its price tier is `LOW` and its contract
    price is 22.75.
    """
    node = create_node(api)
    hub = create_hub(api)
    buyer = create_qualified_offtaker(api, **(buyer_overrides or {}))
    project = create_project(api, node["id"], **(project_overrides or {}))
    if project_status != "PRE_DEVELOPMENT":
        project = advance_project_to(api, project["id"], project_status)
    deal = create_deal(api, project["id"], buyer["id"], node["id"],
                       **(deal_overrides or {}))
    return {"node": node, "hub": hub, "buyer": buyer, "project": project,
            "deal": deal}


def chain_a(api, **kwargs) -> Dict[str, Any]:
    """The `DRAFT` chain: node, hub, qualified buyer, project, priced deal."""
    return origination_chain(api, **kwargs)


def negotiated_chain(api, allocated_mw: Optional[float] = None,
                     **kwargs) -> Dict[str, Any]:
    """A deal carried to `TERMS_AGREED` with credit `APPROVED`.

    One developer round is tabled, the anchor buyer's slice covering the whole
    contracted capacity is proposed and confirmed, the round is accepted, and
    the credit package is submitted and approved.
    """
    chain = origination_chain(api, **kwargs)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]
    chain["round"] = table_round(
        api, deal_id,
        proposed_fixed_price_usd_per_mwh=chain["deal"]["base_fixed_price_usd_per_mwh"],
        proposed_escalation_pct_per_year=chain["deal"]["escalation_pct_per_year"],
        proposed_shape_product=chain["deal"]["shape_product"],
        proposed_basis_responsibility=chain["deal"]["basis_responsibility"])
    chain["allocation"] = confirmed_allocation(
        api, deal_id, buyer_id,
        allocated_mw if allocated_mw is not None
        else chain["deal"]["contracted_mw"])
    chain["round"] = respond_accept(api, chain["round"]["id"], buyer_id)
    submit_credit(api, deal_id)
    chain["deal"] = decide_credit(api, deal_id, "APPROVE")
    return chain


def chain_b(api, **kwargs) -> Dict[str, Any]:
    """The `TERMS_AGREED` chain with credit `APPROVED` and a confirmed slice."""
    return negotiated_chain(api, **kwargs)


def chain_c(api, **kwargs) -> Dict[str, Any]:
    """The `EFFECTIVE` chain: an operational project produces no conditions.

    "an already-`OPERATIONAL` project whose anchor buyer already holds a
    registry account produces the empty template", so execution moves the deal
    `TERMS_AGREED → EXECUTED → EFFECTIVE` inside the very same request.
    """
    kwargs.setdefault("project_status", "OPERATIONAL")
    chain = negotiated_chain(api, **kwargs)
    chain["deal"] = execute_deal(api, chain["deal"]["id"])
    return chain


def executed_chain_with_conditions(api, **kwargs) -> Dict[str, Any]:
    """An `EXECUTED` deal on a `PRE_DEVELOPMENT` project: three conditions.

    The anchor buyer holds a registry account, so the `REGISTRY_ACCOUNT` row is
    absent and the template carries `PERMITTING`, `INTERCONNECTION` and
    `NOTICE_TO_PROCEED` only.
    """
    kwargs.setdefault("project_status", "PRE_DEVELOPMENT")
    chain = negotiated_chain(api, **kwargs)
    chain["deal"] = execute_deal(api, chain["deal"]["id"])
    chain["conditions"] = conditions_of(api, chain["deal"]["id"])
    return chain


# ---------------------------------------------------------------------------
# Tier 5 — settlement chains on top of an effective deal
# ---------------------------------------------------------------------------


def effective_chain_with_period(api, period_start: str = "2026-08-01T00:00:00Z",
                                period_end: str = "2026-09-01T00:00:00Z",
                                **kwargs) -> Dict[str, Any]:
    """An `EFFECTIVE` deal with one `OPEN` settlement period."""
    chain = chain_c(api, **kwargs)
    chain["period"] = open_period(api, chain["deal"]["id"], period_start,
                                 period_end)
    return chain


def calculated_period_chain(api, hours: Optional[List[Dict[str, Any]]] = None,
                            period_start: str = "2026-08-01T00:00:00Z",
                            period_end: str = "2026-09-01T00:00:00Z",
                            **kwargs) -> Dict[str, Any]:
    """An `EFFECTIVE` deal whose one period has been calculated.

    ``hours`` is a list of keyword mappings passed straight to
    ``post_interval``; each entry must carry at least ``hour_start`` and
    ``metered_mwh``.
    """
    chain = effective_chain_with_period(api, period_start, period_end, **kwargs)
    chain["intervals"] = [
        post_interval(api, chain["period"]["id"], **hour)
        for hour in (hours or [{"hour_start": period_start,
                                "metered_mwh": 30.0000,
                                "node_price_usd_per_mwh": 25.00,
                                "hub_price_usd_per_mwh": 25.00}])
    ]
    chain["period"] = calculate_period(api, chain["period"]["id"])
    return chain


def minted_batch_chain(api, quantity_mwh: int = 30,
                       registry: str = "WREGIS", **kwargs) -> Dict[str, Any]:
    """A calculated period with one `MINTED` attribute batch."""
    chain = calculated_period_chain(api, **kwargs)
    chain["batch"] = mint_batch(api, chain["period"]["id"], quantity_mwh,
                               registry)
    return chain
