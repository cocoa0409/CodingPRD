"""PartnerInstitution endpoints."""

import db
from errors import err_not_found, err_invalid_state, err_validation
from errors import ERR_CERTIFICATION_LAPSED, raise_err
from middleware import require_roles, get_json_body, require_fields, check_string, check_enum
from response import success_object, success_list, parse_pagination
from services.common import new_entity, touch
from flask import request

CHARTER_TYPES = {"BANK", "CREDIT_UNION"}


def _serialize(inst):
    return dict(inst)


def register(bp):
    @bp.route("/partner-institutions", methods=["POST"])
    def create_institution():
        require_roles("CoalitionAdmin")
        body = get_json_body()
        require_fields(body, ["legal_name", "charter_type"])
        check_string(body["legal_name"], "legal_name")
        check_enum(body["charter_type"], CHARTER_TYPES, "charter_type")

        inst = new_entity()
        inst.update({
            "legal_name": body["legal_name"],
            "charter_type": body["charter_type"],
            "certification_status": "APPLIED",
            "certified_standard_id": None,
            "certified_at": None,
            "certification_expires_at": None,
            "accounts_opened_total": 0,
            "current_review_id": None,
        })
        db.partner_institutions[inst["id"]] = inst
        return success_object(_serialize(inst), status=201)

    @bp.route("/partner-institutions", methods=["GET"])
    def list_institutions():
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator", "FinancialCoach", "Participant")
        limit, offset = parse_pagination(request.args)
        items = sorted(db.partner_institutions.values(), key=lambda x: db.parse_dt(x["created_at"]))
        status = request.args.get("certification_status")
        csid = request.args.get("certified_standard_id")
        crid = request.args.get("current_review_id")
        if status is not None:
            items = [i for i in items if i["certification_status"] == status]
        if csid is not None:
            items = [i for i in items if i.get("certified_standard_id") == csid]
        if crid is not None:
            items = [i for i in items if i.get("current_review_id") == crid]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([_serialize(i) for i in page], limit, offset, total)

    @bp.route("/partner-institutions/<iid>", methods=["GET"])
    def get_institution(iid):
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator", "FinancialCoach", "Participant")
        inst = db.partner_institutions.get(iid)
        if inst is None:
            err_not_found("PartnerInstitution not found")
        return success_object(_serialize(inst))

    @bp.route("/partner-institutions/<iid>/suspend", methods=["POST"])
    def suspend_institution(iid):
        require_roles("CoalitionAdmin")
        inst = db.partner_institutions.get(iid)
        if inst is None:
            err_not_found("PartnerInstitution not found")
        if inst["certification_status"] != "CERTIFIED":
            err_invalid_state("Institution must be CERTIFIED to suspend")
        inst["certification_status"] = "SUSPENDED"
        touch(inst)
        return success_object(_serialize(inst))

    @bp.route("/partner-institutions/<iid>/reinstate", methods=["POST"])
    def reinstate_institution(iid):
        require_roles("CoalitionAdmin")
        inst = db.partner_institutions.get(iid)
        if inst is None:
            err_not_found("PartnerInstitution not found")
        if inst["certification_status"] != "SUSPENDED":
            err_invalid_state("Institution must be SUSPENDED to reinstate")
        expires = inst.get("certification_expires_at")
        if expires is not None and db.parse_dt(db.get_clock()) >= db.parse_dt(expires):
            raise_err(ERR_CERTIFICATION_LAPSED, "Certification has lapsed; reinstatement not allowed")
        inst["certification_status"] = "CERTIFIED"
        touch(inst)
        return success_object(_serialize(inst))
