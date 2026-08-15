"""Entry endpoints: create/list/get, materials, submit, waive-fee,
eligibility rulings, recheck, withdraw, and entry-scoped collections."""
import re
from datetime import timedelta

from flask import Blueprint, request

import audit
import clock
import services
import store
from auth import authenticate, authorize, forbid
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_OUTSIDE_WINDOW,
    ERR_ELIGIBILITY_WINDOW, ERR_CONSTRAINT_VIOLATION, ERR_FISCAL_BLOCK,
    ERR_EMBARGO_ACTIVE, ERR_APPEAL_CAP_EXCEEDED,
)
from util import (
    body_json, req_str, req_int, req_enum, req_datetime, new_record,
    new_child_record, bump, success_object, list_response, get_or_404,
    ref_or_404,
)

bp = Blueprint("entries", __name__)

MATERIAL_TYPES = ["VIDEO", "AUDIO", "PDF", "IMAGE", "URL"]
CHECKSUM_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _own_entry_or_forbid(entry, uid):
    if entry["entrant_id"] != uid:
        forbid("Entrant may only act on their own entries")


def _embargo_protected(season):
    """PRD 2.10: result data is protected while FINALISTS_LOCKED/EMBARGOED and
    the clock has not reached embargo_lifts_at."""
    if season is None or season["status"] not in ("FINALISTS_LOCKED", "EMBARGOED"):
        return False
    lift = season.get("embargo_lifts_at")
    return lift is None or clock.now() < lift


# ---------------------------------------------------------------------------
# entries under a category
# ---------------------------------------------------------------------------
@bp.post("/awards/categories/<cid>/entries")
def create_entry(cid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    cat = get_or_404(store.categories, cid, "Category")
    body = body_json()
    entrant_id = req_str(body, "entrant_id")
    title = req_str(body, "title")
    work_completed_at = req_datetime(body, "work_completed_at")
    entrant = ref_or_404(store.entrants, entrant_id, "Entrant")
    if entrant["id"] != uid:
        forbid("Entrant may only create entries for themselves")
    season = services.season_of_category(cat)
    if cat["status"] != "PUBLISHED" or season is None \
            or season["status"] not in ("DRAFT", "OPEN"):
        raise_err(ERR_INVALID_STATE,
                  "entries may be created only in a PUBLISHED category of a DRAFT or OPEN season")
    rec = new_record()
    rec.update({
        "category_id": cat["id"],
        "entrant_id": entrant["id"],
        "title": title,
        "work_completed_at": work_completed_at,
        "status": "DRAFT",
        "payment_status": "UNPAID",
        "revision_count": 0,
        "fee_tier_applied": None,
        "fee_waived": False,
        "final_composite_score": None,
        "final_rank": None,
        "disqualified_reason": None,
    })
    store.entries[rec["id"]] = rec
    return success_object(services.serialize_entry(rec), 201)


@bp.get("/awards/categories/<cid>/entries")
def list_category_entries(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor"])
    cat = get_or_404(store.categories, cid, "Category")
    records = services.entries_of_category(cat["id"])
    status = request.args.get("status")
    entrant_id = request.args.get("entrant_id")
    if status:
        records = [e for e in records if e["status"] == status]
    if entrant_id:
        records = [e for e in records if e["entrant_id"] == entrant_id]
    return list_response(records, services.serialize_entry)


@bp.get("/awards/entries/<eid>")
def get_entry(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant", "Judge", "Anonymous"])
    e = get_or_404(store.entries, eid, "Entry")
    if role == "Entrant" and e["entrant_id"] != uid:
        forbid("Entrant may only read their own entries")
    null_results = False
    if role == "Anonymous":
        season = services.season_of_entry(e)
        null_results = _embargo_protected(season)
    return success_object(services.serialize_entry(e, null_results=null_results), 200)


# ---------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------
@bp.post("/awards/entries/<eid>/materials")
def attach_material(eid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    body = body_json()
    material_type = req_enum(body, "material_type", MATERIAL_TYPES)
    uri = req_str(body, "uri")
    file_size = req_int(body, "file_size_bytes")
    checksum = req_str(body, "checksum_sha256")
    if not CHECKSUM_RE.match(checksum):
        raise_err(ERR_INVALID_REQUEST,
                  "checksum_sha256 must be 64 hex characters")
    if file_size < 0:
        raise_err(ERR_INVALID_REQUEST, "file_size_bytes must be >= 0")
    _own_entry_or_forbid(e, uid)
    if e["status"] in services.TERMINAL["entry"]:
        raise_err(ERR_INVALID_STATE,
                  "cannot attach materials to a terminal entry")
    if file_size > services.MAX_MATERIAL_BYTES:
        raise_err(ERR_CONSTRAINT_VIOLATION,
                  "file_size_bytes exceeds MAX_MATERIAL_BYTES (104857600)")
    rec = new_child_record()
    rec.update({
        "entry_id": e["id"],
        "material_type": material_type,
        "uri": uri,
        "file_size_bytes": file_size,
        "checksum_sha256": checksum,
        "status": "PENDING",
    })
    store.materials[rec["id"]] = rec
    return success_object(services.serialize_material(rec), 201)


@bp.get("/awards/entries/<eid>/materials")
def list_materials(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    if role == "Entrant":
        _own_entry_or_forbid(e, uid)
    records = [m for m in store.materials.values() if m["entry_id"] == e["id"]]
    status = request.args.get("status")
    if status:
        records = [m for m in records if m["status"] == status]
    return list_response(records, services.serialize_material)


@bp.post("/awards/materials/<mid>/accept")
def accept_material(mid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    m = get_or_404(store.materials, mid, "EntryMaterial")
    if m["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "material is not PENDING")
    m["status"] = "ACCEPTED"
    return success_object(services.serialize_material(m), 200)


@bp.post("/awards/materials/<mid>/reject")
def reject_material(mid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    m = get_or_404(store.materials, mid, "EntryMaterial")
    if m["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "material is not PENDING")
    m["status"] = "REJECTED"
    return success_object(services.serialize_material(m), 200)


# ---------------------------------------------------------------------------
# submission / fee waiver / eligibility rulings / recheck / withdrawal
# ---------------------------------------------------------------------------
@bp.post("/awards/entries/<eid>/submit")
def submit_entry(eid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    _own_entry_or_forbid(e, uid)
    services.guard_transition("entry", e, {"DRAFT"})
    cat = store.categories.get(e["category_id"])
    season = services.season_of_entry(e)
    if cat is None or cat["status"] != "PUBLISHED" or season is None \
            or season["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE,
                  "submit requires a PUBLISHED category and an OPEN season")
    now = clock.now()
    late_deadline = season["submission_closes_at"] + timedelta(hours=services.LATE_WINDOW_HOURS)
    if now >= late_deadline:
        raise_err(ERR_OUTSIDE_WINDOW,
                  "submission window (including the 48h late window) has closed")
    if not (season["eligibility_window_start"] <= e["work_completed_at"]
            < season["eligibility_window_end"]):
        raise_err(ERR_ELIGIBILITY_WINDOW,
                  "work_completed_at is outside the season eligibility window")
    accepted = sum(1 for m in store.materials.values()
                   if m["entry_id"] == e["id"] and m["status"] == "ACCEPTED")
    if accepted < cat["min_materials"]:
        raise_err(ERR_CONSTRAINT_VIOLATION,
                  "entry holds %d ACCEPTED materials; category requires %d"
                  % (accepted, cat["min_materials"]))
    held = sum(1 for o in services.entries_of_category(cat["id"])
               if o["entrant_id"] == e["entrant_id"] and o["id"] != e["id"]
               and o["status"] != "WITHDRAWN")
    if held >= cat["max_entries_per_entrant"]:
        raise_err(ERR_CONSTRAINT_VIOLATION,
                  "entrant already holds %d non-WITHDRAWN entries in this category"
                  % held)
    entrant = store.entrants.get(e["entrant_id"])
    if entrant is not None and entrant["standing"] == "BARRED":
        raise_err(ERR_FISCAL_BLOCK, "BARRED entrants may not submit entries")
    # fee assessment
    if e["fee_waived"]:
        # waived variant: no invoice; pass straight through to UNDER_REVIEW
        e["status"] = "UNDER_REVIEW"
        e["payment_status"] = "WAIVED"
    else:
        invoice = services.create_invoice(e, cat, season)
        e["status"] = "SUBMITTED"
        e["payment_status"] = "INVOICED"
    bump(e)
    services.recompute_active_entries_count(season)
    audit.append(season["id"], role, uid, "ENTRY_SUBMIT", "Entry", e["id"],
                 {"before": {"status": "DRAFT"},
                  "after": {"status": e["status"],
                            "payment_status": e["payment_status"]}})
    return success_object(services.serialize_entry(e), 200)


@bp.post("/awards/entries/<eid>/waive-fee")
def waive_fee(eid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    e = get_or_404(store.entries, eid, "Entry")
    services.guard_transition("entry", e, {"DRAFT"})
    e["fee_waived"] = True
    bump(e)
    return success_object(services.serialize_entry(e), 200)


@bp.post("/awards/entries/<eid>/mark-eligible")
def mark_eligible(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    e = get_or_404(store.entries, eid, "Entry")
    services.guard_transition("entry", e, {"UNDER_REVIEW"})
    season = services.season_of_entry(e)
    if season is None or season["status"] not in ("OPEN", "SUBMISSION_CLOSED"):
        raise_err(ERR_INVALID_STATE,
                  "eligibility rulings require season OPEN or SUBMISSION_CLOSED")
    e["status"] = "ELIGIBLE"
    bump(e)
    audit.append(season["id"], role, uid, "ENTRY_MARK_ELIGIBLE", "Entry", e["id"],
                 {"before": {"status": "UNDER_REVIEW"}, "after": {"status": "ELIGIBLE"}})
    return success_object(services.serialize_entry(e), 200)


@bp.post("/awards/entries/<eid>/mark-ineligible")
def mark_ineligible(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    e = get_or_404(store.entries, eid, "Entry")
    services.guard_transition("entry", e, {"UNDER_REVIEW"})
    season = services.season_of_entry(e)
    if season is None or season["status"] not in ("OPEN", "SUBMISSION_CLOSED"):
        raise_err(ERR_INVALID_STATE,
                  "eligibility rulings require season OPEN or SUBMISSION_CLOSED")
    # Deliberately NOT a refund event: the settled invoice stays PAID and the
    # active-entries count is unchanged while the revision loop is open.
    e["status"] = "INELIGIBLE"
    bump(e)
    audit.append(season["id"], role, uid, "ENTRY_MARK_INELIGIBLE", "Entry", e["id"],
                 {"before": {"status": "UNDER_REVIEW"}, "after": {"status": "INELIGIBLE"}})
    return success_object(services.serialize_entry(e), 200)


@bp.post("/awards/entries/<eid>/request-recheck")
def request_recheck(eid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    _own_entry_or_forbid(e, uid)
    services.guard_transition("entry", e, {"INELIGIBLE"})
    season = services.season_of_entry(e)
    if e["revision_count"] >= services.MAX_REVISIONS:
        raise_err(ERR_INVALID_STATE,
                  "revision cap reached (MAX_REVISIONS = %d)" % services.MAX_REVISIONS)
    if season is None or season["status"] not in ("OPEN", "SUBMISSION_CLOSED"):
        raise_err(ERR_INVALID_STATE,
                  "recheck requires season OPEN or SUBMISSION_CLOSED")
    e["status"] = "UNDER_REVIEW"
    e["revision_count"] += 1
    e["payment_status"] = "PAID"
    bump(e)
    return success_object(services.serialize_entry(e), 200)


@bp.post("/awards/entries/<eid>/withdraw")
def withdraw_entry(eid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    _own_entry_or_forbid(e, uid)
    services.guard_transition("entry", e, {"DRAFT", "SUBMITTED", "UNDER_REVIEW"})
    season = services.season_of_entry(e)
    for inv in services.invoices_of_entry(e["id"]):
        if inv["status"] == "ISSUED":
            inv["status"] = "VOIDED"
            bump(inv)
            e["payment_status"] = "UNPAID"
        elif inv["status"] == "PAID":
            services.run_withdrawal_refund(inv, season)
            e["payment_status"] = "REFUNDED"
    e["status"] = "WITHDRAWN"
    bump(e)
    if season is not None:
        services.recompute_active_entries_count(season)
    return success_object(services.serialize_entry(e), 200)


# ---------------------------------------------------------------------------
# entry-scoped collections: invoices, scores, finalist record, announcements,
# appeals, fulfillment orders
# ---------------------------------------------------------------------------
@bp.get("/awards/entries/<eid>/invoices")
def list_entry_invoices(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    if role == "Entrant":
        _own_entry_or_forbid(e, uid)
    records = services.invoices_of_entry(e["id"])
    status = request.args.get("status")
    if status:
        records = [i for i in records if i["status"] == status]
    return list_response(records, services.serialize_invoice)


@bp.get("/awards/entries/<eid>/scores")
def list_entry_scores(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    if role == "Entrant":
        _own_entry_or_forbid(e, uid)
    records = [s for s in store.scores.values() if s["entry_id"] == e["id"]]
    round_id = request.args.get("scoring_round_id")
    if round_id:
        records = [s for s in records if s["scoring_round_id"] == round_id]
    return list_response(records, services.serialize_score)


@bp.get("/awards/entries/<eid>/finalist-record")
def get_entry_finalist_record(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    if role == "Entrant":
        _own_entry_or_forbid(e, uid)
    records = [f for f in store.finalists.values() if f["entry_id"] == e["id"]]
    return list_response(records, services.serialize_finalist)


@bp.get("/awards/entries/<eid>/announcements")
def list_entry_announcements(eid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor"])
    e = get_or_404(store.entries, eid, "Entry")
    records = [a for a in store.announcements.values()
               if a.get("winner_entry_id") == e["id"]]
    return list_response(records, services.serialize_announcement)


@bp.get("/awards/entries/<eid>/fulfillment-orders")
def list_entry_fulfillment(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Entrant", "FulfillmentVendor"])
    e = get_or_404(store.entries, eid, "Entry")
    if role == "Entrant":
        _own_entry_or_forbid(e, uid)
    records = [f for f in store.fulfillment_orders.values() if f["entry_id"] == e["id"]]
    status = request.args.get("status")
    if status:
        records = [f for f in records if f["status"] == status]
    return list_response(records, services.serialize_fulfillment)


# ---------------------------------------------------------------------------
# appeals on an entry
# ---------------------------------------------------------------------------
APPEAL_GROUNDS = ["SCORING_ERROR", "CONFLICT_UNDECLARED",
                  "ELIGIBILITY_MISREAD", "PROCEDURAL_VIOLATION"]


@bp.post("/awards/entries/<eid>/appeals")
def file_appeal(eid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    body = body_json()
    filed_by = req_str(body, "filed_by_entrant_id")
    grounds = req_enum(body, "grounds", APPEAL_GROUNDS)
    narrative = req_str(body, "narrative")
    filer = ref_or_404(store.entrants, filed_by, "Entrant")
    if filer["id"] != uid:
        forbid("filed_by_entrant_id must match the acting entrant")
    has_standing = any(o["entrant_id"] == filer["id"]
                       and o["category_id"] == e["category_id"]
                       and o["status"] != "WITHDRAWN"
                       for o in store.entries.values())
    if not has_standing:
        forbid("filing entrant lacks competitor standing in this category")
    season = services.season_of_entry(e)
    open_appeals = sum(1 for a in store.appeals.values()
                       if a["entry_id"] == e["id"]
                       and a["status"] in ("FILED", "UNDER_REVIEW"))
    if season is not None and open_appeals >= season["max_appeals_per_entry"]:
        raise_err(ERR_APPEAL_CAP_EXCEEDED,
                  "entry already has %d open appeals" % open_appeals)
    rec = new_record()
    rec.update({
        "entry_id": e["id"],
        "filed_by_entrant_id": filer["id"],
        "grounds": grounds,
        "narrative": narrative,
        "status": "FILED",
        "decided_by": None,
        "decided_at": None,
        "remedy": None,
    })
    store.appeals[rec["id"]] = rec
    return success_object(services.serialize_appeal(rec), 201)


@bp.get("/awards/entries/<eid>/appeals")
def list_entry_appeals(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant"])
    e = get_or_404(store.entries, eid, "Entry")
    if role == "Entrant":
        _own_entry_or_forbid(e, uid)
    records = [a for a in store.appeals.values() if a["entry_id"] == e["id"]]
    status = request.args.get("status")
    if status:
        records = [a for a in records if a["status"] == status]
    return list_response(records, services.serialize_appeal)
