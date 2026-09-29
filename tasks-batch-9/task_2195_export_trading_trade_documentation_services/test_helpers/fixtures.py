"""Composite setup helpers.

Storage is wiped before every test, so every helper below builds all of the state
it needs through declared endpoints only. Nothing is ever assumed to pre-exist.

The helpers are layered:

* tier 1 - single rows (buyer, order, line, sailing, policy)
* tier 2 - an order with its lines
* tier 3 - compliance progression (screened / cleared / licensed)
* tier 4 - accumulation and threshold targeting (booked, shipped, credit accepted)
* tier 5 - terminal states (presented, complied, honoured, dishonoured)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    ADMIN_PAT,
    COMPLIANCE_CARL,
    FINANCE_FRANK,
    OPS_ALICE,
    REVIEWER_BOB,
    make_buyer_headers,
)

Json = Dict[str, Any]
Headers = Dict[str, str]


def data(response) -> Json:
    """Lenient payload extraction for setup calls."""
    body = get_success_data(response)
    assert body is not None, (
        f"setup call failed with {response.status_code}: {response.text[:400]}"
    )
    return body


def rows(response) -> List[Json]:
    body = data(response)
    assert isinstance(body, list), f"expected an array payload, got {type(body)}"
    return body


def set_clock(api: ApiClient, instant: str, headers: Headers = ADMIN_PAT) -> None:
    """Move the logical clock and let its sweep run."""
    response = api.set_clock(instant, headers)
    assert response.status_code == 200, (
        f"clock move to {instant} failed: {response.status_code} {response.text[:300]}"
    )


def reset_clock(api: ApiClient, headers: Headers = ADMIN_PAT) -> None:
    set_clock(api, DEFAULT_CLOCK_UTC, headers)


# ---------------------------------------------------------------------------
# tier 1 - single rows
# ---------------------------------------------------------------------------


def create_buyer(api: ApiClient, headers: Headers = COMPLIANCE_CARL, **overrides: Any) -> Json:
    return data(api.create_buyer(f.buyer_payload(**overrides), headers))


def create_order(
    api: ApiClient, buyer_id: str, headers: Headers = OPS_ALICE, **overrides: Any
) -> Json:
    return data(api.create_order(f.order_payload(buyer_id, **overrides), headers))


def add_line(
    api: ApiClient, order_id: str, headers: Headers = OPS_ALICE, **overrides: Any
) -> Json:
    return data(
        api.add_shipment_line(order_id, f.shipment_line_payload(**overrides), headers)
    )


def create_sailing(
    api: ApiClient, headers: Headers = OPS_ALICE, **overrides: Any
) -> Json:
    return data(api.create_sailing(f.sailing_payload(**overrides), headers))


def create_policy(
    api: ApiClient, buyer_id: str, headers: Headers = FINANCE_FRANK, **overrides: Any
) -> Json:
    return data(api.create_policy(f.policy_payload(buyer_id, **overrides), headers))


def read_order(api: ApiClient, order_id: str, headers: Headers = OPS_ALICE) -> Json:
    return data(api.get_order(order_id, headers))


def read_credit(api: ApiClient, lc_id: str, headers: Headers = OPS_ALICE) -> Json:
    return data(api.get_credit(lc_id, headers))


def read_sailing(api: ApiClient, sailing_id: str, headers: Headers = OPS_ALICE) -> Json:
    return data(api.get_sailing(sailing_id, headers))


def read_policy(api: ApiClient, policy_id: str, headers: Headers = FINANCE_FRANK) -> Json:
    return data(api.get_policy(policy_id, headers))


def order_version(api: ApiClient, order_id: str, headers: Headers = OPS_ALICE) -> int:
    return read_order(api, order_id, headers)["version"]


def credit_version(api: ApiClient, lc_id: str, headers: Headers = OPS_ALICE) -> int:
    return read_credit(api, lc_id, headers)["version"]


def sailing_version(api: ApiClient, sailing_id: str, headers: Headers = OPS_ALICE) -> int:
    return read_sailing(api, sailing_id, headers)["version"]


def policy_version(api: ApiClient, policy_id: str, headers: Headers = FINANCE_FRANK) -> int:
    return read_policy(api, policy_id, headers)["version"]


# ---------------------------------------------------------------------------
# tier 2 - an order with lines
# ---------------------------------------------------------------------------


def order_with_lines(
    api: ApiClient,
    buyer_overrides: Optional[Json] = None,
    order_overrides: Optional[Json] = None,
    lines: Optional[List[Json]] = None,
    ops_headers: Headers = OPS_ALICE,
    compliance_headers: Headers = COMPLIANCE_CARL,
) -> Json:
    """Buyer + order + one or more shipment lines."""
    buyer = create_buyer(api, compliance_headers, **(buyer_overrides or {}))
    order = create_order(api, buyer["id"], ops_headers, **(order_overrides or {}))
    line_specs = lines if lines is not None else [{}]
    created_lines = [
        add_line(api, order["id"], ops_headers, **spec) for spec in line_specs
    ]
    return {
        "buyer": buyer,
        "buyer_id": buyer["id"],
        "order": order,
        "order_id": order["id"],
        "lines": created_lines,
        "line_ids": [line["id"] for line in created_lines],
        "buyer_headers": make_buyer_headers(buyer["id"]),
    }


# ---------------------------------------------------------------------------
# tier 3 - compliance progression
# ---------------------------------------------------------------------------


def screening_for_order(
    api: ApiClient, order_id: str, headers: Headers = COMPLIANCE_CARL
) -> Json:
    """The screening opened by the compliance submission, read back by filter."""
    listed = rows(
        api.list_screenings(headers, {"export_order_id": order_id, "limit": 10, "offset": 0})
    )
    assert listed, f"no screening exists for order {order_id}"
    return listed[-1]


def submitted_for_compliance(
    api: ApiClient,
    ops_headers: Headers = OPS_ALICE,
    compliance_headers: Headers = COMPLIANCE_CARL,
    **kwargs: Any,
) -> Json:
    """An order in COMPLIANCE_PENDING with its INITIATED screening."""
    ctx = order_with_lines(
        api, ops_headers=ops_headers, compliance_headers=compliance_headers, **kwargs
    )
    ctx["order"] = data(api.submit_for_compliance(ctx["order_id"], ops_headers))
    ctx["screening"] = screening_for_order(api, ctx["order_id"], compliance_headers)
    ctx["screening_id"] = ctx["screening"]["id"]
    return ctx


def cleared_order(
    api: ApiClient,
    decision_overrides: Optional[Json] = None,
    ops_headers: Headers = OPS_ALICE,
    compliance_headers: Headers = COMPLIANCE_CARL,
    **kwargs: Any,
) -> Json:
    """An order in COMPLIANCE_CLEARED via an NLR screening decision."""
    ctx = submitted_for_compliance(
        api, ops_headers=ops_headers, compliance_headers=compliance_headers, **kwargs
    )
    ctx["screening"] = data(
        api.record_screening_decision(
            ctx["screening_id"],
            f.screening_decision_payload(**(decision_overrides or {})),
            compliance_headers,
        )
    )
    ctx["order"] = read_order(api, ctx["order_id"], ops_headers)
    return ctx


def cleared_order_for_buyer(
    api: ApiClient,
    buyer: Json,
    lines: Optional[List[Json]] = None,
    order_overrides: Optional[Json] = None,
    ops_headers: Headers = OPS_ALICE,
    compliance_headers: Headers = COMPLIANCE_CARL,
    decision_overrides: Optional[Json] = None,
) -> Json:
    """A second (or third) COMPLIANCE_CLEARED order hanging off an existing buyer."""
    order = create_order(api, buyer["id"], ops_headers, **(order_overrides or {}))
    specs = lines if lines is not None else [{}]
    created = [add_line(api, order["id"], ops_headers, **spec) for spec in specs]
    ctx: Json = {
        "buyer": buyer,
        "buyer_id": buyer["id"],
        "order": data(api.submit_for_compliance(order["id"], ops_headers)),
        "order_id": order["id"],
        "lines": created,
        "line_ids": [row["id"] for row in created],
        "buyer_headers": make_buyer_headers(buyer["id"]),
    }
    ctx["screening"] = screening_for_order(api, order["id"], compliance_headers)
    ctx["screening_id"] = ctx["screening"]["id"]
    ctx["screening"] = data(
        api.record_screening_decision(
            ctx["screening_id"],
            f.screening_decision_payload(**(decision_overrides or {})),
            compliance_headers,
        )
    )
    ctx["order"] = read_order(api, order["id"], ops_headers)
    return ctx


def licensed_cleared_order(
    api: ApiClient,
    eccn: str = "3A001",
    license_overrides: Optional[Json] = None,
    ops_headers: Headers = OPS_ALICE,
    compliance_headers: Headers = COMPLIANCE_CARL,
    **kwargs: Any,
) -> Json:
    """A LICENSE_REQUIRED screening cleared by an export licence."""
    ctx = submitted_for_compliance(
        api, ops_headers=ops_headers, compliance_headers=compliance_headers, **kwargs
    )
    ctx["screening"] = data(
        api.record_screening_decision(
            ctx["screening_id"],
            f.screening_decision_payload(
                license_determination="LICENSE_REQUIRED", eccn=eccn
            ),
            compliance_headers,
        )
    )
    license_body = f.license_payload(**{"eccn": eccn, **(license_overrides or {})})
    ctx["license"] = data(
        api.create_license(ctx["screening_id"], license_body, compliance_headers)
    )
    ctx["license_id"] = ctx["license"]["id"]
    ctx["screening"] = data(
        api.clear_with_license(
            ctx["screening_id"],
            {"export_license_id": ctx["license_id"]},
            compliance_headers,
        )
    )
    ctx["order"] = read_order(api, ctx["order_id"], ops_headers)
    return ctx


# ---------------------------------------------------------------------------
# tier 4 - accumulation and threshold targeting
# ---------------------------------------------------------------------------


def booked_order(
    api: ApiClient,
    sailing_overrides: Optional[Json] = None,
    booking_overrides: Optional[Json] = None,
    ops_headers: Headers = OPS_ALICE,
    base: Optional[Json] = None,
    **kwargs: Any,
) -> Json:
    """A compliance-cleared order with a BOOKED freight booking."""
    ctx = base if base is not None else cleared_order(api, ops_headers=ops_headers, **kwargs)
    ctx["sailing"] = create_sailing(api, ops_headers, **(sailing_overrides or {}))
    ctx["sailing_id"] = ctx["sailing"]["id"]
    ctx["booking"] = data(
        api.create_booking(
            f.booking_payload(
                ctx["order_id"],
                ctx["sailing_id"],
                ctx["sailing"]["version"],
                **(booking_overrides or {}),
            ),
            ops_headers,
        )
    )
    ctx["booking_id"] = ctx["booking"]["id"]
    ctx["order"] = read_order(api, ctx["order_id"], ops_headers)
    return ctx


def generate_and_issue(
    api: ApiClient, order_id: str, doc_type: str, ops_headers: Headers = OPS_ALICE
) -> Json:
    """Generate then immediately issue one document.

    Issuance bumps the order version, so a sibling document must never be
    generated before the previous one is issued.
    """
    draft = data(api.generate_document(f.document_payload(order_id, doc_type), ops_headers))
    return data(api.issue_document(draft["id"], ops_headers))


def confirmed_booking(
    api: ApiClient, ctx: Json, ops_headers: Headers = OPS_ALICE
) -> Json:
    """Issue the invoice and packing list, then confirm the booking."""
    ctx["invoice"] = generate_and_issue(
        api, ctx["order_id"], "COMMERCIAL_INVOICE", ops_headers
    )
    ctx["invoice_id"] = ctx["invoice"]["id"]
    ctx["packing_list"] = generate_and_issue(
        api, ctx["order_id"], "PACKING_LIST", ops_headers
    )
    ctx["packing_list_id"] = ctx["packing_list"]["id"]
    ctx["booking"] = data(api.confirm_booking(ctx["booking_id"], ops_headers))
    ctx["order"] = read_order(api, ctx["order_id"], ops_headers)
    return ctx


def shipped_order(
    api: ApiClient,
    ctx: Json,
    shipped_quantities: Optional[List[float]] = None,
    on_board_date: str = "2026-08-01T00:00:00Z",
    ops_headers: Headers = OPS_ALICE,
) -> Json:
    """Issue the bill of lading, moving the order to SHIPPED or SHORT_SHIPPED."""
    quantities = (
        shipped_quantities
        if shipped_quantities is not None
        else [line["quantity"] for line in ctx["lines"]]
    )
    shipped_lines = [
        f.shipped_line(line["id"], qty) for line, qty in zip(ctx["lines"], quantities)
    ]
    ctx["bill_of_lading"] = data(
        api.issue_bill_of_lading(
            ctx["booking_id"],
            f.bill_of_lading_payload(shipped_lines, on_board_date=on_board_date),
            ops_headers,
        )
    )
    ctx["bill_of_lading_id"] = ctx["bill_of_lading"]["id"]
    ctx["booking"] = data(api.get_booking(ctx["booking_id"], ops_headers))
    ctx["order"] = read_order(api, ctx["order_id"], ops_headers)
    return ctx


# ---------------------------------------------------------------------------
# credit lifecycle
# ---------------------------------------------------------------------------


def captured_credit(
    api: ApiClient,
    ctx: Json,
    ops_headers: Headers = OPS_ALICE,
    **credit_overrides: Any,
) -> Json:
    """Capture a credit against the order. The capturing user may not review it."""
    ctx["credit"] = data(
        api.capture_credit(
            f.credit_payload(ctx["order_id"], **credit_overrides), ops_headers
        )
    )
    ctx["lc_id"] = ctx["credit"]["id"]
    return ctx


def opened_terms_review(
    api: ApiClient, ctx: Json, reviewer_headers: Headers = REVIEWER_BOB
) -> Json:
    """Open a terms review as a reviewer distinct from the credit's capturer."""
    version = credit_version(api, ctx["lc_id"])
    ctx["review"] = data(
        api.open_terms_review(
            ctx["lc_id"], {"expected_letter_of_credit_version": version}, reviewer_headers
        )
    )
    ctx["review_id"] = ctx["review"]["id"]
    ctx["credit"] = read_credit(api, ctx["lc_id"])
    return ctx


def accepted_credit(
    api: ApiClient,
    ctx: Json,
    ops_headers: Headers = OPS_ALICE,
    reviewer_headers: Headers = REVIEWER_BOB,
    **credit_overrides: Any,
) -> Json:
    """Capture, review with no findings and accept, moving money to LC_ACCEPTED."""
    ctx = captured_credit(api, ctx, ops_headers, **credit_overrides)
    ctx = opened_terms_review(api, ctx, reviewer_headers)
    ctx["review"] = data(
        api.submit_terms_review(
            ctx["review_id"], {"recommendation": "ACCEPT"}, reviewer_headers
        )
    )
    ctx["credit"] = read_credit(api, ctx["lc_id"])
    ctx["order"] = read_order(api, ctx["order_id"], ops_headers)
    return ctx


# ---------------------------------------------------------------------------
# tier 5 - presentation and terminal states
# ---------------------------------------------------------------------------


def full_tender(
    api: ApiClient,
    required_document_types: Optional[List[str]] = None,
    shipped_quantities: Optional[List[float]] = None,
    on_board_date: str = "2026-08-01T00:00:00Z",
    order_overrides: Optional[Json] = None,
    buyer_overrides: Optional[Json] = None,
    lines: Optional[List[Json]] = None,
    sailing_overrides: Optional[Json] = None,
    booking_overrides: Optional[Json] = None,
    credit_overrides: Optional[Json] = None,
    ops_headers: Headers = OPS_ALICE,
    reviewer_headers: Headers = REVIEWER_BOB,
) -> Json:
    """The whole chain up to a shipped order under an accepted credit.

    buyer -> order -> lines -> compliance -> sailing -> booking -> invoice and
    packing list issued -> booking confirmed -> bill of lading issued -> credit
    captured, reviewed and accepted.
    """
    ctx = cleared_order(
        api,
        ops_headers=ops_headers,
        buyer_overrides=buyer_overrides,
        order_overrides=order_overrides,
        lines=lines,
    )
    ctx = booked_order(
        api,
        base=ctx,
        sailing_overrides=sailing_overrides,
        booking_overrides=booking_overrides,
        ops_headers=ops_headers,
    )
    ctx = confirmed_booking(api, ctx, ops_headers)
    ctx = shipped_order(
        api,
        ctx,
        shipped_quantities=shipped_quantities,
        on_board_date=on_board_date,
        ops_headers=ops_headers,
    )
    overrides: Json = dict(credit_overrides or {})
    if required_document_types is not None:
        overrides["required_document_types"] = required_document_types
    ctx = accepted_credit(
        api, ctx, ops_headers=ops_headers, reviewer_headers=reviewer_headers, **overrides
    )
    return ctx


def lodged_presentation(
    api: ApiClient,
    ctx: Json,
    document_ids: Optional[List[str]] = None,
    ops_headers: Headers = OPS_ALICE,
) -> Json:
    """Lodge the tender against the accepted credit at the current order version."""
    ids = document_ids if document_ids is not None else default_tender_ids(ctx)
    version = order_version(api, ctx["order_id"], ops_headers)
    ctx["presentation"] = data(
        api.lodge_presentation(
            f.presentation_payload(ctx["lc_id"], ctx["order_id"], ids, version),
            ops_headers,
        )
    )
    ctx["presentation_id"] = ctx["presentation"]["id"]
    ctx["order"] = read_order(api, ctx["order_id"], ops_headers)
    return ctx


def default_tender_ids(ctx: Json) -> List[str]:
    ids = [ctx["invoice_id"], ctx["packing_list_id"]]
    if ctx.get("bill_of_lading_id"):
        ids.append(ctx["bill_of_lading_id"])
    return ids


def examined_presentation(
    api: ApiClient,
    ctx: Json,
    findings: Optional[List[Json]] = None,
    reviewer_headers: Headers = REVIEWER_BOB,
) -> Json:
    """Examine the presentation. An empty finding set drives the COMPLIED branch."""
    ctx["presentation"] = data(
        api.examine_presentation(
            ctx["presentation_id"], {"findings": findings or []}, reviewer_headers
        )
    )
    ctx["order"] = read_order(api, ctx["order_id"])
    return ctx


def complied_presentation(
    api: ApiClient,
    required_document_types: Optional[List[str]] = None,
    reviewer_headers: Headers = REVIEWER_BOB,
    **kwargs: Any,
) -> Json:
    """Full chain to a COMPLIED presentation priced for negotiation."""
    ctx = full_tender(
        api,
        required_document_types=required_document_types,
        reviewer_headers=reviewer_headers,
        **kwargs,
    )
    ctx = lodged_presentation(api, ctx)
    ctx = examined_presentation(api, ctx, [], reviewer_headers)
    return ctx


def dishonoured_order(
    api: ApiClient,
    refusal_reason: str = "issuing bank refused: applicant insolvent",
    finance_headers: Headers = FINANCE_FRANK,
    **kwargs: Any,
) -> Json:
    """A COMPLIED presentation refused by the bank, parking money at DISHONORED."""
    ctx = complied_presentation(api, **kwargs)
    ctx["presentation"] = data(
        api.dishonour_presentation(
            ctx["presentation_id"], {"refusal_reason": refusal_reason}, finance_headers
        )
    )
    ctx["order"] = read_order(api, ctx["order_id"])
    return ctx


def presentation_links(
    api: ApiClient,
    presentation_id: str,
    headers: Headers = OPS_ALICE,
    params: Optional[Json] = None,
) -> List[Json]:
    query: Json = {"document_presentation_id": presentation_id, "limit": 100, "offset": 0}
    query.update(params or {})
    return rows(api.list_presentation_links(headers, query))


def findings_for_presentation(
    api: ApiClient,
    presentation_id: str,
    headers: Headers = REVIEWER_BOB,
    params: Optional[Json] = None,
) -> List[Json]:
    query: Json = {"document_presentation_id": presentation_id, "limit": 100, "offset": 0}
    query.update(params or {})
    return rows(api.list_findings(headers, query))


def findings_for_review(
    api: ApiClient,
    review_id: str,
    headers: Headers = REVIEWER_BOB,
    params: Optional[Json] = None,
) -> List[Json]:
    query: Json = {"lc_terms_review_id": review_id, "limit": 100, "offset": 0}
    query.update(params or {})
    return rows(api.list_findings(headers, query))
