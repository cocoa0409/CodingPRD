"""Validation ordering on write endpoints.

Each pair below arranges two independently sufficient rejections on one request and
proves the API reports the earlier check in the sequence the PRD declares, plus a
companion request in which only the later failure is present, so that the later check
is shown to be live rather than absent.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_lease,
    close_month,
    create_aircraft,
    create_captain,
    create_first_officer,
    create_flight_leg_payload,
    create_lease,
    create_settlement_invoice_payload,
    file_lease_with_authority,
    file_reliability_report,
    first_open_period,
    fly_leg,
    issue_insurance_certificate,
    qualify_crew_member,
    record_determination,
    schedule_leg,
    setup_active_lease,
    setup_settled_month,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

# A credit limit deliberately below the value of two settled months.
CREDIT_LIMIT_USD_CENTS = 3_000_000

# Three completed 100-minute revenue legs against a 5-hour guarantee at 480,000 cents
# per block hour settle at this figure.
FINAL_CHARGE_CENTS = 2_400_048

HUNDRED_MINUTE_LEGS = [
    {
        "scheduled_out": "2026-09-10T06:00:00Z",
        "scheduled_in": "2026-09-10T07:40:00Z",
        "dest_icao": "LEPA",
        "technical_delay_minutes": 0,
    },
    {
        "scheduled_out": "2026-09-11T06:00:00Z",
        "scheduled_in": "2026-09-11T07:40:00Z",
        "dest_icao": "LFPG",
        "technical_delay_minutes": 0,
    },
    {
        "scheduled_out": "2026-09-12T06:00:00Z",
        "scheduled_in": "2026-09-12T07:40:00Z",
        "dest_icao": "EIDW",
        "technical_delay_minutes": 0,
    },
]

# 795 scheduled block minutes carries 900 duty minutes with the 105-minute allowance.
LONG_LEGS = [
    ("2026-09-28T06:00:00Z", "2026-09-28T19:15:00Z", "LEPA"),
    ("2026-09-29T06:00:00Z", "2026-09-29T19:15:00Z", "LFPG"),
    ("2026-09-30T06:00:00Z", "2026-09-30T19:15:00Z", "EIDW"),
]


def _second_settled_lease_for_same_lessee(api, scenario: dict) -> dict:
    """Bring a second lease of the same lessee to a closed month awaiting settlement."""
    aircraft = create_aircraft(
        api,
        tail_number="G-ACM2",
        airframe_hours_total=24000.00,
        hours_since_last_check=120.00,
        cycles_since_last_check=40,
    )
    captain = create_captain(api, full_name="C Duval", employee_no="EMP-2001")
    first_officer = create_first_officer(api, full_name="D Marchetti", employee_no="EMP-2002")
    lease = create_lease(api, scenario["lessee"]["id"], aircraft["id"])
    approval = file_lease_with_authority(
        api, lease["id"], authority_docket_no="CAA-2026-4472"
    )
    record_determination(api, approval["id"], "APPROVED")
    issue_insurance_certificate(api, lease["id"], certificate_no="COI-88002")
    qualify_crew_member(api, captain["id"], lease["id"])
    qualify_crew_member(api, first_officer["id"], lease["id"])
    lease = activate_lease(api, lease["id"])
    second = {
        "lessee": scenario["lessee"],
        "lessee_headers": scenario["lessee_headers"],
        "aircraft": aircraft,
        "captain": captain,
        "first_officer": first_officer,
        "lease": lease,
        "period": first_open_period(api, lease["id"]),
    }
    for day, dest in (("20", "LEPA"), ("21", "LFPG"), ("22", "EIDW")):
        fly_leg(
            api,
            second,
            scheduled_out=f"2026-09-{day}T06:00:00Z",
            scheduled_in=f"2026-09-{day}T07:40:00Z",
            dest_icao=dest,
            technical_delay_minutes=0,
        )
    second["period"] = close_month(api, second["period"]["id"])
    file_reliability_report(api, second, period_month="2026-09")
    return second


class TestPeriodStateOutranksCreditLimit:
    def test_settled_period_reports_period_readiness_not_credit_limit(self, api):
        """PRD §2.8: Because most write endpoints in this system guard against half a dozen distinct failures, the order in which checks run is part of the contract: the first check that fails determines the response, and a later check never masks an earlier one.
        PRD §2.8: **State guards**, in this order: lessee state (`ERR_LESSEE_INVALID_STATE`), period readiness for settlement (`ERR_PERIOD_NOT_READY_FOR_SETTLEMENT`), lease state (`ERR_LEASE_INVALID_STATE`), docket determination state (`ERR_APPROVAL_INVALID_STATE`), leg state (`ERR_LEG_INVALID_STATE`), substitution state (`ERR_SUBSTITUTION_INVALID_STATE`), invoice state (`ERR_INVOICE_INVALID_STATE`), period state (`ERR_PERIOD_INVALID_STATE`), return-condition state (`ERR_RETURN_CONDITION_INVALID_STATE`), and finally airframe availability (`ERR_AIRCRAFT_UNAVAILABLE`).
        PRD §2.8: **Billing governance**, in this order: an accepted reliability report for the month (`ERR_RELIABILITY_REPORT_NOT_ACCEPTED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and the lessee's credit limit (`ERR_LESSEE_CREDIT_LIMIT_EXCEEDED`).
        PRD §3.9: The target period must be `PENDING_SETTLEMENT`, else `ERR_PERIOD_NOT_READY_FOR_SETTLEMENT` (HTTP 409).
        PRD §3.9: Issue moves the invoice from `APPROVED` to `ISSUED`, records `due_on`, adds `amount_cents` to the lessee's `outstanding_balance_usd_cents`, and — when the invoice's `variant` is `FINAL` — drives the period from `PENDING_SETTLEMENT` to `SETTLED`.

        Design: Difficulty/priority_pair_validation_conflict/period_state_error_outranks_credit_limit_error_on_invoice_prepare
        """
        scenario = setup_settled_month(
            api,
            leg_plan=HUNDRED_MINUTE_LEGS,
            lessee_overrides={"credit_limit_usd_cents": CREDIT_LIMIT_USD_CENTS},
        )
        period = validate_success(
            api.get_utilization_period(scenario["period"]["id"], BILLING)
        )
        assert period["status"] == "SETTLED", (
            "expected the month to be SETTLED after its FINAL invoice was issued, got "
            f"{period['status']}"
        )
        assert period["final_charge_cents"] == FINAL_CHARGE_CENTS, (
            f"expected final_charge_cents {FINAL_CHARGE_CENTS}, got "
            f"{period['final_charge_cents']}"
        )
        lessee = validate_success(api.get_lessee(scenario["lessee"]["id"], BILLING))
        assert lessee["outstanding_balance_usd_cents"] == FINAL_CHARGE_CENTS, (
            f"expected the receivable to stand at {FINAL_CHARGE_CENTS} after issue, got "
            f"{lessee['outstanding_balance_usd_cents']}"
        )
        assert (
            lessee["outstanding_balance_usd_cents"] + period["final_charge_cents"]
            > lessee["credit_limit_usd_cents"]
        ), "the second settlement must also breach the credit ceiling for this pair to be a conflict"

        response = api.create_settlement_invoice(
            create_settlement_invoice_payload(
                period["id"], period["version"], "2026-11-15", variant="FINAL"
            ),
            BILLING,
        )

        error = validate_error(response, ApiErrorId.ERR_PERIOD_NOT_READY_FOR_SETTLEMENT)
        assert error["error_id"] != ApiErrorId.ERR_LESSEE_CREDIT_LIMIT_EXCEEDED.value, (
            "the credit-limit check runs after the period-readiness state guard and must "
            "not mask it"
        )
        assert error["error_id"] != ApiErrorId.ERR_STALE_PERIOD_VERSION.value, (
            "the request carried the period's current version, so no stale-version "
            "rejection is admissible"
        )
        invoices, _ = validate_paginated(
            api.list_settlement_invoices(BILLING, params={"period_id": period["id"]})
        )
        assert len(invoices) == 1, (
            f"expected the rejected preparation to create no invoice, found {len(invoices)}"
        )
        lessee_after = validate_success(api.get_lessee(scenario["lessee"]["id"], BILLING))
        assert lessee_after["outstanding_balance_usd_cents"] == FINAL_CHARGE_CENTS, (
            "a rejected preparation must leave the receivable at "
            f"{FINAL_CHARGE_CENTS}, got {lessee_after['outstanding_balance_usd_cents']}"
        )

    def test_credit_limit_alone_is_reported_when_the_period_awaits_settlement(self, api):
        """PRD §2.8: **Billing governance**, in this order: an accepted reliability report for the month (`ERR_RELIABILITY_REPORT_NOT_ACCEPTED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and the lessee's credit limit (`ERR_LESSEE_CREDIT_LIMIT_EXCEEDED`).
        PRD §3.9: Issue is admissible only from `APPROVED` and requires that the lessee's `outstanding_balance_usd_cents` plus the invoice's `amount_cents` not exceed the lessee's `credit_limit_usd_cents`; a breach is refused with `ERR_LESSEE_CREDIT_LIMIT_EXCEEDED` (HTTP 402).
        PRD §3.9: The same ceiling is tested at preparation time against the amount about to be invoiced.
        PRD §2.9: `Lessee.outstanding_balance_usd_cents` equals the sum of `amount_cents` over every `SettlementInvoice` whose `status` is `ISSUED` and whose lease belongs to that lessee.

        Design: Difficulty/priority_pair_validation_conflict/period_state_error_outranks_credit_limit_error_on_invoice_prepare
        """
        scenario = setup_settled_month(
            api,
            leg_plan=HUNDRED_MINUTE_LEGS,
            lessee_overrides={"credit_limit_usd_cents": CREDIT_LIMIT_USD_CENTS},
        )
        second = _second_settled_lease_for_same_lessee(api, scenario)

        period = validate_success(
            api.get_utilization_period(second["period"]["id"], BILLING)
        )
        assert period["status"] == "PENDING_SETTLEMENT", (
            "the second lease's month must be PENDING_SETTLEMENT so the period-readiness "
            f"guard passes, got {period['status']}"
        )
        assert period["final_charge_cents"] == FINAL_CHARGE_CENTS, (
            f"expected final_charge_cents {FINAL_CHARGE_CENTS}, got "
            f"{period['final_charge_cents']}"
        )
        lessee = validate_success(api.get_lessee(scenario["lessee"]["id"], BILLING))
        assert lessee["outstanding_balance_usd_cents"] == FINAL_CHARGE_CENTS, (
            f"expected the receivable to stand at {FINAL_CHARGE_CENTS} from the first "
            f"lease's issued invoice, got {lessee['outstanding_balance_usd_cents']}"
        )

        response = api.create_settlement_invoice(
            create_settlement_invoice_payload(
                period["id"], period["version"], "2026-11-15", variant="FINAL"
            ),
            BILLING,
        )

        validate_error(response, ApiErrorId.ERR_LESSEE_CREDIT_LIMIT_EXCEEDED)
        invoices, _ = validate_paginated(
            api.list_settlement_invoices(BILLING, params={"period_id": period["id"]})
        )
        assert invoices == [], (
            f"expected no invoice on the rejected period, found {len(invoices)}"
        )
        lessee_after = validate_success(api.get_lessee(scenario["lessee"]["id"], BILLING))
        assert lessee_after["outstanding_balance_usd_cents"] == FINAL_CHARGE_CENTS, (
            "a rejected preparation must leave the receivable at "
            f"{FINAL_CHARGE_CENTS}, got {lessee_after['outstanding_balance_usd_cents']}"
        )


class TestCrewDutyOutranksLeaseTerm:
    def test_out_of_term_leg_over_the_duty_ceiling_reports_the_duty_breach(self, api):
        """PRD §2.8: **Crew safety**, in this order: type rating and crew standing (`ERR_CREW_NOT_TYPE_RATED`), rolling seven-day duty exposure (`ERR_CREW_DUTY_LIMIT_EXCEEDED`), rolling twenty-eight-day block exposure (`ERR_CREW_BLOCK_LIMIT_EXCEEDED`), and lessee-procedures qualification (`ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES`).
        PRD §2.8: **Temporal gates**, in this order: a leg falling inside the lease term (`ERR_LEG_OUTSIDE_LEASE_TERM`), airframe occupancy conflict (`ERR_AIRCRAFT_SCHEDULE_CONFLICT`), and certificate period overlap (`ERR_INSURANCE_PERIOD_OVERLAP`).
        PRD §3.4: For the crew member under test, the projected seven-day duty is that crew member's candidate leg duty — its scheduled block minutes plus the 105-minute allowance — plus the same duty figure summed over that crew member's other legs in `SCHEDULED`, `DISPATCHED` or `COMPLETED` whose `scheduled_out` falls at or after the instant 168 hours before the candidate's off-blocks instant and strictly before that instant.
        PRD §3.4: Exceeding the duty limit yields `ERR_CREW_DUTY_LIMIT_EXCEEDED` (HTTP 409); exceeding the block limit yields `ERR_CREW_BLOCK_LIMIT_EXCEEDED` (HTTP 409).

        Design: Difficulty/priority_pair_validation_conflict/crew_duty_safety_error_outranks_lease_term_temporal_error_on_leg_create
        """
        scenario = setup_active_lease(
            api, lease_overrides={"term_end_date": "2026-09-30"}
        )
        for scheduled_out, scheduled_in, dest in LONG_LEGS:
            leg = schedule_leg(
                api, scenario, scheduled_out, scheduled_in, dest_icao=dest
            )
            assert leg["scheduled_block_minutes"] == 795, (
                "each accumulating leg must carry 795 scheduled block minutes, got "
                f"{leg['scheduled_block_minutes']}"
            )

        # 3 x 900 stored duty minutes plus the candidate's own 901 projects 3601.
        response = api.create_flight_leg(
            create_flight_leg_payload(
                scenario["lease"]["id"],
                scenario["aircraft"]["id"],
                scenario["captain"]["id"],
                scenario["first_officer"]["id"],
                scheduled_out="2026-10-05T00:00:00Z",
                scheduled_in="2026-10-05T13:16:00Z",
                dest_icao="LIRF",
            ),
            OPS,
        )

        error = validate_error(response, ApiErrorId.ERR_CREW_DUTY_LIMIT_EXCEEDED)
        assert error["error_id"] != ApiErrorId.ERR_LEG_OUTSIDE_LEASE_TERM.value, (
            "the lease-term temporal gate runs after crew safety and must not mask the "
            "duty breach"
        )
        legs, _ = validate_paginated(
            api.list_flight_legs(OPS, params={"lease_id": scenario["lease"]["id"]})
        )
        assert len(legs) == 3, (
            f"expected the rejected candidate to create no leg, found {len(legs)} legs"
        )

    def test_out_of_term_leg_within_the_duty_ceiling_reports_the_term_breach(self, api):
        """PRD §3.6: The leg must fall inside the lease term — the calendar date of `scheduled_out` not earlier than `term_start_date` and the calendar date of `scheduled_in` not later than `term_end_date` — else `ERR_LEG_OUTSIDE_LEASE_TERM` (HTTP 422).
        PRD §3.4: The limits are 3,600 minutes of projected seven-day duty — sixty hours — and 5,400 minutes of projected twenty-eight-day block time — ninety hours.
        PRD §2.8: **Temporal gates**, in this order: a leg falling inside the lease term (`ERR_LEG_OUTSIDE_LEASE_TERM`), airframe occupancy conflict (`ERR_AIRCRAFT_SCHEDULE_CONFLICT`), and certificate period overlap (`ERR_INSURANCE_PERIOD_OVERLAP`).

        Design: Difficulty/priority_pair_validation_conflict/crew_duty_safety_error_outranks_lease_term_temporal_error_on_leg_create
        """
        scenario = setup_active_lease(
            api, lease_overrides={"term_end_date": "2026-09-30"}
        )

        # No accumulated legs, so the identical candidate projects only its own 901 duty
        # minutes and the term gate is the sole remaining failure.
        response = api.create_flight_leg(
            create_flight_leg_payload(
                scenario["lease"]["id"],
                scenario["aircraft"]["id"],
                scenario["captain"]["id"],
                scenario["first_officer"]["id"],
                scheduled_out="2026-10-05T00:00:00Z",
                scheduled_in="2026-10-05T13:16:00Z",
                dest_icao="LIRF",
            ),
            OPS,
        )

        validate_error(response, ApiErrorId.ERR_LEG_OUTSIDE_LEASE_TERM)
        legs, _ = validate_paginated(
            api.list_flight_legs(OPS, params={"lease_id": scenario["lease"]["id"]})
        )
        assert legs == [], (
            f"expected the out-of-term candidate to create no leg, found {len(legs)}"
        )
