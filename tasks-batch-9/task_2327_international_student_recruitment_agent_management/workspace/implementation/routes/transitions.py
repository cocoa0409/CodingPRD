"""Student-file custody transition records (PRD 3.9)."""

from flask import Blueprint

import errors
import serializers
from db import db
from response import obj
from routes.common import auth, listing, need
from services import calc
from validation import query_enum, query_str

bp = Blueprint("transitions", __name__)


@bp.route("/recruitment/file-transitions/<transition_id>", methods=["GET"])
def read_transition(transition_id):
    auth("RecruitmentOfficer", "ComplianceOfficer")
    record = need(db.transitions, transition_id, errors.ERR_TRANSITION_NOT_FOUND)
    return obj(serializers.transition(record))


@bp.route("/recruitment/file-transitions", methods=["GET"])
def list_transitions():
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "AgencyOwner")
    application_id = query_str("application_id")
    from_agency_id = query_str("from_agency_id")
    to_agency_id = query_str("to_agency_id")
    trigger_contract_id = query_str("trigger_contract_id")
    reason_code = query_enum("reason_code", calc.TRANSITION_REASONS)

    records = list(db.transitions.values())
    if role == "AgencyOwner":
        records = [r for r in records
                   if r["from_agency_id"] == user_id or r["to_agency_id"] == user_id]
    if application_id is not None:
        records = [r for r in records if r["application_id"] == application_id]
    if from_agency_id is not None:
        records = [r for r in records if r["from_agency_id"] == from_agency_id]
    if to_agency_id is not None:
        records = [r for r in records if r["to_agency_id"] == to_agency_id]
    if trigger_contract_id is not None:
        records = [r for r in records if r["trigger_contract_id"] == trigger_contract_id]
    if reason_code is not None:
        records = [r for r in records if r["reason_code"] == reason_code]
    return listing(records, serializers.transition)
