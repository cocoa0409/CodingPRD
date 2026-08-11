"""Funding authorizations and claims: state gating, segregation of duties,
appeal cycle, exhaustion revival, sweep expiry, window boundaries, RBAC."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_client_payload, create_funding_authorization_payload, create_claim_payload,
    claim_line,
    create_client,
    create_approved_authorization, create_submitted_authorization, create_authorization,
    create_claim, create_submitted_claim,
    setup_allocated_purchase, setup_approved_funding_scenario,
    set_clock, run_daily,
    make_funding_coordinator_headers, make_payer_adjudicator_headers,
    make_billing_specialist_headers,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
SPECIALIST = TEST_USERS["vision_specialist_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def _setup_denied_auth_scenario(api):
    """Gus Ren scenario: allocated order + INSURANCE auth 100, submitted, DENIED;
    a claim with provisional 400 already created."""
    ctx = setup_allocated_purchase(category="MAGNIFIER")
    c, o = ctx["client"], ctx["order"]
    fa = get_success_data(api.create_funding_authorization(create_funding_authorization_payload(
        c["id"], payer_type="INSURANCE", payer_ref="POL-400", authorized_amount_cents=100),
        make_funding_coordinator_headers("fc-1")))
    get_success_data(api.submit_funding_authorization(fa["id"], make_funding_coordinator_headers("fc-1")))
    get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "DENY"}, make_payer_adjudicator_headers("pa-1")))
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 500, 1)]), BILLING))
    return c, o, fa, cl


def test_referential_error_beats_fiscal_on_claim_submit(api):
    """PRD §2.7: "8. **Cross-entity state guards** — referral accepted,
    evaluation finalized, order active, funding approved, loan returned".
    PRD §2.7: "11. **Fiscal sufficiency** — claim provisional total against
    remaining funding".
    PRD §2.7: "every request passes through a fixed validation funnel, and the
    **first** failing check determines the error returned".
    PRD §3.7: "The authorization must be `APPROVED`, else
    `ERR_FUNDING_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/pp_referential_beats_fiscal_on_claim_submit
    """
    c, o, fa, cl = _setup_denied_auth_scenario(api)
    assert cl["provisional_total_cents"] == 400, "provisional computable even on a DENIED authorization"
    resp = api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1"))
    # 400 > 100 remaining would also fail fiscal; referential (earlier) wins.
    validate_error(resp, ApiErrorId.ERR_FUNDING_NOT_APPROVED)


def test_rejected_submit_leaves_no_reservation(api):
    """PRD §3.7: "A successful submit moves the claim `DRAFT → SUBMITTED`,
    records `submitted_by_user_id`, and **subtracts** the provisional total from
    the authorization's `remaining_amount_cents` as a reservation."

    Design: Difficulty/priority_pair_validation_conflict/pp_referential_beats_fiscal_on_claim_submit
    """
    c, o, fa, cl = _setup_denied_auth_scenario(api)
    api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1"))
    claim = get_success_data(api.get_claim(cl["id"], BILLING))
    assert claim["status"] == "DRAFT"
    rem = get_success_data(api.get_funding_authorization(fa["id"], BILLING))["remaining_amount_cents"]
    assert rem == 100, "no reservation leaked by the rejected submit"


def _setup_submitted_auth_claim(api):
    """Luz Per scenario: allocated order + INSURANCE auth 50000 in SUBMITTED
    state + a DRAFT claim (provisional 1600)."""
    ctx = setup_allocated_purchase(category="MAGNIFIER")
    c, o = ctx["client"], ctx["order"]
    fa = get_success_data(api.create_funding_authorization(create_funding_authorization_payload(
        c["id"], payer_type="INSURANCE", payer_ref="POL-600", authorized_amount_cents=50000),
        make_funding_coordinator_headers("fc-1")))
    get_success_data(api.submit_funding_authorization(fa["id"], make_funding_coordinator_headers("fc-1")))
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 2000, 1)]), BILLING))
    return c, o, fa, cl


def test_claim_submit_rejected_before_authorization_approved(api):
    """PRD §3.7: "The authorization must be `APPROVED`, else
    `ERR_FUNDING_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/ce_claim_requires_approved_authorization
    """
    c, o, fa, cl = _setup_submitted_auth_claim(api)
    resp = api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1"))
    validate_error(resp, ApiErrorId.ERR_FUNDING_NOT_APPROVED)


def test_claim_submit_succeeds_after_adjudication(api):
    """PRD §3.7: "The authorization must be `APPROVED`, else
    `ERR_FUNDING_NOT_APPROVED`."
    PRD §3.7: "A successful submit moves the claim `DRAFT → SUBMITTED`, records
    `submitted_by_user_id`, and **subtracts** the provisional total from the
    authorization's `remaining_amount_cents` as a reservation."

    Design: Difficulty/cross_entity_state_dependency/ce_claim_requires_approved_authorization
    """
    c, o, fa, cl = _setup_submitted_auth_claim(api)
    assert cl["provisional_total_cents"] == 1600
    get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("pa-1")))
    submitted = get_success_data(api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    assert submitted["status"] == "SUBMITTED"
    rem = get_success_data(api.get_funding_authorization(fa["id"], BILLING))["remaining_amount_cents"]
    assert rem == 48400, f"50000 - 1600 = 48400, got {rem}"


def test_voided_claim_rejects_further_submit(api):
    """PRD §3.7: "`DENIED` and `VOIDED` are terminal for a claim."
    PRD §2.7: "the target entity is in a state from which the requested
    transition exists; terminal states reject everything (`ERR_INVALID_STATE`,
    or `ERR_PLAN_SUSPENDED` when scheduling onto a suspended or completed plan)".

    Design: Corner/state_machines/sm_claim_terminal_voided_lockdown
    """
    ctx = setup_approved_funding_scenario(payer_type="INSURANCE", authorized_amount_cents=50000)
    cl = create_submitted_claim(ctx["authorization"]["id"], ctx["order"]["id"],
                                lines=[claim_line("DEVICE", 1000, 1)])
    get_success_data(api.void_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    resp = api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_funding_appeal_cycle_reaches_approved(api):
    """PRD §3.7: "A denial is not final: the coordinator's appeal moves
    `DENIED → APPEALED`, and a fresh submit moves `APPEALED → SUBMITTED`,
    overwriting `submitted_by_user_id` with the resubmitting coordinator."

    Design: Corner/state_machines/sm_funding_appeal_cycle
    """
    c = create_client(full_name="Appeal Me")
    fa = get_success_data(api.create_funding_authorization(create_funding_authorization_payload(
        c["id"], payer_type="VR", payer_ref="VR-AP", authorized_amount_cents=9000),
        make_funding_coordinator_headers("fc-1")))
    get_success_data(api.submit_funding_authorization(fa["id"], make_funding_coordinator_headers("fc-1")))
    get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "DENY"}, make_payer_adjudicator_headers("pa-1")))
    appealed = get_success_data(api.appeal_funding_authorization(
        fa["id"], make_funding_coordinator_headers("fc-2")))
    assert appealed["status"] == "APPEALED"
    resub = get_success_data(api.submit_funding_authorization(
        fa["id"], make_funding_coordinator_headers("fc-2")))
    assert resub["status"] == "SUBMITTED"
    assert resub["submitted_by_user_id"] == "fc-2", "resubmission overwrites the submitter"
    approved = get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("pa-1")))
    assert approved["status"] == "APPROVED", "pa-1 != fc-2 so segregation passes"


def test_exhausted_authorization_revives_on_claim_void(api):
    """PRD §3.7: "Either way, if the authorization was `EXHAUSTED` and the
    compensation raises `remaining_amount_cents` above 0, the authorization
    revives `EXHAUSTED → APPROVED`."

    Design: Corner/state_machines/sm_exhausted_revives_on_claim_void
    """
    ctx = setup_approved_funding_scenario(payer_type="INSURANCE", authorized_amount_cents=2000)
    fa, o = ctx["authorization"], ctx["order"]
    cl = get_success_data(api.create_claim(create_claim_payload(
        fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 1000, 1)]), BILLING))
    get_success_data(api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    get_success_data(api.adjudicate_claim(
        cl["id"], {"decision": "PAY", "allowed_amount_cents": 3000},
        make_payer_adjudicator_headers("pa-1")))
    mid = get_success_data(api.get_funding_authorization(fa["id"], BILLING))
    assert mid["status"] == "EXHAUSTED" and mid["remaining_amount_cents"] == 0
    get_success_data(api.void_claim(cl["id"], make_billing_specialist_headers("bs-1")))
    end = get_success_data(api.get_funding_authorization(fa["id"], BILLING))
    assert end["status"] == "APPROVED"
    assert end["remaining_amount_cents"] == 2000, "payer_pays 2000 returned by the void"


def test_funding_expires_via_sweep_and_blocks_claims(api):
    """PRD §2.6: "A funding authorization in `APPROVED` whose `valid_until` is
    strictly before the current clock transitions `APPROVED → EXPIRED`."
    PRD §3.7: "The authorization must be `APPROVED`, else
    `ERR_FUNDING_NOT_APPROVED`."

    Design: Corner/state_machines/sm_funding_expired_via_run_daily
    """
    ctx = setup_approved_funding_scenario(
        payer_type="INSURANCE", authorized_amount_cents=50000,
        valid_from="2026-05-01T00:00:00Z", valid_until="2026-05-31T23:59:59Z")
    fa, o = ctx["authorization"], ctx["order"]
    set_clock("2026-06-01T00:00:00Z")
    sweep = run_daily()
    assert fa["id"] in sweep["expired_authorization_ids"]
    auth = get_success_data(api.get_funding_authorization(fa["id"], BILLING))
    assert auth["status"] == "EXPIRED"
    cl = create_claim(fa["id"], o["id"], service_date="2026-05-10T00:00:00Z",
                      lines=[claim_line("DEVICE", 1000, 1)])
    resp = api.submit_claim(cl["id"], make_billing_specialist_headers("bs-1"))
    validate_error(resp, ApiErrorId.ERR_FUNDING_NOT_APPROVED)


def test_funding_window_inclusive_at_valid_until(api):
    """PRD §3.7: "The `service_date` must lie within the inclusive window from
    `valid_from` to `valid_until`, else `ERR_FUNDING_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/val_funding_window_inclusive_boundary
    """
    ctx = setup_approved_funding_scenario(
        payer_type="INSURANCE", authorized_amount_cents=50000,
        valid_from="2026-05-01T00:00:00Z", valid_until="2026-05-31T23:59:59Z")
    fa, o = ctx["authorization"], ctx["order"]
    cl_ok = create_claim(fa["id"], o["id"], service_date="2026-05-31T23:59:59Z",
                         lines=[claim_line("DEVICE", 100, 1)])
    submitted = get_success_data(api.submit_claim(cl_ok["id"], make_billing_specialist_headers("bs-1")))
    assert submitted["status"] == "SUBMITTED", "service_date == valid_until is inside the inclusive window"


def test_funding_window_one_second_past_rejected(api):
    """PRD §3.7: "The `service_date` must lie within the inclusive window from
    `valid_from` to `valid_until`, else `ERR_FUNDING_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/val_funding_window_inclusive_boundary
    """
    ctx = setup_approved_funding_scenario(
        payer_type="INSURANCE", authorized_amount_cents=50000,
        valid_from="2026-05-01T00:00:00Z", valid_until="2026-05-31T23:59:59Z")
    fa, o = ctx["authorization"], ctx["order"]
    cl_bad = create_claim(fa["id"], o["id"], service_date="2026-06-01T00:00:00Z",
                          lines=[claim_line("DEVICE", 100, 1)])
    resp = api.submit_claim(cl_bad["id"], make_billing_specialist_headers("bs-1"))
    validate_error(resp, ApiErrorId.ERR_FUNDING_WINDOW_INVALID)


def test_segregation_funding_same_user_rejected(api):
    """PRD §2.8: "adjudication of either is performed by a `PayerAdjudicator`
    whose `X-User-ID` **must differ** from the recorded submitter. An
    adjudication attempted by the same operator who submitted is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/val_segregation_funding_adjudicate_same_user_rejected
    """
    c = create_client(full_name="Sod Fund")
    fa = create_submitted_authorization(c["id"], coordinator_id="fc-9",
                                        payer_type="VR", payer_ref="VR-SOD",
                                        authorized_amount_cents=9000)
    resp = api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("fc-9"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    ok = get_success_data(api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("pa-9")))
    assert ok["status"] == "APPROVED", "distinct adjudicator passes"


def test_segregation_claim_same_user_rejected(api):
    """PRD §2.8: "every Claim records `submitted_by_user_id` when it is
    submitted; adjudication of either is performed by a `PayerAdjudicator` whose
    `X-User-ID` **must differ** from the recorded submitter."

    Design: Corner/validations/val_segregation_claim_adjudicate_same_user_rejected
    """
    ctx = setup_approved_funding_scenario(payer_type="INSURANCE", authorized_amount_cents=50000)
    cl = create_submitted_claim(ctx["authorization"]["id"], ctx["order"]["id"],
                                billing_id="zz-1", lines=[claim_line("DEVICE", 1000, 1)])
    resp = api.adjudicate_claim(
        cl["id"], {"decision": "PAY", "allowed_amount_cents": 1000},
        make_payer_adjudicator_headers("zz-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    claim = get_success_data(api.get_claim(cl["id"], BILLING))
    assert claim["status"] == "SUBMITTED", "unchanged after the rejected adjudication"


def test_state_illegality_checked_before_segregation(api):
    """PRD §2.7: "6. **State legality** — the target entity is in a state from
    which the requested transition exists".
    PRD §2.7: "7. **Segregation of duties** — adjudicator differs from submitter".
    PRD §2.7: "every request passes through a fixed validation funnel, and the
    **first** failing check determines the error returned".

    Design: Corner/validations/val_state_checked_before_segregation
    """
    c = create_client(full_name="Prio Check")
    fa = create_authorization(c["id"], coordinator_id="fc-1", payer_type="VR",
                              payer_ref="VR-PC", authorized_amount_cents=9000)
    resp = api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers("fc-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE,
                   expected_status=409)


def test_adjudicate_forbidden_for_funding_coordinator(api):
    """PRD §4: "Payer decision on an authorization (segregation enforced) |
    PayerAdjudicator".
    PRD §2.1: "If the role is recognized but is not among the roles authorized
    for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/rbac_adjudicate_forbidden_for_coordinator
    """
    c = create_client(full_name="RBAC Adj")
    fa = create_submitted_authorization(c["id"], coordinator_id="fc-1",
                                        payer_type="VR", payer_ref="VR-RB",
                                        authorized_amount_cents=9000)
    resp = api.adjudicate_funding_authorization(
        fa["id"], {"decision": "APPROVE"}, make_funding_coordinator_headers("fc-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_claim_create_forbidden_for_vision_specialist(api):
    """PRD §4: "Create a claim with line items (`DRAFT`) | BillingSpecialist".
    PRD §2.1: "This authorization check runs before any business logic — a
    well-formed request from the wrong role never reaches a state machine."

    Design: Corner/rbac/rbac_claim_create_forbidden_for_specialist
    """
    resp = api.create_claim(create_claim_payload(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID,
        service_date="2026-05-10T00:00:00Z",
        lines=[claim_line("DEVICE", 100, 1)]), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
