"""In-memory data store. Everything vanishes with the process."""
from datetime import datetime

from util import UTC, fmt_dt, real_now, new_id

CLOCK_EPOCH_RAW = "2026-08-01T00:00:00Z"


class Store(object):
    def __init__(self):
        self.programs = {}
        self.courses = {}
        self.outcomes = {}
        self.recommendations = {}
        self.rules = {}
        self.students = {}
        self.assessors = {}
        self.claims = {}
        self.portfolios = {}
        self.artifacts = {}
        self.assignments = {}
        self.rubric_scores = {}
        self.appeals = {}
        self.invoices = {}
        self.seq = 0
        self.clock = datetime(2026, 8, 1, tzinfo=UTC)
        self.clock_raw = CLOCK_EPOCH_RAW

    def next_seq(self):
        self.seq += 1
        return self.seq



db = Store()


def new_row(kind, extra_lean=False):
    """Create a row with the system field set required by the entity family."""
    row = {
        "_kind": kind,
        "_seq": db.next_seq(),
        "id": new_id(),
        "created_at": real_now(),
    }
    if not extra_lean:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def order_rows(rows, keys):
    """Stable multi-key sort; each key is (callable, reverse)."""
    result = sorted(rows, key=lambda r: r["_seq"])
    for func, reverse in reversed(keys):
        result = sorted(result, key=func, reverse=reverse)
    return result


# ---------------------------------------------------------------- lookups
def outcomes_of_course(course_id):
    return [o for o in db.outcomes.values() if o["course_id"] == course_id]


def portfolio_of_claim(claim_id):
    for p in db.portfolios.values():
        if p["claim_id"] == claim_id:
            return p
    return None


def invoice_of_claim(claim_id):
    for i in db.invoices.values():
        if i["claim_id"] == claim_id:
            return i
    return None


def artifacts_of_portfolio(portfolio_id):
    return [a for a in db.artifacts.values() if a["portfolio_id"] == portfolio_id]


def assignments_of_claim(claim_id):
    return [a for a in db.assignments.values() if a["claim_id"] == claim_id]


def scores_of_assignment(assignment_id):
    return [s for s in db.rubric_scores.values() if s["assignment_id"] == assignment_id]


def appeals_of_claim(claim_id):
    return [a for a in db.appeals.values() if a["claim_id"] == claim_id]


def next_claim_number(student_id):
    """One greater than the highest claim_number this student has used."""
    highest = 0
    for claim in db.claims.values():
        if claim["student_id"] == student_id and claim["claim_number"] > highest:
            highest = claim["claim_number"]
    return highest + 1


def claims_of_student(student_id):
    return [c for c in db.claims.values() if c["student_id"] == student_id]


def rules_of_recommendation(recommendation_id):
    return [r for r in db.rules.values() if r["recommendation_id"] == recommendation_id]


def claims_of_rule(rule_id):
    return [c for c in db.claims.values() if c.get("articulation_rule_id") == rule_id]
