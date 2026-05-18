"""ParentingPlan routes (PRD §3.3 / §3.4)."""
from flask import Blueprint

from app import serializers, store
from app.auth import require_roles, role, user_id
from app.envelope import success, success_list
from app.errors import ApiError, forbidden, invalid_state, not_found, version_conflict
from app.services import case_service
from app.store import lock, new_id, now
from app.util import get_json_body, pagination_args, paginate


bp = Blueprint("parenting_plans", __name__)


_LEGAL = {"JOINT", "PETITIONER_SOLE", "RESPONDENT_SOLE"}
_PHYS = {"JOINT", "PETITIONER_PRIMARY", "RESPONDENT_PRIMARY"}


def _case_or_404(case_id):
    case = store.cases.get(case_id)
    if not case:
        raise not_found("Case not found")
    return case


def _plan_or_404(case_id, plan_id):
    p = store.parenting_plans.get(plan_id)
    if not p or p["case_id"] != case_id:
        raise not_found("Parenting plan not found on this case")
    return p


def _is_proposer(plan, role_name, uid):
    """True if the current actor is the proposer of `plan` (or that proposer's attorney)."""
    party = store.parties.get(plan["proposing_party_id"])
    if not party:
        return False
    if role_name in {"Petitioner", "Respondent"}:
        return uid == party["id"]
    if role_name == "AttorneyOfRecord":
        return party.get("counsel_user_id") == uid
    return False


# ---------- create (propose or counter) ----------------------------------

@bp.post("/cases/<case_id>/parenting-plans")
def create_plan(case_id):
    require_roles("Petitioner", "Respondent", "AttorneyOfRecord")
    body = get_json_body()
    with lock():
        case = _case_or_404(case_id)

        proposing_party_id = body.get("proposing_party_id")
        if not proposing_party_id:
            raise invalid_state("proposing_party_id is required")
        proposer_party = store.parties.get(proposing_party_id)
        if not proposer_party or proposer_party["case_id"] != case_id:
            raise forbidden("proposing_party_id is not on this case")

        # Identity binding for party-scoped roles.
        r = role()
        uid = user_id()
        if r == "Petitioner":
            if uid != proposer_party["id"] or proposer_party["id"] != case["petitioner_party_id"]:
                raise forbidden("Petitioner can only propose for themselves")
        elif r == "Respondent":
            if uid != proposer_party["id"] or proposer_party["id"] != case["respondent_party_id"]:
                raise forbidden("Respondent can only propose for themselves")
        elif r == "AttorneyOfRecord":
            if proposer_party.get("counsel_user_id") != uid:
                raise forbidden("Attorney does not represent the proposing party")

        countered_plan_id = body.get("countered_plan_id")
        countered_plan = None
        if countered_plan_id:
            countered_plan = store.parenting_plans.get(countered_plan_id)
            if not countered_plan or countered_plan["case_id"] != case_id:
                raise not_found("countered_plan_id not found on this case")
            # Counter-by-proposer check (validation priority 9, before overnights validation).
            cprev_party = store.parties.get(countered_plan["proposing_party_id"])
            if r in {"Petitioner", "Respondent"} and cprev_party and cprev_party["id"] == uid:
                raise ApiError(
                    "ERR_COUNTER_BY_PROPOSER",
                    422,
                    "The party who proposed cannot counter their own plan",
                )
            if r == "AttorneyOfRecord" and cprev_party and cprev_party.get("counsel_user_id") == uid:
                raise ApiError(
                    "ERR_COUNTER_BY_PROPOSER",
                    422,
                    "Attorney cannot counter on behalf of the original proposing party",
                )
            if countered_plan["status"] not in {"PROPOSED", "COUNTERED"}:
                # PRD only mentions PROPOSED -> COUNTERED; counter against finished plan is a state error.
                raise invalid_state("Plan being countered is not in a counterable state")

        legal = body.get("legal_custody")
        physical = body.get("physical_custody")
        if legal not in _LEGAL or physical not in _PHYS:
            raise invalid_state("Invalid custody enum")

        try:
            p_overnights = int(body.get("petitioner_overnights_per_year"))
            r_overnights = int(body.get("respondent_overnights_per_year"))
        except (TypeError, ValueError):
            raise ApiError("ERR_OVERNIGHTS_INVALID", 422, "Overnight counts must be integers")
        if not (0 <= p_overnights <= 365) or not (0 <= r_overnights <= 365):
            raise ApiError("ERR_OVERNIGHTS_INVALID", 422, "Overnights out of range [0, 365]")
        if p_overnights + r_overnights != 365:
            raise ApiError(
                "ERR_OVERNIGHTS_INVALID",
                422,
                "Overnight counts must sum to 365",
            )

        ts = now()
        plan = {
            "id": new_id(),
            "case_id": case_id,
            "proposing_party_id": proposing_party_id,
            "legal_custody": legal,
            "physical_custody": physical,
            "petitioner_overnights_per_year": p_overnights,
            "respondent_overnights_per_year": r_overnights,
            "status": "PROPOSED",
            "countered_by_plan_id": None,
            "pinned_petitioner_disclosure_version": None,
            "pinned_respondent_disclosure_version": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        store.parenting_plans[plan["id"]] = plan

        if countered_plan is not None:
            countered_plan["status"] = "COUNTERED"
            countered_plan["countered_by_plan_id"] = plan["id"]
            countered_plan["updated_at"] = ts
            countered_plan["version"] += 1

        return success(serializers.parenting_plan(plan), status=201)


# ---------- accept --------------------------------------------------------

@bp.post("/cases/<case_id>/parenting-plans/<plan_id>/accept")
def accept_plan(case_id, plan_id):
    require_roles("Petitioner", "Respondent", "AttorneyOfRecord")
    with lock():
        case = _case_or_404(case_id)
        plan = _plan_or_404(case_id, plan_id)
        r = role()
        uid = user_id()

        # Self-accept check (priority 10) — before state and other business rules.
        if _is_proposer(plan, r, uid):
            raise ApiError(
                "ERR_SELF_ACCEPT",
                422,
                "Acceptor cannot be the original proposer (or their counsel)",
            )

        # Party scope: caller must be a party on this case.
        if r == "Petitioner" and uid != case["petitioner_party_id"]:
            raise forbidden("Caller is not the petitioner on this case")
        if r == "Respondent" and uid != case["respondent_party_id"]:
            raise forbidden("Caller is not the respondent on this case")
        if r == "AttorneyOfRecord":
            pet = store.parties.get(case["petitioner_party_id"])
            res = store.parties.get(case["respondent_party_id"])
            if not ((pet and pet.get("counsel_user_id") == uid) or (res and res.get("counsel_user_id") == uid)):
                raise forbidden("Attorney is not counsel for any party on this case")

        if plan["status"] not in {"PROPOSED", "COUNTERED"}:
            raise invalid_state("Plan cannot be accepted from its current state")
        if plan["countered_by_plan_id"] is not None:
            raise invalid_state("Plan has been countered; accept the newer plan instead")

        if not case_service.both_disclosures_accepted(case_id):
            raise ApiError(
                "ERR_DISCLOSURE_INCOMPLETE",
                409,
                "Both parties' disclosures must be ACCEPTED",
            )

        body = get_json_body()
        if "version" in body and body["version"] is not None:
            if int(body["version"]) != int(plan["version"]):
                raise version_conflict()

        # Snapshot the most recent ACCEPTED disclosure version for each party.
        p_disc = case_service.latest_accepted_disclosure(case_id, case["petitioner_party_id"])
        r_disc = case_service.latest_accepted_disclosure(case_id, case["respondent_party_id"])
        plan["pinned_petitioner_disclosure_version"] = int(p_disc["version"])
        plan["pinned_respondent_disclosure_version"] = int(r_disc["version"])

        ts = now()
        plan["status"] = "AGREED"
        plan["updated_at"] = ts
        plan["version"] += 1

        # If case is in MEDIATION and a plan is now AGREED, advance to AWAITING_JUDGMENT.
        case_service.maybe_advance_mediation_to_judgment(case, ts)
        return success(serializers.parenting_plan(plan))


# ---------- impose --------------------------------------------------------

@bp.post("/cases/<case_id>/parenting-plans/<plan_id>/impose")
def impose_plan(case_id, plan_id):
    require_roles("Judge")
    with lock():
        case = _case_or_404(case_id)
        plan = _plan_or_404(case_id, plan_id)
        if plan["status"] != "CONTESTED":
            raise invalid_state("Plan is not CONTESTED")
        if case["mediation_round"] < 3:
            raise ApiError(
                "ERR_MEDIATION_NOT_EXHAUSTED",
                409,
                "Mediation rounds have not reached the cap",
            )
        body = get_json_body()
        if "version" in body and body["version"] is not None:
            if int(body["version"]) != int(plan["version"]):
                raise version_conflict()

        ts = now()
        plan["status"] = "COURT_IMPOSED"
        plan["updated_at"] = ts
        plan["version"] += 1

        case_service.maybe_advance_mediation_to_judgment(case, ts)
        return success(serializers.parenting_plan(plan))


# ---------- list/detail ---------------------------------------------------

@bp.get("/cases/<case_id>/parenting-plans")
def list_plans(case_id):
    require_roles("Petitioner", "Respondent", "Judge", "AttorneyOfRecord")
    case = _case_or_404(case_id)
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
    limit, offset = pagination_args()
    items = [p for p in store.parenting_plans.values() if p["case_id"] == case_id]
    page, total = paginate(items, limit, offset)
    return success_list([serializers.parenting_plan(p) for p in page], limit, offset, total)


@bp.get("/cases/<case_id>/parenting-plans/<plan_id>")
def get_plan(case_id, plan_id):
    require_roles("Petitioner", "Respondent", "Judge", "AttorneyOfRecord")
    case = _case_or_404(case_id)
    plan = _plan_or_404(case_id, plan_id)
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
    return success(serializers.parenting_plan(plan))
