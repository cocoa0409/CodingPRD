"""Cascading reconciliation: payment/dismissal/completion releases, holds, warrants.

Covers the depth-3 payment cascade, the school-completion point-suspension release
cascade, the late-penalty-then-payment open-hold conservation invariant, and the
plan-default nonpayment-hold cascade.
"""
import pytest
from test_helpers import (
    validate_success,
    create_citation_payload,
    create_charge_payload,
    create_payment_payload,
    create_enrollment_payload,
    create_installment_plan_payload,
    make_driver_headers,
)
from test_helpers.fixtures import (
    setup_jurisdiction_and_driver,
    setup_assessed_citation,
    setup_driver_suspended_two_upholds,
    uphold_citation_points,
    pay_citation_in_full,
    file_contest,
    set_clock,
    find_hold,
    list_license_holds,
    CLERK,
)


def test_payment_paid_releases_hold_rederives_license_reevaluates_points(api):
    """PRD §3.4: "Reaching `PAID` sets off the deepest cascade in the system: any
    open nonpayment or failure-to-appear hold for this citation is released;
    releasing each hold re-derives the driver's `license_status`; that re-derivation
    re-evaluates the driver's point suspension; any active warrant for the citation
    is quashed and the driver's `fta_warrant_active` flag is re-derived; and any
    active installment plan is marked `COMPLETED` with its remaining scheduled
    installments flipped to `PAID`."
    PRD §3.6: "Applying it once adds the jurisdiction's `late_penalty_cents` ... and
    — as a cascade — opens a nonpayment **LicenseHold** for the citation if none is
    already open, re-deriving the driver's `license_status` to `HELD`."

    Design: Difficulty/transitive_cascade/payment_paid_releases_hold_rederives_license_reevaluates_points
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-04T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    api.assess_citation(cit["id"], CLERK)  # balance 29000
    set_clock("2026-02-11T00:00:00Z")
    api.apply_late_penalty(cit["id"], CLERK)  # +3000 -> balance 32000, NONPAYMENT_HOLD, HELD
    held = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert held["license_status"] == "HELD"
    # Pay in full (32000) -> PAID -> release hold -> license VALID.
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(32000, method="CARD"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    paid = validate_success(api.get_citation(cit["id"], CLERK), 200)
    assert paid["financial_status"] == "PAID"
    assert paid["balance_cents"] == 0
    hold = find_hold(citation_id=cit["id"], hold_type="NONPAYMENT_HOLD")
    assert hold is not None and hold["status"] == "RELEASED"
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["license_status"] == "VALID"


def test_payment_paid_cascade_quashes_warrant(api):
    """PRD §3.4: "any active warrant for the citation is quashed and the driver's
    `fta_warrant_active` flag is re-derived; and any active installment plan is
    marked `COMPLETED` with its remaining scheduled installments flipped to `PAID`."

    Design: Difficulty/transitive_cascade/payment_paid_releases_hold_rederives_license_reevaluates_points
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-04T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    api.assess_citation(cit["id"], CLERK)
    contest = file_contest(cit["id"], driver["id"])
    from test_helpers.factories import create_schedule_payload
    api.schedule_hearing(contest["id"], create_schedule_payload("2026-03-01T00:00:00Z"), CLERK)
    set_clock("2026-03-02T00:00:00Z")
    api.fail_to_appear(contest["id"], CLERK)  # ACTIVE warrant + FTA_HOLD
    pay_citation_in_full(
        validate_success(api.get_citation(cit["id"], CLERK), 200), driver["id"]
    )
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["fta_warrant_active"] is False


def test_school_completion_masks_points_releases_point_suspension(api):
    """PRD §3.9: "Masking the entries re-evaluates the driver's point suspension and
    may release a point-suspension hold, re-deriving the driver's `license_status`."
    PRD §3.8: "When the balance later falls below the threshold, any open
    point-suspension hold becomes eligible for release."

    Design: Difficulty/transitive_cascade/school_completion_masks_points_releases_point_suspension
    """
    # Jurisdiction with school_eligible_max_points=2; two UPHELD 2-pt citations -> SUSPENDED.
    jur, driver, cit_a, cit_b = setup_driver_suspended_two_upholds(
        jurisdiction_overrides={
            "name": "Court C", "state_code": "AZ", "school_eligible_max_points": 2
        }
    )
    suspended = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert suspended["license_status"] == "SUSPENDED"
    # Pay citation A in full, enroll, and complete school -> mask 2 points -> balance 2.
    pay_citation_in_full(
        validate_success(api.get_citation(cit_a["id"], CLERK), 200), driver["id"]
    )
    enrollment = validate_success(
        api.create_enrollment(
            cit_a["id"], create_enrollment_payload("2026-04-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    completed = validate_success(api.complete_enrollment(enrollment["id"], CLERK), 200)
    assert completed["points_reduced"] == 2
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["point_balance"] == 2
    hold = find_hold(driver_id=driver["id"], hold_type="POINT_SUSPENSION")
    assert hold is not None and hold["status"] == "RELEASED"
    assert driver_after["license_status"] == "VALID"


def test_school_completion_reduces_points_to_eligible_cap(api):
    """PRD §3.9: "On completion the server freezes `points_reduced` as the smaller of
    the enrollment's `eligible_points` and the candidate total — the sum of `points`
    across the citation's still-`ACTIVE` point ledger entries — and masks that many
    points' worth of those entries by flipping their `state` from `ACTIVE` to
    `MASKED`."

    Design: Difficulty/transitive_cascade/school_completion_masks_points_releases_point_suspension
    """
    jur, driver, cit_a, cit_b = setup_driver_suspended_two_upholds(
        jurisdiction_overrides={
            "name": "Court C", "state_code": "AZ", "school_eligible_max_points": 2
        }
    )
    pay_citation_in_full(
        validate_success(api.get_citation(cit_a["id"], CLERK), 200), driver["id"]
    )
    enrollment = validate_success(
        api.create_enrollment(
            cit_a["id"], create_enrollment_payload("2026-04-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    # eligible_points frozen at enrollment = the 2 points on citation A's charge.
    assert enrollment["eligible_points"] == 2
    completed = validate_success(api.complete_enrollment(enrollment["id"], CLERK), 200)
    assert completed["points_reduced"] == 2


def test_late_penalty_hold_then_payment_conserves_open_hold_count(api):
    """PRD §3.6: "opens a nonpayment **LicenseHold** for the citation if none is
    already open, re-deriving the driver's `license_status` to `HELD`."
    PRD §3.4: "Reaching `PAID` sets off the deepest cascade in the system: any open
    nonpayment or failure-to-appear hold for this citation is released; releasing
    each hold re-derives the driver's `license_status`; that re-derivation
    re-evaluates the driver's point suspension; any active warrant for the citation
    is quashed and the driver's `fta_warrant_active` flag is re-derived; and any
    active installment plan is marked `COMPLETED` with its remaining scheduled
    installments flipped to `PAID`."

    Design: Difficulty/compensating_invariant/late_penalty_hold_then_payment_conserves_open_hold_count
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-04T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    api.assess_citation(cit["id"], CLERK)  # balance 29000
    set_clock("2026-02-11T00:00:00Z")
    api.apply_late_penalty(cit["id"], CLERK)  # balance 32000, 1 OPEN NONPAYMENT_HOLD, HELD
    open_holds = list_license_holds(driver_id=driver["id"], status="OPEN")
    assert len(open_holds) == 1
    # Pay it down: 30000 then 2000 (total 32000) -> PAID -> hold released, count back to 0.
    api.create_payment(
        cit["id"], create_payment_payload(30000, method="CARD"),
        make_driver_headers(driver["id"]),
    )
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(2000, method="CARD"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    paid = validate_success(api.get_citation(cit["id"], CLERK), 200)
    assert paid["financial_status"] == "PAID"
    open_after = list_license_holds(driver_id=driver["id"], status="OPEN")
    assert len(open_after) == 0
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["license_status"] == "VALID"


def test_late_penalty_opens_nonpayment_hold(api):
    """PRD §3.6: "Applying it once adds the jurisdiction's `late_penalty_cents` to
    `penalty_cents`, sets `late_penalty_applied` true, recomputes the balance, and —
    as a cascade — opens a nonpayment **LicenseHold** for the citation if none is
    already open, re-deriving the driver's `license_status` to `HELD`."

    Design: Difficulty/compensating_invariant/late_penalty_hold_then_payment_conserves_open_hold_count
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-04T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    api.assess_citation(cit["id"], CLERK)
    set_clock("2026-02-11T00:00:00Z")
    after = validate_success(api.apply_late_penalty(cit["id"], CLERK), 200)
    assert after["penalty_cents"] == 3000
    assert after["late_penalty_applied"] is True
    assert after["balance_cents"] == 32000
    hold = find_hold(citation_id=cit["id"], hold_type="NONPAYMENT_HOLD", status="OPEN")
    assert hold is not None
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["license_status"] == "HELD"


def test_plan_default_opens_nonpayment_hold(api):
    """PRD §3.6: "Default moves the plan from `ACTIVE` to `DEFAULTED`, flips every
    past-due installment to `MISSED`, and cascades a nonpayment hold open for the
    citation if none is already open, re-deriving the driver's `license_status` to
    `HELD`."

    Design: Corner/cross_cutting/cascade_default_opens_nonpayment_hold
    """
    set_clock("2026-01-20T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    cit = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-04T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(create_charge_payload(cit["id"], base_fine_cents=20000, points=1), CLERK)
    assessed = validate_success(api.assess_citation(cit["id"], CLERK), 200)
    plan = validate_success(
        api.create_installment_plan(
            cit["id"],
            create_installment_plan_payload(4, assessed["version"],
                                            first_due_at="2026-03-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    set_clock("2026-03-02T00:00:00Z")  # installment 1 past due, unpaid
    defaulted = validate_success(api.mark_default(plan["id"], CLERK), 200)
    assert defaulted["status"] == "DEFAULTED"
    hold = find_hold(citation_id=cit["id"], hold_type="NONPAYMENT_HOLD", status="OPEN")
    assert hold is not None
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["license_status"] == "HELD"
