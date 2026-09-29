"""Pinned arithmetic: the eleven declared calculations (PRD Sections 2.7, 3.x).

Every intermediate is an exact rational (fractions.Fraction) so that the
staged round-half-up steps are reproducible to the cent and to the stated
decimal place.
"""

import math
from datetime import date, timedelta
from fractions import Fraction

from db import add_days, ordered, parse_ts, store

MS_PER_DAY = 86400000

# ---- reviewer reliability -------------------------------------------------
CLOSED_STATES = ("DECLINED", "EXPIRED", "SUBMITTED", "WITHDRAWN")
OPEN_STATES = ("INVITED", "ACCEPTED")
W_DELIVERY = Fraction(45, 100)
W_ON_TIME = Fraction(35, 100)
W_RESPONSIVENESS = Fraction(20, 100)
LATE_DAY_PENALTY = Fraction(5, 2)
MAX_LATENESS_PENALTY = Fraction(20)
PROBATION_FLOOR = 40.0
PROBATION_MIN_CLOSED = 3
REINSTATE_CEILING = 60.0
ROLLING_WINDOW_DAYS = 180
NEUTRAL_SEED = 50.0
MIN_WEIGHT = Fraction(1, 4)

# ---- consensus ------------------------------------------------------------
REC_VALUE = {"ACCEPT": 4, "MINOR_REVISION": 3, "MAJOR_REVISION": 2, "REJECT": 1}
ACCEPT_THRESHOLD = 3.50
MINOR_THRESHOLD = 2.50
MAJOR_THRESHOLD = 1.75

# ---- fees -----------------------------------------------------------------
LICENSE_MULTIPLIER = {
    "CC_BY": Fraction(1),
    "CC_BY_NC": Fraction(90, 100),
    "CC_BY_NC_ND": Fraction(85, 100),
    "GREEN_SELF_ARCHIVE": Fraction(0),
}
WAIVER_PCT = {"HIGH": 0, "UPPER_MIDDLE": 25, "LOWER_MIDDLE": 50, "LOW": 100}
INSTITUTIONAL_PCT = 15
MIN_BILLABLE_CENTS = 2000
RELIEF_TIER_1_CENTS = 150000
RELIEF_TIER_2_CENTS = 250000

# ---- ethics ---------------------------------------------------------------
UNRESOLVED_CASE_STATES = (
    "OPEN",
    "INVESTIGATION",
    "AUTHOR_RESPONSE_REQUESTED",
    "COMMITTEE_REVIEW",
)


# ==========================================================================
# rounding
# ==========================================================================
def _frac(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def round_half_up_int(value):
    """Round an exact rational half up to a whole unit (cents)."""
    fr = _frac(value)
    q, r = divmod(fr.numerator, fr.denominator)
    if 2 * r >= fr.denominator:
        q += 1
    return q


def round_half_up(value, places):
    """Round an exact rational half up to `places` decimals, returned as float."""
    scale = 10 ** places
    scaled = round_half_up_int(_frac(value) * scale)
    return scaled / scale


# ==========================================================================
# small lookups
# ==========================================================================
def journal_of(manuscript):
    return store.journals[manuscript["journal_id"]]


def author_of(manuscript):
    return store.authors.get(manuscript["corresponding_author_id"])


def review_for_invitation(invitation_id):
    for review in store.reviews.values():
        if review["invitation_id"] == invitation_id:
            return review
    return None


def invitations_of_manuscript(manuscript_id):
    return [i for i in store.invitations.values() if i["manuscript_id"] == manuscript_id]


def invitations_of_reviewer(reviewer_id):
    return [i for i in store.invitations.values() if i["reviewer_id"] == reviewer_id]


def open_invitations_of_manuscript(manuscript_id):
    return [i for i in invitations_of_manuscript(manuscript_id) if i["state"] in OPEN_STATES]


def screenings_of_manuscript(manuscript_id):
    return [s for s in store.screenings.values() if s["manuscript_id"] == manuscript_id]


def decisions_of_manuscript(manuscript_id):
    return ordered([d for d in store.decisions.values() if d["manuscript_id"] == manuscript_id])


def ethics_cases_of_manuscript(manuscript_id):
    return [c for c in store.ethics_cases.values() if c["manuscript_id"] == manuscript_id]


def invoices_of_manuscript(manuscript_id):
    return [i for i in store.invoices.values() if i["manuscript_id"] == manuscript_id]


def production_job_of_manuscript(manuscript_id):
    for job in ordered(list(store.production_jobs.values())):
        if job["manuscript_id"] == manuscript_id:
            return job
    return None


def assignments_of_manuscript(manuscript_id):
    return [a for a in store.assignments.values() if a["manuscript_id"] == manuscript_id]


def active_assignment_of(manuscript_id):
    """Exactly one ACTIVE assignment or nothing at all."""
    found = [a for a in assignments_of_manuscript(manuscript_id) if a["state"] == "ACTIVE"]
    return found[0] if len(found) == 1 else None


def has_high_ethics_hold(manuscript_id):
    for case in ethics_cases_of_manuscript(manuscript_id):
        if case["severity"] == "HIGH" and case["state"] in UNRESOLVED_CASE_STATES:
            return True
    return False


def has_unresolved_case(manuscript_id, case_type=None):
    for case in ethics_cases_of_manuscript(manuscript_id):
        if case["state"] not in UNRESOLVED_CASE_STATES:
            continue
        if case_type is None or case["case_type"] == case_type:
            return True
    return False


def has_issued_invoice(manuscript_id):
    return any(i["status"] == "ISSUED" for i in invoices_of_manuscript(manuscript_id))


# ==========================================================================
# manuscript computed fields
# ==========================================================================
def screening_verdict(scan_type, similarity_pct, manipulated_figure_count):
    if scan_type == "PLAGIARISM":
        if similarity_pct >= 40.0:
            return "BLOCK"
        if similarity_pct >= 20.0:
            return "FLAG"
        return "PASS"
    if manipulated_figure_count >= 2:
        return "BLOCK"
    if manipulated_figure_count == 1:
        return "FLAG"
    return "PASS"


def integrity_status(manuscript):
    """Rollup over the current revision_round's screenings only."""
    current = [
        s
        for s in screenings_of_manuscript(manuscript["id"])
        if s["round"] == manuscript["revision_round"]
    ]
    if not current:
        return "PENDING"
    verdicts = {s["verdict"] for s in current}
    if "BLOCK" in verdicts:
        return "BLOCK"
    if "FLAG" in verdicts:
        return "FLAG"
    return "PASS"


def formatting_status(manuscript):
    journal = journal_of(manuscript)
    if manuscript["page_count"] > journal["max_page_count"]:
        return "NON_COMPLIANT"
    if manuscript["figure_count"] > journal["max_figure_count"]:
        return "NON_COMPLIANT"
    if journal["requires_data_availability_statement"]:
        das = manuscript.get("data_availability_statement")
        if not isinstance(das, str) or das.strip() == "":
            return "NON_COMPLIANT"
    return "COMPLIANT"


def submitted_review_count(manuscript):
    total = 0
    for review in store.reviews.values():
        invitation = store.invitations.get(review["invitation_id"])
        if invitation is None:
            continue
        if (
            invitation["manuscript_id"] == manuscript["id"]
            and invitation["round"] == manuscript["revision_round"]
        ):
            total += 1
    return total


def shortfall_value(manuscript):
    journal = journal_of(manuscript)
    if submitted_review_count(manuscript) >= journal["min_completed_reviews_for_decision"]:
        return False
    return len(open_invitations_of_manuscript(manuscript["id"])) == 0


# ==========================================================================
# reviewer_reliability_score
# ==========================================================================
def _closed_set(reviewer_id, variant):
    closed = [i for i in invitations_of_reviewer(reviewer_id) if i["state"] in CLOSED_STATES]
    if variant == "ROLLING":
        boundary = store.clock - timedelta(days=ROLLING_WINDOW_DAYS)
        closed = [i for i in closed if parse_ts(i["created_at"]) >= boundary]
    return closed


def reliability_score(reviewer_id, variant):
    """Returns (score, n_closed) for the requested variant."""
    window = _closed_set(reviewer_id, variant)
    n_closed = len(window)
    if n_closed == 0:
        return NEUTRAL_SEED, 0

    n_submitted = 0
    n_expired = 0
    n_on_time = 0
    late_days = 0
    for invitation in window:
        if invitation["state"] == "EXPIRED":
            n_expired += 1
        elif invitation["state"] == "SUBMITTED":
            n_submitted += 1
            review = review_for_invitation(invitation["id"])
            days_late = review["days_late"] if review else 0
            late_days += days_late
            if days_late == 0:
                n_on_time += 1

    delivery_rate = Fraction(n_submitted, n_closed)
    on_time_rate = Fraction(n_on_time, n_submitted) if n_submitted > 0 else Fraction(0)
    responsiveness_rate = 1 - Fraction(n_expired, n_closed)
    lateness_penalty = min(MAX_LATENESS_PENALTY, LATE_DAY_PENALTY * late_days)
    raw = (
        100
        * (
            W_DELIVERY * delivery_rate
            + W_ON_TIME * on_time_rate
            + W_RESPONSIVENESS * responsiveness_rate
        )
        - lateness_penalty
    )
    clamped = max(Fraction(0), min(Fraction(100), raw))
    return round_half_up(clamped, 2), n_closed


def reliability_weight(rolling_score):
    quotient = _frac(rolling_score) / 100
    rounded = _frac(round_half_up(quotient, 4))
    weight = max(MIN_WEIGHT, rounded)
    return round_half_up(weight, 4)


def days_late_for(submitted_at, due_at):
    delta_ms = (submitted_at - due_at).total_seconds() * 1000.0
    if delta_ms <= 0:
        return 0
    return max(0, int(math.ceil(delta_ms / MS_PER_DAY)))


# ==========================================================================
# decision_consensus_index
# ==========================================================================
def consensus_review_set(manuscript):
    rows = []
    for review in store.reviews.values():
        invitation = store.invitations.get(review["invitation_id"])
        if invitation is None:
            continue
        if (
            invitation["manuscript_id"] == manuscript["id"]
            and invitation["round"] == manuscript["revision_round"]
            and invitation["state"] == "SUBMITTED"
        ):
            rows.append(review)
    return ordered(rows)


def consensus_index(manuscript, mode):
    rows = consensus_review_set(manuscript)
    n = len(rows)
    if n == 0:
        return None, 0
    if mode == "UNWEIGHTED":
        total = sum(REC_VALUE[r["recommendation"]] for r in rows)
        return round_half_up(Fraction(total, n), 2), n
    numerator = Fraction(0)
    denominator = Fraction(0)
    for review in rows:
        weight = _frac(review["reliability_weight"])
        numerator += REC_VALUE[review["recommendation"]] * weight
        denominator += weight
    if denominator == 0:
        return round_half_up(Fraction(0), 2), n
    return round_half_up(numerator / denominator, 2), n


def auto_category_for(index):
    if index >= ACCEPT_THRESHOLD:
        return "ACCEPT"
    if index >= MINOR_THRESHOLD:
        return "MINOR_REVISION"
    if index >= MAJOR_THRESHOLD:
        return "MAJOR_REVISION"
    return "REJECT"


# ==========================================================================
# apc_net_amount + invoice_total_with_surcharge
# ==========================================================================
def price_invoice(journal, license_at_issue, author, page_charge_count, color_figure_count):
    base_cents = round_half_up_int(
        Fraction(journal["apc_base_cents"]) * LICENSE_MULTIPLIER[license_at_issue]
    )
    waiver_pct = WAIVER_PCT[author["country_income_band"]]
    waiver_cents = round_half_up_int(Fraction(base_cents * waiver_pct, 100))
    institutional_pct = INSTITUTIONAL_PCT if author["institutional_agreement"] else 0
    institutional_cents = round_half_up_int(
        Fraction((base_cents - waiver_cents) * institutional_pct, 100)
    )
    net_apc_cents = base_cents - waiver_cents - institutional_cents
    auto_waived = False
    if 0 < net_apc_cents < MIN_BILLABLE_CENTS:
        net_apc_cents = 0
        auto_waived = True

    raw_surcharge_cents = (
        page_charge_count * journal["page_charge_cents_per_page"]
        + color_figure_count * journal["color_figure_charge_cents"]
    )
    provisional_total_cents = net_apc_cents + raw_surcharge_cents
    if provisional_total_cents >= RELIEF_TIER_2_CENTS:
        surcharge_relief_pct = 20
    elif provisional_total_cents >= RELIEF_TIER_1_CENTS:
        surcharge_relief_pct = 10
    else:
        surcharge_relief_pct = 0
    surcharge_cents = raw_surcharge_cents - round_half_up_int(
        Fraction(raw_surcharge_cents * surcharge_relief_pct, 100)
    )
    total_due_cents = net_apc_cents + surcharge_cents
    return {
        "base_cents": base_cents,
        "waiver_pct": waiver_pct,
        "waiver_cents": waiver_cents,
        "institutional_pct": institutional_pct,
        "institutional_cents": institutional_cents,
        "net_apc_cents": net_apc_cents,
        "auto_waived": auto_waived,
        "raw_surcharge_cents": raw_surcharge_cents,
        "provisional_total_cents": provisional_total_cents,
        "surcharge_relief_pct": surcharge_relief_pct,
        "surcharge_cents": surcharge_cents,
        "total_due_cents": total_due_cents,
    }


# ==========================================================================
# editor_assignment_selection
# ==========================================================================
def eligible_editors(manuscript, exclude_editor_ids=()):
    author = author_of(manuscript)
    coauthors = manuscript.get("coauthor_emails") or []
    recused_editor_ids = {
        a["editor_id"] for a in assignments_of_manuscript(manuscript["id"]) if a["state"] == "RECUSED"
    }
    pool = []
    for editor in store.editors.values():
        if editor["journal_id"] != manuscript["journal_id"]:
            continue
        if editor["status"] != "ACTIVE":
            continue
        if editor["role_level"] != "HANDLING":
            continue
        if manuscript["subject_area"] not in (editor["subject_areas"] or []):
            continue
        if editor["active_assignment_count"] >= editor["max_concurrent_assignments"]:
            continue
        if author is not None and editor["email"] == author["email"]:
            continue
        if editor["email"] in coauthors:
            continue
        if author is not None and editor["affiliation"] == author["affiliation"]:
            continue
        if editor["id"] in recused_editor_ids:
            continue
        if editor["id"] in exclude_editor_ids:
            continue
        pool.append(editor)
    return pool


def select_editor(manuscript, exclude_editor_ids=()):
    pool = eligible_editors(manuscript, exclude_editor_ids)
    if not pool:
        return None
    pool.sort(
        key=lambda e: (
            Fraction(e["active_assignment_count"], e["max_concurrent_assignments"]),
            -e["max_concurrent_assignments"],
            e["created_at"],
            e["_seq"],
        )
    )
    return pool[0]


# ==========================================================================
# reviewer_window_occupancy + reviewer_invitation_selection
# ==========================================================================
def overlapping_open_windows(reviewer_id, new_start, new_end):
    """Half-open [invited_at, due_at) windows, strict on both sides."""
    count = 0
    for invitation in invitations_of_reviewer(reviewer_id):
        if invitation["state"] not in OPEN_STATES:
            continue
        start = parse_ts(invitation["invited_at"])
        end = parse_ts(invitation["due_at"])
        if start is None or end is None:
            continue
        if new_start < end and start < new_end:
            count += 1
    return count


def reviewer_conflict(reviewer, manuscript, handling_editor):
    author = author_of(manuscript)
    coauthors = manuscript.get("coauthor_emails") or []
    if author is not None and reviewer["email"] == author["email"]:
        return True
    if reviewer["email"] in coauthors:
        return True
    if author is not None and reviewer["affiliation"] == author["affiliation"]:
        return True
    if handling_editor is not None and reviewer["email"] == handling_editor["email"]:
        return True
    for invitation in invitations_of_manuscript(manuscript["id"]):
        if invitation["reviewer_id"] == reviewer["id"] and invitation["state"] in OPEN_STATES:
            return True
    return False


def eligible_reviewers(manuscript, handling_editor, new_start, new_end, window_limit):
    author = author_of(manuscript)
    coauthors = manuscript.get("coauthor_emails") or []
    pool = []
    for reviewer in store.reviewers.values():
        if reviewer["status"] != "ACTIVE":
            continue
        if manuscript["subject_area"] not in (reviewer["subject_areas"] or []):
            continue
        if author is not None and reviewer["email"] == author["email"]:
            continue
        if reviewer["email"] in coauthors:
            continue
        if author is not None and reviewer["affiliation"] == author["affiliation"]:
            continue
        if handling_editor is not None and reviewer["email"] == handling_editor["email"]:
            continue
        blocked = False
        for invitation in invitations_of_manuscript(manuscript["id"]):
            if invitation["reviewer_id"] == reviewer["id"] and invitation["state"] in (
                "INVITED",
                "ACCEPTED",
                "SUBMITTED",
            ):
                blocked = True
                break
        if blocked:
            continue
        if overlapping_open_windows(reviewer["id"], new_start, new_end) >= window_limit:
            continue
        pool.append(reviewer)
    return pool


def select_reviewer(manuscript, handling_editor, new_start, new_end, window_limit):
    pool = eligible_reviewers(manuscript, handling_editor, new_start, new_end, window_limit)
    if not pool:
        return None
    pool.sort(
        key=lambda r: (
            -_frac(r["reliability_score_rolling"]),
            r["open_invitation_count"],
            r["created_at"],
            r["_seq"],
        )
    )
    return pool[0]


# ==========================================================================
# typeset_slot_occupancy
# ==========================================================================
def typeset_slot_blockers(job, manuscript, journal, slot_start, slot_end):
    buffer_days = timedelta(days=journal["typeset_changeover_buffer_days"])
    blockers = []
    for other in store.production_jobs.values():
        if other["id"] == job["id"]:
            continue
        if not other.get("slot_start"):
            continue
        if other["content_stage"] == "TERMINATED":
            continue
        other_manuscript = store.manuscripts.get(other["manuscript_id"])
        if other_manuscript is None:
            continue
        if other_manuscript["journal_id"] != manuscript["journal_id"]:
            continue
        other_start = _as_date(other["slot_start"])
        other_end = _as_date(other["slot_end"])
        if other_start is None or other_end is None:
            continue
        if slot_start <= other_end + buffer_days and other_start <= slot_end + buffer_days:
            blockers.append(other)
    return blockers


def _as_date(text):
    if not text:
        return None
    year, month, day = str(text).split("-")
    return date(int(year), int(month), int(day))


# ==========================================================================
# embargo_end_date_projection
# ==========================================================================
def _last_day_of_month(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def embargo_end_date(oa_license, publication_date, embargo_months):
    parsed = _as_date(publication_date)
    if parsed is None:
        return None
    if oa_license != "GREEN_SELF_ARCHIVE":
        return publication_date
    total = (parsed.month - 1) + embargo_months
    target_year = parsed.year + total // 12
    target_month = total % 12 + 1
    last_day = _last_day_of_month(target_year, target_month)
    return "%04d-%02d-%02d" % (target_year, target_month, min(parsed.day, last_day))


# ==========================================================================
# journal_metrics_rollup
# ==========================================================================
DECIDED_STATES = (
    "DESK_REJECTED",
    "REJECTED",
    "IN_PRODUCTION",
    "PUBLISHED",
    "CORRECTED",
    "RETRACTED",
)
ACCEPTED_STATES = ("IN_PRODUCTION", "PUBLISHED", "CORRECTED", "RETRACTED")


def journal_metrics(journal):
    manuscripts = [m for m in store.manuscripts.values() if m["journal_id"] == journal["id"]]
    manuscript_ids = {m["id"] for m in manuscripts}
    decided = [m for m in manuscripts if m["status"] in DECIDED_STATES]
    accepted = [m for m in manuscripts if m["status"] in ACCEPTED_STATES]
    invitations = [i for i in store.invitations.values() if i["manuscript_id"] in manuscript_ids]

    if decided:
        acceptance_rate_pct = round_half_up(Fraction(100 * len(accepted), len(decided)), 2)
    else:
        acceptance_rate_pct = 0.00

    latencies = []
    for manuscript in manuscripts:
        rows = decisions_of_manuscript(manuscript["id"])
        if manuscript["decision_count"] <= 0 or not rows:
            continue
        first = rows[0]
        delta_ms = (
            parse_ts(first["created_at"]) - parse_ts(manuscript["created_at"])
        ).total_seconds() * 1000.0
        latencies.append(int(math.ceil(delta_ms / MS_PER_DAY)))
    latencies.sort()
    if not latencies:
        median = None
    elif len(latencies) % 2 == 1:
        median = latencies[(len(latencies) - 1) // 2]
    else:
        upper = len(latencies) // 2
        median = round_half_up(Fraction(latencies[upper - 1] + latencies[upper], 2), 2)

    if invitations:
        accepted_invitations = [i for i in invitations if i["state"] in ("ACCEPTED", "SUBMITTED")]
        invitation_rate = round_half_up(
            Fraction(100 * len(accepted_invitations), len(invitations)), 2
        )
    else:
        invitation_rate = 0.00

    return {
        "submitted_count": len(manuscripts),
        "desk_rejected_count": len([m for m in manuscripts if m["status"] == "DESK_REJECTED"]),
        "published_count": len(
            [m for m in manuscripts if m["status"] in ("PUBLISHED", "CORRECTED")]
        ),
        "retracted_count": len([m for m in manuscripts if m["status"] == "RETRACTED"]),
        "acceptance_rate_pct": acceptance_rate_pct,
        "median_days_to_first_decision": median,
        "reviewer_invitation_acceptance_rate_pct": invitation_rate,
        "reviewers_on_probation_count": len(
            [r for r in store.reviewers.values() if r["status"] == "PROBATION"]
        ),
        "apc_receivable_cents": journal["apc_receivable_cents"],
        "apc_waived_cents": journal["apc_waived_cents"],
    }
