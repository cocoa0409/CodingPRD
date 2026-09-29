"""Reconsideration evidence admissibility, decided once at filing."""

from services import constants as C
from services.appraisal import (distance_ceiling, eligible_comps, normalize_address,
                                whole_days)


def judge(evidence_type, street_address, sale_price_cents, sale_date, distance_miles,
          citation_note, appraisal, loan):
    """Clauses are evaluated in a pinned order; the first one that fires wins."""
    if evidence_type == "OPINION_STATEMENT":
        return False, "TYPE_NOT_ADMISSIBLE"

    if evidence_type in C.SALE_LIKE_EVIDENCE:
        if sale_price_cents is None or sale_date is None or distance_miles is None:
            return False, "MISSING_REQUIRED_ATTRIBUTE"
    else:
        if citation_note is None:
            return False, "MISSING_REQUIRED_ATTRIBUTE"
        return True, None

    if whole_days(sale_date, appraisal["effective_date"]) > C.STALE_SALE_DAYS:
        return False, "STALE_SALE_DATE"

    if distance_miles > distance_ceiling(loan):
        return False, "DISTANCE_EXCEEDED"

    normalized = normalize_address(street_address or "")
    for comp in eligible_comps(appraisal["id"]):
        if normalize_address(comp["street_address"]) == normalized:
            return False, "DUPLICATE_OF_GRID_COMP"

    return True, None
