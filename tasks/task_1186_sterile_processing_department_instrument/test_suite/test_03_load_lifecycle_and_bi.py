"""Sterilization load lifecycle: state gates, capacity and planned-start
boundaries, biological-indicator incubation, and release safety gates.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    make_supervisor_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]
AUDIT = TEST_USERS["quality_auditor_headers"]


def test_load_wrong_state_actions_rejected(api):
    """PRD §3.4: "Completing the cycle requires the load `RUNNING` (else
    `ERR_LOAD_NOT_RUNNING`)". PRD §3.5: "The load must be `COMPLETED` (else
    `ERR_LOAD_NOT_RELEASABLE`)".

    Design: Corner/state_machines/load_wrong_state_actions_rejected
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    sup = fx.create_technician(api, name="Sup S", certification_level=3)
    sg = fx.create_sterilizer(api)
    load = fx.create_load(api, sg["id"], tech["id"])

    e1 = api.complete_load(load["id"], make_technician_headers(tech["id"]))
    validate_error(e1, ApiErrorId.ERR_LOAD_NOT_RUNNING)
    e2 = api.release_load(load["id"], make_supervisor_headers(sup["id"]))
    validate_error(e2, ApiErrorId.ERR_LOAD_NOT_RELEASABLE)

    after = validate_success(api.get_sterilization_load(load["id"], ADMIN))
    assert after["status"] == "LOADING"


def test_load_start_empty_and_capacity_boundary(api):
    """PRD §3.4: "it must hold at least one tray (else `ERR_LOAD_EMPTY`)" and
    "the load's `tray_count` must still be below the sterilizer's
    `chamber_capacity` — adding when the count already equals capacity is
    rejected with `ERR_LOAD_CAPACITY_EXCEEDED`."

    Design: Corner/state_machines/load_start_empty_and_capacity_boundary
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    sc = fx.create_sterilizer(api, name="SC", chamber_capacity=1)
    c1 = fx.create_assembled_tray(api, tpl["id"], tech["id"], label="C1")
    c2 = fx.create_assembled_tray(api, tpl["id"], tech["id"], label="C2")
    load = fx.create_load(api, sc["id"], tech["id"])
    h = make_technician_headers(tech["id"])

    e0 = api.start_load(load["id"], h)
    validate_error(e0, ApiErrorId.ERR_LOAD_EMPTY)

    added = validate_success(api.add_tray_to_load(load["id"], {"tray_id": c1["id"]}, h))
    assert added["tray_count"] == 1, "tray_count == chamber_capacity is allowed"

    e1 = api.add_tray_to_load(load["id"], {"tray_id": c2["id"]}, h)
    validate_error(e1, ApiErrorId.ERR_LOAD_CAPACITY_EXCEEDED)

    started = validate_success(api.start_load(load["id"], h))
    assert started["status"] == "RUNNING"


def test_load_start_before_planned_start_rejected(api):
    """PRD §3.4: "the logical clock must have reached `planned_start_at` —
    starting early is rejected with `ERR_LOAD_PLANNED_START_NOT_REACHED`."

    Design: Corner/state_machines/load_start_before_planned_start_rejected
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    sg = fx.create_sterilizer(api)
    tray = fx.create_assembled_tray(api, tpl["id"], tech["id"], label="P1")
    load = fx.create_load(api, sg["id"], tech["id"],
                          planned_start_at="2026-05-02T00:00:00Z")
    fx.add_tray_to_load(api, load["id"], tray["id"], tech["id"])
    h = make_technician_headers(tech["id"])

    e1 = api.start_load(load["id"], h)
    validate_error(e1, ApiErrorId.ERR_LOAD_PLANNED_START_NOT_REACHED)

    fx.set_clock(api, "2026-05-02T00:00:00Z")
    started = validate_success(api.start_load(load["id"], h))
    assert started["status"] == "RUNNING", (
        "the >= boundary allows starting exactly at planned_start_at"
    )


def test_load_recall_from_completed_rejected(api):
    """PRD §3.5: "A `RELEASED` load — any other state draws
    `ERR_LOAD_NOT_RECALLABLE` — is recalled either manually by a
    `SpdSupervisor` or `QualityAuditor` supplying a free-text `reason`".

    Design: Corner/state_machines/load_recall_from_completed_rejected
    """
    s = fx.setup_completed_load_scenario(api, label="RC")
    resp = api.recall_load(
        s.ld["id"], {"reason": "steam quality failure suspected"},
        make_supervisor_headers(s.ts["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LOAD_NOT_RECALLABLE)
    load = validate_success(api.get_sterilization_load(s.ld["id"], ADMIN))
    assert load["status"] == "COMPLETED"
    tray = validate_success(api.get_tray(s.tray["id"], ADMIN))
    assert tray["status"] == "IN_LOAD"


def test_bi_record_before_due_and_at_due_boundary(api):
    """PRD §3.5: "Recording is allowed only while the BI is `INCUBATING` — a
    second recording draws `ERR_BI_ALREADY_RECORDED` — and not before
    `due_at`: an early attempt is rejected with `ERR_BI_STILL_INCUBATING`,
    while arriving exactly at `due_at` is accepted." PRD §3.4: "`due_at` set
    to `completed_at` plus 3 hours."

    Design: Corner/state_machines/bi_record_before_due_and_at_due_boundary
    """
    s = fx.setup_completed_load_scenario(api, label="D1")
    bi = fx.first_bi_of_load(api, s.ld["id"])
    assert_instant_equals(bi["due_at"], "2026-05-01T03:00:00Z",
                          "due_at = completed_at + 3h")

    e1 = api.record_bi_result(bi["id"], {"result": "NEGATIVE"}, AUDIT)
    validate_error(e1, ApiErrorId.ERR_BI_STILL_INCUBATING)

    fx.set_clock(api, "2026-05-01T03:00:00Z")
    recorded = validate_success(api.record_bi_result(bi["id"], {"result": "NEGATIVE"}, AUDIT))
    assert recorded["status"] == "RESULT_RECORDED"
    assert recorded["result"] == "NEGATIVE"


def test_bi_double_record_rejected(api):
    """PRD §3.5: "Recording is allowed only while the BI is `INCUBATING` — a
    second recording draws `ERR_BI_ALREADY_RECORDED`".

    Design: Corner/state_machines/bi_double_record_rejected
    """
    s = fx.setup_completed_load_scenario(api, label="D2")
    fx.set_clock(api, "2026-05-01T03:00:00Z")
    bi = fx.first_bi_of_load(api, s.ld["id"])
    fx.record_bi(api, bi["id"], "NEGATIVE")

    resp = api.record_bi_result(bi["id"], {"result": "POSITIVE"}, AUDIT)
    validate_error(resp, ApiErrorId.ERR_BI_ALREADY_RECORDED)

    fetched = validate_success(api.get_biological_indicator(bi["id"], ADMIN))
    assert fetched["result"] == "NEGATIVE", "the first recorded result stands"


def test_manual_bi_requires_completed_or_released_load(api):
    """PRD §3.5: "an auditor may attach an extra follow-up (spore-strip) BI to
    a load while the load is `COMPLETED` or `RELEASED` — against a load in any
    other state the attempt is rejected with `ERR_BI_LOAD_STATE_INVALID`."

    Design: Corner/errors/error_bi_load_state_invalid_trigger
    """
    tech = fx.create_technician(api)
    sg = fx.create_sterilizer(api)
    load = fx.create_load(api, sg["id"], tech["id"])
    resp = api.add_biological_indicator(load["id"], {"lot_number": "LOT-X"}, AUDIT)
    validate_error(resp, ApiErrorId.ERR_BI_LOAD_STATE_INVALID)


def test_load_release_safety_gates(api):
    """PRD §3.5: "the caller's `X-User-ID` must differ from the load's
    recorded `operator_id` — the technician who ran the cycle may never
    release it, else `ERR_RELEASE_OPERATOR_SEGREGATION` (403), and this check
    is evaluated before the biological check per §2.6; and the load's
    biological evidence must be clean: at least one BI exists for the load,
    and *every* BI of the load is `RESULT_RECORDED` with result `NEGATIVE`,
    else `ERR_BI_NOT_PASSED`."

    Design: Corner/state_machines/load_release_safety_gates
    """
    s = fx.setup_completed_load_scenario(api, label="E1")

    # Gate 1 in isolation: the caller is not the operator, but the BI is
    # still incubating.
    e1 = api.release_load(s.ld["id"], make_supervisor_headers(s.ts["id"]))
    validate_error(e1, ApiErrorId.ERR_BI_NOT_PASSED)

    fx.set_clock(api, "2026-05-01T03:00:00Z")
    bi = fx.first_bi_of_load(api, s.ld["id"])
    fx.record_bi(api, bi["id"], "NEGATIVE")

    # Gate 2 in isolation: the BI is NEGATIVE, but the caller is the operator.
    e2 = api.release_load(s.ld["id"], make_supervisor_headers(s.ta["id"]))
    validate_error(e2, ApiErrorId.ERR_RELEASE_OPERATOR_SEGREGATION)

    released = validate_success(
        api.release_load(s.ld["id"], make_supervisor_headers(s.ts["id"]))
    )
    assert released["status"] == "RELEASED"


def test_abort_compensates_load_membership(api):
    """PRD §3.4: "Aborting is available only while `LOADING` (else
    `ERR_LOAD_NOT_LOADING`): the load moves to `ABORTED` and its member trays
    return to `ASSEMBLED` the same way." PRD §3.3: "a tray that was `IN_LOAD`
    additionally leaves its load (its `current_load_id` clears and the load's
    `tray_count` decrements by 1)".

    Design: Corner/state_machines/abort_compensates_load_membership
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    sg = fx.create_sterilizer(api)
    b1 = fx.create_assembled_tray(api, tpl["id"], tech["id"], label="B1")
    b2 = fx.create_assembled_tray(api, tpl["id"], tech["id"], label="B2")
    load = fx.create_load(api, sg["id"], tech["id"])
    fx.add_tray_to_load(api, load["id"], b1["id"], tech["id"])
    added = fx.add_tray_to_load(api, load["id"], b2["id"], tech["id"])
    assert added["tray_count"] == 2

    aborted = validate_success(
        api.abort_load(load["id"], make_technician_headers(tech["id"]))
    )
    assert aborted["status"] == "ABORTED"
    assert aborted["tray_count"] == 0, (
        "every member tray left the load, so the live count returns to 0"
    )
    for t in (b1, b2):
        after = validate_success(api.get_tray(t["id"], ADMIN))
        assert after["status"] == "ASSEMBLED"
        assert after["current_load_id"] is None


def test_derived_fields_reconcile_across_load_lifecycle(api):
    """PRD §3.4: "The load is created `LOADING` with `tray_count` 0" and "Each
    addition moves the tray `ASSEMBLED → IN_LOAD`, sets its `current_load_id`
    to the load, and increments `tray_count` by 1." PRD §3.5: "The load's
    `total_chargeback_cents` — null until this moment — is computed as the
    department chargeback".

    Design: Corner/endpoints/derived_fields_reconcile_across_load_lifecycle
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    fx.create_technician(api, name="Sup S", certification_level=3)
    sg = fx.create_sterilizer(api)
    d1 = fx.create_assembled_tray(api, tpl["id"], tech["id"], label="D1")
    d2 = fx.create_assembled_tray(api, tpl["id"], tech["id"], label="D2")

    created = fx.create_load(api, sg["id"], tech["id"])
    assert created["tray_count"] == 0
    assert created["total_chargeback_cents"] is None, (
        "chargeback is null until the release transition computes it"
    )

    fx.add_tray_to_load(api, created["id"], d1["id"], tech["id"])
    two = fx.add_tray_to_load(api, created["id"], d2["id"], tech["id"])
    assert two["tray_count"] == 2

    aborted = validate_success(
        api.abort_load(created["id"], make_technician_headers(tech["id"]))
    )
    assert aborted["tray_count"] == 0


def test_load_start_certification_gates(api):
    """PRD §3.4: "the tray must be `ASSEMBLED` (else
    `ERR_TRAY_NOT_ASSEMBLED`)"; "The sterilizer's `method` must appear in the
    technician's `certified_methods` (else `ERR_CERTIFICATION_METHOD_MISMATCH`),
    and the technician's `certification_level` must be at least the
    sterilizer's `required_certification_level` (else
    `ERR_CERTIFICATION_LEVEL_INSUFFICIENT`)."

    Design: Corner/errors/error_load_start_certification_gates_trigger
    """
    tpl = fx.create_template(api)
    tg1 = fx.create_technician(api, name="Tech G1", certification_level=3,
                               certified_methods=["STEAM_GRAVITY"])
    tlo = fx.create_technician(api, name="Tech LO", certification_level=1,
                               certified_methods=["STEAM_GRAVITY"])
    sp = fx.create_sterilizer(api, name="SP", method="STEAM_PREVAC",
                              cycle_minutes=45, required_certification_level=1)
    sx = fx.create_sterilizer(api, name="SX", method="STEAM_GRAVITY",
                              required_certification_level=3)
    ta = fx.create_assembled_tray(api, tpl["id"], tg1["id"], label="TA")
    tf = fx.create_tray(api, tpl["id"], tg1["id"], label="TF")
    lp = fx.create_load(api, sp["id"], tg1["id"])
    fx.add_tray_to_load(api, lp["id"], ta["id"], tg1["id"])
    lx = fx.create_load(api, sx["id"], tg1["id"])

    e1 = api.add_tray_to_load(
        lx["id"], {"tray_id": tf["id"]}, make_technician_headers(tg1["id"])
    )
    validate_error(e1, ApiErrorId.ERR_TRAY_NOT_ASSEMBLED)

    e2 = api.start_load(lp["id"], make_technician_headers(tg1["id"]))
    validate_error(e2, ApiErrorId.ERR_CERTIFICATION_METHOD_MISMATCH)

    e3 = api.start_load(lx["id"], make_technician_headers(tlo["id"]))
    validate_error(e3, ApiErrorId.ERR_CERTIFICATION_LEVEL_INSUFFICIENT)


class TestLoadStartRequiresSterilizerIdle:
    """The load's start gate reads the sterilizer's aggregate state (two
    tests, one design instance)."""

    def test_start_rejected_while_sterilizer_running(self, api):
        """PRD §3.4: "the sterilizer must be `IDLE` (else
        `ERR_STERILIZER_NOT_IDLE`)" and "it reads `RUNNING` whenever one of
        its loads is running."

        Design: Difficulty/cross_entity_state_dependency/load_start_requires_sterilizer_idle
        """
        s = fx.setup_sterilizer_idle_scenario(api)
        resp = api.start_load(s.l2["id"], make_technician_headers(s.tech_a["id"]))
        validate_error(resp, ApiErrorId.ERR_STERILIZER_NOT_IDLE)
        load = validate_success(api.get_sterilization_load(s.l2["id"], ADMIN))
        assert load["status"] == "LOADING", "the rejection leaves L2 untouched"

    def test_start_succeeds_after_sterilizer_freed(self, api):
        """PRD §3.4: "Completing the cycle requires the load `RUNNING` (else
        `ERR_LOAD_NOT_RUNNING`) and moves it to `COMPLETED`: `completed_at` is
        stamped, the sterilizer returns to `IDLE`" and "the sterilizer must be
        `IDLE` (else `ERR_STERILIZER_NOT_IDLE`)".

        Design: Difficulty/cross_entity_state_dependency/load_start_requires_sterilizer_idle
        """
        s = fx.setup_sterilizer_idle_scenario(api)
        blocked = api.start_load(s.l2["id"], make_technician_headers(s.tech_a["id"]))
        validate_error(blocked, ApiErrorId.ERR_STERILIZER_NOT_IDLE)
        fx.complete_load(api, s.l1["id"], s.tech_a["id"])
        started = validate_success(
            api.start_load(s.l2["id"], make_technician_headers(s.tech_a["id"]))
        )
        assert started["status"] == "RUNNING", (
            "the gate was the sterilizer's state, not L2's own data"
        )


class TestSterilizerWindowHalfOpenAdjacency:
    """Half-open planned-window semantics on the sterilizer resource (two
    tests, one design instance)."""

    def test_adjacent_window_allowed(self, api):
        """PRD §3.4: "the new load occupies the half-open window from
        `planned_start_at` up to (but not including) `planned_start_at` plus
        `cycle_minutes`, and any intersection with another `LOADING` or
        `RUNNING` load's window on the same sterilizer is rejected with
        `ERR_STERILIZER_WINDOW_CONFLICT` — adjacency, where one window ends
        exactly as the other begins, is allowed."

        Design: Difficulty/resource_temporal_overlap/sterilizer_window_half_open_adjacency
        """
        s = fx.setup_sterilizer_window_scenario(api)
        h = make_technician_headers(s.tech_a["id"])
        a = validate_success(api.create_sterilization_load(
            f.create_sterilization_load_payload(s.sg["id"],
                                                planned_start_at="2026-05-01T10:00:00Z"),
            h), 201)
        assert a["status"] == "LOADING"
        b = validate_success(api.create_sterilization_load(
            f.create_sterilization_load_payload(s.sg["id"],
                                                planned_start_at="2026-05-01T11:00:00Z"),
            h), 201)
        assert b["status"] == "LOADING", "11:00 == 10:00+60min is adjacency"

    def test_intruding_window_rejected(self, api):
        """PRD §3.4: "any intersection with another `LOADING` or `RUNNING`
        load's window on the same sterilizer is rejected with
        `ERR_STERILIZER_WINDOW_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/sterilizer_window_half_open_adjacency
        """
        s = fx.setup_sterilizer_window_scenario(api)
        h = make_technician_headers(s.tech_a["id"])
        fx.create_load(api, s.sg["id"], s.tech_a["id"],
                       planned_start_at="2026-05-01T10:00:00Z")
        fx.create_load(api, s.sg["id"], s.tech_a["id"],
                       planned_start_at="2026-05-01T11:00:00Z")
        resp = api.create_sterilization_load(
            f.create_sterilization_load_payload(s.sg["id"],
                                                planned_start_at="2026-05-01T10:30:00Z"),
            h,
        )
        validate_error(resp, ApiErrorId.ERR_STERILIZER_WINDOW_CONFLICT)
        rows, meta = validate_paginated(
            api.list_sterilization_loads(ADMIN, params={"sterilizer_id": s.sg["id"]})
        )
        assert meta["total_count"] == 2, f"only the two legal loads exist: {rows}"
