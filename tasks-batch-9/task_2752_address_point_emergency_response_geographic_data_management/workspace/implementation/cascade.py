"""The declared cascade rules.

PIN_STALENESS_RULE is evaluated after each individual record mutation, in the
declared cascade order of the triggering transition, before the cascade advances
to its next level.
"""

import re

import calc
from store import db, sorted_rows, touch

TERMINAL_BY_TYPE = {
    "ADDRESS_POINT": ("RETIRED", "VOIDED"),
    "ROAD_CENTERLINE": ("RETIRED",),
    "EMERGENCY_SERVICE_BOUNDARY": ("RETIRED",),
}


# ---------------------------------------------------------------------------
# INVALIDATED_REASON_FIRST_WRITER
# ---------------------------------------------------------------------------
def invalidate_package(package, reason):
    """Invalidate a package unless it already holds an invalidated_reason."""
    if package["status"] == "INVALIDATED" or package.get("invalidated_reason") is not None:
        return False
    package["status"] = "INVALIDATED"
    package["invalidated_reason"] = reason
    touch(package)
    return True


# ---------------------------------------------------------------------------
# PIN_STALENESS_RULE
# ---------------------------------------------------------------------------
def pin_staleness(record_type, record_id, destructive=False):
    """Flip FRESH pins on this record to STALE and settle the owning packages."""
    live_version = calc.live_record_version(record_type, record_id)
    if live_version is None:
        return
    flipped_packages = []
    for pin in sorted_rows(list(db.package_records.values())):
        if pin["record_type"] != record_type or pin["record_id"] != record_id:
            continue
        if pin["pin_state"] != "FRESH":
            continue
        if pin["pinned_version"] == live_version:
            continue
        pin["pin_state"] = "STALE"
        pin["staled_at"] = db.now()
        touch(pin)
        package = db.packages.get(pin["package_id"])
        if package is not None and package not in flipped_packages:
            flipped_packages.append(package)
    if not destructive:
        return
    for package in flipped_packages:
        if package["status"] != "SEALED":
            continue
        if calc.package_pin_counts(package["id"])["stale_pin_count"] > 0:
            invalidate_package(package, "PIN_STALE")


def pin_staleness_for_point(point):
    destructive = point["status"] in TERMINAL_BY_TYPE["ADDRESS_POINT"]
    pin_staleness("ADDRESS_POINT", point["id"], destructive)


def pin_staleness_for_road(road):
    destructive = road["status"] in TERMINAL_BY_TYPE["ROAD_CENTERLINE"]
    pin_staleness("ROAD_CENTERLINE", road["id"], destructive)


def pin_staleness_for_boundary(boundary):
    destructive = boundary["status"] in TERMINAL_BY_TYPE["EMERGENCY_SERVICE_BOUNDARY"]
    pin_staleness("EMERGENCY_SERVICE_BOUNDARY", boundary["id"], destructive)


# ---------------------------------------------------------------------------
# CONFIDENCE_REFRESH
# ---------------------------------------------------------------------------
def confidence_refresh(road):
    """Re-score every non-terminal point on the road under the provisional variant."""
    rows = calc.points_by_house_number(calc.road_points(road["id"], ("PENDING", "ACTIVE")))
    for point in rows:
        point["confidence_score"] = calc.confidence_score(point, "provisional")
        touch(point)
        pin_staleness_for_point(point)
    return rows


# ---------------------------------------------------------------------------
# address point terminal transitions used by several cascades
# ---------------------------------------------------------------------------
def terminate_point(point, status, reason):
    point["status"] = status
    point["retire_reason"] = reason
    point["retired_at"] = db.now()
    touch(point)
    pin_staleness_for_point(point)


def retire_child_units(parent, reason="PARENT_RETIRED"):
    children = calc.points_by_house_number(
        [p for p in db.points.values()
         if p.get("parent_address_point_id") == parent["id"]
         and p["status"] in ("PENDING", "ACTIVE")])
    for child in children:
        terminate_point(child, "RETIRED", reason)
    return children


# ---------------------------------------------------------------------------
# the five-level road retirement cascade
# ---------------------------------------------------------------------------
def road_retirement_cascade(road):
    """Levels 2..5; level 1 (the road itself) is performed by the caller."""
    base_points = calc.points_by_house_number(
        [p for p in db.points.values()
         if p["road_centerline_id"] == road["id"]
         and p.get("unit_id") is None
         and p["status"] in ("PENDING", "ACTIVE")])
    retired_ids = []
    for point in base_points:
        terminate_point(point, "RETIRED", "ROAD_RETIRED")
        retired_ids.append(point["id"])
    for point_id in retired_ids:
        parent = db.points[point_id]
        retire_child_units(parent)


# ---------------------------------------------------------------------------
# the adoption / arbitration cascade (levels 2..5)
# ---------------------------------------------------------------------------
_RANGE_TOKEN = re.compile(r"\d+")


def _apply_range_expression(road, expression):
    """Write a resolved ADDRESS_RANGE expression into the named side's fields.

    The resolved value is operator free text, so parsing is deliberately
    tolerant: a LEFT/RIGHT token selects the side, the first two integers become
    the bounds, and an EVEN/ODD token overrides the parity. An expression that
    cannot be read leaves the range untouched while the rest of the cascade
    still runs.
    """
    upper = expression.upper()
    if "RIGHT" in upper:
        side = "RIGHT"
    elif "LEFT" in upper:
        side = "LEFT"
    else:
        side = "LEFT"
    numbers = [int(n) for n in _RANGE_TOKEN.findall(upper)]
    if len(numbers) < 2:
        return
    low, high = numbers[0], numbers[1]
    if low > high:
        low, high = high, low
    suffix = "left" if side == "LEFT" else "right"
    road["from_addr_" + suffix] = low
    road["to_addr_" + suffix] = high
    if "EVEN" in upper:
        road["parity_" + suffix] = "EVEN"
    elif "ODD" in upper:
        road["parity_" + suffix] = "ODD"


def resolution_cascade(case, resolved_value):
    """Levels 2 through 5 of the adoption / arbitration cascade."""
    if case["subject_type"] not in ("ROAD_NAME", "ADDRESS_RANGE"):
        return
    road = db.roads.get(case["subject_ref_id"])
    if road is None:
        return

    # ---- level 2: the subject centerline applies the resolved value ----
    if case["subject_type"] == "ROAD_NAME":
        road["primary_name"] = resolved_value
    else:
        _apply_range_expression(road, resolved_value)
    road["normalized_name"] = calc.normalized_road_name(road["primary_name"])
    road["qc_dirty"] = True
    if road["status"] == "PUBLISHED":
        road["status"] = "VALIDATED"
    touch(road)
    pin_staleness_for_road(road)

    # ---- level 3: its non-terminal address points lose certified confidence ----
    points = calc.points_by_house_number(calc.road_points(road["id"], ("PENDING", "ACTIVE")))
    for point in points:
        point["confidence_basis"] = "PROVISIONAL"
        point["certified_confidence_score"] = None
        point["confidence_score"] = calc.confidence_score(point, "provisional")
        touch(point)
        pin_staleness_for_point(point)

    # ---- level 4: CERTIFIED reports covering any of those points ----
    decertified = []
    for report in sorted_rows(list(db.reports.values())):
        if report["status"] != "CERTIFIED":
            continue
        if not any(calc.report_covers_point(report, point) for point in points):
            continue
        report["status"] = "DECERTIFIED"
        report["decertified_reason"] = "SUBJECT_RECORD_CHANGED"
        touch(report)
        decertified.append(report["id"])

    # ---- level 5: DRAFT and SEALED packages on those reports ----
    if not decertified:
        return
    for package in sorted_rows(list(db.packages.values())):
        if package["qc_report_id"] not in decertified:
            continue
        if package["status"] not in ("DRAFT", "SEALED"):
            continue
        invalidate_package(package, "REPORT_DECERTIFIED")
