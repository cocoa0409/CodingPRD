"""Resource serializers. Derived fields are computed at read time."""

from services import derive


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def rights_holder(holder):
    data = _common(holder)
    data.update({
        "legal_name": holder["legal_name"],
        "holder_type": holder["holder_type"],
        "home_territory_code": holder["home_territory_code"],
        "direct_deal_rate_bps": holder["direct_deal_rate_bps"],
        "receivable_balance_cents": derive.holder_receivable_balance_cents(holder["id"]),
        "issued_statement_count": derive.holder_issued_statement_count(holder["id"]),
    })
    return data


def work(record):
    data = _common(record)
    data.update({
        "work_type": record["work_type"],
        "identifier": record["identifier"],
        "title": record["title"],
        "artist_credit": record["artist_credit"],
        "linked_work_id": record["linked_work_id"],
        "normalized_title": record["normalized_title"],
        "normalized_artist": record["normalized_artist"],
        "rights_state": derive.work_rights_state(record),
        "approved_master_share_bps": derive.work_approved_master_share_bps(record),
        "provisional_match_by_user_id": record["provisional_match_by_user_id"],
    })
    return data


def accounting_period(record):
    data = _common(record)
    data.update({
        "label": record["label"],
        "usage_start": record["usage_start"],
        "usage_end": record["usage_end"],
        "claim_window_closes_at": record["claim_window_closes_at"],
        "status": record["status"],
        "total_holding_cents": derive.period_total_holding_cents(record["id"]),
    })
    return data


def usage_batch(record):
    total, matched, unmatched, disputed = derive.batch_play_totals(record["id"])
    data = _common(record)
    data.update({
        "period_id": record["period_id"],
        "source_label": record["source_label"],
        "status": record["status"],
        "line_count": derive.batch_line_count(record["id"]),
        "total_play_count": total,
        "matched_play_count": matched,
        "unmatched_play_count": unmatched,
        "disputed_play_count": disputed,
    })
    return data


def usage_line(record):
    data = _common(record)
    data.update({
        "batch_id": record["batch_id"],
        "work_id": record["work_id"],
        "reported_isrc": record["reported_isrc"],
        "reported_title": record["reported_title"],
        "reported_artist": record["reported_artist"],
        "territory_code": record["territory_code"],
        "subscription_tier": record["subscription_tier"],
        "play_count": record["play_count"],
        "match_status": record["match_status"],
        "match_confidence_bps": record["match_confidence_bps"],
        "attributed_revenue_cents": record["attributed_revenue_cents"],
    })
    return data


def rights_registration(record):
    data = _common(record)
    data.update({
        "work_id": record["work_id"],
        "claimant_id": record["claimant_id"],
        "collective_id": record["collective_id"],
        "right_type": record["right_type"],
        "routing": record["routing"],
        "share_bps": record["share_bps"],
        "territory_set": list(record["territory_set"]),
        "effective_from": record["effective_from"],
        "effective_to": record["effective_to"],
        "supersede_overlapping": record["supersede_overlapping"],
        "payee_holder_id": record["payee_holder_id"],
        "status": record["status"],
        "evidence_round": record["evidence_round"],
        "reviewed_by_user_id": record["reviewed_by_user_id"],
        "disputing_holder_id": record["disputing_holder_id"],
        "rejection_reason": record["rejection_reason"],
    })
    return data


def royalty_pool(record):
    data = _common(record)
    data.update({
        "period_id": record["period_id"],
        "territory_code": record["territory_code"],
        "subscription_tier": record["subscription_tier"],
        "subscriber_count": record["subscriber_count"],
        "gross_revenue_cents": record["gross_revenue_cents"],
        "applied_rate_schedule_id": record["applied_rate_schedule_id"],
        "revenue_share_pool_cents": record["revenue_share_pool_cents"],
        "minimum_pool_cents": record["minimum_pool_cents"],
        "statutory_floor_cents": record["statutory_floor_cents"],
        "total_play_count": record["total_play_count"],
        "denominator_basis": record["denominator_basis"],
        "denominator_play_count": record["denominator_play_count"],
        "distributable_cents": record["distributable_cents"],
        "allocation_basis": record["allocation_basis"],
        "matched_attributed_cents": derive.pool_matched_attributed_cents(record),
        "holding_cents": derive.pool_holding_cents(record),
        "rounding_residual_cents": record["rounding_residual_cents"],
        "residual_payee_holder_id": record["residual_payee_holder_id"],
        "status": record["status"],
    })
    return data


def royalty_statement(record):
    gross, fee, net, count = derive.statement_totals(record["id"])
    data = _common(record)
    data.update({
        "rights_holder_id": record["rights_holder_id"],
        "period_id": record["period_id"],
        "status": record["status"],
        "gross_cents": gross,
        "admin_fee_cents": fee,
        "net_payable_cents": net,
        "line_count": count,
        "issued_at": record["issued_at"],
    })
    return data


def statement_line(record):
    # StatementLine is immutable: it carries only id and created_at (§2.4).
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "statement_id": record["statement_id"],
        "pool_id": record["pool_id"],
        "work_id": record["work_id"],
        "adjustment_of_line_id": record["adjustment_of_line_id"],
        "payee_holder_id": record["payee_holder_id"],
        "line_type": record["line_type"],
        "right_type": record["right_type"],
        "routing": record["routing"],
        "territory_code": record["territory_code"],
        "subscription_tier": record["subscription_tier"],
        "play_count": record["play_count"],
        "share_bps": record["share_bps"],
        "gross_cents": record["gross_cents"],
        "admin_fee_cents": record["admin_fee_cents"],
        "net_cents": record["net_cents"],
    }


def audit_engagement(record):
    data = _common(record)
    data.update({
        "rights_holder_id": record["rights_holder_id"],
        "statement_id": record["statement_id"],
        "requested_scope_start": record["requested_scope_start"],
        "requested_scope_end": record["requested_scope_end"],
        "production_deadline_at": record["production_deadline_at"],
        "required_line_count": record["required_line_count"],
        "produced_line_count": record["produced_line_count"],
        "production_status": derive.production_status(record),
        "finding_status": record["finding_status"],
        "asserted_underpayment_cents": record["asserted_underpayment_cents"],
        "settled_amount_cents": record["settled_amount_cents"],
        "interest_cents": record["interest_cents"],
        "finding_note": record["finding_note"],
        "findings_recorded_by_user_id": record["findings_recorded_by_user_id"],
    })
    return data


def rate_schedule(record):
    data = _common(record)
    data.update({
        "proceeding_ref": record["proceeding_ref"],
        "territory_code": record["territory_code"],
        "subscription_tier": record["subscription_tier"],
        "revenue_share_bps": record["revenue_share_bps"],
        "per_subscriber_minimum_cents": record["per_subscriber_minimum_cents"],
        "mechanical_share_bps": record["mechanical_share_bps"],
        "performance_share_bps": record["performance_share_bps"],
        "statutory_floor_per_play_millicents": record["statutory_floor_per_play_millicents"],
        "effective_from": record["effective_from"],
        "effective_to": record["effective_to"],
        "retroactive": record["retroactive"],
        "status": record["status"],
        "promulgated_at": record["promulgated_at"],
    })
    return data
