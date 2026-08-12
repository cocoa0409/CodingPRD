"""Host onboarding, site defaults, and response-envelope claims."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    TEST_USERS,
    api_client,
    assert_hive,
    assert_host,
    assert_site,
    create_active_host,
    create_host_payload,
    create_site_payload,
    is_valid_uuid,
    make_host_headers,
    setup_hive_scenario,
    setup_signed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHostRegistration:
    def test_host_missing_email_rejected(self, api, anonymous_headers):
        """PRD §3.1: "A homeowner joins the platform by self-registering as an
        `Anonymous` caller with their `full_name` and `email`."
        PRD §2.12 step 5: "required fields present, enum values valid, ranges
        honored (`bees_sampled` at least 1, `quiz_score` between 0 and 100,
        `term_end_date` after `term_start_date`, `end_date` after `start_date`,
        `gross_kg` strictly above 0, `email` unique across hosts); otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/host_missing_required_email_invalid_request
        """
        res = api.create_host({"full_name": "No Email"}, anonymous_headers)
        validate_error(res, "ERR_INVALID_REQUEST")
        # Nothing written: the only listable state is via host reads, and the
        # failed creation returned no id to read back; the error itself is the
        # assertion target.

    def test_host_creation_defaults_and_system_fields(self, api, anonymous_headers):
        """PRD §3.1: "The new `Host` record starts in `APPLICANT` status with
        `reputation_score` at 100, `honey_credit_kg` at 0, and
        `balance_due_cents` at 0."
        PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/host_creation_defaults_and_system_fields
        """
        res = api.create_host(
            create_host_payload(full_name="New Host", email="new@example.com"),
            anonymous_headers,
        )
        host = validate_success(res, 201)
        assert_host(host)
        assert host["status"] == "APPLICANT", "initial host status"
        assert host["reputation_score"] == 100
        assert host["honey_credit_kg"] == 0
        assert host["balance_due_cents"] == 0
        assert host["waiver_signed_at"] is None, "no waiver signed yet"
        assert is_valid_uuid(host["id"]), "id is a server-minted UUID"

    def test_host_duplicate_email_rejected(self, api, anonymous_headers):
        """PRD §3.1: "the email must be unique across all hosts."
        PRD §2.12 step 5: "required fields present, enum values valid, ranges
        honored (`bees_sampled` at least 1, `quiz_score` between 0 and 100,
        `term_end_date` after `term_start_date`, `end_date` after `start_date`,
        `gross_kg` strictly above 0, `email` unique across hosts); otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/host_duplicate_email_rejected
        """
        first = validate_success(
            api.create_host(
                create_host_payload(full_name="First", email="dup@example.com"),
                anonymous_headers,
            ),
            201,
        )
        res = api.create_host(
            create_host_payload(full_name="Second", email="dup@example.com"),
            anonymous_headers,
        )
        validate_error(res, "ERR_INVALID_REQUEST")
        reread = validate_success(
            api.get_host(first["id"], TEST_USERS["ops_headers"]), 200,
        )
        assert reread["full_name"] == "First", "first record untouched"


class TestSiteDefaults:
    def test_site_creation_default_capacity_applied(self, api):
        """PRD §2.8: "A site's `base_capacity_hives` (at least 1, defaulting to
        2 when omitted) is augmented by bonuses to yield
        `effective_capacity_hives`."
        PRD §3.1: "A new site starts `CLEAR`."

        Design: Corner/entities/site_creation_default_capacity_applied
        """
        host = create_active_host()
        payload = create_site_payload(host["id"], address="1 Default Way")
        del payload["base_capacity_hives"]  # exercise the declared default
        res = api.create_site(payload, make_host_headers(host["id"]))
        site = validate_success(res, 201)
        assert_site(site)
        assert site["base_capacity_hives"] == 2, "declared default capacity"
        assert site["effective_capacity_hives"] == 2, (
            "no PREMIUM plan and no ADV-201 completion, so no bonuses"
        )
        assert site["status"] == "CLEAR", "site initial state"


class TestReadAndListingEnvelope:
    def test_hive_get_not_found_returns_404(self, api, ops_headers):
        """PRD §2.12 step 4: "a missing resource yields `ERR_NOT_FOUND` (404)."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/hive_get_not_found_returns_404
        """
        res = api.get_hive(NON_EXISTENT_UUID, ops_headers)
        err = validate_error(res, "ERR_NOT_FOUND")
        assert err["message"].strip(), "error envelope carries a message"
        assert res.json()["response_type"] == "error"

    def test_hives_list_filter_and_pagination_envelope(self, api, ops_headers):
        """PRD §2.3: "`limit` defaults to 10 when omitted, with a minimum of 1
        and a maximum of 100. `offset` defaults to 0. Every list response is
        sorted by `created_at` in ascending order unless explicitly stated
        otherwise, and the `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §3.3: "hive listings accept optional filters on `site_id`,
        `agreement_id`, `parent_hive_id`, and `source_swarm_event_id`."

        Design: Corner/entities/hives_list_filter_and_pagination_envelope
        """
        host = create_active_host()
        site1 = validate_success(
            api.create_site(
                create_site_payload(host["id"], address="10 List Ln"),
                make_host_headers(host["id"]),
            ),
            201,
        )
        site2 = validate_success(
            api.create_site(
                create_site_payload(host["id"], address="20 List Ln"),
                make_host_headers(host["id"]),
            ),
            201,
        )
        ag1 = validate_success(
            api.create_agreement(
                {
                    "host_id": host["id"],
                    "site_id": site1["id"],
                    "term_start_date": TEST_DEFAULTS["TERM_START"],
                    "term_end_date": TEST_DEFAULTS["TERM_END"],
                    "host_share_base_bps": 2500,
                },
                ops_headers,
            ),
            201,
        )
        api.sign_agreement(ag1["id"], make_host_headers(host["id"]))
        ag2 = validate_success(
            api.create_agreement(
                {
                    "host_id": host["id"],
                    "site_id": site2["id"],
                    "term_start_date": TEST_DEFAULTS["TERM_START"],
                    "term_end_date": TEST_DEFAULTS["TERM_END"],
                    "host_share_base_bps": 2500,
                },
                ops_headers,
            ),
            201,
        )
        api.sign_agreement(ag2["id"], make_host_headers(host["id"]))
        mgr = TEST_USERS["manager_headers"]
        for _ in range(2):
            validate_success(
                api.create_hive(
                    {"site_id": site1["id"], "agreement_id": ag1["id"]}, mgr,
                ),
                201,
            )
        validate_success(
            api.create_hive(
                {"site_id": site2["id"], "agreement_id": ag2["id"]}, mgr,
            ),
            201,
        )

        res = api.list_hives(ops_headers, params={"site_id": site1["id"]})
        assert res.json()["response_type"] == "array"
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10, "declared default limit"
        assert meta["offset"] == 0, "declared default offset"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert isinstance(meta["api_request_id"], str)
        assert isinstance(meta["api_request_timestamp"], str)
        assert len(data) == 2
        for hive in data:
            assert_hive(hive)
            assert hive["site_id"] == site1["id"], "filter restricts to site1"
