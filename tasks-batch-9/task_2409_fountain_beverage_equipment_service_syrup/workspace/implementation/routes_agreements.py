"""Placement agreements (PRD 3.2) plus the commercial reckoning of PRD 3.9."""

from flask import Blueprint, g

from calc import RECALL_EXPOSURE_FLOOR_CENTS, agreement_shortfall_fee, equipment_recall_exposure
from core import (
    AGREEMENT_STATUSES,
    EXPOSURE_VARIANTS,
    body,
    db,
    endpoint,
    f_bool,
    f_dt,
    f_int,
    f_num,
    f_str,
    get_agreement,
    get_outlet,
    interval_ok,
    new_id,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    q_str,
    require,
    sort_rows,
    stamp_new,
    touch,
)
from serialize import ser_agreement

bp = Blueprint("agreements", __name__)


# ---------------------------------------------------------------------------
# POST /fountain-network/placement-agreements
# ---------------------------------------------------------------------------
@bp.post("/placement-agreements")
@endpoint(["NetworkAdmin"])
def create_agreement():
    payload = body()
    # rung 3
    outlet_id = f_str(payload, "outlet_id", required=True)
    start_raw, start_dt = f_dt(payload, "term_start_date", required=True)
    end_raw, end_dt = f_dt(payload, "term_end_date", required=True)
    commitment = f_num(payload, "annual_commitment_gallons", required=True, gt=0)
    equipment_value_cents = f_int(payload, "equipment_value_cents", required=True, gt=0)
    free_on_loan = f_bool(payload, "free_on_loan", default=True)
    fee_per_gallon = f_int(payload, "shortfall_fee_cents_per_gallon", default=50, ge=0)
    expected_outlet_version = f_int(payload, "expected_outlet_version", required=True)
    # rung 5
    outlet = get_outlet(outlet_id)
    # rung 7
    require(
        expected_outlet_version == outlet["version"],
        "ERR_STALE_OUTLET_VERSION",
        "expected_outlet_version %s does not match the outlet's stored version %s."
        % (expected_outlet_version, outlet["version"]),
    )
    # rung 21
    interval_ok(start_dt, end_dt)

    agreement = {
        "id": new_id(),
        "outlet_id": outlet["id"],
        "term_start_date": start_raw,
        "term_end_date": end_raw,
        "_term_start": start_dt,
        "_term_end": end_dt,
        "annual_commitment_gallons": commitment,
        "free_on_loan": free_on_loan,
        "shortfall_fee_cents_per_gallon": fee_per_gallon,
        "equipment_value_cents": equipment_value_cents,
        "status": "DRAFT",
        "assessed_shortfall_gallons": 0,
        "assessed_fee_cents": 0,
        "exposure_variant": "BOOK_VALUE",
        "recall_exposure_cents": 0,
        "assessment_period_start": None,
        "assessment_period_end": None,
        "shortfall_assessed_by_user_id": None,
        "recall_decided_by_user_id": None,
    }
    stamp_new(agreement)
    db.agreements[agreement["id"]] = agreement

    # any other DRAFT agreement of the same outlet is superseded
    for other in sort_rows(
        [
            a
            for a in db.agreements.values()
            if a["outlet_id"] == outlet["id"] and a["id"] != agreement["id"] and a["status"] == "DRAFT"
        ]
    ):
        other["status"] = "EXPIRED"
        touch(other)
    touch(outlet)
    return ok(ser_agreement(agreement), 201)


# ---------------------------------------------------------------------------
# GET /fountain-network/placement-agreements/{id}
# ---------------------------------------------------------------------------
@bp.get("/placement-agreements/<aid>")
@endpoint(["NetworkAdmin", "ComplianceOfficer", "SupplyPlanner", "OutletManager"])
def read_agreement(aid):
    return ok(ser_agreement(get_agreement(aid)))


# ---------------------------------------------------------------------------
# GET /fountain-network/placement-agreements
# ---------------------------------------------------------------------------
@bp.get("/placement-agreements")
@endpoint(["NetworkAdmin", "ComplianceOfficer", "SupplyPlanner"])
def list_agreements():
    limit, offset = pagination()
    outlet_id = q_str("outlet_id")
    status = q_str("status", enum=AGREEMENT_STATUSES)
    rows = list(db.agreements.values())
    if outlet_id is not None:
        rows = [r for r in rows if r["outlet_id"] == outlet_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([ser_agreement(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /fountain-network/placement-agreements/{id}/activate
# ---------------------------------------------------------------------------
@bp.post("/placement-agreements/<aid>/activate")
@endpoint(["NetworkAdmin"])
def activate_agreement(aid):
    # rung 4
    agreement = get_agreement(aid)
    outlet = db.outlets.get(agreement["outlet_id"])
    # rung 9
    require(
        agreement["status"] == "DRAFT",
        "ERR_INVALID_STATE_TRANSITION",
        "Only a DRAFT agreement can be activated.",
    )
    require(
        outlet is not None and outlet["status"] == "ACTIVE",
        "ERR_INVALID_STATE_TRANSITION",
        "The owning outlet must be ACTIVE.",
    )
    require(
        any(u["agreement_id"] == agreement["id"] for u in db.units.values()),
        "ERR_INVALID_STATE_TRANSITION",
        "At least one dispenser unit must reference the agreement before activation.",
    )
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return ok(ser_agreement(agreement))


# ---------------------------------------------------------------------------
# POST /fountain-network/placement-agreements/{id}/assess-shortfall
# ---------------------------------------------------------------------------
@bp.post("/placement-agreements/<aid>/assess-shortfall")
@endpoint(["NetworkAdmin"])
def assess_shortfall(aid):
    payload = body()
    # rung 3
    start_raw, start_dt = f_dt(payload, "period_start_date", required=True)
    end_raw, end_dt = f_dt(payload, "period_end_date", required=True)
    variant = f_str(payload, "exposure_variant", default="BOOK_VALUE", enum=EXPOSURE_VARIANTS)
    # rung 4
    agreement = get_agreement(aid)
    # rung 9
    require(
        agreement["status"] == "ACTIVE",
        "ERR_INVALID_STATE_TRANSITION",
        "Only an ACTIVE agreement can be assessed.",
    )
    # rung 21
    interval_ok(start_dt, end_dt)

    result = agreement_shortfall_fee(agreement, start_dt, end_dt)
    # rung 34
    require(
        result["assessed_fee_cents"] > 0,
        "ERR_NO_SHORTFALL_TO_ASSESS",
        "The assessment produced no shortfall fee.",
    )

    agreement["assessed_shortfall_gallons"] = result["assessed_shortfall_gallons"]
    agreement["assessed_fee_cents"] = result["assessed_fee_cents"]
    agreement["recall_exposure_cents"] = equipment_recall_exposure(agreement, now(), variant)
    agreement["exposure_variant"] = variant
    agreement["assessment_period_start"] = start_raw
    agreement["assessment_period_end"] = end_raw
    agreement["shortfall_assessed_by_user_id"] = g.user_id
    agreement["status"] = "SHORTFALL_REVIEW"
    touch(agreement)
    return ok(ser_agreement(agreement))


# ---------------------------------------------------------------------------
# POST /fountain-network/placement-agreements/{id}/recall-decision
# ---------------------------------------------------------------------------
@bp.post("/placement-agreements/<aid>/recall-decision")
@endpoint(["ComplianceOfficer"])
def recall_decision(aid):
    payload = body()
    # rung 3
    outcome = f_str(payload, "outcome", required=True, enum=("FEE_ONLY", "RECALL"))
    # rung 4
    agreement = get_agreement(aid)
    # rung 9
    require(
        agreement["status"] == "SHORTFALL_REVIEW",
        "ERR_INVALID_STATE_TRANSITION",
        "Only an agreement in SHORTFALL_REVIEW can carry a recall decision.",
    )
    # rung 16
    require(
        g.user_id != agreement["shortfall_assessed_by_user_id"],
        "ERR_SEGREGATION_OF_DUTIES",
        "The recall decision must be recorded by someone other than the assessor.",
    )
    if outcome == "RECALL":
        # rung 35
        require(
            agreement["free_on_loan"] is True,
            "ERR_RECALL_NOT_PERMITTED",
            "Equipment that is not free-on-loan cannot be recalled.",
        )
        # rung 36
        require(
            agreement["recall_exposure_cents"] >= RECALL_EXPOSURE_FLOOR_CENTS,
            "ERR_RECALL_EXPOSURE_BELOW_FLOOR",
            "recall_exposure_cents is below the %s cent floor." % RECALL_EXPOSURE_FLOOR_CENTS,
        )

    agreement["recall_decided_by_user_id"] = g.user_id
    if outcome == "FEE_ONLY":
        agreement["status"] = "ACTIVE"
        touch(agreement)
    else:
        agreement["status"] = "RECALL_PENDING"
        touch(agreement)
        for unit in sort_rows(
            [
                u
                for u in db.units.values()
                if u["agreement_id"] == agreement["id"] and u["status"] in ("IN_SERVICE", "SERVICE_HOLD")
            ]
        ):
            unit["status"] = "RECALL_STAGED"
            touch(unit)
    return ok(ser_agreement(agreement))


# ---------------------------------------------------------------------------
# POST /fountain-network/placement-agreements/{id}/close-term
# ---------------------------------------------------------------------------
@bp.post("/placement-agreements/<aid>/close-term")
@endpoint(["NetworkAdmin"])
def close_term(aid):
    # rung 4
    agreement = get_agreement(aid)
    # rung 9
    require(
        agreement["status"] == "ACTIVE",
        "ERR_INVALID_STATE_TRANSITION",
        "Only an ACTIVE agreement's term can be closed.",
    )
    # rung 22
    require(
        now() >= agreement["_term_end"],
        "ERR_TERM_NOT_ELAPSED",
        "The agreement term has not elapsed on the logical clock.",
    )
    agreement["status"] = "EXPIRED"
    touch(agreement)
    return ok(ser_agreement(agreement))
