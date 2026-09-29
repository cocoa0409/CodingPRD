"""Which requests the contract refuses, and what the refusal leaves behind.

Each test drives one validation to the edge it guards — a channel outside the
licensed scope, a rights term longer than the deal, a union performer priced as a
buyout, a certificate scoped to the wrong subject, a pickup one second early, a
scope lock with half its inputs, a supersede reaching into another deliverable, a
page window outside its band, insurance one cent short of the venue floor, and a
call sheet one second inside the lead window — and then reads the record back to
show that the refusal moved nothing and that the honest retry succeeds.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    CALL_SHEET_DRAFT,
    CALL_SHEET_PUBLISHED,
    CATEGORY_CREW,
    CATEGORY_EQUIPMENT,
    CATEGORY_POST,
    CERT_SUBMITTED,
    COMPLIANCE_OFFICER,
    COORDINATOR,
    DECISION_REQUEST_CHANGES,
    DELIVERABLE_IN_REVIEW,
    DELIVERABLE_PENDING,
    DEPT_CAMERA,
    DEPT_GRIP_ELECTRIC,
    DEPT_SOUND,
    LINE_PRODUCER,
    LOCATION_CONFIRMED,
    MAX_LIMIT,
    NON_UNION,
    POSTURE_BLOCKED,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    POST_SUPERVISOR,
    PROJECT_DRAFT,
    PROJECT_IN_PRODUCTION,
    PROJECT_SCOPED,
    REVIEW_CHANGES_REQUESTED,
    REVIEW_GATE_OPEN,
    REVIEW_SUBMITTED,
    SHOOT_DAY_CONFIRMED,
    SHOOT_DAY_PLANNED,
    TECHNICAL_QC_PASSED,
    UNION,
    UNION_SESSION_REUSE,
    USAGE_BUYOUT,
    USER_POST_1,
    ApiErrorId,
    add_budget_line,
    add_crew_member,
    add_deliverable,
    approve_budget,
    assert_at_default_clock,
    assert_cert_statuses,
    assert_deliverable_state,
    assert_empty_listing,
    assert_instant_equals,
    assert_ledgers,
    assert_project_state,
    assert_shoot_day_state,
    assert_total_count,
    assert_version_axes,
    assert_version_bumped,
    assert_version_unchanged,
    book_crew,
    confirm_booking,
    confirm_shoot_day,
    created_row,
    cut_payload,
    deliverable_payload,
    equipment_reservation_payload,
    file_coi,
    file_permit,
    film_permit_payload,
    issued_coi,
    issued_permit,
    liability_coi_payload,
    lock_scope,
    ok_row,
    open_project,
    passed_cut,
    publish_call_sheet,
    read_cut,
    read_deliverable,
    read_project,
    read_shoot_day,
    register_location,
    review_cut,
    schedule_shoot_day,
    set_clock,
    submit_cut,
    submitted_cut,
    talent_engagement_payload,
    upload_next_cut,
)


def _draft_project(api, client_name, campaign_title, creative_brief_summary, **over):
    """A `DRAFT` project licensed for OLV on a twelve-month term."""
    over.setdefault("channel_scope", ["OLV"])
    over.setdefault("usage_term_months", 12)
    over.setdefault("budget_ceiling_cents", 50000000)
    return open_project(
        api,
        client_name=client_name,
        campaign_title=campaign_title,
        creative_brief_summary=creative_brief_summary,
        **over,
    )


def _olv_deliverable(api, project_id, title, target_duration_seconds=60):
    """One OLV cut licensed for twelve months, captions unasked for."""
    return add_deliverable(
        api,
        project_id,
        title=title,
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=target_duration_seconds,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )


def _scoped_project(
    api,
    client_name,
    campaign_title,
    creative_brief_summary,
    category,
    description,
    unit_rate_cents,
):
    """A `SCOPED` project carrying one OLV deliverable and one `PLANNED` line."""
    project = _draft_project(api, client_name, campaign_title, creative_brief_summary)
    deliverable = _olv_deliverable(api, project["id"], f"{campaign_title} 60")
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


def _production_project(
    api,
    client_name,
    campaign_title,
    creative_brief_summary,
    category,
    description,
    unit_rate_cents,
):
    """The same project with the client's sign-off recorded, `SCOPED → IN_PRODUCTION`."""
    project, deliverable = _scoped_project(
        api,
        client_name,
        campaign_title,
        creative_brief_summary,
        category,
        description,
        unit_rate_cents,
    )
    return approve_budget(api, project["id"], unit_rate_cents), deliverable


def _venue(api, name, address, permit_authority, insurance_minimum_cents=50000000):
    """A one-stage venue at 90,000 cents a day with its own insurance floor."""
    return register_location(
        api,
        name=name,
        address=address,
        stage_count=1,
        daily_fee_cents=90000,
        insurance_minimum_cents=insurance_minimum_cents,
        permit_authority=permit_authority,
    )


def _day_on(api, project_id, location_id):
    """One `PLANNED` day occupying the venue from call to wrap."""
    return schedule_shoot_day(
        api,
        project_id,
        location_id,
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )


def test_a_deliverable_on_an_unlicensed_channel_is_refused(api):
    """The scope is a licence, not a suggestion, and the broadcast cut never lands.

    PRD §3.1: "Two rights checks guard the registration, in this order: the `channel`
    must be a member of the project's `channel_scope`, or the request is refused with
    `ERR_CHANNEL_OUT_OF_SCOPE`; and `usage_rights_months` must not exceed the project's
    `usage_term_months`, or the request is refused with `ERR_USAGE_RIGHTS_EXCEED_TERM`."

    Design: Corner/validations/deliverable_on_a_channel_outside_project_scope_rejected
    """
    project = _draft_project(
        api,
        client_name="Halvard Brewing",
        campaign_title="Barrel Room",
        creative_brief_summary="Sixty-second brand film for the taproom relaunch.",
        channel_scope=["OLV", "SOCIAL"],
    )

    refused = api.create_deliverable(
        deliverable_payload(
            project["id"],
            title="Barrel Room 30",
            channel="BROADCAST",
            target_duration_seconds=30,
            usage_rights_months=12,
        ),
        headers=LINE_PRODUCER,
    )

    validate_error(refused, ApiErrorId.ERR_CHANNEL_OUT_OF_SCOPE)
    assert_empty_listing(api.list_project_deliverables(project["id"], headers=LINE_PRODUCER))
    after = read_project(api, project["id"])
    assert_project_state(after, status=PROJECT_DRAFT)
    assert_ledgers(after, provisional_cents=0, committed_cents=0)


def test_rights_longer_than_the_project_term_are_refused_and_the_retry_at_the_term_lands(api):
    """The second rights check is an inequality, and the deliverable clears it at parity.

    PRD §3.1: "Two rights checks guard the registration, in this order: the `channel`
    must be a member of the project's `channel_scope`, or the request is refused with
    `ERR_CHANNEL_OUT_OF_SCOPE`; and `usage_rights_months` must not exceed the project's
    `usage_term_months`, or the request is refused with `ERR_USAGE_RIGHTS_EXCEED_TERM`."

    PRD §3.1: "A registered deliverable starts at `status` `PENDING` with
    `consumed_review_rounds` at 0, `granted_extra_rounds` at 0, `round_entitlement`
    equal to the project's `contracted_revision_rounds`, and `version_count` at 0."

    Design: Corner/validations/deliverable_usage_rights_longer_than_the_project_term_rejected
    """
    project = _draft_project(
        api,
        client_name="Halvard Brewing",
        campaign_title="Barrel Room Rights",
        creative_brief_summary="OLV hero film under a strictly bounded licence.",
        channel_scope=["OLV"],
        usage_term_months=12,
    )

    refused = api.create_deliverable(
        deliverable_payload(
            project["id"],
            title="Barrel Room Rights 60",
            channel="OLV",
            usage_rights_months=24,
        ),
        headers=LINE_PRODUCER,
    )

    validate_error(refused, ApiErrorId.ERR_USAGE_RIGHTS_EXCEED_TERM)
    assert_empty_listing(api.list_project_deliverables(project["id"], headers=LINE_PRODUCER))

    accepted = created_row(
        api.create_deliverable(
            deliverable_payload(
                project["id"],
                title="Barrel Room Rights 60",
                channel="OLV",
                usage_rights_months=12,
            ),
            headers=LINE_PRODUCER,
        )
    )

    assert accepted["usage_rights_months"] == 12, accepted["usage_rights_months"]
    assert_deliverable_state(
        accepted,
        status=DELIVERABLE_PENDING,
        version_count=0,
        consumed_review_rounds=0,
        granted_extra_rounds=0,
        round_entitlement=2,
    )
    rows = assert_total_count(
        api.list_project_deliverables(project["id"], headers=LINE_PRODUCER), 1
    )
    assert rows[0]["id"] == accepted["id"], rows[0]["id"]


def test_neither_union_pairing_may_be_inverted(api):
    """Both halves of the pairing rule bite, and neither memo reaches the ledger.

    PRD §3.3: "The two enumerations are not independent: a `UNION` performer may never
    be bought out, so a `UNION` engagement must use `UNION_SESSION_REUSE` and a
    `NON_UNION` engagement must use `USAGE_BUYOUT`; any other pairing is refused with
    `ERR_TALENT_COMP_MODEL_INVALID`."

    Design: Corner/validations/union_talent_priced_as_a_usage_buyout_rejected
    """
    project = _draft_project(
        api,
        client_name="Corven Air",
        campaign_title="Crosswind",
        creative_brief_summary="OLV brand film fronted by a single on-camera performer.",
    )

    bought_out_union = api.create_talent_engagement(
        talent_engagement_payload(
            project["id"],
            talent_name="Odile Prentice",
            union_affiliation=UNION,
            compensation_model=USAGE_BUYOUT,
            session_fee_cents=100000,
            session_days=2,
        ),
        headers=LINE_PRODUCER,
    )
    reused_non_union = api.create_talent_engagement(
        talent_engagement_payload(
            project["id"],
            talent_name="Milo Fenn",
            union_affiliation=NON_UNION,
            compensation_model=UNION_SESSION_REUSE,
            session_fee_cents=100000,
            session_days=2,
        ),
        headers=LINE_PRODUCER,
    )

    validate_error(bought_out_union, ApiErrorId.ERR_TALENT_COMP_MODEL_INVALID)
    validate_error(reused_non_union, ApiErrorId.ERR_TALENT_COMP_MODEL_INVALID)
    assert_empty_listing(
        api.list_project_talent_engagements(project["id"], headers=LINE_PRODUCER)
    )
    assert_ledgers(read_project(api, project["id"]), provisional_cents=0, committed_cents=0)


def test_the_certificate_scope_rule_inverts_with_the_certificate_type(api):
    """One filing form, two opposite requirements, and one error for both mistakes.

    PRD §3.5: "A `FILM_PERMIT` covers exactly one shooting day and must carry a
    `shoot_day_id`, and that shoot day must belong to the project named in the filing; a
    permit that omits the identifier or points at a day of a different project is refused
    with `ERR_CERT_SCOPE_MISMATCH`."

    PRD §3.5: "A `LIABILITY_COI` covers the whole project and must omit `shoot_day_id`
    entirely; supplying one is the same violation and the same error."

    PRD §2.7: "A compliance certificate's `fee_cents` never enters either figure."

    Design: Corner/validations/certificate_scope_rule_is_conditional_on_cert_type
    """
    project, _deliverable = _scoped_project(
        api,
        client_name="Petrel Marine",
        campaign_title="Slipway",
        creative_brief_summary="Documentary short shot inside a working boatyard.",
        category=CATEGORY_CREW,
        description="Boatyard crew week",
        unit_rate_cents=2000000,
    )
    location = _venue(api, "Petrel Slipway", "1 Dockside, Bath", "Bath Harbour Authority")
    day = _day_on(api, project["id"], location["id"])

    unscoped_permit = film_permit_payload(project["id"], day["id"])
    unscoped_permit.pop("shoot_day_id")
    overscoped_coi = liability_coi_payload(project["id"], shoot_day_id=day["id"])

    validate_error(
        api.create_compliance_cert(unscoped_permit, headers=COMPLIANCE_OFFICER),
        ApiErrorId.ERR_CERT_SCOPE_MISMATCH,
    )
    validate_error(
        api.create_compliance_cert(overscoped_coi, headers=COMPLIANCE_OFFICER),
        ApiErrorId.ERR_CERT_SCOPE_MISMATCH,
    )

    permit = file_permit(
        api, project["id"], day["id"], carrier_or_authority=location["permit_authority"]
    )
    coi = file_coi(api, project["id"], coverage_amount_cents=50000000)

    assert_cert_statuses(permit, CERT_SUBMITTED, CERT_SUBMITTED)
    assert_cert_statuses(coi, CERT_SUBMITTED, CERT_SUBMITTED)
    assert permit["shoot_day_id"] == day["id"], permit["shoot_day_id"]
    assert coi["shoot_day_id"] is None, coi["shoot_day_id"]
    assert_total_count(
        api.list_compliance_certs(headers=COMPLIANCE_OFFICER, project_id=project["id"]), 2
    )
    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        status=SHOOT_DAY_PLANNED,
        compliance_posture=POSTURE_BLOCKED,
    )
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=2000000, committed_cents=0
    )


def test_a_pickup_one_second_before_the_prep_window_is_refused(api):
    """Forty-eight hours of slack is exact, and the second before it buys nothing.

    PRD §3.6: "The rental must sit inside the prep and return windows around the day:
    `pickup_at` may be no earlier than the day's `call_time` minus 48 hours, and
    `return_at` must be later than `pickup_at` and no later than the day's `wrap_time`
    plus 48 hours."

    PRD §3.6: "A pickup or return outside those two days of slack is refused with
    `ERR_EQUIPMENT_WINDOW_OUT_OF_RANGE`."

    Design: Corner/validations/equipment_pickup_one_second_before_the_prep_window_rejected
    """
    project, _deliverable = _scoped_project(
        api,
        client_name="Ostrander Foods",
        campaign_title="Early Truck",
        creative_brief_summary="Recipe films shot across a single kitchen day.",
        category=CATEGORY_EQUIPMENT,
        description="Camera package hire",
        unit_rate_cents=200000,
    )
    location = _venue(
        api, "Ostrander Kitchen", "12 Larder Lane, Bristol", "Bristol City Film Office"
    )
    day = _day_on(api, project["id"], location["id"])

    too_early = api.create_equipment_reservation(
        equipment_reservation_payload(
            day["id"],
            vendor_name="Severn Grip",
            kit_label="Kitchen camera package",
            unit_count=1,
            daily_rate_cents=30000,
            pickup_at="2026-09-08T05:59:59Z",
            return_at="2026-09-11T12:00:00Z",
        ),
        headers=COORDINATOR,
    )

    validate_error(too_early, ApiErrorId.ERR_EQUIPMENT_WINDOW_OUT_OF_RANGE)
    assert_empty_listing(
        api.list_shoot_day_equipment_reservations(day["id"], headers=COORDINATOR)
    )
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=200000, committed_cents=0
    )
    assert_shoot_day_state(
        read_shoot_day(api, day["id"]), status=SHOOT_DAY_PLANNED, day_cost_cents=90000
    )


def test_a_scope_lock_missing_its_budget_line_is_refused_and_bumps_nothing(api):
    """Half a scope is no scope, and the refusal leaves the counter where it was.

    PRD §3.1: "It is permitted only from `DRAFT`, and it requires the project to carry at
    least one deliverable **and** at least one budget line; a project missing either, or
    both, is refused with `ERR_SCOPE_INCOMPLETE`."

    PRD §3.1: "Locking the scope increments the project's `version` and refreshes its
    `updated_at`, and it makes the scope commercially binding: from `SCOPED` onwards —
    that is, whenever the project's `status` is anything other than `DRAFT` — registering
    a further deliverable raises a change order with `trigger_reason`
    `DELIVERABLE_ADDED_AFTER_SCOPE_LOCK`, as described in §3.9."

    Design: Corner/validations/scope_lock_without_a_budget_line_rejected
    """
    project = _draft_project(
        api,
        client_name="Kestrel Analytics",
        campaign_title="Half Scope",
        creative_brief_summary="OLV explainer film registered before its budget exists.",
    )
    _olv_deliverable(api, project["id"], "Half Scope 60")
    before = read_project(api, project["id"])

    validate_error(
        api.lock_scope(project["id"], headers=LINE_PRODUCER), ApiErrorId.ERR_SCOPE_INCOMPLETE
    )

    still_draft = read_project(api, project["id"])
    assert_project_state(still_draft, status=PROJECT_DRAFT)
    assert_version_unchanged(before, still_draft)

    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Offline and online edit",
        quantity=1,
        unit_rate_cents=500000,
        markup_pct=0,
    )
    with_line = read_project(api, project["id"])
    locked = lock_scope(api, project["id"])

    assert_project_state(locked, status=PROJECT_SCOPED)
    assert_version_bumped(with_line, locked)
    assert_ledgers(locked, provisional_cents=500000, committed_cents=0)


def test_a_supersede_may_not_reach_into_another_deliverable(api):
    """A cut retires its own predecessor only, and the returned cut stays returned.

    PRD §3.8: "When `supersedes_version_id` is present it must reference a cut of the
    *same* deliverable, and that cut's `review_status` must be `CHANGES_REQUESTED`;
    anything else — a cut of a different deliverable, or a cut in the wrong review state —
    is refused with `ERR_VERSION_DELIVERABLE_MISMATCH`."

    PRD §3.8: "The retirement itself is a system cascade admitting `DRAFT → SUPERSEDED`
    and `CHANGES_REQUESTED → SUPERSEDED` on the referenced row, incrementing that row's
    `version` and refreshing its `updated_at`; because the referential check requires a
    `CHANGES_REQUESTED` target, that is the edge reachable through this API."

    Design: Corner/validations/supersedes_a_cut_belonging_to_another_deliverable_rejected
    """
    project = _draft_project(
        api,
        client_name="Verity Trust",
        campaign_title="Two Cuts",
        creative_brief_summary="One hero film and one cutdown delivered from one shoot.",
    )
    hero = _olv_deliverable(api, project["id"], "Two Cuts 60", target_duration_seconds=60)
    cutdown = _olv_deliverable(api, project["id"], "Two Cuts 30", target_duration_seconds=30)
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Edit and finish",
        quantity=1,
        unit_rate_cents=2000000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)

    sent = submitted_cut(api, hero["id"], cut_label="RC1 hero cut")
    returned = review_cut(
        api, sent["id"], DECISION_REQUEST_CHANGES, review_note="Trim the opening."
    )
    assert_version_axes(returned, review_status=REVIEW_CHANGES_REQUESTED)

    target = read_deliverable(api, cutdown["id"])
    refused = api.create_deliverable_version(
        cut_payload(
            cutdown["id"],
            target["version"],
            cut_label="v1 cutdown",
            duration_seconds=30,
            supersedes_version_id=returned["id"],
        ),
        headers=POST_SUPERVISOR,
    )

    validate_error(refused, ApiErrorId.ERR_VERSION_DELIVERABLE_MISMATCH)
    assert_version_axes(read_cut(api, returned["id"]), review_status=REVIEW_CHANGES_REQUESTED)
    assert_deliverable_state(
        read_deliverable(api, cutdown["id"]), status=DELIVERABLE_PENDING, version_count=0
    )
    assert_empty_listing(
        api.list_deliverable_versions(headers=POST_SUPERVISOR, deliverable_id=cutdown["id"])
    )


def test_a_page_window_outside_its_band_is_rejected_on_both_parameters(api):
    """One over the limit and one under the offset floor, with the band edge itself fine.

    PRD §2.3: "A `limit` outside the 1-to-100 band, or a negative `offset`, is rejected
    with `ERR_INVALID_PAGINATION` (HTTP 400); this pagination check is declared for the
    cut list, the shoot-day list, the compliance-certificate list and the crew-booking
    list, and the same 1-to-100 and non-negative rules are applied wherever pagination
    parameters are accepted."

    Design: Corner/validations/pagination_limit_above_one_hundred_rejected
    """
    _project, deliverable = _production_project(
        api,
        client_name="Ansel Rowe",
        campaign_title="Page Guard",
        creative_brief_summary="Single OLV film whose cut history is read page by page.",
        category=CATEGORY_POST,
        description="Post finishing",
        unit_rate_cents=2000000,
    )
    upload_next_cut(api, deliverable["id"], cut_label="v1 assembly")

    validate_error(
        api.list_deliverable_versions(headers=POST_SUPERVISOR, limit=250),
        ApiErrorId.ERR_INVALID_PAGINATION,
    )

    at_the_band = api.list_deliverable_versions(headers=POST_SUPERVISOR, limit=MAX_LIMIT)
    rows, meta = validate_paginated(at_the_band)
    assert meta["limit"] == MAX_LIMIT, meta["limit"]
    assert meta["total_count"] == 1, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]
    assert len(rows) == 1, len(rows)
    assert rows[0]["deliverable_id"] == deliverable["id"], rows[0]["deliverable_id"]

    validate_error(
        api.list_deliverable_versions(headers=POST_SUPERVISOR, offset=-1),
        ApiErrorId.ERR_INVALID_PAGINATION,
    )


def test_a_submission_passes_while_a_contracted_round_remains(api):
    """The entitlement precondition is a strict inequality, and the first lap clears it.

    PRD §3.8: "Six conditions must hold: the cut's `review_status` is `DRAFT`; its
    `technical_status` is `QC_PASSED` — the cross-axis guard, with both `PENDING_QC` and
    `QC_FAILED` refused as `ERR_VERSION_QC_NOT_PASSED`; the parent deliverable is
    `PENDING` or `CHANGES_REQUESTED`; the project is `IN_PRODUCTION` or `IN_POST`; the
    project's `review_gate` is `OPEN`, or the submission is frozen with
    `ERR_CHANGE_ORDER_PENDING`; and the deliverable's `consumed_review_rounds` is strictly
    less than its `round_entitlement`, or the submission is refused with
    `ERR_REVISION_ROUNDS_EXHAUSTED`."

    PRD §3.8: "Submission stamps `submitted_by_user_id` with the acting `X-User-ID` and
    `submitted_at` with the logical clock, then bubbles up: the deliverable advances
    `PENDING → IN_REVIEW` on a first cut, or `CHANGES_REQUESTED → IN_REVIEW` on a later
    one, incrementing the deliverable's `version` and refreshing its `updated_at`."

    Design: Corner/validations/version_submit_passes_while_a_contracted_round_remains
    """
    project, deliverable = _production_project(
        api,
        client_name="Marlowe Bank",
        campaign_title="First Round",
        creative_brief_summary="OLV brand film going out for its first client round.",
        category=CATEGORY_POST,
        description="Post finishing",
        unit_rate_cents=2000000,
    )
    cut = passed_cut(api, deliverable["id"], cut_label="RC1 client cut")

    sent = submit_cut(api, cut["id"])

    assert_version_axes(
        sent,
        review_status=REVIEW_SUBMITTED,
        technical_status=TECHNICAL_QC_PASSED,
        round_index=1,
    )
    assert sent["submitted_by_user_id"] == USER_POST_1, sent["submitted_by_user_id"]
    assert_at_default_clock(sent["submitted_at"])
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_IN_REVIEW,
        version_count=1,
        consumed_review_rounds=0,
        round_entitlement=2,
    )
    assert_project_state(
        read_project(api, project["id"]),
        status=PROJECT_IN_PRODUCTION,
        review_gate=REVIEW_GATE_OPEN,
        round_entitlement_balance=2,
    )


def test_insurance_one_cent_below_the_venue_floor_blocks_the_lock(api):
    """The venue's floor is a minimum, so the cent that closes the gap unblocks the day.

    PRD §3.5: "The insurance test passes when there exists a certificate on the same
    `project_id`, of `cert_type` `LIABILITY_COI`, with `status` `ISSUED`, whose
    `coverage_amount_cents` is at least the location's `insurance_minimum_cents`, whose
    `effective_from` is at or before `call_time`, whose `effective_to` is at or after
    `wrap_time`, and whose `effective_to` is at or after the logical clock."

    PRD §3.4: "A missing, unissued, expired or badly windowed film permit reports
    `ERR_PERMIT_WINDOW_MISMATCH`; insurance that is missing, unissued, expired, badly
    windowed or below the venue's `insurance_minimum_cents` reports
    `ERR_INSUFFICIENT_COI_COVERAGE`."

    PRD §3.4: "Confirmation recomputes the posture and sets the venue's `scouting_status`
    to `CONFIRMED`."

    Design: Corner/validations/coi_one_cent_below_the_location_minimum_blocks_confirmation
    """
    project, _deliverable = _production_project(
        api,
        client_name="Alder Foundry",
        campaign_title="One Cent Short",
        creative_brief_summary="Process film shot on a working foundry floor.",
        category=CATEGORY_CREW,
        description="Foundry crew day",
        unit_rate_cents=2000000,
    )
    location = _venue(
        api,
        "Alder Foundry Floor",
        "8 Furnace Row, Sheffield",
        "Sheffield City Council",
        insurance_minimum_cents=50000000,
    )
    day = _day_on(api, project["id"], location["id"])
    issued_permit(
        api, project["id"], day["id"], carrier_or_authority=location["permit_authority"]
    )
    issued_coi(
        api, project["id"], coverage_amount_cents=49999999, reference_code="COI-SHORT-1"
    )

    validate_error(
        api.confirm_shoot_day(day["id"], headers=COORDINATOR),
        ApiErrorId.ERR_INSUFFICIENT_COI_COVERAGE,
    )

    still_planned = read_shoot_day(api, day["id"])
    assert_shoot_day_state(
        still_planned,
        status=SHOOT_DAY_PLANNED,
        compliance_posture=POSTURE_BLOCKED,
        call_sheet_status=CALL_SHEET_DRAFT,
    )

    issued_coi(
        api, project["id"], coverage_amount_cents=50000000, reference_code="COI-EXACT-1"
    )
    confirmed = confirm_shoot_day(api, day["id"])

    assert_shoot_day_state(
        confirmed,
        status=SHOOT_DAY_CONFIRMED,
        compliance_posture=POSTURE_RESTRICTED,
        confirmed_crew_count=0,
    )
    venue = ok_row(api.get_location(location["id"], headers=COORDINATOR))
    assert venue["scouting_status"] == LOCATION_CONFIRMED, venue["scouting_status"]


def test_a_call_sheet_one_second_inside_the_lead_window_is_refused(api):
    """Twelve hours before call is still in time; one second later is not.

    PRD §3.7: "Finally the lead-time rule: a call sheet may only go out while the logical
    clock is at or before the day's `call_time` minus twelve hours, so publishing inside
    the last half-day before call is refused with `ERR_CALL_SHEET_WINDOW_CLOSED`."

    PRD §3.7: "When all of it passes, `call_sheet_status` advances `DRAFT → PUBLISHED` and
    `call_sheet_published_at` is stamped with the logical clock."

    Design: Corner/validations/call_sheet_published_inside_the_twelve_hour_lead_window_rejected
    """
    project, _deliverable = _production_project(
        api,
        client_name="Bellwether Cider",
        campaign_title="Lead Window",
        creative_brief_summary="Harvest film shot across one orchard day.",
        category=CATEGORY_CREW,
        description="Orchard crew day",
        unit_rate_cents=2000000,
    )
    location = _venue(
        api, "Bellwether Orchard", "3 Press House Lane, Hereford", "Herefordshire Council"
    )
    day = _day_on(api, project["id"], location["id"])
    issued_permit(
        api, project["id"], day["id"], carrier_or_authority=location["permit_authority"]
    )
    issued_coi(api, project["id"], coverage_amount_cents=50000000)
    day = confirm_shoot_day(api, day["id"])

    for full_name, department, department_role in (
        ("Nils Aubert", DEPT_CAMERA, "1st AC"),
        ("Ida Rourke", DEPT_GRIP_ELECTRIC, "Gaffer"),
        ("Theo Vance", DEPT_SOUND, "Sound recordist"),
    ):
        member = add_crew_member(
            api, full_name=full_name, department=department, hourly_rate_cents=5000
        )
        booking = book_crew(
            api,
            day["id"],
            member["id"],
            department_role=department_role,
            call_time=day["call_time"],
            wrap_time=day["wrap_time"],
        )
        confirm_booking(api, booking["id"])

    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        status=SHOOT_DAY_CONFIRMED,
        compliance_posture=POSTURE_OPEN,
        confirmed_crew_count=3,
        call_sheet_status=CALL_SHEET_DRAFT,
    )

    set_clock(api, "2026-09-09T18:00:01Z")
    validate_error(
        api.publish_call_sheet(day["id"], headers=COORDINATOR),
        ApiErrorId.ERR_CALL_SHEET_WINDOW_CLOSED,
    )
    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        status=SHOOT_DAY_CONFIRMED,
        call_sheet_status=CALL_SHEET_DRAFT,
    )

    set_clock(api, "2026-09-09T18:00:00Z")
    published = publish_call_sheet(api, day["id"])

    assert_shoot_day_state(
        published, status=SHOOT_DAY_CONFIRMED, call_sheet_status=CALL_SHEET_PUBLISHED
    )
    assert_instant_equals(published["call_sheet_published_at"], "2026-09-09T18:00:00Z")
