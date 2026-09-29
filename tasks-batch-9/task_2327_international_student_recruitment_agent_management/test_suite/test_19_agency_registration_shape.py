"""What registration writes, what a read gives back, and how the list is paged.

An agency lands on both initial dimensions at once with every aggregate at zero,
the checklist defaults materialise as values rather than nulls, a read never
advances the version, and the collection reports the full filtered size.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_empty_diligence_checklist,
    assert_fresh_agency_defaults,
    assert_version,
)
from test_helpers.test_users import COMPLIANCE, OFFICER


class TestAgencyRegistrationShape:
    def test_registration_echoes_both_dimensions_and_every_aggregate_at_zero(
        self, client
    ):
        """One call fixes the due-diligence dimension and the integrity dimension.

        "A newly registered agency begins in `DRAFT` on the due-diligence
        dimension and `GOOD_STANDING` on the integrity dimension, with
        `rolling_risk_score` and `lifetime_risk_score` both at 0.00,
        `confirmed_incident_count`, `reviewed_document_count`,
        `confirmed_fraud_document_count`, `net_earned_commission_cents` and
        `clawback_liability_cents` all at 0, `current_tier` at `UNRATED`, and
        `last_posture_reason` unset."

        Design: Corner/entities/agency_creation_persists_due_diligence_checklist
        """
        response = client.register_agency(
            F.complete_diligence_agency_payload(
                "Sunrise Education Consultants",
                "IN",
                beneficial_owner_count=2,
                reference_check_count=3,
            ),
            OFFICER,
        )
        agency = validate_success(response, 201)

        assert is_valid_uuid(agency["id"]), f"id must be a UUID, got {agency['id']!r}"
        assert is_iso8601_timestamp(agency["created_at"])
        assert is_iso8601_timestamp(agency["updated_at"])
        assert_version(agency, 1)

        assert agency["legal_name"] == "Sunrise Education Consultants"
        assert agency["home_country_code"] == "IN"
        assert agency["ownership_disclosed"] is True
        assert agency["beneficial_owner_count"] == 2
        assert agency["sanctions_screen_passed"] is True
        assert agency["reference_check_count"] == 3

        assert_fresh_agency_defaults(agency)

    def test_an_omitted_checklist_materialises_the_four_declared_defaults(
        self, client
    ):
        """Nothing is left null; the negative values are written.

        "`ownership_disclosed` and `sanctions_screen_passed` are booleans that
        both default to false, while `beneficial_owner_count` and
        `reference_check_count` are non-negative integers that both default to 0."

        Design: Corner/entities/agency_defaults_applied_when_checklist_omitted
        """
        agency = fx.register_agency(
            client,
            legal_name="Minimal Agency",
            home_country_code="BD",
            complete_diligence=False,
        )

        assert_empty_diligence_checklist(agency)
        assert agency["vetting_state"] == C.VETTING_DRAFT
        assert agency["current_tier"] == C.TIER_UNRATED

    def test_a_read_back_returns_the_stored_row_without_advancing_the_version(
        self, client
    ):
        """Both risk variants and both ledger aggregates survive the round trip.

        "`version`, an integer that starts at 1 on creation and increments by one
        on every mutation of that resource."

        Design: Corner/entities/agency_retrieval_returns_stored_row
        """
        created = fx.register_agency(
            client,
            legal_name="Meridian Study Abroad",
            home_country_code="VN",
            beneficial_owner_count=1,
            reference_check_count=2,
        )

        fetched = validate_success(client.get_agency(created["id"], COMPLIANCE))

        assert fetched["id"] == created["id"]
        assert fetched["legal_name"] == "Meridian Study Abroad"
        assert fetched["home_country_code"] == "VN"
        assert fetched["beneficial_owner_count"] == 1
        assert_fresh_agency_defaults(fetched)
        assert_version(fetched, 1)

    def test_the_collection_pages_by_window_and_reports_the_whole_result_size(
        self, client
    ):
        """total_count is the full set size, not the size of the returned page.

        "`total_count` is the size of the full filtered result set, not the size
        of the returned page, and `has_more` is true exactly when items remain
        beyond the current window."

        "`limit` caps the number of items returned; it defaults to 10, may be no
        smaller than 1, and may be no larger than 100. `offset` is the number of
        items skipped before the window begins; it defaults to 0"

        Design: Corner/entities/agency_listing_paginates_and_filters
        """
        alpha = fx.register_agency(
            client,
            legal_name="Agency Alpha",
            home_country_code="IN",
            beneficial_owner_count=1,
            reference_check_count=2,
        )
        fx.clear_agency(client, alpha["id"])
        fx.register_agency(
            client,
            legal_name="Agency Bravo",
            home_country_code="NP",
            complete_diligence=False,
        )
        fx.register_agency(
            client,
            legal_name="Agency Charlie",
            home_country_code="NG",
            complete_diligence=False,
        )

        first_page, first_meta = validate_paginated(
            client.list_agencies(OFFICER, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            client.list_agencies(OFFICER, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        unwindowed, default_meta = validate_paginated(client.list_agencies(OFFICER))
        assert len(unwindowed) == 3
        assert default_meta["limit"] == C.DEFAULT_LIMIT
        assert default_meta["offset"] == C.DEFAULT_OFFSET
        assert default_meta["has_more"] is False

    def test_an_unknown_agency_id_is_a_not_found_error_and_not_an_empty_success(
        self, client
    ):
        """The resolution failure carries a machine-readable identifier.

        "The nine resolution failures are `ERR_AGENCY_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`
        and `ERR_TRANSITION_NOT_FOUND`, all HTTP 404."

        "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/agency_lookup_with_unknown_id_returns_not_found
        """
        response = client.get_agency(NON_EXISTENT_UUID, OFFICER)
        error = validate_error(response, E.ERR_AGENCY_NOT_FOUND)
        assert isinstance(error["message"], str) and error["message"].strip()

        listed, meta = validate_paginated(client.list_agencies(OFFICER))
        assert meta["total_count"] == 0
        assert listed == []
