"""Resource projection helpers — strip internal fields and reproject for API output."""

from __future__ import annotations

from typing import Any


def _strip(record: dict, *extras: str) -> dict:
    """Return a copy of `record` without internal `_seq` fields and any extras."""
    skip = {"_seq", *extras}
    return {k: v for k, v in record.items() if k not in skip}


def serialize_department(d: dict) -> dict:
    return _strip(d)


def serialize_matter(m: dict) -> dict:
    return _strip(m)


def serialize_matter_version(v: dict) -> dict:
    return _strip(v)


def serialize_material_template(t: dict) -> dict:
    return _strip(t)


def serialize_certificate_template(t: dict) -> dict:
    return _strip(t)


def serialize_application(a: dict, *, sla: dict | None = None,
                          fee: dict | None = None) -> dict:
    out = _strip(a)
    if sla is not None:
        out["sla"] = sla
    if fee is not None:
        out["fee_breakdown"] = fee
    return out


def serialize_review_task(t: dict) -> dict:
    return _strip(t)


def serialize_correction_notice(n: dict) -> dict:
    return _strip(n)


def serialize_certificate(c: dict) -> dict:
    return _strip(c)


def serialize_external_event(e: dict) -> dict:
    return _strip(e)


def serialize_audit_log(a: dict) -> dict:
    return _strip(a)
