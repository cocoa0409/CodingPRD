"""ClaimTicket routes (PRD §3.4-§3.7).

State machine: SUBMITTED -> {ASSESSED, REJECTED}; ASSESSED -> DISPATCHED;
DISPATCHED -> {RESOLVED, ASSESSED (reopen)}.
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_ON_CONTRACT,
    ERR_OUT_OF_COVERAGE,
    ERR_PRE_EXISTING_EXCLUDED,
    ERR_SCHEDULED_IN_PAST,
    ERR_TECHNICIAN_DOUBLE_BOOKED,
    ERR_NOT_FOUND,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields,
    require_int,
    require_string,
    require_enum,
    lookup_or_404,
    parse_clock_dt,
    parse_request_dt,
)
from services.ownership import assert_customer_owns_contract
from services.calculations import (
    compute_provisional_copay_cents,
    compute_final_copay_cents,
    is_return_visit,
)
from services.aggregates import recompute_contract_aggregates


bp = Blueprint("claims", __name__)


VIEW_ROLES = ["PlatformAdmin", "Customer", "Dispatcher"]
REJECTION_CHOICES = {"PRE_EXISTING_EXCLUDED", "OUT_OF_COVERAGE", "NOT_COVERED_CATEGORY"}
ACTIVE_CONTRACT_STATES = {"ACTIVE", "EXPIRING_SOON"}


# ---------- POST /claims -----------------------------------------------------


@bp.post("/claims")
def create_claim():
    require_auth(["Customer", "PlatformAdmin"])()
    body = get_json_body()
    require_fields(body, ["contract_id", "covered_item_id", "issue_summary"])
    contract_id = body["contract_id"]
    covered_item_id = body["covered_item_id"]
    issue_summary = body["issue_summary"]
    require_string(contract_id, "contract_id")
    require_string(covered_item_id, "covered_item_id")
    require_string(issue_summary, "issue_summary")

    # FK existence (priority 4).
    contract = lookup_or_404(db.contracts, contract_id, "Contract")
    item = lookup_or_404(db.covered_items, covered_item_id, "CoveredItem")

    # Customer ownership.
    assert_customer_owns_contract(contract, current_role(), current_user_id())

    # Cross-aggregate consistency (priority 5).
    if item["contract_id"] != contract_id:
        raise APIError(
            ERR_ITEM_NOT_ON_CONTRACT,
            422,
            "CoveredItem does not belong to the named contract",
        )

    # Coverage-window check (priority 8): contract must be ACTIVE/EXPIRING_SOON,
    # and clock_now in [coverage_start, coverage_end).
    if contract["status"] not in ACTIVE_CONTRACT_STATES:
        raise APIError(ERR_OUT_OF_COVERAGE, 422, "Contract is not in coverage")
    now_dt = parse_clock_dt()
    start = db.parse_iso_dt(contract.get("coverage_start_utc"))
    end = db.parse_iso_dt(contract.get("coverage_end_utc"))
    if start is None or end is None or not (start <= now_dt < end):
        raise APIError(ERR_OUT_OF_COVERAGE, 422, "Clock is outside coverage window")

    ticket = {
        "contract_id": contract_id,
        "covered_item_id": covered_item_id,
        "issue_summary": issue_summary,
        "status": "SUBMITTED",
        "is_return_visit": False,
        "prior_dispatch_id": None,
        "rejection_reason": None,
        "repair_cost_cents": 0,
        "provisional_copay_cents": 0,
        "final_copay_cents": 0,
        "service_fee_charged_cents": 0,
    }
    db.stamp_common(ticket)
    db.claim_tickets[ticket["id"]] = ticket

    # Recompute parent contract aggregate (claims_in_period_count++).
    recompute_contract_aggregates(contract)

    return ok_object(ticket, 201)


# ---------- GET /claims/{id} -------------------------------------------------


@bp.get("/claims/<tid>")
def get_claim(tid: str):
    require_auth(VIEW_ROLES)()
    ticket = lookup_or_404(db.claim_tickets, tid, "ClaimTicket")
    if current_role() == "Customer":
        contract = db.contracts.get(ticket["contract_id"])
        if contract is None:
            raise APIError(ERR_NOT_FOUND, 404, "Claim's contract not found")
        assert_customer_owns_contract(contract, "Customer", current_user_id())
    return ok_object(ticket, 200)


# ---------- GET /claims ------------------------------------------------------


@bp.get("/claims")
def list_claims():
    require_auth(VIEW_ROLES)()
    limit, offset = paginate_params(request.args)
    contract_filter = request.args.get("contract_id")
    item_filter = request.args.get("covered_item_id")
    prior_dispatch_filter = request.args.get("prior_dispatch_id")
    status_filter = request.args.get("status")

    role = current_role()
    user_id = current_user_id()

    items = list(db.claim_tickets.values())
    if role == "Customer":
        own_contract_ids = {c["id"] for c in db.contracts.values() if c["customer_id"] == user_id}
        items = [t for t in items if t["contract_id"] in own_contract_ids]
    if contract_filter:
        items = [t for t in items if t["contract_id"] == contract_filter]
    if item_filter:
        items = [t for t in items if t["covered_item_id"] == item_filter]
    if prior_dispatch_filter:
        items = [t for t in items if t.get("prior_dispatch_id") == prior_dispatch_filter]
    if status_filter:
        items = [t for t in items if t["status"] == status_filter]
    items.sort(key=lambda t: t["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------- POST /claims/{id}/assess ----------------------------------------


@bp.post("/claims/<tid>/assess")
def assess_claim(tid: str):
    require_auth(["Dispatcher", "PlatformAdmin"])()
    ticket = lookup_or_404(db.claim_tickets, tid, "ClaimTicket")
    body = get_json_body()

    # State check (priority 6).
    if ticket["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot assess from status {ticket['status']}")

    # Pre-existing exclusion (priority 7).
    item = db.covered_items.get(ticket["covered_item_id"])
    if item is None:
        raise APIError(ERR_NOT_FOUND, 404, "CoveredItem not found")
    if item.get("pre_existing_flag") is True:
        raise APIError(
            ERR_PRE_EXISTING_EXCLUDED,
            422,
            "Cannot assess: item flagged pre-existing",
        )

    # Contract must be ACTIVE/EXPIRING_SOON for assessment (scaffold preconditions).
    contract = db.contracts.get(ticket["contract_id"])
    if contract is None:
        raise APIError(ERR_NOT_FOUND, 404, "Contract not found")
    if contract["status"] not in ACTIVE_CONTRACT_STATES:
        raise APIError(ERR_INVALID_STATE, 409, "Contract not in ACTIVE/EXPIRING_SOON")

    # Request shape (priority 14).
    require_fields(body, ["estimated_repair_cost_cents"])
    estimated = body["estimated_repair_cost_cents"]
    estimated = require_int(estimated, "estimated_repair_cost_cents", min_value=1)

    pkg = db.contract_packages.get(contract["package_id"])
    if pkg is None:
        raise APIError(ERR_NOT_FOUND, 404, "Package not found")

    provisional = compute_provisional_copay_cents(
        repair_cost_cents=estimated,
        copay_cap_cents=int(pkg["copay_cap_cents"]),
        copay_share_pct=pkg["copay_share_pct"],
        service_fee_cents=int(pkg["service_fee_cents"]),
    )

    ticket["repair_cost_cents"] = estimated
    ticket["provisional_copay_cents"] = provisional
    ticket["status"] = "ASSESSED"
    db.bump(ticket)
    return ok_object(ticket, 200)


# ---------- POST /claims/{id}/reject ----------------------------------------


@bp.post("/claims/<tid>/reject")
def reject_claim(tid: str):
    require_auth(["Dispatcher", "PlatformAdmin"])()
    ticket = lookup_or_404(db.claim_tickets, tid, "ClaimTicket")
    body = get_json_body()

    if ticket["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot reject from status {ticket['status']}")

    require_fields(body, ["rejection_reason"])
    reason = body["rejection_reason"]
    require_enum(reason, REJECTION_CHOICES, "rejection_reason")

    ticket["rejection_reason"] = reason
    ticket["status"] = "REJECTED"
    db.bump(ticket)

    contract = db.contracts.get(ticket["contract_id"])
    if contract is not None:
        recompute_contract_aggregates(contract)

    return ok_object(ticket, 200)


# ---------- POST /claims/{id}/dispatch --------------------------------------


@bp.post("/claims/<tid>/dispatch")
def dispatch_claim(tid: str):
    require_auth(["Dispatcher", "PlatformAdmin"])()
    ticket = lookup_or_404(db.claim_tickets, tid, "ClaimTicket")
    body = get_json_body()

    if ticket["status"] != "ASSESSED":
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot dispatch from status {ticket['status']}")

    require_fields(body, ["technician_id", "scheduled_utc"])
    technician_id = body["technician_id"]
    require_string(technician_id, "technician_id")
    scheduled_dt = parse_request_dt(body["scheduled_utc"], "scheduled_utc")

    now_dt = parse_clock_dt()
    # ERR_SCHEDULED_IN_PAST (priority 10).
    if scheduled_dt < now_dt:
        raise APIError(ERR_SCHEDULED_IN_PAST, 422, "scheduled_utc is in the past")

    # ERR_TECHNICIAN_DOUBLE_BOOKED (priority 11): |existing.scheduled - new.scheduled| < 3600.
    for d in db.dispatches.values():
        if d.get("technician_id") != technician_id:
            continue
        if d.get("status") not in {"SCHEDULED", "IN_PROGRESS"}:
            continue
        existing_dt = db.parse_iso_dt(d["scheduled_utc"])
        if existing_dt is None:
            continue
        diff = abs((existing_dt - scheduled_dt).total_seconds())
        if diff < 3600:
            raise APIError(
                ERR_TECHNICIAN_DOUBLE_BOOKED,
                422,
                "Technician double-booked within 60 minutes",
            )

    # Look up contract + package + item.
    contract = db.contracts.get(ticket["contract_id"])
    if contract is None:
        raise APIError(ERR_NOT_FOUND, 404, "Contract not found")
    pkg = db.contract_packages.get(contract["package_id"])
    if pkg is None:
        raise APIError(ERR_NOT_FOUND, 404, "Package not found")
    item = db.covered_items.get(ticket["covered_item_id"])
    if item is None:
        raise APIError(ERR_NOT_FOUND, 404, "CoveredItem not found")

    # Create the Dispatch row in SCHEDULED.
    dispatch = {
        "claim_id": ticket["id"],
        "technician_id": technician_id,
        "scheduled_utc": db.iso_format(scheduled_dt),
        "status": "SCHEDULED",
        "completed_utc": None,
    }
    db.stamp_common(dispatch)
    db.dispatches[dispatch["id"]] = dispatch

    # is_return_visit evaluation against the covered item.
    irv = is_return_visit(
        last_dispatch_completed_utc=item.get("last_dispatch_completed_utc"),
        window_days=int(pkg["return_visit_window_days"]),
        clock_now_iso=db.get_current_utc(),
    )
    ticket["is_return_visit"] = irv
    if irv:
        ticket["prior_dispatch_id"] = item.get("last_dispatch_id")
        ticket["service_fee_charged_cents"] = 0
    else:
        ticket["prior_dispatch_id"] = None
        ticket["service_fee_charged_cents"] = int(pkg["service_fee_cents"])

    ticket["status"] = "DISPATCHED"
    db.bump(ticket)

    return ok_object(ticket, 200)


# ---------- POST /claims/{id}/resolve ---------------------------------------


@bp.post("/claims/<tid>/resolve")
def resolve_claim(tid: str):
    require_auth(["Dispatcher", "PlatformAdmin"])()
    ticket = lookup_or_404(db.claim_tickets, tid, "ClaimTicket")
    body = get_json_body()

    if ticket["status"] != "DISPATCHED":
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot resolve from status {ticket['status']}")

    # The linked dispatch must be COMPLETED. There may be multiple dispatch rows
    # under this claim across reopen cycles — we need to find the latest one
    # that linked this claim. The state-machine precondition says: 'The Dispatch
    # row linked by Dispatch.claim_id == this claim.id has status == COMPLETED'.
    # In a fresh dispatch cycle (no reopen yet), there's exactly one. After a
    # reopen + new dispatch, there are two: the older one is COMPLETED or
    # RETURN_NEEDED, and the newer one is what we currently care about. We pick
    # the most recently created dispatch on this claim.
    dispatches = [d for d in db.dispatches.values() if d["claim_id"] == ticket["id"]]
    if not dispatches:
        raise APIError(ERR_INVALID_STATE, 409, "No dispatch found for this claim")
    dispatches.sort(key=lambda d: d["created_at"])
    latest = dispatches[-1]
    if latest["status"] != "COMPLETED":
        raise APIError(ERR_INVALID_STATE, 409, "Latest dispatch is not COMPLETED")

    require_fields(body, ["actual_repair_cost_cents"])
    actual = require_int(body["actual_repair_cost_cents"], "actual_repair_cost_cents", min_value=1)

    contract = db.contracts.get(ticket["contract_id"])
    if contract is None:
        raise APIError(ERR_NOT_FOUND, 404, "Contract not found")
    pkg = db.contract_packages.get(contract["package_id"])
    if pkg is None:
        raise APIError(ERR_NOT_FOUND, 404, "Package not found")

    final_copay = compute_final_copay_cents(
        repair_cost_cents=actual,
        copay_cap_cents=int(pkg["copay_cap_cents"]),
        copay_share_pct=pkg["copay_share_pct"],
        service_fee_charged_cents=int(ticket["service_fee_charged_cents"]),
    )

    ticket["repair_cost_cents"] = actual
    ticket["final_copay_cents"] = final_copay
    ticket["status"] = "RESOLVED"
    db.bump(ticket)

    # Recompute contract aggregates.
    recompute_contract_aggregates(contract)

    return ok_object(ticket, 200)


# ---------- POST /claims/{id}/reopen ----------------------------------------


@bp.post("/claims/<tid>/reopen")
def reopen_claim(tid: str):
    require_auth(["Dispatcher", "PlatformAdmin"])()
    ticket = lookup_or_404(db.claim_tickets, tid, "ClaimTicket")

    if ticket["status"] != "DISPATCHED":
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot reopen from status {ticket['status']}")

    # The linked dispatch must be RETURN_NEEDED.
    dispatches = [d for d in db.dispatches.values() if d["claim_id"] == ticket["id"]]
    if not dispatches:
        raise APIError(ERR_INVALID_STATE, 409, "No dispatch found for this claim")
    dispatches.sort(key=lambda d: d["created_at"])
    latest = dispatches[-1]
    if latest["status"] != "RETURN_NEEDED":
        raise APIError(ERR_INVALID_STATE, 409, "Latest dispatch is not RETURN_NEEDED")

    ticket["provisional_copay_cents"] = 0
    ticket["status"] = "ASSESSED"
    db.bump(ticket)
    return ok_object(ticket, 200)
