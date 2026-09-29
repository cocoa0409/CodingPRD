"""Validation-rule and endpoint-contract corner cases.

Every test builds its own world through the public API: the server is
restarted (and the database emptied) before each individual test, so nothing
is shared between them.
"""
from test_helpers import (
    AGENT,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    OFFICER,
    TEST_DEFAULTS,
    ApiErrorId,
    assert_account,
    assert_claim,
    assert_content_item,
    assert_counter_notice,
    assert_instant_equals,
    assert_reference_file,
    assert_rights_holder,
    claims_of_notice,
    create_account,
    create_content_item,
    create_content_item_payload,
    create_counter_notice,
    create_counter_notice_payload,
    create_draft_policy,
    create_enrolled_rights_holder,
    create_notice,
    create_processed_notice,
    create_provider,
    create_reference_file,
    create_reference_file_payload,
    create_rights_holder,
    create_validated_notice,
    activate_reference_file,
    enroll_rights_holder,
    get_account,
    get_claim,
    get_content_item,
    get_counter_notice,
    get_notice,
    get_rights_holder,
    list_account_content_items,
    list_account_strikes,
    list_claims,
    make_abuse_investigator_headers,
    make_rights_holder_rep_headers,
    make_subscriber_headers,
    publish_policy,
    set_clock,
    setup_disabled_claim,
    setup_documented_provider,
    setup_provider_with_agent,
    strike_summary,
    validate_counter_notice,
    validate_error,
    validate_notice,
    validate_paginated,
    validate_success,
)

# The item fingerprint and the reference-file fingerprint below share their
# first 30 characters: 30 / 32 * 0.80 + 0.20 (a registration number is
# present) == 0.95, exactly the acceptance floor of a VERIFIED holder.
_ITEM_FINGERPRINT = TEST_DEFAULTS["CONTENT_FINGERPRINT"]
_REFERENCE_FINGERPRINT = "0123456789abcdef0123456789abcd00"


def _claim_for_item(claims, item_id):
    """The single claim of a notice that targets one particular content item."""
    matches = [claim for claim in claims if claim["content_item_id"] == item_id]
    assert len(matches) == 1, f"expected exactly one claim against {item_id}"
    return matches[0]


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------

def test_second_upload_of_the_same_content_url_conflicts(api):
    """PRD §3.2: "The URL must be unique across all accounts of the same provider; a collision is refused with `ERR_CONTENT_URL_CONFLICT`."

    Design: Corner/validations/second_content_item_with_the_same_url_hits_the_url_conflict
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_provider()
    account = create_account(provider["id"], handle="ada_lovelace",
                             email="ada@subscriber.example")
    item = create_content_item(
        account["id"],
        content_url="https://northstar.example/v/1",
        title="Clip One",
        fingerprint_hash=_ITEM_FINGERPRINT,
    )

    duplicate = api.create_content_item(
        create_content_item_payload(
            account["id"],
            content_url="https://northstar.example/v/1",
            title="Clip One Reupload",
            fingerprint_hash="44444444444444444444444444444444",
        ),
        make_subscriber_headers(account["id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_CONTENT_URL_CONFLICT.value)

    items, meta = list_account_content_items(account["id"])
    assert meta["total_count"] == 1, "the refused upload must not be stored"
    assert len(items) == 1

    reread_account = get_account(account["id"])
    assert_account(reread_account)
    assert reread_account["available_content_count"] == 1

    stored = get_content_item(item["id"])
    assert_content_item(stored)
    assert stored["title"] == "Clip One"
    assert stored["fingerprint_hash"] == _ITEM_FINGERPRINT


def test_counter_notice_on_the_last_day_of_the_window_is_accepted(api):
    """PRD §3.7: "The counter-notice must arrive no later than the claim's `disabled_at` advanced by the claim's snapshotted `counter_notice_window_days`; a later submission is refused with `ERR_COUNTER_NOTICE_WINDOW_CLOSED`."

    Design: Corner/validations/counter_notice_on_the_last_day_of_the_window_is_accepted
    """
    scene = setup_disabled_claim()
    account, claim = scene["account"], scene["claim"]
    assert claim["counter_notice_window_days"] == 30

    # disabled_at 2026-08-01 plus the snapshotted 30-day window lands exactly
    # on 2026-08-31T00:00:00Z, which is still inside the window.
    set_clock("2026-08-31T00:00:00Z")
    accepted = api.create_counter_notice(
        create_counter_notice_payload(claim["id"], get_claim(claim["id"])["version"]),
        make_subscriber_headers(account["id"]),
    )
    counter = validate_success(accepted, expected_status=201)
    assert_counter_notice(counter)
    assert counter["status"] == "RECEIVED"
    assert counter["completeness_score"] == 0
    assert counter["claim_id"] == claim["id"]
    assert counter["account_id"] == account["id"]
    assert get_claim(claim["id"])["status"] == "DISABLED", (
        "creating a counter-notice alone does not move the claim"
    )

    set_clock("2026-08-31T00:00:00.001Z")
    too_late = api.create_counter_notice(
        create_counter_notice_payload(claim["id"], get_claim(claim["id"])["version"]),
        make_subscriber_headers(account["id"]),
    )
    validate_error(too_late, ApiErrorId.ERR_COUNTER_NOTICE_WINDOW_CLOSED.value)


def test_missing_role_header_outranks_every_later_rung(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of those five spellings, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_x_user_role_header_returns_unauthenticated
    """
    set_clock("2026-08-01T00:00:00Z")

    # The payload is simultaneously malformed (no agent_email / agent_phone /
    # mailing_address) and points at a provider that does not exist.
    unauthenticated = api.create_designated_agent(
        {"provider_id": NON_EXISTENT_UUID, "agent_name": "Dana Reyes"},
        NO_AUTH_HEADERS,
    )
    validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED.value)

    providers, meta = validate_paginated(api.list_providers(OFFICER))
    assert meta["total_count"] == 0, "the refused request must not create anything"
    assert providers == []


def test_restore_one_millisecond_before_the_due_instant_is_too_early(api):
    """PRD §3.7: "The logical clock must be at or after the claim's `restoration_due_at`, and an earlier attempt is refused with `ERR_RESTORATION_TOO_EARLY`."

    Design: Corner/validations/restore_one_millisecond_before_the_due_instant_is_too_early
    """
    scene = setup_disabled_claim()
    account, item, claim = scene["account"], scene["item"], scene["claim"]

    counter = create_counter_notice(claim["id"], account["id"])
    validate_counter_notice(counter["id"])
    forwarded = validate_success(api.forward_counter_notice(counter["id"], AGENT))
    # Ten business days after the 2026-08-01 (Saturday) forward instant.
    assert_instant_equals(forwarded["restoration_earliest_at"],
                          "2026-08-14T00:00:00Z", "restoration_earliest_at")
    assert_instant_equals(get_claim(claim["id"])["restoration_due_at"],
                          "2026-08-14T00:00:00Z", "restoration_due_at")

    set_clock("2026-08-13T23:59:59.999Z")
    too_early = api.restore_claim(claim["id"], AGENT)
    validate_error(too_early, ApiErrorId.ERR_RESTORATION_TOO_EARLY.value)

    blocked_claim = get_claim(claim["id"])
    assert_claim(blocked_claim)
    assert blocked_claim["status"] == "RESTORATION_SCHEDULED"
    assert_instant_equals(blocked_claim["restoration_due_at"],
                          "2026-08-14T00:00:00Z", "restoration_due_at")

    still_disabled = get_content_item(item["id"])
    assert still_disabled["availability_status"] == "DISABLED"
    assert still_disabled["restored_at"] is None

    unchanged_account = get_account(account["id"])
    assert unchanged_account["available_content_count"] == 0
    assert float(unchanged_account["strike_points"]) == 10.00

    set_clock("2026-08-14T00:00:00Z")
    restored = validate_success(api.restore_claim(claim["id"], AGENT))
    assert restored["status"] == "RESTORED"


def test_process_requires_a_published_repeat_infringer_policy(api):
    """PRD §3.6: "Two preconditions are checked before any claim is created: the owning provider must hold a policy revision in `PUBLISHED`, or the request is refused with `ERR_REPEAT_INFRINGER_POLICY_NOT_PUBLISHED`; and at least one entry in `claimed_urls` must resolve to a content item whose `availability_status` is `AVAILABLE` or `RESTORED` and whose dispute interval is free."

    Design: Corner/validations/process_needs_a_published_policy_and_succeeds_once_published
    """
    setup = setup_provider_with_agent()
    provider = setup["provider"]
    policy = create_draft_policy(provider["id"], dispute_window_days=45,
                                 counter_notice_window_days=21)
    assert policy["status"] == "DRAFT"

    account = create_account(provider["id"])
    item = create_content_item(account["id"])
    holder = create_enrolled_rights_holder()
    notice = create_validated_notice(holder["id"], [item["content_url"]])
    assert notice["status"] == "VALIDATED"

    refused = api.process_notice(notice["id"], AGENT)
    validate_error(refused, ApiErrorId.ERR_REPEAT_INFRINGER_POLICY_NOT_PUBLISHED.value)
    assert get_notice(notice["id"])["status"] == "VALIDATED"
    _, meta = list_claims(params={"notice_id": notice["id"]})
    assert meta["total_count"] == 0, "a refused process must not create claims"

    publish_policy(policy["id"], provider["id"])

    processed = validate_success(api.process_notice(notice["id"], AGENT))
    assert processed["status"] == "PROCESSED"

    claims, claims_meta = list_claims(params={"notice_id": notice["id"]})
    assert claims_meta["total_count"] == 1
    claim = claims[0]
    assert_claim(claim)
    assert claim["dispute_window_days"] == 45
    assert claim["counter_notice_window_days"] == 21

    disabled_item = get_content_item(item["id"])
    assert disabled_item["availability_status"] == "DISABLED"
    assert disabled_item["dispute_status"] == "UNDER_NOTICE"
    assert float(get_account(account["id"])["strike_points"]) == 10.00


def test_promote_tier_at_abuse_score_exactly_forty_is_refused(api):
    """PRD §3.3: "Both steps require `enrollment_status` to be `ENROLLED`, refused otherwise with `ERR_RIGHTS_HOLDER_NOT_ENROLLED`, and an `abuse_score` below 40, refused otherwise with `ERR_ABUSE_SCORE_TOO_HIGH`."

    Design: Corner/validations/promote_tier_at_abuse_score_forty_is_refused
    """
    setup = setup_documented_provider()
    account = create_account(setup["provider"]["id"])
    item = create_content_item(account["id"])
    holder = create_enrolled_rights_holder()

    create_processed_notice(holder["id"], [item["content_url"]])
    # A notice missing its material identification fails the core-element gate
    # and is rejected, so rejected_count reaches 1 against notices_processed 1:
    # (0 * 1 + 1 * 2 + 0 * 3) / max(1, 5) * 100 == 40.00.
    rejected = create_notice(holder["id"], [item["content_url"]],
                             material_identification=None)
    rejected = validate_notice(rejected["id"])
    assert rejected["status"] == "REJECTED"

    before = get_rights_holder(holder["id"])
    assert_rights_holder(before)
    assert float(before["abuse_score"]) == 40.00
    assert before["enrollment_status"] == "ENROLLED"
    assert before["program_tier"] == "STANDARD"

    refused = api.promote_rights_holder_tier(holder["id"], OFFICER)
    validate_error(refused, ApiErrorId.ERR_ABUSE_SCORE_TOO_HIGH.value)

    after = get_rights_holder(holder["id"])
    assert after["program_tier"] == "STANDARD"
    assert after["enrollment_status"] == "ENROLLED"


def test_reference_quota_counts_pending_and_active_files_together(api):
    """PRD §3.3: "A new file enters `status` `PENDING` with `activated_at` null and `match_count` 0, and it counts against the allowance immediately: if registering it would push the count of the holder's files in `PENDING` or `ACTIVE` above `reference_file_quota`, the request is refused with `ERR_REFERENCE_QUOTA_EXCEEDED`."

    Design: Corner/validations/third_reference_file_exceeds_a_quota_counted_over_pending_plus_active
    """
    set_clock("2026-08-01T00:00:00Z")
    create_provider()
    holder = create_rights_holder(reference_file_quota=2)
    enroll_rights_holder(holder["id"])

    file_a = create_reference_file(holder["id"], work_title="Orbit Vol. 1, track 3",
                                   fingerprint_hash=_REFERENCE_FINGERPRINT,
                                   registration_number="SR0000991122")
    activate_reference_file(file_a["id"], holder["id"])
    file_b = create_reference_file(holder["id"], work_title="Orbit Vol. 1, track 4",
                                   fingerprint_hash="11111111111111111111111111111111")

    over_quota = api.create_reference_file(
        create_reference_file_payload(
            holder["id"],
            work_title="Orbit Vol. 1, track 5",
            fingerprint_hash="22222222222222222222222222222222",
        ),
        make_rights_holder_rep_headers(holder["id"]),
    )
    validate_error(over_quota, ApiErrorId.ERR_REFERENCE_QUOTA_EXCEEDED.value)

    files, meta = validate_paginated(
        api.list_rights_holder_reference_files(holder["id"], OFFICER)
    )
    assert meta["total_count"] == 2
    assert len(files) == 2
    for stored in files:
        assert_reference_file(stored)

    assert validate_success(
        api.get_reference_file(file_a["id"], OFFICER)
    )["status"] == "ACTIVE"
    assert validate_success(
        api.get_reference_file(file_b["id"], OFFICER)
    )["status"] == "PENDING"
    assert get_rights_holder(holder["id"])["reference_file_quota"] == 2


# ---------------------------------------------------------------------------
# Endpoint contracts
# ---------------------------------------------------------------------------

def test_account_create_read_and_list_agree(api):
    """PRD §3.2: "A new account starts with `standing` `ACTIVE`, `strike_points` 0, `upload_restricted` false, `notified_count` 0, `available_content_count` 0 and `terminated_at` null."

    Design: Corner/endpoints/account_create_read_and_list_round_trip
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_provider()
    first = create_account(provider["id"], handle="ada_lovelace",
                           email="ada@subscriber.example")
    second = create_account(provider["id"], handle="grace_hopper",
                            email="grace@subscriber.example")

    read = validate_success(api.get_account(first["id"], OFFICER))
    assert_account(read)
    assert read["handle"] == "ada_lovelace"
    assert read["standing"] == "ACTIVE"
    assert float(read["strike_points"]) == 0
    assert read["upload_restricted"] is False
    assert read["notified_count"] == 0
    assert read["available_content_count"] == 0
    assert read["terminated_at"] is None
    assert read["version"] == 1

    response = api.list_accounts(AGENT, {"provider_id": provider["id"],
                                         "standing": "ACTIVE"})
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [first["id"], second["id"]], (
        "rows come back in ascending created_at order"
    )
    assert [row["created_at"] for row in rows] == sorted(
        row["created_at"] for row in rows
    )
    assert set(rows[0].keys()) == set(read.keys()), (
        "list rows carry the same field set as the single read"
    )

    _, terminated_meta = validate_paginated(
        api.list_accounts(AGENT, {"provider_id": provider["id"],
                                  "standing": "TERMINATED"})
    )
    assert terminated_meta["total_count"] == 0


def test_suspending_a_holder_quarantines_active_files_and_withdraws_their_claims(api):
    """PRD §3.3: "Every reference file of the holder that sits in `ACTIVE` moves `ACTIVE → QUARANTINED`; files still in `PENDING` are left untouched."

    Design: Corner/endpoints/suspend_rights_holder_quarantines_active_files_and_withdraws_their_claims
    """
    setup = setup_documented_provider()
    account = create_account(setup["provider"]["id"])
    item = create_content_item(account["id"], fingerprint_hash=_ITEM_FINGERPRINT)
    holder = create_enrolled_rights_holder("VERIFIED")

    file_a = create_reference_file(holder["id"], work_title="Orbit Vol. 1, track 3",
                                   fingerprint_hash=_REFERENCE_FINGERPRINT,
                                   registration_number="SR0000991122")
    activate_reference_file(file_a["id"], holder["id"])
    file_b = create_reference_file(holder["id"], work_title="Orbit Vol. 1, track 4",
                                   fingerprint_hash="11111111111111111111111111111111")

    notice = create_processed_notice(holder["id"], [item["content_url"]])
    claim = claims_of_notice(notice["id"])[0]
    assert claim["reference_file_id"] == file_a["id"]
    assert float(claim["match_confidence"]) == 0.95

    suspended = validate_success(
        api.suspend_rights_holder(holder["id"], make_abuse_investigator_headers("inv-1"))
    )
    assert_rights_holder(suspended)
    assert suspended["enrollment_status"] == "SUSPENDED"
    assert float(suspended["abuse_score"]) == 0.00, "suspension is not a penalty path"
    assert suspended["misrepresentation_count"] == 0
    assert suspended["program_tier"] == "VERIFIED", "suspension does not step the tier"

    assert validate_success(
        api.get_reference_file(file_a["id"], OFFICER)
    )["status"] == "QUARANTINED"
    assert validate_success(
        api.get_reference_file(file_b["id"], OFFICER)
    )["status"] == "PENDING"

    assert get_claim(claim["id"])["status"] == "WITHDRAWN"

    restored_item = get_content_item(item["id"])
    assert restored_item["availability_status"] == "RESTORED"
    assert restored_item["dispute_status"] == "RESOLVED"

    reread_account = get_account(account["id"])
    assert reread_account["available_content_count"] == 1
    assert float(reread_account["strike_points"]) == 0.00

    _, voided_meta = list_account_strikes(account["id"], params={"status": "VOIDED"})
    assert voided_meta["total_count"] == 1

    assert get_notice(notice["id"])["status"] == "CLOSED"


def test_strike_summary_read_reconciles_with_the_account_fields(api):
    """PRD §3.2: "There is in addition a computed strike-accounting read on an account that returns, under the pinned point variant, the `account_id`, the current `strike_points`, the `active_strike_count`, `decayed_strike_count`, `expired_strike_count` and `voided_strike_count` breakdown of its strike records, the `limitation_threshold_points` and `termination_threshold_points` currently in force from the published policy, and the account's `standing`."

    Design: Corner/endpoints/strike_summary_read_reconciles_with_the_account_fields
    """
    setup = setup_documented_provider()
    account = create_account(setup["provider"]["id"])
    items = [create_content_item(account["id"]) for _ in range(3)]
    holder = create_enrolled_rights_holder()

    first_notice = create_processed_notice(
        holder["id"], [items[0]["content_url"], items[1]["content_url"]]
    )

    # 90 days on: both strikes sit at decay step 1, so 10 * 1.0 * 0.65 each.
    set_clock("2026-10-30T00:00:00Z")
    create_processed_notice(holder["id"], [items[2]["content_url"]])

    withdrawn = validate_success(
        api.withdraw_notice(first_notice["id"],
                            make_rights_holder_rep_headers(holder["id"]))
    )
    assert withdrawn["status"] == "WITHDRAWN"

    before = get_account(account["id"])
    summary = strike_summary(account["id"], AGENT)
    after = get_account(account["id"])

    assert summary["account_id"] == account["id"]
    assert float(summary["strike_points"]) == 10.00
    assert float(summary["strike_points"]) == float(after["strike_points"])
    assert summary["active_strike_count"] == 1
    assert summary["decayed_strike_count"] == 0
    assert summary["voided_strike_count"] == 2
    assert summary["expired_strike_count"] == 0

    _, strike_meta = list_account_strikes(account["id"])
    total_counted = (summary["active_strike_count"] + summary["decayed_strike_count"]
                     + summary["voided_strike_count"] + summary["expired_strike_count"])
    assert total_counted == 3 == strike_meta["total_count"]

    assert summary["limitation_threshold_points"] == 20
    assert summary["termination_threshold_points"] == 40
    assert summary["standing"] == "ACTIVE"
    assert summary["standing"] == after["standing"]
    assert after["version"] == before["version"], "the computed read mutates nothing"


def test_purge_decrements_the_counter_only_for_live_material(api):
    """PRD §3.2: "Purging an item that is already `PURGED`, or purging a disabled item that has a counter-noticed or restoration-scheduled claim against it, is refused with `ERR_INVALID_CONTENT_STATE`."

    Design: Corner/endpoints/purge_decrements_the_counter_only_for_available_or_restored_items
    """
    setup = setup_documented_provider()
    account = create_account(setup["provider"]["id"])
    items = [create_content_item(account["id"]) for _ in range(3)]
    holder = create_enrolled_rights_holder()

    notice = create_processed_notice(
        holder["id"], [items[0]["content_url"], items[1]["content_url"]]
    )
    claims = claims_of_notice(notice["id"])
    first_claim = _claim_for_item(claims, items[0]["id"])

    counter = create_counter_notice(first_claim["id"], account["id"])
    validate_counter_notice(counter["id"])
    assert get_content_item(items[0]["id"])["dispute_status"] == "COUNTER_NOTICED"
    assert get_account(account["id"])["available_content_count"] == 1

    purged_live = validate_success(
        api.purge_content_item(items[2]["id"], make_subscriber_headers(account["id"]))
    )
    assert_content_item(purged_live)
    assert purged_live["availability_status"] == "PURGED"
    assert get_account(account["id"])["available_content_count"] == 0

    purged_disabled = validate_success(api.purge_content_item(items[1]["id"], OFFICER))
    assert purged_disabled["availability_status"] == "PURGED"
    assert get_account(account["id"])["available_content_count"] == 0, (
        "a disabled item was already excluded from the live count"
    )
    assert get_content_item(items[1]["id"])["dispute_status"] == "UNDER_NOTICE", (
        "purging touches only the access dimension"
    )

    refused = api.purge_content_item(items[0]["id"], OFFICER)
    validate_error(refused, ApiErrorId.ERR_INVALID_CONTENT_STATE.value)
    disputed = get_content_item(items[0]["id"])
    assert disputed["availability_status"] == "DISABLED"
    assert disputed["dispute_status"] == "COUNTER_NOTICED"

    final_account = get_account(account["id"])
    assert final_account["available_content_count"] == 0
    assert float(final_account["strike_points"]) == 20.00, "purging voids no strike"


def test_later_counter_notice_supersedes_the_earlier_one(api):
    """PRD §3.7: "If the earlier counter-notice had already reached `VALIDATED`, it moves `VALIDATED → SUPERSEDED`, its `superseded_by_counter_notice_id` is set the same way, **and** the claim is returned from `COUNTER_NOTICED` to `DISABLED` so that the newer counter-notice can itself be validated."

    Design: Corner/endpoints/later_counter_notice_supersedes_the_earlier_one_and_returns_the_claim_to_disabled
    """
    scene = setup_disabled_claim()
    account, claim = scene["account"], scene["claim"]

    first = create_counter_notice(claim["id"], account["id"])
    validate_counter_notice(first["id"])
    assert get_claim(claim["id"])["status"] == "COUNTER_NOTICED"

    current_claim_version = get_claim(claim["id"])["version"]
    assert current_claim_version != claim["version"], (
        "validating the first counter-notice advanced the claim"
    )

    created = api.create_counter_notice(
        create_counter_notice_payload(
            claim["id"], current_claim_version,
            material_identification="Clip One at /v/1 - corrected statement",
        ),
        make_subscriber_headers(account["id"]),
    )
    second = validate_success(created, expected_status=201)
    assert_counter_notice(second)

    superseded = get_counter_notice(first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_counter_notice_id"] == second["id"]
    assert second["superseded_by_counter_notice_id"] is None
    assert get_claim(claim["id"])["status"] == "DISABLED", (
        "the claim is rewound so the newer counter-notice can be validated"
    )

    validated = validate_counter_notice(second["id"])
    assert validated["status"] == "VALIDATED"
    assert validated["completeness_score"] == 100
    assert get_claim(claim["id"])["status"] == "COUNTER_NOTICED"

    rows, meta = validate_paginated(
        api.list_counter_notices(AGENT, {"claim_id": claim["id"]})
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], second["id"]]

    linked, linked_meta = validate_paginated(
        api.list_counter_notices(AGENT,
                                 {"superseded_by_counter_notice_id": second["id"]})
    )
    assert linked_meta["total_count"] == 1
    assert linked[0]["id"] == first["id"]

    stale_forward = api.forward_counter_notice(first["id"], AGENT)
    validate_error(stale_forward, ApiErrorId.ERR_INVALID_COUNTER_NOTICE_STATE.value)
