"""Case state machine corners: invalid transitions, jurisdiction, filing rights."""
from test_helpers import (
    ApiErrorId,
    begin_jurisdiction_review,
    confirm_jurisdiction,
    create_case,
    dismiss_case,
    dismiss_case_payload,
    drive_to_investigation,
    get_case,
    make_cast,
    make_coordinator_headers,
    make_party_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


class TestDismissalGates:
    def test_dismiss_from_received_rejected(self, api):
        """PRD 3.1: "From `RECEIVED`, the only way forward is jurisdiction review."
        PRD 2.11: "**State** — the target entity must be in a from-state from which
        the requested transition exists in its machine, with terminal states
        rejecting all further transitions (`ERR_INVALID_STATE_TRANSITION`, 409)".

        Design: Corner/state_machines/dismiss_from_received_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")

        resp = api.dismiss_case(
            case["id"],
            dismiss_case_payload(dismissal_reason="MANDATORY_NO_JURISDICTION"),
            coord_h,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = get_case(case["id"], cast["coord"]["id"])
        assert after["status"] == "RECEIVED", "rejected dismissal must not move the case"
        notices, _ = validate_paginated(api.list_case_notices(case["id"], coord_h))
        assert notices == [], "a rejected dismissal issues no DISMISSAL notice"

    def test_dismissal_with_referral_lands_referred_to_conduct(self, api):
        """PRD 3.1: "From `JURISDICTION_REVIEW`, dismissal with `refer_to_conduct`
        false lands in `DISMISSED` and appends `CASE_DISMISSED`; dismissal with
        `refer_to_conduct` true instead lands in `REFERRED_TO_CONDUCT` and appends
        `CASE_REFERRED`."

        Design: Corner/validations/confirm_jurisdiction_unmet_facts_rejected
        """
        # The referral leg: dismissal with refer_to_conduct true from
        # JURISDICTION_REVIEW lands in REFERRED_TO_CONDUCT.
        cast = make_cast("comp", "resp", "coord")
        case = create_case(
            cast, categories=["SEXUAL_HARASSMENT"],
            occurred_in_program_activity=False, received_via="EMAIL",
        )
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])
        data = dismiss_case(
            case["id"], cast["coord"]["id"],
            dismissal_reason="MANDATORY_NO_JURISDICTION", refer_to_conduct=True,
        )
        assert data["status"] == "REFERRED_TO_CONDUCT"
        assert data["dismissal_reason"] == "MANDATORY_NO_JURISDICTION"
        assert data["closed_at"] is not None


class TestRepeatedTransition:
    def test_begin_jurisdiction_review_twice_rejected(self, api):
        """PRD 2.11: "**State** — the target entity must be in a from-state from which
        the requested transition exists in its machine, with terminal states
        rejecting all further transitions (`ERR_INVALID_STATE_TRANSITION`, 409)".

        Design: Corner/state_machines/begin_jurisdiction_review_twice_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])

        resp = api.begin_jurisdiction_review(case["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestFormalComplaintRights:
    def test_respondent_cannot_file_formal_complaint(self, api):
        """PRD 3.1: "Filing the signed formal complaint requires the actor's
        identity to equal the case's `complainant_id`; anyone else's attempt is
        rejected with `ERR_ONLY_COMPLAINANT_MAY_FILE` (422)."

        Design: Corner/validations/respondent_cannot_file_formal_complaint
        """
        cast = make_cast("comp", "resp", "coord")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        begin_jurisdiction_review(case["id"], cast["coord"]["id"])
        confirm_jurisdiction(case["id"], cast["coord"]["id"])

        resp = api.file_formal_complaint(
            case["id"], make_party_headers(cast["resp"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ONLY_COMPLAINANT_MAY_FILE)

        after = get_case(case["id"], cast["coord"]["id"])
        assert after["status"] == "AWAITING_FORMAL_COMPLAINT"
        assert after["formal_complaint_signed"] is False


class TestJurisdictionConfirmation:
    def test_confirm_jurisdiction_unmet_facts_rejected(self, api):
        """PRD 3.1: "It succeeds only when both jurisdiction facts are true — the
        incident occurred within an education program or activity *and* the
        complainant was in the United States — *and* the `categories` contain at
        least one Title IX category among `SEXUAL_HARASSMENT`, `SEXUAL_ASSAULT`,
        `DATING_VIOLENCE`, `DOMESTIC_VIOLENCE`, `STALKING`, and `OTHER_SEX_BASED`;
        a report carrying only `NON_TITLE_IX_MISCONDUCT` can never be confirmed.
        A confirmation attempt that fails any leg is rejected with
        `ERR_JURISDICTION_REQUIREMENTS_UNMET` (422)."

        Design: Corner/validations/confirm_jurisdiction_unmet_facts_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        # Case A: program-activity fact false.
        case_a = create_case(
            cast, categories=["SEXUAL_HARASSMENT"],
            occurred_in_program_activity=False, received_via="EMAIL",
        )
        begin_jurisdiction_review(case_a["id"], cast["coord"]["id"])
        # Case B: only a non-Title-IX category.
        case_b = create_case(
            cast, categories=["NON_TITLE_IX_MISCONDUCT"], received_via="EMAIL",
        )
        begin_jurisdiction_review(case_b["id"], cast["coord"]["id"])

        err_a = api.confirm_jurisdiction(case_a["id"], coord_h)
        validate_error(err_a, ApiErrorId.ERR_JURISDICTION_REQUIREMENTS_UNMET)
        err_b = api.confirm_jurisdiction(case_b["id"], coord_h)
        validate_error(err_b, ApiErrorId.ERR_JURISDICTION_REQUIREMENTS_UNMET)

        # The conduct track catches what Title IX cannot.
        data = dismiss_case(
            case_a["id"], cast["coord"]["id"],
            dismissal_reason="MANDATORY_NO_JURISDICTION", refer_to_conduct=True,
        )
        assert data["status"] == "REFERRED_TO_CONDUCT"
