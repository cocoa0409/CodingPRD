"""Opening a bond release, publishing its notice, and public participation."""
from test_helpers import (
    BOND_SPECIALIST_DECIDER,
    PERMIT_REVIEWER,
    ApiErrorId,
    api_client as api,
    assert_money,
    assert_release_application,
    chain_issued,
    create_release_application_payload,
    file_public_comment,
    file_release_application,
    order_cessation,
    publish_release_notice,
    refresh_application,
    refresh_notice,
    refresh_permit,
    set_clock,
    setup_bond_deficient_by_expansion,
    setup_violation_notice,
    validate_error,
    validate_paginated,
    validate_success,
)

BLUE_STEM_OPERATOR = {
    "legal_name": "Blue Stem Coal Partners",
    "tangible_net_worth": 24000000.00,
    "fixed_assets_in_state": 12000000.00,
    "total_liabilities": 8500000.00,
    "net_income_prior_year": 1600000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
BLUE_STEM_SITE = {"name": "Blue Stem Ridge", "county": "Perry", "total_acres": 480.00}

IMMINENT_HARM_NOTICE = {
    "violation_class": "IMMINENT_HARM",
    "severity_points": 30,
    "negligence_points": 25,
    "duration_points": 15,
    "abatement_days": 7,
}


def _blue_stem_two_applications():
    """One PHASE_I application published on 2026-08-01, one PHASE_II still SUBMITTED."""
    ctx = chain_issued(
        operator_overrides=BLUE_STEM_OPERATOR,
        site_overrides=BLUE_STEM_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
    )
    first = file_release_application(ctx, phase="PHASE_I", acres_requested=30.00)
    second = file_release_application(ctx, phase="PHASE_II", acres_requested=30.00)
    ctx["first"] = publish_release_notice(first["id"], BOND_SPECIALIST_DECIDER)
    ctx["second"] = second
    return ctx


def test_a_notice_window_opening_inside_the_fifteen_day_buffer_is_refused():
    """The buffer is treated as a closed interval — a new window beginning exactly
    fifteen days after a prior window's end is permitted, while one beginning a
    single day earlier is refused with `ERR_NOTICE_WINDOW_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/public_notice_windows_enforce_fifteen_day_gap_buffer
    """
    ctx = _blue_stem_two_applications()
    first = ctx["first"]
    assert first["notice_start_date"].startswith("2026-08-01"), (
        f"the window opens on the clock's date, got {first['notice_start_date']}"
    )
    assert first["notice_end_date"].startswith("2026-08-31"), (
        f"thirty days after 2026-08-01, got {first['notice_end_date']}"
    )

    # 2026-09-14 is fourteen days after the 2026-08-31 end, one day short.
    set_clock("2026-09-14T00:00:00Z")
    response = api.publish_notice(ctx["second"]["id"], BOND_SPECIALIST_DECIDER)
    validate_error(response, ApiErrorId.ERR_NOTICE_WINDOW_CONFLICT, 409)

    blocked = refresh_application(ctx["second"]["id"])
    assert blocked["status"] == "SUBMITTED", "the refused publish left it SUBMITTED"
    assert blocked["notice_start_date"] is None, "no window was opened"
    assert blocked["notice_end_date"] is None, "no window was opened"


def test_a_notice_window_opening_exactly_fifteen_days_later_is_admitted():
    """It also enforces a temporal-exclusion rule over the permit's notice windows
    at priority 15: the new window, running from the logical clock's current
    instant through thirty days later, must not begin within fifteen days of the
    `notice_end_date` of any *other* application on the same permit whose status
    is `PUBLIC_NOTICE` or `APPROVED`.

    Design: Difficulty/resource_temporal_overlap/public_notice_windows_enforce_fifteen_day_gap_buffer
    """
    ctx = _blue_stem_two_applications()

    set_clock("2026-09-14T00:00:00Z")
    validate_error(
        api.publish_notice(ctx["second"]["id"], BOND_SPECIALIST_DECIDER),
        ApiErrorId.ERR_NOTICE_WINDOW_CONFLICT,
        409,
    )

    # One day later the gap is exactly fifteen days and the buffer is closed.
    set_clock("2026-09-15T00:00:00Z")
    published = validate_success(
        api.publish_notice(ctx["second"]["id"], BOND_SPECIALIST_DECIDER)
    )
    assert published["status"] == "PUBLIC_NOTICE", "the abutting window is admitted"
    assert published["notice_start_date"].startswith("2026-09-15")
    assert published["notice_end_date"].startswith("2026-10-15"), (
        f"thirty days after 2026-09-15, got {published['notice_end_date']}"
    )

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["last_notice_end_date"].startswith("2026-10-15"), (
        "the permit tracks the latest window end"
    )


def test_a_new_application_defaults_its_participation_counters():
    """A new application begins in `SUBMITTED` with `approved_amount` at 0,
    `comment_count` and `objection_count` at 0, `objections_resolved` false, and
    `notice_start_date`, `notice_end_date`, `inspection_id`,
    `decided_by_user_id`, `approved_at`, `denial_reason`, and `rescission_reason`
    all null.

    Design: Corner/entities/release_application_defaults_public_participation_counters
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Quiet Fork Minerals",
            "tangible_net_worth": 16000000.00,
            "fixed_assets_in_state": 8000000.00,
            "total_liabilities": 5000000.00,
            "net_income_prior_year": 700000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Quiet Fork Pit", "county": "Boone", "total_acres": 260.00},
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "FORESTLAND"},
        disturbed_acres=60.00,
    )

    data = validate_success(
        api.create_release_application(
            create_release_application_payload(
                ctx["permit"]["id"], phase="PHASE_I", acres_requested=20.00
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    assert_release_application(data)

    assert data["status"] == "SUBMITTED", "the declared initial state"
    assert data["comment_count"] == 0, "comment_count starts at zero"
    assert data["objection_count"] == 0, "objection_count starts at zero"
    assert data["objections_resolved"] is False, "objections_resolved starts false"
    assert_money(data["approved_amount"], 0.00, "approved_amount")
    for field in (
        "notice_start_date", "notice_end_date", "inspection_id",
        "decided_by_user_id", "approved_at", "denial_reason", "rescission_reason",
    ):
        assert data[field] is None, f"{field} starts null, got {data[field]!r}"

    # per-acre bond 865998.00 / 60.00 = 14433.30; 14433.30 x 20 x 0.60 = 173199.60,
    # well inside the 553600.80 of headroom above the 346399.20 retention floor.
    assert_money(data["requested_amount"], 173199.60, "requested_amount")


def test_release_acres_beyond_the_disturbed_footprint_rejected():
    """One acreage sanity check applies at creation, at priority 13:
    `acres_requested` plus the acreage the permit has already had released for
    that same phase must not exceed the permit's `disturbed_acres`, else
    `ERR_ACRES_EXCEED_DISTURBED`.

    Design: Corner/validations/release_acres_exceeding_disturbed_rejected
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Small Disturbance Mining",
            "tangible_net_worth": 14900000.00,
            "fixed_assets_in_state": 7350000.00,
            "total_liabilities": 4970000.00,
            "net_income_prior_year": 540000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Small Disturbance Pit", "county": "Carbon", "total_acres": 305.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=40.00,
    )
    permit_id = ctx["permit"]["id"]

    response = api.create_release_application(
        create_release_application_payload(
            permit_id, phase="PHASE_I", acres_requested=60.00
        ),
        ctx["operator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ACRES_EXCEED_DISTURBED, 422)

    permit = refresh_permit(permit_id)
    assert_money(permit["disturbed_acres"], 40.00, "disturbed_acres")
    assert_money(permit["phase1_released_acres"], 0.00, "phase1_released_acres")
    _, meta = validate_paginated(
        api.list_permit_release_applications(permit_id, PERMIT_REVIEWER)
    )
    assert meta["total_count"] == 0, (
        "the 120-acre mining plan does not license a release beyond the "
        "40 acres actually disturbed"
    )


def test_republishing_a_notice_already_out_is_refused():
    """Publishing the **public notice** is a `BondSpecialist` act that moves the
    application `SUBMITTED → PUBLIC_NOTICE`.

    Design: Corner/state_machines/second_publish_notice_on_public_notice_application_rejected
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Double Publish Mining",
            "tangible_net_worth": 15500000.00,
            "fixed_assets_in_state": 7600000.00,
            "total_liabilities": 5100000.00,
            "net_income_prior_year": 610000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Double Publish Pit", "county": "Elk", "total_acres": 250.00},
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
    )
    application = file_release_application(ctx, phase="PHASE_I", acres_requested=30.00)
    published = publish_release_notice(application["id"], BOND_SPECIALIST_DECIDER)
    assert published["notice_start_date"].startswith("2026-08-01")
    assert published["notice_end_date"].startswith("2026-08-31")

    set_clock("2026-08-05T00:00:00Z")
    response = api.publish_notice(application["id"], BOND_SPECIALIST_DECIDER)
    validate_error(response, ApiErrorId.ERR_RELEASE_STATE_INVALID, 409)

    replayed = refresh_application(application["id"])
    assert replayed["status"] == "PUBLIC_NOTICE", "the application is still out for notice"
    assert replayed["notice_start_date"].startswith("2026-08-01"), (
        "the replay must not slide the window forward"
    )
    assert replayed["notice_end_date"].startswith("2026-08-31"), (
        "the replay must not slide the window forward"
    )
    assert refresh_permit(ctx["permit"]["id"])["last_notice_end_date"].startswith("2026-08-31")


def test_publishing_a_notice_on_a_bond_deficient_permit_refused():
    """It requires the permit's `compliance_posture` to be `COMPLIANT` or
    `NOTICE_ACTIVE`, else `ERR_PERMIT_NOT_COMPLIANT` at priority 11.

    Design: Corner/errors/publish_notice_on_bond_deficient_permit_rejected
    """
    ctx = setup_bond_deficient_by_expansion(
        acreage_delta=60.00,
        operator_overrides={
            "legal_name": "Deficient Notice Mining",
            "tangible_net_worth": 15600000.00,
            "fixed_assets_in_state": 7700000.00,
            "total_liabilities": 5080000.00,
            "net_income_prior_year": 600000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Deficient Notice Pit", "county": "Gila", "total_acres": 400.00},
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
    )
    permit = ctx["permit"]
    assert_money(permit["mining_plan_acres"], 180.00, "mining_plan_acres")
    assert_money(permit["bond_required_amount"], 1298997.00, "bond_required_amount")
    assert_money(permit["bond_deficiency_amount"], 398997.00, "bond_deficiency_amount")
    assert permit["compliance_posture"] == "BOND_DEFICIENT"

    application = file_release_application(ctx, phase="PHASE_I", acres_requested=30.00)
    response = api.publish_notice(application["id"], BOND_SPECIALIST_DECIDER)
    validate_error(response, ApiErrorId.ERR_PERMIT_NOT_COMPLIANT, 409)

    blocked = refresh_application(application["id"])
    assert blocked["status"] == "SUBMITTED", "no notice was published"
    assert blocked["notice_start_date"] is None


def test_comments_are_counted_and_objections_disposed_of_separately():
    """Each comment increments `comment_count` by 1, and a comment whose
    `is_objection` is true additionally increments `objection_count` by 1.

    Design: Corner/endpoints/public_comment_endpoint_counts_objection_and_resolution_clears_it
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Public Comment Mining",
            "tangible_net_worth": 15300000.00,
            "fixed_assets_in_state": 7600000.00,
            "total_liabilities": 5040000.00,
            "net_income_prior_year": 580000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Public Comment Pit", "county": "Boone", "total_acres": 320.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "FORESTLAND"},
        disturbed_acres=120.00,
    )
    application = file_release_application(ctx, phase="PHASE_I", acres_requested=30.00)
    published = publish_release_notice(application["id"], BOND_SPECIALIST_DECIDER)
    assert published["status"] == "PUBLIC_NOTICE"

    file_public_comment(
        application["id"],
        "Supportive of the release; revegetation looks established.",
        is_objection=False,
    )
    commented = file_public_comment(
        application["id"],
        "Objection: the sediment pond has not been removed.",
        is_objection=True,
    )
    assert commented["comment_count"] == 2, (
        f"two comments were filed, got {commented['comment_count']}"
    )
    assert commented["objection_count"] == 1, (
        f"only one of them objected, got {commented['objection_count']}"
    )
    assert commented["objections_resolved"] is False, "nothing has disposed of it yet"

    resolved = validate_success(
        api.resolve_objections(
            application["id"],
            {"resolution_note": "Pond removal verified against the as-built survey."},
            BOND_SPECIALIST_DECIDER,
        )
    )
    assert resolved["objections_resolved"] is True, (
        "recording a resolution note is the only way the flag becomes true"
    )
    assert resolved["comment_count"] == 2, "resolution does not touch the counters"
    assert resolved["objection_count"] == 1, "resolution does not touch the counters"
    assert resolved["status"] == "PUBLIC_NOTICE", "the application is still out"
    assert_money(resolved["requested_amount"], 129899.70, "requested_amount")


def _cessation_over_a_published_release(operator_overrides, site_overrides):
    """A published PHASE_I release plus a CESSATION_ORDERED imminent-harm notice."""
    ctx = chain_issued(
        operator_overrides=operator_overrides,
        site_overrides=site_overrides,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "FORESTLAND"},
        disturbed_acres=120.00,
    )
    application = file_release_application(ctx, phase="PHASE_I", acres_requested=30.00)
    ctx["application"] = publish_release_notice(application["id"], BOND_SPECIALIST_DECIDER)
    setup_violation_notice(
        ctx,
        inspection_overrides={"scheduled_start": "2026-08-06T09:00:00Z", "duration_hours": 4},
        **IMMINENT_HARM_NOTICE,
    )
    return ctx


def test_a_cessation_order_suspends_the_open_release_and_clears_its_window():
    """Whenever the newly computed posture lands in `CESSATION`,
    `BOND_DEFICIENT`, or `FORFEITURE_PENDING`, every bond release application on
    that permit whose status is `SUBMITTED` or `PUBLIC_NOTICE` is driven to
    `SUSPENDED`.

    Design: Corner/state_machines/cessation_order_suspends_open_release_application_and_clears_window
    """
    ctx = _cessation_over_a_published_release(
        {
            "legal_name": "Shutdown Order Mining",
            "tangible_net_worth": 15800000.00,
            "fixed_assets_in_state": 7900000.00,
            "total_liabilities": 5200000.00,
            "net_income_prior_year": 640000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        {"name": "Shutdown Order Pit", "county": "Mingo", "total_acres": 245.00},
    )
    assert ctx["notice"]["total_points"] == 70, "30 + 25 + 15 points"

    ordered = order_cessation(
        ctx,
        ctx["notice"]["id"],
        "Imminent danger to downstream dwellings from lost impoundment freeboard.",
    )
    assert ordered["notice_status"] == "CESSATION_ORDERED"
    assert ordered["cessation_ordered_at"] is not None

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["compliance_posture"] == "CESSATION", "the posture axis moves"
    assert permit["status"] == "ISSUED", "the status axis does not"

    application = refresh_application(ctx["application"]["id"])
    assert application["status"] == "SUSPENDED", "the open release is suspended"
    assert application["notice_start_date"] is None, "its window is cleared"
    assert application["notice_end_date"] is None, "its window is cleared"

    assert permit["last_notice_end_date"] is None, (
        "no non-suspended application holds a window any more"
    )
    assert_money(permit["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(permit["bond_released_to_date"], 0.00, "bond_released_to_date")


def test_reinstatement_returns_a_suspended_release_to_submitted():
    """Reinstatement recomputes `requested_amount` against the permit's *current*
    figures rather than restoring the stale figure, which is the point of the
    exercise, and increments the application's `version` by 1.

    Design: Corner/state_machines/suspended_application_reinstate_recomputes_requested_amount
    """
    ctx = _cessation_over_a_published_release(
        {
            "legal_name": "Reinstate Path Mining",
            "tangible_net_worth": 15900000.00,
            "fixed_assets_in_state": 7950000.00,
            "total_liabilities": 5250000.00,
            "net_income_prior_year": 650000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        {"name": "Reinstate Path Pit", "county": "Boone", "total_acres": 255.00},
    )
    order_cessation(
        ctx, ctx["notice"]["id"], "Imminent danger to downstream dwellings."
    )
    suspended = refresh_application(ctx["application"]["id"])
    assert suspended["status"] == "SUSPENDED"

    validate_success(
        api.abate_notice(
            ctx["notice"]["id"],
            {"abatement_note": "Freeboard restored and spillway rebuilt to design."},
            ctx["operator_headers"],
        )
    )
    assert refresh_notice(ctx["notice"]["id"])["notice_status"] == "ABATED"
    assert refresh_permit(ctx["permit"]["id"])["compliance_posture"] == "COMPLIANT", (
        "abatement clears the posture, which is what admits the reinstatement"
    )

    reinstated = validate_success(
        api.reinstate_release_application(
            ctx["application"]["id"], BOND_SPECIALIST_DECIDER
        )
    )
    assert reinstated["status"] == "SUBMITTED", (
        "reinstatement does not restore PUBLIC_NOTICE"
    )
    assert reinstated["notice_start_date"] is None, "the notice must be published afresh"
    assert reinstated["notice_end_date"] is None, "the notice must be published afresh"
    # per-acre bond 865998.00 / 120.00 = 7216.65; 7216.65 x 30 x 0.60 = 129899.70
    assert_money(reinstated["requested_amount"], 129899.70, "requested_amount")
    assert reinstated["version"] == suspended["version"] + 1, (
        "reinstatement is one mutation of the application"
    )
