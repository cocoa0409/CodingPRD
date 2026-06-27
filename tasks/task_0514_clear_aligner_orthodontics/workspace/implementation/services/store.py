"""Lookup helpers over the in-memory store.

Path-referenced lookups raise ERR_NOT_FOUND (404); body FK lookups raise
ERR_FK_NOT_FOUND (404). Validation ordering per PRD §2.10 is enforced by the
order in which routes call these.
"""
from db import db
from errors import err


def _get_or(coll, _id, error_id):
    rec = coll.get(_id)
    if rec is None:
        raise err(error_id, "Resource not found: %s" % _id)
    return rec


# ---- path lookups (ERR_NOT_FOUND) ----
def get_patient(_id):
    return _get_or(db.patients, _id, "ERR_NOT_FOUND")


def get_clinician(_id):
    return _get_or(db.clinicians, _id, "ERR_NOT_FOUND")


def get_case(_id):
    return _get_or(db.cases, _id, "ERR_NOT_FOUND")


def get_plan(_id):
    return _get_or(db.plans, _id, "ERR_NOT_FOUND")


def get_step(_id):
    return _get_or(db.aligner_steps, _id, "ERR_NOT_FOUND")


def get_shipment(_id):
    return _get_or(db.shipments, _id, "ERR_NOT_FOUND")


def get_checkin(_id):
    return _get_or(db.checkins, _id, "ERR_NOT_FOUND")


def get_refinement(_id):
    return _get_or(db.refinements, _id, "ERR_NOT_FOUND")


def get_financing_plan(_id):
    return _get_or(db.financing_plans, _id, "ERR_NOT_FOUND")


def get_retainer(_id):
    return _get_or(db.retainers, _id, "ERR_NOT_FOUND")


def get_refund(_id):
    return _get_or(db.refunds, _id, "ERR_NOT_FOUND")


# ---- body FK lookups (ERR_FK_NOT_FOUND) ----
def fk_patient(_id):
    return _get_or(db.patients, _id, "ERR_FK_NOT_FOUND")


def fk_clinician(_id):
    return _get_or(db.clinicians, _id, "ERR_FK_NOT_FOUND")


def fk_case(_id):
    return _get_or(db.cases, _id, "ERR_FK_NOT_FOUND")


def fk_step(_id):
    return _get_or(db.aligner_steps, _id, "ERR_FK_NOT_FOUND")


def fk_checkin(_id):
    return _get_or(db.checkins, _id, "ERR_FK_NOT_FOUND")


def fk_financing_plan(_id):
    return _get_or(db.financing_plans, _id, "ERR_FK_NOT_FOUND")


# ---- reverse collections ----
def steps_for_case(case_id):
    return [s for s in db.aligner_steps.values() if s["case_id"] == case_id]


def checkins_for_case(case_id):
    return [c for c in db.checkins.values() if c["case_id"] == case_id]


def installments_for_plan(plan_id):
    return [i for i in db.installments.values()
            if i["financing_plan_id"] == plan_id]


def shipments_for_step(step_id):
    return [s for s in db.shipments.values() if s["step_id"] == step_id]


def financing_for_case(case_id):
    return [f for f in db.financing_plans.values() if f["case_id"] == case_id]
