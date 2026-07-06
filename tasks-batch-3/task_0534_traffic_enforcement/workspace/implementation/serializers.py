"""Serializers: build the public JSON view of each entity, including computed fields.

Stored records keep raw fields plus internal (_-prefixed) fields. Serializers
strip internals and surface computed values.
"""
from calculations import amount_owed_total
from clock import parse_iso


def _strip(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_camera(db, camera):
    out = _strip(camera)
    # certified_until_clock = latest PASS calibration valid_until_utc for this camera
    latest = None
    for cr in db.calibrations.values():
        if cr["camera_id"] != camera["id"]:
            continue
        if cr["result"] != "PASS":
            continue
        vu = parse_iso(cr["valid_until_utc"])
        if latest is None or vu > latest:
            latest = vu
            latest_str = cr["valid_until_utc"]
    out["certified_until_clock"] = (latest_str if latest is not None else None)
    return out


def serialize_citation(db, citation):
    out = _strip(citation)
    program = db.programs.get(citation["program_id"])
    if program is not None:
        out["amount_owed_total"] = amount_owed_total(program, citation)
    return out


def serialize_program(db, program):
    return _strip(program)


def serialize_owner(db, owner):
    return _strip(owner)


def serialize_calibration(db, cr):
    return _strip(cr)


def serialize_contest(db, contest):
    return _strip(contest)


def serialize_hearing(db, hearing):
    return _strip(hearing)


def serialize_payment(db, payment):
    return _strip(payment)


def serialize_vendor_contract(db, vc):
    return _strip(vc)


def serialize_notice(db, notice):
    return _strip(notice)
