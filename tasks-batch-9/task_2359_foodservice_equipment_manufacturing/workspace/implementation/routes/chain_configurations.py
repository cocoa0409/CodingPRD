"""ChainConfiguration endpoints (PRD Sections 3.3, 3.5)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize, chain_scope
from response import ok, created, ok_list
from routes.helpers import find, maybe, filter_by, require_reason, unique_code
from services import calc, derive

bp = Blueprint("chain_configurations", __name__)

STATUSES = ("DRAFT", "ENG_REVIEW", "REVISION_REQUESTED", "ENG_APPROVED", "RELEASED",
            "COMPLIANCE_HOLD", "SUPERSEDED")
READ_ROLES = ("ApplicationEngineer", "EngineeringApprover", "ChannelManager", "ChainAdmin",
              "ProductionPlanner", "PlatformAdmin")
QUOTE_ROLES = ("ChannelManager", "ApplicationEngineer", "ChainAdmin", "PlatformAdmin")


def validations_of(config_id):
    return [v for v in ordered(db.performance_validations)
            if v["chain_configuration_id"] == config_id]


def _require_model_posture(model, require_listed):
    """Checks 25 then 26 (PRD Section 2.9)."""
    if model["certification_posture"] == "SUSPENDED":
        raise ApiError("ERR_MODEL_LISTING_SUSPENDED",
                       "the model's certification posture is SUSPENDED")
    if require_listed and model["certification_posture"] != "LISTED":
        raise ApiError("ERR_MODEL_NOT_LISTED",
                       "the model's certification posture is %s" % model["certification_posture"])


@bp.post("/chain-configurations")
def create_configuration():
    authorize("ApplicationEngineer", "PlatformAdmin")
    payload = validate.body()
    chain_account_id = validate.string_field(payload, "chain_account_id")
    equipment_model_id = validate.string_field(payload, "equipment_model_id")
    config_code = validate.string_field(payload, "config_code", min_len=1, max_len=32)
    option_codes = validate.enum_array_field(payload, "option_codes", calc.OPTION_CODES,
                                             allow_empty=True)
    controls_package = validate.enum_field(payload, "controls_package", calc.CONTROLS_PACKAGES)
    branding_kit = validate.enum_field(payload, "branding_kit", calc.BRANDING_KITS)
    expected_version = validate.int_field(payload, "expected_chain_account_version")

    model = find(db.equipment_models, equipment_model_id, "ERR_EQUIPMENT_MODEL_NOT_FOUND")
    account = find(db.chain_accounts, chain_account_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")

    if expected_version != account["version"]:
        raise ApiError("ERR_STALE_CHAIN_ACCOUNT_VERSION",
                       "expected_chain_account_version %s does not match %s"
                       % (expected_version, account["version"]))

    _require_model_posture(model, require_listed=False)

    if controls_package not in model["supported_controls_packages"]:
        raise ApiError("ERR_CONTROLS_PACKAGE_UNSUPPORTED",
                       "%s is not supported by this model" % controls_package)

    unique_code(db.chain_configurations, chain_account_id=chain_account_id,
                config_code=config_code)

    # supersede prior pre-review siblings for the same (account, model) pair
    for sibling in ordered(db.chain_configurations):
        if sibling["chain_account_id"] != chain_account_id:
            continue
        if sibling["equipment_model_id"] != equipment_model_id:
            continue
        if sibling["status"] not in ("DRAFT", "REVISION_REQUESTED"):
            continue
        sibling["status"] = "SUPERSEDED"
        touch(sibling)
        for validation in validations_of(sibling["id"]):
            if validation["status"] in ("IN_PROGRESS", "PASSED", "FAILED"):
                validation["status"] = "SUPERSEDED"
                touch(validation)

    indicative, _firm = calc.configuration_prices(
        model["base_price_cents"], option_codes, controls_package, branding_kit,
        account["contracted_unit_volume"])

    config = insert(db.chain_configurations, {
        "chain_account_id": chain_account_id,
        "equipment_model_id": equipment_model_id,
        "config_code": config_code,
        "option_codes": option_codes,
        "controls_package": controls_package,
        "branding_kit": branding_kit,
        "status": "DRAFT",
        "revision": 0,
        "revision_note": None,
        "branding_signed_off": False,
        "indicative_unit_price_cents": indicative,
        "firm_unit_price_cents": None,
        "pinned_model_version": None,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
    })

    touch(account)  # the create increments the parent account's version by one
    return created(config)


@bp.get("/chain-configurations")
def list_configurations():
    actor = authorize(*READ_ROLES)
    chain_account_id = validate.str_arg("chain_account_id")
    if chain_account_id is not None:
        chain_scope(actor, chain_account_id)
    limit, offset = validate.pagination()
    equipment_model_id = validate.str_arg("equipment_model_id")
    status = validate.enum_arg("status", STATUSES)

    items = ordered(db.chain_configurations)
    if actor.is_chain_admin:
        items = [c for c in items if c["chain_account_id"] == actor.user_id]
    items = filter_by(items, "chain_account_id", chain_account_id)
    items = filter_by(items, "equipment_model_id", equipment_model_id)
    items = filter_by(items, "status", status)
    return ok_list(items, limit, offset)


@bp.get("/chain-configurations/<config_id>")
def get_configuration(config_id):
    actor = authorize(*READ_ROLES)
    existing = maybe(db.chain_configurations, config_id)
    chain_scope(actor, existing["chain_account_id"] if existing else None)
    config = find(db.chain_configurations, config_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    return ok(config)


@bp.get("/chain-configurations/<config_id>/price-quote")
def price_quote(config_id):
    actor = authorize(*QUOTE_ROLES)
    existing = maybe(db.chain_configurations, config_id)
    chain_scope(actor, existing["chain_account_id"] if existing else None)
    config = find(db.chain_configurations, config_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    derive.refresh_indicative_price(config)
    return ok(config)


@bp.post("/chain-configurations/<config_id>/submissions")
def submit_configuration(config_id):
    actor = authorize("ApplicationEngineer", "PlatformAdmin")
    config = find(db.chain_configurations, config_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")

    if config["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_CONFIGURATION_STATE_INVALID",
                       "a %s configuration cannot be submitted" % config["status"])

    if not any(v["status"] == "PASSED" for v in validations_of(config["id"])):
        raise ApiError("ERR_PERFORMANCE_VALIDATION_NOT_PASSED",
                       "no performance validation child has passed")

    if config["status"] == "REVISION_REQUESTED":
        config["revision"] += 1
    config["status"] = "ENG_REVIEW"
    config["submitted_by_user_id"] = actor.user_id
    touch(config)
    return ok(config)


@bp.post("/chain-configurations/<config_id>/engineering-decisions")
def decide_configuration(config_id):
    actor = authorize("EngineeringApprover", "PlatformAdmin")
    payload = validate.body()
    decision = validate.enum_field(payload, "decision", ("APPROVE", "REQUEST_REVISION"))
    revision_note = None
    if decision == "REQUEST_REVISION":
        revision_note = require_reason(payload, "revision_note")

    config = find(db.chain_configurations, config_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")

    if config["submitted_by_user_id"] is not None \
            and actor.user_id == config["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the engineer who submitted the package may not decide it")

    if config["status"] != "ENG_REVIEW":
        raise ApiError("ERR_CONFIGURATION_STATE_INVALID",
                       "%s is not permitted from %s" % (decision, config["status"]))

    model = db.equipment_models[config["equipment_model_id"]]
    _require_model_posture(model, require_listed=(decision == "APPROVE"))

    if decision == "APPROVE":
        config["status"] = "ENG_APPROVED"
        config["pinned_model_version"] = model["version"]
        config["approved_by_user_id"] = actor.user_id
    else:
        config["status"] = "REVISION_REQUESTED"
        config["revision_note"] = revision_note
        config["branding_signed_off"] = False
    touch(config)
    return ok(config)


@bp.post("/chain-configurations/<config_id>/branding-signoff")
def branding_signoff(config_id):
    actor = authorize("ChainAdmin", "PlatformAdmin")
    existing = maybe(db.chain_configurations, config_id)
    chain_scope(actor, existing["chain_account_id"] if existing else None)

    payload = validate.body()
    validate.string_field(payload, "approved_artwork_ref", min_len=1)

    config = find(db.chain_configurations, config_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    if config["status"] not in ("DRAFT", "ENG_REVIEW", "ENG_APPROVED"):
        raise ApiError("ERR_CONFIGURATION_STATE_INVALID",
                       "branding cannot be signed off from %s" % config["status"])

    config["branding_signed_off"] = True
    touch(config)
    return ok(config)


@bp.post("/chain-configurations/<config_id>/release")
def release_configuration(config_id):
    authorize("ApplicationEngineer", "PlatformAdmin")
    config = find(db.chain_configurations, config_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")

    if config["status"] != "ENG_APPROVED":
        raise ApiError("ERR_CONFIGURATION_STATE_INVALID",
                       "a %s configuration cannot be released" % config["status"])
    if not config["branding_signed_off"]:
        raise ApiError("ERR_CONFIGURATION_STATE_INVALID", "branding has not been signed off")

    model = db.equipment_models[config["equipment_model_id"]]
    _require_model_posture(model, require_listed=True)

    if config["pinned_model_version"] != model["version"]:
        raise ApiError("ERR_MODEL_VERSION_PIN_STALE",
                       "pinned_model_version %s no longer matches %s"
                       % (config["pinned_model_version"], model["version"]))

    _indicative, firm = derive.configuration_price_pair(config)
    config["status"] = "RELEASED"
    config["firm_unit_price_cents"] = firm
    touch(config)
    return ok(config)
