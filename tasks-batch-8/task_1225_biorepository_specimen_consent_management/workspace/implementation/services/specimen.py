"""Specimen volume accounting and consent scope helpers."""
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import now
from errors import raise_error
from services.common import touch

BOOK_STATUSES = {"RESERVED", "DESTRUCTION_PENDING", "DISTRIBUTED", "DESTROYED"}
PHYSICAL_STATUSES = {"DISTRIBUTED", "DESTROYED"}


def recompute_volumes(specimen, bump_version=True):
    """Recompute residual / committed volumes for a specimen from its aliquots."""
    residual = Decimal(str(specimen["initial_volume_ml"]))
    book = Decimal("0")
    physical = Decimal("0")
    for a in db.aliquots.values():
        if a["specimen_id"] != specimen["id"]:
            continue
        if a["status"] == "VOID":
            continue
        residual -= Decimal(str(a["initial_volume_ml"]))
        if a["status"] in BOOK_STATUSES:
            book += Decimal(str(a["initial_volume_ml"]))
        if a["status"] in PHYSICAL_STATUSES:
            physical += Decimal(str(a["initial_volume_ml"]))
    q = Decimal("0.001")
    specimen["residual_volume_ml"] = float(residual.quantize(q, rounding=ROUND_HALF_UP))
    specimen["committed_volume_book_ml"] = float(book.quantize(q, rounding=ROUND_HALF_UP))
    specimen["committed_volume_physical_ml"] = float(physical.quantize(q, rounding=ROUND_HALF_UP))
    if bump_version:
        touch(specimen)


def consent_is_effective(consent):
    return consent["status"] == "ACTIVE" and now() >= consent["effective_from"]


def require_consent_active(consent):
    if not consent_is_effective(consent):
        raise_error("ERR_CONSENT_NOT_ACTIVE", "Consent is not ACTIVE or not yet effective")


def scope_covers(consent, required_uses):
    permitted = set(consent["permitted_uses"])
    excluded = set(consent["excluded_uses"])
    required = set(required_uses)
    return required.issubset(permitted) and required.isdisjoint(excluded)


def aliquots_of_specimen(specimen_id):
    return [a for a in db.aliquots.values() if a["specimen_id"] == specimen_id]
