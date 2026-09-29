"""Structural refusals and server-owned fields on the two creation endpoints.

A program missing one of its three dates never reaches the store.  A contract
stamps its drafter from the header and seeds its own negotiation counters.  An
unresolvable parent key is a 404 that consumes nothing, so the identical body
with a real parent still succeeds.
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
from test_helpers.assertions import assert_version
from test_helpers.test_users import OFFICER, make_officer_headers


class TestProgramCreationShape:
    def test_a_program_without_its_census_date_is_a_structural_refusal(self, client):
        """The required field is checked before anything is written.

        "Structural validity of the body and query string: required fields
        present, enum values in range, dates in ISO 8601 `YYYY-MM-DD` form,
        integers within their declared bounds, `limit` between 1 and 100, `offset`
        at least 0 — `ERR_INVALID_REQUEST`."

        "`census_date` is the enrollment census, which must be on or after
        `term_start_date`"

        Design: Corner/entities/program_missing_required_field_rejected
        """
        response = client.create_program(
            F.program_payload(census_date=None), OFFICER
        )
        validate_error(response, E.ERR_INVALID_REQUEST)

        follow_up = client.get_program(NON_EXISTENT_UUID, OFFICER)
        validate_error(follow_up, E.ERR_PROGRAM_NOT_FOUND)


class TestContractCreationShape:
    def test_the_drafter_and_the_negotiation_counters_are_server_owned(self, client):
        """The body never supplies the drafter; the header does.

        "The new contract lands in `DRAFT` with `disclosure_template_version` at
        1, `amendment_round` at 0, `created_by_user_id` set to the drafting
        officer's `X-User-ID`, and `agency_signed_by_user_id`,
        `compliance_approved_by_user_id`, `terminated_on`,
        `termination_reason_code` and `suspension_reason` all unset."

        Design: Corner/entities/contract_system_fields_generated_by_server
        """
        agency = fx.register_agency(
            client,
            legal_name="Contract Fields Agency",
            home_country_code="IN",
            complete_diligence=False,
        )

        response = client.draft_contract(
            F.contract_payload(agency["id"], contract_ref="CTR-001"),
            make_officer_headers("officer-7"),
        )
        contract = validate_success(response, 201)

        assert is_valid_uuid(contract["id"])
        assert is_iso8601_timestamp(contract["created_at"])
        assert is_iso8601_timestamp(contract["updated_at"])
        assert_version(contract, 1)

        assert contract["status"] == C.CONTRACT_DRAFT
        assert contract["disclosure_template_version"] == 1
        assert contract["amendment_round"] == 0
        assert contract["created_by_user_id"] == "officer-7"

        assert contract["agency_signed_by_user_id"] is None
        assert contract["compliance_approved_by_user_id"] is None
        assert contract["terminated_on"] is None
        assert contract["termination_reason_code"] is None
        assert contract["suspension_reason"] is None

    def test_an_unresolvable_agency_key_is_a_not_found_that_consumes_nothing(
        self, client
    ):
        """The rejected attempt does not burn the office-assigned reference.

        "Foreign keys supplied in a request body are resolved after path
        identifiers and after structural validation, and they raise the same 404
        family."

        "an office-assigned `contract_ref` that must be unique across contracts"

        Design: Corner/entities/contract_creation_validates_agency_foreign_key
        """
        agency = fx.register_agency(
            client,
            legal_name="FK Test Agency",
            home_country_code="IN",
            complete_diligence=False,
        )

        refused = client.draft_contract(
            F.contract_payload(NON_EXISTENT_UUID, contract_ref="CTR-001"), OFFICER
        )
        validate_error(refused, E.ERR_AGENCY_NOT_FOUND)

        accepted = validate_success(
            client.draft_contract(
                F.contract_payload(agency["id"], contract_ref="CTR-001"), OFFICER
            ),
            201,
        )
        assert accepted["agency_id"] == agency["id"]
        assert accepted["contract_ref"] == "CTR-001"

        rows, meta = validate_paginated(
            client.list_contracts(OFFICER, {"agency_id": agency["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]
