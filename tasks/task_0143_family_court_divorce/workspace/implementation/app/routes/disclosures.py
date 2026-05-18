"""FinancialDisclosure routes (PRD §3.2)."""
from flask import Blueprint

from app import serializers, store
from app.auth import require_roles, role, user_id
from app.envelope import success, success_list
from app.errors import ApiError, forbidden, invalid_state, not_found, version_conflict
from app.services import case_service
from app.store import lock, new_id, now
from app.util import get_json_body, pagination_args, paginate


bp = Blueprint("disclosures", __name__)


_NUMERIC_FIELDS = (
    "gross_monthly_income_cents",
    "deductible_taxes_cents",
    "monthly_health_insurance_cents",
    "monthly_childcare_cents",
    "assets_total_cents",
    "debts_total_cents",
)


def _case_or_404(case_id):
    case = store.cases.get(case_id)
    if not case:
        raise not_found("Case not found")
    return case


def _disclosure_or_404(case_id, disclosure_id):
    d = store.disclosures.get(disclosure_id)
    if not d or d["case_id"] != case_id:
        raise not_found("Disclosure not found on this case")
    return d


def _assert_party_owner(case, party_id):
    """For Petitioner/Respondent/AttorneyOfRecord acting on a disclosure owned by `party_id`."""
    r = role()
    uid = user_id()
    party = store.parties.get(party_id)
    if not party or party["case_id"] != case["id"]:
        raise forbidden("Party not on this case")
    if r == "Petitioner":
        if uid != party["id"] or party["id"] != case["petitioner_party_id"]:
            raise forbidden("Petitioner can only act on their own disclosure")
    elif r == "Respondent":
        if uid != party["id"] or party["id"] != case["respondent_party_id"]:
            raise forbidden("Respondent can only act on their own disclosure")
    elif r == "AttorneyOfRecord":
        if party.get("counsel_user_id") != uid:
            raise forbidden("Attorney does not represent that party")


def _recompute_net(disclosure):
    gross = int(disclosure.get("gross_monthly_income_cents") or 0)
    taxes = int(disclosure.get("deductible_taxes_cents") or 0)
    disclosure["net_monthly_income_cents"] = max(0, gross - taxes)


# ---------- create --------------------------------------------------------

@bp.post("/cases/<case_id>/disclosures")
def create_disclosure(case_id):
    require_roles("Petitioner", "Respondent", "AttorneyOfRecord")
    with lock():
        case = _case_or_404(case_id)
        body = get_json_body()
        party_id = body.get("party_id")
        if not party_id:
            raise invalid_state("party_id is required")
        _assert_party_owner(case, party_id)

        # Uniqueness on (case_id, party_id).
        for existing in store.disclosures.values():
            if existing["case_id"] == case_id and existing["party_id"] == party_id:
                raise ApiError(
                    "ERR_DUPLICATE_DISCLOSURE",
                    409,
                    "A disclosure already exists for this party on this case",
                )

        ts = now()
        d = {
            "id": new_id(),
            "case_id": case_id,
            "party_id": party_id,
            "gross_monthly_income_cents": int(body.get("gross_monthly_income_cents") or 0),
            "deductible_taxes_cents": int(body.get("deductible_taxes_cents") or 0),
            "monthly_health_insurance_cents": int(body.get("monthly_health_insurance_cents") or 0),
            "monthly_childcare_cents": int(body.get("monthly_childcare_cents") or 0),
            "assets_total_cents": int(body.get("assets_total_cents") or 0),
            "debts_total_cents": int(body.get("debts_total_cents") or 0),
            "status": "DRAFT",
            "rejection_reason": None,
            "net_monthly_income_cents": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        _recompute_net(d)
        store.disclosures[d["id"]] = d
        return success(serializers.disclosure(d), status=201)


# ---------- patch ---------------------------------------------------------

@bp.patch("/cases/<case_id>/disclosures/<disclosure_id>")
def patch_disclosure(case_id, disclosure_id):
    require_roles("Petitioner", "Respondent", "AttorneyOfRecord")
    with lock():
        case = _case_or_404(case_id)
        d = _disclosure_or_404(case_id, disclosure_id)
        _assert_party_owner(case, d["party_id"])

        if d["status"] not in {"DRAFT", "REJECTED"}:
            raise invalid_state("Disclosure is not editable in its current state")

        body = get_json_body()
        if "version" in body and body["version"] is not None:
            if int(body["version"]) != int(d["version"]):
                raise version_conflict()

        for field in _NUMERIC_FIELDS:
            if field in body and body[field] is not None:
                d[field] = int(body[field])
        ts = now()
        was_rejected = d["status"] == "REJECTED"
        if was_rejected:
            d["status"] = "DRAFT"
            d["rejection_reason"] = None
        _recompute_net(d)
        d["updated_at"] = ts
        d["version"] += 1
        return success(serializers.disclosure(d))


# ---------- submit --------------------------------------------------------

@bp.post("/cases/<case_id>/disclosures/<disclosure_id>/submit")
def submit_disclosure(case_id, disclosure_id):
    require_roles("Petitioner", "Respondent", "AttorneyOfRecord")
    with lock():
        case = _case_or_404(case_id)
        d = _disclosure_or_404(case_id, disclosure_id)
        _assert_party_owner(case, d["party_id"])
        if d["status"] != "DRAFT":
            raise invalid_state("Disclosure is not DRAFT")
        body = get_json_body()
        if "version" in body and body["version"] is not None:
            if int(body["version"]) != int(d["version"]):
                raise version_conflict()

        # Non-negativity and gross > 0.
        for field in _NUMERIC_FIELDS:
            val = int(d.get(field) or 0)
            if val < 0:
                raise ApiError("ERR_DISCLOSURE_INCOMPLETE", 409, f"{field} must be non-negative")
        if int(d.get("gross_monthly_income_cents") or 0) <= 0:
            raise ApiError(
                "ERR_DISCLOSURE_INCOMPLETE",
                409,
                "gross_monthly_income_cents must be greater than zero",
            )
        # Consistency: deductible_taxes_cents <= gross.
        if int(d["deductible_taxes_cents"]) > int(d["gross_monthly_income_cents"]):
            raise ApiError(
                "ERR_DISCLOSURE_INCONSISTENT",
                422,
                "deductible_taxes_cents cannot exceed gross_monthly_income_cents",
            )

        ts = now()
        d["status"] = "SUBMITTED"
        _recompute_net(d)
        d["updated_at"] = ts
        d["version"] += 1

        case_service.bump_case_status_on_first_submit(case, ts)
        return success(serializers.disclosure(d))


# ---------- accept --------------------------------------------------------

@bp.post("/cases/<case_id>/disclosures/<disclosure_id>/accept")
def accept_disclosure(case_id, disclosure_id):
    require_roles("Judge")
    with lock():
        case = _case_or_404(case_id)
        d = _disclosure_or_404(case_id, disclosure_id)
        if d["status"] != "SUBMITTED":
            raise invalid_state("Disclosure is not SUBMITTED")
        body = get_json_body()
        if "version" in body and body["version"] is not None:
            if int(body["version"]) != int(d["version"]):
                raise version_conflict()

        ts = now()
        d["status"] = "ACCEPTED"
        _recompute_net(d)
        d["updated_at"] = ts
        d["version"] += 1

        case_service.maybe_defaulted_petitioner_accepted(case, d, ts)
        return success(serializers.disclosure(d))


# ---------- reject --------------------------------------------------------

@bp.post("/cases/<case_id>/disclosures/<disclosure_id>/reject")
def reject_disclosure(case_id, disclosure_id):
    require_roles("Judge")
    with lock():
        case = _case_or_404(case_id)
        d = _disclosure_or_404(case_id, disclosure_id)
        if d["status"] != "SUBMITTED":
            raise invalid_state("Disclosure is not SUBMITTED")
        body = get_json_body()
        if "version" in body and body["version"] is not None:
            if int(body["version"]) != int(d["version"]):
                raise version_conflict()
        reason = body.get("rejection_reason")
        if not reason or not str(reason).strip():
            raise ApiError(
                "ERR_REJECTION_REASON_REQUIRED",
                422,
                "rejection_reason is required",
            )

        ts = now()
        d["status"] = "REJECTED"
        d["rejection_reason"] = reason
        d["updated_at"] = ts
        d["version"] += 1
        return success(serializers.disclosure(d))


# ---------- list ----------------------------------------------------------

@bp.get("/cases/<case_id>/disclosures")
def list_disclosures(case_id):
    require_roles("Petitioner", "Respondent", "Judge", "AttorneyOfRecord")
    case = _case_or_404(case_id)
    # Party-scope read access for non-Judge roles.
    r = role()
    uid = user_id()
    if r in {"Petitioner", "Respondent"}:
        if r == "Petitioner" and uid != case["petitioner_party_id"]:
            raise forbidden("Caller is not the petitioner on this case")
        if r == "Respondent" and uid != case["respondent_party_id"]:
            raise forbidden("Caller is not the respondent on this case")
    elif r == "AttorneyOfRecord":
        pet = store.parties.get(case["petitioner_party_id"])
        res = store.parties.get(case["respondent_party_id"])
        if not ((pet and pet.get("counsel_user_id") == uid) or (res and res.get("counsel_user_id") == uid)):
            raise forbidden("Attorney is not counsel for any party on this case")

    limit, offset = pagination_args()
    items = [d for d in store.disclosures.values() if d["case_id"] == case_id]
    page, total = paginate(items, limit, offset)
    return success_list([serializers.disclosure(d) for d in page], limit, offset, total)
