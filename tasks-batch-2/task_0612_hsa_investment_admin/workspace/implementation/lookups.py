"""Path-id resolution (PRD §2.7): validate identifiers left-to-right and reject
the first that does not resolve with ERR_NOT_FOUND (404). A child that exists
but does not belong to the parent named earlier in the path is ALSO not found.
This ordered check runs before any state or business rule.
"""
from db import db
from errors import err


def get_accountholder(holder_id):
    o = db.accountholders.get(holder_id)
    if o is None:
        raise err("ERR_NOT_FOUND", "Accountholder not found")
    return o


def get_employer(employer_id):
    o = db.employers.get(employer_id)
    if o is None:
        raise err("ERR_NOT_FOUND", "Employer not found")
    return o


def get_account(account_id):
    o = db.accounts.get(account_id)
    if o is None:
        raise err("ERR_NOT_FOUND", "HsaAccount not found")
    return o


def get_payroll_period(employer_id, pp_id):
    o = db.payroll_periods.get(pp_id)
    if o is None or o["employer_id"] != employer_id:
        raise err("ERR_NOT_FOUND", "PayrollPeriod not found")
    return o


def get_coverage_period(account_id, cp_id):
    o = db.coverage_periods.get(cp_id)
    if o is None or o["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "CoveragePeriod not found")
    return o


def get_contribution(account_id, contribution_id):
    o = db.contributions.get(contribution_id)
    if o is None or o["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "Contribution not found")
    return o


def get_sweep(account_id, sweep_id):
    o = db.investment_sweeps.get(sweep_id)
    if o is None or o["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "InvestmentSweep not found")
    return o


def get_distribution(account_id, distribution_id):
    o = db.distributions.get(distribution_id)
    if o is None or o["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "Distribution not found")
    return o


def get_card(account_id, card_id):
    o = db.debit_cards.get(card_id)
    if o is None or o["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "DebitCard not found")
    return o


def get_correction(account_id, correction_id):
    o = db.excess_corrections.get(correction_id)
    if o is None or o["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "ExcessCorrection not found")
    return o


def get_receipt(receipt_id):
    o = db.receipts.get(receipt_id)
    if o is None:
        raise err("ERR_NOT_FOUND", "Receipt not found")
    return o


def get_tax_form(account_id, tax_form_id):
    o = db.tax_forms.get(tax_form_id)
    if o is None or o["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", "TaxForm not found")
    return o


def assert_account_owner(account, user_id):
    """Holder-scoped writes (PRD §2.1): the acting Accountholder must own the
    HSA — account.accountholder_id == X-User-ID, else ERR_NOT_ACCOUNT_OWNER."""
    if account["accountholder_id"] != user_id:
        raise err("ERR_NOT_ACCOUNT_OWNER", "Acting accountholder does not own this HSA")
