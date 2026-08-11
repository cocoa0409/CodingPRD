"""Seller activity report: FINAL vs PROVISIONAL rate divergence."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_confirmed_request,
    get_success_data,
    issue_credential,
    redeem_credential,
    run_sweep,
    set_clock,
    setup_vacant_auto_world,
    validate_success,
)


def _report(world, listing_id, mode):
    resp = api_client.get_activity_report(
        listing_id, world["la_headers"], params={"mode": mode}
    )
    return validate_success(resp)


def _setup_one_completed_one_confirmed():
    """VACANT auto-approve listing with R1 completed via sweep and R2 still CONFIRMED."""
    world = setup_vacant_auto_world()
    listing_id = world["listing"]["id"]
    ba_id = world["buyer_agent"]["id"]
    seller_id = world["seller"]["id"]
    la_id = world["listing_agent"]["id"]

    r1 = create_confirmed_request(listing_id, ba_id, seller_id,
                                  "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    c1 = issue_credential(r1["id"], la_id, "LOCKBOX_CODE")
    r2 = create_confirmed_request(listing_id, ba_id, seller_id,
                                  "2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z")
    set_clock("2026-05-01T10:05:00Z")
    redeem_credential(c1["id"], ba_id)
    set_clock("2026-05-01T10:45:00Z")
    run_sweep()
    return world, listing_id, r1, r2


def test_report_provisional_vs_final_final_mode(api):
    """PRD §3.8: "In FINAL mode, `completion_rate` is the completed count
    divided by the terminal total — the sum of completed, no-show, cancelled,
    expired, and declined counts — rounded half-up to 2 decimal places, and
    reported as 0.00 when the listing has no terminal requests at all."

    Design: Difficulty/dual_variant_calc/report_provisional_vs_final
    """
    world, listing_id, r1, r2 = _setup_one_completed_one_confirmed()
    report = _report(world, listing_id, "FINAL")
    assert report["completed_count"] == 1, report
    assert report["completion_rate"] == pytest.approx(1.00, abs=1e-9), report
    assert report["provisional_completion_rate"] is None, report

    req1 = validate_success(api_client.get_showing_request(r1["id"], world["la_headers"]))
    req2 = validate_success(api_client.get_showing_request(r2["id"], world["la_headers"]))
    assert req1["status"] == "COMPLETED"
    assert req2["status"] == "CONFIRMED"


def test_report_provisional_vs_final_provisional_mode(api):
    """PRD §3.8: "In PROVISIONAL mode the platform additionally reports
    `provisional_completion_rate`, computed as the completed count divided by
    the larger of (completed plus no-show plus confirmed) and 1, again rounded
    half-up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/report_provisional_vs_final
    """
    world, listing_id, r1, r2 = _setup_one_completed_one_confirmed()
    report = _report(world, listing_id, "PROVISIONAL")
    assert report["confirmed_count"] == 1, report
    # completed=1, no_show=0, confirmed=1 -> 1 / max(2, 1) == 0.50
    assert report["provisional_completion_rate"] == pytest.approx(0.50, abs=1e-9), report
