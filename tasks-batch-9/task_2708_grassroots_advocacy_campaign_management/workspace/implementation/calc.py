"""Calculation engine and cascade driver (SCAFFOLD 1.3 / PRD 3.x)."""

import math
from decimal import Decimal

from common import (
    D0,
    by_created,
    db,
    dec,
    now_dt,
    r0,
    r2,
    touch,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHANNELS = ("EMAIL", "SMS", "PHONE")
CONSENT_CHANNELS = ("EMAIL", "SMS", "PHONE", "ALL")

CHANNEL_PRESSURE_WEIGHT = {
    "EMAIL": Decimal("1.0"),
    "SMS": Decimal("1.5"),
    "PHONE": Decimal("3.0"),
}
CHANNEL_UNIT_COST_CENTS = {"EMAIL": 2, "SMS": 15, "PHONE": 60}

ACTION_PRESSURE_FACTOR = Decimal("2.0")
ACTION_PRESSURE_CAP = Decimal("60.0")
MEETING_PRESSURE_CREDIT = Decimal("12.0")
MEETING_PRESSURE_CAP = Decimal("24.0")
PRESSURE_SCORE_CEILING = Decimal("100.0")
STANCE_BONUS = {
    "SUPPORT": Decimal("0.0"),
    "LEAN_SUPPORT": Decimal("10.0"),
    "UNDECIDED": Decimal("10.0"),
    "LEAN_OPPOSE": Decimal("4.0"),
    "OPPOSE": Decimal("0.0"),
}
PRESSURE_TIER_PRIMARY_MIN = Decimal("60.00")
PRESSURE_TIER_SECONDARY_MIN = Decimal("30.00")

MILESTONE_PRESSURE_MULTIPLIER = {
    "COMMITTEE_HEARING": Decimal("1.5"),
    "FLOOR_VOTE": Decimal("2.0"),
    "RECESS": Decimal("0.5"),
    "SIGNING": Decimal("1.0"),
}
DEFAULT_MULTIPLIER = Decimal("1.0")

SHARE_WEIGHT = {"ANCHOR": 5, "CORE": 3, "ALLY": 1}

SOURCE_BONUS = {
    "PETITION": Decimal("1.0"),
    "EVENT": Decimal("2.0"),
    "DIGITAL_AD": Decimal("0.5"),
    "REFERRAL": Decimal("1.5"),
}
STORY_BONUS = {
    "NONE": Decimal("0.0"),
    "UNTRAINED": Decimal("0.0"),
    "TRAINED": Decimal("1.0"),
    "CERTIFIED": Decimal("3.0"),
}
DECAY_FRESH_MAX_DAYS = 7
DECAY_FRESH_FACTOR = Decimal("1.00")
DECAY_MID_MAX_DAYS = 30
DECAY_MID_FACTOR = Decimal("0.75")
DECAY_STALE_FACTOR = Decimal("0.50")
THANK_BONUS = Decimal("2.0")
MEETING_LEAD_BONUS = Decimal("5.0")
ENGAGEMENT_CAP = Decimal("50.0")
RETENTION_CAP = Decimal("80.0")
RETENTION_COHORT_MIN = Decimal("10.00")

BASE_TOUCH_CAP_PER_SUPPORTER = 3
SURGE_GRANT_OPEN = 2
SURGE_GRANT_RESTRICTED = 1

BPS_SCALE = 10000
NO_ACTION_CPA_SENTINEL_CENTS = 999999
MIN_TEST_REACH = 3

POSTURE_FROZEN_BLOCKED_MIN = 2
POSTURE_RESTRICTED_BLOCKED_MIN = 1
POSTURE_RESTRICTED_OPPOSED_MIN = 1

MAX_REVISION_ROUNDS = 3
CHANNEL_WINDOW_MAX_OVERLAP = 2
MEETING_TRAVEL_BUFFER_MINUTES = 30

COUNTED_ACTION_STATES = ("MATCHED", "ACKNOWLEDGED", "THANKED")


# ---------------------------------------------------------------------------
# Collection selectors
# ---------------------------------------------------------------------------


def campaign_of_supporter(sup):
    return db.campaigns.get(sup["campaign_id"])


def milestones_of(campaign_id):
    return by_created(
        [m for m in db.milestones.values() if m["campaign_id"] == campaign_id]
    )


def legislators_of(campaign_id):
    return by_created(
        [l for l in db.legislators.values() if l["campaign_id"] == campaign_id]
    )


def supporters_of(campaign_id):
    return by_created(
        [s for s in db.supporters.values() if s["campaign_id"] == campaign_id]
    )


def segments_of(campaign_id):
    return by_created(
        [s for s in db.segments.values() if s["campaign_id"] == campaign_id]
    )


def variants_of(campaign_id):
    return by_created(
        [v for v in db.variants.values() if v["campaign_id"] == campaign_id]
    )


def partners_of(campaign_id):
    return by_created(
        [p for p in db.partners.values() if p["campaign_id"] == campaign_id]
    )


def activations_of(campaign_id):
    return by_created(
        [a for a in db.activations.values() if a["campaign_id"] == campaign_id]
    )


def actions_of_campaign(campaign_id):
    """Action records are campaign-scoped through their supporter."""
    out = []
    for record in db.action_records.values():
        sup = db.supporters.get(record["supporter_id"])
        if sup is not None and sup["campaign_id"] == campaign_id:
            out.append(record)
    return by_created(out)


def actions_of_supporter(supporter_id):
    return by_created(
        [a for a in db.action_records.values() if a["supporter_id"] == supporter_id]
    )


def meetings_of(campaign_id):
    return by_created(
        [m for m in db.meetings.values() if m["campaign_id"] == campaign_id]
    )


def endorsements_of_variant(variant_id):
    return by_created(
        [e for e in db.endorsements.values() if e["message_variant_id"] == variant_id]
    )


def endorsements_of_partner(partner_id):
    return by_created(
        [e for e in db.endorsements.values() if e["partner_id"] == partner_id]
    )


def profiles_of_supporter(supporter_id):
    return by_created(
        [p for p in db.spokespersons.values() if p["supporter_id"] == supporter_id]
    )


def consent_events_of(supporter_id):
    rows = [e for e in db.consent_events.values() if e["supporter_id"] == supporter_id]
    return sorted(rows, key=lambda e: (e["created_at"], e["sequence_no"]))


# ---------------------------------------------------------------------------
# consent_state_resolution
# ---------------------------------------------------------------------------

CONSENT_FIELD = {
    "EMAIL": "email_consent_state",
    "SMS": "sms_consent_state",
    "PHONE": "phone_consent_state",
}


def consent_state(sup, channel):
    return sup[CONSENT_FIELD[channel]]


def resolve_consent(sup):
    """Recompute the three per-channel consent states plus the suppressed flag."""
    events = consent_events_of(sup["id"])
    changed = False
    for channel in CHANNELS:
        candidates = [e for e in events if e["channel"] in (channel, "ALL")]
        if not candidates:
            state = "NONE"
        else:
            winner = sorted(
                candidates, key=lambda e: (e["created_at"], e["sequence_no"])
            )[-1]
            state = "GRANTED" if winner["action"] == "GRANT" else "REVOKED"
        field = CONSENT_FIELD[channel]
        if sup.get(field) != state:
            sup[field] = state
            changed = True
    suppressed = all(sup[CONSENT_FIELD[c]] == "REVOKED" for c in CHANNELS)
    if sup.get("suppressed") != suppressed:
        sup["suppressed"] = suppressed
        changed = True
    if sup.get("consent_event_count") != len(events):
        sup["consent_event_count"] = len(events)
        changed = True
    if changed:
        touch(sup)
    return changed


# ---------------------------------------------------------------------------
# supporter_value_score
# ---------------------------------------------------------------------------


def _story_bonus(supporter_id):
    best = STORY_BONUS["NONE"]
    for profile in profiles_of_supporter(supporter_id):
        bonus = STORY_BONUS.get(profile["training_state"], D0)
        if bonus > best:
            best = bonus
    return best


def _decay_factor(action_created_at):
    delta = now_dt() - action_created_at
    age_days = int(math.floor(delta.total_seconds() / 86400.0))
    if age_days <= DECAY_FRESH_MAX_DAYS:
        return DECAY_FRESH_FACTOR
    if age_days <= DECAY_MID_MAX_DAYS:
        return DECAY_MID_FACTOR
    return DECAY_STALE_FACTOR


def engagement_score(sup):
    base = SOURCE_BONUS[sup["acquisition_source"]]
    for rec in actions_of_supporter(sup["id"]):
        if rec["status"] not in COUNTED_ACTION_STATES:
            continue
        base += CHANNEL_PRESSURE_WEIGHT[rec["channel"]] * _decay_factor(
            rec["created_at"]
        )
    base += _story_bonus(sup["id"])
    return r2(min(ENGAGEMENT_CAP, base))


def retention_score(sup):
    base = SOURCE_BONUS[sup["acquisition_source"]]
    thanked = 0
    for rec in actions_of_supporter(sup["id"]):
        if rec["status"] not in COUNTED_ACTION_STATES:
            continue
        base += CHANNEL_PRESSURE_WEIGHT[rec["channel"]]
        if rec["status"] == "THANKED":
            thanked += 1
    base += THANK_BONUS * thanked
    profile_ids = set(p["id"] for p in profiles_of_supporter(sup["id"]))
    if profile_ids:
        led = 0
        for meeting in db.meetings.values():
            if (
                meeting["status"] == "HELD"
                and meeting["lead_spokesperson_id"] in profile_ids
            ):
                led += 1
        base += MEETING_LEAD_BONUS * led
    base += _story_bonus(sup["id"])
    return r2(min(RETENTION_CAP, base))


def refresh_supporter_counters(sup, with_retention=True):
    """Recompute action_count / thanked_count / engagement (and retention)."""
    records = actions_of_supporter(sup["id"])
    action_count = len([r for r in records if r["status"] in COUNTED_ACTION_STATES])
    thanked_count = len([r for r in records if r["status"] == "THANKED"])
    changed = False
    if sup.get("action_count") != action_count:
        sup["action_count"] = action_count
        changed = True
    if sup.get("thanked_count") != thanked_count:
        sup["thanked_count"] = thanked_count
        changed = True
    new_engagement = engagement_score(sup)
    if sup.get("engagement_score") != new_engagement:
        sup["engagement_score"] = new_engagement
        changed = True
    if with_retention:
        new_retention = retention_score(sup)
        if sup.get("retention_score") != new_retention:
            sup["retention_score"] = new_retention
            changed = True
    if changed:
        touch(sup)
    return changed


# ---------------------------------------------------------------------------
# district_pressure_index
# ---------------------------------------------------------------------------


def refresh_legislator(leg):
    counted = [
        a
        for a in db.action_records.values()
        if a["legislator_id"] == leg["id"] and a["status"] in COUNTED_ACTION_STATES
    ]
    weighted = D0
    for rec in counted:
        weighted += CHANNEL_PRESSURE_WEIGHT[rec["channel"]] * dec(
            rec["pressure_multiplier"]
        )
    action_component = min(ACTION_PRESSURE_CAP, weighted * ACTION_PRESSURE_FACTOR)
    held = len(
        [
            m
            for m in db.meetings.values()
            if m["legislator_id"] == leg["id"] and m["status"] == "HELD"
        ]
    )
    meeting_component = min(MEETING_PRESSURE_CAP, MEETING_PRESSURE_CREDIT * held)
    bonus = STANCE_BONUS[leg["stance"]]
    score = r2(
        min(PRESSURE_SCORE_CEILING, action_component + meeting_component + bonus)
    )
    if score >= PRESSURE_TIER_PRIMARY_MIN:
        tier = "PRIMARY"
    elif score >= PRESSURE_TIER_SECONDARY_MIN:
        tier = "SECONDARY"
    else:
        tier = "MONITOR"
    changed = False
    if leg.get("meeting_held_count") != held:
        leg["meeting_held_count"] = held
        changed = True
    if leg.get("contact_pressure_score") != score:
        leg["contact_pressure_score"] = score
        changed = True
    if leg.get("priority_tier") != tier:
        leg["priority_tier"] = tier
        changed = True
    if leg.get("constituent_action_count") != len(counted):
        leg["constituent_action_count"] = len(counted)
        changed = True
    if changed:
        touch(leg)
    return changed


def refresh_legislators_of(campaign_id):
    for leg in legislators_of(campaign_id):
        refresh_legislator(leg)


# ---------------------------------------------------------------------------
# milestone status + milestone_multiplier_snapshot
# ---------------------------------------------------------------------------


def milestone_status(milestone):
    clock = now_dt()
    if clock >= milestone["window_end"]:
        return "PASSED"
    if clock >= milestone["window_start"]:
        return "IN_WINDOW"
    return "SCHEDULED"


def refresh_milestone_statuses(campaign_id=None):
    rows = (
        db.milestones.values()
        if campaign_id is None
        else milestones_of(campaign_id)
    )
    for milestone in rows:
        milestone["status"] = milestone_status(milestone)


def milestone_multiplier(campaign_id):
    clock = now_dt()
    containing = [
        m
        for m in milestones_of(campaign_id)
        if m["window_start"] <= clock < m["window_end"]
    ]
    if not containing:
        return DEFAULT_MULTIPLIER
    winner = sorted(
        containing,
        key=lambda m: (-dec(m["pressure_multiplier"]), m["created_at"], m["_seq"]),
    )[0]
    return dec(winner["pressure_multiplier"])


# ---------------------------------------------------------------------------
# legislator_match_selector
# ---------------------------------------------------------------------------


def select_legislator(campaign, sup):
    candidates = [
        l
        for l in legislators_of(campaign["id"])
        if l["district_code"] == sup["district_code"]
    ]
    if not candidates:
        return None
    target = campaign["target_chamber"]

    def chamber_rank(leg):
        if target == "BOTH":
            return 0 if leg["chamber"] == "HOUSE" else 1
        return 0 if leg["chamber"] == target else 1

    winner = sorted(
        candidates,
        key=lambda l: (
            chamber_rank(l),
            dec(l["contact_pressure_score"]),
            l["created_at"],
            l["_seq"],
        ),
    )[0]
    return winner


# ---------------------------------------------------------------------------
# endorsement_quorum + coalition_cost_share
# ---------------------------------------------------------------------------


def quorum_for(campaign_id):
    active = len([p for p in partners_of(campaign_id) if p["status"] == "ACTIVE"])
    return max(1, -((-active) // 2))


def refresh_variant_quorums(campaign_id):
    quorum = quorum_for(campaign_id)
    for variant in variants_of(campaign_id):
        if variant.get("required_endorsement_quorum") != quorum:
            variant["required_endorsement_quorum"] = quorum
            touch(variant)


def refresh_variant_endorsement_count(variant):
    count = len(
        [e for e in endorsements_of_variant(variant["id"]) if e["status"] == "ACTIVE"]
    )
    if variant.get("endorsement_count") != count:
        variant["endorsement_count"] = count
        touch(variant)
        return True
    return False


def refresh_partner_endorsement_count(partner):
    count = len(
        [e for e in endorsements_of_partner(partner["id"]) if e["status"] == "ACTIVE"]
    )
    if partner.get("active_endorsement_count") != count:
        partner["active_endorsement_count"] = count
        touch(partner)
        return True
    return False


def refresh_cost_share(campaign):
    actives = [p for p in partners_of(campaign["id"]) if p["status"] == "ACTIVE"]
    withdrawn = [p for p in partners_of(campaign["id"]) if p["status"] != "ACTIVE"]
    lines = {}
    total_weight = sum(p["share_weight"] for p in actives)
    funded = int(campaign["funded_total_cents"])
    if total_weight == 0:
        for partner in actives:
            lines[partner["id"]] = 0
        total = 0
    else:
        for partner in actives:
            lines[partner["id"]] = (funded * partner["share_weight"]) // total_weight
        remainder = funded - sum(lines.values())
        queue = sorted(
            actives, key=lambda p: (-p["share_weight"], p["created_at"], p["_seq"])
        )
        index = 0
        while remainder > 0 and queue:
            lines[queue[index % len(queue)]["id"]] += 1
            remainder -= 1
            index += 1
        total = sum(lines.values())
    for partner in actives:
        if partner.get("committed_cents") != lines[partner["id"]]:
            partner["committed_cents"] = lines[partner["id"]]
            touch(partner)
    for partner in withdrawn:
        if partner.get("committed_cents") != 0:
            partner["committed_cents"] = 0
            touch(partner)
    if campaign.get("committed_share_total_cents") != total:
        campaign["committed_share_total_cents"] = total
        touch(campaign)
    return total


# ---------------------------------------------------------------------------
# variant_test_metrics
# ---------------------------------------------------------------------------


def refresh_variant_metrics(variant):
    waves = [
        a
        for a in db.activations.values()
        if a["message_variant_id"] == variant["id"]
        and a["delivery_state"] in ("SENT", "PARTIAL")
    ]
    wave_ids = set(a["id"] for a in waves)
    realized = sum(int(a["realized_reach"] or 0) for a in waves)
    cost = sum(int(a["send_cost_cents"] or 0) for a in waves)
    attributed = len(
        [
            r
            for r in db.action_records.values()
            if r["activation_id"] in wave_ids
            and r["status"] in COUNTED_ACTION_STATES
        ]
    )
    if realized == 0:
        bps = 0
    else:
        bps = r0(Decimal(BPS_SCALE * attributed) / Decimal(realized))
    if attributed == 0:
        cpa = NO_ACTION_CPA_SENTINEL_CENTS
    else:
        cpa = cost // attributed
    changed = False
    for field, value in (
        ("realized_reach_total", realized),
        ("send_cost_total_cents", cost),
        ("attributed_action_count", attributed),
        ("response_rate_bps", bps),
        ("cost_per_action_cents", cpa),
    ):
        if variant.get(field) != value:
            variant[field] = value
            changed = True
    if changed:
        touch(variant)
    return changed


def refresh_variant_metrics_of(campaign_id):
    for variant in variants_of(campaign_id):
        refresh_variant_metrics(variant)


# ---------------------------------------------------------------------------
# segment_membership
# ---------------------------------------------------------------------------


def refresh_segment_membership(segment):
    members = []
    for sup in supporters_of(segment["campaign_id"]):
        if consent_state(sup, segment["rule_required_channel"]) != "GRANTED":
            continue
        if sup["suppressed"]:
            continue
        if (
            segment["rule_district_codes"]
            and sup["district_code"] not in segment["rule_district_codes"]
        ):
            continue
        if dec(sup["engagement_score"]) < dec(segment["rule_min_engagement_score"]):
            continue
        if (
            segment["rule_sources"]
            and sup["acquisition_source"] not in segment["rule_sources"]
        ):
            continue
        members.append(sup["id"])
    changed = members != segment.get("member_supporter_ids")
    segment["member_supporter_ids"] = members
    segment["member_count"] = len(members)
    if changed:
        touch(segment)
    return changed


def refresh_segment_activation_count(segment):
    count = len(
        [
            a
            for a in db.activations.values()
            if a["segment_id"] == segment["id"]
            and a["delivery_state"] in ("SCHEDULED", "SENDING")
        ]
    )
    if segment.get("active_activation_count") != count:
        segment["active_activation_count"] = count
        touch(segment)
        return True
    return False


# ---------------------------------------------------------------------------
# activation_reach (projected variant) and the touch reservation ledger
# ---------------------------------------------------------------------------


def eligible_targets(activation, segment):
    out = []
    for supporter_id in segment["member_supporter_ids"]:
        sup = db.supporters.get(supporter_id)
        if sup is None:
            continue
        if consent_state(sup, activation["channel"]) != "GRANTED":
            continue
        if sup["suppressed"]:
            continue
        if (
            int(sup["touches_consumed"]) + int(sup["touches_reserved"])
        ) >= int(activation["effective_touch_cap"]):
            continue
        out.append(supporter_id)
    return out


def take_reservations(supporter_ids):
    for supporter_id in supporter_ids:
        sup = db.supporters.get(supporter_id)
        if sup is not None:
            sup["touches_reserved"] = int(sup["touches_reserved"]) + 1


def release_reservations(supporter_ids):
    for supporter_id in supporter_ids:
        sup = db.supporters.get(supporter_id)
        if sup is not None:
            sup["touches_reserved"] = max(0, int(sup["touches_reserved"]) - 1)


def recompute_scheduled_reach(campaign_id):
    """Re-derive projected reach and reservations for every SCHEDULED wave.

    All existing reservations of the affected waves are released first and then
    retaken in created_at order, so the ledger stays deterministic and the
    earliest wave keeps first claim on a supporter's headroom.
    """
    waves = [
        a
        for a in activations_of(campaign_id)
        if a["delivery_state"] == "SCHEDULED"
    ]
    if not waves:
        return
    snapshot = {
        s["id"]: int(s["touches_reserved"]) for s in db.supporters.values()
    }
    for wave in waves:
        release_reservations(wave["target_supporter_ids"])
    for wave in waves:
        segment = db.segments.get(wave["segment_id"])
        targets = eligible_targets(wave, segment) if segment else []
        changed = targets != wave["target_supporter_ids"]
        wave["target_supporter_ids"] = targets
        wave["projected_reach"] = len(targets)
        take_reservations(targets)
        if changed:
            touch(wave)
    for supporter_id, before in snapshot.items():
        sup = db.supporters.get(supporter_id)
        if sup is not None and int(sup["touches_reserved"]) != before:
            touch(sup)


def windows_overlap_closed_halfopen(closed_start, closed_end, open_start, open_end):
    """[closed_start, closed_end] intersects [open_start, open_end)."""
    return closed_start < open_end and open_start <= closed_end


def intersects_blackout(activation):
    for milestone in milestones_of(activation["campaign_id"]):
        if milestone["kind"] != "RECESS":
            continue
        if windows_overlap_closed_halfopen(
            activation["window_start"],
            activation["window_end"],
            milestone["window_start"],
            milestone["window_end"],
        ):
            return True
    return False


def revalidate_activation(activation):
    """System-triggered PENDING/CLEARED -> BLOCKED edge."""
    if activation["delivery_state"] != "SCHEDULED":
        return False
    if activation["approval_state"] not in ("PENDING", "CLEARED"):
        return False
    variant = db.variants.get(activation["message_variant_id"])
    blocked = False
    if int(activation["projected_reach"] or 0) < int(activation["min_viable_reach"]):
        blocked = True
    elif variant is None or variant["status"] != "LOCKED":
        blocked = True
    elif intersects_blackout(activation):
        blocked = True
    if blocked:
        activation["approval_state"] = "BLOCKED"
        touch(activation)
        return True
    return False


def revalidate_activations_of(campaign_id):
    for activation in activations_of(campaign_id):
        revalidate_activation(activation)


# ---------------------------------------------------------------------------
# campaign_posture -- always the last hop
# ---------------------------------------------------------------------------


def refresh_posture(campaign):
    blocked = len(
        [
            a
            for a in activations_of(campaign["id"])
            if a["approval_state"] == "BLOCKED"
        ]
    )
    opposed = len(
        [
            l
            for l in legislators_of(campaign["id"])
            if l["priority_tier"] == "PRIMARY"
            and l["stance"] in ("LEAN_OPPOSE", "OPPOSE")
        ]
    )
    if campaign["status"] == "CLOSED":
        posture = "FROZEN"
    elif campaign["posture_override"] == "FORCE_FROZEN":
        posture = "FROZEN"
    elif campaign["posture_override"] == "FORCE_OPEN":
        posture = "OPEN"
    elif blocked >= POSTURE_FROZEN_BLOCKED_MIN:
        posture = "FROZEN"
    elif (
        blocked >= POSTURE_RESTRICTED_BLOCKED_MIN
        or opposed >= POSTURE_RESTRICTED_OPPOSED_MIN
    ):
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    counted = [
        r
        for r in actions_of_campaign(campaign["id"])
        if r["status"] in COUNTED_ACTION_STATES
    ]
    total_actions = len(counted)
    distinct = len(set(r["supporter_id"] for r in counted))
    changed = False
    for field, value in (
        ("blocked_activation_count", blocked),
        ("opposed_priority_legislator_count", opposed),
        ("posture", posture),
        ("total_actions_logged", total_actions),
        ("distinct_acting_supporter_count", distinct),
    ):
        if campaign.get(field) != value:
            campaign[field] = value
            changed = True
    if changed:
        touch(campaign)
    return changed


# ---------------------------------------------------------------------------
# Cascade driver
# ---------------------------------------------------------------------------


def cascade(
    campaign,
    segments=False,
    reach=False,
    revalidate=False,
    legislators=False,
    variant_metrics=False,
):
    """Run the standard cascade tail for a campaign-scoped mutation.

    campaign_posture is always the final hop and is never re-entered.
    """
    campaign_id = campaign["id"]
    if segments:
        for segment in segments_of(campaign_id):
            refresh_segment_membership(segment)
    if reach:
        recompute_scheduled_reach(campaign_id)
    if revalidate:
        revalidate_activations_of(campaign_id)
    if legislators:
        refresh_legislators_of(campaign_id)
    if variant_metrics:
        refresh_variant_metrics_of(campaign_id)
    for segment in segments_of(campaign_id):
        refresh_segment_activation_count(segment)
    refresh_posture(campaign)


# ---------------------------------------------------------------------------
# campaign_outcome_analysis
# ---------------------------------------------------------------------------


def outcome_report(campaign):
    supporters = supporters_of(campaign["id"])
    records = actions_of_campaign(campaign["id"])
    counted = [r for r in records if r["status"] in COUNTED_ACTION_STATES]
    action_total = len(counted)
    thanked_total = len([r for r in records if r["status"] == "THANKED"])
    if action_total == 0:
        bps = 0
    else:
        bps = r0(Decimal(BPS_SCALE * thanked_total) / Decimal(action_total))
    primary_flip = len(
        [
            l
            for l in legislators_of(campaign["id"])
            if l["priority_tier"] == "PRIMARY"
            and l["stance"] in ("SUPPORT", "LEAN_SUPPORT")
        ]
    )
    retained = len(
        [s for s in supporters if dec(s["retention_score"]) >= RETENTION_COHORT_MIN]
    )
    reservation_total = sum(int(s["touches_reserved"]) for s in supporters)
    open_wave_total = sum(
        int(a["projected_reach"] or 0)
        for a in activations_of(campaign["id"])
        if a["delivery_state"] in ("SCHEDULED", "SENDING")
    )
    committed = int(campaign["committed_share_total_cents"])
    funded = int(campaign["funded_total_cents"])
    return {
        "supporter_total": len(supporters),
        "consented_reachable_total": len(
            [s for s in supporters if not s["suppressed"]]
        ),
        "action_total": action_total,
        "thanked_total": thanked_total,
        "thank_loop_closure_bps": bps,
        "primary_flip_count": primary_flip,
        "retained_supporter_count": retained,
        "committed_share_total_cents": committed,
        "funded_total_cents": funded,
        "coalition_funding_balanced": committed == funded,
        "touch_reservation_total": reservation_total,
        "open_wave_projected_reach_total": open_wave_total,
        "touch_ledger_balanced": reservation_total == open_wave_total,
    }
