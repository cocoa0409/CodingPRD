"""License fee computation (tiered / lead / on-time vs late), the renewal expiry
cycle, and the pay/refund money-ledger invariant.
"""
from test_helpers import (
    TEST_USERS, get_success_data, validate_success,
    make_landlord_headers,
    create_landlord, create_property, issue_license,
    setup_property_with_active_license, setup_property_with_pending_license,
    get_property,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def _advance_and_read_license(api, property_id, iso):
    """Advance the logical clock, then read the property's license fresh so its lazy
    ACTIVE→EXPIRED transition and current version are reflected."""
    get_success_data(api.set_clock(iso, REGISTRAR))
    licenses = get_success_data(api.list_property_licenses(property_id, REGISTRAR))
    return licenses[0]


# --- Difficulty: dual_variant_calc / license_fee_on_time_vs_late ---------

def test_issue_fee_uses_on_time_base_variant(api):
    """PRD §3.5: "The annual base is chosen by the property's unit_count: a single-unit
    property has an annual base of 15000 cents; a property of 2 to 4 units, 30000 cents; a
    property of 5 to 20 units, 60000 cents; and a property of more than 20 units, 120000 cents."
    PRD §3.5: "Under the on-time variant — used at issuance and at any renewal performed at or
    before the license's expiry instant — the fee equals that base fee."

    Design: Difficulty/dual_variant_calc/license_fee_on_time_vs_late
    """
    ctx = setup_property_with_active_license(api, unit_count=3, year_built=1980, term_years=1)
    assert ctx["license"]["fee_cents"] == 30000, "2-4 units, no lead, term 1 → 30000 on_time"


def test_late_renewal_uses_late_variant_fee(api):
    """PRD §3.5: "Under the late variant — used at a renewal performed strictly after the
    expiry instant — the base fee is first multiplied by 1.5 and rounded half up to whole
    cents, and then a flat reinstatement fee of 10000 cents is added; for the same inputs the
    late fee is always strictly greater than the on-time fee."
    PRD §3.5: "An ACTIVE license lazily transitions to EXPIRED once the logical clock reaches
    its expires_at, evaluated the next time the license is read or written."

    Design: Difficulty/dual_variant_calc/license_fee_on_time_vs_late
    """
    ctx = setup_property_with_active_license(api, unit_count=3, year_built=1980, term_years=1)
    lic = _advance_and_read_license(api, ctx["property_id"], "2027-06-02T00:00:00Z")
    assert lic["status"] == "EXPIRED", "clock past expires_at → EXPIRED before renew"
    resp = api.renew_license(lic["id"], {"expected_license_version": lic["version"]},
                             make_landlord_headers(ctx["landlord_id"]))
    data = validate_success(resp)
    assert data["fee_cents"] == 55000, "round(30000*1.5)+10000 == 45000+10000 == 55000"
    assert data["status"] == "ACTIVE"


# --- Difficulty: combinatorial_formula / license_fee_tiered_lead_nonlinear

def test_tiered_lead_fee_single_unit_pre1978(api):
    """PRD §3.5: "The annual base is chosen by the property's unit_count: a single-unit
    property has an annual base of 15000 cents; a property of 2 to 4 units, 30000 cents; a
    property of 5 to 20 units, 60000 cents; and a property of more than 20 units, 120000 cents."
    PRD §3.5: "If the property's year_built is earlier than 1978, a lead surcharge of 5000
    cents is added to that annual base, and the license's lead_surcharge_applied flag is set
    to true; otherwise no surcharge applies and the flag is false."

    Design: Difficulty/combinatorial_formula/license_fee_tiered_lead_nonlinear
    """
    landlord = create_landlord(api)
    get_success_data(api.set_clock("2026-06-01T09:00:00Z", REGISTRAR))
    prop = create_property(api, landlord["id"], street_address="30 Pine", unit_count=1, year_built=1950)
    lic = issue_license(api, prop["id"], term_years=1)
    assert lic["fee_cents"] == 20000, "(15000 + 5000 lead) * term 1 == 20000"


def test_tiered_lead_fee_sets_surcharge_flag(api):
    """PRD §3.5: "If the property's year_built is earlier than 1978, a lead surcharge of 5000
    cents is added to that annual base, and the license's lead_surcharge_applied flag is set
    to true; otherwise no surcharge applies and the flag is false."

    Design: Difficulty/combinatorial_formula/license_fee_tiered_lead_nonlinear
    """
    landlord = create_landlord(api)
    get_success_data(api.set_clock("2026-06-01T09:00:00Z", REGISTRAR))
    prop = create_property(api, landlord["id"], street_address="30 Pine", unit_count=1, year_built=1950)
    lic = issue_license(api, prop["id"], term_years=1)
    assert lic["lead_surcharge_applied"] is True, "year_built 1950 < 1978 → surcharge applied"


# --- Difficulty: non_linear_state_machine / license_renewal_expiry_cycle --

def test_active_license_expires_when_clock_passes_expiry(api):
    """PRD §3.5: "An ACTIVE license lazily transitions to EXPIRED once the logical clock
    reaches its expires_at, evaluated the next time the license is read or written."

    Design: Difficulty/non_linear_state_machine/license_renewal_expiry_cycle
    """
    ctx = setup_property_with_active_license(api, unit_count=3, year_built=1980, term_years=1)
    lic = _advance_and_read_license(api, ctx["property_id"], "2027-06-02T00:00:00Z")
    assert lic["status"] == "EXPIRED"


def test_expired_license_renews_back_to_active_incrementing_count(api):
    """PRD §3.5: "Either a Landlord or a Registrar renews a license that is ACTIVE or EXPIRED,
    returning it to ACTIVE."
    PRD §3.5: "Renewal recomputes fee_cents — on-time if the clock is at or before the old
    expires_at, late otherwise — sets a fresh issued_at from the clock, sets expires_at to that
    new issued_at plus term_years years, increments renewal_count by one, adds the new fee_cents
    to the property's total_fees_paid_cents, and increments the license's version."

    Design: Difficulty/non_linear_state_machine/license_renewal_expiry_cycle
    """
    ctx = setup_property_with_active_license(api, unit_count=3, year_built=1980, term_years=1)
    lic = _advance_and_read_license(api, ctx["property_id"], "2027-06-02T00:00:00Z")
    resp = api.renew_license(lic["id"], {"expected_license_version": lic["version"]},
                             make_landlord_headers(ctx["landlord_id"]))
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    assert data["renewal_count"] == 1


# --- Corner: calculations / renewal_on_time_fee_uses_base_variant --------

def test_on_time_renewal_keeps_base_fee(api):
    """PRD §3.5: "Under the on-time variant — used at issuance and at any renewal performed at
    or before the license's expiry instant — the fee equals that base fee."

    Design: Corner/calculations/renewal_on_time_fee_uses_base_variant
    """
    ctx = setup_property_with_active_license(api, unit_count=3, year_built=1980, term_years=1)
    lic = ctx["license"]
    resp = api.renew_license(lic["id"], {"expected_license_version": lic["version"]},
                             make_landlord_headers(ctx["landlord_id"]))
    data = validate_success(resp)
    assert data["fee_cents"] == 30000, "renewal at/before expires_at → on_time base fee 30000"
    assert data["status"] == "ACTIVE"


# --- Difficulty: compensating_invariant / fee_ledger_conserved -----------

def test_pay_increments_fee_ledger(api):
    """PRD §3.5: "On success the system sets issued_at to the current clock, sets expires_at to
    issued_at plus term_years years, adds the paid fee_cents to the property's
    total_fees_paid_cents, points the property's current_license_id at this license, and
    increments the property's version."

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_on_pay_then_refund
    """
    ctx = setup_property_with_pending_license(api, unit_count=3, year_built=1980)
    assert get_property(api, ctx["property_id"])["total_fees_paid_cents"] == 0, "ledger starts at 0"
    get_success_data(api.pay_license(ctx["license"]["id"], {"amount_cents": 30000},
                                     make_landlord_headers(ctx["landlord_id"])))
    assert get_property(api, ctx["property_id"])["total_fees_paid_cents"] == 30000


def test_refund_restores_fee_ledger_and_reverts_license(api):
    """PRD §3.5: "The refund subtracts the most recently paid fee_cents from the property's
    total_fees_paid_cents, restoring the ledger to its pre-payment value, clears the license's
    issued_at and expires_at, and clears the property's current_license_id if it currently
    points at this license."
    PRD §3.5: "A Registrar may refund the most recently paid fee, which reverts an ACTIVE
    license to PENDING_PAYMENT as a compensating action."

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_on_pay_then_refund
    """
    ctx = setup_property_with_pending_license(api, unit_count=3, year_built=1980)
    get_success_data(api.pay_license(ctx["license"]["id"], {"amount_cents": 30000},
                                     make_landlord_headers(ctx["landlord_id"])))
    refunded = get_success_data(api.refund_license(ctx["license"]["id"], REGISTRAR))
    assert refunded["status"] == "PENDING_PAYMENT"
    assert get_property(api, ctx["property_id"])["total_fees_paid_cents"] == 0, \
        "pay(+30000) then refund(-30000) conserves the ledger at 0"
