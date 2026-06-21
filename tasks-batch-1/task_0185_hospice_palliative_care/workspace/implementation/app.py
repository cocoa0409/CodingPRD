"""Hospice & Palliative Care API — Flask entry point.

Implements the PRD verbatim. In-memory storage only (db.py). No seeded data.
"""
import os
from datetime import timedelta

from flask import Flask, request

import db
import services as svc
from errors import (
    ApiError, err,
    ERR_RESOURCE_NOT_FOUND, ERR_ELECTION_NOT_ELECTED, ERR_CAP_YEAR_SETTLED,
    ERR_PERIOD_SEQUENCE_MISMATCH, ERR_FACE_TO_FACE_REQUIRED,
    ERR_CERTIFICATION_INCOMPLETE, ERR_IDG_INCOMPLETE, ERR_ITEM_NOT_COVERED,
    ERR_PLAN_NOT_ACTIVE, ERR_SERVICE_DATE_OUT_OF_RANGE,
    ERR_RESPITE_LIMIT_EXCEEDED, ERR_INTENSITY_FLAG_MISMATCH,
    ERR_DUPLICATE_CARE_DAY, ERR_BEREAVEMENT_NOT_ELIGIBLE,
    ERR_STALE_ELECTION_VERSION, ERR_INVALID_REQUEST,
)
from middleware import require_role
from response import success, list_response, error_response
import util

app = Flask(__name__)

IDG_CORE = {"PHYSICIAN", "NURSE", "SOCIAL_WORK", "COUNSELOR"}
IDG_ALL = {"PHYSICIAN", "NURSE", "SOCIAL_WORK", "COUNSELOR", "AIDE", "VOLUNTEER"}
LOC_SET = {"ROUTINE", "RESPITE", "GIP"}
ITEM_TYPES = {"MEDICATION", "DME"}
DISCHARGE_REASONS = {"DEATH", "MOVED_OUT_OF_AREA", "NO_LONGER_TERMINAL"}


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_RESOURCE_NOT_FOUND[0], "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_RESOURCE_NOT_FOUND[0], "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INTERNAL", str(e), 500)


# --------------------------------------------------------------------------
# Existence helpers (404)
# --------------------------------------------------------------------------
def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Resource not found: %s" % rid)
    return rec


# --------------------------------------------------------------------------
# Clock-driven expiry auto-transition (PRD §3.9, §3.12)
# --------------------------------------------------------------------------
def apply_expiry_transitions():
    """Auto-transition to EXPIRED any ELECTED election whose highest CERTIFIED
    period has ended (clock cursor past its window end) while the next period is
    still PENDING_CERT."""
    for election in db.elections.values():
        if election["status"] != "ELECTED":
            continue
        certified = [bp for bp in db.benefit_periods.values()
                     if bp["election_id"] == election["id"] and bp["cert_status"] == "CERTIFIED"]
        if not certified:
            continue
        highest_cert = max(certified, key=lambda bp: bp["sequence"])
        end_offset = highest_cert["start_offset_days"] + highest_cert["length_days"]
        cursor = svc.elapsed_days(election, db.get_clock())
        # next period must still be pending (i.e. lowest pending exists above)
        pending = svc.lowest_pending_cert_period(election)
        if cursor >= end_offset and pending is not None and pending["sequence"] > highest_cert["sequence"]:
            election["status"] = "EXPIRED"
            db.touch(election)


# ==========================================================================
# Provider
# ==========================================================================
@app.route("/hospice/providers", methods=["POST"])
def create_provider():
    require_role({"BillingAdmin"})
    body = util.get_json_body()
    util.require_fields(body, ["name", "cap_year_start", "per_beneficiary_cap_cents"])
    name = util.require_nonempty_str(body["name"], "name")
    cap_year_start_dt = util.parse_datetime(body["cap_year_start"], "cap_year_start")
    util.require_midnight(cap_year_start_dt, "cap_year_start")
    cap_cents = util.require_int(body["per_beneficiary_cap_cents"], "per_beneficiary_cap_cents")
    if cap_cents < 0:
        raise err(ERR_INVALID_REQUEST, "per_beneficiary_cap_cents must be >= 0")

    rec = {
        "id": db.new_id(),
        "name": name,
        "cap_year_start": body["cap_year_start"],
        "_cap_year_start_dt": cap_year_start_dt,
        "per_beneficiary_cap_cents": cap_cents,
        "cap_liability_cents": 0,
        "total_paid_cents": 0,
        "counted_beneficiaries": 0,
        "cap_settled": False,
    }
    rec.update(db.base_fields())
    db.providers[rec["id"]] = rec
    return success(svc.serialize_provider(rec), status=201)


@app.route("/hospice/providers/<pid>", methods=["GET"])
def get_provider(pid):
    require_role({"BillingAdmin", "IntakeCoordinator", "ClinicalManager"})
    p = get_or_404(db.providers, pid)
    return success(svc.serialize_provider(p))


@app.route("/hospice/providers/<pid>/cap-summary", methods=["GET"])
def provider_cap_summary(pid):
    require_role({"BillingAdmin"})
    p = get_or_404(db.providers, pid)
    svc.recompute_provider_ledger(p)
    return success(svc.serialize_provider(p))


@app.route("/hospice/providers/<pid>/settle-cap", methods=["POST"])
def provider_settle_cap(pid):
    require_role({"BillingAdmin"})
    p = get_or_404(db.providers, pid)
    if p["cap_settled"]:
        raise err(ERR_CAP_YEAR_SETTLED, "Cap year already settled")
    total_paid, counted, liability = svc.compute_final_cap(p)
    p["total_paid_cents"] = total_paid
    p["counted_beneficiaries"] = counted
    p["cap_liability_cents"] = liability
    p["cap_settled"] = True
    db.touch(p)
    return success(svc.serialize_provider(p))


@app.route("/hospice/providers/<pid>/elections", methods=["GET"])
def provider_elections(pid):
    require_role({"BillingAdmin", "IntakeCoordinator", "ClinicalManager"})
    limit, offset = util.parse_pagination()
    p = get_or_404(db.providers, pid)
    items = [e for e in db.elections.values() if e["provider_id"] == p["id"]]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for e in items:
        svc.refresh_election_derived(e)
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_election(e) for e in page], limit, offset, total)


# ==========================================================================
# Physician
# ==========================================================================
@app.route("/hospice/physicians", methods=["POST"])
def create_physician():
    require_role({"ClinicalManager"})
    body = util.get_json_body()
    util.require_fields(body, ["full_name"])
    full_name = util.require_nonempty_str(body["full_name"], "full_name")
    is_md = body.get("is_medical_director", False)
    if is_md is None:
        is_md = False
    util.require_bool(is_md, "is_medical_director")

    rec = {
        "id": db.new_id(),
        "full_name": full_name,
        "is_medical_director": is_md,
    }
    rec.update(db.base_fields())
    db.physicians[rec["id"]] = rec
    return success(svc.serialize_physician(rec), status=201)


@app.route("/hospice/physicians/<phid>", methods=["GET"])
def get_physician(phid):
    require_role({"ClinicalManager", "Physician"})
    ph = get_or_404(db.physicians, phid)
    return success(svc.serialize_physician(ph))


# ==========================================================================
# Election
# ==========================================================================
@app.route("/hospice/elections", methods=["POST"])
def create_election():
    require_role({"IntakeCoordinator"})
    body = util.get_json_body()
    util.require_fields(body, ["provider_id", "patient_name", "election_date", "attending_physician_id"])
    provider_id = util.require_str(body["provider_id"], "provider_id")
    patient_name = util.require_nonempty_str(body["patient_name"], "patient_name")
    election_dt = util.parse_datetime(body["election_date"], "election_date")
    util.require_midnight(election_dt, "election_date")
    attending = util.require_str(body["attending_physician_id"], "attending_physician_id")

    # existence (404) — provider FK
    provider = get_or_404(db.providers, provider_id)

    # Election refused when provider cap year covering election_date already settled.
    if provider["cap_settled"] and svc._in_window(provider, election_dt):
        raise err(ERR_CAP_YEAR_SETTLED, "Provider cap year covering election_date is already settled")

    eid = db.new_id()
    rec = {
        "id": eid,
        "provider_id": provider_id,
        "patient_name": patient_name,
        "election_date": body["election_date"],
        "_election_date_dt": election_dt,
        "attending_physician_id": attending,
        "status": "ELECTED",
        "current_period_number": 1,
        "days_used_in_period": 0,
        "revocation_date": None,
        "_revocation_date_dt": None,
        "bereavement_required": False,
    }
    rec.update(db.base_fields())
    db.elections[eid] = rec

    # Materialize benefit period 1 (90 days, offset 0, PENDING_CERT)
    _materialize_period(rec, 1)
    return success(svc.serialize_election(rec), status=201)


def _materialize_period(election, sequence):
    bp_id = db.new_id()
    bp = {
        "id": bp_id,
        "election_id": election["id"],
        "sequence": sequence,
        "length_days": svc.length_days(sequence),
        "start_offset_days": svc.start_offset_days(sequence),
        "requires_face_to_face": svc.requires_face_to_face(sequence),
        "certification_id": None,
        "cert_status": "PENDING_CERT",
    }
    bp.update(db.base_fields())
    db.benefit_periods[bp_id] = bp
    return bp


@app.route("/hospice/elections/<eid>", methods=["GET"])
def get_election(eid):
    require_role({"IntakeCoordinator", "ClinicalManager", "Physician", "BillingAdmin"})
    e = get_or_404(db.elections, eid)
    svc.refresh_election_derived(e)
    return success(svc.serialize_election(e))


@app.route("/hospice/elections", methods=["GET"])
def list_elections():
    require_role({"IntakeCoordinator", "ClinicalManager", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    provider_id = request.args.get("provider_id")
    items = list(db.elections.values())
    if provider_id is not None:
        items = [e for e in items if e["provider_id"] == provider_id]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for e in items:
        svc.refresh_election_derived(e)
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_election(e) for e in page], limit, offset, total)


@app.route("/hospice/elections/<eid>/revoke", methods=["POST"])
def revoke_election(eid):
    require_role({"IntakeCoordinator"})
    body = util.get_json_body()
    e = get_or_404(db.elections, eid)
    if e["status"] != "ELECTED":
        raise err(ERR_ELECTION_NOT_ELECTED, "Election is not ELECTED")
    util.require_fields(body, ["revocation_date"])
    rev_dt = util.parse_datetime(body["revocation_date"], "revocation_date")

    # must be >= election_date and >= service_date of latest care day
    if rev_dt < e["_election_date_dt"]:
        raise err(ERR_INVALID_REQUEST, "revocation_date must be >= election_date")
    latest = svc.latest_care_day(e)
    if latest is not None and rev_dt < latest["_service_date_dt"]:
        raise err(ERR_INVALID_REQUEST, "revocation_date must be >= latest care day service_date")

    e["status"] = "REVOKED"
    e["revocation_date"] = body["revocation_date"]
    e["_revocation_date_dt"] = rev_dt
    # bereavement_required stays false (revocation is not death)
    db.touch(e)
    # days_used reconciled again on revoke (§2.5)
    svc.refresh_election_derived(e, bump_version=True)
    return success(svc.serialize_election(e))


@app.route("/hospice/elections/<eid>/discharge", methods=["POST"])
def discharge_election(eid):
    require_role({"ClinicalManager"})
    body = util.get_json_body()
    e = get_or_404(db.elections, eid)
    if e["status"] != "ELECTED":
        raise err(ERR_ELECTION_NOT_ELECTED, "Election is not ELECTED")
    util.require_fields(body, ["discharge_date", "discharge_reason"])
    discharge_dt = util.parse_datetime(body["discharge_date"], "discharge_date")
    reason = body["discharge_reason"]
    util.require_enum(reason, "discharge_reason", DISCHARGE_REASONS)

    latest = svc.latest_care_day(e)
    if latest is not None and discharge_dt < latest["_service_date_dt"]:
        raise err(ERR_INVALID_REQUEST, "discharge_date must be >= latest care day service_date")

    e["status"] = "DISCHARGED"
    e["revocation_date"] = body["discharge_date"]
    e["_revocation_date_dt"] = discharge_dt
    if reason == "DEATH":
        e["bereavement_required"] = True
    db.touch(e)
    # days_used reconciled again on discharge (§2.5)
    svc.refresh_election_derived(e, bump_version=True)
    return success(svc.serialize_election(e))


# ==========================================================================
# BenefitPeriod
# ==========================================================================
@app.route("/hospice/elections/<eid>/benefit-periods", methods=["GET"])
def list_election_benefit_periods(eid):
    require_role({"IntakeCoordinator", "ClinicalManager", "Physician", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    e = get_or_404(db.elections, eid)
    items = [bp for bp in db.benefit_periods.values() if bp["election_id"] == e["id"]]
    items.sort(key=lambda bp: (bp["created_at"], bp["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_benefit_period(bp) for bp in page], limit, offset, total)


@app.route("/hospice/benefit-periods/<bpid>", methods=["GET"])
def get_benefit_period(bpid):
    require_role({"IntakeCoordinator", "ClinicalManager", "Physician", "BillingAdmin"})
    bp = get_or_404(db.benefit_periods, bpid)
    return success(svc.serialize_benefit_period(bp))


@app.route("/hospice/benefit-periods", methods=["GET"])
def list_benefit_periods():
    require_role({"IntakeCoordinator", "ClinicalManager", "Physician", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    election_id = request.args.get("election_id")
    certification_id = request.args.get("certification_id")
    items = list(db.benefit_periods.values())
    if election_id is not None:
        items = [bp for bp in items if bp["election_id"] == election_id]
    if certification_id is not None:
        items = [bp for bp in items if bp["certification_id"] == certification_id]
    items.sort(key=lambda bp: (bp["created_at"], bp["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_benefit_period(bp) for bp in page], limit, offset, total)


# ==========================================================================
# Certification
# ==========================================================================
@app.route("/hospice/certifications", methods=["POST"])
def create_certification():
    require_role({"Physician"})
    body = util.get_json_body()

    # structural: required fields
    util.require_fields(body, ["election_id", "period_sequence", "certifying_physician_id",
                               "narrative_present", "expected_election_version"])
    election_id = util.require_str(body["election_id"], "election_id")
    period_sequence = util.require_int(body["period_sequence"], "period_sequence")
    if period_sequence < 1:
        raise err(ERR_INVALID_REQUEST, "period_sequence must be >= 1")
    certifying_physician_id = util.require_str(body["certifying_physician_id"], "certifying_physician_id")
    narrative_present = util.require_bool(body["narrative_present"], "narrative_present")
    expected_version = util.require_int(body["expected_election_version"], "expected_election_version")
    f2f_physician_id = body.get("face_to_face_physician_id")
    f2f_date_raw = body.get("face_to_face_date")
    commit = body.get("commit", True)
    if commit is None:
        commit = True
    util.require_bool(commit, "commit")

    f2f_date_dt = None
    if f2f_date_raw is not None:
        f2f_date_dt = util.parse_datetime(f2f_date_raw, "face_to_face_date")
    if f2f_physician_id is not None:
        util.require_str(f2f_physician_id, "face_to_face_physician_id")

    # existence (404): election, certifying physician, f2f physician (declaration order)
    election = get_or_404(db.elections, election_id)
    get_or_404(db.physicians, certifying_physician_id)
    if f2f_physician_id is not None:
        get_or_404(db.physicians, f2f_physician_id)

    # state (409): election must be ELECTED
    if election["status"] != "ELECTED":
        raise err(ERR_ELECTION_NOT_ELECTED, "Election is not ELECTED")

    # business: period_sequence must equal lowest PENDING_CERT period sequence
    pending = svc.lowest_pending_cert_period(election)
    if pending is None or period_sequence != pending["sequence"]:
        raise err(ERR_PERIOD_SEQUENCE_MISMATCH,
                  "period_sequence must equal the lowest PENDING_CERT period sequence")
    target_period = pending

    cert_id = db.new_id()
    cert = {
        "id": cert_id,
        "election_id": election_id,
        "period_sequence": period_sequence,
        "certifying_physician_id": certifying_physician_id,
        "face_to_face_physician_id": f2f_physician_id,
        "face_to_face_date": f2f_date_raw,
        "narrative_present": narrative_present,
        "expected_election_version": expected_version,
        "status": "DRAFT",
        "rejection_reason": None,
    }
    cert.update(db.base_fields())
    db.certifications[cert_id] = cert

    # Draft mode (commit=false): persist DRAFT against the pending period; no
    # precondition branch, no OCC.
    if not commit:
        return success(svc.serialize_certification(cert), status=201)

    # ----- Commit path: evaluate certify preconditions in §3.13 order --------
    # 1) face-to-face requirement (sequence >= 3) — ERR_FACE_TO_FACE_REQUIRED (422)
    if period_sequence >= 3:
        ok_f2f = (f2f_physician_id is not None and f2f_date_dt is not None)
        if ok_f2f:
            window_end = election["_election_date_dt"] + timedelta(days=target_period["start_offset_days"])
            window_start = window_end - timedelta(days=30)
            # within the 30 days immediately before the period start
            if not (window_start <= f2f_date_dt <= window_end):
                ok_f2f = False
        if not ok_f2f:
            cert["status"] = "REJECTED"
            cert["rejection_reason"] = "Face-to-face encounter missing or outside the 30-day pre-period window"
            db.touch(cert)
            raise err(ERR_FACE_TO_FACE_REQUIRED,
                      "Face-to-face encounter required for period_sequence >= 3")

    # 2) initial-certification completeness (narrative + MD-or-two-physician)
    #    Applies to all periods (narrative); the MD/two-physician backing is the
    #    initial-cert rule for sequence 1 or 2.
    complete = narrative_present
    if complete and period_sequence in (1, 2):
        certifier = db.physicians.get(certifying_physician_id)
        is_md = bool(certifier and certifier["is_medical_director"])
        if not is_md:
            # need a second committed/distinct-physician certification for the
            # same period_sequence by a distinct physician
            distinct_second = any(
                c["election_id"] == election_id
                and c["period_sequence"] == period_sequence
                and c["id"] != cert_id
                and c["certifying_physician_id"] != certifying_physician_id
                for c in db.certifications.values()
            )
            complete = distinct_second
    if not complete:
        cert["status"] = "REJECTED"
        if not narrative_present:
            cert["rejection_reason"] = "Clinical narrative absent"
        else:
            cert["rejection_reason"] = "Initial certification lacks medical-director or second physician"
        db.touch(cert)
        raise err(ERR_CERTIFICATION_INCOMPLETE,
                  "Initial certification incomplete")

    # 3) OCC — expected_election_version must match Election.version (412)
    if expected_version != election["version"]:
        # Stale view; do not advance. Leave certification DRAFT->? per OCC.
        raise err(ERR_STALE_ELECTION_VERSION,
                  "expected_election_version does not match the live Election.version")

    # ----- All preconditions hold: certify -----------------------------------
    target_period["cert_status"] = "CERTIFIED"
    target_period["certification_id"] = cert_id
    db.touch(target_period)
    cert["status"] = "CERTIFIED"
    db.touch(cert)
    # materialize the next benefit period (sequence+1)
    next_seq = period_sequence + 1
    if svc.period_by_sequence(election, next_seq) is None:
        _materialize_period(election, next_seq)
    # increment election version by one
    db.touch(election)
    svc.refresh_election_derived(election)
    return success(svc.serialize_certification(cert), status=201)


@app.route("/hospice/certifications/<cid>", methods=["GET"])
def get_certification(cid):
    require_role({"Physician", "ClinicalManager"})
    c = get_or_404(db.certifications, cid)
    return success(svc.serialize_certification(c))


@app.route("/hospice/elections/<eid>/certifications", methods=["GET"])
def list_election_certifications(eid):
    require_role({"Physician", "ClinicalManager", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    e = get_or_404(db.elections, eid)
    period_sequence = request.args.get("period_sequence")
    items = [c for c in db.certifications.values() if c["election_id"] == e["id"]]
    if period_sequence is not None:
        try:
            ps = int(period_sequence)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "period_sequence filter must be an integer")
        items = [c for c in items if c["period_sequence"] == ps]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_certification(c) for c in page], limit, offset, total)


@app.route("/hospice/certifications", methods=["GET"])
def list_certifications():
    require_role({"Physician", "ClinicalManager", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    certifying = request.args.get("certifying_physician_id")
    f2f = request.args.get("face_to_face_physician_id")
    election_id = request.args.get("election_id")
    items = list(db.certifications.values())
    if certifying is not None:
        items = [c for c in items if c["certifying_physician_id"] == certifying]
    if f2f is not None:
        items = [c for c in items if c["face_to_face_physician_id"] == f2f]
    if election_id is not None:
        items = [c for c in items if c["election_id"] == election_id]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_certification(c) for c in page], limit, offset, total)


# ==========================================================================
# CarePlan
# ==========================================================================
@app.route("/hospice/care-plans", methods=["POST"])
def create_care_plan():
    require_role({"ClinicalManager"})
    body = util.get_json_body()
    util.require_fields(body, ["election_id", "idg_members", "expected_election_version"])
    election_id = util.require_str(body["election_id"], "election_id")
    idg_members = body["idg_members"]
    if not isinstance(idg_members, list):
        raise err(ERR_INVALID_REQUEST, "idg_members must be an array")
    for m in idg_members:
        if m not in IDG_ALL:
            raise err(ERR_INVALID_REQUEST, "idg_members contains an invalid discipline code")
    expected_version = util.require_int(body["expected_election_version"], "expected_election_version")
    supersedes_plan_id = body.get("supersedes_plan_id")
    if supersedes_plan_id is not None:
        util.require_str(supersedes_plan_id, "supersedes_plan_id")
    review_due = body.get("review_due_offset_days", 15)
    if review_due is None:
        review_due = 15
    util.require_int(review_due, "review_due_offset_days")
    if review_due < 1:
        raise err(ERR_INVALID_REQUEST, "review_due_offset_days must be >= 1")

    # existence (404): election, then supersedes plan
    election = get_or_404(db.elections, election_id)
    prior = None
    if supersedes_plan_id is not None:
        prior = get_or_404(db.care_plans, supersedes_plan_id)

    # state (409): election ELECTED
    if election["status"] != "ELECTED":
        raise err(ERR_ELECTION_NOT_ELECTED, "Election is not ELECTED")

    # business: idg core completeness (422)
    if not IDG_CORE.issubset(set(idg_members)):
        raise err(ERR_IDG_INCOMPLETE, "idg_members must contain the four core disciplines")

    # supersede semantics (409 ERR_PLAN_NOT_ACTIVE for inactive/foreign target;
    # the PRD scopes ERR_PLAN_NOT_ACTIVE to coverage items, so here we enforce
    # the care-plan create precondition: prior must be ACTIVE; first plan needs
    # no other ACTIVE plan. A stale/inactive supersede target surfaces as OCC.)
    if supersedes_plan_id is None:
        # no other ACTIVE plan may exist for this election
        existing_active = any(cp["election_id"] == election_id and cp["status"] == "ACTIVE"
                              for cp in db.care_plans.values())
        if existing_active:
            raise err(ERR_STALE_ELECTION_VERSION,
                      "An ACTIVE care plan already exists for this election")
    else:
        if prior["election_id"] != election_id or prior["status"] != "ACTIVE":
            raise err(ERR_STALE_ELECTION_VERSION,
                      "supersedes_plan_id target is not an ACTIVE plan of this election")

    # OCC (412): expected_election_version must match
    if expected_version != election["version"]:
        raise err(ERR_STALE_ELECTION_VERSION,
                  "expected_election_version does not match the live Election.version")

    cp_id = db.new_id()
    if supersedes_plan_id is not None:
        revision_number = prior["revision_number"] + 1
    else:
        revision_number = 1
    cp = {
        "id": cp_id,
        "election_id": election_id,
        "supersedes_plan_id": supersedes_plan_id,
        "revision_number": revision_number,
        "idg_members": list(idg_members),
        "review_due_offset_days": review_due,
        "status": "ACTIVE",
    }
    cp.update(db.base_fields())
    db.care_plans[cp_id] = cp

    if supersedes_plan_id is not None:
        prior["status"] = "SUPERSEDED"
        db.touch(prior)

    # increment election version by one
    db.touch(election)
    svc.refresh_election_derived(election)
    return success(svc.serialize_care_plan(cp), status=201)


@app.route("/hospice/care-plans/<cpid>", methods=["GET"])
def get_care_plan(cpid):
    require_role({"ClinicalManager", "Physician", "BillingAdmin"})
    cp = get_or_404(db.care_plans, cpid)
    return success(svc.serialize_care_plan(cp))


@app.route("/hospice/elections/<eid>/care-plans", methods=["GET"])
def list_election_care_plans(eid):
    require_role({"ClinicalManager", "Physician", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    e = get_or_404(db.elections, eid)
    status = request.args.get("status")
    items = [cp for cp in db.care_plans.values() if cp["election_id"] == e["id"]]
    if status is not None:
        items = [cp for cp in items if cp["status"] == status]
    items.sort(key=lambda cp: (cp["created_at"], cp["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_care_plan(cp) for cp in page], limit, offset, total)


@app.route("/hospice/care-plans", methods=["GET"])
def list_care_plans():
    require_role({"ClinicalManager", "Physician", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    supersedes_plan_id = request.args.get("supersedes_plan_id")
    election_id = request.args.get("election_id")
    status = request.args.get("status")
    items = list(db.care_plans.values())
    if supersedes_plan_id is not None:
        items = [cp for cp in items if cp["supersedes_plan_id"] == supersedes_plan_id]
    if election_id is not None:
        items = [cp for cp in items if cp["election_id"] == election_id]
    if status is not None:
        items = [cp for cp in items if cp["status"] == status]
    items.sort(key=lambda cp: (cp["created_at"], cp["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_care_plan(cp) for cp in page], limit, offset, total)


# ==========================================================================
# CareDay
# ==========================================================================
@app.route("/hospice/care-days", methods=["POST"])
def create_care_day():
    require_role({"ClinicalManager"})
    body = util.get_json_body()
    util.require_fields(body, ["election_id", "service_date", "level_of_care"])
    election_id = util.require_str(body["election_id"], "election_id")
    service_dt = util.parse_datetime(body["service_date"], "service_date")
    util.require_midnight(service_dt, "service_date")
    level = body["level_of_care"]
    util.require_enum(level, "level_of_care", LOC_SET)
    high_intensity = body.get("high_intensity", False)
    if high_intensity is None:
        high_intensity = False
    util.require_bool(high_intensity, "high_intensity")

    # existence (404)
    election = get_or_404(db.elections, election_id)
    provider = db.providers.get(election["provider_id"])

    # state (409): election ELECTED
    if election["status"] != "ELECTED":
        raise err(ERR_ELECTION_NOT_ELECTED, "Election is not ELECTED")

    # cap-year-settled guard (409): no care day into a settled cap year
    if provider is not None and provider["cap_settled"] and svc._in_window(provider, service_dt):
        raise err(ERR_CAP_YEAR_SETTLED, "Provider cap year covering service_date is already settled")

    # --- domain checks in §3.13 order ---------------------------------------
    # 1) service-date range (422)
    if service_dt < election["_election_date_dt"]:
        raise err(ERR_SERVICE_DATE_OUT_OF_RANGE, "service_date before election_date")
    if election["_revocation_date_dt"] is not None and service_dt >= election["_revocation_date_dt"]:
        raise err(ERR_SERVICE_DATE_OUT_OF_RANGE, "service_date on/after election termination")

    elapsed_index = (service_dt - election["_election_date_dt"]).days

    # 2) respite consecutive-day limit (422)
    if level == "RESPITE":
        run = svc.respite_run_length(election, service_dt)
        if run > svc.RESPITE_MAX_CONSECUTIVE:
            raise err(ERR_RESPITE_LIMIT_EXCEEDED,
                      "RESPITE posting would exceed 5 consecutive days")

    # 3) intensity-flag agreement (422)
    if level == "ROUTINE":
        in_high = elapsed_index < svc.ROUTINE_HIGH_DAYS
        if high_intensity and not in_high:
            raise err(ERR_INTENSITY_FLAG_MISMATCH,
                      "high_intensity=true requires elapsed_day_index < 60")
        if (not high_intensity) and in_high:
            raise err(ERR_INTENSITY_FLAG_MISMATCH,
                      "high_intensity=false on a ROUTINE day requires elapsed_day_index >= 60")
    else:
        if high_intensity:
            raise err(ERR_INTENSITY_FLAG_MISMATCH,
                      "non-ROUTINE day must carry high_intensity=false")

    # 4) one-day-per-calendar-day uniqueness (409)
    for cd in db.care_days.values():
        if cd["election_id"] == election_id and cd["_service_date_dt"] == service_dt:
            raise err(ERR_DUPLICATE_CARE_DAY,
                      "A care day already exists for this election on this service_date")

    # --- create ----------------------------------------------------------
    payment = svc.day_payment_cents(level, elapsed_index)
    bp = svc.period_for_offset(election, elapsed_index)
    cd_id = db.new_id()
    cd = {
        "id": cd_id,
        "election_id": election_id,
        "benefit_period_id": bp["id"] if bp is not None else None,
        "service_date": body["service_date"],
        "_service_date_dt": service_dt,
        "level_of_care": level,
        "high_intensity": high_intensity,
        "payment_cents": payment,
        "respite_run_length": 0,
    }
    cd.update(db.base_fields())
    db.care_days[cd_id] = cd

    # respite_run_length now that the day is persisted (count includes self)
    if level == "RESPITE":
        cd["respite_run_length"] = svc.respite_run_length(election, service_dt)
    else:
        cd["respite_run_length"] = 0

    # reconcile election days_used_in_period (§2.5 — bumps version on change)
    svc.refresh_election_derived(election, bump_version=True)
    # recompute provider cap ledger (provisional)
    if provider is not None:
        svc.recompute_provider_ledger(provider)

    return success(svc.serialize_care_day(cd), status=201)


@app.route("/hospice/care-days/<cdid>", methods=["GET"])
def get_care_day(cdid):
    require_role({"ClinicalManager", "BillingAdmin"})
    cd = get_or_404(db.care_days, cdid)
    return success(svc.serialize_care_day(cd))


@app.route("/hospice/elections/<eid>/care-days", methods=["GET"])
def list_election_care_days(eid):
    require_role({"ClinicalManager", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    e = get_or_404(db.elections, eid)
    level = request.args.get("level_of_care")
    items = [cd for cd in db.care_days.values() if cd["election_id"] == e["id"]]
    if level is not None:
        items = [cd for cd in items if cd["level_of_care"] == level]
    # ordered by service_date (PRD §2.3 documented exception)
    items.sort(key=lambda cd: (cd["_service_date_dt"], cd["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_care_day(cd) for cd in page], limit, offset, total)


@app.route("/hospice/care-days", methods=["GET"])
def list_care_days():
    require_role({"ClinicalManager", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    election_id = request.args.get("election_id")
    benefit_period_id = request.args.get("benefit_period_id")
    level = request.args.get("level_of_care")
    items = list(db.care_days.values())
    if election_id is not None:
        items = [cd for cd in items if cd["election_id"] == election_id]
    if benefit_period_id is not None:
        items = [cd for cd in items if cd["benefit_period_id"] == benefit_period_id]
    if level is not None:
        items = [cd for cd in items if cd["level_of_care"] == level]
    items.sort(key=lambda cd: (cd["created_at"], cd["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_care_day(cd) for cd in page], limit, offset, total)


# ==========================================================================
# CoverageItem
# ==========================================================================
@app.route("/hospice/coverage-items", methods=["POST"])
def create_coverage_item():
    require_role({"ClinicalManager"})
    body = util.get_json_body()
    util.require_fields(body, ["election_id", "care_plan_id", "item_type", "related_to_terminal_dx"])
    election_id = util.require_str(body["election_id"], "election_id")
    care_plan_id = util.require_str(body["care_plan_id"], "care_plan_id")
    item_type = body["item_type"]
    util.require_enum(item_type, "item_type", ITEM_TYPES)
    related = util.require_bool(body["related_to_terminal_dx"], "related_to_terminal_dx")

    # existence (404): election then care plan
    election = get_or_404(db.elections, election_id)
    care_plan = get_or_404(db.care_plans, care_plan_id)

    # state (409): election ELECTED
    if election["status"] != "ELECTED":
        raise err(ERR_ELECTION_NOT_ELECTED, "Election is not ELECTED")

    # domain: coverage check (422) precedes active-plan check (409) per §3.13
    if not related:
        raise err(ERR_ITEM_NOT_COVERED,
                  "Item not related to terminal diagnosis is not covered")

    if care_plan["election_id"] != election_id or care_plan["status"] != "ACTIVE":
        raise err(ERR_PLAN_NOT_ACTIVE,
                  "care_plan_id must reference an ACTIVE care plan of the same election")

    ci_id = db.new_id()
    ci = {
        "id": ci_id,
        "election_id": election_id,
        "care_plan_id": care_plan_id,
        "item_type": item_type,
        "related_to_terminal_dx": related,
        "coverage_status": "COVERED",  # COVERED iff related_to_terminal_dx
    }
    ci.update(db.base_fields())
    db.coverage_items[ci_id] = ci
    return success(svc.serialize_coverage_item(ci), status=201)


@app.route("/hospice/coverage-items/<ciid>", methods=["GET"])
def get_coverage_item(ciid):
    require_role({"ClinicalManager", "BillingAdmin"})
    ci = get_or_404(db.coverage_items, ciid)
    return success(svc.serialize_coverage_item(ci))


@app.route("/hospice/elections/<eid>/coverage-items", methods=["GET"])
def list_election_coverage_items(eid):
    require_role({"ClinicalManager", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    e = get_or_404(db.elections, eid)
    item_type = request.args.get("item_type")
    items = [ci for ci in db.coverage_items.values() if ci["election_id"] == e["id"]]
    if item_type is not None:
        items = [ci for ci in items if ci["item_type"] == item_type]
    items.sort(key=lambda ci: (ci["created_at"], ci["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_coverage_item(ci) for ci in page], limit, offset, total)


@app.route("/hospice/care-plans/<cpid>/coverage-items", methods=["GET"])
def list_care_plan_coverage_items(cpid):
    require_role({"ClinicalManager", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    cp = get_or_404(db.care_plans, cpid)
    items = [ci for ci in db.coverage_items.values() if ci["care_plan_id"] == cp["id"]]
    items.sort(key=lambda ci: (ci["created_at"], ci["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_coverage_item(ci) for ci in page], limit, offset, total)


# ==========================================================================
# BereavementCase
# ==========================================================================
@app.route("/hospice/bereavement-cases", methods=["POST"])
def create_bereavement_case():
    require_role({"ClinicalManager"})
    body = util.get_json_body()
    util.require_fields(body, ["election_id", "enrolled_date"])
    election_id = util.require_str(body["election_id"], "election_id")
    enrolled_dt = util.parse_datetime(body["enrolled_date"], "enrolled_date")
    service_window = body.get("service_window_days", 365)
    if service_window is None:
        service_window = 365
    util.require_int(service_window, "service_window_days")
    if service_window < 365:
        raise err(ERR_INVALID_REQUEST, "service_window_days must be >= 365")

    # existence (404)
    election = get_or_404(db.elections, election_id)

    # eligibility (409): DISCHARGED with bereavement_required, and no OPEN case
    if not (election["status"] == "DISCHARGED" and election["bereavement_required"]):
        raise err(ERR_BEREAVEMENT_NOT_ELIGIBLE,
                  "Election is not a death discharge")
    existing_open = any(bc["election_id"] == election_id and bc["status"] == "OPEN"
                        for bc in db.bereavement_cases.values())
    if existing_open:
        raise err(ERR_BEREAVEMENT_NOT_ELIGIBLE,
                  "An OPEN bereavement case already exists for this election")

    # enrolled_date must be >= election's discharge date (revocation_date)
    if election["_revocation_date_dt"] is not None and enrolled_dt < election["_revocation_date_dt"]:
        raise err(ERR_INVALID_REQUEST, "enrolled_date must be >= discharge date")

    bc_id = db.new_id()
    bc = {
        "id": bc_id,
        "election_id": election_id,
        "enrolled_date": body["enrolled_date"],
        "service_window_days": service_window,
        "status": "OPEN",
    }
    bc.update(db.base_fields())
    db.bereavement_cases[bc_id] = bc
    return success(svc.serialize_bereavement_case(bc), status=201)


@app.route("/hospice/bereavement-cases/<bcid>", methods=["GET"])
def get_bereavement_case(bcid):
    require_role({"ClinicalManager"})
    bc = get_or_404(db.bereavement_cases, bcid)
    return success(svc.serialize_bereavement_case(bc))


@app.route("/hospice/bereavement-cases/<bcid>/close", methods=["POST"])
def close_bereavement_case(bcid):
    require_role({"ClinicalManager"})
    bc = get_or_404(db.bereavement_cases, bcid)
    # OPEN -> CLOSED
    bc["status"] = "CLOSED"
    db.touch(bc)
    return success(svc.serialize_bereavement_case(bc))


@app.route("/hospice/elections/<eid>/bereavement-cases", methods=["GET"])
def list_election_bereavement_cases(eid):
    require_role({"ClinicalManager", "BillingAdmin"})
    limit, offset = util.parse_pagination()
    e = get_or_404(db.elections, eid)
    items = [bc for bc in db.bereavement_cases.values() if bc["election_id"] == e["id"]]
    items.sort(key=lambda bc: (bc["created_at"], bc["_seq"]))
    page, total = util.paginate(items, limit, offset)
    return list_response([svc.serialize_bereavement_case(bc) for bc in page], limit, offset, total)


# ==========================================================================
# Test-driving clock
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role({"BillingAdmin", "IntakeCoordinator", "ClinicalManager"})
    body = util.get_json_body()
    util.require_fields(body, ["to_iso8601"])
    dt = util.parse_datetime(body["to_iso8601"], "to_iso8601")
    db.set_clock(dt)
    # advance cursors / auto-expire
    apply_expiry_transitions()
    return success({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
