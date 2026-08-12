"""Incident reporting workflow: phone/written branches, deadline boundaries,
and penalty components."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, assert_same_instant,
    create_approved_carrier_paid, create_standard_catalog, create_shipment,
    create_incident, set_clock,
)
from test_helpers.fixtures import ADMIN, OFFICER_A, REGULATOR, _ok


def _setup_shipment_with_incident(api, occurred_at, severity):
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    shipment = create_shipment(carrier["id"], material["id"], spec["id"])
    incident = create_incident(shipment["id"], occurred_at=occurred_at, severity=severity)
    return carrier, incident


# ---------------------------------------------------------------------------
# Corner/state_machines/incident_minor_skips_phone_branch
# ---------------------------------------------------------------------------

def test_incident_minor_skips_phone_branch(api):
    """PRD §3.9: "Filing the written report requires `PHONE_REPORTED` — with one
    exception: a `MINOR` report may file directly from `DRAFT`; any other shape
    yields `ERR_PHONE_REPORT_REQUIRED`."
    PRD §3.9: "`phone_report_required` is true exactly when severity is `MAJOR`
    or `CATASTROPHIC`".
    PRD §3.9: "a severity base of 0 cents for `MINOR`".

    Design: Corner/state_machines/incident_minor_skips_phone_branch
    """
    carrier, incident = _setup_shipment_with_incident(api, "2026-05-02T00:00:00Z", "MINOR")
    assert incident["phone_report_required"] is False

    set_clock("2026-05-03T00:00:00Z")
    filed = validate_success(api.file_written_report(incident["id"], OFFICER_A))
    assert filed["status"] == "WRITTEN_FILED"
    assert filed["penalty_cents"] == 0  # MINOR base 0, no late components


# ---------------------------------------------------------------------------
# Corner/errors/phone_report_required_for_major
# ---------------------------------------------------------------------------

def test_phone_report_required_for_major(api):
    """PRD §3.9: "`phone_report_required` is true exactly when severity is
    `MAJOR` or `CATASTROPHIC`".
    PRD §3.9: "Filing the written report requires `PHONE_REPORTED` — with one
    exception: a `MINOR` report may file directly from `DRAFT`; any other shape
    yields `ERR_PHONE_REPORT_REQUIRED`."
    PRD §3.9: "`is_phone_late` is true when a phone report was required and
    either never happened or was recorded strictly after `phone_deadline` — a
    phone call recorded exactly at the deadline is on time".

    Design: Corner/errors/phone_report_required_for_major
    """
    carrier, incident = _setup_shipment_with_incident(api, "2026-05-02T00:00:00Z", "MAJOR")
    assert incident["phone_report_required"] is True

    set_clock("2026-05-02T06:00:00Z")
    resp = api.file_written_report(incident["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_PHONE_REPORT_REQUIRED)

    _ok(api.record_phone_report(incident["id"], OFFICER_A), "phone")
    filed = validate_success(api.file_written_report(incident["id"], OFFICER_A))
    assert filed["status"] == "WRITTEN_FILED"
    assert filed["is_phone_late"] is False  # phone at +6h <= +12h
    assert filed["penalty_cents"] == 50000  # MAJOR base, no late components


# ---------------------------------------------------------------------------
# Corner/calculations/written_deadline_inclusive_boundary
# ---------------------------------------------------------------------------

def test_written_deadline_inclusive_boundary(api):
    """PRD §3.9: "`written_report_deadline` is thirty days after
    `occurred_at`".
    PRD §3.9: "`is_written_late` is true when `written_filed_at` is strictly
    after `written_report_deadline` — filing exactly at the deadline is on
    time".

    Design: Corner/calculations/written_deadline_inclusive_boundary
    """
    carrier, incident = _setup_shipment_with_incident(api, "2026-06-01T00:00:00Z", "MINOR")
    assert_same_instant(incident["written_report_deadline"], "2026-07-01T00:00:00Z")

    set_clock("2026-07-01T00:00:00Z")  # exactly AT the deadline
    filed = validate_success(api.file_written_report(incident["id"], OFFICER_A))
    assert filed["is_written_late"] is False, "filed exactly at the deadline: inclusive on-time"
    assert filed["penalty_cents"] == 0
