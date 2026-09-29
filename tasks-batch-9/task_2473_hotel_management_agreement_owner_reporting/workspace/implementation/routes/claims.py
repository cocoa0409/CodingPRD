"""Employment claim liability between owner and manager."""

from flask import Blueprint

import validate as v
from auth import READ_ROLES, authenticate
from db import by_seq, new_row, serialize, store, touch
from errors import ApiError
from response import ok
from routes.common import paged
from services import calc, core

bp = Blueprint("claims", __name__)

POSITION_CLASSES = ("GM", "EXEC_COMMITTEE", "LINE_STAFF")
ALLOCATION_ACTIONS = ("ALLOCATE", "REVERSE")
EMPLOYER_OF_RECORD = {"OWNER_EMPLOYEES": "OWNER", "MANAGER_EMPLOYEES": "MANAGER"}


# ---------------------------------------------------------------------------
# POST /hotel-management/agreements/{id}/employment-claims
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/agreements/<agreement_id>/employment-claims")
def file_claim(agreement_id):
    authenticate(["HotelManagerOps"])
    body = v.body()
    position_class = v.req_str(body, "position_class")
    claim_amount_cents = v.req_int(body, "claim_amount_cents", gt=0)
    gross_negligence = v.opt_bool(body, "gross_negligence", default=False)
    v.check_enum(position_class, POSITION_CLASSES, "position_class")

    agreement = core.find_agreement(agreement_id)
    core.require_active(agreement)

    claim = new_row(
        {
            "agreement_id": agreement["id"],
            "position_class": position_class,
            "claim_amount_cents": claim_amount_cents,
            "gross_negligence": gross_negligence,
            "employer_of_record": EMPLOYER_OF_RECORD[agreement["employee_model"]],
            "owner_share_cents": 0,
            "manager_share_cents": 0,
            "status": "FILED",
        }
    )
    store.employment_claims[claim["id"]] = claim
    return ok(serialize(claim), 201)


@bp.get("/hotel-management/agreements/<agreement_id>/employment-claims")
def list_claims(agreement_id):
    authenticate(READ_ROLES)
    agreement = core.find_agreement(agreement_id)
    rows = by_seq(
        [c for c in store.employment_claims.values() if c["agreement_id"] == agreement["id"]]
    )
    status = v.query_str("status")
    position_class = v.query_str("position_class")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if position_class is not None:
        rows = [r for r in rows if r["position_class"] == position_class]
    return paged(rows)


# ---------------------------------------------------------------------------
# POST /hotel-management/employment-claims/{id}/allocation
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/employment-claims/<claim_id>/allocation")
def allocate(claim_id):
    authenticate(["AssetManager"])
    body = v.body()
    action = v.req_str(body, "action")
    v.check_enum(action, ALLOCATION_ACTIONS, "action")

    claim = core.find_claim(claim_id)
    agreement = core.find_agreement(claim["agreement_id"])

    if action == "ALLOCATE":
        core.require_active_or_cure(agreement)
        if claim["status"] not in ("FILED", "REVERSED"):
            raise ApiError("ERR_INVALID_CLAIM_STATE")

        owner_share, manager_share = calc.employment_split(
            claim["claim_amount_cents"],
            claim["gross_negligence"],
            agreement["employee_model"],
            claim["position_class"],
            agreement["manager_indemnity_cap_cents"],
        )
        claim["owner_share_cents"] = owner_share
        claim["manager_share_cents"] = manager_share
        claim["status"] = "ALLOCATED"
        touch(claim)

        # hop 1 -- both balances move
        agreement["working_capital_balance_cents"] = (
            agreement["working_capital_balance_cents"] - owner_share
        )
        agreement["manager_liability_accrued_cents"] = (
            agreement["manager_liability_accrued_cents"] + manager_share
        )
        touch(agreement)

        # hop 2 -- measured against the balance AFTER hop 1, and skipped at the floor
        gap = agreement["working_capital_floor_cents"] - agreement["working_capital_balance_cents"]
        if gap > 0:
            core.create_working_capital_call(agreement, gap, "CLAIM_ALLOCATION", True)
        return ok(serialize(claim))

    # REVERSE -- no agreement-status gate is declared for this branch
    if claim["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    owner_share = claim["owner_share_cents"]
    manager_share = claim["manager_share_cents"]
    claim["status"] = "REVERSED"
    claim["owner_share_cents"] = 0
    claim["manager_share_cents"] = 0
    touch(claim)

    agreement["working_capital_balance_cents"] = (
        agreement["working_capital_balance_cents"] + owner_share
    )
    agreement["manager_liability_accrued_cents"] = (
        agreement["manager_liability_accrued_cents"] - manager_share
    )
    touch(agreement)
    return ok(serialize(claim))
