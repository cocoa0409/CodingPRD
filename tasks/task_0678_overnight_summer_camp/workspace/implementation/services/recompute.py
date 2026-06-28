"""Derived-field reconciliation (PRD §2.5).

Whenever a write changes a computed field, the owning resource is mutated: its
updated_at is refreshed and its version increments. Cascades up the session tree
independently mutate each affected resource the same way.

These helpers mutate-and-touch only when a derived value actually changes a
*persisted* derived field. Pure read-time derivations (balances, counts that are
recomputed at serialize time) do not need to touch versions here — but the
spec's enumerated side effects (e.g. bunk assignment bumping the cabin version)
are handled explicitly at the call sites.
"""
import db
from services import calc
from services.store import touch


# ---------------------------------------------------------------------------
# Session-level computed counts (recomputed on read; helpers below)
# ---------------------------------------------------------------------------
def session_enrolled_count(session_id):
    return sum(
        1 for a in db.applications.values()
        if a["session_id"] == session_id and a["enroll_status"] == "ENROLLED"
    )


def session_committed_count(session_id):
    return sum(
        1 for a in db.applications.values()
        if a["session_id"] == session_id
        and a["enroll_status"] in ("OFFERED", "DEPOSIT_PAID", "ENROLLED")
    )


def session_waitlist_length(session_id):
    return sum(
        1 for a in db.applications.values()
        if a["session_id"] == session_id and a["enroll_status"] == "WAITLISTED"
    )


# ---------------------------------------------------------------------------
# Cabin staffing recomputation — persisted derived fields with version bump.
# ---------------------------------------------------------------------------
def recompute_cabin_occupancy(cabin):
    """Recompute occupied_bunks from the applications bunked here. Used as a
    backstop; in practice occupied_bunks is maintained incrementally by the
    state machine, which is what the PRD's side-effect lists describe.
    """
    cabin["occupied_bunks"] = sum(
        1 for a in db.applications.values()
        if a["cabin_id"] == cabin["id"]
        and a["enroll_status"] in ("DEPOSIT_PAID", "ENROLLED")
    )


def recompute_cabin_staffing(cabin, bump_version=False):
    """Recompute staff_weight_x10 and is_staffable for a cabin. Optionally bump
    its version/updated_at (when staffing changed as a side effect of an
    assignment/release per PRD §3.2).
    """
    session = db.sessions[cabin["session_id"]]
    camp = db.camps[session["camp_id"]]
    new_weight = calc.compute_cabin_staff_weight(cabin)
    new_staffable = None
    cabin["staff_weight_x10"] = new_weight
    new_staffable = calc.compute_cabin_is_staffable(cabin, camp["counselor_camper_ratio"])
    cabin["is_staffable"] = new_staffable
    if bump_version:
        touch(cabin)


def recompute_cabin_is_staffable(cabin):
    session = db.sessions[cabin["session_id"]]
    camp = db.camps[session["camp_id"]]
    cabin["is_staffable"] = calc.compute_cabin_is_staffable(cabin, camp["counselor_camper_ratio"])


def recompute_session_posture(session, bump_version=False):
    new_posture = calc.compute_session_ratio_posture(session)
    changed = session.get("ratio_posture") != new_posture
    session["ratio_posture"] = new_posture
    if bump_version and changed:
        touch(session)


# HealthForm.status -> Camper.health_status mapping (PRD §2.10):
#   no form -> NONE; SUBMITTED -> PENDING; CLEARED -> CLEARED; FLAGGED -> FLAGGED.
# A form in DRAFT does not move the camper off NONE (a DRAFT form is "not yet
# begun" from the infirmary's view, and the latest-form mirror only reflects
# review-relevant states). However, the side-effect lists only ever recompute
# after a submit/clear/flag, so the latest form here is always non-DRAFT.
_FORM_TO_CAMPER = {
    "SUBMITTED": "PENDING",
    "CLEARED": "CLEARED",
    "FLAGGED": "FLAGGED",
    "DRAFT": "NONE",
}


def recompute_camper_health_status(camper):
    """Camper.health_status mirrors the camper's latest HealthForm.status,
    mapped through the camper enum; NONE when no form exists. (PRD §2.10)
    """
    forms = [hf for hf in db.health_forms.values() if hf["camper_id"] == camper["id"]]
    if not forms:
        camper["health_status"] = "NONE"
        return
    forms.sort(key=lambda hf: (hf["created_at_dt"], hf["_seq"]))
    latest = forms[-1]["status"]
    camper["health_status"] = _FORM_TO_CAMPER.get(latest, "NONE")


# ---------------------------------------------------------------------------
# Application balances — recomputed on demand and persisted on the application.
# ---------------------------------------------------------------------------
def recompute_application_money(application):
    application["aid_cents"] = calc.compute_aid_total(application)
    application["estimated_balance_cents"] = calc.compute_estimated_balance(application)
    application["settled_balance_cents"] = calc.compute_settled_balance(application)


def recompute_canteen_account(account):
    camp = _camp_for_application(account["application_id"])
    balance = calc.compute_canteen_balance(account["id"])
    account["balance_cents"] = balance
    low_threshold = camp["canteen_low_balance_cents"] if camp else 0
    account["is_low"] = balance <= low_threshold


def _camp_for_application(application_id):
    app = db.applications.get(application_id)
    if app is None:
        return None
    session = db.sessions.get(app["session_id"])
    if session is None:
        return None
    return db.camps.get(session["camp_id"])
