"""Directory registration and report intake corner cases (PRD 3.1, 2.2-2.4)."""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_case,
    assert_instant_equals,
    assert_party_profile,
    create_case_payload,
    create_party_profile_payload,
    get_success_data,
    is_valid_uuid,
    make_cast,
    make_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


class TestDirectoryRegistration:
    def test_advisor_eligible_defaults_false(self, api, case_admin_headers):
        """PRD 3.1: "records a `full_name`, a university-issued `university_id`, a
        `role_type` of `STUDENT`, `EMPLOYEE`, `FACULTY`, `STAFF`, or `EXTERNAL`, a
        contact `email`, and an optional `advisor_eligible` flag that defaults to
        false and marks whether the person may serve as a university-appointed
        advisor."

        Design: Corner/entities/party_profile_advisor_eligible_default_false
        """
        resp = api.create_party_profile(
            create_party_profile_payload(
                full_name="No Flag", university_id="U-NF-1",
                role_type="EXTERNAL", email="nf@example.edu",
            ),
            case_admin_headers,
        )
        data = validate_success(resp, 201)
        assert_party_profile(data)
        assert data["advisor_eligible"] is False, (
            "advisor_eligible must default to false when omitted"
        )

    def test_duplicate_university_id_rejected(self, api, case_admin_headers):
        """PRD 3.1: "The `university_id` must be unique across the directory; a
        duplicate registration is rejected with `ERR_DUPLICATE_RESOURCE` (409)."

        Design: Corner/entities/party_profile_duplicate_university_id_rejected
        """
        api.create_party_profile(
            create_party_profile_payload(
                full_name="First", university_id="U-C-1",
                role_type="STUDENT", email="a@example.edu",
            ),
            case_admin_headers,
        )
        resp = api.create_party_profile(
            create_party_profile_payload(
                full_name="Second", university_id="U-C-1",
                role_type="STAFF", email="b@example.edu",
            ),
            case_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


class TestCaseIntake:
    def test_case_creation_success_full_readback(self, api):
        """PRD 3.1: "At intake the server mints the human reference `report_number`
        in the form RPT-<received year>-<zero-padded sequence within that received
        year>, stamps `received_at` from the logical clock, computes the initial
        exposure score per §2.7, appends `REPORT_RECEIVED` to the audit trail, and
        lands the case in `RECEIVED`."
        PRD 2.4: "At server startup the logical clock is exactly
        `2026-08-01T00:00:00Z`, and it must not fall back to wall-clock time under
        any circumstance."

        Design: Corner/entities/case_creation_success_full_readback
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        resp = api.create_case(
            create_case_payload(
                cast["comp"]["id"], cast["resp"]["id"], cast["coord"]["id"],
                categories=["SEXUAL_ASSAULT"],
            ),
            coord_h,
        )
        data = validate_success(resp, 201)
        assert_case(data)
        assert data["status"] == "RECEIVED", "case must land in RECEIVED"
        # report_number form RPT-<received year>-<zero-padded sequence>; the
        # first case of clock year 2026 carries sequence 1 with zero padding.
        assert re.fullmatch(r"RPT-2026-0+1", data["report_number"]), (
            f"report_number must be RPT-2026-<zero-padded 1>, got {data['report_number']}"
        )
        assert_instant_equals(data["received_at"], "2026-08-01T00:00:00Z", "received_at")
        # Initial exposure per the scoring rule: SEXUAL_ASSAULT base 40 with no
        # priors, no violations, and no ACTIVE directive.
        assert data["exposure_score"] == 40
        assert data["interim_suspension_eligible"] is False
        assert data["active_supportive_measure_count"] == 0
        assert is_valid_uuid(data["id"])

    def test_case_creation_missing_required_categories_rejected(self, api):
        """PRD 2.11: "**Request schema** — missing required fields, wrong types,
        unknown enum members, empty arrays where a non-empty array is required,
        and malformed datetimes, failing as `ERR_INVALID_REQUEST` (400)."
        PRD 3.1 names "a non-empty `categories` array" in the intake payload.

        Design: Corner/entities/case_creation_missing_required_categories_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        payload = create_case_payload(
            cast["comp"]["id"], cast["resp"]["id"], cast["coord"]["id"],
        )
        payload.pop("categories")
        resp = api.create_case(payload, coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # No partial creation: the register stays empty.
        listing, meta = validate_paginated(api.list_cases(coord_h))
        assert meta["total_count"] == 0 and listing == []

    def test_case_creation_invalid_enum_rejected(self, api):
        """PRD 2.11: "**Request schema** — missing required fields, wrong types,
        unknown enum members, empty arrays where a non-empty array is required,
        and malformed datetimes, failing as `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/case_creation_invalid_enum_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        resp = api.create_case(
            create_case_payload(
                cast["comp"]["id"], cast["resp"]["id"], cast["coord"]["id"],
                categories=["BOGUS"],
            ),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_case_creation_empty_categories_rejected(self, api):
        """PRD 3.1: the intake payload carries "a non-empty `categories` array
        drawn from `SEXUAL_HARASSMENT`, `SEXUAL_ASSAULT`, `DATING_VIOLENCE`,
        `DOMESTIC_VIOLENCE`, `STALKING`, `OTHER_SEX_BASED`, and
        `NON_TITLE_IX_MISCONDUCT`".
        PRD 2.11: "**Request schema** — missing required fields, wrong types,
        unknown enum members, empty arrays where a non-empty array is required,
        and malformed datetimes, failing as `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/case_creation_empty_categories_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        resp = api.create_case(
            create_case_payload(
                cast["comp"]["id"], cast["resp"]["id"], cast["coord"]["id"],
                categories=[],
            ),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_case_create_body_fk_not_found_rejected(self, api):
        """PRD 2.11: "Body foreign-key fields that name people — `complainant_id`,
        `respondent_id`, `coordinator_id`, `investigator_id`, `advisor_id`,
        `decision_maker_id`, `appeal_officer_id`, `facilitator_id`,
        `asked_by_advisor_id` — must likewise resolve to existing `PartyProfile`
        rows, failing as `ERR_NOT_FOUND`."

        Design: Corner/entities/case_create_body_fk_not_found_rejected
        """
        cast = make_cast("resp", "coord")
        resp = api.create_case(
            create_case_payload(
                NON_EXISTENT_UUID, cast["resp"]["id"], cast["coord"]["id"],
            ),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCaseReadAndListing:
    def test_case_get_not_found_returns_404(self, api):
        """PRD 2.11: "**Existence** — path-template identifiers are resolved strictly
        left to right: the case id before any nested child id, the directive id
        before a violation under it, the hearing id before a question under it;
        the first unresolvable identifier in the path fails as `ERR_NOT_FOUND`
        (404)."

        Design: Corner/entities/case_get_not_found_returns_404
        """
        cast = make_cast("coord")
        resp = api.get_case(
            NON_EXISTENT_UUID, make_coordinator_headers(cast["coord"]["id"])
        )
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(err.get("message"), str) and err["message"].strip()

    def test_case_list_pagination_defaults(self, api):
        """PRD 2.3: "The `limit` parameter caps the number of returned items; it
        defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD 2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/case_list_pagination_defaults
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        for day in range(1, 13):
            resp = api.create_case(
                create_case_payload(
                    cast["comp"]["id"], cast["resp"]["id"], cast["coord"]["id"],
                    occurred_at=f"2026-07-{day:02d}T00:00:00Z", received_via="EMAIL",
                ),
                coord_h,
            )
            get_success_data(resp, 201)

        listing, meta = validate_paginated(api.list_cases(coord_h))
        assert len(listing) == 10, "default page must return exactly 10 rows"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10 and meta["offset"] == 0

        listing2, meta2 = validate_paginated(
            api.list_cases(coord_h, params={"limit": 2, "offset": 10})
        )
        assert len(listing2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
