"""Composite setup helpers.

Each helper drives a multi-step scenario through the public API so tests can
focus on assertions. Setup calls use the lenient get_success_data validator
and raise a clear "Setup failed" error when a precondition call is rejected.
All entity-backed role calls thread the owning entity's id into X-User-ID.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import build_user_headers, get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, TEST_DEFAULTS
from .factories import (
    create_application_payload,
    create_complainant_payload,
    create_complaint_payload,
    create_curfew_rule_payload,
    create_event_payload,
    create_flight_payload,
    create_fund_payload,
    create_monitor_payload,
    create_notification_payload,
    create_operator_payload,
    create_outage_payload,
    create_parcel_payload,
    create_report_payload,
    create_study_payload,
)
from .test_users import (
    TEST_USERS,
    make_board_member_headers,
    make_complainant_headers,
    make_noise_analyst_headers,
    make_operator_rep_headers,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]
LIAISON = TEST_USERS["community_liaison_headers"]
COORDINATOR = TEST_USERS["study_coordinator_headers"]
BOARD = TEST_USERS["board_member_headers"]


def _ok(resp, what: str) -> dict:
    if resp.status_code >= 400:
        raise AssertionError(f"Setup failed: {what}: HTTP {resp.status_code} {resp.text}")
    return get_success_data(resp)


# --- Clock ---

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (NoiseOfficeAdmin only, PRD 2.4)."""
    return _ok(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN),
        f"set_clock({to_iso8601})",
    )


# --- Registry tier ---

def create_complainant(**overrides) -> dict:
    return _ok(
        api_client.create_complainant(create_complainant_payload(**overrides), LIAISON),
        "create_complainant",
    )


def complainant_headers_of(complainant: dict) -> dict:
    return make_complainant_headers(complainant["id"])


def create_operator(**overrides) -> dict:
    return _ok(
        api_client.create_operator(create_operator_payload(**overrides), ADMIN),
        "create_operator",
    )


def create_monitor(**overrides) -> dict:
    return _ok(
        api_client.create_monitor(create_monitor_payload(**overrides), ADMIN),
        "create_monitor",
    )


def create_curfew_rule(**overrides) -> dict:
    return _ok(
        api_client.create_curfew_rule(create_curfew_rule_payload(**overrides), ADMIN),
        "create_curfew_rule",
    )


# --- Flights ---

def create_flight(operator_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_flight(create_flight_payload(operator_id, **overrides), ADMIN),
        "create_flight",
    )


def operate_flight(flight_id: str, actual_at: str, **extra) -> dict:
    payload: Dict[str, Any] = {"status": "OPERATED", "actual_at": actual_at}
    payload.update(extra)
    return _ok(api_client.patch_flight(flight_id, payload, ADMIN), "operate_flight")


def create_operated_flight(operator_id: str, actual_at: str, **overrides) -> dict:
    flight = create_flight(operator_id, **overrides)
    return operate_flight(flight["id"], actual_at)


# --- Complaints ---

def create_complaint(complainant_id: str, occurred_at: str, **overrides) -> dict:
    """File a complaint as the complainant-owner (ownership-threaded)."""
    return _ok(
        api_client.create_complaint(
            create_complaint_payload(complainant_id, occurred_at=occurred_at, **overrides),
            make_complainant_headers(complainant_id),
        ),
        "create_complaint",
    )


def begin_review(complaint_id: str) -> int:
    """RECEIVED -> UNDER_REVIEW. Returns the complaint's current version."""
    data = _ok(api_client.begin_review(complaint_id, {}, ANALYST), "begin_review")
    return data["version"]


def file_complaints(complainant_id: str, occurred_ats: List[str], **overrides) -> List[dict]:
    return [create_complaint(complainant_id, at, **overrides) for at in occurred_ats]


def correlate_complaint(
    complaint_id: str,
    expected_version: int,
    flight_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict:
    payload: Dict[str, Any] = {"expected_complaint_version": expected_version}
    if flight_id is not None:
        payload["flight_id"] = flight_id
    if event_id is not None:
        payload["noise_event_id"] = event_id
    return _ok(api_client.correlate_complaint(complaint_id, payload, ANALYST), "correlate")


def close_complaint(complaint_id: str, outcome: str) -> dict:
    return _ok(
        api_client.close_complaint(complaint_id, {"outcome": outcome}, ANALYST),
        f"close_complaint({outcome})",
    )


def create_correlated_complaint(
    complainant: dict,
    flight: dict,
    occurred_at: str,
    event_id: Optional[str] = None,
    **overrides,
) -> dict:
    """Complaint -> begin-review -> correlate. Returns the CORRELATED complaint."""
    complaint = create_complaint(complainant["id"], occurred_at, **overrides)
    version = begin_review(complaint["id"])
    return correlate_complaint(complaint["id"], version, flight_id=flight["id"], event_id=event_id)


def create_substantiated_complaint(
    complainant: dict, flight: dict, occurred_at: str, **overrides
) -> dict:
    correlated = create_correlated_complaint(complainant, flight, occurred_at, **overrides)
    return close_complaint(correlated["id"], "SUBSTANTIATED")


def setup_repeat_complainant(
    filings: int = 10,
    occurred_dates: Optional[List[str]] = None,
    zone_code: str = "Z1",
) -> Dict[str, Any]:
    """Complainant with `filings` complaints; returns complainant plus the
    auto-created outreach case id when the standing crossed into REPEAT."""
    complainant = create_complainant(zone_code=zone_code)
    if occurred_dates is None:
        occurred_dates = [f"2026-07-{day:02d}T08:00:00Z" for day in range(1, filings + 1)]
    file_complaints(complainant["id"], occurred_dates)
    cases, _meta = _list(
        api_client.list_complainant_outreach_cases(complainant["id"], LIAISON)
    )
    return {"complainant": complainant, "cases": cases}


def _list(resp):
    from prd_bench_local_runner.testing import validate_paginated

    if resp.status_code >= 400:
        raise AssertionError(f"Setup failed: list call: HTTP {resp.status_code} {resp.text}")
    return validate_paginated(resp)


# --- Monitors / events ---

def create_event(monitor_id: str, **overrides) -> dict:
    return _ok(
        api_client.ingest_event(monitor_id, create_event_payload(**overrides), ADMIN),
        "ingest_event",
    )


def record_outage(monitor_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_outage(monitor_id, create_outage_payload(**overrides), ADMIN),
        "record_outage",
    )


def begin_screening(event_id: str) -> dict:
    return _ok(api_client.begin_screening(event_id, {}, ANALYST), "begin_screening")


def classify_event(event_id: str, classification: str, flight_id: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {"classification": classification}
    if flight_id is not None:
        payload["flight_id"] = flight_id
    return _ok(api_client.classify_event(event_id, payload, ANALYST), "classify_event")


# --- Studies / parcels ---

def create_study(**overrides) -> dict:
    return _ok(
        api_client.create_study(create_study_payload(**overrides), COORDINATOR),
        "create_study",
    )


def add_parcel(study_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_parcel(study_id, create_parcel_payload(**overrides), COORDINATOR),
        "add_parcel",
    )


def advance_study(study_id: str, stage: str) -> dict:
    """Walk the study lifecycle from SCOPING up to the requested stage."""
    study = _ok(api_client.get_study(study_id, COORDINATOR), "get_study")
    steps = {
        "DATA_COLLECTION": [("start_data_collection", COORDINATOR)],
        "DRAFTED": [("start_data_collection", COORDINATOR), ("release_draft", COORDINATOR)],
        "PUBLIC_REVIEW": [
            ("start_data_collection", COORDINATOR),
            ("release_draft", COORDINATOR),
            ("open_public_comment", COORDINATOR),
        ],
        "ADOPTED": [
            ("start_data_collection", COORDINATOR),
            ("release_draft", COORDINATOR),
            ("open_public_comment", COORDINATOR),
            ("adopt_study", ADMIN),
        ],
    }
    order = ["SCOPING", "DATA_COLLECTION", "DRAFTED", "PUBLIC_REVIEW", "ADOPTED"]
    if order.index(study["status"]) >= order.index(stage):
        return study
    for method, headers in steps[stage][order.index(study["status"]):]:
        study = _ok(getattr(api_client, method)(study_id, {}, headers), method)
    return study


def setup_adopted_study_with_parcel(
    measured: float = 66.0,
    modeled: float = 67.5,
    land_use: str = "RESIDENTIAL",
    zone_code: str = "Z1",
    parcel_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """ADOPTED study with one parcel (exposure already recomputed under the
    final variant). Returns {study, parcel}."""
    study = create_study()
    study = advance_study(study["id"], "DATA_COLLECTION")
    overrides = dict(parcel_overrides or {})
    parcel = add_parcel(
        study["id"],
        land_use=land_use,
        dnl_db_measured=measured,
        dnl_db_modeled=modeled,
        zone_code=zone_code,
        **overrides,
    )
    study = advance_study(study["id"], "ADOPTED")
    parcel = _ok(api_client.get_parcel(parcel["id"], COORDINATOR), "get_parcel")
    return {"study": study, "parcel": parcel}


# --- Funds / applications ---

def create_fund(**overrides) -> dict:
    return _ok(
        api_client.create_fund(create_fund_payload(**overrides), ADMIN),
        "create_fund",
    )


def read_fund(fund_id: str) -> dict:
    return _ok(api_client.get_fund(fund_id, ADMIN), "get_fund")


def fund_version(fund_id: str) -> int:
    return read_fund(fund_id)["version"]


def create_application(parcel_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_application(create_application_payload(parcel_id, **overrides), LIAISON),
        "create_application",
    )


def submit_application(application_id: str) -> dict:
    return _ok(api_client.submit_application(application_id, {}, LIAISON), "submit_application")


def screen_application(application_id: str) -> dict:
    return _ok(
        api_client.begin_application_screening(application_id, {}, COORDINATOR),
        "begin_application_screening",
    )


def decide_application(application_id: str, decision: str) -> dict:
    return _ok(
        api_client.record_decision(application_id, {"decision": decision}, COORDINATOR),
        f"record_decision({decision})",
    )


def issue_offer(application_id: str, fund_id: str) -> dict:
    """Issue an offer, always reading the fund's current version first (PRD 2.6)."""
    version = fund_version(fund_id)
    return _ok(
        api_client.issue_offer(
            application_id, {"expected_fund_version": version}, ADMIN
        ),
        "issue_offer",
    )


def setup_decided_application(
    decision: str = "ELIGIBLE_TIER2",
    est_cost_cents: int = 500_000,
    rooms_count: int = 4,
    fund_total_cents: int = 5_000_000,
    intake_opens_at: str = "2026-07-01T00:00:00Z",
    intake_closes_at: str = "2026-09-30T00:00:00Z",
    adopt: bool = True,
    parcel_measured: float = 66.0,
    parcel_modeled: float = 67.5,
    land_use: str = "RESIDENTIAL",
) -> Dict[str, Any]:
    """ACTIVE fund + study (ADOPTED by default) + parcel + application walked
    through submit/screen/decision. Returns {fund, study, parcel, application}."""
    fund = create_fund(
        total_allocation_cents=fund_total_cents,
        intake_opens_at=intake_opens_at,
        intake_closes_at=intake_closes_at,
    )
    study = create_study()
    advance_study(study["id"], "DATA_COLLECTION")
    parcel = add_parcel(
        study["id"],
        land_use=land_use,
        dnl_db_measured=parcel_measured,
        dnl_db_modeled=parcel_modeled,
    )
    if adopt:
        advance_study(study["id"], "ADOPTED")
        parcel = _ok(api_client.get_parcel(parcel["id"], COORDINATOR), "get_parcel")
    application = create_application(
        parcel["id"], est_cost_cents=est_cost_cents, rooms_count=rooms_count
    )
    submit_application(application["id"])
    screen_application(application["id"])
    application = decide_application(application["id"], decision)
    study = _ok(api_client.get_study(study["id"], COORDINATOR), "get_study")
    return {
        "fund": read_fund(fund["id"]),
        "study": study,
        "parcel": parcel,
        "application": application,
    }


def setup_issued_offer(**kwargs) -> Dict[str, Any]:
    """Decision pipeline plus an issued offer. Returns the context dict with
    the refreshed application in OFFER_ISSUED."""
    ctx = setup_decided_application(**kwargs)
    application = issue_offer(ctx["application"]["id"], ctx["fund"]["id"])
    ctx["application"] = application
    ctx["fund"] = read_fund(ctx["fund"]["id"])
    return ctx


def setup_grant_committed(**kwargs) -> Dict[str, Any]:
    ctx = setup_issued_offer(**kwargs)
    application = _ok(
        api_client.accept_offer(ctx["application"]["id"], {}, LIAISON),
        "accept_offer",
    )
    ctx["application"] = application
    ctx["fund"] = read_fund(ctx["fund"]["id"])
    return ctx


# --- Notifications ---

def create_notification(
    operator_id: str,
    complaint_id: Optional[str] = None,
    event_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = create_notification_payload(operator_id, **overrides)
    if complaint_id is not None:
        payload["complaint_id"] = complaint_id
    if event_id is not None:
        payload["noise_event_id"] = event_id
    return _ok(api_client.create_notification(payload, ANALYST), "create_notification")


def send_notification(notification_id: str) -> dict:
    return _ok(api_client.send_notification(notification_id, {}, ANALYST), "send_notification")


def acknowledge_notification(notification_id: str, operator_id: str) -> dict:
    return _ok(
        api_client.acknowledge_notification(
            notification_id, {}, make_operator_rep_headers(operator_id)
        ),
        "acknowledge_notification",
    )


def respond_notification(notification_id: str, operator_id: str, text: str) -> dict:
    return _ok(
        api_client.respond_notification(
            notification_id, {"response_text": text}, make_operator_rep_headers(operator_id)
        ),
        "respond_notification",
    )


def setup_sent_notification(**overrides) -> Dict[str, Any]:
    """Complainant + complaint + operator + SENT notification linked to the
    complaint. Returns {complainant, complaint, operator, notification}."""
    complainant = create_complainant()
    complaint = create_complaint(complainant["id"], "2026-07-15T09:00:00Z")
    operator = create_operator()
    notification = create_notification(operator["id"], complaint_id=complaint["id"], **overrides)
    notification = send_notification(notification["id"])
    return {
        "complainant": complainant,
        "complaint": complaint,
        "operator": operator,
        "notification": notification,
    }


def setup_responded_notification(**overrides) -> Dict[str, Any]:
    ctx = setup_sent_notification(**overrides)
    acknowledge_notification(ctx["notification"]["id"], ctx["operator"]["id"])
    notification = respond_notification(
        ctx["notification"]["id"],
        ctx["operator"]["id"],
        "We adjusted the climb profile.",
    )
    ctx["notification"] = notification
    return ctx


# --- Reports ---

def create_report(quarter_label: str = "2026-Q2", user_id: str = "analyst-7", **overrides) -> dict:
    headers = make_noise_analyst_headers(user_id)
    return _ok(
        api_client.create_report(
            create_report_payload(quarter_label=quarter_label, **overrides), headers
        ),
        "create_report",
    )


def publish_report(report_id: str, approver_user_id: str = "board-1") -> dict:
    _ok(api_client.submit_for_review(report_id, {}, ANALYST), "submit_for_review")
    _ok(
        api_client.approve_report(report_id, {}, make_board_member_headers(approver_user_id)),
        "approve_report",
    )
    return _ok(api_client.publish_report(report_id, {}, ADMIN), "publish_report")


# --- Outreach ---

def log_contact(case_id: str, outcome: str) -> dict:
    return _ok(
        api_client.log_contact(case_id, {"outcome": outcome}, LIAISON),
        f"log_contact({outcome})",
    )


def analyst_headers(user_id: str = "analyst-op-1") -> dict:
    return make_noise_analyst_headers(user_id)


def board_headers(user_id: str = "board-op-1") -> dict:
    return build_user_headers(user_id, "BoardMember")
