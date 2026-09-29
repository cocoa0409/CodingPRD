"""Path resolution helpers shared by every blueprint (PRD 2.8)."""

from db import store
from errors import ApiError

_NOT_FOUND = {
    "insureds": "ERR_INSURED_NOT_FOUND",
    "submissions": "ERR_SUBMISSION_NOT_FOUND",
    "quotes": "ERR_QUOTE_NOT_FOUND",
    "exclusion_terms": "ERR_EXCLUSION_TERM_NOT_FOUND",
    "policies": "ERR_POLICY_NOT_FOUND",
    "layers": "ERR_LAYER_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "circumstance_reports": "ERR_CIRCUMSTANCE_REPORT_NOT_FOUND",
    "defense_invoices": "ERR_DEFENSE_INVOICE_NOT_FOUND",
    "settlement_proposals": "ERR_SETTLEMENT_PROPOSAL_NOT_FOUND",
}


def fetch(collection, record_id):
    record = getattr(store, collection).get(record_id)
    if record is None:
        raise ApiError(_NOT_FOUND[collection])
    return record


def get_insured(record_id):
    return fetch("insureds", record_id)


def get_submission(record_id):
    return fetch("submissions", record_id)


def get_quote(record_id):
    return fetch("quotes", record_id)


def get_term(record_id):
    return fetch("exclusion_terms", record_id)


def get_policy(record_id):
    return fetch("policies", record_id)


def get_layer(record_id):
    return fetch("layers", record_id)


def get_claim(record_id):
    return fetch("claims", record_id)


def get_report(record_id):
    return fetch("circumstance_reports", record_id)


def get_invoice(record_id):
    return fetch("defense_invoices", record_id)


def get_proposal(record_id):
    return fetch("settlement_proposals", record_id)


def insured_of_policy(policy):
    return store.insureds.get(policy["insured_id"])


def insured_of_submission(submission):
    return store.insureds.get(submission["insured_id"])


def insured_of_quote(quote):
    submission = store.submissions.get(quote["submission_id"])
    if submission is None:
        return None
    return store.insureds.get(submission["insured_id"])


def owning_insured_id_for_quote(quote):
    submission = store.submissions.get(quote["submission_id"])
    return None if submission is None else submission["insured_id"]


def owning_insured_id_for_term(term):
    quote = store.quotes.get(term["quote_id"])
    return None if quote is None else owning_insured_id_for_quote(quote)


def owning_insured_id_for_claim(claim):
    policy = store.policies.get(claim["policy_id"])
    return None if policy is None else policy["insured_id"]


def owning_insured_id_for_proposal(proposal):
    claim = store.claims.get(proposal["claim_id"])
    return None if claim is None else owning_insured_id_for_claim(claim)
