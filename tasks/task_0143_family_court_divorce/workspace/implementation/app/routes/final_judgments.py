"""FinalJudgment create and detail routes (PRD §3.6)."""
from flask import Blueprint

from app import serializers, store
from app.auth import require_roles, role, user_id
from app.calculations import asset_division
from app.envelope import success
from app.errors import ApiError, forbidden, invalid_state, not_found
from app.services import case_service
from app.store import lock, new_id, now
from app.util import get_json_body


bp = Blueprint("final_judgments", __name__)


def _case_or_404(case_id):
    case = store.cases.get(case_id)
    if not case:
        raise not_found("Case not found")
    return case


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


# ---------- create --------------------------------------------------------

@bp.post("/cases/<case_id>/final-judgments")
def create_final_judgment(case_id):
    require_roles("Judge")
    body = get_json_body()
    with lock():
        case = _case_or_404(case_id)
        child_so_id = body.get("child_support_order_id")
        spousal_so_id = body.get("spousal_support_order_id")
        plan_id = body.get("parenting_plan_id")

        # Field combination check (same shape as TemporaryOrder).
        if case["has_minor_children"]:
            if not plan_id or not child_so_id:
                raise ApiError(
                    "ERR_TEMP_ORDER_FIELDS",
                    422,
                    "has_minor_children=true requires parenting_plan_id and child_support_order_id",
                )
        else:
            if plan_id or child_so_id:
                raise ApiError(
                    "ERR_TEMP_ORDER_FIELDS",
                    422,
                    "has_minor_children=false forbids parenting_plan_id and child_support_order_id",
                )

        if plan_id:
            plan = store.parenting_plans.get(plan_id)
            if not plan or plan["case_id"] != case_id:
                raise not_found("parenting_plan_id not found on this case")
            if plan["status"] not in {"AGREED", "COURT_IMPOSED"}:
                raise invalid_state("Referenced parenting plan must be AGREED or COURT_IMPOSED")
        if child_so_id:
            cso = store.support_orders.get(child_so_id)
            if not cso or cso["case_id"] != case_id:
                raise not_found("child_support_order_id not found on this case")
            if cso["support_type"] != "CHILD" or cso["order_kind"] != "FINAL":
                raise invalid_state("child_support_order_id must be a FINAL CHILD order")
        if spousal_so_id:
            sso = store.support_orders.get(spousal_so_id)
            if not sso or sso["case_id"] != case_id:
                raise not_found("spousal_support_order_id not found on this case")
            if sso["support_type"] != "SPOUSAL" or sso["order_kind"] != "FINAL":
                raise invalid_state("spousal_support_order_id must be a FINAL SPOUSAL order")

        if not case_service.both_disclosures_accepted(case_id):
            raise ApiError(
                "ERR_DISCLOSURE_INCOMPLETE",
                409,
                "Both disclosures must be ACCEPTED before computing asset division",
            )

        p_disc = case_service.latest_accepted_disclosure(case_id, case["petitioner_party_id"])
        r_disc = case_service.latest_accepted_disclosure(case_id, case["respondent_party_id"])
        p_share, r_share, model = asset_division(case["jurisdiction_state"], p_disc, r_disc)

        ts = now()
        fj = {
            "id": new_id(),
            "case_id": case_id,
            "child_support_order_id": child_so_id,
            "spousal_support_order_id": spousal_so_id,
            "parenting_plan_id": plan_id,
            "petitioner_asset_share_cents": int(p_share),
            "respondent_asset_share_cents": int(r_share),
            "division_model": model,
            "status": "DRAFT",
            "effective_from": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        store.final_judgments[fj["id"]] = fj
        return success(serializers.final_judgment(fj), status=201)


# ---------- detail --------------------------------------------------------

@bp.get("/cases/<case_id>/final-judgments/<judgment_id>")
def get_final_judgment(case_id, judgment_id):
    require_roles("Petitioner", "Respondent", "Judge", "AttorneyOfRecord")
    case = _case_or_404(case_id)
    fj = store.final_judgments.get(judgment_id)
    if not fj or fj["case_id"] != case_id:
        raise not_found("Final judgment not found on this case")
    if role() != "Judge":
        _assert_party_scope(case)
    return success(serializers.final_judgment(fj))
