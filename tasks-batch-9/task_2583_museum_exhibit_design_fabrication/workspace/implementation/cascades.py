"""Cascade chains (PRD §2.10, §3.2, §3.3, §3.5, §3.6, §3.7).

Every cascade processes its set in a stated deterministic order and touches
every row it disturbs.
"""

from store import db, order_created
import helpers
from helpers import touch

WINDOW_DENIAL_REASON_DESIGN_REVISION = "DESIGN_REVISION_REOPENED"
DRAWING_VOID_REASON_MATERIAL_REJECTED = "MATERIAL_SPEC_REJECTED"


# --- review cascade link four: install-window denials (PRD §3.3) ---------
def deny_requested_windows(project):
    """Every window of the project still REQUESTED becomes DENIED."""
    targets = [w for w in helpers.rows_of_project(db.windows, project["id"])
               if w["status"] == "REQUESTED"]
    for window in targets:
        window["status"] = "DENIED"
        window["denial_reason"] = WINDOW_DENIAL_REASON_DESIGN_REVISION
        touch(window)


# --- review cascade link three: the phase revert (PRD §3.1) -------------
def revert_phase_for_revision(project, package):
    if package["stage"] == "SCHEMATIC" and project["phase"] == "DESIGN_DEV":
        project["phase"] = "SCHEMATIC"
        deny_requested_windows(project)
    elif package["stage"] == "DESIGN_DEV" and project["phase"] == "FABRICATION":
        project["phase"] = "DESIGN_DEV"
        deny_requested_windows(project)


# --- review cascade link two: package -> REVISION_REQUESTED (PRD §3.3) --
def package_to_revision_requested(package):
    project = helpers.owning_project(package)
    package["status"] = "REVISION_REQUESTED"
    package["revision_count"] = package["revision_count"] + 1
    touch(package)
    revert_phase_for_revision(project, package)
    touch(project)


def package_to_approved(package):
    project = helpers.owning_project(package)
    package["status"] = "APPROVED"
    package["approved_at"] = db.now()
    touch(package)
    touch(project)


# --- supersession (PRD §3.2) --------------------------------------------
def supersede_same_stage_packages(project, new_package):
    """Every non-SUPERSEDED package of the same stage, ascending created_at."""
    victims = [p for p in helpers.packages_of_project(project["id"])
               if p["id"] != new_package["id"]
               and p["stage"] == new_package["stage"]
               and p["status"] != "SUPERSEDED"]
    victims.sort(key=order_created)
    for package in victims:
        package["status"] = "SUPERSEDED"
        package["superseded_by_package_id"] = new_package["id"]
        for review_round in helpers.rounds_of_package(package["id"]):
            if review_round["status"] == "OPEN":
                review_round["status"] = "CLOSED_SUPERSEDED"
                review_round["decided_at"] = db.now()
                touch(review_round)
        touch(package)


# --- case revert / object release (PRD §3.5, §3.6 links three and four) --
def release_reserved_objects(case):
    """Every RESERVED object in the case returns to UNPLACED, ascending created_at."""
    for artifact in helpers.artifacts_assigned_to_case(case["id"]):
        if artifact["placement_status"] == "RESERVED":
            artifact["placement_status"] = "UNPLACED"
            artifact["assigned_case_id"] = None
            touch(artifact)


def revert_case_to_draft(case):
    """APPROVED / CONDITIONALLY_APPROVED case falls back to DRAFT, giving up its slot."""
    case["status"] = "DRAFT"
    case["conditions"] = None
    if case["mount_status"] == "MOUNT_FABRICATED":
        case["mount_status"] = "MOUNT_DESIGN"
    release_reserved_objects(case)
    zone = db.zones.get(case["zone_id"], None)
    if zone is not None:
        # reserved_case_slots falls by one, available_case_slots rises by one
        touch(zone)
    touch(case)


# --- drawing void (PRD §3.7, and §3.6 links one to four) ----------------
def void_drawing(drawing, void_reason, revert_case=True):
    """Void a sheet.

    ``revert_case`` is False for the direct void of a sheet still in SUBMITTED or
    UNDER_REVIEW: §3.7 says such a void "moves no money and reverts no case".  The
    material-rejection cascade of §3.6 link three reverts the subject case of every
    voided sheet, so it keeps the default.
    """
    project = helpers.owning_project(drawing)
    committed = drawing["actual_cost_cents"]
    drawing["status"] = "VOID"
    drawing["void_reason"] = void_reason
    touch(drawing)
    if committed is not None:
        # A reversal, not a recomputation: exactly the amount the approval committed.
        project["committed_fabrication_cents"] = project["committed_fabrication_cents"] - committed
    if revert_case and drawing["subject_case_id"] is not None:
        case = db.cases.get(drawing["subject_case_id"], None)
        if case is not None and case["status"] in ("APPROVED", "CONDITIONALLY_APPROVED"):
            revert_case_to_draft(case)
    touch(project)


def material_rejection_cascade(material):
    """Link one: every sheet built from this material that is not VOID or REJECTED."""
    targets = [d for d in helpers.drawings_of_material(material["id"])
               if d["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "APPROVED_AS_NOTED")]
    for drawing in targets:
        void_drawing(drawing, DRAWING_VOID_REASON_MATERIAL_REJECTED)


# --- deadline sweep (PRD §3.3) ------------------------------------------
def review_sweep(project):
    """Lapse every OPEN round whose deadline is at or before the logical clock."""
    now = db.now()
    lapsed = [r for r in helpers.rounds_of_project(project["id"])
              if r["status"] == "OPEN" and r["decision_deadline_at"] <= now]
    lapsed.sort(key=lambda r: (r["decision_deadline_at"], r["created_at"], r["_seq"]))
    for review_round in lapsed:
        review_round["status"] = "REVISION_REQUESTED"
        review_round["swept_by_deadline"] = True
        review_round["decided_at"] = now
        touch(review_round)
        package = db.packages.get(review_round["package_id"], None)
        if package is not None and package["status"] == "IN_REVIEW":
            package_to_revision_requested(package)
    touch(project)
    return lapsed
