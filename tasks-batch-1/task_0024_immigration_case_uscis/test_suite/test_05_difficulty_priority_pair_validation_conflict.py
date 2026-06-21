"""Difficulty Rule 5 — priority_pair_validation_conflict.

Tests where a single request violates two different validations simultaneously,
and the higher-priority one masks the lower-priority one per PRD §2.11.
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    set_clock,
    register_applicant,
    create_draft_case,
    make_applicant_headers,
    create_biometrics_payload,
    TEST_USERS,
)


class TestStateBeatsBusinessConstraintBiometricsOnI130InDraft:
    """An I-130 case in DRAFT receives a biometrics POST.
    Two checks both fail: (state) Case is in DRAFT not FILED, and
    (business_constraint) I-130 doesn't apply to biometrics.
    Priority order makes state-check fire first (ERR_INVALID_STATE).
    """

    def test_state_check_fires_before_case_type_check(self, api):
        """PRD §2.11: "source-state correctness for the requested transition
        (`ERR_INVALID_STATE`), terminal-state preclusion (`ERR_ALREADY_TERMINAL`),
        case-type applicability (`ERR_CASE_TYPE_NOT_APPLICABLE`)"
        PRD §2.11: "a wrong source state always masks a case-type or visa-retrogression issue"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_biometrics_on_i130_in_draft
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        # I-130 case left in DRAFT (never filed).
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="IR")
        assert case["status"] == "DRAFT"

        # POST biometrics on this I-130 DRAFT case. Both ERR_INVALID_STATE (DRAFT
        # is the wrong source state — FILED is required) and ERR_CASE_TYPE_NOT_APPLICABLE
        # (I-130 doesn't take biometrics) are simultaneously true; per the priority
        # order, the state error fires.
        officer = TEST_USERS["officer_headers"]
        res = api.schedule_biometrics(
            case["id"],
            create_biometrics_payload("2026-07-25T15:00:00Z", "ASC-SF-99"),
            officer,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_state_check_response_status_is_409(self, api):
        """PRD §5: "`ERR_INVALID_STATE` | 409 Conflict"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_biometrics_on_i130_in_draft
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="IR")
        officer = TEST_USERS["officer_headers"]
        res = api.schedule_biometrics(
            case["id"],
            create_biometrics_payload("2026-07-25T15:00:00Z", "ASC-SF-99"),
            officer,
        )
        assert res.status_code == 409


class TestExistenceBeatsBusinessReferentialUnknownCaseId:
    """A GET on a non-existent case id by an Applicant whose id is also not the
    case owner (since the case doesn't exist) fails ERR_NOT_FOUND (existence)
    rather than ERR_OWNERSHIP_VIOLATION (business_referential).
    """

    def test_unknown_case_id_returns_not_found_not_ownership_violation(self, api):
        """PRD §2.11: "path-templated resource existence (`ERR_NOT_FOUND`),
        body-supplied foreign-key resolvability (`ERR_REFERENCED_NOT_FOUND`),
        case ownership (`ERR_OWNERSHIP_VIOLATION`)"
        PRD §2.11: "an unknown path id always masks an ownership mismatch"

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_referential_decide_unknown_case_with_wrong_owner_intent
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        headers = make_applicant_headers(applicant["id"])
        # GET /uscis/cases/<unknown UUID> — the applicant is authenticated and
        # authorized for the read; ownership would also fail but cannot because
        # there is no case.
        res = api.get_case("00000000-0000-0000-0000-000000000999", headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_unknown_case_id_returns_404_status(self, api):
        """PRD §5: "`ERR_NOT_FOUND` | 404 Not Found"

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_referential_decide_unknown_case_with_wrong_owner_intent
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        headers = make_applicant_headers(applicant["id"])
        res = api.get_case("00000000-0000-0000-0000-000000000999", headers)
        assert res.status_code == 404
