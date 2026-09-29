"""Two rules could each reject one request; the declared order decides which speaks."""

from test_helpers import (
    ERR_ABSOLUTE_CONTRAINDICATION,
    ERR_ASSET_CAPACITY_EXCEEDED,
    ERR_AUTHORIZATION_NOT_GRANTED,
    ERR_CASE_FROZEN,
    ERR_COLD_ISCHEMIC_LIMIT_EXCEEDED,
    accepted_organ,
    assert_team_ledger,
    book_operation,
    cleared_referral,
    create_asset,
    create_team,
    cross_clamp,
    dispatch_transport,
    donor_case_payload,
    file_serology,
    finalize_authorization,
    frozen_case_by_donor_loss,
    open_registry_authorization,
    read_authorization,
    read_case,
    read_hospital,
    read_organ,
    read_referral,
    read_screening,
    read_team,
    recovery_operation_payload,
    transport_payload,
    validate_error,
    validate_paginated,
)


# ---------------------------------------------------------------------------
# Case creation: authorization state (rule 16) before contraindication (rule 24)
# ---------------------------------------------------------------------------
def _cleared_referral_with_open_packet_and_positive_nat(env):
    bundle = cleared_referral(env, "2026-08-16T09:00:00Z", patient_mrn="MRN-7901")
    bundle.authorization = open_registry_authorization(
        env, bundle.referral_id, registry_document_ref="REG-7901"
    )
    result = file_serology(
        env,
        bundle.screening_id,
        "HIV_NAT",
        "POSITIVE",
        resulted_at="2026-08-16T08:50:00Z",
        nat_confirmed=True,
    )
    assert result["absolute_contraindication_marker"] is True
    screening = read_screening(env, bundle.screening_id)
    assert screening["status"] == "CLEARED"
    assert screening["absolute_contraindication"] is True
    return bundle


def test_authorization_state_gate_masks_the_contraindication_gate(env):
    """An unfinalized packet is reported before the serologic bar is consulted.

    PRD 2.10: "16. **Authorization granted for conversion** —
    `ERR_AUTHORIZATION_NOT_GRANTED`, on `POST /opo/donor-cases`."
    PRD 2.10: "24. **Absolute contraindication** —
    `ERR_ABSOLUTE_CONTRAINDICATION`, on
    `POST /opo/eligibility-screenings/{id}/decision` and `POST /opo/donor-cases`."
    PRD 2.10: "Earlier rules mask later ones, so the ordering is part of the
    contract and not an implementation detail."

    Design: Difficulty/priority_pair_validation_conflict/case_creation_state_gate_precedes_contraindication_safety_gate
    """
    bundle = _cleared_referral_with_open_packet_and_positive_nat(env)

    refused = env.api.create_donor_case(
        donor_case_payload(
            bundle.referral_id, bundle.authorization_id, donor_code="D-7901"
        ),
        env.donor,
    )
    validate_error(refused, ERR_AUTHORIZATION_NOT_GRANTED)


def test_masked_conversion_attempt_leaves_no_case_and_no_side_effects(env):
    """The refused conversion writes nothing anywhere.

    PRD 3.4: "The named authorization must be in `AUTHORIZED`, otherwise
    `ERR_AUTHORIZATION_NOT_GRANTED`."
    PRD 3.4: "On success the referral advances `AUTH_PENDING → CONVERTED` and
    the hospital's `converted_donor_count` increases by one."

    Design: Difficulty/priority_pair_validation_conflict/case_creation_state_gate_precedes_contraindication_safety_gate
    """
    bundle = _cleared_referral_with_open_packet_and_positive_nat(env)

    env.api.create_donor_case(
        donor_case_payload(
            bundle.referral_id, bundle.authorization_id, donor_code="D-7901"
        ),
        env.donor,
    )

    listed = env.api.list_donor_cases(env.donor, {"referral_id": bundle.referral_id})
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 0
    assert rows == []

    assert read_referral(env, bundle.referral_id)["status"] == "AUTH_PENDING"
    assert read_authorization(env, bundle.authorization_id)["status"] == (
        "REGISTRY_CONFIRMED"
    )
    assert read_hospital(env, bundle.hospital_id)["converted_donor_count"] == 0


def test_contraindication_gate_speaks_once_the_packet_is_authorized(env):
    """With the earlier rule satisfied, the serologic bar is the one that refuses.

    PRD 3.4: "the screening's `absolute_contraindication` must be false,
    otherwise `ERR_ABSOLUTE_CONTRAINDICATION` — this is the gate that catches a
    serology result filed after clearance".

    Design: Difficulty/priority_pair_validation_conflict/case_creation_state_gate_precedes_contraindication_safety_gate
    """
    bundle = _cleared_referral_with_open_packet_and_positive_nat(env)
    finalize_authorization(env, bundle.authorization_id, as_user="auth-2")

    refused = env.api.create_donor_case(
        donor_case_payload(
            bundle.referral_id, bundle.authorization_id, donor_code="D-7901"
        ),
        env.donor,
    )
    validate_error(refused, ERR_ABSOLUTE_CONTRAINDICATION)


# ---------------------------------------------------------------------------
# Transport: cold-ischemic ceiling (rule 34) before asset capacity (rule 42)
# ---------------------------------------------------------------------------
def _two_recovered_organs_sharing_one_asset(env):
    clock = "2026-08-17T05:00:00Z"
    kidney = accepted_organ(env, "KIDNEY_LEFT", clock)
    kidney.team = create_team(env, specialty="ABDOMINAL", turnaround_buffer_minutes=90)
    kidney.operation = book_operation(
        env,
        kidney.case_id,
        kidney.team["id"],
        "2026-08-17T05:30:00Z",
        "2026-08-17T07:30:00Z",
    )

    heart = accepted_organ(env, "HEART", clock)
    heart.team = create_team(env, specialty="THORACIC", turnaround_buffer_minutes=90)
    heart.operation = book_operation(
        env,
        heart.case_id,
        heart.team["id"],
        "2026-08-17T05:30:00Z",
        "2026-08-17T07:30:00Z",
    )

    env.set_clock("2026-08-17T06:00:00Z")
    cross_clamp(env, kidney.operation["id"])
    cross_clamp(env, heart.operation["id"])

    asset = create_asset(env, mode="FIXED_WING", concurrent_leg_capacity=1)
    kidney.asset = asset
    heart.asset = asset

    kidney.organs["KIDNEY_LEFT"] = dispatch_transport(
        env,
        kidney.only_organ_id,
        asset["id"],
        "2026-08-17T08:00:00Z",
        "2026-08-17T09:00:00Z",
        transport_mode="FIXED_WING",
    )
    assert kidney.organ("KIDNEY_LEFT")["projected_cold_ischemic_minutes"] == 225
    return kidney, heart


def test_cold_ischemic_ceiling_masks_the_asset_capacity_conflict(env):
    """A leg that both busts the heart's ceiling and collides reports the ceiling.

    PRD 2.10: "34. **Cold-ischemic ceiling** —
    `ERR_COLD_ISCHEMIC_LIMIT_EXCEEDED`, on `POST /opo/organs/{id}/transport`."
    PRD 2.10: "42. **Transport asset capacity** — `ERR_ASSET_CAPACITY_EXCEEDED`,
    on `POST /opo/organs/{id}/transport`."

    Design: Difficulty/priority_pair_validation_conflict/transport_cold_ischemic_temporal_gate_precedes_asset_capacity_constraint
    """
    _kidney, heart = _two_recovered_organs_sharing_one_asset(env)

    refused = env.api.dispatch_transport(
        heart.only_organ_id,
        transport_payload(
            heart.asset["id"],
            "2026-08-17T08:30:00Z",
            "2026-08-17T12:00:00Z",
            transport_mode="FIXED_WING",
        ),
        env.logistics,
    )
    validate_error(refused, ERR_COLD_ISCHEMIC_LIMIT_EXCEEDED)


def test_masked_dispatch_leaves_the_organ_unassigned_and_unprojected(env):
    """The refused leg writes no asset, no mode and no projection onto the organ.

    PRD 3.5: "Registration sets the organ's `cit_limit_minutes` from the
    cold-ischemic ceiling for its type".
    PRD 3.7: "The organ must be in status `RECOVERED`, otherwise
    `ERR_ORGAN_NOT_RECOVERED`, which guarantees its `cross_clamp_at` is already
    set."

    Design: Difficulty/priority_pair_validation_conflict/transport_cold_ischemic_temporal_gate_precedes_asset_capacity_constraint
    """
    _kidney, heart = _two_recovered_organs_sharing_one_asset(env)

    env.api.dispatch_transport(
        heart.only_organ_id,
        transport_payload(
            heart.asset["id"],
            "2026-08-17T08:30:00Z",
            "2026-08-17T12:00:00Z",
            transport_mode="FIXED_WING",
        ),
        env.logistics,
    )

    organ = read_organ(env, heart.only_organ_id)
    assert organ["status"] == "RECOVERED"
    assert organ["cit_limit_minutes"] == 240
    assert organ["transport_asset_id"] is None
    assert organ["projected_cold_ischemic_minutes"] is None


def test_capacity_conflict_surfaces_once_the_leg_fits_the_ceiling(env):
    """A shorter leg clears the ceiling and then meets the capacity refusal.

    PRD 3.7: "the system counts the organs already assigned to the named asset
    whose status is `RECOVERED` or `TRANSPLANTED` and whose leg overlaps the
    requested leg on **closed** intervals".
    PRD 3.7: "When that count has already reached the asset's
    `concurrent_leg_capacity`, the dispatch is rejected with
    `ERR_ASSET_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/transport_cold_ischemic_temporal_gate_precedes_asset_capacity_constraint
    """
    _kidney, heart = _two_recovered_organs_sharing_one_asset(env)

    # 150 elapsed plus 60 transit plus crash prep 20 is 230, inside the 240 ceiling.
    refused = env.api.dispatch_transport(
        heart.only_organ_id,
        transport_payload(
            heart.asset["id"],
            "2026-08-17T08:30:00Z",
            "2026-08-17T09:30:00Z",
            transport_mode="FIXED_WING",
        ),
        env.logistics,
    )
    validate_error(refused, ERR_ASSET_CAPACITY_EXCEEDED)


# ---------------------------------------------------------------------------
# Booking: frozen posture (rule 25) before the accepted-organ rule (rule 38)
# ---------------------------------------------------------------------------
def _frozen_case_without_an_accepted_organ(env):
    bundle = frozen_case_by_donor_loss(env, "KIDNEY_LEFT", "2026-08-18T09:00:00Z")
    bundle.team = create_team(
        env, specialty="ABDOMINAL", turnaround_buffer_minutes=90
    )
    case = read_case(env, bundle.case_id)
    assert case["case_posture"] == "FROZEN"
    assert case["physiologic_status"] == "LOST"
    assert case["allocation_status"] == "CLOSED"
    assert case["closed_reason"] == "DONOR_LOST"
    assert case["organs_accepted_count"] == 0
    return bundle


def test_frozen_posture_masks_the_accepted_organ_requirement(env):
    """Booking a room on a frozen case reports the freeze, not the empty organ set.

    PRD 2.10: "25. **Frozen case posture** — `ERR_CASE_FROZEN`, on the eight
    child mutations enumerated in §2.8."
    PRD 2.10: "38. **At least one accepted organ** — `ERR_NO_ACCEPTED_ORGANS`,
    on `POST /opo/donor-cases/{id}/recovery-operations`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_safety_gate_precedes_no_accepted_organs_constraint
    """
    bundle = _frozen_case_without_an_accepted_organ(env)

    refused = env.api.create_recovery_operation(
        bundle.case_id,
        recovery_operation_payload(
            bundle.team["id"], "2026-08-18T10:00:00Z", "2026-08-18T13:00:00Z"
        ),
        env.logistics,
    )
    validate_error(refused, ERR_CASE_FROZEN)


def test_masked_booking_creates_no_operation_and_moves_no_ledger(env):
    """Nothing is scheduled and the team's ledger stays at zero.

    PRD 2.8: "`FROZEN` refuses every child mutation of the case with
    `ERR_CASE_FROZEN` (409 Conflict)".
    PRD 3.7: "The team's `booked_or_minutes` increases by that `or_minutes` and
    its `scheduled_operation_count` by one."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_safety_gate_precedes_no_accepted_organs_constraint
    """
    bundle = _frozen_case_without_an_accepted_organ(env)

    env.api.create_recovery_operation(
        bundle.case_id,
        recovery_operation_payload(
            bundle.team["id"], "2026-08-18T10:00:00Z", "2026-08-18T13:00:00Z"
        ),
        env.logistics,
    )

    listed = env.api.list_recovery_operations(
        env.logistics, {"donor_case_id": bundle.case_id}
    )
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 0
    assert rows == []
    assert_team_ledger(read_team(env, bundle.team["id"]), 0, 0)


def test_the_frozen_case_also_genuinely_lacks_an_accepted_organ(env):
    """Both refusals really do apply, so the masking is a precedence decision.

    PRD 3.7: "The case must have at least one organ in status `ACCEPTED`,
    otherwise `ERR_NO_ACCEPTED_ORGANS`."
    PRD 3.4: "Every organ of the case whose status is `PENDING_EVAL`,
    `ALLOCATABLE`, `OFFERING` or `ACCEPTED` moves to `NON_TRANSPLANTABLE` with
    `nontransplantable_reason` `VIABILITY_FAILURE`".

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_safety_gate_precedes_no_accepted_organs_constraint
    """
    bundle = _frozen_case_without_an_accepted_organ(env)

    organ = read_organ(env, bundle.only_organ_id)
    assert organ["status"] == "NON_TRANSPLANTABLE"
    assert organ["nontransplantable_reason"] == "VIABILITY_FAILURE"
    assert read_case(env, bundle.case_id)["organs_accepted_count"] == 0
