"""NICU escalation, the step-down cascade and bed promotion, manual bed placement
with half-open interval overlap, and the bed-occupancy conservation invariant.

Difficulty queue: transitive_cascade (step-down), resource_temporal_overlap (bed),
compensating_invariant (bed occupancy).
Corner queue: nicu-stay valid transitions, NICU criteria validations, OCC, consistency.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    assert_bed_vacated, assert_bed_occupied_by,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f


# =========================================================================
# Difficulty/transitive_cascade/step_down_frees_bed_promotes_waiting_stay_depth3
# =========================================================================
class TestStepDownPromotionCascade:
    def _setup_two_competing_stays(self, api):
        """One LEVEL_3 bed; newbornA ACTIVE on it; newbornB PENDING_BED waiting."""
        fx.set_clock("2026-03-05T12:00:00Z")
        bed = fx.create_bed(acuity_level="LEVEL_3")
        policy = fx.create_policy()
        reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
        nb_a = fx.record_birth(
            reg["id"], birth_datetime="2026-03-05T09:00:00Z", birth_sequence=1,
            weight_grams=1500, gestational_age_weeks=31, apgar_5min=9)
        nb_b = fx.record_birth(
            reg["id"], birth_datetime="2026-03-05T10:00:00Z", birth_sequence=2,
            weight_grams=1600, gestational_age_weeks=32, apgar_5min=9)
        stay_a = fx.escalate(nb_a["id"], required_level="LEVEL_3",
                             admitted_at="2026-03-05T09:00:00Z")
        stay_b = fx.escalate(nb_b["id"], required_level="LEVEL_3",
                             admitted_at="2026-03-05T10:00:00Z")
        return bed, nb_a, nb_b, stay_a, stay_b

    def test_step_down_promotes_waiting_stay_onto_freed_bed(self, api):
        """PRD §3.4: "It then promotes the longest-waiting eligible stay onto that
        freed bed: among stays still in PENDING_BED whose required_level is at or below
        the freed bed's acuity_level, it selects the one with the earliest admitted_at,
        breaking ties by the earliest created_at, and gives it the bed — assigning its
        nicu_bed_id, setting it to ACTIVE, occupying the bed, and journaling a
        NICU_BED_ASSIGNED event for the promoted stay."

        Design: Difficulty/transitive_cascade/step_down_frees_bed_promotes_waiting_stay_depth3
        """
        bed, nb_a, nb_b, stay_a, stay_b = self._setup_two_competing_stays(api)
        # stay_b was created when the only bed was already occupied -> PENDING_BED.
        assert stay_b["status"] == "PENDING_BED"

        get_success_data(api.step_down(nb_a["id"], fx.NEO))

        stay_a_final = validate_success(api.get_nicu_stay(stay_a["id"], fx.NEO))
        stay_b_final = validate_success(api.get_nicu_stay(stay_b["id"], fx.NEO))
        assert stay_a_final["status"] == "STEPPED_DOWN", (
            f"stepped-down stay should be STEPPED_DOWN, got {stay_a_final['status']}")
        assert stay_b_final["status"] == "ACTIVE", (
            f"waiting stay should be promoted to ACTIVE, got {stay_b_final['status']}")
        assert stay_b_final["nicu_bed_id"] == bed["id"], (
            "promoted stay must occupy the freed bed")

    def test_step_down_freed_bed_now_occupied_by_promoted_stay(self, api):
        """PRD §3.4: "and frees the bed by setting its occupancy_status back to VACANT
        and clearing its current_stay_id."
        PRD §3.4: "occupying the bed, and journaling a NICU_BED_ASSIGNED event for the
        promoted stay."

        Design: Difficulty/transitive_cascade/step_down_frees_bed_promotes_waiting_stay_depth3
        """
        bed, nb_a, nb_b, stay_a, stay_b = self._setup_two_competing_stays(api)

        get_success_data(api.step_down(nb_a["id"], fx.NEO))

        bed_final = validate_success(api.get_nicu_bed(bed["id"], fx.NEO))
        # The bed was freed then re-occupied by the promoted stay_b in the same cascade.
        assert_bed_occupied_by(bed_final, stay_b["id"])


# =========================================================================
# Difficulty/compensating_invariant/stepdown_conserves_nicu_bed_occupancy_count
# =========================================================================
class TestBedOccupancyConservation:
    def test_escalate_occupies_bed(self, api):
        """PRD §3.4: "On success the selector assigns the chosen bed's id to the stay's
        nicu_bed_id, sets the stay's status to ACTIVE, sets the bed's occupancy_status
        to OCCUPIED, points the bed's current_stay_id at the stay"

        Design: Difficulty/compensating_invariant/stepdown_conserves_nicu_bed_occupancy_count
        """
        fx.set_clock("2026-03-05T09:00:00Z")
        newborn, stay, _ = fx.setup_escalated_active(
            required_level="LEVEL_3", bed_acuity="LEVEL_3",
            admitted_at="2026-03-05T09:00:00Z")
        bed_id = stay["nicu_bed_id"]
        bed = validate_success(api.get_nicu_bed(bed_id, fx.NEO))
        assert_bed_occupied_by(bed, stay["id"])

    def test_step_down_with_no_waiting_stay_vacates_bed(self, api):
        """PRD §3.4: "the server moves the newborn from NICU_ADMITTED to STEP_DOWN,
        sets the infant's open stay to STEPPED_DOWN and stamps that stay's discharged_at
        with the current clock, and frees the bed by setting its occupancy_status back
        to VACANT and clearing its current_stay_id."

        Design: Difficulty/compensating_invariant/stepdown_conserves_nicu_bed_occupancy_count
        """
        fx.set_clock("2026-03-05T09:00:00Z")
        newborn, stay, bed = fx.setup_escalated_active(
            required_level="LEVEL_3", bed_acuity="LEVEL_3",
            admitted_at="2026-03-05T09:00:00Z")
        fx.set_clock("2026-03-05T12:00:00Z")

        get_success_data(api.step_down(newborn["id"], fx.NEO))

        bed_final = validate_success(api.get_nicu_bed(bed["id"], fx.NEO))
        stay_final = validate_success(api.get_nicu_stay(stay["id"], fx.NEO))
        # No waiting stay -> bed returns to VACANT, occupied count conserved (0 == active 0).
        assert_bed_vacated(bed_final)
        assert stay_final["status"] == "STEPPED_DOWN", (
            f"the open stay should be STEPPED_DOWN, got {stay_final['status']}")


# =========================================================================
# Difficulty/resource_temporal_overlap/nicu_bed_halfopen_interval_overlap_rejected_adjacent_ok
# DELETED (2 tests): test_manual_placement_overlapping_prior_interval_rejected and
# test_manual_placement_onto_vacant_bed_with_no_history_succeeds.
#
# Both asserted outcomes of POST /nicu-beds/{bed}/assign-stay (manual placement)
# that are UNREACHABLE under any PRD-faithful operation sequence. PRD §3.4 makes
# manual placement require a stay in PENDING_BED placed onto a VACANT bed whose
# acuity_level >= the stay's required_level. But the only mechanism that can make
# a bed VACANT after escalation is step-down, and PRD §3.4 mandates that step-down
# immediately PROMOTES the longest-waiting PENDING_BED stay whose required_level is
# <= the freed bed's acuity_level — an eligibility predicate IDENTICAL to the manual-
# placement acuity precondition. Therefore no faithful state can ever present a
# PENDING_BED stay alongside a VACANT acuity-compatible bed: any such stay is auto-
# claimed by the bed selector at escalation or by the promotion cascade at step-down.
# A stay that dodges promotion (by requiring a higher level than the freed bed) then
# fails the manual-placement acuity check (ERR_INVALID_STATE) before the overlap
# check is ever reached — exactly what the implementation returns. STEP 1b unique-
# derivability fails: the asserted ERR_BED_INTERVAL_OVERLAP / successful-placement
# outcomes cannot be produced by any PRD-faithful implementation.
# Scaffold rule that drove generation:
#   resource_temporal_overlap/nicu_bed_halfopen_interval_overlap_rejected_adjacent_ok
# (the scaffold's own setup recipe re-escalates newbornB onto the just-freed bed,
# which auto-claims it — the design never reaches a manual-placement-able state).
# =========================================================================


# =========================================================================
# Corner/state_machines/nicu_stay_cancel_from_pending_bed
# =========================================================================
def test_pending_bed_stay_can_be_cancelled(api):
    """PRD §3.4: "a neonatologist may cancel a stay that is still in PENDING_BED — for
    instance when the infant is transferred to another hospital — moving it from
    PENDING_BED to CANCELLED and incrementing the stay's version."

    Design: Corner/state_machines/nicu_stay_cancel_from_pending_bed
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    # No beds in the pool -> the escalated stay stays PENDING_BED.
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=1500, gestational_age_weeks=31, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")
    stay = fx.escalate(newborn["id"], required_level="LEVEL_3",
                       admitted_at="2026-03-05T10:30:00Z")
    assert stay["status"] == "PENDING_BED"

    data = validate_success(api.cancel_nicu_stay(stay["id"], fx.NEO))
    assert data["status"] == "CANCELLED", (
        f"a PENDING_BED stay must cancel to CANCELLED, got {data['status']}")


# =========================================================================
# Corner/validations/room_in_nicu_criteria_met_rejected
# =========================================================================
def test_room_in_blocked_when_nicu_criteria_met(api):
    """PRD §3.3: "If the infant in fact meets the NICU clinical criteria, room-in is
    forbidden and the attempt is rejected with ERR_NICU_CRITERIA_MET — such an infant
    must be escalated instead."

    Design: Corner/validations/room_in_nicu_criteria_met_rejected
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    # gestational_age_weeks 33 (< 35) meets NICU criteria.
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=2400, gestational_age_weeks=33, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")

    resp = api.room_in(newborn["id"], fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_NICU_CRITERIA_MET.value)


# =========================================================================
# Corner/validations/nicu_escalate_criteria_not_met_rejected
# =========================================================================
def test_escalate_from_born_blocked_when_criteria_not_met(api):
    """PRD §3.3: "Escalating from BORN requires that the infant actually meet the NICU
    clinical criteria; an attempt to escalate a BORN infant that does not meet them is
    rejected with ERR_NICU_CRITERIA_NOT_MET."

    Design: Corner/validations/nicu_escalate_criteria_not_met_rejected
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    fx.create_bed(acuity_level="LEVEL_3")
    # Healthy newborn: ga 39, apgar 9, weight 3200 -> clear of criteria.
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=3200, gestational_age_weeks=39, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")
    nb_v = fx.get_newborn_version(newborn["id"])

    resp = api.nicu_escalate(
        newborn["id"],
        f.nicu_escalate_payload(nb_v, required_level="LEVEL_3", admitted_at="2026-03-05T10:30:00Z"),
        fx.NEO)
    validate_error(resp, ApiErrorId.ERR_NICU_CRITERIA_NOT_MET.value)


# =========================================================================
# Corner/validations/step_down_without_active_stay_rejected
# =========================================================================
def test_step_down_without_active_stay_rejected(api):
    """PRD §3.4: "a newborn whose only stay is still PENDING_BED (never bedded) cannot
    step down, and such an attempt is rejected with ERR_NO_ACTIVE_NICU_STAY."

    Design: Corner/validations/step_down_without_active_stay_rejected
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    # No beds -> escalation leaves the stay PENDING_BED (NICU_ADMITTED but unbedded).
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=1500, gestational_age_weeks=31, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")
    fx.escalate(newborn["id"], required_level="LEVEL_3", admitted_at="2026-03-05T10:30:00Z")

    resp = api.step_down(newborn["id"], fx.NEO)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_NICU_STAY.value)


# =========================================================================
# Corner/errors/error_dependent_slots_exhausted_triggerable
#   (kept in dependents file — see test_04)
# =========================================================================


# =========================================================================
# Corner/cross_cutting_complexity_layers/occ_nicu_escalate_stale_newborn_version_rejected
# =========================================================================
def test_nicu_escalate_stale_newborn_version_rejected(api):
    """PRD §2.7: "If that value does not match the newborn's current version — because
    another writer has already escalated the same infant, creating a stay that
    legitimately claimed a scarce bed and bumping the newborn's version — the
    escalation is rejected with ERR_STALE_VERSION at HTTP 412, and no stay is created."

    Design: Corner/cross_cutting_complexity_layers/occ_nicu_escalate_stale_newborn_version_rejected
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    fx.create_bed(acuity_level="LEVEL_3")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=3200, gestational_age_weeks=39, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")
    stale_v = fx.get_newborn_version(newborn["id"])
    # room-in bumps the newborn version so stale_v is now out of date.
    get_success_data(api.room_in(newborn["id"], fx.NURSE))

    resp = api.nicu_escalate(
        newborn["id"],
        f.nicu_escalate_payload(stale_v, required_level="LEVEL_3",
                                admitted_at="2026-03-05T11:00:00Z"),
        fx.NEO)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# =========================================================================
# Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_write
# =========================================================================
def test_newborn_version_increments_on_room_in(api):
    """PRD §2.4: "The version field is an integer that begins at its initial value and
    increments by one on every mutation of the resource"
    PRD §3.3: "The room-in transition increments the newborn's version."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_write
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=3200, gestational_age_weeks=39, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")
    assert newborn["version"] == 1, f"a freshly recorded newborn starts at version 1, got {newborn['version']}"

    data = validate_success(api.room_in(newborn["id"], fx.NURSE))
    assert data["version"] == 2, (
        f"version should increment to 2 after one room-in mutation, got {data['version']}")


# =========================================================================
# Corner/consistency_model/immediate_consistency_escalate_reflected_in_same_response
# =========================================================================
def test_escalation_returns_active_stay_with_bed_in_same_response(api):
    """PRD §2.5: "the server does not merely flip the infant's status — it creates the
    stay record, runs the bed selector, may occupy a bed, and journals the event, all
    as one transition."
    PRD §3.4: "On success the selector assigns the chosen bed's id to the stay's
    nicu_bed_id, sets the stay's status to ACTIVE"

    Design: Corner/consistency_model/immediate_consistency_escalate_reflected_in_same_response
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    bed = fx.create_bed(acuity_level="LEVEL_3")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=1500, gestational_age_weeks=31, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")
    nb_v = fx.get_newborn_version(newborn["id"])

    data = validate_success(api.nicu_escalate(
        newborn["id"],
        f.nicu_escalate_payload(nb_v, required_level="LEVEL_3",
                                admitted_at="2026-03-05T11:00:00Z"),
        fx.NEO), expected_status=201)
    assert data["status"] == "ACTIVE", (
        f"the returned stay must already be ACTIVE in the same response, got {data['status']}")
    assert data["nicu_bed_id"] == bed["id"], (
        "the returned stay must already name the occupied bed in the same response")
