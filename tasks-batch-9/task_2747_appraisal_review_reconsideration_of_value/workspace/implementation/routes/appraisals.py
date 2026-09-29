"""Appraisal delivery, comparable grid, rule checks, bias screening,
communications and the value revision ledger."""

from flask import Blueprint, request

import db
import response
import validate as V
from errors import fail
from middleware import (ROLE_AMC_COORDINATOR, ROLE_APPRAISER, ROLE_BORROWER,
                        ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE, ROLE_DESK_REVIEWER,
                        ROLE_LOAN_OFFICER, require_owner, require_roles)
from routes.common import (PREFIX, active_membership, body_fk, filter_equals,
                           find_appraisal, find_loan)
from services import bias as bias_svc
from services import constants as C
from services import loans as loan_svc
from services import panel as panel_svc
from services.appraisal import (all_comps, grid_locked, normalize_address,
                                refresh_comp_counts, run_rule_checks)

bp = Blueprint("appraisals", __name__)


# ------------------------------------------------------------------- delivery
@bp.post(PREFIX + "/appraisals")
def deliver_appraisal():
    user_id, _ = require_roles(ROLE_AMC_COORDINATOR)
    data = V.body()

    # Rung 4 -- an AMC coordinator may only deliver under its own company id.
    claimed_amc = data.get("amc_id")
    if isinstance(claimed_amc, str) and claimed_amc != "":
        require_owner(claimed_amc, user_id)

    loan = body_fk(data, "loan_file_id", db.loan_files, "ERR_LOAN_FILE_NOT_FOUND")
    appraiser = body_fk(data, "appraiser_id", db.appraisers, "ERR_APPRAISER_NOT_FOUND")
    amc = body_fk(data, "amc_id", db.amcs, "ERR_AMC_NOT_FOUND")
    superseded = body_fk(data, "supersedes_appraisal_id", db.appraisals,
                         "ERR_APPRAISAL_NOT_FOUND")

    V.req_str(data, "loan_file_id")
    V.req_str(data, "appraiser_id")
    V.req_str(data, "amc_id")
    form_type = V.req_enum(data, "report_form_type", C.REPORT_FORM_TYPES)
    effective_date = V.req_dt(data, "effective_date")
    reported_value = V.req_int(data, "reported_value_cents", positive=True)
    sections = V.req_enum_list(data, "sections_present", C.SECTIONS)
    exhibit_count = V.req_int(data, "exhibit_count", minimum=0)
    narrative = V.req_str(data, "narrative_text", min_len=0)
    band = V.req_enum(data, "subject_census_tract_band", C.CENSUS_TRACT_BANDS)
    expected = V.req_int(data, "expected_loan_file_version")
    if effective_date > db.now():
        fail("ERR_INVALID_REQUEST", "effective_date may not be in the future.")

    if expected != loan["version"]:
        fail("ERR_STALE_VERSION")

    if superseded is not None and superseded["review_status"] != "RETURNED_TO_AMC":
        fail("ERR_INVALID_STATE")

    if amc["panel_status"] == "SUSPENDED":
        fail("ERR_AMC_NOT_ELIGIBLE")

    if active_membership(appraiser["id"], amc["id"]) is None:
        fail("ERR_APPRAISER_NOT_ON_PANEL")

    record = db.make_record({
        "loan_file_id": loan["id"],
        "appraiser_id": appraiser["id"],
        "amc_id": amc["id"],
        "supersedes_appraisal_id": superseded["id"] if superseded else None,
        "report_form_type": form_type,
        "effective_date": effective_date,
        "reported_value_cents": reported_value,
        "sections_present": sections,
        "exhibit_count": exhibit_count,
        "narrative_text": narrative,
        "subject_census_tract_band": band,
        "review_status": "RECEIVED",
        "bias_screen_status": "NOT_SCREENED",
        "quarantine_return_status": None,
        "completeness_score_bps": None,
        "eligible_comp_count": 0,
        "closed_comp_count": 0,
        "max_gross_adjustment_bps": 0,
        "max_net_adjustment_bps": 0,
        "indicated_value_cents": None,
        "variance_vs_reported_bps": None,
        "bias_risk_index": None,
        "current_value_cents": None,
        "rule_check_fail_count": 0,
        "rule_check_warn_count": 0,
    })
    db.appraisals[record["id"]] = record
    db.bump(loan)

    if superseded is not None:
        superseded["review_status"] = "SUPERSEDED"
        db.bump(superseded)
        prior_author = db.appraisers.get(superseded["appraiser_id"])
        if prior_author is not None and prior_author["id"] != appraiser["id"]:
            panel_svc.recompute_performance(prior_author)

    panel_svc.recompute_performance(appraiser)
    return response.created(record)


@bp.get(PREFIX + "/appraisals/<appraisal_id>")
def get_appraisal(appraisal_id):
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                  ROLE_AMC_COORDINATOR, ROLE_APPRAISER, ROLE_LOAN_OFFICER, ROLE_BORROWER)
    return response.ok(find_appraisal(appraisal_id))


@bp.get(PREFIX + "/appraisals")
def list_appraisals():
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                  ROLE_AMC_COORDINATOR, ROLE_LOAN_OFFICER)
    rows = db.ordered(db.appraisals)
    rows = filter_equals(rows, "loan_file_id")
    rows = filter_equals(rows, "appraiser_id")
    rows = filter_equals(rows, "amc_id")
    rows = filter_equals(rows, "supersedes_appraisal_id")
    rows = filter_equals(rows, "review_status")
    rows = filter_equals(rows, "bias_screen_status")
    return response.page(rows)


# ---------------------------------------------------------------- comparables
@bp.post(PREFIX + "/appraisals/<appraisal_id>/comparables")
def add_comparable(appraisal_id):
    require_roles(ROLE_AMC_COORDINATOR)
    appraisal = find_appraisal(appraisal_id)
    data = V.body()
    street_address = V.req_str(data, "street_address")
    sale_price = V.req_int(data, "sale_price_cents", positive=True)
    gross_adjustment = V.req_int(data, "gross_adjustment_cents", minimum=0)
    net_adjustment = V.req_int(data, "net_adjustment_cents")
    distance = V.req_decimal_2dp(data, "distance_miles", minimum="0")
    sale_date = V.req_dt(data, "sale_date")
    sale_status = V.req_enum(data, "sale_status", C.SALE_STATUSES)
    dwelling_type = V.req_enum(data, "dwelling_type", C.DWELLING_TYPES)
    band = V.req_enum(data, "census_tract_band", C.CENSUS_TRACT_BANDS)
    included = V.req_bool(data, "included_in_grid", default=True)

    if grid_locked(appraisal):
        fail("ERR_APPRAISAL_GRID_LOCKED")

    if sale_date > appraisal["effective_date"]:
        fail("ERR_COMP_DATE_AFTER_EFFECTIVE")

    normalized = normalize_address(street_address)
    for comp in all_comps(appraisal["id"]):
        if normalize_address(comp["street_address"]) == normalized:
            fail("ERR_DUPLICATE_COMPARABLE")

    if included and appraisal["eligible_comp_count"] >= C.MAX_GRID_COMPS:
        fail("ERR_COMP_LIMIT_EXCEEDED")

    record = db.make_record({
        "appraisal_id": appraisal["id"],
        "street_address": street_address,
        "sale_price_cents": sale_price,
        "gross_adjustment_cents": gross_adjustment,
        "net_adjustment_cents": net_adjustment,
        "distance_miles": distance,
        "sale_date": sale_date,
        "sale_status": sale_status,
        "dwelling_type": dwelling_type,
        "census_tract_band": band,
        "included_in_grid": included,
        "adjusted_price_cents": sale_price + net_adjustment,
        "gross_adjustment_bps": V.bps_of(gross_adjustment, sale_price),
        "net_adjustment_bps": V.bps_of(abs(net_adjustment), sale_price),
    })
    db.comparables[record["id"]] = record
    refresh_comp_counts(appraisal)
    return response.created(record)


@bp.get(PREFIX + "/appraisals/<appraisal_id>/comparables")
def list_comparables(appraisal_id):
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                  ROLE_AMC_COORDINATOR, ROLE_APPRAISER)
    appraisal = find_appraisal(appraisal_id)
    rows = all_comps(appraisal["id"])
    wanted = V.query_bool("included_in_grid")
    if request.args.get("included_in_grid") is not None:
        rows = [r for r in rows if r["included_in_grid"] is wanted]
    return response.page(rows)


# ---------------------------------------------------------------- rule checks
@bp.post(PREFIX + "/appraisals/<appraisal_id>/run-rule-checks")
def run_checks(appraisal_id):
    require_roles(ROLE_DESK_REVIEWER)
    appraisal = find_appraisal(appraisal_id)
    data = V.body()
    expected = V.req_int(data, "expected_appraisal_version")
    if expected != appraisal["version"]:
        fail("ERR_STALE_VERSION")
    if appraisal["review_status"] not in ("RECEIVED", "RULES_CLEARED", "RULES_FLAGGED"):
        fail("ERR_INVALID_STATE")
    loan = find_loan(appraisal["loan_file_id"])
    run_rule_checks(appraisal, loan)
    db.bump(appraisal)
    return response.ok(appraisal)


@bp.get(PREFIX + "/appraisals/<appraisal_id>/rule-checks")
def list_rule_checks(appraisal_id):
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                  ROLE_AMC_COORDINATOR)
    appraisal = find_appraisal(appraisal_id)
    rows = [r for r in db.rule_checks.values() if r["appraisal_id"] == appraisal["id"]]
    rows.sort(key=lambda r: r["sequence_no"])
    rows = filter_equals(rows, "outcome")
    return response.page(rows)


# --------------------------------------------------------------- bias screen
@bp.post(PREFIX + "/appraisals/<appraisal_id>/run-bias-screen")
def run_screen(appraisal_id):
    require_roles(ROLE_COMPLIANCE)
    appraisal = find_appraisal(appraisal_id)
    data = V.body()
    expected = V.req_int(data, "expected_appraisal_version")
    if expected != appraisal["version"]:
        fail("ERR_STALE_VERSION")
    if appraisal["bias_screen_status"] not in ("NOT_SCREENED", "CLEAR", "INDICATED"):
        fail("ERR_INVALID_STATE")
    bias_svc.run_bias_screen(appraisal)
    db.bump(appraisal)
    return response.ok(appraisal)


@bp.get(PREFIX + "/appraisals/<appraisal_id>/bias-flags")
def list_bias_flags(appraisal_id):
    require_roles(ROLE_COMPLIANCE, ROLE_CHIEF_APPRAISER, ROLE_DESK_REVIEWER)
    appraisal = find_appraisal(appraisal_id)
    rows = db.ordered(db.bias_flags, lambda r: r["appraisal_id"] == appraisal["id"])
    rows = filter_equals(rows, "status")
    rows = filter_equals(rows, "source")
    return response.page(rows)


# ------------------------------------------------------------ communications
@bp.post(PREFIX + "/appraisals/<appraisal_id>/communications")
def send_communication(appraisal_id):
    user_id, role = require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER,
                                  ROLE_AMC_COORDINATOR, ROLE_LOAN_OFFICER, ROLE_BORROWER)
    appraisal = find_appraisal(appraisal_id)
    data = V.body()
    recipient = V.req_enum(data, "recipient", C.COMM_RECIPIENTS)
    intent = V.req_enum(data, "intent", C.COMM_INTENTS)
    text = V.req_str(data, "body", min_len=0)

    if appraisal["review_status"] in ("SUPERSEDED", "QUARANTINED"):
        fail("ERR_COMMUNICATION_LOCKED")

    if recipient == "APPRAISER":
        if role in (ROLE_LOAN_OFFICER, ROLE_BORROWER) and intent in (
                "VALUE_INFLUENCE", "COMPARABLE_SUGGESTION", "DEADLINE_PRESSURE"):
            fail("ERR_INDEPENDENCE_VIOLATION")
        if role == ROLE_DESK_REVIEWER and intent == "VALUE_INFLUENCE":
            fail("ERR_INDEPENDENCE_VIOLATION")
    if intent == "VALUE_INFLUENCE":
        for rov in db.rov_requests.values():
            if (rov["appraisal_id"] == appraisal["id"]
                    and rov["status"] == "AWAITING_APPRAISER"):
                fail("ERR_INDEPENDENCE_VIOLATION")

    record = db.make_record({
        "appraisal_id": appraisal["id"],
        "sender_role": role,
        "sender_user_id": user_id,
        "recipient": recipient,
        "intent": intent,
        "body": text,
        "sent_at": db.now(),
    }, versioned=False)
    db.communications[record["id"]] = record
    return response.created(record)


@bp.get(PREFIX + "/appraisals/<appraisal_id>/communications")
def list_communications(appraisal_id):
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                  ROLE_AMC_COORDINATOR)
    appraisal = find_appraisal(appraisal_id)
    rows = db.ordered(db.communications, lambda r: r["appraisal_id"] == appraisal["id"])
    rows = filter_equals(rows, "recipient")
    rows = filter_equals(rows, "intent")
    return response.page(rows)


@bp.get(PREFIX + "/appraisals/<appraisal_id>/value-revisions")
def list_value_revisions(appraisal_id):
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                  ROLE_LOAN_OFFICER, ROLE_AMC_COORDINATOR)
    appraisal = find_appraisal(appraisal_id)
    rows = db.ordered(db.value_revisions, lambda r: r["appraisal_id"] == appraisal["id"])
    rows = filter_equals(rows, "source_type")
    return response.page(rows)


# --------------------------------------------------------- bias adjudication
@bp.post(PREFIX + "/bias-flags/<flag_id>/adjudicate")
def adjudicate_flag(flag_id):
    from routes.common import find_flag
    user_id, _ = require_roles(ROLE_COMPLIANCE)
    flag = find_flag(flag_id)
    data = V.body()
    disposition = V.req_enum(data, "disposition", C.FLAG_DISPOSITIONS)
    rationale = V.req_str(data, "rationale")

    appraisal = db.appraisals.get(flag["appraisal_id"])
    loan = db.loan_files.get(appraisal["loan_file_id"]) if appraisal else None

    if flag["status"] == "CLEARED":
        fail("ERR_INVALID_STATE")

    if disposition == "SUBSTANTIATE":
        if flag["status"] != "OPEN":
            fail("ERR_INVALID_STATE")
        # PRD 3.5: "Quarantine is reachable from every non-terminal review
        # state"; SUPERSEDED is the only terminal review status, and the
        # snapshot field may never hold QUARANTINED or SUPERSEDED.
        if appraisal["review_status"] == "SUPERSEDED":
            fail("ERR_INVALID_STATE")
        flag["status"] = "SUBSTANTIATED"
        flag["adjudicated_by_user_id"] = user_id
        flag["rationale"] = rationale
        db.bump(flag)

        if appraisal["review_status"] != "QUARANTINED":
            appraisal["quarantine_return_status"] = appraisal["review_status"]
        appraisal["review_status"] = "QUARANTINED"
        if appraisal["bias_screen_status"] == "INDICATED":
            appraisal["bias_screen_status"] = "SUBSTANTIATED"
        db.bump(appraisal)
        # PRD 3.5/3.9: the collateral dimension is pulled into quarantine
        # "from either resting state" -- only VALUE_ACCEPTED -> QUARANTINED
        # and VALUE_REVISED -> QUARANTINED exist on that dimension.
        if loan is not None and loan["collateral_status"] in ("VALUE_ACCEPTED", "VALUE_REVISED"):
            loan["collateral_status"] = "QUARANTINED"
            db.bump(loan)
        author = db.appraisers.get(appraisal["appraiser_id"])
        if author is not None:
            author["substantiated_bias_count"] += 1
            panel_svc.recompute_performance(author)
            if author["panel_status"] in ("PROBATION", "SUSPENDED", "REMOVED"):
                panel_svc.flag_second_appraisal_orders(author["id"])
            db.touch(author)
    else:
        was_substantiated = flag["status"] == "SUBSTANTIATED"
        if was_substantiated:
            for other in db.bias_flags.values():
                if (other["id"] != flag["id"]
                        and other["appraisal_id"] == appraisal["id"]
                        and other["status"] == "SUBSTANTIATED"):
                    fail("ERR_INVALID_STATE")
        flag["status"] = "CLEARED"
        flag["adjudicated_by_user_id"] = user_id
        flag["rationale"] = rationale
        db.bump(flag)

        if was_substantiated:
            restored = appraisal["quarantine_return_status"]
            if restored is not None:
                appraisal["review_status"] = restored
            appraisal["quarantine_return_status"] = None
            if appraisal["bias_screen_status"] == "SUBSTANTIATED":
                appraisal["bias_screen_status"] = "CLEARED_ON_REVIEW"
            db.bump(appraisal)
            if loan is not None and loan["collateral_status"] == "QUARANTINED":
                loan["collateral_status"] = loan_svc.collateral_for_review_status(
                    appraisal["review_status"])
                db.bump(loan)
            author = db.appraisers.get(appraisal["appraiser_id"])
            if author is not None:
                author["substantiated_bias_count"] = max(
                    0, author["substantiated_bias_count"] - 1)
                panel_svc.recompute_performance(author)
        else:
            remaining = any(f["appraisal_id"] == appraisal["id"] and f["status"] == "OPEN"
                            for f in db.bias_flags.values())
            if not remaining and appraisal["bias_screen_status"] == "INDICATED":
                appraisal["bias_screen_status"] = "CLEAR"
                db.bump(appraisal)

    return response.ok(flag)
