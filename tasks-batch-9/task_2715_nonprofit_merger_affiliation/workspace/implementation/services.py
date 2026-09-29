"""Cross-entity services: lookups, derived recomputation and the cascades.

Everything here traces to a PRD sentence; the cascade hop comments name the
paragraph that mandates the hop.
"""

from decimal import Decimal

import calc
from clock import CLOCK, parse_date, parse_ts
from db import (APPROVALS, ASSESSMENTS, DILIGENCE, FILINGS, FUNDS, LETTERS,
                ORGANIZATIONS, PROGRAMS, RESTRUCTURINGS, TASKS, touch)
from errors import fail


# ---------------------------------------------------------------- existence ----

def _find(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id)
    return row


def find_org(org_id):
    return _find(ORGANIZATIONS, org_id, "ERR_ORGANIZATION_NOT_FOUND")


def find_deal(deal_id):
    return _find(RESTRUCTURINGS, deal_id, "ERR_RESTRUCTURING_NOT_FOUND")


def find_program(program_id):
    return _find(PROGRAMS, program_id, "ERR_PROGRAM_NOT_FOUND")


def find_letter(letter_id):
    return _find(LETTERS, letter_id, "ERR_LETTER_OF_INTENT_NOT_FOUND")


def find_finding(finding_id):
    return _find(DILIGENCE, finding_id, "ERR_DILIGENCE_REQUEST_NOT_FOUND")


def find_fund(fund_id):
    return _find(FUNDS, fund_id, "ERR_RESTRICTED_FUND_NOT_FOUND")


def find_approval(approval_id):
    return _find(APPROVALS, approval_id, "ERR_BOARD_APPROVAL_NOT_FOUND")


def find_filing(filing_id):
    return _find(FILINGS, filing_id, "ERR_AG_FILING_NOT_FOUND")


def find_task(task_id):
    return _find(TASKS, task_id, "ERR_INTEGRATION_TASK_NOT_FOUND")


# ------------------------------------------------------------ deal ownership ---

def parties(deal):
    return (deal["initiator_org_id"], deal["target_org_id"])


def require_party(actor, deal):
    """Ladder rule 13: two-party membership for an entity-backed role."""
    if actor.entity_backed and actor.user_id not in parties(deal):
        fail("ERR_NOT_DEAL_PARTY", "The acting organization is not a party to this deal.")


def require_specific_party(actor, org_id):
    """Ladder rule 13 where the workflow names one specific party."""
    if actor.entity_backed and actor.user_id != org_id:
        fail("ERR_NOT_DEAL_PARTY", "This operation belongs to the other party.")


def deals_involving(org_ids):
    wanted = set(o for o in org_ids if o)
    out = []
    for deal in RESTRUCTURINGS.values():
        if deal["initiator_org_id"] in wanted or deal["target_org_id"] in wanted:
            out.append(deal)
    return out


# ------------------------------------------------------- restricted corpus -----

def corpus_for(org_id):
    """PRD 3.1: three disjoint contributions, exact integer cents."""
    total = 0
    for fund in FUNDS.values():
        if fund["org_id"] == org_id:
            if fund["transfer_status"] != "TRANSFERRED":
                total += fund["principal_cents"] + fund["accumulated_appreciation_cents"]
            else:
                total += fund["retained_amount_cents"]
        if (fund["transfer_status"] == "TRANSFERRED"
                and fund["transferred_to_org_id"] == org_id):
            total += fund["transferred_amount_cents"]
    return total


def refresh_corpus(org, force=False):
    value = corpus_for(org["id"])
    changed = value != org["restricted_corpus_cents"]
    org["restricted_corpus_cents"] = value
    if changed or force:
        touch(org)
    return changed


def refresh_corpus_for_ids(org_ids, force=False):
    for org_id in set(o for o in org_ids if o):
        org = ORGANIZATIONS.get(org_id)
        if org is not None:
            refresh_corpus(org, force=force)


# ------------------------------------------------------------- deal posture ----

def party_funds(deal):
    init, tgt = parties(deal)
    out = []
    for fund in FUNDS.values():
        if fund["org_id"] in (init, tgt) or fund["transferred_to_org_id"] in (init, tgt):
            out.append(fund)
    return out


def recompute_deal_restricted(deal):
    """PRD 3.6: derived count and posture; first matching branch wins."""
    previous = deal["restricted_asset_posture"]
    funds = party_funds(deal)
    unresolved = [f for f in funds
                  if f["transfer_status"] not in ("TRANSFERRED", "RETAINED")]
    if not funds:
        posture = "NOT_ASSESSED"
    elif any(f["transfer_status"] == "CONSENT_DENIED" for f in funds):
        posture = "BLOCKED"
    elif len(unresolved) > 0:
        posture = "RESTRICTED_PENDING"
    else:
        posture = "CLEARED"
    deal["unresolved_restricted_fund_count"] = len(unresolved)
    deal["restricted_asset_posture"] = posture
    return previous, posture


def recompute_postures_for_orgs(org_ids):
    for deal in deals_involving(org_ids):
        recompute_deal_restricted(deal)


def release_held_continuity_tasks(deal):
    """Transfer cascade hop 4 (PRD 3.6)."""
    for task in TASKS.values():
        if (task["restructuring_id"] == deal["id"]
                and task["workstream"] == "PROGRAM_CONTINUITY"
                and task["status"] == "HELD"):
            task["status"] = "PLANNED"
            task["held_reason"] = None
            touch(task)


def hold_planned_continuity_tasks(deal):
    """Unwind reversal of hop 4 (PRD 3.6)."""
    for task in TASKS.values():
        if (task["restructuring_id"] == deal["id"]
                and task["workstream"] == "PROGRAM_CONTINUITY"
                and task["status"] == "PLANNED"):
            task["status"] = "HELD"
            task["held_reason"] = "RESTRICTED_ASSETS_UNRESOLVED"
            touch(task)


# ----------------------------------------------------------- child selectors ---

def deal_letters(deal_id):
    return [l for l in LETTERS.values() if l["restructuring_id"] == deal_id]


def deal_findings(deal_id):
    return [d for d in DILIGENCE.values() if d["restructuring_id"] == deal_id]


def deal_approvals(deal_id):
    return [a for a in APPROVALS.values() if a["restructuring_id"] == deal_id]


def deal_filings(deal_id):
    return [f for f in FILINGS.values() if f["restructuring_id"] == deal_id]


def deal_tasks(deal_id):
    return [t for t in TASKS.values() if t["restructuring_id"] == deal_id]


def deal_assessments(deal_id):
    return [a for a in ASSESSMENTS.values() if a["restructuring_id"] == deal_id]


def latest_assessment(deal_id, variant):
    rows = [a for a in deal_assessments(deal_id) if a["variant"] == variant]
    if not rows:
        return None
    return max(rows, key=lambda a: (a["sequence_no"], a["_seq"]))


def open_exposure_cents(deal_id):
    return sum(d["exposure_cents"] for d in deal_findings(deal_id)
               if d["status"] in ("OPEN", "RESPONDED", "ESCALATED"))


def governing_letter(deal_id):
    """PRD 3.5: EXECUTED or SUPERSEDED, highest round_no, later created_at wins."""
    rows = [l for l in deal_letters(deal_id)
            if l["status"] in ("EXECUTED", "SUPERSEDED")]
    if not rows:
        return None
    return max(rows, key=lambda l: (l["round_no"], l["created_at"], l["_seq"]))


def executed_letter_highest_round(deal_id):
    rows = [l for l in deal_letters(deal_id) if l["status"] == "EXECUTED"]
    if not rows:
        return None
    return max(rows, key=lambda l: (l["round_no"], l["created_at"], l["_seq"]))


# ----------------------------------------------------------- seat accounting ---

def return_seats(deal, approval):
    """Return an approval's allocated seats to the pool and clear the party's
    governance_seats (PRD 3.5 rescission / supersession)."""
    seats = approval["allocated_seats"]
    if seats:
        deal["reserved_seat_pool"] += seats
        approval["allocated_seats"] = 0
    org_id = party_org_for(deal, approval["approving_party"])
    org = ORGANIZATIONS.get(org_id)
    if org is not None and org["governance_seats"] != 0:
        org["governance_seats"] = 0
        touch(org)


def party_org_for(deal, approving_party):
    return deal["initiator_org_id"] if approving_party == "INITIATOR" else deal["target_org_id"]


def certified_allocated_total(deal_id):
    return sum(a["allocated_seats"] for a in deal_approvals(deal_id)
               if a["status"] == "CERTIFIED")


# ------------------------------------------------------- diligence closure -----

def reevaluate_diligence_closure(deal):
    """PRD 3.4: an aggregate condition, not an explicit action."""
    if deal["status"] != "DILIGENCE":
        return False
    findings = deal_findings(deal["id"])
    if not findings:
        return False
    if all(f["status"] in ("CLEARED", "WAIVED") for f in findings):
        deal["status"] = "DILIGENCE_CLOSED"
        touch(deal)
        return True
    return False


# ------------------------------------------------------------- fund unwind -----

def unwind_fund(fund, deal):
    """PRD 3.6 compensating action; also used by the abandonment fan-out."""
    basis = fund["transfer_basis"]
    fund["transfer_status"] = "CONSENT_GRANTED" if basis == "DONOR_CONSENT" else "MODIFIED"
    recipient_id = fund["transferred_to_org_id"]
    holder_id = fund["org_id"]
    fund["transferred_to_org_id"] = None
    fund["transfer_restructuring_id"] = None
    fund["transfer_basis"] = None
    fund["transferred_amount_cents"] = 0
    fund["retained_amount_cents"] = 0
    fund["unwind_count"] += 1
    touch(fund)
    # Both parties' corpus figures land back on their exact pre-transfer values.
    refresh_corpus_for_ids([holder_id, recipient_id], force=True)
    if deal is not None:
        recompute_deal_restricted(deal)
        hold_planned_continuity_tasks(deal)
    recompute_postures_for_orgs([holder_id, recipient_id])


# ---------------------------------------------------------------- ag review ----

def has_ag_clearance(deal_id):
    return any(f["status"] in ("APPROVED", "DEEMED_APPROVED")
               for f in deal_filings(deal_id))


def has_ag_objection(deal_id):
    return any(f["status"] == "OBJECTED" for f in deal_filings(deal_id))


# -------------------------------------------------------- assessment builder ---

def build_assessment_fields(deal, variant):
    """PRD 3.2: the whole scored snapshot."""
    init = ORGANIZATIONS[deal["initiator_org_id"]]
    tgt = ORGANIZATIONS[deal["target_org_id"]]

    # Step 1 and 2: per-organization rounding happens BEFORE the sum.
    combined_monthly = init["monthly_expense_cents"] + tgt["monthly_expense_cents"]

    exposure = 0 if variant == "SCREENING" else open_exposure_cents(deal["id"])
    raw_available = (init["unrestricted_net_assets_cents"]
                     + tgt["unrestricted_net_assets_cents"])
    available = max(0, raw_available - exposure)
    reserve = calc.reserve_months_decimal(available, combined_monthly)

    # Mission component.
    if init["mission_code"] == tgt["mission_code"]:
        base_mission = calc.MISSION_IDENTICAL_POINTS
    elif calc.mission_family(init["mission_code"]) == calc.mission_family(tgt["mission_code"]):
        base_mission = calc.MISSION_FAMILY_POINTS
    else:
        base_mission = calc.MISSION_UNRELATED_POINTS
    deduct = False
    if variant == "DILIGENCE_ADJUSTED":
        deduct = any(f["workstream"] == "RESTRICTED_FUNDS"
                     and f["severity"] == "CRITICAL"
                     and f["status"] == "ESCALATED"
                     for f in deal_findings(deal["id"]))
    if deduct:
        mission_points = base_mission - calc.RESTRICTED_FUNDS_ESCALATION_DEDUCTION
        if mission_points < Decimal("0.00"):
            mission_points = Decimal("0.00")
    else:
        mission_points = base_mission

    # Overlap component.
    if variant == "SCREENING":
        admitted = [p for p in PROGRAMS.values()
                    if p["org_id"] in (init["id"], tgt["id"])]
    else:
        admitted = [p for p in PROGRAMS.values()
                    if p["org_id"] in (init["id"], tgt["id"])
                    and p["continuity_status"] in ("ACTIVE", "PLANNED_TRANSFER")]
    init_programs = [p for p in admitted if p["org_id"] == init["id"]]
    tgt_programs = [p for p in admitted if p["org_id"] == tgt["id"]]
    pair_count = 0
    for p in init_programs:
        for q in tgt_programs:
            if (p["service_category"] == q["service_category"]
                    and p["county_code"] == q["county_code"]):
                pair_count += 1
    denom = min(len(init_programs), len(tgt_programs))
    index = calc.overlap_index(pair_count, denom)
    overlap_pts = calc.overlap_points(index)

    sustainability = calc.sustainability_points(reserve)
    composite = calc.rhu(mission_points + overlap_pts + sustainability, 2)

    return {
        "included_program_count": len(admitted),
        "overlap_pair_count": pair_count,
        "program_overlap_index": float(index),
        "mission_alignment_points": float(calc.rhu(mission_points, 2)),
        "program_overlap_points": float(overlap_pts),
        "combined_monthly_expense_cents": combined_monthly,
        "open_diligence_exposure_cents": exposure,
        "available_unrestricted_cents": available,
        "reserve_months": float(reserve),
        "sustainability_points": float(sustainability),
        "composite_score": float(composite),
        "composite_rating": calc.composite_rating(composite),
    }


# ----------------------------------------------------------------- the sweep ---

def run_sweep():
    """PRD 3.9: three time-driven transitions in one pass, idempotent."""
    now = CLOCK.now()
    deemed = []
    lapsed = []
    expired = []

    for filing in sorted(FILINGS.values(), key=lambda f: f["_seq"]):
        if filing["status"] != "SUBMITTED":
            continue
        deadline = parse_ts(filing["review_deadline_at"])
        if deadline is not None and now >= deadline:
            filing["status"] = "DEEMED_APPROVED"
            filing["decision_recorded_at"] = CLOCK.now_iso()
            touch(filing)
            deemed.append(filing["id"])
            deal = RESTRUCTURINGS.get(filing["restructuring_id"])
            if deal is not None and deal["status"] == "REGULATORY_REVIEW":
                deal["status"] = "INTEGRATION"
                touch(deal)

    for letter in sorted(LETTERS.values(), key=lambda l: l["_seq"]):
        if letter["status"] in ("ISSUED", "COUNTERED"):
            expires = parse_ts(letter["expires_at"])
            if expires is not None and now >= expires:
                letter["status"] = "LAPSED"
                letter["exclusivity_status"] = "RELEASED"
                touch(letter)
                lapsed.append(letter["id"])

    for letter in sorted(LETTERS.values(), key=lambda l: l["_seq"]):
        if letter["exclusivity_status"] == "ACTIVE":
            end_date = parse_date(letter["exclusivity_end_date"])
            if end_date is not None and end_date < now.date():
                # Dimension B only: the negotiation status is left untouched.
                letter["exclusivity_status"] = "EXPIRED"
                touch(letter)
                expired.append(letter["id"])

    return {
        "swept_at": CLOCK.now_iso(),
        "deemed_approved_filing_ids": deemed,
        "lapsed_letter_of_intent_ids": lapsed,
        "expired_exclusivity_letter_of_intent_ids": expired,
    }
