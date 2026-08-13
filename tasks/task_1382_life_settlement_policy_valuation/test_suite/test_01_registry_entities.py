"""Registry entity corners: brokers, insureds, policies, pagination (PRD §2.2–2.4, §2.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    make_broker_headers,
    create_broker_payload, create_insured_payload, create_policy_payload,
    setup_broker_insured_policy,
    assert_broker,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["case_manager_headers"]


class TestBrokerRegistry:
    def test_broker_create_defaults_and_readback(self, api):
        """PRD §2.9: "Brokers are registered with a `name`, `license_number`, and
        resident `state_code`; a broker record's `status` is always `ACTIVE` — the
        registry keeps a single-state record."
        PRD §2.4: "All entities except `EligibilityScreening` additionally carry
        `updated_at` and an integer `version` that starts at 1 and increments by 1
        on every mutation of that entity."

        Design: Corner/entities/broker_create_defaults_and_readback
        """
        created = validate_success(api.create_broker(
            create_broker_payload(name="Broker One", license_number="BR-1", state_code="TX"),
            ADMIN,
        ), expected_status=201)
        assert created["status"] == "ACTIVE"
        assert created["version"] == 1
        assert_broker(created)

        fetched = validate_success(api.get_broker(created["id"], CM))
        assert fetched["name"] == "Broker One"

    def test_broker_create_ignores_client_supplied_system_fields(self, api):
        """PRD §2.4: "Every entity carries a server-minted `id` formatted as a UUID
        with no type prefix, and a `created_at` timestamp. All entities except
        `EligibilityScreening` additionally carry `updated_at` and an integer
        `version` that starts at 1 and increments by 1 on every mutation of that
        entity."

        Design: Corner/entities/system_fields_input_ignored
        """
        payload = create_broker_payload(name="B", license_number="BR-9", state_code="TX")
        payload["id"] = "00000000-0000-0000-0000-000000000000"
        payload["version"] = 99
        created = validate_success(api.create_broker(payload, ADMIN), expected_status=201)
        assert created["id"] != "00000000-0000-0000-0000-000000000000"
        assert created["version"] == 1


class TestInsuredRegistry:
    def test_insured_missing_required_field_rejected(self, api):
        """PRD §2.7: "Malformed body, missing required field, invalid enum member,
        negative amount, or invalid date (`ERR_INVALID_REQUEST`, HTTP 400)."
        PRD §2.9: "An `Insured` captures `full_name`, `date_of_birth` (an ISO date
        in YYYY-MM-DD form), `state_code`, `gender` (`M` or `F`), `smoker_status`
        (`TOBACCO`, `NON_TOBACCO`, or `UNKNOWN`), and `ssn_last4`."

        Design: Corner/entities/insured_missing_required_field_rejected
        """
        broker = validate_success(api.create_broker(create_broker_payload(name="B"), ADMIN),
                                  expected_status=201)
        payload = create_insured_payload(full_name="P")
        del payload["date_of_birth"]
        resp = api.create_insured(payload, make_broker_headers(broker["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_insured_age_years_tracks_clock(self, api):
        """PRD §2.9: "Every read of an insured exposes the computed `age_years`:
        whole years from `date_of_birth` to the current logical clock date, where
        reaching the birthday increments the count — that is, the age is the clock
        year minus the birth year, reduced by one when the clock's month-and-day
        has not yet reached the birth month-and-day."
        PRD §2.4: "The clock's startup default, before any call to set it, is
        exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/insured_age_years_tracks_clock
        """
        broker = validate_success(api.create_broker(create_broker_payload(name="B"), ADMIN),
                                  expected_status=201)
        insured = validate_success(api.create_insured(
            create_insured_payload(full_name="P", date_of_birth="1960-08-02",
                                   state_code="TX", gender="F"),
            make_broker_headers(broker["id"]),
        ), expected_status=201)
        assert insured["age_years"] == 65, (
            "birthday 08-02 not reached at the default clock 2026-08-01"
        )

        validate_success(api.set_clock("2026-08-02T00:00:00Z", ADMIN))
        reread = validate_success(api.get_insured(insured["id"], CM))
        assert reread["age_years"] == 66


class TestPolicyRegistry:
    def test_policy_defaults_and_computed_contestability(self, api):
        """PRD §2.9: "`cash_value_cents` and `policy_loan_cents` are optional at
        creation and default to 0."
        PRD §2.9: "Every read exposes the computed `in_contestability`: true
        exactly when the current clock date falls earlier than twenty-four months
        after `issue_date`."
        PRD §2.4: "The clock's startup default, before any call to set it, is
        exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/policy_defaults_and_computed_contestability
        """
        broker = validate_success(api.create_broker(create_broker_payload(name="B"), ADMIN),
                                  expected_status=201)
        insured = validate_success(api.create_insured(
            create_insured_payload(full_name="P", date_of_birth="1960-01-01",
                                   state_code="TX", smoker_status="UNKNOWN"),
            make_broker_headers(broker["id"]),
        ), expected_status=201)
        policy = validate_success(api.create_policy(
            create_policy_payload(insured["id"], carrier_name="C", policy_number="P-1",
                                  face_amount_cents=20000000, policy_type="VARIABLE",
                                  issue_date="2025-01-01", annual_premium_cents=900000),
            make_broker_headers(broker["id"]),
        ), expected_status=201)
        assert policy["cash_value_cents"] == 0
        assert policy["policy_loan_cents"] == 0
        # issue 2025-01-01 + 24 months = 2027-01-01 > default clock 2026-08-01
        assert policy["in_contestability"] is True

    def test_policy_invalid_enum_rejected(self, api):
        """PRD §2.7: "Malformed body, missing required field, invalid enum member,
        negative amount, or invalid date (`ERR_INVALID_REQUEST`, HTTP 400)."
        PRD §2.9: "a `policy_type` of `WHOLE_LIFE`, `UNIVERSAL_LIFE`, `VARIABLE`,
        `TERM_CONVERTIBLE`, or `TERM_NONCONVERTIBLE`"

        Design: Corner/entities/policy_invalid_enum_rejected
        """
        broker = validate_success(api.create_broker(create_broker_payload(name="B"), ADMIN),
                                  expected_status=201)
        insured = validate_success(api.create_insured(
            create_insured_payload(full_name="P", date_of_birth="1960-01-01",
                                   state_code="TX", smoker_status="UNKNOWN"),
            make_broker_headers(broker["id"]),
        ), expected_status=201)
        payload = create_policy_payload(insured["id"], carrier_name="C", policy_number="P-1",
                                        face_amount_cents=20000000, issue_date="2023-01-01",
                                        annual_premium_cents=900000, policy_type="TERM")
        resp = api.create_policy(payload, make_broker_headers(broker["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_policy_get_not_found_returns_404(self, api):
        """PRD §2.7: "Where a URL nests one resource under another, path identifiers
        are validated left to right: each id must exist before the next is examined,
        and the first missing id yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/policy_get_not_found_returns_404
        """
        resp = api.get_policy(NON_EXISTENT_UUID, CM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_fk_policy_insured_missing_returns_404(self, api):
        """PRD §2.7: "Body-supplied foreign keys (`policy_id`, `insured_id`,
        `portfolio_id`, and the investor ids inside `allocations`) are validated
        for existence the same way, also producing `ERR_NOT_FOUND` when absent."

        Design: Corner/entities/fk_policy_insured_missing_returns_404
        """
        broker = validate_success(api.create_broker(create_broker_payload(name="B"), ADMIN),
                                  expected_status=201)
        payload = create_policy_payload(NON_EXISTENT_UUID, carrier_name="C",
                                        policy_number="P-1", face_amount_cents=20000000,
                                        issue_date="2023-01-01", annual_premium_cents=900000)
        resp = api.create_policy(payload, make_broker_headers(broker["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCaseListing:
    def test_cases_list_pagination(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and
        `offset`. `limit` defaults to 10, must be at least 1, and may be at most
        100. `offset` defaults to 0. List results are always sorted by `created_at`
        ascending. The `meta` block of a list response carries the four pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/cases_list_pagination
        """
        broker, insured, policy = setup_broker_insured_policy(with_license=False)
        bh = make_broker_headers(broker["id"])
        policy2 = get_success_data(api.create_policy(
            create_policy_payload(insured["id"], policy_number="P-2",
                                  face_amount_cents=20000000, annual_premium_cents=900000), bh))
        policy3 = get_success_data(api.create_policy(
            create_policy_payload(insured["id"], policy_number="P-3",
                                  face_amount_cents=20000000, annual_premium_cents=900000), bh))
        for p in (policy, policy2, policy3):
            validate_success(api.create_case({"policy_id": p["id"]}, bh), expected_status=201)

        page1, meta1 = validate_paginated(api.list_cases(CM, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_cases(CM, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 3
