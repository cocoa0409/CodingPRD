"""Renewal filings, continuing-education claims, and the practice-hour audit."""
from decimal import Decimal

from flask import Blueprint

import calc
import domain
import guards as G
import store
from envelope import created, listing, mark_new, ok, touch
from errors import fail
from timeutil import add_months, parse_dt, whole_days

bp = Blueprint("renewal", __name__)

CE_CATEGORIES = ("LIVE_CONTACT", "SELF_STUDY", "IN_SERVICE", "ACADEMIC")
VERIFICATION_STATUSES = ("UNVERIFIED", "VERIFIED", "REJECTED")
TERMINAL_RENEWAL = ("RENEWED", "DENIED", "WITHDRAWN")


def _renewal_owner_nurse(renewal):
    return G.nurse_of_renewal(renewal)


# ---------------------------------------------------------------------------
# RenewalApplication
# ---------------------------------------------------------------------------
@bp.post("/renewal-applications")
def create_renewal():
    user_id, role = G.auth("Applicant", "LicensureAnalyst")
    b = G.body()
    lic = G.find_opt("license", b.get("license_id"))
    if lic is None:
        G.req_string(b, "license_id")
    G.own_nurse(role, user_id, lic["nurse_id"])

    expected = G.req_int(b, "expected_license_version")
    attested = G.opt_int(b, "attested_practice_hours", 0, minimum=0)
    carry_over = G.opt_number(b, "carry_over_hours_claimed", Decimal("0"), minimum=Decimal("0"))

    if expected != int(lic["version"]):
        fail("ERR_STALE_VERSION")

    st = store.STORE
    board = domain.board_of_license(lic)
    if board is None or board["status"] == "ARCHIVED":
        fail("ERR_INVALID_STATE", "The board configuration is ARCHIVED.")
    if not domain.is_renewable(lic, board):
        fail("ERR_LICENSE_NOT_RENEWABLE")
    if lic["encumbrance_status"] not in ("CLEAR", "INVESTIGATION_PENDING", "RESTRICTED"):
        fail("ERR_LICENSE_ENCUMBERED")

    period_end = lic["expires_on"]
    period_start = add_months(period_end, -int(board["renewal_period_months"]))

    nurse = domain.nurse_of_license(lic)
    for sibling in sorted(st.renewals.values(), key=lambda r: r["created_at"]):
        if sibling["license_id"] != lic["id"]:
            continue
        if sibling["renewal_status"] not in ("DRAFT", "SUBMITTED"):
            continue
        refund = int(sibling.get("fee_applied_cents") or 0)
        sibling["renewal_status"] = "WITHDRAWN"
        sibling["fee_applied_cents"] = 0
        touch(sibling)
        if refund and nurse is not None:
            nurse["fee_credit_cents"] = int(nurse["fee_credit_cents"]) + refund
            touch(nurse)

    rec = store.base_fields()
    rec.update({
        "license_id": lic["id"],
        "period_start_on": period_start,
        "period_end_on": period_end,
        "renewal_status": "DRAFT",
        "audit_status": "NOT_SELECTED",
        "attested_practice_hours": attested,
        "practice_hour_periods": [],
        "carry_over_hours_claimed": carry_over,
        "ce_credit_hours_provisional": None,
        "ce_credit_hours_audited": None,
        "verified_practice_hours": None,
        "audit_risk_score": None,
        "fee_applied_cents": 0,
        "fee_paid_cents": 0,
        "late_days": 0,
        "doc_request_cycle_count": 0,
        "submitted_at": None,
    })
    st.renewals[rec["id"]] = rec
    mark_new(rec)

    touch(lic)
    return created(rec)


@bp.get("/renewal-applications/<rid>")
def get_renewal(rid):
    user_id, role = G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember", "Applicant")
    renewal = G.find("renewal", rid)
    G.own_nurse(role, user_id, _renewal_owner_nurse(renewal))
    return ok(renewal)


@bp.post("/renewal-applications/<rid>/payment")
def renewal_payment(rid):
    user_id, role = G.auth("Applicant", "LicensureAnalyst")
    renewal = G.find("renewal", rid)
    G.own_nurse(role, user_id, _renewal_owner_nurse(renewal))

    if renewal["renewal_status"] in TERMINAL_RENEWAL:
        fail("ERR_INVALID_STATE")
    lic = domain.license_of_renewal(renewal)
    board = domain.board_of_license(lic)
    if not domain.is_renewable(lic, board):
        fail("ERR_LICENSE_NOT_RENEWABLE")

    late_days = whole_days(lic["expires_on"], store.STORE.clock)
    if late_days < 0:
        late_days = 0
    fee = calc.renewal_fee_assessment(renewal, lic, board, late_days)

    renewal["late_days"] = late_days
    renewal["fee_applied_cents"] = fee
    renewal["fee_paid_cents"] = fee
    touch(renewal)

    nurse = domain.nurse_of_license(lic)
    if nurse is not None:
        credit = int(nurse["fee_credit_cents"])
        used = credit if credit < fee else fee
        nurse["fee_credit_cents"] = credit - used
        nurse["fee_paid_total_cents"] = int(nurse["fee_paid_total_cents"]) + fee
        touch(nurse)
    return ok(renewal)


@bp.post("/renewal-applications/<rid>/ce-records")
def create_ce_record(rid):
    user_id, role = G.auth("Applicant", "LicensureAnalyst")
    renewal = G.find("renewal", rid)
    G.own_nurse(role, user_id, _renewal_owner_nurse(renewal))
    b = G.body()
    provider_code = G.req_string(b, "provider_code")
    accredited = G.opt_bool(b, "provider_accredited", True)
    category = G.req_enum(b, "category", CE_CATEGORIES)
    minutes = G.req_int(b, "minutes")
    if minutes <= 0:
        fail("ERR_INVALID_REQUEST", "Field 'minutes' must be greater than zero.")
    completion = G.req_datetime(b, "completion_date")

    if renewal["renewal_status"] not in ("DRAFT", "CE_DEFICIENT"):
        fail("ERR_INVALID_STATE")

    rec = store.base_fields()
    rec.update({
        "renewal_application_id": renewal["id"],
        "provider_code": provider_code,
        "provider_accredited": accredited,
        "category": category,
        "minutes": minutes,
        "completion_date": completion,
        "verification_status": "UNVERIFIED",
        "credit_hours": calc.credit_hours_for_minutes(minutes),
    })
    store.STORE.ce_records[rec["id"]] = rec
    mark_new(rec)
    return created(rec)


@bp.get("/renewal-applications/<rid>/ce-records")
def list_ce_records(rid):
    user_id, role = G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember", "Applicant")
    renewal = G.find("renewal", rid)
    G.own_nurse(role, user_id, _renewal_owner_nurse(renewal))
    limit, offset = G.pagination()
    rows = domain.ce_records_of(renewal["id"])
    rows = G.filter_rows(rows, {"verification_status": "verification_status",
                               "category": "category"})
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


@bp.post("/renewal-applications/<rid>/submit")
def submit_renewal(rid):
    user_id, role = G.auth("Applicant", "LicensureAnalyst")
    renewal = G.find("renewal", rid)
    G.own_nurse(role, user_id, _renewal_owner_nurse(renewal))

    if renewal["renewal_status"] not in ("DRAFT", "CE_DEFICIENT"):
        fail("ERR_INVALID_STATE")
    lic = domain.license_of_renewal(renewal)
    board = domain.board_of_license(lic)
    if not domain.is_renewable(lic, board):
        fail("ERR_LICENSE_NOT_RENEWABLE")

    provisional = calc.ce_hour_credit_total(
        board, renewal, domain.ce_records_of(renewal["id"]), "provisional_self_reported")
    if provisional < board["ce_hours_required"]:
        fail("ERR_CE_HOURS_INSUFFICIENT")
    if int(renewal["fee_applied_cents"]) <= 0 or \
            int(renewal["fee_paid_cents"]) < int(renewal["fee_applied_cents"]):
        fail("ERR_RENEWAL_FEE_UNPAID")

    renewal["ce_credit_hours_provisional"] = provisional
    renewal["renewal_status"] = "SUBMITTED"
    renewal["submitted_at"] = store.STORE.clock
    touch(renewal)
    return ok(renewal)


@bp.post("/renewal-applications/<rid>/ce-verification")
def ce_verification(rid):
    G.auth("LicensureAnalyst")
    renewal = G.find("renewal", rid)
    if renewal["renewal_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    lic = domain.license_of_renewal(renewal)
    board = domain.board_of_license(lic)

    audited = calc.ce_hour_credit_total(
        board, renewal, domain.ce_records_of(renewal["id"]), "audited_verified")
    renewal["ce_credit_hours_audited"] = audited
    renewal["renewal_status"] = "CE_VERIFIED" if audited >= board["ce_hours_required"] else "CE_DEFICIENT"
    touch(renewal)
    return ok(renewal)


@bp.post("/renewal-applications/<rid>/finalization")
def finalize_renewal(rid):
    G.auth("LicensureAnalyst")
    renewal = G.find("renewal", rid)
    b = G.body()
    outcome = G.req_enum(b, "outcome", ("RENEWED", "DENIED"))

    if renewal["renewal_status"] != "CE_VERIFIED":
        fail("ERR_INVALID_STATE")

    lic = domain.license_of_renewal(renewal)
    board = domain.board_of_license(lic)
    nurse = domain.nurse_of_license(lic)

    if outcome == "RENEWED":
        if renewal["audit_status"] in ("SELECTED", "DOCS_REQUESTED", "DOCS_SUBMITTED"):
            fail("ERR_INVALID_STATE", "The practice-hour audit is still outstanding.")
        if renewal["audit_status"] == "FAILED":
            fail("ERR_PRACTICE_HOURS_INSUFFICIENT")
        renewal["renewal_status"] = "RENEWED"
        touch(renewal)
        lic["expires_on"] = add_months(lic["expires_on"], int(board["renewal_period_months"]))
        if lic["license_status"] == "EXPIRED":
            lic["license_status"] = "ACTIVE"
        touch(lic)
        domain.run_privilege(lic, "RESIDENCY_DECLARED")
        return ok(renewal)

    refund = int(renewal.get("fee_applied_cents") or 0)
    failed_audit = renewal["audit_status"] == "FAILED"
    periods = list(renewal.get("practice_hour_periods") or [])
    renewal["renewal_status"] = "DENIED"
    renewal["fee_applied_cents"] = 0
    touch(renewal)
    if refund and nurse is not None:
        nurse["fee_credit_cents"] = int(nurse["fee_credit_cents"]) + refund
        touch(nurse)

    if failed_audit:
        custodians = []
        for period in periods:
            name = period.get("employer_name") if isinstance(period, dict) else None
            if isinstance(name, str) and name not in custodians:
                custodians.append(name)
        complaint = store.base_fields()
        complaint.update({
            "license_id": lic["id"],
            "consolidated_into_complaint_id": None,
            "complainant_type": "BOARD_INITIATED",
            "violation_category": "FRAUD",
            "allegation_codes": [],
            "employer_custodian_codes": custodians,
            "incident_date": store.STORE.clock,
            "received_at": store.STORE.clock,
            "status": "RECEIVED",
            "jurisdiction_finding": "PENDING",
            "triaged_by_user_id": None,
            "investigator_user_id": None,
            "disposition_at": None,
        })
        store.STORE.complaints[complaint["id"]] = complaint
        mark_new(complaint)
        domain.reconcile_license(lic)
    return ok(renewal)


# ---------------------------------------------------------------------------
# audit sampling and documentation cycle
# ---------------------------------------------------------------------------
@bp.post("/_ops/run-audit-sampling")
def run_audit_sampling():
    G.auth("SystemAdmin")
    b = G.body()
    board = G.find_opt("board", b.get("board_config_id"))
    if board is None:
        G.req_string(b, "board_config_id")

    st = store.STORE
    eligible = []
    for renewal in st.renewals.values():
        if renewal["renewal_status"] != "CE_VERIFIED":
            continue
        if renewal["audit_status"] != "NOT_SELECTED":
            continue
        lic = st.licenses.get(renewal["license_id"])
        if lic is None or lic["issuing_board_config_id"] != board["id"]:
            continue
        eligible.append((renewal, lic))

    for renewal, lic in eligible:
        score = calc.audit_risk_score(renewal, lic, board)
        if renewal.get("audit_risk_score") != score:
            renewal["audit_risk_score"] = score
            touch(renewal)

    quota = calc.sample_quota(board["audit_sample_rate_bp"], len(eligible))
    ranked = sorted(eligible, key=lambda pair: (-pair[0]["audit_risk_score"], pair[0]["created_at"]))
    selected_ids = []
    for renewal, _lic in ranked[:quota]:
        renewal["audit_status"] = "SELECTED"
        touch(renewal)
        selected_ids.append(renewal["id"])

    return ok({
        "board_config_id": board["id"],
        "eligible_count": len(eligible),
        "quota": quota,
        "selected_count": len(selected_ids),
        "selected_renewal_application_ids": selected_ids,
    })


@bp.post("/renewal-applications/<rid>/audit-doc-request")
def audit_doc_request(rid):
    G.auth("LicensureAnalyst")
    renewal = G.find("renewal", rid)
    G.body()
    if renewal["audit_status"] not in ("SELECTED", "DOCS_SUBMITTED"):
        fail("ERR_INVALID_STATE")
    if int(renewal["doc_request_cycle_count"]) >= 3:
        fail("ERR_AUDIT_DOC_REQUEST_LIMIT_REACHED")
    renewal["audit_status"] = "DOCS_REQUESTED"
    renewal["doc_request_cycle_count"] = int(renewal["doc_request_cycle_count"]) + 1
    renewal["practice_hour_periods"] = []
    touch(renewal)
    return ok(renewal)


@bp.post("/renewal-applications/<rid>/audit-doc-submission")
def audit_doc_submission(rid):
    user_id, role = G.auth("Applicant", "LicensureAnalyst")
    renewal = G.find("renewal", rid)
    G.own_nurse(role, user_id, _renewal_owner_nurse(renewal))
    b = G.body()
    raw = G.req_obj_array(b, "practice_hour_periods")
    periods = []
    for entry in raw:
        employer = entry.get("employer_name")
        if not isinstance(employer, str) or not employer:
            fail("ERR_INVALID_REQUEST", "practice_hour_periods.employer_name must be a string.")
        try:
            start_on = parse_dt(entry.get("start_on"))
            end_on = parse_dt(entry.get("end_on"))
        except Exception:
            fail("ERR_INVALID_REQUEST",
                 "practice_hour_periods start_on/end_on must be ISO 8601 instants.")
        hours = entry.get("hours")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)):
            fail("ERR_INVALID_REQUEST", "practice_hour_periods.hours must be a number.")
        if float(hours) < 0:
            fail("ERR_INVALID_REQUEST", "practice_hour_periods.hours must not be negative.")
        # The licensee's submitted array is stored verbatim -- PRD 3.5 says the
        # submission overwrites practice_hour_periods wholesale, not that the
        # server rewrites the instants it was handed.
        periods.append({
            "employer_name": employer,
            "start_on": entry.get("start_on"),
            "end_on": entry.get("end_on"),
            "hours": int(hours),
        })

    if renewal["audit_status"] != "DOCS_REQUESTED":
        fail("ERR_INVALID_STATE")

    renewal["practice_hour_periods"] = periods
    renewal["audit_status"] = "DOCS_SUBMITTED"
    touch(renewal)
    return ok(renewal)


@bp.post("/renewal-applications/<rid>/audit-decision")
def audit_decision(rid):
    G.auth("LicensureAnalyst")
    renewal = G.find("renewal", rid)
    if renewal["audit_status"] != "DOCS_SUBMITTED" or not renewal.get("practice_hour_periods"):
        fail("ERR_AUDIT_DOCS_NOT_SUBMITTED")
    lic = domain.license_of_renewal(renewal)
    board = domain.board_of_license(lic)
    verified = calc.practice_hour_attainment(renewal)
    renewal["verified_practice_hours"] = verified
    renewal["audit_status"] = "PASSED" if verified >= int(board["practice_hours_required"]) else "FAILED"
    touch(renewal)
    return ok(renewal)


# ---------------------------------------------------------------------------
# CeRecord
# ---------------------------------------------------------------------------
@bp.get("/ce-records/<cid>")
def get_ce_record(cid):
    user_id, role = G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember", "Applicant")
    rec = G.find("ce_record", cid)
    G.own_nurse(role, user_id, G.nurse_of_ce_record(rec))
    return ok(rec)


@bp.post("/ce-records/<cid>/verification")
def verify_ce_record(cid):
    G.auth("LicensureAnalyst")
    rec = G.find("ce_record", cid)
    b = G.body()
    status = G.req_enum(b, "verification_status", VERIFICATION_STATUSES)
    if status == "UNVERIFIED":
        fail("ERR_INVALID_STATE", "A claim may only be moved to VERIFIED or REJECTED.")
    rec["verification_status"] = status
    touch(rec)
    return ok(rec)
