"""TerritoryAssignment endpoints: create (half-open exclusivity + window
checks), list/get, release."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_DATE_RANGE,
    ERR_DEALER_NOT_FOUND,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_DEALER_MISMATCH,
    ERR_TERRITORY_OVERLAP,
    ERR_ASSIGNMENT_OUTSIDE_AGREEMENT,
    ERR_ASSIGNMENT_NOT_ACTIVE,
)
from middleware import require_roles
from response import success_object, success_list
from services.cascades import release_assignment
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_date,
    parse_pagination,
    require_date,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("assignments", __name__)

COVERAGE_TYPES = {"EXCLUSIVE", "SHARED"}


def get_assignment_or_404(assignment_id: str) -> dict:
    assignment = db.assignments.get(assignment_id)
    if assignment is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "Territory assignment id does not exist")
    return assignment


def _half_open_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Half-open [starts_on, ends_on) overlap: mere adjacency is allowed."""
    return a_start < b_end and b_start < a_end


@bp.route("/territory-assignments", methods=["POST"])
@require_roles("OemNetworkAdmin")
def create_assignment(_user_id: str, _role: str):
    body = get_json_body()
    dealer_id = require_string(body, "dealer_id")
    agreement_id = require_string(body, "agreement_id")
    territory_code = require_string(body, "territory_code")
    coverage_type = require_enum(body, "coverage_type", COVERAGE_TYPES)
    starts_on = require_date(body, "starts_on")
    ends_on = require_date(body, "ends_on")
    # Priority 3 input format: end strictly after start.
    if parse_date(ends_on, "ends_on") <= parse_date(starts_on, "starts_on"):
        raise_err(ERR_INVALID_DATE_RANGE, "ends_on must be strictly after starts_on")

    # Priority 4 existence: body references left-to-right (dealer, agreement).
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        raise_err(ERR_AGREEMENT_NOT_FOUND, "Agreement id does not exist")

    # Priority 6 state: agreement must be ACTIVE.
    if agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "Assignment creation requires agreement ACTIVE")

    # Priority 8: half-open territory overlap per coverage rules.
    for other in db.assignments.values():
        if other["status"] != "ACTIVE":
            continue
        if other["territory_code"] != territory_code:
            continue
        if not _half_open_overlap(starts_on, ends_on, other["starts_on"], other["ends_on"]):
            continue
        # SHARED overlaps SHARED freely; any EXCLUSIVE side forbids overlap.
        if coverage_type == "EXCLUSIVE" or other["coverage_type"] == "EXCLUSIVE":
            raise_err(
                ERR_TERRITORY_OVERLAP,
                "Overlapping ACTIVE assignment on the same territory_code with EXCLUSIVE coverage",
            )

    # Priority 9 temporal: window must sit within the agreement's window.
    if starts_on < agreement["effective_date"] or ends_on > agreement["expiry_date"]:
        raise_err(
            ERR_ASSIGNMENT_OUTSIDE_AGREEMENT,
            "Assignment window must satisfy agreement.effective_date <= starts_on and ends_on <= agreement.expiry_date",
        )

    # Priority 10 referential: agreement must belong to the same dealer.
    if agreement["dealer_id"] != dealer_id:
        raise_err(
            ERR_AGREEMENT_DEALER_MISMATCH,
            "TerritoryAssignment.agreement_id does not belong to TerritoryAssignment.dealer_id",
        )

    assignment = {
        "dealer_id": dealer_id,
        "agreement_id": agreement_id,
        "territory_code": territory_code,
        "coverage_type": coverage_type,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "status": "ACTIVE",
    }
    db.stamp_new(assignment)
    db.assignments[assignment["id"]] = assignment
    return success_object(serialize(assignment), 201)


@bp.route("/territory-assignments", methods=["GET"])
@require_roles("Any")
def list_assignments(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.assignments.values()))
    items = apply_filters(items, ["dealer_id", "agreement_id", "territory_code", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/territory-assignments/<assignment_id>", methods=["GET"])
@require_roles("Any")
def get_assignment(assignment_id: str, _user_id: str, _role: str):
    assignment = get_assignment_or_404(assignment_id)
    return success_object(serialize(assignment))


@bp.route("/territory-assignments/<assignment_id>/release", methods=["POST"])
@require_roles("OemNetworkAdmin")
def release(assignment_id: str, _user_id: str, _role: str):
    assignment = get_assignment_or_404(assignment_id)
    if assignment["status"] != "ACTIVE":
        raise_err(ERR_ASSIGNMENT_NOT_ACTIVE, "Release requires assignment ACTIVE")
    release_assignment(assignment)
    return success_object(serialize(assignment))
