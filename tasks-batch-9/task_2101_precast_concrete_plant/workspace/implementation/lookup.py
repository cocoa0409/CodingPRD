"""Reference resolution (PRD 2.6). Each entity family has its own 404 code."""
import db
import errors


def _get(collection, row_id, error_id):
    if not isinstance(row_id, str) or row_id == "":
        errors.fail(error_id, "Referenced resource does not exist.")
    row = collection.get(row_id)
    if row is None:
        errors.fail(error_id, "Referenced resource does not exist.")
    return row


def project(row_id):
    return _get(db.store.projects, row_id, errors.ERR_PROJECT_NOT_FOUND)


def mix_design(row_id):
    return _get(db.store.mix_designs, row_id, errors.ERR_MIX_DESIGN_NOT_FOUND)


def steam_zone(row_id):
    return _get(db.store.steam_zones, row_id, errors.ERR_PLANT_RESOURCE_NOT_FOUND)


def casting_bed(row_id):
    return _get(db.store.casting_beds, row_id, errors.ERR_PLANT_RESOURCE_NOT_FOUND)


def yard_slot(row_id):
    return _get(db.store.yard_slots, row_id, errors.ERR_PLANT_RESOURCE_NOT_FOUND)


def bed_run(row_id):
    return _get(db.store.bed_runs, row_id, errors.ERR_BED_RUN_NOT_FOUND)


def curing_cycle(row_id):
    return _get(db.store.curing_cycles, row_id, errors.ERR_BED_RUN_NOT_FOUND)


def cylinder_set(row_id):
    return _get(db.store.cylinder_sets, row_id, errors.ERR_CYLINDER_SET_NOT_FOUND)


def piece(row_id):
    return _get(db.store.pieces, row_id, errors.ERR_PIECE_NOT_FOUND)


def yard_placement(row_id):
    return _get(db.store.yard_placements, row_id, errors.ERR_PIECE_NOT_FOUND)


def haul_permit(row_id):
    return _get(db.store.haul_permits, row_id, errors.ERR_HAUL_PERMIT_NOT_FOUND)


def shipment(row_id):
    return _get(db.store.shipments, row_id, errors.ERR_SHIPMENT_NOT_FOUND)


def repair_disposition(row_id):
    return _get(db.store.repair_dispositions, row_id,
                errors.ERR_REPAIR_DISPOSITION_NOT_FOUND)
