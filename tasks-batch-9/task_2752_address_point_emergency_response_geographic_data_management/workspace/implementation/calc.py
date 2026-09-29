"""The thirteen declared calculations.

All score arithmetic runs through Decimal so that the normative rounding order
(clamp after summation, round once per category and once on the sum) is exact.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from store import db, sorted_rows

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
SERVICE_TYPES = ["LAW", "FIRE", "EMS"]
E911_FORWARD_HORIZON_DAYS = 30
BOUNDARY_STALE_WINDOW_DAYS = 30

ROAD_TYPE_ABBREVIATIONS = {
    "ST": "STREET",
    "RD": "ROAD",
    "AVE": "AVENUE",
    "DR": "DRIVE",
    "LN": "LANE",
    "HWY": "HIGHWAY",
    "CT": "COURT",
    "BLVD": "BOULEVARD",
}

BASE_BY_SOURCE = {"PARCEL": 70, "PERMIT": 60, "POSTAL": 45, "FIELD": 80}
GEOMETRY_VERIFIED_BONUS = 12
POSTAL_CITY_MATCH_BONUS = 8
BASE_ADDRESS_BONUS = 6
ROAD_STATUS_PENALTY = {"DRAFT": 15, "VALIDATED": 5, "PUBLISHED": 0}
FULL_COVERAGE_BONUS = 10
OPEN_DISCREPANCY_PENALTY = 20
SCORE_MIN = 0
SCORE_MAX = 100

LOW_CONFIDENCE_CUTOFF = 70
CATEGORY_WEIGHTS = {"ADDRESS": Decimal("0.45"), "ROAD": Decimal("0.30"),
                   "BOUNDARY": Decimal("0.25")}
SEVERITY_DEDUCTION = {"BLOCKING": Decimal("12.5"), "WARNING": Decimal("4.0"),
                      "INFO": Decimal("1.5")}
CATEGORY_SET = ["ADDRESS", "ROAD", "BOUNDARY"]
QUALITY_TIER_THRESHOLDS = [("A", Decimal("95")), ("B", Decimal("85")), ("C", Decimal("70"))]
WAIVER_PENALTY_BY_TIER = {"A": Decimal("1.0"), "B": Decimal("2.5"),
                          "C": Decimal("5.0"), "D": Decimal("8.0")}
PROVISIONING_MIN_SCORE = Decimal("90.00")

CHANNEL_CADENCE_DAYS = {"DISPATCH_E911": 7, "MAPPING": 14, "PUBLIC": 30}
MAX_PROPOSAL_ROUNDS = 3

DEFECT_SEVERITY = {
    "ADDRESS_MISSING_GEOMETRY": "BLOCKING",
    "ADDRESS_UNCOVERED_CELL": "BLOCKING",
    "ADDRESS_POSTAL_CITY_MISMATCH": "WARNING",
    "ADDRESS_UNIT_TYPE_MISSING": "WARNING",
    "ADDRESS_LOW_CONFIDENCE": "INFO",
    "ROAD_UNVALIDATED": "BLOCKING",
    "ROAD_RANGE_OVERLAP": "BLOCKING",
    "ROAD_NAME_NOT_NORMALIZED": "WARNING",
    "ROAD_QC_DIRTY": "WARNING",
    "ROAD_NO_ADDRESSES": "INFO",
    "BOUNDARY_COVERAGE_GAP": "BLOCKING",
    "PROPOSED_COVERAGE_OVERLAP": "WARNING",
    "BOUNDARY_STALE_WINDOW": "INFO",
}
DEFECT_CATEGORY = {
    "ADDRESS_MISSING_GEOMETRY": "ADDRESS",
    "ADDRESS_UNCOVERED_CELL": "ADDRESS",
    "ADDRESS_POSTAL_CITY_MISMATCH": "ADDRESS",
    "ADDRESS_UNIT_TYPE_MISSING": "ADDRESS",
    "ADDRESS_LOW_CONFIDENCE": "ADDRESS",
    "ROAD_UNVALIDATED": "ROAD",
    "ROAD_RANGE_OVERLAP": "ROAD",
    "ROAD_NAME_NOT_NORMALIZED": "ROAD",
    "ROAD_QC_DIRTY": "ROAD",
    "ROAD_NO_ADDRESSES": "ROAD",
    "BOUNDARY_COVERAGE_GAP": "BOUNDARY",
    "PROPOSED_COVERAGE_OVERLAP": "BOUNDARY",
    "BOUNDARY_STALE_WINDOW": "BOUNDARY",
}

MAX_DT = datetime(9999, 12, 31, 23, 59, 59, 999000, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# numeric helpers
# ---------------------------------------------------------------------------
def d(value):
    return Decimal(str(value))


def round2(value):
    """ROUND_HALF_UP to two decimal places, returned as a JSON number."""
    if not isinstance(value, Decimal):
        value = d(value)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round2d(value):
    if not isinstance(value, Decimal):
        value = d(value)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 1. normalized_road_name
# ---------------------------------------------------------------------------
def normalized_road_name(primary_name):
    upper = primary_name.upper()
    kept = re.sub(r"[^A-Z0-9 ]", "", upper)
    tokens = [t for t in kept.split(" ") if t != ""]
    if tokens:
        last = tokens[-1]
        if last in ROAD_TYPE_ABBREVIATIONS:
            tokens[-1] = ROAD_TYPE_ABBREVIATIONS[last]
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# 2. address_range_overlap_detection
# ---------------------------------------------------------------------------
def road_intervals(road):
    """The up-to-two closed parity-carrying intervals a centerline contributes."""
    out = []
    for side, low, high, parity in (
            ("LEFT", "from_addr_left", "to_addr_left", "parity_left"),
            ("RIGHT", "from_addr_right", "to_addr_right", "parity_right")):
        if road.get(low) is None or road.get(high) is None or road.get(parity) is None:
            continue
        out.append((side, road[low], road[high], road[parity]))
    return out


def intervals_conflict(a, b):
    """(a) same jurisdiction and (b) same normalized name are checked by caller."""
    if a[3] != b[3]:
        return False
    return max(a[1], b[1]) <= min(a[2], b[2])


def find_range_conflict(road, peer_statuses):
    """First conflicting (own_interval, peer, peer_interval) or None.

    Peers are examined in created_at order so the reported detail is stable.
    """
    for own in road_intervals(road):
        for peer in sorted_rows(list(db.roads.values())):
            if peer["id"] == road["id"]:
                continue
            if peer["status"] not in peer_statuses:
                continue
            if peer["jurisdiction_id"] != road["jurisdiction_id"]:
                continue
            if peer["normalized_name"] != road["normalized_name"]:
                continue
            for other in road_intervals(peer):
                if intervals_conflict(own, other):
                    return own, peer, other
    return None


def conflict_detail(own, other):
    return "%s range %d-%d %s overlaps %d-%d %s" % (
        own[0], own[1], own[2], own[3], other[1], other[2], other[3])


# ---------------------------------------------------------------------------
# 3. assignable_slot_count
# ---------------------------------------------------------------------------
def side_range(road, side):
    if side == "LEFT":
        return road.get("from_addr_left"), road.get("to_addr_left"), road.get("parity_left")
    return road.get("from_addr_right"), road.get("to_addr_right"), road.get("parity_right")


def assignable_slot_count(road, side):
    low, high, _parity = side_range(road, side)
    if low is None or high is None or high < low:
        return 0
    capacity = (high - low) // 2 + 1
    consumed = 0
    for point in db.points.values():
        if point["road_centerline_id"] != road["id"]:
            continue
        if point["side"] != side:
            continue
        if point["unit_id"] is not None:
            continue
        if point["status"] not in ("PENDING", "ACTIVE"):
            continue
        if low <= point["house_number"] <= high:
            consumed += 1
    return max(0, capacity - consumed)


# ---------------------------------------------------------------------------
# 4. address_point_confidence_score
# ---------------------------------------------------------------------------
def _confidence_raw(point, road):
    raw = BASE_BY_SOURCE.get(point["source"], 0)
    if point.get("geometry_verified"):
        raw += GEOMETRY_VERIFIED_BONUS
    jurisdiction = db.jurisdictions.get(point.get("jurisdiction_id"))
    if jurisdiction is not None and point.get("postal_city") == jurisdiction["postal_city"]:
        raw += POSTAL_CITY_MATCH_BONUS
    if point.get("unit_id") is None:
        raw += BASE_ADDRESS_BONUS
    if road is not None:
        raw -= ROAD_STATUS_PENALTY.get(road["status"], 0)
    return raw


def confidence_score(point, variant="provisional"):
    road = db.roads.get(point.get("road_centerline_id"))
    raw = _confidence_raw(point, road)
    if variant == "certified":
        cell = db.cells.get(point.get("cell_id"))
        if cell is not None and not cell_gap_service_types(cell["id"]):
            raw += FULL_COVERAGE_BONUS
        if road is not None and open_discrepancy_case_count(road["id"]) > 0:
            raw -= OPEN_DISCREPANCY_PENALTY
    clamped = max(SCORE_MIN, min(SCORE_MAX, raw))
    return round2(clamped)


# ---------------------------------------------------------------------------
# temporal window helpers
# ---------------------------------------------------------------------------
def window_end(value):
    return MAX_DT if value is None else value


def window_covers(row, instant):
    return row["effective_start"] <= instant < window_end(row["effective_end"])


def windows_intersect(a_start, a_end, b_start, b_end):
    return max(a_start, b_start) < min(window_end(a_end), window_end(b_end))


def window_contained(inner_start, inner_end, outer_start, outer_end):
    if inner_start < outer_start:
        return False
    return window_end(inner_end) <= window_end(outer_end)


# ---------------------------------------------------------------------------
# 9. coverage_integrity_counters
# ---------------------------------------------------------------------------
def cell_assignments(cell_id, service_type=None, statuses=None):
    rows = []
    for row in db.assignments.values():
        if row["cell_id"] != cell_id:
            continue
        if service_type is not None and row["service_type"] != service_type:
            continue
        if statuses is not None and row["status"] not in statuses:
            continue
        rows.append(row)
    return sorted_rows(rows)


def covering_set(cell_id, service_type, instant=None):
    if instant is None:
        instant = db.now()
    return [row for row in cell_assignments(cell_id, service_type, ("ACTIVE",))
            if window_covers(row, instant)]


def cell_gap_service_types(cell_id, instant=None):
    return [st for st in SERVICE_TYPES if len(covering_set(cell_id, st, instant)) == 0]


def cell_covered_service_types(cell_id, instant=None):
    return [st for st in SERVICE_TYPES if len(covering_set(cell_id, st, instant)) >= 1]


def cell_proposed_conflict_service_types(cell_id):
    out = []
    for st in SERVICE_TYPES:
        rows = cell_assignments(cell_id, st, ("PENDING", "ACTIVE"))
        found = False
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if a["status"] != "PENDING" and b["status"] != "PENDING":
                    continue
                if windows_intersect(a["effective_start"], a["effective_end"],
                                    b["effective_start"], b["effective_end"]):
                    found = True
                    break
            if found:
                break
        if found:
            out.append(st)
    return out


def cell_active_assignment_count(cell_id, instant=None):
    if instant is None:
        instant = db.now()
    total = 0
    for st in SERVICE_TYPES:
        total += len(covering_set(cell_id, st, instant))
    return total


def _merged_covers_horizon(rows, start, end):
    """True when the union of the rows' windows clipped to [start, end) is total."""
    clipped = []
    for row in rows:
        low = max(row["effective_start"], start)
        high = min(window_end(row["effective_end"]), end)
        if low < high:
            clipped.append((low, high))
    clipped.sort()
    cursor = start
    for low, high in clipped:
        if low > cursor:
            return False
        if high > cursor:
            cursor = high
        if cursor >= end:
            return True
    return cursor >= end


def cell_forward_gap_service_types(cell_id, instant=None):
    if instant is None:
        instant = db.now()
    horizon_end = instant + timedelta(days=E911_FORWARD_HORIZON_DAYS)
    out = []
    for st in SERVICE_TYPES:
        rows = cell_assignments(cell_id, st, ("ACTIVE",))
        if not _merged_covers_horizon(rows, instant, horizon_end):
            out.append(st)
    return out


def jurisdiction_cells(jurisdiction_id):
    return sorted_rows([c for c in db.cells.values()
                        if c["jurisdiction_id"] == jurisdiction_id])


def jurisdiction_counters(jurisdiction_id):
    cells = jurisdiction_cells(jurisdiction_id)
    cell_count = len(cells)
    covered = 0
    gaps = 0
    forward_gaps = 0
    for cell in cells:
        sizes = [len(covering_set(cell["id"], st)) for st in SERVICE_TYPES]
        gaps += sum(1 for size in sizes if size == 0)
        if all(size == 1 for size in sizes):
            covered += 1
        forward_gaps += len(cell_forward_gap_service_types(cell["id"]))
    return {
        "cell_count": cell_count,
        "covered_cell_count": covered,
        "gap_pair_count": gaps,
        "forward_gap_pair_count": forward_gaps,
    }


# ---------------------------------------------------------------------------
# derived counters used across modules
# ---------------------------------------------------------------------------
OPEN_CASE_STATUSES = ("OPEN", "PROPOSAL_PENDING", "COUNTERED", "ESCALATED")


def open_discrepancy_case_count(road_id):
    return sum(1 for case in db.cases.values()
               if case["subject_ref_id"] == road_id
               and case["subject_type"] in ("ROAD_NAME", "ADDRESS_RANGE")
               and case["status"] in OPEN_CASE_STATUSES)


def unit_child_count(point_id):
    return sum(1 for p in db.points.values()
               if p.get("parent_address_point_id") == point_id
               and p["status"] in ("PENDING", "ACTIVE"))


def assigned_cell_count(boundary_id):
    return sum(1 for a in db.assignments.values()
               if a["boundary_id"] == boundary_id
               and a["status"] in ("PENDING", "ACTIVE"))


def road_points(road_id, statuses=None):
    rows = [p for p in db.points.values() if p["road_centerline_id"] == road_id]
    if statuses is not None:
        rows = [p for p in rows if p["status"] in statuses]
    return sorted_rows(rows)


def points_by_house_number(rows):
    """CONFIDENCE_REFRESH / certification order: house_number ASC, created_at ASC."""
    return sorted(rows, key=lambda p: (p["house_number"], p["created_at"], p["_seq"]))


# ---------------------------------------------------------------------------
# 8. next_house_number_selection
# ---------------------------------------------------------------------------
def candidate_house_numbers(road, side):
    low, high, parity = side_range(road, side)
    if low is None or high is None or parity is None or high < low:
        return []
    taken = set()
    for point in db.points.values():
        if point["road_centerline_id"] != road["id"]:
            continue
        if point["side"] != side:
            continue
        if point["unit_id"] is not None:
            continue
        if point["status"] not in ("PENDING", "ACTIVE"):
            continue
        taken.add(point["house_number"])
    want = 0 if parity == "EVEN" else 1
    return [n for n in range(low, high + 1) if n % 2 == want and n not in taken]


# ---------------------------------------------------------------------------
# 6. qc_quality_score  /  7. provisioning_eligibility_score
# ---------------------------------------------------------------------------
def report_defects(report_id):
    return sorted_rows([x for x in db.defects.values() if x["report_id"] == report_id])


def quality_score(report_id, variant="strict"):
    defects = report_defects(report_id)
    total = Decimal("0")
    for category in CATEGORY_SET:
        deduction = Decimal("0")
        for defect in defects:
            if defect["defect_category"] != category:
                continue
            if variant == "strict":
                if defect["status"] != "OPEN":
                    continue
                deduction += SEVERITY_DEDUCTION[defect["severity"]]
            else:
                if defect["severity"] != "BLOCKING":
                    continue
                deduction += SEVERITY_DEDUCTION["BLOCKING"]
        category_score = Decimal("100") - deduction
        if category_score < 0:
            category_score = Decimal("0")
        total += round2d(CATEGORY_WEIGHTS[category] * category_score)
    return round2d(total)


def quality_tier(base):
    for tier, threshold in QUALITY_TIER_THRESHOLDS:
        if base >= threshold:
            return tier
    return "D"


def report_counts(report_id):
    defects = report_defects(report_id)
    return {
        "defect_count": len(defects),
        "blocking_defect_count": sum(1 for x in defects if x["severity"] == "BLOCKING"),
        "warning_defect_count": sum(1 for x in defects if x["severity"] == "WARNING"),
        "info_defect_count": sum(1 for x in defects if x["severity"] == "INFO"),
        "open_blocking_defect_count": sum(1 for x in defects
                                          if x["severity"] == "BLOCKING" and x["status"] == "OPEN"),
        "waived_blocking_count": sum(1 for x in defects
                                     if x["severity"] == "BLOCKING" and x["status"] == "WAIVED"),
    }


def report_scores(report_id):
    counts = report_counts(report_id)
    base = quality_score(report_id, "strict")
    advisory = quality_score(report_id, "advisory")
    tier = quality_tier(base)
    penalty = d(counts["waived_blocking_count"]) * WAIVER_PENALTY_BY_TIER[tier]
    eligibility = base - penalty
    if eligibility < 0:
        eligibility = Decimal("0")
    eligibility = round2d(eligibility)
    result = dict(counts)
    result["quality_score"] = float(base)
    result["advisory_quality_score"] = float(advisory)
    result["quality_tier"] = tier
    result["provisioning_eligibility_score"] = float(eligibility)
    result["is_provisioning_eligible"] = bool(
        eligibility >= PROVISIONING_MIN_SCORE and counts["open_blocking_defect_count"] == 0)
    return result


# ---------------------------------------------------------------------------
# 10. package_version_assignment  /  11. package_record_pin_set
# ---------------------------------------------------------------------------
def next_package_version(channel, jurisdiction_id):
    highest = 0
    for package in db.packages.values():
        if package["channel"] != channel:
            continue
        if package["jurisdiction_id"] != jurisdiction_id:
            continue
        if package.get("package_version") is None:
            continue
        if package["package_version"] > highest:
            highest = package["package_version"]
    return highest + 1


def package_scope_records(jurisdiction_id):
    """The in-scope record set as (record_type, record_id, live_version) triples."""
    out = []
    for point in db.points.values():
        if point["status"] != "ACTIVE":
            continue
        road = db.roads.get(point["road_centerline_id"])
        if road is None or road["jurisdiction_id"] != jurisdiction_id:
            continue
        out.append(("ADDRESS_POINT", point["id"], point["version"]))
    for road in db.roads.values():
        if road["status"] != "PUBLISHED":
            continue
        if road["jurisdiction_id"] != jurisdiction_id:
            continue
        out.append(("ROAD_CENTERLINE", road["id"], road["version"]))
    for boundary in db.boundaries.values():
        if boundary["status"] != "ACTIVE":
            continue
        holds = False
        for assignment in db.assignments.values():
            if assignment["boundary_id"] != boundary["id"]:
                continue
            if assignment["status"] != "ACTIVE":
                continue
            cell = db.cells.get(assignment["cell_id"])
            if cell is not None and cell["jurisdiction_id"] == jurisdiction_id:
                holds = True
                break
        if holds:
            out.append(("EMERGENCY_SERVICE_BOUNDARY", boundary["id"], boundary["version"]))
    out.sort(key=lambda row: (row[0], row[1]))
    return out


def package_records(package_id):
    return sorted_rows([r for r in db.package_records.values()
                        if r["package_id"] == package_id])


def package_pin_counts(package_id):
    rows = package_records(package_id)
    fresh = sum(1 for r in rows if r["pin_state"] == "FRESH")
    stale = sum(1 for r in rows if r["pin_state"] == "STALE")
    return {
        "record_count": len(rows),
        "pinned_record_count": len(rows),
        "fresh_pin_count": fresh,
        "stale_pin_count": stale,
        "drift_detected": stale > 0,
    }


def live_record_version(record_type, record_id):
    table = {"ADDRESS_POINT": db.points, "ROAD_CENTERLINE": db.roads,
             "EMERGENCY_SERVICE_BOUNDARY": db.boundaries}.get(record_type)
    if table is None:
        return None
    row = table.get(record_id)
    if row is None:
        return None
    return row["version"]


# ---------------------------------------------------------------------------
# 12. cadence_window_evaluation
# ---------------------------------------------------------------------------
def cadence_reference(channel, jurisdiction_id):
    best = None
    for package in db.packages.values():
        if package["channel"] != channel:
            continue
        if package["jurisdiction_id"] != jurisdiction_id:
            continue
        if package["status"] not in ("PUBLISHED", "SUPERSEDED", "ROLLED_BACK"):
            continue
        if package.get("published_at") is None:
            continue
        if best is None:
            best = package
            continue
        if package["published_at"] > best["published_at"]:
            best = package
        elif package["published_at"] == best["published_at"]:
            if (package["created_at"], package["_seq"]) < (best["created_at"], best["_seq"]):
                best = package
    return best


def cadence_window_open(channel, jurisdiction_id):
    reference = cadence_reference(channel, jurisdiction_id)
    if reference is None:
        return True
    elapsed_ms = (db.now() - reference["published_at"]).total_seconds() * 1000.0
    required_ms = CHANNEL_CADENCE_DAYS[channel] * 86400.0 * 1000.0
    return elapsed_ms >= required_ms


# ---------------------------------------------------------------------------
# 13. discrepancy_proposal_projection
# ---------------------------------------------------------------------------
def case_proposals(case_id):
    return sorted(
        [p for p in db.proposals.values() if p["case_id"] == case_id],
        key=lambda p: (p["round_number"], p["created_at"], p["_seq"]))


def case_round_count(case_id):
    return len(case_proposals(case_id))


def case_current_proposal(case_id):
    rows = case_proposals(case_id)
    if not rows:
        return None
    return rows[-1]


def proposal_status(proposal):
    case = db.cases.get(proposal["case_id"])
    if case is None:
        return "PENDING"
    current = case_current_proposal(case["id"])
    if case["status"] == "ADOPTED" and current is not None and current["id"] == proposal["id"]:
        return "ADOPTED"
    if case["status"] in ("ESCALATED", "ARBITRATED"):
        return "VOIDED"
    for other in case_proposals(case["id"]):
        if other["round_number"] > proposal["round_number"]:
            return "COUNTERED"
    return "PENDING"


# ---------------------------------------------------------------------------
# 5. qc_defect_scan
# ---------------------------------------------------------------------------
def report_scope_roads(scope, jurisdiction_id, road_centerline_id):
    if scope == "ROAD":
        road = db.roads.get(road_centerline_id)
        return [road] if road is not None else []
    if scope == "JURISDICTION":
        return sorted_rows([r for r in db.roads.values()
                            if r["jurisdiction_id"] == jurisdiction_id])
    return sorted_rows(list(db.roads.values()))


def report_scope_points(scope, jurisdiction_id, road_centerline_id):
    roads = report_scope_roads(scope, jurisdiction_id, road_centerline_id)
    road_ids = set(r["id"] for r in roads)
    rows = [p for p in db.points.values()
            if p["road_centerline_id"] in road_ids and p["status"] in ("PENDING", "ACTIVE")]
    return sorted_rows(rows)


def report_covers_point(report, point):
    if report["scope"] == "FULL":
        return True
    if report["scope"] == "ROAD":
        return point["road_centerline_id"] == report["road_centerline_id"]
    road = db.roads.get(point["road_centerline_id"])
    return road is not None and road["jurisdiction_id"] == report["jurisdiction_id"]


def _candidate(code, entity_type, entity_ref_id, detail, subject):
    return {
        "defect_code": code,
        "severity": DEFECT_SEVERITY[code],
        "defect_category": DEFECT_CATEGORY[code],
        "entity_type": entity_type,
        "entity_ref_id": entity_ref_id,
        "detail": detail,
        "_subject_created_at": subject["created_at"],
        "_subject_seq": subject["_seq"],
    }


def qc_defect_scan(scope, jurisdiction_id, road_centerline_id):
    """Return the defect payloads to create, in the declared creation order."""
    now = db.now()
    candidates = []
    roads = report_scope_roads(scope, jurisdiction_id, road_centerline_id)

    for road in roads:
        if road["status"] == "DRAFT":
            candidates.append(_candidate(
                "ROAD_UNVALIDATED", "ROAD_CENTERLINE", road["id"],
                "Centerline %s is still DRAFT and has not been validated." % road["primary_name"],
                road))
        conflict = find_range_conflict(road, ("DRAFT", "VALIDATED", "PUBLISHED"))
        if conflict is not None:
            own, _peer, other = conflict
            candidates.append(_candidate(
                "ROAD_RANGE_OVERLAP", "ROAD_CENTERLINE", road["id"],
                conflict_detail(own, other), road))
        if road["primary_name"] != road["normalized_name"]:
            candidates.append(_candidate(
                "ROAD_NAME_NOT_NORMALIZED", "ROAD_CENTERLINE", road["id"],
                "primary_name '%s' differs from normalized_name '%s'." % (
                    road["primary_name"], road["normalized_name"]),
                road))
        if road.get("qc_dirty"):
            candidates.append(_candidate(
                "ROAD_QC_DIRTY", "ROAD_CENTERLINE", road["id"],
                "Centerline %s is flagged qc_dirty." % road["primary_name"], road))
        if not road_points(road["id"], ("PENDING", "ACTIVE")):
            candidates.append(_candidate(
                "ROAD_NO_ADDRESSES", "ROAD_CENTERLINE", road["id"],
                "Centerline %s carries no non-terminal address points." % road["primary_name"],
                road))

    for point in report_scope_points(scope, jurisdiction_id, road_centerline_id):
        if not point.get("geometry_verified"):
            candidates.append(_candidate(
                "ADDRESS_MISSING_GEOMETRY", "ADDRESS_POINT", point["id"],
                "Address point %d has unverified geometry." % point["house_number"], point))
        if scope == "JURISDICTION" and point["status"] == "ACTIVE":
            cell = db.cells.get(point.get("cell_id"))
            if cell is not None:
                gaps = cell_gap_service_types(cell["id"], now)
                if gaps:
                    candidates.append(_candidate(
                        "ADDRESS_UNCOVERED_CELL", "ADDRESS_POINT", point["id"],
                        "Cell %s has uncovered service types: %s." % (
                            cell["cell_code"], ", ".join(gaps)), point))
        jurisdiction = db.jurisdictions.get(point.get("jurisdiction_id"))
        if jurisdiction is not None and point.get("postal_city") != jurisdiction["postal_city"]:
            candidates.append(_candidate(
                "ADDRESS_POSTAL_CITY_MISMATCH", "ADDRESS_POINT", point["id"],
                "postal_city '%s' differs from jurisdiction postal city '%s'." % (
                    point.get("postal_city"), jurisdiction["postal_city"]), point))
        if point.get("unit_id") is not None and point.get("unit_type") is None:
            candidates.append(_candidate(
                "ADDRESS_UNIT_TYPE_MISSING", "ADDRESS_POINT", point["id"],
                "unit_id '%s' carries no unit_type." % point["unit_id"], point))
        if point.get("confidence_score") is not None \
                and d(point["confidence_score"]) < d(LOW_CONFIDENCE_CUTOFF):
            candidates.append(_candidate(
                "ADDRESS_LOW_CONFIDENCE", "ADDRESS_POINT", point["id"],
                "confidence_score %.2f is below %d." % (
                    point["confidence_score"], LOW_CONFIDENCE_CUTOFF), point))

    if scope == "JURISDICTION":
        cells = jurisdiction_cells(jurisdiction_id)
        for cell in cells:
            for service_type in SERVICE_TYPES:
                if len(covering_set(cell["id"], service_type, now)) == 0:
                    candidates.append(_candidate(
                        "BOUNDARY_COVERAGE_GAP", "COVERAGE_CELL", cell["id"],
                        "Cell %s has no ACTIVE %s coverage at the current instant." % (
                            cell["cell_code"], service_type), cell))
        for cell in cells:
            for service_type in cell_proposed_conflict_service_types(cell["id"]):
                candidates.append(_candidate(
                    "PROPOSED_COVERAGE_OVERLAP", "COVERAGE_CELL", cell["id"],
                    "Cell %s has intersecting %s claims with at least one PENDING." % (
                        cell["cell_code"], service_type), cell))
        horizon_end = now + timedelta(days=BOUNDARY_STALE_WINDOW_DAYS)
        cell_ids = set(c["id"] for c in cells)
        for assignment in sorted_rows(list(db.assignments.values())):
            if assignment["status"] != "ACTIVE":
                continue
            if assignment["cell_id"] not in cell_ids:
                continue
            end = assignment.get("effective_end")
            if end is None:
                continue
            if now <= end < horizon_end:
                candidates.append(_candidate(
                    "BOUNDARY_STALE_WINDOW", "COVERAGE_CELL", assignment["cell_id"],
                    "%s claim window closes inside the %d-day horizon." % (
                        assignment["service_type"], BOUNDARY_STALE_WINDOW_DAYS),
                    assignment))

    candidates.sort(key=lambda c: (c["defect_code"], c["entity_type"],
                                   c["_subject_created_at"]))
    return candidates
