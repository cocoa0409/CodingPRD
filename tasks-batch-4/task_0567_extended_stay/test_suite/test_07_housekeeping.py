"""Housekeeping visit scheduling: the visit_type default and enum validation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    checkin_retail_stay, create_housekeeping_visit_payload, TEST_USERS,
)

PM = TEST_USERS["property_manager_headers"]


def test_housekeeping_visit_type_defaults_to_standard(api):
    """PRD §3.5: "an optional `visit_type` that is either `STANDARD` or `DEEP` and
    defaults to `STANDARD`."

    Design: Corner/entities/default_visit_type_standard_on_housekeeping
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=0)
    created = validate_success(api.create_housekeeping_visit(
        create_housekeeping_visit_payload(ctx["stay"]["id"],
                                          scheduled_date="2026-05-15T00:00:00Z"), PM),
        expected_status=201)
    fetched = validate_success(api.get_housekeeping_visit(created["id"], PM))
    assert fetched["visit_type"] == "STANDARD"
    assert fetched["status"] == "SCHEDULED"


def test_housekeeping_invalid_visit_type_rejected(api):
    """PRD §2.8: "an enum field carrying a value outside its declared set (for
    example, a `visit_type` other than `STANDARD` or `DEEP`) yields
    `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/error_invalid_enum_visit_type
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=0)
    resp = api.create_housekeeping_visit(
        create_housekeeping_visit_payload(ctx["stay"]["id"],
                                          scheduled_date="2026-05-15T00:00:00Z",
                                          visit_type="SUPERDEEP"), PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)
