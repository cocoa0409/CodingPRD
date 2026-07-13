"""Tree inventory, protected classification, and zone canopy accounting."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    create_tree_payload, create_contractor_payload,
    new_zone, new_species, setup_zone_species, setup_tree,
    TEST_USERS,
)

STAFF = TEST_USERS["forestry_staff_headers"]
ADMIN = TEST_USERS["forestry_admin_headers"]


def test_get_nonexistent_tree_returns_not_found(api):
    """PRD §2.5: "then existence of every resource named by a path segment (a
    `ERR_<RESOURCE>_NOT_FOUND` at 404)."

    Design: Corner/entities/get_tree_not_found
    """
    res = api.get_tree(NON_EXISTENT_UUID, STAFF)
    validate_error(res, "ERR_TREE_NOT_FOUND", expected_status=404)


def test_tree_create_missing_dbh_rejected(api):
    """PRD §2.5: "the request body is validated for shape — required fields present and
    correctly typed (`ERR_INVALID_REQUEST`, 400) — followed by enum validity, where any
    enum-valued field carrying a value outside its declared set is rejected with
    `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/tree_create_missing_required_dbh_returns_invalid_request
    """
    zone, species = setup_zone_species()
    payload = create_tree_payload(zone["id"], species["id"])
    del payload["dbh_inches"]
    res = api.create_tree(payload, STAFF)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_tree_create_invalid_condition_class_enum_rejected(api):
    """PRD §2.5: "followed by enum validity, where any enum-valued field carrying a value
    outside its declared set is rejected with `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/tree_create_invalid_enum_condition_class
    """
    zone, species = setup_zone_species()
    payload = create_tree_payload(zone["id"], species["id"], dbh_inches=12.0,
                                  condition_class="EXCELLENT")
    res = api.create_tree(payload, STAFF)
    validate_error(res, "ERR_INVALID_ENUM", expected_status=422)


def test_tree_create_unknown_zone_fk_rejected(api):
    """PRD §2.5: "Foreign keys carried in the body are then resolved (`zone_id`,
    `species_id`, `tree_id`, `permit_id`, `contractor_id`, `affected_zone_id`,
    `work_order_id`), and an unresolved reference yields the matching not-found error at
    404."

    Design: Corner/entities/tree_create_bad_zone_returns_404
    """
    species = new_species()
    payload = create_tree_payload(NON_EXISTENT_UUID, species["id"], dbh_inches=12.0)
    res = api.create_tree(payload, STAFF)
    validate_error(res, "ERR_ZONE_NOT_FOUND", expected_status=404)


def test_zone_create_mints_system_fields(api):
    """PRD §2.4: "Every resource has an `id`, a server-minted UUID with no type prefix,
    and a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits
    recording when the resource was first created."

    Design: Corner/entities/zone_system_fields_generated
    """
    from test_helpers import create_zone_payload, is_valid_uuid, is_iso8601_timestamp
    res = api.create_zone(create_zone_payload(name="Z1"), ADMIN)
    zone = validate_success(res, 201)
    assert is_valid_uuid(zone["id"]), f"id must be a server-minted UUID, got {zone.get('id')!r}"
    assert is_iso8601_timestamp(zone["created_at"]), "created_at must be an ISO 8601 instant"
    assert isinstance(zone["version"], int), "version must be a server-managed integer"


def test_contractor_status_defaults_active(api):
    """PRD §3.1: "Status may be set at registration and defaults to `ACTIVE`, so system
    initialization is permitted to produce a `SUSPENDED` contractor."

    Design: Corner/entities/contractor_status_defaults_active
    """
    payload = create_contractor_payload(name="Acme", license_number="L-9")
    payload.pop("status", None)
    res = api.create_contractor(payload, ADMIN)
    contractor = validate_success(res, 201)
    assert contractor["status"] == "ACTIVE", "omitted status must default to ACTIVE"


def test_zone_canopy_recomputed_when_tree_added(api):
    """PRD §2.9: "From that, `current_canopy_pct` is `live_canopy_sqm` divided by the
    zone's `area_sqm`, multiplied by 100, and rounded half-up to two decimal places."
    PRD §2.9: "The `canopy_status` is `MEETS` when `current_canopy_pct` is greater than or
    equal to the zone's `target_canopy_pct`, and `DEFICIT` otherwise (the boundary at
    exactly the target counts as `MEETS`)."

    Design: Corner/entities/zone_canopy_recomputed_on_tree_create
    """
    zone, species, tree = setup_tree(dbh=12.0,
                                     zone_overrides={"target_canopy_pct": 30.0, "area_sqm": 100},
                                     species_overrides={"mature_canopy_sqm": 50.0})
    fetched = validate_success(api.get_zone(zone["id"], ADMIN), 200)
    assert fetched["current_canopy_pct"] == pytest.approx(50.00, abs=0.005)
    assert fetched["canopy_status"] == "MEETS"


def test_zone_canopy_pct_rounds_to_two_decimals(api):
    """PRD §2.9: "From that, `current_canopy_pct` is `live_canopy_sqm` divided by the
    zone's `area_sqm`, multiplied by 100, and rounded half-up to two decimal places."

    Design: Corner/entities/zone_canopy_pct_two_decimal_precision
    """
    zone, species, tree = setup_tree(dbh=12.0,
                                     zone_overrides={"name": "Z2", "target_canopy_pct": 10.0,
                                                     "area_sqm": 300},
                                     species_overrides={"mature_canopy_sqm": 50.0})
    fetched = validate_success(api.get_zone(zone["id"], ADMIN), 200)
    # 50 / 300 * 100 = 16.666.. -> 16.67 half-up to two decimals.
    assert fetched["current_canopy_pct"] == pytest.approx(16.67, abs=0.001)


def test_list_trees_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to
    10 when omitted, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_trees_pagination_envelope
    """
    zone, species = setup_zone_species(zone_overrides={"area_sqm": 1000})
    from test_helpers import new_tree
    new_tree(zone["id"], species["id"], dbh_inches=12.0)
    new_tree(zone["id"], species["id"], dbh_inches=14.0, condition_class="FAIR")
    res = api.list_trees(STAFF, params={"zone_id": zone["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_protected_flag_inclusive_at_eight_inches(api):
    """PRD §3.2: "a tree is protected when its `dbh_inches` is at least 8.0 inches, or when
    its species has `is_protected_species` set to true. The 8.0-inch boundary is inclusive
    — a tree measured at exactly 8.0 inches is protected."

    Design: Difficulty/boundary_precision_check/protected_dbh_threshold_inclusive_at_eight
    """
    zone, species = setup_zone_species(species_overrides={"is_protected_species": False})
    res = api.create_tree(
        create_tree_payload(zone["id"], species["id"], dbh_inches=8.0, canopy_radius_m=4.0),
        STAFF)
    tree = validate_success(res, 201)
    assert tree["is_protected"] is True, "dbh exactly 8.0 must be protected (inclusive boundary)"


def test_protected_flag_false_below_eight_inches(api):
    """PRD §3.2: "a tree is protected when its `dbh_inches` is at least 8.0 inches, or when
    its species has `is_protected_species` set to true. The 8.0-inch boundary is inclusive
    — a tree measured at exactly 8.0 inches is protected."

    Design: Difficulty/boundary_precision_check/protected_dbh_threshold_inclusive_at_eight
    """
    zone, species = setup_zone_species(species_overrides={"is_protected_species": False})
    res = api.create_tree(
        create_tree_payload(zone["id"], species["id"], dbh_inches=7.5, canopy_radius_m=4.0),
        STAFF)
    tree = validate_success(res, 201)
    assert tree["is_protected"] is False, "dbh 7.5 (< 8.0) on a non-protected species is not protected"
