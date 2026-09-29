"""Foreign-key and path-parameter resolution, each raising its own not-found
error id (PRD 2.8 ranks 6 through 18)."""

import store
from errors import ApiError


def _get(collection, key, error_id, label):
    row = collection.get(key) if isinstance(key, str) else None
    if row is None:
        raise ApiError(error_id, "%s %s was not found." % (label, key))
    return row


def program(key):
    return _get(store.programs, key, "ERR_PROGRAM_NOT_FOUND", "CustomerProgram")


def material_spec(key):
    return _get(store.material_specs, key, "ERR_MATERIAL_SPEC_NOT_FOUND",
                "MaterialSpec")


def design(key):
    return _get(store.designs, key, "ERR_DESIGN_NOT_FOUND", "SpringDesign")


def characteristic(key):
    return _get(store.characteristics, key, "ERR_CHARACTERISTIC_NOT_FOUND",
                "CriticalCharacteristic")


def tooling(key):
    return _get(store.tooling_assets, key, "ERR_TOOLING_NOT_FOUND", "ToolingAsset")


def wire_lot(key):
    return _get(store.wire_lots, key, "ERR_WIRE_LOT_NOT_FOUND", "WireLot")


def machine(key):
    return _get(store.machines, key, "ERR_MACHINE_NOT_FOUND", "CoilingMachine")


def setup(key):
    return _get(store.setups, key, "ERR_SETUP_NOT_FOUND", "MachineSetup")


def run(key):
    return _get(store.runs, key, "ERR_RUN_NOT_FOUND", "ProductionRun")


def inspection_record(key):
    return _get(store.inspection_records, key, "ERR_NOT_FOUND", "InspectionRecord")


def oven(key):
    return _get(store.ovens, key, "ERR_OVEN_NOT_FOUND", "StressReliefOven")


def batch(key):
    return _get(store.batches, key, "ERR_BATCH_NOT_FOUND", "HeatTreatBatch")


def submission(key):
    return _get(store.submissions, key, "ERR_SUBMISSION_NOT_FOUND",
                "QualificationSubmission")


def lot(key):
    return _get(store.lots, key, "ERR_LOT_NOT_FOUND", "ShipmentLot")


def unique_code(collection, field, value):
    for row in collection.values():
        if row.get(field) == value:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "%s '%s' already exists." % (field, value))
