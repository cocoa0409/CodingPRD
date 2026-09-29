"""The release decision gate ladder, its money effects, and its undo."""
from test_helpers import (
    BOND_SPECIALIST_DECIDER,
    PROGRAM_DIRECTOR,
    ApiErrorId,
    api_client as api,
    assert_money,
    assert_permit_ledger_invariants,
    assert_release_application,
    chain_issued,
    decide_release,
    enter_reclamation_phase,
    file_public_comment,
    file_release_application,
    issue_violation_notice,
    publish_release_notice,
    record_inspection_result,
    refresh_application,
    refresh_instrument,
    refresh_notice,
    refresh_permit,
    register_inspector,
    schedule_release_inspection,
    set_clock,
    setup_approved_release,
    setup_release_under_notice,
    validate_error,
    validate_success,
)

MEADOWLARK_OPERATOR = {
    "legal_name": "Meadowlark Coal Company",
    "tangible_net_worth": 21000000.00,
    "fixed_assets_in_state": 10000000.00,
    "total_liabilities": 7000000.00,
    "net_income_prior_year": 1100000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
MEADOWLARK_SITE = {
    "name": "Meadowlark South", "county": "Musselshell", "total_acres": 500.00,
}

WILLOW_DRAW_OPERATOR = {
    "legal_name": "Willow Draw Aggregates",
    "tangible_net_worth": 19000000.00,
    "fixed_assets_in_state": 9500000.00,
    "total_liabilities": 6500000.00,
    "net_income_prior_year": 1000000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
WILLOW_DRAW_SITE = {
    "name": "Willow Draw Pit", "county": "Converse", "total_acres": 420.00,
}

ANTLER_CREEK_OPERATOR = {
    "legal_name": "Antler Creek Mining",
    "tangible_net_worth": 20000000.00,
    "fixed_assets_in_state": 10000000.00,
    "total_liabilities": 7000000.00,
    "net_income_prior_year": 1200000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
ANTLER_CREEK_SITE = {
    "name": "Antler Creek Mine", "county": "Fremont", "total_acres": 460.00,
}


def _meadowlark_decision_inside_the_notice_window():
    """A PHASE_I release under notice until 2026-09-14, an unabated notice, and
    a passed RELEASE inspection, with the clock parked at 2026-08-20."""
    ctx = chain_issued(
        operator_overrides=MEADOWLARK_OPERATOR,
        site_overrides=MEADOWLARK_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
    )
    application = file_release_application(ctx, phase="PHASE_I", acres_requested=30.00)

    set_clock("2026-08-15T00:00:00Z")
    ctx["application"] = publish_release_notice(application["id"])

    inspector = register_inspector(
        full_name="Ivo Krause", certification_level="CERT_III", region="NORTH"
    )
    release_inspection = schedule_release_inspection(
        ctx, scheduled_start="2026-08-16T09:00:00Z", duration_hours=4,
        inspector=inspector, inspection_type="RELEASE",
    )
    routine_inspection = schedule_release_inspection(
        ctx, scheduled_start="2026-08-17T09:00:00Z", duration_hours=3,
        inspector=inspector, inspection_type="ROUTINE",
    )

    set_clock("2026-08-20T00:00:00Z")
    release_result = record_inspection_result(
        ctx, release_inspection["id"], result="PASS",
        findings_note="Phase I revegetation stand established on the claimed acreage.",
    )
    ctx["inspection"] = record_inspection_result(
        ctx, routine_inspection["id"], result="VIOLATIONS_FOUND",
        findings_note="Spoil placed outside the approved disposal area.",
    )
    ctx["notice"] = issue_violation_notice(
        ctx,
        violation_class="NON_COMPLIANCE",
        severity_points=20,
        negligence_points=15,
        duration_points=10,
        abatement_days=30,
    )
    # The decision must cite the RELEASE inspection, not the routine one.
    ctx["inspection"] = release_result
    return ctx


def test_an_unabated_violation_outranks_the_unelapsed_notice_period():
    """At priority 12, the logical clock's current instant must be strictly after
    the application's `notice_end_date`, else `ERR_NOTICE_PERIOD_NOT_ELAPSED` —
    and, as §2.5 stresses, an application that trips both this and the
    unabated-violation check reports the violation.

    Design: Difficulty/priority_pair_validation_conflict/unabated_violation_outranks_notice_period_on_release_decision
    """
    ctx = _meadowlark_decision_inside_the_notice_window()
    assert ctx["application"]["notice_end_date"].startswith("2026-09-14"), (
        "thirty days after the 2026-08-15 publication"
    )
    assert ctx["notice"]["notice_status"] == "ISSUED", "the notice is unabated"

    response = api.decide_release_application(
        ctx["application"]["id"],
        {"decision": "APPROVE", "inspection_id": ctx["inspection"]["id"]},
        BOND_SPECIALIST_DECIDER,
    )
    # The clock reads 2026-08-20, inside the notice window, so both the
    # priority 11 and the priority 12 gate are violated at once.
    body = validate_error(response, ApiErrorId.ERR_UNABATED_VIOLATION, 409)
    assert body["error_id"] != ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED.value, (
        "the lower-priority temporal complaint must not be the one reported"
    )

    application = refresh_application(ctx["application"]["id"])
    assert application["status"] == "PUBLIC_NOTICE", "the refused decision moved nothing"
    assert_money(application["approved_amount"], 0.00, "approved_amount")
    assert application["decided_by_user_id"] is None, "no decider was recorded"

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(permit["bond_released_to_date"], 0.00, "bond_released_to_date")
    assert permit["compliance_posture"] == "NOTICE_ACTIVE", (
        "the unabated notice is what the posture reflects"
    )


def test_the_notice_period_gate_surfaces_once_the_violation_is_abated():
    """At priority 11, no violation notice on the permit may be in
    `notice_status` of `ISSUED` or `CESSATION_ORDERED`, else
    `ERR_UNABATED_VIOLATION`.

    Design: Difficulty/priority_pair_validation_conflict/unabated_violation_outranks_notice_period_on_release_decision
    """
    ctx = _meadowlark_decision_inside_the_notice_window()
    payload = {"decision": "APPROVE", "inspection_id": ctx["inspection"]["id"]}

    validate_error(
        api.decide_release_application(
            ctx["application"]["id"], payload, BOND_SPECIALIST_DECIDER
        ),
        ApiErrorId.ERR_UNABATED_VIOLATION,
        409,
    )

    validate_success(
        api.abate_notice(
            ctx["notice"]["id"],
            {"abatement_note": "Spoil recovered and regraded inside the disposal area."},
            ctx["operator_headers"],
        )
    )
    assert refresh_notice(ctx["notice"]["id"])["notice_status"] == "ABATED"

    # Only the temporal complaint is left, and the clock is still 2026-08-20.
    validate_error(
        api.decide_release_application(
            ctx["application"]["id"], payload, BOND_SPECIALIST_DECIDER
        ),
        ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED,
        409,
    )

    application = refresh_application(ctx["application"]["id"])
    assert application["status"] == "PUBLIC_NOTICE", "still out for notice"
    assert_money(application["approved_amount"], 0.00, "approved_amount")
    assert_money(
        refresh_permit(ctx["permit"]["id"])["bond_released_to_date"],
        0.00,
        "bond_released_to_date",
    )


def _willow_draw_with_a_scheduled_release_inspection():
    """A PHASE_I release whose notice has run out but whose cited RELEASE
    inspection is still SCHEDULED."""
    ctx = setup_release_under_notice(
        phase="PHASE_I",
        acres_requested=30.00,
        disturbed_acres=120.00,
        operator_overrides=WILLOW_DRAW_OPERATOR,
        site_overrides=WILLOW_DRAW_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )
    ctx["inspection"] = schedule_release_inspection(
        ctx,
        scheduled_start="2026-08-16T09:00:00Z",
        duration_hours=4,
        inspector=register_inspector(
            full_name="Nadia Feltrin", certification_level="CERT_III", region="EAST"
        ),
        inspection_type="RELEASE",
    )
    set_clock("2026-09-20T00:00:00Z")
    return ctx


def test_a_release_decision_on_a_scheduled_inspection_is_refused():
    """At priority 10, the cited inspection must belong to the same permit as the
    application, must have `inspection_type` of `RELEASE`, and must be in
    `COMPLETED`; for an `APPROVE` decision its `result` must additionally be
    `PASS`. Any of those failing is `ERR_INSPECTION_NOT_ELIGIBLE`.

    Design: Difficulty/cross_entity_state_dependency/release_decision_gated_on_release_inspection_state
    """
    ctx = _willow_draw_with_a_scheduled_release_inspection()
    assert ctx["inspection"]["status"] == "SCHEDULED", "nothing has been recorded yet"
    assert ctx["inspection"]["result"] is None, "a booked inspection carries no result"

    response = api.decide_release_application(
        ctx["application"]["id"],
        {"decision": "APPROVE", "inspection_id": ctx["inspection"]["id"]},
        BOND_SPECIALIST_DECIDER,
    )
    validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_ELIGIBLE, 409)

    application = refresh_application(ctx["application"]["id"])
    assert application["status"] == "PUBLIC_NOTICE", "the application did not move"
    assert application["inspection_id"] is None, "no inspection was recorded onto it"
    assert application["approved_at"] is None, "nothing was stamped"

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_released_to_date"], 0.00, "bond_released_to_date")
    assert_money(permit["phase1_released_acres"], 0.00, "phase1_released_acres")


def test_the_same_release_decision_succeeds_once_the_inspection_passes():
    """`PUBLIC_NOTICE → APPROVED` sets `status` to `APPROVED`, copies
    `requested_amount` into `approved_amount`, stamps `approved_at` with the
    logical clock's current value, records the cited inspection into the
    application's `inspection_id`, and writes the acting `X-User-ID` into
    `decided_by_user_id`.

    Design: Difficulty/cross_entity_state_dependency/release_decision_gated_on_release_inspection_state
    """
    ctx = _willow_draw_with_a_scheduled_release_inspection()
    inspection_id = ctx["inspection"]["id"]
    payload = {"decision": "APPROVE", "inspection_id": inspection_id}

    validate_error(
        api.decide_release_application(
            ctx["application"]["id"], payload, BOND_SPECIALIST_DECIDER
        ),
        ApiErrorId.ERR_INSPECTION_NOT_ELIGIBLE,
        409,
    )

    completed = record_inspection_result(
        ctx, inspection_id, result="PASS",
        findings_note="Phase I standards met on the thirty claimed acres.",
    )
    assert completed["status"] == "COMPLETED", "recording closes the inspection"
    assert completed["result"] == "PASS"
    inspector = validate_success(
        api.get_inspector_profile(ctx["inspector"]["id"], PROGRAM_DIRECTOR)
    )
    assert inspector["scheduled_inspection_count"] == 0, (
        "recording the result decrements the inspector's scheduled count"
    )

    approved = validate_success(
        api.decide_release_application(
            ctx["application"]["id"], payload, BOND_SPECIALIST_DECIDER
        )
    )
    assert_release_application(approved)
    assert approved["status"] == "APPROVED", "the identical call now succeeds"
    assert approved["inspection_id"] == inspection_id, "the cited inspection is recorded"
    assert approved["approved_at"] is not None, "approval is stamped"
    assert approved["decided_by_user_id"] == "bs-002", (
        f"the acting user is recorded, got {approved['decided_by_user_id']!r}"
    )
    # per-acre bond 865998.00 / 120.00 = 7216.65; 7216.65 x 30 x 0.60 = 129899.70
    assert_money(approved["approved_amount"], 129899.70, "approved_amount")

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_released_to_date"], 129899.70, "bond_released_to_date")
    assert_money(permit["bond_held_amount"], 770100.30, "bond_held_amount")
    assert_money(permit["phase1_released_acres"], 30.00, "phase1_released_acres")


def _antler_creek_approved_release():
    """A PHASE_I release approved for 129899.70 against a 900000.00 bond."""
    return setup_approved_release(
        phase="PHASE_I",
        acres_requested=30.00,
        disturbed_acres=120.00,
        operator_overrides=ANTLER_CREEK_OPERATOR,
        site_overrides=ANTLER_CREEK_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )


def test_rescission_puts_the_released_money_back_on_the_permit():
    """Rescission is a compensating action that restores the bond ledger to its
    pre-approval values: the permit's `bond_released_to_date` becomes its old
    value minus the application's `approved_amount`, rounded half up to two
    decimals; the phase acreage counter for the application's phase is
    decremented by `acres_requested`; the application's `approved_amount` is
    reset to 0.00 and its `rescission_reason` stored.

    Design: Difficulty/compensating_invariant/release_rescission_restores_permit_bond_money_ledger
    """
    ctx = _antler_creek_approved_release()
    before = ctx["permit"]
    assert_money(before["bond_released_to_date"], 129899.70, "bond_released_to_date")
    assert_money(before["bond_held_amount"], 770100.30, "bond_held_amount")
    assert_money(
        before["bond_held_amount"] + before["bond_released_to_date"],
        900000.00,
        "held plus released, the credited total",
    )

    reason = (
        "Post-release audit found the Phase I revegetation stand density was "
        "misreported."
    )
    rescinded = validate_success(
        api.rescind_release_application(
            ctx["application"]["id"], {"rescission_reason": reason}, PROGRAM_DIRECTOR
        )
    )
    assert rescinded["status"] == "RESCINDED", "the approval is undone"
    assert_money(rescinded["approved_amount"], 0.00, "approved_amount")
    assert rescinded["rescission_reason"] == reason, "the reason is stored"
    assert rescinded["version"] == ctx["application"]["version"] + 1, (
        "the rescission is one mutation of the application"
    )

    permit = refresh_permit(ctx["permit"]["id"])
    assert_permit_ledger_invariants(permit)
    assert_money(permit["bond_released_to_date"], 0.00, "bond_released_to_date")
    assert_money(permit["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(permit["phase1_released_acres"], 0.00, "phase1_released_acres")
    assert_money(permit["bond_deficiency_amount"], 0.00, "bond_deficiency_amount")


def test_rescission_recomputes_the_posture_without_rewriting_the_instrument():
    """The application's `version` and the permit's `version` are each
    incremented by 1. `RESCINDED` is terminal.

    Design: Difficulty/compensating_invariant/release_rescission_restores_permit_bond_money_ledger
    """
    ctx = _antler_creek_approved_release()
    permit_before = ctx["permit"]
    assert permit_before["compliance_posture"] == "BOND_DEFICIENT", (
        "the approval left 770100.30 held against 865998.00 required"
    )
    assert_money(permit_before["bond_deficiency_amount"], 95897.70, "bond_deficiency_amount")

    payload = {"rescission_reason": "The release inspection record was incomplete."}
    validate_success(
        api.rescind_release_application(
            ctx["application"]["id"], payload, PROGRAM_DIRECTOR
        )
    )

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["compliance_posture"] == "COMPLIANT", (
        "restoring the held bond clears the deficiency band"
    )
    assert permit["status"] == "ISSUED", "the status axis never moved"
    assert permit["version"] == permit_before["version"] + 1, (
        "the rescission is one mutation of the permit"
    )

    instrument = refresh_instrument(ctx["instrument"]["id"])
    assert instrument["status"] == "ACCEPTED", (
        "the compensation never rewrites instrument history"
    )
    assert_money(instrument["credited_amount"], 900000.00, "credited_amount")

    # RESCINDED admits nothing further.
    validate_error(
        api.rescind_release_application(
            ctx["application"]["id"], payload, PROGRAM_DIRECTOR
        ),
        ApiErrorId.ERR_RELEASE_STATE_INVALID,
        409,
    )


def test_approval_with_an_unresolved_objection_rejected():
    """At priority 14, an `APPROVE` requires either that `objection_count` be 0
    or that `objections_resolved` be true, else `ERR_OBJECTIONS_UNRESOLVED`.

    Design: Corner/errors/release_approval_with_unresolved_objection_rejected
    """
    ctx = setup_release_under_notice(
        phase="PHASE_I",
        acres_requested=30.00,
        disturbed_acres=120.00,
        operator_overrides={
            "legal_name": "Objected Release Mining",
            "tangible_net_worth": 15700000.00,
            "fixed_assets_in_state": 7750000.00,
            "total_liabilities": 5090000.00,
            "net_income_prior_year": 610000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Objected Release Pit", "county": "Gila", "total_acres": 340.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "FORESTLAND"},
    )
    objected = file_public_comment(
        ctx["application"]["id"],
        "Objection: the sediment pond has not been removed from the release area.",
        is_objection=True,
    )
    assert objected["objection_count"] == 1, "one objection stands on the record"
    assert objected["objections_resolved"] is False, "nothing has disposed of it"

    inspection = schedule_release_inspection(
        ctx, scheduled_start="2026-08-20T09:00:00Z", duration_hours=4
    )
    set_clock("2026-09-05T00:00:00Z")
    ctx["inspection"] = record_inspection_result(ctx, inspection["id"], result="PASS")

    payload = {"decision": "APPROVE", "inspection_id": inspection["id"]}
    validate_error(
        api.decide_release_application(
            ctx["application"]["id"], payload, BOND_SPECIALIST_DECIDER
        ),
        ApiErrorId.ERR_OBJECTIONS_UNRESOLVED,
        409,
    )
    assert refresh_application(ctx["application"]["id"])["status"] == "PUBLIC_NOTICE", (
        "the refused approval left the application out for notice"
    )

    validate_success(
        api.resolve_objections(
            ctx["application"]["id"],
            {"resolution_note": "Pond removal verified against the as-built survey."},
            BOND_SPECIALIST_DECIDER,
        )
    )
    approved = validate_success(
        api.decide_release_application(
            ctx["application"]["id"], payload, BOND_SPECIALIST_DECIDER
        )
    )
    assert approved["status"] == "APPROVED", "the disposed objection unblocks the same call"
    assert_money(approved["approved_amount"], 129899.70, "approved_amount")

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_released_to_date"], 129899.70, "bond_released_to_date")
    assert_money(permit["bond_held_amount"], 770100.30, "bond_held_amount")


def test_rescission_after_the_sixty_day_window_rejected():
    """This is admitted only while the application is in `APPROVED` (else
    `ERR_RELEASE_STATE_INVALID`), only while the permit's `status` is `ISSUED` or
    `RECLAMATION_PHASE` (else `ERR_PERMIT_STATE_INVALID`), and only while the
    logical clock's current instant is at or before sixty days after
    `approved_at` — a rescission attempted after that window has closed is
    `ERR_RESCISSION_WINDOW_CLOSED` at priority 12.

    Design: Corner/errors/rescission_after_window_closed_rejected
    """
    ctx = setup_approved_release(
        phase="PHASE_I",
        acres_requested=30.00,
        disturbed_acres=120.00,
        operator_overrides={
            "legal_name": "Late Rescission Mining",
            "tangible_net_worth": 15800000.00,
            "fixed_assets_in_state": 7800000.00,
            "total_liabilities": 5100000.00,
            "net_income_prior_year": 620000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Late Rescission Pit", "county": "Yavapai", "total_acres": 350.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "FORESTLAND"},
    )
    approved = ctx["application"]
    assert approved["approved_at"].startswith("2026-09-05T00:00:00"), (
        f"approved on the decision clock, got {approved['approved_at']!r}"
    )

    # Sixty days after 2026-09-05 is 2026-11-04, so 2026-11-10 is too late.
    set_clock("2026-11-10T00:00:00Z")
    response = api.rescind_release_application(
        approved["id"],
        {"rescission_reason": "Post-audit found the release inspection was incomplete."},
        PROGRAM_DIRECTOR,
    )
    validate_error(response, ApiErrorId.ERR_RESCISSION_WINDOW_CLOSED, 409)

    application = refresh_application(approved["id"])
    assert application["status"] == "APPROVED", "the approval stands"
    assert_money(application["approved_amount"], 129899.70, "approved_amount")
    assert application["rescission_reason"] is None, "no reason was stored"

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_released_to_date"], 129899.70, "the money stays released")
    assert_money(permit["bond_held_amount"], 770100.30, "bond_held_amount")
    assert_money(permit["phase1_released_acres"], 30.00, "phase1_released_acres")


def test_a_final_phase_approval_terminates_the_permit():
    """When it fires, every bond instrument on the permit still in `ACCEPTED`
    moves to `RELEASED`; the permit's `bond_released_to_date` becomes its old
    value plus its `bond_held_amount`, rounded half up to two decimals;
    `bond_held_amount` and `bond_deficiency_amount` are both set to 0.00; and the
    permit's `status` becomes `TERMINATED` with its `version` incremented by 1.

    Design: Corner/state_machines/phase3_release_approval_bubbles_permit_to_terminated
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Final Phase Mining",
            "tangible_net_worth": 16500000.00,
            "fixed_assets_in_state": 8200000.00,
            "total_liabilities": 5300000.00,
            "net_income_prior_year": 700000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Final Phase Pit", "county": "Wetzel", "total_acres": 265.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "FORESTLAND"},
        disturbed_acres=120.00,
        reclaimed_acres_credited=120.00,
    )
    enter_reclamation_phase(ctx)
    assert ctx["permit"]["status"] == "RECLAMATION_PHASE", "active mining has finished"

    application = file_release_application(ctx, phase="PHASE_III", acres_requested=120.00)
    # per-acre 7216.65; 7216.65 x 120 x 0.15 = 129899.70, and the PHASE_III
    # retention floor is the 10000.00 statutory minimum, leaving 890000.00 free.
    assert_money(application["requested_amount"], 129899.70, "requested_amount")
    ctx["application"] = publish_release_notice(application["id"])

    inspection = schedule_release_inspection(
        ctx,
        scheduled_start="2026-08-20T09:00:00Z",
        duration_hours=5,
        inspector=register_inspector(
            full_name="Wren Calloway", certification_level="CERT_III", region="EAST"
        ),
    )
    set_clock("2026-09-05T00:00:00Z")
    ctx["inspection"] = record_inspection_result(
        ctx, inspection["id"], result="PASS",
        findings_note="Phase III revegetation success standards met across 120 acres.",
    )

    approved = decide_release(ctx, "APPROVE")
    assert approved["status"] == "APPROVED"
    assert_money(approved["approved_amount"], 129899.70, "approved_amount")
    assert approved["decided_by_user_id"] == "bs-002"

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["phase3_released_acres"], 120.00, "phase3_released_acres")
    assert_money(permit["disturbed_acres"], 120.00, "disturbed_acres")
    assert permit["status"] == "TERMINATED", (
        "the final-phase approval bubbles the parent permit into its terminal state"
    )
    assert_money(permit["bond_released_to_date"], 900000.00, "bond_released_to_date")
    assert_money(permit["bond_held_amount"], 0.00, "bond_held_amount")
    assert_money(permit["bond_deficiency_amount"], 0.00, "bond_deficiency_amount")
    assert refresh_instrument(ctx["instrument"]["id"])["status"] == "RELEASED", (
        "the remaining accepted instrument is released with the permit"
    )
