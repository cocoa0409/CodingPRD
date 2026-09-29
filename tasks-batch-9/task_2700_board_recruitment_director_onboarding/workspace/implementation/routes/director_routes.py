"""Directors, seating, departure notices and the skills-matrix ratings."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    SEATED_DIRECTOR,
    require,
    require_director_owner,
)
from calc import parse_iso_date, require_policy, whole_years
from derive import (
    _apply,
    end_active_assignments,
    recompute_compliance,
    recompute_onboarding,
)
from errors import fail
from payload import body, check_enum, check_min, check_range, optional, parse_date, required
from store import clock_date, clock_instant, db, new_row, touch
from vocab import (
    DIRECTOR_COMPLIANCE_STATUS,
    DIRECTOR_ONBOARDING_STATUS,
    DIRECTOR_SERVICE_STATUS,
    INITIAL_SERVICE_STATUS,
    NOTICE_TYPE,
    RATING_VALIDATION_STATUS,
)

from routes.common import apply_filters, by_created_at, emit, emit_list, need

bp = Blueprint("director", __name__)

READ_ALL = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER,
            SEATED_DIRECTOR)


@bp.post("/directors")
def create_director():
    require(CORPORATE_SECRETARY)
    b = body()
    full_name = required(b, "full_name", "string")
    email = required(b, "email", "string")
    birth_date = required(b, "birth_date", "string")
    appointed_on = required(b, "appointed_on", "string")
    is_management = optional(b, "is_management", "boolean", False)
    is_sitting_ceo = optional(b, "is_sitting_ceo_elsewhere", "boolean", False)
    is_independent = optional(b, "is_independent", "boolean", True)
    shares_held = optional(b, "shares_held", "integer", 0)
    initial_status = check_enum("initial_service_status",
                                optional(b, "initial_service_status", "string", "ONBOARDING"),
                                INITIAL_SERVICE_STATUS)
    check_min("shares_held", shares_held, 0)
    born = parse_date(birth_date, "birth_date")
    appointed = parse_date(appointed_on, "appointed_on")
    if is_management:
        is_independent = False
    today = clock_date()
    row = new_row({
        "full_name": full_name,
        "email": email,
        "birth_date": birth_date,
        "appointed_on": appointed_on,
        "source_candidate_id": None,
        "is_management": is_management,
        "is_sitting_ceo_elsewhere": is_sitting_ceo,
        "is_independent": is_independent,
        "shares_held": shares_held,
        "service_status": initial_status,
        "compliance_status": "COMPLIANT",
        "onboarding_status": "NOT_STARTED",
        "onboarding_completion_pct": 0.00,
        "age_years": whole_years(born, today),
        "tenure_years": whole_years(appointed, today),
        "external_public_board_count": 0,
        "education_hours_cycle": 0.0,
        "retirement_notice_at": None,
    })
    db.directors[row["id"]] = row
    return emit(row, 201)


@bp.get("/directors/<director_id>")
def read_director(director_id):
    require(*READ_ALL)
    return emit(need("director", director_id))


@bp.get("/directors")
def list_directors():
    require(*READ_ALL)
    rows = apply_filters(list(db.directors.values()), {
        "service_status": ("service_status", "str"),
        "compliance_status": ("compliance_status", "str"),
        "onboarding_status": ("onboarding_status", "str"),
        "source_candidate_id": ("source_candidate_id", "str"),
    })
    return emit_list(by_created_at(rows))


@bp.post("/directors/<director_id>/seat")
def seat_director(director_id):
    require(CORPORATE_SECRETARY)
    director = need("director", director_id)
    policy = require_policy()
    if director["service_status"] != "ONBOARDING":
        fail("ERR_DIRECTOR_STATE_INVALID",
             "Only an ONBOARDING director may be seated; this one is %s."
             % director["service_status"])
    recompute_onboarding(director)
    if director["onboarding_status"] != "COMPLETE":
        fail("ERR_ONBOARDING_INCOMPLETE",
             "The director's onboarding programme is %s." % director["onboarding_status"])
    seated = sum(1 for d in db.directors.values() if d["service_status"] == "SEATED")
    if seated + 1 > policy["authorized_seats"]:
        fail("ERR_SEAT_COUNT_EXCEEDED",
             "The board already holds %s of %s authorized seats."
             % (seated, policy["authorized_seats"]))
    director["service_status"] = "SEATED"
    touch(director)
    recompute_compliance(director, policy)
    return emit(director)


@bp.post("/directors/<director_id>/departure-notice")
def departure_notice(director_id):
    require(CORPORATE_SECRETARY)
    b = body()
    notice_type = check_enum("notice_type", required(b, "notice_type", "string"), NOTICE_TYPE)
    effective_on = optional(b, "effective_on", "string")
    if effective_on is not None:
        parse_date(effective_on, "effective_on")
    director = need("director", director_id)
    if director["service_status"] != "SEATED":
        fail("ERR_DIRECTOR_STATE_INVALID",
             "Only a SEATED director may file a departure notice; this one is %s."
             % director["service_status"])
    director["service_status"] = ("RETIREMENT_NOTICED" if notice_type == "RETIREMENT"
                                 else "RESIGNED")
    director["retirement_notice_at"] = clock_instant()
    touch(director)
    end_active_assignments(director, "RETIREMENT_NOTICE")
    if notice_type == "RESIGNATION":
        for award in db.comp_awards.values():
            if award["director_id"] == director["id"] and award["status"] == "DRAFT":
                _apply(award, {"status": "VOIDED"})
    return emit(director)


# ---------------------------------------------------------------- skill ratings
@bp.post("/directors/<director_id>/skill-ratings")
def record_skill_rating(director_id):
    actor = require(GOVERNANCE_STAFF, CORPORATE_SECRETARY, SEATED_DIRECTOR)
    require_director_owner(actor, director_id)
    b = body()
    skill_category_id = required(b, "skill_category_id", "string")
    self_rating = required(b, "self_rating", "integer")
    check_range("self_rating", self_rating, 1, 5)
    need("director", director_id)
    need("skill_category", skill_category_id)
    for row in db.skill_ratings.values():
        if row["director_id"] == director_id and row["skill_category_id"] == skill_category_id:
            fail("ERR_DUPLICATE_RESOURCE",
                 "This director already carries a rating for that skill category.")
    row = new_row({
        "director_id": director_id,
        "skill_category_id": skill_category_id,
        "self_rating": self_rating,
        "validated_rating": None,
        "validation_status": "UNVALIDATED",
        "effective_rating": self_rating,
        "validated_at": None,
    })
    db.skill_ratings[row["id"]] = row
    return emit(row, 201)


@bp.get("/skill-ratings/<rating_id>")
def read_skill_rating(rating_id):
    require(*READ_ALL)
    return emit(need("skill_rating", rating_id))


@bp.get("/skill-ratings")
def list_skill_ratings():
    require(GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER)
    rows = apply_filters(list(db.skill_ratings.values()), {
        "director_id": ("director_id", "str"),
        "skill_category_id": ("skill_category_id", "str"),
        "validation_status": ("validation_status", "str"),
    })
    return emit_list(by_created_at(rows))


@bp.post("/skill-ratings/<rating_id>/validate")
def validate_skill_rating(rating_id):
    require(COMMITTEE_CHAIR)
    b = body()
    validated_rating = required(b, "validated_rating", "integer")
    check_range("validated_rating", validated_rating, 1, 5)
    rating = need("skill_rating", rating_id)
    rating["validated_rating"] = validated_rating
    rating["validation_status"] = "VALIDATED"
    rating["effective_rating"] = validated_rating
    rating["validated_at"] = clock_instant()
    touch(rating)
    return emit(rating)
