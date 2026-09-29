"""The inspection calendar, violation notices, and the civil penalty ledger."""
from test_helpers import (
    PERMIT_REVIEWER,
    PROGRAM_DIRECTOR,
    ApiErrorId,
    api_client as api,
    assert_money,
    assert_violation_notice,
    assert_violation_point_invariants,
    chain_applied,
    chain_estimate_accepted,
    chain_issued,
    create_inspection_payload,
    create_violation_notice_payload,
    file_permit_revision,
    make_inspector_headers,
    make_operator_headers,
    order_cessation,
    refresh_inspection,
    refresh_notice,
    refresh_operator,
    refresh_permit,
    refresh_revision,
    register_inspector,
    register_operator,
    schedule_release_inspection,
    setup_assessed_penalty,
    setup_completed_violation_inspection,
    setup_violation_notice,
    validate_error,
    validate_paginated,
    validate_success,
)

SLATE_CREEK_OPERATOR = {
    "legal_name": "Slate Creek Minerals",
    "tangible_net_worth": 18000000.00,
    "fixed_assets_in_state": 12000000.00,
    "total_liabilities": 6000000.00,
    "net_income_prior_year": 900000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
SLATE_CREEK_SITE = {
    "name": "Slate Creek Surface Mine", "county": "Boone", "total_acres": 500.00,
}

SLATE_HOLLOW_OPERATOR = {
    "legal_name": "Slate Hollow Extraction",
    "tangible_net_worth": 17000000.00,
    "fixed_assets_in_state": 8500000.00,
    "total_liabilities": 6000000.00,
    "net_income_prior_year": 800000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
SLATE_HOLLOW_SITE = {
    "name": "Slate Hollow Workings", "county": "Boone", "total_acres": 480.00,
}

TWO_RIVERS_OPERATOR = {
    "legal_name": "Two Rivers Sand and Gravel",
    "tangible_net_worth": 16000000.00,
    "fixed_assets_in_state": 8000000.00,
    "total_liabilities": 5500000.00,
    "net_income_prior_year": 700000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
TWO_RIVERS_SITE = {
    "name": "Two Rivers Bar", "county": "Fremont", "total_acres": 300.00,
}

FORTY_FIVE_POINT_NOTICE = {
    "violation_class": "NON_COMPLIANCE",
    "severity_points": 20,
    "negligence_points": 15,
    "duration_points": 10,
    "abatement_days": 30,
}


def _slate_creek_imminent_harm_notice():
    """An 85-point IMMINENT_HARM notice on an issued permit, penalty unassessed."""
    ctx = chain_issued(
        operator_overrides=SLATE_CREEK_OPERATOR,
        site_overrides=SLATE_CREEK_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )
    setup_violation_notice(
        ctx,
        inspection_overrides={
            "scheduled_start": "2026-08-10T09:00:00Z",
            "duration_hours": 4,
            "inspector": register_inspector(
                full_name="Dana Whitlock", certification_level="CERT_III", region="SOUTH"
            ),
        },
        violation_class="IMMINENT_HARM",
        severity_points=30,
        negligence_points=30,
        duration_points=25,
        abatement_days=15,
    )
    return ctx


def test_the_good_faith_credit_cap_is_keyed_on_the_base_and_clips_the_credit():
    """Second, the credit ceiling, which is keyed on the **base**: 1500.00 when
    the base is strictly above 3000.00, otherwise 750.00 when the base is
    strictly above 1500.00, otherwise 0.00.

    Design: Difficulty/combinatorial_formula/penalty_credit_cap_and_imminent_harm_surcharge_interaction
    """
    ctx = _slate_creek_imminent_harm_notice()
    notice = ctx["notice"]
    assert_violation_point_invariants(notice)
    assert notice["history_points"] == 0, "a first offence carries no history"
    assert notice["total_points"] == 85, f"30 + 30 + 25, got {notice['total_points']}"

    assessed = validate_success(
        api.assess_penalty(notice["id"], {"good_faith_level": "RAPID"}, PROGRAM_DIRECTOR)
    )
    assert_violation_notice(assessed)
    assert assessed["penalty_status"] == "ASSESSED"
    assert assessed["good_faith_level"] == "RAPID"

    # base 85 x 60.00 = 5100.00; ceiling 1500.00 clips the 1530.00 raw credit;
    # subtotal 3600.00; the surcharge band on 3600.00 is 0.10, so 360.00.
    assert_money(assessed["penalty_amount"], 3960.00, "penalty_amount")
    assert abs(assessed["penalty_amount"] - 4500.00) > 0.01, (
        "4500.00 is what a surcharge keyed on the base rather than on the "
        "post-credit subtotal would have produced"
    )

    operator = refresh_operator(ctx["operator"]["id"])
    assert_money(operator["outstanding_penalty_balance"], 3960.00, "outstanding_penalty_balance")
    assert operator["violation_points_total"] == 85, "the points ledger carries the notice"

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["compliance_posture"] == "NOTICE_ACTIVE"
    assert permit["status"] == "ISSUED"


def test_the_imminent_harm_surcharge_band_follows_the_post_credit_subtotal():
    """Fifth, the imminent-harm surcharge, which is keyed on the **post-credit
    subtotal**, not on the base: for any `violation_class` other than
    `IMMINENT_HARM` the surcharge rate is 0.00; for `IMMINENT_HARM` it is 0.25
    when the subtotal is strictly above 5000.00, otherwise 0.10 when the subtotal
    is strictly above 2000.00, otherwise 0.00.

    Design: Difficulty/combinatorial_formula/penalty_credit_cap_and_imminent_harm_surcharge_interaction
    """
    ctx = _slate_creek_imminent_harm_notice()
    assert ctx["notice"]["total_points"] == 85, "the same 85-point notice"

    assessed = validate_success(
        api.assess_penalty(ctx["notice"]["id"], {"good_faith_level": "NONE"}, PROGRAM_DIRECTOR)
    )
    # With no good-faith credit the subtotal stays at the 5100.00 base, which
    # lands above 5000.00 and so draws the 0.25 band: 5100.00 + 1275.00.
    assert_money(assessed["penalty_amount"], 6375.00, "penalty_amount")
    assert assessed["good_faith_level"] == "NONE"
    assert assessed["penalty_status"] == "ASSESSED"
    assert_money(assessed["penalty_paid_amount"], 0.00, "penalty_paid_amount")

    assert_money(
        refresh_operator(ctx["operator"]["id"])["outstanding_penalty_balance"],
        6375.00,
        "outstanding_penalty_balance",
    )


def _two_rivers_booked_morning():
    """One inspector holding a 09:00-13:00 assignment on 2026-08-10."""
    ctx = chain_issued(
        operator_overrides=TWO_RIVERS_OPERATOR,
        site_overrides=TWO_RIVERS_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )
    inspector = register_inspector(
        full_name="Halden Roux", certification_level="CERT_II", region="WEST"
    )
    ctx["inspector"] = inspector
    ctx["morning"] = validate_success(
        api.create_inspection(
            create_inspection_payload(
                ctx["permit"]["id"], inspector["id"],
                inspection_type="ROUTINE",
                scheduled_start="2026-08-10T09:00:00Z",
                duration_hours=4,
            ),
            PROGRAM_DIRECTOR,
        ),
        201,
    )
    return ctx


def _complaint_booking(ctx, scheduled_start, duration_hours=2):
    return api.create_inspection(
        create_inspection_payload(
            ctx["permit"]["id"], ctx["inspector"]["id"],
            inspection_type="COMPLAINT",
            scheduled_start=scheduled_start,
            duration_hours=duration_hours,
        ),
        PROGRAM_DIRECTOR,
    )


def test_a_booking_that_starts_inside_a_running_assignment_is_refused():
    """An inspector's calendar is exclusive: at priority 15, the requested
    interval from `scheduled_start` through `scheduled_end` must not overlap the
    interval of any other inspection assigned to the same `inspector_id` and
    still in `SCHEDULED`, else `ERR_INSPECTOR_DOUBLE_BOOKED`.

    Design: Difficulty/resource_temporal_overlap/inspector_calendar_rejects_overlap_but_allows_abutment
    """
    ctx = _two_rivers_booked_morning()
    assert ctx["morning"]["scheduled_end"].startswith("2026-08-10T13:00:00"), (
        f"09:00 plus four hours, got {ctx['morning']['scheduled_end']!r}"
    )

    response = _complaint_booking(ctx, "2026-08-10T12:00:00Z")
    validate_error(response, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED, 409)

    _, meta = validate_paginated(
        api.list_inspector_inspections(ctx["inspector"]["id"], PROGRAM_DIRECTOR)
    )
    assert meta["total_count"] == 1, "the refused booking created no inspection row"
    inspector = validate_success(
        api.get_inspector_profile(ctx["inspector"]["id"], PROGRAM_DIRECTOR)
    )
    assert inspector["scheduled_inspection_count"] == 1, (
        "the rejected attempt never incremented the counter"
    )


def test_a_booking_that_starts_exactly_at_the_prior_end_is_admitted():
    """Abutment is explicitly allowed — one inspection ending exactly when the
    next begins is not an overlap.

    Design: Difficulty/resource_temporal_overlap/inspector_calendar_rejects_overlap_but_allows_abutment
    """
    ctx = _two_rivers_booked_morning()
    validate_error(
        _complaint_booking(ctx, "2026-08-10T12:00:00Z"),
        ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED,
        409,
    )

    abutting = validate_success(_complaint_booking(ctx, "2026-08-10T13:00:00Z"), 201)
    assert abutting["status"] == "SCHEDULED", "the touching endpoint is not an overlap"
    assert abutting["scheduled_end"].startswith("2026-08-10T15:00:00"), (
        f"13:00 plus two hours, got {abutting['scheduled_end']!r}"
    )
    assert abutting["scheduled_start"].startswith("2026-08-10T13:00:00")
    assert abutting["result"] is None, "a booked inspection carries no result"

    inspector = validate_success(
        api.get_inspector_profile(ctx["inspector"]["id"], PROGRAM_DIRECTOR)
    )
    assert inspector["scheduled_inspection_count"] == 2, (
        "both admitted bookings sit on the calendar"
    )


def _slate_hollow_assessed_penalty():
    """An 85-point IMMINENT_HARM notice carrying a 3960.00 assessed penalty."""
    ctx = chain_issued(
        operator_overrides=SLATE_HOLLOW_OPERATOR,
        site_overrides=SLATE_HOLLOW_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "FORESTLAND"},
    )
    setup_assessed_penalty(
        ctx,
        good_faith_level="RAPID",
        inspection_overrides={
            "scheduled_start": "2026-08-05T09:00:00Z",
            "duration_hours": 3,
            "inspector": register_inspector(
                full_name="Corina Vasquez", certification_level="CERT_III", region="SOUTH"
            ),
        },
        violation_class="IMMINENT_HARM",
        severity_points=40,
        negligence_points=30,
        duration_points=15,
        abatement_days=15,
    )
    return ctx


def test_vacatur_zeroes_the_assessed_penalty_on_both_dimensions():
    """On success the notice's `notice_status` becomes `VACATED` and `vacated_at`
    is stamped; and if the notice's `penalty_status` was `ASSESSED`, that
    dimension also moves `ASSESSED → VACATED` with `penalty_amount` reset to
    0.00.

    Design: Difficulty/compensating_invariant/notice_vacatur_restores_operator_penalty_and_points_ledgers
    """
    ctx = _slate_hollow_assessed_penalty()
    before = ctx["notice"]
    assert before["total_points"] == 85, "40 + 30 + 15 points"
    assert before["penalty_status"] == "ASSESSED"
    assert_money(before["penalty_amount"], 3960.00, "penalty_amount")

    reason = (
        "Formal review found the cited embankment was outside the permit boundary."
    )
    vacated = validate_success(
        api.vacate_notice(before["id"], {"vacate_reason": reason}, PROGRAM_DIRECTOR)
    )
    assert vacated["notice_status"] == "VACATED", "the enforcement dimension is undone"
    assert vacated["vacate_reason"] == reason, "the reason is stored"
    assert vacated["vacated_at"] is not None, "vacatur is stamped"
    assert vacated["penalty_status"] == "VACATED", "the money dimension follows"
    assert_money(vacated["penalty_amount"], 0.00, "penalty_amount")
    assert_money(vacated["penalty_paid_amount"], 0.00, "penalty_paid_amount")
    assert vacated["version"] == before["version"] + 1, "vacatur is one mutation"


def test_vacatur_restores_the_operator_penalty_and_points_ledgers():
    """Both the operator's `violation_points_total` and its
    `outstanding_penalty_balance` are recomputed, the permit's
    `compliance_posture` is recomputed on the same terms as abatement, and the
    notice's `version` increments by 1.

    Design: Difficulty/compensating_invariant/notice_vacatur_restores_operator_penalty_and_points_ledgers
    """
    ctx = _slate_hollow_assessed_penalty()
    operator_before = refresh_operator(ctx["operator"]["id"])
    assert_money(
        operator_before["outstanding_penalty_balance"], 3960.00,
        "outstanding_penalty_balance",
    )
    assert operator_before["violation_points_total"] == 85, "the points are accrued"
    assert refresh_permit(ctx["permit"]["id"])["compliance_posture"] == "NOTICE_ACTIVE"

    validate_success(
        api.vacate_notice(
            ctx["notice"]["id"],
            {"vacate_reason": "The cited condition was outside the permit boundary."},
            PROGRAM_DIRECTOR,
        )
    )

    operator = refresh_operator(ctx["operator"]["id"])
    assert_money(operator["outstanding_penalty_balance"], 0.00, "outstanding_penalty_balance")
    assert operator["violation_points_total"] == 0, (
        "a vacated notice leaves the points ledger entirely"
    )

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["compliance_posture"] == "COMPLIANT", "the posture recovers"
    assert permit["status"] == "ISSUED", "the status axis never moved"
    assert_money(permit["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(permit["bond_released_to_date"], 0.00, "bond_released_to_date")


def _issued_permit_with_a_completed_violation_inspection(operator_overrides, site_overrides):
    ctx = chain_issued(
        operator_overrides=operator_overrides,
        site_overrides=site_overrides,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )
    setup_completed_violation_inspection(
        ctx, scheduled_start="2026-08-04T09:00:00Z", duration_hours=3
    )
    return ctx


def test_severity_points_above_the_declared_ceiling_rejected():
    """It supplies three penalty-point components, each with its own ceiling:
    `severity_points` within 0 through 40 inclusive, `negligence_points` within 0
    through 30 inclusive, and `duration_points` within 0 through 25 inclusive.

    Design: Corner/entities/violation_notice_severity_points_above_declared_maximum_rejected
    """
    ctx = _issued_permit_with_a_completed_violation_inspection(
        {
            "legal_name": "Over Ceiling Mining",
            "tangible_net_worth": 15200000.00,
            "fixed_assets_in_state": 7500000.00,
            "total_liabilities": 5000000.00,
            "net_income_prior_year": 570000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        {"name": "Over Ceiling Pit", "county": "Carbon", "total_acres": 280.00},
    )

    response = api.create_violation_notice(
        create_violation_notice_payload(ctx["inspection"]["id"], severity_points=41),
        ctx["inspector_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(
        api.list_permit_violation_notices(ctx["permit"]["id"], PROGRAM_DIRECTOR)
    )
    assert meta["total_count"] == 0, "no notice row was stored"
    assert refresh_operator(ctx["operator"]["id"])["violation_points_total"] == 0, (
        "a refused notice accrues no points"
    )
    assert refresh_permit(ctx["permit"]["id"])["compliance_posture"] == "COMPLIANT", (
        "the posture never moved off COMPLIANT"
    )


def test_the_notice_inherits_its_permit_from_the_cited_inspection():
    """The notice copies `permit_id` from the cited inspection rather than
    accepting one from the client.

    Design: Corner/entities/violation_notice_permit_id_inherited_from_cited_inspection
    """
    ctx = _issued_permit_with_a_completed_violation_inspection(
        {
            "legal_name": "Inherited Parent Mining",
            "tangible_net_worth": 15400000.00,
            "fixed_assets_in_state": 7600000.00,
            "total_liabilities": 5050000.00,
            "net_income_prior_year": 590000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        {"name": "Inherited Parent Pit", "county": "Boone", "total_acres": 290.00},
    )
    permit_id = ctx["permit"]["id"]

    notice = validate_success(
        api.create_violation_notice(
            create_violation_notice_payload(
                ctx["inspection"]["id"], **FORTY_FIVE_POINT_NOTICE
            ),
            ctx["inspector_headers"],
        ),
        201,
    )
    assert_violation_notice(notice)
    assert notice["permit_id"] == permit_id, (
        "the parent is taken from the inspection, not from the request"
    )
    assert notice["inspection_id"] == ctx["inspection"]["id"]
    assert notice["total_points"] == 45, "20 + 15 + 10 points"
    assert notice["history_points"] == 0, "no prior notices"
    assert notice["notice_status"] == "ISSUED"
    assert notice["penalty_status"] == "NONE"

    rows, meta = validate_paginated(
        api.list_permit_violation_notices(permit_id, PROGRAM_DIRECTOR)
    )
    assert meta["total_count"] == 1, "the notice is reachable through its permit"
    assert rows[0]["id"] == notice["id"]

    assert refresh_permit(permit_id)["compliance_posture"] == "NOTICE_ACTIVE"
    assert refresh_operator(ctx["operator"]["id"])["violation_points_total"] == 45


def test_recording_a_pass_completes_the_inspection_and_frees_the_calendar():
    """Recording stamps `completed_at` with the logical clock's current value and
    decrements the inspector's `scheduled_inspection_count` by 1.

    Design: Corner/state_machines/inspection_record_result_moves_scheduled_to_completed
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Clean Pass Mining",
            "tangible_net_worth": 15100000.00,
            "fixed_assets_in_state": 7450000.00,
            "total_liabilities": 4990000.00,
            "net_income_prior_year": 560000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Clean Pass Pit", "county": "Elk", "total_acres": 270.00},
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )
    inspection = schedule_release_inspection(
        ctx,
        scheduled_start="2026-08-04T09:00:00Z",
        duration_hours=3,
        inspection_type="ROUTINE",
    )
    assert inspection["status"] == "SCHEDULED"
    assert inspection["scheduled_end"].startswith("2026-08-04T12:00:00"), (
        f"09:00 plus three hours, got {inspection['scheduled_end']!r}"
    )
    inspector_id = ctx["inspector"]["id"]
    assert validate_success(
        api.get_inspector_profile(inspector_id, PROGRAM_DIRECTOR)
    )["scheduled_inspection_count"] == 1, "the booking occupies the calendar"

    completed = validate_success(
        api.record_inspection_result(
            inspection["id"],
            {"result": "PASS", "findings_note": "No violations observed on the bench."},
            ctx["inspector_headers"],
        )
    )
    assert completed["status"] == "COMPLETED", "recording closes the inspection"
    assert completed["result"] == "PASS"
    assert completed["completed_at"].startswith("2026-08-01T00:00:00"), (
        f"stamped from the logical clock, got {completed['completed_at']!r}"
    )
    assert validate_success(
        api.get_inspector_profile(inspector_id, PROGRAM_DIRECTOR)
    )["scheduled_inspection_count"] == 0, "the calendar is freed"
    assert refresh_permit(ctx["permit"]["id"])["compliance_posture"] == "COMPLIANT", (
        "a PASS creates no notice and moves no posture"
    )


def test_abating_an_already_vacated_notice_rejected():
    """The `Operator` clears a notice by **abating** it, recording an
    `abatement_note` and moving the notice to `ABATED` from either `ISSUED` or
    `CESSATION_ORDERED` — both source states carry the identical effect set.

    Design: Corner/state_machines/abate_on_already_vacated_notice_rejected
    """
    ctx = _issued_permit_with_a_completed_violation_inspection(
        {
            "legal_name": "Vacated Then Abated Mining",
            "tangible_net_worth": 15050000.00,
            "fixed_assets_in_state": 7400000.00,
            "total_liabilities": 4980000.00,
            "net_income_prior_year": 550000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        {"name": "Vacated Then Abated Pit", "county": "Elk", "total_acres": 275.00},
    )
    notice = validate_success(
        api.create_violation_notice(
            create_violation_notice_payload(
                ctx["inspection"]["id"], **FORTY_FIVE_POINT_NOTICE
            ),
            ctx["inspector_headers"],
        ),
        201,
    )
    validate_success(
        api.vacate_notice(
            notice["id"],
            {"vacate_reason": "The cited grade was inside the approved tolerance."},
            PROGRAM_DIRECTOR,
        )
    )

    response = api.abate_notice(
        notice["id"],
        {"abatement_note": "Regraded the north face to the approved contour."},
        ctx["operator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_NOTICE_STATE_INVALID, 409)

    refused = refresh_notice(notice["id"])
    assert refused["notice_status"] == "VACATED", "VACATED is terminal"
    assert refused["abated_at"] is None, "no abatement was stamped"
    assert refused["abatement_note"] is None, "no note was stored"
    assert refresh_operator(ctx["operator"]["id"])["violation_points_total"] == 0
    assert refresh_permit(ctx["permit"]["id"])["compliance_posture"] == "COMPLIANT"


def test_a_cessation_order_meeting_no_criterion_rejected():
    """At least one of three criteria must hold, checked at priority 11: the
    notice's `total_points` is at least 70, or the logical clock's current instant
    is past the notice's `abatement_deadline`, or the notice's `violation_class`
    is `IMMINENT_HARM`. A notice meeting none of them is refused with
    `ERR_CESSATION_CRITERIA_NOT_MET`.

    Design: Corner/state_machines/order_cessation_without_any_criterion_rejected
    """
    ctx = _issued_permit_with_a_completed_violation_inspection(
        {
            "legal_name": "No Criterion Mining",
            "tangible_net_worth": 15250000.00,
            "fixed_assets_in_state": 7520000.00,
            "total_liabilities": 5010000.00,
            "net_income_prior_year": 575000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        {"name": "No Criterion Pit", "county": "Carbon", "total_acres": 285.00},
    )
    notice = validate_success(
        api.create_violation_notice(
            create_violation_notice_payload(
                ctx["inspection"]["id"], **FORTY_FIVE_POINT_NOTICE
            ),
            ctx["inspector_headers"],
        ),
        201,
    )
    assert notice["total_points"] == 45, "below the seventy-point threshold"
    assert notice["violation_class"] == "NON_COMPLIANCE", "not an imminent hazard"
    assert notice["abatement_deadline"].startswith("2026-08-31"), (
        "thirty abatement days from the 2026-08-01 clock, still in the future"
    )

    response = api.order_cessation(
        notice["id"],
        {"cessation_reason": "Escalating the north face grade violation."},
        ctx["inspector_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CESSATION_CRITERIA_NOT_MET, 409)

    refused = refresh_notice(notice["id"])
    assert refused["notice_status"] == "ISSUED", "the notice did not escalate"
    assert refused["cessation_ordered_at"] is None, "nothing was stamped"
    assert refresh_permit(ctx["permit"]["id"])["compliance_posture"] == "NOTICE_ACTIVE", (
        "the posture stays at NOTICE_ACTIVE rather than CESSATION"
    )


def test_a_small_assessment_is_raised_to_the_minimum_penalty():
    """The stored `penalty_amount` is then the subtotal plus the surcharge,
    rounded half up to two decimals, and raised to a minimum penalty of 750.00 if
    it falls below that.

    Design: Corner/calculations/penalty_minimum_floor_applies_to_small_assessment
    """
    ctx = chain_applied(
        operator_overrides={
            "legal_name": "Small Penalty Mining",
            "tangible_net_worth": 11200000.00,
            "fixed_assets_in_state": 5600000.00,
            "total_liabilities": 4200000.00,
            "net_income_prior_year": 240000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Small Penalty Pit", "county": "Sheridan", "total_acres": 170.00,
        },
        mining_plan_acres=70.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
    )
    setup_completed_violation_inspection(
        ctx, scheduled_start="2026-08-04T09:00:00Z", duration_hours=2
    )
    notice = validate_success(
        api.create_violation_notice(
            create_violation_notice_payload(
                ctx["inspection"]["id"],
                violation_class="NON_COMPLIANCE",
                severity_points=5,
                negligence_points=3,
                duration_points=2,
                abatement_days=30,
            ),
            ctx["inspector_headers"],
        ),
        201,
    )
    assert notice["total_points"] == 10, "5 + 3 + 2 points"
    assert notice["history_points"] == 0

    assessed = validate_success(
        api.assess_penalty(notice["id"], {"good_faith_level": "NONE"}, PROGRAM_DIRECTOR)
    )
    # base 10 x 60.00 = 600.00, no credit and no surcharge, so the floor binds.
    assert_money(assessed["penalty_amount"], 750.00, "penalty_amount")
    assert assessed["penalty_status"] == "ASSESSED"
    assert_money(
        refresh_operator(ctx["operator"]["id"])["outstanding_penalty_balance"],
        750.00,
        "outstanding_penalty_balance",
    )


def _partial_good_faith_assessment(operator_overrides, site_overrides):
    """A 45-point NON_COMPLIANCE notice assessed at 2430.00."""
    ctx = chain_applied(
        operator_overrides=operator_overrides,
        site_overrides=site_overrides,
        mining_plan_acres=70.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
    )
    setup_assessed_penalty(
        ctx,
        good_faith_level="PARTIAL",
        inspection_overrides={
            "scheduled_start": "2026-08-04T09:00:00Z", "duration_hours": 2,
        },
        **FORTY_FIVE_POINT_NOTICE,
    )
    return ctx


def test_paying_less_than_the_assessed_penalty_rejected():
    """The request carries `amount_paid`, which must equal the notice's
    `penalty_amount` exactly — partial payment is not a concept this system
    models, and any mismatch is `ERR_PENALTY_AMOUNT_MISMATCH` at priority 13.

    Design: Corner/validations/pay_penalty_partial_amount_rejected
    """
    ctx = _partial_good_faith_assessment(
        {
            "legal_name": "Partial Payer Mining",
            "tangible_net_worth": 11300000.00,
            "fixed_assets_in_state": 5650000.00,
            "total_liabilities": 4250000.00,
            "net_income_prior_year": 250000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        {"name": "Partial Payer Pit", "county": "Sheridan", "total_acres": 175.00},
    )
    # base 45 x 60.00 = 2700.00; the base sits in the 750.00 ceiling band and the
    # PARTIAL rate yields 270.00, so the subtotal 2430.00 stands with no surcharge.
    assert_money(ctx["notice"]["penalty_amount"], 2430.00, "penalty_amount")

    response = api.pay_penalty(
        ctx["notice"]["id"], {"amount_paid": 2000.00}, ctx["operator_headers"]
    )
    validate_error(response, ApiErrorId.ERR_PENALTY_AMOUNT_MISMATCH, 422)

    notice = refresh_notice(ctx["notice"]["id"])
    assert notice["penalty_status"] == "ASSESSED", "the penalty is still outstanding"
    assert_money(notice["penalty_paid_amount"], 0.00, "penalty_paid_amount")
    assert_money(
        refresh_operator(ctx["operator"]["id"])["outstanding_penalty_balance"],
        2430.00,
        "outstanding_penalty_balance — no partial credit is recorded",
    )


def test_paying_the_exact_assessed_penalty_settles_it():
    """On success the supplied figure is stored in `penalty_paid_amount`,
    `penalty_status` moves `ASSESSED → PAID`, the operator's
    `outstanding_penalty_balance` is recomputed so the notice leaves the
    outstanding sum, and the notice's `version` increments by 1.

    Design: Corner/validations/pay_penalty_exact_amount_succeeds
    """
    ctx = _partial_good_faith_assessment(
        {
            "legal_name": "Exact Payer Mining",
            "tangible_net_worth": 11400000.00,
            "fixed_assets_in_state": 5700000.00,
            "total_liabilities": 4260000.00,
            "net_income_prior_year": 260000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        {"name": "Exact Payer Pit", "county": "Sheridan", "total_acres": 180.00},
    )
    assessed = ctx["notice"]
    assert_money(assessed["penalty_amount"], 2430.00, "penalty_amount")

    paid = validate_success(
        api.pay_penalty(
            assessed["id"], {"amount_paid": 2430.00}, ctx["operator_headers"]
        )
    )
    assert paid["penalty_status"] == "PAID", "exact payment settles the penalty"
    assert_money(paid["penalty_paid_amount"], 2430.00, "penalty_paid_amount")
    assert paid["version"] == assessed["version"] + 1, "payment is one mutation"

    operator = refresh_operator(ctx["operator"]["id"])
    assert_money(operator["outstanding_penalty_balance"], 0.00, "outstanding_penalty_balance")
    assert operator["violation_points_total"] == 45, (
        "payment settles money, not points"
    )


def test_a_foreign_operator_cannot_abate_another_operators_notice():
    """For a request whose `X-User-Role` is `Operator`, `X-User-ID` must equal
    the `operator_id` of the permit the request targets, else
    `ERR_NOT_PERMIT_OPERATOR`.

    Design: Corner/errors/foreign_operator_abating_another_operators_notice_rejected
    """
    ctx = chain_applied(
        operator_overrides={
            "legal_name": "Rightful Holder Mining",
            "tangible_net_worth": 11500000.00,
            "fixed_assets_in_state": 5750000.00,
            "total_liabilities": 4270000.00,
            "net_income_prior_year": 270000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Rightful Holder Pit", "county": "Sheridan", "total_acres": 185.00,
        },
        mining_plan_acres=70.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
    )
    interloper = register_operator(
        legal_name="Interloper Mining",
        tangible_net_worth=11600000.00,
        fixed_assets_in_state=5800000.00,
        total_liabilities=4280000.00,
        net_income_prior_year=280000.00,
        elected_financial_test="NET_WORTH_TEST",
    )
    notice = setup_violation_notice(
        ctx,
        inspection_overrides={
            "scheduled_start": "2026-08-04T09:00:00Z", "duration_hours": 2,
        },
        **FORTY_FIVE_POINT_NOTICE,
    )
    payload = {"abatement_note": "Sediment control restored along the haul road."}

    response = api.abate_notice(
        notice["id"], payload, make_operator_headers(interloper["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_PERMIT_OPERATOR, 403)
    assert refresh_notice(notice["id"])["notice_status"] == "ISSUED", (
        "the interloper changed nothing"
    )

    abated = validate_success(
        api.abate_notice(notice["id"], payload, ctx["operator_headers"])
    )
    assert abated["notice_status"] == "ABATED", "the rightful holder succeeds"
    assert refresh_permit(ctx["permit"]["id"])["compliance_posture"] == "COMPLIANT"


def test_an_unassigned_inspector_cannot_record_a_result():
    """This is ownership-checked at priority 6: the acting `X-User-ID` must equal
    the inspection's `inspector_id`, else `ERR_NOT_ASSIGNED_INSPECTOR`.

    Design: Corner/errors/unassigned_inspector_recording_result_rejected
    """
    ctx = chain_applied(
        operator_overrides={
            "legal_name": "Wrong Inspector Mining",
            "tangible_net_worth": 11700000.00,
            "fixed_assets_in_state": 5850000.00,
            "total_liabilities": 4290000.00,
            "net_income_prior_year": 290000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Wrong Inspector Pit", "county": "Sheridan", "total_acres": 190.00,
        },
        mining_plan_acres=70.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
    )
    assigned = register_inspector(
        full_name="Petra Halvorsen", certification_level="CERT_III", region="WEST"
    )
    other = register_inspector(
        full_name="Emeka Sunderland", certification_level="CERT_II", region="EAST"
    )
    inspection = schedule_release_inspection(
        ctx,
        scheduled_start="2026-08-04T09:00:00Z",
        duration_hours=3,
        inspector=assigned,
        inspection_type="ROUTINE",
    )

    response = api.record_inspection_result(
        inspection["id"],
        {"result": "PASS", "findings_note": "Nothing to report."},
        make_inspector_headers(other["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_INSPECTOR, 403)

    unchanged = refresh_inspection(inspection["id"])
    assert unchanged["status"] == "SCHEDULED", "the inspection is still open"
    assert unchanged["result"] is None
    assert unchanged["completed_at"] is None
    assert validate_success(
        api.get_inspector_profile(assigned["id"], PROGRAM_DIRECTOR)
    )["scheduled_inspection_count"] == 1, "the assignment still occupies its calendar"
    assert validate_success(
        api.get_inspector_profile(other["id"], PROGRAM_DIRECTOR)
    )["scheduled_inspection_count"] == 0, "the other inspector holds nothing"


def test_replaying_an_acceptance_or_a_result_recording_rejected():
    """The addressed row's own current state must admit the requested transition;
    terminal states admit nothing.

    Design: Corner/errors/duplicate_estimate_acceptance_and_result_recording_rejected
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Replayed Action Mining",
            "tangible_net_worth": 11800000.00,
            "fixed_assets_in_state": 5900000.00,
            "total_liabilities": 4300000.00,
            "net_income_prior_year": 300000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Replayed Action Pit", "county": "Nye", "total_acres": 250.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )
    assert ctx["estimate"]["status"] == "ACCEPTED", "the estimate was accepted once"
    fresh_version = refresh_permit(ctx["permit"]["id"])["version"]

    # The guard value is freshly read, so the stale-version check passes and the
    # estimate's own state is what refuses.
    response = api.accept_estimate(
        ctx["estimate"]["id"],
        {"expected_permit_version": fresh_version},
        PERMIT_REVIEWER,
    )
    validate_error(response, ApiErrorId.ERR_ESTIMATE_STATE_INVALID, 409)
    assert validate_success(
        api.get_estimate(ctx["estimate"]["id"], PERMIT_REVIEWER)
    )["status"] == "ACCEPTED"
    assert_money(
        refresh_permit(ctx["permit"]["id"])["bond_required_amount"],
        865998.00,
        "bond_required_amount — the replay re-derived nothing",
    )

    inspection = schedule_release_inspection(
        ctx,
        scheduled_start="2026-08-04T09:00:00Z",
        duration_hours=3,
        inspection_type="ROUTINE",
    )
    recorded = validate_success(
        api.record_inspection_result(
            inspection["id"],
            {"result": "PASS", "findings_note": "Baseline conditions documented."},
            ctx["inspector_headers"],
        )
    )
    assert recorded["status"] == "COMPLETED"

    replay = api.record_inspection_result(
        inspection["id"],
        {"result": "VIOLATIONS_FOUND", "findings_note": "Second look at the same day."},
        ctx["inspector_headers"],
    )
    validate_error(replay, ApiErrorId.ERR_INSPECTION_STATE_INVALID, 409)
    assert refresh_inspection(inspection["id"])["result"] == "PASS", (
        "the first recording stands"
    )


def test_replaying_an_assessment_or_a_decided_revision_action_rejected():
    """**Civil penalty assessment** is a separate `ProgramDirector` act, admitted
    only while `penalty_status` is `NONE` (else `ERR_PENALTY_STATE_INVALID`) and
    only while `notice_status` is `ISSUED`, `CESSATION_ORDERED`, or `ABATED`
    (else `ERR_NOTICE_STATE_INVALID`).

    Design: Corner/errors/duplicate_penalty_assessment_and_decided_revision_action_rejected
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Replayed Decision Mining",
            "tangible_net_worth": 15900000.00,
            "fixed_assets_in_state": 7900000.00,
            "total_liabilities": 5300000.00,
            "net_income_prior_year": 660000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Replayed Decision Pit", "county": "Elko", "total_acres": 320.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
    )
    setup_assessed_penalty(
        ctx,
        good_faith_level="NONE",
        inspection_overrides={
            "scheduled_start": "2026-08-04T09:00:00Z", "duration_hours": 3,
        },
        **FORTY_FIVE_POINT_NOTICE,
    )
    # base 45 x 60.00 = 2700.00 with no credit and no surcharge.
    assert_money(ctx["notice"]["penalty_amount"], 2700.00, "penalty_amount")

    replay = api.assess_penalty(
        ctx["notice"]["id"], {"good_faith_level": "RAPID"}, PROGRAM_DIRECTOR
    )
    validate_error(replay, ApiErrorId.ERR_PENALTY_STATE_INVALID, 409)
    notice = refresh_notice(ctx["notice"]["id"])
    assert notice["penalty_status"] == "ASSESSED"
    assert_money(notice["penalty_amount"], 2700.00, "penalty_amount")
    assert notice["good_faith_level"] == "NONE", (
        "the RAPID credit is not retroactively applied"
    )

    revision = file_permit_revision(
        ctx, "SEQUENCE_CHANGE",
        sequence_note="Advance the south panel before the north panel.",
    )
    approved = validate_success(
        api.decide_permit_revision(
            revision["id"], {"decision": "APPROVE"}, PERMIT_REVIEWER
        )
    )
    assert approved["status"] == "APPROVED"

    late_request = api.request_revision_info(
        revision["id"],
        {"info_request_note": "Send the updated sequencing map after all."},
        PERMIT_REVIEWER,
    )
    validate_error(late_request, ApiErrorId.ERR_REVISION_STATE_INVALID, 409)
    settled = refresh_revision(revision["id"])
    assert settled["status"] == "APPROVED", "a decided revision admits nothing"
    assert settled["round_count"] == 1, "no round was consumed"


def test_the_cessation_threshold_boundary_sits_at_seventy_points():
    """At least one of three criteria must hold, checked at priority 11: the
    notice's `total_points` is at least 70, or the logical clock's current instant
    is past the notice's `abatement_deadline`, or the notice's `violation_class`
    is `IMMINENT_HARM`.

    Design: Corner/cross_cutting_complexity_layers/cessation_point_threshold_boundary_is_seventy_points
    """
    inspector = register_inspector(
        full_name="Sable Ortiz", certification_level="CERT_III", region="CENTRAL"
    )
    at_threshold = chain_applied(
        operator_overrides={
            "legal_name": "Seventy Point Mining",
            "tangible_net_worth": 11900000.00,
            "fixed_assets_in_state": 5950000.00,
            "total_liabilities": 4310000.00,
            "net_income_prior_year": 310000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Seventy Point Pit", "county": "Sheridan", "total_acres": 195.00,
        },
        mining_plan_acres=70.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
    )
    below_threshold = chain_applied(
        operator_overrides={
            "legal_name": "Sixty Nine Point Mining",
            "tangible_net_worth": 12000000.00,
            "fixed_assets_in_state": 6000000.00,
            "total_liabilities": 4320000.00,
            "net_income_prior_year": 320000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Sixty Nine Point Pit", "county": "Sheridan", "total_acres": 200.00,
        },
        mining_plan_acres=70.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
    )

    notice_x = setup_violation_notice(
        at_threshold,
        inspection_overrides={
            "scheduled_start": "2026-08-03T09:00:00Z",
            "duration_hours": 3,
            "inspector": inspector,
        },
        violation_class="NON_COMPLIANCE",
        severity_points=30,
        negligence_points=25,
        duration_points=15,
        abatement_days=30,
    )
    notice_y = setup_violation_notice(
        below_threshold,
        inspection_overrides={
            "scheduled_start": "2026-08-03T13:00:00Z",
            "duration_hours": 3,
            "inspector": inspector,
        },
        violation_class="NON_COMPLIANCE",
        severity_points=30,
        negligence_points=24,
        duration_points=15,
        abatement_days=30,
    )
    assert notice_x["total_points"] == 70, "30 + 25 + 15 points"
    assert notice_y["total_points"] == 69, "one negligence point fewer"
    assert notice_x["history_points"] == 0 and notice_y["history_points"] == 0, (
        "the two notices belong to unrelated operators, so neither accrues history"
    )

    ordered = order_cessation(
        at_threshold, notice_x["id"], "Point total reached the cessation threshold."
    )
    assert ordered["notice_status"] == "CESSATION_ORDERED", "seventy points suffices"
    assert refresh_permit(at_threshold["permit"]["id"])["compliance_posture"] == "CESSATION"

    response = api.order_cessation(
        notice_y["id"],
        {"cessation_reason": "Point total reached the cessation threshold."},
        below_threshold["inspector_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CESSATION_CRITERIA_NOT_MET, 409)

    refused = refresh_notice(notice_y["id"])
    assert refused["notice_status"] == "ISSUED", "sixty-nine points is not enough"
    assert refused["abatement_deadline"].startswith("2026-08-31"), (
        "the abatement window is still open, so that criterion cannot carry it"
    )
    assert refresh_permit(below_threshold["permit"]["id"])["compliance_posture"] == (
        "NOTICE_ACTIVE"
    ), "only the notice band applies to the second permit"
