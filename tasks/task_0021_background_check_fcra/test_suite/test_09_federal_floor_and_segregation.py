"""Federal floor on pre_adverse_waiting_days, segregation of duties on
finalize, earliest_final_at calculation, and required-field rejection.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock,
    order_complete_consider_with_adverse_action,
    make_compliance_officer_headers, CO, PA,
)
from test_helpers.fixtures import api_client


def test_jurisdiction_with_pre_adverse_waiting_days_four_rejected_five_accepted(api):
    """pre_adverse_waiting_days must be at least 5 (federal floor). A value
    of 4 is rejected with ERR_BELOW_FEDERAL_FLOOR; a value of 5 is
    accepted.

    PRD §2.8: "The federal minimum waiting period is five calendar days;
    a jurisdiction created or updated with a `pre_adverse_waiting_days`
    value below 5 is rejected with `ERR_BELOW_FEDERAL_FLOOR` (HTTP 422)."
    PRD §3.1: "`pre_adverse_waiting_days` (an integer, default 5, that
    must be at least 5 — the FCRA federal floor; lower values are
    rejected with `ERR_BELOW_FEDERAL_FLOOR`)."

    Design: Difficulty/boundary_precision_check/federal_floor_pre_adverse_days_5_succeeds_4_rejected
    """
    set_clock("2026-06-01T10:00:00.000Z")
    # 4 days → ERR_BELOW_FEDERAL_FLOOR.
    bad = api.create_jurisdiction({"state_code": "ID", "pre_adverse_waiting_days": 4}, PA)
    validate_error(bad, ApiErrorId.ERR_BELOW_FEDERAL_FLOOR.value)
    # 5 days → accepted.
    ok = api.create_jurisdiction({"state_code": "ID", "pre_adverse_waiting_days": 5}, PA)
    jur = validate_success(ok, 201)
    assert jur["pre_adverse_waiting_days"] == 5, \
        f"5 days must be accepted, got {jur['pre_adverse_waiting_days']!r}"


def test_finalize_by_recruiter_who_extended_conditional_offer_rejected_segregation(api):
    """If the ComplianceOfficer's X-User-ID equals the Recruiter X-User-ID
    that issued the conditional offer, the finalize is rejected with
    ERR_SEGREGATION_OF_DUTIES.

    PRD §2.7: "Finalizing an Adverse Action requires that the Compliance
    Officer issuing the finalize be a different operator from the
    Recruiter who extended the parent application's conditional offer.
    The conditional-offer audit row captures the Recruiter's `X-User-ID`;
    on the finalize call the server compares the acting `X-User-ID`
    against that recorded operator. If the two are equal, the finalize
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."
    PRD §3.6: "Third, the acting `X-User-ID` must differ from the
    Recruiter `X-User-ID` recorded on the parent application's
    conditional-offer audit row; a match is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/error_segregation_of_duties_blocks_recruiter_finalizing_own_offer
    """
    # The fixture extends the conditional offer with X-User-ID="shared-actor".
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="ND",
                                                    recruiter_id="shared-actor",
                                                    crim_payload={"hits": 1})
    )
    # Advance clock past waiting period so the SoD check is the failing one.
    set_clock("2026-06-06T10:00:00.000Z")
    # ComplianceOfficer finalizing with the same X-User-ID.
    co_same_headers = make_compliance_officer_headers("shared-actor")
    resp = api.finalize_adverse_action(
        aa["id"], {"expected_adverse_action_version": aa["version"]}, co_same_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_earliest_final_at_uses_jurisdiction_waiting_days_above_floor(api):
    """When pre_adverse_waiting_days = 7 (above the 5-day floor), the
    auto-created AdverseAction's earliest_final_at equals
    pre_adverse_sent_at plus exactly 7 calendar days, preserving the
    time-of-day component.

    PRD §2.8: "The `earliest_final_at` timestamp on an AdverseAction is
    computed by adding the parent jurisdiction's `pre_adverse_waiting_days`
    (interpreted as a calendar-day count) to the `pre_adverse_sent_at`
    baseline, preserving the time-of-day component rather than rounding
    to a day boundary."
    PRD §3.6: "The `earliest_final_at` value is computed once, at row
    creation: the system takes `pre_adverse_sent_at` as the base instant
    and adds exactly the parent jurisdiction's `pre_adverse_waiting_days`
    calendar days, preserving the base time-of-day."

    Design: Corner/calculations/earliest_final_uses_jurisdiction_waiting_days_above_floor
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(
            state_code="CA", pre_adverse_waiting_days=7,
            recruiter_id="rec-001", crim_payload={"hits": 1},
        )
    )
    assert aa["pre_adverse_sent_at"] == "2026-06-01T10:00:00.000Z", \
        f"pre_adverse_sent_at must be stamped at clock time, got {aa['pre_adverse_sent_at']!r}"
    assert aa["earliest_final_at"] == "2026-06-08T10:00:00.000Z", \
        f"earliest_final_at must be pre_adverse_sent_at + 7d preserving time-of-day, got {aa['earliest_final_at']!r}"


def test_create_applicant_without_full_name_returns_invalid_request(api):
    """POST /applicants with the required field full_name missing is
    rejected with ERR_INVALID_REQUEST.

    PRD §2.9: "Body schema well-formedness — types, enum membership, and
    presence of required fields — is checked last and rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "Either the applicant themselves or a recruiter may register
    an `Applicant` row by supplying `full_name` (the applicant's legal
    full name), `email` (a unique email, lowercased on store), and
    `date_of_birth` (an ISO 8601 date used later for identity matching
    on consumer reports)."

    Design: Corner/validations/error_invalid_request_missing_required_field
    """
    from test_helpers import TEST_USERS
    set_clock("2026-06-01T10:00:00.000Z")
    resp = api.create_applicant(
        {"email": "incomplete@example.com", "date_of_birth": "1990-01-01T00:00:00.000Z"},
        TEST_USERS["applicant_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
