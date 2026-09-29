"""Tariff versions, commodity profiles, rate programs and exception agreements."""
from flask import Blueprint

import auth
import clock
import db
import response
import serialize
import validation
from constants import (
    AGREEMENT_TYPES,
    CLASSIFICATION_BASES,
    HANDLING_CODES,
    LIABILITY_CODES,
    PROGRAM_STATUSES,
    PROGRAM_TYPES,
    STOWABILITY_CODES,
    TARIFF_STATUSES,
)
from errors import fail
from routes import _helpers as h
from services import modeling, notices, rating
from util import rhu

bp = Blueprint("pricing", __name__)

ANALYST_AND_AUDITOR = ("PricingAnalyst", "ClassificationAuditor")


# ---------------------------------------------------------------------------
# tariff versions (PRD 3.1)
# ---------------------------------------------------------------------------
def newest_published():
    rows = db.all_rows("tariff_versions", lambda t: t["status"] == "PUBLISHED")
    rows.sort(key=lambda t: (t["effective_at"], t["created_at"], t["_seq"]))
    return rows[-1] if rows else None


@bp.post("/ltl/tariff-versions")
def create_tariff_version():
    auth.authenticate(("PricingAnalyst",))
    body = validation.body()
    code = validation.req_str(body, "code")
    effective_at = validation.req_datetime(body, "effective_at")
    if "density_breaks" not in body or not isinstance(body.get("density_breaks"), list):
        fail("ERR_INVALID_REQUEST", "density_breaks must be an array.")
    validation.as_density_breaks(body["density_breaks"])

    for row in db.all_rows("tariff_versions"):
        if row["code"] == code:
            fail("ERR_INVALID_REQUEST", "Tariff version code %s already exists." % code)

    row = db.insert(
        "tariff_versions",
        {
            "code": code,
            "effective_at": effective_at,
            "status": "DRAFT",
            "density_breaks": body["density_breaks"],
            "superseded_by_tariff_version_id": None,
            "published_at": None,
        },
    )
    return response.created(serialize.tariff_version(row))


@bp.get("/ltl/tariff-versions/<tariff_version_id>")
def read_tariff_version(tariff_version_id):
    auth.authenticate(ANALYST_AND_AUDITOR)
    row = validation.path_row("tariff_versions", tariff_version_id, "ERR_TARIFF_VERSION_NOT_FOUND")
    return response.ok(serialize.tariff_version(row))


@bp.get("/ltl/tariff-versions")
def list_tariff_versions():
    auth.authenticate(ANALYST_AND_AUDITOR)
    rows = db.all_rows("tariff_versions")
    rows = h.apply_filters(
        rows,
        (
            ("status", "status", TARIFF_STATUSES),
            ("superseded_by_tariff_version_id", "superseded_by_tariff_version_id", None),
        ),
    )
    return h.paged(rows, serialize.tariff_version)


@bp.post("/ltl/tariff-versions/<tariff_version_id>/publish")
def publish_tariff_version(tariff_version_id):
    auth.authenticate(("PricingAnalyst",))
    row = validation.path_row("tariff_versions", tariff_version_id, "ERR_TARIFF_VERSION_NOT_FOUND")
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Tariff version is %s, not DRAFT." % row["status"])

    profiles = db.all_rows(
        "commodity_profiles", lambda p: p["tariff_version_id"] == row["id"]
    )
    if not profiles:
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A tariff version needs at least one commodity profile before publication.",
        )

    previous = newest_published()
    if previous is not None and not row["effective_at"] > previous["effective_at"]:
        fail(
            "ERR_TARIFF_EFFECTIVE_CONFLICT",
            "effective_at must be strictly after the newest published version.",
        )

    row["status"] = "PUBLISHED"
    row["published_at"] = clock.now()
    db.touch(row)
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        previous["superseded_by_tariff_version_id"] = row["id"]
        db.touch(previous)
    return response.ok(serialize.tariff_version(row))


# ---------------------------------------------------------------------------
# commodity profiles (PRD 3.1)
# ---------------------------------------------------------------------------
PROFILE_READ_ROLES = ("PricingAnalyst", "ClassificationAuditor", "FreightInspector", "Shipper")


@bp.post("/ltl/commodity-profiles")
def create_commodity_profile():
    auth.authenticate(("PricingAnalyst",))
    body = validation.body()
    tariff = validation.fk(body, "tariff_version_id", "tariff_versions", "ERR_TARIFF_VERSION_NOT_FOUND")

    if tariff is None:
        validation.req_str(body, "tariff_version_id")
    nmfc_item = validation.req_str(body, "nmfc_item")
    description = validation.req_str(body, "description")
    basis = validation.req_enum(body, "classification_basis", CLASSIFICATION_BASES)
    fixed_raw = body.get("fixed_class_code")
    handling = validation.opt_enum(body, "handling_code", HANDLING_CODES, default="STANDARD")
    stowability = validation.opt_enum(body, "stowability_code", STOWABILITY_CODES, default="STACKABLE")
    liability = validation.opt_enum(body, "liability_code", LIABILITY_CODES, default="LOW")

    if basis == "FIXED_CLASS":
        if fixed_raw is None:
            fail("ERR_INVALID_REQUEST", "fixed_class_code is required for FIXED_CLASS profiles.")
    elif fixed_raw is not None:
        fail("ERR_INVALID_REQUEST", "fixed_class_code must be null unless classification_basis is FIXED_CLASS.")

    fixed_class = None
    if fixed_raw is not None:
        if not validation.is_number(fixed_raw):
            fail("ERR_INVALID_REQUEST", "fixed_class_code must be a number.")
        fixed_class = validation.as_class_code(fixed_raw, "fixed_class_code")

    if tariff["status"] != "DRAFT":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Commodity profiles may only be added to a DRAFT tariff version.",
        )

    row = db.insert(
        "commodity_profiles",
        {
            "tariff_version_id": tariff["id"],
            "nmfc_item": nmfc_item,
            "description": description,
            "classification_basis": basis,
            "fixed_class_code": fixed_class,
            "handling_code": handling,
            "stowability_code": stowability,
            "liability_code": liability,
            "min_class_floor": rating.class_floor(handling, stowability, liability),
        },
    )
    return response.created(serialize.commodity_profile(row))


@bp.get("/ltl/commodity-profiles/<profile_id>")
def read_commodity_profile(profile_id):
    auth.authenticate(PROFILE_READ_ROLES)
    row = validation.path_row("commodity_profiles", profile_id, "ERR_COMMODITY_PROFILE_NOT_FOUND")
    return response.ok(serialize.commodity_profile(row))


@bp.get("/ltl/commodity-profiles")
def list_commodity_profiles():
    auth.authenticate(PROFILE_READ_ROLES)
    rows = db.all_rows("commodity_profiles")
    rows = h.apply_filters(
        rows,
        (
            ("tariff_version_id", "tariff_version_id", None),
            ("classification_basis", "classification_basis", CLASSIFICATION_BASES),
        ),
    )
    return h.paged(rows, serialize.commodity_profile)


# ---------------------------------------------------------------------------
# rate programs (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.post("/ltl/rate-programs")
def create_rate_program():
    auth.authenticate(("PricingAnalyst",))
    body = validation.body()
    customer = validation.fk(body, "customer_id", "customers", "ERR_CUSTOMER_NOT_FOUND")
    if customer is None:
        validation.req_str(body, "customer_id")

    program_type = validation.req_enum(body, "program_type", PROGRAM_TYPES)
    base_rate = validation.req_int(body, "base_rate_per_cwt_cents", minimum=1)
    discount = validation.req_number(body, "discount_pct", minimum=0, maximum="0.75")
    min_charge = validation.req_int(body, "min_charge_cents", minimum=0)

    fak_raw = body.get("fak_class_code")
    if program_type == "FAK":
        if fak_raw is None:
            fail("ERR_INVALID_REQUEST", "fak_class_code is required for FAK programs.")
    elif fak_raw is not None:
        fail("ERR_INVALID_REQUEST", "fak_class_code must be null unless program_type is FAK.")

    fak_class = None
    if fak_raw is not None:
        if not validation.is_number(fak_raw):
            fail("ERR_INVALID_REQUEST", "fak_class_code must be a number.")
        fak_class = validation.as_class_code(fak_raw, "fak_class_code")

    row = db.insert(
        "rate_programs",
        {
            "customer_id": customer["id"],
            "program_type": program_type,
            "status": "MODELING",
            "base_rate_per_cwt_cents": base_rate,
            "discount_pct": discount,
            "min_charge_cents": min_charge,
            "fak_class_code": fak_class,
            "pinned_tariff_version_id": None,
            "effective_from": None,
            "effective_to": None,
            "baseline_revenue_cents": 0,
            "modeled_annual_revenue_cents": 0,
            "modeled_delta_pct": rhu(0, 4),
            "modeled_shipment_count": 0,
            "migration_recommendation": None,
        },
    )
    return response.created(serialize.rate_program(row))


@bp.get("/ltl/rate-programs/<program_id>")
def read_rate_program(program_id):
    auth.authenticate(ANALYST_AND_AUDITOR)
    row = validation.path_row("rate_programs", program_id, "ERR_RATE_PROGRAM_NOT_FOUND")
    return response.ok(serialize.rate_program(row))


@bp.get("/ltl/rate-programs")
def list_rate_programs():
    auth.authenticate(ANALYST_AND_AUDITOR)
    rows = db.all_rows("rate_programs")
    rows = h.apply_filters(
        rows,
        (
            ("customer_id", "customer_id", None),
            ("status", "status", PROGRAM_STATUSES),
            ("program_type", "program_type", PROGRAM_TYPES),
            ("pinned_tariff_version_id", "pinned_tariff_version_id", None),
        ),
    )
    return h.paged(rows, serialize.rate_program)


@bp.post("/ltl/rate-programs/<program_id>/approve")
def approve_rate_program(program_id):
    auth.authenticate(("PricingAnalyst",))
    row = validation.path_row("rate_programs", program_id, "ERR_RATE_PROGRAM_NOT_FOUND")
    if row["status"] != "MODELING":
        fail("ERR_INVALID_STATE_TRANSITION", "Rate program is %s, not MODELING." % row["status"])

    customer = db.get("customers", row["customer_id"])
    if customer is not None and customer["billing_posture"] == "CLOSED":
        fail("ERR_CUSTOMER_CLOSED", "The customer account is CLOSED.")

    tariff = newest_published()
    if tariff is None:
        fail("ERR_NO_EFFECTIVE_TARIFF", "No PUBLISHED tariff version exists.")

    row["status"] = "APPROVED"
    row["pinned_tariff_version_id"] = tariff["id"]
    modeling.apply_model(row, modeling.compute_model(row))
    db.touch(row)
    return response.ok(serialize.rate_program(row))


@bp.post("/ltl/rate-programs/<program_id>/activate")
def activate_rate_program(program_id):
    auth.authenticate(("PricingAnalyst",))
    row = validation.path_row("rate_programs", program_id, "ERR_RATE_PROGRAM_NOT_FOUND")
    body = validation.body()
    expected = validation.req_int(body, "expected_customer_version")

    customer = db.get("customers", row["customer_id"])
    if customer is None:
        fail("ERR_CUSTOMER_NOT_FOUND", "The program's customer no longer exists.")
    if expected != int(customer["version"]):
        fail(
            "ERR_STALE_CUSTOMER_VERSION",
            "Customer version is %s, not %s." % (customer["version"], expected),
        )
    if row["status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION", "Rate program is %s, not APPROVED." % row["status"])
    if customer["billing_posture"] == "CLOSED":
        fail("ERR_CUSTOMER_CLOSED", "The customer account is CLOSED.")

    now = clock.now()
    for other in db.all_rows(
        "rate_programs",
        lambda p: p["customer_id"] == customer["id"] and p["status"] == "ACTIVE",
    ):
        other["status"] = "RETIRED"
        other["effective_to"] = now
        db.touch(other)

    row["status"] = "ACTIVE"
    row["effective_from"] = now
    db.touch(row)

    customer["active_program_type"] = row["program_type"]
    db.touch(customer)
    return response.ok(serialize.rate_program(row))


# ---------------------------------------------------------------------------
# exception agreements (PRD 3.1 / 3.4)
# ---------------------------------------------------------------------------
def _overlaps(agreement, start, end):
    return agreement["effective_from"] < end and start < agreement["effective_to"]


@bp.post("/ltl/exception-agreements")
def create_exception_agreement():
    auth.authenticate(("PricingAnalyst",))
    body = validation.body()
    customer = validation.fk(body, "customer_id", "customers", "ERR_CUSTOMER_NOT_FOUND")
    profile = validation.fk(
        body, "commodity_profile_id", "commodity_profiles", "ERR_COMMODITY_PROFILE_NOT_FOUND"
    )
    if customer is None:
        validation.req_str(body, "customer_id")
    if profile is None:
        validation.req_str(body, "commodity_profile_id")

    agreement_type = validation.req_enum(body, "agreement_type", AGREEMENT_TYPES)
    raw_class = body.get("agreed_class_code")
    if raw_class is None or not validation.is_number(raw_class):
        fail("ERR_INVALID_REQUEST", "agreed_class_code must be a number.")
    effective_from = validation.req_datetime(body, "effective_from")
    effective_to = validation.req_datetime(body, "effective_to")

    agreed_class = validation.as_class_code(raw_class, "agreed_class_code")
    validation.check_interval(
        effective_from, effective_to, "effective_to must be strictly after effective_from"
    )

    for other in db.all_rows(
        "exception_agreements",
        lambda a: (
            a["customer_id"] == customer["id"]
            and a["commodity_profile_id"] == profile["id"]
            and a["status"] in ("PENDING", "ACTIVE")
        ),
    ):
        if _overlaps(other, effective_from, effective_to):
            fail(
                "ERR_EXCEPTION_OVERLAP",
                "An agreement already covers part of this interval for the commodity.",
            )

    row = db.insert(
        "exception_agreements",
        {
            "customer_id": customer["id"],
            "commodity_profile_id": profile["id"],
            "agreement_type": agreement_type,
            "agreed_class_code": agreed_class,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "PENDING",
            "approved_by_user_id": None,
            "approved_at": None,
        },
    )
    return response.created(serialize.exception_agreement(row))


@bp.get("/ltl/exception-agreements/<agreement_id>")
def read_exception_agreement(agreement_id):
    auth.authenticate(ANALYST_AND_AUDITOR)
    row = validation.path_row(
        "exception_agreements", agreement_id, "ERR_EXCEPTION_AGREEMENT_NOT_FOUND"
    )
    return response.ok(serialize.exception_agreement(row))


@bp.get("/ltl/exception-agreements")
def list_exception_agreements():
    auth.authenticate(ANALYST_AND_AUDITOR)
    rows = db.all_rows("exception_agreements")
    rows = h.apply_filters(
        rows,
        (
            ("customer_id", "customer_id", None),
            ("commodity_profile_id", "commodity_profile_id", None),
            ("status", "status", ("PENDING", "ACTIVE")),
        ),
    )
    return h.paged(rows, serialize.exception_agreement)


@bp.post("/ltl/exception-agreements/<agreement_id>/approve")
def approve_exception_agreement(agreement_id):
    auth.authenticate(("PricingAnalyst",))
    row = validation.path_row(
        "exception_agreements", agreement_id, "ERR_EXCEPTION_AGREEMENT_NOT_FOUND"
    )
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE_TRANSITION", "Agreement is %s, not PENDING." % row["status"])

    customer = db.get("customers", row["customer_id"])
    if customer is not None and customer["billing_posture"] == "CLOSED":
        fail("ERR_CUSTOMER_CLOSED", "The customer account is CLOSED.")

    for other in db.all_rows(
        "exception_agreements",
        lambda a: (
            a["id"] != row["id"]
            and a["customer_id"] == row["customer_id"]
            and a["commodity_profile_id"] == row["commodity_profile_id"]
            and a["status"] == "ACTIVE"
        ),
    ):
        if _overlaps(other, row["effective_from"], row["effective_to"]):
            fail("ERR_EXCEPTION_OVERLAP", "An ACTIVE agreement already covers this interval.")

    row["status"] = "ACTIVE"
    row["approved_by_user_id"] = auth.user_id()
    row["approved_at"] = clock.now()
    db.touch(row)

    _reclassify_covered_lines(row)
    return response.ok(serialize.exception_agreement(row))


def _reclassify_covered_lines(agreement):
    """A newly ACTIVE agreement re-resolves the classification of the lines it covers."""
    profile_id = agreement["commodity_profile_id"]

    def covered(shipment):
        if shipment["customer_id"] != agreement["customer_id"]:
            return False
        if shipment["billing_status"] not in ("UNBILLED", "BILLED"):
            return False
        if shipment["class_status"] == "CLASS_CONFIRMED":
            return False
        pickup = shipment.get("pickup_at")
        return pickup is not None and agreement["effective_from"] <= pickup < agreement["effective_to"]

    for shipment in db.all_rows("shipments", covered):
        touched = False
        for line in rating.lines_of(shipment["id"]):
            if not _line_uses_profile(line, profile_id):
                continue
            rating.recompute_line_class(shipment, line)
            db.touch(line)
            touched = True
        if not touched:
            continue
        rating.recompute_line_charges(shipment)
        rating.refresh_delta_count(shipment)
        notices.refresh_draft_notices(shipment)


def _line_uses_profile(line, profile_id):
    if line.get("commodity_profile_id") == profile_id:
        return True
    finding = rating.accepted_finding(line)
    return finding is not None and finding.get("found_commodity_profile_id") == profile_id
