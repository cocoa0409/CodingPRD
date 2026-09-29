"""Error-catalogue corners: the 401 that pre-empts every other check, the empty
policy selector, and the one-404-code-per-identifier-family rule."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_fields_equal, assert_page
from test_helpers.test_users import SECRETARY, STAFF

# A well-formed UUID that never resolves, so every refusal below is an existence
# failure and never a malformed-identifier failure.
UNKNOWN_ID = NON_EXISTENT_UUID

# The clock starts at its published default, so this instant is strictly after it
# and a monotonic clock accepts it whenever a governing policy exists.
CLOCK_TARGET = "2026-09-01T00:00:00Z"

# An identity-free request: only the content type, neither X-User-ID nor X-User-Role.
NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}


def _seated_director(client):
    """One governing policy plus one SEATED director, so only ids under test are unknown."""
    X.adopt_policy(client)
    return X.new_seated_director(
        client,
        full_name="Real Director",
        email="real@issuer.example",
        birth_date="1968-01-01",
        appointed_on="2021-01-01",
    )


def test_a_write_without_identity_headers_is_unauthenticated_not_invalid_request(client):
    """A create call that carries neither identity header and an incomplete body is
    refused for the missing headers, not for the missing fields, and writes nothing.

    PRD: "If either header is missing or is present but empty, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/errors/missing_identity_headers_return_unauthenticated_before_anything_else
    """
    X.adopt_policy(client)

    response = client.create_director({"full_name": "No Headers"}, NO_IDENTITY_HEADERS)

    validate_error(response, E.ERR_UNAUTHENTICATED, 401)
    assert_page(client.list_directors(SECRETARY), expected_total=0)


def test_a_read_without_identity_headers_is_unauthenticated_not_not_found(client):
    """Reading an id that does not exist without identity headers reports the
    authentication failure, never the 404 the same path would give a named user.

    PRD: "Both `X-User-ID` and `X-User-Role` present and non-empty, else `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/missing_identity_headers_return_unauthenticated_before_anything_else
    """
    X.adopt_policy(client)

    response = client.get_director(UNKNOWN_ID, NO_IDENTITY_HEADERS)

    validate_error(response, E.ERR_UNAUTHENTICATED, 401)


def test_the_gap_analysis_read_is_refused_when_no_policy_has_ever_been_adopted(client):
    """On an empty database the computed read is an error envelope rather than a zeroed
    result, and the identical call succeeds once a policy is in force.

    PRD: "any request that needs a threshold is refused with `ERR_NO_ACTIVE_POLICY` (HTTP 409)"

    Design: Corner/errors/every_threshold_reading_endpoint_reports_no_active_policy_on_an_empty_database
    """
    refused = client.get_gap_analysis(STAFF)

    error = validate_error(refused, E.ERR_NO_ACTIVE_POLICY, 409)
    assert "board_gap_index" not in error, error

    X.adopt_policy(client)
    validate_success(client.get_gap_analysis(STAFF), 200)


def test_advancing_the_clock_is_refused_when_no_policy_has_ever_been_adopted(client):
    """The clock advance is one of the threshold-reading operations, so it is refused on
    an empty database, and the refusal leaves the clock where it was.

    PRD: "Nine operations depend on a threshold and therefore carry this refusal: submitting an independence screen, running conflict clearance on a candidate, adding a nominee to a slate, submitting a slate for review, recording a slate decision, creating a compensation award, seating a director, running the skills gap analysis, and advancing the logical clock."

    Design: Corner/errors/every_threshold_reading_endpoint_reports_no_active_policy_on_an_empty_database
    """
    refused = client.set_clock(F.clock_payload(CLOCK_TARGET), SECRETARY)

    validate_error(refused, E.ERR_NO_ACTIVE_POLICY, 409)

    X.adopt_policy(client)
    # Replaying the very same instant proves the refused call did not move the clock:
    # a clock already standing at CLOCK_TARGET would refuse it as non-monotonic.
    accepted = validate_success(client.set_clock(F.clock_payload(CLOCK_TARGET), SECRETARY), 200)
    assert_fields_equal(accepted, {"current_utc": CLOCK_TARGET, "recomputed_director_count": 0})


def test_each_path_identifier_family_reports_its_own_not_found_code(client):
    """The same unknown UUID addressed through fourteen different read paths returns the
    404 code bound to that path's own identifier type.

    PRD: "The full set of 404 codes, each bound to one identifier type"

    Design: Corner/errors/every_path_and_body_id_family_has_its_own_not_found_error
    """
    _seated_director(client)

    families = [
        (client.get_policy(UNKNOWN_ID, STAFF), E.ERR_POLICY_NOT_FOUND),
        (client.get_search_firm(UNKNOWN_ID, STAFF), E.ERR_SEARCH_FIRM_NOT_FOUND),
        (client.get_director(UNKNOWN_ID, STAFF), E.ERR_DIRECTOR_NOT_FOUND),
        (client.get_skill_rating(UNKNOWN_ID, STAFF), E.ERR_SKILL_RATING_NOT_FOUND),
        (client.get_screen(UNKNOWN_ID, STAFF), E.ERR_SCREEN_NOT_FOUND),
        (client.get_external_directorship(UNKNOWN_ID, STAFF), E.ERR_DIRECTORSHIP_NOT_FOUND),
        (client.get_interview(UNKNOWN_ID, STAFF), E.ERR_INTERVIEW_NOT_FOUND),
        (client.get_committee(UNKNOWN_ID, STAFF), E.ERR_COMMITTEE_NOT_FOUND),
        (client.get_assignment(UNKNOWN_ID, STAFF), E.ERR_ASSIGNMENT_NOT_FOUND),
        (client.get_slate(UNKNOWN_ID, STAFF), E.ERR_SLATE_NOT_FOUND),
        (client.get_slate_nominee(UNKNOWN_ID, STAFF), E.ERR_NOMINEE_NOT_FOUND),
        (client.get_vote(UNKNOWN_ID, STAFF), E.ERR_VOTE_NOT_FOUND),
        (client.get_onboarding_item(UNKNOWN_ID, STAFF), E.ERR_ONBOARDING_ITEM_NOT_FOUND),
        (client.get_comp_award(UNKNOWN_ID, STAFF), E.ERR_COMP_AWARD_NOT_FOUND),
    ]

    for response, expected_error_id in families:
        validate_error(response, expected_error_id, 404)


def test_body_identifier_families_report_their_own_not_found_codes(client):
    """An unknown identifier supplied in a request body resolves to the same per-family
    404 code as a path identifier does, and no row is written by the refused create.

    PRD: "Identifiers supplied in a request body rather than the path resolve to the same code set and the same HTTP 404."

    Design: Corner/errors/every_path_and_body_id_family_has_its_own_not_found_error
    """
    director = _seated_director(client)

    unknown_category = client.create_skill_rating(
        director["id"], F.skill_rating_payload(UNKNOWN_ID, self_rating=4), STAFF
    )
    unknown_company = client.create_external_directorship(
        F.external_directorship_payload(UNKNOWN_ID, director_id=director["id"]), STAFF
    )

    validate_error(unknown_category, E.ERR_SKILL_CATEGORY_NOT_FOUND, 404)
    validate_error(unknown_company, E.ERR_EXTERNAL_COMPANY_NOT_FOUND, 404)
    assert_page(client.list_skill_ratings(STAFF), expected_total=0)
    assert_page(client.list_external_directorships(STAFF), expected_total=0)
