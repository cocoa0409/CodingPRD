"""Sub-certification requests and officer certification slots."""
from decimal import Decimal

from flask import Blueprint, request

import calc
from authz import (
    ALL_ROLES,
    ROLE_BUSINESS,
    ROLE_CHAIR,
    ROLE_COMPLIANCE_ADMIN,
    ROLE_OFFICER,
    authorize,
    gate_action,
    require_action,
)
from core import TouchLog, bad, dec, fmt_instant, parse_instant, public, store, success_object
from helpers import apply_eq, paged, sort_created_asc
from validate import (
    as_enum,
    as_instant,
    as_string,
    body_of,
    enum_filter,
    opt_string,
    pagination,
    present,
    req_present,
    str_filter,
)

bp = Blueprint("cert", __name__)

SCOPE_AREAS = ("REVENUE", "LEGAL_CONTINGENCY", "OPERATIONS", "IR_COMMUNICATIONS", "IT_CONTROLS")
SUBCERT_STATUSES = ("PENDING", "SUBMITTED", "EXCEPTION_NOTED", "WITHDRAWN", "VOID")
SEVERITIES = ("NONE", "LOW", "MEDIUM", "HIGH")
CERT_TYPES = ("CEO_302", "CFO_302", "CEO_906", "CFO_906")
CERT_STATUSES = ("BLOCKED", "ELIGIBLE", "SIGNED", "REVOKED", "VOID")


@bp.get("/disclosure/sub-certifications")
def list_subcerts():
    authorize(request, ALL_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("subcert")
    rows = apply_eq(rows, "cycle_id", str_filter(request.args, "cycle_id"))
    rows = apply_eq(rows, "member_id", str_filter(request.args, "member_id"))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", SUBCERT_STATUSES))
    rows = apply_eq(rows, "scope_area", enum_filter(request.args, "scope_area", SCOPE_AREAS))
    return paged(sort_created_asc(rows), limit, offset)


@bp.get("/disclosure/sub-certifications/<subcert_id>")
def get_subcert(subcert_id):
    authorize(request, ALL_ROLES)
    return success_object(public(store.must_get("subcert", subcert_id)))


@bp.post("/disclosure/sub-certifications")
def create_subcert():
    authorize(request, [ROLE_CHAIR])
    body = body_of(request)
    cycle = None
    member = None
    if present(body, "cycle_id"):
        cycle = store.must_get("cycle", body["cycle_id"])
    if present(body, "member_id"):
        member = store.must_get("member", body["member_id"])
    if cycle is None:
        req_present(body, "cycle_id")
    if member is None:
        req_present(body, "member_id")
    scope_area = as_enum(req_present(body, "scope_area"), "scope_area", SCOPE_AREAS)
    due_instant = as_instant(req_present(body, "due_utc"), "due_utc")

    if cycle["status"] == "ABANDONED":
        bad("ERR_ENTITY_TERMINAL", "cycle is ABANDONED")
    if cycle["status"] not in ("CLOSE_OPEN", "REVIEW_OPEN", "CERTIFICATION_OPEN"):
        bad("ERR_INVALID_STATE", "the cycle does not accept sub-certification assignments")

    for row in store.where("subcert", cycle_id=cycle["id"], member_id=member["id"], scope_area=scope_area):
        if row["status"] in calc.SUBCERT_LIVE_STATUSES:
            bad("ERR_DUPLICATE_SUBCERT", "a live request already exists for this scope area")

    if member["charter_id"] != cycle["charter_id"]:
        bad("ERR_MEMBER_CHARTER_MISMATCH", "the member does not belong to the cycle's charter")
    if member["status"] != "ACTIVE":
        bad("ERR_MEMBER_SEAT_INVALID", "the member's seat is not ACTIVE")

    for cert in store.where("officer_cert", cycle_id=cycle["id"], officer_member_id=member["id"]):
        if cert["status"] != "VOID":
            bad("ERR_SOD_OFFICER_SUBCERT", "an officer may not sub-certify to itself")

    now = store.clock.now()
    internal_target = parse_instant(cycle["internal_target_utc"])
    if not (due_instant > now and due_instant <= internal_target):
        bad("ERR_SUBCERT_DUE_OUT_OF_WINDOW", "due_utc must be after now and at or before internal_target_utc")

    candidate_start, candidate_end = calc.prep_window(due_instant)
    occupants = 0
    for row in store.where("subcert", member_id=member["id"]):
        if row["status"] not in ("PENDING", "SUBMITTED"):
            continue
        other_start = parse_instant(row["prep_window_start_utc"])
        other_end = parse_instant(row["due_utc"])
        if candidate_start <= other_end and other_start <= candidate_end:
            occupants += 1
    if occupants >= calc.MEMBER_CONCURRENT_SUBCERT_CAP:
        bad("ERR_MEMBER_PREP_WINDOW_CAPACITY", "the member already carries two concurrent preparation windows")

    log = TouchLog()
    row = store.new_row(
        "subcert",
        {
            "cycle_id": cycle["id"],
            "member_id": member["id"],
            "scope_area": scope_area,
            "due_utc": fmt_instant(due_instant),
            "status": "PENDING",
            "exception_severity": "NONE",
            "exception_note": None,
            "submitted_utc": None,
            "scope_weight": calc.subcert_scope_weight(scope_area, member["is_officer"], "NONE"),
            "prep_window_start_utc": fmt_instant(candidate_start),
        },
    )
    calc.recompute_total_assigned_scope_weight(cycle)
    calc.recompute_certification_coverage_pct(cycle)
    log.touch(cycle)
    return success_object(public(row), 201)


@bp.post("/disclosure/sub-certifications/<subcert_id>/transitions")
def transition_subcert(subcert_id):
    actor = authorize(request, [ROLE_BUSINESS, ROLE_CHAIR])
    body = body_of(request)
    gate_action(actor, "subcert", body)
    row = store.must_get("subcert", subcert_id)
    action = require_action("subcert", body)
    severity = "NONE"
    note = None
    if action == "SUBMIT":
        if present(body, "exception_severity"):
            severity = as_enum(body["exception_severity"], "exception_severity", SEVERITIES)
        if severity != "NONE":
            note = as_string(req_present(body, "exception_note"), "exception_note", 2000)

    if row["status"] in ("WITHDRAWN", "VOID"):
        bad("ERR_ENTITY_TERMINAL", "request is %s" % row["status"])
    cycle = store.get("cycle", row["cycle_id"])

    log = TouchLog()
    if action == "SUBMIT":
        if row["status"] != "PENDING":
            bad("ERR_INVALID_STATE", "SUBMIT requires a PENDING request")
        if cycle is None or cycle["status"] not in ("CLOSE_OPEN", "REVIEW_OPEN", "CERTIFICATION_OPEN"):
            bad("ERR_INVALID_STATE", "the cycle does not admit submissions")
        acting = actor.member
        if acting is None or acting["id"] != row["member_id"]:
            bad("ERR_MEMBER_SEAT_INVALID", "only the owning member may submit this request")
        if acting["status"] != "ACTIVE":
            bad("ERR_MEMBER_SEAT_INVALID", "the acting member's seat is not ACTIVE")
        row["submitted_utc"] = store.clock.now_iso()
        if severity == "NONE":
            row["status"] = "SUBMITTED"
        else:
            row["status"] = "EXCEPTION_NOTED"
            row["exception_severity"] = severity
            row["exception_note"] = note
            member = store.get("member", row["member_id"])
            is_officer = bool(member["is_officer"]) if member else False
            row["scope_weight"] = calc.subcert_scope_weight(row["scope_area"], is_officer, severity)
    else:
        if row["status"] != "PENDING":
            bad("ERR_INVALID_STATE", "WITHDRAW requires a PENDING request")
        if cycle is None or cycle["status"] in ("FILED", "AMENDED"):
            bad("ERR_INVALID_STATE", "the cycle does not admit withdrawal")
        row["status"] = "WITHDRAWN"
    log.touch(row)
    if cycle is not None:
        calc.recompute_total_assigned_scope_weight(cycle)
        calc.recompute_certification_coverage_pct(cycle)
        log.touch(cycle)
    return success_object(public(row))


@bp.get("/disclosure/officer-certifications")
def list_officer_certs():
    authorize(request, ALL_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("officer_cert")
    rows = apply_eq(rows, "cycle_id", str_filter(request.args, "cycle_id"))
    rows = apply_eq(rows, "officer_member_id", str_filter(request.args, "officer_member_id"))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", CERT_STATUSES))
    return paged(sort_created_asc(rows), limit, offset)


@bp.get("/disclosure/officer-certifications/<cert_id>")
def get_officer_cert(cert_id):
    authorize(request, ALL_ROLES)
    return success_object(public(store.must_get("officer_cert", cert_id)))


@bp.post("/disclosure/officer-certifications")
def create_officer_cert():
    authorize(request, [ROLE_COMPLIANCE_ADMIN])
    body = body_of(request)
    cycle = None
    member = None
    if present(body, "cycle_id"):
        cycle = store.must_get("cycle", body["cycle_id"])
    if present(body, "officer_member_id"):
        member = store.must_get("member", body["officer_member_id"])
    if cycle is None:
        req_present(body, "cycle_id")
    if member is None:
        req_present(body, "officer_member_id")
    cert_type = as_enum(req_present(body, "cert_type"), "cert_type", CERT_TYPES)

    if cycle["status"] == "ABANDONED":
        bad("ERR_ENTITY_TERMINAL", "cycle is ABANDONED")

    for cert in store.where("officer_cert", cycle_id=cycle["id"], cert_type=cert_type):
        if cert["status"] != "VOID":
            bad("ERR_DUPLICATE_CERTIFICATION", "a live certification of this type already exists")

    if member["charter_id"] != cycle["charter_id"]:
        bad("ERR_MEMBER_CHARTER_MISMATCH", "the member does not belong to the cycle's charter")
    if member["status"] != "ACTIVE" or member["is_officer"] is not True:
        bad("ERR_MEMBER_SEAT_INVALID", "the named seat must be ACTIVE and an officer")

    log = TouchLog()
    row = store.new_row(
        "officer_cert",
        {
            "cycle_id": cycle["id"],
            "officer_member_id": member["id"],
            "cert_type": cert_type,
            "status": "BLOCKED",
            "attestation_text": None,
            "signed_utc": None,
            "coverage_pct_at_signing": None,
        },
    )
    if (
        cycle["status"] == "CERTIFICATION_OPEN"
        and dec(cycle["certification_coverage_pct"]) == calc.COVERAGE_REQUIRED_PCT
        and cycle["open_material_event_count"] == 0
        and dec(cycle["unresolved_deficiency_weight"]) == Decimal("0.00")
    ):
        row["status"] = "ELIGIBLE"
    log.touch(cycle)
    return success_object(public(row), 201)


@bp.post("/disclosure/officer-certifications/<cert_id>/sign")
def sign_officer_cert(cert_id):
    actor = authorize(request, [ROLE_OFFICER])
    body = body_of(request)
    cert = store.must_get("officer_cert", cert_id)
    attestation_text = as_string(req_present(body, "attestation_text"), "attestation_text", 4000)

    if cert["status"] == "VOID":
        bad("ERR_ENTITY_TERMINAL", "certification is VOID")
    if cert["status"] != "ELIGIBLE":
        bad("ERR_INVALID_STATE", "the slot must be ELIGIBLE")

    acting = actor.member
    if acting is None or acting["id"] != cert["officer_member_id"] or acting["is_officer"] is not True:
        bad("ERR_MEMBER_FUNCTION_MISMATCH", "only the named officer may sign this slot")

    cycle = store.get("cycle", cert["cycle_id"])
    if cycle is None or cycle["status"] != "CERTIFICATION_OPEN":
        bad("ERR_INVALID_STATE", "the cycle must be in CERTIFICATION_OPEN")
    if acting["status"] != "ACTIVE":
        bad("ERR_MEMBER_SEAT_INVALID", "the acting member's seat is not ACTIVE")

    charter = store.get("charter", cycle["charter_id"])
    if charter is None or not calc.charter_quorum_ok(charter):
        bad("ERR_QUORUM_NOT_MET", "active voting members below min_quorum_count")
    if cycle["open_material_event_count"] != 0:
        bad("ERR_OPEN_MATERIAL_EVENT", "the cycle carries open material events")
    if not calc.cycle_has_live_subcert_scope(cycle):
        bad("ERR_CERT_SCOPE_EMPTY", "the cycle carries no live sub-certification scope")
    if dec(cycle["certification_coverage_pct"]) != calc.COVERAGE_REQUIRED_PCT:
        bad("ERR_CERT_COVERAGE_INSUFFICIENT", "certification coverage is below 100.00")
    for row in store.where("subcert", cycle_id=cycle["id"], member_id=acting["id"]):
        if row["status"] in calc.SUBCERT_LIVE_STATUSES:
            bad("ERR_SOD_OFFICER_SUBCERT", "an officer holding a live sub-certification may not sign")

    log = TouchLog()
    cert["status"] = "SIGNED"
    cert["attestation_text"] = attestation_text
    cert["signed_utc"] = store.clock.now_iso()
    cert["coverage_pct_at_signing"] = cycle["certification_coverage_pct"]
    log.touch(cert)
    return success_object(public(cert))
