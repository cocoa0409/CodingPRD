"""Decal issuance: the vehicle-active eligibility gate, the optimistic-concurrency
version check, and the supersede-prior-decal side effect.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_vehicle, issue_decal, setup_community_and_resident,
    ADMIN,
)


class TestDecalRequiresActiveVehicle:
    """Tests for the decal_issue_depends_on_vehicle_state rule (see per-test Design tags)."""

    def _inactive_vehicle(self, api):
        _, resident = setup_community_and_resident(resident_overrides={"full_name": "Ivan Inactive"})
        vehicle = create_vehicle(resident["id"], plate="OLD999", plate_state="CA")
        inactive = validate_success(api.transition_vehicle(vehicle["id"], {"to_status": "INACTIVE"}, ADMIN))
        return vehicle, inactive["version"]

    def test_issue_decal_on_inactive_vehicle_returns_vehicle_inactive(self, api):
        """PRD §3.2: "Issuance requires the target vehicle to be `ACTIVE`; issuing
        against an `INACTIVE` vehicle is refused with `ERR_VEHICLE_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/decal_issue_depends_on_vehicle_state
        """
        vehicle, version = self._inactive_vehicle(api)
        resp = api.create_decal(
            {"vehicle_id": vehicle["id"], "tier": "RESIDENT",
             "valid_from": "2026-05-01T00:00:00Z", "valid_until": "2027-05-01T00:00:00Z",
             "expected_vehicle_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_INACTIVE.value)

    def test_vehicle_inactive_gate_is_http_409(self, api):
        """PRD §3.2: "Issuance requires the target vehicle to be `ACTIVE`; issuing
        against an `INACTIVE` vehicle is refused with `ERR_VEHICLE_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/decal_issue_depends_on_vehicle_state
        """
        vehicle, version = self._inactive_vehicle(api)
        resp = api.create_decal(
            {"vehicle_id": vehicle["id"], "tier": "RESIDENT",
             "valid_from": "2026-05-01T00:00:00Z", "valid_until": "2027-05-01T00:00:00Z",
             "expected_vehicle_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_INACTIVE.value, expected_status=409)


def test_decal_issue_stale_vehicle_version_returns_412(api):
    """PRD §2.6: "When the server processes the request, it compares
    `expected_vehicle_version` against the vehicle's current `version`. If another
    writer has already issued a decal for that vehicle — which supersedes the old
    decal and increments the vehicle's `version` — then a request built from the
    earlier view carries a stale value that no longer matches, and it is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/decal_issue_stale_vehicle_version_returns_412
    """
    _, resident = setup_community_and_resident(resident_overrides={"full_name": "Occ Owen"})
    vehicle = create_vehicle(resident["id"], plate="OCC001", plate_state="CA")
    v0 = vehicle["version"]
    issue_decal(vehicle["id"], v0, tier="RESIDENT")  # bumps vehicle version past v0
    resp = api.create_decal(
        {"vehicle_id": vehicle["id"], "tier": "TEMPORARY",
         "valid_from": "2026-05-01T00:00:00Z", "valid_until": "2027-05-01T00:00:00Z",
         "expected_vehicle_version": v0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_decal_issue_supersedes_prior_active_decal(api):
    """PRD §3.2: "On success the system mints a `decal_number`, sets the decal's
    `status` to `ACTIVE`, revokes the vehicle's prior `ACTIVE` decal (if one
    exists) to `REVOKED` as a supersede, and increments the vehicle's `version`
    by one."

    Design: Corner/cross_cutting/decal_issue_supersedes_prior_active_decal
    """
    _, resident = setup_community_and_resident(resident_overrides={"full_name": "Sue Supersede"})
    vehicle = create_vehicle(resident["id"], plate="SUP001", plate_state="CA")
    decal1 = issue_decal(vehicle["id"], vehicle["version"], tier="RESIDENT")
    veh_now = validate_success(api.get_vehicle(vehicle["id"], ADMIN))
    decal2 = validate_success(api.create_decal(
        {"vehicle_id": vehicle["id"], "tier": "TENANT",
         "valid_from": "2026-05-01T00:00:00Z", "valid_until": "2027-05-01T00:00:00Z",
         "expected_vehicle_version": veh_now["version"]}, ADMIN), expected_status=201)
    assert decal2["status"] == "ACTIVE"
    d1 = validate_success(api.get_decal(decal1["id"], ADMIN))
    assert d1["status"] == "REVOKED"
