"""Delivering a session: the timed-unit ladder, pricing, supervision and no-shows."""

from test_helpers import (
    ApiErrorId,
    assert_minutes,
    assert_money,
    check_in,
    complete_session,
    coverage_version,
    create_claim_payload,
    log_home_session,
    read_authorization,
    read_plan,
    schedule_session,
    set_clock,
    setup_active_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_checked_in_slots(scn):
    """Two 30-minute slots in Room A far enough apart that no buffer or cap binds."""
    first = schedule_session(
        scn,
        therapist_id=scn["cvt1"],
        room_id=scn["room_a"],
        scheduled_start_at="2026-06-10T09:00:00Z",
        scheduled_end_at="2026-06-10T09:30:00Z",
    )
    second = schedule_session(
        scn,
        therapist_id=scn["cvt1"],
        room_id=scn["room_a"],
        scheduled_start_at="2026-06-10T10:00:00Z",
        scheduled_end_at="2026-06-10T10:30:00Z",
    )
    check_in(scn, first["id"])
    check_in(scn, second["id"])
    return first, second


def test_twenty_two_delivered_minutes_bills_a_single_timed_unit(api):
    """PRD §3.5: "A `TIMED_THERAPEUTIC_ACTIVITY` session is mapped through a stepped
    table of delivered `timed_minutes`: 7 minutes or fewer bills 0 units; 8 through 22
    minutes bills 1 unit; 23 through 37 bills 2; 38 through 52 bills 3; 53 through 67
    bills 4; 68 through 82 bills 5; and anything beyond 82 minutes bills the
    per-session cap of 6 units."
    PRD §3.5: "`charge_amount` is then `billable_units` multiplied by the clinic rate
    for the code, rounded half-up to two decimal places: 42.00 dollars per timed
    therapeutic-activity unit, 155.00 dollars per flat orthoptic-training unit, and
    210.00 dollars per evaluation-encounter unit, with any other code priced at 0.00."
    PRD §3.5: "the independent billing axis moves off `PENDING` — to `BILLABLE` when
    `billable_units` is at least 1, and to `NON_BILLABLE` when it is 0."

    Design: Difficulty/boundary_precision_check/timed_unit_step_boundary_22_versus_23_minutes
    """
    scn = setup_active_plan()
    first, _second = _two_checked_in_slots(scn)

    data = validate_success(
        api.complete_session(
            first["id"],
            {"performed_at": "2026-06-10T09:25:00Z", "timed_minutes": 22},
            scn["hdr_cvt1"],
        ),
        200,
    )

    assert data["billable_units"] == 1
    assert_money(data["charge_amount"], 42.00, "charge_amount")
    assert data["billing_status"] == "BILLABLE"
    assert data["schedule_status"] == "COMPLETED"


def test_twenty_three_delivered_minutes_crosses_into_two_timed_units(api):
    """PRD §3.5: "The step edges matter — 22 minutes bills 1 unit and 23 minutes bills
    2 — and so does the fork, since 45 delivered minutes bills 1 unit under the flat
    code and 3 units under the timed code."
    PRD §3.5: "On the plan, `cumulative_therapy_minutes` rises by the session's
    `weighted_minutes`, which for an in-office session is simply its `timed_minutes`."

    Design: Difficulty/boundary_precision_check/timed_unit_step_boundary_22_versus_23_minutes
    """
    scn = setup_active_plan()
    first, second = _two_checked_in_slots(scn)
    complete_session(scn, first["id"], "2026-06-10T09:25:00Z", 22)

    data = validate_success(
        api.complete_session(
            second["id"],
            {"performed_at": "2026-06-10T10:25:00Z", "timed_minutes": 23},
            scn["hdr_cvt1"],
        ),
        200,
    )

    assert data["billable_units"] == 2
    assert_money(data["charge_amount"], 84.00, "charge_amount")
    assert data["billing_status"] == "BILLABLE"
    assert_minutes(
        read_plan(scn["plan"])["cumulative_therapy_minutes"], 45.0, "cumulative_therapy_minutes"
    )


def test_seven_delivered_minutes_completes_as_a_non_billable_zero_unit_session(api):
    """PRD §3.5: "That zero-unit landing is a real and reachable outcome: an in-office
    session delivering 7 minutes or fewer completes normally, sits at `NON_BILLABLE`,
    and any later attempt to bill it is refused with `ERR_SESSION_NOT_BILLABLE`."
    PRD §3.5: "A `TIMED_THERAPEUTIC_ACTIVITY` session is mapped through a stepped
    table of delivered `timed_minutes`: 7 minutes or fewer bills 0 units; 8 through 22
    minutes bills 1 unit; 23 through 37 bills 2; 38 through 52 bills 3; 53 through 67
    bills 4; 68 through 82 bills 5; and anything beyond 82 minutes bills the
    per-session cap of 6 units."

    Design: Difficulty/boundary_precision_check/zero_unit_session_is_not_billable_rejects_claim
    """
    scn = setup_active_plan()
    session = schedule_session(
        scn,
        scheduled_start_at="2026-06-10T09:00:00Z",
        scheduled_end_at="2026-06-10T09:30:00Z",
    )
    check_in(scn, session["id"])

    data = validate_success(
        api.complete_session(
            session["id"],
            {"performed_at": "2026-06-10T09:07:00Z", "timed_minutes": 7},
            scn["hdr_cvt1"],
        ),
        200,
    )

    assert data["billable_units"] == 0
    assert_money(data["charge_amount"], 0.00, "charge_amount")
    assert data["billing_status"] == "NON_BILLABLE"
    assert data["schedule_status"] == "COMPLETED"


def test_a_claim_on_a_non_billable_session_is_refused_at_the_billability_rung(api):
    """PRD §2.7 rung 30: "**Billability.** A claim whose `service_class` is
    `THERAPY_SESSION` requires the named session to be in `billing_status`
    `BILLABLE`; a claim whose `service_class` is `EVALUATION` requires the named
    assessment to be in `status` `SIGNED`. Otherwise `ERR_SESSION_NOT_BILLABLE`, HTTP
    422. Applies to claim creation."

    Design: Difficulty/boundary_precision_check/zero_unit_session_is_not_billable_rejects_claim
    """
    scn = setup_active_plan()
    session = schedule_session(
        scn,
        scheduled_start_at="2026-06-10T09:00:00Z",
        scheduled_end_at="2026-06-10T09:30:00Z",
    )
    check_in(scn, session["id"])
    complete_session(scn, session["id"], "2026-06-10T09:07:00Z", 7)
    version_before = coverage_version(scn["cov_med"])

    response = api.create_claim(
        create_claim_payload(
            scn["pt"],
            scn["cov_med"],
            "THERAPY_SESSION",
            "2026-06-10",
            version_before,
            session_id=session["id"],
        ),
        scn["hdr_biller"],
    )

    validate_error(response, ApiErrorId.ERR_SESSION_NOT_BILLABLE.value, 422)
    rows, meta = validate_paginated(
        api.list_claims(scn["hdr_biller"], {"session_id": session["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0 and rows == []
    assert coverage_version(scn["cov_med"]) == version_before


def test_the_flat_code_bills_one_unit_however_many_minutes_were_delivered(api):
    """PRD §3.5: "A `FLAT_ORTHOPTIC_TRAINING` session always bills exactly 1 unit no
    matter how many minutes were delivered."
    PRD §3.5: "`charge_amount` is then `billable_units` multiplied by the clinic rate
    for the code, rounded half-up to two decimal places: 42.00 dollars per timed
    therapeutic-activity unit, 155.00 dollars per flat orthoptic-training unit, and
    210.00 dollars per evaluation-encounter unit, with any other code priced at 0.00."

    Design: Corner/calculations/flat_procedure_code_bills_one_unit_regardless_of_minutes
    """
    scn = setup_active_plan()
    session = schedule_session(scn, procedure_code="FLAT_ORTHOPTIC_TRAINING")
    check_in(scn, session["id"])

    data = validate_success(
        api.complete_session(
            session["id"],
            {"performed_at": "2026-06-10T09:55:00Z", "timed_minutes": 45},
            scn["hdr_cvt1"],
        ),
        200,
    )

    assert data["billable_units"] == 1
    assert_money(data["charge_amount"], 155.00, "charge_amount")
    assert data["billing_status"] == "BILLABLE"


def test_an_assistant_run_session_needs_a_documented_supervising_optometrist(api):
    """PRD §3.5: "When the running clinician's `credential` is
    `VISION_THERAPY_ASSISTANT`, `supervising_optometrist_id` is mandatory, must name a
    clinician whose `credential` is `OPTOMETRIST`, and that supervisor's own
    `credential_expires_at` must also be strictly after `performed_at`; a missing,
    wrongly-credentialled or expired supervisor is refused with
    `ERR_SUPERVISION_REQUIRED`."
    PRD §3.5: "Sessions run by an optometrist or a certified vision therapist need no
    supervisor."

    Design: Corner/validations/assistant_run_session_requires_documented_supervision
    """
    scn = setup_active_plan()
    session = schedule_session(scn, therapist_id=scn["vta1"], room_id=scn["room_a"])
    check_in(scn, session["id"])

    unsupervised = api.complete_session(
        session["id"],
        {"performed_at": "2026-06-10T09:55:00Z", "timed_minutes": 45},
        scn["hdr_vta1"],
    )
    validate_error(unsupervised, ApiErrorId.ERR_SUPERVISION_REQUIRED.value, 422)

    supervised = validate_success(
        api.complete_session(
            session["id"],
            {
                "performed_at": "2026-06-10T09:55:00Z",
                "timed_minutes": 45,
                "supervising_optometrist_id": scn["od1"],
            },
            scn["hdr_vta1"],
        ),
        200,
    )
    assert supervised["schedule_status"] == "COMPLETED"
    assert supervised["billing_status"] == "BILLABLE"
    assert supervised["supervising_optometrist_id"] == scn["od1"]


def test_a_no_show_burns_the_visit_unit_instead_of_returning_it(api):
    """PRD §3.5: "A no-show, by contrast, is reception's operation alone, applies only
    to an in-office session still in `SCHEDULED`, and is permitted only once the
    logical clock has reached or passed the session's `scheduled_start_at`."
    PRD §3.5: "It sets `schedule_status` `NO_SHOW` and `billing_status` `NON_BILLABLE`
    and bumps the session's `version`, and it deliberately does **not** release the
    unit: `visits_consumed` and `visits_remaining` are left exactly as they were,
    because a burned appointment burns the visit."

    Design: Corner/state_machines/no_show_burns_the_visit_unit_while_cancel_returns_it
    """
    scn = setup_active_plan()
    session = schedule_session(scn)
    set_clock("2026-06-10T09:30:00Z")

    data = validate_success(api.no_show_session(session["id"], scn["hdr_front"]), 200)

    assert data["schedule_status"] == "NO_SHOW"
    assert data["billing_status"] == "NON_BILLABLE"

    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 1
    assert pool["visits_released"] == 0
    assert pool["visits_remaining"] == 11
    assert pool["status"] == "ACTIVE"


def test_the_session_list_filters_by_modality_and_reports_the_page_window(api):
    """PRD §3.5: "Sessions are readable individually — the read exposes both the
    scheduling axis and the billing axis — and as a list narrowed by `plan_id`,
    `patient_id`, `therapist_id`, `room_id`, `authorization_id`,
    `supervising_optometrist_id`, `modality`, `schedule_status` and `billing_status`."
    PRD §2.3: "`total_count` reports how many rows matched the filters before the page
    window was applied, and `has_more` is true exactly when rows remain beyond the
    current window."

    Design: Corner/endpoints/session_list_filters_by_modality_and_paginates
    """
    scn = setup_active_plan()
    schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])
    schedule_session(
        scn,
        therapist_id=scn["od2"],
        room_id=scn["room_b"],
        scheduled_start_at="2026-06-11T09:00:00Z",
        scheduled_end_at="2026-06-11T10:00:00Z",
    )
    home = log_home_session(scn, "2026-05-28T18:00:00Z", 20)

    in_office, in_office_meta = validate_paginated(
        api.list_sessions(
            scn["hdr_front"],
            {"plan_id": scn["plan"], "modality": "IN_OFFICE", "limit": 1, "offset": 0},
        )
    )
    assert len(in_office) == 1
    assert in_office_meta["total_count"] == 2
    assert in_office_meta["has_more"] is True

    at_home, home_meta = validate_paginated(
        api.list_sessions(
            scn["hdr_front"],
            {"plan_id": scn["plan"], "modality": "HOME", "limit": 10, "offset": 0},
        )
    )
    assert len(at_home) == 1
    assert at_home[0]["id"] == home["id"]
    assert home_meta["total_count"] == 1
    assert home_meta["has_more"] is False
    for row in in_office + at_home:
        assert row["plan_id"] == scn["plan"]
