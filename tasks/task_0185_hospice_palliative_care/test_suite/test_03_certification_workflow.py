"""Certification / recertification: the certify-vs-reject branch, the cascade that
materializes the next period, sequence ordering, the face-to-face rule, completeness,
OCC stale-version guards, and the version bump. PRD §3.4, §2.7, §3.13.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    assert_certification,
    setup_election_with_md_period1_pending,
    setup_election_period1_certified,
    setup_provider_and_election,
    create_medical_director,
    create_plain_physician,
    commit_certification,
    get_election,
    revoke_election,
    set_clock,
    create_provider,
    create_election,
    make_physician_headers,
    create_certification_payload,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_headers"]


# ─── Non-linear state machine: certify vs reject branch ───────────────

def test_certify_commit_with_narrative_takes_certify_branch(api):
    """PRD §3.4: "When all certify preconditions hold and expected_election_version matches,
    the commit succeeds: the target period's cert_status becomes CERTIFIED and its
    certification_id is set to this certification, the certification's own status becomes
    CERTIFIED..."

    Design: Difficulty/non_linear_state_machine/certification_branch_certify_vs_reject
    """
    provider, election, md = setup_election_with_md_period1_pending(
        election_date="2026-01-01T00:00:00Z")
    res = commit_certification(election["id"], 1, md["id"], election["version"],
                               narrative_present=True)
    cert = validate_success(res, 201)
    assert cert["status"] == "CERTIFIED"
    after = get_election(election["id"])
    assert after["version"] == election["version"] + 1, "certify branch bumps version by 1"


# ─── Transitive cascade: certify → period CERTIFIED → next materialized ─

def test_certify_period1_certifies_period_and_materializes_period2(api):
    """PRD §3.4: "the target period's cert_status becomes CERTIFIED ... the next benefit period
    (one sequence higher) is materialized in PENDING_CERT with its length_days and
    start_offset_days computed per the 90/90/60 rule, and the election's version is incremented
    by one."

    Design: Difficulty/transitive_cascade/certify_cascade_period_certified_next_materialized
    """
    provider, election, md = setup_election_with_md_period1_pending(
        election_date="2026-01-01T00:00:00Z")
    res = commit_certification(election["id"], 1, md["id"], election["version"],
                               narrative_present=True)
    cert = validate_success(res, 201)
    assert cert["status"] == "CERTIFIED"

    periods, _ = _list_periods(api, election["id"])
    by_seq = {p["sequence"]: p for p in periods}
    assert by_seq[1]["cert_status"] == "CERTIFIED", "period 1 flips to CERTIFIED"
    assert 2 in by_seq, "period 2 is materialized by the certify side-effect"
    assert by_seq[2]["cert_status"] == "PENDING_CERT"
    assert by_seq[2]["length_days"] == 90, "period 2 is 90 days (90/90/60 cadence)"


def test_certify_period1_sets_period_certification_id(api):
    """PRD §3.4: "the target period's cert_status becomes CERTIFIED and its certification_id is
    set to this certification..."

    Design: Difficulty/transitive_cascade/certify_cascade_period_certified_next_materialized
    """
    provider, election, md = setup_election_with_md_period1_pending(
        election_date="2026-01-01T00:00:00Z")
    res = commit_certification(election["id"], 1, md["id"], election["version"],
                               narrative_present=True)
    cert = validate_success(res, 201)
    periods, _ = _list_periods(api, election["id"])
    p1 = next(p for p in periods if p["sequence"] == 1)
    assert p1["certification_id"] == cert["id"], "period 1 certification_id points to this cert"


# ─── Priority-pair conflict: state check beats face-to-face safety ────

def test_certify_on_revoked_election_returns_not_elected_over_f2f(api):
    """PRD §3.9: "attempting any of them — like attempting any certify, care-day, care-plan, or
    coverage-item write — against an election that is already REVOKED, DISCHARGED, or EXPIRED
    is rejected with ERR_ELECTION_NOT_ELECTED (HTTP 409)."
    PRD §3.13: "After those, the election-state precondition is checked for certify, care-day,
    care-plan, coverage-item, revoke, and discharge operations (ERR_ELECTION_NOT_ELECTED)..."

    Design: Difficulty/priority_pair_validation_conflict/not_elected_state_beats_face_to_face_safety
    """
    provider = create_provider()
    md = create_medical_director(full_name="Dr PC1")
    set_clock("2026-01-01T00:00:00Z")
    election = create_election(provider["id"], election_date="2026-01-01T00:00:00Z",
                               patient_name="PC1 Pt", attending_physician_id="ext-att-pc1")
    revoke_election(election["id"], "2026-01-05T00:00:00Z")
    # period_sequence 3 also omits the required face-to-face, but the state check fires first.
    res = commit_certification(election["id"], 3, md["id"], election["version"],
                               narrative_present=True)
    validate_error(res, "ERR_ELECTION_NOT_ELECTED")


def test_certify_on_discharged_election_returns_not_elected(api):
    """PRD §3.9: "attempting any of them — like attempting any certify, care-day, care-plan, or
    coverage-item write — against an election that is already REVOKED, DISCHARGED, or EXPIRED
    is rejected with ERR_ELECTION_NOT_ELECTED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/not_elected_state_beats_face_to_face_safety
    """
    provider = create_provider()
    md = create_medical_director(full_name="Dr PC1b")
    set_clock("2026-01-01T00:00:00Z")
    election = create_election(provider["id"], election_date="2026-01-01T00:00:00Z",
                               patient_name="PC1b Pt", attending_physician_id="ext-att-pc1b")
    set_clock("2026-01-05T00:00:00Z")
    from test_helpers import discharge_election
    discharge_election(election["id"], "2026-01-05T00:00:00Z", "NO_LONGER_TERMINAL")
    res = commit_certification(election["id"], 3, md["id"], election["version"],
                               narrative_present=True)
    validate_error(res, "ERR_ELECTION_NOT_ELECTED")


# ─── Corner: certify out of order is rejected ─────────────────────────

def test_certify_period2_while_period1_pending_rejected(api):
    """PRD §3.4: "The period_sequence submitted must equal the election's lowest benefit period
    still in PENDING_CERT. Certifying out of order, or attempting to re-certify a period already
    CERTIFIED, is rejected with ERR_PERIOD_SEQUENCE_MISMATCH (HTTP 409)."

    Design: Corner/state_machines/certify_out_of_order_period_sequence_rejected
    """
    provider, election, md = setup_election_with_md_period1_pending(
        election_date="2026-01-01T00:00:00Z")
    res = commit_certification(election["id"], 2, md["id"], election["version"],
                               narrative_present=True)
    validate_error(res, "ERR_PERIOD_SEQUENCE_MISMATCH")


# ─── Corner: face-to-face required for period 3 recert ────────────────

def test_period3_recert_without_face_to_face_rejected(api):
    """PRD §3.4: "When the face-to-face physician or date is missing, or the date falls outside
    that 30-day pre-period window, the commit is rejected with ERR_FACE_TO_FACE_REQUIRED
    (HTTP 422)."

    Design: Corner/validations/face_to_face_required_for_period3_recert
    """
    provider, election, md = setup_election_with_md_period1_pending(
        election_date="2026-01-01T00:00:00Z")
    # Certify period 1.
    validate_success(commit_certification(election["id"], 1, md["id"], election["version"],
                                          narrative_present=True), 201)
    e1 = get_election(election["id"])
    # Certify period 2.
    validate_success(commit_certification(election["id"], 2, md["id"], e1["version"],
                                          narrative_present=True), 201)
    e2 = get_election(election["id"])
    # Period 3 is now the lowest PENDING_CERT; commit without face-to-face.
    res = commit_certification(election["id"], 3, md["id"], e2["version"],
                               narrative_present=True)
    validate_error(res, "ERR_FACE_TO_FACE_REQUIRED")


# ─── Corner: initial cert incomplete (no director, no second physician) ─

def test_initial_cert_by_non_director_without_second_rejected(api):
    """PRD §3.4: "If the narrative is absent, or neither the medical-director nor the
    two-physician condition holds, the commit is rejected with ERR_CERTIFICATION_INCOMPLETE
    (HTTP 422)."

    Design: Corner/validations/initial_cert_incomplete_no_director_no_second_physician
    """
    provider = create_provider()
    doc = create_plain_physician(full_name="Dr Plain")
    set_clock("2026-01-01T00:00:00Z")
    election = create_election(provider["id"], election_date="2026-01-01T00:00:00Z",
                               patient_name="Cert Pt", attending_physician_id="ext-att-pc")
    res = commit_certification(election["id"], 1, doc["id"], election["version"],
                               narrative_present=True)
    validate_error(res, "ERR_CERTIFICATION_INCOMPLETE")


# ─── Corner: OCC stale election version on certify ────────────────────

def test_certify_with_stale_election_version_rejected(api):
    """PRD §2.7: "For a certification commit, the request must carry expected_election_version
    equal to the target election's current version. If another writer has already certified the
    same pending period — legitimately advancing the election and materializing the next period
    — the election's version will have moved past the client's observed value ... and the commit
    is rejected with ERR_STALE_ELECTION_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/certify_stale_election_version_occ
    """
    provider, election, md = setup_election_with_md_period1_pending(
        election_date="2026-01-01T00:00:00Z")
    stale_version = election["version"]
    # Certify period 1 — advances the election version.
    validate_success(commit_certification(election["id"], 1, md["id"], stale_version,
                                          narrative_present=True), 201)
    # Now commit period 2 carrying the pre-certification (stale) version.
    res = commit_certification(election["id"], 2, md["id"], stale_version,
                               narrative_present=True)
    validate_error(res, "ERR_STALE_ELECTION_VERSION")


# ─── Corner: version increments on a successful certify ───────────────

def test_certify_increments_election_version_1_to_2(api):
    """PRD §2.4: "a version integer that begins at its initial value and increments by one on
    every mutation of that resource."
    PRD §3.4: "and the election's version is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_certify
    """
    provider, election, md = setup_election_with_md_period1_pending(
        election_date="2026-01-01T00:00:00Z")
    assert election["version"] == 1
    validate_success(commit_certification(election["id"], 1, md["id"], election["version"],
                                          narrative_present=True), 201)
    after = get_election(election["id"])
    assert after["version"] == 2, f"version should go 1 -> 2 on certify, got {after['version']}"


# ─── helper ───────────────────────────────────────────────────────────

def _list_periods(api, election_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_election_benefit_periods(
        election_id, TEST_USERS["clinical_headers"], params={"limit": 100}))
