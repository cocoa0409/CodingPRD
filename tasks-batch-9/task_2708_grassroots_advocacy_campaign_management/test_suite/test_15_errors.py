"""The not-found catalogue is per collection, on reads and on write targets.

Twelve entity families each own a 404 code, and the existence check runs
before every state, consent and body-shape rule, so a missing target is never
reported as a generic campaign miss or as a malformed request.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTION_RECORD_NOT_FOUND,
    ERR_ACTIVATION_NOT_FOUND,
    ERR_ENDORSEMENT_NOT_FOUND,
    ERR_MEETING_NOT_FOUND,
    ERR_MILESTONE_NOT_FOUND,
    ERR_PARTNER_NOT_FOUND,
    ERR_SEGMENT_NOT_FOUND,
    ERR_SPOKESPERSON_NOT_FOUND,
    ERR_SUPPORTER_NOT_FOUND,
    ERR_VARIANT_NOT_FOUND,
)
from test_helpers.assertions import assert_page
from test_helpers.test_users import (
    make_campaign_director_headers,
    make_field_organizer_headers,
    make_message_strategist_headers,
)


def test_six_unknown_read_paths_answer_with_six_distinct_not_found_codes(api):
    """The 404 catalogue is per entity family, with no generic fallback.

    PRD: "Twelve entity families each have their own HTTP 404 code: `ERR_CAMPAIGN_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_LEGISLATOR_NOT_FOUND`, `ERR_SUPPORTER_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`, `ERR_ENDORSEMENT_NOT_FOUND`, `ERR_ACTIVATION_NOT_FOUND`, `ERR_ACTION_RECORD_NOT_FOUND`, `ERR_SPOKESPERSON_NOT_FOUND` and `ERR_MEETING_NOT_FOUND`."

    PRD: "3. **Path existence.** Every identifier in the URL path resolves, checked left to right in path order — otherwise the matching not-found code from §2.6."

    Design: Corner/errors/every_unknown_read_path_id_returns_its_own_not_found_code
    """
    fx.park_clock(api)
    director = make_campaign_director_headers()

    validate_error(api.get_milestone(C.UNKNOWN_UUID, headers=director),
                   ERR_MILESTONE_NOT_FOUND, expected_status=404)
    validate_error(api.get_endorsement(C.UNKNOWN_UUID, headers=director),
                   ERR_ENDORSEMENT_NOT_FOUND, expected_status=404)
    validate_error(api.get_activation(C.UNKNOWN_UUID, headers=director),
                   ERR_ACTIVATION_NOT_FOUND, expected_status=404)
    validate_error(api.get_action_record(C.UNKNOWN_UUID, headers=director),
                   ERR_ACTION_RECORD_NOT_FOUND, expected_status=404)
    validate_error(api.get_spokesperson(C.UNKNOWN_UUID, headers=director),
                   ERR_SPOKESPERSON_NOT_FOUND, expected_status=404)
    validate_error(api.get_meeting(C.UNKNOWN_UUID, headers=director),
                   ERR_MEETING_NOT_FOUND, expected_status=404)


def test_four_unknown_write_targets_answer_before_any_later_rule(api):
    """Existence at rung 4 outranks the state and shape rules behind it.

    PRD: "4. **Body foreign-key existence.** Every foreign key supplied in the request body resolves, checked in the field order the endpoint declares — otherwise the matching not-found code."

    PRD: "Foreign keys supplied in a request body are resolved after all path parameters, in the field order the endpoint declares its input list, and each carries the same entity-specific 404 code."

    Design: Corner/errors/every_unknown_write_target_returns_its_own_not_found_code
    """
    fx.park_clock(api)

    validate_error(
        api.refresh_segment(C.UNKNOWN_UUID,
                            headers=make_message_strategist_headers()),
        ERR_SEGMENT_NOT_FOUND, expected_status=404)
    validate_error(
        api.submit_variant(C.UNKNOWN_UUID,
                           F.variant_submit_payload(
                               submission_note="ready for review"),
                           headers=make_message_strategist_headers()),
        ERR_VARIANT_NOT_FOUND, expected_status=404)
    validate_error(
        api.withdraw_partner(C.UNKNOWN_UUID,
                             F.partner_withdraw_payload(
                                 withdraw_reason="board vote reversed"),
                             headers=make_campaign_director_headers()),
        ERR_PARTNER_NOT_FOUND, expected_status=404)
    validate_error(
        api.get_supporter(C.UNKNOWN_UUID,
                          headers=make_field_organizer_headers()),
        ERR_SUPPORTER_NOT_FOUND, expected_status=404)

    director = make_campaign_director_headers()
    assert_page(api.list_segments(headers=director), expected_total=0,
                expected_len=0)
    assert_page(api.list_variants(headers=director), expected_total=0,
                expected_len=0)
    assert_page(api.list_partners(headers=director), expected_total=0,
                expected_len=0)
    assert_page(api.list_supporters(headers=director), expected_total=0,
                expected_len=0)
