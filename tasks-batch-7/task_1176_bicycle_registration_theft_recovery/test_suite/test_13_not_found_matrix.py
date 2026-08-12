"""Per-entity 404 matrix: every entity family reports its own typed not-found
error (PRD §2.6 stage 5)."""
import pytest
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    register_owner,
    owner_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]

# (uuid suffix, expected per-entity 404 error id)
_NOT_FOUND_GET_MATRIX = [
    ("00000000-0000-0000-0000-000000000001", "bicycles", ApiErrorId.ERR_BICYCLE_NOT_FOUND),
    ("00000000-0000-0000-0000-000000000002", "transfers", ApiErrorId.ERR_TRANSFER_NOT_FOUND),
    ("00000000-0000-0000-0000-000000000003", "recovery-intakes", ApiErrorId.ERR_RECOVERY_INTAKE_NOT_FOUND),
    ("00000000-0000-0000-0000-000000000004", "matches", ApiErrorId.ERR_MATCH_NOT_FOUND),
    ("00000000-0000-0000-0000-000000000005", "claims", ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ("00000000-0000-0000-0000-000000000006", "auctions", ApiErrorId.ERR_AUCTION_NOT_FOUND),
    ("00000000-0000-0000-0000-000000000007", "events", ApiErrorId.ERR_EVENT_NOT_FOUND),
    ("00000000-0000-0000-0000-000000000008", "event-registrations", ApiErrorId.ERR_EVENT_REGISTRATION_NOT_FOUND),
    ("00000000-0000-0000-0000-000000000009", "duplicate-flags", ApiErrorId.ERR_DUPLICATE_FLAG_NOT_FOUND),
    ("00000000-0000-0000-0000-00000000000a", "notifications", ApiErrorId.ERR_NOTIFICATION_NOT_FOUND),
    ("00000000-0000-0000-0000-00000000000b", "partner-orgs", ApiErrorId.ERR_PARTNER_ORG_NOT_FOUND),
]


class TestNotFoundMatrix:
    @pytest.mark.parametrize(
        "uuid,collection,expected_error",
        _NOT_FOUND_GET_MATRIX,
        ids=[entry[1] for entry in _NOT_FOUND_GET_MATRIX],
    )
    def test_not_found_matrix_remaining_entities(self, api, uuid, collection, expected_error):
        """PRD §2.6: "each identifier in the URL path must resolve to an existing
        row, checked sequentially from the leftmost segment; the first unresolvable
        segment produces its entity-specific 404: `ERR_OWNER_NOT_FOUND`,
        `ERR_PARTNER_ORG_NOT_FOUND`, `ERR_BICYCLE_NOT_FOUND`,
        `ERR_TRANSFER_NOT_FOUND`, `ERR_THEFT_REPORT_NOT_FOUND`,
        `ERR_RECOVERY_INTAKE_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_AUCTION_NOT_FOUND`, `ERR_BID_NOT_FOUND`,
        `ERR_EVENT_NOT_FOUND`, `ERR_EVENT_REGISTRATION_NOT_FOUND`,
        `ERR_DUPLICATE_FLAG_NOT_FOUND`, or `ERR_NOTIFICATION_NOT_FOUND`."

        Design: Corner/errors/not_found_matrix_remaining_entities
        """
        resp = api._request("GET", f"/registry/{collection}/{uuid}", headers=REGISTRAR)
        validate_error(resp, expected_error, expected_status=404)

    def test_not_found_matrix_bid_retract(self, api):
        """PRD §2.6: "the first unresolvable segment produces its entity-specific
        404:" — for the Bid family that is `ERR_BID_NOT_FOUND`.

        The Bid family is exercised through its action endpoint (retract).

        Design: Corner/errors/not_found_matrix_remaining_entities
        """
        owner = register_owner("o1@x.com", "O One")
        resp = api.retract_bid(
            "00000000-0000-0000-0000-00000000000c", owner_headers(owner)
        )
        validate_error(resp, ApiErrorId.ERR_BID_NOT_FOUND, expected_status=404)
