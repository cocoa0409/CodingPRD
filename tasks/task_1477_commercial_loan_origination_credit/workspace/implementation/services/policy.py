"""Policy exceptions: severity map, auto-creation, and the refresh rule.

Refresh semantics (PRD section 3.3): on an underwriting re-run while the
application is in EXCEPTION_REVIEW, each OPEN auto-created exception whose
triggering condition no longer holds moves to RESOLVED_BY_CHANGE; newly
triggered conditions create fresh exceptions; a WAIVED exception is never
resurrected.
"""
from db import STORE, new_entity, touch
from services.exposure import exceptions_of_app

HIGH_RULES = {
    "DSCR_MINIMUM",
    "SINGLE_BORROWER_LIMIT",
    "LTV_MAXIMUM",
    "COLLATERAL_COVERAGE_MIN",
    "COVENANT_BREACH",
}
LOW_RULES = {
    "STRESS_DSCR_MINIMUM",
    "REG_O_INSIDER",
    "REQUIRED_DOC_WAIVER",
}

RULE_CODES = HIGH_RULES | LOW_RULES


def severity_of(rule_code):
    return "HIGH" if rule_code in HIGH_RULES else "LOW"


def create_exception(app_id, rule_code, detail, condition_key):
    exc = new_entity()
    exc.update({
        'loan_application_id': app_id,
        'rule_code': rule_code,
        'severity': severity_of(rule_code),
        'status': 'OPEN',
        'detail': detail,
        'waived_by_officer_id': None,
        'waiver_rationale': None,
        '_condition_key': condition_key,
    })
    STORE.policy_exceptions[exc['id']] = exc
    return exc


def find_exception_by_key(app_id, condition_key):
    return [e for e in exceptions_of_app(app_id) if e.get('_condition_key') == condition_key]


def refresh_auto_exceptions(app_id, conditions):
    """conditions: iterable of (condition_key, rule_code, holds, detail).

    For each condition: if it holds and no OPEN/WAIVED exception exists for the
    key, create a fresh OPEN one (never resurrect WAIVED). If it does not hold
    and an OPEN one exists, resolve it RESOLVED_BY_CHANGE.
    """
    for key, rule_code, holds, detail in conditions:
        existing = find_exception_by_key(app_id, key)
        if holds:
            if not any(e['status'] in ('OPEN', 'WAIVED') for e in existing):
                create_exception(app_id, rule_code, detail, key)
        else:
            for e in existing:
                if e['status'] == 'OPEN':
                    e['status'] = 'RESOLVED_BY_CHANGE'
                    touch(e)


def resolve_open_exception_by_key(app_id, condition_key):
    for e in find_exception_by_key(app_id, condition_key):
        if e['status'] == 'OPEN':
            e['status'] = 'RESOLVED_BY_CHANGE'
            touch(e)


def waive_open_exception_by_key(app_id, condition_key, officer_id, rationale):
    for e in find_exception_by_key(app_id, condition_key):
        if e['status'] == 'OPEN':
            e['status'] = 'WAIVED'
            e['waived_by_officer_id'] = officer_id
            e['waiver_rationale'] = rationale
            touch(e)


def any_open_exception(app_id):
    return any(e['status'] == 'OPEN' for e in exceptions_of_app(app_id))


def any_open_high_exception(app_id):
    return any(e['status'] == 'OPEN' and e['severity'] == 'HIGH' for e in exceptions_of_app(app_id))


def any_high_exception_open_or_waived(app_id):
    return any(e['severity'] == 'HIGH' and e['status'] in ('OPEN', 'WAIVED')
               for e in exceptions_of_app(app_id))
