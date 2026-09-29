"""Clock, refrigerant programs, regional standards, platforms, certifications."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import db
import derive
import find
import validate
import web
from errors import ApiError
from prec import dec
from web import endpoint

bp = Blueprint("design", __name__)

READ_ALL = (
    "PlantAdmin",
    "DesignEngineer",
    "ReliabilityEngineer",
    "CertificationEngineer",
    "RegulatoryAuditor",
    "SupplyPlanner",
    "ProductionPlanner",
)


def listing(rows, serializer):
    return web.page([serializer(row) for row in rows])


def eq_filter(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]


def enum_arg(name, values, default):
    raw = web.filter_value(name)
    if raw is None:
        return default
    if raw not in values:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(values)))
    return raw


# ------------------------------------------------------------------- clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["PlantAdmin"], 200)
def set_clock():
    payload = web.body()
    _, parsed = validate.instant_field(payload, "current_utc", required=True)
    db.db.set_clock(parsed)
    return {}


# ------------------------------------------------------ refrigerant programs
@bp.route("/plant/refrigerant-programs", methods=["POST"])
@endpoint(["PlantAdmin"], 201)
def create_program():
    payload = web.body()
    refrigerant_code = validate.str_field(payload, "refrigerant_code", max_len=32)
    gwp = validate.int_field(payload, "gwp", minimum=1)
    flammability_class = validate.enum_field(payload, "flammability_class", ("A1", "A2L"))
    cutoff_raw, cutoff = validate.instant_field(payload, "manufacture_cutoff_utc")
    deadline_raw, deadline = validate.instant_field(payload, "sell_through_deadline_utc")
    if deadline <= cutoff:
        validate.bad("sell_through_deadline_utc must be strictly after manufacture_cutoff_utc.")
    for existing in db.db.rows("programs"):
        if existing["refrigerant_code"] == refrigerant_code:
            validate.bad("refrigerant_code already exists.")

    row = db.db.insert(
        "programs",
        {
            "refrigerant_code": refrigerant_code,
            "gwp": gwp,
            "flammability_class": flammability_class,
            "manufacture_cutoff_utc": cutoff_raw,
            "sell_through_deadline_utc": deadline_raw,
            "status": "ACTIVE",
            "sell_through_entered_at": None,
            "expired_at": None,
            "_manufacture_cutoff": cutoff,
            "_sell_through_deadline": deadline,
        },
    )
    return derive.serialize_program(row)


@bp.route("/plant/refrigerant-programs", methods=["GET"])
@endpoint(READ_ALL, 200)
def list_programs():
    rows = db.db.rows("programs")
    rows = eq_filter(rows, "status", web.filter_value("status"))
    rows = eq_filter(rows, "flammability_class", web.filter_value("flammability_class"))
    return listing(rows, derive.serialize_program)


@bp.route("/plant/refrigerant-programs/<row_id>", methods=["GET"])
@endpoint(READ_ALL, 200)
def read_program(row_id):
    return derive.serialize_program(find.program(row_id))


@bp.route("/plant/refrigerant-programs/<row_id>/enter-sell-through", methods=["POST"])
@endpoint(["PlantAdmin"], 200)
def program_enter_sell_through(row_id):
    web.body()
    program = find.program(row_id)
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_STATE_INVALID", "Program is not ACTIVE.")
    if db.db.now() < program["_manufacture_cutoff"]:
        raise ApiError(
            "ERR_MANUFACTURE_CUTOFF_NOT_REACHED",
            "The manufacture cutoff has not been reached.",
        )
    cascade.enter_sell_through(program)
    return derive.serialize_program(program)


@bp.route("/plant/refrigerant-programs/<row_id>/expire", methods=["POST"])
@endpoint(["PlantAdmin"], 200)
def program_expire(row_id):
    web.body()
    program = find.program(row_id)
    if program["status"] != "SELL_THROUGH":
        raise ApiError("ERR_PROGRAM_STATE_INVALID", "Program is not in SELL_THROUGH.")
    if db.db.now() < program["_sell_through_deadline"]:
        raise ApiError(
            "ERR_SELL_THROUGH_DEADLINE_NOT_REACHED",
            "The sell-through deadline has not been reached.",
        )
    cascade.expire_program(program)
    return derive.serialize_program(program)


# -------------------------------------------------------- regional standards
@bp.route("/plant/regional-standards", methods=["POST"])
@endpoint(["PlantAdmin", "RegulatoryAuditor"], 201)
def create_standard():
    payload = web.body()
    region_code = validate.str_field(
        payload, "region_code", max_len=32, pattern=r"^[A-Z_]+$"
    )
    min_standard = validate.num_field(payload, "min_seer2_standard", places=2, gt=0)
    min_high = validate.num_field(payload, "min_seer2_high", places=2, gt=0)
    min_premium = validate.num_field(payload, "min_seer2_premium", places=2, gt=0)
    effective_raw, effective = validate.instant_field(payload, "effective_from_utc")
    prohibits = validate.bool_field(
        payload, "prohibits_flammable_refrigerant", required=False, default=False
    )
    for existing in db.db.rows("standards"):
        if existing["status"] == "ACTIVE" and existing["region_code"] == region_code:
            validate.bad("An ACTIVE standard already exists for this region_code.")

    row = db.db.insert(
        "standards",
        {
            "region_code": region_code,
            "min_seer2_standard": min_standard,
            "min_seer2_high": min_high,
            "min_seer2_premium": min_premium,
            "prohibits_flammable_refrigerant": prohibits,
            "effective_from_utc": effective_raw,
            "status": "ACTIVE",
            "_effective_from": effective,
        },
    )
    return derive.serialize_standard(row)


@bp.route("/plant/regional-standards", methods=["GET"])
@endpoint(READ_ALL + ("DistributorRep",), 200)
def list_standards():
    rows = db.db.rows("standards")
    rows = eq_filter(rows, "region_code", web.filter_value("region_code"))
    rows = eq_filter(rows, "status", web.filter_value("status"))
    prohibits = web.filter_bool("prohibits_flammable_refrigerant")
    if prohibits is not None:
        rows = [r for r in rows if r["prohibits_flammable_refrigerant"] == prohibits]
    return listing(rows, derive.serialize_standard)


@bp.route("/plant/regional-standards/<row_id>", methods=["GET"])
@endpoint(READ_ALL + ("DistributorRep",), 200)
def read_standard(row_id):
    return derive.serialize_standard(find.standard(row_id))


# -------------------------------------------------------- product platforms
PLATFORM_READ_ROLES = READ_ALL + ("WarrantyAnalyst", "DistributorRep")
PLATFORM_DETAIL_ROLES = READ_ALL + (
    "QualityTechnician",
    "ProductionTechnician",
    "WarrantyAnalyst",
    "DistributorRep",
)


@bp.route("/plant/product-platforms", methods=["POST"])
@endpoint(["DesignEngineer"], 201)
def create_platform():
    payload = web.body()
    model_code = validate.str_field(payload, "model_code", max_len=32)
    efficiency_tier = validate.enum_field(
        payload, "efficiency_tier", ("STANDARD", "HIGH", "PREMIUM")
    )
    program_id = validate.str_field(payload, "refrigerant_program_id")
    rated_capacity = validate.int_field(payload, "rated_capacity_btuh", minimum=6000)
    rated_eer = validate.num_field(payload, "rated_eer", places=2, gt=0)
    rated_seer2 = validate.num_field(payload, "rated_seer2", places=2, gt=0)
    compressor_part = validate.str_field(payload, "compressor_part_number")
    board_part = validate.str_field(payload, "control_board_part_number")
    max_charge = validate.int_field(
        payload, "max_charge_grams", required=False, minimum=0, default=None
    )
    supersedes_id = validate.str_field(
        payload, "supersedes_platform_id", required=False, default=None
    )

    program = find.program(program_id)
    if supersedes_id is not None:
        find.platform(supersedes_id)
    for existing in db.db.rows("platforms"):
        if existing["model_code"] == model_code:
            validate.bad("model_code already exists.")
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_STATE_INVALID", "The refrigerant program is not ACTIVE.")

    row = db.db.insert(
        "platforms",
        {
            "model_code": model_code,
            "efficiency_tier": efficiency_tier,
            "refrigerant_program_id": program_id,
            "supersedes_platform_id": supersedes_id,
            "rated_capacity_btuh": rated_capacity,
            "rated_eer": rated_eer,
            "rated_seer2": rated_seer2,
            "compressor_part_number": compressor_part,
            "control_board_part_number": board_part,
            "max_charge_grams": max_charge,
            "status": "DRAFT",
            "revision_round": 0,
            "submitted_by_user_id": None,
            "released_at": None,
            "last_revision_notes": None,
        },
    )
    # the naming program's affected_platform_count is recomputed in the same write
    db.db.touch(program)
    return derive.serialize_platform(row)


@bp.route("/plant/product-platforms", methods=["GET"])
@endpoint(PLATFORM_READ_ROLES, 200)
def list_platforms():
    rows = db.db.rows("platforms")
    rows = eq_filter(rows, "refrigerant_program_id", web.filter_value("refrigerant_program_id"))
    rows = eq_filter(rows, "supersedes_platform_id", web.filter_value("supersedes_platform_id"))
    rows = eq_filter(rows, "efficiency_tier", web.filter_value("efficiency_tier"))
    rows = eq_filter(rows, "status", web.filter_value("status"))
    posture = web.filter_value("warranty_posture")
    if posture is not None:
        rows = [r for r in rows if derive.warranty_posture(r) == posture]
    return listing(rows, derive.serialize_platform)


@bp.route("/plant/product-platforms/<row_id>", methods=["GET"])
@endpoint(PLATFORM_DETAIL_ROLES, 200)
def read_platform(row_id):
    return derive.serialize_platform(find.platform(row_id))


@bp.route("/plant/product-platforms/<row_id>", methods=["PATCH"])
@endpoint(["DesignEngineer"], 200)
def edit_platform(row_id):
    payload = web.body()
    rated_capacity = validate.int_field(
        payload, "rated_capacity_btuh", required=False, minimum=6000, default=None
    )
    rated_eer = validate.num_field(payload, "rated_eer", required=False, places=2, gt=0)
    rated_seer2 = validate.num_field(payload, "rated_seer2", required=False, places=2, gt=0)
    compressor_part = validate.str_field(
        payload, "compressor_part_number", required=False, default=None
    )
    board_part = validate.str_field(
        payload, "control_board_part_number", required=False, default=None
    )
    max_charge = validate.int_field(
        payload, "max_charge_grams", required=False, minimum=0, default=None
    )

    platform = find.platform(row_id)
    if platform["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PLATFORM_STATE", "Only a DRAFT platform may be edited.")

    if rated_capacity is not None:
        platform["rated_capacity_btuh"] = rated_capacity
    if rated_eer is not None:
        platform["rated_eer"] = rated_eer
    if rated_seer2 is not None:
        platform["rated_seer2"] = rated_seer2
    if compressor_part is not None:
        platform["compressor_part_number"] = compressor_part
    if board_part is not None:
        platform["control_board_part_number"] = board_part
    if max_charge is not None:
        platform["max_charge_grams"] = max_charge
    db.db.touch(platform)
    return derive.serialize_platform(platform)


@bp.route("/plant/product-platforms/<row_id>/submit-engineering-review", methods=["POST"])
@endpoint(["DesignEngineer"], 200)
def submit_platform(row_id):
    web.body()
    platform = find.platform(row_id)
    if platform["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PLATFORM_STATE", "Platform is not in DRAFT.")
    program = derive.platform_program(platform)
    if program is None or program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_STATE_INVALID", "The refrigerant program is not ACTIVE.")
    if program["flammability_class"] == "A2L":
        limit = platform["max_charge_grams"]
        if limit is None or limit < 1:
            raise ApiError(
                "ERR_A2L_SAFETY_LIMIT_UNSET",
                "An A2L platform must carry a max_charge_grams of at least 1.",
            )
    platform["status"] = "ENG_REVIEW"
    platform["revision_round"] = platform["revision_round"] + 1
    platform["submitted_by_user_id"] = web.actor()
    db.db.touch(platform)
    return derive.serialize_platform(platform)


@bp.route("/plant/product-platforms/<row_id>/return-to-draft", methods=["POST"])
@endpoint(["ReliabilityEngineer"], 200)
def return_platform_to_draft(row_id):
    payload = web.body()
    revision_notes = validate.str_field(payload, "revision_notes")
    platform = find.platform(row_id)
    if platform["status"] != "ENG_REVIEW":
        raise ApiError("ERR_INVALID_PLATFORM_STATE", "Platform is not in ENG_REVIEW.")
    if web.actor() == platform["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The submitter may not judge their own design."
        )
    platform["status"] = "DRAFT"
    platform["last_revision_notes"] = revision_notes
    db.db.touch(platform)
    return derive.serialize_platform(platform)


@bp.route("/plant/product-platforms/<row_id>/release", methods=["POST"])
@endpoint(["ReliabilityEngineer"], 200)
def release_platform(row_id):
    web.body()
    platform = find.platform(row_id)
    if platform["status"] != "ENG_REVIEW":
        raise ApiError("ERR_INVALID_PLATFORM_STATE", "Platform is not in ENG_REVIEW.")
    program = derive.platform_program(platform)
    if program is None or program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_STATE_INVALID", "The refrigerant program is not ACTIVE.")
    if web.actor() == platform["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The submitter may not release their own design."
        )
    platform["status"] = "RELEASED"
    platform["released_at"] = db.db.stamp()
    db.db.touch(platform)
    return derive.serialize_platform(platform)


@bp.route("/plant/product-platforms/<row_id>/retire", methods=["POST"])
@endpoint(["PlantAdmin"], 200)
def retire_platform(row_id):
    payload = web.body()
    validate.str_field(payload, "reason", required=False, default=None)
    platform = find.platform(row_id)
    if platform["status"] not in ("RELEASED", "RESTRICTED"):
        raise ApiError(
            "ERR_INVALID_PLATFORM_STATE",
            "Only a RELEASED or RESTRICTED platform may be retired.",
        )
    if cascade.platform_builds(platform, cascade.OPEN_BUILD_STATES):
        raise ApiError(
            "ERR_PLATFORM_HAS_OPEN_BUILDS", "The platform still has open build lots."
        )
    cascade.retire_platform(platform)
    return derive.serialize_platform(platform)


@bp.route("/plant/product-platforms/<row_id>/certification-records", methods=["GET"])
@endpoint(
    (
        "PlantAdmin",
        "DesignEngineer",
        "ReliabilityEngineer",
        "CertificationEngineer",
        "RegulatoryAuditor",
        "SupplyPlanner",
    ),
    200,
)
def list_platform_certs(row_id):
    platform = find.platform(row_id)
    rows = [c for c in db.db.rows("certs") if c["platform_id"] == platform["id"]]
    rows = eq_filter(rows, "region_code", web.filter_value("region_code"))
    rows = eq_filter(rows, "status", web.filter_value("status"))
    rows = sorted(rows, key=lambda r: r["_seq"], reverse=True)
    return listing(rows, derive.serialize_cert)


@bp.route("/plant/product-platforms/<row_id>/warranty-claims", methods=["GET"])
@endpoint(("PlantAdmin", "ReliabilityEngineer", "WarrantyAnalyst", "DesignEngineer"), 200)
def list_platform_claims(row_id):
    platform = find.platform(row_id)
    rows = [c for c in db.db.rows("claims") if c["platform_id"] == platform["id"]]
    rows = eq_filter(rows, "status", web.filter_value("status"))
    rows = eq_filter(rows, "component_type", web.filter_value("component_type"))
    rows = eq_filter(rows, "supplier_lot_code", web.filter_value("supplier_lot_code"))
    return listing(rows, derive.serialize_claim)


@bp.route("/plant/product-platforms/<row_id>/warranty-analysis", methods=["GET"])
@endpoint(("PlantAdmin", "ReliabilityEngineer", "WarrantyAnalyst", "DesignEngineer"), 200)
def platform_warranty_analysis(row_id):
    platform = find.platform(row_id)
    basis = enum_arg("basis", ("BUILT_BASIS", "SHIPPED_BASIS"), "BUILT_BASIS")
    rate, counted, denominator = derive.claim_rate(platform, basis)
    return {
        "platform_id": platform["id"],
        "basis": basis,
        "counted_claim_count": counted,
        "denominator_units": denominator,
        "rolling_claim_rate_pct": rate,
        "warranty_posture": derive.warranty_posture(platform),
    }


# ---------------------------------------------------- certification records
CERT_READ_ROLES = (
    "PlantAdmin",
    "CertificationEngineer",
    "RegulatoryAuditor",
    "DesignEngineer",
    "ReliabilityEngineer",
    "SupplyPlanner",
)


@bp.route("/plant/certification-records", methods=["POST"])
@endpoint(["CertificationEngineer"], 201)
def create_cert():
    payload = web.body()
    platform_id = validate.str_field(payload, "platform_id")
    region_code = validate.str_field(payload, "region_code", max_len=32)
    submitted_rating = validate.num_field(payload, "rated_seer2_submitted", places=2, gt=0)
    expected_version = validate.int_field(payload, "expected_platform_version")

    platform = find.platform(platform_id)
    for existing in db.db.rows("certs"):
        if (
            existing["platform_id"] == platform_id
            and existing["region_code"] == region_code
            and existing["status"] == "CERTIFIED"
        ):
            raise ApiError(
                "ERR_DUPLICATE_CERTIFICATION",
                "A CERTIFIED record already exists for this platform and region.",
            )
    if expected_version != platform["version"]:
        raise ApiError(
            "ERR_STALE_PLATFORM_VERSION",
            "expected_platform_version does not match the stored platform version.",
        )
    if platform["status"] not in ("RELEASED", "RESTRICTED"):
        raise ApiError(
            "ERR_INVALID_PLATFORM_STATE",
            "Only a RELEASED or RESTRICTED platform may be filed against.",
        )

    row = db.db.insert(
        "certs",
        {
            "platform_id": platform_id,
            "region_code": region_code,
            "rated_seer2_submitted": submitted_rating,
            "status": "DRAFT",
            "governing_standard_id": None,
            "submitted_by_user_id": None,
            "submitted_at": None,
            "decided_by_user_id": None,
            "decided_at": None,
            "rejection_reason": None,
            "withdrawn_at": None,
        },
    )
    superseded = [
        c
        for c in db.db.rows("certs")
        if c["id"] != row["id"]
        and c["platform_id"] == platform_id
        and c["region_code"] == region_code
        and c["status"] in ("DRAFT", "SUBMITTED", "REJECTED")
    ]
    for cert in cascade.asc(superseded):
        cert["status"] = "SUPERSEDED"
        db.db.touch(cert)
    db.db.touch(platform)
    return derive.serialize_cert(row)


@bp.route("/plant/certification-records", methods=["GET"])
@endpoint(CERT_READ_ROLES, 200)
def list_certs():
    rows = db.db.rows("certs")
    rows = eq_filter(rows, "platform_id", web.filter_value("platform_id"))
    rows = eq_filter(rows, "region_code", web.filter_value("region_code"))
    rows = eq_filter(rows, "status", web.filter_value("status"))
    rows = eq_filter(rows, "governing_standard_id", web.filter_value("governing_standard_id"))
    return listing(rows, derive.serialize_cert)


@bp.route("/plant/certification-records/<row_id>", methods=["GET"])
@endpoint(CERT_READ_ROLES, 200)
def read_cert(row_id):
    return derive.serialize_cert(find.cert(row_id))


@bp.route("/plant/certification-records/<row_id>/submit", methods=["POST"])
@endpoint(["CertificationEngineer"], 200)
def submit_cert(row_id):
    web.body()
    cert = find.cert(row_id)
    if cert["status"] != "DRAFT":
        raise ApiError("ERR_CERTIFICATION_STATE_INVALID", "Record is not in DRAFT.")
    platform = find.platform(cert["platform_id"])
    if platform["status"] != "RELEASED":
        raise ApiError(
            "ERR_INVALID_PLATFORM_STATE", "Only a RELEASED platform may submit a filing."
        )
    candidates = [
        s
        for s in db.db.rows("standards")
        if s["status"] == "ACTIVE" and s["region_code"] == cert["region_code"]
    ]
    if not candidates:
        raise ApiError(
            "ERR_REGIONAL_STANDARD_NOT_FOUND",
            "No ACTIVE regional standard governs this region_code.",
        )
    standard = candidates[-1]
    minimum = derive.tier_minimum(standard, platform["efficiency_tier"])
    if dec(cert["rated_seer2_submitted"]) < dec(minimum):
        raise ApiError(
            "ERR_EFFICIENCY_BELOW_REGIONAL_MINIMUM",
            "rated_seer2_submitted is below the regional minimum for this tier.",
        )
    cert["status"] = "SUBMITTED"
    cert["submitted_by_user_id"] = web.actor()
    cert["submitted_at"] = db.db.stamp()
    cert["governing_standard_id"] = standard["id"]
    db.db.touch(cert)
    return derive.serialize_cert(cert)


@bp.route("/plant/certification-records/<row_id>/decide", methods=["POST"])
@endpoint(["RegulatoryAuditor"], 200)
def decide_cert(row_id):
    payload = web.body()
    decision = validate.enum_field(payload, "decision", ("CERTIFIED", "REJECTED"))
    cert = find.cert(row_id)
    if cert["status"] != "SUBMITTED":
        raise ApiError("ERR_CERTIFICATION_STATE_INVALID", "Record is not SUBMITTED.")
    if web.actor() == cert["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The submitter may not decide their own filing."
        )
    platform = find.platform(cert["platform_id"])

    if decision == "CERTIFIED":
        standard = db.db.get("standards", cert["governing_standard_id"])
        program = derive.platform_program(platform)
        if (
            standard is not None
            and standard["prohibits_flammable_refrigerant"]
            and program is not None
            and program["flammability_class"] == "A2L"
        ):
            raise ApiError(
                "ERR_FLAMMABLE_REFRIGERANT_PROHIBITED",
                "This region prohibits flammable refrigerant.",
            )
        cert["status"] = "CERTIFIED"
    else:
        rejection_reason = validate.str_field(payload, "rejection_reason")
        cert["status"] = "REJECTED"
        cert["rejection_reason"] = rejection_reason

    cert["decided_by_user_id"] = web.actor()
    cert["decided_at"] = db.db.stamp()
    db.db.touch(cert)
    db.db.touch(platform)
    return derive.serialize_cert(cert)
