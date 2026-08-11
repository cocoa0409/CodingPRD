"""Unit configuration defaults, pagination envelope, registry uniqueness, role gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_unit,
    create_personnel_payload,
    create_unit_payload,
    get_unit,
    make_requester_headers,
    new_personnel,
    new_unit,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


class TestUnitConfigAndRegistry:
    def test_unit_creation_applies_config_defaults(self, api):
        """PRD §3.1: "Four temporary-change limits and one training gate may be
        supplied at creation or left to their defaults: `temp_moc_max_days` (the
        maximum initial duration of a temporary MOC, 180 days by default),
        `max_extensions` (the maximum number of approved extensions per temporary
        MOC, 2 by default), `extension_max_days` (the maximum size of a single
        extension request, 90 days by default), `total_temp_cap_days` (a hard
        lifetime cap — a temporary MOC's end date may never pass its start date
        by more than this, 360 days by default), and
        `training_coverage_threshold_pct` (the minimum training coverage required
        before implementation can be declared, 100.00 by default)."
        PRD §3.1: "A freshly created unit starts with `psm_posture` `NORMAL`, an
        `open_action_count` and `overdue_action_count` of zero, and a
        `process_safety_index` of zero."

        Design: Corner/entities/unit_creation_applies_config_defaults
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=36)
        assert_unit(unit)
        unit = get_unit(unit["id"])
        assert unit["temp_moc_max_days"] == 180
        assert unit["max_extensions"] == 2
        assert unit["extension_max_days"] == 90
        assert unit["total_temp_cap_days"] == 360
        assert unit["training_coverage_threshold_pct"] == pytest.approx(100.00, abs=0.001)
        assert unit["psm_posture"] == "NORMAL"
        assert unit["open_action_count"] == 0
        assert unit["overdue_action_count"] == 0
        assert unit["process_safety_index"] == 0
        assert unit["version"] == 1

    def test_unit_listing_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/unit_listing_pagination_envelope
        """
        for i in range(1, 4):
            new_unit(name=f"U{i}", unit_code=f"U{i}", pha_cycle_months=12 * i)

        page1, meta1 = validate_paginated(api.list_units(MANAGER, params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3, f"Expected total_count 3, got {meta1['total_count']}"
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(api.list_units(MANAGER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1, f"Expected 1 row on second page, got {len(page2)}"
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 3

    def test_personnel_invalid_qualification_enum_returns_invalid_request(self, api):
        """PRD §2.9: "any request that is malformed — a missing required field, a
        value of the wrong type, an unknown enum value, or an invalid date — is
        rejected with `ERR_INVALID_REQUEST`."
        PRD §3.1: "a `qualifications` list (defaulting to empty) drawn from
        `MECHANICAL`, `CHEMICAL`, `ELECTRICAL`, `PROCESS`, `HAZOP_LEADER`, and
        `PSSR_CERTIFIED`" — WIZARD is not a member of that closed set.

        Design: Corner/entities/personnel_invalid_qualification_enum_returns_invalid_request
        """
        resp = api.create_personnel(
            create_personnel_payload(full_name="X", employee_ref="E-X", qualifications=["WIZARD"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_uniqueness_unit_code_and_employee_ref(self, api):
        """PRD §3.1: "a `unit_code` that must be unique across all units
        (`ERR_UNIT_CODE_EXISTS` on collision)"
        PRD §3.1: "an `employee_ref` unique across all personnel
        (`ERR_EMPLOYEE_REF_EXISTS`)"

        Design: Corner/validations/uniqueness_unit_code_and_employee_ref
        """
        new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        new_personnel("Req", "E-REQ")

        dup_unit = api.create_unit(create_unit_payload(name="U-bis", unit_code="U1", pha_cycle_months=24), ADMIN)
        validate_error(dup_unit, ApiErrorId.ERR_UNIT_CODE_EXISTS.value)

        dup_person = api.create_personnel(create_personnel_payload(full_name="Other", employee_ref="E-REQ"), ADMIN)
        validate_error(dup_person, ApiErrorId.ERR_EMPLOYEE_REF_EXISTS.value)

    def test_unit_create_forbidden_for_requester_role(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /psm/units is authorized for PsmAdmin only.

        Design: Corner/validations/unit_create_forbidden_for_requester_role
        """
        req = new_personnel("Req", "E-REQ")
        resp = api.create_unit(
            create_unit_payload(name="U", unit_code="U1", pha_cycle_months=12),
            make_requester_headers(req["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
        # No unit was created.
        _, meta = validate_paginated(api.list_units(MANAGER))
        assert meta["total_count"] == 0
