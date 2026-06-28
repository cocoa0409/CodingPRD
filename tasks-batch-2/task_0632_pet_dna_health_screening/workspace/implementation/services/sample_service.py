"""Sample genotyping fork cascade (PRD §3.3, §3.4)."""
from db import db, create_versioned, touch
from services.calculations import compute_breed_composition
from services.report_service import compute_at_risk_marker_count


def kit_has_other_non_terminal_sample(kit_id, exclude_sample_id):
    """A kit may not hold two non-terminal samples at once.
    Sample terminal states: PASS, RETESTED. Non-terminal: RECEIVED, GENOTYPING,
    QNS, FAILED."""
    non_terminal = {"RECEIVED", "GENOTYPING", "QNS", "FAILED"}
    for s in db.samples.values():
        if s["id"] == exclude_sample_id:
            continue
        if s["kit_id"] == kit_id and s["status"] in non_terminal:
            return True
    return False


def apply_genotyping_outcome(sample, run):
    """Drive the sample fork from the run's outcome (PRD §3.3 / §3.4).
    The run's qc_score is copied onto the sample in every branch.
    Returns the created Report record on PASS, else None."""
    outcome = run["outcome"]
    sample["qc_score"] = run["qc_score"]

    if outcome == "PASS":
        sample["status"] = "PASS"
        touch(sample)
        # Transition owning kit RECEIVED -> CONSUMED.
        kit = db.kits.get(sample["kit_id"])
        if kit is not None and kit["status"] == "RECEIVED":
            kit["status"] = "CONSUMED"
            touch(kit)
        # Create a PRELIMINARY report for this sample.
        report = _create_report_for_sample(sample, run)
        return report

    if outcome == "QNS":
        sample["status"] = "QNS"
        touch(sample)
        return None

    if outcome == "FAILED":
        sample["status"] = "FAILED"
        touch(sample)
        return None

    return None


def _create_report_for_sample(sample, run):
    """Report born on sample PASS (PRD §3.4): PRELIMINARY, sample_id set,
    pet_id copied from sample, includes_health true iff kit BREED_HEALTH,
    breed_composition computed from the run's breed_segments,
    at_risk_marker_count computed (preliminary variant -> 0 at creation)."""
    kit = db.kits.get(sample["kit_id"])
    includes_health = bool(kit and kit["product_tier"] == "BREED_HEALTH")
    breed_segments = run.get("breed_segments") or []
    breed_composition = compute_breed_composition(breed_segments)

    report = create_versioned(db.reports, {
        "sample_id": sample["id"],
        "pet_id": sample["pet_id"],
        "includes_health": includes_health,
        "status": "PRELIMINARY",
        "breed_composition": breed_composition,
        "at_risk_marker_count": 0,
    })
    # Preliminary variant rollup (no markers yet -> 0, but compute for symmetry).
    report["at_risk_marker_count"] = compute_at_risk_marker_count(
        report["id"], finalized=False
    )
    return report
