"""Distribution run remit cascades, supersede lineage, agent retention,
oldest-first principal allocation, and payment-version OCC (PRD §2.8, §3.5)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_distribution_run,
    assert_pools_cover_lines,
    assert_waterfall_conservation,
    create_payment,
    create_run,
    demand_buyback,
    facility_version,
    get_facility,
    get_participant,
    get_success_data,
    lines_for_run,
    make_agent_headers,
    make_borrower_headers,
    set_clock,
    settle_buyback,
    setup_funded_facility,
    validate_error,
    validate_paginated,
    validate_success,
    create_draw_payload,
)

AGENT = make_agent_headers()


def _payoff_setup():
    """2,000,000 facility with two equal participants, fully funded on a
    2,000,000 draw from 2026-08-01."""
    return setup_funded_facility(
        [("P1", 1_000_000), ("P2", 1_000_000)],
        2_000_000,
        facility_overrides={"total_commitment_cents": 2_000_000},
    )


class TestRemitCascadeClosesFacility:
    def test_remit_cascade_closes_facility(self):
        """PRD §3.5: "Hop 4: when both outstanding principal and accrued interest
        reach zero and at least one payment has been remitted, the facility
        bubbles to `CLOSED` — from `ACTIVE` or from `ACCELERATED` alike — and the
        payment bubbles `ALLOCATED` → `REMITTED`."
        PRD §3.5: "Hop 2: each remitted line credits its participant's
        `cumulative_interest_cents` and `cumulative_principal_cents`".

        Design: Difficulty/transitive_cascade/remit_cascade_closes_facility
        """
        setup = _payoff_setup()
        facility = setup["facility"]
        borrower = setup["borrower"]
        p1, p2 = setup["participants"]

        # fee 416 + interest 20,000 + principal 2,000,000: exact full payoff.
        pay = create_payment(facility["id"], borrower["id"], 2_020_416, "2026-08-31")
        run = create_run(pay["id"])
        assert run["servicing_fee_cents"] == 416
        assert run["interest_pool_cents"] == 20_000
        assert run["principal_pool_cents"] == 2_000_000

        remitted = validate_success(api_client.remit_distribution_run(run["id"], AGENT))
        assert_distribution_run(remitted)
        assert remitted["status"] == "REMITTED"
        assert remitted["remitted_at"] is not None

        lines = lines_for_run(run["id"])
        assert len(lines) == 2
        assert all(line["status"] == "REMITTED" for line in lines)
        assert get_participant(p1["id"])["cumulative_interest_cents"] == 10_000
        assert get_participant(p1["id"])["cumulative_principal_cents"] == 1_000_000
        assert get_participant(p2["id"])["cumulative_interest_cents"] == 10_000
        assert get_participant(p2["id"])["cumulative_principal_cents"] == 1_000_000

        refreshed = get_facility(facility["id"])
        assert refreshed["outstanding_principal_cents"] == 0
        assert refreshed["accrued_interest_cents"] == 0
        assert refreshed["status"] == "CLOSED"

        payment = get_success_data(api_client.get_payment(pay["id"], AGENT))
        assert payment["status"] == "REMITTED"

    def test_closed_facility_rejects_payments_and_draws(self):
        """PRD §3.5: "Payments are accepted only while the facility is `ACTIVE`,
        `IN_DEFAULT`, or `ACCELERATED`; in any other status the recording is
        rejected with `ERR_INVALID_STATE_TRANSITION`".
        PRD §2.9: "7. Cross-entity facility posture: the facility is not in
        `IN_DEFAULT`, `ACCELERATED`, `CLOSED`, or `TERMINATED` for solicitation,
        transfer propose and settle, and prepayment payments; the facility is
        `COMMITTED` for draw creation; the facility is in `FUNDING`, `ACTIVE`,
        `IN_DEFAULT`, or `ACCELERATED` for buyback demands — otherwise
        `ERR_FACILITY_IN_DEFAULT` or `ERR_FACILITY_NOT_COMMITTED` as the rule
        nominates."

        Design: Difficulty/transitive_cascade/remit_cascade_closes_facility
        """
        setup = _payoff_setup()
        facility = setup["facility"]
        borrower = setup["borrower"]
        pay = create_payment(facility["id"], borrower["id"], 2_020_416, "2026-08-31")
        run = create_run(pay["id"])
        validate_success(api_client.remit_distribution_run(run["id"], AGENT))
        assert get_facility(facility["id"])["status"] == "CLOSED"

        resp = api_client.create_payment(
            {
                "facility_id": facility["id"],
                "payment_type": "REGULAR",
                "amount_cents": 10_000,
                "value_date": "2026-09-15",
            },
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

        resp2 = api_client.create_draw(
            create_draw_payload(
                facility["id"],
                expected_facility_version=facility_version(facility["id"]),
                draw_amount_cents=100_000,
                accrual_start_date="2026-09-01",
                accrual_end_date="2027-09-01",
            ),
            AGENT,
        )
        validate_error(resp2, ApiErrorId.ERR_FACILITY_NOT_COMMITTED, expected_status=409)


class TestRunLineageAndOcc:
    def test_distribution_rerun_supersedes_prior_run(self):
        """PRD §3.5: "Each payment's runs carry a 1-based `run_number` that
        increments with every superseding run, and creating a new run supersedes
        the previous one: the prior run in `COMPUTED` moves to `SUPERSEDED`, its
        `superseded_by_run_id` points at the new run, and its still-`PENDING`
        lines collapse to `VOID`."

        Design: Corner/endpoints/distribution_rerun_supersedes_prior_run
        """
        setup = setup_funded_facility(
            [("RP", 5_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 5_000_000},
        )
        facility = setup["facility"]
        pay = create_payment(facility["id"], setup["borrower"]["id"], 50_000, "2026-08-31")
        run1 = create_run(pay["id"])
        run1_lines = lines_for_run(run1["id"])
        assert run1["run_number"] == 1
        assert run1["status"] == "COMPUTED"

        run2 = create_run(pay["id"])  # fixture threads the current payment version
        assert run2["run_number"] == 2
        assert run2["status"] == "COMPUTED"

        old = get_success_data(api_client.get_distribution_run(run1["id"], AGENT))
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_by_run_id"] == run2["id"]
        for line in run1_lines:
            refreshed = get_success_data(api_client.get_distribution_line(line["id"], AGENT))
            assert refreshed["status"] == "VOID"

        resp = api_client.remit_distribution_run(run1["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    def test_occ_distribution_rerun_stale_payment_version_rejected(self):
        """PRD §2.8: "Computing a distribution run for a payment requires
        `expected_payment_version`, carrying the client's last observed `version`
        of the target BorrowerPayment. A run creation legitimately supersedes the
        prior computed run, and a stale payment version means the client has not
        observed the current run lineage; the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_distribution_rerun_stale_payment_version_rejected
        """
        setup = setup_funded_facility(
            [("OP", 5_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 5_000_000},
        )
        pay = create_payment(setup["facility"]["id"], setup["borrower"]["id"],
                             50_000, "2026-08-31")
        stale_version = pay["version"]
        create_run(pay["id"])  # bumps the payment version

        resp = api_client.create_distribution_run(
            pay["id"], {"expected_payment_version": stale_version}, AGENT
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestWaterfallEdgeScenarios:
    def test_waterfall_agent_retains_pools_without_funded_participants(self):
        """PRD §3.5: "Whatever portion of the two pools is not attributable to
        any funded participant — interest or principal owed to positions the
        agent holds on its own book after exits — is retained by the agent as
        `agent_retained_cents`, computed as the two pools minus the sum of line
        totals."

        Design: Corner/calculations/waterfall_agent_retains_pools_without_funded_participants
        """
        setup = setup_funded_facility(
            [("SoloP", 1_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 1_000_000},
        )
        facility = setup["facility"]
        participant = setup["participants"][0]

        set_clock("2026-08-31T00:00:00Z")
        demand = demand_buyback(facility["id"], participant["id"], "MISREPRESENTATION")
        settle_buyback(demand["id"])
        assert get_participant(participant["id"])["status"] == "EXITED"

        pay = create_payment(facility["id"], setup["borrower"]["id"], 50_000, "2026-08-31")
        run = create_run(pay["id"])
        # fee floor(1,000,000 * 25 * 30 / 3.6M) == 208; accrued 10,000; the rest
        # is principal; with no FUNDED participant the agent retains both pools.
        assert run["servicing_fee_cents"] == 208
        assert run["interest_pool_cents"] == 10_000
        assert run["principal_pool_cents"] == 39_792
        assert run["agent_retained_cents"] == 49_792
        assert_waterfall_conservation(run, 50_000)

        lines_resp = api_client.list_distribution_lines(
            AGENT, params={"run_id": run["id"]}
        )
        lines, _meta = validate_paginated(lines_resp)
        assert lines == []

    def test_immediate_consistency_remit_readback(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.5: "Hop 1: the run's `PENDING` lines become `REMITTED` and the run
        itself moves `COMPUTED` → `REMITTED`, stamping `remitted_at`."

        Design: Corner/consistency_model/immediate_consistency_remit_readback
        """
        setup = setup_funded_facility(
            [("IP", 5_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 5_000_000},
        )
        pay = create_payment(setup["facility"]["id"], setup["borrower"]["id"],
                             50_000, "2026-08-31")
        run = create_run(pay["id"])

        remitted = validate_success(api_client.remit_distribution_run(run["id"], AGENT))
        assert remitted["status"] == "REMITTED"
        assert remitted["remitted_at"] is not None

        fetched = validate_success(api_client.get_distribution_run(run["id"], AGENT))
        assert fetched["status"] == "REMITTED"
        assert fetched["remitted_at"] == remitted["remitted_at"]
        assert fetched["servicing_fee_cents"] == 208
        assert fetched["interest_pool_cents"] == 10_000
        assert fetched["principal_pool_cents"] == 39_792
