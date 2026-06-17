"""Scoring arithmetic and fee calculations.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    make_clerk_headers,
    make_examiner_headers,
    create_fee_payment_payload,
    create_license_payload,
    renew_license_payload,
    eligible_record_with_passed_appointment,
    active_licensed_record,
    setup_served_suspension,
    get_record_version,
    capture_fee,
)

CLERK = make_clerk_headers("clerk-1")


# ===========================================================================
# dual_variant_calc / road_test_provisional_vs_final_diverge
# ===========================================================================
def test_road_test_provisional_and_final_scores_diverge(api):
    """PRD §3.5: "for each maneuver the system multiplies its `weight` by the
    relevant value, sums those products across all maneuvers, divides by the sum
    of the weights, and rounds the result half up to two decimal places."
    PRD §3.5: "the resulting `provisional_score` is advisory and is never allowed
    to decide the pass/fail result."
    PRD §3.4: "the system computes `final_score` and sets `outcome` to `PASS` when
    `final_score` is at least the road-test passing threshold of 80, and to `FAIL`
    otherwise."

    Provisional auto inputs (3*90+2*70+1*85)/6 = 82.5; examiner-adjusted final
    (3*90+2*60+1*85)/6 = 79.17 -> outcome FAIL.

    Design: Difficulty/dual_variant_calc/road_test_provisional_vs_final_diverge
    """
    ctx = eligible_record_with_passed_appointment(
        license_class="D", dob="1986-03-02", opaque_user_id="exu-1",
        full_name="Ann Driver",
        auto_items=[("PARALLEL", 3, 90), ("MERGE", 2, 70), ("STOP", 1, 85)],
        score_items=[("PARALLEL", 3, 90), ("MERGE", 2, 60), ("STOP", 1, 85)],
    )
    appt = ctx["appointment"]
    assert appt["provisional_score"] == 82.5, f"got {appt['provisional_score']}"
    assert appt["final_score"] == 79.17, f"got {appt['final_score']}"
    assert appt["outcome"] == "FAIL", f"got {appt['outcome']}"
    assert appt["provisional_score"] != appt["final_score"]


def test_provisional_score_does_not_decide_outcome(api):
    """PRD §3.4: "Only `final_score` decides the outcome and downstream license
    eligibility; the earlier `provisional_score` is advisory and never decides
    pass or fail."
    PRD §3.4: "the system computes `final_score` and sets `outcome` to `PASS` when
    `final_score` is at least the road-test passing threshold of 80, and to `FAIL`
    otherwise."

    Provisional 82.5 (>=80) yet final 79.17 (<80) -> outcome is FAIL, proving the
    advisory provisional did not carry the pass.

    Design: Difficulty/dual_variant_calc/road_test_provisional_vs_final_diverge
    """
    ctx = eligible_record_with_passed_appointment(
        license_class="D", dob="1986-03-02", opaque_user_id="exu-1b",
        full_name="Ann Driver 2",
        auto_items=[("PARALLEL", 3, 90), ("MERGE", 2, 70), ("STOP", 1, 85)],
        score_items=[("PARALLEL", 3, 90), ("MERGE", 2, 60), ("STOP", 1, 85)],
    )
    appt = ctx["appointment"]
    assert appt["provisional_score"] >= 80
    assert appt["final_score"] < 80
    assert appt["outcome"] == "FAIL"


# ===========================================================================
# dual_variant_calc / reinstatement_fee_per_component_vs_sum_then_round
# combinatorial_formula / reinstatement_fee_rounding_order_pinned
# (both assert per-component rounding -> 188.13 at pb_at_reinstatement == 12)
# ===========================================================================
def test_reinstatement_fee_per_component_rounding_equals_18813(api):
    """PRD §3.7: "The reinstatement_fee is built from three components, each
    rounded to two decimals half-up *before* they are summed — the order is fixed
    and must not be replaced by summing first and rounding once."
    PRD §3.7: "The point component is point_balance_at_reinstatement multiplied by
    8.333 dollars per point, rounded to two decimals."

    At point_balance_at_reinstatement == 12: base 75.00, point round(12*8.333)=99.996
    -> 100.00, admin round(0.075*(75.00+100.00))=13.13, total 188.13 (per-component);
    sum-then-round would give 188.12.

    Design: Difficulty/dual_variant_calc/reinstatement_fee_per_component_vs_sum_then_round
    """
    ctx = setup_served_suspension(full_name="Bob Rein", opaque_user_id="exu-2")
    record, suspension = ctx["record"], ctx["suspension"]
    capture_fee(record["id"], "REINSTATEMENT", 18813)
    version = get_record_version(record["id"])
    reinstated = validate_success(
        api.reinstate_suspension(
            suspension["id"], {"expected_driver_record_version": version}, CLERK,
        ),
        200,
    )
    assert reinstated["point_balance_at_reinstatement"] == 12
    assert reinstated["reinstatement_fee"] == 188.13, f"got {reinstated['reinstatement_fee']}"
    assert reinstated["status"] == "LIFTED_BY_REINSTATEMENT"
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "ACTIVE"


def test_reinstatement_fee_is_not_sum_then_round(api):
    """PRD §3.7: "The reinstatement_fee is built from three components, each
    rounded to two decimals half-up *before* they are summed — the order is fixed
    and must not be replaced by summing first and rounding once."

    The pinned per-component order yields 188.13, distinct from the 188.12 a
    sum-then-round implementation would produce.

    Design: Difficulty/dual_variant_calc/reinstatement_fee_per_component_vs_sum_then_round
    """
    ctx = setup_served_suspension(full_name="Dan Round", opaque_user_id="exu-4")
    record, suspension = ctx["record"], ctx["suspension"]
    capture_fee(record["id"], "REINSTATEMENT", 18813)
    version = get_record_version(record["id"])
    reinstated = validate_success(
        api.reinstate_suspension(
            suspension["id"], {"expected_driver_record_version": version}, CLERK,
        ),
        200,
    )
    assert reinstated["reinstatement_fee"] == 188.13
    assert reinstated["reinstatement_fee"] != 188.12


def test_reinstatement_fee_rounding_order_pinned_value(api):
    """PRD §3.7: "The base component is 75.00 dollars rounded to two decimals."
    PRD §3.7: "The admin component is 7.5 percent of the sum of the base
    component and the point component, rounded to two decimals. The
    reinstatement_fee is then the sum of those three rounded components, itself
    rounded to two decimals."

    Design: Difficulty/combinatorial_formula/reinstatement_fee_rounding_order_pinned
    """
    ctx = setup_served_suspension(full_name="Dan Round 2", opaque_user_id="exu-4b")
    record, suspension = ctx["record"], ctx["suspension"]
    capture_fee(record["id"], "REINSTATEMENT", 18813)
    version = get_record_version(record["id"])
    reinstated = validate_success(
        api.reinstate_suspension(
            suspension["id"], {"expected_driver_record_version": version}, CLERK,
        ),
        200,
    )
    assert reinstated["reinstatement_fee"] == 188.13


def test_reinstatement_fee_point_component_drives_total(api):
    """PRD §3.7: "The point component is point_balance_at_reinstatement multiplied
    by 8.333 dollars per point, rounded to two decimals."
    PRD §3.7: "The reinstatement_fee is then the sum of those three rounded
    components, itself rounded to two decimals."

    At point_balance_at_reinstatement == 12, the snapshot is recorded and the
    pinned per-component total is 188.13.

    Design: Difficulty/combinatorial_formula/reinstatement_fee_rounding_order_pinned
    """
    ctx = setup_served_suspension(full_name="Dan Round 3", opaque_user_id="exu-4c")
    record, suspension = ctx["record"], ctx["suspension"]
    capture_fee(record["id"], "REINSTATEMENT", 18813)
    version = get_record_version(record["id"])
    reinstated = validate_success(
        api.reinstate_suspension(
            suspension["id"], {"expected_driver_record_version": version}, CLERK,
        ),
        200,
    )
    assert reinstated["point_balance_at_reinstatement"] == 12
    assert reinstated["reinstatement_fee"] == 188.13


# ===========================================================================
# combinatorial_formula / renewal_fee_nested_minmax_branches
# ===========================================================================
def test_renewal_fee_senior_realid_class_d_equals_5000(api):
    """PRD §3.6: "A senior discount of 2000 cents applies when the applicant's age
    (the reference year 2026 minus the birth year from date_of_birth) is at least
    65; otherwise the discount is zero. A REAL ID surcharge of 3000 cents applies
    when is_real_id is true; otherwise it is zero."
    PRD §3.6: "The base minus the senior discount is floored at zero before
    anything is added, and then the REAL ID surcharge and the late penalty are
    added on top to give fee_cents."

    Class D base 4000, senior (age 70) discount 2000, REAL ID surcharge 3000,
    days_late 0 -> max(4000-2000,0)+3000+0 = 5000.

    Design: Difficulty/combinatorial_formula/renewal_fee_nested_minmax_branches
    """
    record = get_success_data(
        api.create_driver_record(
            {"full_name": "Cara Senior", "date_of_birth": "1956-05-05", "state_code": "CA"},
            CLERK,
        )
    )
    api.real_id_submit(
        record["id"],
        {"documents": [
            {"doc_type": "PASSPORT", "category": "IDENTITY"},
            {"doc_type": "LEASE", "category": "RESIDENCY"},
            {"doc_type": "SSN_CARD", "category": "SSN"},
        ]},
        CLERK,
    )
    api.real_id_adjudicate(record["id"], {"decision": "APPROVE"}, CLERK)
    # Knowledge pass + scored PASS appointment, examiner distinct from issuing clerk.
    from test_helpers import pass_knowledge_test, create_examiner, scored_appointment
    pass_knowledge_test(record["id"])
    examiner = create_examiner(certified_classes=["D"], opaque_user_id="exu-3")
    appt = scored_appointment(record["id"], examiner, license_class="D")
    capture_fee(record["id"], "RENEWAL", 5000)
    lic = validate_success(
        api.create_license(
            create_license_payload(record["id"], appt["id"], license_class="D", is_real_id=True),
            CLERK,
        ),
        201,
    )
    assert lic["fee_cents"] == 5000, f"got {lic['fee_cents']}"
    assert lic["is_real_id"] is True
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "ACTIVE"


def test_renewal_fee_base_floored_at_zero_with_surcharge(api):
    """PRD §3.6: "The base is the per-class fee for the chosen license_class: 4000
    for class D, 3500 for M, 6000 for A, 6000 for B, and 5500 for C."
    PRD §3.6: "The base minus the senior discount is floored at zero before
    anything is added, and then the REAL ID surcharge and the late penalty are
    added on top to give fee_cents."

    Non-senior, non-real-id class D first issuance: max(4000-0,0)+0+0 = 4000.

    Design: Difficulty/combinatorial_formula/renewal_fee_nested_minmax_branches
    """
    ctx = active_licensed_record(
        license_class="D", dob="1986-01-01", opaque_user_id="exu-3b",
        full_name="Non Senior",
    )
    lic = ctx["license"]
    assert lic["fee_cents"] == 4000, f"got {lic['fee_cents']}"
