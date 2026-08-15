"""Item statistics: p_value, point-biserial, pass_flag (PRD §3.4, §2.6).

All statistics round to 4 decimals ROUND_HALF_UP. PROVISIONAL uses all non-excluded
responses; FINAL adds the closed [start_utc, end_utc] timestamp filter and the
attempt_duration_seconds >= 30 filter.
"""
from decimal import Decimal, ROUND_HALF_UP, getcontext

from db import db
from util import parse_dt

getcontext().prec = 40

MIN_DURATION_SECONDS = 30
Q4 = Decimal("0.0001")
Q6 = Decimal("0.000001")

PB_SEVERE = Decimal("0.10")
PB_MIN = Decimal("0.20")
P_LOW = Decimal("0.30")
P_HIGH = Decimal("0.85")


def round4(d: Decimal) -> Decimal:
    return d.quantize(Q4, rounding=ROUND_HALF_UP)


def round6(d: Decimal) -> Decimal:
    return d.quantize(Q6, rounding=ROUND_HALF_UP)


def to_float(d: Decimal) -> float:
    return float(d)


def pass_flag_for(p_value_4: Decimal, pb_4: Decimal) -> str:
    """Strict boundaries: pb == 0.20 passes PB_MIN; p == 0.30 passes P_LOW."""
    if pb_4 < PB_SEVERE:
        return "FAIL_SEVERE"
    if pb_4 < PB_MIN or p_value_4 < P_LOW or p_value_4 > P_HIGH:
        return "FAIL_BORDERLINE"
    return "PASS"


def _pearson(xs, ys) -> Decimal:
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    syy = sum(y * y for y in ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    num = Decimal(n) * sxy - sx * sy
    den_x = Decimal(n) * sxx - sx * sx
    den_y = Decimal(n) * syy - sy * sy
    if den_x <= 0 or den_y <= 0:
        return Decimal("0")
    den = (den_x * den_y).sqrt()
    if den == 0:
        return Decimal("0")
    return num / den


def _item_max_score(item_id) -> int:
    item = db["items"].get(item_id)
    return item["max_score_points"] if item else 1


def compute_item_stats(item, window, responses_in_scope):
    """Compute (p_value, point_biserial) as rounded Decimals over the given
    already-filtered response set for this window.

    responses_in_scope: ALL responses in the window passing the variant filter
    (any item) — needed to derive each student's mean score over OTHER items.
    """
    item_id = item["id"]
    max_score = item["max_score_points"]
    r_set = [r for r in responses_in_scope if r["item_id"] == item_id]
    n = len(r_set)
    total = sum(r["raw_score"] for r in r_set)
    p_value = round4(Decimal(total) / (Decimal(n) * Decimal(max_score)))

    by_student = {}
    for r in responses_in_scope:
        by_student.setdefault(r["student_anon_id"], []).append(r)

    xs, ys = [], []
    for r in r_set:
        others = [
            o
            for o in by_student.get(r["student_anon_id"], [])
            if o["item_id"] != item_id
        ]
        if not others:
            continue
        x = Decimal(r["raw_score"]) / Decimal(max_score)
        y = sum(Decimal(o["raw_score"]) / Decimal(_item_max_score(o["item_id"])) for o in others) / Decimal(
            len(others)
        )
        xs.append(x)
        ys.append(y)

    if len(xs) < 2 or len(set(xs)) == 1 or len(set(ys)) == 1:
        point_biserial = Decimal("0")
    else:
        point_biserial = _pearson(xs, ys)
    return p_value, round4(point_biserial), n


def provisional_scope(window_id):
    """All non-excluded responses in the window (no timestamp/duration filter)."""
    return [
        r
        for r in db["item_responses"].values()
        if r["window_id"] == window_id and not r["excluded"]
    ]


def final_scope(window, window_id):
    """Non-excluded responses in the closed interval [start_utc, end_utc] with
    attempt_duration_seconds >= MIN_DURATION_SECONDS."""
    start = window["_start_dt"]
    end = window["_end_dt"]
    out = []
    for r in db["item_responses"].values():
        if r["window_id"] != window_id or r["excluded"]:
            continue
        ts = parse_dt(r["response_timestamp"])
        if not (start <= ts <= end):
            continue
        if r["attempt_duration_seconds"] < MIN_DURATION_SECONDS:
            continue
        out.append(r)
    return out
