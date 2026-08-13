"""Review-surface routes: consultations, discrepancies, reports (read-only),
and material release requests."""
from flask import Blueprint, request

from db import db
from errors import ApiError
from helpers import (
    qparam,
    auth, require_role, payload, ok, paginate, forbid,
    need_str, need_enum, need_dt, now,
)
import calc
from calc import new_entity, bump

bp = Blueprint("review", __name__)


def _not_found(what="Resource"):
    raise ApiError("ERR_NOT_FOUND", 404, "%s does not exist" % what)


def _get_consultation(qid):
    q = db.consultations.get(qid)
    if q is None:
        _not_found("Consultation")
    return q


def _get_discrepancy(did):
    d = db.discrepancies.get(did)
    if d is None:
        _not_found("Discrepancy")
    return d


def _get_release(rid):
    r = db.release_requests.get(rid)
    if r is None:
        _not_found("ReleaseRequest")
    return r


# ---------------------------------------------------------------------------
# Consultations
# ---------------------------------------------------------------------------

@bp.get("/pathology/consultations/<qid>")
def get_consultation(qid):
    auth()
    return ok(calc.ser_consultation(_get_consultation(qid)))


@bp.get("/pathology/consultations")
def list_consultations():
    auth()
    items = list(db.consultations.values())
    for param, field in (("case_id", "case_id"),
                         ("consultant_pathologist_id",
                          "consultant_pathologist_id"),
                         ("requesting_pathologist_id",
                          "requesting_pathologist_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [q for q in items if q[field] == v]
    page, meta = paginate(items)
    return ok([calc.ser_consultation(q) for q in page],
              response_type="array", pagination=meta)


@bp.post("/pathology/consultations/<qid>/accept")
def accept_consultation(qid):
    uid, role = auth()
    require_role(role, "Pathologist")
    q = _get_consultation(qid)
    if uid != q["consultant_pathologist_id"]:
        forbid("caller is not the consultation's consultant")
    if q["status"] != "REQUESTED":
        raise ApiError("ERR_CONSULTATION_WRONG_STATE", 409,
                       "accept requires consultation status REQUESTED")
    # the logical clock must be strictly before due_at
    if not now() < q["due_at"]:
        raise ApiError("ERR_CONSULTATION_WRONG_STATE", 409,
                       "consultation is past its due_at")
    if calc.in_unavailable_window(q["consultant_pathologist_id"], now()):
        raise ApiError("ERR_CONSULTANT_UNAVAILABLE", 422,
                       "consultant is inside an ACTIVE UNAVAILABLE window")
    q["status"] = "ACCEPTED"
    bump(q)
    return ok(calc.ser_consultation(q))


@bp.post("/pathology/consultations/<qid>/decline")
def decline_consultation(qid):
    uid, role = auth()
    require_role(role, "Pathologist")
    body = payload()
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "reason must be a string")
    q = _get_consultation(qid)
    if uid != q["consultant_pathologist_id"]:
        forbid("caller is not the consultation's consultant")
    if q["status"] != "REQUESTED":
        raise ApiError("ERR_CONSULTATION_WRONG_STATE", 409,
                       "decline requires consultation status REQUESTED")
    q["status"] = "DECLINED"
    q["decline_reason"] = reason
    bump(q)
    return ok(calc.ser_consultation(q))


@bp.post("/pathology/consultations/<qid>/answer")
def answer_consultation(qid):
    uid, role = auth()
    require_role(role, "Pathologist")
    body = payload()
    opinion_text = need_str(body, "opinion_text")
    concordance = need_enum(body, "concordance", calc.CONCORDANCES)
    q = _get_consultation(qid)
    if uid != q["consultant_pathologist_id"]:
        forbid("caller is not the consultation's consultant")
    if q["status"] != "ACCEPTED":
        raise ApiError("ERR_CONSULTATION_WRONG_STATE", 409,
                       "answer requires consultation status ACCEPTED")
    q["status"] = "ANSWERED"
    q["opinion_text"] = opinion_text
    q["concordance"] = concordance
    q["answered_at"] = now()
    bump(q)
    # non-CONCORDANT answers auto-create a discrepancy on the case
    if concordance in ("MINOR_DISCORDANT", "MAJOR_DISCORDANT"):
        case = db.cases[q["case_id"]]
        signed = calc.current_signed_report(case)
        d = new_entity()
        d.update({
            "case_id": q["case_id"],
            "consultation_id": q["id"],
            "report_id": signed["id"] if signed else None,
            "source": "CONSULTATION",
            "severity": "LEVEL_1" if concordance == "MINOR_DISCORDANT"
                        else "LEVEL_2",
            "description": "Auto-created from %s consultation answer"
                           % concordance,
            "status": "OPEN",
            "attributed_pathologist_id":
                (signed["signed_by_pathologist_id"] if signed
                 else case["assigned_pathologist_id"]),
            "resolved_at": None,
            "resolved_with_amendment": False,
        })
        db.discrepancies[d["id"]] = d
    return ok(calc.ser_consultation(q))


@bp.post("/pathology/consultations/<qid>/incorporate")
def incorporate_consultation(qid):
    uid, role = auth()
    require_role(role, "Pathologist")
    q = _get_consultation(qid)
    if uid != q["requesting_pathologist_id"]:
        forbid("caller is not the consultation's requester")
    if q["status"] != "ANSWERED":
        raise ApiError("ERR_CONSULTATION_WRONG_STATE", 409,
                       "incorporate requires consultation status ANSWERED")
    q["status"] = "INCORPORATED"
    bump(q)
    return ok(calc.ser_consultation(q))


@bp.post("/pathology/consultations/<qid>/reroute")
def reroute_consultation(qid):
    uid, role = auth()
    require_role(role, "Pathologist")
    body = payload()
    consultant_id = need_str(body, "consultant_pathologist_id")
    due_at = need_dt(body, "due_at")
    q = _get_consultation(qid)
    if uid != q["requesting_pathologist_id"]:
        forbid("caller is not the consultation's requester")
    consultant = db.pathologists.get(consultant_id)
    if consultant is None:
        _not_found("Pathologist")
    if q["status"] not in ("DECLINED", "EXPIRED"):
        raise ApiError("ERR_CONSULTATION_WRONG_STATE", 409,
                       "reroute requires consultation status DECLINED or "
                       "EXPIRED")
    case = db.cases[q["case_id"]]
    # creation-time checks re-applied, in the fixed order
    if consultant_id == uid:
        raise ApiError("ERR_SELF_CONSULTATION", 422,
                       "consultant equals the requesting pathologist")
    if consultant_id == case["assigned_pathologist_id"]:
        raise ApiError("ERR_CONSULTANT_IS_ASSIGNED", 422,
                       "consultant equals the case assigned pathologist")
    if q["subspecialty"] not in consultant["subspecialties"]:
        raise ApiError("ERR_SUBSPECIALTY_MISMATCH", 422,
                       "consultant does not hold the requested subspecialty")
    if not due_at > now():
        raise ApiError("ERR_DUE_AT_NOT_FUTURE", 422,
                       "due_at must be strictly in the future")
    q["consultant_pathologist_id"] = consultant_id
    q["due_at"] = due_at
    q["status"] = "REQUESTED"
    q["reroute_count"] += 1
    bump(q)
    return ok(calc.ser_consultation(q))

# ---------------------------------------------------------------------------
# Discrepancies
# ---------------------------------------------------------------------------

@bp.get("/pathology/discrepancies/<did>")
def get_discrepancy(did):
    auth()
    return ok(calc.ser_discrepancy(_get_discrepancy(did)))


@bp.get("/pathology/discrepancies")
def list_discrepancies():
    auth()
    items = list(db.discrepancies.values())
    for param, field in (("case_id", "case_id"),
                         ("consultation_id", "consultation_id"),
                         ("report_id", "report_id"),
                         ("attributed_pathologist_id",
                          "attributed_pathologist_id"),
                         ("status", "status"), ("severity", "severity")):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d[field] == v]
    page, meta = paginate(items)
    return ok([calc.ser_discrepancy(d) for d in page],
              response_type="array", pagination=meta)


@bp.post("/pathology/discrepancies/<did>/acknowledge")
def acknowledge_discrepancy(did):
    uid, role = auth()
    require_role(role, "Pathologist")
    d = _get_discrepancy(did)
    case = db.cases[d["case_id"]]
    if case["assigned_pathologist_id"] is not None \
            and uid != case["assigned_pathologist_id"]:
        forbid("caller is not the case's assigned pathologist")
    if d["status"] != "OPEN":
        raise ApiError("ERR_DISCREPANCY_WRONG_STATE", 409,
                       "acknowledge requires discrepancy status OPEN")
    d["status"] = "ACKNOWLEDGED"
    bump(d)
    return ok(calc.ser_discrepancy(d))


@bp.post("/pathology/discrepancies/<did>/resolve")
def resolve_discrepancy(did):
    _, role = auth()
    require_role(role, "Pathologist", "LabAdmin")
    body = payload()
    rwa = body.get("resolved_with_amendment", False)
    if not isinstance(rwa, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "resolved_with_amendment must be a boolean")
    d = _get_discrepancy(did)
    # state gate: OPEN resolves LEVEL_1 only; ACKNOWLEDGED resolves any
    if d["status"] == "OPEN":
        if d["severity"] != "LEVEL_1":
            raise ApiError("ERR_DISCREPANCY_WRONG_STATE", 409,
                           "LEVEL_2/LEVEL_3 must be ACKNOWLEDGED before "
                           "resolution")
    elif d["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_DISCREPANCY_WRONG_STATE", 409,
                       "resolve requires status OPEN (LEVEL_1) or "
                       "ACKNOWLEDGED")
    if d["severity"] in ("LEVEL_2", "LEVEL_3"):
        # requires resolved_with_amendment true and a subsequently signed
        # AMENDED report on the owning case
        ok_amendment = False
        if rwa:
            for r in calc.case_reports(d["case_id"]):
                if r["report_class"] == "AMENDED" and r["status"] == "SIGNED" \
                        and r["signed_at"] is not None \
                        and r["signed_at"] > d["created_at"]:
                    ok_amendment = True
                    break
        if not ok_amendment:
            raise ApiError("ERR_AMENDMENT_REQUIRED", 422,
                           "LEVEL_2/LEVEL_3 resolution requires a subsequent "
                           "signed amendment and resolved_with_amendment true")
    d["status"] = "RESOLVED"
    d["resolved_at"] = now()
    d["resolved_with_amendment"] = rwa
    bump(d)
    return ok(calc.ser_discrepancy(d))

# ---------------------------------------------------------------------------
# Reports (read-only)
# ---------------------------------------------------------------------------

@bp.get("/pathology/reports/<rid>")
def get_report(rid):
    auth()
    r = db.reports.get(rid)
    if r is None:
        _not_found("Report")
    return ok(calc.ser_report(r))


@bp.get("/pathology/reports")
def list_reports():
    auth()
    items = list(db.reports.values())
    for param, field in (("case_id", "case_id"),
                         ("supersedes_report_id", "supersedes_report_id"),
                         ("signed_by_pathologist_id",
                          "signed_by_pathologist_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    page, meta = paginate(items)
    return ok([calc.ser_report(r) for r in page],
              response_type="array", pagination=meta)

# ---------------------------------------------------------------------------
# Release requests
# ---------------------------------------------------------------------------

@bp.post("/pathology/release-requests")
def create_release_request():
    _, role = auth()
    require_role(role, "LabAdmin", "Pathologist")
    body = payload()
    material_type = need_enum(body, "material_type", {"BLOCK", "SLIDE"})
    block_id = body.get("block_id")
    slide_id = body.get("slide_id")
    if block_id is not None and not isinstance(block_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "block_id must be a string")
    if slide_id is not None and not isinstance(slide_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "slide_id must be a string")
    # exactly the id field matching material_type must be present
    if material_type == "BLOCK" and (block_id is None or slide_id is not None):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "material_type BLOCK requires block_id only")
    if material_type == "SLIDE" and (slide_id is None or block_id is not None):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "material_type SLIDE requires slide_id only")
    institution = need_str(body, "requesting_institution")
    reason = need_str(body, "reason")
    out_at = need_dt(body, "requested_out_at")
    back_at = need_dt(body, "due_back_at")
    if not back_at > out_at:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "due_back_at must be strictly after requested_out_at")
    # resolve the referenced material (priority 4), then its case
    if material_type == "BLOCK":
        block = db.blocks.get(block_id)
        if block is None:
            _not_found("Block")
        case = calc.case_of_block(block)
    else:
        slide = db.slides.get(slide_id)
        if slide is None:
            _not_found("Slide")
        case = calc.case_of_slide(slide)
    if case["status"] != "FINAL":
        raise ApiError("ERR_CASE_NOT_FINAL", 409,
                       "the material's case is not FINAL")
    if material_type == "BLOCK":
        if block["status"] != "EMBEDDED":
            raise ApiError("ERR_MATERIAL_NOT_RELEASABLE", 409,
                           "block is not EMBEDDED")
    else:
        if slide["status"] != "QC_PASSED":
            raise ApiError("ERR_MATERIAL_NOT_RELEASABLE", 409,
                           "slide is not QC_PASSED")
    r = new_entity()
    r.update({
        "material_type": material_type,
        "block_id": block_id if material_type == "BLOCK" else None,
        "slide_id": slide_id if material_type == "SLIDE" else None,
        "requesting_institution": institution,
        "reason": reason,
        "requested_out_at": out_at,
        "due_back_at": back_at,
        "status": "REQUESTED",
        "shipped_at": None,
        "returned_at": None,
        "returned_late": False,
        "deny_reason": None,
    })
    db.release_requests[r["id"]] = r
    return ok(calc.ser_release_request(r), status=201)


@bp.get("/pathology/release-requests/<rid>")
def get_release_request(rid):
    auth()
    return ok(calc.ser_release_request(_get_release(rid)))


@bp.get("/pathology/release-requests")
def list_release_requests():
    auth()
    items = list(db.release_requests.values())
    for param in ("block_id", "slide_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    page, meta = paginate(items)
    return ok([calc.ser_release_request(r) for r in page],
              response_type="array", pagination=meta)


def _release_material(r):
    """(case, block|slide) referenced by a release request."""
    if r["material_type"] == "BLOCK":
        block = db.blocks[r["block_id"]]
        return calc.case_of_block(block), block
    slide = db.slides[r["slide_id"]]
    return calc.case_of_slide(slide), slide


@bp.post("/pathology/release-requests/<rid>/approve")
def approve_release(rid):
    _, role = auth()
    require_role(role, "LabAdmin")
    r = _get_release(rid)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_RELEASE_WRONG_STATE", 409,
                       "approve requires release status REQUESTED")
    case, material = _release_material(r)
    # priority 37 (safety) outranks priority 55 (temporal)
    if r["material_type"] == "SLIDE":
        passed = [s for s in calc.case_slides(case["id"])
                  if s["status"] == "QC_PASSED"]
        if len(passed) == 1 and passed[0]["id"] == r["slide_id"]:
            raise ApiError("ERR_LAST_DIAGNOSTIC_MATERIAL", 422,
                           "cannot release the case's only QC_PASSED slide")
    else:
        embedded = [b for b in calc.case_blocks(case["id"])
                    if b["status"] == "EMBEDDED"]
        if len(embedded) == 1 and embedded[0]["id"] == r["block_id"]:
            raise ApiError("ERR_LAST_DIAGNOSTIC_MATERIAL", 422,
                           "cannot release the case's only EMBEDDED "
                           "non-DEPLETED block")
    key = "block_id" if r["material_type"] == "BLOCK" else "slide_id"
    for other in db.release_requests.values():
        if other["id"] == r["id"] or other.get(key) != r[key]:
            continue
        if other["status"] not in ("REQUESTED", "APPROVED", "SHIPPED",
                                   "OVERDUE"):
            continue
        # CLOSED-interval intersection; touching endpoints count
        if other["requested_out_at"] <= r["due_back_at"] \
                and r["requested_out_at"] <= other["due_back_at"]:
            raise ApiError("ERR_LOAN_INTERVAL_CONFLICT", 409,
                           "overlapping loan interval for the same material")
    r["status"] = "APPROVED"
    bump(r)
    return ok(calc.ser_release_request(r))


@bp.post("/pathology/release-requests/<rid>/deny")
def deny_release(rid):
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    reason = need_str(body, "reason")
    r = _get_release(rid)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_RELEASE_WRONG_STATE", 409,
                       "deny requires release status REQUESTED")
    r["status"] = "DENIED"
    r["deny_reason"] = reason
    bump(r)
    return ok(calc.ser_release_request(r))


@bp.post("/pathology/release-requests/<rid>/ship")
def ship_release(rid):
    _, role = auth()
    require_role(role, "Histotech")
    r = _get_release(rid)
    if r["status"] != "APPROVED":
        raise ApiError("ERR_RELEASE_WRONG_STATE", 409,
                       "ship requires release status APPROVED")
    r["status"] = "SHIPPED"
    r["shipped_at"] = now()
    bump(r)
    return ok(calc.ser_release_request(r))


@bp.post("/pathology/release-requests/<rid>/return")
def return_release(rid):
    _, role = auth()
    require_role(role, "Histotech")
    r = _get_release(rid)
    if r["status"] not in ("SHIPPED", "OVERDUE"):
        raise ApiError("ERR_RELEASE_WRONG_STATE", 409,
                       "return requires release status SHIPPED or OVERDUE")
    t = now()
    r["status"] = "RETURNED"
    r["returned_at"] = t
    r["returned_late"] = t > r["due_back_at"]
    bump(r)
    return ok(calc.ser_release_request(r))
