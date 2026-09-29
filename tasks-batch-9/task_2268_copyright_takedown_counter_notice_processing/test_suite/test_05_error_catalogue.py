"""Reachability and precedence of the PRD §5 error catalogue.

Each test drives one guard to the exact rung of the rejection ladder at which
it is declared, then proves the refusal left every touched aggregate alone.
The API server is restarted before every test, so each one builds its whole
world from scratch through the public API.
"""
from test_helpers import (
    AGENT,
    ApiErrorId,
    CLOCK_START_ISO,
    INVESTIGATOR,
    NON_EXISTENT_UUID,
    OFFICER,
    activate_reference_file,
    assert_instant_equals,
    claims_of_notice,
    create_account,
    create_account_payload,
    create_active_reference_file,
    create_content_item,
    create_content_item_payload,
    create_counter_notice,
    create_draft_agent,
    create_enrolled_rights_holder,
    create_forwarded_counter_notice,
    create_ingestion_batch,
    create_ingestion_batch_payload,
    create_misrepresentation_case,
    create_misrepresentation_case_payload,
    create_notice,
    create_processed_notice,
    create_provider,
    create_reference_file,
    create_submitted_agent,
    dismiss_misrepresentation_case,
    execute_termination_case,
    get_account,
    get_claim,
    get_content_item,
    get_counter_notice,
    get_misrepresentation_case,
    get_notice,
    get_provider,
    get_rights_holder,
    list_account_content_items,
    make_abuse_investigator_headers,
    make_rights_holder_rep_headers,
    make_subscriber_headers,
    promote_tier,
    record_suit_notice,
    set_clock,
    setup_account_with_items,
    setup_disabled_claim,
    setup_documented_provider,
    termination_cases_of_account,
    validate_error,
    validate_notice,
    validate_paginated,
    validate_success,
)

# The instants the recipes below pin, all derived from the default clock.
_REGISTRATION_EXPIRY_ISO = "2029-07-31T00:00:00Z"
_JUST_BEFORE_EXPIRY_ISO = "2029-07-30T23:59:59.999Z"
_RESTORATION_EARLIEST_ISO = "2026-08-14T00:00:00Z"
_RESTORATION_DEADLINE_ISO = "2026-08-20T00:00:00Z"
_SUIT_NOTICE_ISO = "2026-08-19T00:00:00Z"
_APPEAL_DEADLINE_ISO = "2026-08-15T00:00:00Z"
_JUST_AFTER_APPEAL_DEADLINE_ISO = "2026-08-15T00:00:00.001Z"

# A hosted fingerprint and a reference fingerprint sharing a 30-character
# leading run, which with a registration number scores exactly 0.95.
_ITEM_FINGERPRINT = "0123456789abcdef0123456789abcdef"
_REFERENCE_FINGERPRINT = "0123456789abcdef0123456789abcd00"
_REGISTRATION_NUMBER = "SR0000991122"


def _registered_agent_count(api, provider_id):
    _, meta = validate_paginated(
        api.list_provider_designated_agents(
            provider_id, OFFICER, {"registration_status": "REGISTERED"}
        )
    )
    return meta["total_count"]


def _misrepresentation_cases_of_holder(api, rights_holder_id):
    data, meta = validate_paginated(
        api.list_misrepresentation_cases(
            INVESTIGATOR, {"rights_holder_id": rights_holder_id}
        )
    )
    return data, meta["total_count"]


def test_registering_a_second_agent_while_one_is_registered_is_refused(api):
    """PRD §3.1: "The provider's `public_contact_published_at` must already be
    non-null, or the request fails with `ERR_PUBLIC_CONTACT_NOT_PUBLISHED`; the
    provider must not already hold another designation in `REGISTERED`, or the
    request fails with `ERR_AGENT_ALREADY_REGISTERED`; and the supplied provider
    version must match, per Section 2.7."

    Design: Corner/errors/register_a_second_agent_while_one_is_registered_is_refused
    """
    documented = setup_documented_provider()
    provider = documented["provider"]
    first_agent = documented["agent"]

    second_agent = create_submitted_agent(provider["id"])
    current = get_provider(provider["id"])

    response = api.register_designated_agent(
        second_agent["id"],
        {"expected_provider_version": current["version"]},
        OFFICER,
    )

    validate_error(response, ApiErrorId.ERR_AGENT_ALREADY_REGISTERED.value)

    refused = validate_success(api.get_designated_agent(second_agent["id"], OFFICER))
    assert refused["registration_status"] == "SUBMITTED"
    assert refused["registered_at"] is None

    incumbent = validate_success(api.get_designated_agent(first_agent["id"], OFFICER))
    assert incumbent["registration_status"] == "REGISTERED"

    assert get_provider(provider["id"])["version"] == current["version"]
    assert _registered_agent_count(api, provider["id"]) == 1


def test_uploading_while_the_account_is_upload_restricted_is_forbidden(api):
    """PRD §3.2: "Uploading is refused outright when the account is
    `TERMINATED`, with `ERR_ACCOUNT_TERMINATED`, and refused when
    `upload_restricted` is true because the account's standing is `LIMITED`,
    with `ERR_ACCOUNT_UPLOAD_RESTRICTED`."

    Design: Corner/errors/upload_while_the_account_is_upload_restricted_is_forbidden
    """
    documented = setup_documented_provider()
    scene = setup_account_with_items(documented["provider"]["id"], 2)
    account = scene["account"]
    holder = create_enrolled_rights_holder("STANDARD")

    create_processed_notice(
        holder["id"], [item["content_url"] for item in scene["items"]]
    )

    limited = get_account(account["id"])
    assert limited["standing"] == "LIMITED"
    assert limited["upload_restricted"] is True
    assert limited["terminated_at"] is None

    response = api.create_content_item(
        create_content_item_payload(account["id"]),
        make_subscriber_headers(account["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ACCOUNT_UPLOAD_RESTRICTED.value)

    _, meta = list_account_content_items(account["id"])
    assert meta["total_count"] == 2
    assert get_account(account["id"])["available_content_count"] == 0


def test_a_second_open_misrepresentation_case_on_the_same_pair_is_refused(api):
    """PRD §3.9: "At most one `OPEN` case may exist per holder-and-claim pair; a
    second is refused with `ERR_MISREPRESENTATION_CASE_EXISTS`."

    Design: Corner/errors/second_open_misrepresentation_case_for_the_same_pair_is_refused
    """
    scene = setup_disabled_claim()
    holder = scene["rights_holder"]
    claim = scene["claim"]

    # A second notice missing only material identification is rejected on the
    # core-element gate, which drives the holder's abuse score to exactly 40.00
    # and makes the system open its own case on the holder's newest claim.
    deficient = create_notice(
        holder["id"], [scene["item"]["content_url"]], material_identification=None
    )
    rejected = validate_notice(deficient["id"])
    assert rejected["status"] == "REJECTED"

    scored = get_rights_holder(holder["id"])
    assert float(scored["abuse_score"]) == 40.0

    existing, total_before = _misrepresentation_cases_of_holder(api, holder["id"])
    assert total_before == 1
    assert existing[0]["claim_id"] == claim["id"]
    assert existing[0]["opened_by_user_id"] is None
    assert existing[0]["status"] == "OPEN"

    response = api.create_misrepresentation_case(
        create_misrepresentation_case_payload(
            holder["id"], claim["id"], allegation="Duplicate manual filing."
        ),
        make_abuse_investigator_headers("investigator-01"),
    )

    validate_error(response, ApiErrorId.ERR_MISREPRESENTATION_CASE_EXISTS.value)

    survivors, total_after = _misrepresentation_cases_of_holder(api, holder["id"])
    assert total_after == 1
    assert survivors[0]["id"] == existing[0]["id"]
    assert survivors[0]["opened_by_user_id"] is None


def test_recording_a_suit_notice_at_the_restoration_deadline_is_refused(api):
    """PRD §3.7: "Recording the complainant's notice of court action is
    permitted while the counter-notice is `FORWARDED` or
    `RESTORATION_SCHEDULED` and the logical clock is **strictly before**
    `restoration_deadline_at`; at or after that instant the record is refused
    with `ERR_SUIT_NOTICE_WINDOW_CLOSED`, and a counter-notice in any other
    state is refused with `ERR_INVALID_COUNTER_NOTICE_STATE`."

    Design: Corner/errors/record_suit_notice_at_the_restoration_deadline_is_refused
    """
    scene = setup_disabled_claim()
    claim = scene["claim"]

    counter = create_forwarded_counter_notice(claim["id"], scene["account"]["id"])
    assert_instant_equals(
        counter["restoration_earliest_at"], _RESTORATION_EARLIEST_ISO,
        "restoration_earliest_at",
    )
    assert_instant_equals(
        counter["restoration_deadline_at"], _RESTORATION_DEADLINE_ISO,
        "restoration_deadline_at",
    )

    set_clock(_RESTORATION_DEADLINE_ISO)

    response = api.record_suit_notice(counter["id"], AGENT)

    validate_error(response, ApiErrorId.ERR_SUIT_NOTICE_WINDOW_CLOSED.value)

    unblocked = get_counter_notice(counter["id"])
    assert unblocked["status"] == "RESTORATION_SCHEDULED"
    assert unblocked["suit_notice_at"] is None
    assert get_claim(claim["id"])["status"] == "RESTORATION_SCHEDULED"

    # The window closed against the complainant, so restoration still proceeds.
    restored = validate_success(api.restore_claim(claim["id"], AGENT))
    assert restored["status"] == "RESTORED"
    assert get_content_item(scene["item"]["id"])["availability_status"] == "RESTORED"


def test_restoring_while_the_counter_notice_is_blocked_by_suit_is_refused(api):
    """PRD §3.7: "The governing counter-notice must not be `BLOCKED_BY_SUIT`,
    and an attempt while it is blocked is refused with
    `ERR_RESTORATION_BLOCKED_BY_SUIT`."

    Design: Corner/errors/restore_while_the_counter_notice_is_blocked_by_suit_is_refused
    """
    scene = setup_disabled_claim()
    claim = scene["claim"]
    account = scene["account"]

    counter = create_forwarded_counter_notice(claim["id"], account["id"])
    set_clock(_RESTORATION_EARLIEST_ISO)
    set_clock(_SUIT_NOTICE_ISO)
    record_suit_notice(counter["id"])

    blocked = get_counter_notice(counter["id"])
    assert blocked["status"] == "BLOCKED_BY_SUIT"
    assert_instant_equals(blocked["suit_notice_at"], _SUIT_NOTICE_ISO, "suit_notice_at")

    scheduled = get_claim(claim["id"])
    assert scheduled["status"] == "RESTORATION_SCHEDULED"
    assert_instant_equals(
        scheduled["restoration_due_at"], _RESTORATION_EARLIEST_ISO,
        "restoration_due_at",
    )

    response = api.restore_claim(claim["id"], AGENT)

    validate_error(response, ApiErrorId.ERR_RESTORATION_BLOCKED_BY_SUIT.value)

    # Upholding is the only way to finalise the claim, and it adds no strike.
    upheld = validate_success(api.uphold_claim(claim["id"], AGENT))
    assert upheld["status"] == "UPHELD"
    assert upheld["restoration_due_at"] is None

    _, strike_meta = validate_paginated(api.list_claim_strikes(claim["id"], AGENT))
    assert strike_meta["total_count"] == 1
    assert float(get_account(account["id"])["strike_points"]) == 10.0

    item = get_content_item(scene["item"]["id"])
    assert item["availability_status"] == "DISABLED"
    assert item["dispute_status"] == "RESOLVED"
    assert get_notice(scene["notice"]["id"])["status"] == "CLOSED"


def test_lapsing_before_the_registration_term_expires_is_refused(api):
    """PRD §3.1: "Lapsing a registration moves it `REGISTERED → LAPSED` and may
    only be done once the logical clock has reached or passed `expires_at`;
    earlier attempts are refused with `ERR_REGISTRATION_NOT_EXPIRED`, and
    lapsing anything that is not `REGISTERED` is refused with
    `ERR_INVALID_AGENT_STATE`."

    Design: Corner/errors/lapse_before_the_registration_term_expires_is_refused
    """
    documented = setup_documented_provider()
    provider = documented["provider"]
    agent = documented["agent"]
    assert_instant_equals(agent["expires_at"], _REGISTRATION_EXPIRY_ISO, "expires_at")

    set_clock(_JUST_BEFORE_EXPIRY_ISO)

    response = api.lapse_designated_agent(agent["id"], OFFICER)

    validate_error(response, ApiErrorId.ERR_REGISTRATION_NOT_EXPIRED.value)

    intact = validate_success(api.get_designated_agent(agent["id"], OFFICER))
    assert intact["registration_status"] == "REGISTERED"
    assert_instant_equals(intact["expires_at"], _REGISTRATION_EXPIRY_ISO, "expires_at")

    posture = get_provider(provider["id"])
    assert posture["designated_agent_registered"] is True
    assert posture["safe_harbor_status"] == "ELIGIBLE"
    assert posture["safe_harbor_score"] == 100

    # One millisecond later the term has run and the same call is accepted.
    set_clock(_REGISTRATION_EXPIRY_ISO)
    lapsed = validate_success(api.lapse_designated_agent(agent["id"], OFFICER))
    assert lapsed["registration_status"] == "LAPSED"


def test_a_second_account_with_the_same_handle_under_one_provider_is_refused(api):
    """PRD §3.2: "The handle must be unique within that provider; a collision is
    refused with `ERR_ACCOUNT_HANDLE_CONFLICT`."

    Design: Corner/errors/second_account_with_the_same_handle_is_refused
    """
    set_clock(CLOCK_START_ISO)
    first_provider = create_provider()
    second_provider = create_provider()
    incumbent = create_account(
        first_provider["id"], handle="ada_lovelace", email="ada@subscriber.example"
    )

    response = api.create_account(
        create_account_payload(
            first_provider["id"],
            handle="ada_lovelace",
            email="ada.second@subscriber.example",
        ),
        OFFICER,
    )

    validate_error(response, ApiErrorId.ERR_ACCOUNT_HANDLE_CONFLICT.value)

    # Uniqueness is provider-scoped, so the same handle is free elsewhere.
    elsewhere = validate_success(
        api.create_account(
            create_account_payload(
                second_provider["id"],
                handle="ada_lovelace",
                email="ada@southshore.example",
            ),
            OFFICER,
        ),
        201,
    )
    assert elsewhere["handle"] == "ada_lovelace"

    _, first_meta = validate_paginated(
        api.list_accounts(OFFICER, {"provider_id": first_provider["id"]})
    )
    _, second_meta = validate_paginated(
        api.list_accounts(OFFICER, {"provider_id": second_provider["id"]})
    )
    assert first_meta["total_count"] == 1
    assert second_meta["total_count"] == 1
    assert get_account(incumbent["id"])["email"] == "ada@subscriber.example"


def test_a_standard_tier_holder_cannot_open_an_ingestion_batch(api):
    """PRD §3.4: "Three preconditions guard the operation, and their relative
    order is the one given in Section 2.6: the hosting provider's
    `safe_harbor_status` must be `ELIGIBLE`, refused otherwise with
    `ERR_SAFE_HARBOR_NOT_ELIGIBLE`; the holder must be `ENROLLED`, refused
    otherwise with `ERR_RIGHTS_HOLDER_NOT_ENROLLED`; and the holder's
    `program_tier` must be `VERIFIED` or `TRUSTED`, refused otherwise with
    `ERR_PROGRAM_TIER_INSUFFICIENT`."

    Design: Corner/errors/standard_tier_holder_cannot_open_an_ingestion_batch
    """
    documented = setup_documented_provider()
    assert documented["provider"]["safe_harbor_status"] == "ELIGIBLE"

    holder = create_enrolled_rights_holder("STANDARD")
    assert holder["enrollment_status"] == "ENROLLED"
    assert holder["program_tier"] == "STANDARD"

    payload = create_ingestion_batch_payload(holder["id"], 10)
    rep_headers = make_rights_holder_rep_headers(holder["id"])

    response = api.create_ingestion_batch(payload, rep_headers)

    validate_error(response, ApiErrorId.ERR_PROGRAM_TIER_INSUFFICIENT.value)

    _, meta = validate_paginated(
        api.list_rights_holder_ingestion_batches(holder["id"], OFFICER)
    )
    assert meta["total_count"] == 0

    # The tier is the only unmet precondition: promoting it lets the batch open.
    promote_tier(holder["id"])
    accepted = validate_success(api.create_ingestion_batch(payload, rep_headers), 201)
    assert accepted["status"] == "ACCEPTED"


def test_promoting_to_trusted_without_an_active_reference_file_is_refused(api):
    """PRD §3.3: "The step to `TRUSTED` carries one extra requirement: the holder
    must already have at least one reference file in `ACTIVE`, and a promotion
    attempted without one is refused with `ERR_NO_REFERENCE_FILE_ACTIVE`."

    Design: Corner/errors/promote_to_trusted_without_an_active_reference_file_is_refused
    """
    set_clock(CLOCK_START_ISO)
    create_provider()
    holder = create_enrolled_rights_holder("VERIFIED")
    reference = create_reference_file(
        holder["id"], registration_number=_REGISTRATION_NUMBER
    )
    assert reference["status"] == "PENDING"

    before = get_rights_holder(holder["id"])
    assert before["program_tier"] == "VERIFIED"
    assert float(before["abuse_score"]) == 0.0

    response = api.promote_rights_holder_tier(holder["id"], OFFICER)

    validate_error(response, ApiErrorId.ERR_NO_REFERENCE_FILE_ACTIVE.value)

    assert get_rights_holder(holder["id"])["program_tier"] == "VERIFIED"

    # A PENDING file does not satisfy the requirement, but an ACTIVE one does.
    activate_reference_file(reference["id"], holder["id"])
    promoted = validate_success(api.promote_rights_holder_tier(holder["id"], OFFICER))
    assert promoted["program_tier"] == "TRUSTED"


def test_an_appeal_filed_at_the_appeal_deadline_is_refused(api):
    """PRD §3.8: "The clock must be **strictly before** `appeal_deadline_at`; at
    or after that instant the filing is refused with
    `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/errors/appeal_filed_at_the_appeal_deadline_is_refused
    """
    documented = setup_documented_provider()
    scene = setup_account_with_items(documented["provider"]["id"], 4)
    account = scene["account"]
    holder = create_enrolled_rights_holder("STANDARD")

    create_processed_notice(
        holder["id"], [item["content_url"] for item in scene["items"]]
    )

    cases = termination_cases_of_account(account["id"])
    assert len(cases) == 1
    case = execute_termination_case(cases[0]["id"], "officer-01")
    assert_instant_equals(
        case["appeal_deadline_at"], _APPEAL_DEADLINE_ISO, "appeal_deadline_at",
    )
    assert float(case["trigger_points"]) == 40.0

    terminated = get_account(account["id"])
    assert terminated["standing"] == "TERMINATED"
    assert terminated["available_content_count"] == 0
    for item in scene["items"]:
        assert get_content_item(item["id"])["availability_status"] == "DISABLED"

    set_clock(_APPEAL_DEADLINE_ISO)
    at_deadline = validate_success(api.get_termination_case(case["id"], OFFICER))
    assert at_deadline["status"] == "EXECUTED"

    response = api.file_termination_appeal(
        case["id"], make_subscriber_headers(account["id"])
    )

    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)

    unfiled = validate_success(api.get_termination_case(case["id"], OFFICER))
    assert unfiled["status"] == "EXECUTED"
    assert unfiled["appeal_filed_at"] is None

    # A millisecond past the deadline the case auto-closes and the state rung
    # decides the refusal instead.
    set_clock(_JUST_AFTER_APPEAL_DEADLINE_ISO)
    closed = validate_success(api.get_termination_case(case["id"], OFFICER))
    assert closed["status"] == "CLOSED"
    validate_error(
        api.file_termination_appeal(case["id"], make_subscriber_headers(account["id"])),
        ApiErrorId.ERR_INVALID_TERMINATION_STATE.value,
    )


def test_every_not_found_code_is_reachable_from_its_own_read_endpoint(api):
    """PRD §2.5: "A missing provider yields `ERR_PROVIDER_NOT_FOUND`, a missing
    designated agent `ERR_DESIGNATED_AGENT_NOT_FOUND`, a missing policy revision
    `ERR_POLICY_NOT_FOUND`, a missing account `ERR_ACCOUNT_NOT_FOUND`, a missing
    content item `ERR_CONTENT_ITEM_NOT_FOUND`, a missing rights holder
    `ERR_RIGHTS_HOLDER_NOT_FOUND`, a missing notice `ERR_NOTICE_NOT_FOUND`, a
    missing claim `ERR_CLAIM_NOT_FOUND`, a missing counter-notice
    `ERR_COUNTER_NOTICE_NOT_FOUND`, a missing strike record
    `ERR_STRIKE_NOT_FOUND`, a missing termination case
    `ERR_TERMINATION_CASE_NOT_FOUND`, a missing misrepresentation case
    `ERR_MISREPRESENTATION_CASE_NOT_FOUND`, a missing reference file
    `ERR_REFERENCE_FILE_NOT_FOUND`, a missing ingestion batch
    `ERR_INGESTION_BATCH_NOT_FOUND`, and a missing audit record
    `ERR_AUDIT_NOT_FOUND`."

    Design: Corner/errors/every_not_found_code_is_reachable_from_its_own_read_endpoint
    """
    set_clock(CLOCK_START_ISO)

    probes = [
        (api.get_provider(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_PROVIDER_NOT_FOUND),
        (api.get_designated_agent(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_DESIGNATED_AGENT_NOT_FOUND),
        (api.get_policy(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_POLICY_NOT_FOUND),
        (api.get_account(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
        (api.get_content_item(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_CONTENT_ITEM_NOT_FOUND),
        (api.get_rights_holder(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_RIGHTS_HOLDER_NOT_FOUND),
        (api.get_notice(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_NOTICE_NOT_FOUND),
        (api.get_claim(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (api.get_counter_notice(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_COUNTER_NOTICE_NOT_FOUND),
        (api.get_strike(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_STRIKE_NOT_FOUND),
        (api.get_termination_case(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_TERMINATION_CASE_NOT_FOUND),
        (api.get_misrepresentation_case(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_MISREPRESENTATION_CASE_NOT_FOUND),
        (api.get_reference_file(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_REFERENCE_FILE_NOT_FOUND),
        (api.get_ingestion_batch(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_INGESTION_BATCH_NOT_FOUND),
        (api.get_safe_harbor_audit(NON_EXISTENT_UUID, OFFICER),
         ApiErrorId.ERR_AUDIT_NOT_FOUND),
    ]

    seen = []
    for response, expected in probes:
        error = validate_error(response, expected.value)
        seen.append(error["error_id"])

    assert len(set(seen)) == len(probes), (
        f"each read route must answer with its own code, got {seen}"
    )

    # A nested read under an unknown parent reports the parent, not an empty list.
    validate_error(
        api.list_account_strikes(NON_EXISTENT_UUID, OFFICER),
        ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value,
    )


def test_state_codes_are_distinct_on_agent_counter_notice_and_reference_file(api):
    """PRD §2.6: "Depending on the resource this is `ERR_INVALID_AGENT_STATE`,
    `ERR_INVALID_POLICY_STATE`, `ERR_INVALID_NOTICE_STATE`,
    `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_COUNTER_NOTICE_STATE`,
    `ERR_INVALID_CONTENT_STATE`, `ERR_INVALID_ACCOUNT_STANDING`,
    `ERR_INVALID_TERMINATION_STATE`, `ERR_INVALID_MISREPRESENTATION_STATE`,
    `ERR_INVALID_REFERENCE_FILE_STATE` or `ERR_INVALID_BATCH_STATE`, each with
    HTTP 409." PRD §3.1: "Registering from `DRAFT` or from `LAPSED` is refused
    with `ERR_INVALID_AGENT_STATE`." PRD §3.7: "Forwarding anything that is not
    `VALIDATED` is refused with `ERR_INVALID_COUNTER_NOTICE_STATE`." PRD §3.3:
    "Activating a file that is already `ACTIVE`, or one that has been
    `QUARANTINED`, is refused with `ERR_INVALID_REFERENCE_FILE_STATE`;
    `QUARANTINED` is terminal."

    Design: Corner/errors/state_family_codes_are_reachable_on_agent_counter_notice_and_reference_file
    """
    documented = setup_documented_provider()
    provider = documented["provider"]
    account = create_account(provider["id"])
    item = create_content_item(account["id"], fingerprint_hash=_ITEM_FINGERPRINT)
    holder = create_enrolled_rights_holder("VERIFIED")
    reference = create_active_reference_file(
        holder["id"],
        fingerprint_hash=_REFERENCE_FINGERPRINT,
        registration_number=_REGISTRATION_NUMBER,
    )
    draft_agent = create_draft_agent(provider["id"])
    assert draft_agent["registration_status"] == "DRAFT"

    notice = create_processed_notice(holder["id"], [item["content_url"]])
    claim = claims_of_notice(notice["id"])[0]
    counter = create_counter_notice(claim["id"], account["id"])
    assert counter["status"] == "RECEIVED"

    current = get_provider(provider["id"])
    reference_before = validate_success(
        api.get_reference_file(reference["id"], OFFICER)
    )
    assert reference_before["status"] == "ACTIVE"

    # A DRAFT designation was never submitted, so the state rung decides before
    # the one-registered-agent uniqueness rung and before the version check.
    validate_error(
        api.register_designated_agent(
            draft_agent["id"],
            {"expected_provider_version": current["version"]},
            OFFICER,
        ),
        ApiErrorId.ERR_INVALID_AGENT_STATE.value,
    )
    validate_error(
        api.forward_counter_notice(counter["id"], AGENT),
        ApiErrorId.ERR_INVALID_COUNTER_NOTICE_STATE.value,
    )
    validate_error(
        api.activate_reference_file(
            reference["id"], make_rights_holder_rep_headers(holder["id"])
        ),
        ApiErrorId.ERR_INVALID_REFERENCE_FILE_STATE.value,
    )

    untouched_agent = validate_success(
        api.get_designated_agent(draft_agent["id"], OFFICER)
    )
    assert untouched_agent["registration_status"] == "DRAFT"
    assert get_provider(provider["id"])["version"] == current["version"]

    untouched_counter = get_counter_notice(counter["id"])
    assert untouched_counter["status"] == "RECEIVED"
    assert untouched_counter["forwarded_at"] is None

    reference_after = validate_success(api.get_reference_file(reference["id"], OFFICER))
    assert reference_after["status"] == "ACTIVE"
    assert reference_after["activated_at"] == reference_before["activated_at"]
    assert reference_after["match_count"] == reference_before["match_count"]


def test_state_codes_are_distinct_on_account_termination_case_and_batch(api):
    """PRD §2.6: "Depending on the resource this is `ERR_INVALID_AGENT_STATE`,
    `ERR_INVALID_POLICY_STATE`, `ERR_INVALID_NOTICE_STATE`,
    `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_COUNTER_NOTICE_STATE`,
    `ERR_INVALID_CONTENT_STATE`, `ERR_INVALID_ACCOUNT_STANDING`,
    `ERR_INVALID_TERMINATION_STATE`, `ERR_INVALID_MISREPRESENTATION_STATE`,
    `ERR_INVALID_REFERENCE_FILE_STATE` or `ERR_INVALID_BATCH_STATE`, each with
    HTTP 409." PRD §3.8: "An account that is not `TERMINATED`, or one whose
    recomputed total is still at or above the limitation threshold, is refused
    with `ERR_INVALID_ACCOUNT_STANDING`." PRD §3.8: "Filing against a case that
    is not `EXECUTED` is refused with `ERR_INVALID_TERMINATION_STATE`." PRD
    §3.9: "The referenced claim must not be `UPHELD` — a claim the provider
    itself upheld cannot simultaneously be a fraudulent takedown — and a
    substantiation against an upheld claim, or against a case that is not
    `OPEN`, is refused with `ERR_INVALID_MISREPRESENTATION_STATE`." PRD §3.4: "A
    completion attempted on a batch that is not `PROCESSING`, or on one whose
    notices have not all settled, is refused with `ERR_INVALID_BATCH_STATE`."

    Design: Corner/errors/state_family_codes_are_reachable_on_account_termination_case_and_batch
    """
    documented = setup_documented_provider()
    scene = setup_account_with_items(documented["provider"]["id"], 4)
    account = scene["account"]
    holder = create_enrolled_rights_holder("VERIFIED")

    notice = create_processed_notice(
        holder["id"], [item["content_url"] for item in scene["items"]]
    )
    claim = claims_of_notice(notice["id"])[0]

    limited = get_account(account["id"])
    assert limited["standing"] == "LIMITED"
    assert float(limited["strike_points"]) == 60.0

    cases = termination_cases_of_account(account["id"])
    assert len(cases) == 1
    case = cases[0]
    assert case["status"] == "OPEN"

    abuse_case = create_misrepresentation_case(
        holder["id"], claim["id"], investigator_user_id="investigator-01"
    )
    dismiss_misrepresentation_case(abuse_case["id"], "investigator-02")

    batch = create_ingestion_batch(holder["id"], 10)
    assert batch["status"] == "ACCEPTED"

    validate_error(
        api.reinstate_account(account["id"], OFFICER),
        ApiErrorId.ERR_INVALID_ACCOUNT_STANDING.value,
    )
    # The case is OPEN rather than EXECUTED, so the state rung decides ahead of
    # the appeal-window rung.
    validate_error(
        api.file_termination_appeal(case["id"], make_subscriber_headers(account["id"])),
        ApiErrorId.ERR_INVALID_TERMINATION_STATE.value,
    )
    validate_error(
        api.substantiate_misrepresentation_case(
            abuse_case["id"], make_abuse_investigator_headers("investigator-02")
        ),
        ApiErrorId.ERR_INVALID_MISREPRESENTATION_STATE.value,
    )
    validate_error(
        api.complete_ingestion_batch(
            batch["id"], make_rights_holder_rep_headers(holder["id"])
        ),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value,
    )

    unchanged_account = get_account(account["id"])
    assert unchanged_account["standing"] == "LIMITED"
    assert float(unchanged_account["strike_points"]) == 60.0
    assert unchanged_account["terminated_at"] is None

    unchanged_case = validate_success(api.get_termination_case(case["id"], OFFICER))
    assert unchanged_case["status"] == "OPEN"
    assert unchanged_case["appeal_filed_at"] is None

    unchanged_abuse_case = get_misrepresentation_case(abuse_case["id"])
    assert unchanged_abuse_case["status"] == "DISMISSED"
    assert unchanged_abuse_case["total_penalty_cents"] == 0
    assert get_rights_holder(holder["id"])["misrepresentation_count"] == 0

    unchanged_batch = validate_success(api.get_ingestion_batch(batch["id"], OFFICER))
    assert unchanged_batch["status"] == "ACCEPTED"
    assert unchanged_batch["matched_count"] == 0
    assert unchanged_batch["unmatched_count"] == 0
