"""Definitional recomputation and cascading side effects (PRD 2.9)."""

import calc
import db

LIVE_TRANSFER_STATES = ("TRANSFER_PROPOSED", "TRANSFER_ACCEPTED")
PANEL_HOLDING_STATES = ("ACTIVE", "TRANSFER_PROPOSED", "TRANSFER_ACCEPTED")


# --------------------------------------------------------------- panel counters
def sync_panel_size(physician):
    count = sum(1 for a in db.assignments.values()
                if a["physician_id"] == physician["id"] and a["status"] == "ACTIVE")
    if db.apply_fields(physician, panel_size=count):
        db.touch(physician)
    return count


def sync_total_assigned_members(agreement):
    physician_ids = {p["id"] for p in db.physicians.values()
                     if p["agreement_id"] == agreement["id"]}
    count = sum(1 for a in db.assignments.values()
                if a["status"] == "ACTIVE" and a["physician_id"] in physician_ids)
    if db.apply_fields(agreement, total_assigned_members=count):
        db.touch(agreement)
    return count


def sync_enrollee_assignment(enrollee, force_touch=False):
    active = [a for a in db.assignments_of_enrollee(enrollee["id"])
              if a["status"] == "ACTIVE"]
    physician_id = active[-1]["physician_id"] if active else None
    changed = db.apply_fields(enrollee, assigned_physician_id=physician_id)
    if changed or force_touch:
        db.touch(enrollee)


def close_panel_at_capacity(physician, agreement):
    if (physician["panel_size"] >= agreement["max_panel_size"]
            and physician["panel_status"] == "OPEN"):
        physician["panel_status"] = "CLOSED_TO_NEW"
        db.touch(physician)


def resolve_transfer_pending(physician):
    """TRANSFER_PENDING -> CLOSED_TO_NEW once no in-flight transfer remains."""
    if physician["panel_status"] != "TRANSFER_PENDING":
        return
    if physician["credential_status"] == "EXITED":
        return
    for assignment in db.assignments.values():
        if (assignment["physician_id"] == physician["id"]
                and assignment["status"] in LIVE_TRANSFER_STATES):
            return
    physician["panel_status"] = "CLOSED_TO_NEW"
    db.touch(physician)


def close_open_panels(agreement):
    """PRD 2.9 sideways cascade: posture left CURRENT -> close every OPEN panel."""
    for physician in db.physicians_of_agreement(agreement["id"]):
        if physician["panel_status"] == "OPEN":
            physician["panel_status"] = "CLOSED_TO_NEW"
            db.touch(physician)


# ------------------------------------------------------------------- posture
def sync_capitation_posture(agreement):
    previous = agreement["capitation_posture"]
    current = calc.capitation_posture(agreement)
    if current == previous:
        return False
    agreement["capitation_posture"] = current
    db.touch(agreement)
    if previous == "CURRENT" and current != "CURRENT":
        close_open_panels(agreement)
    return True


# ---------------------------------------------------------------- pool ledgers
def sync_pool_ledger(pool, force_touch=False):
    agreement = db.agreement_of_pool(pool)
    attachment = agreement["stop_loss_attachment_cents"] if agreement else 0
    paid_total = 0
    per_enrollee = {}
    for claim in db.claims.values():
        if claim["pool_id"] != pool["id"] or claim["status"] != "PAID":
            continue
        amount = claim["paid_cents"] or 0
        paid_total += amount
        per_enrollee[claim["enrollee_id"]] = per_enrollee.get(claim["enrollee_id"], 0) + amount
    eligible_count = sum(1 for total in per_enrollee.values() if total > attachment)
    recovered = 0
    for recovery in db.recoveries.values():
        if (recovery["pool_id"] == pool["id"]
                and recovery["status"] in ("APPROVED", "RECOVERED")):
            recovered += recovery["recovery_cents"]
    ratio, deficit = calc.pool_loss_ratio_and_deficit(paid_total, pool["funded_cents"])
    changed = db.apply_fields(
        pool,
        paid_claims_cents=paid_total,
        stop_loss_recovery_cents=recovered,
        stop_loss_eligible_enrollee_count=eligible_count,
        loss_ratio_bps=ratio,
        deficit_flag=deficit,
    )
    if changed or force_touch:
        db.touch(pool)


def sync_enrollee_paid_claims(enrollee, force_touch=False):
    total = 0
    for claim in db.claims.values():
        if claim["enrollee_id"] == enrollee["id"] and claim["status"] == "PAID":
            total += claim["paid_cents"] or 0
    changed = db.apply_fields(enrollee, cumulative_paid_claims_cents=total)
    if changed or force_touch:
        db.touch(enrollee)


def sync_accrued_capitation(agreement):
    file_ids = {f["id"] for f in db.files.values()
                if f["agreement_id"] == agreement["id"]}
    total = 0
    for remittance in db.remittances.values():
        if remittance["file_id"] in file_ids and remittance["status"] in ("RECONCILED",
                                                                         "POSTED"):
            total += (remittance["expected_capitation_cents"]
                      + remittance["retro_adjustment_cents"])
    if db.apply_fields(agreement, accrued_capitation_cents=total):
        db.touch(agreement)


# ----------------------------------------------------------------- enrollee pmpm
def derive_enrollee_components(agreement, enrollee, force_touch=False):
    gross, withhold, net = calc.member_pmpm_components(agreement, enrollee)
    changed = db.apply_fields(enrollee, gross_pmpm_cents=gross,
                              withhold_cents=withhold, net_pmpm_cents=net)
    if changed or force_touch:
        db.touch(enrollee)


# --------------------------------------------------------------- pool attribution
def pool_posted_remittances(pool):
    return [db.remittances[rid] for rid in pool.get("_remittance_ids", [])
            if rid in db.remittances and db.remittances[rid]["status"] == "POSTED"]


def panel_member_months_bps(pool, physician_id):
    total = 0
    for remittance in pool_posted_remittances(pool):
        per_enrollee = remittance.get("_per_enrollee_mm") or {}
        attribution = remittance.get("_per_enrollee_physician") or {}
        for enrollee_id, mm_bps in per_enrollee.items():
            if attribution.get(enrollee_id) == physician_id:
                total += mm_bps
    return total


def pool_for_service_date(agreement_id, pool_type, service_date):
    """Closed-interval containment (PRD 2.11)."""
    for pool in db.pools_of_agreement(agreement_id):
        if pool["pool_type"] != pool_type:
            continue
        if (pool["pool_year_start"].dt <= service_date.dt
                <= pool["pool_year_end"].dt):
            return pool
    return None
