"""E&O applications (fork-join review) and distributor delivery packages."""
from flask import Blueprint, g, request

from calc import (EO_BASE_RATE, EO_DEPICTION_SURCHARGE, EO_MIN_PREMIUM_CENTS,
                  EO_RETENTION_CREDIT_RATE, EO_RISK_WEIGHT, round_half_up)
from core import (ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL, ROLE_PRODUCTION_ADMIN, body,
                  by_seq, created, db, fail, guard, invalid, new_row, ok, ok_list, opt_str,
                  pagination, public, req_enum, req_int, req_str, touch)
from domain import (LIVE_COVERAGE, eo_apps_of_production, get_chart, get_eo, get_package,
                    get_production, licenses_of_production, recompute_production)

bp = Blueprint("insurance", __name__)

EO_STATUSES = ("DRAFT", "SUBMITTED", "IN_REVIEW", "CLEARED_TO_BIND", "BOUND",
               "REMEDIATION_REQUIRED", "DECLINED")
REVIEW_TYPES = ("LEGAL", "UNDERWRITING")
OUTCOMES = ("PASS", "FAIL")
WINDOW_CLASSES = ("FESTIVAL_ONLY", "ALL_MEDIA_WINDOW")
PACKAGE_STATUSES = ("DRAFT", "VALIDATED", "DELIVERED", "SUSPENDED", "WITHDRAWN")
MIN_COVERAGE_LIMIT_CENTS = 100000


def _body_chart(data, pid):
    value = data.get("clearance_chart_id")
    if not isinstance(value, str) or not value.strip():
        invalid("Field 'clearance_chart_id' is required and must be a non-empty string.")
    return get_chart(value)


def _has_negotiated_release(asset_id):
    for release in db.subject_releases.values():
        if release["asset_id"] != asset_id:
            continue
        if release["status"] in ("SIGNED", "APPROVAL_GRANTED") \
                and release["approval_rights"] != "NONE":
            return True
    return False


def eo_premium_cents(app, chart):
    coverage = app["coverage_limit_cents"]
    premium = round_half_up(coverage * EO_BASE_RATE)
    loading_total = 0
    for row in chart["pinned_rows"]:
        if row["licensing_status"] != "CLEARED":
            continue
        weight = EO_RISK_WEIGHT.get(row["rights_basis"])
        if weight is None:
            continue
        if row["depiction_status"] == "OBTAINED" and _has_negotiated_release(row["asset_id"]):
            weight = weight + EO_DEPICTION_SURCHARGE
        loading_total += round_half_up(coverage * weight)
    credit = round_half_up(app["retention_cents"] * EO_RETENTION_CREDIT_RATE)
    return max(premium + loading_total - credit, EO_MIN_PREMIUM_CENTS)


@bp.post("/productions/<pid>/eo-applications")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR)
def create_eo(pid):
    production = get_production(pid)
    data = body()
    chart = _body_chart(data, pid)
    coverage = req_int(data, "coverage_limit_cents", minimum=0)
    retention = req_int(data, "retention_cents", minimum=0)

    # rung 19
    if chart["production_id"] != pid:
        fail("ERR_CHART_PRODUCTION_MISMATCH",
             "The chart does not belong to the addressed production.")
    # rung 43
    if coverage < MIN_COVERAGE_LIMIT_CENTS or retention >= coverage:
        fail("ERR_COVERAGE_LIMIT_INVALID",
             "coverage_limit_cents must be at least %d and exceed retention_cents."
             % MIN_COVERAGE_LIMIT_CENTS)

    row = new_row()
    row.update({
        "production_id": pid,
        "clearance_chart_id": chart["id"],
        "coverage_limit_cents": coverage,
        "retention_cents": retention,
        "premium_cents": None,
        "legal_review_status": "PENDING",
        "underwriting_review_status": "PENDING",
        "legal_reviewer_user_id": None,
        "underwriting_reviewer_user_id": None,
        "policy_number": None,
        "status": "DRAFT",
    })
    db.eo_applications[row["id"]] = row
    return created(public(row))


@bp.get("/eo-applications/<eid>")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL)
def read_eo(eid):
    return ok(public(get_eo(eid)))


@bp.get("/eo-applications")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL)
def list_eo():
    limit, offset = pagination()
    rows = by_seq(list(db.eo_applications.values()))
    for key in ("production_id", "clearance_chart_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return ok_list([public(r) for r in rows], limit, offset)


@bp.post("/eo-applications/<eid>/reviews")
@guard(ROLE_LEGAL_COUNSEL, ROLE_CLEARANCE_SUPERVISOR)
def record_review(eid):
    app = get_eo(eid)
    data = body()
    review_type = req_enum(data, "review_type", REVIEW_TYPES)
    outcome = req_enum(data, "outcome", OUTCOMES)
    opt_str(data, "notes")

    # rung 10
    if app["status"] not in ("SUBMITTED", "IN_REVIEW"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "An application in %s takes no reviews." % app["status"])

    chart = db.clearance_charts.get(app["clearance_chart_id"])

    # rung 23 — segregation of duties
    if review_type == "LEGAL":
        issuers = set()
        if chart is not None:
            for letter_id in chart["pinned_opinion_letter_ids"]:
                letter = db.opinion_letters.get(letter_id)
                if letter is not None:
                    issuers.add(letter["issued_by_user_id"])
        if g.user_id in issuers:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The counsel that issued a pinned opinion letter may not review it.")
        if app["underwriting_reviewer_user_id"] == g.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The same operator may not record both review branches.")
    else:
        if app["legal_reviewer_user_id"] == g.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The same operator may not record both review branches.")

    # rung 24
    field = "legal_review_status" if review_type == "LEGAL" else "underwriting_review_status"
    if app[field] != "PENDING":
        fail("ERR_REVIEW_ALREADY_RECORDED",
             "The %s review has already been recorded." % review_type)

    # rung 25
    if review_type == "LEGAL" and g.role != ROLE_LEGAL_COUNSEL:
        fail("ERR_REVIEW_TYPE_ROLE_MISMATCH", "A LEGAL review requires LegalCounsel.")
    if review_type == "UNDERWRITING" and g.role != ROLE_CLEARANCE_SUPERVISOR:
        fail("ERR_REVIEW_TYPE_ROLE_MISMATCH",
             "An UNDERWRITING review requires ClearanceSupervisor.")

    app[field] = "PASSED" if outcome == "PASS" else "FAILED"
    if review_type == "LEGAL":
        app["legal_reviewer_user_id"] = g.user_id
    else:
        app["underwriting_reviewer_user_id"] = g.user_id

    if outcome == "FAIL":
        app["status"] = "DECLINED"
        app["premium_cents"] = None
    elif app["legal_review_status"] == "PASSED" \
            and app["underwriting_review_status"] == "PASSED":
        app["status"] = "CLEARED_TO_BIND"
    else:
        app["status"] = "IN_REVIEW"
    touch(app)
    return ok(public(app))


@bp.post("/eo-applications/<eid>/state")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR)
def eo_state(eid):
    app = get_eo(eid)
    data = body()
    to_status = req_enum(data, "to_status", EO_STATUSES)
    production = get_production(app["production_id"])
    chart = db.clearance_charts.get(app["clearance_chart_id"])
    current = app["status"]

    if to_status == "SUBMITTED":
        if current != "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "An application in %s cannot be submitted." % current)
        # rung 14
        if recompute_production(production) == "BLOCKED":
            fail("ERR_PRODUCTION_POSTURE_BLOCKED",
                 "A BLOCKED production may not submit for insurance.")
        # rungs 20 and 21
        if chart is None or chart["status"] == "STALE":
            fail("ERR_CHART_STALE", "The referenced clearance chart has gone STALE.")
        if chart["status"] == "SUPERSEDED":
            fail("ERR_CHART_SUPERSEDED",
                 "The referenced clearance chart has been superseded.")
        # rung 43, re-checked at submission time
        if app["coverage_limit_cents"] <= app["retention_cents"]:
            fail("ERR_COVERAGE_LIMIT_INVALID",
                 "coverage_limit_cents must exceed retention_cents.")

        app["premium_cents"] = eo_premium_cents(app, chart)
        app["legal_review_status"] = "PENDING"
        app["underwriting_review_status"] = "PENDING"
        app["status"] = "SUBMITTED"
        touch(app)
        return ok(public(app))

    if to_status == "BOUND":
        # rung 44 displaces the generic invalid-transition answer
        if current not in ("CLEARED_TO_BIND", "REMEDIATION_REQUIRED"):
            fail("ERR_REVIEWS_INCOMPLETE",
                 "Both review branches must pass before the policy may be bound.")
        if current == "CLEARED_TO_BIND":
            policy_number = req_str(data, "policy_number")
            if chart is None or chart["status"] != "PINNED":
                fail("ERR_CHART_STALE",
                     "The referenced clearance chart is no longer PINNED.")
            app["policy_number"] = policy_number
        else:
            if recompute_production(production) != "OPEN":
                fail("ERR_PRODUCTION_POSTURE_BLOCKED",
                     "Re-binding requires the production's posture to be OPEN.")
        app["status"] = "BOUND"
        touch(app)
        return ok(public(app))

    fail("ERR_INVALID_STATE_TRANSITION",
         "%s is not requestable through this endpoint." % to_status)


# --- delivery packages ------------------------------------------------------
@bp.post("/productions/<pid>/delivery-packages")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR)
def create_package(pid):
    get_production(pid)
    data = body()
    chart = _body_chart(data, pid)
    distributor = req_str(data, "distributor_name")
    window_class = req_enum(data, "window_class", WINDOW_CLASSES)

    if chart["production_id"] != pid:
        fail("ERR_CHART_PRODUCTION_MISMATCH",
             "The chart does not belong to the addressed production.")

    row = new_row()
    row.update({
        "production_id": pid,
        "clearance_chart_id": chart["id"],
        "distributor_name": distributor,
        "window_class": window_class,
        "cue_sheet_row_count": _music_row_count(chart),
        "rights_chart_row_count": chart["pinned_row_count"],
        "music_leg_gap_count": chart["music_leg_gap_count"],
        "suspension_reason": None,
        "status": "DRAFT",
    })
    db.delivery_packages[row["id"]] = row
    return created(public(row))


def _music_row_count(chart):
    total = 0
    for row in chart["pinned_rows"]:
        asset = db.assets.get(row["asset_id"])
        if asset is not None and asset["asset_type"] == "MUSIC":
            total += 1
    return total


@bp.get("/delivery-packages/<pkid>")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL)
def read_package(pkid):
    return ok(public(get_package(pkid)))


@bp.get("/delivery-packages")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL)
def list_packages():
    limit, offset = pagination()
    rows = by_seq(list(db.delivery_packages.values()))
    for key in ("production_id", "clearance_chart_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return ok_list([public(r) for r in rows], limit, offset)


@bp.post("/delivery-packages/<pkid>/state")
@guard(ROLE_CLEARANCE_SUPERVISOR, ROLE_PRODUCTION_ADMIN)
def package_state(pkid):
    package = get_package(pkid)
    data = body()
    to_status = req_enum(data, "to_status", PACKAGE_STATUSES)
    opt_str(data, "reason")

    production = get_production(package["production_id"])
    chart = db.clearance_charts.get(package["clearance_chart_id"])
    current = package["status"]

    if to_status == "VALIDATED":
        if current != "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A package in %s cannot be validated." % current)
        # rung 14
        if recompute_production(production) == "BLOCKED":
            fail("ERR_PRODUCTION_POSTURE_BLOCKED",
                 "A BLOCKED production may not validate a delivery package.")
        # rungs 20 and 21
        if chart is None or chart["status"] == "STALE":
            fail("ERR_CHART_STALE", "The referenced clearance chart has gone STALE.")
        if chart["status"] == "SUPERSEDED":
            fail("ERR_CHART_SUPERSEDED",
                 "The referenced clearance chart has been superseded.")
        # rung 26
        if chart["music_leg_gap_count"] != 0:
            fail("ERR_CUE_SHEET_INCOMPLETE",
                 "Every pinned MUSIC row needs both its MASTER and PUBLISHING leg.")
        # rung 27
        if package["window_class"] == "ALL_MEDIA_WINDOW":
            for lic in licenses_of_production(production["id"]):
                if lic["status"] in LIVE_COVERAGE and lic["window_class"] != "ALL_MEDIA_WINDOW":
                    fail("ERR_WINDOW_CLASS_INSUFFICIENT",
                         "An all-media delivery may not rest on a festival-only licence.")
        package["cue_sheet_row_count"] = _music_row_count(chart)
        package["rights_chart_row_count"] = chart["pinned_row_count"]
        package["music_leg_gap_count"] = chart["music_leg_gap_count"]
        package["status"] = "VALIDATED"
        touch(package)
        return ok(public(package))

    if to_status == "DELIVERED":
        if current != "VALIDATED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A package in %s cannot be delivered." % current)
        # rung 15
        posture = recompute_production(production)
        if posture == "BLOCKED":
            fail("ERR_PRODUCTION_POSTURE_BLOCKED",
                 "A BLOCKED production may not deliver.")
        if posture != "OPEN":
            fail("ERR_PRODUCTION_POSTURE_RESTRICTED",
                 "Delivery requires the production's posture to be OPEN.")
        if chart is None or chart["status"] != "PINNED":
            fail("ERR_CHART_STALE", "The referenced clearance chart is no longer PINNED.")
        # rung 28
        if not any(a["status"] == "BOUND" for a in eo_apps_of_production(production["id"])):
            fail("ERR_EO_NOT_BOUND", "The production has no BOUND E&O application.")
        package["status"] = "DELIVERED"
        touch(package)
        return ok(public(package))

    if to_status == "WITHDRAWN":
        if current not in ("DRAFT", "VALIDATED", "SUSPENDED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A package in %s cannot be withdrawn." % current)
        package["status"] = "WITHDRAWN"
        touch(package)
        return ok(public(package))

    fail("ERR_INVALID_STATE_TRANSITION",
         "%s is not requestable through this endpoint." % to_status)
