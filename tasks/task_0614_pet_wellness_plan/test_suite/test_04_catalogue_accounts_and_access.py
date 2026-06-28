"""Catalogue/account CRUD, computed and system fields, RBAC, OCC, and consistency.

Corner queue (B) only: entities, endpoints, rbac, cross_cutting_complexity_layers
(optimistic concurrency), and consistency_model.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    create_plan_with_services,
    create_clinic,
    create_account_and_membership,
    add_pet,
    activate_membership,
    record_visit,
    create_plan,
    create_member_account,
    make_member_headers,
    create_plan_payload,
    create_membership_payload,
    plan_change_payload,
    first_active_term,
    get_membership,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]
BILLING_ADMIN = TEST_USERS["billing_admin_headers"]


def _plus_plan():
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        enrollment_fee_cents=0,
    )
    return plan


# ===========================================================================
# Corner: entities
# ===========================================================================
def test_create_plan_defaults(api):
    """PRD §3.1: "A plan may also specify an `alacarte_discount_pct`, the member's fractional
    discount on non-included services, which defaults to 0.0 and must lie between 0.0 and 0.5
    inclusive, and an `enrollment_fee_cents`, a one-time fee charged the first time a pet is
    enrolled on the plan, which defaults to 0 and must be zero or more."
    PRD §3.1: "A new plan begins life with `status` of `ACTIVE`".
    PRD §2.4: "an integer `version` that begins at 1 (or the server's initial value)".

    Design: Corner/entities/create_plan_returns_201_with_defaults
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.create_plan(
        create_plan_payload(tier="ESSENTIAL", name="Ess", monthly_fee_cents=2500,
                            annual_value_cents=30000),
        PLAN_ADMIN,
    )
    plan = validate_success(res, 201)
    assert plan["status"] == "ACTIVE"
    assert plan["alacarte_discount_pct"] == 0.0
    assert plan["enrollment_fee_cents"] == 0
    assert plan["version"] == 1


def test_get_plan_not_found(api):
    """PRD §2.6: "the system validates the identifiers left to right and rejects the request at
    the first identifier that does not resolve to an existing resource, returning `ERR_NOT_FOUND`."

    Design: Corner/entities/get_plan_not_found_returns_404
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.get_plan(NON_EXISTENT_UUID, PLAN_ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_membership_missing_plan_id(api):
    """PRD §3.2: "a `Member` creates a **Membership** by supplying the owning
    `member_account_id`, the chosen `plan_id`, and a `billing_anchor_day`".
    PRD §2.9: "the generic request-shape constraint (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_membership_missing_required_field_returns_422
    """
    set_clock("2026-01-01T00:00:00Z")
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account = create_member_account(clinic["id"])
    res = api.create_membership(
        {"member_account_id": account["id"], "billing_anchor_day": 1},
        make_member_headers(account["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_membership_anchor_day_out_of_range(api):
    """PRD §3.2: "a `billing_anchor_day` — the day of month on which the monthly fee is charged,
    which must be an integer from 1 to 28 inclusive."

    Design: Corner/entities/create_membership_anchor_day_out_of_range_returns_422
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_plan(tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000)
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account = create_member_account(clinic["id"])
    res = api.create_membership(
        create_membership_payload(account["id"], plan["id"], billing_anchor_day=31),
        make_member_headers(account["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_email_case_insensitive(api):
    """PRD §3.2: "E-mail uniqueness is enforced case-insensitively: an attempt to register an
    address that already exists, regardless of letter case, is rejected with
    `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/duplicate_member_email_returns_409
    """
    set_clock("2026-01-01T00:00:00Z")
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    create_member_account(clinic["id"], email="dup@x.com")
    res = api.create_member_account(
        {"email": "DUP@x.com", "full_name": "Second", "home_clinic_id": clinic["id"]},
        TEST_USERS["member_headers"],
    )
    validate_error(res, "ERR_DUPLICATE_EMAIL")


def test_membership_initial_state_and_snapshot(api):
    """PRD §3.2: "A new membership is created in `PENDING_PAYMENT` with no charge yet raised. At
    creation the system snapshots the plan's recurring fee into the membership's own
    `monthly_fee_cents` ... and sets `pet_count` to 0."

    Design: Corner/entities/membership_initial_state_pending_payment
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_plan(tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000)
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account = create_member_account(clinic["id"])
    res = api.create_membership(
        create_membership_payload(account["id"], plan["id"], billing_anchor_day=1),
        make_member_headers(account["id"]),
    )
    membership = validate_success(res, 201)
    assert membership["status"] == "PENDING_PAYMENT"
    assert membership["monthly_fee_cents"] == 4500
    assert membership["pet_count"] == 0


def test_create_membership_nonexistent_plan_reference(api):
    """PRD §2.6: "Foreign keys supplied in a request body — for instance `plan_id`, `clinic_id`,
    `enrolled_pet_id`, or `to_plan_id` — are checked separately: when a body references an entity
    that does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_membership_with_nonexistent_plan_returns_reference_not_found
    """
    set_clock("2026-01-01T00:00:00Z")
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account = create_member_account(clinic["id"])
    res = api.create_membership(
        create_membership_payload(account["id"], NON_EXISTENT_UUID, billing_anchor_day=1),
        make_member_headers(account["id"]),
    )
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


def test_list_plans_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_plans_pagination_envelope
    """
    set_clock("2026-01-01T00:00:00Z")
    create_plan(tier="ESSENTIAL", name="E", monthly_fee_cents=2500, annual_value_cents=30000)
    create_plan(tier="PLUS", name="P", monthly_fee_cents=4500, annual_value_cents=60000)
    data, meta = validate_paginated(api.list_plans(PLAN_ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_pet_enrolled_at_computed_from_clock(api):
    """PRD §3.3: "Adding a pet stamps the pet with an `enrolled_at` instant from the logical
    clock ... sets its `status` to `ENROLLED`, recomputes the owning membership's `pet_count`".

    Design: Corner/entities/enrolled_pet_computed_enrolled_at_ignores_client_input
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_plan(tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000)
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)

    assert pet["status"] == "ENROLLED"
    assert pet["enrolled_at"].startswith("2026-01-01T00:00:00"), (
        f"enrolled_at should be the clock instant, got {pet['enrolled_at']}"
    )
    assert get_membership(membership["id"])["pet_count"] == 1


def test_clock_default_before_any_set(api):
    """PRD §2.4: "At server startup the logical clock reads exactly `2026-01-01T00:00:00Z` and
    never falls back to wall-clock time; until it is explicitly moved it holds that default."

    Design: Corner/entities/clock_default_is_2026_01_01_before_any_set
    """
    res = api.get_clock(PLAN_ADMIN)
    clock = validate_success(res, 200)
    assert clock["current_utc"].startswith("2026-01-01T00:00:00"), (
        f"startup clock default must be 2026-01-01T00:00:00Z, got {clock['current_utc']}"
    )


# ===========================================================================
# Corner: endpoints
# ===========================================================================
def test_remove_last_pet_recomputes_count(api):
    """PRD §3.6: "Removal moves the pet to `REMOVED`, recomputes the owning membership's
    `pet_count`, and increments the membership's `version` by one."

    Design: Corner/endpoints/remove_last_pet_recomputes_pet_count
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])

    removed = validate_success(
        api.remove_pet(membership["id"], pet["id"], make_member_headers(account["id"])), 200
    )
    assert removed["status"] == "REMOVED"
    assert get_membership(membership["id"])["pet_count"] == 0


def test_term_credits_subresource_lists_buckets(api):
    """PRD §3.3: "Contract terms and their credit buckets are read-only to clients and are
    listed with optional filters ... the credit buckets of a term by `service_code` and `status`."
    PRD §3.4: "For each such line it creates one `ServiceCredit` bucket whose `granted_quantity`
    equals the line's `included_quantity`".

    Design: Corner/endpoints/contract_term_credits_subresource_lists_buckets
    """
    set_clock("2026-01-01T00:00:00Z")
    plan, _ = create_plan_with_services(
        [
            {"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000},
            {"service_code": "VACCINE", "included_quantity": 3, "unit_value_cents": 3500},
        ],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    term1 = first_active_term(membership["id"])

    data, meta = validate_paginated(
        api.list_term_credits(term1["id"], make_member_headers(account["id"]),
                              params={"service_code": "EXAM"})
    )
    assert meta["total_count"] == 1
    assert data[0]["granted_quantity"] == 2


def test_list_visits_filtered_by_membership(api):
    """PRD §3.5: "Visits are listed with optional filters on `membership_id`, `enrolled_pet_id`,
    `clinic_id`, `contract_term_id`, `service_code`, and `status`".

    Design: Corner/endpoints/list_visits_filtered_by_membership
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")

    data, meta = validate_paginated(
        api.list_visits(make_member_headers(account["id"]), params={"membership_id": membership["id"]})
    )
    assert meta["total_count"] == 1


# ===========================================================================
# Corner: rbac
# ===========================================================================
def test_member_cannot_create_plan(api):
    """PRD §2.1: "When a role is authenticated but is not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/member_cannot_create_plan_returns_forbidden_role
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.create_plan(
        create_plan_payload(tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000),
        make_member_headers(NON_EXISTENT_UUID),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_member_cannot_act_on_others_membership(api):
    """PRD §2.1: "a `Member` acting on a membership or account must own it — that is, the `id`
    of the `MemberAccount` that owns the resource must equal `X-User-ID` — and a violation is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/member_cannot_act_on_other_members_membership_returns_not_owner
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    acctA = create_member_account(clinic["id"])
    acctB, memB = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(memB["id"], acctB["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(memB["id"], acctB["id"])

    res = api.suspend_membership(memB["id"], make_member_headers(acctA["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_headers(api):
    """PRD §2.1: "If either header is missing or invalid, the request is rejected with
    `ERR_MISSING_AUTH_CONTEXT`."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    res = api.list_plans(headers={})
    validate_error(res, "ERR_MISSING_AUTH_CONTEXT")


# ===========================================================================
# Corner: cross_cutting_complexity_layers (OCC)
# ===========================================================================
def test_occ_correct_version_plan_change_succeeds(api):
    """PRD §2.8: "The plan-change operation requires a non-optional `expected_membership_version`
    field in its request body, carrying the `version` of the target `Membership` that the client
    last observed."
    PRD §3.6: "updates the membership's `plan_id` and re-snapshots its `monthly_fee_cents`, and
    increments the membership's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_plan_change_succeeds
    """
    set_clock("2026-01-01T00:00:00Z")
    plus, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20,
    )
    premium, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 4, "unit_value_cents": 6000}],
        tier="PREMIUM", name="Premium", monthly_fee_cents=9000, annual_value_cents=120000,
        alacarte_discount_pct=0.30,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plus["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    membership = activate_membership(membership["id"], account["id"])

    res = api.plan_change(
        membership["id"], plan_change_payload(premium["id"], membership["version"]),
        make_member_headers(account["id"]),
    )
    pcr = validate_success(res, 200)
    assert pcr["status"] == "APPLIED"
    assert get_membership(membership["id"])["plan_id"] == premium["id"]


def test_occ_stale_version_plan_change_rejected(api):
    """PRD §2.8: "When `expected_membership_version` does not equal the membership's current
    `version`, the plan-change is rejected with `ERR_STALE_MEMBERSHIP_VERSION` at HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_plan_change_returns_412
    """
    set_clock("2026-01-01T00:00:00Z")
    plus, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20,
    )
    premium, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 4, "unit_value_cents": 6000}],
        tier="PREMIUM", name="Premium", monthly_fee_cents=9000, annual_value_cents=120000,
        alacarte_discount_pct=0.30,
    )
    essential, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 1, "unit_value_cents": 6000}],
        tier="ESSENTIAL", name="Ess", monthly_fee_cents=2500, annual_value_cents=30000,
        alacarte_discount_pct=0.10,
    )
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plus["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    membership = activate_membership(membership["id"], account["id"])
    stale_version = membership["version"]
    # First change bumps version; the captured stale_version is now behind.
    validate_success(
        api.plan_change(membership["id"], plan_change_payload(premium["id"], stale_version),
                        make_member_headers(account["id"])),
        200,
    )

    res = api.plan_change(
        membership["id"], plan_change_payload(essential["id"], stale_version),
        make_member_headers(account["id"]),
    )
    validate_error(res, "ERR_STALE_MEMBERSHIP_VERSION")


# ===========================================================================
# Corner: consistency_model
# ===========================================================================
def test_activate_visible_in_same_response(api):
    """PRD §3.3: "activation moves the membership from `PENDING_PAYMENT` to `ENROLLED`".
    PRD §2.5: "the platform treats the membership as an aggregate root and reconciles its
    derived balances immediately after every mutating event."

    Design: Corner/consistency_model/activate_changes_visible_in_same_response
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)

    res = api.activate_membership(membership["id"], make_member_headers(account["id"]))
    activated = validate_success(res, 200)
    assert activated["status"] == "ENROLLED", "activate response body must already show ENROLLED"
    assert get_membership(membership["id"])["status"] == "ENROLLED"
