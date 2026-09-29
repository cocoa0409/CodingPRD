"""Two resources whose reservation windows use opposite boundary conventions.

A keg's custody timeline is a chain of half-open intervals whose boundary instant
belongs to the open spell, while a wash line's intake window is closed at both
ends and rejects its own endpoint.  Each scenario probes the boundary instant and
the interior of the same reservation so the convention is unambiguous.
"""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    SECOND_TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    make_distributor_headers,
    make_technician_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
FIRST_TECHNICIAN = make_technician_headers(TECHNICIAN_USER_ID)
SECOND_TECHNICIAN = make_technician_headers(SECOND_TECHNICIAN_USER_ID)

CLOCK = "2026-08-01T23:00:00Z"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
    "restrict_threshold_pct": 25,
    "freeze_threshold_pct": 10,
    "restricted_max_kegs_per_order": 2,
}

AGREEMENT = {
    "per_fill_rate_cents": 2200,
    "replenishment_threshold_pct": 20,
}


def _keg_whose_open_spell_starts_at_noon():
    """One keg filled at 02:00 and taken into trade at 12:00, so its open custody
    spell starts exactly at noon and the closed spell before it runs 02:00-12:00."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=4,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    distributor = fixtures.create_distributor(return_incentive_rate_cents_per_keg=250)
    fixtures.sign_cooperation_agreement(distributor["id"], "BRONZE", "2026-08-01")

    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T01:00:00Z"
    )
    keg_id = order["allocated_keg_ids"][0]
    fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")
    fixtures.distribution_scan(keg_id, distributor["id"], "2026-08-01T12:00:00Z", "RDG")

    ctx["distributor"] = distributor
    ctx["order"] = order
    ctx["keg_id"] = keg_id
    ctx["keg_in_trade"] = fixtures.read_keg(keg_id)
    return ctx


def _return_attempt(keg_id, distributor_id, scanned_at):
    return api_client.scan_keg(
        keg_id,
        factories.return_scan_payload(distributor_id, scanned_at, "RDG"),
        make_distributor_headers(distributor_id),
    )


def test_a_scan_exactly_at_the_open_spell_start_is_accepted():
    """The retail scan is recorded at the very instant the distribution scan
    opened the current spell, and a zero-length spell is admitted: the two
    intervals touch at a point and do not overlap.

    PRD: "A new scan whose `scanned_at` is at or after `dwell_started_at` lands in
    the open interval and is accepted — including the case where `scanned_at` is
    exactly equal to `dwell_started_at`, because two adjacent intervals touching
    at a single point do not overlap."

    PRD: "A **retail** scan moves the keg `IN_TRADE → AT_RETAIL` and is recorded
    against a `retail_account_code`; it closes the current custody spell and
    resets `dwell_started_at`, but it deliberately does **not** clear
    `distributor_custody_started_at`, because the wholesaler stays accountable for
    the shell all the way through the retail leg."

    Design: Difficulty/resource_temporal_overlap/keg_custody_interval_half_open_boundary_accepted_interior_rejected
    """
    ctx = _keg_whose_open_spell_starts_at_noon()
    assert ctx["keg_in_trade"]["dwell_started_at"] == "2026-08-01T12:00:00Z"
    assert ctx["keg_in_trade"]["custody_state"] == "IN_TRADE"

    scan = fixtures.retail_scan(
        ctx["keg_id"],
        ctx["distributor"]["id"],
        "RA-88",
        "2026-08-01T12:00:00Z",
        "RDG",
    )
    assert scan["scan_point"] == "RETAIL"
    assert scan["dwell_days_closed"] == 0
    assert scan["is_late_arrival"] is False

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "AT_RETAIL"
    assert keg["scan_count"] == 3
    assert keg["distributor_custody_started_at"] == "2026-08-01T12:00:00Z"


def test_a_scan_strictly_inside_a_closed_spell_is_refused():
    """A return stamped three hours before the open spell began falls inside the
    spell that was closed when the keg left the brewery, and is refused.

    PRD: "A new scan whose `scanned_at` is strictly earlier than `dwell_started_at`
    falls inside an interval already closed by a party that no longer holds the
    keg, and is rejected with `ERR_CUSTODY_INTERVAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/keg_custody_interval_half_open_boundary_accepted_interior_rejected
    """
    ctx = _keg_whose_open_spell_starts_at_noon()
    fixtures.retail_scan(
        ctx["keg_id"], ctx["distributor"]["id"], "RA-88", "2026-08-01T12:00:00Z", "RDG"
    )

    refused = _return_attempt(
        ctx["keg_id"], ctx["distributor"]["id"], "2026-08-01T09:00:00Z"
    )
    validate_error(refused, ApiErrorId.ERR_CUSTODY_INTERVAL_CONFLICT.value, 409)

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "AT_RETAIL"
    assert keg["scan_count"] == 3
    assert keg["dwell_started_at"] == "2026-08-01T12:00:00Z"


def test_the_same_return_re_issued_at_the_boundary_instant_is_admitted():
    """Moved to the boundary instant itself the identical return is accepted, and
    because every spell on this keg is under a day the floored dwell never
    accumulates anything.

    PRD: "The spell clock is likewise clamped: `dwell_days_closed` is the
    difference between this scan's `scanned_at` and the keg's `dwell_started_at`,
    floored to whole days and floored at 0, so a late arrival contributes zero
    dwell days rather than a negative number, and `dwell_started_at` becomes
    whichever is later of its existing value and the new `scanned_at`."

    PRD: "The keg moves `IN_TRADE → IN_SERVICE` or `AT_RETAIL → IN_SERVICE`, the
    custody spell closes, `dwell_started_at` resets to `scanned_at`, and
    `distributor_custody_started_at` is cleared."

    Design: Difficulty/resource_temporal_overlap/keg_custody_interval_half_open_boundary_accepted_interior_rejected
    """
    ctx = _keg_whose_open_spell_starts_at_noon()
    fixtures.retail_scan(
        ctx["keg_id"], ctx["distributor"]["id"], "RA-88", "2026-08-01T12:00:00Z", "RDG"
    )
    validate_error(
        _return_attempt(ctx["keg_id"], ctx["distributor"]["id"], "2026-08-01T09:00:00Z"),
        ApiErrorId.ERR_CUSTODY_INTERVAL_CONFLICT.value,
        409,
    )

    scan = validate_success(
        _return_attempt(ctx["keg_id"], ctx["distributor"]["id"], "2026-08-01T12:00:00Z"),
        201,
    )
    assert scan["scan_point"] == "RETURN"
    assert scan["dwell_days_closed"] == 0

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "IN_SERVICE"
    assert keg["scan_count"] == 4
    assert keg["distributor_custody_started_at"] is None
    assert keg["cumulative_dwell_days"] == 0

    rows, _meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR, params={"distributor_id": ctx["distributor"]["id"]}
        )
    )
    assert len(rows) == 1
    accrual = rows[0]
    assert accrual["accrual_type"] == "RETURN_DWELL"
    assert accrual["dwell_days"] == 0
    assert accrual["tier_pct_bp"] == 10000
    assert accrual["cooperation_multiplier_bp"] == 10000
    assert accrual["incentive_cents"] == 250

    distributor = fixtures.read_distributor(ctx["distributor"]["id"])
    assert distributor["total_returns_count"] == 1
    assert distributor["on_time_returns_count"] == 1
    assert distributor["on_time_return_pct"] == 100.00
    assert distributor["avg_dwell_days"] == 0.00


def _wash_line_with_one_intake_on_the_books():
    """A two-slot wash line with a four-hour intake buffer and one cycle already
    received at midnight, which reserves the closed span 00:00 through 04:00.

    All four kegs are imported already `IN_SERVICE`, so cycles can be booked with
    no scan traffic at all, and the clock is then moved a day forward so every
    timestamp the scenario uses is in the past.
    """
    staged = fixtures.setup_pool_with_kegs(
        keg_count=4,
        pool_overrides=dict(POOL),
        keg_specs=[{"initial_custody_state": "IN_SERVICE"} for _ in range(4)],
        clock="2026-08-01T00:00:00Z",
    )
    center = fixtures.create_service_center(
        2, name="Denver Wash Line", region_code="CO", intake_buffer_hours=4
    )
    first_cycle = fixtures.create_service_cycle(
        staged["kegs"][0]["id"],
        center["id"],
        "2026-08-01T00:00:00Z",
        headers=FIRST_TECHNICIAN,
    )
    fixtures.pin_clock("2026-08-02T00:00:00Z")
    return {
        "pool": staged["pool"],
        "kegs": staged["kegs"],
        "center": center,
        "first_cycle": first_cycle,
    }


def _intake_attempt(keg_id, center_id, received_at):
    return api_client.create_service_cycle(
        factories.create_service_cycle_payload(keg_id, center_id, received_at),
        FIRST_TECHNICIAN,
    )


def _open_cycle_count(center_id):
    center = get_success_data(api_client.get_service_center(center_id, OPERATOR))
    return center["open_cycle_count"]


def test_an_intake_exactly_at_the_buffer_edge_is_rejected():
    """A `received_at` exactly four hours after the standing intake sits on the
    upper endpoint of a span that is closed at both ends, so it is refused, and one
    millisecond later it is admitted.

    PRD: "The **intake window** comes first: each cycle ever received at a centre
    reserves the span from its `received_at` through `received_at` plus
    `intake_buffer_hours`, **closed at both ends**, and a new `received_at` falling
    anywhere in that span — including on either endpoint — is refused with
    `ERR_INTAKE_WINDOW_CONFLICT`."

    PRD: "A `received_at` exactly `intake_buffer_hours` after an existing intake is
    therefore rejected, and one millisecond later is accepted."

    Design: Difficulty/resource_temporal_overlap/service_center_closed_intake_window_and_aggregate_capacity
    """
    ctx = _wash_line_with_one_intake_on_the_books()
    center_id = ctx["center"]["id"]
    second_keg_id = ctx["kegs"][1]["id"]

    assert ctx["center"]["intake_buffer_hours"] == 4
    assert ctx["first_cycle"]["stage"] == "RECEIVED"
    assert _open_cycle_count(center_id) == 1

    on_the_edge = _intake_attempt(second_keg_id, center_id, "2026-08-01T04:00:00.000Z")
    validate_error(on_the_edge, ApiErrorId.ERR_INTAKE_WINDOW_CONFLICT.value, 409)
    assert _open_cycle_count(center_id) == 1

    just_past = validate_success(
        _intake_attempt(second_keg_id, center_id, "2026-08-01T04:00:00.001Z"), 201
    )
    assert just_past["stage"] == "RECEIVED"
    assert _open_cycle_count(center_id) == 2


def test_the_capacity_refusal_is_an_aggregate_count_and_not_a_pairwise_overlap():
    """A third intake at 09:00 lies outside both reserved spans, so nothing about
    it overlaps anything; it is refused only because the line is already holding as
    many open cycles as it can.

    PRD: "Only if the window is clear does the **aggregate occupancy** check run:
    the centre's `open_cycle_count` must be strictly below
    `concurrent_cycle_capacity`, otherwise `ERR_SERVICE_CAPACITY_EXCEEDED`."

    PRD: "This second check is a count, not a pairwise comparison — each cycle is
    admissible on its own and only the collective breaches the limit — and because
    `RELEASED` cycles leave the count, releasing one cycle frees exactly one slot."

    Design: Difficulty/resource_temporal_overlap/service_center_closed_intake_window_and_aggregate_capacity
    """
    ctx = _wash_line_with_one_intake_on_the_books()
    center_id = ctx["center"]["id"]

    validate_error(
        _intake_attempt(ctx["kegs"][1]["id"], center_id, "2026-08-01T04:00:00.000Z"),
        ApiErrorId.ERR_INTAKE_WINDOW_CONFLICT.value,
        409,
    )
    validate_success(
        _intake_attempt(ctx["kegs"][1]["id"], center_id, "2026-08-01T04:00:00.001Z"), 201
    )

    assert ctx["center"]["concurrent_cycle_capacity"] == 2
    assert _open_cycle_count(center_id) == 2

    refused = _intake_attempt(ctx["kegs"][2]["id"], center_id, "2026-08-01T09:00:00Z")
    validate_error(refused, ApiErrorId.ERR_SERVICE_CAPACITY_EXCEEDED.value, 409)

    assert _open_cycle_count(center_id) == 2
    rows, _meta = validate_paginated(
        api_client.list_service_cycles(OPERATOR, params={"keg_id": ctx["kegs"][2]["id"]})
    )
    assert rows == []


def test_releasing_one_cycle_frees_exactly_one_slot():
    """Running the first cycle to `RELEASED` returns its slot to the line, and the
    byte-identical 09:00 intake that was refused for capacity now succeeds even
    though the released cycle's own window is still on file.

    PRD: "Windows are evaluated against every cycle the centre has ever received,
    `RELEASED` ones included, because the wash-line block was consumed whatever
    became of the cycle afterwards."

    PRD: "This second check is a count, not a pairwise comparison — each cycle is
    admissible on its own and only the collective breaches the limit — and because
    `RELEASED` cycles leave the count, releasing one cycle frees exactly one slot."

    Design: Difficulty/resource_temporal_overlap/service_center_closed_intake_window_and_aggregate_capacity
    """
    ctx = _wash_line_with_one_intake_on_the_books()
    center_id = ctx["center"]["id"]
    third_keg_id = ctx["kegs"][2]["id"]

    validate_error(
        _intake_attempt(ctx["kegs"][1]["id"], center_id, "2026-08-01T04:00:00.000Z"),
        ApiErrorId.ERR_INTAKE_WINDOW_CONFLICT.value,
        409,
    )
    validate_success(
        _intake_attempt(ctx["kegs"][1]["id"], center_id, "2026-08-01T04:00:00.001Z"), 201
    )
    validate_error(
        _intake_attempt(third_keg_id, center_id, "2026-08-01T09:00:00Z"),
        ApiErrorId.ERR_SERVICE_CAPACITY_EXCEEDED.value,
        409,
    )

    cycle_id = ctx["first_cycle"]["id"]
    fixtures.record_clean(cycle_id, "2026-08-01T10:00:00Z", caustic_cycle_minutes=15)
    fixtures.record_inspect(cycle_id, "2026-08-01T11:00:00Z", inspection_result="PASS")
    fixtures.record_pressure_test(
        cycle_id,
        "2026-08-01T12:00:00Z",
        pressure_test_psi=34,
        pressure_test_result="PASS",
    )
    released = fixtures.release_cycle(
        cycle_id, "2026-08-01T13:00:00Z", headers=SECOND_TECHNICIAN
    )
    assert released["stage"] == "RELEASED"
    assert released["pressure_test_performed_by_user_id"] == TECHNICIAN_USER_ID
    assert released["released_by_user_id"] == SECOND_TECHNICIAN_USER_ID
    assert _open_cycle_count(center_id) == 1

    first_keg = fixtures.read_keg(ctx["kegs"][0]["id"])
    assert first_keg["custody_state"] == "IN_FLOAT"
    assert first_keg["service_state"] == "SERVICE_OK"

    admitted = validate_success(
        _intake_attempt(third_keg_id, center_id, "2026-08-01T09:00:00Z"), 201
    )
    assert admitted["received_at"] == "2026-08-01T09:00:00Z"
    assert admitted["stage"] == "RECEIVED"
    assert _open_cycle_count(center_id) == 2
