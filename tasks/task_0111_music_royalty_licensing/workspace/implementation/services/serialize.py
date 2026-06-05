"""Public serialization of entities.

Each serializer emits exactly the fields declared in SCAFFOLD §1.1 for that
entity, recomputing computed fields where they are read-time derivable, and
strips internal bookkeeping (_seq). Computed-store fields (recouped_cents,
gross_earnings_cents, etc.) are kept current by the services that mutate them,
so we read them straight from the record.
"""
import db


def _base(rec, common=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if common:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


# ---------------------------------------------------------------------------
# Computed: Rightsholder.lifetime_earned_cents and unrecouped_balance_cents
# ---------------------------------------------------------------------------
def rightsholder_lifetime_earned(rh_id):
    """Sum of EARNING ledger amounts across this rightsholder's FINALIZED
    statements (PRD §2.5/§3.6)."""
    total = 0
    for entry in db.ledger_entries.values():
        if entry["entry_type"] != "EARNING":
            continue
        if entry["rightsholder_id"] != rh_id:
            continue
        stmt = db.statements.get(entry["statement_id"])
        if stmt and stmt["status"] == "FINALIZED":
            total += entry["amount_cents"]
    return total


def rightsholder_unrecouped(rh_id):
    """Sum over this rightsholder's ACTIVE advances of (principal - recouped),
    floored at 0 (PRD §2.5)."""
    total = 0
    for adv in db.advances.values():
        if adv["rightsholder_id"] == rh_id and adv["status"] == "ACTIVE":
            total += adv["principal_cents"] - adv["recouped_cents"]
    return max(0, total)


def rightsholder(rec):
    out = _base(rec)
    out.update({
        "legal_name": rec["legal_name"],
        "party_type": rec["party_type"],
        "payee_country": rec["payee_country"],
        "minimum_payout_cents": rec["minimum_payout_cents"],
        "withholding_pct": rec["withholding_pct"],
        "lifetime_earned_cents": rightsholder_lifetime_earned(rec["id"]),
        "unrecouped_balance_cents": rightsholder_unrecouped(rec["id"]),
        "status": rec["status"],
    })
    return out


def work_split_total(work_id):
    return sum(s["split_bps"] for s in db.composition_shares.values()
               if s["work_id"] == work_id)


def work(rec):
    out = _base(rec)
    out.update({
        "title": rec["title"],
        "iswc": rec["iswc"],
        "pro_affiliation": rec["pro_affiliation"],
        "duration_seconds": rec["duration_seconds"],
        "shares_locked": rec["shares_locked"],
        "split_total_bps": work_split_total(rec["id"]),
    })
    return out


def composition_share(rec):
    out = _base(rec)
    out.update({
        "work_id": rec["work_id"],
        "rightsholder_id": rec["rightsholder_id"],
        "role": rec["role"],
        "split_bps": rec["split_bps"],
    })
    return out


def recording_split_total(recording_id):
    return sum(s["split_bps"] for s in db.recording_shares.values()
               if s["recording_id"] == recording_id)


def recording(rec):
    out = _base(rec)
    out.update({
        "work_id": rec["work_id"],
        "isrc": rec["isrc"],
        "title": rec["title"],
        "release_type": rec["release_type"],
        "duration_seconds": rec["duration_seconds"],
        "shares_locked": rec["shares_locked"],
        "split_total_bps": recording_split_total(rec["id"]),
    })
    return out


def recording_share(rec):
    out = _base(rec)
    out.update({
        "recording_id": rec["recording_id"],
        "rightsholder_id": rec["rightsholder_id"],
        "split_bps": rec["split_bps"],
    })
    return out


def rights_window(rec):
    out = _base(rec)
    out.update({
        "recording_id": rec["recording_id"],
        "territory": rec["territory"],
        "rights_type": rec["rights_type"],
        "term_start": rec["term_start"],
        "term_end": rec["term_end"],
        "status": rec["status"],
    })
    return out


def usage_event(rec):
    out = _base(rec)
    out.update({
        "recording_id": rec["recording_id"],
        "usage_type": rec["usage_type"],
        "territory": rec["territory"],
        "occurred_at": rec["occurred_at"],
        "quantity": rec["quantity"],
        "gross_revenue_cents": rec["gross_revenue_cents"],
        "status": rec["status"],
        "royalty_cents": rec["royalty_cents"],
        "allocated_holder_count": rec["allocated_holder_count"],
    })
    return out


def sync_license(rec):
    out = _base(rec)
    out.update({
        "recording_id": rec["recording_id"],
        "licensee_id": rec["licensee_id"],
        "media_type": rec["media_type"],
        "territory": rec["territory"],
        "term_months": rec["term_months"],
        "base_fee_cents": rec["base_fee_cents"],
        "quoted_fee_cents": rec["quoted_fee_cents"],
        "status": rec["status"],
        "counter_fee_cents": rec["counter_fee_cents"],
    })
    return out


def advance(rec):
    out = _base(rec)
    out.update({
        "rightsholder_id": rec["rightsholder_id"],
        "principal_cents": rec["principal_cents"],
        "recoupment_pct": rec["recoupment_pct"],
        "recouped_cents": rec["recouped_cents"],
        "status": rec["status"],
    })
    return out


def statement(rec):
    out = _base(rec)
    out.update({
        "rightsholder_id": rec["rightsholder_id"],
        "period_start": rec["period_start"],
        "period_end": rec["period_end"],
        "gross_earnings_cents": rec["gross_earnings_cents"],
        "recoupment_applied_cents": rec["recoupment_applied_cents"],
        "withholding_cents": rec["withholding_cents"],
        "net_payable_cents": rec["net_payable_cents"],
        "carried_forward_cents": rec["carried_forward_cents"],
        "status": rec["status"],
    })
    return out


def ledger_entry(rec):
    # common_fields: false -> id + created_at only (PRD §2.4).
    out = _base(rec, common=False)
    out.update({
        "statement_id": rec["statement_id"],
        "rightsholder_id": rec["rightsholder_id"],
        "entry_type": rec["entry_type"],
        "source_type": rec["source_type"],
        "source_id": rec["source_id"],
        "amount_cents": rec["amount_cents"],
    })
    return out


def payout(rec):
    out = _base(rec)
    out.update({
        "statement_id": rec["statement_id"],
        "rightsholder_id": rec["rightsholder_id"],
        "amount_cents": rec["amount_cents"],
        "status": rec["status"],
    })
    return out
