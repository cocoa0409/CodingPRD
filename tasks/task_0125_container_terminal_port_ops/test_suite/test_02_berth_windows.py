"""Berth windows: scheduling, physical fit, temporal clash, berthing, OCC,
free-time cascade, unberth compensation, and terminal-state lockdown.

Difficulty instances: resource_temporal_overlap (berth half-open),
transitive_cascade (berth free-time cascade), compensating_invariant (unberth),
cross_cutting (berth OCC stale-version). Corner instances: berth window initial
state, invalid/terminal transitions, fit checks, berth-closed, adjacency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["terminal_admin_headers"]
BERTH = TEST_USERS["berth_planner_headers"]
YARD = TEST_USERS["yard_planner_headers"]


# --------------------------------------------------------------------------- #
# Initial state + invalid / terminal transitions
# --------------------------------------------------------------------------- #
def test_berth_window_initial_state_scheduled(api):
    """PRD §3.2: "A freshly scheduled window begins in `SCHEDULED` status and has
    not yet recorded an `actual_berth_at` or an `actual_depart_at` — both remain
    null until the corresponding action sets them."

    Design: Corner/state_machines/berth_window_initial_state_scheduled
    """
    berth = fx.provision_berth()
    vessel = fx.provision_vessel()
    data = validate_success(
        api.create_berth_window(
            {
                "berth_id": berth["id"],
                "vessel_id": vessel["id"],
                "eta": "2026-02-01T00:00:00.000Z",
                "etd": "2026-02-10T00:00:00.000Z",
            },
            BERTH,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"
    assert data["actual_berth_at"] is None


def test_depart_from_scheduled_returns_invalid_state(api):
    """PRD §3.2: "Departing a vessel advances a `BERTHED` window to the terminal
    `DEPARTED` state (otherwise `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/depart_from_scheduled_returns_invalid_state
    """
    berth = fx.provision_berth()
    vessel = fx.provision_vessel()
    window = fx.create_scheduled_window(berth["id"], vessel["id"])
    validate_error(api.depart_window(window["id"], BERTH), ApiErrorId.ERR_INVALID_STATE.value)


def test_departed_window_cannot_cancel(api):
    """PRD §3.2: "Cancelling a window moves a `SCHEDULED` window to the terminal
    `CANCELLED` state (otherwise `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/terminal_departed_window_cannot_cancel
    """
    _, _, window = fx.provision_berthed_window()
    fx.get_success_data(api.depart_window(window["id"], BERTH))
    validate_error(api.cancel_window(window["id"], BERTH), ApiErrorId.ERR_INVALID_STATE.value)


def test_unberth_blocked_when_cargo_worked(api):
    """PRD §3.2: "[unberth] requires that no container discharged under this window
    has yet been worked, meaning no such container has a handling state of
    `GROUNDED` or `GATED_OUT`; a window whose cargo has already been handled cannot
    be rewound."

    Design: Corner/state_machines/unberth_blocked_when_cargo_worked
    """
    # setup_grounded_container returns (vessel, window, container, slot); the
    # window is BERTHED and its container is already GROUNDED.
    _vessel, window, _container, _slot = fx.setup_grounded_container()
    validate_error(api.unberth_window(window["id"], BERTH), ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# Physical fit + berth-closed
# --------------------------------------------------------------------------- #
def test_berth_window_vessel_draft_exceeded(api):
    """PRD §3.2: "the vessel's `draft_m` must not exceed the berth's `draft_m`,
    failing which the window is rejected with `ERR_BERTH_DRAFT_EXCEEDED`".

    Design: Corner/validations/berth_window_vessel_draft_exceeded
    """
    berth = fx.provision_berth(code="B-FIT1", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="2000700", name="Deep Draft", loa_m=300, draft_m=18.0)
    resp = api.create_berth_window(
        {
            "berth_id": berth["id"],
            "vessel_id": vessel["id"],
            "eta": "2026-02-01T00:00:00.000Z",
            "etd": "2026-02-10T00:00:00.000Z",
        },
        BERTH,
    )
    validate_error(resp, ApiErrorId.ERR_BERTH_DRAFT_EXCEEDED.value)


def test_berth_window_vessel_length_exceeded(api):
    """PRD §3.2: "then the vessel's `loa_m` must not exceed the berth's `length_m`,
    failing which it is rejected with `ERR_BERTH_LENGTH_EXCEEDED`".

    Design: Corner/validations/berth_window_vessel_length_exceeded
    """
    berth = fx.provision_berth(code="B-FIT2", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="2000710", name="Too Long", loa_m=500, draft_m=14.0)
    resp = api.create_berth_window(
        {
            "berth_id": berth["id"],
            "vessel_id": vessel["id"],
            "eta": "2026-02-01T00:00:00.000Z",
            "etd": "2026-02-10T00:00:00.000Z",
        },
        BERTH,
    )
    validate_error(resp, ApiErrorId.ERR_BERTH_LENGTH_EXCEEDED.value)


def test_berth_closed_blocks_berthing(api):
    """PRD §3.2: "The parent berth must be `AVAILABLE`; a `CLOSED` berth yields
    `ERR_BERTH_CLOSED`."

    Design: Corner/validations/berth_closed_blocks_berthing
    """
    berth = fx.provision_berth(code="B-CLSD", length_m=400, draft_m=16.0, status="CLOSED")
    vessel = fx.provision_vessel(imo_number="2000720", name="Closed Berth V", loa_m=300, draft_m=14.0)
    window = fx.create_scheduled_window(berth["id"], vessel["id"])
    resp = api.berth_window(
        window["id"], {"expected_berth_window_version": window["version"]}, BERTH
    )
    validate_error(resp, ApiErrorId.ERR_BERTH_CLOSED.value)


# --------------------------------------------------------------------------- #
# Temporal clash (half-open) + adjacency — resource_temporal_overlap
# --------------------------------------------------------------------------- #
def test_berth_window_overlap_rejected(api):
    """PRD §3.2: "Two windows on the same `berth_id` clash when their half-open
    `[eta, etd)` intervals intersect — formally, when the new window's `eta` is
    earlier than an existing window's `etd` and that existing window's `eta` is
    earlier than the new window's `etd`." A clash is rejected with
    `ERR_BERTH_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/berth_window_half_open_overlap_adjacency_ok
    """
    berth = fx.provision_berth(code="B-16", length_m=400, draft_m=16.0)
    vessel_a = fx.provision_vessel(imo_number="1000016", name="Ovl V1", loa_m=300, draft_m=14.0)
    vessel_b = fx.provision_vessel(imo_number="1000017", name="Ovl V2", loa_m=300, draft_m=14.0)
    fx.create_scheduled_window(
        berth["id"], vessel_a["id"], eta="2026-02-01T00:00:00.000Z", etd="2026-02-03T00:00:00.000Z"
    )
    resp = api.create_berth_window(
        {
            "berth_id": berth["id"],
            "vessel_id": vessel_b["id"],
            "eta": "2026-02-02T12:00:00.000Z",
            "etd": "2026-02-04T00:00:00.000Z",
        },
        BERTH,
    )
    validate_error(resp, ApiErrorId.ERR_BERTH_CONFLICT.value)


def test_berth_window_adjacency_accepted(api):
    """PRD §3.2: "Back-to-back windows that merely touch at the boundary (one
    window's `etd` equal to the next window's `eta`) do **not** clash; adjacency is
    permitted."

    Design: Difficulty/resource_temporal_overlap/berth_window_half_open_overlap_adjacency_ok
    """
    berth = fx.provision_berth(code="B-480", length_m=400, draft_m=16.0)
    vessel_a = fx.provision_vessel(imo_number="2000280", name="Adj V1", loa_m=300, draft_m=14.0)
    vessel_b = fx.provision_vessel(imo_number="2000281", name="Adj V2", loa_m=300, draft_m=14.0)
    fx.create_scheduled_window(
        berth["id"], vessel_a["id"], eta="2026-02-01T00:00:00.000Z", etd="2026-02-03T00:00:00.000Z"
    )
    data = validate_success(
        api.create_berth_window(
            {
                "berth_id": berth["id"],
                "vessel_id": vessel_b["id"],
                "eta": "2026-02-03T00:00:00.000Z",
                "etd": "2026-02-05T00:00:00.000Z",
            },
            BERTH,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"


def test_berth_clash_adjacency_accepted_corner(api):
    """PRD §3.2: "Back-to-back windows that merely touch at the boundary (one
    window's `etd` equal to the next window's `eta`) do **not** clash; adjacency is
    permitted."

    Design: Corner/calculations/berth_clash_adjacency_accepted
    """
    berth = fx.provision_berth(code="B-481", length_m=400, draft_m=16.0)
    vessel_a = fx.provision_vessel(imo_number="2000282", name="AdjC V1", loa_m=300, draft_m=14.0)
    vessel_b = fx.provision_vessel(imo_number="2000283", name="AdjC V2", loa_m=300, draft_m=14.0)
    fx.create_scheduled_window(
        berth["id"], vessel_a["id"], eta="2026-02-01T00:00:00.000Z", etd="2026-02-03T00:00:00.000Z"
    )
    data = validate_success(
        api.create_berth_window(
            {
                "berth_id": berth["id"],
                "vessel_id": vessel_b["id"],
                "eta": "2026-02-03T00:00:00.000Z",
                "etd": "2026-02-05T00:00:00.000Z",
            },
            BERTH,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# Berth free-time cascade — transitive_cascade
# --------------------------------------------------------------------------- #
def test_berth_cascades_free_time_to_all_containers(api):
    """PRD §3.2: "the system sets the window's `actual_berth_at` to the current
    clock instant, moves its `status` to `BERTHED`, and then cascades to every
    container whose `berth_window_id` names this window, recomputing each such
    container's free-time expiry as the window's `actual_berth_at` plus the
    discharge vessel's `free_time_days` days."

    Design: Difficulty/transitive_cascade/berth_cascade_free_time_to_container
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code="B-8", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="1000008", name="FreeTime V", loa_m=300, draft_m=14.0, free_time_days=5)
    window = fx.create_scheduled_window(berth["id"], vessel["id"], etd="2026-02-10T00:00:00.000Z")
    c1 = fx.declare_container(vessel["id"], window["id"], container_number="FREE8000080")
    c2 = fx.declare_container(vessel["id"], window["id"], container_number="FREE8000081")
    berthed = validate_success(
        api.berth_window(window["id"], {"expected_berth_window_version": window["version"]}, BERTH),
        200,
    )
    assert berthed["actual_berth_at"] == "2026-02-01T00:00:00.000Z"
    c1_after = validate_success(api.get_container(c1["id"], YARD), 200)
    c2_after = validate_success(api.get_container(c2["id"], YARD), 200)
    assert c1_after["free_time_expires_at"] == "2026-02-06T00:00:00.000Z"
    assert c2_after["free_time_expires_at"] == "2026-02-06T00:00:00.000Z"


def test_berth_sets_actual_berth_at_to_clock(api):
    """PRD §3.2: "the system sets the window's `actual_berth_at` to the current
    clock instant, moves its `status` to `BERTHED`".

    Design: Difficulty/transitive_cascade/berth_cascade_free_time_to_container
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code="B-8b", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="1000088", name="FreeTime Vb", loa_m=300, draft_m=14.0, free_time_days=5)
    window = fx.create_scheduled_window(berth["id"], vessel["id"], etd="2026-02-10T00:00:00.000Z")
    container = fx.declare_container(vessel["id"], window["id"])
    berthed = validate_success(
        api.berth_window(window["id"], {"expected_berth_window_version": window["version"]}, BERTH),
        200,
    )
    assert berthed["status"] == "BERTHED"
    assert berthed["actual_berth_at"] == "2026-02-01T00:00:00.000Z"
    after = validate_success(api.get_container(container["id"], YARD), 200)
    assert after["free_time_expires_at"] == "2026-02-06T00:00:00.000Z"


# --------------------------------------------------------------------------- #
# Unberth compensation — compensating_invariant
# --------------------------------------------------------------------------- #
def test_unberth_compensates_free_time_to_null(api):
    """PRD §3.2: "On success the system clears `actual_berth_at` back to null,
    returns `status` to `SCHEDULED`, and reverses the earlier cascade by clearing
    the free-time expiry back to null on every container discharged under this
    window."

    Design: Difficulty/compensating_invariant/unberth_compensates_free_time_clock_to_null
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code="B-18", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="1000019", name="Comp V1", loa_m=300, draft_m=14.0, free_time_days=5)
    window = fx.create_scheduled_window(berth["id"], vessel["id"], etd="2026-02-10T00:00:00.000Z")
    container = fx.declare_container(vessel["id"], window["id"], container_number="COMP180180")
    fx.berth_window(window)  # sets free_time_expires_at
    unberthed = validate_success(api.unberth_window(window["id"], BERTH), 200)
    assert unberthed["status"] == "SCHEDULED"
    assert unberthed["actual_berth_at"] is None
    after = validate_success(api.get_container(container["id"], YARD), 200)
    assert after["free_time_expires_at"] is None


def test_unberth_returns_window_to_scheduled(api):
    """PRD §3.2: "Rewinding a berthed window returns it from `BERTHED` to
    `SCHEDULED` — a compensating action for a window berthed in error."

    Design: Difficulty/compensating_invariant/unberth_compensates_free_time_clock_to_null
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code="B-18b", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="1000099", name="Comp V1b", loa_m=300, draft_m=14.0, free_time_days=5)
    window = fx.create_scheduled_window(berth["id"], vessel["id"], etd="2026-02-10T00:00:00.000Z")
    container = fx.declare_container(vessel["id"], window["id"])
    fx.berth_window(window)
    unberthed = validate_success(api.unberth_window(window["id"], BERTH), 200)
    assert unberthed["status"] == "SCHEDULED"
    after = validate_success(api.get_container(container["id"], YARD), 200)
    assert after["free_time_expires_at"] is None


# --------------------------------------------------------------------------- #
# OCC stale-version on berth — cross_cutting_complexity_layers
# --------------------------------------------------------------------------- #
def test_berth_stale_version_rejected(api):
    """PRD §2.7: "A request to move a berth window into its berthed state must carry
    `expected_berth_window_version` ... If the berth window's current `version` has
    advanced beyond that value ... the berth request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/berth_berth_stale_version_conflict
    """
    berth = fx.provision_berth(code="B-800", length_m=300, draft_m=14.0)
    vessel = fx.provision_vessel(imo_number="2000500", name="Occ V", loa_m=280, draft_m=13.0)
    window = fx.create_scheduled_window(berth["id"], vessel["id"])
    resp = api.berth_window(
        window["id"], {"expected_berth_window_version": window["version"] - 1}, BERTH
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = validate_success(api.get_berth_window(window["id"], BERTH), 200)
    assert after["status"] == "SCHEDULED"
