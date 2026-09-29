"""Fair lending analysis from register data (PRD 3.9)."""

from flask import Blueprint

import calc
import constants as C
import serializers as S
import store
from auth import authenticate
from errors import fail
from response import object_response
from validate import Field, check, json_body, lookup

bp = Blueprint("fairlending", __name__)

CREATE_FIELDS = [
    Field("institution_id", "string", required=True),
    Field("basis", "string", required=True, enum=C.FAIR_LENDING_BASES),
    Field("control_group_code", "string", required=True),
    Field("protected_group_code", "string", required=True),
    Field("period_start", "datetime", required=True),
    Field("period_end", "datetime", required=True),
]


def _applicant_entry(application_id):
    for entry in store.ordered(store.demographic_entries.values()):
        if entry["application_id"] == application_id and entry["applicant_role"] == "APPLICANT":
            return entry
    return None


def _in_group(app, basis, code):
    entry = _applicant_entry(app["id"])
    if entry is None:
        return False
    if basis == "RACE":
        return code in (entry["race_codes"] or [])
    if basis == "ETHNICITY":
        return code in (entry["ethnicity_codes"] or [])
    return entry["sex_code"] == code


@bp.route("/hmda/fair-lending-analyses", methods=["POST"])
def create_fair_lending_analysis():
    authenticate(["ComplianceAnalyst"])
    body = check(json_body(), CREATE_FIELDS)
    inst = lookup(store.institutions, body["institution_id"], "ERR_INSTITUTION_NOT_FOUND")

    universe = [a for a in store.ordered(store.applications.values())
                if a["institution_id"] == inst["id"]
                and a["action_taken"] is not None
                and a["action_taken_date"] is not None
                and a["action_taken_date"] >= body["period_start"]
                and a["action_taken_date"] <= body["period_end"]
                and a["is_superseded"] is False
                and a["lar_status"] != "EXCLUDED"]

    basis = body["basis"]
    control = [a for a in universe if _in_group(a, basis, body["control_group_code"])]
    protected = [a for a in universe if _in_group(a, basis, body["protected_group_code"])]

    # step 16 -- both groups must be non-empty
    if not control or not protected:
        fail("ERR_EMPTY_CONTROL_GROUP")

    control_denied = sum(1 for a in control if a["action_taken"] in C.DENIAL_ACTIONS)
    protected_denied = sum(1 for a in protected if a["action_taken"] in C.DENIAL_ACTIONS)

    control_rate, protected_rate, index, flag = calc.fair_lending_index(
        control_denied, len(control), protected_denied, len(protected))

    inst["_analysis_index"] += 1
    row = store.new_row()
    row.update({
        "institution_id": inst["id"],
        "analysis_index": inst["_analysis_index"],
        "basis": basis,
        "control_group_code": body["control_group_code"],
        "protected_group_code": body["protected_group_code"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "control_total": len(control),
        "control_denied": control_denied,
        "protected_total": len(protected),
        "protected_denied": protected_denied,
        "control_denial_rate_pct": calc.as_float(control_rate),
        "protected_denial_rate_pct": calc.as_float(protected_rate),
        "disparity_index": calc.as_float(index),
        "significance_flag": flag,
        "status": "ESCALATED" if flag == "SEVERE" else "CLEARED",
    })
    store.fair_lending_analyses[row["id"]] = row
    return object_response(S.fair_lending_analysis(row), 201)
