"""Interface-posted charges, charge reads, and charge review."""

from flask import Blueprint, request

import derive
import envelope
import lookup
import serializers
import store
import validation as v
from auth import actor, require
from errors import ApiError

bp = Blueprint("charges", __name__, url_prefix="/research-billing")

READ_ROLES = ("ComplianceReviewer", "ResearchBillingManager", "StudyCoordinator",
              "AuditLiaison")
DECISIONS = ("CLEAR_TO_PAYER", "HOLD_FOR_SPONSOR", "NO_CHARGE_PROMOTIONAL")


@bp.post("/charges")
@require("StudyCoordinator")
def create_charge():
    body = v.body()
    study_id = v.req_id(body, "study_id")
    charge_code = v.req_str(body, "charge_code")
    service_date = v.req_date(body, "service_date")
    amount_cents = v.req_int(body, "amount_cents", minimum=0)
    subject_visit_id = v.opt_id(body, "subject_visit_id")

    study = lookup.study(study_id)
    if subject_visit_id is not None:
        lookup.subject_visit(subject_visit_id)

    rec = derive.new_charge(
        study_id=study["id"],
        charge_code=charge_code,
        service_date=service_date,
        amount_cents=amount_cents,
        source="INTERFACE_POSTED",
        subject_visit_id=subject_visit_id,
        posted_by_user_id=actor(),
    )
    return envelope.created(serializers.charge(rec))


@bp.get("/charges")
@require(*READ_ROLES)
def list_charges():
    limit, offset = envelope.read_pagination(request.args)
    rows = store.by_created(store.charges.values())
    for key in ("study_id", "subject_visit_id", "coverage_item_id", "sponsor_invoice_id",
                "replaces_charge_id", "routing_state", "billing_state", "aging_bucket"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.charge(r) for r in page], limit, offset, total)


@bp.get("/charges/<charge_id>")
@require(*READ_ROLES)
def get_charge(charge_id):
    return envelope.ok(serializers.charge(lookup.charge(charge_id)))


@bp.post("/charges/<charge_id>/review")
@require("ComplianceReviewer")
def review_charge(charge_id):
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)
    override = v.opt_str(body, "override_justification", min_len=0)

    rec = lookup.charge(charge_id)
    if rec["routing_state"] != "UNROUTED":
        raise ApiError("ERR_CHARGE_ALREADY_ROUTED")

    study = lookup.study(rec["study_id"])
    posture = derive.billing_hold_posture(study)
    if posture == "ALL_BLOCKED":
        raise ApiError("ERR_STUDY_BILLING_BLOCKED")
    if decision == "CLEAR_TO_PAYER" and posture != "OPEN":
        raise ApiError("ERR_PAYER_BILLING_BLOCKED_NO_QCT")

    analysis = derive.effective_as_of(study["id"], rec["service_date"])
    if analysis is None:
        raise ApiError("ERR_NO_EFFECTIVE_ANALYSIS")

    item = derive.match_item(analysis, rec["charge_code"])
    if item is None:
        raise ApiError("ERR_CHARGE_CODE_NOT_IN_COVERAGE_ANALYSIS")

    has_override = isinstance(override, str) and override != ""
    if item["billable_to"] != derive.DECISION_TARGET[decision] and not has_override:
        raise ApiError("ERR_ROUTING_CONTRADICTS_COVERAGE")

    if decision == "CLEAR_TO_PAYER":
        rec["routing_state"] = "ROUTED_PAYER"
        rec["billing_state"] = "BILLED_PAYER"
    elif decision == "HOLD_FOR_SPONSOR":
        rec["routing_state"] = "ROUTED_SPONSOR"
    else:
        rec["routing_state"] = "ROUTED_NONE"
        rec["billing_state"] = "WRITTEN_OFF"

    rec["coverage_item_id"] = item["id"]
    rec["reviewed_by_user_id"] = actor()
    rec["reviewed_at"] = store.now()
    if has_override:
        rec["override_justification"] = override
    store.touch(rec)
    return envelope.ok(serializers.charge(rec))
