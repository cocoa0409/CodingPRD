"""Case routes: intake, assignment, sign-out lifecycle, amendments,
cancellation, and nested creation (specimens, stain orders, consultations,
discrepancies)."""
from flask import Blueprint, request

from db import db
from errors import ApiError
from helpers import (
    qparam,
    auth, require_role, payload, ok, paginate, forbid,
    need_str, need_enum, need_dt, occ_int, now,
)
import calc
from calc import new_entity, bump

bp = Blueprint("cases", __name__)


def _not_found(what="Resource"):
    raise ApiError("ERR_NOT_FOUND", 404, "%s does not exist" % what)


def _get_case(cid):
    c = db.cases.get(cid)
    if c is None:
        _not_found("Case")
    return c


# ---------------------------------------------------------------------------
# Case intake / reads
# ---------------------------------------------------------------------------

@bp.post("/pathology/cases")
def create_case():
    _, role = auth()
    require_role(role, "LabAdmin", "Histotech")
    body = payload()
    patient_id = need_str(body, "patient_id")
    subspecialty = need_enum(body, "subspecialty", calc.SUBSPECIALTIES)
    tat_mode = need_enum(body, "tat_mode", calc.TAT_MODES) \
        if "tat_mode" in body else "CALENDAR"
    if patient_id not in db.patients:
        _not_found("Patient")
    c = new_entity()
    c.update({
        "patient_id": patient_id,
        "subspecialty": subspecialty,
        "tat_mode": tat_mode,
        "status": "OPEN",
        "assigned_pathologist_id": None,
        "finalized_at": None,
        "amender_pathologist_id": None,
    })
    db.cases[c["id"]] = c
    return ok(calc.ser_case(c), status=201)


@bp.get("/pathology/cases/<cid>")
def get_case(cid):
    auth()
    c = _get_case(cid)
    return ok(calc.ser_case(c))


@bp.get("/pathology/cases")
def list_cases():
    auth()
    items = list(db.cases.values())
    patient_id = qparam("patient_id")
    if patient_id is not None:
        items = [c for c in items if c["patient_id"] == patient_id]
    ap = qparam("assigned_pathologist_id")
    if ap is not None:
        items = [c for c in items if c["assigned_pathologist_id"] == ap]
    am = qparam("amender_pathologist_id")
    if am is not None:
        items = [c for c in items if c["amender_pathologist_id"] == am]
    status = qparam("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    tb = qparam("tat_breached")
    if tb is not None:
        want = tb.lower() == "true"
        items = [c for c in items if calc.breach_state(c)[0] == want]
    page, meta = paginate(items)
    return ok([calc.ser_case(c) for c in page],
              response_type="array", pagination=meta)

# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

def _assign_to(case, target):
    case["assigned_pathologist_id"] = target["id"]
    target["last_assigned_at"] = now()
    bump(target)
    bump(case)


def _resolve_assignment_target(case, pathologist_id):
    """Explicit target -> ERR_PATHOLOGIST_INELIGIBLE on failure; omitted ->
    deterministic selector with ERR_NO_ELIGIBLE_PATHOLOGIST on empty pool."""
    if pathologist_id is not None:
        p = db.pathologists.get(pathologist_id)
        if not calc.is_eligible(p, case["subspecialty"]):
            raise ApiError("ERR_PATHOLOGIST_INELIGIBLE", 422,
                           "pathologist fails eligibility (inactive, "
                           "subspecialty mismatch, or unavailable)")
        return p
    p = calc.select_pathologist(case["subspecialty"])
    if p is None:
        raise ApiError("ERR_NO_ELIGIBLE_PATHOLOGIST", 422,
                       "no eligible pathologist available")
    return p


@bp.post("/pathology/cases/<cid>/assign")
def assign_case(cid):
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    pathologist_id = body.get("pathologist_id")
    if pathologist_id is not None and not isinstance(pathologist_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "pathologist_id must be a string")
    c = _get_case(cid)
    # existence of the body-referenced pathologist (priority 4) precedes the
    # state gate (priority 12)
    if pathologist_id is not None and pathologist_id not in db.pathologists:
        _not_found("Pathologist")
    if c["status"] not in ("OPEN", "WORKUP"):
        raise ApiError("ERR_CASE_NOT_ASSIGNABLE", 409,
                       "case is not in OPEN or WORKUP")
    target = _resolve_assignment_target(c, pathologist_id)
    _assign_to(c, target)
    return ok(calc.ser_case(c))


@bp.post("/pathology/cases/<cid>/reassign")
def reassign_case(cid):
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    pathologist_id = need_str(body, "pathologist_id")
    expected = occ_int(body, "expected_case_version")
    c = _get_case(cid)
    if pathologist_id not in db.pathologists:
        _not_found("Pathologist")
    if c["status"] not in ("WORKUP", "PENDING_SIGNOUT"):
        raise ApiError("ERR_CASE_NOT_REASSIGNABLE", 409,
                       "case is not in WORKUP or PENDING_SIGNOUT")
    if expected != c["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION", 412,
                       "expected_case_version does not match the case's "
                       "current version")
    target = _resolve_assignment_target(c, pathologist_id)
    _assign_to(c, target)
    return ok(calc.ser_case(c))

# ---------------------------------------------------------------------------
# Sign-out lifecycle
# ---------------------------------------------------------------------------

@bp.post("/pathology/cases/<cid>/submit-for-signout")
def submit_for_signout(cid):
    uid, role = auth()
    require_role(role, "Pathologist")
    c = _get_case(cid)
    if c["assigned_pathologist_id"] is not None \
            and uid != c["assigned_pathologist_id"]:
        forbid("caller is not the case's assigned pathologist")
    if c["status"] != "WORKUP":
        raise ApiError("ERR_CASE_NOT_IN_WORKUP", 409, "case is not in WORKUP")
    # per-child readiness gate first (PRD 3.6): every non-CANCELLED slide
    # QC_PASSED and every stain order RESULTED/CANCELLED
    slides = calc.case_slides(cid)
    for s in slides:
        if s["status"] != "CANCELLED" and s["status"] != "QC_PASSED":
            raise ApiError("ERR_SLIDES_NOT_READY", 409,
                           "a non-CANCELLED slide is not QC_PASSED")
    for o in calc.case_stain_orders(cid):
        if o["status"] not in ("RESULTED", "CANCELLED"):
            raise ApiError("ERR_SLIDES_NOT_READY", 409,
                           "a stain order is still open")
    # aggregate gate: at least one QC_PASSED slide
    if not any(s["status"] == "QC_PASSED" for s in slides):
        raise ApiError("ERR_EMPTY_SLIDE_SET", 422,
                       "no slide of the case has status QC_PASSED")
    c["status"] = "PENDING_SIGNOUT"
    bump(c)
    return ok(calc.ser_case(c))


@bp.post("/pathology/cases/<cid>/sign-out")
def sign_out(cid):
    uid, role = auth()
    require_role(role, "Pathologist")
    body = payload()
    diagnosis_text = need_str(body, "diagnosis_text")
    c = _get_case(cid)
    if c["assigned_pathologist_id"] is not None \
            and uid != c["assigned_pathologist_id"]:
        forbid("caller is not the case's assigned pathologist")
    if c["status"] != "PENDING_SIGNOUT":
        raise ApiError("ERR_CASE_NOT_PENDING_SIGNOUT", 409,
                       "case is not in PENDING_SIGNOUT")
    if calc.open_critical_discrepancy_count(c) > 0:
        raise ApiError("ERR_UNRESOLVED_CRITICAL_DISCREPANCY", 422,
                       "a LEVEL_3 discrepancy is OPEN or ACKNOWLEDGED")
    if any(q["status"] == "ACCEPTED" for q in calc.case_consultations(cid)):
        raise ApiError("ERR_ACCEPTED_CONSULTATION_OPEN", 409,
                       "a consultation of the case is still ACCEPTED")
    calc.finalize_case(c, uid, diagnosis_text)
    return ok(calc.ser_case(c))

# ---------------------------------------------------------------------------
# Amendments
# ---------------------------------------------------------------------------

@bp.post("/pathology/cases/<cid>/amend")
def amend_case(cid):
    uid, role = auth()
    require_role(role, "Pathologist")
    body = payload()
    diagnosis_text = need_str(body, "diagnosis_text")
    amendment_reason = need_str(body, "amendment_reason")
    c = _get_case(cid)
    if c["status"] != "FINAL":
        raise ApiError("ERR_CASE_NOT_FINAL", 409, "case is not FINAL")
    signed = calc.current_signed_report(c)
    # segregation of duties (priority 36)
    if signed is not None:
        for d in calc.case_discrepancies(cid):
            if d["severity"] in ("LEVEL_2", "LEVEL_3") \
                    and d["report_id"] == signed["id"] \
                    and uid == signed["signed_by_pathologist_id"]:
                raise ApiError("ERR_SOD_AMENDMENT_FORBIDDEN", 422,
                               "the original signer may not amend a report "
                               "with a linked LEVEL_2/LEVEL_3 discrepancy")
    draft = new_entity()
    draft.update({
        "case_id": cid,
        "report_class": "AMENDED",
        "version_number": (signed["version_number"] + 1) if signed else 1,
        "supersedes_report_id": signed["id"] if signed else None,
        "status": "DRAFT",
        "diagnosis_text": diagnosis_text,
        "amendment_reason": amendment_reason,
        "signed_by_pathologist_id": None,
        "signed_at": None,
    })
    db.reports[draft["id"]] = draft
    c["amender_pathologist_id"] = uid
    c["status"] = "AMENDING"
    bump(c)
    return ok(calc.ser_report(draft), status=201)


def _amend_target(cid, uid):
    c = _get_case(cid)
    # ownership applies when an amender is recorded; a case with no open
    # amendment surfaces the state error instead (corner: amend/sign on a
    # FINAL case by the original signer -> ERR_CASE_NOT_AMENDING)
    if c["amender_pathologist_id"] is not None \
            and uid != c["amender_pathologist_id"]:
        forbid("caller is not the case's amender")
    if c["status"] != "AMENDING":
        raise ApiError("ERR_CASE_NOT_AMENDING", 409, "case is not AMENDING")
    draft = None
    for r in calc.case_reports(cid):
        if r["status"] == "DRAFT":
            draft = r
            break
    return c, draft


@bp.post("/pathology/cases/<cid>/amend/sign")
def amend_sign(cid):
    uid, role = auth()
    require_role(role, "Pathologist")
    c, draft = _amend_target(cid, uid)
    t = now()
    draft["status"] = "SIGNED"
    draft["signed_by_pathologist_id"] = uid
    draft["signed_at"] = t
    bump(draft)
    prior = db.reports.get(draft["supersedes_report_id"])
    if prior is not None and prior["status"] == "SIGNED":
        prior["status"] = "SUPERSEDED"
        bump(prior)
    c["amender_pathologist_id"] = None
    c["status"] = "FINAL"
    bump(c)
    return ok(calc.ser_report(draft))


@bp.post("/pathology/cases/<cid>/amend/cancel")
def amend_cancel(cid):
    uid, role = auth()
    require_role(role, "Pathologist")
    c, draft = _amend_target(cid, uid)
    if draft is not None:
        draft["status"] = "CANCELLED"
        bump(draft)
    c["amender_pathologist_id"] = None
    c["status"] = "FINAL"
    bump(c)
    return ok(calc.ser_case(c))

# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

@bp.post("/pathology/cases/<cid>/cancel")
def cancel_case_endpoint(cid):
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    need_str(body, "reason")
    c = _get_case(cid)
    if c["status"] not in ("OPEN", "WORKUP"):
        raise ApiError("ERR_CASE_NOT_CANCELLABLE", 409,
                       "case is not in OPEN or WORKUP")
    calc.cancel_case(c)
    return ok(calc.ser_case(c))

# ---------------------------------------------------------------------------
# Nested creation: specimens
# ---------------------------------------------------------------------------

@bp.post("/pathology/cases/<cid>/specimens")
def accession_specimen(cid):
    _, role = auth()
    require_role(role, "Histotech")
    body = payload()
    patient_mrn = need_str(body, "patient_mrn")
    patient_dob = need_str(body, "patient_dob")
    specimen_type = need_enum(body, "specimen_type", calc.SPECIMEN_TYPES)
    anatomical_site = need_str(body, "anatomical_site")
    collection_dt = need_dt(body, "collection_datetime")
    received_dt = need_dt(body, "received_datetime")
    cc = body.get("container_count")
    if isinstance(cc, bool) or not isinstance(cc, int) or cc < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "container_count must be an integer >= 1")
    fixative = need_enum(body, "fixative_type", calc.FIXATIVE_TYPES) \
        if "fixative_type" in body else "FORMALIN"
    c = _get_case(cid)
    patient = db.patients[c["patient_id"]]
    # priority 30: two-identifier safety check
    if patient["mrn"] != patient_mrn or patient["date_of_birth"] != patient_dob:
        raise ApiError("ERR_PATIENT_IDENTIFIER_MISMATCH", 422,
                       "patient_mrn/patient_dob do not match the case patient")
    # priority 50
    if received_dt < collection_dt:
        raise ApiError("ERR_COLLECTION_AFTER_RECEIVED", 422,
                       "received_datetime precedes collection_datetime")
    cold_minutes = int((received_dt - collection_dt).total_seconds() // 60)
    year = now().year
    seq = db.accession_seq.get(year, 0) + 1
    db.accession_seq[year] = seq
    accession_number = "SP%02d-%06d" % (year % 100, seq)
    s = new_entity()
    s.update({
        "case_id": cid,
        "accession_number": accession_number,
        "specimen_type": specimen_type,
        "anatomical_site": anatomical_site,
        "collection_datetime": collection_dt,
        "received_datetime": received_dt,
        "container_count": cc,
        "fixative_type": fixative,
        "cold_ischemia_minutes": cold_minutes,
        "status": "ACCESSIONED",
        "gross_description": None,
        "retention_until": None,
        "wet_tissue_disposed_at": None,
        "reject_reason": None,
    })
    db.specimens[s["id"]] = s
    bump(c)  # accession endpoint increments the parent case version
    return ok(calc.ser_specimen(s), status=201)

# ---------------------------------------------------------------------------
# Nested creation: stain orders
# ---------------------------------------------------------------------------

@bp.post("/pathology/cases/<cid>/stain-orders")
def create_stain_order(cid):
    uid, role = auth()
    require_role(role, "Pathologist")
    body = payload()
    block_id = need_str(body, "block_id")
    stain_type = need_enum(body, "stain_type", calc.STAIN_TYPES)
    c = _get_case(cid)
    block = db.blocks.get(block_id)
    if block is None:
        _not_found("Block")
    if c["status"] not in ("WORKUP", "PENDING_SIGNOUT", "AMENDING"):
        raise ApiError("ERR_CASE_NOT_ORDERABLE", 409,
                       "case is not in WORKUP, PENDING_SIGNOUT, or AMENDING")
    # priority 31: cold-ischemia gate for cold-sensitive stains
    limit = calc.COLD_ISCHEMIA_LIMITS.get(stain_type)
    if limit is not None:
        spec = db.specimens[block["specimen_id"]]
        if spec["cold_ischemia_minutes"] > limit:
            raise ApiError("ERR_COLD_ISCHEMIA_EXCEEDED", 422,
                           "cold ischemia exceeds the stain's limit")
    # priority 47: block must belong to this case
    if db.specimens[block["specimen_id"]]["case_id"] != cid:
        raise ApiError("ERR_BLOCK_NOT_IN_CASE", 422,
                       "block does not belong to the case")
    o = new_entity()
    o.update({
        "case_id": cid,
        "block_id": block_id,
        "stain_type": stain_type,
        "ordered_by_pathologist_id": uid,
        "reflex_rule_id": None,
        "parent_stain_order_id": None,
        "status": "ORDERED",
        "result_value": None,
        "resulted_at": None,
    })
    db.stain_orders[o["id"]] = o
    bump(c)
    # ordering while PENDING_SIGNOUT pulls the case back to WORKUP
    if c["status"] == "PENDING_SIGNOUT":
        c["status"] = "WORKUP"
        bump(c)
    return ok(calc.ser_stain_order(o), status=201)

# ---------------------------------------------------------------------------
# Nested creation: consultations
# ---------------------------------------------------------------------------

@bp.post("/pathology/cases/<cid>/consultations")
def create_consultation(cid):
    uid, role = auth()
    require_role(role, "Pathologist")
    body = payload()
    consultant_id = need_str(body, "consultant_pathologist_id")
    subspecialty = need_enum(body, "subspecialty", calc.SUBSPECIALTIES)
    question_text = need_str(body, "question_text")
    due_at = need_dt(body, "due_at")
    c = _get_case(cid)
    consultant = db.pathologists.get(consultant_id)
    if consultant is None:
        _not_found("Pathologist")
    if c["status"] not in ("WORKUP", "PENDING_SIGNOUT", "FINAL", "AMENDING"):
        raise ApiError("ERR_CASE_NOT_CONSULTABLE", 409,
                       "case is not consultable in its current status")
    if consultant_id == uid:
        raise ApiError("ERR_SELF_CONSULTATION", 422,
                       "consultant equals the requesting pathologist")
    if consultant_id == c["assigned_pathologist_id"]:
        raise ApiError("ERR_CONSULTANT_IS_ASSIGNED", 422,
                       "consultant equals the case assigned pathologist")
    if subspecialty not in consultant["subspecialties"]:
        raise ApiError("ERR_SUBSPECIALTY_MISMATCH", 422,
                       "consultant does not hold the requested subspecialty")
    if not due_at > now():
        raise ApiError("ERR_DUE_AT_NOT_FUTURE", 422,
                       "due_at must be strictly in the future")
    q = new_entity()
    q.update({
        "case_id": cid,
        "requesting_pathologist_id": uid,
        "consultant_pathologist_id": consultant_id,
        "subspecialty": subspecialty,
        "question_text": question_text,
        "due_at": due_at,
        "status": "REQUESTED",
        "opinion_text": None,
        "concordance": None,
        "answered_at": None,
        "decline_reason": None,
        "reroute_count": 0,
    })
    db.consultations[q["id"]] = q
    return ok(calc.ser_consultation(q), status=201)

# ---------------------------------------------------------------------------
# Nested creation: discrepancies
# ---------------------------------------------------------------------------

@bp.post("/pathology/cases/<cid>/discrepancies")
def create_discrepancy(cid):
    _, role = auth()
    require_role(role, "Pathologist", "LabAdmin")
    body = payload()
    severity = need_enum(body, "severity", calc.SEVERITIES)
    description = need_str(body, "description")
    report_id = body.get("report_id")
    if report_id is not None and not isinstance(report_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "report_id must be a string")
    c = _get_case(cid)
    attributed = None
    if report_id is not None:
        rep = db.reports.get(report_id)
        if rep is None:
            _not_found("Report")
        attributed = rep["signed_by_pathologist_id"]
    else:
        attributed = c["assigned_pathologist_id"]
    d = new_entity()
    d.update({
        "case_id": cid,
        "consultation_id": None,
        "report_id": report_id,
        "source": "INTERNAL_QA",
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "attributed_pathologist_id": attributed,
        "resolved_at": None,
        "resolved_with_amendment": False,
    })
    db.discrepancies[d["id"]] = d
    bump(c)
    return ok(calc.ser_discrepancy(d), status=201)
