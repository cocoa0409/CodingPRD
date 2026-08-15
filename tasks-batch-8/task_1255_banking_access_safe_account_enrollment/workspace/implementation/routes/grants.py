"""FundingGrant endpoints."""

import db
from errors import (
    err_not_found, err_invalid_state, raise_err, ERR_GRANT_HAS_PENDING_CLAIMS,
)
from middleware import require_roles, get_json_body, require_fields, check_string, check_int
from response import success_object
from services.common import new_entity, touch


def _serialize(g):
    return dict(g)


def register(bp):
    @bp.route("/funding-grants", methods=["POST"])
    def create_grant():
        require_roles("CoalitionAdmin")
        body = get_json_body()
        require_fields(body, ["funder_name", "program_year", "total_cents", "per_report_cap_cents"])
        check_string(body["funder_name"], "funder_name")
        check_int(body["program_year"], "program_year")
        check_int(body["total_cents"], "total_cents")
        check_int(body["per_report_cap_cents"], "per_report_cap_cents")

        g = new_entity()
        g.update({
            "funder_name": body["funder_name"],
            "program_year": body["program_year"],
            "total_cents": body["total_cents"],
            "per_report_cap_cents": body["per_report_cap_cents"],
            "status": "DRAFT",
            "reserved_cents": 0,
            "disbursed_cents": 0,
            "available_cents": body["total_cents"],
        })
        db.funding_grants[g["id"]] = g
        return success_object(_serialize(g), status=201)

    @bp.route("/funding-grants/<gid>", methods=["GET"])
    def get_grant(gid):
        require_roles("CoalitionAdmin", "InstitutionOfficer")
        g = db.funding_grants.get(gid)
        if g is None:
            err_not_found("FundingGrant not found")
        return success_object(_serialize(g))

    @bp.route("/funding-grants/<gid>/activate", methods=["POST"])
    def activate_grant(gid):
        require_roles("CoalitionAdmin")
        g = db.funding_grants.get(gid)
        if g is None:
            err_not_found("FundingGrant not found")
        if g["status"] not in ("DRAFT", "SUSPENDED"):
            err_invalid_state("Grant must be DRAFT or SUSPENDED to activate")
        g["status"] = "ACTIVE"
        touch(g)
        return success_object(_serialize(g))

    @bp.route("/funding-grants/<gid>/suspend", methods=["POST"])
    def suspend_grant(gid):
        require_roles("CoalitionAdmin")
        g = db.funding_grants.get(gid)
        if g is None:
            err_not_found("FundingGrant not found")
        if g["status"] != "ACTIVE":
            err_invalid_state("Grant must be ACTIVE to suspend")
        # cascade: SUBMITTED reports -> DRAFT, release reservations
        for rep in db.partner_reports.values():
            if rep["grant_id"] == g["id"] and rep["status"] == "SUBMITTED":
                rep["status"] = "DRAFT"
                touch(rep)
                g["reserved_cents"] -= rep["claim_total_cents"]
                g["available_cents"] += rep["claim_total_cents"]
        g["status"] = "SUSPENDED"
        touch(g)
        return success_object(_serialize(g))

    @bp.route("/funding-grants/<gid>/close", methods=["POST"])
    def close_grant(gid):
        require_roles("CoalitionAdmin")
        g = db.funding_grants.get(gid)
        if g is None:
            err_not_found("FundingGrant not found")
        if g["status"] != "ACTIVE":
            err_invalid_state("Grant must be ACTIVE to close")
        has_submitted = any(
            r["grant_id"] == g["id"] and r["status"] == "SUBMITTED"
            for r in db.partner_reports.values()
        )
        if has_submitted or g["reserved_cents"] != 0:
            raise_err(ERR_GRANT_HAS_PENDING_CLAIMS, "Grant has pending claims")
        g["status"] = "CLOSED"
        touch(g)
        return success_object(_serialize(g))
