"""List pagination envelope and path-parameter resolution order."""
import pytest

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_float_nurse,
    create_nurse,
    setup_unit_with_shift,
    validate_error,
    validate_paginated,
)


class TestPagination:

    def test_pagination_envelope_on_nurses_list(self):
        """PRD section 2.3: "The `limit` parameter specifies the maximum number
        of items to return: it defaults to 10 when omitted, and accepts values
        from a minimum of 1 to a maximum of 100. The `offset` parameter
        specifies how many items to skip and defaults to 0."
        PRD section 2.3: "List responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/pagination_envelope_on_nurses_list
        """
        for name in ("Page One", "Page Two", "Page Three"):
            create_float_nurse(full_name=name, competencies=["ICU"])

        page1, meta1 = validate_paginated(
            api_client.list_nurses(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api_client.list_nurses(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestPathResolution:

    def test_not_found_left_to_right(self):
        """PRD section 2.5: "Resource identifiers in the URL path are resolved
        left to right; the first identifier that does not correspond to an
        existing resource yields its specific not-found error —
        `ERR_UNIT_NOT_FOUND`, `ERR_NURSE_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`,
        `ERR_OFFER_NOT_FOUND`, `ERR_FLOAT_REQUEST_NOT_FOUND`,
        `ERR_SITTER_REQUEST_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND` — and no
        later check runs."

        Design: Corner/validations/not_found_left_to_right
        """
        sc = setup_unit_with_shift(name="ICU V1", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Real Ruth", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        # The shiftId path segment does not exist; the body references a real
        # nurse, but path existence is validated before the payload matters.
        resp = api_client.create_assignment(
            NON_EXISTENT_UUID,
            {"nurse_id": nurse["id"],
             "expected_shift_version": sc["shift"]["version"]},
            sc["charge_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_FOUND)
        assert resp.status_code == 404
