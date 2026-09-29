"""Shared business logic: cascades, recomputations and state helpers."""

import calc
import db
from errors import fail


# --------------------------------------------------------------------------- #
# lookups                                                                     #
# --------------------------------------------------------------------------- #
def find(collection, identifier):
    if not isinstance(identifier, str):
        return None
    return collection.get(identifier)


def require_path(collection, identifier, error_id):
    record = find(collection, identifier)
    if record is None:
        fail(error_id)
    return record


def require_ref(collection, identifier, error_id):
    record = find(collection, identifier)
    if record is None:
        fail(error_id)
    return record


def all_of(collection):
    return db.ordered(list(collection.values()))


# --------------------------------------------------------------------------- #
# methodology guards (PRD sections 3.2, 3.3, 3.7)                                     #
# --------------------------------------------------------------------------- #
def evaluate_lapse(methodology):
    """Lapse evaluation: a PROVISIONAL or ACCREDITED version whose effective_to
    the logical clock has reached or passed moves to LAPSED, its version
    increments, and the triggering request is rejected with
    ERR_METHODOLOGY_LAPSED.
    """
    status = methodology["accreditation_status"]
    if status in calc.ACCREDITATION_LIVE:
        effective_to = db.parse_dt(methodology["effective_to"])
        if effective_to is not None and db.clock_now() >= effective_to:
            methodology["accreditation_status"] = "LAPSED"
            db.touch(methodology)
            fail("ERR_METHODOLOGY_LAPSED")


def guard_methodology_live(methodology):
    """Lapse first, then accreditation standing."""
    evaluate_lapse(methodology)
    status = methodology["accreditation_status"]
    if status == "SUSPENDED":
        fail("ERR_METHODOLOGY_NOT_ACCREDITED")
    if status == "LAPSED":
        fail("ERR_METHODOLOGY_LAPSED")


def guard_methodology_effective_at(methodology, instant):
    effective_from = db.parse_dt(methodology["effective_from"])
    effective_to = db.parse_dt(methodology["effective_to"])
    if instant is None:
        return
    if effective_from is not None and instant < effective_from:
        fail("ERR_METHODOLOGY_LAPSED")
    if effective_to is not None and instant >= effective_to:
        fail("ERR_METHODOLOGY_LAPSED")


# --------------------------------------------------------------------------- #
# publisher restriction cascade (PRD sections 3.1, 3.5, 3.6)                          #
# --------------------------------------------------------------------------- #
def maybe_restrict_publisher(publisher):
    """Hop 2 of the quarantine / MFA cascade: an ACTIVE publisher whose
    quarantined_batch_count or mfa_page_count has reached its limit moves
    ACTIVE -> RESTRICTED, then the list and segment staling hops follow.
    """
    if publisher["publisher_status"] != "ACTIVE":
        return False
    quarantined = int(publisher["quarantined_batch_count"])
    mfa = int(publisher["mfa_page_count"])
    if quarantined < calc.PUBLISHER_QUARANTINE_LIMIT and mfa < calc.PUBLISHER_MFA_LIMIT:
        return False
    publisher["publisher_status"] = "RESTRICTED"
    if quarantined >= calc.PUBLISHER_QUARANTINE_LIMIT:
        publisher["status_reason"] = "QUARANTINE_THRESHOLD"
    else:
        publisher["status_reason"] = "MFA_THRESHOLD"
    db.touch(publisher)
    stale_lists_naming_publisher(publisher["id"])
    return True


def stale_lists_naming_publisher(publisher_id):
    """Every PUBLISHED list holding an ALLOW / PUBLISHER entry naming this
    publisher moves PUBLISHED -> STALE with stale_reason
    RESTRICTED_PUBLISHER_ENTRY; then every SYNCED segment referencing one of
    those lists moves SYNCED -> STALE with stale_reason LIST_STALE.
    """
    staled = []
    for record in db.ordered(list(db.inventory_lists.values())):
        if record["status"] != "PUBLISHED":
            continue
        if not any(
            entry["list_id"] == record["id"]
            and entry["action"] == "ALLOW"
            and entry["entry_type"] == "PUBLISHER"
            and entry["entry_value"] == publisher_id
            for entry in db.list_entries.values()
        ):
            continue
        record["status"] = "STALE"
        record["stale_reason"] = "RESTRICTED_PUBLISHER_ENTRY"
        db.touch(record)
        staled.append(record["id"])
    if staled:
        stale_segments_referencing(staled)
    return staled


def stale_segments_referencing(list_ids):
    ids = set(list_ids)
    for segment in db.ordered(list(db.pre_bid_segments.values())):
        if segment["sync_status"] != "SYNCED":
            continue
        if segment.get("inclusion_list_id") in ids or segment.get("exclusion_list_id") in ids:
            segment["sync_status"] = "STALE"
            segment["stale_reason"] = "LIST_STALE"
            db.touch(segment)


def stale_segments_of_campaign(campaign_id):
    for segment in db.ordered(list(db.pre_bid_segments.values())):
        if segment["campaign_id"] != campaign_id:
            continue
        if segment["sync_status"] != "SYNCED":
            continue
        segment["sync_status"] = "STALE"
        segment["stale_reason"] = "CAMPAIGN_UNDER_REMEDIATION"
        db.touch(segment)


# --------------------------------------------------------------------------- #
# campaign coverage                                                           #
# --------------------------------------------------------------------------- #
def refresh_coverage_after_certify(campaign):
    campaign["coverage_status"] = calc.coverage_status(campaign)
    if campaign["status"] == "UNDER_REMEDIATION" and campaign["coverage_status"] == "ON_TARGET":
        campaign["status"] = "ACTIVE"
    db.touch(campaign)


def refresh_coverage_after_decertify(campaign):
    campaign["coverage_status"] = calc.coverage_status(campaign)
    db.touch(campaign)
    if campaign["coverage_status"] == "BELOW_TARGET" and campaign["status"] == "ACTIVE":
        campaign["status"] = "UNDER_REMEDIATION"
        db.touch(campaign)
        stale_segments_of_campaign(campaign["id"])


# --------------------------------------------------------------------------- #
# invalid traffic recomputation (PRD section 3.8)                                     #
# --------------------------------------------------------------------------- #
def confirmed_findings(batch_id):
    return [
        finding
        for finding in db.ivt_findings.values()
        if finding["batch_id"] == batch_id and finding["status"] == "CONFIRMED"
    ]


def recompute_batch_ivt(batch):
    figures = calc.ivt_dedup(batch["measured_impressions"], confirmed_findings(batch["id"]))
    batch["ivt_impressions"] = figures["ivt_impressions"]
    batch["ivt_rate"] = calc.num4(figures["ivt_rate"])
    batch["sophistication_flag"] = figures["sophistication_flag"]
    batch["net_billable_impressions"] = figures["net_billable_impressions"]
    db.touch(batch)


# --------------------------------------------------------------------------- #
# suitability snapshot (PRD section 3.7)                                              #
# --------------------------------------------------------------------------- #
def assess_batch_tier(batch):
    page = db.pages.get(batch["page_id"])
    campaign = db.campaigns.get(batch["campaign_id"])
    tier = None
    if page is not None:
        tier = page.get("current_tier")
    if not tier:
        tier = calc.TIER_UNRATED
    batch["assessed_tier"] = tier
    floor_tier = campaign["min_suitability_tier"] if campaign else None
    batch["suitability_breach_flag"] = calc.worse_than(tier, floor_tier)


# --------------------------------------------------------------------------- #
# claim recomputation (PRD section 3.9)                                               #
# --------------------------------------------------------------------------- #
def cited_batches(claim):
    records = [db.measurement_batches.get(bid) for bid in claim["batch_ids"]]
    return db.ordered([record for record in records if record is not None])


def methodology_of(batch):
    return db.methodology_versions.get(batch["methodology_version_id"])


def compute_basis(claim, variant):
    campaign = db.campaigns.get(claim["campaign_id"])
    cpm_cents = int(campaign["cpm_cents"]) if campaign else 0
    impressions = 0
    cents = 0
    for batch in cited_batches(claim):
        methodology = methodology_of(batch)
        if not calc.batch_is_defective(batch, methodology):
            continue
        if variant == "gross":
            basis = calc.gross_basis_impressions(batch)
        else:
            basis = calc.net_basis_impressions(batch)
        impressions += basis
        cents += calc.credit_cents(basis, cpm_cents)
    return impressions, cents


def refresh_provisional(claim):
    impressions, cents = compute_basis(claim, "gross")
    claim["claimed_impressions"] = impressions
    claim["provisional_credit_cents"] = cents
    return impressions, cents
