"""Certification cascade: easement -> parcel -> area -> closure, plus certificate minting (PRD 3.5)."""

from core import db, dec, new_record, now, touch
from services import calc
from services.derive import (append_transfer, close_sending_area, easement_of_parcel,
                             recompute_easement_units, recompute_party_holdings,
                             recompute_sending_area_severed)


def certify_application(app, actor_user_id):
    parcel = db.sending_parcels[app["sending_parcel_id"]]
    area = db.sending_areas[parcel["sending_area_id"]]
    allocated = int(app["allocated_units"] or 0)

    app["status"] = "CERTIFIED"
    app["certified_by_user_id"] = actor_user_id
    touch(app)

    baseline = int(parcel["baseline_allocation_units"])
    cumulative_severed = int(parcel["severed_units"]) + allocated

    # --- link one: create or amend the conservation easement -----------------
    easement = easement_of_parcel(parcel["id"])
    if easement is None:
        easement = new_record(
            {
                "sending_parcel_id": parcel["id"],
                "severance_application_id": app["id"],
                "recording_reference": "EAS-%s-1" % parcel["apn"],
                "restricted_acres": dec("0.00"),
                "permitted_residual_units": 0,
                "units_issued_total": 0,
                "units_redeemed_confirmed": 0,
                "units_retired": 0,
                "units_outstanding": 0,
                "amendment_count": 0,
                "recording_status": "RECORDED",
                "compliance_status": "COMPLIANT",
                "recorded_at": now(),
                "last_inspection_at": None,
                "prior_violation_count": 0,
                "cure_deadline": None,
            }
        )
        db.conservation_easements[easement["id"]] = easement
    else:
        easement["amendment_count"] = int(easement["amendment_count"]) + 1
        easement["recording_status"] = "AMENDED"
        easement["recording_reference"] = "EAS-%s-%d" % (parcel["apn"], easement["amendment_count"] + 1)
        # `severance_application_id` continues to name the application that first
        # created the easement, and `recorded_at` is never rewritten.
        touch(easement)

    # --- link two: restriction extent, issuance totals, parcel roll-up ------
    restricted_acres, permitted_residual = calc.easement_restriction_extent(
        parcel["gross_acres"], baseline, cumulative_severed, parcel["existing_dwelling_units"]
    )
    easement["restricted_acres"] = restricted_acres
    easement["permitted_residual_units"] = permitted_residual
    easement["units_issued_total"] = int(easement["units_issued_total"]) + allocated

    parcel["easement_status"] = "RECORDED"
    parcel["restricted_acres"] = restricted_acres
    parcel["severed_units"] = cumulative_severed
    parcel["remaining_units"] = baseline - cumulative_severed
    parcel["parcel_status"] = "FULLY_SEVERED" if parcel["remaining_units"] <= 0 else "PARTIALLY_SEVERED"
    touch(parcel)

    # --- link three: sending area roll-up -----------------------------------
    area["issued_certificate_count"] = int(area["issued_certificate_count"]) + 1
    recompute_sending_area_severed(area)
    touch(area)

    # --- mint the root certificate and open its chain of title --------------
    serial = "TDR-%s-%05d" % (area["code"], int(area["issued_certificate_count"]))
    cert = new_record(
        {
            "conservation_easement_id": easement["id"],
            "holder_party_id": app["applicant_party_id"],
            "parent_certificate_id": None,
            "origin_sending_area_id": area["id"],
            "serial_number": serial,
            "origin_neighborhood_code": area["neighborhood_code"],
            "generation": 1,
            "split_count": 0,
            "units_face": allocated,
            "units_remaining": allocated,
            "units_split_out": 0,
            "units_encumbered": 0,
            "units_redeemed": 0,
            "units_retired": 0,
            "lifecycle_status": "ISSUED",
            "market_status": "HELD",
            "issued_at": now(),
        }
    )
    db.certificates[cert["id"]] = cert
    append_transfer(cert, "ISSUANCE", None, app["applicant_party_id"], allocated, price_cents=None)

    recompute_easement_units(easement)
    recompute_party_holdings(db.parties.get(app["applicant_party_id"]))

    # --- link four: cap exhaustion closes the area --------------------------
    if area["status"] == "ACTIVE" and int(area["severed_units_total"]) >= int(area["sending_cap_units"]):
        close_sending_area(area)

    return cert
