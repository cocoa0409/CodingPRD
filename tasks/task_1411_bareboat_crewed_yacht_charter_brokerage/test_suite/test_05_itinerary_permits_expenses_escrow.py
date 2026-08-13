"""Itinerary legs, port permit containment and roll-up, clock-sweep permit
expiry, expense state gates and bucket caps, APA position, and auth/existence
pipeline checks."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_expense,
    add_itinerary_leg,
    add_port_permit,
    assert_escrow_movement,
    assert_expense_entry,
    create_client,
    create_expense_payload,
    create_itinerary_leg_payload,
    create_operator,
    create_port_permit_payload,
    decide_permit,
    fund_tranche,
    get_agreement_escrow,
    list_movements,
    make_central_agent_headers,
    make_client_headers,
    review_expense,
    set_clock,
    setup_accepted_agreement,
    setup_fully_funded_agreement,
    setup_in_prep_agreement,
    setup_signed_agreement,
    sign_both,
    TEST_USERS,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_start_prep_blocked_by_denied_permit(api):
    """PRD section 3.7: "Starting preparation moves the agreement from
    `SIGNED` to `IN_PREP` and is gated in a fixed order: the caller must own
    the yacht (`ERR_FORBIDDEN` otherwise); every itinerary leg of the
    agreement must be `PERMITTED` — a single leg still `PLANNED`, whether for
    want of any permit or because a permit is still `REQUESTED`, was `DENIED`,
    or has `EXPIRED`, fails the gate with `ERR_PERMIT_NOT_GRANTED`; and the
    funds axis must be `FULLY_FUNDED`, else `ERR_ESCROW_INSUFFICIENT`."

    Design: Difficulty/cross_entity_state_dependency/start_prep_gated_by_permits
    """
    ctx = setup_fully_funded_agreement(start_date="2026-11-02",
                                       end_date="2026-11-12")
    leg = add_itinerary_leg(ctx.agreement["id"], ctx.central_agent["id"],
                            port_name="Mykonos", arrival_date="2026-11-03",
                            departure_date="2026-11-05")
    permit = add_port_permit(leg["id"], ctx.central_agent["id"],
                             port_authority_ref="PA-1",
                             valid_from="2026-11-01", valid_until="2026-11-06")
    denied = decide_permit(permit["id"], "DENIED")
    assert denied["status"] == "DENIED"

    # The funds gate is already satisfied, so only the permit dependency can fire.
    res = api.start_prep(ctx.agreement["id"], ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_PERMIT_NOT_GRANTED, expected_status=422)

    leg_after = validate_success(api.get_itinerary_leg(leg["id"], ctx.ca_headers),
                                 200)
    assert leg_after["status"] == "PLANNED", (
        "DENIED permits neither qualify nor block; with zero GRANTED permits "
        "the leg stays PLANNED")


def test_start_prep_unblocked_after_resubmit_and_grant(api):
    """PRD section 3.6: "A denied permit is not dead: the central agent may
    resubmit it with a fresh `valid_from` and `valid_until`, returning it from
    `DENIED` to `REQUESTED`."
    PRD section 3.6: "The leg's own status is a pure roll-up of its permits,
    re-evaluated whenever one of them changes. A leg is `PERMITTED` exactly
    when it has at least one `GRANTED` permit and zero `REQUESTED` permits;
    `DENIED` and `EXPIRED` permits neither qualify nor block."

    Design: Difficulty/cross_entity_state_dependency/start_prep_gated_by_permits
    """
    ctx = setup_fully_funded_agreement(start_date="2026-11-02",
                                       end_date="2026-11-12")
    leg = add_itinerary_leg(ctx.agreement["id"], ctx.central_agent["id"],
                            port_name="Mykonos", arrival_date="2026-11-03",
                            departure_date="2026-11-05")
    permit = add_port_permit(leg["id"], ctx.central_agent["id"],
                             port_authority_ref="PA-1",
                             valid_from="2026-11-01", valid_until="2026-11-06")
    decide_permit(permit["id"], "DENIED")

    resubmitted = validate_success(
        api.resubmit_port_permit(permit["id"],
                                 {"valid_from": "2026-11-01",
                                  "valid_until": "2026-11-06"},
                                 ctx.ca_headers),
        200)
    assert resubmitted["status"] == "REQUESTED"

    granted = decide_permit(permit["id"], "GRANTED")
    assert granted["status"] == "GRANTED"

    leg_after = validate_success(api.get_itinerary_leg(leg["id"], ctx.ca_headers),
                                 200)
    assert leg_after["status"] == "PERMITTED", (
        "one GRANTED permit and zero REQUESTED permits flip the leg")

    in_prep = validate_success(
        api.start_prep(ctx.agreement["id"], ctx.op_headers), 200)
    assert in_prep["status"] == "IN_PREP"


def test_permit_grant_short_window_rejected_exact_containment_granted(api):
    """PRD section 3.6: "A `PlatformAdmin` decides the application: a grant is
    containment-validated — the permit's closed window must contain the leg's
    closed window, `valid_from` on or before the leg's `arrival_date` and
    `valid_until` on or after its `departure_date`, else
    `ERR_PERMIT_WINDOW_INSUFFICIENT` — while a denial needs no such check."

    Design: Difficulty/resource_temporal_overlap/permit_window_closed_containment
    """
    ctx = setup_accepted_agreement(start_date="2026-11-02", end_date="2026-11-12")
    leg = add_itinerary_leg(ctx.agreement["id"], ctx.central_agent["id"],
                            port_name="Mykonos", arrival_date="2026-11-03",
                            departure_date="2026-11-05")

    short = add_port_permit(leg["id"], ctx.central_agent["id"],
                            port_authority_ref="PA-SHORT",
                            valid_from="2026-11-03", valid_until="2026-11-04")
    res = api.decide_port_permit(short["id"], {"outcome": "GRANTED"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_PERMIT_WINDOW_INSUFFICIENT,
                   expected_status=422)
    permits, _ = validate_paginated(
        api.list_port_permits(leg["id"], ctx.ca_headers))
    assert len(permits) == 1 and permits[0]["status"] == "REQUESTED", (
        "the failed grant leaves the permit in REQUESTED")

    exact = add_port_permit(leg["id"], ctx.central_agent["id"],
                            port_authority_ref="PA-EXACT",
                            valid_from="2026-11-03", valid_until="2026-11-05")
    granted = decide_permit(exact["id"], "GRANTED")
    assert granted["status"] == "GRANTED", (
        "exact closed containment (valid_from == arrival, valid_until == "
        "departure) is sufficient")


def test_leg_permitted_only_after_requested_permit_resolved(api):
    """PRD section 3.6: "The leg's own status is a pure roll-up of its
    permits, re-evaluated whenever one of them changes. A leg is `PERMITTED`
    exactly when it has at least one `GRANTED` permit and zero `REQUESTED`
    permits; `DENIED` and `EXPIRED` permits neither qualify nor block."

    Design: Difficulty/resource_temporal_overlap/permit_window_closed_containment
    """
    ctx = setup_accepted_agreement(start_date="2026-11-02", end_date="2026-11-12")
    leg = add_itinerary_leg(ctx.agreement["id"], ctx.central_agent["id"],
                            port_name="Mykonos", arrival_date="2026-11-03",
                            departure_date="2026-11-05")
    pending = add_port_permit(leg["id"], ctx.central_agent["id"],
                              port_authority_ref="PA-SHORT",
                              valid_from="2026-11-03", valid_until="2026-11-04")
    exact = add_port_permit(leg["id"], ctx.central_agent["id"],
                            port_authority_ref="PA-EXACT",
                            valid_from="2026-11-03", valid_until="2026-11-05")
    decide_permit(exact["id"], "GRANTED")

    leg_mid = validate_success(api.get_itinerary_leg(leg["id"], ctx.ca_headers),
                               200)
    assert leg_mid["status"] == "PLANNED", (
        "a REQUESTED permit still blocks the roll-up even with one GRANTED")

    decide_permit(pending["id"], "DENIED")
    leg_end = validate_success(api.get_itinerary_leg(leg["id"], ctx.ca_headers),
                               200)
    assert leg_end["status"] == "PERMITTED", (
        "after the REQUESTED permit is DENIED: one GRANTED, zero REQUESTED")


def test_leg_seq_assignment_and_window_validation(api):
    """PRD section 3.6: "Appending a leg is allowed while the agreement is in
    `PENDING_SIGNATURES`, `SIGNED`, or `IN_PREP`, and takes a `port_name`, an
    `arrival_date`, and a `departure_date`; the server assigns `seq_no` as one
    plus the count of legs the agreement already has, and the leg starts
    `PLANNED`. The leg's dates must sit inside the charter window on closed
    bounds — arrival on or after the agreement's `start_date`, departure on or
    after arrival and on or before the agreement's `end_date` — or the append
    is rejected with `ERR_LEG_OUTSIDE_CHARTER_WINDOW`."

    Design: Corner/state_machines/leg_seq_assignment_and_window_validation
    """
    ctx = setup_accepted_agreement(start_date="2026-11-02", end_date="2026-11-12")
    ag = ctx.agreement

    res = api.create_itinerary_leg(
        ag["id"],
        create_itinerary_leg_payload(port_name="Too Early",
                                     arrival_date="2026-11-01",
                                     departure_date="2026-11-03"),
        ctx.ca_headers)
    validate_error(res, ApiErrorId.ERR_LEG_OUTSIDE_CHARTER_WINDOW,
                   expected_status=422)

    leg1 = add_itinerary_leg(ag["id"], ctx.central_agent["id"],
                             port_name="Mykonos", arrival_date="2026-11-03",
                             departure_date="2026-11-05")
    assert leg1["seq_no"] == 1
    assert leg1["status"] == "PLANNED"

    leg2 = add_itinerary_leg(ag["id"], ctx.central_agent["id"],
                             port_name="Santorini", arrival_date="2026-11-06",
                             departure_date="2026-11-08")
    assert leg2["seq_no"] == 2, (
        "the rejected append consumed no sequence number: seq_no is one plus "
        "the count of legs the agreement already has")


def test_permit_expiry_clock_sweep_demotes_leg(api):
    """PRD section 2.5: "Setting the clock triggers one eager sweep: every
    port permit in `GRANTED` status whose `valid_until` date is earlier than
    the new clock date transitions to `EXPIRED`, and each affected itinerary
    leg re-evaluates its permit roll-up (section 3.6), which can flip a leg
    from `PERMITTED` back to `PLANNED`."

    Design: Corner/state_machines/permit_expiry_clock_sweep_demotes_leg
    """
    ctx = setup_fully_funded_agreement(start_date="2026-11-02",
                                       end_date="2026-11-12")
    leg = add_itinerary_leg(ctx.agreement["id"], ctx.central_agent["id"],
                            port_name="Mykonos", arrival_date="2026-11-03",
                            departure_date="2026-11-05")
    permit = add_port_permit(leg["id"], ctx.central_agent["id"],
                             port_authority_ref="PA-1",
                             valid_from="2026-11-01", valid_until="2026-11-06")
    decide_permit(permit["id"], "GRANTED")
    leg_now = validate_success(api.get_itinerary_leg(leg["id"], ctx.ca_headers),
                               200)
    assert leg_now["status"] == "PERMITTED"

    set_clock("2026-11-07T00:00:00Z")  # past valid_until 2026-11-06

    permits, _ = validate_paginated(api.list_port_permits(leg["id"], ctx.ca_headers))
    assert permits[0]["status"] == "EXPIRED", (
        "the clock sweep expires a GRANTED permit once the clock passes "
        "valid_until")

    leg_after = validate_success(api.get_itinerary_leg(leg["id"], ctx.ca_headers),
                                 200)
    assert leg_after["status"] == "PLANNED", "the roll-up demotes the leg"

    res = api.start_prep(ctx.agreement["id"], ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_PERMIT_NOT_GRANTED, expected_status=422)


def test_start_prep_permit_gate_precedes_funding_gate(api):
    """PRD section 3.7: "Starting preparation moves the agreement from
    `SIGNED` to `IN_PREP` and is gated in a fixed order: the caller must own
    the yacht (`ERR_FORBIDDEN` otherwise); every itinerary leg of the
    agreement must be `PERMITTED` — a single leg still `PLANNED`, whether for
    want of any permit or because a permit is still `REQUESTED`, was `DENIED`,
    or has `EXPIRED`, fails the gate with `ERR_PERMIT_NOT_GRANTED`; and the
    funds axis must be `FULLY_FUNDED`, else `ERR_ESCROW_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_start_prep
    """
    ctx = setup_signed_agreement(start_date="2026-10-30", end_date="2026-11-19")
    ag = ctx.agreement
    fund_tranche(ag["id"], "SIGNING", ag["signing_due_cents"], ctx.client["id"])
    add_itinerary_leg(ag["id"], ctx.central_agent["id"],
                      port_name="Mykonos", arrival_date="2026-11-02",
                      departure_date="2026-11-04")  # no permit at all

    # Both the permit gate (leg PLANNED) and the funding gate (DEPOSIT_HELD)
    # are violated; the fixed gate order puts the permit gate first.
    res = api.start_prep(ag["id"], ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_PERMIT_NOT_GRANTED, expected_status=422)


def test_rejected_start_prep_leaves_axes_unchanged(api):
    """PRD section 3.7: "Starting preparation moves the agreement from
    `SIGNED` to `IN_PREP` and is gated in a fixed order: the caller must own
    the yacht (`ERR_FORBIDDEN` otherwise); every itinerary leg of the
    agreement must be `PERMITTED` — a single leg still `PLANNED`, whether for
    want of any permit or because a permit is still `REQUESTED`, was `DENIED`,
    or has `EXPIRED`, fails the gate with `ERR_PERMIT_NOT_GRANTED`; and the
    funds axis must be `FULLY_FUNDED`, else `ERR_ESCROW_INSUFFICIENT`."
    PRD section 2.9: "Consistency in this system is immediate: every mutation
    is fully applied before its response is rendered, so the response body and
    any subsequent read reflect the change."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_start_prep
    """
    ctx = setup_signed_agreement(start_date="2026-10-30", end_date="2026-11-19")
    ag = ctx.agreement
    fund_tranche(ag["id"], "SIGNING", ag["signing_due_cents"], ctx.client["id"])
    add_itinerary_leg(ag["id"], ctx.central_agent["id"],
                      port_name="Mykonos", arrival_date="2026-11-02",
                      departure_date="2026-11-04")

    validate_error(api.start_prep(ag["id"], ctx.op_headers),
                   ApiErrorId.ERR_PERMIT_NOT_GRANTED, expected_status=422)
    after = validate_success(api.get_charter_agreement(ag["id"], ctx.cl_headers),
                             200)
    assert after["status"] == "SIGNED"
    assert after["funds_status"] == "DEPOSIT_HELD", (
        "a rejected start-prep mutates neither axis")


def test_expense_creation_state_gate(api):
    """PRD section 3.7: "While the agreement is in `IN_PREP` or `UNDERWAY`,
    the operator records spend against it: provisioning drawdowns as expenses
    in the `APA` bucket and damage claims in the `DAMAGE_CLAIM` bucket, each
    with a `description` and a positive `amount_cents`, linked to the
    agreement and starting life `PENDING`. An expense recorded outside those
    two states finds no transition and is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/expense_creation_state_gate
    """
    ctx = setup_signed_agreement(start_date="2026-11-02", end_date="2026-11-12")
    res = api.create_expense(
        ctx.agreement["id"],
        create_expense_payload(bucket="APA", description="early provisioning",
                               amount_cents=10000),
        ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    expenses, meta = validate_paginated(
        api.list_expenses(ctx.agreement["id"], ctx.op_headers))
    assert meta["total_count"] == 0 and expenses == []


def test_apa_cap_and_deposit_cap_enforced_on_approve(api):
    """PRD section 3.7: "The client side reviews each pending entry with an
    `outcome`: approval requires the agreement to be in `IN_PREP` or
    `UNDERWAY` (else `ERR_INVALID_STATE`) and is capped against the matching
    escrow bucket — approving an `APA` expense must not push the total of
    already-approved APA expenses plus this amount beyond `held_apa_cents`
    (`ERR_ESCROW_INSUFFICIENT`), and approving a `DAMAGE_CLAIM` must not push
    the approved damage total beyond `held_deposit_cents`
    (`ERR_DEPOSIT_CLAIM_EXCEEDS_HELD`) — while rejection needs no such check."

    Design: Corner/state_machines/apa_cap_and_deposit_cap_enforced_on_approve
    """
    # Yacht A 10-day: fee 1000000 -> apa 0.30 -> held APA 300000; deposit 500000.
    ctx = setup_in_prep_agreement(start_date="2026-11-02", end_date="2026-11-12")
    ag = ctx.agreement

    e1 = add_expense(ag["id"], ctx.operator["id"], bucket="APA",
                     description="e1", amount_cents=200000)
    e2 = add_expense(ag["id"], ctx.operator["id"], bucket="APA",
                     description="e2", amount_cents=150000)
    d1 = add_expense(ag["id"], ctx.operator["id"], bucket="DAMAGE_CLAIM",
                     description="d1", amount_cents=400000)
    d2 = add_expense(ag["id"], ctx.operator["id"], bucket="DAMAGE_CLAIM",
                     description="d2", amount_cents=200000)

    approved = review_expense(e1["id"], "APPROVED", ctx.client["id"])
    assert approved["status"] == "APPROVED"  # 200000 <= 300000

    res = api.review_expense(e2["id"], {"outcome": "APPROVED"}, ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_ESCROW_INSUFFICIENT, expected_status=422)
    # 200000 + 150000 > held_apa 300000; the crossing approval fails.

    approved = review_expense(d1["id"], "APPROVED", ctx.client["id"])
    assert approved["status"] == "APPROVED"  # 400000 <= 500000

    res = api.review_expense(d2["id"], {"outcome": "APPROVED"}, ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_DEPOSIT_CLAIM_EXCEEDS_HELD,
                   expected_status=422)
    # 400000 + 200000 > held_deposit 500000.

    expenses, _ = validate_paginated(api.list_expenses(ag["id"], ctx.op_headers))
    by_id = {e["id"]: e for e in expenses}
    assert by_id[e2["id"]]["status"] == "PENDING"
    assert by_id[d2["id"]]["status"] == "PENDING", (
        "rejected approvals leave the expenses PENDING")


def test_embark_and_complete_date_gates(api):
    """PRD section 3.7: "Embarkation then moves `IN_PREP` to `UNDERWAY`, but
    only once the logical clock date has reached the charter's `start_date`;
    earlier is `ERR_INVALID_REQUEST`."
    PRD section 3.8: "When the charter has run its course, the operator or the
    central agent completes it — but only once the logical clock date has
    reached the agreement's `end_date`, else `ERR_INVALID_REQUEST`, and only a
    caller who owns the yacht or is the central agent, else `ERR_FORBIDDEN`."

    Design: Corner/state_machines/embark_and_complete_date_gates
    """
    ctx = setup_in_prep_agreement(start_date="2026-11-02", end_date="2026-11-12")
    ag = ctx.agreement

    # Clock is still the startup default 2026-08-01T00:00:00Z (< start_date).
    res = api.embark(ag["id"], ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    set_clock("2026-11-02T00:00:00Z")  # exactly start_date: "has reached" passes
    underway = validate_success(api.embark(ag["id"], ctx.op_headers), 200)
    assert underway["status"] == "UNDERWAY"

    res = api.complete(ag["id"], ctx.op_headers)  # clock 11-02 < end 11-12
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_apa_provisional_counts_pending_and_approved(api):
    """PRD section 3.7: "The view returns `held_apa_cents` straight from the
    escrow. The provisional variant, a forward-looking projection of committed
    spend, reports `provisional_apa_committed_cents` as the sum of the
    agreement's APA expenses in `PENDING` or `APPROVED` — `DISPUTED` and
    `REJECTED` are excluded — and `projected_apa_return_cents` as the held APA
    minus that committed sum."

    Design: Difficulty/dual_variant_calc/apa_provisional_vs_final_position
    """
    # Yacht A 10-day: fee 1000000 -> apa 0.30 -> held APA 300000.
    ctx = setup_in_prep_agreement(start_date="2026-11-02", end_date="2026-11-12")
    ag = ctx.agreement

    e1 = add_expense(ag["id"], ctx.operator["id"], bucket="APA",
                     description="provisioning", amount_cents=120000)
    review_expense(e1["id"], "APPROVED", ctx.client["id"])
    add_expense(ag["id"], ctx.operator["id"], bucket="APA",
                description="fuel estimate", amount_cents=45000)  # stays PENDING
    e3 = add_expense(ag["id"], ctx.operator["id"], bucket="APA",
                     description="mooring", amount_cents=30000)
    review_expense(e3["id"], "APPROVED", ctx.client["id"])
    disputed = validate_success(
        api.dispute_expense(e3["id"], ctx.cl_headers), 200)
    assert disputed["status"] == "DISPUTED"

    position = validate_success(api.get_apa_position(ag["id"], ctx.cl_headers), 200)
    assert position["held_apa_cents"] == 300000
    # 120000 APPROVED + 45000 PENDING; the 30000 DISPUTED entry is excluded.
    assert position["provisional_apa_committed_cents"] == 165000
    assert position["projected_apa_return_cents"] == 135000


def test_apa_final_counts_approved_only(api):
    """PRD section 3.7: "The final variant, the settlement basis used at
    completion, counts approved spend only: `final_apa_spent_cents` sums the
    agreement's `APPROVED` APA expenses, and `final_apa_return_cents` is the
    held APA minus that sum. Because the provisional variant admits pending
    expenses and the final does not, any pending expense makes the committed
    total strictly greater and the projected return strictly smaller than
    their final counterparts."

    Design: Difficulty/dual_variant_calc/apa_provisional_vs_final_position
    """
    ctx = setup_in_prep_agreement(start_date="2026-11-02", end_date="2026-11-12")
    ag = ctx.agreement

    e1 = add_expense(ag["id"], ctx.operator["id"], bucket="APA",
                     description="provisioning", amount_cents=120000)
    review_expense(e1["id"], "APPROVED", ctx.client["id"])
    add_expense(ag["id"], ctx.operator["id"], bucket="APA",
                description="fuel estimate", amount_cents=45000)  # PENDING
    e3 = add_expense(ag["id"], ctx.operator["id"], bucket="APA",
                     description="mooring", amount_cents=30000)
    review_expense(e3["id"], "APPROVED", ctx.client["id"])
    validate_success(api.dispute_expense(e3["id"], ctx.cl_headers), 200)

    position = validate_success(api.get_apa_position(ag["id"], ctx.cl_headers), 200)
    assert position["final_apa_spent_cents"] == 120000, (
        "FINAL counts APPROVED only; PENDING and DISPUTED are excluded")
    assert position["final_apa_return_cents"] == 180000
    assert position["provisional_apa_committed_cents"] > position["final_apa_spent_cents"]
    assert position["projected_apa_return_cents"] < position["final_apa_return_cents"]


def test_apa_position_empty_expense_set(api):
    """PRD section 3.7: "The view returns `held_apa_cents` straight from the
    escrow. The provisional variant, a forward-looking projection of committed
    spend, reports `provisional_apa_committed_cents` as the sum of the
    agreement's APA expenses in `PENDING` or `APPROVED` — `DISPUTED` and
    `REJECTED` are excluded — and `projected_apa_return_cents` as the held APA
    minus that committed sum. The final variant, the settlement basis used at
    completion, counts approved spend only: `final_apa_spent_cents` sums the
    agreement's `APPROVED` APA expenses, and `final_apa_return_cents` is the
    held APA minus that sum."

    Design: Corner/calculations/apa_position_empty_expense_set
    """
    ctx = setup_in_prep_agreement(start_date="2026-11-02", end_date="2026-11-12")
    position = validate_success(
        api.get_apa_position(ctx.agreement["id"], ctx.cl_headers), 200)
    assert position["held_apa_cents"] == 300000
    assert position["provisional_apa_committed_cents"] == 0
    assert position["final_apa_spent_cents"] == 0
    assert position["projected_apa_return_cents"] == 300000
    assert position["final_apa_return_cents"] == 300000, (
        "with an empty expense set the full held APA is the return in both "
        "variants — no null leakage")


def test_escrow_movement_immutability(api):
    """PRD section 2.4: "Two ledger-style resources are deliberately slimmer.
    An `EscrowMovement` and a `CommissionStatement` each carry only `id` and
    `created_at`: both `updated_at` and `version` are absent, because
    movements and statements are posted once and never modified afterward."
    PRD section 3.5: "The signing tranche posts a `CLIENT_FUND` against the
    `CHARTER_FEE` bucket for the signing charter part — half the fee, rounded
    half-up — and a `CLIENT_FUND` against the `DEPOSIT` bucket for the full
    security deposit, and moves the funds axis from `UNFUNDED` to
    `DEPOSIT_HELD`."

    Design: Corner/entities/escrow_movement_immutability
    """
    # 20-day charter: fee 2000000 -> signing charter part 1000000, deposit 500000.
    ctx = setup_signed_agreement(start_date="2026-10-30", end_date="2026-11-19")
    escrow = fund_tranche(ctx.agreement["id"], "SIGNING", 1500000,
                          ctx.client["id"])

    movements = list_movements(escrow["id"], headers=ctx.cl_headers)
    assert len(movements) == 2, "the signing tranche posts two CLIENT_FUND movements"
    by_bucket = {mv["bucket"]: mv for mv in movements}
    assert set(by_bucket) == {"CHARTER_FEE", "DEPOSIT"}
    assert by_bucket["CHARTER_FEE"]["amount_cents"] == 1000000
    assert by_bucket["DEPOSIT"]["amount_cents"] == 500000
    for mv in movements:
        assert mv["movement_type"] == "CLIENT_FUND"
        assert mv["escrow_account_id"] == escrow["id"]
        assert_escrow_movement(mv)  # pins id/created_at present, no version/updated_at


def test_unauthenticated_missing_headers(api):
    """PRD section 2.1: "A request that is missing either header, carries a
    role string outside the five declared roles, presents an entity-backed
    `X-User-ID` that references no existing entity of the declared type, or
    presents a broker whose `broker_type` does not admit the declared role is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD section 2.11: "Every request is validated in a fixed category
    pipeline, and an earlier failure masks all later checks."

    Design: Corner/validations/unauthenticated_missing_headers
    """
    # No X-User-Role / X-User-ID at all: auth fires even for a nonexistent id.
    res = api.get_yacht(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_not_found_precedes_business_rules(api):
    """PRD section 2.9: "Where an endpoint path nests one resource under
    another (for example a yacht's availability blocks or an agreement's
    expenses), identifiers in the path are validated strictly left to right:
    the first identifier that does not resolve to an existing resource rejects
    the request with `ERR_NOT_FOUND` (HTTP 404), and body-level foreign keys
    such as `yacht_id`, `client_id`, `listing_central_agent_id`, and
    `retail_broker_id` are likewise checked for existence before business
    rules run."

    Design: Corner/validations/not_found_precedes_business_rules
    """
    client = create_client()
    res = api.cancel(NON_EXISTENT_UUID, {"reason": "x"},
                     make_client_headers(client["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
