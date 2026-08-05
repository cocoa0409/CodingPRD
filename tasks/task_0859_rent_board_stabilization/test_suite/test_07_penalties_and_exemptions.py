"""Penalties (overcharge variants, four-eyes) and exemptions/vacancy decontrol.

Sources: Difficulty/dual_variant_calc, Difficulty/combinatorial_formula,
Difficulty/priority_pair_validation_conflict, Corner/calculations,
Corner/validations, Corner/state_machines, Corner/rbac.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    make_landlord_headers, make_tenant_headers, make_compliance_officer_headers,
    create_penalty_payload,
    setup_landlord_and_unit, setup_buyout_draft, setup_exemption_requested,
    assess_penalty,
)


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/overcharge_treble_vs_interest
# ---------------------------------------------------------------------------
def test_willful_overcharge_treble(api):
    """PRD §3.9: "When the overcharge is willful, the assessed amount is that base
    multiplied by three (treble damages, with no interest component)."
    (base = 10 * 13400 = 134000; treble = 402000.)

    Design: Difficulty/dual_variant_calc/overcharge_treble_vs_interest
    """
    base = setup_landlord_and_unit(api, base_rent_cents=250000, bedrooms=1)
    penalty = assess_penalty(api, base["unit_id"], base["landlord_id"], "OVERCHARGE",
                             "co-1", months_overcharged=10, monthly_overcharge_cents=13400,
                             willful=True)
    assert penalty["assessed_amount_cents"] == 402000


def test_non_willful_overcharge_base_plus_interest(api):
    """PRD §3.9: "When it is not willful, interest is added ... the assessed amount is the
    base plus that total interest." (base 134000 + interest 1010 = 135010.)

    Design: Difficulty/dual_variant_calc/overcharge_treble_vs_interest
    """
    base = setup_landlord_and_unit(api, base_rent_cents=250000, bedrooms=1)
    penalty = assess_penalty(api, base["unit_id"], base["landlord_id"], "OVERCHARGE",
                             "co-1", months_overcharged=10, monthly_overcharge_cents=13400,
                             willful=False)
    assert penalty["assessed_amount_cents"] == 135010


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/overcharge_interest_rounding_order_mode_b
# ---------------------------------------------------------------------------
def test_overcharge_interest_rounded_per_month_then_summed(api):
    """PRD §3.9: "the per-month interest is monthly_overcharge_cents multiplied by the
    monthly interest rate of 0.0075 ... rounded half-up to whole cents; that per-month
    interest is then multiplied by months_overcharged to give the total interest".
    (round(13400 * 0.0075) = 101; 101 * 10 = 1010; 134000 + 1010 = 135010.)

    Design: Difficulty/combinatorial_formula/overcharge_interest_rounding_order_mode_b
    """
    base = setup_landlord_and_unit(api, base_rent_cents=400000, bedrooms=3)
    penalty = assess_penalty(api, base["unit_id"], base["landlord_id"], "OVERCHARGE",
                             "co-9", months_overcharged=10, monthly_overcharge_cents=13400,
                             willful=False)
    assert penalty["assessed_amount_cents"] == 135010


def test_overcharge_interest_not_summed_then_rounded(api):
    """PRD §3.9: "The rounding order is pinned: interest is rounded to whole cents per
    month first and then multiplied by the month count, not summed and rounded once."
    (A sum-then-round implementation would yield 135005; the pinned order yields 135010.)

    Design: Difficulty/combinatorial_formula/overcharge_interest_rounding_order_mode_b
    """
    base = setup_landlord_and_unit(api, base_rent_cents=400000, bedrooms=3)
    penalty = assess_penalty(api, base["unit_id"], base["landlord_id"], "OVERCHARGE",
                             "co-9", months_overcharged=10, monthly_overcharge_cents=13400,
                             willful=False)
    assert penalty["assessed_amount_cents"] == 135010
    assert penalty["assessed_amount_cents"] != 135005


# ---------------------------------------------------------------------------
# Corner/calculations/late_registration_flat_penalty
# ---------------------------------------------------------------------------
def test_late_registration_flat_penalty(api):
    """PRD §3.9: "A LATE_REGISTRATION penalty is a flat 50000 cents (five hundred dollars)."

    Design: Corner/calculations/late_registration_flat_penalty
    """
    base = setup_landlord_and_unit(api, base_rent_cents=200000, bedrooms=1)
    penalty = assess_penalty(api, base["unit_id"], base["landlord_id"], "LATE_REGISTRATION",
                             "co-late")
    assert penalty["assessed_amount_cents"] == 50000


# ---------------------------------------------------------------------------
# Corner/rbac/penalty_confirm_same_officer_sod_violation
# ---------------------------------------------------------------------------
def test_penalty_confirm_same_officer_sod_violation(api):
    """PRD §3.9: "The confirming officer must differ from the assessor: a confirmation
    whose X-User-ID equals the penalty's assessed_by is rejected with ERR_SOD_VIOLATION."

    Design: Corner/rbac/penalty_confirm_same_officer_sod_violation
    """
    base = setup_landlord_and_unit(api)
    penalty = assess_penalty(api, base["unit_id"], base["landlord_id"], "LATE_REGISTRATION", "co-x")
    resp = api.confirm_penalty(penalty["id"], make_compliance_officer_headers("co-x"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)


# ---------------------------------------------------------------------------
# Corner/state_machines/penalty_confirm_from_confirmed_invalid_state
# ---------------------------------------------------------------------------
def test_penalty_confirm_from_confirmed_invalid_state(api):
    """PRD §3.9: "A penalty is finalized by a second compliance officer confirming it,
    moving it ASSESSED → CONFIRMED".
    PRD §2.8: "State — the target resource is in a state from which the requested
    transition is defined, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/penalty_confirm_from_confirmed_invalid_state
    """
    base = setup_landlord_and_unit(api)
    penalty = assess_penalty(api, base["unit_id"], base["landlord_id"], "LATE_REGISTRATION", "co-a")
    get_success_data(api.confirm_penalty(penalty["id"], make_compliance_officer_headers("co-b")))
    resp = api.confirm_penalty(penalty["id"], make_compliance_officer_headers("co-c"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/disclosure_safety_outranks_relocation_fiscal
# ---------------------------------------------------------------------------
def test_disclosure_outranks_relocation_below_minimum(api):
    """PRD §2.8: endpoint-specific checks follow in priority order "disclosure required
    (ERR_DISCLOSURE_REQUIRED) ... relocation-below-minimum (ERR_RELOCATION_BELOW_MINIMUM)";
    the earlier-listed disclosure check wins when both fail.
    PRD §3.7: "a filing where `disclosure_acknowledged` is not true is rejected with
    `ERR_DISCLOSURE_REQUIRED`".

    Design: Difficulty/priority_pair_validation_conflict/disclosure_safety_outranks_relocation_fiscal
    """
    ctx = setup_buyout_draft(api, relocation_amount_cents=100000, offer_amount_cents=3000000)
    resp = api.file_buyout(ctx["buyout_id"], {"disclosure_acknowledged": False},
                           make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_REQUIRED)


def test_relocation_below_minimum_isolated(api):
    """PRD §3.7: "the relocation_amount_cents must be at least the relocation floor of
    500000 cents (five thousand dollars); a value one cent below the floor is rejected with
    ERR_RELOCATION_BELOW_MINIMUM". (Disclosure acknowledged so only the fiscal check fails,
    confirming the disclosure/relocation precedence.)

    Design: Difficulty/priority_pair_validation_conflict/disclosure_safety_outranks_relocation_fiscal
    """
    ctx = setup_buyout_draft(api, relocation_amount_cents=100000, offer_amount_cents=3000000)
    resp = api.file_buyout(ctx["buyout_id"], {"disclosure_acknowledged": True},
                           make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_RELOCATION_BELOW_MINIMUM)


# ---------------------------------------------------------------------------
# Corner/validations — vacancy decontrol gates
# ---------------------------------------------------------------------------
def test_vacancy_decontrol_threshold_exact_boundary(api):
    """PRD §3.8: "the exemption's vacancy_rent_cents must be at least the decontrol
    threshold of 500000 cents (five thousand dollars) — a value at the threshold passes ...
    When both gates pass, approval moves the unit from STABILIZED to DECONTROLLED."

    Design: Corner/validations/vacancy_decontrol_threshold_exact_boundary
    """
    ctx = setup_exemption_requested(api, "VACANCY_DECONTROL", bedrooms=3, base_rent_cents=480000,
                                    exemption_fields={"vacancy_rent_cents": 500000})
    exemption = validate_success(api.decide_exemption(
        ctx["exemption_id"], {"decision": "APPROVE", "effective_date": "2026-06-01"},
        make_compliance_officer_headers("co-dec")))
    assert exemption["status"] == "APPROVED"
    unit = validate_success(api.get_unit(ctx["unit_id"], make_compliance_officer_headers("co-dec")))
    assert unit["stabilization_status"] == "DECONTROLLED"


def test_vacancy_decontrol_below_threshold_rejected(api):
    """PRD §3.8: "a value one cent below it is rejected with ERR_DECONTROL_THRESHOLD_NOT_MET."

    Design: Corner/validations/vacancy_decontrol_below_threshold_rejected
    """
    ctx = setup_exemption_requested(api, "VACANCY_DECONTROL", bedrooms=3, base_rent_cents=480000,
                                    exemption_fields={"vacancy_rent_cents": 499999})
    resp = api.decide_exemption(
        ctx["exemption_id"], {"decision": "APPROVE", "effective_date": "2026-06-01"},
        make_compliance_officer_headers("co-dec2"))
    validate_error(resp, ApiErrorId.ERR_DECONTROL_THRESHOLD_NOT_MET)


def test_vacancy_decontrol_occupied_unit_rejected(api):
    """PRD §3.8: "the unit must have no ACTIVE tenancy (a decontrol approval on an occupied
    unit is rejected with ERR_UNIT_NOT_VACANT)".

    Design: Corner/validations/vacancy_decontrol_occupied_unit_rejected
    """
    ctx = setup_exemption_requested(api, "VACANCY_DECONTROL", with_active_tenancy=True,
                                    exemption_fields={"vacancy_rent_cents": 600000})
    resp = api.decide_exemption(
        ctx["exemption_id"], {"decision": "APPROVE", "effective_date": "2026-06-01"},
        make_compliance_officer_headers("co-occ"))
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_VACANT)


# ---------------------------------------------------------------------------
# Corner/state_machines/exemption_deny_keeps_unit_stabilized
# ---------------------------------------------------------------------------
def test_exemption_deny_keeps_unit_stabilized(api):
    """PRD §3.8: "Deciding requires the exemption to be `REQUESTED` and the unit to be
    `STABILIZED`. A `DENY` leaves the unit's status unchanged."

    Design: Corner/state_machines/exemption_deny_keeps_unit_stabilized
    """
    ctx = setup_exemption_requested(api, "SUBSTANTIAL_REHAB")
    exemption = validate_success(api.decide_exemption(
        ctx["exemption_id"], {"decision": "DENY"}, make_compliance_officer_headers("co-deny")))
    assert exemption["status"] == "DENIED"
    unit = validate_success(api.get_unit(ctx["unit_id"], make_compliance_officer_headers("co-deny")))
    assert unit["stabilization_status"] == "STABILIZED"
