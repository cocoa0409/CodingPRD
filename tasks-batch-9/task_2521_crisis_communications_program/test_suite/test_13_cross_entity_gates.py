"""Gates that live on a *neighbouring* entity: one call, unchanged in every
respect, flips from refused to accepted only because a related row moved
(PRD §3.6, §3.7, §3.8)."""

from test_helpers import (
    ApiErrorId,
    assert_field,
    assert_no_write,
    assert_state,
    assert_two_decimals,
    book_interview,
    log_claim,
    queue_notice,
    read_channel,
    read_claim,
    read_interview,
    read_member,
    read_notice,
    read_statement,
    refresh,
    register_channel,
    seed_roster,
    set_clock,
    setup_activated_incident,
    setup_approved_statement,
    triage_claim,
    validate_error,
    validate_success,
    verify_channel_path,
)

# ---------------------------------------------------------------------------
# StakeholderNotice -> Statement: release waits on publication
# ---------------------------------------------------------------------------


def _queued_notice_behind_an_approved_statement():
    """A SEV2 incident carrying a HOLDING statement approved to quorum but
    deliberately left in APPROVED, plus one QUEUED EMPLOYEE notice at rank 1
    with an ``estimated_reach`` of 1000 and no embargo."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PRODUCT_RECALL",
        title="Delivery network disruption",
    )
    setup_approved_statement(
        scenario,
        statement_type="HOLDING",
        body="Deliveries are running late in two regions; we are rerouting.",
    )
    assert_state(scenario["statement"], "APPROVED", "statement")
    queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1000)
    return scenario


def test_a_notice_carrying_a_merely_approved_statement_cannot_be_released(api):
    """PRD §3.6: "The statement the notice carries must be in `PUBLISHED`, or
    `ERR_STATEMENT_NOT_PUBLISHED` (HTTP 409)."

    The notice itself is faultless — it is `QUEUED`, its rank of 1 has no
    lower-ranked sibling to wait for, it carries no embargo and the posture is
    `OPEN` — so the only thing refusing the release lives on the statement row.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_notice_release_gated_by_statement_publication
    """
    scenario = _queued_notice_behind_an_approved_statement()
    notice = scenario["notices"]["EMPLOYEE"]
    before = read_notice(notice["id"])

    validate_error(
        api.release_stakeholder_notice(notice["id"], scenario["headers"]["comms"], {}),
        ApiErrorId.ERR_STATEMENT_NOT_PUBLISHED,
        409,
    )

    after = read_notice(notice["id"])
    assert_state(after, "QUEUED", "employee notice")
    assert_field(after, "sequence_rank", 1, "employee notice")
    assert after["released_at"] is None, "a refused release must not stamp released_at"
    assert_two_decimals(after["reach_contribution"], 0.00, "reach_contribution")
    assert_no_write(before, after, "employee notice")
    incident = refresh(scenario)
    assert_two_decimals(
        incident["stakeholder_reach_index"], 0.00, "stakeholder_reach_index"
    )
    assert_field(incident, "released_notice_count", 0, "incident")


def test_publishing_the_statement_unblocks_the_identical_release(api):
    """PRD §3.6: once the carried statement reaches `PUBLISHED` the same release
    proceeds, and "a released notice's `reach_contribution` is its audience
    weight multiplied by its `estimated_reach`, divided by one thousand, rounded
    half up to two decimals", after which "The incident's
    `stakeholder_reach_index` is then rebuilt from scratch on every release".

    The `EMPLOYEE` weight of 1.00 on an ``estimated_reach`` of 1000 gives 1.00,
    and the index built from that single released notice is 1.00 as well.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_notice_release_gated_by_statement_publication
    """
    scenario = _queued_notice_behind_an_approved_statement()
    notice = scenario["notices"]["EMPLOYEE"]

    published = validate_success(
        api.publish_statement(scenario["statement"]["id"], scenario["headers"]["comms"])
    )
    assert_state(published, "PUBLISHED", "statement")

    released = validate_success(
        api.release_stakeholder_notice(notice["id"], scenario["headers"]["comms"], {})
    )

    assert_state(released, "RELEASED", "employee notice")
    assert released["released_at"].startswith("2026-08-10T09:00:00"), (
        f"released_at must be the current instant, got {released['released_at']}"
    )
    assert_two_decimals(released["reach_contribution"], 1.00, "reach_contribution")
    assert_field(released, "priority_override_used", False, "employee notice")
    assert_state(read_statement(scenario["statement"]["id"]), "PUBLISHED", "statement")
    incident = refresh(scenario)
    assert_two_decimals(
        incident["stakeholder_reach_index"], 1.00, "stakeholder_reach_index"
    )
    assert_field(incident, "released_notice_count", 1, "incident")


# ---------------------------------------------------------------------------
# MediaInterview -> TeamMember: confirmation waits on live media training
# ---------------------------------------------------------------------------


def _interview_awaiting_confirmation(media_training_expires_at):
    """A SEV2 incident whose spokesperson carries `media_training_status`
    `CURRENT` with the supplied expiry, plus one SCHEDULED interview running
    2026-08-12T14:00:00Z to 15:00:00Z with an eight-question preparation pack, so
    the pack rule cannot fire.  The clock reads 2026-08-10T09:00:00Z."""
    set_clock("2026-08-10T09:00:00Z")
    roster = seed_roster(
        spox={
            "media_training_status": "CURRENT",
            "media_training_expires_at": media_training_expires_at,
        }
    )
    scenario = setup_activated_incident(
        tier="SEV2",
        scenario_code="PLANT_INCIDENT",
        title="Warehouse safety inspection",
        roster=roster,
    )
    interview = book_interview(
        scenario,
        "2026-08-12T14:00:00Z",
        "2026-08-12T15:00:00Z",
        anticipated_question_count=8,
        outlet_name="Wire Morning Desk",
    )
    assert_state(interview, "SCHEDULED", "interview")
    assert_field(interview, "duration_minutes", 60, "interview")
    assert_field(interview, "anticipated_question_count", 8, "interview")
    return scenario


def test_a_spokesperson_whose_training_has_lapsed_cannot_be_confirmed(api):
    """PRD §3.7: "The spokesperson's `media_training_status` must be `CURRENT`
    **and** their `media_training_expires_at` must be strictly after the current
    instant, so training that lapses exactly at the confirmation instant does not
    count; failure gives `ERR_TRAINING_NOT_CURRENT` (HTTP 422)."

    The booking is otherwise perfect — `SCHEDULED`, an eight-question pack with
    three approved high-risk answers, posture `OPEN` — and the status field even
    reads `CURRENT`; only the expiry of 2026-08-05 against a 2026-08-10 clock
    refuses it, and nothing may be charged to the load ledger.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_interview_confirmation_gated_by_member_training
    """
    scenario = _interview_awaiting_confirmation("2026-08-05T00:00:00Z")
    interview = scenario["interview"]
    before = read_interview(interview["id"])

    validate_error(
        api.confirm_media_interview(
            interview["id"],
            scenario["headers"]["comms"],
            {"high_risk_answers_approved_count": 3},
        ),
        ApiErrorId.ERR_TRAINING_NOT_CURRENT,
        422,
    )

    after = read_interview(interview["id"])
    assert_state(after, "SCHEDULED", "interview")
    assert after["confirmed_at"] is None, "a refused confirmation must not stamp confirmed_at"
    assert_no_write(before, after, "interview")
    spokesperson = read_member(scenario["ids"]["spox"])
    assert_field(spokesperson, "scheduled_interview_minutes", 0, "spokesperson")
    assert_field(spokesperson, "media_training_status", "CURRENT", "spokesperson")
    assert_field(refresh(scenario), "confirmed_interview_count", 0, "incident")


def test_live_training_confirms_the_identical_booking_and_charges_the_ledger(api):
    """PRD §3.7: with training live the same confirmation advances
    `SCHEDULED → CONFIRMED`, and "On success `confirmed_at` is stamped, the
    spokesperson's `scheduled_interview_minutes` increases by exactly this
    interview's `duration_minutes`, the incident's `confirmed_interview_count` is
    recomputed, and the incident's `version` is incremented by 1."

    The only difference from the refused case is an expiry of 2026-12-01 rather
    than 2026-08-05, and the sixty-minute booking now lands on the ledger.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_interview_confirmation_gated_by_member_training
    """
    scenario = _interview_awaiting_confirmation("2026-12-01T00:00:00Z")
    interview = scenario["interview"]
    version_before = scenario["incident"]["version"]

    confirmed = validate_success(
        api.confirm_media_interview(
            interview["id"],
            scenario["headers"]["comms"],
            {"high_risk_answers_approved_count": 3},
        )
    )

    assert_state(confirmed, "CONFIRMED", "interview")
    assert confirmed["confirmed_at"].startswith("2026-08-10T09:00:00"), (
        f"confirmed_at must be the current instant, got {confirmed['confirmed_at']}"
    )
    assert_field(confirmed, "duration_minutes", 60, "interview")
    assert_field(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 60,
        "spokesperson",
    )
    incident = refresh(scenario)
    assert_field(incident, "confirmed_interview_count", 1, "incident")
    assert incident["version"] == version_before + 1, (
        "confirmation must increment the incident version by exactly 1, "
        f"got {version_before} then {incident['version']}"
    )


# ---------------------------------------------------------------------------
# MisinformationClaim -> MonitoredChannel: the platform fork waits on the path
# ---------------------------------------------------------------------------


def _triaged_claim_on_an_unverified_social_channel():
    """A SEV2 incident plus a separate SOCIAL surface left in
    ``escalation_path_state`` UNVERIFIED, carrying one TRIAGED claim whose
    ``virality_score`` of 72.00 already clears the 60.00 floor."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PRODUCT_RECALL",
        title="Viral claim about ingredient safety",
        seat_roles=["INCIDENT_LEAD"],
    )
    social = register_channel(name="Platform X", channel_type="SOCIAL")
    assert_field(social, "escalation_path_state", "UNVERIFIED", "social channel")
    log_claim(
        scenario,
        virality_score=72.00,
        channel_id=social["id"],
        claim_text="The product contains a banned additive.",
    )
    triage_claim(scenario)
    assert_state(scenario["claim"], "TRIAGED", "claim")
    scenario["social"] = social
    return scenario


def test_the_platform_fork_is_closed_while_the_channel_path_is_unverified(api):
    """PRD §3.8: the advance `TRIAGED → PLATFORM_ESCALATED` requires that "the
    channel's `escalation_path_state` must be `VERIFIED`, since an unverified path
    has nowhere to send the escalation, and failure gives
    `ERR_ESCALATION_PATH_UNVERIFIED` (HTTP 422)".

    The claim's own gate is already satisfied at 72.00 against the 60.00 floor, so
    the refusal is owed entirely to the neighbouring channel row, and PRD §3.1
    confirms the consequence: "Until that happens, the platform-escalation branch
    of misinformation handling is closed."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_platform_escalation_gated_by_channel_verification
    """
    scenario = _triaged_claim_on_an_unverified_social_channel()
    claim = scenario["claim"]
    channel_before = read_channel(scenario["social"]["id"])

    validate_error(
        api.escalate_platform(claim["id"], scenario["headers"]["listener"]),
        ApiErrorId.ERR_ESCALATION_PATH_UNVERIFIED,
        422,
    )

    after = read_claim(claim["id"])
    assert_state(after, "TRIAGED", "claim")
    assert_field(after, "resolution_branch", None, "claim")
    assert_field(after, "takedown_confirmed", False, "claim")
    assert_no_write(claim, after, "claim")
    channel_after = read_channel(scenario["social"]["id"])
    assert_field(channel_after, "open_escalation_count", 0, "social channel")
    assert_field(channel_after, "escalation_path_state", "UNVERIFIED", "social channel")
    assert_no_write(channel_before, channel_after, "social channel")


def test_verifying_the_channel_path_opens_the_identical_escalation(api):
    """PRD §3.1: "Verifying the escalation path supplies a
    `verified_contact_reference`, which the server records verbatim, moves
    `escalation_path_state` from `UNVERIFIED` to `VERIFIED`, and increments the
    channel's `version` by 1."

    With the path verified the same call now advances the claim, and PRD §3.8
    settles the bookkeeping: "On success the channel's `open_escalation_count` is
    recomputed and the channel's `version` is incremented by 1. The branch the
    claim has taken is settled at this point, though `resolution_branch` itself is
    written only when the claim closes."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_platform_escalation_gated_by_channel_verification
    """
    scenario = _triaged_claim_on_an_unverified_social_channel()
    claim = scenario["claim"]

    verified = verify_channel_path(
        scenario["social"]["id"],
        verified_contact_reference="trust-and-safety@platformx.example",
    )
    assert_field(verified, "escalation_path_state", "VERIFIED", "social channel")
    assert_field(
        verified,
        "verified_contact_reference",
        "trust-and-safety@platformx.example",
        "social channel",
    )

    escalated = validate_success(
        api.escalate_platform(claim["id"], scenario["headers"]["listener"])
    )

    assert_state(escalated, "PLATFORM_ESCALATED", "claim")
    assert_field(escalated, "resolution_branch", None, "claim")
    assert_two_decimals(escalated["virality_score"], 72.00, "virality_score")
    channel_after = read_channel(scenario["social"]["id"])
    assert_field(channel_after, "open_escalation_count", 1, "social channel")
    assert channel_after["version"] == verified["version"] + 1, (
        "platform escalation must increment the channel version by exactly 1, "
        f"got {verified['version']} then {channel_after['version']}"
    )
    assert_field(refresh(scenario), "open_claim_count", 1, "incident")
