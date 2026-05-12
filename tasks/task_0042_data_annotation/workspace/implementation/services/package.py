"""TaskPackage state machine: claim/dispatch, submit, inspection, arbitration."""

from __future__ import annotations

from datetime import timedelta

import db
from errors import (
    AppError, raise_error,
    ERR_PROJECT_NOT_OPEN,
    ERR_PACKAGE_STATE_INVALID,
    ERR_ANNOTATOR_SUSPENDED,
    ERR_TIER_INSUFFICIENT,
    ERR_GRAB_NOT_ALLOWED,
    ERR_DISPATCH_NOT_ALLOWED,
    ERR_PACKAGE_ALREADY_TAKEN,
    ERR_NOT_PACKAGE_OWNER,
    ERR_LABEL_COUNT_MISMATCH,
    ERR_PACKAGE_TIMED_OUT,
    ERR_DEFECTS_OUT_OF_RANGE,
    ERR_INSPECTION_LOCKED_BY_APPEAL,
    ERR_ARBITER_IS_OWNER,
    ERR_NO_ELIGIBLE_ARBITER,
    ERR_INVALID_PARAMETER,
)
from config import MAX_REWORK_ROUNDS, TIER_RANK
from services import calculations as calc
from services.audit import write_audit, queue_event
from services.annotator import (
    update_after_inspection_outcome,
    apply_suspension_cascade,
    push_dispute_history,
    trailing_rejected_appeals,
    tier_rank,
)
from services.ledger import add_entry as add_ledger_entry


# --- helpers --------------------------------------------------------------

def _audit_package_status(pkg_id: str, prev: str, new: str, system: bool = False):
    write_audit(
        subject_kind="TASK_PACKAGE",
        subject_id=pkg_id,
        event_type="STATUS_CHANGE",
        from_value=prev,
        to_value=new,
        system=system,
    )


def _ensure_project_open(project: dict):
    if project.get("status") != "OPEN":
        raise_error(ERR_PROJECT_NOT_OPEN, "Project is not OPEN.")


def _initial_tier_required(difficulty: str) -> str:
    return {"EASY": "JUNIOR", "MEDIUM": "SENIOR", "HARD": "EXPERT"}[difficulty]


def initial_tier_required(difficulty: str) -> str:
    return _initial_tier_required(difficulty)


# --- Claim / dispatch -----------------------------------------------------

def _claim_or_dispatch(pkg: dict, project: dict, annotator: dict, *, mode: str):
    # Priority 4: project state
    _ensure_project_open(project)

    # Priority 5: package state
    if pkg.get("status") != "POOL":
        # If already assigned, surface ALREADY_TAKEN; else generic invalid state.
        if pkg.get("assigned_annotator_id"):
            raise_error(ERR_PACKAGE_ALREADY_TAKEN,
                        "Package was already claimed/dispatched.")
        raise_error(ERR_PACKAGE_STATE_INVALID,
                    f"Package is not in POOL state (currently {pkg.get('status')}).")

    # Priority 6: annotator suspension
    if annotator.get("status") != "ACTIVE":
        raise_error(ERR_ANNOTATOR_SUSPENDED, "Annotator is suspended.")

    # Priority 7: tier sufficiency
    required = pkg.get("tier_required") or _initial_tier_required(project["difficulty"])
    if tier_rank(annotator["tier"]) < tier_rank(required):
        raise_error(ERR_TIER_INSUFFICIENT,
                    f"Annotator tier {annotator['tier']} below required {required}.")

    # Priority 8: distribution mode
    dmode = project["distribution_mode"]
    if mode == "claim" and dmode not in {"GRAB", "HYBRID"}:
        raise_error(ERR_GRAB_NOT_ALLOWED,
                    f"Distribution mode {dmode} does not allow claim.")
    if mode == "dispatch" and dmode not in {"DISPATCH", "HYBRID"}:
        raise_error(ERR_DISPATCH_NOT_ALLOWED,
                    f"Distribution mode {dmode} does not allow dispatch.")

    # Priority 20: package occupancy double-check (race)
    if pkg.get("assigned_annotator_id"):
        raise_error(ERR_PACKAGE_ALREADY_TAKEN, "Package was already taken.")

    # Commit POOL → IN_PROGRESS
    claimed_at_dt = db.now_dt()
    deadline_dt = claimed_at_dt + timedelta(seconds=project["timeout_seconds"])

    # Insert golden samples into the package: take floor(item_count*0.05) entries
    # from the project's GoldenSample pool.
    item_count = pkg["item_count"]
    g_count = calc.golden_inserted_count(item_count)
    project_goldens = db.find_many("golden_samples", project_id=project["id"])
    project_goldens = sorted(project_goldens, key=lambda r: r["created_at"])
    take = project_goldens[:g_count]
    # Deterministically pick item-level positions: first g_count items (0..g_count-1).
    golden_positions = list(range(min(g_count, item_count)))

    db.update("task_packages", pkg["id"], {
        "status": "IN_PROGRESS",
        "assigned_annotator_id": annotator["id"],
        "claimed_at": db.format_ts(claimed_at_dt),
        "deadline_at": db.format_ts(deadline_dt),
        "golden_inserted_count": g_count,
        "golden_positions": golden_positions,
        "golden_sample_ids": [g["id"] for g in take],
    })
    _audit_package_status(pkg["id"], "POOL", "IN_PROGRESS")
    return db.find_by_id("task_packages", pkg["id"])


def claim_package(pkg: dict, project: dict, annotator: dict):
    return _claim_or_dispatch(pkg, project, annotator, mode="claim")


def dispatch_package(pkg: dict, project: dict, annotator: dict):
    return _claim_or_dispatch(pkg, project, annotator, mode="dispatch")


# --- Submit ---------------------------------------------------------------

def submit_labels(pkg: dict, project: dict, annotator: dict, labels):
    if annotator.get("status") != "ACTIVE":
        raise_error(ERR_ANNOTATOR_SUSPENDED, "Annotator is suspended.")
    if pkg.get("status") != "IN_PROGRESS":
        raise_error(ERR_PACKAGE_STATE_INVALID, "Package not in IN_PROGRESS.")
    if pkg.get("assigned_annotator_id") != annotator["id"]:
        raise_error(ERR_NOT_PACKAGE_OWNER, "Acting annotator does not own the package.")

    # Deadline check (priority 10)
    deadline_str = pkg.get("deadline_at")
    if deadline_str:
        deadline_dt = db.parse_iso(deadline_str)
        if db.now_dt() >= deadline_dt:
            raise_error(ERR_PACKAGE_TIMED_OUT, "Package deadline has passed.")

    if not isinstance(labels, list):
        raise_error(ERR_LABEL_COUNT_MISMATCH, "labels must be an array.")
    if len(labels) != pkg["item_count"]:
        raise_error(ERR_LABEL_COUNT_MISMATCH,
                    f"labels.length {len(labels)} != item_count {pkg['item_count']}.")

    # Compute golden_correct / golden_total.
    golden_positions = pkg.get("golden_positions") or []
    golden_ids = pkg.get("golden_sample_ids") or []
    expected = []
    for gid in golden_ids:
        g = db.find_by_id("golden_samples", gid)
        expected.append(g["expected_label"] if g else None)
    g_correct = calc.golden_correct_count(labels, golden_positions, expected)
    g_total = pkg.get("golden_inserted_count", 0)

    submission = db.insert(
        "submissions",
        {
            "package_id": pkg["id"],
            "annotator_id": annotator["id"],
            "rework_round": pkg.get("rework_round", 0),
            "labels": list(labels),
            "golden_correct": g_correct,
            "golden_total": g_total,
        },
        with_version=False,
    )

    # If 2+ submissions exist, compute consistency between the two most recent
    # submissions (different annotators across rework rounds). Persist on package.
    subs = sorted(db.find_many("submissions", package_id=pkg["id"]),
                  key=lambda s: s["created_at"])
    if len(subs) >= 2:
        score = calc.consistency_score(project["task_type"],
                                       subs[-2]["labels"], subs[-1]["labels"])
        db.update("task_packages", pkg["id"], {"consistency_score": score})

    # Bump package counters for its own audit; status moves to SUBMITTED.
    prev = pkg["status"]
    db.update("task_packages", pkg["id"], {"status": "SUBMITTED"})
    _audit_package_status(pkg["id"], prev, "SUBMITTED")

    return db.find_by_id("task_packages", pkg["id"]), submission


# --- Start inspection ----------------------------------------------------

def start_inspection(pkg: dict, project: dict, inspector_id: str):
    if pkg.get("status") != "SUBMITTED":
        raise_error(ERR_PACKAGE_STATE_INVALID, "Package not in SUBMITTED.")
    sub = _latest_submission(pkg["id"])
    if not sub:
        raise_error(ERR_PACKAGE_STATE_INVALID, "No submission found.")
    annotator = db.find_by_id("annotators", sub["annotator_id"])
    sample_size = calc.sample_size_for_inspection(pkg["item_count"], annotator["tier"])

    inspection = db.insert(
        "inspections",
        {
            "package_id": pkg["id"],
            "submission_id": sub["id"],
            "inspector_id": inspector_id,
            "sample_size": sample_size,
            "defects_found": None,
            "pass_rate": None,
            "outcome": None,
        },
    )
    prev = pkg["status"]
    db.update("task_packages", pkg["id"], {"status": "INSPECTING"})
    _audit_package_status(pkg["id"], prev, "INSPECTING")
    return db.find_by_id("inspections", inspection["id"])


def _latest_submission(package_id: str) -> dict | None:
    subs = sorted(db.find_many("submissions", package_id=package_id),
                  key=lambda s: s["created_at"])
    return subs[-1] if subs else None


# --- Finalize inspection -------------------------------------------------

def finalize_inspection(pkg: dict, project: dict, inspection: dict,
                        outcome: str, defects_found):
    # Pre-checks
    if outcome not in {"PASS", "FAIL"}:
        raise_error(ERR_INVALID_PARAMETER, "outcome must be PASS or FAIL.")
    if pkg.get("status") != "INSPECTING":
        raise_error(ERR_PACKAGE_STATE_INVALID, "Package not in INSPECTING.")
    from errors import ERR_INSPECTION_STATE_INVALID
    if inspection.get("outcome") is not None:
        raise_error(ERR_INSPECTION_STATE_INVALID, "Inspection already finalized.")
    if not isinstance(defects_found, int) or defects_found < 0 or defects_found > inspection["sample_size"]:
        raise_error(ERR_DEFECTS_OUT_OF_RANGE,
                    f"defects_found out of [0, {inspection['sample_size']}].")

    # Lock-by-appeal: if a SUBMITTED appeal exists for this inspection,
    # reject the finalize (first-writer-wins).
    for ap in db.find_many("appeals", inspection_id=inspection["id"]):
        if ap.get("status") == "SUBMITTED":
            raise_error(ERR_INSPECTION_LOCKED_BY_APPEAL,
                        "Inspection is locked by a pending appeal.")

    sub = db.find_by_id("submissions", inspection["submission_id"])
    annotator = db.find_by_id("annotators", sub["annotator_id"])

    sample_size = inspection["sample_size"]
    pass_rate = calc.inspection_pass_rate(defects_found, sample_size)

    # Effective outcome consistent with body (FAIL when ratio > 0.10).
    # Trust the submitted outcome but validate consistency with defect ratio.
    is_pass = calc.is_pass(defects_found, sample_size)

    # Update inspection record (defects/pass_rate always set; outcome set below).
    db.update("inspections", inspection["id"], {
        "defects_found": defects_found,
        "pass_rate": pass_rate,
    })

    if outcome == "PASS" and not is_pass:
        # The reviewer claims PASS but defect ratio over threshold — treat as
        # FAIL routing per the scaffold's "outcome resolves" semantics.
        outcome = "FAIL"
    if outcome == "FAIL" and is_pass:
        # Defect ratio shows pass; honor reviewer's FAIL → reroute as FAIL.
        pass

    # Consistency-low isolation: if package has 2+ submissions and last
    # consistency_score < threshold, force ARBITRATING.
    consistency_force = (
        pkg.get("consistency_score") is not None
        and calc.is_low_consistency(pkg["consistency_score"])
    )

    prev = "INSPECTING"
    if outcome == "PASS":
        # INSPECTING → APPROVED
        db.update("inspections", inspection["id"], {"outcome": "PASS"})
        if consistency_force:
            return _route_to_arbitration(pkg, inspection, annotator)
        return _approve_from_inspection(pkg, project, inspection, annotator)
    else:
        # FAIL routing
        db.update("inspections", inspection["id"], {"outcome": "FAIL"})
        if consistency_force:
            return _route_to_arbitration(pkg, inspection, annotator)
        next_round = pkg.get("rework_round", 0) + 1
        if next_round <= MAX_REWORK_ROUNDS:
            db.update("task_packages", pkg["id"], {
                "status": "REWORK_PENDING",
                "rework_round": next_round,
            })
            _audit_package_status(pkg["id"], prev, "REWORK_PENDING")
            update_after_inspection_outcome(annotator["id"], approved=False,
                                            log_fn=_audit_package_status)
            return db.find_by_id("inspections", inspection["id"])
        else:
            return _route_to_arbitration(pkg, inspection, annotator)


def _approve_from_inspection(pkg, project, inspection, annotator):
    prev = pkg["status"]
    db.update("task_packages", pkg["id"], {"status": "APPROVED"})
    _audit_package_status(pkg["id"], prev, "APPROVED")

    # Salary entries
    gross = calc.piece_rate_amount(
        base_unit_price_cents=project["unit_price_cents"],
        item_count=pkg["item_count"],
        difficulty=project["difficulty"],
        tier=annotator["tier"],
    )
    pr_entry = add_ledger_entry(
        annotator_id=annotator["id"], package_id=pkg["id"],
        kind="PIECE_RATE", gross_amount_cents=gross,
        settlement_state="WITHHELD",
    )
    db.update("ledger_entries", pr_entry["id"],
              {"inspection_id": inspection["id"]}, bump=False)

    package_pass_rate = inspection.get("pass_rate")
    if package_pass_rate is None:
        package_pass_rate = calc.inspection_pass_rate(
            inspection.get("defects_found", 0), inspection["sample_size"])
    kind, signed = calc.bonus_or_penalty(
        gross, package_pass_rate, project["pass_rate_target"])
    if kind:
        bp_entry = add_ledger_entry(
            annotator_id=annotator["id"], package_id=pkg["id"],
            kind=kind, gross_amount_cents=signed,
            settlement_state="WITHHELD",
        )
        db.update("ledger_entries", bp_entry["id"],
                  {"inspection_id": inspection["id"]}, bump=False)

    # External events
    queue_event("IM", "package.approved", pkg["id"])
    queue_event("STORAGE", "package.approved", pkg["id"])

    # Counters: approved
    update_after_inspection_outcome(annotator["id"], approved=True,
                                    log_fn=_audit_package_status)
    return db.find_by_id("inspections", inspection["id"])


def _route_to_arbitration(pkg, inspection, annotator):
    """INSPECTING → ARBITRATING with arbiter selection."""
    prev = pkg["status"]
    arbiter = select_arbiter(pkg, exclude_annotator_id=annotator["id"])
    if not arbiter:
        raise_error(ERR_NO_ELIGIBLE_ARBITER, "No eligible arbiter available.")
    db.update("task_packages", pkg["id"], {
        "status": "ARBITRATING",
        "arbiter_id": arbiter["id"],
    })
    db.update("inspections", inspection["id"], {"outcome": "DISPUTED"})
    _audit_package_status(pkg["id"], prev, "ARBITRATING")
    return db.find_by_id("inspections", inspection["id"])


# --- Arbiter selection ----------------------------------------------------

def select_arbiter(pkg, *, exclude_annotator_id=None,
                   appeal_annotator_id=None):
    candidates = []
    for a in db.all_rows("annotators"):
        if a.get("tier") != "EXPERT":
            continue
        if a.get("status") != "ACTIVE":
            continue
        owner_id = pkg.get("assigned_annotator_id")
        if owner_id and a["id"] == owner_id:
            continue
        if exclude_annotator_id and a["id"] == exclude_annotator_id:
            continue
        if appeal_annotator_id and a["id"] == appeal_annotator_id:
            continue
        candidates.append(a)
    if not candidates:
        return None
    candidates.sort(key=lambda a: (
        -a.get("golden_hit_rate", 0),
        -a.get("rolling_pass_rate", 0),
        a["id"],
    ))
    return candidates[0]


# --- Rework claim / dispatch ----------------------------------------------

def rework_claim(pkg: dict, project: dict, annotator: dict):
    if pkg.get("status") != "REWORK_PENDING":
        raise_error(ERR_PACKAGE_STATE_INVALID, "Package not in REWORK_PENDING.")
    if annotator.get("status") != "ACTIVE":
        raise_error(ERR_ANNOTATOR_SUSPENDED, "Annotator is suspended.")
    if pkg.get("assigned_annotator_id") != annotator["id"]:
        raise_error(ERR_NOT_PACKAGE_OWNER, "Only the original owner may rework-claim.")

    claimed_at = db.now_dt()
    deadline = claimed_at + timedelta(seconds=project["timeout_seconds"])
    db.update("task_packages", pkg["id"], {
        "status": "IN_PROGRESS",
        "claimed_at": db.format_ts(claimed_at),
        "deadline_at": db.format_ts(deadline),
    })
    _audit_package_status(pkg["id"], "REWORK_PENDING", "IN_PROGRESS")
    return db.find_by_id("task_packages", pkg["id"])


def rework_dispatch_back_to_pool(pkg: dict):
    if pkg.get("status") != "REWORK_PENDING":
        raise_error(ERR_PACKAGE_STATE_INVALID, "Package not in REWORK_PENDING.")
    prev = pkg["status"]
    db.update("task_packages", pkg["id"], {
        "status": "POOL",
        "assigned_annotator_id": None,
        "claimed_at": None,
        "deadline_at": None,
    })
    _audit_package_status(pkg["id"], prev, "POOL")
    return db.find_by_id("task_packages", pkg["id"])


# --- Arbitrate (final decision) -------------------------------------------

def arbitrate(pkg: dict, project: dict, arbiter: dict, decision: str):
    if pkg.get("status") != "ARBITRATING":
        raise_error(ERR_PACKAGE_STATE_INVALID, "Package not in ARBITRATING.")
    if arbiter.get("tier") != "EXPERT" or arbiter.get("status") != "ACTIVE":
        raise_error(ERR_ARBITER_IS_OWNER, "Acting annotator is not an EXPERT arbiter.")
    if arbiter["id"] == pkg.get("assigned_annotator_id"):
        raise_error(ERR_ARBITER_IS_OWNER, "Arbiter cannot be the package owner.")
    if decision not in {"APPROVE", "REJECT"}:
        raise_error(ERR_INVALID_PARAMETER, "decision must be APPROVE or REJECT.")

    submitter_id = pkg.get("assigned_annotator_id")
    annotator = db.find_by_id("annotators", submitter_id)

    # Grab the latest inspection (the one that triggered ARBITRATING).
    inspections = sorted(
        db.find_many("inspections", package_id=pkg["id"]),
        key=lambda r: r["created_at"],
    )
    last_inspection = inspections[-1] if inspections else None

    prev = pkg["status"]
    if decision == "APPROVE":
        db.update("task_packages", pkg["id"], {"status": "APPROVED"})
        _audit_package_status(pkg["id"], prev, "APPROVED")

        gross = calc.piece_rate_amount(
            base_unit_price_cents=project["unit_price_cents"],
            item_count=pkg["item_count"],
            difficulty=project["difficulty"],
            tier=annotator["tier"],
        )
        pr_entry = add_ledger_entry(
            annotator_id=annotator["id"], package_id=pkg["id"],
            kind="PIECE_RATE", gross_amount_cents=gross,
            settlement_state="WITHHELD",
        )
        if last_inspection:
            db.update("ledger_entries", pr_entry["id"],
                      {"inspection_id": last_inspection["id"]}, bump=False)

        # Bonus/penalty per the most recent inspection's pass rate
        if last_inspection and last_inspection.get("sample_size"):
            pr = last_inspection.get("pass_rate") or calc.inspection_pass_rate(
                last_inspection.get("defects_found", 0),
                last_inspection["sample_size"])
            kind, signed = calc.bonus_or_penalty(
                gross, pr, project["pass_rate_target"])
            if kind:
                bp_entry = add_ledger_entry(
                    annotator_id=annotator["id"], package_id=pkg["id"],
                    kind=kind, gross_amount_cents=signed,
                    settlement_state="WITHHELD",
                )
                db.update("ledger_entries", bp_entry["id"],
                          {"inspection_id": last_inspection["id"]}, bump=False)

        queue_event("IM", "package.approved", pkg["id"])
        update_after_inspection_outcome(annotator["id"], approved=True,
                                        log_fn=_audit_package_status)
    else:
        db.update("task_packages", pkg["id"], {"status": "REJECTED"})
        _audit_package_status(pkg["id"], prev, "REJECTED")
        from config import PENALTY_REJECT_CENTS
        pen_entry = add_ledger_entry(
            annotator_id=annotator["id"], package_id=pkg["id"],
            kind="PENALTY", gross_amount_cents=-PENALTY_REJECT_CENTS,
            settlement_state="WITHHELD",
        )
        if last_inspection:
            db.update("ledger_entries", pen_entry["id"],
                      {"inspection_id": last_inspection["id"]}, bump=False)
        queue_event("IM", "package.rejected", pkg["id"])
        update_after_inspection_outcome(annotator["id"], approved=False,
                                        log_fn=_audit_package_status)

    return db.find_by_id("task_packages", pkg["id"])


# --- Clock advance reclamation -------------------------------------------

def reclaim_timeouts(now_dt):
    """Revert any IN_PROGRESS package whose deadline_at <= now_dt to POOL.
    Used by /_clock/advance.
    """
    for pkg in list(db.all_rows("task_packages")):
        if pkg.get("status") != "IN_PROGRESS":
            continue
        d = pkg.get("deadline_at")
        if not d:
            continue
        try:
            dt = db.parse_iso(d)
        except Exception:
            continue
        if now_dt >= dt:
            prev = pkg["status"]
            db.update("task_packages", pkg["id"], {
                "status": "POOL",
                "assigned_annotator_id": None,
                "claimed_at": None,
                "deadline_at": None,
            })
            _audit_package_status(pkg["id"], prev, "POOL", system=True)
