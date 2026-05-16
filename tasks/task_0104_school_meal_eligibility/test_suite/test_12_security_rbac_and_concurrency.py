"""Security, RBAC enforcement, and PRD-defined concurrency outcomes.

PRD §4 explicitly assigns each endpoint to one or more roles. PRD §2.1
forbids role mismatches with ERR_FORBIDDEN. PRD §3.4 / §3.6 / §3.7 each
explicitly name an outcome when concurrent requests race; those are the
only race conditions tested.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_exactly_one_succeeds,
    build_user_headers,
    create_district_payload,
    create_meal_serving,
    create_meal_serving_payload,
    create_menu_item,
    create_menu_item_payload,
    create_usda_claim,
    make_parent_headers,
    run_race,
    setup_district_with_family,
    setup_paid_serving_with_balance,
    setup_student_with_tier,
    submit_usda_claim,
    top_up_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# §4 RBAC enforcement — role mismatches
# ===========================================================================
class TestRbacRoleMismatches:
    """PRD §4 endpoint table assigns each capability to specific
    roles."""

    def test_parent_cannot_create_district(self, api):
        """PRD §4: POST /districts is AuditOfficer only.
        PRD §2.1: "an authenticated request from a role that the
        endpoint does not permit is rejected with ERR_FORBIDDEN."

        Claim: a Parent calling POST /districts → ERR_FORBIDDEN.
        """
        res = api.create_district(
            create_district_payload(),
            build_user_headers("parent-1", "Parent"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_parent_cannot_create_menu_item(self, api):
        """PRD §4: POST /districts/{id}/menu-items is CafeteriaManager
        only.
        PRD §2.1: role mismatch → ERR_FORBIDDEN.

        Claim: a Parent attempting POST /menu-items → ERR_FORBIDDEN.
        """
        district, parent, _ = setup_district_with_family()
        res = api.create_menu_item(
            district["id"], create_menu_item_payload(),
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_cafeteria_cannot_approve_frl(self, api):
        """PRD §4: POST /frl-applications/{id}/approve is
        DistrictReviewer only.
        PRD §2.1: role mismatch → ERR_FORBIDDEN.

        Claim: a CafeteriaManager attempting POST /approve →
        ERR_FORBIDDEN.
        """
        from test_helpers import (
            create_frl_application,
            submit_frl_application,
        )
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=2_000_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        res = api.approve_frl_application(
            district["id"], app["id"],
            build_user_headers("cafeteria-1", "CafeteriaManager"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_reviewer_cannot_record_meal_serving(self, api):
        """PRD §4: POST /meal-servings is CafeteriaManager only.
        PRD §2.1: role mismatch → ERR_FORBIDDEN.

        Claim: a DistrictReviewer attempting POST /meal-servings →
        ERR_FORBIDDEN.
        """
        district, parent, student, item = setup_paid_serving_with_balance(
            full_price_cents=300, top_up_amount_cents=1000,
        )
        res = api.create_meal_serving(
            district["id"],
            create_meal_serving_payload(
                student_id=student["id"], menu_item_id=item["id"],
            ),
            build_user_headers("reviewer-1", "DistrictReviewer"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_cafeteria_cannot_submit_usda_claim(self, api):
        """PRD §4: POST /usda-claims/{id}/submit is AuditOfficer only.

        Claim: CafeteriaManager attempting POST /submit → ERR_FORBIDDEN.
        """
        from test_helpers import create_district
        district = create_district()
        claim = create_usda_claim(
            district=district,
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-01-31T00:00:00.000Z",
        )
        res = api.submit_usda_claim(
            district["id"], claim["id"],
            build_user_headers("cafeteria-2", "CafeteriaManager"),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.1 Parent ownership enforcement
# ===========================================================================
class TestParentOwnership:
    """PRD §2.1: "any ownership check ... compares the resource's
    parent_account_id (directly, or via the student's
    parent_account_id) to the header value."
    """

    def test_other_parent_cannot_submit_application(self, api):
        """PRD §2.1: ownership-gated calls compare resource
        parent_account_id to X-User-ID.
        PRD §3.4 + §2.9: a stale X-User-ID that does not match the
        owning parent's id surfaces ERR_FORBIDDEN (authorisation, prio
        2) before any state or business check.

        Claim: a different Parent's X-User-ID attempting to submit
        another parent's FRL application → ERR_FORBIDDEN.
        """
        from test_helpers import (
            create_frl_application,
        )
        district, parent_a, student = setup_district_with_family()
        _, parent_b, _ = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent_a, student=student,
        )
        # parent_b tries to submit parent_a's application.
        res = api.submit_frl_application(
            district["id"], app["id"],
            make_parent_headers(parent_b["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# PRD-defined race: two cafeteria managers, same student same day
# ===========================================================================
class TestConcurrentSameDayServing:
    """PRD §3.6: "under concurrent cafeteria-manager submissions on the
    same student and date, exactly one record wins by first-writer-wins
    on that uniqueness key and the loser likewise receives
    ERR_MEAL_ALREADY_SERVED_TODAY."
    """

    def test_two_concurrent_servings_one_wins(self, api):
        """PRD §3.6: "exactly one record wins by first-writer-wins on
        that uniqueness key and the loser likewise receives
        ERR_MEAL_ALREADY_SERVED_TODAY."

        Claim: two concurrent POST /meal-servings on the same student
        and same day → exactly one succeeds (201), the other returns
        409 ERR_MEAL_ALREADY_SERVED_TODAY.
        """
        from test_helpers import (
            TEST_USERS,
            advance_clock_to,
        )
        advance_clock_to("2026-09-20T12:00:00.000Z")
        district, parent, student, _app = setup_student_with_tier(
            target_tier="FREE",
            school_year_start="2026-08-01T00:00:00.000Z",
        )
        item1 = create_menu_item(district=district, name="Race A")
        item2 = create_menu_item(district=district, name="Race B")

        results = run_race(
            lambda: api.create_meal_serving(
                district["id"],
                create_meal_serving_payload(
                    student_id=student["id"], menu_item_id=item1["id"],
                ),
                TEST_USERS["cafeteria_headers"],
            ),
            lambda: api.create_meal_serving(
                district["id"],
                create_meal_serving_payload(
                    student_id=student["id"], menu_item_id=item2["id"],
                ),
                TEST_USERS["cafeteria_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD §3.6 names the loser's error_id explicitly.
        loser_body = outcome["failures"][0].json()
        assert (
            loser_body["data"]["error_id"]
            == "ERR_MEAL_ALREADY_SERVED_TODAY"
        ), (
            f"loser error must be ERR_MEAL_ALREADY_SERVED_TODAY, got "
            f"{loser_body['data']['error_id']!r}"
        )
