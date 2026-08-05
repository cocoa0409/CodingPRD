"""Optimistic concurrency control on the shared LocalArea ITA budget at obligation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_training_ready, create_voucher, obligate_voucher, area_version,
    CM,
)


def _two_nonoverlapping_drafts(api):
    ctx = setup_training_ready(api)
    v1 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-06-01T00:00:00Z",
                        planned_end_date="2026-08-01T00:00:00Z")
    v2 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-09-01T00:00:00Z",
                        planned_end_date="2026-11-01T00:00:00Z")
    ctx["v1_id"], ctx["v2_id"] = v1["id"], v2["id"]
    return ctx


def test_obligate_with_stale_local_area_version_rejected(api):
    """PRD §2.8: "If that value does not match the area's current `version` at obligation
    time — because some other obligation, disbursement, completion, or cancellation has
    advanced the area's version since the client last read the budget — the request is
    rejected with `ERR_STALE_LOCAL_AREA_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/obligate_stale_local_area_version_returns_412
    """
    ctx = _two_nonoverlapping_drafts(api)
    # v1 obligation bumps LocalArea.version, making the captured version stale for v2.
    obligate_voucher(api, ctx["v1_id"], ctx["la_version"])
    resp = api.obligate_voucher(ctx["v2_id"], {"expected_local_area_version": ctx["la_version"]}, CM)
    validate_error(resp, ApiErrorId.ERR_STALE_LOCAL_AREA_VERSION.value)
    v1 = validate_success(api.get_voucher(ctx["v1_id"], CM))
    assert v1["status"] == "OBLIGATED", v1


def test_obligate_with_refreshed_version_succeeds(api):
    """PRD §2.8: "The obligate request must include `expected_local_area_version` carrying
    the client's last-observed `version` of the owning `LocalArea`."

    Design: Corner/cross_cutting_complexity_layers/obligate_fresh_version_after_refresh_succeeds
    """
    ctx = _two_nonoverlapping_drafts(api)
    obligate_voucher(api, ctx["v1_id"], ctx["la_version"])
    fresh = area_version(api, ctx["la_id"])  # re-read the version after v1's obligation
    result = validate_success(
        api.obligate_voucher(ctx["v2_id"], {"expected_local_area_version": fresh}, CM))
    assert result["status"] == "OBLIGATED", result
    area = validate_success(api.get_local_area(ctx["la_id"], CM))
    assert area["ita_budget_obligated_cents"] == 200000, area
