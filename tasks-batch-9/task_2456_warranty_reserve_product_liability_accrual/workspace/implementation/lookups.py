"""Existence resolution helpers (PRD §2.9 rungs 4 and 6).

Path identifiers are resolved strictly left to right; the error belonging to the
first unresolvable segment is returned.
"""

import store
from errors import fail

_NOT_FOUND = {
    "periods": "ERR_PERIOD_NOT_FOUND",
    "families": "ERR_FAMILY_NOT_FOUND",
    "vintages": "ERR_VINTAGE_NOT_FOUND",
    "failure_modes": "ERR_FAILURE_MODE_NOT_FOUND",
    "observations": "ERR_CLAIM_OBSERVATION_NOT_FOUND",
    "accruals": "ERR_ACCRUAL_NOT_FOUND",
    "adequacy_reviews": "ERR_ADEQUACY_REVIEW_NOT_FOUND",
    "field_actions": "ERR_FIELD_ACTION_NOT_FOUND",
    "remedy_options": "ERR_REMEDY_OPTION_NOT_FOUND",
    "service_contracts": "ERR_SERVICE_CONTRACT_NOT_FOUND",
    "suppliers": "ERR_SUPPLIER_NOT_FOUND",
    "recoveries": "ERR_RECOVERY_NOT_FOUND",
    "liability_reserves": "ERR_LIABILITY_RESERVE_NOT_FOUND",
    "rollforwards": "ERR_ROLLFORWARD_NOT_FOUND",
}


def require(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        fail(_NOT_FOUND[collection])
    return row


def find(collection, row_id):
    return store.get(collection, row_id)


def require_period(row_id):
    return require("periods", row_id)


def require_family(row_id):
    return require("families", row_id)


def require_vintage(row_id):
    return require("vintages", row_id)


def require_failure_mode(row_id):
    return require("failure_modes", row_id)


def require_field_action(row_id):
    return require("field_actions", row_id)


def require_supplier(row_id):
    return require("suppliers", row_id)


def period_by_code(code):
    for period in store.all_rows("periods"):
        if period["period_code"] == code:
            return period
    return None
