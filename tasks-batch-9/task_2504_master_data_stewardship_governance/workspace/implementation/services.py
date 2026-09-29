"""Derived quantities, posture recomputation and the cascades.

Every pinned evaluation order described in PRD 2.7 lives here.
"""

from decimal import Decimal

import db
from util import (CLASSIFICATION_RANK, add_days, add_hours, dec, round2,
                  whole_days_between)

# --- constants -------------------------------------------------------------

RESTRICTED_THRESHOLD = Decimal("15.00")
FROZEN_THRESHOLD = Decimal("40.00")

BASE_POINTS = {"LOW": Decimal("1"), "MEDIUM": Decimal("3"),
               "HIGH": Decimal("8"), "CRITICAL": Decimal("20")}
MULTIPLIER = {"OPEN": Decimal("1.00"), "RESTRICTED": Decimal("1.25"),
              "FROZEN": Decimal("1.50")}

TRUST_TIER_POINTS = Decimal("10")
COMPLETENESS_FACTOR = Decimal("0.40")
RECENCY_MAX = Decimal("20")
RECENCY_DECAY_PER_MONTH = Decimal("4")
DAYS_PER_MONTH = 30

NAME_WEIGHT = Decimal("0.50")
KEY_WEIGHT = Decimal("0.30")
COMPLETENESS_WEIGHT = Decimal("0.20")
INTRA_SOURCE_DISCOUNT = Decimal("0.80")
MATCH_CREATION_FLOOR = Decimal("45.00")
HIGH_CONFIDENCE_FLOOR = Decimal("85.00")
MEDIUM_CONFIDENCE_FLOOR = Decimal("60.00")

PUBLISH_COMPLETENESS_FLOOR = Decimal("60.00")

LEAD_DAYS_CAP = 30
CLASSIFICATION_SURCHARGE_DAYS = 2

STRUCTURAL_LEAD_HOURS = 24
STRUCTURAL_TRAIL_HOURS = 48
NON_STRUCTURAL_LEAD_HOURS = 0
NON_STRUCTURAL_TRAIL_HOURS = 12
SEPARATION_BUFFER_HOURS = 72
STRUCTURAL_CAPACITY_PER_30D = 2
ROLLING_WINDOW_DAYS = 30

SENSITIVE_LEVELS = ("CONFIDENTIAL", "RESTRICTED")
HUNDRED = Decimal("100")


def rank(level):
    return CLASSIFICATION_RANK[level]


# --------------------------------------------------------------------------
# master record derived quantities
# --------------------------------------------------------------------------

def completeness_pct(record, domain):
    populated = 0
    attributes = record.get("attributes") or {}
    for value in attributes.values():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        populated += 1
    raw = round2(HUNDRED * Decimal(populated) / Decimal(domain["expected_attribute_count"]))
    return min(Decimal("100.00"), raw)


def survivorship_score(record):
    source = db.store.source_systems[record["source_system_id"]]
    trust_component = Decimal(source["trust_tier"]) * TRUST_TIER_POINTS
    complete_component = round2(record["completeness_pct"] * COMPLETENESS_FACTOR)
    staleness_days = whole_days_between(record["last_verified_at"], db.now())
    staleness_months = staleness_days // DAYS_PER_MONTH
    recency = RECENCY_MAX - RECENCY_DECAY_PER_MONTH * Decimal(staleness_months)
    if recency < 0:
        recency = Decimal("0")
    return round2(trust_component + complete_component + recency)


def refresh_record_derived(record):
    domain = db.store.domains[record["domain_id"]]
    record["completeness_pct"] = completeness_pct(record, domain)
    record["survivorship_score"] = survivorship_score(record)


# --------------------------------------------------------------------------
# steward load
# --------------------------------------------------------------------------

def recount_steward_load(steward_id):
    steward = db.store.stewards.get(steward_id)
    if steward is None:
        return
    count = 0
    for finding in db.store.quality_findings.values():
        if finding["assigned_steward_id"] == steward_id and finding["status"] == "REMEDIATION_PLANNED":
            count += 1
    if steward["open_finding_load"] != count:
        steward["open_finding_load"] = count
        db.bump(steward)


# --------------------------------------------------------------------------
# posture, counters and the freeze cascade
# --------------------------------------------------------------------------

def open_finding_weight(domain_id):
    total = Decimal("0")
    for finding in db.open_findings_of_domain(domain_id):
        total += finding["severity_weight"]
    return round2(total)


def _has_open_critical(domain_id):
    for finding in db.open_findings_of_domain(domain_id):
        rule = db.store.quality_rules[finding["quality_rule_id"]]
        if rule["severity"] == "CRITICAL":
            return True
    return False


def _freeze_cascade(domain):
    """Hops 4 and 5: retract + quarantine the published set, stale the lineage."""
    for record in db.records_of(domain["id"]):
        if record["publication_status"] == "PUBLISHED":
            record["publication_status"] = "RETRACTED"
            record["curation_status"] = "QUARANTINED"
            record["quarantine_reason"] = "AUTHORITATIVE_SOURCE_LOST"
            db.bump(record)
    for subscription in db.subscriptions_of(domain["id"]):
        if subscription["status"] == "ACTIVE" and subscription["lineage_status"] == "DOCUMENTED":
            subscription["lineage_status"] = "STALE"
            db.bump(subscription)


def recompute_domain(domain):
    """Recompute the derived posture, the authoritative pointer and the conserved
    counters.  Marks the domain as touched only when something actually moved."""
    changed = False
    domain_id = domain["id"]

    registration = db.active_authoritative_registration(domain_id)
    if registration is None:
        code = None
    else:
        code = db.store.source_systems[registration["source_system_id"]]["code"]
    if domain["authoritative_source_code"] != code:
        domain["authoritative_source_code"] = code
        changed = True

    weight = open_finding_weight(domain_id)
    if domain["open_finding_weight"] != weight:
        domain["open_finding_weight"] = weight
        changed = True

    has_auth = registration is not None
    if (not has_auth) or weight >= FROZEN_THRESHOLD:
        posture = "FROZEN"
    elif weight >= RESTRICTED_THRESHOLD or _has_open_critical(domain_id):
        posture = "RESTRICTED"
    else:
        posture = "OPEN"

    previous = domain["governance_posture"]
    if posture != previous:
        domain["governance_posture"] = posture
        changed = True
        if posture == "FROZEN":
            _freeze_cascade(domain)

    published = 0
    for record in db.records_of(domain_id):
        if record["publication_status"] == "PUBLISHED":
            published += 1
    if domain["published_master_record_count"] != published:
        domain["published_master_record_count"] = published
        changed = True

    scheduled = 0
    for request_row in db.change_requests_of(domain_id):
        if request_row["status"] == "SCHEDULED":
            scheduled += 1
    if domain["scheduled_change_count"] != scheduled:
        domain["scheduled_change_count"] = scheduled
        changed = True

    if changed:
        db.touch_domain(domain)
    return posture


def recompute_posture_for_source(source_system_id):
    """Every domain holding an ACTIVE AUTHORITATIVE registration on this system."""
    for domain in db.ordered(db.store.domains):
        registration = db.active_authoritative_registration(domain["id"])
        if registration is not None and registration["source_system_id"] == source_system_id:
            recompute_domain(domain)


# --------------------------------------------------------------------------
# scorecard
# --------------------------------------------------------------------------

def evaluate_scorecard(domain, basis, measurements):
    """Returns (evaluated_rows, weighted_score, evaluated_count, failed_count)
    where evaluated_rows is an ascending-rule_code list of (rule, measured_pct)."""
    active = db.active_rules_of(domain["id"])
    if basis == "PROVISIONAL":
        evaluated = [r for r in active if r["rule_code"] in measurements]
    else:
        evaluated = list(active)
    evaluated.sort(key=lambda r: r["rule_code"])

    rows = []
    for rule in evaluated:
        measured = measurements.get(rule["rule_code"])
        if measured is None:
            measured = Decimal("0.00")
        rows.append((rule, measured))

    if not rows:
        return rows, Decimal("0.00"), 0, 0

    earned_total = Decimal("0")
    weight_total = Decimal("0")
    failed = 0
    for rule, measured in rows:
        threshold = rule["threshold_pct"]
        weight = Decimal(rule["weight_points"])
        if measured >= threshold:
            earned = round2(weight)
        else:
            failed += 1
            earned = round2(weight * measured / threshold)
        earned_total += earned
        weight_total += weight

    score = round2(HUNDRED * earned_total / weight_total)
    return rows, score, len(rows), failed


def stored_measurements(domain):
    """The measurement currently recorded on each rule's latest finding, used by
    the pure computed read of the scorecard."""
    result = {}
    for rule in db.active_rules_of(domain["id"]):
        findings = db.findings_of_rule(rule["id"])
        if findings:
            result[rule["rule_code"]] = findings[-1]["measured_pct"]
    return result


# --------------------------------------------------------------------------
# match score
# --------------------------------------------------------------------------

def match_score(survivor, duplicate, name_similarity_pct, key_overlap_pct):
    lesser = min(survivor["completeness_pct"], duplicate["completeness_pct"])
    base = round2(NAME_WEIGHT * name_similarity_pct
                  + KEY_WEIGHT * key_overlap_pct
                  + COMPLETENESS_WEIGHT * lesser)
    if survivor["source_system_id"] == duplicate["source_system_id"]:
        score = round2(base * INTRA_SOURCE_DISCOUNT)
    else:
        score = base
    return score


def match_confidence(score):
    if score >= HIGH_CONFIDENCE_FLOOR:
        return "HIGH"
    if score >= MEDIUM_CONFIDENCE_FLOOR:
        return "MEDIUM"
    return "LOW"


# --------------------------------------------------------------------------
# survivorship selection
# --------------------------------------------------------------------------

def select_survivor(domain, survivor, duplicate):
    """Returns (variant, winner, loser)."""
    registration = db.active_authoritative_registration(domain["id"])
    authoritative_source = registration["source_system_id"] if registration else None

    survivor_is_auth = (authoritative_source is not None
                        and survivor["source_system_id"] == authoritative_source)
    duplicate_is_auth = (authoritative_source is not None
                         and duplicate["source_system_id"] == authoritative_source)

    if survivor_is_auth != duplicate_is_auth:
        winner = survivor if survivor_is_auth else duplicate
        loser = duplicate if survivor_is_auth else survivor
        return "SOURCE_PRIORITY", winner, loser

    ordered = sorted(
        (survivor, duplicate),
        key=lambda r: (-r["survivorship_score"], -r["last_verified_at"].timestamp(),
                       r["created_at"], r["_seq"]),
    )
    return "SCORE_PRIORITY", ordered[0], ordered[1]


def apply_survivorship(winner, loser):
    """Hop 2 - fill the survivor's gaps from the loser and audit the provenance."""
    field_map = {}
    keys = list((winner.get("attributes") or {}).keys())
    for key in (loser.get("attributes") or {}).keys():
        if key not in keys:
            keys.append(key)

    attributes = dict(winner.get("attributes") or {})
    loser_attributes = loser.get("attributes") or {}
    for key in keys:
        if key in attributes and attributes[key] is not None:
            field_map[key] = winner["natural_key"]
        else:
            attributes[key] = loser_attributes.get(key)
            field_map[key] = loser["natural_key"]
    winner["attributes"] = attributes

    if loser["last_verified_at"] > winner["last_verified_at"]:
        winner["last_verified_at"] = loser["last_verified_at"]
    refresh_record_derived(winner)
    return field_map


# --------------------------------------------------------------------------
# change impact assessment
# --------------------------------------------------------------------------

def impacted_consumers(change_request, domain):
    result = []
    for subscription in db.subscriptions_of(domain["id"]):
        if subscription["status"] != "ACTIVE":
            continue
        if change_request["structural"] or subscription["criticality"] == "TIER1":
            result.append(subscription)
    return result


def assess_impact(change_request, domain):
    impacted = impacted_consumers(change_request, domain)
    count = len(impacted)

    base_lead = max((s["required_lead_days"] for s in impacted), default=0)
    floor_lead = domain["notification_lead_days_floor"] if count >= 1 else 0

    if count >= 5:
        breadth = 3
    elif count >= 3:
        breadth = 1
    else:
        breadth = 0

    classification = (CLASSIFICATION_SURCHARGE_DAYS
                      if domain["classification_level"] in SENSITIVE_LEVELS else 0)

    # PINNED: floor first, then the surcharges, then the cap.
    lead = max(base_lead, floor_lead) + breadth + classification
    lead = min(LEAD_DAYS_CAP, lead)

    change_request["impact_consumer_count"] = count
    change_request["required_lead_days"] = lead
    if change_request["submitted_at"] is not None:
        change_request["earliest_apply_at"] = add_days(change_request["submitted_at"], lead)
    return impacted


# --------------------------------------------------------------------------
# freeze window geometry
# --------------------------------------------------------------------------

def freeze_window(change_request, scheduled_apply_at):
    if change_request["structural"]:
        lead, trail = STRUCTURAL_LEAD_HOURS, STRUCTURAL_TRAIL_HOURS
    else:
        lead, trail = NON_STRUCTURAL_LEAD_HOURS, NON_STRUCTURAL_TRAIL_HOURS
    return add_hours(scheduled_apply_at, -lead), add_hours(scheduled_apply_at, trail)


def window_conflicts(change_request, domain, start, end):
    for other in db.change_requests_of(domain["id"]):
        if other["id"] == change_request["id"] or other["status"] != "SCHEDULED":
            continue
        if other["freeze_window_start"] is None or other["freeze_window_end"] is None:
            continue
        clear_after = start >= add_hours(other["freeze_window_end"], SEPARATION_BUFFER_HOURS)
        clear_before = add_hours(end, SEPARATION_BUFFER_HOURS) <= other["freeze_window_start"]
        if not (clear_after or clear_before):
            return True
    return False


def calendar_capacity_exceeded(change_request, domain, scheduled_apply_at):
    if not change_request["structural"]:
        return False
    neighbours = 0
    span = add_days(scheduled_apply_at, ROLLING_WINDOW_DAYS) - scheduled_apply_at
    for other in db.change_requests_of(domain["id"]):
        if other["id"] == change_request["id"] or other["status"] != "SCHEDULED":
            continue
        if not other["structural"] or other["scheduled_apply_at"] is None:
            continue
        delta = other["scheduled_apply_at"] - scheduled_apply_at
        if abs(delta) <= span:
            neighbours += 1
    return neighbours >= STRUCTURAL_CAPACITY_PER_30D


def clear_notifications(change_request, include_revision=True):
    for subscription in db.store.consumer_subscriptions.values():
        if subscription["pending_change_request_id"] != change_request["id"]:
            continue
        subscription["pending_change_request_id"] = None
        subscription["notified_at"] = None
        subscription["acknowledged_at"] = None
        if include_revision:
            subscription["acknowledged_revision"] = None
        db.bump(subscription)
