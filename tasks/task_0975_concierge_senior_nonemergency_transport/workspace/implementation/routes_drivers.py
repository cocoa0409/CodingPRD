"""Driver onboarding/lifecycle and compliance document endpoints."""

from flask import request

from core import (
    db, get_caller, require_role, get_body, ok, parse_pagination, paginate,
    field_str, field_int, field_enum, field_date, stamp_new, touch, sort_created,
    today, ApiError, err_not_found, err_forbidden,
)
from domain import (
    ser_driver, ser_compliance_doc, posture_complete, driver_release_cascade,
)

VEHICLE_CLASSES = {"SEDAN", "WAV"}
ASSIST_CERTS = {"NONE", "DOOR_TO_DOOR", "DOOR_THROUGH_DOOR"}
DOC_TYPES = {"BACKGROUND_CHECK", "BONDING", "INSURANCE", "MOTOR_VEHICLE_RECORD"}
DOC_REVIEW_DECISIONS = {"APPROVE", "REJECT"}
DRIVER_EVENTS = {"ACTIVATE", "SUSPEND", "REINSTATE", "OFFBOARD"}


def register(app):

    @app.route("/drivers", methods=["POST"])
    def create_driver():
        body = get_body()
        full_name = field_str(body, "full_name", required=True)
        vehicle_class = field_enum(body, "vehicle_class", VEHICLE_CLASSES, required=True)
        cert = field_enum(body, "assist_certification", ASSIST_CERTS, required=True)
        home_zone = field_str(body, "home_zone", required=True)
        cap = field_int(body, "max_daily_service_minutes", required=True, minimum=0)
        caller = get_caller()
        require_role(caller, {"Coordinator"})
        driver = {
            "full_name": full_name,
            "status": "APPLICANT",
            "vehicle_class": vehicle_class,
            "assist_certification": cert,
            "home_zone": home_zone,
            "max_daily_service_minutes": cap,
        }
        stamp_new(driver)
        db.drivers[driver["id"]] = driver
        return ok(ser_driver(driver), status=201)

    @app.route("/drivers/<did>", methods=["GET"])
    def get_driver(did):
        caller = get_caller()
        require_role(caller, {"PlatformAdmin", "Coordinator", "BillingAdmin", "Driver"})
        driver = db.drivers.get(did)
        if driver is None:
            raise err_not_found("Driver not found")
        if caller.role == "Driver" and caller.user_id != did:
            raise err_forbidden("Driver may only access their own record")
        return ok(ser_driver(driver))

    @app.route("/drivers", methods=["GET"])
    def list_drivers():
        caller = get_caller()
        require_role(caller, {"PlatformAdmin", "Coordinator"})
        limit, offset = parse_pagination()
        items = sort_created(db.drivers.values())
        status = request.args.get("status")
        vehicle_class = request.args.get("vehicle_class")
        if status is not None:
            items = [d for d in items if d["status"] == status]
        if vehicle_class is not None:
            items = [d for d in items if d["vehicle_class"] == vehicle_class]
        page, meta = paginate(items, limit, offset)
        return ok([ser_driver(d) for d in page], response_type="array", pagination=meta)

    @app.route("/drivers/<did>/status-events", methods=["POST"])
    def driver_status_event(did):
        body = get_body()
        event_type = field_enum(body, "event_type", DRIVER_EVENTS, required=True)
        field_str(body, "reason")
        caller = get_caller()
        require_role(caller, {"Coordinator"})
        driver = db.drivers.get(did)
        if driver is None:
            raise err_not_found("Driver not found")
        status = driver["status"]

        def state_invalid():
            return ApiError(
                "ERR_DRIVER_STATE_INVALID", 409,
                f"Event {event_type} not permitted from driver status {status}",
            )

        if event_type == "ACTIVATE":
            if status != "APPLICANT":
                raise state_invalid()
            if not posture_complete(did, today()):
                raise ApiError(
                    "ERR_DRIVER_COMPLIANCE_INCOMPLETE", 409,
                    "Driver compliance posture is incomplete",
                )
            driver["status"] = "ACTIVE"
            touch(driver)
        elif event_type == "SUSPEND":
            if status != "ACTIVE":
                raise state_invalid()
            driver["status"] = "SUSPENDED"
            touch(driver)
            driver_release_cascade(driver)
        elif event_type == "REINSTATE":
            if status != "SUSPENDED":
                raise state_invalid()
            if not posture_complete(did, today()):
                raise ApiError(
                    "ERR_DRIVER_COMPLIANCE_INCOMPLETE", 409,
                    "Driver compliance posture is incomplete",
                )
            driver["status"] = "ACTIVE"
            touch(driver)
        elif event_type == "OFFBOARD":
            if status == "ACTIVE":
                driver["status"] = "OFFBOARDED"
                touch(driver)
                driver_release_cascade(driver)
            elif status == "SUSPENDED":
                driver["status"] = "OFFBOARDED"
                touch(driver)
            else:
                raise state_invalid()
        return ok(ser_driver(driver))

    # ------------------------------------------------------------------
    # Compliance documents
    # ------------------------------------------------------------------

    @app.route("/compliance-docs", methods=["POST"])
    def create_compliance_doc():
        body = get_body()
        driver_id = field_str(body, "driver_id", required=True)
        doc_type = field_enum(body, "doc_type", DOC_TYPES, required=True)
        valid_from = field_date(body, "valid_from", required=True)
        valid_until = field_date(body, "valid_until", required=True)
        renewal_of = field_str(body, "renewal_of_doc_id")
        caller = get_caller()
        require_role(caller, {"Coordinator", "Driver"})
        if caller.role == "Driver" and caller.user_id != driver_id:
            raise err_forbidden("Driver may only submit their own documents")
        if driver_id not in db.drivers:
            raise err_not_found("Driver not found")
        if renewal_of is not None and renewal_of not in db.compliance_docs:
            raise err_not_found("renewal_of_doc_id not found")
        if valid_until <= valid_from:
            raise ApiError(
                "ERR_DOC_WINDOW_INVALID", 422,
                "valid_until must be strictly after valid_from",
            )
        doc = {
            "driver_id": driver_id,
            "doc_type": doc_type,
            "status": "PENDING_REVIEW",
            "valid_from": valid_from,
            "valid_until": valid_until,
            "renewal_of_doc_id": renewal_of,
            "reviewed_by_user_id": None,
            "review_note": None,
        }
        stamp_new(doc)
        db.compliance_docs[doc["id"]] = doc
        return ok(ser_compliance_doc(doc), status=201)

    @app.route("/compliance-docs/<did>", methods=["GET"])
    def get_compliance_doc(did):
        caller = get_caller()
        require_role(
            caller, {"PlatformAdmin", "Coordinator", "ComplianceOfficer", "Driver"}
        )
        doc = db.compliance_docs.get(did)
        if doc is None:
            raise err_not_found("Compliance document not found")
        if caller.role == "Driver" and doc["driver_id"] != caller.user_id:
            raise err_forbidden("Driver may only access their own documents")
        return ok(ser_compliance_doc(doc))

    @app.route("/compliance-docs", methods=["GET"])
    def list_compliance_docs():
        caller = get_caller()
        require_role(caller, {"PlatformAdmin", "Coordinator", "ComplianceOfficer"})
        limit, offset = parse_pagination()
        items = sort_created(db.compliance_docs.values())
        driver_id = request.args.get("driver_id")
        doc_type = request.args.get("doc_type")
        status = request.args.get("status")
        renewal_of = request.args.get("renewal_of_doc_id")
        if driver_id is not None:
            items = [d for d in items if d["driver_id"] == driver_id]
        if doc_type is not None:
            items = [d for d in items if d["doc_type"] == doc_type]
        if status is not None:
            items = [d for d in items if d["status"] == status]
        if renewal_of is not None:
            items = [d for d in items if d["renewal_of_doc_id"] == renewal_of]
        page, meta = paginate(items, limit, offset)
        return ok(
            [ser_compliance_doc(d) for d in page],
            response_type="array", pagination=meta,
        )

    @app.route("/compliance-docs/<did>/review", methods=["POST"])
    def review_compliance_doc(did):
        body = get_body()
        decision = field_enum(body, "decision", DOC_REVIEW_DECISIONS, required=True)
        note = field_str(body, "review_note")
        caller = get_caller()
        require_role(caller, {"ComplianceOfficer"})
        doc = db.compliance_docs.get(did)
        if doc is None:
            raise err_not_found("Compliance document not found")
        if doc["status"] != "PENDING_REVIEW":
            raise ApiError(
                "ERR_DOC_ALREADY_REVIEWED", 409,
                "Document is no longer pending review",
            )
        doc["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
        doc["reviewed_by_user_id"] = caller.user_id
        doc["review_note"] = note
        touch(doc)
        return ok(ser_compliance_doc(doc))
