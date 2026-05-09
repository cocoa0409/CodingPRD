"""Inspection report lifecycle, pass/fail decision, and revoke cascade (PRD §3.5)."""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    setup_batch_harvested,
    setup_batch_inspected_pass,
    create_draft_inspection,
    issue_inspection,
    revoke_inspection,
    make_grower_headers,
    make_inspector_headers,
    DEFAULT_GROWER_ID,
    TEST_USERS,
)


# --------------------------------------------------------------------------
# PRD §3.5 — segregation of duties
# --------------------------------------------------------------------------

def test_inspector_equal_to_grower_id_rejected_with_segregation_violation():
    """PRD §3.5: "Before computation runs, the segregation-of-duties guard
    fires: if the inspector's X-User-ID equals the batch's grower_id, the
    request is rejected with ERR_SEGREGATION_VIOLATION."

    Claim: inspector_id == grower_id at issue → ERR_SEGREGATION_VIOLATION.
    """
    batch, _bin, _harvest = setup_batch_harvested(grower_id=DEFAULT_GROWER_ID)
    # Create draft as a different inspector first (so creation succeeds), then
    # attempt to issue with X-User-ID equal to the grower_id — that's the
    # violation moment per PRD §3.5.
    draft = create_draft_inspection(
        batch, inspector_id="user-inspector-007"
    )
    # Issue as Inspector role with X-User-ID == batch.grower_id
    headers = make_inspector_headers(DEFAULT_GROWER_ID)
    res = api.issue_inspection(draft["id"], headers)
    validate_error(res, "ERR_SEGREGATION_VIOLATION")


# --------------------------------------------------------------------------
# PRD §3.5 — pass/fail thresholds (boundary precision)
# --------------------------------------------------------------------------

def test_pesticide_residue_at_threshold_passes():
    """PRD §3.5: "For PESTICIDE_RESIDUE, the item passes when the truncated
    pesticide_residue_mg_per_kg is less than or equal to 0.50 (boundary
    inclusive — exact equality passes)."

    Claim: pesticide_residue == 0.50 → PASS (boundary inclusive).
    """
    batch, _bin, _harvest = setup_batch_harvested()
    draft = create_draft_inspection(
        batch,
        test_items=["PESTICIDE_RESIDUE"],
        pesticide_residue_mg_per_kg=0.50,
    )
    issued = issue_inspection(draft)
    assert issued["result"] == "PASS"


def test_heavy_metals_at_threshold_passes():
    """PRD §3.5: "For HEAVY_METALS, the item passes when the truncated
    heavy_metals_mg_per_kg is less than or equal to 0.20 (boundary inclusive
    — exact equality passes)."

    Claim: heavy_metals == 0.20 → PASS (boundary inclusive).
    """
    batch, _bin, _harvest = setup_batch_harvested()
    draft = create_draft_inspection(
        batch,
        test_items=["HEAVY_METALS"],
        heavy_metals_mg_per_kg=0.20,
    )
    issued = issue_inspection(draft)
    assert issued["result"] == "PASS"


def test_microorganism_at_threshold_fails_strict_less_than():
    """PRD §3.5: "For MICROORGANISMS, the item passes when the truncated
    microorganism_cfu_per_g is strictly less than 100000 (boundary strict —
    exact equality fails)."

    Claim: microorganism_cfu_per_g == 100000 → FAIL (strict <).
    """
    batch, _bin, _harvest = setup_batch_harvested()
    draft = create_draft_inspection(
        batch,
        test_items=["MICROORGANISMS"],
        microorganism_cfu_per_g=100000,
    )
    issued = issue_inspection(draft)
    assert issued["result"] == "FAIL"


def test_microorganism_one_below_threshold_passes():
    """PRD §3.5: "For MICROORGANISMS, the item passes when the truncated
    microorganism_cfu_per_g is strictly less than 100000 (boundary strict —
    exact equality fails)."

    Claim: microorganism_cfu_per_g == 99999 → PASS.
    """
    batch, _bin, _harvest = setup_batch_harvested()
    draft = create_draft_inspection(
        batch,
        test_items=["MICROORGANISMS"],
        microorganism_cfu_per_g=99999,
    )
    issued = issue_inspection(draft)
    assert issued["result"] == "PASS"


# --------------------------------------------------------------------------
# PRD §3.5 — issuance cascades
# --------------------------------------------------------------------------

def test_pass_issuance_advances_batch_to_inspected_pass(regulatory_headers):
    """PRD §3.5: "A PASS result advances the parent batch from HARVESTED to
    INSPECTED_PASS and leaves posture CLEAN (unless an agrochemical violation
    has already pushed the batch to FLAGGED)."

    Claim: PASS issuance → batch.status == INSPECTED_PASS, posture CLEAN.
    """
    batch, _bin, _harvest, report = setup_batch_inspected_pass()
    assert report["status"] == "ISSUED"
    assert report["result"] == "PASS"
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["status"] == "INSPECTED_PASS"
    assert refreshed["posture"] == "CLEAN"


def test_fail_issuance_advances_batch_to_inspected_fail_blocked():
    """PRD §3.5: "A FAIL result advances the parent batch from HARVESTED to
    INSPECTED_FAIL, sets posture to BLOCKED."

    Claim: FAIL issuance → batch.status == INSPECTED_FAIL, posture BLOCKED.
    """
    batch, _bin, _harvest = setup_batch_harvested()
    draft = create_draft_inspection(
        batch,
        test_items=["MICROORGANISMS"],
        microorganism_cfu_per_g=200000,  # over threshold
    )
    issued = issue_inspection(draft)
    assert issued["status"] == "ISSUED"
    assert issued["result"] == "FAIL"
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["status"] == "INSPECTED_FAIL"
    assert refreshed["posture"] == "BLOCKED"


# --------------------------------------------------------------------------
# PRD §3.5 — issuance locks the report
# --------------------------------------------------------------------------

def test_issued_report_records_issued_at_and_locks_status():
    """PRD §3.5: "Issuance sets the report's status to ISSUED, locks the
    computed result, and stamps issued_at to the current server time."

    Claim: after issuance, status == ISSUED, result is locked, issued_at set.
    """
    batch, _bin, _harvest, report = setup_batch_inspected_pass()
    assert report["status"] == "ISSUED"
    assert report["result"] == "PASS"
    assert report.get("issued_at") not in (None, "")


def test_issue_already_issued_report_rejected():
    """PRD §3.5: "If an inspector attempts to issue a report whose state has
    shifted out of DRAFT between the time the inspector reads it and the time
    they issue it ... the issuance is rejected with ERR_INVALID_STATE."

    Claim: issuing an already-ISSUED report → ERR_INVALID_STATE.
    """
    batch, _bin, _harvest, report = setup_batch_inspected_pass()
    res = api.issue_inspection(
        report["id"], make_inspector_headers("user-inspector-001")
    )
    validate_error(res, "ERR_INVALID_STATE")


# --------------------------------------------------------------------------
# PRD §3.5 — revoke cascade
# --------------------------------------------------------------------------

def test_revoke_issued_report_reverts_batch_to_harvested(regulatory_headers):
    """PRD §3.5: "Revocation moves the report's status to REVOKED and reverts
    the batch to HARVESTED, with posture recomputed afterward."

    Claim: revoke on ISSUED report → report.status REVOKED, batch reverts to
    HARVESTED.
    """
    batch, _bin, _harvest, report = setup_batch_inspected_pass()
    revoked = revoke_inspection(report)
    assert revoked["status"] == "REVOKED"
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["status"] == "HARVESTED"
