"""Authentication, role authorization, arm-code masking, and segregation of
duties (PRD §2.1, §2.6, §2.8, §4)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    build_user_headers, NON_EXISTENT_UUID, ApiErrorId,
    create_study, create_site, create_staff_member, create_fee_schedule,
    setup_pharmacy, setup_randomized_subject, setup_dispensed_subject,
    setup_returned_kit, setup_returned_kit_for_destruction, upload_slots, slot_spec,
    register_subject, randomize_subject, dispense_kit, record_return,
    create_unblinding_payload, create_temperature_log_payload,
    create_subject_payload, create_dispensing_payload,
    create_destruction_payload, get_kit,
)
from test_helpers import TEST_USERS, make_pharmacist_headers, make_unblinded_pharmacist_headers

SPONSOR = TEST_USERS["sponsor_admin_headers"]
MONITOR = TEST_USERS["monitor_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


# ---------------------------------------------------------------------------
# Corner: validations (authentication)
# ---------------------------------------------------------------------------

def test_pharmacist_role_with_unknown_staff_id_returns_unauthenticated():
    """PRD §2.1: "An `X-User-ID` that does not resolve to an existing staff
    record, or whose `is_unblinded` flag does not match the declared role, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/pharmacist_role_with_unknown_staff_id_returns_unauthenticated
    """
    study = create_study(protocol_number="P-VAL-1", phase="PHASE_I",
                       blinding_model="OPEN_LABEL", max_dose_per_visit_mg=100)
    site = create_site(study["id"])
    resp = api_client.create_temperature_log(
        create_temperature_log_payload(site["id"], 5.0, source="MANUAL"),
        make_pharmacist_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_invalid_role_beats_not_found_in_priority():
    """PRD §2.6: "the server evaluates them in a fixed priority order, and the
    earliest failing check is the one whose error is returned — later checks are
    masked by it: 1. Authentication of `X-User-ID` and `X-User-Role`
    (`ERR_UNAUTHENTICATED`). ... 4. Existence of referenced resources."
    PRD §2.1: "A request that is missing either header, or whose declared role
    is not one of these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/validations/invalid_role_beats_not_found_in_priority
    """
    resp = api_client.get_study(NON_EXISTENT_UUID,
                                build_user_headers("ghost-1", "GhostRole"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


# ---------------------------------------------------------------------------
# Corner: rbac
# ---------------------------------------------------------------------------

def test_pharmacist_cannot_approve_fee_schedule():
    """PRD §2.1: "A request whose role is not listed among an endpoint's
    authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "`POST /api/fee-schedules/{id}/approve` ... SponsorAdmin".

    Design: Corner/rbac/pharmacist_cannot_approve_fee_schedule
    """
    study = create_study(protocol_number="P-RB-1")
    site = create_site(study["id"])
    pharmacist = create_staff_member(site["id"], license_number="L-RB-1")
    fs = create_fee_schedule(study["id"])
    resp = api_client.approve_fee_schedule(
        fs["id"], {"expected_study_version": study["version"]},
        make_pharmacist_headers(pharmacist["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)
    assert get_success_data(api_client.get_fee_schedule(fs["id"], SPONSOR))["status"] == "DRAFT"


def test_monitor_cannot_register_subjects():
    """PRD §2.1: "A request whose role is not listed among an endpoint's
    authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "`POST /api/subjects` ... Pharmacist".

    Design: Corner/rbac/monitor_cannot_register_subjects
    """
    study = create_study(protocol_number="P-RB-2")
    site = create_site(study["id"])
    resp = api_client.create_subject(
        create_subject_payload(site["id"], "SUB-X"), MONITOR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)


def test_unblinded_pharmacist_cannot_dispense():
    """PRD §2.1: "A request whose role is not listed among an endpoint's
    authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "`POST /api/dispensing-records` ... Pharmacist". PRD §2.6: role
    authorization (step 2) precedes existence checks (step 4).

    Design: Corner/rbac/unblinded_pharmacist_cannot_dispense
    """
    study = create_study(protocol_number="P-RB-3")
    site = create_site(study["id"])
    unblinded = create_staff_member(site["id"], license_number="L-RB-3",
                                    full_name="U", is_unblinded=True)
    resp = api_client.create_dispensing_record(
        create_dispensing_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID, 1, 1),
        make_unblinded_pharmacist_headers(unblinded["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)


def test_arm_code_masked_for_blinded_roles_visible_to_unblinded():
    """PRD §2.8: "A randomization slot's `arm_code` — the masked treatment-arm
    code, for example TRT-A — is visible only in responses to `SponsorAdmin` and
    `UnblindedPharmacist` callers; for `Pharmacist`, `Monitor`, and
    `Investigator` callers the field is serialized as `null`."

    Design: Corner/rbac/arm_code_masked_for_blinded_roles_visible_to_unblinded
    """
    world = setup_pharmacy(protocol_number="P-RB-4", kit_numbers=(),
                           pharmacist_license="L-RB-4a",
                           unblinded_licenses=("L-RB-4b",))
    upload_slots(world["study"]["id"], world["study_version"],
                 [slot_spec(1, "K-MK", arm_code="TRT-A")])
    blinded = api_client.list_randomization_slots(
        make_pharmacist_headers(world["pharmacist"]["id"]),
        params={"study_id": world["study"]["id"]})
    blinded_data, _ = validate_paginated(blinded)
    assert blinded_data[0]["arm_code"] is None, "arm_code masked for blinded roles"
    unblinded = api_client.list_randomization_slots(
        make_unblinded_pharmacist_headers(world["unblinded"][0]["id"]),
        params={"study_id": world["study"]["id"]})
    unblinded_data, _ = validate_paginated(unblinded)
    assert unblinded_data[0]["arm_code"] == "TRT-A"


def test_return_verify_by_recorder_rejected_second_pharmacist_ok():
    """PRD §3.6: "A `Pharmacist` verifies a `RECORDED` return, and segregation
    of duties applies: if the verifier's `X-User-ID` equals the return's
    `recorded_by_staff_id`, the verification is rejected with
    `ERR_SEGREGATION_OF_DUTIES`. A successful verification stamps
    `verified_by_staff_id` and moves the return `RECORDED` → `VERIFIED`, its
    terminal state."

    Design: Corner/rbac/return_verify_by_recorder_rejected_second_pharmacist_ok
    """
    world = setup_pharmacy(protocol_number="P-RB-5", kit_numbers=("K-SD",),
                           pharmacist_license="L-RB-5a", extra_licenses=("L-RB-5b",))
    disp = setup_dispensed_subject(world, subject_number="SUB-SD", quantity=4)
    drug_return = record_return(disp["record"]["id"], 4, world["pharmacist"]["id"])
    resp = api_client.verify_return(drug_return["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=422)
    verifier = world["staff"][1]
    verified = get_success_data(api_client.verify_return(
        drug_return["id"], make_pharmacist_headers(verifier["id"])))
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_staff_id"] == verifier["id"]


def test_destruction_attest_by_creator_rejected_then_creator_void_restores_kit():
    """PRD §3.7: "In witness mode (`void` absent or false), the caller must be
    the designated witness — an `X-User-ID` other than the record's
    `witness_staff_id` is rejected with `ERR_UNAUTHORIZED_ROLE` — and must not
    be the creator, since an `X-User-ID` equal to `created_by_staff_id` is
    rejected with `ERR_SEGREGATION_OF_DUTIES`; success moves the record `DRAFT`
    → `WITNESSED`. In void mode (`void` true), only the creator may abandon a
    draft — any other caller is rejected with `ERR_UNAUTHORIZED_ROLE` — and
    voiding moves the record `DRAFT` → `VOIDED` and restores the kit from
    `DESTRUCTION_PENDING` back to its `kit_prior_status`."

    Design: Corner/rbac/destruction_attest_by_creator_rejected_then_creator_void_restores_kit
    """
    world = setup_pharmacy(protocol_number="P-RB-6", kit_numbers=("K-WT",),
                           pharmacist_license="L-RB-6")
    returned = setup_returned_kit(world, subject_number="SUB-WT", quantity=4)
    creator = world["pharmacist"]
    # The creator is also named as the designated witness.
    record = get_success_data(api_client.create_destruction_record(
        create_destruction_payload(returned["kit"]["id"], world["site"]["id"],
                                   creator["id"], quantity_destroyed=10),
        world["pharmacist_headers"]))
    resp = api_client.attest_destruction_record(record["id"], {}, world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=422)
    voided = get_success_data(api_client.attest_destruction_record(
        record["id"], {"void": True}, world["pharmacist_headers"]))
    assert voided["status"] == "VOIDED"
    assert get_kit(returned["kit"]["id"])["status"] == "RETURNED", (
        "the void restores the kit to its kit_prior_status"
    )


def test_unblinding_execute_by_decider_rejected():
    """PRD §3.8: "An `UnblindedPharmacist` executes an `APPROVED` request, but
    the approver may not also execute: an `X-User-ID` equal to
    `decided_by_staff_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`, so
    requester, decider, and executor are three distinct actors." and "when one
    hundred times `unblinded_subject_count` is greater than or equal to
    `unblinding_suspension_threshold_pct` multiplied by
    `randomized_subject_count` ... the study suspends itself from `ACTIVE` to
    `SUSPENDED`, cascading every `ACTIVE` site to `ON_HOLD` (§3.1)."

    Design: Corner/rbac/unblinding_execute_by_decider_rejected
    """
    world = setup_pharmacy(protocol_number="P-RB-7", kit_numbers=("K-UE",),
                           pharmacist_license="L-RB-7a",
                           unblinded_licenses=("L-RB-7b", "L-RB-7c"),
                           study_overrides={"unblinding_suspension_threshold_pct": 99})
    result = setup_randomized_subject(world, subject_number="SUB-UE",
                                      slot_kit_numbers=["K-UE"])
    ub = get_success_data(api_client.create_unblinding_request(
        create_unblinding_payload(result["subject"]["id"], reason="SAE"), INVESTIGATOR))
    decider, executor = world["unblinded"][0], world["unblinded"][1]
    get_success_data(api_client.decide_unblinding_request(
        ub["id"], {"decision": "APPROVED"}, make_unblinded_pharmacist_headers(decider["id"])))
    resp = api_client.execute_unblinding_request(
        ub["id"], make_unblinded_pharmacist_headers(decider["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=422)
    executed = get_success_data(api_client.execute_unblinding_request(
        ub["id"], make_unblinded_pharmacist_headers(executor["id"])))
    assert executed["status"] == "EXECUTED"
    # The slot list uploaded by setup_randomized_subject arms K-UE with TRT-A;
    # §3.8 copies the ASSIGNED slot's arm_code into revealed_arm_code.
    assert executed["revealed_arm_code"] == "TRT-A"
    # 1 unblinded of 1 randomized: 100 >= 99 — the integrity rule fires.
    study = get_success_data(api_client.get_study(world["study"]["id"], SPONSOR))
    assert study["status"] == "SUSPENDED"


def test_pharmacist_role_with_unblinded_staff_id_returns_unauthenticated():
    """PRD §2.1: "When `X-User-Role` is `Pharmacist`, `X-User-ID` is the `id`
    of the acting `PharmacyStaff` record, and that staff record's `is_unblinded`
    flag must be `false`." and "An `X-User-ID` that does not resolve to an
    existing staff record, or whose `is_unblinded` flag does not match the
    declared role, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/pharmacist_role_with_unblinded_staff_id_returns_unauthenticated
    """
    study = create_study(protocol_number="P-RB-8")
    site = create_site(study["id"])
    unblinded = create_staff_member(site["id"], license_number="L-RB-8",
                                    full_name="U", is_unblinded=True)
    resp = api_client.create_temperature_log(
        create_temperature_log_payload(site["id"], 5.0, source="MANUAL"),
        make_pharmacist_headers(unblinded["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
