"""Finalize/reopen cascades, cross-entity state dependencies, temporal-overlap
conflicts, and compensating-action invariants (PRD §2.6, §3.4-§3.8). Queue A.
"""
from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BILLING,
    INTAKE,
    SCHEDULER,
    book_companion_shift,
    create_oasis,
    open_episode,
    schedule_confirm_complete,
    schedule_visit,
    setup_active_episode,
    setup_draft_episode,
    setup_finalized_episode,
    set_clock,
)
from test_helpers.test_users import make_clinician_headers

WOUND_RATE = {
    "clinical_group": "WOUND", "base_30day_rate": 2000.00,
    "functional_weight_low": 0.95, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.05, "lupa_threshold": 5,
}
WOUND_OASIS = {"clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2}
MMTA_RATE = {
    "clinical_group": "MMTA_OTHER", "base_30day_rate": 1500.00,
    "functional_weight_low": 1.00, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.00, "lupa_threshold": 1,
}
MMTA_OASIS = {"clinical_group": "MMTA_OTHER", "functional_level": "LOW", "comorbidity_count": 0}


def _ledger(api, ep_id):
    return validate_paginated(api.list_payment_ledger(ep_id, BILLING))


# ===========================================================================
# Difficulty: finalize_cascade_ledger_patient_discharge_depth3 (≥2)
# ===========================================================================
def test_finalize_creates_ledger_and_discharges_patient(api):
    """PRD §3.8: "Finalize creates a PaymentLedger row capturing episode_id,
    payment_basis, gross_pdgm, mileage_offset, companion_offset, net_settlement,
    and a reversed flag set false. It appends a FINALIZED event and then a
    DISCHARGED event, sets the patient's status to DISCHARGED if the patient has
    no other non-terminal episode, and bumps the episode version."

    Design: Difficulty/transitive_cascade/finalize_cascade_ledger_patient_discharge_depth3
    """
    base = setup_finalized_episode(api)
    ep_id, pat_id = base["episode"]["id"], base["patient"]["id"]
    assert base["episode"]["status"] == "DISCHARGED"
    assert base["episode"]["final_payment"] == 3000.00
    rows, _ = _ledger(api, ep_id)
    assert len(rows) == 1
    assert rows[0]["net_settlement"] == 3000.00
    patient = validate_success(api.get_patient(pat_id, INTAKE))
    assert patient["status"] == "DISCHARGED"


def test_finalize_net_settlement_matches_final_payment(api):
    """PRD §3.8: "net_settlement equal to gross_pdgm plus mileage_offset plus
    companion_offset. That net amount is also written to the episode's
    final_payment".

    Design: Difficulty/transitive_cascade/finalize_cascade_ledger_patient_discharge_depth3
    """
    base = setup_finalized_episode(api)
    ep_id = base["episode"]["id"]
    rows, _ = _ledger(api, ep_id)
    assert rows[0]["net_settlement"] == base["episode"]["final_payment"]


# ===========================================================================
# Difficulty: reopen_cascade_ledger_reverse_patient_reactivate_depth2 (≥2)
# ===========================================================================
def test_reopen_reverses_ledger_and_reactivates_patient(api):
    """PRD §3.8: "Reopening is a compensating action: it sets that ledger row's
    reversed flag to true (conceptually backing out the net_settlement), resets
    the episode's final_payment to zero, restores the patient's status to ACTIVE,
    appends a LEDGER_REVERSED event, and bumps the episode version."

    Design: Difficulty/transitive_cascade/reopen_cascade_ledger_reverse_patient_reactivate_depth2
    """
    base = setup_finalized_episode(api)
    ep_id, pat_id = base["episode"]["id"], base["patient"]["id"]
    reopened = validate_success(api.reopen_episode(ep_id, BILLING))
    assert reopened["status"] == "ACTIVE"
    assert reopened["final_payment"] == 0
    rows, _ = _ledger(api, ep_id)
    assert rows[0]["reversed"] is True
    patient = validate_success(api.get_patient(pat_id, INTAKE))
    assert patient["status"] == "ACTIVE"


def test_reopen_drives_episode_discharged_to_active(api):
    """PRD §3.8: "A finalized episode can be reopened by the BillingManager within
    a 30-day reopen window measured from the finalize event, driving DISCHARGED ->
    ACTIVE."

    Design: Difficulty/transitive_cascade/reopen_cascade_ledger_reverse_patient_reactivate_depth2
    """
    base = setup_finalized_episode(api)
    ep_id = base["episode"]["id"]
    assert base["episode"]["status"] == "DISCHARGED"
    reopened = validate_success(api.reopen_episode(ep_id, BILLING))
    assert reopened["status"] == "ACTIVE"


# ===========================================================================
# Difficulty: visit_complete_requires_episode_active (≥2)
# ===========================================================================
def _confirmed_visit_then_recert_pending(api):
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    recert_oasis = create_oasis(
        base["patient"]["id"], rn_id, api,
        assessment_type="RECERTIFICATION", assessment_date="2026-03-25T08:00:00Z",
        clinical_group="WOUND", functional_level="HIGH", comorbidity_count=2,
    )
    v = schedule_visit(ep_id, rn_id, api,
                       scheduled_start="2026-03-26T09:00:00Z", scheduled_end="2026-03-26T10:00:00Z")
    validate_success(api.confirm_visit(v["id"], make_clinician_headers(rn_id)))
    set_clock("2026-03-26T11:00:00Z", api)
    validate_success(api.create_recert_request(ep_id, {"recert_oasis_id": recert_oasis["id"]}, INTAKE), 201)
    return ep_id, rn_id, v["id"]


def test_complete_blocked_when_episode_recert_pending(api):
    """PRD §3.4: "The same clinician later completes the visit, driving
    CONFIRMED -> COMPLETED, but only after the visit window has elapsed ... and
    only while they are the assigned clinician and the episode remains ACTIVE."
    PRD §3.4: "a non-active episode with ERR_EPISODE_NOT_ACTIVE".

    Design: Difficulty/cross_entity_state_dependency/visit_complete_requires_episode_active
    """
    ep_id, rn_id, vid = _confirmed_visit_then_recert_pending(api)
    resp = api.complete_visit(vid, make_clinician_headers(rn_id))
    validate_error(resp, "ERR_EPISODE_NOT_ACTIVE", 409)


def test_visit_stays_confirmed_after_blocked_complete(api):
    """PRD §3.4: "a non-active episode with ERR_EPISODE_NOT_ACTIVE". (The blocked
    completion must leave the visit in its prior CONFIRMED state.)

    Design: Difficulty/cross_entity_state_dependency/visit_complete_requires_episode_active
    """
    ep_id, rn_id, vid = _confirmed_visit_then_recert_pending(api)
    api.complete_visit(vid, make_clinician_headers(rn_id))
    visit = validate_success(api.get_visit(vid, SCHEDULER))
    assert visit["status"] == "CONFIRMED"


# ===========================================================================
# Difficulty: episode_create_requires_patient_no_open_episode (≥2)
# ===========================================================================
def test_second_episode_for_open_patient_rejected(api):
    """PRD §3.2: "Because a patient may have at most one non-terminal episode at a
    time, an attempt to open an episode for a patient who already holds a DRAFT,
    ACTIVE, or RECERT_PENDING episode is rejected with
    ERR_PATIENT_HAS_OPEN_EPISODE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/episode_create_requires_patient_no_open_episode
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    oasis2 = create_oasis(
        base["patient"]["id"], base["rn"]["id"], api,
        assessment_type="START_OF_CARE", assessment_date="2026-02-01T09:00:00Z",
        clinical_group="WOUND", functional_level="HIGH", comorbidity_count=2,
    )
    resp = api.create_episode(
        {"patient_id": base["patient"]["id"], "soc_oasis_id": oasis2["id"]}, INTAKE)
    validate_error(resp, "ERR_PATIENT_HAS_OPEN_EPISODE", 409)


def test_second_episode_blocked_while_first_is_draft(api):
    """PRD §3.2: "an attempt to open an episode for a patient who already holds a
    DRAFT, ACTIVE, or RECERT_PENDING episode is rejected with
    ERR_PATIENT_HAS_OPEN_EPISODE (HTTP 409)." (First episode still DRAFT.)

    Design: Difficulty/cross_entity_state_dependency/episode_create_requires_patient_no_open_episode
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    oasis2 = create_oasis(
        base["patient"]["id"], base["rn"]["id"], api,
        assessment_type="START_OF_CARE", assessment_date="2026-02-01T09:00:00Z",
        clinical_group="WOUND", functional_level="HIGH", comorbidity_count=2,
    )
    resp = api.create_episode(
        {"patient_id": base["patient"]["id"], "soc_oasis_id": oasis2["id"]}, INTAKE)
    validate_error(resp, "ERR_PATIENT_HAS_OPEN_EPISODE", 409)


# ===========================================================================
# Difficulty: clinician_visit_half_open_overlap_touching_allowed (≥2)
# ===========================================================================
def test_overlapping_visit_interior_rejected(api):
    """PRD §3.4: "The new window must also not overlap any non-terminal visit
    already held by the same clinician — because the interval is half-open, a
    visit ending exactly when another begins is permitted, but any true overlap
    is rejected with ERR_CLINICIAN_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/clinician_visit_half_open_overlap_touching_allowed
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    schedule_visit(ep_id, rn_id, api,
                   scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    resp = api.create_visit(ep_id, {
        "clinician_id": rn_id, "discipline": "RN",
        "scheduled_start": "2026-02-03T09:30:00Z", "scheduled_end": "2026-02-03T10:30:00Z",
    }, SCHEDULER)
    validate_error(resp, "ERR_CLINICIAN_DOUBLE_BOOKED", 409)


def test_touching_visit_endpoints_allowed(api):
    """PRD §3.4: "because the interval is half-open, a visit ending exactly when
    another begins is permitted". (Second visit starts exactly at first's end.)

    Design: Difficulty/resource_temporal_overlap/clinician_visit_half_open_overlap_touching_allowed
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    schedule_visit(ep_id, rn_id, api,
                   scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    resp = api.create_visit(ep_id, {
        "clinician_id": rn_id, "discipline": "RN",
        "scheduled_start": "2026-02-03T10:00:00Z", "scheduled_end": "2026-02-03T11:00:00Z",
    }, SCHEDULER)
    v2 = validate_success(resp, 201)
    assert v2["status"] == "SCHEDULED"


# ===========================================================================
# Difficulty: companion_shift_30min_travel_buffer_conflict (≥2)
# ===========================================================================
def test_companion_shift_buffer_violation_rejected(api):
    """PRD §3.5: "consecutive shifts of the same aide must respect a travel buffer
    of half an hour (30 minutes) between one shift's end and the next shift's
    start; a violation of either constraint is rejected with
    ERR_COMPANION_SHIFT_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/companion_shift_30min_travel_buffer_conflict
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 8},
        with_hha=True,
    )
    ep_id, hha_id = base["episode"]["id"], base["hha"]["id"]
    book_companion_shift(ep_id, hha_id, api,
                        shift_start="2026-02-03T13:00:00Z", shift_end="2026-02-03T14:00:00Z")
    # next shift starts 15 min after prior end -> gap < 30m buffer
    resp = api.create_companion_shift(ep_id, {
        "clinician_id": hha_id,
        "shift_start": "2026-02-03T14:15:00Z", "shift_end": "2026-02-03T15:00:00Z",
    }, SCHEDULER)
    validate_error(resp, "ERR_COMPANION_SHIFT_CONFLICT", 409)


def test_companion_shift_respecting_buffer_allowed(api):
    """PRD §3.5: "consecutive shifts of the same aide must respect a travel buffer
    of half an hour (30 minutes) between one shift's end and the next shift's
    start". (A 30-minute gap satisfies the buffer.)

    Design: Difficulty/resource_temporal_overlap/companion_shift_30min_travel_buffer_conflict
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 8},
        with_hha=True,
    )
    ep_id, hha_id = base["episode"]["id"], base["hha"]["id"]
    book_companion_shift(ep_id, hha_id, api,
                        shift_start="2026-02-03T13:00:00Z", shift_end="2026-02-03T14:00:00Z")
    resp = api.create_companion_shift(ep_id, {
        "clinician_id": hha_id,
        "shift_start": "2026-02-03T14:30:00Z", "shift_end": "2026-02-03T15:00:00Z",
    }, SCHEDULER)
    cs2 = validate_success(resp, 201)
    assert cs2["status"] == "BOOKED"


# ===========================================================================
# Difficulty: companion_hours_zero_authorized_empty_deliver_rejected (≥2)
# ===========================================================================
def test_deliver_blocked_when_zero_authorized(api):
    """PRD §3.5: "delivery is blocked when accruing this shift's hours would carry
    the episode's companion_hours_used above the companion_hours_authorized figure
    on the episode's active plan; that overflow is rejected with
    ERR_COMPANION_HOURS_EXCEEDED (HTTP 422)." (authorized == 0.)

    Design: Difficulty/boundary_precision_check/companion_hours_zero_authorized_empty_deliver_rejected
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 0},
        with_hha=True,
    )
    ep_id, hha_id = base["episode"]["id"], base["hha"]["id"]
    cs = book_companion_shift(ep_id, hha_id, api,
                             shift_start="2026-02-03T13:00:00Z", shift_end="2026-02-03T14:00:00Z")
    set_clock("2026-02-03T15:00:00Z", api)
    resp = api.deliver_companion_shift(cs["id"], SCHEDULER)
    validate_error(resp, "ERR_COMPANION_HOURS_EXCEEDED", 422)


def test_zero_authorized_leaves_companion_hours_used_zero(api):
    """PRD §3.5: "delivery is blocked when accruing this shift's hours would carry
    the episode's companion_hours_used above the companion_hours_authorized figure
    on the episode's active plan". (Blocked delivery accrues nothing.)

    Design: Difficulty/boundary_precision_check/companion_hours_zero_authorized_empty_deliver_rejected
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 0},
        with_hha=True,
    )
    ep_id, hha_id = base["episode"]["id"], base["hha"]["id"]
    cs = book_companion_shift(ep_id, hha_id, api,
                             shift_start="2026-02-03T13:00:00Z", shift_end="2026-02-03T14:00:00Z")
    set_clock("2026-02-03T15:00:00Z", api)
    api.deliver_companion_shift(cs["id"], SCHEDULER)
    ep = validate_success(api.get_episode(ep_id, INTAKE))
    assert ep["companion_hours_used"] == 0


# ===========================================================================
# Difficulty: cancel_episode_unlocks_oasis_lock_count_invariant (≥2)
# ===========================================================================
def test_cancel_draft_episode_unlocks_oasis(api):
    """PRD §3.2: "Cancellation is permitted only while the episode is in DRAFT; it
    supersedes every ACTIVE plan on the episode, unlocks the seeding OASIS so it
    can seed a corrected episode, appends a CANCELLED event, and bumps the episode
    version."

    Design: Difficulty/compensating_invariant/cancel_episode_unlocks_oasis_lock_count_invariant
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep_id, oasis_id = base["episode"]["id"], base["oasis"]["id"]
    cancelled = validate_success(api.cancel_episode(ep_id, INTAKE))
    assert cancelled["status"] == "CANCELLED"
    oasis = validate_success(api.get_oasis(oasis_id, INTAKE))
    assert oasis["locked"] is False


def test_unlocked_oasis_can_seed_new_episode_after_cancel(api):
    """PRD §3.2: "unlocks the seeding OASIS so it can seed a corrected episode".
    (Net lock state restored: the same OASIS opens a fresh episode after cancel.)

    Design: Difficulty/compensating_invariant/cancel_episode_unlocks_oasis_lock_count_invariant
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep_id, oasis_id, pat_id = base["episode"]["id"], base["oasis"]["id"], base["patient"]["id"]
    validate_success(api.cancel_episode(ep_id, INTAKE))
    ep2 = open_episode(pat_id, oasis_id, api)
    assert ep2["status"] == "DRAFT"


# ===========================================================================
# Difficulty: reopen_reverses_final_payment_money_invariant (≥2)
# ===========================================================================
def test_reopen_resets_final_payment_to_zero(api):
    """PRD §3.8: "Reopening is a compensating action: it sets that ledger row's
    reversed flag to true (conceptually backing out the net_settlement), resets
    the episode's final_payment to zero".

    Design: Difficulty/compensating_invariant/reopen_reverses_final_payment_money_invariant
    """
    base = setup_finalized_episode(api)
    ep_id = base["episode"]["id"]
    assert base["episode"]["final_payment"] == 3000.00
    reopened = validate_success(api.reopen_episode(ep_id, BILLING))
    assert reopened["final_payment"] == 0


def test_reopen_marks_ledger_reversed(api):
    """PRD §3.8: "it sets that ledger row's reversed flag to true (conceptually
    backing out the net_settlement)".

    Design: Difficulty/compensating_invariant/reopen_reverses_final_payment_money_invariant
    """
    base = setup_finalized_episode(api)
    ep_id = base["episode"]["id"]
    validate_success(api.reopen_episode(ep_id, BILLING))
    rows, _ = _ledger(api, ep_id)
    assert rows[0]["reversed"] is True
