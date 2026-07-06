"""Marriage-license filing and return compliance: the happy path to RECORDED and
the jurisdiction, validity, and return-window gates (PRD Section 3.6).
"""
from test_helpers import (
    fixtures as fx,
    validate_success, validate_error,
    ApiErrorId,
    make_coordinator_headers, make_couple_headers, make_officiant_headers,
)

COORD = make_coordinator_headers()


def test_full_compliance_path_reaches_recorded(api):
    """PRD §3.6: "A coordinator then records the signed license with the registry,
    moving `SIGNED → RECORDED`, but only within the return window: the current
    clock must be at or before `return_deadline` (the boundary is inclusive),
    otherwise the request is rejected with `ERR_LICENSE_RETURN_OVERDUE`. Recording
    stamps `recorded_at` with the current clock."

    Design: Corner/state_machines/license_full_compliance_path_records
    """
    ctx = fx.setup_confirmed_booking(api)
    lic = fx.create_license(api, ctx.booking, ctx.couple, jurisdiction="CA",
                            issued_date="2026-02-20T00:00:00Z", expiry_date="2026-12-01T00:00:00Z")
    fx.file_license(api, lic, ctx.couple)
    fx.sign_license(api, lic, ctx.officiant)
    resp = api.transition_marriage_license(lic["id"], {"to_state": "RECORDED"}, COORD)
    data = validate_success(resp, 200)
    assert data["status"] == "RECORDED"
    assert data["recorded_at"] is not None


def test_record_after_return_deadline_rejected(api):
    """PRD §3.6: "the current clock must be at or before `return_deadline` (the
    boundary is inclusive), otherwise the request is rejected with
    `ERR_LICENSE_RETURN_OVERDUE`."

    Design: Corner/calculations/license_record_after_deadline_returns_return_overdue
    """
    ctx = fx.setup_confirmed_booking(api)
    lic = fx.create_license(api, ctx.booking, ctx.couple, jurisdiction="CA",
                            issued_date="2026-02-20T00:00:00Z", expiry_date="2026-12-01T00:00:00Z")
    fx.file_license(api, lic, ctx.couple)
    fx.sign_license(api, lic, ctx.officiant)  # signed at clock 2026-03-01 -> deadline 2026-03-11
    fx.set_clock(api, "2026-03-11T00:00:01Z")  # 1s past the inclusive deadline
    resp = api.transition_marriage_license(lic["id"], {"to_state": "RECORDED"}, COORD)
    validate_error(resp, ApiErrorId.ERR_LICENSE_RETURN_OVERDUE.value)


def test_sign_after_license_expiry_rejected(api):
    """PRD §3.6: "The assigned officiant signs a filed license, moving `FILED →
    SIGNED`, but only while the license is still valid: the current clock must be
    at or before the license's `expiry_date`, otherwise the sign is rejected with
    `ERR_LICENSE_EXPIRED`."

    Design: Corner/validations/sign_license_after_expiry_returns_license_expired
    """
    ctx = fx.setup_confirmed_booking(api)
    lic = fx.create_license(api, ctx.booking, ctx.couple, jurisdiction="CA",
                            issued_date="2026-02-20T00:00:00Z", expiry_date="2026-03-10T00:00:00Z")
    fx.file_license(api, lic, ctx.couple)
    fx.set_clock(api, "2026-03-11T00:00:00Z")  # past expiry_date
    resp = api.transition_marriage_license(
        lic["id"], {"to_state": "SIGNED"}, make_officiant_headers(ctx.officiant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_EXPIRED.value)


def test_file_license_wrong_jurisdiction_rejected(api):
    """PRD §3.6: "and that the license's `jurisdiction` equal the booking venue's
    `jurisdiction` (otherwise `ERR_LICENSE_JURISDICTION_MISMATCH`)."

    Design: Corner/validations/file_license_wrong_jurisdiction_returns_mismatch
    """
    ctx = fx.setup_confirmed_booking(api)  # venue jurisdiction CA
    lic = fx.create_license(api, ctx.booking, ctx.couple, jurisdiction="NY", license_number="NY-100",
                            issued_date="2026-02-20T00:00:00Z", expiry_date="2026-12-01T00:00:00Z")
    resp = api.transition_marriage_license(
        lic["id"], {"to_state": "FILED"}, make_couple_headers(ctx.couple["id"])
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_JURISDICTION_MISMATCH.value)


def test_file_license_before_booking_confirmed_rejected(api):
    """PRD §3.6: "Filing requires, in order, that the license be in `NOT_FILED`
    (otherwise `ERR_INVALID_STATE`), that the backing booking be `CONFIRMED` or
    `BACKUP_CONFIRMED` (otherwise `ERR_BOOKING_NOT_CONFIRMED`)".

    Design: Corner/validations/file_license_before_booking_confirmed_returns_not_confirmed
    """
    ctx = fx.setup_held_booking(api)  # booking is HOLD, not CONFIRMED
    lic = fx.create_license(api, ctx.booking, ctx.couple, jurisdiction="CA", license_number="CA-780",
                            issued_date="2026-02-20T00:00:00Z", expiry_date="2026-12-01T00:00:00Z")
    resp = api.transition_marriage_license(
        lic["id"], {"to_state": "FILED"}, make_couple_headers(ctx.couple["id"])
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CONFIRMED.value)
