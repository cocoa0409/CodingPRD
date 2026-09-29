"""The rebuilt application lifecycle: draft, parts evidence, adjudication of
that evidence, submission and the money, documentation review, withdrawal and
the rebuilt-title issuance."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.reads import fetch
from routes.titles import _mint_title as mint_title
from services import calc, cascades, derive

bp = Blueprint("applications", __name__)

LIVE_LICENSE = ("ACTIVE", "PROBATION")
WITHDRAWABLE = (
    "DRAFT",
    "SUBMITTED",
    "DOCS_UNDER_REVIEW",
    "DOCS_ACCEPTED",
    "SCHEDULED",
    "FAILED",
)


def acting_inspector(user_id):
    inspector = db.db.inspectors.get(user_id)
    if inspector is None:
        raise ApiError(
            "ERR_INSPECTOR_NOT_FOUND", "The acting X-User-ID is not a commissioned inspector."
        )
    derive.recompute_inspector(inspector)
    return inspector


def require_owner(application, user_id, role):
    if role == "Rebuilder" and application["rebuilder_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


@bp.post("/v1/applications")
def create_application():
    user_id, _role = mw.authenticate("Rebuilder")
    data = mw.body()

    # 4. body foreign keys, in declared field order
    vehicle_id = data.get("vehicle_id")
    if not isinstance(vehicle_id, str) or not vehicle_id.strip():
        mw.bad("vehicle_id", "is required")
    vehicle = db.db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")

    rebuilder_id = data.get("rebuilder_id")
    if not isinstance(rebuilder_id, str) or not rebuilder_id.strip():
        mw.bad("rebuilder_id", "is required")
    rebuilder = db.db.rebuilders.get(rebuilder_id)
    if rebuilder is None:
        raise ApiError("ERR_REBUILDER_NOT_FOUND")

    salvage_title_id = data.get("salvage_title_id")
    if not isinstance(salvage_title_id, str) or not salvage_title_id.strip():
        mw.bad("salvage_title_id", "is required")
    salvage_title = db.db.titles.get(salvage_title_id)
    if salvage_title is None:
        raise ApiError("ERR_TITLE_NOT_FOUND")

    # 5. well-formedness
    declared_repair_cost_cents = mw.req_int(data, "declared_repair_cost_cents", minimum=0)
    expedite_requested = mw.opt_bool(data, "expedite_requested", False)

    # 7. ownership
    if rebuilder_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    derive.recompute_vehicle(vehicle, touch_row=False)
    derive.recompute_title(salvage_title, touch_row=False)
    derive.recompute_rebuilder(rebuilder, touch_row=False)

    # 10. business safety
    if vehicle["fraud_hold"] != "NONE":
        raise ApiError("ERR_VEHICLE_FRAUD_HOLD", "The vehicle is under a fraud hold.")
    if "NON_REPAIRABLE" in vehicle["brand_history"] or salvage_title["brand_code"] == "NON_REPAIRABLE":
        raise ApiError(
            "ERR_NON_REPAIRABLE_BRAND", "A non-repairable vehicle can never be rebuilt."
        )

    # 11. referential business rules
    if rebuilder["license_status"] not in LIVE_LICENSE:
        raise ApiError(
            "ERR_REBUILDER_LICENSE_INACTIVE", "The rebuilder's licence is not in good standing."
        )
    if (
        salvage_title["brand_code"] not in ("SALVAGE", "FLOOD")
        or salvage_title["status"] != "ACTIVE"
        or not salvage_title["is_current"]
        or salvage_title["vehicle_id"] != vehicle_id
    ):
        raise ApiError(
            "ERR_SALVAGE_TITLE_REQUIRED",
            "The application must convert this vehicle's current, ACTIVE SALVAGE or FLOOD title.",
        )

    # 12. quantitative constraints
    if vehicle["open_application_count"] != 0:
        raise ApiError(
            "ERR_DUPLICATE_ACTIVE_APPLICATION",
            "A vehicle may have at most one live application at a time.",
        )

    row = db.new_row()
    row.update(
        {
            "vehicle_id": vehicle_id,
            "rebuilder_id": rebuilder_id,
            "salvage_title_id": salvage_title_id,
            "status": "DRAFT",
            "expedite_requested": expedite_requested,
            "declared_repair_cost_cents": declared_repair_cost_cents,
            "documented_parts_cost_cents": 0,
            "documentation_completeness_pct": calc.pct2(0),
            "photo_view_count": 0,
            "assessed_fee_cents": calc.BASE_APPLICATION_FEE_CENTS,
            "total_program_charge_cents": 0,
            "fee_escrowed_cents": 0,
            "attempts_completed": 0,
            "attempt_limit": calc.BASE_ATTEMPT_LIMIT,
            "last_inspection_result": None,
            "withdrawn_reason": None,
            "terminal_at": None,
        }
    )
    db.db.applications[row["id"]] = row
    derive.recompute_application(row, touch_row=False)
    derive.recompute_vehicle(vehicle, touch_row=True)
    return response.single(derive.application_out(row), 201)


@bp.post("/v1/applications/<row_id>/parts-documents")
def file_parts_document(row_id):
    user_id, role = mw.authenticate("Rebuilder")
    application = fetch(db.db.applications, row_id, "ERR_APPLICATION_NOT_FOUND")
    data = mw.body()

    # 4. body foreign keys
    donor_title = None
    donor_title_id = data.get("donor_title_id")
    if donor_title_id is not None:
        if not isinstance(donor_title_id, str) or not donor_title_id.strip():
            mw.bad("donor_title_id", "must be a string identifier")
        donor_title = db.db.titles.get(donor_title_id)
        if donor_title is None:
            raise ApiError("ERR_TITLE_NOT_FOUND")

    # 5. well-formedness
    doc_type = mw.req_enum(data, "doc_type", calc.DOC_TYPES)
    part_class = mw.req_enum(data, "part_class", calc.PART_CLASSES)
    source_type = mw.req_enum(data, "source_type", calc.SOURCE_TYPES)
    amount_cents = mw.opt_int(data, "amount_cents", 0, minimum=0)
    vendor_name = mw.opt_str(data, "vendor_name")
    part_serial_number = mw.opt_str(data, "part_serial_number")
    donor_vin = mw.opt_str(data, "donor_vin")
    photo_view_code = mw.opt_enum(data, "photo_view_code", calc.PHOTO_VIEW_CODES)
    if doc_type == "PHOTOGRAPH" and photo_view_code is None:
        mw.bad("photo_view_code", "is required when doc_type is PHOTOGRAPH")
    if doc_type != "PHOTOGRAPH" and photo_view_code is not None:
        mw.bad("photo_view_code", "must be null unless doc_type is PHOTOGRAPH")
    if source_type == "USED_DONOR" and donor_title_id is None:
        mw.bad("donor_title_id", "is required when source_type is USED_DONOR")
    if source_type != "USED_DONOR" and donor_title_id is not None:
        mw.bad("donor_title_id", "must be null unless source_type is USED_DONOR")

    # 7. ownership
    require_owner(application, user_id, role)

    # 9. state-machine admissibility
    if application["status"] != "DRAFT":
        raise ApiError(
            "ERR_APPLICATION_NOT_DRAFT", "Parts evidence may only be filed while the application is DRAFT."
        )

    # 14. identity integrity
    vehicle = db.db.vehicles.get(application["vehicle_id"])
    if donor_vin is not None and vehicle is not None and donor_vin == vehicle["vin"]:
        raise ApiError(
            "ERR_VIN_MISMATCH", "A part cannot be harvested from the very vehicle it was installed in."
        )

    row = db.new_row()
    row.update(
        {
            "application_id": application["id"],
            "donor_title_id": donor_title_id,
            "verified_by_inspector_id": None,
            "doc_type": doc_type,
            "part_class": part_class,
            "photo_view_code": photo_view_code,
            "source_type": source_type,
            "vendor_name": vendor_name,
            "amount_cents": amount_cents,
            "part_serial_number": part_serial_number,
            "donor_vin": donor_vin,
            "status": "SUBMITTED",
            "rejection_reason": None,
            "traceable": source_type == "NEW" or donor_title_id is not None,
        }
    )
    db.db.parts_documents[row["id"]] = row

    derive.recompute_application(application, touch_row=False)
    db.touch(application)
    return response.single(derive.parts_document_out(row), 201)


def _refresh_after_document(application):
    derive.recompute_application(application, touch_row=False)
    derive.recompute_fee_fields(application, touch_row=False)
    db.touch(application)
    rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
    if rebuilder is not None:
        derive.recompute_rebuilder(rebuilder, touch_row=True)


@bp.post("/v1/parts-documents/<row_id>/verify")
def verify_parts_document(row_id):
    user_id, _role = mw.authenticate("Inspector")
    document = fetch(db.db.parts_documents, row_id, "ERR_PARTS_DOCUMENT_NOT_FOUND")
    data = mw.body()
    mw.opt_str(data, "verification_note")
    inspector = acting_inspector(user_id)
    application = db.db.applications.get(document["application_id"])

    # 9. state-machine admissibility
    if application is not None and application["status"] not in (
        "DRAFT",
        "SUBMITTED",
        "DOCS_UNDER_REVIEW",
    ):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "Parts evidence may only be adjudicated while the application is under documentation review.",
        )
    if document["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_PARTS_DOCUMENT_STATE_INVALID", "Only a SUBMITTED document may be verified."
        )

    # 11. referential business rules
    if inspector["credential_status"] != "CURRENT":
        raise ApiError("ERR_INSPECTOR_CREDENTIAL_EXPIRED")
    if document["source_type"] in ("USED_DONOR", "RECYCLER"):
        donor_title = (
            db.db.titles.get(document["donor_title_id"]) if document["donor_title_id"] else None
        )
        if (
            donor_title is None
            or donor_title["status"] == "VOID"
            or donor_title["brand_code"] == "NON_REPAIRABLE"
        ):
            raise ApiError(
                "ERR_DONOR_TITLE_NOT_TRACEABLE",
                "A donor-sourced part must cite a traceable donor title.",
            )

    document["status"] = "VERIFIED"
    document["verified_by_inspector_id"] = user_id
    db.touch(document)
    if application is not None:
        _refresh_after_document(application)
    return response.single(derive.parts_document_out(document))


@bp.post("/v1/parts-documents/<row_id>/reject")
def reject_parts_document(row_id):
    user_id, _role = mw.authenticate("Inspector")
    document = fetch(db.db.parts_documents, row_id, "ERR_PARTS_DOCUMENT_NOT_FOUND")
    data = mw.body()
    rejection_reason = mw.req_enum(data, "rejection_reason", calc.REJECTION_REASONS)
    mw.opt_str(data, "rejection_note")
    inspector = acting_inspector(user_id)

    # 9. state-machine admissibility
    if document["status"] not in ("SUBMITTED", "VERIFIED"):
        raise ApiError(
            "ERR_PARTS_DOCUMENT_STATE_INVALID", "This document has already been rejected."
        )

    # 11. referential business rules
    if inspector["credential_status"] != "CURRENT":
        raise ApiError("ERR_INSPECTOR_CREDENTIAL_EXPIRED")

    document["status"] = "REJECTED"
    document["rejection_reason"] = rejection_reason
    document["verified_by_inspector_id"] = user_id
    db.touch(document)
    application = db.db.applications.get(document["application_id"])
    if application is not None:
        _refresh_after_document(application)
    return response.single(derive.parts_document_out(document))


@bp.post("/v1/applications/<row_id>/submit")
def submit_application(row_id):
    user_id, role = mw.authenticate("Rebuilder")
    application = fetch(db.db.applications, row_id, "ERR_APPLICATION_NOT_FOUND")
    data = mw.body()

    # 5. well-formedness — the attestation must be exactly true
    if data.get("attestation_signed") is not True:
        mw.bad("attestation_signed", "must be exactly true")

    # 7. ownership
    require_owner(application, user_id, role)

    # 9. state-machine admissibility
    if application["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_NOT_DRAFT", "Only a DRAFT application may be submitted.")

    vehicle = db.db.vehicles.get(application["vehicle_id"])
    rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
    salvage_title = db.db.titles.get(application["salvage_title_id"])
    if vehicle is not None:
        derive.recompute_vehicle(vehicle, touch_row=False)
    if rebuilder is not None:
        derive.recompute_rebuilder(rebuilder, touch_row=False)
    derive.recompute_application(application, touch_row=False)

    # 10. business safety
    if vehicle is not None and vehicle["fraud_hold"] != "NONE":
        raise ApiError("ERR_VEHICLE_FRAUD_HOLD", "The vehicle is under a fraud hold.")

    # 11. referential business rules
    if rebuilder is not None and rebuilder["license_status"] not in LIVE_LICENSE:
        raise ApiError(
            "ERR_REBUILDER_LICENSE_INACTIVE", "The rebuilder's licence is not in good standing."
        )

    # 12. quantitative constraints
    if application["documentation_completeness_pct"] != calc.pct2(100):
        raise ApiError(
            "ERR_DOCUMENTATION_INCOMPLETE",
            "documentation_completeness_pct must be exactly 100.00 to submit.",
        )
    if application["photo_view_count"] < calc.MIN_PHOTO_VIEWS:
        raise ApiError(
            "ERR_PHOTO_SET_INCOMPLETE",
            "At least %d distinct camera angles must be on file." % calc.MIN_PHOTO_VIEWS,
        )

    # 13. temporal windows
    if salvage_title is not None:
        issued_at = db.parse_dt(salvage_title["issued_at"])
        if issued_at is not None and db.now() > issued_at + db.days(calc.SUBMISSION_WINDOW_DAYS):
            raise ApiError(
                "ERR_SUBMISSION_WINDOW_EXPIRED",
                "The 180-day submission window on the salvage title has closed.",
            )

    assessed = calc.assess_fee(derive.docs_of_app(application["id"]))
    quote = calc.program_charge(
        assessed,
        application["attempts_completed"],
        application["expedite_requested"],
        rebuilder["applications_titled_count"] if rebuilder is not None else 0,
    )
    charge = quote["total_program_charge_cents"]

    # 15. fiscal capacity, last of all
    if rebuilder is not None and rebuilder["fee_balance_cents"] < charge:
        raise ApiError(
            "ERR_INSUFFICIENT_FEE_BALANCE",
            "fee_balance_cents is below the computed total_program_charge_cents.",
        )

    application["assessed_fee_cents"] = assessed
    application["total_program_charge_cents"] = charge
    application["fee_escrowed_cents"] = charge
    application["status"] = "SUBMITTED"
    derive.recompute_application(application, touch_row=False)
    db.touch(application)
    if rebuilder is not None:
        derive.recompute_rebuilder(rebuilder, touch_row=True)
    return response.single(derive.application_out(application))


@bp.post("/v1/applications/<row_id>/docs-review")
def review_documents(row_id):
    mw.authenticate("StateTitleClerk")
    application = fetch(db.db.applications, row_id, "ERR_APPLICATION_NOT_FOUND")
    data = mw.body()
    decision = mw.req_enum(data, "decision", calc.REVIEW_DECISIONS)
    mw.opt_str(data, "review_note")

    derive.recompute_application(application, touch_row=False)

    # 9. state-machine admissibility
    if application["status"] not in ("SUBMITTED", "DOCS_UNDER_REVIEW"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "Documentation review is only available from SUBMITTED or DOCS_UNDER_REVIEW.",
        )
    required_status = "SUBMITTED" if decision == "OPEN" else "DOCS_UNDER_REVIEW"
    if application["status"] != required_status:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "A decision of %s is not admissible from %s." % (decision, application["status"]),
        )

    if decision == "ACCEPT":
        # 12. quantitative constraints
        if application["documentation_completeness_pct"] != calc.pct2(100):
            raise ApiError(
                "ERR_DOCUMENTATION_INCOMPLETE",
                "documentation_completeness_pct must be exactly 100.00 to accept.",
            )
        for document in derive.docs_of_app(application["id"]):
            if document["part_class"] != "PHOTO_SET" and document["status"] != "VERIFIED":
                raise ApiError(
                    "ERR_DOCUMENTATION_INCOMPLETE",
                    "Every non-photographic parts document must be VERIFIED to accept.",
                )
        application["status"] = "DOCS_ACCEPTED"
    elif decision == "OPEN":
        application["status"] = "DOCS_UNDER_REVIEW"
    else:
        # a return for correction disposes of no escrow at all
        application["status"] = "DRAFT"

    derive.recompute_application(application, touch_row=False)
    db.touch(application)
    return response.single(derive.application_out(application))


@bp.post("/v1/applications/<row_id>/withdraw")
def withdraw_application(row_id):
    user_id, role = mw.authenticate("Rebuilder")
    application = fetch(db.db.applications, row_id, "ERR_APPLICATION_NOT_FOUND")
    data = mw.body()
    withdrawn_reason = mw.req_str(data, "withdrawn_reason")

    # 7. ownership
    require_owner(application, user_id, role)

    # 9. state-machine admissibility
    if application["status"] not in WITHDRAWABLE:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "A terminal application can no longer be withdrawn."
        )

    rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
    if rebuilder is not None:
        cascades.refund_escrow(application, rebuilder)
    else:
        application["fee_escrowed_cents"] = 0

    for inspection in derive.inspections_of_app(application["id"]):
        if inspection["status"] == "SCHEDULED":
            cascades.cancel_attempt(inspection, "APPLICATION_VOIDED")

    application["status"] = "WITHDRAWN"
    application["withdrawn_reason"] = withdrawn_reason
    application["terminal_at"] = db.now_iso()
    derive.recompute_application(application, touch_row=False)
    db.touch(application)

    if rebuilder is not None:
        derive.recompute_rebuilder(rebuilder, touch_row=True)
    vehicle = db.db.vehicles.get(application["vehicle_id"])
    if vehicle is not None:
        derive.recompute_vehicle(vehicle, touch_row=True)
    return response.single(derive.application_out(application))


@bp.post("/v1/applications/<row_id>/issue-rebuilt-title")
def issue_rebuilt_title(row_id):
    mw.authenticate("StateTitleClerk")
    application = fetch(db.db.applications, row_id, "ERR_APPLICATION_NOT_FOUND")
    data = mw.body()
    issuing_state_code = mw.req_state_code(data, "issuing_state_code")
    owner_name = mw.req_str(data, "owner_name")

    vehicle = db.db.vehicles.get(application["vehicle_id"])
    rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
    salvage_title = db.db.titles.get(application["salvage_title_id"])
    if vehicle is not None:
        derive.recompute_vehicle(vehicle, touch_row=False)

    # 9. state-machine admissibility
    if application["status"] != "PASSED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "Only a PASSED application may be titled."
        )
    if salvage_title is None or salvage_title["status"] != "ACTIVE":
        raise ApiError("ERR_TITLE_NOT_ACTIVE", "The salvage title being converted is not ACTIVE.")

    # 10. business safety
    if vehicle is not None and vehicle["fraud_hold"] != "NONE":
        raise ApiError("ERR_VEHICLE_FRAUD_HOLD", "The vehicle is under a fraud hold.")
    if vehicle is not None and "NON_REPAIRABLE" in vehicle["brand_history"]:
        raise ApiError(
            "ERR_NON_REPAIRABLE_BRAND", "A non-repairable vehicle can never be retitled."
        )
    for finding in derive.findings_of_app(application["id"]):
        if finding["category"] == "STOLEN_COMPONENT" and not finding["resolved"]:
            raise ApiError(
                "ERR_STOLEN_COMPONENT_UNRESOLVED",
                "An unresolved stolen-component finding stands against this application.",
            )

    title = mint_title(
        vehicle,
        issuing_state_code,
        owner_name,
        "REBUILT",
        salvage_title["id"],
        None,
        vehicle["last_odometer_miles"] if vehicle is not None else None,
    )
    cascades.leave_active(salvage_title, "SUPERSEDED")

    if rebuilder is not None:
        cascades.capture_escrow(application, rebuilder)
    else:
        application["fee_escrowed_cents"] = 0
    application["status"] = "TITLE_ISSUED"
    application["terminal_at"] = db.now_iso()
    derive.recompute_application(application, touch_row=False)
    db.touch(application)

    derive.recompute_title(title, touch_row=False)
    if rebuilder is not None:
        derive.recompute_rebuilder(rebuilder, touch_row=True)
    if vehicle is not None:
        derive.recompute_vehicle(vehicle, touch_row=True)
    return response.single(derive.title_out(title), 201)


@bp.get("/v1/applications/<row_id>/fee-quote")
def fee_quote(row_id):
    user_id, role = mw.authenticate("ProgramAdmin", "StateTitleClerk", "Rebuilder")
    application = fetch(db.db.applications, row_id, "ERR_APPLICATION_NOT_FOUND")

    # 7. ownership — only the owning rebuilder may read its own quotation
    require_owner(application, user_id, role)

    derive.recompute_application(application)
    rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
    if rebuilder is not None:
        derive.recompute_rebuilder(rebuilder)
    quote = calc.program_charge(
        application["assessed_fee_cents"],
        application["attempts_completed"],
        application["expedite_requested"],
        rebuilder["applications_titled_count"] if rebuilder is not None else 0,
    )
    return response.single(quote)
