"""Shared route helpers: existence lookups and Employer ownership scoping.

Existence checks raise ERR_NOT_FOUND (404). Per PRD §2.10 / §2.11, existence is
validated left-to-right after auth/authorization and before state/business rules.
"""
from __future__ import annotations

from typing import Dict, Any
from flask import g

import db
from errors import APIError, ERR_NOT_FOUND, ERR_UNAUTHORIZED


def _get_or_404(store: Dict[str, Dict[str, Any]], rid: str, label: str) -> Dict[str, Any]:
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{label} not found: {rid}")
    return obj


def get_employer(rid):
    return _get_or_404(db.employers, rid, "Employer")


def get_policy(rid):
    return _get_or_404(db.policies, rid, "Policy")


def get_worker(rid):
    return _get_or_404(db.workers, rid, "Worker")


def get_claim(rid):
    return _get_or_404(db.claims, rid, "Claim")


def get_injury_report(rid):
    return _get_or_404(db.injury_reports, rid, "InjuryReport")


def get_wage_statement(rid):
    return _get_or_404(db.wage_statements, rid, "WageStatement")


def get_benefit_payment(rid):
    return _get_or_404(db.benefit_payments, rid, "BenefitPayment")


def get_impairment_rating(rid):
    return _get_or_404(db.impairment_ratings, rid, "ImpairmentRating")


def get_rtw_offer(rid):
    return _get_or_404(db.rtw_offers, rid, "ReturnToWorkOffer")


def get_reserve(rid):
    return _get_or_404(db.reserves, rid, "Reserve")


def get_ime_order(rid):
    return _get_or_404(db.ime_orders, rid, "IMEOrder")


def get_experience_mod(rid):
    return _get_or_404(db.experience_mods, rid, "ExperienceModEntry")


# ----- Employer ownership scoping (PRD §2.1) --------------------------------

def employer_id_of_claim(claim: Dict[str, Any]) -> str:
    """Resolve a claim's owning employer transitively through its policy."""
    policy = db.policies.get(claim["policy_id"])
    if policy is None:
        return ""
    return policy.get("employer_id", "")


def assert_employer_owns_employer(employer_id: str) -> None:
    if g.user_role == "Employer" and g.user_id != employer_id:
        raise APIError(ERR_UNAUTHORIZED, 403, "Employer may only access its own resources")


def assert_employer_owns_claim(claim: Dict[str, Any]) -> None:
    if g.user_role == "Employer":
        if g.user_id != employer_id_of_claim(claim):
            raise APIError(ERR_UNAUTHORIZED, 403, "Employer may only access its own claims")
