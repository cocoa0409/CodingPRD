"""SubmissionCycle + CapitationRateSchedule routes."""
import math
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store, new_id, now_iso
from middleware import (
    get_auth, require_role, get_body, req_string, req_int, apply_pagination,
)
from response import success_object, success_list
from errors import not_found, invalid_request, invalid_state, ApiError, stale_version
from services.core import (
    parse_iso, parse_date, touch, round4,
    enrolled_overlapping_members,
)

bp = Blueprint("cycles", __name__)

AID_CATEGORIES = {"TANF", "SSI", "DUAL", "EXPANSION", "CHIP"}
HCC_WEIGHTS = {"E11": 0.8, "I50": 1.2, "F32": 0.4, "J45": 0.3, "N18": 1.0}


def cycle_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "program_id": c["program_id"],
        "label": c["label"],
        "window_start_at": c["window_start_at"],
        "window_end_at": c["window_end_at"],
        "submission_deadline_at": c["submission_deadline_at"],
        "effective_deadline_at": c["effective_deadline_at"],
        "extension_status": c["extension_status"],
        "requested_new_deadline_at": c["requested_new_deadline_at"],
        "status": c["status"],
        "intake_encounter_count": c["intake_encounter_count"],
        "net_accepted_encounter_count": c["net_accepted_encounter_count"],
        "net_accepted_paid_cents": c["net_accepted_paid_cents"],
        "risk_computed_at": c["risk_computed_at"],
    }


@bp.route("/programs/cycles", methods=["POST"])
def create_cycle():
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    body = get_body()
    program_id = req_string(body, "program_id")
    label = req_string(body, "label")
    window_start_s = req_string(body, "window_start_at")
    window_end_s = req_string(body, "window_end_at")
    deadline_s = req_string(body, "submission_deadline_at")
    if program_id not in store.programs:
        raise not_found("program not found")
    ws = parse_iso(window_start_s, "window_start_at")
    we = parse_iso(window_end_s, "window_end_at")
    parse_iso(deadline_s, "submission_deadline_at")
    # half-open overlap check; adjacency allowed; window_end > window_start required
    overlap = False
    if not (we > ws):
        overlap = True
    if not overlap:
        for c in store.cycles.values():
            if c["program_id"] != program_id:
                continue
            # overlap iff new.start < existing.end AND existing.start < new.end
            if ws < c["_window_end_at"] and c["_window_start_at"] < we:
                overlap = True
                break
    if overlap:
        raise ApiError("ERR_CYCLE_OVERLAP",
                       "New cycle window overlaps an existing cycle of the program or window_end_at <= window_start_at",
                       409)
    cid = new_id()
    c = {
        "id": cid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "program_id": program_id,
        "label": label,
        "window_start_at": window_start_s,
        "window_end_at": window_end_s,
        "submission_deadline_at": deadline_s,
        "effective_deadline_at": deadline_s,
        "extension_status": "NONE",
        "requested_new_deadline_at": None,
        "status": "OPEN",
        "intake_encounter_count": 0,
        "net_accepted_encounter_count": 0,
        "net_accepted_paid_cents": 0,
        "risk_computed_at": None,
        "_window_start_at": ws,
        "_window_end_at": we,
        "_submission_deadline_at": parse_iso(deadline_s, "submission_deadline_at"),
        "_effective_deadline_at": parse_iso(deadline_s, "submission_deadline_at"),
    }
    store.cycles[cid] = c
    return success_object(cycle_view(c), 201)


@bp.route("/programs/cycles/<cid>", methods=["GET"])
def get_cycle(cid):
    get_auth()
    c = store.cycles.get(cid)
    if c is None:
        raise not_found()
    return success_object(cycle_view(c))


@bp.route("/programs/cycles", methods=["GET"])
def list_cycles():
    get_auth()
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(store.cycles.values())
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = apply_pagination(items)
    return success_list([cycle_view(c) for c in page], limit, offset, total)


@bp.route("/programs/cycles/<cid>/request-extension", methods=["POST"])
def request_extension(cid):
    _, role = get_auth()
    require_role(role, {"McoCompliance"})
    body = get_body()
    requested_s = req_string(body, "requested_new_deadline_at")
    # reason is free-text, required per endpoint table
    if "reason" not in body or body["reason"] is None:
        raise invalid_request("Missing required field: reason")
    if not isinstance(body["reason"], str):
        raise invalid_request("reason must be a string")
    expected_cycle_version = body.get("expected_cycle_version")
    if expected_cycle_version is None or isinstance(expected_cycle_version, bool) or not isinstance(expected_cycle_version, int):
        raise invalid_request("expected_cycle_version is required and must be an integer")
    c = store.cycles.get(cid)
    if c is None:
        raise not_found()
    if c["status"] != "OPEN":
        raise invalid_state("Cycle is not OPEN")
    # OCC check (priority 6) — before temporal gates
    if expected_cycle_version != c["version"]:
        raise stale_version()
    requested_dt = parse_iso(requested_s, "requested_new_deadline_at")
    now = store.clock
    # extension window: now <= effective_deadline_at (boundary inclusive)
    if now > c["_effective_deadline_at"]:
        raise ApiError("ERR_EXTENSION_WINDOW_CLOSED",
                       "Extension requested after the current effective deadline", 409)
    # regression: requested must be strictly greater than current effective deadline
    if requested_dt <= c["_effective_deadline_at"]:
        raise ApiError("ERR_EXTENSION_REGRESSION",
                       "requested_new_deadline_at must be strictly greater than current effective_deadline_at",
                       422)
    c["extension_status"] = "PENDING"
    c["requested_new_deadline_at"] = requested_s
    c["_requested_new_deadline_at"] = requested_dt
    touch(c)
    return success_object(cycle_view(c))


@bp.route("/programs/cycles/<cid>/approve-extension", methods=["POST"])
def approve_extension(cid):
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    get_body(required=False)
    c = store.cycles.get(cid)
    if c is None:
        raise not_found()
    if c["extension_status"] != "PENDING":
        raise ApiError("ERR_EXTENSION_NOT_PENDING",
                       "Approve attempted while extension_status != PENDING", 409)
    c["extension_status"] = "APPROVED"
    c["effective_deadline_at"] = c["requested_new_deadline_at"]
    c["_effective_deadline_at"] = c["_requested_new_deadline_at"]
    touch(c)
    return success_object(cycle_view(c))


@bp.route("/programs/cycles/<cid>/deny-extension", methods=["POST"])
def deny_extension(cid):
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    get_body(required=False)
    c = store.cycles.get(cid)
    if c is None:
        raise not_found()
    if c["extension_status"] != "PENDING":
        raise ApiError("ERR_EXTENSION_NOT_PENDING",
                       "Deny attempted while extension_status != PENDING", 409)
    c["extension_status"] = "DENIED"
    touch(c)
    return success_object(cycle_view(c))


@bp.route("/programs/cycles/<cid>/close", methods=["POST"])
def close_cycle(cid):
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    get_body(required=False)
    c = store.cycles.get(cid)
    if c is None:
        raise not_found()
    if c["status"] != "OPEN":
        raise invalid_state("Cycle is not OPEN")
    now = store.clock
    if not (now > c["_effective_deadline_at"]):
        raise ApiError("ERR_CYCLE_NOT_CLOSABLE", "Deadline has not passed", 409)
    for b in store.batches.values():
        if b["cycle_id"] == cid and b["status"] in ("SEALED", "TRANSMITTED", "ACKNOWLEDGED", "PARTIAL"):
            raise ApiError("ERR_CYCLE_NOT_CLOSABLE", "Unreconciled batch exists", 409)
    audit = None
    for a in store.audits.values():
        if a["cycle_id"] == cid:
            audit = a
            break
    if audit is None or audit["status"] != "DETERMINED":
        raise ApiError("ERR_CYCLE_NOT_CLOSABLE", "Audit not DETERMINED", 409)
    stmt = None
    for s in store.statements.values():
        if s["cycle_id"] == cid:
            stmt = s
            break
    if stmt is None or stmt["status"] != "RECONCILED":
        raise ApiError("ERR_CYCLE_NOT_CLOSABLE", "Statement not RECONCILED", 409)
    # close: DRAFT batches -> DISCARDED; their STAGED encounters -> VALIDATED
    for b in store.batches.values():
        if b["cycle_id"] == cid and b["status"] == "DRAFT":
            for e in store.encounters.values():
                if e.get("batch_id") == b["id"] and e["status"] == "STAGED":
                    e["batch_id"] = None
                    e["status"] = "VALIDATED"
                    touch(e)
            b["status"] = "DISCARDED"
            touch(b)
    c["status"] = "CLOSED"
    touch(c)
    return success_object(cycle_view(c))


@bp.route("/programs/cycles/<cid>/compute-risk-scores", methods=["POST"])
def compute_risk_scores(cid):
    _, role = get_auth()
    require_role(role, {"McoFinance"})
    get_body(required=False)
    c = store.cycles.get(cid)
    if c is None:
        raise not_found()
    # reject if existing snapshots are APPLIED
    existing = [s for s in store.risk_snapshots.values() if s["cycle_id"] == cid]
    if any(s["status"] == "APPLIED" for s in existing):
        raise invalid_state("Risk snapshots already APPLIED")

    members = enrolled_overlapping_members(c["program_id"], c["_window_start_at"], c["_window_end_at"])
    ws_date = c["_window_start_at"].date()
    we_date = c["_window_end_at"].date()

    # pass 1: raw scores
    raw = {}
    for m in members:
        prefixes = set()
        for e in store.encounters.values():
            if e["member_id"] != m["id"]:
                continue
            if e["status"] != "ACKNOWLEDGED":
                continue
            sfd = e["_service_from_date"]
            if not (ws_date <= sfd < we_date):
                continue
            for code in e["diagnosis_codes"]:
                if isinstance(code, str) and len(code) >= 3:
                    prefixes.add(code[:3])
        score = Decimal("0")
        for p in prefixes:
            w = HCC_WEIGHTS.get(p)
            if w is not None:
                score += Decimal(str(w))
        raw[m["id"]] = score

    # pass 2: average across enrolled-overlapping members (zero-raw included)
    if members:
        avg = sum(raw.values(), Decimal("0")) / Decimal(len(members))
    else:
        avg = Decimal("0")

    # pass 3: normalize (4dp round half up); avg == 0 => all 1.0
    snapshots_by_member = {s["member_id"]: s for s in existing}
    out = []
    for m in members:
        if avg == 0:
            normalized = 1.0
        else:
            normalized = round4(raw[m["id"]] / avg)
        raw_f = round4(raw[m["id"]])
        existing_snap = snapshots_by_member.get(m["id"])
        if existing_snap is not None:
            existing_snap["raw_score"] = raw_f
            existing_snap["normalized_score"] = normalized
            touch(existing_snap)
            out.append(existing_snap)
        else:
            sid = new_id()
            snap = {
                "id": sid,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "version": 1,
                "cycle_id": cid,
                "member_id": m["id"],
                "raw_score": raw_f,
                "normalized_score": normalized,
                "status": "COMPUTED",
            }
            store.risk_snapshots[sid] = snap
            out.append(snap)
    c["risk_computed_at"] = now_iso()
    touch(c)
    out_sorted = sorted(out, key=lambda s: (s["created_at"], s["id"]))
    return success_list([snapshot_view(s) for s in out_sorted], len(out_sorted) or 1, 0, len(out_sorted))


def snapshot_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "cycle_id": s["cycle_id"],
        "member_id": s["member_id"],
        "raw_score": s["raw_score"],
        "normalized_score": s["normalized_score"],
        "status": s["status"],
    }


# --------------------------------------------------------- rate schedules ---

def schedule_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "program_id": s["program_id"],
        "aid_category": s["aid_category"],
        "pmpm_cents": s["pmpm_cents"],
        "effective_from": s["effective_from"],
        "effective_to": s["effective_to"],
    }


@bp.route("/programs/rate-schedules", methods=["POST"])
def create_rate_schedule():
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    body = get_body()
    program_id = req_string(body, "program_id")
    aid_category = req_string(body, "aid_category")
    if aid_category not in AID_CATEGORIES:
        raise invalid_request("aid_category must be one of TANF, SSI, DUAL, EXPANSION, CHIP")
    pmpm_cents = req_int(body, "pmpm_cents")
    if pmpm_cents <= 0:
        raise invalid_request("pmpm_cents must be > 0")
    effective_from_s = req_string(body, "effective_from")
    effective_to_s = req_string(body, "effective_to")
    if program_id not in store.programs:
        raise not_found("program not found")
    ef = parse_date(effective_from_s, "effective_from")
    et = parse_date(effective_to_s, "effective_to")
    # closed window: adjacency IS overlap
    overlap = False
    if et < ef:
        overlap = True
    if not overlap:
        for s in store.rate_schedules.values():
            if s["program_id"] != program_id or s["aid_category"] != aid_category:
                continue
            # closed intervals overlap iff new.from <= existing.to AND existing.from <= new.to
            if ef <= s["_effective_to"] and s["_effective_from"] <= et:
                overlap = True
                break
    if overlap:
        raise ApiError("ERR_RATE_SCHEDULE_OVERLAP",
                       "New rate schedule overlaps an existing schedule of the same (program, aid_category)",
                       409)
    sid = new_id()
    s = {
        "id": sid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "program_id": program_id,
        "aid_category": aid_category,
        "pmpm_cents": pmpm_cents,
        "effective_from": effective_from_s,
        "effective_to": effective_to_s,
        "_effective_from": ef,
        "_effective_to": et,
    }
    store.rate_schedules[sid] = s
    return success_object(schedule_view(s), 201)


@bp.route("/programs/rate-schedules/<sid>", methods=["GET"])
def get_rate_schedule(sid):
    get_auth()
    s = store.rate_schedules.get(sid)
    if s is None:
        raise not_found()
    return success_object(schedule_view(s))


@bp.route("/programs/rate-schedules", methods=["GET"])
def list_rate_schedules():
    get_auth()
    program_id = request.args.get("program_id")
    aid_category = request.args.get("aid_category")
    items = list(store.rate_schedules.values())
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    if aid_category is not None:
        items = [s for s in items if s["aid_category"] == aid_category]
    page, limit, offset, total = apply_pagination(items)
    return success_list([schedule_view(s) for s in page], limit, offset, total)


# Expose snapshot_view for other blueprints
__all__ = ["bp", "cycle_view", "snapshot_view", "HCC_WEIGHTS"]
