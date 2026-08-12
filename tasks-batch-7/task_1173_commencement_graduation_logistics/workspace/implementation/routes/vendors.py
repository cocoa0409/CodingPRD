"""Vendor contract routes."""
from datetime import timedelta

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CEREMONY_POSTURE_FORBIDS,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_VENDOR_COVERAGE_OVERLAP,
    ERR_VENDOR_DELIVERABLE_MISSING,
)
from middleware import get_caller, require_role, get_json_body
from response import success
from services.common import (
    get_ceremony_or_404,
    get_vendor_contract_or_404,
    require_body_fields,
    require_string,
    require_int,
    require_enum,
    posture_gate,
)
from services.pricing import vendor_cancellation_fee
from services.serialize import vendor_out


def register(bp):
    @bp.route("/ceremonies/<cid>/vendor-contracts", methods=["POST"])
    def create_vendor_contract(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        get_ceremony_or_404(cid)
        body = get_json_body()
        require_body_fields(body, ["vendor_type", "vendor_user_id", "coverage_start_utc", "coverage_end_utc", "fee_cents"])
        require_enum(body, "vendor_type", {"LIVESTREAM", "PHOTOGRAPHY"})
        require_string(body, "vendor_user_id")
        require_string(body, "coverage_start_utc")
        require_string(body, "coverage_end_utc")
        require_int(body, "fee_cents", 0)
        buffer_min = body.get("setup_buffer_minutes", 30)
        if not isinstance(buffer_min, int) or isinstance(buffer_min, bool) or buffer_min < 0:
            raise_err(ERR_INVALID_REQUEST, "setup_buffer_minutes must be an integer >= 0")
        start = db.parse_dt(body["coverage_start_utc"])
        end = db.parse_dt(body["coverage_end_utc"])
        if end <= start:
            raise_err(ERR_INVALID_REQUEST, "coverage_end_utc must be strictly after coverage_start_utc")

        # buffered closed-interval overlap among non-CANCELLED contracts of same ceremony+vendor_type
        new_lo = start - timedelta(minutes=buffer_min)
        new_hi = end + timedelta(minutes=buffer_min)
        for c in db.vendor_contracts.values():
            if c["ceremony_id"] == cid and c["vendor_type"] == body["vendor_type"] and c["status"] != "CANCELLED":
                ex_start = db.parse_dt(c["coverage_start_utc"])
                ex_end = db.parse_dt(c["coverage_end_utc"])
                ex_lo = ex_start - timedelta(minutes=c["setup_buffer_minutes"])
                ex_hi = ex_end + timedelta(minutes=c["setup_buffer_minutes"])
                # closed intervals: touching boundaries conflict
                if new_lo <= ex_hi and ex_lo <= new_hi:
                    raise_err(ERR_VENDOR_COVERAGE_OVERLAP, "Coverage window overlaps an existing contract")

        now = db.now_iso()
        vid = db.new_id()
        contract = {
            "id": vid,
            "ceremony_id": cid,
            "vendor_type": body["vendor_type"],
            "vendor_user_id": body["vendor_user_id"],
            "coverage_start_utc": body["coverage_start_utc"],
            "coverage_end_utc": body["coverage_end_utc"],
            "setup_buffer_minutes": buffer_min,
            "fee_cents": body["fee_cents"],
            "deliverable_url": None,
            "cancellation_fee_cents": None,
            "status": "DRAFT",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.vendor_contracts[vid] = contract
        return success(vendor_out(contract), status=201)

    @bp.route("/vendor-contracts/<vid>", methods=["GET"])
    def get_vendor_contract(vid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "VenueCoordinator", "Vendor"])
        c = get_vendor_contract_or_404(vid)
        return success(vendor_out(c))

    @bp.route("/vendor-contracts/<vid>/activate", methods=["POST"])
    def activate_contract(vid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_vendor_contract_or_404(vid)
        ceremony = get_ceremony_or_404(c["ceremony_id"])
        if c["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Contract is not DRAFT")
        posture_gate(ceremony, {"AUDIT_LOCKED", "READY", "COMMENCED"})
        c["status"] = "ACTIVE"
        c["version"] += 1
        db.touch(c)
        return success(vendor_out(c))

    @bp.route("/vendor-contracts/<vid>/submit-deliverable", methods=["POST"])
    def submit_deliverable(vid):
        user_id, role = get_caller()
        require_role(role, ["Vendor"])
        c = get_vendor_contract_or_404(vid)
        if c["vendor_user_id"] != user_id:
            raise_err(ERR_FORBIDDEN_OWNERSHIP, "Vendor may only submit on own contracts")
        body = get_json_body()
        require_string(body, "deliverable_url")
        ceremony = get_ceremony_or_404(c["ceremony_id"])
        posture_gate(ceremony, {"COMMENCED", "COMPLETED"})
        c["deliverable_url"] = body["deliverable_url"]
        c["version"] += 1
        db.touch(c)
        return success(vendor_out(c))

    @bp.route("/vendor-contracts/<vid>/settle", methods=["POST"])
    def settle_contract(vid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_vendor_contract_or_404(vid)
        if c["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE, "Contract is not ACTIVE")
        if c["deliverable_url"] is None:
            raise_err(ERR_VENDOR_DELIVERABLE_MISSING, "Deliverable not submitted")
        c["status"] = "SETTLED"
        c["version"] += 1
        db.touch(c)
        return success(vendor_out(c))

    @bp.route("/vendor-contracts/<vid>/cancel", methods=["POST"])
    def cancel_contract(vid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_vendor_contract_or_404(vid)
        if c["status"] not in {"DRAFT", "ACTIVE"}:
            raise_err(ERR_INVALID_STATE, "Contract cannot be cancelled from its current status")
        c["cancellation_fee_cents"] = vendor_cancellation_fee(c)
        c["status"] = "CANCELLED"
        c["version"] += 1
        db.touch(c)
        return success(vendor_out(c))
