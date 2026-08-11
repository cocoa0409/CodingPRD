"""Registration fee variants, tiered math, and processing-fee bracket order."""
import pytest

from test_helpers import (
    validate_success, validate_paginated, ApiErrorId,
    create_carrier, submit_registration, approve_registration, pay_outstanding,
    list_invoices, set_clock, create_incident,
    api_client, assert_same_instant,
)
from test_helpers.fixtures import ADMIN, REGULATOR, _ok


# ---------------------------------------------------------------------------
# dual_variant_calc / registration_fee_provisional_vs_final
# ---------------------------------------------------------------------------

def test_registration_fee_provisional_variant_uses_declared_fleet_without_discount(api):
    """PRD §3.1: "The provisional fee computed at submission uses
    `fleet_size_declared` and never applies a safety discount."
    PRD §3.1: "A fleet of at most 10 power units is `SMALL` with a base of
    25000 cents" and "otherwise it is a flat 2500 cents."

    Design: Difficulty/dual_variant_calc/registration_fee_provisional_vs_final
    """
    carrier = create_carrier(fleet_size_declared=5, hazmat_categories=["FLAMMABLE_LIQUID"],
                             accepts_dangerous_placard_substitution=False)
    invoice = submit_registration(carrier)
    # base 25000 + no surcharge + flat processing 2500
    assert invoice["provisional_total_cents"] == 27500, (
        f"provisional must be 27500, got {invoice['provisional_total_cents']}")
    assert invoice["total_due_cents"] == 27500
    assert invoice["kind"] == "INITIAL"


def test_registration_fee_final_variant_applies_safety_discount_and_replaces_due(api):
    """PRD §3.1: "the same tiered schedule, but with `verified_fleet_size` as the
    fleet input and with a safety discount now applied — 5 percent of the base
    when the carrier's `safety_rating` is at least 95" and "The recomputed
    figure replaces the provisional one: `final_total_cents` is set, and
    `total_due_cents` switches from the provisional amount to the final amount."
    PRD §3.2: "the carrier's `outstanding_balance_cents` is always the sum, over
    exactly its `OPEN` invoices, of each invoice's `total_due_cents` minus its
    `paid_cents`".

    Design: Difficulty/dual_variant_calc/registration_fee_provisional_vs_final
    """
    carrier = create_carrier(fleet_size_declared=5, hazmat_categories=["FLAMMABLE_LIQUID"])
    invoice = submit_registration(carrier)
    approve_registration(carrier, verified_fleet_size=5)
    invoices = list_invoices(carrier["id"])
    inv = invoices[0]
    # final: base 25000 - discount 1250 = 23750 subtotal + flat 2500 = 26250
    assert inv["provisional_total_cents"] == 27500
    assert inv["final_total_cents"] == 26250
    assert inv["total_due_cents"] == 26250
    assert inv["provisional_total_cents"] != inv["final_total_cents"], (
        "the two variants must diverge by the 1250 discount")
    fresh = validate_success(api.get_carrier(carrier["id"], REGULATOR))
    assert fresh["outstanding_balance_cents"] == 26250


# ---------------------------------------------------------------------------
# dual_variant_calc / incident_penalty_reported_vs_confirmed
# ---------------------------------------------------------------------------

def _setup_late_major_incident():
    """Carrier APPROVED_ACTIVE, fees paid; DRAFT shipment; MAJOR incident with a
    late phone report and a written filing 3 days past deadline."""
    from test_helpers import (
        create_approved_carrier_paid, create_standard_catalog, create_shipment,
    )
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    shipment = create_shipment(carrier["id"], material["id"], spec["id"])
    incident = create_incident(shipment["id"], occurred_at="2026-06-01T00:00:00Z", severity="MAJOR")
    return carrier, incident


def test_incident_penalty_reported_variant_computed_at_file_written(api):
    """PRD §3.9: "`phone_deadline` is twelve hours after `occurred_at`; and
    `written_report_deadline` is thirty days after `occurred_at`."
    PRD §3.9: "a severity base of 0 cents for `MINOR`, 50000 for `MAJOR`, or
    150000 for `CATASTROPHIC`; plus 25000 cents when `is_phone_late`; plus a
    written-lateness component of 5000 cents per full day late".

    Design: Difficulty/dual_variant_calc/incident_penalty_reported_vs_confirmed
    """
    carrier, incident = _setup_late_major_incident()
    assert incident["phone_report_required"] is True
    assert_same_instant(incident["phone_deadline"], "2026-06-01T12:00:00Z")
    assert_same_instant(incident["written_report_deadline"], "2026-07-01T00:00:00Z")

    from test_helpers.fixtures import OFFICER_A
    set_clock("2026-06-02T00:00:00Z")  # 12h deadline missed
    _ok(api.record_phone_report(incident["id"], OFFICER_A), "phone")
    set_clock("2026-07-04T00:00:00Z")  # 3 days past written deadline
    filed = validate_success(api.file_written_report(incident["id"], OFFICER_A))
    assert filed["is_phone_late"] is True
    assert filed["is_written_late"] is True
    # reported: 50000 base + 25000 late phone + 5000*3 late written = 90000
    assert filed["penalty_cents"] == 90000, (
        f"reported penalty must be 90000, got {filed['penalty_cents']}")


def test_incident_penalty_confirmed_variant_replaces_reported_at_close(api):
    """PRD §3.9: "the whole sum multiplied by one plus `adjustment_percent`
    hundredths, rounded half-up; the confirmed figure replaces the reported
    figure in `penalty_cents`."
    PRD §3.9: "Closing also decrements the carrier's `safety_rating` — 2 points
    for a confirmed `MINOR`, 10 for `MAJOR`, 25 for `CATASTROPHIC`".

    Design: Difficulty/dual_variant_calc/incident_penalty_reported_vs_confirmed
    """
    carrier, incident = _setup_late_major_incident()
    set_clock("2026-06-02T00:00:00Z")
    from test_helpers.fixtures import OFFICER_A
    _ok(api.record_phone_report(incident["id"], OFFICER_A), "phone")
    set_clock("2026-07-04T00:00:00Z")
    filed = validate_success(api.file_written_report(incident["id"], OFFICER_A))
    assert filed["penalty_cents"] == 90000

    closed = validate_success(api.close_incident_report(
        incident["id"], {"confirmed_severity": "CATASTROPHIC", "adjustment_percent": 10}, REGULATOR))
    # confirmed: round_half_up((150000 + 25000 + 15000) * 1.10) = 209000
    assert closed["penalty_cents"] == 209000, (
        f"confirmed penalty must be 209000, got {closed['penalty_cents']}")
    carrier_after = validate_success(api.get_carrier(carrier["id"], REGULATOR))
    assert carrier_after["safety_rating"] == 75  # 100 - 25 CATASTROPHIC


# ---------------------------------------------------------------------------
# combinatorial_formula / registration_fee_tiered_surcharge_late
# ---------------------------------------------------------------------------

def _setup_expired_explosive_carrier():
    """EXPLOSIVE carrier approved 2026-05-01, INITIAL invoice paid (38750),
    then clock advanced to 2027-06-20 so the registration is EXPIRED."""
    from test_helpers import create_approved_carrier_paid
    carrier = create_approved_carrier_paid(hazmat_categories=["EXPLOSIVE"])
    set_clock("2027-06-20T00:00:00Z")
    fresh = validate_success(api_client.get_carrier(carrier["id"], REGULATOR))
    return fresh


def test_renewal_after_expiry_carries_late_fee_and_security_surcharge(api):
    """PRD §3.1: "When the carrier's `hazmat_categories` intersect `EXPLOSIVE`,
    `RADIOACTIVE`, or `INHALATION_TOXIC` — which is precisely the condition
    recorded on the carrier as `security_plan_required` — a surcharge of 50
    percent of the base, rounded half-up to whole cents, is added; otherwise the
    surcharge is 0."
    PRD §3.1: "For `RENEWAL` invoices only, a late fee applies: `months_late`
    counts the started calendar months strictly after `registration_expires_at`
    up to the clock" and "the late percentage is the lesser of 10 percent per
    month late and a 50 percent cap, applied to the sum of base and surcharge
    and rounded half-up".

    Design: Difficulty/combinatorial_formula/registration_fee_tiered_surcharge_late
    """
    carrier = _setup_expired_explosive_carrier()
    assert carrier["registration_status"] == "EXPIRED"
    invoice = submit_registration(carrier)
    assert invoice["kind"] == "RENEWAL"
    # base 25000 + surcharge 12500 + late round((25000+12500)*0.20)=7500
    # => subtotal 45000 < 100000 => flat 2500
    assert invoice["provisional_total_cents"] == 47500, (
        f"provisional must be 47500, got {invoice['provisional_total_cents']}")


def test_initial_explosive_registration_math_then_clock_expiry(api):
    """PRD §3.1: "a surcharge of 50 percent of the base, rounded half-up to
    whole cents, is added; otherwise the surcharge is 0."
    PRD §2.4: "any carrier whose `registration_expires_at` has been passed moves
    from `APPROVED_ACTIVE` to `EXPIRED`".

    Design: Difficulty/combinatorial_formula/registration_fee_tiered_surcharge_late
    """
    from test_helpers import create_carrier, submit_registration, approve_registration
    carrier = create_carrier(fleet_size_declared=5, hazmat_categories=["EXPLOSIVE"])
    invoice = submit_registration(carrier)
    # provisional: (25000 + 12500) subtotal 37500 + flat 2500 = 40000
    assert invoice["provisional_total_cents"] == 40000
    approved = approve_registration(carrier, verified_fleet_size=5)
    inv = list_invoices(carrier["id"])[0]
    # final: base 25000 - discount 1250 => subtotal 36250 + flat 2500 = 38750
    assert inv["final_total_cents"] == 38750
    paid = pay_outstanding(carrier["id"])
    assert paid["outstanding_balance_cents"] == 0
    assert approved["registration_expires_at"] is not None
    set_clock("2027-06-20T00:00:00Z")
    fresh = validate_success(api.get_carrier(carrier["id"], REGULATOR))
    assert fresh["registration_status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# combinatorial_formula / renewal_processing_fee_subtotal_bracket
# ---------------------------------------------------------------------------

def _setup_rating90_medium_carrier(api):
    """MEDIUM fleet 25 carrier, INITIAL paid (97500), one on-time MAJOR incident
    closed MAJOR (rating 100 -> 90), clock inside the early-renewal window."""
    from test_helpers import (
        create_approved_carrier_paid, create_standard_catalog, create_shipment,
    )
    carrier = create_approved_carrier_paid(fleet_size_declared=25,
                                           hazmat_categories=["FLAMMABLE_LIQUID"])
    inv1 = list_invoices(carrier["id"])[0]
    material, spec = create_standard_catalog()
    shipment = create_shipment(carrier["id"], material["id"], spec["id"])
    incident = create_incident(shipment["id"], occurred_at="2026-05-02T00:00:00Z", severity="MAJOR")
    set_clock("2026-05-02T01:00:00Z")
    from test_helpers.fixtures import OFFICER_A
    _ok(api.record_phone_report(incident["id"], OFFICER_A), "phone")
    set_clock("2026-05-03T00:00:00Z")
    _ok(api.file_written_report(incident["id"], OFFICER_A), "written")
    _ok(api.close_incident_report(
        incident["id"], {"confirmed_severity": "MAJOR", "adjustment_percent": 0}, REGULATOR), "close")
    set_clock("2027-04-15T00:00:00Z")
    fresh = validate_success(api.get_carrier(carrier["id"], REGULATOR))
    return fresh, inv1


def test_renewal_processing_fee_bracket_keyed_on_pre_fee_subtotal(api):
    """PRD §3.1: "when the subtotal, evaluated before the fee is added, is at
    least 100000 cents, the fee is 3 percent of that subtotal rounded half-up;
    otherwise it is a flat 2500 cents."
    PRD §3.1: "2.5 percent when the rating is at least 90 but below 95".

    Design: Difficulty/combinatorial_formula/renewal_processing_fee_subtotal_bracket
    """
    carrier, _ = _setup_rating90_medium_carrier(api)
    assert carrier["safety_rating"] == 90  # 100 - 10 MAJOR
    invoice = submit_registration(carrier)
    approve_registration(carrier, verified_fleet_size=25)
    invoices = list_invoices(carrier["id"])
    inv2 = invoices[1]
    # RENEWAL provisional: no discount, months_late 0; subtotal 100000 >= 100000 => 3% = 3000
    assert inv2["provisional_total_cents"] == 103000, (
        f"renewal provisional must be 103000, got {inv2['provisional_total_cents']}")
    # RENEWAL final: base 100000 - 2.5% discount 2500 = subtotal 97500 < 100000 => flat 2500
    assert inv2["final_total_cents"] == 100000, (
        f"renewal final must be 100000, got {inv2['final_total_cents']}")


def test_initial_invoice_medium_fleet_discount_selects_flat_fee(api):
    """PRD §3.1: "a fleet of 11 through 50 is `MEDIUM` with a base of 100000
    cents" and "5 percent of the base when the carrier's `safety_rating` is at
    least 95" and "when the subtotal, evaluated before the fee is added, is at
    least 100000 cents, the fee is 3 percent of that subtotal rounded half-up;
    otherwise it is a flat 2500 cents."

    Design: Difficulty/combinatorial_formula/renewal_processing_fee_subtotal_bracket
    """
    carrier, inv1 = _setup_rating90_medium_carrier(api)
    # INITIAL at rating 100: provisional subtotal 100000 => 3% 3000 => 103000;
    # final: discount 5000 => subtotal 95000 => flat 2500 => 97500
    assert inv1["provisional_total_cents"] == 103000
    assert inv1["final_total_cents"] == 97500
    assert inv1["status"] == "PAID"  # the setup paid exactly 97500
