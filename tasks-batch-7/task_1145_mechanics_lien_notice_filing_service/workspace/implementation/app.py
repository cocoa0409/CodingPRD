"""Mechanics Lien Notice & Filing Service — Flask app.

All state is in-memory (see core.db). The logical clock starts at
2026-05-01T00:00:00Z and only moves via POST /_clock/set_current_utc.
Validation order follows PRD §2.10: auth -> endpoint role -> company scoping ->
existence -> state -> OCC -> compliance gates -> referential -> temporal ->
uniqueness/aggregate -> fiscal.
"""

import os

from flask import Flask

from core import (
    db, ApiError, ok_object, paginate, body_json, require_roles, current_role,
    current_user_id, scope_company, new_entity, touch, get_or_404,
    clock_now, set_clock, fmt_ts, parse_date, fmt_date, add_calendar_days,
    error_response,
)
from domain import (
    effective_rule, published_rule_exists, recompute_project_furnishing_dates,
    first_furnishing_date, last_furnishing_date, prelim_service_deadline,
    provisional_amount, final_amount, gross_claimable, waiver_waterfall,
    verified_paid_sum, outstanding_for_claim, recompute_claim_amounts,
    serialize_claim, notice_fee_cents, bond_amount, recompute_posture,
    recount_open_notices, apply_notice_expiry, apply_claim_expiry,
    apply_stop_notice_expiry, apply_bond_claim_expiry, lazy_refresh_project,
    claim_exit_filed, cancel_open_referrals, OPEN_CLAIM_STATUSES,
    OPEN_REFERRAL_STATUSES,
)

app = Flask(__name__)

PROJECT_TYPES = {"COMMERCIAL_PRIVATE", "RESIDENTIAL_PRIVATE", "STATE_PUBLIC", "FEDERAL_PUBLIC"}
PARTY_ROLES = {"OWNER", "GC", "LENDER", "HIRER", "SURETY"}
SPAN_KINDS = {"BASE_CONTRACT", "CHANGE_ORDER", "PUNCH_LIST", "WARRANTY"}
DELIVERY_METHODS = {"CERTIFIED_MAIL", "PERSONAL_SERVICE", "EMAIL_STATUTORY"}
DAY_BASIS = {"CALENDAR", "BUSINESS"}
CAP_MODES = {"UNCAPPED", "CONTRACT_BALANCE"}
WAIVER_TYPES = {"CONDITIONAL_PROGRESS", "UNCONDITIONAL_PROGRESS", "CONDITIONAL_FINAL", "UNCONDITIONAL_FINAL"}
PROOF_RESULTS = {"DELIVERED", "REFUSED", "RETURNED"}
DECIDE_OUTCOMES = {"VERIFIED", "FAILED"}
REFERRAL_OUTCOMES = {"ACCEPTED", "DECLINED"}
BOND_RESOLVE_OUTCOMES = {"PAID", "DENIED"}


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(Exception)
def handle_generic(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_VALIDATION", str(err), 400))


# ===========================================================================
# Logical clock
# ===========================================================================


@app.post("/_clock/set_current_utc")
def clock_set():
    require_roles("PlatformAdmin")
    data = body_json(required=["to_iso8601"])
    dt = set_clock(data["to_iso8601"])
    return ok_object({"current_utc": fmt_ts(dt)})


# ===========================================================================
# Companies
# ===========================================================================


@app.post("/lien/companies")
def company_create():
    require_roles("PlatformAdmin")
    data = body_json(required=["name", "contact_email"])
    company = new_entity({
        "name": data["name"],
        "contact_email": data["contact_email"],
        "prepaid_balance_cents": 0,
        "open_notice_count": 0,
    })
    db["companies"][company["id"]] = company
    return ok_object(company, 201)


@app.get("/lien/companies/<cid>")
def company_get(cid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    company = get_or_404("companies", cid)
    scope_company(company["id"])
    return ok_object(company)


@app.post("/lien/companies/<cid>/balance-adjustments")
def company_balance_adjust(cid):
    require_roles("PlatformAdmin")
    company = get_or_404("companies", cid)
    data = body_json(required=["amount_cents", "reason", "expected_company_version"],
                     int_fields=["amount_cents", "expected_company_version"])
    # OCC
    if data["expected_company_version"] != company["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_company_version does not match current version", 412)
    company["prepaid_balance_cents"] += data["amount_cents"]
    touch(company)
    return ok_object(company, 201)


@app.get("/lien/companies/<cid>/projects")
def company_projects(cid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    company = get_or_404("companies", cid)
    scope_company(company["id"])
    projects = [p for p in db["projects"].values() if p["company_id"] == cid]
    return paginate(projects)


# ===========================================================================
# Jurisdiction rules
# ===========================================================================

RULE_INPUT_FIELDS = [
    "prelim_notice_required", "prelim_days", "prelim_day_basis",
    "refused_counts_as_served", "allowed_delivery_methods", "filing_window_days",
    "foreclosure_deadline_days", "stop_notice_days", "bond_claim_days",
    "counts_punch_list", "retainage_claimable", "cap_mode",
    "interest_annual_rate", "bond_pct", "effective_from",
]


def validate_rule_body(extra_required=()):
    return body_json(
        required=list(extra_required) + RULE_INPUT_FIELDS,
        enums={"project_type": PROJECT_TYPES, "prelim_day_basis": DAY_BASIS, "cap_mode": CAP_MODES},
        int_fields=["prelim_days", "filing_window_days", "foreclosure_deadline_days",
                    "stop_notice_days", "bond_claim_days"],
        bool_fields=["prelim_notice_required", "refused_counts_as_served",
                     "counts_punch_list", "retainage_claimable"],
        number_fields=["interest_annual_rate", "bond_pct"],
        date_fields=["effective_from"],
        list_fields=["allowed_delivery_methods"],
    )


@app.post("/lien/jurisdiction-rules")
def rule_create():
    require_roles("PlatformAdmin")
    data = body_json(
        required=["state_code", "project_type"] + RULE_INPUT_FIELDS,
        enums={"project_type": PROJECT_TYPES, "prelim_day_basis": DAY_BASIS, "cap_mode": CAP_MODES},
        int_fields=["prelim_days", "filing_window_days", "foreclosure_deadline_days",
                    "stop_notice_days", "bond_claim_days"],
        bool_fields=["prelim_notice_required", "refused_counts_as_served",
                     "counts_punch_list", "retainage_claimable"],
        number_fields=["interest_annual_rate", "bond_pct"],
        date_fields=["effective_from"],
        list_fields=["allowed_delivery_methods"],
    )
    for m in data["allowed_delivery_methods"]:
        if m not in DELIVERY_METHODS:
            raise ApiError("ERR_VALIDATION", "allowed_delivery_methods contains an invalid value", 400)
    if published_rule_exists(data["state_code"], data["project_type"]):
        raise ApiError("ERR_RULE_ALREADY_PUBLISHED",
                       "A PUBLISHED rule already exists for this (state_code, project_type)", 409)
    fields = {k: data[k] for k in RULE_INPUT_FIELDS}
    fields["state_code"] = data["state_code"]
    fields["project_type"] = data["project_type"]
    fields["status"] = "PUBLISHED"
    fields["supersedes_rule_id"] = None
    rule = new_entity(fields)
    db["jurisdiction_rules"][rule["id"]] = rule
    return ok_object(rule, 201)


@app.post("/lien/jurisdiction-rules/<rid>/supersede")
def rule_supersede(rid):
    require_roles("PlatformAdmin")
    rule = get_or_404("jurisdiction_rules", rid)
    data = validate_rule_body(extra_required=["expected_jurisdiction_rule_version"])
    for m in data["allowed_delivery_methods"]:
        if m not in DELIVERY_METHODS:
            raise ApiError("ERR_VALIDATION", "allowed_delivery_methods contains an invalid value", 400)
    if not isinstance(data["expected_jurisdiction_rule_version"], int) or \
            isinstance(data["expected_jurisdiction_rule_version"], bool):
        raise ApiError("ERR_VALIDATION", "expected_jurisdiction_rule_version must be an integer", 400)
    # State precondition sits above OCC (PRD §2.10)
    if rule["status"] != "PUBLISHED":
        raise ApiError("ERR_RULE_NOT_PUBLISHED", "Addressed rule is not PUBLISHED", 409)
    if data["expected_jurisdiction_rule_version"] != rule["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_jurisdiction_rule_version does not match current version", 412)

    fields = {k: data[k] for k in RULE_INPUT_FIELDS}
    fields["state_code"] = rule["state_code"]
    fields["project_type"] = rule["project_type"]
    fields["status"] = "PUBLISHED"
    fields["supersedes_rule_id"] = rule["id"]
    successor = new_entity(fields)
    db["jurisdiction_rules"][successor["id"]] = successor

    rule["status"] = "SUPERSEDED"
    touch(rule)

    # Cascade: matching projects recompute live deadlines; DRAFT notices past the
    # recomputed service_deadline auto-expire; open-notice counters decremented.
    for project in list(db["projects"].values()):
        if project["state_code"] == rule["state_code"] and project["project_type"] == rule["project_type"]:
            recompute_project_furnishing_dates(project)
            eff = effective_rule(project)
            for notice in list(db["notices"].values()):
                if notice["project_id"] == project["id"] and notice["status"] == "DRAFT":
                    notice["service_deadline"] = fmt_date(prelim_service_deadline(project, eff))
                    touch(notice)
                    apply_notice_expiry(notice)
            recount_open_notices(project)
            touch(project)
            recompute_posture(project)
    return ok_object(successor, 201)


@app.get("/lien/jurisdiction-rules/<rid>")
def rule_get(rid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    rule = get_or_404("jurisdiction_rules", rid)
    return ok_object(rule)


@app.get("/lien/jurisdiction-rules/<rid>/successors")
def rule_successors(rid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    get_or_404("jurisdiction_rules", rid)
    succ = [r for r in db["jurisdiction_rules"].values() if r["supersedes_rule_id"] == rid]
    return paginate(succ)


@app.get("/lien/jurisdiction-rules/<rid>/lien-claims")
def rule_lien_claims(rid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    get_or_404("jurisdiction_rules", rid)
    claims = [serialize_claim(c) for c in db["lien_claims"].values()
              if c.get("locked_rule_id") == rid]
    return paginate(claims)


# ===========================================================================
# Projects
# ===========================================================================


@app.post("/lien/projects")
def project_create():
    require_roles("CustomerAdmin")
    data = body_json(
        required=["name", "state_code", "county", "project_type",
                  "property_legal_description", "contract_value_cents",
                  "approved_extras_cents", "retainage_held_cents"],
        enums={"project_type": PROJECT_TYPES},
        int_fields=["contract_value_cents", "approved_extras_cents", "retainage_held_cents"],
    )
    project = new_entity({
        "company_id": current_user_id(),
        "name": data["name"],
        "state_code": data["state_code"],
        "county": data["county"],
        "project_type": data["project_type"],
        "property_legal_description": data["property_legal_description"],
        "contract_value_cents": data["contract_value_cents"],
        "approved_extras_cents": data["approved_extras_cents"],
        "retainage_held_cents": data["retainage_held_cents"],
        "research_status": "UNRESEARCHED",
        "first_furnishing_date": None,
        "last_furnishing_date": None,
        "open_notice_count": 0,
        "open_lien_count": 0,
        "lien_posture": "CLEAR",
    })
    db["projects"][project["id"]] = project
    return ok_object(project, 201)


def load_project_scoped(pid):
    project = get_or_404("projects", pid)
    scope_company(project["company_id"])
    return project


@app.get("/lien/projects/<pid>")
def project_get(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    project = load_project_scoped(pid)
    lazy_refresh_project(project)
    return ok_object(project)


@app.post("/lien/projects/<pid>/research-advance")
def project_research_advance(pid):
    require_roles("OpsAgent")
    project = get_or_404("projects", pid)
    if project["research_status"] == "VERIFIED":
        raise ApiError("ERR_RESEARCH_ALREADY_VERIFIED", "Project research is already VERIFIED", 409)
    if project["research_status"] == "UNRESEARCHED":
        project["research_status"] = "RESEARCHED"
        touch(project)
        return ok_object(project)
    # RESEARCHED -> VERIFIED: required parties must be VERIFIED
    parties = [p for p in db["parties"].values() if p["project_id"] == pid]
    rule = effective_rule(project)
    required_roles = {"OWNER", "GC"}
    if rule is not None and rule["prelim_notice_required"]:
        required_roles.add("LENDER")
    ok = True
    for role in required_roles:
        if not any(p["party_role"] == role and p["research_status"] == "VERIFIED" for p in parties):
            ok = False
            break
    if not ok:
        raise ApiError("ERR_PARTIES_UNVERIFIED", "Required parties are not all VERIFIED", 409)
    project["research_status"] = "VERIFIED"
    touch(project)
    return ok_object(project)


@app.get("/lien/projects/<pid>/deadline-calendar")
def project_deadline_calendar(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    project = load_project_scoped(pid)
    lazy_refresh_project(project)
    rule = effective_rule(project)
    recompute_project_furnishing_dates(project)
    last, variant = last_furnishing_date(project, rule)
    out = {
        "applied_rule_id": rule["id"] if rule else None,
        "prelim_notice_deadline": None,
        "filing_window_end": None,
        "stop_notice_deadline": None,
        "last_furnishing_date": fmt_date(last),
        "last_furnishing_variant": variant,
    }
    if rule is not None:
        ffd = first_furnishing_date(pid)
        if ffd is not None:
            from core import add_days as _add_days
            out["prelim_notice_deadline"] = fmt_date(
                _add_days(ffd, int(rule["prelim_days"]), rule["prelim_day_basis"]))
        if last is not None:
            out["filing_window_end"] = fmt_date(add_calendar_days(last, int(rule["filing_window_days"])))
            out["stop_notice_deadline"] = fmt_date(add_calendar_days(last, int(rule["stop_notice_days"])))
    return ok_object(out)


def _project_children(pid, collection):
    return [e for e in db[collection].values() if e.get("project_id") == pid]


@app.get("/lien/projects/<pid>/parties")
def project_parties(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    load_project_scoped(pid)
    return paginate(_project_children(pid, "parties"))


@app.get("/lien/projects/<pid>/furnishing-spans")
def project_spans(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    load_project_scoped(pid)
    return paginate(_project_children(pid, "furnishing_spans"))


@app.get("/lien/projects/<pid>/notices")
def project_notices(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    project = load_project_scoped(pid)
    for n in _project_children(pid, "notices"):
        apply_notice_expiry(n)
    recount_open_notices(project)
    recompute_posture(project)
    return paginate(_project_children(pid, "notices"))


@app.get("/lien/projects/<pid>/lien-claims")
def project_claims(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    project = load_project_scoped(pid)
    for c in _project_children(pid, "lien_claims"):
        apply_claim_expiry(c)
    recompute_posture(project)
    return paginate([serialize_claim(c) for c in _project_children(pid, "lien_claims")])


@app.get("/lien/projects/<pid>/waivers")
def project_waivers(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    load_project_scoped(pid)
    return paginate(_project_children(pid, "waivers"))


@app.get("/lien/projects/<pid>/payments")
def project_payments(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    load_project_scoped(pid)
    return paginate(_project_children(pid, "payments"))


@app.get("/lien/projects/<pid>/stop-notices")
def project_stop_notices(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    project = load_project_scoped(pid)
    for s in _project_children(pid, "stop_notices"):
        apply_stop_notice_expiry(s)
    recompute_posture(project)
    return paginate(_project_children(pid, "stop_notices"))


@app.get("/lien/projects/<pid>/bond-claims")
def project_bond_claims(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    project = load_project_scoped(pid)
    for b in _project_children(pid, "bond_claims"):
        apply_bond_claim_expiry(b)
    recompute_posture(project)
    return paginate(_project_children(pid, "bond_claims"))


# ===========================================================================
# Parties
# ===========================================================================


@app.post("/lien/parties")
def party_create():
    require_roles("CustomerAdmin")
    data = body_json(required=["project_id", "party_role", "legal_name", "address"],
                     enums={"party_role": PARTY_ROLES})
    project = get_or_404("projects", data["project_id"])
    scope_company(project["company_id"])
    party = new_entity({
        "project_id": project["id"],
        "party_role": data["party_role"],
        "legal_name": data["legal_name"],
        "address": data["address"],
        "research_status": "PENDING",
    })
    db["parties"][party["id"]] = party
    return ok_object(party, 201)


def load_party_scoped(party_id):
    party = get_or_404("parties", party_id)
    project = db["projects"].get(party["project_id"])
    if project is not None:
        scope_company(project["company_id"])
    return party


@app.get("/lien/parties/<pid>")
def party_get(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    party = load_party_scoped(pid)
    return ok_object(party)


@app.post("/lien/parties/<pid>/decide")
def party_decide(pid):
    require_roles("OpsAgent")
    party = get_or_404("parties", pid)
    data = body_json(required=["outcome"], enums={"outcome": DECIDE_OUTCOMES})
    party["research_status"] = data["outcome"]
    touch(party)
    return ok_object(party)


@app.get("/lien/parties/<pid>/notices")
def party_notices(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    party = load_party_scoped(pid)
    notices = [n for n in db["notices"].values() if n["recipient_party_id"] == pid]
    for n in notices:
        apply_notice_expiry(n)
    return paginate(notices)


@app.get("/lien/parties/<pid>/bonding-requests")
def party_bonding_requests(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    load_party_scoped(pid)
    return paginate([b for b in db["bonding_requests"].values() if b["surety_party_id"] == pid])


@app.get("/lien/parties/<pid>/bond-claims")
def party_bond_claims(pid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    load_party_scoped(pid)
    items = []
    for b in db["bond_claims"].values():
        if b["surety_party_id"] == pid:
            apply_bond_claim_expiry(b)
            items.append(b)
    return paginate(items)


# ===========================================================================
# Furnishing spans
# ===========================================================================


@app.post("/lien/furnishing-spans")
def span_create():
    require_roles("CustomerAdmin")
    data = body_json(
        required=["project_id", "span_kind", "start_date", "end_date", "expected_project_version"],
        enums={"span_kind": SPAN_KINDS},
        date_fields=["start_date", "end_date"],
        int_fields=["expected_project_version"],
    )
    project = get_or_404("projects", data["project_id"])
    scope_company(project["company_id"])
    # OCC (state-priority slot 5b): after existence, before temporal checks
    if data["expected_project_version"] != project["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_project_version does not match current version", 412)
    start = parse_date(data["start_date"])
    end = parse_date(data["end_date"])
    if end < start:
        raise ApiError("ERR_SPAN_DATES_INVALID", "end_date must be >= start_date", 422)
    # Supersede the prior ACTIVE span of the same kind
    for s in db["furnishing_spans"].values():
        if (s["project_id"] == project["id"] and s["span_kind"] == data["span_kind"]
                and s["status"] == "ACTIVE"):
            s["status"] = "SUPERSEDED"
            touch(s)
    span = new_entity({
        "project_id": project["id"],
        "span_kind": data["span_kind"],
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "status": "ACTIVE",
    })
    db["furnishing_spans"][span["id"]] = span
    recompute_project_furnishing_dates(project)
    touch(project)
    return ok_object(span, 201)


# ===========================================================================
# Notice orders
# ===========================================================================


@app.post("/lien/notices")
def notice_create():
    require_roles("CustomerAdmin")
    data = body_json(required=["project_id", "recipient_party_id", "delivery_method"],
                     enums={"delivery_method": DELIVERY_METHODS})
    project = get_or_404("projects", data["project_id"])
    scope_company(project["company_id"])
    party = get_or_404("parties", data["recipient_party_id"])
    # Compliance gates
    if project["research_status"] != "VERIFIED":
        raise ApiError("ERR_PROJECT_NOT_VERIFIED", "Project research is not VERIFIED", 409)
    rule = effective_rule(project)
    if rule is None or data["delivery_method"] not in (rule["allowed_delivery_methods"] if rule else []):
        raise ApiError("ERR_DELIVERY_METHOD_NOT_ALLOWED",
                       "delivery_method is not allowed by the effective rule", 422)
    # Referential consistency
    if party["project_id"] != project["id"]:
        raise ApiError("ERR_PARTY_PROJECT_MISMATCH", "Recipient party belongs to a different project", 422)
    if party["research_status"] != "VERIFIED":
        raise ApiError("ERR_PARTY_NOT_VERIFIED", "Recipient party is not VERIFIED", 409)
    # Deadline arithmetic requires an ACTIVE span
    deadline = prelim_service_deadline(project, rule)
    if deadline is None:
        raise ApiError("ERR_NO_ACTIVE_SPAN", "No ACTIVE furnishing span exists for the project", 409)
    # Fiscal
    fee = notice_fee_cents(party["party_role"], data["delivery_method"])
    company = db["companies"].get(project["company_id"])
    balance = company["prepaid_balance_cents"] if company else 0
    if balance < fee:
        raise ApiError("ERR_INSUFFICIENT_BALANCE", "Company prepaid balance does not cover the notice fee", 402)

    notice = new_entity({
        "project_id": project["id"],
        "recipient_party_id": party["id"],
        "delivery_method": data["delivery_method"],
        "status": "DRAFT",
        "service_deadline": fmt_date(deadline),
        "served_at": None,
        "proof_result": None,
        "proof_url": None,
        "fee_cents": fee,
    })
    db["notices"][notice["id"]] = notice
    if company is not None:
        company["prepaid_balance_cents"] -= fee
        touch(company)
    recount_open_notices(project)
    touch(project)
    recompute_posture(project)
    # A DRAFT notice already past its deadline expires lazily on read; creation
    # itself is allowed.
    return ok_object(notice, 201)


def load_notice_scoped(nid):
    notice = get_or_404("notices", nid)
    project = db["projects"].get(notice["project_id"])
    if project is not None:
        scope_company(project["company_id"])
    return notice


@app.get("/lien/notices/<nid>")
def notice_get(nid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    notice = load_notice_scoped(nid)
    apply_notice_expiry(notice)
    project = db["projects"].get(notice["project_id"])
    if project is not None:
        recount_open_notices(project)
        recompute_posture(project)
    return ok_object(notice)


@app.post("/lien/notices/<nid>/serve")
def notice_serve(nid):
    require_roles("OpsAgent")
    notice = get_or_404("notices", nid)
    apply_notice_expiry(notice)
    data = body_json(required=["served_at"], date_fields=["served_at"])
    if notice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Notice is not in DRAFT", 409)
    project = db["projects"][notice["project_id"]]
    if project["research_status"] != "VERIFIED":
        raise ApiError("ERR_PROJECT_NOT_VERIFIED", "Project research is not VERIFIED", 409)
    deadline = parse_date(notice["service_deadline"]) if notice["service_deadline"] else None
    served = parse_date(data["served_at"])
    if deadline is not None and served > deadline:
        raise ApiError("ERR_NOTICE_DEADLINE_PASSED", "served_at is after the service deadline", 409)
    notice["status"] = "SERVED"
    notice["served_at"] = data["served_at"]
    touch(notice)
    recompute_posture(project)
    return ok_object(notice)


@app.post("/lien/notices/<nid>/proof")
def notice_proof(nid):
    require_roles("OpsAgent")
    notice = get_or_404("notices", nid)
    apply_notice_expiry(notice)
    data = body_json(required=["result"], optional=["proof_url"],
                     enums={"result": PROOF_RESULTS})
    if notice["status"] != "SERVED":
        raise ApiError("ERR_NOTICE_NOT_SERVED", "Proof can only be recorded on a SERVED notice", 409)
    project = db["projects"][notice["project_id"]]
    rule = effective_rule(project)
    result = data["result"]
    refused_ok = bool(rule and rule.get("refused_counts_as_served"))
    if result == "DELIVERED" or (result == "REFUSED" and refused_ok):
        notice["status"] = "PROOF_CONFIRMED"
        notice["proof_result"] = result
        notice["proof_url"] = data.get("proof_url")
        touch(notice)
        recount_open_notices(project)
        touch(project)
        recompute_posture(project)
    else:
        notice["status"] = "DELIVERY_FAILED"
        notice["proof_result"] = result
        notice["proof_url"] = data.get("proof_url")
        touch(notice)
        recompute_posture(project)
    return ok_object(notice)


@app.post("/lien/notices/<nid>/reprepare")
def notice_reprepare(nid):
    require_roles("CustomerAdmin")
    notice = load_notice_scoped(nid)
    apply_notice_expiry(notice)
    if notice["status"] != "DELIVERY_FAILED":
        raise ApiError("ERR_INVALID_STATE", "Notice is not in DELIVERY_FAILED", 409)
    project = db["projects"][notice["project_id"]]
    rule = effective_rule(project)
    notice["status"] = "DRAFT"
    notice["served_at"] = None
    notice["proof_result"] = None
    notice["proof_url"] = None
    notice["service_deadline"] = fmt_date(prelim_service_deadline(project, rule))
    touch(notice)
    return ok_object(notice)


# ===========================================================================
# Lien claims
# ===========================================================================


def open_claim_on_project(project_id):
    for c in db["lien_claims"].values():
        if c["project_id"] == project_id and c["status"] in OPEN_CLAIM_STATUSES:
            return c
    return None


@app.post("/lien/lien-claims")
def claim_create():
    require_roles("CustomerAdmin")
    data = body_json(required=["project_id"])
    project = get_or_404("projects", data["project_id"])
    scope_company(project["company_id"])
    if project["project_type"] in ("STATE_PUBLIC", "FEDERAL_PUBLIC"):
        raise ApiError("ERR_LIEN_NOT_PERMITTED_PUBLIC", "Lien claims are not permitted on public projects", 422)
    if open_claim_on_project(project["id"]) is not None:
        raise ApiError("ERR_OPEN_CLAIM_EXISTS", "An open lien claim already exists on the project", 409)
    claim = new_entity({
        "project_id": project["id"],
        "status": "DRAFT",
        "provisional_amount_cents": provisional_amount(project),
        "final_amount_cents": None,
        "gross_snapshot_cents": None,
        "verified_paid_cents": verified_paid_sum(project["id"]),
        "effective_waiver_cents": 0,
        "waived_to_extras_cents": 0,
        "waived_to_contract_cents": 0,
        "outstanding_cents": None,
        "filed_at": None,
        "filing_window_end": None,
        "foreclosure_deadline": None,
        "locked_rule_id": None,
    })
    eff, w_extras, w_contract = waiver_waterfall(project)
    claim["effective_waiver_cents"] = eff
    claim["waived_to_extras_cents"] = w_extras
    claim["waived_to_contract_cents"] = w_contract
    db["lien_claims"][claim["id"]] = claim
    return ok_object(serialize_claim(claim), 201)


def load_claim_scoped(cid):
    claim = get_or_404("lien_claims", cid)
    project = db["projects"].get(claim["project_id"])
    if project is not None:
        scope_company(project["company_id"])
    return claim


@app.get("/lien/lien-claims/<cid>")
def claim_get(cid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    claim = load_claim_scoped(cid)
    apply_claim_expiry(claim)
    project = db["projects"].get(claim["project_id"])
    if project is not None:
        recompute_posture(project)
    return ok_object(serialize_claim(claim))


@app.post("/lien/lien-claims/<cid>/lock")
def claim_lock(cid):
    require_roles("CustomerAdmin")
    claim = load_claim_scoped(cid)
    apply_claim_expiry(claim)
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Claim is not in DRAFT", 409)
    project = db["projects"][claim["project_id"]]
    rule = effective_rule(project)
    if rule is not None and rule["prelim_notice_required"]:
        confirmed = any(n["project_id"] == project["id"] and n["status"] == "PROOF_CONFIRMED"
                        for n in db["notices"].values())
        if not confirmed:
            raise ApiError("ERR_PRELIM_NOTICE_REQUIRED",
                           "A PROOF_CONFIRMED prelim notice is required before locking", 409)
    if rule is None:
        raise ApiError("ERR_ZERO_CLAIM_AMOUNT", "No effective rule; cannot compute a claim amount", 422)
    final = final_amount(project, rule)
    if final <= 0:
        raise ApiError("ERR_ZERO_CLAIM_AMOUNT", "Lock would produce final_amount_cents <= 0", 422)
    last, _ = last_furnishing_date(project, rule)
    claim["final_amount_cents"] = final
    claim["gross_snapshot_cents"] = gross_claimable(project, rule)
    claim["locked_rule_id"] = rule["id"]
    claim["filing_window_end"] = fmt_date(add_calendar_days(last, int(rule["filing_window_days"]))) \
        if last is not None else None
    eff, w_extras, w_contract = waiver_waterfall(project)
    claim["effective_waiver_cents"] = eff
    claim["waived_to_extras_cents"] = w_extras
    claim["waived_to_contract_cents"] = w_contract
    claim["verified_paid_cents"] = verified_paid_sum(project["id"])
    claim["outstanding_cents"] = outstanding_for_claim(claim)
    claim["status"] = "AMOUNT_LOCKED"
    touch(claim)
    return ok_object(serialize_claim(claim))


@app.post("/lien/lien-claims/<cid>/unlock")
def claim_unlock(cid):
    require_roles("CustomerAdmin")
    claim = load_claim_scoped(cid)
    if claim["status"] != "AMOUNT_LOCKED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not in AMOUNT_LOCKED", 409)
    claim["final_amount_cents"] = None
    claim["gross_snapshot_cents"] = None
    claim["filing_window_end"] = None
    claim["locked_rule_id"] = None
    claim["outstanding_cents"] = None
    claim["status"] = "DRAFT"
    project = db["projects"][claim["project_id"]]
    claim["provisional_amount_cents"] = provisional_amount(project)
    touch(claim)
    return ok_object(serialize_claim(claim))


@app.post("/lien/lien-claims/<cid>/file")
def claim_file(cid):
    require_roles("OpsAgent")
    claim = get_or_404("lien_claims", cid)
    apply_claim_expiry(claim)
    data = body_json(required=["filed_at"], date_fields=["filed_at"])
    if claim["status"] != "AMOUNT_LOCKED":
        raise ApiError("ERR_CLAIM_NOT_LOCKED", "Claim is not in AMOUNT_LOCKED", 409)
    filed = parse_date(data["filed_at"])
    window_end = parse_date(claim["filing_window_end"]) if claim["filing_window_end"] else None
    if window_end is not None and filed > window_end:
        raise ApiError("ERR_FILING_WINDOW_CLOSED", "filed_at is after the filing window end", 409)
    rule = db["jurisdiction_rules"].get(claim["locked_rule_id"])
    claim["filed_at"] = data["filed_at"]
    claim["status"] = "FILED"
    claim["foreclosure_deadline"] = fmt_date(add_calendar_days(filed, int(rule["foreclosure_deadline_days"]))) \
        if rule is not None else None
    claim["outstanding_cents"] = outstanding_for_claim(claim)
    touch(claim)
    project = db["projects"][claim["project_id"]]
    project["open_lien_count"] += 1
    touch(project)
    recompute_posture(project)
    return ok_object(serialize_claim(claim))


@app.post("/lien/lien-claims/<cid>/release")
def claim_release(cid):
    require_roles("CustomerAdmin")
    claim = load_claim_scoped(cid)
    apply_claim_expiry(claim)
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not in FILED", 409)
    claim_exit_filed(claim, "RELEASED", "MOOT_RELEASED")
    return ok_object(serialize_claim(claim))


@app.get("/lien/lien-claims/<cid>/payments")
def claim_payments(cid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    load_claim_scoped(cid)
    return paginate([p for p in db["payments"].values() if p.get("lien_claim_id") == cid])


@app.get("/lien/lien-claims/<cid>/bonding-requests")
def claim_bonding_requests(cid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    load_claim_scoped(cid)
    return paginate([b for b in db["bonding_requests"].values() if b["lien_claim_id"] == cid])


@app.get("/lien/lien-claims/<cid>/foreclosure-referrals")
def claim_referrals(cid):
    require_roles("PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel")
    load_claim_scoped(cid)
    return paginate([r for r in db["foreclosure_referrals"].values() if r["lien_claim_id"] == cid])


# ===========================================================================
# Waivers
# ===========================================================================


def periods_overlap_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; adjacency allowed."""
    return a_start < b_end and b_start < a_end


@app.post("/lien/waivers")
def waiver_create():
    require_roles("CustomerAdmin")
    data = body_json(required=["project_id", "waiver_type", "amount_cents", "period_start", "period_end"],
                     enums={"waiver_type": WAIVER_TYPES},
                     int_fields=["amount_cents"],
                     date_fields=["period_start", "period_end"])
    project = get_or_404("projects", data["project_id"])
    scope_company(project["company_id"])
    ps = parse_date(data["period_start"])
    pe = parse_date(data["period_end"])
    if pe < ps:
        raise ApiError("ERR_VALIDATION", "period_end must be >= period_start", 400)
    for w in db["waivers"].values():
        if w["project_id"] == project["id"] and w["status"] != "VOIDED":
            if periods_overlap_half_open(ps, pe, parse_date(w["period_start"]), parse_date(w["period_end"])):
                raise ApiError("ERR_WAIVER_PERIOD_OVERLAP",
                               "Waiver period overlaps an existing non-VOIDED waiver", 409)
    if data["amount_cents"] <= 0:
        raise ApiError("ERR_AMOUNT_MUST_BE_POSITIVE", "amount_cents must be > 0", 422)
    waiver = new_entity({
        "project_id": project["id"],
        "waiver_type": data["waiver_type"],
        "amount_cents": data["amount_cents"],
        "period_start": data["period_start"],
        "period_end": data["period_end"],
        "status": "RECEIVED",
    })
    db["waivers"][waiver["id"]] = waiver
    # Recompute open claim (provisional counts non-VOIDED waivers)
    claim = open_claim_on_project(project["id"])
    if claim is not None and claim["status"] in ("DRAFT", "AMOUNT_LOCKED"):
        recompute_claim_amounts(claim)
    return ok_object(waiver, 201)


def load_waiver_scoped(wid):
    waiver = get_or_404("waivers", wid)
    project = db["projects"].get(waiver["project_id"])
    if project is not None:
        scope_company(project["company_id"])
    return waiver


@app.post("/lien/waivers/<wid>/apply")
def waiver_apply(wid):
    require_roles("OpsAgent")
    waiver = get_or_404("waivers", wid)
    if waiver["status"] != "RECEIVED":
        raise ApiError("ERR_WAIVER_NOT_RECEIVED", "Waiver is not in RECEIVED", 409)
    waiver["status"] = "APPLIED"
    touch(waiver)
    claim = open_claim_on_project(waiver["project_id"])
    if claim is not None and claim["status"] in ("DRAFT", "AMOUNT_LOCKED"):
        recompute_claim_amounts(claim)
    return ok_object(waiver)


@app.post("/lien/waivers/<wid>/void")
def waiver_void(wid):
    require_roles("CustomerAdmin")
    waiver = load_waiver_scoped(wid)
    if waiver["status"] not in ("RECEIVED", "APPLIED"):
        raise ApiError("ERR_INVALID_STATE", "Waiver cannot be voided from its current state", 409)
    waiver["status"] = "VOIDED"
    touch(waiver)
    claim = open_claim_on_project(waiver["project_id"])
    if claim is not None and claim["status"] in ("DRAFT", "AMOUNT_LOCKED"):
        recompute_claim_amounts(claim)
    return ok_object(waiver)


# ===========================================================================
# Payments
# ===========================================================================


@app.post("/lien/payments")
def payment_create():
    require_roles("CustomerAdmin")
    data = body_json(required=["project_id", "amount_cents", "received_at"],
                     optional=["lien_claim_id"],
                     int_fields=["amount_cents"],
                     date_fields=["received_at"])
    project = get_or_404("projects", data["project_id"])
    scope_company(project["company_id"])
    claim_id = data.get("lien_claim_id")
    if claim_id is not None:
        claim = get_or_404("lien_claims", claim_id)
        if claim["project_id"] != project["id"]:
            raise ApiError("ERR_PARTY_PROJECT_MISMATCH",
                           "lien_claim_id belongs to a different project", 422)
    if data["amount_cents"] <= 0:
        raise ApiError("ERR_AMOUNT_MUST_BE_POSITIVE", "amount_cents must be > 0", 422)
    payment = new_entity({
        "project_id": project["id"],
        "lien_claim_id": claim_id,
        "amount_cents": data["amount_cents"],
        "received_at": data["received_at"],
        "status": "PENDING",
    })
    db["payments"][payment["id"]] = payment
    claim = open_claim_on_project(project["id"])
    if claim is not None and claim["status"] == "DRAFT":
        recompute_claim_amounts(claim)
    return ok_object(payment, 201)


@app.post("/lien/payments/<pid>/verify")
def payment_verify(pid):
    require_roles("OpsAgent")
    payment = get_or_404("payments", pid)
    if payment["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Payment is not PENDING", 409)
    payment["status"] = "VERIFIED"
    touch(payment)
    claim = open_claim_on_project(payment["project_id"])
    if claim is not None:
        if claim["status"] in ("DRAFT", "AMOUNT_LOCKED"):
            recompute_claim_amounts(claim)
        elif claim["status"] == "FILED":
            claim["outstanding_cents"] = outstanding_for_claim(claim)
            touch(claim)
            if claim["outstanding_cents"] == 0:
                claim_exit_filed(claim, "RELEASED", "MOOT_RELEASED")
    return ok_object(payment)


# ===========================================================================
# Bonding requests
# ===========================================================================


def open_bonding_on_claim(claim_id):
    for b in db["bonding_requests"].values():
        if b["lien_claim_id"] == claim_id and b["status"] == "REQUESTED":
            return b
    return None


@app.post("/lien/bonding-requests")
def bonding_create():
    require_roles("CustomerAdmin")
    data = body_json(required=["lien_claim_id", "surety_party_id"])
    claim = get_or_404("lien_claims", data["lien_claim_id"])
    project = db["projects"][claim["project_id"]]
    scope_company(project["company_id"])
    surety = get_or_404("parties", data["surety_party_id"])
    apply_claim_expiry(claim)
    if claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_NOT_FILED", "Claim is not FILED", 409)
    if surety["project_id"] != project["id"]:
        raise ApiError("ERR_PARTY_PROJECT_MISMATCH", "Surety party belongs to a different project", 422)
    if surety["party_role"] != "SURETY" or surety["research_status"] != "VERIFIED":
        raise ApiError("ERR_SURETY_NOT_VERIFIED", "Surety party is not a VERIFIED SURETY", 409)
    if open_bonding_on_claim(claim["id"]) is not None:
        raise ApiError("ERR_OPEN_BONDING_EXISTS", "A REQUESTED bonding request already exists for the claim", 409)
    rule = db["jurisdiction_rules"].get(claim["locked_rule_id"])
    amount = bond_amount(claim, rule)
    bonding = new_entity({
        "lien_claim_id": claim["id"],
        "surety_party_id": surety["id"],
        "bond_amount_cents": amount,
        "status": "REQUESTED",
        "recorded_at": None,
    })
    db["bonding_requests"][bonding["id"]] = bonding
    return ok_object(bonding, 201)


def load_bonding_scoped(bid):
    bonding = get_or_404("bonding_requests", bid)
    claim = db["lien_claims"].get(bonding["lien_claim_id"])
    if claim is not None:
        project = db["projects"].get(claim["project_id"])
        if project is not None:
            scope_company(project["company_id"])
    return bonding


@app.post("/lien/bonding-requests/<bid>/record")
def bonding_record(bid):
    require_roles("OpsAgent")
    bonding = get_or_404("bonding_requests", bid)
    data = body_json(required=["recorded_at"], date_fields=["recorded_at"])
    claim = db["lien_claims"].get(bonding["lien_claim_id"])
    if claim is not None:
        apply_claim_expiry(claim)
    if bonding["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Bonding request is not REQUESTED", 409)
    if claim is None or claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_NOT_FILED", "Linked claim is not FILED", 409)
    bonding["status"] = "BOND_RECORDED"
    bonding["recorded_at"] = data["recorded_at"]
    touch(bonding)
    claim_exit_filed(claim, "BONDED_OFF", "MOOT_BONDED")
    return ok_object(bonding)


@app.post("/lien/bonding-requests/<bid>/reject")
def bonding_reject(bid):
    require_roles("OpsAgent")
    bonding = get_or_404("bonding_requests", bid)
    if bonding["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Bonding request is not REQUESTED", 409)
    bonding["status"] = "REJECTED"
    touch(bonding)
    return ok_object(bonding)


# ===========================================================================
# Foreclosure referrals
# ===========================================================================


def open_referral_on_claim(claim_id):
    for r in db["foreclosure_referrals"].values():
        if r["lien_claim_id"] == claim_id and r["status"] in OPEN_REFERRAL_STATUSES:
            return r
    return None


@app.post("/lien/foreclosure-referrals")
def referral_create():
    require_roles("CustomerAdmin")
    data = body_json(required=["lien_claim_id", "counsel_name"])
    claim = get_or_404("lien_claims", data["lien_claim_id"])
    project = db["projects"][claim["project_id"]]
    scope_company(project["company_id"])
    apply_claim_expiry(claim)
    if claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_NOT_FILED", "Claim is not FILED", 409)
    deadline = parse_date(claim["foreclosure_deadline"]) if claim["foreclosure_deadline"] else None
    from core import clock_date as _cd
    if deadline is not None and _cd() > deadline:
        raise ApiError("ERR_FORECLOSURE_DEADLINE_PASSED",
                       "The claim's foreclosure deadline has passed", 409)
    if open_referral_on_claim(claim["id"]) is not None:
        raise ApiError("ERR_OPEN_REFERRAL_EXISTS", "An open referral already exists for the claim", 409)
    referral = new_entity({
        "lien_claim_id": claim["id"],
        "counsel_name": data["counsel_name"],
        "status": "DRAFT",
        "suit_filed_at": None,
        "cancel_reason": None,
    })
    db["foreclosure_referrals"][referral["id"]] = referral
    return ok_object(referral, 201)


def load_referral_scoped(rid):
    referral = get_or_404("foreclosure_referrals", rid)
    claim = db["lien_claims"].get(referral["lien_claim_id"])
    if claim is not None:
        project = db["projects"].get(claim["project_id"])
        if project is not None:
            scope_company(project["company_id"])
    return referral


@app.post("/lien/foreclosure-referrals/<rid>/send")
def referral_send(rid):
    require_roles("OpsAgent")
    referral = get_or_404("foreclosure_referrals", rid)
    data = body_json(required=[], optional=["counsel_name"])
    claim = db["lien_claims"].get(referral["lien_claim_id"])
    if claim is not None:
        apply_claim_expiry(claim)
    from core import clock_date as _cd
    if referral["status"] == "DRAFT":
        deadline = parse_date(claim["foreclosure_deadline"]) if claim and claim["foreclosure_deadline"] else None
        if deadline is not None and _cd() > deadline:
            raise ApiError("ERR_FORECLOSURE_DEADLINE_PASSED",
                           "The claim's foreclosure deadline has passed", 409)
        referral["status"] = "SENT"
        touch(referral)
        return ok_object(referral)
    if referral["status"] == "DECLINED":
        new_counsel = data.get("counsel_name")
        if not new_counsel or new_counsel == referral["counsel_name"]:
            raise ApiError("ERR_VALIDATION",
                           "A new counsel_name differing from the declined counsel is required", 400)
        deadline = parse_date(claim["foreclosure_deadline"]) if claim and claim["foreclosure_deadline"] else None
        if deadline is not None and _cd() > deadline:
            raise ApiError("ERR_FORECLOSURE_DEADLINE_PASSED",
                           "The claim's foreclosure deadline has passed", 409)
        referral["counsel_name"] = new_counsel
        referral["status"] = "SENT"
        touch(referral)
        return ok_object(referral)
    raise ApiError("ERR_INVALID_STATE", "Referral cannot be sent from its current state", 409)


@app.post("/lien/foreclosure-referrals/<rid>/respond")
def referral_respond(rid):
    require_roles("Counsel")
    referral = get_or_404("foreclosure_referrals", rid)
    data = body_json(required=["outcome"], enums={"outcome": REFERRAL_OUTCOMES})
    if referral["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", "Referral is not SENT", 409)
    referral["status"] = data["outcome"]
    touch(referral)
    return ok_object(referral)


@app.post("/lien/foreclosure-referrals/<rid>/mark-suit-filed")
def referral_mark_suit_filed(rid):
    require_roles("Counsel")
    referral = get_or_404("foreclosure_referrals", rid)
    data = body_json(required=["suit_filed_at"], date_fields=["suit_filed_at"])
    if referral["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "Referral is not ACCEPTED", 409)
    claim = db["lien_claims"].get(referral["lien_claim_id"])
    deadline = parse_date(claim["foreclosure_deadline"]) if claim and claim["foreclosure_deadline"] else None
    suit_date = parse_date(data["suit_filed_at"])
    if deadline is not None and suit_date > deadline:
        raise ApiError("ERR_FORECLOSURE_DEADLINE_PASSED",
                       "suit_filed_at is after the claim's foreclosure deadline", 409)
    referral["status"] = "SUIT_FILED"
    referral["suit_filed_at"] = data["suit_filed_at"]
    touch(referral)
    if claim is not None and claim["status"] == "FILED":
        claim["status"] = "FORECLOSED"
        touch(claim)
        project = db["projects"].get(claim["project_id"])
        if project is not None:
            touch(project)
            recompute_posture(project)
    return ok_object(referral)


# ===========================================================================
# Stop notices
# ===========================================================================


def closed_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval overlap; sharing an endpoint counts."""
    return a_start <= b_end and b_start <= a_end


@app.post("/lien/stop-notices")
def stop_notice_create():
    require_roles("CustomerAdmin")
    data = body_json(required=["project_id", "amount_cents", "coverage_start", "coverage_end"],
                     int_fields=["amount_cents"],
                     date_fields=["coverage_start", "coverage_end"])
    project = get_or_404("projects", data["project_id"])
    scope_company(project["company_id"])
    cs = parse_date(data["coverage_start"])
    ce = parse_date(data["coverage_end"])
    if ce < cs:
        raise ApiError("ERR_VALIDATION", "coverage_end must be >= coverage_start", 400)
    if project["project_type"] != "STATE_PUBLIC":
        raise ApiError("ERR_STOP_NOTICE_NOT_PERMITTED", "Stop notices are only permitted on STATE_PUBLIC projects", 422)
    for s in db["stop_notices"].values():
        if s["project_id"] == project["id"] and s["status"] == "SERVED":
            if closed_overlap(cs, ce, parse_date(s["coverage_start"]), parse_date(s["coverage_end"])):
                raise ApiError("ERR_STOP_NOTICE_OVERLAP",
                               "Coverage overlaps a SERVED stop notice on the project", 409)
    rule = effective_rule(project)
    last, _ = last_furnishing_date(project, rule)
    if last is None:
        raise ApiError("ERR_NO_ACTIVE_SPAN", "No ACTIVE furnishing span exists for the project", 409)
    if data["amount_cents"] <= 0:
        raise ApiError("ERR_AMOUNT_MUST_BE_POSITIVE", "amount_cents must be > 0", 422)
    stop = new_entity({
        "project_id": project["id"],
        "amount_cents": data["amount_cents"],
        "coverage_start": data["coverage_start"],
        "coverage_end": data["coverage_end"],
        "status": "DRAFT",
        "served_at": None,
    })
    db["stop_notices"][stop["id"]] = stop
    return ok_object(stop, 201)


def load_stop_scoped(sid):
    stop = get_or_404("stop_notices", sid)
    project = db["projects"].get(stop["project_id"])
    if project is not None:
        scope_company(project["company_id"])
    return stop


@app.post("/lien/stop-notices/<sid>/serve")
def stop_notice_serve(sid):
    require_roles("OpsAgent")
    stop = get_or_404("stop_notices", sid)
    apply_stop_notice_expiry(stop)
    data = body_json(required=["served_at"], date_fields=["served_at"])
    if stop["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Stop notice is not in DRAFT", 409)
    project = db["projects"][stop["project_id"]]
    rule = effective_rule(project)
    last, _ = last_furnishing_date(project, rule)
    if last is None or rule is None:
        raise ApiError("ERR_NO_ACTIVE_SPAN", "No ACTIVE furnishing span exists for the project", 409)
    deadline = add_calendar_days(last, int(rule["stop_notice_days"]))
    served = parse_date(data["served_at"])
    if served > deadline:
        raise ApiError("ERR_STOP_NOTICE_DEADLINE_PASSED", "served_at is after the stop-notice deadline", 409)
    # Overlap re-checked at serve against SERVED stop notices
    for s in db["stop_notices"].values():
        if s["id"] != stop["id"] and s["project_id"] == project["id"] and s["status"] == "SERVED":
            if closed_overlap(parse_date(stop["coverage_start"]), parse_date(stop["coverage_end"]),
                              parse_date(s["coverage_start"]), parse_date(s["coverage_end"])):
                raise ApiError("ERR_STOP_NOTICE_OVERLAP",
                               "Coverage overlaps a SERVED stop notice on the project", 409)
    stop["status"] = "SERVED"
    stop["served_at"] = data["served_at"]
    touch(stop)
    touch(project)
    recompute_posture(project)
    return ok_object(stop)


@app.post("/lien/stop-notices/<sid>/release")
def stop_notice_release(sid):
    require_roles("OpsAgent")
    stop = get_or_404("stop_notices", sid)
    if stop["status"] != "SERVED":
        raise ApiError("ERR_INVALID_STATE", "Stop notice is not SERVED", 409)
    stop["status"] = "RELEASED"
    touch(stop)
    project = db["projects"].get(stop["project_id"])
    if project is not None:
        touch(project)
        recompute_posture(project)
    return ok_object(stop)


# ===========================================================================
# Bond claims
# ===========================================================================


@app.post("/lien/bond-claims")
def bond_claim_create():
    require_roles("CustomerAdmin")
    data = body_json(required=["project_id", "surety_party_id", "amount_cents"],
                     int_fields=["amount_cents"])
    project = get_or_404("projects", data["project_id"])
    scope_company(project["company_id"])
    surety = get_or_404("parties", data["surety_party_id"])
    if project["project_type"] not in ("STATE_PUBLIC", "FEDERAL_PUBLIC"):
        raise ApiError("ERR_BOND_CLAIM_NOT_PERMITTED", "Bond claims are only permitted on public projects", 422)
    if surety["project_id"] != project["id"]:
        raise ApiError("ERR_PARTY_PROJECT_MISMATCH", "Surety party belongs to a different project", 422)
    if surety["party_role"] != "SURETY" or surety["research_status"] != "VERIFIED":
        raise ApiError("ERR_SURETY_NOT_VERIFIED", "Surety party is not a VERIFIED SURETY", 409)
    if data["amount_cents"] <= 0:
        raise ApiError("ERR_AMOUNT_MUST_BE_POSITIVE", "amount_cents must be > 0", 422)
    bond = new_entity({
        "project_id": project["id"],
        "surety_party_id": surety["id"],
        "amount_cents": data["amount_cents"],
        "status": "DRAFT",
        "submitted_at": None,
        "resolve_outcome": None,
    })
    db["bond_claims"][bond["id"]] = bond
    return ok_object(bond, 201)


def load_bond_scoped(bid):
    bond = get_or_404("bond_claims", bid)
    project = db["projects"].get(bond["project_id"])
    if project is not None:
        scope_company(project["company_id"])
    return bond


@app.post("/lien/bond-claims/<bid>/submit")
def bond_claim_submit(bid):
    require_roles("OpsAgent")
    bond = get_or_404("bond_claims", bid)
    apply_bond_claim_expiry(bond)
    data = body_json(required=["submitted_at"], date_fields=["submitted_at"])
    if bond["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Bond claim is not in DRAFT", 409)
    project = db["projects"][bond["project_id"]]
    rule = effective_rule(project)
    last, _ = last_furnishing_date(project, rule)
    if last is None or rule is None:
        raise ApiError("ERR_NO_ACTIVE_SPAN", "No ACTIVE furnishing span exists for the project", 409)
    deadline = add_calendar_days(last, int(rule["bond_claim_days"]))
    submitted = parse_date(data["submitted_at"])
    if submitted > deadline:
        raise ApiError("ERR_BOND_CLAIM_DEADLINE_PASSED", "submitted_at is after the bond-claim deadline", 409)
    bond["status"] = "SUBMITTED"
    bond["submitted_at"] = data["submitted_at"]
    touch(bond)
    touch(project)
    recompute_posture(project)
    return ok_object(bond)


@app.post("/lien/bond-claims/<bid>/resolve")
def bond_claim_resolve(bid):
    require_roles("OpsAgent")
    bond = get_or_404("bond_claims", bid)
    data = body_json(required=["outcome"], enums={"outcome": BOND_RESOLVE_OUTCOMES})
    if bond["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Bond claim is not SUBMITTED", 409)
    bond["status"] = data["outcome"]
    bond["resolve_outcome"] = data["outcome"]
    touch(bond)
    project = db["projects"].get(bond["project_id"])
    if project is not None:
        touch(project)
        recompute_posture(project)
    return ok_object(bond)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
