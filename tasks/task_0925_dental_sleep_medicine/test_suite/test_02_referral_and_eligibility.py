"""Referral creation, the medical-necessity fork, the dentist's answer and expiry."""

from test_helpers import (
    ApiErrorId,
    approx_index,
    assert_calendar_date,
    assert_referral,
    build_scenario,
    create_lab_order_payload,
    create_prior_auth_payload,
    create_referral_payload,
    make_sleep_physician_headers,
    order_and_result_study,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_same_provider_in_both_referral_slots_is_a_self_referral(api):
    """PRD §2.6 rung 14: "On referral creation, `treating_dentist_id` must differ from
    `referring_physician_id`."
    PRD §2.6: "Rung 14 sits above rung 15 because no single provider can be both a
    `SLEEP_PHYSICIAN` and a `DENTIST`: were suitability evaluated first, a referral naming the
    same provider in both slots would always answer `ERR_PROVIDER_TYPE_MISMATCH` and
    `ERR_SELF_REFERRAL` would be unreachable on referral creation."

    Design: Corner/validations/same_provider_in_both_referral_slots_is_self_referral
    """
    scenario = build_scenario("diagnosed")
    acting = make_sleep_physician_headers(scenario["dent_id"])
    error = validate_error(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["dent_id"], scenario["dent_id"],
                scenario["study_id"],
            ),
            acting,
        ),
        ApiErrorId.ERR_SELF_REFERRAL.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_PROVIDER_TYPE_MISMATCH.value
    rows, _meta = validate_paginated(
        api.list_referrals(scenario["coord_headers"], {"patient_id": scenario["pat_id"]})
    )
    assert rows == [], "the refused referral must not have been written"


def test_wrong_slot_type_and_suspended_provider_share_one_identifier(api):
    """PRD §2.6 rung 15: "`referring_physician_id` and `ordering_physician_id` must name a
    provider whose `provider_type` is `SLEEP_PHYSICIAN`; `treating_dentist_id` and
    `performed_by_dentist_id` must name a `DENTIST`; `lab_provider_id` must name a `DENTAL_LAB`.
    In all five slots the named provider's `status` must also be `ACTIVE` — a `SUSPENDED`
    provider is refused with this same identifier. A violation is `ERR_PROVIDER_TYPE_MISMATCH`
    (422)."

    Design: Corner/validations/wrong_provider_type_and_suspended_provider_both_route_to_type_mismatch
    """
    scenario = build_scenario("diagnosed", suspended_dentist=True)
    for wrong_dentist in (scenario["lab_id"], scenario["dent_susp_id"]):
        validate_error(
            api.create_referral(
                create_referral_payload(
                    scenario["pat_id"], scenario["phys_id"], wrong_dentist,
                    scenario["study_id"], cpap_history="REFUSAL", cpap_nights_used=0,
                ),
                scenario["phys_headers"],
            ),
            ApiErrorId.ERR_PROVIDER_TYPE_MISMATCH.value,
        )
    suspended = validate_success(
        api.get_provider(scenario["dent_susp_id"], scenario["admin_headers"])
    )
    assert suspended["status"] == "SUSPENDED"


def test_severe_band_without_documented_pressure_history_is_refused(api):
    """PRD §3.3: "For a `SEVERE` band, oral appliance therapy is second-line: positive airway
    pressure must have been tried and failed, so all three of the following must hold —
    `cpap_history` is `FAILURE`, `INTOLERANCE` or `REFUSAL`; the trial was long enough, meaning
    either the history is `REFUSAL` (a patient who refuses outright never accumulates nights) or
    `cpap_nights_used` is at least 30; and the documentation is fresh, meaning
    `cpap_documented_on` is not null and the whole number of days from that date to the clock
    date is at most 730."
    PRD §3.3: "If any of the three fails, the referral is refused with
    `ERR_CPAP_TRIAL_REQUIRED`; if all three hold, `eligibility_basis` is set to
    `CPAP_INTOLERANT_SEVERE`."

    Design: Corner/validations/severe_osa_without_documented_pap_history_is_refused
    """
    scenario = build_scenario("diagnosed")
    validate_error(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["phys_id"], scenario["dent_id"],
                scenario["study_id"], cpap_history="NONE", cpap_nights_used=0,
                cpap_documented_on=None,
            ),
            scenario["phys_headers"],
        ),
        ApiErrorId.ERR_CPAP_TRIAL_REQUIRED.value,
    )
    admitted = validate_success(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["phys_id"], scenario["dent_id"],
                scenario["study_id"], cpap_history="FAILURE", cpap_nights_used=30,
                cpap_documented_on="2026-03-01",
            ),
            scenario["phys_headers"],
        ),
        201,
    )
    assert_referral(admitted)
    assert admitted["eligibility_basis"] == "CPAP_INTOLERANT_SEVERE"
    assert admitted["severity_band_at_referral"] == "SEVERE"


def test_mild_band_without_symptoms_or_pressure_history_is_refused(api):
    """PRD §3.3: "For a `MILD` band the same basis applies, but only if the patient is
    symptomatic or has some pressure history: either `epworth_score` is at least 10, or
    `cpap_history` is anything other than `NONE`."
    PRD §3.3: "A mild patient with an `epworth_score` of 9 and no pressure history is refused
    with `ERR_CPAP_TRIAL_REQUIRED`, while the identical payload under a `MODERATE` band is
    admitted without comment."

    Design: Corner/validations/mild_osa_without_symptoms_or_pap_history_is_refused
    """
    scenario = build_scenario("cast", patient_overrides={"epworth_score": 9})
    study = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 60,
                 "recording_minutes": 480, "artifact_pct": 0},
    )
    assert study["severity_index"] == approx_index(7.5)
    assert study["severity_band"] == "MILD"

    validate_error(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["phys_id"], scenario["dent_id"], study["id"],
                cpap_history="NONE", cpap_nights_used=0, cpap_documented_on=None,
            ),
            scenario["phys_headers"],
        ),
        ApiErrorId.ERR_CPAP_TRIAL_REQUIRED.value,
    )
    admitted = validate_success(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["phys_id"], scenario["dent_id"], study["id"],
                cpap_history="REFUSAL", cpap_nights_used=0,
                cpap_documented_on="2026-04-01",
            ),
            scenario["phys_headers"],
        ),
        201,
    )
    assert admitted["eligibility_basis"] == "FIRST_LINE_MILD_MODERATE"


def test_second_response_on_an_accepted_referral_is_an_invalid_transition(api):
    """PRD §2.6 rung 12: "First the path resource's own `status` must admit the transition being
    requested; then the governing parent's status must admit it."
    PRD §3.3: "Both arms are ordinary mutations: `ISSUED → ACCEPTED` and `ISSUED → DECLINED`
    each raise the referral's `version` by 1 and refresh `updated_at`."

    Design: Corner/state_machines/respond_twice_on_a_referral_returns_invalid_state
    """
    scenario = build_scenario("referral_accepted")
    validate_error(
        api.respond_to_referral(
            scenario["ref_id"], {"decision": "DECLINED"}, scenario["dent_headers"]
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["dent_headers"])
    )
    assert referral["status"] == "ACCEPTED"


def test_expired_diagnosis_is_persisted_before_the_request_is_refused(api):
    """PRD §2.6: "At rung 18, when the clock date is later than the referral's
    `diagnosis_valid_until` and the referral is in status `ISSUED` or `ACCEPTED`, three things
    happen in order. First the write: the referral's `status` is persisted as `EXPIRED` and its
    `version` rises by 1, and — on the `ACCEPTED` arm — every `LabOrder` on that referral still
    in `RECORDS_CAPTURED` transitions to `CANCELLED`. Then the rejection:
    `ERR_DIAGNOSIS_EXPIRED` (422)."

    Design: Corner/validations/expired_diagnosis_is_persisted_before_the_request_is_refused
    """
    scenario = build_scenario("referral_accepted")
    lab_order = validate_success(
        api.create_lab_order(
            create_lab_order_payload(
                scenario["ref_id"], scenario["lab_id"], capture_method="PVS_IMPRESSION"
            ),
            scenario["dent_headers"],
        ),
        201,
    )
    set_clock("2027-04-11T00:00:00Z")
    validate_error(
        api.create_prior_auth(
            create_prior_auth_payload(
                scenario["pat_id"], scenario["payer_med_id"], scenario["ref_id"]
            ),
            scenario["billing_headers"],
        ),
        ApiErrorId.ERR_DIAGNOSIS_EXPIRED.value,
    )
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["billing_headers"])
    )
    assert referral["status"] == "EXPIRED", "the expiry write survives the rejection"
    assert_calendar_date(
        referral["diagnosis_valid_until"], "2027-04-10", "Referral.diagnosis_valid_until"
    )
    cancelled = validate_success(
        api.get_lab_order(lab_order["id"], scenario["dent_headers"])
    )
    assert cancelled["status"] == "CANCELLED"
    rows, _meta = validate_paginated(
        api.list_prior_auths(scenario["billing_headers"], {"referral_id": scenario["ref_id"]})
    )
    assert rows == [], "no authorisation row may be created by the refused request"


def test_already_expired_referral_is_pre_empted_by_the_state_gate(api):
    """PRD §2.6: "And third, on any *later* call against a referral that is **already**
    `EXPIRED`, this rung is never reached at all: rung 12's state gate rejects first — a
    dentist's response requires an `ISSUED` referral, and lab-order and prior-authorisation
    creation each require an `ACCEPTED` one — so the answer becomes `ERR_INVALID_STATE` (409), no
    second write occurs, and the referral's `version` is not bumped a second time."

    Design: Corner/validations/already_expired_referral_is_pre_empted_by_the_state_gate
    """
    scenario = build_scenario("referral_accepted")
    set_clock("2027-04-11T00:00:00Z")
    first = validate_error(
        api.create_prior_auth(
            create_prior_auth_payload(
                scenario["pat_id"], scenario["payer_med_id"], scenario["ref_id"]
            ),
            scenario["billing_headers"],
        ),
        ApiErrorId.ERR_DIAGNOSIS_EXPIRED.value,
    )
    assert first["error_id"] == ApiErrorId.ERR_DIAGNOSIS_EXPIRED.value
    after_flip = validate_success(
        api.get_referral(scenario["ref_id"], scenario["billing_headers"])
    )
    assert after_flip["status"] == "EXPIRED"

    validate_error(
        api.create_prior_auth(
            create_prior_auth_payload(
                scenario["pat_id"], scenario["payer_med_id"], scenario["ref_id"]
            ),
            scenario["billing_headers"],
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    after_second = validate_success(
        api.get_referral(scenario["ref_id"], scenario["billing_headers"])
    )
    assert after_second["version"] == after_flip["version"], (
        "the pre-empted rung must not bump the referral a second time"
    )


def test_unknown_provider_referral_and_appliance_ids_keep_their_own_codes(api):
    """PRD §2.6 rung 4: "Every foreign key supplied in the request body resolves, validated in
    the order the fields are declared in the endpoint's input list, so the first unresolvable
    reference in that order is the one reported. `patient_id` gives `ERR_PATIENT_NOT_FOUND`;
    `provider_id`, `referring_physician_id`, `treating_dentist_id`, `ordering_physician_id`,
    `lab_provider_id` and `performed_by_dentist_id` give `ERR_PROVIDER_NOT_FOUND`; `referral_id`
    gives `ERR_REFERRAL_NOT_FOUND`; `appliance_id`, `replaces_appliance_id` and
    `loaner_appliance_id` give `ERR_APPLIANCE_NOT_FOUND`; and `payer_id`, `diagnostic_study_id`,
    `efficacy_study_id`, `written_order_id`, `prior_auth_id`, `lab_order_id`, `lot_id` and
    `repair_order_id` give `ERR_RECORD_NOT_FOUND`. All HTTP 404."

    Design: Corner/errors/unknown_provider_referral_and_appliance_ids_take_their_own_not_found_codes
    """
    scenario = build_scenario("referral_accepted")
    missing = "00000000-0000-4000-8000-000000000abc"

    validate_error(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["phys_id"], missing, scenario["study_id"],
                cpap_history="REFUSAL", cpap_nights_used=0,
            ),
            scenario["phys_headers"],
        ),
        ApiErrorId.ERR_PROVIDER_NOT_FOUND.value,
    )
    validate_error(
        api.create_lab_order(
            create_lab_order_payload(missing, scenario["lab_id"]),
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_REFERRAL_NOT_FOUND.value,
    )
    validate_error(
        api.get_appliance(missing, scenario["dent_headers"]),
        ApiErrorId.ERR_APPLIANCE_NOT_FOUND.value,
    )


def test_unknown_patient_id_on_a_path_is_a_patient_not_found(api):
    """PRD §2.6 rung 3: "Every id embedded in the URL resolves to a live row, validated left to
    right, so that in a multi-segment path the leftmost unresolvable id is the one reported. A
    `patient_id` gives `ERR_PATIENT_NOT_FOUND`; a `provider_id` gives `ERR_PROVIDER_NOT_FOUND`; a
    `referral_id` gives `ERR_REFERRAL_NOT_FOUND`; an `appliance_id` gives
    `ERR_APPLIANCE_NOT_FOUND`; and every other path id — `payer_id`, `study_id`,
    `written_order_id`, `prior_auth_id`, `lab_order_id`, `lot_id`, `visit_id`,
    `adherence_download_id`, `report_id`, `claim_id`, `repair_order_id` and `audit_hold_id` —
    gives `ERR_RECORD_NOT_FOUND`. All five are HTTP 404, and no other id routes to
    `ERR_RECORD_NOT_FOUND`."

    Design: Corner/entities/get_patient_with_unknown_id_returns_patient_not_found
    """
    scenario = build_scenario("cast")
    validate_error(
        api.get_patient(
            "00000000-0000-4000-8000-000000000999", scenario["coord_headers"]
        ),
        ApiErrorId.ERR_PATIENT_NOT_FOUND.value,
    )
