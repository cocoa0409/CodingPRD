"""Emissions screening, permit lifecycle, and the mobilization gate (PRD §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_equipment_line,
    approve_permit,
    assert_emissions_screening,
    confirm_contract,
    create_contract,
    create_customer,
    create_equipment_unit,
    create_permit_for_contract,
    create_site,
    decide_permit,
    get_contract,
    get_permit,
    mobilize_contract,
    quote_contract,
    run_size_load,
    setup_confirmed_contract,
    setup_quoted_contract,
    submit_permit,
    validate_error,
    validate_success,
)

TEST_SALES = TEST_USERS["sales_engineer_headers"]
TEST_DEPOT = TEST_USERS["depot_manager_headers"]


def _screen(api, site_id) -> dict:
    data = validate_success(api.get_emissions_screening(site_id, TEST_SALES), 200)
    assert_emissions_screening(data)
    return data


class TestEmissionsScreeningBoundary:
    def test_aggregate_exactly_at_cap_requires_permit(self, api):
        """PRD §3.5: "The aggregate NOx figure is the capacity-weighted average
        emission factor: each qualifying unit's `nox_g_per_kwh` is multiplied by its
        `capacity_kw`, the products are summed, the sum is divided by the sum of all
        qualifying `capacity_kw`, and the quotient is rounded half-up to two decimal
        places — or reported as 0.0 when no units qualify."
        PRD §3.5: "`permit_required` is true whenever the aggregate is greater than or
        equal to the cap — an aggregate landing exactly on the cap still requires the
        permit."

        Design: Difficulty/boundary_precision_check/emissions_aggregate_equal_cap_requires_permit
        """
        customer = create_customer(name="Cali Builders", billing_email="ap@cali.example")
        site = create_site(
            customer["id"], name="LA Basin Yard", jurisdiction_code="CA-SCAQMD"
        )
        unit_a = create_equipment_unit(
            capacity_kw=100, nox_g_per_kwh=5.0, home_depot_code="LAX-01"
        )
        unit_b = create_equipment_unit(
            capacity_kw=300, nox_g_per_kwh=5.0, home_depot_code="LAX-01"
        )
        contract = create_contract(customer["id"], site["id"])
        run_size_load(contract["id"])
        add_equipment_line(contract["id"], unit_a["id"])
        add_equipment_line(contract["id"], unit_b["id"])
        quote_contract(contract["id"])
        confirm_contract(contract["id"])

        screening = _screen(api, site["id"])
        # (5.0*100 + 5.0*300) / 400 = 5.0 exactly
        assert screening["aggregate_nox_g_per_kwh"] == 5.0
        assert screening["jurisdiction_cap_g_per_kwh"] == 5.0
        assert screening["permit_required"] is True, (
            "the >= comparison makes exact equality require the permit"
        )
        assert screening["input_unit_count"] == 2

    def test_aggregate_below_cap_does_not_require_permit(self, api):
        """PRD §3.5: "`permit_required` is true whenever the aggregate is greater than
        or equal to the cap — an aggregate landing exactly on the cap still requires
        the permit."

        Design: Difficulty/boundary_precision_check/emissions_aggregate_equal_cap_requires_permit
        """
        customer = create_customer(name="Cali Builders", billing_email="ap@cali.example")
        site = create_site(
            customer["id"], name="LA Basin Yard", jurisdiction_code="CA-SCAQMD"
        )
        unit = create_equipment_unit(
            capacity_kw=100, nox_g_per_kwh=4.9, home_depot_code="LAX-01"
        )
        # Profile sizes to ceil(1.25 * 80) = 100 kW so the single 100 kW unit
        # satisfies the quote's fleet-adequacy precondition (PRD §3.4).
        contract = create_contract(
            customer["id"], site["id"],
            load_profile=[{"load_type": "CONTINUOUS", "nameplate_kw": 80}],
        )
        run_size_load(contract["id"])
        add_equipment_line(contract["id"], unit["id"])
        quote_contract(contract["id"])
        confirm_contract(contract["id"])

        screening = _screen(api, site["id"])
        assert screening["aggregate_nox_g_per_kwh"] == 4.9
        assert screening["jurisdiction_cap_g_per_kwh"] == 5.0
        assert screening["permit_required"] is False
        assert screening["input_unit_count"] == 1

    def test_unlisted_jurisdiction_uses_default_cap(self, api):
        """PRD §3.5: "The site's jurisdiction supplies the cap: 5.0 grams per kWh for
        CA-SCAQMD, 8.0 for TX-TCEQ, 12.0 for FL-DEP, and a default of 10.0 for any
        unlisted jurisdiction code."
        PRD §3.5: "The aggregate NOx figure is the capacity-weighted average emission
        factor: each qualifying unit's `nox_g_per_kwh` is multiplied by its
        `capacity_kw`, the products are summed, the sum is divided by the sum of all
        qualifying `capacity_kw`, and the quotient is rounded half-up to two decimal
        places — or reported as 0.0 when no units qualify."

        Design: Corner/endpoints/emissions_screening_default_cap_for_unlisted_locale
        """
        customer = create_customer()
        site = create_site(
            customer["id"], name="Nowhere Yard", jurisdiction_code="ZZ-OTHER",
            fuel_tank_capacity_liters=3000,
        )

        screening = _screen(api, site["id"])
        assert screening["jurisdiction_cap_g_per_kwh"] == 10.0
        assert screening["aggregate_nox_g_per_kwh"] == 0.0
        assert screening["input_unit_count"] == 0
        assert screening["permit_required"] is False


class TestMobilizePermitGate:
    def _confirmed_ca_contract_requiring_permit(self, api):
        """CONFIRMED contract at a CA-SCAQMD site whose screening requires a permit
        (aggregate 5.0 >= cap 5.0)."""
        bundle = setup_confirmed_contract(
            customer_overrides={"name": "Cali Builders",
                                "billing_email": "ap@cali.example"},
            site_overrides={"name": "LA Basin Yard",
                            "jurisdiction_code": "CA-SCAQMD"},
            unit_overrides={"capacity_kw": 100, "nox_g_per_kwh": 5.0,
                            "home_depot_code": "LAX-01"},
            contract_overrides={
                "load_profile": [{"load_type": "CONTINUOUS", "nameplate_kw": 80}]
            },
        )
        assert bundle["contract"]["sized_kw"] == 100
        screening = _screen(api, bundle["site"]["id"])
        assert screening["permit_required"] is True
        return bundle

    def test_mobilize_blocked_without_approved_permit(self, api):
        """PRD §3.5: "Moving a contract `CONFIRMED → MOBILIZING` is a `DepotManager`
        action whose single precondition is the emissions rule: either the site
        screening currently reports no permit requirement, or an `EMISSIONS` permit in
        `APPROVED` status exists for the contract. When neither holds, mobilization is
        rejected with `ERR_PERMIT_REQUIRED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/mobilize_requires_approved_permit
        """
        bundle = self._confirmed_ca_contract_requiring_permit(api)
        res = api.mobilize_contract(bundle["contract"]["id"], TEST_DEPOT)
        validate_error(res, ApiErrorId.ERR_PERMIT_REQUIRED, expected_status=422)
        assert get_contract(bundle["contract"]["id"])["status"] == "CONFIRMED"

    def test_mobilize_succeeds_after_permit_approved(self, api):
        """PRD §3.5: "either the site screening currently reports no permit
        requirement, or an `EMISSIONS` permit in `APPROVED` status exists for the
        contract."
        PRD §3.5: "a submitted permit moves `SUBMITTED → APPROVED` or `SUBMITTED →
        REJECTED` accordingly, `decided_at` is stamped, and the version increments."

        Design: Difficulty/cross_entity_state_dependency/mobilize_requires_approved_permit
        """
        bundle = self._confirmed_ca_contract_requiring_permit(api)
        cid = bundle["contract"]["id"]

        res = api.mobilize_contract(cid, TEST_DEPOT)
        validate_error(res, ApiErrorId.ERR_PERMIT_REQUIRED, expected_status=422)

        permit = approve_permit(cid, "EMISSIONS")
        assert permit["status"] == "APPROVED"
        assert permit["jurisdiction_code"] == "CA-SCAQMD"

        mobilized = mobilize_contract(cid)
        assert mobilized["status"] == "MOBILIZING"


class TestMobilizePriorityPair:
    def _setup_site_requiring_permit_with_draft_contract(self, api):
        """Site where a CONFIRMED contract drives the screening over the cap, plus a
        second contract still in DRAFT (both state and safety fail its mobilize)."""
        cali = create_customer(name="Cali Builders", billing_email="ap@cali.example")
        second = create_customer(name="Second Builder", billing_email="ap@second.example")
        site = create_site(
            cali["id"], name="LA Basin Yard", jurisdiction_code="CA-SCAQMD"
        )
        unit = create_equipment_unit(
            capacity_kw=100, nox_g_per_kwh=5.0, home_depot_code="LAX-01"
        )
        # Profile sizes to ceil(1.25 * 80) = 100 kW so the single 100 kW unit
        # satisfies the quote's fleet-adequacy precondition (PRD §3.4).
        contract_a = create_contract(
            cali["id"], site["id"],
            load_profile=[{"load_type": "CONTINUOUS", "nameplate_kw": 80}],
        )
        run_size_load(contract_a["id"])
        add_equipment_line(contract_a["id"], unit["id"])
        quote_contract(contract_a["id"])
        confirm_contract(contract_a["id"])

        contract_b = create_contract(
            second["id"], site["id"],
            load_profile=[{"load_type": "CONTINUOUS", "nameplate_kw": 50}],
            start_date="2026-09-10T00:00:00Z",
            expected_offhire_date="2026-09-17T00:00:00Z",
        )
        return site, contract_b

    def test_mobilize_draft_returns_invalid_state_not_permit_required(self, api):
        """PRD §2.8: "the tiers are evaluated in strict priority order: a request that
        fails an earlier tier never surfaces an error from a later one."
        PRD §2.8: "The fourth tier checks state: the target must stand in a valid
        from-state for the requested transition (`ERR_INVALID_STATE`)".
        PRD §2.8: "The fifth tier enforces business safety: emissions-tier compliance
        on line assembly (`ERR_EMISSIONS_TIER_NONCOMPLIANT`), the permit gate on
        mobilization (`ERR_PERMIT_REQUIRED`), and fuel-tank capacity on deliveries
        (`ERR_TANK_CAPACITY_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/mobilize_permit_gate_vs_invalid_state
        """
        _, contract_b = self._setup_site_requiring_permit_with_draft_contract(api)
        res = api.mobilize_contract(contract_b["id"], TEST_DEPOT)
        # State tier (fourth) fires before the safety tier (fifth).
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_mobilize_draft_leaves_state_and_screening_unchanged(self, api):
        """PRD §3.5: "The screening's input set is the equipment referenced by
        equipment lines in `PENDING` or `ON_RENT` status belonging to that site's
        contracts in `CONFIRMED`, `MOBILIZING`, `ON_RENT`, or `SUSPENDED` status."
        PRD §2.8: "the tiers are evaluated in strict priority order: a request that
        fails an earlier tier never surfaces an error from a later one."

        Design: Difficulty/priority_pair_validation_conflict/mobilize_permit_gate_vs_invalid_state
        """
        site, contract_b = self._setup_site_requiring_permit_with_draft_contract(api)
        res = api.mobilize_contract(contract_b["id"], TEST_DEPOT)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        assert get_contract(contract_b["id"])["status"] == "DRAFT"
        screening = _screen(api, site["id"])
        assert screening["permit_required"] is True, (
            "the safety condition stays unsatisfied for the rejected contract"
        )


class TestPermitResubmitLoop:
    def test_permit_resubmit_loop_exhaustion(self, api):
        """PRD §3.5: "A rejected application may be resubmitted — `REJECTED →
        SUBMITTED`, again incrementing `review_rounds` and stamping `submitted_at` —
        but only while fewer than three review rounds have been consumed; a
        resubmission attempt at three rounds is rejected with
        `ERR_PERMIT_REVIEW_EXHAUSTED` (HTTP 422)."

        Design: Corner/state_machines/permit_resubmit_loop_exhaustion
        """
        bundle = setup_confirmed_contract()
        permit = create_permit_for_contract(bundle["contract"]["id"], "EMISSIONS")
        assert permit["status"] == "DRAFT"
        assert permit["review_rounds"] == 0

        submitted = submit_permit(permit["id"])
        assert submitted["review_rounds"] == 1
        decide_permit(permit["id"], "REJECTED")

        resubmitted = api.resubmit_permit(permit["id"], TEST_SALES)
        assert validate_success(resubmitted, 200)["review_rounds"] == 2
        decide_permit(permit["id"], "REJECTED")

        resubmitted = api.resubmit_permit(permit["id"], TEST_SALES)
        assert validate_success(resubmitted, 200)["review_rounds"] == 3
        decide_permit(permit["id"], "REJECTED")

        exhausted = api.resubmit_permit(permit["id"], TEST_SALES)
        validate_error(
            exhausted, ApiErrorId.ERR_PERMIT_REVIEW_EXHAUSTED, expected_status=422
        )

        final = validate_success(api.get_permit(permit["id"], TEST_SALES), 200)
        assert final["status"] == "REJECTED"
        assert final["review_rounds"] == 3
