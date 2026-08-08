"""ImmunizationDose validity evaluation and CASCADE B (PRD 3.5)."""
from flask import g

import constants as C
from store import db, touch
from timeutil import day_diff


def _series(child_id, vaccine_code):
    """administered_date ASC, then created_at ASC.  Never id."""
    rows = [
        d
        for d in db.doses.values()
        if d["child_id"] == child_id and d["vaccine_code"] == vaccine_code
    ]
    rows.sort(key=lambda d: (d["administered_date"], d["_seq"]))
    return rows


def reevaluate_series(child, vaccine_code):
    """Recompute effective_series_index, prior_valid_dose_id,
    interval_days_since_prior, validity and invalid_reason for the whole series
    in chronological order.  Doses may flip INVALID -> VALID as well as
    VALID -> INVALID; manually invalidated doses stay INVALID forever."""
    spec = C.VACCINE_SCHEDULE[vaccine_code]
    total_doses = spec["total_doses"]
    positions = spec["positions"]

    valid_so_far = []  # VALID doses already placed, in (date, seq) order
    for dose in _series(child["id"], vaccine_code):
        before = (
            dose["effective_series_index"],
            dose["prior_valid_dose_id"],
            dose["interval_days_since_prior"],
            dose["validity"],
            dose["invalid_reason"],
            dose["age_days_at_administration"],
        )

        index = len(valid_so_far) + 1
        # prior_valid: greatest administered_date STRICTLY less than this one,
        # ties on that date broken by the later created_at.
        prior = None
        for candidate in valid_so_far:
            if candidate["administered_date"] < dose["administered_date"]:
                prior = candidate
        interval = None
        if index > 1:
            reference = prior if prior is not None else valid_so_far[-1]
            interval = day_diff(dose["administered_date"], reference["administered_date"])

        dose["effective_series_index"] = index
        dose["prior_valid_dose_id"] = prior["id"] if prior is not None else None
        dose["interval_days_since_prior"] = interval
        dose["age_days_at_administration"] = day_diff(
            dose["administered_date"], child["date_of_birth"]
        )

        if dose["manually_invalidated"]:
            dose["validity"] = "INVALID"
            dose["invalid_reason"] = "MANUALLY_INVALIDATED"
        elif index > total_doses:
            dose["validity"] = "INVALID"
            dose["invalid_reason"] = "SERIES_ALREADY_COMPLETE"
        else:
            position = positions[index - 1]
            age_ok = (
                dose["age_days_at_administration"] + C.IMMUNIZATION_GRACE_DAYS
                >= position["min_age_days"]
            )
            if index == 1:
                interval_ok = True
            else:
                min_interval = position["min_interval_days"] or 0
                interval_ok = (interval or 0) + C.IMMUNIZATION_GRACE_DAYS >= min_interval
            # RUNG ORDER IS PINNED: age first.  When both rungs fail the
            # reported reason is MIN_AGE_NOT_MET, never MIN_INTERVAL_NOT_MET.
            if not age_ok:
                dose["validity"] = "INVALID"
                dose["invalid_reason"] = "MIN_AGE_NOT_MET"
            elif not interval_ok:
                dose["validity"] = "INVALID"
                dose["invalid_reason"] = "MIN_INTERVAL_NOT_MET"
            else:
                dose["validity"] = "VALID"
                dose["invalid_reason"] = None

        if dose["validity"] == "VALID":
            valid_so_far.append(dose)

        after = (
            dose["effective_series_index"],
            dose["prior_valid_dose_id"],
            dose["interval_days_since_prior"],
            dose["validity"],
            dose["invalid_reason"],
            dose["age_days_at_administration"],
        )
        if before != after:
            touch(dose, g.touched)


def block_pending_forms_of_child(child_id):
    """CASCADE B hop 3 — PENDING form requests of this child block with
    IMMUNIZATION_INCOMPLETE.  ISSUED requests are never revoked."""
    for form in db.form_requests.values():
        if form["status"] != "PENDING":
            continue
        if form["child_id"] != child_id:
            continue
        form["status"] = "BLOCKED"
        form["blocked_reason"] = "IMMUNIZATION_INCOMPLETE"
        touch(form, g.touched)


def invalidate_dose(dose, child, reason):
    """CASCADE B hop 0 -> hop 3."""
    dose["validity"] = "INVALID"
    dose["invalid_reason"] = "MANUALLY_INVALIDATED"
    dose["manually_invalidated"] = True
    dose["invalidation_reason_note"] = reason
    touch(dose, g.touched)
    # hop 1: the remaining series shifts
    reevaluate_series(child, dose["vaccine_code"])
    # hop 2: Child.immunization_complete_for_age is computed on every read
    # hop 3: dependent form requests block
    block_pending_forms_of_child(child["id"])
