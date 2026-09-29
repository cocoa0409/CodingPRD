"""Multi-hop cascades: audience recompute, pause/terminate, merge, tombstone."""

import db
from services import calc, derive


# ------------------------------------------------ activation audience

def resolve_audience(segment, destination):
    members = derive.segment_members(segment)
    candidate_count = len(members)
    audience = [m for m in members if destination["channel"] in derive.activatable_channels(m)]
    field = ("email_norm" if destination["hashing_algorithm"] == "SHA256_EMAIL_LOWER"
             else "phone_norm")
    dispatched = sum(1 for m in audience if m.get(field) is not None)
    return {
        "candidate_count": candidate_count,
        "audience_size": len(audience),
        "suppressed_count": candidate_count - len(audience),
        "dispatched_hash_count": dispatched,
    }


def _segment_of(activation):
    return db.store["segments"].get(activation["segment_id"])


def _destination_of(activation):
    return db.store["destinations"].get(activation["destination_id"])


def audience_cascade(re_derive_rates=False):
    """Recompute every delivering activation; pause the ones whose audience emptied."""
    paused = 0
    for activation in db.by_seq(db.all_of("activations")):
        if activation["status"] not in derive.DELIVERING_ACTIVATION_STATUSES:
            continue
        segment = _segment_of(activation)
        destination = _destination_of(activation)
        if segment is None or destination is None:
            continue
        counts = resolve_audience(segment, destination)
        changed = False
        for key in ("candidate_count", "audience_size", "suppressed_count"):
            if activation[key] != counts[key]:
                activation[key] = counts[key]
                changed = True
        if counts["audience_size"] == 0:
            pause_activation(activation, "CONSENT_WITHDRAWN")
            paused += 1
            continue
        if changed:
            activation["updated_at"] = db.now()
        if re_derive_rates and activation["gross_match_rate"] is not None:
            apply_match_rates(activation, destination)
    return paused


def apply_match_rates(activation, destination):
    """Re-derive the three rates and move ACTIVE <-> UNDERPERFORMING accordingly."""
    gross, net = calc.match_rates(
        activation["dispatched_hash_count"],
        activation["vendor_matched_count"] or 0,
        activation["unusable_hash_count"] or 0,
    )
    activation["gross_match_rate"] = gross
    activation["net_match_rate"] = net
    effective = gross if destination["match_rate_basis"] == "GROSS" else net
    activation["effective_match_rate"] = effective
    floor = calc.dec(destination["min_match_rate"])
    if effective >= floor:
        if activation["status"] == "UNDERPERFORMING":
            activation["status"] = "ACTIVE"
            db.touch(destination)
            db.touch(activation)
    else:
        if activation["status"] == "ACTIVE":
            activation["status"] = "UNDERPERFORMING"
            db.touch(destination)
            db.touch(activation)


# ------------------------------------------------------ pause / resume

def pause_activation(activation, reason):
    destination = _destination_of(activation)
    activation["status"] = "PAUSED"
    activation["paused_reason"] = reason
    if destination is not None:
        destination["remaining_daily_hash_quota"] += activation["dispatched_hash_count"]
        db.touch(destination)
    db.touch(activation)
    segment = _segment_of(activation)
    if segment is not None:
        governance_hop(segment)


def terminate_activation(activation):
    destination = _destination_of(activation)
    refund = activation["status"] in derive.DELIVERING_ACTIVATION_STATUSES
    activation["status"] = "TERMINATED"
    activation["paused_reason"] = "SEGMENT_RETIRED"
    activation["terminated_at"] = db.now()
    if refund and destination is not None:
        destination["remaining_daily_hash_quota"] += activation["dispatched_hash_count"]
        db.touch(destination)
    db.touch(activation)


# ------------------------------------------------------ segment governance

def governance_hop(segment):
    """Hop three: a segment whose last delivering activation left and whose approval lapsed."""
    if segment["status"] != "APPROVED":
        return 0
    if derive.active_activation_count(segment["id"]) != 0:
        return 0
    expires = segment["governance_expires_at"]
    if expires is None or db.now() < expires:
        return 0
    return expire_governance(segment)


def expire_governance(segment):
    """APPROVED -> GOVERNANCE_EXPIRED plus the pause-and-refund cascade."""
    segment["status"] = "GOVERNANCE_EXPIRED"
    segment["sensitive_use_approved"] = False
    db.touch(segment)
    paused = 0
    for activation in db.by_seq(derive.segment_activations(segment["id"])):
        if activation["status"] in derive.DELIVERING_ACTIVATION_STATUSES:
            pause_activation(activation, "GOVERNANCE_EXPIRED")
            paused += 1
    return paused


def retire_segment(segment):
    segment["status"] = "RETIRED"
    db.touch(segment)
    for activation in db.by_seq(derive.segment_activations(segment["id"])):
        if activation["status"] != "TERMINATED":
            terminate_activation(activation)


# ---------------------------------------------------------------- merge

SURVIVORSHIP_FIELDS = (
    "email_norm", "phone_norm", "first_name", "last_name",
    "postal_code", "address_hash", "loyalty_number",
)


def _survivor_rank(profile):
    source = db.store["source_systems"].get(profile["primary_source_system_id"])
    tier = source["trust_tier"] if source else 0
    return (-profile["source_record_count"], -tier, profile["created_at"], profile["_seq"])


def choose_survivor(left, right):
    if _survivor_rank(left) <= _survivor_rank(right):
        return left, right
    return right, left


def _reelect_primary_source(profile):
    candidates = [
        s for s in db.all_of("source_systems")
        if s["code"] in profile["contributing_source_system_codes"]
    ]
    if not candidates:
        return
    candidates.sort(key=lambda s: (-s["trust_tier"], s["created_at"], s["_seq"]))
    profile["primary_source_system_id"] = candidates[0]["id"]


def merge_profiles(left, right, link):
    survivor, loser = choose_survivor(left, right)
    for field in SURVIVORSHIP_FIELDS:
        if survivor.get(field) is None and loser.get(field) is not None:
            survivor[field] = loser[field]
    survivor["source_record_count"] += loser["source_record_count"]
    survivor["lifetime_value_cents"] += loser["lifetime_value_cents"]
    survivor["contributing_source_system_codes"] = sorted(
        set(survivor["contributing_source_system_codes"])
        | set(loser["contributing_source_system_codes"])
    )
    if loser["last_activity_at"] is not None:
        if survivor["last_activity_at"] is None or loser["last_activity_at"] > survivor["last_activity_at"]:
            survivor["last_activity_at"] = loser["last_activity_at"]
    if calc.LOYALTY_ORDINAL[loser["loyalty_tier"]] > calc.LOYALTY_ORDINAL[survivor["loyalty_tier"]]:
        survivor["loyalty_tier"] = loser["loyalty_tier"]
    _reelect_primary_source(survivor)

    moved_groups = set()
    for record in derive.profile_consents(loser["id"]):
        if record["status"] != "ACTIVE":
            continue
        record["profile_id"] = survivor["id"]
        db.touch(record)
        moved_groups.add((record["channel"], record["purpose"]))
    for entry in derive.profile_suppressions(loser["id"]):
        if entry["status"] != "ACTIVE":
            continue
        entry["profile_id"] = survivor["id"]
        db.touch(entry)

    loser_household_id = loser["household_id"]
    loser["resolution_status"] = "MERGED_AWAY"
    loser["merged_into_profile_id"] = survivor["id"]
    loser["household_id"] = None
    loser["lifetime_value_cents"] = 0

    for channel, purpose in sorted(moved_groups):
        derive.rerank_consent_group(survivor["id"], channel, purpose)

    for other in db.by_seq(db.all_of("identity_links")):
        if link is not None and other["id"] == link["id"]:
            continue
        if other["status"] != "PROPOSED":
            continue
        if loser["id"] not in (other["left_profile_id"], other["right_profile_id"]):
            continue
        other["status"] = "VOIDED"
        other["void_reason"] = "SUPERSEDED"
        db.touch(other)

    if loser_household_id is not None:
        household = db.store["households"].get(loser_household_id)
        if household is not None:
            derive.refresh_household(household)
            db.touch(household)
            if survivor["household_id"] is None and household["status"] == "ACTIVE" \
                    and household["address_hash"] == survivor.get("address_hash"):
                survivor["household_id"] = household["id"]
    if survivor["household_id"] is None and survivor.get("address_hash") is not None:
        household, created = derive.assign_household(survivor)
        if household is not None and not created:
            db.touch(household)

    db.touch(loser)
    db.touch(survivor)
    return survivor, loser


# ------------------------------------------------------------ tombstone

TOMBSTONE_FIELDS = (
    "email_norm", "phone_norm", "first_name", "last_name",
    "inferred_health_interest", "inferred_ethnicity_affinity", "precise_geolocation_grid",
)


def tombstone_profile(profile):
    profile["privacy_status"] = "DELETED"
    for field in TOMBSTONE_FIELDS:
        profile[field] = None
    for record in db.by_seq(derive.profile_consents(profile["id"])):
        if record["status"] == "TOMBSTONED":
            continue
        record["status"] = "TOMBSTONED"
        record["precedence_rank"] = 0
        db.touch(record)
    for link in db.by_seq(db.all_of("identity_links")):
        endpoints = (link["left_profile_id"], link["right_profile_id"])
        if link["status"] == "PROPOSED" and profile["id"] in endpoints:
            link["status"] = "VOIDED"
            link["void_reason"] = "PROFILE_DELETED"
            db.touch(link)
        elif link["status"] == "CONFIRMED" and link["survivor_profile_id"] == profile["id"]:
            link["status"] = "VOIDED"
            link["void_reason"] = "PROFILE_DELETED"
            db.touch(link)
    household_id = profile["household_id"]
    profile["household_id"] = None
    if household_id is not None:
        household = db.store["households"].get(household_id)
        if household is not None:
            derive.refresh_household(household)
            db.touch(household)
    db.touch(profile)


# ------------------------------------------------------- rule precision

def disable_rule_if_imprecise(rule):
    if rule["status"] != "ENABLED":
        return False
    precision = calc.precision_estimate(rule["confirmed_count"], rule["rejected_count"])
    if precision >= calc.dec(rule["min_precision"]):
        return False
    rule["status"] = "DISABLED"
    for link in db.by_seq(db.all_of("identity_links")):
        if link["match_rule_id"] != rule["id"] or link["status"] != "PROPOSED":
            continue
        link["status"] = "VOIDED"
        link["void_reason"] = "RULE_DISABLED"
        db.touch(link)
    return True


# ------------------------------------------------- legal hold / deletion

def unblock_deletion_requests(profile_id):
    for request in db.by_seq(db.all_of("deletion_requests")):
        if request["profile_id"] != profile_id:
            continue
        if request["status"] != "BLOCKED_LEGAL_HOLD":
            continue
        request["status"] = "RECEIVED"
        request["blocked_reason"] = None
        db.touch(request)
