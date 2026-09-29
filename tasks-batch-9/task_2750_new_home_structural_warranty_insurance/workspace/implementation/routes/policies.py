"""Home enrollment, the two policy axes and coverage terms (PRD 3.3, 3.4)."""

from flask import Blueprint

import calc
import db
import listing
import response
import store
import validators as v
from errors import err, invalid
from middleware import (ROLE_ADJUSTER, ROLE_BUILDER, ROLE_COMPLIANCE,
                        ROLE_HOMEOWNER, ROLE_UNDERWRITER, endpoint)

bp = Blueprint("policies", __name__)

ALL_READERS = (ROLE_UNDERWRITER, ROLE_COMPLIANCE, ROLE_ADJUSTER, ROLE_BUILDER,
               ROLE_HOMEOWNER)


def _new_term(policy_id, coverage_type, term_kind, start_date, end_date,
              limit_cents, deductible_cents):
    row = {
        "policy_id": policy_id,
        "coverage_type": coverage_type,
        "term_kind": term_kind,
        "start_date": start_date,
        "end_date": end_date,
        "limit_cents": limit_cents,
        "deductible_cents": deductible_cents,
        "consumed_limit_cents": 0,
        "remaining_limit_cents": limit_cents,
        "status": "OPEN",
    }
    db.stamp_create(row)
    db.coverage_terms[row["id"]] = row
    return row


@bp.post("/policies")
@endpoint(ROLE_BUILDER)
def enroll_home(user_id, role):
    body = v.body()
    raw_builder_id = body.get("builder_id")
    if isinstance(raw_builder_id, str) and raw_builder_id != user_id:
        raise err("ERR_NOT_BUILDER_PRINCIPAL",
                  "X-User-ID does not match builder_id")
    builder = None
    if isinstance(raw_builder_id, str):
        builder = store.get_builder(raw_builder_id)
    raw_owner_id = body.get("initial_owner_id")
    if isinstance(raw_owner_id, str):
        store.get_homeowner(raw_owner_id)

    builder_id = v.req_str(body, "builder_id")
    initial_owner_id = v.req_str(body, "initial_owner_id")
    street_address = v.req_str(body, "street_address", 1, 200)
    state_code = v.req_enum(body, "state_code", calc.STATE_CODES)
    price = v.req_int(body, "purchase_price_cents", 5000000, 500000000)
    closing_date = v.req_date(body, "closing_date")
    override = v.opt_bool(body, "posture_override_acknowledged", default=False)
    if closing_date > db.clock_date():
        raise invalid("field 'closing_date' may not be later than the current date")

    if builder is None:
        builder = store.get_builder(builder_id)
    if builder["underwriting_status"] != "APPROVED":
        raise err("ERR_BUILDER_NOT_APPROVED",
                  "the enrolling builder is not APPROVED")
    if builder["monitoring_posture"] == "FROZEN":
        raise err("ERR_BUILDER_POSTURE_FROZEN",
                  "a FROZEN builder may not write new business")
    if builder["monitoring_posture"] == "RESTRICTED" and override is not True:
        raise err("ERR_POSTURE_OVERRIDE_REQUIRED",
                  "posture_override_acknowledged is required under a RESTRICTED posture")

    risk_class = builder["risk_class"]
    premium = calc.premium_components(price, risk_class, state_code)
    closing_str = v.fmt_date(closing_date)
    policy = {
        "builder_id": builder["id"],
        "initial_owner_id": initial_owner_id,
        "current_owner_id": initial_owner_id,
        "pending_transfer_id": None,
        "street_address": street_address,
        "state_code": state_code,
        "purchase_price_cents": price,
        "closing_date": closing_str,
        "coverage_start_date": closing_str,
        "builder_obligation_end_date": v.fmt_date(
            calc.anniversary_end(closing_date, builder["obligation_period_years"])),
        "risk_class_at_enrollment": risk_class,
        "premium_component_workmanship_cents":
            premium["premium_component_workmanship_cents"],
        "premium_component_systems_cents": premium["premium_component_systems_cents"],
        "premium_component_structural_cents":
            premium["premium_component_structural_cents"],
        "state_surcharge_cents": premium["state_surcharge_cents"],
        "premium_cents": premium["premium_cents"],
        "coverage_status": "PENDING_ENROLLMENT",
        "premium_status": "UNBILLED",
        "enrollment_hold": False,
        "transfer_count": 0,
    }
    db.stamp_create(policy)
    db.policies[policy["id"]] = policy
    for spec in calc.base_term_specs(closing_date, price):
        _new_term(policy["id"], spec["coverage_type"], "BASE", closing_str,
                  v.fmt_date(spec["end_date"]), spec["limit_cents"],
                  spec["deductible_cents"])
    return response.object_response(db.public(policy), 201)


@bp.post("/policies/<policy_id>/premium-invoice")
@endpoint(ROLE_UNDERWRITER)
def invoice_premium(policy_id, user_id, role):
    policy = store.get_policy(policy_id)
    v.opt_str(v.body(), "invoice_reference", non_blank=False)
    if policy["premium_status"] != "UNBILLED":
        raise err("ERR_INVALID_PREMIUM_STATE",
                  "policy premium_status is '%s'" % policy["premium_status"])
    if policy["coverage_status"] != "PENDING_ENROLLMENT":
        raise err("ERR_INVALID_POLICY_STATE",
                  "policy coverage_status is '%s'" % policy["coverage_status"])
    policy["premium_status"] = "INVOICED"
    db.mark(policy)
    return response.object_response(db.public(policy))


@bp.post("/policies/<policy_id>/premium-payments")
@endpoint(ROLE_BUILDER)
def pay_premium(policy_id, user_id, role):
    policy = store.get_policy(policy_id)
    if policy["builder_id"] != user_id:
        raise err("ERR_NOT_BUILDER_PRINCIPAL",
                  "X-User-ID is not the builder of this policy")
    v.opt_str(v.body(), "payment_reference", non_blank=False)
    if policy["premium_status"] != "INVOICED":
        raise err("ERR_INVALID_PREMIUM_STATE",
                  "policy premium_status is '%s'" % policy["premium_status"])
    policy["premium_status"] = "PAID"
    store.recompute_builder(db.builders.get(policy["builder_id"]))
    db.mark(policy)
    return response.object_response(db.public(policy))


@bp.post("/policies/<policy_id>/activation")
@endpoint(ROLE_UNDERWRITER)
def activate_policy(policy_id, user_id, role):
    policy = store.get_policy(policy_id)
    if policy["coverage_status"] != "PENDING_ENROLLMENT":
        raise err("ERR_INVALID_POLICY_STATE",
                  "policy coverage_status is '%s'" % policy["coverage_status"])
    builder = db.builders.get(policy["builder_id"])
    if builder is None or builder["underwriting_status"] != "APPROVED":
        raise err("ERR_BUILDER_NOT_APPROVED",
                  "the enrolling builder is no longer APPROVED")
    if policy["premium_status"] != "PAID":
        raise err("ERR_PREMIUM_NOT_PAID", "the enrollment premium is not PAID")
    if policy["enrollment_hold"]:
        raise err("ERR_ENROLLMENT_ON_HOLD", "the enrollment is on hold")
    policy["coverage_status"] = "ACTIVE"
    store.recompute_builder(builder)
    db.mark(policy)
    return response.object_response(db.public(policy))


@bp.post("/policies/<policy_id>/coverage-terms")
@endpoint(ROLE_UNDERWRITER)
def add_endorsement(policy_id, user_id, role):
    policy = store.get_policy(policy_id)
    body = v.body()
    coverage_type = v.req_enum(body, "coverage_type", calc.COVERAGE_TYPES)
    start_date = v.req_date(body, "start_date")
    end_date = v.req_date(body, "end_date")
    limit_cents = v.req_int(body, "limit_cents", 1)
    deductible_cents = v.req_int(body, "deductible_cents", 0)
    if end_date < start_date:
        raise invalid("field 'end_date' may not be earlier than 'start_date'")
    if policy["coverage_status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE",
                  "endorsements are only available on an ACTIVE policy")
    start_str = v.fmt_date(start_date)
    end_str = v.fmt_date(end_date)
    for term in store.terms_of_policy(policy_id):
        if term["coverage_type"] != coverage_type:
            continue
        if start_str <= term["end_date"] and term["start_date"] <= end_str:
            raise err("ERR_COVERAGE_TERM_OVERLAP",
                      "an existing %s term already covers that interval" % coverage_type)
    row = _new_term(policy_id, coverage_type, "ENDORSEMENT", start_str, end_str,
                    limit_cents, deductible_cents)
    db.mark(policy)
    return response.object_response(db.public(row), 201)


@bp.get("/policies/<policy_id>")
@endpoint(*ALL_READERS)
def read_policy(policy_id, user_id, role):
    return response.object_response(db.public(store.get_policy(policy_id)))


@bp.get("/policies")
@endpoint(*ALL_READERS)
def list_policies(user_id, role):
    rows = store.all_rows(db.policies)
    rows = listing.eq_filter(rows, "builder_id")
    rows = listing.eq_filter(rows, "initial_owner_id")
    rows = listing.eq_filter(rows, "current_owner_id")
    rows = listing.eq_filter(rows, "pending_transfer_id")
    rows = listing.eq_filter(rows, "coverage_status")
    rows = listing.eq_filter(rows, "premium_status")
    return response.paginate(rows)


@bp.get("/policies/<policy_id>/coverage-terms")
@endpoint(*ALL_READERS)
def list_policy_terms(policy_id, user_id, role):
    store.get_policy(policy_id)
    rows = store.terms_of_policy(policy_id)
    rows = listing.eq_filter(rows, "coverage_type")
    rows = listing.eq_filter(rows, "term_kind")
    rows = listing.eq_filter(rows, "status")
    rows.sort(key=store.term_sort_key)
    return response.paginate(rows)


@bp.get("/coverage-terms/<term_id>")
@endpoint(*ALL_READERS)
def read_term(term_id, user_id, role):
    return response.object_response(db.public(store.get_term(term_id)))
