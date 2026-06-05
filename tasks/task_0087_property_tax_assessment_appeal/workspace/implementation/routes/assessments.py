"""Assessment endpoints: create, notice, finalize, issue-bill, nested lists."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services.assessment import recompute_value, recompute_exemptions
from services.calc import tax_bill_amount_cents
from services.common import (
    get_body, require_fields, lookup, parse_pagination, paginate, is_number,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("assessments", __name__)

REASSESSMENT_EVENTS = {"NONE", "SALE", "NEW_CONSTRUCTION"}


@bp.post("/assessments")
def create_assessment():
    require_roles(["Assessor"])
    body = get_body()
    # Presence of FK fields is needed to perform the existence checks that, per
    # §2.8, precede full request-schema validation; a missing FK cannot be
    # resolved and is therefore itself a schema error reported here first.
    require_fields(body, ["parcel_id", "tax_roll_id", "market_value"])
    parcel_id = body["parcel_id"]
    tax_roll_id = body["tax_roll_id"]
    if not isinstance(parcel_id, str) or not isinstance(tax_roll_id, str):
        raise err("ERR_INVALID_REQUEST", "parcel_id/tax_roll_id must be strings")
    reassessment_event = body.get("reassessment_event", "NONE")

    with db.LOCK:
        # Existence (priority 4), left-to-right.
        parcel = lookup(db.parcels, parcel_id)
        lookup(db.tax_rolls, tax_roll_id)

        # Business-referential (priority 12): a SOLD parcel's next assessment
        # must be a SALE rebase (PRD §3.3) — ahead of generic request-schema.
        if parcel["status"] == "SOLD" and reassessment_event != "SALE":
            raise err("ERR_SALE_REASSESSMENT_REQUIRED",
                      "First assessment after a sale must carry reassessment_event SALE")

        # Request-schema validation (priority 20, last): enum + numeric range.
        if reassessment_event not in REASSESSMENT_EVENTS:
            raise err("ERR_INVALID_REQUEST", "reassessment_event invalid")
        market_value = body["market_value"]
        if not is_number(market_value) or market_value < 0:
            raise err("ERR_INVALID_REQUEST", "market_value must be >= 0")

        record = {
            "parcel_id": parcel_id,
            "tax_roll_id": tax_roll_id,
            "market_value": market_value,
            "reassessment_event": reassessment_event,
            "capped_base_value": 0,
            "assessed_value": 0,
            "exemption_total": 0,
            "taxable_value": 0,
            "appealed_value": None,
            "final_taxable_value": None,
            "status": "DRAFT",
            "noticed_by_user_id": None,
        }
        db.init_common(record)
        recompute_value(record)

        # Side effect: a SALE assessment against a SOLD parcel returns it ACTIVE.
        if reassessment_event == "SALE" and parcel["status"] == "SOLD":
            parcel["status"] = "ACTIVE"
            db.touch(parcel)

        db.assessments[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/assessments")
def list_assessments():
    require_roles(["Assessor", "Reviewer", "HearingOfficer"])
    limit, offset = parse_pagination()
    tax_roll_id = request.args.get("tax_roll_id")
    parcel_id = request.args.get("parcel_id")
    items = list(db.assessments.values())
    if tax_roll_id is not None:
        items = [a for a in items if a["tax_roll_id"] == tax_roll_id]
    if parcel_id is not None:
        items = [a for a in items if a["parcel_id"] == parcel_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)


@bp.get("/assessments/<assessment_id>")
def get_assessment(assessment_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    return object_response(serialize(lookup(db.assessments, assessment_id)), 200)


@bp.post("/assessments/<assessment_id>/notice")
def notice_assessment(assessment_id):
    user_id, _role = require_roles(["Assessor"])
    with db.LOCK:
        a = lookup(db.assessments, assessment_id)
        if a["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Assessment is not DRAFT")
        roll = db.tax_rolls[a["tax_roll_id"]]
        if roll["status"] != "OPEN":
            raise err("ERR_ROLL_NOT_OPEN", "Parent tax roll is not OPEN")
        pending = [e for e in db.exemptions.values()
                   if e["assessment_id"] == assessment_id and e["status"] == "CLAIMED"]
        if pending:
            raise err("ERR_EXEMPTIONS_PENDING", "An exemption is still CLAIMED")

        recompute_value(a)
        taxable = recompute_exemptions(a)
        a["final_taxable_value"] = taxable
        a["status"] = "NOTICED"
        # Record the operator who noticed, for the segregation-of-duties check.
        a["noticed_by_user_id"] = user_id
        db.touch(a)
    return object_response(serialize(a), 200)


@bp.post("/assessments/<assessment_id>/finalize")
def finalize_assessment(assessment_id):
    require_roles(["Assessor"])
    with db.LOCK:
        a = lookup(db.assessments, assessment_id)
        # finalize is the NOTICED -> FINAL transition. An assessment sits in
        # UNDER_APPEAL precisely because an open appeal holds it there, so that
        # case must surface the specific ERR_OPEN_APPEAL_EXISTS rather than the
        # generic ERR_INVALID_STATE; DRAFT/FINAL remain generic invalid-state.
        if a["status"] not in ("NOTICED", "UNDER_APPEAL"):
            raise err("ERR_INVALID_STATE", "Assessment is not NOTICED")
        open_states = {"FILED", "UNDER_REVIEW", "EVIDENCE_REQUESTED"}
        has_open_appeal = any(
            ap["assessment_id"] == assessment_id and ap["status"] in open_states
            for ap in db.appeals.values()
        )
        if has_open_appeal or a["status"] == "UNDER_APPEAL":
            raise err("ERR_OPEN_APPEAL_EXISTS", "An open appeal blocks finalize")
        a["status"] = "FINAL"
        db.touch(a)
    return object_response(serialize(a), 200)


@bp.post("/assessments/<assessment_id>/issue-bill")
def issue_bill(assessment_id):
    require_roles(["Assessor"])
    with db.LOCK:
        a = lookup(db.assessments, assessment_id)
        if a["status"] != "FINAL":
            raise err("ERR_INVALID_STATE", "Assessment is not FINAL")
        roll = db.tax_rolls[a["tax_roll_id"]]
        btv = a["final_taxable_value"]
        cents = tax_bill_amount_cents(btv, roll["mill_rate"])
        bill = {
            "assessment_id": assessment_id,
            "billed_taxable_value": btv,
            "tax_amount_cents": cents,
            "is_deferred": False,
            "status": "ISSUED",
        }
        db.init_common(bill)
        db.tax_bills[bill["id"]] = bill
    return object_response(serialize(bill), 201)


@bp.get("/assessments/<assessment_id>/exemptions")
def list_assessment_exemptions(assessment_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    lookup(db.assessments, assessment_id)
    limit, offset = parse_pagination()
    items = [e for e in db.exemptions.values()
             if e["assessment_id"] == assessment_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)


@bp.get("/assessments/<assessment_id>/appeals")
def list_assessment_appeals(assessment_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    lookup(db.assessments, assessment_id)
    limit, offset = parse_pagination()
    items = [ap for ap in db.appeals.values()
             if ap["assessment_id"] == assessment_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)


@bp.get("/assessments/<assessment_id>/bills")
def list_assessment_bills(assessment_id):
    require_roles(["Assessor", "Reviewer", "Taxpayer"])
    lookup(db.assessments, assessment_id)
    limit, offset = parse_pagination()
    items = [b for b in db.tax_bills.values()
             if b["assessment_id"] == assessment_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)
