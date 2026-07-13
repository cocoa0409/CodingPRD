"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB, clock at 2026-03-01T00:00:00Z) before
every test. Setup calls use get_success_data() so a broken precondition surfaces as a
clear "Setup failed" rather than a confusing assertion error.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_tester_headers
from . import factories

_ADMIN = TEST_USERS["admin_headers"]
_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock(iso: str, api=api_client, admin=_ADMIN) -> str:
    """Set the logical clock; returns the new current_utc."""
    data = get_success_data(api.set_clock(iso, admin))
    return data.get("current_utc", iso)


# --------------------------------------------------------------------------- #
# Single-entity creators
# --------------------------------------------------------------------------- #
def create_connection(api=api_client, admin=_ADMIN, **overrides) -> dict:
    """Create a ServiceConnection (COMPLIANT, version 1). Unique account_number by default."""
    payload = factories.connection_payload(**overrides)
    if "account_number" not in overrides:
        payload["account_number"] = f"AC-{_uniq():05d}"
    return get_success_data(api.create_connection(payload, admin))


def create_device(service_connection_id, api=api_client, admin=_ADMIN, **overrides) -> dict:
    """Create an ACTIVE BackflowDevice on the given connection. Unique serial by default."""
    payload = factories.device_payload(service_connection_id, **overrides)
    if "serial_number" not in overrides:
        payload["serial_number"] = f"SN-{_uniq():05d}"
    return get_success_data(api.create_device(payload, admin))


def create_tester(api=api_client, admin=_ADMIN, **overrides) -> dict:
    """Create an ACTIVE Tester. Unique certification_number by default."""
    payload = factories.tester_payload(**overrides)
    if "certification_number" not in overrides:
        payload["certification_number"] = f"CN-{_uniq():05d}"
    return get_success_data(api.create_tester(payload, admin))


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def submit_report(device_id, tester_id, api=api_client, **overrides) -> dict:
    """Submit a TestReport as the owning tester (X-User-ID == tester_id)."""
    payload = factories.report_payload(device_id, tester_id, **overrides)
    headers = make_tester_headers(tester_id)
    return get_success_data(api.create_report(payload, headers))


def accept_report(report_id, api=api_client, admin=_ADMIN) -> dict:
    return get_success_data(api.accept_report(report_id, admin))


def reject_report(report_id, reason, api=api_client, admin=_ADMIN) -> dict:
    return get_success_data(api.reject_report(report_id, {"rejection_reason": reason}, admin))


# --------------------------------------------------------------------------- #
# Composite: connection + device + tester
# --------------------------------------------------------------------------- #
def setup_connection_device_tester(api=api_client, admin=_ADMIN,
                                   connection=None, device=None, tester=None):
    """Active connection + one ACTIVE device + one ACTIVE tester.

    Returns (connection, device, tester). Pass dicts of overrides for each.
    """
    conn = create_connection(api, admin, **(connection or {}))
    dev = create_device(conn["id"], api, admin, **(device or {}))
    tst = create_tester(api, admin, **(tester or {}))
    return conn, dev, tst


# --------------------------------------------------------------------------- #
# Hazard surveys
# --------------------------------------------------------------------------- #
def create_survey(service_connection_id, api=api_client, admin=_ADMIN, **scores) -> dict:
    """Create a DRAFT hazard survey."""
    payload = factories.survey_payload(service_connection_id, **scores)
    return get_success_data(api.create_survey(payload, admin))


def finalize_survey(survey_id, service_connection_id, api=api_client, admin=_ADMIN) -> dict:
    """Finalize a draft survey using the connection's live version (OCC match)."""
    conn = get_success_data(api.get_connection(service_connection_id, admin))
    payload = {"expected_service_connection_version": conn["version"]}
    return get_success_data(api.finalize_survey(survey_id, payload, admin))


def create_and_finalize_survey(service_connection_id, api=api_client, admin=_ADMIN,
                               **scores) -> dict:
    """Create a draft survey with the given scores and finalize it, writing the
    connection's risk_tier. Returns the finalized survey."""
    survey = create_survey(service_connection_id, api, admin, **scores)
    return finalize_survey(survey["id"], service_connection_id, api, admin)


def set_connection_risk_tier(service_connection_id, target_tier, api=api_client, admin=_ADMIN):
    """Drive a device-free connection's effective risk_tier to LOW/MODERATE/HIGH via a
    finalized questionnaire-only survey (device floor stays LOW with no HIGH device).

    LOW: all-zero scores. MODERATE: auxiliary=30 floor. HIGH: chemical=35 floor.
    """
    if target_tier == "LOW":
        scores = dict(premise_use_score=0, chemical_exposure_score=0, auxiliary_supply_score=0)
    elif target_tier == "MODERATE":
        scores = dict(premise_use_score=10, chemical_exposure_score=10, auxiliary_supply_score=30)
    elif target_tier == "HIGH":
        scores = dict(premise_use_score=10, chemical_exposure_score=35, auxiliary_supply_score=10)
    else:
        raise ValueError(f"unknown tier {target_tier!r}")
    return create_and_finalize_survey(service_connection_id, api, admin, **scores)


# --------------------------------------------------------------------------- #
# Shutoff notices
# --------------------------------------------------------------------------- #
def issue_notice(service_connection_id, reason="OVERDUE_TEST", api=api_client, admin=_ADMIN) -> dict:
    payload = factories.notice_payload(service_connection_id, reason=reason)
    return get_success_data(api.create_notice(payload, admin))


def first_notice_for_connection(service_connection_id, api=api_client, admin=_ADMIN) -> dict:
    """Return the first ShutoffNotice on the connection (list filtered by connection id)."""
    resp = api.list_notices(admin, params={"service_connection_id": service_connection_id})
    data = get_success_data(resp)
    assert data, "Setup failed: expected at least one notice on the connection"
    return data[0]


# --------------------------------------------------------------------------- #
# Cascades / composite states
# --------------------------------------------------------------------------- #
def setup_device_needs_repair(api=api_client, admin=_ADMIN, device=None, tester=None):
    """Connection + ACTIVE device + tester, then a FAIL report is accepted so the device
    is NEEDS_REPAIR and an ISSUED FAILED_TEST notice exists.

    Returns dict(connection, device, tester, report, notice).
    """
    conn, dev, tst = setup_connection_device_tester(api, admin, device=device, tester=tester)
    report = submit_report(dev["id"], tst["id"], api,
                           relief_valve_differential_psid=1.5, check_valve_1_psid=1.5)
    accept_report(report["id"], api, admin)
    notice = first_notice_for_connection(conn["id"], api, admin)
    return {"connection": conn, "device": dev, "tester": tst,
            "report": report, "notice": notice}


def setup_shutoff_connection(api=api_client, admin=_ADMIN):
    """Connection with one ACTIVE device driven into SHUTOFF posture: a LOW-risk manual
    notice (grace 30) is issued at clock 2026-03-01, the clock is advanced past the
    enforcement_due_date (2026-03-31), and the notice is enforced.

    Returns (connection, device, notice_after_enforce).
    """
    conn = create_connection(api, admin)
    dev = create_device(conn["id"], api, admin, install_date="2026-01-01T00:00:00Z")
    notice = issue_notice(conn["id"], "UNREPAIRED_DEVICE", api, admin)
    set_clock("2026-04-01T00:00:00Z", api, admin)
    enforced = get_success_data(api.enforce_notice(notice["id"], admin))
    return conn, dev, enforced


def book_appointment(device_id, tester_id, scheduled_start, scheduled_end, api=api_client) -> dict:
    """Book a BOOKED appointment as the owning tester."""
    payload = factories.appointment_payload(device_id, tester_id,
                                             scheduled_start=scheduled_start,
                                             scheduled_end=scheduled_end)
    headers = make_tester_headers(tester_id)
    return get_success_data(api.create_appointment(payload, headers))
