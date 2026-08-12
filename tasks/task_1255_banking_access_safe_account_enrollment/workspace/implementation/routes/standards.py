"""AccountStandard endpoints."""

import db
from errors import err_not_found, err_invalid_state
from middleware import (
    require_roles, get_json_body, require_fields,
    check_enum, check_string, check_int, check_bool,
)
from response import success_object
from services.common import new_entity, touch

RUBRIC_MODES = {"STANDARD_RUBRIC", "REMEDIATION_RUBRIC"}
ALT_ID_TYPES = {"MATRICULA_CONSULAR", "MUNICIPAL_ID", "FOREIGN_PASSPORT"}


def _serialize(std):
    return dict(std)


def register(bp):
    @bp.route("/account-standards", methods=["POST"])
    def create_standard():
        require_roles("CoalitionAdmin")
        body = get_json_body()
        require_fields(body, [
            "code", "name", "effective_from", "monthly_fee_cap_cents",
            "overdraft_fee_allowed", "min_opening_deposit_cap_cents",
            "accepted_alt_id_types", "chex_second_look_required",
            "requires_financial_education", "rubric_mode",
        ])
        check_string(body["code"], "code")
        check_string(body["name"], "name")
        check_string(body["effective_from"], "effective_from")
        check_int(body["monthly_fee_cap_cents"], "monthly_fee_cap_cents")
        check_bool(body["overdraft_fee_allowed"], "overdraft_fee_allowed")
        check_int(body["min_opening_deposit_cap_cents"], "min_opening_deposit_cap_cents")
        alt = body["accepted_alt_id_types"]
        if not isinstance(alt, list) or any(not isinstance(x, str) or x not in ALT_ID_TYPES for x in alt):
            from errors import err_validation
            err_validation("accepted_alt_id_types must be a subset of MATRICULA_CONSULAR|MUNICIPAL_ID|FOREIGN_PASSPORT")
        check_bool(body["chex_second_look_required"], "chex_second_look_required")
        check_bool(body["requires_financial_education"], "requires_financial_education")
        check_enum(body["rubric_mode"], RUBRIC_MODES, "rubric_mode")

        std = new_entity()
        std.update({
            "code": body["code"],
            "name": body["name"],
            "effective_from": body["effective_from"],
            "monthly_fee_cap_cents": body["monthly_fee_cap_cents"],
            "overdraft_fee_allowed": body["overdraft_fee_allowed"],
            "min_opening_deposit_cap_cents": body["min_opening_deposit_cap_cents"],
            "accepted_alt_id_types": list(alt),
            "chex_second_look_required": body["chex_second_look_required"],
            "requires_financial_education": body["requires_financial_education"],
            "rubric_mode": body["rubric_mode"],
            "status": "DRAFT",
        })
        db.account_standards[std["id"]] = std
        return success_object(_serialize(std), status=201)

    @bp.route("/account-standards/<sid>", methods=["GET"])
    def get_standard(sid):
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator", "FinancialCoach", "Participant")
        std = db.account_standards.get(sid)
        if std is None:
            err_not_found("AccountStandard not found")
        return success_object(_serialize(std))

    @bp.route("/account-standards/<sid>/activate", methods=["POST"])
    def activate_standard(sid):
        require_roles("CoalitionAdmin")
        std = db.account_standards.get(sid)
        if std is None:
            err_not_found("AccountStandard not found")
        if std["status"] != "DRAFT":
            err_invalid_state("Standard must be DRAFT to activate")
        # supersede any currently EFFECTIVE standard
        for other in db.account_standards.values():
            if other["id"] != sid and other["status"] == "EFFECTIVE":
                other["status"] = "SUPERSEDED"
                touch(other)
        std["status"] = "EFFECTIVE"
        touch(std)
        return success_object(_serialize(std))
