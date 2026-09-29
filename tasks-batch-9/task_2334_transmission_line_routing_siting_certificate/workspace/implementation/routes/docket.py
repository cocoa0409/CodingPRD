"""The commission docket: applications, hearings, interventions and the order
(PRD §3.5, §3.6, §3.7)."""

import re
from datetime import timedelta

from flask import Blueprint, g

import response as resp
from db import insert, store
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import calc, derive
from validation import (
    apply_filters,
    collection_list,
    find_path,
    fk,
    find_ref,
    get_body,
    must_be_absent,
    opt_bool,
    opt_int,
    opt_str,
    paginate,
    req_dt,
    req_enum,
    req_id,
    req_int,
    req_str,
)

bp = Blueprint("docket", __name__)

SESSION_KINDS = ("PREHEARING", "EVIDENTIARY", "PUBLIC_TESTIMONY")
REVIEW_OUTCOMES = ("ACCEPT", "REJECT")
DECISION_OUTCOMES = ("GRANT", "DENY")
PETITIONER_KINDS = ("LANDOWNER", "INTEREST_GROUP")
RULINGS = ("GRANT", "DENY")
CONDITION_CATEGORIES = ("ENVIRONMENTAL", "CULTURAL", "LAND_USE", "ENGINEERING", "PUBLIC_SAFETY")
CONSTRAINT_KINDS = ("SEASONAL_BLACKOUT", "CREW_LIMIT", "NOTICE", "MONITORING")
REVIEW_TERMINAL = ("GRANTED", "DENIED")
OPEN_RECORD_STATUSES = ("SCHEDULING", "EVIDENTIARY_REQUIRED", "RECORD_OPEN")
MMDD_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
HEARING_BUFFER = timedelta(minutes=120)


# ----------------------------------------------------------- reads ----
@bp.get("/siting/applications")
@endpoint(ALL_ROLES)
def list_applications():
    rows, pagination = collection_list(
        store.applications,
        ["project_id", "study_id", "proposed_route_id", "review_status", "record_status"],
    )
    return resp.listing(rows, pagination)


@bp.get("/siting/applications/<application_id>")
@endpoint(ALL_ROLES)
def read_application(application_id):
    return resp.ok(find_path(store.applications, application_id))


@bp.get("/siting/applications/<application_id>/hearing-sessions")
@endpoint(ALL_ROLES)
def list_application_sessions(application_id):
    find_path(store.applications, application_id)
    rows = apply_filters(derive.sessions_of_application(application_id), ["kind", "status"])
    rows, pagination = paginate(rows)
    return resp.listing(rows, pagination)


@bp.get("/siting/hearing-sessions")
@endpoint(ALL_ROLES)
def list_sessions():
    rows, pagination = collection_list(store.hearing_sessions, ["application_id", "kind", "status"])
    return resp.listing(rows, pagination)


@bp.get("/siting/hearing-sessions/<session_id>")
@endpoint(ALL_ROLES)
def read_session(session_id):
    return resp.ok(find_path(store.hearing_sessions, session_id))


@bp.get("/siting/interventions")
@endpoint(ALL_ROLES)
def list_interventions():
    rows, pagination = collection_list(
        store.interventions, ["application_id", "landowner_id", "status", "petitioner_kind"]
    )
    return resp.listing(rows, pagination)


@bp.get("/siting/interventions/<intervention_id>")
@endpoint(ALL_ROLES)
def read_intervention(intervention_id):
    return resp.ok(find_path(store.interventions, intervention_id))


# ------------------------------------------------------- the filing ----
def _nominated_alternates(project_id):
    return [
        r["id"]
        for r in derive.routes_of_project(project_id)
        if r["kind"] == "ALTERNATE" and r["status"] == "NOMINATED"
    ]


@bp.post("/siting/applications")
@endpoint(["Developer"])
def file_application():
    body = get_body()

    project = fk(body, "project_id", store.projects)
    study = fk(body, "study_id", store.planning_studies)
    route = fk(body, "proposed_route_id", store.routes)

    project_id = req_id(body, "project_id")
    req_id(body, "study_id")
    req_id(body, "proposed_route_id")
    docket_number = req_str(body, "docket_number")
    filing_fee_cents = req_int(body, "filing_fee_cents", minimum=0)

    # tier 10 — prerequisite record states
    if study["status"] != "CERTIFIED_SUFFICIENT":
        raise ApiError("ERR_STUDY_NOT_SUFFICIENT", "The planning study is not CERTIFIED_SUFFICIENT.")
    if route["kind"] != "PROPOSED" or route["status"] != "NOMINATED":
        raise ApiError(
            "ERR_ROUTE_NOT_NOMINATED", "The proposed route must be a NOMINATED route of kind PROPOSED."
        )

    # tier 11 — segregation of duties
    if g.user_id == study["authored_by_user_id"]:
        raise ApiError(
            "ERR_SELF_CERTIFICATION", "The study's author may not file the siting application."
        )

    # tier 12 — structural constraint
    for existing in store.applications.values():
        if existing["project_id"] == project_id and existing["review_status"] not in REVIEW_TERMINAL:
            raise ApiError(
                "ERR_DUPLICATE_APPLICATION",
                "The project already carries an application that is neither granted nor denied.",
            )

    # tier 14 — cross-family belonging
    if route["project_id"] != project_id:
        raise ApiError("ERR_ROUTE_PROJECT_MISMATCH", "The proposed route belongs to another project.")
    if study["project_id"] != project_id:
        raise ApiError("ERR_STUDY_PROJECT_MISMATCH", "The planning study belongs to another project.")

    # tier 17 — fiscal, then the alternate snapshot dead last
    if filing_fee_cents < calc.FILING_FEE_MIN_CENTS:
        raise ApiError(
            "ERR_FILING_FEE_INSUFFICIENT",
            "filing_fee_cents must be at least %d." % calc.FILING_FEE_MIN_CENTS,
        )
    alternates = _nominated_alternates(project_id)
    if not alternates:
        raise ApiError(
            "ERR_NO_ALTERNATE_ROUTE", "The project offers no NOMINATED ALTERNATE route to snapshot."
        )

    filed_at = store.now()
    row = insert(
        store.applications,
        {
            "project_id": project_id,
            "study_id": study["id"],
            "proposed_route_id": route["id"],
            "alternate_route_ids": alternates,
            "docket_number": docket_number,
            "filing_fee_cents": filing_fee_cents,
            "review_status": "FILED",
            "record_status": "NOT_OPENED",
            "party_count": 0,
            "suspension_days": 0,
            "decision_deadline_at": filed_at + timedelta(days=calc.FILING_PERIOD_DAYS),
            "amendment_round": 0,
            "deficiency_note": None,
            "filed_at": filed_at,
            "filed_by_user_id": g.user_id,
        },
    )
    derive.update(project, stage="APPLICATION_FILED")
    derive.recompute_project_schedule(project)
    return resp.created(row)


@bp.post("/siting/applications/<application_id>/sufficiency-review")
@endpoint(["CommissionStaff"])
def sufficiency_review(application_id):
    application = find_path(store.applications, application_id)
    body = get_body()
    outcome = req_enum(body, "outcome", REVIEW_OUTCOMES)
    deficiency_note = opt_str(body, "deficiency_note")
    if outcome == "REJECT" and (deficiency_note is None or deficiency_note.strip() == ""):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'deficiency_note' is required for a rejection.")

    if application["review_status"] in REVIEW_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The application is already %s." % application["review_status"])
    if application["review_status"] != "FILED":
        raise ApiError(
            "ERR_INVALID_STATE", "No sufficiency review leaves %s." % application["review_status"]
        )

    if outcome == "ACCEPT":
        if application["filing_fee_cents"] < calc.FILING_FEE_MIN_CENTS:
            raise ApiError(
                "ERR_FILING_FEE_INSUFFICIENT",
                "filing_fee_cents must be at least %d." % calc.FILING_FEE_MIN_CENTS,
            )
        if not application["alternate_route_ids"]:
            raise ApiError(
                "ERR_NO_ALTERNATE_ROUTE", "The application carries no alternate route snapshot."
            )
        derive.apply(application, review_status="ACCEPTED", record_status="SCHEDULING")
    else:
        derive.apply(application, review_status="DEFICIENT", deficiency_note=deficiency_note)
    return resp.created(application)


@bp.post("/siting/applications/<application_id>/amendments")
@endpoint(["Developer"])
def amend_application(application_id):
    application = find_path(store.applications, application_id)
    body = get_body()
    expected_version = req_int(body, "expected_application_version")
    amendment_summary = req_str(body, "amendment_summary")
    filing_fee_cents = opt_int(body, "filing_fee_cents", minimum=0)

    if expected_version != application["version"]:
        raise ApiError(
            "ERR_STALE_APPLICATION_VERSION",
            "expected_application_version %s does not match version %s."
            % (expected_version, application["version"]),
        )

    if application["review_status"] in REVIEW_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The application is already %s." % application["review_status"])
    if application["review_status"] != "DEFICIENT":
        raise ApiError("ERR_INVALID_STATE", "Only a DEFICIENT application may be amended.")
    if application["amendment_round"] >= calc.MAX_AMENDMENT_ROUNDS:
        raise ApiError(
            "ERR_AMENDMENT_LIMIT_REACHED",
            "The application has already been amended %d times." % calc.MAX_AMENDMENT_ROUNDS,
        )

    filed_at = store.now()
    fields = {
        "amendment_round": application["amendment_round"] + 1,
        "deficiency_note": None,
        "review_status": "FILED",
        "filed_at": filed_at,
        "decision_deadline_at": filed_at
        + timedelta(days=calc.FILING_PERIOD_DAYS + application["suspension_days"]),
    }
    if filing_fee_cents is not None:
        fields["filing_fee_cents"] = filing_fee_cents
    derive.apply(application, **fields)
    _ = amendment_summary

    project = store.projects.get(application["project_id"])
    if project is not None:
        derive.recompute_project_schedule(project)
    return resp.created(application)


@bp.post("/siting/applications/<application_id>/record-closure")
@endpoint(["HearingExaminer"])
def close_record(application_id):
    application = find_path(store.applications, application_id)
    body = get_body()
    opt_str(body, "closure_note")

    if application["record_status"] == "RECORD_CLOSED":
        raise ApiError("ERR_TERMINAL_STATE", "The record is already RECORD_CLOSED.")
    if application["record_status"] != "RECORD_OPEN":
        raise ApiError("ERR_INVALID_STATE", "No closure transition leaves %s." % application["record_status"])

    for session in derive.sessions_of_application(application_id):
        if session["status"] == "SCHEDULED":
            raise ApiError("ERR_HEARING_STILL_SCHEDULED", "A hearing session is still SCHEDULED.")
    for intervention in derive.interventions_of_application(application_id):
        if intervention["status"] == "PETITIONED":
            raise ApiError("ERR_INTERVENTION_UNRULED", "An intervention petition is still unruled.")

    derive.apply(application, record_status="RECORD_CLOSED")
    return resp.created(application)


# ------------------------------------------------------ the decision ----
def _parse_condition(spec, index):
    where = "conditions[%d]" % index
    if not isinstance(spec, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an object." % where)
    code = req_str(spec, "code")
    category = req_enum(spec, "category", CONDITION_CATEGORIES)
    constraint_kind = req_enum(spec, "constraint_kind", CONSTRAINT_KINDS)
    severity_weight = req_int(spec, "severity_weight", minimum=1, maximum=5)

    start_mmdd = None
    end_mmdd = None
    crew_limit = None
    if constraint_kind == "SEASONAL_BLACKOUT":
        start_mmdd = req_str(spec, "blackout_start_mmdd")
        end_mmdd = req_str(spec, "blackout_end_mmdd")
        for key, value in (("blackout_start_mmdd", start_mmdd), ("blackout_end_mmdd", end_mmdd)):
            if not MMDD_RE.match(value):
                raise ApiError("ERR_INVALID_REQUEST", "Field '%s.%s' must be MM-DD." % (where, key))
        must_be_absent(spec, "crew_limit", "on a SEASONAL_BLACKOUT condition")
    elif constraint_kind == "CREW_LIMIT":
        crew_limit = req_int(spec, "crew_limit", minimum=0)
        must_be_absent(spec, "blackout_start_mmdd", "on a CREW_LIMIT condition")
        must_be_absent(spec, "blackout_end_mmdd", "on a CREW_LIMIT condition")
    else:
        must_be_absent(spec, "blackout_start_mmdd", "on a %s condition" % constraint_kind)
        must_be_absent(spec, "blackout_end_mmdd", "on a %s condition" % constraint_kind)
        must_be_absent(spec, "crew_limit", "on a %s condition" % constraint_kind)

    return {
        "code": code,
        "category": category,
        "constraint_kind": constraint_kind,
        "severity_weight": severity_weight,
        "blackout_start_mmdd": start_mmdd,
        "blackout_end_mmdd": end_mmdd,
        "crew_limit": crew_limit,
        "status": "ACTIVE",
        "waiver_reason": None,
    }


@bp.post("/siting/applications/<application_id>/decision")
@endpoint(["CommissionStaff"])
def decide_application(application_id):
    application = find_path(store.applications, application_id)
    body = get_body()

    certified_route = fk(body, "certified_route_id", store.routes)
    outcome = req_enum(body, "outcome", DECISION_OUTCOMES)

    condition_specs = []
    eminent_domain_authorized = False
    mitigation_base_cents = None
    if outcome == "GRANT":
        certified_route_id = req_id(body, "certified_route_id")
        mitigation_base_cents = req_int(body, "mitigation_base_cents", minimum=0)
        eminent_domain_authorized = opt_bool(body, "eminent_domain_authorized", False)
        raw_conditions = body.get("conditions")
        if raw_conditions is None:
            raw_conditions = []
        if not isinstance(raw_conditions, list):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'conditions' must be an array.")
        condition_specs = [_parse_condition(spec, i) for i, spec in enumerate(raw_conditions)]
        allowed = [application["proposed_route_id"]] + list(application["alternate_route_ids"])
        if certified_route_id not in allowed:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field 'certified_route_id' must name the proposed route or one of the alternates.",
            )

    if application["review_status"] in REVIEW_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The application is already %s." % application["review_status"])
    if application["review_status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "Only an ACCEPTED application may be decided.")
    if application["record_status"] != "RECORD_CLOSED":
        raise ApiError("ERR_RECORD_NOT_CLOSED", "The evidentiary record is not closed.")

    for session in derive.sessions_of_application(application_id):
        if session["status"] == "HELD" and session["presiding_user_id"] == g.user_id:
            raise ApiError(
                "ERR_DECIDER_PRESIDED",
                "A staff user who presided over a held session may not record the decision.",
            )

    project = store.projects.get(application["project_id"])

    if outcome == "DENY":
        derive.apply(application, review_status="DENIED")
        for route in derive.routes_of_project(application["project_id"]):
            if route["status"] == "NOMINATED":
                derive.update(route, status="REJECTED")
        if project is not None:
            derive.recompute_project_schedule(project)
        return resp.created(application)

    tier, contingency, surcharge, required = calc.mitigation_escrow(
        mitigation_base_cents, condition_specs
    )
    issued_at = store.now()
    certificate = insert(
        store.certificates,
        {
            "application_id": application["id"],
            "certified_route_id": certified_route["id"],
            "status": "ISSUED",
            "posture": "ACTIVE",
            "eminent_domain_authorized": eminent_domain_authorized,
            "mitigation_base_cents": mitigation_base_cents,
            "escrow_tier": tier,
            "contingency_cents": contingency,
            "condition_surcharge_cents": surcharge,
            "escrow_required_cents": required,
            "compliance_index_rolling": calc.D("100.00"),
            "compliance_index_cumulative": calc.D("100.00"),
            "issued_by_user_id": g.user_id,
            "issued_at": issued_at,
        },
    )
    for spec in condition_specs:
        fields = dict(spec)
        fields["certificate_id"] = certificate["id"]
        insert(store.certificate_conditions, fields)

    derive.apply(application, review_status="GRANTED")
    derive.update(certified_route, status="CERTIFIED")
    for route in derive.routes_of_project(application["project_id"]):
        if route["id"] != certified_route["id"] and route["status"] == "NOMINATED":
            derive.update(route, status="REJECTED")
    if project is not None:
        derive.update(project, stage="CERTIFICATED")
    return resp.created(application)


# --------------------------------------------------- hearing sessions ----
@bp.post("/siting/hearing-sessions")
@endpoint(["HearingExaminer"])
def create_session():
    body = get_body()
    application = fk(body, "application_id", store.applications)
    application_id = req_id(body, "application_id")
    kind = req_enum(body, "kind", SESSION_KINDS)
    window_start_at = req_dt(body, "window_start_at")
    window_end_at = req_dt(body, "window_end_at")
    if window_end_at <= window_start_at:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'window_end_at' must be after 'window_start_at'.")

    padded_start = window_start_at - HEARING_BUFFER
    padded_end = window_end_at + HEARING_BUFFER
    for existing in derive.sessions_of_application(application_id):
        if existing["status"] not in ("SCHEDULED", "HELD"):
            continue
        if padded_start <= existing["window_end_at"] and existing["window_start_at"] <= padded_end:
            raise ApiError(
                "ERR_HEARING_WINDOW_CONFLICT",
                "The session window conflicts with an existing session on this application.",
            )

    row = insert(
        store.hearing_sessions,
        {
            "application_id": application_id,
            "kind": kind,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "status": "SCHEDULED",
            "presiding_user_id": g.user_id,
            "exhibits_admitted_count": 0,
        },
    )
    _ = application
    return resp.created(row)


@bp.post("/siting/hearing-sessions/<session_id>/holding")
@endpoint(["HearingExaminer"])
def hold_session(session_id):
    session = find_path(store.hearing_sessions, session_id)
    body = get_body()
    exhibits_admitted_count = req_int(body, "exhibits_admitted_count", minimum=0)

    if session["status"] == "HELD":
        raise ApiError("ERR_TERMINAL_STATE", "The session is already HELD.")
    if store.now() < session["window_start_at"]:
        raise ApiError("ERR_SESSION_NOT_STARTED", "The session window has not begun.")

    application = store.applications.get(session["application_id"])
    if application is None or application["record_status"] not in OPEN_RECORD_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE", "The application's record is not open to hearing activity."
        )

    derive.apply(session, status="HELD", exhibits_admitted_count=exhibits_admitted_count)

    record = application["record_status"]
    if record == "SCHEDULING":
        derive.update(application, record_status="RECORD_OPEN")
    elif record == "EVIDENTIARY_REQUIRED" and session["kind"] == "EVIDENTIARY":
        derive.update(application, record_status="RECORD_OPEN")
    return resp.created(session)


# ----------------------------------------------------- interventions ----
@bp.post("/siting/interventions")
@endpoint(["Landowner", "CommissionStaff"])
def create_intervention():
    body = get_body()
    fk(body, "application_id", store.applications)
    fk(body, "landowner_id", store.landowners)
    application_id = req_id(body, "application_id")
    petitioner_kind = req_enum(body, "petitioner_kind", PETITIONER_KINDS)
    grounds = req_str(body, "grounds")

    landowner_id = None
    organization_name = None
    if petitioner_kind == "LANDOWNER":
        landowner_id = req_id(body, "landowner_id")
        must_be_absent(body, "organization_name", "on a LANDOWNER petition")
    else:
        organization_name = req_str(body, "organization_name")
        must_be_absent(body, "landowner_id", "on an INTEREST_GROUP petition")

    row = insert(
        store.interventions,
        {
            "application_id": application_id,
            "petitioner_kind": petitioner_kind,
            "landowner_id": landowner_id,
            "organization_name": organization_name,
            "grounds": grounds,
            "status": "PETITIONED",
            "ruling_reason": None,
            "ruled_by_user_id": None,
            "filed_at": store.now(),
        },
    )
    return resp.created(row)


@bp.post("/siting/interventions/<intervention_id>/ruling")
@endpoint(["CommissionStaff"])
def rule_intervention(intervention_id):
    intervention = find_path(store.interventions, intervention_id)
    body = get_body()
    ruling = req_enum(body, "ruling", RULINGS)
    ruling_reason = req_str(body, "ruling_reason")

    if intervention["status"] in ("GRANTED", "DENIED"):
        raise ApiError("ERR_TERMINAL_STATE", "The petition is already %s." % intervention["status"])

    application = find_ref(store.applications, intervention["application_id"], "application_id")
    if ruling == "GRANT" and application["record_status"] not in OPEN_RECORD_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE", "A petition may only be granted while the record is open to parties."
        )

    derive.apply(
        intervention,
        status="GRANTED" if ruling == "GRANT" else "DENIED",
        ruling_reason=ruling_reason,
        ruled_by_user_id=g.user_id,
    )

    if ruling != "GRANT":
        return resp.created(intervention)

    party_count = sum(
        1
        for i in derive.interventions_of_application(application["id"])
        if i["status"] == "GRANTED"
    )
    fields = {"party_count": party_count}
    cascade = party_count >= 2 and application["record_status"] == "SCHEDULING"
    if cascade:
        fields["record_status"] = "EVIDENTIARY_REQUIRED"
        fields["suspension_days"] = calc.EVIDENTIARY_SUSPENSION_DAYS
        fields["decision_deadline_at"] = application["filed_at"] + timedelta(
            days=calc.FILING_PERIOD_DAYS + calc.EVIDENTIARY_SUSPENSION_DAYS
        )
    derive.update(application, **fields)
    if cascade:
        project = store.projects.get(application["project_id"])
        if project is not None:
            derive.recompute_project_schedule(project)
    return resp.created(intervention)
