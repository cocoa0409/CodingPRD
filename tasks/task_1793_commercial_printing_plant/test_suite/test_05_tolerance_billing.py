"""Overrun/underrun tolerance billing: nested min/max branches and the
inclusive cap boundary."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_invoice_monetary_conservation,
    complete_bindery_and_deliver,
    complete_press_run,
    create_customer,
    create_fulfilled_ship_job,
    create_plated_job,
    create_press,
    create_received_stock,
    get_success_data,
    refresh_press,
    schedule_press_run,
    standard_signatures,
)

_PM = TEST_USERS["plant_manager_headers"]


def _create_invoice(job_id):
    resp = api_client.create_invoice({"job_id": job_id}, _PM)
    inv = get_success_data(resp)
    assert inv.get("id"), f"Setup failed: create invoice -> {resp.text}"
    return inv


def _standard_job_delivered(delivered):
    """Standard Q=10002 two-signature SHIP job (provisional total 773267),
    fulfilled with the given delivered quantity."""
    cust = create_customer(name="Bill Cust")
    stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
    _est, job, _press = create_fulfilled_ship_job(
        cust["id"], standard_signatures(stock["id"]),
        quantity_ordered=10002, delivered_quantity=delivered,
        press_spoilage_pct=3, bindery_spoilage_pct=2,
        finishing_options=["PERF", "SCORE"], included_proof_rounds=2,
    )
    return cust, job, _create_invoice(job["id"])


def _bindery_via_press(cust, stock, press, name, delivered):
    """Standard Q=10002 job driven to FULFILLED via a shared press."""
    est, job, _proof = create_plated_job(
        cust["id"], standard_signatures(stock["id"]),
        quantity_ordered=10002, press_spoilage_pct=3, bindery_spoilage_pct=2,
        finishing_options=["PERF", "SCORE"], included_proof_rounds=2,
        job_name=name,
    )
    fresh_press = refresh_press(press["id"])
    run = schedule_press_run(fresh_press, job_id=job["id"], run_quantity=10002)
    complete_press_run(run["id"], gross_impressions=10002, sheets_used=10600, waste_sheets=300)
    job = complete_bindery_and_deliver(job["id"], delivered_quantity=delivered,
                                       pieces_completed=delivered)
    return job


class TestUnderrunShortageBranch:
    def test_underrun_bills_delivered_minus_shortage_credit(self, api):
        """PRD §3.12: "When delivery falls below the lower bound,
        `billable_quantity` is `D`, and a shortage credit is computed as the
        job's total basis multiplied by the number of missing-to-band pieces
        (that is, `Q` minus the allowed deviation minus `D`) and divided by
        `Q`, rounded half-up to a whole cent."
        Q=10002, t=5 -> allowed 500, band [9502, 10502]; D=9400 bills 9400
        with shortage credit rhu(773267 x 102/10002) = 7886.

        Design: Difficulty/combinatorial_formula/overrun_underrun_nested_minmax
        """
        _cust, _job, inv = _standard_job_delivered(9400)
        assert inv["billable_quantity"] == 9400
        assert inv["base_amount_cents"] == 726726
        assert inv["shortage_credit_cents"] == 7886

    def test_underrun_total_due_is_base_minus_shortage(self, api):
        """PRD §3.12: "The invoice's `total_due_cents` is `base_amount_cents`
        plus `postage_cents` plus `proof_overage_cents` minus
        `shortage_credit_cents`." 726726 - 7886 = 718840.

        Design: Difficulty/combinatorial_formula/overrun_underrun_nested_minmax
        """
        _cust, _job, inv = _standard_job_delivered(9400)
        assert inv["total_due_cents"] == 718840
        assert_invoice_monetary_conservation(inv)


class TestOverrunCapInclusiveBoundary:
    def _two_jobs(self):
        cust = create_customer(name="Bnd Cust")
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
        press = create_press(name="W1")
        job_a = _bindery_via_press(cust, stock, press, "JA", 10502)
        job_b = _bindery_via_press(cust, stock, press, "JB", 10503)
        return job_a, job_b

    def test_delivered_exactly_at_cap_bills_in_full(self, api):
        """PRD §3.12: "The tolerance band runs from `Q` minus the allowed
        deviation to `Q` plus the allowed deviation, both bounds inclusive...
        When delivery is inside the inclusive band, `billable_quantity` is
        `D`." Q=10002, allowed 500 -> cap 10502; delivered exactly 10502 bills
        10502 in full (base 811923).

        Design: Difficulty/boundary_precision_check/overrun_cap_inclusive_boundary
        """
        job_a, _job_b = self._two_jobs()
        inv = _create_invoice(job_a["id"])
        assert inv["delivered_quantity"] == 10502
        assert inv["billable_quantity"] == 10502
        assert inv["base_amount_cents"] == 811923
        assert inv["shortage_credit_cents"] == 0

    def test_one_piece_beyond_cap_clamps_billable(self, api):
        """PRD §3.12: "When delivery exceeds the upper bound,
        `billable_quantity` is capped at `Q` plus the allowed deviation —
        pieces above the cap are free." Delivered 10503 clamps billable to
        10502; the excess piece is free.

        Design: Difficulty/boundary_precision_check/overrun_cap_inclusive_boundary
        """
        _job_a, job_b = self._two_jobs()
        inv = _create_invoice(job_b["id"])
        assert inv["delivered_quantity"] == 10503
        assert inv["billable_quantity"] == 10502, (
            "10503 must clamp to the inclusive cap 10502"
        )
        assert inv["base_amount_cents"] == 811923


class TestWithinTolerance:
    def test_within_tolerance_delivery_bills_actual(self, api):
        """PRD §3.12: "When delivery is inside the inclusive band,
        `billable_quantity` is `D` and `shortage_credit_cents` is 0."
        D=10000 sits strictly inside [9502, 10502]; base =
        rhu(773267 x 10000/10002) = 773112.

        Design: Corner/calculations/within_tolerance_delivery_bills_actual
        """
        _cust, _job, inv = _standard_job_delivered(10000)
        assert inv["billable_quantity"] == 10000
        assert inv["shortage_credit_cents"] == 0
        assert inv["base_amount_cents"] == 773112
        assert inv["total_due_cents"] == 773112
