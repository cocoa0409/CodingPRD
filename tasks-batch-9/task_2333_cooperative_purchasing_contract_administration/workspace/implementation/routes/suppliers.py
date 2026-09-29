"""The supplier roster and its cooperative standing (PRD 3.1)."""

from flask import Blueprint

import services
from db import create_row, db, ordered, serialize
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_MEMBER, ROLE_SUPPLIER, commit, require_roles,
                        touch)
from response import created_response, object_response
from routes.common import (PERFORMANCE_TIER, QUALIFICATION_STATUS, fetch,
                           list_endpoint)
from validation import json_body, read_state_code, read_str

bp = Blueprint("suppliers", __name__)

READ_ONE_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_MEMBER,
                  ROLE_AUDITOR)
LIST_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_MEMBER, ROLE_AUDITOR)

QUALIFICATION_ACTIONS = ("QUALIFY", "SUSPEND", "REINSTATE", "DEBAR")


@bp.route("/coop/suppliers", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def create_supplier():
    body = json_body(allowed=("legal_name", "home_state_code"),
                     required=("legal_name", "home_state_code"))
    legal_name = read_str(body, "legal_name", required=True, min_len=1, max_len=200)
    home_state = read_state_code(body, "home_state_code", required=True)

    for existing in db.suppliers.values():
        if existing["legal_name"] == legal_name:
            fail("ERR_DUPLICATE_SUPPLIER_NAME",
                 "legal_name %s is already registered" % legal_name)

    row = create_row(
        db.suppliers,
        legal_name=legal_name,
        home_state_code=home_state,
        qualification_status="UNQUALIFIED",
        performance_score=100.0,
        deduction_points_total=0.0,
        performance_tier="PREFERRED",
        substantiated_complaint_count=0,
        fee_assessed_cents_total=0,
        fee_remitted_cents_total=0,
        delinquent_report_count=0,
    )
    return created_response(serialize(row))


@bp.route("/coop/suppliers", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_suppliers():
    return list_endpoint(
        lambda: ordered(db.suppliers),
        {"home_state_code": ("home_state_code", None),
         "qualification_status": ("qualification_status", QUALIFICATION_STATUS),
         "performance_tier": ("performance_tier", PERFORMANCE_TIER)},
    )


@bp.route("/coop/suppliers/<supplier_id>", methods=["GET"])
@require_roles(*READ_ONE_ROLES)
def read_supplier(supplier_id):
    row = fetch(db.suppliers, supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    return object_response(serialize(row))


@bp.route("/coop/suppliers/<supplier_id>/qualification", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def qualification(supplier_id):
    body = json_body(allowed=("action", "note"), required=("action",))
    action = read_str(body, "action", required=True, enum=QUALIFICATION_ACTIONS)
    read_str(body, "note")

    supplier = fetch(db.suppliers, supplier_id, "ERR_SUPPLIER_NOT_FOUND")

    # 6. qualification resolves the supplier's home state configuration row
    if action == "QUALIFY":
        if services.rule_for_state(supplier["home_state_code"]) is None:
            fail("ERR_STATE_LAW_RULE_NOT_FOUND",
                 "no configuration row for state_code %s"
                 % supplier["home_state_code"])

    # 24. from-state, plus the tier condition on REINSTATE
    standing = supplier["qualification_status"]
    expected = {
        "QUALIFY": ("UNQUALIFIED",),
        "SUSPEND": ("QUALIFIED",),
        "REINSTATE": ("SUSPENDED",),
        "DEBAR": ("QUALIFIED", "SUSPENDED"),
    }[action]
    if standing not in expected:
        fail("ERR_SUPPLIER_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, standing))
    if action == "REINSTATE" and supplier["performance_tier"] == "PROBATION":
        fail("ERR_SUPPLIER_INVALID_STATE",
             "a supplier on PROBATION may not be reinstated")

    if action == "QUALIFY":
        supplier["qualification_status"] = "QUALIFIED"
        touch(supplier)
    elif action == "SUSPEND":
        services.system_suspend_supplier(supplier)
    elif action == "REINSTATE":
        supplier["qualification_status"] = "QUALIFIED"
        touch(supplier)
    else:  # DEBAR
        supplier["qualification_status"] = "DEBARRED"
        touch(supplier)
        for contract in services.contracts_of_supplier(supplier_id):
            services.system_terminate_contract(contract)

    commit()
    return object_response(serialize(supplier))
