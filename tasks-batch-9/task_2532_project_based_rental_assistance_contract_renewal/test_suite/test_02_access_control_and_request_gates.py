"""Envelope gates and the four-role access model: authentication, pagination, role lists,
segregation of duties and owner scoping."""
from test_helpers import (
    ApiErrorId,
    REFERENCE_HOUSEHOLD_ONE,
    TEST_USERS,
    api_client,
    approve_determination,
    assert_pagination_meta,
    create_owner_with_headers,
    create_property,
    create_property_payload,
    create_tenant_household_payload,
    create_ua_analysis,
    create_voucher_submission_payload,
    decide_study_payload,
    decide_utility_allowance_payload,
    make_raw_headers,
    setup_adjustment_elected,
    setup_case_with_accepted_study,
    setup_certified_household,
    setup_challenged_study,
    setup_evaluated_determination,
    setup_opt_out_noticed_case,
    setup_portfolio,
    setup_submitted_voucher,
    validate_error,
    validate_paginated,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_READER_HEADERS = TEST_USERS["contract_administrator_reader_headers"]
CA_SECOND_APPROVER_HEADERS = TEST_USERS["contract_administrator_second_approver_headers"]
HUD_HEADERS = TEST_USERS["hud_field_office_third_headers"]
PHA_HEADERS = TEST_USERS["pha_administrator_headers"]
CA_USER_ID = TEST_USERS["contract_administrator_user_id"]
CA_SECOND_APPROVER_USER_ID = TEST_USERS["contract_administrator_second_approver_user_id"]
HUD_USER_ID = TEST_USERS["hud_field_office_third_user_id"]

MAPLE_COURT = {
    "address_label": "418 Maple Court",
    "raw_rent_cents": 128649,
    "adjustment_total_cents": 55,
    "utility_adjustment_cents": 1500,
    "weight": 1,
}
LARKSPUR_WAY = {
    "address_label": "77 Larkspur Way",
    "raw_rent_cents": 141000,
    "adjustment_total_cents": 0,
    "utility_adjustment_cents": 0,
    "weight": 1,
}


def test_header_and_pagination_gates_answer_before_any_resource_is_touched():
    """"If either header is absent, or if `X-User-Role` is not exactly one of the four
    recognised role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)",
    and "A `limit` below 1 or above 100, or a negative `offset`, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)".

    Design: Corner/errors/header_and_pagination_gates_answer_before_any_resource_is_touched
    """
    owner, owner_headers = create_owner_with_headers()
    create_property(owner["id"], owner_headers)
    path = f"/pbra/owners/{owner['id']}"

    no_role = api_client.raw("GET", path, headers=make_raw_headers(owner["id"], None))
    validate_error(no_role, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
    assert "message" in no_role.json()["data"]

    no_user_id = api_client.raw(
        "GET", path, headers=make_raw_headers(None, "ContractAdministrator")
    )
    validate_error(no_user_id, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)

    unknown_role = api_client.raw(
        "GET", path, headers=make_raw_headers(CA_USER_ID, "Auditor")
    )
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)

    ghost_path = "/pbra/owners/00000000-0000-0000-0000-000000000000"
    unauthenticated_ghost = api_client.raw(
        "GET", ghost_path, headers=make_raw_headers(owner["id"], None)
    )
    validate_error(
        unauthenticated_ghost, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
    )

    for limit, offset in ((0, 0), (101, 0), (10, -1)):
        validate_error(
            api_client.list_owner_properties(
                owner["id"], CA_READER_HEADERS, limit=limit, offset=offset
            ),
            ApiErrorId.ERR_INVALID_PAGINATION.value,
            expected_status=400,
        )

    rows, meta = validate_paginated(
        api_client.list_owner_properties(owner["id"], CA_READER_HEADERS, limit=100, offset=0)
    )
    assert_pagination_meta(meta, limit=100, offset=0, total_count=1, has_more=False)
    assert len(rows) == 1, f"the inclusive maximum limit is admitted, got {len(rows)} rows"


def test_each_role_only_reaches_its_own_exclusive_operations():
    """"The acting role must appear in the endpoint's authorized-role list as published in
    §4; if it does not, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)", and the
    same call made by the one role §4 does list succeeds.

    Design: Corner/rbac/each_role_only_reaches_its_own_exclusive_operations
    """
    billing = setup_portfolio()
    setup_certified_household(
        billing["property"]["id"], billing["owner_headers"], REFERENCE_HOUSEHOLD_ONE
    )
    voucher = setup_submitted_voucher(
        billing["contract"]["id"], billing["owner_headers"], "2026-07"
    )
    assert voucher["state"] == "SUBMITTED"

    opt_out = setup_opt_out_noticed_case()
    pending = [
        ev
        for ev in opt_out["enhanced_vouchers"]
        if ev["tenant_id"] == opt_out["household_two"]["id"]
    ]
    assert len(pending) == 1, "the opt-out minted one enhanced voucher per household"
    enhanced_voucher = pending[0]
    assert enhanced_voucher["entitlement_cents"] == 135000, (
        "payment standard 137500 less the 2500 minimum-rent TTP, got "
        f"{enhanced_voucher['entitlement_cents']}"
    )

    restructuring = setup_case_with_accepted_study(
        renewal_option="OPTION_1_MARK_UP_TO_MARKET",
        adjustment_method="OCAF",
        comparables=[MAPLE_COURT],
    )
    determination = setup_evaluated_determination(restructuring["case"]["id"])
    assert determination["determination_state"] == "MUTM_ELIGIBLE"

    # (i) only an OwnerAgent registers a property.
    validate_error(
        api_client.create_property(
            create_property_payload(billing["owner"]["id"], project_name="Interloper Court"),
            CA_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )
    # (ii) only a PhaAdministrator issues an enhanced voucher.
    validate_error(
        api_client.issue_enhanced_voucher(enhanced_voucher["id"], CA_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )
    # (iii) the OwnerAgent files the voucher but does not disburse it.
    validate_error(
        api_client.pay_voucher_submission(voucher["id"], billing["owner_headers"]),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )
    # (iv) only a HudFieldOffice approves a restructuring determination.
    validate_error(
        api_client.approve_restructuring_determination(determination["id"], CA_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )
    # (v) the reconciliation projection is closed to a PhaAdministrator.
    validate_error(
        api_client.get_contract_reconciliation(billing["contract"]["id"], PHA_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )

    issued = validate_success(
        api_client.issue_enhanced_voucher(enhanced_voucher["id"], PHA_HEADERS)
    )
    assert issued["state"] == "ISSUED", (
        "the identical issue call succeeds for a PhaAdministrator, so the refusal was "
        f"about the role, got {issued['state']}"
    )

    paid = validate_success(
        api_client.pay_voucher_submission(voucher["id"], CA_HEADERS)
    )
    assert paid["paid_amount_cents"] == 84500, (
        f"the ContractAdministrator disburses the month, got {paid['paid_amount_cents']}"
    )

    approved = approve_determination(determination["id"], HUD_HEADERS)
    assert approved["determination_state"] == "APPROVED"
    assert approved["post_restructure_rent_per_unit_cents"] == 130200

    projection = validate_success(
        api_client.get_contract_reconciliation(billing["contract"]["id"], HUD_HEADERS)
    )
    assert projection["paid_hap_total_cents"] == 84500, (
        "the read refused to the PhaAdministrator is open to the HudFieldOffice, got "
        f"{projection['paid_hap_total_cents']}"
    )


def test_shared_reads_and_the_shared_utility_allowance_decision_work_for_every_role():
    """A property read is authorized for all four roles, and on a utility allowance
    analysis "When the boolean is false, either role may decide it".

    Design: Corner/rbac/shared_reads_and_the_shared_utility_allowance_decision_work_for_every_declared_role
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    readers = {
        "OwnerAgent": ctx["owner_headers"],
        "ContractAdministrator": CA_READER_HEADERS,
        "HudFieldOffice": HUD_HEADERS,
        "PhaAdministrator": PHA_HEADERS,
    }
    for role, headers in readers.items():
        data = validate_success(api_client.get_property(prop_id, headers))
        assert data["current_utility_allowance_cents"] == 11500, (
            f"{role} reads the same stored allowance, got "
            f"{data['current_utility_allowance_cents']}"
        )

    first = create_ua_analysis(
        prop_id, ctx["owner_headers"], effective_date="2026-09-01", utility_rate_change_pct=0.05
    )
    assert first["proposed_allowance_cents"] == 12075, (
        f"round_half_up(11500 * 1.05) is 12075, got {first['proposed_allowance_cents']}"
    )
    assert first["change_pct"] == 0.05
    assert first["requires_field_office_approval"] is False
    validate_success(
        api_client.submit_utility_allowance_analysis(first["id"], ctx["owner_headers"])
    )

    rejected = validate_success(
        api_client.decide_utility_allowance_analysis(
            first["id"],
            decide_utility_allowance_payload(
                "REJECT", "Rate schedule attachment was illegible"
            ),
            CA_HEADERS,
        )
    )
    assert rejected["state"] == "REJECTED", (
        "a ContractAdministrator may decide while the change stays inside the threshold, "
        f"got {rejected['state']}"
    )

    second = create_ua_analysis(
        prop_id, ctx["owner_headers"], effective_date="2026-09-01", utility_rate_change_pct=0.05
    )
    validate_success(
        api_client.submit_utility_allowance_analysis(second["id"], ctx["owner_headers"])
    )
    accepted = validate_success(
        api_client.decide_utility_allowance_analysis(
            second["id"], decide_utility_allowance_payload("ACCEPT"), HUD_HEADERS
        )
    )
    assert accepted["state"] == "APPROVED", (
        f"the same shared operation is open to a HudFieldOffice, got {accepted['state']}"
    )
    assert accepted["approver_user_id"] == HUD_USER_ID


def test_the_reviewer_who_challenged_the_study_cannot_approve_the_rents_it_supports():
    """"The operator whose identifier sits in that field may never approve the renewal
    rents of that same case; an attempt is refused with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403). Any other `ContractAdministrator` may approve".

    Design: Corner/rbac/the_reviewer_who_challenged_the_study_cannot_approve_the_rents_it_supports
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF"
    )
    case_id = ctx["case"]["id"]
    assert ctx["case"]["challenge_reviewer_user_id"] is None, (
        "an open case carries no challenger yet, got "
        f"{ctx['case']['challenge_reviewer_user_id']}"
    )
    assert ctx["case"]["ocaf_rent_per_unit_cents"] == 120752, (
        "round_half_up(86000 * 1.032) is 88752, plus 32000 debt service, got "
        f"{ctx['case']['ocaf_rent_per_unit_cents']}"
    )
    assert ctx["case"]["rcs_required"] is False, (
        "an OCAF election on a non-mark-up-to-market option releases the study "
        f"requirement, got {ctx['case']['rcs_required']}"
    )

    bundle = setup_challenged_study(
        case_id,
        ctx["owner_headers"],
        struck_index=1,
        comparables=[MAPLE_COURT, LARKSPUR_WAY],
        reason="77 Larkspur Way is a luxury conversion and is not comparable",
        reviewer_headers=CA_HEADERS,
    )
    assert bundle["study"]["challenge_round"] == 1

    challenged_case = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert challenged_case["challenge_reviewer_user_id"] == CA_USER_ID, (
        "the challenge, not the study creation, writes the lock, got "
        f"{challenged_case['challenge_reviewer_user_id']}"
    )

    validate_success(api_client.submit_study(bundle["study"]["id"], ctx["owner_headers"]))
    accepted = validate_success(
        api_client.decide_study(
            bundle["study"]["id"], decide_study_payload("ACCEPT"), CA_HEADERS
        )
    )
    assert accepted["estimated_market_rent_cents"] == 130200, (
        "only 418 Maple Court survives the strike, at 130200, got "
        f"{accepted['estimated_market_rent_cents']}"
    )

    validate_error(
        api_client.approve_rents(case_id, CA_HEADERS),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )
    blocked = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert blocked["rent_track_status"] == "RCS_IN_PROGRESS", (
        f"the refused approval left the track alone, got {blocked['rent_track_status']}"
    )

    approved = validate_success(
        api_client.approve_rents(case_id, CA_SECOND_APPROVER_HEADERS)
    )
    assert approved["rent_track_status"] == "RENTS_APPROVED"
    assert approved["approved_rent_per_unit_cents"] == 120752
    assert approved["rents_approver_user_id"] == CA_SECOND_APPROVER_USER_ID, (
        "a different user in the same role passes, got "
        f"{approved['rents_approver_user_id']}"
    )


def test_one_owner_agent_cannot_write_on_another_owners_property_but_may_read_it():
    """"the owner reached from the target resource — a `Property` via its `owner_id`, or the
    `Property` reached through a resource's property/contract chain — must have an `id`
    equal to `X-User-ID` on every `OwnerAgent` write. A mismatch is rejected with
    `ERR_NOT_PROPERTY_OWNER` (HTTP 403)".

    Design: Corner/rbac/one_owner_agent_cannot_write_on_another_owners_property_but_may_read_it
    """
    first = setup_portfolio(owner_overrides={"legal_name": "Cedar Ridge Housing Partners LP"})
    owner_a = first["owner"]
    headers_a = first["owner_headers"]
    prop_a = first["property"]
    contract_a = first["contract"]

    owner_b, headers_b = create_owner_with_headers(
        legal_name="Brightwater Communities LLC", contact_email="agent@brightwater.example"
    )
    prop_b = create_property(
        owner_b["id"],
        headers_b,
        project_name="Brightwater Court",
        total_units=10,
        assisted_unit_count=8,
    )

    validate_error(
        api_client.create_tenant_household(
            create_tenant_household_payload(
                prop_a["id"],
                unit_number="101",
                household_name="Interloper",
                annual_adjusted_income_cents=1800000,
                annual_gross_income_cents=1920000,
                family_size=3,
            ),
            headers_b,
        ),
        ApiErrorId.ERR_NOT_PROPERTY_OWNER.value,
        expected_status=403,
    )
    validate_error(
        api_client.create_voucher_submission(
            create_voucher_submission_payload(
                contract_a["id"], contract_a["version"], period_month="2026-07"
            ),
            headers_b,
        ),
        ApiErrorId.ERR_NOT_PROPERTY_OWNER.value,
        expected_status=403,
    )

    read_by_b = validate_success(api_client.get_property(prop_a["id"], headers_b))
    assert read_by_b["owner_id"] == owner_a["id"], "the shared read is not owner-scoped"
    assert read_by_b["assisted_unit_count"] == 20

    permitted = validate_success(
        api_client.create_tenant_household(
            create_tenant_household_payload(prop_a["id"], **REFERENCE_HOUSEHOLD_ONE),
            headers_a,
        ),
        expected_status=201,
    )
    assert permitted["unit_number"] == "101", (
        "the identical write by the owning agent succeeds, so the refusal was about "
        "identity and not about the payload"
    )

    leaked, leaked_meta = validate_paginated(
        api_client.list_property_tenant_households(prop_b["id"], headers_b)
    )
    assert leaked_meta["total_count"] == 0 and leaked == [], (
        f"nothing leaked onto owner B's property, got {leaked_meta['total_count']} rows"
    )
    own_rows, own_meta = validate_paginated(
        api_client.list_property_tenant_households(prop_a["id"], headers_a)
    )
    assert own_meta["total_count"] == 1
