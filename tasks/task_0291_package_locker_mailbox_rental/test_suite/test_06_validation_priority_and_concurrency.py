"""Validation-priority conflicts, resource occupancy/overlap, and OCC guarded writes.

Covers difficulty instances for the two priority-pair conflicts, the mailbox
term-overlap and locker point-occupancy rules, and the package-forward
cross-entity gate; plus corner instances for the two OCC stale-version writes,
package receipt against a pending agreement, and mailbox-out-of-service-while-rented.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_facility_operator_headers, make_compliance_officer_headers,
    setup_active_agreement, setup_notified_package,
    create_facility, create_mailbox, create_customer, create_verified_form,
    create_pending_agreement, receive_package, receive_and_notify_package,
    create_form, add_recipient, advance_clock,
)

OP = make_facility_operator_headers()
CO = make_compliance_officer_headers()


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / invalid_state_beats_pickup_code_mismatch
# ---------------------------------------------------------------------------
def test_invalid_state_beats_pickup_code_mismatch(api):
    """PRD §2.10: "Only after those four gates does the system evaluate state
    legality (ERR_INVALID_STATE), then the optimistic-concurrency version match on
    the two guarded writes (ERR_STALE_VERSION), and finally the domain-specific
    business rules — the activation gate, the pickup code, mailbox occupancy, locker
    availability, unresolved packages, the active-required gate, and uniqueness."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_pickup_code_mismatch
    """
    # Package left in RECEIVED (never notified) + a wrong pickup code: state beats code.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="MEDIUM", name="F9")
    pkg = receive_package(s["facility"]["id"], s["agreement"]["id"],
                          size_tier="MEDIUM", longest_dim_cm=40, weight_g=3000)
    v = pkg["version"]
    resp = api.pickup_package(pkg["id"], {"pickup_code": "000000", "expected_package_version": v}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_state_beats_pickup_code_even_with_correct_code(api):
    """PRD §2.10: "Only after those four gates does the system evaluate state
    legality (ERR_INVALID_STATE), then the optimistic-concurrency version match on
    the two guarded writes (ERR_STALE_VERSION), and finally the domain-specific
    business rules — the activation gate, the pickup code, mailbox occupancy, locker
    availability, unresolved packages, the active-required gate, and uniqueness."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_pickup_code_mismatch
    """
    # RECEIVED package (state illegal for pickup); send the CORRECT stored code so
    # only the state gate can fire — confirms state precedes the pickup-code rule.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="MEDIUM", name="F9b")
    pkg = receive_package(s["facility"]["id"], s["agreement"]["id"],
                          size_tier="MEDIUM", longest_dim_cm=40, weight_g=3000)
    resp = api.pickup_package(
        pkg["id"], {"pickup_code": pkg["pickup_code"], "expected_package_version": pkg["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / auth_not_verified_beats_mailbox_occupied
# ---------------------------------------------------------------------------
def test_auth_not_verified_beats_mailbox_occupied(api):
    """PRD §3.3: "Activation is gated by three cross-entity conditions evaluated
    together: the referenced Form1583 must be VERIFIED and the referenced Customer
    must be ACTIVE — either failing yields ERR_AUTH_NOT_VERIFIED — and the referenced
    MailboxUnit must be VACANT, failing which yields ERR_MAILBOX_OCCUPIED."
    PRD §2.10: "Only after those four gates does the system evaluate state legality
    (ERR_INVALID_STATE), then the optimistic-concurrency version match on the two
    guarded writes (ERR_STALE_VERSION), and finally the domain-specific business
    rules — the activation gate, the pickup code, mailbox occupancy, locker
    availability, unresolved packages, the active-required gate, and uniqueness."

    Design: Difficulty/priority_pair_validation_conflict/auth_not_verified_beats_mailbox_occupied
    """
    fac = create_facility(name="F10")
    box = create_mailbox(fac["id"], size_tier="MEDIUM", monthly_fee_cents=3000)
    cust1 = create_customer(fac["id"], full_name="Owner", email="own@x.com", phone="1")
    cust2 = create_customer(fac["id"], full_name="Other", email="oth@x.com", phone="2")

    form1 = create_verified_form(fac["id"], cust1["id"], recipient_name="Owner")
    agr1 = create_pending_agreement(fac["id"], cust1["id"], box["id"], form1["id"], term_months=1)
    get_success_data(api.activate_rental_agreement(agr1["id"], OP))  # mailbox now RENTED

    # Second agreement over the SAME mailbox, but its form is REJECTED (auth fails p7).
    form2 = create_form(fac["id"], cust2["id"], primary_id_type="STATE_ID",
                        address_proof_type="VEHICLE_REG")
    add_recipient(form2["id"], recipient_name="Other")
    get_success_data(api.submit_form_1583(form2["id"], OP))
    get_success_data(api.reject_form_1583(form2["id"], {"rejection_reason": "ID mismatch"}, CO))
    agr2 = create_pending_agreement(fac["id"], cust2["id"], box["id"], form2["id"], term_months=1)

    resp = api.activate_rental_agreement(agr2["id"], OP)
    validate_error(resp, ApiErrorId.ERR_AUTH_NOT_VERIFIED.value)


def test_auth_not_verified_beats_mailbox_occupied_via_suspended_customer(api):
    """PRD §3.3: "Activation is gated by three cross-entity conditions evaluated
    together: the referenced Form1583 must be VERIFIED and the referenced Customer
    must be ACTIVE — either failing yields ERR_AUTH_NOT_VERIFIED — and the referenced
    MailboxUnit must be VACANT, failing which yields ERR_MAILBOX_OCCUPIED."

    Design: Difficulty/priority_pair_validation_conflict/auth_not_verified_beats_mailbox_occupied
    """
    # Same conflict, but the auth failure is a SUSPENDED customer (not a rejected
    # form): auth (p7) still pre-empts mailbox-occupancy (p9).
    fac = create_facility(name="F10b")
    box = create_mailbox(fac["id"], size_tier="MEDIUM", monthly_fee_cents=3000)
    cust1 = create_customer(fac["id"], full_name="Owner", email="own2@x.com", phone="1")
    cust2 = create_customer(fac["id"], full_name="Other", email="oth2@x.com", phone="2")

    form1 = create_verified_form(fac["id"], cust1["id"], recipient_name="Owner")
    agr1 = create_pending_agreement(fac["id"], cust1["id"], box["id"], form1["id"], term_months=1)
    get_success_data(api.activate_rental_agreement(agr1["id"], OP))  # mailbox RENTED

    form2 = create_verified_form(fac["id"], cust2["id"], primary_id_type="STATE_ID",
                                 address_proof_type="VEHICLE_REG", recipient_name="Other")
    agr2 = create_pending_agreement(fac["id"], cust2["id"], box["id"], form2["id"], term_months=1)
    get_success_data(api.suspend_customer(cust2["id"], CO))  # auth precondition now fails

    resp = api.activate_rental_agreement(agr2["id"], OP)
    validate_error(resp, ApiErrorId.ERR_AUTH_NOT_VERIFIED.value)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / mailbox_term_overlap_rejected
# ---------------------------------------------------------------------------
def test_mailbox_term_overlap_rejected(api):
    """PRD §3.3: "A mailbox may back exactly one non-terminal rental at a time;
    activating over a mailbox that is already RENTED or is OUT_OF_SERVICE — its
    occupied closed-open interval from term_start up to but not including term_end
    still live — is the occupancy conflict that ERR_MAILBOX_OCCUPIED reports."

    Design: Difficulty/resource_temporal_overlap/mailbox_term_overlap_rejected
    """
    fac = create_facility(name="F15", clock="2026-06-01T00:00:00.000Z")
    box = create_mailbox(fac["id"], size_tier="MEDIUM", monthly_fee_cents=3000)
    cust1 = create_customer(fac["id"], full_name="Own", email="own15@x.com", phone="1")
    cust2 = create_customer(fac["id"], full_name="Oth", email="oth15@x.com", phone="2")

    form1 = create_verified_form(fac["id"], cust1["id"], recipient_name="Own")
    agr1 = create_pending_agreement(fac["id"], cust1["id"], box["id"], form1["id"], term_months=1)
    get_success_data(api.activate_rental_agreement(agr1["id"], OP))  # mailbox RENTED

    # Second agreement over the SAME mailbox with a VERIFIED form -> overlap rejected.
    form2 = create_verified_form(fac["id"], cust2["id"], primary_id_type="STATE_ID",
                                 address_proof_type="VEHICLE_REG", recipient_name="Oth")
    agr2 = create_pending_agreement(fac["id"], cust2["id"], box["id"], form2["id"], term_months=1)
    resp = api.activate_rental_agreement(agr2["id"], OP)
    validate_error(resp, ApiErrorId.ERR_MAILBOX_OCCUPIED.value)


def test_mailbox_overlap_rejected_when_out_of_service(api):
    """PRD §3.3: "activating over a mailbox that is already RENTED or is
    OUT_OF_SERVICE — its occupied closed-open interval from term_start up to but not
    including term_end still live — is the occupancy conflict that
    ERR_MAILBOX_OCCUPIED reports."

    Design: Difficulty/resource_temporal_overlap/mailbox_term_overlap_rejected
    """
    # The mailbox is OUT_OF_SERVICE (not RENTED) when activation is attempted.
    fac = create_facility(name="F15b", clock="2026-06-01T00:00:00.000Z")
    box = create_mailbox(fac["id"], size_tier="MEDIUM", monthly_fee_cents=3000)
    get_success_data(api.mailbox_out_of_service(box["id"], OP))  # VACANT -> OUT_OF_SERVICE
    cust = create_customer(fac["id"], full_name="Oth", email="oos15@x.com", phone="2")
    form = create_verified_form(fac["id"], cust["id"], recipient_name="Oth")
    agr = create_pending_agreement(fac["id"], cust["id"], box["id"], form["id"], term_months=1)
    resp = api.activate_rental_agreement(agr["id"], OP)
    validate_error(resp, ApiErrorId.ERR_MAILBOX_OCCUPIED.value)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / locker_point_occupancy_no_second_package
# ---------------------------------------------------------------------------
def test_locker_point_occupancy_no_second_package(api):
    """PRD §3.4: "The system then finds a free locker: it must assign an AVAILABLE
    LockerUnit of the requested size_tier, and if none exists the receipt is rejected
    with ERR_NO_LOCKER_AVAILABLE. A locker is occupied by exactly one package at a
    time — an OCCUPIED or OUT_OF_SERVICE locker cannot take a second parcel."

    Design: Difficulty/resource_temporal_overlap/locker_point_occupancy_no_second_package
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="MEDIUM", name="F16")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    # First package occupies the single MEDIUM locker.
    receive_package(fac_id, agr_id, size_tier="MEDIUM", longest_dim_cm=40, weight_g=3000)
    # Second MEDIUM receipt finds zero AVAILABLE MEDIUM lockers.
    resp = api.create_package(
        {"facility_id": fac_id, "rental_agreement_id": agr_id, "carrier": "UPS",
         "size_tier": "MEDIUM", "longest_dim_cm": 40, "weight_g": 3000}, OP)
    validate_error(resp, ApiErrorId.ERR_NO_LOCKER_AVAILABLE.value)


def test_locker_point_occupancy_out_of_service_blocks_receipt(api):
    """PRD §3.4: "it must assign an AVAILABLE LockerUnit of the requested size_tier,
    and if none exists the receipt is rejected with ERR_NO_LOCKER_AVAILABLE. A locker
    is occupied by exactly one package at a time — an OCCUPIED or OUT_OF_SERVICE
    locker cannot take a second parcel."

    Design: Difficulty/resource_temporal_overlap/locker_point_occupancy_no_second_package
    """
    # The only MEDIUM locker is OUT_OF_SERVICE -> zero AVAILABLE -> receipt rejected.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="MEDIUM", name="F16b")
    fac_id = s["facility"]["id"]
    get_success_data(api.locker_out_of_service(s["locker"]["id"], OP))
    resp = api.create_package(
        {"facility_id": fac_id, "rental_agreement_id": s["agreement"]["id"], "carrier": "UPS",
         "size_tier": "MEDIUM", "longest_dim_cm": 40, "weight_g": 3000}, OP)
    validate_error(resp, ApiErrorId.ERR_NO_LOCKER_AVAILABLE.value)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / no_locker_available_empty_pool_on_receipt
# ---------------------------------------------------------------------------
def test_no_locker_available_empty_pool_on_receipt(api):
    """PRD §3.4: "The system then finds a free locker: it must assign an AVAILABLE
    LockerUnit of the requested size_tier, and if none exists the receipt is rejected
    with ERR_NO_LOCKER_AVAILABLE."

    Design: Difficulty/boundary_precision_check/no_locker_available_empty_pool_on_receipt
    """
    # Only a MEDIUM locker exists; a LARGE-tier receipt finds an empty LARGE pool.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="MEDIUM", name="F12")
    resp = api.create_package(
        {"facility_id": s["facility"]["id"], "rental_agreement_id": s["agreement"]["id"],
         "carrier": "UPS", "size_tier": "LARGE", "longest_dim_cm": 60, "weight_g": 8000}, OP)
    validate_error(resp, ApiErrorId.ERR_NO_LOCKER_AVAILABLE.value)


def test_no_locker_available_when_facility_has_no_lockers(api):
    """PRD §3.4: "it must assign an AVAILABLE LockerUnit of the requested size_tier,
    and if none exists the receipt is rejected with ERR_NO_LOCKER_AVAILABLE."

    Design: Difficulty/boundary_precision_check/no_locker_available_empty_pool_on_receipt
    """
    # No lockers at all -> the AVAILABLE-of-size_tier set is empty for any tier.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=False, name="F12b")
    resp = api.create_package(
        {"facility_id": s["facility"]["id"], "rental_agreement_id": s["agreement"]["id"],
         "carrier": "UPS", "size_tier": "MEDIUM", "longest_dim_cm": 40, "weight_g": 3000}, OP)
    validate_error(resp, ApiErrorId.ERR_NO_LOCKER_AVAILABLE.value)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / forward_blocked_when_agreement_suspended
# ---------------------------------------------------------------------------
def test_forward_blocked_when_agreement_suspended(api):
    """PRD §3.4: "The customer or an operator may forward a NOTIFIED package to a
    destination_address, but only while the owning agreement is ACTIVE; forwarding
    against a non-active agreement is rejected with ERR_AGREEMENT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/forward_blocked_when_agreement_suspended
    """
    s = setup_notified_package(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=1, locker_size="MEDIUM", pkg_size="MEDIUM",
                               longest_dim_cm=40, weight_g=3000, name="F14")
    agr_id = s["agreement"]["id"]
    pkg_id = s["package"]["id"]
    validate_success(api.suspend_rental_agreement(agr_id, OP))

    resp = api.forward_package(pkg_id, {"destination_address": "9 Elm St"}, OP)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)
    after = validate_success(api.get_package(pkg_id, OP))
    assert after["status"] == "NOTIFIED", "package stays NOTIFIED when forward is blocked"


def test_forward_succeeds_once_agreement_reactivated(api):
    """PRD §3.4: "The customer or an operator may forward a NOTIFIED package to a
    destination_address, but only while the owning agreement is ACTIVE; forwarding
    against a non-active agreement is rejected with ERR_AGREEMENT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/forward_blocked_when_agreement_suspended
    """
    # Proves the gate is the AGREEMENT state: the same NOTIFIED package forwards
    # successfully once the agreement is returned to ACTIVE.
    s = setup_notified_package(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=1, locker_size="MEDIUM", pkg_size="MEDIUM",
                               longest_dim_cm=40, weight_g=3000, name="F14b")
    agr_id = s["agreement"]["id"]
    pkg_id = s["package"]["id"]
    validate_success(api.suspend_rental_agreement(agr_id, OP))
    validate_error(api.forward_package(pkg_id, {"destination_address": "9 Elm St"}, OP),
                   ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)
    validate_success(api.reactivate_rental_agreement(agr_id, OP))
    forwarded = validate_success(api.forward_package(pkg_id, {"destination_address": "9 Elm St"}, OP))
    assert forwarded["status"] == "FORWARDED", "forward succeeds once the agreement is ACTIVE again"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / occ_renew_stale_version_conflict
# ---------------------------------------------------------------------------
def test_occ_renew_stale_version_conflict(api):
    """PRD §2.5: "The request must carry expected_rental_agreement_version, and that
    value must equal the target RentalAgreement's current version. If another writer
    has advanced the agreement's version since the client last read it — for example,
    a prior renewal that already extended the term and posted another rental charge —
    the renewal is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_renew_stale_version_conflict
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=False, name="Depot")
    agr_id = s["agreement"]["id"]
    v0 = validate_success(api.get_rental_agreement(agr_id, OP))["version"]

    first = validate_success(api.renew_rental_agreement(
        agr_id, {"expected_rental_agreement_version": v0}, OP))
    assert first["renewal_count"] == 1, "first renew succeeds and bumps renewal_count to 1"

    resp = api.renew_rental_agreement(agr_id, {"expected_rental_agreement_version": v0}, OP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / occ_pickup_stale_version_conflict
# ---------------------------------------------------------------------------
def test_occ_pickup_stale_version_conflict(api):
    """PRD §2.5: "A notification (which advances the package version) or a
    clock-driven provisional overstay recompute (which also advances it) can move the
    version after the client's last read; a pickup still carrying the pre-advance
    version is operating on a superseded view of the package's fee and state and is
    rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_pickup_stale_version_conflict
    """
    s = setup_active_agreement(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=1, with_locker=True, locker_size="MEDIUM", name="Depot")
    fac_id = s["facility"]["id"]
    pkg = receive_package(fac_id, s["agreement"]["id"], size_tier="MEDIUM",
                          longest_dim_cm=40, weight_g=3000)
    notified = validate_success(api.notify_package(pkg["id"], OP))
    v_pre = notified["version"]
    # Clock advance recomputes provisional overstay -> bumps the package version.
    advance_clock(fac_id, "2026-06-10T00:00:00.000Z")

    resp = api.pickup_package(
        pkg["id"], {"pickup_code": pkg["pickup_code"], "expected_package_version": v_pre}, OP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = validate_success(api.get_package(pkg["id"], OP))
    assert after["status"] == "NOTIFIED", "package stays NOTIFIED when pickup is stale"


# ---------------------------------------------------------------------------
# Corner: validations / package_receipt_against_pending_agreement_blocked
# ---------------------------------------------------------------------------
def test_package_receipt_against_pending_agreement_blocked(api):
    """PRD §3.4: "Receipt against an agreement that is not ACTIVE is rejected with
    ERR_AUTH_NOT_VERIFIED."

    Design: Corner/validations/package_receipt_against_pending_agreement_blocked
    """
    fac = create_facility(name="Depot")
    box = create_mailbox(fac["id"], size_tier="MEDIUM", monthly_fee_cents=3000)
    locker = get_success_data(api.create_locker_unit(
        {"facility_id": fac["id"], "label": "L1", "size_tier": "MEDIUM"}, OP))
    cust = create_customer(fac["id"], email="a@x.com")
    form = create_form(fac["id"], cust["id"])
    agr = create_pending_agreement(fac["id"], cust["id"], box["id"], form["id"], term_months=1)

    resp = api.create_package(
        {"facility_id": fac["id"], "rental_agreement_id": agr["id"], "carrier": "UPS",
         "size_tier": "MEDIUM", "longest_dim_cm": 40, "weight_g": 3000}, OP)
    validate_error(resp, ApiErrorId.ERR_AUTH_NOT_VERIFIED.value)
    after = validate_success(api.get_locker_unit(locker["id"], OP))
    assert after["status"] == "AVAILABLE", "no locker consumed when receipt is blocked"


# ---------------------------------------------------------------------------
# Corner: errors / mailbox_out_of_service_while_rented_returns_not_vacant
# ---------------------------------------------------------------------------
def test_mailbox_out_of_service_while_rented_returns_not_vacant(api):
    """PRD §3.1: "attempting to take a mailbox out of service while it is RENTED, or
    to restore one that is not OUT_OF_SERVICE, is rejected with ERR_MAILBOX_NOT_VACANT."

    Design: Corner/errors/mailbox_out_of_service_while_rented_returns_not_vacant
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=False, name="Depot")  # mailbox now RENTED
    resp = api.mailbox_out_of_service(s["mailbox"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_MAILBOX_NOT_VACANT.value)
    after = validate_success(api.get_mailbox_unit(s["mailbox"]["id"], OP))
    assert after["status"] == "RENTED", "mailbox stays RENTED when OOS is rejected"
