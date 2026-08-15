"""Projection engine: time derivation, ranking with exclusions, awards,
integrity sweeps, correction/flag cascades, and the live board."""
from datetime import timedelta
from decimal import Decimal

import clock
import db
from db import new_entity, touch
from util import fmt_dt, ms_between, rhu
from validators import sorted_items

PROTEST_WINDOW_MINUTES = 30
MIN_PACE_SEC_PER_KM = 120
AWARD_DEPTH = 3


# ---------------------------------------------------------------- helpers

def race_points(race_id):
    return [p for p in db.timing_points.values() if p["race_id"] == race_id]


def _point_of_kind(points, kind):
    cands = [p for p in points if p["kind"] == kind]
    if not cands:
        return None
    cands.sort(key=lambda p: p["point_index"])
    return cands[0]


def _scored_reads(chip_id, point_id):
    return [
        r
        for r in db.timing_reads.values()
        if r["chip_id"] == chip_id
        and r["timing_point_id"] == point_id
        and r["status"] == "SCORED"
    ]


def _checked_in_regs(race_id):
    regs = [
        r
        for r in db.registrations.values()
        if r["race_id"] == race_id and r["lifecycle_status"] == "CHECKED_IN"
    ]
    return sorted_items(regs)


def derive(reg, points):
    """time_derivation (calc): chip/gun times, finish anchor, completed splits."""
    out = {
        "chip_time_ms": None,
        "gun_time_ms": None,
        "finish_timestamp": None,
        "completed_splits": 0,
    }
    chip_id = reg["chip_id"]
    start_p = _point_of_kind(points, "START")
    finish_p = _point_of_kind(points, "FINISH")
    if not chip_id:
        return out
    splits = [p for p in points if p["kind"] == "SPLIT"]
    out["completed_splits"] = sum(
        1 for p in splits if _scored_reads(chip_id, p["id"])
    )
    if not finish_p:
        return out
    fin_reads = _scored_reads(chip_id, finish_p["id"])
    if not fin_reads:
        return out
    fin_reads.sort(key=lambda r: (r["read_timestamp"], r["_seq"]))
    fin = fin_reads[0]  # earliest SCORED FINISH
    out["finish_timestamp"] = fin["read_timestamp"]
    if start_p:
        starts = [
            r
            for r in _scored_reads(chip_id, start_p["id"])
            if r["read_timestamp"] < fin["read_timestamp"]
        ]
        if starts:
            starts.sort(key=lambda r: (r["read_timestamp"], r["_seq"]))
            latest_start = starts[-1]  # latest SCORED START strictly before finish
            out["chip_time_ms"] = ms_between(
                latest_start["read_timestamp"], fin["read_timestamp"]
            )
    wave = db.waves.get(reg["wave_id"])
    if wave is not None and wave["actual_start_time"] is not None:
        out["gun_time_ms"] = ms_between(wave["actual_start_time"], fin["read_timestamp"])
    return out


def _exclusion_reason(reg_id):
    conf = [
        f
        for f in db.result_flags.values()
        if f["registration_id"] == reg_id and f["status"] == "CONFIRMED"
    ]
    if not conf:
        return None
    conf.sort(key=lambda f: (f["created_at"], f["_seq"]))
    return conf[0]["flag_type"]


def _computed_tuple(res):
    return (
        res["chip_time_ms"],
        res["gun_time_ms"],
        res["finish_timestamp"],
        res["completed_splits"],
        res["overall_rank_gun"],
        res["age_group_rank_chip"],
        res["qualified"],
    )


def _find_result(registration_id):
    for r in db.results.values():
        if r["registration_id"] == registration_id:
            return r
    return None


# ---------------------------------------------------------------- recompute

def recompute_race(race, mode):
    """ranking_with_exclusions (calc): pinned 4-phase evaluation order.
    mode: 'publish' | 'correction' | 'flag'."""
    race_id = race["id"]
    points = race_points(race_id)
    regs = _checked_in_regs(race_id)

    # Phase 1 DERIVE + Phase 2 EXCLUDE
    comp = {}
    for reg in regs:
        d = derive(reg, points)
        reason = _exclusion_reason(reg["id"])
        d["excluded"] = reason is not None
        d["exclusion_reason"] = reason
        d["overall_rank_gun"] = None
        d["age_group_rank_chip"] = None
        comp[reg["id"]] = d

    # Phase 3 RANK
    eligible = [r for r in regs if not comp[r["id"]]["excluded"]]
    gun = [r for r in eligible if comp[r["id"]]["gun_time_ms"] is not None]
    gun.sort(
        key=lambda r: (
            comp[r["id"]]["gun_time_ms"],
            comp[r["id"]]["finish_timestamp"],
            r["created_at"],
            r["_seq"],
        )
    )
    for i, r in enumerate(gun):
        comp[r["id"]]["overall_rank_gun"] = i + 1
    groups = {}
    for r in eligible:
        if comp[r["id"]]["chip_time_ms"] is None:
            continue
        groups.setdefault((r["gender"], r["age_group"]), []).append(r)
    for members in groups.values():
        members.sort(
            key=lambda r: (
                comp[r["id"]]["chip_time_ms"],
                comp[r["id"]]["finish_timestamp"],
                r["created_at"],
                r["_seq"],
            )
        )
        for i, r in enumerate(members):
            comp[r["id"]]["age_group_rank_chip"] = i + 1

    # Phase 4 WRITE
    std = race["qualifying_standard_ms"]
    for reg in regs:
        d = comp[reg["id"]]
        qualified = bool(
            std is not None
            and not d["excluded"]
            and d["chip_time_ms"] is not None
            and d["chip_time_ms"] <= std
        )
        res = _find_result(reg["id"])
        if res is None:
            res = new_entity()
            res.update(
                {
                    "race_id": race_id,
                    "registration_id": reg["id"],
                    "status": "EXCLUDED" if d["excluded"] else "PROVISIONAL",
                    "exclusion_reason": d["exclusion_reason"],
                    "chip_time_ms": d["chip_time_ms"],
                    "gun_time_ms": d["gun_time_ms"],
                    "finish_timestamp": d["finish_timestamp"],
                    "completed_splits": d["completed_splits"],
                    "overall_rank_gun": None if d["excluded"] else d["overall_rank_gun"],
                    "age_group_rank_chip": None if d["excluded"] else d["age_group_rank_chip"],
                    "qualified": qualified,
                    "revision": 1,
                }
            )
            db.results[res["id"]] = res
            continue

        new_tuple = (
            d["chip_time_ms"],
            d["gun_time_ms"],
            d["finish_timestamp"],
            d["completed_splits"],
            None if d["excluded"] else d["overall_rank_gun"],
            None if d["excluded"] else d["age_group_rank_chip"],
            qualified,
        )
        changed = new_tuple != _computed_tuple(res)

        new_status = res["status"]
        if d["excluded"]:
            new_status = "EXCLUDED"
        elif mode == "publish":
            new_status = "PROVISIONAL"
        elif res["status"] == "OFFICIAL" and changed:
            new_status = "AMENDED"

        new_reason = d["exclusion_reason"] if d["excluded"] else res["exclusion_reason"]
        if not d["excluded"] and res["status"] != "EXCLUDED":
            new_reason = None

        anything_changed = (
            changed
            or new_status != res["status"]
            or new_reason != res["exclusion_reason"]
        )
        if anything_changed:
            (
                res["chip_time_ms"],
                res["gun_time_ms"],
                res["finish_timestamp"],
                res["completed_splits"],
                res["overall_rank_gun"],
                res["age_group_rank_chip"],
                res["qualified"],
            ) = new_tuple
            res["status"] = new_status
            res["exclusion_reason"] = new_reason
            if changed:
                res["revision"] += 1
            touch(res)

    _recompute_awards(race, comp, regs)


def _recompute_awards(race, comp, regs):
    """award_computation (calc): waterfall allocation with swap rule."""
    race_id = race["id"]
    eligible = [r for r in regs if not comp[r["id"]]["excluded"]]
    desired = {}
    for gender, cat in (("M", "OVERALL_M"), ("F", "OVERALL_F")):
        cands = [
            r
            for r in eligible
            if r["gender"] == gender and comp[r["id"]]["overall_rank_gun"] is not None
        ]
        cands.sort(key=lambda r: comp[r["id"]]["overall_rank_gun"])
        for place, r in enumerate(cands[:AWARD_DEPTH], start=1):
            desired[(cat, place)] = (r["id"], "GUN", comp[r["id"]]["gun_time_ms"])
    groups = {}
    for r in eligible:
        if comp[r["id"]]["age_group_rank_chip"] is None:
            continue
        groups.setdefault((r["gender"], r["age_group"]), []).append(r)
    for (gender, group), members in groups.items():
        cat = "AG_{}_{}".format(gender, group.replace("-", "_"))
        members.sort(key=lambda r: comp[r["id"]]["age_group_rank_chip"])
        for place, r in enumerate(members[:AWARD_DEPTH], start=1):
            desired[(cat, place)] = (r["id"], "CHIP", comp[r["id"]]["chip_time_ms"])

    existing = [
        a
        for a in db.awards.values()
        if a["race_id"] == race_id and a["status"] != "REVOKED"
    ]
    satisfied = set()
    for a in existing:
        key = (a["category"], a["place"])
        if key in desired and desired[key][0] == a["registration_id"]:
            satisfied.add(key)  # winner unchanged: kept exactly as it is
        else:
            a["status"] = "REVOKED"
            touch(a)
    for key, (reg_id, basis, basis_time) in desired.items():
        if key in satisfied:
            continue
        a = new_entity()
        a.update(
            {
                "race_id": race_id,
                "registration_id": reg_id,
                "category": key[0],
                "place": key[1],
                "basis": basis,
                "basis_time_ms": basis_time,
                "status": "PROJECTED",
            }
        )
        db.awards[a["id"]] = a


# ---------------------------------------------------------------- auto flags

def has_auto_flag(registration_id, flag_type, statuses):
    return any(
        f["registration_id"] == registration_id
        and f["origin"] == "AUTO"
        and f["flag_type"] == flag_type
        and f["status"] in statuses
        for f in db.result_flags.values()
    )


def raise_auto_flag(reg, flag_type, detail):
    f = new_entity()
    f.update(
        {
            "registration_id": reg["id"],
            "flag_type": flag_type,
            "origin": "AUTO",
            "status": "RAISED",
            "detail": detail,
        }
    )
    db.result_flags[f["id"]] = f
    return f


def pace_check(reg, point, read_dt, chip_id, read_id):
    """course_cut_detection per-ingest pace check (calc)."""
    if point["kind"] not in ("SPLIT", "FINISH"):
        return
    points = race_points(point["race_id"])
    start_p = _point_of_kind(points, "START")
    if start_p is None:
        return
    starts = [
        r
        for r in _scored_reads(chip_id, start_p["id"])
        if r["read_timestamp"] < read_dt and r["id"] != read_id
    ]
    if not starts:
        return  # skip silently when no SCORED START read exists yet
    starts.sort(key=lambda r: (r["read_timestamp"], r["_seq"]))
    elapsed_ms = ms_between(starts[-1]["read_timestamp"], read_dt)
    floor = Decimal(str(point["distance_km"])) * MIN_PACE_SEC_PER_KM * 1000
    if Decimal(elapsed_ms) < floor:  # strictly below; equality raises nothing
        if not has_auto_flag(reg["id"], "COURSE_CUT_SUSPECT", ("RAISED", "CONFIRMED")):
            raise_auto_flag(
                reg,
                "COURSE_CUT_SUSPECT",
                "AUTO: elapsed {}ms below minimum pace floor at point_index {}".format(
                    elapsed_ms, point["point_index"]
                ),
            )


def publish_race(race):
    """publish-results side effects: recompute, integrity sweeps, window stamps."""
    race_id = race["id"]
    recompute_race(race, "publish")

    points = race_points(race_id)
    finish_p = _point_of_kind(points, "FINISH")
    regs = _checked_in_regs(race_id)

    # dnf_detection sweep: CHECKED_IN without a SCORED FINISH read.
    for reg in regs:
        chip_id = reg["chip_id"]
        has_finish = bool(
            chip_id and finish_p and _scored_reads(chip_id, finish_p["id"])
        )
        if not has_finish and not has_auto_flag(reg["id"], "DNF", ("RAISED",)):
            raise_auto_flag(reg, "DNF", "AUTO: no SCORED FINISH read at publish")

    # course_cut_detection missing-split sweep.
    for reg in regs:
        if has_auto_flag(reg["id"], "COURSE_CUT_SUSPECT", ("RAISED", "CONFIRMED")):
            continue
        chip_id = reg["chip_id"]
        if not chip_id:
            continue
        scored_point_ids = {
            r["timing_point_id"]
            for r in db.timing_reads.values()
            if r["chip_id"] == chip_id and r["status"] == "SCORED"
        }
        reached = [p["point_index"] for p in points if p["id"] in scored_point_ids]
        if not reached:
            continue
        k = max(reached)
        missing = [
            p
            for p in points
            if p["kind"] == "SPLIT"
            and p["point_index"] < k
            and p["id"] not in scored_point_ids
        ]
        if missing:
            j = min(p["point_index"] for p in missing)
            raise_auto_flag(
                reg,
                "COURSE_CUT_SUSPECT",
                "AUTO: missing SCORED read at SPLIT point_index {}".format(j),
            )

    n = clock.now()
    race["status"] = "PROVISIONAL_PUBLISHED"
    race["provisional_published_at"] = n
    race["protest_window_closes_at"] = n + timedelta(minutes=PROTEST_WINDOW_MINUTES)
    touch(race)


def apply_correction_cascade(corr, race):
    """Cascade C1: read mutation -> recompute -> awards -> race amendment ->
    certification revocation -> race version increment."""
    read = db.timing_reads.get(corr["timing_read_id"])
    if read is not None:
        if corr["kind"] == "EXCLUDE_READ" and read["status"] == "SCORED":
            read["status"] = "EXCLUDED"
        elif corr["kind"] == "REINSTATE_READ" and read["status"] == "EXCLUDED":
            read["status"] = "SCORED"
        elif corr["kind"] == "ADJUST_READ_TIME" and read["status"] == "SCORED":
            read["read_timestamp"] = corr["corrected_timestamp"]
            read["adjusted_by_correction_id"] = corr["id"]

    recompute_race(race, "correction")

    race["status"] = "AMENDMENT_OPEN"
    race["amendment_count"] += 1
    touch(race)  # increments Race.version by 1

    cert = None
    for c in db.certifications.values():
        if c["race_id"] == race["id"]:
            cert = c
            break
    if cert is not None and cert["status"] == "ISSUED":
        cert["status"] = "REVOKED"
        cert["revocation_reason"] = "CORRECTION_APPROVED"
        touch(cert)


# ---------------------------------------------------------------- live board

def build_live_board(race, bib_filter):
    """live_board_projection (calc): pinned nested rounding order."""
    race_id = race["id"]
    points = race_points(race_id)
    point_by_id = {p["id"]: p for p in points}
    start_p = _point_of_kind(points, "START")
    finish_p = _point_of_kind(points, "FINISH")
    regs = _checked_in_regs(race_id)

    projected = []
    finished = []
    waiting = []

    for reg in regs:
        if _exclusion_reason(reg["id"]) is not None:
            continue  # board covers non-excluded registrations only
        chip_id = reg["chip_id"]
        reads = []
        if chip_id:
            reads = [
                r
                for r in db.timing_reads.values()
                if r["chip_id"] == chip_id
                and r["status"] == "SCORED"
                and r["timing_point_id"] in point_by_id
            ]
        per_point = {}
        for r in reads:
            cur = per_point.get(r["timing_point_id"])
            if cur is None or (r["read_timestamp"], r["_seq"]) < (
                cur["read_timestamp"],
                cur["_seq"],
            ):
                per_point[r["timing_point_id"]] = r
        ordered = sorted(
            per_point.values(),
            key=lambda r: point_by_id[r["timing_point_id"]]["point_index"],
        )
        start_read = per_point.get(start_p["id"]) if start_p else None
        fin_read = per_point.get(finish_p["id"]) if finish_p else None

        base = {
            "registration_id": reg["id"],
            "bib_number": reg["bib_number"],
            "participant_name": reg["participant_name"],
            "gender": reg["gender"],
            "age_group": reg["age_group"],
            "projected_total_sec": None,
            "elapsed_last_sec": None,
            "projected_pace_sec_per_km": None,
            "projected_remaining_sec": None,
            "remaining_km": None,
            "last_point_index": None,
            "last_distance_km": None,
            "chip_time_ms": None,
            "gun_time_ms": None,
            "finish_timestamp": None,
        }

        if fin_read is not None:
            d = derive(reg, points)
            base.update(
                {
                    "board_status": "FINISHED",
                    "chip_time_ms": d["chip_time_ms"],
                    "gun_time_ms": d["gun_time_ms"],
                    "finish_timestamp": fmt_dt(d["finish_timestamp"]),
                    "last_point_index": finish_p["point_index"],
                    "last_distance_km": finish_p["distance_km"],
                }
            )
            finished.append((reg, base))
        elif start_read is None:
            base["board_status"] = "AWAITING_START"
            waiting.append((reg, base))
        else:
            segs = []
            for i in range(1, len(ordered)):
                p_prev = point_by_id[ordered[i - 1]["timing_point_id"]]
                p_cur = point_by_id[ordered[i]["timing_point_id"]]
                dt_sec = Decimal(
                    ms_between(
                        ordered[i - 1]["read_timestamp"], ordered[i]["read_timestamp"]
                    )
                ) / Decimal(1000)
                dd = Decimal(str(p_cur["distance_km"])) - Decimal(
                    str(p_prev["distance_km"])
                )
                segs.append(rhu(dt_sec / dd))  # per-segment rounding FIRST
            last_point = point_by_id[ordered[-1]["timing_point_id"]]
            elapsed_last = rhu(
                Decimal(ms_between(start_read["read_timestamp"], ordered[-1]["read_timestamp"]))
                / Decimal(1000)
            )
            remaining = Decimal(str(race["distance_km"])) - Decimal(
                str(last_point["distance_km"])
            )
            if len(segs) >= 2:
                proj_pace = rhu(Decimal(segs[-1] + segs[-2]) / Decimal(2))
            elif len(segs) == 1:
                proj_pace = segs[0]
            else:
                proj_pace = None
            if proj_pace is None:
                proj_remaining = None
                proj_total = elapsed_last
            else:
                proj_remaining = rhu(remaining * proj_pace)
                proj_total = elapsed_last + proj_remaining
            base.update(
                {
                    "board_status": "PROJECTED",
                    "projected_total_sec": proj_total,
                    "elapsed_last_sec": elapsed_last,
                    "projected_pace_sec_per_km": proj_pace,
                    "projected_remaining_sec": proj_remaining,
                    "remaining_km": float(remaining),
                    "last_point_index": last_point["point_index"],
                    "last_distance_km": last_point["distance_km"],
                }
            )
            projected.append((reg, base))

    projected.sort(
        key=lambda t: (
            t[1]["projected_total_sec"],
            t[1]["elapsed_last_sec"],
            t[0]["created_at"],
            t[0]["_seq"],
        )
    )
    finished.sort(
        key=lambda t: (
            t[1]["chip_time_ms"] if t[1]["chip_time_ms"] is not None else 1 << 62,
            t[0]["created_at"],
            t[0]["_seq"],
        )
    )
    waiting.sort(key=lambda t: (t[0]["created_at"], t[0]["_seq"]))

    entries = []
    for _, base in projected + finished + waiting:
        base = dict(base)
        base["position"] = len(entries) + 1
        entries.append(base)
    if bib_filter is not None:
        entries = [e for e in entries if e["bib_number"] == bib_filter]
    return {"entries": entries, "generated_at": fmt_dt(clock.now())}
