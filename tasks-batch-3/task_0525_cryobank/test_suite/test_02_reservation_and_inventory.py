"""Vial reservation guards, inventory availability arithmetic, listability.

Queue-A (Difficulty) translations for dual_variant_calc (booking vs settlement),
combinatorial_formula (is_listed conjunction), boundary_precision_check
(vial-count boundary), cross_entity_state_dependency (confirm requires OPEN
inventory), priority_pair_validation_conflict (consent vs family limit), and
compensating_invariant (vial-pool conservation).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_recipient_headers, assert_inventory_pool_conserved,
    setup_listed_inventory_with_consented_recipient,
    setup_listed_inventory, setup_recipient_with_consent,
    confirm_one_family, place_hold,
    defer_donor_via_second_application,
)

SO = TEST_USERS["screening_officer_headers"]
LT = TEST_USERS["lab_tech_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["catalog_manager_headers"]


def test_available_vials_and_committed_available_diverge_with_held_and_confirmed(api):
    """PRD §3.5: "The booking view, available_vials, is the lot's total_vials minus
    reserved_vials minus shipped_vials". PRD §3.5: "The settlement view,
    committed_available_vials, is instead the lot's total_vials minus the sum of
    vial_count over reservations in CONFIRMED or SHIPPED only; it deliberately
    excludes HELD holds ... and therefore yields a value that is larger than
    available_vials whenever any HELD hold exists on the lot."

    Design: Difficulty/dual_variant_calc/inventory_booking_vs_settlement_diverge
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-2", blood_type="A_POS", dewar_code="T-2",
        initial_vial_count=5)
    inv_id, rcp_headers, rcp_id = ctx["inventory_id"], ctx["headers"], ctx["recipient_id"]
    # Reservation A of 2 left HELD.
    place_hold(inv_id, rcp_id, rcp_headers, 2, ctx["inventory_version"])
    inv1 = validate_success(api.get_donor_inventory(inv_id, CM))
    # Reservation B of 1 CONFIRMED.
    res_b = place_hold(inv_id, rcp_id, rcp_headers, 1, inv1["version"])
    validate_success(api.confirm_reservation(res_b["id"], CM))
    inv = validate_success(api.get_donor_inventory(inv_id, CM))
    assert inv["available_vials"] == 2, "booking: 5 - (2 HELD + 1 CONFIRMED)"
    assert inv["committed_available_vials"] == 4, "settlement: 5 - 1 CONFIRMED (HELD excluded)"


def test_committed_available_excludes_held_holds(api):
    """PRD §3.5: "The settlement view, committed_available_vials, is instead the
    lot's total_vials minus the sum of vial_count over reservations in CONFIRMED or
    SHIPPED only; it deliberately excludes HELD holds, treating them as not yet
    firmly committed, and therefore yields a value that is larger than available_vials
    whenever any HELD hold exists on the lot."

    A single HELD 2-vial hold on a 5-vial lot: available_vials 3 (HELD counted),
    committed_available_vials 5 (HELD excluded), and committed > available.

    Design: Difficulty/dual_variant_calc/inventory_booking_vs_settlement_diverge
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-2b", blood_type="A_POS", dewar_code="T-2b",
        initial_vial_count=5)
    place_hold(ctx["inventory_id"], ctx["recipient_id"], ctx["headers"], 2,
               ctx["inventory_version"])
    inv = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert inv["available_vials"] == 3, "booking: 5 - 2 HELD"
    assert inv["committed_available_vials"] == 5, "settlement: HELD excluded"
    assert inv["committed_available_vials"] > inv["available_vials"]


def test_is_listed_flips_false_when_family_limit_reached(api):
    """PRD §3.5: "An inventory lot is catalog-listed (is_listed true) precisely when
    all of the following hold together: its specimen is RELEASED, its donor is
    ACTIVE, the donor's is_family_limit_reached is false, its hold_status is OPEN,
    and its available_vials is greater than 0."
    PRD §3.8: "if the limit is now reached, every one of the donor's inventory lots
    has its is_listed recomputed to false."

    Design: Difficulty/combinatorial_formula/is_listed_multi_input_conjunction
    """
    inv = setup_listed_inventory(display_code="D-4b", blood_type="B_POS",
                                 family_limit=1, initial_vial_count=5, dewar_code="T-4b")
    rcp = setup_recipient_with_consent(inv["donor_id"], family_name="Fam R4",
                                       contact_email="r4@x.com")
    before = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
    assert before["is_listed"] is True, "listed before family limit reached"
    res = place_hold(inv["inventory_id"], rcp["recipient_id"], rcp["headers"], 1,
                     before["version"])
    validate_success(api.confirm_reservation(res["id"], CM))
    ship = validate_success(api.create_shipment({
        "reservation_id": res["id"], "clinic_address": "4 Clinic Way",
        "ln2_dewar_serial": "DS-4",
    }, LT), expected_status=201)
    validate_success(api.dispatch_shipment(ship["id"], LT))
    confirm_one_family(inv["donor_id"], rcp["recipient_id"], rcp["headers"])
    donor = validate_success(api.get_donor(inv["donor_id"], SO))
    assert donor["reported_family_count"] == 1
    assert donor["is_family_limit_reached"] is True
    after = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
    assert after["is_listed"] is False, "only is_family_limit_reached flipped"


def test_is_listed_true_when_all_five_inputs_satisfied(api):
    """PRD §3.5: "An inventory lot is catalog-listed (is_listed true) precisely when
    all of the following hold together: its specimen is RELEASED, its donor is
    ACTIVE, the donor's is_family_limit_reached is false, its hold_status is OPEN,
    and its available_vials is greater than 0."

    A freshly released lot on an ACTIVE donor below family limit, OPEN, with vials
    available, satisfies all five inputs -> is_listed true.

    Design: Difficulty/combinatorial_formula/is_listed_multi_input_conjunction
    """
    inv = setup_listed_inventory(display_code="D-4c", blood_type="B_POS",
                                 family_limit=10, initial_vial_count=5,
                                 dewar_code="T-4c")
    lot = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
    assert lot["is_listed"] is True
    assert lot["hold_status"] == "OPEN"
    assert lot["available_vials"] == 5
    donor = validate_success(api.get_donor(inv["donor_id"], SO))
    assert donor["status"] == "ACTIVE"
    assert donor["is_family_limit_reached"] is False


def test_reserve_more_than_available_rejected(api):
    """PRD §3.4: "the requested vial_count must not exceed the lot's available_vials;
    a request for more than are available is rejected with ERR_INSUFFICIENT_VIALS."

    Design: Difficulty/boundary_precision_check/vial_count_exact_available_boundary_on_reserve
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-12", blood_type="AB_NEG", dewar_code="T-12",
        initial_vial_count=5)
    resp = api.create_vial_reservation({
        "recipient_id": ctx["recipient_id"], "inventory_id": ctx["inventory_id"],
        "vial_count": 6, "expected_inventory_version": ctx["inventory_version"],
    }, ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VIALS.value)
    inv = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert inv["available_vials"] == 5, "hold not created; availability unchanged"


def test_reserve_exactly_available_succeeds(api):
    """PRD §3.4: "the requested vial_count must not exceed the lot's available_vials;
    a request for more than are available is rejected with ERR_INSUFFICIENT_VIALS."

    Design: Difficulty/boundary_precision_check/vial_count_exact_available_boundary_on_reserve
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-12b", blood_type="AB_NEG", dewar_code="T-12b",
        initial_vial_count=5)
    data = validate_success(api.create_vial_reservation({
        "recipient_id": ctx["recipient_id"], "inventory_id": ctx["inventory_id"],
        "vial_count": 5, "expected_inventory_version": ctx["inventory_version"],
    }, ctx["headers"]), expected_status=201)
    assert data["status"] == "HELD"


def test_confirm_blocked_when_inventory_frozen_by_deferral(api):
    """PRD §3.4: "A reservation may be cancelled ... and cancellations also arise
    from the system cascades of §3.2." PRD §3.4: "Deferring a donor's screening
    application ... every DonorInventory lot of that donor has its hold_status set
    to FROZEN". PRD §2.6: "An action is only accepted when the target entity's
    status currently sits in a state from which the requested transition is
    defined; otherwise the request is rejected with ERR_INVALID_STATE."

    The deferral cascade cancels the HELD reservation, so confirming it afterward
    fails on state.

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_inventory_open
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-14", blood_type="A_POS", dewar_code="T-14",
        initial_vial_count=5)
    res = place_hold(ctx["inventory_id"], ctx["recipient_id"], ctx["headers"], 2,
                     ctx["inventory_version"])
    defer_donor_via_second_application(ctx["donor_id"])
    inv = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert inv["hold_status"] == "FROZEN"
    reservation = validate_success(api.get_vial_reservation(res["id"], CM))
    assert reservation["status"] == "CANCELLED", "deferral cascade cancelled the HELD hold"
    resp = api.confirm_reservation(res["id"], CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_deferral_freezes_inventory_hold_status(api):
    """PRD §3.4: "every DonorInventory lot of that donor has its hold_status set to
    FROZEN, which blocks any new reservation against it." PRD §3.2: "Deferring a
    donor's screening application (the UNDER_REVIEW -> DEFERRED transition of §3.1)
    sets the donor's status to DEFERRED and cascades across all of the donor's
    material ... every DonorInventory lot of that donor has its hold_status set to
    FROZEN".

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_inventory_open
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-14b", blood_type="A_POS", dewar_code="T-14b",
        initial_vial_count=5)
    before = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert before["hold_status"] == "OPEN"
    defer_donor_via_second_application(ctx["donor_id"])
    after = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert after["hold_status"] == "FROZEN", "confirm precondition hold_status==OPEN now fails"


def test_reservation_missing_consent_wins_over_family_limit(api):
    """PRD §3.4: "First, the recipient must hold a SIGNED RecipientConsent for the
    pairing of that recipient and the donor owning the target inventory; absent such
    a consent, the create is rejected with ERR_CONSENT_MISSING. Second, the donor
    must not have reached its family limit: if the donor's is_family_limit_reached
    is true at create time, the create is rejected with ERR_FAMILY_LIMIT_REACHED."
    PRD §2.10: "the business checks themselves run in a fixed sequence detailed in
    §3.4: consent presence, then family limit, then inventory listability, then vial
    availability, and finally the stale-version guard."

    Design: Difficulty/priority_pair_validation_conflict/consent_vs_family_limit_on_reservation
    """
    # Donor family_limit=1, reached by one CONFIRMED family (recipient A).
    inv = setup_listed_inventory(display_code="D-10", blood_type="B_NEG",
                                 family_limit=1, initial_vial_count=5, dewar_code="T-10")
    rcp_a = setup_recipient_with_consent(inv["donor_id"], family_name="Fam A",
                                         contact_email="a@x.com")
    before = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
    res_a = place_hold(inv["inventory_id"], rcp_a["recipient_id"], rcp_a["headers"], 1,
                       before["version"])
    validate_success(api.confirm_reservation(res_a["id"], CM))
    ship = validate_success(api.create_shipment({
        "reservation_id": res_a["id"], "clinic_address": "A Clinic",
        "ln2_dewar_serial": "DS-A",
    }, LT), expected_status=201)
    validate_success(api.dispatch_shipment(ship["id"], LT))
    confirm_one_family(inv["donor_id"], rcp_a["recipient_id"], rcp_a["headers"])
    donor = validate_success(api.get_donor(inv["donor_id"], SO))
    assert donor["is_family_limit_reached"] is True
    # Recipient B: NO signed consent, and donor family limit reached.
    rcp_b = validate_success(api.create_recipient({
        "family_name": "Fam B", "contact_email": "b@x.com"}, CM), expected_status=201)
    inv_now = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
    resp = api.create_vial_reservation({
        "recipient_id": rcp_b["id"], "inventory_id": inv["inventory_id"],
        "vial_count": 1, "expected_inventory_version": inv_now["version"],
    }, make_recipient_headers(rcp_b["id"]))
    validate_error(resp, ApiErrorId.ERR_CONSENT_MISSING.value)


def test_reservation_family_limit_reached_with_consent_present(api):
    """PRD §3.4: "Second, the donor must not have reached its family limit: if the
    donor's is_family_limit_reached is true at create time, the create is rejected
    with ERR_FAMILY_LIMIT_REACHED."

    Family-limit is the second business check; once a SIGNED consent is present it is
    the first error a reservation against a limit-reached donor hits.

    Design: Difficulty/priority_pair_validation_conflict/consent_vs_family_limit_on_reservation
    """
    inv = setup_listed_inventory(display_code="D-10b", blood_type="B_NEG",
                                 family_limit=1, initial_vial_count=5, dewar_code="T-10b")
    rcp_a = setup_recipient_with_consent(inv["donor_id"], family_name="Fam A2",
                                         contact_email="a2@x.com")
    before = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
    res_a = place_hold(inv["inventory_id"], rcp_a["recipient_id"], rcp_a["headers"], 1,
                       before["version"])
    validate_success(api.confirm_reservation(res_a["id"], CM))
    ship = validate_success(api.create_shipment({
        "reservation_id": res_a["id"], "clinic_address": "A2 Clinic",
        "ln2_dewar_serial": "DS-A2",
    }, LT), expected_status=201)
    validate_success(api.dispatch_shipment(ship["id"], LT))
    confirm_one_family(inv["donor_id"], rcp_a["recipient_id"], rcp_a["headers"])
    donor = validate_success(api.get_donor(inv["donor_id"], SO))
    assert donor["is_family_limit_reached"] is True
    # Recipient B WITH a signed consent, but donor family limit reached.
    rcp_b = setup_recipient_with_consent(inv["donor_id"], family_name="Fam B2",
                                         contact_email="b2@x.com")
    inv_now = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
    resp = api.create_vial_reservation({
        "recipient_id": rcp_b["recipient_id"], "inventory_id": inv["inventory_id"],
        "vial_count": 1, "expected_inventory_version": inv_now["version"],
    }, rcp_b["headers"])
    validate_error(resp, ApiErrorId.ERR_FAMILY_LIMIT_REACHED.value)


def test_vial_pool_conserved_after_reserve_then_cancel(api):
    """PRD §3.5: "The lot's reserved_vials is the sum of vial_count over every
    reservation in HELD or CONFIRMED on the lot ... The booking view,
    available_vials, is the lot's total_vials minus reserved_vials minus
    shipped_vials". PRD §3.4: "Cancelling a HELD reservation subtracts its vial_count
    from the lot's reserved_vials and recomputes available_vials and is_listed."

    Design: Difficulty/compensating_invariant/vial_pool_conserved_reserve_then_cancel
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-16", dewar_code="T-16", initial_vial_count=5)
    res = place_hold(ctx["inventory_id"], ctx["recipient_id"], ctx["headers"], 2,
                     ctx["inventory_version"])
    validate_success(api.cancel_reservation(res["id"], CM))
    inv = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert inv["total_vials"] == 5
    assert inv["reserved_vials"] == 0
    assert inv["shipped_vials"] == 0
    assert inv["available_vials"] == 5
    assert_inventory_pool_conserved(inv)


def test_vial_pool_conserved_while_hold_is_held(api):
    """PRD §3.5: "The lot's reserved_vials is the sum of vial_count over every
    reservation in HELD or CONFIRMED on the lot ... The booking view, available_vials,
    is the lot's total_vials minus reserved_vials minus shipped_vials".

    While a 2-vial HELD hold exists on a 5-vial lot, the pool identity total ==
    available + reserved + shipped still holds (5 == 3 + 2 + 0).

    Design: Difficulty/compensating_invariant/vial_pool_conserved_reserve_then_cancel
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-16b", dewar_code="T-16b", initial_vial_count=5)
    place_hold(ctx["inventory_id"], ctx["recipient_id"], ctx["headers"], 2,
               ctx["inventory_version"])
    inv = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert inv["total_vials"] == 5
    assert inv["reserved_vials"] == 2
    assert inv["available_vials"] == 3
    assert inv["shipped_vials"] == 0
    assert_inventory_pool_conserved(inv)
