"""The error envelope, the composite unique key, and the four endpoint round trips."""

from test_helpers import (
    AUTH_USER_2,
    ERR_CASE_FROZEN,
    ERR_DUPLICATE_KEY,
    ERR_INVALID_REQUEST,
    ERR_TEAM_NOT_FOUND,
    NON_EXISTENT_UUID,
    assert_error_envelope,
    assert_instant_equals,
    assert_managed_identity,
    assert_two_decimal_value,
    cit_limit_for,
    create_case,
    create_hospital,
    create_referral,
    dispatched_organ,
    expected_cold_ischemic_projection,
    finalize_authorization,
    frozen_case_by_donor_loss,
    observation_payload,
    open_registry_authorization,
    open_screening,
    organ_payload,
    read_asset,
    read_case,
    read_hospital,
    read_organ,
    read_performance,
    read_team,
    record_disposition,
    recovered_organ,
    rule_screening,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The error envelope and the declared status per family
# ---------------------------------------------------------------------------
def test_error_envelope_shape_and_http_status_are_pinned_per_code(env):
    """A malformed body, an unknown id and a duplicate code differ only in status.

    PRD 2.5: "Body shape is then checked: every required field must be present,
    every value must match its declared type, every enumerated value must be a
    declared member of its enumeration, and every numeric value must fall inside
    its declared range. Any failure yields `ERR_INVALID_REQUEST` (400 Bad
    Request)."
    PRD 2.5: "a `recovery_team_id` that names no team yields
    `ERR_TEAM_NOT_FOUND`; a `transport_asset_id` that names no asset yields
    `ERR_ASSET_NOT_FOUND`. All five are 404 Not Found."
    PRD 2.5: "Uniqueness is enforced on `hospital_code`, `team_code`,
    `asset_code`, `donor_code`, and on the pair of a donor case together with an
    `organ_type`; a collision on any of these yields `ERR_DUPLICATE_KEY` (409
    Conflict)."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD 3.7: "a `turnaround_buffer_minutes` from 0 through 480 that defaults to
    90 and is applied symmetrically around every booked window when availability
    is tested"

    Design: Corner/errors/error_envelope_shape_and_http_status_are_pinned_per_code
    """
    env.set_clock("2026-09-08T08:00:00Z")
    team = validate_success(
        env.api.create_recovery_team(
            {"team_code": "ABD-1", "specialty": "ABDOMINAL"}, env.admin
        ),
        201,
    )
    assert team["turnaround_buffer_minutes"] == 90

    malformed = env.api.create_recovery_team({"team_code": "THX-1"}, env.admin)
    validate_error(malformed, ERR_INVALID_REQUEST, 400)
    assert_error_envelope(malformed.json())

    unknown = env.api.get_recovery_team(NON_EXISTENT_UUID, env.admin)
    validate_error(unknown, ERR_TEAM_NOT_FOUND, 404)
    assert_error_envelope(unknown.json())

    duplicate = env.api.create_recovery_team(
        {"team_code": "ABD-1", "specialty": "MULTIORGAN"}, env.admin
    )
    validate_error(duplicate, ERR_DUPLICATE_KEY, 409)
    assert_error_envelope(duplicate.json())

    survivor = read_team(env, team["id"])
    assert survivor["specialty"] == "ABDOMINAL"
    assert survivor["turnaround_buffer_minutes"] == 90


def test_organ_type_uniqueness_is_scoped_to_the_donor_case(env):
    """A second LIVER on the same case collides; a LIVER on another case does not.

    PRD 2.5: "Uniqueness is enforced on `hospital_code`, `team_code`,
    `asset_code`, `donor_code`, and on the pair of a donor case together with an
    `organ_type`; a collision on any of these yields `ERR_DUPLICATE_KEY` (409
    Conflict)."
    PRD 3.5: "The `DonorCoordinator` registers each recoverable organ on the case
    by naming its `organ_type`, one of `HEART`, `LUNG_LEFT`, `LUNG_RIGHT`,
    `LIVER`, `KIDNEY_LEFT`, `KIDNEY_RIGHT`, `PANCREAS` or `INTESTINE`, and a case
    may carry each type at most once."
    PRD 3.5: "Organs may be listed with optional filters on `donor_case_id`,
    `accepted_offer_id`, `transport_asset_id` and `status`."
    PRD 3.5: "starts it in status `PENDING_EVAL` with `viability_hold` false"

    Design: Corner/errors/organ_type_uniqueness_is_scoped_to_the_donor_case
    """
    env.set_clock("2026-09-08T08:00:00Z")
    hospital = create_hospital(
        env, hospital_code="MERCY", timely_referral_window_minutes=60
    )
    case_a = _case_at(env, hospital, "MRN-7301", "2026-09-08T07:30:00Z", "D-7301")
    case_b = _case_at(env, hospital, "MRN-7302", "2026-09-08T07:40:00Z", "D-7302")

    liver_a = validate_success(
        env.api.create_organ(case_a["id"], organ_payload("LIVER"), env.donor), 201
    )

    collision = env.api.create_organ(case_a["id"], organ_payload("LIVER"), env.donor)
    validate_error(collision, ERR_DUPLICATE_KEY, 409)

    liver_b = validate_success(
        env.api.create_organ(case_b["id"], organ_payload("LIVER"), env.donor), 201
    )
    assert liver_b["donor_case_id"] == case_b["id"]
    assert liver_b["status"] == "PENDING_EVAL"
    assert liver_b["viability_hold"] is False

    rows, meta = validate_paginated(
        env.api.list_organs(env.donor, {"donor_case_id": case_a["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [liver_a["id"]]

    assert read_case(env, case_a["id"])["organ_count"] == 1
    assert read_case(env, case_b["id"])["organ_count"] == 1


def _case_at(env, hospital, patient_mrn, trigger_event_at, donor_code):
    """Walk one referral all the way to a converted donor case on ``hospital``."""
    referral = create_referral(
        env, hospital["id"], trigger_event_at, patient_mrn=patient_mrn
    )
    screening = open_screening(env, referral["id"])
    submit_assessment(env, screening["id"], screening["version"], risk_factors=[])
    rule_screening(env, screening["id"], "CLEARED")
    packet = open_registry_authorization(
        env, referral["id"], registry_document_ref=f"REG-{patient_mrn}"
    )
    finalize_authorization(env, packet["id"], as_user=AUTH_USER_2)
    return create_case(env, referral["id"], packet["id"], donor_code=donor_code)


# ---------------------------------------------------------------------------
# The two logistics registries: create and read only
# ---------------------------------------------------------------------------
def test_recovery_team_and_transport_asset_round_trip(env):
    """Both registries create at 201 and read back exactly what was created.

    PRD 3.7: "An `OpoAdmin` creates each recovery team with a `team_code` of 2 to
    12 characters that is unique across teams, a `specialty` of `THORACIC`,
    `ABDOMINAL` or `MULTIORGAN`, and a `turnaround_buffer_minutes` from 0 through
    480 that defaults to 90 and is applied symmetrically around every booked
    window when availability is tested."
    PRD 3.7: "A new team starts with `booked_or_minutes` and
    `scheduled_operation_count` at zero."
    PRD 3.7: "each transport asset has an `asset_code` of 2 to 12 characters
    unique across assets, a `mode` of `GROUND`, `FIXED_WING` or `HELICOPTER`, and
    a `concurrent_leg_capacity` from 1 through 5 declaring how many organ legs it
    may carry over an overlapping window, defaulting to 1"
    PRD 3.7: "`active_leg_count` starts at zero and always reflects the number of
    organs assigned to that asset whose status is `RECOVERED`, that is, in
    transit."
    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    instant refreshed on every mutation of the resource, and `version`, an
    integer that starts at 1 and increments by one on every mutation."

    Design: Corner/endpoints/recovery_team_and_transport_asset_round_trip
    """
    env.set_clock("2026-09-08T08:00:00Z")

    team = validate_success(
        env.api.create_recovery_team(
            {
                "team_code": "MULTI-1",
                "specialty": "MULTIORGAN",
                "turnaround_buffer_minutes": 30,
            },
            env.admin,
        ),
        201,
    )
    assert_managed_identity(team)
    assert team["turnaround_buffer_minutes"] == 30
    assert team["booked_or_minutes"] == 0
    assert team["scheduled_operation_count"] == 0
    assert team["version"] == 1

    read_back_team = read_team(env, team["id"])
    assert read_back_team["team_code"] == "MULTI-1"
    assert read_back_team["specialty"] == "MULTIORGAN"
    assert read_back_team["turnaround_buffer_minutes"] == 30
    assert read_back_team["version"] == team["version"]

    asset = validate_success(
        env.api.create_transport_asset(
            {
                "asset_code": "JET-1",
                "mode": "FIXED_WING",
                "concurrent_leg_capacity": 3,
            },
            env.admin,
        ),
        201,
    )
    assert_managed_identity(asset)
    assert asset["concurrent_leg_capacity"] == 3
    assert asset["active_leg_count"] == 0

    read_back_asset = read_asset(env, asset["id"])
    assert read_back_asset["asset_code"] == "JET-1"
    assert read_back_asset["mode"] == "FIXED_WING"
    assert read_back_asset["active_leg_count"] == 0
    assert read_back_asset["version"] == asset["version"]


def test_transport_dispatch_links_the_organ_to_its_asset(env):
    """One call links the asset and derives the whole cold-ischemic block.

    PRD 3.5: "The cold-ischemic ceilings are four hours for a `HEART`, six hours
    each for `LUNG_LEFT` and `LUNG_RIGHT`, twelve hours each for a `LIVER` and a
    `PANCREAS`, eight hours for an `INTESTINE`, and eighteen hours each for
    `KIDNEY_LEFT` and `KIDNEY_RIGHT`, all expressed internally in whole minutes."
    PRD 3.7: "First, the elapsed cold time so far is the whole minutes from the
    organ's `cross_clamp_at` to `transport_depart_at`, and `transit_minutes` is
    the whole minutes from `transport_depart_at` to `transport_arrive_at`, both
    truncated downward."
    PRD 3.7: "a margin of at least 120 minutes selects standard prep at 45
    minutes, otherwise a margin of at least 60 minutes selects expedited prep at
    30 minutes, otherwise crash prep at 20 minutes"
    PRD 3.7: "Third, `projected_cold_ischemic_minutes` is the elapsed minutes
    plus `transit_minutes` plus the selected `implant_prep_minutes`; the tier is
    **not** re-selected from this final figure, exactly one pass is performed,
    and no fixed point is sought."
    PRD 3.7: "Fourth, `projected_cit_margin_minutes` is the organ's
    `cit_limit_minutes` less `projected_cold_ischemic_minutes`."
    PRD 3.5: "Organs may be listed with optional filters on `donor_case_id`,
    `accepted_offer_id`, `transport_asset_id` and `status`."

    Design: Corner/endpoints/transport_dispatch_links_the_organ_to_its_asset
    """
    bundle = dispatched_organ(
        env,
        "KIDNEY_LEFT",
        "2026-09-08T09:00:00Z",
        transit_minutes=150,
        depart_offset_minutes=60,
        asset_overrides={"asset_code": "VAN-1", "mode": "GROUND"},
    )
    organ = bundle.organ("KIDNEY_LEFT")
    assert organ["cit_limit_minutes"] == cit_limit_for("KIDNEY_LEFT") == 1080
    assert_instant_equals(organ["cross_clamp_at"], "2026-09-08T12:00:00Z")

    projection = expected_cold_ischemic_projection(
        1080,
        "2026-09-08T12:00:00Z",
        "2026-09-08T13:00:00Z",
        "2026-09-08T15:30:00Z",
    )
    assert projection["transit_minutes"] == 150
    assert organ["transport_asset_id"] == bundle.asset["id"]
    assert organ["transit_minutes"] == 150
    assert organ["implant_prep_minutes"] == 45
    assert organ["projected_cold_ischemic_minutes"] == 255
    assert organ["projected_cit_margin_minutes"] == 825

    assert read_asset(env, bundle.asset["id"])["active_leg_count"] == 1

    rows, meta = validate_paginated(
        env.api.list_organs(env.logistics, {"transport_asset_id": bundle.asset["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [organ["id"]]


def test_hospital_performance_report_pins_every_derived_field(env):
    """One transplanted organ pins every ratio and lands the tier on PROBATION.

    PRD 3.8: "is a computed read against one hospital and persists nothing. It
    accepts an optional `window_days` integer, defaulting to 365, and an optional
    `basis` of `CLINICAL_TRIGGER` or `DEATH_NOTE`, defaulting to
    `CLINICAL_TRIGGER`."
    PRD 3.8: "an `eligible_referral_count`, being the number of in-scope
    referrals whose `ventilated` is true, which is the imminent-death
    denominator; a `timely_referral_count`, being the number of in-scope
    referrals that are both ventilated and timely; a `cleared_referral_count`,
    being the number of in-scope referrals whose `status` is `AUTH_PENDING`,
    `CONVERTED` or `NOT_CONVERTED`; a `converted_referral_count`, being the
    number whose `status` is `CONVERTED`; and a `transplanted_organ_count`, being
    the number of organs in status `TRANSPLANTED` whose donor case was converted
    from an in-scope referral."
    PRD 3.8: "The report's `timely_referral_rate` is null when
    `eligible_referral_count` is zero, and otherwise one hundred multiplied by
    the windowed timely count, divided by `eligible_referral_count`, rounded half
    up to two decimal places."
    PRD 3.8: "The `organs_per_donor` figure is null when
    `converted_referral_count` is zero, and otherwise `transplanted_organ_count`
    divided by `converted_referral_count`, rounded half up to two decimal
    places."
    PRD 3.8: "Otherwise, if the windowed `timely_referral_rate` is at least 75.00
    **and** the `conversion_rate` — treated as zero when null — is at least 65.00
    **and** `organs_per_donor` — likewise treated as zero when null — is at least
    3.00, the tier is `PASS`. Otherwise, if the windowed `timely_referral_rate`
    is at least 60.00, the tier is `PROBATION`."
    PRD 3.1: "if `referral_count` is below four the sample is too small to judge
    and the posture is `GOOD_STANDING` regardless of rate"

    Design: Corner/endpoints/hospital_performance_report_pins_every_derived_field
    """
    bundle = recovered_organ(
        env, "KIDNEY_LEFT", "2026-09-08T09:00:00Z", specialty="ABDOMINAL"
    )
    referral = bundle.referral
    assert referral["referral_lag_minutes"] == 30
    assert referral["timeliness_flag"] == "TIMELY"

    transplanted = record_disposition(
        env, bundle.organ_id("KIDNEY_LEFT"), "TRANSPLANTED"
    )
    assert transplanted["status"] == "TRANSPLANTED"

    report = read_performance(env, bundle.hospital_id)
    assert report["window_days"] == 365
    assert report["basis"] == "CLINICAL_TRIGGER"
    assert report["eligible_referral_count"] == 1
    assert report["timely_referral_count"] == 1
    assert_two_decimal_value(report["timely_referral_rate"], 100.00)
    assert report["cleared_referral_count"] == 1
    assert report["converted_referral_count"] == 1
    assert_two_decimal_value(report["conversion_rate"], 100.00)
    assert report["transplanted_organ_count"] == 1
    assert_two_decimal_value(report["organs_per_donor"], 1.00)
    assert report["recertification_tier"] == "PROBATION"

    hospital = read_hospital(env, bundle.hospital_id)
    assert hospital["referral_count"] == 1
    assert_two_decimal_value(hospital["timely_referral_rate"], 100.00)
    assert hospital["partner_posture"] == "GOOD_STANDING"


def test_disposition_stays_open_after_the_case_freezes(env):
    """The freeze refuses charting and registration but not the research referral.

    PRD 3.4: "An observation recording `cardiac_arrest` as true drives the case
    from `STABILIZING`, `OPTIMIZED` or `DECOMPENSATING` to `physiologic_status`
    `LOST`, which is terminal for that dimension, and sets `viability_index` to
    0. Unless the case has already reached `allocation_status` `RECOVERED`, the
    allocation dimension also moves to `CLOSED` with `closed_reason`
    `DONOR_LOST`."
    PRD 3.4: "Every organ of the case whose status is `PENDING_EVAL`,
    `ALLOCATABLE`, `OFFERING` or `ACCEPTED` moves to `NON_TRANSPLANTABLE` with
    `nontransplantable_reason` `VIABILITY_FAILURE` and its `accepted_offer_id`
    cleared to null"
    PRD 2.8: "`FROZEN` refuses every child mutation of the case with
    `ERR_CASE_FROZEN` (409 Conflict): charting an observation, registering an
    organ, evaluating an organ, generating a match run, responding to an offer,
    booking a recovery operation, recording cross-clamp, and dispatching
    transport."
    PRD 3.8: "Uniquely among case-child mutations, recording a disposition is
    permitted even when the case's posture is `FROZEN`, so that organs stranded
    by a closure can still be accounted for."
    PRD 3.8: "When a disposition leaves **every** organ of the case in one of its
    terminal states — `TRANSPLANTED`, `DISCARDED`, `RESEARCH_REFERRED` or
    `TISSUE_REFERRED` — the case's `allocation_status` advances `RECOVERED →
    CLOSED` with `closed_reason` `RECOVERY_COMPLETE`"

    Design: Corner/endpoints/disposition_stays_open_after_the_case_freezes
    """
    bundle = frozen_case_by_donor_loss(env, "LIVER", "2026-09-08T09:00:00Z")

    case = bundle.case
    assert case["physiologic_status"] == "LOST"
    assert case["allocation_status"] == "CLOSED"
    assert case["closed_reason"] == "DONOR_LOST"
    assert case["case_posture"] == "FROZEN"

    organ = bundle.organ("LIVER")
    assert organ["status"] == "NON_TRANSPLANTABLE"
    assert organ["nontransplantable_reason"] == "VIABILITY_FAILURE"
    assert organ["accepted_offer_id"] is None

    refused_observation = env.api.create_observation(
        bundle.case_id,
        observation_payload(
            "2026-09-08T10:00:00Z",
            map_mmhg=70,
            pao2_fio2_ratio=320,
            sodium=140,
            urine_output_ml_per_kg_hr=1.0,
            pressor_count=0,
        ),
        env.donor,
    )
    validate_error(refused_observation, ERR_CASE_FROZEN, 409)
    assert read_case(env, bundle.case_id)["observation_count"] == 1

    refused_organ = env.api.create_organ(
        bundle.case_id, organ_payload("KIDNEY_LEFT"), env.donor
    )
    validate_error(refused_organ, ERR_CASE_FROZEN, 409)
    assert read_case(env, bundle.case_id)["organ_count"] == 1

    referred = record_disposition(
        env, organ["id"], "RESEARCH_REFERRED", research_protocol_code="PROTO-11"
    )
    assert referred["status"] == "RESEARCH_REFERRED"
    assert referred["research_protocol_code"] == "PROTO-11"
    assert read_organ(env, organ["id"])["status"] == "RESEARCH_REFERRED"

    after = read_case(env, bundle.case_id)
    assert after["allocation_status"] == "CLOSED"
    assert after["closed_reason"] == "DONOR_LOST"
    assert after["organ_count"] == 1
