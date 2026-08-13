"""Composite setup helpers.

Each helper builds precondition state from an empty database using only
PRD-declared endpoints (the harness restarts the server before every test, so
nothing carries over). Setup calls use get_success_data so failures surface as
clear "Setup step failed" messages rather than confusing assertion errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_arrangement_payload,
    create_comm_item_payload,
    create_compliance_policy_payload,
    create_disclosure_payload,
    create_employee_payload,
    create_lexicon_policy_payload,
    create_order_payload,
    create_personal_trade_payload,
    create_restricted_entry_payload,
    create_review_payload,
    create_snapshot_payload,
    create_venue_payload,
    flat_tier,
)
from .test_users import (
    TEST_USERS,
    make_best_ex_analyst_headers,
    make_committee_member_headers,
    make_covered_employee_headers,
)

OPS = TEST_USERS["ops_admin_headers"]
CA = TEST_USERS["compliance_admin_headers"]
SA = TEST_USERS["surveillance_analyst_headers"]
FO = TEST_USERS["filing_officer_headers"]

_ref_counter = {"n": 0}


def _next_ref(prefix: str) -> str:
    _ref_counter["n"] += 1
    return f"{prefix}-{_ref_counter['n']}"


# ---------------------------------------------------------------------------
# Tier 1: basic entity creation and state progression
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4). Returns the response data."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


def ops_run():
    """Fire the ops-run checkpoint (PRD §2.4). Returns the tally object."""
    return get_success_data(api_client.ops_run(OPS))


def make_employee(employee_ref=None, attestation_due_at="2027-01-01T00:00:00Z",
                  full_name="Test Employee", department="TRADING") -> dict:
    """Create a covered employee (employment ACTIVE; attestation computed from
    the logical clock, PRD §3.1). Returns the employee."""
    payload = create_employee_payload(
        full_name=full_name,
        employee_ref=employee_ref or _next_ref("EMP"),
        department=department,
        attestation_due_at=attestation_due_at,
    )
    return get_success_data(api_client.create_employee(payload, CA))


def make_venue(venue_code=None, name="Test Venue", venue_type="EXCHANGE") -> dict:
    """Create a venue (born ACTIVE, PRD §3.2)."""
    payload = create_venue_payload(
        venue_code=venue_code or _next_ref("VEN"),
        name=name,
        venue_type=venue_type,
    )
    return get_success_data(api_client.create_venue(payload, CA))


def make_arrangement(venue_id, effective_from="2026-08-01T00:00:00Z",
                     effective_to="2026-09-01T00:00:00Z",
                     pfof_tiers=None, routing_fee_bps=2) -> dict:
    """Create a routing arrangement (born NEGOTIATION, PRD §3.2)."""
    payload = create_arrangement_payload(
        venue_id,
        effective_from=effective_from,
        effective_to=effective_to,
        pfof_tiers=pfof_tiers if pfof_tiers is not None else flat_tier(),
        routing_fee_bps=routing_fee_bps,
    )
    return get_success_data(api_client.create_arrangement(payload, CA))


def activate_arrangement(arrangement_id) -> dict:
    """NEGOTIATION -> ACTIVE (PRD §3.2)."""
    return get_success_data(
        api_client.arrangement_transition(arrangement_id, {"to_status": "ACTIVE"}, CA)
    )


def make_active_arrangement(venue_id, **kwargs) -> dict:
    """Create + activate an arrangement. Returns the ACTIVE arrangement."""
    arrangement = make_arrangement(venue_id, **kwargs)
    return activate_arrangement(arrangement["id"])


def make_order(arrangement_id=None, execute=None, **overrides) -> dict:
    """Create an order; optionally route it; optionally execute it.

    execute is a dict {price_cents, executed_at} — the caller must have set the
    logical clock to >= executed_at beforehand (PRD §3.2 execution window).
    """
    order = get_success_data(api_client.create_order(create_order_payload(**overrides), OPS))
    if arrangement_id is not None:
        order = get_success_data(api_client.order_transition(
            order["id"], {"to_status": "ROUTED", "arrangement_id": arrangement_id}, OPS))
    if execute is not None:
        order = get_success_data(api_client.order_transition(
            order["id"],
            {"to_status": "EXECUTED",
             "executed_price_cents": execute["price_cents"],
             "executed_at": execute["executed_at"]},
            OPS,
        ))
    return order


def make_snapshot(venue_id, order_type="MARKET", period_month="2026-08",
                  variant="FAR_TOUCH", lock=False) -> dict:
    """Create a snapshot bucket (born PROVISIONAL, PRD §3.3); optionally lock."""
    snap = get_success_data(api_client.create_snapshot(
        create_snapshot_payload(venue_id, order_type=order_type,
                                period_month=period_month, variant=variant), CA))
    if lock:
        snap = get_success_data(api_client.lock_snapshot(snap["id"], CA))
    return snap


def make_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL") -> dict:
    """Create a DRAFT disclosure (revision 1, PRD §3.4)."""
    return get_success_data(api_client.create_disclosure(
        create_disclosure_payload(quarter=quarter, pricing_variant=pricing_variant), FO))


def transition_disclosure(disclosure_id, to_status) -> dict:
    return get_success_data(
        api_client.disclosure_transition(disclosure_id, {"to_status": to_status}, FO))


def make_published_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL") -> dict:
    """DRAFT -> PENDING_APPROVAL -> PUBLISHED (PRD §3.4)."""
    d = make_disclosure(quarter=quarter, pricing_variant=pricing_variant)
    d = transition_disclosure(d["id"], "PENDING_APPROVAL")
    return transition_disclosure(d["id"], "PUBLISHED")


def make_personal_trade(employee_id, symbol="ACME", side="BUY", quantity=50) -> dict:
    """Request preclearance as the owning CoveredEmployee (PRD §3.6)."""
    headers = make_covered_employee_headers(employee_id)
    return get_success_data(api_client.create_personal_trade(
        create_personal_trade_payload(symbol=symbol, side=side, quantity=quantity), headers))


def approve_trade(trade_id) -> dict:
    return get_success_data(api_client.personal_trade_transition(
        trade_id, {"to_status": "APPROVED"}, CA))


def report_trade_execution(trade_id, employee_id, executed_price_cents, executed_at) -> dict:
    headers = make_covered_employee_headers(employee_id)
    return get_success_data(api_client.personal_trade_transition(
        trade_id,
        {"to_status": "EXECUTION_REPORTED",
         "executed_price_cents": executed_price_cents,
         "executed_at": executed_at},
        headers,
    ))


def reconcile_trade(trade_id) -> dict:
    return get_success_data(api_client.personal_trade_transition(
        trade_id, {"to_status": "RECONCILED"}, CA))


def make_lexicon_active(terms, name="LX") -> dict:
    """Create a lexicon policy and activate it (DRAFT -> ACTIVE retires the
    previously ACTIVE policy, PRD §3.8). Returns the ACTIVE policy."""
    policy = get_success_data(api_client.create_lexicon_policy(
        create_lexicon_policy_payload(name=name, terms=terms), CA))
    return get_success_data(api_client.patch_lexicon_policy(
        policy["id"],
        {"expected_lexicon_policy_version": policy["version"], "to_status": "ACTIVE"},
        CA,
    ))


def make_comm_item(author_employee_id, body_text, channel="EMAIL") -> dict:
    """Capture a communication; scored and auto-tiered at creation (PRD §3.8)."""
    return get_success_data(api_client.create_comm_item(
        create_comm_item_payload(author_employee_id, channel=channel, body_text=body_text),
        OPS,
    ))


def publish_policy(policy_code="PAT", version_label="v2026.1", title="Personal Account Trading") -> dict:
    """Create + publish a compliance policy (fans out training, PRD §3.9)."""
    policy = get_success_data(api_client.create_compliance_policy(
        create_compliance_policy_payload(policy_code=policy_code, title=title,
                                         version_label=version_label), CA))
    return get_success_data(api_client.publish_compliance_policy(policy["id"], CA))


# ---------------------------------------------------------------------------
# Tier 2/3: hierarchy + lifecycle composites
# ---------------------------------------------------------------------------

def setup_venue_with_active_arrangement(venue_code=None, name="Test Venue",
                                        venue_type="EXCHANGE",
                                        effective_from="2026-08-01T00:00:00Z",
                                        effective_to="2026-09-01T00:00:00Z",
                                        pfof_tiers=None, routing_fee_bps=2):
    """Venue (ACTIVE) + one ACTIVE arrangement. Returns (venue, arrangement)."""
    venue = make_venue(venue_code=venue_code, name=name, venue_type=venue_type)
    arrangement = make_active_arrangement(
        venue["id"], effective_from=effective_from, effective_to=effective_to,
        pfof_tiers=pfof_tiers, routing_fee_bps=routing_fee_bps,
    )
    return venue, arrangement


def list_alerts(params=None):
    """Paginated alert list (PRD §4). Returns (data_list, meta)."""
    return validate_paginated(api_client.list_alerts(SA, params=params))


def list_cases(params=None):
    """Paginated case list (PRD §4). Returns (data_list, meta)."""
    return validate_paginated(api_client.list_cases(SA, params=params))


def setup_front_running_alert(trade_exec_at, order_exec_at, trade_qty=100, order_qty=100,
                              trade_side="BUY", order_side="BUY", symbol="ACME",
                              order_price_cents=10005,
                              clock_before_order_exec=None, clock_start="2026-08-03T14:00:00Z"):
    """Build one FRONT_RUNNING alert: an employee's EXECUTION_REPORTED trade
    followed by a matching client-order execution (forward scan, PRD §3.7).

    Returns dict(employee, trade, venue, arrangement, order, alert).
    """
    set_clock(clock_start)
    employee = make_employee()
    trade = make_personal_trade(employee["id"], symbol=symbol, side=trade_side, quantity=trade_qty)
    approve_trade(trade["id"])
    trade = report_trade_execution(trade["id"], employee["id"], 10000, trade_exec_at)
    venue, arrangement = setup_venue_with_active_arrangement()
    order = make_order(arrangement_id=arrangement["id"], symbol=symbol, side=order_side,
                       quantity=order_qty, order_type="MARKET")
    if clock_before_order_exec:
        set_clock(clock_before_order_exec)
    order = get_success_data(api_client.order_transition(
        order["id"],
        {"to_status": "EXECUTED",
         "executed_price_cents": order_price_cents,
         "executed_at": order_exec_at},
        OPS,
    ))
    alerts, meta = list_alerts({"related_order_id": order["id"]})
    assert len(alerts) == 1, f"expected exactly one alert for the order, got {len(alerts)}"
    return {
        "employee": employee, "trade": trade, "venue": venue,
        "arrangement": arrangement, "order": order, "alert": alerts[0],
    }


def escalate_alert_to_case(alert_id) -> dict:
    """ACKNOWLEDGE then ESCALATE an alert; returns the escalated alert whose
    case_id now points at the linked-or-created case (PRD §3.7)."""
    get_success_data(api_client.alert_transition(alert_id, {"to_status": "ACKNOWLEDGED"}, SA))
    return get_success_data(api_client.alert_transition(alert_id, {"to_status": "ESCALATED"}, SA))


def get_case_for_employee(employee_id) -> dict:
    """Fetch the single open case for a subject employee (PRD §3.7 maintains
    at most one open case per subject)."""
    cases, meta = list_cases({"subject_employee_id": employee_id})
    assert meta["total_count"] == 1, f"expected exactly one case, got {meta['total_count']}"
    return cases[0]


def setup_case_under_investigation():
    """Front-running alert (delta 900s, equal size, same side -> score 88)
    escalated into a case, case moved to UNDER_INVESTIGATION (PRD §3.7).
    Returns dict(employee, trade, order, alert, case)."""
    ctx = setup_front_running_alert(
        trade_exec_at="2026-08-03T14:30:00Z",
        order_exec_at="2026-08-03T14:45:00Z",
        clock_before_order_exec="2026-08-03T14:50:00Z",
    )
    alert = escalate_alert_to_case(ctx["alert"]["id"])
    case = get_case_for_employee(ctx["employee"]["id"])
    case = get_success_data(api_client.case_review_transition(
        case["id"], {"to_status": "UNDER_INVESTIGATION"}, SA))
    ctx["alert"] = alert
    ctx["case"] = case
    return ctx


def setup_comm_case(body_term_weight=100, clock_start=None):
    """Active lexicon with one term of the given weight; a comm item matching
    it auto-escalates and opens a COMM_REVIEW case on the author (PRD §3.8).
    Returns dict(employee, policy, item, case)."""
    if clock_start:
        set_clock(clock_start)
    employee = make_employee()
    policy = make_lexicon_active([{"term": "guarantee", "weight": body_term_weight}])
    item = make_comm_item(employee["id"], "guarantee")
    cases, meta = list_cases({"source_comm_item_id": item["id"]})
    assert meta["total_count"] == 1, "auto-escalation must create exactly one case"
    return {"employee": employee, "policy": policy, "item": item, "case": cases[0]}


def make_review_in_committee(quarter="2026-Q3", venue_codes=(), analyst_id="ba-1"):
    """Venue(s) ACTIVE + one LOCKED snapshot on the first venue + DRAFT review
    moved to IN_COMMITTEE (PRD §3.5). Returns dict(venues, snapshot, review)."""
    venues = [make_venue(venue_code=code) for code in (venue_codes or ["NYSE"])]
    snapshot = make_snapshot(venues[0]["id"], lock=True)
    decisions = [{"venue_id": v["id"], "determination": "CONTINUE"} for v in venues]
    review = get_success_data(api_client.create_review(
        create_review_payload([snapshot["id"]], decisions),
        make_best_ex_analyst_headers(analyst_id),
    ))
    review = get_success_data(api_client.review_transition(
        review["id"], {"to_status": "IN_COMMITTEE"}, make_best_ex_analyst_headers(analyst_id)))
    return {"venues": venues, "snapshot": snapshot, "review": review}


def make_review_approved(quarter="2026-Q3", venue_codes=(), analyst_id="ba-1",
                         voter_ids=("cm-1", "cm-2", "cm-3")):
    """Review driven to APPROVED by three distinct committee votes (quorum,
    PRD §3.5). Returns the make_review_in_committee dict with updated review."""
    ctx = make_review_in_committee(quarter=quarter, venue_codes=venue_codes, analyst_id=analyst_id)
    review = ctx["review"]
    for voter in voter_ids:
        review = get_success_data(api_client.vote_review(
            review["id"], make_committee_member_headers(voter)))
    ctx["review"] = review
    return ctx
