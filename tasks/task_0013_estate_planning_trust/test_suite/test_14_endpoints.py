"""Corner-design coverage for endpoints section: side-effect coverage and
filter behavior.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    set_clock,
    bootstrap_estate_in_alive,
    create_decedent,
    create_estate,
    create_asset,
    create_directive,
    witness_directive,
    notarize_directive,
    make_planner_headers,
    make_executor_headers,
)


class TestPatchAssetRecomputesGross:
    def test_patch_included_asset_recomputes_gross(self, api):
        """PRD §3.1 / §4 (endpoint row): "PATCH /assets/{id} ... Update an
        asset's appraised value (re-runs gross if INCLUDED)."

        Design: Corner/endpoints/patch_asset_recomputes_gross_when_included
        """
        # bootstrap_estate_in_alive creates one INCLUDED asset at 100000.
        ctx = bootstrap_estate_in_alive(
            clock="2026-01-01T00:00:00Z",
            asset_value_cents=100000,
            asset_category="BANK_ACCOUNT",
        )
        # Before PATCH: gross should equal asset value.
        assert ctx["estate"]["gross_estate_value_cents"] == 100000

        # PATCH asset to a new value.
        api.patch_asset(
            ctx["asset"]["id"],
            {"appraised_value_cents": 250000},
            make_planner_headers(),
        )
        resp = api.get_estate(ctx["estate"]["id"], make_planner_headers())
        data = validate_success(resp, expected_status=200)
        assert data["gross_estate_value_cents"] == 250000, (
            f"Gross should reflect PATCH on INCLUDED asset; expected 250000, "
            f"got {data['gross_estate_value_cents']}"
        )


class TestDirectiveFullLifecycleChain:
    def test_dnr_witness_then_notarize_then_activate(self, api):
        """PRD §3.4: "A directive begins in DRAFT and is taken through a
        formal witnessing chain. The first step is witnessing the directive,
        advancing DRAFT -> WITNESSED; this step is allowed only while the
        decedent's date_of_death is still null"
        PRD §3.4: "Three of the four directive types must additionally be
        notarized: notarization advances WITNESSED -> NOTARIZED and is
        required for DNR, LIVING_WILL, and HEALTHCARE_POA."
        PRD §3.4: "For a DNR specifically, activation additionally requires
        that physician_attester_user_id be non-null — a DNR is not enforceable
        without a physician's signature."

        Design: Corner/endpoints/directive_witness_then_notarize_then_activate_full_chain
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Liam L",
            domicile_state_code="NY", ssn_last4="0017",
        )
        directive = create_directive(
            dec["id"], "DNR", physician_attester_user_id="physician-abc",
        )
        # Step 1: witness
        d1 = validate_success(
            api.witness_directive(directive["id"], make_planner_headers()),
            expected_status=200,
        )
        assert d1["status"] == "WITNESSED"
        # Step 2: notarize
        d2 = validate_success(
            api.notarize_directive(directive["id"], make_planner_headers()),
            expected_status=200,
        )
        assert d2["status"] == "NOTARIZED"
        # Step 3: activate
        d3 = validate_success(
            api.activate_directive(directive["id"], make_planner_headers()),
            expected_status=200,
        )
        assert d3["status"] == "ACTIVE"


class TestListAssetsFilteredByEstateId:
    def test_list_assets_filter_by_estate_id(self, api):
        """PRD §4 (endpoint row): "GET /assets ... List assets; filter by
        estate or by designation."

        Design: Corner/endpoints/get_assets_filtered_by_estate_id_reverse_fk
        """
        set_clock("2026-01-01T00:00:00Z")
        d1 = create_decedent(
            full_legal_name="Mac1",
            domicile_state_code="CA", ssn_last4="0018",
        )
        e1 = create_estate(d1["id"])
        create_asset(e1["id"], "BANK_ACCOUNT", "E1A", 100000)

        d2 = create_decedent(
            full_legal_name="Mac2",
            domicile_state_code="CA", ssn_last4="0019",
        )
        e2 = create_estate(d2["id"])
        create_asset(e2["id"], "BANK_ACCOUNT", "E2A", 200000)

        resp = api.list_assets(
            make_planner_headers(), params={"estate_id": e1["id"]},
        )
        data, _meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert len(data) == 1, (
            f"Filter by estate_id should return only e1's asset; got {len(data)}"
        )
        assert data[0]["appraised_value_cents"] == 100000
        assert data[0]["estate_id"] == e1["id"]
