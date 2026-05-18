"""Client intake and Case opening.

PRD §3.1 — client intake captures full_name / date_of_birth /
contact_email / state_of_residence. Case opening captures client_id,
incident_date, incident_type, jurisdiction_state, and computes
is_minor_at_incident on the client.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    adult_dob_for,
    assert_case,
    assert_client,
    assert_sol_deadline_format,
    create_case,
    create_case_payload,
    create_client,
    create_client_payload,
    minor_dob_for,
    recent_incident_date,
    validate_error,
    validate_success,
)


class TestClientIntake:

    def test_create_client_returns_well_formed_client(
        self, api, paralegal_headers,
    ):
        """PRD §3.1: "The intake step captures full_name,
        date_of_birth, contact_email, and state_of_residence."
        PRD §3.1: "The flag is_minor_at_incident is left null at
        client-creation time and is computed only when the client's
        first case is opened".

        Claim: Created client carries those fields with
        is_minor_at_incident == null.
        """
        resp = api.create_client(
            create_client_payload(
                full_name="Alice Plaintiff",
                date_of_birth="1980-05-04",
                contact_email="alice@example.com",
                state_of_residence="CA",
            ),
            paralegal_headers,
        )
        client = validate_success(resp, expected_status=201)
        assert_client(client)
        assert client["full_name"] == "Alice Plaintiff"
        assert client["date_of_birth"] == "1980-05-04"
        assert client["state_of_residence"] == "CA"
        assert client["is_minor_at_incident"] is None, (
            "PRD §3.1: is_minor_at_incident is null at client creation"
        )


class TestCaseOpening:

    def test_open_case_computes_sol_and_returns_case(
        self, api, paralegal_headers,
    ):
        """PRD §3.1: "On case creation, the server computes
        is_minor_at_incident on the client by asking whether the
        elapsed years between the client's date of birth and the
        case's incident_date is less than 18 years, and the server
        computes the case's sol_deadline via the statute-of-limitations
        calculation".

        Claim: case has sol_deadline set as a YYYY-MM-DD string and
        starts in INTAKE state.
        """
        client = create_client(
            date_of_birth=adult_dob_for(recent_incident_date()),
        )
        resp = api.create_case(
            create_case_payload(
                client["id"],
                incident_date=recent_incident_date(),
                incident_type="AUTO",
                jurisdiction_state="CA",
            ),
            paralegal_headers,
        )
        case = validate_success(resp, expected_status=201)
        assert_case(case)
        assert_sol_deadline_format(case["sol_deadline"])
        # PRD §3.1: "A newly created case enters the INTAKE state".
        assert case["status"] == "INTAKE"
        # PRD §3.1: "with sol_tolled_days of 0, gross_settlement_cents
        # of 0, case_costs_cents of 0, filed_in_court of false, and
        # disbursement_approved_by of null."
        assert case["sol_tolled_days"] == 0
        assert case["gross_settlement_cents"] == 0
        assert case["case_costs_cents"] == 0
        assert case["filed_in_court"] is False
        assert case["disbursement_approved_by"] is None

    def test_is_minor_at_incident_true_when_under_18(
        self, api, paralegal_headers,
    ):
        """PRD §3.1: "the server computes is_minor_at_incident on the
        client by asking whether the elapsed years between the
        client's date of birth and the case's incident_date is less
        than 18 years".

        Claim: minor client (age 14 at incident) has
        is_minor_at_incident == true after case creation.
        """
        incident_iso = recent_incident_date()
        client = create_client(
            date_of_birth=minor_dob_for(incident_iso, age_at_incident=14),
        )
        # Refetch via creating the case (server side-effect).
        create_case(
            client["id"],
            incident_date=incident_iso,
            incident_type="AUTO",
            jurisdiction_state="CA",
        )
        # Re-fetch the client to see the computed flag.
        resp = api.get_client(client["id"], paralegal_headers)
        refreshed_client = validate_success(resp)
        assert refreshed_client["is_minor_at_incident"] is True, (
            "PRD §3.1: is_minor_at_incident is computed true when the "
            "elapsed years is less than 18"
        )

    def test_is_minor_at_incident_false_when_adult(
        self, api, paralegal_headers,
    ):
        """PRD §3.1: "the server computes is_minor_at_incident on the
        client by asking whether the elapsed years between the
        client's date of birth and the case's incident_date is less
        than 18 years".

        Claim: adult client (age 30 at incident) has
        is_minor_at_incident == false after case creation.
        """
        incident_iso = recent_incident_date()
        client = create_client(
            date_of_birth=adult_dob_for(incident_iso, age_at_incident=30),
        )
        create_case(client["id"], incident_date=incident_iso)
        resp = api.get_client(client["id"], paralegal_headers)
        refreshed_client = validate_success(resp)
        assert refreshed_client["is_minor_at_incident"] is False

    def test_open_case_unknown_client_id_returns_reference_not_found(
        self, api, paralegal_headers,
    ):
        """PRD §2.7: "Foreign keys carried in the request body (such
        as client_id when opening a case, assigned_attorney_id when
        assigning an attorney, or predecessor_offer_id when registering
        a counter offer) are validated separately and, if absent, are
        rejected with ERR_REFERENCE_NOT_FOUND (HTTP 404)."

        Claim: POST /pi-cases with unknown client_id →
        ERR_REFERENCE_NOT_FOUND.
        """
        resp = api.create_case(
            create_case_payload(NON_EXISTENT_UUID), paralegal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)

    def test_get_case_unknown_id_returns_not_found(
        self, api, paralegal_headers,
    ):
        """PRD §2.7: "Any failure of an existence check returns
        ERR_NOT_FOUND (HTTP 404)."

        Claim: GET /pi-cases/{id} for missing id → ERR_NOT_FOUND.
        """
        resp = api.get_case(NON_EXISTENT_UUID, paralegal_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_list_cases_returns_paginated_envelope(
        self, api, paralegal_headers,
    ):
        """PRD §2.3: "Every list response surfaces limit, offset,
        total_count, and has_more inside the meta envelope."

        Claim: GET /pi-cases returns a paginated envelope.
        """
        # Seed a single client + case so list isn't empty.
        client = create_client()
        create_case(client["id"])
        from test_helpers import validate_paginated
        resp = api.list_cases(paralegal_headers)
        data, meta = validate_paginated(resp)
        assert "total_count" in meta
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta
        assert isinstance(data, list)
