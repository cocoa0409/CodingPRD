"""One envelope for every status class, and one code for every schema fault."""

import pytest

from test_helpers import (
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    TREASURER_HEADERS,
    ApiErrorId,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

SOLO_TIER = {
    "code": "SOLO",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
NO_GUARANTEE = {"guaranteed_player_count": 0}
ENVELOPE_OUTING = {"name": "Envelope Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
SECOND_COURSE = {"course_name": "Second Course GC", "rate_per_player_cents": 8000,
                 "guaranteed_player_count": 0}
ENTITY_LEAKS = ("id", "version", "name", "status", "outing_id", "created_at", "updated_at")


def assert_error_envelope(response) -> dict:
    """Every 4xx body must carry the declared error envelope and nothing else."""
    body = response.json()
    assert set(body) == {"meta", "response_type", "data"}
    assert body["response_type"] == "error"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert set(body["data"]) == {"error_id", "message"}
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip() != ""
    return body["data"]


class TestOneErrorEnvelopeAcrossStatusClasses:
    def _an_open_outing_with_one_unpaid_package(self, api):
        ctx = fx.open_outing(api, outing=ENVELOPE_OUTING, contract=NO_GUARANTEE, tier=SOLO_TIER)
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Envelope Buyer",
            player_count=1,
        )
        ctx["registration_id"] = registration["id"]
        return ctx

    def _four_rejections(self, api, ctx):
        missing_beneficiary = {
            key: value
            for key, value in f.outing_payload(name="No Beneficiary").items()
            if key != "beneficiary_name"
        }
        return {
            422: (
                api.create_outing(missing_beneficiary, DIRECTOR_HEADERS),
                ApiErrorId.INVALID_REQUEST,
            ),
            404: (
                api.get_outing(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
                ApiErrorId.OUTING_NOT_FOUND,
            ),
            409: (
                api.create_contract(
                    f.contract_payload(ctx["outing_id"], **SECOND_COURSE), COURSE_HEADERS
                ),
                ApiErrorId.CONTRACT_ALREADY_EXISTS,
            ),
            402: (
                api.record_registration_payment(
                    ctx["registration_id"], f.payment_payload(29999), TREASURER_HEADERS
                ),
                ApiErrorId.PAYMENT_AMOUNT_MISMATCH,
            ),
        }

    def test_four_status_classes_come_back_in_the_identical_shape(self, api):
        """The error shape is fixed for every class: "All error API responses (4xx status
        codes) follow this standard envelope format", where "The `meta` object for error
        responses contains only `api_request_id` and `api_request_timestamp`", "The
        `error_id` is a unique, machine-readable string that identifies the specific
        error", and "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/errors/every_rejection_uses_the_same_error_envelope_across_status_classes
        """
        ctx = self._an_open_outing_with_one_unpaid_package(api)
        rejections = self._four_rejections(api, ctx)

        for status, (response, expected_error) in rejections.items():
            assert response.status_code == status
            data = assert_error_envelope(response)
            assert data["error_id"] == expected_error.value
            validate_error(response, expected_error, status)

    def test_a_rejected_write_leaks_no_row_and_changes_no_state(self, api):
        """Because the error body holds only the two declared keys, a refused create cannot
        return a partial row, and none of the four refusals is allowed to move the state
        it addressed - the payment mismatch in particular leaves the registration where it
        was, since the payload carries "a single `amount_cents`, which must equal the held
        tier's `price_cents` to the cent, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP
        402)".

        Design: Corner/errors/every_rejection_uses_the_same_error_envelope_across_status_classes
        """
        ctx = self._an_open_outing_with_one_unpaid_package(api)
        rejections = self._four_rejections(api, ctx)

        for response, _ in rejections.values():
            data = assert_error_envelope(response)
            for leaked in ENTITY_LEAKS:
                assert leaked not in data

        registration = fx.read_registration(api, ctx["registration_id"])
        assert registration["status"] == "PENDING_PAYMENT"
        assert registration["amount_paid_cents"] == 0

        _, contracts_meta = validate_paginated(
            api.list_contracts(COURSE_HEADERS, outing_id=ctx["outing_id"])
        )
        assert contracts_meta["total_count"] == 1

        _, outings_meta = validate_paginated(api.list_outings(DIRECTOR_HEADERS))
        assert outings_meta["total_count"] == 1


SCHEMA_OUTING = {"name": "Schema Faults Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
SCHEMA_FAULTS = (
    "a_required_field_is_absent",
    "an_enum_value_is_not_a_member",
    "a_cents_field_is_negative",
    "a_timestamp_has_no_trailing_z",
    "an_array_that_must_be_non_empty_is_empty",
    "a_computed_field_is_written",
)


class TestSixSchemaFaultsCollapseToOneCode:
    def _an_open_outing_to_write_against(self, api):
        return fx.open_outing(api, outing=SCHEMA_OUTING, contract=NO_GUARANTEE, tier=SOLO_TIER)

    def _fault(self, api, ctx, fault):
        if fault == "a_required_field_is_absent":
            payload = {
                key: value
                for key, value in f.registration_payload(
                    ctx["outing_id"], ctx["tier_id"], player_count=1
                ).items()
                if key != "buyer_name"
            }
            return api.create_registration(payload, DIRECTOR_HEADERS)
        if fault == "an_enum_value_is_not_a_member":
            return api.create_package_tier(
                f.package_tier_payload(
                    ctx["outing_id"], code="ODD", kind="FOURSOME", price_cents=30000,
                    player_slots=1,
                ),
                DIRECTOR_HEADERS,
            )
        if fault == "a_cents_field_is_negative":
            return api.create_package_tier(
                f.package_tier_payload(
                    ctx["outing_id"], code="NEG", kind="INDIVIDUAL", price_cents=-1,
                    player_slots=1,
                ),
                DIRECTOR_HEADERS,
            )
        if fault == "a_timestamp_has_no_trailing_z":
            return api.create_outing(
                f.outing_payload(
                    name="Naive Timestamp", scheduled_date="2026-09-19T12:00:00"
                ),
                DIRECTOR_HEADERS,
            )
        if fault == "an_array_that_must_be_non_empty_is_empty":
            return api.create_team(
                f.team_payload(ctx["outing_id"], [], team_name="Nobody"), DIRECTOR_HEADERS
            )
        return api.create_outing(
            f.outing_payload(
                name="Computed Write", confirmed_player_slots=8, net_proceeds_cents=999999
            ),
            DIRECTOR_HEADERS,
        )

    @pytest.mark.parametrize("fault", SCHEMA_FAULTS)
    def test_each_fault_is_reported_as_the_one_schema_code(self, api, fault):
        """The schema layer absorbs six unrelated faults under a single identifier: requests
        are rejected with `ERR_INVALID_REQUEST` "when a required input is absent, when an
        enum-typed input carries a value outside its declared set, when a value has the
        wrong type, when a field whose name ends in `_cents` or `_count` is supplied as a
        negative number, when a timestamp is not ISO 8601 UTC with a trailing `Z`, when an
        array that must be non-empty is empty, or when the body attempts to write a field
        that the server computes or manages itself."

        Design: Corner/errors/six_distinct_schema_faults_all_collapse_to_invalid_request
        """
        ctx = self._an_open_outing_to_write_against(api)
        validate_error(self._fault(api, ctx, fault), ApiErrorId.INVALID_REQUEST, 422)

    def test_the_empty_roster_reports_the_schema_code_and_leaves_nothing_behind(self, api):
        """`ERR_TEAM_SIZE_INVALID` also claims the empty roster, because "The `player_ids`
        array must be non-empty, must not be longer than four, and must not be longer than
        the `player_count` of the registration that funded the players", but the schema
        tier is evaluated first: "the body and query conform as described in §2.5,
        otherwise `ERR_INVALID_REQUEST`".  None of the six rejected writes may leave a row
        behind.

        Design: Corner/errors/six_distinct_schema_faults_all_collapse_to_invalid_request
        """
        ctx = self._an_open_outing_to_write_against(api)

        validate_error(
            self._fault(api, ctx, "an_array_that_must_be_non_empty_is_empty"),
            ApiErrorId.INVALID_REQUEST,
            422,
        )
        for fault in SCHEMA_FAULTS:
            validate_error(self._fault(api, ctx, fault), ApiErrorId.INVALID_REQUEST, 422)

        _, teams_meta = validate_paginated(
            api.list_teams(DIRECTOR_HEADERS, outing_id=ctx["outing_id"])
        )
        assert teams_meta["total_count"] == 0

        _, tiers_meta = validate_paginated(
            api.list_package_tiers(DIRECTOR_HEADERS, outing_id=ctx["outing_id"])
        )
        assert tiers_meta["total_count"] == 1

        outings, outings_meta = validate_paginated(api.list_outings(DIRECTOR_HEADERS))
        assert outings_meta["total_count"] == 1
        assert {row["name"] for row in outings} == {"Schema Faults Open"}
