"""Sponsorship: the booth review loop, the contract gate, lead capture rules and
the two lead-scoring variants."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_lead,
    assert_booth,
    make_attendee_headers,
    make_sponsor_headers,
    new_event,
    add_ticket_type,
    add_track,
    add_session,
    publish_event,
    start_event,
    add_registration,
    pay_registration,
    check_in,
    record_watch_minutes,
    add_sponsor,
    sign_contract,
    add_booth,
    submit_booth,
    log_interaction,
    read_booth,
    read_lead,
    read_sponsor,
    setup_published_event,
    setup_sponsor_with_booth,
    setup_live_booth_with_lead,
)

ORG = TEST_USERS["organizer_headers"]


# ==========================================================================
# The two lead-scoring variants
# ==========================================================================

def _expo_b_lead_with_two_downloads():
    """Expo B: a CHECKED_IN attendee with 120 watched minutes whose lead carries
    one booth visit and two downloads, so the booth-weighted score is
    1*3 + 2*5 = 13."""
    ctx = setup_live_booth_with_lead(
        watched_minutes=120,
        attendee_email="lead@example.com",
        sponsor_overrides={
            "name": "Acme Cloud", "package_tier": "GOLD",
            "contact_email": "sales@acme.example",
        },
        booth_overrides={"headline": "Acme Cloud Booth", "lead_quota": 2},
    )
    log_interaction(ctx["lead"]["id"], ctx["sponsor"]["id"], "DOWNLOAD")
    ctx["lead"] = log_interaction(ctx["lead"]["id"], ctx["sponsor"]["id"], "DOWNLOAD")
    return ctx


def test_booth_weighted_variant_scores_only_from_booth_counters(api):
    """PRD 3.8: "The booth-weighted variant takes three points for each of the
    lead's `booth_visits` plus five points for each of its `doc_downloads`."
    PRD 3.8: "The booth-weighted variant runs at lead capture and after every
    booth interaction. A `SponsorUser` logs an interaction by supplying an
    `interaction_type`: a `VISIT` increments the lead's `booth_visits` and a
    `DOWNLOAD` increments its `doc_downloads`, and the lead is then re-scored
    with the booth-weighted variant, refreshing `score` and `is_hot`."

    Design: Difficulty/dual_variant_calc/lead_score_booth_weighted_vs_engagement_weighted_diverges
    """
    ctx = _expo_b_lead_with_two_downloads()
    lead = ctx["lead"]

    assert_lead(lead)
    assert lead["booth_visits"] == 1
    assert lead["doc_downloads"] == 2
    assert lead["score"] == 13, (
        f"Expected 1*3 + 2*5 = 13 from booth counters alone, got {lead['score']}"
    )
    assert lead["score_variant"] == "BOOTH_WEIGHTED"
    assert lead["is_hot"] is False, "13 is below the threshold of 60"


def test_engagement_weighted_rescore_folds_in_attendee_behaviour(api):
    """PRD 3.8: "The engagement-weighted variant adds to that same sum half a
    point for each minute of the linked registration's `watched_minutes` and
    twelve points for each of its `accepted_meeting_count`."
    PRD 3.8: "The engagement-weighted variant runs only when the organizer
    triggers an event-wide rescore, which walks every lead of the event, applies
    the engagement-weighted formula, sets each lead's `score_variant` to
    `ENGAGEMENT_WEIGHTED`, and returns a `rescored_count` of leads touched
    together with a `hot_lead_count` of those whose `is_hot` ended up true."
    PRD 3.8: "A lead's `is_hot` flag is then set to true when `score` is at least
    60 and false otherwise, and `score_variant` records which variant last wrote
    the score — `BOOTH_WEIGHTED` or `ENGAGEMENT_WEIGHTED`."

    Design: Difficulty/dual_variant_calc/lead_score_booth_weighted_vs_engagement_weighted_diverges
    """
    ctx = _expo_b_lead_with_two_downloads()
    assert ctx["lead"]["score"] == 13

    result = validate_success(
        api.rescore_event_leads(ctx["event"]["id"], ORG), 200
    )
    assert result["rescored_count"] == 1
    assert result["hot_lead_count"] == 1

    lead = read_lead(ctx["lead"]["id"])
    assert lead["score"] == 73, (
        f"Expected 13 + 120*0.5 = 73 after the engagement rescore, got {lead['score']}"
    )
    assert lead["score_variant"] == "ENGAGEMENT_WEIGHTED"
    assert lead["is_hot"] is True, "73 is at least 60, so is_hot flips to true"
    assert lead["booth_visits"] == 1 and lead["doc_downloads"] == 2


# ==========================================================================
# The contract gate on booth approval
# ==========================================================================

def _expo_n_submitted_booth_unsigned_contract():
    event, ticket_type = setup_published_event(event_overrides={"name": "Expo N"})
    sponsor = add_sponsor(
        event["id"], name="Umbrella Ltd", package_tier="SILVER",
        contact_email="sales@umbrella.example",
    )
    booth = add_booth(
        sponsor["id"], headline="Umbrella Booth", lead_quota=3
    )
    booth = submit_booth(booth["id"], sponsor["id"])
    return event, sponsor, booth


def test_booth_approval_is_refused_while_the_contract_is_unsigned(api):
    """PRD 3.8: "From `SUBMITTED` the organizer forks: approval moves the booth
    `SUBMITTED → APPROVED` and requires the owning sponsor's `contract_status` to
    be `SIGNED`, refusing otherwise with `ERR_CONTRACT_NOT_SIGNED`; requesting
    changes, with a `reason`, moves it `SUBMITTED → CHANGES_REQUESTED` and —
    unlike submission — leaves `revision_round` untouched, since the counter
    tracks submissions rather than review rounds."

    Design: Difficulty/cross_entity_state_dependency/booth_approval_requires_sponsor_contract_signed
    """
    event, sponsor, booth = _expo_n_submitted_booth_unsigned_contract()
    assert booth["state"] == "SUBMITTED"
    assert read_sponsor(sponsor["id"])["contract_status"] == "UNSIGNED"

    validate_error(
        api.approve_booth(booth["id"], ORG), ApiErrorId.ERR_CONTRACT_NOT_SIGNED
    )
    refreshed = read_booth(booth["id"])
    assert_booth(refreshed)
    assert refreshed["state"] == "SUBMITTED", (
        f"A refused approval must leave the booth SUBMITTED, got {refreshed['state']}"
    )
    assert refreshed["revision_round"] == 1
    assert read_sponsor(sponsor["id"])["contract_status"] == "UNSIGNED"


def test_signing_the_contract_makes_the_identical_approval_succeed(api):
    """PRD 3.8: "A new sponsor's `contract_status` is `UNSIGNED`. Marking the
    contract signed — an organizer action recording who `signed_by` — flips
    `contract_status` to `SIGNED`, and that flip is the gate on booth approval."

    Design: Difficulty/cross_entity_state_dependency/booth_approval_requires_sponsor_contract_signed
    """
    event, sponsor, booth = _expo_n_submitted_booth_unsigned_contract()
    validate_error(
        api.approve_booth(booth["id"], ORG), ApiErrorId.ERR_CONTRACT_NOT_SIGNED
    )

    signed = validate_success(
        api.sign_sponsor_contract(sponsor["id"], "Umbrella Legal", ORG), 200
    )
    assert signed["contract_status"] == "SIGNED"

    approved = validate_success(api.approve_booth(booth["id"], ORG), 200)
    assert approved["state"] == "APPROVED", (
        "Once the contract is SIGNED the same call must succeed; got "
        f"{approved['state']}"
    )
    assert approved["revision_round"] == 1, (
        "Approval does not touch the submission counter"
    )


# ==========================================================================
# Safety outranks referential consistency on lead capture
# ==========================================================================

def _two_events_booth_and_foreign_registration():
    """Booth on event 1, registration on event 2."""
    event1, _ = setup_published_event(event_overrides={"name": "Expo J1", "capacity": 50})
    sponsor, booth = setup_sponsor_with_booth(
        event1["id"],
        sponsor_overrides={
            "name": "Initech", "package_tier": "GOLD",
            "contact_email": "sales@initech.example",
        },
        booth_overrides={"headline": "Initech Booth", "lead_quota": 5},
    )
    event2, ticket2 = setup_published_event(
        event_overrides={
            "name": "Expo J2", "capacity": 50,
            "starts_at": "2026-09-20T09:00:00Z", "ends_at": "2026-09-20T18:00:00Z",
        }
    )
    foreign_registration = add_registration(
        event2["id"], ticket2["id"], "other@example.com"
    )
    return event1, booth, event2, foreign_registration


def test_lead_capture_without_consent_reports_consent_required(api):
    """PRD 3.8: "Consent is mandatory — a capture attempted with
    `marketing_consent` false is refused with `ERR_CONSENT_REQUIRED` (HTTP 422),
    and that refusal takes precedence over the cross-event check."

    Design: Difficulty/priority_pair_validation_conflict/lead_capture_reports_consent_required_over_registration_event_mismatch
    """
    event1, booth, event2, foreign_registration = _two_events_booth_and_foreign_registration()

    validate_error(
        api.capture_lead(
            booth["id"], foreign_registration["id"], False,
            make_attendee_headers(foreign_registration["id"]),
        ),
        ApiErrorId.ERR_CONSENT_REQUIRED,
    )


def test_consent_error_wins_over_the_cross_event_mismatch(api):
    """PRD 2.7: "And a lead capture that both lacks marketing consent *and* names
    a registration belonging to a different event fails with
    `ERR_CONSENT_REQUIRED`, not `ERR_REGISTRATION_EVENT_MISMATCH` — the safety
    rule sits above the referential rule."
    PRD 3.8: "The named registration must belong to the same event as the booth,
    or the capture fails with `ERR_REGISTRATION_EVENT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/lead_capture_reports_consent_required_over_registration_event_mismatch
    """
    event1, booth, event2, foreign_registration = _two_events_booth_and_foreign_registration()
    assert foreign_registration["event_id"] == event2["id"], (
        "Setup must leave the registration on a different event so both rules fail"
    )

    error = validate_error(
        api.capture_lead(
            booth["id"], foreign_registration["id"], False,
            make_attendee_headers(foreign_registration["id"]),
        ),
        ApiErrorId.ERR_CONSENT_REQUIRED,
    )
    assert error["error_id"] != ApiErrorId.ERR_REGISTRATION_EVENT_MISMATCH.value
    assert read_booth(booth["id"])["captured_lead_count"] == 0


# ==========================================================================
# Corner instances
# ==========================================================================

def test_booth_request_changes_then_resubmit_bumps_revision_round(api):
    """PRD 3.8: "The sponsor submits the booth from `DRAFT` or from
    `CHANGES_REQUESTED`, and either way the submission increments
    `revision_round` — so a booth that was drafted, submitted, sent back and
    resubmitted carries `revision_round` of 2."

    Design: Corner/state_machines/corner_booth_request_changes_then_resubmit_bumps_revision_round
    """
    event = new_event(name="Booth Loop")
    sponsor = add_sponsor(
        event["id"], name="Hooli", package_tier="BRONZE",
        contact_email="sales@hooli.example",
    )
    booth = add_booth(sponsor["id"], headline="Hooli Booth", lead_quota=1)
    booth = submit_booth(booth["id"], sponsor["id"])
    assert booth["revision_round"] == 1

    sent_back = validate_success(
        api.request_booth_changes(booth["id"], "logo too small", ORG), 200
    )
    assert sent_back["state"] == "CHANGES_REQUESTED"
    assert sent_back["revision_round"] == 1, (
        "Requesting changes leaves revision_round untouched, got "
        f"{sent_back['revision_round']}"
    )

    resubmitted = validate_success(
        api.submit_booth(booth["id"], make_sponsor_headers(sponsor["id"])), 200
    )
    assert resubmitted["state"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 2, (
        f"The second submission takes revision_round to 2, got "
        f"{resubmitted['revision_round']}"
    )


def test_event_start_promotes_approved_booth_to_live(api):
    """PRD 3.1: "Starting the event moves it `PUBLISHED → LIVE` and carries a
    side effect into the sponsorship graph: every booth of this event sitting in
    `APPROVED` is promoted to `LIVE` in the same operation."
    PRD 3.8: "An `APPROVED` booth is promoted to `LIVE` automatically when the
    event starts."

    Design: Corner/state_machines/corner_event_start_promotes_approved_booth_to_live
    """
    event = new_event(name="Go Live")
    add_ticket_type(event["id"])
    sponsor1, booth1 = setup_sponsor_with_booth(
        event["id"],
        sponsor_overrides={
            "name": "Sponsor One", "package_tier": "SILVER",
            "contact_email": "one@example.com",
        },
        booth_overrides={"headline": "One Booth", "lead_quota": 2},
    )
    sponsor2, booth2 = setup_sponsor_with_booth(
        event["id"],
        sponsor_overrides={
            "name": "Sponsor Two", "package_tier": "SILVER",
            "contact_email": "two@example.com",
        },
        booth_overrides={"headline": "Two Booth", "lead_quota": 2},
        sign=False, approve=False,
    )
    publish_event(event["id"])

    started = validate_success(api.start_event(event["id"], ORG), 200)
    assert started["state"] == "LIVE"
    assert read_booth(booth1["id"])["state"] == "LIVE", (
        "The APPROVED booth is promoted by the event start"
    )
    assert read_booth(booth2["id"])["state"] == "SUBMITTED", (
        "A booth still in SUBMITTED is untouched by the event start"
    )


def test_lead_score_capped_at_one_hundred(api):
    """PRD 3.8: "In both variants the weighted sum is rounded half up to a whole
    number exactly once, then capped at 100, and the result is written to
    `score`."

    Design: Corner/calculations/corner_lead_score_capped_at_one_hundred
    """
    ctx = setup_live_booth_with_lead(
        watched_minutes=300,
        attendee_email="cap@example.com",
        sponsor_overrides={
            "name": "Capsule", "package_tier": "BRONZE",
            "contact_email": "sales@capsule.example",
        },
        booth_overrides={"headline": "Capsule Booth", "lead_quota": 5},
    )
    assert ctx["lead"]["score"] == 3, (
        f"At capture only the single booth visit counts, got {ctx['lead']['score']}"
    )

    result = validate_success(api.rescore_event_leads(ctx["event"]["id"], ORG), 200)
    assert result["hot_lead_count"] == 1

    lead = read_lead(ctx["lead"]["id"])
    assert lead["score"] == 100, (
        f"A raw 3 + 300*0.5 = 153 must be capped at 100, got {lead['score']}"
    )
    assert lead["is_hot"] is True
    assert lead["score_variant"] == "ENGAGEMENT_WEIGHTED"


def test_hot_lead_threshold_exactly_sixty_is_hot(api):
    """PRD 3.8: "A lead's `is_hot` flag is then set to true when `score` is at
    least 60 and false otherwise, and `score_variant` records which variant last
    wrote the score — `BOOTH_WEIGHTED` or `ENGAGEMENT_WEIGHTED`."

    Design: Corner/calculations/corner_hot_lead_threshold_exactly_sixty_is_hot
    """
    ctx = setup_live_booth_with_lead(
        watched_minutes=114,
        attendee_email="sixty@example.com",
        sponsor_overrides={
            "name": "Threshold Co", "package_tier": "BRONZE",
            "contact_email": "sales@threshold.example",
        },
        booth_overrides={"headline": "Threshold Booth", "lead_quota": 5},
        pay=False,
    )
    validate_success(api.rescore_event_leads(ctx["event"]["id"], ORG), 200)

    lead = read_lead(ctx["lead"]["id"])
    assert lead["score"] == 60, (
        f"Expected 3 + 114*0.5 = 60 exactly, got {lead['score']}"
    )
    assert lead["is_hot"] is True, "A score of exactly 60 is hot"


def test_duplicate_lead_on_same_booth_returns_duplicate_lead(api):
    """PRD 3.8: "No two leads may share the same `booth_id` and
    `registration_id` pair; a repeat capture is `ERR_DUPLICATE_LEAD` (HTTP 409)."

    Design: Corner/validations/corner_duplicate_lead_on_same_booth_returns_duplicate_lead
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Dup Lead"})
    sponsor, booth = setup_sponsor_with_booth(
        event["id"],
        sponsor_overrides={
            "name": "Dupe Corp", "package_tier": "BRONZE",
            "contact_email": "sales@dupe.example",
        },
        booth_overrides={"headline": "Dupe Booth", "lead_quota": 5},
    )
    registration = add_registration(event["id"], ticket_type["id"], "dl@example.com")
    validate_success(
        api.capture_lead(
            booth["id"], registration["id"], True,
            make_attendee_headers(registration["id"]),
        ),
        201,
    )

    validate_error(
        api.capture_lead(
            booth["id"], registration["id"], True,
            make_attendee_headers(registration["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_LEAD,
    )
    assert read_booth(booth["id"])["captured_lead_count"] == 1


def test_lead_capture_across_events_returns_registration_event_mismatch(api):
    """PRD 3.8: "The named registration must belong to the same event as the
    booth, or the capture fails with `ERR_REGISTRATION_EVENT_MISMATCH`."

    Design: Corner/validations/corner_lead_capture_across_events_returns_registration_event_mismatch
    """
    event1, booth, event2, foreign_registration = _two_events_booth_and_foreign_registration()

    validate_error(
        api.capture_lead(
            booth["id"], foreign_registration["id"], True,
            make_attendee_headers(foreign_registration["id"]),
        ),
        ApiErrorId.ERR_REGISTRATION_EVENT_MISMATCH,
    )
    assert read_booth(booth["id"])["captured_lead_count"] == 0


def test_unknown_booth_returns_booth_not_found(api):
    """PRD 2.7: "Path-segment existence, left to right (the not-found codes
    above)."
    PRD 2.6: "Each entity type has its own not-found code:
    `ERR_EVENT_NOT_FOUND`, `ERR_TICKET_TYPE_NOT_FOUND`,
    `ERR_REGISTRATION_NOT_FOUND`, `ERR_TRACK_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_SPEAKER_NOT_FOUND`, `ERR_SESSION_SPEAKER_NOT_FOUND`,
    `ERR_BROADCAST_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`,
    `ERR_SPONSOR_NOT_FOUND`, `ERR_BOOTH_NOT_FOUND`, `ERR_LEAD_NOT_FOUND`,
    `ERR_MATCH_REQUEST_NOT_FOUND` and `ERR_SETTLEMENT_NOT_FOUND`, each carrying
    HTTP 404."

    Design: Corner/errors/corner_unknown_booth_returns_booth_not_found
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Ghost Booth"})
    registration = add_registration(
        event["id"], ticket_type["id"], "ghost@example.com"
    )

    validate_error(
        api.capture_lead(
            NON_EXISTENT_UUID, registration["id"], False,
            make_attendee_headers(registration["id"]),
        ),
        ApiErrorId.ERR_BOOTH_NOT_FOUND,
    )
