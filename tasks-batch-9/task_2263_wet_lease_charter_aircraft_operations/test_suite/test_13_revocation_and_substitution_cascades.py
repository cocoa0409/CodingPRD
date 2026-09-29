"""Four-level cascades: insurance revocation and substitution effectuation.

Both cascades start from a single write and are required to be walked to the bottom
within the same request — through lease status, leg status, crew exposure and the open
month's charge.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    add_substitute_candidate,
    create_first_officer,
    effectuate_substitution,
    first_open_period,
    qualify_crew_member,
    request_substitution,
    revoke_insurance_certificate,
    schedule_leg,
    set_clock,
    setup_active_lease,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# --------------------------------------------------------------------------- #
# The insurance-lapse cascade                                                  #
# --------------------------------------------------------------------------- #


def _setup_two_scheduled_legs_inside_the_duty_window(api) -> dict:
    """ACTIVE lease with a 330-minute and a 180-minute SCHEDULED revenue leg.

    The clock is then moved to 2026-09-06T00:00:00Z so both legs sit inside the
    half-open seven-day duty window and the rolling exposures are non-zero.
    """
    scenario = setup_active_lease(api)
    scenario["leg_one"] = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-03T06:00:00Z",
        scheduled_in="2026-09-03T11:30:00Z",
    )
    scenario["leg_two"] = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-05T06:00:00Z",
        scheduled_in="2026-09-05T09:00:00Z",
        dest_icao="LFPG",
    )
    set_clock(api, "2026-09-06T00:00:00Z")
    scenario["period"] = first_open_period(api, scenario["lease"]["id"])
    return scenario


class TestInsuranceRevocationCascade:
    def test_revocation_suspends_the_lease_and_cancels_every_open_leg(self, api):
        """PRD §2.7: The **insurance-lapse cascade** begins when the underwriter revokes cover or the logical clock advances past a certificate's `expires_at`. Level one is the certificate leaving `ACTIVE`. Level two: if no `ACTIVE` certificate remains on the lease, the lease moves from `ACTIVE` to `SUSPENDED` with `suspension_reason` set to `INSURANCE_LAPSED`. Level three: every leg on that lease still in `SCHEDULED` or `DISPATCHED` is cancelled into `CANCELLED_LESSOR`.

        PRD §3.3: If no `ACTIVE` certificate remains on the lease afterwards, the four-level lapse cascade of §2.7 runs in full: the lease drops from `ACTIVE` to `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSED`, every leg still `SCHEDULED` or `DISPATCHED` on that lease is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `INSURANCE_LAPSE`, and each cancellation recomputes that leg's crew exposure and the open month's charge.

        PRD §3.6: Either way `cancelling_party` and `cancel_reason` are recorded, `billing_state` is set to `CREDITED`, the rolling exposures of both `captain_id` and `first_officer_id` are recomputed — releasing the cancelled leg's duty and block contribution — and the lease's `OPEN` period is recomputed under the `PROVISIONAL` variant.

        Design: Difficulty/transitive_cascade/insurance_revocation_cascades_through_lease_legs_crew_and_period
        """
        scenario = _setup_two_scheduled_legs_inside_the_duty_window(api)

        certificate = revoke_insurance_certificate(
            api, scenario["certificate"]["id"], "PREMIUM_NON_PAYMENT"
        )

        assert certificate["status"] == "REVOKED", (
            "level one of the cascade takes the certificate out of ACTIVE, got "
            f"{certificate['status']}"
        )

        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["status"] == "SUSPENDED", (
            "level two moves the lease from ACTIVE to SUSPENDED because no ACTIVE "
            f"certificate remains, got {lease['status']}"
        )
        assert lease["suspension_reason"] == "INSURANCE_LAPSED", (
            "level two stamps suspension_reason INSURANCE_LAPSED, got "
            f"{lease['suspension_reason']!r}"
        )

        for label, leg in (
            ("leg_one", scenario["leg_one"]),
            ("leg_two", scenario["leg_two"]),
        ):
            cancelled = validate_success(api.get_flight_leg(leg["id"], OPS))
            assert cancelled["status"] == "CANCELLED_LESSOR", (
                f"level three cancels {label} into CANCELLED_LESSOR, got "
                f"{cancelled['status']}"
            )
            assert cancelled["cancel_reason"] == "INSURANCE_LAPSE", (
                f"{label} must carry cancel_reason INSURANCE_LAPSE, got "
                f"{cancelled['cancel_reason']!r}"
            )
            assert cancelled["billing_state"] == "CREDITED", (
                f"a cancellation sets {label}'s billing_state to CREDITED, got "
                f"{cancelled['billing_state']}"
            )

    def test_cascade_releases_the_rolling_exposure_of_both_pilots(self, api):
        """PRD §3.4: `rolling_duty_minutes_7d` is the sum, over the crew member's legs whose `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED` and whose `scheduled_out` falls within the last seven days — that is, at or after the instant 168 hours before the clock and strictly before the clock — of each leg's scheduled block minutes plus a fixed pre- and post-flight duty allowance of 105 minutes.

        PRD §2.7: Level four: each of those cancellations recomputes the rolling duty and block exposure of that leg's captain and first officer, and recomputes the `OPEN` utilization period covering the leg's scheduled off-blocks month.

        PRD §2.9: `CrewMember.rolling_duty_minutes_7d` and `CrewMember.rolling_block_minutes_28d` are aggregates over the crew member's own legs, recomputed rather than adjusted. Because cancelled and diverted legs are excluded from the aggregate, cancelling a leg is an exact compensation for having scheduled it.

        Design: Difficulty/transitive_cascade/insurance_revocation_cascades_through_lease_legs_crew_and_period
        """
        scenario = _setup_two_scheduled_legs_inside_the_duty_window(api)

        captain_before = validate_success(
            api.get_crew_member(scenario["captain"]["id"], OPS)
        )
        assert captain_before["rolling_duty_minutes_7d"] == 720, (
            "both scheduled legs sit inside the seven-day window, so the captain's "
            "duty exposure must be (330 + 105) + (180 + 105) = 720 minutes, got "
            f"{captain_before['rolling_duty_minutes_7d']}"
        )
        assert captain_before["rolling_block_minutes_28d"] == 510, (
            "the twenty-eight-day exposure sums the scheduled block minutes alone, "
            f"330 + 180 = 510, got {captain_before['rolling_block_minutes_28d']}"
        )

        revoke_insurance_certificate(
            api, scenario["certificate"]["id"], "PREMIUM_NON_PAYMENT"
        )

        captain_after = validate_success(
            api.get_crew_member(scenario["captain"]["id"], OPS)
        )
        assert captain_after["rolling_duty_minutes_7d"] == 0, (
            "cancelled legs are excluded from the aggregate, so the captain's duty "
            f"exposure must fall back to 0, got {captain_after['rolling_duty_minutes_7d']}"
        )
        assert captain_after["rolling_block_minutes_28d"] == 0, (
            "cancelled legs are excluded from the aggregate, so the captain's block "
            f"exposure must fall back to 0, got {captain_after['rolling_block_minutes_28d']}"
        )

        first_officer_after = validate_success(
            api.get_crew_member(scenario["first_officer"]["id"], OPS)
        )
        assert first_officer_after["rolling_duty_minutes_7d"] == 0, (
            "level four recomputes the first officer's exposure too, expected 0, got "
            f"{first_officer_after['rolling_duty_minutes_7d']}"
        )
        assert first_officer_after["rolling_block_minutes_28d"] == 0, (
            "level four recomputes the first officer's block exposure too, expected 0, "
            f"got {first_officer_after['rolling_block_minutes_28d']}"
        )

    def test_cascade_recomputes_the_open_month_into_a_lessor_attributable_credit(
        self, api
    ):
        """PRD §2.7: Level four: each of those cancellations recomputes the rolling duty and block exposure of that leg's captain and first officer, and recomputes the `OPEN` utilization period covering the leg's scheduled off-blocks month.

        PRD §3.8: Under the `PROVISIONAL` variant the include-set is every leg of the lease whose `scheduled_out` falls inside `period_month` and whose `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED`.

        PRD §3.8: Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure.

        PRD §3.8: `base_charge_cents` is `mgh_effective_hours` multiplied by the lease's `block_hour_rate_usd_cents`, rounded half up to whole cents. `shortfall_credit_cents` is `lessor_attributable_shortfall_hours` multiplied by that same rate and by the lease's `shortfall_credit_pct`, rounded half up to whole cents.

        PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.

        Design: Difficulty/transitive_cascade/insurance_revocation_cascades_through_lease_legs_crew_and_period
        """
        scenario = _setup_two_scheduled_legs_inside_the_duty_window(api)

        revoke_insurance_certificate(
            api, scenario["certificate"]["id"], "PREMIUM_NON_PAYMENT"
        )

        period = validate_success(
            api.get_utilization_period(scenario["period"]["id"], BILLING)
        )

        assert period["credited_block_minutes"] == 0, (
            "both legs are cancelled, so nothing is credited to the month, got "
            f"{period['credited_block_minutes']}"
        )
        assert period["credited_hours"] == pytest.approx(0.0000, abs=0.0001), (
            f"credited_hours must fall to 0.0000, got {period['credited_hours']}"
        )
        assert period["shortfall_hours"] == pytest.approx(5.0000, abs=0.0001), (
            "the whole prorated guarantee becomes shortfall, expected 5.0000 hours, "
            f"got {period['shortfall_hours']}"
        )
        assert period["lessor_attributable_shortfall_hours"] == pytest.approx(
            5.0000, abs=0.0001
        ), (
            "the lessor cancelled 8.5000 hours of scheduled block time, so the lesser "
            "of shortfall and lessor-cancelled hours is 5.0000, got "
            f"{period['lessor_attributable_shortfall_hours']}"
        )
        assert period["base_charge_cents"] == 2400000, (
            "the base guarantee charge is 5.0000 hours at 480000 cents, expected "
            f"2400000, got {period['base_charge_cents']}"
        )
        assert period["shortfall_credit_cents"] == 1440000, (
            "the credit is 5.0000 hours at 480000 cents times 0.60, expected 1440000, "
            f"got {period['shortfall_credit_cents']}"
        )
        assert period["gross_charge_cents"] == 960000, (
            "gross is base less credit plus overrun, expected 960000, got "
            f"{period['gross_charge_cents']}"
        )
        assert period["provisional_charge_cents"] == 960000, (
            "the provisional variant writes the net charge to provisional_charge_cents, "
            f"expected 960000, got {period['provisional_charge_cents']}"
        )
        assert period["status"] == "OPEN", (
            "the cascade recomputes the OPEN month without closing it, got "
            f"{period['status']}"
        )


# --------------------------------------------------------------------------- #
# The substitution cascade                                                     #
# --------------------------------------------------------------------------- #


def _setup_approved_cross_variant_substitution(api) -> dict:
    """ACTIVE lease on a B738 with an APPROVED swap onto a same-family B38M.

    The captain is rated on B738 only, so the substitute's exact variant strands him;
    the first officer holds both ratings. Two SCHEDULED legs straddle the substitution's
    ``effective_from`` instant of 2026-09-21T00:00:00Z.
    """
    scenario = setup_active_lease(api, with_first_officer=False)
    lease_id = scenario["lease"]["id"]
    scenario["first_officer"] = create_first_officer(
        api, type_ratings=["B738", "B38M"]
    )
    scenario["first_officer_qualification"] = qualify_crew_member(
        api, scenario["first_officer"]["id"], lease_id
    )
    scenario["substitute"] = add_substitute_candidate(
        api,
        tail_number="G-SUBS",
        type_designator="B38M",
        type_family="B737",
        seat_count=186,
        mtow_kg=82000,
        airframe_hours_total=9000.00,
        hours_since_last_check=80.00,
        cycles_since_last_check=20,
    )
    scenario["leg_before"] = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-20T06:00:00Z",
        scheduled_in="2026-09-20T11:30:00Z",
    )
    scenario["leg_after"] = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-22T06:00:00Z",
        scheduled_in="2026-09-22T09:00:00Z",
        dest_icao="LFPG",
    )
    scenario["lease"] = validate_success(api.get_lease(lease_id, OPS))
    scenario["substitution"] = request_substitution(
        api,
        scenario,
        substitute_aircraft_id=scenario["substitute"]["id"],
        reason="AOG",
        effective_from="2026-09-21T00:00:00Z",
    )
    scenario["period"] = first_open_period(api, lease_id)
    return scenario


class TestSubstitutionEffectuationCascade:
    def test_effectuation_repoints_the_airframes_and_only_the_legs_from_effective_from(
        self, api
    ):
        """PRD §3.7: Effectuation moves the request to the terminal `EFFECTIVE` and runs the four-level cascade.

        PRD §3.7: Level one: the substitute's `status` becomes `ASSIGNED` and its `assigned_lease_id` the lease; the original airframe has `assigned_lease_id` cleared and its `status` moved from `ASSIGNED` to `AVAILABLE`, except that an original already `IN_MAINTENANCE` or `AOG` keeps that status; and the lease's `primary_aircraft_id` is re-pointed to the substitute.

        PRD §3.7: Level two, caused by that re-point: every leg on the lease whose `status` is `SCHEDULED`, whose `aircraft_id` is the original airframe, and whose `scheduled_out` is at or after the substitution's `effective_from`, has its `aircraft_id` re-pointed to the substitute, and `repointed_leg_count` is written with the number re-pointed.

        PRD §3.7: Either way the request records `seat_delta` as the substitute's `seat_count` less the original's `seat_count` — a figure the lessee needs for its consent decision — and `repointed_leg_count` as 0 at creation, and the lease's `version` increments by 1.

        Design: Difficulty/transitive_cascade/substitution_effectuation_repoints_legs_then_cancels_unrated_crew
        """
        scenario = _setup_approved_cross_variant_substitution(api)
        assert scenario["substitution"]["status"] == "APPROVED", (
            "a LESSOR_UNILATERAL lease lands the request directly in APPROVED, got "
            f"{scenario['substitution']['status']}"
        )
        assert scenario["substitution"]["selection_basis"] == "CLIENT_SPECIFIED", (
            "naming substitute_aircraft_id records selection_basis CLIENT_SPECIFIED, "
            f"got {scenario['substitution']['selection_basis']!r}"
        )

        effectuated = effectuate_substitution(api, scenario["substitution"]["id"])

        assert effectuated["status"] == "EFFECTIVE", (
            f"effectuation moves the request to the terminal EFFECTIVE, got "
            f"{effectuated['status']}"
        )
        assert effectuated["seat_delta"] == -3, (
            "seat_delta is the substitute's 186 seats less the original's 189, expected "
            f"-3, got {effectuated['seat_delta']}"
        )
        assert effectuated["repointed_leg_count"] == 1, (
            "only the leg whose scheduled_out is at or after effective_from is "
            f"re-pointed, expected repointed_leg_count 1, got "
            f"{effectuated['repointed_leg_count']}"
        )

        substitute = validate_success(
            api.get_aircraft(scenario["substitute"]["id"], TECH)
        )
        assert substitute["status"] == "ASSIGNED", (
            f"level one assigns the substitute airframe, got {substitute['status']}"
        )
        assert substitute["assigned_lease_id"] == scenario["lease"]["id"], (
            "the substitute's assigned_lease_id must become the lease, got "
            f"{substitute['assigned_lease_id']!r}"
        )

        original = validate_success(api.get_aircraft(scenario["aircraft"]["id"], TECH))
        assert original["status"] == "AVAILABLE", (
            "level one releases the original airframe from ASSIGNED to AVAILABLE, got "
            f"{original['status']}"
        )
        assert original["assigned_lease_id"] is None, (
            "the original airframe's assigned_lease_id must be cleared, got "
            f"{original['assigned_lease_id']!r}"
        )

        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["primary_aircraft_id"] == scenario["substitute"]["id"], (
            "level one re-points the lease's airframe of record to the substitute, got "
            f"{lease['primary_aircraft_id']!r}"
        )

        repointed = validate_success(api.get_flight_leg(scenario["leg_after"]["id"], OPS))
        assert repointed["aircraft_id"] == scenario["substitute"]["id"], (
            "the leg whose scheduled_out is at or after effective_from must be "
            f"re-pointed to the substitute, got {repointed['aircraft_id']!r}"
        )

        untouched = validate_success(
            api.get_flight_leg(scenario["leg_before"]["id"], OPS)
        )
        assert untouched["aircraft_id"] == scenario["aircraft"]["id"], (
            "the leg whose scheduled_out precedes effective_from must keep the "
            f"original airframe, got {untouched['aircraft_id']!r}"
        )
        assert untouched["status"] == "SCHEDULED", (
            "the leg that was never re-pointed must stay SCHEDULED, got "
            f"{untouched['status']}"
        )

    def test_repointed_leg_whose_captain_lacks_the_substitute_variant_is_cancelled(
        self, api
    ):
        """PRD §2.7: Level three, caused by each leg re-point, cancels any re-pointed leg whose rostered pilots are not rated on the substitute's exact variant.

        PRD §3.7: Level three, caused by each leg re-point: any re-pointed leg whose captain or first officer does not hold the substitute's `type_designator` in `type_ratings` has `crew_requalification_required` set to true and is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `CREW`.

        PRD §3.7: Because eligibility turns on the family rather than the variant, a different-variant airframe of the same family is a lawful substitute even when the rostered crew are not rated on that variant.

        Design: Difficulty/transitive_cascade/substitution_effectuation_repoints_legs_then_cancels_unrated_crew
        """
        scenario = _setup_approved_cross_variant_substitution(api)

        effectuate_substitution(api, scenario["substitution"]["id"])

        repointed = validate_success(api.get_flight_leg(scenario["leg_after"]["id"], OPS))
        assert repointed["crew_requalification_required"] is True, (
            "the captain holds B738 only, so the re-pointed leg must set "
            "crew_requalification_required true, got "
            f"{repointed['crew_requalification_required']!r}"
        )
        assert repointed["status"] == "CANCELLED_LESSOR", (
            "level three cancels the re-pointed leg into CANCELLED_LESSOR, got "
            f"{repointed['status']}"
        )
        assert repointed["cancel_reason"] == "CREW", (
            f"the cancellation's cancel_reason must be CREW, got "
            f"{repointed['cancel_reason']!r}"
        )

    def test_cascade_recomputes_the_open_month_from_the_surviving_leg_only(self, api):
        """PRD §3.7: Level four, caused by each such cancellation: the `rolling_duty_minutes_7d` and `rolling_block_minutes_28d` of that leg's captain and first officer are recomputed, and the lease's `OPEN` utilization period covering the leg's `scheduled_out` is recomputed under the `PROVISIONAL` variant.

        PRD §3.8: Under the `PROVISIONAL` variant the include-set is every leg of the lease whose `scheduled_out` falls inside `period_month` and whose `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED`.

        PRD §3.8: Otherwise `shortfall_hours` is 0 and `overrun_hours` is `credited_hours` less `mgh_effective_hours`, rounded half up to four decimal places — so a month landing exactly on the guarantee produces neither.

        PRD §3.8: Each tier's hours are multiplied by the block-hour rate and by that tier's multiplier — 1.00 for the first tier, 1.15 for the second, and 1.35 for the third — and each of the three products is rounded half up to whole cents *individually*; `overrun_charge_cents` is the sum of those three rounded figures.

        PRD §2.11: Whichever variant most recently wrote a period's credited and shortfall/overrun fields is recorded in `variant_applied`, which holds either `PROVISIONAL` or `FINAL`.

        Design: Difficulty/transitive_cascade/substitution_effectuation_repoints_legs_then_cancels_unrated_crew
        """
        scenario = _setup_approved_cross_variant_substitution(api)

        effectuate_substitution(api, scenario["substitution"]["id"])

        period = validate_success(
            api.get_utilization_period(scenario["period"]["id"], BILLING)
        )

        assert period["credited_block_minutes"] == 330, (
            "only the surviving 330-minute SCHEDULED leg counts, got "
            f"{period['credited_block_minutes']}"
        )
        assert period["credited_hours"] == pytest.approx(5.5000, abs=0.0001), (
            f"330 minutes credits 5.5000 hours, got {period['credited_hours']}"
        )
        assert period["overrun_hours"] == pytest.approx(0.5000, abs=0.0001), (
            "credited hours exceed the 5.0000-hour prorated guarantee by 0.5000, got "
            f"{period['overrun_hours']}"
        )
        assert period["base_charge_cents"] == 2400000, (
            "the base guarantee charge is 5.0000 hours at 480000 cents, expected "
            f"2400000, got {period['base_charge_cents']}"
        )
        assert period["overrun_charge_cents"] == 240000, (
            "the 0.5000 overrun hours all fall in the first tier at multiplier 1.00, "
            f"expected 240000, got {period['overrun_charge_cents']}"
        )
        assert period["provisional_charge_cents"] == 2640000, (
            "the provisional net charge is 2400000 plus 240000, expected 2640000, got "
            f"{period['provisional_charge_cents']}"
        )
        assert period["variant_applied"] == "PROVISIONAL", (
            "the cascade recomputes the open month under the PROVISIONAL variant, got "
            f"{period['variant_applied']}"
        )
