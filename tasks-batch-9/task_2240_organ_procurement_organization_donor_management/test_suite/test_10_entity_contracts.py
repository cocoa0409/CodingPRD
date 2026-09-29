"""The per-entity field contract: creation, retrieval, listing, defaults, shape."""

from test_helpers import (
    ERR_ASSET_NOT_FOUND,
    ERR_AUTHORIZATION_NOT_FOUND,
    ERR_AUTHORIZATION_REFERRAL_MISMATCH,
    ERR_DONOR_CASE_NOT_FOUND,
    ERR_HOSPITAL_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MATCH_RUN_NOT_FOUND,
    ERR_OPERATION_NOT_FOUND,
    ERR_ORGAN_NOT_FOUND,
    ERR_REFERRAL_NOT_FOUND,
    ERR_SCREENING_NOT_FOUND,
    ERR_TEAM_NOT_FOUND,
    OMIT,
    PARTNER_POSTURE_GOOD_STANDING,
    RISK_TIER_STANDARD,
    TIMELINESS_TIMELY,
    allocatable_organ,
    assert_append_only_identity,
    assert_instant_equals,
    assert_managed_identity,
    assert_slot_conservation,
    authorized_referral,
    candidate_sequence,
    converted_case,
    create_asset,
    create_hospital,
    death_referral_payload,
    donor_case_payload,
    instants_equal,
    list_serology,
    observation_payload,
    open_match_run,
    open_screening,
    read_authorization,
    read_case,
    read_hospital,
    read_organ,
    read_referral,
    read_screening,
    received_referral,
    recovery_operation_payload,
    register_organ,
    rule_screening,
    serology_result_payload,
    submit_assessment,
    transport_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-09-02T10:00:00Z"
TRIGGER = "2026-09-02T09:30:00Z"

# Identifiers that were never issued by the server.
UNISSUED_HOSPITAL = "11111111-1111-4111-8111-111111111111"
UNISSUED_REFERRAL = "22222222-2222-4222-8222-222222222222"
UNISSUED_SCREENING = "33333333-3333-4333-8333-333333333333"
UNISSUED_AUTHORIZATION = "44444444-4444-4444-8444-444444444444"
UNISSUED_CASE = "55555555-5555-4555-8555-555555555555"
UNISSUED_ORGAN = "66666666-6666-4666-8666-666666666666"
UNISSUED_RUN = "77777777-7777-4777-8777-777777777777"
UNISSUED_OPERATION = "88888888-8888-4888-8888-888888888888"
UNISSUED_TEAM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNISSUED_ASSET = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UNISSUED_OBSERVATION_PARENT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


# ---------------------------------------------------------------------------
# DeathReferral: creation, retrieval, listing
# ---------------------------------------------------------------------------
def test_death_referral_creation_returns_every_declared_field(env):
    """One POST returns the echoed inputs, the stamped instant and both lags.

    PRD 3.1: "The server stamps `referred_at` from the logical clock and the new
    referral enters status `RECEIVED`."
    PRD 3.1: "Under the death-note basis the basis instant is
    `death_pronounced_at`, and the resulting value is stored as
    `audit_lag_minutes`; when `death_pronounced_at` is null, `audit_lag_minutes`
    is null."
    PRD 3.1: "Its `timely_referral_count` increases by one when the new
    referral's `timeliness_flag` is `TIMELY`".

    Design: Corner/entities/death_referral_creation_returns_every_declared_field
    """
    env.set_clock(CLOCK)
    hospital = create_hospital(
        env,
        name="Mercy General",
        hospital_code="MERCY",
        timely_referral_window_minutes=60,
    )

    created = env.api.create_death_referral(
        death_referral_payload(
            hospital["id"],
            TRIGGER,
            patient_mrn="MRN-1001",
            age_years=52,
            ventilated=True,
            gcs_score=4,
            cause_of_death_category="CVA_STROKE",
            death_pronounced_at="2026-09-02T09:45:00Z",
        ),
        env.coordinator,
    )
    referral = validate_success(created, 201)

    assert referral["status"] == "RECEIVED"
    assert_instant_equals(referral["referred_at"], CLOCK)
    assert referral["referral_lag_minutes"] == 30
    assert referral["timeliness_flag"] == TIMELINESS_TIMELY
    assert referral["audit_lag_minutes"] == 15
    assert referral["patient_mrn"] == "MRN-1001"
    assert referral["age_years"] == 52
    assert referral["ventilated"] is True
    assert referral["gcs_score"] == 4
    assert referral["cause_of_death_category"] == "CVA_STROKE"

    standing = read_hospital(env, hospital["id"])
    assert standing["referral_count"] == 1
    assert standing["timely_referral_count"] == 1


def test_get_death_referral_returns_the_stored_row(env):
    """A read reports the same values the creation response did.

    PRD 3.1: "Under the death-note basis the basis instant is
    `death_pronounced_at`, and the resulting value is stored as
    `audit_lag_minutes`; when `death_pronounced_at` is null, `audit_lag_minutes`
    is null."
    PRD 2.4: "`version`, an integer that starts at 1 and increments by one on
    every mutation".

    Design: Corner/entities/get_death_referral_returns_the_stored_row
    """
    bundle = received_referral(env, CLOCK, patient_mrn="MRN-1002", age_years=52,
                              gcs_score=4, cause_of_death_category="CVA_STROKE")

    stored = read_referral(env, bundle.referral_id)

    assert stored["patient_mrn"] == "MRN-1002"
    assert stored["referral_lag_minutes"] == 30
    assert stored["status"] == "RECEIVED"
    assert stored["version"] == 1
    assert stored["audit_lag_minutes"] is None


def test_death_referral_list_filters_and_paginates(env):
    """Two pages of three rows, then the status filter drops the ruled-out one.

    PRD 2.3: "Unless a specific endpoint states otherwise, list results are
    sorted by `created_at` in ascending order."
    PRD 2.3: "where `total_count` is the number of matching rows before the limit
    and offset are applied and `has_more` indicates whether further rows remain
    beyond the current page".
    PRD 3.1: "Referrals may be listed with optional filters on
    `hospital_partner_id`, `status` and `timeliness_flag`".

    Design: Corner/entities/death_referral_list_filters_and_paginates
    """
    env.set_clock(CLOCK)
    hospital = create_hospital(
        env,
        name="Mercy General",
        hospital_code="MERCY",
        timely_referral_window_minutes=60,
    )
    first = validate_success(
        env.api.create_death_referral(
            death_referral_payload(
                hospital["id"],
                TRIGGER,
                patient_mrn="MRN-1101",
                age_years=52,
                gcs_score=4,
                cause_of_death_category="CVA_STROKE",
            ),
            env.coordinator,
        ),
        201,
    )
    second = validate_success(
        env.api.create_death_referral(
            death_referral_payload(
                hospital["id"],
                "2026-09-02T09:40:00Z",
                patient_mrn="MRN-1102",
                age_years=61,
                cause_of_death_category="ANOXIA",
            ),
            env.coordinator,
        ),
        201,
    )
    third = validate_success(
        env.api.create_death_referral(
            death_referral_payload(
                hospital["id"],
                "2026-09-02T09:50:00Z",
                patient_mrn="MRN-1103",
                age_years=77,
                ventilated=False,
                gcs_score=9,
                cause_of_death_category="OTHER",
            ),
            env.coordinator,
        ),
        201,
    )
    screening = open_screening(env, third["id"])
    submit_assessment(
        env,
        screening["id"],
        screening["version"],
        risk_factors=["UNKNOWN_MEDICAL_SOCIAL_HISTORY"],
        informant_reliability="MEDICAL_RECORD_ONLY",
    )
    rule_screening(
        env, screening["id"], "RULED_OUT", ruled_out_reason="AGE_CRITERIA"
    )

    rows, meta = validate_paginated(
        env.api.list_death_referrals(
            env.admin,
            {"hospital_partner_id": hospital["id"], "limit": 2, "offset": 0},
        )
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert [row["id"] for row in rows] == [first["id"], second["id"]]

    rows, meta = validate_paginated(
        env.api.list_death_referrals(
            env.admin,
            {"hospital_partner_id": hospital["id"], "limit": 2, "offset": 2},
        )
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [third["id"]]

    rows, meta = validate_paginated(
        env.api.list_death_referrals(
            env.admin,
            {"hospital_partner_id": hospital["id"], "status": "RECEIVED"},
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert read_referral(env, third["id"])["status"] == "RULED_OUT"


# ---------------------------------------------------------------------------
# Existence: path identifiers and body foreign keys
# ---------------------------------------------------------------------------
def test_unknown_path_ids_return_their_own_not_found_error(env):
    """Eight reads on unissued identifiers each name their own entity family.

    PRD 2.5: "The relevant not-found codes are `ERR_HOSPITAL_NOT_FOUND`,
    `ERR_REFERRAL_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`,
    `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_DONOR_CASE_NOT_FOUND`,
    `ERR_ORGAN_NOT_FOUND`, `ERR_MATCH_RUN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND` and
    `ERR_OPERATION_NOT_FOUND`, each returned with 404 Not Found."

    Design: Corner/entities/unknown_path_ids_return_their_own_not_found_error
    """
    env.set_clock(CLOCK)

    validate_error(
        env.api.get_hospital_partner(UNISSUED_HOSPITAL, env.admin),
        ERR_HOSPITAL_NOT_FOUND,
        404,
    )
    validate_error(
        env.api.get_death_referral(UNISSUED_REFERRAL, env.admin),
        ERR_REFERRAL_NOT_FOUND,
        404,
    )
    validate_error(
        env.api.get_screening(UNISSUED_SCREENING, env.admin),
        ERR_SCREENING_NOT_FOUND,
        404,
    )
    validate_error(
        env.api.get_authorization(UNISSUED_AUTHORIZATION, env.admin),
        ERR_AUTHORIZATION_NOT_FOUND,
        404,
    )
    validate_error(
        env.api.get_donor_case(UNISSUED_CASE, env.admin),
        ERR_DONOR_CASE_NOT_FOUND,
        404,
    )
    validate_error(
        env.api.get_organ(UNISSUED_ORGAN, env.admin), ERR_ORGAN_NOT_FOUND, 404
    )
    validate_error(
        env.api.get_match_run(UNISSUED_RUN, env.admin), ERR_MATCH_RUN_NOT_FOUND, 404
    )
    validate_error(
        env.api.get_recovery_operation(UNISSUED_OPERATION, env.admin),
        ERR_OPERATION_NOT_FOUND,
        404,
    )


def test_unknown_body_foreign_keys_return_their_own_not_found_error(env):
    """A body foreign key is resolved before any state gate can speak.

    PRD 2.5: "Foreign keys supplied in a request body are resolved after path
    identifiers and before any body-shape validation."
    PRD 2.5: "a `recovery_team_id` that names no team yields
    `ERR_TEAM_NOT_FOUND`; a `transport_asset_id` that names no asset yields
    `ERR_ASSET_NOT_FOUND`. All five are 404 Not Found."

    Design: Corner/entities/unknown_body_foreign_keys_return_their_own_not_found_error
    """
    bundle = converted_case(env, CLOCK, organ_types=["LIVER"], patient_mrn="MRN-1201")
    assert read_organ(env, bundle.only_organ_id)["status"] == "PENDING_EVAL"

    validate_error(
        env.api.create_death_referral(
            death_referral_payload(UNISSUED_HOSPITAL, TRIGGER, patient_mrn="MRN-1202"),
            env.coordinator,
        ),
        ERR_HOSPITAL_NOT_FOUND,
        404,
    )
    validate_error(
        env.api.create_recovery_operation(
            bundle.case_id,
            recovery_operation_payload(
                UNISSUED_TEAM, "2026-09-02T12:00:00Z", "2026-09-02T15:00:00Z"
            ),
            env.logistics,
        ),
        ERR_TEAM_NOT_FOUND,
        404,
    )
    validate_error(
        env.api.dispatch_transport(
            bundle.only_organ_id,
            transport_payload(
                UNISSUED_ASSET, "2026-09-02T12:00:00Z", "2026-09-02T13:00:00Z"
            ),
            env.logistics,
        ),
        ERR_ASSET_NOT_FOUND,
        404,
    )

    assert read_organ(env, bundle.only_organ_id)["transport_asset_id"] is None
    _rows, meta = validate_paginated(
        env.api.list_recovery_operations(
            env.logistics, {"donor_case_id": bundle.case_id}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Body shape: required fields, ranges and enum membership
# ---------------------------------------------------------------------------
def test_death_referral_missing_required_field_is_rejected(env):
    """Omitting `ventilated` is a rejection rather than a silent false.

    PRD 2.5: "every required field must be present, every value must match its
    declared type, every enumerated value must be a declared member of its
    enumeration, and every numeric value must fall inside its declared range. Any
    failure yields `ERR_INVALID_REQUEST` (400 Bad Request)."
    PRD 3.1: "a `ventilated` boolean stating whether the patient was on
    mechanical ventilation at the trigger event".

    Design: Corner/entities/death_referral_missing_required_field_is_rejected
    """
    env.set_clock(CLOCK)
    hospital = create_hospital(env, name="Mercy General", hospital_code="MERCY")

    validate_error(
        env.api.create_death_referral(
            death_referral_payload(
                hospital["id"],
                TRIGGER,
                patient_mrn="MRN-1301",
                age_years=44,
                ventilated=OMIT,
            ),
            env.coordinator,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    assert read_hospital(env, hospital["id"])["referral_count"] == 0


def test_out_of_range_and_unknown_enum_values_are_rejected(env):
    """A score outside 3..15 and an undeclared cause both fail on shape alone.

    PRD 3.1: "the `gcs_score` as a Glasgow Coma Scale total from 3 through 15, a
    `cause_of_death_category` drawn from `ANOXIA`, `CVA_STROKE`, `HEAD_TRAUMA`,
    `CNS_TUMOR` or `OTHER`".
    PRD 2.10: "6. **Body shape, types, enum membership and numeric ranges** —
    `ERR_INVALID_REQUEST`, on every POST endpoint."

    Design: Corner/entities/out_of_range_and_unknown_enum_values_are_rejected
    """
    env.set_clock(CLOCK)
    hospital = create_hospital(env, name="Mercy General", hospital_code="MERCY")

    validate_error(
        env.api.create_death_referral(
            death_referral_payload(
                hospital["id"], TRIGGER, patient_mrn="MRN-1401", gcs_score=20
            ),
            env.coordinator,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        env.api.create_death_referral(
            death_referral_payload(
                hospital["id"],
                TRIGGER,
                patient_mrn="MRN-1402",
                cause_of_death_category="DROWNING",
            ),
            env.coordinator,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    assert read_hospital(env, hospital["id"])["referral_count"] == 0


# ---------------------------------------------------------------------------
# Declared defaults
# ---------------------------------------------------------------------------
def test_hospital_partner_optional_fields_fall_back_to_defaults(env):
    """A bare registration takes the declared policy, window and capacity.

    PRD 3.1: "The `referral_trigger_policy` states which clinical event obliges
    the hospital to call the OPO and is one of `VENTILATED_NEURO_INJURY`,
    `ALL_VENTILATED_DEATHS` or `ALL_DEATHS`, defaulting to
    `VENTILATED_NEURO_INJURY`."
    PRD 3.1: "A freshly registered hospital starts with `referral_count`,
    `timely_referral_count`, `untimely_referral_count` and
    `converted_donor_count` all at zero, `timely_referral_rate` at null, and
    `partner_posture` at `GOOD_STANDING`."
    PRD 3.7: "a `concurrent_leg_capacity` from 1 through 5 declaring how many
    organ legs it may carry over an overlapping window, defaulting to 1;
    `active_leg_count` starts at zero".

    Design: Corner/entities/hospital_partner_optional_fields_fall_back_to_defaults
    """
    env.set_clock(CLOCK)

    hospital = create_hospital(
        env,
        name="Riverside Medical",
        hospital_code="RIVER",
        timely_referral_window_minutes=OMIT,
    )
    assert hospital["referral_trigger_policy"] == "VENTILATED_NEURO_INJURY"
    assert hospital["timely_referral_window_minutes"] == 60
    assert hospital["referral_count"] == 0
    assert hospital["timely_referral_count"] == 0
    assert hospital["untimely_referral_count"] == 0
    assert hospital["converted_donor_count"] == 0
    assert hospital["timely_referral_rate"] is None
    assert hospital["partner_posture"] == PARTNER_POSTURE_GOOD_STANDING

    asset = create_asset(env, asset_code="VAN-9", mode="GROUND")
    assert asset["concurrent_leg_capacity"] == 1
    assert asset["active_leg_count"] == 0
    assert asset["mode"] == "GROUND"


def test_match_run_slot_and_acceptance_clock_defaults_applied(env):
    """No slot count and no acceptance clock means two slots and sixty minutes.

    PRD 3.5: "an optional `primary_offer_slots` integer from 1 through 3
    declaring how many offers may sit pending at once — primary plus backups —
    which defaults to 2".
    PRD 3.5: "an optional `acceptance_clock_minutes` from 5 through 240 stating
    how long that centre gets to answer once its offer is promoted, defaulting to
    60".
    PRD 3.5: "assigns `run_number` as one more than the highest existing run
    number on that organ — so the first run on an organ is number 1".
    PRD 3.6: "its `expires_at` set to that instant plus its own
    `acceptance_clock_minutes`".

    Design: Corner/entities/match_run_slot_and_acceptance_clock_defaults_applied
    """
    bundle = allocatable_organ(env, "LIVER", CLOCK)

    bundle.run = open_match_run(env, bundle.only_organ_id, candidate_sequence(1))
    bundle.refresh_offers()

    assert bundle.run["primary_offer_slots"] == 2
    assert bundle.run["run_number"] == 1
    assert_instant_equals(bundle.run["generated_at"], CLOCK)
    assert bundle.run["pending_offer_count"] == 1
    assert bundle.run["slots_free"] == 1
    assert bundle.run["candidate_count"] == 1
    assert_slot_conservation(bundle.run)

    offer = bundle.offers[0]
    assert offer["acceptance_clock_minutes"] == 60
    assert_instant_equals(offer["offered_at"], CLOCK)
    assert_instant_equals(offer["expires_at"], "2026-09-02T11:00:00Z")
    assert offer["increased_risk_ack"] is False


# ---------------------------------------------------------------------------
# Server-derived and server-assigned fields
# ---------------------------------------------------------------------------
def test_organ_cit_limit_is_derived_from_organ_type(env):
    """Three organs on one case take three different ceilings with no input.

    PRD 3.5: "The cold-ischemic ceilings are four hours for a `HEART`, six hours
    each for `LUNG_LEFT` and `LUNG_RIGHT`, twelve hours each for a `LIVER` and a
    `PANCREAS`, eight hours for an `INTESTINE`, and eighteen hours each for
    `KIDNEY_LEFT` and `KIDNEY_RIGHT`, all expressed internally in whole minutes."
    PRD 3.5: "Registration sets the organ's `cit_limit_minutes` from the
    cold-ischemic ceiling for its type and starts it in status `PENDING_EVAL`
    with `viability_hold` false".

    Design: Corner/entities/organ_cit_limit_is_derived_from_organ_type
    """
    bundle = converted_case(env, CLOCK, patient_mrn="MRN-1601")

    heart = register_organ(env, bundle.case_id, "HEART")
    liver = register_organ(env, bundle.case_id, "LIVER")
    kidney = register_organ(env, bundle.case_id, "KIDNEY_LEFT")

    assert heart["cit_limit_minutes"] == 240
    assert liver["cit_limit_minutes"] == 720
    assert kidney["cit_limit_minutes"] == 1080
    assert heart["status"] == "PENDING_EVAL"
    assert heart["viability_hold"] is False
    assert liver["projected_cold_ischemic_minutes"] is None
    assert kidney["cross_clamp_at"] is None

    case = read_case(env, bundle.case_id)
    assert case["organ_count"] == 3
    assert case["organs_accepted_count"] == 0


def test_donor_case_identity_and_version_are_server_assigned(env):
    """The case is minted with its identity, both dimensions and the risk snapshot.

    PRD 2.4: "Each persisted resource carries a server-minted `id` formatted as a
    UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601
    UTC instant with exactly three fractional digits."
    PRD 3.4: "The new case starts with `physiologic_status` at `STABILIZING`,
    `allocation_status` at `NOT_STARTED` and `case_posture` at `OPEN`".
    PRD 3.4: "`risk_tier_snapshot` is pinned from the screening's `risk_tier` at
    this moment, taking the value `STANDARD` or `INCREASED_RISK`, and never
    changes thereafter".

    Design: Corner/entities/donor_case_identity_and_version_are_server_assigned
    """
    bundle = authorized_referral(env, CLOCK, patient_mrn="MRN-1701")
    assert read_screening(env, bundle.screening_id)["risk_tier"] == RISK_TIER_STANDARD

    case = validate_success(
        env.api.create_donor_case(
            donor_case_payload(
                bundle.referral_id, bundle.authorization_id, donor_code="D-1701"
            ),
            env.donor,
        ),
        201,
    )

    assert_managed_identity(case)
    assert case["version"] == 1
    assert_instant_equals(case["created_at"], CLOCK)
    assert instants_equal(case["created_at"], case["updated_at"])
    assert case["physiologic_status"] == "STABILIZING"
    assert case["allocation_status"] == "NOT_STARTED"
    assert case["case_posture"] == "OPEN"
    assert case["viability_index"] == 0
    assert case["risk_tier_snapshot"] == RISK_TIER_STANDARD
    assert case["closed_reason"] is None
    assert case["observation_count"] == 0


def test_serology_result_is_immutable_and_carries_no_version(env):
    """Two filings on one marker are two rows, neither carrying a version.

    PRD 2.4: "Three resources are append-only records rather than managed
    aggregates, and they carry **only** `id` and `created_at`: a
    `SerologyResult`, a `NextOfKinContact`, and a `PhysiologicObservation`. For
    these three, both `updated_at` and `version` are absent from the response body
    entirely — not null, absent."
    PRD 3.2: "it is true when the `marker` is one of the four absolute markers
    `HIV_AB`, `HIV_NAT`, `HBV_SAG` or `HCV_NAT`, **and** the `result` is
    `POSITIVE`, **and** `nat_confirmed` is true".

    Design: Corner/entities/serology_result_is_immutable_and_carries_no_version
    """
    bundle = received_referral(env, CLOCK, patient_mrn="MRN-1801")
    bundle.screening = open_screening(env, bundle.referral_id)

    first = validate_success(
        env.api.file_serology_result(
            bundle.screening_id,
            serology_result_payload("CMV_IGG", "POSITIVE", "2026-09-02T09:50:00Z"),
            env.lab,
        ),
        201,
    )
    second = validate_success(
        env.api.file_serology_result(
            bundle.screening_id,
            serology_result_payload("CMV_IGG", "NEGATIVE", "2026-09-02T09:55:00Z"),
            env.lab,
        ),
        201,
    )

    assert_append_only_identity(first)
    assert_append_only_identity(second)
    assert first["id"] != second["id"]
    assert first["absolute_contraindication_marker"] is False
    assert first["nat_confirmed"] is False

    rows = list_serology(env, bundle.screening_id)
    assert len(rows) == 2
    assert rows[0]["marker"] == "CMV_IGG"
    assert rows[1]["result"] == "NEGATIVE"

    screening = read_screening(env, bundle.screening_id)
    assert screening["absolute_contraindication"] is False
    assert screening["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Parent and cross-reference integrity
# ---------------------------------------------------------------------------
def test_observation_under_an_unknown_donor_case_is_rejected(env):
    """Charting resolves the parent case before it looks at the vitals.

    PRD 2.5: "When a request path contains more than one resource identifier, the
    identifiers are resolved strictly left to right, and the first one that does
    not resolve determines the error."
    PRD 2.10: "4. **Path identifier existence, left to right** — the nine 404
    codes of §2.5, on every path-templated endpoint."

    Design: Corner/entities/observation_under_an_unknown_donor_case_is_rejected
    """
    env.set_clock(CLOCK)

    validate_error(
        env.api.create_observation(
            UNISSUED_OBSERVATION_PARENT,
            observation_payload(
                TRIGGER,
                map_mmhg=70,
                pao2_fio2_ratio=300,
                sodium=140,
                urine_output_ml_per_kg_hr=1.0,
                pressor_count=0,
            ),
            env.donor,
        ),
        ERR_DONOR_CASE_NOT_FOUND,
        404,
    )

    validate_error(
        env.api.list_observations(UNISSUED_OBSERVATION_PARENT, env.donor),
        ERR_DONOR_CASE_NOT_FOUND,
        404,
    )


def test_donor_case_naming_another_referrals_authorization_is_rejected(env):
    """Both rows exist and are in state, but they belong to different decedents.

    PRD 3.4: "The named authorization must reference the same referral as the
    case, and the screening consulted must belong to that referral, otherwise
    `ERR_AUTHORIZATION_REFERRAL_MISMATCH`."
    PRD 3.4: "On success the referral advances `AUTH_PENDING → CONVERTED` and the
    hospital's `converted_donor_count` increases by one."

    Design: Corner/entities/donor_case_naming_another_referrals_authorization_is_rejected
    """
    first = authorized_referral(env, CLOCK, patient_mrn="MRN-1901")
    second = authorized_referral(env, CLOCK, patient_mrn="MRN-1902", age_years=55,
                                 cause_of_death_category="HEAD_TRAUMA")
    assert read_referral(env, second.referral_id)["status"] == "AUTH_PENDING"

    validate_error(
        env.api.create_donor_case(
            donor_case_payload(
                second.referral_id, first.authorization_id, donor_code="D-1902"
            ),
            env.donor,
        ),
        ERR_AUTHORIZATION_REFERRAL_MISMATCH,
        422,
    )
    assert read_referral(env, second.referral_id)["status"] == "AUTH_PENDING"

    case = validate_success(
        env.api.create_donor_case(
            donor_case_payload(
                second.referral_id, second.authorization_id, donor_code="D-1902"
            ),
            env.donor,
        ),
        201,
    )
    assert case["allocation_status"] == "NOT_STARTED"
    assert read_referral(env, second.referral_id)["status"] == "CONVERTED"
    assert read_authorization(env, first.authorization_id)["status"] == "AUTHORIZED"
