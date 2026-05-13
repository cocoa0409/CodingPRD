"""Composite setup helpers for the Government Procurement test suite.

The PRD describes a long-lived workflow:
  ProcurementPlan: DRAFT → UNDER_REVIEW → PUBLISHED → AMENDING → PUBLISHED → ARCHIVED
  PlanItem:        PROPOSED → APPROVED → PUBLISHED → EXECUTED
  Project:         DRAFT → PRESCREEN_OPEN → BIDDING_OPEN → BIDDING_CLOSED
                       → EVALUATING → AWARDED → CONTRACT_SIGNED
  TenderDocument:  DRAFT → PUBLISHED ⇌ CLARIFYING; PUBLISHED → AMENDING → PUBLISHED
  Bid:             SUBMITTED → OPENED → EVALUATED → AWARDED / LOST
  Committee:       FORMED → EVALUATING → FINALIZED
  Contract:        PENDING_SIGNATURE → ACTIVE → AMENDING ⇌ ACTIVE → EXECUTED / TERMINATED
  Complaint:       SUBMITTED → UNDER_REVIEW → UPHELD / DISMISSED

A typical test for "bid evaluation under COMPREHENSIVE_SCORING" needs
~15 API calls of setup. These helpers encapsulate the preambles.

PRD §2.1 identity threading (LOAD-BEARING):

  The Supplier role is entity_backed:Supplier. Every ownership-gated
  Supplier call (submit-bid, withdraw-bid, file-complaint, withdraw-
  complaint, submit-query) MUST use make_supplier_headers(<supplier_id>)
  where <supplier_id> is the id returned by POST /procurement/suppliers.
  Falling back to TEST_USERS["supplier_fallback_headers"] would set
  X-User-ID to a literal that does not match any real Supplier.id, so
  the ownership comparison (Bid.supplier_id == X-User-ID,
  Complaint.complainant_supplier_id == X-User-ID) would reject every
  call.

  Therefore every fixture in this module that creates a Supplier
  remembers the Supplier.id it produced and passes it through to
  make_supplier_headers() for every subsequent Supplier-role call.

Setup helpers use get_success_data (lenient validator) so a broken
precondition surfaces as a clear setup error rather than a confusing
assertion failure inside the test body.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    blacklist_supplier_payload,
    clock_advance_payload,
    comprehensive_scoring_evaluation_criteria,
    contract_amendment_payload,
    create_plan_item_payload,
    create_plan_payload,
    create_project_payload,
    create_supplier_payload,
    create_tender_document_payload,
    emit_event_payload,
    file_complaint_payload,
    file_contract_payload,
    form_committee_payload,
    lowest_price_evaluation_criteria,
    record_evaluation_payload,
    record_payment_payload,
    submit_bid_payload,
    submit_query_payload,
    uphold_complaint_payload,
)
from .test_users import (
    TEST_USERS,
    make_expert_headers,
    make_supplier_headers,
)


# ===========================================================================
# Cross-test clock isolation
# ===========================================================================
# PRD §2.4 mandates the server clock is forward-only. Because pytest tests
# share one server process (one DB, one clock) across the whole session,
# tests that hard-code ISO timestamps relative to a single anchor year
# (e.g., 2026) would only work for the first test; once a test advances
# the clock past 2026-03-01, every subsequent test that wants
# bid_submission_deadline=2026-03-01 would land on a deadline already in
# the past. To preserve PRD-fidelity of every individual test scenario
# (each test verifies a rule against its OWN project window, not against
# leftover clock state from a sibling test), the helpers shift all
# scenario timestamps by a per-test calendar-year offset that is computed
# from how far the live clock has moved. The offset is applied
# transparently to: (a) the timestamps passed to create_project, (b) the
# clock_origin advance issued by setup_project_*, and (c) every
# advance_clock(...) call routed through this module.
#
# The offset is recomputed on each new setup_project_* entry: it grows
# only forward, never backward, so the clock invariant is preserved.

_TEST_BASE_YEAR = 2026                # anchor used by all test ISO literals
_TEST_TIMELINE_SPAN_YEARS = 5         # max calendar span any one test uses
_CURRENT_YEAR_SHIFT = 0               # current global year-offset, mutated by setup


def _parse_iso(s: str) -> datetime:
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


def _shift_iso(iso_str: str) -> str:
    """Shift an ISO timestamp forward by _CURRENT_YEAR_SHIFT years.

    Callers must pass RAW (unshifted) test literals — never pass a value
    that has already been shifted by this helper."""
    if _CURRENT_YEAR_SHIFT == 0:
        return iso_str
    dt = _parse_iso(iso_str)
    # Skip very-low (epoch) timestamps so the 1970-anchored placeholder
    # passed to _read_server_clock() is left untouched.
    if dt.year < _TEST_BASE_YEAR - 50:
        return iso_str
    try:
        new = dt.replace(year=dt.year + _CURRENT_YEAR_SHIFT)
    except ValueError:
        # Feb-29 edge case — drop one day.
        new = dt.replace(month=2, day=28, year=dt.year + _CURRENT_YEAR_SHIFT)
    return _format_iso(new)


def _read_server_clock() -> datetime:
    """Read the current virtual clock by performing an idempotent advance."""
    # POST /_clock/advance is idempotent on identical target_iso. Pass the
    # current epoch (1970-01-01); the server returns its current_time
    # because the clock only moves forward.
    res = api_client.advance_clock(
        clock_advance_payload("1970-01-01T00:00:00.000Z"), OFFICER,
    )
    data = get_success_data(res)
    return _parse_iso(data["current_time"])


def _rebase_for_new_test() -> None:
    """Compute the year-shift required so that fresh-test ISO literals
    anchored at _TEST_BASE_YEAR land strictly after the current server
    clock. Idempotent: the shift only grows."""
    global _CURRENT_YEAR_SHIFT
    now = _read_server_clock()
    # We want _TEST_BASE_YEAR + _CURRENT_YEAR_SHIFT > now.year so test
    # literals like "2026-03-01" land in the future. Add the timeline-
    # span buffer so that within a single test, advance_clock(deadline)
    # also stays ahead.
    needed = (now.year - _TEST_BASE_YEAR) + _TEST_TIMELINE_SPAN_YEARS
    if needed > _CURRENT_YEAR_SHIFT:
        _CURRENT_YEAR_SHIFT = needed


# ===========================================================================
# Shared opaque-role headers
# ===========================================================================
OFFICER = TEST_USERS["officer_headers"]
OFFICER_ALT = TEST_USERS["officer_headers_alt"]
REGULATOR = TEST_USERS["regulator_headers"]
REGULATOR_ALT = TEST_USERS["regulator_headers_alt"]


# ===========================================================================
# Unique-id helpers
# ===========================================================================
def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_legal_name() -> str:
    return f"Supplier-{uuid.uuid4().hex[:8]} Co."


def unique_tax_id() -> str:
    return f"TAX-{uuid.uuid4().hex[:10]}"


# ===========================================================================
# Clock (PRD §2.4)
# ===========================================================================
def advance_clock(target_iso: str) -> Dict[str, Any]:
    """PRD §2.4: "an admin-only test-driving capability that accepts a
    target_iso parameter, moves current_time forward to that instant."

    The target ISO is rebased by the current year-shift so tests that
    advance to literal dates land on the shifted timeline established by
    the most recent setup_project_* call.
    """
    shifted = _shift_iso(target_iso)
    return get_success_data(
        api_client.advance_clock(clock_advance_payload(shifted), OFFICER),
    )


def blacklist_until_iso(target_iso: str) -> str:
    """Rebase a blacklist_until literal so it lines up with the shifted
    timeline established by the current test's setup_project_* call."""
    return _shift_iso(target_iso)


# ===========================================================================
# Tier 1: Supplier lifecycle
# ===========================================================================
def register_supplier(
    legal_name: Optional[str] = None,
    tax_id: Optional[str] = None,
    qualifications: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a Supplier in PENDING. Returns the supplier dict; callers
    MUST retain supplier["id"] and pass it into make_supplier_headers()
    for every ownership-gated supplier call.

    PRD §3.3: "A newly created supplier starts in PENDING registration
    with a default credit_score of 600 and a blacklist_until of null."
    """
    payload = create_supplier_payload(
        legal_name=legal_name or unique_legal_name(),
        tax_id=tax_id or unique_tax_id(),
        qualifications=qualifications,
    )
    return get_success_data(api_client.create_supplier(payload, OFFICER))


def verify_supplier(supplier_id: str) -> Dict[str, Any]:
    """PRD §3.3: "The procurement officer verifies the supplier by
    transitioning PENDING → VERIFIED."""
    return get_success_data(
        api_client.verify_supplier(supplier_id, OFFICER),
    )


def register_verified_supplier(
    qualifications: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Convenience: register + verify. Returns the verified supplier."""
    sup = register_supplier(qualifications=qualifications)
    verify_supplier(sup["id"])
    sup["registration_status"] = "VERIFIED"
    return sup


def set_credit_score(supplier_id: str, score: int) -> Dict[str, Any]:
    """Mirror an external credit-information event onto the supplier.
    PRD §2.4: "such events may update a supplier's credit_score."""
    return get_success_data(
        api_client.emit_event(
            emit_event_payload(
                "credit_information",
                {"supplier_id": supplier_id, "credit_score": int(score)},
            ),
            REGULATOR,
        ),
    )


def blacklist_supplier(
    supplier_id: str,
    until_iso: str,
) -> Dict[str, Any]:
    """PRD §3.3: "A regulator may at any point blacklist the supplier
    ... supplying a blacklist_until UTC timestamp."

    The until_iso is rebased by the current year-shift so a test that
    writes "2030-01-01" lands strictly after the shifted clock origin.
    """
    return get_success_data(
        api_client.blacklist_supplier(
            supplier_id,
            blacklist_supplier_payload(_shift_iso(until_iso)),
            REGULATOR,
        ),
    )


# ===========================================================================
# Tier 2: Plan / PlanItem state progression
# ===========================================================================
def create_draft_plan(
    agency_id: Optional[str] = None,
    fiscal_year: int = TEST_DEFAULTS["FISCAL_YEAR"],
) -> Dict[str, Any]:
    """Create a ProcurementPlan in DRAFT."""
    payload = create_plan_payload(
        agency_id=agency_id or _unique("agency"),
        fiscal_year=fiscal_year,
    )
    return get_success_data(api_client.create_plan(payload, OFFICER))


def add_plan_item(
    plan_id: str,
    title: Optional[str] = None,
    category: str = "GOODS",
    budget_cents: int = TEST_DEFAULTS["PLAN_ITEM_BUDGET_CENTS"],
) -> Dict[str, Any]:
    """PRD §3.1: PlanItem starts in PROPOSED."""
    payload = create_plan_item_payload(
        title=title or _unique("item"),
        category=category,
        budget_cents=budget_cents,
    )
    return get_success_data(
        api_client.add_plan_item(plan_id, payload, OFFICER),
    )


def submit_plan_for_review(plan_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.submit_plan_review(plan_id, OFFICER))


def approve_plan_item(item_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.approve_plan_item(item_id, OFFICER))


def reject_plan_item(item_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reject_plan_item(item_id, OFFICER))


def publish_plan(plan_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.publish_plan(plan_id, OFFICER))


def create_published_plan_with_items(
    num_items: int = 1,
    budget_cents: int = TEST_DEFAULTS["PLAN_ITEM_BUDGET_CENTS"],
    fiscal_year: int = TEST_DEFAULTS["FISCAL_YEAR"],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create plan in PUBLISHED with `num_items` PlanItems all in
    PUBLISHED status. Walks the full path DRAFT → UNDER_REVIEW → PUBLISHED.

    PRD §3.1: "the transition itself cascades the approved items from
    APPROVED to PUBLISHED."
    """
    plan = create_draft_plan(fiscal_year=fiscal_year)
    items = []
    for _ in range(num_items):
        items.append(add_plan_item(plan["id"], budget_cents=budget_cents))
    submit_plan_for_review(plan["id"])
    for item in items:
        approve_plan_item(item["id"])
    publish_plan(plan["id"])
    # Re-fetch items to capture PUBLISHED state.
    refreshed = []
    for item in items:
        # The PRD §4 list endpoint for items is not exposed; rely on
        # GET /plans/{id} to surface item state via cascade. Tests that
        # need accurate item objects re-read via GET /plans.
        refreshed.append({**item, "item_status": "PUBLISHED"})
    plan["status"] = "PUBLISHED"
    return plan, refreshed


# ===========================================================================
# Tier 3: Project + TenderDocument up through PRESCREEN_OPEN / BIDDING_OPEN
# ===========================================================================
def create_project(
    plan_item_id: str,
    evaluation_method: str = "LOWEST_PRICE",
    bid_submission_deadline: str = "2026-03-01T00:00:00.000Z",
    query_window_close_at: str = "2026-02-15T00:00:00.000Z",
    bid_opening_at: str = "2026-03-02T00:00:00.000Z",
    estimated_value_cents: int = TEST_DEFAULTS["ESTIMATED_VALUE_CENTS"],
    required_qualifications: Optional[List[str]] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.4: project is created against a PUBLISHED PlanItem.
    Project enters DRAFT."""
    payload = create_project_payload(
        plan_item_id=plan_item_id,
        title=title or _unique("project"),
        evaluation_method=evaluation_method,
        bid_submission_deadline=bid_submission_deadline,
        query_window_close_at=query_window_close_at,
        bid_opening_at=bid_opening_at,
        estimated_value_cents=estimated_value_cents,
        required_qualifications=required_qualifications or [],
    )
    return get_success_data(api_client.create_project(payload, OFFICER))


def create_tender_document(
    project_id: str,
    evaluation_method: str = "LOWEST_PRICE",
    technical_spec: str = TEST_DEFAULTS["TECHNICAL_SPEC"],
    commercial_spec: str = TEST_DEFAULTS["COMMERCIAL_SPEC"],
    template_id: str = TEST_DEFAULTS["TEMPLATE_ID"],
    weights: Optional[Dict[str, float]] = None,
    max_technical_score: int = TEST_DEFAULTS["MAX_TECHNICAL_SCORE"],
    max_qualification_score: int = TEST_DEFAULTS["MAX_QUALIFICATION_SCORE"],
) -> Dict[str, Any]:
    """PRD §3.4: Exactly one TenderDocument per project. Document enters
    DRAFT with domain-level version 1."""
    if evaluation_method == "LOWEST_PRICE":
        ec = lowest_price_evaluation_criteria()
    else:
        if weights is None:
            weights = {"price": 0.40, "technical": 0.40, "qualification": 0.20}
        ec = comprehensive_scoring_evaluation_criteria(
            weight_price=weights["price"],
            weight_technical=weights["technical"],
            weight_qualification=weights["qualification"],
            max_technical_score=max_technical_score,
            max_qualification_score=max_qualification_score,
        )
    payload = create_tender_document_payload(
        template_id=template_id,
        technical_spec=technical_spec,
        commercial_spec=commercial_spec,
        evaluation_criteria=ec,
    )
    return get_success_data(
        api_client.create_tender_document(project_id, payload, OFFICER),
    )


def publish_tender_document(tender_id: str) -> Dict[str, Any]:
    """PRD §3.4: tender DRAFT → PUBLISHED; cascades Project DRAFT →
    PRESCREEN_OPEN."""
    return get_success_data(
        api_client.publish_tender_document(tender_id, OFFICER),
    )


def open_bidding(project_id: str) -> Dict[str, Any]:
    """PRD §3.6: PRESCREEN_OPEN → BIDDING_OPEN; clock must be strictly
    before bid_submission_deadline."""
    return get_success_data(api_client.open_bidding(project_id, OFFICER))


def close_bidding(project_id: str) -> Dict[str, Any]:
    """PRD §3.6: BIDDING_OPEN → BIDDING_CLOSED; clock must be >=
    bid_submission_deadline."""
    return get_success_data(api_client.close_bidding(project_id, OFFICER))


def setup_project_prescreen_open(
    evaluation_method: str = "LOWEST_PRICE",
    bid_submission_deadline: str = "2026-03-01T00:00:00.000Z",
    query_window_close_at: str = "2026-02-15T00:00:00.000Z",
    bid_opening_at: str = "2026-03-02T00:00:00.000Z",
    required_qualifications: Optional[List[str]] = None,
    estimated_value_cents: int = TEST_DEFAULTS["ESTIMATED_VALUE_CENTS"],
    weights: Optional[Dict[str, float]] = None,
    max_technical_score: int = TEST_DEFAULTS["MAX_TECHNICAL_SCORE"],
    plan_budget_cents: int = TEST_DEFAULTS["PLAN_ITEM_BUDGET_CENTS"],
    commercial_spec: str = TEST_DEFAULTS["COMMERCIAL_SPEC"],
    clock_origin: str = TEST_DEFAULTS["CLOCK_T0"],
) -> Dict[str, Any]:
    """Full chain to a project in PRESCREEN_OPEN with its TenderDocument
    PUBLISHED at version=1. Returns {plan, item, project, tender,
    clock_t0}.

    Caller must advance the clock to a value strictly before
    bid_submission_deadline before calling open_bidding().
    """
    # Rebase the shared year-shift so this test's hard-coded date
    # literals (e.g., 2026-03-01) land strictly after the current
    # server clock — even if a previous test advanced past 2026.
    _rebase_for_new_test()
    shifted_deadline = _shift_iso(bid_submission_deadline)
    shifted_qwc = _shift_iso(query_window_close_at)
    shifted_opening = _shift_iso(bid_opening_at)
    shifted_origin = _shift_iso(clock_origin)
    # Advance to clock_origin (idempotent if already past).
    get_success_data(
        api_client.advance_clock(clock_advance_payload(shifted_origin), OFFICER),
    )
    plan, items = create_published_plan_with_items(
        num_items=1, budget_cents=plan_budget_cents,
    )
    item = items[0]
    project = create_project(
        plan_item_id=item["id"],
        evaluation_method=evaluation_method,
        bid_submission_deadline=shifted_deadline,
        query_window_close_at=shifted_qwc,
        bid_opening_at=shifted_opening,
        estimated_value_cents=estimated_value_cents,
        required_qualifications=required_qualifications,
    )
    tender = create_tender_document(
        project["id"],
        evaluation_method=evaluation_method,
        commercial_spec=commercial_spec,
        weights=weights,
        max_technical_score=max_technical_score,
    )
    tender = publish_tender_document(tender["id"])
    project["project_status"] = "PRESCREEN_OPEN"
    return {
        "plan": plan,
        "item": item,
        "project": project,
        "tender": tender,
        # Expose the raw (unshifted) clock_origin so callers that pass it
        # back into advance_clock() get re-shifted by the wrapper.
        "clock_t0": clock_origin,
    }


def setup_project_bidding_open(
    evaluation_method: str = "LOWEST_PRICE",
    bid_submission_deadline: str = "2026-03-01T00:00:00.000Z",
    query_window_close_at: str = "2026-02-15T00:00:00.000Z",
    bid_opening_at: str = "2026-03-02T00:00:00.000Z",
    required_qualifications: Optional[List[str]] = None,
    estimated_value_cents: int = TEST_DEFAULTS["ESTIMATED_VALUE_CENTS"],
    weights: Optional[Dict[str, float]] = None,
    max_technical_score: int = TEST_DEFAULTS["MAX_TECHNICAL_SCORE"],
    plan_budget_cents: int = TEST_DEFAULTS["PLAN_ITEM_BUDGET_CENTS"],
    commercial_spec: str = TEST_DEFAULTS["COMMERCIAL_SPEC"],
    clock_origin: str = TEST_DEFAULTS["CLOCK_T0"],
) -> Dict[str, Any]:
    """Same as setup_project_prescreen_open + open_bidding. Clock left
    at clock_origin (strictly before bid_submission_deadline)."""
    ctx = setup_project_prescreen_open(
        evaluation_method=evaluation_method,
        bid_submission_deadline=bid_submission_deadline,
        query_window_close_at=query_window_close_at,
        bid_opening_at=bid_opening_at,
        required_qualifications=required_qualifications,
        estimated_value_cents=estimated_value_cents,
        weights=weights,
        max_technical_score=max_technical_score,
        plan_budget_cents=plan_budget_cents,
        commercial_spec=commercial_spec,
        clock_origin=clock_origin,
    )
    ctx["project"] = open_bidding(ctx["project"]["id"])
    return ctx


# ===========================================================================
# Tier 4: Bid submission threading supplier identity
# ===========================================================================
def submit_bid(
    project_id: str,
    supplier_id: str,
    bid_price_cents: int = TEST_DEFAULTS["BID_PRICE_CENTS"],
    tender_document_version: int = 1,
    technical_score_raw: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.6: submits bid as the supplier. The X-User-ID header MUST
    be the supplier's id (entity_backed identity) per PRD §2.1."""
    payload = submit_bid_payload(
        supplier_id=supplier_id,
        tender_document_version=tender_document_version,
        bid_price_cents=bid_price_cents,
        technical_score_raw=technical_score_raw,
    )
    return get_success_data(
        api_client.submit_bid(
            project_id, payload, make_supplier_headers(supplier_id),
        ),
    )


def withdraw_bid(bid_id: str, supplier_id: str) -> Dict[str, Any]:
    """PRD §3.6: "the supplier's identity (X-User-ID) must match the
    bid's supplier_id."""
    return get_success_data(
        api_client.withdraw_bid(bid_id, make_supplier_headers(supplier_id)),
    )


# ===========================================================================
# Tier 5: Committee + evaluation + award
# ===========================================================================
def form_committee(
    project_id: str,
    requested_size: int = 3,
    selection_seed: str = "seed-001",
) -> Dict[str, Any]:
    """PRD §3.7: deterministic given selection_seed. Returns the
    committee dict including members[].expert_id values that tests must
    use as X-User-ID for record-evaluation."""
    payload = form_committee_payload(
        requested_size=requested_size, selection_seed=selection_seed,
    )
    return get_success_data(
        api_client.form_committee(project_id, payload, OFFICER),
    )


def open_bid_ceremony(project_id: str) -> Dict[str, Any]:
    """PRD §3.7: BIDDING_CLOSED → EVALUATING; opens bids; committee
    advances FORMED → EVALUATING."""
    return get_success_data(
        api_client.open_bid_ceremony(project_id, OFFICER),
    )


def record_evaluation(
    bid_id: str,
    expert_id: str,
    technical_score_raw: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.8: expert_id MUST match one of the committee.members[].
    expert_id values."""
    payload = record_evaluation_payload(
        technical_score_raw=technical_score_raw,
    )
    return get_success_data(
        api_client.record_evaluation(
            bid_id, payload, make_expert_headers(expert_id),
        ),
    )


def finalize_committee(committee_id: str) -> Dict[str, Any]:
    """PRD §3.8: EVALUATING → FINALIZED once every OPENED bid is
    EVALUATED."""
    return get_success_data(
        api_client.finalize_committee(committee_id, OFFICER),
    )


def decide_award(project_id: str) -> Dict[str, Any]:
    """PRD §3.9: EVALUATING → AWARDED. Returns the Award (DECIDED)."""
    return get_success_data(
        api_client.decide_award(project_id, OFFICER),
    )


def publish_award(award_id: str) -> Dict[str, Any]:
    """PRD §3.9: DECIDED → PUBLISHED."""
    return get_success_data(
        api_client.publish_award(award_id, OFFICER),
    )


# ===========================================================================
# Tier 6: End-to-end project-to-award scenarios.
# ===========================================================================
def setup_three_bids_submitted(
    evaluation_method: str = "LOWEST_PRICE",
    required_qualifications: Optional[List[str]] = None,
    bid_specs: Optional[List[Dict[str, Any]]] = None,
    bid_submission_deadline: str = "2026-03-01T00:00:00.000Z",
    query_window_close_at: str = "2026-02-15T00:00:00.000Z",
    bid_opening_at: str = "2026-03-02T00:00:00.000Z",
    estimated_value_cents: int = TEST_DEFAULTS["ESTIMATED_VALUE_CENTS"],
    weights: Optional[Dict[str, float]] = None,
    max_technical_score: int = TEST_DEFAULTS["MAX_TECHNICAL_SCORE"],
    clock_origin: str = TEST_DEFAULTS["CLOCK_T0"],
) -> Dict[str, Any]:
    """Drive to BIDDING_OPEN with 3 SUBMITTED bids by 3 verified
    suppliers. Returns {ctx (project/tender/etc.), suppliers (list of
    supplier dicts), bids (list of bid dicts)}.

    bid_specs is an optional list of {price, technical_score_raw,
    qualifications} dicts (length 3). qualifications defaults to the
    project's required_qualifications so all bids pass prescreen.
    """
    if required_qualifications is None:
        required_qualifications = ["Q1", "Q2"]
    ctx = setup_project_bidding_open(
        evaluation_method=evaluation_method,
        bid_submission_deadline=bid_submission_deadline,
        query_window_close_at=query_window_close_at,
        bid_opening_at=bid_opening_at,
        required_qualifications=required_qualifications,
        estimated_value_cents=estimated_value_cents,
        weights=weights,
        max_technical_score=max_technical_score,
        clock_origin=clock_origin,
    )
    if bid_specs is None:
        bid_specs = [
            {"price": 8_000_000, "technical_score_raw": 90,
             "qualifications": list(required_qualifications)},
            {"price": 10_000_000, "technical_score_raw": 85,
             "qualifications": list(required_qualifications)},
            {"price": 7_000_000, "technical_score_raw": 95,
             "qualifications": list(required_qualifications)},
        ]
    suppliers: List[Dict[str, Any]] = []
    bids: List[Dict[str, Any]] = []
    for spec in bid_specs:
        sup = register_verified_supplier(qualifications=spec["qualifications"])
        # Bring credit_score to 700 via the external event so the
        # supplier comfortably passes prescreen.
        set_credit_score(sup["id"], 700)
        bid = submit_bid(
            project_id=ctx["project"]["id"],
            supplier_id=sup["id"],
            bid_price_cents=spec["price"],
            tender_document_version=ctx["tender"]["version"],
            technical_score_raw=spec.get("technical_score_raw"),
        )
        suppliers.append(sup)
        bids.append(bid)
    return {**ctx, "suppliers": suppliers, "bids": bids}


def setup_evaluating(
    evaluation_method: str = "LOWEST_PRICE",
    required_qualifications: Optional[List[str]] = None,
    bid_specs: Optional[List[Dict[str, Any]]] = None,
    weights: Optional[Dict[str, float]] = None,
    max_technical_score: int = TEST_DEFAULTS["MAX_TECHNICAL_SCORE"],
    estimated_value_cents: int = TEST_DEFAULTS["ESTIMATED_VALUE_CENTS"],
    requested_committee_size: int = 3,
    committee_seed: str = "seed-A",
    bid_submission_deadline: str = "2026-03-01T00:00:00.000Z",
    query_window_close_at: str = "2026-02-15T00:00:00.000Z",
    bid_opening_at: str = "2026-03-02T00:00:00.000Z",
    clock_after_open: str = "2026-03-02T01:00:00.000Z",
) -> Dict[str, Any]:
    """Drive to project EVALUATING (BIDDING_CLOSED → ceremony opened).
    Returns the full context including the committee with members[].
    expert_id values."""
    ctx = setup_three_bids_submitted(
        evaluation_method=evaluation_method,
        required_qualifications=required_qualifications,
        bid_specs=bid_specs,
        bid_submission_deadline=bid_submission_deadline,
        query_window_close_at=query_window_close_at,
        bid_opening_at=bid_opening_at,
        estimated_value_cents=estimated_value_cents,
        weights=weights,
        max_technical_score=max_technical_score,
    )
    committee = form_committee(
        ctx["project"]["id"],
        requested_size=requested_committee_size,
        selection_seed=committee_seed,
    )
    # Advance clock past bid_submission_deadline, close bidding, then
    # past bid_opening_at, then open ceremony.
    advance_clock(bid_submission_deadline)
    project = close_bidding(ctx["project"]["id"])
    advance_clock(clock_after_open)
    project = open_bid_ceremony(ctx["project"]["id"])
    ctx["project"] = project
    ctx["committee"] = committee
    return ctx


def evaluate_all_bids(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Iterate over expert + bid pairs, recording one evaluation per
    OPENED bid. Skips bids that ended up DISQUALIFIED at close-bidding
    (failed re-prescreen). Returns the updated bid dicts in evaluation
    order."""
    members = ctx["committee"]["members"]
    expert_ids = [m["expert_id"] for m in members]
    if not expert_ids:
        raise AssertionError(
            "Setup failed: committee has no members[].expert_id values"
        )
    expert_id = expert_ids[0]
    # Determine which bids are currently OPENED by reading the bid list.
    listed_raw = api_client.list_project_bids(
        ctx["project"]["id"], OFFICER, params={"limit": 100},
    )
    listed = get_success_data(listed_raw)
    current_bids = listed if isinstance(listed, list) else listed.get("items", [])
    opened_ids = {b["id"] for b in current_bids if b.get("bid_status") == "OPENED"}
    results: List[Dict[str, Any]] = []
    for bid in ctx["bids"]:
        if bid["id"] not in opened_ids:
            continue
        results.append(record_evaluation(bid["id"], expert_id))
    return results


def setup_awarded(
    evaluation_method: str = "LOWEST_PRICE",
    required_qualifications: Optional[List[str]] = None,
    bid_specs: Optional[List[Dict[str, Any]]] = None,
    weights: Optional[Dict[str, float]] = None,
    max_technical_score: int = TEST_DEFAULTS["MAX_TECHNICAL_SCORE"],
    estimated_value_cents: int = TEST_DEFAULTS["ESTIMATED_VALUE_CENTS"],
    committee_size: int = 3,
    committee_seed: str = "seed-A",
    bid_submission_deadline: str = "2026-03-01T00:00:00.000Z",
    bid_opening_at: str = "2026-03-02T00:00:00.000Z",
    query_window_close_at: str = "2026-02-15T00:00:00.000Z",
    clock_after_open: str = "2026-03-02T01:00:00.000Z",
) -> Dict[str, Any]:
    """Drive all the way to Project.AWARDED with Award.DECIDED.
    Returns full context including award."""
    ctx = setup_evaluating(
        evaluation_method=evaluation_method,
        required_qualifications=required_qualifications,
        bid_specs=bid_specs,
        weights=weights,
        max_technical_score=max_technical_score,
        estimated_value_cents=estimated_value_cents,
        requested_committee_size=committee_size,
        committee_seed=committee_seed,
        bid_submission_deadline=bid_submission_deadline,
        query_window_close_at=query_window_close_at,
        bid_opening_at=bid_opening_at,
        clock_after_open=clock_after_open,
    )
    evaluated_bids = evaluate_all_bids(ctx)
    ctx["evaluated_bids"] = evaluated_bids
    finalize_committee(ctx["committee"]["id"])
    award = decide_award(ctx["project"]["id"])
    ctx["award"] = award
    return ctx


def setup_award_published(
    evaluation_method: str = "LOWEST_PRICE",
    required_qualifications: Optional[List[str]] = None,
    bid_specs: Optional[List[Dict[str, Any]]] = None,
    weights: Optional[Dict[str, float]] = None,
    max_technical_score: int = TEST_DEFAULTS["MAX_TECHNICAL_SCORE"],
    estimated_value_cents: int = TEST_DEFAULTS["ESTIMATED_VALUE_CENTS"],
    committee_size: int = 3,
    committee_seed: str = "seed-A",
) -> Dict[str, Any]:
    """Drive past setup_awarded to Award.PUBLISHED."""
    ctx = setup_awarded(
        evaluation_method=evaluation_method,
        required_qualifications=required_qualifications,
        bid_specs=bid_specs,
        weights=weights,
        max_technical_score=max_technical_score,
        estimated_value_cents=estimated_value_cents,
        committee_size=committee_size,
        committee_seed=committee_seed,
    )
    ctx["award"] = publish_award(ctx["award"]["id"])
    return ctx


# ===========================================================================
# Tier 7: Contract filing / signing
# ===========================================================================
def file_contract(
    project_id: str,
    award_id: str,
    supplier_id: str,
    contract_amount_cents: int,
    payment_terms: str,
) -> Dict[str, Any]:
    """PRD §3.11: file a Contract in PENDING_SIGNATURE."""
    payload = file_contract_payload(
        project_id=project_id,
        award_id=award_id,
        supplier_id=supplier_id,
        contract_amount_cents=contract_amount_cents,
        payment_terms=payment_terms,
    )
    return get_success_data(api_client.file_contract(payload, OFFICER))


def sign_contract(contract_id: str) -> Dict[str, Any]:
    """PRD §3.11: PENDING_SIGNATURE → ACTIVE; cascades Project to
    CONTRACT_SIGNED and PlanItem to EXECUTED."""
    return get_success_data(
        api_client.sign_contract(contract_id, OFFICER),
    )


def setup_signed_contract(
    contract_amount_cents: Optional[int] = None,
    commercial_spec: str = TEST_DEFAULTS["COMMERCIAL_SPEC"],
) -> Dict[str, Any]:
    """Drive all the way to Contract.ACTIVE (Project.CONTRACT_SIGNED).
    Picks the winning supplier from setup_award_published and files a
    consistent contract."""
    bid_specs = [
        {"price": 8_000_000, "technical_score_raw": 90,
         "qualifications": ["Q1", "Q2"]},
        {"price": 9_000_000, "technical_score_raw": 80,
         "qualifications": ["Q1", "Q2"]},
        {"price": 10_000_000, "technical_score_raw": 75,
         "qualifications": ["Q1", "Q2"]},
    ]
    ctx = setup_award_published(
        evaluation_method="LOWEST_PRICE",
        required_qualifications=["Q1", "Q2"],
        bid_specs=bid_specs,
    )
    award = ctx["award"]
    winning_bid_id = award["winning_bid_id"]
    # Identify winning supplier from bids.
    winning_bid = next(b for b in ctx["bids"] if b["id"] == winning_bid_id)
    winning_supplier_id = winning_bid["supplier_id"]
    amount = (
        contract_amount_cents
        if contract_amount_cents is not None
        else award["award_amount_cents"]
    )
    contract = file_contract(
        project_id=ctx["project"]["id"],
        award_id=award["id"],
        supplier_id=winning_supplier_id,
        contract_amount_cents=amount,
        payment_terms=commercial_spec,
    )
    contract = sign_contract(contract["id"])
    ctx["contract"] = contract
    ctx["winning_supplier_id"] = winning_supplier_id
    return ctx


# ===========================================================================
# Tier 8: Complaint setup
# ===========================================================================
def file_complaint(
    project_id: str,
    complainant_supplier_id: str,
    subject: str = "EVALUATION",
    narrative: str = "Scoring appears inconsistent.",
) -> Dict[str, Any]:
    """PRD §3.10: a supplier files a Complaint. Identity-threaded via
    make_supplier_headers because the server compares
    complainant_supplier_id to X-User-ID for ownership-gated mutations
    (withdraw)."""
    payload = file_complaint_payload(
        complainant_supplier_id=complainant_supplier_id,
        subject=subject,
        narrative=narrative,
    )
    return get_success_data(
        api_client.file_complaint(
            project_id, payload,
            make_supplier_headers(complainant_supplier_id),
        ),
    )


def accept_complaint(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.accept_complaint(complaint_id, REGULATOR),
    )


def uphold_complaint(
    complaint_id: str, corrective_action: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.uphold_complaint(
            complaint_id,
            uphold_complaint_payload(corrective_action),
            REGULATOR,
        ),
    )


def dismiss_complaint(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.dismiss_complaint(complaint_id, REGULATOR),
    )


def setup_complaint_under_review_on_awarded(
    subject: str = "AWARD",
) -> Dict[str, Any]:
    """Drive to Project.AWARDED with an Award.PUBLISHED, then file a
    complaint by a losing supplier and accept it (UNDER_REVIEW)."""
    ctx = setup_award_published(
        evaluation_method="LOWEST_PRICE",
        required_qualifications=["Q1", "Q2"],
    )
    # Pick a non-winning bidder for the complaint.
    losing_bid = next(
        b for b in ctx["bids"] if b["id"] != ctx["award"]["winning_bid_id"]
    )
    complainant_id = losing_bid["supplier_id"]
    complaint = file_complaint(
        ctx["project"]["id"], complainant_id, subject=subject,
    )
    complaint = accept_complaint(complaint["id"])
    ctx["complaint"] = complaint
    ctx["complainant_supplier_id"] = complainant_id
    return ctx


# ===========================================================================
# Tier 9: Contract amendment + termination
# ===========================================================================
def begin_contract_amendment(contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.begin_contract_amendment(contract_id, OFFICER),
    )


def file_contract_amendment(
    contract_id: str,
    delta_amount_cents: int,
    reason: str = "Scope adjustment.",
) -> Dict[str, Any]:
    payload = contract_amendment_payload(
        delta_amount_cents=delta_amount_cents, reason=reason,
    )
    return get_success_data(
        api_client.file_contract_amendment(contract_id, payload, OFFICER),
    )


def record_payment(contract_id: str, amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_payment(
            contract_id, record_payment_payload(amount_cents), OFFICER,
        ),
    )


def mark_contract_executed(contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.mark_contract_executed(contract_id, OFFICER),
    )


__all__ = [
    "OFFICER",
    "OFFICER_ALT",
    "REGULATOR",
    "REGULATOR_ALT",
    "advance_clock",
    "register_supplier",
    "verify_supplier",
    "register_verified_supplier",
    "set_credit_score",
    "blacklist_supplier",
    "create_draft_plan",
    "add_plan_item",
    "submit_plan_for_review",
    "approve_plan_item",
    "reject_plan_item",
    "publish_plan",
    "create_published_plan_with_items",
    "create_project",
    "create_tender_document",
    "publish_tender_document",
    "open_bidding",
    "close_bidding",
    "setup_project_prescreen_open",
    "setup_project_bidding_open",
    "submit_bid",
    "withdraw_bid",
    "form_committee",
    "open_bid_ceremony",
    "record_evaluation",
    "finalize_committee",
    "decide_award",
    "publish_award",
    "setup_three_bids_submitted",
    "setup_evaluating",
    "evaluate_all_bids",
    "setup_awarded",
    "setup_award_published",
    "file_contract",
    "sign_contract",
    "setup_signed_contract",
    "file_complaint",
    "accept_complaint",
    "uphold_complaint",
    "dismiss_complaint",
    "setup_complaint_under_review_on_awarded",
    "begin_contract_amendment",
    "file_contract_amendment",
    "record_payment",
    "mark_contract_executed",
    "unique_legal_name",
    "unique_tax_id",
]
