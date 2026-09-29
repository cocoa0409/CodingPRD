"""Corner behaviour of the segregation-of-duties role model and of the consistency model: segregation binds
exactly three workflow steps and compares only the latest round, while every derived figure, cascade and
posture recompute is finished by the time the triggering response is returned."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    build_user_headers, make_billing_headers,
    fixtures as fx, factories as F,
)

BIG_CREDIT = 100_000_000_000
# a PIPELINE parcel: the gauge delta governs, so the parcel's net volume is 29,700.00 liters
PIPELINE_PARCEL = dict(delivery_mode="PIPELINE", supplier_name="Refinery One",
                       meter_ticket_gross_liters=29800.0, tank_opening_gauge_liters=0.0,
                       tank_closing_gauge_liters=29700.0, temperature_c=15.0,
                       certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)


class TestSegregationIsScopedToThreeSteps:
    def test_one_person_may_measure_then_post_a_run_and_bill_then_collect_an_invoice(self, api):
        """PRD §2.1: "**Segregation of duties.** Three workflow steps compare the acting `X-User-ID` against
        the identifier recorded at the preceding step of the same workflow, and reject a match with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): an inspector may not sign a receipt verdict when the acting
        identifier equals the receipt's `sampled_by_user_id`; an inspector may not release a tank on the
        quality dimension when the acting identifier equals the `drawn_by_user_id` of the governing periodic
        tank sample; and a billing clerk may not resolve a dispute on an invoice whose `issued_by_user_id`
        equals the acting identifier."
        PRD §3.9: "Posting a run is a `ConsortiumAdmin` action and requires that no storage tank at the farm
        has `quality_status` `QUARANTINED`."
        PRD §3.9: "Payments are recorded against an issued invoice with an `amount_cents` that must be
        strictly positive and must not push the cumulative `amount_paid_cents` above the invoice's
        `total_cents`; a violation of either bound is `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Measure-then-post and issue-then-pay are two-step flows that are *not* on the list of three, so one
        identifier may walk both halves. A blanket same-user prohibition would reject all of this.

        Design: Corner/complexity_layers/the_sample_release_pair_is_the_only_segregated_pair
        """
        env = fx.setup_completed_order(
            meter_end_liters=20_000.0,
            account_overrides={"credit_limit_cents": BIG_CREDIT})
        farm_id, tank_id = env["farm"]["id"], env["tank"]["id"]

        # one human being, two hats: the same X-User-ID measures as FarmOperator and posts as ConsortiumAdmin
        dual_operator = build_user_headers("u-dual-hat", "FarmOperator")
        dual_admin = build_user_headers("u-dual-hat", "ConsortiumAdmin")

        run = validate_success(api.create_reconciliation_run(
            farm_id,
            F.create_reconciliation_run_payload(period_start_utc="2026-08-10T00:00:00Z",
                                                period_end_utc="2026-08-11T00:00:00Z"),
            dual_operator), 201)
        fx.set_clock("2026-08-11T01:00:00Z")
        book_now = fx.read_tank(tank_id)["book_volume_liters"]
        measured = validate_success(api.measure_reconciliation_run(
            run["id"],
            {"tank_measurements": [{"storage_tank_id": tank_id,
                                    "measured_volume_liters": book_now,
                                    "temperature_c": 15.0}]},
            dual_operator), 200)
        assert measured["variance_liters"] == 0.00, \
            "a tank measured exactly at book has no variance"
        assert measured["status"] == "MEASURED", \
            "a clean run does not hold, so posting needs no override reason"

        posted = validate_success(api.post_reconciliation_run(run["id"], dual_admin), 200)
        assert posted["status"] == "POSTED", \
            "the same identifier that measured the stock may post the adjustment"
        assert posted["posted_by_user_id"] == "u-dual-hat", \
            "the poster is stamped even though it matches the measurer"

        # and one clerk both issues the invoice and collects the money for it
        solo_clerk = make_billing_headers("bc-solo")
        invoice = fx.create_draft_invoice(env["account"]["id"], clerk=solo_clerk)
        issued = validate_success(api.issue_invoice(invoice["id"], solo_clerk), 200)
        assert issued["issued_by_user_id"] == "bc-solo"

        # the one billing step that *is* segregated refuses the very same clerk
        validate_success(api.dispute_invoice(
            invoice["id"], fx.make_airline_rep_headers(env["account"]["id"])), 200)
        validate_error(api.resolve_invoice_dispute(invoice["id"], solo_clerk),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        reopened = validate_success(
            api.resolve_invoice_dispute(invoice["id"], make_billing_headers("bc-other")), 200)
        assert reopened["status"] == "ISSUED"

        paid = validate_success(api.create_payment(
            invoice["id"], {"amount_cents": issued["total_cents"]}, solo_clerk), 201)
        assert paid["amount_cents"] == issued["total_cents"]
        assert fx.read_invoice(invoice["id"])["status"] == "PAID", \
            "collecting on an invoice one issued oneself is not a segregated step"

    def test_a_retest_round_moves_the_identifier_the_signer_is_compared_against(self, api):
        """PRD §3.3: "Both branches are `QualityInspector` actions and both refuse a signer whose identifier
        equals the receipt's `sampled_by_user_id` — the inspector who drew the sample may not sign its
        verdict, and an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.3: "A re-sample raises `retest_round` by one, creates a fresh `RECEIPT_QC` sample in `DRAWN`,
        re-stamps `sampled_by_user_id`, and raises the receipt's `version` by one."
        PRD §3.3: "The revision cycle is therefore `QUARANTINED → SAMPLED → UNDER_TEST → RELEASED` or back
        to `QUARANTINED`."

        Inspector A draws the first round, B quarantines it, A draws the re-test round: because the re-sample
        re-stamps `sampled_by_user_id`, B is still eligible to sign and A is still barred.

        Design: Corner/complexity_layers/segregation_survives_a_retest_round
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0)
        tank_id = env["tank"]["id"]

        receipt, _first_sample = fx.make_tested_receipt(tank_id, drawer=fx.INSPECTOR_A,
                                                       **PIPELINE_PARCEL)
        assert receipt["sampled_by_user_id"] == "qi-alice"
        quarantined = fx.sign_verdict(receipt["id"], "QUARANTINE", fx.INSPECTOR_B)
        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["retest_round"] == 0

        # round two: A samples again, so A remains the sampler of record
        retest = validate_success(api.create_receipt_sample(receipt["id"], fx.INSPECTOR_A), 201)
        assert retest["status"] == "DRAWN"
        after_resample = fx.read_receipt(receipt["id"])
        assert after_resample["status"] == "SAMPLED"
        assert after_resample["retest_round"] == 1
        assert after_resample["sampled_by_user_id"] == "qi-alice", \
            "the re-sample re-stamps the sampler, which is who the signer is compared against"

        fx.post_results(retest["id"], fx.INSPECTOR_A,
                        observed_density_kg_per_m3=PIPELINE_PARCEL["certificate_density_kg_per_m3"])
        validate_error(api.sign_receipt_verdict(receipt["id"], {"decision": "RELEASE"},
                                               fx.INSPECTOR_A),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        released = validate_success(api.sign_receipt_verdict(
            receipt["id"], {"decision": "RELEASE"}, fx.INSPECTOR_B), 200)
        assert released["status"] == "RELEASED", \
            "B never drew a sample in either round, so B may sign the second-round verdict"
        assert released["released_by_user_id"] == "qi-bob"
        assert fx.read_tank(tank_id)["book_volume_liters"] == 29700.00, \
            "the second-round release is what finally moves the parcel into the ledger"


class TestEverythingSettlesInsideTheRequest:
    def test_no_write_is_answered_with_a_promise_to_finish_later(self, api):
        """PRD §4: "Endpoints that create a new resource respond with HTTP 201 and return the created
        resource in the `data` field; endpoints that modify an existing resource, drive a state transition, or
        read a resource respond with HTTP 200."
        PRD §2.11: "Cascades run to completion within the request that triggered them; there is no deferred or
        eventual settlement."
        PRD §2.7: "Posture is never set by a client; it is recomputed by the server on every mutation of a
        child storage tank, fuelling asset, spill incident or environmental permit, on every fuel receipt
        release, and on every advance of the logical clock."

        Every status code in this system is a settled answer: 201 for a create, 200 for everything else. The
        deepest cascade available — a reportable spill escalation freezing the farm — is fully observable on
        the reads that follow it immediately.

        Design: Corner/consistency_model/no_endpoint_returns_a_pending_or_accepted_status
        """
        env = fx.setup_truck_order(target_state="FUELING")
        order_id, farm_id = env["order"]["id"], env["farm"]["id"]
        observed = []

        version = fx.current_order_version(order_id)
        ticket_response = api.create_uplift_record(
            order_id, F.create_uplift_record_payload(version, meter_end_liters=20_000.0), fx.AGENT)
        observed.append(ticket_response)
        validate_success(ticket_response, 201)

        completion = api.complete_order(order_id, fx.AGENT)
        observed.append(completion)
        completed = validate_success(completion, 200)
        assert completed["status"] == "COMPLETED"
        assert completed["posted_net_liters"] == 20000.00, \
            "the derived total is already on the transition response, not filled in afterwards"

        spill_response = api.create_spill_incident(
            F.create_spill_incident_payload(farm_id, spilled_volume_liters=25.0), fx.ENVIRO)
        observed.append(spill_response)
        spill = validate_success(spill_response, 201)

        escalation = api.escalate_spill(spill["id"], {"regulator_reference": "REG-2026-0009"},
                                       fx.ENVIRO)
        observed.append(escalation)
        escalated = validate_success(escalation, 200)
        assert escalated["status"] == "ESCALATED"

        for response in observed:
            assert response.status_code in (200, 201), \
                f"unexpected status {response.status_code}: nothing here is asynchronous"
            assert response.status_code != 202, \
                "no endpoint accepts work for later processing"

        # the three-hop freeze cascade is already settled on the very next read
        assert fx.read_farm(farm_id)["posture"] == "FROZEN"
        assert fx.read_asset(env["truck"]["id"])["status"] == "DOWN_MAINTENANCE"

    def test_a_sibling_tank_does_not_drift_when_another_tank_is_corrected(self, api):
        """PRD §3.9: "Posting writes the signed per-tank variance into the ledger as that tank's
        `adjustment_liters`, with the effect that each measured tank's `book_volume_liters` afterwards equals
        its corrected measured volume exactly."
        PRD §3.4: "The tank ledger is never maintained incrementally."
        PRD §3.4: "The `available_volume_liters` is the book volume less the reserved volume less the farm's
        `unpumpable_bottom_liters`, rounded half up to two decimals and then floored at 0.0 so it can never go
        negative."
        PRD §2.4: "Reading a tank recomputes its book, reserved and available volumes."

        Two tanks are measured in one run. The first matches its book exactly and must come out of the post
        untouched; the second is fifty liters short and is corrected. Recomputation is a full re-derivation
        per entity, so one tank's correction cannot bleed into its sibling.

        Design: Corner/consistency_model/derived_values_are_recomputed_not_cached
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        farm_id = env["farm"]["id"]
        steady = env["tank"]
        drifting = fx.make_released_tank(farm_id, capacity_liters=5_000_000.0,
                                         safe_fill_liters=4_000_000.0,
                                         density_kg_per_m3=795.0,
                                         opening_volume_liters=500_000.0)

        assert fx.read_tank(steady["id"])["book_volume_liters"] == 1000000.00
        assert fx.read_tank(steady["id"])["available_volume_liters"] == 999500.00

        run = fx.open_reconciliation_run(farm_id, period_start_utc="2026-08-10T00:00:00Z",
                                         period_end_utc="2026-08-11T00:00:00Z")
        fx.set_clock("2026-08-11T01:00:00Z")
        measured = fx.measure_reconciliation_run(run["id"], [
            {"storage_tank_id": steady["id"], "measured_volume_liters": 1_000_000.0,
             "temperature_c": 15.0},
            {"storage_tank_id": drifting["id"], "measured_volume_liters": 499_950.0,
             "temperature_c": 15.0},
        ])
        assert measured["variance_liters"] == -50.00, \
            "only the second tank contributes a variance"
        # a dead-quiet period divides by a denominator of 1.0, so this run holds on the governing basis
        assert measured["status"] == "VARIANCE_HOLD"
        validate_success(api.post_reconciliation_run(
            run["id"], fx.ADMIN, {"variance_override_reason": "dip sheets reconciled by hand"}), 200)

        settled_steady = fx.read_tank(steady["id"])
        assert settled_steady["book_volume_liters"] == 1000000.00, \
            "a zero variance writes a zero adjustment, so the sibling's book is untouched"
        assert settled_steady["available_volume_liters"] == 999500.00
        settled_drifting = fx.read_tank(drifting["id"])
        assert settled_drifting["book_volume_liters"] == 499950.00, \
            "the corrected tank equals its corrected measured volume exactly"
        assert settled_drifting["available_volume_liters"] == 499450.00

    def test_two_rows_written_without_moving_the_clock_share_one_timestamp(self, api):
        """PRD §2.5: "Every timestamp the server writes — a receipt's `released_at_utc`, a gauge's
        `last_gauge_at_utc`, a filter change's `changed_at_utc`, a spill's `reported_at_utc`, the `created_at`
        and `updated_at` of every row — is taken from that clock."
        PRD §2.5: "Time in this system is not wall-clock time."
        PRD §3.9: "The variance computation processes the measured tanks in `created_at` ascending order."

        Ties in `created_at` are therefore normal and expected, which is exactly why every ordering rule in
        the design names an explicit secondary key rather than trusting timestamp resolution.

        Design: Corner/consistency_model/the_logical_clock_is_the_only_source_of_time_ordering
        """
        env = fx.setup_fuel_farm(clock="2026-08-10T06:00:00Z")
        farm_id = env["farm"]["id"]

        first = fx.register_tank(farm_id)
        second = fx.register_tank(farm_id)
        assert first["created_at"] == second["created_at"], \
            "no clock advance happened between the two writes, so the two rows are simultaneous"
        assert first["created_at"].startswith("2026-08-10T06:00:00"), \
            "the timestamp comes from the logical clock and not from the wall clock"
        assert first["created_at"] == env["farm"]["created_at"], \
            "the parent farm was written at the same logical instant"

        fx.set_clock("2026-08-10T07:00:00Z")
        third = fx.register_tank(farm_id)
        assert third["created_at"].startswith("2026-08-10T07:00:00"), \
            "only a clock advance moves the timestamp"
        assert third["created_at"] > first["created_at"]

        # re-reading does not re-stamp a row that nothing wrote to
        assert fx.read_tank(first["id"])["created_at"] == first["created_at"]
