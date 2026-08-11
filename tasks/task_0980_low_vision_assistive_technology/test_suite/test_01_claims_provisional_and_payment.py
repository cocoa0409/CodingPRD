"""Claims: provisional estimate vs final remittance, payer responsibility,
per-line rounding, funding boundary precision, and the conservation invariant."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_payload, create_referral_payload, create_evaluation_payload,
    create_device_model_payload, create_device_unit_payload, create_device_order_payload,
    create_funding_authorization_payload, create_claim_payload, claim_line,
    make_funding_coordinator_headers, make_payer_adjudicator_headers,
    make_billing_specialist_headers,
    create_client, create_client_with_accepted_referral, create_finalized_evaluation,
    create_device_model, create_device_unit, place_order, place_and_allocate_order,
    create_approved_authorization, create_claim, create_submitted_claim,
    setup_approved_funding_scenario, setup_allocated_purchase,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
SPECIALIST = TEST_USERS["vision_specialist_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def _setup_dvc_scenario(api):
    """Ana Reyes scenario: CCTV purchase + APPROVED INSURANCE auth 50000."""
    c = get_success_data(api.create_client(
        create_client_payload(full_name="Ana Reyes", date_of_birth="1958-03-04"), INTAKE))
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="PHYSICIAN", referring_party="Dr. Kim"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    e = get_success_data(api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v, acuity_score=60, contrast_score=55,
        field_loss_pct=40, recommended_category="CCTV"), SPECIALIST))
    get_success_data(api.finalize_evaluation(e["id"], SPECIALIST))
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="CCTV Pro 24", category="CCTV", list_price_cents=100000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-A1", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], e["id"], m["id"], fulfillment_type="PURCHASE", warranty_cents=0), SPECIALIST))
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    fa = get_success_data(api.create_funding_authorization(create_funding_authorization_payload(
        c["id"], payer_type="INSURANCE", payer_ref="POL-100", authorized_amount_cents=50000),
        make_funding_coordinator_headers("fc-1")))
    get_success_data(api.submit_funding_authorization(fa["id"], make_funding_coordinator_headers("fc-1")))
    get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("pa-1")))
    return c, e, m, u, o, fa


def test_claim_provisional_estimate_differs_from_final_remittance(api):
    """PRD §3.7: "for each line, in array order, multiply the line's
    `unit_price_cents` by its `quantity` and by a payer factor — 1.00 when the
    authorization's `payer_type` is `VR`, 0.80 when it is `INSURANCE` — rounding
    each line's product half-up to a whole cent **before** summing".
    PRD §3.7: "the adjudicator's `allowed_amount_cents` becomes
    `final_amount_cents` verbatim."

    Design: Difficulty/dual_variant_calc/dvc_claim_provisional_vs_final
    """
    c, e, m, u, o, fa = _setup_dvc_scenario(api)
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 3333, 1), claim_line("WARRANTY", 3333, 1),
               claim_line("TRAINING", 3333, 1)]), BILLING))
    assert cl["provisional_total_cents"] == 7998, (
        f"3 x round_half_up(3333*0.80)=2666 summed = 7998, got {cl['provisional_total_cents']}")
    get_success_data(api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    paid = get_success_data(api.adjudicate_claim(
        cl["id"], {"decision": "PAY", "allowed_amount_cents": 7500},
        make_payer_adjudicator_headers("pa-1")))
    assert paid["final_amount_cents"] == 7500
    assert paid["provisional_total_cents"] != paid["final_amount_cents"]
    assert paid["payer_pays_cents"] == 6000  # round_half_up(7500*0.80)
    assert paid["client_pays_cents"] == 1500


def test_claim_reservation_reconciled_against_authorization(api):
    """PRD §3.7: "A successful submit moves the claim `DRAFT → SUBMITTED`,
    records `submitted_by_user_id`, and **subtracts** the provisional total from
    the authorization's `remaining_amount_cents` as a reservation."
    PRD §3.7: "`remaining_amount_cents` rises by `provisional_total_cents` minus
    `payer_pays_cents` (release the reservation, deduct the payer share)".

    Design: Difficulty/dual_variant_calc/dvc_claim_provisional_vs_final
    """
    c, e, m, u, o, fa = _setup_dvc_scenario(api)
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 3333, 1), claim_line("WARRANTY", 3333, 1),
               claim_line("TRAINING", 3333, 1)]), BILLING))
    get_success_data(api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    rem_mid = get_success_data(api.get_funding_authorization(fa["id"], BILLING))["remaining_amount_cents"]
    assert rem_mid == 42002, f"50000 - 7998 reserved = 42002, got {rem_mid}"
    get_success_data(api.adjudicate_claim(
        cl["id"], {"decision": "PAY", "allowed_amount_cents": 7500},
        make_payer_adjudicator_headers("pa-1")))
    rem_end = get_success_data(api.get_funding_authorization(fa["id"], BILLING))["remaining_amount_cents"]
    assert rem_end == 44000, f"42002 + 7998 - 6000 = 44000, got {rem_end}"


def _setup_min_cap_scenario(api):
    """Cara Dee scenario: MAGNIFIER purchase + APPROVED INSURANCE auth 2000,
    claim provisional 800 already SUBMITTED."""
    c = get_success_data(api.create_client(
        create_client_payload(full_name="Cara Dee", date_of_birth="1949-11-02"), INTAKE))
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="SELF", referring_party="self"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    e = get_success_data(api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v, acuity_score=50, contrast_score=50,
        field_loss_pct=30, recommended_category="MAGNIFIER"), SPECIALIST))
    get_success_data(api.finalize_evaluation(e["id"], SPECIALIST))
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-M1", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], e["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    fa = get_success_data(api.create_funding_authorization(create_funding_authorization_payload(
        c["id"], payer_type="INSURANCE", payer_ref="POL-200", authorized_amount_cents=2000),
        make_funding_coordinator_headers("fc-1")))
    get_success_data(api.submit_funding_authorization(fa["id"], make_funding_coordinator_headers("fc-1")))
    get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("pa-1")))
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 1000, 1)]), BILLING))
    get_success_data(api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    return c, o, fa, cl


def test_payer_responsibility_min_cap_binds_and_exhausts(api):
    """PRD §3.7: "the base is `allowed_amount_cents` for `VR`, or
    `allowed_amount_cents` multiplied by the 80-percent coinsurance and rounded
    half-up for `INSURANCE`; `payer_pays_cents` is the smaller of that base and
    the available funds; and `client_pays_cents` is `allowed_amount_cents` minus
    `payer_pays_cents`."
    PRD §3.7: "if that leaves the remaining balance at exactly 0 the
    authorization flips `APPROVED → EXHAUSTED`."

    Design: Difficulty/combinatorial_formula/cf_payer_responsibility_min_cap_branch
    """
    c, o, fa, cl = _setup_min_cap_scenario(api)
    paid = get_success_data(api.adjudicate_claim(
        cl["id"], {"decision": "PAY", "allowed_amount_cents": 3000},
        make_payer_adjudicator_headers("pa-1")))
    assert paid["payer_pays_cents"] == 2000, (
        f"min(2400, 1200 remaining + 800 reservation) = 2000, got {paid['payer_pays_cents']}")
    assert paid["client_pays_cents"] == 1000  # 3000 - 2000, STANDARD tier
    auth = get_success_data(api.get_funding_authorization(fa["id"], BILLING))
    assert auth["remaining_amount_cents"] == 0  # 1200 + 800 - 2000
    assert auth["status"] == "EXHAUSTED"


def test_payer_responsibility_available_includes_own_reservation(api):
    """PRD §3.7: "the available funds are the authorization's current
    `remaining_amount_cents` **plus** this claim's own `provisional_total_cents`
    (the reservation is still held at this instant)".

    Design: Difficulty/combinatorial_formula/cf_payer_responsibility_min_cap_branch
    """
    c, o, fa, cl = _setup_min_cap_scenario(api)
    # remaining is 1200; claim's own reservation is 800. An allowed amount whose
    # base (2400) exceeds remaining alone (1200) but fits remaining+reservation
    # (2000 cap) pays 2000 — proving the reservation is included in availability.
    paid = get_success_data(api.adjudicate_claim(
        cl["id"], {"decision": "PAY", "allowed_amount_cents": 3000},
        make_payer_adjudicator_headers("pa-1")))
    assert paid["payer_pays_cents"] == 2000
    assert paid["final_amount_cents"] == 3000


def _setup_per_line_scenario(api):
    """Dan Ojo scenario: MAGNIFIER purchase + APPROVED INSURANCE auth 50000."""
    c = get_success_data(api.create_client(
        create_client_payload(full_name="Dan Ojo", date_of_birth="1962-07-21"), INTAKE))
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="VR_AGENCY", referring_party="State VR"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    e = get_success_data(api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v, acuity_score=70, contrast_score=60,
        field_loss_pct=20, recommended_category="MAGNIFIER"), SPECIALIST))
    get_success_data(api.finalize_evaluation(e["id"], SPECIALIST))
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 7x", category="MAGNIFIER", list_price_cents=30000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-M7", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], e["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    fa = get_success_data(api.create_funding_authorization(create_funding_authorization_payload(
        c["id"], payer_type="INSURANCE", payer_ref="POL-300", authorized_amount_cents=50000),
        make_funding_coordinator_headers("fc-1")))
    get_success_data(api.submit_funding_authorization(fa["id"], make_funding_coordinator_headers("fc-1")))
    get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("pa-1")))
    return c, o, fa


def test_claim_provisional_rounds_per_line_then_sums(api):
    """PRD §3.7: "rounding each line's product half-up to a whole cent **before**
    summing; the provisional total is the sum of those per-line rounded amounts."
    PRD §2.5: "Sum-then-round is explicitly not used for claim estimates, because
    it can differ from round-then-sum by whole cents."

    Design: Difficulty/combinatorial_formula/cf_claim_provisional_per_line_rounding
    """
    c, o, fa = _setup_per_line_scenario(api)
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-11T00:00:00Z",
        lines=[claim_line("DEVICE", 1667, 1), claim_line("WARRANTY", 1667, 1)]), BILLING))
    assert cl["provisional_total_cents"] == 2668, (
        f"2 x round_half_up(1667*0.80)=1334 summed = 2668, got {cl['provisional_total_cents']}")
    assert cl["provisional_total_cents"] != 2667, (
        "sum-then-round would give round_half_up(3334*0.80)=2667; that order is rejected")


def test_claim_provisional_per_line_rounding_quantity_multiplies(api):
    """PRD §3.7: "multiply the line's `unit_price_cents` by its `quantity` and by
    a payer factor — 1.00 when the authorization's `payer_type` is `VR`, 0.80
    when it is `INSURANCE` — rounding each line's product half-up to a whole
    cent **before** summing".

    Design: Difficulty/combinatorial_formula/cf_claim_provisional_per_line_rounding
    """
    c, o, fa = _setup_per_line_scenario(api)
    # Single line, quantity 2: round_half_up(1667*2*0.80) = round_half_up(2667.2) = 2667.
    # Two separate lines of 1667 each would give 2668; the pinned per-line order
    # distinguishes quantity multiplication from line splitting.
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-11T00:00:00Z",
        lines=[claim_line("DEVICE", 1667, 2)]), BILLING))
    assert cl["provisional_total_cents"] == 2667, (
        f"round_half_up(1667*2*0.80) = 2667, got {cl['provisional_total_cents']}")


def _setup_funding_boundary_scenario(api):
    """Ira Mel scenario: APPROVED INSURANCE auth for exactly 8000 cents."""
    c = get_success_data(api.create_client(
        create_client_payload(full_name="Ira Mel", date_of_birth="1947-09-09"), INTAKE))
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="SELF", referring_party="self"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    e = get_success_data(api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v, acuity_score=60, contrast_score=60,
        field_loss_pct=20, recommended_category="MAGNIFIER"), SPECIALIST))
    get_success_data(api.finalize_evaluation(e["id"], SPECIALIST))
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-B1", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], e["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    fa = get_success_data(api.create_funding_authorization(create_funding_authorization_payload(
        c["id"], payer_type="INSURANCE", payer_ref="POL-500", authorized_amount_cents=8000),
        make_funding_coordinator_headers("fc-1")))
    get_success_data(api.submit_funding_authorization(fa["id"], make_funding_coordinator_headers("fc-1")))
    get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("pa-1")))
    return c, o, fa


def test_funding_exact_equality_allowed(api):
    """PRD §3.7: "And `provisional_total_cents` must not exceed the
    authorization's `remaining_amount_cents` — exact equality is allowed — else
    `ERR_INSUFFICIENT_FUNDING` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/bp_funding_remaining_exact_equality
    """
    c, o, fa = _setup_funding_boundary_scenario(api)
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 10000, 1)]), BILLING))
    assert cl["provisional_total_cents"] == 8000  # round_half_up(10000*0.80)
    submitted = get_success_data(api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    assert submitted["status"] == "SUBMITTED", "8000 <= 8000: exact equality allowed"
    rem = get_success_data(api.get_funding_authorization(fa["id"], BILLING))["remaining_amount_cents"]
    assert rem == 0


def test_funding_one_cent_over_boundary_rejected(api):
    """PRD §3.7: "And `provisional_total_cents` must not exceed the
    authorization's `remaining_amount_cents` — exact equality is allowed — else
    `ERR_INSUFFICIENT_FUNDING` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/bp_funding_remaining_exact_equality
    """
    c, o, fa = _setup_funding_boundary_scenario(api)
    cl1 = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 10000, 1)]), BILLING))
    get_success_data(api.submit_claim(cl1["id"], make_billing_specialist_headers("bs-1")))
    cl2 = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-11T00:00:00Z",
        lines=[claim_line("SHIPPING", 2, 1)]), BILLING))
    assert cl2["provisional_total_cents"] == 2  # round_half_up(2*0.80)=1.6 -> 2
    resp = api.submit_claim(cl2["id"], make_billing_specialist_headers("bs-1"))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDING)


def _setup_conservation_scenario(api):
    """Ora Fin scenario: APPROVED VR authorization for 20000 cents."""
    c = get_success_data(api.create_client(
        create_client_payload(full_name="Ora Fin", date_of_birth="1948-12-03"), INTAKE))
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="VR_AGENCY", referring_party="State VR"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    e = get_success_data(api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v, acuity_score=60, contrast_score=60,
        field_loss_pct=20, recommended_category="MAGNIFIER"), SPECIALIST))
    get_success_data(api.finalize_evaluation(e["id"], SPECIALIST))
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    u = get_success_data(api.create_device_unit(create_device_unit_payload(
        m["id"], serial_no="SN-V1", condition="NEW"), ADMIN))
    o = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], e["id"], m["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    get_success_data(api.allocate_device_order(o["id"], {"device_unit_id": u["id"]}, SPECIALIST))
    fa = get_success_data(api.create_funding_authorization(create_funding_authorization_payload(
        c["id"], payer_type="VR", payer_ref="VR-900", authorized_amount_cents=20000),
        make_funding_coordinator_headers("fc-1")))
    get_success_data(api.submit_funding_authorization(fa["id"], make_funding_coordinator_headers("fc-1")))
    get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("pa-1")))
    return c, o, fa


def test_funding_conservation_submit_then_void_restores(api):
    """PRD §3.7: "Voiding a `SUBMITTED` claim returns `provisional_total_cents`
    to the remaining balance; voiding a `PAID` claim returns `payer_pays_cents`."
    PRD §3.7: "an authorization's `remaining_amount_cents` always equals its
    `authorized_amount_cents` minus the sum of `provisional_total_cents` over its
    `SUBMITTED` claims, minus the sum of `payer_pays_cents` over its `PAID`
    claims".

    Design: Difficulty/compensating_invariant/ci_funding_conservation
    """
    c, o, fa = _setup_conservation_scenario(api)
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 5000, 1)]), BILLING))
    get_success_data(api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    rem1 = get_success_data(api.get_funding_authorization(fa["id"], BILLING))["remaining_amount_cents"]
    assert rem1 == 15000, f"20000 - 5000 reserved = 15000, got {rem1}"
    get_success_data(api.void_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    rem2 = get_success_data(api.get_funding_authorization(fa["id"], BILLING))["remaining_amount_cents"]
    assert rem2 == 20000, f"void of SUBMITTED fully restores to 20000, got {rem2}"


def test_funding_conservation_pay_reconciles_delta(api):
    """PRD §3.7: "`remaining_amount_cents` rises by `provisional_total_cents`
    minus `payer_pays_cents` (release the reservation, deduct the payer share)".
    PRD §3.7: "the base is `allowed_amount_cents` for `VR`".

    Design: Difficulty/compensating_invariant/ci_funding_conservation
    """
    c, o, fa = _setup_conservation_scenario(api)
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-12T00:00:00Z",
        lines=[claim_line("DEVICE", 5000, 1)]), BILLING))
    get_success_data(api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    rem3 = get_success_data(api.get_funding_authorization(fa["id"], BILLING))["remaining_amount_cents"]
    assert rem3 == 15000
    paid = get_success_data(api.adjudicate_claim(
        cl["id"], {"decision": "PAY", "allowed_amount_cents": 4000},
        make_payer_adjudicator_headers("pa-1")))
    assert paid["payer_pays_cents"] == 4000  # VR base = allowed; min(4000, 15000+5000)
    rem4 = get_success_data(api.get_funding_authorization(fa["id"], BILLING))["remaining_amount_cents"]
    assert rem4 == 16000, f"15000 + 5000 - 4000 = 16000; invariant 16000 + 4000 == 20000, got {rem4}"
