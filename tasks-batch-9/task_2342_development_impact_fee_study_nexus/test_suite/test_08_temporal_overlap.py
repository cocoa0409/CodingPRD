"""Two occupancy rules with deliberately opposite endpoint conventions: the
half-open notice window and the closed horizon-year interval."""

from test_helpers import api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, validate_error
from test_helpers.fixtures import ADMIN, ANALYST, CLERK

JUST_INSIDE_WINDOW = "2026-02-13T23:59:59Z"
STUDY_B_WINDOW_END = "2026-03-16T00:00:00Z"


def _noticed_study_and_a_waiting_certified_study(api):
    chain = fixtures.program_with_categories(api, with_roads=False)
    study_a = fixtures.create_study(api, chain.program_id)
    study_b = fixtures.create_study(
        api, chain.program_id, title="2026 Impact Fee Study - Alternate"
    )
    for study in (study_a, study_b):
        component = fixtures.create_parks_component(api, study["id"], chain.parks_category_id)
        fixtures.allocate(api, component["id"])
        fixtures.add_schedule_line(
            api, component["id"], K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR
        )
        fixtures.certify(api, study["id"])
    chain.study_id = study_a["id"]
    fixtures.set_clock(api, K.CLOCK_NOTICE_PUBLISHED)
    noticed = fixtures.publish_notice(api, study_a["id"], notice_days=30)
    check.assert_timestamp_equals(
        noticed["protest_window_ends_at"], K.CLOCK_PROTEST_WINDOW_END, "protest_window_ends_at"
    )
    return chain, study_a, study_b


def test_a_notice_one_second_inside_the_open_window_is_refused(api):
    """Two guards apply, and their relative order matters. Publishing exactly at
    another study's `protest_window_ends_at` is therefore accepted — for
    timestamps, adjacency is not overlap — while publishing anywhere strictly
    inside returns `ERR_NOTICE_WINDOW_OVERLAP`.

    Design: Difficulty/resource_temporal_overlap/notice_windows_are_half_open_so_back_to_back_notices_are_allowed
    """
    _, study_a, study_b = _noticed_study_and_a_waiting_certified_study(api)

    fixtures.set_clock(api, JUST_INSIDE_WINDOW)
    response = api.publish_notice(
        study_b["id"], factories.notice_payload(notice_days=30), CLERK
    )

    validate_error(response, err.ERR_NOTICE_WINDOW_OVERLAP, 409)
    blocked = get_success_data(api.get_fee_study(study_b["id"], ADMIN))
    assert blocked["status"] == K.STUDY_NEXUS_CERTIFIED
    check.assert_fields_null(
        blocked, "notice_published_at", "protest_window_ends_at", "notice_method", "notice_days"
    )
    occupant = get_success_data(api.get_fee_study(study_a["id"], ADMIN))
    assert occupant["status"] == K.STUDY_NOTICE_PUBLISHED


def test_a_notice_exactly_at_the_window_end_is_accepted(api):
    """Publishing exactly at another study's `protest_window_ends_at` is therefore
    accepted — for timestamps, adjacency is not overlap — while publishing anywhere
    strictly inside returns `ERR_NOTICE_WINDOW_OVERLAP`. Publication stores the
    notice method and days, stamps `notice_published_at` from the logical clock,
    sets `protest_window_ends_at` to that instant plus `notice_days` days, and
    increments the study's `version`.

    Design: Difficulty/resource_temporal_overlap/notice_windows_are_half_open_so_back_to_back_notices_are_allowed
    """
    _, study_a, study_b = _noticed_study_and_a_waiting_certified_study(api)
    fixtures.set_clock(api, JUST_INSIDE_WINDOW)
    api.publish_notice(study_b["id"], factories.notice_payload(notice_days=30), CLERK)

    fixtures.set_clock(api, K.CLOCK_PROTEST_WINDOW_END)
    published = fixtures.publish_notice(api, study_b["id"], notice_days=30)

    assert published["status"] == K.STUDY_NOTICE_PUBLISHED
    check.assert_timestamp_equals(
        published["notice_published_at"], K.CLOCK_PROTEST_WINDOW_END, "notice_published_at"
    )
    check.assert_timestamp_equals(
        published["protest_window_ends_at"], STUDY_B_WINDOW_END, "protest_window_ends_at"
    )
    occupant = get_success_data(api.get_fee_study(study_a["id"], ADMIN))
    assert occupant["status"] == K.STUDY_NOTICE_PUBLISHED
    check.assert_timestamp_equals(
        occupant["protest_window_ends_at"], K.CLOCK_PROTEST_WINDOW_END, "protest_window_ends_at"
    )


def _effective_study_and_a_second_draft(api):
    chain = fixtures.effective_program(api, with_roads=False)
    draft = fixtures.create_study(api, chain.program_id, title="2031 Impact Fee Study")
    return chain, draft


def test_a_horizon_sharing_one_year_with_the_effective_study_is_refused(api):
    """One structural constraint is checked on both component creation and
    component revision. Contrast this with the notice-window rule of §3.4: that
    one is a half-open timestamp interval where touching endpoints do not
    conflict, and this one is a closed year interval where they do.

    Design: Difficulty/resource_temporal_overlap/component_horizons_are_closed_so_adjacent_years_collide
    """
    chain, draft = _effective_study_and_a_second_draft(api)

    response = api.create_nexus_component(
        factories.parks_component_payload(
            draft["id"],
            chain.parks_category_id,
            horizon_start_year=2030,
            horizon_end_year=2035,
        ),
        ANALYST,
    )

    validate_error(response, err.ERR_HORIZON_OVERLAP, 409)
    components = get_success_data(
        api.list_nexus_components(ADMIN, {"fee_study_id": draft["id"]})
    )
    assert components == [], "a rejected horizon must not create a component"
    effective_component = get_success_data(
        api.get_nexus_component(chain.parks_component_id, ADMIN)
    )
    assert effective_component["horizon_end_year"] == 2030
    assert effective_component["allocation_status"] == K.ALLOCATION_VALID


def test_a_horizon_starting_the_following_year_is_accepted(api):
    """Components belonging to studies in `DRAFT`, `NEXUS_CERTIFIED`,
    `NOTICE_PUBLISHED`, `PROTEST_CLEARED`, `ADOPTED` or `SUPERSEDED` are ignored by
    this check, so competing drafts covering the same years may legitimately
    coexist. Until the component is allocated, its `allocation_status` is
    `PENDING`, `allocated_at` is null, and all four computed cost figures are null.

    Design: Difficulty/resource_temporal_overlap/component_horizons_are_closed_so_adjacent_years_collide
    """
    chain, draft = _effective_study_and_a_second_draft(api)
    api.create_nexus_component(
        factories.parks_component_payload(
            draft["id"],
            chain.parks_category_id,
            horizon_start_year=2030,
            horizon_end_year=2035,
        ),
        ANALYST,
    )

    created = get_success_data(
        api.create_nexus_component(
            factories.parks_component_payload(
                draft["id"],
                chain.parks_category_id,
                horizon_start_year=2031,
                horizon_end_year=2035,
            ),
            ANALYST,
        ),
        201,
    )

    assert created["horizon_start_year"] == 2031
    assert created["horizon_end_year"] == 2035
    assert created["allocation_status"] == K.ALLOCATION_PENDING
    check.assert_four_decimal_equals(
        created["growth_demand_units"], K.PARKS_GROWTH_DEMAND_UNITS, "growth_demand_units"
    )
    check.assert_fields_null(
        created,
        "allocated_at",
        "plan_based_cost_per_unit_cents",
        "standard_based_cost_per_unit_cents",
        "adopted_cost_per_unit_cents",
        "nexus_ratio",
    )
    effective_component = get_success_data(
        api.get_nexus_component(chain.parks_component_id, ADMIN)
    )
    assert effective_component["horizon_end_year"] == 2030
