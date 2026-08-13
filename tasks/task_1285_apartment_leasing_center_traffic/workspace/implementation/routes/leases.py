"""Lease endpoints (generation with OCC, e-signature, countersign, cancel)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import DB, clock_now, new_id
from errors import ApiError
from middleware import APPLICANT, AGENT, PM, auth
from response import ok, ok_list
from services import (
    OVERRIDE_FLOOR_PCT,
    SIGNING_WINDOW_HOURS,
    conversion_cascade,
    get_application,
    get_lease,
    lease_cancel_cascade,
    round_half_up_cents,
    ser_lease,
    sorted_created,
    stamp,
    touch,
)
from util import (
    apply_filters,
    as_nonneg_int,
    as_str,
    body,
    pagination,
    required,
)

bp = Blueprint("leases", __name__)

STAFF = [PM, AGENT]


@bp.post("/leasing/leases")
def create_lease():
    auth([PM])
    data = body()
    application_id = as_str(required(data, "application_id"), "application_id")
    expected = required(data, "expected_application_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "expected_application_version must be an integer",
        )
    pricing_offer_id = data.get("pricing_offer_id")
    if pricing_offer_id is not None:
        as_str(pricing_offer_id, "pricing_offer_id")
    rent_override_cents = data.get("rent_override_cents")
    if rent_override_cents is not None:
        rent_override_cents = as_nonneg_int(rent_override_cents, "rent_override_cents")

    # Existence (priority 3).
    app = DB["applications"].get(application_id)
    if app is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application does not exist")
    offer = None
    if pricing_offer_id is not None:
        offer = DB["offers"].get(pricing_offer_id)
        if offer is None:
            raise ApiError(
                "ERR_PRICING_OFFER_NOT_FOUND", 404, "Pricing offer does not exist"
            )

    # State checks (priority 4): per-entity invalid-state family, then the
    # pipeline gate, then the OCC stale-version rejection (PRD §2.10 order).
    if offer is not None and offer["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_PRICING_OFFER_INVALID_STATE",
            409,
            "A lease can only pin a PUBLISHED pricing offer",
        )
    if app["status"] not in ("APPROVED", "CONDITIONS_CLEARED"):
        raise ApiError(
            "ERR_APPLICATION_NOT_LEASABLE",
            409,
            "Lease generation requires an APPROVED or CONDITIONS_CLEARED application",
        )
    if expected != app["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_application_version does not match the application's version",
        )

    # Uniqueness (priority 6): no regeneration once a lease is committed.
    for l in DB["leases"].values():
        if l["application_id"] == application_id and l["status"] in (
            "SIGNED_BY_APPLICANT",
            "EXECUTED",
        ):
            raise ApiError(
                "ERR_LEASE_ALREADY_COMMITTED",
                409,
                "A SIGNED_BY_APPLICANT or EXECUTED lease exists for this application",
            )

    # Cross-reference integrity (priority 8).
    if offer is not None and offer["floorplan_id"] != app["floorplan_id"]:
        raise ApiError(
            "ERR_OFFER_FLOORPLAN_MISMATCH",
            422,
            "pricing_offer_id belongs to a different floorplan than the application's",
        )

    # Rent pinning precedence: valid override > selected offer > floorplan base.
    fp = DB["floorplans"][app["floorplan_id"]]
    computed = (
        offer["effective_monthly_rent_cents"] if offer else fp["base_rent_cents"]
    )
    if rent_override_cents is not None:
        floor = round_half_up_cents(OVERRIDE_FLOOR_PCT * Decimal(computed))
        if rent_override_cents < floor:
            raise ApiError(
                "ERR_RENT_OVERRIDE_TOO_LOW",
                422,
                "rent_override_cents is below 80% of the computed monthly rent",
            )
        monthly_rent_cents = rent_override_cents
    else:
        monthly_rent_cents = computed

    prop = DB["properties"][fp["property_id"]]
    now = clock_now()
    rec = {
        "id": new_id(),
        "application_id": application_id,
        "floorplan_id": app["floorplan_id"],
        "monthly_rent_cents": monthly_rent_cents,
        "deposit_cents": app["required_deposit_cents"],
        "addenda_codes": list(prop["required_addenda"]),
        "signing_deadline": now + timedelta(hours=SIGNING_WINDOW_HOURS),
        "signed_at": None,
        "executed_at": None,
        "superseded_by_id": None,
        "status": "ISSUED",
    }
    stamp(rec)
    DB["leases"][rec["id"]] = rec

    # Supersede any prior ISSUED lease for the same application.
    for l in DB["leases"].values():
        if (
            l["application_id"] == application_id
            and l["status"] == "ISSUED"
            and l["id"] != rec["id"]
        ):
            l["status"] = "SUPERSEDED"
            l["superseded_by_id"] = rec["id"]
            touch(l)

    # Generation advances the application's version by one (PRD §2.8).
    touch(app)
    return ok(ser_lease(rec), status=201)


@bp.get("/leasing/leases")
def list_leases():
    auth(STAFF)
    limit, offset = pagination()
    items = apply_filters(
        DB["leases"].values(),
        [
            ("application_id", "application_id"),
            ("floorplan_id", "floorplan_id"),
            ("status", "status"),
        ],
    )
    items = sorted_created(items)
    total = len(items)
    return ok_list(
        [ser_lease(l) for l in items[offset : offset + limit]], total, limit, offset
    )


@bp.get("/leasing/leases/<lid>")
def get_one_lease(lid):
    auth([PM, AGENT, APPLICANT])
    return ok(ser_lease(get_lease(lid)))


@bp.post("/leasing/leases/<lid>/sign")
def sign_lease(lid):
    user_id, role = auth([APPLICANT])
    lease = get_lease(lid)
    # Signature identity: X-User-ID must equal the lease's application_id.
    if user_id != lease["application_id"]:
        raise ApiError(
            "ERR_APPLICANT_MISMATCH",
            403,
            "Lease sign caller's X-User-ID does not equal the lease's application_id",
        )
    if lease["status"] != "ISSUED" or clock_now() >= lease["signing_deadline"]:
        raise ApiError(
            "ERR_LEASE_INVALID_STATE",
            409,
            "Only an ISSUED lease inside its signing window can be signed",
        )
    lease["signed_at"] = clock_now()
    lease["status"] = "SIGNED_BY_APPLICANT"
    touch(lease)
    return ok(ser_lease(lease))


@bp.post("/leasing/leases/<lid>/countersign")
def countersign_lease(lid):
    auth([PM])
    lease = get_lease(lid)
    if lease["status"] != "SIGNED_BY_APPLICANT":
        raise ApiError(
            "ERR_LEASE_INVALID_STATE",
            409,
            "Only a SIGNED_BY_APPLICANT lease can be countersigned",
        )
    lease["status"] = "EXECUTED"
    lease["executed_at"] = clock_now()
    touch(lease)
    app = DB["applications"].get(lease["application_id"])
    if app is not None:
        conversion_cascade(app)
    return ok(ser_lease(lease))


@bp.post("/leasing/leases/<lid>/cancel")
def cancel_lease(lid):
    auth([PM])
    lease = get_lease(lid)
    if lease["status"] not in ("ISSUED", "SIGNED_BY_APPLICANT", "EXECUTED"):
        raise ApiError(
            "ERR_LEASE_INVALID_STATE",
            409,
            "Only an ISSUED, SIGNED_BY_APPLICANT, or EXECUTED lease can be cancelled",
        )
    was_executed = lease["status"] == "EXECUTED"
    lease["status"] = "CANCELLED"
    touch(lease)
    lease_cancel_cascade(lease, was_executed)
    return ok(ser_lease(lease))
