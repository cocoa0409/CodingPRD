"""Post-transfer participant complaints: filing, triage, re-triage and resolution."""

from flask import Blueprint, request

from db import db, make_entity, now, ordered, public, touch
from errors import api_error
from middleware import (
    authenticate,
    body,
    filter_arg,
    get_enum,
    get_int,
    get_string,
    lookup,
    pagination,
    require_range,
    slice_page,
)
from response import list_response, object_response
from services import calculations as calc
from services import domain as dom

bp = Blueprint("complaints", __name__)

COMPLAINT_READ_ROLES = [
    "PlanSponsor",
    "PlanFiduciary",
    "PlanAdministrator",
    "Regulator",
    "Participant",
]

CATEGORIES = ("BENEFIT_AMOUNT", "MISSING_PAYMENT", "ADDRESS_OR_IDENTITY", "ANNUITY_FORM")
DETERMINATIONS = ("SPONSOR_RESPONSIBLE", "INSURER_RESPONSIBLE", "NO_ERROR")
SETTLED_PARTICIPANT_STATUSES = (
    "TRANSFERRED_TO_INSURER",
    "SETTLED_LUMP_SUM",
    "RESIDUAL_ANNUITY_PURCHASED",
)


def _next_reference(plan_id):
    count = len(dom.plan_complaints(plan_id))
    return "CMP-%04d" % (count + 1)


@bp.post("/prt/participants/<participant_id>/complaints")
def file_complaint(participant_id):
    user_id, _role = authenticate(["Participant"])
    if user_id != participant_id:
        raise api_error("ERR_IDENTITY_MISMATCH")
    participant = lookup("participants", participant_id)
    payload = body()
    category = get_enum(payload, "complaint_category", CATEGORIES)
    narrative = get_string(payload, "complaint_narrative")
    if len(narrative) < 1 or len(narrative) > 1000:
        raise api_error("ERR_INVALID_REQUEST", "complaint_narrative has an invalid length.")
    supplied_tranche = get_string(payload, "tranche_id", required=False)

    if supplied_tranche is not None and supplied_tranche != participant.get("tranche_id"):
        raise api_error("ERR_QUOTE_TRANCHE_MISMATCH")
    if participant["participant_status"] not in SETTLED_PARTICIPANT_STATUSES:
        raise api_error("ERR_PARTICIPANT_NOT_TRANSFERRED")

    complaint = make_entity()
    complaint["participant_id"] = participant["id"]
    complaint["tranche_id"] = (
        supplied_tranche if supplied_tranche is not None else participant.get("tranche_id")
    )
    complaint["complaint_reference"] = _next_reference(participant["plan_id"])
    complaint["complaint_category"] = category
    complaint["complaint_detail"] = narrative
    complaint["complaint_status"] = "OPEN"
    complaint["responsibility_determination"] = None
    complaint["determination_rationale"] = None
    complaint["remediation_amount_cents"] = 0
    complaint["reversed_amount_cents"] = 0
    complaint["triage_count"] = 0
    complaint["resolved_at"] = None
    db.complaints[complaint["id"]] = complaint
    return object_response(public(complaint), 201)


@bp.get("/prt/complaints")
def list_complaints():
    authenticate(COMPLAINT_READ_ROLES)
    participant_id = filter_arg("participants", "participant_id")
    tranche_id = filter_arg("tranches", "tranche_id")
    complaint_status = request.args.get("complaint_status")
    determination = request.args.get("responsibility_determination")
    limit, offset = pagination()
    records = ordered(list(db.complaints.values()))
    if participant_id is not None:
        records = [c for c in records if c["participant_id"] == participant_id]
    if tranche_id is not None:
        records = [c for c in records if c["tranche_id"] == tranche_id]
    if complaint_status is not None:
        records = [c for c in records if c["complaint_status"] == complaint_status]
    if determination is not None:
        records = [c for c in records if c["responsibility_determination"] == determination]
    page, total = slice_page(records, limit, offset)
    return list_response([public(c) for c in page], limit, offset, total)


@bp.get("/prt/complaints/<complaint_id>")
def get_complaint(complaint_id):
    authenticate(COMPLAINT_READ_ROLES)
    complaint = lookup("complaints", complaint_id)
    return object_response(public(complaint))


@bp.post("/prt/complaints/<complaint_id>/triage")
def triage_complaint(complaint_id):
    authenticate(["PlanAdministrator"])
    complaint = lookup("complaints", complaint_id)
    payload = body()
    determination = get_enum(payload, "responsibility_determination", DETERMINATIONS)
    rationale = get_string(payload, "determination_rationale")
    participant = db.participants.get(complaint["participant_id"])

    # Consistency with the documented audit variance (ERR_INVALID_REQUEST family).
    if complaint["complaint_category"] == "BENEFIT_AMOUNT" and participant is not None:
        audit = dom.latest_live_audit(participant["id"])
        if audit is not None and abs(audit["variance_cents"] or 0) > (
            calc.AUDIT_VARIANCE_TOLERANCE_CENTS
        ):
            if determination != "SPONSOR_RESPONSIBLE":
                raise api_error(
                    "ERR_INVALID_REQUEST",
                    "A documented benefit variance requires SPONSOR_RESPONSIBLE.",
                )

    status = complaint["complaint_status"]
    if status not in ("OPEN", "RESOLVED"):
        raise api_error("ERR_COMPLAINT_NOT_TRIAGED")
    if status == "RESOLVED" and determination == complaint["responsibility_determination"]:
        raise api_error("ERR_COMPLAINT_STATE_INVALID")

    if status == "OPEN":
        complaint["complaint_status"] = "TRIAGED"
        complaint["responsibility_determination"] = determination
        complaint["determination_rationale"] = rationale
        complaint["triage_count"] = complaint["triage_count"] + 1
        touch(complaint)
        if determination == "SPONSOR_RESPONSIBLE" and participant is not None:
            audit = dom.latest_live_audit(participant["id"])
            if audit is not None:
                audit["audit_status"] = "REOPENED"
                audit["reopened_by_complaint_id"] = complaint["id"]
                touch(audit)
            participant["benefit_audit_status"] = "REOPENED"
            dom.refresh_participant_confidence(participant)
            tranche = dom.participant_open_tranche(participant)
            if tranche is not None:
                dom.recompute_tranche(
                    tranche, readiness="BLOCKED", count=False, liabilities=False
                )
        return object_response(public(complaint))

    # Re-triage from RESOLVED.
    prior_determination = complaint["responsibility_determination"]
    remediation = complaint["remediation_amount_cents"] or 0
    complaint["complaint_status"] = "TRIAGED"
    complaint["responsibility_determination"] = determination
    complaint["determination_rationale"] = rationale
    complaint["triage_count"] = complaint["triage_count"] + 1
    complaint["resolved_at"] = None

    if (
        prior_determination == "SPONSOR_RESPONSIBLE"
        and remediation > 0
        and determination == "NO_ERROR"
        and participant is not None
    ):
        plan = db.plans.get(participant["plan_id"])
        if plan is not None:
            complaint["reversed_amount_cents"] = remediation
            dom.append_settlement_entry(
                plan,
                "REMEDIATION_REVERSAL",
                -remediation,
                0,
                0,
                0,
                "ParticipantComplaint RESOLVED -> TRIAGED (%s)"
                % complaint["complaint_reference"],
            )
            plan["plan_assets_cents"] = plan["plan_assets_cents"] + remediation
            dom.recompute_plan_accounting_funded_status(plan)
    touch(complaint)
    return object_response(public(complaint))


@bp.post("/prt/complaints/<complaint_id>/resolution")
def resolve_complaint(complaint_id):
    authenticate(["PlanAdministrator"])
    complaint = lookup("complaints", complaint_id)
    payload = body()
    remediation = get_int(payload, "remediation_amount_cents")
    require_range(remediation, "remediation_amount_cents", 0, None)
    determination = complaint["responsibility_determination"]
    if determination == "SPONSOR_RESPONSIBLE" and remediation < 1:
        raise api_error(
            "ERR_INVALID_AMOUNT", "A sponsor-responsible remediation must be at least 1."
        )
    if determination in ("INSURER_RESPONSIBLE", "NO_ERROR") and remediation != 0:
        raise api_error("ERR_INVALID_AMOUNT", "This determination requires a remediation of 0.")

    if complaint["complaint_status"] != "TRIAGED":
        raise api_error("ERR_COMPLAINT_NOT_TRIAGED")
    participant = db.participants.get(complaint["participant_id"])
    if participant is not None and participant["benefit_audit_status"] == "REOPENED":
        raise api_error("ERR_AUDIT_STATE_INVALID")
    plan = db.plans.get(participant["plan_id"]) if participant is not None else None
    if determination == "SPONSOR_RESPONSIBLE":
        if plan is None or plan["plan_assets_cents"] < remediation:
            raise api_error("ERR_PLAN_ASSETS_INSUFFICIENT")

    complaint["complaint_status"] = "RESOLVED"
    complaint["remediation_amount_cents"] = remediation
    complaint["resolved_at"] = now()
    touch(complaint)

    if determination == "SPONSOR_RESPONSIBLE" and plan is not None:
        dom.append_settlement_entry(
            plan,
            "REMEDIATION",
            remediation,
            0,
            0,
            0,
            "ParticipantComplaint TRIAGED -> RESOLVED (%s)" % complaint["complaint_reference"],
        )
        plan["plan_assets_cents"] = plan["plan_assets_cents"] - remediation
        dom.recompute_plan_accounting_funded_status(plan)
    return object_response(public(complaint))
