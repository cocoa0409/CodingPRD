"""Error conditions: the precedence ladder, the 404 families and the refusals.

Each test drives a request that must be refused, checks the published error_id
and HTTP status, and then re-reads the resources involved to prove the refusal
left no partial write behind.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    build_user_headers,
    complete_inspection_payload,
    create_appeal_payload,
    create_application_payload,
    create_inspection_station_payload,
    create_license_action_payload,
    create_vehicle_payload,
    decide_recognition_request,
    decide_recognition_request_payload,
    docs_review_payload,
    file_parts_document,
    issue_title,
    license_rebuilder,
    make_fraud_investigator_headers,
    make_inspector_headers,
    make_program_admin_headers,
    make_rebuilder_headers,
    make_state_title_clerk_headers,
    open_fraud_referral,
    read_application,
    read_fraud_referral,
    read_inspection,
    read_parts_document,
    read_rebuilder,
    read_recognition_request,
    read_title,
    read_vehicle,
    register_vehicle,
    resolve_referral_payload,
    schedule_inspection_payload,
    set_clock,
    setup_appealable_failure,
    setup_draft_application,
    setup_failed_application,
    setup_program_actors,
    setup_salvage_titled_vehicle,
    setup_scheduled_inspection,
    submit_application_payload,
    submit_recognition_request,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    verify_parts_document,
    verify_parts_document_payload,
)


# ---------------------------------------------------------------------------
# priority 10 — header authentication
# ---------------------------------------------------------------------------
def test_writes_without_identity_headers_are_unauthenticated():
    """A missing X-User-ID and an undeclared role both stop at the header gate.

    PRD: "If either header is absent, empty, or if `X-User-Role` is not one of the seven declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is examined."
    Design: Corner/errors/writes_without_identity_headers_are_unauthenticated
    """
    headerless = {"X-User-Role": "StateTitleClerk", "Content-Type": "application/json"}
    malformed_body = create_vehicle_payload(body_class="NOT_A_CLASS")
    response = api_client.create_vehicle(malformed_body, headerless)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401, (
        f"an absent X-User-ID is a 401, got {response.status_code}"
    )

    undeclared_role = build_user_headers("aud-01", "Auditor")
    unknown_read = api_client.get_application(NON_EXISTENT_UUID, undeclared_role)
    validate_error(unknown_read, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert unknown_read.status_code == 401, (
        "an undeclared role is answered before the unknown path id, so the status is "
        f"401 rather than 404, got {unknown_read.status_code}"
    )
    body = unknown_read.json()
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"the error payload carries exactly error_id and message, got {sorted(body['data'])}"
    )


# ---------------------------------------------------------------------------
# priority 20 — role authorisation
# ---------------------------------------------------------------------------
def test_rebuilder_calling_a_clerk_only_write_is_forbidden():
    """The role gate answers before the path-existence gate.

    PRD: "When both headers are well formed but the named role is not among the roles authorised for the endpoint being called (see the endpoint table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    Design: Corner/errors/rebuilder_calling_a_clerk_only_write_is_forbidden
    """
    rebuilder = license_rebuilder()
    headers = make_rebuilder_headers(rebuilder["id"])

    registry_write = api_client.create_vehicle(create_vehicle_payload(), headers)
    validate_error(registry_write, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert registry_write.status_code == 403, (
        f"a rebuilder may not register vehicles, got {registry_write.status_code}"
    )

    unknown_application = api_client.review_application_docs(
        NON_EXISTENT_UUID, docs_review_payload("OPEN", review_note="not my endpoint"), headers
    )
    error = validate_error(unknown_application, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert unknown_application.status_code == 403, (
        f"the role refusal is a 403, got {unknown_application.status_code}"
    )
    assert error["error_id"] != ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, (
        "role authorisation runs before path-segment existence, so the unknown "
        "application id must not be reported"
    )


# ---------------------------------------------------------------------------
# priority 30 — path-segment existence
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "reader,expected_error",
    [
        ("get_vehicle", ApiErrorId.ERR_VEHICLE_NOT_FOUND),
        ("get_rebuilder", ApiErrorId.ERR_REBUILDER_NOT_FOUND),
        ("get_inspector", ApiErrorId.ERR_INSPECTOR_NOT_FOUND),
        ("get_inspection_station", ApiErrorId.ERR_STATION_NOT_FOUND),
        ("get_damage_report", ApiErrorId.ERR_DAMAGE_REPORT_NOT_FOUND),
        ("get_title_record", ApiErrorId.ERR_TITLE_NOT_FOUND),
        ("get_application", ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        ("get_parts_document", ApiErrorId.ERR_PARTS_DOCUMENT_NOT_FOUND),
        ("get_inspection", ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        ("get_finding", ApiErrorId.ERR_FINDING_NOT_FOUND),
        ("get_appeal", ApiErrorId.ERR_APPEAL_NOT_FOUND),
        ("get_fraud_referral", ApiErrorId.ERR_REFERRAL_NOT_FOUND),
        ("get_recognition_request", ApiErrorId.ERR_RECOGNITION_REQUEST_NOT_FOUND),
        ("get_title_transfer", ApiErrorId.ERR_TRANSFER_NOT_FOUND),
    ],
)
def test_unknown_ids_on_every_read_path_return_not_found(reader, expected_error):
    """Each single-resource read reports the 404 code named for its own family.

    PRD: "Existence of every resource named by a path segment, validated strictly left to right, so that a nested path reports the leftmost unresolvable segment."
    Design: Corner/errors/unknown_ids_on_every_read_path_return_not_found
    """
    response = getattr(api_client, reader)(NON_EXISTENT_UUID, make_program_admin_headers())
    error = validate_error(response, expected_error.value)
    assert response.status_code == 404, (
        f"{reader} on an unknown id is a 404, got {response.status_code}"
    )
    assert set(response.json()["data"].keys()) == {"error_id", "message"}, (
        f"the error payload carries exactly error_id and message, got {sorted(error)}"
    )


# ---------------------------------------------------------------------------
# priority 35 — body foreign keys
# ---------------------------------------------------------------------------
def test_an_unresolvable_body_vehicle_id_reports_vehicle_not_found():
    """A body foreign key that does not resolve yields its own 404 code.

    PRD: "Existence of every foreign key supplied in the request body, validated in the order the endpoint declares its body fields."
    Design: Corner/errors/body_foreign_keys_that_do_not_resolve_return_not_found
    """
    env = setup_salvage_titled_vehicle()
    rebuilder = license_rebuilder()
    headers = make_rebuilder_headers(rebuilder["id"])

    response = api_client.create_application(
        create_application_payload(
            NON_EXISTENT_UUID,
            rebuilder["id"],
            env["salvage_title_id"],
            declared_repair_cost_cents=800_000,
        ),
        headers,
    )
    validate_error(response, ApiErrorId.ERR_VEHICLE_NOT_FOUND.value)
    assert response.status_code == 404, (
        f"an unknown body vehicle_id is a 404, got {response.status_code}"
    )

    rows, meta = validate_paginated(
        api_client.list_applications(
            make_state_title_clerk_headers(), {"rebuilder_id": rebuilder["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused create must leave no application behind, got {rows}"
    )
    assert read_vehicle(env["vehicle_id"])["open_application_count"] == 0, (
        "the real vehicle's open_application_count must stay at 0"
    )


def test_an_unresolvable_title_shaped_body_key_reports_title_not_found():
    """Every title-shaped foreign key collapses onto the one title 404 code.

    PRD: "Any title-shaped foreign key — `salvage_title_id`, `predecessor_title_id`, `donor_title_id`, `from_title_id` or `title_record_id` — that fails to resolve reports `ERR_TITLE_NOT_FOUND`."
    Design: Corner/errors/body_foreign_keys_that_do_not_resolve_return_not_found
    """
    env = setup_salvage_titled_vehicle()
    rebuilder = license_rebuilder()

    response = api_client.create_application(
        create_application_payload(
            env["vehicle_id"],
            rebuilder["id"],
            NON_EXISTENT_UUID,
            declared_repair_cost_cents=800_000,
        ),
        make_rebuilder_headers(rebuilder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TITLE_NOT_FOUND.value)
    assert response.status_code == 404, (
        f"an unknown salvage_title_id is a 404, got {response.status_code}"
    )
    assert read_vehicle(env["vehicle_id"])["open_application_count"] == 0, (
        "the refused create must not raise the vehicle's open_application_count"
    )


# ---------------------------------------------------------------------------
# priority 40 — request well-formedness
# ---------------------------------------------------------------------------
def _post_vehicle_missing_a_required_field():
    payload = create_vehicle_payload()
    payload.pop("model")
    return api_client.create_vehicle(payload, make_state_title_clerk_headers())


def _post_vehicle_with_an_undeclared_enum_member():
    return api_client.create_vehicle(
        create_vehicle_payload(body_class="SPACESHIP"), make_state_title_clerk_headers()
    )


def _post_vehicle_with_a_sixteen_character_vin():
    return api_client.create_vehicle(
        create_vehicle_payload(vin="1HGCM82633A00732"), make_state_title_clerk_headers()
    )


def _list_applications_beyond_the_limit_ceiling():
    return api_client.list_applications(make_program_admin_headers(), {"limit": 500})


def _post_station_with_a_negative_bay_count():
    return api_client.create_inspection_station(
        create_inspection_station_payload(bay_count=-1), make_program_admin_headers()
    )


@pytest.mark.parametrize(
    "call",
    [
        _post_vehicle_missing_a_required_field,
        _post_vehicle_with_an_undeclared_enum_member,
        _post_vehicle_with_a_sixteen_character_vin,
        _list_applications_beyond_the_limit_ceiling,
        _post_station_with_a_negative_bay_count,
    ],
    ids=[
        "missing_required_field",
        "undeclared_enum_member",
        "sixteen_character_vin",
        "limit_above_one_hundred",
        "negative_bay_count",
    ],
)
def test_malformed_bodies_across_writes_return_invalid_request(call):
    """One well-formedness code answers every shape of malformed input.

    PRD: "This covers a missing required field, an enum value that is not a declared member, a negative money or mileage amount where the field is constrained to be non-negative, a timestamp that is not ISO 8601, a `scheduled_end_at` that is at or before `scheduled_start_at`, a `limit` outside 1 through 100 or a negative `offset`, a `vin` that is not exactly seventeen legal characters, a `checkpoint_results` array that is missing one of the weighted checkpoints, and an `attestation_signed` value that is not true."
    Design: Corner/errors/malformed_bodies_across_writes_return_invalid_request
    """
    response = call()
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400, (
        f"a malformed request is a 400, got {response.status_code}"
    )


def test_a_submission_whose_attestation_is_false_is_malformed():
    """attestation_signed must be exactly true or the submission is malformed.

    PRD: "The rebuilder submits with a single body field, `attestation_signed`, which must be exactly true; anything else is `ERR_INVALID_REQUEST`."
    Design: Corner/errors/malformed_bodies_across_writes_return_invalid_request
    """
    env = setup_draft_application(body_class="TRAILER")

    response = api_client.submit_application(
        env["application_id"],
        submit_application_payload(attestation_signed=False),
        env["rebuilder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400, (
        f"an unsigned attestation is a 400, got {response.status_code}"
    )
    application = read_application(env["application_id"])
    assert application["status"] == "DRAFT", (
        f"the refused submission leaves the application in DRAFT, got {application['status']}"
    )
    assert application["fee_escrowed_cents"] == 0, (
        "no money moves on a refused submission, "
        f"got {application['fee_escrowed_cents']}"
    )


# ---------------------------------------------------------------------------
# the referential gates around the salvage brand
# ---------------------------------------------------------------------------
def test_an_application_on_a_non_repairable_title_is_rejected():
    """A vehicle written off as beyond repair can never host an application.

    PRD: "The vehicle's `brand_history` must not contain `NON_REPAIRABLE`, and neither may the referenced title's `brand_code` be `NON_REPAIRABLE`; a vehicle the state has already written off as beyond repair can never be rebuilt, and the attempt is refused with `ERR_NON_REPAIRABLE_BRAND` (HTTP 409)."
    Design: Corner/errors/non_repairable_brand_clean_title_and_untraceable_donor_are_rejected
    """
    env = setup_salvage_titled_vehicle(acv_cents=400_000, repair_estimate_cents=600_000)
    assert env["damage_report"]["recommended_brand_code"] == "NON_REPAIRABLE", (
        "a repair estimate of 600,000 cents against an ACV of 400,000 gives a ratio of "
        "1.5000, which recommends NON_REPAIRABLE, got "
        f"{env['damage_report']['recommended_brand_code']}"
    )
    assert env["salvage_title"]["brand_code"] == "NON_REPAIRABLE", (
        f"the title takes the recommended brand, got {env['salvage_title']['brand_code']}"
    )
    assert env["salvage_title"]["brand_severity"] == 90, (
        f"NON_REPAIRABLE sits at severity 90, got {env['salvage_title']['brand_severity']}"
    )
    rebuilder = license_rebuilder()

    response = api_client.create_application(
        create_application_payload(
            env["vehicle_id"],
            rebuilder["id"],
            env["salvage_title_id"],
            declared_repair_cost_cents=600_000,
        ),
        make_rebuilder_headers(rebuilder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NON_REPAIRABLE_BRAND.value)
    assert response.status_code == 409, (
        f"the non-repairable refusal is a 409, got {response.status_code}"
    )
    assert read_vehicle(env["vehicle_id"])["open_application_count"] == 0, (
        "no application was opened"
    )


def test_an_application_on_an_unbranded_clean_title_is_rejected():
    """Only a SALVAGE or FLOOD title can be converted, so a clean title is refused.

    PRD: "The referenced title must have a `brand_code` of either `SALVAGE` or `FLOOD`, must have `status` of `ACTIVE` with `is_current` true, and its own `vehicle_id` must equal the application's `vehicle_id`; anything else is `ERR_SALVAGE_TITLE_REQUIRED` (HTTP 409)."
    Design: Corner/errors/non_repairable_brand_clean_title_and_untraceable_donor_are_rejected
    """
    vehicle = register_vehicle(make="Toyota", model="Camry", model_year=2022)
    clean_title = issue_title(vehicle["id"], owner_name="Noor Haddad")
    assert clean_title["brand_code"] == "NONE", (
        f"a title with no damage report behind it is unbranded, got {clean_title['brand_code']}"
    )
    assert clean_title["brand_severity"] == 0, (
        f"NONE sits at severity 0, got {clean_title['brand_severity']}"
    )
    rebuilder = license_rebuilder()

    response = api_client.create_application(
        create_application_payload(
            vehicle["id"],
            rebuilder["id"],
            clean_title["id"],
            declared_repair_cost_cents=150_000,
        ),
        make_rebuilder_headers(rebuilder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SALVAGE_TITLE_REQUIRED.value)
    assert response.status_code == 409, (
        f"the salvage-title requirement is a 409, got {response.status_code}"
    )
    assert read_vehicle(vehicle["id"])["open_application_count"] == 0, (
        "no application was opened against the clean title"
    )


def test_verifying_a_part_sourced_from_a_non_repairable_donor_is_rejected():
    """A donor title branded NON_REPAIRABLE cannot support a replacement part.

    PRD: "Replacement-part traceability is enforced here: a document whose `source_type` is `USED_DONOR` or `RECYCLER` must carry a `donor_title_id`, and the referenced donor title's `status` must not be `VOID` and its `brand_code` must not be `NON_REPAIRABLE`; a violation is `ERR_DONOR_TITLE_NOT_TRACEABLE` (HTTP 422)."
    Design: Corner/errors/non_repairable_brand_clean_title_and_untraceable_donor_are_rejected
    """
    donor = setup_salvage_titled_vehicle(acv_cents=400_000, repair_estimate_cents=600_000)
    assert donor["salvage_title"]["brand_code"] == "NON_REPAIRABLE", (
        "the donor vehicle's title is branded NON_REPAIRABLE"
    )
    env = setup_draft_application(body_class="TRAILER")
    document = file_parts_document(
        env["application_id"],
        env["rebuilder_id"],
        doc_type="PARTS_INVOICE",
        part_class="STRUCTURAL",
        source_type="USED_DONOR",
        amount_cents=250_000,
        vendor_name="Vega Auto Recyclers",
        donor_title_id=donor["salvage_title_id"],
    )

    response = api_client.verify_parts_document(
        document["id"],
        verify_parts_document_payload(),
        make_inspector_headers(env["inspector_id"]),
    )
    validate_error(response, ApiErrorId.ERR_DONOR_TITLE_NOT_TRACEABLE.value)
    assert response.status_code == 422, (
        f"an untraceable donor is a 422, got {response.status_code}"
    )
    assert read_parts_document(document["id"])["status"] == "SUBMITTED", (
        "the refused verification leaves the document in SUBMITTED"
    )
    assert read_application(env["application_id"])["documented_parts_cost_cents"] == 0, (
        "no amount is counted from a document that was never verified"
    )


# ---------------------------------------------------------------------------
# lifecycle gates on referrals and licences
# ---------------------------------------------------------------------------
def test_resolving_a_freshly_opened_referral_is_rejected():
    """Resolution is admissible only from INVESTIGATING, never straight from OPEN.

    PRD: "Resolution takes an `outcome` and an optional `resolution_note`, is admissible only from `INVESTIGATING`, and is barred to the principal recorded in `opened_by_user_id` under the segregation-of-duties rule of §2.10."
    Design: Corner/errors/resolving_an_open_referral_and_reinstating_an_active_licence_are_rejected
    """
    vehicle = register_vehicle()
    referral = open_fraud_referral(
        vehicle["id"],
        referral_type="IDENTITY_TAMPERING",
        evidence_summary="public tip about a swapped identity plate",
    )
    assert referral["status"] == "OPEN", (
        f"a manually filed referral opens in OPEN, got {referral['status']}"
    )

    response = api_client.resolve_fraud_referral(
        referral["id"],
        resolve_referral_payload(
            outcome="UNSUBSTANTIATED", resolution_note="closing without an investigation"
        ),
        make_fraud_investigator_headers(),
    )
    validate_error(response, ApiErrorId.ERR_REFERRAL_STATE_INVALID.value)
    assert response.status_code == 409, (
        f"an inadmissible referral transition is a 409, got {response.status_code}"
    )

    unchanged = read_fraud_referral(referral["id"])
    assert unchanged["status"] == "OPEN", (
        f"the refused resolution leaves the referral OPEN, got {unchanged['status']}"
    )
    assert unchanged["resolved_at"] is None, (
        f"no resolution instant is stamped, got {unchanged['resolved_at']}"
    )
    assert unchanged["investigator_user_id"] is None, (
        "no investigator is recorded, because the referral was never taken up"
    )
    assert read_vehicle(vehicle["id"])["fraud_hold"] == "UNDER_REFERRAL", (
        "filing placed the hold and the failed resolution did not lift it"
    )


def test_reinstating_an_active_licence_is_rejected():
    """REINSTATE is only a declared transition out of SUSPENDED.

    PRD: "Five actions exist and each is admissible only from specific statuses; an action that is not a declared transition out of the rebuilder's current `license_status` — a `REINSTATE` on an `ACTIVE` licence, or any action at all on a `REVOKED` licence, which is terminal — is refused with `ERR_LICENSE_ACTION_INVALID` (HTTP 409)."
    Design: Corner/errors/resolving_an_open_referral_and_reinstating_an_active_licence_are_rejected
    """
    rebuilder = license_rebuilder()
    assert rebuilder["license_status"] == "ACTIVE", (
        f"a new licence opens in ACTIVE, got {rebuilder['license_status']}"
    )

    response = api_client.create_license_action(
        rebuilder["id"],
        create_license_action_payload("REINSTATE", note="no suspension is in force"),
        make_program_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_LICENSE_ACTION_INVALID.value)
    assert response.status_code == 409, (
        f"an undeclared licence transition is a 409, got {response.status_code}"
    )

    unchanged = read_rebuilder(rebuilder["id"])
    assert unchanged["license_status"] == "ACTIVE", (
        f"the refused action leaves the licence ACTIVE, got {unchanged['license_status']}"
    )
    assert unchanged["version"] == rebuilder["version"], (
        "a refused licence action must not bump the rebuilder version, "
        f"moved from {rebuilder['version']} to {unchanged['version']}"
    )


# ---------------------------------------------------------------------------
# a decided recognition request is terminal
# ---------------------------------------------------------------------------
def test_deciding_a_recognition_request_twice_is_rejected():
    """DECIDED is terminal, so the second answer from the requesting state is refused.

    PRD: "The request must still be `PENDING`; one that is already `DECIDED` or `SUPERSEDED` is refused with `ERR_RECOGNITION_ALREADY_DECIDED` (HTTP 409)."
    Design: Corner/errors/deciding_a_recognition_request_twice_is_rejected
    """
    env = setup_salvage_titled_vehicle()
    request = submit_recognition_request(
        env["salvage_title_id"], env["salvage_title"]["version"]
    )
    decided = decide_recognition_request(request["id"], mapped_brand_code="SALVAGE")
    assert decided["status"] == "DECIDED", (
        f"the first decision closes the request, got {decided['status']}"
    )
    assert decided["outcome"] == "RECOGNIZED", (
        "a mapped brand equal to the submitted brand is RECOGNIZED, "
        f"got {decided['outcome']}"
    )

    response = api_client.decide_recognition_request(
        request["id"],
        decide_recognition_request_payload(
            mapped_brand_code="SALVAGE", decision_note="second bite at the decision"
        ),
        make_program_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_RECOGNITION_ALREADY_DECIDED.value)
    assert response.status_code == 409, (
        f"a second decision is a 409, got {response.status_code}"
    )

    unchanged = read_recognition_request(request["id"])
    assert unchanged["status"] == "DECIDED", "the request stays DECIDED"
    assert unchanged["mapped_brand_code"] == "SALVAGE", (
        f"the recorded mapping does not move, got {unchanged['mapped_brand_code']}"
    )
    assert unchanged["outcome"] == "RECOGNIZED", (
        f"the recorded outcome does not move, got {unchanged['outcome']}"
    )
    title = read_title(env["salvage_title_id"])
    assert title["recognition_state"] == "RECOGNIZED", (
        f"the title's recognition_state does not move again, got {title['recognition_state']}"
    )
    assert title["brand_code"] == "SALVAGE", (
        f"the title's own brand is untouched by a recognition decision, got {title['brand_code']}"
    )
    rows, meta = validate_paginated(
        api_client.list_recognition_requests(
            make_state_title_clerk_headers(), {"title_record_id": env["salvage_title_id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused decision created no second request, got {rows}"
    )


# ---------------------------------------------------------------------------
# state-machine gates on documents and attempts
# ---------------------------------------------------------------------------
def test_verifying_an_already_verified_document_is_rejected():
    """Verification is admissible only from SUBMITTED, so the amount cannot double-count.

    PRD: "It is admissible only from `SUBMITTED`; a document already `VERIFIED` or `REJECTED` draws `ERR_PARTS_DOCUMENT_STATE_INVALID` (HTTP 409)."
    Design: Corner/errors/reverifying_a_verified_document_and_completing_an_unstarted_inspection_are_rejected
    """
    env = setup_draft_application(body_class="TRAILER")
    document = file_parts_document(
        env["application_id"],
        env["rebuilder_id"],
        doc_type="RECEIPT",
        part_class="LIGHTING",
        source_type="NEW",
        amount_cents=20_000,
        vendor_name="Basin Frame Supply",
    )
    verified = verify_parts_document(document["id"], env["inspector_id"])
    assert verified["status"] == "VERIFIED", (
        f"the first verification lands the document in VERIFIED, got {verified['status']}"
    )
    assert read_application(env["application_id"])["documented_parts_cost_cents"] == 20_000, (
        "the verified amount is counted once"
    )

    response = api_client.verify_parts_document(
        document["id"],
        verify_parts_document_payload(verification_note="verifying a second time"),
        make_inspector_headers(env["inspector_id"]),
    )
    validate_error(response, ApiErrorId.ERR_PARTS_DOCUMENT_STATE_INVALID.value)
    assert response.status_code == 409, (
        f"a second verification is a 409, got {response.status_code}"
    )
    assert read_parts_document(document["id"])["status"] == "VERIFIED", (
        "the document stays VERIFIED"
    )
    assert read_application(env["application_id"])["documented_parts_cost_cents"] == 20_000, (
        "the refused second verification must not count the amount twice"
    )


def test_completing_an_attempt_that_was_never_started_is_rejected():
    """Completion is admissible only from IN_PROGRESS.

    PRD: "Completion is admissible only from `IN_PROGRESS`, or `ERR_INSPECTION_NOT_IN_PROGRESS` results."
    Design: Corner/errors/reverifying_a_verified_document_and_completing_an_unstarted_inspection_are_rejected
    """
    env = setup_scheduled_inspection()
    assert env["inspection"]["status"] == "SCHEDULED", (
        f"the attempt is booked but not started, got {env['inspection']['status']}"
    )

    response = api_client.complete_inspection(
        env["inspection_id"],
        complete_inspection_payload(env["vin"]),
        make_inspector_headers(env["inspector_id"]),
    )
    validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_IN_PROGRESS.value)
    assert response.status_code == 409, (
        f"completing an unstarted attempt is a 409, got {response.status_code}"
    )

    unchanged = read_inspection(env["inspection_id"])
    assert unchanged["status"] == "SCHEDULED", (
        f"the attempt stays SCHEDULED, got {unchanged['status']}"
    )
    assert unchanged["started_at"] is None, (
        f"no start instant is stamped, got {unchanged['started_at']}"
    )
    assert unchanged["result"] is None, (
        f"no result is adjudicated, got {unchanged['result']}"
    )
    application = read_application(env["application_id"])
    assert application["attempts_completed"] == 0, (
        f"no attempt has been consumed, got {application['attempts_completed']}"
    )
    assert application["last_inspection_result"] is None, (
        f"no outcome is published on the application, got {application['last_inspection_result']}"
    )


# ---------------------------------------------------------------------------
# the two appeal gates
# ---------------------------------------------------------------------------
def test_a_pending_appeal_blocks_rescheduling_the_next_attempt():
    """An appeal in flight freezes the scheduling track until it is decided.

    PRD: "No appeal of this application may sit in `FILED`, `UNDER_REVIEW` or `REMANDED`, or the request is refused with `ERR_APPEAL_PENDING_BLOCKS_SCHEDULING` (HTTP 409); an appeal in flight freezes the scheduling track until it is decided."
    Design: Corner/errors/pending_appeal_blocks_rescheduling_and_a_late_appeal_is_rejected
    """
    env = setup_appealable_failure(body_class="TRAILER")
    assert env["appeal"]["status"] == "FILED", (
        f"the appeal sits in FILED, got {env['appeal']['status']}"
    )
    # A second inspector keeps the segregation-of-duties rule out of the picture.
    other_inspector = setup_program_actors(with_station=False, deposit_cents=0)["inspector"]
    application = read_application(env["application_id"])

    response = api_client.schedule_inspection(
        env["application_id"],
        schedule_inspection_payload(
            other_inspector["id"],
            env["station_id"],
            application["version"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T11:00:00Z",
        ),
        make_state_title_clerk_headers(),
    )
    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_APPEAL_PENDING_BLOCKS_SCHEDULING.value,
            ApiErrorId.ERR_INVALID_APPLICATION_STATE.value,
        ],
    )
    assert response.status_code == 409, (
        "both readings of the frozen scheduling track are 409 refusals, got "
        f"{response.status_code}"
    )

    rows, meta = validate_paginated(
        api_client.list_inspections(
            make_state_title_clerk_headers(), {"application_id": env["application_id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"no second attempt was booked, got {meta['total_count']} rows: {rows}"
    )


def test_an_appeal_filed_after_the_thirty_day_window_is_rejected():
    """The appeal window runs 30 days from the failed attempt's completion.

    PRD: "The named attempt's `status` must be `COMPLETED_FAIL`, and the logical clock must be no later than that attempt's `completed_at` plus 30 days; a later filing, or a filing against an attempt that is not `COMPLETED_FAIL`, is refused with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422)."
    Design: Corner/errors/pending_appeal_blocks_rescheduling_and_a_late_appeal_is_rejected
    """
    env = setup_failed_application(body_class="TRAILER")
    inspection = read_inspection(env["inspection_id"])
    assert inspection["status"] == "COMPLETED_FAIL", (
        f"the attempt closed as a failure, got {inspection['status']}"
    )
    # The attempt completed at 2026-08-10T09:00:00Z, so the window shuts on
    # 2026-09-09T09:00:00Z and this filing is more than ten days late.
    set_clock("2026-09-20T00:00:00Z")

    response = api_client.create_appeal(
        create_appeal_payload(
            env["inspection_id"],
            grounds="PROCEDURAL_DEFECT",
            narrative="filed well after the statutory window",
        ),
        make_rebuilder_headers(env["rebuilder_id"]),
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)
    assert response.status_code == 422, (
        f"a late appeal is a 422, got {response.status_code}"
    )

    rows, meta = validate_paginated(
        api_client.list_appeals(
            make_state_title_clerk_headers(), {"inspection_id": env["inspection_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused filing created no appeal, got {rows}"
    )
    assert read_application(env["application_id"])["status"] == "FAILED", (
        "the application stays in FAILED because no appeal was filed"
    )
