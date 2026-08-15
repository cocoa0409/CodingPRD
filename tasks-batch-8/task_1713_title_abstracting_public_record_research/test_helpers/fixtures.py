"""Composite setup helpers for the title-abstracting workflows (PRD §3).

Every helper builds its preconditions from scratch through the public API,
because the test harness restarts the server before every test. Setup calls
use the lenient get_success_data() validator so failures surface as clear
"Setup step failed" errors.

Identity threading: ownership-gated calls always use make_*_headers() with
the exact ref string booked on the resource (PRD §2.1 attribute-ownership).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assignment_payload,
    create_curative_payload,
    create_document_payload,
    create_legal_check_payload,
    create_order_payload,
    create_report_payload,
    create_retrieval_payload,
)
from .test_users import (
    DEFAULT_ABSTRACTER_REF,
    DEFAULT_CLIENT_REF,
    DEFAULT_EXAMINER_REF,
    make_abstracter_headers,
    make_client_headers,
    make_examiner_headers,
    make_ops_headers,
)

DEFAULT_WINDOW_START = "2026-08-01T09:00:00Z"
DEFAULT_WINDOW_END = "2026-08-01T17:00:00Z"
DEFAULT_SLOT_START = "2026-08-02T10:00:00Z"
DEFAULT_SLOT_END = "2026-08-02T11:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1 — single-resource creation helpers
# ---------------------------------------------------------------------------

def create_order(client_ref: str = DEFAULT_CLIENT_REF, **overrides) -> dict:
    """Place an order as the owning Client. Returns the created order."""
    payload = create_order_payload(client_ref, **overrides)
    resp = api_client.create_abstract_order(payload, make_client_headers(client_ref))
    return get_success_data(resp)


def get_order(order_id: str) -> dict:
    resp = api_client.get_abstract_order(order_id, make_ops_headers())
    return get_success_data(resp)


def create_assignment(
    order_id: str,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    search_type: str = "CHAIN_OF_TITLE",
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
) -> dict:
    """Dispatch a search assignment as OperationsManager."""
    payload = create_assignment_payload(
        order_id,
        abstracter_ref,
        search_type=search_type,
        window_start=window_start,
        window_end=window_end,
    )
    resp = api_client.create_search_assignment(payload, make_ops_headers())
    return get_success_data(resp)


def get_assignment(assignment_id: str) -> dict:
    resp = api_client.get_search_assignment(assignment_id, make_ops_headers())
    return get_success_data(resp)


def create_document(
    order_id: str,
    assignment_id: str,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    **overrides,
) -> dict:
    """Record an instrument as the owning Abstracter."""
    payload = create_document_payload(order_id, assignment_id, **overrides)
    resp = api_client.create_record_document(payload, make_abstracter_headers(abstracter_ref))
    return get_success_data(resp)


def get_document(document_id: str) -> dict:
    resp = api_client.get_record_document(document_id, make_ops_headers())
    return get_success_data(resp)


def verify_document(document_id: str, abstracter_ref: str = DEFAULT_ABSTRACTER_REF) -> dict:
    resp = api_client.verify_record_document(document_id, make_abstracter_headers(abstracter_ref))
    return get_success_data(resp)


def create_verified_document(
    order_id: str,
    assignment_id: str,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    **overrides,
) -> dict:
    doc = create_document(order_id, assignment_id, abstracter_ref, **overrides)
    return verify_document(doc["id"], abstracter_ref)


def submit_assignment(assignment_id: str, abstracter_ref: str = DEFAULT_ABSTRACTER_REF) -> dict:
    resp = api_client.submit_search_assignment(assignment_id, make_abstracter_headers(abstracter_ref))
    return get_success_data(resp)


def accept_assignment(assignment_id: str, examiner_ref: str = DEFAULT_EXAMINER_REF) -> dict:
    resp = api_client.accept_search_assignment(assignment_id, make_examiner_headers(examiner_ref))
    return get_success_data(resp)


def return_assignment(
    assignment_id: str,
    reason: str,
    examiner_ref: str = DEFAULT_EXAMINER_REF,
) -> dict:
    resp = api_client.return_search_assignment(
        assignment_id, {"reason": reason}, make_examiner_headers(examiner_ref)
    )
    return get_success_data(resp)


def resume_assignment(assignment_id: str, abstracter_ref: str = DEFAULT_ABSTRACTER_REF) -> dict:
    resp = api_client.resume_search_assignment(assignment_id, make_abstracter_headers(abstracter_ref))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2 — legal description checks and curative requirements
# ---------------------------------------------------------------------------

def create_legal_check(
    order_id: str,
    survey_reference: str = "SURV-2026-001",
    checked_legal_description: str = "LOT 1 BLK A",
) -> dict:
    payload = create_legal_check_payload(
        order_id,
        survey_reference=survey_reference,
        checked_legal_description=checked_legal_description,
    )
    resp = api_client.create_legal_description_check(payload, make_ops_headers())
    return get_success_data(resp)


def submit_verdict(check_id: str, verdict: str, survey_exception_applied: bool) -> dict:
    payload = {"verdict": verdict, "survey_exception_applied": survey_exception_applied}
    resp = api_client.submit_legal_verdict(check_id, payload, make_ops_headers())
    return get_success_data(resp)


def resolve_check(check_id: str, resolved_description: str) -> dict:
    resp = api_client.resolve_legal_description_check(
        check_id, {"resolved_description": resolved_description}, make_ops_headers()
    )
    return get_success_data(resp)


def create_curative(
    order_id: str,
    examiner_ref: str = DEFAULT_EXAMINER_REF,
    description: str = "Cure the noted title defect",
    **overrides,
) -> dict:
    payload = create_curative_payload(order_id, description, **overrides)
    resp = api_client.create_curative_requirement(payload, make_examiner_headers(examiner_ref))
    return get_success_data(resp)


def satisfy_curative(
    curative_id: str,
    resolution_note: str = "cured",
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
) -> dict:
    resp = api_client.satisfy_curative_requirement(
        curative_id, {"resolution_note": resolution_note}, make_abstracter_headers(abstracter_ref)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3 — report lifecycle and delivery
# ---------------------------------------------------------------------------

def open_report(
    order_id: str,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    title: str = "Abstract Report",
) -> dict:
    """Open the abstract report against the order's current version (PRD §2.8)."""
    current_version = get_order(order_id)["version"]
    payload = create_report_payload(
        order_id, expected_abstract_order_version=current_version, title=title
    )
    resp = api_client.create_abstract_report(payload, make_abstracter_headers(abstracter_ref))
    return get_success_data(resp)


def submit_report(report_id: str, abstracter_ref: str = DEFAULT_ABSTRACTER_REF) -> dict:
    resp = api_client.submit_abstract_report(report_id, make_abstracter_headers(abstracter_ref))
    return get_success_data(resp)


def start_review(
    report_id: str,
    examiner_ref: str = DEFAULT_EXAMINER_REF,
    review_slot_start: str = DEFAULT_SLOT_START,
    review_slot_end: str = DEFAULT_SLOT_END,
) -> dict:
    payload = {
        "review_slot_start": review_slot_start,
        "review_slot_end": review_slot_end,
    }
    resp = api_client.start_report_review(report_id, payload, make_examiner_headers(examiner_ref))
    return get_success_data(resp)


def approve_report(report_id: str, examiner_ref: str = DEFAULT_EXAMINER_REF) -> dict:
    resp = api_client.approve_abstract_report(report_id, make_examiner_headers(examiner_ref))
    return get_success_data(resp)


def deliver_order(order_id: str) -> dict:
    resp = api_client.deliver_abstract_order(order_id, make_ops_headers())
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, make_ops_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4 — county retrievals and the fee ledger
# ---------------------------------------------------------------------------

def create_retrieval(
    order_id: str,
    document_id: str,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    county: str = "Travis",
    fee_mode: str = "PER_DOCUMENT",
    page_count=None,
) -> dict:
    overrides = {"county": county, "fee_mode": fee_mode}
    if page_count is not None:
        overrides["page_count"] = page_count
    payload = create_retrieval_payload(order_id, document_id, **overrides)
    resp = api_client.create_county_retrieval(payload, make_abstracter_headers(abstracter_ref))
    return get_success_data(resp)


def get_retrieval(retrieval_id: str) -> dict:
    resp = api_client.get_county_retrieval(retrieval_id, make_ops_headers())
    return get_success_data(resp)


def post_fee(retrieval_id: str) -> dict:
    resp = api_client.post_retrieval_fee(retrieval_id, make_ops_headers())
    return get_success_data(resp)


def reverse_fee(retrieval_id: str, reason: str = "county rejected the pull") -> dict:
    resp = api_client.reverse_retrieval_fee(retrieval_id, {"reason": reason}, make_ops_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5 — full lifecycle drives
# ---------------------------------------------------------------------------

def setup_order_with_assignment(
    client_ref: str = DEFAULT_CLIENT_REF,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    search_type: str = "CHAIN_OF_TITLE",
    **order_overrides,
) -> dict:
    """Order + first assignment. Order lands in SEARCH_IN_PROGRESS."""
    order = create_order(client_ref, **order_overrides)
    assignment = create_assignment(order["id"], abstracter_ref, search_type)
    return {
        "order": order,
        "assignment": assignment,
        "client_ref": client_ref,
        "abstracter_ref": abstracter_ref,
    }


def drive_order_to_search_complete(
    client_ref: str = DEFAULT_CLIENT_REF,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    examiner_ref: str = DEFAULT_EXAMINER_REF,
    instrument_type: str = "DEED",
    **order_overrides,
) -> dict:
    """Order + assignment + one verified document + submit + accept.

    Lands the order in SEARCH_COMPLETE with no legal hold in effect.
    """
    ctx = setup_order_with_assignment(client_ref, abstracter_ref, "CHAIN_OF_TITLE", **order_overrides)
    ctx["order_at_creation"] = ctx["order"]
    document = create_verified_document(
        ctx["order"]["id"], ctx["assignment"]["id"], abstracter_ref,
        instrument_type=instrument_type,
    )
    submit_assignment(ctx["assignment"]["id"], abstracter_ref)
    accept_assignment(ctx["assignment"]["id"], examiner_ref)
    ctx["document"] = document
    ctx["examiner_ref"] = examiner_ref
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def drive_report_under_review(
    client_ref: str = DEFAULT_CLIENT_REF,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    examiner_ref: str = DEFAULT_EXAMINER_REF,
    review_slot_start: str = DEFAULT_SLOT_START,
    review_slot_end: str = DEFAULT_SLOT_END,
    **order_overrides,
) -> dict:
    """Full drive: SEARCH_COMPLETE -> report opened -> submitted -> UNDER_REVIEW."""
    ctx = drive_order_to_search_complete(client_ref, abstracter_ref, examiner_ref, **order_overrides)
    report = open_report(ctx["order"]["id"], abstracter_ref)
    submit_report(report["id"], abstracter_ref)
    report = start_review(report["id"], examiner_ref, review_slot_start, review_slot_end)
    ctx["report"] = report
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def drive_order_ready_for_delivery(
    client_ref: str = DEFAULT_CLIENT_REF,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    examiner_ref: str = DEFAULT_EXAMINER_REF,
    review_slot_start: str = DEFAULT_SLOT_START,
    review_slot_end: str = DEFAULT_SLOT_END,
    retrieval_specs=None,
    **order_overrides,
) -> dict:
    """Full drive through APPROVED report; order lands READY_FOR_DELIVERY.

    retrieval_specs: optional list of dicts accepted by create_retrieval()
    (minus order_id / record_document_id), e.g.
        [{"fee_mode": "PER_PAGE", "page_count": 10}, {"fee_mode": "PER_DOCUMENT"}]
    Each listed retrieval is created against the verified document and its fee
    is posted before the search is submitted.
    """
    order = create_order(client_ref, **order_overrides)
    order_at_creation = order
    assignment = create_assignment(order["id"], abstracter_ref, "CHAIN_OF_TITLE")
    document = create_document(order["id"], assignment["id"], abstracter_ref)

    retrievals = []
    for spec in retrieval_specs or []:
        retrieval = create_retrieval(order["id"], document["id"], abstracter_ref, **spec)
        retrievals.append(post_fee(retrieval["id"]))

    verify_document(document["id"], abstracter_ref)
    submit_assignment(assignment["id"], abstracter_ref)
    accept_assignment(assignment["id"], examiner_ref)
    report = open_report(order["id"], abstracter_ref)
    submit_report(report["id"], abstracter_ref)
    report = start_review(report["id"], examiner_ref, review_slot_start, review_slot_end)
    report = approve_report(report["id"], examiner_ref)

    return {
        "order": get_order(order["id"]),
        "order_at_creation": order_at_creation,
        "assignment": assignment,
        "document": get_document(document["id"]),
        "report": report,
        "retrievals": retrievals,
        "client_ref": client_ref,
        "abstracter_ref": abstracter_ref,
        "examiner_ref": examiner_ref,
    }


def setup_delivered_order(
    client_ref: str = DEFAULT_CLIENT_REF,
    abstracter_ref: str = DEFAULT_ABSTRACTER_REF,
    examiner_ref: str = DEFAULT_EXAMINER_REF,
    retrieval_specs=None,
    **order_overrides,
) -> dict:
    """Full lifecycle through DELIVERED. For terminal-state and invoicing tests."""
    ctx = drive_order_ready_for_delivery(
        client_ref, abstracter_ref, examiner_ref, retrieval_specs=retrieval_specs, **order_overrides
    )
    delivered = deliver_order(ctx["order"]["id"])
    ctx["order"] = delivered
    ctx["report"] = get_success_data(
        api_client.get_abstract_report(ctx["report"]["id"], make_ops_headers())
    )
    return ctx
