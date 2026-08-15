"""Byproduct streams, characterization profiles, reuse-eligibility determinations."""
from flask import Blueprint, request

from common import (ApiError, actor, as_date, as_dec, as_enum, as_int, as_str,
                    bad_request, body_dict, created, fk_not_found,
                    invalid_state, not_found, ok, ok_list, ownership_err,
                    paginate, raw_body, ser)
from logic import (MATERIALS, USE_CASES, current_date,
                   eligibility_window_overlaps, lazy_expire_determination,
                   new_record, sorted_items,
                   stream_has_verified_characterization, touch)
from store import db

bp = Blueprint("streams", __name__)


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------

@bp.post("/api/streams")
def create_stream():
    uid, _ = actor({"Generator"})
    raw = raw_body()
    # stage 3 ownership (before body well-formedness)
    if isinstance(raw, dict):
        gid = raw.get("generator_id")
        if gid is not None and gid != uid:
            ownership_err()
    body = body_dict()
    gen_id = as_str(body, "generator_id")
    material = as_enum(body, "material_type", MATERIALS)
    moisture = as_dec(body, "declared_moisture_pct")
    expected = as_int(body, "expected_tons_per_month")
    if expected <= 0:
        bad_request("expected_tons_per_month must be positive")
    if gen_id not in db.generators:
        fk_not_found("generator_id does not resolve to a Generator")
    rec = new_record()
    rec.update(generator_id=gen_id, material_type=material,
               declared_moisture_pct=moisture,
               expected_tons_per_month=expected, status="DRAFT")
    db.streams[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/streams")
def list_streams():
    actor()
    items = sorted_items(db.streams.values())
    gid = request.args.get("generator_id")
    status = request.args.get("status")
    mt = request.args.get("material_type")
    if gid is not None:
        items = [r for r in items if r["generator_id"] == gid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if mt is not None:
        items = [r for r in items if r["material_type"] == mt]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


@bp.get("/api/streams/<sid>")
def get_stream(sid):
    actor()
    rec = db.streams.get(sid)
    if rec is None:
        not_found("Stream not found")
    return ok(ser(rec))


# ---------------------------------------------------------------------------
# Characterization profiles
# ---------------------------------------------------------------------------

@bp.post("/api/streams/<sid>/characterizations")
def create_characterization(sid):
    uid, _ = actor({"Generator"})
    stream = db.streams.get(sid)
    if stream is not None and stream["generator_id"] != uid:
        ownership_err()
    body = body_dict()
    lab = as_str(body, "lab_name")
    sampled = as_date(body, "sampled_on")
    ph = as_dec(body, "ph")
    arsenic = as_dec(body, "arsenic_ppm")
    lead = as_dec(body, "lead_ppm")
    moisture = as_dec(body, "moisture_pct_measured")
    if stream is None:
        not_found("Stream not found")
    rec = new_record()
    rec.update(stream_id=sid, lab_name=lab, sampled_on=sampled, ph=ph,
               arsenic_ppm=arsenic, lead_ppm=lead,
               moisture_pct_measured=moisture, status="SUBMITTED",
               rejection_reason=None)
    db.characterizations[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/streams/<sid>/characterizations")
def list_characterizations(sid):
    actor()
    if sid not in db.streams:
        not_found("Stream not found")
    items = [c for c in sorted_items(db.characterizations.values())
             if c["stream_id"] == sid]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


@bp.post("/api/characterizations/<cid>/verify")
def verify_characterization(cid):
    actor({"BrokerOps"})
    rec = db.characterizations.get(cid)
    if rec is None:
        not_found("Characterization not found")
    if rec["status"] != "SUBMITTED":
        invalid_state()
    rec["status"] = "VERIFIED"
    touch(rec)
    stream = db.streams.get(rec["stream_id"])
    if stream is not None and stream["status"] == "DRAFT":
        stream["status"] = "CHARACTERIZED"
        touch(stream)
    return ok(ser(rec))


@bp.post("/api/characterizations/<cid>/reject")
def reject_characterization(cid):
    actor({"BrokerOps"})
    rec = db.characterizations.get(cid)
    reason = as_str(body_dict(), "reason")
    if rec is None:
        not_found("Characterization not found")
    if rec["status"] != "SUBMITTED":
        invalid_state()
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = reason
    touch(rec)
    return ok(ser(rec))


# ---------------------------------------------------------------------------
# Reuse-eligibility determinations
# ---------------------------------------------------------------------------

@bp.post("/api/streams/<sid>/eligibility-determinations")
def create_determination(sid):
    uid, _ = actor({"ComplianceOfficer"})
    body = body_dict()
    state_code = as_str(body, "state_code")
    use_case = as_enum(body, "use_case", USE_CASES)
    v_from = as_date(body, "valid_from")
    v_until = as_date(body, "valid_until")
    if v_until <= v_from:
        bad_request("valid_until must be after valid_from")
    if sid not in db.streams:
        not_found("Stream not found")
    if not stream_has_verified_characterization(sid):
        raise ApiError("ERR_STREAM_NOT_CHARACTERIZED", 422,
                       "Stream lacks a VERIFIED characterization")
    rec = new_record()
    rec.update(stream_id=sid, state_code=state_code, use_case=use_case,
               valid_from=v_from, valid_until=v_until,
               filed_by_user_id=uid, approved_by_user_id=None,
               status="DRAFT", decision_reason=None)
    db.determinations[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/streams/<sid>/eligibility-determinations")
def list_determinations(sid):
    actor()
    if sid not in db.streams:
        not_found("Stream not found")
    items = [d for d in sorted_items(db.determinations.values())
             if d["stream_id"] == sid]
    for d in items:
        lazy_expire_determination(d)
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


def _load_determination(did):
    d = db.determinations.get(did)
    if d is None:
        not_found("Determination not found")
    lazy_expire_determination(d)
    return d


def _segregation_check(d, uid):
    if d["filed_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Approver/denier must differ from the filer")


@bp.post("/api/eligibility-determinations/<did>/submit")
def submit_determination(did):
    actor({"ComplianceOfficer"})
    d = _load_determination(did)
    if d["status"] != "DRAFT":
        invalid_state()
    # stage 10 (temporal) before stage 12 (referential) per section 2.10
    if eligibility_window_overlaps(d["stream_id"], d["state_code"], d["id"],
                                   d["valid_from"], d["valid_until"]):
        raise ApiError("ERR_ELIGIBILITY_WINDOW_OVERLAP", 409,
                       "Window overlaps a peer determination")
    if not stream_has_verified_characterization(d["stream_id"]):
        raise ApiError("ERR_STREAM_NOT_CHARACTERIZED", 422,
                       "Stream lacks a VERIFIED characterization")
    d["status"] = "SUBMITTED"
    touch(d)
    return ok(ser(d))


@bp.post("/api/eligibility-determinations/<did>/revise")
def revise_determination(did):
    actor({"ComplianceOfficer"})
    d = _load_determination(did)
    if d["status"] != "DENIED":
        invalid_state()
    d["status"] = "DRAFT"
    d["decision_reason"] = None
    d["approved_by_user_id"] = None
    touch(d)
    return ok(ser(d))


@bp.post("/api/eligibility-determinations/<did>/approve")
def approve_determination(did):
    uid, _ = actor({"ComplianceOfficer"})
    d = db.determinations.get(did)
    if d is not None:
        _segregation_check(d, uid)
    if d is None:
        not_found("Determination not found")
    lazy_expire_determination(d)
    if d["status"] != "SUBMITTED":
        invalid_state()
    # stage 10: overlap before window-past per section 2.10
    if eligibility_window_overlaps(d["stream_id"], d["state_code"], d["id"],
                                   d["valid_from"], d["valid_until"]):
        raise ApiError("ERR_ELIGIBILITY_WINDOW_OVERLAP", 409,
                       "Window overlaps a peer determination")
    if not d["valid_until"] > current_date():
        raise ApiError("ERR_ELIGIBILITY_WINDOW_PAST", 422,
                       "valid_until is not after the current logical date")
    d["status"] = "APPROVED"
    d["approved_by_user_id"] = uid
    touch(d)
    stream = db.streams.get(d["stream_id"])
    if stream is not None and stream["status"] == "CHARACTERIZED":
        stream["status"] = "ACTIVE"
        touch(stream)
    return ok(ser(d))


@bp.post("/api/eligibility-determinations/<did>/deny")
def deny_determination(did):
    uid, _ = actor({"ComplianceOfficer"})
    d = db.determinations.get(did)
    if d is not None:
        _segregation_check(d, uid)
    reason = as_str(body_dict(), "reason")
    if d is None:
        not_found("Determination not found")
    lazy_expire_determination(d)
    if d["status"] != "SUBMITTED":
        invalid_state()
    d["status"] = "DENIED"
    d["decision_reason"] = reason
    touch(d)
    return ok(ser(d))


@bp.post("/api/eligibility-determinations/<did>/suspend")
def suspend_determination(did):
    actor({"ComplianceOfficer"})
    d = _load_determination(did)
    if d["status"] != "APPROVED":
        invalid_state()
    d["status"] = "SUSPENDED"
    touch(d)
    return ok(ser(d))


@bp.post("/api/eligibility-determinations/<did>/reinstate")
def reinstate_determination(did):
    actor({"ComplianceOfficer"})
    d = _load_determination(did)
    if d["status"] != "SUSPENDED":
        invalid_state()
    if eligibility_window_overlaps(d["stream_id"], d["state_code"], d["id"],
                                   d["valid_from"], d["valid_until"]):
        raise ApiError("ERR_ELIGIBILITY_WINDOW_OVERLAP", 409,
                       "Window overlaps a peer determination")
    if not d["valid_until"] > current_date():
        raise ApiError("ERR_ELIGIBILITY_WINDOW_PAST", 422,
                       "valid_until is not after the current logical date")
    d["status"] = "APPROVED"
    touch(d)
    return ok(ser(d))
