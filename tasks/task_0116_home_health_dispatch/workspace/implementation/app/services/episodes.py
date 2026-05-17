"""Episode lifecycle: open, close, expire — and the paired-claim side effects.

Encapsulates the cross-entity cascades that the route handlers invoke:
- on Episode OPEN: derive computed fields, create paired PDGMClaim, compute
  provisional payment.
- on Episode CLOSED: recompute final payment + LUPA + mileage aggregation,
  finalize the claim.
- on Episode EXPIRED (sweep): cancel SCHEDULED visits, finalize the claim
  using provisional payment.
"""
from decimal import Decimal
from typing import Tuple

from ..clock import add_days, parse_date
from ..errors import APIError
from ..store import get_store, new_id, real_now_iso, stamp_create, stamp_update
from . import calculations as calc


# ----- timing category derivation ----------------------------------------

def _patient_prior_episode_chain(patient_id: str) -> list:
    """Return all episodes for a patient ordered by start_date ascending."""
    eps = [e for e in get_store().episodes.values() if e["patient_id"] == patient_id]
    eps.sort(key=lambda e: (e["start_date"], e["created_at"]))
    return eps


def _timing_category(patient_id: str, episode_type: str) -> str:
    """INITIAL -> EARLY. RECERT/ROC -> LATE if patient's chain has any EARLY."""
    if episode_type == "INITIAL":
        return "EARLY"
    # RECERT / ROC
    chain = _patient_prior_episode_chain(patient_id)
    for e in chain:
        if e.get("timing_category") == "EARLY":
            return "LATE"
    # No prior EARLY episode in chain — defensive default.
    return "LATE"


def _episode_type_from_reason(reason: str) -> str:
    return {
        "START_OF_CARE": "INITIAL",
        "RECERTIFICATION": "RECERT",
        "RESUMPTION_OF_CARE": "ROC",
    }[reason]


# ----- core: open --------------------------------------------------------

def open_episode_from_oasis(patient: dict, oasis: dict, *, now: str) -> Tuple[dict, dict]:
    """Atomically: create Episode (OPEN) + PDGMClaim (PENDING) with provisional payment.

    Caller has already verified RBAC, existence, OASIS LOCKED status, and the
    no-duplicate-use / no-open-episode constraints. This function is the side
    effect path described in SCAFFOLD §1.2 (Episode null -> OPEN).
    """
    store = get_store()

    episode_type = _episode_type_from_reason(oasis["assessment_reason"])

    # start_date: assessment_date for INITIAL/ROC, prior_end_date + 1 for RECERT.
    if episode_type == "RECERT":
        # The most recent prior episode for this patient determines start_date.
        chain = _patient_prior_episode_chain(patient["id"])
        if not chain:
            raise APIError(
                "ERR_RECERT_WINDOW_VIOLATION",
                "RECERT episode requires a prior episode in the patient's chain",
            )
        prior = chain[-1]
        start_date = add_days(prior["end_date"], 1)
    else:
        start_date = oasis["assessment_date"]

    end_date = add_days(start_date, 59)
    recert_due_date = add_days(end_date, -4)
    timing_category = _timing_category(patient["id"], episode_type)

    episode = {
        "id": new_id(),
        "patient_id": patient["id"],
        "source_oasis_id": oasis["id"],
        "episode_type": episode_type,
        "start_date": start_date,
        "end_date": end_date,
        "timing_category": timing_category,
        "recert_due_date": recert_due_date,
        "status": "OPEN",
    }
    stamp_create(episode, now=now)
    store.episodes[episode["id"]] = episode

    # Paired PDGMClaim.
    wage_index = patient["wage_index"]
    cmw = calc.lookup_case_mix_weight(
        timing_category,
        oasis["clinical_grouping"],
        oasis["functional_impairment_level"],
        oasis["admission_source"],
    )
    hipps = calc.hipps_code(
        timing_category,
        oasis["clinical_grouping"],
        oasis["functional_impairment_level"],
        oasis["admission_source"],
    )
    provisional = calc.case_mix_payment(wage_index, cmw)

    claim = {
        "id": new_id(),
        "episode_id": episode["id"],
        "hipps_code": hipps,
        "case_mix_weight": cmw,
        "provisional_payment": provisional,
        "final_payment": None,
        "lupa_applied": None,
        "total_mileage_reimbursement": Decimal("0.00"),
        "status": "PENDING",
    }
    stamp_create(claim, now=now)
    store.pdgm_claims[claim["id"]] = claim

    return episode, claim


# ----- close / expire helpers --------------------------------------------

def _claim_for_episode(episode_id: str) -> dict:
    store = get_store()
    for c in store.pdgm_claims.values():
        if c["episode_id"] == episode_id:
            return c
    raise APIError("ERR_NOT_FOUND", f"No claim for episode {episode_id}")


def _completed_visits_chronological(episode_id: str) -> list:
    store = get_store()
    visits = [
        v for v in store.visits.values()
        if v["episode_id"] == episode_id and v["status"] == "COMPLETED"
    ]
    visits.sort(key=lambda v: (v["visit_date"], v["start_minute"], v["id"]))
    return visits


def _mileage_total_for_completed(episode_id: str) -> Decimal:
    store = get_store()
    completed_visit_ids = {
        v["id"] for v in store.visits.values()
        if v["episode_id"] == episode_id and v["status"] == "COMPLETED"
    }
    amounts = [
        m["reimbursement_amount"]
        for m in store.mileage_logs.values()
        if m["visit_id"] in completed_visit_ids
    ]
    return calc.aggregate_mileage(amounts)


def close_episode(episode: dict, *, now: str) -> dict:
    """Episode OPEN -> CLOSED side effect: finalize PDGMClaim per §3.7."""
    store = get_store()
    claim = _claim_for_episode(episode["id"])

    patient = store.patients.get(episode["patient_id"])
    wage_index = patient["wage_index"] if patient else Decimal("1.0000")
    cmw = claim["case_mix_weight"]

    completed = _completed_visits_chronological(episode["id"])
    count = len(completed)

    if calc.is_lupa(count):
        final = calc.lupa_payment(wage_index, completed)
        lupa_applied = True
    else:
        final = calc.case_mix_payment(wage_index, cmw)
        lupa_applied = False

    total_mileage = _mileage_total_for_completed(episode["id"])

    claim["final_payment"] = final
    claim["lupa_applied"] = lupa_applied
    claim["total_mileage_reimbursement"] = total_mileage
    claim["status"] = "FINALIZED"
    stamp_update(claim, now=now)

    episode["status"] = "CLOSED"
    stamp_update(episode, now=now)

    return claim


def expire_episode(episode: dict, *, now: str) -> dict:
    """Episode OPEN -> EXPIRED via sweep. Cascade: cancel SCHEDULED visits,
    finalize claim with final = provisional, lupa_applied = false, mileage from
    already-COMPLETED visits.
    """
    store = get_store()
    claim = _claim_for_episode(episode["id"])

    # 1) Cancel SCHEDULED visits on this episode.
    for v in store.visits.values():
        if v["episode_id"] == episode["id"] and v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            stamp_update(v, now=now)

    # 2) Finalize claim using provisional payment + already-COMPLETED mileage.
    total_mileage = _mileage_total_for_completed(episode["id"])

    claim["final_payment"] = claim["provisional_payment"]
    claim["lupa_applied"] = False
    claim["total_mileage_reimbursement"] = total_mileage
    claim["status"] = "FINALIZED"
    stamp_update(claim, now=now)

    # 3) Transition episode.
    episode["status"] = "EXPIRED"
    stamp_update(episode, now=now)

    return claim


# ----- validation helpers ------------------------------------------------

def episode_can_close(episode: dict, current_date_iso: str) -> None:
    """Raise APIError if episode is not eligible to close."""
    # Precondition: ClockState.current_date >= end_date.
    if parse_date(current_date_iso) < parse_date(episode["end_date"]):
        raise APIError(
            "ERR_EPISODE_NOT_OPEN",
            "Episode end_date has not yet been reached on the clock",
        )
    # Precondition: zero SCHEDULED visits.
    store = get_store()
    for v in store.visits.values():
        if v["episode_id"] == episode["id"] and v["status"] == "SCHEDULED":
            raise APIError(
                "ERR_EPISODE_NOT_OPEN",
                "Episode has SCHEDULED visits and cannot be closed",
            )


def episode_eligible_for_expire(episode: dict, current_date_iso: str) -> bool:
    """ClockState.current_date > Episode.end_date + 7 AND status == OPEN."""
    if episode["status"] != "OPEN":
        return False
    cutoff = add_days(episode["end_date"], 7)
    return parse_date(current_date_iso) > parse_date(cutoff)
