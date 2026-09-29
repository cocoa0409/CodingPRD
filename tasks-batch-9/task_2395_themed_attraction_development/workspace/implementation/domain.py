"""Lookups, child indexes, roll-up recomputation and the posture cascade."""

from decimal import Decimal

import calc
import store
from errors import ApiError

LADDER = (
    "BLUE_SKY",
    "CONCEPT",
    "SCHEMATIC",
    "DESIGN_DEVELOPMENT",
    "PRODUCTION",
    "INSTALLATION",
    "TECHNICAL_REHEARSAL",
    "SOFT_OPEN",
    "OPERATIONS_HANDOVER",
)

HOLDABLE_STATUSES = ("SEQUENCED", "PROGRAMMED", "VALIDATED")


def successor(phase):
    index = LADDER.index(phase)
    if index + 1 >= len(LADDER):
        return None
    return LADDER[index + 1]


# ------------------------------------------------------------------- lookups
def _find(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id, 404)
    return row


def get_project(project_id):
    return _find(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")


def get_ride_system(row_id):
    return _find(store.ride_systems, row_id, "ERR_RIDE_SYSTEM_NOT_FOUND")


def get_queue_segment(row_id):
    return _find(store.queue_segments, row_id, "ERR_QUEUE_SEGMENT_NOT_FOUND")


def get_scene(row_id):
    return _find(store.show_scenes, row_id, "ERR_SCENE_NOT_FOUND")


def get_cue(row_id):
    return _find(store.effect_cues, row_id, "ERR_CUE_NOT_FOUND")


def get_package(row_id):
    return _find(store.design_packages, row_id, "ERR_PACKAGE_NOT_FOUND")


def get_review(row_id):
    return _find(store.safety_reviews, row_id, "ERR_REVIEW_NOT_FOUND")


def get_finding(row_id):
    return _find(store.safety_findings, row_id, "ERR_FINDING_NOT_FOUND")


def get_ve_item(row_id):
    return _find(store.ve_items, row_id, "ERR_VE_ITEM_NOT_FOUND")


def get_rehearsal_run(row_id):
    return _find(store.rehearsal_runs, row_id, "ERR_REHEARSAL_RUN_NOT_FOUND")


def get_maintenance_item(row_id):
    return _find(store.maintenance_items, row_id, "ERR_MAINTENANCE_ITEM_NOT_FOUND")


def get_ledger_entry(row_id):
    return _find(store.ledger_entries, row_id, "ERR_LEDGER_ENTRY_NOT_FOUND")


# ------------------------------------------------------------- child indexes
def _children(collection, key, value):
    return store.sorted_rows([r for r in collection.values() if r.get(key) == value])


def ride_systems_of(project_id):
    return _children(store.ride_systems, "project_id", project_id)


def segments_of(project_id):
    return _children(store.queue_segments, "project_id", project_id)


def scenes_of(project_id):
    return _children(store.show_scenes, "project_id", project_id)


def cues_of_scene(scene_id):
    return _children(store.effect_cues, "scene_id", scene_id)


def packages_of(project_id):
    return _children(store.design_packages, "project_id", project_id)


def reviews_of_package(package_id):
    return _children(store.safety_reviews, "design_package_id", package_id)


def findings_of_review(review_id):
    return _children(store.safety_findings, "safety_review_id", review_id)


def ve_items_of(project_id):
    return _children(store.ve_items, "project_id", project_id)


def ballots_of(item_id):
    return _children(store.ve_ballots, "value_engineering_item_id", item_id)


def runs_of(project_id):
    return _children(store.rehearsal_runs, "project_id", project_id)


def maintenance_of(project_id):
    return _children(store.maintenance_items, "project_id", project_id)


def ledger_of(project_id):
    """Chronological replay order: created_at ASC, then sequence_no ASC."""
    rows = [r for r in store.ledger_entries.values() if r.get("project_id") == project_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["sequence_no"]))


def reviews_of_project(project_id):
    out = []
    for package in packages_of(project_id):
        out.extend(reviews_of_package(package["id"]))
    return store.sorted_rows(out)


def findings_of_project(project_id):
    out = []
    for review in reviews_of_project(project_id):
        out.extend(findings_of_review(review["id"]))
    return store.sorted_rows(out)


def project_of_review(review):
    package = store.design_packages.get(review["design_package_id"])
    if package is None:
        return None
    return store.projects.get(package["project_id"])


def project_of_finding(finding):
    review = store.safety_reviews.get(finding["safety_review_id"])
    if review is None:
        return None
    return project_of_review(review)


def selected_ride_system(project):
    row_id = project.get("selected_ride_system_id")
    if not row_id:
        return None
    return store.ride_systems.get(row_id)


# ----------------------------------------------------------------- gate helpers
def check_not_frozen(project):
    if project["readiness_posture"] == "FROZEN":
        raise ApiError("ERR_PROJECT_FROZEN", 409)


def check_not_restricted(project):
    if project["readiness_posture"] == "RESTRICTED":
        raise ApiError("ERR_POSTURE_RESTRICTED", 409)


def check_phase_in(project, allowed):
    if project["design_phase"] not in allowed:
        raise ApiError("ERR_PROJECT_PHASE_INVALID", 409)


# --------------------------------------------------------------- recomputation
def recompute_required_capacity(project):
    project["required_hourly_capacity_guests"] = calc.required_hourly_capacity(
        project["design_day_attendance"], project["peak_hour_share"]
    )


def recompute_selected_ride_system(project):
    picked = None
    for row in ride_systems_of(project["id"]):
        if row["status"] in ("SELECTED", "ENGINEERED", "COMMISSIONED"):
            picked = row
    project["selected_ride_system_id"] = picked["id"] if picked else None


def recompute_queue_total(project):
    total = 0
    for segment in segments_of(project["id"]):
        if segment["status"] == "ACCEPTED":
            total += segment["capacity_guests"]
    project["queue_capacity_total_guests"] = total


def queue_position(project):
    total = 0
    accessible = 0
    for segment in segments_of(project["id"]):
        if segment["status"] != "ACCEPTED":
            continue
        total += segment["capacity_guests"]
        if segment["routing_type"] == "ACCESSIBLE":
            accessible += segment["capacity_guests"]
    system = selected_ride_system(project)
    operational = system["operational_hourly_capacity_guests"] if system else 0
    return {
        "queue_capacity_total_guests": total,
        "accessible_capacity_guests": accessible,
        "accessible_share_pct": calc.accessible_share_pct(accessible, total),
        "virtual_queue_allocation_guests": calc.virtual_queue_allocation(
            total, project["virtual_queue_share_pct"]
        ),
        "posted_wait_minutes": calc.posted_wait_minutes(total, operational),
    }


def compute_show_quality(project):
    return calc.project_show_quality(scenes_of(project["id"]))


def recompute_show_quality(project):
    project["show_quality_score"] = compute_show_quality(project)


def recompute_finding_counters(project):
    critical = 0
    major = 0
    for finding in findings_of_project(project["id"]):
        if finding["status"] not in ("OPEN", "RESOLVED"):
            continue
        if finding["severity"] == "CRITICAL":
            critical += 1
        elif finding["severity"] == "MAJOR":
            major += 1
    project["open_critical_finding_count"] = critical
    project["open_major_finding_count"] = major


def committed_cost(project):
    running = 0
    for entry in ledger_of(project["id"]):
        running += entry["amount_cents"]
    return running


def forecast_cost(project, committed):
    in_flight = 0
    for item in ve_items_of(project["id"]):
        if item["status"] == "UNDER_REVIEW" and item["net_saving_cents"] is not None:
            in_flight += item["net_saving_cents"]
    remediation = 0
    for finding in findings_of_project(project["id"]):
        if finding["status"] in ("OPEN", "RESOLVED"):
            remediation += finding["remediation_cost_estimate_cents"]
    return committed - in_flight + remediation


def recompute_budget(project):
    committed = committed_cost(project)
    project["committed_cost_cents"] = committed
    project["forecast_cost_cents"] = forecast_cost(project, committed)


def ve_program_net_savings(project):
    total = 0
    for item in ve_items_of(project["id"]):
        if item["status"] == "ADOPTED" and item["net_saving_cents"] is not None:
            total += item["net_saving_cents"]
    return total


# ------------------------------------------------------------ posture cascade
def _freeze_scenes(project):
    reason = "SAFETY_FREEZE" if project["open_critical_finding_count"] > 0 else "BUDGET_FREEZE"
    for scene in scenes_of(project["id"]):
        if scene["status"] in HOLDABLE_STATUSES:
            scene["held_from_status"] = scene["status"]
            scene["hold_reason"] = reason
            scene["status"] = "HELD"
            store.touch(scene)


def _release_scenes(project):
    for scene in scenes_of(project["id"]):
        if scene["status"] == "HELD":
            scene["status"] = scene["held_from_status"] or "SEQUENCED"
            scene["held_from_status"] = None
            scene["hold_reason"] = None
            store.touch(scene)


def recompute_posture(project):
    previous = project["readiness_posture"]
    current = calc.posture_for(
        project["open_critical_finding_count"],
        project["open_major_finding_count"],
        project["committed_cost_cents"],
        project["budget_ceiling_cents"],
    )
    project["readiness_posture"] = current
    if current == "FROZEN" and previous != "FROZEN":
        _freeze_scenes(project)
        recompute_show_quality(project)
    elif previous == "FROZEN" and current != "FROZEN":
        _release_scenes(project)
        recompute_show_quality(project)


def refresh_project_exposure(project):
    """Recompute the finding counters, both budget bases and the posture gate."""
    recompute_finding_counters(project)
    recompute_budget(project)
    recompute_posture(project)


# ---------------------------------------------------------------- ledger minting
def mint_ledger_entry(project, entry_kind, amount_cents, memo, reversal_of_sequence_no=None):
    project["ledger_sequence_high_water"] = project["ledger_sequence_high_water"] + 1
    entry = store.base_row(with_audit=False)
    entry["project_id"] = project["id"]
    entry["entry_kind"] = entry_kind
    entry["amount_cents"] = amount_cents
    entry["memo"] = memo
    entry["sequence_no"] = project["ledger_sequence_high_water"]
    entry["reversed"] = False
    entry["reversal_of_sequence_no"] = reversal_of_sequence_no
    store.ledger_entries[entry["id"]] = entry
    return entry


# ------------------------------------------------------------------ pagination
def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset : offset + limit]
    return store.public_list(window), total


def restricted_utilisation(project):
    return calc.restricted_utilisation_cents(project["budget_ceiling_cents"])


def has_cleared_review(project, ride_system_id=None):
    """A CLEARED review against an APPROVED package (optionally of one ride system)."""
    for package in packages_of(project["id"]):
        if package["status"] != "APPROVED":
            continue
        if ride_system_id is not None and package["ride_system_id"] != ride_system_id:
            continue
        for review in reviews_of_package(package["id"]):
            if review["status"] == "CLEARED":
                return True
    return False


def scene_chain_has_cycle(scene_id, predecessor_id):
    """Walking follows_scene_id forward from the predecessor must not reach scene_id."""
    if not predecessor_id:
        return False
    if predecessor_id == scene_id:
        return True
    seen = set()
    cursor = predecessor_id
    while cursor:
        if cursor == scene_id:
            return True
        if cursor in seen:
            return False
        seen.add(cursor)
        row = store.show_scenes.get(cursor)
        if row is None:
            return False
        cursor = row.get("follows_scene_id")
    return False


def decimal_or_zero(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))
