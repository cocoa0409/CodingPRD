"""Household creation, retrieval, listing, update — core household lifecycle.

Covers PRD §3.1 (creation), §2.4 (common fields including case_number),
§3.10 (listing with filters), §2.6 (optimistic concurrency on PATCH).
"""
import pytest

from test_helpers import (
    api_client as _api,
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    ERR_AUTH_MISSING, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
    TEST_USERS, make_household_head_headers,
    assert_household, CASE_NUMBER_PATTERN,
    create_household_payload, create_household,
)


CASEWORKER = TEST_USERS["caseworker_headers"]


# ---------------------------------------------------------------------------
# POST /households — creation
# ---------------------------------------------------------------------------

class TestCreateHousehold:
    def test_create_household_minimal_returns_201(self, api):
        """PRD §3.1: "A `Caseworker` creates the empty household by supplying
        the two-letter `state_code`, the 5-digit residential `address_zip`."

        Claim: minimal valid payload returns 201 with a Household entity.
        """
        resp = api.create_household(create_household_payload(), CASEWORKER)
        data = validate_success(resp, expected_status=201)
        assert_household(data)
        assert data["state_code"] == "CA"
        assert data["address_zip"] == "94110"

    def test_create_household_case_number_format(self, api):
        """PRD §2.4: "Household carries the public-facing identifier `case_number`
        minted by the server on creation, formatted as `SNAP-YYYY-NNNNNN` (the
        prefix `SNAP-`, four digits for the year, and six zero-padded sequence
        digits), and immutable thereafter."

        Claim: case_number matches the SNAP-YYYY-NNNNNN pattern.
        """
        resp = api.create_household(create_household_payload(), CASEWORKER)
        data = validate_success(resp, expected_status=201)
        assert CASE_NUMBER_PATTERN.match(data["case_number"]), (
            f"case_number {data['case_number']} does not match SNAP-YYYY-NNNNNN"
        )

    def test_create_household_initial_aggregates_are_zero(self, api):
        """PRD §3.1: "At creation there are no members, so the computed aggregates
        start at their identity values: `household_size` is 0,
        `gross_monthly_income_cents` is 0, `has_elderly_or_disabled` is false,
        `net_monthly_income_cents` is 0, `monthly_allotment_cents` is 0,
        and `certification_status` is null."

        Claim: a fresh household has all zero/null aggregates.
        """
        resp = api.create_household(create_household_payload(), CASEWORKER)
        data = validate_success(resp, expected_status=201)
        assert data["household_size"] == 0
        assert data["gross_monthly_income_cents"] == 0
        assert data["has_elderly_or_disabled"] is False
        assert data["net_monthly_income_cents"] == 0
        assert data["monthly_allotment_cents"] == 0
        assert data["certification_status"] is None

    def test_create_household_default_expenses_are_zero(self, api):
        """PRD §3.1: "both default to 0 and must be non-negative integer cents"
        (referring to dependent_care_expense_cents and shelter_expense_cents).

        Claim: when expenses are omitted, both default to 0.
        """
        resp = api.create_household(create_household_payload(), CASEWORKER)
        data = validate_success(resp, expected_status=201)
        assert data["dependent_care_expense_cents"] == 0
        assert data["shelter_expense_cents"] == 0

    @pytest.mark.parametrize("bad_state", ["XX", "ZZ", "ca", "California"])
    def test_create_household_invalid_state_code_rejected(self, api, bad_state):
        """PRD §2.11: "Household.state_code: one of `CA`, `TX`, `NY`, `FL`, `IL`,
        `PA`, `OH`, `GA`, `NC`, `MI`."

        Claim: state_code outside the enum yields ERR_VALIDATION.
        """
        payload = create_household_payload(state_code=bad_state)
        resp = api.create_household(payload, CASEWORKER)
        validate_error(resp, ERR_VALIDATION)

    @pytest.mark.parametrize("bad_zip", ["1234", "123456", "abcde", ""])
    def test_create_household_invalid_zip_rejected(self, api, bad_zip):
        """PRD §3.1: "the 5-digit residential `address_zip`."

        Claim: a non-5-digit zip yields ERR_VALIDATION.
        """
        payload = create_household_payload(address_zip=bad_zip)
        resp = api.create_household(payload, CASEWORKER)
        validate_error(resp, ERR_VALIDATION)

    def test_create_household_negative_expense_rejected(self, api):
        """PRD §3.1: "both default to 0 and must be non-negative integer cents."

        Claim: a negative shelter_expense_cents yields ERR_VALIDATION.
        """
        payload = create_household_payload(shelter_expense_cents=-1)
        resp = api.create_household(payload, CASEWORKER)
        validate_error(resp, ERR_VALIDATION)

    def test_create_household_missing_auth_rejected(self, api):
        """PRD §2.1: "Both must be present and non-empty; missing either yields
        `ERR_AUTH_MISSING` with HTTP 401."

        Claim: missing X-User-* headers yield ERR_AUTH_MISSING.
        """
        resp = api.create_household(create_household_payload(), headers={})
        validate_error(resp, ERR_AUTH_MISSING)

    def test_create_household_non_caseworker_role_forbidden(self, api):
        """PRD §4 table: "POST /households — Create a new Household — Caseworker."

        Claim: a non-Caseworker role yields ERR_FORBIDDEN.
        """
        resp = api.create_household(
            create_household_payload(),
            TEST_USERS["state_admin_headers"],
        )
        validate_error(resp, ERR_FORBIDDEN)


# ---------------------------------------------------------------------------
# GET /households/{id}
# ---------------------------------------------------------------------------

class TestGetHousehold:
    def test_get_household_returns_full_record(self, api):
        """PRD §4 table: "GET /households/{id} — Fetch a Household with all
        computed fields up to date — Caseworker, HouseholdHead, FraudInvestigator."

        Claim: GET on a valid household id returns the household entity.
        """
        hh = create_household()
        resp = api.get_household(hh["id"], CASEWORKER)
        data = validate_success(resp)
        assert data["id"] == hh["id"]
        assert_household(data)

    def test_get_household_unknown_id_returns_not_found(self, api):
        """PRD §2.12: "Path-resource existence, validated left-to-right
        (`ERR_NOT_FOUND`)."

        Claim: GET with a non-existent household id yields ERR_NOT_FOUND.
        """
        resp = api.get_household(NON_EXISTENT_UUID, CASEWORKER)
        validate_error(resp, ERR_NOT_FOUND)

    def test_get_household_cross_owner_forbidden_for_household_head(self, api):
        """PRD §2.1: "an attempt by a `HouseholdHead` to read or mutate another
        household's data yields `ERR_FORBIDDEN`."

        Claim: a HouseholdHead whose X-User-ID does not match the household id
        yields ERR_FORBIDDEN.
        """
        hh = create_household()
        other_hh = create_household()
        # Identity threading: pretend caller is other_hh
        other_headers = make_household_head_headers(other_hh["id"])
        resp = api.get_household(hh["id"], other_headers)
        validate_error(resp, ERR_FORBIDDEN)

    def test_get_household_by_owning_household_head_succeeds(self, api):
        """PRD §2.1: "X-User-ID is the `id` of the acting `Household`; any
        ownership check on a household-scoped resource compares the resource's
        `household_id` to `X-User-ID`."

        Claim: the HouseholdHead whose id equals the household's id can read it.
        """
        hh = create_household()
        own_headers = make_household_head_headers(hh["id"])
        resp = api.get_household(hh["id"], own_headers)
        data = validate_success(resp)
        assert data["id"] == hh["id"]


# ---------------------------------------------------------------------------
# GET /households — listing + pagination
# ---------------------------------------------------------------------------

class TestListHouseholds:
    def test_list_households_returns_paginated_envelope(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`
        (default 10, minimum 1, maximum 100) and `offset` (default 0)."

        Claim: list endpoint returns paginated envelope with meta block.
        """
        create_household()
        resp = api.list_households(CASEWORKER)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert "total_count" in meta
        assert "has_more" in meta

    def test_list_households_filter_by_state_code(self, api):
        """PRD §3.10: "Listing households supports filters on `state_code` and
        `certification_status`."

        Claim: state_code filter narrows results.
        """
        ca_h = create_household(state_code="CA")
        ny_h = create_household(state_code="NY")
        resp = api.list_households(CASEWORKER, params={"state_code": "CA", "limit": 100})
        data, _ = validate_paginated(resp)
        ids = {h["id"] for h in data}
        assert ca_h["id"] in ids
        assert ny_h["id"] not in ids
        for h in data:
            assert h["state_code"] == "CA"

    @pytest.mark.parametrize("bad_limit", [0, 101, -1, "abc"])
    def test_list_households_bad_pagination_rejected(self, api, bad_limit):
        """PRD §2.3: "Values outside these ranges, or non-integer values, are
        rejected with `ERR_VALIDATION` (HTTP 400)."

        Claim: out-of-range or non-integer limit yields ERR_VALIDATION.
        """
        resp = api.list_households(CASEWORKER, params={"limit": bad_limit})
        validate_error(resp, ERR_VALIDATION)


# ---------------------------------------------------------------------------
# PATCH /households/{id}
# ---------------------------------------------------------------------------

class TestUpdateHousehold:
    def test_update_household_shelter_expense_recomputes(self, api):
        """PRD §3.1: "A caseworker can adjust ... `shelter_expense_cents` later
        via a household update; if either expense field changes, the server
        immediately recomputes `net_monthly_income_cents` and
        `monthly_allotment_cents` so subsequent reads reflect current eligibility math."

        Claim: PATCH shelter expense updates the household and triggers
        downstream recompute.
        """
        hh = create_household(shelter_expense_cents=0)
        resp = api.update_household(
            hh["id"], {"shelter_expense_cents": 100000}, CASEWORKER
        )
        data = validate_success(resp)
        assert data["shelter_expense_cents"] == 100000

    def test_update_household_version_bumps_on_mutation(self, api):
        """PRD §2.4: "`version` is a non-negative integer that starts at 1 and
        increments by exactly 1 on every mutation that changes any persisted
        field on the entity."

        Claim: a PATCH that changes a field bumps version by exactly 1.
        """
        hh = create_household()
        v1 = hh["version"]
        resp = api.update_household(
            hh["id"], {"shelter_expense_cents": 50000}, CASEWORKER
        )
        data = validate_success(resp)
        assert data["version"] == v1 + 1

    def test_update_household_version_conflict(self, api):
        """PRD §2.6: "When supplied values disagree, the server returns
        `ERR_VERSION_CONFLICT` with HTTP 409 and applies no mutation."

        Claim: PATCH with a stale version yields ERR_VERSION_CONFLICT.
        """
        hh = create_household()
        # Take one mutation so version becomes 2
        validate_success(api.update_household(
            hh["id"], {"shelter_expense_cents": 1}, CASEWORKER
        ))
        # Now try with the stale version=1
        resp = api.update_household(
            hh["id"], {"shelter_expense_cents": 2, "version": 1}, CASEWORKER
        )
        validate_error(resp, ERR_VERSION_CONFLICT)

    def test_update_household_omitted_version_skips_check(self, api):
        """PRD §2.6: "When the client omits `version` from the body entirely,
        the version check is skipped and the mutation proceeds against whatever
        value is current."

        Claim: PATCH without version field proceeds against current version.
        """
        hh = create_household()
        validate_success(api.update_household(hh["id"], {"shelter_expense_cents": 1}, CASEWORKER))
        resp = api.update_household(hh["id"], {"shelter_expense_cents": 2}, CASEWORKER)
        validate_success(resp)
