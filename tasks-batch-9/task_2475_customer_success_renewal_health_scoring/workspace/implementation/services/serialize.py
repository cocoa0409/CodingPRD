"""Row -> JSON projections."""
from decimal import Decimal


def _score(value):
    """A score field always carries exactly two decimal places."""
    if value is None:
        return None
    return float(Decimal(value).quantize(Decimal('0.01')))


def _number(value):
    """A plain numeric field keeps its natural shape."""
    if value is None:
        return None
    dec = Decimal(value)
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _common(row):
    return {
        'id': row['id'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
        'version': row['version'],
    }


def account(row):
    out = {
        'name': row['name'],
        'arr_cents': row['arr_cents'],
        'segment_band': row['segment_band'],
        'contract_start_date': row['contract_start_date'],
        'contract_end_date': row['contract_end_date'],
        'lifecycle_state': row['lifecycle_state'],
        'adoption_index': _score(row['adoption_index']),
        'support_risk_penalty': _score(row['support_risk_penalty']),
        'exec_engagement_score': _score(row['exec_engagement_score']),
        'outcome_attainment_index': _score(row['outcome_attainment_index']),
        'snapshot_health_score': _score(row['snapshot_health_score']),
        'trended_health_score': _score(row['trended_health_score']),
        'health_tier': row['health_tier'],
        'coverage_tier': row['coverage_tier'],
        'coverage_posture': row['coverage_posture'],
        'assigned_csm_id': row['assigned_csm_id'],
        'open_save_play_count': row['open_save_play_count'],
        'ttv_breach_flag': row['ttv_breach_flag'],
        'contractual_ttv_days': row['contractual_ttv_days'],
        'activation_ttv_days': row['activation_ttv_days'],
        'renewal_likelihood': row['renewal_likelihood'],
        'churn_root_cause_code': row['churn_root_cause_code'],
        'win_back_offer_bp': row['win_back_offer_bp'],
        'remediation_credit_outstanding_cents': row['remediation_credit_outstanding_cents'],
        'remediation_credit_settled_cents': row['remediation_credit_settled_cents'],
        'reference_calls_cap': row['reference_calls_cap'],
    }
    out.update(_common(row))
    return out


def csm(row):
    out = {
        'full_name': row['full_name'],
        'coverage_specialty': row['coverage_specialty'],
        'capacity_units_total': row['capacity_units_total'],
        'capacity_units_committed': row['capacity_units_committed'],
        'capacity_units_available': row['capacity_units_available'],
        'status': row['status'],
    }
    out.update(_common(row))
    return out


def coverage_assignment(row):
    out = {
        'account_id': row['account_id'],
        'csm_id': row['csm_id'],
        'coverage_tier': row['coverage_tier'],
        'load_units': row['load_units'],
        'state': row['state'],
        'committed_at': row['committed_at'],
        'released_at': row['released_at'],
        'release_reason': row['release_reason'],
        'superseded_by_assignment_id': row['superseded_by_assignment_id'],
    }
    out.update(_common(row))
    return out


def account_signal(row):
    return {
        'id': row['id'],
        'created_at': row['created_at'],
        'account_id': row['account_id'],
        'signal_kind': row['signal_kind'],
        'period_end_date': row['period_end_date'],
        'weekly_active_users': row['weekly_active_users'],
        'licensed_seats': row['licensed_seats'],
        'feature_depth_pct': _number(row['feature_depth_pct']),
        'seat_utilisation_pct': _score(row['seat_utilisation_pct']),
        'usage_row_index': _score(row['usage_row_index']),
        'ticket_severity': row['ticket_severity'],
        'opened_at': row['opened_at'],
        'resolved_at': row['resolved_at'],
        'breached_sla': row['breached_sla'],
        'csat_score': row['csat_score'],
        'penalty_points': (int(row['penalty_points'])
                           if row['penalty_points'] is not None else None),
    }


def sponsor_contact(row):
    out = {
        'account_id': row['account_id'],
        'full_name': row['full_name'],
        'seniority': row['seniority'],
        'is_economic_buyer': row['is_economic_buyer'],
        'status': row['status'],
    }
    out.update(_common(row))
    return out


def executive_engagement(row):
    out = {
        'account_id': row['account_id'],
        'sponsor_contact_id': row['sponsor_contact_id'],
        'engagement_type': row['engagement_type'],
        'start_at': row['start_at'],
        'end_at': row['end_at'],
        'state': row['state'],
        'outcome_recorded_at': row['outcome_recorded_at'],
    }
    out.update(_common(row))
    return out


def outcome_goal(row):
    out = {
        'account_id': row['account_id'],
        'title': row['title'],
        'target_value': _number(row['target_value']),
        'actual_value': _number(row['actual_value']),
        'weight_bp': row['weight_bp'],
        'status': row['status'],
        'attainment_pct': _score(row['attainment_pct']),
    }
    out.update(_common(row))
    return out


def onboarding_milestone(row):
    out = {
        'account_id': row['account_id'],
        'milestone_code': row['milestone_code'],
        'sequence_index': row['sequence_index'],
        'due_date': row['due_date'],
        'completed_date': row['completed_date'],
        'state': row['state'],
        'days_late': row['days_late'],
    }
    out.update(_common(row))
    return out


def save_play(row):
    out = {
        'account_id': row['account_id'],
        'owner_csm_id': row['owner_csm_id'],
        'risk_code': row['risk_code'],
        'play_type': row['play_type'],
        'window_start_date': row['window_start_date'],
        'window_end_date': row['window_end_date'],
        'state': row['state'],
        'outcome_note': row['outcome_note'],
    }
    out.update(_common(row))
    return out


def escalation_case(row):
    out = {
        'account_id': row['account_id'],
        'save_play_id': row['save_play_id'],
        'severity': row['severity'],
        'summary': row['summary'],
        'state': row['state'],
        'remediation_round': row['remediation_round'],
        'final_credit_cents': row['final_credit_cents'],
    }
    out.update(_common(row))
    return out


def remediation_commitment(row):
    out = {
        'escalation_case_id': row['escalation_case_id'],
        'description': row['description'],
        'due_date': row['due_date'],
        'credit_cents': row['credit_cents'],
        'state': row['state'],
        'round_index': row['round_index'],
        'accepted_by_user_id': row['accepted_by_user_id'],
        'delivered_by_user_id': row['delivered_by_user_id'],
    }
    out.update(_common(row))
    return out


def renewal_forecast(row):
    out = {
        'account_id': row['account_id'],
        'fiscal_period': row['fiscal_period'],
        'cs_amount_cents': row['cs_amount_cents'],
        'finance_amount_cents': row['finance_amount_cents'],
        'variance_cents': row['variance_cents'],
        'likelihood_category': row['likelihood_category'],
        'cs_state': row['cs_state'],
        'finance_state': row['finance_state'],
        'submitted_at': row['submitted_at'],
        'reconciled_at': row['reconciled_at'],
    }
    out.update(_common(row))
    return out


def expansion_opportunity(row):
    out = {
        'account_id': row['account_id'],
        'recycled_from_opportunity_id': row['recycled_from_opportunity_id'],
        'estimated_value_cents': row['estimated_value_cents'],
        'source_signal': row['source_signal'],
        'qualification_score': _score(row['qualification_score']),
        'state': row['state'],
        'handoff_ae_user_id': row['handoff_ae_user_id'],
        'rejection_reason': row['rejection_reason'],
        'identified_at': row['identified_at'],
    }
    out.update(_common(row))
    return out


def advocacy_enrollment(row):
    out = {
        'account_id': row['account_id'],
        'program_type': row['program_type'],
        'state': row['state'],
        'reference_calls_used': row['reference_calls_used'],
        'reference_calls_cap': row['reference_calls_cap'],
        'last_reference_call_at': row['last_reference_call_at'],
    }
    out.update(_common(row))
    return out
