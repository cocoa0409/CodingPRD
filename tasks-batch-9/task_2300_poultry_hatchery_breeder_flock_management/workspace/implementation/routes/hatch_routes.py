"""Hatcher loads, the three pull branches and chick processing (PRD §3.6, §3.7)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import serializers
import services
from errors import fail
from helpers import (apply_filters, authorize, body, must_get, need_int, need_str,
                     ok, ok_list, pagination, paginate)
from store import store

bp = Blueprint("hatch", __name__)

HATCHER_READ_ROLES = ("HatcheryManager", "IncubationOperator", "ChickProcessor")
BATCH_READ_ROLES = ("HatcheryManager", "ChickProcessor", "Veterinarian")
PULLED_STATES = ("EARLY_PULLED", "WINDOW_PULLED", "LATE_PULLED")


def _primary_flock(setter_load_id):
    """Flock contributing the most eggs, ties broken by earliest draw created_at."""
    totals = {}
    first_seen = {}
    for item in services.items_of_load(setter_load_id, active_only=True):
        lot = store.egg_lots.get(item["egg_lot_id"])
        if lot is None:
            continue
        flock_id = lot["flock_id"]
        totals[flock_id] = totals.get(flock_id, 0) + item["eggs_taken"]
        if flock_id not in first_seen:
            first_seen[flock_id] = (item["created_at"], item["_seq"])
    if not totals:
        return None
    best = sorted(totals.items(),
                  key=lambda kv: (-kv[1], first_seen[kv[0]][0], first_seen[kv[0]][1]))
    return store.breeder_flocks.get(best[0][0])


# ---------------------------------------------------------------------------
# Hatcher loads
# ---------------------------------------------------------------------------
@bp.get("/hatcher-loads/<rid>")
def get_hatcher_load(rid):
    authorize(HATCHER_READ_ROLES)
    return ok(serializers.hatcher_load(must_get("hatcher_loads", rid)))


@bp.get("/hatcher-loads")
def list_hatcher_loads():
    authorize(HATCHER_READ_ROLES)
    limit, offset = pagination()
    rows = apply_filters(store.sorted_rows("hatcher_loads"),
                         {"setter_load_id": "setter_load_id", "unit_id": "unit_id",
                          "status": "status", "pull_class": "pull_class"})
    page, limit, offset, total = paginate(rows, limit, offset, serializers.hatcher_load)
    return ok_list(page, limit, offset, total)


@bp.post("/hatcher-loads/<rid>/pull")
def pull_chicks(rid):
    authorize(("ChickProcessor",))
    hatcher = must_get("hatcher_loads", rid)
    data = body()
    hatched_count = need_int(data, "hatched_count")

    if hatched_count < 1:
        fail("ERR_NON_POSITIVE_COUNT", "hatched_count must be at least 1.")

    # rank 14 — a hatcher load is pulled exactly once
    if hatcher["status"] != "HATCHING":
        fail("ERR_INCUBATION_INVALID_STATE", "The hatcher load has already been pulled.")

    # rank 30 — derived count never exceeds its source
    if hatched_count > hatcher["eggs_transferred"]:
        fail("ERR_COUNT_EXCEEDS_SOURCE", "hatched_count exceeds eggs_transferred.")

    pulled_at = store.clock
    window_start = hatcher["pull_window_start_at"]
    window_end = hatcher["pull_window_end_at"]

    if window_start is not None and pulled_at < window_start:
        pull_class = "EARLY"
        offset_hours = calc.rnd(
            calc.seconds_between(pulled_at, window_start) / calc.SECONDS_PER_HOUR, 2)
        hatcher["quality_flag"] = "UNHEALED_NAVEL"
        hatcher["hold_release_at"] = pulled_at + timedelta(hours=calc.EARLY_HOLD_HOURS)
        hatcher["status"] = "EARLY_PULLED"
    elif window_end is not None and pulled_at > window_end:
        pull_class = "LATE"
        offset_hours = calc.rnd(
            calc.seconds_between(pulled_at, window_end) / calc.SECONDS_PER_HOUR, 2)
        hatcher["quality_flag"] = "DEHYDRATION"
        hatcher["status"] = "LATE_PULLED"
    else:
        pull_class = "WINDOW"
        offset_hours = Decimal("0.00")
        hatcher["status"] = "WINDOW_PULLED"

    hatcher["actual_pull_at"] = pulled_at
    hatcher["pull_offset_hours"] = offset_hours
    hatcher["pull_class"] = pull_class
    store.touch(hatcher)

    flock = _primary_flock(hatcher["setter_load_id"])
    provisional = calc.quality_score(
        pull_class, offset_hours, hatcher["inherited_degree_hours"],
        0, hatched_count, hatcher["quality_flag"], "PROVISIONAL")

    batch = store.new_record(
        hatcher_load_id=hatcher["id"],
        primary_flock_id=flock["id"] if flock is not None else None,
        breed=flock["breed"] if flock is not None else None,
        hatched_count=hatched_count,
        male_count=None, female_count=None, unsexed_count=None,
        sexing_cull_count=None, preliminary_yield_pct=None,
        vaccine_reject_rate=None, vaccine_cull_count=None, cull_count=None,
        saleable_count=None, final_yield_pct=None, box_count=None,
        unassigned_chicks=None, quality_score_provisional=provisional,
        quality_score_final=None, status="PULLED",
    )
    store.chick_batches[batch["id"]] = batch

    if pull_class == "LATE" and flock is not None:
        flock["late_pull_count"] = flock["late_pull_count"] + 1
        store.touch(flock)

    return ok(serializers.chick_batch(batch), 201)


# ---------------------------------------------------------------------------
# Chick batches
# ---------------------------------------------------------------------------
@bp.get("/chick-batches/<rid>")
def get_chick_batch(rid):
    authorize(BATCH_READ_ROLES)
    return ok(serializers.chick_batch(must_get("chick_batches", rid)))


@bp.get("/chick-batches")
def list_chick_batches():
    authorize(BATCH_READ_ROLES)
    limit, offset = pagination()
    rows = apply_filters(store.sorted_rows("chick_batches"),
                         {"hatcher_load_id": "hatcher_load_id",
                          "primary_flock_id": "primary_flock_id",
                          "status": "status"})
    page, limit, offset, total = paginate(rows, limit, offset, serializers.chick_batch)
    return ok_list(page, limit, offset, total)


@bp.post("/chick-batches/<rid>/sex")
def sex_batch(rid):
    authorize(("ChickProcessor",))
    batch = must_get("chick_batches", rid)
    data = body()

    male = need_int(data, "male_count")
    female = need_int(data, "female_count")
    unsexed = need_int(data, "unsexed_count")
    culls = need_int(data, "sexing_cull_count")

    for name, value in (("male_count", male), ("female_count", female),
                        ("unsexed_count", unsexed), ("sexing_cull_count", culls)):
        if value < 0:
            fail("ERR_NON_POSITIVE_COUNT", "%s may not be negative." % name)

    if batch["status"] != "PULLED":
        fail("ERR_CHICK_FLOW_INVALID_STATE", "Only a PULLED batch can be sexed.")

    if male + female + unsexed + culls != batch["hatched_count"]:
        fail("ERR_SEX_COUNT_MISMATCH", "Sexing counts must sum to hatched_count.")

    batch["male_count"] = male
    batch["female_count"] = female
    batch["unsexed_count"] = unsexed
    batch["sexing_cull_count"] = culls
    batch["preliminary_yield_pct"] = calc.preliminary_yield_pct(
        batch["hatched_count"], culls)
    batch["status"] = "SEXED"
    store.touch(batch)
    return ok(serializers.chick_batch(batch))


@bp.post("/chick-batches/<rid>/vaccinate")
def vaccinate_batch(rid):
    authorize(("ChickProcessor",))
    batch = must_get("chick_batches", rid)
    data = body()
    need_str(data, "vaccine_code", 1)

    if batch["status"] != "SEXED":
        fail("ERR_CHICK_FLOW_INVALID_STATE", "Only a SEXED batch can be vaccinated.")

    rate = calc.vaccine_reject_rate(batch["preliminary_yield_pct"])
    vaccine_culls = calc.vaccine_cull_count(
        batch["hatched_count"], batch["sexing_cull_count"], rate)
    cull_count = batch["sexing_cull_count"] + vaccine_culls
    saleable = batch["hatched_count"] - cull_count

    batch["vaccine_reject_rate"] = rate
    batch["vaccine_cull_count"] = vaccine_culls
    batch["cull_count"] = cull_count
    batch["saleable_count"] = saleable
    batch["final_yield_pct"] = calc.final_yield_pct(saleable, batch["hatched_count"])
    batch["status"] = "VACCINATED"
    store.touch(batch)
    return ok(serializers.chick_batch(batch))


@bp.post("/chick-batches/<rid>/box")
def box_batch(rid):
    user_id, _ = authorize(("ChickProcessor",))
    batch = must_get("chick_batches", rid)

    if batch["status"] != "VACCINATED":
        fail("ERR_CHICK_FLOW_INVALID_STATE", "Only a VACCINATED batch can be boxed.")

    hatcher = store.hatcher_loads.get(batch["hatcher_load_id"])

    # rank 26 — the early-pull hold
    if hatcher is not None and hatcher["hold_release_at"] is not None \
            and store.clock < hatcher["hold_release_at"]:
        fail("ERR_EARLY_HOLD_ACTIVE", "The early-pull hold has not expired.")

    batch["box_count"] = calc.box_count_for(batch["saleable_count"])
    batch["unassigned_chicks"] = batch["saleable_count"]
    if hatcher is not None:
        batch["quality_score_final"] = calc.quality_score(
            hatcher["pull_class"], hatcher["pull_offset_hours"],
            hatcher["inherited_degree_hours"], batch["cull_count"],
            batch["hatched_count"], hatcher["quality_flag"], "FINAL")
    batch["status"] = "BOXED"
    store.touch(batch)

    if hatcher is not None and hatcher["status"] in PULLED_STATES:
        hatcher["status"] = "PROCESSED"
        store.touch(hatcher)
        services.release_unit(store.incubation_units.get(hatcher["unit_id"]))

    flock = store.breeder_flocks.get(batch["primary_flock_id"])
    if flock is not None:
        observed = services.recompute_flock_hatchability(flock)
        if observed is not None and observed < calc.HATCHABILITY_THRESHOLD_PCT:
            services.open_corrective_action(
                flock, "HATCHABILITY_BELOW_THRESHOLD", observed, user_id)
        store.touch(flock)

    return ok(serializers.chick_batch(batch))
