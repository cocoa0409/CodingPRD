"""Reconciliation-line materialisation and the client-total variants."""

from decimal import Decimal

import calc
import derive
from store import db, new_row


def recompute_line(line, element, program):
    """FINAL head-count rule then the line-amount rule (PRD section 3.8)."""
    kind = line["line_kind"]
    if kind == "DELIVERY":
        billed = calc.billable_headcount_final(line["guaranteed_headcount"],
                                               line["actual_headcount"], kind)
        cost = billed * int(element["per_person_cost_cents"])
    else:
        billed = 0
        cost = int(element["cancellation_penalty_cents"])
    line["billed_headcount"] = billed
    line["supplier_cost_cents"] = cost
    line["markup_cents"] = calc.markup_for(cost, program["markup_pct"])
    line["client_charge_cents"] = cost + line["markup_cents"]
    line["variance_pct"] = calc.variance_pct(line["actual_headcount"],
                                             line["guaranteed_headcount"], kind)
    return line


def materialise_lines(program):
    """One line per DELIVERED or CANCELLED element, in element starts_at order."""
    elements = [e for e in derive.elements_of_program(program["id"])
                if e["status"] in ("DELIVERED", "CANCELLED")]
    elements.sort(key=lambda e: (e["starts_at"], e["created_at"], e["_seq"]))
    created = []
    for element in elements:
        kind = "DELIVERY" if element["status"] == "DELIVERED" else "CANCELLATION_PENALTY"
        if kind == "DELIVERY":
            actual = element.get("actual_headcount")
            actual = 0 if actual is None else int(actual)
        else:
            actual = 0
        line = new_row(
            program_id=program["id"],
            element_id=element["id"],
            supplier_id=element["supplier_id"],
            line_kind=kind,
            guaranteed_headcount=int(element["guaranteed_headcount"]),
            actual_headcount=actual,
            billed_headcount=0,
            supplier_cost_cents=0,
            markup_cents=0,
            client_charge_cents=0,
            variance_pct=Decimal("0"),
            variance_reason=None,
            status="DRAFT",
        )
        recompute_line(line, element, program)
        db.recon_lines[line["id"]] = line
        created.append(line)
    return created


def estimate_client_total(program):
    """ESTIMATE variant: walks elements in PLANNED or READY."""
    subtotal = 0
    markup_total = 0
    for element in derive.elements_of_program(program["id"]):
        if element["status"] not in ("PLANNED", "READY"):
            continue
        headcount = calc.billable_headcount_estimate(element)
        cost = headcount * int(element["per_person_cost_cents"])
        subtotal += cost
        markup_total += calc.markup_for(cost, program["markup_pct"])
    return calc.program_client_total(subtotal, markup_total)


def final_client_total(program):
    """FINAL variant: walks the programme's APPROVED reconciliation lines."""
    lines = derive.approved_lines(program["id"])
    subtotal = sum(int(l["supplier_cost_cents"]) for l in lines)
    markup_total = sum(int(l["markup_cents"]) for l in lines)
    return calc.program_client_total(subtotal, markup_total)
