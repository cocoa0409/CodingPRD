"""Corner queue / rbac section — role denials, applicator identity,
segregation of duties."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_applicator_headers, make_safety_officer_headers,
    make_site_manager_headers,
    create_bin, create_applicator, set_clock,
    get_first_alert_for_bin, create_hotspot_reading,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_bin_payload, create_lot_payload, create_contract_payload,
    create_fumigation_payload, create_permit_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]
SO = TEST_USERS["safety_officer_headers"]


def test_site_manager_cannot_create_contract(api):
    """PRD section 2.1: "A well-formed request whose role is not permitted
    to invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP
    403)."
    PRD section 2.1: "A `FarmOwner` controls the money side: creating
    marketing contracts and insurance policies and approving insurance
    claims."

    SiteManager on POST /grain/contracts is denied.

    Design: Corner/rbac/site_manager_cannot_create_contract
    """
    resp = api_client.create_contract(create_contract_payload(
        contracted_bu=1000.00), SM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_farm_owner_cannot_create_bin(api):
    """PRD section 2.1: "A `SiteManager` runs the bin site: creating bins
    and lots, ingesting temperature readings, ...".
    PRD section 2.1: "A well-formed request whose role is not permitted to
    invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    FarmOwner on POST /grain/bins is denied.

    Design: Corner/rbac/farm_owner_cannot_create_bin
    """
    resp = api_client.create_bin(
        create_bin_payload(name="BIN-RB", capacity_bu=5000.00, crop="CORN"),
        FO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_applicator_cannot_create_lot(api):
    """PRD section 2.1: "A `CertifiedApplicator` creates and clears
    fumigation records."
    PRD section 2.1: "A well-formed request whose role is not permitted to
    invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    CertifiedApplicator on POST /grain/lots is denied even with a valid
    entity-backed X-User-ID.

    Design: Corner/rbac/applicator_cannot_create_lot
    """
    b = create_bin(name="BIN-RA")
    app = create_applicator()
    resp = api_client.create_lot(
        create_lot_payload(b["id"], original_bu=100.00),
        make_applicator_headers(app["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_farm_owner_cannot_close_alert(api):
    """PRD section 3.2: "A `SiteManager` closes an open alert by naming an
    `outcome` of `RESOLVED` or `CONFIRMED_LOSS`."
    PRD section 2.1: "A well-formed request whose role is not permitted to
    invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    FarmOwner attempting alert closure is denied; alert stays OPEN.

    Design: Corner/rbac/farm_owner_cannot_close_alert
    """
    b = create_bin(name="BIN-RC")
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    resp = api_client.close_alert(alert["id"], {"outcome": "RESOLVED"}, FO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    after = get_success_data(api_client.get_alert(alert["id"], SM))
    assert after["status"] == "OPEN"


def test_applicator_identity_mismatch_forbidden(api):
    """PRD section 3.3: "Segregation begins at creation: the applicator
    acts as self, so the payload's `applicator_id` must equal the caller's
    `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` at the
    authorization layer, before any existence or shape check."

    Caller A creating a fumigation naming applicator B -> 403.

    Design: Corner/rbac/applicator_identity_mismatch_forbidden
    """
    b = create_bin(name="BIN-AI")
    app_a = create_applicator(name="Alice A", license_no="LIC-A")
    app_b = create_applicator(name="Bob B", license_no="LIC-B")
    resp = api_client.create_fumigation(create_fumigation_payload(
        b["id"], app_b["id"]), make_applicator_headers(app_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_sod_fumigation_clear_by_applier_rejected(api):
    """PRD section 3.3: "Clearance is segregated from application. A
    `CertifiedApplicator` clears the record, but the caller's `X-User-ID`
    must differ from the record's `applicator_id`; the same applicator who
    applied a fumigation may not clear it, and an attempt is rejected with
    `ERR_SOD_SAME_APPLICATOR`."

    After REI, applicator A (who applied) cannot clear; applicator B can,
    and the record shows cleared_by_applicator_id == B.

    Design: Corner/rbac/sod_fumigation_clear_by_applier_rejected
    """
    b = create_bin(name="BIN-SD")
    app_a = create_applicator(name="Alice A", license_no="LIC-A")
    app_b = create_applicator(name="Bob B", license_no="LIC-B")
    fum = get_success_data(api_client.create_fumigation(
        create_fumigation_payload(b["id"], app_a["id"]),
        make_applicator_headers(app_a["id"])))
    set_clock("2026-08-04T00:00:00Z")

    bad = api_client.clear_fumigation(
        fum["id"], make_applicator_headers(app_a["id"]))
    validate_error(bad, ApiErrorId.ERR_SOD_SAME_APPLICATOR,
                   expected_status=403)

    ok = api_client.clear_fumigation(
        fum["id"], make_applicator_headers(app_b["id"]))
    data = validate_success(ok, expected_status=200)
    assert data["status"] == "CLEARED"
    assert data["cleared_by_applicator_id"] == app_b["id"]


def test_sod_permit_self_approve_rejected(api):
    """PRD section 3.4: "Approval belongs to a `SafetyOfficer` and is
    deliberately segregated: the approver's `X-User-ID` must differ from
    the `requester_user_id`, even when both hold the same role, and a
    self-approval attempt is rejected with `ERR_SOD_PERMIT_SELF_APPROVE`."

    Permit requested by SafetyOfficer so-1 cannot be approved by so-1;
    so-2 approves and is stamped as approver.

    Design: Corner/rbac/sod_permit_self_approve_rejected
    """
    b = create_bin(name="BIN-SP")
    permit = get_success_data(api_client.create_permit(create_permit_payload(
        b["id"]), make_safety_officer_headers("so-1")))

    bad = api_client.approve_permit(
        permit["id"], make_safety_officer_headers("so-1"))
    validate_error(bad, ApiErrorId.ERR_SOD_PERMIT_SELF_APPROVE,
                   expected_status=403)

    ok = api_client.approve_permit(
        permit["id"], make_safety_officer_headers("so-2"))
    data = validate_success(ok, expected_status=200)
    assert data["status"] == "APPROVED"
    assert data["approver_user_id"] == "so-2"
