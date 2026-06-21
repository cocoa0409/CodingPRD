"""Corner-design coverage for cross-cutting concerns (OCC, cascade
conditioning, version semantics) and consistency-model.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    set_clock,
    create_decedent,
    create_estate,
    create_asset,
    create_designation,
    create_executor,
    accept_executor,
    finalize_plan,
    bootstrap_estate_with_two_active_designations,
    bootstrap_two_scope_poas_on_decedent,
    register_death,
    make_planner_headers,
)


class TestOccStaleEstateVersionOnRevoke:
    def test_revoke_with_stale_estate_version_rejected(self, api):
        """PRD §2.6: "A request that revokes a designation must include
        expected_estate_version as a non-optional input field, carrying the
        version value the client last observed on the parent Estate. If this
        value does not match the estate's current version at the moment the
        server processes the revocation, the request is rejected with
        ERR_STALE_ESTATE_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_estate_version_on_revoke_designation
        """
        ctx = bootstrap_estate_with_two_active_designations(a_bp=6000, b_bp=4000)
        original_version = ctx["estate"]["version"]
        # First revoke A — bumps estate.version.
        resp_a = api.revoke_beneficiary_designation(
            ctx["designation_a"]["id"],
            expected_estate_version=original_version,
            headers=make_planner_headers(),
        )
        validate_success(resp_a, expected_status=200)
        # Second client retries with the now-stale original version → reject.
        resp_b = api.revoke_beneficiary_designation(
            ctx["designation_b"]["id"],
            expected_estate_version=original_version,  # stale
            headers=make_planner_headers(),
        )
        validate_error(resp_b, ApiErrorId.ERR_STALE_ESTATE_VERSION)


class TestVersionIncrementsOnEstateMutation:
    def test_finalize_plan_bumps_estate_version(self, api):
        """PRD §2.4: "The version field is a non-negative integer that starts
        at 1 on creation and increments by exactly one on every successful
        mutation of the row."
        PRD §3.1: "every asset on the estate whose status is DRAFT advances
        to INCLUDED; every designation in DRAFT advances to ACTIVE (subject
        still to the cumulative share check below); the gross-estate value
        is recomputed as the sum of appraised_value_cents across every asset
        whose status is INCLUDED, iterated by created_at ascending for
        stability; the estate's updated_at refreshes; and Estate.version
        increments by one."

        Design: Corner/cross_cutting_layers/version_increments_on_each_estate_mutation
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Sam S",
            domicile_state_code="CA", ssn_last4="0025",
        )
        estate = create_estate(dec["id"])
        v0 = estate["version"]
        assert v0 == 1, f"new estate should start at version 1, got {v0}"
        create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
        create_designation(estate["id"], "Heir S", "CHILD", 10000)
        executor = create_executor(estate["id"], "Exec S", "EXECUTOR", False)
        accept_executor(executor["id"])
        # Read pre-finalize version.
        est_pre = validate_success(
            api.get_estate(estate["id"], make_planner_headers()),
            expected_status=200,
        )
        v_pre = est_pre["version"]
        # Finalize — must bump version by exactly one.
        est_post = validate_success(
            api.finalize_plan(estate["id"], make_planner_headers()),
            expected_status=200,
        )
        assert est_post["version"] == v_pre + 1, (
            f"finalize-plan should bump estate.version by 1; "
            f"v_pre={v_pre}, v_post={est_post['version']}"
        )


class TestCascadeTerminatesDurableNotExcluded:
    def test_durable_poa_survives_death_cascade(self, api):
        """PRD §3.3: "Every PowerOfAttorney on this decedent whose scope is
        FINANCIAL or HEALTHCARE (the two non-durable variants) and whose
        current status is ACTIVE is terminated — moved to the TERMINATED
        state — because non-durable powers do not survive incapacity or
        death. The two durable variants — DURABLE_FINANCIAL and
        DURABLE_HEALTHCARE — explicitly survive and are not touched by this
        cascade."

        Design: Corner/cross_cutting_layers/cascade_terminates_durable_poa_not_excluded
        """
        ctx = bootstrap_two_scope_poas_on_decedent(
            scope_a="FINANCIAL", scope_b="DURABLE_FINANCIAL",
        )
        register_death(ctx["decedent"]["id"], "2026-02-01T00:00:00Z")
        poa_a = validate_success(
            api.get_poa(ctx["poa_a"]["id"], make_planner_headers()),
            expected_status=200,
        )
        poa_b = validate_success(
            api.get_poa(ctx["poa_b"]["id"], make_planner_headers()),
            expected_status=200,
        )
        assert poa_a["status"] == "TERMINATED", (
            f"FINANCIAL POA should TERMINATE on death, got {poa_a['status']!r}"
        )
        assert poa_b["status"] == "ACTIVE", (
            f"DURABLE_FINANCIAL POA should survive death cascade, "
            f"got {poa_b['status']!r}"
        )


class TestConsistencyModelImmediateGross:
    def test_finalize_response_returns_updated_gross_in_same_call(self, api):
        """PRD §3.1: "every asset on the estate whose status is DRAFT advances
        to INCLUDED; every designation in DRAFT advances to ACTIVE (subject
        still to the cumulative share check below); the gross-estate value
        is recomputed as the sum of appraised_value_cents across every asset
        whose status is INCLUDED, iterated by created_at ascending for
        stability"

        Design: Corner/consistency_model/gross_visible_immediately_in_response_after_finalize
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Uno U",
            domicile_state_code="TX", ssn_last4="0027",
        )
        estate = create_estate(dec["id"])
        create_asset(estate["id"], "BANK_ACCOUNT", "A", 250000)
        create_asset(estate["id"], "REAL_ESTATE", "B", 500000)
        create_designation(estate["id"], "Heir U", "CHILD", 10000)
        executor = create_executor(estate["id"], "Exec U", "EXECUTOR", False)
        accept_executor(executor["id"])
        # The finalize response itself must carry the recomputed gross.
        resp = api.finalize_plan(estate["id"], make_planner_headers())
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ALIVE"
        assert data["gross_estate_value_cents"] == 750000, (
            f"finalize response should carry updated gross 750000; got "
            f"{data['gross_estate_value_cents']}"
        )
