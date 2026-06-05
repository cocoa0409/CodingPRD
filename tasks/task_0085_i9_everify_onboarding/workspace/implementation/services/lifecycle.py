"""Clock-driven lifecycle helpers and automatic transitions.

This module concentrates the time-crossing logic that the PRD describes in §3.4,
§3.6 and §3.7: the latching is_overdue flag, the controlling work-authorization
selection, the move into REVERIFICATION_DUE / EXPIRED_UNAUTHORIZED, the
auto-EXPIRY of a lapsed authorization, and the TNC->FINAL_NONCONFIRMATION lapse.
"""

from clock import now, parse_iso8601
from db import db, touch
from services import audit


# ---------------------------------------------------------------------------
# is_overdue latching (PRD §3.2)
# ---------------------------------------------------------------------------
def recompute_is_overdue(onboarding, form):
    """Latch is_overdue. Once true it stays true (only an override clears it).

    Becomes true when:
      - Section 2 not yet completed (section2_completed_at null) AND clock is
        strictly past section2_deadline; OR
      - Section 2 completed but section2_completed_at strictly after
        section2_deadline.
    """
    if onboarding.get("is_overdue"):
        return  # latched; only override clears it
    deadline_iso = onboarding.get("section2_deadline")
    if not deadline_iso:
        return
    deadline = parse_iso8601(deadline_iso)
    completed_iso = form.get("section2_completed_at") if form else None
    if completed_iso is None:
        if now() > deadline:
            onboarding["is_overdue"] = True
    else:
        if parse_iso8601(completed_iso) > deadline:
            onboarding["is_overdue"] = True


# ---------------------------------------------------------------------------
# Work authorization helpers
# ---------------------------------------------------------------------------
def work_auths_for(onboarding_id):
    return [w for w in db.work_authorizations.values()
            if w.get("onboarding_id") == onboarding_id]


def controlling_work_auth(onboarding_id, exclude_id=None):
    """The authorization whose effective_valid_until currently governs
    reverification: the non-superseded record with the latest
    effective_valid_until. Returns None when the onboarding has no auths.

    ``exclude_id`` omits a particular record from consideration — used when
    recording a Section 3 block to find the *prior* controlling authorization
    (the one being replaced) without picking the just-presented new record."""
    candidates = [w for w in work_auths_for(onboarding_id)
                  if w.get("status") != "SUPERSEDED"
                  and w.get("effective_valid_until")
                  and w.get("id") != exclude_id]
    if not candidates:
        return None
    return max(candidates,
               key=lambda w: parse_iso8601(w["effective_valid_until"]))


def everify_case_for(onboarding_id):
    """The most recent E-Verify case for an onboarding (by insertion seq)."""
    cases = [c for c in db.everify_cases.values()
             if c.get("onboarding_id") == onboarding_id]
    if not cases:
        return None
    return max(cases, key=lambda c: c.get("_seq", 0))


# ---------------------------------------------------------------------------
# Automatic, clock-driven transitions (PRD §3.7 advance-lifecycle)
# ---------------------------------------------------------------------------
def advance(onboarding, actor_role, actor_user_id):
    """Re-derive deadlines for one onboarding against the current clock and
    apply whichever automatic transitions are now due. Returns True if any
    transition fired (caller bumps version via the transitions themselves)."""
    clock = now()
    fired = False
    onboarding_id = onboarding["id"]

    # Capture the status the onboarding had on entry to this advance call. The
    # AUTHORIZED -> REVERIFICATION_DUE and REVERIFICATION_DUE ->
    # EXPIRED_UNAUTHORIZED transitions are separate clock events (PRD §3.6: the
    # terminal expiry fires only "while the onboarding sits in
    # REVERIFICATION_DUE"), so a single advance applies at most one of them.
    entry_status = onboarding.get("status")

    # 2. TNC_ISSUED case lapse -> FINAL_NONCONFIRMATION (PRD §3.4 / §3.7).
    case = everify_case_for(onboarding_id)
    if (case is not None and case.get("status") == "TNC_ISSUED"
            and case.get("referral_deadline")):
        if clock > parse_iso8601(case["referral_deadline"]):
            case["status"] = "FINAL_NONCONFIRMATION"
            touch(case)
            if onboarding.get("status") == "EVERIFY_PENDING":
                onboarding["status"] = "TERMINATED_NONCONFIRMED"
                touch(onboarding)
                audit.append(onboarding_id, "system", "system",
                             "FINAL_NONCONFIRMATION",
                             "TNC referral window lapsed; case final nonconfirmation")
                audit.append(onboarding_id, "system", "system",
                             "TERMINATED_NONCONFIRMED",
                             "Onboarding terminated after final nonconfirmation")
            fired = True

    # 3. AUTHORIZED -> REVERIFICATION_DUE (PRD §3.6).
    if onboarding.get("status") == "AUTHORIZED":
        ctrl = controlling_work_auth(onboarding_id)
        if ctrl is not None and ctrl.get("effective_valid_until"):
            evu = parse_iso8601(ctrl["effective_valid_until"])
            if clock > evu and not _reverification_covers(onboarding_id, evu):
                onboarding["status"] = "REVERIFICATION_DUE"
                touch(onboarding)
                # the lapsed controlling auth expires if still active
                if ctrl.get("status") in ("ACTIVE", "EXTENDED"):
                    ctrl["status"] = "EXPIRED"
                    touch(ctrl)
                audit.append(onboarding_id, "system", "system",
                             "REVERIFICATION_DUE",
                             "Controlling authorization lapsed; reverification due")
                fired = True

    # 4. REVERIFICATION_DUE -> EXPIRED_UNAUTHORIZED (PRD §3.6). Only when the
    #    onboarding was ALREADY in REVERIFICATION_DUE on entry (i.e. it did not
    #    just transition there in step 3 during this same call).
    if (entry_status == "REVERIFICATION_DUE"
            and onboarding.get("status") == "REVERIFICATION_DUE"):
        ctrl = controlling_work_auth(onboarding_id)
        if ctrl is not None and ctrl.get("effective_valid_until"):
            evu = parse_iso8601(ctrl["effective_valid_until"])
            if clock > evu and not _reverification_covers(onboarding_id, evu):
                onboarding["status"] = "EXPIRED_UNAUTHORIZED"
                touch(onboarding)
                if ctrl.get("status") in ("ACTIVE", "EXTENDED"):
                    ctrl["status"] = "EXPIRED"
                    touch(ctrl)
                audit.append(onboarding_id, "system", "system",
                             "EXPIRED_UNAUTHORIZED",
                             "Reverification never recorded; authorization expired")
                fired = True

    return fired


def _reverification_covers(onboarding_id, lapsed_evu):
    """True when a RECORDED ReverificationEvent on this onboarding's form
    presents an authorization whose effective_valid_until is strictly after the
    lapsed authorization's effective_valid_until (i.e. it covers the lapse)."""
    form = next((f for f in db.i9_forms.values()
                 if f.get("onboarding_id") == onboarding_id), None)
    if form is None:
        return False
    for ev in db.reverification_events.values():
        if ev.get("i9_form_id") != form["id"]:
            continue
        if ev.get("status") != "RECORDED":
            continue
        wa = db.work_authorizations.get(ev.get("work_authorization_id"))
        if wa is None or not wa.get("effective_valid_until"):
            continue
        if parse_iso8601(wa["effective_valid_until"]) > lapsed_evu:
            return True
    return False
