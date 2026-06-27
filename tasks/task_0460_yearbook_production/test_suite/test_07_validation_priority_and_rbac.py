"""Validation ordering, RBAC enforcement, optimistic concurrency on the print run,
and the staff-assignment deadline check.

Difficulty (queue A) priority-pair instances, corner (queue B) RBAC/OCC/validation
instances.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_yearbook_payload,
    create_ad_contract_payload,
    create_presale_order_payload,
    create_staff_assignment_payload,
    create_print_run_payload,
    create_yearbook,
    create_yearbook_early_window,
    create_page,
    create_active_staff_assignment,
    create_paid_order,
    set_clock,
    current_yearbook_version,
    TEST_USERS,
)

ADVISER = TEST_USERS["adviser_headers"]
STAFF = TEST_USERS["staff_headers"]
CONTRIBUTOR = TEST_USERS["contributor_headers"]
SALESREP = TEST_USERS["salesrep_headers"]


# ─── Priority pair: state check beats temporal (re-cancel a CANCELLED order) ─

def test_recancel_cancelled_order_returns_invalid_state(api):
    """PRD §2.6: "sixth, that the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409) ... Domain-
    specific business rules (pre-sale window, ad-page section, plant-frozen, submission
    completeness, and so on) are evaluated after these foundational checks".

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_presale_window
    """
    yb = create_yearbook_early_window()
    order = validate_success(
        api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="X", quantity=1), SALESREP
        ), 201,
    )
    validate_success(api.cancel_presale_order(order["id"], SALESREP), 200)  # PLACED -> CANCELLED
    res = api.cancel_presale_order(order["id"], SALESREP)  # cancel from CANCELLED is undefined
    validate_error(res, "ERR_INVALID_STATE")


def test_pay_cancelled_order_returns_invalid_state(api):
    """PRD §2.6: "sixth, that the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409) ... Domain-
    specific business rules (pre-sale window, ad-page section, plant-frozen, submission
    completeness, and so on) are evaluated after these foundational checks".

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_presale_window
    """
    # A second state-vs-business-rule conflict: paying a CANCELLED order. The state
    # check (pay is defined only from PLACED) fires before any later business rule.
    yb = create_yearbook_early_window()
    order = validate_success(
        api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="Y", quantity=1), SALESREP
        ), 201,
    )
    validate_success(api.cancel_presale_order(order["id"], SALESREP), 200)  # PLACED -> CANCELLED
    res = api.pay_presale_order(order["id"], SALESREP)  # pay undefined from CANCELLED
    validate_error(res, "ERR_INVALID_STATE")


# ─── Priority pair: authorization beats referential (Contributor signs ad) ───

def test_contributor_sign_ad_forbidden_beats_section_check(api):
    """PRD §2.6: "second, authorization — the declared role is permitted for the
    operation, else `ERR_FORBIDDEN` ... Domain-specific business rules (pre-sale
    window, ad-page section, plant-frozen, submission completeness, and so on) are
    evaluated after these foundational checks".

    Design: Difficulty/priority_pair_validation_conflict/priority_auth_beats_referential_ad_sign
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 3, "SPORTS", template_code="T")  # non-ADS page
    ad = validate_success(
        api.create_ad_contract(
            create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Mis-placed Ad",
                                       size="FULL"),
            SALESREP,
        ), 201,
    )
    res = api.sign_ad_contract(ad["id"], CONTRIBUTOR)  # Contributor not permitted to sign
    validate_error(res, "ERR_FORBIDDEN")


def test_staff_sign_ad_forbidden_beats_section_check(api):
    """PRD §2.6: "second, authorization — the declared role is permitted for the
    operation, else `ERR_FORBIDDEN` ... Domain-specific business rules (pre-sale
    window, ad-page section, plant-frozen, submission completeness, and so on) are
    evaluated after these foundational checks".

    Design: Difficulty/priority_pair_validation_conflict/priority_auth_beats_referential_ad_sign
    """
    # A second auth-vs-business-rule conflict: a Staff member (not permitted to sign,
    # which is SalesRep-exclusive) signs an ad on a non-ADS page. ERR_FORBIDDEN wins.
    yb = create_yearbook()
    page = create_page(yb["id"], 3, "SPORTS", template_code="T")  # non-ADS
    ad = validate_success(
        api.create_ad_contract(
            create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Mis-placed Ad",
                                       size="FULL"),
            SALESREP,
        ), 201,
    )
    res = api.sign_ad_contract(ad["id"], STAFF)
    validate_error(res, "ERR_FORBIDDEN")


# ─── RBAC ─────────────────────────────────────────────────────────────────────

def test_contributor_cannot_create_yearbook_forbidden(api):
    """PRD §4: the `POST /yearbooks` operation is authorized for role `Adviser`.
    PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/contributor_cannot_create_yearbook_forbidden
    """
    res = api.create_yearbook(create_yearbook_payload(), CONTRIBUTOR)
    validate_error(res, "ERR_FORBIDDEN")


def test_salesrep_cannot_approve_page_forbidden(api):
    """PRD §4: the `POST /yearbooks/pages/{pageId}/approve` operation is authorized for
    role `Adviser`. PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/salesrep_cannot_approve_page_forbidden
    """
    yb = create_yearbook()
    sa = create_active_staff_assignment(yb["id"])
    page = create_page(yb["id"], 1, "CLUBS", required_submission_count=0,
                       assigned_staff_id=sa["id"])
    validate_success(api.submit_review_page(page["id"], STAFF), 200)  # -> IN_REVIEW
    res = api.approve_page(page["id"], SALESREP)
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory
    HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares
    the operational capacity under which they are acting. If either header is missing,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_yearbooks({})  # no X-User-ID / X-User-Role
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Deadline temporal validation ─────────────────────────────────────────────

def test_staff_assignment_deadline_in_past_returns_error(api):
    """PRD §3.3: "A deadline that has already passed relative to the logical clock —
    that is, a `deadline_iso` earlier than the current clock instant — cannot be set on
    a new assignment and is rejected with `ERR_DEADLINE_IN_PAST`."

    Design: Corner/validations/staff_assignment_deadline_in_past_returns_error
    """
    yb = create_yearbook()
    set_clock("2026-05-01T00:00:00Z")
    res = api.create_staff_assignment(
        create_staff_assignment_payload(yb["id"], staff_user_id="staff-9",
                                        role_title="EDITOR",
                                        deadline_iso="2026-04-01T00:00:00Z"),
        ADVISER,
    )
    validate_error(res, "ERR_DEADLINE_IN_PAST")


# ─── OCC on the print run ─────────────────────────────────────────────────────

def test_print_run_correct_version_succeeds_and_bumps(api):
    """PRD §3.7: "Committing the run computes its `cost_cents` from the production-cost
    calculation, snapshots that figure onto the run, mirrors it onto the yearbook's
    `production_cost_cents`, sets the run's `status` to `COMMITTED`, and increments the
    yearbook's `version` by one".

    Design: Corner/cross_cutting_complexity_layers/occ_print_run_correct_version_succeeds_and_bumps
    """
    yb = create_yearbook()  # version 1
    res = api.create_print_run(
        create_print_run_payload(yb["id"], 100, yb["version"]), ADVISER
    )
    validate_success(res, 201)
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["version"] == 2


def test_print_run_stale_version_conflict(api):
    """PRD §2.8: "The server compares `expected_yearbook_version` against the target
    yearbook's current `version`. If they differ ... the commit is rejected with
    `ERR_STALE_VERSION` and HTTP status 412".

    Design: Corner/cross_cutting_complexity_layers/occ_print_run_stale_version_conflict
    """
    yb = create_yearbook()  # version 1
    stale_version = yb["version"]
    validate_success(
        api.create_print_run(
            create_print_run_payload(yb["id"], 100, stale_version), ADVISER
        ), 201,
    )  # bumps version to 2
    res = api.create_print_run(
        create_print_run_payload(yb["id"], 50, stale_version), ADVISER  # still version 1
    )
    validate_error(res, "ERR_STALE_VERSION")
