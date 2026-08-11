"""Survey expiry and coverage-verification cascades onto leads (PRD §3.3)."""
from test_helpers import (
    TEST_USERS,
    assert_lead,
    create_config,
    create_coverage_payload,
    create_lead,
    create_member,
    get_success_data,
    make_member_self_headers,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

COB = TEST_USERS["cob_analyst_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_error_survey_expired(api):
    """PRD §3.3: "Responding requires the current clock to be on or before
    `due_at` — a late response is rejected with `ERR_SURVEY_EXPIRED` (HTTP 409)".
    The clock advance also auto-expires the still-SENT survey per PRD §2.6:
    "every MemberSurvey still in `SENT` status whose `due_at` is earlier than the
    new clock transitions to `EXPIRED`", so an implementation that gates on state
    surfaces the §2.9 family-4 state rejection for the same late response; both
    outcomes are the 409 rejection of a response past `due_at`.

    Design: Corner/errors/error_survey_expired
    """
    create_config()
    set_clock("2026-05-01T00:00:00Z")
    member = create_member()
    survey = get_success_data(api.create_survey(member["id"], COB))
    assert survey["status"] == "SENT"

    set_clock("2026-07-01T00:00:00Z")
    res = api.respond_survey(
        member["id"], survey["id"], {"response_payload": "yes"},
        make_member_self_headers(member["id"]),
    )
    actual = validate_error_is_one_of(res, ["ERR_SURVEY_EXPIRED", "ERR_INVALID_STATE"])
    assert res.status_code == 409


def test_coverage_verify_cascade_to_lead(api):
    """PRD §3.3: "On successful verification the coverage transitions from
    `PENDING_VERIFICATION` to `VERIFIED`, the member's `other_coverage_count` is
    recomputed (counting only `VERIFIED` coverages and excluding `OUR_PLAN` ones),
    any linked lead transitions from `RECEIVED` to `VERIFIED_COVERAGE`, and both
    the coverage's and the member's `version` increment."

    Design: Difficulty/transitive_cascade/coverage_verify_cascade_to_lead_and_member
    """
    create_config()
    member = create_member()
    lead = create_lead(member["id"], source="DATA_MATCH_CMS")
    assert lead["disposition"] == "RECEIVED"

    coverage = get_success_data(api.create_coverage(
        member["id"], create_coverage_payload(verification_source="DATA_MATCH_CMS"), COB,
    ))
    verified = validate_success(
        api.verify_coverage(member["id"], coverage["id"], COB), 200
    )
    assert verified["verification_status"] == "VERIFIED"

    lead_after = validate_success(api.get_lead(member["id"], lead["id"], COB), 200)
    assert_lead(lead_after)
    assert lead_after["disposition"] == "VERIFIED_COVERAGE"


def test_coverage_verify_recomputes_other_coverage_count(api):
    """PRD §3.3: "the member's `other_coverage_count` is recomputed (counting only
    `VERIFIED` coverages and excluding `OUR_PLAN` ones)".

    Design: Difficulty/transitive_cascade/coverage_verify_cascade_to_lead_and_member
    """
    create_config()
    member = create_member()
    create_lead(member["id"], source="DATA_MATCH_CMS")
    coverage = get_success_data(api.create_coverage(
        member["id"], create_coverage_payload(verification_source="DATA_MATCH_CMS"), COB,
    ))

    before = validate_success(api.get_member(member["id"], COB), 200)
    assert before["other_coverage_count"] == 0

    get_success_data(api.verify_coverage(member["id"], coverage["id"], COB))
    after = validate_success(api.get_member(member["id"], COB), 200)
    assert after["other_coverage_count"] == 1
