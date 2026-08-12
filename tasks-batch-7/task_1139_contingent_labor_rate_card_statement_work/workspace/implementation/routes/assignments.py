from flask import Blueprint, request

from db import stamp_new, store, today_str, touch
from envelope import ok, ok_list
from errors import (
    ERR_CARD_NOT_EFFECTIVE,
    ERR_ENGAGEMENT_TYPE_MISMATCH,
    ERR_INVALID_STATE,
    ERR_MARKUP_ABOVE_CAP,
    ERR_NOT_FOUND,
    ERR_OFFER_NOT_ACCEPTED,
    ERR_PAY_BELOW_FLOOR,
    ERR_RATE_ABOVE_CEILING,
    ERR_RATE_CARD_INACTIVE,
    ERR_SUPPLIER_SUSPENDED,
    ERR_TENURE_LIMIT_EXCEEDED,
    ERR_VALIDATION,
    ERR_WORKER_DOUBLE_BOOKED,
    ERR_WORKER_SUPPLIER_MISMATCH,
    raise_err,
)
from security import ALL_READ, require_roles
from services import (
    TENURE_LIMIT_DAYS,
    markup_allowed,
    parse_d,
    projected_tenure_on_create,
    projected_tenure_on_extend,
    worker_offboard_cascade,
)
from validators import apply_filters, get_body, paginate, req_date, req_int, req_str
import serializers

bp = Blueprint("assignments", __name__)


def _get_assignment(assignment_id):
    a = store.assignments.get(assignment_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Assignment {assignment_id} not found.")
    return a


@bp.post("/v1/assignments")
def create_assignment():
    require_roles("ProgramAdmin")
    body = get_body()
    # -- request shape (400) --
    worker_id = req_str(body, "worker_id")
    engagement_id = req_str(body, "engagement_id")
    offer_id = req_str(body, "offer_id")
    rate_card_id = req_str(body, "rate_card_id")
    bill_rate = req_int(body, "bill_rate_cents")
    pay_rate = req_int(body, "pay_rate_cents")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")

    # -- existence (404) --
    worker = store.workers.get(worker_id)
    if worker is None:
        raise_err(ERR_NOT_FOUND, f"Worker {worker_id} not found.")
    eng = store.engagements.get(engagement_id)
    if eng is None:
        raise_err(ERR_NOT_FOUND, f"Engagement {engagement_id} not found.")
    offer = store.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_NOT_FOUND, f"Distribution offer {offer_id} not found.")
    card = store.rate_cards.get(rate_card_id)
    if card is None:
        raise_err(ERR_NOT_FOUND, f"Rate card {rate_card_id} not found.")

    # -- business safety (422): suspension, then tenure projection --
    sup = store.suppliers.get(offer["supplier_id"])
    if sup is not None and sup["status"] == "SUSPENDED":
        raise_err(ERR_SUPPLIER_SUSPENDED, "The offer's supplier is suspended.")
    if projected_tenure_on_create(worker, start_date, end_date) >= TENURE_LIMIT_DAYS:
        raise_err(
            ERR_TENURE_LIMIT_EXCEEDED,
            "Projected tenure reaches or exceeds the 730-day limit.",
        )

    # -- business constraint (409): worker double-booking on closed intervals --
    new_start, new_end = parse_d(start_date), parse_d(end_date)
    for a in store.assignments.values():
        if a["worker_id"] == worker_id and a["status"] in ("PENDING", "ACTIVE"):
            if new_start <= parse_d(a["end_date"]) and parse_d(a["start_date"]) <= new_end:
                raise_err(
                    ERR_WORKER_DOUBLE_BOOKED,
                    "The worker already has a non-terminal assignment overlapping this interval.",
                )

    # -- temporal (422): the card's half-open window must contain start_date --
    if not (parse_d(card["effective_from"]) <= new_start < parse_d(card["effective_to"])):
        raise_err(
            ERR_CARD_NOT_EFFECTIVE,
            "The rate card's effective window does not contain the assignment start date.",
        )

    # -- referential (422) --
    if (
        card["status"] != "ACTIVE"
        or card["role_code"] != eng["role_code"]
        or card["skill_code"] != eng["skill_code"]
        or card["geo_code"] != eng["geo_code"]
    ):
        raise_err(
            ERR_RATE_CARD_INACTIVE,
            "The referenced rate card is not ACTIVE or does not match the engagement key.",
        )
    if eng["engagement_type"] != "REQUISITION":
        raise_err(
            ERR_ENGAGEMENT_TYPE_MISMATCH,
            "Assignments may only be booked on REQUISITION engagements.",
        )
    if offer["status"] != "ACCEPTED" or offer["engagement_id"] != engagement_id:
        raise_err(
            ERR_OFFER_NOT_ACCEPTED,
            "The offer must be ACCEPTED and belong to the named engagement.",
        )
    if worker["supplier_id"] != offer["supplier_id"]:
        raise_err(
            ERR_WORKER_SUPPLIER_MISMATCH,
            "The worker's supplier differs from the offer's supplier.",
        )

    # -- fiscal (422): ceiling, then markup, then floor --
    if bill_rate > card["bill_rate_ceiling_cents"]:
        raise_err(ERR_RATE_ABOVE_CEILING, "bill_rate_cents exceeds the rate card ceiling.")
    if not markup_allowed(bill_rate, pay_rate, card, sup["tier"]):
        raise_err(ERR_MARKUP_ABOVE_CAP, "Markup exceeds the applicable cap.")
    if pay_rate < card["pay_rate_floor_cents"]:
        raise_err(ERR_PAY_BELOW_FLOOR, "pay_rate_cents is below the rate card floor.")

    rec = {
        "worker_id": worker_id,
        "engagement_id": engagement_id,
        "offer_id": offer_id,
        "supplier_id": offer["supplier_id"],
        "rate_card_id": rate_card_id,
        "bill_rate_cents": bill_rate,
        "pay_rate_cents": pay_rate,
        "start_date": start_date,
        "end_date": end_date,
        "actual_end_date": None,
        "status": "PENDING",
        "termination_reason": None,
    }
    stamp_new(rec)
    store.assignments[rec["id"]] = rec
    offer["status"] = "CONSUMED"
    touch(offer)
    if sup is not None:
        sup["offers_filled_count"] += 1
        touch(sup)
    return ok(serializers.assignment(rec), 201)


@bp.get("/v1/assignments")
def list_assignments():
    require_roles(*ALL_READ)
    filters = {
        "worker_id": request.args.get("worker_id"),
        "engagement_id": request.args.get("engagement_id"),
        "supplier_id": request.args.get("supplier_id"),
        "rate_card_id": request.args.get("rate_card_id"),
        "offer_id": request.args.get("offer_id"),
        "status": request.args.get("status"),
    }
    records = apply_filters(list(store.assignments.values()), filters)
    page, total, limit, offset = paginate(records, serializers.assignment)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/assignments/<assignment_id>")
def get_assignment(assignment_id):
    require_roles(*ALL_READ)
    return ok(serializers.assignment(_get_assignment(assignment_id)))


@bp.post("/v1/assignments/<assignment_id>/activate")
def activate_assignment(assignment_id):
    require_roles("ProgramAdmin")
    a = _get_assignment(assignment_id)
    if a["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only a PENDING assignment can be activated.")
    eng = store.engagements.get(a["engagement_id"])
    if eng is None or eng["status"] not in ("FILLING", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "The engagement must be FILLING or ACTIVE.")
    worker = store.workers.get(a["worker_id"])
    if worker is None or worker["status"] not in ("ONBOARDING", "OFFBOARDING", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "The worker must be ONBOARDING, OFFBOARDING or ACTIVE.")
    a["status"] = "ACTIVE"
    touch(a)
    if worker["status"] in ("ONBOARDING", "OFFBOARDING"):
        worker["status"] = "ACTIVE"
        touch(worker)
    return ok(serializers.assignment(a))


@bp.post("/v1/assignments/<assignment_id>/extend")
def extend_assignment(assignment_id):
    require_roles("ProgramAdmin")
    body = get_body()
    new_end = req_date(body, "new_end_date")
    a = _get_assignment(assignment_id)
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE assignment can be extended.")
    if parse_d(new_end) <= parse_d(a["end_date"]):
        raise_err(ERR_VALIDATION, "new_end_date must be strictly later than the current end_date.")
    worker = store.workers.get(a["worker_id"])
    if worker is not None and projected_tenure_on_extend(worker, a, new_end) >= TENURE_LIMIT_DAYS:
        raise_err(
            ERR_TENURE_LIMIT_EXCEEDED,
            "Projected tenure reaches or exceeds the 730-day limit.",
        )
    a["end_date"] = new_end
    touch(a)
    return ok(serializers.assignment(a))


@bp.post("/v1/assignments/<assignment_id>/terminate")
def terminate_assignment(assignment_id):
    require_roles("ProgramAdmin")
    a = _get_assignment(assignment_id)
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE assignment can be terminated.")
    a["status"] = "TERMINATED"
    a["termination_reason"] = "MANUAL"
    a["actual_end_date"] = today_str()
    touch(a)
    worker = store.workers.get(a["worker_id"])
    if worker is not None:
        worker_offboard_cascade(worker)
    return ok(serializers.assignment(a))


@bp.post("/v1/assignments/<assignment_id>/complete")
def complete_assignment(assignment_id):
    require_roles("ProgramAdmin")
    a = _get_assignment(assignment_id)
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE assignment can be completed.")
    a["status"] = "COMPLETED"
    a["actual_end_date"] = today_str()
    touch(a)
    sup = store.suppliers.get(a["supplier_id"])
    if sup is not None:
        sup["completed_assignments_count"] += 1
        touch(sup)
    worker = store.workers.get(a["worker_id"])
    if worker is not None:
        worker_offboard_cascade(worker)
    return ok(serializers.assignment(a))
