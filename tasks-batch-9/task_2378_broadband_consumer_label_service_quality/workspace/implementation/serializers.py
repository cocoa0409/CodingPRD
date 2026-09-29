"""Resource serialisation.

Every stored key is an entity field of the PRD except the internal
underscore-prefixed bookkeeping keys, which are never emitted.
"""

import copy

from services import calculations as calc


def _public(record):
    return {key: copy.deepcopy(value) for key, value in record.items()
            if not key.startswith("_")}


def service_plan(record):
    return _public(record)


def fee_line_item(record):
    return _public(record)


def methodology_document(record):
    return _public(record)


def measurement_probe(record):
    return _public(record)


def test_run(record):
    return _public(record)


def attestation(record):
    return _public(record)


def label_version(record):
    return _public(record)


def label_translation(record):
    return _public(record)


def subscriber_account(record):
    """`pricing_phase` is derived on every read (PRD §3.7)."""
    data = _public(record)
    data["pricing_phase"] = calc.account_pricing_phase(record)
    return data


def label_disclosure(record):
    """Immutable audit event: no updated_at, no version (PRD §2.5)."""
    return _public(record)


def complaint(record):
    return _public(record)


def remediation_credit(record):
    return _public(record)


def regulator_inquiry(record):
    return _public(record)


def plan_change_notice(record):
    return _public(record)
