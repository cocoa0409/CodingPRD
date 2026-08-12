"""Credentialing pipeline: resubmission loop, segregation of duties and its
ordering against the state precondition, dependency gating at filing, and the
credential critical path as the start-date gate at offer execution."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_physician, create_case, create_offer, extend_offer, accept_offer,
    get_case, get_credential_item,
    create_credential_item, approve_credential_item,
)

RECRUITER = TEST_USERS["recruiter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
DIRECTOR = TEST_USERS["onboarding_director_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]      # X-User-ID cs-1
CS2 = TEST_USERS["credentialing_specialist_2_headers"]    # X-User-ID cs-2


def test_credential_item_resubmit_loop_after_reject(api):
    """PRD §3.3: "A `REJECTED` item can re-enter the pipeline through document submission, which is the resubmission loop `REJECTED` → `DOCS_SUBMITTED`."
    PRD §3.3: "A successful verify records the caller as `verified_by_user_id` and moves the item to `VERIFIED`."

    Design: Corner/state_machines/credential_item_resubmit_loop_after_reject
    """
    physician = create_physician(full_name="Dr. Jay", specialty="CARDIOLOGY")
    case = create_case(physician["id"])
    item = create_credential_item(case["id"], "STATE_LICENSE")
    validate_success(api.submit_credential_docs(item["id"], {}, CS1), 200)
    validate_success(api.reject_credential_item(item["id"], {"reason": "blurry"}, DIRECTOR), 200)

    data = validate_success(
        api.submit_credential_docs(item["id"], {"document_ref": "doc-lic-v2"}, CS1), 200
    )
    assert data["status"] == "DOCS_SUBMITTED", "REJECTED must loop back to DOCS_SUBMITTED"
    assert data["submitted_by_user_id"] == "cs-1"

    data = validate_success(api.verify_credential_item(item["id"], {}, CS2), 200)
    assert data["status"] == "VERIFIED"
    validate_success(api.file_credential_item(item["id"], {}, CS1), 200)
    data = validate_success(api.approve_credential_item(item["id"], DIRECTOR), 200)
    assert data["status"] == "APPROVED"


def test_segregation_of_duties_same_user_verify(api):
    """PRD §3.3: "Immediately after the state check, segregation of duties is enforced: the verifier's `X-User-ID` must differ from the item's `submitted_by_user_id`, else the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/validations/segregation_of_duties_same_user_verify
    """
    physician = create_physician(full_name="Dr. Uma", specialty="CARDIOLOGY")
    case = create_case(physician["id"])
    item = create_credential_item(case["id"], "STATE_LICENSE")
    validate_success(api.submit_credential_docs(item["id"], {}, CS1), 200)

    resp = api.verify_credential_item(item["id"], {}, CS1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_credential_item(item["id"])["status"] == "DOCS_SUBMITTED"

    data = validate_success(api.verify_credential_item(item["id"], {}, CS2), 200)
    assert data["status"] == "VERIFIED"
    assert data["verified_by_user_id"] == "cs-2"


def test_verify_state_beats_segregation_priority_error_id(api):
    """PRD §2.9: "On that operation the state precondition is evaluated first, so an item that was never submitted surfaces `ERR_ITEM_NOT_SUBMITTED` rather than the segregation error."

    Design: Difficulty/priority_pair_validation_conflict/verify_state_beats_segregation_priority
    """
    physician = create_physician(full_name="Dr. Kim", specialty="CARDIOLOGY")
    case = create_case(physician["id"])
    item = create_credential_item(case["id"], "STATE_LICENSE")
    validate_success(api.submit_credential_docs(item["id"], {}, CS1), 200)
    validate_success(api.reject_credential_item(item["id"], {"reason": "blurry scan"}, DIRECTOR), 200)

    # The caller IS the recorded submitter, but the item is REJECTED (not
    # DOCS_SUBMITTED): both rules fail and the state error must win.
    resp = api.verify_credential_item(item["id"], {}, CS1)
    error_data = validate_error(resp, ApiErrorId.ERR_ITEM_NOT_SUBMITTED)
    assert resp.status_code == 409
    assert error_data["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES


def test_verify_state_beats_segregation_priority_no_mutation(api):
    """PRD §2.9: "On that operation the state precondition is evaluated first, so an item that was never submitted surfaces `ERR_ITEM_NOT_SUBMITTED` rather than the segregation error."
    PRD §3.3: "A successful verify records the caller as `verified_by_user_id` and moves the item to `VERIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/verify_state_beats_segregation_priority
    """
    physician = create_physician(full_name="Dr. Kim", specialty="CARDIOLOGY")
    case = create_case(physician["id"])
    item = create_credential_item(case["id"], "STATE_LICENSE")
    validate_success(api.submit_credential_docs(item["id"], {}, CS1), 200)
    validate_success(api.reject_credential_item(item["id"], {"reason": "blurry scan"}, DIRECTOR), 200)

    resp = api.verify_credential_item(item["id"], {}, CS1)
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_SUBMITTED)

    item_after = get_credential_item(item["id"])
    assert item_after["status"] == "REJECTED", "a rejected verify must not transition the item"
    assert item_after.get("verified_by_user_id") is None, (
        "a rejected verify must not record a verifier"
    )


def test_file_blocked_until_dependency_approved(api):
    """PRD §3.3: "Filing, optionally carrying a `filing_ref`, requires `VERIFIED` (else `ERR_ITEM_NOT_VERIFIED`) and additionally requires every item named in `depends_on_item_ids` to be `APPROVED` (else `ERR_ITEM_DEPENDENCY_NOT_APPROVED`), moving the item to `FILED`."

    Design: Corner/validations/file_blocked_until_dependency_approved
    """
    physician = create_physician(full_name="Dr. Vic", specialty="CARDIOLOGY")
    case = create_case(physician["id"])
    lic = create_credential_item(case["id"], "STATE_LICENSE")
    dea = create_credential_item(
        case["id"], "DEA_REGISTRATION", depends_on_item_ids=[lic["id"]]
    )
    validate_success(api.submit_credential_docs(dea["id"], {}, CS1), 200)
    validate_success(api.verify_credential_item(dea["id"], {}, CS2), 200)

    resp = api.file_credential_item(dea["id"], {}, CS1)
    validate_error(resp, ApiErrorId.ERR_ITEM_DEPENDENCY_NOT_APPROVED)

    approve_credential_item(lic["id"])
    data = validate_success(api.file_credential_item(dea["id"], {}, CS1), 200)
    assert data["status"] == "FILED", "approving the dependency must unlock the identical file call"


def test_critical_path_eta_boundary_date(api):
    """PRD §3.3: "The critical path length is the greatest total of remaining days accumulated along any dependency chain following `depends_on_item_ids`, considering every item of the case regardless of status."
    PRD §3.3: "The earliest legal start date is the current logical date plus the critical path length plus the fixed fourteen-day buffer"
    PRD §3.2: "the `proposed_start_date` must clear the credential critical path: it may not be earlier than the current logical date plus the critical path's remaining days plus the fixed fourteen-day start-date buffer computed in §3.3, or execution fails with `ERR_START_DATE_BEFORE_CREDENTIAL_ETA` (HTTP 422)."

    The chain STATE_LICENSE (90) -> DEA_REGISTRATION (45) -> PAYER_ENROLLMENT_COMMERCIAL (75)
    yields critical path 210; from the clock default 2026-05-01 the earliest legal start is
    2026-12-11 (210 + 14 days), so 2026-12-10 fails and exactly 2026-12-11 executes.

    Design: Corner/calculations/critical_path_eta_boundary_date
    """
    physician = create_physician(full_name="Dr. Pia")
    case = create_case(physician["id"])
    offer_a = create_offer(case, proposed_start_date="2026-12-10")
    offer_a = extend_offer(offer_a["id"])
    offer_a = accept_offer(offer_a["id"], physician["id"])

    lic = create_credential_item(case["id"], "STATE_LICENSE")
    dea = create_credential_item(case["id"], "DEA_REGISTRATION", depends_on_item_ids=[lic["id"]])
    create_credential_item(
        case["id"], "PAYER_ENROLLMENT_COMMERCIAL",
        payer_code="AETNA", depends_on_item_ids=[dea["id"]],
    )

    resp = api.execute_offer(offer_a["id"], CONTRACT_ADMIN)
    validate_error(resp, ApiErrorId.ERR_START_DATE_BEFORE_CREDENTIAL_ETA)
    assert get_success_data(api.get_offer(offer_a["id"], RECRUITER))["status"] == "ACCEPTED", (
        "a rejected execute must leave the offer ACCEPTED"
    )

    validate_success(api.withdraw_offer(offer_a["id"], {}, RECRUITER), 200)

    offer_b = create_offer(case, proposed_start_date="2026-12-11")
    offer_b = extend_offer(offer_b["id"])
    offer_b = accept_offer(offer_b["id"], physician["id"])
    data = validate_success(api.execute_offer(offer_b["id"], CONTRACT_ADMIN), 200)
    assert data["status"] == "EXECUTED", "the exact boundary date must clear the gate (>=)"
    assert get_case(case["id"])["actual_start_date"] == "2026-12-11"
