"""Autopsy fee and indigent waterfall calculations."""
from test_helpers import (
    validate_success,
    create_investigator, create_pathologist,
    set_clock, create_investigating_case,
    schedule_autopsy, complete_autopsy,
    collect_specimen, send_specimen_to_lab,
    add_property_item, declare_indigent,
    make_pathologist_headers, make_medical_examiner_headers,
)


def test_autopsy_estimate_and_final_diverge_on_specimens(api):
    """PRD §3.4: "It begins from a base fee of 150,000 cents. The requested duration is
    billed per whole 30-minute block, with the block count obtained by dividing
    duration_minutes by 30 and rounding up to the next whole block; each block adds 20,000
    cents on top of the base." PRD §3.4: "A per-specimen add-on is then applied: the system
    counts the specimens belonging to the case's body whose chain_status is either
    SENT_TO_LAB or CONSUMED (specimens still COLLECTED or already DISCARDED are excluded),
    and adds 5,000 cents for each."

    Design: Difficulty/dual_variant_calc/autopsy_estimate_vs_final_diverge_on_exam
    """
    set_clock("2026-05-10T00:00:00Z")
    inv = create_investigator("Inv A")
    path = create_pathologist("Path A", is_medical_examiner=False)
    case, body = create_investigating_case(inv, case_type="NATURAL")

    exam = schedule_autopsy(path, case, "2026-05-10T00:00:00Z", 120)
    assert exam["estimated_fee_cents"] == 230000

    spec1 = collect_specimen(path, body, "BLOOD")
    spec2 = collect_specimen(path, body, "URINE")
    send_specimen_to_lab(path, spec1)
    send_specimen_to_lab(path, spec2)

    completed = complete_autopsy(path, exam, "cardiac", "MI")
    assert completed["final_fee_cents"] == 240000
    assert completed["final_fee_cents"] != completed["estimated_fee_cents"]


def test_autopsy_final_nonlinear_max_ceil_homicide_multiplier(api):
    """PRD §3.4: "Elapsed time is the current logical-clock instant minus scheduled_for,
    taken in whole minutes by flooring the second-level difference. The billable minutes are
    the greater of that elapsed figure and the originally requested duration_minutes, so an
    exam never bills fewer minutes than were scheduled." PRD §3.4: "Finally, and only for a
    HOMICIDE case, the running subtotal of base plus duration surcharge plus specimen add-on
    is multiplied by 1.5 and rounded half-up to whole cents — the multiplier is applied
    strictly after the specimen add-on has been folded in."

    Design: Difficulty/combinatorial_formula/autopsy_final_nonlinear_max_ceil_conditional
    """
    set_clock("2026-05-10T00:00:00Z")
    inv = create_investigator("Inv C")
    path = create_pathologist("Path C", is_medical_examiner=False)
    case, body = create_investigating_case(inv, case_type="HOMICIDE")

    exam = schedule_autopsy(path, case, "2026-05-10T00:00:00Z", 90)
    set_clock("2026-05-10T02:30:00Z")

    completed = complete_autopsy(path, exam, "gsw", "gunshot")
    assert completed["final_fee_cents"] == 375000


def test_autopsy_estimate_homicide_multiplier_applied(api):
    """PRD §3.4: "If, and only if, the case's case_type is HOMICIDE, the sum of base plus
    duration surcharge is then multiplied by 1.5 and rounded half-up to whole cents. The
    result is the estimated_fee_cents. The estimate carries no overtime and no per-specimen
    charge."

    Design: Corner/calculations/autopsy_estimate_homicide_multiplier
    """
    inv = create_investigator("Inv CC3")
    path = create_pathologist("Path CC3", is_medical_examiner=False)
    case, body = create_investigating_case(inv, case_type="HOMICIDE")

    path_headers = make_pathologist_headers(path["id"])
    from test_helpers import create_autopsy_exam_payload
    res = api.create_autopsy_exam(
        case["id"],
        create_autopsy_exam_payload(path["id"], "2026-05-05T00:00:00Z", 90),
        path_headers,
    )
    exam = validate_success(res, 201)
    assert exam["estimated_fee_cents"] == 315000


def test_indigent_payable_estate_offset_variant(api):
    """PRD §3.8: "First, the decedent's estate offsets the cost: the estate value is the sum
    of `valuation_cents` across the case's property items still in `HELD`. Second, the cost
    owed after the estate is applied is the `itemized_cost_cents` minus that estate value,
    floored at zero so it never goes negative. Third, the county pays the smaller of that
    post-estate cost and the `statutory_allowance_cents` ceiling."

    Design: Difficulty/dual_variant_calc/indigent_payable_estate_offset_variant
    """
    inv = create_investigator("Inv B")
    me = create_pathologist("ME B", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL", decedent_name="Unknown")
    add_property_item(inv, case, "watch", 150000)
    disp = declare_indigent(inv, case, statutory_allowance_cents=400000, itemized_cost_cents=500000)

    me_headers = make_medical_examiner_headers(me["id"])
    approved = validate_success(api.approve_indigent_disposition(disp["id"], me_headers), 200)
    assert approved["county_payable_cents"] == 350000
    assert approved["disposition_status"] == "APPROVED"


def test_indigent_payable_pinned_evaluation_order(api):
    """PRD §3.8: "Because the estate is applied before the cap, a case with substantial held
    property can drive the county's share below the itemized cost even when the itemized cost
    was already under the allowance."

    Design: Difficulty/combinatorial_formula/indigent_payable_pinned_evaluation_order
    """
    inv = create_investigator("Inv D")
    me = create_pathologist("ME D", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL", decedent_name="Unknown2")
    add_property_item(inv, case, "ring", 350000)
    disp = declare_indigent(inv, case, statutory_allowance_cents=400000, itemized_cost_cents=300000)

    me_headers = make_medical_examiner_headers(me["id"])
    approved = validate_success(api.approve_indigent_disposition(disp["id"], me_headers), 200)
    assert approved["county_payable_cents"] == 0


def test_indigent_payable_no_estate_hits_cap(api):
    """PRD §3.8: "Third, the county pays the smaller of that post-estate cost and the
    statutory_allowance_cents ceiling."

    Design: Corner/calculations/indigent_payable_no_estate_hits_cap
    """
    inv = create_investigator("Inv CC4")
    me = create_pathologist("ME CC4", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL", decedent_name="Unknown CC4")
    disp = declare_indigent(inv, case, statutory_allowance_cents=400000, itemized_cost_cents=500000)

    me_headers = make_medical_examiner_headers(me["id"])
    approved = validate_success(api.approve_indigent_disposition(disp["id"], me_headers), 200)
    assert approved["county_payable_cents"] == 400000
