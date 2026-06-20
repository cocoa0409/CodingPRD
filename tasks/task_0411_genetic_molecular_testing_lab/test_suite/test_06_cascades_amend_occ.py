"""Cascades, report amendment, optimistic concurrency, conserved-quantity
invariants, derived-field reconciliation, and immediate consistency.

Translates queue A transitive_cascade/{amend_cascade_report_to_variant_archive_depth3,
cancel_cascade_order_billing_writeoff_depth2}, compensating_invariant/{...}, plus
queue B cross_cutting/{occ_correct_version_on_amend_succeeds_and_increments,
occ_stale_order_version_on_amend, version_increments_on_each_mutation,
derived_financial_status_mirrors_billing_on_auth_denied} and
consistency_model/immediate_consistency_signout_visible_in_same_response.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_headers,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import ApiErrorId

DIRECTOR = TEST_USERS["director_headers"]
INTAKE = TEST_USERS["intake_headers"]
ACCESSIONING = TEST_USERS["accessioning_headers"]
BILLING = TEST_USERS["billing_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]


def _build_signed_out_with_vus_referral(gene_symbol="GZ", panel_name="PZ"):
    """Sign out an order carrying a single VUS variant unblocked by a VUS_FOLLOWUP
    referral. Returns (order, report, variant)."""
    FX.set_clock()
    gc = FX.create_counselor("GC One")
    panel, genes = FX.create_published_panel(gene_symbols=(gene_symbol,), name=panel_name)
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"])
    FX.add_requisition(order["id"], "SELF_PAY")
    FX.submit_requisition(order["id"])
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api_client.start_sequencing(order["id"], ACCESSIONING))
    var = FX.add_variant(order["id"], genes[0]["id"], hgvs="c.9T>C")
    FX.classify(order["id"], var["id"], "VUS", user_id="tech-1")
    FX.complete_classification(order["id"])
    FX.request_referral(order["id"], gc["id"], reason="VUS_FOLLOWUP")
    report = FX.create_report(order["id"])
    FX.sign_out(order["id"], report["id"], director_user_id="director-1")
    return order, report, var


def test_cancel_cascade_depth2_billing_writeoff(api):
    """PRD §3.13: "If the billing record is in `AUTH_REQUESTED`, `AUTH_APPROVED`, or
    `PATIENT_PAY`, it is moved to `REVERSED`: the difference of the current
    `allowed_amount_cents` minus the current `coinsurance_collected_cents`, clamped
    so it is never negative (a floor of zero), is added to `writeoff_cents`;
    `coinsurance_collected_cents` is then reset to zero; and the order's
    `financial_status` becomes `SETTLED`."

    Design: Difficulty/transitive_cascade/cancel_cascade_order_billing_writeoff_depth2
    """
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=300000,
                                 gene_symbols=("GC2",), name="PCAN")
    FX.auth_approve(ctx["order"]["id"], 200000)
    resp = api.cancel_order(ctx["order"]["id"], {"cancel_reason": "patient withdrew"}, INTAKE)
    validate_success(resp, 200)
    order = FX.get_order(ctx["order"]["id"])
    billing = validate_success(api.list_order_billing(ctx["order"]["id"], BILLING), 200)[0]
    assert order["pipeline_status"] == "CANCELLED"
    assert order["financial_status"] == "SETTLED"
    assert billing["status"] == "REVERSED"
    assert billing["writeoff_cents"] == 200000


def test_billing_money_conserved_on_cancel_reversal(api):
    """PRD §3.13: "the difference of the current `allowed_amount_cents` minus the
    current `coinsurance_collected_cents`, clamped so it is never negative (a floor
    of zero), is added to `writeoff_cents`; `coinsurance_collected_cents` is then
    reset to zero."

    Design: Difficulty/compensating_invariant/billing_amount_conserved_on_cancel_reversal
    """
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=250000,
                                 gene_symbols=("GM1",), name="PM1")
    FX.auth_approve(ctx["order"]["id"], 200000)
    resp = api.cancel_order(ctx["order"]["id"], {"cancel_reason": "withdrew"}, INTAKE)
    validate_success(resp, 200)
    billing = validate_success(api.list_order_billing(ctx["order"]["id"], BILLING), 200)[0]
    assert billing["writeoff_cents"] == 200000
    assert billing["coinsurance_collected_cents"] == 0
    # Conserved money: writeoff + collected == allowed (nothing collected, full writeoff).
    assert (billing["writeoff_cents"] + billing["coinsurance_collected_cents"]
            == billing["allowed_amount_cents"])


def test_live_report_count_conserved_on_amend(api):
    """PRD §3.9: "On a valid amend, the server creates a successor report whose
    `amends_report_id` points at the report being amended and whose `status` is
    `SIGNED_OUT` ... The prior report moves from `SIGNED_OUT` to `AMENDED`."

    Design: Difficulty/compensating_invariant/live_report_count_conserved_on_amend
    """
    ctx = FX.setup_signed_out(classification="BENIGN", insurance_payer="SELF_PAY",
                              gene_symbols=("GN1",), name="PN1")
    ord_v = FX.get_order(ctx["order"]["id"])["version"]
    resp = api.amend_report(ctx["order"]["id"], ctx["report"]["id"],
                            F.amend_payload(ord_v), make_headers("director-1", "LabDirector"))
    successor = validate_success(resp, 201)
    prior = validate_success(api.get_report(ctx["report"]["id"], DIRECTOR), 200)
    assert prior["status"] == "AMENDED"
    assert successor["status"] == "SIGNED_OUT"
    reports = validate_success(api.list_order_reports(ctx["order"]["id"], DIRECTOR), 200)
    signed_out = [r for r in reports if r["status"] == "SIGNED_OUT"]
    assert len(signed_out) == 1


def test_amend_cascade_depth3_no_change_still_supersedes(api):
    """PRD §3.9: "On a valid amend, the server creates a successor report whose
    `amends_report_id` points at the report being amended and whose `status` is
    `SIGNED_OUT` ... The prior report moves from `SIGNED_OUT` to `AMENDED`, its
    terminal superseded state. ... The amend increments the order's `version` by
    one."

    Design: Difficulty/transitive_cascade/amend_cascade_report_to_variant_archive_depth3
    """
    # Amend without reclassifying: the successor/supersede cascade and version bump
    # still fire even though no variant classification changed.
    ctx = FX.setup_signed_out(classification="BENIGN", insurance_payer="SELF_PAY",
                              gene_symbols=("GZ2",), name="PZ2")
    ord_v = FX.get_order(ctx["order"]["id"])["version"]
    resp = api.amend_report(ctx["order"]["id"], ctx["report"]["id"],
                            F.amend_payload(ord_v), make_headers("director-1", "LabDirector"))
    successor = validate_success(resp, 201)
    prior = validate_success(api.get_report(ctx["report"]["id"], DIRECTOR), 200)
    assert prior["status"] == "AMENDED"
    assert successor["amends_report_id"] == ctx["report"]["id"]
    assert successor["status"] == "SIGNED_OUT"
    assert FX.get_order(ctx["order"]["id"])["version"] == ord_v + 1


def test_cancel_cascade_depth2_from_patient_pay(api):
    """PRD §3.13: "If the billing record is in `AUTH_REQUESTED`, `AUTH_APPROVED`, or
    `PATIENT_PAY`, it is moved to `REVERSED`: the difference of the current
    `allowed_amount_cents` minus the current `coinsurance_collected_cents`, clamped
    so it is never negative (a floor of zero), is added to `writeoff_cents`;
    `coinsurance_collected_cents` is then reset to zero; and the order's
    `financial_status` becomes `SETTLED`."

    Design: Difficulty/transitive_cascade/cancel_cascade_order_billing_writeoff_depth2
    """
    # SELF_PAY order -> billing PATIENT_PAY with allowed == list_price; nothing
    # collected; cancel reverses to SETTLED with writeoff == list_price.
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", list_price_cents=120000,
                                 gene_symbols=("GC2B",), name="PCAN2")
    resp = api.cancel_order(ctx["order"]["id"], {"cancel_reason": "withdrew"}, INTAKE)
    validate_success(resp, 200)
    order = FX.get_order(ctx["order"]["id"])
    billing = validate_success(api.list_order_billing(ctx["order"]["id"], BILLING), 200)[0]
    assert order["pipeline_status"] == "CANCELLED"
    assert order["financial_status"] == "SETTLED"
    assert billing["status"] == "REVERSED"
    assert billing["writeoff_cents"] == 120000


def test_billing_money_conserved_on_cancel_reversal_other_amount(api):
    """PRD §3.13: "the difference of the current `allowed_amount_cents` minus the
    current `coinsurance_collected_cents`, clamped so it is never negative (a floor
    of zero), is added to `writeoff_cents`; `coinsurance_collected_cents` is then
    reset to zero."

    Design: Difficulty/compensating_invariant/billing_amount_conserved_on_cancel_reversal
    """
    # COMMERCIAL allowed 90000, no collection; cancel reverses: writeoff == 90000,
    # collected == 0, and writeoff + collected == allowed (no money drift).
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", list_price_cents=300000,
                                 gene_symbols=("GM2",), name="PM2")
    FX.auth_approve(ctx["order"]["id"], 90000)
    resp = api.cancel_order(ctx["order"]["id"], {"cancel_reason": "withdrew"}, INTAKE)
    validate_success(resp, 200)
    billing = validate_success(api.list_order_billing(ctx["order"]["id"], BILLING), 200)[0]
    assert billing["writeoff_cents"] == 90000
    assert billing["coinsurance_collected_cents"] == 0
    assert (billing["writeoff_cents"] + billing["coinsurance_collected_cents"]
            == billing["allowed_amount_cents"])


def test_live_report_count_conserved_after_two_amends(api):
    """PRD §3.9: "On a valid amend, the server creates a successor report whose
    `amends_report_id` points at the report being amended and whose `status` is
    `SIGNED_OUT` ... The prior report moves from `SIGNED_OUT` to `AMENDED`."

    Design: Difficulty/compensating_invariant/live_report_count_conserved_on_amend
    """
    # Amend twice (each with the current order version); exactly one SIGNED_OUT
    # (non-superseded) report remains.
    ctx = FX.setup_signed_out(classification="BENIGN", insurance_payer="SELF_PAY",
                              gene_symbols=("GN2",), name="PN2")
    v1 = FX.get_order(ctx["order"]["id"])["version"]
    succ1 = validate_success(
        api.amend_report(ctx["order"]["id"], ctx["report"]["id"], F.amend_payload(v1),
                         make_headers("director-1", "LabDirector")), 201)
    v2 = FX.get_order(ctx["order"]["id"])["version"]
    validate_success(
        api.amend_report(ctx["order"]["id"], succ1["id"], F.amend_payload(v2),
                         make_headers("director-1", "LabDirector")), 201)
    reports = validate_success(api.list_order_reports(ctx["order"]["id"], DIRECTOR), 200)
    signed_out = [r for r in reports if r["status"] == "SIGNED_OUT"]
    assert len(signed_out) == 1


def test_occ_correct_version_amend_succeeds_and_increments(api):
    """PRD §2.7: "The amend operation requires the field `expected_test_order_version`
    in its request body, carrying the `version` of the parent `TestOrder` that the
    client last observed."
    PRD §3.9: "The amend increments the order's `version` by one."

    Design: Corner/cross_cutting/occ_correct_version_on_amend_succeeds_and_increments
    """
    ctx = FX.setup_signed_out(classification="BENIGN", insurance_payer="SELF_PAY",
                              gene_symbols=("GCC1",), name="CC1")
    ord_v = FX.get_order(ctx["order"]["id"])["version"]
    resp = api.amend_report(ctx["order"]["id"], ctx["report"]["id"],
                            F.amend_payload(ord_v), make_headers("director-1", "LabDirector"))
    successor = validate_success(resp, 201)
    prior = validate_success(api.get_report(ctx["report"]["id"], DIRECTOR), 200)
    assert prior["status"] == "AMENDED"
    assert successor["amends_report_id"] == ctx["report"]["id"]
    assert FX.get_order(ctx["order"]["id"])["version"] == ord_v + 1


def test_occ_stale_order_version_amend_rejected(api):
    """PRD §2.7: "The server compares that value against the order's current
    `version`; if they differ — for example, because a prior amendment has already
    advanced the order's `version` and moved the earlier report to its superseded
    state — the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), and
    no successor report is created."

    Design: Corner/cross_cutting/occ_stale_order_version_on_amend
    """
    ctx = FX.setup_signed_out(classification="BENIGN", insurance_payer="SELF_PAY",
                              gene_symbols=("GCC2",), name="CC2")
    stale_v = FX.get_order(ctx["order"]["id"])["version"]
    # First amend succeeds with the captured version, advancing TestOrder.version.
    first = validate_success(
        api.amend_report(ctx["order"]["id"], ctx["report"]["id"],
                         F.amend_payload(stale_v), make_headers("director-1", "LabDirector")), 201)
    # Second amend on the successor still carrying the pre-first-amend version -> stale.
    resp = api.amend_report(ctx["order"]["id"], first["id"],
                            F.amend_payload(stale_v), make_headers("director-1", "LabDirector"))
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value, 412)


def test_version_increments_on_mutation(api):
    """PRD §2.4: "a `version` integer that begins at 1 and increments by one on
    every mutation of the resource."

    Design: Corner/cross_cutting/version_increments_on_each_mutation
    """
    ctx = FX.setup_ordered(gene_symbols=("GCC3",), name="CC3")
    assert ctx["order"]["version"] == 1
    FX.add_requisition(ctx["order"]["id"], "SELF_PAY")
    resp = api.submit_requisition(ctx["order"]["id"], INTAKE)
    validate_success(resp, 200)
    order = FX.get_order(ctx["order"]["id"])
    assert order["version"] >= 2


def test_financial_status_mirrors_billing_on_denial(api):
    """PRD §3.6: "A denial advances the billing record from `AUTH_REQUESTED` to
    `AUTH_DENIED` and sets the order's `financial_status` to `AUTH_DENIED`."

    Design: Corner/cross_cutting/derived_financial_status_mirrors_billing_on_auth_denied
    """
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", gene_symbols=("GCC4",), name="CC4")
    resp = api.auth_decision(ctx["order"]["id"], F.auth_decision_payload("DENIED"), BILLING)
    validate_success(resp, 200)
    order = FX.get_order(ctx["order"]["id"])
    billing = validate_success(api.list_order_billing(ctx["order"]["id"], BILLING), 200)[0]
    assert order["financial_status"] == "AUTH_DENIED"
    assert billing["status"] == "AUTH_DENIED"


def test_immediate_consistency_signout_visible_in_response(api):
    """PRD §3.8: "the report's `status` moves from `DRAFT` to `SIGNED_OUT` and
    `signed_out_by_user_id` is set to the director's `X-User-ID`."
    PRD §2.4: the consistency model is immediate (server-stamped fields reflected
    in the same response).

    Design: Corner/consistency_model/immediate_consistency_signout_visible_in_same_response
    """
    ctx = FX.setup_draft_report(classification="BENIGN", insurance_payer="SELF_PAY",
                                classifier_user_id="tech-1", gene_symbols=("GCM1",), name="CM1")
    resp = api.sign_out_report(ctx["order"]["id"], ctx["report"]["id"],
                               make_headers("director-1", "LabDirector"))
    data = validate_success(resp, 200)
    assert data["status"] == "SIGNED_OUT"
    assert data["signed_out_by_user_id"] == "director-1"
