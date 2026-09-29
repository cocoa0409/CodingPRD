"""Serialisation, pagination and the shared cascade helpers.

Every cascade hop here refreshes the touched record's updated_at and bumps its
version by exactly 1 (PRD 2.8).
"""

import calc
import envelope
import store

LIVE_PERIOD_STATUSES = ("ACTIVE", "EXTENDED")
RESPONSIVE_STATUSES = ("SUBMITTED", "SHORTLISTED")
LIVE_DISPOSITION = ("PENDING", "APPROVED", "APPROVED_WITH_CONDITIONS")


# ------------------------------------------------------------- serialisation ---
def public(rec):
    """The record as clients see it; internal bookkeeping keys are stripped."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def respond_list(records, limit, offset):
    page, total = paginate(records, limit, offset)
    return envelope.listing([public(r) for r in page], limit, offset, total)


def created_asc(records):
    """created_at ASC with the hidden insertion sequence as the real comparator so
    records minted at the same logical instant keep their true order."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# -------------------------------------------------------------- child lookups ---
def assessments_of(site_id):
    return [a for a in store.all_of("assessment") if a["site_id"] == site_id]


def solicitations_of(site_id):
    return [s for s in store.all_of("solicitation") if s["site_id"] == site_id]


def valuations_of(site_id):
    return [v for v in store.all_of("valuation") if v["site_id"] == site_id]


def proposals_of(solicitation_id):
    return [p for p in store.all_of("proposal") if p["solicitation_id"] == solicitation_id]


def periods_of(site_id):
    return [p for p in store.all_of("negotiation_period") if p["site_id"] == site_id]


def agreements_of_site(site_id):
    return [a for a in store.all_of("agreement") if a["site_id"] == site_id]


def replacements_of(jda_id):
    return [r for r in store.all_of("facility_replacement") if r["jda_id"] == jda_id]


def dispositions_of(jda_id):
    return [d for d in store.all_of("disposition_request") if d["jda_id"] == jda_id]


def facilities_of(site_id):
    return [f for f in store.all_of("shared_facility") if f["site_id"] == site_id]


def windows_of_facility(facility_id):
    return [w for w in store.all_of("staging_window")
            if w["shared_facility_id"] == facility_id]


def windows_of_agreement(jda_id):
    return [w for w in store.all_of("staging_window") if w["jda_id"] == jda_id]


def live_periods_of_site(site_id, exclude_id=None):
    return [p for p in periods_of(site_id)
            if p["status"] in LIVE_PERIOD_STATUSES and p["id"] != exclude_id]


def period_holding(proposal_id):
    """The live exclusive negotiation period holding this proposal, if any."""
    for period in store.by_seq(store.all_of("negotiation_period")):
        if period["proposal_id"] == proposal_id and period["status"] in LIVE_PERIOD_STATUSES:
            return period
    return None


def any_period_for(proposal_id):
    for period in store.by_seq(store.all_of("negotiation_period")):
        if period["proposal_id"] == proposal_id:
            return period
    return None


def site_has_executed_agreement(site_id):
    return any(a["negotiation_status"] == "EXECUTED" for a in agreements_of_site(site_id))


# ----------------------------------------------------------------- overlap ---
def overlaps_closed_closed(start, end, other_start, other_end):
    """PRD 3.5: sharing even a single boundary day is a collision."""
    return start <= other_end and other_start <= end


def period_collides(site_id, start, end, exclude_id=None):
    for other in live_periods_of_site(site_id, exclude_id=exclude_id):
        if overlaps_closed_closed(start, end,
                                  store.parse_date(other["start_date"]),
                                  store.parse_date(other["end_date"])):
            return True
    return False


# ------------------------------------------------------------- derived counts ---
def refresh_responsive_count(solicitation, bump=False):
    """responsive_proposal_count is the number of SUBMITTED or SHORTLISTED
    proposals of the solicitation.  A refresh that leaves the value unchanged is
    not a mutation and so never bumps the version (PRD 2.4, 3.3)."""
    count = len([p for p in proposals_of(solicitation["id"])
                 if p["status"] in RESPONSIVE_STATUSES])
    changed = solicitation["responsive_proposal_count"] != count
    solicitation["responsive_proposal_count"] = count
    if changed and bump:
        store.touch(solicitation)
    return count


def refresh_available_bays(facility):
    """Denormalised ledger: total less the bays of the facility's APPROVED windows."""
    used = sum(int(w["bays_occupied"]) for w in windows_of_facility(facility["id"])
               if w["status"] == "APPROVED")
    facility["available_bay_capacity"] = int(facility["total_bay_capacity"]) - used
    return facility["available_bay_capacity"]


def conflicting_windows(facility_id, start, end, exclude_id=None):
    """APPROVED windows on the facility overlapping [start, end) half-open."""
    out = []
    for w in windows_of_facility(facility_id):
        if w["status"] != "APPROVED" or w["id"] == exclude_id:
            continue
        w_start = store.parse_dt(w["start_at"])
        w_end = store.parse_dt(w["end_at"])
        if w_start < end and start < w_end:
            out.append((w_start, w_end, int(w["bays_occupied"])))
    return out


def peak_for(facility_id, start, end, bays, exclude_id=None):
    return calc.peak_occupancy(start, bays,
                               conflicting_windows(facility_id, start, end, exclude_id))


# ------------------------------------------------------------------ cascades ---
def release_site_if_free(site, exclude_period_id=None):
    """Conditional cascade: the site returns UNDER_AGREEMENT -> SOLICITATION_READY
    only when no live period remains and no agreement on it is EXECUTED."""
    if site["status"] != "UNDER_AGREEMENT":
        return False
    if live_periods_of_site(site["id"], exclude_id=exclude_period_id):
        return False
    if site_has_executed_agreement(site["id"]):
        return False
    site["status"] = "SOLICITATION_READY"
    store.touch(site)
    return True


def cancel_site_solicitations(site_id, statuses, exclude_ids):
    """Hop 4/5: cancel the site's other solicitations in `statuses` and reject
    their live proposals, each with its own version bump."""
    for solicitation in store.by_seq(solicitations_of(site_id)):
        if solicitation["id"] in exclude_ids:
            continue
        if solicitation["status"] not in statuses:
            continue
        solicitation["status"] = "CANCELLED"
        store.touch(solicitation)
        for proposal in store.by_seq(proposals_of(solicitation["id"])):
            if proposal["status"] in RESPONSIVE_STATUSES:
                proposal["status"] = "REJECTED"
                store.touch(proposal)
        refresh_responsive_count(solicitation)


def move_site_under_agreement(site):
    """Hop 3: a site already UNDER_AGREEMENT stays there."""
    if site["status"] == "SOLICITATION_READY":
        site["status"] = "UNDER_AGREEMENT"
        store.touch(site)
        return True
    return False


def supersede_other_certified(records, keep_id):
    for rec in store.by_seq(records):
        if rec["id"] != keep_id and rec["status"] == "CERTIFIED":
            rec["status"] = "SUPERSEDED"
            store.touch(rec)


def pin_federal_basis(site, appraised_value_cents):
    """The basis is pinned from the appraisal; unencumbered is recomputed so the
    ledger identity of PRD 2.7 holds after every write."""
    basis = calc.rhu(calc.dec(appraised_value_cents) * calc.dec(site["federal_interest_pct"])
                     / calc.D("100"))
    site["federal_interest_basis_cents"] = basis
    site["federal_interest_unencumbered_cents"] = basis - site["federal_interest_encumbered_cents"]
    store.touch(site)
