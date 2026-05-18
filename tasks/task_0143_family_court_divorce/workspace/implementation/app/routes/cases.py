"""Case-level endpoints: petition filing, lifecycle, and reads."""
from datetime import timedelta

from flask import Blueprint, request

from app import serializers, store
from app.auth import require_roles, role, user_id
from app.envelope import success, success_list
from app.errors import ApiError, forbidden, invalid_state, not_found
from app.services import case_service
from app.store import lock, new_id, now, parse_iso
from app.util import get_json_body, pagination_args, paginate


bp = Blueprint("cases", __name__)


# ---------- create ----------------------------------------------------------

@bp.post("/cases")
def create_case():
    require_roles("Petitioner", "AttorneyOfRecord")
    body = get_json_body()

    jurisdiction = body.get("jurisdiction_state")
    if jurisdiction not in {"CA", "NY", "TX", "FL", "IL", "WA"}:
        raise ApiError("ERR_INVALID_STATE", 409, "Invalid jurisdiction_state")

    marriage_date = parse_iso(body.get("marriage_date"))
    separation_date = parse_iso(body.get("separation_date"))
    if marriage_date is None or separation_date is None:
        raise ApiError("ERR_SEPARATION_BEFORE_MARRIAGE", 422, "Invalid date(s)")
    if separation_date <= marriage_date:
        raise ApiError(
            "ERR_SEPARATION_BEFORE_MARRIAGE",
            422,
            "separation_date must be strictly after marriage_date",
        )

    has_minor_children = bool(body.get("has_minor_children"))
    petitioner_in = body.get("petitioner") or {}
    respondent_in = body.get("respondent") or {}

    for who, src in (("petitioner", petitioner_in), ("respondent", respondent_in)):
        if not isinstance(src, dict) or not src.get("full_name") \
                or src.get("date_of_birth") is None \
                or src.get("gross_monthly_income_cents") is None:
            raise ApiError("ERR_INVALID_STATE", 409, f"Missing {who} fields")

    with lock():
        ts = now()
        case_id = new_id()
        petitioner_party = {
            "id": new_id(),
            "case_id": case_id,
            "role": "PETITIONER",
            "full_name": petitioner_in.get("full_name"),
            "date_of_birth": parse_iso(petitioner_in.get("date_of_birth")),
            "gross_monthly_income_cents": int(petitioner_in.get("gross_monthly_income_cents")),
            "counsel_user_id": petitioner_in.get("counsel_user_id"),
            "served_at": None,
            "has_filed_answer": False,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        respondent_party = {
            "id": new_id(),
            "case_id": case_id,
            "role": "RESPONDENT",
            "full_name": respondent_in.get("full_name"),
            "date_of_birth": parse_iso(respondent_in.get("date_of_birth")),
            "gross_monthly_income_cents": int(respondent_in.get("gross_monthly_income_cents")),
            "counsel_user_id": respondent_in.get("counsel_user_id"),
            "served_at": ts,
            "has_filed_answer": False,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }

        docket = store.next_docket(ts.year)
        case = {
            "id": case_id,
            "docket_number": docket,
            "petitioner_party_id": petitioner_party["id"],
            "respondent_party_id": respondent_party["id"],
            "jurisdiction_state": jurisdiction,
            "marriage_date": marriage_date,
            "separation_date": separation_date,
            "has_minor_children": has_minor_children,
            # PRD §3.1: "immediately advances" from FILED to AWAITING_ANSWER.
            "status": "AWAITING_ANSWER",
            "answer_deadline_at": ts + timedelta(days=30),
            "response_received_at": None,
            "mediation_round": 0,
            "temporary_order_id": None,
            "final_judgment_id": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }

        # If acting as Petitioner, the X-User-ID is the petitioner Party.id by definition.
        # We don't enforce a separate check here because the petition creates the Party.
        store.parties[petitioner_party["id"]] = petitioner_party
        store.parties[respondent_party["id"]] = respondent_party
        store.cases[case_id] = case
        return success(serializers.case(case), status=201)


# ---------- detail / list ---------------------------------------------------

def _get_case_or_404(case_id):
    case = store.cases.get(case_id)
    if not case:
        raise not_found("Case not found")
    return case


def _assert_case_party_scope(case):
    """For Petitioner/Respondent/AttorneyOfRecord, verify they have standing on this case."""
    r = role()
    uid = user_id()
    if r == "Petitioner":
        if uid != case["petitioner_party_id"]:
            raise forbidden("Caller is not the petitioner on this case")
    elif r == "Respondent":
        if uid != case["respondent_party_id"]:
            raise forbidden("Caller is not the respondent on this case")
    elif r == "AttorneyOfRecord":
        pet = store.parties.get(case["petitioner_party_id"])
        res = store.parties.get(case["respondent_party_id"])
        if (pet and pet.get("counsel_user_id") == uid) or (res and res.get("counsel_user_id") == uid):
            return
        raise forbidden("Attorney is not counsel for any party on this case")


@bp.get("/cases/<case_id>")
def get_case(case_id):
    require_roles("Petitioner", "Respondent", "Judge", "AttorneyOfRecord", "PlatformAdmin")
    case = _get_case_or_404(case_id)
    if role() in {"Petitioner", "Respondent", "AttorneyOfRecord"}:
        _assert_case_party_scope(case)
    return success(serializers.case(case))


@bp.get("/cases")
def list_cases():
    require_roles("Judge", "PlatformAdmin")
    limit, offset = pagination_args()
    status_filter = request.args.get("status")
    jurisdiction_filter = request.args.get("jurisdiction_state")

    candidates = list(store.cases.values())
    if status_filter:
        candidates = [c for c in candidates if c["status"] == status_filter]
    if jurisdiction_filter:
        candidates = [c for c in candidates if c["jurisdiction_state"] == jurisdiction_filter]
    page, total = paginate(candidates, limit, offset)
    return success_list([serializers.case(c) for c in page], limit, offset, total)


# ---------- lifecycle endpoints --------------------------------------------

@bp.post("/cases/<case_id>/answer")
def file_answer(case_id):
    require_roles("Respondent", "AttorneyOfRecord")
    with lock():
        case = _get_case_or_404(case_id)
        # Party-scope: must be respondent (or that respondent's attorney).
        r = role()
        uid = user_id()
        respondent = store.parties.get(case["respondent_party_id"])
        if r == "Respondent":
            if uid != case["respondent_party_id"]:
                raise forbidden("Caller is not the respondent on this case")
        elif r == "AttorneyOfRecord":
            if not respondent or respondent.get("counsel_user_id") != uid:
                raise forbidden("Attorney does not represent the respondent")

        if case["status"] != "AWAITING_ANSWER":
            raise invalid_state("Case is not awaiting an answer")
        if respondent.get("has_filed_answer"):
            raise invalid_state("Respondent has already filed an answer")
        ts = now()
        if ts > case["answer_deadline_at"]:
            raise ApiError("ERR_ANSWER_WINDOW_EXPIRED", 409, "Answer window has expired")

        respondent["has_filed_answer"] = True
        respondent["updated_at"] = ts
        respondent["version"] += 1

        case["status"] = "ANSWERED"
        case["response_received_at"] = ts
        case["updated_at"] = ts
        case["version"] += 1

        return success(serializers.case(case))


@bp.post("/cases/<case_id>/default")
def file_default(case_id):
    require_roles("Petitioner", "AttorneyOfRecord")
    with lock():
        case = _get_case_or_404(case_id)
        r = role()
        uid = user_id()
        petitioner = store.parties.get(case["petitioner_party_id"])
        if r == "Petitioner":
            if uid != case["petitioner_party_id"]:
                raise forbidden("Caller is not the petitioner on this case")
        elif r == "AttorneyOfRecord":
            if not petitioner or petitioner.get("counsel_user_id") != uid:
                raise forbidden("Attorney does not represent the petitioner")

        if case["status"] != "AWAITING_ANSWER":
            raise invalid_state("Case is not awaiting an answer")
        respondent = store.parties.get(case["respondent_party_id"])
        if respondent and respondent.get("has_filed_answer"):
            raise invalid_state("Respondent already filed an answer")
        ts = now()
        if ts <= case["answer_deadline_at"]:
            raise ApiError("ERR_ANSWER_WINDOW_OPEN", 409, "Answer window still open")

        case["status"] = "DEFAULTED"
        case["updated_at"] = ts
        case["version"] += 1
        return success(serializers.case(case))


@bp.post("/cases/<case_id>/start-mediation")
def start_mediation(case_id):
    require_roles("Petitioner", "AttorneyOfRecord")
    with lock():
        case = _get_case_or_404(case_id)
        r = role()
        uid = user_id()
        petitioner = store.parties.get(case["petitioner_party_id"])
        if r == "Petitioner":
            if uid != case["petitioner_party_id"]:
                raise forbidden("Caller is not the petitioner on this case")
        elif r == "AttorneyOfRecord":
            if not petitioner or petitioner.get("counsel_user_id") != uid:
                raise forbidden("Attorney does not represent the petitioner")

        if case["status"] != "DISCLOSURE":
            raise invalid_state("Case is not in DISCLOSURE")
        # Both disclosures must be ACCEPTED.
        if not case_service.both_disclosures_accepted(case_id):
            raise ApiError("ERR_DISCLOSURE_INCOMPLETE", 409, "Both disclosures must be ACCEPTED")
        # At least one plan in PROPOSED/COUNTERED/AGREED (parenting plan precondition for §3.4).
        if case["has_minor_children"]:
            plans = case_service.plans_for_case(case_id)
            if not any(p["status"] in {"PROPOSED", "COUNTERED", "AGREED"} for p in plans):
                raise invalid_state("No active parenting plan to mediate")

        case["status"] = "MEDIATION"
        ts = now()
        case["updated_at"] = ts
        case["version"] += 1
        return success(serializers.case(case))


@bp.post("/cases/<case_id>/dismiss")
def dismiss_case(case_id):
    require_roles("Judge")
    body = get_json_body()
    with lock():
        case = _get_case_or_404(case_id)
        if case["status"] not in {"FILED", "AWAITING_ANSWER"}:
            raise invalid_state("Case can only be dismissed before answer")
        case["status"] = "DISMISSED"
        case["dismiss_reason"] = body.get("reason")
        ts = now()
        case["updated_at"] = ts
        case["version"] += 1
        return success(serializers.case(case))


@bp.post("/cases/<case_id>/issue-temp-order")
def issue_temp_order(case_id):
    require_roles("Judge")
    body = get_json_body()
    temp_id = body.get("temporary_order_id")
    if not temp_id:
        raise invalid_state("temporary_order_id is required")
    with lock():
        case = _get_case_or_404(case_id)
        temp = store.temp_orders.get(temp_id)
        if not temp or temp["case_id"] != case_id:
            raise not_found("TemporaryOrder not found on this case")

        if temp["status"] != "DRAFT":
            raise invalid_state("TemporaryOrder is not DRAFT")
        if case["status"] not in {"DISCLOSURE", "MEDIATION"}:
            raise invalid_state("Case is not eligible to issue temp order")
        if not case_service.both_disclosures_accepted(case_id):
            raise ApiError("ERR_DISCLOSURE_INCOMPLETE", 409, "Both disclosures must be ACCEPTED")

        if case["has_minor_children"]:
            plan = store.parenting_plans.get(temp.get("parenting_plan_id"))
            if not plan or plan["case_id"] != case_id:
                raise invalid_state("Referenced parenting plan is invalid")
            if case["status"] == "DISCLOSURE":
                if plan["status"] not in {"PROPOSED", "COUNTERED", "AGREED"}:
                    raise invalid_state("Parenting plan is not in an active proposing state")
            else:
                # MEDIATION
                if plan["status"] not in {"AGREED", "CONTESTED", "COURT_IMPOSED"}:
                    raise invalid_state("Parenting plan is not eligible for mediation-phase issuance")

        ts = now()
        # Cascade: temp order becomes EFFECTIVE.
        temp["status"] = "EFFECTIVE"
        temp["effective_from"] = ts
        temp["updated_at"] = ts
        temp["version"] += 1

        # Cascade: linked TEMPORARY support orders go DRAFT -> ISSUED.
        for so_id_key in ("child_support_order_id", "spousal_support_order_id"):
            so_id = temp.get(so_id_key)
            if not so_id:
                continue
            so = store.support_orders.get(so_id)
            if so and so["status"] == "DRAFT" and so["order_kind"] == "TEMPORARY":
                case_service.issue_support_order(so, ts)

        case["temporary_order_id"] = temp["id"]
        case["status"] = "TEMP_ORDERED"
        case["updated_at"] = ts
        case["version"] += 1

        # After TEMP_ORDERED, auto-progress to AWAITING_JUDGMENT when the parenting
        # picture is finalised (or no minor children).
        case_service.maybe_advance_to_awaiting_judgment(case, ts)
        return success(serializers.case(case))


@bp.post("/cases/<case_id>/issue-final-judgment")
def issue_final_judgment(case_id):
    require_roles("Judge")
    body = get_json_body()
    fj_id = body.get("final_judgment_id")
    if not fj_id:
        raise invalid_state("final_judgment_id is required")
    with lock():
        case = _get_case_or_404(case_id)
        fj = store.final_judgments.get(fj_id)
        if not fj or fj["case_id"] != case_id:
            raise not_found("FinalJudgment not found on this case")

        if fj["status"] != "DRAFT":
            raise invalid_state("FinalJudgment is not DRAFT")
        if case["status"] != "AWAITING_JUDGMENT":
            raise invalid_state("Case is not AWAITING_JUDGMENT")
        if not case_service.both_disclosures_accepted(case_id):
            raise ApiError("ERR_DISCLOSURE_INCOMPLETE", 409, "Both disclosures must be ACCEPTED")
        if case["has_minor_children"]:
            plan = store.parenting_plans.get(fj.get("parenting_plan_id"))
            if not plan or plan["case_id"] != case_id:
                raise invalid_state("Referenced parenting plan is invalid")
            if plan["status"] not in {"AGREED", "COURT_IMPOSED"}:
                raise invalid_state("Parenting plan must be AGREED or COURT_IMPOSED")

        ts = now()
        fj["status"] = "EFFECTIVE"
        fj["effective_from"] = ts
        fj["updated_at"] = ts
        fj["version"] += 1

        # Map support_type -> new FINAL order id for the supersede pointer.
        final_orders_by_type = {}
        for so_id_key in ("child_support_order_id", "spousal_support_order_id"):
            so_id = fj.get(so_id_key)
            if not so_id:
                continue
            so = store.support_orders.get(so_id)
            if so and so["status"] == "DRAFT" and so["order_kind"] == "FINAL":
                case_service.issue_support_order(so, ts)
                final_orders_by_type[so["support_type"]] = so["id"]

        # Supersede the active TemporaryOrder, if any.
        if case.get("temporary_order_id"):
            old_temp = store.temp_orders.get(case["temporary_order_id"])
            if old_temp and old_temp["status"] == "EFFECTIVE":
                old_temp["status"] = "SUPERSEDED"
                old_temp["superseded_at"] = ts
                old_temp["updated_at"] = ts
                old_temp["version"] += 1
                for so_id_key in ("child_support_order_id", "spousal_support_order_id"):
                    so_id = old_temp.get(so_id_key)
                    if not so_id:
                        continue
                    so = store.support_orders.get(so_id)
                    if so and so["status"] == "ISSUED" and so["order_kind"] == "TEMPORARY":
                        so["status"] = "SUPERSEDED"
                        # Point at the matching FINAL order of the same support_type.
                        so["superseded_by_id"] = final_orders_by_type.get(so["support_type"])
                        so["updated_at"] = ts
                        so["version"] += 1

        # Supersede other AGREED/COURT_IMPOSED parenting plans on the case.
        chosen_plan_id = fj.get("parenting_plan_id")
        if chosen_plan_id:
            for pp in case_service.plans_for_case(case_id):
                if pp["id"] == chosen_plan_id:
                    continue
                if pp["status"] in {"AGREED", "COURT_IMPOSED"}:
                    pp["status"] = "SUPERSEDED"
                    pp["updated_at"] = ts
                    pp["version"] += 1

        case["final_judgment_id"] = fj["id"]
        case["status"] = "FINALIZED"
        case["updated_at"] = ts
        case["version"] += 1
        return success(serializers.case(case))
