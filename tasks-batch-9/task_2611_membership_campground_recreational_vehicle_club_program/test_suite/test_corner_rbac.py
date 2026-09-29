"""Authentication, role exclusivity, ownership scope and segregation of duties."""

from test_helpers import (
    ADMIN,
    ADMIN_2,
    CLUB_ADMIN_PRIMARY_ID,
    GUEST,
    NON_EXISTENT_UUID,
    OFFICER,
    assert_reservation_state,
    book_member_stay,
    build_user_headers,
    create_classic_tier,
    create_open_park,
    create_park,
    create_member,
    headers_without_user_id,
    list_invoices,
    make_capital_decision_payload,
    make_capital_project_payload,
    make_exception_decision_payload,
    make_maintenance_window_payload,
    make_membership_payload,
    make_park_manager_headers,
    make_payment_payload,
    make_reservation_payload,
    make_transfer_decision_payload,
    make_transient_reservation_payload,
    propose_project,
    read_park,
    read_project,
    read_reservation,
    reset_clock,
    schedule_window,
    sell_membership_to_new_member,
    submit_transfer,
    validate_error,
    validate_success,
)


def test_identity_and_role_gates_outrank_existence_and_domain_rules(api):
    """Every role is pushed at another role's exclusive endpoint, headquarters included.

    PRD §2.1: "If both headers are well formed but the named role does not appear
    in the authorised-role list for the addressed operation — the list given in §4
    — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/identity_and_role_gates_outrank_existence_and_domain_rules
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    park = create_open_park(
        api,
        name="Sable Creek Campground",
        park_class="CLASS_C",
        total_sites=30,
        member_allocation_pct=60,
    )
    booking_body = make_reservation_payload(
        park["id"], holder["membership_id"], "2026-08-20", "2026-08-22"
    )

    validate_error(
        api.create_reservation(booking_body, headers_without_user_id("Member")),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(api.create_reservation(booking_body, OFFICER), "ERR_UNAUTHORIZED", 403)
    validate_error(
        api.create_transient_reservation(
            make_transient_reservation_payload(
                park["id"], "2026-08-20", "2026-08-22", guest_name="Dana Whitlock"
            ),
            holder["headers"],
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.create_membership(
            make_membership_payload(holder["member_id"], tier["id"]), GUEST
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.create_maintenance_window(
            make_maintenance_window_payload(
                park["id"], "2026-10-05", "2026-10-09", work_type="ROUTINE"
            ),
            ADMIN,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    # Both ids below are fabricated, so a 404 would leak the id space: the role
    # gate must report ahead of the existence rules.
    validate_error(
        api.decide_transfer_request(
            NON_EXISTENT_UUID,
            make_transfer_decision_payload("APPROVE"),
            make_park_manager_headers(park["id"]),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.decide_occupancy_exception(
            NON_EXISTENT_UUID,
            make_exception_decision_payload("GRANT", granted_run_nights=20),
            holder["headers"],
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    guest_stay = validate_success(
        api.create_transient_reservation(
            make_transient_reservation_payload(
                park["id"], "2026-08-20", "2026-08-22", guest_name="Owen Deleon"
            ),
            GUEST,
        ),
        201,
    )
    assert_reservation_state(guest_stay, "CONFIRMED", pool_charged="TRANSIENT_POOL")
    manager_window = validate_success(
        api.create_maintenance_window(
            make_maintenance_window_payload(
                park["id"], "2026-10-05", "2026-10-09", work_type="ROUTINE"
            ),
            make_park_manager_headers(park["id"]),
        ),
        201,
    )
    assert manager_window["status"] == "SCHEDULED", "the refusals were the role and nothing else"


def test_a_member_cannot_read_or_move_another_members_resources(api):
    """Five ownership probes fail for a Member and the same reads pass for headquarters.

    PRD §2.1: "Concretely, a `Member` acting on a membership, a reservation, a dues
    invoice, a transfer request or an occupancy exception must be the holder of the
    membership that owns it, and a mismatch is refused with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/a_member_cannot_read_or_move_another_members_resources
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    first = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    second = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Nathan Boyle", "email": "nathan.boyle@example.com"},
    )
    park = create_open_park(
        api,
        name="Sable Creek Campground",
        park_class="CLASS_C",
        total_sites=30,
        member_allocation_pct=60,
    )
    stay = book_member_stay(
        api, first["headers"], park["id"], first["membership_id"], "2026-08-20", "2026-08-22"
    )
    assert stay["status"] == "CONFIRMED"
    foreign_invoice = list_invoices(api, second["membership_id"])[0]
    assert foreign_invoice["amount_cents"] == 45360

    validate_error(
        api.get_membership(second["membership_id"], first["headers"]),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api.list_membership_dues_invoices(second["membership_id"], first["headers"]),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api.create_reservation(
            make_reservation_payload(
                park["id"], second["membership_id"], "2026-08-25", "2026-08-27"
            ),
            first["headers"],
        ),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api.cancel_reservation(stay["id"], second["headers"]), "ERR_NOT_RESOURCE_OWNER", 403
    )
    assert read_reservation(api, stay["id"])["status"] == "CONFIRMED"
    # Ownership is settled before any fiscal arithmetic, so the deliberately wrong
    # amount of 1 cent never reaches the payment-amount rule.
    validate_error(
        api.pay_dues_invoice(foreign_invoice["id"], make_payment_payload(1), first["headers"]),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )

    own = validate_success(
        api.get_membership(first["membership_id"], first["headers"]), 200
    )
    assert own["id"] == first["membership_id"]
    admin_read = validate_success(api.get_membership(second["membership_id"], ADMIN), 200)
    assert admin_read["membership_status"] == "ACTIVE", "the owner rule never fires for ClubAdmin"
    own_stay = validate_success(api.get_reservation(stay["id"], first["headers"]), 200)
    assert own_stay["id"] == stay["id"]


def test_a_park_manager_may_only_write_against_its_own_park(api):
    """Six writes at the neighbouring park are refused while the reads still pass.

    PRD §2.1: "When `X-User-Role` is `ParkManager`, `X-User-ID` is the `id` of the acting
    `Park`; a park manager may only reach a park directly, or indirectly through a maintenance
    window, an amenity inspection, a capital project or a reservation whose park is that same
    park, and a mismatch is refused with `ERR_NOT_PARK_MANAGER` (HTTP 403)."

    Design: Corner/rbac/a_park_manager_may_only_write_against_its_own_park
    """
    reset_clock(api)
    home = create_park(
        api,
        name="Sable Creek Campground",
        park_class="CLASS_C",
        total_sites=30,
        member_allocation_pct=60,
    )
    neighbour = create_open_park(
        api,
        name="Ridgeline RV Resort",
        park_class="CLASS_B",
        total_sites=24,
        member_allocation_pct=50,
    )
    neighbour_window = schedule_window(
        api, neighbour["id"], "2026-09-01", "2026-09-04", work_type="ROUTINE"
    )
    outsider = make_park_manager_headers(home["id"])

    validate_error(
        api.open_park_season(neighbour["id"], outsider), "ERR_NOT_PARK_MANAGER", 403
    )
    validate_error(
        api.close_park_season(neighbour["id"], outsider), "ERR_NOT_PARK_MANAGER", 403
    )
    validate_error(
        api.file_amenity_inspection(
            neighbour["id"],
            {"restroom_score": 4, "hookup_score": 4, "utility_score": 4, "road_score": 4},
            outsider,
        ),
        "ERR_NOT_PARK_MANAGER",
        403,
    )
    validate_error(
        api.create_maintenance_window(
            make_maintenance_window_payload(
                neighbour["id"], "2026-10-01", "2026-10-03", work_type="EMERGENCY"
            ),
            outsider,
        ),
        "ERR_NOT_PARK_MANAGER",
        403,
    )
    validate_error(
        api.create_capital_project(
            make_capital_project_payload(
                neighbour["id"],
                title="Ridgeline utility loop rebuild",
                category="UTILITY",
                requested_cost_cents=4500000,
                fiscal_year=2027,
            ),
            outsider,
        ),
        "ERR_NOT_PARK_MANAGER",
        403,
    )
    # The scope is resolved through the addressed window's park, not the path.
    validate_error(
        api.activate_maintenance_window(neighbour_window["id"], outsider),
        "ERR_NOT_PARK_MANAGER",
        403,
    )

    untouched = validate_success(api.get_park(neighbour["id"], outsider), 200)
    assert untouched["park_status"] == "OPEN", "an out-of-scope manager may still read the park"
    listed = validate_success(
        api.list_park_maintenance_windows(neighbour["id"], outsider), 200
    )
    assert listed[0]["status"] == "SCHEDULED"
    assert listed[0]["cancelled_reservation_count"] == 0

    activated = validate_success(
        api.activate_maintenance_window(
            neighbour_window["id"], make_park_manager_headers(neighbour["id"])
        ),
        200,
    )
    assert activated["status"] == "ACTIVE", "the owning manager may do what the outsider cannot"
    opened = validate_success(api.open_park_season(home["id"], outsider), 200)
    assert opened["park_status"] == "OPEN", "the same identity is in scope at its own park"


def test_the_user_that_proposes_can_never_be_the_user_that_decides(api):
    """The identity comparison is on X-User-ID alone and is blind to the role header.

    PRD §2.2: "That equality comparison is the entire mechanism behind the club's
    segregation-of-duties rule: the `X-User-ID` that decides a capital project must
    differ from the `X-User-ID` recorded as having created it, and the `X-User-ID`
    that decides a transfer request must differ from the `X-User-ID` that submitted
    it. Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_user_that_proposes_can_never_be_the_user_that_decides
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    receiver = create_member(api, full_name="Nathan Boyle", email="nathan.boyle@example.com")
    request = submit_transfer(
        api, holder["headers"], holder["membership_id"], receiver["id"], transfer_type="GIFT"
    )
    park = create_open_park(
        api,
        name="Sable Creek Campground",
        park_class="CLASS_C",
        total_sites=30,
        member_allocation_pct=60,
    )
    admin_project = propose_project(
        api,
        park["id"],
        ADMIN,
        title="Sable Creek bathhouse rebuild",
        category="SAFETY",
        requested_cost_cents=3000000,
        fiscal_year=2027,
    )
    manager_project = propose_project(
        api,
        park["id"],
        make_park_manager_headers(park["id"]),
        title="Sable Creek pull-through expansion",
        category="EXPANSION",
        requested_cost_cents=2500000,
        fiscal_year=2027,
    )
    assert admin_project["requested_by_user_id"] == CLUB_ADMIN_PRIMARY_ID
    assert manager_project["requested_by_user_id"] == park["id"]
    version_before = read_park(api, park["id"])["version"]

    # The submitting member's id behind a ClubAdmin role header is still that id.
    validate_error(
        api.decide_transfer_request(
            request["id"],
            make_transfer_decision_payload("APPROVE"),
            build_user_headers(holder["member_id"], "ClubAdmin"),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    assert validate_success(api.get_transfer_request(request["id"], ADMIN), 200)[
        "status"
    ] == "SUBMITTED"
    approved = validate_success(
        api.decide_transfer_request(
            request["id"], make_transfer_decision_payload("APPROVE"), ADMIN
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["successor_membership_id"] is not None

    validate_error(
        api.decide_capital_project(
            admin_project["id"],
            make_capital_decision_payload("APPROVE", version_before),
            ADMIN,
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    decided = validate_success(
        api.decide_capital_project(
            admin_project["id"],
            make_capital_decision_payload("APPROVE", version_before),
            ADMIN_2,
        ),
        200,
    )
    assert decided["status"] == "APPROVED", (
        "the refused attempt bumped no park version, so the pinned figure was still fresh"
    )
    version_after = read_park(api, park["id"])["version"]
    assert version_after > version_before, "an accepted decision does increment the park version"

    validate_error(
        api.decide_capital_project(
            manager_project["id"],
            make_capital_decision_payload("APPROVE", version_after),
            build_user_headers(park["id"], "ClubAdmin"),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    manager_decided = validate_success(
        api.decide_capital_project(
            manager_project["id"],
            make_capital_decision_payload("APPROVE", version_after),
            ADMIN,
        ),
        200,
    )
    assert manager_decided["status"] == "APPROVED"
    assert read_project(api, manager_project["id"])["decided_by_user_id"] == (
        CLUB_ADMIN_PRIMARY_ID
    ), "the audit trail names the second party rather than the proposer"
