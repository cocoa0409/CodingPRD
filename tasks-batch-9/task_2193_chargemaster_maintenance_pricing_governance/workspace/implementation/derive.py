"""Derived fields, aggregates and the cascade chains of PRD 2.7 / 2.11."""

from calc import rhu_div, BP
from store import STORE


# ---------------------------------------------------------------------------
# Facility
# ---------------------------------------------------------------------------
def facility_items(facility_id):
    return [
        item
        for item in STORE.charge_items.values()
        if item["facility_id"] == facility_id
    ]


def derive_posture(facility):
    facility_id = facility["id"]
    for row in STORE.transparency_files.values():
        if row["facility_id"] == facility_id and row["status"] in ("BUILDING", "VALIDATED"):
            return "FROZEN"
    for row in STORE.code_update_cycles.values():
        if row["facility_id"] == facility_id and row["status"] in (
            "MAPPING",
            "CROSSWALK_APPROVED",
        ):
            return "RESTRICTED"
    if facility["stale_price_item_count"] >= 5:
        return "RESTRICTED"
    return "OPEN"


def recompute_facility_aggregates(facility):
    active_count = 0
    gross = 0
    cost = 0
    stale = 0
    for item in facility_items(facility["id"]):
        if item["lifecycle_status"] != "ACTIVE":
            continue
        active_count += 1
        gross += item["gross_charge_cents"]
        cost += item["cost_basis_cents"]
        if item["price_status"] == "PRICE_STALE":
            stale += 1
    facility["active_item_count"] = active_count
    facility["aggregate_gross_charge_cents"] = gross
    facility["aggregate_cost_basis_cents"] = cost
    facility["aggregate_markup_ratio_bp"] = 0 if cost == 0 else rhu_div(gross * BP, cost)
    facility["stale_price_item_count"] = stale


def recompute_facility(facility, bump=True):
    recompute_facility_aggregates(facility)
    facility["chargemaster_posture"] = derive_posture(facility)
    if facility.get("published_transparency_file_id") is None:
        facility["transparency_status"] = "NEEDS_REFRESH"
    if bump:
        STORE.touch(facility)


def supersede_published_files(facility, superseded_by_file_id=None):
    """PRD 2.11 — PUBLISHED files of the facility become SUPERSEDED."""
    touched = []
    for row in STORE.ordered(STORE.transparency_files):
        if row["facility_id"] != facility["id"]:
            continue
        if row["status"] != "PUBLISHED":
            continue
        row["status"] = "SUPERSEDED"
        row["superseded_by_file_id"] = superseded_by_file_id
        STORE.touch(row)
        touched.append(row)
    if touched or facility.get("published_transparency_file_id") is not None:
        facility["published_transparency_file_id"] = None
        facility["transparency_status"] = "NEEDS_REFRESH"
    return touched


def item_mutation_cascade(facility):
    """The chain of PRD 2.11 for a mutated ACTIVE charge item."""
    supersede_published_files(facility, None)
    facility["transparency_status"] = "NEEDS_REFRESH"
    recompute_facility(facility, bump=True)


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------
def recompute_department(department, bump=True):
    dept_id = department["id"]
    unresolved = 0
    recovered = 0
    for finding in STORE.findings.values():
        if finding["department_id"] != dept_id:
            continue
        if finding["status"] == "CONFIRMED":
            unresolved += finding["estimated_lost_charge_cents"]
        elif finding["status"] == "RESOLVED":
            recovered += finding["estimated_lost_charge_cents"]
    open_requests = 0
    for request in STORE.change_requests.values():
        if request["department_id"] != dept_id:
            continue
        if request["status"] in (
            "SUBMITTED",
            "UNDER_REVIEW",
            "CHANGES_REQUESTED",
            "APPROVED",
        ):
            open_requests += 1
    department["unresolved_finding_amount_cents"] = unresolved
    department["recovered_charge_cents"] = recovered
    department["open_request_count"] = open_requests
    department["capture_hold"] = unresolved >= 500000
    if bump:
        STORE.touch(department)


# ---------------------------------------------------------------------------
# CodeUpdateCycle / CodeUpdateEntry
# ---------------------------------------------------------------------------
def cycle_entries(cycle_id):
    return [
        entry
        for entry in STORE.ordered(STORE.code_update_entries)
        if entry["cycle_id"] == cycle_id
    ]


def recompute_cycle_counters(cycle, bump=True):
    entries = cycle_entries(cycle["id"])
    cycle["entry_count"] = len(entries)
    cycle["unmapped_entry_count"] = len([e for e in entries if e["status"] == "PENDING"])
    cycle["applied_entry_count"] = len([e for e in entries if e["status"] == "APPLIED"])
    if bump:
        STORE.touch(cycle)


# ---------------------------------------------------------------------------
# ChargeCaptureBatch
# ---------------------------------------------------------------------------
def recompute_batch_counters(batch, bump=True):
    lines = [
        line
        for line in STORE.captured_charges.values()
        if line["batch_id"] == batch["id"]
    ]
    batch["line_count"] = len(lines)
    batch["matched_line_count"] = len(
        [l for l in lines if l["match_status"] == "MATCHED"]
    )
    batch["exception_line_count"] = len(
        [
            l
            for l in lines
            if l["match_status"]
            in ("PRICE_VARIANCE", "UNKNOWN_CODE", "INACTIVE_ITEM", "DUPLICATE_LINE")
        ]
    )
    batch["total_expected_charge_cents"] = sum(
        (l["expected_charge_cents"] or 0)
        for l in lines
        if l["match_status"] != "UNKNOWN_CODE"
    )
    batch["total_posted_charge_cents"] = sum(l["posted_charge_cents"] for l in lines)
    batch["open_finding_count"] = len(
        [
            f
            for f in STORE.findings.values()
            if f["batch_id"] == batch["id"] and f["status"] == "OPEN"
        ]
    )
    if bump:
        STORE.touch(batch)


# ---------------------------------------------------------------------------
# PriceRule / PriceChangeImpactAnalysis
# ---------------------------------------------------------------------------
def price_rule_view(rule):
    rule["applied_item_count"] = len(
        [
            item
            for item in STORE.charge_items.values()
            if item.get("applied_price_rule_id") == rule["id"]
        ]
    )
    return rule


def stale_analyses_for_item(item_id):
    for analysis in STORE.ordered(STORE.analyses):
        if analysis["status"] != "COMPUTED":
            continue
        request = STORE.change_requests.get(analysis["change_request_id"])
        if request is None or request["charge_item_id"] != item_id:
            continue
        analysis["status"] = "STALE"
        STORE.touch(analysis)


def stale_analyses_for_request(request_id):
    for analysis in STORE.ordered(STORE.analyses):
        if analysis["status"] != "COMPUTED":
            continue
        if analysis["change_request_id"] != request_id:
            continue
        analysis["status"] = "STALE"
        STORE.touch(analysis)


def stale_analyses_for_facility(facility_id):
    for analysis in STORE.ordered(STORE.analyses):
        if analysis["status"] != "COMPUTED":
            continue
        request = STORE.change_requests.get(analysis["change_request_id"])
        if request is None:
            continue
        item = STORE.charge_items.get(request["charge_item_id"])
        if item is None or item["facility_id"] != facility_id:
            continue
        analysis["status"] = "STALE"
        STORE.touch(analysis)


# ---------------------------------------------------------------------------
# lookup helpers used by the existence ranks
# ---------------------------------------------------------------------------
def find_facility(facility_id, error_id="ERR_FACILITY_NOT_FOUND"):
    from errors import fail

    row = STORE.facilities.get(facility_id) if facility_id is not None else None
    if row is None:
        fail(error_id, "Facility %s does not exist." % facility_id)
    return row


def find(collection, row_id, error_id, label):
    from errors import fail

    row = collection.get(row_id) if row_id is not None else None
    if row is None:
        fail(error_id, "%s %s does not exist." % (label, row_id))
    return row
