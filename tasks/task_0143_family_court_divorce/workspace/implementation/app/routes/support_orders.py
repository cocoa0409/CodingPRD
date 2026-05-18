"""SupportOrder routes (PRD §3.5)."""
from flask import Blueprint

from app import serializers, store
from app.auth import require_roles, role, user_id
from app.calculations import (
    child_support_amount,
    marriage_duration_years,
    spousal_support_amount,
)
from app.envelope import success, success_list
from app.errors import ApiError, forbidden, invalid_state, not_found
from app.services import case_service
from app.store import lock, new_id, now
from app.util import get_json_body, pagination_args, paginate


bp = Blueprint("support_orders", __name__)


def _case_or_404(case_id):
    case = store.cases.get(case_id)
    if not case:
        raise not_found("Case not found")
    return case


def _order_or_404(case_id, order_id):
    so = store.support_orders.get(order_id)
    if not so or so["case_id"] != case_id:
        raise not_found("Support order not found on this case")
    return so


# ---------- create --------------------------------------------------------

@bp.post("/cases/<case_id>/support-orders")
def create_support_order(case_id):
    require_roles("Judge")
    body = get_json_body()
    with lock():
        case = _case_or_404(case_id)
        support_type = body.get("support_type")
        order_kind = body.get("order_kind")
        if support_type not in {"CHILD", "SPOUSAL"} or order_kind not in {"TEMPORARY", "FINAL"}:
            raise invalid_state("Invalid support_type/order_kind")
        plan_id = body.get("parenting_plan_id")

        # Field-combination check (priority 12).
        if support_type == "CHILD" and not plan_id:
            raise ApiError(
                "ERR_PLAN_REQUIRED_OR_FORBIDDEN",
                422,
                "CHILD support requires parenting_plan_id",
            )
        if support_type == "SPOUSAL" and plan_id:
            raise ApiError(
                "ERR_PLAN_REQUIRED_OR_FORBIDDEN",
                422,
                "SPOUSAL support cannot carry parenting_plan_id",
            )

        # Spousal eligibility check (priority 13) before disclosure-completeness.
        if support_type == "SPOUSAL":
            duration = marriage_duration_years(case["marriage_date"], case["separation_date"])
            if duration < 5:
                raise ApiError(
                    "ERR_NOT_ELIGIBLE_FOR_SPOUSAL",
                    422,
                    "Marriage too short for spousal support",
                )

        if not case_service.both_disclosures_accepted(case_id):
            raise ApiError(
                "ERR_DISCLOSURE_INCOMPLETE",
                409,
                "Both disclosures must be ACCEPTED before computing support",
            )

        p_disc = case_service.latest_accepted_disclosure(case_id, case["petitioner_party_id"])
        r_disc = case_service.latest_accepted_disclosure(case_id, case["respondent_party_id"])

        if support_type == "CHILD":
            plan = store.parenting_plans.get(plan_id)
            if not plan or plan["case_id"] != case_id:
                raise not_found("parenting_plan_id not found on this case")
            monthly, model, obligor_role = child_support_amount(
                case["jurisdiction_state"], p_disc, r_disc, plan
            )
            guideline = model
        else:
            duration = marriage_duration_years(case["marriage_date"], case["separation_date"])
            monthly, obligor_role = spousal_support_amount(p_disc, r_disc, duration)
            guideline = None

        if obligor_role == "PETITIONER":
            obligor_party_id = case["petitioner_party_id"]
            obligee_party_id = case["respondent_party_id"]
        else:
            obligor_party_id = case["respondent_party_id"]
            obligee_party_id = case["petitioner_party_id"]

        ts = now()
        so = {
            "id": new_id(),
            "case_id": case_id,
            "support_type": support_type,
            "order_kind": order_kind,
            "parenting_plan_id": plan_id,
            "obligor_party_id": obligor_party_id,
            "obligee_party_id": obligee_party_id,
            "monthly_amount_cents": int(monthly),
            "guideline_model": guideline,
            "status": "DRAFT",
            "effective_from": None,
            "superseded_by_id": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        store.support_orders[so["id"]] = so
        return success(serializers.support_order(so), status=201)


# ---------- terminate -----------------------------------------------------

@bp.post("/cases/<case_id>/support-orders/<order_id>/terminate")
def terminate_support_order(case_id, order_id):
    require_roles("Judge")
    body = get_json_body()
    with lock():
        case = _case_or_404(case_id)
        so = _order_or_404(case_id, order_id)
        if so["status"] != "ISSUED":
            raise invalid_state("Support order is not ISSUED")

        if so["support_type"] == "CHILD":
            # No child currently <18: we have no child roster in the model, so the
            # safe interpretation is to allow termination only if the case states
            # it has no minor children (i.e. all children are over 18 by now).
            # The PRD couples this to the case's child status; without per-child
            # data we use Case.has_minor_children as the gating fact.
            if case["has_minor_children"]:
                raise invalid_state("A minor child is still on the case")
        else:  # SPOUSAL
            if not bool(body.get("obligee_remarried")):
                raise invalid_state("obligee_remarried must be true to terminate spousal support")

        ts = now()
        so["status"] = "TERMINATED"
        so["updated_at"] = ts
        so["version"] += 1
        return success(serializers.support_order(so))


# ---------- list / detail -------------------------------------------------

def _assert_party_scope(case):
    r = role()
    uid = user_id()
    if r == "Petitioner" and uid != case["petitioner_party_id"]:
        raise forbidden("Caller is not the petitioner on this case")
    if r == "Respondent" and uid != case["respondent_party_id"]:
        raise forbidden("Caller is not the respondent on this case")
    if r == "AttorneyOfRecord":
        pet = store.parties.get(case["petitioner_party_id"])
        res = store.parties.get(case["respondent_party_id"])
        if not ((pet and pet.get("counsel_user_id") == uid) or (res and res.get("counsel_user_id") == uid)):
            raise forbidden("Attorney is not counsel for any party on this case")


@bp.get("/cases/<case_id>/support-orders/<order_id>")
def get_support_order(case_id, order_id):
    require_roles("Petitioner", "Respondent", "Judge", "AttorneyOfRecord")
    case = _case_or_404(case_id)
    so = _order_or_404(case_id, order_id)
    if role() != "Judge":
        _assert_party_scope(case)
    return success(serializers.support_order(so))


@bp.get("/cases/<case_id>/support-orders")
def list_support_orders(case_id):
    require_roles("Petitioner", "Respondent", "Judge", "AttorneyOfRecord")
    case = _case_or_404(case_id)
    if role() != "Judge":
        _assert_party_scope(case)
    limit, offset = pagination_args()
    items = [s for s in store.support_orders.values() if s["case_id"] == case_id]
    page, total = paginate(items, limit, offset)
    return success_list([serializers.support_order(s) for s in page], limit, offset, total)
