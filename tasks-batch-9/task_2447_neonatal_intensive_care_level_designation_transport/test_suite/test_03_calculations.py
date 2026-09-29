"""Computed-figure conformance for the Neonatal Network API.

Covers the derived-on-read credential and equipment statuses of PRD §2.5, the
version rules of PRD §2.4 and §2.6, the bed ledger, waterfall allocation,
census-posture bands and nursing requirement of PRD §2.8, the rounding
conventions of PRD §2.9, the referral level variants and triage priority of
PRD §3.3, the deferral-queue promotion ranking of PRD §3.4, the surge tier and
authorized-bed arithmetic of PRD §3.5, the developmental bundle score and the
milk expiry and volume ledger of PRD §3.7, the back-transfer weight basis of
PRD §3.8, and the follow-up eligibility, risk tier and appointment window of
PRD §3.9.
"""

import math
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    assert_bed_ledger_balanced,
    assert_close,
    assert_decimal_places,
    assert_milk_ledger_balanced,
    assert_unit_counts,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    BUNDLE_BACK_TRANSFER_READY_THRESHOLD,
    CLOCK_START,
    CONSTRAINED_POSTURE_FRACTION,
    DONOR_PASTEURIZED_SHELF_LIFE_HOURS,
    FOLLOWUP_WINDOW_END_DAYS,
    FOLLOWUP_WINDOW_START_DAYS,
    MOTHERS_OWN_SHELF_LIFE_HOURS,
    NEONATAL_HOLD_MINUTES,
    SURGE_BED_CAPS,
    SURGE_WAIVER_RATIOS,
    TRIAGE_KIND_POINTS,
    TRIAGE_KIND_WEIGHT,
    TRIAGE_LEVEL_POINTS,
    TRIAGE_LEVEL_WEIGHT,
    TRIAGE_PREMATURITY_WEIGHT,
    TRIAGE_WEIGHT_WEIGHT,
)


def _instant(value):
    """Read an ISO-8601 UTC instant so two renderings of one moment compare equal."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _triage_priority(required_level, prematurity_points, weight_points, referral_kind):
    """The weighted triage score of PRD §3.3, assembled from the published weights."""
    return round(
        TRIAGE_LEVEL_WEIGHT * TRIAGE_LEVEL_POINTS[required_level]
        + TRIAGE_PREMATURITY_WEIGHT * prematurity_points
        + TRIAGE_WEIGHT_WEIGHT * weight_points
        + TRIAGE_KIND_WEIGHT * TRIAGE_KIND_POINTS[referral_kind],
        2,
    )


# ---------------------------------------------------------------------------
# Derived-on-read credential and equipment status
# ---------------------------------------------------------------------------


def test_credential_expiry_collapses_capability_without_writing_the_unit(api, network):
    """PRD §2.5: "A credential's `status` is `REVOKED` when its `revoked_at` is set to a non-null instant; otherwise it is `EXPIRED` when its `expires_on` is at or before the current clock instant; otherwise it is `VALID`."

    PRD §2.7: "`capability_level` is what the unit can currently prove — the highest-ranking level among the declared standards that the unit satisfies, falling back to `LEVEL_I` when it satisfies none of them, because a newborn nursery baseline is statutory and a unit is never rated below `LEVEL_I`."

    PRD §2.7: "All four derived values are recomputed on every read of the unit and again before every acceptance decision, which means a credential revocation or an equipment fault propagates into `effective_level` with no explicit write to the unit at all."

    Design: Corner/calculations/credential_expiry_and_service_due_are_pure_clock_functions
    """
    credential_id = network["credentials"]["RN_NICU_CORE"]["id"]
    fixtures.set_clock("2027-01-01T00:00:00Z")

    credential = validate_success(api.get_staff_credential(credential_id, network["admin"]))
    assert credential["status"] == "EXPIRED"
    assert credential["revoked_at"] is None

    unit = validate_success(api.get_nicu_unit(network["unit_a_id"], network["intake_a"]))
    assert unit["capability_level"] == "LEVEL_I"
    assert unit["effective_level"] == "LEVEL_I"
    assert unit["staffing_compliant"] is False
    assert unit["version"] == 1


def test_clock_driven_expiry_leaves_the_queued_referral_for_the_acceptance_gate(api, network):
    """PRD §2.5: "Advancing the clock never, by itself, rewrites a stored row."

    PRD §3.4: "The unit's `effective_level` must rank at or above the referral's `required_level`, or the acceptance is refused with `ERR_LEVEL_CAPABILITY_INSUFFICIENT` — note that this reads the *effective* level of §2.7, so a unit designated `LEVEL_III` whose ventilator is out of service cannot accept a `LEVEL_III` case."

    Design: Corner/calculations/credential_expiry_and_service_due_are_pure_clock_functions
    """
    referral = fixtures.create_referral(network, case_reference="CASE-N1")
    fixtures.set_clock("2027-01-01T00:00:00Z")

    parked = fixtures.read_referral(network, referral["id"])
    assert parked["status"] == "PENDING"
    assert parked["decision_reason"] is None
    assert parked["required_level"] == "LEVEL_III"

    version = fixtures.read_unit_version(network)
    assert version == 1
    validate_error(
        api.accept_referral(
            referral["id"], factories.accept_referral_payload(version), network["intake_a"]
        ),
        ApiErrorId.LEVEL_CAPABILITY_INSUFFICIENT,
    )


def test_service_due_boundary_and_the_recompute_after_maintenance(api, network):
    """PRD §2.5: "An equipment asset's `status` is `OUT_OF_SERVICE` when its `out_of_service_at` is non-null; otherwise it is `SERVICE_DUE` when its `next_service_due_at` is at or before the current clock instant; otherwise it is `IN_SERVICE`." "The asset's `next_service_due_at` is itself derived — the `last_service_at` instant advanced by `service_interval_days` days."

    PRD §3.1: "Completing preventive maintenance supplies a `serviced_at` instant, which becomes the asset's new `last_service_at`, and clears both `out_of_service_at` and `out_of_service_reason` — after which `next_service_due_at` and the derived `status` are recomputed along with the unit's `capability_level`, `effective_level` and `equipment_compliant`."

    Design: Corner/calculations/credential_expiry_and_service_due_are_pure_clock_functions
    """
    asset_id = network["assets"]["CONVENTIONAL_VENT"]["id"]
    fixtures.set_clock("2027-07-01T00:00:00Z")

    due = validate_success(api.get_equipment_asset(asset_id, network["admin"]))
    assert _instant(due["next_service_due_at"]) == _instant("2027-07-01T00:00:00Z")
    assert due["status"] == "SERVICE_DUE"

    serviced = validate_success(
        api.service_equipment_asset(
            asset_id, factories.service_payload("2027-07-01T00:00:00Z"), network["dir_a"]
        )
    )
    assert _instant(serviced["last_service_at"]) == _instant("2027-07-01T00:00:00Z")
    assert _instant(serviced["next_service_due_at"]) == _instant("2028-06-30T00:00:00Z")
    assert serviced["status"] == "IN_SERVICE"
    assert serviced["out_of_service_at"] is None


# ---------------------------------------------------------------------------
# Waterfall allocation and the surge arithmetic behind it
# ---------------------------------------------------------------------------


def test_surge_authorization_computes_ratio_tier_waiver_and_authorized_beds(api, network):
    """PRD §3.5: "First, `census_ratio_at_request` — the unit's `occupied_bed_count` divided by the sum of its `staffed_bed_target` and the `authorized_beds` of every *other* `ACTIVE` escalation at that unit, rounded half up to four decimals."

    PRD §3.5: "The tier fixes `staffing_waiver_ratio` — 1.10 at `TIER_1`, 1.25 at `TIER_2`, 1.50 at `TIER_3` — which is the multiplier applied to the acuity-band denominators in the nurse calculation of §2.8, and it also fixes a bed cap of 2 beds at `TIER_1`, 4 beds at `TIER_2` and 6 beds at `TIER_3`."

    PRD §3.5: "`authorized_beds` is then the lowest of three quantities: the `requested_beds` asked for, that staffing headroom, and the tier's bed cap — floored at zero so it is never negative."

    Design: Corner/calculations/staffed_beds_fill_before_escalation_beds
    """
    fixtures.patch_unit(network, staffed_bed_target=1)
    fixtures.admit_case(network, case_reference="CASE-N1")

    escalation = fixtures.request_surge(network, requested_beds=2)
    authorized = validate_success(
        api.authorize_surge_escalation(escalation["id"], {}, network["admin"])
    )

    assert_close(authorized["census_ratio_at_request"], 1.0000)
    assert_decimal_places(authorized["census_ratio_at_request"], 4)
    assert authorized["escalation_tier"] == "TIER_3"
    assert_close(authorized["staffing_waiver_ratio"], SURGE_WAIVER_RATIOS["TIER_3"])
    # staffing capacity floor(3.0 RN FTE * 1.50 * 2) = 9 beds, less the one committed bed
    staffing_headroom = math.floor(3.0 * SURGE_WAIVER_RATIOS["TIER_3"] * 2) - 1
    assert authorized["authorized_beds"] == min(2, staffing_headroom, SURGE_BED_CAPS["TIER_3"])
    assert authorized["authorized_beds"] == 2
    assert authorized["status"] == "ACTIVE"


def test_holds_take_escalation_class_once_the_staffed_beds_are_committed(api, network):
    """PRD §2.8: "First, allocation is a **waterfall**: a new hold takes `bed_class` `STAFFED` while the pre-operation sum of `occupied_bed_count` and `held_bed_count` is strictly below `staffed_bed_target`, and `ESCALATION` otherwise."

    PRD §2.8: "The invariant that must hold after every single operation is that `staffed_bed_target` plus `escalation_bed_count` equals `occupied_bed_count` plus `held_bed_count` plus `available_bed_count`."

    PRD §2.8: "For each level, divide that level's census band by the product of the `nurse_patient_ratio_denominator` declared by the standard for that level and the waiver in force, then round the quotient **up** to a whole nurse; `required_nurse_count` is the sum of those per-band whole numbers."

    Design: Corner/calculations/staffed_beds_fill_before_escalation_beds
    """
    fixtures.patch_unit(network, staffed_bed_target=1)
    first = fixtures.create_referral(network, case_reference="CASE-N1")
    staffed_hold = fixtures.accept_referral(network, first["id"])
    fixtures.admit(network, first["id"])

    escalation = fixtures.request_surge(network, requested_beds=2)
    fixtures.authorize_surge(network, escalation["id"])

    escalation_holds = []
    for case_reference in ("CASE-N2", "CASE-N4"):
        referral = fixtures.create_referral(network, case_reference=case_reference)
        version = fixtures.read_unit_version(network)
        accepted = validate_success(
            api.accept_referral(
                referral["id"], factories.accept_referral_payload(version), network["intake_a"]
            )
        )
        escalation_holds.append(fixtures.read_reservation(network, accepted["reservation_id"]))

    assert fixtures.read_reservation(network, staffed_hold["reservation_id"])["bed_class"] == "STAFFED"
    assert [hold["bed_class"] for hold in escalation_holds] == ["ESCALATION", "ESCALATION"]

    unit = fixtures.read_unit(network)
    assert_unit_counts(unit, occupied=1, held=2, available=0, escalation=2, posture="CLOSED")
    assert unit["staffed_bed_target"] + unit["escalation_bed_count"] == (
        unit["occupied_bed_count"] + unit["held_bed_count"] + unit["available_bed_count"]
    )
    # one LEVEL_III infant over a denominator of 2.0 widened by the TIER_3 waiver
    assert unit["required_nurse_count"] == math.ceil(1 / (2.0 * SURGE_WAIVER_RATIOS["TIER_3"]))
    assert unit["required_nurse_count"] == 1


# ---------------------------------------------------------------------------
# Census posture bands
# ---------------------------------------------------------------------------


def test_census_posture_walks_open_constrained_then_closed(api, network):
    """PRD §2.8: "Otherwise, when `available_bed_count` is at or below the `staffed_bed_target` multiplied by 0.20 and rounded down to a whole bed, the posture is `CONSTRAINED`."

    PRD §2.8: "Because the constrained band uses an at-or-below comparison, a unit with a target of 5 and exactly 1 free bed is `CONSTRAINED` while the same unit with 2 free beds is `OPEN`; and because the threshold is rounded down, a unit with a target of 4 has an empty constrained band — one free bed there is already `OPEN`."

    Design: Corner/calculations/census_posture_at_and_around_the_constrained_band
    """
    fixtures.patch_unit(network, staffed_bed_target=5)

    reservations = []
    snapshots = []
    for index in range(1, 6):
        referral = fixtures.create_referral(network, case_reference=f"CASE-P{index}")
        version = fixtures.read_unit_version(network)
        accepted = validate_success(
            api.accept_referral(
                referral["id"], factories.accept_referral_payload(version), network["intake_a"]
            )
        )
        reservations.append(fixtures.read_reservation(network, accepted["reservation_id"]))
        snapshots.append(fixtures.read_unit(network))

    assert math.floor(5 * CONSTRAINED_POSTURE_FRACTION) == 1

    after_three, after_four, after_five = snapshots[2], snapshots[3], snapshots[4]
    assert after_three["available_bed_count"] == 2
    assert after_three["census_posture"] == "OPEN"
    assert after_four["available_bed_count"] == 1
    assert after_four["census_posture"] == "CONSTRAINED"
    assert after_five["available_bed_count"] == 0
    assert after_five["census_posture"] == "CLOSED"

    assert [reservation["bed_class"] for reservation in reservations] == ["STAFFED"] * 5
    assert_unit_counts(after_five, occupied=0, held=5, available=0)
    assert_bed_ledger_balanced(after_five)


def test_each_acceptance_advances_the_units_version_once(api, network):
    """PRD §2.4: "Alongside `id`, resources carry `created_at` and `updated_at` — ISO 8601 UTC timestamps rendered with exactly three fractional-second digits — and `version`, an integer that begins at 1 when the resource is created and increases by one on every mutation of that resource."

    PRD §3.4: "The unit's `version` advances by one and its counters and `census_posture` are re-derived."

    Design: Corner/calculations/census_posture_at_and_around_the_constrained_band
    """
    fixtures.patch_unit(network, staffed_bed_target=5)

    quoted_versions = []
    for index in range(1, 6):
        referral = fixtures.create_referral(network, case_reference=f"CASE-P{index}")
        version = fixtures.read_unit_version(network)
        quoted_versions.append(version)
        validate_success(
            api.accept_referral(
                referral["id"], factories.accept_referral_payload(version), network["intake_a"]
            )
        )

    # version 1 at registration, +1 for the capacity edit, +1 for each acceptance
    assert quoted_versions == [2, 3, 4, 5, 6]
    assert fixtures.read_unit_version(network) == 7


# ---------------------------------------------------------------------------
# Bedside record, developmental bundle and the back-transfer weight basis
# ---------------------------------------------------------------------------


def test_care_update_stabilizes_and_rederives_the_current_care_level(api, network):
    """PRD §3.7: "One care-status consequence rides along: when the posted `support_modality` is `ROOM_AIR` or `CPAP` and the admission is in `ADMITTED`, the posting moves it `ADMITTED → STABILIZED`."

    PRD §3.7: "`current_care_level` is re-derived from the bedside record as the higher-ranking of the weight term applied to `current_weight_grams` and the support term applied to `support_modality`, using exactly the weight and support mappings of §3.3."

    Design: Corner/calculations/back_transfer_is_judged_on_current_weight_not_birth_weight
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N1")

    updated = validate_success(
        api.create_care_update(
            admission["id"],
            factories.care_update_payload(current_weight_grams=1900, support_modality="ROOM_AIR"),
            network["nurse"],
        )
    )

    assert updated["care_status"] == "STABILIZED"
    assert updated["current_weight_grams"] == 1900
    # 1900 g is at or above 1800 g, so the weight term is LEVEL_I, as is room air
    assert updated["current_care_level"] == "LEVEL_I"


def test_two_compliant_rounds_land_exactly_on_the_readiness_boundary(api, network):
    """PRD §3.7: "`developmental_bundle_score` is 0.35 of the kangaroo points plus 0.25 of the family points plus 0.20 of the cluster points plus 0.20 of the light points, rounded half up to two decimals."

    PRD §3.7: "Two rounds each of 60 kangaroo minutes, 240 family minutes, cluster compliance true and light cycling false produce exactly 60.00 — the boundary at which back-transfer readiness passes."

    PRD §3.8: "The receiving unit's `IntakeNeonatologist` attests that readiness, moving the admission `STABILIZED → BACK_TRANSFER_READY`."

    Design: Corner/calculations/back_transfer_is_judged_on_current_weight_not_birth_weight
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N1")
    fixtures.care_update(
        network, admission["id"], current_weight_grams=1900, support_modality="ROOM_AIR"
    )

    scored = fixtures.developmental_rounds(
        network,
        admission["id"],
        count=2,
        kangaroo_care_minutes=60,
        family_presence_minutes=240,
        cluster_care_compliant=True,
        light_cycling_compliant=False,
    )
    assert scored["developmental_round_count"] == 2
    assert scored["kangaroo_care_sessions"] == 2
    assert scored["family_presence_minutes"] == 480
    assert_close(scored["developmental_bundle_score"], BUNDLE_BACK_TRANSFER_READY_THRESHOLD)
    assert_close(scored["developmental_bundle_score"], 60.00)
    assert_decimal_places(scored["developmental_bundle_score"], 2)

    note = "Weight 1900 g, room air, feeding fully, risk-appropriate for Community Hospital B"
    attested = validate_success(
        api.attest_back_transfer_ready(
            admission["id"],
            factories.back_transfer_ready_payload(back_transfer_attestation_note=note),
            network["intake_a"],
        )
    )
    assert attested["care_status"] == "BACK_TRANSFER_READY"
    assert attested["back_transfer_attestation_note"] == note


def test_back_transfer_referral_reads_current_weight_and_drops_the_gestation_term(api, network):
    """PRD §3.3: "The weight the level calculation actually consults is `weight_basis_grams`: it is the source admission's `current_weight_grams` when `referral_kind` is `BACK_TRANSFER`, and the referral's own `birth_weight_grams` otherwise."

    PRD §3.3: "So an inbound neonatal case at 35.0 weeks and 2400 grams on `CPAP` with surgery planned computes `LEVEL_II` current, `LEVEL_IV` anticipated and a basis of `ANTICIPATED_NEED`; an inbound case at 29.0 weeks and 1200 grams in `ROOM_AIR` computes `LEVEL_III` on both variants and a basis of `CURRENT_SUPPORT`; an antenatal case at 30.0 weeks with an estimated fetal weight of 1300 grams computes `LEVEL_I` current and `LEVEL_III` anticipated with `maternal_transfer_preferred` true; a back-transfer at 29.0 weeks now weighing 1900 grams in `ROOM_AIR` computes `LEVEL_I`; and an antenatal case at 33.0 weeks and 2000 grams in `ROOM_AIR` computes `LEVEL_II` with `maternal_transfer_preferred` false, because the level sits below `LEVEL_III`."

    PRD §3.3: "An inbound `LEVEL_III` case at 31.0 weeks and 1600 grams scores 66.25, an inbound `LEVEL_IV` case at 26.0 weeks and 850 grams scores 92.50, and a back-transfer at `LEVEL_I`, 29.0 weeks and 1900 grams scores 33.75."

    Design: Corner/calculations/back_transfer_is_judged_on_current_weight_not_birth_weight
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N1")
    assert admission["birth_weight_grams"] == 1200
    fixtures.care_update(
        network, admission["id"], current_weight_grams=1900, support_modality="ROOM_AIR"
    )
    fixtures.developmental_rounds(
        network,
        admission["id"],
        count=2,
        kangaroo_care_minutes=60,
        family_presence_minutes=240,
        cluster_care_compliant=True,
        light_cycling_compliant=False,
    )
    fixtures.attest_back_transfer_ready(network, admission["id"])
    version = fixtures.read_admission(network, admission["id"])["version"]

    onward = validate_success(
        api.create_back_transfer_referral(
            admission["id"],
            factories.back_transfer_referral_payload(
                version, network["unit_b_id"], case_reference="CASE-BT1"
            ),
            network["intake_a"],
        ),
        201,
    )

    assert onward["referral_kind"] == "BACK_TRANSFER"
    assert onward["source_admission_id"] == admission["id"]
    assert onward["referring_unit_id"] == network["unit_a_id"]
    assert onward["receiving_unit_id"] == network["unit_b_id"]
    assert onward["weight_basis_grams"] == 1900
    assert onward["current_support_level"] == "LEVEL_I"
    assert onward["anticipated_need_level"] == "LEVEL_I"
    assert onward["required_level"] == "LEVEL_I"
    assert onward["level_basis"] == "CURRENT_SUPPORT"
    assert onward["maternal_transfer_preferred"] is False
    assert_close(onward["triage_priority"], 33.75)
    assert_close(
        onward["triage_priority"],
        _triage_priority("LEVEL_I", 75, 25, "BACK_TRANSFER"),
    )
    assert_decimal_places(onward["triage_priority"], 2)


# ---------------------------------------------------------------------------
# Milk shelf life and the volume ledger
# ---------------------------------------------------------------------------


def test_milk_shelf_life_differs_by_donor_type(api, network):
    """PRD §3.7: "The caller's `X-User-ID` is stored as `received_by_user_id`, the batch opens at status `RECEIVED` with `verified_by_user_id` null, and `expires_at` is derived from the donor type: 96 hours — four days — after `expressed_at` for `MOTHERS_OWN`, and 24 hours after `expressed_at` for `DONOR_PASTEURIZED`."

    PRD §3.7: "A successful verification records the caller as `verified_by_user_id` and moves the batch `RECEIVED → VERIFIED`."

    Design: Corner/calculations/milk_expiry_constants_differ_by_donor_type
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")
    mothers_own = fixtures.verified_milk_batch(
        network, admission["id"], label_code="LBL-1", donor_type="MOTHERS_OWN", volume_ml=120.0
    )
    donor = fixtures.verified_milk_batch(
        network,
        admission["id"],
        label_code="LBL-2",
        donor_type="DONOR_PASTEURIZED",
        volume_ml=60.0,
    )

    expressed = _instant(CLOCK_START)
    stored_mothers_own = validate_success(api.get_milk_batch(mothers_own["id"], network["admin"]))
    stored_donor = validate_success(api.get_milk_batch(donor["id"], network["admin"]))

    assert _instant(stored_mothers_own["expires_at"]) == expressed + timedelta(
        hours=MOTHERS_OWN_SHELF_LIFE_HOURS
    )
    assert _instant(stored_mothers_own["expires_at"]) == _instant("2026-08-05T00:00:00Z")
    assert _instant(stored_donor["expires_at"]) == expressed + timedelta(
        hours=DONOR_PASTEURIZED_SHELF_LIFE_HOURS
    )
    assert _instant(stored_donor["expires_at"]) == _instant("2026-08-02T00:00:00Z")

    for batch in (stored_mothers_own, stored_donor):
        assert batch["status"] == "VERIFIED"
        assert batch["received_by_user_id"] == "nurse-1"
        assert batch["verified_by_user_id"] == "nurse-2"
        assert batch["verified_by_user_id"] != batch["received_by_user_id"]


def test_donor_batch_is_already_expired_at_its_boundary_instant(api, network):
    """PRD §3.7: "The batch must not have expired: an `expires_at` at or before the current clock instant is refused with `ERR_MILK_EXPIRED`, and at exactly `expires_at` the batch is already expired."

    Design: Corner/calculations/milk_expiry_constants_differ_by_donor_type
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")
    donor = fixtures.verified_milk_batch(
        network,
        admission["id"],
        label_code="LBL-2",
        donor_type="DONOR_PASTEURIZED",
        volume_ml=60.0,
    )
    fixtures.set_clock("2026-08-02T00:00:00Z")

    validate_error(
        api.administer_milk(donor["id"], factories.milk_volume_payload(30.0), network["nurse"]),
        ApiErrorId.MILK_EXPIRED,
    )

    untouched = validate_success(api.get_milk_batch(donor["id"], network["admin"]))
    assert_close(untouched["administered_ml"], 0.0)
    assert_close(untouched["remaining_ml"], 60.0)
    assert_decimal_places(untouched["administered_ml"], 1)
    assert_decimal_places(untouched["remaining_ml"], 1)
    assert_milk_ledger_balanced(untouched)


def test_mothers_own_administration_splits_the_ledger_and_rolls_up(api, network):
    """PRD §3.7: "The batch's `status` is derived from that split: `DISCARDED` when `discarded_ml` is above zero and `remaining_ml` is zero; `ADMINISTERED` when `remaining_ml` is zero and `administered_ml` is above zero; `PARTIALLY_ADMINISTERED` when `administered_ml` is above zero while `remaining_ml` is still above zero; and otherwise whatever status was last stored, meaning `RECEIVED`, `VERIFIED` or `QUARANTINED`."

    PRD §3.7: "Every administration and every reversal recomputes the batch's ledger and status, recomputes the admission's `milk_administered_ml` as the sum of `administered_ml` over that admission's batches at one decimal place, and advances the admission's `version` by one."

    Design: Corner/calculations/milk_expiry_constants_differ_by_donor_type
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")
    mothers_own = fixtures.verified_milk_batch(
        network, admission["id"], label_code="LBL-1", donor_type="MOTHERS_OWN", volume_ml=120.0
    )
    donor = fixtures.verified_milk_batch(
        network,
        admission["id"],
        label_code="LBL-2",
        donor_type="DONOR_PASTEURIZED",
        volume_ml=60.0,
    )
    fixtures.set_clock("2026-08-02T00:00:00Z")
    validate_error(
        api.administer_milk(donor["id"], factories.milk_volume_payload(30.0), network["nurse"]),
        ApiErrorId.MILK_EXPIRED,
    )

    fed = validate_success(
        api.administer_milk(
            mothers_own["id"], factories.milk_volume_payload(30.0), network["nurse"]
        )
    )
    assert fed["status"] == "PARTIALLY_ADMINISTERED"
    assert_close(fed["administered_ml"], 30.0)
    assert_close(fed["remaining_ml"], 90.0)
    assert_decimal_places(fed["administered_ml"], 1)
    assert_decimal_places(fed["remaining_ml"], 1)
    assert_milk_ledger_balanced(fed)

    rolled_up = fixtures.read_admission(network, admission["id"])
    assert_close(rolled_up["milk_administered_ml"], 30.0)
    assert_decimal_places(rolled_up["milk_administered_ml"], 1)


# ---------------------------------------------------------------------------
# Follow-up eligibility, risk tier and appointment window
# ---------------------------------------------------------------------------


def test_high_risk_referral_scores_its_weighted_triage_priority(api, network):
    """PRD §3.3: "The priority is 0.40 of the level points plus 0.25 of the prematurity points plus 0.20 of the weight points plus 0.15 of the kind points, rounded half up to two decimals."

    PRD §3.3: "Level points are 25 for `LEVEL_I`, 50 for `LEVEL_II`, 75 for `LEVEL_III` and 100 for `LEVEL_IV`, taken from `required_level`."

    Design: Corner/calculations/followup_eligibility_basis_risk_tier_and_window
    """
    referral = validate_success(
        api.create_referral(
            factories.referral_payload(
                network["unit_b_id"],
                network["unit_a_id"],
                case_reference="CASE-HR1",
                gestational_age_weeks=26.0,
                birth_weight_grams=850,
                support_modality="ROOM_AIR",
            ),
            network["ref_b"],
        ),
        201,
    )

    assert referral["weight_basis_grams"] == 850
    assert referral["required_level"] == "LEVEL_III"
    # level 75, prematurity 100 below 28.0 weeks, weight 100 below 1000 g, inbound kind 50
    assert_close(
        referral["triage_priority"], _triage_priority("LEVEL_III", 100, 100, "INBOUND_NEONATAL")
    )
    assert_close(referral["triage_priority"], 82.50)
    assert_decimal_places(referral["triage_priority"], 2)


def test_discharge_home_marks_the_high_risk_graduate_and_returns_the_bed(api, network):
    """PRD §3.8: "The discharge stamps `discharged_at` with the current clock instant, sets `discharge_disposition` to `HOME`, re-derives `high_risk_graduate` from the eligibility rules of §3.9, then re-derives the unit's counters, promotes its deferral queue, and advances its `version` by one."

    PRD §3.9: "`high_risk_graduate` on the admission is true exactly when `eligibility_basis` is anything other than `NOT_ELIGIBLE`."

    Design: Corner/calculations/followup_eligibility_basis_risk_tier_and_window
    """
    admission = fixtures.admit_case(
        network,
        case_reference="CASE-HR1",
        gestational_age_weeks=26.0,
        birth_weight_grams=850,
    )
    fixtures.care_update(
        network, admission["id"], current_weight_grams=2100, support_modality="ROOM_AIR"
    )

    discharged = validate_success(
        api.discharge_admission(
            admission["id"], factories.discharge_payload("HOME"), network["intake_a"]
        )
    )
    assert discharged["care_status"] == "DISCHARGED"
    assert discharged["discharge_disposition"] == "HOME"
    assert _instant(discharged["discharged_at"]) == _instant(CLOCK_START)
    assert discharged["high_risk_graduate"] is True

    unit = fixtures.read_unit(network)
    assert_unit_counts(unit, occupied=0, held=0, available=4)


def test_enrollment_derives_the_basis_the_tier_and_the_appointment_window(api, network):
    """PRD §3.9: "`eligibility_basis` is the **first** match in a pinned order: `BW_UNDER_1500` when `birth_weight_grams` is below 1500; otherwise `GA_UNDER_32` when `gestational_age_weeks` is below 32.0; otherwise `HIE_COOLED` when the originating referral's `diagnoses` contain `HIE_MODERATE`; otherwise `SURGICAL_NEC` when those `diagnoses` contain `SURGICAL_NEC`; otherwise `VENT_OVER_7D` when `ventilator_days` is strictly greater than 7; and otherwise `NOT_ELIGIBLE`."

    PRD §3.9: "`risk_tier` is `HIGH` when `birth_weight_grams` is below 1000 or `eligibility_basis` is `HIE_COOLED`, and `MODERATE` otherwise."

    PRD §3.9: "A permitted enrollment opens at status `ENROLLED` with `confirmed_appointment_date` and `attendance_recorded_at` null, and with its appointment window derived from the admission: `appointment_window_start` is the admission's `discharged_at` advanced by 14 days, inclusive, and `appointment_window_end` is that same instant advanced by 90 days, also inclusive."

    Design: Corner/calculations/followup_eligibility_basis_risk_tier_and_window
    """
    admission = fixtures.admit_case(
        network,
        case_reference="CASE-HR1",
        gestational_age_weeks=26.0,
        birth_weight_grams=850,
    )
    fixtures.care_update(
        network, admission["id"], current_weight_grams=2100, support_modality="ROOM_AIR"
    )
    discharged = fixtures.discharge(network, admission["id"], "HOME")

    enrollment = validate_success(
        api.create_follow_up_enrollment(
            factories.follow_up_enrollment_payload(
                admission["id"], network["unit_a_id"], "2026-09-01T09:00:00Z"
            ),
            network["fu"],
        ),
        201,
    )

    assert enrollment["status"] == "ENROLLED"
    assert enrollment["eligibility_basis"] == "BW_UNDER_1500"
    assert enrollment["risk_tier"] == "HIGH"
    assert enrollment["confirmed_appointment_date"] is None
    assert enrollment["attendance_recorded_at"] is None

    discharged_at = _instant(discharged["discharged_at"])
    assert _instant(enrollment["appointment_window_start"]) == discharged_at + timedelta(
        days=FOLLOWUP_WINDOW_START_DAYS
    )
    assert _instant(enrollment["appointment_window_start"]) == _instant("2026-08-15T00:00:00Z")
    assert _instant(enrollment["appointment_window_end"]) == discharged_at + timedelta(
        days=FOLLOWUP_WINDOW_END_DAYS
    )
    assert _instant(enrollment["appointment_window_end"]) == _instant("2026-10-30T00:00:00Z")


def test_scheduling_inside_the_window_then_attendance_closes_the_enrollment(api, network):
    """PRD §3.9: "A permitted scheduling moves the enrollment `ENROLLED → SCHEDULED` and records the confirmed instant."

    PRD §3.9: "The coordinator posts `attended`: true moves the enrollment `SCHEDULED → ATTENDED`, false moves it `SCHEDULED → NO_SHOW`, and either branch stamps `attendance_recorded_at` with the current clock instant."

    Design: Corner/calculations/followup_eligibility_basis_risk_tier_and_window
    """
    admission = fixtures.admit_case(
        network,
        case_reference="CASE-HR1",
        gestational_age_weeks=26.0,
        birth_weight_grams=850,
    )
    fixtures.care_update(
        network, admission["id"], current_weight_grams=2100, support_modality="ROOM_AIR"
    )
    fixtures.discharge(network, admission["id"], "HOME")
    enrollment = fixtures.enroll_graduate(
        network, admission["id"], target_appointment_date="2026-09-01T09:00:00Z"
    )

    scheduled = validate_success(
        api.schedule_follow_up_enrollment(
            enrollment["id"],
            factories.schedule_payload("2026-09-01T09:00:00Z"),
            network["fu"],
        )
    )
    assert scheduled["status"] == "SCHEDULED"
    assert _instant(scheduled["confirmed_appointment_date"]) == _instant("2026-09-01T09:00:00Z")

    attended = validate_success(
        api.record_follow_up_attendance(
            enrollment["id"], factories.attendance_payload(True), network["fu"]
        )
    )
    assert attended["status"] == "ATTENDED"
    assert _instant(attended["attendance_recorded_at"]) == _instant(CLOCK_START)


# ---------------------------------------------------------------------------
# Deferral-queue ranking and promotion
# ---------------------------------------------------------------------------


def test_tied_triage_priorities_are_ranked_by_created_at(api, network):
    """PRD §3.3: "An antenatal `LEVEL_III` case at 30.0 weeks and 1300 grams scores 78.75; an inbound `LEVEL_III` case at 29.0 weeks and 1200 grams scores 71.25, as does an inbound `LEVEL_III` case at 30.0 weeks and 1250 grams — ties are real and are broken by the rules in §3.4."

    PRD §3.4: "The ranking over that pool is total and pinned: `triage_priority` descending first; then, among ties, referrals with `maternal_transfer_preferred` true ahead of those with it false; then, among remaining ties, `created_at` ascending."

    Design: Corner/calculations/deferral_queue_tie_breaks_on_created_at
    """
    fixtures.patch_unit(network, staffed_bed_target=1)
    holder = fixtures.create_referral(network, case_reference="CASE-N1")
    fixtures.accept_referral(network, holder["id"])

    early = fixtures.create_referral(
        network,
        case_reference="CASE-TIE-EARLY",
        gestational_age_weeks=30.0,
        birth_weight_grams=1250,
    )
    validate_success(api.defer_referral(early["id"], {}, network["intake_a"]))
    late = fixtures.create_referral(
        network,
        case_reference="CASE-TIE-LATE",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
    )
    validate_success(api.defer_referral(late["id"], {}, network["intake_a"]))

    assert_close(fixtures.read_referral(network, early["id"])["triage_priority"], 71.25)
    assert_close(fixtures.read_referral(network, late["id"])["triage_priority"], 71.25)

    ranked, _meta = validate_paginated(
        api.get_deferral_queue(network["unit_a_id"], network["intake_a"])
    )
    assert [row["id"] for row in ranked] == [early["id"], late["id"]]
    assert_close(ranked[0]["triage_priority"], 71.25)
    assert_decimal_places(ranked[0]["triage_priority"], 2)


def test_sweep_promotes_exactly_one_tied_referral_onto_the_freed_bed(api, network):
    """PRD §3.4: "Promotion then loops: while the unit's committed `available_bed_count` is at least 1 and the pool is non-empty, the top-ranked candidate is promoted `DEFERRED → ACCEPTED`, a `HELD` reservation is created for it exactly as an ordinary acceptance would (same waterfall `bed_class`, same `held_at`, same kind-dependent `expires_at`), its `decision_reason` is cleared back to null, the unit's `version` advances by one, the ledger is re-derived, and the loop continues."

    PRD §3.4: "With a pool scoring 78.75, 71.25, 71.25 and 66.25 and one free bed, only the 78.75 referral is promoted and the rest stay `DEFERRED`; with two non-maternal referrals tied at 71.25, the one created earlier goes first."

    PRD §2.8: "`deferral_queue_depth` is itself the count of referrals whose `receiving_unit_id` is this unit and whose status is `DEFERRED`."

    Design: Corner/calculations/deferral_queue_tie_breaks_on_created_at
    """
    fixtures.patch_unit(network, staffed_bed_target=1)
    holder = fixtures.create_referral(network, case_reference="CASE-N1")
    fixtures.accept_referral(network, holder["id"])

    early = fixtures.create_referral(
        network,
        case_reference="CASE-TIE-EARLY",
        gestational_age_weeks=30.0,
        birth_weight_grams=1250,
    )
    validate_success(api.defer_referral(early["id"], {}, network["intake_a"]))
    late = fixtures.create_referral(
        network,
        case_reference="CASE-TIE-LATE",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
    )
    validate_success(api.defer_referral(late["id"], {}, network["intake_a"]))

    fixtures.set_clock("2026-08-01T04:00:00Z")
    swept = validate_success(
        api.run_capacity_sweep(
            factories.capacity_sweep_payload(network["unit_a_id"]), network["admin"]
        )
    )
    assert swept["referrals_promoted"] == 1

    promoted = fixtures.read_referral(network, early["id"])
    assert promoted["status"] == "ACCEPTED"
    assert promoted["decision_reason"] is None
    reservation = fixtures.read_reservation(network, promoted["reservation_id"])
    assert reservation["status"] == "HELD"
    assert _instant(reservation["expires_at"]) == _instant("2026-08-01T04:00:00Z") + timedelta(
        minutes=NEONATAL_HOLD_MINUTES
    )
    assert _instant(reservation["expires_at"]) == _instant("2026-08-01T08:00:00Z")

    still_queued = fixtures.read_referral(network, late["id"])
    assert still_queued["status"] == "DEFERRED"
    assert still_queued["decision_reason"] == "NO_BED"

    unit = fixtures.read_unit(network)
    assert unit["deferral_queue_depth"] == 1
    assert_unit_counts(unit, occupied=0, held=1, available=0)
