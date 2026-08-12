"""PrintBatch & Diploma routes."""
from datetime import timedelta

from flask import request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CEREMONY_POSTURE_FORBIDS,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_BATCH_NOT_RELEASABLE,
    ERR_HONOR_SNAPSHOT_STALE,
    ERR_NO_OPEN_REPRINT_BATCH,
    ERR_CORRECTION_WINDOW_CLOSED,
)
from middleware import get_caller, require_role, get_json_body, require_graduate_ownership
from response import success, success_list, parse_pagination, paginate
from services.common import (
    get_ceremony_or_404,
    get_graduate_or_404,
    get_batch_or_404,
    get_diploma_or_404,
    require_body_fields,
    require_string,
    require_enum,
    posture_gate,
    graduate_eligible_gate,
)
from services.honor import HONORS_TEXT
from services.serialize import batch_out, diploma_out

CORRECTION_WINDOW_DAYS = 30


def register(bp):
    @bp.route("/ceremonies/<cid>/print-batches", methods=["POST"])
    def create_batch(cid):
        user_id, role = get_caller()
        require_role(role, ["RegistrarOfficer"])
        ceremony = get_ceremony_or_404(cid)
        body = get_json_body(required=False)
        sched = body.get("scheduled_print_date")
        if sched is not None and not isinstance(sched, str):
            raise_err(ERR_INVALID_REQUEST, "scheduled_print_date must be a string")
        now = db.now_iso()
        bid = db.new_id()
        batch = {
            "id": bid,
            "ceremony_id": cid,
            "scheduled_print_date": sched,
            "status": "OPEN",
            "created_by_user_id": user_id,
            "released_by_user_id": None,
            "diploma_count": 0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.print_batches[bid] = batch
        return success(batch_out(batch), status=201)

    @bp.route("/print-batches/<bid>", methods=["GET"])
    def get_batch(bid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer"])
        b = get_batch_or_404(bid)
        return success(batch_out(b))

    @bp.route("/print-batches/<bid>/diplomas", methods=["POST"])
    def queue_diploma(bid):
        user_id, role = get_caller()
        require_role(role, ["RegistrarOfficer"])
        batch = get_batch_or_404(bid)
        body = get_json_body()
        require_body_fields(body, ["graduate_id"])
        g = get_graduate_or_404(body["graduate_id"])
        ceremony = get_ceremony_or_404(batch["ceremony_id"])
        printed_name = body.get("printed_name")
        if printed_name is not None and not isinstance(printed_name, str):
            raise_err(ERR_INVALID_REQUEST, "printed_name must be a string")
        if batch["status"] != "OPEN":
            raise_err(ERR_INVALID_STATE, "Batch is not OPEN")
        posture_gate(ceremony, {"AUDIT_LOCKED", "READY"})
        graduate_eligible_gate(g)

        now = db.now_iso()
        did = db.new_id()
        pinned = g["honor_tier"]
        diploma = {
            "id": did,
            "graduate_id": g["id"],
            "print_batch_id": bid,
            "printed_name": printed_name if printed_name is not None else g["full_name"],
            "honors_text": HONORS_TEXT.get(pinned, ""),
            "pinned_honor_tier": pinned,
            "corrected_name": None,
            "correction_count": 0,
            "status": "QUEUED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.diplomas[did] = diploma
        batch["diploma_count"] += 1
        batch["version"] += 1
        db.touch(batch)
        return success(diploma_out(diploma), status=201)

    @bp.route("/print-batches/<bid>/diplomas", methods=["GET"])
    def list_batch_diplomas(bid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer"])
        batch = get_batch_or_404(bid)
        limit, offset = parse_pagination(request.args)
        items = [d for d in db.diplomas.values() if d["print_batch_id"] == bid]
        items.sort(key=lambda d: d["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([diploma_out(d) for d in page], limit, offset, total)

    @bp.route("/print-batches/<bid>/release", methods=["POST"])
    def release_batch(bid):
        user_id, role = get_caller()
        require_role(role, ["RegistrarOfficer"])
        batch = get_batch_or_404(bid)
        ceremony = get_ceremony_or_404(batch["ceremony_id"])
        # SoD check (priority 6) before state checks (priority 8) per global order
        if user_id == batch["created_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES, "Releaser must differ from batch creator")
        if batch["status"] != "OPEN":
            raise_err(ERR_INVALID_STATE, "Batch is not OPEN")
        posture_gate(ceremony, {"AUDIT_LOCKED", "READY", "COMMENCED", "COMPLETED"})
        attached = [d for d in db.diplomas.values() if d["print_batch_id"] == bid]
        for d in attached:
            if d["status"] in {"QUEUED", "REPRINT_QUEUED"}:
                g = db.graduates.get(d["graduate_id"])
                if g is not None and d["pinned_honor_tier"] != g["honor_tier"]:
                    raise_err(ERR_HONOR_SNAPSHOT_STALE, "Diploma honor snapshot is stale")
        if batch["diploma_count"] < 1:
            raise_err(ERR_BATCH_NOT_RELEASABLE, "Batch has no diplomas")
        batch["status"] = "RELEASED"
        batch["released_by_user_id"] = user_id
        batch["version"] += 1
        db.touch(batch)
        return success(batch_out(batch))

    @bp.route("/print-batches/<bid>/mark-printed", methods=["POST"])
    def mark_printed(bid):
        user_id, role = get_caller()
        require_role(role, ["RegistrarOfficer"])
        batch = get_batch_or_404(bid)
        if batch["status"] != "RELEASED":
            raise_err(ERR_INVALID_STATE, "Batch is not RELEASED")
        for d in db.diplomas.values():
            if d["print_batch_id"] == bid and d["status"] in {"QUEUED", "REPRINT_QUEUED"}:
                d["status"] = "PRINTED"
                d["version"] += 1
                db.touch(d)
        batch["status"] = "PRINTED"
        batch["version"] += 1
        db.touch(batch)
        return success(batch_out(batch))

    @bp.route("/diplomas/<did>", methods=["GET"])
    def get_diploma(did):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        d = get_diploma_or_404(did)
        require_graduate_ownership(user_id, role, d["graduate_id"])
        return success(diploma_out(d))

    @bp.route("/diplomas/<did>/issue", methods=["POST"])
    def issue_diploma(did):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        d = get_diploma_or_404(did)
        g = get_graduate_or_404(d["graduate_id"])
        ceremony = get_ceremony_or_404(g["ceremony_id"])
        if d["status"] != "PRINTED":
            raise_err(ERR_INVALID_STATE, "Diploma is not PRINTED")
        posture_gate(ceremony, {"COMMENCED"})
        d["status"] = "ISSUED"
        d["version"] += 1
        db.touch(d)
        return success(diploma_out(d))

    @bp.route("/diplomas/<did>/corrections", methods=["POST"])
    def request_correction(did):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        d = get_diploma_or_404(did)
        require_graduate_ownership(user_id, role, d["graduate_id"])
        body = get_json_body()
        require_string(body, "corrected_name")
        g = get_graduate_or_404(d["graduate_id"])
        ceremony = get_ceremony_or_404(g["ceremony_id"])
        if d["status"] != "ISSUED":
            raise_err(ERR_INVALID_STATE, "Diploma is not ISSUED")
        if db.now_dt() > db.parse_dt(ceremony["ceremony_date"]) + timedelta(days=CORRECTION_WINDOW_DAYS):
            raise_err(ERR_CORRECTION_WINDOW_CLOSED, "Correction window closed")
        d["status"] = "CORRECTION_REQUESTED"
        d["corrected_name"] = body["corrected_name"]
        d["version"] += 1
        db.touch(d)
        return success(diploma_out(d))

    @bp.route("/diplomas/<did>/correction-decision", methods=["POST"])
    def correction_decision(did):
        user_id, role = get_caller()
        require_role(role, ["RegistrarOfficer"])
        d = get_diploma_or_404(did)
        body = get_json_body()
        require_enum(body, "decision", {"APPROVED", "DENIED"})
        g = get_graduate_or_404(d["graduate_id"])
        if d["status"] != "CORRECTION_REQUESTED":
            raise_err(ERR_INVALID_STATE, "Diploma is not CORRECTION_REQUESTED")
        if body["decision"] == "APPROVED":
            open_batch = next(
                (b for b in db.print_batches.values()
                 if b["ceremony_id"] == g["ceremony_id"] and b["status"] == "OPEN"),
                None,
            )
            if open_batch is None:
                raise_err(ERR_NO_OPEN_REPRINT_BATCH, "No OPEN print batch for the ceremony")
            # detach from old batch
            old_batch = db.print_batches.get(d["print_batch_id"])
            if old_batch is not None:
                old_batch["diploma_count"] = sum(
                    1 for x in db.diplomas.values()
                    if x["print_batch_id"] == old_batch["id"] and x["id"] != d["id"]
                )
                db.touch(old_batch)
            d["print_batch_id"] = open_batch["id"]
            d["printed_name"] = d["corrected_name"]
            d["corrected_name"] = None
            d["correction_count"] += 1
            d["pinned_honor_tier"] = g["honor_tier"]
            d["honors_text"] = HONORS_TEXT.get(g["honor_tier"], "")
            d["status"] = "REPRINT_QUEUED"
            open_batch["diploma_count"] = sum(
                1 for x in db.diplomas.values() if x["print_batch_id"] == open_batch["id"]
            )
            db.touch(open_batch)
        else:
            d["corrected_name"] = None
            d["status"] = "ISSUED"
        d["version"] += 1
        db.touch(d)
        return success(diploma_out(d))
