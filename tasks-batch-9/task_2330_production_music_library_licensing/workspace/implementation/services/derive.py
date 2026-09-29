"""Lookups, derived-field computation and response serialization.

Derived fields (SCAFFOLD `source: computed`) are recomputed from the live store
on every read so they can never drift.
"""

from decimal import Decimal

from db import DB, fmt_ts, parse_ts, sort_rows
from errors import fail
from services.calc import (
    OVERAGE_RATE_CENTS_PER_MINUTE,
    dp2,
    num,
)

NOT_FOUND = {
    "composers": "ERR_COMPOSER_NOT_FOUND",
    "agreements": "ERR_COMPOSER_AGREEMENT_NOT_FOUND",
    "compositions": "ERR_COMPOSITION_NOT_FOUND",
    "tiers": "ERR_LICENSE_TIER_NOT_FOUND",
    "licensees": "ERR_LICENSEE_NOT_FOUND",
    "sync_requests": "ERR_SYNC_REQUEST_NOT_FOUND",
    "licenses": "ERR_LICENSE_NOT_FOUND",
    "blankets": "ERR_BLANKET_AGREEMENT_NOT_FOUND",
    "usage_reports": "ERR_USAGE_REPORT_NOT_FOUND",
    "cue_sheets": "ERR_CUE_SHEET_NOT_FOUND",
    "matches": "ERR_FINGERPRINT_MATCH_NOT_FOUND",
    "claims": "ERR_INFRINGEMENT_CLAIM_NOT_FOUND",
    "statements": "ERR_ROYALTY_STATEMENT_NOT_FOUND",
    "ledger": "ERR_ROYALTY_LEDGER_ENTRY_NOT_FOUND",
}


def table(name):
    return getattr(DB, name)


def lookup(name, row_id):
    """Resolve an id in `name`, raising that entity's not-found error."""
    if not isinstance(row_id, str):
        fail(NOT_FOUND[name])
    row = table(name).get(row_id)
    if row is None:
        fail(NOT_FOUND[name])
    return row


def rows(name):
    return sort_rows(list(table(name).values()))


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------
def composer_entries(composer_id):
    return [e for e in rows("ledger") if e["composer_id"] == composer_id]


def accrued_unpaid_cents(composer_id):
    total = 0
    for entry in composer_entries(composer_id):
        if entry["statement_id"] is None and entry["source_type"] not in ("ADVANCE", "ADVANCE_RECOUP"):
            total += entry["amount_cents"]
    return total


def outstanding_advance_cents(composer_id):
    total = 0
    for entry in composer_entries(composer_id):
        if entry["source_type"] in ("ADVANCE", "ADVANCE_RECOUP"):
            total += entry["amount_cents"]
    return max(0, -total)


def lifetime_paid_cents(composer_id):
    total = 0
    for st in rows("statements"):
        if st["composer_id"] == composer_id and st["status"] == "PAID":
            total += st["net_payable_cents"]
    return total


def latest_statement_period_end(composer_id):
    best = None
    for st in rows("statements"):
        if st["composer_id"] != composer_id:
            continue
        if best is None or st["_period_end_dt"] > best["_period_end_dt"]:
            best = st
    return None if best is None else best["period_end"]


def serialize_composer(row):
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "pro_affiliation": row["pro_affiliation"],
        "payee_country": row["payee_country"],
        "tax_withholding_pct": num(row["_tax_withholding_pct"]),
        "accrued_unpaid_cents": accrued_unpaid_cents(row["id"]),
        "outstanding_advance_cents": outstanding_advance_cents(row["id"]),
        "lifetime_paid_cents": lifetime_paid_cents(row["id"]),
        "latest_statement_period_end": latest_statement_period_end(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# ComposerAgreement
# ---------------------------------------------------------------------------
def serialize_agreement(row):
    return {
        "id": row["id"],
        "composer_id": row["composer_id"],
        "agreement_type": row["agreement_type"],
        "status": row["status"],
        "writer_share_pct": num(row["_writer_share_pct"]),
        "publisher_share_pct": num(row["_publisher_share_pct"]),
        "sync_fee_share_pct": num(row["_sync_fee_share_pct"]),
        "buyout_fee_cents": row["buyout_fee_cents"],
        "exclusivity": row["exclusivity"],
        "holdback_days": row["holdback_days"],
        "advance_cents": row["advance_cents"],
        "blanket_opt_in": row["blanket_opt_in"],
        "pending_writer_share_pct": num(row["_pending_writer_share_pct"]),
        "pending_publisher_share_pct": num(row["_pending_publisher_share_pct"]),
        "pending_sync_fee_share_pct": num(row["_pending_sync_fee_share_pct"]),
        "pending_holdback_days": row["pending_holdback_days"],
        "amendment_round": row["amendment_round"],
        "signed_at": row["signed_at"],
        "terminated_at": row["terminated_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------
def composition_licenses(composition_id):
    return [l for l in rows("licenses") if l["composition_id"] == composition_id]


def active_license_count(composition_id):
    return len([
        l for l in composition_licenses(composition_id) if l["status"] in ("ISSUED", "ACTIVE")
    ])


def exclusive_block_until(composition_id):
    best = None
    for lic in composition_licenses(composition_id):
        if lic["is_exclusive"] and lic["status"] in ("ISSUED", "ACTIVE"):
            if best is None or lic["_exclusive_block_until_dt"] > best:
                best = lic["_exclusive_block_until_dt"]
    return best


def open_claim_count(composition_id):
    return len([
        c for c in rows("claims")
        if c["composition_id"] == composition_id and c["status"] in ("NOTICED", "DISPUTED")
    ])


def lifetime_performance_credits(composition_id):
    total = Decimal("0")
    for sheet in rows("cue_sheets"):
        if sheet["status"] in ("REGISTERED", "ACCEPTED_BY_SOCIETY"):
            total += sheet["_credits_by_composition"].get(composition_id, Decimal("0"))
    return dp2(total)


def serialize_composition(row, relevance_score=None):
    return {
        "id": row["id"],
        "composer_id": row["composer_id"],
        "agreement_id": row["agreement_id"],
        "title": row["title"],
        "duration_sec": row["duration_sec"],
        "tempo_bpm": row["tempo_bpm"],
        "genre": row["genre"],
        "mood_tags": list(row["mood_tags"]),
        "instrumentation": list(row["instrumentation"]),
        "catalog_status": row["catalog_status"],
        "availability_status": row["availability_status"],
        "active_license_count": active_license_count(row["id"]),
        "exclusive_block_until": fmt_ts(exclusive_block_until(row["id"])),
        "open_claim_count": open_claim_count(row["id"]),
        "lifetime_performance_credits": num(lifetime_performance_credits(row["id"])),
        "relevance_score": num(relevance_score) if relevance_score is not None else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# CatalogSearchProfile
# ---------------------------------------------------------------------------
def serialize_profile(row):
    return {
        "id": row["id"],
        "weight_mood": row["weight_mood"],
        "weight_genre": row["weight_genre"],
        "weight_instrumentation": row["weight_instrumentation"],
        "weight_tempo": row["weight_tempo"],
        "tempo_tolerance_bpm": row["tempo_tolerance_bpm"],
        "restricted_availability_factor": num(row["_restricted_availability_factor"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# LicenseTier
# ---------------------------------------------------------------------------
def serialize_tier(row):
    return {
        "id": row["id"],
        "code": row["code"],
        "media_type": row["media_type"],
        "allowed_scales": list(row["allowed_scales"]),
        "base_rate_cents": row["base_rate_cents"],
        "min_term_months": row["min_term_months"],
        "max_term_months": row["max_term_months"],
        "per_use_eligible": row["per_use_eligible"],
        "blanket_eligible": row["blanket_eligible"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# Licensee
# ---------------------------------------------------------------------------
def committed_spend_cents(licensee_id):
    total = 0
    for lic in rows("licenses"):
        if lic["licensee_id"] == licensee_id and lic["status"] in ("ISSUED", "ACTIVE"):
            total += lic["final_fee_cents"]
    return total


def reserved_spend_cents(licensee_id):
    total = 0
    for sr in rows("sync_requests"):
        if (
            sr["licensee_id"] == licensee_id
            and sr["status"] in ("QUOTED", "ACCEPTED", "EDIT_IN_PROGRESS")
            and sr["license_id"] is None
            and sr["quoted_fee_cents"] is not None
        ):
            total += sr["quoted_fee_cents"]
    return total


def serialize_licensee(row):
    committed = committed_spend_cents(row["id"])
    reserved = reserved_spend_cents(row["id"])
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "licensee_type": row["licensee_type"],
        "credit_limit_cents": row["credit_limit_cents"],
        "committed_spend_cents": committed,
        "reserved_spend_cents": reserved,
        "credit_available_cents": row["credit_limit_cents"] - committed - reserved,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# SyncRequest
# ---------------------------------------------------------------------------
def serialize_sync_request(row):
    return {
        "id": row["id"],
        "composition_id": row["composition_id"],
        "licensee_id": row["licensee_id"],
        "tier_id": row["tier_id"],
        "media_type": row["media_type"],
        "distribution_scale": row["distribution_scale"],
        "requested_term_start": row["requested_term_start"],
        "requested_term_months": row["requested_term_months"],
        "exclusive_requested": row["exclusive_requested"],
        "custom_edit_requested": row["custom_edit_requested"],
        "stems_requested": row["stems_requested"],
        "alternate_lengths_sec": list(row["alternate_lengths_sec"]),
        "rush_requested": row["rush_requested"],
        "brief_note": row["brief_note"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "quoted_fee_cents": row["quoted_fee_cents"],
        "quoted_spend_basis_cents": row["quoted_spend_basis_cents"],
        "quoted_discount_pct": num(row["_quoted_discount_pct"]),
        "quote_expires_at": row["quote_expires_at"],
        "license_id": row["license_id"],
        "decline_reason": row["decline_reason"],
        "delivered_asset_count": row["delivered_asset_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# License
# ---------------------------------------------------------------------------
def serialize_license(row):
    return {
        "id": row["id"],
        "sync_request_id": row["sync_request_id"],
        "composition_id": row["composition_id"],
        "licensee_id": row["licensee_id"],
        "tier_id": row["tier_id"],
        "blanket_agreement_id": row["blanket_agreement_id"],
        "license_mode": row["license_mode"],
        "media_type": row["media_type"],
        "distribution_scale": row["distribution_scale"],
        "is_exclusive": row["is_exclusive"],
        "term_start": row["term_start"],
        "term_months": row["term_months"],
        "term_end": row["term_end"],
        "exclusive_block_until": row["exclusive_block_until"],
        "final_fee_cents": row["final_fee_cents"],
        "final_spend_basis_cents": row["final_spend_basis_cents"],
        "final_discount_pct": num(row["_final_discount_pct"]),
        "composer_sync_share_cents": row["composer_sync_share_cents"],
        "collected_amount_cents": row["collected_amount_cents"],
        "collected_at": row["collected_at"],
        "status": row["status"],
        "revoke_reason": row["revoke_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# BlanketAgreement
# ---------------------------------------------------------------------------
def blanket_reports(blanket_agreement_id):
    return [r for r in rows("usage_reports") if r["blanket_agreement_id"] == blanket_agreement_id]


def reported_minutes_ytd(blanket_agreement_id):
    return sum(
        r["reported_minutes_total"]
        for r in blanket_reports(blanket_agreement_id)
        if r["status"] == "ACCEPTED"
    )


def overage_figures(blanket):
    ytd = reported_minutes_ytd(blanket["id"])
    minutes = max(0, ytd - blanket["usage_cap_minutes"])
    return ytd, minutes, minutes * OVERAGE_RATE_CENTS_PER_MINUTE


def serialize_blanket(row):
    ytd, overage_minutes, overage_cents = overage_figures(row)
    accepted = [r for r in blanket_reports(row["id"]) if r["status"] == "ACCEPTED"]
    return {
        "id": row["id"],
        "licensee_id": row["licensee_id"],
        "coverage_start": row["coverage_start"],
        "coverage_end": row["coverage_end"],
        "annual_fee_cents": row["annual_fee_cents"],
        "reporting_cadence": row["reporting_cadence"],
        "usage_cap_minutes": row["usage_cap_minutes"],
        "pool_share_pct": num(row["_pool_share_pct"]),
        "coverage_status": row["coverage_status"],
        "reporting_status": row["reporting_status"],
        "reported_minutes_ytd": ytd,
        "overage_minutes": overage_minutes,
        "overage_cents": overage_cents,
        "pool_distributed_cents": sum(r["pool_distributable_cents"] for r in accepted),
        "pool_admin_fee_cents": sum(r["pool_admin_fee_cents"] for r in accepted),
        "delinquent_since": row["delinquent_since"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# UsageReport
# ---------------------------------------------------------------------------
def report_sheets(usage_report_id):
    return [s for s in rows("cue_sheets") if s["usage_report_id"] == usage_report_id]


def report_usage_totals(usage_report_id):
    """Live minutes/credits over the report's REGISTERED / ACCEPTED_BY_SOCIETY sheets."""
    seconds = 0
    credits = Decimal("0")
    for sheet in report_sheets(usage_report_id):
        if sheet["status"] in ("REGISTERED", "ACCEPTED_BY_SOCIETY"):
            seconds += sheet["total_seconds"]
            credits += sheet["_total_credits"]
    minutes = -(-seconds // 60)  # ceiling division, applied once per report
    return minutes, dp2(credits)


def serialize_report(row):
    if row["status"] == "ACCEPTED":
        minutes = row["reported_minutes_total"]
        credits = row["_reported_credits_total"]
    else:
        minutes, credits = report_usage_totals(row["id"])
    return {
        "id": row["id"],
        "blanket_agreement_id": row["blanket_agreement_id"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "status": row["status"],
        "reported_minutes_total": minutes,
        "reported_credits_total": num(dp2(credits)),
        "pool_cents": row["pool_cents"],
        "pool_admin_fee_cents": row["pool_admin_fee_cents"],
        "pool_distributable_cents": row["pool_distributable_cents"],
        "pool_allocations": [dict(a) for a in row["pool_allocations"]],
        "rejection_reason": row["rejection_reason"],
        "submitted_at": row["submitted_at"],
        "accepted_at": row["accepted_at"],
        "resubmission_count": row["resubmission_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# CueSheet
# ---------------------------------------------------------------------------
def serialize_cue_sheet(row):
    return {
        "id": row["id"],
        "license_id": row["license_id"],
        "usage_report_id": row["usage_report_id"],
        "production_title": row["production_title"],
        "broadcast_date": row["broadcast_date"],
        "market_tier": row["market_tier"],
        "cues": [dict(c) for c in row["cues"]],
        "status": row["status"],
        "cue_credit_breakdown": [dict(c) for c in row["cue_credit_breakdown"]],
        "total_credits": num(row["_total_credits"]),
        "total_seconds": row["total_seconds"],
        "credits_by_composition": {
            k: num(v) for k, v in row["_credits_by_composition"].items()
        },
        "society_reference": row["society_reference"],
        "registration_round": row["registration_round"],
        "registered_at": row["registered_at"],
        "rejection_reason": row["rejection_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# FingerprintMatch / InfringementClaim
# ---------------------------------------------------------------------------
def serialize_match(row):
    return {
        "id": row["id"],
        "composition_id": row["composition_id"],
        "source_platform": row["source_platform"],
        "source_reference": row["source_reference"],
        "matched_seconds": row["matched_seconds"],
        "confidence_pct": num(row["_confidence_pct"]),
        "detected_at": row["detected_at"],
        "created_at": row["created_at"],
    }


def serialize_claim(row):
    return {
        "id": row["id"],
        "composition_id": row["composition_id"],
        "fingerprint_match_id": row["fingerprint_match_id"],
        "status": row["status"],
        "statutory_amount_cents": row["statutory_amount_cents"],
        "settlement_floor_cents": row["settlement_floor_cents"],
        "settlement_amount_cents": row["settlement_amount_cents"],
        "settlement_basis": row["settlement_basis"],
        "settlement_collected": row["settlement_collected"],
        "composer_share_cents": row["composer_share_cents"],
        "notice_channel": row["notice_channel"],
        "dispute_note": row["dispute_note"],
        "escalation_note": row["escalation_note"],
        "noticed_at": row["noticed_at"],
        "settled_at": row["settled_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# Royalty accounting
# ---------------------------------------------------------------------------
def serialize_statement(row):
    return {
        "id": row["id"],
        "composer_id": row["composer_id"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "basis": row["basis"],
        "status": row["status"],
        "gross_cents": row["gross_cents"],
        "recouped_cents": row["recouped_cents"],
        "withholding_cents": row["withholding_cents"],
        "net_payable_cents": row["net_payable_cents"],
        "line_count": row["line_count"],
        "payout_status": row["payout_status"],
        "finalized_by_user_id": row["finalized_by_user_id"],
        "paid_by_user_id": row["paid_by_user_id"],
        "payment_reference": row["payment_reference"],
        "finalized_at": row["finalized_at"],
        "paid_at": row["paid_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_entry(row):
    return {
        "id": row["id"],
        "composer_id": row["composer_id"],
        "statement_id": row["statement_id"],
        "source_type": row["source_type"],
        "source_ref_id": row["source_ref_id"],
        "amount_cents": row["amount_cents"],
        "accrual_recognized_at": row["accrual_recognized_at"],
        "cash_recognized_at": row["cash_recognized_at"],
        "memo": row["memo"],
        "created_at": row["created_at"],
    }
