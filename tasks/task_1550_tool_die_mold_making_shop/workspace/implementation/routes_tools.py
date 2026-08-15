"""Tool asset shipping/lien, shot reports, warranty claims, spare inserts
(PRD §3.8, §3.9)."""
from flask import Blueprint, request

from store import STORE, now
from helpers import (ApiError, endpoint, get_body, validate_payload, ok, created,
                     ok_list, paginate, filter_eq, sort_created, not_found,
                     stamp_new, stamp_new_noversion, bump)
from domain import (ser_tool, ser_shot_report, ser_claim, ser_insert,
                    eval_ownership, job_outstanding_cents, ship_threshold_cents,
                    warranty_credit)

bp = Blueprint("tools", __name__)


# ---------------------------------------------------------------------------
# Tool assets: shipping, delivery, ownership transfer (PRD §3.8)
# ---------------------------------------------------------------------------

@bp.route("/tool-assets", methods=["GET"])
@endpoint(roles=None)
def list_tools(uid, role):
    items = sort_created(list(STORE.tools.values()))
    items = filter_eq(items, "customer_id", request.args.get("customer_id"))
    items = filter_eq(items, "build_job_id", request.args.get("build_job_id"))
    items = filter_eq(items, "physical_status", request.args.get("physical_status"))
    items = filter_eq(items, "ownership_status", request.args.get("ownership_status"))
    page, meta = paginate(items)
    return ok_list([ser_tool(t) for t in page], meta)


@bp.route("/tool-assets/<toolId>", methods=["GET"])
@endpoint(roles=None)
def get_tool(uid, role, toolId):
    tool = STORE.tools.get(toolId)
    if tool is None:
        not_found("TOOL_ASSET")
    return ok(ser_tool(tool))


@bp.route("/tool-assets/<toolId>/ship", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def ship_tool(uid, role, toolId):
    data = validate_payload(get_body(), [
        ("carrier", "str", True),
        ("tracking_number", "str", True),
    ])
    tool = STORE.tools.get(toolId)
    if tool is None:
        not_found("TOOL_ASSET")
    job = STORE.jobs.get(tool["build_job_id"])
    # State gate first, then the fiscal lien gate (PRD §3.8).
    if tool["physical_status"] != "AWAITING_SHIPMENT" or job is None or job["status"] != "READY_TO_SHIP":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Shipping requires the tool AWAITING_SHIPMENT and the job READY_TO_SHIP")
    if job_outstanding_cents(job) > ship_threshold_cents(job):
        raise ApiError("ERR_RETENTION_LIEN_BLOCK", 402,
                       "Outstanding balance exceeds the tooler's lien threshold")
    tool["carrier"] = data["carrier"]
    tool["tracking_number"] = data["tracking_number"]
    tool["shipped_at"] = now()
    tool["physical_status"] = "IN_TRANSIT"
    bump(tool)
    job["status"] = "SHIPPED"
    bump(job)
    return ok(ser_tool(tool))


@bp.route("/tool-assets/<toolId>/deliver", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def deliver_tool(uid, role, toolId):
    validate_payload(get_body(), [])
    tool = STORE.tools.get(toolId)
    if tool is None:
        not_found("TOOL_ASSET")
    if tool["physical_status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IN_TRANSIT tool may be delivered")
    tool["physical_status"] = "IN_PRODUCTION"
    tool["delivered_at"] = now()
    bump(tool)
    job = STORE.jobs.get(tool["build_job_id"])
    if job is not None:
        eval_ownership(job)
    return ok(ser_tool(tool))


# ---------------------------------------------------------------------------
# Shot reports (PRD §3.9)
# ---------------------------------------------------------------------------

@bp.route("/shot-reports", methods=["POST"])
@endpoint(roles=["Customer"])
def create_shot_report(uid, role):
    data = validate_payload(get_body(), [
        ("tool_asset_id", "str", True),
        ("report_period_end", "datetime", True),
        ("shots_in_period", "int", True, {"min": 1}),
    ])
    tool = STORE.tools.get(data["tool_asset_id"])
    if tool is None:
        not_found("TOOL_ASSET")
    if tool["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Customers report shots only for their own tools")
    # Tier 9: the period must not end in the future.
    if data["report_period_end"] > now():
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422,
                       "report_period_end must not lie in the future")
    # Tier 10: strictly increasing period ends across ACTIVE reports.
    for prior in STORE.shot_reports.values():
        if (prior["tool_asset_id"] == tool["id"] and prior["status"] == "ACTIVE"
                and data["report_period_end"] <= prior["report_period_end"]):
            raise ApiError("ERR_NON_MONOTONIC_SHOT_PERIOD", 409,
                           "report_period_end must be strictly later than prior ACTIVE reports")
    # Tier 11: the tool must be in production.
    if tool["physical_status"] != "IN_PRODUCTION":
        raise ApiError("ERR_TOOL_NOT_IN_PRODUCTION", 409,
                       "Shot reports require the tool IN_PRODUCTION")
    report = stamp_new_noversion({
        "tool_asset_id": tool["id"],
        "report_period_end": data["report_period_end"],
        "shots_in_period": data["shots_in_period"],
        "status": "ACTIVE",
    })
    STORE.shot_reports[report["id"]] = report
    tool["reported_shots"] += data["shots_in_period"]
    bump(tool)
    return created(ser_shot_report(report))


@bp.route("/shot-reports", methods=["GET"])
@endpoint(roles=None)
def list_shot_reports(uid, role):
    items = sorted(STORE.shot_reports.values(),
                   key=lambda r: (r["report_period_end"], r["_seq"]))
    items = filter_eq(items, "tool_asset_id", request.args.get("tool_asset_id"))
    page, meta = paginate(items)
    return ok_list([ser_shot_report(r) for r in page], meta)


@bp.route("/shot-reports/<reportId>", methods=["GET"])
@endpoint(roles=None)
def get_shot_report(uid, role, reportId):
    report = STORE.shot_reports.get(reportId)
    if report is None:
        not_found("SHOT_REPORT")
    return ok(ser_shot_report(report))


@bp.route("/shot-reports/<reportId>/reverse", methods=["POST"])
@endpoint(roles=["Customer"])
def reverse_shot_report(uid, role, reportId):
    validate_payload(get_body(), [])
    report = STORE.shot_reports.get(reportId)
    if report is None:
        not_found("SHOT_REPORT")
    tool = STORE.tools.get(report["tool_asset_id"])
    if tool is None or tool["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Customers reverse reports only for their own tools")
    if report["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACTIVE shot report may be reversed")
    # Conserved-quantity guard: reversal must not invalidate a filed claim.
    lifetime = tool["tryout_shots"] + tool["reported_shots"]
    for claim in STORE.claims.values():
        if (claim["tool_asset_id"] == tool["id"]
                and claim["status"] in ("FILED", "REPAIR_SCHEDULED")
                and claim["claimed_at_shot_count"] > lifetime - report["shots_in_period"]):
            raise ApiError("ERR_SHOT_REVERSAL_BLOCKED", 409,
                           "Reversal would drop lifetime shots below a filed claim's snapshot")
    report["status"] = "REVERSED"
    tool["reported_shots"] -= report["shots_in_period"]
    bump(tool)
    return ok(ser_shot_report(report))


# ---------------------------------------------------------------------------
# Warranty claims (PRD §3.9)
# ---------------------------------------------------------------------------

@bp.route("/warranty-claims", methods=["POST"])
@endpoint(roles=["Customer"])
def create_claim(uid, role):
    data = validate_payload(get_body(), [
        ("tool_asset_id", "str", True),
        ("defect_description", "str", True),
        ("estimated_repair_cost_cents", "int", True, {"min": 1}),
    ])
    tool = STORE.tools.get(data["tool_asset_id"])
    if tool is None:
        not_found("TOOL_ASSET")
    if tool["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Customers file claims only for their own tools")
    # Pinned gate order: time expiry first, then the shot limit (PRD §3.9).
    if tool["warranty_expires_at"] is not None and now() > tool["warranty_expires_at"]:
        raise ApiError("ERR_WARRANTY_TIME_EXPIRED", 422,
                       "The warranty period has expired")
    lifetime = tool["tryout_shots"] + tool["reported_shots"]
    if lifetime > tool["warranty_shot_limit"]:
        raise ApiError("ERR_WARRANTY_SHOT_LIMIT_EXCEEDED", 422,
                       "The tool's lifetime shots exceed the warranty shot limit")
    if tool["physical_status"] not in ("IN_PRODUCTION", "RETURNED_FOR_REPAIR"):
        raise ApiError("ERR_TOOL_NOT_IN_PRODUCTION", 409,
                       "Warranty claims require the tool IN_PRODUCTION or RETURNED_FOR_REPAIR")
    claim = stamp_new({
        "tool_asset_id": tool["id"],
        "defect_description": data["defect_description"],
        "estimated_repair_cost_cents": data["estimated_repair_cost_cents"],
        "claimed_at_shot_count": lifetime,
        "approved_credit_cents": None,
        "denial_reason": None,
        "status": "FILED",
    })
    STORE.claims[claim["id"]] = claim
    return created(ser_claim(claim))


@bp.route("/warranty-claims", methods=["GET"])
@endpoint(roles=None)
def list_claims(uid, role):
    items = sort_created(list(STORE.claims.values()))
    items = filter_eq(items, "tool_asset_id", request.args.get("tool_asset_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_claim(c) for c in page], meta)


@bp.route("/warranty-claims/<claimId>", methods=["GET"])
@endpoint(roles=None)
def get_claim(uid, role, claimId):
    claim = STORE.claims.get(claimId)
    if claim is None:
        not_found("WARRANTY_CLAIM")
    return ok(ser_claim(claim))


@bp.route("/warranty-claims/<claimId>/review", methods=["POST"])
@endpoint(roles=["QualityManager"])
def review_claim(uid, role, claimId):
    body = get_body()
    data = validate_payload(body, [
        ("decision", "enum", True, {"values": {"APPROVE", "DENY"}}),
        ("denial_reason", "str", False),
    ])
    # Shape tier: DENY requires a non-empty denial_reason.
    if data["decision"] == "DENY" and not data.get("denial_reason"):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "denial_reason must be non-empty when denying a claim")
    claim = STORE.claims.get(claimId)
    if claim is None:
        not_found("WARRANTY_CLAIM")
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a FILED claim may be reviewed")
    if data["decision"] == "DENY":
        claim["denial_reason"] = data["denial_reason"]
        claim["status"] = "DENIED"
        bump(claim)
        return ok(ser_claim(claim))
    tool = STORE.tools.get(claim["tool_asset_id"])
    claim["approved_credit_cents"] = warranty_credit(tool, claim)
    claim["status"] = "REPAIR_SCHEDULED"
    bump(claim)
    if tool is not None and tool["physical_status"] == "IN_PRODUCTION":
        tool["physical_status"] = "RETURNED_FOR_REPAIR"
        bump(tool)
    return ok(ser_claim(claim))


@bp.route("/warranty-claims/<claimId>/close", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def close_claim(uid, role, claimId):
    validate_payload(get_body(), [])
    claim = STORE.claims.get(claimId)
    if claim is None:
        not_found("WARRANTY_CLAIM")
    if claim["status"] != "REPAIR_SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a REPAIR_SCHEDULED claim may be closed")
    claim["status"] = "CLOSED"
    bump(claim)
    tool = STORE.tools.get(claim["tool_asset_id"])
    if tool is not None and tool["physical_status"] == "RETURNED_FOR_REPAIR":
        tool["physical_status"] = "IN_PRODUCTION"
        bump(tool)
    return ok(ser_claim(claim))


# ---------------------------------------------------------------------------
# Spare inserts (PRD §3.9)
# ---------------------------------------------------------------------------

@bp.route("/spare-inserts", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def create_insert(uid, role):
    data = validate_payload(get_body(), [
        ("tool_asset_id", "str", True),
        ("insert_code", "str", True),
        ("unit_cost_cents", "int", True, {"min": 0}),
        ("initial_on_hand", "int", True, {"min": 0}),
        ("reorder_point", "int", True, {"min": 0}),
    ])
    tool = STORE.tools.get(data["tool_asset_id"])
    if tool is None:
        not_found("TOOL_ASSET")
    insert = stamp_new({
        "tool_asset_id": tool["id"],
        "insert_code": data["insert_code"],
        "unit_cost_cents": data["unit_cost_cents"],
        "on_hand": data["initial_on_hand"],
        "reorder_point": data["reorder_point"],
        "status": "DEPLETED" if data["initial_on_hand"] == 0 else "ACTIVE",
    })
    STORE.inserts[insert["id"]] = insert
    return created(ser_insert(insert))


@bp.route("/spare-inserts", methods=["GET"])
@endpoint(roles=None)
def list_inserts(uid, role):
    items = sort_created(list(STORE.inserts.values()))
    items = filter_eq(items, "tool_asset_id", request.args.get("tool_asset_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_insert(s) for s in page], meta)


@bp.route("/spare-inserts/<insertId>", methods=["GET"])
@endpoint(roles=None)
def get_insert(uid, role, insertId):
    insert = STORE.inserts.get(insertId)
    if insert is None:
        not_found("SPARE_INSERT")
    return ok(ser_insert(insert))


@bp.route("/spare-inserts/<insertId>/allocate", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def allocate_insert(uid, role, insertId):
    data = validate_payload(get_body(), [
        ("quantity", "int", True, {"min": 1}),
    ])
    insert = STORE.inserts.get(insertId)
    if insert is None:
        not_found("SPARE_INSERT")
    if insert["status"] == "DISCONTINUED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A DISCONTINUED insert may not be allocated")
    if data["quantity"] > insert["on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_STOCK", 409,
                       "Allocation quantity exceeds stock on hand")
    tool = STORE.tools.get(insert["tool_asset_id"])
    if tool is None or tool["physical_status"] != "IN_PRODUCTION":
        raise ApiError("ERR_TOOL_NOT_IN_PRODUCTION", 409,
                       "Allocation requires the tool IN_PRODUCTION")
    insert["on_hand"] -= data["quantity"]
    if insert["on_hand"] == 0:
        insert["status"] = "DEPLETED"
    bump(insert)
    return ok(ser_insert(insert))


@bp.route("/spare-inserts/<insertId>/restock", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def restock_insert(uid, role, insertId):
    data = validate_payload(get_body(), [
        ("quantity", "int", True, {"min": 1}),
    ])
    insert = STORE.inserts.get(insertId)
    if insert is None:
        not_found("SPARE_INSERT")
    if insert["status"] == "DISCONTINUED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A DISCONTINUED insert may not be restocked")
    insert["on_hand"] += data["quantity"]
    if insert["status"] == "DEPLETED" and insert["on_hand"] > 0:
        insert["status"] = "ACTIVE"
    bump(insert)
    return ok(ser_insert(insert))


@bp.route("/spare-inserts/<insertId>/discontinue", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def discontinue_insert(uid, role, insertId):
    validate_payload(get_body(), [])
    insert = STORE.inserts.get(insertId)
    if insert is None:
        not_found("SPARE_INSERT")
    if insert["status"] not in ("ACTIVE", "DEPLETED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACTIVE or DEPLETED insert may be discontinued")
    insert["status"] = "DISCONTINUED"
    bump(insert)
    return ok(ser_insert(insert))
