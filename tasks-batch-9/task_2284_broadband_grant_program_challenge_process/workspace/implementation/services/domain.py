"""Lookups, derived-field refreshers and the append-only ledger."""

from db import db, new_record, now_ts, sort_rows
from errors import ApiError
from records import assign, touch
from services import calculations as calc

# ----------------------------------------------------------------- existence

def require_program(program_id):
    row = db.programs.get(program_id) if isinstance(program_id, str) else None
    if row is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND")
    return row


def require_location(location_id):
    row = db.locations.get(location_id) if isinstance(location_id, str) else None
    if row is None:
        raise ApiError("ERR_LOCATION_NOT_FOUND")
    return row


def require_challenge(challenge_id):
    row = db.challenges.get(challenge_id) if isinstance(challenge_id, str) else None
    if row is None:
        raise ApiError("ERR_CHALLENGE_NOT_FOUND")
    return row


def require_subgrantee(subgrantee_id):
    row = db.subgrantees.get(subgrantee_id) if isinstance(subgrantee_id, str) else None
    if row is None:
        raise ApiError("ERR_SUBGRANTEE_NOT_FOUND")
    return row


def require_application(application_id):
    row = db.applications.get(application_id) if isinstance(application_id, str) else None
    if row is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND")
    return row


def require_award(award_id):
    row = db.awards.get(award_id) if isinstance(award_id, str) else None
    if row is None:
        raise ApiError("ERR_AWARD_NOT_FOUND")
    return row


def require_milestone(award, milestone_id):
    row = db.milestones.get(milestone_id) if isinstance(milestone_id, str) else None
    if row is None or row["award_id"] != award["id"]:
        raise ApiError("ERR_MILESTONE_NOT_FOUND")
    return row


def require_audit(award, audit_id):
    row = db.audits.get(audit_id) if isinstance(audit_id, str) else None
    if row is None or row["award_id"] != award["id"]:
        raise ApiError("ERR_AUDIT_NOT_FOUND")
    return row


def find_env_review(award):
    rows = [r for r in db.env_reviews.values() if r["award_id"] == award["id"]]
    rows = sort_rows(rows)
    return rows[-1] if rows else None


def require_env_review(award):
    row = find_env_review(award)
    if row is None:
        raise ApiError("ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND")
    return row


# ------------------------------------------------------------------ traversal

def program_of_application(application):
    return db.programs.get(application["program_id"])


def application_of_award(award):
    return db.applications.get(award["application_id"])


def program_of_award(award):
    application = application_of_award(award)
    return db.programs.get(application["program_id"]) if application else None


def subgrantee_of_award(award):
    application = application_of_award(award)
    return db.subgrantees.get(application["subgrantee_id"]) if application else None


def claims_of_application(application_id):
    return sort_rows([c for c in db.claims.values() if c["application_id"] == application_id])


def claims_of_location(location_id):
    return sort_rows([c for c in db.claims.values() if c["location_id"] == location_id])


def evidence_of_challenge(challenge_id):
    return sort_rows([e for e in db.evidence.values() if e["challenge_id"] == challenge_id])


def score_sheets_of_application(application_id):
    return sort_rows([s for s in db.score_sheets.values()
                      if s["application_id"] == application_id])


def milestones_of_award(award_id):
    return sort_rows([m for m in db.milestones.values() if m["award_id"] == award_id])


def audits_of_award(award_id):
    return sort_rows([a for a in db.audits.values() if a["award_id"] == award_id])


def ledger_of_award(award_id):
    return sort_rows([e for e in db.ledger.values() if e["award_id"] == award_id])


def locations_of_award(award_id):
    return sort_rows([l for l in db.locations.values() if l.get("awarded_award_id") == award_id])


def awards_of_application(application_id):
    return sort_rows([a for a in db.awards.values() if a["application_id"] == application_id])


def applications_of_program(program_id):
    return sort_rows([a for a in db.applications.values() if a["program_id"] == program_id])


# ------------------------------------------------------- derived-field refresh

CLAIM_WIDE = ("CLAIMED_ELIGIBLE", "CLAIMED_INELIGIBLE", "AWARD_BOUND", "EHCL_DEFERRED")
CLAIM_NARROW = ("CLAIMED_ELIGIBLE", "AWARD_BOUND")


def refresh_challenge_scores(challenge):
    items = evidence_of_challenge(challenge["id"])
    accepted = [i for i in items if i["evidence_state"] == "ACCEPTED"]
    challenge_side = [i for i in accepted if i["submitter_side"] == "CHALLENGE"]
    rebuttal_side = [i for i in accepted if i["submitter_side"] == "REBUTTAL"]
    changed = assign(challenge, "evidence_sufficiency_score",
                     calc.num(calc.sum_weighted(challenge_side)))
    changed = assign(challenge, "rebuttal_strength_score",
                     calc.num(calc.sum_weighted(rebuttal_side))) or changed
    changed = assign(challenge, "distinct_evidence_type_count",
                     len(set(i["evidence_type"] for i in challenge_side))) or changed
    return changed


def challenge_side_accepted(challenge):
    return [i for i in evidence_of_challenge(challenge["id"])
            if i["evidence_state"] == "ACCEPTED" and i["submitter_side"] == "CHALLENGE"]


def refresh_location_challenge_count(location):
    count = len([c for c in db.challenges.values() if c["location_id"] == location["id"]])
    return assign(location, "challenge_count", count)


def refresh_application(application, stamp_costs=None):
    """Re-derive the four claim aggregates and, when appropriate, both cost variants."""
    claims = claims_of_application(application["id"])
    wide = [c for c in claims if c["claim_state"] in CLAIM_WIDE]
    narrow = [c for c in claims if c["claim_state"] in CLAIM_NARROW]
    changed = assign(application, "claim_count", len(wide))
    changed = assign(application, "confirmed_location_count", len(narrow)) or changed
    changed = assign(application, "total_project_cost_cents",
                     sum(int(c["claimed_cost_cents"]) for c in wide)) or changed
    changed = assign(application, "eligible_project_cost_cents",
                     sum(int(c["claimed_cost_cents"]) for c in narrow)) or changed

    if stamp_costs is None:
        stamp_costs = application["application_state"] != "DRAFT"
    if stamp_costs:
        changed = assign(
            application, "preliminary_cost_per_location_cents",
            calc.preliminary_cost_per_location(application["total_project_cost_cents"],
                                               application["claim_count"])) or changed
        changed = assign(
            application, "final_cost_per_location_cents",
            calc.final_cost_per_location(application["eligible_project_cost_cents"],
                                         application["confirmed_location_count"])) or changed
    return changed


def refresh_award(award):
    entries = ledger_of_award(award["id"])
    disbursed = sum(int(e["amount_cents"]) for e in entries
                    if e["entry_type"] == "DISBURSEMENT")
    recovered = sum(int(e["amount_cents"]) for e in entries
                    if e["entry_type"] == "CLAWBACK_RECOVERY")
    locations = locations_of_award(award["id"])
    # `confirmed_location_count` is stamped once when the award is obligated
    # (PRD 3.7: "its `confirmed_location_count` counting the claims now bound to
    # it") and is never re-derived afterwards; only the three counters the PRD
    # explicitly re-derives are recomputed here.
    changed = assign(award, "disbursed_to_date_cents", disbursed - recovered)
    changed = assign(award, "certified_location_count",
                     len([l for l in locations if l["service_state"] == "CERTIFIED"])) or changed
    changed = assign(award, "failed_location_count",
                     len([l for l in locations if l["service_state"] == "AUDIT_FAILED"])) or changed
    return changed


def refresh_subgrantee(subgrantee):
    count = 0
    for application in db.applications.values():
        if application["subgrantee_id"] != subgrantee["id"]:
            continue
        for award in db.awards.values():
            if (award["application_id"] == application["id"]
                    and award["compliance_state"] == "NONCOMPLIANT"):
                count += 1
    return assign(subgrantee, "open_noncompliance_count", count)


def program_scoring_posture(program, stale_count):
    if program["program_state"] in ("DRAFT", "CHALLENGE_OPEN", "ALLOCATION_CLOSED"):
        return "FROZEN"
    if (program["program_state"] in ("CHALLENGE_CLOSED", "SCORING")
            and stale_count >= 1):
        return "RESTRICTED"
    return "OPEN"


def refresh_program(program):
    """Re-derive location count, stale sheets, posture and the three balances."""
    location_count = len([l for l in db.locations.values()
                          if l["program_id"] == program["id"]])
    stale = 0
    for sheet in db.score_sheets.values():
        application = db.applications.get(sheet["application_id"])
        if (application and application["program_id"] == program["id"]
                and sheet["score_state"] == "STALE"):
            stale += 1

    obligation_total = 0
    disbursed_total = 0
    deobligated_total = 0
    recovered_total = 0
    for entry in db.ledger.values():
        award = db.awards.get(entry["award_id"])
        if award is None:
            continue
        application = db.applications.get(award["application_id"])
        if application is None or application["program_id"] != program["id"]:
            continue
        amount = int(entry["amount_cents"])
        if entry["entry_type"] == "OBLIGATION":
            obligation_total += amount
        elif entry["entry_type"] == "DISBURSEMENT":
            disbursed_total += amount
        elif entry["entry_type"] == "DEOBLIGATION":
            deobligated_total += amount
        elif entry["entry_type"] == "CLAWBACK_RECOVERY":
            recovered_total += amount

    total = int(program["total_appropriation_cents"])
    uncommitted = total - obligation_total + deobligated_total + recovered_total
    obligated = obligation_total - deobligated_total - disbursed_total
    disbursed = disbursed_total - recovered_total

    changed = assign(program, "location_count_total", location_count)
    changed = assign(program, "stale_score_sheet_count", stale) or changed
    changed = assign(program, "scoring_posture",
                     program_scoring_posture(program, stale)) or changed
    changed = assign(program, "uncommitted_balance_cents", uncommitted) or changed
    changed = assign(program, "obligated_balance_cents", obligated) or changed
    changed = assign(program, "disbursed_balance_cents", disbursed) or changed
    if changed:
        touch(program)
    return changed


# --------------------------------------------------------------------- ledger

def append_ledger(award, entry_type, amount_cents, source_reference, memo):
    """Append one immutable ledger row and reconcile the program balances."""
    program = program_of_award(award)
    entry = new_record({
        "award_id": award["id"],
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "source_reference": source_reference,
        "program_uncommitted_after_cents": None,
        "memo": memo,
    }, versioned=False)
    db.ledger[entry["id"]] = entry
    refresh_program(program)
    entry["program_uncommitted_after_cents"] = int(program["uncommitted_balance_cents"])
    return entry


def stamp_now(record, field):
    record[field] = now_ts()
