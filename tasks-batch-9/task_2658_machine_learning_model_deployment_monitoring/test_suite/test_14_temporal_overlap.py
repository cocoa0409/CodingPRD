"""Two interval geometries that are deliberately not the same shape."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_MONITORING_WINDOW_OVERLAP,
    ERR_SERVE_WINDOW_CONFLICT,
)
from test_helpers.factories import (
    build_deployment_payload,
    build_monitoring_window_payload,
)
from test_helpers.fixtures import (
    Stack,
    build_stack,
    close_window,
    read_endpoint_version,
    record_window,
    set_clock,
)
from test_helpers.test_users import RELIABILITY_1

# ─── Half-open serve windows with an asymmetric trailing buffer ───

_INCUMBENT_FROM = "2026-08-05T00:00:00Z"
_INCUMBENT_UNTIL = "2026-08-06T00:00:00Z"


def _incumbent(api: ApiClient) -> Stack:
    """One PENDING realtime deployment holding a whole day, cooldown 30 minutes."""
    stack = build_stack(
        api,
        serve_from=_INCUMBENT_FROM,
        serve_until=_INCUMBENT_UNTIL,
        deploy_cooldown_minutes=30,
    )
    assert stack.deployment["rollout_state"] == "PENDING"
    assert stack.endpoint["deploy_cooldown_minutes"] == 30
    return stack


def _co_tenant(
    api: ApiClient,
    stack: Stack,
    serve_from: str,
    serve_until: str,
    pattern: str = "REALTIME",
):
    """Attempt a second deployment on the same cluster, on a current token."""
    return api.create_deployment(
        build_deployment_payload(
            stack.version_id,
            stack.endpoint_id,
            read_endpoint_version(api, stack.endpoint_id),
            pattern=pattern,
            serve_from=serve_from,
            serve_until=serve_until,
        ),
        RELIABILITY_1,
    )


def test_the_trailing_buffer_extends_the_incumbent_by_the_cooldown(api):
    """An interior interval collides, and so does the whole trailing buffer.

    PRD 3.4: the new interval "must not overlap the interval of any existing
    non-terminal deployment that shares the same serving_endpoint_id and the same
    pattern", and "a new serve_from must be at or after the existing deployment's
    serve_until plus deploy_cooldown_minutes minutes". PRD 2.6 does not consume the
    cluster's concurrency token on a rejected create.

    Design: Difficulty/temporal_interval_overlap/serve_window_half_open_with_asymmetric_trailing_cooldown_buffer
    """
    stack = _incumbent(api)
    token_before = read_endpoint_version(api, stack.endpoint_id)

    interior = _co_tenant(
        api, stack, "2026-08-05T12:00:00Z", "2026-08-05T18:00:00Z"
    )
    validate_error(interior, ERR_SERVE_WINDOW_CONFLICT)

    at_serve_until = _co_tenant(
        api, stack, _INCUMBENT_UNTIL, "2026-08-06T12:00:00Z"
    )
    validate_error(at_serve_until, ERR_SERVE_WINDOW_CONFLICT)

    one_minute_short = _co_tenant(
        api, stack, "2026-08-06T00:29:00Z", "2026-08-06T12:00:00Z"
    )
    validate_error(one_minute_short, ERR_SERVE_WINDOW_CONFLICT)

    assert read_endpoint_version(api, stack.endpoint_id) == token_before
    rows = get_success_data(
        api.list_deployments(
            RELIABILITY_1, {"serving_endpoint_id": stack.endpoint_id}
        )
    )
    assert len(rows) == 1


def test_a_start_exactly_at_the_end_of_the_buffer_is_accepted(api):
    """The buffer's far edge is inclusive of the new deployment.

    PRD 3.4 requires the new serve_from to be "at or after the existing
    deployment's serve_until plus deploy_cooldown_minutes minutes", so the instant
    exactly 30 minutes after the incumbent's exclusive end is admissible.

    Design: Difficulty/temporal_interval_overlap/serve_window_half_open_with_asymmetric_trailing_cooldown_buffer
    """
    stack = _incumbent(api)

    accepted = get_success_data(
        _co_tenant(api, stack, "2026-08-06T00:30:00Z", "2026-08-06T12:00:00Z")
    )
    assert accepted["serve_from"] == "2026-08-06T00:30:00Z"
    assert accepted["rollout_state"] == "PENDING"


def test_the_buffer_is_trailing_only_and_scoped_to_one_pattern(api):
    """No leading buffer, and no collision across patterns at all.

    PRD 3.4: "a new serve_until exactly equal to an existing serve_from is allowed
    with no buffer at all, because the half-open geometry means the two intervals
    do not actually share an instant", and the collision test is scoped to
    deployments that share "the same pattern".

    Design: Difficulty/temporal_interval_overlap/serve_window_half_open_with_asymmetric_trailing_cooldown_buffer
    """
    stack = _incumbent(api)
    get_success_data(
        _co_tenant(api, stack, "2026-08-06T00:30:00Z", "2026-08-06T12:00:00Z")
    )

    abutting = get_success_data(
        _co_tenant(api, stack, "2026-08-04T00:00:00Z", _INCUMBENT_FROM)
    )
    assert abutting["serve_until"] == _INCUMBENT_FROM

    other_pattern = get_success_data(
        _co_tenant(
            api, stack, _INCUMBENT_FROM, _INCUMBENT_UNTIL, pattern="SHADOW"
        )
    )
    assert other_pattern["pattern"] == "SHADOW"

    rows = get_success_data(
        api.list_deployments(
            RELIABILITY_1, {"serving_endpoint_id": stack.endpoint_id}
        )
    )
    assert len(rows) == 4


# ─── Fully closed observation windows with zero buffer, per kind ───

_W1_START = "2026-08-06T00:00:00Z"
_W1_END = "2026-08-06T06:00:00Z"


def _closed_incumbent_window(api: ApiClient) -> Stack:
    """One CLOSED PERFORMANCE window occupying six hours of the previous day."""
    stack = build_stack(api, ramps=1)
    set_clock(api, "2026-08-07T00:00:00Z")
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_kind="PERFORMANCE",
        window_start=_W1_START,
        window_end=_W1_END,
    )
    closed = close_window(api, window["id"])
    assert closed["status"] == "CLOSED"
    return stack


def _window_attempt(
    api: ApiClient,
    stack: Stack,
    window_start: str,
    window_end: str,
    window_kind: str = "PERFORMANCE",
):
    return api.create_monitoring_window(
        build_monitoring_window_payload(
            stack.deployment_id,
            stack.version_id,
            window_kind=window_kind,
            window_start=window_start,
            window_end=window_end,
        ),
        RELIABILITY_1,
    )


def _window_count(api: ApiClient, stack: Stack) -> int:
    rows = get_success_data(
        api.list_monitoring_windows(
            RELIABILITY_1, {"deployment_id": stack.deployment_id}
        )
    )
    return len(rows)


def test_a_fully_closed_window_collides_even_at_a_single_shared_instant(api):
    """Touching endpoints are an overlap, in both directions.

    PRD 3.5: "window_start is inclusive, window_end is inclusive", the geometry is
    "closed at both ends with zero buffer, deliberately unlike the half-open
    serve-window rule", and "a new window_start exactly equal to an existing
    window's window_end is an overlap and is rejected".

    Design: Difficulty/temporal_interval_overlap/monitoring_window_fully_closed_zero_buffer_overlap_per_kind
    """
    stack = _closed_incumbent_window(api)

    straddling = _window_attempt(
        api, stack, "2026-08-06T03:00:00Z", "2026-08-06T09:00:00Z"
    )
    validate_error(straddling, ERR_MONITORING_WINDOW_OVERLAP)

    starting_at_its_end = _window_attempt(
        api, stack, _W1_END, "2026-08-06T12:00:00Z"
    )
    validate_error(starting_at_its_end, ERR_MONITORING_WINDOW_OVERLAP)

    ending_at_its_start = _window_attempt(
        api, stack, "2026-08-05T18:00:00Z", _W1_START
    )
    validate_error(ending_at_its_start, ERR_MONITORING_WINDOW_OVERLAP)

    assert _window_count(api, stack) == 1


def test_one_second_past_the_closed_end_is_free_and_so_is_another_kind(api):
    """Zero buffer means exactly zero, and the rule is scoped per kind.

    PRD 3.5 scopes the overlap test to windows "sharing the same deployment_id and
    window_kind" and adds no buffer whatsoever to the closed interval, so the very
    next second is admissible and the same interval under a different monitoring
    family is untouched by the rule.

    Design: Difficulty/temporal_interval_overlap/monitoring_window_fully_closed_zero_buffer_overlap_per_kind
    """
    stack = _closed_incumbent_window(api)

    one_second_later = get_success_data(
        _window_attempt(api, stack, "2026-08-06T06:00:01Z", "2026-08-06T12:00:00Z")
    )
    assert one_second_later["window_start"] == "2026-08-06T06:00:01Z"
    assert one_second_later["status"] == "OPEN"

    other_kind = get_success_data(
        _window_attempt(api, stack, _W1_START, _W1_END, window_kind="DISTRIBUTION")
    )
    assert other_kind["window_kind"] == "DISTRIBUTION"
    assert other_kind["status"] == "OPEN"

    assert _window_count(api, stack) == 3
