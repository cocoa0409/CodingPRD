"""Discharge pricing arithmetic and the interrupted-stay linkage rules."""

from test_helpers import (
    OFFICER_HEADERS,
    ApiErrorId,
    admit,
    admit_admission_payload,
    api_client,
    assert_admission_dimensions,
    assert_payment,
    create_concurred_screening,
    discharge,
    open_admission,
    read_admission,
    read_facility,
    register_patient,
    rescind_interruption_payload,
    set_clock,
    setup_admitted_cohort,
    setup_facility_with_staff,
    setup_interruption_chain,
    setup_stay,
    validate_error,
    validate_success,
)

TIER_A_PATIENT = {"impairment_group_code": "0704", "comorbidity_tier": "NONE"}
SECOND_PATIENT_NAME = {"impairment_group_code": "0704",
                       "comorbidity_tier": "NONE",
                       "full_name": "Bo Whitaker"}


def test_short_stay_factor_binds_at_three_days_and_releases_at_four():
    """A three-day tier A stay is paid 630000 cents; a four-day one is paid 1800000.

    PRD §3.8: "Each payment tier has a base amount in cents: `TIER_A` is 1800000
    cents, `TIER_B` is 2450000 cents, and `TIER_C` is 3120000 cents."

    PRD §3.8: "When `effective_los_days` is at most 3, the uplifted base is
    multiplied by a short-stay factor of 0.35; when it is 4 days or more the
    factor is 1.00."

    Design: Corner/calculations/short_stay_factor_applies_at_three_days_and_stops_at_four
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stays = setup_admitted_cohort(
        env,
        [{"mrn": "MRN-A", "patient_overrides": TIER_A_PATIENT},
         {"mrn": "MRN-B", "patient_overrides": SECOND_PATIENT_NAME}],
        admitted_at="2026-08-04T12:00:00Z",
    )

    short_stay = discharge(env, stays[0]["admission"]["id"],
                           "2026-08-06T12:00:00Z")
    ordinary_stay = discharge(env, stays[1]["admission"]["id"],
                              "2026-08-07T12:00:00Z")

    assert_payment(short_stay, effective_los_days=3,
                   total_payment_cents=630000, payment_status="PRICED")
    assert_payment(ordinary_stay, effective_los_days=4,
                   total_payment_cents=1800000, payment_status="PRICED")
    assert read_facility(env["facility_id"])["settled_payment_cents"] == 2430000


def test_transfer_per_diem_rounds_half_up_and_stays_under_the_adjusted_base():
    """Tier B per-diem 204167 cents times 5.5 rounds 1122918.5 up to 1122919.

    PRD §3.8: "Each tier also carries an average length of stay: 9 days for
    `TIER_A`, 12 days for `TIER_B`, and 15 days for `TIER_C`."

    PRD §3.8: "When it applies, a per-diem amount is the adjusted base divided by
    the tier's average length of stay, rounded half up to whole cents; the
    transfer amount is that per-diem multiplied by the effective length of stay
    plus one half, again rounded half up to whole cents; and the gross amount is
    the smaller of the adjusted base and that transfer amount."

    Design: Corner/calculations/transfer_per_diem_rounds_half_up_then_caps_at_adjusted_base
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stay = setup_stay(env, patient_overrides={"comorbidity_tier": "NONE"},
                      admitted_at="2026-08-04T12:00:00Z")
    assert read_admission(stay["admission"]["id"])["cmg_tier"] == "TIER_B"

    discharged = discharge(env, stay["admission"]["id"], "2026-08-08T12:00:00Z",
                           discharge_destination="SNF")

    assert_payment(discharged, effective_los_days=5,
                   total_payment_cents=1122919, payment_status="PRICED")
    assert discharged["total_payment_cents"] < 2450000
    assert read_facility(env["facility_id"])["settled_payment_cents"] == 1122919


def test_discharge_response_already_carries_price_and_verdict():
    """The pricing waterfall and the compliance ladder both land in this response.

    PRD §2.11: "These chains run to completion within the request that triggered
    them: a client that reads the facility immediately after a discharge sees the
    new posture, not a stale one."

    Design: Corner/consistency model/discharge_response_carries_pricing_and_compliance_class_immediately
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stay = setup_stay(env, patient_overrides={"comorbidity_tier": "NONE"},
                      admitted_at="2026-08-04T12:00:00Z")

    set_clock("2026-08-08T12:00:00Z")
    response = api_client.discharge_admission(
        stay["admission"]["id"],
        {"discharged_at": "2026-08-08T12:00:00Z",
         "discharge_destination": "COMMUNITY",
         "discharge_planned": True},
        env["nurse_headers"],
    )

    discharged = validate_success(response, expected_status=200)
    assert_admission_dimensions(discharged, stay_status="DISCHARGED",
                                payment_status="PRICED",
                                compliance_class="NON_QUALIFYING")
    assert discharged["effective_los_days"] == 5
    assert discharged["total_payment_cents"] == 2450000
    facility = read_facility(env["facility_id"])
    assert facility["settled_payment_cents"] == 2450000
    assert facility["cohort_total_count"] == 1
    assert facility["posture"] == "OPEN"


def test_rescinding_an_interruption_on_a_standalone_stay_is_rejected():
    """There is nothing to unlink, because this stay continues nothing.

    PRD §3.4: "Rescinding an interruption requires the admission to carry
    `interrupted_stay_flag` true — otherwise `ERR_NOT_INTERRUPTED_STAY` — and
    requires that continuation to still be `ADMITTED`; a continuation that has
    already been discharged may not be unlinked, and the attempt is refused with
    `ERR_INVALID_STATE`."

    Design: Corner/validations/rescind_interruption_on_standalone_admission_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stay = setup_stay(env, admitted_at="2026-08-04T12:00:00Z")
    assert stay["admission"]["interrupted_stay_flag"] is False

    response = api_client.rescind_interruption(
        stay["admission"]["id"], rescind_interruption_payload(), OFFICER_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_NOT_INTERRUPTED_STAY)
    unchanged = read_admission(stay["admission"]["id"])
    assert unchanged["interrupted_stay_flag"] is False
    assert unchanged["interruption_gap_days"] is None


def test_continuation_admitted_four_days_after_discharge_is_rejected():
    """Three whole days is the outer edge of the window and this gap is four.

    PRD §3.4: "the gap — the number of whole calendar days from the predecessor's
    discharge date to this admission's admit date — must be at least 0 and at most
    3; a predecessor that is not discharged or a gap beyond three days is
    `ERR_INTERRUPTION_WINDOW_EXCEEDED`."

    Design: Corner/validations/continuation_admitted_four_days_after_discharge_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    chain = setup_interruption_chain(
        env, head_discharged_at="2026-08-10T12:00:00Z",
        continuation_screened_at="2026-08-13T09:00:00Z",
        continuation_admitted_at="2026-08-14T12:00:00Z",
        attach=False,
    )
    set_clock("2026-08-14T12:00:00Z")

    response = api_client.admit_admission(
        chain["continuation"]["id"],
        admit_admission_payload("2026-08-14T12:00:00Z"),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INTERRUPTION_WINDOW_EXCEEDED)
    unchanged = read_admission(chain["continuation"]["id"])
    assert unchanged["stay_status"] == "PENDING"
    assert unchanged["interrupted_stay_flag"] is False
    assert read_admission(chain["head"]["id"])["payment_status"] == "PRICED"


def test_readmission_two_days_later_without_naming_the_predecessor_is_rejected():
    """The silence is the error: a recent discharge must be linked explicitly.

    PRD §3.4: "Conversely, if the admit request names no predecessor at all but
    the same patient has a `DISCHARGED` admission whose discharge date falls
    within the three calendar days before this admission's admit date, the
    omission is itself an error: `ERR_INTERRUPTED_STAY_LINK_REQUIRED`."

    Design: Corner/validations/readmission_within_three_days_without_predecessor_link_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    patient = register_patient(env)
    head_screening = create_concurred_screening(env, patient["id"])
    head = open_admission(env, patient["id"], head_screening["id"])
    admit(env, head["id"], "2026-08-04T12:00:00Z")
    discharge(env, head["id"], "2026-08-10T12:00:00Z")
    set_clock("2026-08-11T09:00:00Z")
    readmission_screening = create_concurred_screening(
        env, patient["id"], expected_admission_at="2026-08-12T12:00:00Z"
    )
    readmission = open_admission(env, patient["id"], readmission_screening["id"])
    set_clock("2026-08-12T12:00:00Z")

    response = api_client.admit_admission(
        readmission["id"], admit_admission_payload("2026-08-12T12:00:00Z"),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INTERRUPTED_STAY_LINK_REQUIRED)
    assert read_admission(readmission["id"])["stay_status"] == "PENDING"


def test_second_continuation_naming_an_already_continued_predecessor_is_rejected():
    """The head stay has one continuation already and cannot take another.

    PRD §3.4: "That predecessor must also not already be named by some other
    admission, or the attach fails with `ERR_PREDECESSOR_ALREADY_CONTINUED`."

    Design: Corner/validations/second_continuation_of_same_predecessor_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    chain = setup_interruption_chain(env)
    assert chain["continuation_admission"]["interrupted_stay_flag"] is True

    set_clock("2026-08-13T09:00:00Z")
    rival_screening = create_concurred_screening(
        env, chain["patient"]["id"], expected_admission_at="2026-08-13T12:00:00Z"
    )
    rival = open_admission(env, chain["patient"]["id"], rival_screening["id"],
                           predecessor_admission_id=chain["head"]["id"])
    set_clock("2026-08-13T12:00:00Z")

    response = api_client.admit_admission(
        rival["id"], admit_admission_payload("2026-08-13T12:00:00Z"),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_PREDECESSOR_ALREADY_CONTINUED)
    assert read_admission(rival["id"])["stay_status"] == "PENDING"
    assert read_admission(chain["continuation"]["id"])["interrupted_stay_flag"] is True
