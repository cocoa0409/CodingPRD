"""Orders: creation, reads, traveller enrolment, quoting, money collection,
tier changes, travel-date changes and the feasibility surface."""
from decimal import Decimal

from flask import Blueprint

import clock
import serializers
import store
import validation
from constants import (
    API_PREFIX,
    PAYMENT_STREAMS,
    PHOTO_VALIDITY_DAYS,
    SERVICE_LEVELS,
    TIER_ORDER,
)
from calendar_util import whole_years_between
from errors import fail
from routes.common import (
    AUDIT_ROLES,
    READ_ROLES,
    created,
    endpoint,
    listing,
    ok,
)
from services import custody, lookup, money, pricing, projection, readiness
from validation import Body

import datetime as _dt

bp = Blueprint("orders", __name__)
P = API_PREFIX


def resolve_body_fk(data, field, collection):
    raw = data.get(field)
    if isinstance(raw, str):
        return validation.need(collection, raw)
    return None


def new_order_row(catalog_item_id, consulate_id, service_level, travel_date, return_date,
                  delivery_region_code, parent_order_id=None, workflow_status="DRAFT",
                  furthest_stage_reached="DRAFT"):
    return {
        "catalog_item_id": catalog_item_id,
        "consulate_id": consulate_id,
        "parent_order_id": parent_order_id,
        "service_level": service_level,
        "travel_date": travel_date,
        "return_date": return_date,
        "delivery_region_code": delivery_region_code,
        "workflow_status": workflow_status,
        "payment_status": "UNPAID",
        "custody_holder": "APPLICANT",
        "feasibility_status": "UNKNOWN",
        "furthest_stage_reached": furthest_stage_reached,
        "applicant_count": 0,
        "government_fee_quoted_cents": 0,
        "service_fee_quoted_cents": 0,
        "total_quoted_cents": 0,
        "discount_pct_applied": Decimal("0"),
        "handling_fee_waived": False,
        "collected_government_cents": 0,
        "collected_service_cents": 0,
        "government_tendered_cents": 0,
        "service_earned_cents": 0,
        "refunded_cents": 0,
        "refund_scheduled_cents": 0,
        "outstanding_cents": 0,
        "quoted_by_user_id": None,
        "submitted_by_user_id": None,
        "acknowledged_by_user_id": None,
        "quoted_at": None,
        "submitted_at": None,
        "tendered_at": None,
        "decided_at": None,
        "effective_submission_date": None,
        "projected_completion_date": None,
        "rfe_round_count": 0,
    }


@bp.route(P + "/orders", methods=["POST"])
@endpoint("orders.create", ["CaseManager"])
def create_order(ctx):
    catalog = resolve_body_fk(ctx.body, "catalog_item_id", "catalog_items")
    consulate = resolve_body_fk(ctx.body, "consulate_id", "consulates")

    body = Body(ctx.body)
    body.string("catalog_item_id")
    travel_date = body.date("travel_date")
    return_date = body.date("return_date")
    delivery_region = body.string("delivery_region_code")
    service_level = body.enum("service_level", SERVICE_LEVELS, required=False, default="STANDARD")
    body.string("consulate_id", required=False)
    body.invalid(
        catalog is not None and catalog["requires_appointment"] and consulate is None,
        "consulate_id is required when the catalog item requires an appointment.",
    )
    body.invalid(
        travel_date is not None and return_date is not None and return_date < travel_date,
        "return_date must be on or after travel_date.",
    )
    body.check()

    row = store.insert("orders", new_order_row(
        catalog["id"], consulate["id"] if consulate else None, service_level,
        travel_date, return_date, delivery_region,
    ))
    custody.append_first(row, "APPLICANT", "ORDER_CREATED")
    return created(serializers.order(row))


@bp.route(P + "/orders", methods=["GET"])
@endpoint("orders.list", READ_ROLES)
def list_orders(ctx):
    rows = store.all_rows("orders")
    rows = validation.apply_filter(rows, "workflow_status")
    rows = validation.apply_filter(rows, "catalog_item_id")
    rows = validation.apply_filter(rows, "consulate_id")
    rows = validation.apply_filter(rows, "parent_order_id")
    return listing(store.sort_default(rows), serializers.order)


@bp.route(P + "/orders/<order_id>", methods=["GET"])
@endpoint("orders.read", READ_ROLES)
def read_order(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    return ok(serializers.order(order))


# --------------------------------------------------------------- applicants ---
@bp.route(P + "/orders/<order_id>/applicants", methods=["POST"])
@endpoint("orders.applicants.create", ["CaseManager"])
def create_applicant(ctx, order_id):
    order = validation.need_order(order_id)
    body = Body(ctx.body)
    full_name = body.string("full_name")
    date_of_birth = body.date("date_of_birth")
    nationality = body.string("nationality_code")
    residence = body.string("residence_region_code")
    body.invalid(
        isinstance(nationality, str)
        and not (len(nationality) == 2 and nationality.isalpha() and nationality.isupper()),
        "nationality_code must be exactly 2 uppercase letters.",
    )
    body.check()
    validation.guard_order(ctx, order)

    catalog = lookup.catalog_of(order)
    if nationality != catalog["nationality_code"]:
        fail("ERR_NATIONALITY_MISMATCH")

    age_years = whole_years_between(date_of_birth, order["travel_date"])
    applicant = store.insert("applicants", {
        "order_id": order["id"],
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "nationality_code": nationality,
        "residence_region_code": residence,
        "readiness_status": "PENDING",
        "age_years": age_years,
        "required_doc_count": 0,
        "accepted_doc_count": 0,
    })

    required_count = 0
    for line in lookup.requirements_of(catalog["id"]):
        limit = line["applies_max_age_years"]
        if limit is not None and not (age_years < limit):
            continue
        store.insert("documents", {
            "applicant_id": applicant["id"],
            "doc_type": line["doc_type"],
            "is_required": line["is_required"],
            "validity_rule": line["validity_rule"],
            "validity_param": line["validity_param"],
            "review_status": "MISSING",
            "issue_date": None,
            "expiry_date": None,
            "resubmission_count": 0,
            "rejection_reason": None,
            "reviewed_by_user_id": None,
        })
        if line["is_required"]:
            required_count += 1
    applicant["required_doc_count"] = required_count

    pricing.recompute_applicant_count(order)
    store.touch(order)
    return created(serializers.applicant(applicant))


@bp.route(P + "/orders/<order_id>/applicants", methods=["GET"])
@endpoint("orders.applicants.list", READ_ROLES)
def list_applicants(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    rows = lookup.applicants_of(order)
    rows = validation.apply_filter(rows, "readiness_status")
    return listing(rows, serializers.applicant)


@bp.route(P + "/applicants/<applicant_id>", methods=["GET"])
@endpoint("applicants.read", READ_ROLES)
def read_applicant(ctx, applicant_id):
    applicant = validation.need("applicants", applicant_id)
    validation.check_membership(ctx, lookup.order_of_applicant(applicant))
    return ok(serializers.applicant(applicant))


@bp.route(P + "/applicants/<applicant_id>/required-documents", methods=["GET"])
@endpoint("applicants.required_documents", AUDIT_ROLES)
def read_required_documents(ctx, applicant_id):
    applicant = validation.need("applicants", applicant_id)
    validation.check_membership(ctx, lookup.order_of_applicant(applicant))
    docs = lookup.documents_of(applicant)
    required = [d["doc_type"] for d in docs if d["is_required"]]
    optional = [d["doc_type"] for d in docs if not d["is_required"]]
    return ok({
        "required_doc_types": required,
        "optional_doc_types": optional,
        "required_doc_count": applicant["required_doc_count"],
        "accepted_doc_count": applicant["accepted_doc_count"],
        "satisfied": applicant["accepted_doc_count"] == applicant["required_doc_count"],
    })


# -------------------------------------------------------------------- quote ---
@bp.route(P + "/orders/<order_id>/quote", methods=["POST"])
@endpoint("orders.quote", ["CaseManager"])
def quote_order(ctx, order_id):
    order = validation.need_order(order_id)
    body = Body(ctx.body)
    promo = body.number("promo_discount_pct", required=False, default=Decimal("0.00"), minimum=0)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(order["workflow_status"], ("DRAFT", "QUOTED"))
    if not lookup.counted_applicants(order):
        fail("ERR_INVALID_STATE", "The order carries no traveller in PENDING or COMPLETE.")

    pricing.run_full_quote(order, promo)
    order["quoted_by_user_id"] = ctx.user_id
    order["quoted_at"] = clock.now()
    order["workflow_status"] = "QUOTED"
    readiness.raise_stage(order, "QUOTED")
    projection.run_projection_and_feasibility(order)
    store.touch(order)
    return ok(serializers.order(order))


@bp.route(P + "/orders/<order_id>/accept-quote", methods=["POST"])
@endpoint("orders.accept_quote", ["CaseManager", "Traveler"])
def accept_quote(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    Body(ctx.body).check()
    validation.guard_order(ctx, order)
    if (order["workflow_status"] != "QUOTED"
            or order["payment_status"] != "COLLECTED"
            or order["total_quoted_cents"] <= 0):
        fail("ERR_INVALID_STATE", "The order is not a fully funded standing quote.")

    order["workflow_status"] = "INTAKE"
    readiness.raise_stage(order, "INTAKE")
    for applicant in lookup.applicants_of(order):
        readiness.recompute_readiness(applicant)
    store.touch(order)
    readiness.reevaluate_gate(order, bump=False)
    return ok(serializers.order(order))


# ----------------------------------------------------------------- payments ---
@bp.route(P + "/orders/<order_id>/payments", methods=["POST"])
@endpoint("orders.payments", ["CaseManager", "Traveler"])
def record_payment(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    body = Body(ctx.body)
    amount = body.integer("amount_cents", minimum=1)
    override = body.enum("stream_override", PAYMENT_STREAMS, required=False)
    body.check()
    validation.guard_order(ctx, order)
    if (order["payment_status"] not in ("UNPAID", "PARTIALLY_COLLECTED")
            or order["total_quoted_cents"] <= 0):
        fail("ERR_INVALID_STATE", "The order is not open for collection.")

    gov_part, svc_part = money.allocate_payment(order, amount, override)
    if order["collected_government_cents"] + gov_part > order["government_fee_quoted_cents"]:
        fail("ERR_STREAM_ALLOCATION_INVALID")

    gov_row = money.record_collection(order, "GOVERNMENT", gov_part) if gov_part > 0 else None
    svc_row = money.record_collection(order, "SERVICE", svc_part) if svc_part > 0 else None
    money.recompute_collected(order)
    money.derive_payment_status(order)
    store.touch(order)
    chosen = svc_row if svc_row is not None else gov_row
    return created(serializers.ledger_entry(chosen))


@bp.route(P + "/orders/<order_id>/ledger-entries", methods=["GET"])
@endpoint("orders.ledger_entries", AUDIT_ROLES)
def list_ledger_entries(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    rows = lookup.ledger_of(order)
    rows = validation.apply_filter(rows, "stream")
    rows = validation.apply_filter(rows, "kind")
    return listing(rows, serializers.ledger_entry)


# ------------------------------------------------------------ service level ---
@bp.route(P + "/orders/<order_id>/service-level", methods=["POST"])
@endpoint("orders.service_level", ["CaseManager"])
def change_service_level(ctx, order_id):
    order = validation.need_order(order_id)
    body = Body(ctx.body)
    requested = body.enum("service_level", SERVICE_LEVELS)
    expected = body.integer("expected_order_version")
    body.check()
    validation.guard_order(ctx, order)
    validation.check_occ(expected, order)
    if TIER_ORDER[requested] <= TIER_ORDER[order["service_level"]]:
        fail("ERR_TIER_NOT_AN_UPGRADE")
    if order["workflow_status"] not in ("DRAFT", "QUOTED", "INTAKE", "READY_FOR_SUBMISSION"):
        fail("ERR_UPGRADE_STAGE_CLOSED")

    stage = order["workflow_status"]
    order["service_level"] = requested
    if stage in ("DRAFT", "QUOTED"):
        # pre_intake_requote -- the whole quote is recomputed, promo treated as 0.00
        pricing.run_full_quote(order, Decimal("0.00"))
    else:
        pricing.apply_in_flight_delta(order)
    money.derive_payment_status(order)
    projection.run_projection_and_feasibility(order)
    store.touch(order)
    return ok(serializers.order(order))


# ------------------------------------------------------------- travel dates ---
@bp.route(P + "/orders/<order_id>/travel-dates", methods=["PATCH"])
@endpoint("orders.travel_dates", ["CaseManager", "Traveler"])
def change_travel_dates(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    body = Body(ctx.body)
    travel_date = body.date("travel_date")
    return_date = body.date("return_date")
    body.invalid(
        travel_date is not None and return_date is not None and return_date < travel_date,
        "return_date must be on or after travel_date.",
    )
    body.check()
    validation.guard_order(ctx, order)

    order["travel_date"] = travel_date
    order["return_date"] = return_date

    for applicant in lookup.applicants_of(order):
        for doc in lookup.documents_of(applicant):
            if doc["review_status"] == "ACCEPTED" and doc["validity_rule"] != "NONE":
                doc["review_status"] = "RECEIVED"
                store.touch(doc)
        for photo in lookup.photos_of(applicant):
            if photo["compliance_status"] != "PASSED":
                continue
            horizon = photo["taken_on"] + _dt.timedelta(days=PHOTO_VALIDITY_DAYS)
            if horizon < travel_date:
                photo["compliance_status"] = "EXPIRED"
                store.touch(photo)
        readiness.recompute_readiness(applicant)

    store.touch(order)
    readiness.reevaluate_gate(order, bump=False)
    projection.run_projection_and_feasibility(order)
    return ok(serializers.order(order))


# -------------------------------------------------------------- feasibility ---
@bp.route(P + "/orders/<order_id>/feasibility", methods=["GET"])
@endpoint("orders.feasibility", AUDIT_ROLES)
def read_feasibility(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    # Adjudication of friction 8: a PURE read -- it persists nothing, does not
    # move the stored feasibility_status and does not revoke an acknowledgment.
    projected, effective, turnaround, variant = projection.project(order)
    return ok({
        "effective_submission_date": clock.render_date(effective),
        "agency_turnaround_days": turnaround,
        "projected_completion_date": clock.render_date(projected),
        "deadline_date": clock.render_date(projection.deadline_date(order)),
        "feasibility_status": order["feasibility_status"],
        "variant_used": variant,
    })


@bp.route(P + "/orders/<order_id>/feasibility-acknowledgment", methods=["POST"])
@endpoint("orders.feasibility_acknowledgment", ["ComplianceOfficer"])
def acknowledge_feasibility(ctx, order_id):
    order = validation.need_order(order_id)
    Body(ctx.body).check()
    validation.guard_order(ctx, order)
    if (order["feasibility_status"] != "INFEASIBLE"
            or order["workflow_status"] not in ("INTAKE", "READY_FOR_SUBMISSION")):
        fail("ERR_INVALID_STATE", "The order is not an unacknowledged infeasible order.")
    order["feasibility_status"] = "ACKNOWLEDGED_INFEASIBLE"
    order["acknowledged_by_user_id"] = ctx.user_id
    store.touch(order)
    return ok(serializers.order(order))
