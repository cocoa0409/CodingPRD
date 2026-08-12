"""Diversion reports: close gates, frozen totals, unique period (PRD §3.9, §2.9)."""
from test_helpers import (
    ApiErrorId,
    create_category,
    create_in_progress_job,
    create_manifested_batch,
    create_report,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["warehouse_admin_headers"]
COORD = TEST_USERS["crew_coordinator_headers"]


# ---------------------------------------------------------------------------
# Corner: calculations / closed_report_totals_frozen
# ---------------------------------------------------------------------------

def test_closed_report_totals_frozen(api):
    """PRD §2.9: "Closing a report is an ops-run checkpoint: the figures freeze at
    close, and a `CLOSED` report never recomputes, no matter what later happens in
    that period."
    PRD §3.9: "At close the five figures freeze: from the batch stream, certified
    diverted pounds are the sum of `diverted_weight_lbs` over batches whose
    `report_period` equals the period, standing `WEIGHED` or `SORTED`, in
    `divertible` categories, and batch landfill pounds are the sum of
    `contamination_weight_lbs` over the period's `WEIGHED` and `SORTED` batches
    plus the full `scale_weight_lbs` of the period's `DISPOSED_HAZARD` batches."

    Design: Corner/calculations/closed_report_totals_frozen
    """
    set_clock("2026-07-06T09:00:00Z")
    report = create_report("2026-07")
    ctx = create_in_progress_job(start="2026-07-07T08:00:00Z", end="2026-07-07T16:00:00Z",
                                 title="Freeze Job", quoted_fee_cents=1000)
    category = create_category(code="FRCAT", display_name="FR Cat")
    batch1 = create_manifested_batch(ctx["job"]["id"], category["id"],
                                     estimated_weight_lbs=110)
    validate_success(api.weigh_batch(
        batch1["id"], {"scale_weight_lbs": 110, "contamination_weight_lbs": 10}, COORD))

    report = validate_success(api.close_diversion_report(report["id"], ADMIN))
    assert report["status"] == "CLOSED"
    assert report["total_diverted_lbs"] == 100
    assert report["landfill_lbs"] == 10

    # Later period activity must not move the frozen figures.
    batch2 = create_manifested_batch(ctx["job"]["id"], category["id"],
                                     estimated_weight_lbs=220)
    validate_success(api.weigh_batch(
        batch2["id"], {"scale_weight_lbs": 220, "contamination_weight_lbs": 20}, COORD))
    report = get_success_data(api.get_diversion_report(report["id"], ADMIN))
    assert report["total_diverted_lbs"] == 100, "CLOSED report never recomputes"
    assert report["landfill_lbs"] == 10


# ---------------------------------------------------------------------------
# Corner: calculations / report_close_blocked_by_manifested_batch
# ---------------------------------------------------------------------------

def test_report_close_blocked_by_manifested_batch(api):
    """PRD §3.9: "Closing is an ops-run checkpoint by an administrator, gated three
    ways: the report must stand `OPEN` (`ERR_REPORT_NOT_OPEN`); no salvage batch
    anywhere may still stand `MANIFESTED`, because unweighed material has no
    `report_period` yet and cannot be attributed
    (`ERR_UNWEIGHED_BATCHES_IN_PERIOD`); and no batch of the report's period may
    stand `QUARANTINED` (`ERR_QUARANTINED_BATCHES_OPEN`)."

    Design: Corner/calculations/report_close_blocked_by_manifested_batch
    """
    set_clock("2026-08-03T09:00:00Z")
    report = create_report("2026-08")
    ctx = create_in_progress_job(start="2026-08-04T08:00:00Z", end="2026-08-04T16:00:00Z",
                                 title="Block Job", quoted_fee_cents=1000)
    category = create_category(code="BLCAT", display_name="BL Cat")
    create_manifested_batch(ctx["job"]["id"], category["id"], estimated_weight_lbs=300)

    response = api.close_diversion_report(report["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_UNWEIGHED_BATCHES_IN_PERIOD)
    report = get_success_data(api.get_diversion_report(report["id"], ADMIN))
    assert report["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Corner: validations / duplicate_report_period_rejected
# ---------------------------------------------------------------------------

def test_duplicate_report_period_rejected(api):
    """PRD §3.9: "A `WarehouseAdmin` opens a `DiversionReport` by naming its
    `period` in `YYYY-MM` form; one report per period, so a duplicate fails with
    `ERR_DUPLICATE_REPORT_PERIOD`."

    Design: Corner/validations/duplicate_report_period_rejected
    """
    create_report("2026-09")
    response = api.create_diversion_report({"period": "2026-09"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD)
