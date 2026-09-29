"""The commission ledger: reads, listing and disposition (PRD 3.7)."""

from flask import Blueprint

import errors
import serializers
from db import db, touch
from errors import fail
from middleware import check_scope
from response import obj
from routes.common import auth, listing, need
from services import calc, domain
from validation import body, opt_str, query_enum, query_str, req_enum

bp = Blueprint("entries", __name__)

ACTIONS = ("APPROVE", "PAY", "VOID")
ACTION_SOURCE = {"APPROVE": ("ACCRUED",), "PAY": ("APPROVED",), "VOID": ("ACCRUED", "APPROVED")}
READ_ROLES = ("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer", "AgencyOwner")


def _entry_agency_id(entry):
    contract = db.contracts.get(entry["contract_id"])
    return contract["agency_id"] if contract is not None else None


@bp.route("/recruitment/commission-entries/<entry_id>", methods=["GET"])
def read_entry(entry_id):
    user_id, role = auth(*READ_ROLES)
    entry = db.entries.get(entry_id)
    if entry is not None:
        check_scope(role, user_id, _entry_agency_id(entry))
    if entry is None:
        fail(errors.ERR_ENTRY_NOT_FOUND, "Commission entry not found")
    return obj(serializers.entry(entry))


@bp.route("/recruitment/commission-entries", methods=["GET"])
def list_entries():
    user_id, role = auth(*READ_ROLES)
    contract_id = query_str("contract_id")
    application_id = query_str("application_id")
    schedule_id = query_str("schedule_id")
    parent_entry_id = query_str("parent_entry_id")
    kind = query_enum("kind", calc.ENTRY_KINDS)
    milestone = query_enum("milestone", calc.MILESTONES)
    state = query_enum("state", calc.ENTRY_STATES)

    records = list(db.entries.values())
    if role == "AgencyOwner":
        records = [r for r in records if _entry_agency_id(r) == user_id]
    if contract_id is not None:
        records = [r for r in records if r["contract_id"] == contract_id]
    if application_id is not None:
        records = [r for r in records if r["application_id"] == application_id]
    if schedule_id is not None:
        records = [r for r in records if r["schedule_id"] == schedule_id]
    if parent_entry_id is not None:
        records = [r for r in records if r["parent_entry_id"] == parent_entry_id]
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    if milestone is not None:
        records = [r for r in records if r["milestone"] == milestone]
    if state is not None:
        records = [r for r in records if r["state"] == state]
    return listing(records, serializers.entry)


@bp.route("/recruitment/commission-entries/<entry_id>/disposition", methods=["POST"])
def entry_disposition(entry_id):
    user_id, _role = auth("FinanceOfficer")
    data = body()
    action = req_enum(data, "action", ACTIONS)
    note = opt_str(data, "note")
    entry = need(db.entries, entry_id, errors.ERR_ENTRY_NOT_FOUND)

    if action == "PAY" and entry["approved_by_user_id"] is not None \
            and user_id == entry["approved_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The paying officer must differ from the approving officer")

    contract = db.contracts.get(entry["contract_id"])
    app = db.applications.get(entry["application_id"])
    agency = db.agencies.get(contract["agency_id"]) if contract is not None else None

    if action == "APPROVE":
        if contract is None or contract["status"] != "ACTIVE":
            fail(errors.ERR_INVALID_CONTRACT_STATE,
                 "The entry's contract must be ACTIVE to approve")
        if app is not None and app["status"] in ("WITHDRAWN", "DENIED"):
            fail(errors.ERR_INVALID_APPLICATION_STATE,
                 "The producing application is %s" % app["status"])

    if entry["state"] not in ACTION_SOURCE[action]:
        fail(errors.ERR_INVALID_ENTRY_STATE,
             "Action %s is not defined from state %s" % (action, entry["state"]))

    if agency is not None:
        posture = agency["compliance_posture"]
        if action == "APPROVE" and posture not in ("GOOD_STANDING", "WATCH"):
            fail(errors.ERR_AGENCY_POSTURE_BLOCKED,
                 "Compliance posture %s blocks approval" % posture)
        if action == "PAY" and posture in ("SUSPENDED", "DEBARRED"):
            fail(errors.ERR_AGENCY_POSTURE_BLOCKED,
                 "Compliance posture %s blocks payment" % posture)

    if action == "APPROVE":
        if entry["incentive_comp_prohibited"]:
            fail(errors.ERR_INCENTIVE_COMPENSATION_PROHIBITED,
                 "Per-enrollment incentive compensation is prohibited for this entry")
        committed = sum(e["amount_cents"] for e in calc.contract_entries(contract["id"])
                        if e["kind"] == "ACCRUAL" and e["state"] in ("APPROVED", "PAID"))
        if committed + entry["amount_cents"] > contract["annual_commission_cap_cents"]:
            fail(errors.ERR_COMMISSION_CAP_EXCEEDED,
                 "The contract's annual commission cap would be exceeded")

    if action == "PAY" and agency is not None and agency["clawback_liability_cents"] != 0:
        fail(errors.ERR_CLAWBACK_LIABILITY_UNSETTLED,
             "The agency carries an unsettled clawback liability")

    if action == "APPROVE":
        entry["state"] = "APPROVED"
        entry["approved_by_user_id"] = user_id
        touch(entry)
    elif action == "PAY":
        entry["state"] = "PAID"
        entry["paid_by_user_id"] = user_id
        touch(entry)
    else:
        entry["state"] = "VOID"
        entry["void_reason"] = note if note else "MANUAL_VOID"
        touch(entry)
        if app is not None:
            domain.recompute_application_net(app)
        if agency is not None:
            domain.recompute_agency_ledger(agency)
    return obj(serializers.entry(entry))
