"""Access control: authentication, role lists, segregation of duties and resident scoping."""
from test_helpers import (
    BILLING_SPECIALIST,
    CLINICAL_STAFF,
    DIETITIAN,
    DIETITIAN_ALT,
    DINING_MANAGER,
    KITCHEN_LEAD,
    PROGRAM_ADMIN,
    ApiErrorId,
    add_menu_item,
    approve_diet_order,
    create_community,
    create_diet_order,
    create_menu_cycle,
    create_resident,
    create_venue,
    make_resident_representative_headers,
    read_menu_cycle,
    read_menu_item,
    read_ticket,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_only_the_dietitian_may_publish_and_the_role_check_comes_first(api):
    """`ClinicalStaff` is turned away on a `DRAFT` cycle with the role error, while the permitted
    role on that same row gets the state error instead — the two refusals are not interchangeable.

    PRD: "Because most write endpoints are guarded by several checks at once, the order in which
    those checks run is part of the contract: the first failing check determines the error the caller
    sees, and later checks never mask an earlier one."

    Design: Corner/rbac/clinical_staff_cannot_publish_menu_cycle
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    cycle = create_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
    )
    add_menu_item(
        cycle["id"],
        item_code="REG-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )
    assert cycle["status"] == "DRAFT"

    wrong_role = api.publish_menu_cycle(cycle["id"], CLINICAL_STAFF)
    validate_error(wrong_role, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    right_role_wrong_state = api.publish_menu_cycle(cycle["id"], DIETITIAN)
    validate_error(right_role_wrong_state, ApiErrorId.ERR_INVALID_STATE, 409)
    assert read_menu_cycle(cycle["id"])["status"] == "DRAFT"

    submitted = validate_success(api.submit_menu_cycle(cycle["id"], DINING_MANAGER))
    assert submitted["status"] == "PENDING_DIETITIAN_SIGNOFF"

    published = validate_success(api.publish_menu_cycle(cycle["id"], DIETITIAN))
    assert published["status"] == "PUBLISHED"
    assert published["signed_off_by_user_id"] == DIETITIAN["X-User-ID"]


def test_issuing_and_serving_are_shared_while_voiding_is_not(api):
    """Either service role may issue a ticket and serve the other's, but the void belongs to the
    billing specialist alone, so the manager's attempt is refused and the specialist's succeeds.

    PRD: "Voiding a ticket belongs to the `BillingSpecialist` and takes an optional `void_reason`."

    Design: Corner/rbac/both_dsm_and_satellite_lead_can_issue_tickets
    """
    set_clock("2026-08-10T12:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    venue = create_venue(
        community["id"],
        name="Aldergate Main Dining",
        venue_kind="MAIN_DINING",
        seat_capacity=12,
        care_levels_served=["ASSISTED_LIVING"],
    )
    resident = create_resident(
        community["id"], full_name="Elena Marchetti", baseline_weight_kg=62.0
    )
    order = create_diet_order(resident["id"])
    approve_diet_order(order["id"])

    manager_ticket = validate_success(
        api.create_meal_ticket(
            {
                "venue_id": venue["id"],
                "ticket_type": "RESIDENT",
                "service_date": "2026-08-10",
                "meal_period": "LUNCH",
                "resident_id": resident["id"],
            },
            DINING_MANAGER,
        ),
        201,
    )
    assert manager_ticket["billed_amount_cents"] == 650
    assert manager_ticket["issued_by_user_id"] == DINING_MANAGER["X-User-ID"]

    kitchen_ticket = validate_success(
        api.create_meal_ticket(
            {
                "venue_id": venue["id"],
                "ticket_type": "TAKEOUT",
                "service_date": "2026-08-10",
                "meal_period": "LUNCH",
                "resident_id": resident["id"],
            },
            KITCHEN_LEAD,
        ),
        201,
    )
    assert kitchen_ticket["billed_amount_cents"] == 1219
    assert kitchen_ticket["issued_by_user_id"] == KITCHEN_LEAD["X-User-ID"]

    crossed_one = validate_success(
        api.serve_meal_ticket(manager_ticket["id"], KITCHEN_LEAD)
    )
    crossed_two = validate_success(
        api.serve_meal_ticket(kitchen_ticket["id"], DINING_MANAGER)
    )
    assert crossed_one["status"] == "SERVED"
    assert crossed_two["status"] == "SERVED"

    refused = api.void_meal_ticket(
        manager_ticket["id"], {"void_reason": "tray returned untouched"}, DINING_MANAGER
    )
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert read_ticket(manager_ticket["id"])["status"] == "SERVED"

    voided = validate_success(
        api.void_meal_ticket(
            manager_ticket["id"],
            {"void_reason": "tray returned untouched"},
            BILLING_SPECIALIST,
        )
    )

    assert voided["status"] == "VOIDED"
    assert voided["voided_amount_cents"] == 650
    assert voided["billed_amount_cents"] == 0


def test_a_request_without_a_usable_role_header_is_unauthenticated(api):
    """Authentication is settled before any id is resolved, so the header-less read of an id that
    resolves to nothing is a 401 rather than a 404, and an invented role name fares the same.

    PRD: "**Authentication** — headers present and well-formed, role among the seven, and for a
    `ResidentRepresentative` an `X-User-ID` that resolves to an existing resident:
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])

    headerless = api.get_community("00000000-0000-4000-8000-0000000000ff", {})
    error = validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert error["error_id"] != ApiErrorId.ERR_COMMUNITY_NOT_FOUND.value

    invented_role = api.get_community(
        community["id"], {"X-User-Role": "NotARole", "X-User-ID": "nar-1"}
    )
    validate_error(invented_role, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    headerless_write = api.create_menu_cycle(
        {
            "community_id": community["id"],
            "cycle_number": 1,
            "week_count": 1,
            "effective_start_date": "2026-08-10",
            "effective_end_date": "2026-08-16",
        },
        {},
    )
    validate_error(headerless_write, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    _, meta = validate_paginated(
        api.list_community_menu_cycles(community["id"], PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 0


def test_a_dietitian_cannot_review_the_extension_they_authored(api):
    """Both actors hold the same role, so the refusal is keyed on the recorded author rather than on
    the role list; the second dietitian's approval lands and completes the item's coverage.

    PRD: "Segregation of duties is enforced on top of role authorization and is a separate refusal,
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): the dietitian recording a decision on a diet order must
    not be the operator identified by that order's `ordered_by_user_id`; the dietitian reviewing a
    therapeutic extension must not be the operator identified by its `authored_by_user_id`; and the
    dietitian completing a plan-of-care review must not be the operator identified by the
    `recorded_by_user_id` of the intake observation that triggered it."

    Design: Corner/rbac/dietitian_cannot_review_own_therapeutic_extension
    """
    community = create_community("Brookdale Aldergate", ["SKILLED_NURSING"])
    cycle = create_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
    )
    item = add_menu_item(
        cycle["id"],
        item_code="REG-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
        required_therapeutic_codes=["RENAL"],
    )
    extension = validate_success(
        api.create_therapeutic_extension(
            item["id"],
            {"diet_code": "RENAL", "nutrient_overrides": {"sodium_mg": 500}},
            DIETITIAN,
        ),
        201,
    )
    assert extension["authored_by_user_id"] == DIETITIAN["X-User-ID"]
    assert extension["review_status"] == "DRAFT"

    submitted = validate_success(
        api.submit_therapeutic_extension(extension["id"], DIETITIAN)
    )
    assert submitted["review_status"] == "SUBMITTED"

    self_review = api.review_therapeutic_extension(
        extension["id"],
        {"decision": "APPROVE", "reviewer_note": "self review attempt"},
        DIETITIAN,
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    peer_review = validate_success(
        api.review_therapeutic_extension(
            extension["id"],
            {"decision": "APPROVE", "reviewer_note": "sodium target verified"},
            DIETITIAN_ALT,
        )
    )

    assert peer_review["review_status"] == "APPROVED"
    assert peer_review["reviewed_by_user_id"] == DIETITIAN_ALT["X-User-ID"]
    assert peer_review["review_round"] == 0
    assert read_menu_item(item["id"])["extension_coverage_status"] == "COMPLETE"


def test_a_representative_reads_its_own_resident_and_no_other(api):
    """The scoping is per row, not per endpoint: the same reads that answer for the acting resident
    are refused for a sibling — including the diet order reached by its own id — while the
    community read stays open.

    PRD: "Ownership checks then compare the addressed resource's resident reference to `X-User-ID`: a
    `ResidentRepresentative` may read or write only the record of the resident their `X-User-ID`
    resolves to, whether that resident is named by a path id, by a `resident_id` in the payload, or
    indirectly as the owning resident of an addressed diet order, seating reservation, plan-of-care
    review or intake observation."

    Design: Corner/rbac/resident_representative_scoped_to_own_resident
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident_a = create_resident(
        community["id"], full_name="Resident A", baseline_weight_kg=70.0
    )
    resident_b = create_resident(
        community["id"], full_name="Resident B", baseline_weight_kg=71.0
    )
    order_b = create_diet_order(resident_b["id"])
    approve_diet_order(order_b["id"])
    representative = make_resident_representative_headers(resident_a["id"])

    own = validate_success(api.get_resident(resident_a["id"], representative))
    assert own["full_name"] == "Resident A"
    assert own["dining_status"] == "ACTIVE"

    other = api.get_resident(resident_b["id"], representative)
    validate_error(other, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    other_observations = api.list_intake_observations(resident_b["id"], representative)
    validate_error(other_observations, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    other_order = api.get_diet_order(order_b["id"], representative)
    error = validate_error(other_order, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert error["error_id"] != ApiErrorId.ERR_DIET_ORDER_NOT_FOUND.value

    open_read = validate_success(api.get_community(community["id"], representative))
    assert open_read["name"] == "Brookdale Aldergate"
