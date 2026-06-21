"""Claim endpoints: create, fetch, list, estimate, finalize, submit, adjudicate
(PRD §3.9)."""
from flask import request

import db
import errors
import response
import serialize
import validation as V
from clock import parse_iso, current_utc
from gate import gate
from services import claims as claim_svc
from services import lookups


def _stay_window_end(adm):
    """Upper bound of the stay window: discharge_at if set, else now (PRD §3.9)."""
    if adm.get("discharge_at"):
        return parse_iso(adm["discharge_at"])
    return current_utc()


def register(app):
    @app.route("/snf/admissions/<aid>/claims", methods=["POST"])
    def create_claim(aid):
        gate(["BillingAnalyst"])
        adm = lookups.get_admission(aid)
        body = V.get_body()
        driving_assessment_id = V.as_str(
            V.require(body, "driving_assessment_id"), "driving_assessment_id")
        period_start_at = V.require(body, "period_start_at")
        period_end_at = V.require(body, "period_end_at")
        ps_dt = V.as_datetime(period_start_at, "period_start_at")
        pe_dt = V.as_datetime(period_end_at, "period_end_at")
        # Existence of the driving assessment (PRD §2.5).
        assessment = lookups.get_assessment(driving_assessment_id)
        # Referential: belongs to same admission and is SUBMITTED (priority 13).
        if assessment["admission_id"] != aid or assessment["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_ASSESSMENT_NOT_SUBMITTED,
                             "driving assessment must belong to this admission and be SUBMITTED")
        # Period validity (priority 15).
        if pe_dt < ps_dt:
            raise errors.err(errors.ERR_CLAIM_PERIOD_INVALID,
                             "period_end_at must be on/after period_start_at")
        admit_dt = parse_iso(adm["admit_at"])
        window_end = _stay_window_end(adm)
        if ps_dt < admit_dt or pe_dt > window_end:
            raise errors.err(errors.ERR_CLAIM_PERIOD_INVALID,
                             "claim period lies outside the stay window")
        obj = {
            "admission_id": aid,
            "driving_assessment_id": driving_assessment_id,
            "period_start_at": period_start_at,
            "period_end_at": period_end_at,
            "billed_day_count": 0,
            "estimated_amount_cents": 0,
            "final_amount_cents": 0,
            "variance_cents": 0,
            "status": "DRAFT",
        }
        db.stamp_create(obj)
        db.claims[obj["id"]] = obj
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/admissions/<aid>/claims", methods=["GET"])
    def list_admission_claims(aid):
        gate(["BillingAnalyst"])
        lookups.get_admission(aid)
        limit, offset = V.pagination(request.args)
        rows = lookups.claims_for_admission(aid)
        status = request.args.get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    @app.route("/snf/claims/<cid>", methods=["GET"])
    def get_claim(cid):
        gate(["BillingAnalyst"])
        obj = lookups.get_claim(cid)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/claims", methods=["GET"])
    def list_claims():
        gate(["BillingAnalyst"])
        limit, offset = V.pagination(request.args)
        rows = list(db.claims.values())
        for key in ("driving_assessment_id", "admission_id", "status"):
            val = request.args.get(key)
            if val is not None:
                rows = [r for r in rows if r.get(key) == val]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    @app.route("/snf/claims/<cid>/estimate", methods=["POST"])
    def estimate_claim(cid):
        gate(["BillingAnalyst"])
        claim = lookups.get_claim(cid)
        if claim["status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "claim is not DRAFT")
        adm = db.admissions.get(claim["admission_id"])
        assessment = db.assessments.get(claim["driving_assessment_id"])
        # Driving assessment must still be SUBMITTED (priority 13).
        if assessment is None or assessment["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_ASSESSMENT_NOT_SUBMITTED,
                             "driving assessment is not SUBMITTED")
        # Parent admission medicare_covered (priority 14).
        if not adm or not adm.get("medicare_covered"):
            raise errors.err(errors.ERR_NOT_MEDICARE_COVERED,
                             "admission is not medicare_covered")
        billed, total = claim_svc.price_claim(claim, adm, assessment, "estimated")
        claim["billed_day_count"] = billed
        claim["estimated_amount_cents"] = total
        claim["status"] = "ESTIMATED"
        db.touch(claim)
        return response.success(serialize.public(claim), 200)

    @app.route("/snf/claims/<cid>/finalize", methods=["POST"])
    def finalize_claim(cid):
        gate(["BillingAnalyst"])
        claim = lookups.get_claim(cid)
        if claim["status"] != "ESTIMATED":
            raise errors.err(errors.ERR_INVALID_STATE, "claim is not ESTIMATED")
        adm = db.admissions.get(claim["admission_id"])
        assessment = db.assessments.get(claim["driving_assessment_id"])
        # Blocked while any OPEN bed-hold overlaps the claim period (PRD §3.9).
        ps = parse_iso(claim["period_start_at"])
        pe = parse_iso(claim["period_end_at"])
        for bh in lookups.bed_holds_for_admission(adm["id"]):
            if bh["status"] != "OPEN":
                continue
            b_start = parse_iso(bh["leave_start_at"])
            b_end = parse_iso(bh.get("actual_return_at") or bh["expected_return_at"])
            # Overlap of [period_start, period_end] (inclusive) with [start, end).
            if b_start <= pe and ps < b_end:
                raise errors.err(errors.ERR_INVALID_STATE,
                                 "an OPEN bed-hold overlaps the claim period")
        billed, total = claim_svc.price_claim(claim, adm, assessment, "final")
        claim["billed_day_count"] = billed
        claim["final_amount_cents"] = total
        claim["variance_cents"] = total - claim["estimated_amount_cents"]
        claim["status"] = "FINALIZED"
        db.touch(claim)
        return response.success(serialize.public(claim), 200)

    @app.route("/snf/claims/<cid>/submit", methods=["POST"])
    def submit_claim(cid):
        gate(["BillingAnalyst"])
        claim = lookups.get_claim(cid)
        body = V.get_body()
        expected_version = V.as_int(
            V.require(body, "expected_claim_version"), "expected_claim_version")
        if claim["status"] != "FINALIZED":
            raise errors.err(errors.ERR_INVALID_STATE, "claim is not FINALIZED")
        # OCC (priority 20): expected_claim_version must match (PRD §2.6).
        if expected_version != claim.get("version"):
            raise errors.err(errors.ERR_STALE_VERSION,
                             "expected_claim_version does not match claim version")
        claim["status"] = "SUBMITTED"
        db.touch(claim)  # increments version by 1
        return response.success(serialize.public(claim), 200)

    @app.route("/snf/claims/<cid>/adjudicate", methods=["POST"])
    def adjudicate_claim(cid):
        gate(["BillingAnalyst"])
        claim = lookups.get_claim(cid)
        body = V.get_body()
        decision = V.as_enum(V.require(body, "decision"), "decision", {"PAID", "REJECTED"})
        if claim["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_INVALID_STATE, "claim is not SUBMITTED")
        if decision == "PAID":
            claim["status"] = "PAID"
            db.touch(claim)
            adm = db.admissions.get(claim["admission_id"])
            if adm is not None:
                adm["covered_day_count"] = adm["covered_day_count"] + claim["billed_day_count"]
                db.touch(adm)
        else:
            claim["status"] = "REJECTED"
            db.touch(claim)
        return response.success(serialize.public(claim), 200)
