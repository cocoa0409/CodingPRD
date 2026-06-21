"""Serializers — strip private (_underscore) fields from response payloads."""
from __future__ import annotations


def _public(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def business_entity(be: dict) -> dict:
    return _public(be)


def operating_agreement(oa: dict) -> dict:
    return _public(oa)


def ein_application(ea: dict) -> dict:
    return _public(ea)


def registered_agent(ra: dict) -> dict:
    return _public(ra)


def annual_report(ar: dict) -> dict:
    return _public(ar)


def foreign_qualification(fq: dict) -> dict:
    return _public(fq)


def boi_disclosure(b: dict, boi_filing_deadline_iso: str = None) -> dict:
    out = _public(b)
    if boi_filing_deadline_iso is not None:
        out["boi_filing_deadline"] = boi_filing_deadline_iso
    return out


def compliance_event(ev: dict) -> dict:
    return _public(ev)
