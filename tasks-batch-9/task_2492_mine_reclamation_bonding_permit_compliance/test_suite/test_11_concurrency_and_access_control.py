"""Role authorisation, segregation of duties, and the permit version guard."""
from test_helpers import (
    BOND_SPECIALIST_ACCEPTER,
    BOND_SPECIALIST_ACCEPTER_ID,
    BOND_SPECIALIST_DECIDER,
    BOND_SPECIALIST_DECIDER_ID,
    PERMIT_REVIEWER,
    PROGRAM_DIRECTOR,
    PUBLIC_PARTICIPANT,
    ApiErrorId,
    api_client as api,
    assert_envelope_meta,
    assert_estimate,
    assert_money,
    assert_permit,
    assert_permit_ledger_invariants,
    assert_release_application,
    chain_applied,
    chain_issued,
    create_inspection_payload,
    create_operator_payload,
    create_permit_payload,
    decide_release,
    file_estimate,
    file_release_application,
    make_inspector_headers,
    make_operator_headers,
    refresh_application,
    refresh_inspection,
    refresh_instrument,
    refresh_permit,
    register_inspector,
    setup_nominated_legacy_site,
    setup_release_ready_for_decision,
    validate_error,
    validate_paginated,
    validate_success,
)

ROLE_MATRIX_OPERATOR = {
    "legal_name": "Role Matrix Mining",
    "tangible_net_worth": 16000000.00,
    "fixed_assets_in_state": 7900000.00,
    "total_liabilities": 5120000.00,
    "net_income_prior_year": 640000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
ROLE_MATRIX_SITE = {"name": "Role Matrix Pit", "county": "Pima", "total_acres": 300.00}

PUBLIC_READER_OPERATOR = {
    "legal_name": "Public Reader Mining",
    "tangible_net_worth": 16050000.00,
    "fixed_assets_in_state": 7920000.00,
    "total_liabilities": 5125000.00,
    "net_income_prior_year": 645000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
PUBLIC_READER_SITE = {"name": "Public Reader Pit", "county": "Pima", "total_acres": 260.00}

SHARED_READ_OPERATOR = {
    "legal_name": "Shared Read Mining",
    "tangible_net_worth": 16100000.00,
    "fixed_assets_in_state": 7940000.00,
    "total_liabilities": 5130000.00,
    "net_income_prior_year": 650000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
SHARED_READ_SITE = {"name": "Shared Read Pit", "county": "Pima", "total_acres": 265.00}

SEGREGATED_OPERATOR = {
    "legal_name": "Segregated Duties Mining",
    "tangible_net_worth": 16150000.00,
    "fixed_assets_in_state": 7960000.00,
    "total_liabilities": 5135000.00,
    "net_income_prior_year": 655000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
SEGREGATED_SITE = {
    "name": "Segregated Duties Pit", "county": "Pinal", "total_acres": 300.00,
}

TWO_ESTIMATES_OPERATOR = {
    "legal_name": "Two Estimates Mining",
    "tangible_net_worth": 16200000.00,
    "fixed_assets_in_state": 7980000.00,
    "total_liabilities": 5140000.00,
    "net_income_prior_year": 660000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
TWO_ESTIMATES_SITE = {
    "name": "Two Estimates Pit", "county": "Pinal", "total_acres": 280.00,
}

STALE_RECALC_OPERATOR = {
    "legal_name": "Stale Recalc Mining",
    "tangible_net_worth": 16250000.00,
    "fixed_assets_in_state": 8000000.00,
    "total_liabilities": 5145000.00,
    "net_income_prior_year": 665000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
STALE_RECALC_SITE = {"name": "Stale Recalc Pit", "county": "Pinal", "total_acres": 290.00}

DEARER_ESTIMATE = {
    "estimator_firm": "Basin Closure Consultants",
    "estimator_license_no": "RE-5290",
    "estimate_effective_date": "2026-07-01",
    "direct_cost_per_acre": 6500.00,
}


def test_no_role_may_invoke_an_operation_reserved_to_a_peer_role():
    """If both headers are present but the declared role does not appear in the
    authorised-role list for the addressed endpoint (see the table in §4), the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/peer_roles_cannot_invoke_each_others_exclusive_writes
    """
    ctx = chain_issued(
        operator_overrides=ROLE_MATRIX_OPERATOR,
        site_overrides=ROLE_MATRIX_SITE,
        mining_plan_acres=120.00,
        disturbed_acres=120.00,
    )
    inspector = register_inspector(
        full_name="Ingrid Halvorsen", certification_level="CERT_II", region="SOUTH"
    )
    inspection = validate_success(
        api.create_inspection(
            create_inspection_payload(
                ctx["permit"]["id"], inspector["id"],
                inspection_type="ROUTINE",
                scheduled_start="2026-08-10T09:00:00Z",
                duration_hours=3,
            ),
            PROGRAM_DIRECTOR,
        ),
        201,
    )
    application = file_release_application(ctx, phase="PHASE_I", acres_requested=30.00)

    # An Inspector may not register operators; that write belongs to ProgramDirector.
    validate_error(
        api.create_operator(
            create_operator_payload(
                legal_name="Inspector Founded Mining",
                tangible_net_worth=9000000.00,
                fixed_assets_in_state=4000000.00,
                total_liabilities=3000000.00,
                net_income_prior_year=100000.00,
            ),
            make_inspector_headers(inspector["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # A PermitReviewer may not file a permit application; that write is the Operator's.
    validate_error(
        api.create_permit(
            create_permit_payload(
                ctx["site"]["id"], ctx["operator"]["id"],
                mining_plan_acres=40.00,
                post_mining_land_use="CROPLAND",
                proposed_start_date="2026-10-01",
            ),
            PERMIT_REVIEWER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # An Operator may not decide its own application; issuance is the reviewer's.
    validate_error(
        api.decide_permit(
            ctx["permit"]["id"],
            {"decision": "DENY", "denial_reason": "Self-denying to test the role gate."},
            ctx["operator_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # A PermitReviewer may not accept financial security; that is the specialist's.
    validate_error(
        api.accept_bond_instrument(ctx["instrument"]["id"], PERMIT_REVIEWER),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # A ProgramDirector may not record an on-site result; only an Inspector may.
    validate_error(
        api.record_inspection_result(
            inspection["id"],
            {"result": "PASS", "findings_note": "Director signing off from the office."},
            PROGRAM_DIRECTOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # A BondSpecialist may not file a public comment; that is the public's channel.
    validate_error(
        api.file_public_comment(
            application["id"],
            {"comment_text": "Specialist posing as the public.", "is_objection": True},
            BOND_SPECIALIST_ACCEPTER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    _, operator_meta = validate_paginated(api.list_operators(PROGRAM_DIRECTOR))
    assert operator_meta["total_count"] == 1, "the refused registration stored nothing"
    _, permit_meta = validate_paginated(api.list_permits(PERMIT_REVIEWER))
    assert permit_meta["total_count"] == 1, "the refused application stored nothing"

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["status"] == "ISSUED", "the refused denial left the permit issued"
    assert permit["denial_reason"] is None, "no denial reason was ever stored"
    assert refresh_inspection(inspection["id"])["status"] == "SCHEDULED", (
        "the refused result recording left the inspection scheduled"
    )
    assert refresh_instrument(ctx["instrument"]["id"])["status"] == "ACCEPTED", (
        "the instrument was already accepted and the refused call changed nothing"
    )

    stored_application = refresh_application(application["id"])
    assert_release_application(stored_application)
    assert stored_application["comment_count"] == 0, "the refused comment was not counted"
    assert stored_application["objection_count"] == 0, "nor was it counted as an objection"


def test_a_public_participant_reads_the_docket_but_not_the_bond_desk():
    """**Role authorisation.** The declared role appears in the endpoint's
    authorised-role list, else `ERR_UNAUTHORIZED`.

    Design: Corner/rbac/public_participant_cannot_read_inspector_or_bond_records
    """
    ctx = chain_applied(
        operator_overrides=PUBLIC_READER_OPERATOR,
        site_overrides=PUBLIC_READER_SITE,
        mining_plan_acres=80.00,
    )
    register_inspector(
        full_name="Marcus Oyelaran", certification_level="CERT_I", region="SOUTH"
    )
    legacy_site = setup_nominated_legacy_site(
        site_overrides={
            "name": "Public Reader Legacy Adit", "county": "Pima", "total_acres": 90.00,
        },
        hazard_class="H2_HIGH",
        public_safety_score=40,
        water_quality_score=30,
        acres_affected=40.00,
        unfunded_reclamation_need=350000.00,
    )
    permit_id = ctx["permit"]["id"]

    validate_error(
        api.list_inspector_profiles(PUBLIC_PARTICIPANT),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.list_bond_instruments(PUBLIC_PARTICIPANT),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.list_estimates(PUBLIC_PARTICIPANT),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.get_bond_summary(permit_id, PUBLIC_PARTICIPANT),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    permit = validate_success(api.get_permit(permit_id, PUBLIC_PARTICIPANT))
    assert_permit(permit)
    assert permit["status"] == "APPLICATION_SUBMITTED", (
        "the permit record itself is a public read"
    )

    notices, notice_meta = validate_paginated(
        api.list_permit_violation_notices(permit_id, PUBLIC_PARTICIPANT)
    )
    assert notice_meta["total_count"] == 0, "this permit has no violation notices"
    assert notices == [], "an empty docket is still readable by the public"

    queue, queue_meta = validate_paginated(
        api.list_legacy_funding_queue(PUBLIC_PARTICIPANT)
    )
    assert queue_meta["total_count"] == 1, "exactly one site has been nominated"
    assert queue[0]["id"] == legacy_site["id"], "the nominated adit is the queue entry"
    # H2_HIGH weight 30 + 40 x 0.30 + 30 x 0.20 + 2.00 acre points.
    assert_money(queue[0]["legacy_priority_score"], 50.00, "legacy_priority_score")


def test_all_six_declared_roles_read_the_shared_permit_and_site_records():
    """Six roles exist, spelled exactly as follows: `Operator`, `PermitReviewer`,
    `BondSpecialist`, `Inspector`, `ProgramDirector`, and `PublicParticipant`.

    Design: Corner/rbac/shared_read_endpoints_admit_all_six_declared_roles
    """
    ctx = chain_applied(
        operator_overrides=SHARED_READ_OPERATOR,
        site_overrides=SHARED_READ_SITE,
        mining_plan_acres=80.00,
        permit_overrides={"post_mining_land_use": "WILDLIFE_HABITAT"},
    )
    inspector = register_inspector(
        full_name="Priya Raghunathan", certification_level="CERT_III", region="SOUTH"
    )
    permit_id = ctx["permit"]["id"]

    readers = {
        "Operator": make_operator_headers(ctx["operator"]["id"]),
        "PermitReviewer": PERMIT_REVIEWER,
        "BondSpecialist": BOND_SPECIALIST_ACCEPTER,
        "Inspector": make_inspector_headers(inspector["id"]),
        "ProgramDirector": PROGRAM_DIRECTOR,
        "PublicParticipant": PUBLIC_PARTICIPANT,
    }
    for role, headers in readers.items():
        response = api.get_permit(permit_id, headers)
        permit = validate_success(response)
        assert_permit(permit)
        assert permit["status"] == "APPLICATION_SUBMITTED", (
            f"{role} must see the same permit status as every other role"
        )
        assert permit["id"] == permit_id
        assert_envelope_meta(response.json())

    site_response = api.get_mine_site(ctx["site"]["id"], PUBLIC_PARTICIPANT)
    site = validate_success(site_response)
    assert site["site_class"] == "ACTIVE_PERMITTED", (
        "the default site class applied at creation is publicly readable"
    )
    assert_envelope_meta(site_response.json())


def test_the_specialist_who_accepted_the_bond_may_not_decide_its_release():
    """When a bond release decision is submitted, the acting `X-User-ID` is
    compared against the `accepted_by_user_id` of **every** bond instrument on
    the application's permit whose status is `ACCEPTED`. If the acting id matches
    any one of them, the decision is refused with `ERR_SEGREGATION_OF_DUTIES` at
    HTTP 409.

    Design: Corner/rbac/same_specialist_cannot_accept_instrument_and_decide_release
    """
    ctx = setup_release_ready_for_decision(
        operator_overrides=SEGREGATED_OPERATOR,
        site_overrides=SEGREGATED_SITE,
        mining_plan_acres=120.00,
        phase="PHASE_I",
        acres_requested=30.00,
        disturbed_acres=120.00,
    )
    assert ctx["instrument"]["accepted_by_user_id"] == BOND_SPECIALIST_ACCEPTER_ID, (
        "the accepting specialist is recorded on the instrument"
    )
    assert ctx["application"]["status"] == "PUBLIC_NOTICE", (
        "the same specialist was allowed to publish the notice"
    )

    response = api.decide_release_application(
        ctx["application"]["id"],
        {"decision": "APPROVE", "inspection_id": ctx["inspection"]["id"]},
        BOND_SPECIALIST_ACCEPTER,
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

    parked = refresh_application(ctx["application"]["id"])
    assert parked["status"] == "PUBLIC_NOTICE", "the refused decision moved nothing"
    assert parked["decided_by_user_id"] is None, "no decider was recorded"
    assert_money(
        refresh_permit(ctx["permit"]["id"])["bond_released_to_date"],
        0.00,
        "bond_released_to_date",
    )

    approved = decide_release(ctx, "APPROVE", BOND_SPECIALIST_DECIDER)
    assert approved["status"] == "APPROVED", "a second, distinct specialist may decide"
    assert_money(approved["approved_amount"], 129899.70, "approved_amount")
    assert approved["decided_by_user_id"] == BOND_SPECIALIST_DECIDER_ID

    permit = refresh_permit(ctx["permit"]["id"])
    assert_permit_ledger_invariants(permit)
    assert_money(permit["bond_released_to_date"], 129899.70, "bond_released_to_date")
    assert_money(permit["bond_held_amount"], 770100.30, "bond_held_amount")


def test_an_estimate_acceptance_carrying_a_superseded_permit_version_is_refused():
    """`POST /mining/reclamation-cost-estimates/{id}/accept` must carry an
    `expected_permit_version` equal to the current `version` of the permit named
    by the estimate's `permit_id`. If some other writer has advanced that
    permit's `version` since the client last read it, the acceptance is rejected
    with `ERR_STALE_PERMIT_VERSION` at HTTP 412.

    Design: Corner/cross_cutting_complexity_layers/stale_permit_version_on_estimate_acceptance_rejected
    """
    ctx = chain_applied(
        operator_overrides=TWO_ESTIMATES_OPERATOR,
        site_overrides=TWO_ESTIMATES_SITE,
        mining_plan_acres=120.00,
    )
    permit_id = ctx["permit"]["id"]
    cheaper = file_estimate(
        permit_id, ctx["operator_headers"],
        estimate_effective_date="2026-07-01",
        direct_cost_per_acre=6000.00,
    )
    dearer = file_estimate(permit_id, ctx["operator_headers"], **DEARER_ESTIMATE)
    assert cheaper["status"] == "SUBMITTED" and dearer["status"] == "SUBMITTED", (
        "two estimates sit on the permit, each independently acceptable"
    )

    observed_version = refresh_permit(permit_id)["version"]

    accepted = validate_success(
        api.accept_estimate(
            dearer["id"], {"expected_permit_version": observed_version}, PERMIT_REVIEWER
        )
    )
    assert_estimate(accepted)
    assert accepted["status"] == "ACCEPTED", "the first acceptance carries a fresh version"
    # 6500.00 x 1.185 = 7702.50 per acre, x 120.00 = 924300.00, fee 13864.50.
    assert_money(
        refresh_permit(permit_id)["bond_required_amount"], 938164.50, "bond_required_amount"
    )

    response = api.accept_estimate(
        cheaper["id"], {"expected_permit_version": observed_version}, PERMIT_REVIEWER
    )
    validate_error(response, ApiErrorId.ERR_STALE_PERMIT_VERSION, 412)

    assert validate_success(api.get_estimate(cheaper["id"], PERMIT_REVIEWER))["status"] == (
        "SUBMITTED"
    ), "the refused acceptance left the cheaper estimate submitted"
    stale_read = refresh_permit(permit_id)
    assert_money(stale_read["bond_required_amount"], 938164.50, "bond_required_amount")
    assert stale_read["version"] == observed_version + 1, (
        "only the successful acceptance advanced the permit"
    )

    superseding = validate_success(
        api.accept_estimate(
            cheaper["id"],
            {"expected_permit_version": stale_read["version"]},
            PERMIT_REVIEWER,
        )
    )
    assert superseding["status"] == "ACCEPTED", "the re-read version is accepted"
    assert validate_success(api.get_estimate(dearer["id"], PERMIT_REVIEWER))["status"] == (
        "SUPERSEDED"
    ), "a permit never has two accepted estimates at once"

    permit = refresh_permit(permit_id)
    # 6000.00 x 1.185 = 7110.00 per acre, x 120.00 = 853200.00, fee 12798.00.
    assert_money(permit["bond_required_amount"], 865998.00, "bond_required_amount")
    assert permit["version"] == observed_version + 2, "two acceptances, two increments"


def test_a_bond_recalculation_carrying_a_superseded_permit_version_is_refused():
    """`POST /mining/permits/{id}/recalculate-bond` must likewise carry an
    `expected_permit_version` equal to the addressed permit's current `version`,
    and a mismatch is rejected with `ERR_STALE_PERMIT_VERSION` at HTTP 412.

    Design: Corner/cross_cutting_complexity_layers/stale_permit_version_on_bond_recalculation_rejected
    """
    ctx = chain_issued(
        operator_overrides=STALE_RECALC_OPERATOR,
        site_overrides=STALE_RECALC_SITE,
        mining_plan_acres=120.00,
        direct_cost_per_acre=6000.00,
        disturbed_acres=60.00,
    )
    permit_id = ctx["permit"]["id"]
    assert_money(ctx["permit"]["bond_required_amount"], 865998.00, "bond_required_amount")

    dearer = file_estimate(permit_id, ctx["operator_headers"], **DEARER_ESTIMATE)
    observed_version = refresh_permit(permit_id)["version"]
    validate_success(
        api.accept_estimate(
            dearer["id"], {"expected_permit_version": observed_version}, PERMIT_REVIEWER
        )
    )

    response = api.recalculate_bond(
        permit_id,
        {"basis": "INCREMENTAL", "expected_permit_version": observed_version},
        BOND_SPECIALIST_ACCEPTER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_PERMIT_VERSION, 412)

    unchanged = refresh_permit(permit_id)
    assert unchanged["bond_basis"] == "FULL_PLAN", "the refused call did not switch the basis"
    assert_money(unchanged["bond_required_amount"], 938164.50, "bond_required_amount")
    assert unchanged["version"] == observed_version + 1, (
        "the newer estimate's acceptance is what advanced the permit"
    )

    recalculated = validate_success(
        api.recalculate_bond(
            permit_id,
            {"basis": "INCREMENTAL", "expected_permit_version": unchanged["version"]},
            BOND_SPECIALIST_ACCEPTER,
        )
    )
    assert_permit_ledger_invariants(recalculated)
    assert recalculated["bond_basis"] == "INCREMENTAL", "the retry writes the new basis"
    # The newer 7702.50 loaded cost x 60.00 unreclaimed acres = 462150.00, fee 6932.25.
    assert_money(recalculated["bond_required_amount"], 469082.25, "bond_required_amount")
    assert_money(recalculated["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(recalculated["bond_deficiency_amount"], 0.00, "bond_deficiency_amount")
    assert recalculated["compliance_posture"] == "COMPLIANT", (
        "the held bond now covers the incremental requirement"
    )
