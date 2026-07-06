"""Job completion: per-line disposal-fee invoice rounding, the open-repairs guard,
terminal lockdown, and warranty void on the cancel fan-out."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, validate_success, validate_error,
)
from test_helpers import fixtures as fx

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------- cf invoice per-line rounding
def test_invoice_total_rounds_disposal_fee_per_line():
    """PRD §3.6: "For each line, a disposal fee is computed as 4.5% of that line
    (the line multiplied by 0.045) and rounded half up to whole cents; the running
    total then increases by the line amount plus its rounded fee."
    PRD §3.6: "Because each disposal fee is rounded per line before summing,
    computing the fee once on the summed lines is not equivalent and must not be
    used."

    Design: Difficulty/combinatorial_formula/cf_invoice_disposal_fee_rounding_order_mode_b
    """
    setup = fx.setup_completed_invoice_job(
        inspection_level=1, trip_zone="A", measured_creosote_class=1,
        repair_finals=[(1050, 1050), (1050, 1050)], repair_authorization_cents=100000,
    )
    # Lines [15000, 1050, 1050]; fees [675, 47, 47]; total 15675 + 1097 + 1097 = 17869.
    assert setup["job"]["invoice_total_cents"] == 17869


def test_invoice_total_single_sweep_line():
    """PRD §3.6: "The invoice is built from line items: the first line is the job's
    `sweep_final_cost_cents`, followed by the `final_cost_cents` of every repair
    order on the job in `COMPLETED` status (orders that are cancelled, rejected, or
    still open are excluded)."
    PRD §3.6: "For each line, a disposal fee is computed as 4.5% of that line (the
    line multiplied by 0.045) and rounded half up to whole cents; the running total
    then increases by the line amount plus its rounded fee."

    Design: Difficulty/combinatorial_formula/cf_invoice_disposal_fee_rounding_order_mode_b
    """
    setup = fx.setup_completed_invoice_job(
        inspection_level=1, trip_zone="A", measured_creosote_class=1,
        repair_finals=[], repair_authorization_cents=100000,
    )
    # Single line [15000]; fee round_half_up(675.0) = 675; total 15675.
    assert setup["job"]["invoice_total_cents"] == 15675


# ---------------------------------------------------------------- corner: open-repairs guard
def test_complete_blocked_by_open_repair():
    """PRD §3.6: "Completion is also blocked while any repair order on the job
    remains non-terminal, that is in `PROPOSED`, `APPROVED`, `IN_PROGRESS`, or
    `BLOCKED`; such an attempt is `ERR_JOB_HAS_OPEN_REPAIRS`."

    Design: Corner/validations/error_job_complete_with_open_repairs
    """
    setup = fx.setup_in_progress_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    fx.make_job_safe(job_id, tech)
    fx.propose_repair(job_id, technician=tech, repair_type="CAP", part_sku="CAP-STD", quoted_cost_cents=9000)
    resp = api_client.complete_service_job(job_id, BILLING)
    validate_error(resp, ApiErrorId.ERR_JOB_HAS_OPEN_REPAIRS)


# ---------------------------------------------------------------- corner: terminal lockdown
def test_cancel_already_cancelled_job_rejected():
    """PRD §3.9: "A `Dispatcher` cancels a `ServiceJob` that has not already
    terminated; cancelling a job that is already `COMPLETED` or `CANCELLED` is
    rejected with `ERR_JOB_TERMINAL`."

    Design: Corner/state_machines/terminal_lockdown_cancel_already_cancelled_job
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    api_client.cancel_service_job(job["id"], DISPATCHER)
    resp = api_client.cancel_service_job(job["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_JOB_TERMINAL)


# ---------------------------------------------------------------- corner: warranty void fan-out
def test_job_cancel_voids_issued_warranty():
    """PRD §3.9: "Finally, every warranty for the job that is currently `ISSUED` is
    voided (`ISSUED → VOIDED`); a warranty already `CLAIMED` may likewise be voided
    by the same cascade when the parent job is cancelled."

    Design: Corner/state_machines/warranty_voided_on_job_cancel_fanout
    """
    setup = fx.setup_safe_draft_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    ro = fx.add_completed_repair(job_id, tech, repair_type="CAP", part_sku="CAP-STD",
                                 quoted_cost_cents=12000, final_cost_cents=12000, labor_cents=8000)
    warranty = fx.issue_warranty(job_id, ro["id"], coverage_type="LABOR_ONLY", term_months=12)
    resp = api_client.cancel_service_job(job_id, DISPATCHER)
    validate_success(resp, 200)
    assert fx.get_warranty(warranty["id"])["status"] == "VOIDED"
    assert fx.get_job(job_id)["job_status"] == "CANCELLED"
