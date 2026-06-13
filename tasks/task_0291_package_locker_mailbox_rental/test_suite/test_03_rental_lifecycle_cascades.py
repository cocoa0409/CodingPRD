"""Rental lifecycle transitions and the cascades they fire.

Covers difficulty instances for the ACTIVE<->SUSPENDED cycle, the suspend->ON_HOLD
depth-2 cascade, and the conserved locker-count invariant; plus corner instances
for close blocking, abandonment sweeps, and close cascades.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_facility_operator_headers, make_compliance_officer_headers,
    setup_active_agreement, setup_agreement_with_forwarding,
    create_facility, create_mailbox, create_customer, create_verified_form,
    create_pending_agreement, receive_package, receive_and_notify_package,
    create_mail_item, advance_clock, get_open_invoice,
)

OP = make_facility_operator_headers()
CO = make_compliance_officer_headers()


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / rental_agreement_active_suspended_cycle
# ---------------------------------------------------------------------------
def test_rental_agreement_active_suspended_cycle(api):
    """PRD §3.3: "Either way the agreement moves ACTIVE → SUSPENDED, and as a
    depth-two cascade every forwarding request in REQUESTED status whose mail item
    belongs to this agreement is placed REQUESTED → ON_HOLD."
    PRD §3.3: "Reactivation moves SUSPENDED → ACTIVE, but only when the invoice
    balance has been brought back to at or below that same 5,000-cent threshold;"

    Design: Difficulty/non_linear_state_machine/rental_agreement_active_suspended_cycle
    """
    # 1-month rental, monthly 3000 -> balance 3000 <= 5000 threshold, autopay OFF.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               autopay_enabled=False, with_locker=False, name="F5")
    agr_id = s["agreement"]["id"]

    susp = validate_success(api.suspend_rental_agreement(agr_id, OP))
    assert susp["status"] == "SUSPENDED", "suspend moves ACTIVE -> SUSPENDED"

    react = validate_success(api.reactivate_rental_agreement(agr_id, OP))
    assert react["status"] == "ACTIVE", "reactivate closes the cycle back to ACTIVE"


def test_active_suspended_active_cycle_alternate(api):
    """PRD §3.3: "Either way the agreement moves ACTIVE → SUSPENDED, and as a
    depth-two cascade every forwarding request in REQUESTED status whose mail item
    belongs to this agreement is placed REQUESTED → ON_HOLD."
    PRD §3.3: "Reactivation moves SUSPENDED → ACTIVE, but only when the invoice
    balance has been brought back to at or below that same 5,000-cent threshold;"

    Design: Difficulty/non_linear_state_machine/rental_agreement_active_suspended_cycle
    """
    s = setup_active_agreement(monthly_fee_cents=2000, term_months=1,
                               autopay_enabled=False, with_locker=False, name="F5b")
    agr_id = s["agreement"]["id"]
    assert validate_success(api.suspend_rental_agreement(agr_id, OP))["status"] == "SUSPENDED"
    assert validate_success(api.reactivate_rental_agreement(agr_id, OP))["status"] == "ACTIVE"
    # A second suspend confirms the cycle is genuinely reusable.
    assert validate_success(api.suspend_rental_agreement(agr_id, OP))["status"] == "SUSPENDED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / suspend_forwarding_on_hold_depth2
# ---------------------------------------------------------------------------
def test_suspend_forwarding_on_hold_depth2(api):
    """PRD §3.3: "Either way the agreement moves ACTIVE → SUSPENDED, and as a
    depth-two cascade every forwarding request in REQUESTED status whose mail item
    belongs to this agreement is placed REQUESTED → ON_HOLD."

    Design: Difficulty/transitive_cascade/suspend_forwarding_on_hold_depth2
    """
    s = setup_agreement_with_forwarding(kind="SCAN", mailbox_size="SMALL",
                                        monthly_fee_cents=2000, term_months=1, name="F8")
    fr_id = s["forwarding_request"]["id"]
    assert s["forwarding_request"]["status"] == "REQUESTED"

    validate_success(api.suspend_rental_agreement(s["agreement"]["id"], OP))
    fr = validate_success(api.get_forwarding_request(fr_id, OP))
    assert fr["status"] == "ON_HOLD", "REQUESTED forwarding must go ON_HOLD on suspend"


def test_reactivate_returns_forwarding_to_requested(api):
    """PRD §3.3: "Reactivation reverses the hold cascade, returning every ON_HOLD
    forwarding request on the agreement's mail to REQUESTED."

    Design: Difficulty/transitive_cascade/suspend_forwarding_on_hold_depth2
    """
    s = setup_agreement_with_forwarding(kind="SCAN", mailbox_size="SMALL",
                                        monthly_fee_cents=2000, term_months=1, name="F8b")
    fr_id = s["forwarding_request"]["id"]
    validate_success(api.suspend_rental_agreement(s["agreement"]["id"], OP))
    assert validate_success(api.get_forwarding_request(fr_id, OP))["status"] == "ON_HOLD"

    validate_success(api.reactivate_rental_agreement(s["agreement"]["id"], OP))
    fr = validate_success(api.get_forwarding_request(fr_id, OP))
    assert fr["status"] == "REQUESTED", "reactivate returns ON_HOLD forwarding to REQUESTED"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / locker_count_conserved_receive_then_pickup
# ---------------------------------------------------------------------------
def test_locker_count_conserved_receive_then_pickup(api):
    """PRD §3.4: "On success a new Package is created in RECEIVED, its locker_unit_id
    set to the assigned locker, which is driven AVAILABLE → OCCUPIED with its
    current_package_id set to the new package and the facility's
    available_locker_count decremented by one."
    PRD §3.4: "Finally the locker is released: it returns OCCUPIED → AVAILABLE, its
    current_package_id is cleared to null, the package's locker_unit_id is cleared,
    and the facility's available_locker_count is incremented."

    Design: Difficulty/compensating_invariant/locker_count_conserved_receive_then_pickup
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               autopay_enabled=False, with_locker=True,
                               locker_size="MEDIUM", name="F17")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]

    before = validate_success(api.get_facility(fac_id, OP))["available_locker_count"]
    assert before == 1, "facility starts with 1 available locker"

    pkg = receive_package(fac_id, agr_id, size_tier="MEDIUM", longest_dim_cm=40, weight_g=3000)
    occupied = validate_success(api.get_facility(fac_id, OP))["available_locker_count"]
    assert occupied == 0, "available drops to 0 while the locker is OCCUPIED"

    notified = validate_success(api.notify_package(pkg["id"], OP))
    code = pkg["pickup_code"]
    validate_success(api.pickup_package(
        pkg["id"], {"pickup_code": code, "expected_package_version": notified["version"]}, OP))

    after = validate_success(api.get_facility(fac_id, OP))["available_locker_count"]
    assert after == 1, "available returns to 1 after pickup (conserved)"


def test_locker_status_and_backref_conserved_receive_then_pickup(api):
    """PRD §3.4: "On success a new Package is created in RECEIVED, its locker_unit_id
    set to the assigned locker, which is driven AVAILABLE → OCCUPIED with its
    current_package_id set to the new package and the facility's available_locker_count
    decremented by one."
    PRD §3.4: "Finally the locker is released: it returns OCCUPIED → AVAILABLE, its
    current_package_id is cleared to null, the package's locker_unit_id is cleared,
    and the facility's available_locker_count is incremented."

    Design: Difficulty/compensating_invariant/locker_count_conserved_receive_then_pickup
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               autopay_enabled=False, with_locker=True,
                               locker_size="MEDIUM", name="F17b")
    fac_id = s["facility"]["id"]
    locker_id = s["locker"]["id"]

    pkg = receive_package(fac_id, s["agreement"]["id"], size_tier="MEDIUM",
                          longest_dim_cm=40, weight_g=3000)
    occ = validate_success(api.get_locker_unit(locker_id, OP))
    assert occ["status"] == "OCCUPIED", "locker is OCCUPIED while holding the package"
    assert occ["current_package_id"] == pkg["id"], "current_package_id points at the package"

    notified = validate_success(api.notify_package(pkg["id"], OP))
    validate_success(api.pickup_package(
        pkg["id"], {"pickup_code": pkg["pickup_code"], "expected_package_version": notified["version"]}, OP))

    released = validate_success(api.get_locker_unit(locker_id, OP))
    assert released["status"] == "AVAILABLE", "locker returns to AVAILABLE (conserved)"
    assert released["current_package_id"] is None, "current_package_id clears to null on release"


# ---------------------------------------------------------------------------
# Corner: state_machines section — close / abandonment cascades
# ---------------------------------------------------------------------------
def test_close_blocked_by_unresolved_package(api):
    """PRD §3.3: "Closure is blocked while any package on the agreement is still
    RECEIVED or NOTIFIED — those are unresolved packages and the attempt is rejected
    with ERR_UNRESOLVED_PACKAGES."

    Design: Corner/state_machines/close_blocked_by_unresolved_package
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="MEDIUM", name="Depot")
    receive_package(s["facility"]["id"], s["agreement"]["id"],
                    size_tier="MEDIUM", longest_dim_cm=40, weight_g=3000)

    resp = api.close_rental_agreement(s["agreement"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_PACKAGES.value)
    after = validate_success(api.get_rental_agreement(s["agreement"]["id"], OP))
    assert after["status"] == "ACTIVE", "agreement must stay ACTIVE when close is blocked"


def test_agreement_abandonment_sweep_cascade(api):
    """PRD §3.3: "Abandonment releases the mailbox RENTED → VACANT, cascades every
    package on the agreement still in RECEIVED or NOTIFIED to ABANDONED (each
    releasing its locker as in §3.4), shreds every STORED mail item, and writes off
    the debt: it posts a WRITE_OFF credit equal to the remaining invoice balance and
    moves the invoice to WRITTEN_OFF."

    Design: Corner/state_machines/agreement_abandonment_sweep_cascade
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               autopay_enabled=False, with_locker=True,
                               locker_size="MEDIUM", name="Depot")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    box_id = s["mailbox"]["id"]
    pkg = receive_package(fac_id, agr_id, size_tier="MEDIUM", longest_dim_cm=40, weight_g=3000)
    mi = create_mail_item(fac_id, agr_id)

    # term_start 2026-06-01, term_end 2026-07-01; advance past term_end + 30d.
    advance_clock(fac_id, "2026-08-01T00:00:00.000Z")

    agr = validate_success(api.get_rental_agreement(agr_id, OP))
    assert agr["status"] == "ABANDONED", "agreement past term_end+30d with balance>0 abandons"
    box = validate_success(api.get_mailbox_unit(box_id, OP))
    assert box["status"] == "VACANT", "mailbox released to VACANT on abandonment"
    pkg_after = validate_success(api.get_package(pkg["id"], OP))
    assert pkg_after["status"] == "ABANDONED", "RECEIVED package cascades to ABANDONED"
    mi_after = validate_success(api.get_mail_item(mi["id"], OP))
    assert mi_after["status"] == "SHREDDED", "STORED mail item is shredded"
    invoice = get_open_invoice(agr_id)
    invoice = validate_success(api.get_invoice(invoice["id"], OP))
    assert invoice["status"] == "WRITTEN_OFF", "invoice moves to WRITTEN_OFF on abandonment"


def test_package_abandonment_sweep_releases_locker(api):
    """PRD §3.4: "During a clock advance, a package still RECEIVED or NOTIFIED whose
    notified_at is now at least the package-abandonment window of 14 days in the past
    is driven to ABANDONED. Like pickup and forward, abandonment finalizes the
    overstay fee, posts the OVERSTAY and OVERSIZE charges, stamps resolved_at, and
    releases the locker."

    Design: Corner/state_machines/package_abandonment_sweep_releases_locker
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=6,
                               autopay_enabled=False, with_locker=True,
                               locker_size="MEDIUM", name="Depot")
    fac_id = s["facility"]["id"]
    locker_id = s["locker"]["id"]
    pkg = receive_and_notify_package(fac_id, s["agreement"]["id"],
                                     size_tier="MEDIUM", longest_dim_cm=40, weight_g=3000)
    # notified at 2026-06-01; advance past notified_at + 14d.
    advance_clock(fac_id, "2026-06-16T00:00:00.000Z")

    pkg_after = validate_success(api.get_package(pkg["id"], OP))
    assert pkg_after["status"] == "ABANDONED", "NOTIFIED package past 14d window abandons"
    locker = validate_success(api.get_locker_unit(locker_id, OP))
    assert locker["status"] == "AVAILABLE", "locker returns to AVAILABLE on package abandonment"


def test_close_cascade_shreds_mail_and_cancels_forwarding(api):
    """PRD §3.3: "every STORED mail item on the agreement is shredded (STORED →
    SHREDDED) and every REQUESTED or ON_HOLD forwarding request on those items is
    cancelled (to CANCELLED); and the invoice is settled if its balance is at or
    below zero, otherwise it stays open."

    Design: Corner/state_machines/close_cascade_shreds_mail_and_cancels_forwarding
    """
    s = setup_agreement_with_forwarding(kind="FORWARD", destination_address="5 Oak Ave",
                                        mailbox_size="MEDIUM", monthly_fee_cents=3000,
                                        term_months=1, name="Depot")
    validate_success(api.close_rental_agreement(s["agreement"]["id"], OP))

    mi = validate_success(api.get_mail_item(s["mail_item"]["id"], OP))
    assert mi["status"] == "SHREDDED", "STORED mail is shredded on close"
    fr = validate_success(api.get_forwarding_request(s["forwarding_request"]["id"], OP))
    assert fr["status"] == "CANCELLED", "REQUESTED forwarding is cancelled on close"
    box = validate_success(api.get_mailbox_unit(s["mailbox"]["id"], OP))
    assert box["status"] == "VACANT", "mailbox returns to VACANT on close"
