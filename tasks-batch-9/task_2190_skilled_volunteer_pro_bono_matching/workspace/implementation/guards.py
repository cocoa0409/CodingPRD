"""The rejection-precedence ladder of PRD 2.12.

Each guard is named for its global priority (`g07_...` is priority 7).  Route
handlers call the guards in ascending priority order and the first failure
short-circuits the request, which is exactly the ordering the PRD fixes.  A
guard is never inlined out of order.
"""
from datetime import timedelta
from decimal import Decimal

from flask import g, request

import calc
import config as C
import store as S
from calc import dec, rnd
from errors import ApiError

ROLE_REGISTRY = {}

TIER_RANK = {"STANDARD": 0, "ELEVATED": 1, "RESTRICTED": 2}


# --------------------------------------------------------------------------- #
# routing / RBAC registration
# --------------------------------------------------------------------------- #
def route(bp, rule, methods, roles, name=None):
    """Register a view with its authorized roles (priority 2 data)."""

    def decorator(fn):
        endpoint = name or fn.__name__
        bp.add_url_rule(rule, endpoint=endpoint, view_func=fn, methods=methods)
        ROLE_REGISTRY["%s.%s" % (bp.name, endpoint)] = tuple(roles)
        return fn

    return decorator


def user_id():
    return g.user_id


def role():
    return g.user_role


# --------------------------------------------------------------------------- #
# priority 1 + 2
# --------------------------------------------------------------------------- #
def g01_auth_headers():
    uid = request.headers.get("X-User-ID")
    urole = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if urole is None or not str(urole).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    g.user_id = str(uid).strip()
    g.user_role = str(urole).strip()


def g02_role_permitted(allowed):
    if g.user_role not in C.ALL_ROLES:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if allowed is not None and g.user_role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


# --------------------------------------------------------------------------- #
# priorities 3-13: path existence
# --------------------------------------------------------------------------- #
def _need(table, row_id, error_id):
    row = S.get(table, row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def g03_partner(partner_id):
    return _need("partner_orgs", partner_id, "ERR_PARTNER_ORG_NOT_FOUND")


def g04_cycle(cycle_id):
    return _need("program_cycles", cycle_id, "ERR_PROGRAM_CYCLE_NOT_FOUND")


def g05_request(request_id):
    return _need("project_requests", request_id, "ERR_PROJECT_REQUEST_NOT_FOUND")


def g06_scope(scope_id):
    return _need("scope_definitions", scope_id, "ERR_SCOPE_DEFINITION_NOT_FOUND")


def g07_volunteer(volunteer_id):
    return _need("volunteers", volunteer_id, "ERR_VOLUNTEER_NOT_FOUND")


def g08_offer(offer_id):
    return _need("match_offers", offer_id, "ERR_MATCH_OFFER_NOT_FOUND")


def g09_engagement(engagement_id):
    return _need("engagements", engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")


def g10_agreement(agreement_id):
    return _need("agreements", agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def g11_milestone(milestone_id):
    return _need("milestones", milestone_id, "ERR_MILESTONE_NOT_FOUND")


def g12_scope_change(scr_id):
    return _need("scope_change_requests", scr_id, "ERR_SCOPE_CHANGE_NOT_FOUND")


def g13_review(review_id):
    return _need("quality_reviews", review_id, "ERR_QUALITY_REVIEW_NOT_FOUND")


# --------------------------------------------------------------------------- #
# priority 14: body foreign keys
# --------------------------------------------------------------------------- #
def g14_body_partner(partner_id):
    return _need("partner_orgs", partner_id, "ERR_PARTNER_ORG_NOT_FOUND")


def g14_body_cycle(cycle_id):
    return _need("program_cycles", cycle_id, "ERR_PROGRAM_CYCLE_NOT_FOUND")


def g14_body_scope(scope_id):
    return _need("scope_definitions", scope_id, "ERR_SCOPE_DEFINITION_NOT_FOUND")


def g14_deliverable_ids(scope_id, body):
    """Every deliverable_id inside deliverable_scores names a pinned deliverable."""
    entries = body.get("deliverable_scores")
    if not isinstance(entries, list):
        return
    known = {d["id"] for d in S.where("deliverables", scope_definition_id=scope_id)}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        did = entry.get("deliverable_id")
        if isinstance(did, str) and did not in known:
            raise ApiError("ERR_DELIVERABLE_NOT_FOUND")


# --------------------------------------------------------------------------- #
# priority 15: ownership for entity-backed roles
# --------------------------------------------------------------------------- #
def g15_owns_partner(partner_org_id):
    if role() == C.ROLE_PARTNER_CONTACT and user_id() != partner_org_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def g15_owns_volunteer(volunteer_id):
    if role() == C.ROLE_VOLUNTEER and user_id() != volunteer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def g15_owns_engagement(engagement):
    g15_owns_volunteer(engagement["volunteer_id"])
    req = S.get("project_requests", engagement["project_request_id"])
    if req is not None:
        g15_owns_partner(req["partner_org_id"])


# --------------------------------------------------------------------------- #
# priority 16: segregation of duties
# --------------------------------------------------------------------------- #
def g16_review_open(engagement):
    scope = S.get("scope_definitions", engagement["scope_definition_id"])
    if scope is not None and scope["authored_by_user_id"] == user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    prior = S.where("quality_reviews", engagement_id=engagement["id"])
    if prior and any(r["reviewer_user_id"] != user_id() for r in prior):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def g16_review_act(review, engagement):
    scope = S.get("scope_definitions", engagement["scope_definition_id"])
    if scope is not None and scope["authored_by_user_id"] == user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if review["reviewer_user_id"] != user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


# --------------------------------------------------------------------------- #
# priority 17: input schema
# --------------------------------------------------------------------------- #
def body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Body must be a JSON object")
    return data


def _missing(payload, name, required, default):
    if name not in payload or payload.get(name) is None:
        if required:
            raise ApiError("ERR_VALIDATION", "Missing field: %s" % name)
        return True, default
    return False, None


def v_str(payload, name, required=True, min_len=1, max_len=None, default=None,
          charset=None):
    absent, fallback = _missing(payload, name, required, default)
    if absent:
        return fallback
    value = payload[name]
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "%s must be a string" % name)
    if len(value) < min_len:
        raise ApiError("ERR_VALIDATION", "%s is too short" % name)
    if max_len is not None and len(value) > max_len:
        raise ApiError("ERR_VALIDATION", "%s is too long" % name)
    if charset is not None and any(ch not in charset for ch in value):
        raise ApiError("ERR_VALIDATION", "%s has invalid characters" % name)
    return value


def v_enum(payload, name, allowed, required=True, default=None):
    absent, fallback = _missing(payload, name, required, default)
    if absent:
        return fallback
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_VALIDATION", "%s must be one of %s" % (name, list(allowed)))
    return value


def v_num(payload, name, required=True, minimum=None, maximum=None,
          exclusive_min=None, places=2, default=None):
    absent, fallback = _missing(payload, name, required, default)
    if absent:
        return fallback
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", "%s must be a number" % name)
    number = dec(value)
    if minimum is not None and number < dec(minimum):
        raise ApiError("ERR_VALIDATION", "%s below minimum" % name)
    if exclusive_min is not None and number <= dec(exclusive_min):
        raise ApiError("ERR_VALIDATION", "%s must be greater than %s" % (name, exclusive_min))
    if maximum is not None and number > dec(maximum):
        raise ApiError("ERR_VALIDATION", "%s above maximum" % name)
    return rnd(number, places)


def v_int(payload, name, required=True, minimum=None, maximum=None, default=None):
    absent, fallback = _missing(payload, name, required, default)
    if absent:
        return fallback
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "%s below minimum" % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s above maximum" % name)
    return value


def v_bool(payload, name, required=True, default=None):
    absent, fallback = _missing(payload, name, required, default)
    if absent:
        return fallback
    value = payload[name]
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", "%s must be a boolean" % name)
    return value


def v_dt(payload, name, required=True, default=None):
    absent, fallback = _missing(payload, name, required, default)
    if absent:
        return fallback
    value = payload[name]
    parsed = S.parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        raise ApiError("ERR_VALIDATION", "%s must be an ISO 8601 UTC datetime" % name)
    return parsed


def v_id(payload, name, required=True, default=None):
    absent, fallback = _missing(payload, name, required, default)
    if absent:
        return fallback
    value = payload[name]
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_VALIDATION", "%s must be an identifier string" % name)
    return value


# --------------------------------------------------------------------------- #
# priority 19
# --------------------------------------------------------------------------- #
def g19_positive(value, label="hours"):
    if value is not None and dec(value) == 0:
        raise ApiError("ERR_ZERO_HOURS_NOT_ALLOWED", "%s must be strictly positive" % label)


# --------------------------------------------------------------------------- #
# priorities 20-28: state from-sets
# --------------------------------------------------------------------------- #
def g20_request_state(req, allowed):
    if req["status"] not in allowed:
        raise ApiError("ERR_INVALID_REQUEST_STATE")


def g21_scope_draft(scope):
    if scope["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SCOPE_STATE")


def g22_offer_open(offer):
    if offer["status"] != "OFFERED":
        raise ApiError("ERR_OFFER_NOT_OPEN")


def g23_work_state(engagement, allowed):
    if engagement["work_status"] not in allowed:
        raise ApiError("ERR_INVALID_WORK_STATE")


def g24_valuation_stage(engagement):
    """Returns the stage this post reaches, or refuses the post."""
    if engagement["valuation_status"] == "RESTATED":
        raise ApiError("ERR_INVALID_VALUATION_STATE")
    work = engagement["work_status"]
    if work == "HANDED_OFF":
        return "FINAL"
    if work in ("IN_PROGRESS", "SUBMITTED"):
        approved = [
            l
            for l in S.where("time_logs", engagement_id=engagement["id"])
            if l["approved"]
        ]
        if not approved:
            raise ApiError("ERR_INVALID_VALUATION_STATE")
        return "PROVISIONAL"
    raise ApiError("ERR_INVALID_VALUATION_STATE")


def g25_agreement_state(agreement, allowed):
    if agreement["status"] not in allowed:
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")


def g26_milestone_scheduled(milestone):
    if milestone["checkin_status"] != "SCHEDULED":
        raise ApiError("ERR_MILESTONE_NOT_SCHEDULED")


def g27_review_state(review, expected):
    if review["status"] != expected:
        raise ApiError("ERR_REVIEW_NOT_SCORED")


def g28_scope_change_pending(scr):
    if scr["status"] != "PENDING":
        raise ApiError("ERR_SCOPE_CHANGE_NOT_PENDING")


# --------------------------------------------------------------------------- #
# priorities 29-30: stale-version guards
# --------------------------------------------------------------------------- #
def g29_request_version(req, expected):
    if int(expected) != int(req["version"]):
        raise ApiError("ERR_STALE_PROJECT_REQUEST_VERSION")


def g30_engagement_version(engagement, expected):
    if int(expected) != int(engagement["version"]):
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION")


# --------------------------------------------------------------------------- #
# priorities 31-38
# --------------------------------------------------------------------------- #
def g31_partner_not_suspended(partner):
    if partner["status"] == "SUSPENDED":
        raise ApiError("ERR_PARTNER_SUSPENDED")


def g31_partner_active(partner):
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_SUSPENDED")


def g32_credential_verified(volunteer):
    if volunteer["credential_verified_at"] is None:
        raise ApiError("ERR_CREDENTIAL_NOT_VERIFIED")


def g33_volunteer_active(volunteer):
    if volunteer["status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_NOT_ACTIVE")


def g34_attestation(scope, attested, certificate_ref):
    if attested is not True:
        raise ApiError("ERR_CONFIDENTIALITY_ATTESTATION_MISSING")
    if scope is not None and scope["confidentiality_tier"] == "RESTRICTED":
        if not certificate_ref or not str(certificate_ref).strip():
            raise ApiError("ERR_CONFIDENTIALITY_ATTESTATION_MISSING")


def g35_ip_terms(agreement, scope):
    if agreement is None or scope is None:
        raise ApiError("ERR_IP_TERMS_MISMATCH")
    if agreement["ip_disposition"] != scope["ip_disposition"]:
        raise ApiError("ERR_IP_TERMS_MISMATCH")
    if TIER_RANK[agreement["confidentiality_tier"]] < TIER_RANK[scope["confidentiality_tier"]]:
        raise ApiError("ERR_IP_TERMS_MISMATCH")


def governing_agreement(engagement_id):
    """The active terms document: newest non-voided, else newest of all."""
    rows = S.where("agreements", engagement_id=engagement_id)
    live = [r for r in rows if r["status"] != "VOIDED"]
    pool = live or rows
    if not pool:
        return None
    return pool[-1]


def g36_agreement_executed(engagement):
    agreement = governing_agreement(engagement["id"])
    if agreement is None or agreement["status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTED")
    return agreement


def g37_counter_limit(agreement, party):
    if int(agreement["counter_round"]) >= C.MAX_COUNTER_ROUNDS:
        return False  # the caller voids the agreement and answers the error
    if agreement["last_countered_by"] == party:
        raise ApiError("ERR_COUNTER_LIMIT_EXCEEDED")
    return True


def g38_offer_not_expired(offer):
    if S.now() >= offer["expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED")


# --------------------------------------------------------------------------- #
# priorities 39-45: interval geometry
# --------------------------------------------------------------------------- #
def g39_window_inside_cycle(starts_at, ends_at):
    if ends_at <= starts_at:
        raise ApiError("ERR_WINDOW_OUTSIDE_CYCLE")
    for cycle in S.all_rows("program_cycles"):
        if cycle["starts_at"] <= starts_at and ends_at <= cycle["ends_at"]:
            return cycle
    raise ApiError("ERR_WINDOW_OUTSIDE_CYCLE")


def g40_milestone_due(engagement, window, due_at):
    if window is None:
        raise ApiError("ERR_MILESTONE_DUE_OUTSIDE_ENGAGEMENT")
    if not (window["starts_at"] <= due_at < window["ends_at"]):
        raise ApiError("ERR_MILESTONE_DUE_OUTSIDE_ENGAGEMENT")
    if not due_at > engagement["created_at"]:
        raise ApiError("ERR_MILESTONE_DUE_OUTSIDE_ENGAGEMENT")


def g41_log_inside_window(window, work_date):
    if window is None or not (window["starts_at"] <= work_date < window["ends_at"]):
        raise ApiError("ERR_WINDOW_OUTSIDE_CYCLE")


def g42_no_clock_regression(target):
    if target < S.now():
        raise ApiError("ERR_CLOCK_REGRESSION")


def g43_no_window_overlap(volunteer_id, starts_at, ends_at):
    for existing in S.where("availability_windows", volunteer_id=volunteer_id):
        if calc.window_metrics(existing)["status"] == "EXPIRED":
            continue
        if starts_at < existing["ends_at"] and existing["starts_at"] < ends_at:
            raise ApiError("ERR_AVAILABILITY_WINDOW_OVERLAP")


def g44_milestone_spacing(engagement_id, due_at):
    buffer_ = timedelta(hours=C.MILESTONE_MIN_SPACING_HOURS)
    for sibling in S.where("milestones", engagement_id=engagement_id):
        if sibling["checkin_status"] not in ("SCHEDULED", "HELD"):
            continue
        delta = abs(sibling["due_at"] - due_at)
        if delta < buffer_:
            raise ApiError("ERR_MILESTONE_SPACING_VIOLATION")


def g45_checkin_saturation(volunteer_id, due_at):
    low = due_at - timedelta(days=7)
    high = due_at + timedelta(days=7)
    eng_ids = {
        e["id"]
        for e in S.all_rows("engagements")
        if e["volunteer_id"] == volunteer_id
    }
    count = 0
    for milestone in S.all_rows("milestones"):
        if milestone["engagement_id"] not in eng_ids:
            continue
        if milestone["checkin_status"] != "SCHEDULED":
            continue
        if low <= milestone["due_at"] <= high:
            count += 1
    if count >= C.CHECKIN_SATURATION_LIMIT:
        raise ApiError("ERR_VOLUNTEER_CHECKIN_SATURATED")


# --------------------------------------------------------------------------- #
# priorities 46-57
# --------------------------------------------------------------------------- #
def g46_unique_skill(volunteer_id, skill_code):
    for existing in S.where("skill_profiles", volunteer_id=volunteer_id):
        if existing["skill_code"] == skill_code:
            raise ApiError("ERR_DUPLICATE_SKILL_PROFILE")


def g47_unique_sequence(scope_id, sequence_no):
    for existing in S.where("deliverables", scope_definition_id=scope_id):
        if int(existing["sequence_no"]) == int(sequence_no):
            raise ApiError("ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID")


def g47_weight_ceiling(scope_id, incoming_weight):
    total = calc.deliverable_weight_total(scope_id) + dec(incoming_weight)
    if rnd(total, 2) > Decimal("100.00"):
        raise ApiError("ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID")


def g47_weight_exact(scope_id):
    active = calc.active_deliverables(scope_id)
    if len(active) < 1:
        raise ApiError("ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID")
    if calc.deliverable_weight_total(scope_id) != Decimal("100.00"):
        raise ApiError("ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID")


def g48_deliverable_set(scope_id, entries):
    active = calc.active_deliverables(scope_id)
    expected = {d["id"] for d in active}
    if not expected:
        raise ApiError("ERR_DELIVERABLE_SET_MISMATCH")
    if not isinstance(entries, list) or not entries:
        raise ApiError("ERR_DELIVERABLE_SET_MISMATCH")
    seen = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("ERR_DELIVERABLE_SET_MISMATCH")
        seen.append(entry.get("deliverable_id"))
    if len(set(seen)) != len(seen):
        raise ApiError("ERR_DELIVERABLE_SET_MISMATCH")
    if set(seen) != expected:
        raise ApiError("ERR_DELIVERABLE_SET_MISMATCH")


def g49_scope_approved(scope):
    if scope is None or scope["status"] != "APPROVED":
        raise ApiError("ERR_SCOPE_VERSION_SUPERSEDED")


def g50_rescope_limit(req):
    if int(req["rescope_count"]) >= C.MAX_RESCOPES:
        raise ApiError("ERR_RESCOPE_LIMIT_REACHED")


def g51_cycle_not_frozen(cycle):
    if calc.cycle_posture(cycle) == "FROZEN":
        raise ApiError("ERR_CYCLE_CAPACITY_FROZEN")


def g52_restricted_urgency(cycle, req):
    if calc.cycle_posture(cycle) == "RESTRICTED" and req["urgency"] not in (
        "ELEVATED",
        "CRITICAL",
    ):
        raise ApiError("ERR_CYCLE_RESTRICTED_URGENCY")


def g53_partner_engagement_limit(partner):
    _, ceiling = calc.partner_capacity(partner["annual_budget_usd"])
    if calc.partner_open_engagements(partner["id"]) >= ceiling:
        raise ApiError("ERR_PARTNER_ENGAGEMENT_LIMIT")


def g54_volunteer_concurrency(volunteer):
    if calc.volunteer_open_engagements(volunteer["id"]) >= C.VOLUNTEER_MAX_CONCURRENT:
        raise ApiError("ERR_VOLUNTEER_CONCURRENCY_LIMIT")


def g55_window_hours(window, needed):
    if window is None:
        raise ApiError("ERR_AVAILABILITY_HOURS_EXCEEDED")
    if calc.window_remaining(window) < dec(needed):
        raise ApiError("ERR_AVAILABILITY_HOURS_EXCEEDED")


def g55_log_hours(window, hours):
    if window is None:
        raise ApiError("ERR_AVAILABILITY_HOURS_EXCEEDED")
    ceiling = dec(window["hours_offered"]) - calc.window_approved_hours(window)
    if dec(hours) > ceiling:
        raise ApiError("ERR_AVAILABILITY_HOURS_EXCEEDED")


def g56_no_breach(engagement):
    _, level = calc.creep(engagement)
    if level == "BREACH":
        raise ApiError("ERR_SCOPE_BREACH_THRESHOLD")
    for scr in S.where("scope_change_requests", engagement_id=engagement["id"]):
        if scr["status"] in ("PENDING", "ESCALATED"):
            raise ApiError("ERR_SCOPE_BREACH_THRESHOLD")


def g57_candidates(candidates):
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_VOLUNTEER")
