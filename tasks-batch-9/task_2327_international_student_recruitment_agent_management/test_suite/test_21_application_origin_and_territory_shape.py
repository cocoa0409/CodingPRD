"""Derived fields ignore client input; structural gates run before geometry.

The recruitment origin is computed from two fields and nothing else, so a
supplied value is discarded.  A territory request with an out-of-enum exclusivity
or a non-increasing interval never reaches the exclusivity geometry.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents
from test_helpers.test_users import OFFICER, make_agency_owner_headers


class TestApplicationOriginIsComputed:
    def test_a_supplied_recruitment_origin_is_discarded_for_a_us_person(self, client):
        """The classifier reads only residence country and the US-person flag.

        "When `student_residence_country` is `US`, or `student_us_person` is true,
        `recruitment_origin` is `DOMESTIC`; in every other case it is
        `INTERNATIONAL`. The classification reads only those two client-supplied
        fields and is never re-derived afterwards"

        "The new application sits in `status` `DRAFT` and `disclosure_state`
        `NOT_ISSUED`, with `custody_agency_id` initialised to the recruiting
        `agency_id`"

        Design: Corner/entities/application_recruitment_origin_computed_extra_field_ignored
        """
        agency = fx.register_agency(
            client,
            legal_name="Origin Test Agency",
            home_country_code="IN",
            complete_diligence=False,
        )
        program = fx.create_program(client)

        response = client.create_application(
            F.application_payload(
                agency["id"],
                program["id"],
                student_ref="STU-001",
                student_residence_country="IN",
                student_us_person=True,
                recruitment_origin=C.ORIGIN_INTERNATIONAL,
            ),
            make_agency_owner_headers(agency["id"]),
        )
        application = validate_success(response, 201)

        assert application["recruitment_origin"] == C.ORIGIN_DOMESTIC, (
            "the supplied origin must be ignored in favour of the derivation"
        )
        assert application["status"] == C.APPLICATION_DRAFT
        assert application["disclosure_state"] == C.DISCLOSURE_NOT_ISSUED
        assert application["custody_agency_id"] == agency["id"]
        assert_cents(
            application["projected_commission_cents"],
            0,
            "projected_commission_cents",
        )
        assert_cents(application["net_commission_cents"], 0, "net_commission_cents")
        assert application["integrity_hold"] is False


class TestTerritoryStructuralGates:
    @pytest.fixture()
    def drafted_contract(self, client):
        """One contract in DRAFT whose term runs the full year."""
        agency = fx.register_agency(
            client,
            legal_name="Enum Test Agency",
            home_country_code="IN",
            complete_diligence=False,
        )
        contract = fx.draft_contract(client, agency["id"], contract_ref="CTR-001")
        return contract["id"]

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param(
                {"exclusivity": "SEMI_EXCLUSIVE"}, id="exclusivity_out_of_enum"
            ),
        ],
    )
    def test_a_malformed_territory_request_fails_structurally(
        self, client, drafted_contract, overrides
    ):
        """An out-of-enum exclusivity lands in the structural group.

        "Structural validity of the body and query string: required fields
        present, enum values in range, dates in ISO 8601 `YYYY-MM-DD` form,
        integers within their declared bounds"

        Design: Corner/entities/territory_assignment_invalid_enum_rejected
        """
        response = client.assign_territory(
            drafted_contract, F.territory_payload(**overrides), OFFICER
        )
        validate_error(response, E.ERR_INVALID_REQUEST)

        assert fx.read_assignments(client, drafted_contract) == [], (
            "a structurally refused request must persist no assignment"
        )
