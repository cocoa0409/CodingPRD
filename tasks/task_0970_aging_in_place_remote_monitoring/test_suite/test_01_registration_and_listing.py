"""Registration validation, computed-field initialization, not-found, and
list pagination for seniors and plans."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_senior,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestSeniorRegistration:
    def test_senior_create_missing_required_full_name_returns_400(self, api):
        """PRD 3.1: "Registering a senior takes a `full_name`, a `date_of_birth`
        as an ISO calendar date, and the `address` where the kit will be
        installed; the new senior starts with `monitoring_posture` of
        `INACTIVE`, an `open_alert_count` of zero, and a `risk_tier` of
        `STANDARD`."
        PRD 2.9: "Next the request body is checked for well-formedness — every
        required field present, every type correct — with violations rejected
        as `ERR_INVALID_REQUEST`; when the offending content is an enum field
        carrying an undeclared member, the rejection is specifically
        `ERR_INVALID_ENUM`."

        Design: Corner/entities/senior_create_missing_required_full_name_returns_400
        """
        resp = api.create_senior(
            {"date_of_birth": "1940-01-01", "address": "1 X St"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        listed, meta = validate_paginated(api.list_seniors(ADMIN))
        assert listed == [], "no Senior row may be created by a rejected request"

    def test_plan_create_invalid_tier_enum_returns_400(self, api):
        """PRD 2.9: "Next the request body is checked for well-formedness —
        every required field present, every type correct — with violations
        rejected as `ERR_INVALID_REQUEST`; when the offending content is an
        enum field carrying an undeclared member, the rejection is specifically
        `ERR_INVALID_ENUM`."
        PRD 3.1: "A plan's `tier` is one of `ESSENTIAL`, `PLUS`, or `PREMIUM`,
        priced by `monthly_fee_cents` per 30-day cycle."

        Design: Corner/entities/plan_create_invalid_tier_enum_returns_400
        """
        payload = factories.create_subscription_plan_payload(
            tier="GOLD",
            monthly_fee_cents=1000,
            included_motion_sensors=1,
            extra_sensor_fee_cents=99,
            max_contacts=3,
            checkin_interval_hours=72,
            medication_reminders_enabled=False,
            wellness_report_enabled=False,
            wellness_report_cadence="NONE",
        )
        resp = api.create_subscription_plan(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)

    def test_senior_create_computed_fields_initialized_by_server(self, api):
        """PRD 3.1: "Registering a senior takes a `full_name`, a `date_of_birth`
        as an ISO calendar date, and the `address` where the kit will be
        installed; the new senior starts with `monitoring_posture` of
        `INACTIVE`, an `open_alert_count` of zero, and a `risk_tier` of
        `STANDARD`."
        PRD 2.6: "All three fields are maintained by the system and are never
        set directly by clients."

        Design: Corner/entities/senior_create_computed_field_input_ignored
        """
        payload = factories.create_senior_payload(
            full_name="Cmp Senior",
            date_of_birth="1940-01-01",
            address="1 C St",
            open_alert_count=99,
        )
        data = validate_success(api.create_senior(payload, ADMIN), 201)
        assert data["open_alert_count"] == 0, (
            f"open_alert_count must initialize to 0, got {data['open_alert_count']}"
        )
        assert data["monitoring_posture"] == "INACTIVE"
        assert data["risk_tier"] == "STANDARD"


class TestSeniorLookupAndListing:
    def test_get_nonexistent_senior_returns_not_found(self, api):
        """PRD 2.9: "Only after the body parses does the system resolve
        identifiers: path-template identifiers are validated strictly left to
        right, so a request naming two resources fails with `ERR_NOT_FOUND` for
        the first unresolvable id in the path, and only once the path fully
        resolves are foreign keys inside the body checked, also under
        `ERR_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_senior_returns_not_found
        """
        resp = api.get_senior("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_seniors_list_pagination_limit_and_has_more(self, api):
        """PRD 2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items from the front of the result
        set and defaults to 0. Unless otherwise specified, every list endpoint
        returns resources sorted by `created_at` in ascending order. Paginated
        list responses carry `limit`, `offset`, `total_count`, and `has_more`
        in the `meta` object of the envelope."

        Design: Corner/entities/seniors_list_pagination_limit_and_has_more
        """
        created = [
            create_senior(full_name=f"Pg {name}", address=f"{i} Pg St")
            for i, name in enumerate(["One", "Two", "Three"], start=1)
        ]
        page1, meta1 = validate_paginated(
            api.list_seniors(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_seniors(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False

        page1_ids = {row["id"] for row in page1}
        page2_ids = {row["id"] for row in page2}
        assert page1_ids.isdisjoint(page2_ids), "pages must be disjoint"
        assert page1_ids | page2_ids == {s["id"] for s in created}
        created_ats = [row["created_at"] for row in page1 + page2]
        assert created_ats == sorted(created_ats), (
            "pages must be ordered by created_at ascending"
        )
