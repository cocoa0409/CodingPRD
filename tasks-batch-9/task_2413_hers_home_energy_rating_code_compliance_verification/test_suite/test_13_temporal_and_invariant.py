"""Depth tests for the `resource_temporal_overlap` and `compensating_invariant`
rules.

Every test below translates exactly one non-stub instance of
`SCAFFOLD_DIFFICULTY_DESIGN.yaml`; the trailing `Design:` line of each docstring
names the instance it came from.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_INSPECTOR_WINDOW_CONFLICT,
    ERR_SAMPLE_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_builder_ledger,
    assert_common_fields,
    assert_count,
    assert_coverage_ledger,
    assert_home_sampling_state,
    assert_package_state,
    assert_rating_dimensions,
    assert_sample_set_counters,
)
from test_helpers.fixtures import (
    add_sample_member,
    build_issued_package_world,
    build_rating_world,
    build_sample_world,
    create_home,
    create_rating,
    create_sample_set,
    get_builder,
    get_home,
    get_inspection,
    get_rating,
    get_sample_set,
    get_subdivision,
    list_packages,
    schedule_inspection,
    void_rating,
    withdraw_sample_member,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_certified_rater_headers,
    make_field_inspector_headers,
)


def _inspector_with_one_booking(api: ApiClient):
    """One inspector already holding a SCHEDULED 09:00-11:00 checkpoint, plus a
    second rating on which to attempt a neighbouring booking."""
    world = build_rating_world(
        api,
        builder_name="Cobblestone Homes",
        subdivision_name="Harrow Green",
        lot_number="L-1",
        permit_date="2026-08-04",
    )
    held = schedule_inspection(
        api,
        world.rating_id,
        world.inspector_id,
        checkpoint="FINAL",
        scheduled_start_utc="2026-08-18T09:00:00Z",
        scheduled_end_utc="2026-08-18T11:00:00Z",
        air_handler_installed=True,
    )
    other_home = create_home(
        api,
        world.subdivision_id,
        world.plan_model_id,
        world.builder_id,
        lot_number="L-2",
        permit_date="2026-08-05",
    )
    other_rating = create_rating(api, other_home["id"], world.rater_id)
    return world, held, other_rating


def _subdivision_with_one_window(api: ApiClient):
    """A sampling-enabled subdivision already holding a FORMING window that runs
    from 2026-08-01 to 2026-08-15 inclusive."""
    world = build_rating_world(
        api,
        builder_name="Wexford Homes",
        subdivision_name="Bellrose",
        sampling_enabled=True,
        with_home=False,
        with_rating=False,
    )
    held = create_sample_set(
        api,
        world.subdivision_id,
        world.rater_id,
        window_start_date="2026-08-01",
        window_end_date="2026-08-15",
    )
    return world, held


def _added_then_withdrawn(api: ApiClient):
    """Three unsampled lots, one added to the set and then withdrawn again."""
    world = build_sample_world(
        api,
        member_count=3,
        add_members=False,
        open_ratings=False,
        builder_name="Aldergate Homes",
        subdivision_name="Pennyfield",
        lot_numbers=["L-1", "L-2", "L-3"],
        permit_dates=["2026-08-04", "2026-08-05", "2026-08-06"],
    )
    add_sample_member(api, world.sample_set_id, world.homes[0]["id"], world.rater_id)
    withdraw_sample_member(
        api, world.sample_set_id, world.homes[0]["id"], world.rater_id
    )
    # PRD never says which resource the withdrawal endpoint returns, so the set is
    # re-read through its own GET route before the §2.9/§2.10 assertions run.
    return world, get_sample_set(api, world.sample_set_id)


# ==================================================== resource_temporal_overlap
def test_buffered_inspector_windows_that_genuinely_overlap_are_refused(
    api: ApiClient,
) -> None:
    """A 11:30-12:30 request buffers out to 10:45-13:15, which intersects the held
    checkpoint's 08:15-11:45 buffered interval.

    PRD §3.3: "Each scheduled checkpoint's half-open window is expanded by a travel buffer of three quarters of an hour — 45 minutes — on *both* ends, and a new request is refused with `ERR_INSPECTOR_WINDOW_CONFLICT` if the resulting buffered interval overlaps the buffered interval of any other checkpoint that inspector already holds in `SCHEDULED` status."

    Design: Difficulty/resource_temporal_overlap/inspection_window_overlap_with_travel_buffer_on_inspector
    """
    world, held, other_rating = _inspector_with_one_booking(api)
    response = api.create_inspection(
        factories.inspection_payload(
            other_rating["id"],
            world.inspector_id,
            checkpoint="FINAL",
            scheduled_start_utc="2026-08-18T11:30:00Z",
            scheduled_end_utc="2026-08-18T12:30:00Z",
            air_handler_installed=True,
        ),
        make_field_inspector_headers(world.inspector_id),
    )
    validate_error(response, ERR_INSPECTOR_WINDOW_CONFLICT, 409)
    assert get_inspection(api, held["id"])["status"] == "SCHEDULED"


def test_buffered_inspector_windows_that_only_touch_both_stand(api: ApiClient) -> None:
    """A 12:30-13:30 request buffers out to 11:45-14:15, which merely touches the
    held checkpoint's buffered end instant, so both bookings survive.

    PRD §3.3: "Because the intervals are half-open, two buffered windows that merely touch at an instant do not overlap and both bookings stand."

    Design: Difficulty/resource_temporal_overlap/inspection_window_overlap_with_travel_buffer_on_inspector
    """
    world, held, other_rating = _inspector_with_one_booking(api)
    response = api.create_inspection(
        factories.inspection_payload(
            other_rating["id"],
            world.inspector_id,
            checkpoint="FINAL",
            scheduled_start_utc="2026-08-18T12:30:00Z",
            scheduled_end_utc="2026-08-18T13:30:00Z",
            air_handler_installed=True,
        ),
        make_field_inspector_headers(world.inspector_id),
    )
    created = validate_success(response, 201)
    assert_common_fields(created)
    assert created["status"] == "SCHEDULED", created
    assert get_inspection(api, held["id"])["status"] == "SCHEDULED"
    inspections, _meta = validate_paginated(api.list_inspections(ADMIN_HEADERS))
    assert_count(inspections, 2)


def test_sample_windows_sharing_a_single_endpoint_date_are_refused(
    api: ApiClient,
) -> None:
    """A window running 2026-08-15 to 2026-08-31 shares the held window's closing
    date, and closed intervals that share a date intersect.

    PRD §3.5: "Because both intervals are closed, two windows that share even a single endpoint date do intersect."

    Design: Difficulty/resource_temporal_overlap/sample_set_window_overlap_on_subdivision_closed_interval
    """
    world, held = _subdivision_with_one_window(api)
    response = api.create_sample_set(
        factories.sample_set_payload(
            world.subdivision_id,
            window_start_date="2026-08-15",
            window_end_date="2026-08-31",
        ),
        make_certified_rater_headers(world.rater_id),
    )
    validate_error(response, ERR_SAMPLE_WINDOW_CONFLICT, 409)
    assert_sample_set_counters(get_sample_set(api, held["id"]), status="FORMING")


def test_sample_window_starting_the_day_after_is_accepted(api: ApiClient) -> None:
    """A window running 2026-08-16 to 2026-08-31 shares no date with the held
    2026-08-01 to 2026-08-15 window, so the subdivision may hold both.

    PRD §3.5: "A subdivision may run only one live sampling window at a time: if it already has a sample set in `FORMING`, `SELECTED` or `TESTED` status whose closed date interval intersects the requested one, the request is refused with `ERR_SAMPLE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/sample_set_window_overlap_on_subdivision_closed_interval
    """
    world, held = _subdivision_with_one_window(api)
    response = api.create_sample_set(
        factories.sample_set_payload(
            world.subdivision_id,
            window_start_date="2026-08-16",
            window_end_date="2026-08-31",
        ),
        make_certified_rater_headers(world.rater_id),
    )
    created = validate_success(response, 201)
    assert_sample_set_counters(created, status="FORMING", member_count=0)
    assert_sample_set_counters(get_sample_set(api, held["id"]), status="FORMING")
    sets, _meta = validate_paginated(api.list_sample_sets(ADMIN_HEADERS))
    assert_count(sets, 2)


# ===================================================== compensating_invariant
def test_issue_then_revoke_restores_the_incentive_ledger_exactly(api: ApiClient) -> None:
    """The ledger reads 100,000 cents after issuance and exactly its pre-issuance
    zero after the void cascade takes the money back.

    PRD §2.10: "The ledger is recomputed as a full aggregation rather than patched blindly, and the governing invariant is that issuing a package and then revoking it restores `certified_incentive_cents` to exactly its pre-issuance value."

    Design: Difficulty/compensating_invariant/issue_then_revoke_package_leaves_builder_incentive_ledger_unchanged
    """
    world, package = build_issued_package_world(
        api,
        package_type="TAX_CREDIT_45L",
        builder_name="Thistledown Homes",
        subdivision_name="Beacon Hollow",
        utility_program_budget_cents=500000,
        lot_number="L-12",
    )
    assert_package_state(package, status="ISSUED", certified_amount_cents=100000)
    assert_builder_ledger(
        get_builder(api, world.builder_id), certified_incentive_cents=100000
    )
    void_rating(api, world.rating_id)
    assert_builder_ledger(get_builder(api, world.builder_id), certified_incentive_cents=0)


def test_revocation_keeps_the_audit_trail_while_reversing_the_money(
    api: ApiClient,
) -> None:
    """The reversal is compensating, not erasing: the package keeps its certified
    amount, records `RATING_VOID`, and the counters that are not part of the
    invariant do move.

    PRD §3.9: "The revocation paths of §3.6 and §3.8 are the compensating counterparts: after an issue-then-revoke pair the builder's `certified_incentive_cents` reads exactly what it read before the issue, and the package's `revocation_reason` records which of the two cascades — `QA_MAJOR_FAILURE` or `RATING_VOID` — took the money back."

    Design: Difficulty/compensating_invariant/issue_then_revoke_package_leaves_builder_incentive_ledger_unchanged
    """
    world, _package = build_issued_package_world(
        api,
        package_type="TAX_CREDIT_45L",
        builder_name="Thistledown Homes",
        subdivision_name="Beacon Hollow",
        utility_program_budget_cents=500000,
        lot_number="L-12",
    )
    void_rating(api, world.rating_id)
    (revoked,) = list_packages(api, world.rating_id)
    assert_package_state(
        revoked,
        status="REVOKED",
        revocation_reason="RATING_VOID",
        certified_amount_cents=100000,
    )
    assert_builder_ledger(
        get_builder(api, world.builder_id),
        revoked_package_count=1,
        status="SAMPLING_SUSPENDED",
        sampling_eligible=False,
    )
    rating = get_rating(api, world.rating_id)
    assert rating["file_locked"] is True, rating
    assert_rating_dimensions(rating, stage="VOID", compliance_status="FAILING")


def test_add_then_withdraw_restores_the_coverage_ledger_exactly(api: ApiClient) -> None:
    """Adding a lot and withdrawing it again returns `homes_count`,
    `sampled_home_count` and `unsampled_home_count` to 3 / 0 / 3.

    PRD §2.10: "The invariant is that after every single operation the sampled and unsampled counts sum to `homes_count`, and that adding a home to a set and then withdrawing it restores all three counters to their pre-addition values."

    Design: Difficulty/compensating_invariant/add_then_withdraw_home_leaves_subdivision_coverage_ledger_unchanged
    """
    world, withdrawn = _added_then_withdrawn(api)
    assert_coverage_ledger(
        get_subdivision(api, world.subdivision_id),
        homes_count=3,
        sampled_home_count=0,
        unsampled_home_count=3,
    )
    assert_sample_set_counters(withdrawn, status="FORMING", member_count=0)


def test_withdrawal_releases_the_home_but_still_advances_the_set_version(
    api: ApiClient,
) -> None:
    """The compensation is not a rollback: the home returns to `UNASSIGNED` with a
    null `sample_set_id` and no individual-testing flag, while the set's `version`
    has been raised once by the addition and once by the withdrawal.

    PRD §2.9: "A successful withdrawal likewise increases the set's `version` by 1."

    Design: Difficulty/compensating_invariant/add_then_withdraw_home_leaves_subdivision_coverage_ledger_unchanged
    """
    world, withdrawn = _added_then_withdrawn(api)
    assert withdrawn["version"] == 3, withdrawn
    assert_home_sampling_state(
        get_home(api, world.homes[0]["id"]),
        sampling_role="UNASSIGNED",
        sample_set_id=None,
        individual_testing_required=False,
    )
