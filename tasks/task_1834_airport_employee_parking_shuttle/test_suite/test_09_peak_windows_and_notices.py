"""Peak windows and service change notices: half-open overlap, remote-only
targeting, checkpoint-driven activation, the 72-hour publish rule, and the
notice effectiveness cascades."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_permit,
    apply_for_permit,
    assert_instant_equals,
    create_employee,
    create_lot,
    create_notice_payload,
    create_peak_window_payload,
    create_program,
    create_route_payload,
    get_lot,
    make_employee_headers,
    open_billing_cycle,
    permit_fee_entries,
    permits_of_lot,
    set_logical_clock,
    setup_active_permit,
    setup_program_lot_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]
PAYROLL = TEST_USERS["payroll_admin_headers"]
DISPATCHER = TEST_USERS["shuttle_dispatcher_headers"]


class TestPeakWindowHalfOpenAdjacency:
    """Half-open [starts_at, ends_at) overlap semantics on a lot's windows."""

    def _setup(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        program = create_program(name="P-PK")
        lot = create_lot(program["id"], code="REM-A", tier="REMOTE", capacity=40)
        first = validate_success(
            api.create_peak_window(
                create_peak_window_payload(lot["id"], "2026-08-10T00:00:00Z",
                                           "2026-08-20T00:00:00Z"),
                ADMIN,
            ),
            201,
        )
        return program, lot, first

    def test_one_second_of_shared_time_is_an_overlap(self, api):
        """PRD section 3.9: "Windows are half-open — they include `starts_at` and
        exclude `ends_at` — and a new window may not overlap any non-`CANCELLED`
        window of the same lot (`ERR_PEAK_WINDOW_OVERLAP`), although
        back-to-back adjacency, where one window's `starts_at` equals another's
        `ends_at`, is allowed."

        Design: Difficulty/resource_temporal_overlap/peak_window_half_open_adjacency
        """
        _program, lot, _first = self._setup(api)
        res = api.create_peak_window(
            create_peak_window_payload(lot["id"], "2026-08-19T23:59:59Z",
                                       "2026-08-25T00:00:00Z"),
            ADMIN,
        )
        validate_error(res, "ERR_PEAK_WINDOW_OVERLAP", expected_status=409)

    def test_back_to_back_adjacency_allowed(self, api):
        """PRD section 3.9: "Windows are half-open — they include `starts_at` and
        exclude `ends_at` — and a new window may not overlap any non-`CANCELLED`
        window of the same lot (`ERR_PEAK_WINDOW_OVERLAP`), although
        back-to-back adjacency, where one window's `starts_at` equals another's
        `ends_at`, is allowed."

        Design: Difficulty/resource_temporal_overlap/peak_window_half_open_adjacency
        """
        _program, lot, _first = self._setup(api)
        res = api.create_peak_window(
            create_peak_window_payload(lot["id"], "2026-08-19T23:59:59Z",
                                       "2026-08-25T00:00:00Z"),
            ADMIN,
        )
        validate_error(res, "ERR_PEAK_WINDOW_OVERLAP", expected_status=409)

        adjacent = validate_success(
            api.create_peak_window(
                create_peak_window_payload(lot["id"], "2026-08-20T00:00:00Z",
                                           "2026-08-25T00:00:00Z"),
                ADMIN,
            ),
            201,
        )
        assert adjacent["status"] == "SCHEDULED"

        _data, meta = validate_paginated(
            api.list_peak_windows(ADMIN, params={"lot_id": lot["id"]})
        )
        assert meta["total_count"] == 2, "the rejected create left no residue"


def test_peak_window_on_core_lot_rejected(api):
    """PRD section 3.9: "The target lot must be tier `REMOTE`
    (`ERR_REMOTE_LOT_REQUIRED`, HTTP 422), and `ends_at` must be strictly later
    than `starts_at`."

    Design: Corner/validations/peak_window_on_core_lot_rejected
    """
    program = create_program(name="P-V8")
    lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=5)

    res = api.create_peak_window(
        create_peak_window_payload(lot["id"], "2026-08-10T00:00:00Z",
                                   "2026-08-20T00:00:00Z"),
        ADMIN,
    )
    validate_error(res, "ERR_REMOTE_LOT_REQUIRED", expected_status=422)

    _data, meta = validate_paginated(
        api.list_peak_windows(ADMIN, params={"lot_id": lot["id"]})
    )
    assert meta["total_count"] == 0, "no window is persisted"


def test_peak_window_activation_and_ending_via_run_ops(api):
    """PRD section 3.9: "When the logical clock has reached a window's
    `starts_at` but not yet its `ends_at`, the checkpoint moves the window from
    `SCHEDULED` to `ACTIVE` and flips its lot from `STANDBY` to `ACTIVATED`,
    making it bookable and running a waitlist promotion pass on it. Once the
    clock reaches `ends_at`, the checkpoint moves the window from `ACTIVE` to
    `ENDED` and returns the lot to `STANDBY` — unbookable for new applications,
    while existing `ACTIVE` permits on the lot are unaffected."
    PRD section 3.3: "Expiry is the system's path: at the ops checkpoint, any
    offer whose `offer_expires_at` is strictly earlier than the current logical
    time moves `OFFERED` to `EXPIRED`, releases the reservation, and the
    promotion pass continues within the same checkpoint."
    PRD section 3.3: "Three structural gates guard the application: the program
    must not be `PROGRAM_FROZEN` or `PROGRAM_CLOSED` (`ERR_PROGRAM_FROZEN`); the
    target lot must be bookable (`ERR_LOT_NOT_BOOKABLE`); and the employee may
    hold at most one non-terminal permit — a second application while any permit
    of theirs sits in `REQUESTED`, `WAITLISTED`, `OFFERED`, `ACTIVE`, or
    `SUSPENDED` is rejected with `ERR_DUPLICATE_ACTIVE_PERMIT`."

    Design: Corner/state_machines/peak_window_activation_and_ending_via_run_ops
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    program = create_program(name="P-PK2", waitlist_offer_ttl_hours=72)
    lot = create_lot(program["id"], code="REM-A", tier="REMOTE", capacity=40)
    assert lot["status"] == "STANDBY", "a REMOTE lot starts STANDBY"
    window = validate_success(
        api.create_peak_window(
            create_peak_window_payload(lot["id"], "2026-08-10T00:00:00Z",
                                       "2026-08-20T00:00:00Z"),
            ADMIN,
        ),
        201,
    )
    e1 = create_employee(program["id"], badge_number="B001")
    e2 = create_employee(program["id"], badge_number="B002")

    # At exactly starts_at (inclusive lower bound) the window activates.
    set_logical_clock("2026-08-10T00:00:00Z")
    validate_success(api.run_program_ops(program["id"], ADMIN), 200)
    mid_window = validate_success(api.get_peak_window(window["id"], ADMIN), 200)
    mid_lot = get_lot(lot["id"])
    assert mid_window["status"] == "ACTIVE"
    assert mid_lot["status"] == "ACTIVATED"

    # The activated remote lot is bookable.
    p1 = apply_for_permit(e1, lot, vehicle_plate="P001")
    assert p1["status"] == "OFFERED"

    # At exactly ends_at (exclusive upper bound) the window ends.
    set_logical_clock("2026-08-20T00:00:00Z")
    validate_success(api.run_program_ops(program["id"], ADMIN), 200)
    end_window = validate_success(api.get_peak_window(window["id"], ADMIN), 200)
    end_lot = get_lot(lot["id"])
    assert end_window["status"] == "ENDED"
    assert end_lot["status"] == "STANDBY"

    # E1's 72h offer (expired 2026-08-13T00:00:00Z) was swept by the same
    # checkpoint's offer-expiry step.
    p1_after = validate_success(api.get_permit(p1["id"], ADMIN), 200)
    assert p1_after["status"] == "EXPIRED"

    # New applications are rejected against the unbookable STANDBY lot.
    res = api.create_permit(
        {"employee_id": e2["id"], "lot_id": lot["id"], "vehicle_plate": "P002"},
        make_employee_headers(e2["id"]),
    )
    validate_error(res, "ERR_LOT_NOT_BOOKABLE", expected_status=409)


def test_notice_publish_min_notice_boundary(api):
    """PRD section 3.9: "A notice event of `PUBLISH` stamps `published_at` and
    moves the notice from `DRAFT` to `PUBLISHED`, but only when `effective_from`
    lies at least 72 hours in the future relative to the logical clock
    (`ERR_NOTICE_EFFECTIVE_TOO_SOON`, HTTP 422) — the program owes its parkers
    three days of warning."

    Design: Corner/validations/notice_publish_min_notice_boundary
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    program = create_program(name="P-V2")
    lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=5)
    n1 = validate_success(
        api.create_notice(
            create_notice_payload("LOT_CLOSURE", "N1", "2026-08-04T00:00:00Z",
                                  lot_id=lot["id"]),
            ADMIN,
        ),
        201,
    )
    n2 = validate_success(
        api.create_notice(
            create_notice_payload("LOT_CLOSURE", "N2", "2026-08-03T23:59:59Z",
                                  lot_id=lot["id"]),
            ADMIN,
        ),
        201,
    )

    # Exactly +72h: inside the rule (boundary is inclusive).
    ok = validate_success(
        api.notice_event(n1["id"], {"event_type": "PUBLISH"}, ADMIN), 200
    )
    assert ok["status"] == "PUBLISHED"
    assert_instant_equals(ok["published_at"], "2026-08-01T00:00:00Z",
                          label="published_at")

    # One second short of 72 hours: rejected.
    res = api.notice_event(n2["id"], {"event_type": "PUBLISH"}, ADMIN)
    validate_error(res, "ERR_NOTICE_EFFECTIVE_TOO_SOON", expected_status=422)
    after = validate_success(api.get_notice(n2["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


class TestNoticeClosureThreeHopCascade:
    """Depth-3 chain from one run-ops trigger: notice EFFECTIVE -> lot CLOSED
    -> permits SUSPENDED(LOT_CLOSURE) -> fee entries reversed and reposted."""

    def _drive(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_active_permit(
            program_overrides={"monthly_subsidy_pool_cents": 100000},
            lot_overrides={"capacity": 5},
        )
        notice = validate_success(
            api.create_notice(
                create_notice_payload("LOT_CLOSURE",
                                      "Lot A closes for resurfacing",
                                      "2026-08-10T00:00:00Z",
                                      lot_id=bundle["lot"]["id"]),
                ADMIN,
            ),
            201,
        )
        validate_success(
            api.notice_event(notice["id"], {"event_type": "PUBLISH"}, ADMIN), 200
        )
        set_logical_clock("2026-08-10T06:00:00Z")
        validate_success(
            api.run_program_ops(bundle["program"]["id"], ADMIN), 200
        )
        return bundle, notice

    def test_notice_lot_permit_hops(self, api):
        """PRD section 3.9: "At the ops checkpoint, every `PUBLISHED` notice whose
        `effective_from` has been reached moves to `EFFECTIVE` and fires its
        cascade. A `LOT_CLOSURE` closes its target lot: from `ACTIVE` or
        `ACTIVATED`, every permit of the lot currently `ACTIVE` is suspended with
        `suspension_reason` `LOT_CLOSURE` and `suspended_at` stamped, and each
        such suspension applies the §3.5 span truncation — the pending fee entry
        whose span contains the suspension date is reversed and reposted through
        that date — in the program's `OPEN` cycle when one exists; a lot sitting
        in `STANDBY` simply closes, with no permit cascade."

        Design: Difficulty/transitive_cascade/notice_closure_three_hop_cascade
        """
        bundle, notice = self._drive(api)
        notice_after = validate_success(api.get_notice(notice["id"], ADMIN), 200)
        assert notice_after["status"] == "EFFECTIVE", "hop 1"

        lot_after = get_lot(bundle["lot"]["id"])
        assert lot_after["status"] == "CLOSED", "hop 2, caused by hop 1"

        permit_after = validate_success(
            api.get_permit(bundle["permit"]["id"], ADMIN), 200
        )
        assert permit_after["status"] == "SUSPENDED", "hop 3, caused by hop 2"
        assert permit_after["suspension_reason"] == "LOT_CLOSURE"
        assert_instant_equals(permit_after["suspended_at"], "2026-08-10T06:00:00Z",
                              label="suspended_at (checkpoint time)")

    def test_fee_reversed_and_truncated_repost(self, api):
        """PRD section 3.9: "At the ops checkpoint, every `PUBLISHED` notice whose
        `effective_from` has been reached moves to `EFFECTIVE` and fires its
        cascade. A `LOT_CLOSURE` closes its target lot: from `ACTIVE` or
        `ACTIVATED`, every permit of the lot currently `ACTIVE` is suspended with
        `suspension_reason` `LOT_CLOSURE` and `suspended_at` stamped, and each
        such suspension applies the §3.5 span truncation — the pending fee entry
        whose span contains the suspension date is reversed and reposted through
        that date — in the program's `OPEN` cycle when one exists; a lot sitting
        in `STANDBY` simply closes, with no permit cascade."
        PRD section 3.5: "The permit's `PENDING` `PERMIT_FEE` entry in the
        program's `OPEN` cycle whose span contains the suspension date is
        reversed, and a truncated `PENDING` repost is created covering the span
        start through the suspension date, priced per §3.4."

        Design: Difficulty/transitive_cascade/notice_closure_three_hop_cascade
        """
        bundle, _notice = self._drive(api)
        fees = permit_fee_entries(bundle["permit"]["id"])
        by_span = {(f["span_start"], f["span_end"]): f for f in fees}
        original = by_span[("2026-08-01", "2026-08-31")]
        truncated = by_span[("2026-08-01", "2026-08-10")]
        assert original["amount_cents"] == 10800
        assert original["status"] == "REVERSED"
        # net 10800 over 10 active days of 31.
        assert truncated["amount_cents"] == 3484
        assert truncated["status"] == "PENDING"

        cycle = validate_success(
            api.get_billing_cycle(bundle["cycle"]["id"], PAYROLL), 200
        )
        assert cycle["total_charges_cents"] == 3484


def test_notice_headway_change_and_route_suspension_effects(api):
    """PRD section 3.9: "A `ROUTE_SUSPENSION` suspends its route — trips are not
    cancelled, but departures are blocked while suspended. A `HEADWAY_CHANGE`
    rewrites the route's `headway_target_minutes` to `new_headway_minutes`."
    PRD section 3.9: "At the ops checkpoint, every `PUBLISHED` notice whose
    `effective_from` has been reached moves to `EFFECTIVE` and fires its
    cascade."

    Design: Corner/endpoints/notice_headway_change_and_route_suspension_effects
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    program = create_program(name="P-EP3")
    lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=5)
    route = validate_success(
        api.create_route(
            create_route_payload(lot["id"], code="R1", headway_target_minutes=10,
                                 operating_cost_per_trip_cents=4000),
            DISPATCHER,
        ),
        201,
    )
    n1 = validate_success(
        api.create_notice(
            create_notice_payload("HEADWAY_CHANGE", "Headway to 15",
                                  "2026-08-05T00:00:00Z", route_id=route["id"],
                                  new_headway_minutes=15),
            ADMIN,
        ),
        201,
    )
    n2 = validate_success(
        api.create_notice(
            create_notice_payload("ROUTE_SUSPENSION", "Route suspended",
                                  "2026-08-06T00:00:00Z", route_id=route["id"]),
            ADMIN,
        ),
        201,
    )
    for notice in (n1, n2):
        validate_success(
            api.notice_event(notice["id"], {"event_type": "PUBLISH"}, ADMIN), 200
        )

    set_logical_clock("2026-08-05T00:00:01Z")
    validate_success(api.run_program_ops(program["id"], ADMIN), 200)
    after_headway = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert after_headway["headway_target_minutes"] == 15
    assert after_headway["status"] == "ACTIVE"

    set_logical_clock("2026-08-06T00:00:01Z")
    validate_success(api.run_program_ops(program["id"], ADMIN), 200)
    after_suspension = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert after_suspension["status"] == "SUSPENDED"
    assert after_suspension["headway_target_minutes"] == 15


def test_occupied_slots_reconciled_after_notice_cascade(api):
    """PRD section 2.10: "Derived figures — a lot's `occupied_slots` and
    `reserved_slots`, an employee's `balance_due_cents` and `standing`, a cycle's
    `total_charges_cents` — are always recomputed from their defining source rows
    rather than stored independently, so they stay correct after every direct
    write and every cascade."
    PRD section 3.9: "At the ops checkpoint, every `PUBLISHED` notice whose
    `effective_from` has been reached moves to `EFFECTIVE` and fires its
    cascade. A `LOT_CLOSURE` closes its target lot: from `ACTIVE` or `ACTIVATED`,
    every permit of the lot currently `ACTIVE` is suspended with
    `suspension_reason` `LOT_CLOSURE` and `suspended_at` stamped, and each such
    suspension applies the §3.5 span truncation — the pending fee entry whose
    span contains the suspension date is reversed and reposted through that date
    — in the program's `OPEN` cycle when one exists; a lot sitting in `STANDBY`
    simply closes, with no permit cascade."

    Design: Corner/cross_cutting_layers/occupied_slots_reconciled_after_notice_cascade
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_program_lot_cycle(
        program_overrides={"monthly_subsidy_pool_cents": 0},
        lot_overrides={"capacity": 5},
    )
    for badge, plate in (("B001", "P001"), ("B002", "P002")):
        emp = create_employee(bundle["program"]["id"], badge_number=badge)
        permit = apply_for_permit(emp, bundle["lot"], vehicle_plate=plate)
        accept_permit(permit, emp)
    assert get_lot(bundle["lot"]["id"])["occupied_slots"] == 2

    notice = validate_success(
        api.create_notice(
            create_notice_payload("LOT_CLOSURE", "Closure", "2026-08-10T00:00:00Z",
                                  lot_id=bundle["lot"]["id"]),
            ADMIN,
        ),
        201,
    )
    validate_success(api.notice_event(notice["id"], {"event_type": "PUBLISH"}, ADMIN),
                     200)
    set_logical_clock("2026-08-10T06:00:00Z")
    validate_success(api.run_program_ops(bundle["program"]["id"], ADMIN), 200)

    lot = get_lot(bundle["lot"]["id"])
    assert lot["status"] == "CLOSED"
    assert lot["occupied_slots"] == 0, "recomputed from permit states"
    assert lot["reserved_slots"] == 0

    suspended = permits_of_lot(bundle["lot"]["id"], status="SUSPENDED")
    assert len(suspended) == 2
    assert all(p["suspension_reason"] == "LOT_CLOSURE" for p in suspended)
