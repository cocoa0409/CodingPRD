"""The permit's two independent state axes, and the revision review cycle."""
from test_helpers import (
    PERMIT_REVIEWER,
    ApiErrorId,
    api_client as api,
    assert_money,
    assert_violation_point_invariants,
    chain_issued,
    create_permit_revision_payload,
    enter_reclamation_phase,
    file_permit_revision,
    file_release_application,
    publish_release_notice,
    refresh_application,
    refresh_permit,
    refresh_revision,
    register_inspector,
    setup_violation_notice,
    validate_error,
    validate_paginated,
    validate_success,
)

WINTERHAWK_OPERATOR = {
    "legal_name": "Winterhawk Sand & Gravel",
    "tangible_net_worth": 16000000.00,
    "fixed_assets_in_state": 8000000.00,
    "total_liabilities": 5000000.00,
    "net_income_prior_year": 700000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
WINTERHAWK_SITE = {"name": "Winterhawk Bar", "county": "Grand", "total_acres": 260.00}

BLACKROCK_OPERATOR = {
    "legal_name": "Blackrock Quarry Partners",
    "tangible_net_worth": 14000000.00,
    "fixed_assets_in_state": 7000000.00,
    "total_liabilities": 5000000.00,
    "net_income_prior_year": 600000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
BLACKROCK_SITE = {
    "name": "Blackrock North Bench", "county": "Lincoln", "total_acres": 240.00,
}

GRANITE_FORK_OPERATOR = {
    "legal_name": "Granite Fork Mining LLC",
    "tangible_net_worth": 22000000.00,
    "fixed_assets_in_state": 11000000.00,
    "total_liabilities": 8000000.00,
    "net_income_prior_year": 1400000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
GRANITE_FORK_SITE = {"name": "Granite Fork Mine", "county": "Elko", "total_acres": 600.00}


def _winterhawk_under_notice():
    """An ISSUED, 120-acre-disturbed permit carrying one ISSUED violation notice."""
    ctx = chain_issued(
        operator_overrides=WINTERHAWK_OPERATOR,
        site_overrides=WINTERHAWK_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "WILDLIFE_HABITAT"},
        disturbed_acres=120.00,
    )
    setup_violation_notice(
        ctx,
        inspection_overrides={
            "scheduled_start": "2026-08-12T08:00:00Z",
            "duration_hours": 3,
            "inspector": register_inspector(
                full_name="Marta Ocasio", certification_level="CERT_II", region="WEST"
            ),
        },
        severity_points=20,
        negligence_points=15,
        duration_points=10,
        abatement_days=30,
    )
    return ctx


def test_a_violation_notice_moves_the_posture_and_leaves_the_status_alone():
    """A permit's regulatory standing is tracked on a second, independent
    dimension called `compliance_posture`, whose value is always derived — never
    set directly by a client. `NOTICE_ACTIVE`, when any violation notice on the
    permit has `notice_status` of `ISSUED`.

    Design: Difficulty/non_linear_state_machine/permit_status_and_compliance_posture_advance_independently
    """
    ctx = _winterhawk_under_notice()

    notice = ctx["notice"]
    assert_violation_point_invariants(notice)
    assert notice["total_points"] == 45, (
        f"20 + 15 + 10 severity, negligence and duration points, got "
        f"{notice['total_points']}"
    )
    assert notice["notice_status"] == "ISSUED", "a new notice is ISSUED"

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["compliance_posture"] == "NOTICE_ACTIVE", (
        "the unabated notice moves the posture axis"
    )
    assert permit["status"] == "ISSUED", (
        "the status axis is untouched by a violation notice"
    )
    assert_money(permit["bond_held_amount"], 900000.00, "bond_held_amount")


def test_cease_mining_moves_the_status_and_leaves_the_posture_alone():
    """When active mining finishes, the `Operator` declares the transition into
    reclamation, moving the permit `ISSUED → RECLAMATION_PHASE`.

    Design: Difficulty/non_linear_state_machine/permit_status_and_compliance_posture_advance_independently
    """
    ctx = _winterhawk_under_notice()
    before = refresh_permit(ctx["permit"]["id"])
    assert before["compliance_posture"] == "NOTICE_ACTIVE"
    assert before["status"] == "ISSUED"

    enter_reclamation_phase(ctx)
    permit = refresh_permit(ctx["permit"]["id"])

    assert permit["status"] == "RECLAMATION_PHASE", "the status axis advances"
    assert permit["compliance_posture"] == "NOTICE_ACTIVE", (
        "the notice is still unabated, so the posture axis does not move back"
    )
    assert permit["version"] == before["version"] + 1, "cease-mining is one mutation"
    assert_money(permit["bond_held_amount"], 900000.00, "bond_held_amount")


def _blackrock_revision():
    """An ISSUED, COMPLIANT permit carrying one SUBMITTED SEQUENCE_CHANGE revision."""
    ctx = chain_issued(
        operator_overrides=BLACKROCK_OPERATOR,
        site_overrides=BLACKROCK_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "INDUSTRIAL"},
    )
    ctx["revision"] = file_permit_revision(
        ctx, "SEQUENCE_CHANGE",
        sequence_note="Advance the west highwall cut ahead of the east bench.",
    )
    return ctx


def test_an_answered_information_request_returns_the_revision_to_submitted():
    """A `PermitReviewer` who needs more material moves the revision
    `SUBMITTED → INFO_REQUESTED` while recording an `info_request_note`. The
    operator answers by moving it `INFO_REQUESTED → SUBMITTED` with a
    `response_note`, which increments `round_count` by 1.

    Design: Difficulty/non_linear_state_machine/permit_revision_info_request_cycle_bounded_by_round_cap
    """
    ctx = _blackrock_revision()
    revision_id = ctx["revision"]["id"]
    assert ctx["revision"]["status"] == "SUBMITTED", "a new revision starts SUBMITTED"
    assert ctx["revision"]["round_count"] == 1, "round_count starts at 1"

    asked = validate_success(
        api.request_revision_info(
            revision_id,
            {"info_request_note": "Provide the revised pit sequencing map."},
            PERMIT_REVIEWER,
        )
    )
    assert asked["status"] == "INFO_REQUESTED", "the reviewer parks the revision"
    assert asked["info_request_note"] == "Provide the revised pit sequencing map."
    assert asked["round_count"] == 1, "asking does not consume a round"

    answered = validate_success(
        api.resubmit_revision(
            revision_id,
            {"response_note": "Sequencing map attached, revision A."},
            ctx["operator_headers"],
        )
    )
    assert answered["status"] == "SUBMITTED", "the cycle returns to SUBMITTED"
    assert answered["response_note"] == "Sequencing map attached, revision A."
    assert answered["round_count"] == 2, "the answer consumes one round"
    assert_money(
        refresh_permit(ctx["permit"]["id"])["mining_plan_acres"],
        120.00,
        "mining_plan_acres",
    )


def test_a_revision_that_has_consumed_its_rounds_cannot_be_resubmitted():
    """That cycle is bounded: a resubmission is admitted only while `round_count`
    is strictly below 2, so a revision that has already consumed its rounds is
    refused with `ERR_REVISION_ROUND_LIMIT` at priority 13.

    Design: Difficulty/non_linear_state_machine/permit_revision_info_request_cycle_bounded_by_round_cap
    """
    ctx = _blackrock_revision()
    revision_id = ctx["revision"]["id"]

    validate_success(
        api.request_revision_info(
            revision_id,
            {"info_request_note": "Provide the revised pit sequencing map."},
            PERMIT_REVIEWER,
        )
    )
    consumed = validate_success(
        api.resubmit_revision(
            revision_id,
            {"response_note": "Sequencing map attached, revision A."},
            ctx["operator_headers"],
        )
    )
    assert consumed["round_count"] == 2, "the single admissible round is now spent"

    validate_success(
        api.request_revision_info(
            revision_id,
            {"info_request_note": "Map lacks the drainage overlay."},
            PERMIT_REVIEWER,
        )
    )
    response = api.resubmit_revision(
        revision_id,
        {"response_note": "Drainage overlay added, revision B."},
        ctx["operator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_REVISION_ROUND_LIMIT, 409)

    revision = refresh_revision(revision_id)
    assert revision["status"] == "INFO_REQUESTED", (
        "the refused resubmission leaves the revision parked"
    )
    assert revision["round_count"] == 2, "the cap holds at 2"
    assert_money(
        refresh_permit(ctx["permit"]["id"])["mining_plan_acres"],
        120.00,
        "mining_plan_acres — no revision was approved",
    )


def _granite_fork_expansion():
    """A published PHASE_I release plus a SUBMITTED 60-acre EXPANSION revision."""
    ctx = chain_issued(
        operator_overrides=GRANITE_FORK_OPERATOR,
        site_overrides=GRANITE_FORK_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
    )
    application = file_release_application(ctx, phase="PHASE_I", acres_requested=30.00)
    ctx["application"] = publish_release_notice(application["id"])
    ctx["revision"] = file_permit_revision(ctx, "EXPANSION", acreage_delta=60.00)
    ctx["permit"] = refresh_permit(ctx["permit"]["id"])
    return ctx


def test_expansion_approval_enlarges_the_plan_and_reprices_the_bond():
    """For an `EXPANSION`, the permit's `mining_plan_acres` becomes its old value
    plus `acreage_delta`, rounded half up to two decimals, and
    `bond_required_amount` is re-derived under the permit's current `bond_basis`.

    Design: Difficulty/transitive_cascade/expansion_revision_approval_cascade_suspends_public_notice
    """
    ctx = _granite_fork_expansion()
    assert_money(ctx["permit"]["bond_required_amount"], 865998.00, "bond_required_amount")
    assert ctx["permit"]["compliance_posture"] == "COMPLIANT"

    approved = validate_success(
        api.decide_permit_revision(
            ctx["revision"]["id"], {"decision": "APPROVE"}, PERMIT_REVIEWER
        )
    )
    assert approved["status"] == "APPROVED", "the revision is approved"
    assert approved["decided_at"] is not None, "approval stamps decided_at"

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["mining_plan_acres"], 180.00, "mining_plan_acres")
    # 7110.00 loaded per acre x 180.00 = 1279800.00 subtotal, + 19197.00 fee
    assert_money(permit["bond_required_amount"], 1298997.00, "bond_required_amount")
    assert_money(permit["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(permit["bond_released_to_date"], 0.00, "bond_released_to_date")
    assert_money(permit["bond_deficiency_amount"], 398997.00, "bond_deficiency_amount")
    assert permit["compliance_posture"] == "BOND_DEFICIENT", (
        "the raised requirement now outruns the held bond"
    )


def test_expansion_approval_suspends_the_published_release_and_clears_its_window():
    """An application that was in `PUBLIC_NOTICE` additionally has its
    `notice_start_date` and `notice_end_date` cleared to null, and the permit's
    `last_notice_end_date` is recomputed as the greatest `notice_end_date` still
    held by a non-suspended application on that permit, or null when none
    remains.

    Design: Difficulty/transitive_cascade/expansion_revision_approval_cascade_suspends_public_notice
    """
    ctx = _granite_fork_expansion()
    published = ctx["application"]
    assert published["status"] == "PUBLIC_NOTICE", "the application is under notice"
    assert published["notice_start_date"] is not None
    assert published["notice_end_date"] is not None
    assert ctx["permit"]["last_notice_end_date"] is not None

    validate_success(
        api.decide_permit_revision(
            ctx["revision"]["id"], {"decision": "APPROVE"}, PERMIT_REVIEWER
        )
    )

    application = refresh_application(published["id"])
    assert application["status"] == "SUSPENDED", (
        "the BOND_DEFICIENT posture drives the open application to SUSPENDED"
    )
    assert application["notice_start_date"] is None, "the notice window is cleared"
    assert application["notice_end_date"] is None, "the notice window is cleared"

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["last_notice_end_date"] is None, (
        "no non-suspended application still holds a notice window"
    )
    assert_money(permit["bond_held_amount"], 900000.00, "bond_held_amount")


def test_cease_mining_needs_broken_ground():
    """This is admitted only from `ISSUED`, requires `disturbed_acres` to be
    strictly greater than zero — a permit that never broke ground has nothing to
    reclaim — and is ownership-checked against the permit's `operator_id`.

    Design: Corner/endpoints/cease_mining_action_moves_permit_to_reclamation_phase
    """
    operator_overrides = {
        "legal_name": "Cease Mining Corp",
        "tangible_net_worth": 20000000.00,
        "fixed_assets_in_state": 9000000.00,
        "total_liabilities": 6000000.00,
        "net_income_prior_year": 800000.00,
        "elected_financial_test": "NET_WORTH_TEST",
    }
    broken_ground = chain_issued(
        operator_overrides=operator_overrides,
        site_overrides={
            "name": "Cease Mining Pit A", "county": "Campbell", "total_acres": 300.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
        disturbed_acres=120.00,
    )
    untouched = chain_issued(
        operator=broken_ground["operator"],
        site_overrides={
            "name": "Cease Mining Pit B", "county": "Campbell", "total_acres": 300.00,
        },
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )

    ceased = validate_success(
        api.cease_mining(broken_ground["permit"]["id"], broken_ground["operator_headers"])
    )
    assert ceased["status"] == "RECLAMATION_PHASE", "120 disturbed acres may be reclaimed"
    assert ceased["compliance_posture"] == "COMPLIANT", "the posture axis is untouched"
    assert_money(ceased["bond_held_amount"], 900000.00, "bond_held_amount")
    assert ceased["version"] == broken_ground["permit"]["version"] + 1

    assert_money(untouched["permit"]["disturbed_acres"], 0.00, "disturbed_acres")
    response = api.cease_mining(
        untouched["permit"]["id"], untouched["operator_headers"]
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_STATE_INVALID, 409)
    assert refresh_permit(untouched["permit"]["id"])["status"] == "ISSUED", (
        "a permit that never broke ground stays ISSUED"
    )


def test_expansion_revision_carrying_a_land_use_change_rejected():
    """An `EXPANSION` must carry `acreage_delta` — additional plan acreage,
    strictly greater than zero when present — and must not carry
    `new_post_mining_land_use`.

    Design: Corner/validations/expansion_revision_with_land_use_field_rejected
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Mixed Fields Mining",
            "tangible_net_worth": 14800000.00,
            "fixed_assets_in_state": 7300000.00,
            "total_liabilities": 4950000.00,
            "net_income_prior_year": 530000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Mixed Fields Pit", "county": "Carbon", "total_acres": 300.00},
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )
    permit_id = ctx["permit"]["id"]

    response = api.create_permit_revision(
        create_permit_revision_payload(
            permit_id,
            revision_type="EXPANSION",
            acreage_delta=40.00,
            new_post_mining_land_use="INDUSTRIAL",
        ),
        ctx["operator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_REVISION_FIELDS_MISMATCH, 422)

    clean = validate_success(
        api.create_permit_revision(
            create_permit_revision_payload(
                permit_id, revision_type="EXPANSION", acreage_delta=40.00
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    assert clean["status"] == "SUBMITTED", "the correctly shaped revision is admitted"
    assert clean["round_count"] == 1, "round_count starts at 1"

    _, meta = validate_paginated(
        api.list_permit_revisions_for_permit(permit_id, PERMIT_REVIEWER)
    )
    assert meta["total_count"] == 1, "only the well-formed revision was stored"
    assert_money(
        refresh_permit(permit_id)["mining_plan_acres"],
        120.00,
        "mining_plan_acres — a submitted revision changes nothing yet",
    )
