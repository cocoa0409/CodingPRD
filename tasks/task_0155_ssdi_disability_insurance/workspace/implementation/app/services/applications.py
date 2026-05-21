"""Application lifecycle and the approval/cessation cascades.

This module orchestrates the §3.4 / §3.6 state machine including:
  - DRAFT -> INITIAL_REVIEW (with QC + evidence + AOD checks)
  - Determination POST (INITIAL / RECONSIDERATION / ALJ / APPEALS_COUNCIL)
  - Appeal POST (with appeal-window enforcement)
  - The approval cascade (PIA, Family Max, Back Pay, CDR diary, auto-CDR row,
    child auxiliary recompute via the waterfall)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app import clock, store
from app.calculations import (
    APPEAL_WINDOW_DAYS,
    back_pay_calc,
    cdr_diary_lookup,
    child_aux_waterfall,
    family_max_calc,
    pia_calc,
    waiting_period_calc,
)
from app.errors import (
    aod_after_filing,
    appeal_window_expired,
    application_not_found,
    bad_request,
    evidence_insufficient,
    hearing_not_held,
    invalid_state,
    qc_insufficient,
    segregation_of_duties,
)
from app.routes._helpers import fetch_application_under_claimant, fetch_claimant
from app.services.claimants import recompute_claimant_qc
from app.util import add_months, new_uuid


_VALID_LEVELS = {"INITIAL", "RECONSIDERATION", "ALJ", "APPEALS_COUNCIL"}
_VALID_DECISIONS = {"ALLOW", "DENY", "REMAND"}
_VALID_MEDICAL_BASIS = {"MEETS_LISTING", "EQUALS_LISTING", "DISABLED_BY_RFC", "NOT_DISABLED", "NOT_REACHED"}
_ALLOW_MEDICAL_BASIS = {"MEETS_LISTING", "EQUALS_LISTING", "DISABLED_BY_RFC"}
_VALID_TARGET_LEVEL = {"RECONSIDERATION", "ALJ", "APPEALS_COUNCIL"}


# ---------------------------------------------------------------------------
# Create / Get
# ---------------------------------------------------------------------------

def create_application(claimant_id: str) -> dict:
    fetch_claimant(claimant_id)
    now = clock.now()
    new_id = new_uuid()
    record = {
        "id": new_id,
        "claimant_id": claimant_id,
        "status": "DRAFT",
        "medical_decision": None,
        "last_initial_examiner_id": None,
        "established_onset_date": None,
        "pia_cents": None,
        "aime_cents": None,
        "family_max_cents": None,
        "monthly_benefit_cents": None,
        "entitlement_date": None,
        "back_pay_cents": None,
        "approval_date": None,
        "next_cdr_due_date": None,
        "cdr_diary": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock():
        store.applications[new_id] = record
    return record


def get_application(claimant_id: str, app_id: str) -> dict:
    return fetch_application_under_claimant(claimant_id, app_id)


# ---------------------------------------------------------------------------
# Submit DRAFT -> INITIAL_REVIEW
# ---------------------------------------------------------------------------

def submit_application(claimant_id: str, app_id: str) -> dict:
    with store.lock():
        application = fetch_application_under_claimant(claimant_id, app_id)
        if application["status"] != "DRAFT":
            raise invalid_state(f"Application in status {application['status']} cannot be submitted")

        claimant = store.claimants[claimant_id]

        # Recompute QC aggregates first so we evaluate the latest figures.
        recompute_claimant_qc(claimant)

        # Order per §3.3: QC -> evidence -> AOD-after-filing.
        if claimant["insured_status"] != "INSURED":
            raise qc_insufficient("Claimant is NOT_INSURED — QC requirement not met")

        has_accepted = any(
            m["claimant_id"] == claimant_id and m["status"] == "ACCEPTED"
            for m in store.medical_evidence.values()
        )
        if not has_accepted:
            raise evidence_insufficient("No ACCEPTED medical evidence on file")

        if claimant["alleged_onset_date"] > claimant["filing_date"]:
            raise aod_after_filing("alleged_onset_date must be on or before filing_date")

        application["status"] = "INITIAL_REVIEW"
        application["updated_at"] = clock.now()
        application["version"] += 1
    return application


# ---------------------------------------------------------------------------
# Determinations
# ---------------------------------------------------------------------------

def _validate_determination_body(body: dict) -> dict:
    level = body.get("level")
    if level not in _VALID_LEVELS:
        raise bad_request(f"level must be one of {sorted(_VALID_LEVELS)}")
    decision = body.get("decision")
    if decision not in _VALID_DECISIONS:
        raise bad_request(f"decision must be one of {sorted(_VALID_DECISIONS)}")
    if decision == "REMAND" and level != "APPEALS_COUNCIL":
        raise bad_request("REMAND decision is valid only at APPEALS_COUNCIL")
    medical_basis = body.get("medical_basis")
    if medical_basis is not None and medical_basis not in _VALID_MEDICAL_BASIS:
        raise bad_request(f"medical_basis must be one of {sorted(_VALID_MEDICAL_BASIS)}")
    rationale = body.get("rationale")
    if not isinstance(rationale, str) or len(rationale) < 50:
        raise bad_request("rationale must be a string of at least 50 characters")
    return body


def _expected_status_for_level(level: str) -> str:
    """The Application.status that must hold for a determination at this level."""
    return {
        "INITIAL": "INITIAL_REVIEW",
        "RECONSIDERATION": "RECONSIDERATION",
        "ALJ": "ALJ_PENDING",
        "APPEALS_COUNCIL": "APPEALS_COUNCIL",
    }[level]


def _role_allowed_for_level(role: str, level: str) -> bool:
    if level in ("INITIAL", "RECONSIDERATION"):
        return role == "DDS_Examiner"
    if level == "ALJ":
        return role == "ALJ"
    if level == "APPEALS_COUNCIL":
        return role == "AppealsCouncil"
    return False


def _examiner_role_for_level(level: str) -> str:
    return {
        "INITIAL": "DDS_Examiner",
        "RECONSIDERATION": "DDS_Examiner",
        "ALJ": "ALJ",
        "APPEALS_COUNCIL": "AppealsCouncil",
    }[level]


def _existing_application_determinations(app_id: str) -> list[dict]:
    rows = [
        d for d in store.determinations.values()
        if d["application_id"] == app_id
    ]
    rows.sort(key=lambda d: (d["created_at"], d["id"]))
    return rows


def _latest_determination_for_level(app_id: str, level: str) -> Optional[dict]:
    rows = [
        d for d in _existing_application_determinations(app_id)
        if d["level"] == level
    ]
    if not rows:
        return None
    return rows[-1]


def post_determination(claimant_id: str, app_id: str, body: dict, caller) -> dict:
    _validate_determination_body(body)
    level = body["level"]
    decision = body["decision"]
    medical_basis = body.get("medical_basis")

    if not _role_allowed_for_level(caller.role, level):
        from app.errors import forbidden
        raise forbidden(f"Role {caller.role} cannot issue a {level} determination")

    with store.lock():
        application = fetch_application_under_claimant(claimant_id, app_id)
        expected_status = _expected_status_for_level(level)
        if application["status"] != expected_status:
            raise invalid_state(
                f"Determination at level {level} requires Application.status == {expected_status}; "
                f"current status is {application['status']}"
            )

        # Segregation of duties at RECONSIDERATION.
        if level == "RECONSIDERATION":
            if caller.user_id == application.get("last_initial_examiner_id"):
                raise segregation_of_duties(
                    "Reconsideration examiner cannot equal the initial-review examiner"
                )

        # ALJ requires an associated HELD hearing slot.
        if level == "ALJ":
            has_held = any(
                h["application_id"] == app_id and h["status"] == "HELD"
                for h in store.hearing_slots.values()
            )
            if not has_held:
                raise hearing_not_held("No HELD hearing slot for this application")

        # ALLOW gate: medical_basis must be one of {MEETS_LISTING, EQUALS_LISTING, DISABLED_BY_RFC}.
        if decision == "ALLOW":
            if level == "APPEALS_COUNCIL":
                # Appeals Council can only DENY or REMAND.
                raise bad_request("Appeals Council determinations cannot ALLOW directly; remand or deny")
            if medical_basis not in _ALLOW_MEDICAL_BASIS:
                raise bad_request(
                    f"ALLOW requires medical_basis in {sorted(_ALLOW_MEDICAL_BASIS)}; got {medical_basis}"
                )

        # Established onset date parsing/validation.
        eod = None
        if body.get("established_onset_date") is not None:
            from app.util import parse_iso_date
            eod = parse_iso_date(body["established_onset_date"], "established_onset_date")
            claimant = store.claimants[claimant_id]
            if eod < claimant["alleged_onset_date"]:
                raise bad_request("established_onset_date must be on or after alleged_onset_date")

        now = clock.now()
        det_id = new_uuid()
        det = {
            "id": det_id,
            "application_id": app_id,
            "level": level,
            "examiner_id": caller.user_id,
            "examiner_role": _examiner_role_for_level(level),
            "decision": decision,
            "medical_basis": medical_basis,
            "established_onset_date": eod,
            "rationale": body["rationale"],
            "created_at": now,
        }

        # Apply the state transition + cascades on the Application
        _apply_determination(application, det, claimant_id)

        store.determinations[det_id] = det
    return det


def _apply_determination(application: dict, det: dict, claimant_id: str) -> None:
    level = det["level"]
    decision = det["decision"]
    application["medical_decision"] = det.get("medical_basis")

    # Stamp initial examiner where relevant.
    if level == "INITIAL":
        application["last_initial_examiner_id"] = det["examiner_id"]

    if decision == "DENY":
        if level == "INITIAL":
            application["status"] = "INITIAL_DENIED"
        elif level == "RECONSIDERATION":
            application["status"] = "RECON_DENIED"
        elif level == "ALJ":
            application["status"] = "ALJ_DENIED"
        elif level == "APPEALS_COUNCIL":
            application["status"] = "CLOSED_DENIED"
        application["updated_at"] = clock.now()
        application["version"] += 1
        return

    if decision == "REMAND":
        # REMAND only valid at APPEALS_COUNCIL — cycle back to RECONSIDERATION.
        application["status"] = "RECONSIDERATION"
        application["updated_at"] = clock.now()
        application["version"] += 1
        return

    # ALLOW path — runs the approval cascade.
    if decision == "ALLOW":
        if level == "ALJ":
            new_status = "ALJ_APPROVED"
            variant = "FINAL"
        else:
            new_status = "APPROVED"
            variant = "PROVISIONAL"
        application["status"] = new_status

        _run_approval_cascade(application, det, variant)


def _run_approval_cascade(application: dict, det: dict, variant: str) -> None:
    """Compute PIA, family max, back pay, CDR diary; auto-create CDRReview."""
    claimant = store.claimants[application["claimant_id"]]

    # 1. established_onset_date
    eod = det.get("established_onset_date") or claimant["alleged_onset_date"]
    application["established_onset_date"] = eod

    # 2. entitlement_date (waiting period)
    application["entitlement_date"] = waiting_period_calc(eod)

    # 3. PIA / AIME
    qc_rows = [q for q in store.quarter_credits.values() if q["claimant_id"] == claimant["id"]]
    aime, pia = pia_calc(qc_rows, claimant["alleged_onset_date"], variant=variant)
    application["aime_cents"] = aime
    application["pia_cents"] = pia

    # 4. Family max
    application["family_max_cents"] = family_max_calc(pia)

    # 5. monthly_benefit_cents = pia (pre-auxiliary)
    application["monthly_benefit_cents"] = pia

    # 6. approval_date
    now = clock.now()
    application["approval_date"] = now

    # 7. back pay
    back_pay_variant = variant   # PROVISIONAL or FINAL
    application["back_pay_cents"] = back_pay_calc(
        application["entitlement_date"],
        now,
        claimant["filing_date"],
        pia,
        variant=back_pay_variant,
    )

    # 8. CDR diary
    # Resolve listing_code / age_category from the latest ACCEPTED MedicalEvidence row.
    listing_code = None
    age_cat = None
    accepted_rows = [
        m for m in store.medical_evidence.values()
        if m["claimant_id"] == claimant["id"] and m["status"] == "ACCEPTED"
    ]
    if accepted_rows:
        accepted_rows.sort(key=lambda m: m["created_at"])
        latest = accepted_rows[-1]
        listing_code = latest.get("listing_code")
        age_cat = latest.get("age_category_at_decision")
    diary, months = cdr_diary_lookup(det.get("medical_basis"), listing_code, age_cat)
    application["cdr_diary"] = diary
    # next_cdr_due_date = approval_date + diary months
    if isinstance(now, datetime):
        approval_date = now.date()
    else:
        approval_date = now
    application["next_cdr_due_date"] = add_months(approval_date, months)

    # 9. Auto-create CDRReview row (PENDING).
    cdr_id = new_uuid()
    review = {
        "id": cdr_id,
        "application_id": application["id"],
        "review_due_date": application["next_cdr_due_date"],
        "scheduled_at": None,
        "completed_at": None,
        "outcome": None,
        "medical_improvement_found": None,
        "working_at_sga": None,
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.cdr_reviews[cdr_id] = review

    application["updated_at"] = clock.now()
    application["version"] += 1

    # 10. Recompute child auxiliary waterfall for any ENTITLED siblings (if any
    # were already ENTITLED — rare on first approval but possible after remand).
    _recompute_child_aux_for_app(application)


def _recompute_child_aux_for_app(application: dict) -> None:
    entitled = [
        c for c in store.child_auxiliaries.values()
        if c["application_id"] == application["id"] and c["status"] == "ENTITLED"
    ]
    if not entitled:
        return
    pia = application.get("pia_cents") or 0
    fmb = application.get("family_max_cents") or 0
    allocations = child_aux_waterfall(pia, fmb, entitled)
    now = clock.now()
    for child in entitled:
        new_amount = allocations.get(child["id"], 0)
        if child.get("monthly_benefit_cents") != new_amount:
            child["monthly_benefit_cents"] = new_amount
            child["updated_at"] = now
            child["version"] += 1


# ---------------------------------------------------------------------------
# Appeal
# ---------------------------------------------------------------------------

def appeal_application(claimant_id: str, app_id: str, body: dict) -> dict:
    target = body.get("target_level")
    if target not in _VALID_TARGET_LEVEL:
        raise bad_request(f"target_level must be one of {sorted(_VALID_TARGET_LEVEL)}")

    with store.lock():
        application = fetch_application_under_claimant(claimant_id, app_id)
        current = application["status"]
        expected = {
            "RECONSIDERATION": "INITIAL_DENIED",
            "ALJ": "RECON_DENIED",
            "APPEALS_COUNCIL": "ALJ_DENIED",
        }[target]
        if current != expected:
            raise invalid_state(
                f"Appeal to {target} requires Application.status == {expected}; current is {current}"
            )

        # Appeal window check: latest determination must be within 60 days.
        last_det = _latest_determination_for_status(app_id, current)
        if last_det is None:
            raise invalid_state("No prior determination to appeal")
        now = clock.now()
        deadline = last_det["created_at"] + timedelta(days=APPEAL_WINDOW_DAYS)
        if now > deadline:
            raise appeal_window_expired("Appeal posted after the 60-day window")

        new_status = {
            "RECONSIDERATION": "RECONSIDERATION",
            "ALJ": "ALJ_PENDING",
            "APPEALS_COUNCIL": "APPEALS_COUNCIL",
        }[target]
        application["status"] = new_status
        application["updated_at"] = now
        application["version"] += 1
    return application


def _latest_determination_for_status(app_id: str, current_status: str) -> Optional[dict]:
    """Return the most recent determination matching the denial level."""
    level = {
        "INITIAL_DENIED": "INITIAL",
        "RECON_DENIED": "RECONSIDERATION",
        "ALJ_DENIED": "ALJ",
    }.get(current_status)
    if level is None:
        return None
    return _latest_determination_for_level(app_id, level)


# ---------------------------------------------------------------------------
# List determinations
# ---------------------------------------------------------------------------

def list_determinations(claimant_id: str, app_id: str) -> list[dict]:
    fetch_application_under_claimant(claimant_id, app_id)
    rows = _existing_application_determinations(app_id)
    return rows


# ---------------------------------------------------------------------------
# CDR cessation cascade — called by services.cdr_reviews
# ---------------------------------------------------------------------------

def cdr_cease_application(app_id: str) -> None:
    application = store.applications.get(app_id)
    if not application:
        return
    if application["status"] not in ("APPROVED", "ALJ_APPROVED"):
        # The state machine only emits cdr-cease on an APPROVED application.
        return

    application["status"] = "CLOSED_DENIED"
    now = clock.now()
    application["updated_at"] = now
    application["version"] += 1

    # Compensating ledger row: negative entitlement delta.
    delta_id = new_uuid()
    original_back_pay = application.get("back_pay_cents") or 0
    delta = {
        "id": delta_id,
        "application_id": app_id,
        "level": "CDR_CESSATION",
        "examiner_id": "system",
        "examiner_role": "CDR_Reviewer",
        "decision": "DENY",
        "medical_basis": "NOT_DISABLED",
        "established_onset_date": None,
        "rationale": (
            "Continuing Disability Review CEASE outcome; compensating ledger "
            "row recoups previously awarded back pay of "
            f"{original_back_pay} cents."
        ),
        "created_at": now,
        "entitlement_delta_cents": -original_back_pay,
    }
    store.determinations[delta_id] = delta

    # Terminate all ENTITLED children for this application with PARENT_BENEFIT_ENDED.
    for child in list(store.child_auxiliaries.values()):
        if child["application_id"] == app_id and child["status"] == "ENTITLED":
            child["status"] = "TERMINATED"
            child["termination_reason"] = "PARENT_BENEFIT_ENDED"
            child["monthly_benefit_cents"] = 0
            child["updated_at"] = now
            child["version"] += 1

    # Recompute any SSI supplement on this claimant that was suppressed by DIB.
    claimant_id = application["claimant_id"]
    from app.services.ssi_supplements import recompute_after_dib_loss
    recompute_after_dib_loss(claimant_id)
