"""Declared state transitions, their guards and their cascades.

Every test builds its whole world through the public API: the server is
restarted before each test, so nothing survives between them.
"""
from test_helpers import (
    AGENT,
    CLOCK_START_ISO,
    OFFICER,
    ApiErrorId,
    assert_instant_equals,
    create_account,
    create_content_item,
    create_content_item_payload,
    create_counter_notice,
    create_draft_agent,
    create_enrolled_rights_holder,
    create_forwarded_counter_notice,
    create_ingestion_batch,
    create_ingestion_batch_payload,
    create_notice,
    create_processed_notice,
    create_provider,
    create_reference_file_payload,
    create_submitted_agent,
    create_validated_notice,
    execute_termination_case,
    file_termination_appeal,
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
    list_claims,
    make_compliance_officer_headers,
    make_rights_holder_rep_headers,
    make_subscriber_headers,
    process_notice,
    publish_contact,
    register_agent,
    set_clock,
    setup_disabled_claim,
    setup_documented_provider,
    shift_iso,
    strike_summary,
    validate_error,
    validate_notice,
    validate_paginated,
    validate_success,
)

REGISTRATION_TERM_DAYS = 1095


def _total_count(response) -> int:
    """The size of a filtered collection, taken from the list envelope."""
    _, meta = validate_paginated(response)
    return meta["total_count"]


def _notice_with_one_item(tier: str = "STANDARD"):
    """A documented provider, one subscriber account holding one AVAILABLE
    item, and one ENROLLED complaining rights holder."""
    setup = setup_documented_provider()
    account = create_account(setup["provider"]["id"])
    item = create_content_item(account["id"])
    holder = create_enrolled_rights_holder(tier)
    return setup, account, item, holder


def _terminated_account_with_four_strikes():
    """Four claims from one notice put the account at 40.00 points, which
    opens and then executes a termination case under officer-01."""
    setup = setup_documented_provider()
    account = create_account(setup["provider"]["id"])
    items = [create_content_item(account["id"]) for _ in range(4)]
    holder = create_enrolled_rights_holder("STANDARD")
    notice = create_processed_notice(holder["id"], [i["content_url"] for i in items])
    cases, _ = list_account_termination_cases(account["id"], None, {"status": "OPEN"})
    assert len(cases) == 1, f"exactly one OPEN termination case, got {cases}"
    execute_termination_case(cases[0]["id"], "officer-01")
    return setup, account, items, holder, notice, cases[0]


def test_registering_a_reference_work_leaves_it_pending_and_outside_the_matching_pool(api):
    """PRD §3.3: "A new file enters `status` `PENDING` with `activated_at` null
    and `match_count` 0, and it counts against the allowance immediately: if
    registering it would push the count of the holder's files in `PENDING` or
    `ACTIVE` above `reference_file_quota`, the request is refused with
    `ERR_REFERENCE_QUOTA_EXCEEDED`."

    Design: Corner/state_machines/reference_file_starts_pending_before_activation
    """
    set_clock(CLOCK_START_ISO)
    create_provider()
    holder = create_enrolled_rights_holder("STANDARD")
    rep = make_rights_holder_rep_headers(holder["id"])

    reference = validate_success(
        api.create_reference_file(
            create_reference_file_payload(
                holder["id"],
                work_title="Orbit Vol. 1, track 3",
                registration_number="SR0000991122",
            ),
            rep,
        ),
        expected_status=201,
    )

    assert reference["status"] == "PENDING"
    assert reference["activated_at"] is None
    assert reference["match_count"] == 0
    assert _total_count(
        api.list_rights_holder_reference_files(holder["id"], rep, {"status": "ACTIVE"})
    ) == 0


def test_submitting_a_drafted_designation_stamps_submitted_at_without_touching_the_provider(api):
    """PRD §3.1: "Submitting the designation to the copyright office directory
    moves it `DRAFT → SUBMITTED`, and requires that `agent_email`,
    `agent_phone` and `mailing_address` are all non-empty."

    Design: Corner/state_machines/submit_designated_agent_moves_draft_to_submitted
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    provider_after_contact = publish_contact(provider["id"])
    agent = create_draft_agent(provider["id"])

    submitted = validate_success(api.submit_designated_agent(agent["id"], OFFICER))

    assert submitted["registration_status"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_at"], CLOCK_START_ISO, "submitted_at")
    assert submitted["registered_at"] is None
    assert submitted["expires_at"] is None

    provider_now = get_provider(provider["id"])
    assert provider_now["designated_agent_registered"] is False
    assert provider_now["version"] == provider_after_contact["version"]
    assert provider_now["safe_harbor_status"] == "FORFEITED"


def test_registering_an_agent_before_the_public_contact_is_published_is_refused(api):
    """PRD §3.1: "The provider's `public_contact_published_at` must already be
    non-null, or the request fails with `ERR_PUBLIC_CONTACT_NOT_PUBLISHED`; the
    provider must not already hold another designation in `REGISTERED`, or the
    request fails with `ERR_AGENT_ALREADY_REGISTERED`; and the supplied provider
    version must match, per Section 2.7."

    Design: Corner/state_machines/register_agent_before_contact_publication_is_blocked_at_priority_8
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    agent = create_submitted_agent(provider["id"])
    version_before = get_provider(provider["id"])["version"]

    validate_error(
        api.register_designated_agent(
            agent["id"], {"expected_provider_version": version_before}, OFFICER
        ),
        ApiErrorId.ERR_PUBLIC_CONTACT_NOT_PUBLISHED.value,
    )

    agent_now = validate_success(api.get_designated_agent(agent["id"], OFFICER))
    assert agent_now["registration_status"] == "SUBMITTED"
    assert agent_now["registered_at"] is None

    provider_now = get_provider(provider["id"])
    assert provider_now["designated_agent_registered"] is False
    assert provider_now["version"] == version_before


def test_publishing_an_already_published_policy_revision_is_refused(api):
    """PRD §3.1: "Publishing something that is already `PUBLISHED` or
    `SUPERSEDED` is refused with `ERR_INVALID_POLICY_STATE`."

    Design: Corner/state_machines/publish_policy_twice_returns_invalid_policy_state
    """
    setup = setup_documented_provider()
    provider, policy = setup["provider"], setup["policy"]
    version_before = get_provider(provider["id"])["version"]

    validate_error(
        api.publish_policy(policy["id"], version_before, OFFICER),
        ApiErrorId.ERR_INVALID_POLICY_STATE.value,
    )

    policy_now = validate_success(api.get_policy(policy["id"], OFFICER))
    assert policy_now["status"] == "PUBLISHED"
    assert_instant_equals(policy_now["published_at"], CLOCK_START_ISO, "published_at")
    assert get_provider(provider["id"])["version"] == version_before
    assert _total_count(
        api.list_provider_policies(provider["id"], OFFICER, {"status": "PUBLISHED"})
    ) == 1


def test_validating_an_already_validated_notice_is_refused_and_rescores_nothing(api):
    """PRD §3.5: "Withdrawing a notice that is already `REJECTED`, `WITHDRAWN`
    or `CLOSED` is refused with `ERR_INVALID_NOTICE_STATE`, as is validating a
    notice that is not `RECEIVED` or processing one that is not `VALIDATED`."

    Design: Corner/state_machines/validate_notice_twice_returns_invalid_notice_state
    """
    _, _, item, holder = _notice_with_one_item()
    notice = create_validated_notice(holder["id"], [item["content_url"]])
    assert notice["status"] == "VALIDATED"

    set_clock(shift_iso(CLOCK_START_ISO, days=1))
    validate_error(
        api.validate_notice(notice["id"], AGENT),
        ApiErrorId.ERR_INVALID_NOTICE_STATE.value,
    )

    notice_now = get_notice(notice["id"])
    assert notice_now["status"] == "VALIDATED"
    assert notice_now["completeness_score"] == 100
    assert notice_now["compliance_variant"] == "SUBSTANTIAL_COMPLIANCE"
    assert_instant_equals(notice_now["validated_at"], CLOCK_START_ISO, "validated_at")
    _, meta = list_claims(AGENT, {"notice_id": notice["id"]})
    assert meta["total_count"] == 0


def test_a_rejected_notice_accepts_neither_processing_nor_withdrawal(api):
    """PRD §3.5: "Withdrawing a notice that is already `REJECTED`, `WITHDRAWN`
    or `CLOSED` is refused with `ERR_INVALID_NOTICE_STATE`, as is validating a
    notice that is not `RECEIVED` or processing one that is not `VALIDATED`."

    Design: Corner/state_machines/process_a_rejected_notice_is_locked_out_of_every_transition
    """
    _, _, item, holder = _notice_with_one_item()
    notice = create_notice(holder["id"], [item["content_url"]], signature_present=False)
    rejected = validate_notice(notice["id"])
    assert rejected["status"] == "REJECTED"

    validate_error(
        api.process_notice(notice["id"], AGENT),
        ApiErrorId.ERR_INVALID_NOTICE_STATE.value,
    )
    validate_error(
        api.withdraw_notice(notice["id"], make_rights_holder_rep_headers(holder["id"])),
        ApiErrorId.ERR_INVALID_NOTICE_STATE.value,
    )

    notice_now = get_notice(notice["id"])
    assert notice_now["status"] == "REJECTED"
    assert notice_now["completeness_score"] == 92
    assert notice_now["rejection_reason"] == "CORE_ELEMENT_MISSING:signature_present"
    assert notice_now["processed_at"] is None
    assert notice_now["matched_claim_count"] == 0

    holder_now = get_rights_holder(holder["id"])
    assert holder_now["rejected_count"] == 1
    assert holder_now["withdrawn_count"] == 0
    assert holder_now["abuse_score"] == 40.00
    assert get_content_item(item["id"])["availability_status"] == "AVAILABLE"


def test_publishing_the_public_contact_stamps_the_url_and_bumps_the_provider_version(api):
    """PRD §3.1: "The officer supplies the `public_contact_url` at which the
    designated agent's contact details can be read; the system stores that URL,
    stamps `public_contact_published_at` from the logical clock, increments the
    provider's `version` by 1, and recomputes the compliance score and posture —
    which, on a provider that still lacks a registered agent, leaves the posture
    at `FORFEITED` because the agent gate fails first."

    Design: Corner/state_machines/publish_contact_stamps_url_timestamp_and_bumps_provider_version
    """
    set_clock(CLOCK_START_ISO)
    provider = create_provider()
    assert provider["version"] == 1

    contact_url = "https://northstar.example/legal/dmca-agent"
    published = validate_success(
        api.publish_provider_contact(provider["id"], contact_url, OFFICER)
    )

    assert published["public_contact_url"] == contact_url
    assert_instant_equals(
        published["public_contact_published_at"], CLOCK_START_ISO,
        "public_contact_published_at",
    )
    assert published["version"] == 2
    assert published["safe_harbor_status"] == "FORFEITED"
    assert published["safe_harbor_score"] == 0
    assert published["designated_agent_registered"] is False


def test_a_designation_walks_registered_lapsed_submitted_and_registered_again(api):
    """PRD §3.1: "The same operation also serves re-designation after a term has
    run out, moving a designation `LAPSED → SUBMITTED`; on that path
    `submitted_at` is overwritten with the current clock while `registered_at`
    and `expires_at` are deliberately retained until the next registration
    overwrites them."

    Design: Corner/state_machines/designated_agent_cycles_registered_lapsed_submitted_registered
    """
    setup = setup_documented_provider()
    provider, agent = setup["provider"], setup["agent"]
    first_term_end = shift_iso(CLOCK_START_ISO, days=REGISTRATION_TERM_DAYS)
    assert agent["registration_status"] == "REGISTERED"
    assert_instant_equals(agent["expires_at"], first_term_end, "expires_at")

    set_clock(first_term_end)
    lapsed = validate_success(api.lapse_designated_agent(agent["id"], OFFICER))
    assert lapsed["registration_status"] == "LAPSED"
    provider_after_lapse = get_provider(provider["id"])
    assert provider_after_lapse["designated_agent_registered"] is False
    assert provider_after_lapse["safe_harbor_status"] == "FORFEITED"
    assert provider_after_lapse["safe_harbor_score"] == 0

    resubmitted = validate_success(api.submit_designated_agent(agent["id"], OFFICER))
    assert resubmitted["registration_status"] == "SUBMITTED"
    assert_instant_equals(resubmitted["submitted_at"], first_term_end, "submitted_at")
    assert_instant_equals(resubmitted["registered_at"], CLOCK_START_ISO, "registered_at")
    assert_instant_equals(resubmitted["expires_at"], first_term_end, "expires_at")

    reregistered = register_agent(agent["id"], provider["id"])
    assert reregistered["registration_status"] == "REGISTERED"
    assert_instant_equals(reregistered["registered_at"], first_term_end, "registered_at")
    assert_instant_equals(
        reregistered["expires_at"],
        shift_iso(first_term_end, days=REGISTRATION_TERM_DAYS),
        "expires_at",
    )

    provider_now = get_provider(provider["id"])
    assert provider_now["designated_agent_registered"] is True
    assert provider_now["safe_harbor_status"] == "ELIGIBLE"
    assert provider_now["safe_harbor_score"] == 100
    assert _total_count(
        api.list_provider_designated_agents(provider["id"], OFFICER)
    ) == 1


def test_upholding_the_last_claim_auto_closes_its_notice(api):
    """PRD §3.6: "Finally, a processed notice **auto-closes**: as soon as
    `matched_claim_count` is at least 1 and every one of the notice's child
    claims has reached one of the terminal claim states `RESTORED`, `UPHELD` or
    `WITHDRAWN`, the notice transitions `PROCESSED → CLOSED` of its own accord,
    and no further claim may ever be created against it."

    Design: Corner/state_machines/uphold_last_claim_bubbles_the_notice_to_closed
    """
    scene = setup_disabled_claim()
    claim, notice = scene["claim"], scene["notice"]
    account, item = scene["account"], scene["item"]

    set_clock(shift_iso(CLOCK_START_ISO, days=claim["counter_notice_window_days"]))
    upheld = validate_success(api.uphold_claim(claim["id"], AGENT))

    assert upheld["status"] == "UPHELD"
    assert get_notice(notice["id"])["status"] == "CLOSED"

    item_now = get_content_item(item["id"])
    assert item_now["availability_status"] == "DISABLED"
    assert item_now["dispute_status"] == "RESOLVED"

    strikes, meta = validate_paginated(api.list_claim_strikes(claim["id"], AGENT))
    assert meta["total_count"] == 2
    assert sorted(s["reason"] for s in strikes) == ["CLAIM_UPHELD", "NOTICE_PROCESSED"]

    account_now = get_account(account["id"])
    assert account_now["strike_points"] == 20.00
    assert account_now["standing"] == "LIMITED"
    assert account_now["upload_restricted"] is True
    assert _total_count(
        api.list_account_termination_cases(account["id"], OFFICER)
    ) == 0


def test_upholding_a_claim_inside_the_counter_notice_window_is_refused(api):
    """PRD §3.7: "From `DISABLED → UPHELD`, the ordinary outcome when no valid
    dispute ever arrived: the logical clock must be at or after the claim's
    `disabled_at` advanced by its snapshotted `counter_notice_window_days`, and
    an earlier attempt is refused with `ERR_COUNTER_NOTICE_WINDOW_OPEN`."

    Design: Corner/state_machines/uphold_before_the_counter_notice_window_closes_returns_window_open
    """
    scene = setup_disabled_claim()
    claim, notice = scene["claim"], scene["notice"]
    account, item = scene["account"], scene["item"]

    set_clock("2026-08-30T23:59:59.999Z")
    validate_error(
        api.uphold_claim(claim["id"], AGENT),
        ApiErrorId.ERR_COUNTER_NOTICE_WINDOW_OPEN.value,
    )

    assert get_claim(claim["id"])["status"] == "DISABLED"
    assert get_content_item(item["id"])["dispute_status"] == "UNDER_NOTICE"
    assert _total_count(api.list_claim_strikes(claim["id"], AGENT)) == 1

    account_now = get_account(account["id"])
    assert account_now["strike_points"] == 10.00
    assert account_now["standing"] == "ACTIVE"
    assert get_notice(notice["id"])["status"] == "PROCESSED"


def test_restoring_a_claim_that_is_still_disabled_is_refused_as_an_illegal_state(api):
    """PRD §3.7: "Restoring access is performed by a `TakedownAgent` on a claim
    that is in `RESTORATION_SCHEDULED`; a claim in any other state is refused
    with `ERR_INVALID_CLAIM_STATE`."

    Design: Corner/state_machines/restore_a_claim_that_never_reached_restoration_scheduled_is_refused
    """
    scene = setup_disabled_claim()
    claim, account, item = scene["claim"], scene["account"], scene["item"]

    set_clock(shift_iso(CLOCK_START_ISO, days=100))
    validate_error(
        api.restore_claim(claim["id"], AGENT),
        ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
    )

    claim_now = get_claim(claim["id"])
    assert claim_now["status"] == "DISABLED"
    assert claim_now["restoration_due_at"] is None

    item_now = get_content_item(item["id"])
    assert item_now["availability_status"] == "DISABLED"
    assert item_now["restored_at"] is None
    assert get_account(account["id"])["available_content_count"] == 0


def test_a_suit_notice_on_a_forwarded_counter_notice_upholds_the_claim_and_resolves_the_item(api):
    """PRD §3.7: "When the suit notice arrives while the counter-notice is still
    `FORWARDED` — that is, before the restoration window has opened — it moves
    `FORWARDED → BLOCKED_BY_SUIT` and the dispute is finished on the spot."

    Design: Corner/state_machines/record_suit_notice_upholds_the_claim_and_resolves_the_item
    """
    scene = setup_disabled_claim()
    claim, notice = scene["claim"], scene["notice"]
    account, item = scene["account"], scene["item"]

    forwarded = create_forwarded_counter_notice(claim["id"], account["id"])
    assert forwarded["status"] == "FORWARDED"
    assert_instant_equals(
        forwarded["restoration_earliest_at"], "2026-08-14T00:00:00Z",
        "restoration_earliest_at",
    )
    assert_instant_equals(
        forwarded["restoration_deadline_at"], "2026-08-20T00:00:00Z",
        "restoration_deadline_at",
    )

    set_clock("2026-08-13T00:00:00Z")
    assert get_counter_notice(forwarded["id"])["status"] == "FORWARDED"

    blocked = validate_success(api.record_suit_notice(forwarded["id"], AGENT))
    assert blocked["status"] == "BLOCKED_BY_SUIT"
    assert_instant_equals(
        blocked["suit_notice_at"], "2026-08-13T00:00:00Z", "suit_notice_at",
    )
    assert_instant_equals(
        blocked["restoration_earliest_at"], "2026-08-14T00:00:00Z",
        "restoration_earliest_at",
    )
    assert_instant_equals(
        blocked["restoration_deadline_at"], "2026-08-20T00:00:00Z",
        "restoration_deadline_at",
    )

    claim_now = get_claim(claim["id"])
    assert claim_now["status"] == "UPHELD"
    assert claim_now["restoration_due_at"] is None

    item_now = get_content_item(item["id"])
    assert item_now["availability_status"] == "DISABLED"
    assert item_now["dispute_status"] == "RESOLVED"

    account_now = get_account(account["id"])
    assert account_now["available_content_count"] == 0
    assert account_now["strike_points"] == 10.00
    assert get_notice(notice["id"])["status"] == "CLOSED"

    validate_error(
        api.restore_claim(claim["id"], AGENT),
        ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
    )


def test_a_counter_notice_missing_jurisdiction_consent_is_rejected_at_score_94(api):
    """PRD §3.7: "A counter-notice passes only when `completeness_score` is at
    least 94 and neither consent is missing — which means a counter-notice that
    omits only consent to jurisdiction scores 94, meets the threshold, and is
    nonetheless rejected."

    Design: Corner/state_machines/counter_notice_missing_jurisdiction_consent_branches_to_rejected
    """
    scene = setup_disabled_claim()
    claim, account, item = scene["claim"], scene["account"], scene["item"]

    counter = create_counter_notice(
        claim["id"], account["id"], consent_to_jurisdiction=False,
    )
    rejected = validate_success(api.validate_counter_notice(counter["id"], AGENT))

    assert rejected["status"] == "REJECTED"
    assert rejected["completeness_score"] == 94
    assert rejected["rejection_reason"] == "CONSENT_MISSING:consent_to_jurisdiction"
    assert rejected["forwarded_at"] is None
    assert rejected["restoration_earliest_at"] is None

    assert get_claim(claim["id"])["status"] == "DISABLED"
    item_now = get_content_item(item["id"])
    assert item_now["availability_status"] == "DISABLED"
    assert item_now["dispute_status"] == "UNDER_NOTICE"
    assert get_account(account["id"])["available_content_count"] == 0


def test_completing_an_ingestion_batch_aggregates_its_notices_match_counts(api):
    """PRD §3.4: "The rep closes the batch with a completion action that moves it
    `PROCESSING → COMPLETED`, permitted only once every notice belonging to the
    batch has reached `PROCESSED`, `REJECTED`, `WITHDRAWN` or `CLOSED`;
    completion then aggregates the batch's outcome, summing each notice's
    `matched_claim_count` into `matched_count` and each notice's
    `unmatched_url_count` into `unmatched_count`."

    Design: Corner/state_machines/complete_ingestion_batch_derives_matched_and_unmatched_counts_from_children
    """
    setup, _, item, holder = _notice_with_one_item("VERIFIED")
    assert setup["provider"]["safe_harbor_status"] == "ELIGIBLE"
    rep = make_rights_holder_rep_headers(holder["id"])

    batch = create_ingestion_batch(holder["id"], 10)
    assert batch["status"] == "ACCEPTED"

    notice = create_notice(
        holder["id"],
        [item["content_url"], "https://northstar.example/v/nothing-here"],
        headers=rep,
        submission_channel="API_BULK",
        ingestion_batch_id=batch["id"],
    )
    batch_after_notice = validate_success(api.get_ingestion_batch(batch["id"], rep))
    assert batch_after_notice["status"] == "PROCESSING"
    assert batch_after_notice["notices_created"] == 1

    validate_notice(notice["id"])
    processed = process_notice(notice["id"])
    assert processed["compliance_variant"] == "STRICT_COMPLIANCE"
    assert processed["completeness_score"] == 100
    assert processed["matched_claim_count"] == 1
    assert processed["unmatched_url_count"] == 1

    completed = validate_success(api.complete_ingestion_batch(batch["id"], rep))
    assert completed["status"] == "COMPLETED"
    assert completed["matched_count"] == 1
    assert completed["unmatched_count"] == 1
    assert completed["item_count"] == 10
    assert completed["rolling_item_total"] == 10
    assert _total_count(
        api.list_notices(AGENT, {"ingestion_batch_id": batch["id"]})
    ) == 1


def test_deciding_an_appeal_upheld_closes_the_case_and_voids_no_strike(api):
    """PRD §3.8: "An `UPHELD` decision moves the case `APPEAL_FILED → CLOSED`,
    leaves the account `TERMINATED`, and touches no strike record."

    Design: Corner/state_machines/decide_appeal_upheld_closes_the_case_and_leaves_every_strike_standing
    """
    _, account, items, _, _, case = _terminated_account_with_four_strikes()

    set_clock(shift_iso(CLOCK_START_ISO, days=4))
    file_termination_appeal(case["id"], account["id"])

    decided = validate_success(
        api.decide_termination_appeal(
            case["id"], "UPHELD", make_compliance_officer_headers("officer-02")
        )
    )
    assert decided["status"] == "CLOSED"
    assert decided["decision"] == "UPHELD"
    assert decided["decided_by_user_id"] == "officer-02"

    account_now = get_account(account["id"])
    assert account_now["standing"] == "TERMINATED"
    assert account_now["terminated_at"] is not None
    assert account_now["upload_restricted"] is True
    assert account_now["strike_points"] == 40.00
    assert account_now["available_content_count"] == 0

    _, voided_meta = list_account_strikes(account["id"], None, {"status": "VOIDED"})
    assert voided_meta["total_count"] == 0
    _, active_meta = list_account_strikes(account["id"], None, {"status": "ACTIVE"})
    assert active_meta["total_count"] == 4

    for item in items:
        assert get_content_item(item["id"])["availability_status"] == "DISABLED"

    validate_error(
        api.decide_termination_appeal(
            case["id"], "UPHELD", make_compliance_officer_headers("officer-02")
        ),
        ApiErrorId.ERR_INVALID_TERMINATION_STATE.value,
    )
    validate_error(
        api.reinstate_account(account["id"], OFFICER),
        ApiErrorId.ERR_INVALID_ACCOUNT_STANDING.value,
    )


def test_reinstatement_waits_until_decay_drops_the_total_below_the_limitation_threshold(api):
    """PRD §3.8: "Reinstatement moves the account `TERMINATED → ACTIVE`,
    clearing `terminated_at` and `upload_restricted`, but only when the account
    is genuinely `TERMINATED` **and** its recomputed `strike_points` is strictly
    below `limitation_threshold_points` — which in practice only happens once the
    strikes have decayed or expired on their own."

    Design: Corner/state_machines/reinstate_is_refused_until_decay_drops_the_points_below_the_limitation_threshold
    """
    _, account, items, _, _, case = _terminated_account_with_four_strikes()

    set_clock(shift_iso(CLOCK_START_ISO, days=90))
    summary = strike_summary(account["id"])
    assert summary["strike_points"] == 26.00
    assert summary["decayed_strike_count"] == 4
    assert get_termination_case(case["id"])["status"] == "CLOSED"

    validate_error(
        api.reinstate_account(account["id"], OFFICER),
        ApiErrorId.ERR_INVALID_ACCOUNT_STANDING.value,
    )
    assert get_account(account["id"])["standing"] == "TERMINATED"

    set_clock(shift_iso(CLOCK_START_ISO, days=180))
    assert strike_summary(account["id"])["strike_points"] == 13.00

    reinstated = validate_success(api.reinstate_account(account["id"], OFFICER))
    assert reinstated["standing"] == "ACTIVE"
    assert reinstated["terminated_at"] is None
    assert reinstated["upload_restricted"] is False
    assert reinstated["strike_points"] == 13.00

    _, voided_meta = list_account_strikes(account["id"], None, {"status": "VOIDED"})
    assert voided_meta["total_count"] == 0
    assert get_termination_case(case["id"])["status"] == "CLOSED"

    for item in items:
        assert get_content_item(item["id"])["availability_status"] == "DISABLED"
    assert get_account(account["id"])["available_content_count"] == 0

    validate_success(
        api.create_content_item(
            create_content_item_payload(account["id"]),
            make_subscriber_headers(account["id"]),
        ),
        expected_status=201,
    )


def test_rejecting_an_empty_batch_releases_its_items_from_the_rolling_window(api):
    """PRD §3.4: "Rejection matters commercially as well as administratively: a
    rejected batch's `item_count` leaves the rolling window, so the holder
    recovers that allowance for subsequent batches."

    Design: Corner/state_machines/reject_an_empty_ingestion_batch_drops_its_items_from_the_rolling_quota
    """
    setup_documented_provider()
    holder = create_enrolled_rights_holder("VERIFIED")
    rep = make_rights_holder_rep_headers(holder["id"])
    assert holder["daily_item_quota"] == 500

    first = create_ingestion_batch(holder["id"], 400)

    rejected = validate_success(api.reject_ingestion_batch(first["id"], OFFICER))
    assert rejected["status"] == "REJECTED"
    assert rejected["notices_created"] == 0

    second = validate_success(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 400), rep
        ),
        expected_status=201,
    )
    assert second["rolling_item_total"] == 400

    third = validate_success(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 100), rep
        ),
        expected_status=201,
    )
    assert third["rolling_item_total"] == 500

    validate_error(
        api.create_ingestion_batch(
            create_ingestion_batch_payload(holder["id"], 1), rep
        ),
        ApiErrorId.ERR_INGESTION_WINDOW_QUOTA_EXCEEDED.value,
    )
    assert _total_count(
        api.list_rights_holder_ingestion_batches(
            holder["id"], rep, {"status": "ACCEPTED"}
        )
    ) == 2

    validate_error(
        api.reject_ingestion_batch(first["id"], OFFICER),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value,
    )
