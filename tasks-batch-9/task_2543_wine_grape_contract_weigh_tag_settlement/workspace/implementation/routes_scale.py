"""The scale house and the receipt lab: weigh tags and quality gradings."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import validation as v
from authz import (ACCOUNTS_PAYABLE_CLERK, GROWER, GROWER_RELATIONS_MANAGER,
                   HARVEST_COORDINATOR, QUALITY_LAB_TECH, SCALE_OPERATOR,
                   auth, own)
from common import (CLOCK, D, add_hours, add_minutes, by_created_asc, fail,
                    new_record, read_body, respond, respond_list, rows, touch)
from lookup import contract_writable, contract_in, find, not_suspended

bp = Blueprint("scale", __name__)

ZERO3 = Decimal("0.000")
MAX_LBS = 200000
DISPUTABLE = ("ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED_QUALITY")


# --------------------------------------------------------------------------
# The inbound gross pass
# --------------------------------------------------------------------------
@bp.post("/grower-relations/weigh-tags")
def create_weigh_tag():
    user_id, role = auth(SCALE_OPERATOR)
    body = read_body()

    appointment_id = v.req_id(body, "appointment_id")
    appointment = find("appointments", appointment_id)
    block_id = v.req_id(body, "block_id")
    block = find("blocks", block_id)

    gross = v.req_int(body, "gross_weight_lbs", minimum=1, maximum=MAX_LBS)
    expected_version = v.req_int(body, "expected_appointment_version")

    # rank 12 -- stale-version protection
    if expected_version != int(appointment["version"]):
        fail("ERR_STALE_APPOINTMENT_VERSION",
             "expected_appointment_version %d does not match the appointment's "
             "current version %d." % (expected_version, int(appointment["version"])))

    call = find("pick_calls", appointment["pick_call_id"])
    contract = find("contracts", call["contract_id"])

    # rank 20
    contract_writable(contract)
    # rank 22
    if appointment["status"] not in ("SCHEDULED", "ARRIVED"):
        fail("ERR_APPOINTMENT_NOT_OPEN",
             "The appointment is '%s' and is not open for receiving."
             % appointment["status"])
    # rank 31
    not_suspended(find("growers", contract["grower_id"]))
    # rank 36 -- the arrival envelope
    latest = add_minutes(appointment["window_end"], calc.LATE_ARRIVAL_GRACE_MINUTES)
    if CLOCK.now < appointment["window_start"] or not CLOCK.now < latest:
        fail("ERR_OUTSIDE_APPOINTMENT_WINDOW",
             "The truck presented outside the appointment's arrival envelope.")
    # rank 41
    if derive.allocation_for(contract["id"], block["id"]) is None:
        fail("ERR_BLOCK_NOT_ALLOCATED",
             "The block is not allocated to this contract.")

    row = new_record("weigh_tags", {
        "appointment_id": appointment["id"],
        "block_id": block["id"],
        "gross_weight_lbs": gross,
        "tare_weight_lbs": None,
        "net_weight_lbs": None,
        "net_tons": None,
        "weigh_status": "GROSS_CAPTURED",
        "disposition": "PENDING",
        "captured_by_user_id": user_id,
        "contract_slice_tons": ZERO3,
        "over_slice_tons": ZERO3,
        "over_rejected_tons": ZERO3,
        "excess_rejected_tons": ZERO3,
        "dispute_deadline_at": None,
    })

    if appointment["status"] == "SCHEDULED":
        appointment["status"] = "ARRIVED"
    touch(appointment)
    return respond(derive.tag_json(row), 201)


# --------------------------------------------------------------------------
# The outbound tare pass
# --------------------------------------------------------------------------
@bp.post("/grower-relations/weigh-tags/<tag_id>/tare")
def tare_weigh_tag(tag_id):
    auth(SCALE_OPERATOR)
    tag = find("weigh_tags", tag_id)
    body = read_body()
    tare = v.req_int(body, "tare_weight_lbs", minimum=0, maximum=MAX_LBS)

    contract = derive.contract_of_tag(tag)
    if contract is not None:
        contract_writable(contract)

    if tag["weigh_status"] != "GROSS_CAPTURED":
        fail("ERR_TAG_WEIGH_STATE_INVALID",
             "The weigh tag is '%s'; the tare pass is already complete."
             % tag["weigh_status"])
    if tare > int(tag["gross_weight_lbs"]):
        fail("ERR_TARE_EXCEEDS_GROSS",
             "tare_weight_lbs may not exceed gross_weight_lbs.")

    net_weight_lbs, net_tons = calc.net_weight_conversion(tag["gross_weight_lbs"], tare)
    tag["tare_weight_lbs"] = tare
    tag["net_weight_lbs"] = net_weight_lbs
    tag["net_tons"] = net_tons
    tag["weigh_status"] = "NET_FINAL"
    touch(tag)

    appointment = find("appointments", tag["appointment_id"])
    touch(appointment)
    return respond(derive.tag_json(tag))


# --------------------------------------------------------------------------
# Grading at receipt
# --------------------------------------------------------------------------
@bp.post("/grower-relations/weigh-tags/<tag_id>/grades")
def grade_weigh_tag(tag_id):
    user_id, role = auth(QUALITY_LAB_TECH)
    tag = find("weigh_tags", tag_id)

    # rank 4 -- segregation of duties outranks every state question here
    if user_id == tag["captured_by_user_id"]:
        fail("ERR_SOD_SAME_USER_GRADING",
             "The operator who captured this load may not grade it.")

    body = read_body()
    brix = v.req_num(body, "brix", 1, exclusive_min=0, maximum=40)
    ta_gl = v.req_num(body, "ta_gl", 1, exclusive_min=0, maximum=20)
    ph = v.req_num(body, "ph", 2, exclusive_min=0, maximum=5)
    rot_pct = v.req_num(body, "rot_pct", 1, minimum=0, maximum=100)
    mog_pct = v.req_num(body, "mog_pct", 1, minimum=0, maximum=100)
    expected_version = v.req_int(body, "expected_weigh_tag_version")

    # rank 13
    if expected_version != int(tag["version"]):
        fail("ERR_STALE_WEIGH_TAG_VERSION",
             "expected_weigh_tag_version %d does not match the weigh tag's current "
             "version %d." % (expected_version, int(tag["version"])))

    appointment = find("appointments", tag["appointment_id"])
    call = find("pick_calls", appointment["pick_call_id"])
    contract = find("contracts", call["contract_id"])

    # rank 20
    contract_writable(contract)
    # rank 24
    if tag["weigh_status"] != "NET_FINAL":
        fail("ERR_TAG_WEIGH_STATE_INVALID",
             "The load must reach NET_FINAL before it can be graded.")
    # rank 25
    if tag["disposition"] not in ("PENDING", "DISPUTED"):
        fail("ERR_TAG_NOT_DISPUTABLE",
             "The load's disposition is already decided as '%s'."
             % tag["disposition"])

    spec = find("specs", contract["quality_spec_id"])
    result = calc.quality_adjustment_pct(spec, brix, ta_gl, rot_pct, mog_pct)

    # a newer grading supersedes every earlier one
    for earlier in derive.grades_of_tag(tag["id"]):
        if earlier["superseded_at"] is None:
            earlier["superseded_at"] = CLOCK.now

    grade = new_record("grades", {
        "weigh_tag_id": tag["id"],
        "brix": brix,
        "ta_gl": ta_gl,
        "ph": ph,
        "rot_pct": rot_pct,
        "mog_pct": mog_pct,
        "graded_by_user_id": user_id,
        "brix_component_pct": result["brix_component_pct"],
        "acid_component_pct": result["acid_component_pct"],
        "rot_component_pct": result["rot_component_pct"],
        "mog_component_pct": result["mog_component_pct"],
        "raw_adjustment_pct": result["raw_adjustment_pct"],
        "adjustment_pct": result["adjustment_pct"],
        "recommended_disposition": result["recommended_disposition"],
        "superseded_at": None,
    })

    if result["recommended_disposition"] == "REJECT_QUALITY":
        tag["contract_slice_tons"] = ZERO3
        tag["over_slice_tons"] = ZERO3
        tag["over_rejected_tons"] = ZERO3
        tag["excess_rejected_tons"] = ZERO3
        tag["disposition"] = "REJECTED_QUALITY"
    else:
        if contract["cap_scope"] == "PER_BLOCK":
            allocation = derive.allocation_for(contract["id"], tag["block_id"])
            soft_cap = allocation["block_cap_tons"]
            hard_cap = allocation["block_hard_cap_tons"]
            consumed_soft = derive.allocation_bucket_tons(allocation, ("CONTRACT",))
            consumed_total = derive.allocation_bucket_tons(
                allocation, ("CONTRACT", "OVER_DELIVERY"))
        else:
            soft_cap = contract["contract_cap_tons"]
            hard_cap = contract["hard_cap_tons"]
            consumed_soft = derive.bucket_tons(contract["id"], "CONTRACT")
            consumed_total = consumed_soft + derive.bucket_tons(contract["id"],
                                                               "OVER_DELIVERY")
        slices = calc.tonnage_waterfall(tag["net_tons"], soft_cap, hard_cap,
                                        consumed_soft, consumed_total,
                                        contract["over_delivery_policy"])
        tag["contract_slice_tons"] = slices["contract_slice_tons"]
        tag["over_slice_tons"] = slices["over_slice_tons"]
        tag["over_rejected_tons"] = slices["over_rejected_tons"]
        tag["excess_rejected_tons"] = slices["excess_rejected_tons"]
        tag["disposition"] = slices["disposition"]

        for bucket, tons in (("CONTRACT", tag["contract_slice_tons"]),
                             ("OVER_DELIVERY", tag["over_slice_tons"])):
            if tons <= ZERO3:
                continue
            priced = calc.settlement_line_amount(contract, bucket, tons,
                                                 result["adjustment_pct"])
            new_record("lines", {
                "weigh_tag_id": tag["id"],
                "contract_id": contract["id"],
                "quality_grade_id": grade["id"],
                "bucket": bucket,
                "tons": tons,
                "adjustment_pct_applied": priced["adjustment_pct_applied"],
                "price_per_ton_cents": priced["price_per_ton_cents"],
                "gross_amount_cents": priced["gross_amount_cents"],
                "provisional_amount_cents": priced["provisional_amount_cents"],
                "final_amount_cents": None,
                "status": "PROVISIONAL",
                "voided_at": None,
            })

    if tag["dispute_deadline_at"] is None:
        tag["dispute_deadline_at"] = add_hours(CLOCK.now,
                                               calc.GRADE_DISPUTE_WINDOW_HOURS)
    touch(tag)
    cascades.grading_cascade(tag, contract)
    return respond(derive.grade_json(grade), 201)


# --------------------------------------------------------------------------
# Contesting a grading
# --------------------------------------------------------------------------
@bp.post("/grower-relations/weigh-tags/<tag_id>/grade-disputes")
def dispute_grading(tag_id):
    user_id, role = auth(GROWER)
    tag = find("weigh_tags", tag_id)
    appointment = find("appointments", tag["appointment_id"])
    call = find("pick_calls", appointment["pick_call_id"])
    contract = find("contracts", call["contract_id"])
    own(user_id, role, contract["grower_id"])

    body = read_body()
    v.free_text(body, "reason")

    # rank 20
    contract_in(contract, ("ACTIVE",))
    # rank 25
    if tag["disposition"] not in DISPUTABLE:
        fail("ERR_TAG_NOT_DISPUTABLE",
             "A load whose disposition is '%s' cannot be contested."
             % tag["disposition"])
    # rank 39
    if tag["dispute_deadline_at"] is None or CLOCK.now > tag["dispute_deadline_at"]:
        fail("ERR_DISPUTE_WINDOW_CLOSED", "The dispute window has closed.")

    was_rejected = tag["disposition"] in derive.REJECTED_SET
    active = derive.active_grade(tag["id"])
    if active is not None:
        active["superseded_at"] = CLOCK.now

    cascades.dispute_cascade(tag, contract, was_rejected)
    return respond(derive.tag_json(tag))


# --------------------------------------------------------------------------
# Weigh tag reads
# --------------------------------------------------------------------------
@bp.get("/grower-relations/weigh-tags/<tag_id>")
def get_weigh_tag(tag_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR,
                         SCALE_OPERATOR, QUALITY_LAB_TECH, ACCOUNTS_PAYABLE_CLERK,
                         GROWER)
    tag = find("weigh_tags", tag_id)
    if role == GROWER:
        contract = derive.contract_of_tag(tag)
        own(user_id, role, contract["grower_id"] if contract else None)
    return respond(derive.tag_json(tag))


@bp.get("/grower-relations/weigh-tags")
def list_weigh_tags():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, SCALE_OPERATOR,
         QUALITY_LAB_TECH, ACCOUNTS_PAYABLE_CLERK)
    limit, offset = v.pagination()
    appointment_id = v.filt("appointment_id")
    block_id = v.filt("block_id")
    weigh_status = v.filt("weigh_status")
    disposition = v.filt("disposition")
    items = rows("weigh_tags")
    if appointment_id is not None:
        items = [r for r in items if r["appointment_id"] == appointment_id]
    if block_id is not None:
        items = [r for r in items if r["block_id"] == block_id]
    if weigh_status is not None:
        items = [r for r in items if r["weigh_status"] == weigh_status]
    if disposition is not None:
        items = [r for r in items if r["disposition"] == disposition]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.tag_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)


# --------------------------------------------------------------------------
# Grading reads
# --------------------------------------------------------------------------
@bp.get("/grower-relations/quality-grades/<grade_id>")
def get_grade(grade_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, QUALITY_LAB_TECH,
                         ACCOUNTS_PAYABLE_CLERK, GROWER)
    grade = find("grades", grade_id)
    if role == GROWER:
        tag = find("weigh_tags", grade["weigh_tag_id"])
        contract = derive.contract_of_tag(tag)
        own(user_id, role, contract["grower_id"] if contract else None)
    return respond(derive.grade_json(grade))


@bp.get("/grower-relations/quality-grades")
def list_grades():
    auth(GROWER_RELATIONS_MANAGER, QUALITY_LAB_TECH, ACCOUNTS_PAYABLE_CLERK)
    limit, offset = v.pagination()
    weigh_tag_id = v.filt("weigh_tag_id")
    recommended = v.filt("recommended_disposition")
    items = rows("grades")
    if weigh_tag_id is not None:
        items = [r for r in items if r["weigh_tag_id"] == weigh_tag_id]
    if recommended is not None:
        items = [r for r in items if r["recommended_disposition"] == recommended]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.grade_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)
