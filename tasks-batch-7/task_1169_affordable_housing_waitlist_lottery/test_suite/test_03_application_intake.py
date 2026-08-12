"""Applicant registration and application intake: minted fields, provisional
screening, window and state gates, duplicate and household-size bounds."""
from test_helpers import (
    STARTUP_CLOCK_UTC_MS, ApiErrorId, assert_applicant, assert_application,
    fixtures, is_valid_uuid, make_applicant_headers,
    validate_error, validate_paginated, validate_success,
)

DEVELOPER = fixtures.DEVELOPER
CLERK = fixtures.CLERK


def test_applicant_register_returns_system_minted_fields(api):
    """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted
    as a UUID, with no type prefix." PRD §2.5: "the server never falls back to
    wall-clock time. At server startup, before any clock operation has been
    issued, the logical clock reads exactly `2026-05-01T00:00:00Z`."

    Design: Corner/entities/applicant_register_returns_system_minted_fields
    """
    payload = {"full_name": "Sam S", "email": "s@x.com"}
    applicant = validate_success(
        api.create_applicant(payload, fixtures.ANONYMOUS),
        expected_status=201)
    assert_applicant(applicant)
    assert "id" not in payload and is_valid_uuid(applicant["id"])
    # The single logical clock (never wall-clock) stamps created_at; with no
    # clock operation issued, it reads the startup default.
    assert applicant["created_at"] == STARTUP_CLOCK_UTC_MS


def test_application_create_mints_confirmation_code_and_provisional(api):
    """PRD §3.3: "The server assigns a `confirmation_code`, the household's
    lottery ticket string that later feeds the seeded draw." PRD §3.3:
    "because the boundary is inclusive, income exactly equal to the limit
    yields `PROVISIONALLY_ELIGIBLE` while anything above yields
    `PROVISIONALLY_OVER_INCOME`. The new application lands in `SUBMITTED`
    status, and the campaign's `applications_received_count` is recomputed."

    Design: Corner/entities/application_create_mints_confirmation_code_and_provisional
    """
    prop = fixtures.new_property(api)
    fixtures.new_ami_limit(api, prop["id"])
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant = fixtures.new_applicant(api, full_name="Tia T",
                                       email="t@x.com")

    payload = fixtures.create_application_payload(applicant["id"],
                                                  campaign["id"])
    application = validate_success(
        api.create_application(payload,
                               make_applicant_headers(applicant["id"])),
        expected_status=201)
    assert_application(application)
    assert "confirmation_code" not in payload
    assert application["confirmation_code"], "server mints a non-empty code"
    assert application["provisional_determination"] == "PROVISIONALLY_ELIGIBLE"
    assert application["status"] == "SUBMITTED"
    campaign_after = fixtures.get_campaign(api, campaign["id"])
    assert campaign_after["applications_received_count"] == 1


def test_submit_after_close_at_while_still_open_returns_window_closed(api):
    """PRD §3.3: "the logical clock must not yet have reached
    `application_close_at`, else `ERR_APPLICATION_WINDOW_CLOSED`"."

    Design: Corner/validations/submit_after_close_at_while_still_open_returns_window_closed
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    fixtures.set_clock("2026-07-01T00:00:00Z", api)
    applicant = fixtures.new_applicant(api, full_name="Sue S",
                                       email="s9@x.com")
    resp = api.create_application(
        fixtures.create_application_payload(applicant["id"], campaign["id"]),
        make_applicant_headers(applicant["id"]))
    # Campaign status is still OPEN (nobody closed it); the half-open window
    # [2026-06-01, 2026-06-30) has ended — the pure temporal leg.
    validate_error(resp, ApiErrorId.ERR_APPLICATION_WINDOW_CLOSED)


def test_duplicate_application_rejected_then_reapply_after_withdraw(api):
    """PRD §3.3: "the same applicant must not already hold a non-terminal
    application — one in `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_INFO`, or
    `VERIFIED` — in this campaign, else `ERR_DUPLICATE_APPLICATION`. A
    rejected or withdrawn household may therefore apply again, but an active
    one may not."

    Design: Corner/validations/duplicate_application_rejected_then_reapply_after_withdraw
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant = fixtures.new_applicant(api, full_name="Tom T",
                                       email="t9@x.com")
    first = fixtures.submit_application(api, campaign["id"], applicant["id"])

    resp = api.create_application(
        fixtures.create_application_payload(applicant["id"], campaign["id"],
                                            household_size=3,
                                            self_reported_annual_income_cents=3200000),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)

    validate_success(api.withdraw_application(
        first["id"], make_applicant_headers(applicant["id"])))
    second = validate_success(
        api.create_application(
            fixtures.create_application_payload(
                applicant["id"], campaign["id"], household_size=3,
                self_reported_annual_income_cents=3200000),
            make_applicant_headers(applicant["id"])),
        expected_status=201)
    assert second["status"] == "SUBMITTED"


def test_household_size_zero_and_thirteen_rejected(api):
    """PRD §3.3: "a `household_size` between 1 and 12 inclusive (outside that
    band the submission is rejected with `ERR_HOUSEHOLD_SIZE_INVALID`)"."

    Design: Corner/validations/household_size_zero_and_thirteen_rejected
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant = fixtures.new_applicant(api, full_name="Uli U",
                                       email="u9@x.com")
    headers = make_applicant_headers(applicant["id"])

    for bad_size in (0, 13):
        resp = api.create_application(
            fixtures.create_application_payload(applicant["id"],
                                                campaign["id"],
                                                household_size=bad_size),
            headers)
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_SIZE_INVALID)

    ok = validate_success(
        api.create_application(
            fixtures.create_application_payload(applicant["id"],
                                                campaign["id"],
                                                household_size=12),
            headers),
        expected_status=201)
    assert ok["household_size"] == 12


def test_submit_rejected_while_campaign_announced(api):
    """PRD §3.3: "Three gates stand in front of acceptance, evaluated in the
    pipeline order of §2.10: the campaign's status must be `OPEN`, else
    `ERR_CAMPAIGN_NOT_OPEN`".

    Design: Difficulty/cross_entity_state_dependency/application_submit_gated_by_campaign_state
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_campaign(api, prop["id"])
    fixtures.announce_campaign(api, campaign["id"])
    fixtures.set_clock("2026-06-10T00:00:00Z", api)  # inside the window
    applicant = fixtures.new_applicant(api, full_name="Meg M",
                                       email="m@x.com")
    resp = api.create_application(
        fixtures.create_application_payload(applicant["id"], campaign["id"]),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN)


def test_submit_accepted_once_campaign_opens(api):
    """PRD §3.3: "the campaign's status must be `OPEN`, else
    `ERR_CAMPAIGN_NOT_OPEN`". PRD §3.3: "The new application lands in
    `SUBMITTED` status, and the campaign's `applications_received_count` is
    recomputed."

    Design: Difficulty/cross_entity_state_dependency/application_submit_gated_by_campaign_state
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_campaign(api, prop["id"])
    fixtures.announce_campaign(api, campaign["id"])
    fixtures.set_clock("2026-06-10T00:00:00Z", api)
    applicant = fixtures.new_applicant(api, full_name="Meg M",
                                       email="m@x.com")
    fixtures.open_campaign(api, campaign["id"])
    application = validate_success(
        api.create_application(
            fixtures.create_application_payload(applicant["id"],
                                                campaign["id"]),
            make_applicant_headers(applicant["id"])),
        expected_status=201)
    assert application["status"] == "SUBMITTED"


def _setup_closed_campaign_past_close(api):
    """Campaign ran its June window and was CLOSED at 2026-06-30; the clock is
    then advanced past close_at to 2026-07-05."""
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    fixtures.close_campaign_at(api, campaign["id"])
    fixtures.set_clock("2026-07-05T00:00:00Z", api)
    return prop, campaign


def test_submit_closed_campaign_state_beats_temporal(api):
    """PRD §2.10: "When several checks could reject the same request, they are
    evaluated in a fixed priority order so the surfaced error is
    deterministic". PRD §3.3: "Three gates stand in front of acceptance,
    evaluated in the pipeline order of §2.10: the campaign's status must be
    `OPEN`, else `ERR_CAMPAIGN_NOT_OPEN`; the logical clock must not yet have
    reached `application_close_at`, else `ERR_APPLICATION_WINDOW_CLOSED`".

    Design: Difficulty/priority_pair_validation_conflict/submit_closed_campaign_state_beats_temporal
    """
    _, campaign = _setup_closed_campaign_past_close(api)
    applicant = fixtures.new_applicant(api, full_name="Ivy I",
                                       email="i@x.com")
    resp = api.create_application(
        fixtures.create_application_payload(applicant["id"], campaign["id"]),
        make_applicant_headers(applicant["id"]))
    # Both the state violation (CLOSED) and the temporal violation (clock past
    # close_at) hold; the state gate is evaluated first.
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN)


def test_submit_closed_campaign_creates_no_application(api):
    """PRD §2.8: "A campaign exposes `applications_received_count` (its
    applications in `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_INFO`, or `VERIFIED`
    status)". PRD §3.3: "the campaign's status must be `OPEN`, else
    `ERR_CAMPAIGN_NOT_OPEN`".

    Design: Difficulty/priority_pair_validation_conflict/submit_closed_campaign_state_beats_temporal
    """
    _, campaign = _setup_closed_campaign_past_close(api)
    applicant = fixtures.new_applicant(api, full_name="Ivy I",
                                       email="i@x.com")
    resp = api.create_application(
        fixtures.create_application_payload(applicant["id"], campaign["id"]),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN)
    _, meta = validate_paginated(api.list_applications(
        CLERK, params={"applicant_id": applicant["id"]}))
    assert meta["total_count"] == 0, "a rejected submit writes no row"
    assert fixtures.get_campaign(
        api, campaign["id"])["applications_received_count"] == 0
