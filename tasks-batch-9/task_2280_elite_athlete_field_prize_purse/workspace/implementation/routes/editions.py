"""RaceEdition endpoints (PRD 3.1, 3.4, 3.7, 3.8, 3.9)."""
from flask import Blueprint

from clock import (
    add_days,
    clock,
    date_at_midnight_utc,
    fmt_dt,
    now_iso,
    parse_date,
    parse_dt,
)
from constants import (
    DIVISIONS,
    GENDERS,
    PURSE_CATEGORIES,
)
from db import db, new_record, touch
from errors import err
from middleware import authenticate
from response import list_response, object_response, paginate
from services import awards as awards_service
from services import cascade, gates, lookup, places, serializers, valuation
from validators import (
    enum_filter,
    get_body,
    oint,
    pagination_args,
    rint,
    rstr,
    str_filter,
)

bp = Blueprint("editions", __name__)

ALL_ROLES = (
    "ElitesDirector",
    "FinanceOfficer",
    "TechnicalOfficial",
    "AntiDopingLiaison",
    "SanctioningBody",
    "AthleteAgent",
)


@bp.post("/race-editions")
def create_edition():
    authenticate(("ElitesDirector",))
    body = get_body()
    name = rstr(body, "name")
    city = rstr(body, "city")
    race_date = parse_date(rstr(body, "race_date"), "race_date")
    appearance_budget_cents = rint(body, "appearance_budget_cents", minimum=0)
    total_purse_cents = rint(body, "total_purse_cents", minimum=0)
    bonus_pool_cap_cents = rint(body, "bonus_pool_cap_cents", minimum=0)
    offer_response_days = oint(body, "offer_response_days", 14, 1, 60)
    max_negotiation_rounds = oint(body, "max_negotiation_rounds", 3, 1, 6)
    masters_min_age = oint(body, "masters_min_age", 40, 35, 60)
    edition = new_record(
        name=name,
        city=city,
        race_date=race_date.isoformat(),
        status="PLANNING",
        appearance_budget_cents=appearance_budget_cents,
        total_purse_cents=total_purse_cents,
        bonus_pool_cap_cents=bonus_pool_cap_cents,
        course_record_male_seconds=oint(body, "course_record_male_seconds"),
        course_record_female_seconds=oint(body, "course_record_female_seconds"),
        course_record_wheelchair_male_seconds=oint(
            body, "course_record_wheelchair_male_seconds"
        ),
        course_record_wheelchair_female_seconds=oint(
            body, "course_record_wheelchair_female_seconds"
        ),
        offer_response_days=offer_response_days,
        max_negotiation_rounds=max_negotiation_rounds,
        masters_min_age=masters_min_age,
        expired_offer_count=0,
    )
    db.race_editions[edition["id"]] = edition
    return object_response(serializers.ser_edition(edition), 201)


@bp.get("/race-editions/<edition_id>")
def read_edition(edition_id):
    authenticate(ALL_ROLES)
    edition = lookup.get_edition(edition_id)
    return object_response(serializers.ser_edition(edition))


@bp.post("/race-editions/<edition_id>/open-field")
def open_field(edition_id):
    authenticate(("ElitesDirector",))
    edition = lookup.get_edition(edition_id)
    get_body()
    gates.gate_edition(edition, ("PLANNING",))
    standards = lookup.edition_standards(edition_id)
    overall_lines = [
        line for line in lookup.edition_purse_lines(edition_id)
        if line["category"] == "OVERALL"
    ]
    if not standards or not overall_lines:
        raise err(
            "ERR_EDITION_CONFIG_INCOMPLETE",
            "The edition needs at least one division standard and one OVERALL purse line",
        )
    edition["status"] = "FIELD_OPEN"
    touch(edition)
    return object_response(serializers.ser_edition(edition))


@bp.post("/race-editions/<edition_id>/lock-field")
def lock_field(edition_id):
    authenticate(("ElitesDirector",))
    edition = lookup.get_edition(edition_id)
    get_body()
    gates.gate_edition(edition, ("FIELD_OPEN",))
    invitations = lookup.edition_invitations(edition_id)
    accepted = [inv for inv in invitations if inv["status"] == "ACCEPTED"]
    if not accepted:
        raise err(
            "ERR_INVALID_INVITATION_STATE",
            "The field cannot be locked before an invitation is ACCEPTED",
        )
    exposures = {}
    total_exposure = 0
    for invitation in accepted:
        athlete = lookup.soft_get("athletes", invitation["athlete_id"])
        value = valuation.full_exposure_valuation(edition, invitation, athlete)
        exposures[invitation["id"]] = value
        total_exposure += value
    ceiling = edition["appearance_budget_cents"] + edition["bonus_pool_cap_cents"]
    if total_exposure > ceiling:
        raise err(
            "ERR_FIELD_LOCK_EXPOSURE_EXCEEDED",
            "The summed full exposure of ACCEPTED invitations exceeds the ceiling",
        )
    for invitation in accepted:
        invitation["full_exposure_cents"] = exposures[invitation["id"]]
        touch(invitation)
    for invitation in invitations:
        if invitation["status"] in ("DRAFT", "OFFERED", "COUNTERED"):
            invitation["status"] = "EXPIRED"
            touch(invitation)
            edition["expired_offer_count"] += 1
    edition["status"] = "FIELD_LOCKED"
    touch(edition)
    return object_response(serializers.ser_edition(edition))


@bp.post("/race-editions/<edition_id>/mark-raced")
def mark_raced(edition_id):
    authenticate(("TechnicalOfficial",))
    edition = lookup.get_edition(edition_id)
    get_body()
    gates.gate_edition(edition, ("FIELD_LOCKED",))
    race_start = date_at_midnight_utc(parse_date(edition["race_date"], "race_date"))
    if clock.now() < race_start:
        raise err("ERR_RACE_DATE_NOT_REACHED", "The logical clock has not reached race day")
    edition["status"] = "RACED"
    touch(edition)
    return object_response(serializers.ser_edition(edition))


@bp.post("/race-editions/<edition_id>/certify-results")
def certify_results(edition_id):
    authenticate(("TechnicalOfficial",))
    edition = lookup.get_edition(edition_id)
    get_body()
    gates.gate_edition(edition, ("RACED",))
    results = lookup.edition_results(edition_id)
    certified = [r for r in results if r["certification_status"] == "CERTIFIED"]
    if any(r["certification_status"] == "PROVISIONAL" for r in results) or not certified:
        raise err(
            "ERR_RESULTS_NOT_ALL_ADJUDICATED",
            "Every result must be adjudicated and at least one must be CERTIFIED",
        )
    places.assign_places(edition)
    for result in certified:
        if result["division"] == "SUB_ELITE":
            continue
        gender = places.athlete_gender(result)
        record = valuation.course_record(edition, result["division"], gender)
        beats = record is None or result["official_seconds"] < record
        if beats and result["record_claim_status"] == "NONE":
            result["record_claim_status"] = "CLAIMED"
            touch(result)
    edition["status"] = "RESULTS_CERTIFIED"
    touch(edition)
    return object_response(serializers.ser_edition(edition))


@bp.post("/race-editions/<edition_id>/compute-awards")
def compute_awards(edition_id):
    authenticate(("FinanceOfficer",))
    edition = lookup.get_edition(edition_id)
    body = get_body()
    expected = rint(body, "expected_race_edition_version")
    gates.gate_edition(edition, ("RESULTS_CERTIFIED",))
    if expected != edition["version"]:
        raise err(
            "ERR_STALE_EDITION_VERSION",
            "expected_race_edition_version does not match the edition version",
        )
    awards_service.compute_awards(edition)
    touch(edition)
    return object_response(serializers.ser_edition(edition))


@bp.post("/race-editions/<edition_id>/settle-purse")
def settle_purse(edition_id):
    authenticate(("FinanceOfficer",))
    edition = lookup.get_edition(edition_id)
    get_body()
    gates.gate_edition(edition, ("RESULTS_CERTIFIED",))
    for award in lookup.edition_awards(edition_id):
        if award["status"] not in ("PAID", "VOID", "CLAWBACK_PENDING"):
            raise err(
                "ERR_AWARDS_NOT_ALL_SETTLED",
                "Every prize award must be PAID, VOID or CLAWBACK_PENDING",
            )
    for result in lookup.edition_results(edition_id):
        if result["record_claim_status"] == "SUBMITTED":
            raise err(
                "ERR_INVALID_RECORD_CLAIM_STATE",
                "A record claim of this edition is still SUBMITTED",
            )
    edition["status"] = "PURSE_SETTLED"
    touch(edition)
    return object_response(serializers.ser_edition(edition))


@bp.post("/race-editions/<edition_id>/run-ops")
def run_ops(edition_id):
    authenticate(("ElitesDirector",))
    edition = lookup.get_edition(edition_id)
    get_body()
    gates.gate_edition(edition)
    now = clock.now()

    # Step 1 — expire overdue offers.
    for invitation in lookup.edition_invitations(edition_id):
        if invitation["status"] not in ("OFFERED", "COUNTERED"):
            continue
        deadline = invitation.get("response_deadline_at")
        if deadline is None:
            continue
        if parse_dt(deadline) < now:
            invitation["status"] = "EXPIRED"
            touch(invitation)
            edition["expired_offer_count"] += 1

    # Step 2 — record missed tests.
    for test in lookup.edition_doping_tests(edition_id):
        if test["status"] != "SCHEDULED":
            continue
        if parse_dt(test["window_end_at"]) < now:
            test["status"] = "MISSED"
            touch(test)
            athlete = lookup.soft_get("athletes", test["athlete_id"])
            if athlete is not None:
                athlete["missed_test_count"] += 1
                touch(athlete)

    # Step 3 — recompute the ledger projections (derived at read time) and
    # increment the edition version once for the checkpoint.
    touch(edition)
    return object_response(serializers.ser_edition(edition))


@bp.get("/race-editions/<edition_id>/purse-lines")
def list_purse_lines(edition_id):
    authenticate(("ElitesDirector", "FinanceOfficer", "TechnicalOfficial"))
    lookup.get_edition(edition_id)
    limit, offset = pagination_args()
    category = enum_filter("category", PURSE_CATEGORIES)
    gender = enum_filter("gender", GENDERS)
    rows = lookup.edition_purse_lines(edition_id)
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if gender is not None:
        rows = [r for r in rows if r["gender"] == gender]
    window, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.ser_purse_line(r) for r in window], limit, offset, total
    )


@bp.get("/race-editions/<edition_id>/division-standards")
def list_division_standards(edition_id):
    authenticate(("ElitesDirector", "FinanceOfficer", "TechnicalOfficial", "AthleteAgent"))
    lookup.get_edition(edition_id)
    limit, offset = pagination_args()
    division = enum_filter("division", DIVISIONS)
    gender = enum_filter("gender", GENDERS)
    rows = lookup.edition_standards(edition_id)
    if division is not None:
        rows = [r for r in rows if r["division"] == division]
    if gender is not None:
        rows = [r for r in rows if r["gender"] == gender]
    window, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.ser_standard(r) for r in window], limit, offset, total
    )


@bp.get("/race-editions/<edition_id>/pacer-assignments")
def list_pacer_assignments(edition_id):
    authenticate(("ElitesDirector", "TechnicalOfficial"))
    lookup.get_edition(edition_id)
    limit, offset = pagination_args()
    license_code = str_filter("pacer_license_code")
    rows = lookup.rows("pacer_assignments", race_edition_id=edition_id)
    if license_code is not None:
        rows = [r for r in rows if r["pacer_license_code"] == license_code]
    window, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.ser_pacer(r) for r in window], limit, offset, total
    )
