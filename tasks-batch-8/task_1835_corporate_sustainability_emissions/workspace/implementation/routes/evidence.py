"""Evidence items: upload (with supersession), verification, rejection (PRD 3.4)."""
from flask import Blueprint, g, request

import calc
import domain
from envelope import ok, ok_list
from errors import err, invalid_request, invalid_state, not_found, sod
from http_util import (
    ANALYST,
    READ_ROLES,
    SHA256_RE,
    STEWARD,
    get_body,
    parse_pagination,
    require_roles,
    v_enum,
    v_str,
)
from store import db, new_entity, touch

bp = Blueprint("evidence", __name__, url_prefix="/sustainability")

EVIDENCE_STATUSES = {"UPLOADED", "VERIFIED", "REJECTED", "SUPERSEDED"}


def load_evidence(evidence_id):
    item = db.evidence.get(evidence_id)
    if item is None:
        raise not_found(f"EvidenceItem {evidence_id} not found")
    return item


@bp.route("/activity-records/<record_id>/evidence", methods=["POST"])
@require_roles(STEWARD)
def upload_evidence(record_id):
    body = get_body()
    # Priority 3: path id first, then the body-supplied FK.
    rec = db.records.get(record_id)
    if rec is None:
        raise not_found(f"ActivityRecord {record_id} not found")
    superseded = None
    sup_id = body.get("supersedes_evidence_id")
    if sup_id is not None:
        if not isinstance(sup_id, str) or sup_id not in db.evidence:
            raise not_found("Field supersedes_evidence_id does not resolve to an existing resource")
        superseded = db.evidence[sup_id]
    # Priority 4: request shape.
    file_name = v_str(body, "file_name")
    digest = v_str(body, "sha256_hex")
    if not SHA256_RE.match(digest):
        raise invalid_request("Field sha256_hex must be a 64-character lowercase hex digest")
    if superseded is not None:
        if superseded["activity_record_id"] != record_id:
            raise invalid_request(
                "supersedes_evidence_id names an evidence item on a different activity record"
            )
        if superseded["status"] != "VERIFIED":
            raise invalid_state("Only a VERIFIED evidence item can be superseded")
    cycle = db.cycles[rec["cycle_id"]]
    item = new_entity(
        {
            "activity_record_id": record_id,
            "supersedes_evidence_id": sup_id,
            "file_name": file_name,
            "sha256_hex": digest,
            "status": "UPLOADED",
            "uploaded_by_user_id": g.user_id,
            "verified_by_user_id": None,
            # Retention: Dec 31 of the cycle reporting year 23:59:59Z + 7 years,
            # fixed once at creation.
            "retention_until": f"{cycle['reporting_year'] + 7}-12-31T23:59:59Z",
        }
    )
    db.evidence[item["id"]] = item
    if superseded is not None:
        # Supersession is performed by the upload itself. The replacement is
        # UPLOADED (uncovered), so readiness is recomputed and may drop.
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
        calc.recompute_readiness(cycle)
    return ok(domain.ser_evidence(item), status=201)


@bp.route("/evidence-items/<evidence_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_evidence(evidence_id):
    return ok(domain.ser_evidence(load_evidence(evidence_id)))


@bp.route("/evidence-items", methods=["GET"])
@require_roles(*READ_ROLES)
def list_evidence():
    limit, offset = parse_pagination()
    items = sorted(db.evidence.values(), key=lambda x: x["_seq"])
    record_id = request.args.get("activity_record_id")
    sup_id = request.args.get("supersedes_evidence_id")
    status = request.args.get("status")
    if record_id is not None:
        items = [e for e in items if e["activity_record_id"] == record_id]
    if sup_id is not None:
        items = [e for e in items if e["supersedes_evidence_id"] == sup_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.ser_evidence(e) for e in page], limit, offset, total)


@bp.route("/evidence-items/<evidence_id>/transition", methods=["POST"])
@require_roles(ANALYST)
def evidence_transition(evidence_id):
    item = load_evidence(evidence_id)
    body = get_body()
    to_state = v_enum(body, "to_state", EVIDENCE_STATUSES)
    # Priority 6: the item's own state permits the transition (UPLOADED only).
    if item["status"] != "UPLOADED" or to_state not in ("VERIFIED", "REJECTED"):
        raise invalid_state(
            f"EvidenceItem in status {item['status']} cannot transition to {to_state}"
        )
    rec = db.records[item["activity_record_id"]]
    cycle = db.cycles[rec["cycle_id"]]
    if to_state == "VERIFIED":
        # Priority 6: parent record state gate (verification only).
        if rec["status"] not in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
            raise invalid_state(
                f"Evidence cannot be verified while the record is {rec['status']}"
            )
    # Priority 6: parent-cycle gate.
    if cycle["status"] not in ("DATA_COLLECTION", "UNDER_REVIEW"):
        raise err(
            "ERR_CYCLE_NOT_COLLECTING",
            409,
            f"Cycle in status {cycle['status']} does not permit evidence workflow steps",
        )
    # Priority 7: segregation of duties vs the uploader.
    if g.user_id == item["uploaded_by_user_id"]:
        raise sod("The verifier/rejecter must differ from the evidence uploader")
    item["status"] = to_state
    if to_state == "VERIFIED":
        item["verified_by_user_id"] = g.user_id
        calc.recompute_readiness(cycle)
    touch(item)
    return ok(domain.ser_evidence(item))
