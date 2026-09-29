"""Deep cascade fan-outs, rejection-ladder precedence and threshold boundaries.

Every scene is built from scratch through the public API: the server is
relaunched against an empty database before each test.
"""
from test_helpers import (
    AGENT,
    INVESTIGATOR,
    OFFICER,
    ApiErrorId,
    assert_instant_equals,
    claims_of_notice,
    create_account,
    create_active_reference_file,
    create_content_item,
    create_counter_notice_payload,
    create_enrolled_rights_holder,
    create_ingestion_batch_payload,
    create_misrepresentation_case,
    create_notice,
    create_processed_notice,
    create_rights_holder,
    create_validated_notice,
    enroll_rights_holder,
    execute_termination_case,
    get_account,
    get_claim,
    get_content_item,
    get_notice,
    get_provider,
    get_rights_holder,
    list_account_strikes,
    make_abuse_investigator_headers,
    make_rights_holder_rep_headers,
    make_subscriber_headers,
    promote_tier,
    set_clock,
    setup_account_with_items,
    setup_documented_provider,
    setup_provider_with_agent,
    validate_error,
    validate_paginated,
    validate_success,
)

# A 32-character lowercase hexadecimal fingerprint shared by a piece of hosted
# material and a rights holder's reference work, so the match is exact.
_SHARED_FINGERPRINT = "0123456789abcdef0123456789abcdef"
_ABSENT_URL = "https://northstar.example/v/absent"


def _documented_scene(item_count: int = 1):
    """Fully documented provider, one account with `item_count` AVAILABLE items,
    and one STANDARD-tier complaining rights holder."""
    setup = setup_documented_provider()
    provider = setup["provider"]
    scene = setup_account_with_items(provider["id"], item_count)
    holder = create_rights_holder()
    return provider, scene["account"], scene["items"], holder


def _urls(items):
    return [item["content_url"] for item in items]


def _trusted_holder_with_matching_reference():
    """ENROLLED holder walked up to TRUSTED, holding one ACTIVE reference file
    whose fingerprint is identical to `_SHARED_FINGERPRINT`."""
    holder = create_rights_holder()
    enroll_rights_holder(holder["id"])
    reference = create_active_reference_file(
        holder["id"],
        fingerprint_hash=_SHARED_FINGERPRINT,
        registration_number="SR0000991122",
    )
    promote_tier(holder["id"])
    holder = promote_tier(holder["id"])
    return holder, reference


# ---------------------------------------------------------------------------
# Processing a notice: notice -> claims -> items + strikes -> account -> case
# ---------------------------------------------------------------------------

def test_processing_a_notice_cascades_claims_items_strikes_and_termination_case(api):
    """PRD §3.6: "Every accrual recomputes the account's `strike_points` by the
    rule in Section 3.7, which may move standing `ACTIVE → LIMITED`, and a
    recomputed total that also reaches `termination_threshold_points` opens a
    termination case for that account."

    Design: Difficulty/transitive_cascade/process_notice_cascades_claim_content_strike_and_termination_case
    """
    provider, account, items, holder = _documented_scene(4)
    notice = create_validated_notice(holder["id"], _urls(items))

    processed = validate_success(api.process_notice(notice["id"], AGENT),
                                 expected_status=200)

    assert processed["status"] == "PROCESSED"
    assert processed["matched_claim_count"] == 4
    assert processed["unmatched_url_count"] == 0
    assert_instant_equals(processed["processed_at"], "2026-08-01T00:00:00Z",
                          "notice processed_at")

    claims, claims_meta = validate_paginated(
        api.list_claims(AGENT, {"notice_id": notice["id"]})
    )
    assert claims_meta["total_count"] == 4
    assert [claim["status"] for claim in claims] == ["DISABLED"] * 4
    assert [claim["matched_url"] for claim in claims] == _urls(items)

    for item in items:
        stored = get_content_item(item["id"])
        assert stored["availability_status"] == "DISABLED"
        assert stored["dispute_status"] == "UNDER_NOTICE"
        assert_instant_equals(stored["disabled_at"], "2026-08-01T00:00:00Z",
                              "content item disabled_at")

    strikes, strikes_meta = validate_paginated(
        api.list_account_strikes(account["id"], OFFICER)
    )
    assert strikes_meta["total_count"] == 4
    for strike in strikes:
        assert strike["status"] == "ACTIVE"
        assert strike["reason"] == "NOTICE_PROCESSED"
        assert float(strike["weight"]) == 1.0
        assert float(strike["base_points"]) == 10.0
        assert float(strike["effective_points"]) == 10.0

    stored_account = get_account(account["id"])
    assert stored_account["available_content_count"] == 0
    assert stored_account["notified_count"] == 4
    assert float(stored_account["strike_points"]) == 40.00
    assert stored_account["standing"] == "LIMITED"
    assert stored_account["upload_restricted"] is True

    cases, cases_meta = validate_paginated(
        api.list_account_termination_cases(account["id"], OFFICER)
    )
    assert cases_meta["total_count"] == 1
    assert cases[0]["status"] == "OPEN"
    assert float(cases[0]["trigger_points"]) == 40.00
    assert cases[0]["opened_by_user_id"] is None
    assert cases[0]["account_id"] == account["id"]

    assert get_rights_holder(holder["id"])["notices_processed"] == 1


def test_three_claim_cascade_limits_the_account_without_opening_a_case(api):
    """PRD §3.8: "`ACTIVE → LIMITED` fires as soon as a recomputation puts
    `strike_points` at or above the published policy's
    `limitation_threshold_points`, and sets `upload_restricted` to true, which is
    what blocks further uploads from that account."

    Design: Difficulty/transitive_cascade/process_notice_cascades_claim_content_strike_and_termination_case
    """
    provider, account, items, holder = _documented_scene(3)
    notice = create_validated_notice(holder["id"], _urls(items))

    processed = validate_success(api.process_notice(notice["id"], AGENT),
                                 expected_status=200)
    assert processed["matched_claim_count"] == 3

    stored_account = get_account(account["id"])
    assert float(stored_account["strike_points"]) == 30.00
    assert stored_account["standing"] == "LIMITED"
    assert stored_account["upload_restricted"] is True
    assert stored_account["available_content_count"] == 0
    assert stored_account["notified_count"] == 3

    # 30.00 sits above the limitation threshold of 20 but below the termination
    # threshold of 40, so the termination step of the cascade must not fire.
    _, cases_meta = validate_paginated(
        api.list_account_termination_cases(account["id"], OFFICER)
    )
    assert cases_meta["total_count"] == 0

    summary = validate_success(
        api.get_account_strike_summary(account["id"], OFFICER), expected_status=200
    )
    assert summary["active_strike_count"] == 3
    assert float(summary["strike_points"]) == 30.00
    assert summary["standing"] == "LIMITED"


def test_cascade_snapshots_policy_windows_onto_every_created_claim(api):
    """PRD §3.6: "The disabling transition snapshots `dispute_window_days` and
    `counter_notice_window_days` from the provider's currently `PUBLISHED` policy
    revision onto the claim itself — a later policy revision cannot retroactively
    lengthen or shorten a window already in flight — and stamps the claim's
    `disabled_at` from the logical clock, leaving `restoration_due_at` null until
    a counter-notice is forwarded."

    Design: Difficulty/transitive_cascade/process_notice_cascades_claim_content_strike_and_termination_case
    """
    provider, account, items, holder = _documented_scene(2)
    notice = create_validated_notice(holder["id"], _urls(items))

    validate_success(api.process_notice(notice["id"], AGENT), expected_status=200)

    claims = claims_of_notice(notice["id"])
    assert len(claims) == 2
    for claim, item in zip(claims, items):
        assert claim["notice_id"] == notice["id"]
        assert claim["content_item_id"] == item["id"]
        assert claim["rights_holder_id"] == holder["id"]
        assert claim["matched_url"] == item["content_url"]
        assert claim["dispute_window_days"] == 30
        assert claim["counter_notice_window_days"] == 30
        assert claim["restoration_due_at"] is None
        # No reference file of the complainant is ACTIVE, so the claim rests on
        # the URL match alone.
        assert claim["reference_file_id"] is None
        assert claim["match_confidence"] is None
        assert_instant_equals(claim["disabled_at"], "2026-08-01T00:00:00Z",
                              "claim disabled_at")

        claim_strikes, claim_strikes_meta = validate_paginated(
            api.list_claim_strikes(claim["id"], AGENT)
        )
        assert claim_strikes_meta["total_count"] == 1
        strike = claim_strikes[0]
        assert strike["claim_id"] == claim["id"]
        assert strike["account_id"] == account["id"]
        assert strike["reason"] == "NOTICE_PROCESSED"
        assert strike["status"] == "ACTIVE"
        assert_instant_equals(strike["accrued_at"], "2026-08-01T00:00:00Z",
                              "strike accrued_at")
        assert_instant_equals(strike["expires_at"], "2027-08-01T00:00:00Z",
                              "strike expires_at")


# ---------------------------------------------------------------------------
# Substantiating a misrepresentation case: holder -> reference file -> claim
# -> content item -> strike -> account -> notice
# ---------------------------------------------------------------------------

def test_substantiation_cascades_suspension_quarantine_withdrawal_and_void(api):
    """PRD §3.9: "The suspension in turn quarantines every reference file of the
    holder that is `ACTIVE`, and each quarantined file withdraws the non-terminal
    claims that had selected it, restoring their content items unless purged,
    voiding their strike records, and recomputing the affected accounts'
    `strike_points` — which may return those accounts' standing from `LIMITED` to
    `ACTIVE`."

    Design: Difficulty/transitive_cascade/substantiated_misrepresentation_cascades_suspension_quarantine_withdrawal_and_void
    """
    setup = setup_documented_provider()
    provider = setup["provider"]
    account = create_account(provider["id"])
    item = create_content_item(account["id"], fingerprint_hash=_SHARED_FINGERPRINT)
    holder, reference = _trusted_holder_with_matching_reference()

    first_notice = create_processed_notice(holder["id"], [item["content_url"]])
    claim = claims_of_notice(first_notice["id"])[0]
    strike = list_account_strikes(account["id"])[0][0]

    # A second notice from the same holder omits its signature and is rejected,
    # which drives the abuse score to the auto-open floor.
    rejected = create_notice(holder["id"], [item["content_url"]],
                             signature_present=False)
    rejected = validate_success(api.validate_notice(rejected["id"], AGENT),
                                expected_status=200)
    assert rejected["status"] == "REJECTED"

    cases, cases_meta = validate_paginated(
        api.list_misrepresentation_cases(INVESTIGATOR,
                                         {"rights_holder_id": holder["id"]})
    )
    assert cases_meta["total_count"] == 1
    case_id = cases[0]["id"]
    assert cases[0]["opened_by_user_id"] is None

    substantiated = validate_success(
        api.substantiate_misrepresentation_case(
            case_id, make_abuse_investigator_headers("investigator-07")
        ),
        expected_status=200,
    )

    assert substantiated["status"] == "SUBSTANTIATED"
    assert substantiated["opened_by_user_id"] is None
    assert substantiated["substantiated_by_user_id"] == "investigator-07"
    assert substantiated["affected_claim_count"] == 1
    assert substantiated["disabled_day_count"] == 0
    assert substantiated["base_penalty_cents"] == 25000
    assert substantiated["surcharge_cents"] == 0
    assert substantiated["total_penalty_cents"] == 25000
    assert_instant_equals(substantiated["substantiated_at"], "2026-08-01T00:00:00Z",
                          "substantiated_at")

    stored_holder = get_rights_holder(holder["id"])
    assert stored_holder["misrepresentation_count"] == 1
    assert float(stored_holder["abuse_score"]) == 100.00
    assert stored_holder["enrollment_status"] == "SUSPENDED"
    assert stored_holder["program_tier"] == "VERIFIED"

    stored_reference = validate_success(
        api.get_reference_file(reference["id"], OFFICER), expected_status=200
    )
    assert stored_reference["status"] == "QUARANTINED"

    stored_claim = get_claim(claim["id"])
    assert stored_claim["status"] == "WITHDRAWN"
    assert stored_claim["reference_file_id"] == reference["id"]
    assert float(stored_claim["match_confidence"]) == 1.0

    stored_item = get_content_item(item["id"])
    assert stored_item["availability_status"] == "RESTORED"
    assert stored_item["dispute_status"] == "RESOLVED"

    stored_strike = validate_success(api.get_strike(strike["id"], OFFICER),
                                    expected_status=200)
    assert stored_strike["status"] == "VOIDED"
    assert float(stored_strike["effective_points"]) == 0.0

    stored_account = get_account(account["id"])
    assert float(stored_account["strike_points"]) == 0.00
    assert stored_account["standing"] == "ACTIVE"
    assert stored_account["upload_restricted"] is False
    assert stored_account["available_content_count"] == 1

    assert get_notice(first_notice["id"])["status"] == "CLOSED"


def test_dismissing_the_case_leaves_the_whole_cascade_unfired(api):
    """PRD §3.9: "Dismissing a case instead moves it `OPEN → DISMISSED` under the
    same segregation-of-duties rule, records no penalty, and leaves `abuse_score`
    untouched."

    Design: Difficulty/transitive_cascade/substantiated_misrepresentation_cascades_suspension_quarantine_withdrawal_and_void
    """
    setup = setup_documented_provider()
    provider = setup["provider"]
    account = create_account(provider["id"])
    item = create_content_item(account["id"], fingerprint_hash=_SHARED_FINGERPRINT)
    holder, reference = _trusted_holder_with_matching_reference()

    first_notice = create_processed_notice(holder["id"], [item["content_url"]])
    claim = claims_of_notice(first_notice["id"])[0]
    strike = list_account_strikes(account["id"])[0][0]

    unsigned = create_notice(holder["id"], [item["content_url"]],
                             signature_present=False)
    validate_success(api.validate_notice(unsigned["id"], AGENT), expected_status=200)

    cases, _ = validate_paginated(
        api.list_misrepresentation_cases(INVESTIGATOR,
                                         {"rights_holder_id": holder["id"]})
    )
    case_id = cases[0]["id"]

    dismissed = validate_success(
        api.dismiss_misrepresentation_case(
            case_id, make_abuse_investigator_headers("investigator-07")
        ),
        expected_status=200,
    )

    assert dismissed["status"] == "DISMISSED"
    assert dismissed["base_penalty_cents"] == 0
    assert dismissed["surcharge_cents"] == 0
    assert dismissed["total_penalty_cents"] == 0
    assert dismissed["affected_claim_count"] == 0
    assert dismissed["disabled_day_count"] == 0

    stored_holder = get_rights_holder(holder["id"])
    assert stored_holder["misrepresentation_count"] == 0
    assert float(stored_holder["abuse_score"]) == 40.00
    assert stored_holder["enrollment_status"] == "ENROLLED"
    assert stored_holder["program_tier"] == "TRUSTED"

    assert validate_success(api.get_reference_file(reference["id"], OFFICER),
                            expected_status=200)["status"] == "ACTIVE"
    assert get_claim(claim["id"])["status"] == "DISABLED"

    stored_item = get_content_item(item["id"])
    assert stored_item["availability_status"] == "DISABLED"
    assert stored_item["dispute_status"] == "UNDER_NOTICE"

    assert validate_success(api.get_strike(strike["id"], OFFICER),
                            expected_status=200)["status"] == "ACTIVE"

    stored_account = get_account(account["id"])
    assert float(stored_account["strike_points"]) == 20.00
    assert stored_account["standing"] == "LIMITED"
    assert stored_account["available_content_count"] == 0

    assert get_notice(first_notice["id"])["status"] == "PROCESSED"


def test_substantiation_below_the_suspension_floor_stops_before_the_holder(api):
    """PRD §3.9: "When that recomputed score is 70 or more, the holder's
    `program_tier` steps down one level — `TRUSTED → VERIFIED`, or `VERIFIED →
    STANDARD` — and its `enrollment_status` moves `ENROLLED → SUSPENDED`."

    Design: Difficulty/transitive_cascade/substantiated_misrepresentation_cascades_suspension_quarantine_withdrawal_and_void
    """
    setup = setup_documented_provider()
    provider = setup["provider"]
    scene = setup_account_with_items(provider["id"], 5)
    account, items = scene["account"], scene["items"]
    holder = create_enrolled_rights_holder("VERIFIED")
    reference = create_active_reference_file(holder["id"])

    notices = [create_processed_notice(holder["id"], [item["content_url"]])
               for item in items]
    assert get_rights_holder(holder["id"])["notices_processed"] == 5

    claim = claims_of_notice(notices[0]["id"])[0]
    strike = validate_paginated(api.list_claim_strikes(claim["id"], AGENT))[0][0]

    case = create_misrepresentation_case(holder["id"], claim["id"],
                                         investigator_user_id="investigator-01")

    substantiated = validate_success(
        api.substantiate_misrepresentation_case(
            case["id"], make_abuse_investigator_headers("investigator-02")
        ),
        expected_status=200,
    )
    assert substantiated["status"] == "SUBSTANTIATED"
    assert substantiated["affected_claim_count"] == 1
    assert substantiated["base_penalty_cents"] == 25000
    assert substantiated["total_penalty_cents"] == 25000

    # One substantiation over five processed notices scores 60.00, short of the
    # suspension floor of 70, so the holder-side cascade must not fire.
    stored_holder = get_rights_holder(holder["id"])
    assert stored_holder["misrepresentation_count"] == 1
    assert float(stored_holder["abuse_score"]) == 60.00
    assert stored_holder["enrollment_status"] == "ENROLLED"
    assert stored_holder["program_tier"] == "VERIFIED"

    assert validate_success(api.get_reference_file(reference["id"], OFFICER),
                            expected_status=200)["status"] == "ACTIVE"
    assert get_claim(claim["id"])["status"] == "DISABLED"
    assert validate_success(api.get_strike(strike["id"], OFFICER),
                            expected_status=200)["status"] == "ACTIVE"
    assert get_content_item(items[0]["id"])["availability_status"] == "DISABLED"

    # No strike was voided, so the five VERIFIED-weight strikes still stand.
    stored_account = get_account(account["id"])
    assert float(stored_account["strike_points"]) == 75.00
    assert stored_account["standing"] == "LIMITED"


# ---------------------------------------------------------------------------
# Ingestion batch: the safe-harbour gate outranks the referential checks
# ---------------------------------------------------------------------------

def test_ingestion_safe_harbor_gate_outranks_enrollment_and_tier_checks(api):
    """PRD §3.4: "Three preconditions guard the operation, and their relative
    order is the one given in Section 2.6: the hosting provider's
    `safe_harbor_status` must be `ELIGIBLE`, refused otherwise with
    `ERR_SAFE_HARBOR_NOT_ELIGIBLE`; the holder must be `ENROLLED`, refused
    otherwise with `ERR_RIGHTS_HOLDER_NOT_ENROLLED`; and the holder's
    `program_tier` must be `VERIFIED` or `TRUSTED`, refused otherwise with
    `ERR_PROGRAM_TIER_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/ingestion_safe_harbor_gate_precedes_enrollment_referential_check
    """
    setup = setup_provider_with_agent()
    provider = get_provider(setup["provider"]["id"])
    # No policy revision is PUBLISHED, so the documentation gate forfeits posture.
    assert provider["safe_harbor_status"] == "FORFEITED"
    assert provider["safe_harbor_score"] == 0

    holder = create_rights_holder()
    assert holder["enrollment_status"] == "PROSPECT"
    assert holder["program_tier"] == "STANDARD"

    response = api.create_ingestion_batch(
        create_ingestion_batch_payload(holder["id"], 10),
        make_rights_holder_rep_headers(holder["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SAFE_HARBOR_NOT_ELIGIBLE.value)
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_RIGHTS_HOLDER_NOT_ENROLLED.value
    )
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_PROGRAM_TIER_INSUFFICIENT.value
    )

    _, batches_meta = validate_paginated(
        api.list_rights_holder_ingestion_batches(holder["id"], OFFICER)
    )
    assert batches_meta["total_count"] == 0

    unchanged = get_provider(provider["id"])
    assert unchanged["safe_harbor_status"] == "FORFEITED"
    assert unchanged["safe_harbor_score"] == 0


def test_enrollment_check_fires_once_the_safe_harbor_gate_is_satisfied(api):
    """PRD §2.6: "Because most operations in this domain are guarded by several
    conditions at once, the order in which those conditions are evaluated is part
    of the contract: the first condition that fails decides both the error
    identifier and the HTTP status, and no later condition may mask an earlier
    one."

    Design: Difficulty/priority_pair_validation_conflict/ingestion_safe_harbor_gate_precedes_enrollment_referential_check
    """
    setup = setup_documented_provider()
    provider = get_provider(setup["provider"]["id"])
    assert provider["safe_harbor_status"] == "ELIGIBLE"

    holder = create_rights_holder()
    assert holder["enrollment_status"] == "PROSPECT"

    response = api.create_ingestion_batch(
        create_ingestion_batch_payload(holder["id"], 10),
        make_rights_holder_rep_headers(holder["id"]),
    )

    validate_error(response, ApiErrorId.ERR_RIGHTS_HOLDER_NOT_ENROLLED.value)

    _, batches_meta = validate_paginated(
        api.list_rights_holder_ingestion_batches(holder["id"], OFFICER)
    )
    assert batches_meta["total_count"] == 0


def test_tier_check_fires_last_of_the_three_ingestion_preconditions(api):
    """PRD §3.4: "Three preconditions guard the operation, and their relative
    order is the one given in Section 2.6: the hosting provider's
    `safe_harbor_status` must be `ELIGIBLE`, refused otherwise with
    `ERR_SAFE_HARBOR_NOT_ELIGIBLE`; the holder must be `ENROLLED`, refused
    otherwise with `ERR_RIGHTS_HOLDER_NOT_ENROLLED`; and the holder's
    `program_tier` must be `VERIFIED` or `TRUSTED`, refused otherwise with
    `ERR_PROGRAM_TIER_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/ingestion_safe_harbor_gate_precedes_enrollment_referential_check
    """
    setup = setup_documented_provider()
    provider = get_provider(setup["provider"]["id"])
    assert provider["safe_harbor_status"] == "ELIGIBLE"

    holder = create_enrolled_rights_holder("STANDARD")
    assert holder["enrollment_status"] == "ENROLLED"
    assert holder["program_tier"] == "STANDARD"

    response = api.create_ingestion_batch(
        create_ingestion_batch_payload(holder["id"], 10),
        make_rights_holder_rep_headers(holder["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PROGRAM_TIER_INSUFFICIENT.value)

    _, batches_meta = validate_paginated(
        api.list_rights_holder_ingestion_batches(holder["id"], OFFICER)
    )
    assert batches_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Counter-notice receipt: the temporal window outranks the terminated account
# ---------------------------------------------------------------------------

def test_closed_counter_notice_window_outranks_the_terminated_account(api):
    """PRD §2.6: "Six checks share this rung, each on a different operation:
    restoring before the claim's due instant gives `ERR_RESTORATION_TOO_EARLY`; a
    counter-notice arriving after its window gives
    `ERR_COUNTER_NOTICE_WINDOW_CLOSED`; upholding a disabled claim while its
    counter-notice window is still open gives `ERR_COUNTER_NOTICE_WINDOW_OPEN`;
    recording a notice of court action too late gives
    `ERR_SUIT_NOTICE_WINDOW_CLOSED`; filing an appeal too late gives
    `ERR_APPEAL_WINDOW_CLOSED`; lapsing a registration before its term has run
    gives `ERR_REGISTRATION_NOT_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/counter_notice_window_temporal_check_precedes_terminated_account_check
    """
    provider, account, items, holder = _documented_scene(4)
    notice = create_processed_notice(holder["id"], _urls(items))
    claim = claims_of_notice(notice["id"])[0]

    cases, cases_meta = validate_paginated(
        api.list_account_termination_cases(account["id"], OFFICER)
    )
    assert cases_meta["total_count"] == 1

    # The claim's counter-notice window closed on 2026-08-31; move past it and
    # terminate the account, so both rungs are violated by the same request.
    set_clock("2026-09-15T00:00:00Z")
    executed = execute_termination_case(cases[0]["id"], "officer-01")
    assert executed["status"] == "EXECUTED"
    assert get_account(account["id"])["standing"] == "TERMINATED"

    claim_version = get_claim(claim["id"])["version"]
    response = api.create_counter_notice(
        create_counter_notice_payload(claim["id"], claim_version),
        make_subscriber_headers(account["id"]),
    )

    validate_error(response, ApiErrorId.ERR_COUNTER_NOTICE_WINDOW_CLOSED.value)
    assert response.status_code == 409
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_ACCOUNT_TERMINATED.value
    )

    _, counters_meta = validate_paginated(
        api.list_counter_notices(AGENT, {"claim_id": claim["id"]})
    )
    assert counters_meta["total_count"] == 0
    assert get_claim(claim["id"])["status"] == "DISABLED"

    stored_account = get_account(account["id"])
    assert stored_account["standing"] == "TERMINATED"
    assert float(stored_account["strike_points"]) == 40.00


def test_terminated_account_check_fires_while_the_window_is_still_open(api):
    """PRD §3.7: "And the acting account must not be `TERMINATED`, which is
    refused with `ERR_ACCOUNT_TERMINATED`."

    Design: Difficulty/priority_pair_validation_conflict/counter_notice_window_temporal_check_precedes_terminated_account_check
    """
    provider, account, items, holder = _documented_scene(4)
    notice = create_processed_notice(holder["id"], _urls(items))
    claim = claims_of_notice(notice["id"])[0]

    cases, _ = validate_paginated(
        api.list_account_termination_cases(account["id"], OFFICER)
    )

    # 2026-08-15 is still inside the claim's 30-day counter-notice window, so
    # only the terminated-account rung is violated.
    set_clock("2026-08-15T00:00:00Z")
    execute_termination_case(cases[0]["id"], "officer-01")
    assert get_account(account["id"])["standing"] == "TERMINATED"

    claim_version = get_claim(claim["id"])["version"]
    response = api.create_counter_notice(
        create_counter_notice_payload(claim["id"], claim_version),
        make_subscriber_headers(account["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ACCOUNT_TERMINATED.value)
    assert response.status_code == 403

    _, counters_meta = validate_paginated(
        api.list_counter_notices(AGENT, {"claim_id": claim["id"]})
    )
    assert counters_meta["total_count"] == 0


def test_counter_notice_at_the_last_instant_of_the_window_is_accepted(api):
    """PRD §3.7: "The counter-notice must arrive no later than the claim's
    `disabled_at` advanced by the claim's snapshotted
    `counter_notice_window_days`; a later submission is refused with
    `ERR_COUNTER_NOTICE_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/counter_notice_window_temporal_check_precedes_terminated_account_check
    """
    provider, account, items, holder = _documented_scene(1)
    notice = create_processed_notice(holder["id"], _urls(items))
    claim = claims_of_notice(notice["id"])[0]
    assert claim["counter_notice_window_days"] == 30

    # disabled_at 2026-08-01 advanced by 30 days is exactly 2026-08-31, and the
    # bound is inclusive.
    set_clock("2026-08-31T00:00:00Z")
    claim_version = get_claim(claim["id"])["version"]

    created = validate_success(
        api.create_counter_notice(
            create_counter_notice_payload(claim["id"], claim_version),
            make_subscriber_headers(account["id"]),
        ),
        expected_status=201,
    )

    assert created["status"] == "RECEIVED"
    assert created["claim_id"] == claim["id"]
    assert created["account_id"] == account["id"]
    assert created["completeness_score"] == 0
    assert created["forwarded_at"] is None
    assert created["superseded_by_counter_notice_id"] is None
    assert get_claim(claim["id"])["version"] == claim_version + 1


# ---------------------------------------------------------------------------
# Notice validation: the substantial threshold and the core-element gate
# ---------------------------------------------------------------------------

def test_notice_scoring_exactly_the_substantial_threshold_is_validated(api):
    """PRD §3.5: "Under `SUBSTANTIAL_COMPLIANCE` the notice clears the threshold
    when `completeness_score` is at least 92, and `sworn_under_penalty` is ignored
    entirely — so a notice whose only missing element is the accuracy statement
    scores exactly 92, meets the threshold, and passes that stage."

    Design: Difficulty/boundary_precision_check/notice_score_at_substantial_threshold_passes_while_core_gate_still_bites
    """
    setup_provider_with_agent()
    holder = create_rights_holder()

    notice = create_notice(holder["id"], [_ABSENT_URL], accuracy_statement=False)
    validated = validate_success(api.validate_notice(notice["id"], AGENT),
                                 expected_status=200)

    assert validated["completeness_score"] == 92
    assert validated["compliance_variant"] == "SUBSTANTIAL_COMPLIANCE"
    assert validated["status"] == "VALIDATED"
    assert validated["rejection_reason"] is None
    assert_instant_equals(validated["validated_at"], "2026-08-01T00:00:00Z",
                          "notice validated_at")

    stored_holder = get_rights_holder(holder["id"])
    assert stored_holder["rejected_count"] == 0
    assert float(stored_holder["abuse_score"]) == 0.00


def test_core_element_gate_bites_a_notice_that_already_met_the_threshold(api):
    """PRD §3.5: "Independently of the score, the core gate walks these five
    elements in this fixed order — the signature, work identification, material
    identification, the good-faith statement, and the authority statement — and
    identifies the first one that is absent."

    Design: Difficulty/boundary_precision_check/notice_score_at_substantial_threshold_passes_while_core_gate_still_bites
    """
    setup_provider_with_agent()
    holder = create_rights_holder()

    notice = create_notice(holder["id"], [_ABSENT_URL], signature_present=False)
    rejected = validate_success(api.validate_notice(notice["id"], AGENT),
                                expected_status=200)

    # The same 92 that clears the threshold cannot survive the non-waivable gate.
    assert rejected["completeness_score"] == 92
    assert rejected["compliance_variant"] == "SUBSTANTIAL_COMPLIANCE"
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "CORE_ELEMENT_MISSING:signature_present"
    assert rejected["validated_at"] is None
    assert rejected["processed_at"] is None
    assert rejected["matched_claim_count"] == 0

    stored_holder = get_rights_holder(holder["id"])
    assert stored_holder["rejected_count"] == 1
    assert float(stored_holder["abuse_score"]) == 40.00
    assert stored_holder["enrollment_status"] == "PROSPECT"


def test_notice_two_weights_below_the_threshold_is_rejected_on_score(api):
    """PRD §3.5: "Seven elements carry weight, and their weights sum to exactly
    100: the signature contributes 8, work identification 18, material
    identification 20, the contact address 10, the good-faith statement 18, the
    accuracy statement 8, and the authority statement 18."

    Design: Difficulty/boundary_precision_check/notice_score_at_substantial_threshold_passes_while_core_gate_still_bites
    """
    setup_provider_with_agent()
    holder = create_rights_holder()

    below = create_notice(holder["id"], [_ABSENT_URL], contact_email=None)
    below = validate_success(api.validate_notice(below["id"], AGENT),
                             expected_status=200)

    assert below["completeness_score"] == 90
    assert below["status"] == "REJECTED"
    assert below["rejection_reason"] == "SCORE_BELOW_THRESHOLD"

    gated = create_notice(holder["id"], [_ABSENT_URL], signature_present=False)
    gated = validate_success(api.validate_notice(gated["id"], AGENT),
                             expected_status=200)

    assert gated["completeness_score"] == 92
    assert gated["status"] == "REJECTED"
    assert gated["rejection_reason"] == "CORE_ELEMENT_MISSING:signature_present"

    stored_holder = get_rights_holder(holder["id"])
    assert stored_holder["rejected_count"] == 2
    assert float(stored_holder["abuse_score"]) == 80.00
    assert stored_holder["enrollment_status"] == "PROSPECT"


# ---------------------------------------------------------------------------
# Processing with an empty actionable set
# ---------------------------------------------------------------------------

def test_processing_a_notice_with_no_resolvable_url_is_unprocessable(api):
    """PRD §3.6: "If no entry resolves to material in `AVAILABLE` or `RESTORED`
    at all, the request is refused with `ERR_NO_ACTIONABLE_CLAIMS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/process_notice_with_zero_resolvable_urls_yields_no_actionable_claims
    """
    provider, account, items, holder = _documented_scene(1)
    notice = create_validated_notice(holder["id"], [_ABSENT_URL])

    response = api.process_notice(notice["id"], AGENT)
    validate_error(response, ApiErrorId.ERR_NO_ACTIONABLE_CLAIMS.value)
    assert response.status_code == 422

    stored_notice = get_notice(notice["id"])
    assert stored_notice["status"] == "VALIDATED"
    assert stored_notice["matched_claim_count"] == 0
    assert stored_notice["unmatched_url_count"] == 0
    assert stored_notice["processed_at"] is None

    _, claims_meta = validate_paginated(
        api.list_claims(AGENT, {"notice_id": notice["id"]})
    )
    assert claims_meta["total_count"] == 0

    assert get_content_item(items[0]["id"])["availability_status"] == "AVAILABLE"
    assert get_content_item(items[0]["id"])["dispute_status"] == "NONE"

    stored_account = get_account(account["id"])
    assert stored_account["available_content_count"] == 1
    assert stored_account["notified_count"] == 0
    assert float(stored_account["strike_points"]) == 0.00

    assert get_rights_holder(holder["id"])["notices_processed"] == 0


def test_one_resolvable_url_alongside_an_absent_one_still_processes(api):
    """PRD §3.6: "Processing writes `matched_claim_count`, the number of
    `claimed_urls` entries that matched live material, and `unmatched_url_count`,
    the number that matched none, then stamps `processed_at` from the logical
    clock — that stamp is the endpoint of the response-latency measurement used by
    the safe-harbour audit."

    Design: Difficulty/boundary_precision_check/process_notice_with_zero_resolvable_urls_yields_no_actionable_claims
    """
    provider, account, items, holder = _documented_scene(1)
    notice = create_validated_notice(
        holder["id"], [items[0]["content_url"], _ABSENT_URL]
    )

    processed = validate_success(api.process_notice(notice["id"], AGENT),
                                 expected_status=200)

    assert processed["status"] == "PROCESSED"
    assert processed["matched_claim_count"] == 1
    assert processed["unmatched_url_count"] == 1
    assert_instant_equals(processed["processed_at"], "2026-08-01T00:00:00Z",
                          "notice processed_at")

    claims, claims_meta = validate_paginated(
        api.list_claims(AGENT, {"notice_id": notice["id"]})
    )
    assert claims_meta["total_count"] == 1
    assert claims[0]["matched_url"] == items[0]["content_url"]
    assert claims[0]["status"] == "DISABLED"

    assert get_content_item(items[0]["id"])["availability_status"] == "DISABLED"

    stored_account = get_account(account["id"])
    assert stored_account["available_content_count"] == 0
    assert stored_account["notified_count"] == 1
    assert float(stored_account["strike_points"]) == 10.00

    assert get_rights_holder(holder["id"])["notices_processed"] == 1


def test_a_url_resolving_only_to_disabled_material_is_unprocessable(api):
    """PRD §3.6: "Two preconditions are checked before any claim is created: the
    owning provider must hold a policy revision in `PUBLISHED`, or the request is
    refused with `ERR_REPEAT_INFRINGER_POLICY_NOT_PUBLISHED`; and at least one
    entry in `claimed_urls` must resolve to a content item whose
    `availability_status` is `AVAILABLE` or `RESTORED` and whose dispute interval
    is free."

    Design: Difficulty/boundary_precision_check/process_notice_with_zero_resolvable_urls_yields_no_actionable_claims
    """
    provider, account, items, first_holder = _documented_scene(1)
    create_processed_notice(first_holder["id"], _urls(items))
    assert get_content_item(items[0]["id"])["availability_status"] == "DISABLED"

    # A different complainant, so no dispute interval of its own is occupied:
    # the only reason the request fails is that nothing live resolves.
    second_holder = create_rights_holder()
    notice = create_validated_notice(second_holder["id"], _urls(items))

    response = api.process_notice(notice["id"], AGENT)
    validate_error(response, ApiErrorId.ERR_NO_ACTIONABLE_CLAIMS.value)
    assert response.status_code == 422

    stored_notice = get_notice(notice["id"])
    assert stored_notice["status"] == "VALIDATED"
    assert stored_notice["matched_claim_count"] == 0
    assert stored_notice["processed_at"] is None

    _, claims_meta = validate_paginated(
        api.list_claims(AGENT, {"rights_holder_id": second_holder["id"]})
    )
    assert claims_meta["total_count"] == 0

    assert get_rights_holder(second_holder["id"])["notices_processed"] == 0

    stored_account = get_account(account["id"])
    assert stored_account["notified_count"] == 1
    assert float(stored_account["strike_points"]) == 10.00
