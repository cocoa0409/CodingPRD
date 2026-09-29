"""Covered claims, other insurance, vendor engagements, recommendation, approval, referrals."""

from flask import Blueprint

import domain
from auth import (
    ROLE_ASSOCIATION_ADMIN,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_CLAIMS_COMMITTEE_OFFICER,
    ROLE_COVERAGE_ANALYST,
    ROLE_DEFENSE_COUNSEL,
    ROLE_RECEIVER_LIAISON,
    VENDOR_TYPE_FOR_ROLE,
    acting_role,
    acting_user_id,
    endpoint,
)
from calc import ASSOCIATION_STATE_CODE, add_hours, vendor_invoice_fee
from envelope import list_response, object_response
from errors import fail
from shape import F, enum_filter, get_body, paginate, pagination, str_filter, validate
from store import now_iso, parse_date, parse_datetime, sort_rows, stamp_new, store, touch

claims_bp = Blueprint("claims", __name__)

CLAIM_WRITE_OPEN_STATUSES = ("SCREENED_ELIGIBLE", "ADJUSTING", "RECOMMENDED")


# --------------------------------------------------------------------------
# shared guards
# --------------------------------------------------------------------------
def _acting_engagement(claim_id):
    """Validation priority 3: the acting vendor engagement on the target claim.

    Runs ahead of every existence check, so a vendor addressing a claim it is not
    engaged on -- including a claim that does not exist -- gets 403.
    """
    vendor_type = VENDOR_TYPE_FOR_ROLE.get(acting_role())
    user_id = acting_user_id()
    row = store.vendor_assignments.get(user_id)
    if (
        row is None
        or row["claim_id"] != claim_id
        or row["status"] != "ASSIGNED"
        or row["vendor_type"] != vendor_type
    ):
        fail(
            "ERR_NOT_ASSIGNED_ADJUSTER",
            "X-User-ID is not an ASSIGNED %s engagement on this claim." % vendor_type,
        )
    return row


def _require_claim_status(claim, allowed):
    if claim["status"] not in allowed:
        fail(
            "ERR_CLAIM_INVALID_STATE",
            "A claim in '%s' does not admit this operation." % claim["status"],
        )


# ==========================================================================
# covered claims
# ==========================================================================
@claims_bp.route("/claims", methods=["POST"])
@endpoint([ROLE_RECEIVER_LIAISON, ROLE_COVERAGE_ANALYST])
def create_claim():
    body = get_body()

    # priority 13: body foreign keys resolve before request-shape validation
    raw_insolvency_id = body.get("insolvency_id")
    if isinstance(raw_insolvency_id, str) and raw_insolvency_id not in store.insolvencies:
        fail(
            "ERR_REFERENCED_ROW_NOT_FOUND",
            "No insolvency file matches insolvency_id '%s'." % raw_insolvency_id,
        )
    raw_policy_id = body.get("policy_id")
    if isinstance(raw_policy_id, str) and raw_policy_id not in store.policies:
        fail(
            "ERR_REFERENCED_ROW_NOT_FOUND",
            "No transferred policy matches policy_id '%s'." % raw_policy_id,
        )

    values = validate(
        body,
        [
            F("insolvency_id", "str"),
            F("policy_id", "str"),
            F("claim_number", "str"),
            F("claimant_name", "str"),
            F("claimant_state_code", "str", state_code=True),
            F("loss_date", "date"),
            F("gross_loss_cents", "int", exclusive_minimum=0),
            F("punitive_damages_cents", "int", required=False, default=0, minimum=0),
        ],
    )
    if values["insolvency_id"] not in store.insolvencies:
        fail(
            "ERR_REFERENCED_ROW_NOT_FOUND",
            "No insolvency file matches insolvency_id '%s'." % values["insolvency_id"],
        )
    if values["policy_id"] not in store.policies:
        fail(
            "ERR_REFERENCED_ROW_NOT_FOUND",
            "No transferred policy matches policy_id '%s'." % values["policy_id"],
        )

    insolvency = store.insolvencies[values["insolvency_id"]]
    if insolvency["status"] != "TRIGGERED":
        fail(
            "ERR_INSOLVENCY_NOT_TRIGGERED",
            "The triggering event has not been recorded on this insolvency file.",
        )

    deadline = parse_datetime(insolvency.get("proof_of_claim_deadline_utc"))
    if deadline is not None and store.now > deadline:
        fail("ERR_FILING_DEADLINE_PASSED", "The proof-of-claim filing deadline has passed.")

    for sibling in domain.claims_of_policy(values["policy_id"]):
        if sibling["claim_number"] == values["claim_number"]:
            fail(
                "ERR_DUPLICATE_CLAIM",
                "claim_number '%s' is already presented against this policy."
                % values["claim_number"],
            )

    row = {
        "insolvency_id": values["insolvency_id"],
        "policy_id": values["policy_id"],
        "source_transfer_id": None,
        "claim_number": values["claim_number"],
        "claimant_name": values["claimant_name"],
        "claimant_state_code": values["claimant_state_code"],
        "loss_date": values["loss_date"],
        "filed_at_utc": now_iso(),
        "gross_loss_cents": values["gross_loss_cents"],
        "punitive_damages_cents": values["punitive_damages_cents"],
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
    return object_response(domain.serialize_claim(row), 201)


@claims_bp.route("/claims", methods=["GET"])
@endpoint(
    [
        ROLE_ASSOCIATION_ADMIN,
        ROLE_RECEIVER_LIAISON,
        ROLE_COVERAGE_ANALYST,
        ROLE_CLAIMS_COMMITTEE_OFFICER,
    ]
)
def list_claims():
    limit, offset = pagination()
    insolvency_id = str_filter("insolvency_id")
    policy_id = str_filter("policy_id")
    source_transfer_id = str_filter("source_transfer_id")
    status = enum_filter("status", domain.CLAIM_STATUSES)

    rows = list(store.claims.values())
    if insolvency_id is not None:
        rows = [c for c in rows if c["insolvency_id"] == insolvency_id]
    if policy_id is not None:
        rows = [c for c in rows if c["policy_id"] == policy_id]
    if source_transfer_id is not None:
        rows = [c for c in rows if c["source_transfer_id"] == source_transfer_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_claim(r) for r in page], limit, offset, total)


@claims_bp.route("/claims/<claim_id>", methods=["GET"])
@endpoint(
    [
        ROLE_ASSOCIATION_ADMIN,
        ROLE_RECEIVER_LIAISON,
        ROLE_COVERAGE_ANALYST,
        ROLE_CLAIMS_COMMITTEE_OFFICER,
        ROLE_CLAIMS_ADJUSTER,
        ROLE_DEFENSE_COUNSEL,
    ]
)
def read_claim(claim_id):
    row = domain.get_claim(claim_id)
    return object_response(domain.serialize_claim(row))


@claims_bp.route("/claims/<claim_id>/settlement-worksheet", methods=["GET"])
@endpoint([ROLE_COVERAGE_ANALYST, ROLE_CLAIMS_COMMITTEE_OFFICER, ROLE_CLAIMS_ADJUSTER])
def read_settlement_worksheet(claim_id):
    claim = domain.get_claim(claim_id)
    policy = store.policies.get(claim["policy_id"])
    profile = domain.profile_for_line(policy["line_of_business"]) if policy else None
    terms = domain.claim_payable_terms(claim) or {}
    return object_response(
        {
            "claim_id": claim["id"],
            "cap_order_mode": profile["cap_order_mode"] if profile else None,
            "covered_basis_cents": claim["covered_basis_cents"],
            "attachment_point_cents": claim["attachment_point_cents"],
            "covered_layer_cents": claim["covered_layer_cents"],
            "other_insurance_recoverable_cents": domain.other_insurance_recoverable(claim["id"]),
            "statutory_deductible_cents": terms.get("statutory_deductible_cents", 0),
            "per_claim_cap_cents": terms.get("per_claim_cap_cents", 0),
            "remaining_aggregate_cents": terms.get("remaining_aggregate_cents", 0),
            "net_payable_cents": claim["net_payable_cents"],
            "alt_net_payable_cents": claim["alt_net_payable_cents"],
            "variant_delta_cents": int(claim["net_payable_cents"] or 0)
            - int(claim["alt_net_payable_cents"] or 0),
            "cap_binding": claim["cap_binding"],
        }
    )


@claims_bp.route("/claims/<claim_id>/screen", methods=["POST"])
@endpoint([ROLE_COVERAGE_ANALYST])
def screen_claim(claim_id):
    claim = domain.get_claim(claim_id)
    values = validate(
        get_body(),
        [
            F("decision", "enum", enum=("COVERED", "DENIED")),
            F("denial_reason", "str", required=False),
        ],
    )
    _require_claim_status(claim, ("RECEIVED",))

    policy = domain.get_policy(claim["policy_id"])
    if policy["status"] != "CANCELLED_BY_ORDER":
        fail(
            "ERR_POLICY_NOT_CANCELLED",
            "The claim's transferred policy is not CANCELLED_BY_ORDER.",
        )

    profile = domain.profile_for_line(policy["line_of_business"])
    if profile is not None:
        threshold = int(profile["net_worth_exclusion_threshold_cents"])
        if int(policy["policyholder_net_worth_cents"] or 0) >= threshold:
            fail(
                "ERR_NET_WORTH_EXCLUSION",
                "The policyholder's net worth is at or above the line's exclusion threshold.",
            )
    else:
        fail(
            "ERR_COVERAGE_PROFILE_MISSING",
            "No coverage configuration row exists for line '%s'." % policy["line_of_business"],
        )

    claim["screened_by_user_id"] = acting_user_id()
    if values["decision"] == "COVERED":
        claim["status"] = "SCREENED_ELIGIBLE"
        domain.recompute_claim_payable(claim)
    else:
        claim["status"] = "DENIED_NOT_COVERED"
        claim["denial_reason"] = values["denial_reason"]
        claim["net_payable_cents"] = 0
        domain.close_assigned_vendor_assignments(claim["id"])
    touch(claim)
    return object_response(domain.serialize_claim(claim))


# ==========================================================================
# other insurance
# ==========================================================================
@claims_bp.route("/claims/<claim_id>/other-insurance", methods=["POST"])
@endpoint([ROLE_COVERAGE_ANALYST])
def create_other_insurance(claim_id):
    claim = domain.get_claim(claim_id)
    values = validate(
        get_body(),
        [
            F("carrier_name", "str"),
            F("policy_number", "str"),
            F("coverage_type", "enum", enum=domain.COVERAGE_TYPES),
            F("stated_limit_cents", "int", exclusive_minimum=0),
            F("expected_claim_version", "int"),
        ],
    )
    if values["expected_claim_version"] != claim["version"]:
        fail(
            "ERR_STALE_CLAIM_VERSION",
            "expected_claim_version %s does not match the claim's current version %s."
            % (values["expected_claim_version"], claim["version"]),
        )
    _require_claim_status(claim, CLAIM_WRITE_OPEN_STATUSES)

    row = {
        "claim_id": claim_id,
        "carrier_name": values["carrier_name"],
        "policy_number": values["policy_number"],
        "coverage_type": values["coverage_type"],
        "stated_limit_cents": values["stated_limit_cents"],
        "recovered_cents": 0,
        "status": "UNEXHAUSTED",
        "sequence": store.next_sequence("oic:%s" % claim_id),
    }
    stamp_new(row)
    store.other_insurance[row["id"]] = row
    touch(claim)
    return object_response(domain.serialize_layer(row), 201)


@claims_bp.route("/claims/<claim_id>/other-insurance/<coverage_id>", methods=["PATCH"])
@endpoint([ROLE_COVERAGE_ANALYST])
def update_other_insurance(claim_id, coverage_id):
    claim = domain.get_claim(claim_id)
    layer = store.other_insurance.get(coverage_id)
    if layer is None or layer["claim_id"] != claim_id:
        fail(
            "ERR_CHILD_RESOURCE_NOT_FOUND",
            "No other-insurance layer '%s' belongs to claim '%s'." % (coverage_id, claim_id),
        )

    values = validate(
        get_body(),
        [
            F("status", "enum", enum=domain.OIC_STATUSES),
            F("recovered_cents", "int", required=False, minimum=0),
        ],
    )
    recovered = values["recovered_cents"]
    if recovered is not None and recovered > int(layer["stated_limit_cents"]):
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'recovered_cents' must not exceed the layer's stated_limit_cents.",
        )

    _require_claim_status(claim, CLAIM_WRITE_OPEN_STATUSES)

    target = values["status"]
    current = layer["status"]
    allowed = {
        "UNEXHAUSTED": ("PURSUING",),
        "PURSUING": ("EXHAUSTED", "CARRIER_DENIED"),
    }
    if target not in allowed.get(current, ()):
        fail(
            "ERR_CLAIM_INVALID_STATE",
            "An other-insurance layer in '%s' cannot move to '%s'." % (current, target),
        )

    layer["status"] = target
    if target == "EXHAUSTED":
        layer["recovered_cents"] = recovered or 0
    touch(layer)

    if target in ("EXHAUSTED", "CARRIER_DENIED"):
        domain.recompute_claim_payable(claim)
        touch(claim)
    return object_response(domain.serialize_layer(layer))


@claims_bp.route("/claims/<claim_id>/other-insurance", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_COVERAGE_ANALYST, ROLE_CLAIMS_COMMITTEE_OFFICER])
def list_other_insurance(claim_id):
    domain.get_claim(claim_id)
    limit, offset = pagination()
    status = enum_filter("status", domain.OIC_STATUSES)
    rows = domain.layers_of_claim(claim_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_layer(r) for r in page], limit, offset, total)


# ==========================================================================
# vendor engagements
# ==========================================================================
@claims_bp.route("/claims/<claim_id>/vendor-assignments", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def create_vendor_assignment(claim_id):
    claim = domain.get_claim(claim_id)
    values = validate(
        get_body(),
        [
            F("vendor_type", "enum", enum=domain.VENDOR_TYPES),
            F("vendor_name", "str"),
            F("settlement_authority_cents", "int", minimum=0),
            F("hourly_rate_cents", "int", exclusive_minimum=0),
            F("engagement_start", "date"),
            F("engagement_end", "date"),
        ],
    )
    start = parse_date(values["engagement_start"])
    end = parse_date(values["engagement_end"])
    if end < start:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'engagement_end' must fall on or after 'engagement_start'.",
        )

    _require_claim_status(claim, CLAIM_WRITE_OPEN_STATUSES)

    live_same_type = [
        a
        for a in domain.assignments_of_claim(claim_id)
        if a["status"] == "ASSIGNED" and a["vendor_type"] == values["vendor_type"]
    ]
    for existing in live_same_type:
        other_start = parse_date(existing["engagement_start"])
        other_end = parse_date(existing["engagement_end"])
        if other_start is None or other_end is None:
            continue
        # closed intervals: touching endpoints collide
        if start <= other_end and other_start <= end:
            fail(
                "ERR_ADJUSTER_ENGAGEMENT_OVERLAP",
                "The engagement window intersects a live %s engagement on this claim."
                % values["vendor_type"],
            )

    row = {
        "claim_id": claim_id,
        "vendor_type": values["vendor_type"],
        "vendor_name": values["vendor_name"],
        "settlement_authority_cents": values["settlement_authority_cents"],
        "hourly_rate_cents": values["hourly_rate_cents"],
        "engagement_start": values["engagement_start"],
        "engagement_end": values["engagement_end"],
        "hours_logged": 0,
        "fees_accrued_cents": 0,
        "status": "ASSIGNED",
    }
    stamp_new(row)
    store.vendor_assignments[row["id"]] = row

    # the older live engagement of this vendor_type is superseded, freezing its fees
    for existing in live_same_type:
        existing["status"] = "SUPERSEDED"
        touch(existing)

    if values["vendor_type"] == "ADJUSTER" and claim["status"] == "SCREENED_ELIGIBLE":
        claim["status"] = "ADJUSTING"
    touch(claim)
    return object_response(domain.serialize_assignment(row), 201)


@claims_bp.route("/claims/<claim_id>/vendor-assignments", methods=["GET"])
@endpoint(
    [
        ROLE_ASSOCIATION_ADMIN,
        ROLE_COVERAGE_ANALYST,
        ROLE_CLAIMS_COMMITTEE_OFFICER,
        ROLE_CLAIMS_ADJUSTER,
        ROLE_DEFENSE_COUNSEL,
    ]
)
def list_vendor_assignments(claim_id):
    domain.get_claim(claim_id)
    limit, offset = pagination()
    vendor_type = enum_filter("vendor_type", domain.VENDOR_TYPES)
    status = enum_filter("status", domain.VENDOR_STATUSES)
    rows = domain.assignments_of_claim(claim_id)
    if vendor_type is not None:
        rows = [a for a in rows if a["vendor_type"] == vendor_type]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_assignment(r) for r in page], limit, offset, total)


@claims_bp.route(
    "/claims/<claim_id>/vendor-assignments/<assignment_id>/invoices", methods=["POST"]
)
@endpoint([ROLE_CLAIMS_ADJUSTER, ROLE_DEFENSE_COUNSEL])
def create_vendor_invoice(claim_id, assignment_id):
    acting = _acting_engagement(claim_id)
    domain.get_claim(claim_id)

    assignment = store.vendor_assignments.get(assignment_id)
    if assignment is None or assignment["claim_id"] != claim_id:
        fail(
            "ERR_CHILD_RESOURCE_NOT_FOUND",
            "No vendor engagement '%s' belongs to claim '%s'." % (assignment_id, claim_id),
        )

    values = validate(get_body(), [F("hours", "number", minimum=0), F("invoice_ref", "str")])

    if assignment["id"] != acting["id"] or assignment["status"] != "ASSIGNED":
        fail(
            "ERR_NOT_ASSIGNED_ADJUSTER",
            "Invoices may only be posted against the acting engagement while it is ASSIGNED.",
        )

    fee = vendor_invoice_fee(values["hours"], assignment["hourly_rate_cents"])
    assignment["fees_accrued_cents"] = int(assignment["fees_accrued_cents"] or 0) + fee
    assignment["hours_logged"] = add_hours(assignment["hours_logged"], values["hours"])
    touch(assignment)
    return object_response(domain.serialize_assignment(assignment), 201)


# ==========================================================================
# recommendation, remand, approval
# ==========================================================================
@claims_bp.route("/claims/<claim_id>/recommend", methods=["POST"])
@endpoint([ROLE_CLAIMS_ADJUSTER])
def recommend_claim(claim_id):
    acting = _acting_engagement(claim_id)
    claim = domain.get_claim(claim_id)
    values = validate(
        get_body(),
        [
            F("recommended_amount_cents", "int", minimum=0),
            F("note", "str", required=False),
        ],
    )
    _require_claim_status(claim, ("ADJUSTING",))

    amount = values["recommended_amount_cents"]
    if amount > int(acting["settlement_authority_cents"] or 0):
        fail(
            "ERR_ADJUSTER_AUTHORITY_EXCEEDED",
            "recommended_amount_cents exceeds the engagement's delegated settlement authority.",
        )
    if amount > int(claim["net_payable_cents"] or 0):
        fail(
            "ERR_OVERPAYMENT",
            "recommended_amount_cents exceeds the claim's statutory net payable.",
        )

    claim["status"] = "RECOMMENDED"
    claim["recommended_amount_cents"] = amount
    claim["recommended_by_vendor_name"] = acting["vendor_name"]
    claim["recommended_at_utc"] = now_iso()
    touch(claim)
    return object_response(domain.serialize_claim(claim))


@claims_bp.route("/claims/<claim_id>/remand", methods=["POST"])
@endpoint([ROLE_CLAIMS_COMMITTEE_OFFICER])
def remand_claim(claim_id):
    claim = domain.get_claim(claim_id)
    values = validate(get_body(), [F("remand_reason", "str")])

    if int(claim["remand_count"] or 0) >= 2:
        fail(
            "ERR_REMAND_LIMIT_REACHED",
            "The claim has already been remanded twice.",
        )
    _require_claim_status(claim, ("RECOMMENDED",))

    claim["status"] = "ADJUSTING"
    claim["remand_count"] = int(claim["remand_count"] or 0) + 1
    claim["recommended_amount_cents"] = None
    claim["recommended_by_vendor_name"] = None
    claim["recommended_at_utc"] = None
    claim["denial_reason"] = claim["denial_reason"]
    touch(claim)
    _ = values
    return object_response(domain.serialize_claim(claim))


@claims_bp.route("/claims/<claim_id>/approve", methods=["POST"])
@endpoint([ROLE_CLAIMS_COMMITTEE_OFFICER])
def approve_claim(claim_id):
    # priority 5 runs ahead of the claim existence check; with no claim there is no
    # screened_by_user_id to collide with, so the check passes vacuously
    existing = store.claims.get(claim_id)
    if (
        existing is not None
        and existing["screened_by_user_id"] is not None
        and existing["screened_by_user_id"] == acting_user_id()
    ):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The officer who screened this claim may not approve it.",
        )

    claim = domain.get_claim(claim_id)
    validate(get_body(), [F("approval_note", "str", required=False)])
    _require_claim_status(claim, ("RECOMMENDED",))

    for layer in domain.layers_of_claim(claim_id):
        if layer["status"] not in ("EXHAUSTED", "CARRIER_DENIED"):
            fail(
                "ERR_OTHER_INSURANCE_NOT_EXHAUSTED",
                "Every other-insurance layer must resolve before approval.",
            )

    policy = domain.get_policy(claim["policy_id"])
    profile = domain.profile_for_line(policy["line_of_business"])
    aggregate_cap = int(profile["per_policy_aggregate_cap_cents"]) if profile else 0
    remaining = max(0, aggregate_cap - domain.aggregate_paid_cents(policy["id"]))
    if int(claim["net_payable_cents"] or 0) > remaining:
        fail(
            "ERR_AGGREGATE_CAP_EXHAUSTED",
            "The policy's remaining aggregate room cannot absorb this claim's net payable.",
        )

    claim["approved_by_user_id"] = acting_user_id()
    claim["status"] = "APPROVED"
    domain.recompute_claim_payable(claim)
    touch(claim)
    return object_response(domain.serialize_claim(claim))


# ==========================================================================
# sister-association referrals
# ==========================================================================
@claims_bp.route("/claims/<claim_id>/referrals", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def create_referral(claim_id):
    claim = domain.get_claim(claim_id)
    values = validate(
        get_body(),
        [
            F("target_state_code", "str", state_code=True),
            F("basis", "enum", enum=domain.REFERRAL_BASES),
        ],
    )
    if values["target_state_code"] == ASSOCIATION_STATE_CODE:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'target_state_code' must not be this association's own state code '%s'."
            % ASSOCIATION_STATE_CODE,
        )

    for existing in domain.referrals_of_claim(claim_id):
        if existing["status"] == "OPEN":
            fail(
                "ERR_REFERRAL_ALREADY_OPEN",
                "A sister-association referral on this claim is still open.",
            )

    _require_claim_status(claim, ("SCREENED_ELIGIBLE", "ADJUSTING"))

    policy = domain.get_policy(claim["policy_id"])
    if values["basis"] == "POLICYHOLDER_RESIDENCE":
        basis_state_code = policy["policyholder_state_code"]
    else:
        basis_state_code = claim["claimant_state_code"]
    if basis_state_code != values["target_state_code"]:
        fail(
            "ERR_REFERRAL_BASIS_MISMATCH",
            "The asserted basis resolves to '%s', not to target_state_code '%s'."
            % (basis_state_code, values["target_state_code"]),
        )

    row = {
        "claim_id": claim_id,
        "target_state_code": values["target_state_code"],
        "basis": values["basis"],
        "basis_state_code": basis_state_code,
        "status": "OPEN",
        "response_note": None,
        "responded_at_utc": None,
    }
    stamp_new(row)
    store.referrals[row["id"]] = row

    claim["pre_referral_status"] = claim["status"]
    claim["status"] = "REFERRAL_PENDING"
    touch(claim)
    return object_response(domain.serialize_referral(row), 201)


@claims_bp.route("/claims/<claim_id>/referrals", methods=["GET"])
@endpoint([ROLE_ASSOCIATION_ADMIN, ROLE_COVERAGE_ANALYST, ROLE_CLAIMS_COMMITTEE_OFFICER])
def list_referrals(claim_id):
    domain.get_claim(claim_id)
    limit, offset = pagination()
    status = enum_filter("status", domain.REFERRAL_STATUSES)
    rows = domain.referrals_of_claim(claim_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_rows(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_referral(r) for r in page], limit, offset, total)


@claims_bp.route("/claims/<claim_id>/referrals/<referral_id>/respond", methods=["POST"])
@endpoint([ROLE_ASSOCIATION_ADMIN])
def respond_to_referral(claim_id, referral_id):
    claim = domain.get_claim(claim_id)
    referral = store.referrals.get(referral_id)
    if referral is None or referral["claim_id"] != claim_id:
        fail(
            "ERR_CHILD_RESOURCE_NOT_FOUND",
            "No referral '%s' belongs to claim '%s'." % (referral_id, claim_id),
        )

    values = validate(
        get_body(),
        [
            F("disposition", "enum", enum=("ACCEPTED", "DECLINED")),
            F("response_note", "str", required=False),
        ],
    )
    if referral["status"] != "OPEN":
        fail(
            "ERR_REFERRAL_ALREADY_ANSWERED",
            "The referral has already been answered.",
        )

    referral["status"] = values["disposition"]
    referral["response_note"] = values["response_note"]
    referral["responded_at_utc"] = now_iso()
    touch(referral)

    if values["disposition"] == "ACCEPTED":
        claim["status"] = "REFERRED_OUT"
        claim["referred_to_state_code"] = referral["target_state_code"]
        claim["pre_referral_status"] = None
        claim["net_payable_cents"] = 0
        domain.close_assigned_vendor_assignments(claim_id)
    else:
        claim["status"] = claim["pre_referral_status"] or "SCREENED_ELIGIBLE"
        claim["pre_referral_status"] = None
    touch(claim)
    return object_response(domain.serialize_referral(referral))
