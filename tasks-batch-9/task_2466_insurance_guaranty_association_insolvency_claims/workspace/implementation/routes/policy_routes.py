"""Transferred policies and unearned premium refunds."""

from flask import Blueprint

import domain
from auth import (
    ROLE_ASSOCIATION_ADMIN,
    ROLE_CLAIMS_COMMITTEE_OFFICER,
    ROLE_COVERAGE_ANALYST,
    ROLE_RECEIVER_LIAISON,
    endpoint,
)
from calc import unearned_premium_refund
from envelope import list_response, object_response
from errors import fail
from shape import F, enum_filter, get_body, paginate, pagination, str_filter, validate
from store import parse_date, parse_datetime, sort_rows, stamp_new, store, touch

policies_bp = Blueprint("policies", __name__)


@policies_bp.route("/policies", methods=["POST"])
@endpoint([ROLE_RECEIVER_LIAISON, ROLE_ASSOCIATION_ADMIN])
def create_policy():
    body = get_body()

    # priority 13: body foreign keys resolve before request-shape validation
    raw_insolvency_id = body.get("insolvency_id")
    if isinstance(raw_insolvency_id, str) and raw_insolvency_id not in store.insolvencies:
        fail(
            "ERR_REFERENCED_ROW_NOT_FOUND",
            "No insolvency file matches insolvency_id '%s'." % raw_insolvency_id,
        )

    values = validate(
        body,
        [
            F("insolvency_id", "str"),
            F("policy_number", "str"),
            F("line_of_business", "enum", enum=domain.LINES),
            F("policyholder_name", "str"),
            F("policyholder_state_code", "str", state_code=True),
            F("effective_date", "date"),
            F("expiration_date", "date"),
            F("annual_premium_cents", "int", exclusive_minimum=0),
            F("policyholder_net_worth_cents", "int", required=False, default=0, minimum=0),
            F("large_deductible_cents", "int", required=False, default=0, minimum=0),
            F("self_insured_retention_cents", "int", required=False, default=0, minimum=0),
            F("collateral_held_cents", "int", required=False, default=0, minimum=0),
        ],
    )
    if values["insolvency_id"] not in store.insolvencies:
        fail(
            "ERR_REFERENCED_ROW_NOT_FOUND",
            "No insolvency file matches insolvency_id '%s'." % values["insolvency_id"],
        )

    effective = parse_date(values["effective_date"])
    expiration = parse_date(values["expiration_date"])
    if expiration <= effective:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'expiration_date' must be strictly after 'effective_date'.",
        )

    insolvency = store.insolvencies[values["insolvency_id"]]
    if insolvency["status"] == "CLOSED":
        fail("ERR_INSOLVENCY_CLOSED", "The insolvency file is closed.")

    for existing in domain.policies_of_insolvency(insolvency["id"]):
        if existing["policy_number"] != values["policy_number"]:
            continue
        other_start = parse_date(existing["effective_date"])
        other_end = parse_date(existing["expiration_date"])
        if other_start is None or other_end is None:
            continue
        # half-open terms: touching boundaries do not intersect (a renewal)
        if effective < other_end and other_start < expiration:
            fail(
                "ERR_POLICY_PERIOD_OVERLAP",
                "The policy term intersects another policy of this insolvency file sharing "
                "policy_number '%s'." % values["policy_number"],
            )

    row = {
        "insolvency_id": values["insolvency_id"],
        "source_transfer_id": None,
        "policy_number": values["policy_number"],
        "line_of_business": values["line_of_business"],
        "policyholder_name": values["policyholder_name"],
        "policyholder_state_code": values["policyholder_state_code"],
        "policyholder_net_worth_cents": values["policyholder_net_worth_cents"],
        "effective_date": values["effective_date"],
        "expiration_date": values["expiration_date"],
        "annual_premium_cents": values["annual_premium_cents"],
        "large_deductible_cents": values["large_deductible_cents"],
        "self_insured_retention_cents": values["self_insured_retention_cents"],
        "collateral_held_cents": values["collateral_held_cents"],
        "status": "IMPORTED",
        "cancellation_date": None,
        "unexpired_days": 0,
    }
    stamp_new(row)
    store.policies[row["id"]] = row
    return object_response(domain.serialize_policy(row), 201)


@policies_bp.route("/policies", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_RECEIVER_LIAISON, ROLE_COVERAGE_ANALYST])
def list_policies():
    limit, offset = pagination()
    insolvency_id = str_filter("insolvency_id")
    source_transfer_id = str_filter("source_transfer_id")
    status = enum_filter("status", domain.POLICY_STATUSES)
    line = enum_filter("line_of_business", domain.LINES)

    rows = list(store.policies.values())
    if insolvency_id is not None:
        rows = [p for p in rows if p["insolvency_id"] == insolvency_id]
    if source_transfer_id is not None:
        rows = [p for p in rows if p["source_transfer_id"] == source_transfer_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    if line is not None:
        rows = [p for p in rows if p["line_of_business"] == line]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_policy(r) for r in page], limit, offset, total)


@policies_bp.route("/policies/<policy_id>", methods=["GET"])
@endpoint(
    [
        ROLE_ASSOCIATION_ADMIN,
        ROLE_RECEIVER_LIAISON,
        ROLE_COVERAGE_ANALYST,
        ROLE_CLAIMS_COMMITTEE_OFFICER,
    ]
)
def read_policy(policy_id):
    row = domain.get_policy(policy_id)
    return object_response(domain.serialize_policy(row))


@policies_bp.route("/policies/<policy_id>/premium-refunds", methods=["POST"])
@endpoint([ROLE_COVERAGE_ANALYST])
def create_premium_refund(policy_id):
    policy = domain.get_policy(policy_id)
    values = validate(
        get_body(),
        [
            F("refund_method", "enum", enum=domain.REFUND_METHODS),
            F("expected_policy_version", "int"),
        ],
    )
    if values["expected_policy_version"] != policy["version"]:
        fail(
            "ERR_STALE_POLICY_VERSION",
            "expected_policy_version %s does not match the policy's current version %s."
            % (values["expected_policy_version"], policy["version"]),
        )

    insolvency = domain.insolvency_of_policy(policy)
    if insolvency is None or insolvency["status"] != "TRIGGERED":
        fail(
            "ERR_INSOLVENCY_NOT_TRIGGERED",
            "The triggering event has not been recorded on this insolvency file.",
        )
    if policy["status"] != "CANCELLED_BY_ORDER":
        fail(
            "ERR_POLICY_NOT_CANCELLED",
            "Unearned premium may only be refunded on a policy cancelled by the liquidation order.",
        )

    deadline = parse_datetime(insolvency.get("proof_of_claim_deadline_utc"))
    if deadline is not None and store.now > deadline:
        fail("ERR_FILING_DEADLINE_PASSED", "The proof-of-claim filing deadline has passed.")

    profile = domain.profile_for_line(policy["line_of_business"])
    if profile is None:
        fail(
            "ERR_COVERAGE_PROFILE_MISSING",
            "No coverage configuration row exists for line '%s'." % policy["line_of_business"],
        )
    if domain.up_refund_filed(policy_id):
        fail(
            "ERR_UP_REFUND_ALREADY_FILED",
            "An unearned premium refund has already been filed on this policy.",
        )

    result = unearned_premium_refund(
        policy["annual_premium_cents"],
        policy["unexpired_days"],
        domain.policy_term_days(policy),
        values["refund_method"],
        profile["unearned_premium_cap_cents"],
    )

    row = {
        "policy_id": policy_id,
        "refund_method": values["refund_method"],
        "computed_refund_cents": result["computed_refund_cents"],
        "alt_refund_cents": result["alt_refund_cents"],
        "capped": result["capped"],
        "priority_class": profile["refund_priority_class"],
        "paid_amount_cents": 0,
        "status": "PENDING",
        "sequence": store.next_sequence("refund"),
    }
    stamp_new(row)
    store.refunds[row["id"]] = row

    # the policy's up_refund_filed flips to true and its version advances, which is
    # exactly what turns away a second concurrent filer holding the earlier version
    touch(policy)
    return object_response(domain.serialize_refund(row), 201)


@policies_bp.route("/policies/<policy_id>/premium-refunds", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_COVERAGE_ANALYST, ROLE_RECEIVER_LIAISON])
def list_premium_refunds(policy_id):
    domain.get_policy(policy_id)
    limit, offset = pagination()
    status = enum_filter("status", domain.REFUND_STATUSES)
    rows = domain.refunds_of_policy(policy_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_refund(r) for r in page], limit, offset, total)
