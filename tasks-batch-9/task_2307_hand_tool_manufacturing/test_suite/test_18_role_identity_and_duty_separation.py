"""The two header gates sitting above every business rule, the peer shop-floor
roles, the entity-backed Claimant identity, and the duty separation that binds a
user identity across clear-hold and approval."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    NO_ROLE_HEADERS,
    add_claim_line,
    advance_payload,
    api_client,
    approve_claim_payload,
    assert_unit_ledger,
    claim_line_payload,
    clear_hold_payload,
    create_claim,
    create_claimant,
    create_program,
    create_sku,
    hold_payload,
    make_claimant_headers,
    make_headers_with_role,
    make_platform_admin_headers,
    make_warranty_administrator_headers,
    read_claim,
    read_program,
    read_sku,
    setup_lot_with_completed_campaign,
    setup_warranty_scenario,
    tool_sku_payload,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_claim_payload,
)

CM = TEST_USERS["channel_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]
WA = TEST_USERS["warranty_administrator_headers"]
BP = TEST_USERS["brand_protection_analyst_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

UNKNOWN_ROLE_HEADERS = make_headers_with_role("aud-1", "Auditor")
WA_ONE = make_warranty_administrator_headers("wa-1")
WA_TWO = make_warranty_administrator_headers("wa-2")
ADMIN_AS_WA_ONE = make_platform_admin_headers("wa-1")
HANDLE_LINE = {"component_code": "HANDLE", "component_list_price_cents": 1099, "quantity": 1}


# ---------------------------------------------------------------------------
# The header gates sit above the whole ladder
# ---------------------------------------------------------------------------


def test_a_request_carrying_no_role_header_is_unauthenticated_before_anything_else():
    """The first request has no role and a legitimate body, the second has no role
    and addresses a lot that does not exist, and both are answered on the header
    rather than on the row.

    PRD §2.7: "In ascending order the rungs are: authentication of the role header;
    role authorisation for the endpoint; claimant ownership; existence of every
    identifier named in the path and then in the body; request shape, meaning
    required fields present and correctly typed, enum values drawn from the declared
    members, integers within their declared ranges, pagination bounds, window sanity
    and the reading-array length — a missing required field, a wrongly typed value, a
    number outside its declared range or an undeclared enum member is reported as
    `ERR_INVALID_REQUEST`, while the pagination, window and reading-length faults
    have their own identifiers; state preconditions on the entity the request
    addresses; the stale-version check of §2.6; cross-entity state dependencies such
    as a furnace being available or a member SKU being certified; metallurgical and
    qualification safety gates; temporal window and buffer rules; capacity rules over
    pools, coupons and stock; fiscal rules over reserve money; and finally integrity
    rules covering ledgers, uniqueness, lineage and segregation of duties."

    Design: Corner/rbac/authentication_and_role_gates_precede_every_business_rule
    """
    validate_error(
        api_client.create_tool_sku(tool_sku_payload(), NO_ROLE_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    body = validate_error(
        api_client.get_production_lot(NON_EXISTENT_UUID, NO_ROLE_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    assert body["error_id"] != ApiErrorId.ERR_PRODUCTION_LOT_NOT_FOUND

    _, meta = validate_paginated(api_client.list_tool_skus(ADMIN))
    assert meta["total_count"] == 0


def test_a_role_string_outside_the_declared_seven_never_authenticates():
    """The header is present and well-formed but names a capacity the system does
    not know, which is an authentication failure rather than an authorisation one.

    PRD §2.1: "A request whose `X-User-Role` header is absent, or whose value is not
    one of those seven strings, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/authentication_and_role_gates_precede_every_business_rule
    """
    body = validate_error(
        api_client.create_tool_sku(tool_sku_payload(), UNKNOWN_ROLE_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    assert body["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED

    _, meta = validate_paginated(api_client.list_tool_skus(ADMIN))
    assert meta["total_count"] == 0


def test_role_authorisation_is_settled_before_the_shape_of_the_body_is_read():
    """A planner posting a catalogue row without its `sku_code` is refused on the
    role, and the same defective identity carrying a complete body would still be
    refused, so the acceptance from the channel manager isolates identity as the only
    variable.

    PRD §2.1: "A request whose role is well-formed but not listed among the
    authorised roles for the endpoint it targets is rejected with
    `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/authentication_and_role_gates_precede_every_business_rule
    """
    codeless = tool_sku_payload()
    codeless.pop("sku_code")

    body = validate_error(
        api_client.create_tool_sku(codeless, PP), ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403
    )
    assert body["error_id"] != ApiErrorId.ERR_INVALID_REQUEST

    created = validate_success(api_client.create_tool_sku(tool_sku_payload(), CM), 201)
    assert created["sku_code"] == "WR-17-BR"

    _, meta = validate_paginated(api_client.list_tool_skus(ADMIN))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Exclusive duties are role-bound; shared duties are not
# ---------------------------------------------------------------------------


def _a_lot_whose_advance_is_otherwise_legal():
    """The heat-treat campaign is COMPLETED, so the only thing that can stand
    between a caller and the step into HEAT_TREATED is the caller's role."""
    return setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 20})


def test_the_two_shop_floor_roles_cannot_borrow_each_others_verbs():
    """The engineer is refused an advance that the planner is then granted, and the
    planner is refused a certification even though the dossier is in the wrong state
    for one anyway.

    PRD §2.1: "The first is that certification is exclusively a `QualityEngineer` act
    while release into finished stock is exclusively a `ProductionPlanner` act, so no
    single operational role can both pass a lot and bank its units."

    Design: Corner/rbac/exclusive_duties_are_role_bound_while_shared_duties_are_not
    """
    ctx = _a_lot_whose_advance_is_otherwise_legal()
    lot_id = ctx["lot"]["id"]

    validate_error(
        api_client.advance_production_lot(lot_id, advance_payload("HEAT_TREATED"), QE),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    advanced = validate_success(
        api_client.advance_production_lot(lot_id, advance_payload("HEAT_TREATED"), PP)
    )
    assert advanced["process_status"] == "HEAT_TREATED"

    body = validate_error(
        api_client.certify_production_lot(lot_id, PP), ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403
    )
    assert body["error_id"] != ApiErrorId.ERR_LOT_CERT_STATE_INVALID


def test_an_analyst_may_place_a_fraud_hold_but_never_clear_one():
    """Holding is shared with the analyst and clearing is not, so the very user who
    recorded the hold is turned away on the role long before the duty separation
    could be consulted.

    PRD §2.1: "A `BrandProtectionAnalyst` may place a hold but may never clear one —
    clearing is reserved to `WarrantyAdministrator`."

    Design: Corner/rbac/exclusive_duties_are_role_bound_while_shared_duties_are_not
    """
    ctx = setup_warranty_scenario()
    claim_id = ctx["claim"]["id"]

    held = validate_success(
        api_client.hold_warranty_claim(
            claim_id, hold_payload(hold_reason="SECONDARY_CHANNEL_MATCH"), BP
        )
    )
    assert held["status"] == "FRAUD_HOLD"
    assert held["held_by_user_id"] == "bp-1"
    assert read_program(ctx["program"]["id"])["open_hold_count"] == 1

    body = validate_error(
        api_client.clear_hold_warranty_claim(
            claim_id, clear_hold_payload(clearance_note="Analyst clearing their own hold"), BP
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    assert body["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES
    assert read_claim(claim_id)["status"] == "FRAUD_HOLD"

    cleared = validate_success(
        api_client.clear_hold_warranty_claim(
            claim_id, clear_hold_payload(clearance_note="Reviewed by warranty administration"), ADMIN
        )
    )
    assert cleared["status"] == "SUBMITTED"
    assert cleared["fraud_cleared"] is True
    assert cleared["held_by_user_id"] == "bp-1"


# ---------------------------------------------------------------------------
# The Claimant role is bound to a row, not to a permission set
# ---------------------------------------------------------------------------


def _two_claimants_and_one_claim_owned_by_the_first():
    sku = create_sku()
    program = create_program()
    first = create_claimant(email="a@example.com", claimant_type="CONSUMER")
    second = create_claimant(email="b@example.com", claimant_type="PRO_ACCOUNT")
    claim = create_claim(first["id"], sku["id"], program["id"], serial_code="SN-1")
    return {
        "sku": sku,
        "program": program,
        "first": first,
        "second": second,
        "claim": claim,
        "first_headers": make_claimant_headers(first["id"]),
        "second_headers": make_claimant_headers(second["id"]),
    }


def test_a_claimant_reads_their_own_claim_and_is_refused_another_partys():
    """The same read succeeds for the owner and fails for the stranger, and the
    stranger's refusal is a permission fault rather than a pretence that the row is
    missing.

    PRD §2.1: "When `X-User-Role` is `Claimant`, `X-User-ID` is the `id` of the
    acting `Claimant` row; ownership checks compare a claim's `claimant_id` against
    `X-User-ID`, so a claimant may file only for themselves, may add replacement lines
    only to their own claims, and may read only their own claims."

    Design: Corner/rbac/claimant_role_is_scoped_to_its_own_entity_row
    """
    ctx = _two_claimants_and_one_claim_owned_by_the_first()
    claim_id = ctx["claim"]["id"]

    own = validate_success(api_client.get_warranty_claim(claim_id, ctx["first_headers"]))
    assert own["status"] == "SUBMITTED"

    body = validate_error(
        api_client.get_warranty_claim(claim_id, ctx["second_headers"]),
        ApiErrorId.ERR_CLAIMANT_MISMATCH,
        403,
    )
    assert body["error_id"] != ApiErrorId.ERR_CLAIM_NOT_FOUND


def test_a_claimant_may_not_file_under_another_partys_identifier():
    """The body names the other party's claimant row, and the filing is refused
    without leaving a claim behind.

    PRD §3.7: "Either a `WarrantyAdministrator` or the claimant themselves may file;
    when the caller acts as a `Claimant`, `claimant_id` must equal their own
    `X-User-ID` or the request is `ERR_CLAIMANT_MISMATCH`."

    Design: Corner/rbac/claimant_role_is_scoped_to_its_own_entity_row
    """
    ctx = _two_claimants_and_one_claim_owned_by_the_first()

    validate_error(
        api_client.create_warranty_claim(
            warranty_claim_payload(
                ctx["first"]["id"], ctx["sku"]["id"], ctx["program"]["id"], serial_code="SN-2"
            ),
            ctx["second_headers"],
        ),
        ApiErrorId.ERR_CLAIMANT_MISMATCH,
        403,
    )

    _, meta = validate_paginated(api_client.list_warranty_claims(WA))
    assert meta["total_count"] == 1


def test_a_claimant_may_not_append_a_replacement_line_to_another_partys_claim():
    """Line-adding is ownership-scoped in the same way as reading, so the stranger's
    line never reaches the claim.

    PRD §3.7: "Replacement lines are added one at a time by a
    `WarrantyAdministrator` or by the owning claimant, each naming a `component_code`
    for the replacement component or tool, a `component_list_price_cents` of at least
    one cent, and a `quantity` of at least one unit."

    Design: Corner/rbac/claimant_role_is_scoped_to_its_own_entity_row
    """
    ctx = _two_claimants_and_one_claim_owned_by_the_first()
    claim_id = ctx["claim"]["id"]

    validate_error(
        api_client.add_claim_line(claim_id, claim_line_payload(), ctx["second_headers"]),
        ApiErrorId.ERR_CLAIMANT_MISMATCH,
        403,
    )

    unchanged = read_claim(claim_id)
    assert unchanged["line_count"] == 0
    assert unchanged["replacement_unit_count"] == 0

    _, meta = validate_paginated(api_client.list_claim_lines(claim_id, WA))
    assert meta["total_count"] == 0


def test_the_unscoped_claim_collection_lists_no_claimant_role_at_all():
    """The owner of the only claim in the system is still refused the unscoped
    collection, which authorises the administrator, the analyst, the channel manager
    and the platform admin and no claimant at all.

    PRD §2.1: "A request whose role is well-formed but not listed among the
    authorised roles for the endpoint it targets is rejected with
    `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/claimant_role_is_scoped_to_its_own_entity_row
    """
    ctx = _two_claimants_and_one_claim_owned_by_the_first()

    body = validate_error(
        api_client.list_warranty_claims(ctx["first_headers"], params={"limit": 50, "offset": 0}),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    assert body["error_id"] != ApiErrorId.ERR_CLAIMANT_MISMATCH

    _, meta = validate_paginated(api_client.list_warranty_claims(WA))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The duty separation binds a user identity across two later verbs
# ---------------------------------------------------------------------------


def _a_funded_claim_with_one_line():
    """Ten units on the shelf, five million cents of reserve and a single HANDLE
    line worth 681 cents of reserve charge, so nothing but the duty separation can
    stand in the way of an approval."""
    return setup_warranty_scenario(lines=(HANDLE_LINE,))


def test_the_user_who_placed_a_hold_may_not_clear_their_own_hold():
    """The hold records the acting identity, and that identity is then compared
    against the clearer.

    PRD §3.7: "The claim must be `FRAUD_HOLD`, otherwise `ERR_CLAIM_STATE_INVALID`,
    and the acting `X-User-ID` must not equal the claim's `held_by_user_id`, otherwise
    `ERR_SEGREGATION_OF_DUTIES`; that check applies only when `held_by_user_id` is
    non-null, so a hold placed automatically by intake scoring or by the counterfeit
    cascade constrains nobody."

    Design: Corner/rbac/segregation_of_duties_binds_the_holding_user_across_two_verbs
    """
    ctx = _a_funded_claim_with_one_line()
    claim_id = ctx["claim"]["id"]

    held = validate_success(
        api_client.hold_warranty_claim(
            claim_id, hold_payload(hold_reason="SERIAL_PATTERN_REVIEW"), WA_ONE
        )
    )
    assert held["held_by_user_id"] == "wa-1"
    assert read_program(ctx["program"]["id"])["open_hold_count"] == 1

    validate_error(
        api_client.clear_hold_warranty_claim(
            claim_id, clear_hold_payload(clearance_note="Self-clearance attempt"), WA_ONE
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    assert read_claim(claim_id)["status"] == "FRAUD_HOLD"


def test_the_retained_holder_is_barred_from_approval_whatever_role_it_wears():
    """One clearance by a second administrator keeps the holder recorded, and the
    holder is then refused the approval both as an administrator and as a platform
    admin, while all three refusals leave the version token they quoted still valid.

    PRD §3.8: "And last of all, the acting `X-User-ID` must not equal the claim's
    retained `held_by_user_id` when that field is non-null
    (`ERR_SEGREGATION_OF_DUTIES`), so the administrator who once held a claim can
    never be the one who approves it even after somebody else cleared the hold."

    Design: Corner/rbac/segregation_of_duties_binds_the_holding_user_across_two_verbs
    """
    ctx = _a_funded_claim_with_one_line()
    claim_id = ctx["claim"]["id"]
    validate_success(
        api_client.hold_warranty_claim(
            claim_id, hold_payload(hold_reason="SERIAL_PATTERN_REVIEW"), WA_ONE
        )
    )

    cleared = validate_success(
        api_client.clear_hold_warranty_claim(
            claim_id, clear_hold_payload(clearance_note="Independent review complete"), WA_TWO
        )
    )
    assert cleared["status"] == "SUBMITTED"
    assert cleared["fraud_cleared"] is True
    assert cleared["held_by_user_id"] == "wa-1"

    token = read_program(ctx["program"]["id"])["version"]
    for headers in (WA_ONE, ADMIN_AS_WA_ONE):
        validate_error(
            api_client.approve_warranty_claim(claim_id, approve_claim_payload(token), headers),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

    approved = validate_success(
        api_client.approve_warranty_claim(claim_id, approve_claim_payload(token), WA_TWO)
    )
    assert approved["status"] == "APPROVED"
    assert approved["reserve_charge_cents"] == 681

    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 4_999_319
    sku = read_sku(ctx["sku"]["id"])
    assert sku["units_on_hand"] == 9
    assert sku["units_reserved"] == 1
    assert_unit_ledger(sku)


def test_a_second_line_from_the_administrator_keeps_the_reserve_charge_current():
    """A second HANDLE line doubles the charge before any approval is attempted, so
    the figure the duty separation is protecting is the recomputed one.

    PRD §3.7: "The claim's three roll-ups are refreshed from its lines in
    `created_at` ascending order: `reserve_charge_cents` is the **sum of the
    already-rounded per-line amounts**, `replacement_unit_count` is the sum of the
    lines' `quantity` values, and `line_count` is the number of lines."

    Design: Corner/rbac/segregation_of_duties_binds_the_holding_user_across_two_verbs
    """
    ctx = _a_funded_claim_with_one_line()
    claim_id = ctx["claim"]["id"]

    add_claim_line(claim_id, component_code="JAW", component_list_price_cents=1099, quantity=1)

    lined = read_claim(claim_id)
    assert lined["line_count"] == 2
    assert lined["replacement_unit_count"] == 2
    assert lined["reserve_charge_cents"] == 1362

    validate_success(
        api_client.hold_warranty_claim(
            claim_id, hold_payload(hold_reason="SERIAL_PATTERN_REVIEW"), WA_ONE
        )
    )
    validate_error(
        api_client.clear_hold_warranty_claim(
            claim_id, clear_hold_payload(clearance_note="Self-clearance attempt"), WA_ONE
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    assert read_claim(claim_id)["reserve_charge_cents"] == 1362
