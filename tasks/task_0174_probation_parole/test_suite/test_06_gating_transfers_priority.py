"""Cross-entity posture gating, interstate transfers (single-live-claim, OCC,
high-risk block, bubble-up), and validation-priority conflicts.

Difficulty queue: cross_entity_state_dependency (condition gate, transfer points
gate), resource_temporal_overlap (transfer single-live-claim),
priority_pair_validation_conflict (closed-beats-fiscal, segregation-beats-state).
Corner queue: state_machines (transfer accept bubble-up), validations (same-state
transfer), cross_cutting (OCC stale + correct version), rbac (officer cannot
accept).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_officer_headers, make_judge_headers, make_compact_admin_headers,
    setup_active_supervisee, add_condition, add_active_condition,
    file_violation, sustain_violation, file_and_sustain,
    request_transfer, current_version, setup_supervisee_with_open_transfer,
    setup_completed_supervisee, create_transfer_payload,
)


# ─── Difficulty: cross_entity_state_dependency / condition gate ───
def test_condition_activation_blocked_when_level_too_low(api):
    """PRD §3.3: "If the supervisee's level sits below the condition's
    minimum_level_required, activation is refused with
    ERR_LEVEL_TOO_LOW_FOR_CONDITION (HTTP 409)."

    A MAXIMUM-required condition cannot activate while the supervisee sits at
    ADMINISTRATIVE.

    Design: Difficulty/cross_entity_state_dependency/condition_activation_gated_by_supervisee_level
    """
    officer, sup = setup_active_supervisee(level_total=10)  # ADMINISTRATIVE
    oh = make_officer_headers(officer["id"])
    cond = add_condition(
        sup["id"], officer["id"],
        condition_type="ELECTRONIC_MONITORING", minimum_level_required="MAXIMUM",
    )
    res = api.activate_condition(sup["id"], cond["id"], oh)
    validate_error(res, "ERR_LEVEL_TOO_LOW_FOR_CONDITION")
    after = validate_success(api.get_condition(sup["id"], cond["id"], oh), 200)
    assert after["status"] == "PROPOSED"


def test_condition_activation_allowed_when_level_meets_requirement(api):
    """PRD §3.3: "An Officer activates a condition, which is permitted only when the
    condition is in PROPOSED status ..., the supervisee is in ACTIVE status, and
    the supervisee's current supervision_level is greater than or equal to the
    condition's minimum_level_required by the level ordering."

    The same MAXIMUM-required condition activates when the supervisee is at
    MAXIMUM — confirming the gate is the level comparison.

    Design: Difficulty/cross_entity_state_dependency/condition_activation_gated_by_supervisee_level
    """
    officer, sup = setup_active_supervisee(level_total=40)  # MAXIMUM
    oh = make_officer_headers(officer["id"])
    cond = add_condition(
        sup["id"], officer["id"],
        condition_type="ELECTRONIC_MONITORING", minimum_level_required="MAXIMUM",
    )
    activated = validate_success(api.activate_condition(sup["id"], cond["id"], oh), 200)
    assert activated["status"] == "ACTIVE"


# ─── Difficulty: cross_entity_state_dependency / transfer points gate ───
def test_transfer_accept_blocked_high_risk_points(api):
    """PRD §3.8: "Acceptance is permitted only when the transfer is REQUESTED, the
    supervisee is ACTIVE, and the supervisee's cumulative_violation_points is
    strictly below the revocation-referral threshold of 12 points ... an
    acceptance attempted at or above that threshold is rejected with
    ERR_TRANSFER_BLOCKED_HIGH_RISK (HTTP 409)."

    With cumulative 12 (two sustained FELONIES) but status reinstated to ACTIVE,
    accepting the open transfer is blocked on the points gate.

    Design: Difficulty/cross_entity_state_dependency/transfer_accept_gated_by_supervisee_points
    """
    officer, sup = setup_active_supervisee(level_total=30, ordered_term_months=36)
    oh = make_officer_headers(officer["id"])
    v_after = current_version(sup["id"], officer["id"])
    xfer = request_transfer(sup["id"], officer["id"], "NV", v_after)

    file_and_sustain(sup["id"], officer["id"], "FELONY")  # cumulative 6
    v2 = file_violation(sup["id"], officer["id"], "FELONY")
    sustain_violation(sup["id"], v2["id"])  # cumulative 12 -> REVOCATION_PENDING
    validate_success(api.reinstate_supervisee(sup["id"], make_judge_headers()), 200)

    sup_now = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_now["cumulative_violation_points"] == 12
    assert sup_now["status"] == "ACTIVE"

    res = api.accept_transfer(
        sup["id"], xfer["id"], {"decided_at": "2026-04-01T00:00:00.000Z"},
        make_compact_admin_headers(),
    )
    validate_error(res, "ERR_TRANSFER_BLOCKED_HIGH_RISK")


def test_transfer_accept_allowed_low_risk_points(api):
    """PRD §3.8: "the supervisee's cumulative_violation_points is strictly below the
    revocation-referral threshold of 12 points ... Acceptance moves the transfer
    to ACCEPTED and bubbles up to the root: the supervisee transitions from ACTIVE
    to the terminal TRANSFERRED_OUT"

    A low-risk (0 points) supervisee's transfer accepts successfully — the points
    gate distinguishes this from the blocked case.

    Design: Difficulty/cross_entity_state_dependency/transfer_accept_gated_by_supervisee_points
    """
    officer, sup, xfer = setup_supervisee_with_open_transfer()
    accepted = validate_success(
        api.accept_transfer(sup["id"], xfer["id"],
                            {"decided_at": "2026-04-10T00:00:00.000Z"},
                            make_compact_admin_headers()),
        200,
    )
    assert accepted["status"] == "ACCEPTED"


# ─── Difficulty: resource_temporal_overlap / transfer single-live-claim ───
def test_second_transfer_while_one_open_rejected(api):
    """PRD §3.8: "Only one live compact claim may exist at a time: if a transfer
    for this supervisee is already in REQUESTED or ACCEPTED status, a new transfer
    request is rejected with ERR_TRANSFER_ALREADY_OPEN (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/transfer_single_live_claim_overlap
    """
    officer, sup, xfer = setup_supervisee_with_open_transfer(receiving_state_code="NV")
    oh = make_officer_headers(officer["id"])
    v_now = current_version(sup["id"], officer["id"])
    res = api.create_transfer(
        sup["id"], create_transfer_payload("OR", v_now), oh
    )
    validate_error(res, "ERR_TRANSFER_ALREADY_OPEN")


def test_new_transfer_allowed_after_withdrawal(api):
    """PRD §3.8: "if a transfer for this supervisee is already in REQUESTED or
    ACCEPTED status, a new transfer request is rejected with
    ERR_TRANSFER_ALREADY_OPEN"
    PRD §3.8: "The originating Officer may instead withdraw a REQUESTED transfer,
    which moves it to WITHDRAWN, makes no change to the supervisee"

    Once the prior transfer is WITHDRAWN (no longer REQUESTED/ACCEPTED), a new
    transfer is accepted — confirming the rule keys on the live-claim status set,
    not on any transfer ever having existed.

    Design: Difficulty/resource_temporal_overlap/transfer_single_live_claim_overlap
    """
    officer, sup, xfer = setup_supervisee_with_open_transfer(receiving_state_code="NV")
    oh = make_officer_headers(officer["id"])
    validate_success(api.withdraw_transfer(sup["id"], xfer["id"], oh), 200)
    v_now = current_version(sup["id"], officer["id"])
    res = api.create_transfer(sup["id"], create_transfer_payload("OR", v_now), oh)
    new_xfer = validate_success(res, 201)
    assert new_xfer["status"] == "REQUESTED"


# ─── Difficulty: priority_pair / closed beats fiscal payment-exceeds ───
def test_closed_supervisee_beats_payment_exceeds(api):
    """PRD §3.11: "Filing a violation, sustaining a violation, creating a
    condition, scheduling a check-in, and tendering a payment are all blocked on a
    closed supervisee and rejected with ERR_SUPERVISEE_CLOSED (HTTP 409). This
    guard is in addition to, and evaluated ahead of, the per-resource state checks
    that each individual operation already enforces."

    A payment on a COMPLETED supervisee (which also has zero balance, so it would
    also exceed balance) returns ERR_SUPERVISEE_CLOSED, not
    ERR_PAYMENT_EXCEEDS_BALANCE.

    Design: Difficulty/priority_pair_validation_conflict/state_closed_beats_fiscal_payment_exceeds
    """
    officer, sup_id = setup_completed_supervisee()
    oh = make_officer_headers(officer["id"])
    res = api.create_payment(sup_id, {"amount_cents": 10000}, oh)
    validate_error(res, "ERR_SUPERVISEE_CLOSED")


def test_closed_supervisee_beats_payment_exceeds_after_transfer_out(api):
    """PRD §3.11: "Filing a violation, sustaining a violation, creating a
    condition, scheduling a check-in, and tendering a payment are all blocked on a
    closed supervisee and rejected with ERR_SUPERVISEE_CLOSED (HTTP 409)."
    PRD §3.11: "This guard is in addition to, and evaluated ahead of, the
    per-resource state checks that each individual operation already enforces."

    A payment on a TRANSFERRED_OUT supervisee (zero balance, so it would also
    exceed balance) returns the closed-guard error, not the fiscal error — the
    same closed-beats-fiscal priority, on a different terminal status.

    Design: Difficulty/priority_pair_validation_conflict/state_closed_beats_fiscal_payment_exceeds
    """
    officer, sup, xfer = setup_supervisee_with_open_transfer()
    oh = make_officer_headers(officer["id"])
    validate_success(
        api.accept_transfer(sup["id"], xfer["id"],
                            {"decided_at": "2026-04-10T00:00:00.000Z"},
                            make_compact_admin_headers()),
        200,
    )
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["status"] == "TRANSFERRED_OUT"
    res = api.create_payment(sup["id"], {"amount_cents": 10000}, oh)
    validate_error(res, "ERR_SUPERVISEE_CLOSED")


def test_segregation_blocked_by_invalid_state_on_dismissed(api):
    """PRD §3.5: "Sustaining a violation that is not in FILED status is rejected
    with ERR_INVALID_STATE (HTTP 409)."
    PRD §3.5: "the segregation-of-duties check ... is evaluated after the state
    check that confirms the violation is FILED."

    When the filer (same id) tries to sustain an already-DISMISSED violation, the
    state check (priority 10) fires first -> ERR_INVALID_STATE, not
    ERR_SEGREGATION_OF_DUTIES.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_invalid_state_on_sustain
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    v = file_violation(sup["id"], officer["id"], "TECHNICAL")
    validate_success(api.dismiss_violation(sup["id"], v["id"], make_judge_headers()), 200)
    # The acting judge id equals the filing officer id (would violate SoD if state allowed).
    res = api.sustain_violation(sup["id"], v["id"], make_judge_headers(officer["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_segregation_blocked_by_invalid_state_on_already_sustained(api):
    """PRD §3.5: "Sustaining a violation that is not in FILED status is rejected
    with ERR_INVALID_STATE (HTTP 409)."
    PRD §3.5: "the segregation-of-duties check ... is evaluated after the state
    check that confirms the violation is FILED."

    A violation already SUSTAINED (also non-FILED) re-sustained by the filer
    returns ERR_INVALID_STATE — the state check pre-empts the segregation check on
    a different non-FILED status.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_invalid_state_on_sustain
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    v = file_violation(sup["id"], officer["id"], "TECHNICAL")
    # First sustain by a distinct judge succeeds -> violation now SUSTAINED.
    validate_success(api.sustain_violation(sup["id"], v["id"], make_judge_headers()), 200)
    # Filer (same id) tries to sustain the already-SUSTAINED violation.
    res = api.sustain_violation(sup["id"], v["id"], make_judge_headers(officer["id"]))
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: state_machines / transfer_accept_bubbles_supervisee ───
def test_transfer_accept_bubbles_to_transferred_out_and_satisfies_conditions(api):
    """PRD §3.8: "Acceptance moves the transfer to ACCEPTED and bubbles up to the
    root: the supervisee transitions from ACTIVE to the terminal TRANSFERRED_OUT,
    all of the supervisee's ACTIVE conditions cascade to SATISFIED on the sending
    side"

    Design: Corner/state_machines/transfer_accept_bubbles_supervisee_to_transferred_out
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    cond = add_active_condition(
        sup["id"], officer["id"],
        condition_type="EMPLOYMENT", minimum_level_required="ADMINISTRATIVE",
    )
    v_now = current_version(sup["id"], officer["id"])
    xfer = request_transfer(sup["id"], officer["id"], "NV", v_now)

    accepted = validate_success(
        api.accept_transfer(sup["id"], xfer["id"],
                            {"decided_at": "2026-04-10T00:00:00.000Z"},
                            make_compact_admin_headers()),
        200,
    )
    assert accepted["status"] == "ACCEPTED"
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["status"] == "TRANSFERRED_OUT"
    cond_after = validate_success(api.get_condition(sup["id"], cond["id"], oh), 200)
    assert cond_after["status"] == "SATISFIED"


# ─── Corner: validations / transfer_same_state_code_rejected ───
def test_transfer_same_receiving_state_rejected(api):
    """PRD §3.8: "The receiving state must differ from the supervisee's
    sentence_state_code; a transfer whose receiving_state_code equals the sending
    state's code is a semantic error rejected with ERR_VALIDATION (HTTP 422)."

    Design: Corner/validations/transfer_same_state_code_rejected
    """
    officer, sup = setup_active_supervisee(level_total=10, sentence_state_code="CA")
    oh = make_officer_headers(officer["id"])
    v_now = current_version(sup["id"], officer["id"])
    res = api.create_transfer(sup["id"], create_transfer_payload("CA", v_now), oh)
    validate_error(res, "ERR_VALIDATION")


# ─── Corner: cross_cutting / OCC stale version ───
def test_transfer_create_stale_version_rejected(api):
    """PRD §2.6: "If expected_supervisee_version does not equal the supervisee's
    current version, the create is rejected with ERR_STALE_SUPERVISEE_VERSION
    (HTTP 412)."
    PRD §3.8: "A successful request mints the transfer in REQUESTED status and
    increments the supervisee's version by one."

    The first transfer create bumps the version; a retry (after withdrawal)
    carrying the pre-bump version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_supervisee_version_on_transfer_create
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    v1 = sup["version"]
    xfer = request_transfer(sup["id"], officer["id"], "NV", v1)
    validate_success(api.withdraw_transfer(sup["id"], xfer["id"], oh), 200)
    res = api.create_transfer(sup["id"], create_transfer_payload("OR", v1), oh)
    validate_error(res, "ERR_STALE_SUPERVISEE_VERSION")


# ─── Corner: cross_cutting / OCC correct version succeeds and bumps ───
def test_transfer_create_correct_version_succeeds_and_bumps(api):
    """PRD §2.6: "A request to create an InterstateTransfer for a supervisee must
    carry an expected_supervisee_version field whose value is the version of the
    parent Supervisee that the requester last observed."
    PRD §3.8: "A successful request mints the transfer in REQUESTED status and
    increments the supervisee's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    v_now = current_version(sup["id"], officer["id"])
    res = api.create_transfer(sup["id"], create_transfer_payload("NV", v_now), oh)
    validate_success(res, 201)
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["version"] == v_now + 1


# ─── Corner: rbac / officer_cannot_accept_transfer ───
def test_officer_cannot_accept_transfer(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."
    PRD §2.1: "A CompactAdministrator administers the interstate compact. Compact
    administrators register officers and accept or reject interstate-transfer
    requests."

    Accept is a CompactAdministrator capability; an Officer invoking it is denied.

    Design: Corner/rbac/officer_cannot_accept_transfer
    """
    officer, sup, xfer = setup_supervisee_with_open_transfer()
    oh = make_officer_headers(officer["id"])
    res = api.accept_transfer(
        sup["id"], xfer["id"], {"decided_at": "2026-04-01T00:00:00.000Z"}, oh
    )
    validate_error(res, "ERR_UNAUTHORIZED")
