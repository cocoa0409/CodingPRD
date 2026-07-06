"""Derived calculations: warranty window, adjustment billability windows, repair cost,
prior-auth requirement, and the DMEPOS compliance gate.

Covers Queue B (Corner) section: calculations.
"""
from test_helpers import validate_success, validate_error
from test_helpers.assertions import assert_same_instant
from test_helpers.test_users import TEST_USERS, make_practitioner_headers
from test_helpers.fixtures import (
    setup_delivered_medicare, setup_delivered_no_auth, set_clock, setup_order_at_intake,
    setup_repair_reported, setup_order_ready_no_auth,
)
from test_helpers.factories import deliver_payload


def test_warranty_window_prosthetic_eighteen_months(api):
    """PRD §3.7: "Lower-limb and upper-limb prosthetics — `LOWER_LIMB_PROSTHETIC` and
    `UPPER_LIMB_PROSTHETIC` — carry an eighteen-month term; all orthoses carry a
    twelve-month term."
    PRD §3.5: "On successful delivery the system writes an append-only `ComplianceCheck`
    record for the order, stamps `delivery_date` to the current logical clock, computes
    the `warranty_expiry` (§3.7), advances every `ClaimLine` of the order that is still in
    `DRAFT` to `SUBMITTED`, and increments the order's `version`."

    Design: Corner/calculations/warranty_window_prosthetic_18_months
    """
    # Medicare lower-limb delivered 2026-06-01 -> warranty 2026-06-01 + 18 mo = 2027-12-01.
    cast = setup_delivered_medicare(clock="2026-06-01T00:00:00Z")
    order = cast["order"]
    assert_same_instant(order["delivery_date"], "2026-06-01T00:00:00Z")
    assert_same_instant(order["warranty_expiry"], "2027-12-01T00:00:00Z")


def test_adjustment_free_at_ninety_day_boundary(api):
    """PRD §3.7: "An adjustment dated exactly on the ninety-day cutoff, or exactly on the
    warranty expiry, is not billable."
    PRD §3.7: "The adjustment is `within_warranty` when its `adjustment_date` is at or
    before the order's `warranty_expiry`."

    Design: Corner/calculations/adjustment_free_within_90_days_boundary
    """
    # Orthosis delivered 2026-06-01; clock advanced to 2026-08-30 (== delivery + 90 days).
    cast = setup_delivered_no_auth(clock="2026-06-01T00:00:00Z")
    set_clock("2026-08-30T00:00:00Z")
    adj = validate_success(
        api.create_adjustment(cast["ord_id"], {}, make_practitioner_headers(cast["fit_id"])), 201)
    assert adj["billable"] is False
    assert adj["within_warranty"] is True


def test_adjustment_billable_after_warranty(api):
    """PRD §3.7: "The adjustment is `billable` only when neither window covers it — that
    is, only when its `adjustment_date` is strictly after the ninety-day free-fitting
    cutoff and strictly after the warranty expiry."

    Design: Corner/calculations/adjustment_billable_after_warranty
    """
    # Orthosis delivered 2026-06-01 (warranty 2027-06-01); adjustment dated 2027-07-01 is
    # after both the 90-day cutoff and the warranty expiry.
    cast = setup_delivered_no_auth(clock="2026-06-01T00:00:00Z")
    set_clock("2027-07-01T00:00:00Z")
    adj = validate_success(
        api.create_adjustment(cast["ord_id"], {}, make_practitioner_headers(cast["fit_id"])), 201)
    assert adj["billable"] is True
    assert adj["within_warranty"] is False


def test_repair_cost_out_of_warranty_labor_plus_parts(api):
    """PRD §3.8: "Assessment computes `warranty_applies` and `cost_cents`: the repair is
    in warranty when the report date — the request's `created_at` — is at or before the
    order's `warranty_expiry`, a boundary that is inclusive so that a report dated exactly
    on the warranty expiry is still in warranty. When warranty applies, `cost_cents` is
    0; otherwise the cost is the flat labor fee of 12,500 cents plus the supplied
    `parts_cents`."

    Design: Corner/calculations/repair_cost_out_of_warranty_labor_plus_parts
    """
    # Delivered 2026-06-01 (warranty 2027-06-01); repair reported and assessed 2027-09-01
    # (out of warranty), parts_cents 8000 -> 12500 + 8000 = 20500.
    cast, rr = setup_repair_reported(delivered_clock="2026-06-01T00:00:00Z",
                                     report_clock="2027-09-01T00:00:00Z",
                                     supplier_overrides={"accreditation_expiry": "2030-01-01T00:00:00Z",
                                                         "surety_bond_active": True})
    assessed = validate_success(
        api.assess_repair(rr["id"], {"parts_cents": 8000},
                          make_practitioner_headers(cast["fit_id"])), 200)
    assert assessed["cost_cents"] == 20500
    assert assessed["warranty_applies"] is False


def test_prior_auth_required_for_medicare_lower_limb(api):
    """PRD §3.3: "On successful creation, the system determines whether the order needs
    prior authorization and records the result in `requires_prior_auth`: this is true only
    when the patient's `payer_type` is `MEDICARE` and the prescription's `device_category`
    is either `LOWER_LIMB_PROSTHETIC` or `SPINAL_ORTHOSIS`, and false in all other cases."

    Design: Corner/calculations/prior_auth_requirement_medicare_lower_limb_true
    """
    cast = setup_order_at_intake(device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True)
    assert cast["order"]["requires_prior_auth"] is True


def test_delivery_blocked_when_no_surety_bond(api):
    """PRD §2.9: "The checks, in order, are: first, that the fabricating supplier's
    `accreditation_status` is `ACCREDITED` — failure appends `SUPPLIER_NOT_ACCREDITED`;
    second, that the supplier's `surety_bond_active` is true — failure appends
    `NO_SURETY_BOND`;"
    PRD §3.5: "Second, the DMEPOS compliance gate of §2.9 must pass; when the gate fails
    for any reason other than segregation of duties, delivery is rejected with
    `ERR_COMPLIANCE_GATE_FAILED`."

    Design: Corner/calculations/dmepos_gate_failure_reasons_ordered
    """
    # Supplier ACCREDITED but surety_bond_active false -> the only failing gate check.
    cast = setup_order_ready_no_auth(
        supplier_overrides={"legal_name": "NoBond O&P",
                            "accreditation_expiry": "2028-01-01T00:00:00Z",
                            "surety_bond_active": False})
    res = api.deliver_order(cast["ord_id"], deliver_payload(cast["ord_v"]),
                            make_practitioner_headers(cast["fit_id"]))
    validate_error(res, "ERR_COMPLIANCE_GATE_FAILED")
    order = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert order["status"] == "READY_FOR_FITTING"
