"""EntryApplication, Float, and SafetyInspection endpoints."""
from flask import Blueprint, request

import db
from auth import guarded, require_owner
from db import STORE, make_record, touch
from errors import api_err
from logic import (
    ENTRY_CATEGORIES,
    FUEL_TYPES,
    VEHICLE_CLASSES,
    certify_compensation,
    compute_entry_fee,
    ensure_not_frozen,
    entry_or_404,
    float_or_404,
    inspection_or_404,
    parade_or_404,
    pull_live_assignments_of_entry,
    ser_entry,
    ser_float,
    ser_inspection,
    suspend_entry,
)
from util import body, opt_int, opt_str, paged, req_enum, req_int, req_num, req_str, req_dt, respond_object

bp = Blueprint("entries", __name__)

CA = ("CommitteeAdmin",)
ENTRANT = ("Entrant",)
SI = ("SafetyInspector",)
ENTRY_READERS = ("CommitteeAdmin", "AgencyReviewer", "Judge", "Entrant")
FLOAT_READERS = ("CommitteeAdmin", "SafetyInspector", "Entrant")
INSPECTION_READERS = ("CommitteeAdmin", "SafetyInspector")


def add(rule, methods, view):
    bp.add_url_rule(rule, view_func=view, methods=methods, strict_slashes=False)


# --- EntryApplication --------------------------------------------------------

def create_entry(uid, role, id):
    parade = parade_or_404(id)
    data = body()
    org_name = req_str(data, "org_name")
    requested_category = req_enum(data, "requested_category", ENTRY_CATEGORIES)
    estimated_participants = req_int(data, "estimated_participants", minimum=1)
    # Temporal gate: creation accepted while the logical clock reads at or
    # before the parade's entry_deadline.
    if db.now() > parade["entry_deadline"]:
        raise api_err("ERR_ENTRY_DEADLINE_PASSED", "Entry creation is past the parade entry_deadline")
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "applicant_user_id": uid,
            "org_name": org_name,
            "requested_category": requested_category,
            "assigned_category": None,
            "estimated_participants": estimated_participants,
            "status": "SUBMITTED",
            "revision_count": 0,
            "fee_paid": False,
        }
    )
    rec["fee_cents"] = compute_entry_fee(rec, parade, rec["created_at"])
    STORE.entries[rec["id"]] = rec
    return respond_object(ser_entry(rec), 201)


def list_entries(uid, role, id):
    parade_or_404(id)
    items = [e for e in STORE.entries.values() if e["parade_id"] == id]
    status = request.args.get("status")
    assigned_category = request.args.get("assigned_category")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if assigned_category is not None:
        items = [e for e in items if e["assigned_category"] == assigned_category]
    return paged(items, ser_entry)


def get_entry(uid, role, id):
    return respond_object(ser_entry(entry_or_404(id)))


def start_review(uid, role, id):
    entry = entry_or_404(id)
    if entry["status"] != "SUBMITTED":
        raise api_err("ERR_INVALID_STATE", "Entry must be in SUBMITTED to start review")
    ensure_not_frozen(parade_or_404(entry["parade_id"]))
    entry["status"] = "UNDER_REVIEW"
    touch(entry)
    return respond_object(ser_entry(entry))


def approve_entry(uid, role, id):
    entry = entry_or_404(id)
    data = body()
    assigned_category = req_enum(data, "assigned_category", ENTRY_CATEGORIES)
    if entry["status"] != "UNDER_REVIEW":
        raise api_err("ERR_INVALID_STATE", "Entry must be in UNDER_REVIEW to approve")
    parade = parade_or_404(entry["parade_id"])
    ensure_not_frozen(parade)
    entry["assigned_category"] = assigned_category
    entry["fee_cents"] = compute_entry_fee(entry, parade, entry["created_at"])
    entry["status"] = "APPROVED"
    touch(entry)
    return respond_object(ser_entry(entry))


def reject_entry(uid, role, id):
    entry = entry_or_404(id)
    data = body()
    reason = opt_str(data, "reason")
    if entry["status"] != "UNDER_REVIEW":
        raise api_err("ERR_INVALID_STATE", "Entry must be in UNDER_REVIEW to reject")
    ensure_not_frozen(parade_or_404(entry["parade_id"]))
    entry["_reason"] = reason
    entry["status"] = "REJECTED"
    touch(entry)
    return respond_object(ser_entry(entry))


def request_revision(uid, role, id):
    entry = entry_or_404(id)
    data = body()
    notes = req_str(data, "revision_notes")
    if entry["status"] != "UNDER_REVIEW":
        raise api_err("ERR_INVALID_STATE", "Entry must be in UNDER_REVIEW to request revision")
    ensure_not_frozen(parade_or_404(entry["parade_id"]))
    entry["_revision_notes"] = notes
    entry["revision_count"] += 1
    entry["status"] = "REVISION_REQUESTED"
    touch(entry)
    return respond_object(ser_entry(entry))


def resubmit_entry(uid, role, id):
    entry = entry_or_404(id)
    require_owner(uid, entry["applicant_user_id"])
    data = body()
    org_name = opt_str(data, "org_name")
    estimated_participants = opt_int(data, "estimated_participants", minimum=1)
    if entry["status"] != "REVISION_REQUESTED":
        raise api_err("ERR_INVALID_STATE", "Entry must be in REVISION_REQUESTED to resubmit")
    parade = parade_or_404(entry["parade_id"])
    ensure_not_frozen(parade)
    if org_name is not None:
        entry["org_name"] = org_name
    if estimated_participants is not None:
        entry["estimated_participants"] = estimated_participants
    entry["fee_cents"] = compute_entry_fee(entry, parade, db.now())
    entry["status"] = "SUBMITTED"
    touch(entry)
    return respond_object(ser_entry(entry))


def withdraw_entry(uid, role, id):
    entry = entry_or_404(id)
    require_owner(uid, entry["applicant_user_id"])
    if entry["status"] not in ("SUBMITTED", "APPROVED"):
        raise api_err("ERR_INVALID_STATE", "Entry must be in SUBMITTED or APPROVED to withdraw")
    if entry["status"] == "APPROVED":
        pull_live_assignments_of_entry(entry)
    entry["status"] = "WITHDRAWN"
    touch(entry)
    return respond_object(ser_entry(entry))


def pay_fee(uid, role, id):
    entry = entry_or_404(id)
    require_owner(uid, entry["applicant_user_id"])
    entry["fee_paid"] = True
    touch(entry)
    return respond_object(ser_entry(entry))


add("/parades/<id>/entries", ["POST"], guarded(ENTRANT)(create_entry))
add("/parades/<id>/entries", ["GET"], guarded(ENTRY_READERS)(list_entries))
add("/entries/<id>", ["GET"], guarded(ENTRY_READERS)(get_entry))
add("/entries/<id>/start-review", ["POST"], guarded(CA)(start_review))
add("/entries/<id>/approve", ["POST"], guarded(CA)(approve_entry))
add("/entries/<id>/reject", ["POST"], guarded(CA)(reject_entry))
add("/entries/<id>/request-revision", ["POST"], guarded(CA)(request_revision))
add("/entries/<id>/resubmit", ["POST"], guarded(ENTRANT)(resubmit_entry))
add("/entries/<id>/withdraw", ["POST"], guarded(ENTRANT)(withdraw_entry))
add("/entries/<id>/pay-fee", ["POST"], guarded(ENTRANT)(pay_fee))


# --- Float -------------------------------------------------------------------

def create_float(uid, role, id):
    entry = entry_or_404(id)
    require_owner(uid, entry["applicant_user_id"])
    data = body()
    length_m = req_num(data, "length_m", minimum=0, exclusive_min=True)
    width_m = req_num(data, "width_m", minimum=0, exclusive_min=True)
    height_m = req_num(data, "height_m", minimum=0, exclusive_min=True)
    weight_kg = req_num(data, "weight_kg", minimum=0, exclusive_min=True)
    vehicle_class = req_enum(data, "vehicle_class", VEHICLE_CLASSES)
    fuel_type = req_enum(data, "fuel_type", FUEL_TYPES)
    if entry["status"] != "APPROVED" or entry["assigned_category"] not in ("FLOAT", "VEHICLE"):
        raise api_err(
            "ERR_CATEGORY_WITHOUT_FLOAT",
            "Float registration requires the entry APPROVED with assigned_category FLOAT or VEHICLE",
        )
    rec = make_record()
    rec.update(
        {
            "entry_id": id,
            "length_m": length_m,
            "width_m": width_m,
            "height_m": height_m,
            "weight_kg": weight_kg,
            "vehicle_class": vehicle_class,
            "fuel_type": fuel_type,
            "compliance_status": "PENDING_INSPECTION",
        }
    )
    STORE.floats[rec["id"]] = rec
    return respond_object(ser_float(rec), 201)


def list_floats(uid, role, id):
    entry_or_404(id)
    items = [f for f in STORE.floats.values() if f["entry_id"] == id]
    return paged(items, ser_float)


def get_float(uid, role, id):
    return respond_object(ser_float(float_or_404(id)))


add("/entries/<id>/floats", ["POST"], guarded(ENTRANT)(create_float))
add("/entries/<id>/floats", ["GET"], guarded(FLOAT_READERS)(list_floats))
add("/floats/<id>", ["GET"], guarded(FLOAT_READERS)(get_float))


# --- SafetyInspection ----------------------------------------------------------

def schedule_inspection(uid, role, id):
    flt = float_or_404(id)
    data = body()
    scheduled_at = req_dt(data, "scheduled_at")
    # State: at most one SCHEDULED inspection per float at a time.
    if any(i["float_id"] == id and i["status"] == "SCHEDULED" for i in STORE.inspections.values()):
        raise api_err("ERR_INVALID_STATE", "The float already has a SCHEDULED inspection")
    # Safety: segregation of duties on re-inspection.
    failed = [i for i in STORE.inspections.values() if i["float_id"] == id and i["status"] == "FAILED"]
    if failed:
        latest_failed = max(failed, key=lambda i: (i["created_at"], i["_seq"]))
        if latest_failed["inspector_user_id"] == uid:
            raise api_err(
                "ERR_REINSPECTION_SOD",
                "Re-inspection must use a different inspector than the latest FAILED inspection",
            )
    rec = make_record()
    rec.update(
        {
            "float_id": id,
            "inspector_user_id": uid,
            "scheduled_at": scheduled_at,
            "status": "SCHEDULED",
            "checklist_score": None,
            "decided_at": None,
        }
    )
    STORE.inspections[rec["id"]] = rec
    if flt["compliance_status"] == "FAILED":
        flt["compliance_status"] = "PENDING_INSPECTION"
        touch(flt)
    return respond_object(ser_inspection(rec), 201)


def list_inspections(uid, role, id):
    float_or_404(id)
    items = [i for i in STORE.inspections.values() if i["float_id"] == id]
    return paged(items, ser_inspection)


def get_inspection(uid, role, id):
    return respond_object(ser_inspection(inspection_or_404(id)))


def _decide_inspection(uid, id, passing):
    inspection = inspection_or_404(id)
    data = body()
    score = req_int(data, "checklist_score", minimum=0, maximum=100)
    if passing and score < 70:
        raise api_err("ERR_VALIDATION", "Passing requires checklist_score >= 70")
    if not passing and score >= 70:
        raise api_err("ERR_VALIDATION", "Failing requires checklist_score < 70")
    if inspection["status"] != "SCHEDULED":
        raise api_err("ERR_INVALID_STATE", "Inspection must be in SCHEDULED")
    inspection["checklist_score"] = score
    inspection["decided_at"] = db.now()
    flt = float_or_404(inspection["float_id"])
    entry = entry_or_404(flt["entry_id"])
    if passing:
        inspection["status"] = "PASSED"
        touch(inspection)
        if flt["compliance_status"] == "PENDING_INSPECTION":
            flt["compliance_status"] = "CERTIFIED"
            touch(flt)
        certify_compensation(entry)
    else:
        inspection["status"] = "FAILED"
        touch(inspection)
        if flt["compliance_status"] in ("PENDING_INSPECTION", "CERTIFIED"):
            flt["compliance_status"] = "FAILED"
            touch(flt)
        suspend_entry(entry)
    return respond_object(ser_inspection(inspection))


def pass_inspection(uid, role, id):
    return _decide_inspection(uid, id, True)


def fail_inspection(uid, role, id):
    return _decide_inspection(uid, id, False)


def cancel_inspection(uid, role, id):
    inspection = inspection_or_404(id)
    if inspection["status"] != "SCHEDULED":
        raise api_err("ERR_INVALID_STATE", "Inspection must be in SCHEDULED to cancel")
    inspection["status"] = "CANCELLED"
    touch(inspection)
    return respond_object(ser_inspection(inspection))


add("/floats/<id>/inspections", ["POST"], guarded(SI)(schedule_inspection))
add("/floats/<id>/inspections", ["GET"], guarded(FLOAT_READERS)(list_inspections))
add("/inspections/<id>", ["GET"], guarded(INSPECTION_READERS)(get_inspection))
add("/inspections/<id>/pass", ["POST"], guarded(SI)(pass_inspection))
add("/inspections/<id>/fail", ["POST"], guarded(SI)(fail_inspection))
add("/inspections/<id>/cancel", ["POST"], guarded(SI)(cancel_inspection))
