"""PartnerReport endpoints with claim computation and OCC on grant version."""

import db
from errors import (
    err_not_found, err_invalid_state, err_validation, err_unauthorized, raise_err,
    ERR_STALE_VERSION, ERR_GRANT_NOT_ACTIVE, ERR_CLAIM_EXCEEDS_CAP,
    ERR_INSUFFICIENT_GRANT_FUNDS,
)
from middleware import require_roles, get_json_body, require_fields, check_string, check_int, check_enum
from response import success_object, success_list, parse_pagination
from services.common import new_entity, touch
from services.calculations import compute_claim
from flask import request

EVALUATION_MODES = {"PROVISIONAL", "FINAL"}


def _serialize(r):
    return dict(r)


def register(bp):
    @bp.route("/partner-reports", methods=["POST"])
    def create_report():
        user_id, _ = require_roles("InstitutionOfficer")
        body = get_json_body()
        require_fields(body, ["institution_id", "grant_id", "period_start", "period_end", "evaluation_mode", "expected_grant_version"])
        check_string(body["institution_id"], "institution_id")
        check_string(body["grant_id"], "grant_id")
        check_string(body["period_start"], "period_start")
        check_string(body["period_end"], "period_end")
        check_enum(body["evaluation_mode"], EVALUATION_MODES, "evaluation_mode")
        check_int(body["expected_grant_version"], "expected_grant_version")
        if db.parse_date(body["period_start"]) > db.parse_date(body["period_end"]):
            err_validation("period_start must be on or before period_end")

        if user_id != body["institution_id"]:
            err_unauthorized("InstitutionOfficer identity must equal institution_id")

        inst = db.partner_institutions.get(body["institution_id"])
        if inst is None:
            err_not_found("PartnerInstitution not found")
        grant = db.funding_grants.get(body["grant_id"])
        if grant is None:
            err_not_found("FundingGrant not found")

        # OCC check
        if body["expected_grant_version"] != grant["version"]:
            raise_err(ERR_STALE_VERSION, "expected_grant_version does not match current grant version")

        claim = compute_claim(inst["id"], body["period_start"], body["period_end"], body["evaluation_mode"])

        rep = new_entity()
        rep.update({
            "institution_id": inst["id"],
            "grant_id": grant["id"],
            "period_start": body["period_start"],
            "period_end": body["period_end"],
            "evaluation_mode": body["evaluation_mode"],
            "status": "DRAFT",
            "opened_count": claim["opened_count"],
            "opening_claim_cents": claim["opening_claim_cents"],
            "retention_rate_m6": claim["retention_rate_m6"],
            "retention_rate_m12": claim["retention_rate_m12"],
            "retention_bonus_cents": claim["retention_bonus_cents"],
            "education_stipend_cents": claim["education_stipend_cents"],
            "claim_total_cents": claim["claim_total_cents"],
        })
        db.partner_reports[rep["id"]] = rep
        # ledger anchor touch on the grant
        touch(grant)
        return success_object(_serialize(rep), status=201)

    @bp.route("/partner-reports", methods=["GET"])
    def list_reports():
        require_roles("CoalitionAdmin", "InstitutionOfficer")
        limit, offset = parse_pagination(request.args)
        items = sorted(db.partner_reports.values(), key=lambda x: db.parse_dt(x["created_at"]))
        iid = request.args.get("institution_id")
        gid = request.args.get("grant_id")
        st = request.args.get("status")
        if iid is not None:
            items = [r for r in items if r["institution_id"] == iid]
        if gid is not None:
            items = [r for r in items if r["grant_id"] == gid]
        if st is not None:
            items = [r for r in items if r["status"] == st]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([_serialize(r) for r in page], limit, offset, total)

    @bp.route("/partner-reports/<rid>", methods=["GET"])
    def get_report(rid):
        require_roles("CoalitionAdmin", "InstitutionOfficer")
        rep = db.partner_reports.get(rid)
        if rep is None:
            err_not_found("PartnerReport not found")
        return success_object(_serialize(rep))

    @bp.route("/partner-reports/<rid>/submit", methods=["POST"])
    def submit_report(rid):
        user_id, _ = require_roles("InstitutionOfficer")
        rep = db.partner_reports.get(rid)
        if rep is None:
            err_not_found("PartnerReport not found")
        if user_id != rep["institution_id"]:
            err_unauthorized("Officer must belong to the report's institution")
        if rep["status"] not in ("DRAFT", "REJECTED"):
            err_invalid_state("Report must be DRAFT or REJECTED to submit")
        grant = db.funding_grants.get(rep["grant_id"])
        if grant is None:
            err_not_found("FundingGrant not found")
        if grant["status"] != "ACTIVE":
            raise_err(ERR_GRANT_NOT_ACTIVE, "Grant must be ACTIVE to submit a report")

        # resubmit from REJECTED recomputes the claim snapshot against current data
        if rep["status"] == "REJECTED":
            claim = compute_claim(rep["institution_id"], rep["period_start"], rep["period_end"], rep["evaluation_mode"])
            rep.update(claim)

        if rep["claim_total_cents"] > grant["per_report_cap_cents"]:
            raise_err(ERR_CLAIM_EXCEEDS_CAP, "claim_total_cents exceeds per_report_cap_cents")
        if rep["claim_total_cents"] > grant["available_cents"]:
            raise_err(ERR_INSUFFICIENT_GRANT_FUNDS, "claim_total_cents exceeds available grant funds")

        rep["status"] = "SUBMITTED"
        touch(rep)
        grant["reserved_cents"] += rep["claim_total_cents"]
        grant["available_cents"] -= rep["claim_total_cents"]
        touch(grant)
        return success_object(_serialize(rep))

    @bp.route("/partner-reports/<rid>/review", methods=["POST"])
    def review_report(rid):
        require_roles("CoalitionAdmin")
        rep = db.partner_reports.get(rid)
        if rep is None:
            err_not_found("PartnerReport not found")
        body = get_json_body()
        require_fields(body, ["outcome"])
        outcome = check_enum(body["outcome"], {"APPROVE", "REJECT"}, "outcome")
        if rep["status"] != "SUBMITTED":
            err_invalid_state("Report must be SUBMITTED to review")
        grant = db.funding_grants.get(rep["grant_id"])
        if grant is None:
            err_not_found("FundingGrant not found")
        if outcome == "APPROVE":
            rep["status"] = "APPROVED"
            grant["reserved_cents"] -= rep["claim_total_cents"]
            grant["disbursed_cents"] += rep["claim_total_cents"]
        else:
            rep["status"] = "REJECTED"
            grant["reserved_cents"] -= rep["claim_total_cents"]
            grant["available_cents"] += rep["claim_total_cents"]
        touch(rep)
        touch(grant)
        return success_object(_serialize(rep))
