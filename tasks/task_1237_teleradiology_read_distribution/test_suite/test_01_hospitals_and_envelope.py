"""Hospital entity defaults, common system fields, and list envelope."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_hospital,
    assert_study,
    create_hospital_payload,
    create_study_payload,
    get_success_data,
    make_hospital_user_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]


class TestHospitalDefaults:
    def test_hospital_create_applies_documented_defaults(self, api):
        """PRD section 3.1: "Each hospital also carries a `credentialing_mode` —
        `BY_PROXY` (the default) or `INDEPENDENT` — declaring which style of
        credential grant it accepts for reader privileges, and a `pricing_mode` —
        `MARGINAL` (the default) or `FLAT_TIER` — selecting the volume-pricing
        variant used on its invoices."

        Design: Corner/entities/hospital_create_defaults_applied
        """
        resp = api.create_hospital(
            create_hospital_payload(name="Defaults Hosp", state_code="WA"), ADMIN)
        data = validate_success(resp, 201)
        assert_hospital(data)
        assert data["status"] == "ONBOARDING"
        assert data["pricing_mode"] == "MARGINAL"
        assert data["credentialing_mode"] == "BY_PROXY"

    def test_hospital_create_applies_tat_and_penalty_defaults(self, api):
        """PRD section 3.1: "The `tat_stat_minutes`, `tat_urgent_minutes`, and
        `tat_routine_minutes` fields hold the turnaround targets for `STAT`,
        `URGENT`, and `ROUTINE` studies respectively, defaulting to 60, 240, and
        1440 minutes. The `penalty_per_breach_minute_cents` field (default 50)
        prices each whole minute of lateness, and `breach_penalty_cap_cents`
        (default 20000) caps the per-study penalty credit."

        Design: Corner/entities/hospital_create_defaults_applied
        """
        resp = api.create_hospital(
            create_hospital_payload(name="Defaults Hosp 2", state_code="WA"), ADMIN)
        data = validate_success(resp, 201)
        assert data["tat_stat_minutes"] == 60
        assert data["tat_urgent_minutes"] == 240
        assert data["tat_routine_minutes"] == 1440
        assert data["penalty_per_breach_minute_cents"] == 50
        assert data["breach_penalty_cap_cents"] == 20000
        assert data["version"] == 1


class TestHospitalVersioning:
    def test_hospital_version_increments_by_one_per_mutation(self, api):
        """PRD section 2.4: "`version` (integer): a system-managed integer that
        increments by exactly 1 on every mutation of the resource, including
        mutations caused by cascades and clock sweeps."
        PRD section 3.1: "Activation by a `PlatformAdmin` moves `ONBOARDING →
        ACTIVE`, and the same activation also rehabilitates a suspended hospital
        (`SUSPENDED → ACTIVE`); both increment the hospital's `version` by 1 and
        refresh `updated_at`."

        Design: Corner/entities/hospital_version_increments_on_mutation
        """
        hosp = validate_success(api.create_hospital(
            create_hospital_payload(name="Hosp Ver", state_code="CA"), ADMIN), 201)
        assert hosp["version"] == 1
        v1 = validate_success(api.activate_hospital(hosp["id"], ADMIN), 200)
        assert v1["version"] == 2
        # Advance the logical clock so the refresh of updated_at on the next
        # mutation is observable (all timestamps derive from the logical clock,
        # PRD section 2.5; under a frozen clock a refresh re-stamps the same
        # value).
        set_clock("2026-05-01T01:00:00Z")
        v2 = validate_success(api.suspend_hospital(hosp["id"], ADMIN), 200)
        assert v2["version"] == 3
        assert v2["status"] == "SUSPENDED"
        assert v2["updated_at"] != hosp["created_at"]


class TestStudyListPagination:
    def test_study_list_pagination_envelope(self, api):
        """PRD section 2.3: "The `limit` parameter sets the maximum number of
        items returned; it defaults to 10, with a minimum of 1 and a maximum of
        100. The `offset` parameter sets the number of items skipped and defaults
        to 0." and "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/study_list_pagination_envelope
        """
        hosp = validate_success(api.create_hospital(
            create_hospital_payload(name="Hosp Page", state_code="CA"), ADMIN), 201)
        validate_success(api.activate_hospital(hosp["id"], ADMIN), 200)
        hdrs = make_hospital_user_headers(hosp["id"])
        for i in (1, 2, 3):
            validate_success(api.create_study(
                create_study_payload(hosp["id"], f"ACC-P{i}"), hdrs), 201)

        page1, meta1 = validate_paginated(
            api.list_studies(DISPATCH, params={"hospital_id": hosp["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_studies(DISPATCH, params={"hospital_id": hosp["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        for row in page1 + page2:
            assert_study(row)
            assert row["hospital_id"] == hosp["id"]
