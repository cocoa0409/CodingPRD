"""Every declared formula walked on hand-computable inputs and on its constants."""

from test_helpers import (
    COORDINATOR_USER_9,
    PARTNER_POSTURE_GOOD_STANDING,
    PARTNER_POSTURE_WATCH,
    TIMELINESS_TIMELY,
    TIMELINESS_UNTIMELY,
    assert_two_decimal_value,
    chart_observation,
    cleared_referral,
    converted_case,
    create_hospital,
    create_referral,
    list_nok_contacts,
    make_donor_coordinator_headers,
    observation_payload,
    open_nok_authorization,
    open_screening,
    read_authorization,
    read_case,
    read_hospital,
    read_referral,
    record_nok_contact,
    rule_screening,
    submit_assessment,
    upload_document,
    validate_success,
)

CASE_CLOCK = "2026-09-04T09:00:00Z"
CHART_CLOCK = "2026-09-04T10:00:00Z"
INTAKE_CLOCK = "2026-09-04T08:00:00Z"


# ---------------------------------------------------------------------------
# The donor viability index and the tiers it feeds
# ---------------------------------------------------------------------------
def test_viability_index_sums_oxygenation_haemodynamic_and_metabolic_blocks(env):
    """One observation pins all three blocks: 30 plus 25 plus 5 makes 60.

    PRD 3.4: "Oxygenation is scored on `pao2_fio2_ratio` alone: a ratio of at
    least 300 scores 40 points, otherwise a ratio of at least 200 scores 30,
    otherwise a ratio of at least 100 scores 15, otherwise 0."
    PRD 3.4: "Haemodynamics starts from `map_mmhg`: a pressure of at least 70
    gives a base of 35 points, otherwise at least 60 gives 25, otherwise at least
    50 gives 10, otherwise 0."
    PRD 3.4: "Metabolic scoring combines two inputs: sodium contributes 15 points
    when it lies at or between 135 and 155 inclusive and 5 points otherwise;
    urine output contributes 10 points at 1.0 or above, 5 points at 0.5 or above,
    and 0 below that."
    PRD 3.4: "The three components are added and clamped into the range 0 through
    100 to give the observation's `viability_index_snapshot`"
    PRD 3.4: "which is true only when **all five** bounds hold simultaneously:
    `map_mmhg` is at least 60, `pao2_fio2_ratio` is at least 300"
    PRD 3.4: "The charting operator is recorded in `recorded_by_user_id`.
    Charting is one of the mutations blocked when the case is frozen."

    Design: Corner/calculations/viability_index_sums_oxygenation_haemodynamic_and_metabolic_blocks
    """
    bundle = converted_case(env, CASE_CLOCK, patient_mrn="MRN-4001")
    assert bundle.case["viability_index"] == 0
    assert bundle.case["physiologic_status"] == "STABILIZING"

    env.set_clock(CHART_CLOCK)
    charted = validate_success(
        env.api.create_observation(
            bundle.case_id,
            observation_payload(
                CHART_CLOCK,
                map_mmhg=65,
                pao2_fio2_ratio=250,
                sodium=130,
                urine_output_ml_per_kg_hr=0.4,
                pressor_count=0,
            ),
            make_donor_coordinator_headers(COORDINATOR_USER_9),
        ),
        201,
    )

    assert charted["viability_index_snapshot"] == 60
    assert charted["dmg_bundle_met"] is False
    assert charted["recorded_by_user_id"] == COORDINATOR_USER_9

    case = read_case(env, bundle.case_id)
    assert case["viability_index"] == 60
    assert case["physiologic_status"] == "STABILIZING"
    assert case["case_posture"] == "OPEN"
    assert case["observation_count"] == 1
    assert case["dmg_bundle_met_count"] == 0


def test_viability_tier_floors_are_inclusive_at_seventy_and_forty(env):
    """Seventy is optimized, forty is still stabilizing, thirty-five restricts.

    PRD 3.4: "otherwise an index of at least 70 gives `OPTIMIZED`, an index of at
    least 40 gives `STABILIZING`, and anything lower gives `DECOMPENSATING`."
    PRD 2.8: "Otherwise, if `physiologic_status` is `DECOMPENSATING`,
    `case_posture` is `RESTRICTED`. Otherwise it is `OPEN`."
    PRD 2.6: "Every threshold comparison in this specification is inclusive at
    the stated floor unless the text says otherwise."
    PRD 3.4: "The case's `dmg_bundle_met_count` is refreshed to the number of its
    observations whose `dmg_bundle_met` is true, and `observation_count` to the
    total number of its observations"

    Design: Corner/calculations/viability_tier_floors_are_inclusive_at_seventy_and_forty
    """
    bundle = converted_case(env, CASE_CLOCK, patient_mrn="MRN-4101")

    env.set_clock(CHART_CLOCK)
    at_seventy = chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            CHART_CLOCK,
            map_mmhg=65,
            pao2_fio2_ratio=300,
            sodium=130,
            urine_output_ml_per_kg_hr=0.4,
            pressor_count=0,
        ),
    )
    assert at_seventy["viability_index_snapshot"] == 70
    case = read_case(env, bundle.case_id)
    assert case["physiologic_status"] == "OPTIMIZED"
    assert case["case_posture"] == "OPEN"

    env.set_clock("2026-09-04T10:30:00Z")
    at_forty = chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-09-04T10:30:00Z",
            map_mmhg=55,
            pao2_fio2_ratio=150,
            sodium=140,
            urine_output_ml_per_kg_hr=0.4,
            pressor_count=0,
        ),
    )
    assert at_forty["viability_index_snapshot"] == 40
    case = read_case(env, bundle.case_id)
    assert case["physiologic_status"] == "STABILIZING"
    assert case["case_posture"] == "OPEN"

    env.set_clock("2026-09-04T11:00:00Z")
    below_the_floor = chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-09-04T11:00:00Z",
            map_mmhg=55,
            pao2_fio2_ratio=150,
            sodium=130,
            urine_output_ml_per_kg_hr=0.6,
            pressor_count=0,
        ),
    )
    assert below_the_floor["viability_index_snapshot"] == 35

    case = read_case(env, bundle.case_id)
    assert case["viability_index"] == 35
    assert case["physiologic_status"] == "DECOMPENSATING"
    assert case["case_posture"] == "RESTRICTED"
    assert case["observation_count"] == 3
    assert case["dmg_bundle_met_count"] == 0


def test_late_filed_observation_does_not_replace_the_latest_index(env):
    """A back-dated row is counted but never becomes the case's index.

    PRD 3.4: "The case always takes the index of its **latest** observation,
    where latest means the greatest `recorded_at`, breaking a tie by the greatest
    `created_at`."
    PRD 3.4: "The `recorded_at` instant must not be after the logical clock,
    otherwise `ERR_OBSERVATION_IN_FUTURE`."
    PRD 3.4: "and `observation_count` to the total number of its observations;
    both aggregate over **all** observations of the case, not merely the latest."

    Design: Corner/calculations/late_filed_observation_does_not_replace_the_latest_index
    """
    bundle = converted_case(env, CASE_CLOCK, patient_mrn="MRN-4201")

    env.set_clock(CHART_CLOCK)
    latest = chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            CHART_CLOCK,
            map_mmhg=65,
            pao2_fio2_ratio=300,
            sodium=130,
            urine_output_ml_per_kg_hr=0.4,
            pressor_count=0,
        ),
    )
    assert latest["viability_index_snapshot"] == 70

    env.set_clock("2026-09-04T10:30:00Z")
    back_dated = validate_success(
        env.api.create_observation(
            bundle.case_id,
            observation_payload(
                "2026-09-04T09:15:00Z",
                map_mmhg=55,
                pao2_fio2_ratio=150,
                sodium=130,
                urine_output_ml_per_kg_hr=0.6,
                pressor_count=0,
            ),
            env.donor,
        ),
        201,
    )
    assert back_dated["viability_index_snapshot"] == 35

    case = read_case(env, bundle.case_id)
    assert case["viability_index"] == 70
    assert case["physiologic_status"] == "OPTIMIZED"
    assert case["case_posture"] == "OPEN"
    assert case["observation_count"] == 2


# ---------------------------------------------------------------------------
# The hospital's lifetime timeliness posture
# ---------------------------------------------------------------------------
def test_lifetime_counters_count_every_referral_regardless_of_ventilation_or_outcome(
    env,
):
    """Non-ventilated and ruled-out referrals both stay in the denominator.

    PRD 3.1: "This lifetime denominator counts **every** referral the hospital
    has ever placed — ventilated or not, ruled out or not — and its numerator
    uses each referral's stored flag."
    PRD 3.1: "it is `TIMELY` when `referral_lag_minutes` is less than or equal to
    the hospital's `timely_referral_window_minutes`, with equality counting as
    timely, and `UNTIMELY` otherwise."
    PRD 3.1: "otherwise becomes one hundred multiplied by
    `timely_referral_count`, divided by `referral_count`, rounded half up to two
    decimal places"
    PRD 3.1: "if `referral_count` is below four the sample is too small to judge
    and the posture is `GOOD_STANDING` regardless of rate"

    Design: Corner/calculations/lifetime_counters_count_every_referral_regardless_of_ventilation_or_outcome
    """
    env.set_clock(INTAKE_CLOCK)
    hospital = create_hospital(env, timely_referral_window_minutes=60)

    ventilated = create_referral(
        env,
        hospital["id"],
        "2026-09-04T07:30:00Z",
        patient_mrn="MRN-4301",
        age_years=40,
    )
    assert ventilated["timeliness_flag"] == TIMELINESS_TIMELY

    not_ventilated = create_referral(
        env,
        hospital["id"],
        "2026-09-04T06:30:00Z",
        patient_mrn="MRN-4302",
        age_years=55,
        ventilated=False,
        gcs_score=8,
        cause_of_death_category="OTHER",
    )
    assert not_ventilated["referral_lag_minutes"] == 90
    assert not_ventilated["timeliness_flag"] == TIMELINESS_UNTIMELY

    ruled_out = create_referral(
        env,
        hospital["id"],
        "2026-09-04T07:45:00Z",
        patient_mrn="MRN-4303",
        age_years=82,
    )
    screening = open_screening(env, ruled_out["id"])
    submit_assessment(env, screening["id"], screening["version"])
    rule_screening(
        env, screening["id"], "RULED_OUT", ruled_out_reason="AGE_CRITERIA"
    )
    assert read_referral(env, ruled_out["id"])["status"] == "RULED_OUT"

    standing = read_hospital(env, hospital["id"])
    assert standing["referral_count"] == 3
    assert standing["timely_referral_count"] == 2
    assert standing["untimely_referral_count"] == 1
    assert_two_decimal_value(standing["timely_referral_rate"], 66.67)
    assert standing["partner_posture"] == PARTNER_POSTURE_GOOD_STANDING


def test_partner_posture_demotes_when_the_lifetime_rate_crosses_seventy_five(env):
    """Exactly 75.00 stays in good standing; exactly 60.00 lands on watch.

    PRD 3.1: "otherwise, a rate of at least 75.00 gives `GOOD_STANDING`, a rate
    of at least 60.00 gives `WATCH`, and anything lower gives `PROBATION`."
    PRD 3.1: "Its `timely_referral_count` increases by one when the new
    referral's `timeliness_flag` is `TIMELY`, and its `untimely_referral_count`
    increases by one when the flag is `UNTIMELY`."
    PRD 3.1: "For each basis, the lag is the number of whole minutes from the
    basis instant to `referred_at`, taking the difference in seconds, dividing by
    sixty and discarding the fraction downward."

    Design: Corner/calculations/partner_posture_demotes_when_the_lifetime_rate_crosses_seventy_five
    """
    env.set_clock(INTAKE_CLOCK)
    hospital = create_hospital(env, timely_referral_window_minutes=60)

    for mrn, trigger_at in (
        ("MRN-4401", "2026-09-04T07:30:00Z"),
        ("MRN-4402", "2026-09-04T07:45:00Z"),
        ("MRN-4403", "2026-09-04T07:40:00Z"),
        ("MRN-4404", "2026-09-04T06:00:00Z"),
    ):
        create_referral(env, hospital["id"], trigger_at, patient_mrn=mrn)

    at_four = read_hospital(env, hospital["id"])
    assert at_four["referral_count"] == 4
    assert_two_decimal_value(at_four["timely_referral_rate"], 75.00)
    assert at_four["partner_posture"] == PARTNER_POSTURE_GOOD_STANDING

    fifth = create_referral(
        env,
        hospital["id"],
        "2026-09-04T05:00:00Z",
        patient_mrn="MRN-4405",
        age_years=44,
    )
    assert fifth["referral_lag_minutes"] == 180
    assert fifth["timeliness_flag"] == TIMELINESS_UNTIMELY

    at_five = read_hospital(env, hospital["id"])
    assert at_five["referral_count"] == 5
    assert at_five["timely_referral_count"] == 3
    assert_two_decimal_value(at_five["timely_referral_rate"], 60.00)
    assert at_five["partner_posture"] == PARTNER_POSTURE_WATCH


# ---------------------------------------------------------------------------
# Documentation completeness over a set of filed types
# ---------------------------------------------------------------------------
def test_duplicate_document_upload_is_idempotent_and_witness_name_completes_the_packet(
    env,
):
    """The same type twice leaves one entry; the attestation and its name complete it.

    PRD 3.3: "The type is added to `document_types_present`, which is a set of
    distinct types — uploading the same type twice is idempotent — and
    `witness_name` is stored when supplied."
    PRD 3.3: "on the `LEGAL_NEXT_OF_KIN` basis, it is true exactly when both
    `SIGNED_CONSENT_FORM` and `WITNESS_ATTESTATION` appear in
    `document_types_present` **and** `witness_name` is non-null"
    PRD 3.3: "its `required_document_types` becomes the two-member list
    containing `SIGNED_CONSENT_FORM` and `WITNESS_ATTESTATION`, and
    `documentation_complete` becomes false"
    PRD 3.3: "A `CONSENT` moves the packet `NOK_REQUIRED → NOK_CONSENTED`, sets
    `consenting_rank` to the consenting relative's rank, and records the acting
    specialist in `consent_recorded_by_user_id`."
    PRD 3.3: "an upload onto a packet already in `NOK_CONSENTED` leaves the
    status unchanged"

    Design: Corner/calculations/duplicate_document_upload_is_idempotent_and_witness_name_completes_the_packet
    """
    bundle = cleared_referral(env, INTAKE_CLOCK, patient_mrn="MRN-4501")
    packet = open_nok_authorization(env, bundle.referral_id)
    assert packet["documentation_complete"] is False
    assert packet["required_document_types"] == [
        "SIGNED_CONSENT_FORM",
        "WITNESS_ATTESTATION",
    ]

    contact = record_nok_contact(env, packet["id"], "SPOUSE", "CONSENT")
    assert contact["rank"] == 1
    consented = read_authorization(env, packet["id"])
    assert consented["status"] == "NOK_CONSENTED"
    assert consented["consenting_rank"] == 1

    first_upload = upload_document(env, packet["id"], "SIGNED_CONSENT_FORM")
    assert first_upload["document_types_present"] == ["SIGNED_CONSENT_FORM"]
    assert first_upload["documentation_complete"] is False

    repeat_upload = upload_document(env, packet["id"], "SIGNED_CONSENT_FORM")
    assert repeat_upload["document_types_present"] == ["SIGNED_CONSENT_FORM"]
    assert repeat_upload["documentation_complete"] is False

    attested = upload_document(
        env, packet["id"], "WITNESS_ATTESTATION", witness_name="R. Alvarez"
    )
    assert sorted(attested["document_types_present"]) == [
        "SIGNED_CONSENT_FORM",
        "WITNESS_ATTESTATION",
    ]
    assert attested["witness_name"] == "R. Alvarez"
    assert attested["documentation_complete"] is True
    assert attested["status"] == "NOK_CONSENTED"

    assert len(list_nok_contacts(env, packet["id"])) == 1
