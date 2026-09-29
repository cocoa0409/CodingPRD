"""Error triggerability: the not-found family, state gates, uniqueness keys, appeals and single-shot writes."""

from test_helpers import (
    AUDITOR_ADJUDICATOR,
    AUDITOR_ADJUDICATOR_ID,
    PROGRAM_ADMIN,
    ApiErrorId,
    assert_instant,
    assert_instant_null,
    assert_ledger_tuple,
    assert_subscriber_case,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
JUNE_START = "2026-06-01T00:00:00Z"
JULY_FILING = "2026-07-02T00:00:00Z"
SAME_UUID = "11111111-1111-4111-8111-111111111111"
DE_ENROLL_INSTANT = "2026-09-01T00:00:00Z"
APPEAL_DEADLINE = "2026-10-01T23:59:59.999Z"
ONE_MS_PAST_APPEAL = "2026-10-02T00:00:00.000Z"


def test_one_unused_uuid_yields_seven_different_not_found_codes(api):
    """The not-found family is keyed on the addressed entity, never on a single generic code.

    PRD: "Path existence, resolved outer to inner: for every identifier segment in the path,
    the addressed row must exist, otherwise the entity-specific not-found code for that
    segment: `ERR_PROVIDER_NOT_FOUND`, `ERR_ADDRESS_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`,
    `ERR_ELIGIBILITY_CHECK_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`,
    `ERR_SERVICE_TRANSFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AUDIT_SAMPLE_NOT_FOUND` or
    `ERR_CASE_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found_code
    """
    fx.set_clock(api, CLOCK)

    reads = (
        (api.get_address, ApiErrorId.ADDRESS_NOT_FOUND),
        (api.get_eligibility_check, ApiErrorId.ELIGIBILITY_CHECK_NOT_FOUND),
        (api.get_device, ApiErrorId.DEVICE_NOT_FOUND),
        (api.get_service_transfer, ApiErrorId.SERVICE_TRANSFER_NOT_FOUND),
        (api.get_claim, ApiErrorId.CLAIM_NOT_FOUND),
        (api.get_audit_sample, ApiErrorId.AUDIT_SAMPLE_NOT_FOUND),
        (api.get_subscriber_case, ApiErrorId.CASE_NOT_FOUND),
    )
    seen = []
    for read, expected in reads:
        response = read(SAME_UUID, PROGRAM_ADMIN)
        validate_error(response, expected.value, 404)
        body = response.json()
        assert sorted(body["data"].keys()) == ["error_id", "message"], (
            f"the error payload is exactly error_id and message, got {sorted(body['data'].keys())}"
        )
        assert sorted(body["meta"].keys()) == ["api_request_id", "api_request_timestamp"], (
            f"an error meta block carries only the two request fields, got {sorted(body['meta'].keys())}"
        )
        seen.append(body["data"]["error_id"])

    assert len(set(seen)) == 7, (
        f"the same path id produced seven distinct codes, got {sorted(set(seen))}"
    )
    assert ApiErrorId.INVALID_REQUEST.value not in seen, (
        "a syntactically valid but unused UUID is never a schema failure"
    )


def test_four_state_gates_on_four_entities_each_refuse_a_move_legal_elsewhere(api):
    """Resubmitting unasked documentation, resolving an unflagged dwelling, returning stock,
    and issuing a second handset.

    PRD: "the benefit's `device_status` must be `AWAITING_DEVICE`, so a benefit already in
    `DEVICE_ISSUED` or `RECLAIM_PENDING` is refused with `ERR_DEVICE_ALREADY_ISSUED`; then the
    freeze; then the one-handset rule; and only last the availability of stock."

    Design: Corner/errors/wrong_state_actions_are_rejected_on_checks_addresses_and_handsets
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    agent = fx.provider_headers(provider)
    first_handset, second_handset = fx.stock_devices(
        api, provider, [("BASIC", 2100), ("BASIC", 2200)]
    )
    dwelling = fx.register_distinct_address(api, 1)
    applicant = fx.create_subscriber(api, dwelling["id"])
    check = fx.open_eligibility_check(api, applicant["id"], proof_document_ref="DOC-1")
    assert dwelling["status"] == "UNVERIFIED"
    assert check["status"] == "PENDING_VERIFIER"

    unasked = api.resubmit_documentation(
        check["id"], f.resubmit_documentation_payload(proof_document_ref="DOC-S2"), agent
    )
    validate_error(unasked, ApiErrorId.DOCUMENTATION_NOT_REQUESTED.value, 409)
    assert fx.refresh_eligibility_check(api, check["id"])["resubmission_count"] == 0, (
        "the refused resubmission did not consume one of the two attempts"
    )

    pinned_version = fx.address_version(api, dwelling["id"])
    unflagged = api.resolve_duplicate_address(
        dwelling["id"],
        f.duplicate_resolution_payload(
            resolution="SINGLE_HOUSEHOLD",
            expected_address_version=pinned_version,
            resolution_note="no duplicate cohort exists",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(unflagged, ApiErrorId.ADDRESS_NOT_FLAGGED.value, 409)
    untouched_dwelling = fx.refresh_address(api, dwelling["id"])
    assert untouched_dwelling["status"] == "UNVERIFIED"
    assert untouched_dwelling["version"] == pinned_version, (
        "the refused resolution left the dwelling at its original version"
    )

    never_out = api.return_device(
        first_handset["id"], f.device_return_payload(return_condition="GOOD"), agent
    )
    validate_error(never_out, ApiErrorId.DEVICE_NOT_ISSUED.value, 409)
    in_stock = fx.refresh_device(api, first_handset["id"])
    assert in_stock["status"] == "IN_STOCK"
    assert_instant_null(in_stock["returned_at"], "returned_at")

    fx.confirm_eligibility_check(api, check["id"])
    benefit = fx.enroll(
        api,
        provider,
        applicant,
        fx.refresh_eligibility_check(api, check["id"]),
        dwelling,
        service_type="VOICE",
        benefit_start_date=CLOCK,
    )
    issued = fx.issue_device(api, benefit["id"], provider, device_id=first_handset["id"])
    assert issued["status"] == "ISSUED"

    already = api.issue_device(
        benefit["id"], f.device_issuance_payload(device_id=second_handset["id"]), agent
    )
    validate_error(already, ApiErrorId.DEVICE_ALREADY_ISSUED.value, 409)
    assert already.json()["data"]["error_id"] != ApiErrorId.SINGLE_DEVICE_PER_SUBSCRIBER.value, (
        "the device_status gate answers before the one-handset-per-subscriber rule is reached"
    )
    assert fx.refresh_device(api, second_handset["id"])["status"] == "IN_STOCK"
    assert fx.refresh_enrollment(api, benefit["id"])["device_issuance_count"] == 1


def test_the_identity_key_is_the_whole_triple_and_the_month_key_skips_drafts(api):
    """Changing only the SSN digits is admitted; a superseded draft never blocks a redraft.

    PRD: "And if another claim of the same carrier already covers the same `service_month`
    with a status outside `DRAFT` and `SUPERSEDED` — that is, one already `FILED`, `HELD`,
    `UNDER_AUDIT`, `AUDIT_PASSED` or `AUDIT_FAILED` — the draft is refused with
    `ERR_CLAIM_DUPLICATE_SERVICE_MONTH`."

    Design: Corner/errors/uniqueness_codes_fire_on_the_identity_triple_and_the_settled_month
    """
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    agent = fx.provider_headers(provider)
    first_dwelling = fx.register_distinct_address(api, 1)
    second_dwelling = fx.register_distinct_address(api, 2)

    identity = {"full_name": "Ana Ruiz", "date_of_birth": "1980-04-11", "last4_ssn": "4417"}
    resident = fx.eligible_applicant(
        api, first_dwelling["id"], subscriber_overrides=dict(identity)
    )
    original_key = resident["subscriber"]["identity_key"]
    assert original_key == "ANARUIZ|1980-04-11|4417"
    fx.enroll(
        api,
        provider,
        resident["subscriber"],
        resident["check"],
        first_dwelling,
        service_type="VOICE",
        benefit_start_date=JUNE_START,
    )

    same_person = api.create_subscriber(
        f.subscriber_payload(second_dwelling["id"], **identity), PROGRAM_ADMIN
    )
    validate_error(same_person, ApiErrorId.DUPLICATE_SUBSCRIBER_IDENTITY.value, 409)
    _empty, empty_meta = validate_paginated(
        api.list_subscribers(PROGRAM_ADMIN, {"address_id": second_dwelling["id"]})
    )
    assert empty_meta["total_count"] == 0, "the refused creation wrote no applicant row"

    near_twin = validate_success(
        api.create_subscriber(
            f.subscriber_payload(
                second_dwelling["id"],
                full_name="Ana Ruiz",
                date_of_birth="1980-04-11",
                last4_ssn="4418",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert near_twin["identity_key"] != original_key, (
        "only the four SSN digits changed, and the fingerprint moved with them"
    )
    assert near_twin["identity_key"] == "ANARUIZ|1980-04-11|4418"

    matched, matched_meta = validate_paginated(
        api.list_subscribers(PROGRAM_ADMIN, {"identity_key": original_key})
    )
    assert matched_meta["total_count"] == 1, (
        f"the original fingerprint still names one applicant, got {matched_meta['total_count']}"
    )
    assert matched[0]["id"] == resident["subscriber"]["id"]

    fx.set_clock(api, JULY_FILING)
    first_draft = fx.draft_claim(api, provider, "2026-06")
    second_draft = fx.draft_claim(api, provider, "2026-06")
    assert second_draft["status"] == "DRAFT"
    assert fx.refresh_claim(api, first_draft["id"])["status"] == "SUPERSEDED", (
        "a pre-existing draft stands down rather than blocking the redraft"
    )

    filed = fx.file_claim(api, second_draft["id"], provider, certifying_officer_ref="OFFICER-22")
    assert filed["status"] == "FILED"

    third = api.create_claim(
        f.claim_payload(
            provider_id=provider["id"],
            service_month="2026-06",
            expected_provider_version=fx.provider_version(api, provider["id"]),
        ),
        agent,
    )
    validate_error(third, ApiErrorId.CLAIM_DUPLICATE_SERVICE_MONTH.value, 409)

    _claims, claims_meta = validate_paginated(
        api.list_claims(
            PROGRAM_ADMIN, {"provider_id": provider["id"], "service_month": "2026-06"}
        )
    )
    assert claims_meta["total_count"] == 2, (
        f"the superseded draft and the filed claim, and nothing else, got {claims_meta['total_count']}"
    )
    carrier = fx.refresh_provider(api, provider["id"])
    assert carrier["claim_gross_cents"] == 925
    assert carrier["open_claim_count"] == 1, (
        f"the superseded draft counts in neither figure, got {carrier['open_claim_count']}"
    )


def test_the_case_type_is_gated_both_ways_and_the_appeal_window_closes_at_a_millisecond(api):
    """Appealing a live benefit and complaining about a stopped one are the same refusal.

    PRD: "Getting that backwards — appealing a live benefit, or complaining about a stopped
    one — is refused with `ERR_APPEAL_NOT_APPLICABLE`."

    Design: Corner/errors/appeal_codes_fire_on_the_wrong_benefit_state_and_after_the_window
    """
    fx.set_clock(api, CLOCK)
    provider = fx.register_provider(api)
    agent = fx.provider_headers(provider)
    dwelling = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, dwelling["id"])
    subscriber_id = applicant["subscriber"]["id"]
    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        dwelling,
        service_type="VOICE",
        benefit_start_date=CLOCK,
    )
    assert_instant_null(benefit["appeal_deadline_at"], "appeal_deadline_at")

    premature = api.create_subscriber_case(
        f.subscriber_case_payload(
            subscriber_id,
            benefit["id"],
            case_type="DE_ENROLLMENT_APPEAL",
            narrative="I never asked to be removed",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(premature, ApiErrorId.APPEAL_NOT_APPLICABLE.value, 409)

    complaint = validate_success(
        api.create_subscriber_case(
            f.subscriber_case_payload(
                subscriber_id,
                benefit["id"],
                case_type="SERVICE_COMPLAINT",
                narrative="Calls drop in my neighbourhood",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_subscriber_case(complaint)
    assert complaint["status"] == "SUBMITTED"
    assert complaint["review_round"] == 0
    assert complaint["decision"] is None

    fx.set_clock(api, DE_ENROLL_INSTANT)
    stopped = fx.de_enroll(
        api, benefit["id"], reason="SUBSCRIBER_REQUEST", headers=agent, note="agent error"
    )
    assert stopped["benefit_status"] == "DE_ENROLLED"
    assert_instant(stopped["appeal_deadline_at"], APPEAL_DEADLINE, "appeal_deadline_at")

    stale_complaint = api.create_subscriber_case(
        f.subscriber_case_payload(
            subscriber_id,
            benefit["id"],
            case_type="SERVICE_COMPLAINT",
            narrative="Still complaining about call quality",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(stale_complaint, ApiErrorId.APPEAL_NOT_APPLICABLE.value, 409)

    fx.set_clock(api, APPEAL_DEADLINE)
    appeal = validate_success(
        api.create_subscriber_case(
            f.subscriber_case_payload(
                subscriber_id,
                benefit["id"],
                case_type="DE_ENROLLMENT_APPEAL",
                narrative="Filing at the last permitted millisecond",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert appeal["case_type"] == "DE_ENROLLMENT_APPEAL"
    assert appeal["status"] == "SUBMITTED", (
        "the boundary instant is still inside the thirty-day window"
    )
    assert fx.refresh_case(api, appeal["id"])["reinstated_enrollment_flag"] is False

    fx.set_clock(api, ONE_MS_PAST_APPEAL)
    too_late = api.create_subscriber_case(
        f.subscriber_case_payload(
            subscriber_id,
            benefit["id"],
            case_type="DE_ENROLLMENT_APPEAL",
            narrative="One millisecond too late",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(too_late, ApiErrorId.APPEAL_WINDOW_EXPIRED.value, 409)

    cases, cases_meta = validate_paginated(
        api.list_subscriber_cases(PROGRAM_ADMIN, {"enrollment_id": benefit["id"]})
    )
    assert cases_meta["total_count"] == 2, (
        f"only the two admitted filings exist, got {cases_meta['total_count']}"
    )
    assert sorted(row["id"] for row in cases) == sorted([complaint["id"], appeal["id"]])
    assert fx.refresh_enrollment(api, benefit["id"])["benefit_status"] == "DE_ENROLLED"


def test_a_settled_sample_cannot_be_adjudicated_twice_even_with_the_same_finding(api):
    """The refused second adjudication must not re-run the bubble-up into the ledger.

    PRD: "The sample must be `DRAWN`, or the request is refused with
    `ERR_SAMPLE_ALREADY_ADJUDICATED`, and the owning claim must be `UNDER_AUDIT`."

    Design: Corner/errors/adjudication_is_single_shot_per_sample
    """
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api, licensed_state_codes=["TX"])
    dwelling = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, dwelling["id"])
    fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        dwelling,
        service_type="VOICE",
        benefit_start_date=JUNE_START,
    )

    fx.set_clock(api, JULY_FILING)
    claim = fx.file_claim(api, fx.draft_claim(api, provider, "2026-06")["id"], provider)
    assert claim["final_amount_cents"] == 925
    sample = fx.draw_samples(api, claim["id"], sample_size=1)[0]
    assert sample["selection_rank"] == 1
    assert sample["claimed_line_cents"] == 925

    settled = validate_success(
        api.adjudicate_audit_sample(
            sample["id"],
            f.adjudicate_payload(finding="COMPLIANT", finding_note="documentation complete"),
            AUDITOR_ADJUDICATOR,
        )
    )
    assert settled["status"] == "ADJUDICATED_PASS"
    assert settled["finding"] == "COMPLIANT"
    assert settled["disallowed_support_cents"] == 0
    assert settled["adjudicated_by_ref"] == AUDITOR_ADJUDICATOR_ID, (
        f"the adjudicating auditor is stamped, got {settled['adjudicated_by_ref']}"
    )

    passed = fx.refresh_claim(api, claim["id"])
    assert passed["status"] == "AUDIT_PASSED"
    assert passed["failed_sample_count"] == 0
    assert passed["net_payable_cents"] == 925

    again = api.adjudicate_audit_sample(
        sample["id"],
        f.adjudicate_payload(finding="COMPLIANT", finding_note="re-confirming the same finding"),
        AUDITOR_ADJUDICATOR,
    )
    validate_error(again, ApiErrorId.SAMPLE_ALREADY_ADJUDICATED.value, 409)

    unchanged_sample = fx.refresh_sample(api, sample["id"])
    assert unchanged_sample["status"] == "ADJUDICATED_PASS"
    assert unchanged_sample["finding_note"] == "documentation complete", (
        f"the refused call overwrote the note, got {unchanged_sample['finding_note']!r}"
    )

    unchanged_claim = fx.refresh_claim(api, claim["id"])
    assert unchanged_claim["status"] == "AUDIT_PASSED"
    assert unchanged_claim["net_payable_cents"] == 925, (
        "the refusal did not re-run the bubble-up"
    )
    carrier = fx.refresh_provider(api, provider["id"])
    assert_ledger_tuple(carrier, 925, 0, 925, False)
    assert carrier["open_claim_count"] == 0, (
        f"an audited-and-passed claim is closed, got {carrier['open_claim_count']}"
    )
