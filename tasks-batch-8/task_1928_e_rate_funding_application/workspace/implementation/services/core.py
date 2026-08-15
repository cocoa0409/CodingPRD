"""Core shared services: record lifecycle, chain resolution, retained documents, budget."""
import itertools
from datetime import timedelta

from db import db
from util import new_id, now_ts, parse_date, add_years

# Global monotonic creation-order counter. created_at carries millisecond
# precision; this breaks same-millisecond ties deterministically while always
# agreeing with created_at ordering (records are created sequentially).
_seq = itertools.count(1)


def new_record(collection, fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = next(_seq)
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """PRD 2.5: updated_at refreshed and version incremented by exactly 1 on
    every mutation of the resource (including cascade side effects)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Chain resolution helpers
# ---------------------------------------------------------------------------

def request_of_line(line):
    return db["funding_requests"].get(line["funding_request_id"])


def applicant_id_of_line(line):
    req = request_of_line(line)
    return req["applicant_id"] if req else None


def cycle_of_line(line):
    req = request_of_line(line)
    return req["funding_cycle_id"] if req else None


def lines_of_request(request_id):
    return [l for l in db["funding_request_lines"].values()
            if l["funding_request_id"] == request_id]


def latest_snapshot(applicant_id, funding_cycle_id):
    """Effective snapshot = latest by created_at; sequential creation makes ties
    impossible (_seq agrees with created_at ordering)."""
    cands = [s for s in db["nslp_snapshots"].values()
             if s["applicant_id"] == applicant_id
             and s["funding_cycle_id"] == funding_cycle_id]
    if not cands:
        return None
    return max(cands, key=lambda s: s["_seq"])


# ---------------------------------------------------------------------------
# Category Two budget pool (calculation category_two_budget_cap)
# ---------------------------------------------------------------------------

C2_PER_STUDENT_CENTS = 16700
C2_PER_SQFT_CENTS = 450
C2_FLOOR_CENTS = 2500000


def c2_cap_cents(applicant):
    if applicant["entity_type"] == "SCHOOL":
        base = C2_PER_STUDENT_CENTS * applicant["student_count"]
    else:  # LIBRARY
        base = C2_PER_SQFT_CENTS * applicant["square_feet"]
    return max(base, C2_FLOOR_CENTS)


def c2_committed_cents(applicant_id):
    """Sum of committed_pre_discount_cents over the applicant's CATEGORY_TWO
    lines in COMMITTED status. PENDING/DENIED never consume; CANCELLED released."""
    total = 0
    for line in db["funding_request_lines"].values():
        if line["category"] != "CATEGORY_TWO" or line["status"] != "COMMITTED":
            continue
        if applicant_id_of_line(line) == applicant_id:
            total += line["committed_pre_discount_cents"]
    return total


def recompute_request_total(request):
    """committed_total_share_cents = sum of per-line committed_share_cents over
    COMMITTED lines (per-line rounding first, then summation — never reversed)."""
    request["committed_total_share_cents"] = sum(
        l["committed_share_cents"]
        for l in lines_of_request(request["id"])
        if l["status"] == "COMMITTED"
    )


# ---------------------------------------------------------------------------
# Automatic document retention (PRD 2.9)
# ---------------------------------------------------------------------------

def retain_document(subject_type, subject_id, funding_cycle_id, document_kind):
    cycle = db["funding_cycles"][funding_cycle_id]
    retained_until = add_years(parse_date(cycle["service_delivery_deadline"]), 10)
    return new_record("retained_documents", {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "funding_cycle_id": funding_cycle_id,
        "document_kind": document_kind,
        "retained_until_date": retained_until.isoformat(),
        "status": "RETAINED",
        "hold_start_date": None,
        "hold_end_date": None,
    })


def invoice_deadline_for_cycle(cycle):
    """cycle.service_delivery_deadline + 120 days (closed invoice interval end)."""
    return (parse_date(cycle["service_delivery_deadline"]) + timedelta(days=120)).isoformat()
