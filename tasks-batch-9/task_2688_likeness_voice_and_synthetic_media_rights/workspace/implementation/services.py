"""Derived state, the append-only ledger, and every multi-hop cascade."""

from decimal import Decimal

import calc
from core import (
    by_created_asc, db, dec, iso, new_id, now, round_half_up, touch,
)


# ------------------------------------------------------------------- navigation

def grant_of(row):
    return db.consent_grants.get(row.get("consent_grant_id"))


def replica_of_performance(performance):
    return db.digital_replicas.get(performance["digital_replica_id"])


def grant_of_performance(performance):
    replica = replica_of_performance(performance)
    return grant_of(replica) if replica else None


def talent_of_performance(performance):
    replica = replica_of_performance(performance)
    if replica is None:
        return None
    return db.talents.get(replica["talent_id"])


def performance_of_license(license_row):
    return db.generated_performances.get(license_row["generated_performance_id"])


def replica_of_license(license_row):
    performance = performance_of_license(license_row)
    return replica_of_performance(performance) if performance else None


def talent_of_license(license_row):
    replica = replica_of_license(license_row)
    if replica is None:
        return None
    return db.talents.get(replica["talent_id"])


def grant_of_license(license_row):
    replica = replica_of_license(license_row)
    return grant_of(replica) if replica else None


def licenses_of_talent(talent_id):
    out = []
    for lic in db.usage_licenses.values():
        replica = replica_of_license(lic)
        if replica is not None and replica["talent_id"] == talent_id:
            out.append(lic)
    return out


def licenses_of_replica(replica_id):
    out = []
    for lic in db.usage_licenses.values():
        performance = performance_of_license(lic)
        if performance is not None and performance["digital_replica_id"] == replica_id:
            out.append(lic)
    return out


def performances_of_replica(replica_id):
    return [p for p in db.generated_performances.values()
            if p["digital_replica_id"] == replica_id]


def verified_authority(talent_id):
    rows = [a for a in db.estate_authorities.values()
            if a["talent_id"] == talent_id and a["status"] == "VERIFIED"]
    rows = by_created_asc(rows)
    return rows[0] if rows else None


# --------------------------------------------------------------- derived talent

OPEN_LICENSE_STATUSES = ("ISSUED", "LIVE", "REMOVAL_PENDING")


def compute_posture(talent_id, open_removal_count):
    for case in db.infringement_cases.values():
        if case["talent_id"] == talent_id and case["status"] == "LEGAL_ESCALATED":
            return "FROZEN"
    if open_removal_count > 0:
        return "RESTRICTED"
    for grant in db.consent_grants.values():
        if grant["talent_id"] == talent_id and grant["status"] == "SUSPENDED":
            return "RESTRICTED"
    return "CLEAR"


def recompute_talent(talent):
    """Recompute both counters, the lifetime roll-up and the posture from
    scratch.  Bumps the talent's version only when something moved."""
    if talent is None:
        return
    open_removal = len([lic for lic in licenses_of_talent(talent["id"])
                        if lic["distribution_status"] == "REMOVAL_PENDING"])
    holds = len([a for a in db.biometric_assets.values()
                 if a["talent_id"] == talent["id"] and a["status"] == "LEGAL_HOLD"])
    lifetime = sum(int(e["amount_cents"]) for e in db.compensation_entries.values()
                   if e["talent_id"] == talent["id"])
    posture = compute_posture(talent["id"], open_removal)
    changed = (
        talent["open_removal_obligation_count"] != open_removal
        or talent["legal_hold_asset_count"] != holds
        or talent["lifetime_compensation_cents"] != lifetime
        or talent["rights_posture"] != posture
    )
    talent["open_removal_obligation_count"] = max(0, open_removal)
    talent["legal_hold_asset_count"] = max(0, holds)
    talent["lifetime_compensation_cents"] = lifetime
    talent["rights_posture"] = posture
    if changed:
        touch(talent)


def recompute_grant_total(grant):
    if grant is None:
        return
    total = sum(int(e["amount_cents"]) for e in db.compensation_entries.values()
                if e["consent_grant_id"] == grant["id"])
    grant["total_compensation_cents"] = total


def recompute_replica_open_count(replica):
    if replica is None:
        return
    count = len([lic for lic in licenses_of_replica(replica["id"])
                 if lic["distribution_status"] in OPEN_LICENSE_STATUSES])
    if replica["open_license_count"] != count:
        replica["open_license_count"] = count
        touch(replica)


# ----------------------------------------------------------------- the ledger

def append_entry(grant, entry_type, amount_cents, performance_id=None,
                 license_id=None, reverses=None, memo=""):
    amount = int(amount_cents)
    if entry_type == "REVERSAL" and reverses is not None:
        talent_share = -int(reverses["talent_share_cents"])
        agency_share = -int(reverses["agency_share_cents"])
        admin_share = -int(reverses["administrator_share_cents"])
    else:
        talent_share = int(round_half_up(dec(amount) * dec(grant["talent_share_pct"])))
        agency_share = int(round_half_up(dec(amount) * dec(grant["agency_share_pct"])))
        admin_share = int(round_half_up(dec(amount) * dec(grant["administrator_share_pct"])))
        remainder = amount - (talent_share + agency_share + admin_share)
        talent_share += remainder
    stamp = now()
    entry = {
        "id": new_id(),
        "created_at": stamp,
        "talent_id": grant["talent_id"],
        "consent_grant_id": grant["id"],
        "generated_performance_id": performance_id,
        "usage_license_id": license_id,
        "reverses_entry_id": reverses["id"] if reverses is not None else None,
        "entry_type": entry_type,
        "amount_cents": amount,
        "talent_share_cents": talent_share,
        "agency_share_cents": agency_share,
        "administrator_share_cents": admin_share,
        "memo": memo,
        "posted_at": stamp,
        "_seq": db.next_seq(),
    }
    db.compensation_entries[entry["id"]] = entry
    recompute_grant_total(grant)
    talent = db.talents.get(grant["talent_id"])
    if talent is not None:
        talent["lifetime_compensation_cents"] = sum(
            int(e["amount_cents"]) for e in db.compensation_entries.values()
            if e["talent_id"] == talent["id"]
        )
    return entry


def reverse_live_provisional(performance, grant, memo):
    """Reverse the live PER_USE_PROVISIONAL accrual, if any."""
    entry_id = performance.get("_live_provisional_entry_id")
    reversed_entry = db.compensation_entries.get(entry_id) if entry_id else None
    if reversed_entry is None or int(performance.get("provisional_compensation_cents") or 0) <= 0:
        performance["provisional_compensation_cents"] = 0
        performance["_live_provisional_entry_id"] = None
        return None
    entry = append_entry(
        grant,
        "REVERSAL",
        -int(reversed_entry["amount_cents"]),
        performance_id=performance["id"],
        reverses=reversed_entry,
        memo=memo,
    )
    performance["provisional_compensation_cents"] = 0
    performance["_live_provisional_entry_id"] = None
    return entry


def post_provisional(performance, grant, amount, memo):
    entry = append_entry(
        grant,
        "PER_USE_PROVISIONAL",
        amount,
        performance_id=performance["id"],
        memo=memo,
    )
    performance["provisional_compensation_cents"] = int(amount)
    performance["_live_provisional_entry_id"] = entry["id"]
    return entry


# ------------------------------------------------------------- shared cascades

def recompute_asset_deadlines(grant):
    """Recompute retention_until (and purge_due_at where scheduled) for every
    non-purged asset of a grant whose effective end just moved.  Returns the
    assets actually changed."""
    profile = calc.profile_for(db.talents[grant["talent_id"]]["domicile_state_code"])
    if profile is None:
        return []
    changed = []
    candidates = [a for a in db.biometric_assets.values()
                  if a["consent_grant_id"] == grant["id"]
                  and a["status"] in ("STORED", "PURGE_SCHEDULED", "LEGAL_HOLD")]
    for asset in by_created_asc(candidates):
        deadline = calc.biometric_retention_deadline(asset["created_at"], grant, profile)
        moved = False
        if asset["retention_until"] != deadline:
            asset["retention_until"] = deadline
            moved = True
        if asset["status"] == "PURGE_SCHEDULED":
            due = calc.purge_due_from(deadline)
            if asset["purge_due_at"] != due:
                asset["purge_due_at"] = due
                moved = True
        if moved:
            touch(asset)
            changed.append(asset)
    return changed


def quarantine_replicas_of_grant(grant, reason):
    changed = []
    candidates = [r for r in db.digital_replicas.values()
                  if r["consent_grant_id"] == grant["id"]
                  and r["status"] in ("BUILT", "APPROVED_FOR_USE")]
    for replica in by_created_asc(candidates):
        replica["held_from_status"] = replica["status"]
        replica["status"] = "QUARANTINED"
        replica["quarantine_reason"] = reason
        touch(replica)
        changed.append(replica)
    return changed


def withdraw_performances_of_replicas(replicas, memo):
    changed = []
    candidates = []
    for replica in replicas:
        for performance in performances_of_replica(replica["id"]):
            if performance["review_status"] in ("SUBMITTED", "REVISION_REQUESTED", "APPROVED"):
                candidates.append(performance)
    for performance in by_created_asc(candidates):
        performance["review_status"] = "WITHDRAWN"
        grant = grant_of_performance(performance)
        reverse_live_provisional(performance, grant, memo)
        touch(performance)
        changed.append(performance)
    return changed


def open_removal_obligations(performances, reason):
    changed = []
    candidates = []
    for performance in performances:
        for lic in db.usage_licenses.values():
            if lic["generated_performance_id"] == performance["id"] and \
                    lic["distribution_status"] in ("ISSUED", "LIVE"):
                candidates.append(lic)
    for lic in by_created_asc(candidates):
        talent = talent_of_license(lic)
        profile = calc.profile_for(talent["domicile_state_code"]) if talent else None
        lic["distribution_status"] = "REMOVAL_PENDING"
        lic["removal_reason"] = reason
        if profile is not None:
            lic["removal_deadline"] = calc.license_removal_deadline(profile)
        touch(lic)
        changed.append(lic)
    for replica in {id(r): r for r in
                    [replica_of_license(l) for l in changed] if r is not None}.values():
        recompute_replica_open_count(replica)
    return changed


# ------------------------------------------------------------ specific cascades

def death_record_cascade(talent):
    """Four hops: talent, its own TALENT-granted ACTIVE consents, the replicas
    beneath them, and finally the posture."""
    grants = [gr for gr in db.consent_grants.values()
              if gr["talent_id"] == talent["id"]
              and gr["status"] == "ACTIVE"
              and gr["grantor_kind"] == "TALENT"]
    suspended = []
    for grant in by_created_asc(grants):
        grant["status"] = "SUSPENDED"
        grant["suspension_reason"] = "DEATH_PENDING_ESTATE"
        touch(grant)
        suspended.append(grant)
    if suspended:
        replicas = []
        candidates = [r for r in db.digital_replicas.values()
                      if r["consent_grant_id"] in [gr["id"] for gr in suspended]
                      and r["status"] in ("BUILT", "APPROVED_FOR_USE")]
        for replica in by_created_asc(candidates):
            replica["held_from_status"] = replica["status"]
            replica["status"] = "QUARANTINED"
            replica["quarantine_reason"] = "ESTATE_PENDING"
            touch(replica)
            replicas.append(replica)
    recompute_talent(talent)


def release_estate_pending(talent, grant=None):
    """Release what a death record suspended.  When grant is given only that
    grant's replicas are released (consent reinstatement)."""
    if grant is None:
        grants = [gr for gr in db.consent_grants.values()
                  if gr["talent_id"] == talent["id"]
                  and gr["status"] == "SUSPENDED"
                  and gr["suspension_reason"] == "DEATH_PENDING_ESTATE"]
        for row in by_created_asc(grants):
            row["status"] = "ACTIVE"
            row["suspension_reason"] = None
            touch(row)
        replicas = [r for r in db.digital_replicas.values()
                    if r["talent_id"] == talent["id"]
                    and r["status"] == "QUARANTINED"
                    and r["quarantine_reason"] == "ESTATE_PENDING"]
    else:
        replicas = [r for r in db.digital_replicas.values()
                    if r["consent_grant_id"] == grant["id"]
                    and r["status"] == "QUARANTINED"
                    and r["quarantine_reason"] == "ESTATE_PENDING"]
    for replica in by_created_asc(replicas):
        replica["status"] = replica["held_from_status"] or "BUILT"
        replica["quarantine_reason"] = None
        replica["held_from_status"] = None
        touch(replica)
    recompute_talent(talent)


def revoke_cascade(grant, talent):
    """Five hops beneath a revoked ACTIVE or SUSPENDED grant."""
    recompute_asset_deadlines(grant)
    replicas = quarantine_replicas_of_grant(grant, "CONSENT_REVOKED")
    performances = []
    if replicas:
        performances = withdraw_performances_of_replicas(
            replicas, "Provisional accrual reversed: consent grant revoked")
    if performances:
        open_removal_obligations(performances, "CONSENT_REVOKED")
    recompute_talent(talent)


def escalation_cascade(case, talent):
    assets = [a for a in db.biometric_assets.values()
              if a["talent_id"] == talent["id"]
              and a["status"] in ("STORED", "PURGE_SCHEDULED")]
    held = []
    for asset in by_created_asc(assets):
        asset["held_from_status"] = asset["status"]
        asset["status"] = "LEGAL_HOLD"
        touch(asset)
        held.append(asset)
    case["legal_hold_applied_count"] = len(held)
    replicas = []
    if held:
        held_ids = set(a["id"] for a in held)
        candidates = [r for r in db.digital_replicas.values()
                      if r["talent_id"] == talent["id"]
                      and r["status"] in ("BUILT", "APPROVED_FOR_USE")
                      and held_ids.intersection(set(r["source_asset_ids"]))]
        for replica in by_created_asc(candidates):
            replica["held_from_status"] = replica["status"]
            replica["status"] = "QUARANTINED"
            replica["quarantine_reason"] = "SOURCE_LEGAL_HOLD"
            touch(replica)
            replicas.append(replica)
    performances = []
    if replicas:
        performances = withdraw_performances_of_replicas(
            replicas, "Provisional accrual reversed: replica quarantined by legal escalation")
    if performances:
        open_removal_obligations(performances, "REPLICA_QUARANTINED")
    recompute_talent(talent)


def release_legal_holds(case, talent):
    """Escalated closure releases what the escalation impounded, but only when
    no other case of this talent remains LEGAL_ESCALATED."""
    for other in db.infringement_cases.values():
        if other["id"] != case["id"] and other["talent_id"] == talent["id"] \
                and other["status"] == "LEGAL_ESCALATED":
            recompute_talent(talent)
            return
    assets = [a for a in db.biometric_assets.values()
              if a["talent_id"] == talent["id"] and a["status"] == "LEGAL_HOLD"]
    for asset in by_created_asc(assets):
        asset["status"] = asset["held_from_status"] or "STORED"
        asset["held_from_status"] = None
        touch(asset)
    replicas = [r for r in db.digital_replicas.values()
                if r["talent_id"] == talent["id"]
                and r["status"] == "QUARANTINED"
                and r["quarantine_reason"] == "SOURCE_LEGAL_HOLD"]
    for replica in by_created_asc(replicas):
        replica["status"] = replica["held_from_status"] or "BUILT"
        replica["quarantine_reason"] = None
        replica["held_from_status"] = None
        touch(replica)
    recompute_talent(talent)


# --------------------------------------------------------------- case creation

def create_case(talent, domicile_profile, detected_profile, fields):
    posture_before = talent["rights_posture"]
    severity = calc.infringement_severity_score(
        fields["match_confidence"], fields["detected_view_count"], posture_before)
    rights_until, enforceable = calc.use_state_enforceability(talent, detected_profile)
    stamp = now()
    case = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "talent_id": talent["id"],
        "matched_usage_license_id": fields.get("matched_usage_license_id"),
        "detection_source": fields["detection_source"],
        "suspect_url": fields["suspect_url"],
        "detected_channel": fields["detected_channel"],
        "detected_state_code": fields["detected_state_code"],
        "detected_view_count": int(fields["detected_view_count"]),
        "match_confidence": float(fields["match_confidence"]),
        "severity_score": float(severity),
        "use_state_rights_until": rights_until,
        "enforceable_under_use_state": enforceable,
        "status": "DETECTED",
        "triaged_by_user_id": None,
        "escalated_by_user_id": None,
        "closed_by_user_id": None,
        "takedown_issued_at": None,
        "legal_hold_applied_count": 0,
        "closure_outcome": None,
        "_seq": db.next_seq(),
    }
    db.infringement_cases[case["id"]] = case
    return case


# --------------------------------------------------------------- compliance sweep

def run_compliance_sweep():
    instant = now()
    report = {
        "sweep_id": new_id(),
        "run_at": instant,
        "expired_consent_count": 0,
        "retired_replica_count": 0,
        "expired_license_count": 0,
        "removal_pending_count": 0,
        "overdue_removal_count": 0,
        "auto_rejected_performance_count": 0,
        "purge_scheduled_count": 0,
        "purged_count": 0,
        "opened_case_count": 0,
    }
    affected_talents = {}

    def mark_talent(talent):
        if talent is not None:
            affected_talents[talent["id"]] = talent

    # Phase one: retire expired consent.
    grants = [gr for gr in db.consent_grants.values()
              if gr["status"] in ("ACTIVE", "SUSPENDED")
              and gr["effective_until"] <= instant]
    for grant in by_created_asc(grants):
        grant["status"] = "EXPIRED"
        grant["effective_end_actual"] = grant["effective_until"]
        grant["suspension_reason"] = None
        touch(grant)
        report["expired_consent_count"] += 1
        recompute_asset_deadlines(grant)
        replicas = [r for r in db.digital_replicas.values()
                    if r["consent_grant_id"] == grant["id"]
                    and r["status"] in ("BUILT", "APPROVED_FOR_USE")]
        for replica in by_created_asc(replicas):
            replica["status"] = "RETIRED"
            replica["held_from_status"] = None
            replica["quarantine_reason"] = None
            touch(replica)
            report["retired_replica_count"] += 1
        mark_talent(db.talents.get(grant["talent_id"]))

    # Phase two: open removal obligations on expired licenses.
    licenses = [lic for lic in db.usage_licenses.values()
                if lic["distribution_status"] in ("ISSUED", "LIVE")
                and lic["distribution_end"] < instant]
    touched_replicas = {}
    for lic in by_created_asc(licenses):
        talent = talent_of_license(lic)
        profile = calc.profile_for(talent["domicile_state_code"]) if talent else None
        lic["distribution_status"] = "REMOVAL_PENDING"
        lic["removal_reason"] = "TERM_EXPIRED"
        if profile is not None:
            lic["removal_deadline"] = calc.license_removal_deadline(profile)
        touch(lic)
        report["expired_license_count"] += 1
        report["removal_pending_count"] += 1
        replica = replica_of_license(lic)
        if replica is not None:
            touched_replicas[replica["id"]] = replica
        mark_talent(talent)
    for replica in touched_replicas.values():
        recompute_replica_open_count(replica)

    # Phase three: punish overdue removals.
    overdue = [lic for lic in db.usage_licenses.values()
               if lic["distribution_status"] == "REMOVAL_PENDING"
               and lic["removal_deadline"] is not None
               and lic["removal_deadline"] < instant
               and lic["removal_confirmed_at"] is None
               and lic["compliance_status"] != "NON_COMPLIANT"]
    for lic in by_created_asc(overdue):
        lic["compliance_status"] = "NON_COMPLIANT"
        touch(lic)
        report["overdue_removal_count"] += 1
        talent = talent_of_license(lic)
        mark_talent(talent)
        if talent is None:
            continue
        domicile = calc.profile_for(talent["domicile_state_code"])
        if domicile is None:
            continue
        create_case(talent, domicile, domicile, {
            "matched_usage_license_id": lic["id"],
            "detection_source": "SWEEP",
            "suspect_url": lic.get("distribution_reference"),
            "detected_channel": lic["channel"],
            "detected_state_code": talent["domicile_state_code"],
            "detected_view_count": 0,
            "match_confidence": Decimal("1.000"),
        })
        report["opened_case_count"] += 1

    # Phase four: close lapsed reviews.
    lapsed = [p for p in db.generated_performances.values()
              if p["review_status"] == "SUBMITTED"
              and p["review_deadline"] is not None
              and p["review_deadline"] <= instant]
    for performance in by_created_asc(lapsed):
        performance["review_status"] = "REJECTED"
        performance["rejection_reason"] = "REVIEW_WINDOW_LAPSED"
        grant = grant_of_performance(performance)
        reverse_live_provisional(
            performance, grant,
            "Provisional accrual reversed: review window lapsed")
        touch(performance)
        report["auto_rejected_performance_count"] += 1
        mark_talent(talent_of_performance(performance))

    # Phase five: discharge retention in two ordered steps.
    schedulable = [a for a in db.biometric_assets.values()
                   if a["status"] == "STORED"
                   and a["retention_until"] is not None
                   and a["retention_until"] <= instant]
    for asset in by_created_asc(schedulable):
        asset["status"] = "PURGE_SCHEDULED"
        asset["purge_due_at"] = calc.purge_due_from(asset["retention_until"])
        touch(asset)
        report["purge_scheduled_count"] += 1
        mark_talent(db.talents.get(asset["talent_id"]))
    purgeable = [a for a in db.biometric_assets.values()
                 if a["status"] == "PURGE_SCHEDULED"
                 and a["purge_due_at"] is not None
                 and a["purge_due_at"] <= instant]
    for asset in by_created_asc(purgeable):
        asset["status"] = "PURGED"
        asset["payload_digest"] = None
        asset["purged_at"] = instant
        touch(asset)
        report["purged_count"] += 1
        mark_talent(db.talents.get(asset["talent_id"]))

    for talent in list(affected_talents.values()):
        recompute_talent(talent)
    for grant in db.consent_grants.values():
        recompute_grant_total(grant)

    report["run_at"] = iso(instant)
    return report
