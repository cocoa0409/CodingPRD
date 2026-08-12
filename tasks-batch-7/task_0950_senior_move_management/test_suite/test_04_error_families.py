"""The authentication ladder, the fourteen existence rungs and the gate-4,
gate-7, gate-8, gate-10 and gate-12 refusal families."""

from test_helpers import (
    ApiErrorId,
    BILLING_ADMIN,
    MOVE_MANAGER,
    PLATFORM_ADMIN,
    api_client,
    assert_money,
    commission_cents,
    consignment_fees_cents,
    create_engagement_payload,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    headers_without_role,
    headers_without_user_id,
    invoice_lines,
    invoice_of,
    make_power_of_attorney_headers,
    milestone_by_key,
    reopen_milestone,
    net_proceeds_cents,
    new_active_authority,
    new_authority_record,
    new_client,
    new_consignment_lot,
    new_engagement,
    new_item,
    new_portal_party,
    new_residence,
    new_sort_plan,
    new_vendor,
    read_authority,
    read_invoice,
    read_item,
    read_lot,
    read_milestone,
    read_party,
    read_room,
    read_sort_plan,
    set_clock,
    setup_consignment_lot,
    setup_engagement,
    submit_sort_plan,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

MISSING = "00000000-0000-4000-8000-000000000001"


def test_the_first_four_rungs_answer_with_their_own_authentication_errors():
    """PRD §2.1: "A request with no `X-User-Role` header, or with an empty one, is
    rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401). A request whose
    `X-User-Role` is not one of the eight role names below is rejected with
    `ERR_UNKNOWN_ROLE` (HTTP 401). A request whose role is entity-backed but which
    carries no `X-User-ID` is rejected with `ERR_MISSING_USER_ID` (HTTP 401). A
    syntactically valid, authenticated request whose role does not appear in the
    target endpoint's authorised-role list is rejected with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."

    Design: Corner/errors/auth_ladder_rungs_one_through_four_are_ordered
    """
    set_clock("2026-05-02T09:00:00.000Z")
    new_client(email=None)

    validate_error(
        api_client.create_client(
            {"full_name": "No auth", "phone": "+1-555-0000"}, headers_without_role()
        ),
        ApiErrorId.ERR_MISSING_AUTH_HEADER.value,
    )
    validate_error(
        api_client.create_client(
            {"full_name": "Bad role", "phone": "+1-555-0001"},
            {"X-User-ID": "someone", "X-User-Role": "HOUSE_SITTER", "Content-Type": "application/json"},
        ),
        ApiErrorId.ERR_UNKNOWN_ROLE.value,
    )
    validate_error(
        api_client.create_family_hold(
            {"inventory_item_id": MISSING, "raised_by_party_id": MISSING, "reason": "no user id"},
            headers_without_user_id("FAMILY_MEMBER"),
        ),
        ApiErrorId.ERR_MISSING_USER_ID.value,
    )
    validate_error(
        api_client.create_client(
            {"full_name": "Wrong role", "phone": "+1-555-0002"},
            {"X-User-ID": "vendor-1", "X-User-Role": "VENDOR", "Content-Type": "application/json"},
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )


def test_the_first_seven_existence_rungs_each_report_their_own_not_found_code():
    """PRD §2.7: "The engagement id in the path, or `engagement_id` in the body,
    resolves to an engagement. Otherwise `ERR_ENGAGEMENT_NOT_FOUND`, HTTP 404."
    PRD §2.7: "The room id in the path, or `assigned_room_id` in the body, resolves.
    Otherwise `ERR_ROOM_NOT_FOUND`, HTTP 404. Applies to the
    `/destination-rooms/{id}` endpoints and `POST /inventory-items/{id}/designate`."

    Design: Corner/errors/not_found_family_part_one_engagement_client_party_authority_residence_room_item
    """
    world = setup_engagement(with_client_party=False)
    new_residence(world["engagement_id"])
    item = new_item(
        world["engagement_id"], label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40
    )

    validate_error(
        api_client.get_engagement(MISSING, MOVE_MANAGER), ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value
    )
    validate_error(
        api_client.create_engagement(create_engagement_payload(MISSING), MOVE_MANAGER),
        ApiErrorId.ERR_CLIENT_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_portal_party(MISSING, MOVE_MANAGER), ApiErrorId.ERR_PARTY_NOT_FOUND.value
    )
    validate_error(
        api_client.get_authority_record(MISSING, MOVE_MANAGER),
        ApiErrorId.ERR_AUTHORITY_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_destination_residence(MISSING, MOVE_MANAGER),
        ApiErrorId.ERR_RESIDENCE_NOT_FOUND.value,
    )
    validate_error(
        api_client.designate_item(
            item["id"], {"disposition": "KEEP", "assigned_room_id": MISSING}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_ROOM_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_inventory_item(MISSING, MOVE_MANAGER), ApiErrorId.ERR_ITEM_NOT_FOUND.value
    )
    assert read_item(item["id"])["disposition"] == "UNDECIDED"


def test_the_remaining_existence_rungs_keep_their_codes_distinct():
    """PRD §2.7: "The family hold id in the path resolves. Otherwise
    `ERR_HOLD_NOT_FOUND`, HTTP 404. Applies to the `/family-holds/{id}` endpoints."
    PRD §2.7: "The milestone, unpack-session or punch-list id in the path, or
    `unpack_session_id` in the body, resolves. Otherwise
    `ERR_TIMELINE_RECORD_NOT_FOUND`, HTTP 404."

    Design: Corner/errors/not_found_family_part_two_hold_plan_crew_vendor_lot_invoice_timeline
    """
    setup_engagement(with_client_party=False)

    validate_error(api_client.get_family_hold(MISSING, MOVE_MANAGER), ApiErrorId.ERR_HOLD_NOT_FOUND.value)
    validate_error(
        api_client.get_move_day_plan(MISSING, MOVE_MANAGER), ApiErrorId.ERR_PLAN_NOT_FOUND.value
    )
    validate_error(
        api_client.get_crew_member(MISSING, MOVE_MANAGER),
        ApiErrorId.ERR_CREW_RECORD_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_vendor(MISSING, MOVE_MANAGER), ApiErrorId.ERR_VENDOR_RECORD_NOT_FOUND.value
    )
    validate_error(
        api_client.get_consignment_lot(MISSING, MOVE_MANAGER), ApiErrorId.ERR_LOT_NOT_FOUND.value
    )
    validate_error(
        api_client.get_invoice(MISSING, BILLING_ADMIN), ApiErrorId.ERR_INVOICE_NOT_FOUND.value
    )
    validate_error(
        api_client.get_milestone(MISSING, MOVE_MANAGER),
        ApiErrorId.ERR_TIMELINE_RECORD_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_sort_plan(MISSING, MOVE_MANAGER), ApiErrorId.ERR_PLAN_NOT_FOUND.value
    )


def test_a_party_belonging_to_another_engagement_is_a_membership_failure():
    """PRD §2.7: "Every supplied party id belongs to the same engagement as the
    subject resource. Otherwise `ERR_PARTY_ENGAGEMENT_MISMATCH`, HTTP 422. Applies
    to every endpoint carrying a party id."

    Design: Corner/errors/party_from_another_engagement_is_rejected_as_mismatch
    """
    world = setup_engagement(with_client_party=False)
    other = new_engagement(
        world["client"]["id"], scheduled_move_start_utc="2026-08-15T14:00:00.000Z"
    )
    other_party = new_portal_party(other["id"], "CLIENT", client_id=world["client"]["id"])
    assessment = milestone_by_key(world["engagement_id"], "ASSESSMENT")

    error = validate_error(
        api_client.complete_milestone(
            assessment["id"], {"completed_by_party_id": other_party["id"]}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_PARTY_ENGAGEMENT_MISMATCH.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_PARTY_NOT_FOUND.value
    assert read_milestone(assessment["id"])["status"] == "IN_PROGRESS"


def test_the_four_delegated_authority_rungs_fire_in_their_declared_order():
    """PRD §2.7: "A `POWER_OF_ATTORNEY` actor holds at least one authority record
    whose `holder_party_id` is the acting party and whose `status` is `ACTIVE`.
    Otherwise `ERR_NO_ACTIVE_AUTHORITY`, HTTP 403."
    PRD §2.7: "That active record's `authority_scope` covers the operation family:
    `FULL` or `DISPOSITION_ONLY` for disposition, sort-plan and placement approvals,
    `FULL` or `BILLING_ONLY` for invoice disputes and vendor sign-off. Otherwise
    `ERR_AUTHORITY_SCOPE_INSUFFICIENT`, HTTP 403."
    PRD §2.7: "When the subject item's `appraised_value_cents` is at or above the
    high-value threshold of 250000 cents, the acting `authority_scope` must be
    exactly `FULL`; `DISPOSITION_ONLY` is not enough. Otherwise
    `ERR_HIGH_VALUE_AUTHORITY_REQUIRED`, HTTP 403."

    Design: Corner/errors/poa_without_active_authority_then_wrong_scope_then_ceiling_and_high_value
    """
    world = setup_engagement(with_client_party=False, with_poa_party=True, with_residence=True)
    eng_id, party_id, room_id = world["engagement_id"], world["poa_party"]["id"], world["room"]["id"]
    item = new_item(
        eng_id,
        label="Estate diamond brooch",
        category="JEWELRY",
        footprint_linear_inches=2,
        volume_cft=1,
        appraised_value_cents=300000,
        appraisal_source="APPRAISED",
    )
    poa_headers = make_power_of_attorney_headers(party_id)
    body = {"disposition": "KEEP", "assigned_room_id": room_id, "acting_party_id": party_id}

    pending = new_authority_record(
        eng_id, party_id, authority_scope="BILLING_ONLY", approval_ceiling_cents=400000
    )
    validate_error(
        api_client.designate_item(item["id"], body, poa_headers),
        ApiErrorId.ERR_NO_ACTIVE_AUTHORITY.value,
    )

    get_success_data(api_client.activate_authority_record(pending["id"], MOVE_MANAGER))
    validate_error(
        api_client.designate_item(item["id"], body, poa_headers),
        ApiErrorId.ERR_AUTHORITY_SCOPE_INSUFFICIENT.value,
    )

    get_success_data(
        api_client.revoke_authority_record(
            pending["id"], {"reason": "Replaced by a disposition authority"}, MOVE_MANAGER
        )
    )
    new_active_authority(
        eng_id, party_id, authority_scope="DISPOSITION_ONLY", approval_ceiling_cents=400000
    )
    validate_error(
        api_client.designate_item(item["id"], body, poa_headers),
        ApiErrorId.ERR_HIGH_VALUE_AUTHORITY_REQUIRED.value,
    )
    assert read_item(item["id"])["disposition"] == "UNDECIDED"


def test_an_inverted_window_and_an_early_activation_share_one_window_error():
    """PRD §2.7: "An authority record's `effective_to_utc` is strictly after its
    `effective_from_utc` at creation; activation requires the clock to be at or
    after `effective_from_utc` and strictly before `effective_to_utc`; reinstatement
    requires the clock to be strictly before `effective_to_utc`. Otherwise
    `ERR_AUTHORITY_WINDOW_INVALID`, HTTP 409."

    Design: Corner/errors/authority_window_inverted_and_activation_outside_window_rejected
    """
    world = setup_engagement(with_client_party=False, with_poa_party=True)
    eng_id, party_id = world["engagement_id"], world["poa_party"]["id"]
    future = new_authority_record(
        eng_id,
        party_id,
        effective_from_utc="2026-07-01T00:00:00.000Z",
        effective_to_utc="2026-12-31T00:00:00.000Z",
        approval_ceiling_cents=400000,
    )
    validate_error(
        api_client.create_authority_record(
            {
                "engagement_id": eng_id,
                "holder_party_id": party_id,
                "authority_scope": "FULL",
                "effective_from_utc": "2026-09-01T00:00:00.000Z",
                "effective_to_utc": "2026-09-01T00:00:00.000Z",
                "approval_ceiling_cents": 400000,
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_AUTHORITY_WINDOW_INVALID.value,
    )
    validate_error(
        api_client.activate_authority_record(future["id"], MOVE_MANAGER),
        ApiErrorId.ERR_AUTHORITY_WINDOW_INVALID.value,
    )
    assert read_authority(future["id"])["status"] == "PENDING"
    assert read_party(party_id)["can_approve_dispositions"] is False


def test_the_empty_catalogue_and_the_undecided_catalogue_report_different_codes():
    """PRD §3.6: "Submitting the plan requires it to be `DRAFT`, requires the
    engagement to have at least one catalogued item — otherwise `ERR_NO_INVENTORY` —
    and requires that no item of the engagement is under a live hold. On success it
    snapshots `undecided_count_at_submit`, the count of the engagement's items whose
    disposition was `UNDECIDED` at that instant."
    PRD §2.7: "At submit time no inventory item of the engagement is `UNDECIDED`; at
    approve time the plan's `undecided_count_at_submit` is zero. Otherwise
    `ERR_UNDECIDED_ITEMS_REMAIN`, HTTP 422."

    Design: Corner/errors/sort_plan_submit_requires_inventory_and_no_undecided_items
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    plan = new_sort_plan(eng_id)

    validate_error(
        api_client.submit_sort_plan(plan["id"], MOVE_MANAGER), ApiErrorId.ERR_NO_INVENTORY.value
    )
    item = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    validate_error(
        api_client.submit_sort_plan(plan["id"], MOVE_MANAGER),
        ApiErrorId.ERR_UNDECIDED_ITEMS_REMAIN.value,
    )
    designate(item["id"], "DONATE")
    validate_success(api_client.submit_sort_plan(plan["id"], MOVE_MANAGER))

    submitted = read_sort_plan(plan["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["undecided_count_at_submit"] == 0


def test_a_locked_item_and_a_consigned_item_are_refused_by_different_rungs():
    """PRD §2.7: "The item's `disposition_locked` is false. Otherwise
    `ERR_DISPOSITION_LOCKED`, HTTP 409. Applies to
    `POST /inventory-items/{id}/designate`."
    PRD §3.4: "An item already attached to a lot may not be designated to anything
    other than `SELL`, and the attempt is refused with `ERR_ITEM_ALREADY_CONSIGNED`."

    Design: Corner/errors/locked_disposition_and_consigned_item_are_refused_separately
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    locked = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(locked["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])
    # Approval locks the dispositions and, per PRD §3.6, also completes the SORT_PLAN
    # milestone, which moves the phase to PACK. Gate 5 (rung 31) precedes gate 7
    # (rung 39), so the phase is pulled back to SORT_PLAN by reopening that milestone
    # - PRD §3.10 permits the reopen while no higher-sequence milestone is COMPLETE,
    # and it leaves every item's `disposition_locked` untouched.
    reopen_milestone(milestone_by_key(eng_id, "SORT_PLAN")["id"], "Family asked to revisit")

    other = new_engagement(
        world["client"]["id"], scheduled_move_start_utc="2026-08-15T14:00:00.000Z"
    )
    vendor = new_vendor("Hollis Estate Gallery", "CONSIGNMENT", "2027-01-31")
    consigned = new_item(
        other["id"],
        label="Mantel clock",
        category="MISC",
        footprint_linear_inches=12,
        volume_cft=3,
        appraised_value_cents=45000,
        appraisal_source="APPRAISED",
    )
    designate(consigned["id"], "SELL")
    lot = new_consignment_lot(other["id"], vendor["id"], 90000, "2026-05-05", [consigned["id"]])

    validate_error(
        api_client.designate_item(locked["id"], {"disposition": "HAUL_AWAY"}, MOVE_MANAGER),
        ApiErrorId.ERR_DISPOSITION_LOCKED.value,
    )
    validate_error(
        api_client.designate_item(consigned["id"], {"disposition": "HAUL_AWAY"}, MOVE_MANAGER),
        ApiErrorId.ERR_ITEM_ALREADY_CONSIGNED.value,
    )
    assert read_item(locked["id"])["disposition"] == "DONATE"
    member = read_item(consigned["id"])
    assert member["disposition"] == "SELL"
    assert member["consignment_lot_id"] == lot["id"]


def test_a_service_kind_mismatch_and_an_early_unsold_declaration_are_refused():
    """PRD §3.8: "The service kind must match the vendor's type under a strict
    one-to-one map — haul-away work to a junk hauler, consignment pickup to a
    consignment house, appraisal to an appraiser, cleaning to a cleaner and
    shredding to a shredder — and a mismatch is refused with
    `ERR_VENDOR_TYPE_MISMATCH`."
    PRD §2.7: "A lot may be declared unsold only once the logical clock date is at
    least thirty days after `listed_on`. Otherwise `ERR_UNSOLD_WINDOW_NOT_ELAPSED`,
    HTTP 409."

    Design: Corner/errors/vendor_type_mismatch_and_unsold_window_not_elapsed
    """
    world = setup_consignment_lot(
        item_specs=[
            {
                "label": "Mantel clock",
                "category": "MISC",
                "footprint_linear_inches": 12,
                "volume_cft": 3,
                "appraised_value_cents": 45000,
                "appraisal_source": "APPRAISED",
            }
        ],
        list_price_cents=90000,
    )
    set_clock("2026-06-03T00:00:00.000Z")

    validate_error(
        api_client.create_vendor_assignment(
            {
                "engagement_id": world["engagement_id"],
                "vendor_id": world["vendor"]["id"],
                "service_kind": "HAUL_AWAY",
                "service_date": "2026-06-16",
                "quoted_cents": 45000,
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_VENDOR_TYPE_MISMATCH.value,
    )
    validate_error(
        api_client.declare_lot_unsold(world["lot"]["id"], MOVE_MANAGER),
        ApiErrorId.ERR_UNSOLD_WINDOW_NOT_ELAPSED.value,
    )
    set_clock("2026-06-04T00:00:00.000Z")
    validate_success(api_client.declare_lot_unsold(world["lot"]["id"], MOVE_MANAGER))

    assert read_lot(world["lot"]["id"])["status"] == "UNSOLD"
    _, meta = validate_paginated(
        api_client.list_vendor_assignments(
            MOVE_MANAGER, params={"engagement_id": world["engagement_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_zero_gross_sale_and_a_second_settlement_are_both_refused():
    """PRD §2.7: "`gross_sale_price_cents` is greater than zero and the lot has at
    least one member item. Otherwise `ERR_INVALID_SALE_PRICE`, HTTP 422. Applies to
    `POST /consignment-lots/{id}/record-sale`."
    PRD §3.8: "A second settle on the same lot is refused with
    `ERR_LOT_ALREADY_CREDITED`."

    Design: Corner/errors/invalid_sale_price_and_second_settle_are_refused
    """
    world = setup_consignment_lot(
        item_specs=[
            {
                "label": "Mantel clock",
                "category": "MISC",
                "footprint_linear_inches": 12,
                "volume_cft": 3,
                "appraised_value_cents": 45000,
                "appraisal_source": "APPRAISED",
            }
        ],
        list_price_cents=90000,
    )
    # The PRD names two different errors for the same zero price: §2.7 rung 5 lists
    # `gross_sale_price_cents` among the fields that must be greater than zero and
    # routes that failure to ERR_VALIDATION, while §3.8 says a violation of the
    # "greater than zero" requirement "reports `ERR_INVALID_SALE_PRICE`". The ladder
    # order makes rung 5 first, the narrative makes rung 51 the answer; both readings
    # are faithful, so either identifier is accepted and the refusal itself is pinned.
    validate_error_is_one_of(
        api_client.record_lot_sale(
            world["lot"]["id"], {"gross_sale_price_cents": 0, "sold_on": "2026-05-20"}, MOVE_MANAGER
        ),
        [ApiErrorId.ERR_VALIDATION.value, ApiErrorId.ERR_INVALID_SALE_PRICE.value],
    )
    validate_success(
        api_client.record_lot_sale(
            world["lot"]["id"],
            {"gross_sale_price_cents": 80000, "sold_on": "2026-05-20"},
            MOVE_MANAGER,
        )
    )
    lot = read_lot(world["lot"]["id"])
    assert_money(lot["commission_cents"], commission_cents(80000), "commission_cents")
    assert_money(lot["fees_cents"], consignment_fees_cents(1), "fees_cents")
    assert_money(lot["net_proceeds_cents"], net_proceeds_cents(80000, 1), "net_proceeds_cents")

    validate_success(api_client.settle_lot(world["lot"]["id"], BILLING_ADMIN))
    # Same shape again: §3.8 says "A second settle on the same lot is refused with
    # `ERR_LOT_ALREADY_CREDITED`" (rung 54), but the very same paragraph makes
    # settlement "reachable from `SOLD` only", and the first settle leaves the lot
    # `SETTLED`, so §2.7's rung 48 fails first and reports ERR_INVALID_STATE. Both
    # readings are faithful to the PRD, so either identifier is accepted.
    validate_error_is_one_of(
        api_client.settle_lot(world["lot"]["id"], BILLING_ADMIN),
        [ApiErrorId.ERR_LOT_ALREADY_CREDITED.value, ApiErrorId.ERR_INVALID_STATE.value],
    )
    expected_credit = -net_proceeds_cents(80000, 1)
    lines = [
        line for line in invoice_lines(world["invoice"]["id"]) if line["line_type"] == "CONSIGNMENT_CREDIT"
    ]
    assert len(lines) == 1
    assert_money(lines[0]["amount_cents"], expected_credit, "credit line")
    assert_money(
        read_invoice(world["invoice"]["id"])["credits_cents"], expected_credit, "credits_cents"
    )


def test_the_package_tier_is_required_under_package_and_forbidden_under_hourly():
    """PRD §2.7: "`package_tier` is present and non-null when `billing_mode` is
    `PACKAGE`, and absent or null when `billing_mode` is `HOURLY`. This is the single
    rung at which the two pipelines diverge at creation time. Otherwise
    `ERR_PACKAGE_TIER_REQUIRED`, HTTP 422."
    PRD §3.1: "Supplying a package tier under the hourly pipeline, or omitting it
    under the package pipeline, is rejected with `ERR_PACKAGE_TIER_REQUIRED`."

    Design: Corner/errors/package_tier_required_under_package_and_forbidden_under_hourly
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)

    validate_error(
        api_client.create_engagement(
            create_engagement_payload(client["id"], billing_mode="PACKAGE"), MOVE_MANAGER
        ),
        ApiErrorId.ERR_PACKAGE_TIER_REQUIRED.value,
    )
    validate_error(
        api_client.create_engagement(
            create_engagement_payload(client["id"], billing_mode="HOURLY", package_tier="STUDIO"),
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_PACKAGE_TIER_REQUIRED.value,
    )
    assert (
        validate_success(api_client.get_client(client["id"], MOVE_MANAGER))["engagement_count"] == 0
    )


def test_a_narrow_but_bulky_item_fails_the_volume_test_after_passing_the_linear_one():
    """PRD §3.4: "Only when the linear test passes is the volume test evaluated: the
    room's `keep_load_volume_cft` excluding this item, plus the item's `volume_cft`,
    must be less than or equal to the room's `nominal_volume_cft` multiplied by a
    safety factor of 0.90 and rounded half-up to two decimal places."
    PRD §2.7: "The target room's prospective `KEEP` volume load is less than or equal
    to its `nominal_volume_cft` multiplied by the room volume safety factor of 0.90.
    Evaluated only after rung 68 has passed. Otherwise `ERR_ROOM_VOLUME_EXCEEDED`,
    HTTP 422."

    Design: Corner/errors/room_volume_exceeded_when_linear_test_passes
    """
    world = setup_engagement(
        with_client_party=False,
        with_residence=True,
        room_kwargs={"nominal_linear_inches": 240, "nominal_volume_cft": 100},
    )
    bulky = new_item(
        world["engagement_id"], label="Upright piano", category="MISC", footprint_linear_inches=6, volume_cft=95
    )
    error = validate_error(
        api_client.designate_item(
            bulky["id"], {"disposition": "KEEP", "assigned_room_id": world["room"]["id"]}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_ROOM_VOLUME_EXCEEDED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED.value
    assert read_item(bulky["id"])["disposition"] == "UNDECIDED"
    assert read_room(world["room"]["id"])["keep_load_volume_cft"] == 0
