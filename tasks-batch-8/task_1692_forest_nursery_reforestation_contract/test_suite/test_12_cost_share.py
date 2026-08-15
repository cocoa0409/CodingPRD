"""Cost-share enrollments: per-component rounding, the review loop, and the
documented-acreage ceiling."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_landowner, create_enrollment, submit_enrollment,
    make_landowner_headers,
)

CO = TEST_USERS["contract_officer_headers"]
PA = TEST_USERS["program_administrator_headers"]


def test_cost_share_provisional_award_at_create(api):
    """PRD §3.7: "The base component is the acreage basis multiplied by
    `rate_per_acre_cents`, rounded half-up to a whole cent. The stewardship
    bonus is ten percent of that base, likewise rounded half-up to a whole cent.
    The award is the sum of base and bonus, capped at the enrollment's
    `cap_cents`." and "The provisional variant uses `enrolled_acres` as the
    basis at creation"

    Design: Difficulty/combinatorial_formula/cost_share_award_component_rounding
    """
    lo = create_landowner()
    enr = create_enrollment(lo["id"], enrolled_acres=40, rate_per_acre_cents=15001,
                            cap_cents=99999999)
    # base = round(40 * 15001) = 600040; bonus = round(600040 * 0.10) = 60004
    assert enr["provisional_award_cents"] == 660044, (
        f"provisional award from enrolled acres: 600040 + 60004 = 660044, "
        f"got {enr['provisional_award_cents']}"
    )
    assert enr["status"] == "DRAFT"


def test_cost_share_final_award_per_component_rounding(api):
    """PRD §3.7: "Each component is rounded to whole cents before the two are
    summed; summing first and rounding once is not permitted." and "The
    provisional variant uses `enrolled_acres` as the basis at creation and is
    recomputed from `documented_acres` at submit; the final variant, computed at
    approval, uses `documented_acres` and therefore diverges from the original
    provisional whenever documented and enrolled acreage differ."

    Design: Difficulty/combinatorial_formula/cost_share_award_component_rounding
    """
    lo = create_landowner()
    enr = create_enrollment(lo["id"], enrolled_acres=40, rate_per_acre_cents=15001,
                            cap_cents=99999999)
    prov_create = enr["provisional_award_cents"]

    submitted = submit_enrollment(enr["id"], lo["id"], 33.33, 499983)
    # base = round_half_up(33.33 * 15001) = 499983; bonus = round_half_up(499983 * 0.10) = 49998
    assert submitted["provisional_award_cents"] == 549981, (
        f"provisional recomputed from documented acres: 499983 + 49998 = 549981, "
        f"got {submitted['provisional_award_cents']}"
    )

    approved = get_success_data(api.approve_cost_share_enrollment(enr["id"], PA))
    assert approved["final_award_cents"] == 549981, (
        "per-component rounding: 499983 + 49998 = 549981; the forbidden "
        f"sum-then-round would give 549982, got {approved['final_award_cents']}"
    )
    assert prov_create != approved["final_award_cents"], (
        "provisional (enrolled basis) and final (documented basis) diverge"
    )
    assert approved["status"] == "APPROVED"


def test_enrollment_return_for_correction_loop(api):
    """PRD §3.7: "Returning one for correction moves it from `UNDER_REVIEW` back
    to `DRAFT` and requires a non-empty `reason`; the submit-and-return loop may
    cycle without limit." and "recomputing the provisional award from the
    documented acreage"

    Design: Corner/state_machines/enrollment_return_for_correction_loop
    """
    lo = create_landowner()
    enr = create_enrollment(lo["id"], enrolled_acres=10, rate_per_acre_cents=15000,
                            cap_cents=200000)

    submitted = submit_enrollment(enr["id"], lo["id"], 8, 70000)
    assert submitted["status"] == "UNDER_REVIEW"
    assert submitted["provisional_award_cents"] == 132000, (
        f"8 acres: 120000 base + 12000 bonus = 132000, "
        f"got {submitted['provisional_award_cents']}"
    )

    returned = get_success_data(
        api.return_enrollment_for_correction(enr["id"], {"reason": "missing invoices"}, PA)
    )
    assert returned["status"] == "DRAFT"

    resubmitted = submit_enrollment(enr["id"], lo["id"], 9, 80000)
    assert resubmitted["status"] == "UNDER_REVIEW"
    assert resubmitted["provisional_award_cents"] == 148500, (
        f"9 acres: 135000 base + 13500 bonus = 148500, "
        f"got {resubmitted['provisional_award_cents']}"
    )


def test_enrollment_documented_acres_exceeded(api):
    """PRD §3.7: "recording the verified `documented_acres` — which must be
    positive and no greater than `enrolled_acres`, otherwise
    `ERR_ENROLLMENT_ACRES_EXCEEDED`"

    Design: Corner/validations/enrollment_documented_acres_exceeded
    """
    lo = create_landowner()
    enr = create_enrollment(lo["id"], enrolled_acres=10, rate_per_acre_cents=15000,
                            cap_cents=200000)

    res = api.submit_cost_share_enrollment(
        enr["id"], {"documented_acres": 11, "documented_cost_cents": 90000},
        make_landowner_headers(lo["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_ACRES_EXCEEDED)
