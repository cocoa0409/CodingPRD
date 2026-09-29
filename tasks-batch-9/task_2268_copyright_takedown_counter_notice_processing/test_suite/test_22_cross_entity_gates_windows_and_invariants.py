"""Cross-entity gates, overlapping time windows and compensating counters.

Every scene is built from scratch through the public API: the server is
restarted before each test, so nothing survives between them.
"""

from test_helpers import (
    AGENT,
    CLOCK_START_ISO,
    OFFICER,
    ApiErrorId,
    assert_instant_equals,
    claims_of_notice,
    create_enrolled_rights_holder,
    create_forwarded_counter_notice,
    create_ingestion_batch,
    create_ingestion_batch_payload,
    create_notice,
    create_processed_notice,
    create_provider,
    create_reference_file,
    create_rights_holder,
    create_submitted_agent,
    create_validated_notice,
    enroll_rights_holder,
    get_account,
    get_content_item,
    get_counter_notice,
    get_notice,
    get_provider,
    get_rights_holder,
    get_success_data,
    list_account_content_items,
    list_account_strikes,
    list_claims,
    make_rights_holder_rep_headers,
    publish_contact,
    register_agent,
    restore_claim,
    set_clock,
    setup_account_with_items,
    setup_documented_provider,
    strike_summary,
    validate_error,
    validate_notice,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Module-private scene builders
# ---------------------------------------------------------------------------


def _submitted_agent_scene():
    """Provider with a published public contact and one designation still in
    SUBMITTED, plus a STANDARD rights holder and a statutorily complete notice
    sitting in RECEIVED."""
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    publish_contact(provider["id"])
    agent = create_submitted_agent(provider["id"])
    holder = create_rights_holder()
    notice = create_notice(holder["id"], ["https://northstar.example/v/1"])
    return {
        "provider": provider,
        "agent": agent,
        "rights_holder": holder,
        "notice": notice,
    }


def _pending_reference_file_scene():
    """A never-enrolled (PROSPECT) rights holder with one PENDING reference
    file carrying a copyright registration number."""
    set_clock(CLOCK_START_ISO)
    holder = create_rights_holder()
    reference = create_reference_file(
        holder["id"], registration_number="SR0000991122"
    )
    return {"rights_holder": holder, "reference_file": reference}


def _restored_claim_occupying_its_interval():
    """One claim disabled at 2026-08-01 under a 30-day dispute window, counter-
    noticed, forwarded and finally RESTORED at 2026-08-14 — the interval it
    occupies therefore runs [2026-08-01, 2026-08-31)."""
    setup = setup_documented_provider()
    provider = setup["provider"]
    scene = setup_account_with_items(provider["id"], 1)
    account = scene["account"]
    item = scene["items"][0]
    holder = create_rights_holder()
    notice = create_processed_notice(holder["id"], [item["content_url"]])
    claim = claims_of_notice(notice["id"])[0]
    counter = create_forwarded_counter_notice(claim["id"], account["id"])
    set_clock("2026-08-14T00:00:00Z")
    restore_claim(claim["id"])
    return {
        "provider": provider,
        "policy": setup["policy"],
        "account": account,
        "item": item,
        "rights_holder": holder,
        "notice": notice,
        "claim": claim,
        "counter_notice": counter,
    }


def _verified_holder_with_first_batch():
    """An ELIGIBLE provider plus a VERIFIED, ENROLLED holder whose quota is 500
    items and whose first ACCEPTED batch of 300 items is anchored at
    2026-08-01T00:00:00Z."""
    setup = setup_documented_provider()
    holder = create_enrolled_rights_holder("VERIFIED", daily_item_quota=500)
    batch = create_ingestion_batch(holder["id"], 300)
    return {"provider": setup["provider"], "rights_holder": holder, "batch": batch}


def _two_complainants_one_account():
    """Three AVAILABLE items on one account; Meridian's notice on the third is
    PROCESSED first, so the account's pre-process baseline is one ACTIVE
    strike."""
    setup = setup_documented_provider()
    scene = setup_account_with_items(setup["provider"]["id"], 3)
    account = scene["account"]
    items = scene["items"]
    meridian = create_rights_holder()
    orbit = create_rights_holder()
    meridian_notice = create_processed_notice(
        meridian["id"], [items[2]["content_url"]]
    )
    return {
        "provider": setup["provider"],
        "account": account,
        "items": items,
        "meridian": meridian,
        "orbit": orbit,
        "meridian_notice": meridian_notice,
    }


def _forwarded_counter_notice_scene():
    """Three AVAILABLE items on one account (the pre-disable baseline), one of
    them disabled by a PROCESSED notice, its claim counter-noticed and
    forwarded on 2026-08-01, with the clock moved to 2026-08-14."""
    setup = setup_documented_provider()
    scene = setup_account_with_items(setup["provider"]["id"], 3)
    baseline_account = scene["account"]
    items = scene["items"]
    holder = create_rights_holder()
    notice = create_processed_notice(holder["id"], [items[0]["content_url"]])
    claim = claims_of_notice(notice["id"])[0]
    counter = create_forwarded_counter_notice(claim["id"], baseline_account["id"])
    set_clock("2026-08-14T00:00:00Z")
    return {
        "baseline_account": baseline_account,
        "items": items,
        "rights_holder": holder,
        "notice": notice,
        "claim": claim,
        "counter_notice": counter,
    }


def _withdraw_notice(api, notice_id: str, rights_holder_id: str):
    return api.withdraw_notice(
        notice_id, make_rights_holder_rep_headers(rights_holder_id)
    )


# ---------------------------------------------------------------------------
# cross_entity_state_dependency —
# notice_validation_depends_on_designated_agent_registration_state
# ---------------------------------------------------------------------------


def test_notice_validation_is_refused_while_the_designation_is_only_submitted(api):
    """PRD §3.5: "Before either branch is reached, the provider must hold at least one designated agent in `REGISTERED` — a provider that has not completed its own registration may not act on complaints at all — and a notice that is not in `RECEIVED` is refused with `ERR_INVALID_NOTICE_STATE`."

    Design: Difficulty/cross_entity_state_dependency/notice_validation_depends_on_designated_agent_registration_state
    """
    scene = _submitted_agent_scene()
    notice = scene["notice"]

    validate_error(
        api.validate_notice(notice["id"], AGENT),
        ApiErrorId.ERR_DESIGNATED_AGENT_NOT_REGISTERED.value,
    )

    unchanged = get_notice(notice["id"])
    assert unchanged["status"] == "RECEIVED"
    assert unchanged["completeness_score"] == 0
    assert unchanged["validated_at"] is None

    agent = get_success_data(
        api.get_designated_agent(scene["agent"]["id"], OFFICER)
    )
    assert agent["registration_status"] == "SUBMITTED"
    assert get_provider(scene["provider"]["id"])["designated_agent_registered"] is False


def test_the_identical_notice_validation_succeeds_once_the_agent_reaches_registered(api):
    """PRD §2.6: "Before any notice may be validated, the provider must hold at least one designated agent in `REGISTERED`; otherwise `ERR_DESIGNATED_AGENT_NOT_REGISTERED` (409)."

    Design: Difficulty/cross_entity_state_dependency/notice_validation_depends_on_designated_agent_registration_state
    """
    scene = _submitted_agent_scene()
    notice = scene["notice"]

    validate_error(
        api.validate_notice(notice["id"], AGENT),
        ApiErrorId.ERR_DESIGNATED_AGENT_NOT_REGISTERED.value,
    )

    registered = register_agent(
        scene["agent"]["id"],
        scene["provider"]["id"],
        copyright_office_receipt="CO-2026-0001",
    )
    assert registered["registration_status"] == "REGISTERED"
    assert get_provider(scene["provider"]["id"])["designated_agent_registered"] is True

    validated = validate_success(api.validate_notice(notice["id"], AGENT))
    assert validated["status"] == "VALIDATED"
    assert validated["completeness_score"] == 100
    assert validated["compliance_variant"] == "SUBSTANTIAL_COMPLIANCE"
    assert_instant_equals(validated["validated_at"], CLOCK_START_ISO, "validated_at")

    holder = get_rights_holder(scene["rights_holder"]["id"])
    assert holder["rejected_count"] == 0
    assert float(holder["abuse_score"]) == 0.00


# ---------------------------------------------------------------------------
# cross_entity_state_dependency —
# reference_file_activation_depends_on_rights_holder_enrollment_state
# ---------------------------------------------------------------------------


def test_reference_file_activation_is_refused_while_its_holder_is_only_a_prospect(api):
    """PRD §3.3: "Activating a file moves it `PENDING → ACTIVE`, requires the owning holder to be `ENROLLED`, and requires the stored `fingerprint_hash` to be 32 lowercase hexadecimal characters."

    Design: Difficulty/cross_entity_state_dependency/reference_file_activation_depends_on_rights_holder_enrollment_state
    """
    scene = _pending_reference_file_scene()
    holder = scene["rights_holder"]
    reference = scene["reference_file"]
    rep = make_rights_holder_rep_headers(holder["id"])

    assert holder["enrollment_status"] == "PROSPECT"

    validate_error(
        api.activate_reference_file(reference["id"], rep),
        ApiErrorId.ERR_RIGHTS_HOLDER_NOT_ENROLLED.value,
    )

    unchanged = get_success_data(api.get_reference_file(reference["id"], rep))
    assert unchanged["status"] == "PENDING"
    assert unchanged["activated_at"] is None


def test_reference_file_activation_succeeds_and_stamps_the_clock_after_enrollment(api):
    """PRD §3.3: "Activation stamps `activated_at` from the logical clock and makes the file eligible for confidence-based selection."

    Design: Difficulty/cross_entity_state_dependency/reference_file_activation_depends_on_rights_holder_enrollment_state
    """
    scene = _pending_reference_file_scene()
    holder = scene["rights_holder"]
    reference = scene["reference_file"]
    rep = make_rights_holder_rep_headers(holder["id"])

    validate_error(
        api.activate_reference_file(reference["id"], rep),
        ApiErrorId.ERR_RIGHTS_HOLDER_NOT_ENROLLED.value,
    )

    enrolled = enroll_rights_holder(holder["id"])
    assert enrolled["enrollment_status"] == "ENROLLED"

    activated = validate_success(api.activate_reference_file(reference["id"], rep))
    assert activated["status"] == "ACTIVE"
    assert_instant_equals(activated["activated_at"], CLOCK_START_ISO, "activated_at")

    _, meta = validate_paginated(
        api.list_rights_holder_reference_files(
            holder["id"], rep, {"status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# resource_temporal_overlap —
# duplicate_claim_rejected_inside_half_open_dispute_interval_and_allowed_at_its_upper_bound
# ---------------------------------------------------------------------------


def test_a_second_notice_inside_the_dispute_interval_is_refused_as_a_duplicate(api):
    """PRD §3.6: "For each existing claim, the occupied interval begins at that claim's `disabled_at` and extends forward by that claim's snapshotted `dispute_window_days`, with the lower bound included and the upper bound **excluded**."

    Design: Difficulty/resource_temporal_overlap/duplicate_claim_rejected_inside_half_open_dispute_interval_and_allowed_at_its_upper_bound
    """
    scene = _restored_claim_occupying_its_interval()
    item = scene["item"]
    holder = scene["rights_holder"]

    first_claim = get_success_data(api.get_claim(scene["claim"]["id"], AGENT))
    assert first_claim["status"] == "RESTORED"
    assert_instant_equals(first_claim["disabled_at"], CLOCK_START_ISO, "disabled_at")
    assert first_claim["dispute_window_days"] == 30

    set_clock("2026-08-30T00:00:00Z")
    second = create_validated_notice(holder["id"], [item["content_url"]])

    validate_error(
        api.process_notice(second["id"], AGENT),
        ApiErrorId.ERR_DUPLICATE_CLAIM_WINDOW.value,
    )

    assert get_notice(second["id"])["status"] == "VALIDATED"
    _, meta = list_claims(params={"content_item_id": item["id"]})
    assert meta["total_count"] == 1


def test_the_same_notice_is_processed_at_exactly_the_excluded_upper_bound(api):
    """PRD §3.6: "A new claim is refused when the logical clock at processing time falls inside any such interval; because the upper bound is excluded, a clock instant exactly equal to a prior claim's `disabled_at` advanced by its `dispute_window_days` lies outside the interval and the new claim is created."

    Design: Difficulty/resource_temporal_overlap/duplicate_claim_rejected_inside_half_open_dispute_interval_and_allowed_at_its_upper_bound
    """
    scene = _restored_claim_occupying_its_interval()
    account = scene["account"]
    item = scene["item"]
    holder = scene["rights_holder"]

    set_clock("2026-08-30T00:00:00Z")
    second = create_validated_notice(holder["id"], [item["content_url"]])

    set_clock("2026-08-31T00:00:00Z")
    processed = validate_success(api.process_notice(second["id"], AGENT))
    assert processed["status"] == "PROCESSED"
    assert processed["matched_claim_count"] == 1
    assert processed["unmatched_url_count"] == 0

    claims, meta = list_claims(params={"content_item_id": item["id"]})
    assert meta["total_count"] == 2
    assert claims[1]["status"] == "DISABLED"
    assert_instant_equals(
        claims[1]["disabled_at"], "2026-08-31T00:00:00Z", "new claim disabled_at"
    )

    reread_item = get_content_item(item["id"])
    assert reread_item["availability_status"] == "DISABLED"
    assert reread_item["dispute_status"] == "UNDER_NOTICE"

    reread_account = get_account(account["id"])
    assert float(reread_account["strike_points"]) == 10.00
    assert reread_account["available_content_count"] == 0


# ---------------------------------------------------------------------------
# resource_temporal_overlap —
# ingestion_batch_rejected_when_closed_24h_window_aggregate_exceeds_quota
# ---------------------------------------------------------------------------


def test_a_rolling_total_equal_to_the_quota_is_accepted_and_one_more_item_is_refused(api):
    """PRD §3.4: "The request is refused with `ERR_INGESTION_WINDOW_QUOTA_EXCEEDED` when that rolling total is **strictly greater than** the holder's `daily_item_quota`; a rolling total exactly equal to the quota is accepted, so the quota value itself is attainable."

    Design: Difficulty/resource_temporal_overlap/ingestion_batch_rejected_when_closed_24h_window_aggregate_exceeds_quota
    """
    scene = _verified_holder_with_first_batch()
    holder = scene["rights_holder"]
    rep = make_rights_holder_rep_headers(holder["id"])

    assert scene["provider"]["safe_harbor_status"] == "ELIGIBLE"
    assert scene["batch"]["rolling_item_total"] == 300
    assert_instant_equals(
        scene["batch"]["accepted_at"], CLOCK_START_ISO, "first batch accepted_at"
    )

    set_clock("2026-08-01T18:00:00Z")
    second = validate_success(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 200), rep
        ),
        expected_status=201,
    )
    assert second["rolling_item_total"] == 500
    assert second["status"] == "ACCEPTED"

    validate_error(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 1), rep
        ),
        ApiErrorId.ERR_INGESTION_WINDOW_QUOTA_EXCEEDED.value,
    )

    _, meta = validate_paginated(
        api.list_rights_holder_ingestion_batches(holder["id"], rep)
    )
    assert meta["total_count"] == 2


def test_a_batch_accepted_exactly_24_hours_earlier_is_still_inside_the_window(api):
    """PRD §3.4: "Take every ingestion batch of the same rights holder whose `status` is `ACCEPTED`, `PROCESSING` or `COMPLETED` and whose `accepted_at` falls within the interval that begins 24 hours before the logical clock and ends at the logical clock, both endpoints included — a batch accepted exactly 24 hours before the current instant *is* counted, and batches in `REJECTED` are excluded entirely."

    Design: Difficulty/resource_temporal_overlap/ingestion_batch_rejected_when_closed_24h_window_aggregate_exceeds_quota
    """
    scene = _verified_holder_with_first_batch()
    holder = scene["rights_holder"]
    rep = make_rights_holder_rep_headers(holder["id"])

    set_clock("2026-08-01T18:00:00Z")
    create_ingestion_batch(holder["id"], 200)

    set_clock("2026-08-02T00:00:00Z")
    validate_error(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 1), rep
        ),
        ApiErrorId.ERR_INGESTION_WINDOW_QUOTA_EXCEEDED.value,
    )

    _, meta = validate_paginated(
        api.list_rights_holder_ingestion_batches(holder["id"], rep)
    )
    assert meta["total_count"] == 2


def test_one_second_past_the_closed_window_the_older_batch_drops_out(api):
    """PRD §3.4: "Sum their `item_count` values, add the `item_count` requested now, and store the result as the new batch's `rolling_item_total`."

    Design: Difficulty/resource_temporal_overlap/ingestion_batch_rejected_when_closed_24h_window_aggregate_exceeds_quota
    """
    scene = _verified_holder_with_first_batch()
    holder = scene["rights_holder"]
    rep = make_rights_holder_rep_headers(holder["id"])

    set_clock("2026-08-01T18:00:00Z")
    create_ingestion_batch(holder["id"], 200)

    set_clock("2026-08-02T00:00:01Z")
    third = validate_success(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 1), rep
        ),
        expected_status=201,
    )
    assert third["rolling_item_total"] == 201
    assert third["status"] == "ACCEPTED"
    assert_instant_equals(
        third["accepted_at"], "2026-08-02T00:00:01Z", "third batch accepted_at"
    )

    _, meta = validate_paginated(
        api.list_rights_holder_ingestion_batches(holder["id"], rep)
    )
    assert meta["total_count"] == 3


# ---------------------------------------------------------------------------
# compensating_invariant —
# notice_withdrawal_returns_strike_points_to_the_pre_process_value
# ---------------------------------------------------------------------------


def test_withdrawing_a_processed_notice_returns_strike_points_to_the_baseline(api):
    """PRD §3.5: "Every non-terminal child claim moves either `DISABLED → WITHDRAWN` or `COUNTER_NOTICED → WITHDRAWN`, and a claim withdrawn from `COUNTER_NOTICED` additionally moves its counter-notice to `SUPERSEDED`; each withdrawn claim restores its content item — `availability_status` to `RESTORED` and `dispute_status` to `RESOLVED` — unless that item has been purged, in which case the item is left alone; each restoration increments the owning account's `available_content_count` back by 1; each withdrawn claim voids its strike record, which recomputes the account's `strike_points` and may return that account's standing from `LIMITED` to `ACTIVE`; and finally `withdrawn_count` increments by 1 with the abuse score recomputed."

    Design: Difficulty/compensating_invariant/notice_withdrawal_returns_strike_points_to_the_pre_process_value
    """
    scene = _two_complainants_one_account()
    account_id = scene["account"]["id"]
    items = scene["items"]

    baseline = get_account(account_id)
    baseline_points = float(baseline["strike_points"])
    assert baseline_points == 10.00
    assert baseline["standing"] == "ACTIVE"
    baseline_strikes, _ = list_account_strikes(account_id)
    baseline_strike_id = baseline_strikes[0]["id"]

    orbit_notice = create_processed_notice(
        scene["orbit"]["id"],
        [items[0]["content_url"], items[1]["content_url"]],
    )
    after_process = get_account(account_id)
    assert float(after_process["strike_points"]) == 30.00
    assert after_process["standing"] == "LIMITED"
    assert after_process["upload_restricted"] is True

    validate_success(_withdraw_notice(api, orbit_notice["id"], scene["orbit"]["id"]))

    compensated = get_account(account_id)
    assert float(compensated["strike_points"]) == baseline_points
    assert compensated["standing"] == "ACTIVE"
    assert compensated["upload_restricted"] is False

    _, voided_meta = list_account_strikes(account_id, params={"status": "VOIDED"})
    assert voided_meta["total_count"] == 2
    surviving = get_success_data(api.get_strike(baseline_strike_id, OFFICER))
    assert surviving["status"] == "ACTIVE"
    assert float(surviving["effective_points"]) == 10.00


def test_withdrawing_a_processed_notice_returns_available_content_count_to_the_baseline(api):
    """PRD §2.11: "On an account, `available_content_count` tracks the number of its content items whose `availability_status` is `AVAILABLE` or `RESTORED`, and `notified_count` tracks how many takedown notifications have been delivered to the subscriber."

    Design: Difficulty/compensating_invariant/notice_withdrawal_returns_strike_points_to_the_pre_process_value
    """
    scene = _two_complainants_one_account()
    account_id = scene["account"]["id"]
    items = scene["items"]

    baseline = get_account(account_id)
    baseline_available = baseline["available_content_count"]
    assert baseline_available == 2

    orbit_notice = create_processed_notice(
        scene["orbit"]["id"],
        [items[0]["content_url"], items[1]["content_url"]],
    )
    assert get_account(account_id)["available_content_count"] == 0

    validate_success(_withdraw_notice(api, orbit_notice["id"], scene["orbit"]["id"]))

    compensated = get_account(account_id)
    assert compensated["available_content_count"] == baseline_available

    for index in (0, 1):
        restored = get_content_item(items[index]["id"])
        assert restored["availability_status"] == "RESTORED"
        assert restored["dispute_status"] == "RESOLVED"

    untouched = get_content_item(items[2]["id"])
    assert untouched["availability_status"] == "DISABLED"
    assert untouched["dispute_status"] == "UNDER_NOTICE"

    assert get_notice(orbit_notice["id"])["status"] == "WITHDRAWN"
    _, withdrawn_meta = list_claims(
        params={"notice_id": orbit_notice["id"], "status": "WITHDRAWN"}
    )
    assert withdrawn_meta["total_count"] == 2
    assert get_rights_holder(scene["orbit"]["id"])["withdrawn_count"] == 1


def test_the_strike_summary_reconciles_with_the_compensated_point_total(api):
    """PRD §3.8: "Only strike records whose `status` is `ACTIVE` or `DECAYED` are included; those in `EXPIRED` or `VOIDED` are excluded entirely."

    Design: Difficulty/compensating_invariant/notice_withdrawal_returns_strike_points_to_the_pre_process_value
    """
    scene = _two_complainants_one_account()
    account_id = scene["account"]["id"]
    items = scene["items"]

    baseline_summary = strike_summary(account_id)
    baseline_points = float(baseline_summary["strike_points"])
    assert baseline_points == 10.00
    assert baseline_summary["active_strike_count"] == 1
    assert baseline_summary["voided_strike_count"] == 0

    orbit_notice = create_processed_notice(
        scene["orbit"]["id"],
        [items[0]["content_url"], items[1]["content_url"]],
    )
    assert float(strike_summary(account_id)["strike_points"]) == 30.00

    validate_success(_withdraw_notice(api, orbit_notice["id"], scene["orbit"]["id"]))

    summary = strike_summary(account_id)
    assert float(summary["strike_points"]) == baseline_points
    assert summary["active_strike_count"] == 1
    assert summary["voided_strike_count"] == 2
    assert summary["standing"] == "ACTIVE"
    assert float(get_account(account_id)["strike_points"]) == baseline_points

    assert get_notice(scene["meridian_notice"]["id"])["status"] == "PROCESSED"


# ---------------------------------------------------------------------------
# compensating_invariant —
# claim_restoration_returns_available_content_count_to_the_pre_disable_value
# ---------------------------------------------------------------------------


def test_restoring_a_claim_returns_available_content_count_to_the_pre_disable_value(api):
    """PRD §2.11: "On an account, `available_content_count` tracks the number of its content items whose `availability_status` is `AVAILABLE` or `RESTORED`, and `notified_count` tracks how many takedown notifications have been delivered to the subscriber."

    Design: Difficulty/compensating_invariant/claim_restoration_returns_available_content_count_to_the_pre_disable_value
    """
    scene = _forwarded_counter_notice_scene()
    account_id = scene["baseline_account"]["id"]
    baseline_available = scene["baseline_account"]["available_content_count"]
    assert baseline_available == 3

    disabled_state = get_account(account_id)
    assert disabled_state["available_content_count"] == 2
    assert disabled_state["notified_count"] == 1

    restore_claim(scene["claim"]["id"])

    compensated = get_account(account_id)
    assert compensated["available_content_count"] == baseline_available
    assert compensated["notified_count"] == 1

    _, restored_meta = list_account_content_items(
        account_id, params={"availability_status": "RESTORED"}
    )
    assert restored_meta["total_count"] == 1
    _, available_meta = list_account_content_items(
        account_id, params={"availability_status": "AVAILABLE"}
    )
    assert available_meta["total_count"] == 2


def test_restoring_a_claim_voids_its_strike_and_closes_the_parent_notice(api):
    """PRD §3.7: "On success the claim moves `RESTORATION_SCHEDULED → RESTORED` and the governing counter-notice moves `RESTORATION_SCHEDULED → RESTORED` with it; the content item's access dimension moves `DISABLED → RESTORED` with `restored_at` stamped from the logical clock and the owning account's `available_content_count` incremented by 1; the item's dispute dimension moves `RESTORATION_PENDING → RESOLVED`; the strike record this claim produced is voided, which recomputes the account's `strike_points`; and if every sibling claim of the same notice has now reached a terminal state, the notice auto-closes."

    Design: Difficulty/compensating_invariant/claim_restoration_returns_available_content_count_to_the_pre_disable_value
    """
    scene = _forwarded_counter_notice_scene()
    account_id = scene["baseline_account"]["id"]
    baseline_points = float(scene["baseline_account"]["strike_points"])
    assert baseline_points == 0.00
    assert float(get_account(account_id)["strike_points"]) == 10.00

    restored_claim = restore_claim(scene["claim"]["id"])
    assert restored_claim["status"] == "RESTORED"

    counter = get_counter_notice(scene["counter_notice"]["id"])
    assert counter["status"] == "RESTORED"

    item = get_content_item(scene["items"][0]["id"])
    assert item["availability_status"] == "RESTORED"
    assert item["dispute_status"] == "RESOLVED"
    assert_instant_equals(item["restored_at"], "2026-08-14T00:00:00Z", "restored_at")

    assert get_notice(scene["notice"]["id"])["status"] == "CLOSED"

    _, voided_meta = validate_paginated(
        api.list_claim_strikes(scene["claim"]["id"], AGENT, {"status": "VOIDED"})
    )
    assert voided_meta["total_count"] == 1

    compensated = get_account(account_id)
    assert float(compensated["strike_points"]) == baseline_points
    assert compensated["standing"] == "ACTIVE"
