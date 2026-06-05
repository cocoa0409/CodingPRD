"""Validation-precedence conflicts on audit endpoints, temporal-overlap
geometry (cycle adjacency vs audit cooldown buffer), and boundary-precision
checks (exact-threshold requirement, empty certificate collection).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    factories as F,
    fixtures as FX,
    make_licensee_headers,
    make_auditor_headers,
)
from test_helpers.constants import ADMIN_INITIATOR_ID

ADMIN = FX.ADMIN
ADMIN_INITIATOR = FX.ADMIN_INITIATOR
AUDITOR = FX.AUDITOR

# An Auditor whose X-User-ID collides with the initiating BoardAdmin's recorded
# `initiated_by_user_id`. Deciding through this identity creates a genuine
# segregation-of-duties violation (PRD §2.7) on the Auditor-only decide endpoint
# (PRD §4 endpoint table) — without the role-authorization (`ERR_FORBIDDEN`)
# violation that a BoardAdmin caller would trip first under §2.10 precedence.
CONFLICTING_AUDITOR = make_auditor_headers(ADMIN_INITIATOR_ID)


# ===========================================================================
# Difficulty/priority_pair_validation_conflict  (>=2 tests per instance)
# ===========================================================================
def test_state_beats_business_temporal_on_audit_initiate(api):
    """PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`). Endpoint-specific business
    checks — the cross-entity accreditation gate, segregation of duties, temporal
    window checks, overlap, cooldown, single-open-audit, jurisdiction,
    requirements-met, carryover-cap, and the renewal version check — are
    evaluated after those foundational checks."
    PRD §3.9: "The audit may be initiated only when the cycle is `OPEN` or
    `REQUIREMENTS_MET`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_audit_initiate
    """
    # Drive the cycle to LAPSED via a FAILED audit closed at 2026-03-01.
    decided = FX.setup_audit_decided(
        decision="FAIL", attested_hours=30.0, decide_clock="2026-03-01T00:00:00Z")
    cycle = decided["cycle"]
    assert cycle["status"] == "LAPSED"

    # Clock to 2026-04-01: well within the 365-day cooldown after the first audit.
    FX.set_clock("2026-04-01T00:00:00Z")

    # A new audit on a LAPSED cycle violates BOTH the state precondition (cycle not
    # OPEN/REQUIREMENTS_MET) and the cooldown buffer; the state check wins.
    resp = api.create_audit(F.create_audit_payload(cycle["id"]), ADMIN_INITIATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_audit_initiate_on_lapsed_cycle_http_status_is_409(api):
    """PRD §3.9: "The audit may be initiated only when the cycle is `OPEN` or
    `REQUIREMENTS_MET`."
    PRD §5 (error catalogue): "`ERR_INVALID_STATE` | 409."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_audit_initiate
    """
    decided = FX.setup_audit_decided(
        decision="FAIL", attested_hours=30.0, decide_clock="2026-03-01T00:00:00Z")
    cycle = decided["cycle"]
    FX.set_clock("2026-04-01T00:00:00Z")

    resp = api.create_audit(F.create_audit_payload(cycle["id"]), ADMIN_INITIATOR)
    # The state check (priority) returns 409, not the 409-cooldown by a different id.
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_business_safety_beats_business_constraint_on_audit_decide(api):
    """PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`). Endpoint-specific business
    checks — the cross-entity accreditation gate, segregation of duties ... — are
    evaluated after those foundational checks."
    PRD §3.9: "A decision is allowed only when the audit is `UNDER_REVIEW`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_audit_decide
    """
    met = FX.setup_requirements_met_cycle()
    cycle = met["cycle"]
    audit = FX.initiate_audit(cycle["id"], ADMIN_INITIATOR)  # still INITIATED
    assert audit["status"] == "INITIATED"

    # An Auditor whose X-User-ID equals the recorded initiated_by_user_id decides
    # while the audit is still INITIATED: this violates BOTH segregation-of-duties
    # (a business check) and the UNDER_REVIEW state precondition. Per §2.10 the
    # foundational state check fires before the segregation business check, so the
    # returned error is ERR_INVALID_STATE.
    resp = api.decide_audit(
        audit["id"], F.decide_audit_payload("PASS"), CONFLICTING_AUDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_decide_initiated_audit_leaves_audit_unchanged(api):
    """PRD §3.9: "A decision is allowed only when the audit is `UNDER_REVIEW`."
    PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_audit_decide
    """
    met = FX.setup_requirements_met_cycle()
    audit = FX.initiate_audit(met["cycle"]["id"], ADMIN_INITIATOR)  # INITIATED

    # An Auditor colliding with the initiator's id (would-be segregation
    # violation) is blocked first by the state precondition; the audit stays
    # INITIATED.
    resp = api.decide_audit(
        audit["id"], F.decide_audit_payload("FAIL"), CONFLICTING_AUDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = get_success_data(api.get_audit(audit["id"], ADMIN))
    assert after["status"] == "INITIATED", "blocked decide leaves the audit unchanged"


# ===========================================================================
# Difficulty/resource_temporal_overlap  (>=2 tests per instance)
# ===========================================================================
def test_renewal_cycle_overlap_closed_open_adjacency(api):
    """PRD §3.3: "A new cycle whose `cycle_start` exactly equals a prior cycle's
    `cycle_end` is permitted (the windows are adjacent, not overlapping); any new
    start that lands strictly inside a prior cycle's interval is rejected with
    `ERR_CYCLE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/renewal_cycle_overlap_closed_open_adjacency
    """
    board = FX.create_board(with_requirements=False, cycle_length_months=24)
    licensee = FX.create_licensee(board["id"])
    # First cycle [2026-01-01, 2028-01-01).
    FX.open_cycle(licensee["id"], board["id"], "2026-01-01T00:00:00Z")

    # 2027-06-01 lands strictly inside the first cycle's interval.
    payload = F.create_renewal_cycle_payload(
        licensee["id"], board["id"], "2027-06-01T00:00:00Z")
    resp = api.create_renewal_cycle(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_CYCLE_OVERLAP.value, 409)


def test_renewal_cycle_adjacent_start_is_allowed(api):
    """PRD §3.3: "A new cycle whose `cycle_start` exactly equals a prior cycle's
    `cycle_end` is permitted (the windows are adjacent, not overlapping)."

    Design: Difficulty/resource_temporal_overlap/renewal_cycle_overlap_closed_open_adjacency
    """
    board = FX.create_board(with_requirements=False, cycle_length_months=24)
    licensee = FX.create_licensee(board["id"])
    FX.open_cycle(licensee["id"], board["id"], "2026-01-01T00:00:00Z")  # ends 2028-01-01

    # cycle_start exactly at the prior cycle_end is adjacency, not overlap.
    payload = F.create_renewal_cycle_payload(
        licensee["id"], board["id"], "2028-01-01T00:00:00Z")
    data = validate_success(
        api.create_renewal_cycle(payload, make_licensee_headers(licensee["id"])), 201)
    assert data["cycle_start"].startswith("2028-01-01")


def test_audit_cooldown_buffer_gap_on_same_licensee(api):
    """PRD §3.9: "Initiation is further gated by a cooldown: a new audit on a
    licensee is allowed only if the current clock is at or after the most
    recently closed audit's `closed_at` plus the board's `audit_cooldown_days` —
    the full buffer must have elapsed — otherwise the request is rejected with
    `ERR_AUDIT_COOLDOWN_ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/audit_cooldown_buffer_gap_on_same_licensee
    """
    # First audit PASSES and closes at 2026-03-01; cycle returns to REQUIREMENTS_MET.
    decided = FX.setup_audit_decided(
        decision="PASS", attested_hours=30.0, decide_clock="2026-03-01T00:00:00Z")
    cycle = decided["cycle"]
    assert cycle["status"] == "REQUIREMENTS_MET"

    # Clock to 2026-06-01: only ~92 days after close, < 365-day cooldown.
    FX.set_clock("2026-06-01T00:00:00Z")
    resp = api.create_audit(F.create_audit_payload(cycle["id"]), ADMIN_INITIATOR)
    validate_error(resp, ApiErrorId.ERR_AUDIT_COOLDOWN_ACTIVE.value, 409)


def test_audit_allowed_once_cooldown_fully_elapsed(api):
    """PRD §3.9: "a new audit on a licensee is allowed only if the current clock
    is at or after the most recently closed audit's `closed_at` plus the board's
    `audit_cooldown_days` — the full buffer must have elapsed."

    Design: Difficulty/resource_temporal_overlap/audit_cooldown_buffer_gap_on_same_licensee
    """
    # First audit PASSES and closes at 2026-03-01; cycle back to REQUIREMENTS_MET.
    decided = FX.setup_audit_decided(
        decision="PASS", attested_hours=30.0, decide_clock="2026-03-01T00:00:00Z")
    cycle = decided["cycle"]

    # 2027-03-02 is well past closed_at + 365 days; the buffer has fully elapsed.
    FX.set_clock("2027-03-02T00:00:00Z")
    data = validate_success(
        api.create_audit(F.create_audit_payload(cycle["id"]), ADMIN_INITIATOR), 201)
    assert data["status"] == "INITIATED", "a new audit is allowed after the full cooldown"


# ===========================================================================
# Difficulty/boundary_precision_check  (>=2 tests per instance)
# ===========================================================================
def test_requirement_met_exactly_at_threshold_on_verify(api):
    """PRD §3.6: "A category holding precisely its minimum is satisfied —
    comparisons are inclusive, treating exactly-the-minimum as met."
    PRD §3.4: "if the cycle's requirement is now satisfied on verified hours the
    cycle bubbles up from `OPEN` to `REQUIREMENTS_MET`."

    Design: Difficulty/boundary_precision_check/requirement_met_exactly_at_threshold_on_verify
    """
    base = FX.setup_board_provider_licensee_cycle()  # total 30, ETHICS 4, SUBSTANCE 2
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    # ETHICS 4.0 + SUBSTANCE 2.0 verified; GENERAL 24.0 left PENDING.
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "ETHICS", 4.0)["id"], cycle["id"])
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "SUBSTANCE", 2.0)["id"], cycle["id"])
    course_g = FX.create_course(provider["id"], "GENERAL", 24.0)
    comp_g = FX.log_completion(licensee["id"], course_g["id"], cycle["id"])

    # Verifying the last completion lands each category exactly at its min (total 30.0).
    validate_success(api.verify_completion(comp_g["id"], ADMIN), 200)

    data = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(data["final_earned_hours"]) == pytest.approx(30.0, abs=0.01), "exact threshold"
    assert data["status"] == "REQUIREMENTS_MET", ">= boundary is MET"


def test_requirement_unmet_just_below_threshold_on_verify(api):
    """PRD §3.6: "The requirement is met exactly when every non-`GENERAL`
    category's deficit is 0 and the general deficit is also 0."
    PRD §3.6: "The general deficit is the general requirement minus the general
    pool, floored at 0."

    Design: Difficulty/boundary_precision_check/requirement_met_exactly_at_threshold_on_verify
    """
    base = FX.setup_board_provider_licensee_cycle()  # total 30, ETHICS 4, SUBSTANCE 2
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    # ETHICS 4.0 + SUBSTANCE 2.0 verified; GENERAL 23.9 -> one tenth below the 24.0 general req.
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "ETHICS", 4.0)["id"], cycle["id"])
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "SUBSTANCE", 2.0)["id"], cycle["id"])
    course_g = FX.create_course(provider["id"], "GENERAL", 23.9)
    comp_g = FX.log_completion(licensee["id"], course_g["id"], cycle["id"])

    validate_success(api.verify_completion(comp_g["id"], ADMIN), 200)

    data = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(data["final_earned_hours"]) == pytest.approx(29.9, abs=0.01), "just below total"
    assert data["status"] == "OPEN", "0.1 general deficit keeps the cycle below the boundary"


def test_empty_certificate_collection_before_renew(api):
    """PRD §3.8: "On a successful renewal ... a certificate is issued for the
    cycle."
    PRD §4 (endpoint table): "GET `/renewal-cycles/{id}/certificate` List the
    certificate(s) issued for a cycle."

    Design: Difficulty/boundary_precision_check/empty_certificate_collection_before_renew
    """
    met = FX.setup_requirements_met_cycle()  # REQUIREMENTS_MET but not yet renewed
    cycle, licensee = met["cycle"], met["licensee"]
    lic = make_licensee_headers(licensee["id"])

    data, meta = validate_paginated(api.list_cycle_certificates(cycle["id"], lic))
    assert data == [], "no certificate exists before renew (empty array)"
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_certificate_collection_has_one_entry_after_renew(api):
    """PRD §3.8: "a certificate is issued for the cycle. The certificate
    references the cycle through its `cycle_id`, carries a `serial_number`
    assigned at issuance."
    PRD §4 (endpoint table): "GET `/renewal-cycles/{id}/certificate` List the
    certificate(s) issued for a cycle."

    Design: Difficulty/boundary_precision_check/empty_certificate_collection_before_renew
    """
    met = FX.setup_requirements_met_cycle()
    cycle, licensee = met["cycle"], met["licensee"]
    lic = make_licensee_headers(licensee["id"])

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], lic))
    get_success_data(api.renew_cycle(cycle["id"], F.renew_cycle_payload(cyc["version"]), lic))

    # The collection transitions from length 0 to exactly length 1 after renew.
    data, meta = validate_paginated(api.list_cycle_certificates(cycle["id"], lic))
    assert meta["total_count"] == 1, "exactly one certificate after renew"
    assert len(data) == 1
    assert data[0]["cycle_id"] == cycle["id"]
