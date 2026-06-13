"""Numeric/temporal boundaries, validation-priority conflicts, cross-entity gates."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_citation_payload,
    create_charge_payload,
    create_payment_payload,
    create_enrollment_payload,
    create_schedule_payload,
    create_decide_payload,
    make_driver_headers,
)
from test_helpers.fixtures import (
    setup_jurisdiction_and_driver,
    setup_assessed_citation,
    setup_driver_suspended_two_upholds,
    file_contest,
    pay_citation_in_full,
    set_clock,
    find_hold,
    list_license_holds,
    CLERK,
    HEARING,
    DMV,
)


def test_point_suspension_threshold_inclusive_boundary(api):
    """PRD §3.8: "the suspension boundary is inclusive: when the `point_balance` is
    greater than or equal to the jurisdiction's `point_suspension_threshold`, the
    system opens a point-suspension hold if none is open and the driver's
    `license_status` becomes `SUSPENDED`; a balance of exactly threshold-minus-one
    does not suspend."

    Design: Difficulty/boundary_precision_check/point_suspension_threshold_inclusive_boundary
    """
    # Two UPHELD 2-point citations reach exactly 4 == threshold -> SUSPENDED.
    jur, driver, cit_a, cit_b = setup_driver_suspended_two_upholds()
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["point_balance"] == 4
    assert driver_after["license_status"] == "SUSPENDED"
    hold = find_hold(driver_id=driver["id"], hold_type="POINT_SUSPENSION", status="OPEN")
    assert hold is not None


def test_point_suspension_below_threshold_not_suspended(api):
    """PRD §3.8: "a balance of exactly threshold-minus-one does not suspend."

    Design: Difficulty/boundary_precision_check/point_suspension_threshold_inclusive_boundary
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver = setup_jurisdiction_and_driver()
    # One 2-point and one 1-point UPHELD citation -> point_balance 3 (== threshold-1).
    for i, points in enumerate((2, 1)):
        cit = validate_success(
            api.create_citation(
                create_citation_payload(
                    driver["id"], issued_at=f"2026-01-0{i + 2}T00:00:00Z",
                    appear_by=f"2026-02-0{i + 2}T00:00:00Z",
                ),
                CLERK,
            ),
            201,
        )
        api.create_charge(
            create_charge_payload(
                cit["id"], violation_code="VC23103", description="Reckless",
                base_fine_cents=10000, points=points,
            ),
            CLERK,
        )
        api.assess_citation(cit["id"], CLERK)
        contest = file_contest(cit["id"], driver["id"])
        api.schedule_hearing(contest["id"], create_schedule_payload(f"2026-03-0{i + 1}T00:00:00Z"), CLERK)
        api.decide_contest(contest["id"], create_decide_payload("UPHOLD"), HEARING)
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["point_balance"] == 3
    assert driver_after["license_status"] != "SUSPENDED"


def test_collections_age_days_boundary_via_referral(api):
    """PRD §3.10: "Referral is eligible only when the citation has aged at least the
    jurisdiction's `collections_age_days` past its `appear_by`, with the age
    measured as the whole number of days (the floor of the elapsed seconds divided
    by 86,400) between the deadline and now; the boundary is inclusive, so day N of
    the threshold qualifies while day N-minus-one does not."
    PRD §3.10: "computes `collections_fee_cents` as that outstanding amount
    multiplied by the jurisdiction's `collections_fee_pct`, rounded half-up to a
    whole cent."

    Design: Difficulty/boundary_precision_check/collections_age_days_boundary_via_referral
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    assert cit["balance_cents"] == 29000
    set_clock("2026-03-06T00:00:00Z")  # exactly 30 days past appear_by
    referral = validate_success(api.create_collections_referral(cit["id"], CLERK), 201)
    assert referral["status"] == "REFERRED"
    assert referral["outstanding_at_referral_cents"] == 29000
    # round_half_up(29000 * 0.25) = 7250
    assert referral["collections_fee_cents"] == 7250
    citation = validate_success(api.get_citation(cit["id"], CLERK), 200)
    assert citation["balance_cents"] == 36250  # 29000 + 7250


def test_collections_referral_before_age_threshold_rejected(api):
    """PRD §3.10: "Referral is eligible only when the citation has aged at least the
    jurisdiction's `collections_age_days` past its `appear_by` ... A referral
    attempted before the citation is eligible is rejected with `ERR_NOT_YET_LATE`."

    Design: Difficulty/boundary_precision_check/collections_age_days_boundary_via_referral
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    set_clock("2026-03-05T00:00:00Z")  # 29 days past appear_by (< 30, inclusive boundary)
    res = api.create_collections_referral(cit["id"], CLERK)
    validate_error(res, "ERR_NOT_YET_LATE")


def test_owner_vs_state_on_void_citation_owner_wins(api):
    """PRD §2.9: "For driver-initiated actions, resource ownership is checked next,
    yielding `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.9: "Only then are state-machine preconditions evaluated, with an
    out-of-state target yielding `ERR_INVALID_STATE`; followed by time-gating checks
    yielding `ERR_NOT_YET_LATE`; followed by the remaining business constraints
    described throughout §3."
    PRD §2.1: "the citation (or the citation behind the plan or enrollment) must
    belong to that driver — its `driver_id` must equal `X-User-ID` — or the request
    is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/owner_vs_state_on_partial_payment_owner_wins
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    # Void the citation (CourtClerk).
    validate_success(api.void_citation(cit["id"], CLERK), 200)
    # A second driver (not the owner) attempts to pay the VOID citation.
    other_driver = validate_success(
        api.create_driver(
            {"jurisdiction_id": jur["id"], "license_number": "OTHER-1", "full_name": "Other"},
            CLERK,
        ),
        201,
    )
    res = api.create_payment(
        cit["id"], create_payment_payload(1000, method="CARD"),
        make_driver_headers(other_driver["id"]),
    )
    # Ownership (priority 4) beats state (priority 5).
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_owner_check_precedes_state_on_partial_payment(api):
    """PRD §2.9: "For driver-initiated actions, resource ownership is checked next,
    yielding `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.9: "Only then are state-machine preconditions evaluated, with an
    out-of-state target yielding `ERR_INVALID_STATE`; followed by time-gating checks
    yielding `ERR_NOT_YET_LATE`; followed by the remaining business constraints
    described throughout §3."

    Design: Difficulty/priority_pair_validation_conflict/owner_vs_state_on_partial_payment_owner_wins
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    validate_success(api.void_citation(cit["id"], CLERK), 200)
    other_driver = validate_success(
        api.create_driver(
            {"jurisdiction_id": jur["id"], "license_number": "OTHER-2", "full_name": "Other Two"},
            CLERK,
        ),
        201,
    )
    res = api.create_payment(
        cit["id"], create_payment_payload(500, method="CASH"),
        make_driver_headers(other_driver["id"]),
    )
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_not_yet_late_vs_already_applied_on_late_penalty(api):
    """PRD §2.9: "Only then are state-machine preconditions evaluated ... followed by
    time-gating checks yielding `ERR_NOT_YET_LATE`; followed by the remaining
    business constraints described throughout §3."
    PRD §3.6: "The server clock must have reached or passed the `appear_by` deadline
    — an attempt before that instant is rejected with `ERR_NOT_YET_LATE` — and the
    penalty must not already have been applied, guarded by the `late_penalty_applied`
    flag; a second attempt is rejected with `ERR_PENALTY_ALREADY_APPLIED`."

    Design: Difficulty/priority_pair_validation_conflict/not_yet_late_vs_already_applied_on_late_penalty
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    set_clock("2026-02-11T00:00:00Z")
    validate_success(api.apply_late_penalty(cit["id"], CLERK), 200)  # applied once
    set_clock("2026-01-20T00:00:00Z")  # rewind to before appear_by
    res = api.apply_late_penalty(cit["id"], CLERK)
    # Time-gating (ERR_NOT_YET_LATE) fires before the already-applied business constraint.
    validate_error(res, "ERR_NOT_YET_LATE", expected_status=409)


def test_late_penalty_after_already_applied_is_time_gated_when_rewound(api):
    """PRD §3.6: "the penalty must not already have been applied, guarded by the
    `late_penalty_applied` flag; a second attempt is rejected with
    `ERR_PENALTY_ALREADY_APPLIED`."
    PRD §2.9: "followed by time-gating checks yielding `ERR_NOT_YET_LATE`; followed
    by the remaining business constraints described throughout §3."

    Design: Difficulty/priority_pair_validation_conflict/not_yet_late_vs_already_applied_on_late_penalty
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    set_clock("2026-02-11T00:00:00Z")
    api.apply_late_penalty(cit["id"], CLERK)
    set_clock("2026-01-20T00:00:00Z")
    res = api.apply_late_penalty(cit["id"], CLERK)
    validate_error(res, "ERR_NOT_YET_LATE", expected_status=409)


def test_school_completion_requires_citation_paid(api):
    """PRD §3.9: "only when the citation's `financial_status` is already `PAID`,
    since the fine must be settled first; an unpaid fine is rejected with
    `ERR_FINE_UNPAID`."

    Design: Difficulty/cross_entity_state_dependency/school_completion_requires_citation_paid
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    # Enroll on an unpaid (ASSESSED) citation, then attempt completion.
    enrollment = validate_success(
        api.create_enrollment(
            cit["id"], create_enrollment_payload("2026-04-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    res = api.complete_enrollment(enrollment["id"], CLERK)
    validate_error(res, "ERR_FINE_UNPAID")
    after = validate_success(api.get_enrollment(enrollment["id"], CLERK), 200)
    assert after["status"] == "ENROLLED"


def test_school_completion_succeeds_once_citation_paid(api):
    """PRD §3.9: "A clerk marks the course **completed**, moving the enrollment from
    `ENROLLED` to `COMPLETED`, but only when the server clock has not yet passed the
    `completion_due_at` — a late completion is rejected with
    `ERR_SCHOOL_DEADLINE_PASSED` — and only when the citation's `financial_status`
    is already `PAID`, since the fine must be settled first; an unpaid fine is
    rejected with `ERR_FINE_UNPAID`."

    Design: Difficulty/cross_entity_state_dependency/school_completion_requires_citation_paid
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit = setup_assessed_citation(
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    enrollment = validate_success(
        api.create_enrollment(
            cit["id"], create_enrollment_payload("2026-04-01T00:00:00Z"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    # Now pay the fine in full (enrollment fee already added to penalty).
    paid_citation = validate_success(api.get_citation(cit["id"], CLERK), 200)
    pay_citation_in_full(paid_citation, driver["id"])
    completed = validate_success(api.complete_enrollment(enrollment["id"], CLERK), 200)
    assert completed["status"] == "COMPLETED"


def test_point_suspension_release_succeeds_once_below_threshold(api):
    """PRD §3.6: "for a point suspension, the driver's `point_balance` must have
    fallen below the jurisdiction's `point_suspension_threshold`."
    PRD §3.6: "A successful release sets `status` to `RELEASED`, stamps
    `released_at`, and re-derives the driver's `license_status`."

    Design: Difficulty/cross_entity_state_dependency/point_suspension_release_requires_driver_below_threshold
    """
    # school_eligible_max_points=2 so we can drop one citation's points via school.
    jur, driver, cit_a, cit_b = setup_driver_suspended_two_upholds(
        jurisdiction_overrides={
            "name": "Court C", "state_code": "AZ", "school_eligible_max_points": 2
        }
    )
    # Drop point_balance from 4 to 2 by completing school on citation A.
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
    api.complete_enrollment(enrollment["id"], CLERK)
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["point_balance"] == 2  # now below threshold 4
    # The point-suspension hold was auto-released by the cascade; the license is VALID.
    assert driver_after["license_status"] == "VALID"


def test_point_suspension_release_requires_driver_below_threshold(api):
    """PRD §3.6: "for a point suspension, the driver's `point_balance` must have
    fallen below the jurisdiction's `point_suspension_threshold`. A release attempted
    while its condition is unmet is rejected with `ERR_HOLD_CONDITION_UNMET`."

    Design: Difficulty/cross_entity_state_dependency/point_suspension_release_requires_driver_below_threshold
    """
    jur, driver, cit_a, cit_b = setup_driver_suspended_two_upholds()
    hold = find_hold(driver_id=driver["id"], hold_type="POINT_SUSPENSION", status="OPEN")
    assert hold is not None
    res = api.release_license_hold(hold["id"], DMV)
    validate_error(res, "ERR_HOLD_CONDITION_UNMET", expected_status=409)
    still_open = find_hold(driver_id=driver["id"], hold_type="POINT_SUSPENSION")
    assert still_open["status"] == "OPEN"


def test_license_status_suspended_outranks_held(api):
    """PRD §2.7: "The `license_status` is `VALID` when the driver has no open holds,
    `HELD` when at least one hold is open but none of them is a point suspension, and
    `SUSPENDED` whenever any open hold is a point suspension — a point suspension
    always dominates a concurrent nonpayment or failure-to-appear hold."

    Design: Corner/calculations/license_status_suspended_outranks_held
    """
    set_clock("2026-01-05T00:00:00Z")
    jur, driver, cit_a, cit_b = setup_driver_suspended_two_upholds()
    # Add a third citation with a late-penalty NONPAYMENT_HOLD.
    cit_c = validate_success(
        api.create_citation(
            create_citation_payload(
                driver["id"], issued_at="2026-01-04T00:00:00Z",
                appear_by="2026-02-04T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    api.create_charge(create_charge_payload(cit_c["id"], base_fine_cents=20000, points=0), CLERK)
    api.assess_citation(cit_c["id"], CLERK)
    set_clock("2026-02-11T00:00:00Z")
    api.apply_late_penalty(cit_c["id"], CLERK)
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["license_status"] == "SUSPENDED"
    open_holds = list_license_holds(driver_id=driver["id"], status="OPEN")
    types = {h["hold_type"] for h in open_holds}
    assert "POINT_SUSPENSION" in types
    assert "NONPAYMENT_HOLD" in types
