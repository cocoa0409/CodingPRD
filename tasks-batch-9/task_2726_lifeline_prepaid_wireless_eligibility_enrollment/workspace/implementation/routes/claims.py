"""Monthly subsidy claims, audit sampling and the clawback of PRD 3.8."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from routes.common import (CLAIM_STATUSES, COMPLIANCE_AUDITOR, FINDINGS,
                           PROVIDER_AGENT, ROLES_ALL, SAMPLE_STATUSES,
                           authenticate, get_claim, get_provider, get_sample,
                           require_provider_owner)
from services import calc, cascades, derive

bp = Blueprint("claims", __name__)

DE_ENROLLING_FINDINGS = ("INELIGIBLE_SUBSCRIBER", "DUPLICATE_HOUSEHOLD",
                        "MISSING_CERTIFICATION")


@bp.post("/lifeline/reimbursement-claims")
def open_claim():
    caller = authenticate((PROVIDER_AGENT,))

    body = v.get_body()
    provider_id = v.string_field(body, "provider_id")
    service_month = v.month_field(body, "service_month")
    expected_version = v.int_field(body, "expected_provider_version")

    provider = get_provider(provider_id)
    require_provider_owner(caller, provider_id)

    if expected_version != provider["version"]:
        raise ApiError("ERR_STALE_PROVIDER_VERSION",
                       "The carrier version does not match")

    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", "The carrier is not active")

    siblings = db.by_created(derive.claims_of_provider(provider_id))
    if any(c["status"] == "AUDIT_FAILED" for c in siblings):
        raise ApiError("ERR_PROVIDER_AUDIT_HOLD",
                       "The carrier is under an audit hold")

    same_month = [c for c in siblings if c["service_month"] == service_month]
    for other in same_month:
        if other["status"] not in ("DRAFT", "SUPERSEDED"):
            raise ApiError("ERR_CLAIM_DUPLICATE_SERVICE_MONTH",
                           "The service month is already claimed")

    now = db.now()
    for other in same_month:
        if other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            db.touch(other)

    provisional, covered = cascades.price_provisional(provider_id, service_month, now)

    row = db.base_row()
    row.update({
        "provider_id": provider_id,
        "service_month": service_month,
        "status": "DRAFT",
        "provisional_amount_cents": provisional,
        "final_amount_cents": 0,
        "variance_cents": 0,
        "covered_enrollment_count": covered,
        "certifying_officer_ref": None,
        "filed_at": None,
        "sample_drawn_by_ref": None,
        "recoupment_amount_cents": 0,
        "penalty_cents": 0,
        "net_payable_cents": 0,
        "_final_lines": {},
    })
    db.db.claims[row["id"]] = row
    db.touch(provider)
    return response.ok(derive.claim_json(row), 201)


@bp.get("/lifeline/reimbursement-claims/<claim_id>")
def read_claim(claim_id):
    authenticate(ROLES_ALL)
    return response.ok(derive.claim_json(get_claim(claim_id)))


@bp.get("/lifeline/reimbursement-claims")
def list_claims():
    authenticate(ROLES_ALL)
    provider_id = response.filter_str("provider_id")
    service_month = response.filter_str("service_month")
    status = response.filter_enum("status", CLAIM_STATUSES)
    rows = list(db.db.claims.values())
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if service_month is not None:
        rows = [r for r in rows if r["service_month"] == service_month]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(db.by_created(rows), derive.claim_json)


@bp.post("/lifeline/reimbursement-claims/<claim_id>/file")
def file_claim(claim_id):
    caller = authenticate((PROVIDER_AGENT,))
    claim = get_claim(claim_id)

    body = v.get_body()
    officer_ref = v.string_field(body, "certifying_officer_ref", min_len=1, max_len=64)

    require_provider_owner(caller, claim["provider_id"])

    if claim["status"] != "DRAFT":
        raise ApiError("ERR_CLAIM_NOT_DRAFT", "The claim is not a draft")

    provider = db.db.providers.get(claim["provider_id"])
    if provider is None or provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", "The carrier is not active")

    first, last, _days = calc.month_bounds(claim["service_month"])
    if db.now().date() <= last:
        raise ApiError("ERR_SERVICE_MONTH_NOT_CLOSED",
                       "The service month has not closed yet")

    if derive.audit_hold_flag(provider["id"]):
        raise ApiError("ERR_PROVIDER_AUDIT_HOLD",
                       "The carrier is under an audit hold")

    total, covered, lines = cascades.price_final(claim["provider_id"],
                                                claim["service_month"])
    claim["final_amount_cents"] = total
    claim["variance_cents"] = total - (claim["provisional_amount_cents"] or 0)
    claim["covered_enrollment_count"] = covered
    claim["_final_lines"] = lines
    claim["certifying_officer_ref"] = officer_ref
    claim["filed_at"] = db.now()
    claim["status"] = "FILED"
    db.touch(claim)
    db.touch(provider)
    return response.ok(derive.claim_json(claim))


@bp.post("/lifeline/reimbursement-claims/<claim_id>/audit-draw")
def draw_sample(claim_id):
    caller = authenticate((COMPLIANCE_AUDITOR,))
    claim = get_claim(claim_id)

    body = v.get_body()
    sample_size = v.int_field(body, "sample_size")

    if claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_NOT_FILED", "The claim is not filed")

    if sample_size < calc.SAMPLE_SIZE_MIN or sample_size > calc.SAMPLE_SIZE_MAX:
        raise ApiError("ERR_INVALID_SAMPLE_SIZE",
                       "sample_size must be between 1 and 50 inclusive")

    lines = claim.get("_final_lines") or {}
    pool = []
    for enrollment_id, line in lines.items():
        enrollment = db.db.enrollments.get(enrollment_id)
        if enrollment is not None:
            pool.append((enrollment, line))
    if not pool:
        raise ApiError("ERR_EMPTY_SAMPLE_POOL",
                       "The claim paid for no enrollment to sample")

    pool.sort(key=lambda pair: (-(pair[0]["audit_risk_score"] or 0),
                                pair[0]["benefit_start_date"],
                                pair[0]["created_at"], pair[0]["_seq"]))
    effective = min(sample_size, len(pool))

    drawn = []
    for index in range(effective):
        enrollment, line = pool[index]
        row = db.base_row()
        row.update({
            "claim_id": claim["id"],
            "enrollment_id": enrollment["id"],
            "selection_rank": index + 1,
            "risk_score_at_draw": enrollment["audit_risk_score"],
            "claimed_line_cents": line,
            "drawn_by_ref": caller.user_id,
            "status": "DRAWN",
            "finding": None,
            "finding_note": None,
            "adjudicated_by_ref": None,
            "disallowed_support_cents": None,
        })
        db.db.audit_samples[row["id"]] = row
        drawn.append(row)

    claim["status"] = "UNDER_AUDIT"
    claim["sample_drawn_by_ref"] = caller.user_id
    db.touch(claim)

    return response.ok([derive.audit_sample_json(r) for r in drawn], 201)


@bp.get("/lifeline/audit-samples/<sample_id>")
def read_sample(sample_id):
    authenticate(ROLES_ALL)
    return response.ok(derive.audit_sample_json(get_sample(sample_id)))


@bp.get("/lifeline/audit-samples")
def list_samples():
    authenticate(ROLES_ALL)
    claim_id = response.filter_str("claim_id")
    enrollment_id = response.filter_str("enrollment_id")
    status = response.filter_enum("status", SAMPLE_STATUSES)
    finding = response.filter_enum("finding", FINDINGS)
    rows = list(db.db.audit_samples.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if finding is not None:
        rows = [r for r in rows if r["finding"] == finding]
    return response.paginate(db.by_created(rows), derive.audit_sample_json)


@bp.post("/lifeline/audit-samples/<sample_id>/adjudicate")
def adjudicate_sample(sample_id):
    caller = authenticate((COMPLIANCE_AUDITOR,))
    sample = get_sample(sample_id)

    body = v.get_body()
    finding = v.enum_field(body, "finding", FINDINGS)
    note = v.string_field(body, "finding_note", required=False, default=None)

    claim = db.db.claims.get(sample["claim_id"])

    if claim is not None and caller.user_id == claim["sample_drawn_by_ref"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The auditor that drew the sample may not adjudicate it")

    if sample["status"] != "DRAWN":
        raise ApiError("ERR_SAMPLE_ALREADY_ADJUDICATED",
                       "The sample has already been adjudicated")
    if claim is None or claim["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_CLAIM_NOT_FILED", "The claim is not under audit")

    sample["finding"] = finding
    sample["finding_note"] = note
    sample["adjudicated_by_ref"] = caller.user_id

    provider = db.db.providers.get(claim["provider_id"])

    if finding == "COMPLIANT":
        sample["status"] = "ADJUDICATED_PASS"
        sample["disallowed_support_cents"] = 0
        db.touch(sample)

        # "When failed_sample_count is 0, recoupment_amount_cents and penalty_cents
        # are 0 and net_payable_cents equals final_amount_cents." That holds on the
        # passing arm whether or not the join has closed.
        claim["recoupment_amount_cents"] = 0
        claim["penalty_cents"] = 0
        claim["net_payable_cents"] = claim["final_amount_cents"] or 0

        outstanding = [s for s in derive.samples_of_claim(claim["id"])
                       if s["status"] == "DRAWN"]
        if not outstanding and derive.failed_sample_count(claim["id"]) == 0:
            claim["status"] = "AUDIT_PASSED"
        db.touch(claim)
        if provider is not None:
            db.touch(provider)
        return response.ok(derive.audit_sample_json(sample))

    # Any other finding fails fast: the claim settles without waiting.
    sample["status"] = "ADJUDICATED_FAIL"
    sample["disallowed_support_cents"] = sample["claimed_line_cents"]
    db.touch(sample)

    recoupment, penalty, net = calc.audit_recoupment(
        claim["final_amount_cents"],
        derive.audit_sample_count(claim["id"]),
        derive.failed_sample_count(claim["id"]))
    claim["status"] = "AUDIT_FAILED"
    claim["recoupment_amount_cents"] = recoupment
    claim["penalty_cents"] = penalty
    claim["net_payable_cents"] = net
    db.touch(claim)

    if provider is not None:
        db.touch(provider)
        for other in db.by_created(derive.claims_of_provider(provider["id"])):
            if other["id"] != claim["id"] and other["status"] == "FILED":
                other["status"] = "HELD"
                db.touch(other)

    if finding in DE_ENROLLING_FINDINGS:
        enrollment = db.db.enrollments.get(sample["enrollment_id"])
        if enrollment is not None and enrollment["benefit_status"] == "ACTIVE":
            cascades.de_enroll(enrollment, "AUDIT_INELIGIBLE", caller.user_id)

    return response.ok(derive.audit_sample_json(sample))
