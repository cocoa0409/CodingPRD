"""Grant creation: defaults, required fields, enum constraints, computed fields,
and 404s (PRD §2.2, §2.4, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_grant,
    create_funder,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


class TestGrantCreation:
    def test_grant_creation_defaults_applied(self, api):
        """PRD §3.1: "Five optional knobs tune the reporting and compliance
        posture: `interim_report_due_days` (default 30), ... `final_report_due_days`
        (default 90), ... `variance_threshold_pct` (default 10.0), ...
        `renewal_window_days` (default 60), ... and `required_match_cents`
        (default 0)."
        PRD §3.1: "At creation the server snapshots `end_date` into
        `original_end_date`; the snapshot is never mutated, even when an approved
        extension later moves `end_date` forward."
        PRD §3.1: "A grant is born in `DRAFT` status with `total_expended_cents`
        equal to zero."

        Design: Corner/entities/grant_creation_defaults_applied
        """
        funder = create_funder(funder_type="STATE")
        resp = api.create_grant(
            {
                "funder_id": funder["id"],
                "award_number": "AW-D",
                "title": "T",
                "award_amount_cents": 500,
                "start_date": "2026-06-01",
                "end_date": "2027-05-31",
                "reporting_frequency": "ANNUAL",
            },
            OFFICER,
        )
        data = validate_success(resp, expected_status=201)
        assert_grant(data)
        assert data["variance_threshold_pct"] == pytest.approx(10.0)
        assert data["final_report_due_days"] == 90
        assert data["interim_report_due_days"] == 30
        assert data["renewal_window_days"] == 60
        assert data["required_match_cents"] == 0
        assert data["indirect_rate_pct"] == pytest.approx(0)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert data["original_end_date"][:10] == "2027-05-31"

    def test_grant_missing_required_field_returns_400(self, api):
        """PRD §3.1: "The creation payload carries the `funder_id` of the awarding
        funder, the funder-assigned `award_number`, a `title`, the total
        `award_amount_cents`, the `start_date` and `end_date` of the award period
        (dates at UTC midnight), and the `reporting_frequency`."
        PRD §5: `ERR_VALIDATION` (400) covers "missing required field, bad enum
        value, malformed date, non-positive amount, cross-grant reference".

        Design: Corner/entities/grant_missing_required_field_returns_400
        """
        funder = create_funder(funder_type="STATE")
        resp = api.create_grant(
            {
                "funder_id": funder["id"],
                "award_number": "AW-M",
                "title": "T",
                # award_amount_cents omitted
                "start_date": "2026-06-01",
                "end_date": "2027-05-31",
                "reporting_frequency": "ANNUAL",
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_grant_invalid_enum_returns_400(self, api):
        """PRD §3.1: "the `reporting_frequency` — one of `MONTHLY`, `QUARTERLY`,
        `SEMIANNUAL`, or `ANNUAL`."
        PRD §5: `ERR_VALIDATION` (400) covers "missing required field, bad enum
        value, malformed date, non-positive amount, cross-grant reference".

        Design: Corner/entities/grant_invalid_enum_returns_400
        """
        funder = create_funder(funder_type="STATE")
        resp = api.create_grant(
            {
                "funder_id": funder["id"],
                "award_number": "AW-E",
                "title": "T",
                "award_amount_cents": 500,
                "start_date": "2026-06-01",
                "end_date": "2027-05-31",
                "reporting_frequency": "WEEKLY",
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_grant_computed_total_expended_input_ignored(self, api):
        """PRD §3.1: "A grant is born in `DRAFT` status with `total_expended_cents`
        equal to zero."
        PRD §3.6: the summary exposes `total_expended_cents`, a value the server
        derives as "the sum over all active allocations on the grant" — it is
        server-computed, not client-supplied (§3.3: "the grant's
        `total_expended_cents` is recomputed as the sum over all active
        allocations on the grant").

        Design: Corner/entities/grant_computed_total_expended_input_ignored
        """
        funder = create_funder(funder_type="STATE")
        resp = api.create_grant(
            {
                "funder_id": funder["id"],
                "award_number": "AW-C",
                "title": "T",
                "award_amount_cents": 500,
                "start_date": "2026-06-01",
                "end_date": "2027-05-31",
                "reporting_frequency": "ANNUAL",
                "total_expended_cents": 999,
            },
            OFFICER,
        )
        data = validate_success(resp, expected_status=201)
        assert data["total_expended_cents"] == 0, (
            f"computed field must ignore client input 999, got "
            f"{data['total_expended_cents']}"
        )

    def test_grant_not_found_returns_404(self, api):
        """PRD §2.7: "if it does not exist, the request is rejected with
        `ERR_NOT_FOUND` (HTTP 404) before any identifier further to the right is
        examined."

        Design: Corner/entities/grant_not_found_returns_404
        """
        create_funder(funder_type="STATE")
        resp = api.get_grant(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
