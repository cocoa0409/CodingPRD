"""Damage-inspection scheduling and the TRAVEL_BUFFER_MINUTES non-overlap rule."""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    make_public_adjuster_headers,
)
from test_helpers.fixtures import setup_active_contract, new_draft_claim, file_claim

FIRM = TEST_USERS["firm_principal_headers"]


def _two_filed_claims(api):
    ctx = setup_active_contract(api)
    clm_a = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"])
    file_claim(api, clm_a, ctx["adj"])
    clm_b = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"], peril_type="HAIL",
                            date_of_loss="2026-06-20T00:00:00Z", pa_rcv_estimate_cents=7_500_000)
    file_claim(api, clm_b, ctx["adj"])
    return ctx, clm_a, clm_b


def test_inspection_window_within_buffer_rejected(api):
    """PRD §3.3: "if the new window falls within a fixed buffer — denoted
    `TRAVEL_BUFFER_MINUTES`, which equals 60 minutes — of another of that adjuster's
    inspections, it is rejected with `ERR_INSPECTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/inspection_window_within_buffer_rejected
    """
    ctx, clm_a, clm_b = _two_filed_claims(api)
    pa = make_public_adjuster_headers(ctx["adj"])
    validate_success(api.schedule_inspection(
        clm_a, {"inspection_start": "2026-07-10T09:00:00Z", "inspection_end": "2026-07-10T11:00:00Z"}, pa))
    # B starts 30 min after A ends -> inside the 60-minute buffer.
    resp = api.schedule_inspection(
        clm_b, {"inspection_start": "2026-07-10T11:30:00Z", "inspection_end": "2026-07-10T13:00:00Z"}, pa)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_OVERLAP.value, expected_status=409)


def test_inspection_window_outside_buffer_accepted(api):
    """PRD §3.3: "A scheduled window may not sit too close to another inspection already
    booked for the same adjuster: if the new window falls within a fixed buffer — denoted
    `TRAVEL_BUFFER_MINUTES`, which equals 60 minutes — of another of that adjuster's
    inspections, it is rejected with `ERR_INSPECTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/inspection_window_within_buffer_rejected
    """
    ctx, clm_a, clm_b = _two_filed_claims(api)
    pa = make_public_adjuster_headers(ctx["adj"])
    validate_success(api.schedule_inspection(
        clm_a, {"inspection_start": "2026-07-10T09:00:00Z", "inspection_end": "2026-07-10T11:00:00Z"}, pa))
    # B starts 90 min after A ends -> outside the 60-minute buffer, so accepted.
    data = validate_success(api.schedule_inspection(
        clm_b, {"inspection_start": "2026-07-10T12:30:00Z", "inspection_end": "2026-07-10T14:00:00Z"}, pa))
    assert data["inspection_start"] is not None
