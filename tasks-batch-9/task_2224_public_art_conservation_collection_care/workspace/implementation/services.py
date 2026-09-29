"""Roll-ups, shared guards and the three named cascades (PRD 2.9)."""

import calc
from db import (
    db,
    fmt_instant,
    now,
    ordered,
    parse_date,
    parse_instant,
    touch,
)
from errors import ApiError

TERMINAL_CUSTODY = ("DEACCESSIONED", "DESTROYED")
ENCUMBERED = ("RESERVED", "COMMITTED", "DISBURSED")
LIVE_PROPOSAL_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "IN_EXECUTION")
ENGAGED_STATUSES = ("APPROVED", "IN_EXECUTION")
COHORT_STATUSES = ("TREATMENT_REQUIRED", "TREATMENT_IN_PROGRESS")


# ---------------------------------------------------------------------------
# resolution (PRD 2.8 steps 3 and 5)
# ---------------------------------------------------------------------------

def fetch(store, ident, error_id):
    rec = store.get(ident) if isinstance(ident, str) else None
    if rec is None:
        raise ApiError(error_id)
    return rec


def artwork_or_404(ident):
    return fetch(db.artworks, ident, "ERR_ARTWORK_NOT_FOUND")


def artist_or_404(ident):
    return fetch(db.artists, ident, "ERR_ARTIST_NOT_FOUND")


def site_or_404(ident):
    return fetch(db.sites, ident, "ERR_SITE_NOT_FOUND")


def protocol_or_404(ident):
    return fetch(db.protocols, ident, "ERR_PROTOCOL_NOT_FOUND")


def visit_or_404(ident):
    return fetch(db.visits, ident, "ERR_VISIT_NOT_FOUND")


def assessment_or_404(ident):
    return fetch(db.assessments, ident, "ERR_ASSESSMENT_NOT_FOUND")


def conservator_or_404(ident):
    return fetch(db.conservators, ident, "ERR_CONSERVATOR_NOT_FOUND")


def proposal_or_404(ident):
    return fetch(db.proposals, ident, "ERR_PROPOSAL_NOT_FOUND")


def consultation_or_404(ident):
    return fetch(db.consultations, ident, "ERR_CONSULTATION_NOT_FOUND")


def notice_or_404(ident):
    return fetch(db.notices, ident, "ERR_NOTICE_NOT_FOUND")


def case_or_404(ident):
    return fetch(db.cases, ident, "ERR_CASE_NOT_FOUND")


def pool_or_404(ident):
    return fetch(db.pools, ident, "ERR_POOL_NOT_FOUND")


def allocation_or_404(ident):
    return fetch(db.allocations, ident, "ERR_ALLOCATION_NOT_FOUND")


def incident_or_404(ident):
    return fetch(db.incidents, ident, "ERR_INCIDENT_NOT_FOUND")


# ---------------------------------------------------------------------------
# shared guards
# ---------------------------------------------------------------------------

def require_in_collection(artwork):
    """PRD 2.8 step 12."""
    if artwork["custody_status"] in TERMINAL_CUSTODY:
        raise ApiError("ERR_ARTWORK_DEACCESSIONED")


def require_state(current, allowed, error_id):
    """PRD 2.8 step 9."""
    if current not in allowed:
        raise ApiError(error_id)


# ---------------------------------------------------------------------------
# roll-ups (PRD 2.5: a server-initiated change is a mutation)
# ---------------------------------------------------------------------------

def recompute_artist_count(artist):
    if artist is None:
        return
    total = sum(1 for a in db.artworks.values() if a["artist_id"] == artist["id"])
    if artist.get("artwork_count") != total:
        artist["artwork_count"] = total
        touch(artist)


def recompute_site_units(site):
    if site is None:
        return
    total = 0
    for art in db.artworks.values():
        if art["site_id"] == site["id"] and art["custody_status"] in ("ON_VIEW", "IN_TREATMENT"):
            total += int(art["footprint_units"])
    if site.get("installed_units_used") != total:
        site["installed_units_used"] = total
        touch(site)


def recompute_open_notice_count(artwork):
    if artwork is None:
        return
    total = sum(
        1
        for n in db.notices.values()
        if n["artwork_id"] == artwork["id"]
        and n["status"] in ("SENT", "ACKNOWLEDGED", "WAIT_ELAPSED")
    )
    if artwork.get("open_notice_count") != total:
        artwork["open_notice_count"] = total
        touch(artwork)


def recompute_engagement_count(conservator):
    if conservator is None:
        return
    total = sum(
        1
        for p in db.proposals.values()
        if p["conservator_id"] == conservator["id"] and p["status"] in ENGAGED_STATUSES
    )
    if conservator.get("active_engagement_count") != total:
        conservator["active_engagement_count"] = total
        touch(conservator)


def recompute_maintenance_ytd(artwork):
    if artwork is None:
        return
    year = now().year
    total = 0
    for v in db.visits.values():
        if v["artwork_id"] != artwork["id"] or v["status"] != "COMPLETED":
            continue
        stamp = v.get("completed_at")
        if not stamp:
            continue
        try:
            if parse_instant(stamp).year == year:
                total += 1
        except Exception:
            continue
    if artwork.get("maintenance_applications_ytd") != total:
        artwork["maintenance_applications_ytd"] = total
        touch(artwork)


def recompute_pool(pool):
    """PRD 3.10: available = authorized + credits - encumbered."""
    if pool is None:
        return
    encumbered = 0
    for alloc in db.allocations.values():
        if alloc["pool_id"] == pool["id"] and alloc["status"] in ENCUMBERED:
            encumbered += int(alloc["amount_cents"])
    available = (
        int(pool["draw_authorized_cents"])
        + int(pool["recovery_credits_cents"])
        - encumbered
    )
    if pool.get("available_cents") != available:
        pool["available_cents"] = available
        touch(pool)


def recompute_ranks():
    """PRD 3.9: score DESC then created_at ASC over the treatment cohort."""
    cohort = [a for a in db.artworks.values() if a["conservation_status"] in COHORT_STATUSES]

    def sort_key(rec):
        score = rec.get("treatment_priority_score")
        primary = float(score) if score is not None else float("-inf")
        return (-primary, rec.get("created_at") or "", rec.get("_seq", 0))

    cohort.sort(key=sort_key)
    ranked = {}
    for index, art in enumerate(cohort, start=1):
        ranked[art["id"]] = index
    for art in db.artworks.values():
        wanted = ranked.get(art["id"])
        if art.get("treatment_priority_rank") != wanted:
            art["treatment_priority_rank"] = wanted
            touch(art)


# ---------------------------------------------------------------------------
# money movement
# ---------------------------------------------------------------------------

def allocations_for_proposal(proposal_id):
    return [a for a in ordered(db.allocations.values()) if a.get("proposal_id") == proposal_id]


def allocations_for_visit(visit_id):
    return [a for a in ordered(db.allocations.values()) if a.get("visit_id") == visit_id]


def release_allocation(alloc, reason):
    if alloc["status"] not in ("RESERVED", "COMMITTED"):
        return False
    alloc["status"] = "RELEASED"
    alloc["release_reason"] = reason
    alloc["released_at"] = fmt_instant(now())
    touch(alloc)
    recompute_pool(db.pools.get(alloc["pool_id"]))
    return True


def advance_allocations(allocs, from_status, to_status):
    for alloc in allocs:
        if alloc["status"] == from_status:
            alloc["status"] = to_status
            touch(alloc)
            recompute_pool(db.pools.get(alloc["pool_id"]))


# ---------------------------------------------------------------------------
# scores
# ---------------------------------------------------------------------------

def site_of(artwork):
    return db.sites.get(artwork["site_id"])


def score_single_assessment(artwork, assessment):
    return calc.treatment_priority_score(
        assessment["condition_index"], artwork, site_of(artwork), 0
    )


def score_cycle_cohort(artwork, assessment):
    days = (now().date() - parse_date(assessment["assessed_on"])).days
    if days < 0:
        days = 0
    return calc.treatment_priority_score(
        assessment["condition_index"], artwork, site_of(artwork), days
    )


# ---------------------------------------------------------------------------
# moral-rights authorisation (PRD 3.6)
# ---------------------------------------------------------------------------

def authorizing_notice(artwork, action_types):
    """Returns the notice that authorises the action, or raises."""
    candidates = [
        n
        for n in ordered(db.notices.values())
        if n["artwork_id"] == artwork["id"]
        and n["action_type"] in action_types
        and n["status"] in ("ACKNOWLEDGED", "WAIT_ELAPSED")
    ]
    if not candidates:
        raise ApiError("ERR_MORAL_RIGHTS_NOTICE_REQUIRED")
    clock = now()
    for notice in candidates:
        if parse_instant(notice["earliest_action_at"]) <= clock:
            return notice
    raise ApiError("ERR_MORAL_RIGHTS_WAIT_ACTIVE")


def consume_notice(notice, consumed_by_ref):
    notice["status"] = "CONSUMED"
    notice["consumed_by_ref"] = consumed_by_ref
    touch(notice)


# ---------------------------------------------------------------------------
# Cascade A -- a condition survey is finalized (PRD 2.9, 3.2)
# ---------------------------------------------------------------------------

def cascade_a(assessment, artwork):
    # hop 1: prior finalized surveys on the same work are superseded
    for other in ordered(db.assessments.values()):
        if (
            other["id"] != assessment["id"]
            and other["artwork_id"] == artwork["id"]
            and other["status"] == "FINALIZED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)

    # hop 2: the work adopts the new index, score and basis
    index = assessment["condition_index"]
    artwork["condition_index"] = index
    artwork["treatment_priority_score"] = score_single_assessment(artwork, assessment)
    artwork["priority_basis"] = "SINGLE_ASSESSMENT"
    became_required = False
    if (
        calc.D(index) < calc.TREATMENT_TRIGGER_INDEX
        and artwork["conservation_status"] in ("MONITORED", "STABILIZED")
    ):
        artwork["conservation_status"] = "TREATMENT_REQUIRED"
        became_required = True
    touch(artwork)

    # hop 3: pointless routine visits are aborted
    if became_required:
        for visit in ordered(db.visits.values()):
            if visit["artwork_id"] != artwork["id"] or visit["status"] != "SCHEDULED":
                continue
            protocol = db.protocols.get(visit["protocol_id"])
            if protocol is not None and protocol.get("requires_conservator"):
                continue
            visit["status"] = "ABORTED"
            visit["abort_reason"] = "SUPERSEDED_BY_TREATMENT"
            touch(visit)
            # hops 4 and 5: their funding is released and pools rise
            for alloc in allocations_for_visit(visit["id"]):
                release_allocation(alloc, "VISIT_ABORTED")

    recompute_ranks()


# ---------------------------------------------------------------------------
# Cascade B -- an approved deaccession is executed (PRD 2.9, 3.8)
# ---------------------------------------------------------------------------

def cascade_b(case, artwork, consumed_notice):
    # hop 1: terminal custody, footprint returned to the site
    artwork["custody_status"] = (
        "DESTROYED" if case["disposition"] == "DESTRUCTION" else "DEACCESSIONED"
    )
    touch(artwork)
    recompute_site_units(site_of(artwork))

    # hop 2: everything still hanging off the work is terminated
    for proposal in ordered(db.proposals.values()):
        if proposal["artwork_id"] != artwork["id"]:
            continue
        if proposal["status"] not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED"):
            continue
        was_approved = proposal["status"] == "APPROVED"
        proposal["status"] = "WITHDRAWN"
        proposal["withdraw_reason"] = "ARTWORK_DEACCESSIONED"
        touch(proposal)
        if was_approved:
            recompute_engagement_count(db.conservators.get(proposal["conservator_id"]))
        # hop 3 and 4
        for alloc in allocations_for_proposal(proposal["id"]):
            release_allocation(alloc, "PROPOSAL_WITHDRAWN")

    for visit in ordered(db.visits.values()):
        if visit["artwork_id"] != artwork["id"] or visit["status"] != "SCHEDULED":
            continue
        visit["status"] = "ABORTED"
        visit["abort_reason"] = "ARTWORK_DEACCESSIONED"
        touch(visit)
        for alloc in allocations_for_visit(visit["id"]):
            release_allocation(alloc, "VISIT_ABORTED")

    for consultation in ordered(db.consultations.values()):
        if consultation["artwork_id"] == artwork["id"] and consultation["status"] == "PENDING":
            consultation["status"] = "LAPSED"
            touch(consultation)

    for notice in ordered(db.notices.values()):
        if notice["artwork_id"] != artwork["id"]:
            continue
        if consumed_notice is not None and notice["id"] == consumed_notice["id"]:
            continue
        if notice["status"] in ("SENT", "ACKNOWLEDGED", "WAIT_ELAPSED"):
            notice["status"] = "VOID"
            touch(notice)

    # the authorising notice is finally spent
    if consumed_notice is not None:
        consume_notice(consumed_notice, case["id"])

    recompute_open_notice_count(artwork)


# ---------------------------------------------------------------------------
# Cascade C -- a treatment proposal is approved (PRD 2.9, 3.5)
# ---------------------------------------------------------------------------

def cascade_c(proposal, artwork):
    for other in ordered(db.proposals.values()):
        if other["id"] == proposal["id"] or other["artwork_id"] != artwork["id"]:
            continue
        if other["status"] not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
            continue
        other["status"] = "WITHDRAWN"
        other["withdraw_reason"] = "PROPOSAL_SUPERSEDED"
        touch(other)
        for alloc in allocations_for_proposal(other["id"]):
            release_allocation(alloc, "PROPOSAL_WITHDRAWN")
