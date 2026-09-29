"""External payer audit findings: open, respond, resolve."""

from flask import Blueprint, request

import derive
import envelope
import lookup
import serializers
import store
import validation as v
from auth import actor, require
from errors import ApiError

bp = Blueprint("audit", __name__, url_prefix="/research-billing")

READ_ROLES = ("AuditLiaison", "ComplianceReviewer", "ResearchBillingManager")
FINDING_TYPES = ("IMPROPER_PAYER_BILL", "MISSING_REGISTRY_NUMBER",
                 "UNSUPPORTED_ROUTINE_CLASSIFICATION")
DISPOSITIONS = ("NO_ACTION", "REFUND_AND_REROUTE")


@bp.post("/audit-findings")
@require("AuditLiaison")
def create_finding():
    body = v.body()
    study_id = v.req_id(body, "study_id")
    finding_type = v.req_enum(body, "finding_type", FINDING_TYPES)
    claimed_amount_cents = v.req_int(body, "claimed_amount_cents", minimum=0)
    charge_id = v.opt_id(body, "charge_id")

    study = lookup.study(study_id)
    if charge_id is not None:
        lookup.charge(charge_id)

    rec = store.base_record()
    rec.update({
        "study_id": study["id"],
        "charge_id": charge_id,
        "finding_type": finding_type,
        "claimed_amount_cents": claimed_amount_cents,
        "status": "OPEN",
        "response_narrative": None,
        "opened_by_user_id": actor(),
        "responded_by_user_id": None,
        "refund_amount_cents": 0,
    })
    store.findings[rec["id"]] = rec
    store.touch(study)
    return envelope.created(serializers.finding(rec))


@bp.get("/audit-findings")
@require(*READ_ROLES)
def list_findings():
    limit, offset = envelope.read_pagination(request.args)
    rows = store.by_created(store.findings.values())
    for key in ("study_id", "charge_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.finding(r) for r in page], limit, offset, total)


@bp.get("/audit-findings/<finding_id>")
@require(*READ_ROLES)
def get_finding(finding_id):
    return envelope.ok(serializers.finding(lookup.finding(finding_id)))


@bp.post("/audit-findings/<finding_id>/respond")
@require("AuditLiaison")
def respond_finding(finding_id):
    body = v.body()
    narrative = v.req_str(body, "response_narrative")

    rec = lookup.finding(finding_id)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_FINDING_NOT_OPEN")
    if actor() == rec["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    rec["status"] = "RESPONDED"
    rec["response_narrative"] = narrative
    rec["responded_by_user_id"] = actor()
    store.touch(rec)
    return envelope.ok(serializers.finding(rec))


@bp.post("/audit-findings/<finding_id>/resolve")
@require("AuditLiaison")
def resolve_finding(finding_id):
    body = v.body()
    disposition = v.req_enum(body, "disposition", DISPOSITIONS)

    rec = lookup.finding(finding_id)
    if rec["status"] != "RESPONDED":
        raise ApiError("ERR_FINDING_NOT_RESPONDED")

    study = store.studies.get(rec["study_id"])

    if disposition == "NO_ACTION":
        rec["status"] = "CLOSED_NO_ACTION"
        store.touch(rec)
        if study is not None:
            store.touch(study)
        return envelope.ok(serializers.finding(rec))

    charge = store.charges.get(rec["charge_id"]) if rec["charge_id"] else None
    if charge is None or charge["billing_state"] != "BILLED_PAYER":
        raise ApiError("ERR_CHARGE_NOT_BILLED_TO_PAYER")

    rec["status"] = "CLOSED_REFUNDED"
    rec["refund_amount_cents"] = charge["amount_cents"]
    store.touch(rec)

    charge["billing_state"] = "REFUNDED"
    charge["refunded_amount_cents"] = charge["amount_cents"]
    store.touch(charge)

    derive.new_charge(
        study_id=charge["study_id"],
        charge_code=charge["charge_code"],
        service_date=charge["service_date"],
        amount_cents=charge["amount_cents"],
        source="REFUND_REPLACEMENT",
        replaces_charge_id=charge["id"],
        coverage_item_id=charge["coverage_item_id"],
        routing_state="ROUTED_SPONSOR",
    )

    if study is not None:
        store.touch(study)
    return envelope.ok(serializers.finding(rec))
