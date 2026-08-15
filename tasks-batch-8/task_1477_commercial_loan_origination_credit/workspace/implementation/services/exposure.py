"""Exposure ledger, hold reconciliation, and collateral aggregates.

All of these are derived from live state on every read (PRD: the system
computes rather than trusts; the conservation invariants fall out of the
formulas).
"""
from db import STORE


def applications_of_borrower(borrower_id):
    return [a for a in STORE.loan_applications.values() if a['borrower_id'] == borrower_id]


def statements_of_app(app_id):
    return [s for s in STORE.financial_statements.values() if s['loan_application_id'] == app_id]


def exceptions_of_app(app_id):
    return [e for e in STORE.policy_exceptions.values() if e['loan_application_id'] == app_id]


def appraisals_of_app(app_id):
    return [a for a in STORE.appraisals.values() if a['loan_application_id'] == app_id]


def term_sheets_of_app(app_id):
    return [t for t in STORE.term_sheets.values() if t['loan_application_id'] == app_id]


def letters_of_app(app_id):
    return [l for l in STORE.commitment_letters.values() if l['loan_application_id'] == app_id]


def letter_for_app(app_id):
    """The application's commitment letter (at most one can ever exist)."""
    letters = letters_of_app(app_id)
    if not letters:
        return None
    return max(letters, key=lambda l: l['_seq'])


def checklist_items_of_app(app_id):
    return [i for i in STORE.document_checklist_items.values() if i['loan_application_id'] == app_id]


def fundings_of_app(app_id):
    return [f for f in STORE.funding_authorizations.values() if f['loan_application_id'] == app_id]


def covenants_of_app(app_id):
    return [c for c in STORE.covenants.values() if c['loan_application_id'] == app_id]


def participations_of_app(app_id):
    return [p for p in STORE.participations.values() if p['loan_application_id'] == app_id]


def decisions_of_app(app_id):
    return [d for d in STORE.committee_decisions.values() if d['loan_application_id'] == app_id]


# --- exposure ledger (calculations.exposure_ledger) ---

def app_funded_amount_cents(app_id):
    return sum(f['amount_cents'] for f in fundings_of_app(app_id) if f['status'] == 'RELEASED')


def borrower_committed_exposure_cents(borrower_id):
    total = 0
    for app in applications_of_borrower(borrower_id):
        letter = letter_for_app(app['id'])
        if letter is not None and letter['status'] in ('ACCEPTED', 'FUNDED'):
            total += letter['committed_amount_cents'] - app_funded_amount_cents(app['id'])
    return total


def borrower_funded_exposure_cents(borrower_id):
    total = 0
    for app in applications_of_borrower(borrower_id):
        total += app_funded_amount_cents(app['id'])
    return total


def borrower_total_exposure_cents(borrower_id):
    return borrower_committed_exposure_cents(borrower_id) + borrower_funded_exposure_cents(borrower_id)


# --- participation hold reconciliation (calculations.participation_hold_reconciliation) ---

def allocated_participation_cents(app_id):
    return sum(p['allocated_amount_cents'] for p in participations_of_app(app_id)
               if p['status'] in ('PROPOSED', 'COMMITTED', 'FUNDED'))


def bank_hold_amount_cents(app_id):
    letter = letter_for_app(app_id)
    if letter is None:
        return 0
    return letter['committed_amount_cents'] - allocated_participation_cents(app_id)


def bank_hold_fee_cents(app_id):
    letter = letter_for_app(app_id)
    if letter is None:
        return None
    shares = sum(p['fee_share_cents'] for p in participations_of_app(app_id)
                 if p['status'] in ('COMMITTED', 'FUNDED') and p['fee_share_cents'] is not None)
    return letter['origination_fee_cents'] - shares


# --- collateral aggregates (over ACCEPTED appraisals) ---

def collateral_aggregates(app_id):
    accepted = [a for a in appraisals_of_app(app_id) if a['status'] == 'ACCEPTED']
    total_appraised = sum(a['appraised_value_cents'] for a in accepted)
    total_eligible = sum(a['eligible_value_cents'] for a in accepted)
    total_liquidation = sum(a['liquidation_basis_value_cents'] for a in accepted)
    return total_appraised, total_eligible, total_liquidation
