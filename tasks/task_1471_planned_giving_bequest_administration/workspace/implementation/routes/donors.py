"""Donors: register, list, read, record-death cascade, legacy society (PRD 3.1)."""
from flask import Blueprint, g

import store
from calc import LEGACY_THRESHOLD_CENTS
from domain import (
    ANNUITY_VEHICLES,
    DOCUMENTED_STATUSES,
    donor_view,
    lookup,
    matches,
    paginate,
    sort_created,
    update_reserve,
)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from store import base_fields, touch
from validate import get_body, validate_body

bp = Blueprint("donors", __name__)

LEGACY_ACTIONS = ("ENROLL", "RECOGNIZE", "REVOKE")


@bp.post("/giving/donors")
@require_roles("GiftOfficer")
def create_donor():
    body = get_body()
    validate_body(
        body,
        {
            "full_name": ("str", True, None),
            "date_of_birth": ("datetime", True, None),
            "contact_email": ("str", False, None),
        },
    )
    donor = base_fields()
    donor.update(
        {
            "full_name": body["full_name"],
            "date_of_birth": body["date_of_birth"],
            "contact_email": body.get("contact_email"),
            "vital_status": "LIVING",
            "deceased_on": None,
            "legacy_society_status": "NONE",
        }
    )
    store.donors[donor["id"]] = donor
    return success(donor_view(donor), 201)


@bp.get("/giving/donors")
@require_roles(*ALL_ROLES)
def list_donors():
    items = [
        d
        for d in sort_created(store.donors.values())
        if matches(d, {"vital_status": None, "legacy_society_status": None})
    ]
    page, meta = paginate(items)
    return success([donor_view(d) for d in page], 200, meta)


@bp.get("/giving/donors/<donor_id>")
@require_roles(*ALL_ROLES)
def get_donor(donor_id):
    return success(donor_view(lookup(store.donors, donor_id, "Donor")), 200)


@bp.post("/giving/donors/<donor_id>/record-death")
@require_roles("EstateManager")
def record_death(donor_id):
    donor = lookup(store.donors, donor_id, "Donor")
    if donor["vital_status"] != "LIVING":
        raise ApiError("ERR_INVALID_STATE", 409, "Donor is already DECEASED")
    body = get_body()
    validate_body(body, {"deceased_on": ("datetime", True, None)})

    donor["vital_status"] = "DECEASED"
    donor["deceased_on"] = body["deceased_on"]

    # HOP 1/1b: mature this donor's agreements in created_at ASC order
    for agreement in sort_created(
        [a for a in store.agreements.values() if a["donor_id"] == donor["id"]]
    ):
        if (
            agreement["status"] in ("EXECUTED", "FUNDED", "ACTIVE", "SUSPENDED")
            and agreement["vehicle_type"] in ANNUITY_VEHICLES
        ):
            # house rule: annuity vehicles mature on donor death regardless of lives
            agreement["status"] = "MATURED"
            touch(agreement)
            # HOP 2: lapse open payments with DONOR_DEATH
            for p in store.payments.values():
                if p["gift_agreement_id"] == agreement["id"] and p["status"] in (
                    "SCHEDULED",
                    "DUE",
                    "DEFERRED",
                ):
                    p["status"] = "LAPSED"
                    p["lapse_reason"] = "DONOR_DEATH"
                    touch(p)
        elif agreement["vehicle_type"] == "BEQUEST" and agreement["status"] in (
            "EXECUTED",
            "FUNDED",
        ):
            agreement["status"] = "MATURED"
            touch(agreement)
            # HOP 1b: auto-create the estate for the matured bequest
            estate = base_fields()
            estate.update(
                {
                    "donor_id": donor["id"],
                    "gift_agreement_id": agreement["id"],
                    "status": "NOTIFIED",
                    "notified_on": body["deceased_on"],
                    "recorded_by_user_id": g.user_id,
                    "alternate_valuation_elected": False,
                    "administration_costs_cents": 0,
                    "specific_bequests_cents": 0,
                    "residual_to_university_cents": None,
                    "distributed_on": None,
                }
            )
            store.estates[estate["id"]] = estate

    # HOP 3/4: reserve booked target / coverage / posture recompute
    update_reserve()
    touch(donor)
    return success(donor_view(donor), 200)


@bp.post("/giving/donors/<donor_id>/legacy-society-transition")
@require_roles("GiftOfficer")
def legacy_society_transition(donor_id):
    donor = lookup(store.donors, donor_id, "Donor")
    body = get_body()
    validate_body(body, {"action": ("str", True, LEGACY_ACTIONS)})
    action = body["action"]
    status = donor["legacy_society_status"]

    if action == "ENROLL":
        if status not in ("NONE", "REVOKED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot ENROLL from %s" % status
            )
        if donor["vital_status"] != "LIVING":
            raise ApiError(
                "ERR_DONOR_STATE_MISMATCH", 409, "Donor must be LIVING to enroll"
            )
        documented = any(
            a["donor_id"] == donor["id"] and a["status"] in DOCUMENTED_STATUSES
            for a in store.agreements.values()
        )
        if not documented:
            raise ApiError(
                "ERR_LEGACY_SOCIETY_INELIGIBLE",
                422,
                "ENROLL requires a documented planned gift",
            )
        donor["legacy_society_status"] = "ENROLLED"
    elif action == "RECOGNIZE":
        if status != "ENROLLED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot RECOGNIZE from %s" % status
            )
        if donor_view(donor)["documented_gift_total_cents"] < LEGACY_THRESHOLD_CENTS:
            raise ApiError(
                "ERR_LEGACY_SOCIETY_INELIGIBLE",
                422,
                "documented_gift_total_cents below the recognition threshold",
            )
        donor["legacy_society_status"] = "RECOGNIZED"
    else:  # REVOKE
        if status not in ("ENROLLED", "RECOGNIZED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot REVOKE from %s" % status
            )
        donor["legacy_society_status"] = "REVOKED"

    touch(donor)
    return success(donor_view(donor), 200)
