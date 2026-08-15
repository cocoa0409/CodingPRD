"""Gate intake: window boundary, stockpile conservation invariant, and the
site capacity / run-input admission checks."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ADMIN,
    HAULER,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    assert_intake_event,
    create_active_program,
    get_intake_event,
    get_site,
    open_site,
    patch_site,
    record_intake,
    schedule_run,
    set_clock,
    site_stockpile,
    validate_error,
)

WINDOW_MID = "2027-01-05T00:00:00Z"
WINDOW_END = "2027-01-16T23:59:59Z"


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestIntakeWindowBoundary:

    def test_intake_at_window_end_inclusive_accepted(self):
        """PRD section 3.3: "The event's `recorded_at` is stamped from the
        server's logical clock at creation and must fall within the program's
        collection window inclusive of both ends, failing which the recording
        is rejected with `ERR_OUTSIDE_COLLECTION_WINDOW`."

        Design: Difficulty/boundary_precision_check/intake_at_window_end_inclusive
        """
        ctx = create_active_program()
        site = ctx["site"]
        open_site(site)

        # Exactly at window_end: the closed interval admits the recording.
        set_clock(WINDOW_END)
        resp = api_client.create_intake_event(
            {"site_id": site["id"], "source_type": "RESIDENT_SELF_HAUL",
             "tree_count": 2, "size_class": "SMALL"},
            SUPERVISOR,
        )
        intake = resp.json()["data"] if resp.status_code < 400 else None
        assert intake is not None, \
            f"intake at window_end must be admitted, got {resp.status_code}"
        assert_intake_event(intake)
        assert intake["status"] == "RECORDED"
        assert _parse_instant(intake["recorded_at"]) == \
            _parse_instant(WINDOW_END), "recorded_at must be the logical clock"
        # The site absorbs exactly the recorded net volume (site started at 0).
        assert site_stockpile(site["id"]) == \
            pytest.approx(intake["net_volume_cy"])

    def test_intake_one_second_past_window_end_rejected(self):
        """PRD section 2.4: "gate intake must be recorded inside the window
        inclusive of both endpoints".
        PRD section 3.3: "must fall within the program's collection window
        inclusive of both ends, failing which the recording is rejected with
        `ERR_OUTSIDE_COLLECTION_WINDOW`."

        Design: Difficulty/boundary_precision_check/intake_at_window_end_inclusive
        """
        ctx = create_active_program()
        site = ctx["site"]
        open_site(site)

        set_clock(WINDOW_END)
        record_intake(site["id"], tree_count=2, size_class="SMALL",
                      source_type="RESIDENT_SELF_HAUL")
        stockpile_at_close = site_stockpile(site["id"])

        # One second past window_end is outside the closed interval.
        set_clock("2027-01-17T00:00:00Z")
        resp = api_client.create_intake_event(
            {"site_id": site["id"], "source_type": "RESIDENT_SELF_HAUL",
             "tree_count": 1, "size_class": "SMALL"},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_COLLECTION_WINDOW)
        assert site_stockpile(site["id"]) == pytest.approx(stockpile_at_close)


class TestStockpileConservation:

    def test_record_intake_adds_net_volume(self):
        """PRD section 3.3: "The `net_volume_cy` is the gross volume minus the
        contaminated volume, and that net figure is what the site absorbs:
        recording the event adds `net_volume_cy` to the site's
        `stockpile_cy`."

        Design: Difficulty/compensating_invariant/intake_record_void_stockpile_conservation
        """
        ctx = create_active_program(clock=WINDOW_MID,
                                    site_overrides={"capacity_cy": 50})
        site = ctx["site"]
        open_site(site)

        intake = record_intake(site["id"], tree_count=10, size_class="LARGE",
                               source_type="RESIDENT_SELF_HAUL",
                               contaminated_cy=0.5)
        assert_intake_event(intake)
        assert intake["net_volume_cy"] == pytest.approx(
            intake["gross_volume_cy"] - 0.5), \
            "net volume is the gross volume minus the contaminated volume"
        assert site_stockpile(site["id"]) == \
            pytest.approx(intake["net_volume_cy"])

    def test_void_intake_restores_stockpile(self):
        """PRD section 3.3: "Voiding a `RECORDED` intake — by a supervisor or
        administrator, supplying a `reason` that is stored on the event as
        `void_reason` — moves it to the terminal `VOIDED` status and subtracts
        its `net_volume_cy` from the site's `stockpile_cy`. The invariant this
        preserves is exact: recording an intake and later voiding it leaves
        the stockpile unchanged."

        Design: Difficulty/compensating_invariant/intake_record_void_stockpile_conservation
        """
        ctx = create_active_program(clock=WINDOW_MID,
                                    site_overrides={"capacity_cy": 50})
        site = ctx["site"]
        open_site(site)

        intake = record_intake(site["id"], tree_count=10, size_class="LARGE",
                               source_type="RESIDENT_SELF_HAUL",
                               contaminated_cy=0.5)
        assert site_stockpile(site["id"]) > 0

        resp = api_client.void_intake_event(
            intake["id"], {"reason": "duplicate entry at gate"}, SUPERVISOR)
        assert resp.status_code == 200
        voided = get_intake_event(intake["id"])
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "duplicate entry at gate"
        assert site_stockpile(site["id"]) == pytest.approx(0.0), \
            "record-then-void must leave the stockpile unchanged"


class TestSiteCapacityAdmission:

    def test_site_capacity_exact_fit_intake(self):
        """PRD section 3.3: "Admission is capacity-checked — the resulting
        `stockpile_cy` must remain at or below the site's `capacity_cy`, with
        exact equality admitted and any excess rejected as
        `ERR_SITE_CAPACITY_EXCEEDED`."

        Design: Corner/calculations/site_capacity_exact_fit_intake
        """
        ctx = create_active_program(clock=WINDOW_MID)
        site = ctx["site"]
        open_site(site)

        # First delivery establishes a known net volume by read-back; the
        # capacity is then engineered so the second identical delivery lands
        # exactly on the ceiling (the PRD pins the equality rule, not the
        # per-class cubic-yard factor).
        first = record_intake(site["id"], tree_count=2, size_class="SMALL",
                              source_type="RESIDENT_SELF_HAUL")
        net = first["net_volume_cy"]
        assert net > 0
        patch_site(site["id"], capacity_cy=round(2 * net, 2))

        # Exact fit admitted: stockpile rises to exactly capacity_cy.
        record_intake(site["id"], tree_count=2, size_class="SMALL",
                      source_type="RESIDENT_SELF_HAUL")
        site_after = get_site(site["id"])
        assert site_after["stockpile_cy"] == pytest.approx(2 * net)
        assert site_after["stockpile_cy"] == \
            pytest.approx(site_after["capacity_cy"])

        # Any further positive delivery overflows.
        resp = api_client.create_intake_event(
            {"site_id": site["id"], "source_type": "RESIDENT_SELF_HAUL",
             "tree_count": 1, "size_class": "SMALL"},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED)
        assert site_stockpile(site["id"]) == pytest.approx(2 * net)

    def test_site_capacity_patch_below_stockpile_rejected(self):
        """PRD section 3.1: "All site transitions, including capacity edits
        through `capacity_cy`, run under the site's optimistic concurrency
        guard; lowering a site's `capacity_cy` below its current
        `stockpile_cy` is rejected with `ERR_CAPACITY_BELOW_STOCKPILE`."

        Design: Corner/validations/site_capacity_patch_below_stockpile_rejected
        """
        ctx = create_active_program(clock=WINDOW_MID)
        site = ctx["site"]
        open_site(site)
        record_intake(site["id"], tree_count=10, size_class="LARGE",
                      contaminated_cy=0.5)
        stockpile = site_stockpile(site["id"])
        assert stockpile > 0

        resp = api_client.patch_site(
            site["id"],
            {"capacity_cy": round(stockpile / 2, 2),
             "expected_site_version": get_site(site["id"])["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_BELOW_STOCKPILE)
        site_after = get_site(site["id"])
        assert site_after["capacity_cy"] == pytest.approx(100), \
            "a rejected capacity edit must leave capacity_cy unchanged"
        assert site_after["stockpile_cy"] == pytest.approx(stockpile)

    def test_run_input_exceeds_stockpile_rejected(self):
        """PRD section 3.5: "The `input_cy` may not exceed the site's current
        `stockpile_cy` — exact equality draws the pile to zero and is allowed,
        and anything more is rejected with
        `ERR_RUN_INPUT_EXCEEDS_STOCKPILE`."

        Design: Corner/validations/run_input_exceeds_stockpile_rejected
        """
        ctx = create_active_program(clock=WINDOW_MID)
        program, site = ctx["program"], ctx["site"]
        open_site(site)
        record_intake(site["id"], tree_count=1, size_class="MEDIUM")
        stockpile = site_stockpile(site["id"])
        assert stockpile > 0

        run = schedule_run(program["id"], site["id"])
        set_clock("2027-01-17T08:30:00Z")
        resp = api_client.complete_chipping_run(
            run["id"],
            {"input_cy": round(stockpile + 0.5, 2),
             "measured_input_tons": 1.0, "contaminated_input_tons": 0,
             "measured_output_cy": 2.0},
            HAULER,
        )
        validate_error(resp, ApiErrorId.ERR_RUN_INPUT_EXCEEDS_STOCKPILE)
        run_after = api_client.get_chipping_run(run["id"], ADMIN).json()["data"]
        assert run_after["status"] == "SCHEDULED", \
            "a rejected completion must leave the run SCHEDULED"
        assert site_stockpile(site["id"]) == pytest.approx(stockpile)
