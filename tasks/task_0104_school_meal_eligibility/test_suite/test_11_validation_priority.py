"""Validation priority — the deterministic precedence in PRD §2.9.

Order, from highest to lowest:
1. Authentication (ERR_UNAUTHENTICATED).
2. Authorisation (ERR_FORBIDDEN).
3. Existence (ERR_NOT_FOUND).
4. State (ERR_INVALID_STATE).
5. Domain safety, referential, fiscal, constraint, temporal — and
   within this group, ERR_VALIDATION is a structural input check that
   runs before higher-numbered business rules.

The reviewer's deny-already-approved example in PRD §2.9 anchors the
state-over-business rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    create_allergy_entry,
    create_meal_serving_payload,
    create_menu_item,
    deny_payload,
    make_parent_headers,
    retire_menu_item,
    setup_district_with_family,
    setup_paid_serving_with_balance,
    validate_error,
)


# ===========================================================================
# §2.9 State vs business_safety — state wins
# ===========================================================================
class TestStateWinsOverBusinessSafety:
    """PRD §2.9: "every other rule in this document is evaluated only
    after the four checks above have passed." State (priority 4) wins
    over business_safety (priority 5)."""

    def test_retired_menu_with_allergen_returns_invalid_state(
        self, api, cafeteria_headers,
    ):
        """PRD §2.9: "Domain safety, referential, fiscal, constraint,
        and temporal checks — every other rule in this document is
        evaluated only after the four checks above have passed."

        Concretely: ACTIVE allergy on PEANUT plus a RETIRED menu item
        whose contains_allergens=[PEANUT] — both checks would fail,
        but priority 4 (state) fires before priority 5 (allergen),
        yielding ERR_INVALID_STATE.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_invalid_state_wins_over_allergen
        """
        district, parent, student = setup_district_with_family()
        create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="PEANUT", severity="MILD",
        )
        item = create_menu_item(
            district=district, contains_allergens=["PEANUT"],
            full_price_cents=350,
        )
        # Retire the menu item.
        retire_menu_item(district=district, menu_item=item)
        # Attempt to serve. Both state (RETIRED) and allergen would
        # block; PRD §2.9 says state wins.
        res = api.create_meal_serving(
            district["id"],
            create_meal_serving_payload(
                student_id=student["id"], menu_item_id=item["id"],
            ),
            cafeteria_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.6 Allergen vs fiscal — within the post-state group, PRD §3.6 lists
# allergen FIRST then balance.
# ===========================================================================
class TestAllergenWinsOverBalance:
    """PRD §3.6 lists the four substantive preconditions in this exact
    order: (1) allergen block, (2) menu item ACTIVE, (3) daily
    uniqueness, (4) PAID-tier balance.

    PRD §3.6: "The system runs four substantive preconditions before
    persisting the record. First, the student must not be allergen-
    blocked ... Fourth, if the student's eligibility tier is PAID at
    the moment of serving, the parent account's prepaid_balance_cents
    must be at least the menu item's full_price_cents".

    This in-order listing in PRD §3.6 names the allergen check as the
    first substantive precondition, and the balance check as the
    fourth. Combined with §2.9's precedence ordering "domain safety,
    referential, fiscal, constraint, and temporal checks" (safety
    before fiscal), the allergen check fires first.
    """

    def test_paid_with_allergy_and_zero_balance_returns_allergen_block(
        self, api, cafeteria_headers,
    ):
        """PRD §3.6 (in order): "First, the student must not be
        allergen-blocked against this specific menu item ... Fourth,
        if the student's eligibility tier is PAID at the moment of
        serving, the parent account's prepaid_balance_cents must be at
        least the menu item's full_price_cents."

        Concretely: PAID-tier student with balance 0 and an ACTIVE
        DAIRY allergy attempting to serve a DAIRY-containing menu
        item — both would fail. The allergen check (PRD §3.6 first
        precondition) fires before the balance check (PRD §3.6 fourth
        precondition), yielding ERR_ALLERGEN_BLOCK.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_allergen_wins_over_balance
        """
        district, parent, student = setup_district_with_family()
        create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="DAIRY", severity="MODERATE",
            doctor_note_attached=False,
        )
        item = create_menu_item(
            district=district, contains_allergens=["DAIRY"],
            full_price_cents=350,
        )
        # Balance is 0; student tier is PAID. Allergen check is listed
        # first in PRD §3.6, so it fires first.
        res = api.create_meal_serving(
            district["id"],
            create_meal_serving_payload(
                student_id=student["id"], menu_item_id=item["id"],
            ),
            cafeteria_headers,
        )
        validate_error(res, "ERR_ALLERGEN_BLOCK")


# ===========================================================================
# §2.9 State vs SoD — state wins (PRD §2.9 explicit example)
# ===========================================================================
class TestStateBeforeSegregationOfDuties:
    """PRD §2.9: "A reviewer who attempts to deny an already-APPROVED
    application thus sees ERR_INVALID_STATE, not
    ERR_SEGREGATION_OF_DUTIES, even if both would have applied."
    """

    def test_deny_already_approved_returns_invalid_state(self, api):
        """PRD §2.9: "A reviewer who attempts to deny an already-
        APPROVED application thus sees ERR_INVALID_STATE, not
        ERR_SEGREGATION_OF_DUTIES, even if both would have applied".

        Claim: deny on an APPROVED application by the parent-as-
        reviewer (a SoD violation) still surfaces ERR_INVALID_STATE.
        """
        from test_helpers import (
            approve_frl_application,
            build_user_headers,
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
        approve_frl_application(district=district, application=app)
        # Now try to deny. Use parent-as-reviewer (a SoD violation), but
        # PRD §2.9 says state error (APPROVED is not SUBMITTED) wins.
        bad_headers = build_user_headers(parent["id"], "DistrictReviewer")
        res = api.deny_frl_application(
            district["id"], app["id"],
            deny_payload(review_note="too late"),
            bad_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")
