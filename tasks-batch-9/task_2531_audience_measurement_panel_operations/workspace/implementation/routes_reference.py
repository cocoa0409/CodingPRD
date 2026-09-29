"""Universe estimates and editing rule sets: the two version-pinned parents."""
from flask import Blueprint

from auth import ALL_ROLES, METHODOLOGY_STATISTICIAN, roles
from common import check_expected_version, must
from errors import ApiError
from response import apply_filters, created, listing, ok
from services import repin_runs
from store import db
from util import (D, bad_request, format_iso, get_body, require_fields,
                  round_half_up, want_int, want_iso, want_number, want_pattern,
                  want_str, whole_days_between)

bp = Blueprint("reference", __name__)


def _parse_cell_populations(body, market):
    if "cell_populations" not in body or body["cell_populations"] is None:
        raise bad_request("cell_populations is required")
    raw = body["cell_populations"]
    if not isinstance(raw, list):
        raise bad_request("cell_populations must be an array")
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            raise bad_request("cell_populations entries must be objects")
        cell_id = item.get("quota_cell_id")
        if not isinstance(cell_id, str) or not cell_id:
            raise bad_request("cell_populations entries need a quota_cell_id")
        households = item.get("population_households")
        persons = item.get("population_persons")
        if isinstance(households, bool) or not isinstance(households, int):
            raise bad_request("population_households must be an integer")
        if households < 1:
            raise bad_request("population_households must be at least 1")
        if isinstance(persons, bool) or not isinstance(persons, int):
            raise bad_request("population_persons must be an integer")
        if persons < 0:
            raise bad_request("population_persons must be at least 0")
        entries.append({"quota_cell_id": cell_id,
                        "population_households": households,
                        "population_persons": persons})
    return entries


def _check_cell_coverage(entries, market):
    market_cells = set(c["id"] for c in db.where("quota_cells",
                                                 market_id=market["id"]))
    named = [entry["quota_cell_id"] for entry in entries]
    if len(set(named)) != len(named) or set(named) != market_cells:
        raise ApiError("ERR_UNIVERSE_CELL_COVERAGE",
                       "cell_populations must name every quota cell of the "
                       "market exactly once")


@bp.post("/universe-estimates")
@roles(METHODOLOGY_STATISTICIAN)
def draft_universe_estimate():
    body = get_body()
    market = None
    if body.get("market_id") is not None:
        market = must("markets", body["market_id"])
    require_fields(body, ["market_id", "vintage_label", "effective_from",
                          "effective_to", "cell_populations",
                          "expected_market_version"])
    label = want_pattern(body, "vintage_label", r"^\d{4}Q[1-4]$", max_len=6)
    effective_from = want_iso(body, "effective_from")
    effective_to = want_iso(body, "effective_to")
    entries = _parse_cell_populations(body, market)
    check_expected_version(body, "expected_market_version", market,
                           "ERR_STALE_MARKET_VERSION")
    _check_cell_coverage(entries, market)
    if not effective_from < effective_to:
        raise ApiError("ERR_INVALID_WINDOW",
                       "effective_from must be strictly before effective_to")
    for existing in db.where("universe_estimates", market_id=market["id"]):
        if existing["vintage_label"] == label:
            raise ApiError("ERR_UNIVERSE_VINTAGE_DUPLICATE",
                           "this vintage_label already exists for the market")
    estimate = db.insert("universe_estimates", {
        "market_id": market["id"],
        "vintage_label": label,
        "effective_from": format_iso(effective_from),
        "effective_to": format_iso(effective_to),
        "cell_populations": entries,
        "total_population_households": sum(e["population_households"]
                                           for e in entries),
        "total_population_persons": sum(e["population_persons"]
                                        for e in entries),
        "status": "DRAFT",
        "published_at": None,
        "superseded_at": None,
    })
    db.touch(market)
    return created(estimate)


@bp.post("/universe-estimates/<universe_estimate_id>/publish")
@roles(METHODOLOGY_STATISTICIAN)
def publish_universe_estimate(universe_estimate_id):
    estimate = must("universe_estimates", universe_estimate_id)
    if estimate["status"] != "DRAFT":
        raise ApiError("ERR_UNIVERSE_NOT_DRAFT", "only a DRAFT may be published")
    current = [e for e in db.where("universe_estimates",
                                   market_id=estimate["market_id"])
               if e["status"] == "PUBLISHED" and e["published_at"]]
    for published in current:
        if whole_days_between(published["published_at"], db.now_iso()) < 28:
            raise ApiError("ERR_UNIVERSE_VINTAGE_TOO_SOON",
                           "28 whole days must elapse between vintages")
    market_cells = set(c["id"] for c in db.where("quota_cells",
                                                 market_id=estimate["market_id"]))
    for entry in estimate["cell_populations"]:
        if entry["quota_cell_id"] not in market_cells:
            raise ApiError("ERR_UNIVERSE_CELL_COVERAGE",
                           "a cell_populations entry no longer resolves")
    estimate["status"] = "PUBLISHED"
    estimate["published_at"] = db.now_iso()
    db.touch(estimate)
    superseded = []
    for other in db.where("universe_estimates", market_id=estimate["market_id"]):
        if other["id"] == estimate["id"] or other["status"] != "PUBLISHED":
            continue
        if other["effective_from"] < estimate["effective_from"]:
            other["status"] = "SUPERSEDED"
            other["superseded_at"] = db.now_iso()
            db.touch(other)
            superseded.append(other["id"])
    if superseded:
        runs = [r for r in db.where("processing_runs",
                                    market_id=estimate["market_id"])
                if r["universe_estimate_id"] in superseded
                and r["state"] in ("OPEN", "EDITED", "WEIGHTED")]
        repin_runs(runs, "UNIVERSE_SUPERSEDED")
    return ok(estimate)


@bp.get("/universe-estimates/<universe_estimate_id>")
@roles(*ALL_ROLES)
def read_universe_estimate(universe_estimate_id):
    return ok(must("universe_estimates", universe_estimate_id))


@bp.get("/universe-estimates")
@roles(*ALL_ROLES)
def list_universe_estimates():
    rows = apply_filters(db.all("universe_estimates"), {
        "market_id": ("market_id", "str"),
        "status": ("status", "str"),
    })
    return listing("universe_estimates", rows)


# ------------------------------------------------------------- rule sets
@bp.post("/edit-rule-sets")
@roles(METHODOLOGY_STATISTICIAN)
def draft_edit_rule_set():
    body = get_body()
    require_fields(body, ["label", "missing_interval_ascription_minutes",
                          "invalid_tuning_max_minutes",
                          "outlier_household_minutes_cap",
                          "outlier_weight_ratio_cap",
                          "fault_missing_minutes_threshold"])
    label = want_str(body, "label", min_len=1, max_len=60)
    ascription = want_int(body, "missing_interval_ascription_minutes",
                          minimum=0, maximum=240)
    invalid_max = want_int(body, "invalid_tuning_max_minutes", minimum=1)
    outlier_cap = want_int(body, "outlier_household_minutes_cap", minimum=1)
    ratio_cap = want_number(body, "outlier_weight_ratio_cap", minimum=1)
    fault_threshold = want_int(body, "fault_missing_minutes_threshold", minimum=1)
    for existing in db.all("edit_rule_sets"):
        if existing["label"] == label:
            raise ApiError("ERR_INVALID_REQUEST", "label already exists")
    rule_set = db.insert("edit_rule_sets", {
        "label": label,
        "missing_interval_ascription_minutes": ascription,
        "invalid_tuning_max_minutes": invalid_max,
        "outlier_household_minutes_cap": outlier_cap,
        "outlier_weight_ratio_cap": round_half_up(ratio_cap, 4),
        "fault_missing_minutes_threshold": fault_threshold,
        "status": "DRAFT",
        "published_at": None,
    })
    return created(rule_set)


@bp.post("/edit-rule-sets/<edit_rule_set_id>/publish")
@roles(METHODOLOGY_STATISTICIAN)
def publish_edit_rule_set(edit_rule_set_id):
    rule_set = must("edit_rule_sets", edit_rule_set_id)
    if rule_set["status"] != "DRAFT":
        raise ApiError("ERR_RULE_SET_NOT_DRAFT", "only a DRAFT may be published")
    rule_set["status"] = "PUBLISHED"
    rule_set["published_at"] = db.now_iso()
    db.touch(rule_set)
    superseded = []
    for other in db.all("edit_rule_sets"):
        if other["id"] == rule_set["id"] or other["status"] != "PUBLISHED":
            continue
        other["status"] = "SUPERSEDED"
        db.touch(other)
        superseded.append(other["id"])
    if superseded:
        runs = [r for r in db.all("processing_runs")
                if r["edit_rule_set_id"] in superseded
                and r["state"] in ("OPEN", "EDITED", "WEIGHTED")]
        repin_runs(runs, "RULE_SET_SUPERSEDED")
    return ok(rule_set)


@bp.get("/edit-rule-sets/<edit_rule_set_id>")
@roles(*ALL_ROLES)
def read_edit_rule_set(edit_rule_set_id):
    return ok(must("edit_rule_sets", edit_rule_set_id))


@bp.get("/edit-rule-sets")
@roles(*ALL_ROLES)
def list_edit_rule_sets():
    rows = apply_filters(db.all("edit_rule_sets"), {
        "status": ("status", "str"),
    })
    return listing("edit_rule_sets", rows)
