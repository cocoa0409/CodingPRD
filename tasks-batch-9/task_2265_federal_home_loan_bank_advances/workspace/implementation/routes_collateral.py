"""CollateralAsset, SafekeepingReceipt, verification review and finding endpoints."""

from flask import g

import config
import services as svc
from envelope import list_response, object_response
from errors import ApiError
from routing import (
    endpoint,
    get_asset,
    get_finding,
    get_member,
    get_receipt,
    get_review,
)
from store import db, parse_dt, touch
from validation import (
    get_body,
    present,
    q_enum,
    q_pagination,
    q_str,
    v_bool,
    v_datetime,
    v_enum,
    v_int,
    v_string,
)

_ASSET_READ_ROLES = [config.ROLE_SYSTEM_ADMIN, config.ROLE_CREDIT_OFFICER,
                     config.ROLE_TREASURY_OFFICER, config.ROLE_COLLATERAL_CUSTODIAN,
                     config.ROLE_COLLATERAL_REVIEW_AUDITOR]
_REVIEW_READ_ROLES = [config.ROLE_SYSTEM_ADMIN, config.ROLE_CREDIT_OFFICER,
                      config.ROLE_TREASURY_OFFICER, config.ROLE_COLLATERAL_REVIEW_AUDITOR]


def _asset_input(body):
    """Read the shared pledge-description payload used by create and substitute."""
    fields = {}
    fields["asset_class"] = v_enum(body, "asset_class", config.ASSET_CLASSES)
    fields["market_value_cents"] = v_int(body, "market_value_cents", minimum=1)
    fields["appraisal_date"] = v_datetime(body, "appraisal_date")
    fields["unpaid_principal_balance_cents"] = v_int(
        body, "unpaid_principal_balance_cents", required=False, default=0, minimum=0)
    fields["ltv_bps"] = v_int(body, "ltv_bps", required=False, default=0,
                              minimum=0, maximum=20000)
    fields["delinquency_days"] = v_int(body, "delinquency_days", required=False,
                                       default=0, minimum=0)
    fields["documentation_status"] = v_enum(body, "documentation_status",
                                           config.DOCUMENTATION_STATUSES,
                                           required=False, default="COMPLETE")
    fields["custody_location"] = v_enum(body, "custody_location",
                                        config.CUSTODY_LOCATIONS,
                                        required=False, default="MEMBER_VAULT")
    return fields


# --------------------------------------------------------- collateral assets --


@endpoint("/fhlb/collateral-assets", ["POST"], [config.ROLE_TREASURY_OFFICER])
def create_collateral_asset():
    body = get_body()
    member_bank_id = v_string(body, "member_bank_id")
    fields = _asset_input(body)
    member = get_member(member_bank_id)
    svc.require_own_member(member["id"])
    if member["pledge_agreement_status"] != "EXECUTED":
        raise ApiError("ERR_PLEDGE_AGREEMENT_NOT_EXECUTED")
    asset = svc.create_asset(member, fields)
    return object_response(svc.serialize(asset), 201)


@endpoint("/fhlb/collateral-assets", ["GET"], _ASSET_READ_ROLES)
def list_collateral_assets():
    limit, offset = q_pagination()
    member_bank_id = q_str("member_bank_id")
    replaces_asset_id = q_str("replaces_asset_id")
    status = q_enum("status", config.ASSET_STATUSES)
    asset_class = q_enum("asset_class", config.ASSET_CLASSES)
    if svc.is_treasury():
        member_bank_id = g.user_id if member_bank_id in (None, g.user_id) else "\0"
    records = []
    for asset in db.assets.values():
        if member_bank_id is not None and asset["member_bank_id"] != member_bank_id:
            continue
        if replaces_asset_id is not None and asset["replaces_asset_id"] != replaces_asset_id:
            continue
        if status is not None and asset["status"] != status:
            continue
        if asset_class is not None and asset["asset_class"] != asset_class:
            continue
        records.append(asset)
    items, total = svc.paginate(records, limit, offset)
    return list_response(items, limit, offset, total)


@endpoint("/fhlb/collateral-assets/<collateral_asset_id>", ["GET"], _ASSET_READ_ROLES)
def read_collateral_asset(collateral_asset_id):
    asset = get_asset(collateral_asset_id)
    svc.require_own_member(asset["member_bank_id"])
    return object_response(svc.serialize(asset))


@endpoint("/fhlb/collateral-assets/<collateral_asset_id>/review-eligibility", ["POST"],
          [config.ROLE_CREDIT_OFFICER])
def review_asset_eligibility(collateral_asset_id):
    body = get_body()
    force_ineligible = v_bool(body, "force_ineligible", required=False, default=False)
    asset = get_asset(collateral_asset_id)
    member = get_member(asset["member_bank_id"])
    if asset["status"] not in ("UNDER_REVIEW", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")
    if member["pledge_agreement_status"] != "EXECUTED":
        raise ApiError("ERR_PLEDGE_AGREEMENT_NOT_EXECUTED")
    for finding in svc.asset_findings(asset["id"]):
        if finding["status"] == "UNRESOLVED":
            raise ApiError("ERR_CRITICAL_FINDINGS_OPEN")

    asset["effective_listing_mode"] = svc.effective_listing_mode(asset, member)
    asset["collateral_basis_cents"] = svc.collateral_basis(asset)

    failures = []
    if asset["documentation_status"] == "MISSING":
        failures.append(("DOCUMENTATION_MISSING", "ERR_DOCUMENTATION_MISSING"))
    if asset["ltv_bps"] > config.LTV_MAX_BPS:
        failures.append(("LTV_EXCEEDS_MAX", "ERR_LTV_EXCEEDS_MAX"))
    if asset["delinquency_days"] >= config.DELINQUENCY_INELIGIBLE_DAYS:
        failures.append(("DELINQUENT", "ERR_DELINQUENT_ASSET_INELIGIBLE"))
    if (asset["asset_class"] in config.SECURITIES_CLASSES
            and asset["effective_listing_mode"] == "BLANKET"):
        failures.append(("SECURITIES_NOT_DELIVERED", "ERR_SECURITIES_REQUIRE_DELIVERY"))

    if failures:
        if not force_ineligible:
            raise ApiError(failures[0][1])
        asset["status"] = "INELIGIBLE"
        asset["ineligibility_reason"] = failures[0][0]
        asset["discount_factor_bps"] = 0
        asset["lendable_value_cents"] = 0
    else:
        asset["status"] = "ELIGIBLE"
        asset["ineligibility_reason"] = "NONE"
        svc.refresh_asset(asset, member)
    touch(asset)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(asset))


@endpoint("/fhlb/collateral-assets/<collateral_asset_id>/documentation", ["PATCH"],
          [config.ROLE_COLLATERAL_CUSTODIAN])
def amend_asset_documentation(collateral_asset_id):
    body = get_body()
    documentation_status = v_enum(body, "documentation_status",
                                  config.DOCUMENTATION_STATUSES, required=False)
    custody_location = v_enum(body, "custody_location", config.CUSTODY_LOCATIONS,
                              required=False)
    delinquency_days = v_int(body, "delinquency_days", required=False, minimum=0)
    market_value_cents = v_int(body, "market_value_cents", required=False, minimum=1)
    ltv_bps = v_int(body, "ltv_bps", required=False, minimum=0, maximum=20000)
    appraisal_date = v_datetime(body, "appraisal_date", required=False)
    asset = get_asset(collateral_asset_id)
    member = get_member(asset["member_bank_id"])
    if asset["status"] not in ("ELIGIBLE", "INELIGIBLE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")
    if documentation_status is not None:
        asset["documentation_status"] = documentation_status
    if custody_location is not None:
        asset["custody_location"] = custody_location
    if delinquency_days is not None:
        asset["delinquency_days"] = delinquency_days
    if market_value_cents is not None:
        asset["market_value_cents"] = market_value_cents
    if ltv_bps is not None:
        asset["ltv_bps"] = ltv_bps
    if appraisal_date is not None:
        asset["appraisal_date"] = appraisal_date
    asset["status"] = "UNDER_REVIEW"
    svc.refresh_asset(asset, member)
    touch(asset)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(asset))


@endpoint("/fhlb/collateral-assets/<collateral_asset_id>/substitute", ["POST"],
          [config.ROLE_TREASURY_OFFICER])
def substitute_collateral_asset(collateral_asset_id):
    body = get_body()
    expected_version = v_int(body, "expected_member_bank_version")
    fields = _asset_input(body)
    outgoing = get_asset(collateral_asset_id)
    svc.require_own_member(outgoing["member_bank_id"])
    member = get_member(outgoing["member_bank_id"])
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION")
    if outgoing["status"] not in ("ELIGIBLE", "SUSPENDED", "INELIGIBLE"):
        raise ApiError("ERR_INVALID_STATE")
    if member["collateral_posture"] == "FROZEN":
        candidate = dict(fields)
        candidate["id"] = None
        candidate["status"] = "UNDER_REVIEW"
        if svc.hypothetical_lendable(candidate, member) < outgoing["lendable_value_cents"]:
            raise ApiError("ERR_SUBSTITUTION_REDUCES_LENDABLE_VALUE")
    replacement = svc.create_asset(member, fields, replaces_asset_id=outgoing["id"])
    outgoing["status"] = "SUBSTITUTED"
    outgoing["discount_factor_bps"] = 0
    outgoing["lendable_value_cents"] = 0
    touch(outgoing)
    for receipt in svc.asset_receipts(outgoing["id"]):
        if receipt["status"] in ("RECEIVED", "EXCEPTION"):
            receipt["status"] = "RETURNED"
            touch(receipt)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(replacement), 201)


# ------------------------------------------------------- safekeeping receipts --


@endpoint("/fhlb/collateral-assets/<collateral_asset_id>/safekeeping-receipts",
          ["POST"], [config.ROLE_COLLATERAL_CUSTODIAN])
def create_safekeeping_receipt(collateral_asset_id):
    body = get_body()
    file_count = v_int(body, "file_count", minimum=1)
    delivery_date = v_datetime(body, "delivery_date")
    return_date = v_datetime(body, "return_date")
    if parse_dt(return_date) <= parse_dt(delivery_date):
        raise ApiError("ERR_INVALID_REQUEST", "return_date must be later than delivery_date.")
    asset = get_asset(collateral_asset_id)
    if asset["status"] in ("INELIGIBLE", "SUBSTITUTED"):
        raise ApiError("ERR_ASSET_NOT_ELIGIBLE")
    new_start = parse_dt(delivery_date)
    new_end = parse_dt(return_date)
    buffer = config.CUSTODY_BUFFER_DAYS
    from datetime import timedelta
    for existing in svc.asset_receipts(asset["id"]):
        if existing["status"] not in ("PENDING_DELIVERY", "RECEIVED", "EXCEPTION"):
            continue
        old_start = parse_dt(existing["delivery_date"])
        old_end = parse_dt(existing["return_date"])
        if (new_start <= old_end + timedelta(days=buffer)
                and new_end >= old_start - timedelta(days=buffer)):
            raise ApiError("ERR_CUSTODY_WINDOW_CONFLICT")
    receipt = svc.create_receipt(asset["id"], file_count, delivery_date, return_date)
    return object_response(svc.serialize(receipt), 201)


@endpoint("/fhlb/safekeeping-receipts", ["GET"], _ASSET_READ_ROLES)
def list_safekeeping_receipts():
    limit, offset = q_pagination()
    collateral_asset_id = q_str("collateral_asset_id")
    member_bank_id = q_str("member_bank_id")
    status = q_enum("status", config.RECEIPT_STATUSES)
    if svc.is_treasury():
        if member_bank_id is not None and member_bank_id != g.user_id:
            raise ApiError("ERR_MEMBER_SCOPE_VIOLATION")
        if collateral_asset_id is not None:
            asset = db.assets.get(collateral_asset_id)
            if asset is not None and asset["member_bank_id"] != g.user_id:
                raise ApiError("ERR_MEMBER_SCOPE_VIOLATION")
        member_bank_id = g.user_id
    records = []
    for receipt in db.receipts.values():
        asset = db.assets.get(receipt["collateral_asset_id"])
        if collateral_asset_id is not None \
                and receipt["collateral_asset_id"] != collateral_asset_id:
            continue
        if member_bank_id is not None \
                and (asset is None or asset["member_bank_id"] != member_bank_id):
            continue
        if status is not None and receipt["status"] != status:
            continue
        records.append(receipt)
    items, total = svc.paginate(records, limit, offset)
    return list_response(items, limit, offset, total)


@endpoint("/fhlb/safekeeping-receipts/<safekeeping_receipt_id>", ["GET"],
          _ASSET_READ_ROLES)
def read_safekeeping_receipt(safekeeping_receipt_id):
    receipt = get_receipt(safekeeping_receipt_id)
    asset = db.assets.get(receipt["collateral_asset_id"])
    if asset is not None:
        svc.require_own_member(asset["member_bank_id"])
    return object_response(svc.serialize(receipt))


@endpoint("/fhlb/safekeeping-receipts/<safekeeping_receipt_id>/confirm", ["POST"],
          [config.ROLE_COLLATERAL_CUSTODIAN])
def confirm_safekeeping_receipt(safekeeping_receipt_id):
    body = get_body()
    outcome = v_enum(body, "outcome", config.RECEIPT_CONFIRM_OUTCOMES)
    exception_note = v_string(body, "exception_note", required=False)
    receipt = get_receipt(safekeeping_receipt_id)
    asset = get_asset(receipt["collateral_asset_id"])
    member = get_member(asset["member_bank_id"])
    if receipt["status"] != "PENDING_DELIVERY":
        raise ApiError("ERR_INVALID_STATE")
    if db.now() < parse_dt(receipt["delivery_date"]):
        raise ApiError("ERR_INVALID_STATE")
    if outcome == "RECEIVED":
        receipt["status"] = "RECEIVED"
        receipt["received_at"] = db.now_iso()
        asset["custody_location"] = "FHLB_SAFEKEEPING"
    else:
        receipt["status"] = "EXCEPTION"
        receipt["exception_note"] = exception_note
        asset["documentation_status"] = "EXCEPTION"
        asset["status"] = "UNDER_REVIEW"
    touch(receipt)
    svc.refresh_asset(asset, member)
    touch(asset)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(receipt))


# ------------------------------------------------- verification reviews -------


@endpoint("/fhlb/collateral-verification-reviews", ["POST"],
          [config.ROLE_COLLATERAL_REVIEW_AUDITOR])
def create_verification_review():
    body = get_body()
    member_bank_id = v_string(body, "member_bank_id")
    window_start = v_datetime(body, "window_start")
    window_end = v_datetime(body, "window_end")
    sample_size = v_int(body, "sample_size", minimum=1)
    if parse_dt(window_end) <= parse_dt(window_start):
        raise ApiError("ERR_INVALID_REQUEST", "window_end must be later than window_start.")
    member = get_member(member_bank_id)
    new_start = parse_dt(window_start)
    new_end = parse_dt(window_end)
    for existing in db.reviews.values():
        if existing["member_bank_id"] != member["id"] or existing["status"] == "CLOSED":
            continue
        old_start = parse_dt(existing["window_start"])
        old_end = parse_dt(existing["window_end"])
        if new_start < old_end and old_start < new_end:
            raise ApiError("ERR_REVIEW_WINDOW_OVERLAP")
    review = svc.create_review(member["id"], window_start, window_end, sample_size)
    return object_response(svc.serialize(review), 201)


@endpoint("/fhlb/collateral-verification-reviews", ["GET"], _REVIEW_READ_ROLES)
def list_verification_reviews():
    limit, offset = q_pagination()
    member_bank_id = q_str("member_bank_id")
    status = q_enum("status", config.REVIEW_STATUSES)
    outcome = q_enum("outcome", config.REVIEW_OUTCOME_VALUES)
    if svc.is_treasury():
        member_bank_id = g.user_id if member_bank_id in (None, g.user_id) else "\0"
    records = []
    for review in db.reviews.values():
        if member_bank_id is not None and review["member_bank_id"] != member_bank_id:
            continue
        if status is not None and review["status"] != status:
            continue
        if outcome is not None and review["outcome"] != outcome:
            continue
        records.append(review)
    items, total = svc.paginate(records, limit, offset)
    return list_response(items, limit, offset, total)


@endpoint("/fhlb/collateral-verification-reviews/<collateral_verification_review_id>",
          ["GET"], _REVIEW_READ_ROLES)
def read_verification_review(collateral_verification_review_id):
    review = get_review(collateral_verification_review_id)
    svc.require_own_member(review["member_bank_id"])
    return object_response(svc.serialize(review))


@endpoint("/fhlb/collateral-verification-reviews/<collateral_verification_review_id>"
          "/begin-field-work", ["POST"], [config.ROLE_COLLATERAL_REVIEW_AUDITOR])
def begin_field_work(collateral_verification_review_id):
    get_body()
    review = get_review(collateral_verification_review_id)
    member = get_member(review["member_bank_id"])
    if review["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    if db.now() < parse_dt(review["window_start"]):
        raise ApiError("ERR_INVALID_STATE")
    if member["membership_status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")
    review["status"] = "FIELD_WORK"
    touch(review)
    return object_response(svc.serialize(review))


@endpoint("/fhlb/collateral-verification-reviews/<collateral_verification_review_id>"
          "/findings", ["POST"], [config.ROLE_COLLATERAL_REVIEW_AUDITOR])
def create_review_finding(collateral_verification_review_id):
    body = get_body()
    collateral_asset_id = v_string(body, "collateral_asset_id")
    finding_type = v_enum(body, "finding_type", config.FINDING_TYPES)
    severity = v_enum(body, "severity", config.SEVERITIES)
    review = get_review(collateral_verification_review_id)
    asset = get_asset(collateral_asset_id)
    if review["status"] != "FIELD_WORK":
        raise ApiError("ERR_INVALID_STATE")
    if asset["member_bank_id"] != review["member_bank_id"]:
        raise ApiError("ERR_ASSET_MEMBER_MISMATCH")
    finding = svc.create_finding(review["id"], asset["id"], finding_type, severity,
                                 g.user_id)
    return object_response(svc.serialize(finding), 201)


@endpoint("/fhlb/collateral-verification-reviews/<collateral_verification_review_id>"
          "/issue-findings", ["POST"], [config.ROLE_COLLATERAL_REVIEW_AUDITOR])
def issue_review_findings(collateral_verification_review_id):
    get_body()
    review = get_review(collateral_verification_review_id)
    if review["status"] != "FIELD_WORK":
        raise ApiError("ERR_INVALID_STATE")
    review["status"] = "FINDINGS_ISSUED"
    for finding in svc.review_findings(review["id"]):
        if finding["status"] == "OPEN" and finding["severity"] == "CRITICAL":
            review["status"] = "REMEDIATION"
            break
    touch(review)
    return object_response(svc.serialize(review))


@endpoint("/fhlb/collateral-verification-reviews/<collateral_verification_review_id>"
          "/retest", ["POST"], [config.ROLE_COLLATERAL_REVIEW_AUDITOR])
def retest_review(collateral_verification_review_id):
    get_body()
    review = get_review(collateral_verification_review_id)
    if review["status"] != "REMEDIATION":
        raise ApiError("ERR_INVALID_STATE")
    if review["retest_count"] >= config.MAX_RETESTS:
        raise ApiError("ERR_RETEST_LIMIT_EXCEEDED")
    for finding in svc.review_findings(review["id"]):
        if finding["severity"] == "CRITICAL" and finding["status"] == "OPEN":
            raise ApiError("ERR_CRITICAL_FINDINGS_OPEN")
    review["status"] = "FIELD_WORK"
    review["retest_count"] += 1
    touch(review)
    return object_response(svc.serialize(review))


@endpoint("/fhlb/collateral-verification-reviews/<collateral_verification_review_id>"
          "/close", ["POST"], [config.ROLE_COLLATERAL_REVIEW_AUDITOR])
def close_review(collateral_verification_review_id):
    get_body()
    review = get_review(collateral_verification_review_id)
    member = get_member(review["member_bank_id"])
    if review["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    for finding in svc.review_findings(review["id"]):
        if finding["severity"] == "CRITICAL" and finding["status"] == "OPEN":
            raise ApiError("ERR_CRITICAL_FINDINGS_OPEN")
    svc.close_review_cascade(review, member)
    touch(review)
    svc.bump_member(member)
    return object_response(svc.serialize(review))


# ----------------------------------------------------------- review findings --


@endpoint("/fhlb/review-findings", ["GET"], _REVIEW_READ_ROLES)
def list_review_findings():
    limit, offset = q_pagination()
    review_id = q_str("collateral_verification_review_id")
    asset_id = q_str("collateral_asset_id")
    status = q_enum("status", config.FINDING_STATUSES)
    severity = q_enum("severity", config.SEVERITIES)
    own_member = g.user_id if svc.is_treasury() else None
    records = []
    for finding in db.findings.values():
        if review_id is not None \
                and finding["collateral_verification_review_id"] != review_id:
            continue
        if asset_id is not None and finding["collateral_asset_id"] != asset_id:
            continue
        if status is not None and finding["status"] != status:
            continue
        if severity is not None and finding["severity"] != severity:
            continue
        if own_member is not None:
            review = db.reviews.get(finding["collateral_verification_review_id"])
            if review is None or review["member_bank_id"] != own_member:
                continue
        records.append(finding)
    items, total = svc.paginate(records, limit, offset)
    return list_response(items, limit, offset, total)


@endpoint("/fhlb/review-findings/<review_finding_id>", ["GET"], _REVIEW_READ_ROLES)
def read_review_finding(review_finding_id):
    finding = get_finding(review_finding_id)
    review = db.reviews.get(finding["collateral_verification_review_id"])
    if review is not None:
        svc.require_own_member(review["member_bank_id"])
    return object_response(svc.serialize(finding))


@endpoint("/fhlb/review-findings/<review_finding_id>/remediate", ["POST"],
          [config.ROLE_TREASURY_OFFICER])
def remediate_review_finding(review_finding_id):
    get_body()
    finding = get_finding(review_finding_id)
    review = get_review(finding["collateral_verification_review_id"])
    svc.require_own_member(review["member_bank_id"])
    if finding["status"] != "OPEN" \
            or review["status"] not in ("FINDINGS_ISSUED", "REMEDIATION"):
        raise ApiError("ERR_INVALID_STATE")
    finding["status"] = "REMEDIATED"
    touch(finding)
    return object_response(svc.serialize(finding))


@endpoint("/fhlb/review-findings/<review_finding_id>/waive", ["POST"],
          [config.ROLE_CREDIT_OFFICER])
def waive_review_finding(review_finding_id):
    get_body()
    finding = get_finding(review_finding_id)
    review = get_review(finding["collateral_verification_review_id"])
    if finding["status"] != "OPEN" \
            or review["status"] not in ("FINDINGS_ISSUED", "REMEDIATION"):
        raise ApiError("ERR_INVALID_STATE")
    if g.user_id == finding["raised_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    finding["status"] = "WAIVED"
    finding["waived_by_user_id"] = g.user_id
    touch(finding)
    return object_response(svc.serialize(finding))
