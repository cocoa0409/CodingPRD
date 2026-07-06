"""Serializers strip internal fields (prefixed with _) from stored records."""


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def clinic(rec):
    return _public(rec)


def provider(rec):
    return _public(rec)


def patient(rec):
    return _public(rec)


def opioid_agreement(rec):
    return _public(rec)


def pdmp_check(rec):
    # Immutable audit record: only id + created_at (+ the payload fields).
    return _public(rec)


def treatment_plan(rec):
    return _public(rec)


def fluoroscopy_suite(rec):
    return _public(rec)


def procedure(rec):
    return _public(rec)


def prior_authorization(rec):
    return _public(rec)


def prescription(rec):
    return _public(rec)


def urine_drug_screen(rec):
    return _public(rec)


def pill_count_audit(rec):
    return _public(rec)


def ledger(rec):
    return _public(rec)
