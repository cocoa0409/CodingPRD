"""Superbill billing: estimated vs final patient responsibility, the self-pay
sliding scale, multi-component round-then-sum, the independent billing axis,
void cascade, insurance-visit conservation, and superbill precedence/state gates.

Queue A: dual_variant_calc, combinatorial_formula, non_linear_state_machine
(parallel axes), transitive_cascade (void), priority_pair (state>fiscal),
cross_entity_state_dependency (superbill requires completed), compensating_invariant.
Queue B: auth visits exhausted, adjudicate-voided.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx


# ================================ estimated vs final (queue A)
def test_superbill_estimated_patient_responsibility_at_create(api):
    """PRD §3.8: "The `patient_responsibility_cents` is computed per component and
    then summed: the therapy component's allowed amount times `coinsurance_pct`,
    rounded half-up to whole cents, plus the materials component's allowed amount
    times `coinsurance_pct`, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/superbill_estimated_vs_final_patient_responsibility
    """
    ctx = fx.setup_completed_session(api, payer="INSURANCE")
    sb = validate_success(api.create_superbill(
        {"session_id": ctx["session_id"], "client_id": ctx["client_id"]},
        TEST_USERS["billing_headers"]), expected_status=201)
    assert sb["patient_responsibility_cents"] == 2501, "round(12503*0.20) -> 2501 (ESTIMATED)"


def test_superbill_final_patient_responsibility_after_adjudicate(api):
    """PRD §3.8: "In this final variant, `allowed_amount_cents` becomes the posted
    remittance figure, and `adjustment_cents` becomes `billed_amount_cents` minus that
    allowed amount." PRD §3.8: "The `plan_paid_cents` is the allowed amount minus the
    recomputed `patient_responsibility_cents`."

    Design: Difficulty/dual_variant_calc/superbill_estimated_vs_final_patient_responsibility
    """
    ctx = fx.setup_completed_session(api, payer="INSURANCE")
    sb = validate_success(api.create_superbill(
        {"session_id": ctx["session_id"], "client_id": ctx["client_id"]},
        TEST_USERS["billing_headers"]), expected_status=201)
    final = validate_success(api.adjudicate_superbill(
        sb["id"], {"allowed_amount_cents": 10000}, TEST_USERS["billing_headers"]),
        expected_status=200)
    assert final["patient_responsibility_cents"] == 2000, "round(10000*0.20) -> 2000 (FINAL)"
    assert final["adjustment_cents"] == 2503, "billed 12503 - allowed 10000"
    assert final["plan_paid_cents"] == 8000, "allowed 10000 - pr 2000"


# ================================ self-pay sliding scale (queue A)
def test_self_pay_sliding_scale_75pct_discount_fee(api):
    """PRD §3.8: "A ratio at or below 1.50 earns a 75% discount ... Take the base rate
    for the session's modality (the individual rate of 12503 cents or the group rate
    of 6503 cents), multiply it by one minus the discount, and round half-up to whole
    cents; then clamp the result so it is never below the 2000-cent minimum fee and
    never above the undiscounted base rate."

    Design: Difficulty/combinatorial_formula/sliding_scale_fee_tiered_fpl_bands
    """
    ctx = fx.setup_completed_session(
        api, payer="SELF_PAY",
        client_overrides={"household_income_cents": 3_000_000, "household_size": 2})
    sb = validate_success(api.create_superbill(
        {"session_id": ctx["session_id"], "client_id": ctx["client_id"]},
        TEST_USERS["billing_headers"]), expected_status=201)
    assert sb["patient_responsibility_cents"] == 3126, "round(12503*0.25) -> 3126"


def test_self_pay_sliding_scale_plan_paid_and_adjustment(api):
    """PRD §3.8: "That clamped figure is the self-pay `patient_responsibility_cents`;
    `plan_paid_cents` is 0, and `adjustment_cents` is the `billed_amount_cents` minus
    the patient responsibility (the sliding-scale write-off)."

    Design: Difficulty/combinatorial_formula/sliding_scale_fee_tiered_fpl_bands
    """
    ctx = fx.setup_completed_session(
        api, payer="SELF_PAY",
        client_overrides={"household_income_cents": 3_000_000, "household_size": 2})
    sb = validate_success(api.create_superbill(
        {"session_id": ctx["session_id"], "client_id": ctx["client_id"]},
        TEST_USERS["billing_headers"]), expected_status=201)
    assert sb["plan_paid_cents"] == 0
    assert sb["adjustment_cents"] == 9377, "billed 12503 - fee 3126"


# ================================ multi-component round-then-sum (queue A)
def _completed_insurance_session_with_material(api):
    ctx = fx.setup_active_plan(
        api, payer="INSURANCE",
        client_overrides={"insurance_contracted_rate_cents": 13756,
                          "insurance_coinsurance_pct": 0.20, "insurance_visits_authorized": 5},
        clock="2026-06-01T00:00:00Z")
    mat = fx.new_material(api, name="Djembe", on_hand_quantity=4, unit_charge_cents=1253)
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                                  material_item_id=mat["id"], material_qty=1)
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    fx.set_clock(api, "2026-06-01T09:30:00Z")
    fx.complete_session(api, session["id"], ctx["ther_id"], [ctx["client_id"]])
    ctx["session_id"] = session["id"]
    return ctx


def test_superbill_component_charges(api):
    """PRD §3.8: "The `therapy_charge_cents` is the individual rate of 12503 cents
    when the session modality is `INDIVIDUAL` ... The `materials_charge_cents` is the
    session's `material_qty` multiplied by the material item's `unit_charge_cents` ...
    The `billed_amount_cents` is the therapy charge plus the materials charge."

    Design: Difficulty/combinatorial_formula/superbill_multicomponent_round_then_sum
    """
    ctx = _completed_insurance_session_with_material(api)
    sb = validate_success(api.create_superbill(
        {"session_id": ctx["session_id"], "client_id": ctx["client_id"]},
        TEST_USERS["billing_headers"]), expected_status=201)
    assert sb["therapy_charge_cents"] == 12503
    assert sb["materials_charge_cents"] == 1253
    assert sb["billed_amount_cents"] == 13756


def test_superbill_round_per_component_then_sum(api):
    """PRD §2.9: "the therapy component and the materials component are each rounded
    to whole cents *before* they are summed — rounding the raw sum once is explicitly
    not the rule."

    Design: Difficulty/combinatorial_formula/superbill_multicomponent_round_then_sum
    """
    ctx = _completed_insurance_session_with_material(api)
    sb = validate_success(api.create_superbill(
        {"session_id": ctx["session_id"], "client_id": ctx["client_id"]},
        TEST_USERS["billing_headers"]), expected_status=201)
    # round(12503*0.20)=2501 + round(1253*0.20)=251 -> 2752 (NOT round(13756*0.20)=2751)
    assert sb["patient_responsibility_cents"] == 2752


# ================================ parallel scheduling/billing axes (queue A)
def test_billing_axis_advances_to_billed_scheduling_unchanged(api):
    """PRD §3.8: "Billing runs on the session's second, independent axis." PRD §3.8:
    "On success the session advances `UNBILLED → BILLED`, a new superbill opens in
    `SUBMITTED` status".

    Design: Difficulty/non_linear_state_machine/session_parallel_scheduling_billing_axes
    """
    ctx = fx.setup_completed_session(api, payer="INSURANCE")
    fx.create_superbill(api, ctx["session_id"], ctx["client_id"])
    session = validate_success(api.get_session(ctx["session_id"], TEST_USERS["billing_headers"]),
                               expected_status=200)
    assert session["scheduling_status"] == "COMPLETED", "scheduling axis unchanged"
    assert session["billing_status"] == "BILLED"


def test_billing_axis_advances_to_adjudicated_scheduling_unchanged(api):
    """PRD §3.8: "The superbill advances `SUBMITTED → ADJUDICATED` and the session
    advances `BILLED → ADJUDICATED`."

    Design: Difficulty/non_linear_state_machine/session_parallel_scheduling_billing_axes
    """
    ctx = fx.setup_completed_session(api, payer="INSURANCE")
    sb = fx.create_superbill(api, ctx["session_id"], ctx["client_id"])
    api.adjudicate_superbill(sb["id"], {"allowed_amount_cents": 12000}, TEST_USERS["billing_headers"])
    session = validate_success(api.get_session(ctx["session_id"], TEST_USERS["billing_headers"]),
                               expected_status=200)
    assert session["scheduling_status"] == "COMPLETED", "scheduling axis still unchanged"
    assert session["billing_status"] == "ADJUDICATED"


# ================================ void cascade (queue A)
def test_void_cascades_superbill_and_session(api):
    """PRD §3.8: "A `BillingSpecialist` may void a superbill that is either
    `SUBMITTED` or `ADJUDICATED`, driving it to the terminal `VOIDED` state ... Voiding
    cascades to the linked session, reverting its billing axis to `UNBILLED`".

    Design: Difficulty/transitive_cascade/superbill_void_cascade_to_visit_credit
    """
    ctx = fx.setup_billed_session(api, visits_authorized=2)
    sb = validate_success(api.void_superbill(ctx["superbill_id"], TEST_USERS["billing_headers"]),
                          expected_status=200)
    assert sb["status"] == "VOIDED"
    session = validate_success(api.get_session(ctx["session_id"], TEST_USERS["billing_headers"]),
                               expected_status=200)
    assert session["billing_status"] == "UNBILLED"


def test_void_refunds_insurance_visit_credit(api):
    """PRD §3.8: "If the client is an insurance client, the void also refunds the
    authorization by lowering `insurance_visits_used` by 1, so
    `insurance_visits_remaining` recovers."

    Design: Difficulty/transitive_cascade/superbill_void_cascade_to_visit_credit
    """
    ctx = fx.setup_billed_session(api, visits_authorized=2)
    api.void_superbill(ctx["superbill_id"], TEST_USERS["billing_headers"])
    client = validate_success(api.get_client(ctx["client_id"], TEST_USERS["billing_headers"]),
                              expected_status=200)
    assert client["insurance_visits_used"] == 0
    assert client["insurance_visits_remaining"] == 2


# ================================ insurance-visit conservation (queue A)
def test_insurance_visit_consumed_on_bill(api):
    """PRD §3.8: "On success the session advances `UNBILLED → BILLED`, a new superbill
    opens in `SUBMITTED` status, and — for an insurance client — the client's
    `insurance_visits_used` rises by 1."

    Design: Difficulty/compensating_invariant/insurance_visit_bill_void_conserves_authorization
    """
    ctx = fx.setup_billed_session(api, visits_authorized=3)
    client = validate_success(api.get_client(ctx["client_id"], TEST_USERS["billing_headers"]),
                              expected_status=200)
    assert client["insurance_visits_used"] == 1
    assert client["insurance_visits_remaining"] == 2
    assert (client["insurance_visits_used"] + client["insurance_visits_remaining"]
            == client["insurance_visits_authorized"] == 3)


def test_insurance_visit_refunded_on_void_conserves(api):
    """PRD §3.8: "the void also refunds the authorization by lowering
    `insurance_visits_used` by 1, so `insurance_visits_remaining` recovers."

    Design: Difficulty/compensating_invariant/insurance_visit_bill_void_conserves_authorization
    """
    ctx = fx.setup_billed_session(api, visits_authorized=3)
    api.void_superbill(ctx["superbill_id"], TEST_USERS["billing_headers"])
    client = validate_success(api.get_client(ctx["client_id"], TEST_USERS["billing_headers"]),
                              expected_status=200)
    assert client["insurance_visits_used"] == 0
    assert client["insurance_visits_remaining"] == 3
    assert (client["insurance_visits_used"] + client["insurance_visits_remaining"]
            == client["insurance_visits_authorized"] == 3)


# ================================ state beats fiscal on superbill (queue A)
def _scheduled_insurance_session_no_visits(api):
    ctx = fx.setup_active_plan(api, payer="INSURANCE",
                               client_overrides={"insurance_visits_authorized": 0},
                               clock="2026-06-01T00:00:00Z")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"])
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    ctx["session_id"] = session["id"]
    return ctx


def test_superbill_state_error_beats_fiscal(api):
    """PRD §3.8: "If the session is not `COMPLETED`, the create is rejected with
    `ERR_SESSION_NOT_COMPLETED`."
    PRD §2.7: "wherever two of them could both fire on the same request, the
    lower-numbered check wins."

    Design: Difficulty/priority_pair_validation_conflict/superbill_state_beats_fiscal
    """
    ctx = _scheduled_insurance_session_no_visits(api)
    resp = api.create_superbill({"session_id": ctx["session_id"], "client_id": ctx["client_id"]},
                                TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_COMPLETED.value)


def test_superbill_state_error_not_auth_visits(api):
    """PRD §2.7: "wherever two of them could both fire on the same request, the
    lower-numbered check wins."
    PRD §2.7: "7. State — the target resource is in a state that permits the requested
    transition (... or `ERR_SESSION_NOT_COMPLETED`, each 409)."

    Design: Difficulty/priority_pair_validation_conflict/superbill_state_beats_fiscal
    """
    ctx = _scheduled_insurance_session_no_visits(api)
    resp = api.create_superbill({"session_id": ctx["session_id"], "client_id": ctx["client_id"]},
                                TEST_USERS["billing_headers"])
    err = validate_error(resp, ApiErrorId.ERR_SESSION_NOT_COMPLETED.value)
    assert err["error_id"] != ApiErrorId.ERR_AUTH_VISITS_EXHAUSTED.value


# ================================ superbill requires completed session (queue A)
def test_superbill_on_scheduled_session_rejected(api):
    """PRD §3.8: "A session may be billed only after it has been completed and while
    its `billing_status` is `UNBILLED` ... If the session is not `COMPLETED`, the
    create is rejected with `ERR_SESSION_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/superbill_requires_session_completed
    """
    ctx = fx.setup_active_plan(api, payer="INSURANCE", clock="2026-06-01T00:00:00Z")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"])
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    resp = api.create_superbill({"session_id": session["id"], "client_id": ctx["client_id"]},
                                TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_COMPLETED.value)


def test_superbill_rejected_leaves_session_unbilled(api):
    """PRD §3.8: "On success the session advances `UNBILLED → BILLED`". PRD §3.8: "If
    the session is not `COMPLETED`, the create is rejected with
    `ERR_SESSION_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/superbill_requires_session_completed
    """
    ctx = fx.setup_active_plan(api, payer="INSURANCE", clock="2026-06-01T00:00:00Z")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"])
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    api.create_superbill({"session_id": session["id"], "client_id": ctx["client_id"]},
                         TEST_USERS["billing_headers"])
    live = validate_success(api.get_session(session["id"], TEST_USERS["billing_headers"]),
                            expected_status=200)
    assert live["billing_status"] == "UNBILLED", "a rejected superbill does not advance billing"


# ================================ fiscal + terminal-state (queue B)
def test_auth_visits_exhausted_on_superbill_rejected(api):
    """PRD §3.8: "For an insurance client, the superbill also consumes authorization:
    `insurance_visits_remaining` must be at least 1, or the create is rejected with
    `ERR_AUTH_VISITS_EXHAUSTED`."

    Design: Corner/validations/auth_visits_exhausted_on_superbill_rejected
    """
    ctx = fx.setup_completed_session(api, payer="INSURANCE",
                                     client_overrides={"insurance_visits_authorized": 0})
    resp = api.create_superbill({"session_id": ctx["session_id"], "client_id": ctx["client_id"]},
                                TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_AUTH_VISITS_EXHAUSTED.value)


def test_adjudicate_voided_superbill_rejected(api):
    """PRD §3.8: "The `BillingSpecialist` supplies the remittance `allowed_amount_cents`,
    permitted only while the superbill is `SUBMITTED` (otherwise
    `ERR_SUPERBILL_INVALID_STATE`)".

    Design: Corner/state_machines/adjudicate_voided_superbill_rejected
    """
    ctx = fx.setup_billed_session(api, visits_authorized=3)
    api.void_superbill(ctx["superbill_id"], TEST_USERS["billing_headers"])
    resp = api.adjudicate_superbill(ctx["superbill_id"], {"allowed_amount_cents": 10000},
                                    TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_SUPERBILL_INVALID_STATE.value)
