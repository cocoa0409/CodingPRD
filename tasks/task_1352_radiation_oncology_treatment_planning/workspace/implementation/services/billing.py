"""Billing service: charge-line append/backfill, auto-reopen, totals (PRD 3.9)."""
from db import store, new_entity, touch
from services import calc
from timeutil import new_id


def claims_of_course(course_id):
    return [c for c in store.claims.values() if c["course_id"] == course_id]


def open_claim(course_id):
    """The course's single open claim (DRAFT or FINALIZED), if any."""
    for c in claims_of_course(course_id):
        if c["status"] in ("DRAFT", "FINALIZED"):
            return c
    return None


def draft_claim(course_id):
    for c in claims_of_course(course_id):
        if c["status"] == "DRAFT":
            return c
    return None


def claim_lines(claim_id):
    return [l for l in store.lines.values() if l["claim_id"] == claim_id]


def recompute_gross(claim):
    claim["gross_total_cents"] = sum(l["amount_cents"] for l in claim_lines(claim["id"]))


def auto_reopen_finalized(course_id):
    """FINALIZED -> DRAFT when a charge-affecting clinical event lands
    (fraction delivery, no-show marking, adaptation trigger, discontinuation).
    Monetary fields are retained verbatim; recomputed only on next finalize."""
    for c in claims_of_course(course_id):
        if c["status"] == "FINALIZED":
            c["status"] = "DRAFT"
            touch(c)


def append_line(claim, code, description, unit_charge_cents, event_ref_id):
    """Append a system-generated line; (claim_id, code, event_ref_id) is unique
    so backfill and live appends never double-charge. Recomputes gross and
    bumps the claim version (the claim itself was mutated)."""
    for l in claim_lines(claim["id"]):
        if l["code"] == code and l["event_ref_id"] == event_ref_id:
            return l
    line = new_entity(common=False)
    line.update({
        "id": new_id(),
        "claim_id": claim["id"],
        "code": code,
        "description": description,
        "quantity": 1,
        "unit_charge_cents": unit_charge_cents,
        "amount_cents": unit_charge_cents,
        "event_ref_id": event_ref_id,
    })
    store.lines[line["id"]] = line
    recompute_gross(claim)
    touch(claim)
    return line


def bill_draft(course, code, description, unit_cents, event_ref_id):
    """Append to the course's DRAFT claim when one exists (no auto-reopen)."""
    claim = draft_claim(course["id"])
    if claim is not None:
        append_line(claim, code, description, unit_cents, event_ref_id)


def backfill(claim, course):
    """On claim creation, charge for billable events that already occurred:
    completed simulations, passed physics checks, approved plans, delivered
    fractions (+IGRT/+first-fraction setup), and no-shows."""
    cid = course["id"]

    events = []
    for a in store.simulations.values():
        if a["course_id"] == cid and a["status"] == "COMPLETED":
            events.append((a["_seq"], "SIMULATION", a["id"],
                           "Simulation appointment", calc.SIMULATION_FEE_CENTS))
    course_plan_ids = {p["id"] for p in store.plans.values() if p["course_id"] == cid}
    for chk in store.checks.values():
        if chk["plan_id"] in course_plan_ids and chk["outcome"] == "PASS":
            events.append((chk["_seq"], "PHYSICS_CHECK", chk["id"],
                           "Physics plan check", calc.PHYSICS_CHECK_FEE_CENTS))
    for p in store.plans.values():
        if p["course_id"] == cid and p.get("secondary_checker_id"):
            contour = store.contours.get(p["contour_set_id"])
            n_targets = len(contour["target_volumes"]) if contour else 1
            amount = calc.planning_charge_cents(course["technique"], n_targets,
                                                p["supersedes_plan_id"] is not None)
            events.append((p["_seq"], "PLANNING", p["id"],
                           "Treatment planning", amount))
    for s in store.sessions.values():
        if s["course_id"] != cid:
            continue
        if s["status"] == "DELIVERED":
            rate = calc.FRACTION_DELIVERY_RATE_CENTS[course["technique"]]
            events.append((s["_seq"], "FRACTION_DELIVERY", s["id"],
                           f"Fraction delivery #{s['fraction_number']}", rate))
            if s["igrt_planned"]:
                events.append((s["_seq"], "IGRT", s["id"],
                               "Image guidance", calc.IGRT_FEE_CENTS))
            if s["is_first_fraction"]:
                events.append((s["_seq"], "FIRST_FRACTION_SETUP", s["id"],
                               "First fraction setup", calc.FIRST_FRACTION_SETUP_FEE_CENTS))
        elif s["status"] == "NO_SHOW":
            events.append((s["_seq"], "NO_SHOW_FEE", s["id"],
                           "No-show fee", calc.NO_SHOW_FEE_CENTS))

    events.sort(key=lambda e: e[0])
    for _seq, code, ref, desc, amount in events:
        append_line(claim, code, desc, amount, ref)
