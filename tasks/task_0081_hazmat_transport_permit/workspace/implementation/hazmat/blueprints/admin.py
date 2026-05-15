"""The three test-harness-mode endpoints: clock-advance, sweep-run, and
the conventional admin-reset that wipes the per-process singletons
between tests.

The PRD §2.5's H3 paragraph names the first two endpoints' contracts:

  - `POST /v1/_clock/advance` accepts the request body
    `{"advance_seconds": <integer-or-float, nonnegative>,
      "run_sweep_after_advance": <boolean, default false>}`. The response
    body carries `prior_now` (the pre-advance simulated-clock value as
    an ISO 8601 millisecond-and-Z string), `new_now` (the post-advance
    value), `advance_seconds_applied` (the body's echoed integer-or-
    float), and `sweep_summary` which is null when the
    `run_sweep_after_advance` flag is false and is the same shape as
    the standalone sweep-run's response when the flag is true. The
    HTTP status is 200. The validation tier rejects a negative
    `advance_seconds` and a non-boolean `run_sweep_after_advance` and
    an `advance_seconds` exceeding the deployment's
    `CLOCK_ADVANCE_MAX_SECONDS` upper bound with `ERR_VALIDATION` 422
    each.

  - `POST /v1/_sweep/run` accepts the request body
    `{"scope": <one of "ALL", "PERMITS_ONLY", "DRIVERS_ONLY", default
    "ALL">}`. The response is the structured summary the `sweep.run_sweep`
    function returns. The HTTP status is 200.

  - `POST /v1/_admin/reset` is the standard PRD-bench between-test
    state-wipe affordance the test-harness fixture-framework's
    autoreset hook invokes. The body is an empty object (or omitted
    entirely; the handler accepts either). The handler calls the
    three init hooks `store.init_store`, `clock.init_clock`, and
    `idempotency.init_idempotency_registry` to wipe the in-memory
    state. The response is the empty data object in the standard
    envelope at HTTP 200. The endpoint is gated to the `TestHarness`
    role per the auth middleware's RBAC matrix; in a production
    deployment where the TestHarness role is unrecognized the request
    is the standard `ERR_UNAUTHENTICATED` 401 from the auth tier.

All three endpoints are TestHarness-only by the §1.7 RBAC matrix's
column-uniform-deny TestHarness column with the two named-allow cells
for the clock-and-sweep pair, and the conventional third allow-cell for
the admin-reset that the standard PRD-bench convention adds.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app

from ..clock import advance_clock, current_now, iso_format, iso_now
from ..config import Constants
from ..envelope import get_json_body, make_object_response
from ..errors import APIError
from ..idempotency import init_idempotency_registry
from ..store import init_store
from ..clock import init_clock
from ..sweep import run_sweep
from ..validation import require_bool, require_enum, require_number


admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/_clock/advance", methods=["POST"])
def post_clock_advance() -> Any:
    """The test-harness's clock-advance endpoint. Reads the body's
    nonnegative `advance_seconds` and the optional boolean
    `run_sweep_after_advance` flag, advances the simulated wall-clock
    by the given seconds (a zero-duration advance is a permitted no-
    op per the §2.5 paragraph's "zero is a permitted no-op for the
    harness to sync its local clock idea with the server's"), and
    optionally fires the sweep after the advance.

    The response carries `prior_now`, `new_now`, `advance_seconds_applied`,
    and `sweep_summary` (null when the flag was false, the sweep's
    standard response payload when the flag was true).

    The validation tier's bounds check on `advance_seconds` is the
    nonnegativity rule and the upper-bound check against the
    deployment's `CLOCK_ADVANCE_MAX_SECONDS` constant for the "the
    harness can't jump the clock by more than a century" safety rail
    that prevents accidental year-9999 overflow.
    """
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]

    # The body shape: a required nonnegative number for the advance
    # duration and an optional boolean flag for the immediate sweep
    # after the advance.
    advance_seconds = require_number(
        body,
        "advance_seconds",
        nonnegative=True,
        range_inclusive=(0.0, float(constants.clock_advance_max_seconds)),
    )
    assert advance_seconds is not None  # not optional
    run_sweep_after_advance = require_bool(
        body, "run_sweep_after_advance", optional=True
    )
    if run_sweep_after_advance is None:
        run_sweep_after_advance = False

    # Advance the clock and optionally run the sweep.
    prior_now, new_now = advance_clock(float(advance_seconds))

    sweep_summary: Any = None
    if run_sweep_after_advance:
        # The combined-advance-and-sweep path. The sweep's `scope`
        # argument is unspecified in this combined call's request shape
        # — the scaffold's §1.5 prose names the combined call's
        # convention as "the standalone sweep-run's default `ALL` scope
        # is what the combined call fires". The handler invokes the
        # sweep with the canonical `"ALL"` scope.
        sweep_summary = run_sweep("ALL", constants)

    data = {
        "prior_now": iso_format(prior_now),
        "new_now": iso_format(new_now),
        "advance_seconds_applied": float(advance_seconds),
        "sweep_summary": sweep_summary,
    }
    return make_object_response(data, http_status=200)


@admin_bp.route("/_sweep/run", methods=["POST"])
def post_sweep_run() -> Any:
    """The test-harness's sweep-run endpoint. Reads the body's optional
    `scope` enum (`"ALL"` default, `"PERMITS_ONLY"` for the permit-side
    fan-out only, `"DRIVERS_ONLY"` for the per-driver rolling-window-
    fall-off-recompute only) and invokes the canonical
    `sweep.run_sweep(scope, constants)` function. The handler maps the
    sweep's return dict onto the response's `data` block in the
    standard envelope at HTTP 200.

    A body-absent or scope-absent case defaults the scope to `"ALL"`
    per the §2.5 paragraph's "the default is `ALL`" rule. An out-of-
    enum scope value is the catch-all body-shape `ERR_VALIDATION` 422.
    """
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]

    scope = require_enum(
        body,
        "scope",
        allowed=("ALL", "PERMITS_ONLY", "DRIVERS_ONLY"),
        optional=True,
    )
    if scope is None:
        scope = "ALL"

    summary = run_sweep(scope, constants)
    return make_object_response(summary, http_status=200)


@admin_bp.route("/_admin/reset", methods=["POST"])
def post_admin_reset() -> Any:
    """The standard PRD-bench between-test state-wipe affordance the
    test fixtures' autoreset hook invokes. Calls the three init hooks
    on the per-process singletons (`store.init_store` clears every
    entity table, `clock.init_clock` re-anchors the simulated wall
    clock to the OS wall clock, `idempotency.init_idempotency_registry`
    clears the per-trip idempotency-key slots) so each test starts
    from the same blank-world baseline. The response is the empty
    `{}` data object in the standard envelope at HTTP 200; the meta
    block's `api_request_timestamp` carries the new post-reset
    simulated-clock value (which equals the OS clock value at the
    moment of the reset because `init_clock` re-anchors to the OS
    clock).

    The endpoint is TestHarness-only per the auth middleware's RBAC
    matrix's row for `POST /v1/_admin/reset` — in a production
    deployment where the TestHarness role is unrecognized the auth
    tier's role-canonicalization check rejects every request to this
    endpoint with `ERR_UNAUTHENTICATED` 401, which is the standard
    "the test-mode endpoint is unreachable in production" pattern.

    The body is ignored; the canonical convention is the empty JSON
    object `{}` or no body at all. The handler does not raise on a
    non-object body since the body-shape catch-all-on-an-extra-key
    rule is not asserted here (an extra field is silently ignored).
    """
    # Read the body just to advance Flask's body-read state cleanly,
    # but do not validate any field — the reset has no input.
    _ = get_json_body()

    # Fire the three resets in order: the clock is re-anchored to the
    # OS wall clock so the test starts at a known time-origin; the
    # store and the idempotency registry are wiped so no row from a
    # prior test contaminates the new one.
    init_clock()
    init_store()
    init_idempotency_registry()

    # The empty-data success envelope.
    data: dict[str, Any] = {
        "reset_at": iso_now(),
        "message": "in-memory state wiped",
    }
    return make_object_response(data, http_status=200)
