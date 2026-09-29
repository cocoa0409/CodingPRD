"""Error catalogue shape: the authentication floor, code specificity and code reuse.

Three properties of the catalogue are pinned here.  The authentication rung
sits under everything, so a malformed identity is reported as an
authentication failure even when the addressed row does not exist and even
when the declared capacity would have been refused anyway.  Six of the eight
not-found codes are shown to be genuinely distinct rather than one generic
404 wearing different labels.  And one state-machine code is shown to be
deliberately shared by three different placement operations, keyed only on
the row's current status.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_all_distinct,
    assert_cents,
    assert_entry_types,
    assert_error,
    assert_ok,
    assert_page,
)
from test_helpers.constants import NON_EXISTENT_UUID
from test_helpers.test_users import MOVE_OPS_AGENT_USER_ID, make_headers
from test_helpers.types import LedgerEntryType, PlacementStatus, UtilityType


# ---------------------------------------------------------------------------
# The authentication floor
# ---------------------------------------------------------------------------
def test_01_a_request_carrying_no_headers_at_all_is_unauthenticated(api, ops_headers):
    """A read that would have succeeded is refused outright when both headers are absent.

    PRD: "If either header is absent, or if `X-User-Role` is any string outside
    that set of eight, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/errors/error_shape_missing_auth_header_or_unknown_role_returns_401_unauthenticated
    """
    network = fixtures.build_network(api)
    move = fixtures.ingest_move(api, network)
    assert_ok(api.get_move(move["id"], ops_headers))

    response = api.raw_request("GET", f"/moves/{move['id']}")

    assert_error(response, ApiErrorId.UNAUTHENTICATED, expected_status=401)


def test_02_either_header_on_its_own_is_still_unauthenticated(api):
    """Half an identity is no identity: role-only and id-only both return 401.

    PRD: "Every request — read or write — must carry two headers."
    PRD: "If either header is absent, or if `X-User-Role` is any string outside
    that set of eight, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/errors/error_shape_missing_auth_header_or_unknown_role_returns_401_unauthenticated
    """
    network = fixtures.build_network(api)
    move = fixtures.ingest_move(api, network)

    role_only = api.raw_request(
        "GET", f"/moves/{move['id']}", headers={"X-User-Role": "MoveOpsAgent"}
    )
    assert_error(role_only, ApiErrorId.UNAUTHENTICATED, expected_status=401)

    id_only = api.raw_request(
        "GET", f"/moves/{move['id']}", headers={"X-User-ID": MOVE_OPS_AGENT_USER_ID}
    )
    assert_error(id_only, ApiErrorId.UNAUTHENTICATED, expected_status=401)


def test_03_an_undeclared_role_string_is_unauthenticated_not_forbidden(api):
    """A well-formed pair naming a role outside the eight is an authentication failure.

    PRD: "Exactly eight roles are recognised, spelled precisely as follows:
    `PlatformAdmin`, `FeedIntegrator`, `MoveOpsAgent`, `ComplianceOfficer`,
    `Resident`, `ProviderAgent`, `PartnerAgent`, and `ExternalServiceGateway`."
    PRD: "If the headers are well-formed but the declared role is not authorised
    for the endpoint being addressed — or the endpoint is one that a role holds
    exclusively and the caller is not among its holders — the rejection is
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/errors/error_shape_missing_auth_header_or_unknown_role_returns_401_unauthenticated
    """
    network = fixtures.build_network(api)
    move = fixtures.ingest_move(api, network)

    response = api.get_move(move["id"], make_headers(MOVE_OPS_AGENT_USER_ID, "RelocationAuditor"))

    assert_error(response, ApiErrorId.UNAUTHENTICATED, expected_status=401)


def test_04_the_authentication_rung_outranks_the_not_found_rung(api):
    """An unknown role addressing an id that does not exist still returns 401, not 404.

    PRD: "1. Both `X-User-ID` and `X-User-Role` are present and `X-User-Role` is
    one of the eight declared roles — otherwise `ERR_UNAUTHENTICATED` (401).
    Applies to every endpoint."
    PRD: "3. Every identifier in the request path resolves, left to right, to an
    existing row — otherwise the matching not-found error of §2.6 (404)."

    Design: Corner/errors/error_shape_missing_auth_header_or_unknown_role_returns_401_unauthenticated
    """
    anonymous = api.raw_request("GET", f"/moves/{NON_EXISTENT_UUID}")
    assert_error(anonymous, ApiErrorId.UNAUTHENTICATED, expected_status=401)

    unknown_role = api.get_move(
        NON_EXISTENT_UUID, make_headers(MOVE_OPS_AGENT_USER_ID, "RelocationAuditor")
    )
    assert_error(unknown_role, ApiErrorId.UNAUTHENTICATED, expected_status=401)


def test_05_a_write_refused_at_the_authentication_rung_changes_nothing(api, admin_headers):
    """Mapping under an undeclared role returns 401 and creates no service order.

    PRD: "1. Both `X-User-ID` and `X-User-Role` are present and `X-User-Role` is
    one of the eight declared roles — otherwise `ERR_UNAUTHENTICATED` (401).
    Applies to every endpoint."
    PRD: "Provider mapping, attention clearance, move completion, order
    scheduling, credit-check dispatch, order waiver and referral placement are
    reserved to `MoveOpsAgent` and `PlatformAdmin`."

    Design: Corner/errors/error_shape_missing_auth_header_or_unknown_role_returns_401_unauthenticated
    """
    bundle = fixtures.verified_move(api)

    response = api.run_provider_mapping(
        bundle["move"]["id"],
        factories.mapping_payload([UtilityType.ELECTRIC.value]),
        make_headers(MOVE_OPS_AGENT_USER_ID, "RelocationAuditor"),
    )

    assert_error(response, ApiErrorId.UNAUTHENTICATED, expected_status=401)
    assert_page(
        api.list_utility_orders(admin_headers, move_id=bundle["move"]["id"]),
        total_count=0,
        has_more=False,
    )


# ---------------------------------------------------------------------------
# Six of the eight not-found codes are genuinely distinct
# ---------------------------------------------------------------------------
def test_06_three_resource_families_each_report_their_own_not_found_code(api, admin_headers):
    """Residents, verifications and handoffs each miss with their own 404 code.

    PRD: "A missing move yields `ERR_MOVE_NOT_FOUND`, a missing resident
    `ERR_RESIDENT_NOT_FOUND`, a missing service order
    `ERR_UTILITY_ORDER_NOT_FOUND`, a missing credit-check handoff
    `ERR_HANDOFF_NOT_FOUND`, a missing postal filing `ERR_FILING_NOT_FOUND`, a
    missing referral placement `ERR_PLACEMENT_NOT_FOUND`, a missing consent
    record `ERR_CONSENT_NOT_FOUND`, and a missing identity verification
    `ERR_VERIFICATION_NOT_FOUND`. All eight carry HTTP 404."

    Design: Corner/errors/error_code_specificity_six_unknown_path_ids_return_six_distinct_not_found_codes
    """
    assert_error(
        api.get_resident(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.RESIDENT_NOT_FOUND,
        expected_status=404,
    )
    assert_error(
        api.get_identity_verification(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.VERIFICATION_NOT_FOUND,
        expected_status=404,
    )
    assert_error(
        api.get_credit_check_handoff(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.HANDOFF_NOT_FOUND,
        expected_status=404,
    )


def test_07_the_other_three_resource_families_do_the_same(api, admin_headers):
    """Filings, placements and consent records also carry their own 404 codes.

    PRD: "a missing postal filing `ERR_FILING_NOT_FOUND`, a missing referral
    placement `ERR_PLACEMENT_NOT_FOUND`, a missing consent record
    `ERR_CONSENT_NOT_FOUND`"
    PRD: "All eight carry HTTP 404."

    Design: Corner/errors/error_code_specificity_six_unknown_path_ids_return_six_distinct_not_found_codes
    """
    assert_error(
        api.get_filing(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.FILING_NOT_FOUND,
        expected_status=404,
    )
    assert_error(
        api.get_placement(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.PLACEMENT_NOT_FOUND,
        expected_status=404,
    )
    assert_error(
        api.get_consent_record(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.CONSENT_NOT_FOUND,
        expected_status=404,
    )


def test_08_the_same_unknown_identifier_yields_six_pairwise_distinct_codes(api, admin_headers):
    """One identifier against six paths produces six different error ids, all 404.

    PRD: "Path identifiers are resolved strictly left to right, and the first
    identifier that fails to resolve decides the error"
    PRD: "All eight carry HTTP 404."

    Design: Corner/errors/error_code_specificity_six_unknown_path_ids_return_six_distinct_not_found_codes
    """
    responses = [
        api.get_resident(NON_EXISTENT_UUID, admin_headers),
        api.get_identity_verification(NON_EXISTENT_UUID, admin_headers),
        api.get_credit_check_handoff(NON_EXISTENT_UUID, admin_headers),
        api.get_filing(NON_EXISTENT_UUID, admin_headers),
        api.get_placement(NON_EXISTENT_UUID, admin_headers),
        api.get_consent_record(NON_EXISTENT_UUID, admin_headers),
    ]

    codes = []
    for response in responses:
        assert response.status_code == 404, (
            f"an unresolved path identifier must be a 404, got {response.status_code}"
        )
        codes.append(response.json()["data"]["error_id"])

    assert_all_distinct(codes)
    assert len(codes) == 6, f"expected six probes, got {len(codes)}"


# ---------------------------------------------------------------------------
# One placement code, three operations, keyed purely on state
# ---------------------------------------------------------------------------
def test_09_converting_a_placement_that_was_never_accepted_is_not_convertible(api, admin_headers):
    """Conversion straight from PLACED is refused and the placement keeps its status.

    PRD: "acceptance from `PLACED`, decline from `ACCEPTED`, conversion from
    `ACCEPTED`, settlement from `CONVERTED`, reversal from `CONVERTED` —
    otherwise `ERR_PLACEMENT_NOT_CONVERTIBLE` (409)"

    Design: Corner/errors/error_reuse_one_code_covers_three_placement_operations_and_is_state_only
    """
    partner = fixtures.add_insurance_partner(api)
    bundle = fixtures.placed_referral(api, partner=partner)

    response = api.convert_placement(
        bundle["placement"]["id"], factories.conversion_payload(), admin_headers
    )
    assert_error(response, ApiErrorId.PLACEMENT_NOT_CONVERTIBLE, expected_status=409)

    unchanged = assert_ok(api.get_placement(bundle["placement"]["id"], admin_headers))
    assert unchanged["placement_status"] == PlacementStatus.PLACED.value, (
        f"the placement must still be PLACED, got {unchanged['placement_status']}"
    )


def test_10_settlement_and_reversal_from_placed_reuse_the_very_same_code(api, admin_headers):
    """Three different operations on the same PLACED row all return one shared code.

    PRD: "acceptance from `PLACED`, decline from `ACCEPTED`, conversion from
    `ACCEPTED`, settlement from `CONVERTED`, reversal from `CONVERTED` —
    otherwise `ERR_PLACEMENT_NOT_CONVERTIBLE` (409)"
    PRD: "A settled placement is terminal and is not reversible."

    Design: Corner/errors/error_reuse_one_code_covers_three_placement_operations_and_is_state_only
    """
    partner = fixtures.add_insurance_partner(api)
    bundle = fixtures.placed_referral(api, partner=partner)
    placement_id = bundle["placement"]["id"]

    assert_error(
        api.convert_placement(placement_id, factories.conversion_payload(), admin_headers),
        ApiErrorId.PLACEMENT_NOT_CONVERTIBLE,
        expected_status=409,
    )
    assert_error(
        api.settle_placement(placement_id, factories.settlement_payload(), admin_headers),
        ApiErrorId.PLACEMENT_NOT_CONVERTIBLE,
        expected_status=409,
    )
    assert_error(
        api.reverse_placement(placement_id, factories.reversal_payload(), admin_headers),
        ApiErrorId.PLACEMENT_NOT_CONVERTIBLE,
        expected_status=409,
    )

    assert_page(
        api.list_ledger_entries(admin_headers, placement_id=placement_id),
        total_count=0,
        has_more=False,
    )


def test_11_the_identical_conversion_succeeds_once_the_state_permits_it(api, admin_headers):
    """Acceptance alone turns the refused conversion into a flat-bounty accrual.

    PRD: "under a `FLAT_BOUNTY` payout model the commission is simply the
    partner's `bounty_cents`, independent of the reported revenue"
    PRD: "Conversion posts an `ACCRUAL` entry whose `amount_cents` is the
    positive commission and a `FEED_SOURCE_SHARE` entry whose `amount_cents` is
    the negative of the feed source's cut."

    Design: Corner/errors/error_reuse_one_code_covers_three_placement_operations_and_is_state_only
    """
    partner = fixtures.add_insurance_partner(api)
    bundle = fixtures.placed_referral(api, partner=partner)
    payload = factories.conversion_payload()
    assert_error(
        api.convert_placement(bundle["placement"]["id"], payload, admin_headers),
        ApiErrorId.PLACEMENT_NOT_CONVERTIBLE,
    )

    assert_ok(api.accept_placement(bundle["placement"]["id"], {}, admin_headers))
    converted = assert_ok(api.convert_placement(bundle["placement"]["id"], payload, admin_headers))

    assert converted["placement_status"] == PlacementStatus.CONVERTED.value, (
        f"expected CONVERTED, got {converted['placement_status']}"
    )
    assert_cents(converted, "attributed_share_cents", 5000)
    assert_cents(converted, "feed_source_share_cents", 875)

    entries = assert_page(
        api.list_ledger_entries(admin_headers, placement_id=bundle["placement"]["id"]),
        total_count=2,
        has_more=False,
    )
    assert_entry_types(
        entries, [LedgerEntryType.ACCRUAL.value, LedgerEntryType.FEED_SOURCE_SHARE.value]
    )
