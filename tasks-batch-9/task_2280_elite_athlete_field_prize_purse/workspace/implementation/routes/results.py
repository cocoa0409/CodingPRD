"""Race results: entry, certification, disqualification and the record claim
dimension (PRD 3.7)."""
from flask import Blueprint

from constants import (
    CERTIFICATION_STATUSES,
    DIVISIONS,
    DQ_REASONS,
    RECORD_CLAIM_STATUSES,
)
from db import db, new_record, touch
from errors import err, invalid
from middleware import authenticate
from response import list_response, object_response, paginate
from services import cascade, gates, lookup, serializers
from validators import (
    enum_filter,
    get_body,
    ostr,
    pagination_args,
    renum,
    rint,
    rstr,
    str_filter,
)

bp = Blueprint("results", __name__)

READ_ROLES = (
    "TechnicalOfficial",
    "ElitesDirector",
    "FinanceOfficer",
    "SanctioningBody",
    "AthleteAgent",
)


@bp.post("/race-results")
def create_result():
    authenticate(("TechnicalOfficial",))
    body = get_body()
    edition_id = rstr(body, "race_edition_id")
    invitation_id = rstr(body, "invitation_id")
    edition = lookup.get_edition(edition_id)
    invitation = lookup.get_invitation(invitation_id)

    gun_seconds = rint(body, "gun_seconds", minimum=1)
    net_seconds = rint(body, "net_seconds", minimum=1)
    if net_seconds > gun_seconds:
        raise invalid("net_seconds must not be greater than gun_seconds")

    gates.gate_edition(edition, ("RACED",))

    if lookup.rows("race_results", invitation_id=invitation_id):
        raise err("ERR_DUPLICATE_RESULT", "A result already exists for this invitation")

    if (
        invitation["race_edition_id"] != edition_id
        or invitation["status"] != "ACCEPTED"
        or invitation["bib_number"] is None
    ):
        raise err(
            "ERR_INVITATION_EDITION_MISMATCH",
            "The invitation must belong to this edition, be ACCEPTED and hold a bib",
        )

    division = invitation["division"]
    official = net_seconds if division == "WHEELCHAIR" else gun_seconds
    result = new_record(
        race_edition_id=edition_id,
        invitation_id=invitation_id,
        athlete_id=invitation["athlete_id"],
        division=division,
        gun_seconds=gun_seconds,
        net_seconds=net_seconds,
        official_seconds=official,
        certification_status="PROVISIONAL",
        record_claim_status="NONE",
        dq_reason=None,
        place_overall=None,
        place_division=None,
        place_masters=None,
        tie_group_size=1,
        is_masters=False,
        sanctioning_submission_ref=None,
    )
    db.race_results[result["id"]] = result
    return object_response(serializers.ser_result(result), 201)


@bp.get("/race-results/<result_id>")
def read_result(result_id):
    authenticate(READ_ROLES)
    result = lookup.get_result(result_id)
    return object_response(serializers.ser_result(result))


@bp.get("/race-results")
def list_results():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = {}
    for name in ("race_edition_id", "athlete_id", "invitation_id"):
        value = str_filter(name)
        if value is not None:
            filters[name] = value
    division = enum_filter("division", DIVISIONS)
    certification_status = enum_filter("certification_status", CERTIFICATION_STATUSES)
    record_claim_status = enum_filter("record_claim_status", RECORD_CLAIM_STATUSES)
    if division is not None:
        filters["division"] = division
    if certification_status is not None:
        filters["certification_status"] = certification_status
    if record_claim_status is not None:
        filters["record_claim_status"] = record_claim_status
    rows = lookup.rows("race_results", **filters)
    window, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.ser_result(r) for r in window], limit, offset, total
    )


@bp.post("/race-results/<result_id>/certify")
def certify_result(result_id):
    authenticate(("TechnicalOfficial",))
    result = lookup.get_result(result_id)
    get_body()

    edition = lookup.soft_get("race_editions", result["race_edition_id"])
    gates.gate_edition(edition, ("RACED",))

    if result["certification_status"] != "PROVISIONAL":
        raise err(
            "ERR_RESULT_NOT_CERTIFIED",
            "Only a PROVISIONAL result may be certified",
        )
    result["certification_status"] = "CERTIFIED"
    touch(result)
    return object_response(serializers.ser_result(result))


@bp.post("/race-results/<result_id>/disqualify")
def disqualify_result(result_id):
    authenticate(("TechnicalOfficial",))
    result = lookup.get_result(result_id)
    body = get_body()
    dq_reason = renum(body, "dq_reason", DQ_REASONS)

    edition = lookup.soft_get("race_editions", result["race_edition_id"])
    gates.gate_edition(edition, ("RACED", "RESULTS_CERTIFIED"))

    if result["certification_status"] not in ("PROVISIONAL", "CERTIFIED"):
        raise err(
            "ERR_RESULT_NOT_CERTIFIED",
            "Only a PROVISIONAL or CERTIFIED result may be disqualified",
        )

    edition_changed = cascade.disqualify_result(edition, result, dq_reason)
    if edition_changed:
        touch(edition)
    return object_response(serializers.ser_result(result))


@bp.post("/race-results/<result_id>/record-submission")
def record_submission(result_id):
    authenticate(("TechnicalOfficial",))
    result = lookup.get_result(result_id)
    body = get_body()
    submission_ref = rstr(body, "sanctioning_submission_ref")

    edition = lookup.soft_get("race_editions", result["race_edition_id"])
    gates.gate_edition(edition)

    if result["record_claim_status"] in ("SUBMITTED", "RATIFIED"):
        raise err(
            "ERR_INVALID_RECORD_CLAIM_STATE",
            "The record claim has already been lodged",
        )
    if result["certification_status"] != "CERTIFIED":
        # Priority 8 target-entity state (PRD 2.11) surfaces ahead of the
        # priority-15 record-claim eligibility check below.
        raise err(
            "ERR_RESULT_NOT_CERTIFIED",
            "A record package may only be lodged for a CERTIFIED result",
        )
    if (
        result["division"] == "SUB_ELITE"
        or result["record_claim_status"] not in ("CLAIMED", "REJECTED")
    ):
        raise err(
            "ERR_RECORD_CLAIM_NOT_ELIGIBLE",
            "This result is not eligible for a record ratification package",
        )

    result["sanctioning_submission_ref"] = submission_ref
    result["record_claim_status"] = "SUBMITTED"
    touch(result)
    return object_response(serializers.ser_result(result))


@bp.post("/race-results/<result_id>/record-decision")
def record_decision(result_id):
    authenticate(("SanctioningBody",))
    result = lookup.get_result(result_id)
    body = get_body()
    decision = renum(body, "decision", ("RATIFIED", "REJECTED"))
    ostr(body, "decision_note")

    edition = lookup.soft_get("race_editions", result["race_edition_id"])
    gates.gate_edition(edition)

    if result["record_claim_status"] != "SUBMITTED":
        raise err(
            "ERR_INVALID_RECORD_CLAIM_STATE",
            "Only a SUBMITTED record claim may be decided",
        )
    if decision == "RATIFIED" and result["certification_status"] != "CERTIFIED":
        raise err(
            "ERR_INVALID_RECORD_CLAIM_STATE",
            "A record may only be ratified for a CERTIFIED result",
        )

    if decision == "REJECTED":
        result["record_claim_status"] = "REJECTED"
        touch(result)
        return object_response(serializers.ser_result(result))

    cascade.ratify_record(edition, result)
    return object_response(serializers.ser_result(result))
