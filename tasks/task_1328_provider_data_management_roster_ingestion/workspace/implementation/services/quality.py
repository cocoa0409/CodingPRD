"""Data quality scoring per PRD §3.7 and the data_quality_scoring calculation."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import DB, CLOCK, new_id, iso_ts


REQUIRED_KEYS = {
    "DEMOGRAPHIC": ["name", "dob", "gender"],
    "SPECIALTY": ["primary_taxonomy"],
    "PRACTICE_ADDRESS": ["street1", "city", "state", "zip"],
    "CONTACT": ["phone"],
    "LICENSE": ["license_number", "license_state"],
}
ALL_GROUPS = ["DEMOGRAPHIC", "SPECIALTY", "PRACTICE_ADDRESS", "CONTACT", "LICENSE"]


def _active_attributes(provider_id):
    return [
        a for a in DB.provider_attributes.values()
        if a["provider_id"] == provider_id and a["status"] == "ACTIVE"
    ]


def _source_sla(source_id):
    src = DB.roster_sources.get(source_id)
    if src is None:
        return None
    return src.get("freshness_sla_days")


def _group_stale(provider_id, group, today):
    """A group is stale when the most recent effective_date among its ACTIVE
    attributes is earlier than (today - freshness_sla_days of the asserting
    attribute's source); a group with no ACTIVE attributes counts stale.
    The asserting attribute is the one holding the group's max effective_date."""
    attrs = [a for a in _active_attributes(provider_id) if a["attribute_group"] == group]
    if not attrs:
        return True
    newest = max(attrs, key=lambda a: (a["effective_date"], a["created_at"]))
    sla = _source_sla(newest.get("roster_source_id"))
    if sla is None:
        # Manually-written attributes carry no feed SLA; treat as fresh.
        return False
    cutoff = (today - timedelta(days=sla)).isoformat()
    return newest["effective_date"] < cutoff


def compute_staleness_flag(provider_id):
    """True iff any non-terminated attribute group's max effective_date across
    committed rows is older than its source's freshness_sla_days."""
    today = CLOCK.now().date()
    for group in ALL_GROUPS:
        attrs = [
            a for a in DB.provider_attributes.values()
            if a["provider_id"] == provider_id
            and a["attribute_group"] == group
            and a["status"] == "ACTIVE"
            and a.get("term_date") is None
        ]
        if not attrs:
            continue
        newest = max(attrs, key=lambda a: (a["effective_date"], a["created_at"]))
        sla = _source_sla(newest.get("roster_source_id"))
        if sla is None:
            continue
        cutoff = (today - timedelta(days=sla)).isoformat()
        if newest["effective_date"] < cutoff:
            return True
    return False


def _consecutive_unattested(provider_id):
    """Count consecutive EXPIRED/ESCALATED requests scanning backward by
    sent_at DESC, stopping at the first RESPONDED or WITHDRAWN."""
    reqs = [
        r for r in DB.attestation_requests.values()
        if r["provider_id"] == provider_id and r.get("sent_at") is not None
    ]
    reqs.sort(key=lambda r: (r["sent_at"], r["created_at"]), reverse=True)
    count = 0
    for r in reqs:
        if r["status"] in ("EXPIRED", "ESCALATED"):
            count += 1
        elif r["status"] in ("RESPONDED", "WITHDRAWN"):
            break
        else:
            # DRAFT / SENT requests have sent_at None or are in-flight;
            # SENT is neither a stop nor a count — skip it.
            continue
    return count


def compute_score_components(provider_id, directory_variant=False):
    """Compute the four components per PRD §3.7."""
    attrs = _active_attributes(provider_id)

    # completeness (0-40): fraction of 10 required keys with an ACTIVE,
    # non-terminated attribute, scaled by 40, rounded half-up once.
    present = 0
    for group, keys in REQUIRED_KEYS.items():
        for key in keys:
            if any(
                a["attribute_group"] == group
                and a["attribute_key"] == key
                and a.get("term_date") is None
                for a in attrs
            ):
                present += 1
    completeness = int(
        (Decimal(40) * Decimal(present) / Decimal(10)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )

    # freshness (0-30): 6 points per fresh group.
    stale_count = sum(1 for g in ALL_GROUPS if _group_stale(provider_id, g, CLOCK.now().date()))
    freshness = 6 * (5 - stale_count)

    # conflict (0-20): 20 minus 5 per OPEN/ESCALATED conflict (ESCALATED counts
    # double for the DIRECTORY eligibility variant).
    open_conflicts = [
        c for c in DB.attribute_conflicts.values()
        if c["provider_id"] == provider_id and c["status"] in ("OPEN", "ESCALATED")
    ]
    if directory_variant:
        penalty = sum(10 if c["status"] == "ESCALATED" else 5 for c in open_conflicts)
    else:
        penalty = 5 * len(open_conflicts)
    conflict = max(0, 20 - penalty)

    # attestation (0-10): 10 minus 5 per consecutive unanswered outreach.
    consecutive = _consecutive_unattested(provider_id)
    attestation = max(0, 10 - 5 * consecutive)

    return completeness, freshness, conflict, attestation


def run_quality_scoring(provider_id, roster_file_id=None):
    """Append a new DataQualityScore row and refresh the provider's
    current_quality_score and staleness_flag. Returns the score row."""
    provider = DB.providers.get(provider_id)
    if provider is None:
        return None
    c, f, conf, att = compute_score_components(provider_id)
    total = c + f + conf + att
    row = {
        "id": new_id(),
        "created_at": iso_ts(CLOCK.now()),
        "provider_id": provider_id,
        "computed_at": iso_ts(CLOCK.now()),
        "completeness_component": c,
        "freshness_component": f,
        "conflict_component": conf,
        "attestation_component": att,
        "total_score": total,
        "roster_file_id": roster_file_id,
    }
    DB.data_quality_scores[row["id"]] = row
    provider["current_quality_score"] = total
    provider["staleness_flag"] = compute_staleness_flag(provider_id)
    return row


def directory_strict_score(provider_id):
    """Score used only for DIRECTORY eligibility (ESCALATED conflicts cost 10)."""
    c, f, conf, att = compute_score_components(provider_id, directory_variant=True)
    return c + f + conf + att
