"""Trip use reports and the fee assessments they synthesize (PRD 3.7)."""
from flask import Blueprint

import calc
import envelope
import security
import serialize
import shapes
import store
from errors import ApiError
from routes.common import match, qint, qstr
from security import ADMIN, ANY_ROLE, REPRESENTATIVE, SPECIALIST

bp = Blueprint("reports", __name__)

REPORTABLE = ("ISSUED", "ACTIVE")
LIVE_REPORT_STATUSES = ("SUBMITTED", "ACCEPTED")


def assessment_for(permit_id, season_year):
    for a in store.all_of("fee_assessments"):
        if a["permit_id"] == permit_id and a["season_year"] == season_year:
            return a
    return None


def sync_permit_money(permit):
    calc.recompute_service_days_ytd(permit)
    calc.recompute_permit_signals(permit)
    store.touch(permit)
    calc.derive_compliance(permit)


@bp.post("/osup/permits/<permit_id>/trip-use-reports")
def file_report(permit_id):
    caller = security.authenticate((REPRESENTATIVE,))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    period_start = shapes.req_date(data, "period_start_date")
    period_end = shapes.req_date(data, "period_end_date")
    service_days = shapes.req_int(data, "service_days_used", minimum=1, maximum=3650)
    clients = shapes.req_int(data, "client_count", minimum=1)
    gross = shapes.req_int(data, "gross_revenue_cents", minimum=0)
    deductions = shapes.opt_int(data, "allowable_deductions_cents", minimum=0, default=0)
    start_date = store.as_date(period_start)
    end_date = store.as_date(period_end)
    if end_date <= start_date:
        shapes.bad("period_end_date", "must be strictly after period_start_date")
    # priority 7
    if permit["administrative_status"] not in REPORTABLE:
        raise ApiError("ERR_PERMIT_NOT_OPERATIONAL", "the permit is not ISSUED or ACTIVE")
    # priority 8
    if clients > permit["authorized_client_capacity_total"]:
        raise ApiError(
            "ERR_CLIENT_GUIDE_RATIO_UNMET",
            "client_count exceeds the permit's authorized client capacity",
        )
    # priority 10: the season window, then elapse, then overlap
    area = store.get("use_areas", permit["use_area_id"])
    if area is not None:
        inside_season = start_date >= store.as_date(
            area["season_open_date"]
        ) and end_date <= store.as_date(area["season_close_date"])
    else:
        inside_season = False
    inside_term = start_date >= store.as_date(
        permit["term_start_date"]
    ) and end_date <= store.as_date(permit["term_end_date"])
    if not inside_season or not inside_term:
        raise ApiError(
            "ERR_OUTSIDE_SEASON_WINDOW",
            "the period falls outside the season window or the permit term",
        )
    if end_date > store.today():
        raise ApiError("ERR_PERIOD_NOT_ELAPSED", "the reporting period has not elapsed")
    for other in store.all_of("use_reports"):
        if other["permit_id"] != permit["id"] or other["status"] not in LIVE_REPORT_STATUSES:
            continue
        other_start = store.as_date(other["period_start_date"])
        other_end = store.as_date(other["period_end_date"])
        if start_date < other_end and other_start < end_date:
            raise ApiError(
                "ERR_REPORTING_PERIOD_OVERLAP", "the period overlaps a live report"
            )
    # priority 12
    if deductions > calc.deduction_cap(gross):
        raise ApiError(
            "ERR_DEDUCTIONS_EXCEED_CAP", "allowable_deductions_cents exceeds 15% of gross"
        )

    report = store.insert(
        "use_reports",
        {
            "permit_id": permit["id"],
            "supersedes_report_id": None,
            "period_start_date": period_start,
            "period_end_date": period_end,
            "season_year": start_date.year,
            "service_days_used": service_days,
            "client_count": clients,
            "gross_revenue_cents": gross,
            "allowable_deductions_cents": deductions,
            "adjusted_gross_revenue_cents": gross - deductions,
            "applied_rate_bp": None,
            "fee_component_cents": None,
            "status": "SUBMITTED",
            "accepted_at": None,
        },
    )
    return envelope.ok(serialize.use_report(report), 201)


@bp.get("/osup/trip-use-reports/<report_id>")
def read_report(report_id):
    security.authenticate(ANY_ROLE, mutating=False)
    report = store.get_or_404("use_reports", report_id, "ERR_USE_REPORT_NOT_FOUND")
    return envelope.ok(serialize.use_report(report))


@bp.get("/osup/trip-use-reports")
def list_reports():
    security.authenticate(ANY_ROLE, mutating=False)
    filters = {
        "permit_id": qstr("permit_id"),
        "supersedes_report_id": qstr("supersedes_report_id"),
        "status": qstr("status"),
        "season_year": qint("season_year"),
    }
    rows = [r for r in store.all_of("use_reports") if match(r, **filters)]
    rows = store.sort_by(rows, [lambda r: store.as_date(r["period_start_date"])])
    return envelope.paginate(rows, serialize.use_report)


@bp.post("/osup/trip-use-reports/<report_id>/accept")
def accept_report(report_id):
    security.authenticate((SPECIALIST,))
    report = store.get_or_404("use_reports", report_id, "ERR_USE_REPORT_NOT_FOUND")
    permit = store.get("permits", report["permit_id"])
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_USE_REPORT_STATE_INVALID", "the report is not SUBMITTED")
    # priority 12: the season's accepted service days, including this report
    accepted = calc.ordered_accepted_reports(report["permit_id"], report["season_year"])
    cumulative = sum(r["service_days_used"] for r in accepted) + report["service_days_used"]
    if permit is not None and cumulative > permit["authorized_service_days"]:
        raise ApiError(
            "ERR_SERVICE_DAY_LIMIT_EXCEEDED",
            "the season's reported service days exceed authorized_service_days",
        )

    report["status"] = "ACCEPTED"
    report["accepted_at"] = store.now_str()
    store.touch(report)
    assessment = assessment_for(report["permit_id"], report["season_year"])
    if assessment is None:
        assessment = store.insert(
            "fee_assessments",
            {
                "permit_id": report["permit_id"],
                "season_year": report["season_year"],
                "variant_applied": "PROVISIONAL_PER_REPORT",
                "reported_agr_cents": 0,
                "assessed_fee_cents": 0,
                "minimum_fee_applied": False,
                "paid_to_date_cents": 0,
                "balance_due_cents": 0,
                "credit_balance_cents": 0,
                "status": "PROVISIONAL",
                "finalized_at": None,
            },
        )
        calc.compute_assessment(assessment, permit, "PROVISIONAL_PER_REPORT")
    else:
        calc.compute_assessment(assessment, permit, "PROVISIONAL_PER_REPORT")
        store.touch(assessment)
    if permit is not None:
        sync_permit_money(permit)
    return envelope.ok(serialize.use_report(report))


@bp.post("/osup/trip-use-reports/<report_id>/amend")
def amend_report(report_id):
    caller = security.authenticate((REPRESENTATIVE,))
    report = store.get_or_404("use_reports", report_id, "ERR_USE_REPORT_NOT_FOUND")
    permit = store.get("permits", report["permit_id"])
    if permit is not None:
        security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    expected = shapes.req_int(data, "expected_permit_version", minimum=0)
    service_days = shapes.req_int(data, "service_days_used", minimum=1, maximum=3650)
    clients = shapes.req_int(data, "client_count", minimum=1)
    gross = shapes.req_int(data, "gross_revenue_cents", minimum=0)
    deductions = shapes.opt_int(data, "allowable_deductions_cents", minimum=0, default=0)
    # priority 6
    if permit is None or expected != permit["version"]:
        raise ApiError("ERR_STALE_PERMIT_VERSION", "expected_permit_version is stale")
    # priority 7
    if report["status"] != "ACCEPTED":
        raise ApiError("ERR_USE_REPORT_STATE_INVALID", "only an ACCEPTED report may be amended")
    assessment = assessment_for(report["permit_id"], report["season_year"])
    if assessment is not None and assessment["status"] == "CLOSED":
        raise ApiError("ERR_FEE_ASSESSMENT_CLOSED", "a closed season cannot be reopened")
    # priority 12
    if deductions > calc.deduction_cap(gross):
        raise ApiError(
            "ERR_DEDUCTIONS_EXCEED_CAP", "allowable_deductions_cents exceeds 15% of gross"
        )

    report["status"] = "SUPERSEDED"
    store.touch(report)
    replacement = store.insert(
        "use_reports",
        {
            "permit_id": report["permit_id"],
            "supersedes_report_id": report["id"],
            "period_start_date": report["period_start_date"],
            "period_end_date": report["period_end_date"],
            "season_year": report["season_year"],
            "service_days_used": service_days,
            "client_count": clients,
            "gross_revenue_cents": gross,
            "allowable_deductions_cents": deductions,
            "adjusted_gross_revenue_cents": gross - deductions,
            "applied_rate_bp": None,
            "fee_component_cents": None,
            "status": "ACCEPTED",
            "accepted_at": store.now_str(),
        },
    )
    if assessment is not None:
        if assessment["status"] in ("FINAL", "PAID"):
            assessment["status"] = "PROVISIONAL"
        assessment["finalized_at"] = None
        calc.compute_assessment(assessment, permit, "PROVISIONAL_PER_REPORT")
        store.touch(assessment)
    sync_permit_money(permit)
    return envelope.ok(serialize.use_report(replacement), 201)


@bp.get("/osup/permits/<permit_id>/fee-assessments")
def list_assessments(permit_id):
    security.authenticate(ANY_ROLE, mutating=False)
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    filters = {"season_year": qint("season_year"), "status": qstr("status")}
    rows = [
        a
        for a in store.all_of("fee_assessments")
        if a["permit_id"] == permit["id"] and match(a, **filters)
    ]
    rows = store.sort_by(rows, [lambda a: a["season_year"]])
    return envelope.paginate(rows, serialize.fee_assessment)


@bp.get("/osup/fee-assessments/<assessment_id>")
def read_assessment(assessment_id):
    security.authenticate(ANY_ROLE, mutating=False)
    assessment = store.get_or_404(
        "fee_assessments", assessment_id, "ERR_FEE_ASSESSMENT_NOT_FOUND"
    )
    return envelope.ok(serialize.fee_assessment(assessment))


@bp.post("/osup/fee-assessments/<assessment_id>/finalize")
def finalize_assessment(assessment_id):
    security.authenticate((SPECIALIST, ADMIN))
    assessment = store.get_or_404(
        "fee_assessments", assessment_id, "ERR_FEE_ASSESSMENT_NOT_FOUND"
    )
    permit = store.get("permits", assessment["permit_id"])
    if assessment["status"] != "PROVISIONAL":
        raise ApiError("ERR_FEE_ASSESSMENT_CLOSED", "only a PROVISIONAL season may be finalized")
    for r in store.all_of("use_reports"):
        if (
            r["permit_id"] == assessment["permit_id"]
            and r["season_year"] == assessment["season_year"]
            and r["status"] == "SUBMITTED"
        ):
            raise ApiError("ERR_USE_REPORTS_PENDING", "a report for the season is still SUBMITTED")
    calc.compute_assessment(
        assessment, permit, "FINAL_AGGREGATE", write_report_fields=False
    )
    assessment["status"] = "FINAL"
    assessment["finalized_at"] = store.now_str()
    store.touch(assessment)
    if permit is not None:
        calc.recompute_permit_signals(permit)
        store.touch(permit)
        calc.derive_compliance(permit)
    return envelope.ok(serialize.fee_assessment(assessment))


@bp.post("/osup/fee-assessments/<assessment_id>/payments")
def record_payment(assessment_id):
    caller = security.authenticate((REPRESENTATIVE,))
    assessment = store.get_or_404(
        "fee_assessments", assessment_id, "ERR_FEE_ASSESSMENT_NOT_FOUND"
    )
    permit = store.get("permits", assessment["permit_id"])
    if permit is not None:
        security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    amount = shapes.req_int(data, "amount_cents")
    # PRD 3.7 names ERR_FEE_ASSESSMENT_CLOSED for "a later payment ... against a
    # closed assessment"; a PAID assessment carries a zero balance, so every
    # strictly-positive amount is caught by the balance rule below instead.
    if assessment["status"] == "CLOSED":
        raise ApiError("ERR_FEE_ASSESSMENT_CLOSED", "the assessment accepts no further payment")
    if amount <= 0 or amount > assessment["balance_due_cents"]:
        raise ApiError(
            "ERR_PAYMENT_EXCEEDS_BALANCE", "the payment is non-positive or exceeds the balance"
        )
    assessment["paid_to_date_cents"] = assessment["paid_to_date_cents"] + amount
    paid = assessment["paid_to_date_cents"]
    assessed = assessment["assessed_fee_cents"]
    assessment["balance_due_cents"] = max(0, assessed - paid)
    assessment["credit_balance_cents"] = max(0, paid - assessed)
    if assessment["balance_due_cents"] == 0:
        assessment["status"] = "PAID"
    store.touch(assessment)
    if permit is not None:
        calc.recompute_permit_signals(permit)
        store.touch(permit)
        calc.derive_compliance(permit)
    return envelope.ok(serialize.fee_assessment(assessment))


@bp.post("/osup/fee-assessments/<assessment_id>/close")
def close_assessment(assessment_id):
    security.authenticate((ADMIN,))
    assessment = store.get_or_404(
        "fee_assessments", assessment_id, "ERR_FEE_ASSESSMENT_NOT_FOUND"
    )
    if assessment["status"] != "PAID" or assessment["balance_due_cents"] != 0:
        raise ApiError("ERR_FEE_ASSESSMENT_CLOSED", "only a settled PAID assessment is closable")
    assessment["status"] = "CLOSED"
    store.touch(assessment)
    return envelope.ok(serialize.fee_assessment(assessment))
