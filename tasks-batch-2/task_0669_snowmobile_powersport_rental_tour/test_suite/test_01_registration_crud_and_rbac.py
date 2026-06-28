"""Entity creation, required fields, type constraints, not-found, duplicates,
listing, and RBAC (authn / role-denial / ownership). Corner sections: entities,
endpoints, rbac."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    NON_EXISTENT_UUID,
    create_trail, create_unit, create_departure, create_gear,
    register_member, register_signed_member,
    create_reservation, create_and_confirm_reservation,
    read_member, read_reservation,
    make_member_headers, assert_member,
)

DISPATCH = TEST_USERS["dispatch_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ===================================================================
# entities
# ===================================================================

def test_register_member_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly registered member begins with `waiver_status` of `UNSIGNED`,
    a null `waiver_signed_at`, `training_level` of `NONE`, a `deposit_hold_cents` of 0,
    and a `lifetime_damage_strikes` count of 0."
    PRD §3.1: "The `membership_tier` is one of `NONE`, `SEASON`, or `PREMIER` and
    defaults to `NONE` when omitted".

    Design: Corner/entities/create_member_returns_201_with_defaults
    """
    res = api.register_member(
        {"full_name": "New Rider", "email": "new-unique@example.com", "date_of_birth": "1990-01-01"}, ANON)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["waiver_status"] == "UNSIGNED"
    assert member["training_level"] == "NONE"
    assert member["membership_tier"] == "NONE"
    assert member["deposit_hold_cents"] == 0
    assert member["version"] == 1


def test_register_member_missing_email_returns_invalid_request(api):
    """PRD §3.1: "Registration supplies the rider's `full_name`, a contact `email`, and a
    `date_of_birth` given as an ISO 8601 calendar date in `YYYY-MM-DD` form".
    PRD §3.4 / §5: well-formedness failures map to `ERR_INVALID_REQUEST` (422).

    Design: Corner/entities/create_member_missing_email_returns_invalid_request
    """
    res = api.register_member({"full_name": "No Email", "date_of_birth": "1990-01-01"}, ANON)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_unit_invalid_class_enum_returns_invalid_request(api):
    """PRD §2.7: "the fixed ordering `TRAIL` below `UTILITY` below `MOUNTAIN`."
    PRD §5: a bad enum maps to `ERR_INVALID_REQUEST` (422).

    Design: Corner/entities/create_unit_invalid_class_enum_returns_invalid_request
    """
    res = api.create_unit(
        {"vin_tag": "BAD-1", "unit_class": "ROCKET", "daily_rate_cents": 5000,
         "deposit_cents": 25000, "tank_capacity_liters": 30}, DISPATCH)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_get_member_nonexistent_returns_not_found(api):
    """PRD §2.10: "the first identifier that does not resolve to an existing record
    causes the request to fail with `ERR_NOT_FOUND` before any later identifier or
    business rule is examined."

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, DISPATCH)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_confirm_recomputes_member_deposit_hold_computed_field(api):
    """PRD §3.4: "The member's `deposit_hold_cents` is at all times the sum of the active
    security-deposit holds across that member's reservations currently in the `HELD`
    billing state, recomputed every time a hold is placed or released."

    Design: Corner/entities/confirm_recomputes_member_deposit_hold_computed_field
    """
    trail = create_trail(name="CompT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-02-01T09:00:00Z",
                           ends_at="2027-02-01T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    member = register_signed_member()
    res = create_and_confirm_reservation(member, dep["id"], unit["id"], expected_version=dep["version"])
    assert read_member(member["id"])["deposit_hold_cents"] == 25000
    assert res["deposit_hold_cents"] == 25000


def test_create_reservation_gear_kind_mismatch_returns_invalid_request(api):
    """PRD §3.4: "The helmet slot must reference a `GearItem` whose `kind` is `HELMET`,
    and the suit slot must reference one whose `kind` is `SUIT`; a slot/kind mismatch is
    rejected with `ERR_GEAR_KIND_MISMATCH`."

    Design: Corner/entities/create_reservation_gear_kind_mismatch_returns_invalid_request
    """
    trail = create_trail(name="MisT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    suit = create_gear(kind="SUIT", size_code="L", replacement_cost_cents=20000)
    dep = create_departure(trail["id"], starts_at="2027-02-03T09:00:00Z",
                           ends_at="2027-02-03T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    member = register_member()
    res = api.create_reservation(
        {"member_id": member["id"], "tour_departure_id": dep["id"], "unit_id": unit["id"],
         "helmet_gear_id": suit["id"]}, make_member_headers(member["id"]))
    validate_error(res, "ERR_GEAR_KIND_MISMATCH", expected_status=422)


# ===================================================================
# endpoints — duplicate / listing
# ===================================================================

def test_duplicate_member_email_returns_duplicate(api):
    """PRD §3.1: "The `email` must be unique among members on a case-insensitive basis;
    a collision is rejected with `ERR_DUPLICATE`."

    Design: Corner/endpoints/duplicate_member_email_returns_duplicate
    """
    validate_success(api.register_member(
        {"full_name": "First", "email": "dup@example.com", "date_of_birth": "1990-01-01"}, ANON), 201)
    res = api.register_member(
        {"full_name": "Second", "email": "dup@example.com", "date_of_birth": "1991-01-01"}, ANON)
    validate_error(res, "ERR_DUPLICATE", expected_status=409)


def test_duplicate_settlement_on_returned_reservation_returns_invalid_state(api):
    """PRD §3.9: "On return the reservation moves from `CHECKED_OUT` to `RETURNED`".
    PRD §3.9: "Attempting any of these transitions from a state in which it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/duplicate_settlement_on_returned_reservation_returns_duplicate
    """
    from test_helpers import setup_checked_out_reservation, set_clock
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "DupS", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2027-03-03T09:00:00Z", "ends_at": "2027-03-03T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        depart_clock="2027-03-03T09:30:00Z")
    set_clock("2027-03-03T11:30:00Z")
    validate_success(api.return_reservation(bundle["reservation"]["id"], {"fuel_return_fraction": 1.0}, DISPATCH), 200)
    # Second return: reservation is no longer CHECKED_OUT, the state guard fires first.
    res = api.return_reservation(bundle["reservation"]["id"], {"fuel_return_fraction": 1.0}, DISPATCH)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert read_reservation(bundle["reservation"]["id"])["reservation_status"] == "RETURNED"


def test_list_member_reservations_paginated(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_member_reservations_paginated
    """
    trail = create_trail(name="ListT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-03-05T09:00:00Z",
                           ends_at="2027-03-05T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    member = register_member()
    create_reservation(member, dep["id"], unit["id"])
    data, meta = validate_paginated(
        api.list_member_reservations(member["id"], make_member_headers(member["id"])))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ===================================================================
# rbac
# ===================================================================

def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or carries a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    res = api.get_unit(unit["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_member_cannot_create_unit_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/member_cannot_create_unit_returns_unauthorized
    """
    member = register_member()
    res = api.create_unit(
        {"vin_tag": "RU-1", "unit_class": "TRAIL", "daily_rate_cents": 5000,
         "deposit_cents": 25000, "tank_capacity_liters": 30}, make_member_headers(member["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_member_cannot_confirm_other_members_reservation_returns_ownership_required(api):
    """PRD §2.1: "When an entity-backed `Member` attempts to confirm, cancel, or
    otherwise act on a reservation they do not own, the request is rejected with
    `ERR_OWNERSHIP_REQUIRED`."

    Design: Corner/rbac/member_cannot_confirm_other_members_reservation_returns_ownership_required
    """
    trail = create_trail(name="OwnT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-03-09T09:00:00Z",
                           ends_at="2027-03-09T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    mem_b = register_signed_member()
    res_b = create_reservation(mem_b, dep["id"], unit["id"])
    mem_a = register_member()  # a different member
    resp = api.confirm_reservation(res_b["id"], {"expected_tour_departure_version": dep["version"]},
                                   make_member_headers(mem_a["id"]))
    validate_error(resp, "ERR_OWNERSHIP_REQUIRED", expected_status=403)
    assert read_reservation(res_b["id"])["reservation_status"] == "PENDING"
