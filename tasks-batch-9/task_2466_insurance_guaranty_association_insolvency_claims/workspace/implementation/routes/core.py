"""Coverage configuration, insolvency files, proof-of-claim batches, logical clock."""

from datetime import timedelta

from flask import Blueprint

import domain
from auth import (
    ROLE_ASSESSMENT_OFFICER,
    ROLE_ASSOCIATION_ADMIN,
    ROLE_CLAIMS_COMMITTEE_OFFICER,
    ROLE_COVERAGE_ANALYST,
    ROLE_RECEIVER_LIAISON,
    endpoint,
)
from calc import allocate
from envelope import list_response, object_response
from errors import fail
from shape import (
    F,
    enum_filter,
    get_body,
    no_body,
    paginate,
    pagination,
    validate,
)
from store import (
    date_to_str,
    day_count,
    fmt_dt,
    now_dt,
    now_iso,
    parse_date,
    parse_datetime,
    sort_rows,
    stamp_new,
    store,
    touch,
)

core_bp = Blueprint("core", __name__)

COVERAGE_TERMINATION_OFFSET_DAYS = 30
PROOF_OF_CLAIM_DEADLINE_OFFSET_DAYS = 365
DELINQUENCY_GRACE_DAYS = 30


# ==========================================================================
# coverage configuration
# ==========================================================================
@core_bp.route("/coverage-profiles", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def create_coverage_profile():
    values = validate(
        get_body(),
        [
            F("line_of_business", "enum", enum=domain.LINES),
            F("per_claim_cap_cents", "int", exclusive_minimum=0),
            F("per_policy_aggregate_cap_cents", "int", minimum=0),
            F("unearned_premium_cap_cents", "int", exclusive_minimum=0),
            F("refund_priority_class", "int", minimum=1, maximum=3),
            F("statutory_deductible_cents", "int", required=False, default=10000, minimum=0),
            F(
                "net_worth_exclusion_threshold_cents",
                "int",
                required=False,
                default=2500000000,
                minimum=0,
            ),
            F("covers_punitive_damages", "bool", required=False, default=False),
            F(
                "cap_order_mode",
                "enum",
                required=False,
                default="OFFSET_THEN_CAP",
                enum=domain.CAP_ORDER_MODES,
            ),
        ],
    )
    if values["per_policy_aggregate_cap_cents"] < values["per_claim_cap_cents"]:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'per_policy_aggregate_cap_cents' must be greater than or equal to "
            "'per_claim_cap_cents'.",
        )
    if domain.profile_for_line(values["line_of_business"]) is not None:
        fail(
            "ERR_INVALID_REQUEST",
            "A coverage configuration row already exists for line '%s'."
            % values["line_of_business"],
        )

    row = dict(values)
    stamp_new(row)
    # the configuration row is exempt from the lifecycle fields (PRD 2.4)
    row.pop("updated_at", None)
    row.pop("version", None)
    store.coverage_profiles[row["id"]] = row
    return object_response(domain.serialize_coverage_profile(row), 201)


@core_bp.route("/coverage-profiles", methods=["GET"])
@endpoint(
    [
        ROLE_ASSOCIATION_ADMIN,
        ROLE_COVERAGE_ANALYST,
        ROLE_CLAIMS_COMMITTEE_OFFICER,
        ROLE_ASSESSMENT_OFFICER,
    ]
)
def list_coverage_profiles():
    limit, offset = pagination()
    line = enum_filter("line_of_business", domain.LINES)
    rows = list(store.coverage_profiles.values())
    if line is not None:
        rows = [r for r in rows if r["line_of_business"] == line]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [domain.serialize_coverage_profile(r) for r in page], limit, offset, total
    )


# ==========================================================================
# insolvency files
# ==========================================================================
@core_bp.route("/insolvencies", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def create_insolvency():
    values = validate(
        get_body(),
        [
            F("insurer_name", "str"),
            F("naic_code", "str"),
            F("domiciliary_state_code", "str", state_code=True),
            F("liquidation_order_date", "date"),
        ],
    )
    for existing in store.insolvencies.values():
        if existing["naic_code"] == values["naic_code"]:
            fail(
                "ERR_INVALID_REQUEST",
                "An insolvency file already exists for NAIC code '%s'." % values["naic_code"],
            )

    row = {
        "insurer_name": values["insurer_name"],
        "naic_code": values["naic_code"],
        "domiciliary_state_code": values["domiciliary_state_code"],
        "liquidation_order_date": values["liquidation_order_date"],
        "coverage_termination_date": None,
        "proof_of_claim_deadline_utc": None,
        "status": "DECLARED",
        "triggered_at_utc": None,
        "estate_remitted_cents": 0,
        "estate_distributed_cents": 0,
        "estate_returned_cents": 0,
        "administrative_paid_cents": 0,
        "distribution_sequence": 0,
    }
    stamp_new(row)
    store.insolvencies[row["id"]] = row
    return object_response(domain.serialize_insolvency(row), 201)


@core_bp.route("/insolvencies/<insolvency_id>", methods=["GET"])
@endpoint(
    [
        ROLE_ASSOCIATION_ADMIN,
        ROLE_RECEIVER_LIAISON,
        ROLE_COVERAGE_ANALYST,
        ROLE_CLAIMS_COMMITTEE_OFFICER,
        ROLE_ASSESSMENT_OFFICER,
    ]
)
def read_insolvency(insolvency_id):
    row = domain.get_insolvency(insolvency_id)
    return object_response(domain.serialize_insolvency(row))


@core_bp.route("/insolvencies/<insolvency_id>/trigger", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def trigger_insolvency(insolvency_id):
    insolvency = domain.get_insolvency(insolvency_id)
    no_body()

    if insolvency["status"] == "CLOSED":
        fail("ERR_INSOLVENCY_CLOSED", "The insolvency file is closed.")
    if insolvency["status"] != "DECLARED":
        fail(
            "ERR_INSOLVENCY_ALREADY_TRIGGERED",
            "The triggering event has already been recorded on this insolvency file.",
        )

    policies = domain.policies_of_insolvency(insolvency_id)
    for line in sorted(set(p["line_of_business"] for p in policies)):
        if domain.profile_for_line(line) is None:
            fail(
                "ERR_COVERAGE_PROFILE_MISSING",
                "No coverage configuration row exists for line '%s'." % line,
            )
    if not [p for p in policies if p["status"] == "IMPORTED"]:
        fail(
            "ERR_INVALID_REQUEST",
            "At least one transferred policy in IMPORTED is required before the triggering event.",
        )

    order_date = parse_date(insolvency["liquidation_order_date"])
    termination_date = order_date + timedelta(days=COVERAGE_TERMINATION_OFFSET_DAYS)
    deadline_date = order_date + timedelta(days=PROOF_OF_CLAIM_DEADLINE_OFFSET_DAYS)

    insolvency["triggered_at_utc"] = now_iso()
    insolvency["coverage_termination_date"] = date_to_str(termination_date)
    insolvency["proof_of_claim_deadline_utc"] = "%sT00:00:00.000Z" % date_to_str(deadline_date)
    insolvency["status"] = "TRIGGERED"

    for policy in policies:
        if policy["status"] != "IMPORTED":
            continue
        expiration = parse_date(policy["expiration_date"])
        if expiration is not None and expiration > order_date:
            cancellation = min(expiration, termination_date)
            policy["status"] = "CANCELLED_BY_ORDER"
            policy["cancellation_date"] = date_to_str(cancellation)
            policy["unexpired_days"] = max(0, day_count(cancellation, expiration))
        else:
            policy["status"] = "EXPIRED_BEFORE_ORDER"
            policy["cancellation_date"] = None
            policy["unexpired_days"] = 0
        touch(policy)

    touch(insolvency)
    return object_response(domain.serialize_insolvency(insolvency))


@core_bp.route("/insolvencies/<insolvency_id>/estate-remittances", methods=["POST"])
@endpoint([ROLE_RECEIVER_LIAISON])
def create_estate_remittance(insolvency_id):
    insolvency = domain.get_insolvency(insolvency_id)
    values = validate(
        get_body(),
        [F("amount_cents", "int", minimum=0), F("remittance_ref", "str")],
    )
    _require_triggered(insolvency)

    insolvency["estate_remitted_cents"] += values["amount_cents"]
    touch(insolvency)
    return object_response(domain.serialize_insolvency(insolvency))


@core_bp.route("/insolvencies/<insolvency_id>/distributions", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def create_distribution(insolvency_id):
    insolvency = domain.get_insolvency(insolvency_id)
    values = validate(
        get_body(),
        [
            F("distribution_amount_cents", "int", minimum=0),
            F("expected_insolvency_version", "int"),
        ],
    )
    if values["expected_insolvency_version"] != insolvency["version"]:
        fail(
            "ERR_STALE_INSOLVENCY_VERSION",
            "expected_insolvency_version %s does not match the insolvency file's current version %s."
            % (values["expected_insolvency_version"], insolvency["version"]),
        )
    _require_triggered(insolvency)

    funds = values["distribution_amount_cents"]
    if funds > domain.estate_undistributed_cents(insolvency):
        fail(
            "ERR_INSUFFICIENT_ESTATE_FUNDS",
            "distribution_amount_cents exceeds the undistributed estate balance.",
        )

    # ---- class 1: association administrative expense -------------------
    outstanding_admin = max(
        0,
        domain.administrative_expense_cents(insolvency_id)
        - int(insolvency["administrative_paid_cents"]),
    )
    class1_paid = min(funds, outstanding_admin)
    insolvency["administrative_paid_cents"] += class1_paid
    funds -= class1_paid

    # ---- class 2: covered claims ---------------------------------------
    claims = [
        c
        for c in domain.claims_of_insolvency(insolvency_id)
        if c["status"] in ("APPROVED", "PARTIALLY_PAID")
        and (int(c["net_payable_cents"] or 0) - int(c["paid_amount_cents"] or 0)) > 0
    ]
    claims.sort(key=lambda c: (c["created_at"], c["sequence"]))
    claim_outstanding = [
        int(c["net_payable_cents"] or 0) - int(c["paid_amount_cents"] or 0) for c in claims
    ]
    claim_shares, funds = allocate(funds, claim_outstanding)

    claim_payments = []
    class2_paid = 0
    for claim, share in zip(claims, claim_shares):
        if share <= 0:
            continue
        outstanding = int(claim["net_payable_cents"] or 0) - int(claim["paid_amount_cents"] or 0)
        claim["paid_amount_cents"] = int(claim["paid_amount_cents"] or 0) + share
        if share >= outstanding:
            claim["paid_amount_cents"] = int(claim["net_payable_cents"] or 0)
            claim["status"] = "PAID"
            domain.close_assigned_vendor_assignments(claim["id"])
        else:
            claim["status"] = "PARTIALLY_PAID"
        touch(claim)
        class2_paid += share
        claim_payments.append(
            {
                "claim_id": claim["id"],
                "allocated_cents": share,
                "paid_amount_cents": claim["paid_amount_cents"],
                "status": claim["status"],
            }
        )

    # ---- class 3: unearned premium refunds -----------------------------
    refunds = [
        r
        for r in domain.refunds_of_insolvency(insolvency_id)
        if r["status"] in ("PENDING", "PARTIALLY_PAID")
        and (int(r["computed_refund_cents"] or 0) - int(r["paid_amount_cents"] or 0)) > 0
    ]
    refunds.sort(key=lambda r: (r["priority_class"], r["created_at"], r["sequence"]))
    refund_outstanding = [
        int(r["computed_refund_cents"] or 0) - int(r["paid_amount_cents"] or 0) for r in refunds
    ]
    refund_shares, funds = allocate(funds, refund_outstanding)

    refund_payments = []
    class3_paid = 0
    for refund, share in zip(refunds, refund_shares):
        if share <= 0:
            continue
        outstanding = int(refund["computed_refund_cents"] or 0) - int(
            refund["paid_amount_cents"] or 0
        )
        refund["paid_amount_cents"] = int(refund["paid_amount_cents"] or 0) + share
        if share >= outstanding:
            refund["paid_amount_cents"] = int(refund["computed_refund_cents"] or 0)
            refund["status"] = "PAID"
        else:
            refund["status"] = "PARTIALLY_PAID"
        touch(refund)
        class3_paid += share
        refund_payments.append(
            {
                "refund_id": refund["id"],
                "allocated_cents": share,
                "paid_amount_cents": refund["paid_amount_cents"],
                "status": refund["status"],
            }
        )

    insolvency["estate_distributed_cents"] += class1_paid + class2_paid + class3_paid
    insolvency["distribution_sequence"] += 1
    touch(insolvency)

    return object_response(
        {
            "distribution_sequence": insolvency["distribution_sequence"],
            "class1_paid_cents": class1_paid,
            "class2_paid_cents": class2_paid,
            "class3_paid_cents": class3_paid,
            "claim_payments": claim_payments,
            "refund_payments": refund_payments,
            "estate_distributed_cents": insolvency["estate_distributed_cents"],
            "estate_undistributed_cents": domain.estate_undistributed_cents(insolvency),
        }
    )


@core_bp.route("/insolvencies/<insolvency_id>/close", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def close_insolvency(insolvency_id):
    insolvency = domain.get_insolvency(insolvency_id)
    no_body()
    _require_triggered(insolvency)

    for claim in domain.claims_of_insolvency(insolvency_id):
        if claim["status"] in domain.CLAIMS_OUTSTANDING_STATUSES:
            fail(
                "ERR_CLAIMS_OUTSTANDING",
                "Covered claims of this insolvency file are still outstanding.",
            )
    for refund in domain.refunds_of_insolvency(insolvency_id):
        if refund["status"] in ("PENDING", "PARTIALLY_PAID"):
            fail(
                "ERR_REFUNDS_OUTSTANDING",
                "Unearned premium refunds of this insolvency file are still outstanding.",
            )

    insolvency["estate_returned_cents"] += domain.estate_undistributed_cents(insolvency)
    insolvency["status"] = "CLOSED"
    touch(insolvency)
    return object_response(domain.serialize_insolvency(insolvency))


def _require_triggered(insolvency):
    if insolvency["status"] != "TRIGGERED":
        fail(
            "ERR_INSOLVENCY_NOT_TRIGGERED",
            "The triggering event has not been recorded on this insolvency file.",
        )


def _require_not_closed(insolvency):
    if insolvency["status"] == "CLOSED":
        fail("ERR_INSOLVENCY_CLOSED", "The insolvency file is closed.")


# ==========================================================================
# proof-of-claim transfer batches
# ==========================================================================
@core_bp.route("/insolvencies/<insolvency_id>/poc-transfers", methods=["POST"])
@endpoint([ROLE_RECEIVER_LIAISON])
def create_poc_transfer(insolvency_id):
    insolvency = domain.get_insolvency(insolvency_id)
    values = validate(
        get_body(),
        [F("receiver_batch_ref", "str"), F("records", "array", min_items=1)],
    )
    for index, record in enumerate(values["records"]):
        if not isinstance(record, dict):
            fail("ERR_INVALID_REQUEST", "records[%d] must be an object." % index)
    _require_not_closed(insolvency)

    for existing in store.poc_transfers.values():
        if (
            existing["insolvency_id"] == insolvency_id
            and existing["receiver_batch_ref"] == values["receiver_batch_ref"]
        ):
            fail(
                "ERR_INVALID_REQUEST",
                "receiver_batch_ref '%s' is already registered on this insolvency file."
                % values["receiver_batch_ref"],
            )

    row = {
        "insolvency_id": insolvency_id,
        "receiver_batch_ref": values["receiver_batch_ref"],
        "records": values["records"],
        "record_count": len(values["records"]),
        "converted_count": 0,
        "rejected_count": 0,
        "rejection_reasons": [],
        "status": "RECEIVED",
    }
    stamp_new(row)
    store.poc_transfers[row["id"]] = row
    return object_response(domain.serialize_transfer(row), 201)


@core_bp.route("/insolvencies/<insolvency_id>/poc-transfers", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_RECEIVER_LIAISON])
def list_poc_transfers(insolvency_id):
    domain.get_insolvency(insolvency_id)
    limit, offset = pagination()
    status = enum_filter("status", domain.TRANSFER_STATUSES)
    rows = [t for t in store.poc_transfers.values() if t["insolvency_id"] == insolvency_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_transfer(r) for r in page], limit, offset, total)


@core_bp.route("/insolvencies/<insolvency_id>/assessments", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_ASSESSMENT_OFFICER])
def list_insolvency_assessments(insolvency_id):
    domain.get_insolvency(insolvency_id)
    limit, offset = pagination()
    status = enum_filter("status", domain.ASSESSMENT_STATUSES)
    rows = domain.assessments_of_insolvency(insolvency_id)
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_assessment(r) for r in page], limit, offset, total)


@core_bp.route("/poc-transfers/<transfer_id>", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_RECEIVER_LIAISON])
def read_poc_transfer(transfer_id):
    row = domain.get_transfer(transfer_id)
    return object_response(domain.serialize_transfer(row))


POLICY_REQUIRED_KEYS = (
    "policy_number",
    "line_of_business",
    "policyholder_name",
    "policyholder_state_code",
    "effective_date",
    "expiration_date",
    "annual_premium_cents",
)
CLAIM_REQUIRED_KEYS = (
    "policy_number",
    "claimant_name",
    "claimant_state_code",
    "loss_date",
    "gross_loss_cents",
)


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict, tuple)) and len(value) == 0:
        return True
    return False


def _as_int(value, default=0):
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


@core_bp.route("/poc-transfers/<transfer_id>/convert", methods=["POST"])
@endpoint([ROLE_RECEIVER_LIAISON])
def convert_poc_transfer(transfer_id):
    transfer = domain.get_transfer(transfer_id)
    no_body()
    if transfer["status"] != "RECEIVED":
        fail(
            "ERR_TRANSFER_INVALID_STATE",
            "The proof-of-claim batch is no longer in RECEIVED.",
        )
    insolvency = domain.get_insolvency(transfer["insolvency_id"])
    _require_not_closed(insolvency)

    insolvency_id = transfer["insolvency_id"]
    converted = 0
    reasons = []

    for index, record in enumerate(transfer["records"]):
        reason = _conversion_reason(record, insolvency_id)
        if reason is not None:
            reasons.append("%d:%s" % (index, reason))
            continue
        if record.get("record_type") == "POLICY":
            _materialise_policy(record, insolvency_id, transfer_id)
        else:
            _materialise_claim(record, insolvency_id, transfer_id)
        converted += 1

    transfer["converted_count"] = converted
    transfer["rejected_count"] = len(reasons)
    transfer["rejection_reasons"] = reasons
    if not reasons:
        transfer["status"] = "CONVERTED"
    elif converted == 0:
        transfer["status"] = "REJECTED"
    else:
        transfer["status"] = "PARTIALLY_CONVERTED"
    touch(transfer)
    return object_response(domain.serialize_transfer(transfer))


def _conversion_reason(record, insolvency_id):
    """The first failing conversion check, or None when the record passes."""
    if not isinstance(record, dict):
        return "MISSING_REQUIRED_FIELD"
    record_type = record.get("record_type")
    if record_type not in ("POLICY", "CLAIM"):
        return "MISSING_REQUIRED_FIELD"

    required = POLICY_REQUIRED_KEYS if record_type == "POLICY" else CLAIM_REQUIRED_KEYS
    for key in required:
        if key not in record or _is_empty(record.get(key)):
            return "MISSING_REQUIRED_FIELD"

    line = record.get("line_of_business")
    if not _is_empty(line):
        if domain.profile_for_line(line) is None:
            return "UNKNOWN_LINE_OF_BUSINESS"

    if record_type == "CLAIM":
        if _match_policy(record.get("policy_number"), insolvency_id) is None:
            return "NO_MATCHING_POLICY"
    return None


def _match_policy(policy_number, insolvency_id):
    candidates = [
        p
        for p in domain.policies_of_insolvency(insolvency_id)
        if p["policy_number"] == policy_number
    ]
    if not candidates:
        return None
    return sort_rows(candidates)[0]


def _materialise_policy(record, insolvency_id, transfer_id):
    row = {
        "insolvency_id": insolvency_id,
        "source_transfer_id": transfer_id,
        "policy_number": _as_text(record.get("policy_number")),
        "line_of_business": record.get("line_of_business"),
        "policyholder_name": _as_text(record.get("policyholder_name")),
        "policyholder_state_code": _as_text(record.get("policyholder_state_code")),
        "policyholder_net_worth_cents": _as_int(record.get("policyholder_net_worth_cents")),
        "effective_date": _as_text(record.get("effective_date")),
        "expiration_date": _as_text(record.get("expiration_date")),
        "annual_premium_cents": _as_int(record.get("annual_premium_cents")),
        "large_deductible_cents": _as_int(record.get("large_deductible_cents")),
        "self_insured_retention_cents": _as_int(record.get("self_insured_retention_cents")),
        "collateral_held_cents": _as_int(record.get("collateral_held_cents")),
        "status": "IMPORTED",
        "cancellation_date": None,
        "unexpired_days": 0,
    }
    stamp_new(row)
    store.policies[row["id"]] = row
    return row


def _materialise_claim(record, insolvency_id, transfer_id):
    policy = _match_policy(record.get("policy_number"), insolvency_id)
    row = {
        "insolvency_id": insolvency_id,
        "policy_id": policy["id"],
        "source_transfer_id": transfer_id,
        "claim_number": _as_text(record.get("claim_number")),
        "claimant_name": _as_text(record.get("claimant_name")),
        "claimant_state_code": _as_text(record.get("claimant_state_code")),
        "loss_date": _as_text(record.get("loss_date")),
        "filed_at_utc": now_iso(),
        "gross_loss_cents": _as_int(record.get("gross_loss_cents")),
        "punitive_damages_cents": _as_int(record.get("punitive_damages_cents")),
        "covered_basis_cents": 0,
        "attachment_point_cents": 0,
        "covered_layer_cents": 0,
        "net_payable_cents": 0,
        "alt_net_payable_cents": 0,
        "cap_binding": "NONE",
        "paid_amount_cents": 0,
        "status": "RECEIVED",
        "screened_by_user_id": None,
        "approved_by_user_id": None,
        "recommended_by_vendor_name": None,
        "recommended_amount_cents": None,
        "recommended_at_utc": None,
        "remand_count": 0,
        "pre_referral_status": None,
        "referred_to_state_code": None,
        "denial_reason": None,
        "sequence": store.next_sequence("claim"),
    }
    stamp_new(row)
    store.claims[row["id"]] = row
    return row


# ==========================================================================
# logical clock
# ==========================================================================
@core_bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def set_clock():
    values = validate(get_body(), [F("to_iso8601", "datetime")])
    store.now = parse_datetime(values["to_iso8601"])

    swept = 0
    for invoice in sort_rows(list(store.member_assessments.values())):
        if invoice["billing_status"] != "INVOICED":
            continue
        assessment = store.assessments.get(invoice["assessment_id"])
        if assessment is None or not assessment.get("certified_at_utc"):
            continue
        certified = parse_datetime(assessment["certified_at_utc"])
        if certified is None:
            continue
        if certified + timedelta(days=DELINQUENCY_GRACE_DAYS) < now_dt():
            invoice["billing_status"] = "DELINQUENT"
            touch(invoice)
            swept += 1

    return object_response(
        {
            "current_utc": fmt_dt(now_dt()),
            "delinquent_member_assessment_count": swept,
        }
    )
