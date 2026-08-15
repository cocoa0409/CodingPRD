"""Core business logic: wave counts, readiness, refunds, replay, ranks, cascades."""
import math
from datetime import timedelta

import db
from util import parse_dt, parse_date_year, clock_dt, touch


# ---------------------------------------------------------------- waves

def wave_assigned_count(wave_id):
    """Count registrations pointing at this wave in an occupying status."""
    n = 0
    for r in db.registrations.values():
        if r.get("wave_id") == wave_id and r["status"] in ("CONFIRMED", "RACKED", "RACING", "FINISHED", "DSQ"):
            n += 1
    return n


def refresh_wave(wave):
    """Recompute assigned_count and auto OPEN<->FULL (CLOSED is manual only)."""
    wave["assigned_count"] = wave_assigned_count(wave["id"])
    if wave["status"] != "CLOSED":
        if wave["assigned_count"] >= wave["capacity"]:
            wave["status"] = "FULL"
        else:
            wave["status"] = "OPEN"
    return wave


def age_at_event(event, athlete):
    return parse_date_year(event["start_date"]) - parse_date_year(athlete["birth_date"])


def wave_eligible(wave, event, registration, athlete):
    if wave["status"] != "OPEN":
        return False
    if wave["assigned_count"] >= wave["capacity"]:
        return False
    if wave["division"] != registration["division"]:
        return False
    age = age_at_event(event, athlete)
    return wave["age_band_min"] <= age <= wave["age_band_max"]


def select_wave(event, registration, athlete):
    """Deterministic selector: eligible OPEN waves ranked scheduled_start_time ASC, created_at ASC."""
    eligible = [w for w in db.waves.values()
                if w["event_id"] == event["id"] and wave_eligible(w, event, registration, athlete)]
    eligible.sort(key=lambda w: (w["scheduled_start_time"], w["created_at"]))
    return eligible[0] if eligible else None


def promote_waitlist(event, wave):
    """Promote oldest eligible WAITLISTED registrations into this wave while slots remain."""
    while True:
        refresh_wave(wave)
        if wave["status"] != "OPEN" or wave["assigned_count"] >= wave["capacity"]:
            return
        candidates = [r for r in db.registrations.values()
                      if r["event_id"] == event["id"] and r["status"] == "WAITLISTED"]
        candidates.sort(key=lambda r: r["created_at"])
        promoted = False
        for reg in candidates:
            athlete = db.athletes.get(reg["athlete_id"])
            if not athlete:
                continue
            if wave_eligible(wave, event, reg, athlete):
                reg["wave_id"] = wave["id"]
                reg["age_at_event"] = age_at_event(event, athlete)
                reg["status"] = "CONFIRMED"
                touch(reg)
                refresh_wave(wave)
                touch(wave)
                promoted = True
                break
        if not promoted:
            return


def waitlist_sweep(event):
    """Run promotion across all waves of the event."""
    for wave in db.waves.values():
        if wave["event_id"] == event["id"]:
            promote_waitlist(event, wave)


# ---------------------------------------------------------- aid stations

def recompute_readiness(station):
    count = sum(1 for a in db.volunteer_assignments.values()
                if a["aid_station_id"] == station["id"] and a["status"] == "CONFIRMED")
    station["confirmed_volunteer_count"] = count
    if count < station["required_volunteers"]:
        station["readiness_status"] = "UNDERSTAFFED"
    elif station["allocated_water_units"] < station["required_water_units"]:
        station["readiness_status"] = "WATER_SHORT"
    else:
        station["readiness_status"] = "READY"
    return station


def refresh_water_pool(event):
    total = sum(s["allocated_water_units"] for s in db.aid_stations.values()
                if s["event_id"] == event["id"])
    event["water_pool_remaining"] = event["water_pool_units"] - total
    return event


# -------------------------------------------------------------- refunds

def refund_tier(entry_fee_cents, days_until_event):
    """Tiered refund per PRD §3.4. Returns estimated refund cents."""
    if days_until_event >= 60:
        pct = 0.75
    elif 30 <= days_until_event <= 59:
        pct = 0.50
    else:
        pct = 0.00
    base_cents = math.floor(entry_fee_cents * pct)
    fee_cents = math.ceil(base_cents * 0.10)
    return base_cents - fee_cents


def days_until(event, at_dt):
    delta = parse_dt(event["start_date"]) - at_dt
    return math.floor(delta.total_seconds() / 86400)


# ---------------------------------------------------------- result replay

def replay_result(result):
    """Replay VALIDATED timing records and recompute splits + provisional total.

    Division ranks are recomputed separately by recompute_ranks.
    """
    registration = db.registrations[result["registration_id"]]
    event = db.events[registration["event_id"]]
    wave = db.waves.get(registration.get("wave_id"))

    records = [t for t in db.timing_records.values()
               if t["registration_id"] == registration["id"] and t["status"] == "VALIDATED"]
    records.sort(key=lambda t: t["recorded_at"])

    by_disc = {}
    for t in records:
        by_disc[t["discipline"]] = t  # latest validated read per discipline

    swim = t1 = bike = t2 = run = None
    finish_ts = None

    if wave is not None and wave.get("actual_start_time"):
        start = parse_dt(wave["actual_start_time"])
        if event["swim_status"] == "SWIM_CANCELLED":
            swim = 0
            t1 = 0
            if "BIKE" in by_disc:
                bike = int((parse_dt(by_disc["BIKE"]["recorded_at"]) - start).total_seconds())
            if "T2" in by_disc and bike is not None:
                t2 = int((parse_dt(by_disc["T2"]["recorded_at"]) - parse_dt(by_disc["BIKE"]["recorded_at"])).total_seconds())
            if "FINISH" in by_disc and t2 is not None:
                run = int((parse_dt(by_disc["FINISH"]["recorded_at"]) - parse_dt(by_disc["T2"]["recorded_at"])).total_seconds())
                finish_ts = by_disc["FINISH"]["recorded_at"]
        else:
            if "SWIM" in by_disc:
                swim = int((parse_dt(by_disc["SWIM"]["recorded_at"]) - start).total_seconds())
            if "T1" in by_disc and swim is not None:
                t1 = int((parse_dt(by_disc["T1"]["recorded_at"]) - parse_dt(by_disc["SWIM"]["recorded_at"])).total_seconds())
            if "BIKE" in by_disc and t1 is not None:
                bike = int((parse_dt(by_disc["BIKE"]["recorded_at"]) - parse_dt(by_disc["T1"]["recorded_at"])).total_seconds())
            if "T2" in by_disc and bike is not None:
                t2 = int((parse_dt(by_disc["T2"]["recorded_at"]) - parse_dt(by_disc["BIKE"]["recorded_at"])).total_seconds())
            if "FINISH" in by_disc and t2 is not None:
                run = int((parse_dt(by_disc["FINISH"]["recorded_at"]) - parse_dt(by_disc["T2"]["recorded_at"])).total_seconds())
                finish_ts = by_disc["FINISH"]["recorded_at"]

    result["swim_seconds"] = swim
    result["t1_seconds"] = t1
    result["bike_seconds"] = bike
    result["t2_seconds"] = t2
    result["run_seconds"] = run
    result["finish_timestamp"] = finish_ts

    if finish_ts is not None and None not in (swim, t1, bike, t2, run):
        result["provisional_total_seconds"] = swim + t1 + bike + t2 + run
    else:
        result["provisional_total_seconds"] = None

    recompute_totals(result)
    return result


def penalty_seconds_total(registration_id):
    return sum(p["seconds"] for p in db.penalties.values()
               if p["registration_id"] == registration_id and p["status"] == "CONFIRMED")


def recompute_totals(result):
    result["penalty_seconds_total"] = penalty_seconds_total(result["registration_id"])
    if result["status"] == "OFFICIAL":
        if result["provisional_total_seconds"] is not None:
            result["official_total_seconds"] = result["provisional_total_seconds"] + result["penalty_seconds_total"]
        else:
            result["official_total_seconds"] = None
        result["effective_total_seconds"] = result["official_total_seconds"]
    else:
        result["official_total_seconds"] = None
        result["effective_total_seconds"] = result["provisional_total_seconds"]
    return result


def recompute_ranks(event_id):
    """Recompute division_rank per division over non-DSQ results with non-null effective totals."""
    regs = {r["id"]: r for r in db.registrations.values() if r["event_id"] == event_id}
    event_results = [res for res in db.results.values() if res["registration_id"] in regs]

    for division in ("AGE_GROUP", "ELITE"):
        cands = []
        for res in event_results:
            reg = regs[res["registration_id"]]
            if reg["division"] != division:
                continue
            if reg["status"] == "DSQ" or res["effective_total_seconds"] is None:
                res["division_rank"] = None
                continue
            cands.append((res, reg))
        cands.sort(key=lambda pair: (
            pair[0]["effective_total_seconds"],
            pair[0].get("finish_timestamp") or "",
            pair[1]["created_at"],
        ))
        for i, (res, _reg) in enumerate(cands, start=1):
            res["division_rank"] = i


# ------------------------------------------------------------ cascades

def confirm_penalty(penalty):
    """Confirm a penalty: recompute totals, apply DSQ cascade if flagged."""
    if penalty["status"] != "ASSESSED":
        return
    penalty["status"] = "CONFIRMED"
    touch(penalty)
    registration = db.registrations[penalty["registration_id"]]
    result = next((r for r in db.results.values() if r["registration_id"] == registration["id"]), None)
    if result:
        recompute_totals(result)
        touch(result)
    if penalty.get("triggers_dsq"):
        if registration["status"] in ("RACING", "FINISHED"):
            registration["status"] = "DSQ"
            touch(registration)
            if result:
                result["division_rank"] = None
                touch(result)
            # wave count refresh (DSQ still counts as occupying per assigned_count definition)
            if registration.get("wave_id") and registration["wave_id"] in db.waves:
                wave = db.waves[registration["wave_id"]]
                refresh_wave(wave)
                touch(wave)
    recompute_ranks(registration["event_id"])


def withdraw_registration(registration, *, full_refund=False, refund_destination=None):
    """Shared withdrawal logic. Mutates registration; frees wave slot + promotes when occupied.

    Caller must have already validated preconditions (appeals open, refund destination).
    """
    clock = clock_dt()
    event = db.events[registration["event_id"]]
    prev_status = registration["status"]
    freed_wave_id = registration.get("wave_id") if prev_status in ("CONFIRMED", "RACKED") else None

    registration["status"] = "WITHDRAWN"
    registration["withdrawn_at"] = db.get_clock()
    if full_refund:
        registration["refund_estimate_cents"] = registration["entry_fee_cents"]
        registration["refund_final_cents"] = registration["entry_fee_cents"]
    else:
        estimate = refund_tier(registration["entry_fee_cents"], days_until(event, clock))
        registration["refund_estimate_cents"] = estimate
        registration["refund_final_cents"] = None
        if refund_destination is not None:
            registration["refund_destination"] = refund_destination
    touch(registration)

    if freed_wave_id and freed_wave_id in db.waves:
        wave = db.waves[freed_wave_id]
        refresh_wave(wave)
        touch(wave)
        promote_waitlist(event, wave)
