"""Entity creation, stored-field semantics and list mechanics.

Each test builds its own world through the public API against an empty
database and a logical clock that starts at 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    AGENT,
    CLOCK_START_ISO,
    INVESTIGATOR,
    NON_EXISTENT_UUID,
    OFFICER,
    ApiErrorId,
    assert_claim,
    assert_common_fields,
    assert_content_item,
    assert_instant_equals,
    assert_notice,
    assert_policy,
    assert_provider,
    assert_rights_holder,
    assert_safe_harbor_audit,
    create_account,
    create_active_reference_file,
    create_content_item,
    create_content_item_payload,
    create_designated_agent_payload,
    create_enrolled_rights_holder,
    create_notice,
    create_notice_payload,
    create_policy_payload,
    create_provider,
    create_provider_payload,
    create_rights_holder,
    create_validated_notice,
    enroll_rights_holder,
    get_account,
    get_provider,
    get_rights_holder,
    list_account_content_items,
    list_claims,
    list_provider_audits,
    make_subscriber_headers,
    promote_tier,
    set_clock,
    setup_documented_provider,
    shift_iso,
    validate_error,
    validate_paginated,
    validate_success,
)

CONTENT_FINGERPRINT = "0123456789abcdef0123456789abcdef"
# Shares the first 30 of 32 characters with CONTENT_FINGERPRINT.
REFERENCE_FINGERPRINT = "0123456789abcdef0123456789abcd00"


def _response_type(response) -> str:
    return response.json()["response_type"]


def _ids(rows) -> list:
    return [row["id"] for row in rows]


def test_new_provider_starts_forfeited_with_zero_score_and_all_gates_closed(api):
    """PRD §3.1: "A newly registered provider is deliberately non-compliant: `safe_harbor_status` starts at `FORFEITED` with `safe_harbor_score` 0, `designated_agent_registered` and `repeat_infringer_policy_published` both start false, and `public_contact_url`, `public_contact_published_at` and `last_audit_at` all start null."

    Design: Corner/entities/create_provider_starts_forfeited_with_zero_score
    """
    set_clock(CLOCK_START_ISO)

    response = api.create_provider(
        create_provider_payload(
            legal_name="Northstar Hosting LLC",
            service_domain="northstar.example",
        ),
        OFFICER,
    )
    provider = validate_success(response, expected_status=201)

    assert _response_type(response) == "object"
    assert_provider(provider)
    assert provider["legal_name"] == "Northstar Hosting LLC"
    assert provider["service_domain"] == "northstar.example"
    assert provider["safe_harbor_status"] == "FORFEITED"
    assert provider["safe_harbor_score"] == 0
    assert provider["designated_agent_registered"] is False
    assert provider["repeat_infringer_policy_published"] is False
    assert provider["public_contact_url"] is None
    assert provider["public_contact_published_at"] is None
    assert provider["last_audit_at"] is None
    assert provider["version"] == 1
    assert_instant_equals(provider["created_at"], CLOCK_START_ISO,
                          "provider created_at")


def test_rights_holder_read_echoes_supplied_quotas_and_zeroed_counters(api):
    """PRD §3.3: "A new holder starts at `enrollment_status` `PROSPECT` and `program_tier` `STANDARD`, with `notices_processed`, `withdrawn_count`, `rejected_count`, `misrepresentation_count` and `abuse_score` all 0."

    Design: Corner/entities/get_rights_holder_returns_stored_quotas_and_counters
    """
    set_clock(CLOCK_START_ISO)
    holder = create_rights_holder(
        legal_name="Orbit Records LLC",
        contact_email="legal@orbit.example",
        reference_file_quota=3,
        daily_item_quota=750,
    )

    data = validate_success(api.get_rights_holder(holder["id"], AGENT))

    assert_rights_holder(data)
    assert data["id"] == holder["id"]
    assert data["legal_name"] == "Orbit Records LLC"
    assert data["contact_email"] == "legal@orbit.example"
    assert data["reference_file_quota"] == 3
    assert data["daily_item_quota"] == 750
    assert data["enrollment_status"] == "PROSPECT"
    assert data["program_tier"] == "STANDARD"
    assert data["notices_processed"] == 0
    assert data["withdrawn_count"] == 0
    assert data["rejected_count"] == 0
    assert data["misrepresentation_count"] == 0
    assert float(data["abuse_score"]) == 0.0


def test_notice_list_reports_filtered_total_and_derives_has_more_from_offset(api):
    """PRD §2.3: "Filters are applied **before** pagination, so `total_count` is the size of the filtered set rather than the size of the underlying collection, and `has_more` is true exactly when the sum of `offset` and the number of rows actually returned is less than `total_count`."

    Design: Corner/entities/list_notices_paginates_oldest_first_with_total_count_and_has_more
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    holder = create_rights_holder(contact_email="legal@orbit.example")

    first = create_notice(holder["id"], ["https://northstar.example/v/1"],
                          submission_channel="WEB_FORM")
    set_clock(shift_iso(CLOCK_START_ISO, hours=1))
    second = create_notice(holder["id"], ["https://northstar.example/v/2"],
                           submission_channel="WEB_FORM")
    set_clock(shift_iso(CLOCK_START_ISO, hours=2))
    third = create_notice(holder["id"], ["https://northstar.example/v/3"],
                          submission_channel="EMAIL")

    page_response = api.list_notices(
        OFFICER,
        {"rights_holder_id": holder["id"], "limit": 2, "offset": 0},
    )
    page, meta = validate_paginated(page_response)

    assert _response_type(page_response) == "array"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert len(page) == 2
    assert _ids(page) == [first["id"], second["id"]]

    tail, tail_meta = validate_paginated(
        api.list_notices(
            OFFICER,
            {"rights_holder_id": holder["id"], "limit": 2, "offset": 2},
        )
    )
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False
    assert len(tail) == 1
    assert tail[0]["id"] == third["id"]

    for row in page + tail:
        assert_notice(row)
        assert row["status"] == "RECEIVED"
        assert row["completeness_score"] == 0

    assert get_provider(provider["id"])["version"] == 1


def test_reading_an_unknown_claim_id_returns_claim_not_found(api):
    """PRD §2.5: "A missing provider yields `ERR_PROVIDER_NOT_FOUND`, a missing designated agent `ERR_DESIGNATED_AGENT_NOT_FOUND`, a missing policy revision `ERR_POLICY_NOT_FOUND`, a missing account `ERR_ACCOUNT_NOT_FOUND`, a missing content item `ERR_CONTENT_ITEM_NOT_FOUND`, a missing rights holder `ERR_RIGHTS_HOLDER_NOT_FOUND`, a missing notice `ERR_NOTICE_NOT_FOUND`, a missing claim `ERR_CLAIM_NOT_FOUND`, a missing counter-notice `ERR_COUNTER_NOTICE_NOT_FOUND`, a missing strike record `ERR_STRIKE_NOT_FOUND`, a missing termination case `ERR_TERMINATION_CASE_NOT_FOUND`, a missing misrepresentation case `ERR_MISREPRESENTATION_CASE_NOT_FOUND`, a missing reference file `ERR_REFERENCE_FILE_NOT_FOUND`, a missing ingestion batch `ERR_INGESTION_BATCH_NOT_FOUND`, and a missing audit record `ERR_AUDIT_NOT_FOUND`."

    Design: Corner/entities/get_claim_with_unknown_id_returns_claim_not_found
    """
    set_clock(CLOCK_START_ISO)

    response = api.get_claim(NON_EXISTENT_UUID, AGENT)

    error = validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND.value)
    assert _response_type(response) == "error"
    assert error["message"].strip()


def test_upload_without_a_fingerprint_is_rejected_and_stores_nothing(api):
    """PRD §3.2: "A `Subscriber` uploads material against its own `account_id`, supplying the `content_url` at which the material lives, a `title`, and a `fingerprint_hash` — a lowercase 32-character hexadecimal content fingerprint that will later be compared against rights holders' reference works."

    Design: Corner/entities/create_content_item_without_fingerprint_returns_invalid_request
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    account = create_account(provider["id"], handle="ada_lovelace",
                             email="ada@subscriber.example")

    payload = create_content_item_payload(
        account["id"],
        content_url="https://northstar.example/v/1",
        title="Clip One",
    )
    payload.pop("fingerprint_hash")

    validate_error(
        api.create_content_item(payload, make_subscriber_headers(account["id"])),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    items, meta = list_account_content_items(account["id"])
    assert meta["total_count"] == 0
    assert items == []
    assert get_account(account["id"])["available_content_count"] == 0


def test_policy_revision_applies_every_documented_default_when_omitted(api):
    """PRD §3.1: "Drafting a revision takes the `provider_id` and the `policy_text` that will be published as prose, plus seven optional numeric settings that all have defaults."

    Design: Corner/entities/repeat_infringer_policy_threshold_defaults_applied_when_omitted
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()

    response = api.create_policy(
        create_policy_payload(
            provider["id"],
            policy_text="Repeat infringers lose their accounts.",
        ),
        OFFICER,
    )
    policy = validate_success(response, expected_status=201)

    assert_policy(policy)
    assert policy["strike_expiry_days"] == 365
    assert policy["decay_step_days"] == 90
    assert policy["limitation_threshold_points"] == 20
    assert policy["termination_threshold_points"] == 40
    assert policy["appeal_window_days"] == 14
    assert policy["counter_notice_window_days"] == 30
    assert policy["dispute_window_days"] == 30
    assert policy["status"] == "DRAFT"
    assert policy["published_at"] is None
    assert get_provider(provider["id"])["repeat_infringer_policy_published"] is False


def test_claim_match_confidence_is_computed_from_the_active_reference_prefix(api):
    """PRD §3.6: "Divide that length by 32, multiply by 0.80, and add 0.20 when the reference file has a non-null `registration_number` and nothing when it does not; round the result half up to four decimal places to obtain that candidate's confidence."

    Design: Corner/entities/claim_match_confidence_computed_from_active_reference_file_prefix
    """
    setup = setup_documented_provider()
    provider = setup["provider"]
    account = create_account(provider["id"], handle="ada_lovelace",
                             email="ada@subscriber.example")
    item = create_content_item(
        account["id"],
        content_url="https://northstar.example/v/1",
        title="Clip One",
        fingerprint_hash=CONTENT_FINGERPRINT,
    )
    holder = create_enrolled_rights_holder(
        "VERIFIED",
        legal_name="Orbit Records LLC",
        contact_email="legal@orbit.example",
    )
    reference = create_active_reference_file(
        holder["id"],
        work_title="Orbit Vol. 1, track 3",
        fingerprint_hash=REFERENCE_FINGERPRINT,
        registration_number="SR0000991122",
    )
    notice = create_validated_notice(holder["id"], [item["content_url"]])

    validate_success(api.process_notice(notice["id"], AGENT))

    claims, meta = list_claims(AGENT, {"notice_id": notice["id"]})
    assert meta["total_count"] == 1
    claim = claims[0]
    assert_claim(claim)
    # 30 shared leading characters of 32: 30 / 32 * 0.80 + 0.20 == 0.9500,
    # which meets the VERIFIED acceptance floor of 0.95.
    assert round(float(claim["match_confidence"]), 4) == 0.95
    assert claim["reference_file_id"] == reference["id"]
    assert claim["matched_url"] == "https://northstar.example/v/1"
    assert claim["content_item_id"] == item["id"]
    assert claim["dispute_window_days"] == 30
    assert claim["counter_notice_window_days"] == 30

    stored_reference = validate_success(
        api.get_reference_file(reference["id"], OFFICER)
    )
    assert stored_reference["match_count"] == 1

    # VERIFIED weight 1.5 on the base of 10 points.
    assert float(get_account(account["id"])["strike_points"]) == 15.0

    by_reference, reference_meta = list_claims(
        AGENT, {"reference_file_id": reference["id"]}
    )
    assert reference_meta["total_count"] == 1
    assert by_reference[0]["id"] == claim["id"]


def test_uploaded_content_item_system_fields_are_server_minted(api):
    """PRD §2.4: "Every stored record carries an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits."

    Design: Corner/entities/content_item_system_fields_are_server_minted
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    account = create_account(provider["id"], handle="ada_lovelace",
                             email="ada@subscriber.example")

    response = api.create_content_item(
        create_content_item_payload(
            account["id"],
            content_url="https://northstar.example/v/1",
            title="Clip One",
            fingerprint_hash=CONTENT_FINGERPRINT,
        ),
        make_subscriber_headers(account["id"]),
    )
    item = validate_success(response, expected_status=201)

    assert_content_item(item)
    assert_common_fields(item)
    assert not item["id"].startswith("item_")
    assert_instant_equals(item["created_at"], CLOCK_START_ISO, "item created_at")
    assert_instant_equals(item["updated_at"], CLOCK_START_ISO, "item updated_at")
    assert item["version"] == 1
    assert item["availability_status"] == "AVAILABLE"
    assert item["dispute_status"] == "NONE"
    assert item["disabled_at"] is None
    assert item["restored_at"] is None
    assert get_account(account["id"])["available_content_count"] == 1


def test_short_fingerprint_and_out_of_range_channel_are_both_malformed(api):
    """PRD §2.6: "Required fields present, enum values in range, `fingerprint_hash` exactly 32 characters drawn from the lowercase hexadecimal alphabet, `claimed_urls` holding between 1 and 25 entries with none of them empty, `limit` between 1 and 100, `offset` not negative, and `limitation_threshold_points` strictly below `termination_threshold_points`."

    Design: Corner/entities/malformed_fingerprint_and_out_of_range_enum_are_rejected
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    account = create_account(provider["id"], handle="ada_lovelace",
                             email="ada@subscriber.example")
    holder = create_rights_holder(contact_email="legal@orbit.example")

    validate_error(
        api.create_content_item(
            create_content_item_payload(
                account["id"],
                content_url="https://northstar.example/v/1",
                title="Clip One",
                fingerprint_hash="0123456789abcdef0123456789abcde",
            ),
            make_subscriber_headers(account["id"]),
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        api.create_notice(
            create_notice_payload(
                holder["id"],
                ["https://northstar.example/v/1"],
                submission_channel="FAX",
            ),
            AGENT,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, item_meta = list_account_content_items(account["id"])
    assert item_meta["total_count"] == 0

    _, notice_meta = validate_paginated(
        api.list_notices(OFFICER, {"rights_holder_id": holder["id"]})
    )
    assert notice_meta["total_count"] == 0


def test_safe_harbor_audits_append_immutable_records_without_a_version(api):
    """PRD §2.4: "There is one exception: a `SafeHarborAudit` is an immutable evidentiary record and carries only `id` and `created_at` — both `updated_at` and `version` are absent from it entirely."

    Design: Corner/entities/safe_harbor_audit_is_append_only_with_no_version_field
    """
    setup = setup_documented_provider()
    provider_id = setup["provider"]["id"]

    first = validate_success(
        api.create_safe_harbor_audit(provider_id, OFFICER), expected_status=201
    )
    set_clock("2026-08-02T00:00:00Z")
    second = validate_success(
        api.create_safe_harbor_audit(provider_id, OFFICER), expected_status=201
    )

    assert_safe_harbor_audit(first)
    assert_safe_harbor_audit(second)
    assert first["id"] != second["id"]
    assert_instant_equals(first["created_at"], CLOCK_START_ISO, "first audit created_at")
    assert_instant_equals(second["created_at"], "2026-08-02T00:00:00Z",
                          "second audit created_at")

    assert first["gate_failure_reason"] is None
    assert float(first["response_component"]) == 40.0
    assert float(first["restoration_component"]) == 30.0
    assert float(first["termination_component"]) == 20.0
    assert float(first["contact_component"]) == 10.0
    assert first["compliance_score"] == 100
    assert first["resulting_status"] == "ELIGIBLE"

    audits, meta = list_provider_audits(provider_id)
    assert meta["total_count"] == 2
    assert _ids(audits) == [first["id"], second["id"]]

    provider = get_provider(provider_id)
    assert_instant_equals(provider["last_audit_at"], "2026-08-02T00:00:00Z",
                          "provider last_audit_at")


def test_drafting_an_agent_for_an_unknown_provider_returns_provider_not_found(api):
    """PRD §2.5: "When a creation payload names a parent that does not exist — `provider_id`, `account_id`, `rights_holder_id`, `claim_id` or `ingestion_batch_id`, and equally an identifier supplied as a list filter — the matching not-found code from the list above is returned with HTTP 404."

    Design: Corner/entities/create_designated_agent_under_unknown_provider_returns_provider_not_found
    """
    set_clock(CLOCK_START_ISO)

    validate_error(
        api.create_designated_agent(
            create_designated_agent_payload(
                NON_EXISTENT_UUID,
                agent_name="Dana Reyes",
                agent_email="dmca@northstar.example",
                agent_phone="+1-555-0100",
                mailing_address="1 Harbor Way, Springfield, IL 62701",
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_PROVIDER_NOT_FOUND.value,
    )

    _, meta = validate_paginated(api.list_providers(OFFICER))
    assert meta["total_count"] == 0


def test_cascade_created_claim_links_all_three_parents_and_no_reference_file(api):
    """PRD §3.6: "The claim records the `notice_id` of the notice that produced it, the `content_item_id` of the material it targets, a denormalised `rights_holder_id` for the complainant — which together with the content item forms the interval key just described — and the `matched_url`, which is the `claimed_urls` entry this claim resolved."

    Design: Corner/entities/notice_claim_is_a_junction_reachable_from_both_parents
    """
    setup = setup_documented_provider()
    provider = setup["provider"]
    account = create_account(provider["id"], handle="ada_lovelace",
                             email="ada@subscriber.example")
    item = create_content_item(
        account["id"],
        content_url="https://northstar.example/v/1",
        title="Clip One",
        fingerprint_hash=CONTENT_FINGERPRINT,
    )
    holder = create_rights_holder(
        legal_name="Orbit Records LLC",
        contact_email="legal@orbit.example",
    )
    notice = create_validated_notice(holder["id"], [item["content_url"]])

    validate_success(api.process_notice(notice["id"], AGENT))

    by_item, item_meta = list_claims(AGENT, {"content_item_id": item["id"]})
    by_holder, holder_meta = list_claims(AGENT, {"rights_holder_id": holder["id"]})

    assert item_meta["total_count"] == 1
    assert holder_meta["total_count"] == 1
    assert by_item[0]["id"] == by_holder[0]["id"]

    claim = by_item[0]
    assert_common_fields(claim)
    assert claim["notice_id"] == notice["id"]
    assert claim["content_item_id"] == item["id"]
    assert claim["rights_holder_id"] == holder["id"]
    assert claim["matched_url"] == "https://northstar.example/v/1"
    assert claim["reference_file_id"] is None
    assert claim["match_confidence"] is None
    assert claim["status"] == "DISABLED"


def test_provider_and_rights_holder_filters_intersect_before_pagination(api):
    """PRD §2.3: "When several filters are supplied on the same request they intersect."

    Design: Corner/entities/root_collections_combine_their_filters_with_pagination
    """
    documented = setup_documented_provider()
    provider_one = documented["provider"]
    assert provider_one["safe_harbor_status"] == "ELIGIBLE"

    set_clock(shift_iso(CLOCK_START_ISO, hours=1))
    provider_two = create_provider(legal_name="Southshore Media Inc",
                                   service_domain="southshore.example")
    set_clock(shift_iso(CLOCK_START_ISO, hours=2))
    provider_three = create_provider(legal_name="Ridgeline Video Ltd",
                                     service_domain="ridgeline.example")
    assert provider_two["safe_harbor_status"] == "FORFEITED"
    assert provider_three["safe_harbor_status"] == "FORFEITED"

    set_clock(shift_iso(CLOCK_START_ISO, hours=3))
    holder_a = create_rights_holder(legal_name="Orbit Records LLC",
                                    contact_email="legal@orbit.example")
    enroll_rights_holder(holder_a["id"])
    set_clock(shift_iso(CLOCK_START_ISO, hours=4))
    holder_b = create_rights_holder(legal_name="Vantage Pictures LLC",
                                    contact_email="legal@vantage.example",
                                    reference_file_quota=5,
                                    daily_item_quota=100)
    enroll_rights_holder(holder_b["id"])
    promote_tier(holder_b["id"])
    set_clock(shift_iso(CLOCK_START_ISO, hours=5))
    holder_c = create_rights_holder(legal_name="Harborlight Music Co",
                                    contact_email="legal@harborlight.example")

    versions_before = {
        provider_one["id"]: get_provider(provider_one["id"])["version"],
        provider_two["id"]: get_provider(provider_two["id"])["version"],
        holder_a["id"]: get_rights_holder(holder_a["id"])["version"],
        holder_b["id"]: get_rights_holder(holder_b["id"])["version"],
    }

    all_providers_response = api.list_providers(AGENT)
    all_providers, all_meta = validate_paginated(all_providers_response)
    assert _response_type(all_providers_response) == "array"
    assert all_meta["total_count"] == 3
    assert all_meta["has_more"] is False
    assert _ids(all_providers) == [provider_one["id"], provider_two["id"],
                                   provider_three["id"]]

    forfeited, forfeited_meta = validate_paginated(
        api.list_providers(INVESTIGATOR, {"safe_harbor_status": "FORFEITED"})
    )
    assert forfeited_meta["total_count"] == 2
    assert _ids(forfeited) == [provider_two["id"], provider_three["id"]]

    first_page, first_meta = validate_paginated(
        api.list_providers(OFFICER, {"limit": 2, "offset": 0})
    )
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(first_page) == 2

    last_page, last_meta = validate_paginated(
        api.list_providers(OFFICER, {"limit": 2, "offset": 2})
    )
    assert last_meta["total_count"] == 3
    assert last_meta["has_more"] is False
    assert _ids(last_page) == [provider_three["id"]]

    enrolled, enrolled_meta = validate_paginated(
        api.list_rights_holders(AGENT, {"enrollment_status": "ENROLLED"})
    )
    assert enrolled_meta["total_count"] == 2
    assert _ids(enrolled) == [holder_a["id"], holder_b["id"]]

    intersected, intersected_meta = validate_paginated(
        api.list_rights_holders(
            INVESTIGATOR,
            {"enrollment_status": "ENROLLED", "program_tier": "STANDARD"},
        )
    )
    assert intersected_meta["total_count"] == 1
    assert _ids(intersected) == [holder_a["id"]]

    standard, standard_meta = validate_paginated(
        api.list_rights_holders(OFFICER, {"program_tier": "STANDARD"})
    )
    assert standard_meta["total_count"] == 2
    assert _ids(standard) == [holder_a["id"], holder_c["id"]]

    stored_holder_b = get_rights_holder(holder_b["id"])
    assert stored_holder_b["reference_file_quota"] == 5
    assert stored_holder_b["daily_item_quota"] == 100
    assert stored_holder_b["program_tier"] == "VERIFIED"

    assert get_provider(provider_one["id"])["version"] == \
        versions_before[provider_one["id"]]
    assert get_provider(provider_two["id"])["version"] == \
        versions_before[provider_two["id"]]
    assert get_rights_holder(holder_a["id"])["version"] == \
        versions_before[holder_a["id"]]
    assert get_rights_holder(holder_b["id"])["version"] == \
        versions_before[holder_b["id"]]
