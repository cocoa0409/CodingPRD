"""Storage agreements: activation cascade from run completion, accrual with
the minimum-days floor, duplicate prevention, close gates, and title transfer
on default (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_storage_agreement,
    complete_run,
    create_dried_lot,
    create_queued_lot,
    create_storage_agreement,
    get_lot,
    get_ticket,
    schedule_run,
    set_clock,
    setup_base,
    setup_dried_lot_scenario,
    start_run,
    validate_error,
    validate_success,
)


def _get_agreement(api, agreement_id, headers):
    return validate_success(api.get_storage_agreement(agreement_id, headers), 200)


class TestRunCompletionStorageCascade:
    """DRYING -> STORED via a RESERVED agreement: depth-3 cascade."""

    def _setup_reserved_cascade(self):
        ctx = setup_base(with_schedule=True)
        lot, _t, ticket = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-05",
            requested_bushels=200, sample_moisture_pct=22.5, foreign_material_pct=2.0)
        agreement = create_storage_agreement(lot["id"])
        run = schedule_run(ctx["unit"]["id"], lot["id"], ticket["id"])
        set_clock("2026-09-05T08:00:00Z")
        start_run(run["id"], meter_start_therms=1200.0)
        set_clock("2026-09-05T12:00:00Z")
        return ctx, lot, ticket, run, agreement

    def test_completion_activates_reserved_agreement(self, api, manager_headers):
        """PRD §3.5: "With exactly one `RESERVED` agreement for the lot, a
        three-link cascade fires: the run's completion first applies the same
        weight reconciliation to the lot; the lot reaching dried-weight state
        then activates the agreement, moving it `RESERVED` → `ACTIVE` with
        `baseline_bushels` fixed from the just-completed final weight and
        `start_date` set to the completion date; and that activation moves the
        lot to `STORED`, its version advancing."
        PRD §3.6: "`baseline_bushels` is fixed as the lot's
        `final_dry_weight_lbs` divided by the commodity's pounds per bushel
        (56 for CORN, 60 for SOYBEAN, 60 for WHEAT), rounded half up to two
        decimal places"

        Design: Difficulty/transitive_cascade/run_completion_storage_activation_cascade
        """
        ctx, lot, ticket, run, agreement = self._setup_reserved_cascade()
        assert agreement["status"] == "RESERVED"

        complete_run(run["id"], scale_out_weight_lbs=9050, discharge_moisture_pct=15.0,
                     meter_end_therms=1265.0)
        after = _get_agreement(api, agreement["id"], manager_headers)
        assert_storage_agreement(after)
        assert after["status"] == "ACTIVE"
        # round_half_up(9050 / 56, 2) = 161.61
        assert after["baseline_bushels"] == pytest.approx(161.61)
        assert after["start_date"] == "2026-09-05"

    def test_cascade_moves_lot_to_stored_and_consumes_ticket(self, api, manager_headers):
        """PRD §3.5: "With exactly one `RESERVED` agreement for the lot, a
        three-link cascade fires: the run's completion first applies the same
        weight reconciliation to the lot; the lot reaching dried-weight state
        then activates the agreement, moving it `RESERVED` → `ACTIVE` with
        `baseline_bushels` fixed from the just-completed final weight and
        `start_date` set to the completion date; and that activation moves the
        lot to `STORED`, its version advancing."
        PRD §3.5: "Starting cascades outward: the backing ticket moves
        `CONFIRMED` → `CONSUMED`, and the lot moves `QUEUED` → `DRYING`."

        Design: Difficulty/transitive_cascade/run_completion_storage_activation_cascade
        """
        ctx, lot, ticket, run, agreement = self._setup_reserved_cascade()
        completed = complete_run(run["id"], scale_out_weight_lbs=9050,
                                 discharge_moisture_pct=15.0, meter_end_therms=1265.0)
        assert completed["status"] == "COMPLETED"
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "STORED"
        assert lot_after["final_dry_weight_lbs"] == 9050
        assert get_ticket(ticket["id"])["status"] == "CONSUMED"


class TestStorageDefault:
    def test_storage_default_transfers_title_to_elevator(self, api, manager_headers):
        """PRD §3.6: "Declaring default — again only against an `ACTIVE`
        agreement, else `ERR_AGREEMENT_NOT_ACTIVE` — moves the agreement
        `ACTIVE` → `DEFAULTED` and transfers title: the lot's `ownership`
        becomes `ELEVATOR_HELD`, its `current_owner_id` is cleared to null, and
        its version increments, while the lot itself remains `STORED`."

        Design: Corner/state_machines/storage_default_transfers_title_to_elevator
        """
        ctx = setup_dried_lot_scenario(with_schedule=False, sample_moisture_pct=20.0,
                                       meter_start=1200.0, meter_end=1265.0)
        # Lot already DRIED: the agreement is born ACTIVE.
        agreement = create_storage_agreement(ctx["lot"]["id"])
        assert agreement["status"] == "ACTIVE"
        assert get_lot(ctx["lot"]["id"])["status"] == "STORED"

        defaulted = validate_success(
            api.declare_default_storage_agreement(agreement["id"], manager_headers), 200)
        assert defaulted["status"] == "DEFAULTED"
        lot = get_lot(ctx["lot"]["id"])
        assert lot["ownership"] == "ELEVATOR_HELD"
        assert lot["current_owner_id"] is None
        assert lot["status"] == "STORED"


class TestStorageAccrual:
    def test_storage_accrual_min_days_floor_and_ten_day(self, api, manager_headers):
        """PRD §3.6: "Accrual is chronological and half-open. `accrued_days`
        counts the days from `start_date` up to but not including `closed_date`
        — or up to but not including the current date while the agreement is
        still open. `accrued_storage_cents` is `baseline_bushels` multiplied by
        `daily_rate_cents_per_bu`, multiplied by the larger of `min_days` and
        `accrued_days`, rounded half up to whole cents; the figure finalizes
        when the agreement closes."
        PRD §3.6: "Closing sets `closed_date` to the current date, finalizes
        `accrued_days` and `accrued_storage_cents` with the minimum-days floor,
        moves the agreement to `CLOSED` (terminal), and releases the lot
        `STORED` → `DRIED`, its version incrementing."

        Design: Corner/calculations/storage_accrual_min_days_floor_and_ten_day
        """
        ctx = setup_base()
        dried_a = create_dried_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], sample_moisture_pct=20.0,
            run_start="2026-09-05T08:00:00Z", run_end="2026-09-05T10:00:00Z",
            meter_start=100.0, meter_end=160.0)
        dried_b = create_dried_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], sample_moisture_pct=20.0,
            run_start="2026-09-05T11:00:00Z", run_end="2026-09-05T13:00:00Z",
            meter_start=100.0, meter_end=160.0)
        # Both agreements born ACTIVE with start_date == current date 2026-09-05.
        ag_a = create_storage_agreement(dried_a["lot"]["id"])
        ag_b = create_storage_agreement(dried_b["lot"]["id"])
        assert ag_a["status"] == "ACTIVE"
        assert ag_a["baseline_bushels"] == pytest.approx(161.61)
        assert ag_a["start_date"] == "2026-09-05"

        # Close A on 2026-09-08: 3 actual days, floor bills 7.
        set_clock("2026-09-08T09:00:00Z")
        closed_a = validate_success(
            api.close_storage_agreement(ag_a["id"], manager_headers), 200)
        assert closed_a["status"] == "CLOSED"
        assert closed_a["accrued_days"] == 3
        # 161.61 bu * 0.15 c * max(7, 3) = 169.6905 -> 170
        assert closed_a["accrued_storage_cents"] == 170
        assert get_lot(dried_a["lot"]["id"])["status"] == "DRIED"

        # Close B on 2026-09-15: 10 actual days.
        set_clock("2026-09-15T09:00:00Z")
        closed_b = validate_success(
            api.close_storage_agreement(ag_b["id"], manager_headers), 200)
        assert closed_b["status"] == "CLOSED"
        assert closed_b["accrued_days"] == 10
        # 161.61 bu * 0.15 c * 10 = 242.415 -> 242
        assert closed_b["accrued_storage_cents"] == 242


class TestStorageGates:
    def test_duplicate_active_agreement_rejected(self, api, manager_headers):
        """PRD §3.6: "A lot may never carry two live agreements — creating one
        while another stands `RESERVED` or `ACTIVE` for the same lot is rejected
        with `ERR_DUPLICATE_ACTIVE_AGREEMENT` (HTTP 409)."

        Design: Corner/validations/duplicate_active_agreement_rejected
        """
        ctx = setup_dried_lot_scenario(with_schedule=False, sample_moisture_pct=20.0,
                                       meter_start=1200.0, meter_end=1265.0)
        create_storage_agreement(ctx["lot"]["id"])
        res = api.create_storage_agreement({"lot_id": ctx["lot"]["id"]}, manager_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_AGREEMENT,
                       expected_status=409)

    def test_agreement_close_when_not_active_rejected(self, api, manager_headers):
        """PRD §3.6: "Closing is a manager's action on an `ACTIVE` agreement —
        against any other state, `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)."
        PRD §3.6: "Otherwise the agreement waits in `RESERVED` until the lot's
        dryer run completes, when the §3.5 cascade activates it: the baseline is
        fixed from the completing lot's `final_dry_weight_lbs` in the same way,
        and `start_date` is the completion date."

        Design: Corner/validations/agreement_close_when_not_active_rejected
        """
        ctx = setup_base()
        lot, _t, _ticket = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-05",
            requested_bushels=200, sample_moisture_pct=20.0)
        agreement = create_storage_agreement(lot["id"])
        assert agreement["status"] == "RESERVED"  # lot not yet DRIED
        res = api.close_storage_agreement(agreement["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, expected_status=409)
