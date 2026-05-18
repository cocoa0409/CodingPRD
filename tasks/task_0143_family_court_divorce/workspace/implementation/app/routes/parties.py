"""Party read endpoints."""
from flask import Blueprint

from app import serializers, store
from app.auth import require_roles, role, user_id
from app.envelope import success, success_list
from app.errors import forbidden, not_found
from app.util import pagination_args, paginate


bp = Blueprint("parties", __name__)


def _case_or_404(case_id):
    case = store.cases.get(case_id)
    if not case:
        raise not_found("Case not found")
    return case


def _assert_party_scope_on_case(case):
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


@bp.get("/cases/<case_id>/parties")
def list_parties(case_id):
    require_roles("Petitioner", "Respondent", "Judge", "AttorneyOfRecord", "PlatformAdmin")
    case = _case_or_404(case_id)
    if role() in {"Petitioner", "Respondent", "AttorneyOfRecord"}:
        _assert_party_scope_on_case(case)
    limit, offset = pagination_args()
    items = [p for p in store.parties.values() if p["case_id"] == case_id]
    page, total = paginate(items, limit, offset)
    return success_list([serializers.party(p) for p in page], limit, offset, total)


@bp.get("/cases/<case_id>/parties/<party_id>")
def get_party(case_id, party_id):
    require_roles("Petitioner", "Respondent", "Judge", "AttorneyOfRecord", "PlatformAdmin")
    case = _case_or_404(case_id)
    party = store.parties.get(party_id)
    if not party or party["case_id"] != case_id:
        raise not_found("Party not found on this case")
    if role() in {"Petitioner", "Respondent", "AttorneyOfRecord"}:
        _assert_party_scope_on_case(case)
    return success(serializers.party(party))
