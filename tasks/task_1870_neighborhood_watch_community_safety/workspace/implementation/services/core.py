"""Core business logic: posture recompute, participation score, cascades, helpers."""

import math
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import errors


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return db.get_clock()


def touch(record: dict):
    """Refresh updated_at and increment version on a record."""
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 1) + 1


def stamp_new(record: dict):
    """Set id, created_at, updated_at, version on a brand-new record."""
    record["id"] = new_id()
    record["created_at"] = db.now_iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1


# ---------------------------------------------------------------------------
# Lazy DataShareAgreement expiry sweep
# ---------------------------------------------------------------------------

def sweep_agreement_expiry(group_id: str = None):
    """Check ACTIVE agreements whose expires_at <= clock; transition to EXPIRED."""
    clock = db.get_clock()
    for ag in list(db.data_share_agreements.values()):
        if ag["agreement_status"] != "ACTIVE":
            continue
        if group_id and ag["watch_group_id"] != group_id:
            continue
        exp = db.parse_iso(ag["expires_at"])
        if clock >= exp:
            _revoke_agreement(ag, expired=True)


def _revoke_agreement(ag: dict, expired: bool = False):
    """Shared cascade for revoke and expire."""
    ag["agreement_status"] = "EXPIRED" if expired else "REVOKED"
    touch(ag)
    gid = ag["watch_group_id"]
    # Re-scope incident reports (they keep shared_with_liaison=True but reads denied)
    # Recompute heat under CORROBORATED_ONLY variant
    _recompute_all_block_heats(gid)


def revoke_agreement_by_id(agreement_id: str):
    ag = db.data_share_agreements.get(agreement_id)
    if not ag:
        raise errors.not_found("DataShareAgreement not found")
    if ag["agreement_status"] != "ACTIVE":
        raise errors.invalid_state("Agreement is not ACTIVE")
    _revoke_agreement(ag, expired=False)
    return ag


# ---------------------------------------------------------------------------
# Active agreement check
# ---------------------------------------------------------------------------

def has_active_agreement(group_id: str, scopes: set = None) -> bool:
    """Check if the group has an ACTIVE DataShareAgreement (optionally filtered by scope)."""
    sweep_agreement_expiry(group_id)
    for ag in db.data_share_agreements.values():
        if ag["watch_group_id"] != group_id:
            continue
        if ag["agreement_status"] != "ACTIVE":
            continue
        if scopes and ag["scope"] not in scopes:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# WatchGroup posture recompute
# ---------------------------------------------------------------------------

def recompute_posture(group_id: str):
    """Derive posture from first principles. Returns the group dict."""
    g = db.watch_groups.get(group_id)
    if not g:
        return None

    # If FROZEN, don't auto-recompute out of it — only unfreeze does that.
    if g["posture"] == "FROZEN":
        _recompute_participation(g)
        return g

    old_posture = g["posture"]
    new_posture = _derive_posture(g)
    changed = False
    if new_posture != old_posture:
        g["posture"] = new_posture
        changed = True
    # PRD §3.1/§2.4: one triggering mutation = one version increment on the
    # group, even when both posture and participation score change together.
    if _recompute_participation(g, bump=False):
        changed = True
    if changed:
        touch(g)
    return g


def _derive_posture(g: dict) -> str:
    gid = g["id"]
    cert = g["certification_status"]

    registered_blocks = [b for b in db.blocks.values()
                         if b["watch_group_id"] == gid and b["registration_status"] == "REGISTERED"]

    if not registered_blocks:
        return "DORMANT"

    # At least one REGISTERED block — at minimum FORMATION
    # Check captain coverage: every REGISTERED block must have exactly one ACTIVE captain
    all_covered = True
    for b in registered_blocks:
        active_captains = [ca for ca in db.captain_assignments.values()
                           if ca["block_id"] == b["id"] and ca["assignment_status"] == "ACTIVE"]
        if len(active_captains) != 1:
            all_covered = False
            break

    has_bias_training = any(
        ts for ts in db.training_sessions.values()
        if ts["watch_group_id"] == gid
        and ts["session_status"] == "COMPLETED"
        and ts["curriculum"] == "BIAS_AVOIDANCE"
    )

    if all_covered and has_bias_training and cert != "REVOKED":
        return "OPERATIONAL"

    # If was OPERATIONAL but lost captain coverage → DEGRADED
    if g["posture"] in ("OPERATIONAL", "DEGRADED") and not all_covered and cert != "REVOKED":
        return "DEGRADED"

    # If has registered blocks but doesn't meet OPERATIONAL criteria → FORMATION
    if cert != "REVOKED":
        return "FORMATION"

    # REVOKED — stay at current posture or default to FORMATION
    return g["posture"] if g["posture"] != "DORMANT" else "FORMATION"


# ---------------------------------------------------------------------------
# Participation score
# ---------------------------------------------------------------------------

def _recompute_participation(g: dict, bump: bool = True):
    gid = g["id"]
    posture = g["posture"]

    base = 10 * sum(1 for b in db.blocks.values()
                    if b["watch_group_id"] == gid and b["registration_status"] == "REGISTERED")
    member_term = 2 * sum(1 for m in db.members.values()
                          if m["watch_group_id"] == gid and m["membership_status"] == "ACTIVE")

    if posture in ("DORMANT", "FORMATION"):
        # CENSUS variant
        score = base + member_term
    else:
        # ACTIVITY variant
        meeting_term = 5 * sum(1 for mt in db.liaison_meetings.values()
                               if mt["watch_group_id"] == gid
                               and mt["meeting_status"] == "HELD"
                               and mt.get("quorum_met"))
        event_term = 8 * sum(1 for ev in db.community_events.values()
                             if ev["watch_group_id"] == gid and ev["event_status"] == "COMPLETED")
        incident_term = 3 * sum(1 for ir in db.incident_reports.values()
                                if _report_group(ir) == gid
                                and ir["review_status"] in ("CORROBORATED", "CLEARED"))
        score = base + member_term + meeting_term + event_term + incident_term

    if g["participation_score"] != score:
        g["participation_score"] = score
        if bump:
            touch(g)
        return True
    return False


def _report_group(report: dict) -> str:
    """Get the watch_group_id for an incident report via its block."""
    block = db.blocks.get(report["block_id"])
    return block["watch_group_id"] if block else None


# ---------------------------------------------------------------------------
# Block risk heat
# ---------------------------------------------------------------------------

def recompute_block_heat(block_id: str):
    """Recompute risk_heat_score for a block."""
    block = db.blocks.get(block_id)
    if not block:
        return

    gid = block["watch_group_id"]
    has_agreement = has_active_agreement(gid)
    clock = db.get_clock()

    heat = Decimal("0")
    latest_incident_at = None

    for r in db.incident_reports.values():
        if r["block_id"] != block_id:
            continue
        if r["review_status"] not in ("CORROBORATED", "CLEARED"):
            continue
        # CORROBORATED_ONLY variant: skip CLEARED reports when no active agreement
        if not has_agreement and r["review_status"] == "CLEARED":
            continue

        occurred = db.parse_iso(r["occurred_at"])
        age_days = (clock - occurred).days

        if age_days <= 30:
            bw = Decimal("1.0")
        elif age_days <= 60:
            bw = Decimal("0.5")
        elif age_days <= 90:
            bw = Decimal("0.25")
        else:
            bw = Decimal("0.0")

        term = (Decimal(str(r["severity"])) * bw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        heat += term

        # Track last_incident_at
        if latest_incident_at is None or r["occurred_at"] > latest_incident_at:
            latest_incident_at = r["occurred_at"]

    new_heat = float(heat)
    if block["risk_heat_score"] != new_heat or block.get("last_incident_at") != latest_incident_at:
        block["risk_heat_score"] = new_heat
        block["last_incident_at"] = latest_incident_at
        touch(block)


def _recompute_all_block_heats(group_id: str):
    """Recompute heat for every block in a group."""
    for b in db.blocks.values():
        if b["watch_group_id"] == group_id:
            recompute_block_heat(b["id"])


# ---------------------------------------------------------------------------
# Corroboration weight for a single report
# ---------------------------------------------------------------------------

def compute_corroboration_weight(report: dict):
    """Set corroboration_weight on a report based on bucket weight."""
    clock = db.get_clock()
    occurred = db.parse_iso(report["occurred_at"])
    age_days = (clock - occurred).days

    if age_days <= 30:
        bw = Decimal("1.0")
    elif age_days <= 60:
        bw = Decimal("0.5")
    elif age_days <= 90:
        bw = Decimal("0.25")
    else:
        bw = Decimal("0.0")

    weight = (Decimal(str(report["severity"])) * bw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    report["corroboration_weight"] = float(weight)


# ---------------------------------------------------------------------------
# Alert fanout
# ---------------------------------------------------------------------------

PHONE_TREE_RELAY = 2.5
FLYER_RATIO = 10


def compute_fanout(alert: dict) -> tuple:
    """Returns (recipient_count, printed_flyers)."""
    scope = alert["audience_scope"]
    gid = alert["watch_group_id"]

    if scope == "BLOCK":
        target = db.blocks.get(alert.get("target_block_id"))
        in_scope_blocks = [target] if target else []
    else:
        in_scope_blocks = [b for b in db.blocks.values()
                           if b["watch_group_id"] == gid and b["registration_status"] == "REGISTERED"]

    total_recipients = 0
    for blk in in_scope_blocks:
        m_sms = sum(1 for m in db.members.values()
                    if m.get("block_id") == blk["id"]
                    and m["membership_status"] == "ACTIVE"
                    and m["contact_channel"] == "SMS")
        m_email = sum(1 for m in db.members.values()
                      if m.get("block_id") == blk["id"]
                      and m["membership_status"] == "ACTIVE"
                      and m["contact_channel"] == "EMAIL")
        m_tree = sum(1 for m in db.members.values()
                     if m.get("block_id") == blk["id"]
                     and m["membership_status"] == "ACTIVE"
                     and m["contact_channel"] == "PHONE_TREE")
        raw = m_sms + m_email + m_tree * PHONE_TREE_RELAY
        total_recipients += math.ceil(raw)

    printed_flyers = math.ceil(total_recipients / FLYER_RATIO)
    return total_recipients, printed_flyers


# ---------------------------------------------------------------------------
# Ack posture
# ---------------------------------------------------------------------------

def recompute_ack_posture(alert: dict):
    rc = alert.get("recipient_count", 0)
    ac = alert.get("ack_count", 0)
    if ac == 0:
        alert["ack_posture"] = "UNTRACKED"
    elif rc > 0 and ac == rc:
        alert["ack_posture"] = "FULL"
    elif rc > 0 and ac >= (rc // 2) + 1:
        alert["ack_posture"] = "MAJORITY"
    else:
        alert["ack_posture"] = "PARTIAL"


# ---------------------------------------------------------------------------
# Certification points
# ---------------------------------------------------------------------------

def compute_certification_points(group_id: str) -> int:
    member_pts = min(25, sum(
        1 for m in db.members.values()
        if m["watch_group_id"] == group_id
        and m["membership_status"] == "ACTIVE"
        and m.get("bias_training_completed_at") is not None
    ))

    meeting_pts = min(25, 5 * sum(
        1 for mt in db.liaison_meetings.values()
        if mt["watch_group_id"] == group_id
        and mt["meeting_status"] == "HELD"
        and mt.get("quorum_met")
    ))

    has_nno_completed = any(
        ev for ev in db.community_events.values()
        if ev["watch_group_id"] == group_id
        and ev["event_kind"] == "NATIONAL_NIGHT_OUT"
        and ev["event_status"] == "COMPLETED"
    )
    has_any_completed = any(
        ev for ev in db.community_events.values()
        if ev["watch_group_id"] == group_id
        and ev["event_status"] == "COMPLETED"
    )
    event_pts = 20 if has_nno_completed else (10 if has_any_completed else 0)

    registered_blocks = [b for b in db.blocks.values()
                         if b["watch_group_id"] == group_id
                         and b["registration_status"] == "REGISTERED"]
    all_captained = all(
        len([ca for ca in db.captain_assignments.values()
             if ca["block_id"] == b["id"] and ca["assignment_status"] == "ACTIVE"]) == 1
        for b in registered_blocks
    ) if registered_blocks else False
    captain_pts = 15 if all_captained else 0

    sent_count = sum(1 for a in db.alerts.values()
                     if a["watch_group_id"] == group_id and a["distribution_status"] == "SENT")
    alert_pts = 15 if sent_count >= 3 else (5 if sent_count >= 1 else 0)

    return member_pts + meeting_pts + event_pts + captain_pts + alert_pts


# ---------------------------------------------------------------------------
# Quiet hours check
# ---------------------------------------------------------------------------

def is_quiet_hours(dt: datetime) -> bool:
    """Check if a datetime falls in the 22:00-07:00 quiet hours window (local = UTC for this system)."""
    hour = dt.hour
    return hour >= 22 or hour < 7


# ---------------------------------------------------------------------------
# Meeting quorum
# ---------------------------------------------------------------------------

QUORUM_FRACTION = 0.25
QUORUM_MIN = 2


def compute_quorum(group_id: str, attendee_count: int) -> bool:
    active_members = sum(1 for m in db.members.values()
                         if m["watch_group_id"] == group_id and m["membership_status"] == "ACTIVE")
    threshold = max(QUORUM_MIN, math.ceil(active_members * QUORUM_FRACTION))
    return attendee_count >= threshold


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------

def cascade_member_withdrawal(member: dict):
    """Relieve ACTIVE captain assignments for a member being withdrawn."""
    for ca in db.captain_assignments.values():
        if ca["member_id"] == member["id"] and ca["assignment_status"] == "ACTIVE":
            ca["assignment_status"] = "RELIEVED"
            ca["relieved_at"] = db.now_iso()
            touch(ca)


def cascade_member_suspension(member: dict):
    """Revoke ACTIVE captain assignments for a member being suspended."""
    for ca in db.captain_assignments.values():
        if ca["member_id"] == member["id"] and ca["assignment_status"] == "ACTIVE":
            ca["assignment_status"] = "REVOKED"
            ca["relieved_at"] = db.now_iso()
            touch(ca)


def cascade_block_deregistration(block: dict):
    """Withdraw all ACTIVE members on a deregistered block."""
    for m in db.members.values():
        if m.get("block_id") == block["id"] and m["membership_status"] == "ACTIVE":
            m["membership_status"] = "WITHDRAWN"
            touch(m)
            # Also relieve any ACTIVE captain assignments for this member
            cascade_member_withdrawal(m)
