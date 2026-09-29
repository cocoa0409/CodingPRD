"""Reversals that must restore an invariant exactly, not approximately.

Closing cancellation has to give back the absorbed remainder cent; amendment
rescission has to re-derive the impervious allowance from first principles rather
than decrement it. Both are places where an "undo by subtraction" drifts.
"""

import pytest

from test_helpers import (
    CLOCK_2026_10_12,
    accept_as_landowner,
    assert_rights_conserved,
    assert_source_ledger_conserved,
    cancel_closing,
    commitment_on,
    commitments_of,
    decide_amendment,
    draft_amendment,
    list_requirements,
    read_amendment,
    read_application,
    read_easement,
    read_parcel,
    read_source,
    rescind_amendment,
    set_clock,
    setup_accepted_application,
    setup_easement_with_approved_impervious_amendment,
    setup_easement_with_approved_rights_amendment,
    setup_two_applications_competing_for_headroom,
    submit_amendment,
)


class TestClosingCancellationRestoresTheLedgers:
    """Every cent obligated by the waterfall must come back, including the one
    the last non-zero take absorbed."""

    def test_cancellation_releases_every_commitment_on_the_plan(self):
        """All three commitments move to RELEASED under one lapse reason.

        PRD §3.7: "Every commitment in `RESERVED` or `OBLIGATED` flips to
        `RELEASED` with `lapse_reason` `CLOSING_CANCELLED` and
        `funding_plan_status` becomes `RELEASED`; each touched source has its
        ledger recomputed so that `authorized_cents` still equals
        `available_cents` plus `committed_cents` exactly, with its `version`
        incremented, and any source whose `committed_cents` has fallen back below
        the obligation floor returns `FULLY_OBLIGATED → ACTIVE`."

        Design: Difficulty/compensating_invariant/closing_cancellation_restores_every_source_ledger_including_the_absorbed_remainder
        """
        scenario = setup_accepted_application()
        application_id = scenario["application"]["id"]
        before = commitments_of(application_id)
        assert {row["status"] for row in before} == {"OBLIGATED"}
        assert sum(row["absorbed_remainder_cents"] for row in before) == 1

        cancelled = cancel_closing(application_id)
        assert cancelled["closing_status"] == "CANCELLED"
        assert cancelled["funding_plan_status"] == "RELEASED"

        for row in commitments_of(application_id):
            assert row["status"] == "RELEASED"
            assert row["lapse_reason"] == "CLOSING_CANCELLED"

    def test_every_source_ledger_returns_to_its_full_authority(self):
        """The absorbed cent is returned too, so federal lands on 200,000,000.

        PRD §3.7: "each touched source has its ledger recomputed so that
        `authorized_cents` still equals `available_cents` plus `committed_cents`
        exactly, with its `version` incremented, and any source whose
        `committed_cents` has fallen back below the obligation floor returns
        `FULLY_OBLIGATED → ACTIVE`."

        Design: Difficulty/compensating_invariant/closing_cancellation_restores_every_source_ledger_including_the_absorbed_remainder
        """
        scenario = setup_accepted_application()
        sources = scenario["sources"]
        federal_before = read_source(sources["federal"]["id"])
        # 40,091,231 from its own share cap plus the one absorbed cent.
        assert federal_before["committed_cents"] == 40_091_232

        cancel_closing(scenario["application"]["id"])

        expected = {"local": 60_000_000, "state": 120_000_000, "federal": 200_000_000}
        for key, authorized in expected.items():
            source = read_source(sources[key]["id"])
            assert source["authorized_cents"] == authorized
            assert source["committed_cents"] == 0
            assert source["reserved_cents"] == 0
            assert source["disbursed_cents"] == 0
            # An undo-by-subtraction that forgets the absorbed cent would leave
            # the federal source one cent short at 199,999,999.
            assert source["available_cents"] == authorized
            assert source["version"] > sources[key]["version"]
            assert_source_ledger_conserved(source)

    def test_cancellation_also_waives_the_file_and_frees_the_land(self):
        """The rest of the reversal: requirements, application and parcel.

        PRD §3.7: "Every requirement still in `OUTSTANDING`, `SUBMITTED` or
        `DEFICIENT` becomes `WAIVED` with `waiver_reason` `CLOSING_CANCELLED`. The
        application itself moves `ACCEPTED → WITHDRAWN` with `withdrawal_reason`
        `CLOSING_CANCELLED`, the parcel returns `UNDER_APPLICATION → ELIGIBLE`
        with its `version` incremented, and the application's `version`
        increments."

        Design: Difficulty/compensating_invariant/closing_cancellation_restores_every_source_ledger_including_the_absorbed_remainder
        """
        scenario = setup_accepted_application()
        application_id = scenario["application"]["id"]

        cancel_closing(application_id)

        for requirement in list_requirements(application_id, {"limit": 100}):
            assert requirement["status"] == "WAIVED"
            assert requirement["waiver_reason"] == "CLOSING_CANCELLED"

        after = read_application(application_id)
        assert after["status"] == "WITHDRAWN"
        assert after["withdrawal_reason"] == "CLOSING_CANCELLED"
        assert after["version"] > scenario["application"]["version"]

        parcel = read_parcel(scenario["parcel"]["id"])
        assert parcel["status"] == "ELIGIBLE"
        assert parcel["version"] > scenario["parcel"]["version"]

    def test_a_fully_obligated_source_returns_to_active_without_reviving_lapses(self):
        """The status flip reverses; the lapse it caused does not.

        PRD §3.1: "When a commitment is released and `committed_cents` falls back
        strictly below that same floor, the source flips
        `FULLY_OBLIGATED → ACTIVE` and its `version` increments — but commitments
        already lapsed are never revived, because lapse is deliberately
        irreversible."

        Design: Difficulty/compensating_invariant/closing_cancellation_restores_every_source_ledger_including_the_absorbed_remainder
        """
        scenario = setup_two_applications_competing_for_headroom(
            local_threshold_pct=0.50
        )
        local_id = scenario["sources"]["local"]["id"]
        set_clock(CLOCK_2026_10_12)
        accepted = accept_as_landowner(
            scenario["application_a"]["id"], scenario["landowner_a"]["id"]
        )
        assert read_source(local_id)["status"] == "FULLY_OBLIGATED"
        sibling_lapsed = commitment_on(scenario["application_b"]["id"], local_id)
        assert sibling_lapsed["status"] == "LAPSED"

        cancel_closing(accepted["id"])

        restored = read_source(local_id)
        assert restored["status"] == "ACTIVE"
        assert restored["committed_cents"] == 0
        assert restored["available_cents"] == 60_000_000
        assert_source_ledger_conserved(restored)

        # The competitor's lapse stands and its plan stays underfunded.
        assert commitment_on(scenario["application_b"]["id"], local_id)["status"] == (
            "LAPSED"
        )
        assert (
            read_application(scenario["application_b"]["id"])["funding_plan_status"]
            == "UNDERFUNDED"
        )


class TestAmendmentRescissionRestoresTheEasement:
    """Rescission is the exact inverse of approval on both rewritable fields."""

    def test_approval_moves_the_rights_pair_while_conserving_the_baseline(self):
        """The delta is added to one field and subtracted from the other.

        PRD §3.9: "the signed `residential_rights_delta` is added to
        `residential_rights_retained` and subtracted from
        `residential_rights_extinguished`; since the delta is negative, retained
        rights fall and extinguished rights rise by the same magnitude, so their
        sum still equals the parcel's `baseline_dwelling_rights`, and
        `applied_rights_delta` records the delta that was applied."

        Design: Difficulty/compensating_invariant/amendment_rescission_restores_the_residential_rights_conservation_pair
        """
        scenario = setup_easement_with_approved_rights_amendment()
        easement = scenario["easement"]
        assert scenario["parcel"]["baseline_dwelling_rights"] == 4
        # Closing retained 2 of 4; the amendment relocates 2 more.
        assert easement["residential_rights_retained"] == 0
        assert easement["residential_rights_extinguished"] == 4
        assert_rights_conserved(easement, 4)

        amendment = scenario["amendment"]
        assert amendment["status"] == "APPROVED"
        assert amendment["applied_rights_delta"] == -2
        assert amendment["applied_impervious_sqft"] is None
        assert easement["status"] == "AMENDED"
        assert easement["amendment_count"] == 1

    def test_rescission_restores_the_exact_pair_and_the_deed_dimension(self):
        """The stored delta is subtracted back and then cleared.

        PRD §3.9: "Where `applied_rights_delta` is non-zero,
        `applied_rights_delta` is subtracted from `residential_rights_retained`
        and added to `residential_rights_extinguished`, restoring the exact
        pre-approval pair and again conserving the baseline total."

        Design: Difficulty/compensating_invariant/amendment_rescission_restores_the_residential_rights_conservation_pair
        """
        scenario = setup_easement_with_approved_rights_amendment()
        rescinded = rescind_amendment(scenario["amendment"]["id"])
        assert rescinded["status"] == "RESCINDED"
        assert rescinded["rescission_reason"] == "landowner reversed the request"
        assert rescinded["applied_rights_delta"] == 0
        assert rescinded["applied_impervious_sqft"] is None

        easement = read_easement(scenario["easement"]["id"])
        assert easement["residential_rights_retained"] == 2
        assert easement["residential_rights_extinguished"] == 2
        assert_rights_conserved(easement, 4)
        assert easement["amendment_count"] == 0
        # With no approved amendment left the deed dimension returns.
        assert easement["status"] == "RECORDED"
        assert easement["version"] > scenario["easement"]["version"]

    def test_rescission_re_derives_the_impervious_allowance_from_first_principles(self):
        """The allowance is recomputed, not decremented by the applied figure.

        PRD §3.9: "Where `applied_impervious_sqft` is non-null, the easement's
        `impervious_allowance_sqft` is not merely decremented but re-derived from
        first principles: `protected_acres` multiplied by 43,560 square feet per
        acre and then by the program's `impervious_allowance_pct`, floored to
        whole square feet."

        Design: Difficulty/compensating_invariant/amendment_rescission_restores_the_residential_rights_conservation_pair
        """
        scenario = setup_easement_with_approved_impervious_amendment(
            requested_impervious_sqft=160_000
        )
        assert scenario["easement"]["impervious_allowance_sqft"] == 160_000
        assert scenario["amendment"]["applied_impervious_sqft"] == 160_000

        rescinded = rescind_amendment(scenario["amendment"]["id"])
        assert rescinded["applied_impervious_sqft"] is None

        easement = read_easement(scenario["easement"]["id"])
        # floor(160.00 x 43,560 x 0.02)
        assert easement["impervious_allowance_sqft"] == 139_392
        assert easement["protected_acres"] == pytest.approx(160.00, abs=0.01)
        assert easement["status"] == "RECORDED"
        # The rights pair was never touched by an impervious amendment.
        assert_rights_conserved(easement, 4)
        assert easement["residential_rights_retained"] == 2

    def test_the_deed_dimension_holds_while_another_approved_amendment_remains(self):
        """`amendment_count` must reach 0 before the deed dimension returns.

        PRD §3.9: "`amendment_count` is recomputed, and when it reaches 0 the
        easement's deed dimension returns `AMENDED → RECORDED`."

        Design: Difficulty/compensating_invariant/amendment_rescission_restores_the_residential_rights_conservation_pair
        """
        scenario = setup_easement_with_approved_rights_amendment()
        easement_id = scenario["easement"]["id"]

        second = draft_amendment(easement_id, amendment_type="BOUNDARY_ADJUSTMENT")
        submit_amendment(second["id"])
        decide_amendment(second["id"], "APPROVE")
        assert read_easement(easement_id)["amendment_count"] == 2

        rescind_amendment(second["id"])
        midway = read_easement(easement_id)
        assert midway["amendment_count"] == 1
        assert midway["status"] == "AMENDED"
        # A BOUNDARY_ADJUSTMENT rewrites neither field, so the pair is unmoved.
        assert midway["residential_rights_retained"] == 0
        assert midway["impervious_allowance_sqft"] == 139_392

        rescind_amendment(scenario["amendment"]["id"])
        final = read_easement(easement_id)
        assert final["amendment_count"] == 0
        assert final["status"] == "RECORDED"
        assert final["residential_rights_retained"] == 2
        assert_rights_conserved(final, 4)
        assert read_amendment(second["id"])["status"] == "RESCINDED"
