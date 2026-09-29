"""Role authorisation, resource ownership, segregation of duties, optimistic
concurrency on provider and claim versions, threshold-driven standing, and the
immediacy of derived state (PRD §2.1, §2.4, §2.6, §2.7, §2.11, §3.6, §3.8).
"""
from test_helpers import (
    AGENT,
    OFFICER,
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_DEFAULTS,
    assert_instant_equals,
    claims_of_notice,
    create_account,
    create_content_item,
    create_content_item_payload,
    create_counter_notice,
    create_counter_notice_payload,
    create_draft_policy,
    create_enrolled_rights_holder,
    create_ingestion_batch_payload,
    create_misrepresentation_case_payload,
    create_notice,
    create_notice_payload,
    create_processed_notice,
    create_provider,
    create_reference_file_payload,
    create_registered_agent,
    create_rights_holder,
    create_submitted_agent,
    get_account,
    get_claim,
    get_content_item,
    get_counter_notice,
    get_notice,
    get_provider,
    get_rights_holder,
    get_termination_case,
    list_account_strikes,
    list_account_termination_cases,
    make_abuse_investigator_headers,
    make_compliance_officer_headers,
    make_rights_holder_rep_headers,
    make_subscriber_headers,
    publish_contact,
    set_clock,
    setup_account_with_items,
    setup_disabled_claim,
    setup_documented_provider,
    strike_summary,
    validate_counter_notice,
    validate_error,
    validate_paginated,
    validate_success,
)

# A reference fingerprint sharing its first 30 characters with the hosted
# material's fingerprint, so a VERIFIED holder's match floor is met exactly.
_REFERENCE_FINGERPRINT = "0123456789abcdef0123456789abcd00"


def _counter_notice_body(claim_id: str, expected_claim_version: int) -> dict:
    """A statutorily complete counter-notice body pinned to one claim version."""
    return create_counter_notice_payload(claim_id, expected_claim_version)


# ---------------------------------------------------------------------------
# Role authorisation and resource ownership (PRD §2.1)
# ---------------------------------------------------------------------------

def test_compliance_officer_cannot_validate_a_notice(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not
    among the roles authorised for the endpoint being called, the request fails
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_validate_a_notice
    """
    setup = setup_documented_provider()
    account = create_account(setup["provider"]["id"])
    item = create_content_item(account["id"])
    holder = create_enrolled_rights_holder("STANDARD")
    notice = create_notice(holder["id"], [item["content_url"]])
    assert notice["status"] == "RECEIVED"

    refused = api.validate_notice(notice["id"], OFFICER)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    # The read is shared with the ComplianceOfficer, and shows nothing moved.
    untouched = validate_success(api.get_notice(notice["id"], OFFICER))
    assert untouched["status"] == "RECEIVED"
    assert untouched["completeness_score"] == 0
    assert untouched["validated_at"] is None

    # The very same call from the authorised TakedownAgent lands.
    validated = validate_success(api.validate_notice(notice["id"], AGENT))
    assert validated["status"] == "VALIDATED"
    assert validated["validated_at"] is not None


def test_subscriber_cannot_counter_notice_another_subscribers_claim(api):
    """PRD §2.1: "An entity-backed role that acts on a resource belonging to a
    different entity is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/subscriber_cannot_counter_notice_another_subscribers_claim
    """
    setup = setup_documented_provider()
    provider_id = setup["provider"]["id"]
    owner = create_account(provider_id)
    owned_item = create_content_item(owner["id"])
    impostor = create_account(provider_id)
    create_content_item(impostor["id"])
    holder = create_enrolled_rights_holder("STANDARD")

    notice = create_processed_notice(holder["id"], [owned_item["content_url"]])
    claim = claims_of_notice(notice["id"])[0]
    assert claim["content_item_id"] == owned_item["id"]

    # The impostor holds a perfectly current claim version, and is still refused.
    body = _counter_notice_body(claim["id"], claim["version"])
    refused = api.create_counter_notice(body, make_subscriber_headers(impostor["id"]))
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    _, meta = validate_paginated(
        api.list_counter_notices(AGENT, {"claim_id": claim["id"]})
    )
    assert meta["total_count"] == 0
    assert get_claim(claim["id"])["status"] == "DISABLED"

    # The identical body from the owning account is accepted.
    accepted = validate_success(
        api.create_counter_notice(body, make_subscriber_headers(owner["id"])),
        expected_status=201,
    )
    assert accepted["account_id"] == owner["id"]


def test_the_officer_who_executed_a_termination_cannot_decide_its_appeal(api):
    """PRD §2.1: "A `ComplianceOfficer` whose `X-User-ID` equals the
    `executed_by_user_id` recorded on a termination case may not decide that
    case's appeal; a second officer identity must decide it."

    Design: Corner/rbac/the_officer_who_executed_a_termination_cannot_decide_its_appeal
    """
    setup = setup_documented_provider()
    scene = setup_account_with_items(setup["provider"]["id"], 4)
    account_id = scene["account"]["id"]
    holder = create_enrolled_rights_holder("STANDARD")

    notice = create_processed_notice(
        holder["id"], [item["content_url"] for item in scene["items"]]
    )
    assert notice["matched_claim_count"] == 4

    cases, cases_meta = list_account_termination_cases(account_id, params={"status": "OPEN"})
    assert cases_meta["total_count"] == 1
    case_id = cases[0]["id"]

    executing_officer = make_compliance_officer_headers("co-1")
    executed = validate_success(api.execute_termination_case(case_id, executing_officer))
    assert executed["status"] == "EXECUTED"
    assert executed["executed_by_user_id"] == "co-1"

    set_clock("2026-08-05T00:00:00Z")
    appealed = validate_success(
        api.file_termination_appeal(case_id, make_subscriber_headers(account_id))
    )
    assert appealed["status"] == "APPEAL_FILED"

    refused = api.decide_termination_appeal(case_id, "VACATED", executing_officer)
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    still_open = get_termination_case(case_id)
    assert still_open["status"] == "APPEAL_FILED"
    assert still_open["decision"] is None
    assert still_open["decided_by_user_id"] is None

    decided = validate_success(
        api.decide_termination_appeal(
            case_id, "VACATED", make_compliance_officer_headers("co-2")
        )
    )
    assert decided["status"] == "VACATED"
    assert decided["decision"] == "VACATED"
    assert decided["decided_by_user_id"] == "co-2"
    assert decided["executed_by_user_id"] == "co-1"

    account = get_account(account_id)
    assert account["standing"] == "ACTIVE"
    assert float(account["strike_points"]) == 0.0
    assert account["upload_restricted"] is False
    assert account["terminated_at"] is None

    _, voided_meta = list_account_strikes(account_id, params={"status": "VOIDED"})
    assert voided_meta["total_count"] == 4


def test_the_investigator_who_opened_a_case_cannot_substantiate_it(api):
    """PRD §2.1: "An `AbuseInvestigator` whose `X-User-ID` equals a non-null
    `opened_by_user_id` on a misrepresentation case may neither substantiate nor
    dismiss that case; a second investigator identity must."

    Design: Corner/rbac/the_investigator_who_opened_a_case_cannot_substantiate_it
    """
    scene = setup_disabled_claim()
    holder_id = scene["rights_holder"]["id"]
    claim_id = scene["claim"]["id"]

    opener = make_abuse_investigator_headers("inv-1")
    case = validate_success(
        api.create_misrepresentation_case(
            create_misrepresentation_case_payload(holder_id, claim_id), opener
        ),
        expected_status=201,
    )
    assert case["opened_by_user_id"] == "inv-1"

    validate_error(
        api.substantiate_misrepresentation_case(case["id"], opener),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    validate_error(
        api.dismiss_misrepresentation_case(case["id"], opener),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    untouched = validate_success(api.get_misrepresentation_case(case["id"], opener))
    assert untouched["status"] == "OPEN"
    assert untouched["substantiated_at"] is None
    assert untouched["total_penalty_cents"] == 0

    substantiated = validate_success(
        api.substantiate_misrepresentation_case(
            case["id"], make_abuse_investigator_headers("inv-2")
        )
    )
    assert substantiated["status"] == "SUBSTANTIATED"
    assert substantiated["substantiated_by_user_id"] == "inv-2"
    assert substantiated["affected_claim_count"] == 1
    assert substantiated["disabled_day_count"] == 0
    assert substantiated["base_penalty_cents"] == 25000
    assert substantiated["surcharge_cents"] == 0
    assert substantiated["total_penalty_cents"] == 25000

    holder = get_rights_holder(holder_id)
    assert holder["misrepresentation_count"] == 1
    assert float(holder["abuse_score"]) == 60.00


def test_rights_holder_rep_performs_its_exclusive_and_shared_operations(api):
    """PRD §2.1: "This ownership check guards exactly ten operations: uploading
    material, purging material, creating a counter-notice, filing a termination
    appeal, submitting a notice, withdrawing a notice, registering a reference
    file, activating a reference file, opening an ingestion batch, and completing
    an ingestion batch."

    Design: Corner/rbac/rights_holder_rep_performs_its_exclusive_and_shared_operations
    """
    setup = setup_documented_provider()
    assert setup["provider"]["safe_harbor_status"] == "ELIGIBLE"
    account = create_account(setup["provider"]["id"])
    item = create_content_item(
        account["id"], fingerprint_hash=TEST_DEFAULTS["CONTENT_FINGERPRINT"]
    )
    holder = create_enrolled_rights_holder("VERIFIED")
    rep = make_rights_holder_rep_headers(holder["id"])

    reference = validate_success(
        api.create_reference_file(
            create_reference_file_payload(
                holder["id"],
                fingerprint_hash=_REFERENCE_FINGERPRINT,
                registration_number="SR0000991122",
            ),
            rep,
        ),
        expected_status=201,
    )
    activated = validate_success(api.activate_reference_file(reference["id"], rep))
    assert activated["status"] == "ACTIVE"

    batch = validate_success(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 10), rep
        ),
        expected_status=201,
    )
    assert batch["status"] == "ACCEPTED"

    notice = validate_success(
        api.create_notice(
            create_notice_payload(
                holder["id"],
                [item["content_url"]],
                submission_channel="API_BULK",
                ingestion_batch_id=batch["id"],
            ),
            rep,
        ),
        expected_status=201,
    )
    validate_success(api.validate_notice(notice["id"], AGENT))
    validate_success(api.process_notice(notice["id"], AGENT))

    assert validate_success(api.get_ingestion_batch(batch["id"], rep))["notices_created"] == 1

    withdrawn = validate_success(api.withdraw_notice(notice["id"], rep))
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_rights_holder(holder["id"])["withdrawn_count"] == 1

    completed = validate_success(api.complete_ingestion_batch(batch["id"], rep))
    assert completed["status"] == "COMPLETED"
    assert completed["matched_count"] == 1
    assert completed["unmatched_count"] == 0

    # The withdrawal compensated everything the processing had done.
    assert float(get_account(account["id"])["strike_points"]) == 0.0
    assert get_content_item(item["id"])["availability_status"] == "RESTORED"

    # Opening a batch is exclusive to the RightsHolderRep, and only for its own
    # holder: a different holder's identity is an ownership violation.
    other_holder = create_rights_holder()
    validate_error(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 10), AGENT
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 10),
            make_rights_holder_rep_headers(other_holder["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )


# ---------------------------------------------------------------------------
# Optimistic concurrency and threshold triggers (PRD §2.4, §2.7, §3.8)
# ---------------------------------------------------------------------------

def test_register_agent_with_a_stale_provider_version_returns_412(api):
    """PRD §2.7: "A registration legitimately supersedes the provider's
    previously published agent designation, so a writer holding a stale provider
    view is rejected with `ERR_STALE_PROVIDER_VERSION` (HTTP 412) and must
    re-read the provider before re-issuing the registration."

    Design: Corner/cross_cutting_complexity_layers/register_agent_with_a_stale_provider_version_returns_412
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    stale_version = provider["version"]
    publish_contact(provider["id"])
    agent = create_submitted_agent(provider["id"])

    refused = api.register_designated_agent(
        agent["id"], {"expected_provider_version": stale_version}, OFFICER
    )
    validate_error(refused, ApiErrorId.ERR_STALE_PROVIDER_VERSION.value)

    assert validate_success(
        api.get_designated_agent(agent["id"], OFFICER)
    )["registration_status"] == "SUBMITTED"

    fresh = get_provider(provider["id"])
    assert fresh["designated_agent_registered"] is False
    fresh_version = fresh["version"]
    assert fresh_version != stale_version

    registered = validate_success(
        api.register_designated_agent(
            agent["id"], {"expected_provider_version": fresh_version}, OFFICER
        )
    )
    assert registered["registration_status"] == "REGISTERED"

    after = get_provider(provider["id"])
    assert after["designated_agent_registered"] is True
    assert after["version"] > fresh_version


def test_publish_policy_with_a_stale_provider_version_returns_412(api):
    """PRD §2.7: "Publication supersedes whichever revision the provider
    currently has in `PUBLISHED`, so a writer that does not hold the provider
    version it intends to supersede is rejected with
    `ERR_STALE_PROVIDER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/publish_policy_with_a_stale_provider_version_returns_412
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    stale_version = publish_contact(provider["id"])["version"]
    create_registered_agent(provider["id"])
    policy = create_draft_policy(provider["id"])

    refused = api.publish_policy(policy["id"], stale_version, OFFICER)
    validate_error(refused, ApiErrorId.ERR_STALE_PROVIDER_VERSION.value)

    unpublished = validate_success(api.get_policy(policy["id"], OFFICER))
    assert unpublished["status"] == "DRAFT"
    assert unpublished["published_at"] is None

    blocked = get_provider(provider["id"])
    assert blocked["repeat_infringer_policy_published"] is False
    assert blocked["safe_harbor_status"] == "FORFEITED"

    published = validate_success(
        api.publish_policy(policy["id"], blocked["version"], OFFICER)
    )
    assert published["status"] == "PUBLISHED"

    after = get_provider(provider["id"])
    assert after["repeat_infringer_policy_published"] is True
    assert after["safe_harbor_status"] == "ELIGIBLE"
    assert after["safe_harbor_score"] == 100


def test_counter_notice_with_a_stale_claim_version_returns_412(api):
    """PRD §2.7: "A new counter-notice legitimately supersedes an earlier
    non-terminal counter-notice on the same claim, so the creating writer must
    present the claim version it observed when it decided to supersede; a
    mismatch is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/counter_notice_with_a_stale_claim_version_returns_412
    """
    scene = setup_disabled_claim()
    account_id = scene["account"]["id"]
    claim_id = scene["claim"]["id"]
    observed_version = scene["claim"]["version"]

    first = create_counter_notice(
        claim_id, account_id, expected_claim_version=observed_version
    )
    validate_counter_notice(first["id"])

    replayed = api.create_counter_notice(
        _counter_notice_body(claim_id, observed_version),
        make_subscriber_headers(account_id),
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_CLAIM_VERSION.value)

    _, meta = validate_paginated(
        api.list_counter_notices(AGENT, {"claim_id": claim_id})
    )
    assert meta["total_count"] == 1

    survivor = get_counter_notice(first["id"])
    assert survivor["status"] == "VALIDATED"
    assert survivor["superseded_by_counter_notice_id"] is None

    claim = get_claim(claim_id)
    assert claim["status"] == "COUNTER_NOTICED"
    assert claim["version"] > observed_version


def test_version_increments_on_every_write_and_never_on_a_read(api):
    """PRD §2.4: "Records also carry `updated_at`, in the same format, refreshed
    on every mutation, and `version`, an integer that starts at 1 and increments
    by exactly 1 each time the record is mutated."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()

    v_a = validate_success(api.get_provider(provider["id"], OFFICER))["version"]
    assert v_a == 1

    v_b = publish_contact(provider["id"])["version"]
    assert v_b == 2

    v_c = validate_success(api.get_provider(provider["id"], OFFICER))["version"]
    assert v_c == v_b

    agent = validate_success(
        api.create_designated_agent(
            {
                "provider_id": provider["id"],
                "agent_name": TEST_DEFAULTS["AGENT_NAME"],
                "agent_email": TEST_DEFAULTS["AGENT_EMAIL"],
                "agent_phone": TEST_DEFAULTS["AGENT_PHONE"],
                "mailing_address": TEST_DEFAULTS["MAILING_ADDRESS"],
            },
            OFFICER,
        ),
        expected_status=201,
    )
    assert agent["version"] == 1
    assert validate_success(api.submit_designated_agent(agent["id"], OFFICER))["version"] == 2
    registered = validate_success(
        api.register_designated_agent(
            agent["id"], {"expected_provider_version": v_c}, OFFICER
        )
    )
    assert registered["version"] == 3

    # Only the registration touched the provider row: 2 -> 3, not 2 -> 5.
    v_d = validate_success(api.get_provider(provider["id"], OFFICER))["version"]
    assert v_d == 3

    # A rejected write leaves both rows exactly where they were.
    validate_error(
        api.submit_designated_agent(agent["id"], OFFICER),
        ApiErrorId.ERR_INVALID_AGENT_STATE.value,
    )
    assert validate_success(
        api.get_designated_agent(agent["id"], OFFICER)
    )["version"] == 3
    assert validate_success(api.get_provider(provider["id"], OFFICER))["version"] == 3


def test_account_flips_to_limited_at_exactly_the_limitation_threshold(api):
    """PRD §3.8: "`ACTIVE → LIMITED` fires as soon as a recomputation puts
    `strike_points` at or above the published policy's
    `limitation_threshold_points`, and sets `upload_restricted` to true, which is
    what blocks further uploads from that account."

    Design: Corner/cross_cutting_complexity_layers/account_flips_to_limited_at_exactly_the_limitation_threshold
    """
    setup = setup_documented_provider()
    assert setup["policy"]["limitation_threshold_points"] == 20
    assert setup["policy"]["termination_threshold_points"] == 40
    scene = setup_account_with_items(setup["provider"]["id"], 3)
    account_id = scene["account"]["id"]
    holder = create_enrolled_rights_holder("STANDARD")
    assert holder["program_tier"] == "STANDARD"

    create_processed_notice(holder["id"], [scene["items"][0]["content_url"]])
    after_first = get_account(account_id)
    assert float(after_first["strike_points"]) == 10.00
    assert after_first["standing"] == "ACTIVE"
    assert after_first["upload_restricted"] is False

    create_processed_notice(holder["id"], [scene["items"][1]["content_url"]])
    after_second = get_account(account_id)
    assert float(after_second["strike_points"]) == 20.00
    assert after_second["standing"] == "LIMITED"
    assert after_second["upload_restricted"] is True

    _, cases_meta = list_account_termination_cases(account_id)
    assert cases_meta["total_count"] == 0

    validate_error(
        api.create_content_item(
            create_content_item_payload(account_id), make_subscriber_headers(account_id)
        ),
        ApiErrorId.ERR_ACCOUNT_UPLOAD_RESTRICTED.value,
    )

    assert get_content_item(scene["items"][2]["id"])["availability_status"] == "AVAILABLE"
    assert get_account(account_id)["available_content_count"] == 1


# ---------------------------------------------------------------------------
# Immediate consistency of derived state (PRD §3.6)
# ---------------------------------------------------------------------------

def test_process_response_already_carries_every_derived_field(api):
    """PRD §3.6: "Processing writes `matched_claim_count`, the number of
    `claimed_urls` entries that matched live material, and `unmatched_url_count`,
    the number that matched none, then stamps `processed_at` from the logical
    clock — that stamp is the endpoint of the response-latency measurement used
    by the safe-harbour audit."

    Design: Corner/consistency_model/process_response_already_carries_every_derived_field
    """
    setup = setup_documented_provider()
    scene = setup_account_with_items(setup["provider"]["id"], 2)
    account_id = scene["account"]["id"]
    holder = create_enrolled_rights_holder("STANDARD")
    unknown_url = "https://northstar.example/v/never-hosted"
    claimed = [
        scene["items"][0]["content_url"],
        scene["items"][1]["content_url"],
        unknown_url,
    ]
    notice = create_notice(holder["id"], claimed)
    validate_success(api.validate_notice(notice["id"], AGENT))

    processed = validate_success(api.process_notice(notice["id"], AGENT))
    assert processed["status"] == "PROCESSED"
    assert processed["matched_claim_count"] == 2
    assert processed["unmatched_url_count"] == 1
    assert_instant_equals(processed["processed_at"], CLOCK_START_ISO, "processed_at")

    claims, claims_meta = validate_paginated(
        api.list_claims(AGENT, {"notice_id": notice["id"]})
    )
    assert claims_meta["total_count"] == 2
    assert [claim["matched_url"] for claim in claims] == claimed[:2]

    account = validate_success(api.get_account(account_id, OFFICER))
    assert float(account["strike_points"]) == 20.00
    assert account["standing"] == "LIMITED"
    assert account["upload_restricted"] is True
    assert account["notified_count"] == 2
    assert account["available_content_count"] == 0

    summary = strike_summary(account_id)
    assert float(summary["strike_points"]) == 20.00
    assert summary["active_strike_count"] == 2

    assert get_rights_holder(holder["id"])["notices_processed"] == 1
    assert get_notice(notice["id"])["status"] == "PROCESSED"
