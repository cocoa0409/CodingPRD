"""Bell-curve calibration algorithms."""
from db import db
from routes.cycles import bands_for_cycle


def ordered_bands(cycle_id):
    """RatingBands sorted ascending by min_score (lowest band first)."""
    return sorted(bands_for_cycle(cycle_id), key=lambda b: b["min_score"])


def band_for_score(cycle_id, score):
    bands = ordered_bands(cycle_id)
    for b in bands:
        if b["min_score"] <= score < b["max_score"]:
            return b["label"]
    # top band inclusive of 100
    top = bands[-1]
    if score == top["max_score"]:
        return top["label"]
    # score below lowest min or above top max: clamp to nearest band
    if score < bands[0]["min_score"]:
        return bands[0]["label"]
    return top["label"]


def in_scope_reviews(cycle_id, department):
    """SUBMITTED reviews in cycle, whose subject employee is in department."""
    result = []
    for r in db.reviews.values():
        if r["cycle_id"] != cycle_id or r["status"] != "SUBMITTED":
            continue
        emp = db.employees.get(r["employee_id"])
        if emp and emp.get("department") == department:
            result.append(r)
    return result


def compute_actual(cycle_id, reviews, ratings):
    """Fraction per band label given a dict review_id -> band label."""
    bands = ordered_bands(cycle_id)
    counts = {b["label"]: 0 for b in bands}
    n = len(reviews)
    for r in reviews:
        lbl = ratings[r["id"]]
        counts[lbl] = counts.get(lbl, 0) + 1
    if n == 0:
        return {lbl: 0.0 for lbl in counts}
    return {lbl: counts[lbl] / n for lbl in counts}


def assign_final_ratings(cycle_id, reviews):
    """Chronological-replay bell-curve assignment.

    Returns dict review_id -> final band label.
    """
    cycle = db.cycles[cycle_id]
    target = cycle["bell_curve_target"]
    tolerance = cycle["distribution_tolerance"]
    bands = ordered_bands(cycle_id)  # lowest first
    band_labels = [b["label"] for b in bands]
    lowest_label = band_labels[0]

    ordered = sorted(reviews, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    ratings = {r["id"]: band_for_score(cycle_id, r["composite_score"]) for r in ordered}

    n = len(ordered)
    if n == 0:
        return ratings

    def next_lower(label):
        idx = band_labels.index(label)
        return band_labels[idx - 1] if idx > 0 else label

    def actual_fraction(label):
        cnt = sum(1 for r in ordered if ratings[r["id"]] == label)
        return cnt / n

    # Iteratively demote until every band (except the lowest) is within tolerance.
    while True:
        over_band = None
        # Consider bands from highest to lowest, excluding the lowest band.
        for label in reversed(band_labels):
            if label == lowest_label:
                continue
            tgt = target.get(label, 0)
            if actual_fraction(label) > tgt + tolerance:
                over_band = label
                break
        if over_band is None:
            break
        # victim: lowest composite_score review currently in over_band,
        # tie-break by created_at ascending (then _seq).
        candidates = [r for r in ordered if ratings[r["id"]] == over_band]
        victim = min(
            candidates,
            key=lambda r: (r["composite_score"], r["created_at"], r.get("_seq", 0)),
        )
        ratings[victim["id"]] = next_lower(over_band)

    return ratings
