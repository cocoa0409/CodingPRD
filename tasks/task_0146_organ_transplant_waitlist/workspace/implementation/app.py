"""Organ Transplant Waitlist API — Flask entry point.

In-memory store, deterministic clock, full validation-priority ordering per
PRD §2.8. Boots empty on every invocation; no seeding.
"""
import os

from flask import Flask, request

from errors import ApiError, err
from store import db
from response import success, error
from timeutil import parse_iso, format_iso, add_hours
from common import (
    authenticate, require_role, base_fields, touch, touch_no_version, public_view,
    parse_pagination, paginate, sorted_by_created, get_body,
    require_str, require_enum, require_int_range, require_number,
    require_positive_number, require_hla_array, optional_str_array,
    require_bool, require_timestamp,
)
import calc
import services

app = Flask(__name__)

ORGAN_TYPES = {"LIVER", "KIDNEY", "HEART", "LUNG"}
BLOOD_TYPES = {"O", "A", "B", "AB"}
REMOVAL_REASONS = {"DECEASED", "IMPROVED", "TRANSFERRED", "OTHER"}
DECLINE_REASONS = {"SIZE_MISMATCH", "MEDICAL_UNSUITABLE", "CANDIDATE_UNAVAILABLE",
                   "CENTER_DECLINE", "OTHER"}
INTERVAL_LABELS = {"M1", "M6", "M12", "M24"}
REPORT_KINDS = {"TRANSPLANT", "REMOVAL", "FOLLOWUP"}
POLICY_CODES = {"STANDARD", "BROADER_SHARING"}


# ============================================================================
# Error handling
# ============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)


# ============================================================================
# Existence / ownership helpers (PRD §2.6, §2.8)
# ============================================================================
def find_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource '%s' not found" % rid)
    return rec


def candidate_owner_check(candidate, user_id, role):
    """A TransplantCenter may mutate a candidate only when it owns it."""
    if role == "TransplantCenter" and candidate["center_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting center does not own this candidate")


def offer_owner_check(offer, user_id, role):
    if role == "TransplantCenter":
        candidate = db.candidates.get(offer["candidate_id"])
        if candidate is None or candidate["center_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Acting center does not own this offer")


def transplant_owner_check(transplant, user_id, role):
    if role == "TransplantCenter":
        candidate = db.candidates.get(transplant["candidate_id"])
        if candidate is None or candidate["center_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Acting center does not own this transplant")


# ============================================================================
# Reference data: Transplant Centers
# ============================================================================
@app.route("/transplant-centers", methods=["POST"])
def create_center():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin"})
    body = get_body()
    name = require_str(body, "name")
    code = require_str(body, "unos_center_code")
    region = require_int_range(body, "region_code", 1, 11)
    lat = require_number(body, "latitude")
    lon = require_number(body, "longitude")
    for c in db.transplant_centers.values():
        if c["unos_center_code"] == code:
            raise err("ERR_DUPLICATE_RESOURCE", "unos_center_code already exists")
    rec = base_fields()
    rec.update({"name": name, "unos_center_code": code, "region_code": region,
                "latitude": lat, "longitude": lon})
    db.transplant_centers[rec["id"]] = rec
    return success(public_view(rec), 201)


@app.route("/transplant-centers/<rid>", methods=["GET"])
def get_center(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter", "OrganProcurementOrg"})
    rec = find_or_404(db.transplant_centers, rid)
    return success(public_view(rec), 200)


# ============================================================================
# Reference data: Organ Procurement Orgs
# ============================================================================
@app.route("/organ-procurement-orgs", methods=["POST"])
def create_opo():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin"})
    body = get_body()
    name = require_str(body, "name")
    code = require_str(body, "opo_code")
    region = require_int_range(body, "region_code", 1, 11)
    lat = require_number(body, "latitude")
    lon = require_number(body, "longitude")
    for o in db.opos.values():
        if o["opo_code"] == code:
            raise err("ERR_DUPLICATE_RESOURCE", "opo_code already exists")
    rec = base_fields()
    rec.update({"name": name, "opo_code": code, "region_code": region,
                "latitude": lat, "longitude": lon})
    db.opos[rec["id"]] = rec
    return success(public_view(rec), 201)


@app.route("/organ-procurement-orgs/<rid>", methods=["GET"])
def get_opo(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter", "OrganProcurementOrg"})
    rec = find_or_404(db.opos, rid)
    return success(public_view(rec), 200)


# ============================================================================
# Candidates
# ============================================================================
@app.route("/candidates", methods=["POST"])
def create_candidate():
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    body = get_body()
    # Existence: center_id must resolve (PRD §2.6).
    center_id = body.get("center_id")
    if not isinstance(center_id, str) or center_id not in db.transplant_centers:
        if not isinstance(center_id, str):
            raise err("ERR_INVALID_REQUEST", "center_id required")
        raise err("ERR_NOT_FOUND", "center_id does not resolve")
    # Ownership: the acting center must be the owning center.
    if center_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting center does not own this candidate")
    # Field shape.
    mrn = require_str(body, "mrn")
    organ_type = require_enum(body, "organ_type", ORGAN_TYPES)
    blood_type = require_enum(body, "blood_type", BLOOD_TYPES)
    dob = require_timestamp(body, "date_of_birth")
    height = require_positive_number(body, "height_cm")
    weight = require_positive_number(body, "weight_kg")
    hla_a = require_hla_array(body, "hla_a")
    hla_b = require_hla_array(body, "hla_b")
    hla_dr = require_hla_array(body, "hla_dr")
    unacceptable = optional_str_array(body, "unacceptable_antigens", default=[])
    # Uniqueness: (center_id, mrn).
    for c in db.candidates.values():
        if c["center_id"] == center_id and c["mrn"] == mrn:
            raise err("ERR_DUPLICATE_RESOURCE", "(center_id, mrn) already exists")
    rec = base_fields()
    rec.update({
        "center_id": center_id, "mrn": mrn, "organ_type": organ_type,
        "blood_type": blood_type, "date_of_birth": format_iso(dob),
        "height_cm": height, "weight_kg": weight,
        "hla_a": hla_a, "hla_b": hla_b, "hla_dr": hla_dr,
        "unacceptable_antigens": unacceptable,
        "listing_status": "DRAFT", "medical_status": "ACTIVE",
        "current_meld_peld": 0, "is_pediatric": None,
        "listed_at": None, "waiting_time_days": 0, "removal_reason": None,
        "_accrual_intervals": [],
    })
    db.candidates[rec["id"]] = rec
    return success(services.serialize_candidate(rec), 201)


@app.route("/candidates", methods=["GET"])
def list_candidates():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter", "OrganProcurementOrg"})
    items = list(db.candidates.values())
    center_id = request.args.get("center_id")
    organ_type = request.args.get("organ_type")
    listing_status = request.args.get("listing_status")
    if center_id is not None:
        items = [c for c in items if c["center_id"] == center_id]
    if organ_type is not None:
        items = [c for c in items if c["organ_type"] == organ_type]
    if listing_status is not None:
        items = [c for c in items if c["listing_status"] == listing_status]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([services.serialize_candidate(c) for c in page], 200,
                   is_array=True, pagination=pg)


@app.route("/candidates/<rid>", methods=["GET"])
def get_candidate(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter", "OrganProcurementOrg"})
    rec = find_or_404(db.candidates, rid)
    return success(services.serialize_candidate(rec), 200)


@app.route("/candidates/<rid>/list", methods=["POST"])
def list_candidate(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    cand = find_or_404(db.candidates, rid)
    candidate_owner_check(cand, user_id, role)
    # State: DRAFT -> LISTED.
    if cand["listing_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Candidate is not in DRAFT")
    # Business safety: requires a FINALIZED score and ACTIVE medical status.
    if cand["current_meld_peld"] <= 0:
        raise err("ERR_NO_FINALIZED_SCORE", "Candidate has no finalized clinical score")
    if cand["medical_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Candidate medical_status must be ACTIVE to list")
    now = db.clock
    cand["listing_status"] = "LISTED"
    cand["listed_at"] = format_iso(now)
    cand["is_pediatric"] = services.compute_is_pediatric(cand, now)
    services.open_accrual_interval(cand, format_iso(now))
    # Create the ACTIVE waitlist registration.
    reg = base_fields()
    reg.update({
        "candidate_id": cand["id"], "organ_type": cand["organ_type"],
        "status": "ACTIVE", "suspended_at": None, "withdrawn_reason": None,
    })
    db.registrations[reg["id"]] = reg
    touch(cand)
    return success(services.serialize_candidate(cand), 200)


@app.route("/candidates/<rid>/deactivate", methods=["POST"])
def deactivate_candidate(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    cand = find_or_404(db.candidates, rid)
    candidate_owner_check(cand, user_id, role)
    # State: medical ACTIVE -> INACTIVE, only while listing in {DRAFT, LISTED}.
    if cand["medical_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Candidate is not ACTIVE")
    if cand["listing_status"] not in ("DRAFT", "LISTED"):
        raise err("ERR_INVALID_STATE", "Candidate listing_status forbids deactivate")
    now = db.clock
    cand["medical_status"] = "INACTIVE"
    if cand["listing_status"] == "LISTED":
        services.close_accrual_interval(cand, format_iso(now))
        for reg in db.registrations.values():
            if reg["candidate_id"] == cand["id"] and reg["status"] == "ACTIVE":
                reg["status"] = "SUSPENDED"
                reg["suspended_at"] = format_iso(now)
                touch(reg)
    touch(cand)
    return success(services.serialize_candidate(cand), 200)


@app.route("/candidates/<rid>/reactivate", methods=["POST"])
def reactivate_candidate(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    cand = find_or_404(db.candidates, rid)
    candidate_owner_check(cand, user_id, role)
    if cand["medical_status"] != "INACTIVE":
        raise err("ERR_INVALID_STATE", "Candidate is not INACTIVE")
    if cand["listing_status"] not in ("DRAFT", "LISTED"):
        raise err("ERR_INVALID_STATE", "Candidate listing_status forbids reactivate")
    now = db.clock
    cand["medical_status"] = "ACTIVE"
    if cand["listing_status"] == "LISTED":
        services.open_accrual_interval(cand, format_iso(now))
        for reg in db.registrations.values():
            if reg["candidate_id"] == cand["id"] and reg["status"] == "SUSPENDED":
                reg["status"] = "ACTIVE"
                reg["suspended_at"] = None
                touch(reg)
    touch(cand)
    return success(services.serialize_candidate(cand), 200)


@app.route("/candidates/<rid>/remove", methods=["POST"])
def remove_candidate(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    cand = find_or_404(db.candidates, rid)
    candidate_owner_check(cand, user_id, role)
    body = get_body()
    reason = require_enum(body, "removal_reason", REMOVAL_REASONS)
    # State: LISTED -> REMOVED.
    if cand["listing_status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "Candidate is not LISTED")
    now = db.clock
    cand["listing_status"] = "REMOVED"
    cand["removal_reason"] = reason
    services.close_accrual_interval(cand, format_iso(now))
    # Cascade: ACTIVE registration -> WITHDRAWN.
    for reg in db.registrations.values():
        if reg["candidate_id"] == cand["id"] and reg["status"] == "ACTIVE":
            reg["status"] = "WITHDRAWN"
            reg["withdrawn_reason"] = reason
            touch(reg)
    # Cascade: every OFFERED offer for this candidate -> RESCINDED.
    for offer in db.offers.values():
        if offer["candidate_id"] == cand["id"] and offer["status"] == "OFFERED":
            _rescind_offer(offer)
    # Cascade: invalidate runs that ranked this candidate.
    _invalidate_runs_for_candidate(cand["id"])
    touch(cand)
    return success(services.serialize_candidate(cand), 200)


# ============================================================================
# Clinical Scores
# ============================================================================
@app.route("/candidates/<rid>/clinical-scores", methods=["POST"])
def create_clinical_score(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    cand = find_or_404(db.candidates, rid)
    candidate_owner_check(cand, user_id, role)
    body = get_body()
    bilirubin = require_positive_number(body, "bilirubin_mg_dl")
    inr = require_positive_number(body, "inr")
    creatinine = require_positive_number(body, "creatinine_mg_dl")
    sodium = require_positive_number(body, "sodium_mmol_l")
    albumin = require_positive_number(body, "albumin_g_dl")
    growth_failure = require_bool(body, "growth_failure", False)
    on_dialysis = require_bool(body, "on_dialysis_twice_in_week", False)
    effective_at = require_timestamp(body, "effective_at")
    rec = base_fields()
    rec.update({
        "candidate_id": cand["id"],
        "bilirubin_mg_dl": bilirubin, "inr": inr, "creatinine_mg_dl": creatinine,
        "sodium_mmol_l": sodium, "albumin_g_dl": albumin,
        "growth_failure": growth_failure, "on_dialysis_twice_in_week": on_dialysis,
        "effective_at": format_iso(effective_at),
        "score_kind": None, "raw_score": None, "allocation_score": None,
        "status": "DRAFT",
    })
    db.clinical_scores[rec["id"]] = rec
    return success(public_view(rec), 201)


@app.route("/candidates/<rid>/clinical-scores", methods=["GET"])
def list_clinical_scores(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter"})
    cand = find_or_404(db.candidates, rid)
    items = [s for s in db.clinical_scores.values() if s["candidate_id"] == cand["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(s) for s in page], 200, is_array=True, pagination=pg)


@app.route("/clinical-scores/<rid>", methods=["GET"])
def get_clinical_score(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter"})
    rec = find_or_404(db.clinical_scores, rid)
    return success(public_view(rec), 200)


@app.route("/clinical-scores/<rid>/finalize", methods=["POST"])
def finalize_clinical_score(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    score = find_or_404(db.clinical_scores, rid)
    cand = db.candidates.get(score["candidate_id"])
    if cand is None:
        raise err("ERR_NOT_FOUND", "Parent candidate not found")
    candidate_owner_check(cand, user_id, role)
    # State: DRAFT -> FINALIZED; parent candidate must not be REMOVED.
    if score["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Score is not in DRAFT")
    if cand["listing_status"] == "REMOVED":
        raise err("ERR_INVALID_STATE", "Parent candidate is REMOVED")
    # is_pediatric drives the formula. Use listed_at if listed, else evaluate at
    # the score's effective instant relative to DOB (PRD §3.2 ties pediatric to
    # listing time; before listing, fall back to effective_at for the score).
    if cand.get("is_pediatric") is not None:
        is_pediatric = cand["is_pediatric"]
    else:
        ref = parse_iso(cand["listed_at"]) if cand["listed_at"] else parse_iso(score["effective_at"])
        is_pediatric = services.compute_is_pediatric(cand, ref)
    if is_pediatric:
        raw, allocation = calc.peld_score(
            score["bilirubin_mg_dl"], score["inr"],
            score["albumin_g_dl"], score["growth_failure"])
        score["score_kind"] = "PELD"
    else:
        raw, allocation = calc.meld_na_score(
            score["bilirubin_mg_dl"], score["inr"], score["creatinine_mg_dl"],
            score["sodium_mmol_l"], score["on_dialysis_twice_in_week"])
        score["score_kind"] = "MELD_NA"
    score["raw_score"] = calc.to_number(raw)
    score["allocation_score"] = allocation
    score["status"] = "FINALIZED"
    touch(score)
    # Supersede prior FINALIZED for this candidate.
    for other in db.clinical_scores.values():
        if (other["id"] != score["id"] and other["candidate_id"] == cand["id"]
                and other["status"] == "FINALIZED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    # Recompute current_meld_peld = most-recent FINALIZED by effective_at (tie created_at).
    _recompute_current_meld_peld(cand)
    touch(cand)
    return success(public_view(score), 200)


def _recompute_current_meld_peld(cand):
    finalized = [s for s in db.clinical_scores.values()
                 if s["candidate_id"] == cand["id"] and s["status"] == "FINALIZED"]
    if not finalized:
        cand["current_meld_peld"] = 0
        return
    finalized.sort(key=lambda s: (parse_iso(s["effective_at"]), s["created_at"], s["_seq"]))
    cand["current_meld_peld"] = finalized[-1]["allocation_score"]


# ============================================================================
# Waitlist Registrations
# ============================================================================
@app.route("/candidates/<rid>/registrations", methods=["GET"])
def list_registrations(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter", "OrganProcurementOrg"})
    cand = find_or_404(db.candidates, rid)
    items = [r for r in db.registrations.values() if r["candidate_id"] == cand["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(r) for r in page], 200, is_array=True, pagination=pg)


# ============================================================================
# Donor Organs
# ============================================================================
@app.route("/donor-organs", methods=["POST"])
def create_donor_organ():
    user_id, role = authenticate()
    require_role(role, {"OrganProcurementOrg"})
    body = get_body()
    opo_id = body.get("opo_id")
    if not isinstance(opo_id, str) or opo_id not in db.opos:
        if not isinstance(opo_id, str):
            raise err("ERR_INVALID_REQUEST", "opo_id required")
        raise err("ERR_NOT_FOUND", "opo_id does not resolve")
    if opo_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting OPO does not own this organ")
    organ_type = require_enum(body, "organ_type", ORGAN_TYPES)
    blood_type = require_enum(body, "blood_type", BLOOD_TYPES)
    height = require_positive_number(body, "donor_height_cm")
    weight = require_positive_number(body, "donor_weight_kg")
    hla_a = require_hla_array(body, "hla_a")
    hla_b = require_hla_array(body, "hla_b")
    hla_dr = require_hla_array(body, "hla_dr")
    recovered_at = require_timestamp(body, "recovered_at")
    max_ci = require_positive_number(body, "max_cold_ischemia_hours")
    rec = base_fields()
    rec.update({
        "opo_id": opo_id, "organ_type": organ_type, "blood_type": blood_type,
        "donor_height_cm": height, "donor_weight_kg": weight,
        "hla_a": hla_a, "hla_b": hla_b, "hla_dr": hla_dr,
        "recovered_at": format_iso(recovered_at), "max_cold_ischemia_hours": max_ci,
        "status": "AVAILABLE", "open_offer_count": 0,
    })
    db.donor_organs[rec["id"]] = rec
    return success(public_view(rec), 201)


@app.route("/donor-organs", methods=["GET"])
def list_donor_organs():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "OrganProcurementOrg", "TransplantCenter"})
    items = list(db.donor_organs.values())
    opo_id = request.args.get("opo_id")
    organ_type = request.args.get("organ_type")
    status = request.args.get("status")
    if opo_id is not None:
        items = [o for o in items if o["opo_id"] == opo_id]
    if organ_type is not None:
        items = [o for o in items if o["organ_type"] == organ_type]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(o) for o in page], 200, is_array=True, pagination=pg)


@app.route("/donor-organs/<rid>", methods=["GET"])
def get_donor_organ(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "OrganProcurementOrg", "TransplantCenter"})
    rec = find_or_404(db.donor_organs, rid)
    return success(public_view(rec), 200)


@app.route("/donor-organs/<rid>/discard", methods=["POST"])
def discard_donor_organ(rid):
    user_id, role = authenticate()
    require_role(role, {"OrganProcurementOrg"})
    organ = find_or_404(db.donor_organs, rid)
    if role == "OrganProcurementOrg" and organ["opo_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting OPO does not own this organ")
    status = organ["status"]
    if status == "AVAILABLE":
        organ["status"] = "DISCARDED"
        touch(organ)
        return success(public_view(organ), 200)
    if status == "MATCHING":
        now = db.clock
        recovered = parse_iso(organ["recovered_at"])
        ischemia_end = add_hours(recovered, organ["max_cold_ischemia_hours"])
        has_open_or_accepted = any(
            o["donor_organ_id"] == organ["id"] and o["status"] in ("OFFERED", "ACCEPTED")
            for o in db.offers.values())
        if not (now > ischemia_end or not has_open_or_accepted):
            raise err("ERR_INVALID_STATE",
                      "Cannot discard MATCHING organ while viable with open/accepted offers")
        # Cascade: OFFERED offers -> EXPIRED (each decrements open_offer_count).
        for offer in db.offers.values():
            if offer["donor_organ_id"] == organ["id"] and offer["status"] == "OFFERED":
                offer["status"] = "EXPIRED"
                organ["open_offer_count"] = max(0, organ["open_offer_count"] - 1)
                touch(offer)
        # Cascade: the organ's match run(s) -> INVALIDATED.
        for run in db.match_runs.values():
            if run["donor_organ_id"] == organ["id"] and run["status"] == "COMPLETED":
                run["status"] = "INVALIDATED"
                touch(run)
        organ["status"] = "DISCARDED"
        touch(organ)
        return success(public_view(organ), 200)
    raise err("ERR_INVALID_STATE", "Organ cannot be discarded from status %s" % status)


# ============================================================================
# Match Runs
# ============================================================================
def _build_eligible_pool(organ, policy_code):
    """Return list of (candidate, priority_points, hla_mismatch) eligible
    for this organ under the policy, sorted into ranked order (PRD §3.5)."""
    opo = db.opos.get(organ["opo_id"])
    organ_region = opo["region_code"] if opo else None
    broader = policy_code == "BROADER_SHARING"
    pool = []
    for cand in db.candidates.values():
        if cand["listing_status"] != "LISTED":
            continue
        if cand["medical_status"] != "ACTIVE":
            continue
        if cand["organ_type"] != organ["organ_type"]:
            continue
        if not calc.abo_compatible(organ["blood_type"], cand["blood_type"]):
            continue
        if not calc.size_compatible(organ["donor_weight_kg"], cand["weight_kg"], cand["organ_type"]):
            continue
        donor_antigens = set(organ["hla_a"]) | set(organ["hla_b"]) | set(organ["hla_dr"])
        if donor_antigens & set(cand.get("unacceptable_antigens", [])):
            continue
        center = db.transplant_centers.get(cand["center_id"])
        cand_region = center["region_code"] if center else None
        out_of_region = cand_region != organ_region
        if not broader and out_of_region:
            continue
        mismatch = calc.hla_mismatch_count(organ, cand)
        wait_days = services.waiting_time_days(cand)
        pts = calc.allocation_priority_points(
            cand["current_meld_peld"], wait_days, mismatch,
            bool(cand.get("is_pediatric")), out_of_region, broader)
        pool.append({
            "candidate": cand, "priority_points": pts,
            "hla_mismatch": mismatch, "wait_days": wait_days,
        })
    # Rank: DESC priority_points; tie -> higher current_meld_peld; tie -> more
    # waiting_time_days; tie -> earlier created_at.
    pool.sort(key=lambda e: (
        -e["priority_points"],
        -e["candidate"]["current_meld_peld"],
        -e["wait_days"],
        e["candidate"]["created_at"],
        e["candidate"]["_seq"],
    ))
    return pool


@app.route("/match-runs", methods=["POST"])
def create_match_run():
    user_id, role = authenticate()
    require_role(role, {"OrganProcurementOrg"})
    body = get_body()
    organ_id = body.get("donor_organ_id")
    if not isinstance(organ_id, str) or organ_id not in db.donor_organs:
        if not isinstance(organ_id, str):
            raise err("ERR_INVALID_REQUEST", "donor_organ_id required")
        raise err("ERR_NOT_FOUND", "donor_organ_id does not resolve")
    organ = db.donor_organs[organ_id]
    if role == "OrganProcurementOrg" and organ["opo_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting OPO does not own this organ")
    expected_version = require_int_range_any(body, "expected_donor_organ_version")
    policy_code = require_enum(body, "policy_code", POLICY_CODES)
    # OCC before state: a prior run/discard that advanced the version (and so
    # also moved the organ off AVAILABLE) is reported as a stale-version write
    # (PRD §2.7 — "a prior run has already advanced the version ... rejected
    # with ERR_STALE_ORGAN_VERSION").
    if expected_version != organ["version"]:
        raise err("ERR_STALE_ORGAN_VERSION", "Stale donor organ version")
    # State: organ must be AVAILABLE.
    if organ["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Organ is not AVAILABLE")
    pool = _build_eligible_pool(organ, policy_code)
    run = base_fields()
    run.update({
        "donor_organ_id": organ_id,
        "expected_donor_organ_version": expected_version,
        "policy_code": policy_code,
        "ranked_count": len(pool),
        "status": "COMPLETED",
    })
    db.match_runs[run["id"]] = run
    for idx, entry in enumerate(pool):
        mle = base_fields(full=False)
        mle.update({
            "match_run_id": run["id"],
            "candidate_id": entry["candidate"]["id"],
            "rank": idx + 1,
            "priority_points": entry["priority_points"],
            "hla_mismatch_count": entry["hla_mismatch"],
        })
        db.match_list_entries[mle["id"]] = mle
    # Side effect: organ AVAILABLE -> MATCHING, version++.
    organ["status"] = "MATCHING"
    touch(organ)
    # The donor organ's version is the OCC token threaded through allocation;
    # surface the post-run organ version on the run so callers can chain it into
    # the next organ-touching operation (PRD §2.7).
    run["version"] = organ["version"]
    db.match_runs[run["id"]] = run
    return success(public_view(run), 201)


def require_int_range_any(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer" % field)
    return v


@app.route("/match-runs/<rid>", methods=["GET"])
def get_match_run(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "OrganProcurementOrg", "TransplantCenter"})
    rec = find_or_404(db.match_runs, rid)
    return success(public_view(rec), 200)


@app.route("/match-runs", methods=["GET"])
def list_match_runs():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "OrganProcurementOrg", "TransplantCenter"})
    items = list(db.match_runs.values())
    donor_organ_id = request.args.get("donor_organ_id")
    status = request.args.get("status")
    if donor_organ_id is not None:
        items = [r for r in items if r["donor_organ_id"] == donor_organ_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(r) for r in page], 200, is_array=True, pagination=pg)


@app.route("/match-runs/<rid>/entries", methods=["GET"])
def list_match_run_entries(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "OrganProcurementOrg", "TransplantCenter"})
    run = find_or_404(db.match_runs, rid)
    items = [e for e in db.match_list_entries.values() if e["match_run_id"] == run["id"]]
    items.sort(key=lambda e: (e["rank"], e["_seq"]))
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(e) for e in page], 200, is_array=True, pagination=pg)


@app.route("/match-list-entries/<rid>", methods=["GET"])
def get_match_list_entry(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "OrganProcurementOrg", "TransplantCenter"})
    rec = find_or_404(db.match_list_entries, rid)
    return success(public_view(rec), 200)


@app.route("/match-list-entries", methods=["GET"])
def list_match_list_entries():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "OrganProcurementOrg", "TransplantCenter"})
    items = list(db.match_list_entries.values())
    candidate_id = request.args.get("candidate_id")
    match_run_id = request.args.get("match_run_id")
    if candidate_id is not None:
        items = [e for e in items if e["candidate_id"] == candidate_id]
    if match_run_id is not None:
        items = [e for e in items if e["match_run_id"] == match_run_id]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(e) for e in page], 200, is_array=True, pagination=pg)


# ============================================================================
# Offers — shared issuance gate
# ============================================================================
def _compute_response_deadline(organ, offered_at):
    window_end = add_hours(offered_at, calc.OFFER_RESPONSE_WINDOW_HOURS)
    recovered = parse_iso(organ["recovered_at"])
    ischemia_end = add_hours(recovered, organ["max_cold_ischemia_hours"])
    return min(window_end, ischemia_end)


def _issue_offer(organ, cand, run, rank_at_offer):
    """Run the shared compatibility/timing battery and create an OFFERED offer.
    Caller has already validated state/OCC. Order per PRD §3.7."""
    # Organ type.
    if organ["organ_type"] != cand["organ_type"]:
        raise err("ERR_ORGAN_TYPE_MISMATCH", "Organ type does not match candidate")
    # ABO.
    if not calc.abo_compatible(organ["blood_type"], cand["blood_type"]):
        raise err("ERR_ABO_INCOMPATIBLE", "ABO incompatible")
    # Virtual crossmatch.
    donor_antigens = set(organ["hla_a"]) | set(organ["hla_b"]) | set(organ["hla_dr"])
    if donor_antigens & set(cand.get("unacceptable_antigens", [])):
        raise err("ERR_POSITIVE_CROSSMATCH", "Positive virtual crossmatch")
    # Size.
    if not calc.size_compatible(organ["donor_weight_kg"], cand["weight_kg"], cand["organ_type"]):
        raise err("ERR_SIZE_INCOMPATIBLE", "Size incompatible")
    # Viability window.
    now = db.clock
    offered_at = now
    deadline = _compute_response_deadline(organ, offered_at)
    if not (deadline > offered_at):
        raise err("ERR_ISCHEMIA_WINDOW_CLOSED", "Cold-ischemia window already closed")
    # At most one open offer per (organ, candidate).
    for o in db.offers.values():
        if (o["donor_organ_id"] == organ["id"] and o["candidate_id"] == cand["id"]
                and o["status"] == "OFFERED"):
            raise err("ERR_DUPLICATE_OPEN_OFFER", "Candidate already holds an open offer")
    offer = base_fields()
    offer.update({
        "donor_organ_id": organ["id"], "candidate_id": cand["id"],
        "match_run_id": run["id"], "expected_donor_organ_version": organ["version"],
        "rank_at_offer": rank_at_offer, "offered_at": format_iso(offered_at),
        "response_deadline_at": format_iso(deadline),
        "status": "OFFERED", "decline_reason": None,
    })
    db.offers[offer["id"]] = offer
    organ["open_offer_count"] += 1
    touch(organ)  # increments organ version
    # Surface the post-issuance organ version on the offer (OCC token; PRD §2.7).
    offer["version"] = organ["version"]
    return offer


@app.route("/offers", methods=["POST"])
def create_offer():
    user_id, role = authenticate()
    require_role(role, {"OrganProcurementOrg"})
    body = get_body()
    # Existence, left-to-right: donor_organ_id, candidate_id, match_run_id.
    organ_id = body.get("donor_organ_id")
    if not isinstance(organ_id, str) or organ_id not in db.donor_organs:
        if not isinstance(organ_id, str):
            raise err("ERR_INVALID_REQUEST", "donor_organ_id required")
        raise err("ERR_NOT_FOUND", "donor_organ_id does not resolve")
    cand_id = body.get("candidate_id")
    if not isinstance(cand_id, str) or cand_id not in db.candidates:
        if not isinstance(cand_id, str):
            raise err("ERR_INVALID_REQUEST", "candidate_id required")
        raise err("ERR_NOT_FOUND", "candidate_id does not resolve")
    run_id = body.get("match_run_id")
    if not isinstance(run_id, str) or run_id not in db.match_runs:
        if not isinstance(run_id, str):
            raise err("ERR_INVALID_REQUEST", "match_run_id required")
        raise err("ERR_NOT_FOUND", "match_run_id does not resolve")
    organ = db.donor_organs[organ_id]
    cand = db.candidates[cand_id]
    run = db.match_runs[run_id]
    if role == "OrganProcurementOrg" and organ["opo_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting OPO does not own this organ")
    expected_version = require_int_range_any(body, "expected_donor_organ_version")
    # State: organ must be MATCHING to issue an offer.
    if organ["status"] != "MATCHING":
        raise err("ERR_INVALID_STATE", "Organ is not MATCHING")
    # OCC.
    if expected_version != organ["version"]:
        raise err("ERR_STALE_ORGAN_VERSION", "Stale donor organ version")
    rank_at_offer = _rank_for(run["id"], cand["id"])
    offer = _issue_offer(organ, cand, run, rank_at_offer)
    return success(public_view(offer), 201)


def _rank_for(run_id, candidate_id):
    for e in db.match_list_entries.values():
        if e["match_run_id"] == run_id and e["candidate_id"] == candidate_id:
            return e["rank"]
    return None


@app.route("/donor-organs/<rid>/offer-next", methods=["POST"])
def offer_next(rid):
    user_id, role = authenticate()
    require_role(role, {"OrganProcurementOrg"})
    organ = find_or_404(db.donor_organs, rid)
    if role == "OrganProcurementOrg" and organ["opo_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting OPO does not own this organ")
    body = get_body()
    expected_version = require_int_range_any(body, "expected_donor_organ_version")
    # State: organ must be MATCHING.
    if organ["status"] != "MATCHING":
        raise err("ERR_INVALID_STATE", "Organ is not MATCHING")
    # OCC.
    if expected_version != organ["version"]:
        raise err("ERR_STALE_ORGAN_VERSION", "Stale donor organ version")
    # Find the organ's latest COMPLETED run.
    runs = [r for r in db.match_runs.values()
            if r["donor_organ_id"] == organ["id"] and r["status"] == "COMPLETED"]
    runs = sorted_by_created(runs)
    if not runs:
        raise err("ERR_NO_NEXT_CANDIDATE", "No completed run for this organ")
    run = runs[-1]
    entries = [e for e in db.match_list_entries.values() if e["match_run_id"] == run["id"]]
    entries.sort(key=lambda e: (e["rank"], e["_seq"]))
    # Next-ranked eligible candidate who does not yet hold a terminal offer for
    # this organ and no current OFFERED offer.
    chosen = None
    for e in entries:
        cand = db.candidates.get(e["candidate_id"])
        if cand is None:
            continue
        offers_for = [o for o in db.offers.values()
                      if o["donor_organ_id"] == organ["id"] and o["candidate_id"] == cand["id"]]
        if any(o["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "RESCINDED")
               for o in offers_for):
            continue
        chosen = (cand, e["rank"])
        break
    if chosen is None:
        raise err("ERR_NO_NEXT_CANDIDATE", "No further eligible un-offered candidate")
    cand, rank_at_offer = chosen
    offer = _issue_offer(organ, cand, run, rank_at_offer)
    return success(public_view(offer), 201)


@app.route("/offers/<rid>", methods=["GET"])
def get_offer(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "OrganProcurementOrg", "TransplantCenter"})
    rec = find_or_404(db.offers, rid)
    return success(public_view(rec), 200)


@app.route("/offers", methods=["GET"])
def list_offers():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "OrganProcurementOrg", "TransplantCenter"})
    items = list(db.offers.values())
    for param, key in (("donor_organ_id", "donor_organ_id"),
                       ("candidate_id", "candidate_id"),
                       ("match_run_id", "match_run_id"),
                       ("status", "status")):
        val = request.args.get(param)
        if val is not None:
            items = [o for o in items if o[key] == val]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(o) for o in page], 200, is_array=True, pagination=pg)


@app.route("/offers/<rid>/accept", methods=["POST"])
def accept_offer(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    offer = find_or_404(db.offers, rid)
    offer_owner_check(offer, user_id, role)
    body = get_body()
    expected_version = require_int_range_any(body, "expected_donor_organ_version")
    organ = db.donor_organs.get(offer["donor_organ_id"])
    cand = db.candidates.get(offer["candidate_id"])
    # State: offer must be OFFERED.
    if offer["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Offer is not OFFERED")
    # Window: now <= deadline.
    now = db.clock
    deadline = parse_iso(offer["response_deadline_at"])
    if now > deadline:
        raise err("ERR_OFFER_WINDOW_CLOSED", "Response window closed")
    # Candidate readiness.
    if cand["medical_status"] != "ACTIVE" or cand["listing_status"] != "LISTED":
        raise err("ERR_CANDIDATE_NOT_ACTIVE", "Candidate is not active and listed")
    # Organ MATCHING.
    if organ["status"] != "MATCHING":
        raise err("ERR_INVALID_STATE", "Organ is not MATCHING")
    # OCC.
    if expected_version != organ["version"]:
        raise err("ERR_STALE_ORGAN_VERSION", "Stale donor organ version")
    # ----- Cascade -----
    offer["status"] = "ACCEPTED"
    organ["open_offer_count"] = max(0, organ["open_offer_count"] - 1)
    touch(offer)
    # Organ MATCHING -> ALLOCATED: rescind sibling OFFERED offers, then ooc=0.
    for sib in db.offers.values():
        if (sib["id"] != offer["id"] and sib["donor_organ_id"] == organ["id"]
                and sib["status"] == "OFFERED"):
            sib["status"] = "RESCINDED"
            organ["open_offer_count"] = max(0, organ["open_offer_count"] - 1)
            touch(sib)
    organ["status"] = "ALLOCATED"
    organ["open_offer_count"] = 0
    touch(organ)  # version++
    # Candidate LISTED -> TRANSPLANTED.
    cand["listing_status"] = "TRANSPLANTED"
    cand["removal_reason"] = "TRANSPLANTED"
    services.close_accrual_interval(cand, format_iso(now))
    for reg in db.registrations.values():
        if reg["candidate_id"] == cand["id"] and reg["status"] == "ACTIVE":
            reg["status"] = "WITHDRAWN"
            reg["withdrawn_reason"] = "TRANSPLANTED"
            touch(reg)
    touch(cand)
    # The offer's match run -> INVALIDATED.
    run = db.match_runs.get(offer["match_run_id"])
    if run is not None and run["status"] == "COMPLETED":
        run["status"] = "INVALIDATED"
        touch(run)
    # Surface the post-accept organ version on the offer (OCC token; PRD §2.7).
    offer["version"] = organ["version"]
    return success(public_view(offer), 200)


@app.route("/offers/<rid>/decline", methods=["POST"])
def decline_offer(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    offer = find_or_404(db.offers, rid)
    offer_owner_check(offer, user_id, role)
    body = get_body()
    reason = require_enum(body, "decline_reason", DECLINE_REASONS)
    if offer["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Offer is not OFFERED")
    offer["status"] = "DECLINED"
    offer["decline_reason"] = reason
    organ = db.donor_organs.get(offer["donor_organ_id"])
    if organ is not None:
        organ["open_offer_count"] = max(0, organ["open_offer_count"] - 1)
        touch_no_version(organ)  # decline does not advance organ OCC token
    touch(offer)
    return success(public_view(offer), 200)


@app.route("/offers/<rid>/expire", methods=["POST"])
def expire_offer(rid):
    user_id, role = authenticate()
    require_role(role, {"OrganProcurementOrg"})
    offer = find_or_404(db.offers, rid)
    organ = db.donor_organs.get(offer["donor_organ_id"])
    if role == "OrganProcurementOrg" and organ is not None and organ["opo_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting OPO does not own this organ")
    if offer["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Offer is not OFFERED")
    now = db.clock
    deadline = parse_iso(offer["response_deadline_at"])
    if not (now > deadline):
        raise err("ERR_OFFER_WINDOW_OPEN", "Response window still open")
    offer["status"] = "EXPIRED"
    if organ is not None:
        organ["open_offer_count"] = max(0, organ["open_offer_count"] - 1)
        touch_no_version(organ)  # expire does not advance organ OCC token
    touch(offer)
    return success(public_view(offer), 200)


# ============================================================================
# Cascade helpers shared by candidate remove / organ discard
# ============================================================================
def _rescind_offer(offer):
    offer["status"] = "RESCINDED"
    organ = db.donor_organs.get(offer["donor_organ_id"])
    if organ is not None:
        organ["open_offer_count"] = max(0, organ["open_offer_count"] - 1)
        touch_no_version(organ)  # rescission does not advance organ OCC token
    touch(offer)


def _invalidate_runs_for_candidate(candidate_id):
    run_ids = set(e["match_run_id"] for e in db.match_list_entries.values()
                  if e["candidate_id"] == candidate_id)
    for run_id in run_ids:
        run = db.match_runs.get(run_id)
        if run is not None and run["status"] == "COMPLETED":
            run["status"] = "INVALIDATED"
            touch(run)


# ============================================================================
# Transplants
# ============================================================================
@app.route("/transplants", methods=["POST"])
def create_transplant():
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    body = get_body()
    offer_id = body.get("offer_id")
    if not isinstance(offer_id, str) or offer_id not in db.offers:
        if not isinstance(offer_id, str):
            raise err("ERR_INVALID_REQUEST", "offer_id required")
        raise err("ERR_NOT_FOUND", "offer_id does not resolve")
    offer = db.offers[offer_id]
    offer_owner_check(offer, user_id, role)
    transplanted_at = require_timestamp(body, "transplanted_at")
    # Business: offer ACCEPTED and no existing transplant for it.
    if offer["status"] != "ACCEPTED":
        raise err("ERR_OFFER_NOT_ACCEPTED", "Offer is not ACCEPTED")
    for t in db.transplants.values():
        if t["offer_id"] == offer_id:
            raise err("ERR_OFFER_NOT_ACCEPTED", "Transplant already exists for this offer")
    organ = db.donor_organs.get(offer["donor_organ_id"])
    recovered = parse_iso(organ["recovered_at"])
    ci = calc.cold_ischemia_hours_actual(recovered, transplanted_at)
    rec = base_fields()
    rec.update({
        "offer_id": offer_id,
        "candidate_id": offer["candidate_id"],
        "donor_organ_id": offer["donor_organ_id"],
        "transplanted_at": format_iso(transplanted_at),
        "cold_ischemia_hours_actual": ci,
        "graft_status": "FUNCTIONING",
    })
    db.transplants[rec["id"]] = rec
    # Organ ALLOCATED -> TRANSPLANTED, version++.
    if organ is not None and organ["status"] == "ALLOCATED":
        organ["status"] = "TRANSPLANTED"
        touch(organ)
    return success(public_view(rec), 201)


@app.route("/transplants/<rid>", methods=["GET"])
def get_transplant(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter"})
    rec = find_or_404(db.transplants, rid)
    return success(public_view(rec), 200)


@app.route("/transplants", methods=["GET"])
def list_transplants():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter", "OrganProcurementOrg"})
    items = list(db.transplants.values())
    for param in ("offer_id", "candidate_id", "donor_organ_id"):
        val = request.args.get(param)
        if val is not None:
            items = [t for t in items if t[param] == val]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(t) for t in page], 200, is_array=True, pagination=pg)


@app.route("/transplants/<rid>/mark-graft-failed", methods=["POST"])
def mark_graft_failed(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    tx = find_or_404(db.transplants, rid)
    transplant_owner_check(tx, user_id, role)
    if tx["graft_status"] != "AT_RISK":
        raise err("ERR_INVALID_STATE", "Graft is not AT_RISK")
    tx["graft_status"] = "FAILED"
    touch(tx)
    return success(public_view(tx), 200)


# ============================================================================
# Follow-ups
# ============================================================================
@app.route("/transplants/<rid>/follow-ups", methods=["POST"])
def create_follow_up(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    tx = find_or_404(db.transplants, rid)
    transplant_owner_check(tx, user_id, role)
    body = get_body()
    interval_label = require_enum(body, "interval_label", INTERVAL_LABELS)
    scheduled_for = require_timestamp(body, "scheduled_for")
    graft_functioning = require_bool(body, "graft_functioning", True)
    # Business-temporal: scheduled_for >= transplanted_at.
    transplanted_at = parse_iso(tx["transplanted_at"])
    if scheduled_for < transplanted_at:
        raise err("ERR_FOLLOWUP_BEFORE_TRANSPLANT", "Follow-up precedes transplant")
    rec = base_fields()
    rec.update({
        "transplant_id": tx["id"], "interval_label": interval_label,
        "scheduled_for": format_iso(scheduled_for),
        "graft_functioning": graft_functioning, "status": "SCHEDULED",
    })
    db.follow_ups[rec["id"]] = rec
    return success(public_view(rec), 201)


@app.route("/transplants/<rid>/follow-ups", methods=["GET"])
def list_follow_ups(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter"})
    tx = find_or_404(db.transplants, rid)
    items = [f for f in db.follow_ups.values() if f["transplant_id"] == tx["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(f) for f in page], 200, is_array=True, pagination=pg)


@app.route("/follow-ups/<rid>", methods=["GET"])
def get_follow_up(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter"})
    rec = find_or_404(db.follow_ups, rid)
    return success(public_view(rec), 200)


@app.route("/follow-ups/<rid>/complete", methods=["POST"])
def complete_follow_up(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    fu = find_or_404(db.follow_ups, rid)
    tx = db.transplants.get(fu["transplant_id"])
    transplant_owner_check(tx, user_id, role)
    if fu["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Follow-up is not SCHEDULED")
    if tx["graft_status"] == "FAILED":
        raise err("ERR_INVALID_STATE", "Parent transplant graft has FAILED")
    fu["status"] = "COMPLETED"
    touch(fu)
    if fu["graft_functioning"] is False and tx["graft_status"] == "FUNCTIONING":
        tx["graft_status"] = "AT_RISK"
        touch(tx)
    elif fu["graft_functioning"] is True and tx["graft_status"] == "AT_RISK":
        tx["graft_status"] = "FUNCTIONING"
        touch(tx)
    return success(public_view(fu), 200)


@app.route("/follow-ups/<rid>/mark-missed", methods=["POST"])
def mark_follow_up_missed(rid):
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    fu = find_or_404(db.follow_ups, rid)
    tx = db.transplants.get(fu["transplant_id"])
    transplant_owner_check(tx, user_id, role)
    if fu["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Follow-up is not SCHEDULED")
    now = db.clock
    scheduled_for = parse_iso(fu["scheduled_for"])
    if not (now > scheduled_for):
        raise err("ERR_INVALID_STATE", "Clock has not passed scheduled_for")
    fu["status"] = "MISSED"
    touch(fu)
    return success(public_view(fu), 200)


# ============================================================================
# UNOS Reports
# ============================================================================
@app.route("/unos-reports", methods=["POST"])
def create_unos_report():
    user_id, role = authenticate()
    require_role(role, {"TransplantCenter"})
    body = get_body()
    report_kind = require_enum(body, "report_kind", REPORT_KINDS)
    transplant_id = body.get("transplant_id")
    candidate_id = body.get("candidate_id")
    # Existence left-to-right for any supplied FK (PRD §2.6).
    if transplant_id is not None:
        if not isinstance(transplant_id, str) or transplant_id not in db.transplants:
            raise err("ERR_NOT_FOUND", "transplant_id does not resolve")
    if candidate_id is not None:
        if not isinstance(candidate_id, str) or candidate_id not in db.candidates:
            raise err("ERR_NOT_FOUND", "candidate_id does not resolve")
    # Subject consistency (PRD §3.10).
    if report_kind in ("TRANSPLANT", "FOLLOWUP"):
        if not transplant_id or transplant_id not in db.transplants:
            raise err("ERR_REPORT_SUBJECT_INVALID", "transplant_id required for this kind")
    elif report_kind == "REMOVAL":
        if not candidate_id or candidate_id not in db.candidates:
            raise err("ERR_REPORT_SUBJECT_INVALID", "candidate_id required for REMOVAL")
        if db.candidates[candidate_id]["listing_status"] != "REMOVED":
            raise err("ERR_REPORT_SUBJECT_INVALID", "REMOVAL candidate is not REMOVED")
    rec = base_fields()
    rec.update({
        "report_kind": report_kind,
        "transplant_id": transplant_id if transplant_id is not None else None,
        "candidate_id": candidate_id if candidate_id is not None else None,
        "submitted_at": format_iso(db.clock),
        "status": "SUBMITTED", "rejection_reason": None,
    })
    db.unos_reports[rec["id"]] = rec
    return success(public_view(rec), 201)


@app.route("/unos-reports/<rid>", methods=["GET"])
def get_unos_report(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter"})
    rec = find_or_404(db.unos_reports, rid)
    return success(public_view(rec), 200)


@app.route("/unos-reports", methods=["GET"])
def list_unos_reports():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter"})
    items = list(db.unos_reports.values())
    for param in ("transplant_id", "candidate_id", "report_kind", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r.get(param) == val]
    items = sorted_by_created(items)
    limit, offset = parse_pagination()
    page, pg = paginate(items, limit, offset)
    return success([public_view(r) for r in page], 200, is_array=True, pagination=pg)


@app.route("/unos-reports/<rid>/accept", methods=["POST"])
def accept_unos_report(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin"})
    rec = find_or_404(db.unos_reports, rid)
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Report is not SUBMITTED")
    # Subject still validates.
    if rec["report_kind"] in ("TRANSPLANT", "FOLLOWUP"):
        if not rec["transplant_id"] or rec["transplant_id"] not in db.transplants:
            raise err("ERR_REPORT_SUBJECT_INVALID", "Referenced transplant missing")
    elif rec["report_kind"] == "REMOVAL":
        cand = db.candidates.get(rec["candidate_id"])
        if cand is None or cand["listing_status"] != "REMOVED":
            raise err("ERR_REPORT_SUBJECT_INVALID", "Removal candidate not REMOVED")
    rec["status"] = "ACCEPTED"
    touch(rec)
    return success(public_view(rec), 200)


@app.route("/unos-reports/<rid>/reject", methods=["POST"])
def reject_unos_report(rid):
    _, role = authenticate()
    require_role(role, {"UNOSAdmin"})
    rec = find_or_404(db.unos_reports, rid)
    body = get_body()
    reason = require_str(body, "rejection_reason")
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Report is not SUBMITTED")
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = reason
    touch(rec)
    return success(public_view(rec), 200)


# ============================================================================
# Deterministic clock (PRD §2.5)
# ============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin"})
    body = get_body()
    target = require_timestamp(body, "to_iso8601")
    db.clock = target
    return success({"current_utc": format_iso(db.clock)}, 200)


@app.route("/_clock", methods=["GET"])
def get_clock():
    _, role = authenticate()
    require_role(role, {"UNOSAdmin", "TransplantCenter", "OrganProcurementOrg"})
    return success({"current_utc": format_iso(db.clock)}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
