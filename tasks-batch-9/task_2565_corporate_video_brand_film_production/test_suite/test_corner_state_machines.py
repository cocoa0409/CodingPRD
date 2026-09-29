"""Where each row starts, which edges it will take, and which it refuses.

The declared initial states come first, then one accepted transition per family,
then the refusals: an edge that does not exist, a call repeated on a row that has
already taken it, and a terminal row asked to move again. The last four drive the
cascades and bubble-ups the contract attaches to those edges.
"""

from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

from test_helpers import (
    ARCHIVE_HANDED_OVER,
    ARCHIVE_NOT_PACKAGED,
    BASIS_FINAL,
    BOOKING_COMPLETED,
    BOOKING_HELD,
    BOOKING_RELEASED,
    CALL_SHEET_DRAFT,
    CATEGORY_LOCATION,
    CATEGORY_POST,
    CERT_ISSUED,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_2,
    COORDINATOR,
    DECISION_APPROVE,
    DECISION_DENY,
    DECISION_ISSUE,
    DEFAULT_CLOCK,
    DELIVERABLE_APPROVED,
    DELIVERABLE_HANDED_OVER,
    DEPT_CAMERA,
    DEPT_GRIP_ELECTRIC,
    ENGAGEMENT_COMPLETED,
    ENGAGEMENT_CONFIRMED,
    LINE_PRODUCER,
    NON_UNION,
    POSTURE_BLOCKED,
    POSTURE_RESTRICTED,
    POST_SUPERVISOR,
    PROJECT_ARCHIVED,
    PROJECT_DELIVERED,
    PROJECT_IN_POST,
    PROJECT_SCOPED,
    RESERVATION_RETURNED,
    REVIEW_APPROVED,
    REVIEW_DRAFT,
    SHOOT_DAY_CANCELLED,
    SHOOT_DAY_PLANNED,
    SHOOT_DAY_WRAPPED,
    TECHNICAL_QC_PASSED,
    USAGE_BUYOUT,
    USER_CLIENT_1,
    ApiErrorId,
    add_budget_line,
    add_crew_member,
    add_deliverable,
    approve_budget,
    assert_at_default_clock,
    assert_booking_components,
    assert_cert_statuses,
    assert_deliverable_state,
    assert_instant_equals,
    assert_ledgers,
    assert_project_state,
    assert_reservation,
    assert_shoot_day_state,
    assert_talent_comp,
    assert_total_count,
    assert_version_axes,
    assert_version_unchanged,
    book_crew,
    cancel_shoot_day,
    cast_talent,
    cert_decision_payload,
    confirm_booking,
    confirm_shoot_day,
    confirm_talent,
    decide_cert,
    expected_retention_expiry,
    file_coi,
    file_permit,
    handover,
    handover_payload,
    issued_coi,
    issued_permit,
    lock_scope,
    open_project,
    passed_cut,
    read_booking,
    read_cert,
    read_cut,
    read_deliverable,
    read_project,
    read_shoot_day,
    register_location,
    reserve_equipment,
    review_cut,
    schedule_shoot_day,
    set_clock,
    submit_cut,
    wrap_shoot_day,
)


def _project_with_one_deliverable_and_one_line(
    api,
    client_name,
    campaign_title,
    creative_brief_summary,
    category,
    description,
    unit_rate_cents,
    quantity=1,
    **project_over,
):
    """A `DRAFT` project carrying exactly what the scope lock demands."""
    project = open_project(
        api,
        client_name=client_name,
        campaign_title=campaign_title,
        creative_brief_summary=creative_brief_summary,
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
        **project_over,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title=f"{campaign_title} 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=category,
        description=description,
        quantity=quantity,
        unit_rate_cents=unit_rate_cents,
        markup_pct=0,
    )
    return project, deliverable


def _venue(api, name, address, permit_authority, stage_count=1):
    """A one-stage venue at 90,000 cents a day demanding 50,000,000 cents of cover."""
    return register_location(
        api,
        name=name,
        address=address,
        stage_count=stage_count,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority=permit_authority,
    )


def test_a_fresh_day_is_planned_and_a_fresh_booking_is_held_and_uncommitted(api):
    """Both rows land on their declared initial state, and only one ledger moves.

    PRD §3.4: "A new shoot day starts at `status` `PLANNED` with
    `call_sheet_status` `DRAFT`, `call_sheet_published_at` null and
    `cancellation_reason` null."

    PRD §3.6: "A new booking is written at `status` `HELD`, which puts its cost
    inside the provisional figure but not the committed one, and refreshes the day's
    `day_cost_cents`."

    Design: Corner/state_machines/shoot_day_and_crew_booking_start_in_declared_initial_states
    """
    project, _deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Vantage Realty",
        campaign_title="Open House",
        creative_brief_summary="One-day OLV brand film.",
        category=CATEGORY_LOCATION,
        description="House location fee",
        unit_rate_cents=90000,
    )
    lock_scope(api, project["id"])
    location = _venue(api, "Cedar Street House", "44 Cedar Street, Boise", "Boise Film Office")
    crew = add_crew_member(
        api, full_name="Ivo Marek", department=DEPT_CAMERA, hourly_rate_cents=5000
    )

    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    booking = book_crew(
        api,
        day["id"],
        crew["id"],
        department_role="Operator",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )

    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        status=SHOOT_DAY_PLANNED,
        compliance_posture=POSTURE_BLOCKED,
        call_sheet_status=CALL_SHEET_DRAFT,
        confirmed_crew_count=0,
        day_cost_cents=90000,
    )
    assert_booking_components(booking, status=BOOKING_HELD, cost_cents=50000)
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=140000, committed_cents=0
    )


def test_countersigning_the_memo_flips_the_basis_and_credits_the_committed_ledger(api):
    """The deal memo is re-priced on the `FINAL` basis and joins the committed set.

    PRD §3.3: "Confirmation flips `comp_basis` from `PROVISIONAL` to `FINAL` and
    rewrites `channel_basis_count`, `term_basis_months`, `reuse_cycles` and every
    money component on the `FINAL` basis."

    PRD §3.3: "The engagement then enters the committed set: the project's
    `committed_cost_cents` increases by the `FINAL` `total_comp_cents`, and
    `provisional_cost_cents` is recomputed with the `FINAL` total replacing the
    `PROVISIONAL` total for this engagement — which may move the provisional figure
    in either direction — after which `budget_variance_cents` is recomputed."

    PRD §3.3: "A channel multiplier is selected by the channel count, treating any
    count above four as four: one channel gives 0.50, two channels 0.85, three
    channels 1.20, and four or more channels 1.60."

    Design: Corner/state_machines/talent_engagement_confirm_advances_state_and_syncs_committed_ledger
    """
    project, _deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Fjord Outdoor",
        campaign_title="First Light",
        creative_brief_summary="OLV brand film with one on-camera principal.",
        category=CATEGORY_POST,
        description="Edit and finish",
        unit_rate_cents=500000,
    )
    engagement = cast_talent(
        api,
        project["id"],
        talent_name="Rea Sandoval",
        union_affiliation=NON_UNION,
        compensation_model=USAGE_BUYOUT,
        session_fee_cents=100000,
        session_days=1,
    )
    lock_scope(api, project["id"])

    confirmed = confirm_talent(api, engagement["id"])

    assert_talent_comp(
        confirmed,
        base_fee_cents=100000,
        usage_load_cents=50000,
        reuse_fee_cents=0,
        pension_health_cents=0,
        agent_fee_cents=15000,
        total_comp_cents=165000,
        comp_basis=BASIS_FINAL,
        status=ENGAGEMENT_CONFIRMED,
    )
    assert confirmed["channel_basis_count"] == 1, confirmed["channel_basis_count"]
    assert confirmed["term_basis_months"] == 12, confirmed["term_basis_months"]
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=665000, committed_cents=165000
    )


def test_wrapping_a_day_that_was_never_confirmed_is_refused(api):
    """The only edge into `WRAPPED` leaves `CONFIRMED`, so a planned day cannot wrap.

    PRD §2.12: "Priority 22: **Shoot-day status permits the operation**
    (`ERR_SHOOT_DAY_STATE_INVALID`): confirmation requires `PLANNED`; call-sheet
    publication requires `CONFIRMED`; wrap requires `CONFIRMED`; cancellation
    requires `PLANNED` or `CONFIRMED`; crew-booking and equipment-reservation
    creation require the day to be `PLANNED` or `CONFIRMED`."

    Design: Corner/state_machines/wrap_on_a_planned_shoot_day_is_rejected
    """
    project, _deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Anvil Bikes",
        campaign_title="Downhill",
        creative_brief_summary="One-day OLV brand film never confirmed.",
        category=CATEGORY_LOCATION,
        description="Trailhead fee",
        unit_rate_cents=90000,
    )
    lock_scope(api, project["id"])
    location = _venue(api, "Anvil Trailhead", "1 Summit Road, Bend", "Bend Film Office")
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    set_clock(api, "2026-09-10T16:00:00Z")

    refused = api.wrap_shoot_day(day["id"], headers=COORDINATOR)

    validate_error(refused, ApiErrorId.ERR_SHOOT_DAY_STATE_INVALID)
    assert_shoot_day_state(read_shoot_day(api, day["id"]), status=SHOOT_DAY_PLANNED)
    assert_project_state(read_project(api, project["id"]), status=PROJECT_SCOPED)


def test_a_second_qc_pass_on_the_same_cut_is_refused(api):
    """QC is recordable once; the repeat call changes neither axis of the cut.

    PRD §3.8: "Exactly one QC record is permitted per cut: the `technical_status`
    must still be `PENDING_QC`, and a second attempt is refused with
    `ERR_QC_ALREADY_RECORDED`."

    Design: Corner/state_machines/second_qc_on_the_same_cut_is_rejected
    """
    project = open_project(
        api,
        client_name="Loam Gardens",
        campaign_title="Root System",
        creative_brief_summary="OLV brand film with one conforming cut.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title="Root System 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    cut = passed_cut(
        api,
        deliverable["id"],
        cut_label="Root System v1",
        aspect_ratio="16:9",
        duration_seconds=60,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=8.5,
    )

    refused = api.record_qc(cut["id"], headers=POST_SUPERVISOR)

    validate_error(refused, ApiErrorId.ERR_QC_ALREADY_RECORDED)
    assert_version_axes(
        read_cut(api, cut["id"]),
        review_status=REVIEW_DRAFT,
        technical_status=TECHNICAL_QC_PASSED,
        qc_failure_reasons=[],
    )


def test_locking_an_already_scoped_project_is_refused_and_bumps_nothing(api):
    """The lock leaves `DRAFT` only, so the repeat call neither re-locks nor counts.

    PRD §3.1: "Freezing the scope is the `LineProducer`'s move and advances the
    project `DRAFT → SCOPED`."

    PRD §2.12: "Priority 17: **Project status permits the operation**
    (`ERR_PROJECT_STATE_INVALID`, HTTP 409). Scope lock requires `DRAFT`; budget
    approval requires `SCOPED`; budget-line creation requires `DRAFT`, `SCOPED`,
    `IN_PRODUCTION` or `IN_POST`; talent-engagement creation requires `DRAFT`,
    `SCOPED` or `IN_PRODUCTION`; deliverable creation requires `DRAFT`, `SCOPED`,
    `IN_PRODUCTION` or `IN_POST`; shoot-day creation requires `SCOPED` or
    `IN_PRODUCTION`; shoot-day confirmation requires `IN_PRODUCTION`; cut submission
    and review decisions require `IN_PRODUCTION` or `IN_POST`; handover requires
    `DELIVERED`."

    PRD §2.4 defines `version` as "a counter that starts at 1 on creation and
    increments by 1 on every mutation of the row, including mutations the server
    performs on its own initiative as part of a cascade."

    Design: Corner/state_machines/second_lock_scope_on_a_scoped_project_is_rejected
    """
    project, _deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Quarry Coffee",
        campaign_title="Second Pour",
        creative_brief_summary="OLV brand film already scope-locked.",
        category=CATEGORY_POST,
        description="Edit and finish",
        unit_rate_cents=500000,
    )
    locked = lock_scope(api, project["id"])

    refused = api.lock_scope(project["id"], headers=LINE_PRODUCER)

    validate_error(refused, ApiErrorId.ERR_PROJECT_STATE_INVALID)
    after = read_project(api, project["id"])
    assert_project_state(after, status=PROJECT_SCOPED)
    assert_version_unchanged(locked, after)


def test_a_second_decision_on_an_issued_permit_cannot_reverse_it(api):
    """`ISSUED` is terminal, and the attempted denial overwrites neither field.

    PRD §3.5: "Recording the authority's or carrier's verdict is also a
    `ComplianceOfficer` action, must come from a different `X-User-ID` than the
    filer's (otherwise `ERR_SEGREGATION_OF_DUTIES`), and is permitted only while the
    certificate is `SUBMITTED` — `ISSUED` and `DENIED` are terminal, and a second
    decision is refused with `ERR_COMPLIANCE_CERT_STATE_INVALID`."

    PRD §3.5: "`effective_status` reads `EXPIRED` when the stored `status` is
    `ISSUED` and the logical clock has passed `effective_to`; in every other case it
    simply equals the stored `status`, so `SUBMITTED`, `DENIED`, and an `ISSUED`
    certificate still inside its window all report themselves."

    Design: Corner/state_machines/decision_on_an_already_issued_certificate_is_rejected
    """
    project, _deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Tobin Motors",
        campaign_title="City Loop",
        creative_brief_summary="One-day OLV brand film on a permitted street.",
        category=CATEGORY_LOCATION,
        description="Street hold",
        unit_rate_cents=90000,
    )
    lock_scope(api, project["id"])
    location = _venue(api, "Tobin Loop", "5 Central Loop, Akron", "Akron Film Office")
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    filed = file_permit(
        api,
        project["id"],
        day["id"],
        carrier_or_authority="Akron Film Office",
        reference_code="PRM-31009",
    )
    issued = decide_cert(
        api, filed["id"], DECISION_ISSUE, decision_note="Street permit granted."
    )

    refused = api.compliance_cert_decision(
        filed["id"],
        cert_decision_payload(DECISION_DENY, "Reversal attempt."),
        headers=COMPLIANCE_OFFICER_2,
    )

    validate_error(refused, ApiErrorId.ERR_COMPLIANCE_CERT_STATE_INVALID)
    after = read_cert(api, filed["id"])
    assert_cert_statuses(after, status=CERT_ISSUED, effective_status=CERT_ISSUED)
    assert after["decision_note"] == "Street permit granted.", after["decision_note"]
    assert_at_default_clock(after["decided_at"])
    assert_instant_equals(after["decided_at"], issued["decided_at"])


def test_issuing_the_project_wide_coi_lifts_both_days_out_of_blocked(api):
    """One insurance decision recomputes the posture of every day on the project.

    PRD §3.5: "Either verdict cascades across aggregates: for a `FILM_PERMIT` the
    linked shoot day's `compliance_posture` is recomputed, and for a
    `LIABILITY_COI` the `compliance_posture` of every shoot day of the project is
    recomputed."

    PRD §3.5: "The insurance test passes when there exists a certificate on the same
    `project_id`, of `cert_type` `LIABILITY_COI`, with `status` `ISSUED`, whose
    `coverage_amount_cents` is at least the location's `insurance_minimum_cents`,
    whose `effective_from` is at or before `call_time`, whose `effective_to` is at or
    after `wrap_time`, and whose `effective_to` is at or after the logical clock."

    PRD §3.5: "The posture is `BLOCKED` whenever either the permit test or the
    insurance test fails; it is `RESTRICTED` when both pass but fewer than three
    crew bookings are confirmed; and it is `OPEN` only when both pass and at least
    three are confirmed."

    Design: Corner/state_machines/liability_coi_issue_recomputes_posture_on_every_shoot_day_of_the_project
    """
    project, _deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Kirby Cement",
        campaign_title="Set Time",
        creative_brief_summary="Two-day OLV brand film on one insured location.",
        category=CATEGORY_LOCATION,
        description="Plant location fee",
        unit_rate_cents=90000,
        quantity=2,
    )
    lock_scope(api, project["id"])
    location = _venue(
        api, "Kirby Plant Yard", "600 Kiln Road, Gary", "Gary Film Office", stage_count=2
    )
    day_a = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    day_b = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-11T06:00:00Z",
        wrap_time="2026-09-11T16:00:00Z",
    )
    issued_permit(
        api,
        project["id"],
        day_a["id"],
        carrier_or_authority="Gary Film Office",
        reference_code="PRM-70001",
    )
    issued_permit(
        api,
        project["id"],
        day_b["id"],
        carrier_or_authority="Gary Film Office",
        reference_code="PRM-70002",
    )
    coi = file_coi(
        api,
        project["id"],
        reference_code="COI-70003",
        coverage_amount_cents=50000000,
    )
    assert_shoot_day_state(read_shoot_day(api, day_a["id"]), compliance_posture=POSTURE_BLOCKED)
    assert_shoot_day_state(read_shoot_day(api, day_b["id"]), compliance_posture=POSTURE_BLOCKED)

    bound = decide_cert(
        api, coi["id"], DECISION_ISSUE, decision_note="Carrier bound the policy."
    )

    assert_cert_statuses(bound, status=CERT_ISSUED, effective_status=CERT_ISSUED)
    assert_shoot_day_state(
        read_shoot_day(api, day_a["id"]), compliance_posture=POSTURE_RESTRICTED
    )
    assert_shoot_day_state(
        read_shoot_day(api, day_b["id"]), compliance_posture=POSTURE_RESTRICTED
    )
    certs = assert_total_count(
        api.list_compliance_certs(project_id=project["id"], headers=COMPLIANCE_OFFICER), 3
    )
    assert [cert["status"] for cert in certs] == [CERT_ISSUED] * 3, certs


def test_wrapping_completes_the_crew_returns_the_kit_and_bubbles_the_project(api):
    """One wrap moves three child rows and the project, and neither ledger stirs.

    PRD §3.7: "Every crew booking still `CONFIRMED` moves `CONFIRMED → COMPLETED`,
    and the committed figure does not move because `COMPLETED` stays inside the
    committed inclusion set."

    PRD §3.7: "Every equipment reservation still `RESERVED` moves `RESERVED →
    RETURNED`, and neither figure moves because `RETURNED` stays inside both
    inclusion sets."

    PRD §3.7: "Finally the day bubbles up: when no shoot day of the project remains
    in `PLANNED` or `CONFIRMED` and at least one shoot day exists, and the project is
    `IN_PRODUCTION`, the project advances `IN_PRODUCTION → IN_POST`, incrementing its
    `version` and refreshing its `updated_at`."

    Design: Corner/state_machines/shoot_day_wrap_completes_crew_returns_equipment_and_bubbles_project_to_post
    """
    project, _deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Halcyon Air",
        campaign_title="Tail Number",
        creative_brief_summary="One-day OLV brand film on an insured airfield.",
        category=CATEGORY_POST,
        description="Edit and finish",
        unit_rate_cents=2000000,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    location = _venue(
        api, "Halcyon Hangar 3", "3 Airfield Road, Wichita", "Wichita Film Office"
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    issued_coi(
        api,
        project["id"],
        reference_code="COI-81002",
        coverage_amount_cents=50000000,
    )
    issued_permit(
        api,
        project["id"],
        day["id"],
        carrier_or_authority="Wichita Film Office",
        reference_code="PRM-81003",
    )
    confirm_shoot_day(api, day["id"])
    crew = add_crew_member(
        api, full_name="Ivo Marek", department=DEPT_CAMERA, hourly_rate_cents=5000
    )
    booking = book_crew(
        api,
        day["id"],
        crew["id"],
        department_role="Operator",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    confirm_booking(api, booking["id"])
    reserve_equipment(
        api,
        day["id"],
        vendor_name="Cascade Camera Rentals",
        kit_label="A-cam and B-cam bodies",
        unit_count=2,
        daily_rate_cents=30000,
        pickup_at="2026-09-09T06:00:00Z",
        return_at="2026-09-11T06:00:00Z",
    )
    set_clock(api, "2026-09-10T16:00:00Z")

    wrapped = wrap_shoot_day(api, day["id"])

    assert_shoot_day_state(wrapped, status=SHOOT_DAY_WRAPPED)
    assert_booking_components(
        read_booking(api, booking["id"]), status=BOOKING_COMPLETED, cost_cents=50000
    )
    reservations = assert_total_count(
        api.list_shoot_day_equipment_reservations(day["id"], headers=COORDINATOR), 1
    )
    assert_reservation(
        reservations[0], rental_days=2, total_cost_cents=120000, status=RESERVATION_RETURNED
    )
    after = read_project(api, project["id"])
    assert_project_state(after, status=PROJECT_IN_POST)
    assert_ledgers(
        after,
        provisional_cents=2170000,
        committed_cents=2170000,
        approved_cents=2000000,
        variance_cents=170000,
    )
    assert_shoot_day_state(
        read_shoot_day(api, day["id"]), day_cost_cents=260000, confirmed_crew_count=1
    )


def test_the_last_approval_delivers_the_project_and_completes_the_talent(api):
    """Approving the only cut bubbles twice and sweeps the countersigned memo.

    PRD §3.8: "An approval advances the cut `SUBMITTED → APPROVED` and bubbles up in
    two hops."

    PRD §3.8: "Then, if that leaves every deliverable of the project in `APPROVED`
    and the project is `IN_POST`, the project advances `IN_POST → DELIVERED`, which
    in turn completes every `CONFIRMED` talent engagement as described in §3.3."

    PRD §3.3: "When the project reaches delivery, every engagement still `CONFIRMED`
    moves `CONFIRMED → COMPLETED`, and this movement is deliberately ledger-neutral:
    `total_comp_cents` is untouched and `COMPLETED` sits inside both the provisional
    and the committed inclusion sets, so neither project figure changes."

    Design: Corner/state_machines/final_deliverable_approval_delivers_project_and_completes_talent
    """
    project, deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Rhodes Ceramics",
        campaign_title="Kiln Light",
        creative_brief_summary=(
            "OLV brand film with one principal and one cancelled shoot day."
        ),
        category=CATEGORY_POST,
        description="Edit and finish",
        unit_rate_cents=2000000,
    )
    engagement = cast_talent(
        api,
        project["id"],
        talent_name="Rea Sandoval",
        union_affiliation=NON_UNION,
        compensation_model=USAGE_BUYOUT,
        session_fee_cents=100000,
        session_days=1,
    )
    lock_scope(api, project["id"])
    confirm_talent(api, engagement["id"])
    approve_budget(api, project["id"], 2165000)
    location = _venue(
        api, "Rhodes Studio Kiln", "18 Potters Way, Athens", "Athens Film Office"
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    cancel_shoot_day(
        api, day["id"], cancellation_reason="Shoot folded into the studio schedule."
    )
    cut = passed_cut(
        api,
        deliverable["id"],
        cut_label="Kiln Light v1",
        aspect_ratio="16:9",
        duration_seconds=60,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=9.0,
    )
    submit_cut(api, cut["id"])

    approved = review_cut(
        api, cut["id"], DECISION_APPROVE, review_note="Approved as delivered."
    )

    assert_version_axes(approved, review_status=REVIEW_APPROVED)
    assert approved["reviewed_by_user_id"] == USER_CLIENT_1, approved["reviewed_by_user_id"]
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_APPROVED,
        consumed_review_rounds=0,
    )
    after = read_project(api, project["id"])
    assert_project_state(
        after, status=PROJECT_DELIVERED, archive_status=ARCHIVE_NOT_PACKAGED
    )
    assert_ledgers(after, committed_cents=2165000, variance_cents=0)
    engagements = assert_total_count(
        api.list_project_talent_engagements(project["id"], headers=LINE_PRODUCER), 1
    )
    assert_talent_comp(
        engagements[0], status=ENGAGEMENT_COMPLETED, total_comp_cents=165000
    )


def test_a_second_handover_cannot_restamp_the_retention_clock(api):
    """`ARCHIVED` is terminal: the retention window stays where the first call put it.

    PRD §3.10: "It requires the project to be `DELIVERED` — any other status reports
    `ERR_PROJECT_STATE_INVALID` — and it requires `handover_at` to still be null,
    expressed operationally as `archive_status` still reading `NOT_PACKAGED`; a second
    handover on the same project is refused with `ERR_ARCHIVE_ALREADY_HANDED_OVER`."

    PRD §3.10: "`retention_expires_at` is `handover_at` plus the project's
    `raw_footage_retention_months` multiplied by 30 days, using whole days added to
    the handover instant; calendar month lengths are deliberately not used, so a
    12-month retention term is exactly 360 days."

    PRD §3.10: "Handover also cascades down: every deliverable of the project whose
    `status` is `APPROVED` advances `APPROVED → HANDED_OVER`, each such row
    incrementing its `version` and refreshing its `updated_at`, and the project's own
    `version` increments as well."

    Design: Corner/state_machines/second_handover_on_an_archived_project_is_rejected
    """
    project, deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Pemberton Glass",
        campaign_title="Clear Cast",
        creative_brief_summary=(
            "OLV brand film delivered and ready for archive handover."
        ),
        category=CATEGORY_POST,
        description="Edit and finish",
        unit_rate_cents=2000000,
        raw_footage_terabytes=18.75,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    location = _venue(
        api, "Pemberton Studio", "2 Glassworks Row, Toledo", "Toledo Film Office"
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    cancel_shoot_day(
        api, day["id"], cancellation_reason="Archive footage used instead of a new shoot."
    )
    cut = passed_cut(
        api,
        deliverable["id"],
        cut_label="Clear Cast v1",
        aspect_ratio="16:9",
        duration_seconds=60,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=9.0,
    )
    submit_cut(api, cut["id"])
    review_cut(api, cut["id"], DECISION_APPROVE, review_note="Approved as delivered.")
    handover(api, project["id"], handover_recipient="Dana Whitlock, client archive custodian")

    refused = api.handover(
        project["id"], handover_payload("Someone else entirely"), headers=LINE_PRODUCER
    )

    # PRD leaves the *identity* of this error undetermined, so either code is faithful.
    # §3.10 names `ERR_ARCHIVE_ALREADY_HANDED_OVER` for "a second handover on the same
    # project", but handover itself advances the project `DELIVERED → ARCHIVED`, so the
    # second call also violates the priority-17 rule that "handover requires `DELIVERED`".
    # §2.12 orders project-status (17) ahead of handover-happens-once (27) and states that
    # when "a single request violates several rules ... which one is fully determined" —
    # which makes `ERR_PROJECT_STATE_INVALID` the literal reading of the precedence table.
    # Both readings are PRD-faithful; what the product rule actually guarantees, and what
    # the assertions below pin, is that the second call restamps nothing.
    validate_error_is_one_of(
        refused,
        [
            ApiErrorId.ERR_ARCHIVE_ALREADY_HANDED_OVER,
            ApiErrorId.ERR_PROJECT_STATE_INVALID,
        ],
    )
    # PRD §5 maps both candidate codes to 409, so the status stays exactly asserted.
    assert refused.status_code == 409, refused.status_code
    after = read_project(api, project["id"])
    assert_project_state(
        after, status=PROJECT_ARCHIVED, archive_status=ARCHIVE_HANDED_OVER
    )
    assert_at_default_clock(after["handover_at"])
    assert after["handover_recipient"] == "Dana Whitlock, client archive custodian", (
        after["handover_recipient"]
    )
    assert_instant_equals(
        after["retention_expires_at"], expected_retention_expiry(DEFAULT_CLOCK, 12)
    )
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]), status=DELIVERABLE_HANDED_OVER
    )


def test_cancelling_debits_the_confirmed_booking_and_not_the_held_one(api):
    """Both bookings are released, but only the confirmed one had been committed.

    PRD §3.7: "Hop two, caused by hop one: each booking that left `CONFIRMED` debits
    the project's `committed_cost_cents` by its own `cost_cents`, while bookings
    released out of `HELD` debit the committed figure nothing; every released booking,
    from either state, leaves the provisional set, so `provisional_cost_cents` drops
    by its `cost_cents`."

    PRD §3.7: "And exactly as with wrap, when no shoot day of the project remains in
    `PLANNED` or `CONFIRMED` and at least one exists, the project bubbles
    `IN_PRODUCTION → IN_POST`."

    Design: Corner/state_machines/cancel_debits_only_the_confirmed_booking_and_leaves_held_unbilled
    """
    project, _deliverable = _project_with_one_deliverable_and_one_line(
        api,
        client_name="Ashgrove Cider",
        campaign_title="Press Day",
        creative_brief_summary="One-day OLV brand film with a partly confirmed unit.",
        category=CATEGORY_POST,
        description="Edit and finish",
        unit_rate_cents=2000000,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)
    location = _venue(
        api, "Ashgrove Press House", "6 Orchard Lane, Hood River", "Hood River Film Office"
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    crew_a = add_crew_member(
        api, full_name="Ivo Marek", department=DEPT_CAMERA, hourly_rate_cents=5000
    )
    crew_b = add_crew_member(
        api, full_name="Sasha Bell", department=DEPT_GRIP_ELECTRIC, hourly_rate_cents=5000
    )
    confirmed_booking = book_crew(
        api,
        day["id"],
        crew_a["id"],
        department_role="Operator",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    confirm_booking(api, confirmed_booking["id"])
    held_booking = book_crew(
        api,
        day["id"],
        crew_b["id"],
        department_role="Key Grip",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    assert_ledgers(
        read_project(api, project["id"]),
        provisional_cents=2100000,
        committed_cents=2050000,
    )

    cancelled = cancel_shoot_day(
        api, day["id"], cancellation_reason="Client postponed the press day."
    )

    assert_shoot_day_state(cancelled, status=SHOOT_DAY_CANCELLED)
    assert cancelled["cancellation_reason"] == "Client postponed the press day.", (
        cancelled["cancellation_reason"]
    )
    assert_booking_components(
        read_booking(api, confirmed_booking["id"]), status=BOOKING_RELEASED
    )
    assert_booking_components(read_booking(api, held_booking["id"]), status=BOOKING_RELEASED)
    after = read_project(api, project["id"])
    assert_ledgers(
        after,
        provisional_cents=2000000,
        committed_cents=2000000,
        approved_cents=2000000,
        variance_cents=0,
    )
    assert_project_state(after, status=PROJECT_IN_POST)
    assert_shoot_day_state(
        read_shoot_day(api, day["id"]), confirmed_crew_count=0, day_cost_cents=90000
    )
