"""Routes: residents, assessments, admissions."""

from flask import Blueprint, g, request

from db import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STALE_VERSION, ERR_SELF_APPROVAL, ERR_ASSESSMENT_SUPERSEDED,
    ERR_BED_NOT_CERTIFIED, ERR_CAPACITY_EXCEEDED, ERR_BLOCKED_BY_INCIDENT,
    ERR_INSUFFICIENT_NOTICE,
)
from util import (
    ok_object, ok_list, paginate, require_roles, get_or_404, body,
    need, need_str, need_int, need_num, need_enum, need_date,
    stamp_new, touch, pub, sort_created, fmt_ts, now_ts,
)
from logic import (
    recompute_home_counters, release_bed_hold, compute_discharge_refund,
)

bp = Blueprint("routes_b", __name__)

ALL = ("Provider", "Nurse", "CaregiverRole")
PROVIDER = ("Provider",)
NURSE = ("Nurse",)
PROVIDER_NURSE = ("Provider", "Nurse")

PAYER_TYPES = ("PRIVATE_PAY", "MEDICAID")
DISCHARGE_REASONS = ("VOLUNTARY", "HOSPITALIZATION", "LEVEL_OF_CARE_EXCEEDED",
                     "NONPAYMENT", "DECEASED")
NOTICE_EXEMPT = ("HOSPITALIZATION", "DECEASED")


# ---------------------------------------------------------------------------
# Residents
# ---------------------------------------------------------------------------

@bp.post("/api/homes/<id>/residents")
@require_roles(*PROVIDER_NURSE)
def create_resident(id):
    get_or_404(db.homes, id, "home")
    b = body()
    full_name = need_str(b, "full_name")
    dob = need_date(b, "date_of_birth")
    payer_type = need_enum(b, "payer_type", PAYER_TYPES)
    rec = stamp_new({
        "home_id": id,
        "full_name": full_name,
        "date_of_birth": dob.isoformat(),
        "payer_type": payer_type,
        "status": "PROSPECT",
        "admitted_at": None,
        "discharged_at": None,
        "_admitted_dt": None,
        "_discharged_dt": None,
    })
    db.residents[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/homes/<id>/residents")
@require_roles(*ALL)
def list_residents(id):
    get_or_404(db.homes, id, "home")
    items = sort_created([r for r in db.residents.values() if r["home_id"] == id])
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    payer = request.args.get("payer_type")
    if payer is not None:
        items = [r for r in items if r["payer_type"] == payer]
    page, meta = paginate(items)
    return ok_list([pub(r) for r in page], meta)


@bp.get("/api/residents/<id>")
@require_roles(*ALL)
def get_resident(id):
    resident = get_or_404(db.residents, id, "resident")
    return ok_object(pub(resident))


@bp.post("/api/residents/<id>/withdraw")
@require_roles(*PROVIDER)
def withdraw_resident(id):
    resident = get_or_404(db.residents, id, "resident")
    if resident["status"] != "APPLICANT":
        raise_err(ERR_INVALID_STATE, "resident is not an APPLICANT")
    live = any(a["resident_id"] == id and a["status"] in ("PENDING", "APPROVED")
               for a in db.admissions.values())
    if live:
        raise_err(ERR_INVALID_STATE, "resident has a live admission")
    resident["status"] = "PROSPECT"
    touch(resident)
    return ok_object(pub(resident))


@bp.post("/api/residents/<id>/discharge")
@require_roles(*PROVIDER)
def discharge_resident(id):
    resident = get_or_404(db.residents, id, "resident")
    b = body()
    # 5. state legality
    if resident["status"] != "ADMITTED":
        raise_err(ERR_INVALID_STATE, "resident is not ADMITTED")
    # 7. critical-incident block
    blocked = any(i["resident_id"] == id and i["severity"] == "CRITICAL"
                  and i["status"] in ("REPORTED", "UNDER_REVIEW")
                  for i in db.incidents.values())
    if blocked:
        raise_err(ERR_BLOCKED_BY_INCIDENT,
                  "a CRITICAL incident is under investigation for this resident")
    # 13. notice rule (computable only when fields are usable)
    reason = b.get("reason")
    notice_days = b.get("notice_days")
    if (isinstance(reason, str) and reason not in NOTICE_EXEMPT
            and isinstance(notice_days, int) and not isinstance(notice_days, bool)
            and notice_days < 30):
        raise_err(ERR_INSUFFICIENT_NOTICE,
                  "notice_days must be >= 30 unless reason is HOSPITALIZATION or DECEASED")
    # 22. structural validity
    reason = need_enum(b, "reason", DISCHARGE_REASONS)
    notice_days = need_int(b, "notice_days")
    if notice_days < 0:
        raise_err(ERR_INVALID_REQUEST, "notice_days must be >= 0")

    home = get_or_404(db.homes, resident["home_id"], "home")
    now = db.now()
    discharged_at = fmt_ts(now)
    refund = compute_discharge_refund(home, resident, now)

    resident["status"] = "DISCHARGED"
    resident["discharged_at"] = discharged_at
    resident["_discharged_dt"] = now
    touch(resident)

    # Occupied bed -> AVAILABLE
    completed = [a for a in db.admissions.values()
                 if a["resident_id"] == id and a["status"] == "COMPLETED"]
    completed.sort(key=lambda a: a["_seq"])
    if completed:
        bed = db.beds.get(completed[-1]["bed_id"])
        if bed is not None and bed["status"] == "OCCUPIED":
            bed["status"] = "AVAILABLE"
            touch(bed)

    # All ACTIVE medication orders -> DISCONTINUED
    for order in db.med_orders.values():
        if order["resident_id"] == id and order["status"] == "ACTIVE":
            order["status"] = "DISCONTINUED"
            touch(order)

    recompute_home_counters(home)

    rec = stamp_new({
        "resident_id": id,
        "reason": reason,
        "notice_days": notice_days,
        "discharged_at": discharged_at,
        "refund_amount_cents": refund,
    }, common=False)
    db.discharge_records[rec["id"]] = rec
    return ok_object(pub(rec))


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------

@bp.post("/api/residents/<id>/assessments")
@require_roles(*NURSE)
def create_assessment(id):
    get_or_404(db.residents, id, "resident")
    b = body()
    nursing = need_num(b, "nursing_hours_per_week")
    if nursing < 0 or nursing > 40:
        raise_err(ERR_INVALID_REQUEST, "nursing_hours_per_week must be in [0, 40]")
    adl = need_int(b, "adl_dependency_score")
    if adl < 0 or adl > 6:
        raise_err(ERR_INVALID_REQUEST, "adl_dependency_score must be in [0, 6]")
    care_plan = need(b, "care_plan")
    if not isinstance(care_plan, dict):
        raise_err(ERR_INVALID_REQUEST, "care_plan must be an object")
    now = db.now()
    rec = stamp_new({
        "resident_id": id,
        "assessed_at": fmt_ts(now),
        "_assessed_dt": now,
        "nursing_hours_per_week": nursing,
        "adl_dependency_score": adl,
        "care_plan": care_plan,
        "status": "DRAFT",
    })
    db.assessments[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/residents/<id>/assessments")
@require_roles(*PROVIDER_NURSE)
def list_assessments(id):
    get_or_404(db.residents, id, "resident")
    items = sort_created([a for a in db.assessments.values() if a["resident_id"] == id])
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return ok_list([pub(a) for a in page], meta)


@bp.get("/api/assessments/<id>")
@require_roles(*PROVIDER_NURSE)
def get_assessment(id):
    rec = get_or_404(db.assessments, id, "assessment")
    return ok_object(pub(rec))


@bp.post("/api/assessments/<id>/finalize")
@require_roles(*NURSE)
def finalize_assessment(id):
    rec = get_or_404(db.assessments, id, "assessment")
    if rec["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "assessment is not DRAFT")
    resident = db.residents.get(rec["resident_id"])
    if resident is None or resident["status"] not in ("PROSPECT", "APPLICANT", "ADMITTED"):
        raise_err(ERR_INVALID_STATE, "resident state does not permit finalization")
    # Supersede any previously FINALIZED assessment for the same resident.
    for other in db.assessments.values():
        if (other["resident_id"] == rec["resident_id"] and other["id"] != id
                and other["status"] == "FINALIZED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    rec["status"] = "FINALIZED"
    touch(rec)
    if resident["status"] == "PROSPECT":
        resident["status"] = "APPLICANT"
        touch(resident)
    return ok_object(pub(rec))


# ---------------------------------------------------------------------------
# Admissions
# ---------------------------------------------------------------------------

@bp.post("/api/admissions")
@require_roles(*PROVIDER)
def create_admission():
    b = body()
    # 3. existence, body identifiers left-to-right
    resident = get_or_404(db.residents, b.get("resident_id"), "resident") \
        if "resident_id" in b else None
    bed = get_or_404(db.beds, b.get("bed_id"), "bed") if "bed_id" in b else None
    assessment = get_or_404(db.assessments, b.get("assessment_id"), "assessment") \
        if "assessment_id" in b else None
    if resident is not None and assessment is not None \
            and assessment["resident_id"] != resident["id"]:
        raise_err(ERR_NOT_FOUND, "assessment does not belong to the resident")
    # 4. OCC on the bed
    if bed is not None and "expected_bed_version" in b and b["expected_bed_version"] is not None:
        if b["expected_bed_version"] != bed["version"]:
            raise_err(ERR_STALE_VERSION, "expected_bed_version does not match bed version")
    # 5. state legality
    if bed is not None and bed["status"] != "AVAILABLE":
        raise_err(ERR_INVALID_STATE, "bed is not AVAILABLE")
    if bed is not None:
        bed_home = db.homes.get(bed["home_id"])
        if bed_home is None or bed_home["status"] not in ("PROVISIONAL", "LICENSED"):
            raise_err(ERR_INVALID_STATE, "bed's home does not permit admissions")
    if assessment is not None and assessment["status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE, "pinned assessment is not FINALIZED")
    # 12. Medicaid bed certification
    if resident is not None and bed is not None \
            and resident["payer_type"] == "MEDICAID" and not bed["medicaid_certified"]:
        raise_err(ERR_BED_NOT_CERTIFIED,
                  "MEDICAID admissions require a medicaid_certified bed")
    # 22. structural validity
    resident_id = need_str(b, "resident_id")
    bed_id = need_str(b, "bed_id")
    assessment_id = need_str(b, "assessment_id")
    expected_date = need_date(b, "expected_admission_date")
    need(b, "expected_bed_version")

    bed["status"] = "HELD"
    touch(bed)
    rec = stamp_new({
        "resident_id": resident_id,
        "bed_id": bed_id,
        "assessment_id": assessment_id,
        "expected_admission_date": expected_date.isoformat(),
        "status": "PENDING",
        "decided_by": None,
        "decided_at": None,
        "_created_by": g.user_id,
    })
    db.admissions[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/admissions")
@require_roles(*PROVIDER_NURSE)
def list_admissions():
    items = sort_created(list(db.admissions.values()))
    for f in ("resident_id", "bed_id", "assessment_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    page, meta = paginate(items)
    return ok_list([pub(a) for a in page], meta)


@bp.get("/api/admissions/<id>")
@require_roles(*PROVIDER_NURSE)
def get_admission(id):
    rec = get_or_404(db.admissions, id, "admission")
    return ok_object(pub(rec))


@bp.post("/api/admissions/<id>/approve")
@require_roles(*PROVIDER)
def approve_admission(id):
    adm = get_or_404(db.admissions, id, "admission")
    if adm["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "admission is not PENDING")
    if g.user_id == adm["_created_by"]:
        raise_err(ERR_SELF_APPROVAL, "the requester cannot approve their own admission")
    resident = db.residents.get(adm["resident_id"])
    home = db.homes.get(resident["home_id"]) if resident else None
    if home is None or home["status"] != "LICENSED":
        raise_err(ERR_INVALID_STATE, "home is not LICENSED")
    assessment = db.assessments.get(adm["assessment_id"])
    if assessment is None or assessment["status"] != "FINALIZED":
        raise_err(ERR_ASSESSMENT_SUPERSEDED, "pinned assessment is no longer FINALIZED")
    bed = db.beds.get(adm["bed_id"])
    if bed is None or bed["status"] != "HELD":
        raise_err(ERR_INVALID_STATE, "bed is not HELD by this admission")
    adm["status"] = "APPROVED"
    adm["decided_by"] = g.user_id
    adm["decided_at"] = now_ts()
    touch(adm)
    return ok_object(pub(adm))


@bp.post("/api/admissions/<id>/reject")
@require_roles(*PROVIDER)
def reject_admission(id):
    adm = get_or_404(db.admissions, id, "admission")
    if adm["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "admission is not PENDING")
    adm["status"] = "REJECTED"
    adm["decided_by"] = g.user_id
    adm["decided_at"] = now_ts()
    touch(adm)
    release_bed_hold(adm)
    return ok_object(pub(adm))


@bp.post("/api/admissions/<id>/cancel")
@require_roles(*PROVIDER)
def cancel_admission(id):
    adm = get_or_404(db.admissions, id, "admission")
    if adm["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "admission is not APPROVED")
    adm["status"] = "CANCELLED"
    adm["decided_by"] = g.user_id
    adm["decided_at"] = now_ts()
    touch(adm)
    release_bed_hold(adm)
    return ok_object(pub(adm))


@bp.post("/api/admissions/<id>/complete")
@require_roles(*PROVIDER)
def complete_admission(id):
    adm = get_or_404(db.admissions, id, "admission")
    if adm["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "admission is not APPROVED")
    resident = db.residents.get(adm["resident_id"])
    home = db.homes.get(resident["home_id"]) if resident else None
    if home is None or home["status"] != "LICENSED":
        raise_err(ERR_INVALID_STATE, "home is not LICENSED")
    if home["current_census"] >= home["licensed_bed_capacity"]:
        raise_err(ERR_CAPACITY_EXCEEDED, "home is at licensed bed capacity")
    bed = db.beds.get(adm["bed_id"])
    if bed is None or bed["status"] != "HELD":
        raise_err(ERR_INVALID_STATE, "bed is not HELD by this admission")
    now = db.now()
    adm["status"] = "COMPLETED"
    touch(adm)
    resident["status"] = "ADMITTED"
    resident["admitted_at"] = fmt_ts(now)
    resident["_admitted_dt"] = now
    touch(resident)
    bed["status"] = "OCCUPIED"
    touch(bed)
    recompute_home_counters(home)
    return ok_object(pub(adm))
