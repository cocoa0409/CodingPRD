"""BookTaxDifference endpoints: identify (create), list, get, and the review
lifecycle: review / return-for-rework / lock / reject.

Lifecycle actions require the parent TaxYear to be OPEN (priority 5), checked
after state-transition legality (priority 4). Lock fires the deferred-tax
cascade (SCAFFOLD state_machines.BookTaxDifference hops 1-3b).
"""
from flask import Blueprint

from db import db, new_record, touch
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_TAX_YEAR_NOT_OPEN,
)
from middleware import authorized, READER_ROLES
from response import success_object, success_list
from routes.common import get_or_404, apply_filters, paginate
from serializers import serialize
from services.calc import (
    compute_difference_cents,
    compute_deferred_movement,
    compute_allowance_amount,
    recompute_deferred,
    recompute_open_year_stack_and_etrs,
    vas_of_year,
)
from validate import body_json, req_str, req_int, req_enum, opt_nullable_id

bp = Blueprint("differences", __name__)

DIFFERENCE_TYPES = ("TEMPORARY", "PERMANENT")


def _resolve_year_or_404(data):
    tax_year_id = data.get("tax_year_id")
    if isinstance(tax_year_id, str):
        get_or_404(db.tax_years, tax_year_id, "TaxYear")
    return tax_year_id


@bp.route("/tax/book-tax-differences", methods=["POST"])
def create_difference():
    caller = authorized(("TaxAccountant",))
    data = body_json()

    # Priority 3 (existence): body FK references resolve.
    tax_year_id = data.get("tax_year_id")
    year = None
    if isinstance(tax_year_id, str):
        year = get_or_404(db.tax_years, tax_year_id, "TaxYear")
    jur_probe = data.get("jurisdiction_id")
    if jur_probe is not None and isinstance(jur_probe, str):
        get_or_404(db.jurisdictions, jur_probe, "Jurisdiction")

    # Priority 5 (tax-year posture): artifact creation requires OPEN.
    if year is not None and year["status"] != "OPEN":
        raise_error(ERR_TAX_YEAR_NOT_OPEN,
                    "book-to-tax differences may be identified only while the year is OPEN")

    # Priority 11 (structural).
    tax_year_id = req_str(data, "tax_year_id")
    jurisdiction_id = opt_nullable_id(data, "jurisdiction_id")
    if jurisdiction_id is not None:
        get_or_404(db.jurisdictions, jurisdiction_id, "Jurisdiction")
    description = req_str(data, "description")
    book_amount = req_int(data, "book_amount_cents")
    tax_amount = req_int(data, "tax_amount_cents")
    difference_type = req_enum(data, "difference_type", DIFFERENCE_TYPES)
    if year is None:
        raise_error(ERR_NOT_FOUND, f"TaxYear '{tax_year_id}' does not exist")

    diff = new_record({
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "description": description,
        "book_amount_cents": book_amount,
        "tax_amount_cents": tax_amount,
        "difference_cents": compute_difference_cents(book_amount, tax_amount),
        "difference_type": difference_type,
        "status": "IDENTIFIED",
        "created_by_user_id": caller.user_id,
        "reviewed_by_user_id": None,
    })
    db.differences[diff["id"]] = diff
    return success_object(serialize(diff), status=201)


@bp.route("/tax/book-tax-differences", methods=["GET"])
def list_differences():
    authorized(READER_ROLES)
    recs = apply_filters(db.differences.values(), {
        "tax_year_id": "tax_year_id",
        "jurisdiction_id": "jurisdiction_id",
        "status": "status",
        "difference_type": "difference_type",
    })
    page, total, limit, offset = paginate(recs)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.route("/tax/book-tax-differences/<differenceId>", methods=["GET"])
def get_difference(differenceId):
    authorized(READER_ROLES)
    return success_object(serialize(get_or_404(db.differences, differenceId, "BookTaxDifference")))


def _lifecycle_target(difference_id, allowed_from):
    """Priorities 3-5 shared by all difference lifecycle actions."""
    diff = get_or_404(db.differences, difference_id, "BookTaxDifference")
    if diff["status"] not in allowed_from:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"action is not defined from difference status {diff['status']}")
    year = db.tax_years.get(diff["tax_year_id"])
    if year is not None and year["status"] != "OPEN":
        raise_error(ERR_TAX_YEAR_NOT_OPEN,
                    "difference lifecycle actions require the parent TaxYear to be OPEN")
    return diff, year


@bp.route("/tax/book-tax-differences/<differenceId>/review", methods=["POST"])
def review_difference(differenceId):
    caller = authorized(("TaxManager",))
    diff, _year = _lifecycle_target(differenceId, ("IDENTIFIED",))
    diff["status"] = "REVIEWED"
    diff["reviewed_by_user_id"] = caller.user_id
    touch(diff)
    return success_object(serialize(diff))


@bp.route("/tax/book-tax-differences/<differenceId>/return-for-rework", methods=["POST"])
def return_difference_for_rework(differenceId):
    authorized(("TaxManager",))
    diff, _year = _lifecycle_target(differenceId, ("REVIEWED",))
    diff["status"] = "IDENTIFIED"
    diff["reviewed_by_user_id"] = None
    touch(diff)
    return success_object(serialize(diff))


@bp.route("/tax/book-tax-differences/<differenceId>/lock", methods=["POST"])
def lock_difference(differenceId):
    authorized(("TaxManager", "TaxDirector"))
    diff, year = _lifecycle_target(differenceId, ("REVIEWED",))
    diff["status"] = "LOCKED"
    touch(diff)

    # Cascade hop 1: upsert the DeferredTaxItem for TEMPORARY nonzero differences.
    if diff["difference_type"] == "TEMPORARY" and diff["difference_cents"] != 0:
        item_kind, movement = compute_deferred_movement(
            diff["difference_cents"], year["enacted_federal_rate_bp"])
        item = next((i for i in db.deferred_items.values()
                     if i["source_difference_id"] == diff["id"]), None)
        if item is None:
            item = new_record({
                "tax_year_id": year["id"],
                "source_difference_id": diff["id"],
                "item_kind": item_kind,
                "opening_balance_cents": 0,
                "movement_cents": movement,
                "closing_balance_cents": movement,  # opening (0) + movement
            })
            db.deferred_items[item["id"]] = item
        else:
            item["item_kind"] = item_kind
            item["movement_cents"] = movement
            item["closing_balance_cents"] = item["opening_balance_cents"] + movement
            touch(item)

    # Cascade hop 2 + 3a: deferred aggregates, current stack, ETRs.
    recompute_deferred(year)
    recompute_open_year_stack_and_etrs(year)

    # Cascade hop 3b: live (DRAFT/SUBMITTED) assessments re-measure against the
    # updated DTA pool; APPROVED amounts are frozen.
    for va in vas_of_year(year["id"]):
        if va["status"] in ("DRAFT", "SUBMITTED"):
            va["allowance_amount_cents"] = compute_allowance_amount(va, year)
            touch(va)

    return success_object(serialize(diff))


@bp.route("/tax/book-tax-differences/<differenceId>/reject", methods=["POST"])
def reject_difference(differenceId):
    authorized(("TaxManager",))
    diff, year = _lifecycle_target(differenceId, ("REVIEWED",))
    diff["status"] = "REJECTED"
    touch(diff)
    # Rejected differences never enter any calculation input set; the stack is
    # nonetheless maintained per the declared lock/reject trigger.
    recompute_open_year_stack_and_etrs(year)
    return success_object(serialize(diff))
