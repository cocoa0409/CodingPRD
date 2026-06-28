"""State-machine workflows and transitive cascades.

Covers the service-ticket revision cycle, the coverage-claim fork-join, the depth-3
return-inspect cascade, the depth-3 theft write-off cascade, and the cross-entity
state dependencies (rental gated by delivery completion and by ticket closure).
"""
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    make_subscriber_headers,
    make_field_tech_headers,
    make_ops_admin_headers,
    setup_resolved_ticket,
    setup_under_review_claim,
    inspect_payload,
)
from test_helpers.fixtures import (
    set_clock, create_model, add_bikes, create_account, read_model_version,
    reserve, schedule_and_complete_initial_delivery, activate,
)

OPS = make_ops_admin_headers()
TECH = make_field_tech_headers()


# ===========================================================================
# Difficulty/non_linear_state_machine/service_ticket_resolve_reopen_cycle
# ===========================================================================
def test_service_ticket_reopen_returns_to_reopened(api):
    """PRD §3.5: "A holding Subscriber or FleetManager may reopen a RESOLVED ticket back
    to REOPENED, forming a revision loop, after which a FieldTech may start it again into
    IN_PROGRESS."

    From RESOLVED, reopen sets status REOPENED.

    Design: Difficulty/non_linear_state_machine/service_ticket_resolve_reopen_cycle
    """
    bundle = setup_resolved_ticket(severity="MINOR", issue_type="BRAKE")
    ctx, ticket = bundle["ctx"], bundle["ticket"]
    sub = make_subscriber_headers(ctx["account"]["id"])
    resp = api_client.reopen_service_ticket(ticket["id"], sub)
    data = validate_success(resp, 200)
    assert data["status"] == "REOPENED"


def test_service_ticket_reopen_then_start_reenters_in_progress(api):
    """PRD §3.5: "starting it advances an OPEN or REOPENED ticket to IN_PROGRESS".

    After reopen (status REOPENED), starting re-enters the IN_PROGRESS state, closing
    the revision cycle.

    Design: Difficulty/non_linear_state_machine/service_ticket_resolve_reopen_cycle
    """
    bundle = setup_resolved_ticket(severity="MINOR", issue_type="BRAKE")
    ctx, ticket = bundle["ctx"], bundle["ticket"]
    sub = make_subscriber_headers(ctx["account"]["id"])
    get_success_data(api_client.reopen_service_ticket(ticket["id"], sub))
    resp = api_client.start_service_ticket(ticket["id"], TECH)
    data = validate_success(resp, 200)
    assert data["status"] == "IN_PROGRESS"


# ===========================================================================
# Difficulty/non_linear_state_machine/coverage_claim_fork_join_branches
# ===========================================================================
def test_coverage_claim_approved_branch_records_payout(api):
    """PRD §3.10: "On a valid approval the claim's approved_payout_cents is recorded and
    its status becomes APPROVED."
    PRD §3.10: "for a DAMAGE claim, the approved payout is credited to the account's
    wallet_credit_cents only, with no rental cascade".

    A DAMAGE claim approved with 18000 -> status APPROVED, approved_payout_cents 18000,
    and the rental stays ACTIVE.

    Design: Difficulty/non_linear_state_machine/coverage_claim_fork_join_branches
    """
    bundle = setup_under_review_claim(claim_type="DAMAGE", claimed_amount_cents=20000,
                                      rental_mode="MONTHLY",
                                      return_due_clock="2027-06-01T00:00:00Z")
    ctx, claim = bundle["ctx"], bundle["claim"]
    resp = api_client.approve_coverage_claim(claim["id"], {"approved_payout_cents": 18000}, OPS)
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED"
    assert data["approved_payout_cents"] == 18000
    sub = make_subscriber_headers(ctx["account"]["id"])
    rental = get_success_data(api_client.get_rental(ctx["rental"]["id"], sub))
    assert rental["lifecycle_status"] == "ACTIVE", "DAMAGE approval does not cancel the rental"


def test_coverage_claim_denied_branch_zero_payout(api):
    """PRD §3.10: "Denying a claim, by contrast, requires only that it be UNDER_REVIEW,
    sets its approved_payout_cents to 0, moves it to DENIED, and produces no payout and
    no rental cascade."

    A DAMAGE claim denied -> status DENIED, approved_payout_cents 0.

    Design: Difficulty/non_linear_state_machine/coverage_claim_fork_join_branches
    """
    bundle = setup_under_review_claim(claim_type="DAMAGE", claimed_amount_cents=20000,
                                      rental_mode="MONTHLY",
                                      return_due_clock="2027-06-01T00:00:00Z")
    claim = bundle["claim"]
    resp = api_client.deny_coverage_claim(claim["id"], OPS)
    data = validate_success(resp, 200)
    assert data["status"] == "DENIED"
    assert data["approved_payout_cents"] == 0


# ===========================================================================
# Difficulty/transitive_cascade/return_inspect_cascade_depth3
# ===========================================================================
def test_return_inspect_cascade_releases_bike_and_reconciles_model(api):
    """PRD §3.6: "Second, the bike returns from OUT to AVAILABLE and its
    current_rental_id is cleared. Third, the model's available_count is reconciled."
    PRD §3.9: "The remainder of the deposit is refunded to the wallet:
    deposit_refund_cents is the greater of zero and the deposit minus
    total_assessed_cents."

    On-time GOOD return with deposit 20000: deposit_refund 20000, bike AVAILABLE,
    model available_count back to 1.

    Design: Difficulty/transitive_cascade/return_inspect_cascade_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=20000, fleet_size=5)
    bikes = add_bikes(model["id"], 1)
    bike_id = bikes[0]["id"]
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-12T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "1 A St"}, sub))
    set_clock("2026-06-11T00:00:00Z")
    insp = get_success_data(api_client.inspect_rental(rental["id"], inspect_payload(), TECH))
    assert insp["deposit_refund_cents"] == 20000, "hop1: full deposit refund on GOOD on-time"
    bike = get_success_data(api_client.get_bike(bike_id, OPS))
    assert bike["bike_status"] == "AVAILABLE", "hop2: bike released by settlement"
    model_after = get_success_data(api_client.get_bike_model(model["id"], sub))
    assert model_after["available_count"] == 1, "hop3: model reconcile from bike release"


def test_return_inspect_settles_billing_and_returns_rental(api):
    """PRD §3.6: "sets billing_status to SETTLED ... The rental's lifecycle_status becomes
    RETURNED and its version increments."

    The inspect transition settles billing_status to SETTLED and moves lifecycle_status
    to RETURNED — the head of the depth-3 cascade.

    Design: Difficulty/transitive_cascade/return_inspect_cascade_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=20000, fleet_size=5)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-12T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "1 A St"}, sub))
    set_clock("2026-06-11T00:00:00Z")
    get_success_data(api_client.inspect_rental(rental["id"], inspect_payload(), TECH))
    rental_after = get_success_data(api_client.get_rental(rental["id"], sub))
    assert rental_after["lifecycle_status"] == "RETURNED"
    assert rental_after["billing_status"] == "SETTLED"


# ===========================================================================
# Difficulty/transitive_cascade/theft_claim_cascade_depth3
# ===========================================================================
def test_theft_claim_approval_writes_off_rental(api):
    """PRD §3.10: "The theft write-off cascade fires when a THEFT claim is approved while
    the rental's billing_status is BILLING_ACTIVE: the rental's billing_status moves to
    WRITTEN_OFF, its lifecycle_status is set to CANCELLED".

    Approving the THEFT claim writes off the rental: billing_status WRITTEN_OFF,
    lifecycle_status CANCELLED.

    Design: Difficulty/transitive_cascade/theft_claim_cascade_depth3
    """
    bundle = setup_under_review_claim(claim_type="THEFT", claimed_amount_cents=90000,
                                      incident_clock="2026-06-05T00:00:00Z",
                                      rental_mode="MONTHLY",
                                      return_due_clock="2027-06-01T00:00:00Z",
                                      num_bikes=2, fleet_size=5)
    ctx, claim = bundle["ctx"], bundle["claim"]
    get_success_data(api_client.approve_coverage_claim(
        claim["id"], {"approved_payout_cents": 90000}, OPS))
    sub = make_subscriber_headers(ctx["account"]["id"])
    rental = get_success_data(api_client.get_rental(ctx["rental"]["id"], sub))
    assert rental["billing_status"] == "WRITTEN_OFF"
    assert rental["lifecycle_status"] == "CANCELLED"


def test_theft_claim_approval_retires_bike_and_reconciles_total(api):
    """PRD §3.10: "the bike transitions from OUT to RETIRED with its current_rental_id
    cleared, the model's available_count and total_bikes are recomputed".

    PRD §2.5: "total_bikes is the count of Bike rows whose model_id equals that model's
    id regardless of their status". The write-off retires the bike (hop2); recomputing
    total_bikes leaves it at 2 since the RETIRED bike row still exists, while
    available_count stays at 1 (the one remaining AVAILABLE bike) — the recompute (hop3).

    Design: Difficulty/transitive_cascade/theft_claim_cascade_depth3
    """
    bundle = setup_under_review_claim(claim_type="THEFT", claimed_amount_cents=90000,
                                      incident_clock="2026-06-05T00:00:00Z",
                                      rental_mode="MONTHLY",
                                      return_due_clock="2027-06-01T00:00:00Z",
                                      num_bikes=2, fleet_size=5)
    ctx, claim = bundle["ctx"], bundle["claim"]
    bike_id = ctx["rental"]["bike_id"]
    get_success_data(api_client.approve_coverage_claim(
        claim["id"], {"approved_payout_cents": 90000}, OPS))
    sub = make_subscriber_headers(ctx["account"]["id"])
    bike = get_success_data(api_client.get_bike(bike_id, OPS))
    assert bike["bike_status"] == "RETIRED", "hop2: bike retired by write-off"
    model_after = get_success_data(api_client.get_bike_model(ctx["model"]["id"], sub))
    assert model_after["total_bikes"] == 2, "hop3: total_bikes recomputed, row count unchanged"
    assert model_after["available_count"] == 1, "hop3: available_count recomputed"


# ===========================================================================
# Difficulty/cross_entity_state_dependency/rental_delivered_requires_delivery_completed
# ===========================================================================
def test_rental_advances_to_delivered_on_delivery_completion(api):
    """PRD §3.4: "Completing the INITIAL delivery advances the rental's lifecycle_status
    from RESERVED to DELIVERED and transitions the bike's bike_status from RESERVED to
    OUT".

    Completing the INITIAL delivery is what flips the RESERVED rental to DELIVERED.

    Design: Difficulty/cross_entity_state_dependency/rental_delivered_requires_delivery_completed
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    sub = make_subscriber_headers(account["id"])
    delivery = get_success_data(api_client.create_delivery(
        {"rental_id": rental["id"], "delivery_type": "INITIAL", "address": "1 A St",
         "window_start_clock": "2026-06-01T08:00:00Z",
         "window_end_clock": "2026-06-01T12:00:00Z"}, OPS))
    resp = api_client.complete_delivery(delivery["id"], TECH)
    dstatus = validate_success(resp, 200)
    assert dstatus["status"] == "COMPLETED"
    rental_after = get_success_data(api_client.get_rental(rental["id"], sub))
    assert rental_after["lifecycle_status"] == "DELIVERED", "gated by delivery completion"


def test_rental_stays_reserved_until_delivery_completed(api):
    """PRD §3.4: "Once a bike has been delivered, the holding Subscriber or FleetManager
    activates the rental. Activation requires the rental to be DELIVERED".

    Before the INITIAL delivery is completed the rental remains RESERVED, so activation
    (only defined from DELIVERED) is rejected with ERR_INVALID_STATE — the rental cannot
    reach DELIVERED by any other path.

    Design: Difficulty/cross_entity_state_dependency/rental_delivered_requires_delivery_completed
    """
    from test_helpers import validate_error, ApiErrorId
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    sub = make_subscriber_headers(account["id"])
    # INITIAL delivery scheduled but NOT completed.
    get_success_data(api_client.create_delivery(
        {"rental_id": rental["id"], "delivery_type": "INITIAL", "address": "1 A St",
         "window_start_clock": "2026-06-01T08:00:00Z",
         "window_end_clock": "2026-06-01T12:00:00Z"}, OPS))
    resp = api_client.activate_rental(rental["id"], sub)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    rental_after = get_success_data(api_client.get_rental(rental["id"], sub))
    assert rental_after["lifecycle_status"] == "RESERVED"


# ===========================================================================
# Difficulty/cross_entity_state_dependency/rental_resumes_when_no_open_ticket
# ===========================================================================
def test_rental_resumes_active_when_ticket_closed(api):
    """PRD §3.5: "if the rental is currently IN_SERVICE and no other ticket for that
    rental remains in OPEN, IN_PROGRESS, or REOPENED, then the rental auto-transitions
    from IN_SERVICE back to ACTIVE and the bike returns from SERVICING to OUT".

    Closing the resolved CRITICAL ticket resumes the rental to ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/rental_resumes_when_no_open_ticket
    """
    bundle = setup_resolved_ticket(severity="CRITICAL", issue_type="MOTOR",
                                   rental_mode="MONTHLY",
                                   return_due_clock="2027-06-01T00:00:00Z")
    ctx, ticket = bundle["ctx"], bundle["ticket"]
    get_success_data(api_client.close_service_ticket(ticket["id"], TECH))
    sub = make_subscriber_headers(ctx["account"]["id"])
    rental = get_success_data(api_client.get_rental(ctx["rental"]["id"], sub))
    assert rental["lifecycle_status"] == "ACTIVE", "resumed: no open ticket remains"


def test_rental_resume_releases_bike_servicing(api):
    """PRD §3.5: "and the bike returns from SERVICING to OUT, each with its version
    bumped."

    When the rental resumes to ACTIVE on ticket close, its bike returns from SERVICING
    to OUT.

    Design: Difficulty/cross_entity_state_dependency/rental_resumes_when_no_open_ticket
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    bikes = add_bikes(model["id"], 1)
    bike_id = bikes[0]["id"]
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    ticket = get_success_data(api_client.create_service_ticket(
        {"rental_id": rental["id"], "issue_type": "MOTOR", "severity": "CRITICAL",
         "description": "motor dead"}, sub))
    get_success_data(api_client.start_service_ticket(ticket["id"], TECH))
    get_success_data(api_client.resolve_service_ticket(
        ticket["id"], {"resolution_note": "replaced motor"}, TECH))
    get_success_data(api_client.close_service_ticket(ticket["id"], TECH))
    bike = get_success_data(api_client.get_bike(bike_id, OPS))
    assert bike["bike_status"] == "OUT", "servicing released back to OUT"


# ===========================================================================
# Corner/state_machines/critical_ticket_freezes_rental_to_in_service
# ===========================================================================
def test_critical_ticket_freezes_rental_to_in_service(api):
    """PRD §3.5: "A CRITICAL ticket freezes the rental at filing time: as an automatic
    side effect the bike's bike_status moves from OUT to SERVICING and the rental's
    lifecycle_status moves from ACTIVE to IN_SERVICE".

    Design: Corner/state_machines/critical_ticket_freezes_rental_to_in_service
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    bikes = add_bikes(model["id"], 1)
    bike_id = bikes[0]["id"]
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.create_service_ticket(
        {"rental_id": rental["id"], "issue_type": "BATTERY", "severity": "CRITICAL",
         "description": "battery fault"}, sub))
    rental_after = get_success_data(api_client.get_rental(rental["id"], sub))
    assert rental_after["lifecycle_status"] == "IN_SERVICE"
    bike = get_success_data(api_client.get_bike(bike_id, OPS))
    assert bike["bike_status"] == "SERVICING"


# ===========================================================================
# Corner/state_machines/swap_delivery_exchanges_bike
# ===========================================================================
def test_swap_delivery_exchanges_bike(api):
    """PRD §3.4: "Completing a SWAP delivery returns the old bike from OUT to AVAILABLE
    and clears its current_rental_id, transitions the replacement swap_to_bike_id bike
    from RESERVED to OUT, repoints the agreement's bike_id to the replacement, and
    recomputes the model's available_count."

    Design: Corner/state_machines/swap_delivery_exchanges_bike
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 2)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    old_bike_id = rental["bike_id"]
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    swap = get_success_data(api_client.create_delivery(
        {"rental_id": rental["id"], "delivery_type": "SWAP", "address": "1 A St",
         "window_start_clock": "2026-06-05T08:00:00Z",
         "window_end_clock": "2026-06-05T12:00:00Z"}, OPS))
    replacement_id = swap["swap_to_bike_id"]
    assert replacement_id and replacement_id != old_bike_id
    get_success_data(api_client.complete_delivery(swap["id"], TECH))
    rental_after = get_success_data(api_client.get_rental(rental["id"], sub))
    assert rental_after["bike_id"] == replacement_id, "rental repointed to replacement"
    old_bike = get_success_data(api_client.get_bike(old_bike_id, OPS))
    new_bike = get_success_data(api_client.get_bike(replacement_id, OPS))
    assert old_bike["bike_status"] == "AVAILABLE"
    assert new_bike["bike_status"] == "OUT"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/damage_claim_payout_credits_wallet_only
# ===========================================================================
def test_damage_claim_payout_credits_wallet_only(api):
    """PRD §3.10: "for a DAMAGE claim, the approved payout is credited to the account's
    wallet_credit_cents only, with no rental cascade".

    DAMAGE claim approved 30000 (cap 40% of 90000 = 36000): wallet credited 30000, the
    rental stays ACTIVE and the bike stays OUT (no retire).

    Design: Corner/cross_cutting_complexity_layers/damage_claim_payout_credits_wallet_only
    """
    bundle = setup_under_review_claim(claim_type="DAMAGE", claimed_amount_cents=30000,
                                      rental_mode="MONTHLY",
                                      return_due_clock="2027-06-01T00:00:00Z")
    ctx, claim = bundle["ctx"], bundle["claim"]
    bike_id = ctx["rental"]["bike_id"]
    get_success_data(api_client.approve_coverage_claim(
        claim["id"], {"approved_payout_cents": 30000}, OPS))
    sub = make_subscriber_headers(ctx["account"]["id"])
    account = get_success_data(api_client.get_account(ctx["account"]["id"], sub))
    assert account["wallet_credit_cents"] == 30000, "payout credited to wallet"
    rental = get_success_data(api_client.get_rental(ctx["rental"]["id"], sub))
    assert rental["lifecycle_status"] == "ACTIVE"
    bike = get_success_data(api_client.get_bike(bike_id, OPS))
    assert bike["bike_status"] == "OUT", "no retire on DAMAGE"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/derived_active_rental_count_reconciles_on_return
# ===========================================================================
def test_active_rental_count_reconciles_to_zero_on_return(api):
    """PRD §2.5: "active_rental_count is the count of RentalAgreement rows for that
    account whose lifecycle_status is one of RESERVED, DELIVERED, ACTIVE, or IN_SERVICE,
    and it is recomputed on every rental lifecycle transition."

    A single ACTIVE rental returned (RETURNED is excluded from the active set) reconciles
    active_rental_count from 1 to 0.

    Design: Corner/cross_cutting_complexity_layers/derived_active_rental_count_reconciles_on_return
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=20000, fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-30T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "1 A St"}, sub))
    set_clock("2026-06-05T00:00:00Z")
    get_success_data(api_client.inspect_rental(rental["id"], inspect_payload(), TECH))
    account_after = get_success_data(api_client.get_account(account["id"], sub))
    assert account_after["active_rental_count"] == 0, "reconciled from 1 after RETURNED"
