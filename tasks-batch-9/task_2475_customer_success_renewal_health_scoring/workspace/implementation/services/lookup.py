"""Existence lookups.  Path parameters are resolved outermost first; body
foreign keys are resolved after path parameters and before schema validation."""
from db import db
from errors import ApiError

_NOT_FOUND = {
    'accounts': 'ERR_ACCOUNT_NOT_FOUND',
    'csms': 'ERR_CSM_NOT_FOUND',
    'coverage_assignments': 'ERR_COVERAGE_ASSIGNMENT_NOT_FOUND',
    'account_signals': 'ERR_SIGNAL_NOT_FOUND',
    'sponsor_contacts': 'ERR_SPONSOR_CONTACT_NOT_FOUND',
    'executive_engagements': 'ERR_EXECUTIVE_ENGAGEMENT_NOT_FOUND',
    'outcome_goals': 'ERR_OUTCOME_GOAL_NOT_FOUND',
    'onboarding_milestones': 'ERR_ONBOARDING_MILESTONE_NOT_FOUND',
    'save_plays': 'ERR_SAVE_PLAY_NOT_FOUND',
    'escalation_cases': 'ERR_ESCALATION_CASE_NOT_FOUND',
    'remediation_commitments': 'ERR_REMEDIATION_COMMITMENT_NOT_FOUND',
    'renewal_forecasts': 'ERR_RENEWAL_FORECAST_NOT_FOUND',
    'expansion_opportunities': 'ERR_EXPANSION_OPPORTUNITY_NOT_FOUND',
    'advocacy_enrollments': 'ERR_ADVOCACY_ENROLLMENT_NOT_FOUND',
}

_LABEL = {
    'accounts': 'Account',
    'csms': 'Csm',
    'coverage_assignments': 'CoverageAssignment',
    'account_signals': 'AccountSignal',
    'sponsor_contacts': 'SponsorContact',
    'executive_engagements': 'ExecutiveEngagement',
    'outcome_goals': 'OutcomeGoal',
    'onboarding_milestones': 'OnboardingMilestone',
    'save_plays': 'SavePlay',
    'escalation_cases': 'EscalationCase',
    'remediation_commitments': 'RemediationCommitment',
    'renewal_forecasts': 'RenewalForecast',
    'expansion_opportunities': 'ExpansionOpportunity',
    'advocacy_enrollments': 'AdvocacyEnrollment',
}


def fetch(collection, row_id):
    row = getattr(db, collection).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[collection],
                       '%s %s was not found.' % (_LABEL[collection], row_id))
    return row


def account(row_id):
    return fetch('accounts', row_id)


def csm(row_id):
    return fetch('csms', row_id)


def coverage_assignment(row_id):
    return fetch('coverage_assignments', row_id)


def sponsor_contact(row_id):
    return fetch('sponsor_contacts', row_id)


def executive_engagement(row_id):
    return fetch('executive_engagements', row_id)


def outcome_goal(row_id):
    return fetch('outcome_goals', row_id)


def onboarding_milestone(row_id):
    return fetch('onboarding_milestones', row_id)


def save_play(row_id):
    return fetch('save_plays', row_id)


def escalation_case(row_id):
    return fetch('escalation_cases', row_id)


def remediation_commitment(row_id):
    return fetch('remediation_commitments', row_id)


def renewal_forecast(row_id):
    return fetch('renewal_forecasts', row_id)


def expansion_opportunity(row_id):
    return fetch('expansion_opportunities', row_id)


def advocacy_enrollment(row_id):
    return fetch('advocacy_enrollments', row_id)
