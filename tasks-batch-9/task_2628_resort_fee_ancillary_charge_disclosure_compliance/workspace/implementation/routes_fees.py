"""Fee programs, fees, inclusion analysis, review and attestation (PRD 3.2)."""

from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import resolve
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("fees", __name__)

FEE_CODE_PATTERN = r"^[A-Z0-9_]+$"
CLASSIFICATIONS = ("MANDATORY", "OPTIONAL", "CONDITIONAL")
BASES = ("PER_NIGHT", "PER_STAY", "PER_PERSON_PER_NIGHT", "PERCENT_OF_ROOM")
PROGRAM_STATUSES = ("DRAFT", "UNDER_REVIEW", "PUBLISHED", "SUPERSEDED")


def _refresh_fee_counts(program):
    fees = store.fees_of_program(program["id"])
    program["fee_count"] = len(fees)
    program["mandatory_fee_count"] = sum(1 for f in fees if f["classification"] == "MANDATORY")


# --------------------------------------------------------------- fee programs

@bp.post("/fee-programs")
def create_fee_program():
    user_id, _role = auth.require([auth.REVENUE_MANAGER, auth.COMPLIANCE_OFFICER])
    payload = shape.body()

    # rank 7 — request shape
    property_id = shape.identifier(payload, "property_id")
    version_label = shape.string(payload, "version_label", min_len=1, max_len=32)
    effective_from = shape.timestamp(payload, "effective_from")
    effective_to = shape.timestamp(payload, "effective_to")
    expected_property_version = shape.integer(payload, "expected_property_version")
    supersedes_program_id = shape.identifier(payload, "supersedes_program_id", required=False)
    if effective_to <= effective_from:
        raise ApiError("ERR_INVALID_REQUEST", "effective_to must be after effective_from.")

    # rank 8 — body references, in the order the endpoint declares them
    prop = resolve.property_(property_id)
    if supersedes_program_id is not None:
        resolve.fee_program(supersedes_program_id)

    # rank 10 — optimistic concurrency on the property version
    if expected_property_version != prop["version"]:
        raise ApiError("ERR_STALE_PROPERTY_VERSION",
                       "expected_property_version does not match the property version.")

    # rank 16 — property operating status
    if prop["status"] != "ACTIVE":
        raise ApiError("ERR_PROPERTY_NOT_ACTIVE",
                       "A fee program cannot be opened against a SUSPENDED property.")

    for existing in store.programs_of_property(prop["id"]):
        if existing["version_label"] == version_label:
            raise ApiError("ERR_INVALID_REQUEST",
                           "version_label must be unique for the property.")

    row = {
        "property_id": prop["id"],
        "supersedes_program_id": supersedes_program_id,
        "version_label": version_label,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
        "authored_by_user_id": user_id,
        "attested_by_user_id": None,
        "attestation_note": None,
        "published_at": None,
        "fee_count": 0,
        "mandatory_fee_count": 0,
        "total_mandatory_fee_cents_per_night": 0,
        "inclusion_coverage_ratio": 0.0,
        "_coverage_num": 0,
    }
    store.stamp_new(row)
    store.fee_programs[row["id"]] = row

    store.touch(prop)  # a successful create increments Property.version by exactly 1
    return envelope.created(serialize.fee_program(row))


@bp.get("/fee-programs/<identifier>")
def read_fee_program(identifier):
    auth.require(auth.OPERATORS)
    return envelope.ok(serialize.fee_program(resolve.fee_program(identifier)))


@bp.get("/fee-programs")
def list_fee_programs():
    auth.require(auth.OPERATORS)
    rows = envelope.apply_filters(
        store.sort_default(store.fee_programs.values()),
        [("property_id", envelope.str_filter("property_id")),
         ("supersedes_program_id", envelope.str_filter("supersedes_program_id")),
         ("status", envelope.str_filter("status"))],
    )
    return envelope.page(rows, serialize.fee_program)


# ----------------------------------------------------------------------- fees

@bp.post("/fee-programs/<identifier>/fees")
def create_fee(identifier):
    auth.require([auth.REVENUE_MANAGER, auth.COMPLIANCE_OFFICER])
    program = resolve.fee_program(identifier)
    payload = shape.body()

    code = shape.string(payload, "code", min_len=1, max_len=32, pattern=FEE_CODE_PATTERN)
    label = shape.string(payload, "label", min_len=1, max_len=120)
    classification = shape.enum(payload, "classification", CLASSIFICATIONS)
    basis = shape.enum(payload, "basis", BASES)
    disclosure_text = shape.string(payload, "disclosure_text", min_len=8, max_len=500)
    avoidable = shape.boolean(payload, "avoidable", required=False, default=False)

    if basis == "PERCENT_OF_ROOM":
        if shape.present(payload, "amount_cents"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "amount_cents must be absent when basis is PERCENT_OF_ROOM.")
        percent_bps = shape.integer(payload, "percent_bps", minimum=1, maximum=10000)
        amount_cents = None
    else:
        if shape.present(payload, "percent_bps"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "percent_bps is only permitted when basis is PERCENT_OF_ROOM.")
        amount_cents = shape.integer(payload, "amount_cents", minimum=0)
        percent_bps = None

    if avoidable:
        opt_out_window_hours = shape.integer(payload, "opt_out_window_hours",
                                             minimum=0, maximum=720)
    else:
        if shape.present(payload, "opt_out_window_hours"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "opt_out_window_hours is only permitted when avoidable is true.")
        opt_out_window_hours = None

    # rank 12 — fees are appended to a DRAFT program
    if program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Fees may only be added to a DRAFT program.")

    # rank 26 — code unique within the program
    for existing in store.fees_of_program(program["id"]):
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_FEE_CODE",
                           "Fee code %s already exists on this program." % code)

    row = {
        "fee_program_id": program["id"],
        "code": code,
        "label": label,
        "classification": classification,
        "basis": basis,
        "amount_cents": amount_cents,
        "percent_bps": percent_bps,
        "avoidable": avoidable,
        "opt_out_window_hours": opt_out_window_hours,
        "disclosure_text": disclosure_text,
        "inclusion_count": 0,
        "inclusion_value_cents": 0,
    }
    store.stamp_new(row)
    store.fees[row["id"]] = row

    _refresh_fee_counts(program)
    store.touch(program)
    return envelope.created(serialize.fee(row))


@bp.get("/fees/<identifier>")
def read_fee(identifier):
    auth.require(auth.ALL_ROLES)
    return envelope.ok(serialize.fee(resolve.fee(identifier)))


@bp.get("/fees")
def list_fees():
    auth.require(auth.ALL_ROLES)
    rows = envelope.apply_filters(
        store.sort_default(store.fees.values()),
        [("fee_program_id", envelope.str_filter("fee_program_id")),
         ("classification", envelope.str_filter("classification")),
         ("basis", envelope.str_filter("basis")),
         ("avoidable", envelope.bool_filter("avoidable"))],
    )
    return envelope.page(rows, serialize.fee)


# ----------------------------------------------------------- fee inclusions

@bp.post("/fees/<identifier>/inclusions")
def create_inclusion(identifier):
    auth.require([auth.REVENUE_MANAGER, auth.COMPLIANCE_OFFICER])
    fee = resolve.fee(identifier)
    payload = shape.body()

    service_code = shape.string(payload, "service_code", min_len=1, max_len=32)
    service_label = shape.string(payload, "service_label", min_len=1, max_len=120)
    retail_value_cents = shape.integer(payload, "retail_value_cents", minimum=0)
    units = shape.integer(payload, "units", required=False, minimum=1, maximum=100)
    if units is None:
        units = 1

    program = store.fee_programs.get(fee["fee_program_id"])
    if program is not None and program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Inclusions may only be recorded on a fee of a DRAFT program.")

    for existing in store.inclusions_of_fee(fee["id"]):
        if existing["service_code"] == service_code:
            raise ApiError("ERR_DUPLICATE_INCLUSION_CODE",
                           "Inclusion code %s already exists on this fee." % service_code)

    row = {
        "fee_id": fee["id"],
        "service_code": service_code,
        "service_label": service_label,
        "retail_value_cents": retail_value_cents,
        "units": units,
        "included_value_cents": retail_value_cents * units,
    }
    store.stamp_new(row)
    store.fee_inclusions[row["id"]] = row

    inclusions = store.inclusions_of_fee(fee["id"])
    fee["inclusion_count"] = len(inclusions)
    fee["inclusion_value_cents"] = sum(i["included_value_cents"] for i in inclusions)
    store.touch(fee)
    return envelope.created(serialize.fee_inclusion(row))


@bp.get("/fees/<identifier>/inclusions")
def list_inclusions(identifier):
    auth.require(auth.ALL_ROLES)
    fee = resolve.fee(identifier)
    rows = store.sort_default(store.inclusions_of_fee(fee["id"]))
    return envelope.page(rows, serialize.fee_inclusion)


# ------------------------------------------------------- review and attestation

@bp.post("/fee-programs/<identifier>/submit-review")
def submit_review(identifier):
    auth.require([auth.REVENUE_MANAGER, auth.COMPLIANCE_OFFICER])
    program = resolve.fee_program(identifier)
    prop = store.properties.get(program["property_id"])

    if program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT program may be submitted for review.")
    if prop is None or prop["status"] != "ACTIVE":
        raise ApiError("ERR_PROPERTY_NOT_ACTIVE", "The property is not ACTIVE.")
    if not store.fees_of_program(program["id"]):
        raise ApiError("ERR_FEE_PROGRAM_EMPTY",
                       "A program must hold at least one fee before review.")

    program["status"] = "UNDER_REVIEW"
    _refresh_fee_counts(program)
    store.touch(program)
    return envelope.ok(serialize.fee_program(program))


def _intervals_collide(a_from, a_to, b_from, b_to):
    """Half-open [from, to). Touching endpoints do not collide (PRD 3.2)."""
    return a_from < b_to and b_from < a_to


@bp.post("/fee-programs/<identifier>/publish")
def publish_fee_program(identifier):
    user_id, _role = auth.require([auth.COMPLIANCE_OFFICER])
    program = resolve.fee_program(identifier)
    payload = shape.body()
    attestation_note = shape.string(payload, "attestation_note", min_len=None)

    # rank 9 — segregation of duties
    if user_id == program["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The attesting officer must differ from the author.")

    # rank 12 — state
    if program["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an UNDER_REVIEW program may be published.")

    # rank 14 — the superseded program must exist, match the property and be PUBLISHED
    predecessor = None
    if program["supersedes_program_id"] is not None:
        predecessor = resolve.fee_program(program["supersedes_program_id"])
        if predecessor["property_id"] != program["property_id"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "The superseded program belongs to another property.")
        if predecessor["status"] != "PUBLISHED":
            raise ApiError("ERR_FEE_PROGRAM_NOT_PUBLISHED",
                           "The superseded program is not PUBLISHED.")

    prop = store.properties.get(program["property_id"])
    jurisdiction = store.jurisdictions.get(prop["jurisdiction_id"]) if prop else None

    # rank 16 / 17 — property status and posture freeze
    if prop is None or prop["status"] != "ACTIVE":
        raise ApiError("ERR_PROPERTY_NOT_ACTIVE", "The property is not ACTIVE.")
    if prop["disclosure_posture"] == "NON_COMPLIANT":
        raise ApiError("ERR_PROPERTY_DISCLOSURE_FROZEN",
                       "The property's disclosure posture is NON_COMPLIANT.")

    mandatory = store.mandatory_fees_of_program(program["id"])

    # rank 19 — jurisdictional mandatory-fee ban
    if jurisdiction is not None and jurisdiction["mandatory_fee_ban"] and mandatory:
        raise ApiError("ERR_MANDATORY_FEE_BANNED_IN_JURISDICTION",
                       "The jurisdiction forbids mandatory fees.")

    # rank 22 — every mandatory fee must buy the guest something
    for fee in mandatory:
        if not calc.fee_has_value_bearing_inclusion(fee):
            raise ApiError("ERR_MANDATORY_FEE_WITHOUT_INCLUSION",
                           "Mandatory fee %s carries no value-bearing inclusion." % fee["code"])

    # rank 23 — taxability coverage for every mandatory fee
    for fee in mandatory:
        if store.taxability_rule(prop["jurisdiction_id"], fee["code"]) is None:
            raise ApiError("ERR_TAXABILITY_RULE_MISSING",
                           "No taxability rule for fee code %s." % fee["code"])

    # rank 27 — half-open interval overlap against other PUBLISHED programs
    for other in store.programs_of_property(prop["id"]):
        if other["id"] == program["id"] or other["status"] != "PUBLISHED":
            continue
        if predecessor is not None and other["id"] == predecessor["id"]:
            continue
        if _intervals_collide(program["effective_from"], program["effective_to"],
                              other["effective_from"], other["effective_to"]):
            raise ApiError("ERR_FEE_PROGRAM_PERIOD_OVERLAP",
                           "The effective interval overlaps another PUBLISHED program.")

    # rank 29 — effective_from may not be in the past
    if program["effective_from"] < clock.now():
        raise ApiError("ERR_EFFECTIVE_FROM_IN_PAST",
                       "effective_from is before the current logical clock.")

    # ---- side effects ----
    program["status"] = "PUBLISHED"
    program["attested_by_user_id"] = user_id
    program["attestation_note"] = attestation_note
    program["published_at"] = clock.now()
    _refresh_fee_counts(program)
    program["total_mandatory_fee_cents_per_night"] = \
        calc.total_mandatory_fee_cents_per_night(program, prop)
    coverage_num, coverage_ratio = calc.inclusion_coverage(program)
    program["_coverage_num"] = coverage_num
    program["inclusion_coverage_ratio"] = coverage_ratio

    # the supersession cascade — every link must fire
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        store.touch(predecessor)
        for profile in store.sort_created(
                [p for p in store.profiles.values()
                 if p["fee_program_id"] == predecessor["id"]]):
            if profile["status"] in ("DEPLOYED", "FLAGGED", "REMEDIATED"):
                derive.retire_profile(profile)

    derive.recompute_property(prop, force=True)
    store.touch(program)
    return envelope.ok(serialize.fee_program(program))
