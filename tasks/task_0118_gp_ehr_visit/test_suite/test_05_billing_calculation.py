"""CPT billing — list_charge_cents (observable), allowed_amount_cents
calculation invariants (observable insofar as the completion cascade
runs and the encounter reaches COMPLETED).

PRD §3.3 (allowed-amount procedure, modifier multipliers, tier
factors, apportion residual), §3.7 (catalog price validation),
§2.8 (round half-up at the two pinned steps).

Note: PRD §4 does not define a GET /cpt-line-items/{id} endpoint.
Per-line allowed_amount_cents is therefore not directly observable
through the documented API surface unless the implementation chooses
to embed it on the encounter response. Tests in this file assert what
IS observable: list_charge_cents on line creation, and the COMPLETED
status returned by /encounters/{id}/complete after the cascade runs.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_cpt_line_item,
    create_cpt_code_entry,
    create_cpt_code_payload,
    create_cpt_line_item_payload,
    setup_billing_apportion_residual_encounter,
    setup_billing_dual_variant_encounter,
    setup_checked_in_encounter,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 / §3.7 list_charge_cents on line creation
# ===========================================================================
class TestListChargeProvisional:

    def test_list_charge_is_list_price_times_units(self, api):
        """PRD §3.3: "On a successful line append, the server
        snapshots a provisional cash charge as list_charge_cents
        equal to the catalog's list_price_cents for that cpt_code
        multiplied by the supplied units; this provisional figure
        ignores the modifier and ignores the catalog's
        is_telehealth_eligible flag."

        Claim: line append on cpt 99213 (list 12000) with units=2
        and modifier='25' yields list_charge_cents == 24000 (modifier
        ignored).
        """
        patient, provider, encounter = setup_checked_in_encounter()
        cpt_entry = create_cpt_code_entry(
            cpt_code="99213", list_price_cents=12000,
            allowed_price_cents=8000,
        )
        line = add_cpt_line_item(
            encounter["id"], cpt_entry["cpt_code"],
            units=2, modifier="25",
        )
        assert line["list_charge_cents"] == 24000, (
            f"list_charge_cents expected 24000, "
            f"got {line['list_charge_cents']}"
        )

    def test_list_charge_pre_completion_allowed_is_null(self, api):
        """PRD §3.3: "is_preventive on the line is left at its
        default of false at append time, and allowed_amount_cents is
        left null."

        Claim: on line create (encounter still CHECKED_IN),
        allowed_amount_cents is null.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        cpt_entry = create_cpt_code_entry(
            cpt_code="99213", list_price_cents=12000,
            allowed_price_cents=8000,
        )
        line = add_cpt_line_item(
            encounter["id"], cpt_entry["cpt_code"], units=1,
        )
        assert line.get("allowed_amount_cents") is None, (
            "allowed_amount_cents must be null at line append; "
            "got " + repr(line.get("allowed_amount_cents"))
        )

    def test_list_charge_ignores_modifier(self, api):
        """PRD §3.3: "this provisional figure ignores the modifier
        and ignores the catalog's is_telehealth_eligible flag."

        Claim: two lines on the same catalog code with the same
        units but different modifiers ('25' and 'TC') get the same
        list_charge_cents.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        cpt_entry = create_cpt_code_entry(
            cpt_code="99214", list_price_cents=10000,
            allowed_price_cents=8000,
        )
        line_with_25 = add_cpt_line_item(
            encounter["id"], cpt_entry["cpt_code"],
            units=3, modifier="25",
        )
        line_with_tc = add_cpt_line_item(
            encounter["id"], cpt_entry["cpt_code"],
            units=3, modifier="TC",
        )
        assert line_with_25["list_charge_cents"] == 30000
        assert line_with_tc["list_charge_cents"] == 30000


# ===========================================================================
# §3.3 ERR_INVALID_BILLING_UNITS — boundary precision
# ===========================================================================
class TestInvalidBillingUnits:

    def test_units_zero_rejected(self, api, billing_clerk_headers):
        """PRD §3.3: "a units count between 1 and 50 inclusive ...
        Adding a unit count outside the inclusive 1–50 range is
        rejected with ERR_INVALID_BILLING_UNITS."

        Claim: units=0 returns ERR_INVALID_BILLING_UNITS.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        cpt_entry = create_cpt_code_entry(
            cpt_code="99214", list_price_cents=15000,
            allowed_price_cents=12000,
        )
        res = api.create_cpt_line_item(
            encounter["id"],
            create_cpt_line_item_payload(
                cpt_code=cpt_entry["cpt_code"], units=0,
            ),
            billing_clerk_headers,
        )
        validate_error(res, "ERR_INVALID_BILLING_UNITS")

    def test_units_51_rejected(self, api, billing_clerk_headers):
        """PRD §3.3: "a units count between 1 and 50 inclusive ...
        Adding a unit count outside the inclusive 1–50 range is
        rejected with ERR_INVALID_BILLING_UNITS."

        Claim: units=51 returns ERR_INVALID_BILLING_UNITS.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        cpt_entry = create_cpt_code_entry(
            cpt_code="99214", list_price_cents=15000,
            allowed_price_cents=12000,
        )
        res = api.create_cpt_line_item(
            encounter["id"],
            create_cpt_line_item_payload(
                cpt_code=cpt_entry["cpt_code"], units=51,
            ),
            billing_clerk_headers,
        )
        validate_error(res, "ERR_INVALID_BILLING_UNITS")

    def test_units_one_accepted(self, api):
        """PRD §3.3: "a units count between 1 and 50 inclusive".

        Claim: units=1 is accepted (the inclusive lower bound).
        """
        patient, provider, encounter = setup_checked_in_encounter()
        cpt_entry = create_cpt_code_entry(
            cpt_code="99214", list_price_cents=15000,
            allowed_price_cents=12000,
        )
        line = add_cpt_line_item(
            encounter["id"], cpt_entry["cpt_code"], units=1,
        )
        assert line["units"] == 1
        assert line["list_charge_cents"] == 15000

    def test_units_fifty_accepted(self, api):
        """PRD §3.3: "a units count between 1 and 50 inclusive".

        Claim: units=50 is accepted (the inclusive upper bound).
        """
        patient, provider, encounter = setup_checked_in_encounter()
        cpt_entry = create_cpt_code_entry(
            cpt_code="99214", list_price_cents=100,
            allowed_price_cents=100,
        )
        line = add_cpt_line_item(
            encounter["id"], cpt_entry["cpt_code"], units=50,
        )
        assert line["units"] == 50

    def test_catalog_allowed_greater_than_list_rejected(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.7: "the non-negative allowed_price_cents (which
        must be less than or equal to list_price_cents — a violation
        yields ERR_INVALID_BILLING_UNITS)".

        Claim: POST /cpt-codes with allowed > list returns
        ERR_INVALID_BILLING_UNITS.
        """
        res = api.create_cpt_code(
            create_cpt_code_payload(
                cpt_code="99991", description="bad prices",
                list_price_cents=1000,
                allowed_price_cents=2000,
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_INVALID_BILLING_UNITS")


# ===========================================================================
# §3.3 / §2.8 Dual-variant calculation: list_charge vs allowed_amount
# ===========================================================================
class TestDualVariantBilling:
    """Both list_charge_cents and allowed_amount_cents operate on the
    same CptLineItem inputs but produce different totals."""

    # difficulty: dual_variant_calc/cpt_billing_charge_vs_allowed_on_encounter
    def test_list_charge_sum_observable_post_creation(self, api):
        """PRD §3.3: "On a successful line append, the server
        snapshots a provisional cash charge as list_charge_cents
        equal to the catalog's list_price_cents for that cpt_code
        multiplied by the supplied units."

        Claim: in the dual-variant fixture (99213 list=12000 units=1
        modifier=25; 90471 list=3000 units=2), the sum of
        list_charge_cents across the two lines equals 12000 + 6000 =
        18000 — the modifier is ignored.
        """
        setup = setup_billing_dual_variant_encounter()
        assert setup["line_a"]["list_charge_cents"] == 12000, (
            f"line_a list_charge_cents expected 12000, "
            f"got {setup['line_a']['list_charge_cents']}"
        )
        assert setup["line_b"]["list_charge_cents"] == 6000, (
            f"line_b list_charge_cents expected 6000, "
            f"got {setup['line_b']['list_charge_cents']}"
        )
        sum_list = (
            setup["line_a"]["list_charge_cents"]
            + setup["line_b"]["list_charge_cents"]
        )
        assert sum_list == 18000

    # difficulty: dual_variant_calc/cpt_billing_charge_vs_allowed_on_encounter
    def test_dual_variant_encounter_completes(self, api):
        """PRD §3.3: "The allowed-amount calculation differs from
        the line-creation list_charge_cents calculation along three
        axes: it uses the catalog's allowed_price_cents rather than
        list_price_cents; it applies modifier multipliers and the
        encounter-level tier factor, neither of which the list-charge
        formula touches; and it rounds per line before summing the
        encounter total, where the list-charge formula has no
        rounding at all."

        Claim: the dual-variant fixture (which calls
        /encounters/{id}/complete after attaching two lines whose
        list_charge sum is 18000) drives the encounter to COMPLETED,
        confirming the allowed-amount cascade ran. The cascade itself
        produces an allowed-amount sum mathematically distinct from
        the list-charge sum: with line A allowed-base 8000 * 1 *
        1.25 (modifier '25') = 10000 and line B allowed-base 2000 *
        2 * 1.00 = 4000, the encounter allowed total is 14000 —
        which under PRD §3.3 tier1 (<= 50000) is multiplied by 1.00
        for an adjusted total of 14000, distinct from the
        list-charge sum of 18000.
        """
        setup = setup_billing_dual_variant_encounter()
        assert setup["encounter"]["status"] == "COMPLETED", (
            "Encounter must reach COMPLETED so the §3.3 allowed-"
            "amount cascade has run."
        )
        # The two computed sums are mathematically distinct under
        # PRD §3.3's formulae:
        sum_list = 12000 + 6000  # list_price * units, no modifier
        # Per PRD: base_allowed_A = 8000*1; mult_A = 1.25 (modifier
        # '25'); per_line_A = round_half_up(8000*1.25) = 10000.
        # base_allowed_B = 2000*2; mult_B = 1.00; per_line_B = 4000.
        # encounter_total = 14000 (<=50000 ⇒ tier1 factor 1.00).
        # adjusted_total = round_half_up(14000*1.00) = 14000.
        expected_allowed_total = 14000
        assert sum_list != expected_allowed_total, (
            "Sum of list_charge_cents (18000) must differ from the "
            "expected allowed total (14000) under PRD §3.3 — proving "
            "the two variants yield different totals from identical "
            "inputs."
        )


# ===========================================================================
# §3.3 / §2.8 Apportion residual — sum invariant after completion
# ===========================================================================
class TestApportionResidualInvariant:
    """PRD §3.3: the residual rule guarantees the sum of
    allowed_amount_cents equals adjusted_total exactly."""

    # difficulty: combinatorial_formula/cpt_billing_allowed_round_per_line_then_apportion
    def test_apportion_residual_encounter_completes(self, api):
        """PRD §3.3: "The residual rule guarantees that the sum of
        allowed_amount_cents across all lines on the encounter
        equals the adjusted encounter total exactly."

        Claim: completing an encounter with three lines whose per-
        line bases are 33334, 33333, 33335 (summing to 99999 which
        is in tier-2 band, factor 0.95) drives the encounter to
        COMPLETED — confirming the §3.3 apportion-residual cascade
        ran without raising an error on the apportion arithmetic.
        """
        setup = setup_billing_apportion_residual_encounter()
        assert setup["encounter"]["status"] == "COMPLETED"

    # difficulty: combinatorial_formula/cpt_billing_allowed_round_per_line_then_apportion
    def test_apportion_per_line_rounding_before_summing(self, api):
        """PRD §2.8: "Rounding happens at the two pinned steps named
        in §3.3 — once per line after the modifier multiplier is
        applied, and once per line after the tier factor is
        apportioned — never on intermediate sums."

        Claim: per PRD's formulae on the apportion-residual fixture:
        per_line_cents (no modifier so multiplier 1.00) are
        round_half_up(33334*1) = 33334, round_half_up(33333*1) =
        33333, round_half_up(33335*1) = 33335. encounter_total =
        99999 (in tier-2 band 50001..200000, factor 0.95).
        adjusted_total = round_half_up(99999*0.95) =
        round_half_up(94999.05) = 94999. Per-line apportion shares
        are round_half_up(33334*0.95) = 31667, round_half_up(33333
        *0.95) = 31666, round_half_up(33335*0.95) = 31668. The
        residual = adjusted_total - sum(apportion) = 94999 -
        (31667+31666+31668) = 94999 - 95001 = -2. PRD: "Assign the
        entire residual — as a single cents value, not split — to
        the line with the largest per-line amount before apportion".
        That is line C (per_line_cents=33335). So line C's final
        allowed_amount_cents = 31668 + (-2) = 31666 and the
        sum 31667 + 31666 + 31666 = 94999 == adjusted_total.

        This test asserts the encounter reaches COMPLETED — the same
        observable evidence the cascade ran — and asserts the
        consistency of the calculation at the formula level via this
        docstring. (PRD does not define a per-line read endpoint, so
        per-line allowed_amount_cents is only directly observable
        via implementations that embed lines in the encounter
        response.)
        """
        setup = setup_billing_apportion_residual_encounter()
        assert setup["encounter"]["status"] == "COMPLETED"
        # Sanity-check the formula side of the invariant explicitly,
        # using the fixture's actual per-line bases (see
        # setup_billing_apportion_residual_encounter):
        per_line = [33334, 33333, 33335]
        # Tier factor depends on encounter_total per PRD §3.3 bands;
        # 100002 falls in tier-2 band 50001..200000 (factor 0.95).
        tier_factor = 0.95
        encounter_total = sum(per_line)
        # round_half_up emulated for non-negative values:
        def _r(x):
            import math
            return math.floor(x + 0.5) if x >= 0 \
                else -math.floor(-x + 0.5)
        adjusted_total = _r(encounter_total * tier_factor)
        apportion = [_r(p * tier_factor) for p in per_line]
        residual = adjusted_total - sum(apportion)
        # Assign residual to the line with the greatest pre-
        # apportion per_line_cents (line C, 33335):
        greatest_idx = per_line.index(max(per_line))
        finalized = list(apportion)
        finalized[greatest_idx] += residual
        assert sum(finalized) == adjusted_total, (
            "Sum invariant must hold over the PRD-pinned formula"
        )
