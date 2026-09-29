"""Public hearings, statutory notice, protest filings and protest tabulation (PRD §3.6)."""

from flask import Blueprint

import validate as v
from auth import ANY_ROLE, check_municipality_scope, check_owner_scope, prelude
from clockutil import add_days
from db import base_record, db, notice_record, touch
from errors import ApiError
from response import object_response, paginate
from services import calc, domain

bp = Blueprint("hearings", __name__)

FILING_ROLES = ("PropertyOwner", "CityClerk")


def _hearing_for_write(hearing_id, roles):
    user_id, role = prelude(roles)
    soft_hearing = domain.soft("hearings", hearing_id)
    if soft_hearing is not None:
        check_municipality_scope(role, user_id, soft_hearing.get("municipality_id"))
        check_municipality_scope(
            role, user_id, domain.municipality_id_of_case(domain.case_of_hearing(soft_hearing))
        )
    hearing = domain.path_record("hearings", hearing_id)
    return hearing, user_id, role


# ---------------------------------------------------------------------------
# Hearings
# ---------------------------------------------------------------------------

@bp.post("/public-hearings")
def create_hearing():
    user_id, role = prelude(("CityClerk",))
    body = v.get_body()

    raw_municipality = body.get("municipality_id")
    if isinstance(raw_municipality, str):
        check_municipality_scope(role, user_id, raw_municipality)
    soft_case = domain.soft("cases", body.get("annexation_case_id"))
    check_municipality_scope(role, user_id, domain.municipality_id_of_case(soft_case))

    case_id = v.id_field(body, "annexation_case_id")
    case = domain.body_ref("cases", case_id)
    municipality_id = v.id_field(body, "municipality_id")
    municipality = domain.body_ref("municipalities", municipality_id)

    start_at = v.datetime_field(body, "scheduled_start_at")
    end_at = v.datetime_field(body, "scheduled_end_at")
    protest_window_days = v.int_field(
        body, "protest_window_days", required=False, default=30, minimum=1, maximum=120
    )
    if end_at <= start_at:
        v.bad("scheduled_end_at must be later than scheduled_start_at.")

    domain.assert_case_not_terminal(case)

    buffer_minutes = municipality["hearing_changeover_buffer_minutes"]
    for peer in domain.rows("hearings"):
        if peer["municipality_id"] != municipality_id:
            continue
        if peer["hearing_status"] not in ("SCHEDULED", "HELD"):
            continue
        if calc.chamber_conflict(
            start_at, end_at, peer["scheduled_start_at"], peer["scheduled_end_at"], buffer_minutes
        ):
            raise ApiError(
                "ERR_HEARING_SLOT_CONFLICT",
                "The council chamber is already occupied inside the changeover buffer.",
            )

    record = base_record()
    record.update(
        {
            "annexation_case_id": case["id"],
            "municipality_id": municipality_id,
            "scheduled_start_at": start_at,
            "scheduled_end_at": end_at,
            "protest_window_days": protest_window_days,
            "hearing_status": "SCHEDULED",
            "held_at": None,
            "notice_published_at": None,
            "protest_opens_at": None,
            "protest_closes_at": None,
            "protest_pct": calc.pct2(0),
            "protest_outcome": "OPEN",
        }
    )
    db.hearings[record["id"]] = record
    return object_response(record, 201)


@bp.get("/public-hearings/<hearing_id>")
def read_hearing(hearing_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("hearings", hearing_id))


@bp.get("/public-hearings")
def list_hearings():
    prelude(ANY_ROLE)
    return paginate(
        domain.rows("hearings"), ("annexation_case_id", "municipality_id", "hearing_status")
    )


# ---------------------------------------------------------------------------
# Notice publications
# ---------------------------------------------------------------------------

@bp.post("/public-hearings/<hearing_id>/notice-publications")
def publish_notice(hearing_id):
    hearing, _user_id, _role = _hearing_for_write(hearing_id, ("CityClerk",))
    body = v.get_body()
    publication_type = v.enum_field(
        body, "publication_type", ("NEWSPAPER", "MAILED", "POSTED")
    )
    case = domain.case_of_hearing(hearing)
    domain.assert_case_not_terminal(case)

    admissible = False
    if case is not None:
        if case["status"] == "SUFFICIENCY_REVIEW":
            admissible = True
        elif case["status"] == "TERRITORY_CERTIFIED" and case["method"] in (
            "REFERENDUM",
            "INVOLUNTARY_ORDINANCE",
        ):
            admissible = True
    if not admissible:
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "The case is not in a state where statutory notice may be published.",
        )

    if hearing["hearing_status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_NOT_SCHEDULED", "The hearing is not SCHEDULED.")
    if domain.adopted_plan(case) is None:
        raise ApiError("ERR_PLAN_NOT_ADOPTED", "The case has no ADOPTED plan of services.")

    published_at = db.now()
    record = notice_record()
    record.update(
        {
            "public_hearing_id": hearing["id"],
            "publication_type": publication_type,
            "published_at": published_at,
            "notice_status": "PUBLISHED",
        }
    )
    db.notices[record["id"]] = record

    hearing["notice_published_at"] = published_at
    touch(hearing)
    case["status"] = "HEARING_NOTICED"
    touch(case)
    return object_response(record, 201)


@bp.get("/public-hearings/<hearing_id>/notice-publications")
def list_hearing_notices(hearing_id):
    prelude(ANY_ROLE)
    hearing = domain.path_record("hearings", hearing_id)
    return paginate(domain.hearing_notices(hearing), ("notice_status",))


@bp.get("/notice-publications/<notice_id>")
def read_notice(notice_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("notices", notice_id))


@bp.get("/notice-publications")
def list_notices():
    prelude(ANY_ROLE)
    return paginate(domain.rows("notices"), ("public_hearing_id", "notice_status"))


# ---------------------------------------------------------------------------
# Holding the hearing
# ---------------------------------------------------------------------------

@bp.post("/public-hearings/<hearing_id>/hold")
def hold_hearing(hearing_id):
    hearing, _user_id, _role = _hearing_for_write(hearing_id, ("CityClerk",))
    case = domain.case_of_hearing(hearing)
    domain.assert_case_not_terminal(case)
    statute = domain.statute_of_case(case)

    if hearing["hearing_status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_NOT_SCHEDULED", "The hearing is not SCHEDULED.")
    for peer in domain.rows("hearings"):
        if (
            peer["id"] != hearing["id"]
            and peer["annexation_case_id"] == hearing["annexation_case_id"]
            and peer["hearing_status"] == "HELD"
        ):
            raise ApiError(
                "ERR_HEARING_ALREADY_HELD", "Another hearing of this case has already been held."
            )

    if hearing["notice_published_at"] is None:
        raise ApiError("ERR_NOTICE_NOT_PUBLISHED", "No statutory notice supports this hearing.")

    now = db.now()
    if now < add_days(hearing["notice_published_at"], statute["notice_min_days"]):
        raise ApiError(
            "ERR_NOTICE_WINDOW_NOT_SATISFIED",
            "The statutory notice period has not elapsed.",
        )
    if now < hearing["scheduled_start_at"]:
        raise ApiError("ERR_HEARING_NOT_STARTED", "The hearing's scheduled start has not arrived.")

    hearing["hearing_status"] = "HELD"
    hearing["held_at"] = now
    hearing["protest_opens_at"] = now
    hearing["protest_closes_at"] = add_days(now, hearing["protest_window_days"])
    hearing["protest_outcome"] = "OPEN"
    touch(hearing)

    case["status"] = "HEARING_HELD"
    case["hearing_held_at"] = now
    touch(case)
    return object_response(hearing)


@bp.post("/public-hearings/<hearing_id>/close-protest-period")
def close_protest_period(hearing_id):
    hearing, _user_id, _role = _hearing_for_write(hearing_id, ("CityClerk",))
    case = domain.case_of_hearing(hearing)
    domain.assert_case_not_terminal(case)
    statute = domain.statute_of_case(case)

    if hearing["hearing_status"] != "HELD" or hearing["protest_outcome"] != "OPEN":
        raise ApiError("ERR_PROTEST_PERIOD_CLOSED", "The protest period is not open.")
    if db.now() <= hearing["protest_closes_at"]:
        raise ApiError(
            "ERR_PROTEST_PERIOD_NOT_CLOSED", "The protest period has not yet closed."
        )

    result = calc.protest_evaluation(
        statute,
        domain.qualifying_filings(hearing),
        case["territory_assessed_value_cents"],
        domain.territory_owner_count(case),
    )
    hearing["protest_pct"] = result["protest_pct"]
    hearing["protest_outcome"] = "SUSTAINED" if result["sustained"] else "FAILED"
    touch(hearing)

    case["protest_pct"] = result["protest_pct"]
    case["protest_outcome"] = hearing["protest_outcome"]
    if result["sustained"]:
        case["status"] = "PROTEST_SUSTAINED"
    touch(case)
    return object_response(hearing)


# ---------------------------------------------------------------------------
# Protest filings
# ---------------------------------------------------------------------------

@bp.post("/protest-filings")
def create_filing():
    user_id, role = prelude(FILING_ROLES)
    body = v.get_body()

    soft_hearing = domain.soft("hearings", body.get("public_hearing_id"))
    if soft_hearing is not None:
        check_municipality_scope(role, user_id, soft_hearing.get("municipality_id"))
    raw_owner = body.get("property_owner_id")
    if isinstance(raw_owner, str):
        check_owner_scope(role, user_id, raw_owner)

    hearing_id = v.id_field(body, "public_hearing_id")
    hearing = domain.body_ref("hearings", hearing_id)
    parcel_id = v.id_field(body, "parcel_id")
    parcel = domain.body_ref("parcels", parcel_id)
    owner_id = v.id_field(body, "property_owner_id")
    domain.body_ref("property_owners", owner_id)

    share = v.num_field(
        body, "ownership_share_pct", exclusive_minimum=0, maximum=100, places=2
    )

    case = domain.case_of_hearing(hearing)
    domain.assert_case_not_terminal(case)

    if hearing["hearing_status"] != "HELD" or hearing["protest_outcome"] != "OPEN":
        raise ApiError("ERR_PROTEST_PERIOD_CLOSED", "The protest period is not open.")

    now = db.now()
    if now < hearing["protest_opens_at"] or now > hearing["protest_closes_at"]:
        raise ApiError(
            "ERR_PROTEST_FILING_OUT_OF_WINDOW",
            "The logical clock lies outside the protest window.",
        )

    if case is None or parcel["annexation_case_id"] != case["id"]:
        raise ApiError(
            "ERR_PARCEL_CASE_MISMATCH",
            "The parcel does not belong to the hearing's annexation case.",
        )

    siblings = [
        f
        for f in domain.rows("filings")
        if f["public_hearing_id"] == hearing["id"]
        and f["parcel_id"] == parcel["id"]
        and f["filing_status"] == "FILED"
    ]
    for existing in siblings:
        if existing["property_owner_id"] == owner_id:
            raise ApiError(
                "ERR_FILING_DUPLICATE",
                "This owner has already protested for this parcel at this hearing.",
            )

    total_share = sum((calc.D(f["ownership_share_pct"]) for f in siblings), calc.ZERO) + share
    if total_share > calc.HUNDRED:
        raise ApiError(
            "ERR_PROTEST_OWNERSHIP_SHARE_INVALID",
            "Filed ownership shares for this parcel would exceed 100 percent.",
        )

    record = base_record()
    record.update(
        {
            "public_hearing_id": hearing["id"],
            "parcel_id": parcel["id"],
            "property_owner_id": owner_id,
            "ownership_share_pct": share,
            "filing_status": "FILED",
            "filed_at": now,
            "protest_value_cents": calc.share_value_cents(parcel["assessed_value_cents"], share),
        }
    )
    db.filings[record["id"]] = record
    return object_response(record, 201)


@bp.get("/protest-filings/<filing_id>")
def read_filing(filing_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("filings", filing_id))


@bp.get("/protest-filings")
def list_filings():
    prelude(ANY_ROLE)
    return paginate(
        domain.rows("filings"),
        ("public_hearing_id", "parcel_id", "property_owner_id", "filing_status"),
    )


@bp.post("/protest-filings/<filing_id>/withdraw")
def withdraw_filing(filing_id):
    user_id, role = prelude(FILING_ROLES)
    soft_filing = domain.soft("filings", filing_id)
    if soft_filing is not None:
        soft_hearing = domain.soft("hearings", soft_filing.get("public_hearing_id"))
        if soft_hearing is not None:
            check_municipality_scope(role, user_id, soft_hearing.get("municipality_id"))
        check_owner_scope(role, user_id, soft_filing.get("property_owner_id"))
    filing = domain.path_record("filings", filing_id)

    hearing = domain.soft("hearings", filing["public_hearing_id"])
    case = domain.case_of_filing(filing)
    domain.assert_case_not_terminal(case)

    if filing["filing_status"] != "FILED":
        raise ApiError("ERR_FILING_ALREADY_WITHDRAWN", "The filing is already withdrawn.")
    if hearing is None or hearing["protest_outcome"] != "OPEN":
        raise ApiError("ERR_PROTEST_PERIOD_CLOSED", "The protest period has closed.")

    filing["filing_status"] = "WITHDRAWN"
    filing["protest_value_cents"] = 0
    touch(filing)
    return object_response(filing)
