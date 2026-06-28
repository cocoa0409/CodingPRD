"""Reservation guards, delivery/servicing temporal conflicts, OCC, and validation order.

Covers the reservation guard ordering that PRD §3.3 states explicitly, the
ERR_BIKE_RETIRED safety guard, delivery-window half-open overlap, bike-servicing whole-
span mutual exclusion, and the optimistic-concurrency check on BikeModel.version.
"""
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    make_subscriber_headers,
    make_fleet_manager_headers,
    make_field_tech_headers,
    make_ops_admin_headers,
    setup_under_review_claim,
    create_rental_payload,
    create_delivery_payload,
)
from test_helpers.fixtures import (
    set_clock, create_model, add_bikes, create_account, read_model_version,
    reserve, schedule_and_complete_initial_delivery, activate,
)

OPS = make_ops_admin_headers()
TECH = make_field_tech_headers()


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_reserve
# ===========================================================================
def test_stale_version_beats_no_bikes_available_on_reserve(api):
    """PRD §3.3: "The optimistic-concurrency comparison of expected_model_version against
    the model's current version comes next and rejects a stale request with
    ERR_STALE_MODEL_VERSION (HTTP 412). After that the business guards apply in this
    order: a SUSPENDED account cannot reserve and is rejected with ERR_ACCOUNT_SUSPENDED
    (HTTP 409); an account already holding a number of active rentals equal to or greater
    than its rental_cap is rejected with ERR_RENTAL_CAP_EXCEEDED (HTTP 409); and a model
    whose pool has no free unit — that is, whose available_count is below one — is
    rejected with ERR_NO_BIKES_AVAILABLE (HTTP 409)."

    A reserve carrying a stale model version against a model with zero free bikes returns
    the higher-priority ERR_STALE_MODEL_VERSION (412), checked before the pool guard.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_reserve
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=1)
    add_bikes(model["id"], 1)
    a1 = create_account(display_name="A1", email="a1@x.com", rental_cap=1)
    a2 = create_account(display_name="A2", email="a2@x.com", rental_cap=1)
    # a2 reads the model version BEFORE a1's reservation advances it.
    mv_stale = read_model_version(model["id"], a2["id"])
    # a1 consumes the only bike (and bumps the model version).
    reserve(a1["id"], model["id"], mv_stale)
    # a2 now reserves with the stale version against an empty pool.
    resp = api_client.create_rental(
        create_rental_payload(a2["id"], model["id"], mv_stale),
        make_subscriber_headers(a2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_MODEL_VERSION.value, 412)


def test_stale_version_reserve_returns_412_status(api):
    """PRD §2.7: "the reservation is rejected with ERR_STALE_MODEL_VERSION (HTTP 412)."

    The dual-failure reserve resolves to HTTP 412, confirming the precedence-winning
    error's status (vs the 409 the pool guard would emit).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_reserve
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=1)
    add_bikes(model["id"], 1)
    a1 = create_account(display_name="A1", email="a1@x.com", rental_cap=1)
    a2 = create_account(display_name="A2", email="a2@x.com", rental_cap=1)
    mv_stale = read_model_version(model["id"], a2["id"])
    reserve(a1["id"], model["id"], mv_stale)
    resp = api_client.create_rental(
        create_rental_payload(a2["id"], model["id"], mv_stale),
        make_subscriber_headers(a2["id"]))
    assert resp.status_code == 412


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_service_ticket
# ===========================================================================
def test_service_ticket_on_retired_bike_returns_bike_retired(api):
    """PRD §3.10: "This is why a rental against a bike that has already been written off
    cannot be inspected, returned, or have a non-critical action filed against it — those
    operations are rejected with ERR_BIKE_RETIRED."
    PRD §3.5: "a ticket may not be opened against a rental whose bike is RETIRED (rejected
    with ERR_BIKE_RETIRED, HTTP 409)".

    After a THEFT write-off retires the bike, opening a new service ticket against the
    rental is rejected with ERR_BIKE_RETIRED.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_service_ticket
    """
    bundle = setup_under_review_claim(claim_type="THEFT", claimed_amount_cents=90000,
                                      incident_clock="2026-06-03T00:00:00Z",
                                      rental_mode="MONTHLY",
                                      return_due_clock="2027-06-01T00:00:00Z")
    ctx, claim = bundle["ctx"], bundle["claim"]
    get_success_data(api_client.approve_coverage_claim(
        claim["id"], {"approved_payout_cents": 90000}, OPS))
    sub = make_subscriber_headers(ctx["account"]["id"])
    resp = api_client.create_service_ticket(
        {"rental_id": ctx["rental"]["id"], "issue_type": "BRAKE", "severity": "CRITICAL",
         "description": "post-retire attempt"}, sub)
    validate_error(resp, ApiErrorId.ERR_BIKE_RETIRED.value, 409)


def test_request_return_on_retired_bike_returns_bike_retired(api):
    """PRD §3.6: "A return may not be requested on a rental whose bike is RETIRED
    (rejected with ERR_BIKE_RETIRED)."

    After a THEFT write-off the rental is CANCELLED and its bike RETIRED; requesting a
    return is rejected with ERR_BIKE_RETIRED (the safety guard), confirming the guard
    fires across return-path actions.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_service_ticket
    """
    bundle = setup_under_review_claim(claim_type="THEFT", claimed_amount_cents=90000,
                                      incident_clock="2026-06-03T00:00:00Z",
                                      rental_mode="MONTHLY",
                                      return_due_clock="2027-06-01T00:00:00Z")
    ctx, claim = bundle["ctx"], bundle["claim"]
    get_success_data(api_client.approve_coverage_claim(
        claim["id"], {"approved_payout_cents": 90000}, OPS))
    sub = make_subscriber_headers(ctx["account"]["id"])
    resp = api_client.request_return(ctx["rental"]["id"], {"return_address": "1 A St"}, sub)
    validate_error(resp, ApiErrorId.ERR_BIKE_RETIRED.value, 409)


# ===========================================================================
# Difficulty/resource_temporal_overlap/delivery_window_half_open_overlap_same_rental
# ===========================================================================
def test_delivery_window_overlap_same_rental_rejected(api):
    """PRD §3.4: "a new delivery must not collide with an existing SCHEDULED delivery for
    the same rental: if the two half-open intervals [start, end) share any single instant,
    the new request is rejected with the same ERR_DELIVERY_WINDOW_CONFLICT."

    A second INITIAL delivery [10:00,14:00) sharing instant 10:00 with [08:00,12:00) is
    rejected with ERR_DELIVERY_WINDOW_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_overlap_same_rental
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    get_success_data(api_client.create_delivery(
        create_delivery_payload(rental["id"], "INITIAL",
                                window_start_clock="2026-06-01T08:00:00Z",
                                window_end_clock="2026-06-01T12:00:00Z"), OPS))
    resp = api_client.create_delivery(
        create_delivery_payload(rental["id"], "INITIAL",
                                window_start_clock="2026-06-01T10:00:00Z",
                                window_end_clock="2026-06-01T14:00:00Z"), OPS)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_CONFLICT.value, 409)


def test_delivery_window_conflict_returns_409(api):
    """PRD §3.4: "The window must be well-formed: window_start_clock must be strictly
    earlier than window_end_clock, otherwise the delivery is rejected with
    ERR_DELIVERY_WINDOW_CONFLICT (HTTP 409)."

    The overlap conflict resolves to HTTP 409.

    Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_overlap_same_rental
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    get_success_data(api_client.create_delivery(
        create_delivery_payload(rental["id"], "INITIAL",
                                window_start_clock="2026-06-01T08:00:00Z",
                                window_end_clock="2026-06-01T12:00:00Z"), OPS))
    resp = api_client.create_delivery(
        create_delivery_payload(rental["id"], "INITIAL",
                                window_start_clock="2026-06-01T10:00:00Z",
                                window_end_clock="2026-06-01T14:00:00Z"), OPS)
    assert resp.status_code == 409


# ===========================================================================
# Difficulty/resource_temporal_overlap/bike_servicing_whole_span_mutual_exclusion
# ===========================================================================
def test_second_ticket_on_servicing_bike_rejected(api):
    """PRD §3.5: "a ticket may not be opened against a bike whose bike_status is already
    SERVICING, since the physical unit's servicing span is mutually exclusive — that
    overlap is rejected with ERR_BIKE_ALREADY_SERVICING (HTTP 409)."

    A CRITICAL ticket puts the bike into SERVICING; a second ticket on the same bike is
    rejected with ERR_BIKE_ALREADY_SERVICING.

    Design: Difficulty/resource_temporal_overlap/bike_servicing_whole_span_mutual_exclusion
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.create_service_ticket(
        {"rental_id": rental["id"], "issue_type": "BATTERY", "severity": "CRITICAL",
         "description": "battery fault"}, sub))
    resp = api_client.create_service_ticket(
        {"rental_id": rental["id"], "issue_type": "MOTOR", "severity": "MAJOR",
         "description": "second issue"}, sub)
    validate_error(resp, ApiErrorId.ERR_BIKE_ALREADY_SERVICING.value, 409)


def test_servicing_mutual_exclusion_returns_409(api):
    """PRD §3.5: "that overlap is rejected with ERR_BIKE_ALREADY_SERVICING (HTTP 409)."

    The whole-span servicing exclusion resolves to HTTP 409.

    Design: Difficulty/resource_temporal_overlap/bike_servicing_whole_span_mutual_exclusion
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.create_service_ticket(
        {"rental_id": rental["id"], "issue_type": "BATTERY", "severity": "CRITICAL",
         "description": "battery fault"}, sub))
    resp = api_client.create_service_ticket(
        {"rental_id": rental["id"], "issue_type": "MOTOR", "severity": "MAJOR",
         "description": "second issue"}, sub)
    assert resp.status_code == 409


# ===========================================================================
# Corner/validations/reserve_when_no_bikes_available
# ===========================================================================
def test_reserve_with_no_bikes_available(api):
    """PRD §3.3: "a model whose pool has no free unit — that is, whose available_count is
    below one — is rejected with ERR_NO_BIKES_AVAILABLE (HTTP 409)."

    With the only bike already reserved and a current (non-stale) model version, the OCC
    check passes and the pool guard fires: ERR_NO_BIKES_AVAILABLE.

    Design: Corner/validations/reserve_when_no_bikes_available
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=1)
    add_bikes(model["id"], 1)
    a1 = create_account(display_name="A1", email="a1@x.com", rental_cap=1)
    a2 = create_account(display_name="A2", email="a2@x.com", rental_cap=1)
    mv0 = read_model_version(model["id"], a1["id"])
    reserve(a1["id"], model["id"], mv0)
    mv1 = read_model_version(model["id"], a2["id"])  # current version after the reserve
    resp = api_client.create_rental(
        create_rental_payload(a2["id"], model["id"], mv1),
        make_subscriber_headers(a2["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_BIKES_AVAILABLE.value, 409)


# ===========================================================================
# Corner/validations/reserve_exceeds_rental_cap
# ===========================================================================
def test_reserve_exceeds_rental_cap(api):
    """PRD §3.3: "an account already holding a number of active rentals equal to or
    greater than its rental_cap is rejected with ERR_RENTAL_CAP_EXCEEDED (HTTP 409)".

    An account with rental_cap 1 already holding one RESERVED rental attempts a second
    reserve -> ERR_RENTAL_CAP_EXCEEDED.

    Design: Corner/validations/reserve_exceeds_rental_cap
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=3)
    add_bikes(model["id"], 2)
    account = create_account(rental_cap=1)
    mv0 = read_model_version(model["id"], account["id"])
    reserve(account["id"], model["id"], mv0)
    mv1 = read_model_version(model["id"], account["id"])
    resp = api_client.create_rental(
        create_rental_payload(account["id"], model["id"], mv1),
        make_subscriber_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_RENTAL_CAP_EXCEEDED.value, 409)


# ===========================================================================
# Corner/validations/reserve_by_suspended_account
# ===========================================================================
def test_reserve_by_suspended_account(api):
    """PRD §3.3: "a SUSPENDED account cannot reserve and is rejected with
    ERR_ACCOUNT_SUSPENDED (HTTP 409)".

    Design: Corner/validations/reserve_by_suspended_account
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    get_success_data(api_client.suspend_account(account["id"], OPS))
    mv = read_model_version(model["id"], account["id"])
    resp = api_client.create_rental(
        create_rental_payload(account["id"], model["id"], mv),
        make_subscriber_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value, 409)


# ===========================================================================
# Corner/validations/delivery_type_mismatch_initial_on_active
# ===========================================================================
def test_delivery_type_mismatch_initial_on_active(api):
    """PRD §3.4: "The delivery_type must also match the rental's current lifecycle_status
    — INITIAL requires the rental to be RESERVED, PICKUP requires it to be
    RETURN_REQUESTED, and SWAP requires it to be either DELIVERED or ACTIVE — and a
    mismatch is rejected with ERR_DELIVERY_TYPE_MISMATCH (HTTP 409)."

    Scheduling an INITIAL delivery for an already-ACTIVE rental -> ERR_DELIVERY_TYPE_MISMATCH.

    Design: Corner/validations/delivery_type_mismatch_initial_on_active
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    resp = api_client.create_delivery(
        create_delivery_payload(rental["id"], "INITIAL",
                                window_start_clock="2026-06-07T08:00:00Z",
                                window_end_clock="2026-06-07T12:00:00Z"), OPS)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_TYPE_MISMATCH.value, 409)


# ===========================================================================
# Corner/validations/payout_exceeds_cap_on_damage_claim
# ===========================================================================
def test_payout_exceeds_cap_on_damage_claim(api):
    """PRD §3.10: "the cap is the model's purchase_price_cents multiplied by a percentage
    that depends on the claim type — 100% for a THEFT claim and 40% for a DAMAGE claim —
    rounded half up ... If the requested approved_payout_cents exceeds the claim's
    claimed_amount_cents or exceeds the coverage cap, the approval is rejected with
    ERR_PAYOUT_EXCEEDS_CAP (HTTP 422)."

    DAMAGE cap 40% of 180000 = 72000; approving with 80000 -> ERR_PAYOUT_EXCEEDS_CAP 422.

    Design: Corner/validations/payout_exceeds_cap_on_damage_claim
    """
    bundle = setup_under_review_claim(claim_type="DAMAGE", claimed_amount_cents=100000,
                                      rental_mode="MONTHLY",
                                      return_due_clock="2027-06-01T00:00:00Z",
                                      model_overrides={"model_class": "EBIKE",
                                                       "monthly_fee_cents": 12000,
                                                       "daily_rate_cents": 4000,
                                                       "purchase_price_cents": 180000},
                                      deposit_cents=20000)
    claim = bundle["claim"]
    resp = api_client.approve_coverage_claim(claim["id"], {"approved_payout_cents": 80000}, OPS)
    validate_error(resp, ApiErrorId.ERR_PAYOUT_EXCEEDS_CAP.value, 422)


# ===========================================================================
# Corner/validations/fleet_invoice_on_subscriber_account_rejected
# ===========================================================================
def test_fleet_invoice_on_subscriber_account_rejected(api):
    """PRD §3.11: "An invoice may only be generated for an account whose account_type is
    FLEET; a request against a non-fleet account is rejected with ERR_NOT_FLEET_ACCOUNT
    (HTTP 409)."

    Design: Corner/validations/fleet_invoice_on_subscriber_account_rejected
    """
    account = create_account(account_type="SUBSCRIBER", email="sam@x.com", rental_cap=1)
    resp = api_client.create_fleet_invoice(account["id"], {"cycle_index": 0}, OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FLEET_ACCOUNT.value, 409)


# ===========================================================================
# Corner/validations/buyout_accept_after_expiry_rejected
# ===========================================================================
def test_buyout_accept_after_expiry_rejected(api):
    """PRD §3.7: "an accept attempt at or after expires_at_clock is rejected with
    ERR_OFFER_EXPIRED."

    An offer expiring 2026-06-10 accepted at 2026-06-11 (clock advanced past expiry) ->
    ERR_OFFER_EXPIRED 409.

    Design: Corner/validations/buyout_accept_after_expiry_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(model_class="EBIKE", monthly_fee_cents=12000,
                         daily_rate_cents=4000, purchase_price_cents=180000,
                         deposit_cents=20000, fleet_size=2)
    add_bikes(model["id"], 1, prefix="E")
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="MONTHLY",
                     return_due_clock="2027-06-01T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    offer = get_success_data(api_client.create_buyout_offer(
        rental["id"], {"expires_at_clock": "2026-06-10T00:00:00Z"}, sub))
    set_clock("2026-06-11T00:00:00Z")
    resp = api_client.accept_buyout_offer(offer["id"], sub)
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value, 409)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_correct_model_version_reserve_succeeds
# ===========================================================================
def test_occ_correct_model_version_reserve_succeeds(api):
    """PRD §2.7: "A successful reservation itself increments the BikeModel.version by
    one, so a second create still carrying the pre-advance value will fail this check."

    A reserve carrying the current model version succeeds (201) and bumps the model
    version by exactly 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_model_version_reserve_succeeds
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    sub = make_subscriber_headers(account["id"])
    mv0 = get_success_data(api_client.get_bike_model(model["id"], sub))["version"]
    resp = api_client.create_rental(
        create_rental_payload(account["id"], model["id"], mv0), sub)
    data = validate_success(resp, 201)
    from test_helpers import is_valid_uuid
    assert is_valid_uuid(data["bike_id"]), "reservation selected a bike"
    mv1 = get_success_data(api_client.get_bike_model(model["id"], sub))["version"]
    assert mv1 == mv0 + 1, "model version incremented by exactly 1"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_model_version_reserve_rejected
# ===========================================================================
def test_occ_stale_model_version_reserve_rejected(api):
    """PRD §2.7: "If another writer has advanced the model's version since the client
    read it — for example, a prior reservation that already consumed a unit and recomputed
    available_count — then the client is acting on a stale view of pool availability, and
    the reservation is rejected with ERR_STALE_MODEL_VERSION (HTTP 412)."

    With 2 bikes, a first reserve bumps the version; a second reserve carrying the
    pre-bump version is rejected with ERR_STALE_MODEL_VERSION 412.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_model_version_reserve_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=3)
    add_bikes(model["id"], 2)
    account = create_account(account_type="FLEET", email="fleet@x.com",
                             display_name="RiderCo", rental_cap=5)
    fm = make_fleet_manager_headers(account["id"])
    mv_after_bikes = get_success_data(api_client.get_bike_model(model["id"], fm))["version"]
    get_success_data(api_client.create_rental(
        create_rental_payload(account["id"], model["id"], mv_after_bikes), fm))
    resp = api_client.create_rental(
        create_rental_payload(account["id"], model["id"], mv_after_bikes), fm)
    validate_error(resp, ApiErrorId.ERR_STALE_MODEL_VERSION.value, 412)
