"""Compensating actions that must restore a conserved quantity exactly."""

from test_helpers import (
    assert_balance_equals_ledger,
    assert_ledger_sum,
    entries_of_type,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestDisputeRestoresTheLedger:
    """Dispute is the compensating action for submit."""

    def test_the_summed_ledger_returns_to_its_pre_submission_value(self, api):
        """PRD §3.8: "The design guarantee here is that the summed ledger returns to
        its exact pre-submission value with zero drift."
        PRD §3.8: "When `credit_applied_cents` is greater than 0, a `REVERSAL` ledger
        entry is posted whose `amount_cents` is the positive value of
        `credit_applied_cents` — returning to the ledger exactly what the submission
        took from it — after which the invoice's `credit_applied_cents` is set to 0
        and its `total_cents` is set equal to `net_before_credit_cents`."

        Design: Difficulty/compensating_invariant/invoice_dispute_restores_credit_ledger_sum
        """
        program = fixtures.setup_submitted_invoice(line_count=2, credit_grade="B")
        fleet_id = program["fleet"]["id"]
        assert program["invoice"]["credit_applied_cents"] == 6334

        before = fixtures.list_ledger(fleet_id)
        assert [e["amount_cents"] for e in entries_of_type(before, "ACCRUAL")] == [10500]
        applications = entries_of_type(before, "APPLICATION")
        assert len(applications) == 1
        assert applications[0]["amount_cents"] == -6334
        assert applications[0].get("casing_id") is None
        assert applications[0]["source_entity_type"] == "CROSS_LOCATION_INVOICE"
        assert_ledger_sum(before, 4166)

        fixtures.dispute_invoice(program["invoice"]["id"])

        after = fixtures.list_ledger(fleet_id)
        reversals = entries_of_type(after, "REVERSAL")
        assert len(reversals) == 1
        assert reversals[0]["amount_cents"] == 6334
        assert reversals[0]["source_entity_type"] == "CROSS_LOCATION_INVOICE"
        assert reversals[0]["source_entity_id"] == program["invoice"]["id"]
        assert_ledger_sum(after, 10500)

        surviving = entries_of_type(after, "APPLICATION")
        assert len(surviving) == 1, "corrections are further entries, never mutations"
        assert surviving[0]["amount_cents"] == -6334
        assert surviving[0]["id"] == applications[0]["id"]

        fleet = fixtures.read_fleet(fleet_id)
        assert fleet["casing_credit_balance_cents"] == 10500
        assert_balance_equals_ledger(fleet, after)

    def test_dispute_zeroes_the_credit_and_releases_every_claimed_line(self, api):
        """PRD §3.8: "Every claimed call cascades `BILLED_TO_NATIONAL → UNBILLED` and
        has its `cross_location_invoice_id` cleared, releasing it to be picked up by a
        later invoice; the calls' `dispatch_status` remains `COMPLETED` throughout,
        since disputing a bill does not un-repair a truck."
        PRD §3.8: "A `dispute_reason` is supplied and the invoice advances `SUBMITTED
        → DISPUTED`."

        Design: Difficulty/compensating_invariant/invoice_dispute_restores_credit_ledger_sum
        """
        program = fixtures.setup_submitted_invoice(line_count=2, credit_grade="B")
        submitted = program["invoice"]
        assert submitted["subtotal_cents"] == 28960
        assert submitted["discount_cents"] == 3621
        assert submitted["net_before_credit_cents"] == 25339
        assert submitted["total_cents"] == 19005

        disputed = fixtures.dispute_invoice(submitted["id"])

        assert disputed["status"] == "DISPUTED"
        assert disputed["credit_applied_cents"] == 0
        assert disputed["total_cents"] == 25339, "the total falls back to the net"
        assert disputed["subtotal_cents"] == 28960, "the lines have not changed"
        assert disputed["discount_cents"] == 3621
        assert disputed["net_before_credit_cents"] == 25339
        # PRD §2.10: "An invoice's `line_count` is the number of calls whose
        # `cross_location_invoice_id` is that invoice." The dispute clears that
        # reference on every claimed call, so the recomputed count falls to 0.
        assert disputed["line_count"] == 0

        for call in program["calls"]:
            released = fixtures.read_call(call["id"])
            assert released["billing_status"] == "UNBILLED"
            assert released.get("cross_location_invoice_id") is None
            assert released["dispatch_status"] == "COMPLETED"


class TestCancelRestoresBookedMinutes:
    """The schedule is a conserved quantity."""

    def test_cancelling_a_booking_gives_the_minutes_back_exactly(self, api):
        """PRD §3.5: "From `SCHEDULED`, cancellation cascades the casing
        `RETREAD_QUEUED → INSPECTED` — the grade and the accrued credit are untouched,
        so the carcass simply returns to the queue of retreadable candidates — and
        releases the job's slot from the line's `booked_minutes`, restoring that figure
        to exactly its pre-booking value with zero drift."
        PRD §3.4: "The base rate is the negotiated `casing_credit_rate_cents` of the
        fleet's `ACTIVE` national agreement whose closed window covers the logical
        clock's date; when no such agreement exists, the base rate is the dealer default
        of 12000 cents — one hundred and twenty dollars per casing."

        Design: Difficulty/compensating_invariant/retread_cancel_restores_line_booked_minutes
        """
        program = fixtures.setup_scheduled_job(grade="A")
        line_id = program["line"]["id"]
        assert fixtures.read_line(line_id)["booked_minutes"] == 270
        assert program["agreement"] is None, "no agreement, so the dealer default rate"
        assert (
            fixtures.read_casing(program["casing"]["id"])["provisional_credit_cents"]
            == 12000
        )

        cancelled = validate_success(
            api.cancel_retread_job(
                program["job"]["id"], factories.cancel_job_payload(), fixtures.SCHEDULER
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert fixtures.read_line(line_id)["booked_minutes"] == 0, (
            "restored to exactly its pre-booking value"
        )

        casing = fixtures.read_casing(program["casing"]["id"])
        assert casing["status"] == "INSPECTED"
        assert casing["inspection_grade"] == "A"
        assert casing["provisional_credit_cents"] == 12000

        entries = fixtures.list_ledger(program["fleet"]["id"])
        assert len(entries_of_type(entries, "ACCRUAL")) == 1
        assert entries_of_type(entries, "REVERSAL") == []
        assert entries_of_type(entries, "ADJUSTMENT") == []
        assert_ledger_sum(entries, 12000)

    def test_the_released_slot_is_immediately_re_bookable(self, api):
        """PRD §3.5: "Plant capacity is scarce and a cured casing cannot be rushed, so
        the schedule is treated as a conserved quantity: whatever a `PlantScheduler`
        books must be given back exactly when the booking is released, with no drift."
        PRD §3.5: "Cancellation ends a job in `CANCELLED`, which together with
        `COMPLETED` is terminal."

        Design: Difficulty/compensating_invariant/retread_cancel_restores_line_booked_minutes
        """
        program = fixtures.setup_scheduled_job(grade="A")
        line_id = program["line"]["id"]
        first_job_id = program["job"]["id"]

        validate_success(
            api.cancel_retread_job(
                first_job_id, factories.cancel_job_payload(), fixtures.SCHEDULER
            )
        )

        rebooked = validate_success(
            api.create_retread_job(
                factories.retread_job_payload(
                    program["casing"]["id"],
                    line_id,
                    "2026-08-20T08:00:00Z",
                    "2026-08-20T12:00:00Z",
                ),
                fixtures.SCHEDULER,
            ),
            expected_status=201,
        )

        assert rebooked["id"] != first_job_id
        assert rebooked["status"] == "SCHEDULED"
        assert rebooked["reschedule_count"] == 0
        assert fixtures.read_line(line_id)["booked_minutes"] == 270

        stale = fixtures.read_job(first_job_id)
        assert stale["status"] == "CANCELLED", (
            "the cancelled row survives; it is simply out of the occupying set"
        )
        assert fixtures.count_jobs_for_casing(program["casing"]["id"]) == 2


class TestVoidRestoresTheManifest:
    """Voiding unlinks a load without resurrecting anything."""

    def test_voiding_a_signed_manifest_clears_totals_and_the_signature(self, api):
        """PRD §3.7: "Voiding a `DRAFT` or `SIGNED` manifest records the supplied
        `void_reason`, advances the manifest to `VOIDED`, and clears the
        `scrap_manifest_id` of every casing that was listed — with the casings' own
        statuses left completely unchanged, so a condemned carcass returns to the pool
        of scrap-eligible carcasses rather than being resurrected."
        PRD §3.7: "When the manifest being voided was already `SIGNED`, the void
        additionally clears `signed_by_user_id` and `signed_at`, because the signature
        no longer attests to anything."

        Design: Difficulty/compensating_invariant/manifest_void_restores_manifest_totals_and_casing_linkage
        """
        program = fixtures.setup_manifest_with_condemned_casings(
            casing_specs=[125, 130]
        )
        manifest_id = program["manifest"]["id"]
        signed = fixtures.sign_manifest(manifest_id)
        assert signed["tire_count"] == 2
        assert signed["total_weight_lbs"] == 255
        assert signed["signed_by_user_id"] == "officer-signer"

        voided = fixtures.void_manifest(manifest_id)

        assert voided["status"] == "VOIDED"
        assert voided["tire_count"] == 0
        assert voided["total_weight_lbs"] == 0
        assert voided.get("signed_by_user_id") is None
        assert voided.get("signed_at") is None
        assert voided["void_reason"] == "Load rebuilt"

        for casing in program["casings"]:
            released = fixtures.read_casing(casing["id"])
            assert released.get("scrap_manifest_id") is None
            assert released["status"] == "REJECTED", "unlinked, not resurrected"
            assert released["provisional_credit_cents"] == 8400

        assert (
            fixtures.read_location(program["location"]["id"])[
                "casings_in_holding_count"
            ]
            == 2
        ), "a REJECTED carcass is still in the holding set"

    def test_the_unlinked_casings_can_be_put_on_a_fresh_load(self, api):
        """PRD §3.7: "Both `tire_count` and `total_weight_lbs` fall to 0 as a
        consequence of the unlinking."
        PRD §3.7: "The casing's `scrap_manifest_id` must be empty, since a carcass
        cannot be on two loads at once; a repeat is rejected with
        `ERR_CASING_ALREADY_ON_MANIFEST`."

        Design: Difficulty/compensating_invariant/manifest_void_restores_manifest_totals_and_casing_linkage
        """
        program = fixtures.setup_manifest_with_condemned_casings(
            casing_specs=[125, 130]
        )
        first_manifest_id = program["manifest"]["id"]
        fixtures.sign_manifest(first_manifest_id)

        # While the load stands, the carcasses are spoken for.
        rival = fixtures.create_manifest(program["location"]["id"])
        validate_error(
            api.add_scrap_manifest_line(
                rival["id"],
                factories.manifest_line_payload(program["casings"][0]["id"]),
                fixtures.OFFICER,
            ),
            "ERR_CASING_ALREADY_ON_MANIFEST",
            expected_status=409,
        )

        fixtures.void_manifest(first_manifest_id)

        totals = None
        for casing in program["casings"]:
            totals = fixtures.add_manifest_line(rival["id"], casing["id"])
        assert totals["tire_count"] == 2
        assert totals["total_weight_lbs"] == 255
        assert totals["status"] == "DRAFT"

        for casing in program["casings"]:
            assert fixtures.read_casing(casing["id"])["scrap_manifest_id"] == rival["id"]
        assert fixtures.read_manifest(first_manifest_id)["tire_count"] == 0
