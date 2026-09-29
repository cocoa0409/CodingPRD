"""Encounters (two parallel state dimensions) and inability-to-pay waivers."""

from flask import Blueprint

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, owner_ref, require, segregation, state
from services import cascade
from services import charge
from services import fee_schedule as fs
from services import health_center as hc_svc
from validation import Field, pagination, parse_body

bp = Blueprint("encounters", __name__)

PAYER_TYPES = ("SELF_PAY", "MEDICAID_MCO", "MEDICAID_FFS", "MEDICARE", "PRIVATE")
VOID_REASONS = ("DUPLICATE", "CODING_ERROR", "NONPAYMENT", "SITE_OUT_OF_SCOPE")

CREATE_FIELDS = [
    Field("patient_id", "string", required=True),
    Field("service_site_id", "string", required=True),
    Field("service_definition_id", "string", required=True),
    Field("encounter_date", "datetime", required=True),
    Field("payer_type", "enum", required=True, enum=PAYER_TYPES),
    Field("gross_charge_cents", "integer", required=True, exclusive_min=0),
    Field("income_verification_id", "string", nullable=True),
]


def _bump_grantee(enc):
    hc = hc_svc.health_center_of_encounter(enc)
    if hc is not None:
        hc_svc.bump(hc)


@bp.post("/encounters")
def create_encounter():
    authorize("BillingSpecialist")
    body = parse_body(CREATE_FIELDS)

    # Rung 7 — foreign keys in the field order declared in §1.1.
    patient = require("patients", body["patient_id"])
    site = require("service_sites", body["service_site_id"])
    service = require("service_definitions", body["service_definition_id"])
    supplied_verification = None
    if body.get("income_verification_id") is not None:
        supplied_verification = require(
            "income_verifications", body["income_verification_id"]
        )

    # Rung 8 — the site and the service must share one grantee.
    if site["health_center_id"] != service["health_center_id"]:
        raise ApiError("ERR_CROSS_GRANTEE_REFERENCE")

    encounter_date = body["encounter_date"]

    # Rung 23 — no future dates of service.
    if encounter_date > db.now():
        raise ApiError("ERR_ENCOUNTER_DATE_IN_FUTURE")

    # Rung 27 — an explicitly supplied verification must be VERIFIED and cover
    # the date of service on the closed window.
    if supplied_verification is not None:
        if supplied_verification["status"] != "VERIFIED" or not fs.verification_window_covers(
            supplied_verification, encounter_date
        ):
            raise ApiError("ERR_VERIFICATION_DOES_NOT_COVER_ENCOUNTER")

    # Rung 33 — the site is in scope.
    if site["status"] != "IN_SCOPE":
        raise ApiError("ERR_SITE_NOT_IN_SCOPE")

    # Rung 34 — an administrative site never carries an encounter.
    if site["site_type"] == "ADMINISTRATIVE":
        raise ApiError("ERR_ADMINISTRATIVE_SITE_NOT_BILLABLE")

    # Rung 35 — the service is in scope.
    if service["status"] != "IN_SCOPE":
        raise ApiError("ERR_SERVICE_NOT_IN_SCOPE")

    hc = db.db.health_centers.get(site["health_center_id"])
    if hc is None:
        raise ApiError("ERR_HEALTH_CENTER_NOT_FOUND")

    # Rung 36 — the fee-schedule selector must return a row.
    schedule = fs.select_schedule_for_health_center(hc["id"], encounter_date)
    if schedule is None:
        raise ApiError("ERR_NO_EFFECTIVE_FEE_SCHEDULE")

    # E1 and E2 are already frozen on the verification row; E3 computes the
    # provisional patient charge.
    verification = supplied_verification
    if verification is None:
        verification = fs.select_verification(patient["id"], encounter_date)

    result = charge.patient_charge(
        body["payer_type"], body["gross_charge_cents"], schedule, verification
    )

    row = db.base_row()
    row.update(
        {
            "patient_id": patient["id"],
            "service_site_id": site["id"],
            "service_definition_id": service["id"],
            "fee_schedule_id": schedule["id"],
            "income_verification_id": result["income_verification_id"],
            "pinned_discount_tier_id": result["pinned_discount_tier_id"],
            "encounter_date": encounter_date,
            "payer_type": body["payer_type"],
            "gross_charge_cents": body["gross_charge_cents"],
            "patient_charge_cents": result["patient_charge_cents"],
            "charge_basis": result["charge_basis"],
            "sliding_fee_applied": result["sliding_fee_applied"],
            "charge_adjustment_cents": 0,
            "waived_amount_cents": 0,
            "pps_encounter_rate_cents": charge.pps_encounter_rate(
                hc, site, service, body["payer_type"]
            ),
            "mco_paid_cents": 0,
            "wraparound_due_cents": 0,
            "pps_claim_status": "UNBILLED",
            "wraparound_status": "NOT_APPLICABLE",
            "claim_reference": None,
            "void_reason": None,
        }
    )

    # E5 and E6 — the residual is computed once the counted portion is known.
    row["wraparound_due_cents"] = charge.wraparound_due(row)

    db.db.encounters[row["id"]] = row

    db.touch(patient)
    hc_svc.bump(hc)
    return object_response(serializers.encounter(row), 201)


@bp.get("/encounters/<encounter_id>")
def read_encounter(encounter_id):
    authorize(*ALL_ROLES)
    return object_response(serializers.encounter(require("encounters", encounter_id)))


@bp.get("/encounters")
def list_encounters():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    return listing(
        db.all_rows("encounters"),
        serializers.encounter,
        limit,
        offset,
        specs=[
            ("patient_id", "patient_id", "string"),
            ("service_site_id", "service_site_id", "string"),
            ("service_definition_id", "service_definition_id", "string"),
            ("fee_schedule_id", "fee_schedule_id", "string"),
            ("income_verification_id", "income_verification_id", "string"),
            ("pinned_discount_tier_id", "pinned_discount_tier_id", "string"),
            ("pps_claim_status", "pps_claim_status", "string"),
            ("wraparound_status", "wraparound_status", "string"),
            ("payer_type", "payer_type", "string"),
        ],
    )


@bp.post("/encounters/<encounter_id>/bill")
def bill_encounter(encounter_id):
    authorize("BillingSpecialist")
    body = parse_body([Field("claim_reference", "string", required=True)])
    enc = require("encounters", encounter_id)

    state(enc, "pps_claim_status", ("UNBILLED", "PENDING_ADJUSTMENT"))

    # Rung 33 — a site that left scope cannot be billed against.
    site = db.db.service_sites.get(enc["service_site_id"])
    if site is None or site["status"] != "IN_SCOPE":
        raise ApiError("ERR_SITE_NOT_IN_SCOPE")

    enc["pps_claim_status"] = "BILLED"
    enc["claim_reference"] = body["claim_reference"]
    db.touch(enc)
    return object_response(serializers.encounter(enc))


@bp.post("/encounters/<encounter_id>/record-payment")
def record_payment(encounter_id):
    authorize("BillingSpecialist")
    body = parse_body([Field("mco_paid_cents", "integer", required=True, minimum=0)])
    enc = require("encounters", encounter_id)

    state(enc, "pps_claim_status", ("BILLED",))

    # Rung 42 — a payer may not post more than the allowable PPS rate.
    if body["mco_paid_cents"] > enc["pps_encounter_rate_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_PPS_RATE")

    enc["mco_paid_cents"] = body["mco_paid_cents"]
    enc["pps_claim_status"] = "PAID"

    if enc["payer_type"] == "MEDICAID_MCO":
        enc["wraparound_due_cents"] = charge.wraparound_due(enc)
        if enc["wraparound_due_cents"] > 0 and enc["wraparound_status"] in (
            "NOT_APPLICABLE",
            "PENDING",
        ):
            enc["wraparound_status"] = "PENDING"
    else:
        enc["wraparound_due_cents"] = 0
        enc["wraparound_status"] = "NOT_APPLICABLE"
        # A non-MCO payer reconciles in the same request.
        enc["pps_claim_status"] = "RECONCILED"

    db.touch(enc)
    _bump_grantee(enc)
    return object_response(serializers.encounter(enc))


@bp.post("/encounters/<encounter_id>/claim-wraparound")
def claim_wraparound(encounter_id):
    authorize("BillingSpecialist")
    body = parse_body([Field("receipt_confirmed", "boolean")])
    enc = require("encounters", encounter_id)

    confirmed = bool(body.get("receipt_confirmed", False))
    if confirmed:
        state(enc, "wraparound_status", ("CLAIMED",))
        enc["wraparound_status"] = "RECEIVED"
        # The only coupling between the two dimensions.
        if enc["pps_claim_status"] == "PAID":
            enc["pps_claim_status"] = "RECONCILED"
    else:
        state(enc, "wraparound_status", ("PENDING", "REBILL_REQUIRED"))
        enc["wraparound_status"] = "CLAIMED"

    db.touch(enc)
    _bump_grantee(enc)
    return object_response(serializers.encounter(enc))


@bp.post("/encounters/<encounter_id>/void")
def void_encounter(encounter_id):
    authorize("BillingSpecialist")
    body = parse_body([Field("void_reason", "enum", required=True, enum=VOID_REASONS)])
    enc = require("encounters", encounter_id)

    state(
        enc,
        "pps_claim_status",
        ("UNBILLED", "BILLED", "PAID", "PENDING_ADJUSTMENT"),
    )

    # Rung 17 — the inability-to-pay protection.
    if body["void_reason"] == "NONPAYMENT" and charge.granted_waiver(enc["id"]) is not None:
        raise ApiError("ERR_INABILITY_TO_PAY_PROTECTED")

    cascade.void_encounter(enc, body["void_reason"])
    _bump_grantee(enc)
    return object_response(serializers.encounter(enc))


# --------------------------------------------------------------------------- #
# inability-to-pay waivers
# --------------------------------------------------------------------------- #


@bp.post("/encounters/<encounter_id>/waivers")
def request_waiver(encounter_id):
    user_id = authorize("PatientServicesRep")
    body = parse_body(
        [Field("encounter_id", "string"), Field("waiver_reason", "string", required=True)]
    )
    enc = require("encounters", encounter_id)
    owner_ref(body, "encounter_id", "encounters", encounter_id)

    # Rung 18 — only the pinned nominal fee is protected.
    schedule = db.db.fee_schedules.get(enc["fee_schedule_id"])
    if (
        enc["charge_basis"] != "SLIDING_FEE_TIER"
        or schedule is None
        or enc["patient_charge_cents"] != schedule["nominal_fee_cents"]
    ):
        raise ApiError("ERR_WAIVER_NOT_ELIGIBLE")

    row = db.base_row()
    row.update(
        {
            "encounter_id": enc["id"],
            "waiver_reason": body["waiver_reason"],
            "status": "REQUESTED",
            "requested_by_user_id": user_id,
            "decided_by_user_id": None,
            "decision_note": None,
            "waived_amount_cents": 0,
        }
    )
    db.db.waivers[row["id"]] = row
    return object_response(serializers.waiver(row), 201)


@bp.get("/waivers/<waiver_id>")
def read_waiver(waiver_id):
    authorize(*ALL_ROLES)
    return object_response(serializers.waiver(require("waivers", waiver_id)))


@bp.get("/encounters/<encounter_id>/waivers")
def list_waivers(encounter_id):
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    require("encounters", encounter_id)
    rows = db.in_creation_order(
        [w for w in db.db.waivers.values() if w["encounter_id"] == encounter_id]
    )
    return listing(
        rows,
        serializers.waiver,
        limit,
        offset,
        specs=[("status", "status", "string")],
    )


@bp.post("/waivers/<waiver_id>/decide")
def decide_waiver(waiver_id):
    user_id = authorize("ComplianceOfficer")
    body = parse_body(
        [
            Field("decision", "enum", required=True, enum=("GRANT", "DENY")),
            Field("decision_note", "string", nullable=True),
        ]
    )
    waiver = require("waivers", waiver_id)

    state(waiver, "status", ("REQUESTED",))
    enc = db.db.encounters.get(waiver["encounter_id"])
    if enc is None:
        raise ApiError("ERR_ENCOUNTER_NOT_FOUND")
    if enc["pps_claim_status"] in ("RECONCILED", "VOID"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    segregation(user_id, waiver["requested_by_user_id"])

    waiver["decided_by_user_id"] = user_id
    waiver["decision_note"] = body.get("decision_note")

    if body["decision"] == "DENY":
        waiver["status"] = "DENIED"
        db.touch(waiver)
        return object_response(serializers.waiver(waiver))

    waiver["status"] = "GRANTED"
    waiver["waived_amount_cents"] = enc["patient_charge_cents"]
    db.touch(waiver)

    # Depth-3 cascade: the encounter's waived amount, then the patient ledger,
    # then the wraparound residual and the grantee receivable.
    enc["waived_amount_cents"] = waiver["waived_amount_cents"]
    charge.recompute_wraparound(enc)
    db.touch(enc)

    patient = db.db.patients.get(enc["patient_id"])
    if patient is not None:
        db.touch(patient)
    _bump_grantee(enc)

    return object_response(serializers.waiver(waiver))
