"""Calculation rules (PRD §2.8, §2.9, §3.8 / SCAFFOLD §1.3)."""

from db import db

# --- risk_score constants (§1.3) ---------------------------------------------
MANDATORY_MISS_PENALTY = 25
SCORE_CEILING = 100
SCORE_FLOOR = 0

# --- clause_deviation_cost constants (§1.3 / §3.8) ---------------------------
BASE_CENTS = 50000
TIER1_RATE_CENTS = 10000
TIER2_RATE_CENTS = 7500
TIER3_RATE_CENTS = 5000


def _mandatory_template_ids(contract):
    """Clause-template ids the contract's ContractTemplate marks mandatory."""
    template = db.contract_templates.get(contract.get("contract_template_id"))
    if not template:
        return []
    mandatory = []
    for ct_id in template.get("clause_template_ids", []):
        ct = db.clause_templates.get(ct_id)
        if ct and ct.get("is_mandatory"):
            mandatory.append(ct_id)
    return mandatory


def compute_risk_score(contract, version, final=False):
    """Compute the weighted risk score over a version's clauses (PRD §2.8, §1.3).

    raw = sum of ClauseTemplate.risk_weight over clauses where is_deviation is True.
      - provisional (final=False): include all deviated clauses.
      - final (final=True): exclude deviated clauses that have a GRANTED
        DeviationApproval pinned to the contract's current version.
    mandatory_penalty = MANDATORY_MISS_PENALTY for each mandatory clause template
      the contract's template requires but that is absent from the version's clauses.
    score = clamp(raw + mandatory_penalty, 0, 100)  (sum first, then clamp).
    """
    if version is None:
        return 0

    clauses = version.get("clauses", []) or []

    granted_clause_ids = set()
    if final:
        for dev in db.deviation_approvals.values():
            if (
                dev.get("contract_id") == contract.get("id")
                and dev.get("status") == "GRANTED"
                and dev.get("contract_version_id") == contract.get("current_version_id")
            ):
                granted_clause_ids.add(dev.get("clause_template_id"))

    raw = 0
    present_template_ids = set()
    for clause in clauses:
        ct_id = clause.get("clause_template_id")
        present_template_ids.add(ct_id)
        if not clause.get("is_deviation"):
            continue
        if final and ct_id in granted_clause_ids:
            continue
        ct = db.clause_templates.get(ct_id)
        if ct:
            raw += int(ct.get("risk_weight") or 0)

    mandatory_penalty = 0
    for mand_id in _mandatory_template_ids(contract):
        if mand_id not in present_template_ids:
            mandatory_penalty += MANDATORY_MISS_PENALTY

    score = raw + mandatory_penalty
    if score < SCORE_FLOOR:
        score = SCORE_FLOOR
    if score > SCORE_CEILING:
        score = SCORE_CEILING
    return score


def review_cost_cents(deviation_count):
    """Marginal, tiered legal-review cost in integer cents (PRD §3.8, §1.3).

    Tiers on n = deviation_count:
      first 3 units at TIER1_RATE_CENTS,
      next 5 units (4th..8th) at TIER2_RATE_CENTS,
      9th onward at TIER3_RATE_CENTS.
    review_cost_cents = BASE_CENTS + marginal_sum.
    """
    n = int(deviation_count or 0)
    if n < 0:
        n = 0
    tier1 = min(n, 3)
    tier2 = min(max(n - 3, 0), 5)
    tier3 = max(n - 8, 0)
    marginal = (
        tier1 * TIER1_RATE_CENTS
        + tier2 * TIER2_RATE_CENTS
        + tier3 * TIER3_RATE_CENTS
    )
    return BASE_CENTS + marginal
