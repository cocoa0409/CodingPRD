"""Informal resolution: gates, consent fan-in, withdrawal loop, resolution."""
from test_helpers import (
    ApiErrorId,
    begin_jurisdiction_review,
    confirm_jurisdiction,
    consent_informal,
    create_case,
    drive_to_investigation,
    file_formal_complaint,
    get_case,
    informal_resolution_payload,
    make_cast,
    make_coordinator_headers,
    propose_informal_resolution,
    resolve_informal,
    validate_error,
    validate_success,
    withdraw_informal,
)
from test_helpers import api_client


def _case_with_signed_complaint(cast, categories=("SEXUAL_HARASSMENT",), **case_overrides):
    case = create_case(cast, categories=list(categories), received_via="EMAIL", **case_overrides)
    drive_to_investigation(case["id"], cast["coord"]["id"], cast["comp"]["id"])
    return case


class TestInformalProposalGates:
    def test_informal_resolution_employee_respondent_prohibited(self, api):
        """PRD 3.7: "Informal resolution is categorically prohibited when the
        respondent's `role_type` is `EMPLOYEE` and the complainant's is `STUDENT`
        — employee-on-student allegations may never resolve informally — failing
        as `ERR_INFORMAL_RESOLUTION_PROHIBITED` (422)."

        Design: Corner/validations/informal_resolution_employee_respondent_prohibited
        """
        cast = make_cast("comp", "resp_emp", "coord", "fac")
        case = _case_with_signed_complaint(cast, respondent_id=cast["resp_emp"]["id"])
        resp = api.propose_informal_resolution(
            case["id"], informal_resolution_payload(cast["fac"]["id"]),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INFORMAL_RESOLUTION_PROHIBITED)

    def test_informal_resolution_requires_formal_complaint(self, api):
        """PRD 3.7: "The case must carry a signed formal complaint:
        `formal_complaint_signed` true, failing as `ERR_FORMAL_COMPLAINT_REQUIRED`
        (422)."

        Design: Corner/validations/informal_resolution_requires_formal_complaint
        """
        cast = make_cast("comp", "resp", "coord", "fac")
        case = create_case(cast, categories=["SEXUAL_HARASSMENT"], received_via="EMAIL")
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])
        confirm_jurisdiction(case["id"], cast["coord"]["id"])
        # Still AWAITING_FORMAL_COMPLAINT: formal_complaint_signed is false.
        resp = api.propose_informal_resolution(
            case["id"], informal_resolution_payload(cast["fac"]["id"]),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORMAL_COMPLAINT_REQUIRED)

    def test_second_informal_resolution_rejected(self, api):
        """PRD 3.7: "And only one informal resolution per case may be live — in
        `PROPOSED` or `IN_PROGRESS` — failing as
        `ERR_ACTIVE_INFORMAL_RESOLUTION_EXISTS` (409)."

        Design: Corner/validations/second_informal_resolution_rejected
        """
        cast = make_cast("comp", "resp", "coord", "fac")
        case = _case_with_signed_complaint(cast)
        propose_informal_resolution(case["id"], cast["coord"]["id"], cast["fac"]["id"])
        resp = api.propose_informal_resolution(
            case["id"], informal_resolution_payload(cast["fac"]["id"]),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_INFORMAL_RESOLUTION_EXISTS)


class TestInformalDeclineAndWithdrawal:
    def test_informal_resolution_decline_terminates_and_resumes_case(self, api):
        """PRD 3.7: "A false consent is a decline: the resolution moves `PROPOSED
        → TERMINATED`, the case returns to `INVESTIGATION`, and
        `INFORMAL_TERMINATED` plus `CASE_RESUMED` are appended with a version
        increment."

        Design: Corner/state_machines/informal_resolution_decline_terminates_and_resumes_case
        """
        cast = make_cast("comp", "resp", "coord", "fac")
        case = _case_with_signed_complaint(cast)
        resolution = propose_informal_resolution(case["id"], cast["coord"]["id"], cast["fac"]["id"])
        assert get_case(case["id"], cast["coord"]["id"])["status"] == "INFORMAL_RESOLUTION_IN_PROGRESS"

        declined = consent_informal(resolution["id"], "RESPONDENT", cast["resp"]["id"], False)
        assert declined["status"] == "TERMINATED"
        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["status"] == "INVESTIGATION", "the formal track resumes"


class TestInformalCycleAndResolve:
    def test_withdrawal_loop_then_consent_fan_in_and_resolve(self, api):
        """PRD 3.7: "Either party may also withdraw outright, from `PROPOSED` or
        `IN_PROGRESS` alike — a non-party's attempt is
        `ERR_PARTY_BINDING_MISMATCH`. Withdrawal records the `withdrawn_by_side`,
        moves the resolution to `WITHDRAWN`, returns the case to `INVESTIGATION`,
        and appends `INFORMAL_WITHDRAWN` plus `CASE_RESUMED` with a version
        increment. This withdrawal loop is the second of the §3.1 cycles: a case
        may leave the informal track and, conditions permitting, re-enter it
        later under a fresh proposal."
        PRD 3.7: "Resolving moves the resolution `IN_PROGRESS → RESOLVED` —
        `RESOLVED`, `WITHDRAWN`, and `TERMINATED` are the resolution's terminal
        states — moves the case to `RESOLVED_INFORMAL` with `closed_at` stamped,
        and appends `INFORMAL_RESOLVED` plus `CASE_CLOSED` with a version
        increment."

        Design: Difficulty/non_linear_state_machine/informal_resolution_withdrawal_cycle_then_resolve
        """
        cast = make_cast("comp", "resp", "coord", "fac")
        case = _case_with_signed_complaint(cast)

        # First lap: proposed, then withdrawn by the respondent.
        ir1 = propose_informal_resolution(case["id"], cast["coord"]["id"], cast["fac"]["id"])
        withdrawn = withdraw_informal(ir1["id"], cast["resp"]["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawn_by_side"] == "RESPONDENT"
        assert get_case(case["id"], cast["coord"]["id"])["status"] == "INVESTIGATION"

        # Second lap: the cycle is re-enterable, and resolves the case.
        ir2 = propose_informal_resolution(case["id"], cast["coord"]["id"], cast["fac"]["id"])
        consent_informal(ir2["id"], "COMPLAINANT", cast["comp"]["id"], True)
        in_progress = consent_informal(ir2["id"], "RESPONDENT", cast["resp"]["id"], True)
        assert in_progress["status"] == "IN_PROGRESS"

        resolved = resolve_informal(ir2["id"], cast["coord"]["id"])
        assert resolved["status"] == "RESOLVED"
        assert resolved["agreed_terms"] == "Mutual no-contact + counseling"
        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["status"] == "RESOLVED_INFORMAL"
        assert case_after["closed_at"] is not None

    def test_second_consent_alone_fires_in_progress(self, api):
        """PRD 3.7: "A true consent stamps `complainant_consent_at` or
        `respondent_consent_at` from the logical clock and appends
        `INFORMAL_CONSENT_RECORDED` with a version increment; the same party
        consenting twice is rejected with `ERR_DUPLICATE_RESOURCE` (409). The
        instant the **second** party consents — both consent timestamps now set —
        the resolution auto-fires `PROPOSED → IN_PROGRESS`."

        Design: Difficulty/non_linear_state_machine/informal_resolution_withdrawal_cycle_then_resolve
        """
        cast = make_cast("comp", "resp", "coord", "fac")
        case = _case_with_signed_complaint(cast)

        # Complete one withdrawal lap first: the loop returns to INVESTIGATION.
        ir1 = propose_informal_resolution(case["id"], cast["coord"]["id"], cast["fac"]["id"])
        withdrawn = withdraw_informal(ir1["id"], cast["resp"]["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_case(case["id"], cast["coord"]["id"])["status"] == "INVESTIGATION"

        ir2 = propose_informal_resolution(case["id"], cast["coord"]["id"], cast["fac"]["id"])
        after_one = consent_informal(ir2["id"], "COMPLAINANT", cast["comp"]["id"], True)
        assert after_one["status"] == "PROPOSED", (
            "a single consent is not enough: the fan-in needs both parties"
        )
        assert after_one["complainant_consent_at"] is not None
        assert after_one["respondent_consent_at"] is None

        after_two = consent_informal(ir2["id"], "RESPONDENT", cast["resp"]["id"], True)
        assert after_two["status"] == "IN_PROGRESS"
        assert after_two["respondent_consent_at"] is not None
