"""Requests that break two rungs at once, pinning which gate answers first."""

from test_helpers import (
    ApiErrorId,
    FREEZE_INSTANT,
    MOVE_MANAGER,
    MOVE_START,
    api_client,
    create_crew_assignment_payload,
    create_engagement_payload,
    create_sort_plan_payload,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    headers_without_user_id,
    make_client_headers,
    make_family_member_headers,
    make_power_of_attorney_headers,
    milestone_by_key,
    new_active_authority,
    new_client,
    new_consignment_lot,
    new_crew_member,
    new_engagement,
    new_family_hold,
    new_item,
    new_move_day_plan,
    new_portal_party,
    new_sort_plan,
    new_vendor,
    read_engagement,
    read_item,
    read_lot,
    read_move_day_plan,
    read_party,
    read_room,
    read_sort_plan,
    set_clock,
    setup_engagement,
    submit_sort_plan,
    validate_error,
    validate_paginated,
    validate_success,
    assert_two_dp,
    assert_money,
)

MISSING = "00000000-0000-4000-8000-0000000000aa"
DONATE_SPEC = {
    "label": "Old linens",
    "category": "LINENS",
    "footprint_linear_inches": 10,
    "volume_cft": 5,
}


def test_the_role_list_closes_before_the_engagement_is_even_looked_up():
    """PRD §2.6: "Read endpoints pass gates 1 and 2 only: a GET authenticates, checks
    the role, validates its pagination parameters and returns the gate-2 404 for an
    unresolvable id, but never evaluates gates 3 through 12."
    PRD §2.7: "The acting role appears in the endpoint's declared role list.
    Otherwise `ERR_ROLE_NOT_PERMITTED`, HTTP 403. Applies to every endpoint."

    Design: Corner/errors/role_permission_rung_precedes_engagement_existence
    """
    set_clock("2026-05-02T09:00:00.000Z")
    from test_helpers import BILLING_ADMIN

    validate_error(
        api_client.hold_engagement(MISSING, {"reason": "Family requested a pause"}, BILLING_ADMIN),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api_client.hold_engagement(MISSING, {"reason": "Family requested a pause"}, MOVE_MANAGER),
        ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value,
    )


def test_enum_membership_is_checked_before_the_path_id_is_resolved():
    """PRD §2.6: "1. **Envelope, authentication and body shape.** Authentication
    headers present, `X-User-Role` a declared role, `X-User-ID` present when the role
    is entity-backed, the role permitted for the endpoint, then request-body shape
    and enum membership. Ladder rungs 1 through 7."
    PRD §2.7: "The inventory item id in the path, `inventory_item_id` in the body, or
    every member of `item_ids`, resolves. Otherwise `ERR_ITEM_NOT_FOUND`, HTTP 404."

    Design: Corner/errors/enum_membership_rung_precedes_item_existence
    """
    set_clock("2026-05-02T09:00:00.000Z")
    validate_error(
        api_client.designate_item(MISSING, {"disposition": "SCRAP"}, MOVE_MANAGER),
        ApiErrorId.ERR_INVALID_ENUM.value,
    )
    validate_error(
        api_client.designate_item(MISSING, {"disposition": "DONATE"}, MOVE_MANAGER),
        ApiErrorId.ERR_ITEM_NOT_FOUND.value,
    )


def test_the_missing_user_id_rung_answers_before_the_role_list_and_the_404():
    """PRD §2.7: "`X-User-ID` is present whenever the acting role is entity-backed —
    that is `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY`, `CREW_LEAD` or `VENDOR`.
    Otherwise `ERR_MISSING_USER_ID`, HTTP 401. Applies to every endpoint."
    PRD §2.7: "The sort plan or move-day plan id in the path, or `move_day_plan_id`
    in the body, resolves. Otherwise `ERR_PLAN_NOT_FOUND`, HTTP 404."

    Design: Corner/errors/missing_user_id_rung_precedes_role_permission_and_plan_existence
    """
    world = setup_engagement(with_client_party=False, with_family_party=True)
    party_id = world["family_party"]["id"]

    validate_error(
        api_client.approve_sort_plan(
            MISSING, {"approved_by_party_id": party_id}, headers_without_user_id("FAMILY_MEMBER")
        ),
        ApiErrorId.ERR_MISSING_USER_ID.value,
    )
    validate_error(
        api_client.approve_sort_plan(
            MISSING, {"approved_by_party_id": party_id}, make_family_member_headers(party_id)
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )


def test_the_cancelled_engagement_gate_answers_before_the_ownership_check():
    """PRD §2.6: "3. **Engagement lifecycle.** The owning engagement's `status` must
    not be `CLOSED` or `CANCELLED`; `ON_HOLD` blocks every mutation except resuming
    and cancelling the engagement. Ladder rungs 22 through 24."
    PRD §2.6: "4. **Actor authority.** Entity-backed ownership, then
    party-to-engagement membership, then the delegated-authority checks: `ACTIVE`
    status, scope, high-value scope escalation, monetary ceiling. Ladder rungs 25
    through 30."

    Design: Corner/errors/engagement_cancelled_rung_precedes_actor_ownership
    """
    set_clock("2026-05-02T09:00:00.000Z")
    owner = new_client(full_name="Ada Whitfield", phone="+1-555-0142", email=None)
    stranger = new_client(full_name="Bea Nakamura", phone="+1-555-0188", email=None)
    engagement = new_engagement(owner["id"])
    item = new_item(engagement["id"], label="Wing chair", footprint_linear_inches=30, volume_cft=20)
    get_success_data(
        api_client.cancel_engagement(
            engagement["id"], {"reason": "Client moved in with family instead"}, MOVE_MANAGER
        )
    )

    error = validate_error(
        api_client.designate_item(
            item["id"], {"disposition": "DONATE"}, make_client_headers(stranger["id"])
        ),
        ApiErrorId.ERR_ENGAGEMENT_CANCELLED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_ACTOR_NOT_OWNER.value
    assert read_item(item["id"])["disposition"] == "UNDECIDED"
    assert read_engagement(engagement["id"])["status"] == "CANCELLED"


def test_the_on_hold_gate_answers_before_the_phase_gate():
    """PRD §2.7: "The owning engagement's `status` is not `ON_HOLD`, except for
    `POST /engagements/{id}/resume` and `POST /engagements/{id}/cancel`. Otherwise
    `ERR_ENGAGEMENT_ON_HOLD`, HTTP 409."
    PRD §2.6: "5. **Timeline phase.** The engagement's derived `phase` must permit
    the operation; a milestone whose predecessor is not `COMPLETE` cannot be
    completed, and one with a `COMPLETE` successor cannot be reopened. Ladder rungs
    31 through 34."

    Design: Corner/errors/engagement_on_hold_rung_precedes_the_phase_gate
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    get_success_data(
        api_client.hold_engagement(eng_id, {"reason": "Awaiting the family conference"}, MOVE_MANAGER)
    )
    error = validate_error(
        api_client.create_move_day_plan(
            {
                "engagement_id": eng_id,
                "scheduled_start_utc": MOVE_START,
                "truck_capacity_cft": 1000,
                "truck_count": 1,
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_ENGAGEMENT_ON_HOLD.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_PHASE_NOT_PERMITTED.value
    engagement = read_engagement(eng_id)
    assert engagement["status"] == "ON_HOLD"
    assert engagement["phase"] == "ASSESSMENT"
    _, meta = validate_paginated(
        api_client.list_move_day_plans(MOVE_MANAGER, params={"engagement_id": eng_id})
    )
    assert meta["total_count"] == 0


def test_party_membership_is_checked_before_the_active_authority_rung():
    """PRD §2.7: "Every supplied party id belongs to the same engagement as the
    subject resource. Otherwise `ERR_PARTY_ENGAGEMENT_MISMATCH`, HTTP 422. Applies to
    every endpoint carrying a party id."
    PRD §2.7: "A `POWER_OF_ATTORNEY` actor holds at least one authority record whose
    `holder_party_id` is the acting party and whose `status` is `ACTIVE`. Otherwise
    `ERR_NO_ACTIVE_AUTHORITY`, HTTP 403."

    Design: Corner/errors/party_engagement_mismatch_precedes_the_active_authority_check
    """
    set_clock("2026-05-02T09:00:00.000Z")
    first_client = new_client(full_name="Ada Whitfield", phone="+1-555-0142", email=None)
    second_client = new_client(full_name="Bea Nakamura", phone="+1-555-0188", email=None)
    engagement_a = new_engagement(first_client["id"])
    party_a = new_portal_party(engagement_a["id"], "CLIENT", client_id=first_client["id"])
    engagement_b = new_engagement(
        second_client["id"], scheduled_move_start_utc="2026-07-20T14:00:00.000Z"
    )
    party_b = new_portal_party(
        engagement_b["id"], "POA", display_name="Rex Nakamura", email="rex@example.com"
    )
    item = new_item(engagement_b["id"], **DONATE_SPEC)
    designate(item["id"], "DONATE")
    plan = new_sort_plan(engagement_b["id"])
    submit_sort_plan(plan["id"])

    error = validate_error(
        api_client.approve_sort_plan(
            plan["id"],
            {"approved_by_party_id": party_a["id"]},
            make_power_of_attorney_headers(party_b["id"]),
        ),
        ApiErrorId.ERR_PARTY_ENGAGEMENT_MISMATCH.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_NO_ACTIVE_AUTHORITY.value
    stored = read_sort_plan(plan["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["approved_by_party_id"] is None


def test_the_authority_ceiling_rung_answers_before_the_phase_and_lock_gates():
    """PRD §2.7: "The acting party's `active_authority_ceiling_cents` is greater than
    or equal to the subject value, which is the item's `appraised_value_cents` for a
    single-item approval and the maximum `appraised_value_cents` among the
    engagement's non-`KEEP` items for a sort-plan approval. The boundary is
    inclusive: a ceiling exactly equal to the subject value permits the approval.
    Otherwise `ERR_AUTHORITY_CEILING_EXCEEDED`, HTTP 403."

    Design: Corner/errors/authority_ceiling_rung_precedes_the_phase_gate_on_designate
    """
    world = setup_engagement(with_poa_party=True)
    eng_id, poa_id = world["engagement_id"], world["poa_party"]["id"]
    new_active_authority(
        eng_id, poa_id, authority_scope="FULL", approval_ceiling_cents=100000
    )
    item = new_item(
        eng_id,
        label="Silver service",
        category="MISC",
        footprint_linear_inches=24,
        volume_cft=8,
        appraised_value_cents=200000,
        appraisal_source="SELF_REPORTED",
    )
    designate(item["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])

    error = validate_error(
        api_client.designate_item(
            item["id"],
            {"disposition": "HAUL_AWAY", "acting_party_id": poa_id},
            make_power_of_attorney_headers(poa_id),
        ),
        ApiErrorId.ERR_AUTHORITY_CEILING_EXCEEDED.value,
    )
    assert error["error_id"] not in (
        ApiErrorId.ERR_PHASE_NOT_PERMITTED.value,
        ApiErrorId.ERR_DISPOSITION_LOCKED.value,
    )
    assert_money(read_party(poa_id)["active_authority_ceiling_cents"], 100000, "active ceiling")
    assert read_engagement(eng_id)["phase"] == "PACK"
    stored = read_item(item["id"])
    assert stored["disposition"] == "DONATE"
    assert stored["disposition_locked"] is True


def test_the_freeze_window_answers_before_the_family_hold_rung_on_appraisal():
    """PRD §2.7: "Once the logical clock is at or after that same instant, no
    inventory item may be designated or appraised. Otherwise
    `ERR_FREEZE_WINDOW_ENTERED`, HTTP 409. Applies to
    `POST /inventory-items/{id}/designate` and `POST /inventory-items/{id}/appraise`."
    PRD §2.7: "The item's `hold_state` is `NONE` for appraisal, for staging and for
    consignment membership. Otherwise `ERR_ITEM_UNDER_FAMILY_HOLD`, HTTP 409."

    Design: Corner/errors/freeze_window_rung_precedes_the_family_hold_rung_on_appraise
    """
    world = setup_engagement(with_family_party=True)
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=60, volume_cft=45)
    designate(item["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])
    plan = new_move_day_plan(eng_id)
    new_family_hold(
        item["id"], world["family_party"]["id"], reason="Grandchild wants the sideboard"
    )
    set_clock(FREEZE_INSTANT)

    error = validate_error(
        api_client.appraise_item(
            item["id"],
            {"appraised_value_cents": 90000, "appraisal_source": "APPRAISED"},
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_FREEZE_WINDOW_ENTERED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_ITEM_UNDER_FAMILY_HOLD.value
    stored = read_item(item["id"])
    assert_money(stored["appraised_value_cents"], 0, "appraised_value_cents")
    assert stored["appraisal_source"] == "NONE"
    assert stored["hold_state"] == "HELD"


def test_the_disposition_lock_answers_before_the_room_capacity_gate():
    """PRD §2.7: "The item's `disposition_locked` is false. Otherwise
    `ERR_DISPOSITION_LOCKED`, HTTP 409. Applies to
    `POST /inventory-items/{id}/designate`."
    PRD §2.6: "12. **Business capacity and arithmetic.** Pipeline consistency,
    space-fit feasibility, consignment minimums, crew minimums and monetary bounds.
    These run last, which is why a request that is both over capacity and in the
    wrong state always reports the state error."

    Design: Corner/errors/disposition_lock_rung_precedes_the_room_capacity_rung
    """
    world = setup_engagement(
        with_residence=True,
        room_kwargs={
            "nominal_linear_inches": 100,
            "nominal_volume_cft": 100,
            "room_type": "LIVING",
        },
    )
    eng_id, room_id = world["engagement_id"], world["room"]["id"]
    sofa = new_item(eng_id, label="Sofa", footprint_linear_inches=70, volume_cft=20)
    table = new_item(eng_id, label="Side table", footprint_linear_inches=30, volume_cft=10)
    designate(sofa["id"], "KEEP", room_id)
    designate(table["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])
    get_success_data(
        api_client.reopen_milestone(
            milestone_by_key(eng_id, "SORT_PLAN")["id"],
            {"reason": "One room assignment still under discussion"},
            MOVE_MANAGER,
        )
    )

    error = validate_error(
        api_client.designate_item(
            table["id"], {"disposition": "KEEP", "assigned_room_id": room_id}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_DISPOSITION_LOCKED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED.value
    assert read_engagement(eng_id)["phase"] == "SORT_PLAN"
    room = read_room(room_id)
    assert_two_dp(room["effective_capacity_linear_inches"], 80.00, "effective capacity")
    assert_two_dp(room["keep_load_linear_inches"], 70.00, "keep_load_linear_inches")
    stored = read_item(table["id"])
    assert stored["disposition"] == "DONATE"
    assert stored["disposition_locked"] is True


def test_the_family_hold_answers_before_the_consignment_minimum():
    """PRD §2.7: "The item's `hold_state` is `NONE`, that is no dispute on the item
    is `OPEN` or `ESCALATED`. Otherwise `ERR_ITEM_UNDER_FAMILY_HOLD`, HTTP 409.
    Applies to `POST /inventory-items/{id}/designate`."
    PRD §2.7: "An item designated `SELL` has `appraised_value_cents` greater than or
    equal to 15000 cents. The boundary is inclusive. Otherwise
    `ERR_ITEM_BELOW_CONSIGN_MINIMUM`, HTTP 422."

    Design: Corner/errors/family_hold_rung_precedes_the_consign_minimum_rung
    """
    world = setup_engagement(with_client_party=False, with_family_party=True)
    item = new_item(
        world["engagement_id"],
        label="Costume brooch",
        category="JEWELRY",
        footprint_linear_inches=4,
        volume_cft=1,
        appraised_value_cents=14999,
        appraisal_source="SELF_REPORTED",
    )
    new_family_hold(
        item["id"], world["family_party"]["id"], reason="Sentimental value under review"
    )

    error = validate_error(
        api_client.designate_item(item["id"], {"disposition": "SELL"}, MOVE_MANAGER),
        ApiErrorId.ERR_ITEM_UNDER_FAMILY_HOLD.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_ITEM_BELOW_CONSIGN_MINIMUM.value
    stored = read_item(item["id"])
    assert stored["disposition"] == "UNDECIDED"
    assert stored["hold_state"] == "HELD"


def test_lot_membership_answers_before_the_state_machine_and_capacity_rungs():
    """PRD §2.7: "An item whose `consignment_lot_id` is not null cannot be designated
    to anything other than `SELL`. Otherwise `ERR_ITEM_ALREADY_CONSIGNED`, HTTP 409.
    Applies to `POST /inventory-items/{id}/designate`."
    PRD §2.6: "10. **State-machine preconditions.** The target entity's own
    originating state, its transition preconditions, and its capped-retry counters.
    Ladder rungs 48 through 63."

    Design: Corner/errors/item_already_consigned_rung_precedes_the_state_and_capacity_rungs
    """
    world = setup_engagement(
        with_client_party=False,
        with_residence=True,
        room_kwargs={"nominal_linear_inches": 100, "nominal_volume_cft": 100},
    )
    eng_id, room_id = world["engagement_id"], world["room"]["id"]
    sofa = new_item(eng_id, label="Sofa", footprint_linear_inches=70, volume_cft=20)
    designate(sofa["id"], "KEEP", room_id)
    vase = new_item(
        eng_id,
        label="Porcelain vase",
        category="ARTWORK",
        footprint_linear_inches=30,
        volume_cft=10,
        appraised_value_cents=40000,
        appraisal_source="APPRAISED",
    )
    designate(vase["id"], "SELL")
    vendor = new_vendor("Harbour Consignment", "CONSIGNMENT", "2026-12-31")
    lot = new_consignment_lot(eng_id, vendor["id"], 40000, "2026-05-02", [vase["id"]])

    error = validate_error(
        api_client.designate_item(
            vase["id"], {"disposition": "KEEP", "assigned_room_id": room_id}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_ITEM_ALREADY_CONSIGNED.value,
    )
    assert error["error_id"] not in (
        ApiErrorId.ERR_INVALID_STATE.value,
        ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED.value,
    )
    stored = read_item(vase["id"])
    assert stored["disposition"] == "SELL"
    assert stored["consignment_lot_id"] == lot["id"]
    assert_two_dp(read_room(room_id)["keep_load_linear_inches"], 70.00, "keep_load_linear_inches")
    stored_lot = read_lot(lot["id"])
    assert stored_lot["item_count"] == 1
    assert stored_lot["status"] == "LISTED"


def test_the_on_hold_gate_answers_before_the_stale_engagement_version_check():
    """PRD §2.6: "11. **Optimistic concurrency.** The supplied expected parent
    version must equal the parent's current `version`. Ladder rungs 64 through 66."
    PRD §2.7: "`expected_engagement_version` equals the engagement's `version`.
    Otherwise `ERR_STALE_ENGAGEMENT_VERSION`, HTTP 412. Applies to `POST /sort-plans`."

    Design: Corner/errors/engagement_on_hold_rung_precedes_the_stale_engagement_version_rung
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    engagement = new_engagement(client["id"])
    observed = engagement["version"]
    get_success_data(
        api_client.hold_engagement(
            engagement["id"], {"reason": "Awaiting the family conference"}, MOVE_MANAGER
        )
    )

    validate_error(
        api_client.create_sort_plan(
            create_sort_plan_payload(engagement["id"], observed), MOVE_MANAGER
        ),
        ApiErrorId.ERR_ENGAGEMENT_ON_HOLD.value,
    )
    get_success_data(api_client.resume_engagement(engagement["id"], MOVE_MANAGER))
    validate_error(
        api_client.create_sort_plan(
            create_sort_plan_payload(engagement["id"], observed), MOVE_MANAGER
        ),
        ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value,
    )
    stored = read_engagement(engagement["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["hold_count"] == 1
    _, meta = validate_paginated(
        api_client.list_sort_plans(MOVE_MANAGER, params={"engagement_id": engagement["id"]})
    )
    assert meta["total_count"] == 0


def test_the_required_field_rung_answers_before_the_enum_membership_rung():
    """PRD §2.7: "Every required input field of the endpoint is present and of its
    declared type, and the numeric fields the domain requires to be positive are
    greater than zero: `quoted_cents`, `list_price_cents`, `gross_sale_price_cents`,
    `amount_cents` on a charge line, `truck_capacity_cft`, `truck_count`,
    `footprint_linear_inches`, `volume_cft`, `nominal_linear_inches` and
    `nominal_volume_cft`. Otherwise `ERR_VALIDATION`, HTTP 400."
    PRD §2.7: "Every enum-typed input field carries a declared member of that enum."

    Design: Corner/errors/required_field_rung_precedes_the_enum_membership_rung
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    payload = create_engagement_payload(client["id"], billing_mode="WEEKLY")
    payload.pop("home_tier")

    validate_error(
        api_client.create_engagement(payload, MOVE_MANAGER), ApiErrorId.ERR_VALIDATION.value
    )
    validate_error(
        api_client.create_engagement(
            create_engagement_payload(client["id"], billing_mode="WEEKLY"), MOVE_MANAGER
        ),
        ApiErrorId.ERR_INVALID_ENUM.value,
    )
    assert (
        validate_success(api_client.get_client(client["id"], MOVE_MANAGER))["engagement_count"] == 0
    )


def test_the_crew_record_404_answers_before_the_freeze_window_gate():
    """PRD §2.7: "`crew_member_id`, `crew_assignment_id`, `replaces_assignment_id`
    and the crew or time-entry id in the path all resolve. Otherwise
    `ERR_CREW_RECORD_NOT_FOUND`, HTTP 404."
    PRD §2.7: "Once the logical clock is at or after the move-day plan's
    `freeze_at_utc`, the crew roster is locked: no crew assignment may be created,
    confirmed or re-crewed. Otherwise `ERR_FREEZE_WINDOW_ENTERED`, HTTP 409."

    Design: Corner/errors/crew_record_existence_rung_precedes_the_freeze_window_rung
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    item = new_item(eng_id, **DONATE_SPEC)
    designate(item["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])
    plan = new_move_day_plan(eng_id)
    lead = new_crew_member("Tom Reyes", "LEAD", 9500)
    set_clock(FREEZE_INSTANT)

    validate_error(
        api_client.create_crew_assignment(
            create_crew_assignment_payload(plan["id"], MISSING, plan["version"]), MOVE_MANAGER
        ),
        ApiErrorId.ERR_CREW_RECORD_NOT_FOUND.value,
    )
    validate_error(
        api_client.create_crew_assignment(
            create_crew_assignment_payload(plan["id"], lead["id"], plan["version"]), MOVE_MANAGER
        ),
        ApiErrorId.ERR_FREEZE_WINDOW_ENTERED.value,
    )
    stored = read_move_day_plan(plan["id"])
    assert stored["status"] == "DRAFT"
    assert stored["crew_confirmed_count"] == 0
    _, meta = validate_paginated(
        api_client.list_crew_assignments(MOVE_MANAGER, params={"move_day_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 0
