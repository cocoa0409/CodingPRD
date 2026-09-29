"""Prize awards: reads, approval and payment (PRD 3.8)."""
from flask import Blueprint

from clock import now_iso
from constants import AWARD_STATUSES, PURSE_CATEGORIES
from db import touch
from errors import err
from middleware import authenticate
from response import list_response, object_response, paginate
from services import gates, lookup, serializers
from validators import enum_filter, get_body, pagination_args, rstr, str_filter

bp = Blueprint("awards", __name__)

READ_ROLES = ("FinanceOfficer", "ElitesDirector", "TechnicalOfficial", "AthleteAgent")


@bp.get("/prize-awards/<award_id>")
def read_award(award_id):
    authenticate(READ_ROLES)
    award = lookup.get_award(award_id)
    return object_response(serializers.ser_award(award))


@bp.get("/prize-awards")
def list_awards():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = {}
    for name in ("race_edition_id", "race_result_id", "athlete_id"):
        value = str_filter(name)
        if value is not None:
            filters[name] = value
    category = enum_filter("category", PURSE_CATEGORIES)
    status = enum_filter("status", AWARD_STATUSES)
    if category is not None:
        filters["category"] = category
    if status is not None:
        filters["status"] = status
    rows = lookup.rows("prize_awards", **filters)
    window, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.ser_award(r) for r in window], limit, offset, total
    )


@bp.post("/prize-awards/<award_id>/approve")
def approve_award(award_id):
    role, user_id = authenticate(("FinanceOfficer",))
    award = lookup.get_award(award_id)
    get_body()

    edition = lookup.soft_get("race_editions", award["race_edition_id"])
    gates.gate_edition(edition, ("RESULTS_CERTIFIED",))

    if award["status"] != "COMPUTED":
        raise err("ERR_INVALID_AWARD_STATE", "Only a COMPUTED award may be approved")

    result = lookup.soft_get("race_results", award["race_result_id"])
    if result is None or result["certification_status"] != "CERTIFIED":
        raise err(
            "ERR_RESULT_NOT_CERTIFIED",
            "The award's race result is not CERTIFIED",
        )

    if not gates.has_cleared_in_competition_test(
        award["athlete_id"], award["race_edition_id"]
    ):
        raise err(
            "ERR_IN_COMPETITION_TEST_NOT_CLEARED",
            "No CLEARED in-competition test exists for this athlete in this edition",
        )

    award["status"] = "APPROVED"
    award["approved_by_user_id"] = user_id
    touch(award)
    return object_response(serializers.ser_award(award))


@bp.post("/prize-awards/<award_id>/pay")
def pay_award(award_id):
    role, user_id = authenticate(("FinanceOfficer",))
    award = lookup.get_award(award_id)
    body = get_body()
    payment_reference = rstr(body, "payment_reference")

    edition = lookup.soft_get("race_editions", award["race_edition_id"])
    gates.gate_edition(edition, ("RESULTS_CERTIFIED",))

    if award["status"] != "APPROVED":
        raise err("ERR_INVALID_AWARD_STATE", "Only an APPROVED award may be paid")

    if award["approved_by_user_id"] == user_id:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approver of an award may not also pay it",
        )

    award["status"] = "PAID"
    award["paid_by_user_id"] = user_id
    award["payment_reference"] = payment_reference
    award["paid_at"] = now_iso()
    touch(award)
    return object_response(serializers.ser_award(award))
