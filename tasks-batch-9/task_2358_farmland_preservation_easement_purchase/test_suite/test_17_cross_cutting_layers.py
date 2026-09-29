"""Cross-cutting layers: optimistic concurrency and the remainder policy.

The four version gates of §2.7 all guard operations that are legitimate repeats,
so only the stale version distinguishes the rejected write from the accepted one.
The final case shows the waterfall's remainder rule choosing its absorbing source
by sweep position rather than by identity.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLOCK_2026_08_10,
    CLOCK_2026_10_05,
    TEST_USERS,
    ApiErrorId,
    api_client,
    application_version,
    create_landowner,
    create_parcel,
    draft_amendment_payload,
    easement_version,
    file_counter,
    funding_plan_payload,
    impervious_request_payload,
    issue_offer_payload,
    patch_parcel_payload,
    read_application,
    read_easement,
    read_parcel,
    read_source,
    set_clock,
    setup_offered_application,
    setup_ranked_application,
    setup_recorded_easement,
    suspend_source_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]
MONITOR = TEST_USERS["stewardship_monitor_headers"]


class TestOfferIssuanceConcurrency:
    """Re-issuing an offer from `COUNTERED` is legal, so only the version gate
    can reject the stale writer."""

    def test_the_stale_offer_is_refused_and_the_refreshed_one_advances_the_count(self):
        """One offer lands, its version is replayed, then refreshed and re-used.

        PRD §2.7: "`POST /applications/{id}/offers` requires
        `expected_application_version` matching the target `Application`'s
        current `version`. A mismatch is rejected with
        `ERR_STALE_APPLICATION_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/occ_offer_issuance_rejects_a_stale_application_version_and_admits_the_refreshed_one
        """
        scenario = setup_ranked_application()
        application_id = scenario["application"]["id"]
        set_clock(CLOCK_2026_10_05)
        first_version = application_version(application_id)

        offered = validate_success(
            api_client.issue_offer(
                application_id,
                issue_offer_payload(
                    first_version, 160_000_000, "BARGAIN_SALE", donation_pct=0.10
                ),
                OFFICER,
            )
        )
        assert offered["status"] == "OFFER_ISSUED"
        assert offered["current_offer_cents"] == 160_000_000
        assert offered["negotiation_round_count"] == 1
        assert offered["version"] == first_version + 1

        stale = api_client.issue_offer(
            application_id,
            issue_offer_payload(first_version, 170_000_000, "FULL_PURCHASE"),
            OFFICER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value, 412)
        untouched = read_application(application_id)
        # Nothing is mutated when the gate rejects.
        assert untouched["current_offer_cents"] == 160_000_000
        assert untouched["negotiation_round_count"] == 1
        assert untouched["version"] == first_version + 1

        # PRD §3.5 admits a re-issued offer only from `COUNTERED`, so the
        # landowner answers first; a `COUNTER` entry leaves the offer count at 1.
        countered = file_counter(
            application_id, scenario["landowner"]["id"], 175_550_000
        )
        assert countered["status"] == "COUNTERED"
        assert countered["negotiation_round_count"] == 1

        second_version = application_version(application_id)
        reoffered = validate_success(
            api_client.issue_offer(
                application_id,
                issue_offer_payload(second_version, 170_000_000, "FULL_PURCHASE"),
                OFFICER,
            )
        )
        assert reoffered["current_offer_cents"] == 170_000_000
        assert reoffered["structure"] == "FULL_PURCHASE"
        assert reoffered["donation_pct"] == pytest.approx(0.0, abs=0.0001)
        assert reoffered["negotiation_round_count"] == 2
        # 170,000,000 cash at the 1.5 percent fee tier.
        assert reoffered["total_program_cost_cents"] == 172_550_000
        assert reoffered["version"] == second_version + 1


class TestFundingPlanSupersedeConcurrency:
    """The rejected supersede must release nothing; the accepted one releases
    exactly the standing set."""

    def test_the_stale_supersede_leaves_every_reservation_intact(self):
        """Assemble, replay the pre-assembly version, then supersede cleanly.

        PRD §2.7: "`POST /applications/{id}/funding-plan` requires
        `expected_application_version` matching the target `Application`'s
        current `version`. A mismatch is rejected with
        `ERR_STALE_APPLICATION_VERSION` (412). Re-assembling a plan is also a
        legitimate repeat operation, so only the stale view distinguishes a
        writer whose `total_program_cost_cents` basis has since been rewritten by
        an offer or a counter."

        Design: Corner/cross_cutting_complexity_layers/occ_funding_plan_supersede_rejects_a_stale_application_version_before_touching_any_commitment
        """
        scenario = setup_offered_application()
        application_id = scenario["application"]["id"]
        local_id = scenario["sources"]["local"]["id"]
        pre_plan_version = application_version(application_id)

        first_plan = validate_success(
            api_client.assemble_funding_plan(
                application_id, funding_plan_payload(pre_plan_version), ADMIN
            )
        )
        assert first_plan["commitment_count"] == 3
        assert first_plan["funded_cost_cents"] == 160_364_925
        assert first_plan["local_total_cents"] == 56_127_723
        assert first_plan["state_total_cents"] == 64_145_970
        assert first_plan["federal_total_cents"] == 40_091_232
        # Per-source flooring leaves exactly one cent for the last non-zero take.
        assert first_plan["remainder_absorbed_cents"] == 1

        stale = api_client.assemble_funding_plan(
            application_id,
            funding_plan_payload(
                pre_plan_version, target_closing_date="2027-02-15T00:00:00Z"
            ),
            ADMIN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value, 412)

        held, held_meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN, {"application_id": application_id, "status": "RESERVED"}
            )
        )
        assert held_meta["total_count"] == 3
        assert sorted(row["amount_cents"] for row in held) == [
            40_091_232,
            56_127_723,
            64_145_970,
        ]

        refreshed_version = application_version(application_id)
        superseded = validate_success(
            api_client.assemble_funding_plan(
                application_id,
                funding_plan_payload(
                    refreshed_version, target_closing_date="2027-02-15T00:00:00Z"
                ),
                ADMIN,
            )
        )
        assert superseded["commitment_count"] == 3
        assert superseded["funded_cost_cents"] == 160_364_925
        assert superseded["remainder_absorbed_cents"] == 1

        released, released_meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN, {"application_id": application_id, "status": "RELEASED"}
            )
        )
        assert released_meta["total_count"] == 3
        assert {row["lapse_reason"] for row in released} == {"PLAN_SUPERSEDED"}

        _, fresh_meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN, {"application_id": application_id, "status": "RESERVED"}
            )
        )
        assert fresh_meta["total_count"] == 3
        # The released rows are excluded from the recomputation, so nothing is
        # double-counted.
        assert read_source(local_id)["reserved_cents"] == 56_127_723


class TestAmendmentDraftConcurrency:
    """A stewardship write, not another amendment, is what invalidates the
    drafter's view."""

    def test_an_intervening_impervious_request_invalidates_the_draft(self):
        """The stale draft creates no row; the refreshed one is accepted.

        PRD §2.7: "`POST /easements/{id}/amendments` requires
        `expected_easement_version` matching the target `Easement`'s current
        `version`. A mismatch is rejected with `ERR_STALE_EASEMENT_VERSION`
        (412)."

        Design: Corner/cross_cutting_complexity_layers/occ_amendment_draft_rejects_a_stale_easement_version
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        observed_version = easement_version(easement_id)

        metered = validate_success(
            api_client.record_impervious_request(
                easement_id,
                impervious_request_payload(1_200, "new milkhouse slab"),
                MONITOR,
            )
        )
        assert metered["impervious_used_sqft"] == 1_200
        assert metered["version"] == observed_version + 1

        stale = api_client.draft_amendment(
            easement_id,
            draft_amendment_payload(
                observed_version,
                amendment_type="RESIDENTIAL_RIGHT_RELOCATION",
                net_conservation_benefit_cents=250_000,
                residential_rights_delta=-1,
            ),
            ADMIN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_EASEMENT_VERSION.value, 412)
        _, empty_meta = validate_paginated(
            api_client.list_easement_amendments(easement_id, ADMIN)
        )
        assert empty_meta["total_count"] == 0

        drafted = validate_success(
            api_client.draft_amendment(
                easement_id,
                draft_amendment_payload(
                    easement_version(easement_id),
                    amendment_type="RESIDENTIAL_RIGHT_RELOCATION",
                    net_conservation_benefit_cents=250_000,
                    residential_rights_delta=-1,
                ),
                ADMIN,
            ),
            201,
        )
        assert drafted["status"] == "DRAFT"
        assert drafted["residential_rights_delta"] == -1
        # Only an APPROVE decision applies the delta.
        assert drafted["applied_rights_delta"] == 0
        assert read_easement(easement_id)["residential_rights_retained"] == 2


class TestParcelPatchConcurrency:
    """Two identical patch bodies, separated only by the version they declare."""

    def test_the_replayed_patch_is_refused_and_the_scores_are_recomputed(self):
        """Frontage, then sewer, each recomputing the pressure score.

        PRD §2.7: "`PATCH /parcels/{id}` requires `expected_parcel_version`
        matching the target `Parcel`'s current `version`. A mismatch is rejected
        with `ERR_STALE_PARCEL_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/occ_parcel_patch_rejects_a_stale_parcel_version
        """
        landowner = create_landowner()
        set_clock(CLOCK_2026_08_10)
        parcel = create_parcel(landowner["id"])
        parcel_id = parcel["id"]
        observed_version = parcel["version"]
        # 640 feet is six whole units at 3 points, plus 25 for sewer, plus the
        # 2.0-acre zoning tier at 35.
        assert parcel["development_pressure_score"] == pytest.approx(78.00, abs=0.01)

        widened = validate_success(
            api_client.patch_parcel(
                parcel_id,
                patch_parcel_payload(observed_version, road_frontage_feet=1_200),
                ADMIN,
            )
        )
        assert widened["road_frontage_feet"] == 1_200
        # Twelve whole units would earn 36, but the frontage award caps at 30.
        assert widened["development_pressure_score"] == pytest.approx(90.00, abs=0.01)
        assert widened["version"] == observed_version + 1

        replay = api_client.patch_parcel(
            parcel_id,
            patch_parcel_payload(observed_version, road_frontage_feet=1_200),
            ADMIN,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_PARCEL_VERSION.value, 412)
        unchanged = read_parcel(parcel_id)
        assert unchanged["road_frontage_feet"] == 1_200
        assert unchanged["development_pressure_score"] == pytest.approx(90.00, abs=0.01)
        assert unchanged["version"] == observed_version + 1

        dropped = validate_success(
            api_client.patch_parcel(
                parcel_id,
                patch_parcel_payload(unchanged["version"], sewer_available=False),
                ADMIN,
            )
        )
        assert dropped["sewer_available"] is False
        # Frontage still contributes the capped 30 and zoning 35; sewer drops out.
        assert dropped["development_pressure_score"] == pytest.approx(65.00, abs=0.01)
        # No patched field feeds the soil calculation.
        assert dropped["soil_quality_score"] == pytest.approx(84.00, abs=0.01)


class TestRemainderPolicySelectsBySweepPosition:
    """`LAST_NON_ZERO_TAKE` names a position in the sweep, not a source."""

    def test_suspending_the_last_source_moves_the_absorption_upstream(self):
        """With FEDERAL skipped, STATE absorbs 40,091,232 above its own cap.

        PRD §3.6: "If a remainder survives the walk and at least one source took
        a non-zero amount, the last source with a non-zero take absorbs an extra
        amount equal to the smaller of the surviving remainder and that source's
        still-unused headroom (its `available_cents` less what it has already
        taken). The extra is added to that source's take, recorded on the
        commitment as `absorbed_remainder_cents`, and subtracted from the
        remainder. `absorbed_remainder_cents` is 0 on every other commitment.
        The absorbing source's own `max_share_pct` is deliberately not
        re-checked against the absorbed remainder; only the program-level federal
        ceiling still binds."

        Design: Corner/cross_cutting_complexity_layers/remainder_policy_last_non_zero_take_moves_when_the_last_eligible_source_is_suspended
        """
        scenario = setup_offered_application()
        application_id = scenario["application"]["id"]
        federal_id = scenario["sources"]["federal"]["id"]
        state_id = scenario["sources"]["state"]["id"]

        suspended = validate_success(
            api_client.suspend_funding_source(
                federal_id,
                suspend_source_payload(
                    "federal award notice delayed past the closing window"
                ),
                ADMIN,
            )
        )
        assert suspended["status"] == "SUSPENDED"

        plan = validate_success(
            api_client.assemble_funding_plan(
                application_id,
                funding_plan_payload(application_version(application_id)),
                ADMIN,
            )
        )
        assert plan["commitment_count"] == 2
        assert plan["federal_total_cents"] == 0
        assert plan["local_total_cents"] == 56_127_723
        # 64,145,970 capped take plus the 40,091,232 remainder.
        assert plan["state_total_cents"] == 104_237_202
        assert plan["remainder_absorbed_cents"] == 40_091_232
        assert plan["funded_cost_cents"] == 160_364_925

        rows, meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN, {"application_id": application_id}
            )
        )
        # A SUSPENDED source is skipped entirely, however large its headroom.
        assert meta["total_count"] == 2
        assert [row["sweep_order"] for row in rows] == [1, 2]
        assert federal_id not in {row["funding_source_id"] for row in rows}

        state_rows, state_meta = validate_paginated(
            api_client.list_funding_commitments(ADMIN, {"funding_source_id": state_id})
        )
        assert state_meta["total_count"] == 1
        state_commitment = state_rows[0]
        assert state_commitment["amount_cents"] == 104_237_202
        # Above the source's own floor(160,364,925 * 0.40) == 64,145,970 cap,
        # which the absorbed remainder is not re-checked against.
        assert state_commitment["absorbed_remainder_cents"] == 40_091_232
        local_commitment = next(
            row for row in rows if row["sweep_order"] == 1
        )
        assert local_commitment["absorbed_remainder_cents"] == 0
        # The LOCAL floor still holds: ceil(160,364,925 * 0.25) == 40,091,232.
        assert local_commitment["amount_cents"] >= 40_091_232
