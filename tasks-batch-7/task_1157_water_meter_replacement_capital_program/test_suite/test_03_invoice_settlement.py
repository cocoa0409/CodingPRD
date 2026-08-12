"""Invoice settlement formula: conditional branches and pinned min/max
(PRD 3.9)."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, create_invoice, fc, get_success_data,
    record_for_cause_fail, setup_program_wave_contractor,
    setup_work_order_qa_review, submit_rework, validate_success,
)

SCHED = TEST_USERS["scheduler_headers"]
PM = TEST_USERS["program_manager_headers"]


def test_settlement_components_branches_and_min(api):
    """PRD §3.9: "The `units_completed` is the count of the contractor's work
    orders in `CLOSED` whose `closed_at` falls on or after `period_start` and
    strictly before `period_end`; a period yielding zero units is refused with
    `ERR_INVOICE_PERIOD_EMPTY`. The `gross_amount_cents` is `units_completed`
    times the contractor's `unit_price_cents`. The `bonus_cents` is two
    percent of the gross, rounded half up to whole cents, when the
    contractor's `quality_score_bp` at submit is at least 9,800 basis points,
    and zero otherwise. The penalty counts the contractor's `FAIL` audits
    whose `recorded_at` falls in the same half-open period: `penalty_cents` is
    the smaller of that failure count times one percent of the gross (rounded
    half up to whole cents) and ten percent of the gross (rounded half up to
    whole cents). The `retainage_cents` is ten percent of the gross, rounded
    half up to whole cents, when the contractor is `SUSPENDED` at submit, and
    five percent of the gross otherwise. The `net_amount_cents` is then the
    gross plus the bonus minus the penalty minus the retainage."

    Design: Difficulty/combinatorial_formula/invoice_settlement_conditional_minmax
    """
    prog, wave, contr = setup_program_wave_contractor()
    # Two work orders in the same wave, each: one FAIL audit, rework, close.
    for i in range(2):
        ctx = setup_work_order_qa_review(contr["id"], program=prog, wave=wave)
        record_for_cause_fail(ctx["work_order"]["id"], contr["id"],
                              checks_total=10, checks_passed=8 + i,
                              defects_found=i + 1)
        submit_rework(ctx["work_order"]["id"], contr["id"])
        get_success_data(api_client.close_work_order(ctx["work_order"]["id"], SCHED))
    # 2 FAILs -> score 9200: still ACTIVE (9200 not < 9200), below bonus floor
    c = get_success_data(api_client.get_contractor(contr["id"], PM))
    assert c["quality_score_bp"] == 9200
    assert c["status"] == "ACTIVE"
    inv = create_invoice(contr["id"])
    resp = api.submit_invoice(inv["id"], fc(contr["id"]))
    data = validate_success(resp)
    assert data["status"] == "SUBMITTED"
    assert data["units_completed"] == 2
    assert data["gross_amount_cents"] == 37000
    assert data["bonus_cents"] == 0          # 9200 < 9800
    assert data["penalty_cents"] == 740      # min(2 x 370, 3700)
    assert data["retainage_cents"] == 1850   # ACTIVE -> 5%
    assert data["net_amount_cents"] == 34410


def test_settlement_exact_freeze_and_recompute_on_resubmit(api):
    """PRD §3.9: "Submitting — from `DRAFT`, or again from `DISPUTED` after a
    program-manager dispute — re-runs the full settlement against the submit
    instant and freezes every figure."

    Design: Difficulty/combinatorial_formula/invoice_settlement_conditional_minmax
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_qa_review(contr["id"])
    record_for_cause_fail(ctx["work_order"]["id"], contr["id"])  # score 9600
    submit_rework(ctx["work_order"]["id"], contr["id"])
    get_success_data(api_client.close_work_order(ctx["work_order"]["id"], SCHED))
    inv = create_invoice(contr["id"])
    first = validate_success(api.submit_invoice(inv["id"], fc(contr["id"])))
    # gross 18500; bonus 0 (9600 < 9800); penalty min(1 x 185, 1850) = 185;
    # retainage 5% = 925; net 18500 - 185 - 925 = 17390
    assert first["gross_amount_cents"] == 18500
    assert first["bonus_cents"] == 0
    assert first["penalty_cents"] == 185
    assert first["retainage_cents"] == 925
    assert first["net_amount_cents"] == 17390
    # Dispute then resubmit: settlement re-runs, same inputs -> same figures.
    get_success_data(api.dispute_invoice(inv["id"], {"reason": "recheck"}, PM))
    second = validate_success(api.submit_invoice(inv["id"], fc(contr["id"])))
    assert second["status"] == "SUBMITTED"
    for key in ("units_completed", "gross_amount_cents", "bonus_cents",
                "penalty_cents", "retainage_cents", "net_amount_cents"):
        assert second[key] == first[key], f"{key} drifted across resubmit"
