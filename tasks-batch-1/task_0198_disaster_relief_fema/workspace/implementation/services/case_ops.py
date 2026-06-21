"""IhpCase lifecycle operations: provisional/final award, DOB recompute, recoupment.

PRD §3.3-§3.10. All amounts integer cents.
"""
from db import STORE, parse_iso
from services import calc
from services.models import base_entity, touch


def create_line_items(case):
    """Lay down one AwardLineItem per category in PENDING (PRD §3.3)."""
    for category in calc.CATEGORY_ORDER:
        li = base_entity()
        li.update({
            "ihp_case_id": case["id"],
            "category": category,
            "gross_amount_cents": 0,
            "approved_amount_cents": 0,
            "li_status": "PENDING",
        })
        STORE.award_line_items[li["id"]] = li


def compute_provisional(case, applicant, assessment):
    """PROVISIONAL gross: self-reported amounts, verified habitability (PRD §3.3)."""
    habitable = assessment.get("habitability") == "HABITABLE"
    comp = calc.compute_components(
        repair=applicant["reported_repair_cost_cents"],
        personal=applicant["reported_personal_property_cents"],
        rental_mo=applicant["reported_rental_months"],
        fmr=case["monthly_fmr_cents"],
        habitable=habitable,
    )
    gross = sum(comp.values())
    case["gross_eligible_cents"] = gross
    # set per-line gross for visibility (still PENDING)
    by_cat = {li["category"]: li for li in calc.case_line_items(case["id"])}
    for c, li in by_cat.items():
        li["gross_amount_cents"] = comp.get(c, 0)
    return comp


def _final_components(case, applicant, assessment, repair_override=None):
    repair = assessment["verified_repair_cost_cents"]
    if repair_override is not None:
        repair = repair_override
    habitable = assessment.get("habitability") == "HABITABLE"
    return calc.compute_components(
        repair=repair,
        personal=assessment["verified_personal_property_cents"],
        rental_mo=assessment["verified_rental_months"],
        fmr=case["monthly_fmr_cents"],
        habitable=habitable,
    )


def compute_final_award(case, applicant, assessment, declaration,
                        at_award=False, approved_at=None, repair_override=None):
    """Recompute the full final award chain and run the cap-and-offset waterfall.

    Returns dict with gross/capped/dob_offset/net/total_approved.
    Sets the derived fields on the case and approved_amount_cents on line items.
    """
    comp = _final_components(case, applicant, assessment, repair_override=repair_override)
    gross = sum(comp.values())
    max_grant = declaration["ihp_max_grant_cents"]
    capped = min(gross, max_grant)

    if at_award:
        offset = calc.dob_offset(applicant["id"], at_award=True, approved_at=approved_at)
    else:
        offset = calc.dob_offset(applicant["id"], at_award=False)

    net = max(0, capped - offset)

    case["gross_eligible_cents"] = gross
    case["capped_eligible_cents"] = capped
    case["dob_offset_cents"] = offset
    case["net_eligible_cents"] = net

    total_approved = calc.apply_cap_and_offset_waterfall(case, comp, max_grant, offset)
    return {
        "gross": gross, "capped": capped, "offset": offset,
        "net": net, "total_approved": total_approved, "components": comp,
    }


def recompute_obligation(case):
    case["remaining_obligation_cents"] = case["total_approved_cents"] - case["disbursed_total_cents"]


def recompute_dob_for_case(case, applicant, assessment, declaration):
    """At-recoupment recompute of dob_offset/net for an AWARD_APPROVED/DISBURSING case.

    Does NOT touch line items / total_approved (those reflect the approval-time award);
    only dob_offset_cents and net_eligible_cents move (PRD §3.5)."""
    offset = calc.dob_offset(applicant["id"], at_award=False)
    case["dob_offset_cents"] = offset
    case["net_eligible_cents"] = max(0, case["capped_eligible_cents"] - offset)


def maybe_establish_recoupment(case, origin):
    """Establish a recoupment if disbursed_total exceeds net_eligible (PRD §3.9).

    Returns the recoupment dict or None."""
    debt = max(0, case["disbursed_total_cents"] - case["net_eligible_cents"])
    if debt <= 0:
        return None
    r = base_entity()
    r.update({
        "ihp_case_id": case["id"],
        "origin": origin,
        "debt_amount_cents": debt,
        "recovered_cents": 0,
        "status": "ESTABLISHED",
    })
    STORE.recoupments[r["id"]] = r
    return r


def case_assessment(case):
    return STORE.assessments.get(case["assessment_id"])


def case_declaration(case):
    applicant = STORE.applicants.get(case["applicant_id"])
    if applicant is None:
        return None
    return STORE.declarations.get(applicant["declaration_id"])
