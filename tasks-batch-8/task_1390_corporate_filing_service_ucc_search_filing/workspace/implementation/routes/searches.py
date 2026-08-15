"""Lien-search routes: ordering, certified-results recording (hit classification,
prior-lien counts, priority position, reflection-dimension transitions), hit listing."""
from flask import Blueprint, request as flask_request

import errors
from db import store
from middleware import auth, body, opt_str, pagination_params, req_enum, req_str, require_role
from response import ok, ok_list
from services import (
    SEARCH_PURPOSES, append_event, hit_json, name_of_record, profile_by_code,
    search_json, stamp_new, touch,
)
from util import new_id, normalize_name, parse_dt

bp = Blueprint("searches", __name__)


def _paginate(records, serializer):
    limit, offset = pagination_params()
    items = [serializer(r) for r in records]
    return ok_list(items[offset:offset + limit], len(items), limit, offset)


def _search_or_404(search_id):
    s = store.lien_searches.get(search_id)
    if s is None:
        raise errors.err_not_found("search")
    return s


@bp.post("/lien-searches")
def create_lien_search():
    auth()
    data = body()
    # Priority 2: structural.
    client_id = req_str(data, "client_id")
    purpose = req_enum(data, "purpose", SEARCH_PURPOSES)
    debtor_id = req_str(data, "debtor_id")
    jurisdiction_code = req_str(data, "jurisdiction_code")
    county_name = opt_str(data, "county_name")
    subject_filing_id = opt_str(data, "subject_filing_id")
    if purpose == "POST_FILING_VERIFICATION" and not subject_filing_id:
        raise errors.err_invalid_request(
            "subject_filing_id is required for POST_FILING_VERIFICATION searches")
    # Priority 3: role.
    _user_id, role = auth()
    require_role(role, "FilingSpecialist")
    # Priority 6: body references.
    if client_id not in store.clients:
        raise errors.err_not_found("client")
    debtor = store.debtors.get(debtor_id)
    if debtor is None or debtor["client_id"] != client_id:
        raise errors.err_not_found("debtor")
    if profile_by_code(jurisdiction_code) is None:
        raise errors.err_not_found("jurisdiction")
    subject = None
    if subject_filing_id is not None:
        subject = store.filings.get(subject_filing_id)
        if subject is None:
            raise errors.err_not_found("filing")
    # Priority 7: verification subjects must be ACTIVE.
    if purpose == "POST_FILING_VERIFICATION" and subject["effectiveness_status"] != "ACTIVE":
        raise errors.err_target_not_active()
    search = stamp_new({
        "id": new_id(),
        "client_id": client_id,
        "purpose": purpose,
        "debtor_id": debtor_id,
        "jurisdiction_code": jurisdiction_code,
        "county_name": county_name,
        "subject_filing_id": subject_filing_id,
        "status": "ORDERED",
        "through_date": None,
        "prior_lien_count": None,
        "priority_position_of_subject": None,
    })
    store.lien_searches[search["id"]] = search
    return ok(search_json(search), 201)


@bp.get("/lien-searches")
def list_lien_searches():
    auth()
    records = list(store.lien_searches.values())
    args = flask_request.args
    for param in ("client_id", "debtor_id", "subject_filing_id", "purpose", "status"):
        value = args.get(param)
        if value is not None:
            records = [s for s in records if s.get(param) == value]
    return _paginate(records, search_json)


@bp.get("/lien-searches/<search_id>")
def get_lien_search(search_id):
    auth()
    return ok(search_json(_search_or_404(search_id)))


@bp.post("/lien-searches/<search_id>/record-results")
def record_results(search_id):
    auth()
    data = body()
    # Priority 2: structural -- through_date and hits[] with typed members.
    if "through_date" not in data or data["through_date"] is None:
        raise errors.err_invalid_request("Missing required field: through_date")
    through_date = parse_dt(data["through_date"])
    if through_date is None:
        raise errors.err_invalid_request("through_date must be an ISO 8601 datetime")
    if through_date > store.clock:
        raise errors.err_invalid_request("through_date must not be later than the current instant")
    if "hits" not in data or data["hits"] is None or not isinstance(data["hits"], list):
        raise errors.err_invalid_request("hits must be an array")
    parsed_hits = []
    for raw in data["hits"]:
        if not isinstance(raw, dict):
            raise errors.err_invalid_request("each hit must be an object")
        found_debtor_name = req_str(raw, "found_debtor_name")
        found_filing_number = req_str(raw, "found_filing_number")
        found_filed_at = parse_dt(raw.get("found_filed_at"))
        if found_filed_at is None:
            raise errors.err_invalid_request("found_filed_at must be an ISO 8601 datetime")
        secured_party_name = req_str(raw, "secured_party_name")
        parsed_hits.append((found_debtor_name, found_filing_number, found_filed_at, secured_party_name))
    # Priority 3: role.
    _user_id, role = auth()
    require_role(role, "SearchAnalyst")
    # Priority 5: existence.
    search = _search_or_404(search_id)
    # Priority 7: one-shot transition.
    if search["status"] != "ORDERED":
        raise errors.err_search_not_ordered()
    subject = store.filings.get(search["subject_filing_id"]) if search["subject_filing_id"] else None
    # Priority 9: verification through-date coverage.
    if search["purpose"] == "POST_FILING_VERIFICATION":
        if subject is None or subject["filed_at"] is None or through_date < subject["filed_at"]:
            raise errors.err_through_date_too_early()
    # Side effects: create and classify the hits.
    debtor = store.debtors[search["debtor_id"]]
    profile = profile_by_code(search["jurisdiction_code"])
    record, _rule = name_of_record(debtor, profile)
    norm_record = normalize_name(record) if record else None
    hit_objs = []
    for found_debtor_name, found_filing_number, found_filed_at, secured_party_name in parsed_hits:
        hit_kind = (
            "EXACT_MATCH"
            if norm_record is not None and normalize_name(found_debtor_name) == norm_record
            else "SIMILAR"
        )
        is_subject = bool(subject) and found_filing_number == subject["filing_number"]
        hit = {
            "id": new_id(),
            "lien_search_id": search["id"],
            "found_debtor_name": found_debtor_name,
            "found_filing_number": found_filing_number,
            "found_filed_at": found_filed_at,
            "secured_party_name": secured_party_name,
            "hit_kind": hit_kind,
            "is_subject_filing": is_subject,
            "created_at": store.clock,
        }
        store.hits[hit["id"]] = hit
        hit_objs.append(hit)
    search["through_date"] = through_date
    if search["purpose"] == "PRE_FILING":
        search["status"] = "COMPLETED"
        search["prior_lien_count"] = sum(1 for h in hit_objs if h["hit_kind"] == "EXACT_MATCH")
    else:
        subject_found = any(h["is_subject_filing"] for h in hit_objs)
        if subject_found:
            search["status"] = "VERIFIED"
            position = 1
            for h in hit_objs:
                if h["hit_kind"] == "EXACT_MATCH" and not h["is_subject_filing"]:
                    if (
                        h["found_filed_at"] < subject["filed_at"]
                        or (h["found_filed_at"] == subject["filed_at"]
                            and h["found_filing_number"] < subject["filing_number"])
                    ):
                        position += 1
            search["priority_position_of_subject"] = position
            if subject["reflection_status"] != "REFLECTED":
                subject["reflection_status"] = "REFLECTED"
                touch(subject)
                append_event(subject, "REFLECTED", {"lien_search_id": search["id"]})
        else:
            search["status"] = "DISCREPANCY"
            search["priority_position_of_subject"] = None
            # REFLECTED is never downgraded; only UNVERIFIED flips to DISCREPANCY.
            if subject["reflection_status"] == "UNVERIFIED":
                subject["reflection_status"] = "DISCREPANCY"
                touch(subject)
                append_event(subject, "DISCREPANCY_FLAGGED", {"lien_search_id": search["id"]})
    touch(search)
    return ok(search_json(search))


@bp.get("/lien-searches/<search_id>/hits")
def list_hits(search_id):
    auth()
    _search_or_404(search_id)
    records = [h for h in store.hits.values() if h["lien_search_id"] == search_id]
    return _paginate(records, hit_json)
