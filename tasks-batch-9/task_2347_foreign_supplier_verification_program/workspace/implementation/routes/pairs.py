"""SupplierFoodPair: creation, reads, verification approval, reassessment, exemption."""
from flask import Blueprint, g

import cascades
import core
import serialize
from core import write_txn
from db import store
from errors import fail
from middleware import CO, FDA, QI, endpoint
from response import object_response
from routes._common import find, paged, require_qi_current
from shapes import body, opt_str, pagination, query_enum, query_str, req_enum, req_str

bp = Blueprint("pairs", __name__)

EXEMPTION_ACTIONS = ("CLAIM", "VERIFY", "REJECT", "REVOKE")


@bp.post("/fsvp/supplier-food-pairs")
@endpoint([CO])
def create_pair():
    b = body()
    importer_id = req_str(b, "importer_id")
    supplier_id = req_str(b, "supplier_id")
    food_id = req_str(b, "food_id")
    designated_qi_id = req_str(b, "designated_qi_id")

    importer = find("importer", importer_id, "ERR_IMPORTER_NOT_FOUND")
    qi = find("qi", designated_qi_id, "ERR_QI_NOT_FOUND")
    supplier = find("supplier", supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    food = find("food", food_id, "ERR_FOOD_NOT_FOUND")

    if (
        supplier["importer_id"] != importer["id"]
        or food["importer_id"] != importer["id"]
        or qi["importer_id"] != importer["id"]
    ):
        fail("ERR_IMPORTER_SCOPE_MISMATCH", "every referenced entity must share one importer")

    for row in store.pairs.values():
        if (
            row["supplier_id"] == supplier_id
            and row["food_id"] == food_id
            and row["verification_status"] != "RETIRED"
        ):
            fail("ERR_DUPLICATE_SUPPLIER_FOOD_PAIR", "this supplier-food combination already exists")

    with write_txn():
        row = store.new_row("pair")
        row.update(
            {
                "importer_id": importer_id,
                "supplier_id": supplier_id,
                "food_id": food_id,
                "designated_qi_id": designated_qi_id,
                "active_hazard_analysis_id": None,
                "verification_status": "DRAFT",
                "entry_eligibility_status": "PENDING",
                "exemption_status": "NONE",
                "exemption_type": None,
                "last_reassessed_at": None,
            }
        )
        store.insert(row)
    return object_response(serialize.pair_out(row), 201)


@bp.get("/fsvp/supplier-food-pairs/<pair_id>")
@endpoint([CO, QI, FDA])
def read_pair(pair_id):
    row = find("pair", pair_id, "ERR_PAIR_NOT_FOUND")
    return object_response(serialize.pair_out(row))


@bp.get("/fsvp/supplier-food-pairs")
@endpoint([CO, QI, FDA])
def list_pairs():
    importer_id = query_str("importer_id")
    supplier_id = query_str("supplier_id")
    food_id = query_str("food_id")
    designated_qi_id = query_str("designated_qi_id")
    active_analysis_id = query_str("active_hazard_analysis_id")
    verification_status = query_enum("verification_status", core.VERIFICATION_STATUSES)
    eligibility = query_enum("entry_eligibility_status", core.ENTRY_ELIGIBILITY_STATUSES)
    exemption_status = query_enum("exemption_status", core.EXEMPTION_STATUSES)
    risk_tier = query_enum("risk_tier", ("LOW", "MODERATE", "HIGH"))
    limit, offset = pagination()

    rows = list(store.pairs.values())
    if importer_id is not None:
        rows = [r for r in rows if r["importer_id"] == importer_id]
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    if food_id is not None:
        rows = [r for r in rows if r["food_id"] == food_id]
    if designated_qi_id is not None:
        rows = [r for r in rows if r["designated_qi_id"] == designated_qi_id]
    if active_analysis_id is not None:
        rows = [r for r in rows if r["active_hazard_analysis_id"] == active_analysis_id]
    if verification_status is not None:
        rows = [r for r in rows if r["verification_status"] == verification_status]
    if eligibility is not None:
        rows = [r for r in rows if r["entry_eligibility_status"] == eligibility]
    if exemption_status is not None:
        rows = [r for r in rows if r["exemption_status"] == exemption_status]
    if risk_tier is not None:
        rows = [r for r in rows if core.pair_risk(r)["risk_tier"] == risk_tier]
    return paged(rows, serialize.pair_out, limit, offset)


@bp.post("/fsvp/supplier-food-pairs/<pair_id>/verification-approval")
@endpoint([QI])
def verification_approval(pair_id):
    b = body()
    req_str(b, "approval_note", minlen=1)

    pair = find("pair", pair_id, "ERR_PAIR_NOT_FOUND")

    # rung 19
    if pair["verification_status"] not in ("HAZARD_ANALYZED", "REASSESSMENT_REQUIRED"):
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "verification approval is not available from %s" % pair["verification_status"],
        )

    # rung 26
    require_qi_current()

    supplier = core.supplier_of_pair(pair)

    # rung 27
    if supplier is None or supplier["status"] not in ("APPROVED", "CONDITIONALLY_APPROVED"):
        fail("ERR_SUPPLIER_NOT_APPROVED", "the supplier is not approved")

    # rung 28
    if core.supplier_has_import_suspension(pair["supplier_id"]):
        fail("ERR_IMPORT_SUSPENSION_ACTIVE", "an import suspension is active on this supplier")

    # rung 31
    if not pair["active_hazard_analysis_id"]:
        fail("ERR_HAZARD_ANALYSIS_REQUIRED", "the pair has no active hazard analysis")

    approved = [a for a in core.activities_of_pair(pair["id"]) if a["status"] == "APPROVED"]

    # rung 32
    if not approved:
        fail("ERR_NO_VERIFICATION_ACTIVITY", "no approved verification activity on this pair")

    # rung 33
    sahcodha = [
        h
        for h in core.pair_active_hazards(pair)
        if h["severity"] == 5 and h["requires_control"] and h["control_owner"] == "FOREIGN_SUPPLIER"
    ]
    if sahcodha:
        audits = [
            a
            for a in approved
            if a["activity_type"] == "ONSITE_AUDIT" and a["frequency_per_year"] >= 1
        ]
        if not audits:
            fail("ERR_ONSITE_AUDIT_REQUIRED", "an approved onsite audit is required")

    risk = core.pair_risk(pair)

    # rung 34
    freq_sum = sum(a["frequency_per_year"] for a in approved)
    if freq_sum < risk["required_annual_frequency"]:
        fail(
            "ERR_FREQUENCY_BELOW_REQUIRED",
            "planned frequency %d is below the required %d"
            % (freq_sum, risk["required_annual_frequency"]),
        )

    # rung 35
    planned = core.pair_adequacy_planned(pair)
    floor = core.pair_adequacy_floor(pair)
    if planned < floor:
        fail("ERR_ADEQUACY_BELOW_FLOOR", "adequacy_score_planned is below the applicable floor")

    # rung 41
    due = core.pair_reassessment_due_at(pair)
    if due is not None and due < core.clock():
        fail("ERR_REASSESSMENT_OVERDUE", "the pair is past its reassessment date")

    # rung 48
    if g.user_id != pair["designated_qi_id"]:
        fail(
            "ERR_QI_NOT_DESIGNATED_FOR_PAIR",
            "only the designated qualified individual may sign this approval",
        )

    with write_txn():
        pair["verification_status"] = "VERIFICATION_APPROVED"
        pair["last_reassessed_at"] = core.clock()
        if pair["entry_eligibility_status"] == "PENDING":
            pair["entry_eligibility_status"] = "ELIGIBLE"
        store.touch(pair)
    return object_response(serialize.pair_out(pair))


@bp.post("/fsvp/supplier-food-pairs/<pair_id>/reassessment")
@endpoint([CO, QI])
def reassessment(pair_id):
    b = body()
    req_str(b, "trigger_reason", minlen=1)
    opt_str(b, "note")

    pair = find("pair", pair_id, "ERR_PAIR_NOT_FOUND")
    if pair["verification_status"] != "VERIFICATION_APPROVED":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "reassessment is not available from %s" % pair["verification_status"],
        )

    with write_txn():
        pair["verification_status"] = "REASSESSMENT_REQUIRED"
        pair["last_reassessed_at"] = core.clock()
        store.touch(pair)
    return object_response(serialize.pair_out(pair))


@bp.post("/fsvp/supplier-food-pairs/<pair_id>/exemption")
@endpoint([CO, QI])
def exemption(pair_id):
    b = body()
    action = req_enum(b, "action", EXEMPTION_ACTIONS)
    opt_str(b, "basis_note")
    opt_str(b, "determination_note")
    exemption_type = None
    if action == "CLAIM":
        exemption_type = req_enum(b, "exemption_type", core.EXEMPTION_TYPES)

    pair = find("pair", pair_id, "ERR_PAIR_NOT_FOUND")
    status = pair["exemption_status"]

    allowed = {
        "CLAIM": ("NONE", "REJECTED", "REVOKED"),
        "VERIFY": ("CLAIMED",),
        "REJECT": ("CLAIMED",),
        "REVOKE": ("VERIFIED",),
    }
    if status not in allowed[action]:
        fail("ERR_INVALID_STATE_TRANSITION", "cannot %s from exemption status %s" % (action, status))

    if action == "CLAIM":
        food = core.food_of_pair(pair)
        applicable = core.EXEMPTION_APPLICABILITY[exemption_type]
        if applicable is not None and (
            food is None or food["process_control_category"] not in applicable
        ):
            fail(
                "ERR_EXEMPTION_NOT_APPLICABLE",
                "%s is not applicable to this food" % exemption_type,
            )
        if exemption_type == "SMALL_IMPORTER_MODIFIED":
            importer = core.importer_of_pair(pair)
            if importer is None or not importer["small_importer_flag"]:
                fail(
                    "ERR_MODIFIED_REQUIREMENTS_NOT_AVAILABLE",
                    "the importer is not a very small importer",
                )

    with write_txn():
        if action == "CLAIM":
            pair["exemption_status"] = "CLAIMED"
            pair["exemption_type"] = exemption_type
        elif action == "VERIFY":
            pair["exemption_status"] = "VERIFIED"
            if pair["entry_eligibility_status"] == "PENDING":
                pair["entry_eligibility_status"] = "ELIGIBLE"
        elif action == "REJECT":
            pair["exemption_status"] = "REJECTED"
        else:
            pair["exemption_status"] = "REVOKED"
        store.touch(pair)
        if action == "REVOKE":
            cascades.exemption_revocation_cascade(pair)
    return object_response(serialize.pair_out(pair))
