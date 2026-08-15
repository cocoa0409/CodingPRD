"""Entity serializers — one function per resource, emitting exactly the fields
declared in SCAFFOLD §1.1 plus the common system fields (PRD §2.6). Date
fields are stored as datetime.date and rendered as YYYY-MM-DD strings;
nullable fields serialize as null until set.
"""


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _d(v):
    return v.isoformat() if v is not None else None


def jurisdiction_rule(rec):
    out = _base(rec)
    out.update({
        "jurisdiction": rec["jurisdiction"],
        "oa_response_months": rec["oa_response_months"],
        "max_extensions": rec["max_extensions"],
        "extension_months": rec["extension_months"],
        "extension_fee_cents": rec["extension_fee_cents"],
        "annuity_start_year": rec["annuity_start_year"],
        "term_years": rec["term_years"],
        "surcharge_window_months": rec["surcharge_window_months"],
        "surcharge_bps_month_1": rec["surcharge_bps_month_1"],
        "surcharge_bps_late": rec["surcharge_bps_late"],
        "small_entity_multiplier_bps": rec["small_entity_multiplier_bps"],
        "fee_tier_bounds": rec["fee_tier_bounds"],
        "fee_tier_1_cents": rec["fee_tier_1_cents"],
        "fee_tier_2_cents": rec["fee_tier_2_cents"],
        "fee_tier_3_cents": rec["fee_tier_3_cents"],
        "fee_tier_4_cents": rec["fee_tier_4_cents"],
        "paris_window_months": rec["paris_window_months"],
        "pct_window_months": rec["pct_window_months"],
        "fx_to_usd_cents_bps": rec["fx_to_usd_cents_bps"],
        "requires_recorded_assignment_for_grant": rec["requires_recorded_assignment_for_grant"],
        "requires_recorded_assignment_for_payment": rec["requires_recorded_assignment_for_payment"],
        "requires_confirmed_instruction_for_payment": rec["requires_confirmed_instruction_for_payment"],
    })
    return out


def client(rec):
    out = _base(rec)
    out.update({
        "display_name": rec["display_name"],
        "default_currency": rec["default_currency"],
        "status": rec["status"],
    })
    return out


def contact(rec):
    out = _base(rec)
    out.update({
        "client_id": rec["client_id"],
        "full_name": rec["full_name"],
        "email": rec["email"],
    })
    return out


def counsel_firm(rec):
    out = _base(rec)
    out.update({
        "display_name": rec["display_name"],
        "accredited_jurisdictions": list(rec["accredited_jurisdictions"]),
    })
    return out


def inventor(rec):
    out = _base(rec)
    out.update({
        "client_id": rec["client_id"],
        "full_name": rec["full_name"],
        "email": rec["email"],
    })
    return out


def family(rec):
    out = _base(rec)
    out.update({
        "client_id": rec["client_id"],
        "title": rec["title"],
        "first_priority_date": _d(rec["first_priority_date"]),
        "budget_cap_cents": rec["budget_cap_cents"],
        "status": rec["status"],
        "committed_forecast_cents": rec["committed_forecast_cents"],
    })
    return out


def application(rec):
    out = _base(rec)
    out.update({
        "family_id": rec["family_id"],
        "jurisdiction": rec["jurisdiction"],
        "application_type": rec["application_type"],
        "filing_date": _d(rec["filing_date"]),
        "application_number": rec["application_number"],
        "entity_size": rec["entity_size"],
        "parent_application_id": rec["parent_application_id"],
        "grant_date": _d(rec["grant_date"]),
        "status": rec["status"],
        "open_docket_count": rec["open_docket_count"],
    })
    return out


def docket_entry(rec):
    out = _base(rec)
    out.update({
        "application_id": rec["application_id"],
        "entry_type": rec["entry_type"],
        "title": rec["title"],
        "base_due_date": _d(rec["base_due_date"]),
        "extension_count": rec["extension_count"],
        "extension_fees_total_cents": rec["extension_fees_total_cents"],
        "current_due_date": _d(rec["current_due_date"]),
        "status": rec["status"],
    })
    return out


def office_action(rec):
    out = _base(rec)
    out.update({
        "application_id": rec["application_id"],
        "action_type": rec["action_type"],
        "mail_date": _d(rec["mail_date"]),
        "docket_entry_id": rec["docket_entry_id"],
        "status": rec["status"],
    })
    return out


def obligation(rec):
    out = _base(rec)
    out.update({
        "application_id": rec["application_id"],
        "period_year": rec["period_year"],
        "due_date": _d(rec["due_date"]),
        "surcharge_window_end": _d(rec["surcharge_window_end"]),
        "base_fee_local_cents": rec["base_fee_local_cents"],
        "estimated_amount_usd_cents": rec["estimated_amount_usd_cents"],
        "authorized_amount_cents": rec["authorized_amount_cents"],
        "paid_amount_cents": rec["paid_amount_cents"],
        "status": rec["status"],
    })
    return out


def authorization(rec):
    out = _base(rec)
    out.update({
        "annuity_obligation_id": rec["annuity_obligation_id"],
        "amount_cents": rec["amount_cents"],
        "requested_by_user_id": rec["requested_by_user_id"],
        "decided_by_user_id": rec["decided_by_user_id"],
        "status": rec["status"],
    })
    return out


def instruction(rec):
    out = _base(rec)
    out.update({
        "application_id": rec["application_id"],
        "counsel_firm_id": rec["counsel_firm_id"],
        "docket_entry_id": rec["docket_entry_id"],
        "instruction_type": rec["instruction_type"],
        "due_date": _d(rec["due_date"]),
        "status": rec["status"],
    })
    return out


def review(rec):
    out = _base(rec)
    out.update({
        "application_id": rec["application_id"],
        "rationale": rec["rationale"],
        "estimated_savings_usd_cents": rec["estimated_savings_usd_cents"],
        "submitted_by_user_id": rec["submitted_by_user_id"],
        "status": rec["status"],
    })
    return out


def assignment(rec):
    out = _base(rec)
    out.update({
        "application_id": rec["application_id"],
        "assignee_name": rec["assignee_name"],
        "inventor_ids": list(rec["inventor_ids"]),
        "execution_date": _d(rec["execution_date"]),
        "executed_by_user_id": rec["executed_by_user_id"],
        "register_recordation_number": rec["register_recordation_number"],
        "status": rec["status"],
    })
    return out


def audit(rec):
    out = _base(rec)
    out.update({
        "application_id": rec["application_id"],
        "window_start": _d(rec["window_start"]),
        "window_end": _d(rec["window_end"]),
        "register_entries": [
            {"entry_type": r["entry_type"], "due_date": _d(r["due_date"])}
            for r in rec["register_entries"]
        ],
        "variances": rec["variances"],
        "resolution_note": rec["resolution_note"],
        "status": rec["status"],
    })
    return out
