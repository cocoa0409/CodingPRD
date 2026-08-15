"""Training sessions and the throughput guarantee: trainer scheduling
half-open intervals, training-window rejection, operator/technician pass
thresholds, logical clock no-show (PRD §3.8, §3.6, §2.10)."""
from test_helpers import (
    ApiErrorId,
    assert_training_session,
    create_org,
    create_project,
    create_site,
    create_training_session_payload,
    create_user,
    get_project,
    make_finance_admin_headers,
    make_project_engineer_headers,
    make_trainer_headers,
    setup_full_project,
    setup_project_in_training,
    validate_error,
    validate_success,
)


def test_trainer_double_booking_half_open_adjacency(api):
    """PRD §3.8: "Overlap is judged on half-open intervals — the start instant
    counts, the end instant does not — so back-to-back sessions where one
    begins exactly as the other ends do not conflict." Both scheduling-rule
    violations are rejected with `ERR_TRAINER_SCHEDULE_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/trainer_double_booking_half_open_adjacency
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-TO1"})
    trn = ctx["users"]["TRAINER"]
    trainer = make_trainer_headers(trn["id"])

    s1 = validate_success(
        api.create_training_session(
            ctx["project"]["id"],
            create_training_session_payload(
                "OPERATOR",
                "2026-08-10T08:00:00Z",
                "2026-08-10T16:00:00Z",
                trn["id"],
                attendee_count=6,
            ),
            trainer,
        ),
        201,
    )
    assert_training_session(s1)

    # Adjacent: starts exactly when s1 ends -> allowed under half-open [start, end).
    s2 = validate_success(
        api.create_training_session(
            ctx["project"]["id"],
            create_training_session_payload(
                "TECHNICIAN",
                "2026-08-10T16:00:00Z",
                "2026-08-10T20:00:00Z",
                trn["id"],
                attendee_count=4,
            ),
            trainer,
        ),
        201,
    )
    assert s2["session_status"] == "SCHEDULED"

    # Overlap by one second: starts 15:59:59 -> rejected.
    resp = api.create_training_session(
        ctx["project"]["id"],
        create_training_session_payload(
            "TECHNICIAN",
            "2026-08-10T15:59:59Z",
            "2026-08-10T18:00:00Z",
            trn["id"],
            attendee_count=4,
        ),
        trainer,
    )
    validate_error(resp, ApiErrorId.ERR_TRAINER_SCHEDULE_CONFLICT)


def test_training_start_outside_window_rejected(api):
    """PRD §3.8: "Starting a session is legal only while the project stands
    in `TRAINING` and only inside the scheduled window — the logical clock
    (§2.10) must read at or after `scheduled_start_utc` and at or before
    `scheduled_end_utc`, both ends inclusive; an attempt outside the window
    is rejected with `ERR_OUTSIDE_SESSION_WINDOW`."

    Design: Corner/validations/training_start_outside_window_rejected
    """
    # Project must stand in TRAINING for the session-window check to be
    # reachable (per the §2.6 ladder, state legality precedes window
    # compliance).
    ctx = setup_project_in_training(project_overrides={"project_code": "P-WIN"})
    proj = ctx["project"]
    trn = ctx["users"]["TRAINER"]

    trainer = make_trainer_headers(trn["id"])
    sess = validate_success(
        api.create_training_session(
            proj["id"],
            create_training_session_payload(
                "OPERATOR",
                "2026-08-10T08:00:00Z",
                "2026-08-10T16:00:00Z",
                trn["id"],
                attendee_count=5,
            ),
            trainer,
        ),
        201,
    )

    # Clock before window start.
    validate_success(
        api.set_clock("2026-08-09T09:00:00Z", make_finance_admin_headers())
    )
    resp = api.start_training_session(sess["id"], trainer)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_SESSION_WINDOW)


def test_training_advance_requires_operator_and_technician_completion(api):
    """PRD §3.6: "`TRAINING` → `GUARANTEE`, by a `ProjectEngineer`: every
    `OPERATOR` training session of the project stands `COMPLETED` with a
    `completion_score_pct` of at least 80, every `TECHNICIAN` session stands
    `COMPLETED` with a `completion_score_pct` of at least 85, a maintenance
    plan in `ACTIVE` status exists, and the throughput guarantee stands
    `MEASURING`." PRD §3.8: "for an `OPERATOR` audience, sixty percent of the
    practical score plus forty percent of the written score; for a
    `TECHNICIAN` audience, half of each."

    Design: Difficulty/cross_entity_state_dependency/training_advance_requires_operator_and_technician_completion
    """
    ctx = setup_project_in_training(project_overrides={"project_code": "P-XD2"})
    proj = ctx["project"]
    eng = ctx["users"]["PROJECT_ENGINEER"]
    svc = ctx["users"]["SERVICE_MANAGER"]
    trn = ctx["users"]["TRAINER"]

    from test_helpers import (
        create_and_activate_maintenance_plan,
        run_training_session,
    )

    create_and_activate_maintenance_plan(proj, svc["id"])

    # OPERATOR: 0.6*90 + 0.4*75 = 84.0 -> passes (>= 80).
    op = run_training_session(
        proj,
        trn["id"],
        "OPERATOR",
        "2026-08-10T08:00:00Z",
        "2026-08-10T16:00:00Z",
        "2026-08-10T09:00:00Z",
        90.0,
        75.0,
        attendee_count=6,
    )
    assert op["completion_score_pct"] == 84.0

    # TECHNICIAN: 0.5*90 + 0.5*75 = 82.5 -> below 85 threshold.
    tech = run_training_session(
        proj,
        trn["id"],
        "TECHNICIAN",
        "2026-08-11T08:00:00Z",
        "2026-08-11T16:00:00Z",
        "2026-08-11T09:00:00Z",
        90.0,
        75.0,
        attendee_count=4,
    )
    assert tech["completion_score_pct"] == 82.5

    eng_hdrs = make_project_engineer_headers(eng["id"])
    current = get_project(proj["id"], eng_hdrs)
    resp = api.advance_cell_project(
        proj["id"], {"expected_project_version": current["version"]}, eng_hdrs
    )
    validate_error(resp, ApiErrorId.ERR_GATE_PRECONDITION_UNMET)

    after = get_project(proj["id"], eng_hdrs)
    assert after["status"] == "TRAINING"


def test_logical_clock_default_and_no_show(api):
    """PRD §2.10: "Before it has ever been set, the logical clock reads
    exactly 2026-08-01T00:00:00Z." PRD §2.10: "Setting the clock triggers
    exactly one time-driven effect: any training session still `SCHEDULED`
    whose scheduled window has fully elapsed — that is, the clock has moved
    past its `scheduled_end_utc` — transitions to `NO_SHOW`."

    Design: Corner/cross_cutting_layers/logical_clock_default_and_no_show
    """
    org = create_org(retention_rate_bps=1000)
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    trn = create_user(org["id"], "Trainer One", "TRAINER")
    site = create_site(org["id"], eng["id"], site_name="S25")
    proj = create_project(
        site["id"],
        eng["id"],
        project_code="P-NOSHOW",
        contracted_cycle_time_s=10.0,
        contract_value_cents=100000,
        guaranteed_oee_pct=80.0,
    )

    trainer = make_trainer_headers(trn["id"])
    sess = validate_success(
        api.create_training_session(
            proj["id"],
            create_training_session_payload(
                "OPERATOR",
                "2026-08-05T08:00:00Z",
                "2026-08-05T16:00:00Z",
                trn["id"],
                attendee_count=5,
            ),
            trainer,
        ),
        201,
    )
    # Default clock (2026-08-01) is before the window, so the session remains
    # SCHEDULED at creation.
    assert sess["session_status"] == "SCHEDULED"

    # Advance the clock past scheduled_end_utc; session becomes NO_SHOW.
    validate_success(
        api.set_clock("2026-08-06T00:00:00Z", make_finance_admin_headers())
    )
    after = validate_success(api.get_training_session(sess["id"], trainer))
    assert after["session_status"] == "NO_SHOW"
