"""Billing and reimbursement cycle: provisional-vs-final billed amounts,
remittance rounding and money conservation, the deny path, duplicate and
undelivered-session guards, and the adjudication precedence pair."""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_rbt_headers,
    make_bcba_headers,
    setup_active_authorization,
    setup_delivered_direct_session,
    schedule_session,
    deliver_session,
    deliver_supervision_units,
    get_authorization,
    create_draft_claim,
    create_submitted_claim,
    factories,
)


# ─── Difficulty: provisional vs final billed_cents on short delivery ─────────

def test_provisional_billed_uses_scheduled_units_at_create(api):
    """PRD §3.9: "The provisional billed amount set at claim creation is the
    session's `scheduled_units` multiplied by that line's rate — the reserved
    estimate."

    Design: Difficulty/dual_variant_calc/claim_billed_provisional_vs_final_diverges_on_short_delivery
    """
    sc = setup_delivered_direct_session(api, scheduled_units=8, delivered_units=7,
                                        authorized_direct_units=320,
                                        assessment_score=130)
    claim = create_draft_claim(api, sc["session"]["id"])
    # DIRECT_THERAPY rate 3200; 8 scheduled units -> 25600.
    assert claim["billed_cents"] == 25600, claim["billed_cents"]


def test_final_billed_uses_delivered_units_at_submit(api):
    """PRD §3.9: "When a `BillingSpecialist` submits the claim, moving it from
    `DRAFT` to `SUBMITTED`, `billed_cents` is refinalized to the session's
    `delivered_units` multiplied by that line's rate — the actuals."

    Design: Difficulty/dual_variant_calc/claim_billed_provisional_vs_final_diverges_on_short_delivery
    """
    sc = setup_delivered_direct_session(api, scheduled_units=8, delivered_units=7,
                                        authorized_direct_units=320,
                                        assessment_score=130)
    claim = create_draft_claim(api, sc["session"]["id"])
    assert claim["billed_cents"] == 25600
    submitted = get_success_data(
        api.submit_claim(claim["id"], TEST_USERS["billing_headers"])
    )
    # 7 delivered units * 3200 -> 22400; diverges from provisional by 3200.
    assert submitted["billed_cents"] == 22400, submitted["billed_cents"]
    assert 25600 - submitted["billed_cents"] == 3200


# ─── Difficulty: remittance rounds patient share first, then subtracts ───────

def _setup_compliant_paid_ready(api, allowed_rate_cents, coinsurance_pct,
                                delivered_direct=5):
    """5 delivered direct + 1 delivered supervision -> COMPLIANT (ceil(5*0.1)=1)."""
    sc = setup_active_authorization(
        api, authorized_direct_units=100, authorized_supervision_units=20,
        assessment_score=70,
        payer_overrides={"allowed_rate_cents": allowed_rate_cents,
                         "coinsurance_pct": coinsurance_pct,
                         "supervision_ratio_pct": 0.10},
    )
    direct = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                              "RBT", scheduled_start="2026-03-02T09:00:00Z",
                              scheduled_end="2026-03-02T10:15:00Z",
                              scheduled_units=delivered_direct)
    deliver_session(api, direct["id"], sc["rbt"]["id"], "RBT", delivered_direct)
    deliver_supervision_units(api, sc, scheduled_units=2, delivered_units=1,
                              scheduled_start="2026-03-02T11:00:00Z",
                              scheduled_end="2026-03-02T11:30:00Z")
    sc["_direct"] = direct
    return sc


def test_patient_responsibility_rounds_half_up(api):
    """PRD §2.8: "the result is rounded to the nearest whole cent using the
    round-half-up convention (a value exactly halfway between two cents rounds
    up)."

    Design: Difficulty/combinatorial_formula/claim_remittance_rounds_patient_share_first_then_subtracts
    """
    sc = _setup_compliant_paid_ready(api, allowed_rate_cents=2750,
                                     coinsurance_pct=0.15, delivered_direct=5)
    claim = create_submitted_claim(api, sc["_direct"]["id"])
    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"decision": "PAY"},
                             TEST_USERS["billing_headers"]),
        200,
    )
    # allowed = 5 * 2750 = 13750; 13750 * 0.15 = 2062.5 rounds up to 2063.
    assert paid["allowed_cents"] == 13750, paid["allowed_cents"]
    assert paid["patient_responsibility_cents"] == 2063, (
        paid["patient_responsibility_cents"]
    )


def test_payer_paid_is_allowed_minus_patient_share(api):
    """PRD §2.8: "The rounding is applied to the patient's share, and the payer's
    share is then computed as the remainder, so the two always sum back to the
    allowed amount without drift."

    Design: Difficulty/combinatorial_formula/claim_remittance_rounds_patient_share_first_then_subtracts
    """
    sc = _setup_compliant_paid_ready(api, allowed_rate_cents=2750,
                                     coinsurance_pct=0.15, delivered_direct=5)
    claim = create_submitted_claim(api, sc["_direct"]["id"])
    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"decision": "PAY"},
                             TEST_USERS["billing_headers"]),
        200,
    )
    # payer_paid = 13750 - 2063 = 11687.
    assert paid["payer_paid_cents"] == 11687, paid["payer_paid_cents"]


# ─── Difficulty: money conservation allowed == patient + payer ───────────────

def test_remittance_money_split_values(api):
    """PRD §3.9: "`allowed_cents` is the session's `delivered_units` multiplied by
    the payer's `allowed_rate_cents`; `patient_responsibility_cents` is that
    allowed amount multiplied by the payer's `coinsurance_pct`, rounded half up to
    whole cents; and `payer_paid_cents` is the allowed amount minus the patient
    responsibility."

    Design: Difficulty/compensating_invariant/claim_money_conserved_allowed_equals_patient_plus_payer
    """
    sc = _setup_compliant_paid_ready(api, allowed_rate_cents=2800,
                                     coinsurance_pct=0.20, delivered_direct=7)
    claim = create_submitted_claim(api, sc["_direct"]["id"])
    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"decision": "PAY"},
                             TEST_USERS["billing_headers"]),
        200,
    )
    # allowed = 7 * 2800 = 19600; patient = 19600 * 0.20 = 3920; payer = 15680.
    assert paid["allowed_cents"] == 19600, paid["allowed_cents"]
    assert paid["patient_responsibility_cents"] == 3920
    assert paid["payer_paid_cents"] == 15680


def test_allowed_equals_patient_plus_payer_no_drift(api):
    """PRD §2.8: "The rounding is applied to the patient's share, and the payer's
    share is then computed as the remainder, so the two always sum back to the
    allowed amount without drift."

    Design: Difficulty/compensating_invariant/claim_money_conserved_allowed_equals_patient_plus_payer
    """
    sc = _setup_compliant_paid_ready(api, allowed_rate_cents=2800,
                                     coinsurance_pct=0.20, delivered_direct=7)
    claim = create_submitted_claim(api, sc["_direct"]["id"])
    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"decision": "PAY"},
                             TEST_USERS["billing_headers"]),
        200,
    )
    assert (paid["allowed_cents"]
            == paid["patient_responsibility_cents"] + paid["payer_paid_cents"]), (
        f"money drift: {paid['allowed_cents']} != "
        f"{paid['patient_responsibility_cents']} + {paid['payer_paid_cents']}"
    )


# ─── Difficulty: invalid-state beats supervision-deficient on adjudicate ─────

def test_adjudicate_draft_claim_returns_invalid_state(api):
    """PRD §3.10: "a request to drive a transition that the resource's current
    state does not permit is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_supervision_deficient_on_adjudicate
    """
    # Direct delivered but no supervision -> DEFICIENT; claim left in DRAFT.
    sc = setup_delivered_direct_session(api, scheduled_units=8, delivered_units=8,
                                        authorized_direct_units=100)
    claim = create_draft_claim(api, sc["session"]["id"])
    resp = api.adjudicate_claim(claim["id"], {"decision": "PAY"},
                                TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_draft_claim_authorization_is_supervision_deficient(api):
    """PRD §3.8: "If the authorization's `delivered_supervision_units` is greater
    than or equal to that required figure, the supervision status is `COMPLIANT`;
    otherwise it is `DEFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_supervision_deficient_on_adjudicate
    """
    sc = setup_delivered_direct_session(api, scheduled_units=8, delivered_units=8,
                                        authorized_direct_units=100)
    auth = get_authorization(api, sc["authorization"]["id"])
    # required = ceil(8 * 0.10) = 1, delivered supervision 0 < 1 -> DEFICIENT.
    assert auth["supervision_status"] == "DEFICIENT", auth["supervision_status"]
    claim = create_draft_claim(api, sc["session"]["id"])
    resp = api.adjudicate_claim(claim["id"], {"decision": "PAY"},
                                TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ─── Corner: supervision-line claim uses 4800 rate ───────────────────────────

def test_supervision_line_claim_bills_4800_per_unit(api):
    """PRD §3.9: "The billed figure is computed from a per-service-line rate:
    direct therapy bills at 3200 cents per unit, supervision at 4800 cents per
    unit, and parent training at 2400 cents per unit."

    Design: Corner/calculations/claim_billed_supervision_line_uses_4800_rate
    """
    sc = setup_active_authorization(api, authorized_supervision_units=20,
                                    assessment_score=130, with_rbt=False)
    bcba_id = sc["bcba"]["id"]
    sup = schedule_session(api, sc["authorization"]["id"], bcba_id, "BCBA",
                           service_line="SUPERVISION",
                           scheduled_start="2026-02-02T09:00:00Z",
                           scheduled_end="2026-02-02T10:00:00Z", scheduled_units=4)
    deliver_session(api, sup["id"], bcba_id, "BCBA", 4)
    claim = create_draft_claim(api, sup["id"])
    # 4 scheduled * 4800 = 19200 provisional.
    assert claim["billed_cents"] == 19200, claim["billed_cents"]
    submitted = get_success_data(
        api.submit_claim(claim["id"], TEST_USERS["billing_headers"])
    )
    # 4 delivered * 4800 = 19200 final (equal, delivered == scheduled).
    assert submitted["billed_cents"] == 19200, submitted["billed_cents"]


# ─── Corner: deny path zeroes money and sets reason ──────────────────────────

def test_deny_zeroes_money_and_sets_reason(api):
    """PRD §3.9: "A decision of `DENY` moves the claim from `SUBMITTED` to
    `DENIED`, sets the `denial_reason` from the body (one of `NONE`,
    `NOT_AUTHORIZED`, `SUPERVISION_DEFICIENT`, or `DUPLICATE`, where `NONE` is the
    default carried on a fresh claim), and zeroes the money fields so that
    `allowed_cents`, `patient_responsibility_cents`, and `payer_paid_cents` are
    all zero."

    Design: Corner/state_machines/claim_deny_path_zeroes_money_and_sets_reason
    """
    sc = setup_delivered_direct_session(api, scheduled_units=8, delivered_units=8,
                                        authorized_direct_units=100)
    claim = create_submitted_claim(api, sc["session"]["id"])
    denied = validate_success(
        api.adjudicate_claim(
            claim["id"], {"decision": "DENY", "denial_reason": "NOT_AUTHORIZED"},
            TEST_USERS["billing_headers"],
        ),
        200,
    )
    assert denied["status"] == "DENIED", denied["status"]
    assert denied["denial_reason"] == "NOT_AUTHORIZED"
    assert denied["allowed_cents"] == 0
    assert denied["patient_responsibility_cents"] == 0
    assert denied["payer_paid_cents"] == 0


# ─── Corner: duplicate claim rejected ────────────────────────────────────────

def test_duplicate_claim_for_submitted_session_rejected(api):
    """PRD §3.9: "if another claim for the same `session_id` already exists in a
    `SUBMITTED` or `PAID` state, both claim creation and claim submission are
    rejected with `ERR_DUPLICATE_CLAIM`".

    Design: Corner/validations/duplicate_claim_for_same_session_rejected
    """
    sc = setup_delivered_direct_session(api, scheduled_units=8, delivered_units=8,
                                        authorized_direct_units=100)
    create_submitted_claim(api, sc["session"]["id"])
    resp = api.create_claim(
        factories.create_claim_payload(sc["session"]["id"]),
        TEST_USERS["billing_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM.value, 409)


# ─── Corner: claim for undelivered session rejected ──────────────────────────

def test_claim_for_scheduled_session_rejected(api):
    """PRD §3.9: "the claim may only be created for a session whose status is
    `DELIVERED`, otherwise it is rejected with `ERR_SESSION_NOT_DELIVERED`."

    Design: Corner/validations/claim_for_undelivered_session_rejected
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    session = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                               "RBT", scheduled_units=8)
    resp = api.create_claim(
        factories.create_claim_payload(session["id"]),
        TEST_USERS["billing_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_DELIVERED.value, 409)
