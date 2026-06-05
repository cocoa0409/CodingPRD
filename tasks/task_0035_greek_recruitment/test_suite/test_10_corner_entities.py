"""Corner — entities section.

Per-entity claims of creation, computed-field derivation, not-found, and
input-range validation.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_chapter,
    create_chapter_payload,
    register_pnm_payload,
    set_clock,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
)


class TestChapterCreationInitialComputedFields:
    """A freshly created Chapter has all computed fields at their zero-input
    baseline per PRD §3.1."""

    def test_create_chapter_returns_201_with_zero_initialized_counters(
        self, api, panhellenic_admin_headers
    ):
        """PRD §3.1: "On creation, `risk_status` is `GOOD_STANDING`, `risk_points` is 0, `pledged_count` is 0, and `legacy_pledged_count` is 0."
        PRD §2.4: "Every resource also carries a `created_at` timestamp set at insertion. With one exception — `DuesLedgerEntry` — every resource additionally carries an `updated_at` timestamp refreshed on every mutation and a `version` integer initialized to 1 and incremented by exactly 1 on every mutation that changes the row."

        Design: Corner/entities/corner_chapter_create_success_returns_201_with_initial_computed_fields
        """
        payload = create_chapter_payload(
            name="Omega-1",
            greek_type="FRATERNITY",
            quota_total=4,
            dues_per_member_cents=12345,
            legacy_priority_slots=2,
        )
        res = api.create_chapter(payload, panhellenic_admin_headers)
        chapter = validate_success(res, 201)
        assert chapter["risk_status"] == "GOOD_STANDING"
        assert chapter["risk_points"] == 0
        assert chapter["pledged_count"] == 0
        assert chapter["legacy_pledged_count"] == 0
        assert chapter["version"] == 1
        assert chapter["dues_per_member_cents"] == 12345


class TestPnmIsLegacyComputedFromLegacyChapterId:
    """is_legacy is the computed convenience flag: true iff legacy_chapter_id
    is non-null."""

    def test_legacy_pnm_has_is_legacy_true(self, api, panhellenic_admin_headers):
        """PRD §3.1: "the `is_legacy` flag is set to true if and only if `legacy_chapter_id` is non-null, and is otherwise false."

        Design: Corner/entities/corner_pnm_is_legacy_computed_from_legacy_chapter_id
        """
        host = create_chapter(
            name="LegacyHost",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=1,
        )
        res = api.register_pnm(
            register_pnm_payload(
                full_name="LegacyPnm", gpa=3.20, legacy_chapter_id=host["id"]
            ),
            TEST_USERS["anonymous_headers"],
        )
        pnm = validate_success(res, 201)
        assert pnm["is_legacy"] is True
        assert pnm["legacy_chapter_id"] == host["id"]

    def test_non_legacy_pnm_has_is_legacy_false_with_null_legacy_chapter_id(
        self, api
    ):
        """PRD §3.1: "the `is_legacy` flag is set to true if and only if `legacy_chapter_id` is non-null, and is otherwise false."

        Design: Corner/entities/corner_pnm_is_legacy_computed_from_legacy_chapter_id
        """
        res = api.register_pnm(
            register_pnm_payload(full_name="PlainPnm", gpa=3.20),
            TEST_USERS["anonymous_headers"],
        )
        pnm = validate_success(res, 201)
        assert pnm["is_legacy"] is False
        assert pnm.get("legacy_chapter_id") is None


class TestChapterGetNotFound:
    """GET against a non-existent UUID returns 404 ERR_RESOURCE_NOT_FOUND."""

    def test_get_nonexistent_chapter_returns_resource_not_found(
        self, api, panhellenic_admin_headers
    ):
        """PRD §2.6: "Path parameters are validated left-to-right: the outermost id is resolved first and, if it does not exist, returns `ERR_RESOURCE_NOT_FOUND` (HTTP 404) before the inner id is even inspected."

        Design: Corner/entities/corner_chapter_get_not_found
        """
        res = api.get_chapter(NON_EXISTENT_UUID, panhellenic_admin_headers)
        validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


class TestPnmRegisterInvalidGpaReturnsInvalidRequest:
    """gpa=5.50 violates the 0.00..4.00 range — priority 16 catches it as
    ERR_INVALID_REQUEST."""

    def test_register_pnm_with_out_of_range_gpa_returns_invalid_request(self, api):
        """PRD §3.1: "a cumulative `gpa` expressed to two decimal places between 0.00 and 4.00 inclusive"
        PRD §2.7: "and finally generic body shape (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/corner_pnm_register_invalid_gpa_returns_invalid_request
        """
        res = api.register_pnm(
            register_pnm_payload(full_name="BadGpa", gpa=5.50),
            TEST_USERS["anonymous_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
