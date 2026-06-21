"""Audit + Attestation endpoints (PRD §3.9)."""

from datetime import timedelta

from flask import Blueprint, g, request

import clock
import errors
import serialize
import services.cycle as cycle_service
import services.risk as risk_service
from common import (
    get_json_body,
    require_string,
    require_number,
    require_field,
    enum_field,
    parse_pagination,
    paginate,
)
from db import db
from middleware import require_roles
from models import new_full_record, new_lightweight_record, bump
from response import success_object, success_list
from routes.renewal_cycles import get_cycle_or_404
from routes.licensees import get_licensee_or_404
from util import as_decimal

bp = Blueprint("audits", __name__)

NON_TERMINAL_AUDIT = ("INITIATED", "ATTESTATION_PENDING", "UNDER_REVIEW")


def get_audit_or_404(audit_id):
    a = db.audits.get(audit_id)
    if a is None:
        raise errors.not_found(f"Audit '{audit_id}' not found.")
    return a


@bp.route("/audits", methods=["POST"])
@require_roles("BoardAdmin")
def initiate_audit():
    body = get_json_body()
    cycle_id = require_string(body, "cycle_id")
    cycle = get_cycle_or_404(cycle_id)

    with db.lock:
        # State gate (priority 5): cycle must be OPEN or REQUIREMENTS_MET.
        if cycle["status"] not in ("OPEN", "REQUIREMENTS_MET"):
            raise errors.invalid_state(
                "Cycle must be OPEN or REQUIREMENTS_MET to initiate an audit."
            )

        # Cooldown (priority 10): now >= last closed audit's closed_at + cooldown.
        board = db.license_boards[cycle["board_id"]]
        licensee_id = cycle["licensee_id"]
        now = clock.now()
        last_closed_at = None
        for a in db.audits.values():
            if a["licensee_id"] != licensee_id:
                continue
            if a["status"] in ("PASSED", "FAILED") and a["closed_at"] is not None:
                if last_closed_at is None or a["closed_at"] > last_closed_at:
                    last_closed_at = a["closed_at"]
        if last_closed_at is not None:
            buffer_end = last_closed_at + timedelta(days=board["audit_cooldown_days"])
            if now < buffer_end:
                raise errors.audit_cooldown_active(
                    "Audit cooldown buffer has not fully elapsed."
                )

        # Single-open (priority 11): no non-terminal audit for this cycle.
        for a in db.audits.values():
            if a["cycle_id"] == cycle_id and a["status"] in NON_TERMINAL_AUDIT:
                raise errors.audit_already_open(
                    "A non-terminal audit already exists for this cycle."
                )

        rec = new_full_record()
        rec.update({
            "cycle_id": cycle_id,
            "licensee_id": licensee_id,
            "initiated_by_user_id": g.user_id,
            "decided_by_user_id": None,
            "status": "INITIATED",
            "initiated_at": rec["created_at"],
            "closed_at": None,
        })
        db.audits[rec["id"]] = rec

        # Cycle -> AUDIT_HOLD (from OPEN or REQUIREMENTS_MET).
        cycle["status"] = "AUDIT_HOLD"
        bump(cycle)

    return success_object(serialize.audit(rec), status=201)


@bp.route("/audits/<audit_id>", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def get_audit(audit_id):
    a = get_audit_or_404(audit_id)
    return success_object(serialize.audit(a), status=200)


@bp.route("/audits", methods=["GET"])
@require_roles("BoardAdmin", "Auditor")
def list_audits():
    limit, offset = parse_pagination()
    licensee_id = request.args.get("licensee_id")
    cycle_id = request.args.get("cycle_id")
    items = list(db.audits.values())
    if licensee_id is not None:
        items = [a for a in items if a["licensee_id"] == licensee_id]
    if cycle_id is not None:
        items = [a for a in items if a["cycle_id"] == cycle_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.audit(a) for a in page], limit, offset, total, status=200,
    )


@bp.route("/renewal-cycles/<cycle_id>/audits", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def list_cycle_audits(cycle_id):
    get_cycle_or_404(cycle_id)
    limit, offset = parse_pagination()
    items = [a for a in db.audits.values() if a["cycle_id"] == cycle_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.audit(a) for a in page], limit, offset, total, status=200,
    )


@bp.route("/audits/<audit_id>/request-attestation", methods=["POST"])
@require_roles("BoardAdmin", "Auditor")
def request_attestation(audit_id):
    a = get_audit_or_404(audit_id)
    with db.lock:
        if a["status"] not in ("INITIATED", "UNDER_REVIEW"):
            raise errors.invalid_state(
                "Audit must be INITIATED or UNDER_REVIEW to request attestation."
            )
        a["status"] = "ATTESTATION_PENDING"
        bump(a)
    return success_object(serialize.audit(a), status=200)


@bp.route("/audits/<audit_id>/attestations", methods=["POST"])
@require_roles("Licensee")
def submit_attestation(audit_id):
    a = get_audit_or_404(audit_id)
    body = get_json_body()
    statement = require_string(body, "statement")
    attested_hours = require_number(body, "attested_hours")

    # Ownership: the owning Licensee attests (audit.licensee_id == X-User-ID).
    if g.user_role == "Licensee" and g.user_id != a["licensee_id"]:
        raise errors.not_resource_owner(
            "Only the audited licensee may submit an attestation."
        )

    with db.lock:
        if a["status"] != "ATTESTATION_PENDING":
            raise errors.invalid_state(
                "Audit must be ATTESTATION_PENDING to submit an attestation."
            )

        att = new_lightweight_record()
        att.update({
            "audit_id": audit_id,
            "statement": statement,
            "attested_hours": attested_hours,
        })
        db.attestations[att["id"]] = att

        a["status"] = "UNDER_REVIEW"
        bump(a)

        # Recompute the licensee's audit_risk_score (review_final variant).
        licensee = db.licensees[a["licensee_id"]]
        new_score = risk_service.compute_review_final(licensee["id"])
        if new_score != licensee["audit_risk_score"]:
            licensee["audit_risk_score"] = new_score
            bump(licensee)

    return success_object(serialize.attestation(att), status=201)


@bp.route("/audits/<audit_id>/attestations", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def list_attestations(audit_id):
    get_audit_or_404(audit_id)
    limit, offset = parse_pagination()
    items = [t for t in db.attestations.values() if t["audit_id"] == audit_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.attestation(t) for t in page], limit, offset, total, status=200,
    )


def _latest_attestation(audit_id):
    atts = [t for t in db.attestations.values() if t["audit_id"] == audit_id]
    if not atts:
        return None
    atts.sort(key=lambda r: r["created_at"])
    return atts[-1]


@bp.route("/audits/<audit_id>/decide", methods=["POST"])
@require_roles("Auditor")
def decide_audit(audit_id):
    a = get_audit_or_404(audit_id)
    body = get_json_body()
    decision = enum_field(body, "decision", {"PASS", "FAIL"})

    with db.lock:
        # State gate (priority 5): must be UNDER_REVIEW.
        if a["status"] != "UNDER_REVIEW":
            raise errors.invalid_state("Audit must be UNDER_REVIEW to decide.")

        # Segregation of duties (priority 7): decider != initiator.
        if g.user_id == a["initiated_by_user_id"]:
            raise errors.segregation_of_duties(
                "The auditor deciding an audit must not be the initiating BoardAdmin."
            )

        cycle = db.renewal_cycles[a["cycle_id"]]
        latest = _latest_attestation(audit_id)
        attested = latest["attested_hours"] if latest is not None else None
        hours_match = (
            attested is not None
            and as_decimal(attested) == as_decimal(cycle["final_earned_hours"])
        )

        # PASS iff decision == PASS and attested_hours == final_earned_hours.
        # Otherwise FAIL (decision == FAIL, or mismatch even on a PASS decision).
        if decision == "PASS" and hours_match:
            a["status"] = "PASSED"
        else:
            a["status"] = "FAILED"

        a["decided_by_user_id"] = g.user_id
        a["closed_at"] = clock.now()
        bump(a)

        # Bubble-up to the held cycle.
        if a["status"] == "PASSED":
            if cycle_service.requirement_met(cycle):
                cycle["status"] = "REQUIREMENTS_MET"
                cycle["carryover_out_hours"] = cycle_service.compute_carryover_out(cycle)
            else:
                cycle["status"] = "OPEN"
                cycle["carryover_out_hours"] = 0
            bump(cycle)
        else:  # FAILED
            cycle["status"] = "LAPSED"
            cycle["carryover_out_hours"] = 0
            bump(cycle)

    return success_object(serialize.audit(a), status=200)
