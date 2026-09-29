"""Catastrophe events, the reinsurance tower, claims and the post-event
assessment (PRD 3.7 and 3.8)."""

import calc
import envelope
import guards
import store
from errors import ApiError
from flask import Blueprint

bp = Blueprint("catastrophe", __name__)

COUNTY_CODE_LENGTH = 5
CLAIM_OPEN_STATUSES = ("FNOL_RECEIVED", "PROVISIONAL_ADJUSTED", "FINAL_ADJUSTED")
CLAIM_INTAKE_EVENT_STATUSES = ("DECLARED", "LOSS_AGGREGATION", "CAPACITY_EXHAUSTED")
EVENT_CLOSEABLE_STATUSES = ("MONITORING", "LOSS_AGGREGATION", "ASSESSMENT_LEVIED")


# --- catastrophe events ---------------------------------------------------

@bp.post("/catastrophe-events")
def create_event():
    guards.auth(("ProgramAdmin",))
    body = guards.body()
    guards.required(body, ("event_code", "magnitude", "epicenter_county_code",
                           "occurred_at", "retention_cents"))
    event_code = guards.required_string(body, "event_code")
    county = guards.required_string(body, "epicenter_county_code")
    if len(county) != COUNTY_CODE_LENGTH:
        raise ApiError("ERR_INVALID_REQUEST")
    guards.decimal_field(body, "magnitude", minimum="4.0", maximum="9.5", max_places=1)
    retention = guards.integer(body, "retention_cents", minimum=0)
    occurred = guards.instant(body, "occurred_at")
    guards.unique_violation("events", "event_code", event_code)
    if occurred > store.clock_now():
        raise ApiError("ERR_INVALID_REQUEST")
    row = store.insert("events", {
        "event_code": event_code,
        "magnitude": body["magnitude"],
        "epicenter_county_code": county,
        "occurred_at": store.iso(occurred),
        "treaty_year": occurred.year,
        "retention_cents": retention,
        "status": "MONITORING",
        "aggregate_incurred_cents": 0,
        "retained_cents": 0,
        "ceded_total_cents": 0,
        "uncovered_cents": 0,
        "assessment_shortfall_cents": 0,
        "admin_loading_cents": 0,
        "assessment_total_cents": 0,
        "claim_count": 0,
    })
    return envelope.created(store.public(row))


@bp.post("/catastrophe-events/<row_id>/declare")
def declare_event(row_id):
    guards.auth(("ProgramAdmin",))
    event = guards.path_row("events", row_id)
    if event["status"] != "MONITORING":
        raise ApiError("ERR_EVENT_INVALID_STATE")
    if store.dec(event["magnitude"]) < calc.DECLARATION_MIN_MAGNITUDE:
        raise ApiError("ERR_MAGNITUDE_BELOW_DECLARATION_FLOOR")
    if not calc.has_active_layer(event["treaty_year"]):
        raise ApiError("ERR_NO_REINSURANCE_PROGRAM")
    event["status"] = "DECLARED"
    store.touch(event)
    return envelope.object_response(store.public(event))


@bp.post("/catastrophe-events/<row_id>/levy-assessment")
def levy_assessment(row_id):
    guards.auth(("ProgramAdmin",))
    event = guards.path_row("events", row_id)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_EVENT_CLOSED")
    if event["status"] == "ASSESSMENT_LEVIED":
        raise ApiError("ERR_EVENT_ASSESSMENT_LOCKED")
    if event["status"] != "CAPACITY_EXHAUSTED":
        raise ApiError("ERR_EVENT_CAPACITY_NOT_EXHAUSTED")
    calc.levy_assessment(event)
    event["status"] = "ASSESSMENT_LEVIED"
    store.touch(event)
    return envelope.object_response(store.public(event))


@bp.post("/catastrophe-events/<row_id>/close")
def close_event(row_id):
    guards.auth(("ProgramAdmin",))
    event = guards.path_row("events", row_id)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_EVENT_CLOSED")
    if event["status"] not in EVENT_CLOSEABLE_STATUSES:
        raise ApiError("ERR_EVENT_INVALID_STATE")
    for claim in store.DB["claims"].values():
        if claim["event_id"] == event["id"] and claim["adjustment_status"] in CLAIM_OPEN_STATUSES:
            raise ApiError("ERR_EVENT_HAS_OPEN_CLAIMS")
    event["status"] = "CLOSED"
    store.touch(event)
    return envelope.object_response(store.public(event))


@bp.get("/catastrophe-events/<row_id>")
def read_event(row_id):
    guards.auth(("ProgramAdmin", "ClaimAdjuster", "ParticipatingInsurer"))
    event = guards.path_row("events", row_id)
    return envelope.object_response(store.public(event))


@bp.get("/catastrophe-events")
def list_events():
    guards.auth(("ProgramAdmin", "ClaimAdjuster", "ParticipatingInsurer"))
    rows = guards.filtered(store.all_rows("events"),
                           (("status", "status"),
                            ("treaty_year", "treaty_year"),
                            ("epicenter_county_code", "epicenter_county_code")))
    return envelope.list_response(rows)


# --- the reinsurance tower ------------------------------------------------

@bp.post("/reinsurance-layers")
def create_layer():
    guards.auth(("ProgramAdmin",))
    body = guards.body()
    guards.required(body, ("treaty_year", "layer_index", "attachment_point_cents",
                           "limit_cents", "ceded_pct"))
    treaty_year = guards.integer(body, "treaty_year", minimum=0)
    layer_index = guards.integer(body, "layer_index", minimum=1)
    attachment = guards.integer(body, "attachment_point_cents", minimum=0)
    limit = guards.integer(body, "limit_cents", exclusive_min=0)
    guards.decimal_field(body, "ceded_pct", exclusive_min=0, maximum=1, max_places=2)
    for other in store.DB["layers"].values():
        if other["treaty_year"] == treaty_year and other["layer_index"] == layer_index:
            raise ApiError("ERR_DUPLICATE_LAYER_INDEX")
    if layer_index > 1:
        below = None
        for other in store.DB["layers"].values():
            if other["treaty_year"] == treaty_year and other["layer_index"] == layer_index - 1:
                below = other
                break
        if below is not None:
            floor = below["attachment_point_cents"] + below["limit_cents"]
            if attachment < floor:
                raise ApiError("ERR_LAYER_ATTACHMENT_GAP")
    row = store.insert("layers", {
        "treaty_year": treaty_year,
        "layer_index": layer_index,
        "attachment_point_cents": attachment,
        "limit_cents": limit,
        "ceded_pct": body["ceded_pct"],
        "status": "ACTIVE",
        "ceded_cents": 0,
    })
    return envelope.created(store.public(row))


@bp.post("/reinsurance-layers/<row_id>/status")
def set_layer_status(row_id):
    guards.auth(("ProgramAdmin",))
    layer = guards.path_row("layers", row_id)
    body = guards.body()
    guards.required(body, ("status",))
    target = guards.enum(body, "status", "layer_status")
    layer["status"] = target
    store.touch(layer)
    return envelope.object_response(store.public(layer))


@bp.get("/reinsurance-layers/<row_id>")
def read_layer(row_id):
    guards.auth(("ProgramAdmin", "ParticipatingInsurer"))
    layer = guards.path_row("layers", row_id)
    return envelope.object_response(store.public(layer))


@bp.get("/reinsurance-layers")
def list_layers():
    guards.auth(("ProgramAdmin", "ParticipatingInsurer"))
    rows = guards.filtered(store.all_rows("layers"),
                           (("treaty_year", "treaty_year"), ("status", "status")))
    return envelope.list_response(rows)


# --- claims ---------------------------------------------------------------

def _policy_of(claim):
    return store.DB["policies"][claim["policy_id"]]


def _event_of(claim):
    return store.DB["events"][claim["event_id"]]


def _scope_claim(role, claim):
    """Ownership for the two entity-backed roles that may read claims."""
    policy = _policy_of(claim)
    if role == "Policyholder":
        guards.owner_must_be(policy["policyholder_id"])
    elif role == "ParticipatingInsurer":
        guards.owner_must_be(policy["insurer_id"])


@bp.post("/claims")
def file_claim():
    role = guards.auth(("ClaimAdjuster", "ProgramAdmin", "Policyholder"))
    body = guards.body()
    fks = guards.body_fks(body, ("policy_id", "event_id"))
    policy = fks.get("policy_id")
    if role == "Policyholder" and policy is not None:
        guards.owner_must_be(policy["policyholder_id"])
    guards.required(body, ("policy_id", "event_id", "structural_damage_cents",
                           "cosmetic_damage_cents", "contents_damage_cents",
                           "loss_of_use_cents", "expected_event_version"))
    structural = guards.integer(body, "structural_damage_cents", minimum=0)
    cosmetic = guards.integer(body, "cosmetic_damage_cents", minimum=0)
    contents = guards.integer(body, "contents_damage_cents", minimum=0)
    loss_of_use = guards.integer(body, "loss_of_use_cents", minimum=0)
    event = fks["event_id"]
    guards.occ(body, "expected_event_version", event["version"],
               "ERR_STALE_EVENT_VERSION")
    if policy["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")
    if event["status"] == "CLOSED":
        raise ApiError("ERR_EVENT_CLOSED")
    if event["status"] == "ASSESSMENT_LEVIED":
        raise ApiError("ERR_EVENT_ASSESSMENT_LOCKED")
    if event["status"] not in CLAIM_INTAKE_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_NOT_DECLARED")
    if not calc.has_active_layer(event["treaty_year"]):
        raise ApiError("ERR_NO_REINSURANCE_PROGRAM")
    for other in store.DB["claims"].values():
        if (other["policy_id"] == policy["id"] and other["event_id"] == event["id"]
                and other["adjustment_status"] != "DENIED"):
            raise ApiError("ERR_DUPLICATE_CLAIM")
    occurred = store.dt_of(event, "occurred_at")
    if not (store.dt_of(policy, "effective_at") <= occurred
            < store.dt_of(policy, "expires_at")):
        raise ApiError("ERR_POLICY_NOT_IN_FORCE_AT_EVENT")
    row = store.insert("claims", {
        "policy_id": policy["id"],
        "event_id": event["id"],
        "structural_damage_cents": structural,
        "cosmetic_damage_cents": cosmetic,
        "contents_damage_cents": contents,
        "loss_of_use_cents": loss_of_use,
        "deductible_applied_cents": 0,
        "dwelling_part_cents": 0,
        "contents_part_cents": 0,
        "loss_of_use_part_cents": 0,
        "provisional_payable_cents": 0,
        "final_payable_cents": 0,
        "payable_cents": 0,
        "paid_cents": 0,
        "adjustment_status": "FNOL_RECEIVED",
        "payment_status": "UNPAID",
        "provisional_adjuster_user_id": None,
        "final_adjuster_user_id": None,
        "reopen_count": 0,
        "denial_reason": "",
    })
    event["claim_count"] += 1
    store.touch(event)
    return envelope.created(store.public(row))


@bp.post("/claims/<row_id>/adjust-provisional")
def adjust_provisional(row_id):
    guards.auth(("ClaimAdjuster",), need_user_id=True)
    claim = guards.path_row("claims", row_id)
    if claim["adjustment_status"] != "FNOL_RECEIVED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    event = _event_of(claim)
    if event["status"] not in CLAIM_INTAKE_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_NOT_DECLARED")
    claim.update(calc.settle_provisional(claim, _policy_of(claim)))
    claim["provisional_adjuster_user_id"] = guards.acting_id()
    claim["adjustment_status"] = "PROVISIONAL_ADJUSTED"
    store.touch(claim)
    return envelope.object_response(store.public(claim))


@bp.post("/claims/<row_id>/finalize-adjustment")
def finalize_adjustment(row_id):
    guards.auth(("ClaimAdjuster",), need_user_id=True)
    claim = guards.path_row("claims", row_id)
    guards.sod(claim["provisional_adjuster_user_id"], "ERR_SOD_ADJUSTER_CONFLICT")
    event = _event_of(claim)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_EVENT_CLOSED")
    if event["status"] == "ASSESSMENT_LEVIED":
        raise ApiError("ERR_EVENT_ASSESSMENT_LOCKED")
    if claim["adjustment_status"] != "PROVISIONAL_ADJUSTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    # hop 1: the settlement rewrite
    claim.update(calc.settle_final(claim, _policy_of(claim)))
    claim["final_adjuster_user_id"] = guards.acting_id()
    claim["adjustment_status"] = "FINAL_ADJUSTED"
    store.touch(claim)
    # hop 2: the event's loss aggregate
    event["aggregate_incurred_cents"] += claim["final_payable_cents"]
    if event["status"] == "DECLARED":
        event["status"] = "LOSS_AGGREGATION"
    # hop 3: the waterfall re-runs over the new gross
    uncovered = calc.run_loss_waterfall(event)
    # hop 4: capacity exhaustion
    if uncovered > 0 and event["status"] == "LOSS_AGGREGATION":
        event["status"] = "CAPACITY_EXHAUSTED"
    store.touch(event)
    return envelope.object_response(store.public(claim))


@bp.post("/claims/<row_id>/reopen")
def reopen_claim(row_id):
    guards.auth(("ClaimAdjuster",))
    claim = guards.path_row("claims", row_id)
    guards.body()
    event = _event_of(claim)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_EVENT_CLOSED")
    if event["status"] == "ASSESSMENT_LEVIED":
        raise ApiError("ERR_EVENT_ASSESSMENT_LOCKED")
    if claim["adjustment_status"] != "FINAL_ADJUSTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    if claim["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
        raise ApiError("ERR_CLAIM_ALREADY_SETTLED")
    if claim["reopen_count"] >= calc.MAX_REOPENS:
        raise ApiError("ERR_CLAIM_REOPEN_LIMIT")
    # compensation hop 1: unwind this claim's contribution to the gross
    event["aggregate_incurred_cents"] -= claim["final_payable_cents"]
    # compensation hop 2: the waterfall re-runs over the reduced gross
    uncovered = calc.run_loss_waterfall(event)
    # compensation hop 3: the one cycle in the event machine
    if uncovered == 0 and event["status"] == "CAPACITY_EXHAUSTED":
        event["status"] = "LOSS_AGGREGATION"
    store.touch(event)
    claim["final_payable_cents"] = 0
    claim["payable_cents"] = claim["provisional_payable_cents"]
    claim["final_adjuster_user_id"] = None
    claim["reopen_count"] += 1
    claim["adjustment_status"] = "PROVISIONAL_ADJUSTED"
    store.touch(claim)
    return envelope.object_response(store.public(claim))


@bp.post("/claims/<row_id>/record-payment")
def record_payment(row_id):
    guards.auth(("ProgramAdmin",))
    claim = guards.path_row("claims", row_id)
    body = guards.body()
    guards.required(body, ("amount_cents",))
    amount = guards.integer(body, "amount_cents", exclusive_min=0)
    if claim["adjustment_status"] not in ("PROVISIONAL_ADJUSTED", "FINAL_ADJUSTED"):
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    if claim["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
        raise ApiError("ERR_CLAIM_ALREADY_SETTLED")
    if claim["paid_cents"] + amount > claim["payable_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_PAYABLE")
    claim["paid_cents"] += amount
    claim["payment_status"] = ("PAID" if claim["paid_cents"] == claim["payable_cents"]
                               else "PARTIALLY_PAID")
    store.touch(claim)
    return envelope.object_response(store.public(claim))


@bp.post("/claims/<row_id>/deny")
def deny_claim(row_id):
    guards.auth(("ClaimAdjuster",))
    claim = guards.path_row("claims", row_id)
    body = guards.body()
    guards.required(body, ("denial_reason",))
    reason = guards.required_string(body, "denial_reason")
    if claim["adjustment_status"] != "FNOL_RECEIVED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    claim["payable_cents"] = 0
    claim["provisional_payable_cents"] = 0
    claim["denial_reason"] = reason
    claim["adjustment_status"] = "DENIED"
    if claim["payment_status"] == "UNPAID":
        claim["payment_status"] = "WRITTEN_OFF"
    store.touch(claim)
    return envelope.object_response(store.public(claim))


@bp.post("/claims/<row_id>/close")
def close_claim(row_id):
    guards.auth(("ProgramAdmin",))
    claim = guards.path_row("claims", row_id)
    if claim["adjustment_status"] != "FINAL_ADJUSTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    if claim["payment_status"] != "PAID":
        raise ApiError("ERR_CLAIM_NOT_FULLY_PAID")
    claim["adjustment_status"] = "CLOSED"
    store.touch(claim)
    return envelope.object_response(store.public(claim))


@bp.get("/claims/<row_id>")
def read_claim(row_id):
    role = guards.auth(("ProgramAdmin", "ClaimAdjuster", "ParticipatingInsurer",
                        "Policyholder"))
    claim = guards.path_row("claims", row_id)
    _scope_claim(role, claim)
    return envelope.object_response(store.public(claim))


@bp.get("/claims")
def list_claims():
    role = guards.auth(("ProgramAdmin", "ClaimAdjuster", "ParticipatingInsurer",
                        "Policyholder"))
    rows = store.all_rows("claims")
    if role in ("Policyholder", "ParticipatingInsurer"):
        owner = guards.acting_id()
        field = "policyholder_id" if role == "Policyholder" else "insurer_id"
        rows = [row for row in rows if _policy_of(row)[field] == owner]
    rows = guards.filtered(rows, (("policy_id", "policy_id"),
                                  ("event_id", "event_id"),
                                  ("adjustment_status", "adjustment_status"),
                                  ("payment_status", "payment_status")))
    return envelope.list_response(rows)


# --- assessment allocations ----------------------------------------------

@bp.get("/assessment-allocations/<row_id>")
def read_allocation(row_id):
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer"))
    allocation = guards.path_row("allocations", row_id)
    if role == "ParticipatingInsurer":
        guards.owner_must_be(allocation["insurer_id"])
    return envelope.object_response(store.public(allocation))


@bp.get("/assessment-allocations")
def list_allocations():
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer"))
    rows = store.all_rows("allocations")
    if role == "ParticipatingInsurer":
        owner = guards.acting_id()
        rows = [row for row in rows if row["insurer_id"] == owner]
    rows = guards.filtered(rows, (("event_id", "event_id"),
                                  ("insurer_id", "insurer_id")))
    return envelope.list_response(rows)
