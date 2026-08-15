"""Calculation rules (SCAFFOLD section 1.3). Integer arithmetic throughout;
credit-hour workload uses Decimal with ROUND_HALF_UP to one decimal place."""

from decimal import Decimal, ROUND_HALF_UP

from db import STORE

# substantive_change_score constants
BASE = {"NEW_COURSE": 20, "COURSE_CHANGE": 10, "DEACTIVATION": 30}
CREDIT_DELTA_FACTOR = 25
CREDIT_DELTA_RATIO = Decimal("0.25")
PREREQ_PER_LINK = 10
PREREQ_FACTOR_CAP = 20
CROSS_LISTING_FACTOR = 15
TEACH_OUT_FACTOR = 20
NOTIFY_THRESHOLD = 50

# teach-out constants
COHORTS_DRAINED_PER_TERM = 2
CATALOG_TEACH_OUT_TERMS = 4
SECTION_CAPACITY = 15
SECTION_COST_CENTS = 400000

# credit-hour workload constants
WEEKS_PER_TERM = 15
CARNEGIE_HOURS_PER_CREDIT = 45
CREDIT_TOLERANCE = Decimal("0.5")


def ceil_div(a, b):
    return -(-a // b)


def credit_workload_passes(contact_hours, out_of_class_hours, proposed_credit_hours):
    """round_half_up((contact + out) * 15 / 45, 1); pass iff |proposed - computed| <= 0.5."""
    total = Decimal(str(contact_hours)) + Decimal(str(out_of_class_hours))
    computed = (total * WEEKS_PER_TERM) / CARNEGIE_HOURS_PER_CREDIT
    computed = computed.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return abs(Decimal(str(proposed_credit_hours)) - computed) <= CREDIT_TOLERANCE


def _prereq_factor(proposal):
    """10 per payload PREREQUISITE entry with no already-ACTIVE link from the
    target course to that same requisite course; capped at 20."""
    target_id = proposal["target_course_id"]
    count = 0
    for entry in proposal["proposed_requisites"]:
        if entry["requisite_type"] != "PREREQUISITE":
            continue
        if target_id is not None:
            dup = any(
                l for l in STORE["requisite_links"].values()
                if l["course_id"] == target_id
                and l["requisite_course_id"] == entry["requisite_course_id"]
                and l["status"] == "ACTIVE"
            )
            if dup:
                continue
        count += 1
    return min(PREREQ_PER_LINK * count, PREREQ_FACTOR_CAP)


def substantive_change_score(proposal, variant):
    """variant is 'PROVISIONAL' (at submit) or 'FINAL' (on SENATE -> REGISTRAR)."""
    score = BASE[proposal["proposal_type"]]
    if proposal["proposal_type"] == "COURSE_CHANGE":
        target = STORE["courses"].get(proposal["target_course_id"])
        if target is not None:
            current = Decimal(str(target["credit_hours"]))
            proposed = Decimal(str(proposal["proposed_credit_hours"]))
            if current != 0 and abs(proposed - current) / current >= CREDIT_DELTA_RATIO:
                score += CREDIT_DELTA_FACTOR
    score += _prereq_factor(proposal)
    if variant == "FINAL":
        target_id = proposal["target_course_id"]
        if target_id is not None:
            touched = any(
                cl for cl in STORE["cross_listings"].values()
                if (cl["home_course_id"] == target_id or cl["partner_course_id"] == target_id)
                and cl["status"] in ("PENDING", "HOME_APPROVED", "PARTNER_APPROVED", "ACTIVE")
            )
            if touched:
                score += CROSS_LISTING_FACTOR
        if proposal["proposal_type"] == "DEACTIVATION" and (proposal["declared_remaining_cohorts"] or 0) > 0:
            score += TEACH_OUT_FACTOR
    return score


def notification_required(score):
    return score >= NOTIFY_THRESHOLD


def provisional_completion_sequence(last_enrolled_term, enrolled_cohort_count):
    """ENROLLMENT_DRIVEN: last_enrolled sequence + ceil(cohorts / 2)."""
    return last_enrolled_term["sequence_index"] + ceil_div(enrolled_cohort_count, COHORTS_DRAINED_PER_TERM)


def committed_completion_sequence(requested_effective_term):
    """CATALOG_DRIVEN: requested effective term sequence + 4."""
    return requested_effective_term["sequence_index"] + CATALOG_TEACH_OUT_TERMS


def teach_out_resource_cost_cents(cohort_sizes):
    """Per-cohort ceil to whole sections FIRST, then sum, then multiply."""
    sections = sum(ceil_div(size, SECTION_CAPACITY) for size in cohort_sizes)
    return sections * SECTION_COST_CENTS


def _active_prereq_adjacency(extra_edges):
    """Edges course_id -> requisite_course_id from ACTIVE PREREQUISITE links
    plus already-simulated edges from this activation batch."""
    adj = {}
    for l in STORE["requisite_links"].values():
        if l["status"] == "ACTIVE" and l["requisite_type"] == "PREREQUISITE":
            adj.setdefault(l["course_id"], []).append(l["requisite_course_id"])
    for x, r in extra_edges:
        adj.setdefault(x, []).append(r)
    return adj


def would_close_cycle(course_x, requisite_r, extra_edges):
    """Cycle iff X is reachable from R following graph edges."""
    adj = _active_prereq_adjacency(extra_edges)
    stack = [requisite_r]
    seen = set()
    while stack:
        node = stack.pop()
        if node == course_x:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adj.get(node, []))
    return False
