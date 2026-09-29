"""Optimistic concurrency guards and the immediacy of the cascades.

The two superseding writes are guarded by an equality comparison against a live `version`,
so a client one behind and a client one ahead are refused alike and neither refusal
disturbs the row; and every cascade is walked to the bottom inside the triggering request,
so the very next read already observes the settled world.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_gross_charge_composition,
    close_month,
    create_aircraft,
    create_settlement_invoice_payload,
    create_substitution_payload,
    get_success_data,
    revoke_payload,
    schedule_leg,
    setup_active_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
UNDERWRITER = TEST_USERS["insurance_underwriter_headers"]

CLOCK = "2026-09-01T00:00:00Z"

SUBSTITUTE_AIRFRAME = {
    "tail_number": "G-SUBA",
    "type_designator": "B739",
    "type_family": "B737",
    "seat_count": 189,
    "mtow_kg": 85000,
    "airframe_hours_total": 12000.00,
    "hours_since_last_check": 90.00,
    "cycles_since_last_check": 20,
}


def test_a_period_version_one_behind_or_one_ahead_is_refused_and_the_live_one_succeeds(api):
    """PRD §2.6: The request that prepares a `SettlementInvoice` must carry `expected_period_version`, a non-optional field holding the `version` of the target `UtilizationPeriod` as the client last read it.
    PRD §2.6: If that value does not equal the period's current `version`, the request is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412).
    PRD §2.6: The check is purely a comparison against `UtilizationPeriod.version`; it is not a timing condition, and it says nothing about how close together two requests arrive.
    PRD §3.8: Closing recomputes every charge field under the `FINAL` variant, sets `variant_applied` to `FINAL`, writes `final_charge_cents`, and increments the period's `version`.
    PRD §3.9: The invoice is created with `status` `PREPARED`, its `lease_id` denormalised from the period for lessee-scoped queries, and `prepared_by_user_id` set to the acting `X-User-ID` while `approved_by_user_id` is null.

    Design: Corner/cross_cutting_complexity_layers/stale_or_future_period_version_on_invoice_prepare_returns_412
    """
    scenario = setup_active_lease(api, clock=CLOCK)
    close_month(api, scenario["period"]["id"])
    period = validate_success(
        api.get_utilization_period(scenario["period"]["id"], BILLING), 200
    )
    live_version = period["version"]
    assert period["status"] == "PENDING_SETTLEMENT", (
        f"the closed month must be PENDING_SETTLEMENT, got {period['status']}"
    )

    for offset in (-1, 1):
        validate_error(
            api.create_settlement_invoice(
                create_settlement_invoice_payload(
                    period["id"],
                    live_version + offset,
                    due_on="2026-10-15",
                    variant="FINAL",
                ),
                BILLING,
            ),
            ApiErrorId.ERR_STALE_PERIOD_VERSION,
        )

    untouched = get_success_data(api.get_utilization_period(period["id"], BILLING))
    assert untouched["version"] == live_version, (
        "a refused preparation must not increment the period's version, expected "
        f"{live_version}, got {untouched['version']}"
    )
    assert untouched["status"] == "PENDING_SETTLEMENT", (
        f"a refused preparation must not move the period, got {untouched['status']}"
    )

    invoice = validate_success(
        api.create_settlement_invoice(
            create_settlement_invoice_payload(
                period["id"], live_version, due_on="2026-10-15", variant="FINAL"
            ),
            BILLING,
        ),
        201,
    )
    assert invoice["status"] == "PREPARED", (
        f"the preparation at the live version must land PREPARED, got {invoice['status']}"
    )
    assert invoice["variant"] == "FINAL", (
        f"the requested variant must be recorded, got {invoice['variant']}"
    )
    assert invoice["amount_cents"] == period["final_charge_cents"], (
        "a FINAL invoice freezes the period's final_charge_cents, expected "
        f"{period['final_charge_cents']}, got {invoice['amount_cents']}"
    )


def test_a_lease_version_one_behind_is_refused_before_the_substitute_is_even_evaluated(api):
    """PRD §2.6: The request that creates an `AircraftSubstitution` must carry `expected_lease_version`, a non-optional field holding the `version` of the target `LeaseAgreement` as the client last read it.
    PRD §2.6: A mismatch against the lease's current `version` is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412).
    PRD §2.6: A new substitution request legitimately supersedes prior open requests on the same lease and, on a lease whose substitution rights are unilateral, withdraws them outright — so a writer whose view of the lease predates the last airframe re-point, suspension or activation must re-read the lease before it is permitted to supersede anything.
    PRD §3.7: When `substitute_aircraft_id` is supplied, `selection_basis` is recorded as `CLIENT_SPECIFIED` and the named airframe must satisfy every eligibility test: its `type_family` must equal the original's `type_family` (the exact `type_designator` may differ, which is what makes the crew-rating cascade reachable), its `seat_count` must be at least the original's `seat_count` less a tolerance of five seats, its `status` must be `AVAILABLE`, its `assigned_lease_id` must be null, and its `hours_since_last_check` must not exceed 400.00 hours.
    PRD §3.7: On a lease whose rights are `LESSOR_UNILATERAL` the request lands directly in `APPROVED`, `seat_delta` is written, no airframe is touched yet, and — this is the branch's extra effect — every other substitution on the same lease whose `status` is `REQUESTED`, `LESSEE_CONSENT_PENDING` or `APPROVED` is moved to the terminal `WITHDRAWN`, without touching any airframe.

    Design: Corner/cross_cutting_complexity_layers/stale_lease_version_on_substitution_request_returns_412
    """
    scenario = setup_active_lease(api, clock=CLOCK)
    substitute = create_aircraft(api, **SUBSTITUTE_AIRFRAME)
    lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
    live_version = lease["version"]

    def request_at(expected_lease_version):
        return api.create_substitution(
            create_substitution_payload(
                lease["id"],
                scenario["aircraft"]["id"],
                expected_lease_version,
                reason="SCHEDULED_MAINTENANCE",
                effective_from="2026-09-20T00:00:00Z",
                substitute_aircraft_id=substitute["id"],
            ),
            OPS,
        )

    validate_error(request_at(live_version - 1), ApiErrorId.ERR_STALE_LEASE_VERSION)

    untouched_lease = get_success_data(api.get_lease(lease["id"], OPS))
    assert untouched_lease["version"] == live_version, (
        "a refused substitution request must not increment the lease's version, expected "
        f"{live_version}, got {untouched_lease['version']}"
    )
    assert untouched_lease["primary_aircraft_id"] == scenario["aircraft"]["id"], (
        "the version guard runs before the substitute is evaluated, so the airframe of "
        "record must be untouched"
    )
    untouched_substitute = get_success_data(api.get_aircraft(substitute["id"], TECH))
    assert untouched_substitute["status"] == "AVAILABLE", (
        f"the refused request must leave the substitute AVAILABLE, got {untouched_substitute['status']}"
    )

    substitution = validate_success(request_at(live_version), 201)
    assert substitution["status"] == "APPROVED", (
        "on a LESSOR_UNILATERAL lease the accepted request lands directly in APPROVED, got "
        f"{substitution['status']}"
    )
    assert substitution["selection_basis"] == "CLIENT_SPECIFIED", (
        "a named substitute must be recorded as CLIENT_SPECIFIED, got "
        f"{substitution['selection_basis']}"
    )

    requests, meta = validate_paginated(
        api.list_substitutions(OPS, params={"lease_id": lease["id"]})
    )
    assert meta["total_count"] == 1, (
        "only the accepted request may exist on the lease, expected 1, got "
        f"{meta['total_count']}"
    )
    assert len(requests) == 1, (
        f"only the accepted request may exist on the lease, got {len(requests)} rows"
    )


def test_the_insurance_lapse_cascade_is_settled_by_the_time_the_next_read_runs(api):
    """PRD §2.7: A single event in this domain rarely touches a single row. Two cascades in particular are four levels deep, and the server is required to walk them to the bottom within the same request.
    PRD §3.3: If no `ACTIVE` certificate remains on the lease afterwards, the four-level lapse cascade of §2.7 runs in full: the lease drops from `ACTIVE` to `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSED`, every leg still `SCHEDULED` or `DISPATCHED` on that lease is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `INSURANCE_LAPSE`, and each cancellation recomputes that leg's crew exposure and the open month's charge.
    PRD §3.5: In every case the legs still `SCHEDULED` or `DISPATCHED` on the lease are cancelled into `CANCELLED_LESSOR` with `cancelling_party` `LESSOR` and a `cancel_reason` matched to the cause — `INSURANCE_LAPSE`, `REGULATORY` or `TECHNICAL` respectively — and each cancellation recomputes crew exposure and the open month's charge.
    PRD §2.4: Cancelled and diverted legs are excluded from both sums, which is exactly what makes a cancellation an exact compensation for the scheduling that preceded it.
    PRD §3.8: Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure.
    PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.
    PRD §3.8: If no accepted report exists for the month, `reliability_penalty_cents` is 0 and no penalty applies.

    Design: Corner/consistency_model/revocation_cascade_is_visible_to_the_very_next_read_with_no_settling_time
    """
    scenario = setup_active_lease(api, clock=CLOCK)
    leg = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:25:00Z",
        origin_icao="EGSS",
        dest_icao="LEPA",
        leg_class="REVENUE",
    )

    revoked = validate_success(
        api.revoke_insurance_certificate(
            scenario["certificate"]["id"],
            revoke_payload("PREMIUM_NON_PAYMENT"),
            UNDERWRITER,
        ),
        200,
    )
    assert revoked["status"] == "REVOKED", (
        f"pulling cover must move the certificate to REVOKED, got {revoked['status']}"
    )
    assert revoked["revocation_reason"] == "PREMIUM_NON_PAYMENT", (
        f"the revocation reason must be recorded, got {revoked['revocation_reason']!r}"
    )

    # No retry, poll or sleep: the reads below run immediately after the revoke response.
    lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
    assert lease["status"] == "SUSPENDED", (
        f"level two must already be visible: the lease must be SUSPENDED, got {lease['status']}"
    )
    assert lease["suspension_reason"] == "INSURANCE_LAPSED", (
        f"the suspension must be stamped INSURANCE_LAPSED, got {lease['suspension_reason']!r}"
    )

    cancelled_leg = get_success_data(api.get_flight_leg(leg["id"], OPS))
    assert cancelled_leg["status"] == "CANCELLED_LESSOR", (
        f"level three must already be visible: the leg must be CANCELLED_LESSOR, got {cancelled_leg['status']}"
    )
    assert cancelled_leg["cancel_reason"] == "INSURANCE_LAPSE", (
        f"the cancellation must be attributed to INSURANCE_LAPSE, got {cancelled_leg['cancel_reason']!r}"
    )
    assert cancelled_leg["cancelling_party"] == "LESSOR", (
        f"the cancelling party must be LESSOR, got {cancelled_leg['cancelling_party']!r}"
    )

    for role, crew_id in (
        ("captain", scenario["captain"]["id"]),
        ("first officer", scenario["first_officer"]["id"]),
    ):
        crew = get_success_data(api.get_crew_member(crew_id, OPS))
        assert crew["rolling_duty_minutes_7d"] == 0, (
            f"level four must already be visible: the {role}'s rolling duty exposure must "
            f"exclude the cancelled leg, expected 0, got {crew['rolling_duty_minutes_7d']}"
        )
        assert crew["rolling_block_minutes_28d"] == 0, (
            f"level four must already be visible: the {role}'s rolling block exposure must "
            f"exclude the cancelled leg, expected 0, got {crew['rolling_block_minutes_28d']}"
        )

    periods, _ = validate_paginated(
        api.list_utilization_periods(
            BILLING,
            params={"lease_id": scenario["lease"]["id"], "period_month": "2026-09"},
        )
    )
    assert len(periods) == 1, f"exactly one 2026-09 period must exist, got {len(periods)}"
    period = periods[0]
    assert period["status"] == "OPEN", (
        f"the covering month must still be OPEN, got {period['status']}"
    )
    assert float(period["credited_hours"]) == 0, (
        "a lessor-cancelled leg contributes nothing, so credited_hours must be 0.0000, got "
        f"{period['credited_hours']}"
    )
    assert period["base_charge_cents"] == 2400000, (
        "the whole-month guarantee of 5 hours at 480000 cents is 2400000 cents, got "
        f"{period['base_charge_cents']}"
    )
    assert period["shortfall_credit_cents"] == 696010, (
        "the 145 lessor-cancelled minutes are 2.4167 hours, credited at 60 percent of the "
        f"block-hour rate, expected 696010, got {period['shortfall_credit_cents']}"
    )
    assert_gross_charge_composition(period)
    assert period["gross_charge_cents"] == 1703990, (
        "gross_charge_cents must be 2400000 less the 696010 shortfall credit, got "
        f"{period['gross_charge_cents']}"
    )
    assert period["reliability_penalty_cents"] == 0, (
        "no accepted reliability report exists for the month, so the penalty must be 0, got "
        f"{period['reliability_penalty_cents']}"
    )
    assert period["provisional_charge_cents"] == period["gross_charge_cents"], (
        "with no penalty the provisional charge equals the gross charge, expected "
        f"{period['gross_charge_cents']}, got {period['provisional_charge_cents']}"
    )
