"""Serializers.  Every emitted field traces to the scaffold entity table."""
import derive
from store import render_date, render_instant


def _common(row):
    return {
        "id": row["id"],
        "created_at": render_instant(row["created_at"]),
        "updated_at": render_instant(row["updated_at"]),
        "version": row["version"],
    }


def _appendonly(row):
    # PRD 2.4: PostageLedgerEntry, ReturnEvent and BlackoutDate carry only
    # id and created_at — no updated_at and no version.
    return {"id": row["id"], "created_at": render_instant(row["created_at"])}


def account(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "permit_number": row["permit_number"],
        "status": row["status"],
        "permit_balance_cents": derive.account_balance(row["id"]),
        "lifetime_topup_cents": derive.account_sum(row["id"], "TOPUP"),
        "lifetime_draw_cents": derive.account_sum(row["id"], "DRAW"),
        "lifetime_refund_cents": derive.account_sum(row["id"], "REFUND"),
        "lifetime_forfeit_cents": derive.account_sum(row["id"], "FORFEIT"),
    })
    return out


def campaign(row):
    out = _common(row)
    out.update({
        "account_id": row["account_id"],
        "name": row["name"],
        "lifecycle_status": row["lifecycle_status"],
        "compliance_status": row["compliance_status"],
        "billing_status": row["billing_status"],
        "write_gate": derive.campaign_write_gate(row),
        "hold_reason": row["hold_reason"],
        "mailed_piece_count": derive.campaign_mailed_piece_count(row["id"]),
        "returned_piece_count": derive.campaign_returned_piece_count(row["id"]),
        "committed_postage_cents": derive.campaign_ledger_sum(row["id"], "DRAW"),
        "refunded_postage_cents": derive.campaign_ledger_sum(row["id"], "REFUND"),
        "forfeited_postage_cents": derive.campaign_ledger_sum(row["id"], "FORFEIT"),
    })
    return out


def handwriting_style(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "pen_type": row["pen_type"],
        "ink_type": row["ink_type"],
        "chars_per_minute": row["chars_per_minute"],
        "ink_ul_per_1000_chars": row["ink_ul_per_1000_chars"],
    })
    return out


def template(row):
    out = _common(row)
    out.update({
        "account_id": row["account_id"],
        "handwriting_style_id": row["handwriting_style_id"],
        "name": row["name"],
        "body_text": row["body_text"],
        "character_count": row["character_count"],
        "version_no": row["version_no"],
        "envelope_style": row["envelope_style"],
    })
    return out


def mailing_list(row):
    out = _common(row)
    out.update({
        "account_id": row["account_id"],
        "name": row["name"],
        "import_status": row["import_status"],
        "dedupe_mode": row["dedupe_mode"],
    })
    out.update(derive.list_counts(row["id"]))
    return out


def list_record(row):
    out = _common(row)
    out.update({
        "mailing_list_id": row["mailing_list_id"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "address_line1": row["address_line1"],
        "address_line2": row["address_line2"],
        "city": row["city"],
        "state_code": row["state_code"],
        "zip5": row["zip5"],
        "country_code": row["country_code"],
        "dpv_confirmation_code": row["dpv_confirmation_code"],
        "cass_status": row["cass_status"],
        "deliverability_tier": row["deliverability_tier"],
        "dedupe_status": row["dedupe_status"],
        "mail_status": row["mail_status"],
        "move_status": row["move_status"],
        "exact_key": row["exact_key"],
        "household_key": row["household_key"],
        "reprint_count": derive.record_reprint_count(row),
        "last_mail_job_id": row["last_mail_job_id"],
        "insertion_seq": row["insertion_seq"],
    })
    return out


def mail_job(row):
    out = _common(row)
    out.update({
        "campaign_id": row["campaign_id"],
        "template_id": row["template_id"],
        "mailing_list_id": row["mailing_list_id"],
        "job_kind": row["job_kind"],
        "mail_class": row["mail_class"],
        "eddm_rate_variant": row["eddm_rate_variant"],
        "status": row["status"],
        "pinned_template_version": row["pinned_template_version"],
        "automation_piece_count": row["automation_piece_count"],
        "retail_piece_count": row["retail_piece_count"],
        "unmailable_piece_count": row["unmailable_piece_count"],
        "eddm_piece_count": row["eddm_piece_count"],
        "billable_piece_count": row["billable_piece_count"],
        "presort_tier": row["presort_tier"],
        "provisional_postage_cents": row["provisional_postage_cents"],
        "final_postage_cents": row["final_postage_cents"],
        "handling_fee_cents": row["handling_fee_cents"],
        "volume_credit_cents": row["volume_credit_cents"],
        "total_due_cents": row["total_due_cents"],
        "drawn_postage_cents": row["drawn_postage_cents"],
        "refunded_postage_cents": derive.job_refunded_postage_cents(row["id"]),
        "returned_piece_count": derive.job_returned_piece_count(row["id"]),
        "target_in_home_date": render_date(row["target_in_home_date"]),
        "mail_date": render_date(row["mail_date"]),
        "blackout_shifted_days": row["blackout_shifted_days"],
        "scheduled_at": render_instant(row["scheduled_at"]),
    })
    return out


def eddm_route(row):
    out = _common(row)
    out.update({
        "mail_job_id": row["mail_job_id"],
        "route_code": row["route_code"],
        "total_deliveries": row["total_deliveries"],
        "residential_piece_count": row["residential_piece_count"],
        "business_piece_count": row["business_piece_count"],
        "selected_piece_count": row["selected_piece_count"],
        "saturation_pct": row["saturation_pct"],
    })
    return out


def proof(row):
    out = _common(row)
    out.update({
        "mail_job_id": row["mail_job_id"],
        "template_id": row["template_id"],
        "pinned_template_version": row["pinned_template_version"],
        "status": row["status"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "approved_at": render_instant(row["approved_at"]),
        "expires_at": render_instant(row["expires_at"]),
        "reject_reason": row["reject_reason"],
    })
    return out


def machine(row):
    out = _common(row)
    out.update({
        "machine_code": row["machine_code"],
        "daily_capacity_minutes": row["daily_capacity_minutes"],
        "status": row["status"],
    })
    return out


def ink_lot(row):
    out = _common(row)
    out.update({
        "lot_code": row["lot_code"],
        "ink_type": row["ink_type"],
        "initial_volume_ul": row["initial_volume_ul"],
        "remaining_ul": row["remaining_ul"],
        "status": row["status"],
    })
    return out


def production_run(row):
    out = _common(row)
    out.update({
        "mail_job_id": row["mail_job_id"],
        "machine_id": row["machine_id"],
        "ink_lot_id": row["ink_lot_id"],
        "run_date": render_date(row["run_date"]),
        "piece_count": row["piece_count"],
        "capacity_variant": row["capacity_variant"],
        "planned_write_minutes": row["planned_write_minutes"],
        "planned_slot_minutes": row["planned_slot_minutes"],
        "planned_ink_ul": row["planned_ink_ul"],
        "status": row["status"],
        "spoiled_piece_count": row["spoiled_piece_count"],
    })
    return out


def drip_schedule(row):
    out = _common(row)
    out.update({
        "campaign_id": row["campaign_id"],
        "name": row["name"],
        "anchor_variant": row["anchor_variant"],
        "status": row["status"],
        "step_count": derive.schedule_step_count(row["id"]) if row["status"] != "CANCELLED" else 0,
    })
    return out


def drip_step(row):
    out = _common(row)
    out.update({
        "drip_schedule_id": row["drip_schedule_id"],
        "mail_job_id": row["mail_job_id"],
        "sequence_no": row["sequence_no"],
        "anchor_date": render_date(row["anchor_date"]),
        "computed_mail_date": render_date(row["computed_mail_date"]),
        "computed_in_home_date": render_date(row["computed_in_home_date"]),
        "shifted_days": row["shifted_days"],
        "status": row["status"],
    })
    return out


def ledger_entry(row):
    out = _appendonly(row)
    out.update({
        "account_id": row["account_id"],
        "mail_job_id": row["mail_job_id"],
        "campaign_id": row["campaign_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "signed_amount_cents": row["signed_amount_cents"],
        "balance_after_cents": row["balance_after_cents"],
        "reason": row["reason"],
    })
    return out


def return_event(row):
    out = _appendonly(row)
    out.update({
        "list_record_id": row["list_record_id"],
        "mail_job_id": row["mail_job_id"],
        "return_reason": row["return_reason"],
        "entitlement": row["entitlement"],
        "return_fee_cents": row["return_fee_cents"],
    })
    return out


def reprint_request(row):
    out = _common(row)
    out.update({
        "list_record_id": row["list_record_id"],
        "return_event_id": row["return_event_id"],
        "campaign_id": row["campaign_id"],
        "status": row["status"],
        "deny_reason": row["deny_reason"],
    })
    return out


def blackout_date(row):
    out = _appendonly(row)
    out.update({
        "blackout_date": render_date(row["blackout_date"]),
        "reason": row["reason"],
    })
    return out
