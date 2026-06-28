"""Tuition discount engine: dual-variant (provisional vs invoiced snapshot) and
combinatorial pinned-rounding-order / non-linear multi-class+family interaction.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADMIN_H = TEST_USERS["admin_headers"]


# =========================================================================
# Rule 1 — dual_variant_calc
# =========================================================================
def test_invoiced_snapshot_frozen_when_sibling_enrollment_drops(api):
    """PRD §3.3: "The invoiced figure is a frozen snapshot: at invoice generation the
    then-current `monthly_charge_cents` of each billing-active enrollment is summed, and a
    later drop does not retroactively alter an already-generated invoice."
    PRD §3.3: "the second class is discounted by ten percent; the third and any further class
    are discounted by twenty percent."

    The provisional Enrollment.monthly_charge_cents recomputes when classB drops, but the
    already-generated Invoice.tuition_cents stays frozen at the pre-drop snapshot.

    Design: Difficulty/dual_variant_calc/tuition_provisional_vs_invoiced_snapshot
    """
    env = fx.setup_open_term_two_sections(
        secA_overrides={"discipline": "JAZZ", "monthly_tuition_cents": 10000},
        secB_overrides={"discipline": "TAP", "monthly_tuition_cents": 7000},
    )
    family = fx.create_family()
    student = fx.create_student(family["id"], full_name="Ada", birth_date="2014-05-01", level="ELITE")
    enr_a = fx.create_enrollment(student["id"], env["secA"]["id"])
    enr_b = fx.create_enrollment(student["id"], env["secB"]["id"])
    # Provisional: classA=10000 (1st), classB=6300 (2nd, mc10%), single-student family.
    invoice = fx.generate_invoice(family["id"], env["term"]["id"], "2026-03")
    assert invoice["tuition_cents"] == 16300, f"snapshot should be 16300, got {invoice['tuition_cents']}"

    # Trigger: drop classB.
    validate_success(api.drop_enrollment(enr_b["id"], ADMIN_H))

    enr_a_after = validate_success(api.get_enrollment(enr_a["id"], ADMIN_H))
    invoice_after = validate_success(api.get_invoice(invoice["id"], ADMIN_H))
    assert enr_a_after["monthly_charge_cents"] == 10000, "provisional classA charge unchanged at 10000"
    assert invoice_after["tuition_cents"] == 16300, "invoiced snapshot must stay frozen at 16300"
    assert invoice_after["status"] == "OPEN"


def test_chaperone_threshold_calc_independent_of_tuition_tier(api):
    """PRD §3.7: "the number of chaperones required is the `participant_count` divided by the
    `chaperone_ratio` and rounded up to the next whole number, and this required count must be
    at most the `chaperone_count`."
    PRD §3.7: "On confirmation the trip moves to `CONFIRMED`."

    ceil(4/4)=1 <= 1 chaperone, so the trip confirms — a ceil-threshold over TravelTrip counts,
    a different calc shape and domain than the tuition tiered-discount.

    Design: Difficulty/dual_variant_calc/chaperone_threshold_vs_tuition_tier_distinct_domains
    """
    setup = fx.setup_proposed_trip(num_participants=4, chaperone_ratio=4, chaperone_count=1,
                                   per_member_cost_cents=50000, min_level="NOVICE")
    trip_after = validate_success(api.confirm_trip(setup["trip"]["id"], ADMIN_H))
    assert trip_after["status"] == "CONFIRMED"
    assert trip_after["participant_count"] == 4


# =========================================================================
# Rule 2 — combinatorial_formula
# =========================================================================
def test_tuition_pinned_rounding_order_per_line(api):
    """PRD §3.3: "apply the multi-class percentage and round that intermediate result half up to
    a whole cent; then apply the family percentage to that rounded figure and round half up again
    to a whole cent."
    PRD §3.3: "the family percentage is never folded into the multi-class percentage, and totals
    are never summed before rounding."

    classB base 5005, 2nd class (mc 10%), 2-student family (family 5%): pinned order gives
    round(5005*0.9)=4505 then round(4505*0.95)=4280 (single-round-at-end would give 4279).

    Design: Difficulty/combinatorial_formula/tuition_rounding_order_pinned_per_line
    """
    term = fx.create_term(monthly_billing_day=10)
    room = fx.create_room(capacity=20)
    instructor = fx.create_instructor()
    secA = fx.create_section(term["id"], room["id"], instructor["id"],
                             discipline="BALLET", monthly_tuition_cents=9000)
    fx.add_session(secA["id"], day_of_week=1, start_minute=600, end_minute=660)
    secB = fx.create_section(term["id"], room["id"], instructor["id"],
                             discipline="TAP", monthly_tuition_cents=5005)
    fx.add_session(secB["id"], day_of_week=1, start_minute=700, end_minute=760)
    secC = fx.create_section(term["id"], room["id"], instructor["id"],
                             discipline="JAZZ", monthly_tuition_cents=7000)
    fx.add_session(secC["id"], day_of_week=1, start_minute=800, end_minute=860)
    get_success_data(api.open_term(term["id"], ADMIN_H))

    family = fx.create_family()
    s1 = fx.create_student(family["id"], full_name="S One", level="ELITE")
    s2 = fx.create_student(family["id"], full_name="S Two", level="ELITE")
    enr_a = fx.create_enrollment(s1["id"], secA["id"])
    enr_c = fx.create_enrollment(s2["id"], secC["id"])
    # Trigger: enroll s1 into classB as the 2nd class.
    resp = api.create_enrollment(f.create_enrollment_payload(s1["id"], secB["id"]), ADMIN_H)
    enr_b = validate_success(resp, expected_status=201)

    assert enr_b["monthly_charge_cents"] == 4280, \
        f"classB pinned-order charge should be 4280, got {enr_b['monthly_charge_cents']}"
    enr_a_after = validate_success(api.get_enrollment(enr_a["id"], ADMIN_H))
    enr_c_after = validate_success(api.get_enrollment(enr_c["id"], ADMIN_H))
    # s1 classA: 1st class 9000 *0.95 family = 8550; s2 classC: 1st class 7000 *0.95 = 6650.
    assert enr_a_after["monthly_charge_cents"] == 8550
    assert enr_c_after["monthly_charge_cents"] == 6650


def test_tuition_nonlinear_multiclass_family_interaction(api):
    """PRD §3.3: "A student's first class gets no discount; the second class is discounted by ten
    percent; the third and any further class are discounted by twenty percent."
    PRD §3.3: "those active enrollments are sorted by their section's `monthly_tuition_cents`
    descending, breaking ties by `created_at` ascending (never by `id`)."

    One student in three classes (12000, 9000, 6000), single-student family (0% family):
    ranked by tuition DESC -> 12000(1st,0%), 9000(2nd,mc10%)->8100, 6000(3rd,mc20%)->4800.

    Design: Difficulty/combinatorial_formula/tuition_nonlinear_multiclass_family_interaction
    """
    env = fx.setup_open_term_three_sections(tuitions=(12000, 9000, 6000))
    sections = env["sections"]
    family = fx.create_family()
    student = fx.create_student(family["id"], full_name="Only Child", level="ELITE")
    enr_a = fx.create_enrollment(student["id"], sections[0]["id"])
    enr_b = fx.create_enrollment(student["id"], sections[1]["id"])
    resp = api.create_enrollment(f.create_enrollment_payload(student["id"], sections[2]["id"]), ADMIN_H)
    enr_c = validate_success(resp, expected_status=201)

    enr_a_after = validate_success(api.get_enrollment(enr_a["id"], ADMIN_H))
    enr_b_after = validate_success(api.get_enrollment(enr_b["id"], ADMIN_H))
    assert enr_a_after["monthly_charge_cents"] == 12000
    assert enr_b_after["monthly_charge_cents"] == 8100
    assert enr_c["monthly_charge_cents"] == 4800
