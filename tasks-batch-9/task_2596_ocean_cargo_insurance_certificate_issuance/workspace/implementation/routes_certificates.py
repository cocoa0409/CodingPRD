"""Certificates (declare, issue, endorse, cancel, confirm delivery) and the ledger."""
from decimal import Decimal

from flask import Blueprint

import clock
import serialize
import services
from errors import ApiError, require_state
from response import array_response, object_response
from store import db, new_row, ordered, touch
from validation import (D, authenticate, body, get_bool, get_decimal, get_dt, get_enum,
                        get_int, get_str, pagination, paginate, q2, query_dt, query_enum,
                        query_str)

bp = Blueprint("certificates", __name__)

CERT_STATUSES = ("DRAFT", "ISSUED", "SUPERSEDED", "CANCELLED", "TRANSIT_ENDED", "CLAIMED")
WAR_STATUSES = ("PENDING", "ATTACHED", "TERMINATED", "REINSTATED", "NOT_TAKEN")
PACKAGING_CODES = ("STD", "EXPORT_CRATE", "IBC_LINED", "REEFER_SEALED")
VALUATION_BASES = ("CIF_PLUS_MARKUP", "DECLARED_VALUE")


def _require_owner(user_id, policy_id):
    if user_id != policy_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


def _check_packaging(cert, commodity):
    if cert["packaging_code"] != commodity["required_packaging_code"]:
        raise ApiError("ERR_PACKAGING_WARRANTY_BREACH")


def _check_voyage_dates(cert):
    sailing, discharge = cert["sailing_date"], cert["discharge_date"]
    if not clock.is_midnight(sailing) or not clock.is_midnight(discharge):
        raise ApiError("ERR_VOYAGE_DATES_INVALID")
    if not (sailing < discharge):
        raise ApiError("ERR_VOYAGE_DATES_INVALID")


def _check_valuation_inputs(cert):
    if cert["valuation_basis"] == "DECLARED_VALUE":
        if cert["declared_value"] is None or D(cert["declared_value"]) <= 0:
            raise ApiError("ERR_VALUATION_INPUT_MISSING")
    else:
        if cert["invoice_value"] is None or D(cert["invoice_value"]) <= 0:
            raise ApiError("ERR_VALUATION_INPUT_MISSING")


def _blank_certificate():
    row = new_row()
    row.update({
        "open_policy_id": None,
        "commodity_class_id": None,
        "vessel_id": None,
        "loading_port_id": None,
        "discharge_port_id": None,
        "replaces_certificate_id": None,
        "premium_declaration_id": None,
        "certificate_number": None,
        "valuation_basis": None,
        "invoice_value": None,
        "freight_amount": None,
        "duty_amount": Decimal("0.00"),
        "declared_value": None,
        "packaging_code": None,
        "package_count": None,
        "gross_weight_kg": None,
        "sailing_date": None,
        "discharge_date": None,
        "war_cover_requested": True,
        "strikes_cover_requested": True,
        "insured_value": None,
        "attachment_at": None,
        "transit_termination_at": None,
        "effective_rate_per_mille": None,
        "base_premium_amount": None,
        "war_premium_amount": None,
        "strikes_premium_amount": None,
        "total_premium_amount": None,
        "reinstatement_premium_amount": Decimal("0.00"),
        "return_premium_amount": Decimal("0.00"),
        "deductible_amount": None,
        "status": "DRAFT",
        "war_cover_status": "PENDING",
        "issued_by_user_id": None,
        "issued_at": None,
        "ga_contribution_amount": Decimal("0.00"),
        "cancellation_reason": None,
        "delivered_at": None,
    })
    return row


@bp.post("/certificates")
def create_certificate():
    user_id, _role = authenticate(("Assured",))
    payload = body()
    open_policy_id = get_str(payload, "open_policy_id")
    commodity_class_id = get_str(payload, "commodity_class_id")
    vessel_id = get_str(payload, "vessel_id")
    loading_port_id = get_str(payload, "loading_port_id")
    discharge_port_id = get_str(payload, "discharge_port_id")
    certificate_number = get_str(payload, "certificate_number")
    valuation_basis = get_enum(payload, "valuation_basis", VALUATION_BASES)
    packaging_code = get_enum(payload, "packaging_code", PACKAGING_CODES)
    package_count = get_int(payload, "package_count", gt=0)
    gross_weight_kg = get_decimal(payload, "gross_weight_kg", gt=0)
    sailing_date = get_dt(payload, "sailing_date")
    discharge_date = get_dt(payload, "discharge_date")
    invoice_value = get_decimal(payload, "invoice_value", required=False, minimum=0)
    freight_amount = get_decimal(payload, "freight_amount", required=False, minimum=0)
    duty_amount = get_decimal(payload, "duty_amount", required=False, default=Decimal("0.00"),
                              minimum=0)
    declared_value = get_decimal(payload, "declared_value", required=False, minimum=0)
    war_cover_requested = get_bool(payload, "war_cover_requested", default=True)
    strikes_cover_requested = get_bool(payload, "strikes_cover_requested", default=True)

    policy = services.find(db.open_policies, open_policy_id, "ERR_POLICY_NOT_FOUND")
    commodity = services.find(db.commodity_classes, commodity_class_id,
                              "ERR_COMMODITY_CLASS_NOT_FOUND")
    vessel = services.find(db.vessels, vessel_id, "ERR_VESSEL_NOT_FOUND")
    loading_port = services.find(db.ports, loading_port_id, "ERR_PORT_NOT_FOUND")
    discharge_port = services.find(db.ports, discharge_port_id, "ERR_PORT_NOT_FOUND")

    _require_owner(user_id, policy["id"])

    for other in db.certificates.values():
        if other["certificate_number"] == certificate_number:
            raise ApiError("ERR_DUPLICATE_REFERENCE")

    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")

    row = _blank_certificate()
    row.update({
        "open_policy_id": policy["id"],
        "commodity_class_id": commodity["id"],
        "vessel_id": vessel["id"],
        "loading_port_id": loading_port["id"],
        "discharge_port_id": discharge_port["id"],
        "certificate_number": certificate_number,
        "valuation_basis": valuation_basis,
        "packaging_code": packaging_code,
        "package_count": package_count,
        "gross_weight_kg": gross_weight_kg,
        "sailing_date": sailing_date,
        "discharge_date": discharge_date,
        "invoice_value": invoice_value,
        "freight_amount": freight_amount,
        "duty_amount": duty_amount,
        "declared_value": declared_value,
        "war_cover_requested": war_cover_requested,
        "strikes_cover_requested": strikes_cover_requested,
        "deductible_amount": q2(policy["deductible_amount"]),
    })

    _check_packaging(row, commodity)
    _check_voyage_dates(row)
    _check_valuation_inputs(row)
    row["insured_value"] = services.insured_value_for(row, policy)
    services.check_commodity_share(policy, commodity, row["insured_value"])

    db.certificates[row["id"]] = row
    return object_response(serialize.certificate(row), 201)


@bp.get("/certificates/<certificate_id>")
def read_certificate(certificate_id):
    authenticate(("Underwriter", "Assured", "ComplianceOfficer", "ClaimsAdjuster",
                  "PremiumAuditor", "Surveyor", "PlatformAdmin"))
    cert = services.find(db.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND")
    return object_response(serialize.certificate(cert))


@bp.get("/certificates")
def list_certificates():
    authenticate(("Underwriter", "Assured", "ComplianceOfficer", "ClaimsAdjuster",
                  "PremiumAuditor", "PlatformAdmin"))
    limit, offset = pagination()
    filters = {
        "open_policy_id": query_str("open_policy_id"),
        "commodity_class_id": query_str("commodity_class_id"),
        "vessel_id": query_str("vessel_id"),
        "loading_port_id": query_str("loading_port_id"),
        "discharge_port_id": query_str("discharge_port_id"),
        "replaces_certificate_id": query_str("replaces_certificate_id"),
        "premium_declaration_id": query_str("premium_declaration_id"),
    }
    status = query_enum("status", CERT_STATUSES)
    war_status = query_enum("war_cover_status", WAR_STATUSES)
    sailing_date = query_dt("sailing_date")

    rows = []
    for row in db.certificates.values():
        if any(v is not None and row[k] != v for k, v in filters.items()):
            continue
        if status is not None and row["status"] != status:
            continue
        if war_status is not None and row["war_cover_status"] != war_status:
            continue
        if sailing_date is not None and row["sailing_date"] != sailing_date:
            continue
        rows.append(row)
    page, limit, offset, total = paginate(ordered(rows), limit, offset, serialize.certificate)
    return array_response(page, limit, offset, total)


def _refs(cert):
    return (services.policy_of(cert),
            db.commodity_classes[cert["commodity_class_id"]],
            db.vessels[cert["vessel_id"]],
            db.ports[cert["loading_port_id"]],
            db.ports[cert["discharge_port_id"]])


def _price_and_pin(cert, policy, commodity, vessel, loading_port, discharge_port,
                   insured_value):
    """Pin insured value, the cover window, the war axis and the premium components."""
    cert["insured_value"] = insured_value
    cert["attachment_at"] = clock.midnight(cert["sailing_date"])
    cert["transit_termination_at"] = services.transit_termination_for(cert, policy,
                                                                     discharge_port)
    war_attached = services.war_axis_attached(cert, policy, loading_port, discharge_port)
    components = services.premium_components(cert, policy, commodity, vessel, loading_port,
                                             discharge_port, insured_value, war_attached)
    cert.update(components)
    cert["war_cover_status"] = "ATTACHED" if war_attached else "NOT_TAKEN"
    cert["deductible_amount"] = q2(policy["deductible_amount"])
    return war_attached


@bp.post("/certificates/<certificate_id>/issue")
def issue_certificate(certificate_id):
    user_id, _role = authenticate(("Underwriter",))
    payload = body()
    expected_version = get_int(payload, "expected_open_policy_version", minimum=0)
    cert = services.find(db.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND")
    policy, commodity, vessel, loading_port, discharge_port = _refs(cert)

    require_state("Certificate", "status", cert["status"], ("DRAFT",))
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    if expected_version != policy["version"]:
        raise ApiError("ERR_STALE_POLICY_VERSION")
    if policy["war_cover_status"] == "TERMINATED" and (cert["war_cover_requested"]
                                                      or cert["strikes_cover_requested"]):
        raise ApiError("ERR_WAR_COVER_TERMINATED")
    if vessel["status"] not in ("APPROVED", "OVERAGE_SURCHARGED"):
        raise ApiError("ERR_VESSEL_BLOCKED")
    _check_packaging(cert, commodity)
    attachment_at = clock.midnight(cert["sailing_date"])
    if not (policy["inception_at"] <= attachment_at < policy["expiry_at"]):
        raise ApiError("ERR_OUTSIDE_POLICY_PERIOD")

    insured_value = services.insured_value_for(cert, policy)
    candidate_end = services.transit_termination_for(cert, policy, discharge_port)
    services.run_capacity_tower(cert, policy, commodity, vessel, discharge_port,
                                insured_value, candidate_end)

    _price_and_pin(cert, policy, commodity, vessel, loading_port, discharge_port,
                   insured_value)
    cert["status"] = "ISSUED"
    cert["issued_by_user_id"] = user_id
    cert["issued_at"] = clock.now()
    services.book_exposure(cert, vessel, loading_port, discharge_port, insured_value)
    policy["aggregate_insured_value_booked"] = q2(
        D(policy["aggregate_insured_value_booked"]) + insured_value)
    policy["aggregate_premium_booked"] = q2(
        D(policy["aggregate_premium_booked"]) + D(cert["total_premium_amount"]))
    policy["certificates_issued_count"] += 1
    touch(policy)
    touch(cert)
    return object_response(serialize.certificate(cert))


@bp.post("/certificates/<certificate_id>/endorse")
def endorse_certificate(certificate_id):
    user_id, _role = authenticate(("Underwriter",))
    payload = body()
    certificate_number = get_str(payload, "certificate_number")
    invoice_value = get_decimal(payload, "invoice_value", required=False, minimum=0)
    declared_value = get_decimal(payload, "declared_value", required=False, minimum=0)
    packaging_code = get_enum(payload, "packaging_code", PACKAGING_CODES, required=False)
    package_count = get_int(payload, "package_count", required=False, gt=0)
    gross_weight_kg = get_decimal(payload, "gross_weight_kg", required=False, gt=0)
    sailing_date = get_dt(payload, "sailing_date", required=False)
    discharge_date = get_dt(payload, "discharge_date", required=False)

    original = services.find(db.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND")
    policy, commodity, vessel, loading_port, discharge_port = _refs(original)

    for other in db.certificates.values():
        if other["certificate_number"] == certificate_number:
            raise ApiError("ERR_DUPLICATE_REFERENCE")

    require_state("Certificate", "status", original["status"], ("ISSUED",))
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    if original["premium_declaration_id"] is not None:
        raise ApiError("ERR_INVALID_STATE")

    replacement = _blank_certificate()
    for field in ("open_policy_id", "commodity_class_id", "vessel_id", "loading_port_id",
                  "discharge_port_id", "valuation_basis", "invoice_value", "freight_amount",
                  "duty_amount", "declared_value", "packaging_code", "package_count",
                  "gross_weight_kg", "sailing_date", "discharge_date", "war_cover_requested",
                  "strikes_cover_requested"):
        replacement[field] = original[field]
    replacement["certificate_number"] = certificate_number
    replacement["replaces_certificate_id"] = original["id"]
    if invoice_value is not None:
        replacement["invoice_value"] = invoice_value
    if declared_value is not None:
        replacement["declared_value"] = declared_value
    if packaging_code is not None:
        replacement["packaging_code"] = packaging_code
    if package_count is not None:
        replacement["package_count"] = package_count
    if gross_weight_kg is not None:
        replacement["gross_weight_kg"] = gross_weight_kg
    if sailing_date is not None:
        replacement["sailing_date"] = sailing_date
    if discharge_date is not None:
        replacement["discharge_date"] = discharge_date

    _check_packaging(replacement, commodity)
    _check_voyage_dates(replacement)
    _check_valuation_inputs(replacement)
    insured_value = services.insured_value_for(replacement, policy)
    services.check_commodity_share(policy, commodity, insured_value)

    # the original is returned ab initio and steps aside
    original_insured_value = D(original["insured_value"])
    ab_initio = q2(D(original["total_premium_amount"])
                   + D(original["reinstatement_premium_amount"]))
    original["status"] = "SUPERSEDED"
    original["return_premium_amount"] = q2(D(original["return_premium_amount"]) + ab_initio)
    services.release_exposure(original, "CERTIFICATE_SUPERSEDED")
    touch(original)

    _price_and_pin(replacement, policy, commodity, vessel, loading_port, discharge_port,
                   insured_value)
    replacement["status"] = "ISSUED"
    replacement["issued_by_user_id"] = user_id
    replacement["issued_at"] = clock.now()
    db.certificates[replacement["id"]] = replacement
    services.book_exposure(replacement, vessel, loading_port, discharge_port, insured_value)

    policy["aggregate_return_premium"] = q2(
        D(policy["aggregate_return_premium"]) + ab_initio)
    policy["aggregate_premium_booked"] = q2(
        D(policy["aggregate_premium_booked"]) + D(replacement["total_premium_amount"]))
    policy["aggregate_insured_value_booked"] = q2(
        D(policy["aggregate_insured_value_booked"]) + insured_value - original_insured_value)
    touch(policy)
    return object_response(serialize.certificate(replacement), 201)


@bp.post("/certificates/<certificate_id>/cancel")
def cancel_certificate(certificate_id):
    authenticate(("Underwriter",))
    payload = body()
    cancellation_reason = get_str(payload, "cancellation_reason", required=False)
    cert = services.find(db.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND")
    policy = services.policy_of(cert)
    require_state("Certificate", "status", cert["status"], ("ISSUED",))
    for claim in db.claim_files.values():
        if claim["certificate_id"] == cert["id"] and claim["status"] != "DENIED":
            raise ApiError("ERR_INVALID_STATE")
    for posting in db.ga_postings.values():
        if (posting["certificate_id"] == cert["id"]
                and posting["status"] in ("REQUIRED", "POSTED")):
            raise ApiError("ERR_INVALID_STATE")

    cert["status"] = "CANCELLED"
    if cancellation_reason is not None:
        cert["cancellation_reason"] = cancellation_reason
    delta = services.cancellation_return(cert)
    services.book_return_premium(cert, policy, delta)
    services.release_exposure(cert, "CERTIFICATE_CANCELLED")
    policy["aggregate_insured_value_booked"] = q2(
        D(policy["aggregate_insured_value_booked"]) - D(cert["insured_value"]))
    touch(policy)
    touch(cert)
    return object_response(serialize.certificate(cert))


@bp.post("/certificates/<certificate_id>/confirm-delivery")
def confirm_delivery(certificate_id):
    user_id, _role = authenticate(("Assured",))
    payload = body()
    delivered_at = get_dt(payload, "delivered_at", required=False)
    cert = services.find(db.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND")
    _require_owner(user_id, cert["open_policy_id"])
    require_state("Certificate", "status", cert["status"], ("ISSUED",))
    if clock.now() < cert["attachment_at"]:
        raise ApiError("ERR_INVALID_STATE")

    cert["status"] = "TRANSIT_ENDED"
    if delivered_at is not None:
        cert["delivered_at"] = delivered_at
        if delivered_at < cert["transit_termination_at"]:
            cert["transit_termination_at"] = delivered_at
    services.release_exposure(cert, "DELIVERY_CONFIRMED")
    touch(cert)
    return object_response(serialize.certificate(cert))


# ========================== AccumulationEntry ============================== #
@bp.get("/accumulation-entries")
def list_accumulation_entries():
    authenticate(("Underwriter", "ComplianceOfficer", "PremiumAuditor", "PlatformAdmin"))
    limit, offset = pagination()
    certificate_id = query_str("certificate_id")
    vessel_id = query_str("vessel_id")
    port_id = query_str("port_id")
    scope_type = query_enum("scope_type", ("VESSEL", "LOADING_PORT", "DISCHARGE_PORT"))
    status = query_enum("status", ("ACTIVE", "RELEASED"))
    rows = []
    for row in db.accumulation_entries.values():
        if certificate_id is not None and row["certificate_id"] != certificate_id:
            continue
        if vessel_id is not None and row["vessel_id"] != vessel_id:
            continue
        if port_id is not None and row["port_id"] != port_id:
            continue
        if scope_type is not None and row["scope_type"] != scope_type:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, limit, offset, total = paginate(ordered(rows), limit, offset,
                                         serialize.accumulation_entry)
    return array_response(page, limit, offset, total)


@bp.get("/accumulation-entries/<entry_id>")
def read_accumulation_entry(entry_id):
    authenticate(("Underwriter", "ComplianceOfficer", "PremiumAuditor", "PlatformAdmin"))
    entry = services.find(db.accumulation_entries, entry_id,
                          "ERR_ACCUMULATION_ENTRY_NOT_FOUND")
    return object_response(serialize.accumulation_entry(entry))
