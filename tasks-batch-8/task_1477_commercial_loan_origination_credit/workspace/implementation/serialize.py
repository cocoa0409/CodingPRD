"""Entity serializers. Derived fields are computed live from the store."""
from services import exposure
from services.money import ratio_to_float


def _common(e):
    return {
        'id': e['id'],
        'created_at': e['created_at'],
        'updated_at': e['updated_at'],
        'version': e['version'],
    }


def bank_officer(o):
    d = _common(o)
    d['full_name'] = o['full_name']
    return d


def borrower(b):
    d = _common(b)
    committed = exposure.borrower_committed_exposure_cents(b['id'])
    funded = exposure.borrower_funded_exposure_cents(b['id'])
    d.update({
        'legal_name': b['legal_name'],
        'naics_code': b['naics_code'],
        'is_reg_o_insider': b['is_reg_o_insider'],
        'relationship_since': b['relationship_since'].isoformat(),
        'status': b['status'],
        'committed_exposure_cents': committed,
        'funded_exposure_cents': funded,
        'total_exposure_cents': committed + funded,
    })
    return d


def loan_application(a):
    d = _common(a)
    total_appraised, total_eligible, total_liquidation = exposure.collateral_aggregates(a['id'])
    d.update({
        'borrower_id': a['borrower_id'],
        'originating_officer_id': a['originating_officer_id'],
        'product_type': a['product_type'],
        'requested_amount_cents': a['requested_amount_cents'],
        'term_months': a['term_months'],
        'purpose': a['purpose'],
        'status': a['status'],
        'dscr_standard': ratio_to_float(a['dscr_standard']),
        'dscr_stress': ratio_to_float(a['dscr_stress']),
        'risk_rating': a['risk_rating'],
        'rating_basis': a['rating_basis'],
        'proposed_amount_cents': a['proposed_amount_cents'],
        'committee_level_required': a['committee_level_required'],
        'total_appraised_value_cents': total_appraised,
        'total_eligible_collateral_cents': total_eligible,
        'total_liquidation_collateral_cents': total_liquidation,
        'bank_hold_amount_cents': exposure.bank_hold_amount_cents(a['id']),
        'bank_hold_fee_cents': exposure.bank_hold_fee_cents(a['id']),
        'funded_amount_cents': exposure.app_funded_amount_cents(a['id']),
    })
    return d


def financial_statement(s):
    d = _common(s)
    d.update({
        'loan_application_id': s['loan_application_id'],
        'restatement_of_id': s['restatement_of_id'],
        'period_end_date': s['period_end_date'].isoformat(),
        'revenue_cents': s['revenue_cents'],
        'ebitda_cents': s['ebitda_cents'],
        'addbacks_cents': s['addbacks_cents'],
        'distributions_cents': s['distributions_cents'],
        'maintenance_capex_cents': s['maintenance_capex_cents'],
        'existing_annual_debt_service_cents': s['existing_annual_debt_service_cents'],
        'total_assets_cents': s['total_assets_cents'],
        'total_liabilities_cents': s['total_liabilities_cents'],
        'status': s['status'],
        'spread_by_officer_id': s['spread_by_officer_id'],
        'finalized_by_officer_id': s['finalized_by_officer_id'],
    })
    return d


def policy_exception(e):
    d = _common(e)
    d.update({
        'loan_application_id': e['loan_application_id'],
        'rule_code': e['rule_code'],
        'severity': e['severity'],
        'status': e['status'],
        'detail': e['detail'],
        'waived_by_officer_id': e['waived_by_officer_id'],
        'waiver_rationale': e['waiver_rationale'],
    })
    return d


def appraiser(a):
    d = _common(a)
    d.update({
        'name': a['name'],
        'license_number': a['license_number'],
        'max_concurrent_engagements': a['max_concurrent_engagements'],
        'status': a['status'],
    })
    return d


def appraisal(a):
    d = _common(a)
    d.update({
        'loan_application_id': a['loan_application_id'],
        'appraiser_id': a['appraiser_id'],
        'collateral_class': a['collateral_class'],
        'engagement_start_date': a['engagement_start_date'].isoformat(),
        'engagement_end_date': a['engagement_end_date'].isoformat(),
        'appraised_value_cents': a['appraised_value_cents'],
        'orderly_liquidation_value_cents': a['orderly_liquidation_value_cents'],
        'eligible_value_cents': a['eligible_value_cents'],
        'liquidation_basis_value_cents': a['liquidation_basis_value_cents'],
        'status': a['status'],
    })
    return d


def committee_session(s):
    d = _common(s)
    d.update({
        'level': s['level'],
        'starts_at': s['starts_at'],
        'ends_at': s['ends_at'],
        'status': s['status'],
    })
    return d


def committee_decision(dec):
    d = _common(dec)
    d.update({
        'loan_application_id': dec['loan_application_id'],
        'committee_session_id': dec['committee_session_id'],
        'level_required': dec['level_required'],
        'votes_required': dec['votes_required'],
        'votes': list(dec['votes']),
        'votes_for': dec['votes_for'],
        'votes_against': dec['votes_against'],
        'chair_approved': dec['chair_approved'],
        'status': dec['status'],
    })
    return d


def term_sheet(t):
    d = _common(t)
    d.update({
        'loan_application_id': t['loan_application_id'],
        'amount_cents': t['amount_cents'],
        'rate_bps': t['rate_bps'],
        'term_months': t['term_months'],
        'expires_at': t['expires_at'],
        'origination_fee_cents': t['origination_fee_cents'],
        'status': t['status'],
    })
    return d


def commitment_letter(l):
    d = _common(l)
    d.update({
        'loan_application_id': l['loan_application_id'],
        'committed_amount_cents': l['committed_amount_cents'],
        'rate_bps': l['rate_bps'],
        'term_months': l['term_months'],
        'origination_fee_cents': l['origination_fee_cents'],
        'expiry_date': l['expiry_date'],
        'rate_lock_expires_at': l['rate_lock_expires_at'],
        'status': l['status'],
    })
    return d


def document_checklist_item(i):
    d = _common(i)
    d.update({
        'loan_application_id': i['loan_application_id'],
        'category': i['category'],
        'label': i['label'],
        'is_required': i['is_required'],
        'severity': i['severity'],
        'status': i['status'],
        'waived_by_officer_id': i['waived_by_officer_id'],
        'waiver_rationale': i['waiver_rationale'],
    })
    return d


def funding_authorization(f):
    d = _common(f)
    d.update({
        'loan_application_id': f['loan_application_id'],
        'amount_cents': f['amount_cents'],
        'disbursement_date': f['disbursement_date'].isoformat(),
        'requested_by_officer_id': f['requested_by_officer_id'],
        'authorized_by_officer_id': f['authorized_by_officer_id'],
        'status': f['status'],
    })
    return d


def covenant(c):
    d = _common(c)
    d.update({
        'loan_application_id': c['loan_application_id'],
        'covenant_type': c['covenant_type'],
        'threshold_value': c['threshold_value'],
        'frequency': c['frequency'],
        'status': c['status'],
        'last_reviewed_period': c['last_reviewed_period'].isoformat() if c['last_reviewed_period'] else None,
    })
    return d


def participation(p):
    d = _common(p)
    d.update({
        'loan_application_id': p['loan_application_id'],
        'participant_bank_name': p['participant_bank_name'],
        'allocated_amount_cents': p['allocated_amount_cents'],
        'fee_share_cents': p['fee_share_cents'],
        'status': p['status'],
    })
    return d
