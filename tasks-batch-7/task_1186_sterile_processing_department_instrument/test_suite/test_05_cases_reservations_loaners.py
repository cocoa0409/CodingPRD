"""OR scheduling: reservations and their gates, case lifecycle, the lazy
sterility sweep on reserved trays, and loaner-set intake deadlines.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]
SCHED = TEST_USERS["or_scheduler_headers"]


class TestTrayReservationGatedByLoadRelease:
    """A tray becomes reservable only when its load crosses COMPLETED ->
    RELEASED (two tests, one design instance)."""

    def test_reservation_rejected_while_tray_in_load(self, api):
        """PRD §3.6: "The tray must be `STERILE` as stored (post-sweep, else
        `ERR_TRAY_NOT_STERILE`)".

        Design: Difficulty/cross_entity_state_dependency/tray_reservation_gated_by_load_release
        """
        s = fx.setup_reservation_gated_scenario(api)
        resp = api.create_reservation(
            s.cj["id"],
            f.create_reservation_payload(s.tj["id"], s.cj["version"]),
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_TRAY_NOT_STERILE)

    def test_reservation_succeeds_after_release_with_same_version(self, api):
        """PRD §2.7: "Each successful reservation creation mutates the case
        (status recompute) and increments `ORCase.version` by 1, so a second
        creation carrying a previously observed version is deterministically
        rejected as stale." — a rejected attempt is not a successful creation,
        so the observed version remains current.

        Design: Difficulty/cross_entity_state_dependency/tray_reservation_gated_by_load_release
        """
        s = fx.setup_reservation_gated_scenario(api)
        blocked = api.create_reservation(
            s.cj["id"],
            f.create_reservation_payload(s.tj["id"], s.cj["version"]),
            SCHED,
        )
        validate_error(blocked, ApiErrorId.ERR_TRAY_NOT_STERILE)

        fx.set_clock(api, "2026-05-01T03:00:00Z")
        bi = fx.first_bi_of_load(api, s.lj["id"])
        fx.record_bi(api, bi["id"], "NEGATIVE")
        fx.release_load(api, s.lj["id"], s.tech_s["id"])

        case = validate_success(api.get_or_case(s.cj["id"], SCHED))
        assert case["version"] == s.cj["version"], (
            "the rejected reservation must not bump the case version"
        )
        retry = validate_success(
            api.create_reservation(
                s.cj["id"],
                f.create_reservation_payload(s.tj["id"], case["version"]),
                SCHED,
            ),
            201,
        )
        assert retry["status"] == "RESERVED"
        tray = validate_success(api.get_tray(s.tj["id"], ADMIN))
        assert tray["status"] == "STERILE", "a booking is temporal, not a status change"


class TestSterilityExpiryExactEquality:
    """The strict `>` between tray expiry and case start (two tests, one
    design instance)."""

    def test_case_start_exactly_at_expiry_rejected(self, api):
        """PRD §2.10: "Reserving a tray for a case requires
        `sterility_expires_at` to be strictly later than the case's
        `scheduled_start_at`". PRD §3.6: "this expiry gate
        (`ERR_STERILITY_EXPIRED_FOR_CASE`)".

        Design: Difficulty/boundary_precision_check/sterility_expiry_exact_equality_rejected
        """
        s = fx.setup_sterility_boundary_scenario(api)
        resp = api.create_reservation(
            s.ce1["id"],
            f.create_reservation_payload(s.te["id"], s.ce1["version"]),
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_STERILITY_EXPIRED_FOR_CASE)

    def test_case_start_one_minute_before_expiry_accepted(self, api):
        """PRD §2.10: "Reserving a tray for a case requires
        `sterility_expires_at` to be strictly later than the case's
        `scheduled_start_at`". PRD §3.6: "On success the reservation is
        created `RESERVED` with `reserved_at` stamped".

        Design: Difficulty/boundary_precision_check/sterility_expiry_exact_equality_rejected
        """
        s = fx.setup_sterility_boundary_scenario(api)
        ok = validate_success(
            api.create_reservation(
                s.ce2["id"],
                f.create_reservation_payload(s.te["id"], s.ce2["version"]),
                SCHED,
            ),
            201,
        )
        assert ok["status"] == "RESERVED"
        tray = validate_success(api.get_tray(s.te["id"], ADMIN))
        assert tray["status"] == "STERILE", "booking leaves the tray untouched"


class TestTrayReservationBufferedGap45:
    """The 45-minute turnover buffer on the tray resource (two tests, one
    design instance)."""

    def test_gap_of_exactly_45_minutes_allowed(self, api):
        """PRD §3.6: "The turnover rule then expands the new case's window by
        45 minutes on both sides and rejects any intersection with another
        `RESERVED` reservation's case window for the same tray
        (`ERR_TRAY_RESERVATION_TIME_CONFLICT`); a gap of exactly 45 minutes
        between the expanded windows is allowed."

        Design: Difficulty/resource_temporal_overlap/tray_reservation_buffered_gap_45
        """
        s = fx.setup_buffered_gap_scenario(api)
        ra = fx.reserve_tray(api, s.ca["id"], s.tr["id"], s.ca["version"])
        assert ra["status"] == "RESERVED"
        rb = validate_success(
            api.create_reservation(
                s.cb["id"],
                f.create_reservation_payload(s.tr["id"], s.cb["version"]),
                SCHED,
            ),
            201,
        )
        assert rb["status"] == "RESERVED", (
            "12:45 == 12:00 + 45 minutes: the gap equals the buffer"
        )

    def test_gap_of_44_minutes_conflicts(self, api):
        """PRD §3.6: "rejects any intersection with another `RESERVED`
        reservation's case window for the same tray
        (`ERR_TRAY_RESERVATION_TIME_CONFLICT`); a gap of exactly 45 minutes
        between the expanded windows is allowed."

        Design: Difficulty/resource_temporal_overlap/tray_reservation_buffered_gap_45
        """
        s = fx.setup_buffered_gap_scenario(api)
        fx.reserve_tray(api, s.ca["id"], s.tr["id"], s.ca["version"])
        fx.reserve_tray(api, s.cb["id"], s.tr["id"], s.cb["version"])
        resp = api.create_reservation(
            s.cc["id"],
            f.create_reservation_payload(s.tr["id"], s.cc["version"]),
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_TRAY_RESERVATION_TIME_CONFLICT)
        rows, meta = validate_paginated(
            api.list_tray_reservations(ADMIN, params={"tray_id": s.tr["id"]})
        )
        assert meta["total_count"] == 2
        assert all(r["status"] == "RESERVED" for r in rows)


class TestReserveReleaseRoundtrip:
    """Reserve + its compensating release conserve the sterile pool (two
    tests, one design instance)."""

    def test_roundtrip_conserves_sterile_pool_and_releases_reservation(self, api):
        """PRD §3.6: "Releasing a reservation is the compensating action of
        reserving: the reservation must be `RESERVED` (else
        `ERR_RESERVATION_NOT_ACTIVE`) and moves to `RELEASED`. The tray is
        untouched and stays `STERILE`". PRD §3.6: "Reservations are temporal
        bookings, not status changes: reserving a tray leaves it `STERILE`".

        Design: Difficulty/compensating_invariant/reserve_release_roundtrip_conserves_sterile_pool
        """
        s = fx.setup_sterile_pair_scenario(api)
        params = {"template_id": s.tpl["id"], "status": "STERILE"}
        _, before = validate_paginated(api.list_trays(ADMIN, params=params))
        assert before["total_count"] == 2

        rk = fx.reserve_tray(api, s.ck["id"], s.k1["id"], s.ck["version"])
        released = validate_success(api.release_reservation(rk["id"], SCHED))
        assert released["status"] == "RELEASED"

        _, after = validate_paginated(api.list_trays(ADMIN, params=params))
        assert after["total_count"] == 2, (
            "forward + compensating pair conserves the STERILE pool"
        )

    def test_roundtrip_returns_case_to_scheduled(self, api):
        """PRD §3.6: "the owning case recomputes — when no `RESERVED`
        reservations remain and the case is `TRAYS_RESERVED` or `AT_RISK`, it
        returns to `SCHEDULED`."

        Design: Difficulty/compensating_invariant/reserve_release_roundtrip_conserves_sterile_pool
        """
        s = fx.setup_sterile_pair_scenario(api)
        rk = fx.reserve_tray(api, s.ck["id"], s.k1["id"], s.ck["version"])
        mid = validate_success(api.get_or_case(s.ck["id"], SCHED))
        assert mid["status"] == "TRAYS_RESERVED"
        validate_success(api.release_reservation(rk["id"], SCHED))
        case = validate_success(api.get_or_case(s.ck["id"], SCHED))
        assert case["status"] == "SCHEDULED", "0 RESERVED remain -> reverted"


class TestCaseStartGatedByLoanerReadiness:
    """A reserved case still cannot start while a linked loaner set is not
    READY (two tests, one design instance)."""

    def test_start_blocked_while_loaner_booked(self, api):
        """PRD §3.6: "every loaner set booked for the case must be `READY`
        (else `ERR_LOANER_NOT_READY`)". PRD §3.7: "`due_by` is the case's
        `scheduled_start_at` minus 24 hours when `tray_count` is below 10".

        Design: Difficulty/cross_entity_state_dependency/case_start_gated_by_loaner_readiness
        """
        s = fx.setup_loaner_gate_scenario(api)
        resp = api.start_case(s.cl["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_LOANER_NOT_READY)
        case = validate_success(api.get_or_case(s.cl["id"], SCHED))
        assert case["status"] == "TRAYS_RESERVED"
        assert_instant_equals(s.ln["due_by"], "2026-05-09T09:00:00Z",
                              "3 trays < 10 -> 24h lead off the case start")

    def test_start_succeeds_after_loaner_ready(self, api):
        """PRD §3.7: "arriving at or before the deadline — an arrival exactly
        at `due_by` counts as on time — moves the set to `RECEIVED` with
        `received_late` false". PRD §3.6: "Either path moves the case to
        `IN_PROGRESS`, transitions the reserved trays `STERILE → IN_USE`, and
        flips linked `READY` loaner sets to `IN_USE`."

        Design: Difficulty/cross_entity_state_dependency/case_start_gated_by_loaner_readiness
        """
        s = fx.setup_loaner_gate_scenario(api)
        blocked = api.start_case(s.cl["id"], SCHED)
        validate_error(blocked, ApiErrorId.ERR_LOANER_NOT_READY)

        fx.set_clock(api, "2026-05-05T00:00:00Z")
        h = make_technician_headers(s.tech_a["id"])
        received = validate_success(api.receive_loaner_set(s.ln["id"], h))
        assert received["status"] == "RECEIVED"
        assert received["received_late"] is False
        validate_success(api.mark_loaner_ready(s.ln["id"], h))

        started = validate_success(api.start_case(s.cl["id"], SCHED))
        assert started["status"] == "IN_PROGRESS"
        tray = validate_success(api.get_tray(s.tl["id"], ADMIN))
        assert tray["status"] == "IN_USE"
        loaner = validate_success(api.get_loaner_set(s.ln["id"], ADMIN))
        assert loaner["status"] == "IN_USE"


def test_occ_reservation_stale_version_rejected(api):
    """PRD §2.7: "Creating a tray reservation against a case (`POST
    /spd/or-cases/{id}/reservations`) must carry `expected_or_case_version`
    equal to the case's current `version`. Each successful reservation
    creation mutates the case (status recompute) and increments
    `ORCase.version` by 1, so a second creation carrying a previously observed
    version is deterministically rejected as stale." "a mismatch with the
    parent entity's current `version` is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_reservation_stale_version_rejected
    """
    s = fx.setup_occ_reservation_scenario(api)
    r1 = validate_success(
        api.create_reservation(
            s.co["id"],
            f.create_reservation_payload(s.o1["id"], s.co["version"]),
            SCHED,
        ),
        201,
    )
    assert r1["status"] == "RESERVED"

    stale = api.create_reservation(
        s.co["id"],
        f.create_reservation_payload(s.o2["id"], s.co["version"]),
        SCHED,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    case = validate_success(api.get_or_case(s.co["id"], SCHED))
    assert case["version"] == 2, "the first reservation bumped the case version"
    r2 = validate_success(
        api.create_reservation(
            s.co["id"],
            f.create_reservation_payload(s.o2["id"], case["version"]),
            SCHED,
        ),
        201,
    )
    assert r2["status"] == "RESERVED"


def test_case_and_reservation_terminal_gates(api):
    """PRD §3.6: "Creating one requires the case to be `SCHEDULED`,
    `TRAYS_RESERVED`, or `AT_RISK` (else `ERR_CASE_NOT_RESERVABLE`)" and "the
    reservation must be `RESERVED` (else `ERR_RESERVATION_NOT_ACTIVE`) and
    moves to `RELEASED`."

    Design: Corner/errors/error_case_and_reservation_terminal_gates_trigger
    """
    s = fx.setup_case_terminal_gate_scenario(api)
    e1 = api.create_reservation(
        s.cg["id"],
        f.create_reservation_payload(s.g2["id"], s.cg["version"]),
        SCHED,
    )
    validate_error(e1, ApiErrorId.ERR_CASE_NOT_RESERVABLE)

    r1 = validate_success(api.release_reservation(s.rh["id"], SCHED))
    assert r1["status"] == "RELEASED"
    e2 = api.release_reservation(s.rh["id"], SCHED)
    validate_error(e2, ApiErrorId.ERR_RESERVATION_NOT_ACTIVE)


def test_case_start_without_reservations_or_iuss_rejected(api):
    """PRD §3.6: "the case must be `TRAYS_RESERVED` or `AT_RISK` with at least
    one `RESERVED` reservation (else `ERR_CASE_NOT_STARTABLE`)"; "a case still
    `SCHEDULED` may start only when at least one IUSS exception references it
    (else `ERR_CASE_NOT_STARTABLE`)"; "**Cancelling a case** is permitted from
    `SCHEDULED`, `TRAYS_RESERVED`, or `AT_RISK` (else
    `ERR_CASE_NOT_CANCELLABLE`)"; "**Completing a case** requires
    `IN_PROGRESS` (else `ERR_CASE_NOT_COMPLETABLE`)".

    Design: Corner/state_machines/case_start_without_reservations_or_iuss_rejected
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    cn = fx.create_case(api, case_number="C-N", surgeon="Dr N",
                        scheduled_start_at="2026-05-10T09:00:00Z",
                        scheduled_end_at="2026-05-10T10:00:00Z", priority="ELECTIVE")
    ct = fx.create_case(api, case_number="C-T", surgeon="Dr T",
                        scheduled_start_at="2026-05-10T11:00:00Z",
                        scheduled_end_at="2026-05-10T12:00:00Z", priority="EMERGENCY")
    ut = fx.create_decontaminated_tray(api, tpl["id"], tech["id"], label="UT")
    validate_success(
        api.create_iuss_exception(
            f.create_iuss_payload(ut["id"], ct["id"]),
            make_technician_headers(tech["id"]),
        ),
        201,
    )
    validate_success(api.start_case(ct["id"], SCHED))
    validate_success(api.complete_case(ct["id"], SCHED))

    e1 = api.start_case(cn["id"], SCHED)
    validate_error(e1, ApiErrorId.ERR_CASE_NOT_STARTABLE)
    e2 = api.cancel_case(ct["id"], SCHED)
    validate_error(e2, ApiErrorId.ERR_CASE_NOT_CANCELLABLE)
    e3 = api.complete_case(ct["id"], SCHED)
    validate_error(e3, ApiErrorId.ERR_CASE_NOT_COMPLETABLE)


def test_case_emergency_start_via_iuss_path(api):
    """PRD §3.6: "On the emergency IUSS path, a case still `SCHEDULED` may
    start only when at least one IUSS exception references it (else
    `ERR_CASE_NOT_STARTABLE`)". PRD §3.6: "The tray must be `DECONTAMINATED`
    or `ASSEMBLED` (else `ERR_IUSS_TRAY_NOT_ELIGIBLE`) and moves to `IN_USE`".

    Design: Corner/state_machines/case_emergency_start_via_iuss_path
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    ud = fx.create_decontaminated_tray(api, tpl["id"], tech["id"], label="UD")
    ce = fx.create_case(api, case_number="C-E", surgeon="Dr E",
                        scheduled_start_at="2026-05-02T09:00:00Z",
                        scheduled_end_at="2026-05-02T10:00:00Z", priority="EMERGENCY")
    validate_success(
        api.create_iuss_exception(
            f.create_iuss_payload(ud["id"], ce["id"]),
            make_technician_headers(tech["id"]),
        ),
        201,
    )
    started = validate_success(api.start_case(ce["id"], SCHED))
    assert started["status"] == "IN_PROGRESS"
    tray = validate_success(api.get_tray(ud["id"], ADMIN))
    assert tray["status"] == "IN_USE", "the IUSS tray was consumed at logging time"


def test_reserved_tray_expired_blocks_case_start_then_sweeps(api):
    """PRD §2.4: "a tray whose `sterility_expires_at` has passed but which has
    not itself been read or touched is still seen in its stale `STERILE` state
    and trips `ERR_RESERVED_TRAY_EXPIRED` at case start; a subsequent direct
    read of that tray then applies the sweep." PRD §3.6: "The same
    release-and-recompute applies when the lazy sterility sweep retires a
    `STERILE` tray: the tray drops to `AWAITING_DECONTAMINATION` with
    `sterility_expires_at` cleared, and each of its `RESERVED` reservations
    moves to `RELEASED` under the same case recompute."

    Design: Corner/state_machines/reserved_tray_expired_blocks_case_start_then_sweeps
    """
    s = fx.setup_expired_reservation_scenario(api)
    resp = api.start_case(s.cx["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_RESERVED_TRAY_EXPIRED)

    tray = validate_success(api.get_tray(s.te["id"], ADMIN))
    assert tray["status"] == "AWAITING_DECONTAMINATION", (
        "the direct read applies the due sterility sweep"
    )
    reservation = validate_success(api.get_tray_reservation(s.rx["id"], ADMIN))
    assert reservation["status"] == "RELEASED"
    case = validate_success(api.get_or_case(s.cx["id"], SCHED))
    assert case["status"] == "SCHEDULED", "0 RESERVED remain -> reverted"


def test_loaner_due_by_tier_boundary(api):
    """PRD §3.7: "The intake deadline is tiered off the linked case: `due_by`
    is the case's `scheduled_start_at` minus 24 hours when `tray_count` is
    below 10, and minus 48 hours when `tray_count` is 10 or more."

    Design: Corner/calculations/loaner_due_by_tier_boundary
    """
    clt = fx.create_case(api, case_number="C-LT", surgeon="Dr L",
                         scheduled_start_at="2026-05-20T12:00:00Z",
                         scheduled_end_at="2026-05-20T14:00:00Z", priority="ELECTIVE")
    d9 = validate_success(
        api.create_loaner_set(f.create_loaner_set_payload(clt["id"], tray_count=9), SCHED),
        201,
    )
    d10 = validate_success(
        api.create_loaner_set(f.create_loaner_set_payload(clt["id"], tray_count=10), SCHED),
        201,
    )
    assert_instant_equals(d9["due_by"], "2026-05-19T12:00:00Z",
                          "9 < 10 -> 24h standard lead")
    assert_instant_equals(d10["due_by"], "2026-05-18T12:00:00Z",
                          "10 >= 10 -> 48h bulk lead")


def test_loaner_receive_exactly_at_due_is_on_time(api):
    """PRD §3.7: "The lateness verdict branches on `due_by`: arriving at or
    before the deadline — an arrival exactly at `due_by` counts as on time —
    moves the set to `RECEIVED` with `received_late` false; arriving strictly
    after moves it to `LATE_RECEIVED` with `received_late` true."

    Design: Corner/calculations/loaner_receive_exactly_at_due_is_on_time
    """
    tech = fx.create_technician(api)
    clr = fx.create_case(api, case_number="C-LR", surgeon="Dr L",
                         scheduled_start_at="2026-05-10T09:00:00Z",
                         scheduled_end_at="2026-05-10T10:00:00Z", priority="ELECTIVE")
    la = fx.create_loaner(api, clr["id"], tray_count=2)
    lb = fx.create_loaner(api, clr["id"], tray_count=2)
    h = make_technician_headers(tech["id"])

    fx.set_clock(api, "2026-05-09T09:00:00Z")
    on_time = validate_success(api.receive_loaner_set(la["id"], h))
    assert on_time["status"] == "RECEIVED"
    assert on_time["received_late"] is False, "equality with due_by is on time"

    fx.set_clock(api, "2026-05-09T09:01:00Z")
    late = validate_success(api.receive_loaner_set(lb["id"], h))
    assert late["status"] == "LATE_RECEIVED"
    assert late["received_late"] is True


def test_loaner_state_gates_and_double_receive(api):
    """PRD §3.7: "the set must be `RECEIVED` or `LATE_RECEIVED` (else
    `ERR_LOANER_NOT_RECEIVED`) and moves to `READY`" and "A `SpdTechnician`
    records intake against a `BOOKED` set (else `ERR_LOANER_NOT_BOOKED`)."

    Design: Corner/state_machines/loaner_state_gates_and_double_receive
    """
    tech = fx.create_technician(api)
    cln = fx.create_case(api, case_number="C-LN", surgeon="Dr L",
                         scheduled_start_at="2026-05-10T09:00:00Z",
                         scheduled_end_at="2026-05-10T10:00:00Z", priority="ELECTIVE")
    ln = fx.create_loaner(api, cln["id"], tray_count=2)
    h = make_technician_headers(tech["id"])

    e1 = api.mark_loaner_ready(ln["id"], h)
    validate_error(e1, ApiErrorId.ERR_LOANER_NOT_RECEIVED)

    received = validate_success(api.receive_loaner_set(ln["id"], h))
    assert received["status"] == "RECEIVED", (
        "clock default 2026-05-01 is well before due_by 2026-05-09T09:00:00Z"
    )

    e2 = api.receive_loaner_set(ln["id"], h)
    validate_error(e2, ApiErrorId.ERR_LOANER_NOT_BOOKED)

    ready = validate_success(api.mark_loaner_ready(ln["id"], h))
    assert ready["status"] == "READY"
