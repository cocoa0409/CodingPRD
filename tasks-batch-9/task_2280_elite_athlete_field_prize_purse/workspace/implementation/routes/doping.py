"""Anti-doping coordination (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint

from clock import clock, fmt_dt, now_iso, parse_dt
from constants import (
    DOPING_TEST_STATUSES,
    FREQUENCY_WINDOW_DAYS,
    MAX_TESTS_PER_WINDOW,
    TEST_TYPES,
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
    rstr,
    str_filter,
)

bp = Blueprint("doping", __name__)

READ_ROLES = (
    "AntiDopingLiaison",
    "SanctioningBody",
    "FinanceOfficer",
    "TechnicalOfficial",
    "ElitesDirector",
)


@bp.post("/doping-tests")
def create_doping_test():
    authenticate(("AntiDopingLiaison",))
    body = get_body()
    athlete_id = rstr(body, "athlete_id")
    edition_id = rstr(body, "race_edition_id")
    athlete = lookup.get_athlete(athlete_id)
    edition = lookup.get_edition(edition_id)

    test_type = renum(body, "test_type", TEST_TYPES)
    window_start = parse_dt(rstr(body, "window_start_at"), "window_start_at")
    window_end = parse_dt(rstr(body, "window_end_at"), "window_end_at")
    if window_end <= window_start:
        raise invalid("window_end_at must be strictly later than window_start_at")
    sample_code = rstr(body, "sample_code")

    gates.gate_edition(edition)

    peers = lookup.rows("doping_tests", athlete_id=athlete_id)

    # Overlap of closed windows against open tests only; touching counts.
    for peer in peers:
        if peer["status"] not in ("SCHEDULED", "COLLECTED"):
            continue
        peer_start = parse_dt(peer["window_start_at"])
        peer_end = parse_dt(peer["window_end_at"])
        if window_start <= peer_end and peer_start <= window_end:
            raise err(
                "ERR_TESTING_WINDOW_OVERLAP",
                "The requested window overlaps an open testing window",
            )

    # Frequency cap over every status, +/- seven days around the requested start.
    span = timedelta(days=FREQUENCY_WINDOW_DAYS)
    nearby = 0
    for peer in peers:
        peer_start = parse_dt(peer["window_start_at"])
        if abs(peer_start - window_start) <= span:
            nearby += 1
    if nearby >= MAX_TESTS_PER_WINDOW:
        raise err(
            "ERR_TESTING_FREQUENCY_EXCEEDED",
            "The athlete has already reached the testing frequency cap",
        )

    for existing in db.doping_tests.values():
        if existing["sample_code"] == sample_code:
            raise err("ERR_CONFIG_DUPLICATE", "sample_code is already in use")

    test = new_record(
        athlete_id=athlete_id,
        race_edition_id=edition_id,
        test_type=test_type,
        window_start_at=fmt_dt(window_start),
        window_end_at=fmt_dt(window_end),
        sample_code=sample_code,
        status="SCHEDULED",
        collected_at=None,
        collected_sample_ref=None,
        outcome_notes=None,
    )
    db.doping_tests[test["id"]] = test
    return object_response(serializers.ser_doping_test(test), 201)


@bp.get("/doping-tests/<test_id>")
def read_doping_test(test_id):
    authenticate(READ_ROLES)
    test = lookup.get_doping_test(test_id)
    return object_response(serializers.ser_doping_test(test))


@bp.get("/doping-tests")
def list_doping_tests():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = {}
    for name in ("athlete_id", "race_edition_id"):
        value = str_filter(name)
        if value is not None:
            filters[name] = value
    test_type = enum_filter("test_type", TEST_TYPES)
    status = enum_filter("status", DOPING_TEST_STATUSES)
    if test_type is not None:
        filters["test_type"] = test_type
    if status is not None:
        filters["status"] = status
    rows = lookup.rows("doping_tests", **filters)
    window, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.ser_doping_test(r) for r in window], limit, offset, total
    )


@bp.post("/doping-tests/<test_id>/collect")
def collect_sample(test_id):
    authenticate(("AntiDopingLiaison",))
    test = lookup.get_doping_test(test_id)
    body = get_body()
    collected_sample_ref = rstr(body, "collected_sample_ref")

    edition = lookup.soft_get("race_editions", test["race_edition_id"])
    if edition is not None:
        gates.gate_edition(edition)

    if test["status"] != "SCHEDULED":
        raise err(
            "ERR_INVALID_DOPING_TEST_STATE",
            "Only a SCHEDULED test may be collected",
        )

    now = clock.now()
    if now < parse_dt(test["window_start_at"]) or now > parse_dt(test["window_end_at"]):
        raise err(
            "ERR_COLLECTION_WINDOW_INVALID",
            "The logical clock is outside the declared availability window",
        )

    test["status"] = "COLLECTED"
    test["collected_sample_ref"] = collected_sample_ref
    test["collected_at"] = now_iso()
    touch(test)
    return object_response(serializers.ser_doping_test(test))


@bp.post("/doping-tests/<test_id>/adjudicate")
def adjudicate(test_id):
    authenticate(("SanctioningBody",))
    test = lookup.get_doping_test(test_id)
    body = get_body()
    outcome = renum(body, "outcome", ("CLEARED", "ADVERSE"))
    outcome_notes = ostr(body, "outcome_notes")

    edition = lookup.soft_get("race_editions", test["race_edition_id"])
    if edition is not None:
        gates.gate_edition(edition)

    if test["status"] != "COLLECTED":
        raise err(
            "ERR_INVALID_DOPING_TEST_STATE",
            "Only a COLLECTED test may be adjudicated",
        )

    test["status"] = outcome
    test["outcome_notes"] = outcome_notes
    touch(test)

    if outcome == "ADVERSE":
        edition_changed = cascade.adverse_test_cascade(test)
        if edition_changed and edition is not None:
            touch(edition)
    return object_response(serializers.ser_doping_test(test))
