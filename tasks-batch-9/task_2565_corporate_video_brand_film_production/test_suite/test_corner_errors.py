"""Every refusal names itself, and names itself rather than its neighbour.

Nine refusals are provoked one at a time: a submit before QC has run, a verdict on a
cut nobody submitted, a second countersignature, an approval of an order already
rejected, a second release of the same booking, a cut against a closed deliverable, a
wrap under a permit that lapsed at the wrap instant, ten unknown identifiers each
answered by its own family's code, and a request carrying no acting user at all. In
every case the reads afterwards show the refusal cost the record nothing.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ARCHIVE_NOT_PACKAGED,
    BOOKING_RELEASED,
    CATEGORY_CREW,
    CATEGORY_POST,
    CATEGORY_TALENT,
    CERT_ISSUED,
    CERT_EXPIRED,
    CHANGE_ORDER_PENDING_APPROVAL,
    CHANGE_ORDER_REJECTED,
    CLIENT_APPROVER,
    COMPLIANCE_OFFICER,
    COORDINATOR,
    DECISION_APPROVE,
    DECISION_REJECT,
    DELIVERABLE_APPROVED,
    DELIVERABLE_PENDING,
    DEPT_GRIP_ELECTRIC,
    EMPTY_USER_ID_HEADERS,
    ENGAGEMENT_CONFIRMED,
    LINE_PRODUCER,
    NON_EXISTENT_UUID,
    NON_UNION,
    POSTURE_BLOCKED,
    POST_SUPERVISOR,
    PROJECT_DELIVERED,
    PROJECT_IN_PRODUCTION,
    PROJECT_SCOPED,
    REVIEW_DRAFT,
    REVIEW_GATE_OPEN,
    SHOOT_DAY_CONFIRMED,
    SHOOT_DAY_PLANNED,
    TECHNICAL_PENDING_QC,
    TECHNICAL_QC_PASSED,
    TRIGGER_DELIVERABLE_ADDED_AFTER_SCOPE_LOCK,
    USAGE_BUYOUT,
    ApiErrorId,
    add_budget_line,
    add_crew_member,
    add_deliverable,
    approve_budget,
    approved_cut,
    assert_cert_statuses,
    assert_change_order,
    assert_deliverable_state,
    assert_ledgers,
    assert_project_state,
    assert_shoot_day_state,
    assert_talent_comp,
    assert_total_count,
    assert_version_axes,
    book_crew,
    cancel_shoot_day,
    cast_talent,
    change_order_decision_payload,
    confirm_booking,
    confirm_shoot_day,
    confirm_talent,
    cut_payload,
    issued_coi,
    issued_permit,
    latest_change_order,
    lock_scope,
    ok_row,
    open_project,
    passed_cut,
    project_payload,
    read_booking,
    read_cert,
    read_cut,
    read_deliverable,
    read_project,
    read_shoot_day,
    register_location,
    release_booking,
    review_decision_payload,
    schedule_shoot_day,
    set_clock,
    upload_next_cut,
)


def _project_with_one_olv_deliverable(api, client_name, campaign_title, brief):
    """A `DRAFT` project and the one OLV deliverable a later lock will demand."""
    project = open_project(
        api,
        client_name=client_name,
        campaign_title=campaign_title,
        creative_brief_summary=brief,
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
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
    return project, deliverable


def _scoped(api, client_name, campaign_title, brief, category, description, unit_rate_cents):
    """The same project locked, with one `PLANNED` line on the top sheet."""
    project, deliverable = _project_with_one_olv_deliverable(api, client_name, campaign_title, brief)
    add_budget_line(
        api,
        project["id"],
        category=category,
        description=description,
        quantity=1,
        unit_rate_cents=unit_rate_cents,
        markup_pct=0,
    )
    return lock_scope(api, project["id"]), deliverable


def _in_production(api, client_name, campaign_title, brief, category, description, unit_rate_cents):
    """The same project signed off, so its line is committed and post may begin."""
    project, deliverable = _scoped(
        api, client_name, campaign_title, brief, category, description, unit_rate_cents
    )
    return approve_budget(api, project["id"], unit_rate_cents), deliverable


def _in_post(api, client_name, campaign_title, brief, category, description, unit_rate_cents,
             venue_name, venue_address, permit_authority):
    """The same project again, bubbled into post once no shoot day is left standing.

    A project reaches `DELIVERED` only from `IN_POST`, and the cheapest honest route
    there is to schedule the one day the production needed and then drop it.
    """
    project, deliverable = _in_production(
        api, client_name, campaign_title, brief, category, description, unit_rate_cents
    )
    location = register_location(
        api,
        name=venue_name,
        address=venue_address,
        stage_count=1,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority=permit_authority,
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    cancel_shoot_day(
        api, day["id"], cancellation_reason="Library footage used instead of a new shoot."
    )
    return read_project(api, project["id"]), deliverable


def test_submitting_a_cut_whose_qc_never_ran_names_the_technical_axis(api):
    """The technical axis has not been walked, so the cross-axis guard fires alone.

    PRD §2.12: "Priority 21: **QC passed before submission** — a cut may only be submitted
    while its `technical_status` is `QC_PASSED`; both `PENDING_QC` and `QC_FAILED` are
    refused (`ERR_VERSION_QC_NOT_PASSED`)."

    PRD §3.8: "An accepted upload increments the parent deliverable's `version` by one —
    which is what the next uploader must present as `expected_deliverable_version` — and
    writes the new row with `review_status` `DRAFT`, `technical_status` `PENDING_QC`,
    `qc_failure_reasons` as an empty array, and `submitted_by_user_id`,
    `reviewed_by_user_id`, `submitted_at` and `decided_at` all null."

    Design: Corner/errors/submit_before_qc_returns_version_qc_not_passed
    """
    _project, deliverable = _in_production(
        api,
        "Selwyn Textiles",
        "Unchecked",
        "Brand film submitted before QC ran.",
        CATEGORY_POST,
        "Edit and finish",
        2000000,
    )
    cut = upload_next_cut(api, deliverable["id"], cut_label="v1", file_size_gb=9.0)

    validate_error(
        api.submit_version(cut["id"], headers=POST_SUPERVISOR),
        ApiErrorId.ERR_VERSION_QC_NOT_PASSED,
    )

    after = read_cut(api, cut["id"])
    assert_version_axes(
        after, review_status=REVIEW_DRAFT, technical_status=TECHNICAL_PENDING_QC
    )
    assert after["submitted_at"] is None, after["submitted_at"]
    assert after["submitted_by_user_id"] is None, after["submitted_by_user_id"]
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_PENDING,
        version_count=1,
        consumed_review_rounds=0,
    )


def test_a_verdict_on_a_cut_nobody_submitted_names_the_review_axis(api):
    """QC passed is not the same as sent, and the approver's decision has nothing to judge.

    PRD §2.12: "Priority 19: **Cut review status permits the operation**
    (`ERR_VERSION_REVIEW_STATE_INVALID`): submission requires `DRAFT`, a review decision
    requires `SUBMITTED`, and a `SUPERSEDED`, `APPROVED` or `CHANGES_REQUESTED` cut accepts
    neither."

    PRD §3.8: "Either verdict stamps `reviewed_by_user_id` with the acting `X-User-ID` and
    `decided_at` with the logical clock."

    Design: Corner/errors/review_decision_on_a_draft_cut_returns_version_review_state_invalid
    """
    _project, deliverable = _in_production(
        api,
        "Selwyn Textiles",
        "Unsubmitted",
        "Brand film judged before it was submitted.",
        CATEGORY_POST,
        "Edit and finish",
        2000000,
    )
    cut = passed_cut(api, deliverable["id"], cut_label="v1", file_size_gb=9.0)

    validate_error(
        api.review_decision(
            cut["id"],
            review_decision_payload(DECISION_APPROVE, "Looks fine to me."),
            headers=CLIENT_APPROVER,
        ),
        ApiErrorId.ERR_VERSION_REVIEW_STATE_INVALID,
    )

    after = read_cut(api, cut["id"])
    assert_version_axes(
        after, review_status=REVIEW_DRAFT, technical_status=TECHNICAL_QC_PASSED
    )
    assert after["reviewed_by_user_id"] is None, after["reviewed_by_user_id"]
    assert after["decided_at"] is None, after["decided_at"]
    assert_deliverable_state(read_deliverable(api, deliverable["id"]), status=DELIVERABLE_PENDING)


def test_a_second_countersignature_cannot_credit_the_committed_ledger_twice(api):
    """Confirmation is not idempotent, and the 165,000 credit is applied exactly once.

    PRD §2.12: "Priority 26: **Engagement status permits confirmation** — must be `DRAFT`
    (`ERR_TALENT_ENGAGEMENT_STATE_INVALID`)."

    PRD §3.3: "The engagement then enters the committed set: the project's
    `committed_cost_cents` increases by the `FINAL` `total_comp_cents`, and
    `provisional_cost_cents` is recomputed with the `FINAL` total replacing the
    `PROVISIONAL` total for this engagement — which may move the provisional figure in
    either direction — after which `budget_variance_cents` is recomputed."

    Design: Corner/errors/confirming_a_confirmed_engagement_returns_talent_engagement_state_invalid
    """
    project, _deliverable = _project_with_one_olv_deliverable(
        api,
        "Bramwell Legal",
        "Twice Confirmed",
        "Brand film whose talent confirmation is retried.",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_TALENT,
        description="Principal talent",
        quantity=1,
        unit_rate_cents=200000,
        markup_pct=0,
    )
    engagement = cast_talent(
        api,
        project["id"],
        talent_name="Aurelio Vance",
        union_affiliation=NON_UNION,
        compensation_model=USAGE_BUYOUT,
        session_fee_cents=50000,
        session_days=2,
    )
    lock_scope(api, project["id"])
    confirmed = confirm_talent(api, engagement["id"])

    assert_talent_comp(
        confirmed,
        base_fee_cents=100000,
        usage_load_cents=50000,
        agent_fee_cents=15000,
        total_comp_cents=165000,
        status=ENGAGEMENT_CONFIRMED,
    )

    validate_error(
        api.confirm_talent_engagement(engagement["id"], headers=LINE_PRODUCER),
        ApiErrorId.ERR_TALENT_ENGAGEMENT_STATE_INVALID,
    )

    rows = assert_total_count(
        api.list_project_talent_engagements(project["id"], headers=LINE_PRODUCER), 1
    )
    assert_talent_comp(rows[0], total_comp_cents=165000, status=ENGAGEMENT_CONFIRMED)
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=365000, committed_cents=165000
    )


def test_a_rejected_change_order_can_never_be_approved_afterwards(api):
    """Rejection is terminal, and the money it removed does not come back.

    PRD §2.12: "Priority 25: **Change-order status permits the decision** —
    `PENDING_APPROVAL` for an approve or reject, `APPROVED` for a void
    (`ERR_CHANGE_ORDER_STATE_INVALID`)."

    PRD §3.9: "Rejection advances `PENDING_APPROVAL → REJECTED` and does the opposite: the
    project's `provisional_cost_cents` decreases by `amount_cents` as the row leaves the
    provisional set, `budget_variance_cents` is recomputed, and the `review_gate` returns
    to `OPEN` once no `PENDING_APPROVAL` order remains."

    Design: Corner/errors/approving_a_rejected_change_order_returns_change_order_state_invalid
    """
    project, _hero = _scoped(
        api,
        "Ludlow Ceramics",
        "Late Addition",
        "Brand film gaining a deliverable after scope lock.",
        CATEGORY_POST,
        "Edit and finish",
        2000000,
    )
    late = add_deliverable(
        api,
        project["id"],
        title="Late Addition cutdown 30",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=30,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    raised = latest_change_order(api, late["id"])

    assert_change_order(
        raised,
        labor_cents=620000,
        rush_pct=0.00,
        subtotal_cents=620000,
        producer_fee_pct=0.15,
        producer_fee_cents=93000,
        amount_cents=713000,
        status=CHANGE_ORDER_PENDING_APPROVAL,
        trigger_reason=TRIGGER_DELIVERABLE_ADDED_AFTER_SCOPE_LOCK,
    )
    assert raised["additional_rounds_granted"] == 0, raised["additional_rounds_granted"]

    ok_row(
        api.change_order_decision(
            raised["id"],
            change_order_decision_payload(
                DECISION_REJECT, "The cutdown is out of budget this quarter."
            ),
            headers=CLIENT_APPROVER,
        )
    )

    validate_error(
        api.change_order_decision(
            raised["id"],
            change_order_decision_payload(DECISION_APPROVE, "Reconsidered."),
            headers=CLIENT_APPROVER,
        ),
        ApiErrorId.ERR_CHANGE_ORDER_STATE_INVALID,
    )

    assert_change_order(
        latest_change_order(api, late["id"]),
        amount_cents=713000,
        status=CHANGE_ORDER_REJECTED,
    )
    after = read_project(api, project["id"])
    assert_project_state(after, status=PROJECT_SCOPED, review_gate=REVIEW_GATE_OPEN)
    assert_ledgers(after, provisional_cents=2000000, committed_cents=0)


def test_a_second_release_of_the_same_booking_cannot_debit_the_ledger_twice(api):
    """`RELEASED` accepts neither release nor confirm, and the 50,000 left only once.

    PRD §2.12: "Priority 23: **Crew-booking status permits the operation**
    (`ERR_CREW_BOOKING_STATE_INVALID`): confirmation requires `HELD`, release requires
    `HELD` or `CONFIRMED`, and a `COMPLETED` or `RELEASED` booking accepts neither."

    PRD §3.6: "Because `RELEASED` sits outside both inclusion sets, the project's
    `provisional_cost_cents` drops by the booking's `cost_cents`; and when the booking was
    `CONFIRMED`, the project's `committed_cost_cents` drops by exactly the amount that
    confirmation credited, leaving no drift."

    Design: Corner/errors/releasing_an_already_released_booking_returns_crew_booking_state_invalid
    """
    project, _deliverable = _scoped(
        api,
        "Quillon Optics",
        "Double Release",
        "Brand film whose grip is released twice.",
        CATEGORY_CREW,
        "Core unit",
        200000,
    )
    location = register_location(
        api,
        name="Quillon Lab",
        address="5 Lens Court, Rochester",
        stage_count=1,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority="Rochester Film Office",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    member = add_crew_member(
        api, full_name="Petra Lund", department=DEPT_GRIP_ELECTRIC, hourly_rate_cents=5000
    )
    booking = book_crew(
        api,
        day["id"],
        member["id"],
        department_role="Key Grip",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    confirm_booking(api, booking["id"])
    release_booking(api, booking["id"], release_reason="Day scaled back.")

    validate_error(
        api.release_crew_booking(
            booking["id"], {"release_reason": "Released again by mistake."}, headers=COORDINATOR
        ),
        ApiErrorId.ERR_CREW_BOOKING_STATE_INVALID,
    )
    validate_error(
        api.confirm_crew_booking(booking["id"], headers=COORDINATOR),
        ApiErrorId.ERR_CREW_BOOKING_STATE_INVALID,
    )

    after = read_booking(api, booking["id"])
    assert after["status"] == BOOKING_RELEASED, after["status"]
    assert after["cost_cents"] == 50000, after["cost_cents"]
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=200000, committed_cents=0
    )
    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        status=SHOOT_DAY_PLANNED,
        day_cost_cents=90000,
        confirmed_crew_count=0,
    )


def test_an_approved_deliverable_accepts_no_further_cut_even_at_the_right_version(api):
    """The deliverable is closed, so the state guard answers before any version comparison.

    PRD §2.12: "Priority 18: **Deliverable status permits the operation**
    (`ERR_DELIVERABLE_STATE_INVALID`): a cut may only be uploaded against a deliverable in
    `PENDING`, `IN_REVIEW` or `CHANGES_REQUESTED`; an `APPROVED` or `HANDED_OVER`
    deliverable accepts no further cuts."

    PRD §3.8: "Then, if that leaves every deliverable of the project in `APPROVED` and the
    project is `IN_POST`, the project advances `IN_POST → DELIVERED`, which in turn completes
    every `CONFIRMED` talent engagement as described in §3.3."

    Design: Corner/errors/new_cut_on_an_approved_deliverable_returns_deliverable_state_invalid
    """
    project, deliverable = _in_post(
        api,
        "Ashgrove Foods",
        "Closed Book",
        "Brand film approved on the first cut.",
        CATEGORY_POST,
        "Edit and finish",
        2000000,
        "Ashgrove Barn",
        "3 Grove Lane, Ashgrove",
        "Ashgrove Film Office",
    )
    approved_cut(api, deliverable["id"], cut_label="v1", file_size_gb=9.0)
    closed = read_deliverable(api, deliverable["id"])

    refused = api.create_deliverable_version(
        cut_payload(
            deliverable["id"],
            closed["version"],
            cut_label="v2 after approval",
            file_size_gb=9.1,
        ),
        headers=POST_SUPERVISOR,
    )

    validate_error(refused, ApiErrorId.ERR_DELIVERABLE_STATE_INVALID)
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_APPROVED,
        version_count=1,
    )
    assert_project_state(
        read_project(api, project["id"]),
        status=PROJECT_DELIVERED,
        archive_status=ARCHIVE_NOT_PACKAGED,
    )


def test_wrapping_under_a_permit_that_lapsed_at_the_wrap_instant_is_refused(api):
    """The permit was in force at confirmation and expired by the time wrap was called.

    PRD §2.12: "Priority 31: **Live compliance posture not blocked**
    (`ERR_COMPLIANCE_POSTURE_BLOCKED`, HTTP 422), checked on call-sheet publication and on
    wrap."

    PRD §3.5: "`effective_status` reads `EXPIRED` when the stored `status` is `ISSUED` and
    the logical clock has passed `effective_to`; in every other case it simply equals the
    stored `status`, so `SUBMITTED`, `DENIED`, and an `ISSUED` certificate still inside its
    window all report themselves."

    PRD §3.7: "It requires the day to be `CONFIRMED`, requires the logical clock to have
    reached or passed the day's `wrap_time`, and re-evaluates the posture, refusing with
    `ERR_COMPLIANCE_POSTURE_BLOCKED` if it reads `BLOCKED` at that instant."

    Design: Corner/errors/wrap_after_the_permit_expires_returns_compliance_posture_blocked
    """
    project, _deliverable = _in_production(
        api,
        "Harrow Rail",
        "Expiring Permit",
        "Brand film whose permit lapses at wrap.",
        CATEGORY_CREW,
        "Core unit",
        2000000,
    )
    location = register_location(
        api,
        name="Harrow Depot",
        address="2 Depot Road, Harrow",
        stage_count=1,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority="Harrow Council",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    permit = issued_permit(
        api,
        project["id"],
        day["id"],
        carrier_or_authority="Harrow Council",
        reference_code="PERMIT-HR-1",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-10T16:00:00Z",
        fee_cents=40000,
    )
    issued_coi(
        api,
        project["id"],
        carrier_or_authority="Middlesex Casualty",
        reference_code="COI-HR-1",
        coverage_amount_cents=50000000,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-30T00:00:00Z",
        fee_cents=60000,
    )
    confirm_shoot_day(api, day["id"])

    set_clock(api, "2026-09-10T16:00:01Z")
    validate_error(
        api.wrap_shoot_day(day["id"], headers=COORDINATOR),
        ApiErrorId.ERR_COMPLIANCE_POSTURE_BLOCKED,
    )

    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        status=SHOOT_DAY_CONFIRMED,
        compliance_posture=POSTURE_BLOCKED,
    )
    assert_cert_statuses(read_cert(api, permit["id"]), CERT_ISSUED, CERT_EXPIRED)
    assert_project_state(read_project(api, project["id"]), status=PROJECT_IN_PRODUCTION)


def test_every_identifier_family_answers_an_unknown_id_with_its_own_code(api):
    """Ten resolutions of the same unknown identifier, ten distinct 404 codes.

    PRD §2.12: "Priorities 6 through 15: **Existence** of every referenced row, in this
    order of identifier families — project (priority 6), deliverable (7), cut (8), change
    order (9), shoot day (10), location (11), crew member (12), crew booking (13),
    compliance certificate (14), talent engagement (15) — each reporting the 404 code listed
    in §2.11."

    Design: Corner/errors/unknown_ids_across_every_resource_return_their_own_not_found_codes
    """
    validate_error(
        api.get_project(NON_EXISTENT_UUID, headers=COORDINATOR),
        ApiErrorId.ERR_PROJECT_NOT_FOUND,
    )
    validate_error(
        api.get_deliverable(NON_EXISTENT_UUID, headers=COORDINATOR),
        ApiErrorId.ERR_DELIVERABLE_NOT_FOUND,
    )
    validate_error(
        api.get_deliverable_version(NON_EXISTENT_UUID, headers=COORDINATOR),
        ApiErrorId.ERR_DELIVERABLE_VERSION_NOT_FOUND,
    )
    validate_error(
        api.change_order_decision(
            NON_EXISTENT_UUID,
            change_order_decision_payload(DECISION_APPROVE, "No such order."),
            headers=CLIENT_APPROVER,
        ),
        ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND,
    )
    validate_error(
        api.get_shoot_day(NON_EXISTENT_UUID, headers=COORDINATOR),
        ApiErrorId.ERR_SHOOT_DAY_NOT_FOUND,
    )
    validate_error(
        api.get_location(NON_EXISTENT_UUID, headers=COORDINATOR),
        ApiErrorId.ERR_LOCATION_NOT_FOUND,
    )
    validate_error(
        api.get_crew_member(NON_EXISTENT_UUID, headers=COORDINATOR),
        ApiErrorId.ERR_CREW_MEMBER_NOT_FOUND,
    )
    validate_error(
        api.get_crew_booking(NON_EXISTENT_UUID, headers=COORDINATOR),
        ApiErrorId.ERR_CREW_BOOKING_NOT_FOUND,
    )
    validate_error(
        api.get_compliance_cert(NON_EXISTENT_UUID, headers=COMPLIANCE_OFFICER),
        ApiErrorId.ERR_COMPLIANCE_CERT_NOT_FOUND,
    )
    validate_error(
        api.confirm_talent_engagement(NON_EXISTENT_UUID, headers=LINE_PRODUCER),
        ApiErrorId.ERR_TALENT_ENGAGEMENT_NOT_FOUND,
    )


def test_a_request_with_no_acting_user_is_refused_before_anything_is_resolved(api):
    """An empty `X-User-ID` sinks both a creation and a read of an identifier that is absent.

    PRD §2.1: "If either header is missing, empty, or if `X-User-Role` names anything
    outside those six values, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    PRD §2.12: "Priority 1: **Authentication** — headers present and naming one of the six
    roles (`ERR_UNAUTHENTICATED`)."

    Design: Corner/errors/an_empty_user_id_header_returns_4xx_unauthenticated
    """
    validate_error(
        api.create_project(
            project_payload(
                client_name="Nameless Client",
                campaign_title="Anonymous Brief",
                creative_brief_summary="Brand film opened by nobody in particular.",
                channel_scope=["OLV"],
                usage_term_months=12,
                budget_ceiling_cents=50000000,
            ),
            headers=EMPTY_USER_ID_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
    validate_error(
        api.get_project(NON_EXISTENT_UUID, headers=EMPTY_USER_ID_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
