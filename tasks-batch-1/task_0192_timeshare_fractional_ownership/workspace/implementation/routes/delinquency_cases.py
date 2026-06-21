"""DelinquencyCase routes: get, list, escalate, foreclose."""
from flask import request

from db import db, touch
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, list_response
from services.util import serialize
from services.calc import late_charge_delta
from services.cascade import (
    contract_has_delinquent_invoice,
    suspend_contract,
    foreclose_or_terminate_contract,
)


def serialize_case(c):
    return serialize(c)


def register(app):
    @app.route("/delinquency-cases/<case_id>", methods=["GET"])
    def get_case(case_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "ComplianceOfficer", "Owner"])
        c = get_or_404(db.delinquency_cases, case_id)
        return success(serialize_case(c))

    @app.route("/delinquency-cases", methods=["GET"])
    def list_cases():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "ComplianceOfficer", "Owner"])
        items = list(db.delinquency_cases.values())
        for key in ("contract_id", "owner_id", "trigger_invoice_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [c for c in items if c.get(key) == val]
        return list_response(items, serialize_case)

    @app.route("/delinquency-cases/<case_id>/escalate", methods=["POST"])
    def escalate_case(case_id):
        _, role = get_user_context()
        require_role(role, ["ComplianceOfficer"])
        case = get_or_404(db.delinquency_cases, case_id)
        # Valid from-state: NOTICE or LIEN.
        if case["status"] not in ("NOTICE", "LIEN"):
            raise err(errors.ERR_INVALID_STATE, "Case is not in an escalatable state.")
        contract = db.contracts[case["contract_id"]]
        # Precondition: contract still has a DELINQUENT invoice.
        if not contract_has_delinquent_invoice(contract):
            raise err(errors.ERR_NO_DELINQUENT_INVOICE, "No remaining DELINQUENT invoice.")

        first_lien = case["status"] == "NOTICE"
        case["status"] = "LIEN"
        case["escalation_periods"] += 1
        touch(case)
        # Apply late charge to each DELINQUENT invoice on the contract.
        for inv in db.invoices.values():
            if inv["contract_id"] == contract["id"] and inv["status"] == "DELINQUENT":
                delta = late_charge_delta(inv, case["late_charge_basis"])
                inv["late_charge_cents"] += delta
                touch(inv)
        # First escalation to LIEN cascades contract ACTIVE -> SUSPENDED.
        if first_lien and contract["status"] == "ACTIVE":
            suspend_contract(contract)
        return success(serialize_case(case))

    @app.route("/delinquency-cases/<case_id>/foreclose", methods=["POST"])
    def foreclose_case(case_id):
        _, role = get_user_context()
        require_role(role, ["ComplianceOfficer"])
        case = get_or_404(db.delinquency_cases, case_id)
        contract = db.contracts[case["contract_id"]]
        resort = db.resorts[contract["resort_id"]]
        # Priority 13: eligibility — case must be LIEN and escalation >= threshold.
        if case["status"] != "LIEN" or case["escalation_periods"] < resort["foreclosure_threshold_periods"]:
            raise err(errors.ERR_FORECLOSURE_NOT_ELIGIBLE, "Case is not eligible for foreclosure.")

        # Branch on ownership type.
        if contract["ownership_type"] == "DEEDED":
            case["status"] = "FORECLOSURE"
            touch(case)
            foreclose_or_terminate_contract(contract, "FORECLOSED")
        elif contract["ownership_type"] == "RIGHT_TO_USE":
            case["status"] = "TERMINATION"
            touch(case)
            foreclose_or_terminate_contract(contract, "TERMINATED")
        else:
            raise err(errors.ERR_OWNERSHIP_TYPE_MISMATCH, "Unknown ownership type.")
        return success(serialize_case(case))
