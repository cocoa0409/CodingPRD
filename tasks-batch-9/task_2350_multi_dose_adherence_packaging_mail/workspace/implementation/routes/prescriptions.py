"""Mid-cycle regimen change: supersede, mint a successor, unwind the roll."""

from flask import Blueprint

import calc
import db
import engine
import enums
import middleware
import response
import store
import validators
from errors import ApiError

bp = Blueprint("prescriptions", __name__)

REVERTABLE_CYCLE_STATUSES = (
    "DRAFT",
    "LINES_ADJUDICATED",
    "ROLL_GENERATED",
    "PACKED",
    "VERIFIED",
)


@bp.post("/prescriptions/<prescription_id>/regimen-change")
def regimen_change(prescription_id):
    middleware.authenticate(("Prescriber",))
    body = validators.json_body()
    new_drug_name = validators.string(body, "new_drug_name")
    new_form = validators.enum(body, "new_form", enums.FORMS)
    new_copay_tier = validators.enum(body, "new_copay_tier", enums.COPAY_TIERS)
    new_dose_times = validators.string_array(
        body, "new_dose_times", non_empty=True, distinct=True, allowed=enums.DOSE_SLOTS
    )
    new_quantity_per_dose = validators.integer(body, "new_quantity_per_dose", minimum=1)
    expected_prescription_version = validators.integer(
        body, "expected_prescription_version"
    )
    new_ndc = validators.string(body, "new_ndc", required=False, default=None)
    new_strength = validators.string(body, "new_strength", required=False, default=None)
    new_days_supply_written = validators.integer(
        body, "new_days_supply_written", required=False, default=None,
        minimum=1, maximum=90,
    )
    validators.string(body, "change_reason", required=False, default=None)

    prescription = middleware.lookup("prescription", prescription_id)

    if expected_prescription_version != prescription["version"]:
        raise ApiError("ERR_STALE_PRESCRIPTION_VERSION")
    if prescription["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PRESCRIPTION_STATE")

    prescription["status"] = "SUPERSEDED"
    store.touch(prescription)

    successor = store.create(
        db.prescriptions,
        {
            "patient_id": prescription["patient_id"],
            "prescriber_npi": prescription["prescriber_npi"],
            "drug_name": new_drug_name,
            "ndc": new_ndc if new_ndc is not None else prescription["ndc"],
            "strength": (
                new_strength if new_strength is not None else prescription["strength"]
            ),
            "form": new_form,
            "copay_tier": new_copay_tier,
            "refrigerated": prescription["refrigerated"],
            "is_controlled": prescription["is_controlled"],
            "packable": calc.is_packable(new_form, prescription["refrigerated"]),
            "dose_times": list(new_dose_times),
            "quantity_per_dose": new_quantity_per_dose,
            "days_supply_written": (
                new_days_supply_written
                if new_days_supply_written is not None
                else prescription["days_supply_written"]
            ),
            "refills_authorized": prescription["refills_authorized"],
            "refills_remaining": prescription["refills_remaining"],
            "refills_consumed": prescription["refills_consumed"],
            "written_date": prescription["written_date"],
            "expiration_date": prescription["expiration_date"],
            "status": "ACTIVE",
            "supersedes_rx_id": prescription["id"],
            "last_dispensed_date": None,
            "last_dispensed_days_supply": 0,
            "prior_last_dispensed_date": None,
            "prior_last_dispensed_days_supply": 0,
            "days_dispensed_total": 0,
            "sync_bridge_days": 0,
            "sync_trim_days": 0,
        },
    )

    # Cascade one: supersede the lines that were built on the old regimen.
    affected_cycles = []
    for line in engine.lines_of_prescription(prescription_id):
        cycle = db.fill_cycles[line["cycle_id"]]
        if cycle["packaging_status"] not in REVERTABLE_CYCLE_STATUSES:
            continue
        line["line_status"] = "SUPERSEDED_PENDING_REISSUE"
        line["hold_reason"] = "REGIMEN_CHANGE"
        store.touch(line)
        if cycle["id"] not in [c["id"] for c in affected_cycles]:
            affected_cycles.append(cycle)

    # Cascade two: the cycle needs a reissue and its roll must be rebuilt.
    for cycle in affected_cycles:
        cycle["reissue_required"] = True
        if cycle["packaging_status"] in ("PACKED", "VERIFIED"):
            cycle["packaging_status"] = "ROLL_GENERATED"
        store.touch(cycle)

        # Cascade three: a staged pouch-roll parcel no longer carries the truth.
        for shipment in engine.shipments_of_cycle(cycle["id"]):
            if (
                shipment["status"] == "STAGED"
                and shipment["shipment_kind"] == "POUCH_ROLL"
            ):
                shipment["status"] = "CANCELLED"
                store.touch(shipment)

    store.commit()
    return response.object_response(store.serialize(successor), 201)
