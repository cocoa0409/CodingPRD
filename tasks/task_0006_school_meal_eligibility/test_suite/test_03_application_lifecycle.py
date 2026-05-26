"""Tests covering the MealApplication state machine: branching at UNDER_REVIEW,
the cyclic DENIED→APPEALED→UNDER_REVIEW→APPROVED path, and version bumps on
every transition.
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    setup_clean_world,
    create_household,
    create_application,
    submit_application,
    start_review,
    approve_application,
    deny_application,
    appeal_application,
    get_application,
    TEST_USERS,
    make_parent_headers,
)


# ---------------------------------------------------------------------
# Difficulty rule 3 / instance 1 — mealapplication_branching_with_appeal_cycle
# DRAFT→SUBMITTED→UNDER_REVIEW→DENIED→APPEALED→UNDER_REVIEW→APPROVED.
# ---------------------------------------------------------------------

def test_denied_application_can_be_appealed_then_reapproved(api):
    """PRD §3.2: "A `DENIED` application is not terminal: the parent may
    appeal it, supplying an `appeal_reason` in the payload. The appeal is also
    the OCC-guarded act described in §2.5: the appeal request must carry
    `expected_mealapplication_version` matching the application's current
    `version`, or the appeal is rejected with `ERR_STALE_VERSION` (HTTP 412).
    On success the application moves from `DENIED` to `APPEALED`. From
    `APPEALED` the review cycle reopens: school staff or a district reviewer
    move the application back to `UNDER_REVIEW`, and the approve/deny choice
    is presented again."

    Design: Difficulty/non_linear_state_machine/mealapplication_branching_with_appeal_cycle
    """
    setup_clean_world("2026-02-01T09:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=False,
    )
    app = create_application(hh["id"])
    submit_application(app["id"], hh["id"])
    start_review(app["id"])
    denied = deny_application(app["id"], decision_reason="missing documentation")
    assert denied["status"] == "DENIED"
    v_denied = denied["version"]

    # Appeal — moves DENIED → APPEALED.
    appealed = appeal_application(
        app["id"], hh["id"], "documents attached", v_denied
    )
    assert appealed["status"] == "APPEALED", (
        f"after appeal, status must be APPEALED; got {appealed['status']!r}"
    )

    # Second review cycle.
    under_review_2 = start_review(app["id"])
    assert under_review_2["status"] == "UNDER_REVIEW", (
        f"after start-review on APPEALED, status must be UNDER_REVIEW; "
        f"got {under_review_2['status']!r}"
    )
    final = approve_application(app["id"], decision_reason="verified on appeal")
    assert final["status"] == "APPROVED", (
        f"final status after second review must be APPROVED; got {final['status']!r}"
    )


def test_appeal_cycle_bumps_version_on_every_transition(api):
    """PRD §3.2: "Every state transition on a `MealApplication` increments its
    `version` by one and refreshes its `updated_at`."

    Design: Difficulty/non_linear_state_machine/mealapplication_branching_with_appeal_cycle
    """
    setup_clean_world("2026-02-01T09:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=False,
    )
    app = create_application(hh["id"])
    assert app["version"] == 1, "freshly created application is v1"
    submitted = submit_application(app["id"], hh["id"])
    assert submitted["version"] == 2, f"after submit, version must be 2; got {submitted['version']}"
    under_review_1 = start_review(app["id"])
    assert under_review_1["version"] == 3
    denied = deny_application(app["id"], decision_reason="missing")
    assert denied["version"] == 4
    appealed = appeal_application(
        app["id"], hh["id"], "documents attached", denied["version"]
    )
    assert appealed["version"] == 5
    under_review_2 = start_review(app["id"])
    assert under_review_2["version"] == 6
    approved = approve_application(app["id"], decision_reason="verified")
    assert approved["version"] == 7
    assert approved["status"] == "APPROVED"
