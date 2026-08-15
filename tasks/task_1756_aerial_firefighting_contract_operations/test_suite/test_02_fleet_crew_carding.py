"""Fleet and crew registration, the carding program, and its cascades."""
from test_helpers import (
    INSPECTOR,
    ApiErrorId,
    TEST_USERS,
    accept_order,
    add_aircraft,
    add_carded_pilot,
    add_crew_member,
    card_aircraft,
    card_crew_member,
    complete_inspection,
    create_active_contract,
    create_assignment,
    create_availability_period_payload,
    create_draft_invoice,
    create_incident,
    get_aircraft,
    get_invoice,
    place_order,
    schedule_inspection,
    setup_carded_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["carrier_ops_headers"]
DISPATCH = TEST_USERS["agency_dispatcher_headers"]


class TestCardedGate:
    def test_carded_gate_errors_aircraft_and_crew(self, api):
        """PRD §3.5: "Both the aircraft and the pilot must currently be
        `CARDED`, or creation fails with `ERR_AIRCRAFT_NOT_CARDED` or
        `ERR_CREW_NOT_CARDED` respectively."
        PRD §3.2: "New aircraft are `UNCARDED` with a null `carded_until`."

        Design: Corner/validations/carded_gate_errors_aircraft_and_crew
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])  # stays UNCARDED
        pilot = add_crew_member(contract["id"], full_name="Pat Reed")
        card_crew_member(pilot["id"])
        pilot2 = add_crew_member(contract["id"], full_name="Sam Ortiz")
        incident = create_incident()
        order1 = accept_order(place_order(
            contract["id"], incident["id"], order_number="O-1001")["id"])
        order2 = accept_order(place_order(
            contract["id"], incident["id"], order_number="O-1002")["id"])

        # UNCARDED aircraft blocks creation.
        v1 = validate_success(api.get_dispatch_order(order1["id"], OPS))["version"]
        resp1 = api.create_assignment(order1["id"], {
            "aircraft_id": aircraft["id"], "pilot_id": pilot["id"],
            "planned_start": "2026-08-04T08:00:00Z",
            "planned_end": "2026-08-04T09:00:00Z",
            "expected_dispatch_order_version": v1,
        }, OPS)
        validate_error(resp1, ApiErrorId.ERR_AIRCRAFT_NOT_CARDED,
                       expected_status=409)

        # Card the aircraft; now the UNCARDED pilot blocks creation.
        aircraft = card_aircraft(aircraft["id"])
        assert aircraft["carding_status"] == "CARDED"
        v2 = validate_success(api.get_dispatch_order(order2["id"], OPS))["version"]
        resp2 = api.create_assignment(order2["id"], {
            "aircraft_id": aircraft["id"], "pilot_id": pilot2["id"],
            "planned_start": "2026-08-04T08:00:00Z",
            "planned_end": "2026-08-04T09:00:00Z",
            "expected_dispatch_order_version": v2,
        }, OPS)
        validate_error(resp2, ApiErrorId.ERR_CREW_NOT_CARDED,
                       expected_status=409)


class TestLaunchCardingExpiry:
    def test_launch_with_expired_card_rejected(self, api):
        """PRD §3.6: "the aircraft must be `CARDED` with `carded_until` on or
        after the current clock date — an expired card is `ERR_CARDING_EXPIRED`".
        PRD §3.2: "with `carded_until` set to the calendar date of
        `completed_at` plus `valid_days` days".

        Design: Corner/state_machines/launch_with_expired_card_rejected
        """
        # Card valid_days=1 from 2026-07-15 => carded_until 2026-07-16, while
        # the default logical clock is already 2026-08-01.
        ws = setup_carded_pair(aircraft_card_days=1)
        aircraft = get_aircraft(ws["aircraft"]["id"])
        assert aircraft["carding_status"] == "CARDED"
        assert aircraft["carded_until"] == "2026-07-16"

        order = accept_order(place_order(
            ws["contract"]["id"], ws["incident"]["id"])["id"])
        assignment = create_assignment(
            order["id"], aircraft["id"], ws["pilot"]["id"],
            "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z")

        from test_helpers import make_pilot_headers
        resp = api.launch_assignment(
            assignment["id"], make_pilot_headers(ws["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CARDING_EXPIRED, expected_status=422)

        after = validate_success(api.get_assignment(assignment["id"], OPS))
        assert after["status"] == "ASSIGNED", "rejected launch leaves ASSIGNED"


class TestIncidentAdvance:
    def test_incident_skip_level_advance_rejected(self, api):
        """PRD §3.4: "Incidents advance strictly along `REPORTED` → `ACTIVE` →
        `CONTAINED` → `CLOSED`, each step taken by naming the target in
        `to_status`".
        PRD §2.9: "the requested transition must be valid from the entity's
        current state (`ERR_INVALID_STATE`, HTTP 409)".

        Design: Corner/state_machines/incident_skip_level_advance_rejected
        """
        incident = create_incident()
        assert incident["status"] == "REPORTED"

        resp = api.advance_incident(incident["id"], {"to_status": "CONTAINED"},
                                    DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = validate_success(api.get_incident(incident["id"], DISPATCH))
        assert after["status"] == "REPORTED"


class TestAircraftCardingCycle:
    def test_aircraft_suspend_then_recard_refreshes_validity(self, api):
        """PRD §3.2: "On `PASSED`, the subject — aircraft or crew member —
        becomes `CARDED`, with `carded_until` set to the calendar date of
        `completed_at` plus `valid_days` days; this holds whether the subject
        was `UNCARDED` or previously `SUSPENDED`."
        PRD §3.2: "On `FAILED`, a `CARDED` subject drops to `SUSPENDED` and its
        `carded_until` is cleared."

        Design: Difficulty/non_linear_state_machine/aircraft_carding_suspend_recard_cycle
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        card_aircraft(aircraft["id"])
        aircraft = get_aircraft(aircraft["id"])
        assert aircraft["carding_status"] == "CARDED"
        assert aircraft["carded_until"] == "2027-07-15", \
            "2026-07-15 pass plus 365 valid days"

        i2 = schedule_inspection(subject_aircraft_id=aircraft["id"],
                                 scheduled_for="2026-08-01T08:00:00Z")
        complete_inspection(i2["id"], result="FAILED",
                            completed_at="2026-08-02T09:00:00Z")
        aircraft = get_aircraft(aircraft["id"])
        assert aircraft["carding_status"] == "SUSPENDED"
        assert aircraft["carded_until"] is None, "failure clears carded_until"

        # Reinspect and pass: the same aircraft returns to CARDED.
        from test_helpers import api_client as _api  # local alias for clarity
        get_success = validate_success
        resp = _api.reschedule_carding_inspection(
            i2["id"], {"scheduled_for": "2026-08-03T08:00:00Z"}, INSPECTOR)
        get_success(resp, 200)
        complete_inspection(i2["id"], result="PASSED",
                            completed_at="2026-08-03T09:00:00Z")
        aircraft = get_aircraft(aircraft["id"])
        assert aircraft["carding_status"] == "CARDED"
        assert aircraft["carded_until"] == "2027-08-03", \
            "carded_until recomputed from the new pass date plus 365 days"

    def test_failed_inspection_reschedule_resets_result(self, api):
        """PRD §3.2: "When a `COMPLETED` inspection ended in failure, the
        inspector may reschedule it, moving it `COMPLETED` → `SCHEDULED` with
        `result` reset to `PENDING`, `completed_at` cleared, and a new
        `scheduled_for`".

        Design: Difficulty/non_linear_state_machine/aircraft_carding_suspend_recard_cycle
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        card_aircraft(aircraft["id"])

        i2 = schedule_inspection(subject_aircraft_id=aircraft["id"],
                                 scheduled_for="2026-08-01T08:00:00Z")
        failed = complete_inspection(i2["id"], result="FAILED",
                                     completed_at="2026-08-02T09:00:00Z")
        assert failed["status"] == "COMPLETED"
        assert failed["result"] == "FAILED"

        from test_helpers import api_client as _api
        rescheduled = validate_success(_api.reschedule_carding_inspection(
            i2["id"], {"scheduled_for": "2026-08-03T08:00:00Z"}, INSPECTOR), 200)
        assert rescheduled["status"] == "SCHEDULED", "revision loop reopens it"
        assert rescheduled["result"] == "PENDING", "result reset to PENDING"
        assert rescheduled["completed_at"] is None, "completed_at cleared"
        # PRD pins the new scheduled_for instant (§3.2); instants are ISO 8601
        # UTC (§2.6) but the lexical rendering (fractional digits) is not
        # pinned, so compare parsed instants rather than raw strings.
        from datetime import datetime as _dt, timezone as _tz
        assert _dt.fromisoformat(
            rescheduled["scheduled_for"].replace("Z", "+00:00")) == _dt(
                2026, 8, 3, 8, 0, tzinfo=_tz.utc), "new scheduled_for carried"

        # The reopened inspection completes again on the same record.
        repassed = complete_inspection(i2["id"], result="PASSED",
                                       completed_at="2026-08-03T09:00:00Z")
        assert repassed["id"] == i2["id"]
        assert repassed["result"] == "PASSED"


class TestInspectionFailCascade:
    def _setup_covering_draft_invoice(self):
        """Carded aircraft with a CONFIRMED 570-minute day on 2026-08-05 and a
        DRAFT invoice covering all of August."""
        ws = setup_carded_pair()
        period = validate_success(api_client_create_period(
            ws["contract"]["id"], ws["aircraft"]["id"]), 201)
        invoice = create_draft_invoice(ws["contract"]["id"],
                                       "2026-08-01", "2026-08-31")
        assert invoice["availability_subtotal_cents"] == 500000
        assert invoice["penalty_cents"] == 0
        assert invoice["net_cents"] == 500000
        i2 = schedule_inspection(subject_aircraft_id=ws["aircraft"]["id"],
                                 scheduled_for="2026-08-01T08:00:00Z")
        return ws, period, invoice, i2

    def test_failed_inspection_suspends_aircraft_and_flips_periods(self, api):
        """PRD §3.2: "Every availability period of that aircraft still in
        `CONFIRMED` whose `service_date` falls on or after the failure's
        calendar date flips to `UNAVAILABLE` with `excuse_reason` set to
        `CARDING`, its charge zeroed and its own version bumped."
        PRD §3.2: "On `FAILED`, a `CARDED` subject drops to `SUSPENDED` and its
        `carded_until` is cleared."

        Design: Difficulty/transitive_cascade/inspection_fail_three_link_cascade
        """
        ws, period, _invoice, i2 = self._setup_covering_draft_invoice()

        complete_inspection(i2["id"], result="FAILED",
                            completed_at="2026-08-02T09:00:00Z")

        aircraft = get_aircraft(ws["aircraft"]["id"])
        assert aircraft["carding_status"] == "SUSPENDED", "cascade link 1"

        after = validate_success(
            api.get_availability_period(period["id"], OPS))
        assert after["status"] == "UNAVAILABLE", "cascade link 2"
        assert after["excuse_reason"] == "CARDING"
        assert after["availability_charge_cents"] == 0, "charge zeroed"

    def test_draft_invoice_rederived_after_carding_cascade(self, api):
        """PRD §3.2: "Each such flip in turn re-derives every `DRAFT` invoice
        of the same contract whose billing period covers the affected
        `service_date`: line items are regenerated, the totals of §3.8
        recomputed, and each invoice's version bumped."
        PRD §3.8: "Fifth, `penalty_cents` is five percent of
        `availability_subtotal_cents`, rounded half up to whole cents".

        Design: Difficulty/transitive_cascade/inspection_fail_three_link_cascade
        """
        ws, period, invoice, i2 = self._setup_covering_draft_invoice()

        complete_inspection(i2["id"], result="FAILED",
                            completed_at="2026-08-02T09:00:00Z")

        after = get_invoice(invoice["id"])
        assert after["availability_subtotal_cents"] == 0, \
            "flipped day contributes nothing"
        assert after["penalty_cents"] == 0, \
            "5% of a zero availability subtotal is zero"
        assert after["net_cents"] == 0, "cascade link 3 re-derives the invoice"


class TestCrewAndAircraftListing:
    def test_crew_member_list_pagination(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        how many items to skip and defaults to 0."
        PRD §2.3: "the `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/crew_member_list_pagination
        """
        contract = create_active_contract()
        add_crew_member(contract["id"], full_name="Pat Reed")
        add_crew_member(contract["id"], full_name="Sam Ortiz")
        add_crew_member(contract["id"], full_name="Lee Chan",
                        crew_role="SIC", qualified_aircraft_models=[])

        page1, meta1 = validate_paginated(
            api.list_crew_members(OPS, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_crew_members(OPS, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_aircraft_list_filter_combination(self, api):
        """PRD §2.3: "the aircraft list by `contract_id` and `carding_status`".
        PRD §2.3: "`offset` sets how many items to skip and defaults to 0.
        Unless otherwise specified, every list endpoint returns resources
        sorted by `created_at` in ascending order, and the `meta` object of a
        list response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/aircraft_list_filter_combination
        """
        c1 = create_active_contract(contract_number="EU-2026-001")
        c2 = create_active_contract(contract_number="EU-2026-002")
        ac1 = add_aircraft(c1["id"], tail_number="N100AF")
        add_aircraft(c1["id"], tail_number="N200AF")  # stays UNCARDED
        card_aircraft(ac1["id"])

        data, meta = validate_paginated(
            api.list_aircraft(OPS, params={"carding_status": "CARDED"}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["tail_number"] == "N100AF"

        data2, meta2 = validate_paginated(
            api.list_aircraft(OPS, params={"contract_id": c2["id"]}))
        assert data2 == [], "empty filter result is a 200 with an empty array"
        assert meta2["total_count"] == 0
        assert meta2["has_more"] is False


# Local helper bound after imports to keep the import block PRD-domain-only.
from test_helpers import api_client  # noqa: E402


def api_client_create_period(contract_id, aircraft_id):
    return api_client.create_availability_period(
        contract_id,
        create_availability_period_payload(
            aircraft_id, service_date="2026-08-05",
            available_start="2026-08-05T07:00:00Z",
            available_end="2026-08-05T16:30:00Z"),
        OPS)
