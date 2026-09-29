"""Incidents, damage claims and claim evidence (PRD 3.5 / 3.6 / 3.7 / 3.8)."""

from flask import Blueprint, g

import calc
import views
from core import (ALL_ROLES, ROLE_ADJUDICATOR, ROLE_ADMIN, ROLE_COMPLIANCE,
                  ROLE_GUEST, ROLE_HOST, body_json, db, fail, hours, new_row,
                  now, object_response, opt_int, opt_number, opt_string,
                  paginate, qs, qs_int, req_dt, req_enum, req_int, req_string,
                  require_auth, require_owner, touch)

bp = Blueprint("claims", __name__)

INCIDENT_TYPES = ("NOISE_VIOLATION", "OVER_OCCUPANCY", "UNAUTHORIZED_EVENT",
                  "PROPERTY_DAMAGE", "SAFETY_THREAT")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
SOURCES = ("SENSOR", "NEIGHBOR_COMPLAINT", "HOST_REPORT")
DISMISS_REASONS = ("NO_EVIDENCE", "DUPLICATE_REPORT", "GUEST_EXONERATED")
TERMINAL_INCIDENT_STATES = ("CLOSED", "DISMISSED")


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@bp.route("/rentals/incidents", methods=["POST"])
def create_incident():
    user_id, role = require_auth(ROLE_HOST, ROLE_COMPLIANCE, ROLE_ADMIN)
    body = body_json()
    reservation_id = req_string(body, "reservation_id")
    source = req_enum(body, "source", SOURCES)
    sensor_device_id = opt_string(body, "sensor_device_id")
    if source == "SENSOR" and sensor_device_id is None:
        fail("ERR_INVALID_REQUEST",
             "sensor_device_id is required when source is SENSOR")
    incident_type = req_enum(body, "incident_type", INCIDENT_TYPES)
    severity = req_enum(body, "severity", SEVERITIES)
    detected_at = req_dt(body, "detected_at")
    description = req_string(body, "description")
    decibel_reading = opt_number(body, "decibel_reading")
    observed_occupancy = opt_int(body, "observed_occupancy")
    complainant_ref = opt_string(body, "complainant_ref")

    r = db.reservations.get(reservation_id)
    if r is None:
        fail("ERR_RESERVATION_NOT_FOUND", "Reservation not found")
    if sensor_device_id is not None \
            and sensor_device_id not in db.monitoring_devices:
        fail("ERR_DEVICE_NOT_FOUND", "Monitoring device not found")
    p = db.properties.get(r["property_id"])
    if role == ROLE_HOST:
        require_owner(p["host_id"])

    row = new_row()
    row.update({
        "reservation_id": reservation_id,
        "sensor_device_id": sensor_device_id,
        "incident_type": incident_type,
        "severity": severity,
        "source": source,
        "detected_at": detected_at,
        "description": description,
        "decibel_reading": decibel_reading,
        "observed_occupancy": observed_occupancy,
        "complainant_ref": complainant_ref,
        "incident_state": "OPEN",
        "substantiated": False,
        "escalated": False,
        "law_enforcement_ref": None,
        "response_due_at": (detected_at + hours(24))
        if source == "NEIGHBOR_COMPLAINT" else None,
        "response_sla_breached": False,
        "dismiss_reason_code": None,
    })
    db.incidents[row["id"]] = row
    return object_response(views.incident_view(row)), 201


@bp.route("/rentals/incidents/<iid>", methods=["GET"])
def get_incident(iid):
    require_auth(ROLE_HOST, ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    row = db.incidents.get(iid)
    if row is None:
        fail("ERR_INCIDENT_NOT_FOUND", "Incident not found")
    return object_response(views.incident_view(row)), 200


@bp.route("/rentals/incidents", methods=["GET"])
def list_incidents():
    require_auth(ROLE_HOST, ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    rows = list(db.incidents.values())
    for param in ("reservation_id", "sensor_device_id", "incident_state",
                  "source"):
        value = qs(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return paginate(rows, views.incident_view), 200


def _incident_or_404(iid):
    row = db.incidents.get(iid)
    if row is None:
        fail("ERR_INCIDENT_NOT_FOUND", "Incident not found")
    return row


def _has_live_claim(incident_id):
    for c in db.damage_claims.values():
        if c["incident_id"] == incident_id \
                and c["claim_state"] in calc.LIVE_CLAIM_STATES:
            return True
    return False


@bp.route("/rentals/incidents/<iid>/acknowledge", methods=["POST"])
def acknowledge_incident(iid):
    require_auth(ROLE_ADJUDICATOR)
    body_json()
    i = _incident_or_404(iid)
    if i["incident_state"] in TERMINAL_INCIDENT_STATES:
        fail("ERR_ALREADY_TERMINAL", "This incident is already terminal")
    if i["incident_state"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN incident can be acknowledged")
    r = db.reservations.get(i["reservation_id"])
    p = db.properties.get(r["property_id"])
    jr = calc.prop_rule(p)
    if i["incident_type"] == "NOISE_VIOLATION":
        reading = i["decibel_reading"]
        if reading is None or reading < jr["noise_threshold_db"]:
            fail("ERR_NOISE_BELOW_THRESHOLD",
                 "decibel_reading does not reach the jurisdiction threshold")
    if i["incident_type"] == "OVER_OCCUPANCY":
        observed = i["observed_occupancy"]
        if observed is None or observed <= calc.effective_max_occupancy(p):
            fail("ERR_OCCUPANCY_WITHIN_LIMIT",
                 "observed_occupancy does not exceed the effective ceiling")
    i["incident_state"] = "ACKNOWLEDGED"
    i["substantiated"] = True
    touch(i)
    guest_row = db.guests.get(r["guest_id"])
    if guest_row is not None:
        touch(guest_row)
        calc.apply_risk_cascade(guest_row)
    return object_response(views.incident_view(i)), 200


@bp.route("/rentals/incidents/<iid>/dismiss", methods=["POST"])
def dismiss_incident(iid):
    require_auth(ROLE_ADJUDICATOR)
    body = body_json()
    dismiss_reason_code = req_enum(body, "dismiss_reason_code",
                                   DISMISS_REASONS)
    i = _incident_or_404(iid)
    if i["incident_state"] in TERMINAL_INCIDENT_STATES:
        fail("ERR_ALREADY_TERMINAL", "This incident is already terminal")
    if i["incident_state"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN incident can be dismissed")
    if _has_live_claim(i["id"]):
        fail("ERR_INCIDENT_HAS_LIVE_CLAIM",
             "A live damage claim still references this incident")
    i["dismiss_reason_code"] = dismiss_reason_code
    i["incident_state"] = "DISMISSED"
    touch(i)
    return object_response(views.incident_view(i)), 200


@bp.route("/rentals/incidents/<iid>/escalate", methods=["POST"])
def escalate_incident(iid):
    require_auth(ROLE_ADJUDICATOR)
    body = body_json()
    law_enforcement_ref = opt_string(body, "law_enforcement_ref")
    i = _incident_or_404(iid)
    if i["incident_state"] in TERMINAL_INCIDENT_STATES:
        fail("ERR_ALREADY_TERMINAL", "This incident is already terminal")
    if i["incident_state"] != "ACKNOWLEDGED":
        fail("ERR_INVALID_STATE",
             "Only an ACKNOWLEDGED incident can be escalated")
    warranted = i["severity"] == "HIGH" or i["incident_type"] in (
        "SAFETY_THREAT", "UNAUTHORIZED_EVENT")
    if not warranted:
        fail("ERR_ESCALATION_NOT_WARRANTED",
             "Escalation requires HIGH severity or a qualifying incident type")
    if law_enforcement_ref is None or law_enforcement_ref.strip() == "":
        fail("ERR_ESCALATION_NOT_WARRANTED",
             "law_enforcement_ref must be present and non-empty")
    i["law_enforcement_ref"] = law_enforcement_ref
    i["incident_state"] = "ESCALATED_LAW_ENFORCEMENT"
    i["escalated"] = True
    touch(i)
    r = db.reservations.get(i["reservation_id"])
    guest_row = db.guests.get(r["guest_id"]) if r is not None else None
    if guest_row is not None:
        touch(guest_row)
        calc.apply_risk_cascade(guest_row)
    return object_response(views.incident_view(i)), 200


@bp.route("/rentals/incidents/<iid>/close", methods=["POST"])
def close_incident(iid):
    require_auth(ROLE_ADJUDICATOR)
    body_json()
    i = _incident_or_404(iid)
    if i["incident_state"] in TERMINAL_INCIDENT_STATES:
        fail("ERR_ALREADY_TERMINAL", "This incident is already terminal")
    if i["incident_state"] not in ("ACKNOWLEDGED",
                                   "ESCALATED_LAW_ENFORCEMENT"):
        fail("ERR_INVALID_STATE",
             "Only an ACKNOWLEDGED or ESCALATED incident can be closed")
    if _has_live_claim(i["id"]):
        fail("ERR_INCIDENT_HAS_LIVE_CLAIM",
             "A live damage claim still references this incident")
    i["incident_state"] = "CLOSED"
    touch(i)
    return object_response(views.incident_view(i)), 200


# ---------------------------------------------------------------------------
# Damage claims (PRD 3.6)
# ---------------------------------------------------------------------------

DECISION_REASONS = ("DAMAGE_CONFIRMED", "PARTIAL_DEPRECIATION",
                    "EVIDENCE_INSUFFICIENT", "NORMAL_WEAR", "FRAUD_SUSPECTED",
                    "SLA_LAPSED")
TERMINAL_CLAIM_STATES = ("SETTLED", "CLOSED_DENIED")


@bp.route("/rentals/damage-claims", methods=["POST"])
def create_claim():
    require_auth(ROLE_HOST)
    body = body_json()
    reservation_id = req_string(body, "reservation_id")
    incident_id = opt_string(body, "incident_id")
    claimed_amount_cents = req_int(body, "claimed_amount_cents", minimum=1)
    description = req_string(body, "description")
    expected_reservation_version = req_int(body, "expected_reservation_version")

    r = db.reservations.get(reservation_id)
    if r is None:
        fail("ERR_RESERVATION_NOT_FOUND", "Reservation not found")
    inc = None
    if incident_id is not None:
        inc = db.incidents.get(incident_id)
        if inc is None:
            fail("ERR_INCIDENT_NOT_FOUND", "Incident not found")
    p = db.properties.get(r["property_id"])
    require_owner(p["host_id"])
    if expected_reservation_version != r["version"]:
        fail("ERR_RESERVATION_VERSION_STALE",
             "expected_reservation_version does not match the reservation")

    # 1. The stay must be finished.
    if r["stay_state"] != "COMPLETED":
        fail("ERR_STAY_NOT_COMPLETED",
             "A claim may only be filed against a COMPLETED stay")
    # 2. The host must not be under a payout hold.
    host_row = db.hosts.get(p["host_id"])
    if host_row is not None and host_row["payout_hold"]:
        fail("ERR_HOST_PAYOUT_HELD",
             "This host is under a payout hold while an appeal is pending")
    # 3. The window must still be open.
    if now() > r["claim_window_ends_at"]:
        fail("ERR_CLAIM_WINDOW_CLOSED", "The 72-hour claim window has closed")
    # 4. A linked incident must be usable.
    if inc is not None:
        if inc["reservation_id"] != reservation_id:
            fail("ERR_DUPLICATE_CLAIM_FOR_INCIDENT",
                 "That incident belongs to a different reservation")
        for other in db.damage_claims.values():
            if other["incident_id"] == incident_id \
                    and other["claim_state"] != "CLOSED_DENIED":
                fail("ERR_DUPLICATE_CLAIM_FOR_INCIDENT",
                     "Another live claim already references this incident")
    # 5. The ceiling must hold -- fiscal, evaluated last.
    if claimed_amount_cents > p["claim_ceiling_cents"]:
        fail("ERR_CLAIM_CEILING_EXCEEDED",
             "claimed_amount_cents exceeds the listing's claim ceiling")

    row = new_row()
    row.update({
        "reservation_id": reservation_id,
        "incident_id": incident_id,
        "host_id": p["host_id"],
        "claimed_amount_cents": claimed_amount_cents,
        "description": description,
        "claim_state": "AWAITING_EVIDENCE",
        "evidence_round": 1,
        "submitted_for_review_at": None,
        "sla_lapsed": False,
        "decided_at": None,
        "decided_by_user_id": None,
        "decision_reason_code": None,
        "approved_amount_cents": 0,
        "projected_recovery_cents": 0,
        "deposit_applied_cents": 0,
        "recovered_cents": 0,
        "uncovered_cents": 0,
        "host_absorbed_cents": 0,
        "appeal_round": 0,
        "appealed_by_role": None,
        "appeal_decided_by_user_id": None,
        "appeal_decision": None,
    })
    db.damage_claims[row["id"]] = row
    touch(r)
    return object_response(views.claim_view(row)), 201


@bp.route("/rentals/damage-claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_auth(*ALL_ROLES)
    row = db.damage_claims.get(cid)
    if row is None:
        fail("ERR_CLAIM_NOT_FOUND", "Damage claim not found")
    return object_response(views.claim_view(row)), 200


@bp.route("/rentals/damage-claims", methods=["GET"])
def list_claims():
    require_auth(*ALL_ROLES)
    rows = list(db.damage_claims.values())
    for param in ("reservation_id", "incident_id", "host_id", "claim_state"):
        value = qs(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return paginate(rows, views.claim_view), 200


@bp.route("/rentals/damage-claims/<cid>/settlement-summary", methods=["GET"])
def claim_settlement_summary(cid):
    require_auth(ROLE_GUEST, ROLE_HOST, ROLE_ADJUDICATOR, ROLE_ADMIN)
    row = db.damage_claims.get(cid)
    if row is None:
        fail("ERR_CLAIM_NOT_FOUND", "Damage claim not found")
    return object_response(views.settlement_summary_view(row)), 200


def _claim_or_404(cid):
    row = db.damage_claims.get(cid)
    if row is None:
        fail("ERR_CLAIM_NOT_FOUND", "Damage claim not found")
    return row


@bp.route("/rentals/damage-claims/<cid>/submit-for-review", methods=["POST"])
def submit_claim_for_review(cid):
    require_auth(ROLE_HOST)
    body_json()
    c = _claim_or_404(cid)
    require_owner(c["host_id"])
    if c["claim_state"] in TERMINAL_CLAIM_STATES:
        fail("ERR_ALREADY_TERMINAL", "This claim is already terminal")
    if c["claim_state"] != "AWAITING_EVIDENCE":
        fail("ERR_INVALID_STATE",
             "Only an AWAITING_EVIDENCE claim can be submitted for review")
    if not calc.evidence_complete(c):
        fail("ERR_EVIDENCE_INCOMPLETE",
             "The evidence set does not satisfy the requirement schedule")
    c["claim_state"] = "UNDER_REVIEW"
    c["submitted_for_review_at"] = now()
    r = db.reservations.get(c["reservation_id"])
    p = db.properties.get(r["property_id"]) if r is not None else None
    if r is not None and p is not None:
        calc.run_provisional_waterfall(c, r, p)
    touch(c)
    return object_response(views.claim_view(c)), 200


@bp.route("/rentals/damage-claims/<cid>/request-evidence", methods=["POST"])
def request_more_evidence(cid):
    require_auth(ROLE_ADJUDICATOR)
    body = body_json()
    opt_string(body, "note")
    c = _claim_or_404(cid)
    if c["claim_state"] in TERMINAL_CLAIM_STATES:
        fail("ERR_ALREADY_TERMINAL", "This claim is already terminal")
    if c["claim_state"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE",
             "Only an UNDER_REVIEW claim can be sent back for evidence")
    if c["evidence_round"] >= 2:
        fail("ERR_EVIDENCE_ROUNDS_EXHAUSTED",
             "This claim has already used both evidence rounds")
    c["claim_state"] = "AWAITING_EVIDENCE"
    c["evidence_round"] += 1
    c["submitted_for_review_at"] = None
    touch(c)
    return object_response(views.claim_view(c)), 200


@bp.route("/rentals/damage-claims/<cid>/decide", methods=["POST"])
def decide_claim(cid):
    require_auth(ROLE_ADJUDICATOR)
    body = body_json()
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    decision_reason_code = req_enum(body, "decision_reason_code",
                                    DECISION_REASONS)
    approved_amount_cents = opt_int(body, "approved_amount_cents")
    c = _claim_or_404(cid)
    if c["claim_state"] in TERMINAL_CLAIM_STATES:
        fail("ERR_ALREADY_TERMINAL", "This claim is already terminal")
    if c["claim_state"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW claim can be decided")
    r = db.reservations.get(c["reservation_id"])
    p = db.properties.get(r["property_id"]) if r is not None else None
    guest_row = db.guests.get(r["guest_id"]) if r is not None else None

    if decision == "APPROVE":
        if approved_amount_cents is None or approved_amount_cents <= 0 \
                or approved_amount_cents > c["claimed_amount_cents"]:
            fail("ERR_APPROVED_AMOUNT_INVALID",
                 "approved_amount_cents must be positive and at most the "
                 "claimed amount")
        if r is None or r["stay_state"] != "COMPLETED":
            fail("ERR_STAY_NOT_COMPLETED",
                 "The reservation must still read COMPLETED")
        c["decided_at"] = now()
        c["decided_by_user_id"] = g.user_id
        c["decision_reason_code"] = decision_reason_code
        c["approved_amount_cents"] = approved_amount_cents
        c["claim_state"] = "APPROVED"
        calc.run_final_waterfall(c, r, p, guest_row)
        if guest_row is not None:
            guest_row["approved_claim_count"] += 1
            touch(guest_row)
            calc.apply_risk_cascade(guest_row)
    else:
        if approved_amount_cents is not None and approved_amount_cents != 0:
            fail("ERR_APPROVED_AMOUNT_INVALID",
                 "A denial may not carry a non-zero approved_amount_cents")
        c["decided_at"] = now()
        c["decided_by_user_id"] = g.user_id
        c["decision_reason_code"] = decision_reason_code
        c["claim_state"] = "DENIED"
    touch(c)
    return object_response(views.claim_view(c)), 200


# ---------------------------------------------------------------------------
# Appeals (PRD 3.8)
# ---------------------------------------------------------------------------

@bp.route("/rentals/damage-claims/<cid>/appeal", methods=["POST"])
def file_appeal(cid):
    user_id, role = require_auth(ROLE_GUEST, ROLE_HOST)
    body = body_json()
    opt_string(body, "note")
    c = _claim_or_404(cid)
    if c["claim_state"] in TERMINAL_CLAIM_STATES:
        fail("ERR_ALREADY_TERMINAL", "This claim is already terminal")
    if c["claim_state"] not in ("APPROVED", "DENIED"):
        fail("ERR_INVALID_STATE",
             "Only a decided claim can be appealed")
    r = db.reservations.get(c["reservation_id"])
    if c["claim_state"] == "APPROVED":
        if role != ROLE_GUEST:
            fail("ERR_APPEAL_ROLE_MISMATCH",
                 "Only the charged guest may appeal an approval")
        require_owner(r["guest_id"])
    else:
        if role != ROLE_HOST:
            fail("ERR_APPEAL_ROLE_MISMATCH",
                 "Only the refused host may appeal a denial")
        require_owner(c["host_id"])
    if c["appeal_round"] != 0:
        fail("ERR_APPEAL_ALREADY_FILED",
             "An appeal has already been filed on this claim")
    if c["decided_at"] is None or now() > c["decided_at"] + hours(168):
        fail("ERR_APPEAL_WINDOW_CLOSED", "The 168-hour appeal window is closed")

    guest_appealed = c["claim_state"] == "APPROVED"
    c["claim_state"] = "APPEALED"
    c["appeal_round"] = 1
    c["appealed_by_role"] = role
    touch(c)
    if guest_appealed:
        host_row = db.hosts.get(c["host_id"])
        if host_row is not None:
            host_row["payout_hold"] = True
            touch(host_row)
    return object_response(views.claim_view(c)), 200


@bp.route("/rentals/damage-claims/<cid>/appeal-decision", methods=["POST"])
def decide_appeal(cid):
    require_auth(ROLE_ADJUDICATOR)
    body = body_json()
    decision = req_enum(body, "decision", ("UPHELD", "OVERTURNED"))
    decision_reason_code = body.get("decision_reason_code")
    if decision_reason_code is not None:
        decision_reason_code = req_enum(body, "decision_reason_code",
                                        DECISION_REASONS)
    approved_amount_cents = opt_int(body, "approved_amount_cents")
    c = _claim_or_404(cid)
    if c["decided_by_user_id"] is not None \
            and c["decided_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The first-instance adjudicator may not rule on the appeal")
    if c["claim_state"] in TERMINAL_CLAIM_STATES:
        fail("ERR_ALREADY_TERMINAL", "This claim is already terminal")
    if c["claim_state"] != "APPEALED":
        fail("ERR_INVALID_STATE", "Only an APPEALED claim has an appeal to rule")

    r = db.reservations.get(c["reservation_id"])
    p = db.properties.get(r["property_id"]) if r is not None else None
    guest_row = db.guests.get(r["guest_id"]) if r is not None else None
    host_row = db.hosts.get(c["host_id"])
    guest_appealed = c["appealed_by_role"] == ROLE_GUEST

    if guest_appealed and decision == "OVERTURNED":
        calc.void_allocations(c)
        if r is not None and r["deposit_state"] == "APPLIED":
            r["deposit_state"] = "HELD"
            r["deposit_applied_cents"] = 0
            touch(r)
            if guest_row is not None:
                touch(guest_row)
        c["approved_amount_cents"] = 0
        c["recovered_cents"] = 0
        c["uncovered_cents"] = 0
        c["host_absorbed_cents"] = 0
        c["deposit_applied_cents"] = 0
        c["claim_state"] = "DENIED"
        if guest_row is not None:
            guest_row["approved_claim_count"] = max(
                0, guest_row["approved_claim_count"] - 1)
            touch(guest_row)
        if host_row is not None:
            host_row["payout_hold"] = False
            touch(host_row)
    elif guest_appealed:
        c["claim_state"] = "APPROVED"
        if host_row is not None:
            host_row["payout_hold"] = False
            touch(host_row)
    elif decision == "OVERTURNED":
        if approved_amount_cents is None or approved_amount_cents <= 0 \
                or approved_amount_cents > c["claimed_amount_cents"]:
            fail("ERR_APPROVED_AMOUNT_INVALID",
                 "approved_amount_cents must be positive and at most the "
                 "claimed amount")
        c["approved_amount_cents"] = approved_amount_cents
        c["claim_state"] = "APPROVED"
        if r is not None and p is not None:
            calc.run_final_waterfall(c, r, p, guest_row)
        if guest_row is not None:
            guest_row["approved_claim_count"] += 1
            touch(guest_row)
            calc.apply_risk_cascade(guest_row)
    else:
        c["claim_state"] = "DENIED"

    c["appeal_decision"] = decision
    c["appeal_decided_by_user_id"] = g.user_id
    if decision_reason_code is not None:
        c["decision_reason_code"] = decision_reason_code
    touch(c)
    return object_response(views.claim_view(c)), 200


# ---------------------------------------------------------------------------
# Claim evidence (PRD 3.6) -- immutable, no version, no updated_at
# ---------------------------------------------------------------------------

EVIDENCE_TYPES = ("PHOTO", "RECEIPT", "REPAIR_ESTIMATE", "POLICE_REPORT",
                  "SENSOR_LOG")
MONEY_BEARING = ("RECEIPT", "REPAIR_ESTIMATE")


@bp.route("/rentals/claim-evidence", methods=["POST"])
def create_evidence():
    user_id, role = require_auth(ROLE_HOST, ROLE_GUEST)
    body = body_json()
    claim_id = req_string(body, "claim_id")
    evidence_type = req_enum(body, "evidence_type", EVIDENCE_TYPES)
    amount_cents = opt_int(body, "amount_cents")
    captured_at = req_dt(body, "captured_at")
    file_ref = req_string(body, "file_ref")

    c = db.damage_claims.get(claim_id)
    if c is None:
        fail("ERR_CLAIM_NOT_FOUND", "Damage claim not found")

    if evidence_type in MONEY_BEARING:
        if amount_cents is None or amount_cents <= 0:
            fail("ERR_EVIDENCE_AMOUNT_REQUIRED",
                 "amount_cents must be present and greater than zero for a "
                 "money-bearing artifact")
    elif amount_cents is not None:
        fail("ERR_EVIDENCE_AMOUNT_REQUIRED",
             "amount_cents must be null for this evidence_type")

    row = new_row(with_version=False)
    row.update({
        "claim_id": claim_id,
        "evidence_type": evidence_type,
        "amount_cents": amount_cents,
        "captured_at": captured_at,
        "file_ref": file_ref,
        "uploaded_by_role": role,
        "uploaded_by_user_id": user_id,
        "evidence_round": c["evidence_round"],
    })
    db.claim_evidence[row["id"]] = row
    return object_response(views.evidence_view(row)), 201


@bp.route("/rentals/claim-evidence/<eid>", methods=["GET"])
def get_evidence(eid):
    require_auth(ROLE_GUEST, ROLE_HOST, ROLE_ADJUDICATOR, ROLE_ADMIN)
    row = db.claim_evidence.get(eid)
    if row is None:
        fail("ERR_EVIDENCE_NOT_FOUND", "Claim evidence not found")
    return object_response(views.evidence_view(row)), 200


@bp.route("/rentals/claim-evidence", methods=["GET"])
def list_evidence():
    require_auth(ROLE_GUEST, ROLE_HOST, ROLE_ADJUDICATOR, ROLE_ADMIN)
    claim_id = qs("claim_id")
    evidence_type = qs("evidence_type")
    evidence_round = qs_int("evidence_round")
    rows = list(db.claim_evidence.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if evidence_type is not None:
        rows = [r for r in rows if r["evidence_type"] == evidence_type]
    if evidence_round is not None:
        rows = [r for r in rows if r["evidence_round"] == evidence_round]
    return paginate(rows, views.evidence_view), 200
