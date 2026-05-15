"""Exhibitor applications, priority scoring, and theme matching —
PRD §3.3.

Covers application lifecycle (DRAFT → SUBMITTED → UNDER_REVIEW →
QUALIFIED / REJECTED, plus SUBMITTED → WITHDRAWN and UNDER_REVIEW →
WITHDRAWN), the theme-mismatch validation at qualification, and the
default values for optional fields on intake.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_application,
    create_application_payload,
    create_exhibition,
    create_qualified_application,
    create_submitted_application,
    make_exhibitor_headers,
    open_intake,
    qualify_application,
    random_exhibitor_id,
    reject_application_payload,
    setup_exhibition_with_active_plan,
    validate_error,
    validate_success,
)


# ===========================================================================
# Application creation (PRD §3.3)
# ===========================================================================
class TestApplicationCreation:

    def test_application_starts_in_draft(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "A newly created application is in DRAFT."

        Claim: POST /exhibitions/{id}/applications returns status='DRAFT'.
        """
        exh, _, _ = setup_exhibition_with_active_plan()
        open_intake(exh["id"])
        exhibitor_id = random_exhibitor_id()
        headers = make_exhibitor_headers(exhibitor_id)
        res = api.create_application(
            exh["id"], create_application_payload(theme_tags=["GEN"]),
            headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "DRAFT"
        assert_application(data)


# ===========================================================================
# Application submission and priority score (PRD §3.3)
# ===========================================================================
class TestSubmitAndPriorityScore:

    def test_submit_requires_intake_open(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "When the exhibitor submits the application, the
        system requires the owning exhibition to be in INTAKE_OPEN
        (otherwise ERR_INVALID_STATE)."

        Claim: submitting before /open-intake → ERR_INVALID_STATE.
        """
        # Exhibition still in DRAFT — intake NOT opened.
        exh, _, _ = setup_exhibition_with_active_plan()
        exhibitor_id = random_exhibitor_id()
        headers = make_exhibitor_headers(exhibitor_id)
        create_res = api.create_application(
            exh["id"], create_application_payload(theme_tags=["GEN"]),
            headers,
        )
        # PRD §3.3 says SUBMITTED requires INTAKE_OPEN; the implementer
        # MAY also reject the CREATE step. We assert the submit step
        # specifically since PRD names it.
        app = validate_success(create_res, expected_status=201)
        submit_res = api.submit_application(app["id"], headers)
        validate_error(submit_res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_submit_assigns_lottery_token_in_range(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "on successful submission it assigns a random
        integer lottery_token drawn uniformly from the closed interval
        bounded below by 0 and above by 999999."

        Claim: a submitted application has lottery_token in
        [0, 999999].
        """
        exh, _, _ = setup_exhibition_with_active_plan()
        open_intake(exh["id"])
        app, _ = create_submitted_application(
            exh["id"], theme_tags=["GEN"],
        )
        assert isinstance(app["lottery_token"], int)
        assert 0 <= app["lottery_token"] <= 999999

    def test_priority_score_platinum_seniority_capped(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "a sponsor weight first (0 for NONE, 100 for
        BRONZE, 250 for SILVER, 500 for GOLD, 1000 for PLATINUM), plus
        a seniority weight equal to ten times the smaller of
        seniority_years and twenty (so each year adds ten, capped at
        twenty years), plus a lottery component equal to lottery_token
        divided by ten thousand."

        Claim: PLATINUM + 25 years (capped at 20) yields a priority
        score in [1200, 1300) — sponsor 1000 + seniority 200 + lottery
        in [0, 100).
        """
        exh, _, _ = setup_exhibition_with_active_plan()
        open_intake(exh["id"])
        app, _ = create_submitted_application(
            exh["id"],
            theme_tags=["GEN"],
            sponsorship_level="PLATINUM",
            seniority_years=25,
        )
        # priority_score in [1200.0, 1300.0)
        assert 1200.0 <= app["priority_score"] < 1300.0

    def test_priority_score_seniority_per_year_is_ten(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "a seniority weight equal to ten times the
        smaller of seniority_years and twenty (so each year adds ten,
        capped at twenty years)."

        Claim: NONE + 5 years yields priority_score in [50, 150) —
        sponsor 0 + seniority 50 + lottery in [0, 100).
        """
        exh, _, _ = setup_exhibition_with_active_plan()
        open_intake(exh["id"])
        app, _ = create_submitted_application(
            exh["id"],
            theme_tags=["GEN"],
            sponsorship_level="NONE",
            seniority_years=5,
        )
        assert 50.0 <= app["priority_score"] < 150.0


# ===========================================================================
# Qualification and theme matching (PRD §3.3)
# ===========================================================================
class TestQualifyAndThemeMatching:

    def test_qualify_rejected_when_theme_tags_do_not_intersect(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "qualify it (moving it to QUALIFIED, provided the
        application's theme_tags set intersects the singleton set
        containing the exhibition's theme_code — failure surfaces as
        ERR_THEME_MISMATCH)."

        Claim: qualifying an application whose theme_tags do not
        contain Exhibition.theme_code → ERR_THEME_MISMATCH.
        """
        exh, _, _ = setup_exhibition_with_active_plan(theme_code="GEN")
        open_intake(exh["id"])
        # Submit with theme_tags that do NOT include 'GEN'.
        app, _ = create_submitted_application(
            exh["id"], theme_tags=["WRONG_THEME"],
        )
        # Move to UNDER_REVIEW first.
        api.start_review_application(
            app["id"], TEST_USERS["venue_admin_headers"],
        )
        res = api.qualify_application(
            app["id"], TEST_USERS["venue_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_THEME_MISMATCH.value)

    def test_qualify_succeeds_when_theme_intersects(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "the application's theme_tags set intersects the
        singleton set containing the exhibition's theme_code."

        Claim: an application with matching theme_tags can be qualified.
        """
        exh, _, _ = setup_exhibition_with_active_plan(theme_code="GEN")
        open_intake(exh["id"])
        app, _ = create_qualified_application(
            exh["id"], theme_tags=["GEN"],
        )
        assert app["status"] == "QUALIFIED"


# ===========================================================================
# Reject path (PRD §3.3)
# ===========================================================================
class TestRejectApplication:

    def test_reject_records_rejection_reason(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "reject it (moving it to REJECTED while recording
        a non-empty rejection_reason on the row)."

        Claim: reject with rejection_reason → status=REJECTED and
        rejection_reason is stored.
        """
        exh, _, _ = setup_exhibition_with_active_plan(theme_code="GEN")
        open_intake(exh["id"])
        app, _ = create_submitted_application(
            exh["id"], theme_tags=["GEN"],
        )
        api.start_review_application(app["id"], venue_admin_headers)
        res = api.reject_application(
            app["id"],
            reject_application_payload(rejection_reason="Off-topic"),
            venue_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REJECTED"
        assert data["rejection_reason"] == "Off-topic"


# ===========================================================================
# Withdraw path (PRD §3.3)
# ===========================================================================
class TestWithdrawApplication:

    def test_exhibitor_withdraws_from_submitted(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "An exhibitor can withdraw their own application
        from SUBMITTED or UNDER_REVIEW, moving it to WITHDRAWN."

        Claim: withdraw from SUBMITTED → status=WITHDRAWN.
        """
        exh, _, _ = setup_exhibition_with_active_plan()
        open_intake(exh["id"])
        app, exhibitor_id = create_submitted_application(
            exh["id"], theme_tags=["GEN"],
        )
        res = api.withdraw_application(
            app["id"], make_exhibitor_headers(exhibitor_id),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "WITHDRAWN"

    def test_exhibitor_withdraws_from_under_review(
        self, api, venue_admin_headers,
    ):
        """PRD §3.3: "An exhibitor can withdraw their own application
        from SUBMITTED or UNDER_REVIEW, moving it to WITHDRAWN."

        Claim: withdraw from UNDER_REVIEW → status=WITHDRAWN.
        """
        exh, _, _ = setup_exhibition_with_active_plan()
        open_intake(exh["id"])
        app, exhibitor_id = create_submitted_application(
            exh["id"], theme_tags=["GEN"],
        )
        api.start_review_application(app["id"], venue_admin_headers)
        res = api.withdraw_application(
            app["id"], make_exhibitor_headers(exhibitor_id),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "WITHDRAWN"
