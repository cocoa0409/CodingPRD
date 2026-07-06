"""Existence lookups -> ERR_NOT_FOUND (404) on miss (validation priority 20)."""
import errors
from db import db


def _get(store, id_, label):
    rec = store.get(id_)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, f"{label} not found")
    return rec


def case(id_):
    return _get(db.cases, id_, "Case")


def investigator(id_):
    return _get(db.investigators, id_, "Investigator")


def pathologist(id_):
    return _get(db.pathologists, id_, "Pathologist")


def cooler_unit(id_):
    return _get(db.cooler_units, id_, "CoolerUnit")


def body(id_):
    return _get(db.bodies, id_, "Body")


def autopsy_exam(id_):
    return _get(db.autopsy_exams, id_, "AutopsyExam")


def specimen(id_):
    return _get(db.specimens, id_, "Specimen")


def tox_screen(id_):
    return _get(db.tox_screens, id_, "ToxScreen")


def death_certificate(id_):
    return _get(db.death_certificates, id_, "DeathCertificate")


def next_of_kin(id_):
    return _get(db.next_of_kin, id_, "NextOfKin")


def property_item(id_):
    return _get(db.property_items, id_, "PropertyItem")


def property_release(id_):
    return _get(db.property_releases, id_, "PropertyRelease")


def indigent_disposition(id_):
    return _get(db.indigent_dispositions, id_, "IndigentDisposition")
