"""Claim files, the evidence log, survey orders and the subrogation axis."""
from decimal import Decimal

from flask import Blueprint

import clock
import serialize
import services
from errors import ApiError, require_state
from response import array_response, object_response
from store import db, new_row, ordered, ordered_by, touch
from validation import (D, authenticate, body, get_bool, get_decimal, get_dt, get_enum,
                        get_str, pagination, paginate, q2, query_enum, query_str)

bp = Blueprint("claims", __name__)

LOSS_TYPES = ("PARTICULAR_AVERAGE", "GENERAL_AVERAGE", "SALVAGE_CHARGE", "TOTAL_LOSS",
              "SHORTAGE")
PERILS = ("SEA_PERIL", "WET_DAMAGE", "JETTISON", "WAR", "STRIKES", "THEFT", "HANDLING")
ADJUSTMENT_BASES = ("DEPRECIATION_PCT", "SALVAGE_SALE_PROCEEDS")
CLAIM_STATUSES = ("OPENED", "SURVEY_ORDERED", "SURVEY_RECEIVED", "DOCS_INCOMPLETE",
                  "ADJUSTED", "SETTLED", "DENIED")
SUBROGATION_STATUSES = ("NOT_STARTED", "NOTICE_SENT", "RECOVERED", "TIME_BARRED")
DOC_TYPES = ("SURVEY_REPORT", "PACKING_LIST", "BILL_OF_LADING", "COMMERCIAL_INVOICE",
             "CARRIER_CLAIM_LETTER", "PHOTO_SET")
ORDER_STATUSES = ("APPOINTED", "REPORT_FILED", "CANCELLED")


@bp.post("/claim-files")
def create_claim_file():
    authenticate(("ClaimsAdjuster",))
    payload = body()
    certificate_id = get_str(payload, "certificate_id")
    loss_type = get_enum(payload, "loss_type", LOSS_TYPES)
    peril = get_enum(payload, "peril", PERILS)
    adjustment_basis = get_enum(payload, "adjustment_basis", ADJUSTMENT_BASES)
    claimed_amount = get_decimal(payload, "claimed_amount", gt=0)
    loss_date = get_dt(payload, "loss_date")
    ga_event_id = get_str(payload, "ga_event_id", required=False)
    damage_percentage = get_decimal(payload, "damage_percentage", required=False, gt=0,
                                    maximum=Decimal("100"))
    sound_market_value = get_decimal(payload, "sound_market_value", required=False, minimum=0)
    damaged_sale_proceeds = get_decimal(payload, "damaged_sale_proceeds", required=False,
                                        minimum=0)

    cert = services.find(db.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND")
    ga_event = None
    if ga_event_id is not None:
        ga_event = services.find(db.ga_events, ga_event_id, "ERR_GA_EVENT_NOT_FOUND")

    require_state("Certificate", "status", cert["status"], ("ISSUED",))

    linked_ga_event_id = None
    if ga_event is not None and loss_type == "GENERAL_AVERAGE":
        linked_ga_event_id = ga_event["id"]

    row = new_row()
    row.update({
        "certificate_id": cert["id"],
        "ga_event_id": linked_ga_event_id,
        "loss_type": loss_type,
        "peril": peril,
        "adjustment_basis": adjustment_basis,
        "claimed_amount": claimed_amount,
        "loss_date": loss_date,
        "damage_percentage": damage_percentage,
        "sound_market_value": sound_market_value,
        "damaged_sale_proceeds": damaged_sale_proceeds,
        "carrier_name": None,
        "adjusted_amount": None,
        "deductible_applied_amount": None,
        "settled_amount": None,
        "documentation_complete": False,
        "warranty_breach": False,
        "adjusted_by_user_id": None,
        "settled_by_user_id": None,
        "subrogation_status": "NOT_STARTED",
        "subrogation_notice_at": None,
        "time_bar_at": None,
        "recovered_amount": Decimal("0.00"),
        "net_loss_amount": Decimal("0.00"),
        "status": "OPENED",
    })
    db.claim_files[row["id"]] = row

    cert["status"] = "CLAIMED"
    touch(cert)
    return object_response(serialize.claim_file(row), 201)


@bp.get("/claim-files/<claim_id>")
def read_claim_file(claim_id):
    authenticate(("ClaimsAdjuster", "Underwriter", "ComplianceOfficer", "Surveyor",
                  "PlatformAdmin"))
    claim = services.find(db.claim_files, claim_id, "ERR_CLAIM_NOT_FOUND")
    return object_response(serialize.claim_file(claim))


@bp.get("/claim-files")
def list_claim_files():
    authenticate(("ClaimsAdjuster", "Underwriter", "ComplianceOfficer", "PlatformAdmin"))
    limit, offset = pagination()
    certificate_id = query_str("certificate_id")
    ga_event_id = query_str("ga_event_id")
    status = query_enum("status", CLAIM_STATUSES)
    subrogation_status = query_enum("subrogation_status", SUBROGATION_STATUSES)
    rows = [r for r in db.claim_files.values()
            if (certificate_id is None or r["certificate_id"] == certificate_id)
            and (ga_event_id is None or r["ga_event_id"] == ga_event_id)
            and (status is None or r["status"] == status)
            and (subrogation_status is None or r["subrogation_status"] == subrogation_status)]
    page, limit, offset, total = paginate(ordered(rows), limit, offset, serialize.claim_file)
    return array_response(page, limit, offset, total)


@bp.post("/claim-files/<claim_id>/documents")
def append_document(claim_id):
    _user_id, role = authenticate(("ClaimsAdjuster", "Surveyor"))
    payload = body()
    doc_type = get_enum(payload, "doc_type", DOC_TYPES)
    reference = get_str(payload, "reference")
    received_at = get_dt(payload, "received_at", required=False)
    claim = services.find(db.claim_files, claim_id, "ERR_CLAIM_NOT_FOUND")
    if received_at is None:
        received_at = clock.now()
    origin = "SURVEYOR" if role == "Surveyor" else "ADJUSTER"
    doc = services.append_document(claim, doc_type, reference, received_at, origin)
    touch(claim)
    return object_response(serialize.damage_document(doc), 201)


@bp.get("/claim-files/<claim_id>/documents")
def list_documents(claim_id):
    authenticate(("ClaimsAdjuster", "Underwriter", "ComplianceOfficer", "Surveyor",
                  "PlatformAdmin"))
    limit, offset = pagination()
    doc_type = query_enum("doc_type", DOC_TYPES)
    claim = services.find(db.claim_files, claim_id, "ERR_CLAIM_NOT_FOUND")
    rows = [d for d in db.damage_documents.values()
            if d["claim_file_id"] == claim["id"]
            and (doc_type is None or d["doc_type"] == doc_type)]
    page, limit, offset, total = paginate(ordered_by(rows, "received_at"), limit, offset,
                                         serialize.damage_document)
    return array_response(page, limit, offset, total)


@bp.post("/claim-files/<claim_id>/adjust")
def adjust_claim(claim_id):
    user_id, _role = authenticate(("ClaimsAdjuster",))
    payload = body()
    damage_percentage = get_decimal(payload, "damage_percentage", required=False, gt=0,
                                    maximum=Decimal("100"))
    sound_market_value = get_decimal(payload, "sound_market_value", required=False, minimum=0)
    damaged_sale_proceeds = get_decimal(payload, "damaged_sale_proceeds", required=False,
                                        minimum=0)
    claim = services.find(db.claim_files, claim_id, "ERR_CLAIM_NOT_FOUND")
    require_state("ClaimFile", "status", claim["status"],
                  ("OPENED", "SURVEY_RECEIVED", "DOCS_INCOMPLETE"))
    if damage_percentage is not None:
        claim["damage_percentage"] = damage_percentage
    if sound_market_value is not None:
        claim["sound_market_value"] = sound_market_value
    if damaged_sale_proceeds is not None:
        claim["damaged_sale_proceeds"] = damaged_sale_proceeds

    cert = db.certificates[claim["certificate_id"]]
    commodity = db.commodity_classes[cert["commodity_class_id"]]

    if claim["warranty_breach"]:
        claim["status"] = "DENIED"
        claim["adjusted_amount"] = Decimal("0.00")
        claim["deductible_applied_amount"] = Decimal("0.00")
        claim["adjusted_by_user_id"] = user_id
        touch(claim)
        return object_response(serialize.claim_file(claim))

    if D(claim["claimed_amount"]) > D(commodity["survey_required_above_amount"]):
        filed = any(o["claim_file_id"] == claim["id"] and o["status"] == "REPORT_FILED"
                    for o in db.survey_orders.values())
        if not filed:
            raise ApiError("ERR_SURVEY_REQUIRED")

    if not claim["documentation_complete"]:
        claim["status"] = "DOCS_INCOMPLETE"
        touch(claim)
        return object_response(serialize.claim_file(claim))

    adjusted, applied = services.quantify_loss(claim, cert)
    claim["status"] = "ADJUSTED"
    claim["adjusted_amount"] = adjusted
    claim["deductible_applied_amount"] = applied
    claim["adjusted_by_user_id"] = user_id
    claim["time_bar_at"] = clock.plus_days(clock.midnight(cert["discharge_date"]),
                                           services.SUBROGATION_TIME_BAR_DAYS)
    touch(claim)
    return object_response(serialize.claim_file(claim))


@bp.post("/claim-files/<claim_id>/settle")
def settle_claim(claim_id):
    user_id, _role = authenticate(("ClaimsAdjuster",))
    claim = services.find(db.claim_files, claim_id, "ERR_CLAIM_NOT_FOUND")
    if user_id == claim["adjusted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    require_state("ClaimFile", "status", claim["status"], ("ADJUSTED",))
    if claim["ga_event_id"] is not None:
        event = db.ga_events.get(claim["ga_event_id"])
        if event is None or event["status"] != "ADJUSTED":
            raise ApiError("ERR_GA_ADJUSTMENT_PENDING")
    claim["status"] = "SETTLED"
    claim["settled_amount"] = q2(claim["adjusted_amount"])
    claim["net_loss_amount"] = q2(D(claim["adjusted_amount"])
                                  - D(claim["recovered_amount"] or 0))
    claim["settled_by_user_id"] = user_id
    touch(claim)
    return object_response(serialize.claim_file(claim))


@bp.post("/claim-files/<claim_id>/subrogation-notice")
def subrogation_notice(claim_id):
    authenticate(("ClaimsAdjuster",))
    payload = body()
    carrier_name = get_str(payload, "carrier_name")
    claim = services.find(db.claim_files, claim_id, "ERR_CLAIM_NOT_FOUND")
    require_state("ClaimFile", "subrogation_status", claim["subrogation_status"],
                  ("NOT_STARTED",))
    if claim["status"] not in ("ADJUSTED", "SETTLED"):
        raise ApiError("ERR_INVALID_STATE")
    if claim["time_bar_at"] is not None and clock.now() >= claim["time_bar_at"]:
        claim["subrogation_status"] = "TIME_BARRED"
        touch(claim)
        raise ApiError("ERR_SUBROGATION_TIME_BARRED")
    claim["subrogation_status"] = "NOTICE_SENT"
    claim["carrier_name"] = carrier_name
    claim["subrogation_notice_at"] = clock.now()
    touch(claim)
    return object_response(serialize.claim_file(claim))


@bp.post("/claim-files/<claim_id>/subrogation-recovery")
def subrogation_recovery(claim_id):
    authenticate(("ClaimsAdjuster",))
    payload = body()
    recovered_amount = get_decimal(payload, "recovered_amount", minimum=0)
    claim = services.find(db.claim_files, claim_id, "ERR_CLAIM_NOT_FOUND")
    require_state("ClaimFile", "subrogation_status", claim["subrogation_status"],
                  ("NOTICE_SENT",))
    if claim["status"] != "SETTLED":
        raise ApiError("ERR_INVALID_STATE")
    if recovered_amount > D(claim["settled_amount"] or 0):
        raise ApiError("ERR_RECOVERY_EXCEEDS_SETTLEMENT")
    claim["subrogation_status"] = "RECOVERED"
    claim["recovered_amount"] = recovered_amount
    claim["net_loss_amount"] = q2(D(claim["settled_amount"]) - recovered_amount)
    touch(claim)
    return object_response(serialize.claim_file(claim))


# ============================== SurveyOrder ================================ #
@bp.post("/survey-orders")
def create_survey_order():
    authenticate(("ClaimsAdjuster",))
    payload = body()
    claim_file_id = get_str(payload, "claim_file_id")
    surveyor_id = get_str(payload, "surveyor_id")
    window_start_at = get_dt(payload, "window_start_at")
    window_end_at = get_dt(payload, "window_end_at")
    if not (window_end_at > window_start_at):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'window_end_at' must be strictly later than 'window_start_at'.")
    minutes = services.window_minutes_of(window_start_at, window_end_at)
    if minutes < services.SURVEY_WINDOW_MIN_MINUTES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The attendance window must be at least 30 minutes.")
    if minutes > services.SURVEY_WINDOW_MAX_MINUTES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The attendance window must be at most 480 minutes.")

    claim = services.find(db.claim_files, claim_file_id, "ERR_CLAIM_NOT_FOUND")
    surveyor = services.find(db.surveyors, surveyor_id, "ERR_SURVEYOR_NOT_FOUND")
    require_state("ClaimFile", "status", claim["status"], ("OPENED", "DOCS_INCOMPLETE"))

    services.check_window_conflict(surveyor, window_start_at, window_end_at)
    cert = db.certificates[claim["certificate_id"]]
    commodity = db.commodity_classes[cert["commodity_class_id"]]
    if commodity["susceptibility_rating"] not in surveyor["certified_commodity_ratings"]:
        raise ApiError("ERR_SURVEYOR_NOT_CERTIFIED")
    if surveyor["status"] != "ACTIVE":
        raise ApiError("ERR_SURVEYOR_INACTIVE")

    row = new_row()
    row.update({
        "claim_file_id": claim["id"],
        "surveyor_id": surveyor["id"],
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "window_minutes": minutes,
        "packaging_compliant": None,
        "damage_percentage_found": None,
        "report_reference": None,
        "status": "APPOINTED",
    })
    db.survey_orders[row["id"]] = row

    surveyor["booked_minutes_total"] += minutes
    touch(surveyor)
    claim["status"] = "SURVEY_ORDERED"
    touch(claim)
    return object_response(serialize.survey_order(row), 201)


@bp.get("/survey-orders/<order_id>")
def read_survey_order(order_id):
    authenticate(("ClaimsAdjuster", "Surveyor", "ComplianceOfficer", "Underwriter",
                  "PlatformAdmin"))
    order = services.find(db.survey_orders, order_id, "ERR_SURVEY_ORDER_NOT_FOUND")
    return object_response(serialize.survey_order(order))


@bp.get("/survey-orders")
def list_survey_orders():
    authenticate(("ClaimsAdjuster", "Surveyor", "ComplianceOfficer", "Underwriter",
                  "PlatformAdmin"))
    limit, offset = pagination()
    claim_file_id = query_str("claim_file_id")
    surveyor_id = query_str("surveyor_id")
    status = query_enum("status", ORDER_STATUSES)
    rows = [r for r in db.survey_orders.values()
            if (claim_file_id is None or r["claim_file_id"] == claim_file_id)
            and (surveyor_id is None or r["surveyor_id"] == surveyor_id)
            and (status is None or r["status"] == status)]
    page, limit, offset, total = paginate(ordered(rows), limit, offset, serialize.survey_order)
    return array_response(page, limit, offset, total)


@bp.post("/survey-orders/<order_id>/file-report")
def file_report(order_id):
    user_id, _role = authenticate(("Surveyor",))
    payload = body()
    packaging_compliant = get_bool(payload, "packaging_compliant", required=True)
    report_reference = get_str(payload, "report_reference")
    damage_percentage_found = get_decimal(payload, "damage_percentage_found", required=False,
                                         minimum=0, maximum=Decimal("100"))
    order = services.find(db.survey_orders, order_id, "ERR_SURVEY_ORDER_NOT_FOUND")
    if user_id != order["surveyor_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    require_state("SurveyOrder", "status", order["status"], ("APPOINTED",))
    surveyor = db.surveyors[order["surveyor_id"]]
    if surveyor["status"] != "ACTIVE":
        raise ApiError("ERR_SURVEYOR_INACTIVE")
    if clock.now() < order["window_start_at"]:
        raise ApiError("ERR_INVALID_STATE")

    order["status"] = "REPORT_FILED"
    order["packaging_compliant"] = packaging_compliant
    order["report_reference"] = report_reference
    order["damage_percentage_found"] = damage_percentage_found
    touch(order)

    claim = db.claim_files[order["claim_file_id"]]
    services.append_document(claim, "SURVEY_REPORT", report_reference, clock.now(), "SURVEYOR")
    if not packaging_compliant:
        claim["warranty_breach"] = True
    if (claim["adjustment_basis"] == "DEPRECIATION_PCT"
            and claim["damage_percentage"] is None
            and damage_percentage_found is not None):
        claim["damage_percentage"] = damage_percentage_found
    if claim["status"] == "SURVEY_ORDERED":
        claim["status"] = "SURVEY_RECEIVED"
    touch(claim)
    return object_response(serialize.survey_order(order))


@bp.post("/survey-orders/<order_id>/cancel")
def cancel_survey_order(order_id):
    authenticate(("ClaimsAdjuster",))
    order = services.find(db.survey_orders, order_id, "ERR_SURVEY_ORDER_NOT_FOUND")
    require_state("SurveyOrder", "status", order["status"], ("APPOINTED",))
    order["status"] = "CANCELLED"
    touch(order)
    surveyor = db.surveyors[order["surveyor_id"]]
    surveyor["booked_minutes_total"] -= order["window_minutes"]
    touch(surveyor)
    claim = db.claim_files[order["claim_file_id"]]
    if claim["status"] == "SURVEY_ORDERED":
        still_standing = any(o["id"] != order["id"]
                            and o["claim_file_id"] == claim["id"]
                            and o["status"] == "APPOINTED"
                            for o in db.survey_orders.values())
        if not still_standing:
            claim["status"] = "OPENED"
            touch(claim)
    return object_response(serialize.survey_order(order))
