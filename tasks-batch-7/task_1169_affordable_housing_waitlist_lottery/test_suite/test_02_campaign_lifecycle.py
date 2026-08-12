"""Campaign authoring, announcement, the application window, and reopening."""
from test_helpers import (
    ApiErrorId, assert_campaign, fixtures, get_success_data, validate_error,
    validate_success,
)

DEVELOPER = fixtures.DEVELOPER
MARKETING = fixtures.MARKETING


def test_announce_with_single_channel_returns_marketing_insufficient(api):
    """PRD §3.2: "the outreach plan must name at least two marketing channels,
    and an announcement carrying fewer is rejected with
    `ERR_MARKETING_PLAN_INSUFFICIENT`."

    Design: Corner/state_machines/announce_with_single_channel_returns_marketing_insufficient
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_campaign(api, prop["id"],
                                     marketing_channels=["LOCAL_NEWSPAPER"],
                                     marketing_plan_summary="thin plan")
    resp = api.transition_campaign(campaign["id"], {"action": "ANNOUNCE"},
                                   MARKETING)
    validate_error(resp, ApiErrorId.ERR_MARKETING_PLAN_INSUFFICIENT)
    fetched = fixtures.get_campaign(api, campaign["id"])
    assert fetched["status"] == "DRAFT"


def test_open_before_window_returns_window_not_open(api):
    """PRD §3.2: "a `HousingDeveloper` opens the campaign, moving it from
    `ANNOUNCED` to `OPEN`, but only once the logical clock has reached
    `application_open_at`; an early opening is rejected with
    `ERR_APPLICATION_WINDOW_NOT_OPEN`."

    Design: Corner/state_machines/open_before_window_returns_window_not_open
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_campaign(api, prop["id"])
    fixtures.announce_campaign(api, campaign["id"])
    # Logical clock still at the startup default 2026-05-01T00:00:00Z,
    # before application_open_at 2026-06-01.
    resp = api.transition_campaign(campaign["id"], {"action": "OPEN"},
                                   DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_WINDOW_NOT_OPEN)
    assert fixtures.get_campaign(api, campaign["id"])["status"] == "ANNOUNCED"


def test_close_before_close_at_returns_invalid_state(api):
    """PRD §3.2: "Closing is the mirror image: from `OPEN` to `CLOSED`,
    allowed only once the logical clock has reached `application_close_at`,
    with an early close rejected as `ERR_INVALID_STATE`."

    Design: Corner/state_machines/close_before_close_at_returns_invalid_state
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"],
                                          open_clock="2026-06-15T00:00:00Z")
    resp = api.transition_campaign(campaign["id"], {"action": "CLOSE"},
                                   DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fixtures.get_campaign(api, campaign["id"])["status"] == "OPEN"


def test_default_clock_open_at_startup_default_boundary(api):
    """PRD §2.5: "At server startup, before any clock operation has been
    issued, the logical clock reads exactly `2026-05-01T00:00:00Z`." PRD §3.2:
    "a `HousingDeveloper` opens the campaign, moving it from `ANNOUNCED` to
    `OPEN`, but only once the logical clock has reached
    `application_open_at`".

    Design: Corner/cross_cutting_layers/default_clock_open_at_startup_default_boundary
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_campaign(
        api, prop["id"], name="May 2026",
        application_open_at="2026-05-01T00:00:00Z",
        application_close_at="2026-05-31T00:00:00Z")
    fixtures.announce_campaign(api, campaign["id"])
    # No clock-set call is ever made: the startup default equals
    # application_open_at, and "reached" includes equality.
    opened = fixtures.open_campaign(api, campaign["id"])
    assert opened["status"] == "OPEN"


def test_transition_response_reflects_new_state_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §2.4: "a system-managed integer that increments by exactly 1
    on every mutation of the resource."

    Design: Corner/consistency_model/transition_response_reflects_new_state_immediately
    """
    prop = fixtures.new_property(api)
    created = validate_success(
        api.create_campaign(fixtures.create_campaign_payload(prop["id"]),
                            DEVELOPER),
        expected_status=201)
    announced = validate_success(
        api.transition_campaign(created["id"], {"action": "ANNOUNCE"},
                                MARKETING))
    assert_campaign(announced)
    assert announced["status"] == "ANNOUNCED"
    assert announced["version"] == created["version"] + 1, (
        "the transition response itself carries the incremented version; "
        "no follow-up read is needed"
    )


def test_campaign_windows_adjacent_at_boundary_accepted(api):
    """PRD §3.2: "two half-open windows overlap when the first opens before
    the other closes and the other opens before the first closes — so a
    window opening exactly as another closes does not overlap — and any
    overlap is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/campaign_windows_half_open_adjacency_allowed
    """
    prop = fixtures.new_property(api)
    fixtures.new_campaign(api, prop["id"], name="June 2026")
    adjacent = validate_success(
        api.create_campaign(
            fixtures.create_campaign_payload(
                prop["id"], name="July 2026",
                application_open_at="2026-06-30T00:00:00Z",
                application_close_at="2026-07-30T00:00:00Z"),
            DEVELOPER),
        expected_status=201)
    assert adjacent["status"] == "DRAFT", (
        "a window opening exactly as the sibling closes is disjoint under "
        "half-open semantics"
    )


def test_campaign_windows_one_day_overlap_rejected(api):
    """PRD §3.2: "two half-open windows overlap when the first opens before
    the other closes and the other opens before the first closes — so a
    window opening exactly as another closes does not overlap — and any
    overlap is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/campaign_windows_half_open_adjacency_allowed
    """
    prop = fixtures.new_property(api)
    fixtures.new_campaign(api, prop["id"], name="June 2026")
    fixtures.new_campaign(
        api, prop["id"], name="July 2026",
        application_open_at="2026-06-30T00:00:00Z",
        application_close_at="2026-07-30T00:00:00Z")
    resp = api.create_campaign(
        fixtures.create_campaign_payload(
            prop["id"], name="Overlap 2026",
            application_open_at="2026-06-29T00:00:00Z",
            application_close_at="2026-07-15T00:00:00Z"),
        DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_OVERLAP)
