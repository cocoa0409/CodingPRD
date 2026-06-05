"""Validation precedence pairs, cross-entity state gates on confirm/check-in/check-out,
and the folio / audit / rate-plan validation errors.

Difficulty queue: priority_pair_validation_conflict, cross_entity_state_dependency.
Corner queue (validations): folio-not-open, disputed checkout, rate-plan mismatch on
pickup, audit-blocked-open-balance.
"""
from test_helpers import (
    api_client as _api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_basic,
    setup_corporate,
    create_hotel,
    create_room_type,
    create_rate_plan,
    create_corporate_account,
    create_guest,
    create_inspected_room,
    create_group_block,
    create_confirmed_reservation,
    create_assigned_reservation,
    create_checked_in_reservation,
    get_folio_for_reservation,
    open_audit,
    run_one_audit,
)
api = _api_client
RM = TEST_USERS["revenue_manager_headers"]
FDA = TEST_USERS["front_desk_headers"]
NA = TEST_USERS["night_auditor_headers"]


def _folio(hotel_id, res_id):
    return get_folio_for_reservation(hotel_id, res_id)


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/audit_lock_state_beats_availability_constraint
# ===========================================================================
def test_audit_lock_masks_availability_on_create():
    """PRD §3.9: "then posture, rejecting an operational mutation while the property is
    `AUDIT_LOCK` with `ERR_HOTEL_AUDIT_LOCKED`; then transition validity ... Beyond these
    come the business checks in their own order: ... then availability (`ERR_NO_AVAILABILITY`)".
    PRD §2.7: "reservation create ... are all rejected with `ERR_HOTEL_AUDIT_LOCKED`
    (HTTP 409) while the lock is held."

    inv 1, one room already sold for 07-01, audit IN_PROGRESS: a second create that would
    BOTH oversell AND hit the lock returns ERR_HOTEL_AUDIT_LOCKED, not ERR_NO_AVAILABILITY.

    Design: Difficulty/priority_pair_validation_conflict/audit_lock_state_beats_availability_constraint
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    only = create_room_type(hotel["id"], code="ONLY", tier_rank=1,
                            physical_inventory=1, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": only["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA))
    open_audit(hotel["id"])

    resp = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": only["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA)
    validate_error(resp, ApiErrorId.ERR_HOTEL_AUDIT_LOCKED.value)


def test_oversell_create_returns_availability_once_lock_cleared():
    """PRD §2.7: "Completing or aborting the audit returns the `posture` to `OPEN`."
    PRD §3.3: "If for any night in the half-open interval from `arrival_date` to
    `departure_date` the sold count plus one would exceed the sellable count, the booking
    is rejected with `ERR_NO_AVAILABILITY` (HTTP 409)."

    The complement of the masking test: the same oversell create, once the audit is
    aborted (lock cleared), surfaces the lower-priority ERR_NO_AVAILABILITY — proving the
    lock was masking a genuine availability failure, not the absence of one.

    Design: Difficulty/priority_pair_validation_conflict/audit_lock_state_beats_availability_constraint
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    only = create_room_type(hotel["id"], code="ONLY", tier_rank=1,
                            physical_inventory=1, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": only["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA))
    run = open_audit(hotel["id"])
    hv = validate_success(api.get_hotel(hotel["id"], NA))["version"]
    get_success_data(api.abort_night_audit_run(run["id"], {"expected_hotel_version": hv}, NA))

    resp = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": only["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA)
    validate_error(resp, ApiErrorId.ERR_NO_AVAILABILITY.value)


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/ratePlan_referential_beats_fiscal_credit_on_confirm
# ===========================================================================
def test_rate_plan_mismatch_masks_credit_limit_on_confirm():
    """PRD §3.9: "Beyond these come the business checks in their own order: rate-plan
    applicability (`ERR_RATE_PLAN_MISMATCH`), then group-block cutoff
    (`ERR_BLOCK_CUTOFF_PASSED`), then room assignability (`ERR_ROOM_NOT_ASSIGNABLE`), then
    availability (`ERR_NO_AVAILABILITY`), then corporate credit
    (`ERR_CREDIT_LIMIT_EXCEEDED`)".
    PRD §3.6: "the backing rate plan's `status` is `ACTIVE` (otherwise
    `ERR_RATE_PLAN_MISMATCH`, HTTP 409)".

    CORPORATE plan FLAT+0 base 60000 credit_limit 50000; plan CLOSED before confirm.
    The confirm both fails rate-plan-active AND credit; the higher-priority
    ERR_RATE_PLAN_MISMATCH is returned.

    Design: Difficulty/priority_pair_validation_conflict/ratePlan_referential_beats_fiscal_credit_on_confirm
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    king = create_room_type(hotel["id"], code="KING", tier_rank=1,
                            physical_inventory=5, base_rate_cents=60000)
    acct = create_corporate_account(hotel["id"], name="Initech", credit_limit_cents=50000)
    corp = create_rate_plan(hotel["id"], code="CORP", kind="CORPORATE",
                            corporate_account_id=acct["id"], adjustment_mode="FLAT",
                            adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": king["id"],
        "rate_plan_id": corp["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    get_success_data(api.close_rate_plan(
        corp["id"], {"expected_rate_plan_version": corp["version"]}, RM))

    resp = api.confirm_reservation(res["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_RATE_PLAN_MISMATCH.value)


def test_credit_limit_surfaces_when_rate_plan_active():
    """PRD §3.7: "rejects the confirmation when that projected total is strictly greater
    than the account's `credit_limit_cents`, returning `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 402)."
    PRD §3.6: "the backing rate plan's `status` is `ACTIVE`".

    The complement: with the CORPORATE plan left ACTIVE (rate-plan check passes), the same
    over-credit confirm surfaces the lower-priority ERR_CREDIT_LIMIT_EXCEEDED — proving the
    rate-plan error in the masking test genuinely pre-empted a real credit failure.
    base 60000 * 1 night = 60000 projection > limit 50000.

    Design: Difficulty/priority_pair_validation_conflict/ratePlan_referential_beats_fiscal_credit_on_confirm
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    king = create_room_type(hotel["id"], code="KING", tier_rank=1,
                            physical_inventory=5, base_rate_cents=60000)
    acct = create_corporate_account(hotel["id"], name="Initech", credit_limit_cents=50000)
    corp = create_rate_plan(hotel["id"], code="CORP", kind="CORPORATE",
                            corporate_account_id=acct["id"], adjustment_mode="FLAT",
                            adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": king["id"],
        "rate_plan_id": corp["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA))

    resp = api.confirm_reservation(res["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


# ===========================================================================
# Difficulty/cross_entity_state_dependency/checkin_requires_room_inspected_state
# ===========================================================================
def test_checkin_requires_assigned_room_inspected():
    """PRD §3.6: "the assigned room's `housekeeping_status` equal to `INSPECTED`
    (otherwise `ERR_ROOM_NOT_INSPECTED`, HTTP 409)".

    Room assigned while CLEAN (never INSPECTED) blocks check-in.

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_room_inspected_state
    """
    b = setup_basic(current_business_date="2026-07-01")
    # Assign a CLEAN room (not inspected). assign-room does not require INSPECTED.
    room = get_success_data(api.create_room({
        "hotel_id": b["hotel"]["id"], "room_type_id": b["room_type"]["id"],
        "room_number": "601"}, RM))
    res = create_confirmed_reservation(b, arrival_date="2026-07-01",
                                       departure_date="2026-07-02")
    get_success_data(api.assign_room(res["id"],
        {"room_id": room["id"], "expected_room_version": room["version"]}, FDA))

    resp = api.check_in(res["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_INSPECTED.value)
    res_after = validate_success(api.get_reservation(res["id"], FDA))
    assert res_after["status"] == "CONFIRMED", res_after


def test_checkin_succeeds_when_room_inspected():
    """PRD §3.6: "Check-in is a `FrontDeskAgent` action moving the reservation
    `CONFIRMED → CHECKED_IN`. It requires posture `OPEN`, a non-null `assigned_room_id`
    ..., the assigned room's `housekeeping_status` equal to `INSPECTED` ..., and the
    property's `current_business_date` on or after the reservation's `arrival_date`".

    The positive control for the INSPECTED gate: an INSPECTED assigned room admits check-in.

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_room_inspected_state
    """
    b = setup_basic(current_business_date="2026-07-01")
    res, _room = create_assigned_reservation(b, room_number="602",
                                             arrival_date="2026-07-01",
                                             departure_date="2026-07-02")
    checked_in = validate_success(api.check_in(res["id"], FDA))
    assert checked_in["status"] == "CHECKED_IN", checked_in


# ===========================================================================
# Difficulty/cross_entity_state_dependency/confirm_corporate_requires_account_active_state
# ===========================================================================
def test_confirm_corporate_blocked_when_account_suspended():
    """PRD §3.6: "for a corporate reservation — the backing `CorporateAccount`'s `status`
    is `ACTIVE` (otherwise `ERR_CORPORATE_SUSPENDED`, HTTP 409) and the corporate credit
    check passes."

    Design: Difficulty/cross_entity_state_dependency/confirm_corporate_requires_account_active_state
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    king = create_room_type(hotel["id"], code="KING", tier_rank=1,
                            physical_inventory=5, base_rate_cents=20000)
    acct = create_corporate_account(hotel["id"], name="Hooli", credit_limit_cents=100000)
    corp = create_rate_plan(hotel["id"], code="CORP", kind="CORPORATE",
                            corporate_account_id=acct["id"], adjustment_mode="FLAT",
                            adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": king["id"],
        "rate_plan_id": corp["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    get_success_data(api.suspend_corporate_account(
        acct["id"], {"expected_corporate_account_version": acct["version"]}, RM))

    resp = api.confirm_reservation(res["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_CORPORATE_SUSPENDED.value)
    res_after = validate_success(api.get_reservation(res["id"], FDA))
    assert res_after["status"] == "HELD", res_after


def test_confirm_corporate_succeeds_when_account_active():
    """PRD §3.1: "While an account is `SUSPENDED`, confirming a new corporate reservation
    drawn on it is blocked."
    PRD §3.6: "Confirming a reservation is a `FrontDeskAgent` action moving its `status`
    from `HELD` to `CONFIRMED`".

    Positive control: an ACTIVE account admits the corporate confirm.

    Design: Difficulty/cross_entity_state_dependency/confirm_corporate_requires_account_active_state
    """
    b = setup_corporate(credit_limit_cents=100000, base_rate_cents=20000,
                        physical_inventory=5, adjustment_value=0)
    res = get_success_data(api.create_reservation({
        "hotel_id": b["hotel"]["id"], "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    confirmed = validate_success(api.confirm_reservation(res["id"], FDA))
    assert confirmed["status"] == "CONFIRMED", confirmed


# ===========================================================================
# Corner/validations/incidental_post_to_disputed_folio_returns_folio_not_open
# ===========================================================================
def test_post_incidental_to_disputed_folio_returns_folio_not_open():
    """PRD §3.6: "A folio that is not in the status required for the requested operation —
    for instance, an attempt to post or void against a folio that is not `OPEN` — is
    rejected with `ERR_FOLIO_NOT_OPEN` (HTTP 409)."

    Design: Corner/validations/incidental_post_to_disputed_folio_returns_folio_not_open
    """
    b = setup_basic()
    res = get_success_data(api.create_reservation({
        "hotel_id": b["hotel"]["id"], "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(b["hotel"]["id"], res["id"])["id"]
    get_success_data(api.dispute_folio(folio_id, FDA))

    resp = api.create_incidental({
        "hotel_id": b["hotel"]["id"], "folio_id": folio_id, "kind": "CHARGE",
        "description": "Minibar", "amount_cents": 1000}, FDA)
    validate_error(resp, ApiErrorId.ERR_FOLIO_NOT_OPEN.value)
    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["status"] == "DISPUTED", folio


# ===========================================================================
# Corner/validations/checkout_disputed_folio_returns_folio_disputed_checkout
# ===========================================================================
def test_checkout_with_disputed_folio_returns_folio_disputed_checkout():
    """PRD §3.6: "Check-out is a `FrontDeskAgent` action moving the reservation
    `CHECKED_IN → CHECKED_OUT`. It requires posture `OPEN` and a folio that is not
    `DISPUTED` (otherwise `ERR_FOLIO_DISPUTED_CHECKOUT`, HTTP 409)."

    Design: Corner/validations/checkout_disputed_folio_returns_folio_disputed_checkout
    """
    b = setup_basic(current_business_date="2026-07-01")
    res, _room = create_checked_in_reservation(b, room_number="111",
                                               arrival_date="2026-07-01",
                                               departure_date="2026-07-02")
    folio_id = _folio(b["hotel"]["id"], res["id"])["id"]
    get_success_data(api.dispute_folio(folio_id, FDA))

    resp = api.check_out(res["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_FOLIO_DISPUTED_CHECKOUT.value)
    res_after = validate_success(api.get_reservation(res["id"], FDA))
    assert res_after["status"] == "CHECKED_IN", res_after


# ===========================================================================
# Corner/validations/group_pickup_wrong_rate_plan_returns_rate_plan_mismatch
# ===========================================================================
def test_group_pickup_with_wrong_rate_plan_returns_rate_plan_mismatch():
    """PRD §3.2: "A group pickup's `rate_plan_id` must equal the block's `rate_plan_id`;
    a mismatch is rejected with `ERR_RATE_PLAN_MISMATCH` (HTTP 409)."

    Design: Corner/validations/group_pickup_wrong_rate_plan_returns_rate_plan_mismatch
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=9, base_rate_cents=15000)
    grp = create_rate_plan(hotel["id"], code="GRP", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    other = create_rate_plan(hotel["id"], code="OTHER", kind="BAR",
                             adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    block = create_group_block(hotel["id"], queen["id"], grp["id"], block_name="Conf",
                               arrival_date="2026-07-08", departure_date="2026-07-10",
                               cutoff_date="2026-07-07", blocked_rooms=4)
    guest = create_guest(hotel["id"])

    resp = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": queen["id"],
        "rate_plan_id": other["id"], "arrival_date": "2026-07-08",
        "departure_date": "2026-07-10", "group_block_id": block["id"],
        "expected_group_block_version": block["version"]}, FDA)
    validate_error(resp, ApiErrorId.ERR_RATE_PLAN_MISMATCH.value)


# ===========================================================================
# Corner/validations/audit_complete_with_open_departing_balance_returns_blocked
# ===========================================================================
def test_audit_complete_blocked_by_open_departing_folio():
    """PRD §3.8: "It is blocked when any `CHECKED_IN` reservation departing today — whose
    `departure_date` equals the `business_date` — still has a folio that is `OPEN` or
    `DISPUTED`, in which case the completion is rejected with
    `ERR_AUDIT_BLOCKED_OPEN_BALANCE` (HTTP 409)."

    A reservation arriving 06-30 / departing 07-01 is CHECKED_IN on business_date 07-01,
    so departure_date == business_date and its OPEN folio blocks the audit close. (The PRD
    pins the block to departure_date == business_date; arrival 06-30 satisfies the
    current_business_date >= arrival_date check-in precondition.)

    Design: Corner/validations/audit_complete_with_open_departing_balance_returns_blocked
    """
    b = setup_basic(current_business_date="2026-07-01")
    res, _room = create_checked_in_reservation(b, room_number="121",
                                               arrival_date="2026-06-30",
                                               departure_date="2026-07-01")
    run = open_audit(b["hotel"]["id"])
    hv = validate_success(api.get_hotel(b["hotel"]["id"], NA))["version"]
    resp = api.complete_night_audit_run(run["id"], {"expected_hotel_version": hv}, NA)
    validate_error(resp, ApiErrorId.ERR_AUDIT_BLOCKED_OPEN_BALANCE.value)
