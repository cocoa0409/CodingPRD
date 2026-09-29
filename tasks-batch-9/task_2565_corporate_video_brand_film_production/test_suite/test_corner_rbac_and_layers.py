"""Who may act, whose rows may be read, and how fresh a single read already is.

The first five cases walk the duty lines of §2.1 — the client's exclusive sign-off, the
producer's exclusive purse, the two peer specialists who cannot reach into each other's
endpoints, the one entity-backed role that sees only its own rows, and the identity
comparison that stops a supervisor approving his own cut — and each of them ends with the
authorised caller succeeding at the very same call. The last four watch the layers that
cut across every entity: the one optimistically controlled write refusing a stale parent
version and accepting a fresh one, a derived count reconciling after a create and after a
cancel, and a confirm whose consequences are already visible in the next read.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ARCHIVE_NOT_PACKAGED,
    BOOKING_CONFIRMED,
    BOOKING_HELD,
    CALL_SHEET_DRAFT,
    CATEGORY_CREW,
    CATEGORY_LOCATION,
    CATEGORY_POST,
    CERT_SUBMITTED,
    CLIENT_APPROVER,
    COMPLIANCE_OFFICER,
    COORDINATOR,
    DECISION_APPROVE,
    DECISION_ISSUE,
    DELIVERABLE_APPROVED,
    DELIVERABLE_PENDING,
    DEPT_CAMERA,
    DEPT_SOUND,
    LINE_PRODUCER,
    LOCATION_HOLD,
    LOCATION_SCOUTED,
    POSTURE_BLOCKED,
    POST_SUPERVISOR,
    PROJECT_DELIVERED,
    PROJECT_IN_PRODUCTION,
    PROJECT_SCOPED,
    REVIEW_APPROVED,
    REVIEW_DRAFT,
    REVIEW_SUBMITTED,
    ROLE_CLIENT_APPROVER,
    SHOOT_DAY_CANCELLED,
    SHOOT_DAY_PLANNED,
    TECHNICAL_PENDING_QC,
    TECHNICAL_QC_PASSED,
    USER_CLIENT_1,
    USER_POST_1,
    ApiErrorId,
    add_budget_line,
    add_crew_member,
    add_deliverable,
    approve_budget,
    approve_budget_payload,
    assert_deliverable_state,
    assert_empty_listing,
    assert_ledgers,
    assert_project_state,
    assert_shoot_day_state,
    assert_total_count,
    assert_variance_is_zero_while_unapproved,
    assert_version_axes,
    book_crew,
    budget_line_payload,
    build_user_headers,
    cancel_shoot_day,
    cert_decision_payload,
    confirm_booking,
    cut_payload,
    file_permit,
    ids_of,
    lock_scope,
    make_crew_member_headers,
    ok_row,
    open_project,
    read_booking,
    read_cert,
    read_cut,
    read_deliverable,
    read_project,
    read_shoot_day,
    register_location,
    review_cut,
    review_decision_payload,
    schedule_shoot_day,
    submitted_cut,
    upload_cut,
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


def _scoped(api, client_name, campaign_title, brief, category, description, unit_rate_cents,
            quantity=1):
    """The same project locked, with one `PLANNED` line on the top sheet."""
    project, deliverable = _project_with_one_olv_deliverable(
        api, client_name, campaign_title, brief
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
    return lock_scope(api, project["id"]), deliverable


def _in_production(api, client_name, campaign_title, brief, category, description,
                   unit_rate_cents):
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
    location = _venue(api, venue_name, venue_address, permit_authority)
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


def _read_location(api, location_id):
    """A live venue read, which recomputes the two derived scheduling columns."""
    return ok_row(api.get_location(location_id, headers=COORDINATOR))


def _venue(api, name, address, permit_authority, stage_count=1):
    """A scouted venue charging 90,000 cents a day and demanding 500,000.00 of cover."""
    return register_location(
        api,
        name=name,
        address=address,
        stage_count=stage_count,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority=permit_authority,
    )


def test_only_the_client_may_sign_off_the_budget(api):
    """The coordinator's sign-off is refused, and the approver's identical call is not.

    PRD §2.1: "If the headers are well formed but the acting role is not listed among the
    authorized roles of the endpoint being called (see the table in §4), the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.12: "Priority 2: **Role authorization** — the acting role appears in the target
    endpoint's authorized-role list (`ERR_ROLE_NOT_PERMITTED`)."

    Design: Corner/rbac/coordinator_cannot_approve_the_budget_returns_4xx
    """
    project, _deliverable = _scoped(
        api,
        "Nardin Group",
        "Wrong Hands",
        "Brand film where the coordinator tries to approve the budget.",
        CATEGORY_POST,
        "Edit and finish",
        2000000,
    )

    validate_error(
        api.approve_budget(
            project["id"], approve_budget_payload(2000000), headers=COORDINATOR
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )

    refused = read_project(api, project["id"])
    assert_project_state(refused, status=PROJECT_SCOPED)
    assert refused["approved_budget_cents"] is None, refused["approved_budget_cents"]

    signed = ok_row(
        api.approve_budget(
            project["id"], approve_budget_payload(2000000), headers=CLIENT_APPROVER
        )
    )
    assert_project_state(signed, status=PROJECT_IN_PRODUCTION)
    assert_ledgers(signed, approved_cents=2000000, variance_cents=0)


def test_only_the_line_producer_may_write_a_budget_line(api):
    """A perfectly valid line from the wrong hand leaves the top sheet empty.

    PRD §2.1: "A `LineProducer` owns the money — opening the project, building the budget,
    casting talent, and voiding an approved change order."

    PRD §2.12: "Priority 2: **Role authorization** — the acting role appears in the target
    endpoint's authorized-role list (`ERR_ROLE_NOT_PERMITTED`)."

    Design: Corner/rbac/post_supervisor_cannot_write_a_budget_line_returns_4xx
    """
    project, _deliverable = _project_with_one_olv_deliverable(
        api,
        "Nardin Group",
        "Post Overreach",
        "Brand film where post tries to budget.",
    )

    validate_error(
        api.create_budget_line(
            budget_line_payload(
                project["id"],
                category=CATEGORY_POST,
                description="Extra finishing days",
                quantity=1,
                unit_rate_cents=400000,
                markup_pct=0,
            ),
            headers=POST_SUPERVISOR,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )

    assert_empty_listing(api.list_project_budget_lines(project["id"], headers=LINE_PRODUCER))
    assert_ledgers(read_project(api, project["id"]), provisional_cents=0, committed_cents=0)


def test_the_two_peer_specialists_cannot_reach_into_each_others_endpoints(api):
    """The officer who filed the paperwork still may not publish the sheet that needs it.

    PRD §2.1: "A `ProductionCoordinator` runs the physical production — locations, shoot
    days, call sheets, crew bookings and equipment rentals."

    PRD §2.1: "A `ComplianceOfficer` files film permits and certificates of insurance and
    records the issuing authority's or carrier's decision."

    PRD §2.12: "Priority 2: **Role authorization** — the acting role appears in the target
    endpoint's authorized-role list (`ERR_ROLE_NOT_PERMITTED`)."

    Design: Corner/rbac/compliance_officer_cannot_publish_a_call_sheet_returns_4xx
    """
    project, _deliverable = _scoped(
        api,
        "Marden Freight",
        "Peer Lines",
        "Brand film exercising the peer role boundary.",
        CATEGORY_CREW,
        "Core unit",
        2000000,
    )
    location = _venue(api, "Marden Yard", "6 Freight Way, Leeds", "Leeds Film Office")
    day = schedule_shoot_day(api, project["id"], location["id"])
    permit = file_permit(
        api,
        project["id"],
        day["id"],
        carrier_or_authority="Leeds Film Office",
        reference_code="PERMIT-MF-1",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-30T00:00:00Z",
        fee_cents=40000,
    )

    validate_error(
        api.publish_call_sheet(day["id"], headers=COMPLIANCE_OFFICER),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.compliance_cert_decision(
            permit["id"],
            cert_decision_payload(DECISION_ISSUE, "Coordinator trying to issue a permit."),
            headers=COORDINATOR,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )

    assert_shoot_day_state(
        read_shoot_day(api, day["id"]),
        status=SHOOT_DAY_PLANNED,
        call_sheet_status=CALL_SHEET_DRAFT,
    )
    filed = read_cert(api, permit["id"])
    assert filed["status"] == CERT_SUBMITTED, filed["status"]
    assert filed["decided_at"] is None, filed["decided_at"]
    assert filed["decision_note"] is None, filed["decision_note"]

    # Reading is shared even where writing is not.
    ok_row(api.get_shoot_day(day["id"], headers=COMPLIANCE_OFFICER))
    ok_row(api.get_shoot_day(day["id"], headers=COORDINATOR))


def test_a_crew_member_sees_its_own_bookings_and_no_others(api):
    """A colleague's row, and the unfiltered table, are both out of reach.

    PRD §2.1: "A `CrewMember` is a booked crew person who may read only its own bookings
    plus the shoot days and roster entry those bookings reference, and may write nothing."

    PRD §2.1: "Consequently a `CrewMember` caller reading a single booking whose
    `crew_member_id` differs from its own `X-User-ID`, or listing bookings without supplying
    a `crew_member_id` filter equal to its own `X-User-ID`, is refused with
    `ERR_CREW_SCOPE_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/crew_member_cannot_read_another_members_bookings_returns_4xx
    """
    project, _deliverable = _scoped(
        api,
        "Ilbert Cheese",
        "Own Rows",
        "Brand film exercising crew-scoped reads.",
        CATEGORY_CREW,
        "Core unit",
        2000000,
    )
    location = _venue(api, "Ilbert Creamery", "11 Curd Lane, Waterloo", "Waterloo Film Office")
    day = schedule_shoot_day(api, project["id"], location["id"])
    operator = add_crew_member(
        api, full_name="Anke Rios", department=DEPT_CAMERA, hourly_rate_cents=5000
    )
    mixer = add_crew_member(
        api, full_name="Bo Halvorsen", department=DEPT_SOUND, hourly_rate_cents=5000
    )
    own_booking = book_crew(api, day["id"], operator["id"], department_role="Operator")
    other_booking = book_crew(api, day["id"], mixer["id"], department_role="Mixer")

    acting_as_operator = make_crew_member_headers(operator["id"])

    validate_error(
        api.list_crew_bookings(
            headers=acting_as_operator, crew_member_id=mixer["id"], limit=10, offset=0
        ),
        ApiErrorId.ERR_CREW_SCOPE_FORBIDDEN,
    )
    validate_error(
        api.list_crew_bookings(headers=acting_as_operator, limit=10, offset=0),
        ApiErrorId.ERR_CREW_SCOPE_FORBIDDEN,
    )
    validate_error(
        api.get_crew_booking(other_booking["id"], headers=acting_as_operator),
        ApiErrorId.ERR_CREW_SCOPE_FORBIDDEN,
    )

    mine = assert_total_count(
        api.list_crew_bookings(
            headers=acting_as_operator, crew_member_id=operator["id"], limit=10, offset=0
        ),
        1,
    )
    assert ids_of(mine) == [own_booking["id"]], ids_of(mine)
    assert mine[0]["status"] == BOOKING_HELD, mine[0]["status"]

    # The shoot day and roster entry those bookings reference stay readable.
    ok_row(api.get_shoot_day(day["id"], headers=acting_as_operator))
    ok_row(api.get_crew_member(operator["id"], headers=acting_as_operator))


def test_the_uploader_of_a_cut_cannot_record_its_own_review_decision(api):
    """The comparison is on the acting user id, so the right role with the wrong id fails.

    PRD §2.1: "Segregation of duties is enforced on `X-User-ID` in three places, all of them
    yielding `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD §3.8: "It requires the cut's `review_status` to be `SUBMITTED`, requires the project
    to be `IN_PRODUCTION` or `IN_POST`, and requires the acting `X-User-ID` to differ from
    the cut's `submitted_by_user_id` — a supervisor may not sign off their own cut, and an
    attempt reports `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_uploader_of_a_cut_cannot_record_its_review_decision
    """
    project, deliverable = _in_post(
        api,
        "Oakhurst Wine",
        "Same Hand",
        "Brand film where the uploader tries to approve his own cut.",
        CATEGORY_POST,
        "Edit and finish",
        2000000,
        "Oakhurst Cellar",
        "9 Vine Row, Oakhurst",
        "Oakhurst Film Office",
    )
    cut = submitted_cut(api, deliverable["id"], cut_label="v1", file_size_gb=9.0)
    assert cut["submitted_by_user_id"] == USER_POST_1, cut["submitted_by_user_id"]

    supervisor_wearing_the_clients_hat = build_user_headers(USER_POST_1, ROLE_CLIENT_APPROVER)
    validate_error(
        api.review_decision(
            cut["id"],
            review_decision_payload(DECISION_APPROVE, "Approving my own cut."),
            headers=supervisor_wearing_the_clients_hat,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    untouched = read_cut(api, cut["id"])
    assert_version_axes(
        untouched, review_status=REVIEW_SUBMITTED, technical_status=TECHNICAL_QC_PASSED
    )
    assert untouched["reviewed_by_user_id"] is None, untouched["reviewed_by_user_id"]
    assert untouched["decided_at"] is None, untouched["decided_at"]

    decided = review_cut(api, cut["id"], DECISION_APPROVE, review_note="Approved by the client.")
    assert_version_axes(decided, review_status=REVIEW_APPROVED)
    assert decided["reviewed_by_user_id"] == USER_CLIENT_1, decided["reviewed_by_user_id"]
    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]), status=DELIVERABLE_APPROVED
    )
    assert_project_state(
        read_project(api, project["id"]),
        status=PROJECT_DELIVERED,
        archive_status=ARCHIVE_NOT_PACKAGED,
    )


def test_a_second_cut_presenting_the_consumed_parent_version_is_refused(api):
    """The first upload spent that number, so replaying it is a stale read, not a race.

    PRD §2.10: "The server compares it against the parent `Deliverable.version` stored at
    the moment the create is processed; if the two differ, the create is rejected with
    `ERR_STALE_DELIVERABLE_VERSION` (HTTP 412)."

    PRD §3.8: "An accepted upload increments the parent deliverable's `version` by one —
    which is what the next uploader must present as `expected_deliverable_version` — and
    writes the new row with `review_status` `DRAFT`, `technical_status` `PENDING_QC`,
    `qc_failure_reasons` as an empty array, and `submitted_by_user_id`,
    `reviewed_by_user_id`, `submitted_at` and `decided_at` all null."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_deliverable_version_returns_412
    """
    _project, deliverable = _in_production(
        api,
        "Redmarsh Bank",
        "Stale Read",
        "Brand film uploaded twice from one stale read.",
        CATEGORY_POST,
        "Edit and finish",
        2000000,
    )
    last_observed = deliverable["version"]
    first = upload_cut(api, deliverable["id"], last_observed, cut_label="v1", file_size_gb=9.0)

    validate_error(
        api.create_deliverable_version(
            cut_payload(
                deliverable["id"],
                last_observed,
                cut_label="v2 from a stale read",
                file_size_gb=9.2,
            ),
            headers=POST_SUPERVISOR,
        ),
        ApiErrorId.ERR_STALE_DELIVERABLE_VERSION,
    )

    assert_deliverable_state(
        read_deliverable(api, deliverable["id"]),
        status=DELIVERABLE_PENDING,
        version_count=1,
    )
    assert_total_count(
        api.list_deliverable_versions(headers=POST_SUPERVISOR, deliverable_id=deliverable["id"]),
        1,
    )
    assert_version_axes(
        read_cut(api, first["id"]),
        review_status=REVIEW_DRAFT,
        technical_status=TECHNICAL_PENDING_QC,
    )


def test_re_reading_the_parent_yields_the_number_the_retry_needs(api):
    """The advanced version is exactly one higher, and the retry that presents it lands.

    PRD §2.10: "That request must carry `expected_deliverable_version`, a non-optional
    integer field holding the client's last observed `version` of the parent deliverable."

    PRD §3.8: "The deliverable's `version_count` is recomputed as the number of cuts
    carrying its identifier."

    Design: Corner/cross_cutting_complexity_layers/a_fresh_expected_deliverable_version_succeeds_and_bumps_the_parent
    """
    _project, deliverable = _in_production(
        api,
        "Redmarsh Bank",
        "Fresh Read",
        "Brand film uploaded twice with a re-read in between.",
        CATEGORY_POST,
        "Edit and finish",
        2000000,
    )
    last_observed = deliverable["version"]
    first = upload_cut(api, deliverable["id"], last_observed, cut_label="v1", file_size_gb=9.0)

    re_read = read_deliverable(api, deliverable["id"])
    assert re_read["version"] == last_observed + 1, re_read["version"]

    second = upload_cut(
        api,
        deliverable["id"],
        re_read["version"],
        cut_label="v2 from a fresh read",
        file_size_gb=9.2,
    )
    assert_version_axes(
        second, review_status=REVIEW_DRAFT, technical_status=TECHNICAL_PENDING_QC, round_index=1
    )

    after_both = read_deliverable(api, deliverable["id"])
    assert_deliverable_state(after_both, status=DELIVERABLE_PENDING, version_count=2)
    assert after_both["version"] == re_read["version"] + 1, after_both["version"]
    assert_version_axes(
        read_cut(api, first["id"]),
        review_status=REVIEW_DRAFT,
        technical_status=TECHNICAL_PENDING_QC,
    )


def test_the_venues_day_count_tracks_every_schedule_and_every_cancellation(api):
    """Zero, one, two, then back to one — and the hold survives, because a day remains.

    PRD §3.4: "A fresh location reports `scouting_status` `SCOUTED` and
    `scheduled_shoot_day_count` 0."

    PRD §3.4: "`scheduled_shoot_day_count` is the number of shoot days at the location whose
    `status` is `PLANNED` or `CONFIRMED`. `scouting_status` is `CONFIRMED` when at least one
    shoot day there is `CONFIRMED`; it is `HOLD` when at least one is `PLANNED` and none is
    `CONFIRMED`; and it is `SCOUTED` in every other case, including a venue with no days at
    all and a venue whose only days have wrapped or been cancelled."

    PRD §3.7: "Also in parallel, the venue's `scheduled_shoot_day_count` and
    `scouting_status` are recomputed — a cancelled day no longer holds a stage, and a venue
    whose only confirmed day was just cancelled falls back to `HOLD` or `SCOUTED`."

    Design: Corner/cross_cutting_complexity_layers/derived_shoot_day_count_reconciles_after_create_and_after_cancel
    """
    project, _deliverable = _scoped(
        api,
        "Vantry Motors",
        "Two Days",
        "Brand film shot over two days on one stage.",
        CATEGORY_LOCATION,
        "Stage fees",
        90000,
        quantity=2,
    )
    location = _venue(
        api, "Vantry Assembly Hall", "20 Axle Road, Flint", "Flint Film Office", stage_count=2
    )

    unscheduled = _read_location(api, location["id"])
    assert unscheduled["scheduled_shoot_day_count"] == 0, unscheduled["scheduled_shoot_day_count"]
    assert unscheduled["scouting_status"] == LOCATION_SCOUTED, unscheduled["scouting_status"]

    first_day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    after_one = _read_location(api, location["id"])
    assert after_one["scheduled_shoot_day_count"] == 1, after_one["scheduled_shoot_day_count"]
    assert after_one["scouting_status"] == LOCATION_HOLD, after_one["scouting_status"]

    second_day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-11T06:00:00Z",
        wrap_time="2026-09-11T16:00:00Z",
    )
    after_two = _read_location(api, location["id"])
    assert after_two["scheduled_shoot_day_count"] == 2, after_two["scheduled_shoot_day_count"]
    assert after_two["scouting_status"] == LOCATION_HOLD, after_two["scouting_status"]

    cancel_shoot_day(
        api,
        first_day["id"],
        cancellation_reason="Client moved the hero scene to day two.",
    )

    after_cancel = _read_location(api, location["id"])
    assert after_cancel["scheduled_shoot_day_count"] == 1, (
        after_cancel["scheduled_shoot_day_count"]
    )
    assert after_cancel["scouting_status"] == LOCATION_HOLD, after_cancel["scouting_status"]
    assert_shoot_day_state(read_shoot_day(api, first_day["id"]), status=SHOOT_DAY_CANCELLED)
    assert_shoot_day_state(read_shoot_day(api, second_day["id"]), status=SHOOT_DAY_PLANNED)
    assert_project_state(read_project(api, project["id"]), status=PROJECT_SCOPED)


def test_one_confirmation_is_already_visible_in_the_next_read_of_every_aggregate(api):
    """The confirm response, the project read and the day read agree with no settling.

    PRD §2.9: "Derived columns — a project's ledger figures, `budget_variance_cents`,
    `round_entitlement_balance`, `review_gate`, `archive_status` and `retention_expires_at`;
    a deliverable's `consumed_review_rounds`, `granted_extra_rounds`, `round_entitlement` and
    `version_count`; a location's `scheduled_shoot_day_count` and `scouting_status`; a shoot
    day's `compliance_posture`, `confirmed_crew_count` and `day_cost_cents`; a certificate's
    `effective_status` — are recomputed from live data before being returned by a read, so a
    read never serves a stale derivation."

    PRD §3.6: "The ledger syncs at that moment: the project's `committed_cost_cents`
    increases by the booking's `cost_cents` and `budget_variance_cents` is recomputed."

    PRD §3.6: "A day's `day_cost_cents` is a display-only total, recomputed on every
    shoot-day read and after any booking or reservation status change on that day: it is the
    venue's `daily_fee_cents` plus the `cost_cents` of every crew booking on the day whose
    `status` is `CONFIRMED` or `COMPLETED` plus the `total_cost_cents` of every reservation
    on the day whose `status` is `RESERVED` or `RETURNED`."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
    """
    project, _deliverable = _scoped(
        api,
        "Callow Springs",
        "Read Your Writes",
        "Brand film verifying immediate consistency.",
        CATEGORY_CREW,
        "Core unit",
        200000,
    )
    location = _venue(
        api, "Callow Spring House", "8 Well Road, Saratoga", "Saratoga Film Office"
    )
    day = schedule_shoot_day(api, project["id"], location["id"])
    member = add_crew_member(
        api, full_name="Wren Delacroix", department=DEPT_CAMERA, hourly_rate_cents=5000
    )
    booking = book_crew(api, day["id"], member["id"], department_role="Operator")
    assert booking["status"] == BOOKING_HELD, booking["status"]

    confirmed = confirm_booking(api, booking["id"])

    # The write's own response already carries the frozen cost and the new status.
    assert confirmed["status"] == BOOKING_CONFIRMED, confirmed["status"]
    assert confirmed["cost_cents"] == 50000, confirmed["cost_cents"]

    straight_after = read_project(api, project["id"])
    assert_ledgers(straight_after, provisional_cents=250000, committed_cents=50000)
    assert_variance_is_zero_while_unapproved(straight_after)

    day_after = read_shoot_day(api, day["id"])
    assert_shoot_day_state(
        day_after,
        status=SHOOT_DAY_PLANNED,
        compliance_posture=POSTURE_BLOCKED,
        confirmed_crew_count=1,
        day_cost_cents=140000,
    )
    assert read_booking(api, booking["id"])["cost_cents"] == 50000
