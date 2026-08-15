"""Lease agreement lifecycle: lazy expiry, OCC amendment, state gates,
early termination fee."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_lease,
    create_lease_assignment_payload,
    create_lessee,
    get_assignment,
    get_lessee_balance,
    get_success_data,
    set_clock,
    setup_active_lease_scenario,
    validate_error,
    validate_success,
)

LEASE_ADMIN = TEST_USERS["lease_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
PLANNER = TEST_USERS["fleet_planner_headers"]


class TestLeaseExpiry:
    def test_lease_expires_automatically_past_end_date(self, api):
        """PRD §3.3: "A lease also expires passively: whenever the lease is
        read or mutated and the current logical date is after its `end_date`,
        an `ACTIVE` lease transitions to `EXPIRED`."
        PRD §2.5: "A `SystemAdmin` may advance the clock to a supplied
        `to_iso8601` instant through the test-driving capability listed in
        §4; the response echoes the new reading as `current_utc`."

        Design: Corner/state_machines/lease_expires_automatically_past_end_date
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX2000", lease_type="NET", lease_start="2026-08-01",
            lease_end="2026-08-31", with_assignment=False,
        )
        lease = scenario["lease"]
        assert lease["status"] == "ACTIVE"
        set_clock("2026-09-01T00:00:00Z")
        after = get_success_data(api.get_lease_agreement(lease["id"], LEASE_ADMIN))
        assert after["status"] == "EXPIRED", (
            "Reading the lease after the clock passes end_date must lazily "
            "transition it to EXPIRED"
        )


class TestLeaseAmendmentOcc:
    def test_lease_amend_stale_version_rejected(self, api):
        """PRD §2.11: "Amending a lease agreement requires
        `expected_lease_version` carrying the client's last observed `version`
        of the lease. A lease in `DRAFT` or `ACTIVE` remains legitimately
        amendable, so a stale `expected_lease_version` is the only signal that
        another writer has already changed the terms the client based its
        amendment on; the mismatch is rejected with `ERR_STALE_VERSION`
        (412)."

        Design: Corner/cross_cutting_layers/lease_amend_stale_version_rejected
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX2002", with_assignment=False
        )
        lease = scenario["lease"]
        observed_version = lease["version"]

        first = validate_success(
            api.amend_lease_agreement(
                lease["id"],
                {"base_daily_rate_cents": 5500,
                 "expected_lease_version": observed_version},
                LEASE_ADMIN,
            )
        )
        assert first["base_daily_rate_cents"] == 5500
        assert first["version"] == observed_version + 1, (
            "A successful amendment increments the lease's version by 1 (§3.3)"
        )

        replayed = api.amend_lease_agreement(
            lease["id"],
            {"base_daily_rate_cents": 6000,
             "expected_lease_version": observed_version},
            LEASE_ADMIN,
        )
        validate_error(replayed, ApiErrorId.ERR_STALE_VERSION, 412)
        after = get_success_data(api.get_lease_agreement(lease["id"], LEASE_ADMIN))
        assert after["base_daily_rate_cents"] == 5500, (
            "The stale amendment must not apply"
        )


class TestLeaseStateGates:
    def test_assignment_on_draft_lease_returns_lease_not_active(self, api):
        """PRD §2.7: "Creating an assignment requires the lease to be
        `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`), the lessee to be `ACTIVE`
        (`ERR_LESSEE_NOT_ACTIVE`), and the railcar to be `AVAILABLE`
        (`ERR_RAILCAR_NOT_AVAILABLE`)."

        Design: Corner/validations/assignment_on_draft_lease_returns_lease_not_active
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1401", with_assignment=False
        )
        # A second lease that is never submitted stays DRAFT.
        draft = create_lease(scenario["lessee"]["id"])

        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=draft["id"],
                railcar_id=scenario["railcar"]["id"],
                planned_commodity="GRAIN",
                scheduled_start="2026-08-10",
                scheduled_end="2026-08-20",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE, 409)


class TestEarlyTermination:
    def test_early_termination_fee_capped_at_90_days(self, api):
        """PRD §3.3: "First, an `early_termination_fee_cents` is computed:
        take the number of days from the current logical date to the
        `end_date`, floor it at zero, cap it at 90 days, multiply by
        `base_daily_rate_cents`, and take 50 percent, rounding half-up to a
        whole cent. Second, every `SCHEDULED` assignment of the lease is
        cancelled with `cancellation_reason` `LEASE_TERMINATED`. Third, the
        fee is added to the lessee's `outstanding_balance_cents`, and the
        auto-suspension rule of §3.1 is re-evaluated."

        Design: Corner/calculations/early_termination_fee_capped_at_90_days
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1306", window_start="2026-12-05",
            window_end="2027-01-05",
        )
        lease = scenario["lease"]
        assignment = scenario["assignment"]
        set_clock("2026-12-01T00:00:00Z")

        terminated = validate_success(
            api.terminate_lease_agreement(lease["id"], LEASE_ADMIN)
        )
        assert terminated["status"] == "TERMINATED"
        # 242 remaining days are capped at 90: 90 x 5000 x 50% = 225000.
        assert terminated["early_termination_fee_cents"] == 225000

        after_assignment = get_assignment(assignment["id"])
        assert after_assignment["status"] == "CANCELLED"
        assert after_assignment["cancellation_reason"] == "LEASE_TERMINATED"
        assert get_lessee_balance(scenario["lessee"]["id"]) == 225000


class TestAssignmentWindowContainment:
    def test_assignment_outside_lease_term_rejected(self, api):
        """PRD §3.4: "The whole assignment window must lie within the lease
        term from `start_date` to `end_date` (`ERR_OUTSIDE_LEASE_TERM`,
        422)."

        Design: Corner/validations/assignment_outside_lease_term_rejected
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1408", tariff_to="2028-01-01", with_assignment=False,
        )
        resp = api.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=scenario["lease"]["id"],
                railcar_id=scenario["railcar"]["id"],
                planned_commodity="GRAIN",
                scheduled_start="2027-07-01",
                scheduled_end="2027-08-01",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_LEASE_TERM, 422)
