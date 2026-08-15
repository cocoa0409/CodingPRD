"""Outbreak zones, quarantine orders, and the infection cascade: cyclic zone
transitions, three-link hold/restore cascades, segregation of duties, lazy
expiry (PRD §3.2, §3.6, §3.7)."""
from test_helpers import (
    AUDITOR,
    ApiErrorId,
    assert_outbreak_zone,
    assert_quarantine_order,
    create_draft_certificate,
    create_outbreak_zone,
    create_premises,
    create_quarantine_order,
    create_test_record,
    get_certificate,
    get_permit,
    get_premises,
    make_officer_headers,
    report_result,
    set_clock,
    setup_issued_certificate_with_permit,
    setup_standard_scenario,
    submit_certificate,
    transmit_and_acknowledge,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestZoneReescalationCycle:
    def test_outbreak_zone_reescalation_cycle_sequence(self, api, officer_headers):
        """PRD §3.6: "A zone is born `MONITORING`, and a zone id that
        does not exist yields `ERR_OUTBREAK_ZONE_NOT_FOUND` (HTTP 404)."
        PRD §3.6: "Escalation moves a zone from `MONITORING` or `CONTAINED` to
        `ACTIVE` — the re-escalation loop lets a contained outbreak flare back".
        PRD §3.6: "Containment moves an `ACTIVE` zone to `CONTAINED`".

        Design: Difficulty/non_linear_state_machine/outbreak_zone_reescalation_cycle
        """
        zone = create_outbreak_zone(
            county="Colusa", disease_code="AVIAN_INFLUENZA", species_code="POULTRY",
            severity="MODERATE",
        )
        assert zone["status"] == "MONITORING"

        z = validate_success(api.escalate_outbreak_zone(zone["id"], officer_headers), 200)
        assert z["status"] == "ACTIVE"
        z = validate_success(api.contain_outbreak_zone(zone["id"], officer_headers), 200)
        assert z["status"] == "CONTAINED"

    def test_outbreak_zone_reescalation_cycle_second_escalate(self, api, officer_headers):
        """PRD §3.6: "Escalation moves a zone from `MONITORING` or `CONTAINED`
        to `ACTIVE` — the re-escalation loop lets a contained outbreak flare
        back — and from any other state is rejected with
        `ERR_ZONE_INVALID_TRANSITION` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/outbreak_zone_reescalation_cycle
        """
        zone = create_outbreak_zone(
            county="Colusa", disease_code="AVIAN_INFLUENZA", species_code="POULTRY",
            severity="MODERATE",
        )
        api.escalate_outbreak_zone(zone["id"], officer_headers)
        api.contain_outbreak_zone(zone["id"], officer_headers)
        # The CONTAINED -> ACTIVE re-escalation arc exists and succeeds.
        z = validate_success(api.escalate_outbreak_zone(zone["id"], officer_headers), 200)
        assert_outbreak_zone(z)
        assert z["status"] == "ACTIVE", "CONTAINED -> ACTIVE re-escalation arc"


class TestEscalateCascadeThreeLevels:
    def _setup_zone_over_issued_chain(self, api):
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        zone = create_outbreak_zone()  # Yolo / VESICULAR_STOMATITIS / CATTLE
        return scenario, cert, permit, zone

    def test_outbreak_escalate_cascades_three_levels_premises_and_certificate(
        self, api, officer_headers
    ):
        """PRD §3.6: "Escalation fires a three-link cascade, atomically: 1.
        Every premises whose `county` and `species_code` match the zone and
        whose `disease_status` is not already `INFECTED` drops to
        `QUARANTINE_HOLD`. 2. Every certificate originating at a just-held
        premises whose `status` is `ISSUED` or `TRANSMITTED` becomes
        `ENTRY_BLOCKED`, remembering where it came from in `pre_block_status`
        (`ISSUED` or `TRANSMITTED` respectively; the field is null at all other
        times)."

        Design: Difficulty/transitive_cascade/outbreak_escalate_cascades_three_levels
        """
        scenario, cert, permit, zone = self._setup_zone_over_issued_chain(api)
        validate_success(api.escalate_outbreak_zone(zone["id"], officer_headers), 200)

        premises = get_premises(scenario["premises"]["id"])
        assert premises["disease_status"] == "QUARANTINE_HOLD", "cascade link 1"
        cert_after = get_certificate(cert["id"])
        assert cert_after["status"] == "ENTRY_BLOCKED", "cascade link 2"
        assert cert_after["pre_block_status"] == "ISSUED"

    def test_outbreak_escalate_cascades_three_levels_permit(self, api, officer_headers):
        """PRD §3.6: "3. Every movement permit in `ISSUED` whose certificate
        was just blocked becomes `SUSPENDED`."

        Design: Difficulty/transitive_cascade/outbreak_escalate_cascades_three_levels
        """
        scenario, cert, permit, zone = self._setup_zone_over_issued_chain(api)
        validate_success(api.escalate_outbreak_zone(zone["id"], officer_headers), 200)

        permit_after = get_permit(permit["id"])
        assert permit_after["status"] == "SUSPENDED", "cascade link 3"


class TestResolveRestoresChain:
    def test_outbreak_resolve_restores_full_chain(self, api, officer_headers):
        """PRD §3.6: "Containment moves an `ACTIVE` zone to `CONTAINED` and is
        a paperwork-only gesture: all holds stay exactly where they are, and
        only resolution releases them."
        PRD §3.6: "Resolving from `CONTAINED` runs the three-link restore
        cascade: every premises held by this zone (county and species match,
        `disease_status` `QUARANTINE_HOLD`) returns to `MONITORED`, but only
        when no other `ACTIVE` zone covers it and no `ACTIVE` quarantine order
        covers it; every certificate in `ENTRY_BLOCKED` whose origin premises
        was just restored returns to the state saved in `pre_block_status` —
        back to `ISSUED` or back to `TRANSMITTED` — and clears
        `pre_block_status` to null; and every permit in `SUSPENDED` whose
        certificate was just restored returns to `ISSUED`."

        Design: Corner/state_machines/outbreak_resolve_restores_full_chain
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        # Drive the certificate to TRANSMITTED before the outbreak.
        transmit_and_acknowledge(cert["id"], officer_headers)
        assert get_certificate(cert["id"])["status"] == "TRANSMITTED"

        zone = create_outbreak_zone()
        validate_success(api.escalate_outbreak_zone(zone["id"], officer_headers), 200)
        blocked = get_certificate(cert["id"])
        assert blocked["status"] == "ENTRY_BLOCKED"
        assert blocked["pre_block_status"] == "TRANSMITTED", (
            "pre_block_status remembers TRANSMITTED, not ISSUED"
        )

        # Containment releases nothing.
        validate_success(api.contain_outbreak_zone(zone["id"], officer_headers), 200)
        assert get_premises(scenario["premises"]["id"])["disease_status"] == "QUARANTINE_HOLD"

        # Resolution runs the full restore cascade.
        validate_success(api.resolve_outbreak_zone(zone["id"], officer_headers), 200)
        assert get_premises(scenario["premises"]["id"])["disease_status"] == "MONITORED"
        restored = get_certificate(cert["id"])
        assert restored["status"] == "TRANSMITTED"
        assert restored["pre_block_status"] is None
        assert get_permit(permit["id"])["status"] == "ISSUED"


class TestZoneTransitionMatrix:
    def test_zone_invalid_transition_matrix(self, api, officer_headers):
        """PRD §3.6: "Resolution is allowed from `MONITORING` or `CONTAINED` —
        attempting escalate, contain, or resolve from an incompatible state
        always yields `ERR_ZONE_INVALID_TRANSITION`."
        PRD §3.6: "Resolving from `MONITORING` has nothing to unwind."

        Design: Corner/state_machines/zone_invalid_transition_matrix
        """
        z1 = create_outbreak_zone(
            county="Colusa", disease_code="AVIAN_INFLUENZA", species_code="POULTRY",
            severity="MODERATE",
        )
        validate_error(
            api.contain_outbreak_zone(z1["id"], officer_headers),
            ApiErrorId.ERR_ZONE_INVALID_TRANSITION,
        )
        assert validate_success(
            api.escalate_outbreak_zone(z1["id"], officer_headers), 200
        )["status"] == "ACTIVE"
        validate_error(
            api.resolve_outbreak_zone(z1["id"], officer_headers),
            ApiErrorId.ERR_ZONE_INVALID_TRANSITION,
        )
        assert validate_success(
            api.contain_outbreak_zone(z1["id"], officer_headers), 200
        )["status"] == "CONTAINED"
        assert validate_success(
            api.resolve_outbreak_zone(z1["id"], officer_headers), 200
        )["status"] == "RESOLVED"
        validate_error(
            api.escalate_outbreak_zone(z1["id"], officer_headers),
            ApiErrorId.ERR_ZONE_INVALID_TRANSITION,
        )

        # The direct MONITORING -> RESOLVED arc is legal.
        z2 = create_outbreak_zone(
            county="Colusa", disease_code="AVIAN_INFLUENZA", species_code="POULTRY",
            severity="LOW",
            effective_from="2026-08-05T00:00:00Z", effective_until="2026-08-20T00:00:00Z",
        )
        assert validate_success(
            api.resolve_outbreak_zone(z2["id"], officer_headers), 200
        )["status"] == "RESOLVED"


class TestZoneWindowOverlap:
    def test_outbreak_zone_half_open_adjacency_accepted(self, api, officer_headers):
        """PRD §3.6: "The zone's half-open window runs from
        `effective_from` (inclusive) to `effective_until` (exclusive, null for
        open-ended, and strictly later than `effective_from` when provided)."
        PRD §3.6: "Declaration is rejected with `ERR_ZONE_WINDOW_OVERLAP`
        (HTTP 409) when the new zone's window would overlap another zone in
        `MONITORING`, `ACTIVE`, or `CONTAINED` for the same combination of
        county, disease, and species".

        Design: Difficulty/resource_temporal_overlap/outbreak_zone_half_open_adjacency
        """
        create_outbreak_zone(
            county="Colusa", disease_code="AVIAN_INFLUENZA", species_code="POULTRY",
            severity="LOW",
            effective_from="2026-08-10T00:00:00Z", effective_until="2026-08-20T00:00:00Z",
        )
        # Gap-0 adjacency: starts exactly at the predecessor's exclusive end.
        zone_b = create_outbreak_zone(
            county="Colusa", disease_code="AVIAN_INFLUENZA", species_code="POULTRY",
            severity="LOW",
            effective_from="2026-08-20T00:00:00Z", effective_until="2026-08-30T00:00:00Z",
        )
        assert zone_b["status"] == "MONITORING"

    def test_outbreak_zone_half_open_adjacency_overlap_rejected(self, api, officer_headers):
        """PRD §3.6: "Declaration is rejected with `ERR_ZONE_WINDOW_OVERLAP`
        (HTTP 409) when the new zone's window would overlap another zone in
        `MONITORING`, `ACTIVE`, or `CONTAINED` for the same combination of
        county, disease, and species".

        Design: Difficulty/resource_temporal_overlap/outbreak_zone_half_open_adjacency
        """
        create_outbreak_zone(
            county="Colusa", disease_code="AVIAN_INFLUENZA", species_code="POULTRY",
            severity="LOW",
            effective_from="2026-08-10T00:00:00Z", effective_until="2026-08-20T00:00:00Z",
        )
        # Starts one day inside the existing half-open window -> overlap.
        resp = api.create_outbreak_zone(
            {
                "county": "Colusa", "state_code": "CA",
                "disease_code": "AVIAN_INFLUENZA", "species_code": "POULTRY",
                "severity": "HIGH", "effective_from": "2026-08-19T00:00:00Z",
            },
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_WINDOW_OVERLAP)

    def test_zone_window_overlap_ignores_resolved(self, api, officer_headers):
        """PRD §3.6: "zones that have reached `RESOLVED` no longer block."
        PRD §3.6: "Declaration is rejected with `ERR_ZONE_WINDOW_OVERLAP`
        (HTTP 409) when the new zone's window would overlap another zone in
        `MONITORING`, `ACTIVE`, or `CONTAINED` for the same combination of
        county, disease, and species".

        Design: Corner/validations/zone_window_overlap_ignores_resolved
        """
        z1 = create_outbreak_zone(
            county="Colusa", disease_code="AVIAN_INFLUENZA", species_code="POULTRY",
            severity="LOW",
            effective_from="2026-08-10T00:00:00Z", effective_until="2026-08-20T00:00:00Z",
        )
        resolved = validate_success(api.resolve_outbreak_zone(z1["id"], officer_headers), 200)
        assert resolved["status"] == "RESOLVED"

        # Overlapping only the RESOLVED zone's window is accepted.
        z2 = create_outbreak_zone(
            county="Colusa", disease_code="AVIAN_INFLUENZA", species_code="POULTRY",
            severity="MODERATE",
            effective_from="2026-08-15T00:00:00Z", effective_until="2026-08-25T00:00:00Z",
        )
        assert z2["status"] == "MONITORING", (
            "terminal zones are excluded from the overlap sweep"
        )

        # Overlapping the still-live MONITORING zone is rejected.
        resp = api.create_outbreak_zone(
            {
                "county": "Colusa", "state_code": "CA",
                "disease_code": "AVIAN_INFLUENZA", "species_code": "POULTRY",
                "severity": "HIGH",
                "effective_from": "2026-08-22T00:00:00Z",
                "effective_until": "2026-08-30T00:00:00Z",
            },
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_WINDOW_OVERLAP)


class TestQuarantineSpacing:
    def _setup_lifted_order(self, api):
        premises = create_premises(name="Ranch L", initial_head_count=20)
        # Pin the logical clock inside q1's active window so the lazy EXPIRED
        # materialization does not fire before the lift (PRD §2.4).
        set_clock("2026-07-01T00:00:00Z")
        q1 = create_quarantine_order(
            premises["id"],
            start_at="2026-06-12T00:00:00Z",
            end_at="2026-07-10T00:00:00Z",
            reason="INITIAL_HOLD",
            officer_user_id="officer-a",
        )
        lifted = validate_success(
            api.lift_quarantine_order(q1["id"], make_officer_headers("officer-b")), 200
        )
        assert lifted["status"] == "LIFTED"
        return premises

    def test_quarantine_closed_interval_with_min_gap_exact_pass(self, api, officer_headers):
        """PRD §3.7: "a new order may not begin less than 14 days after the
        most recent `LIFTED` or `EXPIRED` order's `end_at` for that premises
        and species — a shorter gap yields `ERR_QUARANTINE_MIN_GAP_VIOLATION`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/quarantine_closed_interval_with_min_gap
        """
        premises = self._setup_lifted_order(api)
        # Exactly 14 days after the LIFTED order's end_at 2026-07-10: allowed.
        q2 = create_quarantine_order(
            premises["id"],
            start_at="2026-07-24T00:00:00Z",
            end_at="2026-08-07T00:00:00Z",
            reason="SECOND_HOLD",
            officer_user_id="officer-a",
        )
        assert_quarantine_order(q2)
        assert q2["status"] == "ACTIVE", "a gap of exactly 14 days passes (inclusive)"

    def test_quarantine_closed_interval_with_min_gap_violations(self, api, officer_headers):
        """PRD §3.7: "a new order may not begin less than 14 days after the
        most recent `LIFTED` or `EXPIRED` order's `end_at` for that premises
        and species — a shorter gap yields `ERR_QUARANTINE_MIN_GAP_VIOLATION`
        (HTTP 422)."
        PRD §3.7: "The new order's closed interval may not overlap an `ACTIVE`
        order for the same premises and species — overlap yields
        `ERR_QUARANTINE_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/quarantine_closed_interval_with_min_gap
        """
        premises = self._setup_lifted_order(api)
        q2 = create_quarantine_order(
            premises["id"],
            start_at="2026-07-24T00:00:00Z",
            end_at="2026-08-07T00:00:00Z",
            reason="SECOND_HOLD",
            officer_user_id="officer-a",
        )

        # 12 days after the LIFTED order's end_at: too soon.
        resp_gap = api.create_quarantine_order(
            {
                "premises_id": premises["id"], "species_code": "CATTLE",
                "disease_code": "BRUCELLOSIS",
                "start_at": "2026-07-22T00:00:00Z", "end_at": "2026-07-23T00:00:00Z",
                "reason": "TOO_SOON",
            },
            make_officer_headers("officer-a"),
        )
        validate_error(resp_gap, ApiErrorId.ERR_QUARANTINE_MIN_GAP_VIOLATION)

        # Closed-interval overlap with the ACTIVE Q2 (2026-07-24..2026-08-07).
        resp_ovl = api.create_quarantine_order(
            {
                "premises_id": premises["id"], "species_code": "CATTLE",
                "disease_code": "BRUCELLOSIS",
                "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-10T00:00:00Z",
                "reason": "OVERLAPPING",
            },
            make_officer_headers("officer-a"),
        )
        validate_error(resp_ovl, ApiErrorId.ERR_QUARANTINE_WINDOW_CONFLICT)


class TestQuarantineLift:
    def test_quarantine_lift_segregation_of_duties(self, api, auditor_headers):
        """PRD §3.7: "The issuing officer's identity is stamped into
        `issued_by_user_id` from `X-User-ID`".
        PRD §3.7: "An officer may instead lift an `ACTIVE` order —
        lifting anything else yields `ERR_QUARANTINE_NOT_ACTIVE` (HTTP 409) —
        but never their own: if the lifter's `X-User-ID` equals the order's
        `issued_by_user_id`, the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and a second officer must
        perform the lift."
        PRD §3.7: "Either ending re-evaluates the premises identically: when
        the premises sits in `QUARANTINE_HOLD` and no other `ACTIVE` order
        covers that premises and species and no `ACTIVE` outbreak zone covers
        its county and species, the premises returns to `MONITORED`".

        Design: Corner/state_machines/quarantine_lift_segregation_of_duties
        """
        premises = create_premises(name="Ranch S19", initial_head_count=20)
        order = create_quarantine_order(
            premises["id"],
            start_at="2026-08-01T00:00:00Z", end_at="2026-08-15T00:00:00Z",
            reason="TRACE_EXPOSURE", officer_user_id="officer-a",
        )
        assert order["issued_by_user_id"] == "officer-a"
        assert get_premises(premises["id"])["disease_status"] == "QUARANTINE_HOLD"

        # The issuing officer may not lift their own order.
        resp_sod = api.lift_quarantine_order(
            order["id"], make_officer_headers("officer-a")
        )
        validate_error(resp_sod, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_premises(premises["id"])["disease_status"] == "QUARANTINE_HOLD"

        # A second officer performs the lift; the premises is restored.
        lifted = validate_success(
            api.lift_quarantine_order(order["id"], make_officer_headers("officer-b")), 200
        )
        assert lifted["status"] == "LIFTED"
        assert get_premises(premises["id"])["disease_status"] == "MONITORED"

    def test_quarantine_lift_twice_rejected(self, api):
        """PRD §3.7: "An officer may instead lift an `ACTIVE` order — lifting
        anything else yields `ERR_QUARANTINE_NOT_ACTIVE` (HTTP 409)".

        Design: Corner/state_machines/quarantine_lift_twice_rejected
        """
        premises = create_premises(name="Ranch S20", initial_head_count=20)
        order = create_quarantine_order(
            premises["id"],
            start_at="2026-08-01T00:00:00Z", end_at="2026-08-15T00:00:00Z",
            reason="TRACE_EXPOSURE", officer_user_id="officer-a",
        )
        lifted = validate_success(
            api.lift_quarantine_order(order["id"], make_officer_headers("officer-b")), 200
        )
        assert lifted["status"] == "LIFTED"
        resp2 = api.lift_quarantine_order(order["id"], make_officer_headers("officer-b"))
        validate_error(resp2, ApiErrorId.ERR_QUARANTINE_NOT_ACTIVE)


class TestQuarantineExpiry:
    def test_quarantine_expires_only_after_end_at(self, api, admin_headers):
        """PRD §3.7: "When the logical clock moves strictly past `end_at`, the
        order becomes `EXPIRED` on the next read or write that touches it, per
        the lazy rule of §2.4."
        PRD §2.4: "a premises read first materializes the `EXPIRED` evaluation
        of that premises' quarantine orders."

        Design: Corner/state_machines/quarantine_expires_only_after_end_at
        """
        premises = create_premises(name="Ranch S21", initial_head_count=20)
        create_quarantine_order(
            premises["id"],
            start_at="2026-08-01T00:00:00Z", end_at="2026-08-15T00:00:00Z",
            reason="TRACE_EXPOSURE", officer_user_id="officer-a",
        )

        # At clock == end_at the closed interval still holds: no expiry.
        set_clock("2026-08-15T00:00:00Z")
        assert get_premises(premises["id"])["disease_status"] == "QUARANTINE_HOLD"
        orders, _ = validate_paginated(
            api.list_quarantine_orders_for_premises(premises["id"], AUDITOR)
        )
        assert orders[0]["status"] == "ACTIVE", (
            "equality with end_at must NOT expire the closed-interval order"
        )

        # One day later the premises read materializes EXPIRED and restores.
        set_clock("2026-08-16T00:00:00Z")
        assert get_premises(premises["id"])["disease_status"] == "MONITORED"
        orders, _ = validate_paginated(
            api.list_quarantine_orders_for_premises(premises["id"], AUDITOR)
        )
        assert orders[0]["status"] == "EXPIRED"


class TestTestRecordResolution:
    def test_test_record_result_twice_rejected(self, api, admin_headers, lab_headers):
        """PRD §3.2: "Reporting the result is a one-way door: the `result`
        submitted by the `LabTechnician` moves the record from
        `RESULT_PENDING` to either `NEGATIVE` or `POSITIVE`, and a record that
        has already resolved rejects further result postings with
        `ERR_TEST_RECORD_NOT_PENDING` (HTTP 409)."

        Design: Corner/state_machines/test_record_result_twice_rejected
        """
        premises = create_premises(name="Ranch S22", initial_head_count=20)
        test = create_test_record(premises["id"], lab_reference="LAB-S22")
        first = report_result(test["id"], "NEGATIVE")
        assert first["result"] == "NEGATIVE"

        resp2 = api.report_test_result(test["id"], {"result": "POSITIVE"}, lab_headers)
        validate_error(resp2, ApiErrorId.ERR_TEST_RECORD_NOT_PENDING)


class TestPositiveTestCascade:
    def test_positive_test_infection_cascade(self, api, admin_headers, lab_headers):
        """PRD §3.2: "A `POSITIVE` result detonates the infection cascade,
        atomically within the same request: 1. The sampled premises'
        `disease_status` becomes `INFECTED`. 2. Unless an `ACTIVE` quarantine
        order already covers that premises and species, the system auto-creates
        a `QuarantineOrder` whose `start_at` is the logical clock, whose
        `end_at` is exactly 30 days later, whose `disease_code` is derived from
        the test's type, whose `reason` is the literal string
        `AUTO_POSITIVE_TEST:` followed by the test record's id, and whose
        `issued_by_user_id` is the literal string `system`. 3. Every
        certificate whose `origin_premises_id` is the newly infected premises
        and whose `status` is `DRAFT` or `PENDING_REVIEW` is rejected to
        `REJECTED` with `reject_reason` set to `AUTO_POSITIVE_TEST`."

        Design: Corner/state_machines/positive_test_infection_cascade
        """
        scenario = setup_standard_scenario()  # clock 2026-08-10, NEGATIVE test t1
        cert_a = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=5,
            test_record_id=scenario["test"]["id"],
            vaccination_date="2026-07-12T00:00:00Z",
        )
        cert_b = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=5,
            test_record_id=scenario["test"]["id"],
            vaccination_date="2026-07-12T00:00:00Z",
        )
        submit_certificate(cert_b["id"], scenario["vet"]["id"])
        # A second, still-pending test drawn the day before the clock.
        t2 = create_test_record(
            scenario["premises"]["id"],
            test_date="2026-08-09T00:00:00Z", lab_reference="LAB-S23-B",
        )

        resolved = report_result(t2["id"], "POSITIVE")
        assert resolved["result"] == "POSITIVE"

        assert get_premises(scenario["premises"]["id"])["disease_status"] == "INFECTED"

        orders, meta = validate_paginated(
            api.list_quarantine_orders_for_premises(scenario["premises"]["id"], AUDITOR)
        )
        assert meta["total_count"] == 1, "exactly one auto-created order"
        order = orders[0]
        assert_quarantine_order(order)
        assert order["status"] == "ACTIVE"
        assert order["reason"] == f"AUTO_POSITIVE_TEST:{t2['id']}"
        assert order["issued_by_user_id"] == "system"
        assert order["disease_code"] == "BRUCELLOSIS", (
            "disease_code is derived from the test's type"
        )
        assert order["start_at"] == "2026-08-10T00:00:00Z"
        assert order["end_at"] == "2026-09-09T00:00:00Z", "clock + 30 days"

        ca = get_certificate(cert_a["id"])
        assert ca["status"] == "REJECTED" and ca["reject_reason"] == "AUTO_POSITIVE_TEST"
        cb = get_certificate(cert_b["id"])
        assert cb["status"] == "REJECTED" and cb["reject_reason"] == "AUTO_POSITIVE_TEST"

    def test_positive_test_with_existing_quarantine_creates_no_duplicate(
        self, api, admin_headers
    ):
        """PRD §3.2: "Unless an `ACTIVE` quarantine order already covers
        that premises and species, the system auto-creates a `QuarantineOrder`
        whose `start_at` is the logical clock, whose `end_at` is exactly 30
        days later, whose `disease_code` is derived from the test's type, whose
        `reason` is the literal string `AUTO_POSITIVE_TEST:` followed by the
        test record's id, and whose `issued_by_user_id` is the literal string
        `system`."
        PRD §3.7: "Creation pushes the premises' `disease_status` to
        `QUARANTINE_HOLD` unless the premises is already `INFECTED`, in which
        case infection stands."

        Design: Corner/state_machines/positive_test_with_existing_quarantine_creates_no_duplicate
        """
        premises = create_premises(name="Ranch S24", initial_head_count=20)
        manual = create_quarantine_order(
            premises["id"],
            start_at="2026-08-01T00:00:00Z", end_at="2026-09-01T00:00:00Z",
            reason="TRACE_EXPOSURE", officer_user_id="officer-a",
        )
        test = create_test_record(
            premises["id"], test_date="2026-08-01T00:00:00Z", lab_reference="LAB-S24"
        )
        report_result(test["id"], "POSITIVE")

        assert get_premises(premises["id"])["disease_status"] == "INFECTED", (
            "the infection cascade still fires"
        )
        orders, meta = validate_paginated(
            api.list_quarantine_orders_for_premises(premises["id"], AUDITOR)
        )
        assert meta["total_count"] == 1, "no AUTO_POSITIVE_TEST duplicate may be created"
        assert orders[0]["id"] == manual["id"]
        assert orders[0]["reason"] == "TRACE_EXPOSURE"


class TestPremisesAccredit:
    def test_premises_accredit_happy_and_repeat_rejected(self, api, officer_headers):
        """PRD §3.1: "A `StateVetOfficer` may grant accredited-free standing to
        a premises by accrediting it, which succeeds only while
        `disease_status` is `MONITORED` and no `ACTIVE` quarantine order covers
        that premises and species — otherwise the attempt is rejected with
        `ERR_PREMISES_NOT_ACCREDITABLE` (HTTP 409) — and sets `disease_status`
        to `ACCREDITED_FREE`."

        Design: Corner/state_machines/premises_accredit_happy_and_repeat_rejected
        """
        prem1 = create_premises(name="Ranch S28a", initial_head_count=20)
        prem2 = create_premises(name="Ranch S28b", initial_head_count=20)
        create_quarantine_order(
            prem2["id"],
            start_at="2026-08-01T00:00:00Z", end_at="2026-08-15T00:00:00Z",
            reason="TRACE_EXPOSURE", officer_user_id="officer-a",
        )

        accredited = validate_success(api.accredit_premises(prem1["id"], officer_headers), 200)
        assert accredited["disease_status"] == "ACCREDITED_FREE"

        validate_error(
            api.accredit_premises(prem1["id"], officer_headers),
            ApiErrorId.ERR_PREMISES_NOT_ACCREDITABLE,
        )
        validate_error(
            api.accredit_premises(prem2["id"], officer_headers),
            ApiErrorId.ERR_PREMISES_NOT_ACCREDITABLE,
        )
