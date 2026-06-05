"""Visit lifecycle: request, compliance, approval/routing, completion, cancel,
prescriptions, claims (cascade), compliance-check log."""
from flask import Blueprint, request

import db
from errors import (err, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_VISIT_SLOT_CONFLICT, ERR_INVALID_STATE,
                    ERR_MODALITY_NOT_PERMITTED, ERR_NO_LICENSE_IN_STATE,
                    ERR_DEA_EXAM_REQUIRED, ERR_NO_CONTROLLED_AUTHORITY,
                    ERR_STALE_PRESCRIPTION_VERSION)
from middleware import require_auth, require_role
from response import success_object
from services import store, serializers, lookup, validate, compliance
from services.calculations import (patient_cost_insurance, patient_cost_self_pay,
                                    claim_adjudication, VISIT_BUFFER_MINUTES,
                                    FOLLOW_UP_INTERVAL_DAYS, DEA_EXAM_RECENCY_DAYS)
from datetime import timedelta
from .common import list_response

bp = Blueprint("visits", __name__)

NON_TERMINAL_VISIT_FOR_BUFFER = lambda s: s not in ("CANCELLED", "VOIDED", "COMPLETED")


# ---------------- Visit request + reads ----------------

@bp.route("/visits", methods=["POST"])
def create_visit():
    user_id, role = require_auth()
    require_role(role, {"Patient"})
    body = validate.get_body()

    # Body well-formedness (priority 4) — but FK existence (priority 3) and
    # ownership (priority 2) precede business rules. We resolve ids first, then
    # check ownership, then body constraints, then slot conflict.
    physician_id = validate.require_str(body, "physician_id")
    patient_id = validate.require_str(body, "patient_id")
    modality = validate.require_enum(body, "modality", {"VIDEO", "AUDIO_ONLY"})
    scheduled_at = validate.require_datetime(body, "scheduled_at")
    determined_state_code = validate.require_state(body, "determined_state_code")
    list_fee_cents = validate.require_int_gt(body, "list_fee_cents", 0)
    platform_fee_cents = validate.optional_int(body, "platform_fee_cents", 0)
    if platform_fee_cents < 0:
        raise err(ERR_INVALID_REQUEST, "platform_fee_cents must be >= 0.")

    with db.lock:
        # Existence (priority 3): body FKs.
        if physician_id not in db.physicians:
            raise err(ERR_NOT_FOUND, "physician_id not found.")
        if patient_id not in db.patients:
            raise err(ERR_NOT_FOUND, "patient_id not found.")
        # Ownership (priority 2): a Patient may only request a visit they own.
        if patient_id != user_id:
            raise err(ERR_FORBIDDEN, "Patient may only request visits for themselves.")

        # Slot buffer conflict (priority 8): point-plus-symmetric-buffer, exclusive.
        new_sched = db.parse_iso(scheduled_at)
        for v in db.visits.values():
            if v["physician_id"] != physician_id:
                continue
            if not NON_TERMINAL_VISIT_FOR_BUFFER(v["status"]):
                continue
            ex_sched = db.parse_iso(v["scheduled_at"])
            delta_minutes = abs((new_sched - ex_sched).total_seconds()) / 60.0
            if delta_minutes < VISIT_BUFFER_MINUTES:
                raise err(ERR_VISIT_SLOT_CONFLICT,
                          "Visit conflicts with an existing visit within the buffer window.")

        record = store.create_full({
            "physician_id": physician_id,
            "patient_id": patient_id,
            "modality": modality,
            "scheduled_at": scheduled_at,
            "determined_state_code": determined_state_code,
            "list_fee_cents": list_fee_cents,
            "platform_fee_cents": platform_fee_cents,
            "routing": None,
            "patient_cost_cents": None,
            "prescription_version": 0,
            "status": "REQUESTED",
        })
        db.visits[record["id"]] = record
        return success_object(serializers.visit(record), status=201)


@bp.route("/visits/<vid>", methods=["GET"])
def get_visit(vid):
    with db.lock:
        v = lookup.visit(vid)
        return success_object(serializers.visit(v))


@bp.route("/visits", methods=["GET"])
def list_visits():
    with db.lock:
        records = list(db.visits.values())
        physician_id = request.args.get("physician_id")
        patient_id = request.args.get("patient_id")
        if physician_id is not None:
            records = [v for v in records if v["physician_id"] == physician_id]
        if patient_id is not None:
            records = [v for v in records if v["patient_id"] == patient_id]
        return list_response(records, serializers.visit)


# ---------------- Compliance ----------------

def _append_compliance_check(visit_id, outcome, matched_license_id, reason_code):
    record = store.create_lean({
        "visit_id": visit_id,
        "outcome": outcome,
        "matched_license_id": matched_license_id,
        "reason_code": reason_code,
    })
    db.compliance_checks[record["id"]] = record
    return record


@bp.route("/visits/<vid>/run-compliance", methods=["POST"])
def run_compliance(vid):
    user_id, role = require_auth()
    require_role(role, {"Physician"})
    with db.lock:
        v = lookup.visit(vid)
        # Ownership: physician owns the visit.
        if v["physician_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Physician does not own this visit.")
        # State precondition (priority 9).
        if v["status"] != "REQUESTED":
            raise err(ERR_INVALID_STATE, "Visit must be REQUESTED to run compliance.")
        phys = db.physicians.get(v["physician_id"])
        # Physician.status must be ACTIVE (PRD §3.3) — treated as a state objection.
        if phys is None or phys["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Physician is not ACTIVE.")

        # Modality rule (priority 12): AUDIO_ONLY cannot be cleared.
        if v["modality"] == "AUDIO_ONLY":
            _append_compliance_check(vid, "BLOCKED", None, "AUDIO_ONLY_NOT_PERMITTED")
            raise err(ERR_MODALITY_NOT_PERMITTED, "AUDIO_ONLY visit cannot be compliance-cleared.")

        # Licensure rule (priority 13).
        selected, blocked_reason = compliance.select_license(
            v["physician_id"], v["determined_state_code"])
        if selected is None:
            _append_compliance_check(vid, "BLOCKED", None, blocked_reason)
            raise err(ERR_NO_LICENSE_IN_STATE,
                      "Physician has no governing ACTIVE license in the determined state.")

        # CLEARED.
        _append_compliance_check(vid, "CLEARED", selected["id"], "LICENSE_MATCH")
        v["status"] = "COMPLIANCE_CLEARED"
        store.touch(v)
        return success_object(serializers.visit(v))


@bp.route("/visits/<vid>/override-compliance", methods=["POST"])
def override_compliance(vid):
    _user_id, role = require_auth()
    require_role(role, {"ComplianceOfficer"})
    with db.lock:
        v = lookup.visit(vid)
        if v["status"] != "REQUESTED":
            raise err(ERR_INVALID_STATE, "Visit must be REQUESTED to override.")
        # Most recent ComplianceCheck must be BLOCKED.
        checks = [c for c in db.compliance_checks.values() if c["visit_id"] == vid]
        if not checks:
            raise err(ERR_INVALID_STATE, "No prior blocked compliance check to override.")
        checks.sort(key=lambda c: (db.parse_iso(c["created_at"]).timestamp(), c.get("_seq", 0)))
        if checks[-1]["outcome"] != "BLOCKED":
            raise err(ERR_INVALID_STATE, "Most recent compliance check is not BLOCKED.")
        _append_compliance_check(vid, "OVERRIDDEN", None, "OFFICER_OVERRIDE")
        v["status"] = "COMPLIANCE_CLEARED"
        store.touch(v)
        return success_object(serializers.visit(v))


# ---------------- Approval + routing ----------------

@bp.route("/visits/<vid>/approve", methods=["POST"])
def approve_visit(vid):
    user_id, role = require_auth()
    require_role(role, {"Physician"})
    with db.lock:
        v = lookup.visit(vid)
        if v["physician_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Physician does not own this visit.")
        if v["status"] != "COMPLIANCE_CLEARED":
            raise err(ERR_INVALID_STATE, "Visit must be COMPLIANCE_CLEARED to approve.")

        patient = db.patients.get(v["patient_id"])
        insured = patient is not None and patient.get("insurance_payer_id") is not None

        if insured:
            payer = db.payers.get(patient["insurance_payer_id"])
            v["routing"] = "INSURANCE"
            v["patient_cost_cents"] = patient_cost_insurance(v["list_fee_cents"], payer)
            v["status"] = "APPROVED_INSURANCE"
            store.touch(v)
            # CASCADE: create + pre-adjudicate a Claim.
            allowed, plan_paid = claim_adjudication(v["list_fee_cents"], payer)
            claim = store.create_full({
                "visit_id": v["id"],
                "payer_id": patient["insurance_payer_id"],
                "billed_cents": v["list_fee_cents"],
                "allowed_cents": allowed,
                "plan_paid_cents": plan_paid,
                "status": "SUBMITTED",
            })
            db.claims[claim["id"]] = claim
        else:
            v["routing"] = "SELF_PAY"
            v["patient_cost_cents"] = patient_cost_self_pay(
                v["list_fee_cents"], v["platform_fee_cents"])
            v["status"] = "APPROVED_SELF_PAY"
            store.touch(v)

        return success_object(serializers.visit(v))


@bp.route("/visits/<vid>/complete", methods=["POST"])
def complete_visit(vid):
    user_id, role = require_auth()
    require_role(role, {"Physician"})
    with db.lock:
        v = lookup.visit(vid)
        if v["physician_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Physician does not own this visit.")
        if v["status"] not in ("APPROVED_INSURANCE", "APPROVED_SELF_PAY"):
            raise err(ERR_INVALID_STATE, "Visit must be APPROVED to complete.")
        v["status"] = "COMPLETED"
        store.touch(v)
        completed_at = v["updated_at"]  # updated_at at the instant it reached COMPLETED
        # CASCADE: create FollowUp.
        due_dt = db.parse_iso(completed_at) + timedelta(days=FOLLOW_UP_INTERVAL_DAYS)
        fu = store.create_full({
            "source_visit_id": v["id"],
            "due_at": db.iso_millis(due_dt),
            "linked_visit_id": None,
            "status": "OPEN",
        })
        db.follow_ups[fu["id"]] = fu
        return success_object(serializers.visit(v))


@bp.route("/visits/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    user_id, role = require_auth()
    require_role(role, {"Patient"})
    with db.lock:
        v = lookup.visit(vid)
        if v["patient_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Patient does not own this visit.")
        if v["status"] not in ("REQUESTED", "COMPLIANCE_CLEARED"):
            raise err(ERR_INVALID_STATE, "Visit must be REQUESTED or COMPLIANCE_CLEARED to cancel.")
        v["status"] = "CANCELLED"
        store.touch(v)
        return success_object(serializers.visit(v))


# ---------------- Compliance-check log reads ----------------

@bp.route("/visits/<vid>/compliance-checks", methods=["GET"])
def list_visit_compliance_checks(vid):
    with db.lock:
        lookup.visit(vid)
        records = [c for c in db.compliance_checks.values() if c["visit_id"] == vid]
        return list_response(records, serializers.compliance_check)


@bp.route("/state-licenses/<sid>/compliance-checks", methods=["GET"])
def list_license_compliance_checks(sid):
    with db.lock:
        lookup.state_license(sid)
        records = [c for c in db.compliance_checks.values()
                   if c.get("matched_license_id") == sid]
        return list_response(records, serializers.compliance_check)


# ---------------- Prescriptions ----------------

def _governing_license_for_visit(visit_id):
    """The StateLicense named by the most recent CLEARED ComplianceCheck."""
    checks = [c for c in db.compliance_checks.values()
              if c["visit_id"] == visit_id and c["outcome"] == "CLEARED"
              and c.get("matched_license_id")]
    if not checks:
        return None
    checks.sort(key=lambda c: (db.parse_iso(c["created_at"]).timestamp(), c.get("_seq", 0)))
    return db.state_licenses.get(checks[-1]["matched_license_id"])


def _dea_recency_ok(visit):
    """True if a qualifying prior COMPLETED in-state visit is within the window."""
    candidates = []
    for v in db.visits.values():
        if v["status"] != "COMPLETED":
            continue
        if v["patient_id"] != visit["patient_id"]:
            continue
        if v["physician_id"] != visit["physician_id"]:
            continue
        if v["determined_state_code"] != visit["determined_state_code"]:
            continue
        if v["id"] == visit["id"]:
            continue
        candidates.append(v)
    if not candidates:
        return False
    # most recent by completed_at (updated_at at COMPLETED), tie-break earliest created_at.
    def key(v):
        return (db.parse_iso(v["updated_at"]).timestamp(),
                -db.parse_iso(v["created_at"]).timestamp())
    candidates.sort(key=key)
    most_recent = candidates[-1]
    completed_at = db.parse_iso(most_recent["updated_at"])
    now = db.clock_now()
    delta_days = (now - completed_at).total_seconds() / 86400.0
    return delta_days <= DEA_EXAM_RECENCY_DAYS


@bp.route("/visits/<vid>/prescriptions", methods=["POST"])
def author_prescription(vid):
    user_id, role = require_auth()
    require_role(role, {"Physician"})
    with db.lock:
        v = lookup.visit(vid)
        if v["physician_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Physician does not own this visit.")

        body = validate.get_body()
        # Priority 4: body well-formedness.
        drug_name = validate.require_str(body, "drug_name")
        dea_schedule = validate.require_enum(body, "dea_schedule", {"NONE", "II", "III", "IV", "V"})
        days_supply = validate.require_int_gt(body, "days_supply", 0)
        expected_version = validate.optional_int(body, "expected_visit_prescription_version", None)

        # Priority 9: visit state must allow prescribing.
        if v["status"] not in ("COMPLIANCE_CLEARED", "APPROVED_INSURANCE", "APPROVED_SELF_PAY"):
            raise err(ERR_INVALID_STATE, "Visit must be cleared or approved to author a prescription.")

        controlled = dea_schedule != "NONE"

        if controlled:
            phys = db.physicians.get(v["physician_id"])
            gov_license = _governing_license_for_visit(vid)

            # Priority 10: DEA recency-and-modality rule.
            recency_ok = _dea_recency_ok(v)
            video = v["modality"] == "VIDEO"
            if dea_schedule == "II":
                dea_ok = recency_ok and video
            else:  # III, IV, V
                dea_ok = recency_ok or video
            if not dea_ok:
                raise err(ERR_DEA_EXAM_REQUIRED,
                          "Controlled-substance prescription fails the DEA exam-recency/modality rule.")

            # Priority 11: controlled-substance authority.
            has_dea_number = phys is not None and phys.get("dea_number") is not None
            has_state_authority = gov_license is not None and gov_license.get("controlled_substance_authority") is True
            if not (has_dea_number and has_state_authority):
                raise err(ERR_NO_CONTROLLED_AUTHORITY,
                          "Missing physician DEA number or state controlled-substance authority.")

            # Priority 14: OCC stale-version check.
            if expected_version != v["prescription_version"]:
                raise err(ERR_STALE_PRESCRIPTION_VERSION,
                          "expected_visit_prescription_version does not match current prescription_version.")

        # Create the new ACTIVE prescription.
        rx = store.create_full({
            "visit_id": vid,
            "drug_name": drug_name,
            "dea_schedule": dea_schedule,
            "days_supply": days_supply,
            "status": "ACTIVE",
        })
        db.prescriptions[rx["id"]] = rx

        if controlled:
            # Supersede a prior ACTIVE controlled rx of the SAME drug_name on this visit.
            prior = [
                p for p in db.prescriptions.values()
                if p["visit_id"] == vid and p["id"] != rx["id"]
                and p["status"] == "ACTIVE" and p["drug_name"] == drug_name
                and p["dea_schedule"] != "NONE"
            ]
            if prior:
                for p in prior:
                    p["status"] = "SUPERSEDED"
                    store.touch(p)
                v["prescription_version"] = v["prescription_version"] + 1
                store.touch(v)

        return success_object(serializers.prescription(rx), status=201)


@bp.route("/visits/<vid>/prescriptions", methods=["GET"])
def list_visit_prescriptions(vid):
    with db.lock:
        lookup.visit(vid)
        records = [p for p in db.prescriptions.values() if p["visit_id"] == vid]
        return list_response(records, serializers.prescription)


@bp.route("/prescriptions/<pid>", methods=["GET"])
def get_prescription(pid):
    with db.lock:
        p = lookup.prescription(pid)
        return success_object(serializers.prescription(p))


# ---------------- Claims (reads + adjudicate) ----------------

@bp.route("/visits/<vid>/claims", methods=["GET"])
def list_visit_claims(vid):
    with db.lock:
        lookup.visit(vid)
        records = [c for c in db.claims.values() if c["visit_id"] == vid]
        return list_response(records, serializers.claim)


@bp.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    with db.lock:
        c = lookup.claim(cid)
        return success_object(serializers.claim(c))


@bp.route("/claims", methods=["GET"])
def list_claims():
    with db.lock:
        records = list(db.claims.values())
        payer_id = request.args.get("payer_id")
        if payer_id is not None:
            records = [c for c in records if c["payer_id"] == payer_id]
        return list_response(records, serializers.claim)


@bp.route("/claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    _user_id, role = require_auth()
    require_role(role, {"ComplianceOfficer"})
    with db.lock:
        c = lookup.claim(cid)
        if c["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Claim must be SUBMITTED to adjudicate.")
        visit = db.visits.get(c["visit_id"])
        payer = db.payers.get(c["payer_id"])
        covered = visit["determined_state_code"] in payer["covered_state_codes"]
        if covered:
            allowed, plan_paid = claim_adjudication(c["billed_cents"], payer)
            c["allowed_cents"] = allowed
            c["plan_paid_cents"] = plan_paid
            c["status"] = "ADJUDICATED"
        else:
            c["allowed_cents"] = 0
            c["plan_paid_cents"] = 0
            c["status"] = "DENIED"
        store.touch(c)
        return success_object(serializers.claim(c))
