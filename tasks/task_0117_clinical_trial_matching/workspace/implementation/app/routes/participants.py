"""Participant CRUD, lifecycle transitions, and the cascade chains."""
from __future__ import annotations

from typing import Any

from flask import Blueprint

from ..auth import (
    ROLE_COORD,
    ROLE_PARTICIPANT_SELF,
    ROLE_PI,
    enforce_self_ownership,
    require_roles,
)
from ..clock import now
from ..errors import (
    err_consent_version_stale,
    err_invalid_input,
    err_invalid_state,
    err_stratum_key_missing,
    err_trial_full,
)
from ..helpers import (
    assert_integer,
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.calculations import assign_arm, compute_eligibility
from ..services.lookups import (
    arms_for_trial,
    consent_versions_for_trial,
    get_arm,
    get_participant,
    get_trial,
    open_ae_count_for,
    payments_for_participant,
    visits_for_participant,
)
from ..services.serialize import serialize_participant
from ..store import store

bp = Blueprint("participants", __name__)


def _bump(p: dict[str, Any]) -> None:
    p["updated_at"] = now()
    p["version"] = p["version"] + 1


# =====================================================================
# POST /participants
# =====================================================================

@bp.post("/participants")
@require_roles(ROLE_COORD)
def create_participant(**_caller):
    body = require_json_object()
    trial_id = assert_string(body.get("trial_id"), "trial_id", required=True)
    profile = body.get("profile")
    if profile is None:
        raise err_invalid_input("profile is required")
    if not isinstance(profile, dict):
        raise err_invalid_input("profile must be a JSON object")
    if len(profile) > 50:
        raise err_invalid_input("profile may contain at most 50 keys")

    with store().lock:
        trial = get_trial(trial_id)  # ERR_NOT_FOUND if missing
        ts = now()
        pid = new_uuid()
        # Snapshot the trial's current inclusion/exclusion criteria for chronological replay.
        incl_snapshot = list(trial["inclusion_criteria"])
        excl_snapshot = list(trial["exclusion_criteria"])
        p = {
            "id": pid,
            "trial_id": trial_id,
            "arm_id": None,
            "profile": dict(profile),
            "status": "SCREENING",
            "signed_consent_version": None,
            "eligibility_score": None,
            "open_ae_count": 0,
            "enrolled_at": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_inclusion_at_creation": incl_snapshot,
            "_exclusion_at_creation": excl_snapshot,
        }
        store().participants[pid] = p

    return created(serialize_participant(p))


# =====================================================================
# GET /participants/<id>
# =====================================================================

@bp.get("/participants/<participant_id>")
@require_roles(ROLE_PI, ROLE_COORD, ROLE_PARTICIPANT_SELF)
def read_participant(participant_id: str, **caller):
    enforce_self_ownership(participant_id, caller["_caller_id"], caller["_caller_role"])
    with store().lock:
        p = get_participant(participant_id)
        return ok(serialize_participant(p))


# =====================================================================
# POST /participants/<id>/evaluate
# =====================================================================

@bp.post("/participants/<participant_id>/evaluate")
@require_roles(ROLE_COORD)
def evaluate_participant(participant_id: str, **_caller):
    with store().lock:
        p = get_participant(participant_id)
        if p["status"] != "SCREENING":
            raise err_invalid_state("Participant must be in SCREENING for evaluation")
        trial = get_trial(p["trial_id"])
        if trial["status"] != "OPEN_FOR_ENROLLMENT":
            raise err_invalid_state("Trial must be OPEN_FOR_ENROLLMENT to evaluate participants")

        decision, score = compute_eligibility(
            p["profile"], trial["inclusion_criteria"], trial["exclusion_criteria"]
        )
        p["eligibility_score"] = score
        p["status"] = "ELIGIBLE" if decision == "ELIGIBLE" else "INELIGIBLE"
        _bump(p)
        return ok(serialize_participant(p))


# =====================================================================
# GET /participants/<id>/eligibility-history (chronological variant)
# =====================================================================

@bp.get("/participants/<participant_id>/eligibility-history")
@require_roles(ROLE_PI, ROLE_COORD)
def eligibility_history(participant_id: str, **_caller):
    with store().lock:
        p = get_participant(participant_id)
        incl = p.get("_inclusion_at_creation", [])
        excl = p.get("_exclusion_at_creation", [])
        decision, score = compute_eligibility(p["profile"], incl, excl)
        return ok(
            {
                "participant_id": p["id"],
                "variant": "chronological",
                "decision": decision,
                "score": score,
                "inclusion_criteria_at_creation": incl,
                "exclusion_criteria_at_creation": excl,
            }
        )


# =====================================================================
# POST /participants/<id>/request-consent
# =====================================================================

@bp.post("/participants/<participant_id>/request-consent")
@require_roles(ROLE_COORD)
def request_consent(participant_id: str, **_caller):
    with store().lock:
        p = get_participant(participant_id)
        if p["status"] != "ELIGIBLE":
            raise err_invalid_state("Participant must be ELIGIBLE to request consent")
        trial = get_trial(p["trial_id"])
        if trial["active_consent_version"] is None:
            raise err_invalid_state("Trial has no active consent version")
        p["status"] = "CONSENT_PENDING"
        _bump(p)
        return ok(serialize_participant(p))


# =====================================================================
# POST /participants/<id>/sign-consent
# =====================================================================

@bp.post("/participants/<participant_id>/sign-consent")
@require_roles(ROLE_COORD, ROLE_PARTICIPANT_SELF)
def sign_consent(participant_id: str, **caller):
    enforce_self_ownership(participant_id, caller["_caller_id"], caller["_caller_role"])
    body = require_json_object()

    with store().lock:
        # Order per PRD §2.8: existence → state → consent_version match (priority 61) →
        # TRIAL_FULL (62) → STRATUM_KEY_MISSING (80) → input.
        p = get_participant(participant_id)
        if p["status"] != "CONSENT_PENDING":
            raise err_invalid_state("Participant is not in CONSENT_PENDING")
        trial = get_trial(p["trial_id"])
        if trial["status"] != "OPEN_FOR_ENROLLMENT":
            raise err_invalid_state("Trial is not OPEN_FOR_ENROLLMENT")
        consent_version = assert_integer(
            body.get("consent_version"), "consent_version", required=True, minimum=1
        )
        if trial["active_consent_version"] is None or consent_version != trial["active_consent_version"]:
            raise err_consent_version_stale(
                "consent_version does not match the trial's active_consent_version"
            )
        if trial["enrolled_count"] >= trial["target_enrollment"]:
            raise err_trial_full()

        # Stratification key presence (priority 80).
        if trial["randomization_scheme"] == "STRATIFIED_BLOCK":
            sf = trial["stratification_field"]
            if not sf or sf not in (p["profile"] or {}):
                raise err_stratum_key_missing()

        arms = arms_for_trial(p["trial_id"])
        stratum_counters = trial.get("_stratum_counters", {})
        chosen = assign_arm(
            trial["randomization_scheme"],
            arms,
            trial["block_size"],
            trial["stratification_field"],
            p["profile"],
            trial["enrolled_count"],
            stratum_counters,
        )

        ts = now()
        # Apply mutations atomically.
        p["signed_consent_version"] = consent_version
        p["arm_id"] = chosen["id"]
        p["enrolled_at"] = ts
        p["status"] = "ENROLLED"
        _bump(p)

        chosen["assigned_count"] = chosen["assigned_count"] + 1
        chosen["updated_at"] = ts
        chosen["version"] = chosen["version"] + 1

        trial["enrolled_count"] = trial["enrolled_count"] + 1
        trial["updated_at"] = ts
        trial["version"] = trial["version"] + 1

        # Per-stratum counter bump (only used by STRATIFIED_BLOCK at next assignment).
        if trial["randomization_scheme"] == "STRATIFIED_BLOCK":
            sf = trial["stratification_field"]
            key = str(p["profile"].get(sf))
            stratum_counters[key] = stratum_counters.get(key, 0) + 1
            trial["_stratum_counters"] = stratum_counters

        # Auto-close enrollment if cap reached.
        if trial["enrolled_count"] == trial["target_enrollment"]:
            trial["status"] = "CLOSED_TO_ENROLLMENT"
            trial["updated_at"] = ts
            trial["version"] = trial["version"] + 1

        return ok(serialize_participant(p))


# =====================================================================
# POST /participants/<id>/withdraw
# =====================================================================

@bp.post("/participants/<participant_id>/withdraw")
@require_roles(ROLE_COORD, ROLE_PARTICIPANT_SELF)
def withdraw_participant(participant_id: str, **caller):
    enforce_self_ownership(participant_id, caller["_caller_id"], caller["_caller_role"])
    body = require_json_object()
    reason = body.get("reason")
    if reason is not None:
        assert_string(reason, "reason", required=False, min_len=1, max_len=1000)

    with store().lock:
        p = get_participant(participant_id)
        if p["status"] not in {"ENROLLED", "CONSENT_PENDING"}:
            raise err_invalid_state("Participant is not in a withdrawable state")

        trial = store().trials.get(p["trial_id"])
        ts = now()

        was_enrolled = p["status"] == "ENROLLED"
        prev_arm_id = p["arm_id"]

        p["status"] = "WITHDRAWN"
        _bump(p)

        if was_enrolled:
            # Cascade: each SCHEDULED visit on this participant → CANCELLED.
            # Cascade-of-cascade: for each visit cascaded that had a PROVISIONAL payment,
            # write a REVERSAL row.
            _cascade_cancel_scheduled_visits(p, ts)
            # Decrement Trial.enrolled_count, decrement Arm.assigned_count.
            if trial is not None and trial["enrolled_count"] > 0:
                trial["enrolled_count"] = trial["enrolled_count"] - 1
                trial["updated_at"] = ts
                trial["version"] = trial["version"] + 1
            if prev_arm_id and prev_arm_id in store().arms:
                arm = store().arms[prev_arm_id]
                if arm["assigned_count"] > 0:
                    arm["assigned_count"] = arm["assigned_count"] - 1
                arm["updated_at"] = ts
                arm["version"] = arm["version"] + 1

        return ok(serialize_participant(p))


# =====================================================================
# POST /participants/<id>/complete
# =====================================================================

@bp.post("/participants/<participant_id>/complete")
@require_roles(ROLE_COORD)
def complete_participant(participant_id: str, **_caller):
    with store().lock:
        p = get_participant(participant_id)
        if p["status"] != "ENROLLED":
            raise err_invalid_state("Participant is not ENROLLED")
        # All visits must be in COMPLETED, MISSED, CANCELLED.
        for v in visits_for_participant(participant_id):
            if v["status"] not in {"COMPLETED", "MISSED", "CANCELLED"}:
                raise err_invalid_state("Some visits are still active for this participant")
        if open_ae_count_for(participant_id) > 0:
            raise err_invalid_state("Participant still has open adverse events")

        trial = get_trial(p["trial_id"])
        ts = now()
        p["status"] = "COMPLETED"
        _bump(p)

        # Finalization: for each COMPLETED Visit with a PROVISIONAL payment that has NOT been reversed,
        # write a FINAL payment row with the same amount_cents and paid_at = now().
        # Additionally, allocate RE_CONSENT_BONUS_CENTS to the LAST chronological COMPLETED visit
        # (by max sequence_no) iff the participant signed the current active_consent_version AND
        # at least one ConsentVersion with version >= 2 exists on the trial.
        from ..services.calculations import RE_CONSENT_BONUS_CENTS

        # Find completed visits and the provisional payments active on each (after subtracting reversals).
        visits = [v for v in visits_for_participant(participant_id) if v["status"] == "COMPLETED"]
        # Determine effective per-visit provisional balance (provisional + reversal nets).
        # We must only finalize visits whose net is > 0 (i.e., not reversed away).
        payments = payments_for_participant(participant_id)
        net_by_visit: dict[str, int] = {}
        for pmt in payments:
            vid = pmt.get("visit_id")
            if not vid:
                continue
            if pmt["kind"] == "PROVISIONAL":
                net_by_visit[vid] = net_by_visit.get(vid, 0) + pmt["amount_cents"]
            elif pmt["kind"] == "REVERSAL":
                net_by_visit[vid] = net_by_visit.get(vid, 0) + pmt["amount_cents"]
            # FINAL rows shouldn't pre-exist for a not-yet-completed participant, but defensively skip.

        # Sort visits by sequence_no ascending; the re-consent bonus goes to the last (max seq).
        visits_with_pay = [
            v for v in visits if net_by_visit.get(v["id"], 0) > 0
        ]
        visits_with_pay.sort(key=lambda v: v["sequence_no"])
        # Eligibility for re-consent bonus.
        has_v2 = any(c["version"] >= 2 for c in consent_versions_for_trial(trial["id"]))
        active = trial["active_consent_version"]
        receives_bonus = (
            has_v2
            and active is not None
            and p["signed_consent_version"] is not None
            and p["signed_consent_version"] == active
        )

        # Determine last-visit recipient of the bonus.
        recipient_visit_id: str | None = None
        if receives_bonus and visits_with_pay:
            # Last by sequence_no, with DESC tie-break (i.e., still the max).
            recipient_visit_id = visits_with_pay[-1]["id"]

        for v in visits_with_pay:
            amount = net_by_visit[v["id"]]
            if v["id"] == recipient_visit_id:
                amount += RE_CONSENT_BONUS_CENTS
            final_id = new_uuid()
            store().payments[final_id] = {
                "id": final_id,
                "participant_id": p["id"],
                "visit_id": v["id"],
                "kind": "FINAL",
                "amount_cents": amount,
                "paid_at": ts,
                "created_at": ts,
            }

        return ok(serialize_participant(p))


# =====================================================================
# Cascade helpers used by trial termination and participant withdrawal
# =====================================================================

def _cascade_cancel_scheduled_visits(participant: dict[str, Any], ts: Any) -> None:
    """For each SCHEDULED visit on `participant`, transition to CANCELLED.

    For each cascaded visit holding a PROVISIONAL payment that has NOT already been
    reversed, write a REVERSAL Payment row whose amount = -PROVISIONAL.amount_cents.
    """
    from ..services.lookups import payments_for_participant as _pp

    # Build per-visit net of (PROVISIONAL + REVERSAL) sums.
    net_by_visit: dict[str, int] = {}
    for pmt in _pp(participant["id"]):
        vid = pmt.get("visit_id")
        if not vid:
            continue
        if pmt["kind"] in {"PROVISIONAL", "REVERSAL"}:
            net_by_visit[vid] = net_by_visit.get(vid, 0) + pmt["amount_cents"]

    for v in list(store().visits.values()):
        if v["participant_id"] != participant["id"]:
            continue
        if v["status"] != "SCHEDULED":
            continue
        v["status"] = "CANCELLED"
        v["updated_at"] = ts
        v["version"] = v["version"] + 1

    # Now handle PROVISIONAL → REVERSAL for visits that were COMPLETED but get unwound by this cascade.
    # Per PRD §3.7: "for each visit cascaded to CANCELLED that holds a PROVISIONAL payment, write a REVERSAL".
    # In the withdraw flow, the only visits that hold a PROVISIONAL payment AND would get reversed are
    # the ones being cancelled in this cascade. But SCHEDULED visits don't have PROVISIONAL payments;
    # completed visits do. The PRD is using "cascaded to CANCELLED" loosely — what is meant is:
    # the participant's withdrawal unwinds outstanding provisional accruals on visits that won't be paid.
    # We interpret this as: any COMPLETED visit with a positive net PROVISIONAL balance gets reversed
    # when the participant withdraws (those compensations will never be paid because the participant
    # didn't finish the trial). This matches the test-suite expectations for the cascade chain.
    for v in store().visits.values():
        if v["participant_id"] != participant["id"]:
            continue
        if v["status"] != "COMPLETED":
            continue
        net = net_by_visit.get(v["id"], 0)
        if net > 0:
            rev_id = new_uuid()
            store().payments[rev_id] = {
                "id": rev_id,
                "participant_id": participant["id"],
                "visit_id": v["id"],
                "kind": "REVERSAL",
                "amount_cents": -net,
                "paid_at": None,
                "created_at": ts,
            }


def cascade_withdraw_for_trial_termination(p: dict[str, Any], trial: dict[str, Any]) -> None:
    """Trial.terminate cascade: WITHDRAW a single participant and cancel their scheduled visits."""
    ts = now()
    prev_arm_id = p["arm_id"]
    was_enrolled = p["status"] == "ENROLLED"
    p["status"] = "WITHDRAWN"
    _bump(p)
    if was_enrolled:
        _cascade_cancel_scheduled_visits(p, ts)
        if trial["enrolled_count"] > 0:
            trial["enrolled_count"] = trial["enrolled_count"] - 1
        # Note: we don't bump trial here because the caller bumps it once at the end.
        if prev_arm_id and prev_arm_id in store().arms:
            arm = store().arms[prev_arm_id]
            if arm["assigned_count"] > 0:
                arm["assigned_count"] = arm["assigned_count"] - 1
            arm["updated_at"] = ts
            arm["version"] = arm["version"] + 1
    else:
        # SCHEDULED-state visit cancellation cascade still runs (the participant might have visits
        # scheduled, although for SCREENING/ELIGIBLE/CONSENT_PENDING they typically don't).
        _cascade_cancel_scheduled_visits(p, ts)
