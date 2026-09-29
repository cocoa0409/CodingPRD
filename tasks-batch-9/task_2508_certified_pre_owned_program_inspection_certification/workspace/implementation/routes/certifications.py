"""Certification submission, documentation and adjudication (PRD 3.6-3.7)."""
from flask import Blueprint

import calc
import cascades as cas
import enums
import helpers as h
import serializers as ser
from db import cfg, db, new_id
from errors import ApiError

bp = Blueprint("certifications", __name__)

READ_ROLES = (
    "ProgramAdministrator",
    "ProgramAuditor",
    "DealerPrincipal",
    "CustomerAdvocate",
)
DOC_ROLES = ("ProgramAdministrator", "ProgramAuditor", "DealerPrincipal")
LIVE_STATUSES = ("ACTIVE", "UNDER_AUDIT")
BLOCKING_STATUSES = ("ACTIVE", "UNDER_AUDIT")


def certification_or_404(certification_id):
    row = db.certifications.get(certification_id)
    if row is None:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND", "No certification with that id.")
    return row


def certification_documents(certification_id):
    return [d for d in db.documents.values() if d["certification_id"] == certification_id]


# --------------------------------------------------------------------------- #
# POST /cpo/certifications
# --------------------------------------------------------------------------- #
@bp.route("/certifications", methods=["POST"])
def submit_certification():
    _uid, _role, dealer = h.authorize(("DealerPrincipal",))
    config = cfg()
    body = h.body_dict()
    vehicle_id = h.f_string(body, "vehicle_id")
    inspection_id = h.f_string(body, "inspection_id")
    expected_version = h.f_int(body, "expected_vehicle_version")
    documents = h.f_list(body, "documents", non_empty=True)
    parsed_docs = []
    for entry in documents:
        if not isinstance(entry, dict):
            h.bad_request("Each documents entry must be an object.")
        parsed_docs.append(
            {
                "doc_type": h.f_enum(entry, "doc_type", enums.DOC_TYPES),
                "reference": h.f_string(entry, "reference"),
            }
        )

    vehicle = db.vehicles.get(vehicle_id)
    inspection = db.inspections.get(inspection_id)
    if vehicle is None or inspection is None:
        raise ApiError(
            "ERR_REFERENCED_ENTITY_NOT_FOUND",
            "A foreign key supplied in the request body does not resolve.",
        )

    if inspection["dealer_id"] != dealer["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION", "That inspection belongs to another dealership."
        )

    if inspection["status"] != "PASSED":
        raise ApiError(
            "ERR_INSPECTION_NOT_PASSED",
            "Only a PASSED inspection may back a certification.",
        )

    if expected_version != vehicle["version"]:
        raise ApiError(
            "ERR_STALE_VEHICLE_VERSION",
            "The vehicle has moved on since it was read; re-read it and retry.",
        )

    if vehicle["title_brand"] in (config["ineligible_title_brands"] or []):
        raise ApiError(
            "ERR_BRANDED_TITLE_INELIGIBLE",
            "A branded car is permanently outside the programme.",
        )
    if vehicle["prior_use"] in (config["ineligible_prior_uses"] or []):
        raise ApiError(
            "ERR_PRIOR_USE_INELIGIBLE",
            "That prior use excludes the car from the programme.",
        )

    if dealer["privilege_status"] == "SUSPENDED":
        raise ApiError(
            "ERR_DEALER_PRIVILEGE_SUSPENDED",
            "The dealer's certifying privilege is suspended.",
        )

    # rung 21 — the vehicle's single certification slot
    superseded = None
    for other in db.certifications.values():
        if other["vehicle_id"] != vehicle_id:
            continue
        if other["status"] in BLOCKING_STATUSES:
            raise ApiError(
                "ERR_VEHICLE_ALREADY_CERTIFIED",
                "That vehicle already holds a live certification.",
            )
        if other["status"] == "SUBMITTED":
            superseded = other

    # rungs 22 and 23 — documentation
    recon_count = len(cas.inspection_recon_items(inspection_id))
    supplied = [d["doc_type"] for d in parsed_docs]
    required = list(config["required_doc_types"] or [])
    for doc_type in required:
        if doc_type == "RECONDITIONING_INVOICE" and recon_count == 0:
            continue
        if doc_type not in supplied:
            raise ApiError(
                "ERR_DOCUMENTATION_INCOMPLETE",
                "The documents array omits the required %s." % doc_type,
            )
    if "RECONDITIONING_INVOICE" in supplied and recon_count == 0:
        raise ApiError(
            "ERR_DOCUMENT_NOT_APPLICABLE",
            "The backing inspection generated no repairs, so no invoice applies.",
        )
    if len(set(supplied)) != len(supplied):
        raise ApiError(
            "ERR_DOCUMENT_NOT_APPLICABLE", "The documents array repeats a doc_type."
        )

    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        h.touch(superseded)

    row = h.new_common(
        {
            "id": new_id(),
            "vehicle_id": vehicle_id,
            "inspection_id": inspection_id,
            "dealer_id": dealer["id"],
            "certification_number": None,
            "status": "SUBMITTED",
            "submitted_at": db.clock,
            "activated_at": None,
            "decertified_at": None,
            "rejection_reason": None,
            "decertification_reason": None,
            "program_config_version": None,
            "fee_surcharge_cents": 0,
            "fee_discount_cents": 0,
            "fee_charged_cents": 0,
            "fee_credited_cents": 0,
            "warranty_anchor_variant": None,
            "warranty_start_date": None,
            "warranty_end_date": None,
            "warranty_end_miles": None,
            "retention_expires_at": None,
            "audit_sampled": False,
            "listing_syndicated_at": None,
        }
    )
    db.certifications[row["id"]] = row

    cas.recompute_dealer_cert_counts(dealer)
    row["certification_number"] = "CPO-%s-%04d" % (
        dealer["franchise_code"],
        dealer["lifetime_submitted_count"],
    )

    for entry in parsed_docs:
        doc = h.new_evidence(
            {
                "id": new_id(),
                "certification_id": row["id"],
                "doc_type": entry["doc_type"],
                "reference": entry["reference"],
                "uploaded_at": db.clock,
                "retained_until": None,
            }
        )
        db.documents[doc["id"]] = doc

    h.touch(vehicle)
    h.touch(dealer)
    return h.object_response(ser.certification(row), 201)


@bp.route("/certifications", methods=["GET"])
def list_certifications():
    h.authorize(READ_ROLES)
    vehicle_id = h.q_string("vehicle_id")
    inspection_id = h.q_string("inspection_id")
    dealer_id = h.q_string("dealer_id")
    status = h.q_enum("status", enums.CERT_STATUSES)
    audit_sampled = h.q_bool("audit_sampled")
    limit, offset = h.pagination()
    rows = list(db.certifications.values())
    if vehicle_id:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    if inspection_id:
        rows = [r for r in rows if r["inspection_id"] == inspection_id]
    if dealer_id:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if audit_sampled is not None:
        rows = [r for r in rows if r["audit_sampled"] == audit_sampled]
    return h.paged(rows, limit, offset, ser.certification)


@bp.route("/certifications/<certification_id>", methods=["GET"])
def read_certification(certification_id):
    user_id, role, _principal = h.authorize(READ_ROLES)
    certification = certification_or_404(certification_id)
    h.require_dealer_scope(user_id, role, certification["dealer_id"])
    return h.object_response(ser.certification(certification))


@bp.route("/certifications/<certification_id>/documents", methods=["GET"])
def list_documents(certification_id):
    user_id, role, _principal = h.authorize(DOC_ROLES)
    doc_type = h.q_enum("doc_type", enums.DOC_TYPES)
    limit, offset = h.pagination()
    # 3.7: the documents listing is readable by an administrator, an auditor,
    # "or the owning `DealerPrincipal`".
    h.require_dealer_scope(
        user_id, role, certification_or_404(certification_id)["dealer_id"]
    )
    rows = certification_documents(certification_id)
    if doc_type:
        rows = [r for r in rows if r["doc_type"] == doc_type]
    return h.paged(rows, limit, offset, ser.certification_document)


# --------------------------------------------------------------------------- #
# POST /cpo/certifications/{id}/approve
# --------------------------------------------------------------------------- #
@bp.route("/certifications/<certification_id>/approve", methods=["POST"])
def adjudicate_certification(certification_id):
    h.authorize(("ProgramAdministrator",))
    config = cfg()
    body = h.body_dict()
    decision = h.f_enum(body, "decision", enums.CERT_DECISIONS)
    rejection_reason = h.f_enum(
        body,
        "rejection_reason",
        ("DOCUMENTATION_INCOMPLETE", "DEALER_SUSPENDED", "ADMIN_DECISION"),
        required=False,
    )

    certification = certification_or_404(certification_id)
    if certification["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_CERTIFICATION_NOT_SUBMITTED",
            "Only a SUBMITTED certification may be adjudicated.",
        )

    vehicle = db.vehicles.get(certification["vehicle_id"])
    dealer = db.dealers.get(certification["dealer_id"])
    inspection = db.inspections.get(certification["inspection_id"])

    if decision == "REJECT":
        cas.reject_submitted_certification(
            certification, rejection_reason or "ADMIN_DECISION"
        )
        if dealer is not None:
            cas.recompute_dealer_cert_counts(dealer)
            h.touch(dealer)
        return h.object_response(ser.certification(certification))

    # ---- APPROVE ---------------------------------------------------------- #
    if vehicle is None or vehicle["inventory_state"] != "IN_INVENTORY":
        raise ApiError(
            "ERR_VEHICLE_NOT_IN_INVENTORY",
            "A car that has left inventory can no longer be certified.",
        )
    if vehicle["title_brand"] in (config["ineligible_title_brands"] or []):
        raise ApiError(
            "ERR_BRANDED_TITLE_INELIGIBLE",
            "A branded car is permanently outside the programme.",
        )
    if vehicle["prior_use"] in (config["ineligible_prior_uses"] or []):
        raise ApiError(
            "ERR_PRIOR_USE_INELIGIBLE",
            "That prior use excludes the car from the programme.",
        )
    if dealer is None or dealer["privilege_status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError(
            "ERR_DEALER_PRIVILEGE_SUSPENDED",
            "A suspended dealer may not have a certification approved.",
        )

    activation_date = h.clock_date()
    odometer = inspection["odometer_at_inspection"] if inspection else 0
    lifetime_activated = dealer["lifetime_activated_count"]

    surcharge, discount, charged = calc.certification_fee(
        config, vehicle["in_service_date"], activation_date, odometer, lifetime_activated
    )
    variant, start, end, end_miles, retention = calc.warranty_coverage(
        config, vehicle["in_service_date"], activation_date, odometer
    )

    # rung 30 — the coverage interval must be non-empty on both axes
    if end <= start or end_miles <= odometer:
        raise ApiError(
            "ERR_NO_COVERAGE_REMAINING",
            "The programme cap leaves no coverage to grant.",
        )

    # rung 31 — overlap against coverage already retained on the same vehicle
    for other in db.certifications.values():
        if other["id"] == certification_id or other["vehicle_id"] != vehicle["id"]:
            continue
        retained = other["status"] in LIVE_STATUSES or (
            other["status"] == "DECERTIFIED"
            and other["decertification_reason"] == "RETAIL_SOLD"
        )
        if not retained:
            continue
        if calc.coverage_conflicts(
            start, end, other["warranty_start_date"], other["warranty_end_date"]
        ):
            raise ApiError(
                "ERR_COVERAGE_WINDOW_OVERLAP",
                "Coverage already retained on this vehicle overlaps the candidate window.",
            )

    certification["program_config_version"] = config["version"]
    certification["fee_surcharge_cents"] = surcharge
    certification["fee_discount_cents"] = discount
    certification["fee_charged_cents"] = charged
    certification["warranty_anchor_variant"] = variant
    certification["warranty_start_date"] = start
    certification["warranty_end_date"] = end
    certification["warranty_end_miles"] = end_miles
    certification["retention_expires_at"] = retention
    certification["status"] = "ACTIVE"
    certification["activated_at"] = db.clock
    h.touch(certification)

    for doc in certification_documents(certification_id):
        doc["retained_until"] = retention

    if vehicle["cpo_state"] == "CERTIFICATION_PENDING":
        vehicle["cpo_state"] = "CERTIFIED"
    h.touch(vehicle)

    cas.recompute_dealer_cert_counts(dealer)
    cas.recompute_dealer_fee_ledger(dealer)
    cas.recompute_dealer_ratio(dealer)
    h.touch(dealer)
    return h.object_response(ser.certification(certification))


# --------------------------------------------------------------------------- #
# POST /cpo/certifications/{id}/decertify
# --------------------------------------------------------------------------- #
@bp.route("/certifications/<certification_id>/decertify", methods=["POST"])
def decertify(certification_id):
    _uid, role, principal = h.authorize(("ProgramAdministrator", "DealerPrincipal"))
    body = h.body_dict()
    reason = h.f_enum(
        body, "decertification_reason", ("ADMIN_ACTION", "TITLE_BRANDED")
    )
    certification = certification_or_404(certification_id)
    if role == "DealerPrincipal" and certification["dealer_id"] != principal["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "That certification belongs to another dealership.",
        )
    if certification["status"] not in LIVE_STATUSES:
        raise ApiError(
            "ERR_CERTIFICATION_TERMINAL",
            "Only an ACTIVE or UNDER_AUDIT certification may be decertified.",
        )
    cas.decertify_certification(certification, reason)
    return h.object_response(ser.certification(certification))
