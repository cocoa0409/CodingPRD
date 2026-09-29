"""Tuning interval ingest, the processing run lifecycle and weight rows."""
from datetime import timedelta

from flask import Blueprint, g

from auth import (ALL_ROLES, CONFIDENTIAL_READ_ROLES, METHODOLOGY_STATISTICIAN,
                  roles)
from calculations import (METHODOLOGY_FOR_METER_TYPE, SOURCE_METHODOLOGIES,
                          WEIGHT_VARIANTS)
from common import check_expected_version, must
from errors import ApiError
from response import apply_filters, created, listing, ok
from services import (cell_denominator, data_households, detect_faults,
                      edit_pass, refresh_rolling_compliance,
                      release_run_artifacts, weight_pass)
from store import created_key, db
from util import (D, bad_request, format_iso, get_body, minutes_between,
                  require_fields, want_enum, want_int, want_iso, want_str)

bp = Blueprint("runs", __name__)

INTERVAL_LIVE_STATES = ("RAW", "EDITED", "ASCRIBED")


# ------------------------------------------------------------ tuning intervals
@bp.post("/tuning-intervals")
@roles(METHODOLOGY_STATISTICIAN)
def ingest_interval():
    body = get_body()
    meter = None
    if body.get("meter_id") is not None:
        meter = must("meters", body["meter_id"])
    if body.get("household_id") is not None:
        must("households", body["household_id"])
    require_fields(body, ["meter_id", "source_methodology", "start_iso",
                          "end_iso", "station_code", "tuning_minutes"])
    methodology = want_enum(body, "source_methodology", SOURCE_METHODOLOGIES)
    start_dt = want_iso(body, "start_iso")
    end_dt = want_iso(body, "end_iso")
    want_str(body, "station_code", min_len=1, max_len=24)
    if body.get("household_id") is not None:
        if body["household_id"] != meter["household_id"]:
            raise bad_request("household_id must match the meter's household")
    tuning_minutes = want_int(body, "tuning_minutes", minimum=0)
    if start_dt < end_dt:
        wall_minutes = minutes_between(start_dt, end_dt)
        if tuning_minutes > wall_minutes:
            raise bad_request("tuning_minutes exceeds the block's wall length")
    if not start_dt < end_dt:
        raise ApiError("ERR_INVALID_WINDOW",
                       "start_iso must be strictly before end_iso")
    if meter["install_status"] != "INSTALLED":
        raise ApiError("ERR_METER_NOT_INSTALLED",
                       "only an INSTALLED device reports data")
    if METHODOLOGY_FOR_METER_TYPE[meter["meter_type"]] != methodology:
        raise ApiError("ERR_METHODOLOGY_METER_MISMATCH",
                       "source_methodology does not match the meter_type")
    start_iso = format_iso(start_dt)
    end_iso = format_iso(end_dt)
    for row in db.where("tuning_intervals", meter_id=meter["id"]):
        if row["state"] not in INTERVAL_LIVE_STATES:
            continue
        if start_iso < row["end_iso"] and row["start_iso"] < end_iso:
            raise ApiError("ERR_INTERVAL_OVERLAP",
                           "the block overlaps an existing interval")
    if end_dt > db.clock:
        raise ApiError("ERR_INTERVAL_IN_FUTURE",
                       "end_iso must be at or before the logical clock")
    interval = db.insert("tuning_intervals", {
        "meter_id": meter["id"],
        "household_id": meter["household_id"],
        "processing_run_id": None,
        "source_methodology": methodology,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "station_code": body["station_code"],
        "tuning_minutes": tuning_minutes,
        "usable_minutes": 0,
        "state": "RAW",
        "invalidation_reason": None,
        "ascribed": False,
    })
    household = db.get("households", meter["household_id"])
    if household is not None:
        refresh_rolling_compliance(household)
    return created(interval)


@bp.get("/tuning-intervals/<tuning_interval_id>")
@roles(*CONFIDENTIAL_READ_ROLES)
def read_interval(tuning_interval_id):
    return ok(must("tuning_intervals", tuning_interval_id))


@bp.get("/tuning-intervals")
@roles(*CONFIDENTIAL_READ_ROLES)
def list_intervals():
    rows = apply_filters(db.all("tuning_intervals"), {
        "meter_id": ("meter_id", "str"),
        "household_id": ("household_id", "str"),
        "processing_run_id": ("processing_run_id", "str"),
        "state": ("state", "str"),
        "source_methodology": ("source_methodology", "str"),
        "ascribed": ("ascribed", "bool"),
    })
    return listing("tuning_intervals", rows)


# ------------------------------------------------------------- processing runs
@bp.post("/processing-runs")
@roles(METHODOLOGY_STATISTICIAN)
def open_run():
    body = get_body()
    market = universe = rule_set = None
    if body.get("market_id") is not None:
        market = must("markets", body["market_id"])
    if body.get("universe_estimate_id") is not None:
        universe = must("universe_estimates", body["universe_estimate_id"])
    if body.get("edit_rule_set_id") is not None:
        rule_set = must("edit_rule_sets", body["edit_rule_set_id"])
    require_fields(body, ["market_id", "universe_estimate_id",
                          "edit_rule_set_id", "window_start_iso",
                          "window_end_iso", "expected_market_version"])
    start_dt = want_iso(body, "window_start_iso")
    end_dt = want_iso(body, "window_end_iso")
    check_expected_version(body, "expected_market_version", market,
                           "ERR_STALE_MARKET_VERSION")
    if not start_dt < end_dt:
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_start_iso must be strictly before window_end_iso")
    if universe["market_id"] != market["id"]:
        raise ApiError("ERR_UNIVERSE_MARKET_MISMATCH",
                       "the universe estimate belongs to another market")
    if universe["status"] != "PUBLISHED":
        raise ApiError("ERR_UNIVERSE_NOT_PUBLISHED",
                       "a draft universe is not a projection basis")
    if rule_set["status"] != "PUBLISHED":
        raise ApiError("ERR_RULE_SET_NOT_PUBLISHED",
                       "the edit rule set must be PUBLISHED")
    start_iso = format_iso(start_dt)
    end_iso = format_iso(end_dt)
    if start_iso < universe["effective_from"] or end_iso > universe["effective_to"]:
        raise ApiError("ERR_RUN_WINDOW_OUTSIDE_UNIVERSE",
                       "the window lies outside the vintage's effectivity")
    identical = []
    for other in db.where("processing_runs", market_id=market["id"]):
        if other["state"] == "SUPERSEDED":
            continue
        same_window = (other["window_start_iso"] == start_iso
                       and other["window_end_iso"] == end_iso)
        overlaps = (start_iso < other["window_end_iso"]
                    and other["window_start_iso"] < end_iso)
        if same_window:
            if other["state"] == "PUBLISHED":
                raise ApiError("ERR_RUN_WINDOW_OVERLAP",
                               "published output is never quietly displaced")
            identical.append(other)
        elif overlaps:
            raise ApiError("ERR_RUN_WINDOW_OVERLAP",
                           "the window partially overlaps another run")
    if end_dt > db.clock:
        raise ApiError("ERR_INVALID_WINDOW",
                       "a run cannot process a period that has not finished")
    intab = len([h for h in db.where("households", market_id=market["id"])
                 if h["status"] == "ACTIVE"])
    run = db.insert("processing_runs", {
        "market_id": market["id"],
        "universe_estimate_id": universe["id"],
        "edit_rule_set_id": rule_set["id"],
        "window_start_iso": start_iso,
        "window_end_iso": end_iso,
        "window_minutes": minutes_between(start_dt, end_dt),
        "state": "OPEN",
        "weight_variant": None,
        "intab_snapshot_count": intab,
        "contributing_household_count": 0,
        "ascribed_interval_count": 0,
        "invalidated_interval_count": 0,
        "outlier_household_count": 0,
        "excluded_cell_count": 0,
        "total_weight_mass": D("0.0000"),
        "projected_average_audience": None,
        "limitation_disclosures": [],
        "opened_by_user_id": g.user_id,
        "published_at": None,
        "published_by_user_id": None,
        "repin_required_reason": None,
        "superseded_by_run_id": None,
    })
    for older in sorted(identical, key=created_key):
        older["state"] = "SUPERSEDED"
        older["superseded_by_run_id"] = run["id"]
        release_run_artifacts(older)
        db.touch(older)
    db.touch(market)
    return created(run)


@bp.post("/processing-runs/<processing_run_id>/detect-faults")
@roles(METHODOLOGY_STATISTICIAN)
def run_detect_faults(processing_run_id):
    run = must("processing_runs", processing_run_id)
    if run["state"] != "OPEN":
        raise ApiError("ERR_RUN_NOT_OPEN", "the run must be OPEN to scan")
    rule_set = db.get("edit_rule_sets", run["edit_rule_set_id"])
    detect_faults(run, rule_set)
    return ok(run)


@bp.post("/processing-runs/<processing_run_id>/edit")
@roles(METHODOLOGY_STATISTICIAN)
def run_edit(processing_run_id):
    run = must("processing_runs", processing_run_id)
    if run["state"] != "OPEN":
        raise ApiError("ERR_RUN_NOT_OPEN", "the edit pass requires an OPEN run")
    rule_set = db.get("edit_rule_sets", run["edit_rule_set_id"])
    if rule_set is None or rule_set["status"] != "PUBLISHED":
        raise ApiError("ERR_RULE_SET_NOT_PUBLISHED",
                       "the pinned rule set must still be PUBLISHED")
    edit_pass(run, rule_set)
    db.touch(run)
    return ok(run)


@bp.post("/processing-runs/<processing_run_id>/weight")
@roles(METHODOLOGY_STATISTICIAN)
def run_weight(processing_run_id):
    run = must("processing_runs", processing_run_id)
    body = get_body()
    require_fields(body, ["weight_variant"])
    variant = want_enum(body, "weight_variant", WEIGHT_VARIANTS)
    if not (run["state"] == "EDITED"
            or (run["state"] == "WEIGHTED" and run["weight_variant"] != variant)):
        raise ApiError("ERR_RUN_NOT_EDITED",
                       "the run must be EDITED, or WEIGHTED under the other variant")
    if run["contributing_household_count"] < 1:
        raise ApiError("ERR_NO_CONTRIBUTING_HOUSEHOLDS",
                       "a window with no contributors cannot be projected")
    households = data_households(run)
    contributor_ids = set(h["id"] for h in households)
    if variant == "DESIGN":
        for household in households:
            if cell_denominator(household["quota_cell_id"], "DESIGN",
                                contributor_ids) == 0:
                raise ApiError("ERR_DESIGN_DENOMINATOR_EMPTY",
                               "a contributing cell holds no non-retired household")
    universe = db.get("universe_estimates", run["universe_estimate_id"])
    if universe is None or universe["status"] != "PUBLISHED":
        raise ApiError("ERR_UNIVERSE_NOT_PUBLISHED",
                       "the pinned universe vintage must still be PUBLISHED")
    if (run["window_start_iso"] < universe["effective_from"]
            or run["window_end_iso"] > universe["effective_to"]):
        raise ApiError("ERR_RUN_WINDOW_OUTSIDE_UNIVERSE",
                       "the pinned vintage no longer covers the run window")
    rule_set = db.get("edit_rule_sets", run["edit_rule_set_id"])
    weight_pass(run, rule_set, universe, variant)
    db.touch(run)
    return ok(run)


@bp.post("/processing-runs/<processing_run_id>/publish")
@roles(METHODOLOGY_STATISTICIAN)
def run_publish(processing_run_id):
    run = must("processing_runs", processing_run_id)
    market = db.get("markets", run["market_id"])
    if market is not None and market["recruitment_posture"] == "FROZEN":
        raise ApiError("ERR_MARKET_FROZEN",
                       "an open accreditation audit stops publication")
    if run["state"] != "WEIGHTED":
        raise ApiError("ERR_RUN_NOT_WEIGHTED",
                       "there is no route to publication that skips weighting")
    if market is not None and market["publication_blocked"]:
        raise ApiError("ERR_PUBLICATION_BLOCKED",
                       "a denied accreditation outcome bars publication")
    if g.user_id == run["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the statistician who opened a run may not publish it")
    universe = db.get("universe_estimates", run["universe_estimate_id"])
    if universe is None or universe["status"] != "PUBLISHED":
        raise ApiError("ERR_UNIVERSE_NOT_PUBLISHED",
                       "the pinned universe vintage must still be PUBLISHED")
    run["state"] = "PUBLISHED"
    run["published_at"] = db.now_iso()
    run["published_by_user_id"] = g.user_id
    if market is not None:
        run["limitation_disclosures"] = (list(run["limitation_disclosures"])
                                         + list(market["limitation_disclosures"]))
    db.touch(run)
    pending = [d for d in db.all("client_deliverables")
               if d["processing_run_id"] == run["id"] and d["state"] == "SCHEDULED"]

    def client_order(row):
        client = db.get("clients", row["client_id"])
        return (client["created_at"], client["_seq"]) if client else ("", 0)

    for row in sorted(pending, key=client_order):
        client = db.get("clients", row["client_id"])
        if client is None:
            continue
        row["due_at"] = format_iso(db.clock
                                   + timedelta(hours=client["delivery_sla_hours"]))
        db.touch(row)
    return ok(run)


@bp.post("/processing-runs/<processing_run_id>/repin")
@roles(METHODOLOGY_STATISTICIAN)
def run_repin(processing_run_id):
    run = must("processing_runs", processing_run_id)
    body = get_body()
    universe = rule_set = None
    if body.get("universe_estimate_id") is not None:
        universe = must("universe_estimates", body["universe_estimate_id"])
    if body.get("edit_rule_set_id") is not None:
        rule_set = must("edit_rule_sets", body["edit_rule_set_id"])
    if run["state"] != "PENDING_REPIN":
        raise ApiError("ERR_RUN_NOT_PENDING_REPIN",
                       "only a PENDING_REPIN run is re-pinned")
    if rule_set is not None and rule_set["status"] != "PUBLISHED":
        raise ApiError("ERR_RULE_SET_NOT_PUBLISHED",
                       "the new rule set must be PUBLISHED")
    if universe is not None:
        if universe["status"] != "PUBLISHED":
            raise ApiError("ERR_UNIVERSE_NOT_PUBLISHED",
                           "the new universe vintage must be PUBLISHED")
        if (run["window_start_iso"] < universe["effective_from"]
                or run["window_end_iso"] > universe["effective_to"]):
            raise ApiError("ERR_RUN_WINDOW_OUTSIDE_UNIVERSE",
                           "the new vintage does not cover the run window")
    release_run_artifacts(run)
    if universe is not None:
        run["universe_estimate_id"] = universe["id"]
    if rule_set is not None:
        run["edit_rule_set_id"] = rule_set["id"]
    run["state"] = "OPEN"
    run["repin_required_reason"] = None
    run["invalidated_interval_count"] = 0
    run["ascribed_interval_count"] = 0
    run["outlier_household_count"] = 0
    run["contributing_household_count"] = 0
    run["excluded_cell_count"] = 0
    run["limitation_disclosures"] = []
    run["total_weight_mass"] = D("0.0000")
    run["projected_average_audience"] = None
    run["weight_variant"] = None
    db.touch(run)
    return ok(run)


@bp.get("/processing-runs/<processing_run_id>")
@roles(*ALL_ROLES)
def read_run(processing_run_id):
    return ok(must("processing_runs", processing_run_id))


@bp.get("/processing-runs")
@roles(*ALL_ROLES)
def list_runs():
    rows = apply_filters(db.all("processing_runs"), {
        "market_id": ("market_id", "str"),
        "universe_estimate_id": ("universe_estimate_id", "str"),
        "edit_rule_set_id": ("edit_rule_set_id", "str"),
        "state": ("state", "str"),
        "weight_variant": ("weight_variant", "str"),
    })
    return listing("processing_runs", rows)


# ----------------------------------------------------------- household weights
@bp.get("/household-weights/<household_weight_id>")
@roles(*CONFIDENTIAL_READ_ROLES)
def read_weight(household_weight_id):
    return ok(must("household_weights", household_weight_id))


@bp.get("/household-weights")
@roles(*CONFIDENTIAL_READ_ROLES)
def list_weights():
    rows = apply_filters(db.all("household_weights"), {
        "processing_run_id": ("processing_run_id", "str"),
        "household_id": ("household_id", "str"),
        "weight_variant": ("weight_variant", "str"),
        "capped": ("capped", "bool"),
    })
    return listing("household_weights", rows)
