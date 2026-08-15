"""Cold-chain thresholds, breach side effects, and the deliver safety gate
(PRD §3.4, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    cancel_distribution,
    create_distribution,
    get_distribution,
    make_crew_leader_headers,
    new_agency,
    new_crew_leader,
    new_event,
    new_farm,
    new_offer,
    new_vehicle,
    officer_headers,
    open_incident,
    record_templog,
    run_event_lifecycle,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestTempLogBreachComputation:
    def test_breach_flag_computed_server_side_for_low_class(self, api):
        """PRD §3.4: "The server computes `breach_flag` at write time. For produce
        whose `perishability_class` is `HIGH` or `MEDIUM`, a reading strictly above
        41.0°F is a breach — a reading of exactly 41.0 is not; for `LOW`, the
        threshold is 55.0°F under the same strict-above rule."

        Design: Corner/entities/templog_breach_flag_computed_not_input
        """
        farm = new_farm(farm_name="TF", county_code="TL1")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        offer = new_offer(farm["id"], perishability_class="LOW",
                          requires_refrigeration=False)
        event = new_event(offer["id"], lead["id"], vehicle["id"])
        resp = api.create_templog(
            {"glean_event_id": event["id"], "recorded_at": "2026-08-10T10:00:00Z",
             "temp_f": 60.0},
            officer_headers(),
        )
        log = validate_success(resp, 201)
        assert log["breach_flag"] is True, "60.0 > 55.0 breaches the LOW threshold"
        assert "version" not in log and "updated_at" not in log

    def test_incident_is_born_open(self, api):
        """PRD §3.4: "An incident is born `OPEN`, and an `OPEN` incident blocks both
        event reconciliation and offer closing with `ERR_INCIDENT_OPEN`."

        Design: Corner/state_machines/incident_initial_state_open
        """
        farm = new_farm(farm_name="IM", county_code="IM1")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"])
        incident = open_incident(event["id"], lead["id"], severity="CRITICAL",
                                 condemned_lbs=10.0)
        assert incident["disposition"] == "OPEN"


class TestColdChainThresholdBoundary:
    def _refrigerated_harvest_with_distribution(self, api):
        ctx = run_event_lifecycle(
            stop_at="harvested",
            offer_over={"crop_code": "LEAFY_GREENS", "estimated_lbs": 120.0,
                        "perishability_class": "HIGH", "requires_refrigeration": True},
            lot_specs=[{"gross": 110.0, "verify": True}],  # net 100.0
        )
        agency = new_agency(agency_name="AGB", county_code="BBB",
                            weekly_capacity_lbs=10000.0, refrigeration_capable=True)
        dist = create_distribution(ctx["event"]["id"], agency["id"], 50.0,
                                   delivery_date="2026-08-11T10:00:00Z")
        return ctx, agency, dist

    def test_exactly_threshold_is_not_a_breach(self, api):
        """PRD §3.4: "For produce whose `perishability_class` is `HIGH` or `MEDIUM`, a
        reading strictly above 41.0°F is a breach — a reading of exactly 41.0 is not"
        PRD §2.8: "Temperature comparisons are made at one decimal place and are
        strict: a reading must be above the threshold to count as a breach; a reading
        exactly at the threshold does not."

        Design: Difficulty/boundary_precision_check/cold_chain_threshold_strict_greater
        """
        ctx, agency, dist = self._refrigerated_harvest_with_distribution(api)
        log = record_templog(ctx["event"]["id"], 41.0,
                             recorded_at="2026-08-10T13:00:00Z")
        assert log["breach_flag"] is False, "41.0 exactly is NOT a breach (strict >)"
        assert get_distribution(dist["id"])["cold_chain_intact"] is True

    def test_one_tenth_over_threshold_breaches_and_flags_distribution(self, api):
        """PRD §3.4: "When a breaching log lands, every `SCHEDULED` distribution of
        that event has its `cold_chain_intact` recomputed to false, which in turn
        gates delivery for refrigeration-required offers."

        Design: Difficulty/boundary_precision_check/cold_chain_threshold_strict_greater
        """
        ctx, agency, dist = self._refrigerated_harvest_with_distribution(api)
        log = record_templog(ctx["event"]["id"], 41.1,
                             recorded_at="2026-08-10T14:00:00Z")
        assert log["breach_flag"] is True, "41.1 > 41.0 breaches"
        assert get_distribution(dist["id"])["cold_chain_intact"] is False, (
            "the breach flips cold_chain_intact on the SCHEDULED distribution"
        )


class TestDeliverGateOrdering:
    def _breached_setup(self, api, cancel=False):
        """Refrigeration-required event harvested 100.0; breaching log 45.0°F recorded
        after the distribution is SCHEDULED; optionally the distribution is then
        cancelled."""
        ctx = run_event_lifecycle(
            stop_at="harvested",
            offer_over={"crop_code": "LEAFY_GREENS", "estimated_lbs": 120.0,
                        "perishability_class": "HIGH", "requires_refrigeration": True},
            lot_specs=[{"gross": 110.0, "verify": True}],
        )
        agency = new_agency(agency_name="AGS", county_code="SSS",
                            weekly_capacity_lbs=10000.0, refrigeration_capable=True)
        dist = create_distribution(ctx["event"]["id"], agency["id"], 50.0,
                                   delivery_date="2026-08-11T10:00:00Z")
        record_templog(ctx["event"]["id"], 45.0, recorded_at="2026-08-10T13:00:00Z")
        if cancel:
            dist = cancel_distribution(dist["id"])
        return ctx, dist

    def test_state_gate_outranks_cold_chain_gate(self, api):
        """PRD §2.6: "Every request is evaluated against a fixed, ordered sequence of
        gates, and the first gate that fails determines the error returned — later
        gates are never consulted on a failed request."
        PRD §2.6: "4. **State compatibility** — the target resource must be in a state
        that permits the requested transition, failing with `ERR_INVALID_STATE` (HTTP
        409)."
        PRD §2.6: "5. **Cold-chain delivery gate** — `ERR_COLD_CHAIN_BREACH` (§3.4,
        §3.5)."
        PRD §2.6: "20. **Terminal-state lockdown** — any action invoked on a resource
        that has already reached a terminal state is rejected with
        `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/deliver_state_vs_safety_pair
        """
        ctx, dist = self._breached_setup(api, cancel=True)
        resp = api.deliver_distribution(
            dist["id"], {"delivered_lbs": 50.0},
            make_crew_leader_headers(ctx["lead"]["id"]),
        )
        # The state/terminal rejection (both 409) must outrank the cold-chain gate;
        # PRD does not pin which of gates 4 and 20 reports a terminal path target.
        assert resp.status_code == 409
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL]
        )
        assert get_distribution(dist["id"])["status"] == "CANCELLED"

    def test_cold_chain_gate_rejects_delivery_alone(self, api):
        """PRD §3.5: "Both outcomes require the event to be `HARVESTED` and — for
        refrigeration-required offers — `cold_chain_intact` still true, failing with
        `ERR_COLD_CHAIN_BREACH` otherwise."

        Design: Difficulty/priority_pair_validation_conflict/deliver_state_vs_safety_pair
        """
        ctx, dist = self._breached_setup(api, cancel=False)
        resp = api.deliver_distribution(
            dist["id"], {"delivered_lbs": 50.0},
            make_crew_leader_headers(ctx["lead"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_BREACH, 422)
        assert get_distribution(dist["id"])["status"] == "SCHEDULED"
