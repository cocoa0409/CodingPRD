"""Derived state: consent precedence, channel resolution, households, segments."""

from decimal import Decimal

import db
from services import calc

SENSITIVE_ATTRIBUTES = (
    "inferred_health_interest",
    "inferred_ethnicity_affinity",
    "precise_geolocation_grid",
)

SEGMENT_ATTRIBUTES = (
    "postal_code",
    "loyalty_tier",
    "lifetime_value_cents",
    "channel_engagement_score",
) + SENSITIVE_ATTRIBUTES

ALL_CHANNELS_SORTED = tuple(sorted(calc.CHANNELS))

BLANKET_SUPPRESSION_TYPES = ("PRIVACY_DELETE", "GLOBAL_OPT_OUT", "LEGAL_HOLD")
DELIVERING_ACTIVATION_STATUSES = ("DISPATCHED", "ACTIVE", "UNDERPERFORMING")
OCCUPYING_ACTIVATION_STATUSES = ("DRAFT", "DISPATCHED", "ACTIVE", "UNDERPERFORMING", "PAUSED")
OPEN_DELETION_STATUSES = ("RECEIVED", "BLOCKED_LEGAL_HOLD", "PROPAGATING", "PARTIALLY_VERIFIED")


# ------------------------------------------------------------- lookups

def trust_tier_of(source_system_id):
    source = db.store["source_systems"].get(source_system_id)
    if source is None:
        return 0
    return source.get("trust_tier") or 0


def profile_consents(profile_id):
    return [c for c in db.all_of("consent_records") if c["profile_id"] == profile_id]


def profile_suppressions(profile_id):
    return [s for s in db.all_of("suppression_entries") if s["profile_id"] == profile_id]


def active_suppressions(profile_id):
    return [s for s in profile_suppressions(profile_id) if s["status"] == "ACTIVE"]


def in_window(entry, moment):
    """Half-open window: effective_at inclusive, expires_at exclusive."""
    if entry["effective_at"] > moment:
        return False
    if entry["expires_at"] is not None and entry["expires_at"] <= moment:
        return False
    return True


# --------------------------------------------------- consent precedence

def _group_key(record):
    return (record["profile_id"], record["channel"], record["purpose"])


def rerank_consent_group(profile_id, channel, purpose, skip_version_ids=()):
    members = [
        c for c in db.all_of("consent_records")
        if _group_key(c) == (profile_id, channel, purpose)
        and c["status"] in ("ACTIVE", "SUPERSEDED")
    ]
    members.sort(key=lambda c: (
        -c["captured_at"].timestamp(),
        -trust_tier_of(c["source_system_id"]),
        c["created_at"],
        c["_seq"],
    ))
    for index, record in enumerate(members):
        rank = index + 1
        status = "ACTIVE" if rank == 1 else "SUPERSEDED"
        if record["precedence_rank"] != rank or record["status"] != status:
            record["precedence_rank"] = rank
            record["status"] = status
            if record["id"] not in skip_version_ids:
                db.touch(record)


def rerank_all_groups_for(profile_id, skip_version_ids=()):
    keys = {_group_key(c) for c in profile_consents(profile_id)}
    for profile, channel, purpose in sorted(keys, key=lambda k: (k[1], k[2])):
        rerank_consent_group(profile, channel, purpose, skip_version_ids)


# ------------------------------------------- effective_channel_consent

def resolve_channels(profile, moment=None):
    """Returns an ordered list of per-channel decisions for one profile."""
    moment = moment or db.now()
    decisions = []
    blanket = None
    do_not_sell = None
    for entry in sorted(active_suppressions(profile["id"]), key=lambda s: (s["created_at"], s["_seq"])):
        if not in_window(entry, moment):
            continue
        if entry["entry_type"] in BLANKET_SUPPRESSION_TYPES and blanket is None:
            blanket = entry
        if entry["entry_type"] == "DO_NOT_SELL" and do_not_sell is None:
            do_not_sell = entry
    elections = _marketing_elections(profile["id"], moment)
    for channel in ALL_CHANNELS_SORTED:
        if profile["resolution_status"] == "MERGED_AWAY":
            decisions.append(_decision(channel, "OPT_OUT", None, "MERGED_AWAY"))
            continue
        if profile["privacy_status"] != "NORMAL":
            decisions.append(_decision(channel, "OPT_OUT", None, "PRIVACY_STATUS"))
            continue
        if blanket is not None:
            decisions.append(_decision(channel, "OPT_OUT", None, "SUPPRESSED_ALL_CHANNELS"))
            continue
        if do_not_sell is not None and channel == "ADVERTISING":
            decisions.append(_decision(channel, "OPT_OUT", None, "DO_NOT_SELL"))
            continue
        winner = elections.get(channel)
        if winner is None:
            decisions.append(_decision(channel, "OPT_OUT", None, "NO_ELECTION"))
        else:
            decisions.append(_decision(channel, winner["consent_state"], winner["id"], "ELECTION"))
    return decisions


def _decision(channel, state, record_id, reason):
    return {
        "channel": channel,
        "consent_state": state,
        "consent_record_id": record_id,
        "reason": reason,
    }


def _marketing_elections(profile_id, moment):
    qualifying = {}
    for record in profile_consents(profile_id):
        if record["purpose"] != "MARKETING":
            continue
        if record["status"] not in ("ACTIVE", "SUPERSEDED"):
            continue
        if record["captured_at"] > moment:
            continue
        if record["expires_at"] is not None and record["expires_at"] <= moment:
            continue
        qualifying.setdefault(record["channel"], []).append(record)
    winners = {}
    for channel, records in qualifying.items():
        records.sort(key=lambda c: (
            -c["captured_at"].timestamp(),
            -trust_tier_of(c["source_system_id"]),
            c["created_at"],
            c["_seq"],
        ))
        winners[channel] = records[0]
    return winners


def activatable_channels(profile, moment=None):
    return sorted(
        d["channel"] for d in resolve_channels(profile, moment)
        if d["consent_state"] == "OPT_IN"
    )


def engagement_score(profile, moment=None):
    count = len(activatable_channels(profile, moment))
    return calc.round_half_up(Decimal(count) / Decimal(len(calc.CHANNELS)), 2)


def active_consent_count(profile_id):
    return sum(1 for c in profile_consents(profile_id) if c["status"] == "ACTIVE")


# ------------------------------------------------------- privacy status

def derive_privacy_status(profile):
    if profile["privacy_status"] == "DELETED":
        return "DELETED"
    for request in db.all_of("deletion_requests"):
        if request["profile_id"] == profile["id"] and request["status"] in OPEN_DELETION_STATUSES:
            return "DELETION_PENDING"
    entries = active_suppressions(profile["id"])
    if any(e["entry_type"] == "LEGAL_HOLD" for e in entries):
        return "LEGAL_HOLD"
    if entries:
        return "SUPPRESSED"
    return "NORMAL"


def apply_privacy_status(profile):
    """Re-derive the privacy axis. Returns True when it moved."""
    resolved = derive_privacy_status(profile)
    if profile["privacy_status"] != resolved:
        profile["privacy_status"] = resolved
        return True
    return False


def has_active_legal_hold(profile_id):
    return any(e["entry_type"] == "LEGAL_HOLD" and e["status"] == "ACTIVE"
               for e in profile_suppressions(profile_id))


# ------------------------------------------------------------ households

def household_members(household_id):
    return [
        p for p in db.all_of("profiles")
        if p["household_id"] == household_id
        and p["resolution_status"] != "MERGED_AWAY"
        and p["privacy_status"] != "DELETED"
    ]


def household_member_count(household_id):
    return len(household_members(household_id))


def dominant_last_name(members):
    counts = {}
    for member in members:
        last = member.get("last_name")
        if last is None:
            continue
        counts[last] = counts.get(last, 0) + 1
    if not counts:
        return None
    best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return best[0][0]


def combined_lifetime_value(members):
    return sum(m["lifetime_value_cents"] for m in members)


def refresh_household(household):
    """Dissolve a household that has lost its last member. Returns True when it moved."""
    if household["status"] != "ACTIVE":
        return False
    if household_member_count(household["id"]) == 0:
        household["status"] = "DISSOLVED"
        return True
    return False


def assign_household(profile):
    """household_grouping waterfall for one profile with a non-null address_hash."""
    if profile.get("address_hash") is None:
        return None, None
    buckets = [
        h for h in db.all_of("households")
        if h["address_hash"] == profile["address_hash"] and h["status"] == "ACTIVE"
    ]
    buckets.sort(key=lambda h: (h["sequence_no"], h["created_at"], h["_seq"]))
    for bucket in buckets:
        if household_member_count(bucket["id"]) < calc.HOUSEHOLD_MAX_MEMBERS:
            profile["household_id"] = bucket["id"]
            return bucket, False
    existing = [h for h in db.all_of("households") if h["address_hash"] == profile["address_hash"]]
    next_no = max((h["sequence_no"] for h in existing), default=0) + 1
    household = db.new_entity(
        "households",
        address_hash=profile["address_hash"],
        sequence_no=next_no,
        status="ACTIVE",
    )
    profile["household_id"] = household["id"]
    return household, True


# ------------------------------------------------------- source systems

IN_WINDOW_BATCH_STATUSES = ("VALIDATED", "QUARANTINED", "PROMOTED", "REJECTED")


def source_window_batches(source):
    window_start = source.get("dq_window_start_at")
    result = []
    for batch in db.all_of("ingest_batches"):
        if batch["source_system_id"] != source["id"]:
            continue
        if batch["status"] not in IN_WINDOW_BATCH_STATUSES:
            continue
        if window_start is not None and batch["created_at"] < window_start:
            continue
        result.append(batch)
    return result


def source_totals(source):
    batches = source_window_batches(source)
    submitted = sum(b["record_count"] for b in batches)
    valid = sum(b["valid_record_count"] or 0 for b in batches)
    return submitted, valid, calc.pass_rate(valid, submitted)


def source_breaches_floor(source):
    submitted, _valid, rate = source_totals(source)
    if submitted < calc.DQ_MIN_SAMPLE:
        return False
    return rate < calc.dec(source["pii_completeness_floor"])


# ---------------------------------------------------------- segments

def segment_eligible_profiles():
    return [
        p for p in db.all_of("profiles")
        if p["resolution_status"] != "MERGED_AWAY" and p["privacy_status"] == "NORMAL"
    ]


def attribute_value(profile, attribute):
    if attribute == "channel_engagement_score":
        return engagement_score(profile)
    return profile.get(attribute)


def _satisfies(profile, criterion):
    attribute = criterion["attribute"]
    operator = criterion["operator"]
    expected = criterion["value"]
    actual = attribute_value(profile, attribute)
    if actual is None:
        return False
    if operator == "EQ":
        if attribute == "channel_engagement_score":
            return calc.dec(actual) == calc.dec(expected)
        return actual == expected
    if operator == "IN":
        if not isinstance(expected, list):
            return False
        if attribute == "channel_engagement_score":
            return any(calc.dec(actual) == calc.dec(v) for v in expected
                       if isinstance(v, (int, float)) and not isinstance(v, bool))
        return actual in expected
    if operator == "GTE":
        return _gte(attribute, actual, expected)
    return False


def _gte(attribute, actual, expected):
    if attribute == "loyalty_tier":
        left = calc.LOYALTY_ORDINAL.get(actual)
        if isinstance(expected, str):
            right = calc.LOYALTY_ORDINAL.get(expected)
        elif isinstance(expected, bool):
            right = None
        elif isinstance(expected, (int, float)):
            right = int(expected)
        else:
            right = None
        if left is None or right is None:
            return False
        return left >= right
    numeric_left = isinstance(actual, (int, float, Decimal)) and not isinstance(actual, bool)
    numeric_right = isinstance(expected, (int, float, Decimal)) and not isinstance(expected, bool)
    if numeric_left and numeric_right:
        return calc.dec(actual) >= calc.dec(expected)
    if isinstance(actual, str) and isinstance(expected, str):
        return actual >= expected
    return False


def segment_members(segment):
    members = []
    for profile in segment_eligible_profiles():
        matched = True
        for criterion in segment["criteria"]:
            if not _satisfies(profile, criterion):
                matched = False
                break
        if matched:
            members.append(profile)
    return db.by_seq(members)


def segment_member_count(segment):
    if segment["status"] == "RETIRED":
        return len(segment_members(segment))
    return len(segment_members(segment))


def uses_sensitive(criteria):
    return any(c["attribute"] in SENSITIVE_ATTRIBUTES for c in criteria)


def segment_activations(segment_id):
    return [a for a in db.all_of("activations") if a["segment_id"] == segment_id]


def active_activation_count(segment_id):
    return sum(
        1 for a in segment_activations(segment_id)
        if a["status"] in DELIVERING_ACTIVATION_STATUSES
    )


def destination_activations(destination_id):
    return [a for a in db.all_of("activations") if a["destination_id"] == destination_id]


def underperforming_count(destination_id):
    return sum(1 for a in destination_activations(destination_id) if a["status"] == "UNDERPERFORMING")
