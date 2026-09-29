"""Spill reporting, the quarantine cascade and getting a barge back to work.

One POST against a delivery order can reach five records: the incident itself, the
order it happened on, the barge, the barge's other booked order and that order's
stem. Lifting the quarantine afterwards is a two-entity precondition chain running
the other way.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    COMPLIANCE,
    EARLY_QUOTE,
    OPS,
    add_confirmed_nomination,
    api_client,
    assert_nomination_state,
    assert_spill_incident,
    build_closed_spill,
    build_open_spill,
    build_pumping_order,
    build_quarantined_asset,
    build_scheduled_order,
    clear_order,
    close_spill,
    confirm_containment,
    confirm_containment_payload,
    create_delivery_order_payload,
    read_asset,
    read_nomination,
    read_order,
    read_spill,
    report_spill,
    return_asset_to_service,
    schedule_order,
    set_logical_clock,
    validate_error,
    validate_success,
)

SECOND_SLOT_START = "2026-08-10T13:31:00Z"
SECOND_SLOT_END = "2026-08-10T17:00:00Z"

MINOR_SPILL = {"volume_liters": 50.00, "boom_deployed": True}
MINOR_CASE_REF = "PRT-RTM-CASE-12"

AGED_SPILL = {"volume_liters": 150.00, "boom_deployed": True}
THIRTY_TWO_DAYS_LATER = "2026-09-11T06:45:00Z"

MID_TRANSFER_SPILL = {"volume_liters": 140.00, "boom_deployed": True}

NOMINATION_C_WINDOW_START = "2026-08-12T06:00:00Z"
NOMINATION_C_WINDOW_END = "2026-08-13T06:00:00Z"
NOMINATION_C_SLOT_END = "2026-08-12T09:00:00Z"


def _two_orders_on_one_barge():
    """Barge Alpha holding a cleared 1200.000 mt slot and a later booked one.

    Stem A is scheduled 06:00 to 12:00 and cleared; stem B for 800.000 mt is
    scheduled 13:31 to 17:00, a 91-minute gap that clears the barge's 90-minute
    turnaround buffer, and is left untouched at `SCHEDULED`.
    """
    ctx = build_scheduled_order(quotes=[EARLY_QUOTE])
    nomination_b = add_confirmed_nomination(
        ctx,
        store_as="nomination_b",
        nominated_quantity_mt=800.000,
        vessel_imo="9654321",
        vessel_name="MV Boreas",
        eca_documentation_ref="CHG-2026-0002",
    )
    schedule_order(
        ctx,
        nomination_id=nomination_b["id"],
        store_as="order_b",
        planned_quantity_mt=800.000,
        slot_start=SECOND_SLOT_START,
        slot_end=SECOND_SLOT_END,
    )
    clear_order(ctx)
    return ctx


def _quarantined_barge_with_a_waiting_stem():
    """A quarantined barge, an open incident and a confirmed stem needing a slot."""
    ctx = build_quarantined_asset(quotes=[EARLY_QUOTE])
    add_confirmed_nomination(
        ctx,
        store_as="nomination_c",
        nominated_quantity_mt=500.000,
        vessel_imo="9654321",
        vessel_name="MV Boreas",
        window_start=NOMINATION_C_WINDOW_START,
        window_end=NOMINATION_C_WINDOW_END,
        eca_documentation_ref="CHG-2026-0003",
    )
    return ctx


def _order_c_payload(ctx):
    nomination_c = ctx["nomination_c"]
    return create_delivery_order_payload(
        nomination_c["id"],
        ctx["asset"]["id"],
        nomination_c["version"],
        planned_quantity_mt=500.000,
        slot_start=NOMINATION_C_WINDOW_START,
        slot_end=NOMINATION_C_SLOT_END,
    )


class TestSpillCascade:
    """A major incident propagates four levels from the report."""

    def test_severity_and_attribution_are_derived_from_the_report(self):
        """PRD §3.6: "The system copies `asset_id` from the delivery order and
        `port_id` from the nomination behind it, so the incident is attributable
        without the reporter having to restate either."
        PRD §3.6: "it is `MAJOR` when the spilled volume is at least 100.00 litres
        **or** the boom was not deployed, and `MINOR` otherwise. That `severity`
        fixes `penalty_points`: 45.00 points for a major incident, 15.00 for a minor
        one."
        PRD §3.6: "The incident opens in status `OPEN` with `containment_confirmed`
        false, `response_ref` null and `closed_at` null."

        Design: Difficulty/transitive_cascade/spill_quarantine_cascade_depth_four
        """
        ctx = _two_orders_on_one_barge()

        incident = report_spill(ctx)

        assert_spill_incident(incident)
        assert incident["severity"] == "MAJOR", (
            "250.00 litres with no boom in the water is a major incident, got "
            f"{incident['severity']}"
        )
        assert incident["penalty_points"] == pytest.approx(45.00, abs=0.01), (
            f"A major incident carries 45.00 penalty points, got "
            f"{incident['penalty_points']}"
        )
        assert incident["asset_id"] == ctx["asset"]["id"], (
            "asset_id must be copied from the delivery order, got "
            f"{incident['asset_id']}"
        )
        assert incident["port_id"] == ctx["port"]["id"], (
            "port_id must be copied from the nomination behind the order, got "
            f"{incident['port_id']}"
        )
        assert incident["status"] == "OPEN", (
            f"A fresh incident opens OPEN, got {incident['status']}"
        )
        assert incident["containment_confirmed"] is False, (
            "Nothing but the confirm step sets the containment flag"
        )
        assert incident["response_ref"] is None, (
            f"response_ref opens null, got {incident['response_ref']}"
        )
        assert incident["closed_at"] is None, (
            f"closed_at opens null, got {incident['closed_at']}"
        )

    def test_cascade_reaches_the_other_stem_but_spares_the_reporting_one(self):
        """PRD §3.6: "Reporting an incident always suspends the delivery it happened
        on: an order in `SCHEDULED`, `CLEARED` or `PUMPING` moves to `SUSPENDED`, and
        the asset's `compliance_score` is recomputed to absorb the new penalty
        points."
        PRD §3.6: "When and only when the derived severity is `MAJOR`, a deeper
        cascade fires: the asset moves `AVAILABLE → QUARANTINED`; every **other**
        delivery order on that asset whose `logistics_status` is `SCHEDULED` or
        `CLEARED` moves to `CANCELLED`; and each of those cancelled orders pushes its
        own nomination `SCHEDULED → AWAITING_SCHEDULE`."

        Design: Difficulty/transitive_cascade/spill_quarantine_cascade_depth_four
        """
        ctx = _two_orders_on_one_barge()

        report_spill(ctx)

        reporting_order = read_order(ctx)
        assert reporting_order["logistics_status"] == "SUSPENDED", (
            "The order the spill happened on must be suspended, got "
            f"{reporting_order['logistics_status']}"
        )
        asset = read_asset(ctx)
        assert asset["status"] == "QUARANTINED", (
            f"A major incident quarantines the barge, got {asset['status']}"
        )
        other_order = read_order(order_id=ctx["order_b"]["id"])
        assert other_order["logistics_status"] == "CANCELLED", (
            "The barge's other booked slot must be cancelled, got "
            f"{other_order['logistics_status']}"
        )
        nomination_b = read_nomination(nomination_id=ctx["nomination_b"]["id"])
        assert nomination_b["fulfillment_status"] == "AWAITING_SCHEDULE", (
            "The cancelled order's stem falls back for re-slotting, got "
            f"{nomination_b['fulfillment_status']}"
        )
        nomination_a = read_nomination(ctx)
        assert_nomination_state(nomination_a, "APPROVED", "SCHEDULED")

    def test_committed_tonnage_and_compliance_score_are_re_derived(self):
        """PRD §3.1: "`committed_quantity_mt` is the sum of `planned_quantity_mt`
        across the asset's delivery orders whose `logistics_status` is `SCHEDULED`,
        `CLEARED` or `PUMPING`, held to three decimals and initialised to 0.000; it
        is recomputed whenever an order enters or leaves that set."
        PRD §3.6: "An incident aged 30 days or fewer contributes its full
        `penalty_points`, weighted by 1.00."
        PRD §3.6: "The score is then 100.00 minus the accumulated penalty plus the
        bonus, rounded to two decimal places, and finally clamped into the inclusive
        range from 0.00 to 100.00."

        Design: Difficulty/transitive_cascade/spill_quarantine_cascade_depth_four
        """
        ctx = _two_orders_on_one_barge()
        before = read_asset(ctx)
        assert before["committed_quantity_mt"] == pytest.approx(2000.000, abs=0.0005), (
            "1200.000 cleared plus 800.000 scheduled is 2000.000 mt committed, got "
            f"{before['committed_quantity_mt']}"
        )
        assert before["compliance_score"] == pytest.approx(100.00, abs=0.01), (
            f"A clean barge starts at 100.00, got {before['compliance_score']}"
        )

        report_spill(ctx)

        after = read_asset(ctx)
        assert after["committed_quantity_mt"] == pytest.approx(0.000, abs=0.0005), (
            "SUSPENDED and CANCELLED both sit outside the committed set, got "
            f"{after['committed_quantity_mt']}"
        )
        assert after["compliance_score"] == pytest.approx(55.00, abs=0.01), (
            "100.00 less the 45.00 penalty at full weight, with no clean-delivery "
            f"bonus, is 55.00, got {after['compliance_score']}"
        )


class TestQuarantineBlocksNewWork:
    """Scheduling is gated by the barge's state, not by anything on the stem."""

    def test_order_creation_is_refused_while_the_barge_is_quarantined(self):
        """PRD §3.4: "The asset must not be `QUARANTINED`, or the request is rejected
        with `ERR_ASSET_QUARANTINED`."
        PRD §2.5: "`version`, an integer that starts at 1 on creation and increments
        by one on every mutation of the record."

        The stem is approved and confirmed and every temporal and capacity rule
        passes, so only the sibling barge's state can be doing the refusing.

        Design: Difficulty/cross_entity_state_dependency/order_creation_blocked_by_quarantined_asset
        """
        ctx = _quarantined_barge_with_a_waiting_stem()
        assert_nomination_state(ctx["nomination_c"], "APPROVED", "CONFIRMED")
        assert read_asset(ctx)["status"] == "QUARANTINED"

        response = api_client.create_delivery_order(_order_c_payload(ctx), OPS)

        validate_error(response, ApiErrorId.ERR_ASSET_QUARANTINED)
        unchanged = read_nomination(nomination_id=ctx["nomination_c"]["id"])
        assert_nomination_state(unchanged, "APPROVED", "CONFIRMED")
        assert unchanged["version"] == ctx["nomination_c"]["version"], (
            "A refused scheduling attempt must not move the stem's version, got "
            f"{unchanged['version']}"
        )

    def test_quarantine_cannot_lift_while_the_incident_is_open(self):
        """PRD §3.6: "The asset must actually be quarantined — a request against an
        already-available asset is rejected with `ERR_INVALID_ASSET_STATE` — and no
        spill incident on the asset may remain `OPEN`, else the request is rejected
        with `ERR_OPEN_SPILL_INCIDENT`."

        Design: Difficulty/cross_entity_state_dependency/order_creation_blocked_by_quarantined_asset
        """
        ctx = _quarantined_barge_with_a_waiting_stem()
        assert ctx["spill"]["status"] == "OPEN"

        response = api_client.return_asset_to_service(ctx["asset"]["id"], COMPLIANCE)

        validate_error(response, ApiErrorId.ERR_OPEN_SPILL_INCIDENT)
        assert read_asset(ctx)["status"] == "QUARANTINED", (
            "The barge must stay quarantined while its incident is open"
        )

    def test_containment_then_release_reopens_the_barge_for_scheduling(self):
        """PRD §3.6: "First, confirming containment records the port response team's
        case reference as `response_ref` and sets `containment_confirmed` to true;
        nothing else sets that flag."
        PRD §3.6: "Second, closing the incident moves it `OPEN → CLOSED` and stamps
        `closed_at` with the logical clock, but only if `containment_confirmed` is
        true and `response_ref` is not null — either omission is rejected with
        `ERR_CONTAINMENT_NOT_CONFIRMED` (HTTP 422)."
        PRD §3.6: "Release recomputes the asset's `compliance_score` against the
        current decay window, so the asset re-enters the auto-schedule candidate pool
        with a score that reflects how long ago its incidents happened."

        Design: Difficulty/cross_entity_state_dependency/order_creation_blocked_by_quarantined_asset
        """
        ctx = _quarantined_barge_with_a_waiting_stem()

        confirmed = confirm_containment(ctx)
        assert confirmed["containment_confirmed"] is True, (
            "Confirming containment must set the flag"
        )
        assert confirmed["response_ref"] == "RESP-RTM-0001", (
            f"The response team's reference must be stored, got "
            f"{confirmed['response_ref']}"
        )
        closed = close_spill(ctx)
        assert closed["status"] == "CLOSED", (
            f"The incident must close, got {closed['status']}"
        )

        asset = return_asset_to_service(ctx)

        assert asset["status"] == "AVAILABLE", (
            f"The barge must return to service, got {asset['status']}"
        )
        assert asset["compliance_score"] == pytest.approx(55.00, abs=0.01), (
            "A closed incident still counts at full weight inside 30 days, so the "
            f"score stays 55.00, got {asset['compliance_score']}"
        )

        order = validate_success(
            api_client.create_delivery_order(_order_c_payload(ctx), OPS), 201
        )
        assert order["logistics_status"] == "SCHEDULED", (
            f"The stem must now take a slot, got {order['logistics_status']}"
        )
        assert_nomination_state(
            read_nomination(nomination_id=ctx["nomination_c"]["id"]),
            "APPROVED",
            "SCHEDULED",
        )


class TestContainmentSignOffOrder:
    """Closing an incident is the second of two steps, never the first."""

    def test_closing_before_containment_is_confirmed_is_refused(self):
        """PRD §3.6: "Second, closing the incident moves it `OPEN → CLOSED` and stamps
        `closed_at` with the logical clock, but only if `containment_confirmed` is true
        and `response_ref` is not null — either omission is rejected with
        `ERR_CONTAINMENT_NOT_CONFIRMED` (HTTP 422)."
        PRD §3.6: "The incident opens in status `OPEN` with `containment_confirmed`
        false, `response_ref` null and `closed_at` null."
        PRD §3.6: "A minor incident suspends only its own order and leaves the asset
        available."

        50.00 litres with the boom in the water is a minor incident, so the barge is
        never quarantined and the only thing standing in the way of closure is the
        missing containment sign-off.

        Design: Corner/state_machines/spill_close_before_containment_confirmed_rejected
        """
        ctx = build_open_spill(quotes=[EARLY_QUOTE], spill=MINOR_SPILL)
        incident = ctx["spill"]
        assert incident["severity"] == "MINOR", (
            "50.00 litres behind a deployed boom is minor, got "
            f"{incident['severity']}"
        )
        assert incident["penalty_points"] == pytest.approx(15.00, abs=0.01), (
            f"A minor incident carries 15.00 points, got {incident['penalty_points']}"
        )

        response = api_client.close_spill_incident(incident["id"], COMPLIANCE)

        validate_error(response, ApiErrorId.ERR_CONTAINMENT_NOT_CONFIRMED)
        after = read_spill(ctx)
        assert after["status"] == "OPEN", (
            f"The refused closure must leave the incident open, got {after['status']}"
        )
        assert after["containment_confirmed"] is False, (
            "Only the confirm step may set the containment flag"
        )
        assert after["closed_at"] is None, (
            f"closed_at must stay null, got {after['closed_at']}"
        )
        assert read_asset(ctx)["status"] == "AVAILABLE", (
            "A minor incident leaves the barge available, got "
            f"{read_asset(ctx)['status']}"
        )

    def test_the_two_steps_close_the_incident_and_a_repeat_close_is_refused(self):
        """PRD §3.6: "First, confirming containment records the port response team's
        case reference as `response_ref` and sets `containment_confirmed` to true;
        nothing else sets that flag."
        PRD §3.6: "Closing an incident that is already `CLOSED` is rejected with
        `ERR_INVALID_SPILL_STATE` (HTTP 409)."
        PRD §3.6: "An incident aged 30 days or fewer contributes its full
        `penalty_points`, weighted by 1.00."

        The clock stands at 2026-08-10T06:30:00Z throughout, so the closure is stamped
        there and the fresh minor penalty counts at full weight.

        Design: Corner/state_machines/spill_close_before_containment_confirmed_rejected
        """
        ctx = build_open_spill(quotes=[EARLY_QUOTE], spill=MINOR_SPILL)

        confirmed = validate_success(
            api_client.confirm_containment(
                ctx["spill"]["id"],
                confirm_containment_payload(MINOR_CASE_REF),
                COMPLIANCE,
            )
        )
        assert confirmed["containment_confirmed"] is True, (
            "The first step must set the flag"
        )
        assert confirmed["response_ref"] == MINOR_CASE_REF, (
            f"The case reference must be stored, got {confirmed['response_ref']}"
        )
        assert confirmed["status"] == "OPEN", (
            "Confirming containment does not itself close the incident, got "
            f"{confirmed['status']}"
        )

        closed = close_spill(ctx)

        assert closed["status"] == "CLOSED", (
            f"The second step must close the incident, got {closed['status']}"
        )
        assert closed["closed_at"].startswith("2026-08-10T06:30:00"), (
            f"closed_at takes the logical clock, got {closed['closed_at']}"
        )
        repeat = api_client.close_spill_incident(ctx["spill"]["id"], COMPLIANCE)
        validate_error(repeat, ApiErrorId.ERR_INVALID_SPILL_STATE)
        assert read_spill(ctx)["closed_at"].startswith("2026-08-10T06:30:00"), (
            "The refused repeat must not restamp the closure"
        )
        asset = read_asset(ctx)
        assert asset["status"] == "AVAILABLE", (
            f"The barge was never quarantined, got {asset['status']}"
        )
        assert asset["compliance_score"] == pytest.approx(85.00, abs=0.01), (
            "100.00 less the 15.00 minor penalty at full weight is 85.00, got "
            f"{asset['compliance_score']}"
        )


class TestPenaltyDecayOnRelease:
    """Release rescores the barge against the age of its incidents."""

    def test_an_incident_aged_thirty_two_days_counts_at_half_weight(self):
        """PRD §3.6: "An incident aged 31 through 90 days contributes half, weighted by
        0.50."
        PRD §3.6: "For each incident, its age in whole days is the elapsed time from
        `reported_at` to the current logical clock divided by 24 hours and rounded down to
        a whole number of days."
        PRD §3.6: "Each incident's weighted contribution is rounded to two decimal
        places before it is added to the running penalty."
        PRD §3.6: "Release recomputes the asset's `compliance_score` against the current
        decay window, so the asset re-enters the auto-schedule candidate pool with a score
        that reflects how long ago its incidents happened."

        The incident was reported at 2026-08-10T06:45:00Z and the release happens at
        2026-09-11T06:45:00Z, exactly 32 whole days later — one day past the full-weight
        band — so 45.00 points weigh in at 22.50 and the score is 77.50 with no clean
        delivery to earn a bonus.

        Design: Corner/calculations/compliance_score_decay_band_at_thirty_two_days
        """
        ctx = build_closed_spill(quotes=[EARLY_QUOTE], spill=AGED_SPILL)
        assert ctx["spill"]["severity"] == "MAJOR", (
            "150.00 litres is at or above the 100.00-litre threshold, got "
            f"{ctx['spill']['severity']}"
        )
        assert ctx["spill"]["status"] == "CLOSED", (
            f"The incident must be closed before a release, got {ctx['spill']['status']}"
        )
        assert read_asset(ctx)["status"] == "QUARANTINED", (
            "The major incident must have quarantined the barge, got "
            f"{read_asset(ctx)['status']}"
        )
        set_logical_clock(THIRTY_TWO_DAYS_LATER)

        asset = return_asset_to_service(ctx)

        assert asset["status"] == "AVAILABLE", (
            f"The release must return the barge to service, got {asset['status']}"
        )
        assert asset["compliance_score"] == pytest.approx(77.50, abs=0.01), (
            "100.00 less 45.00 weighted by 0.50 is 77.50, got "
            f"{asset['compliance_score']}"
        )
        assert read_spill(ctx)["penalty_points"] == pytest.approx(45.00, abs=0.01), (
            "Decay weights the contribution without rewriting the incident's own "
            f"points, got {read_spill(ctx)['penalty_points']}"
        )


class TestCascadeIsVisibleWithoutDelay:
    """No background pass settles the spill cascade."""

    def test_the_report_response_and_the_next_reads_already_show_everything(self):
        """PRD §3.6: "Reporting an incident always suspends the delivery it happened
        on: an order in `SCHEDULED`, `CLEARED` or `PUMPING` moves to `SUSPENDED`, and the
        asset's `compliance_score` is recomputed to absorb the new penalty points."
        PRD §3.6: "When and only when the derived severity is `MAJOR`, a deeper cascade
        fires: the asset moves `AVAILABLE → QUARANTINED`; every **other** delivery order
        on that asset whose `logistics_status` is `SCHEDULED` or `CLEARED` moves to
        `CANCELLED`; and each of those cancelled orders pushes its own nomination
        `SCHEDULED → AWAITING_SCHEDULE`."
        PRD §2.5: "All resources except index quotes additionally carry `updated_at`, an
        ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer
        that starts at 1 on creation and increments by one on every mutation of the
        record."

        140.00 litres is a major incident even with the boom deployed. Everything the
        cascade touches is already settled in the creating response and in the reads that
        follow it, and reading the barge twice with no write between must return the same
        projection rather than a converging one.

        Design: Corner/consistency_model/spill_cascade_and_score_visible_without_any_delay
        """
        ctx = build_pumping_order(quotes=[EARLY_QUOTE])

        incident = report_spill(ctx, **MID_TRANSFER_SPILL)

        assert incident["severity"] == "MAJOR", (
            "140.00 litres is at or above the 100.00-litre threshold, got "
            f"{incident['severity']}"
        )
        assert incident["penalty_points"] == pytest.approx(45.00, abs=0.01), (
            f"A major incident carries 45.00 points, got {incident['penalty_points']}"
        )
        assert incident["status"] == "OPEN", (
            f"The creating response already carries the status, got {incident['status']}"
        )
        assert incident["containment_confirmed"] is False, (
            "The containment flag opens false in the same response"
        )
        first_read = read_asset(ctx)
        assert first_read["status"] == "QUARANTINED", (
            f"The barge must already be quarantined, got {first_read['status']}"
        )
        assert first_read["compliance_score"] == pytest.approx(55.00, abs=0.01), (
            "100.00 less the fresh 45.00 penalty is 55.00 with no clean delivery to "
            f"bonus, got {first_read['compliance_score']}"
        )
        assert read_order(ctx)["logistics_status"] == "SUSPENDED", (
            "The transfer the spill happened on must already be suspended, got "
            f"{read_order(ctx)['logistics_status']}"
        )
        second_read = read_asset(ctx)
        assert second_read == first_read, (
            "Two reads with no write between them must return the identical "
            f"projection, got {second_read} after {first_read}"
        )
