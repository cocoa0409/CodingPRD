"""Temporal geometry: the half-open exclusivity window plus its tail-off gap, the
closed-interval capacity window, and the closed introduction slot."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_introduction,
    api_client,
    create_engagement_payload,
    create_introduction_payload,
    new_engagement,
    new_practice_group,
    read_integration_plan,
    read_practice_group,
    setup_active_plan,
    setup_config,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]


def test_overlap_a_touching_endpoint_and_a_short_tail_are_all_exclusivity_conflicts():
    """On the **practice group** side, the requested half-open window must not overlap the
    half-open window of any existing engagement on the same `practice_group_id` whose
    `status` is `ACTIVE`, and in addition the requested `exclusivity_start_date` must fall
    at or after that existing engagement's `exclusivity_end_date` advanced by its own
    `tail_off_days` days.

    Design: Difficulty/resource_temporal_overlap/practice_group_engagement_half_open_plus_tail_off_gap
    """
    ctx = setup_config(sf_overrides={"max_concurrent_engagements": 3})

    for start, end, label in (
        ("2026-10-01T00:00:00.000Z", "2027-01-01T00:00:00.000Z", "mid-window overlap"),
        ("2026-12-01T00:00:00.000Z", "2027-03-01T00:00:00.000Z", "touching endpoint"),
        ("2027-02-28T00:00:00.000Z", "2027-05-28T00:00:00.000Z", "one day short of tail"),
    ):
        response = api_client.create_search_firm_engagement(
            create_engagement_payload(
                ctx["search_firm"]["id"],
                ctx["practice_group"]["id"],
                exclusivity_start_date=start,
                exclusivity_end_date=end,
            ),
            COORDINATOR,
        )
        error = validate_error(
            response, ApiErrorId.ERR_ENGAGEMENT_EXCLUSIVITY_CONFLICT.value
        )
        assert (
            error["error_id"] != ApiErrorId.ERR_SEARCH_FIRM_CAPACITY_EXCEEDED.value
        ), label


def test_a_start_exactly_at_the_end_of_the_tail_off_gap_is_accepted():
    """The `tail_off_days` value does double duty — it is the fee-protection tail that
    survives the end of exclusivity, and it is also the mandatory quiet gap that must
    elapse before the same practice group may be given to another recruiter.
    A new engagement starts with `status` `ACTIVE`, `fee_status` `NOT_DUE`, `fee_basis`
    `NONE`, and `fee_amount_usd` `0.00`, and it increments the named firm's
    `engagement_count` by 1 (which, being a mutation of the firm row, also advances that
    firm's `version` by 1).

    Design: Difficulty/resource_temporal_overlap/practice_group_engagement_half_open_plus_tail_off_gap
    """
    ctx = setup_config(sf_overrides={"max_concurrent_engagements": 3})

    second = validate_success(
        api_client.create_search_firm_engagement(
            create_engagement_payload(
                ctx["search_firm"]["id"],
                ctx["practice_group"]["id"],
                exclusivity_start_date="2027-03-01T00:00:00.000Z",
                exclusivity_end_date="2027-06-01T00:00:00.000Z",
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert second["status"] == "ACTIVE"
    assert second["tail_off_days"] == 90
    assert second["fee_status"] == "NOT_DUE"

    first = validate_success(
        api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
    )
    assert first["status"] == "ACTIVE"

    firm = validate_success(
        api_client.get_search_firm(ctx["search_firm"]["id"], COORDINATOR)
    )
    assert firm["engagement_count"] == 2


def test_windows_that_merely_touch_still_count_against_the_firms_capacity():
    """Count the engagements naming the same `search_firm_id` whose `status` is `ACTIVE`
    and whose closed window, from `exclusivity_start_date` through `exclusivity_end_date`
    inclusive of both endpoints, intersects the requested closed window. That count must
    be strictly less than the firm's `max_concurrent_engagements`; if it has already
    reached that number, the create is refused with
    `ERR_SEARCH_FIRM_CAPACITY_EXCEEDED`.

    Design: Difficulty/resource_temporal_overlap/search_firm_closed_interval_capacity_touching_endpoints
    """
    ctx = _setup_two_group_firm()

    third = api_client.create_search_firm_engagement(
        create_engagement_payload(
            ctx["search_firm"]["id"],
            ctx["group_c"]["id"],
            exclusivity_start_date="2026-12-01T00:00:00.000Z",
            exclusivity_end_date="2027-01-01T00:00:00.000Z",
            tail_off_days=0,
        ),
        COORDINATOR,
    )
    error = validate_error(third, ApiErrorId.ERR_SEARCH_FIRM_CAPACITY_EXCEEDED.value)
    assert error["error_id"] != ApiErrorId.ERR_ENGAGEMENT_EXCLUSIVITY_CONFLICT.value

    firm = validate_success(
        api_client.get_search_firm(ctx["search_firm"]["id"], COORDINATOR)
    )
    assert firm["engagement_count"] == 2


def test_a_window_disjoint_from_both_live_engagements_is_within_capacity():
    """Two independent geometry rules guard the create, and they use **different interval
    conventions on different resources** — a distinction that has caught more than one
    implementer.
    Because the intervals are closed here, two windows that merely touch — one ending at
    the exact instant another begins — *do* intersect and *do* both count.

    Design: Difficulty/resource_temporal_overlap/search_firm_closed_interval_capacity_touching_endpoints
    """
    ctx = _setup_two_group_firm()

    fourth = validate_success(
        api_client.create_search_firm_engagement(
            create_engagement_payload(
                ctx["search_firm"]["id"],
                ctx["group_c"]["id"],
                exclusivity_start_date="2027-05-01T00:00:00.000Z",
                exclusivity_end_date="2027-08-01T00:00:00.000Z",
                tail_off_days=0,
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert fourth["status"] == "ACTIVE"

    assert (
        validate_success(
            api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
        )["status"]
        == "ACTIVE"
    )
    assert (
        validate_success(
            api_client.get_search_firm_engagement(
                ctx["engagement_b"]["id"], COORDINATOR
            )
        )["status"]
        == "ACTIVE"
    )

    firm = validate_success(
        api_client.get_search_firm(ctx["search_firm"]["id"], COORDINATOR)
    )
    assert firm["engagement_count"] == 3


def test_two_introduction_slots_may_not_even_touch_at_their_endpoints():
    """And it must not intersect any other slot on the same plan whose `status` is
    `PROPOSED` or `COMPLETED`, again under closed semantics, so two slots that merely
    touch at an endpoint **do** conflict; the refusal is
    `ERR_INTRODUCTION_SLOT_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/introduction_closed_slot_pairwise_and_containment
    """
    ctx = setup_active_plan("SLIM")
    first = add_introduction(
        ctx,
        target_client_name="Halloran Group",
        slot_start_at="2026-10-05T09:00:00.000Z",
        slot_end_at="2026-10-05T10:00:00.000Z",
    )
    assert first["status"] == "PROPOSED"

    touching = api_client.create_introduction(
        ctx["plan"]["id"],
        create_introduction_payload(
            target_client_name="Ingram Partners",
            slot_start_at="2026-10-05T10:00:00.000Z",
            slot_end_at="2026-10-05T11:00:00.000Z",
        ),
        ctx["leader_headers"],
    )
    validate_error(touching, ApiErrorId.ERR_INTRODUCTION_SLOT_CONFLICT.value)

    second = add_introduction(
        ctx,
        target_client_name="Ingram Partners",
        slot_start_at="2026-10-05T10:00:00.001Z",
        slot_end_at="2026-10-05T11:00:00.000Z",
    )
    assert second["status"] == "PROPOSED"

    plan = read_integration_plan(ctx["plan"]["id"])
    assert plan["introduction_count"] == 2
    assert plan["completed_introduction_count"] == 0
    assert plan["status"] == "ACTIVE"
    assert read_practice_group(ctx["practice_group"]["id"])["active_onboarding_count"] == 1


def test_a_slot_running_past_the_onboarding_window_is_outside_the_window():
    """The slot must be closed-contained in the plan's onboarding window —
    `slot_start_at` at or after `onboarding_start_date` and `slot_end_at` at or before
    `onboarding_end_date` — or the request is refused with
    `ERR_INTRODUCTION_OUTSIDE_WINDOW`.

    Design: Difficulty/resource_temporal_overlap/introduction_closed_slot_pairwise_and_containment
    """
    ctx = setup_active_plan("SLIM")
    add_introduction(
        ctx,
        target_client_name="Halloran Group",
        slot_start_at="2026-10-05T09:00:00.000Z",
        slot_end_at="2026-10-05T10:00:00.000Z",
    )

    response = api_client.create_introduction(
        ctx["plan"]["id"],
        create_introduction_payload(
            target_client_name="Jessup Foods",
            slot_start_at="2027-06-29T09:00:00.000Z",
            slot_end_at="2027-07-01T10:00:00.000Z",
        ),
        ctx["leader_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_INTRODUCTION_OUTSIDE_WINDOW.value)
    assert error["error_id"] != ApiErrorId.ERR_INTRODUCTION_SLOT_CONFLICT.value

    plan = read_integration_plan(ctx["plan"]["id"])
    assert plan["introduction_count"] == 1
    assert plan["status"] == "ACTIVE"


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _setup_two_group_firm():
    """One firm with capacity 2 already holding two ACTIVE engagements on two different
    practice groups, whose closed windows touch at 2026-12-01, plus an untouched third
    practice group."""
    ctx = setup_config(
        sf_overrides={"max_concurrent_engagements": 2},
        eng_overrides={"tail_off_days": 0},
    )
    ctx["group_b"] = new_practice_group(name="Litigation")
    ctx["group_c"] = new_practice_group(name="Tax")
    ctx["engagement_b"] = new_engagement(
        ctx["search_firm"]["id"],
        ctx["group_b"]["id"],
        exclusivity_start_date="2026-12-01T00:00:00.000Z",
        exclusivity_end_date="2027-04-01T00:00:00.000Z",
        tail_off_days=0,
    )
    return ctx
