"""Routes: damage reports and competitive bidding."""

from datetime import timedelta

from flask import Blueprint, request

from auth import get_auth, require_role, ANY_ROLE
from db import store, new_entity, bump, public, clock_date
from errors import raise_err
from response import ok, ok_list
from services import select_allowable, recompute_property_score
from util import (
    get_body, req_str, req_amount, req_enum, req_bool, get_or_404,
    parse_pagination, paginate, sort_created, DAMAGE_TYPES, SEVERITIES,
)

bp = Blueprint("damage", __name__)


def _report_servicer_id(report):
    prop = store.properties.get(report["property_id"])
    return prop["servicer_id"] if prop else None


# ---- DamageReport ------------------------------------------------------------

@bp.post("/preservation/damage-reports")
def create_damage_report():
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    b = get_body()
    property_id = b.get("property_id")
    if property_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: property_id")
    if not isinstance(property_id, str):
        raise_err("ERR_INVALID_REQUEST", "property_id must be a string")
    prop = get_or_404(store.properties, property_id, "Property")
    work_order_id = b.get("work_order_id")
    if work_order_id is not None:
        if not isinstance(work_order_id, str):
            raise_err("ERR_INVALID_REQUEST", "work_order_id must be a string")
        get_or_404(store.work_orders, work_order_id, "WorkOrder")

    damage_type = req_enum(b, "damage_type", DAMAGE_TYPES)
    severity = req_enum(b, "severity", SEVERITIES)
    is_interior = req_bool(b, "is_interior")
    description = req_str(b, "description")

    report = new_entity({
        "property_id": prop["id"],
        "work_order_id": work_order_id,
        "reported_by_crew_id": user_id,
        "damage_type": damage_type,
        "severity": severity,
        "is_interior": is_interior,
        "description": description,
        "status": "REPORTED",
    })
    store.damage_reports[report["id"]] = report
    recompute_property_score(prop)
    return ok(public(report), status=201)


@bp.get("/preservation/damage-reports/<reportId>")
def get_damage_report(reportId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    report = get_or_404(store.damage_reports, reportId, "DamageReport")
    return ok(public(report))


@bp.get("/preservation/damage-reports")
def list_damage_reports():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.damage_reports.values())
    for field in ("property_id", "reported_by_crew_id", "work_order_id", "status"):
        f = request.args.get(field)
        if f is not None:
            items = [d for d in items if d.get(field) == f]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/damage-reports/<reportId>/triage")
def triage_report(reportId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    report = get_or_404(store.damage_reports, reportId, "DamageReport")
    get_body()
    if report["status"] != "REPORTED":
        raise_err("ERR_INVALID_STATE", "Damage report is not REPORTED")
    report["status"] = "TRIAGED"
    bump(report)
    return ok(public(report))


@bp.post("/preservation/damage-reports/<reportId>/request-bids")
def request_bids(reportId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    report = get_or_404(store.damage_reports, reportId, "DamageReport")
    get_body()
    if report["status"] != "TRIAGED":
        raise_err("ERR_INVALID_STATE", "Damage report is not TRIAGED")
    report["status"] = "BID_REQUESTED"
    bump(report)
    return ok(public(report))


@bp.post("/preservation/damage-reports/<reportId>/close")
def close_report(reportId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    report = get_or_404(store.damage_reports, reportId, "DamageReport")
    b = get_body()
    outcome = req_enum(b, "outcome", {"CLOSED", "MONITORING"})

    open_bids = any(
        bd["damage_report_id"] == report["id"] and bd["status"] in ("DRAFT", "SUBMITTED", "COUNTERED")
        for bd in store.bids.values()
    )

    if report["status"] == "REPAIR_IN_PROGRESS":
        if open_bids:
            raise_err("ERR_OPEN_BIDS", "Bids in DRAFT, SUBMITTED, or COUNTERED remain on this report")
        if outcome == "CLOSED":
            approved_bid = next(
                (bd for bd in store.bids.values()
                 if bd["damage_report_id"] == report["id"] and bd["status"] == "APPROVED"),
                None,
            )
            wo = store.work_orders.get(approved_bid["approved_work_order_id"]) if approved_bid else None
            if wo is None or wo["status"] != "COMPLETED":
                raise_err("ERR_REPAIR_NOT_COMPLETED", "The approved repair work order is not COMPLETED")
            report["status"] = "CLOSED"
            bump(report)
            prop = store.properties.get(report["property_id"])
            if prop is not None:
                recompute_property_score(prop)
        else:
            report["status"] = "MONITORING"
            bump(report)
    elif report["status"] == "TRIAGED" and outcome == "CLOSED":
        report["status"] = "CLOSED"
        bump(report)
        prop = store.properties.get(report["property_id"])
        if prop is not None:
            recompute_property_score(prop)
    else:
        raise_err("ERR_INVALID_STATE", "Damage report cannot be closed with that outcome from its current state")
    return ok(public(report))


# ---- Bid ------------------------------------------------------------------------

@bp.post("/preservation/damage-reports/<damageReportId>/bids")
def create_bid(damageReportId):
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    report = get_or_404(store.damage_reports, damageReportId, "DamageReport")
    b = get_body()
    amount_cents = req_amount(b, "amount_cents")
    if "expected_damage_report_version" not in b or b.get("expected_damage_report_version") is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: expected_damage_report_version")
    expected = b["expected_damage_report_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err("ERR_INVALID_REQUEST", "expected_damage_report_version must be an integer")

    # OCC guard (section 2.8).
    if expected != report["version"]:
        raise_err("ERR_STALE_VERSION", "Damage report version has advanced since last read")
    if report["status"] != "BID_REQUESTED":
        raise_err("ERR_DAMAGE_NOT_ACCEPTING_BIDS", "Damage report is not accepting bids")

    bid = new_entity({
        "damage_report_id": report["id"],
        "property_id": report["property_id"],
        "submitted_by_crew_id": user_id,
        "amount_cents": amount_cents,
        "round_number": 1,
        "counter_amount_cents": None,
        "status": "DRAFT",
        "approved_work_order_id": None,
    })
    store.bids[bid["id"]] = bid
    # Side effect: bid creation advances the report's version.
    bump(report)
    return ok(public(bid), status=201)


@bp.get("/preservation/bids/<bidId>")
def get_bid(bidId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    bid = get_or_404(store.bids, bidId, "Bid")
    return ok(public(bid))


@bp.get("/preservation/bids")
def list_bids():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.bids.values())
    for field in ("damage_report_id", "submitted_by_crew_id", "property_id", "approved_work_order_id", "status"):
        f = request.args.get(field)
        if f is not None:
            items = [bd for bd in items if bd.get(field) == f]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/bids/<bidId>/submit")
def submit_bid(bidId):
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    bid = get_or_404(store.bids, bidId, "Bid")
    get_body()
    if bid["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Bid is not DRAFT")
    report = store.damage_reports.get(bid["damage_report_id"])
    if report is None or report["status"] != "BID_REQUESTED":
        raise_err("ERR_DAMAGE_NOT_ACCEPTING_BIDS", "Damage report is not accepting bids")
    if user_id != bid["submitted_by_crew_id"]:
        raise_err("ERR_NOT_BID_OWNER", "Only the owning crew may submit this bid")
    bid["status"] = "SUBMITTED"
    bump(bid)
    return ok(public(bid))


@bp.post("/preservation/bids/<bidId>/approve")
def approve_bid(bidId):
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    bid = get_or_404(store.bids, bidId, "Bid")
    get_body()
    # Entity-backed ownership: the approver must own the report's property.
    if _report_servicer_id(store.damage_reports.get(bid["damage_report_id"]) or {}) != user_id:
        raise_err("ERR_FORBIDDEN_FOR_ROLE", "Servicer may approve bids only for its own properties")
    if bid["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Bid is not SUBMITTED")
    report = store.damage_reports.get(bid["damage_report_id"])
    if report is None or report["status"] != "BID_REQUESTED":
        raise_err("ERR_DAMAGE_NOT_ACCEPTING_BIDS", "Damage report is not accepting bids")

    prop = store.properties.get(report["property_id"])

    # Spawn the DAMAGE_REPAIR work order (BID_CONVERTED), negotiated cap = bid amount.
    row = select_allowable(prop["investor_type"], "DAMAGE_REPAIR") if prop else None
    wo = new_entity({
        "property_id": report["property_id"],
        "servicer_id": prop["servicer_id"] if prop else None,
        "order_type": "DAMAGE_REPAIR",
        "item_code": "DAMAGE_REPAIR",
        "source": "BID_CONVERTED",
        "status": "ISSUED",
        "due_date": (clock_date() + timedelta(days=14)).isoformat(),
        "scheduled_date": None,
        "assigned_crew_id": None,
        "bid_id": bid["id"],
        "damage_report_id": report["id"],
        "code_violation_id": None,
        "recurring_plan_id": None,
        "investor_allowable_id": row["id"] if row else None,
        "investor_allowable_version": row["version"] if row else None,
        "allowable_cap_cents": bid["amount_cents"],
        "requires_bid_over_cents": row["requires_bid_over_cents"] if row else None,
        "estimated_cost_cents": 0,
        "submitted_cost_cents": None,
        "approved_cost_cents": None,
        "rework_count": 0,
        "evidence_complete": False,
    })
    store.work_orders[wo["id"]] = wo

    bid["status"] = "APPROVED"
    bid["approved_work_order_id"] = wo["id"]
    bump(bid)

    # Cascade link 1: report -> REPAIR_IN_PROGRESS.
    report["status"] = "REPAIR_IN_PROGRESS"
    bump(report)

    # Cascade link 2: competing open bids -> REJECTED.
    for other in store.bids.values():
        if (
            other["id"] != bid["id"]
            and other["damage_report_id"] == report["id"]
            and other["status"] in ("SUBMITTED", "COUNTERED")
        ):
            other["status"] = "REJECTED"
            bump(other)
    return ok(public(bid))


@bp.post("/preservation/bids/<bidId>/counter")
def counter_bid(bidId):
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    bid = get_or_404(store.bids, bidId, "Bid")
    b = get_body()
    if _report_servicer_id(store.damage_reports.get(bid["damage_report_id"]) or {}) != user_id:
        raise_err("ERR_FORBIDDEN_FOR_ROLE", "Servicer may counter bids only for its own properties")
    counter_amount_cents = req_amount(b, "counter_amount_cents")
    opt = b.get("note")
    if opt is not None and not isinstance(opt, str):
        raise_err("ERR_INVALID_REQUEST", "note must be a string")
    if bid["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Bid is not SUBMITTED")
    bid["counter_amount_cents"] = counter_amount_cents
    bid["status"] = "COUNTERED"
    bump(bid)
    return ok(public(bid))


@bp.post("/preservation/bids/<bidId>/revise")
def revise_bid(bidId):
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    bid = get_or_404(store.bids, bidId, "Bid")
    b = get_body()
    amount_cents = req_amount(b, "amount_cents")
    if bid["status"] != "COUNTERED":
        raise_err("ERR_INVALID_STATE", "Bid is not COUNTERED")
    if user_id != bid["submitted_by_crew_id"]:
        raise_err("ERR_NOT_BID_OWNER", "Only the owning crew may revise this bid")
    bid["amount_cents"] = amount_cents
    bid["round_number"] += 1
    bid["status"] = "SUBMITTED"
    bump(bid)
    return ok(public(bid))


@bp.post("/preservation/bids/<bidId>/reject")
def reject_bid(bidId):
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    bid = get_or_404(store.bids, bidId, "Bid")
    b = get_body()
    if _report_servicer_id(store.damage_reports.get(bid["damage_report_id"]) or {}) != user_id:
        raise_err("ERR_FORBIDDEN_FOR_ROLE", "Servicer may reject bids only for its own properties")
    req_str(b, "reason")
    if bid["status"] not in ("SUBMITTED", "COUNTERED"):
        raise_err("ERR_INVALID_STATE", "Bid is not SUBMITTED or COUNTERED")
    bid["status"] = "REJECTED"
    bump(bid)
    return ok(public(bid))


@bp.post("/preservation/bids/<bidId>/withdraw")
def withdraw_bid(bidId):
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    bid = get_or_404(store.bids, bidId, "Bid")
    get_body()
    if bid["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err("ERR_INVALID_STATE", "Bid is not DRAFT or SUBMITTED")
    if user_id != bid["submitted_by_crew_id"]:
        raise_err("ERR_NOT_BID_OWNER", "Only the owning crew may withdraw this bid")
    bid["status"] = "WITHDRAWN"
    bump(bid)
    return ok(public(bid))
