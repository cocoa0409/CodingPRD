"""Authentication, role authorisation, care-team scope and the global write gate."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approx_mm,
    assert_audit_hold,
    build_scenario,
    create_adherence_download_payload,
    create_referral_payload,
    no_auth_headers,
    open_audit_hold,
    register_payer,
    schedule_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_frozen_records_pre_empt_the_referral_state_gate(api):
    """PRD §2.6: "**Rung 5 is a global write gate.** When the patient in scope has at least one
    `AuditHold` in status `OPEN` — which is what `records_frozen` records — every mutating
    endpoint whose subject resolves to that patient is refused at rung 5, **pre-empting rungs 6
    through 35 entirely**. No care-team check, no field validation, no state check and no
    business rule runs; the only possible answer is `ERR_RECORDS_FROZEN` (409)."

    Design: Difficulty/priority_pair_validation_conflict/records_freeze_beats_referral_state_gate
    """
    scenario = build_scenario("referral_accepted")
    open_audit_hold(scenario)
    error = validate_error(
        api.respond_to_referral(
            scenario["ref_id"], {"decision": "ACCEPTED"}, scenario["dent_headers"]
        ),
        ApiErrorId.ERR_RECORDS_FROZEN.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value, (
        "the referral is no longer ISSUED, yet the write gate answers first"
    )


def test_audit_hold_freezes_the_patient_and_leaves_the_referral_untouched(api):
    """PRD §3.1: "Creating the hold recomputes the patient's `records_frozen` to true — which is
    itself a write to the patient row, so the patient's `version` rises by 1 and its
    `updated_at` refreshes — and from that instant every mutating endpoint whose subject resolves
    to that patient answers `ERR_RECORDS_FROZEN` and nothing else."
    PRD §3.1: "The hold's `opened_on` is stamped from the clock date and its `status` starts
    `OPEN`; `closed_on` stays null until the audit ends."

    Design: Difficulty/priority_pair_validation_conflict/records_freeze_beats_referral_state_gate
    """
    scenario = build_scenario("referral_accepted")
    hold = open_audit_hold(scenario)
    assert_audit_hold(hold)
    assert hold["status"] == "OPEN"

    validate_error(
        api.respond_to_referral(
            scenario["ref_id"], {"decision": "ACCEPTED"}, scenario["dent_headers"]
        ),
        ApiErrorId.ERR_RECORDS_FROZEN.value,
    )
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["dent_headers"])
    )
    assert referral["status"] == "ACCEPTED", "the refused write changed nothing"
    patient = validate_success(
        api.get_patient(scenario["pat_id"], scenario["coord_headers"])
    )
    assert patient["records_frozen"] is True


def test_dentist_may_not_issue_a_referral(api):
    """PRD §2.6 rung 2: "The acting role appears in the endpoint's authorised-roles list in §4 —
    otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint."
    PRD §2.1: "`SleepPhysician` is the only role permitted to order and result a sleep study, to
    refer a patient for oral appliance therapy, to write and sign a standard written order, and
    to sign off an efficacy report."

    Design: Corner/rbac/dentist_cannot_issue_a_referral
    """
    scenario = build_scenario("diagnosed")
    validate_error(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["phys_id"], scenario["dent_id"],
                scenario["study_id"],
            ),
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    rows, meta = validate_paginated(
        api.list_referrals(scenario["coord_headers"], {"patient_id": scenario["pat_id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_billing_specialist_may_not_apply_a_titration_visit(api):
    """PRD §2.6 rung 2: "The acting role appears in the endpoint's authorised-roles list in §4 —
    otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint."
    PRD §2.1: "`BillingSpecialist` files prior authorisations and medical claims, submits them
    and appeals them, and never touches clinical state."

    Design: Corner/rbac/billing_specialist_cannot_apply_a_titration_visit
    """
    scenario = build_scenario("delivered")
    visit = schedule_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    validate_error(
        api.apply_titration_visit(
            visit["id"], {"side_effect_severity": "NONE"}, scenario["billing_headers"]
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    unchanged = validate_success(
        api.get_titration_visit(visit["id"], scenario["dent_headers"])
    )
    assert unchanged["status"] == "SCHEDULED"
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(4.75)


def test_a_request_with_no_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying the actor, and
    `X-User-Role`, naming the capacity in which the actor is writing. If either header is absent,
    or if `X-User-Role` is not one of the seven role names below spelled exactly, the request is
    refused with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."

    Design: Corner/rbac/missing_header_returns_unauthenticated
    """
    payer = register_payer(prior_auth_required=False)
    validate_error(
        api.create_patient(
            {
                "mrn": "MRN-900",
                "full_name": "No Auth",
                "date_of_birth": "1980-01-01",
                "medical_payer_id": payer["id"],
            },
            no_auth_headers(),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    rows, meta = validate_paginated(
        api.list_patients(TEST_USERS["clinic_coordinator_headers"])
    )
    assert meta["total_count"] == 0 and rows == []


def test_an_unrelated_dentist_is_outside_the_care_team(api):
    """PRD §2.1: "A `Dentist` is in scope for a patient when some `Referral` names him as its
    `treating_dentist_id` in *any* status, `ISSUED` included — without that clause he could never
    answer the very referral that admits him to the care team."
    PRD §2.1: "Beyond the endpoint-level role check, an actor must belong to the care team of the
    patient whose row is being touched. This test guards *reads as well as writes* on every
    patient-scoped endpoint, and a failure is `ERR_NOT_CARE_TEAM` (HTTP 403)."

    Design: Corner/rbac/unrelated_dentist_is_not_on_the_care_team
    """
    scenario = build_scenario("referral_issued", extra_dentist=True)
    validate_error(
        api.respond_to_referral(
            scenario["ref_id"], {"decision": "ACCEPTED"}, scenario["dent2_headers"]
        ),
        ApiErrorId.ERR_NOT_CARE_TEAM.value,
    )
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["dent_headers"])
    )
    assert referral["status"] == "ISSUED"
    assert referral["treating_dentist_id"] == scenario["dent_id"]


def test_a_patient_may_not_attest_wear_on_another_patients_device(api):
    """PRD §2.1: "A `Patient` is in scope only for rows that resolve to his own `patient_id`."
    PRD §2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`,
    and ownership checks compare the resource's `patient_id` to `X-User-ID`."

    Design: Corner/rbac/patient_cannot_attest_adherence_for_another_patients_device
    """
    scenario = build_scenario("fabricated", second_patient=True)
    validate_error(
        api.create_adherence_download(
            create_adherence_download_payload(
                scenario["app_id"],
                source="PATIENT_ATTESTED",
                window_start="2026-07-08",
                window_end="2026-08-06",
                nights_recorded=30,
                nights_at_or_above_min_hours=30,
                mean_hours_per_worn_night=8.0,
            ),
            scenario["patient2_headers"],
        ),
        ApiErrorId.ERR_NOT_CARE_TEAM.value,
    )
    rows, meta = validate_paginated(
        api.list_adherence_downloads(
            scenario["dent_headers"], {"appliance_id": scenario["app_id"]}
        )
    )
    assert meta["total_count"] == 0 and rows == []
