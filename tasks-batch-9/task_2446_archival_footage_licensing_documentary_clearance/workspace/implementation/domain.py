"""Derived state: asset clearance rollup, production posture, ledgers, staleness."""
from core import by_seq, db, fail, touch
from calc import DEPICTION_BUFFER_DAYS

# --- status sets ------------------------------------------------------------
LIVE_COVERAGE = ("EXECUTED", "ACTIVE", "EXPIRING")
NEGOTIATING = ("DRAFT", "QUOTED", "COUNTERED")
OVERLAP_STATUSES = ("DRAFT", "QUOTED", "COUNTERED", "EXECUTED", "ACTIVE", "EXPIRING")
OPEN_LICENSING = ("UNCLEARED", "IN_NEGOTIATION", "PARTIALLY_CLEARED", "LAPSED")
LIVE_RELEASE_STATUSES = ("SENT", "REVISION_REQUESTED", "SIGNED", "APPROVAL_GRANTED")


# --- lookups ---------------------------------------------------------------
def licenses_of_asset(asset_id):
    return by_seq([l for l in db.licenses.values() if l["asset_id"] == asset_id])


def licenses_of_production(production_id):
    return by_seq([l for l in db.licenses.values() if l["production_id"] == production_id])


def assets_of_production(production_id):
    return by_seq([a for a in db.assets.values() if a["production_id"] == production_id])


def charts_of_production(production_id):
    return by_seq([c for c in db.clearance_charts.values()
                   if c["production_id"] == production_id])


def candidates_of_asset(asset_id):
    return by_seq([c for c in db.source_candidates.values() if c["asset_id"] == asset_id])


def analyses_of_asset(asset_id):
    return by_seq([f for f in db.fair_use_analyses.values() if f["asset_id"] == asset_id])


def letters_of_analysis(analysis_id):
    return by_seq([o for o in db.opinion_letters.values()
                   if o["fair_use_analysis_id"] == analysis_id])


def releases_of_production(production_id):
    return by_seq([r for r in db.subject_releases.values()
                   if r["production_id"] == production_id])


def eo_apps_of_production(production_id):
    return by_seq([e for e in db.eo_applications.values()
                   if e["production_id"] == production_id])


def packages_of_production(production_id):
    return by_seq([p for p in db.delivery_packages.values()
                   if p["production_id"] == production_id])


def rate_cards_of_archive(archive_id):
    return by_seq([r for r in db.rate_cards.values() if r["archive_id"] == archive_id])


def required_legs(asset):
    if asset["asset_type"] == "MUSIC":
        return {"MASTER", "PUBLISHING"}
    return {"FOOTAGE"}


def coverage_of_asset(asset):
    """(covered_legs set, covering license ids in created_at ASC)."""
    legs = set()
    ids = []
    for lic in licenses_of_asset(asset["id"]):
        if lic["status"] in LIVE_COVERAGE:
            legs.add(lic["rights_leg"])
            ids.append(lic["id"])
    return legs, ids


# --- chart staleness (PRD 2.10) --------------------------------------------
def stale_charts_for_asset(asset):
    for chart in charts_of_production(asset["production_id"]):
        if chart["status"] != "PINNED":
            continue
        for row in chart["pinned_rows"]:
            if row["asset_id"] == asset["id"] and row["asset_version"] != asset["version"]:
                chart["status"] = "STALE"
                touch(chart)
                break


def bump_asset(asset):
    """Every write to an asset row bumps its version and may stale pinned charts."""
    touch(asset)
    stale_charts_for_asset(asset)


# --- asset clearance rollup (PRD 3.1) --------------------------------------
def rollup_asset(asset):
    """Recompute rights_basis / lapse_count / licensing_status. True when changed."""
    req = required_legs(asset)
    covered, _ids = coverage_of_asset(asset)
    all_licenses = licenses_of_asset(asset["id"])

    # step 1 — rights_basis, first match wins
    if asset.get("pd_attestation_reference") is not None:
        basis = "PUBLIC_DOMAIN"
    elif any(f["status"] == "ACCEPTED" for f in analyses_of_asset(asset["id"])):
        basis = "FAIR_USE"
    elif req <= covered:
        basis = "LICENSED"
    else:
        basis = "UNDETERMINED"

    previous = asset["licensing_status"]
    lapse_count = asset["lapse_count"]

    # step 2 — lapse accounting, BEFORE step 3
    if previous == "CLEARED" and basis == "UNDETERMINED":
        lapse_count += 1

    # step 3 — licensing_status, first match wins
    if basis != "UNDETERMINED":
        licensing = "CLEARED"
    elif lapse_count > 0 and not covered:
        licensing = "LAPSED"
    elif covered:
        licensing = "PARTIALLY_CLEARED"
    elif any(l["status"] in NEGOTIATING for l in all_licenses):
        licensing = "IN_NEGOTIATION"
    else:
        licensing = "UNCLEARED"

    changed = (
        basis != asset["rights_basis"]
        or lapse_count != asset["lapse_count"]
        or licensing != asset["licensing_status"]
    )
    if changed:
        asset["rights_basis"] = basis
        asset["lapse_count"] = lapse_count
        asset["licensing_status"] = licensing
        bump_asset(asset)
    return changed


def set_depiction_status(asset, status):
    if asset["depiction_status"] == status:
        return False
    asset["depiction_status"] = status
    bump_asset(asset)
    return True


# --- production posture and ledgers (PRD 2.8, 2.9) -------------------------
def compute_posture(assets):
    asset_count = len(assets)
    open_count = sum(1 for a in assets if a["licensing_status"] in OPEN_LICENSING)
    blocked = sum(1 for a in assets if a["depiction_status"] == "BLOCKED")
    lapsed = sum(1 for a in assets if a["licensing_status"] == "LAPSED")
    pending_depiction = sum(1 for a in assets if a["depiction_status"] == "PENDING")

    if asset_count == 0:
        return "OPEN"
    if blocked > 0 or lapsed > 0:
        return "BLOCKED"
    if open_count == 0 and pending_depiction == 0:
        return "OPEN"
    if open_count * 4 <= asset_count:
        return "RESTRICTED"
    return "BLOCKED"


def recompute_production(production):
    """Counters, ledger and posture. Never bumps the production's version itself."""
    assets = assets_of_production(production["id"])
    production["asset_count"] = len(assets)
    production["cleared_asset_count"] = sum(
        1 for a in assets if a["licensing_status"] == "CLEARED")
    production["open_asset_count"] = sum(
        1 for a in assets if a["licensing_status"] in OPEN_LICENSING)
    production["posture"] = compute_posture(assets)
    recompute_committed(production)
    return production["posture"]


def recompute_committed(production):
    total = 0
    for lic in licenses_of_production(production["id"]):
        if lic["status"] in LIVE_COVERAGE and lic["executed_fee_cents"] is not None:
            total += lic["executed_fee_cents"]
    production["committed_fee_cents"] = total


def production_of(row):
    return db.productions[row["production_id"]]


# --- posture-driven downstream cascade (hops 4 & 5) ------------------------
def cascade_blocked_posture(production, suspension_reason):
    """When posture is BLOCKED: suspend DELIVERED packages, remediate BOUND E&O."""
    suspended = []
    remediated = []
    if production["posture"] != "BLOCKED":
        return suspended, remediated
    for pkg in packages_of_production(production["id"]):
        if pkg["status"] == "DELIVERED":
            pkg["status"] = "SUSPENDED"
            pkg["suspension_reason"] = suspension_reason
            touch(pkg)
            suspended.append(pkg["id"])
    if suspended:
        for app in eo_apps_of_production(production["id"]):
            if app["status"] == "BOUND":
                app["status"] = "REMEDIATION_REQUIRED"
                touch(app)
                remediated.append(app["id"])
    return suspended, remediated


# --- overlap helpers (PRD 3.3) --------------------------------------------
def media_overlap(a, b):
    return a == b or a == "ALL_MEDIA" or b == "ALL_MEDIA"


def territory_overlap(a, b):
    return a == b or a == "WORLD" or b == "WORLD"


def terms_intersect(start_a, end_a, start_b, end_b):
    """Half-open [start, end): adjacency does not overlap."""
    return start_a < end_b and start_b < end_a


def has_term_overlap(asset_id, rights_leg, media, territory, start, end, exclude_id=None):
    from core import parse_date
    for lic in licenses_of_asset(asset_id):
        if lic["id"] == exclude_id:
            continue
        if lic["status"] not in OVERLAP_STATUSES:
            continue
        if lic["rights_leg"] != rights_leg:
            continue
        if not media_overlap(lic["media"], media):
            continue
        if not territory_overlap(lic["territory"], territory):
            continue
        other_start = parse_date(lic["term_start_date"], "term_start_date")
        other_end = parse_date(lic["term_end_date"], "term_end_date")
        if terms_intersect(start, end, other_start, other_end):
            return True
    return False


# --- depiction window conflict (PRD 3.6) ----------------------------------
def has_depiction_conflict(production_id, subject_person_key, from_date, to_date):
    from datetime import timedelta
    from core import parse_date

    wide_from = from_date - timedelta(days=DEPICTION_BUFFER_DAYS)
    wide_to = to_date + timedelta(days=DEPICTION_BUFFER_DAYS)
    for rel in releases_of_production(production_id):
        if rel["subject_person_key"] != subject_person_key:
            continue
        if rel["status"] not in LIVE_RELEASE_STATUSES:
            continue
        other_from = parse_date(rel["depiction_from_date"], "depiction_from_date")
        other_to = parse_date(rel["depiction_to_date"], "depiction_to_date")
        # closed intervals on both sides
        if wide_from <= other_to and other_from <= wide_to:
            return True
    return False


# --- rate card resolution (rung 18) ---------------------------------------
def active_rate_card(archive_id, on_or_before_date):
    from core import parse_date
    for card in rate_cards_of_archive(archive_id):
        if card["status"] != "ACTIVE":
            continue
        if parse_date(card["effective_from_date"], "effective_from_date") <= on_or_before_date:
            return card
    return None


# --- path-parameter resolution (rung 5) ----------------------------------
def get_or_404(table, row_id, error_id):
    row = table.get(row_id)
    if row is None:
        fail(error_id)
    return row


def get_production(pid):
    return get_or_404(db.productions, pid, "ERR_PRODUCTION_NOT_FOUND")


def get_archive(aid):
    return get_or_404(db.archives, aid, "ERR_ARCHIVE_NOT_FOUND")


def get_asset(aid):
    return get_or_404(db.assets, aid, "ERR_ASSET_NOT_FOUND")


def get_license(lid):
    return get_or_404(db.licenses, lid, "ERR_LICENSE_NOT_FOUND")


def get_analysis(fid):
    return get_or_404(db.fair_use_analyses, fid, "ERR_FAIR_USE_ANALYSIS_NOT_FOUND")


def get_letter(oid):
    return get_or_404(db.opinion_letters, oid, "ERR_OPINION_LETTER_NOT_FOUND")


def get_release(rid):
    return get_or_404(db.subject_releases, rid, "ERR_SUBJECT_RELEASE_NOT_FOUND")


def get_chart(cid):
    return get_or_404(db.clearance_charts, cid, "ERR_CLEARANCE_CHART_NOT_FOUND")


def get_eo(eid):
    return get_or_404(db.eo_applications, eid, "ERR_EO_APPLICATION_NOT_FOUND")


def get_package(pid):
    return get_or_404(db.delivery_packages, pid, "ERR_DELIVERY_PACKAGE_NOT_FOUND")
