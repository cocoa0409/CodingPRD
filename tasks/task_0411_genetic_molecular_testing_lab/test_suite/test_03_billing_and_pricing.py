"""Billing and patient-responsibility pricing claims: estimate/final variants,
tiered coinsurance, caps, surcharge, collection matching, auth-amount bounds,
and the parallel pipeline/financial dimensions.

Translates queue B (Corner) section `calculations` (non-stub, non-pathogenicity),
plus queue A dual_variant_calc/patient_responsibility_estimate_vs_final_billing,
combinatorial_formula/patient_responsibility_nested_min_tiered_inputs, and
non_linear_state_machine/testorder_parallel_pipeline_and_financial_dimensions.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import ApiErrorId

DIRECTOR = TEST_USERS["director_headers"]
INTAKE = TEST_USERS["intake_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_self_pay_estimate_full_list_price_under_cap(api):
    """PRD §3.6: "If the payer is `SELF_PAY`, the billing record advances from `OPEN`
    directly to `PATIENT_PAY` ... the billing record's `allowed_amount_cents` is
    set equal to the order's `list_price_cents`. In either fork the server then
    computes the estimate variant of patient responsibility into
    `estimated_patient_responsibility_cents`."
    PRD §3.7: "`SELF_PAY` carries the full one hundred percent (1.00), meaning a
    self-pay patient owes the entire allowed/list amount."

    Design: Corner/calculations/self_pay_estimate_full_list_price_under_cap
    """
    ctx = FX.setup_ordered(list_price_cents=40000, gene_symbols=("GCALC1",), name="CALC1")
    FX.add_requisition(ctx["order"]["id"], "SELF_PAY")
    resp = api.submit_requisition(ctx["order"]["id"], INTAKE)
    validate_success(resp, 200)
    order = FX.get_order(ctx["order"]["id"])
    assert order["financial_status"] == "PATIENT_PAY"
    assert order["estimated_patient_responsibility_cents"] == 40000


def test_commercial_estimate_recomputed_on_auth_approved(api):
    """PRD §3.6: "A valid approval stores `allowed_amount_cents` on the billing
    record, advances the record from `AUTH_REQUESTED` to `AUTH_APPROVED`, sets the
    order's `financial_status` to `AUTH_APPROVED`, and recomputes
    `estimated_patient_responsibility_cents`."
    PRD §3.7: "`COMMERCIAL` carries ten percent (0.10)."

    Design: Corner/calculations/commercial_estimate_recomputed_on_auth_approved
    """
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=400000,
                                 gene_symbols=("GCALC2",), name="CALC2")
    resp = api.auth_decision(ctx["order"]["id"],
                             F.auth_decision_payload("APPROVED", 300000), BILLING)
    validate_success(resp, 200)
    order = FX.get_order(ctx["order"]["id"])
    assert order["financial_status"] == "AUTH_APPROVED"
    assert order["estimated_patient_responsibility_cents"] == 30000


def test_denied_then_convert_self_pay_writeoff_and_estimate(api):
    """PRD §3.6: "Conversion ... writes off the denied payer portion — the current
    `allowed_amount_cents` is added to `writeoff_cents` — then resets
    `allowed_amount_cents` to equal the order's `list_price_cents`, advances the
    billing record from `AUTH_DENIED` to `PATIENT_PAY`, sets the order's
    `financial_status` to `PATIENT_PAY`, and recomputes
    `estimated_patient_responsibility_cents`."

    Design: Corner/calculations/denied_then_convert_self_pay_writeoff_and_estimate
    """
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=40000,
                                 gene_symbols=("GCALC3",), name="CALC3")
    FX.auth_deny(ctx["order"]["id"])
    resp = api.convert_self_pay(ctx["order"]["id"], BILLING)
    validate_success(resp, 200)
    order = FX.get_order(ctx["order"]["id"])
    billing = validate_success(api.list_order_billing(ctx["order"]["id"], BILLING), 200)[0]
    assert order["financial_status"] == "PATIENT_PAY"
    assert billing["allowed_amount_cents"] == 40000
    assert billing["writeoff_cents"] == 0
    # PRD §3.7: the coinsurance rate is "tiered by the requisition's
    # `insurance_payer`". Conversion to self-pay (PRD §3.6) is a billing-level
    # transition that does NOT mutate the requisition's payer, which remains
    # COMMERCIAL. So the recomputed estimate uses the COMMERCIAL rate (0.10):
    # round(40000 * 0.10) = 4000, under the $500.00 cap.
    assert order["estimated_patient_responsibility_cents"] == 4000


def test_collect_exact_estimate_pre_signout_settles(api):
    """PRD §3.6: "The collect body carries an `amount_cents` that must exactly equal
    the amount currently owed: if the report has been signed out, the owed amount
    is the order's `final_patient_responsibility_cents`; otherwise it is the
    order's `estimated_patient_responsibility_cents`. ... On a matching collection,
    the `amount_cents` is added to `coinsurance_collected_cents`, the billing
    record advances from `PATIENT_PAY` to `SETTLED`, and the order's
    `financial_status` becomes `SETTLED`."

    Design: Corner/calculations/collect_exact_estimate_pre_signout_settles
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", list_price_cents=40000,
                                 gene_symbols=("GCALC4",), name="CALC4")
    resp = api.collect(ctx["order"]["id"], F.collect_payload(40000), BILLING)
    validate_success(resp, 200)
    billing = validate_success(api.list_order_billing(ctx["order"]["id"], BILLING), 200)[0]
    order = FX.get_order(ctx["order"]["id"])
    assert billing["status"] == "SETTLED"
    assert billing["coinsurance_collected_cents"] == 40000
    assert order["financial_status"] == "SETTLED"


def test_collect_wrong_amount_rejected(api):
    """PRD §3.6: "The collect body carries an `amount_cents` that must exactly equal
    the amount currently owed ... A mismatch is rejected with
    `ERR_COLLECT_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/calculations/collect_wrong_amount_returns_collect_amount_mismatch
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", list_price_cents=40000,
                                 gene_symbols=("GCALC5",), name="CALC5")
    resp = api.collect(ctx["order"]["id"], F.collect_payload(39999), BILLING)
    validate_error(resp, ApiErrorId.ERR_COLLECT_AMOUNT_MISMATCH.value, 422)
    billing = validate_success(api.list_order_billing(ctx["order"]["id"], BILLING), 200)[0]
    assert billing["status"] == "PATIENT_PAY"


def test_auth_allowed_amount_above_list_price_rejected(api):
    """PRD §3.6: "the supplied `allowed_amount_cents` must be present and must
    satisfy: greater than or equal to zero and less than or equal to the order's
    `list_price_cents`; a missing or out-of-range value is rejected with
    `ERR_ALLOWED_AMOUNT_INVALID` (HTTP 422)."

    Design: Corner/calculations/auth_approved_allowed_amount_above_list_price_rejected
    """
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=40000,
                                 gene_symbols=("GCALC6",), name="CALC6")
    resp = api.auth_decision(ctx["order"]["id"],
                             F.auth_decision_payload("APPROVED", 40001), BILLING)
    validate_error(resp, ApiErrorId.ERR_ALLOWED_AMOUNT_INVALID.value, 422)
    billing = validate_success(api.list_order_billing(ctx["order"]["id"], BILLING), 200)[0]
    assert billing["status"] == "AUTH_REQUESTED"


def test_get_test_order_exposes_both_dimensions(api):
    """PRD §3.6: "A valid approval ... sets the order's `financial_status` to
    `AUTH_APPROVED`, and recomputes `estimated_patient_responsibility_cents`."
    PRD §3.7: "`COMMERCIAL` carries ten percent (0.10)."

    Design: Corner/endpoints/get_test_order_computed_read_exposes_both_dimensions
    """
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=200000,
                                 gene_symbols=("GLIST6",), name="LIST6")
    FX.auth_approve(ctx["order"]["id"], 150000)
    order = validate_success(api.get_test_order(ctx["order"]["id"], BILLING), 200)
    assert order["pipeline_status"] == "REQUISITIONED"
    assert order["financial_status"] == "AUTH_APPROVED"
    assert order["estimated_patient_responsibility_cents"] == 15000


# --------------------------------------------------------------------------- #
# Queue A — dual variant & combinatorial pricing & parallel dimensions
# --------------------------------------------------------------------------- #
def test_patient_responsibility_estimate_vs_final_commercial(api):
    """PRD §3.7: "The **estimate variant** writes `estimated_patient_responsibility_cents`
    ... It takes the rounded gross and clamps it down to no more than a
    patient-assistance cap of $500.00 (50,000 cents): the result is the smaller of
    the gross and 50,000 cents."
    PRD §3.7: "The **final variant** writes `final_patient_responsibility_cents` ...
    then, if the signed-out report discloses an incidental finding, adds an
    incidental disclosure/counseling surcharge of $75.00 (7,500 cents) ... Finally
    it clamps that sum down to no more than the final patient-assistance cap of
    $600.00 (60,000 cents)."

    Design: Difficulty/dual_variant_calc/patient_responsibility_estimate_vs_final_billing
    """
    # COMMERCIAL list 400000, allowed 300000; one incidental PATHOGENIC ACMG variant
    # not on panel; adult opted-in; signed out by non-classifier.
    FX.set_clock("2026-06-19T00:00:00.000Z")
    on_gene = FX.create_gene("BRCA1", is_acmg_reportable=True)
    off_gene = FX.create_gene("MLH1", is_acmg_reportable=True)
    # Panel includes only on_gene; off_gene stays off-panel so its variant is incidental.
    panel = get_success_data(api.create_panel(
        F.create_panel_payload(name="Cancer Panel", list_price_cents=400000,
                               requires_consent=True), DIRECTOR))
    get_success_data(api.add_panel_gene(panel["id"], F.add_panel_gene_payload(on_gene["id"]), DIRECTOR))
    panel = get_success_data(api.publish_panel(panel["id"], DIRECTOR))
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"], patient_dob="2008-06-01", patient_mrn="MRN-A")
    FX.add_requisition(order["id"], "COMMERCIAL")
    FX.submit_requisition(order["id"])
    FX.auth_approve(order["id"], 300000)
    FX.add_signed_consent(order["id"], incidental_findings_opt_in=True)
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api.start_sequencing(order["id"], TEST_USERS["accessioning_headers"]))
    var = FX.add_variant(order["id"], off_gene["id"], hgvs="c.100C>T")
    FX.classify(order["id"], var["id"], "PATHOGENIC", user_id="tech-1")
    FX.complete_classification(order["id"])
    report = FX.create_report(order["id"])
    # estimate already computed on auth approve
    order_after_est = FX.get_order(order["id"])
    assert order_after_est["estimated_patient_responsibility_cents"] == 30000
    FX.sign_out(order["id"], report["id"], director_user_id="director-1")
    order_final = FX.get_order(order["id"])
    assert order_final["final_patient_responsibility_cents"] == 37500
    assert (order_final["final_patient_responsibility_cents"]
            != order_final["estimated_patient_responsibility_cents"])


def test_patient_responsibility_medicare_cap_and_final_surcharge(api):
    """PRD §3.7: "`MEDICARE` carries a rate of twenty percent (0.20)."
    PRD §3.7: "It takes the rounded gross and clamps it down to no more than a
    patient-assistance cap of $500.00 (50,000 cents): the result is the smaller of
    the gross and 50,000 cents."
    PRD §3.7: "The evaluation order is pinned and must be followed exactly: compute
    gross (the single rounding), then apply the $500.00 cap, then add the surcharge
    (final only), then re-clamp to the $600.00 final cap."

    Design: Difficulty/combinatorial_formula/patient_responsibility_nested_min_tiered_inputs
    """
    FX.set_clock("2026-06-19T00:00:00.000Z")
    on_gene = FX.create_gene("MSH2", is_acmg_reportable=True)
    off_gene = FX.create_gene("PMS2", is_acmg_reportable=True)
    panel = get_success_data(api.create_panel(
        F.create_panel_payload(name="Med Panel", list_price_cents=400000,
                               requires_consent=False), DIRECTOR))
    get_success_data(api.add_panel_gene(panel["id"], F.add_panel_gene_payload(on_gene["id"]), DIRECTOR))
    panel = get_success_data(api.publish_panel(panel["id"], DIRECTOR))
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"], patient_dob="1980-01-01", patient_mrn="MRN-D")
    FX.add_requisition(order["id"], "MEDICARE")
    FX.submit_requisition(order["id"])
    FX.auth_approve(order["id"], 300000)
    FX.add_signed_consent(order["id"], incidental_findings_opt_in=True)
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api.start_sequencing(order["id"], TEST_USERS["accessioning_headers"]))
    var = FX.add_variant(order["id"], off_gene["id"], hgvs="c.300A>T")
    FX.classify(order["id"], var["id"], "PATHOGENIC", user_id="tech-1")
    FX.complete_classification(order["id"])
    report = FX.create_report(order["id"])
    order_est = FX.get_order(order["id"])
    assert order_est["estimated_patient_responsibility_cents"] == 50000
    FX.sign_out(order["id"], report["id"], director_user_id="director-1")
    order_final = FX.get_order(order["id"])
    assert order_final["final_patient_responsibility_cents"] == 57500


def test_patient_responsibility_estimate_equals_final_when_no_incidental(api):
    """PRD §3.7: "if the signed-out report discloses an incidental finding, adds an
    incidental disclosure/counseling surcharge of $75.00 (7,500 cents); if no
    incidental is disclosed, it adds nothing."
    PRD §3.7: "Because the surcharge can apply, the same order can carry a
    structurally different final figure than its estimate even though both start
    from the same base and rate."

    Design: Difficulty/dual_variant_calc/patient_responsibility_estimate_vs_final_billing
    """
    # COMMERCIAL allowed 300000, one on-panel BENIGN variant -> no incidental disclosed,
    # so final == estimate == 30000 (no surcharge).
    FX.set_clock("2026-06-19T00:00:00.000Z")
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=400000,
                                 gene_symbols=("GNOIN",), name="NoInc Panel",
                                 patient_dob="1980-01-01")
    FX.auth_approve(ctx["order"]["id"], 300000)
    spec = FX.add_specimen(ctx["order"]["id"])
    FX.accession(ctx["order"]["id"], spec["id"])
    get_success_data(api.start_sequencing(ctx["order"]["id"], TEST_USERS["accessioning_headers"]))
    var = FX.add_variant(ctx["order"]["id"], ctx["genes"][0]["id"], hgvs="c.10A>T")
    FX.classify(ctx["order"]["id"], var["id"], "BENIGN", user_id="tech-1")
    FX.complete_classification(ctx["order"]["id"])
    report = FX.create_report(ctx["order"]["id"])
    FX.sign_out(ctx["order"]["id"], report["id"], director_user_id="director-1")
    order_final = FX.get_order(ctx["order"]["id"])
    assert order_final["estimated_patient_responsibility_cents"] == 30000
    assert order_final["final_patient_responsibility_cents"] == 30000


def test_patient_responsibility_medicare_cap_no_surcharge_when_no_incidental(api):
    """PRD §3.7: "It takes the rounded gross and clamps it down to no more than a
    patient-assistance cap of $500.00 (50,000 cents): the result is the smaller of
    the gross and 50,000 cents."
    PRD §3.7: "if no incidental is disclosed, it adds nothing. Finally it clamps
    that sum down to no more than the final patient-assistance cap of $600.00
    (60,000 cents)."

    Design: Difficulty/combinatorial_formula/patient_responsibility_nested_min_tiered_inputs
    """
    # MEDICARE allowed 300000 -> gross 60000 capped to 50000; on-panel BENIGN (no incidental)
    # -> final = min(50000 + 0, 60000) = 50000.
    FX.set_clock("2026-06-19T00:00:00.000Z")
    ctx = FX.setup_requisitioned(insurance_payer="MEDICARE", list_price_cents=400000,
                                 gene_symbols=("GMEDN",), name="MedNoInc",
                                 patient_dob="1980-01-01")
    FX.auth_approve(ctx["order"]["id"], 300000)
    spec = FX.add_specimen(ctx["order"]["id"])
    FX.accession(ctx["order"]["id"], spec["id"])
    get_success_data(api.start_sequencing(ctx["order"]["id"], TEST_USERS["accessioning_headers"]))
    var = FX.add_variant(ctx["order"]["id"], ctx["genes"][0]["id"], hgvs="c.11A>T")
    FX.classify(ctx["order"]["id"], var["id"], "BENIGN", user_id="tech-1")
    FX.complete_classification(ctx["order"]["id"])
    report = FX.create_report(ctx["order"]["id"])
    order_est = FX.get_order(ctx["order"]["id"])
    assert order_est["estimated_patient_responsibility_cents"] == 50000
    FX.sign_out(ctx["order"]["id"], report["id"], director_user_id="director-1")
    order_final = FX.get_order(ctx["order"]["id"])
    assert order_final["final_patient_responsibility_cents"] == 50000


def test_parallel_pipeline_and_financial_dimensions(api):
    """PRD §3.6: "The billing dimension runs parallel to the clinical pipeline ...
    A valid approval ... sets the order's `financial_status` to `AUTH_APPROVED`."
    PRD §3.2: "Submission moves the requisition from `PENDING` to `SUBMITTED` and
    advances the order from `ORDERED` to `REQUISITIONED`."

    Design: Difficulty/non_linear_state_machine/testorder_parallel_pipeline_and_financial_dimensions
    """
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=200000,
                                 gene_symbols=("GY",), name="PY")
    resp = api.auth_decision(ctx["order"]["id"],
                             F.auth_decision_payload("APPROVED", 150000), BILLING)
    validate_success(resp, 200)
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "REQUISITIONED"
    assert order["financial_status"] == "AUTH_APPROVED"


def test_parallel_dimensions_pipeline_advances_while_auth_requested(api):
    """PRD §3.4: "the server stamps `received_at` with the current lab clock value,
    moves the specimen from `RECEIVED` to `ACCESSIONED`, and advances the order's
    `pipeline_status` from `REQUISITIONED` to `ACCESSIONED`."
    PRD §3.6: "If the payer is not `SELF_PAY` ... a prior-authorization request
    opens: the billing record advances from `OPEN` to `AUTH_REQUESTED` and the
    order's `financial_status` becomes `AUTH_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/testorder_parallel_pipeline_and_financial_dimensions
    """
    # COMMERCIAL order: financial stays AUTH_REQUESTED (no auth decision) while the
    # clinical pipeline independently advances to ACCESSIONED.
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=200000,
                                 gene_symbols=("GY2",), name="PY2")
    spec = FX.add_specimen(ctx["order"]["id"])
    FX.accession(ctx["order"]["id"], spec["id"])
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "ACCESSIONED"
    assert order["financial_status"] == "AUTH_REQUESTED"
