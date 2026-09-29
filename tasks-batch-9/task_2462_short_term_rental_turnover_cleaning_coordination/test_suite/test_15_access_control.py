"""Role exclusivity and the three ownership scopes: pay lines, units and assignments."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_turnover_payload,
    cleaner_status_payload,
    create_property_payload,
    create_quality_audit_payload,
    fixtures as fx,
    make_cleaner_headers,
    make_property_owner_headers,
    make_quality_auditor_headers,
    review_task_payload,
    submit_task_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]
THIRD = TEST_USERS["coordinator_third_headers"]
FOURTH = TEST_USERS["coordinator_fourth_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def unassigned_world(api):
    """P1, Cleaner C, OUT-1/IN-1 and T1 at version 1 with nothing offered yet."""
    return fx.build_world(api, supply=None)


@pytest.fixture
def paid_and_unpaid_cleaners(api):
    """Cleaner C owns the PROVISIONAL pay line; Cleaner B has no work at all."""
    world = fx.world_scheduled(api, supply="pair")
    world["cb"] = fx.seed_cleaner(
        api, name="Cleaner B", skill_level=3, initial_quality_score=85.00)
    return world


@pytest.fixture
def two_units_two_stays(api):
    """P1 and P2, one reservation each, and a stock line that belongs to P2."""
    fx.reset_clock(api)
    p1 = validate_success(api.create_property(create_property_payload(), ADMIN), 201)
    p2 = validate_success(api.create_property(create_property_payload(
        code="AUS-102", name="Rainey Studio", zone_code="ZONE_B",
        size_tier="STUDIO", owner_contact_email="owner2@example.com"), ADMIN), 201)
    b1 = fx.seed_booking(
        api, p1["id"], external_ref="OUT-1", guest_name="Guest One",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    b2 = fx.seed_booking(
        api, p2["id"], external_ref="OUT-2", guest_name="Guest Two",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    fx.seed_supply_line(
        api, p2["id"], sku="CON-COFFEE", name="Coffee Box",
        category="CONSUMABLE", unit_cost_cents=340, par_qty=4, unit="BOX",
        initial_on_hand_qty=4)
    return {"p1": p1, "p2": p2, "b1": b1, "b2": b2}


@pytest.fixture
def offered_to_one_of_two_cleaners(api):
    """T1 offered to Cleaner C, the guest checked out, and Cleaner B idle and eligible."""
    world = fx.build_world(api, supply=None)
    world["cb"] = fx.seed_cleaner(
        api, name="Cleaner B", skill_level=4, initial_quality_score=90.00)
    fx.offer_turnover(api, world)
    fx.reset_clock(api, "2026-08-08T16:00:00Z")
    validate_success(api.checkout_booking(world["b_out"]["id"], {}, COORDINATOR))
    return world


@pytest.fixture
def completed_turn_with_four_operator_identities(api):
    """coord-1 offered it, coord-2 and coord-3 split the reviews, coord-4 closed it."""
    world = fx.build_world(api, supply="pair")
    fx.offer_turnover(api, world)
    fx.accept_offer(api, world)
    fx.start_clean(api, world)
    fx.submit_all_tasks(api, world)
    reviewed = []
    for index, task in enumerate(world["tasks"]):
        headers = REVIEWER if index < 2 else THIRD
        reviewed.append(validate_success(api.review_checklist_task(
            task["id"], review_task_payload("APPROVE"), headers)))
    world["tasks"] = reviewed
    world["t1"] = validate_success(api.complete_turnover(
        world["t1"]["id"], {"completion_note": "all rows verified"}, FOURTH))
    return world


# ─── rbac ─────────────────────────────────────────────────────────────────

def test_01_no_role_may_borrow_another_roles_exclusive_operation(
        api, unassigned_world):
    """Nine cross-role writes are refused, including two attempted by the admin.

    PRD §2.1: "A syntactically valid request whose role is not listed among the
    authorized roles for the addressed endpoint is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)." PRD §2.5: "2. **Role authorization.** The
    acting role must appear in the addressed endpoint's authorized-role list, on
    every endpoint. Failure yields `ERR_UNAUTHORIZED` (403)." PRD §2.5: "A
    request is evaluated through the following gates, and the **first** gate that
    fails determines the response; no later gate may mask an earlier one."

    Design: Corner/rbac/corner_rbac_no_role_can_perform_another_roles_exclusive_operation
    """
    world = unassigned_world

    validate_error(api.create_cleaner(
        {"name": "Sneaky Hire", "home_zone_code": "ZONE_A", "skill_level": 3},
        COORDINATOR), ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.set_cleaner_status(
        world["cc"]["id"], cleaner_status_payload("SUSPEND", "not your call"),
        COORDINATOR), ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.set_clock("2026-08-09T00:00:00Z", COORDINATOR),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.assign_turnover(
        world["t1"]["id"],
        assign_turnover_payload(world["t1"]["version"], world["cc"]["id"]),
        world["cleaner_headers"]), ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.create_booking({
        "property_id": world["p1"]["id"], "external_ref": "ADMIN-1",
        "guest_name": "Admin Guest", "checkin_at": "2026-10-01T21:00:00Z",
        "checkout_at": "2026-10-03T16:00:00Z"}, ADMIN),
        ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.start_turnover(world["t1"]["id"], {}, COORDINATOR),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.create_quality_audit(
        create_quality_audit_payload(world["t1"]["id"], 90), COORDINATOR),
        ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.create_turnover(
        {"outgoing_booking_id": world["b_out"]["id"]}, AUDITOR),
        ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.cancel_booking(
        world["b_out"]["id"], {"cancellation_reason": "owner walked in"},
        make_property_owner_headers(world["p1"]["id"])),
        ApiErrorId.ERR_UNAUTHORIZED, 403)

    turnover = fx.read_turnover(api, world)
    assert turnover["status"] == "PENDING_ASSIGNMENT", (
        f"nine denials must have moved nothing, got {turnover['status']}")
    assert turnover["version"] == 1, (
        f"a refusal at gate 2 never reaches a write, got {turnover['version']}")
    assert fx.read_cleaner(api, world)["status"] == "ACTIVE", (
        f"the refused suspension must not have landed, got "
        f"{fx.read_cleaner(api, world)['status']}")

    _, meta = validate_paginated(
        api.list_bookings(COORDINATOR, {"property_id": world["p1"]["id"]}))
    assert meta["total_count"] == 2, (
        f"the administrator's reservation attempt persisted nothing, "
        f"got {meta['total_count']}")


def test_02_a_cleaner_reads_only_its_own_pay_lines_and_never_a_peers(
        api, paid_and_unpaid_cleaners):
    """An unfiltered read, a peer filter and a peer id are each 403, not empty pages.

    PRD §2.5: "4. **Cleaner pay-line scoping.** On the two pay-line reads (`GET
    /pay-lines` and `GET /pay-lines/{id}`), a `Cleaner` reading the collection must
    pass a `cleaner_id` filter equal to its own `X-User-ID`, and a `Cleaner`
    reading a single pay line may only address one whose `cleaner_id` equals its
    own `X-User-ID`. Failure yields `ERR_UNAUTHORIZED` (403)." PRD §4: "A Cleaner
    must pass its own id as cleaner_id." PRD §4: "A Cleaner may only read a pay
    line whose cleaner_id equals its own X-User-ID."

    Design: Corner/rbac/corner_rbac_cleaner_pay_line_reads_are_self_scoped_at_priority_four
    """
    world = paid_and_unpaid_cleaners
    ca, cb = world["cc"]["id"], world["cb"]["id"]
    peer_headers = make_cleaner_headers(cb)

    line = validate_success(api.list_pay_lines(COORDINATOR, {"cleaner_id": ca}))[0]
    assert line["cleaner_id"] == ca, (
        f"the only pay line belongs to the accepting cleaner, "
        f"got {line['cleaner_id']}")

    validate_error(api.list_pay_lines(world["cleaner_headers"]),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.list_pay_lines(world["cleaner_headers"], {"cleaner_id": cb}),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api.get_pay_line(line["id"], peer_headers),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)

    own, own_meta = validate_paginated(
        api.list_pay_lines(world["cleaner_headers"], {"cleaner_id": ca}))
    assert own_meta["total_count"] == 1, (
        f"the self-scoped read must succeed, got {own_meta['total_count']}")
    assert own[0]["cleaner_id"] == ca, (
        f"the self-scoped read returns its own row, got {own[0]['cleaner_id']}")
    assert own[0]["net_cents"] == 12554, (
        f"the provisional net must be 11254 + 1300, got {own[0]['net_cents']}")

    single = validate_success(
        api.get_pay_line(line["id"], world["cleaner_headers"]))
    assert single["net_cents"] == 12554, (
        f"the same figure must read back by id, got {single['net_cents']}")
    assert single["status"] == "PROVISIONAL", (
        f"the line is still provisional, got {single['status']}")

    _, admin_meta = validate_paginated(api.list_pay_lines(COORDINATOR))
    assert admin_meta["total_count"] == 1, (
        f"the scope rule binds only the Cleaner role, "
        f"got {admin_meta['total_count']}")


def test_03_a_property_owner_may_not_look_outside_the_unit_it_identifies_as(
        api, two_units_two_stays):
    """A neighbour's row, an unfiltered page and a foreign filter are all one code.

    PRD §2.1: "When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the `id` of
    the acting `Property`; ownership checks compare the addressed resource's
    property reference to `X-User-ID`, and on the list reads available to owners
    the `property_id` filter is mandatory and must equal `X-User-ID`." PRD §2.1:
    "Addressing a resource outside its own unit, or omitting that mandatory
    filter, is rejected with `ERR_NOT_PROPERTY_OWNER` (HTTP 403)." PRD §2.5: "7.
    **Property-owner scoping.** A `PropertyOwner` may only touch its own unit:
    `X-User-ID` must equal the addressed property's `id`, or the mandatory
    `property_id` filter on a list read."

    Design: Corner/rbac/corner_rbac_property_owner_is_confined_to_the_property_it_identifies_as
    """
    world = two_units_two_stays
    owner = make_property_owner_headers(world["p1"]["id"])

    validate_error(api.get_property(world["p2"]["id"], owner),
                   ApiErrorId.ERR_NOT_PROPERTY_OWNER, 403)
    validate_error(api.list_bookings(owner),
                   ApiErrorId.ERR_NOT_PROPERTY_OWNER, 403)
    validate_error(api.list_bookings(owner, {"property_id": world["p2"]["id"]}),
                   ApiErrorId.ERR_NOT_PROPERTY_OWNER, 403)
    validate_error(api.list_property_supply_lines(world["p2"]["id"], owner),
                   ApiErrorId.ERR_NOT_PROPERTY_OWNER, 403)

    own_unit = validate_success(api.get_property(world["p1"]["id"], owner))
    assert own_unit["code"] == "AUS-101", (
        f"reading its own unit is unaffected, got {own_unit['code']}")
    assert own_unit["status"] == "ACTIVE", (
        f"the unit is operationally active, got {own_unit['status']}")

    own_stays, own_meta = validate_paginated(
        api.list_bookings(owner, {"property_id": world["p1"]["id"]}))
    assert own_meta["total_count"] == 1, (
        f"the self-scoped page shows only its own stay, "
        f"got {own_meta['total_count']}")
    assert own_stays[0]["external_ref"] == "OUT-1", (
        f"that stay is OUT-1, got {own_stays[0]['external_ref']}")

    _, all_meta = validate_paginated(api.list_bookings(COORDINATOR))
    assert all_meta["total_count"] == 2, (
        f"the same endpoint answers a coordinator unfiltered, "
        f"got {all_meta['total_count']}")


def test_04_a_peer_cleaner_is_refused_on_both_the_direct_and_indirect_routes(
        api, offered_to_one_of_two_cleaners):
    """Ownership is checked before the offer's own state, on and off the assignment URL.

    PRD §2.1: "Concretely, a cleaner may act only on an `Assignment` whose
    `cleaner_id` equals its own `X-User-ID`, and may act on a turnover, a
    checklist task or an issue report only when the covering non-terminal
    assignment on that turnover belongs to it; a violation is rejected with
    `ERR_NOT_ASSIGNMENT_OWNER` (HTTP 403)." PRD §2.5: "8. **Cleaner work
    scoping.** A `Cleaner` may only act on its own work: the addressed
    assignment's `cleaner_id`, or the `cleaner_id` of the turnover's `ACCEPTED` or
    `ACTIVE` assignment, must equal the acting `X-User-ID`." PRD §2.5: "A request
    is evaluated through the following gates, and the **first** gate that fails
    determines the response; no later gate may mask an earlier one."

    Design: Corner/rbac/corner_rbac_cleaner_may_only_act_on_its_own_assignment_and_turnover
    """
    world = offered_to_one_of_two_cleaners
    peer = make_cleaner_headers(world["cb"]["id"])
    assert world["a1"]["cleaner_id"] == world["cc"]["id"], (
        f"the offer belongs to Cleaner C, got {world['a1']['cleaner_id']}")

    validate_error(api.accept_assignment(world["a1"]["id"], {}, peer),
                   ApiErrorId.ERR_NOT_ASSIGNMENT_OWNER, 403)
    validate_error(api.decline_assignment(
        world["a1"]["id"], {"decline_reason": "not mine to decline"}, peer),
        ApiErrorId.ERR_NOT_ASSIGNMENT_OWNER, 403)

    accepted = validate_success(api.accept_assignment(
        world["a1"]["id"], {}, world["cleaner_headers"]))
    assert accepted["status"] == "ACCEPTED", (
        f"the rightful cleaner may accept, got {accepted['status']}")

    validate_error(api.start_turnover(world["t1"]["id"], {}, peer),
                   ApiErrorId.ERR_NOT_ASSIGNMENT_OWNER, 403)

    started = validate_success(
        api.start_turnover(world["t1"]["id"], {}, world["cleaner_headers"]))
    assert started["status"] == "IN_PROGRESS", (
        f"the rightful cleaner may start, got {started['status']}")

    tasks = validate_success(
        api.list_turnover_checklist_tasks(world["t1"]["id"], COORDINATOR))
    strip = tasks[0]

    validate_error(api.submit_checklist_task(
        strip["id"], submit_task_payload(note="helping out"), peer),
        ApiErrorId.ERR_NOT_ASSIGNMENT_OWNER, 403)

    submitted = validate_success(api.submit_checklist_task(
        strip["id"], submit_task_payload(note="linens stripped"),
        world["cleaner_headers"]))
    assert submitted["status"] == "SUBMITTED", (
        f"the rightful cleaner may submit, got {submitted['status']}")


def test_05_segregation_of_duties_bans_participating_identities_not_the_role(
        api, completed_turn_with_four_operator_identities):
    """Three identities recorded on this turnover are barred and a fourth samples it.

    PRD §2.5: "14. **Segregation of duties.** On `POST /quality-audits`, the
    acting auditor's `X-User-ID` must differ from the turnover's
    `assigned_by_user_id` and from every `reviewed_by_user_id` recorded on that
    turnover's checklist tasks. Failure yields `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §3.9: "The independence rule is the sharpest of the four: the acting
    auditor's `X-User-ID` must differ both from the `assigned_by_user_id` recorded
    on the turnover's assignment and from every `reviewed_by_user_id` recorded on
    that turnover's checklist rows, failing which the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`." PRD §3.9: "A successful sample lands in `status`
    `SAMPLED`, records `auditor_user_id` from the acting `X-User-ID`, and copies
    `cleaner_id` from the turnover's `COMPLETED` assignment." PRD §2.1: "When
    `X-User-Role` is `QualityAuditor`, `X-User-ID` is again an opaque operator
    identifier, recorded as `auditor_user_id` on the `QualityAudit` it samples and
    compared thereafter only against other recorded operator identifiers, never
    against an entity `id`."

    Design: Corner/rbac/corner_rbac_segregation_of_duties_bans_participating_identities_not_a_whole_role
    """
    world = completed_turn_with_four_operator_identities
    assert world["a1"]["assigned_by_user_id"] == "coord-1", (
        f"the offering identity is recorded from X-User-ID, "
        f"got {world['a1']['assigned_by_user_id']}")
    assert world["tasks"][0]["reviewed_by_user_id"] == "coord-2", (
        f"the first two rows were cleared by coord-2, "
        f"got {world['tasks'][0]['reviewed_by_user_id']}")
    assert world["tasks"][3]["reviewed_by_user_id"] == "coord-3", (
        f"the last two rows were cleared by coord-3, "
        f"got {world['tasks'][3]['reviewed_by_user_id']}")
    assert world["t1"]["status"] == "COMPLETED", (
        f"the completion gate must already be satisfied, "
        f"got {world['t1']['status']}")

    payload = create_quality_audit_payload(world["t1"]["id"], 91)
    for banned in ("coord-1", "coord-2", "coord-3"):
        validate_error(
            api.create_quality_audit(payload, make_quality_auditor_headers(banned)),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    _, meta = validate_paginated(api.list_quality_audits(
        make_quality_auditor_headers("coord-1"),
        {"turnover_id": world["t1"]["id"]}))
    assert meta["total_count"] == 0, (
        f"a banned identity may still read; only sampling is segregated, "
        f"got {meta['total_count']}")

    audit = validate_success(api.create_quality_audit(
        create_quality_audit_payload(world["t1"]["id"], 91, findings="spotless"),
        make_quality_auditor_headers("coord-4")), 201)
    assert audit["status"] == "SAMPLED", (
        f"coord-4 appears nowhere in the offer or review history, "
        f"got {audit['status']}")
    assert audit["auditor_user_id"] == "coord-4", (
        f"auditor_user_id is the acting X-User-ID, got {audit['auditor_user_id']}")
    assert audit["cleaner_id"] == world["cc"]["id"], (
        f"cleaner_id is copied from the COMPLETED assignment, "
        f"got {audit['cleaner_id']}")
