"""Complement approvals and the GME funding cap: pinned stipend rounding,
headcount vs funded-census variants, the revision cycle, OCC, lockdown, and
role gates (PRD §3.2)."""
from test_helpers import (
    DIO, NON_EXISTENT_UUID, PC, PD, ApiClient, ApiErrorId, approx2,
    assert_complement, create_complement_payload, make_active_resident,
    make_active_year, make_complement, make_program, make_resident, make_year,
    validate_error, validate_success,
)


def _complement_row(api, comp_id):
    return validate_success(api.get_complement(comp_id, PD))


class TestStipendRoundingOrder:
    def test_round_per_block_then_multiply_pinned(self, api: ApiClient):
        """PRD §3.2: "the blended stipend is divided by the thirteen blocks of
        the year, the per-block quotient is rounded half-up to a whole cent,
        and that per-block figure is then multiplied by thirteen. The rounding
        order is pinned — round per block first, then multiply — because the
        reverse order yields a different integer and is forbidden. For example,
        a blended stipend of 6,500,007 cents produces a per-block figure of
        round-half-up of 500,000.538…, i.e. 500,001 cents, and therefore a year
        stipend of 6,500,013 cents — not 6,500,007."
        PRD §3.2: "`effective_funded_positions`: the smaller of
        `approved_positions` and the whole number of resident-years the budget
        affords, computed as the floor of `annual_funding_budget_cents` divided
        by `resident_year_stipend_cents`."

        Design: Difficulty/combinatorial_formula/stipend_round_per_block_then_sum_order
        """
        program = make_program()
        year = make_active_year(program["id"])
        comp = make_complement(program["id"], year["id"], approved_positions=4,
                               annual_funding_budget_cents=13000020,
                               blended_stipend_cents=6500007)
        row = _complement_row(api, comp["id"])
        assert row["resident_year_stipend_cents"] == 6500013, (
            "pinned order: round_half_up(6500007/13) = 500001 per block, x13 "
            f"= 6500013; got {row['resident_year_stipend_cents']}")
        assert row["effective_funded_positions"] == 1, (
            "min(4, floor(13000020 / 6500013)) == 1; got "
            f"{row['effective_funded_positions']}")

    def test_pinned_stipend_drives_funding_cap_at_activation(self, api: ApiClient):
        """PRD §3.3: "The funding gate: the funded census after admitting the
        candidate — `filled_funded_census` plus a full 1.0 position —
        multiplied by `resident_year_stipend_cents` and rounded half-up to
        whole cents must not exceed `annual_funding_budget_cents`; a breach is
        `ERR_FUNDING_CAP_EXCEEDED` (HTTP 402)."

        Design: Difficulty/combinatorial_formula/stipend_round_per_block_then_sum_order
        """
        program = make_program()
        year = make_active_year(program["id"])
        make_complement(program["id"], year["id"], approved_positions=4,
                        annual_funding_budget_cents=13000020,
                        blended_stipend_cents=6500007)
        res_a = make_resident(program["id"], year["id"], full_name="A One")
        res_b = make_resident(program["id"], year["id"], full_name="B Two")

        # round_half_up(1.0 x 6500013) = 6500013 <= 13000020: first passes.
        activated = validate_success(api.activate_resident(res_a["id"], PC))
        assert activated["lifecycle_status"] == "ACTIVE"

        # round_half_up(2.0 x 6500013) = 13000026 > 13000020: second breaches.
        resp = api.activate_resident(res_b["id"], PC)
        validate_error(resp, ApiErrorId.ERR_FUNDING_CAP_EXCEEDED)
        assert resp.status_code == 402
        assert validate_success(api.get_resident(res_b["id"], PD))[
            "lifecycle_status"] == "INCOMING"


class TestHeadcountVsFundedCensus:
    def _setup(self, api):
        program = make_program()
        year = make_active_year(program["id"])
        comp = make_complement(program["id"], year["id"], approved_positions=2,
                               annual_funding_budget_cents=100000000,
                               blended_stipend_cents=6000000)
        res_a = make_active_resident(program["id"], year["id"], full_name="A One")
        res_b = make_active_resident(program["id"], year["id"], full_name="B Two")
        validate_success(api.place_on_leave(res_b["id"], PD))
        res_c = make_resident(program["id"], year["id"], full_name="C Three")
        return program, year, comp, res_a, res_b, res_c

    def test_fill_variants_diverge_on_identical_roster(self, api: ApiClient):
        """PRD §3.2: "`filled_headcount` counts the program's residents at the
        row's `pgy_level` whose `lifecycle_status` is `ACTIVE` or `ON_LEAVE`,
        with each such resident counting as a full 1 — the headcount variant
        used for the ACGME complement cap. `filled_funded_census` sums the same
        residents with a weight of 1.0 for `ACTIVE` and 0.5 for `ON_LEAVE`,
        carried at 2 decimal places — the funded-census variant, which
        deliberately diverges from headcount for identical rosters".

        Design: Difficulty/dual_variant_calc/complement_headcount_vs_funded_census_divergence
        """
        _, _, comp, _, _, _ = self._setup(api)
        row = _complement_row(api, comp["id"])
        assert row["filled_headcount"] == 2, (
            f"headcount variant counts ON_LEAVE as a full 1: {row}")
        assert row["filled_funded_census"] == approx2(1.5), (
            f"funded-census variant weights ON_LEAVE 0.5: {row}")

    def test_headcount_gate_rejects_third_activation(self, api: ApiClient):
        """PRD §3.3: "The headcount gate: the row's `filled_headcount` plus 1
        must not exceed `approved_positions`; a breach is
        `ERR_COMPLEMENT_EXCEEDED` (HTTP 409)."

        Design: Difficulty/dual_variant_calc/complement_headcount_vs_funded_census_divergence
        """
        _, _, comp, _, _, res_c = self._setup(api)
        # headcount 2 + 1 > approved_positions 2 — even though the census
        # variant reads only 1.5 with ample funding headroom.
        resp = api.activate_resident(res_c["id"], PC)
        validate_error(resp, ApiErrorId.ERR_COMPLEMENT_EXCEEDED)
        assert resp.status_code == 409
        assert validate_success(api.get_resident(res_c["id"], PD))[
            "lifecycle_status"] == "INCOMING"
        row = _complement_row(api, comp["id"])
        assert row["filled_headcount"] == 2
        assert row["filled_funded_census"] == approx2(1.5)


class TestComplementRevisionCycle:
    def _setup_rejected(self, api):
        program = make_program()
        year = make_year(program["id"])
        comp = validate_success(api.create_complement(
            create_complement_payload(program["id"], year["id"], pgy_level=2,
                                      approved_positions=3,
                                      annual_funding_budget_cents=50000000,
                                      blended_stipend_cents=6200000),
            PD), expected_status=201)
        assert comp["version"] == 1
        comp = validate_success(api.submit_complement(comp["id"], PD))
        comp = validate_success(api.reject_complement(comp["id"], DIO))
        assert comp["status"] == "REJECTED"
        assert comp["version"] == 3
        return comp

    def test_rejected_row_editable_under_occ(self, api: ApiClient):
        """PRD §3.2: "While the row is `DRAFT` or `REJECTED`, the
        `ProgramDirector` may edit `approved_positions`,
        `annual_funding_budget_cents`, or `blended_stipend_cents` — the edit is
        OCC-protected with `expected_complement_approval_version` (§2.7),
        recomputes both derived figures, and bumps the row's `version`".

        Design: Difficulty/non_linear_state_machine/complement_revision_cycle_rejected_to_resubmitted
        """
        comp = self._setup_rejected(api)
        edited = validate_success(api.update_complement(
            comp["id"], {"approved_positions": 6,
                         "expected_complement_approval_version": comp["version"]},
            PD))
        assert edited["status"] == "REJECTED", "PUT does not change status"
        assert edited["approved_positions"] == 6
        assert edited["version"] == 4

    def test_revision_cycle_closes_to_locked_with_exact_versions(self, api: ApiClient):
        """PRD §3.2: "Submitting moves a `DRAFT` row to `SUBMITTED`, and a
        `REJECTED` row may be edited and submitted again through the same
        action; submitting from any other status fails with
        `ERR_COMPLEMENT_NOT_SUBMITTABLE` (HTTP 409)."
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource".

        Design: Difficulty/non_linear_state_machine/complement_revision_cycle_rejected_to_resubmitted
        """
        comp = self._setup_rejected(api)
        comp = validate_success(api.update_complement(
            comp["id"], {"approved_positions": 6,
                         "expected_complement_approval_version": comp["version"]},
            PD))
        comp = validate_success(api.submit_complement(comp["id"], PD))
        assert comp["status"] == "SUBMITTED"
        comp = validate_success(api.approve_complement(comp["id"], DIO))
        assert comp["status"] == "APPROVED"
        comp = validate_success(api.lock_complement(comp["id"], DIO))
        assert comp["status"] == "LOCKED"
        # create 1, submit 2, reject 3, PUT 4, submit 5, approve 6, lock 7
        assert comp["version"] == 7


class TestLockedComplementLockdown:
    def test_locked_row_rejects_submit_and_edit(self, api: ApiClient):
        """PRD §3.2: "a `LOCKED` row rejects both edits
        (`ERR_COMPLEMENT_NOT_EDITABLE`) and submission
        (`ERR_COMPLEMENT_NOT_SUBMITTABLE`)."

        Design: Corner/state_machines/locked_complement_rejects_submit_and_edit
        """
        program = make_program()
        year = make_year(program["id"])
        comp = make_complement(program["id"], year["id"])
        locked = validate_success(api.lock_complement(comp["id"], DIO))
        assert locked["status"] == "LOCKED"
        vlock = locked["version"]

        resp = api.submit_complement(comp["id"], PD)
        validate_error(resp, ApiErrorId.ERR_COMPLEMENT_NOT_SUBMITTABLE)

        # The PUT carries the CORRECT current version: the rejection is the
        # state rule, not staleness (OCC runs before business rules, §2.8).
        resp2 = api.update_complement(
            comp["id"], {"approved_positions": 9,
                         "expected_complement_approval_version": vlock}, PD)
        validate_error(resp2, ApiErrorId.ERR_COMPLEMENT_NOT_EDITABLE)

        row = _complement_row(api, comp["id"])
        assert row["status"] == "LOCKED"
        assert row["version"] == vlock


class TestComplementOCC:
    def test_stale_version_rejected_after_first_edit(self, api: ApiClient):
        """PRD §2.7: "Updating a complement row requires the request to carry
        `expected_complement_approval_version`, the value of the complement
        row's `version` the client last observed. If the row's current
        `version` has advanced since then — because another writer edited the
        row, or because a resident lifecycle event recomputed its fill fields
        — the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_complement_update_stale_version
        """
        program = make_program()
        year = make_year(program["id"])
        comp = make_complement(program["id"], year["id"], approve=False)
        assert comp["version"] == 1

        edited = validate_success(api.update_complement(
            comp["id"], {"approved_positions": 5,
                         "expected_complement_approval_version": 1}, PD))
        assert edited["approved_positions"] == 5
        assert edited["version"] == 2

        stale = api.update_complement(
            comp["id"], {"approved_positions": 7,
                         "expected_complement_approval_version": 1}, PD)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412
        assert _complement_row(api, comp["id"])["approved_positions"] == 5


class TestImmediateConsistency:
    def test_create_response_carries_computed_figures(self, api: ApiClient):
        """PRD §3.2: "Two figures are computed at creation and on every
        subsequent edit."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/immediate_consistency_computed_fields_on_create
        """
        program = make_program()
        year = make_year(program["id"])
        resp = api.create_complement(
            create_complement_payload(program["id"], year["id"],
                                      approved_positions=4,
                                      annual_funding_budget_cents=13000020,
                                      blended_stipend_cents=6500007),
            PD)
        data = validate_success(resp, expected_status=201)
        assert_complement(data)
        assert data["resident_year_stipend_cents"] == 6500013
        assert data["effective_funded_positions"] == 1
        assert data["filled_headcount"] == 0
        assert data["filled_funded_census"] == approx2(0.0)


class TestZeroFundedPositionsFloor:
    def test_zero_funded_positions_blocks_first_activation(self, api: ApiClient):
        """PRD §3.2: "`effective_funded_positions`: the smaller of
        `approved_positions` and the whole number of resident-years the budget
        affords, computed as the floor of `annual_funding_budget_cents` divided
        by `resident_year_stipend_cents`."
        PRD §3.3: "The funding gate: the funded census after admitting the
        candidate — `filled_funded_census` plus a full 1.0 position —
        multiplied by `resident_year_stipend_cents` and rounded half-up to
        whole cents must not exceed `annual_funding_budget_cents`; a breach is
        `ERR_FUNDING_CAP_EXCEEDED` (HTTP 402)."

        Design: Corner/calculations/effective_funded_positions_zero_floor
        """
        program = make_program()
        year = make_active_year(program["id"])
        comp = make_complement(program["id"], year["id"], approved_positions=1,
                               annual_funding_budget_cents=6999999,
                               blended_stipend_cents=7000000)
        row = _complement_row(api, comp["id"])
        # round_half_up(7000000/13) = 538462 per block, x13 = 7000006.
        assert row["resident_year_stipend_cents"] == 7000006
        # min(1, floor(6999999 / 7000006)) == 0
        assert row["effective_funded_positions"] == 0

        res = make_resident(program["id"], year["id"], full_name="R One")
        resp = api.activate_resident(res["id"], PC)
        validate_error(resp, ApiErrorId.ERR_FUNDING_CAP_EXCEEDED)
        assert resp.status_code == 402
        assert validate_success(api.get_resident(res["id"], PD))[
            "lifecycle_status"] == "INCOMING"


class TestComplementRoleGates:
    def test_coordinator_cannot_approve_complement(self, api: ApiClient):
        """PRD §2.1: "an attempt to perform an action outside the caller's
        designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §3.2: "Decision authority rests with the
        `DesignatedInstitutionalOfficial`".

        Design: Corner/rbac/coordinator_cannot_approve_complement
        """
        program = make_program()
        year = make_year(program["id"])
        comp = make_complement(program["id"], year["id"], approve=False)
        validate_success(api.submit_complement(comp["id"], PD))

        resp = api.approve_complement(comp["id"], PC)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403
        assert _complement_row(api, comp["id"])["status"] == "SUBMITTED"

    def test_role_check_precedes_existence_check(self, api: ApiClient):
        """PRD §2.8: "Every request is validated against an ordered pipeline,
        and the first failure wins — the server reports the earliest failing
        stage and does not evaluate later stages." (stage 3 role authorization
        precedes stage 5 existence.)

        Design: Corner/validations/resident_cannot_create_complement_even_with_bogus_refs
        """
        make_program()
        resp = api.create_complement(
            create_complement_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            {"X-User-ID": NON_EXISTENT_UUID, "X-User-Role": "Resident",
             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403
