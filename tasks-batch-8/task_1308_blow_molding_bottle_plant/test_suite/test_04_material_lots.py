"""Material lot inventory: pagination, release/hold cycle, shape and uniqueness violations, and RBAC denial on QC release."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_version_incremented,
    create_lot, create_material_lot_payload,
    api_client, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["plant_admin"]
TECH = TEST_USERS["quality_technician"]
SCHEDULER = TEST_USERS["production_scheduler"]


class TestMaterialLotPagination:
    def test_material_lot_list_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Every list response orders its rows by `created_at` ascending". "Paginated list responses expose `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

Design: Corner/entities/material_lot_list_pagination"""
        for code in ("R-1", "R-2", "R-3"):
            create_lot(lot_code=code, received_kg=100)

        page1, meta1 = validate_paginated(
            api.list_material_lots(TECH, params={"limit": 2, "offset": 0}))
        assert [lot["lot_code"] for lot in page1] == ["R-1", "R-2"]
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_material_lots(TECH, params={"limit": 2, "offset": 2}))
        assert [lot["lot_code"] for lot in page2] == ["R-3"]
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestMaterialLotCycle:
    def test_release_hold_release_cycle(self, api):
        """PRD §3.4: "Releasing moves a `QUARANTINED` lot to `RELEASED`; holding moves a `RELEASED` or `IN_USE` lot back to `QUARANTINED`".
PRD §2.5: "The `version` is an integer that increments by one on every mutation of the resource".

Design: Corner/state_machines/material_lot_release_hold_release_cycle"""
        lot = create_lot(lot_code="R-1", received_kg=100)
        assert lot["status"] == "QUARANTINED"

        released = validate_success(api.release_material_lot(lot["id"], TECH), 200)
        assert released["status"] == "RELEASED"
        assert_version_incremented(released["version"], lot["version"])

        held = validate_success(api.hold_material_lot(lot["id"], TECH), 200)
        assert held["status"] == "QUARANTINED"
        assert_version_incremented(held["version"], released["version"])

        released2 = validate_success(api.release_material_lot(lot["id"], TECH), 200)
        assert released2["status"] == "RELEASED"
        assert_version_incremented(released2["version"], held["version"])


class TestMaterialLotViolations:
    def test_invalid_enum_material_type_rejected(self, api):
        """PRD §3.4: "Each lot declares a `material_type` of `RESIN` or `COLORANT`". PRD §2.9: "every enum value inside its declared set, numeric fields non-negative" — "violations are `ERR_INVALID_REQUEST` (HTTP 400)".

Design: Corner/validations/invalid_enum_material_type_returns_invalid_request"""
        res = api.create_material_lot(
            create_material_lot_payload(material_type="WAX", lot_code="R-9"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_lot_code_rejected(self, api):
        """PRD §3.4: "Every lot has a globally unique `lot_code`". The catalogue's uniqueness error follows the convention PRD §3.1/§3.2 establish for code collisions: "a collision is refused with `ERR_DUPLICATE_CODE`" and "uniqueness violations are again `ERR_DUPLICATE_CODE`".

Design: Corner/validations/duplicate_lot_code_rejected"""
        create_lot(lot_code="R-1", received_kg=100)
        res = api.create_material_lot(
            create_material_lot_payload(
                lot_code="R-1", resin_type="HDPE", received_kg=50),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CODE)


class TestMaterialLotRbac:
    def test_scheduler_cannot_release_material_lot(self, api):
        """PRD §2.1: "Each endpoint admits a specific set of roles (enumerated in §4); a caller whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." §4 lists only QualityTechnician for POST /plant/material-lots/{id}/release.

Design: Corner/rbac/scheduler_cannot_release_material_lot"""
        lot = create_lot(lot_code="R-1", received_kg=100)
        res = api.release_material_lot(lot["id"], SCHEDULER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
