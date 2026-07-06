"""Estimation pricing, the repair-vs-replace recommendation, the approval cycle,
the spend cap, and estimate-creation optimistic concurrency.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, TEST_USERS, make_customer_headers, make_technician_headers,
    setup_diagnosed_ticket, setup_estimate_sent, setup_ticket_in_repair,
    post_estimate, add_part_order, create_part,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / estimate_provisional_vs_final_invoice
# ---------------------------------------------------------------------------
def test_estimate_provisional_total_at_creation(api):
    """PRD §3.3: "The `provisional_total_cents` is the sum of `labor_cost_cents`,
    `parts_cost_cents`, and `diagnostic_fee_cents`."
    PRD §3.3: "5000 cents per hour for a `STANDARD` technician and 8000 cents per
    hour for a `MASTER` technician".

    Design: Difficulty/dual_variant_calc/estimate_provisional_vs_final_invoice
    """
    scn = setup_estimate_sent(market_value_cents=40000, certification_level="STANDARD",
                              is_under_warranty=False, spend_cap_cents=100000,
                              labor_hours=2, part_specs=[(6000, 10, 1)])
    est = validate_success(api.get_estimate(scn["ticket"]["id"], scn["estimate"]["id"], SM))
    assert est["provisional_total_cents"] == 20000


def test_final_invoice_diverges_from_provisional_after_completion(api):
    """PRD §3.5: "its `final_total_cents` is recomputed using the same formula as the
    provisional total but with two substitutions: labor is priced from
    `actual_labor_hours` rather than the estimated hours, and the parts component sums
    only the `line_cost_cents` of the ticket's part orders that are `INSTALLED`."
    PRD §3.5: "The ticket's `final_invoice_cents` is set to the estimate's `final_total_cents`."

    Design: Difficulty/dual_variant_calc/estimate_provisional_vs_final_invoice
    """
    scn = setup_ticket_in_repair(market_value_cents=40000, certification_level="STANDARD",
                                 is_under_warranty=False, spend_cap_cents=100000,
                                 labor_hours=2, part_specs=[(6000, 10, 1)])
    completed = validate_success(api.complete_ticket(
        scn["ticket"]["id"], {"actual_labor_hours": 3},
        make_technician_headers(scn["technician"]["id"])))
    est = validate_success(api.get_estimate(scn["ticket"]["id"], scn["estimate"]["id"], SM))
    assert est["provisional_total_cents"] == 20000
    assert est["final_total_cents"] == 25000
    assert est["provisional_total_cents"] != est["final_total_cents"]
    assert completed["final_invoice_cents"] == 25000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / estimate_total_tiered_labor_and_conditional_diagnostic
# ---------------------------------------------------------------------------
def test_estimate_components_master_rate_warranty_waiver(api):
    """PRD §3.3: "5000 cents per hour for a `STANDARD` technician and 8000 cents per
    hour for a `MASTER` technician — with that product rounded half-up to whole cents."
    PRD §3.3: "The `diagnostic_fee_cents` is 4000 cents, except that it is 0 when the
    ticket's `is_under_warranty` is true."

    Design: Difficulty/combinatorial_formula/estimate_total_tiered_labor_and_conditional_diagnostic
    """
    scn = setup_estimate_sent(market_value_cents=200000, certification_level="MASTER",
                              is_under_warranty=True, spend_cap_cents=100000,
                              labor_hours=2, part_specs=[(6000, 10, 2), (3000, 10, 1)])
    est = validate_success(api.get_estimate(scn["ticket"]["id"], scn["estimate"]["id"], SM))
    assert est["labor_cost_cents"] == 16000
    assert est["diagnostic_fee_cents"] == 0


def test_estimate_parts_sum_and_provisional_total_combination(api):
    """PRD §3.3: "The parts component `parts_cost_cents` is the sum of the
    `line_cost_cents` of the ticket's active part orders, meaning those in
    `REQUESTED`, `RESERVED`, or `BACKORDERED` status at the time the estimate is created."
    PRD §3.3: "The `provisional_total_cents` is the sum of `labor_cost_cents`,
    `parts_cost_cents`, and `diagnostic_fee_cents`."

    Design: Difficulty/combinatorial_formula/estimate_total_tiered_labor_and_conditional_diagnostic
    """
    scn = setup_estimate_sent(market_value_cents=200000, certification_level="MASTER",
                              is_under_warranty=True, spend_cap_cents=100000,
                              labor_hours=2, part_specs=[(6000, 10, 2), (3000, 10, 1)])
    est = validate_success(api.get_estimate(scn["ticket"]["id"], scn["estimate"]["id"], SM))
    assert est["parts_cost_cents"] == 15000
    assert est["provisional_total_cents"] == 31000


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / repair_vs_replace_threshold_inclusive
# ---------------------------------------------------------------------------
def test_repair_vs_replace_threshold_inclusive_recommends_replace(api):
    """PRD §3.3: "The system first computes 60 percent of the linked device's
    `market_value_cents`, rounded half-up to whole cents, as a replace threshold.
    If `provisional_total_cents` is greater than or equal to that threshold, the
    `recommendation` is `REPLACE`; otherwise it is `REPAIR`."
    PRD §3.3: "The boundary is inclusive: a provisional total exactly equal to the
    threshold recommends `REPLACE`."

    Design: Difficulty/boundary_precision_check/repair_vs_replace_threshold_inclusive
    """
    # market_value 23333 -> threshold round(0.60*23333)=14000; total = 10000 labor + 4000 diag.
    scn = setup_estimate_sent(market_value_cents=23333, certification_level="STANDARD",
                              is_under_warranty=False, spend_cap_cents=100000,
                              labor_hours=2, part_specs=None)
    est = validate_success(api.get_estimate(scn["ticket"]["id"], scn["estimate"]["id"], SM))
    assert est["provisional_total_cents"] == 14000
    assert est["recommendation"] == "REPLACE"


def test_repair_vs_replace_just_below_threshold_recommends_repair(api):
    """PRD §3.3: "If `provisional_total_cents` is greater than or equal to that
    threshold, the `recommendation` is `REPLACE`; otherwise it is `REPAIR`."

    Design: Difficulty/boundary_precision_check/repair_vs_replace_threshold_inclusive
    """
    # market_value 23335 -> threshold round(0.60*23335)=14001; total 14000 < threshold -> REPAIR.
    scn = setup_estimate_sent(market_value_cents=23335, certification_level="STANDARD",
                              is_under_warranty=False, spend_cap_cents=100000,
                              labor_hours=2, part_specs=None)
    est = validate_success(api.get_estimate(scn["ticket"]["id"], scn["estimate"]["id"], SM))
    assert est["provisional_total_cents"] == 14000
    assert est["recommendation"] == "REPAIR"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / repair_ticket_estimate_reject_revision_cycle
# ---------------------------------------------------------------------------
def test_reject_estimate_returns_ticket_to_diagnosing(api):
    """PRD §3.3: "Rejection instead moves the estimate `SENT → REJECTED` and sends the
    ticket back `AWAITING_APPROVAL → DIAGNOSING`, opening the revision cycle so the
    technician can post a fresh estimate — which will supersede the rejected one."

    Design: Difficulty/non_linear_state_machine/repair_ticket_estimate_reject_revision_cycle
    """
    scn = setup_estimate_sent(market_value_cents=40000, spend_cap_cents=100000, labor_hours=2)
    tkt_id, est1_id, cust_id = scn["ticket"]["id"], scn["estimate"]["id"], scn["customer"]["id"]
    rejected = validate_success(api.reject_estimate(tkt_id, est1_id, make_customer_headers(cust_id)))
    assert rejected["status"] == "REJECTED"
    tkt = validate_success(api.get_repair_ticket(tkt_id, SM))
    assert tkt["status"] == "DIAGNOSING"


def test_new_estimate_after_reject_supersedes_and_increments_revision(api):
    """PRD §3.3: "Each new estimate on a ticket takes the next `revision_number`, a
    1-based counter that increments per estimate so that the newest revision is the
    live one, and it is created in status `SENT`. Creating it also supersedes history:
    any prior estimate on the ticket still in `SENT` or `REJECTED` transitions to `SUPERSEDED`."

    Design: Difficulty/non_linear_state_machine/repair_ticket_estimate_reject_revision_cycle
    """
    scn = setup_estimate_sent(market_value_cents=40000, spend_cap_cents=100000, labor_hours=2)
    tkt_id, est1_id, cust_id = scn["ticket"]["id"], scn["estimate"]["id"], scn["customer"]["id"]
    api.reject_estimate(tkt_id, est1_id, make_customer_headers(cust_id))
    tkt = validate_success(api.get_repair_ticket(tkt_id, SM))
    est2 = post_estimate(tkt_id, scn["technician"]["id"], 3, tkt["version"])
    assert est2["revision_number"] == 2
    est1 = validate_success(api.get_estimate(tkt_id, est1_id, SM))
    assert est1["status"] == "SUPERSEDED"
    tkt2 = validate_success(api.get_repair_ticket(tkt_id, SM))
    assert tkt2["status"] == "AWAITING_APPROVAL"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / estimate_approve_state_beats_fiscal
# ---------------------------------------------------------------------------
def test_approve_rejected_estimate_state_error_beats_fiscal(api):
    """PRD §3.3: "Approval and rejection are both permitted only while the target
    estimate is in `SENT` status — otherwise the action is rejected with
    `ERR_ESTIMATE_NOT_SENT` — and only while the parent ticket is in
    `AWAITING_APPROVAL`, otherwise `ERR_TICKET_INVALID_STATE`."
    PRD §2.11: "Only after these five layers pass does the server evaluate the
    operation-specific business rules".

    (Both priority-5 state checks fail here — estimate REJECTED and ticket DIAGNOSING;
    PRD does not commit to which fires first, so either state error is accepted, but
    the fiscal ERR_SPEND_CAP_EXCEEDED must NOT win over the state layer.)

    Design: Difficulty/priority_pair_validation_conflict/estimate_approve_state_beats_fiscal
    """
    scn = setup_estimate_sent(market_value_cents=40000, spend_cap_cents=5000, labor_hours=2)
    tkt_id, est_id, cust_id = scn["ticket"]["id"], scn["estimate"]["id"], scn["customer"]["id"]
    api.reject_estimate(tkt_id, est_id, make_customer_headers(cust_id))
    resp = api.approve_estimate(tkt_id, est_id, make_customer_headers(cust_id))
    actual = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ESTIMATE_NOT_SENT.value, ApiErrorId.ERR_TICKET_INVALID_STATE.value])
    assert actual != ApiErrorId.ERR_SPEND_CAP_EXCEEDED.value
    assert resp.status_code == 409


def test_approve_rejected_estimate_not_charged_spend_cap(api):
    """PRD §2.11: "Fifth, the target resource's state is checked against the requested
    transition, yielding the relevant invalid-state error. Only after these five layers
    pass does the server evaluate the operation-specific business rules".

    Design: Difficulty/priority_pair_validation_conflict/estimate_approve_state_beats_fiscal
    """
    scn = setup_estimate_sent(market_value_cents=40000, spend_cap_cents=5000, labor_hours=2)
    tkt_id, est_id, cust_id = scn["ticket"]["id"], scn["estimate"]["id"], scn["customer"]["id"]
    api.reject_estimate(tkt_id, est_id, make_customer_headers(cust_id))
    resp = api.approve_estimate(tkt_id, est_id, make_customer_headers(cust_id))
    # Fiscal (402) must not be the returned outcome; a state error (409) is.
    assert resp.status_code != 402


# ---------------------------------------------------------------------------
# Corner: validations / approve_estimate_exceeds_spend_cap_returns_402
# ---------------------------------------------------------------------------
def test_approve_estimate_exceeds_spend_cap_returns_402(api):
    """PRD §3.3: "On approval, the system enforces the spend cap: the estimate's
    `provisional_total_cents` must not exceed the ticket's `spend_cap_cents`, or the
    approval is refused with `ERR_SPEND_CAP_EXCEEDED` and HTTP 402."

    Design: Corner/validations/approve_estimate_exceeds_spend_cap_returns_402
    """
    scn = setup_estimate_sent(market_value_cents=40000, spend_cap_cents=5000, labor_hours=2)
    tkt_id, est_id, cust_id = scn["ticket"]["id"], scn["estimate"]["id"], scn["customer"]["id"]
    resp = api.approve_estimate(tkt_id, est_id, make_customer_headers(cust_id))
    validate_error(resp, ApiErrorId.ERR_SPEND_CAP_EXCEEDED.value, 402)
    tkt = validate_success(api.get_repair_ticket(tkt_id, SM))
    assert tkt["status"] == "AWAITING_APPROVAL"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / estimate_create_stale_ticket_version_returns_412
# ---------------------------------------------------------------------------
def test_estimate_create_stale_ticket_version_returns_412(api):
    """PRD §2.7: "If `expected_repair_ticket_version` does not equal the ticket's
    current `version` — because another writer has already posted an estimate and
    advanced the version since the client last read the ticket — the creation is
    rejected with `ERR_STALE_TICKET_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/estimate_create_stale_ticket_version_returns_412
    """
    scn = setup_diagnosed_ticket(market_value_cents=40000, spend_cap_cents=100000)
    tkt_id, tech_id, cust_id = scn["ticket"]["id"], scn["technician"]["id"], scn["customer"]["id"]
    v0 = scn["ticket"]["version"]
    est1 = post_estimate(tkt_id, tech_id, 2, v0)              # bumps version
    api.reject_estimate(tkt_id, est1["id"], make_customer_headers(cust_id))  # bumps version again
    resp = api.create_estimate(
        tkt_id, {"labor_hours": 3, "expected_repair_ticket_version": v0},
        make_technician_headers(tech_id))
    validate_error(resp, ApiErrorId.ERR_STALE_TICKET_VERSION.value, 412)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / estimate_create_fresh_version_succeeds_and_bumps
# ---------------------------------------------------------------------------
def test_estimate_create_fresh_version_succeeds_and_bumps(api):
    """PRD §3.3: "From `DIAGNOSING`, a `Technician` posts an estimate, which drives the
    ticket to `AWAITING_APPROVAL`."
    PRD §3.3: "Finally the ticket's `version` is incremented by one as part of this
    operation, which is exactly why a second, stale creation attempt is caught by the
    concurrency check."

    Design: Corner/cross_cutting_complexity_layers/estimate_create_fresh_version_succeeds_and_bumps
    """
    scn = setup_diagnosed_ticket(market_value_cents=40000, spend_cap_cents=100000)
    tkt_id, tech_id = scn["ticket"]["id"], scn["technician"]["id"]
    v0 = scn["ticket"]["version"]
    est = post_estimate(tkt_id, tech_id, 2, v0)
    assert est["status"] == "SENT"
    tkt = validate_success(api.get_repair_ticket(tkt_id, SM))
    assert tkt["status"] == "AWAITING_APPROVAL"
    assert tkt["version"] == v0 + 1
