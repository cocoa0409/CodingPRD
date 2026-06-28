"""Shared business-logic helpers used across multiple routes.

PA draw/restore (PRD §3.6), PA pre-draw validation chain, and encounter coding
helpers. All callers hold db.lock().
"""

import db
import errors
import clock
import calculations as calc


# ---- PA pre-draw validation (PRD §3.6, validation priority order §2.11) ----

def check_pa_drawable(pa, expected_category, draw_qty):
    """Run the business-referential / temporal / unit checks for a draw, in the
    PRD §2.11 priority order (after FK/structural/OCC have already passed):

      9  ERR_PA_CATEGORY_MISMATCH
      10 ERR_PA_NOT_DRAWABLE
      11 ERR_PA_EXPIRED
      14 ERR_PA_UNITS_EXCEEDED

    Expiry auto-transitions the PA to EXPIRED (PRD §3.6). Mutating callers must
    persist that transition. Returns nothing; raises on failure.
    """
    # 9: category match
    if pa["service_category"] != expected_category:
        raise errors.ApiError(errors.ERR_PA_CATEGORY_MISMATCH, 409,
                              "Linked PA service_category does not match the operation.")
    # 10: drawable state (must be APPROVED)
    if pa["status"] != "APPROVED":
        raise errors.ApiError(errors.ERR_PA_NOT_DRAWABLE, 409,
                              "Linked PA is not in a drawable (APPROVED) state.")
    # 11: expiry at draw time against the logical clock
    current = clock.current_date().isoformat()
    if current > pa["valid_through_date"]:
        pa["status"] = "EXPIRED"
        db.touch(pa)
        raise errors.ApiError(errors.ERR_PA_EXPIRED, 409,
                              "PA is past its valid_through_date.")
    # 14: unit budget
    if draw_qty > pa["remaining_units"]:
        raise errors.ApiError(errors.ERR_PA_UNITS_EXCEEDED, 409,
                              "Draw quantity exceeds remaining authorized units.")


def draw_pa_units(pa, qty):
    """Apply a draw: consume units, recompute remaining, auto-exhaust (PRD §3.6)."""
    pa["units_consumed"] += qty
    pa["remaining_units"] = pa["authorized_units"] - pa["units_consumed"]
    if pa["remaining_units"] == 0:
        pa["status"] = "EXHAUSTED"
    db.touch(pa)


def restore_pa_units(pa, qty):
    """Reverse a draw: restore units, revive EXHAUSTED -> APPROVED (PRD §3.6)."""
    pa["units_consumed"] -= qty
    pa["remaining_units"] = pa["authorized_units"] - pa["units_consumed"]
    if pa["status"] == "EXHAUSTED" and pa["remaining_units"] > 0:
        pa["status"] = "APPROVED"
    db.touch(pa)


# ---- Encounter coding helpers (PRD §3.3, §3.4, §3.5) ----

def code_encounter(encounter):
    """Run coverage + charge split across the exam line and all child procedures,
    recompute encounter totals (PRD §3.3 / §3.4 / §3.5). Caller advances status.
    """
    patient = db.patients[encounter["patient_id"]]
    practice = db.practices[patient["practice_id"]]
    fee_split = practice["fee_split_medicare_pct"]

    # Exam line is always COVERED.
    encounter["exam_coverage_decision"] = "COVERED"
    exam_medicare, exam_patient = calc.charge_split(
        encounter["exam_billed_cents"], encounter["exam_fee_cap_cents"],
        "COVERED", fee_split)

    total_medicare = exam_medicare
    total_patient = exam_patient

    children = _child_procedures(encounter["id"])
    for proc in children:
        decision = calc.procedure_coverage_decision(proc, patient, practice)
        proc["coverage_decision"] = decision
        medicare, patient_resp = calc.charge_split(
            proc["billed_cents"], proc["fee_cap_cents"], decision, fee_split)
        proc["medicare_pays_cents"] = medicare
        proc["patient_resp_cents"] = patient_resp
        db.touch(proc)
        total_medicare += medicare
        total_patient += patient_resp

    encounter["total_medicare_pays_cents"] = total_medicare
    encounter["total_patient_resp_cents"] = total_patient


def reset_encounter_charges(encounter):
    """Reset exam + child procedure coverage/charge fields and totals (PRD §3.3)."""
    encounter["exam_coverage_decision"] = "PENDING"
    encounter["total_medicare_pays_cents"] = 0
    encounter["total_patient_resp_cents"] = 0
    for proc in _child_procedures(encounter["id"]):
        proc["coverage_decision"] = "PENDING"
        proc["medicare_pays_cents"] = 0
        proc["patient_resp_cents"] = 0
        db.touch(proc)


def _child_procedures(encounter_id):
    return [p for p in db.procedures.values() if p["encounter_id"] == encounter_id]
