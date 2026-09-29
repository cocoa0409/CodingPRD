"""Vendor contracts: the consent fork's disjoint effects and the blackout-buffered window."""

from typing import Any, Dict

import pytest
from test_helpers import (
    DECLARANT_HEADERS,
    ERR_SERVICE_WINDOW_CONFLICT,
    ApiClient,
    assert_instant,
    assert_pct,
    do_consent,
    do_deliver_item,
    do_refuse_consent,
    do_request_assignment,
    make_transition_committee_headers,
    read_association,
    read_turnover_case,
    seed_association,
    seed_component,
    seed_records_item,
    seed_turnover_case,
    seed_vendor_contract,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_contract_payload,
)

# ─── Gladstone Park: consent and refusal on sibling contracts ──────────


@pytest.fixture
def gladstone_park(api: ApiClient) -> Dict[str, Any]:
    """Two affiliated contracts awaiting consent and two delivered contract items."""
    association = seed_association(
        api,
        name="Gladstone Park",
        total_planned_lots=16,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-09-01T00:00:00Z",
        statute_of_repose_years=9,
        reserve_pool_cents=300000,
        reserve_claim_pool_cents=900000,
        declarant_monthly_subsidy_cents=60000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=5)
    beds = seed_component(
        api,
        association["id"],
        name="Landscape Beds",
        category="INFRASTRUCTURE",
        replacement_cost_cents=400000,
        useful_life_years=10,
        effective_age_years=2,
        promised_completion_date="2025-01-01T00:00:00Z",
    )
    gate = seed_component(
        api,
        association["id"],
        name="Entry Gate",
        category="INFRASTRUCTURE",
        replacement_cost_cents=250000,
        useful_life_years=12,
        effective_age_years=1,
        promised_completion_date="2025-01-01T00:00:00Z",
    )
    contract_a = seed_vendor_contract(
        api,
        association["id"],
        beds["id"],
        vendor_name="GreenScape LLC",
        developer_affiliated=True,
        annual_cost_cents=240000,
        service_window_start="2026-01-01T00:00:00Z",
        service_window_end="2026-12-31T00:00:00Z",
    )
    contract_b = seed_vendor_contract(
        api,
        association["id"],
        gate["id"],
        vendor_name="GateTech Inc",
        developer_affiliated=True,
        annual_cost_cents=120000,
        service_window_start="2026-01-01T00:00:00Z",
        service_window_end="2026-12-31T00:00:00Z",
    )
    do_request_assignment(api, contract_a["id"])
    do_request_assignment(api, contract_b["id"])
    items = []
    for _ in range(2):
        item = seed_records_item(api, case["id"], "VENDOR_CONTRACTS", required=True)
        items.append(do_deliver_item(api, item["id"]))
    return {
        "association": association,
        "case": case,
        "contract_a": contract_a,
        "contract_b": contract_b,
        "items": items,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestConsentForkIsDisjoint:
    """Refusal touches no records item, and consent touches no forecast."""

    def test_refusal_terminates_the_contract_and_stales_the_forecast_only(
        self, api: ApiClient, gladstone_park: Dict[str, Any]
    ) -> None:
        """The delivered contract items stay delivered, so completeness reads 0.00.

        "`REFUSE_CONSENT` moves `assignment_status` `ASSIGNMENT_REQUESTED →
        CONSENT_REFUSED` and simultaneously terminates the contract, moving
        `status` to `TERMINATED_FOR_REFUSAL`; because the refused service has to
        be re-procured, the association's `budget_forecast_status` is set to
        `STALE` and its `version` advances."

        Design: Difficulty/non_linear_state_machine/vendor_contract_consent_and_refusal_branches_have_disjoint_effects
        """
        association_id = gladstone_park["association"]["id"]
        committee = gladstone_park["committee_headers"]

        refused = do_refuse_consent(api, gladstone_park["contract_b"]["id"], association_id)
        assert refused["assignment_status"] == "CONSENT_REFUSED"
        assert refused["status"] == "TERMINATED_FOR_REFUSAL"

        association = read_association(api, association_id)
        assert association["budget_forecast_status"] == "STALE"

        rows, _meta = validate_paginated(
            api.list_records_items(gladstone_park["case"]["id"], committee)
        )
        assert [row["status"] for row in rows] == ["DELIVERED", "DELIVERED"], (
            "Refusal touches no records item"
        )
        case = read_turnover_case(api, gladstone_park["case"]["id"])
        assert_pct(
            case["records_transfer_completeness_pct"],
            0.00,
            "records_transfer_completeness_pct",
        )

    def test_consent_accepts_the_delivered_items_and_leaves_the_status_alone(
        self, api: ApiClient, gladstone_park: Dict[str, Any]
    ) -> None:
        """Consent keeps the contract ACTIVE and drives completeness to 100.00.

        "`CONSENT` moves `assignment_status` `ASSIGNMENT_REQUESTED → CONSENTED`
        and leaves `status` untouched; because consent is what completes the
        contract handover, it cascades — every records item of the association's
        case whose `category` is `VENDOR_CONTRACTS` and whose `status` is
        `DELIVERED` moves `DELIVERED → ACCEPTED`, oldest first, and the case's
        `records_transfer_completeness_pct` is then recomputed over those
        acceptances."

        Design: Difficulty/non_linear_state_machine/vendor_contract_consent_and_refusal_branches_have_disjoint_effects
        """
        association_id = gladstone_park["association"]["id"]
        committee = gladstone_park["committee_headers"]

        do_refuse_consent(api, gladstone_park["contract_b"]["id"], association_id)
        consented = do_consent(api, gladstone_park["contract_a"]["id"], association_id)

        assert consented["assignment_status"] == "CONSENTED"
        assert consented["status"] == "ACTIVE", "Consent leaves status untouched"

        rows, _meta = validate_paginated(
            api.list_records_items(gladstone_park["case"]["id"], committee)
        )
        assert [row["status"] for row in rows] == ["ACCEPTED", "ACCEPTED"]
        case = read_turnover_case(api, gladstone_park["case"]["id"])
        assert_pct(
            case["records_transfer_completeness_pct"],
            100.00,
            "records_transfer_completeness_pct",
        )


# ─── Umber Fields: the thirty-day blackout buffer ──────────────────────


@pytest.fixture
def umber_fields(api: ApiClient) -> Dict[str, Any]:
    """One incumbent pool contract whose window ends on 2026-04-01."""
    association = seed_association(
        api,
        name="Umber Fields",
        total_planned_lots=20,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-06-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=150000,
        reserve_claim_pool_cents=300000,
        declarant_monthly_subsidy_cents=28000,
    )
    pool_deck = seed_component(
        api,
        association["id"],
        name="Pool Deck",
        category="AMENITY",
        replacement_cost_cents=1500000,
        useful_life_years=20,
        effective_age_years=2,
        promised_completion_date="2027-01-01T00:00:00Z",
    )
    entry_gate = seed_component(
        api,
        association["id"],
        name="Entry Gate",
        category="INFRASTRUCTURE",
        replacement_cost_cents=400000,
        useful_life_years=15,
        effective_age_years=1,
        promised_completion_date="2027-01-01T00:00:00Z",
    )
    incumbent = seed_vendor_contract(
        api,
        association["id"],
        pool_deck["id"],
        vendor_name="BlueWave Pools",
        developer_affiliated=False,
        annual_cost_cents=240000,
        service_window_start="2026-01-01T00:00:00Z",
        service_window_end="2026-04-01T00:00:00Z",
    )
    return {
        "association": association,
        "pool_deck": pool_deck,
        "entry_gate": entry_gate,
        "incumbent": incumbent,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestServiceWindowBlackout:
    """The buffer is applied per component, and only to the comparison."""

    def test_a_window_starting_on_the_raw_end_collides_through_the_buffer(
        self, api: ApiClient, umber_fields: Dict[str, Any]
    ) -> None:
        """The incumbent's effective end is 2026-05-01, so an April start collides.

        "A component's service windows may not collide: a new window is refused
        with `ERR_SERVICE_WINDOW_CONFLICT` if it overlaps the window of any
        existing contract on that same component whose `status` is `ACTIVE` or
        `CANCELLABLE`, where the existing window is first extended by a
        thirty-day transition blackout buffer added to its end and the comparison
        treats each window as including its start instant and excluding its end
        instant."

        Design: Difficulty/resource_temporal_overlap/vendor_service_window_conflict_uses_blackout_inflated_end_per_component
        """
        association_id = umber_fields["association"]["id"]

        validate_error(
            api.create_vendor_contract(
                vendor_contract_payload(
                    association_id,
                    umber_fields["pool_deck"]["id"],
                    vendor_name="AquaCrest Services",
                    developer_affiliated=False,
                    annual_cost_cents=200000,
                    service_window_start="2026-04-01T00:00:00Z",
                    service_window_end="2026-08-01T00:00:00Z",
                ),
                DECLARANT_HEADERS,
            ),
            ERR_SERVICE_WINDOW_CONFLICT,
        )

        incumbent = validate_success(
            api.get_vendor_contract(
                umber_fields["incumbent"]["id"], umber_fields["committee_headers"]
            )
        )
        assert_instant(
            incumbent["service_window_end"],
            "2026-04-01T00:00:00Z",
            "service_window_end",
        )

    def test_the_buffer_is_scoped_to_the_component_and_clears_after_thirty_days(
        self, api: ApiClient, umber_fields: Dict[str, Any]
    ) -> None:
        """The identical window is fine on another component, and May is fine on this one.

        "New contracts begin with `status` `ACTIVE`, `assignment_status`
        `NOT_REQUESTED` and `cancellation_window_end` null."

        Design: Difficulty/resource_temporal_overlap/vendor_service_window_conflict_uses_blackout_inflated_end_per_component
        """
        association_id = umber_fields["association"]["id"]
        committee = umber_fields["committee_headers"]

        validate_error(
            api.create_vendor_contract(
                vendor_contract_payload(
                    association_id,
                    umber_fields["pool_deck"]["id"],
                    vendor_name="AquaCrest Services",
                    developer_affiliated=False,
                    annual_cost_cents=200000,
                    service_window_start="2026-04-01T00:00:00Z",
                    service_window_end="2026-08-01T00:00:00Z",
                ),
                DECLARANT_HEADERS,
            ),
            ERR_SERVICE_WINDOW_CONFLICT,
        )

        other_component = validate_success(
            api.create_vendor_contract(
                vendor_contract_payload(
                    association_id,
                    umber_fields["entry_gate"]["id"],
                    vendor_name="AquaCrest Services",
                    developer_affiliated=False,
                    annual_cost_cents=200000,
                    service_window_start="2026-04-01T00:00:00Z",
                    service_window_end="2026-08-01T00:00:00Z",
                ),
                DECLARANT_HEADERS,
            ),
            expected_status=201,
        )
        assert other_component["status"] == "ACTIVE"

        later = validate_success(
            api.create_vendor_contract(
                vendor_contract_payload(
                    association_id,
                    umber_fields["pool_deck"]["id"],
                    vendor_name="AquaCrest Services",
                    developer_affiliated=False,
                    annual_cost_cents=200000,
                    service_window_start="2026-05-01T00:00:00Z",
                    service_window_end="2026-09-01T00:00:00Z",
                ),
                DECLARANT_HEADERS,
            ),
            expected_status=201,
        )
        assert later["status"] == "ACTIVE"
        assert later["assignment_status"] == "NOT_REQUESTED"
        assert later["cancellation_window_end"] is None

        _rows, meta = validate_paginated(
            api.list_vendor_contracts(committee, {"association_id": association_id})
        )
        assert meta["total_count"] == 3, "The refused registration created nothing"
