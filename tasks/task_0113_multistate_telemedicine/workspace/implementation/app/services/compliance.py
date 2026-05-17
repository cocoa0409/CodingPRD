"""Prescription compliance score per §3.5 / scaffold prescription_compliance_score."""
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from app.store import store


def compute_compliance_score(
    *,
    routing_basis: Optional[str],
    dea_schedule: str,
    has_dea_number: bool,
    has_epcs_token: bool,
    refills: int,
    days_supply: int,
) -> int:
    score = 0

    # (a) Licensure leg.
    if routing_basis == "FULL_LICENSE":
        score += 40
    elif routing_basis == "IMLC_EXPEDITED":
        score += 30
    else:
        score += 0

    # (b) DEA leg.
    if dea_schedule == "NONE":
        score += 30
    elif dea_schedule != "NONE" and has_dea_number and has_epcs_token:
        score += 30
    else:
        score += 0

    # (c) Refill compliance leg.
    if dea_schedule == "II" and refills == 0:
        score += 20
    elif dea_schedule == "II" and refills > 0:
        score += 0
    elif dea_schedule in ("III", "IV") and refills <= 5:
        score += 20
    elif dea_schedule in ("III", "IV") and refills > 5:
        score += 10
    elif dea_schedule in ("V", "NONE"):
        score += 20

    # (d) Days-supply leg.
    if days_supply <= 30:
        score += 10
    elif days_supply <= 60:
        score += 5
    else:
        score += 0

    return score


def physician_aggregate_compliance(physician_id: str) -> Dict[str, Any]:
    """Return the average compliance score across this physician's qualifying Rx.

    Qualifying = status IN {ISSUED, TRANSMITTED, DISPENSED}.
    Rounded HALF_UP to one decimal place. When there are no qualifying Rx,
    returns 0.0 with prescription_count=0.
    """
    qualifying: List[Dict[str, Any]] = []
    for rx in store.prescriptions.values():
        if rx.get("prescribing_physician_id") != physician_id:
            continue
        if rx.get("status") not in {"ISSUED", "TRANSMITTED", "DISPENSED"}:
            continue
        qualifying.append(rx)

    if not qualifying:
        return {
            "physician_id": physician_id,
            "average_score": 0.0,
            "prescription_count": 0,
        }

    scores: List[int] = []
    for rx in qualifying:
        consult = store.consults.get(rx.get("consult_id", ""))
        routing_basis = (consult or {}).get("routing_basis")
        physician = store.physicians.get(physician_id)
        has_dea = bool((physician or {}).get("dea_number"))
        has_epcs = bool(rx.get("epcs_two_factor_token"))
        score = compute_compliance_score(
            routing_basis=routing_basis,
            dea_schedule=rx.get("dea_schedule", "NONE"),
            has_dea_number=has_dea,
            has_epcs_token=has_epcs,
            refills=int(rx.get("refills", 0)),
            days_supply=int(rx.get("days_supply", 0)),
        )
        scores.append(score)

    total = sum(scores)
    avg = Decimal(total) / Decimal(len(scores))
    rounded = avg.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return {
        "physician_id": physician_id,
        "average_score": float(rounded),
        "prescription_count": len(scores),
    }
