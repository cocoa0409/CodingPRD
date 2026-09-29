"""Entity shapes: creation defaults, derived fields, server-minted audit fields,
immutability and reference integrity for the EAS Compliance API.

Every test builds its own preconditions: the harness restarts the server before
each test, so each one starts against an empty database with the logical clock at
its startup default 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    INSPECTOR,
    TEST_DEFAULTS,
    ApiErrorId,
    assert_immutable_audit_fields,
    assert_matched_rule,
    assert_relay_rule,
    assert_state_plan,
    assert_station,
    assert_test_log_entry,
    assert_versioned_audit_fields,
    assert_wireless_alert_notice,
    create_active_plan,
    create_plan,
    create_ready_device,
    create_relay_rule,
    factories,
    is_iso8601_timestamp,
    is_valid_uuid,
    log_alert,
    make_engineer_headers,
    monitoring_assignment_payload,
    record_wireless_notice,
    register_station,
    relay_rule_payload,
    set_clock,
    setup_ready_test_event,
    setup_station,
    state_plan_payload,
    station_payload,
    station_version,
    validate_error,
    validate_paginated,
    validate_success,
    wireless_alert_notice_payload,
)

# A syntactically valid UUID the server never minted.
UNKNOWN_PLAN_ID = "11111111-2222-4333-8444-555555555555"
UNKNOWN_PLAN_ID_ON_CREATE = "99999999-8888-4777-8666-555555555555"


def _instant(value: str) -> str:
    """Whole-second prefix of an ISO 8601 UTC timestamp, so a comparison does not
    depend on whether the server emitted the optional fractional digits."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    return value[:19]


class TestCreationDefaultsAndDerivedFields:
    def test_state_plan_create_derives_required_source_count_and_opens_in_draft(self, api):
        """PRD §3.1: "At create time the server derives `required_source_count` as the number of entries in `required_source_types`, sets `status` to `DRAFT`, and leaves both `activated_at` and `superseded_at` null."
        PRD §4: "Operations that create a new stored row return `201 Created`; operations that mutate an existing row, run a computation, drive a state transition or set the logical clock return `200 OK`."

        Design: Corner/entities/plan_creation_returns_draft_with_required_source_count_derived
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = state_plan_payload(
            state_code="KS",
            plan_version_label="2026-R1",
            required_source_types=["PEP", "NWS", "SATELLITE"],
            mandatory_relay_event_codes=["EAN", "TOR"],
        )

        response = api.create_state_plan(payload, ADMIN)
        created = validate_success(response, 201)

        assert response.json()["response_type"] == "object", (
            "a single created resource is returned as an object"
        )
        assert_state_plan(created)
        assert created["state_code"] == "KS"
        assert created["plan_version_label"] == "2026-R1"
        assert created["required_source_types"] == ["PEP", "NWS", "SATELLITE"]
        assert created["mandatory_relay_event_codes"] == ["EAN", "TOR"]
        assert created["required_source_count"] == 3, (
            f"expected required_source_count 3, got {created['required_source_count']}"
        )
        assert created["status"] == "DRAFT", f"expected DRAFT, got {created['status']}"
        assert created["activated_at"] is None, "a DRAFT plan has activated_at null"
        assert created["superseded_at"] is None, "a DRAFT plan has superseded_at null"

        fetched = validate_success(api.get_state_plan(created["id"], INSPECTOR))
        assert fetched["required_source_count"] == 3
        assert fetched["status"] == "DRAFT"
        assert fetched["activated_at"] is None
        assert fetched["superseded_at"] is None
        assert fetched["required_source_types"] == ["PEP", "NWS", "SATELLITE"]
        assert fetched["mandatory_relay_event_codes"] == ["EAN", "TOR"]

    def test_station_read_reports_provisioning_defaults(self, api):
        """PRD §3.2: "A freshly registered station has `compliance_posture` `PROVISIONING`, `compliance_score` and `compliance_variant_applied` both null, `accessible_source_count` 0, `silent_assignment_count` 0, `penalty_points_total` 0, `plan_revalidation_required` false, `public_file_document_count` 0, `last_log_review_at` null and `version` 1."

        Design: Corner/entities/station_retrieval_echoes_stored_fields_and_provisioning_defaults
        """
        plan = create_active_plan(("PEP",))
        station = register_station(
            plan["id"],
            call_sign="KWEA",
            service_type="TV",
            engineer_user_ids=["eng-1", "eng-2"],
            certification_officer_user_id="cert-1",
        )

        fetched = validate_success(api.get_station(station["id"], make_engineer_headers("eng-1")))

        assert_station(fetched)
        assert fetched["state_plan_id"] == plan["id"]
        assert fetched["call_sign"] == "KWEA"
        assert fetched["service_type"] == "TV"
        assert fetched["engineer_user_ids"] == ["eng-1", "eng-2"]
        assert fetched["certification_officer_user_id"] == "cert-1"
        assert fetched["compliance_posture"] == "PROVISIONING", (
            f"expected PROVISIONING, got {fetched['compliance_posture']}"
        )
        assert fetched["compliance_score"] is None, "no recompute event has fired yet"
        assert fetched["compliance_variant_applied"] is None
        assert fetched["accessible_source_count"] == 0
        assert fetched["silent_assignment_count"] == 0
        assert fetched["penalty_points_total"] == pytest.approx(0, abs=0.01)
        assert fetched["public_file_document_count"] == 0
        assert fetched["plan_revalidation_required"] is False
        assert fetched["last_log_review_at"] is None
        assert fetched["version"] == 1, f"expected version 1, got {fetched['version']}"

    def test_relay_rule_omitted_forward_delay_stores_zero_and_is_copied_to_the_alert(self, api):
        """PRD §3.1: "An optional `forward_delay_seconds` between 0 and 600 inclusive states how long forwarding is deferred when this rule is the one selected; when the field is omitted it is 0."
        PRD §3.1: "New rules begin with `status` set to `ACTIVE`."
        PRD §3.5: "When a rule is selected, the alert moves `RECEIVED` → `RELAY_PENDING`, `matched_relay_rule_id` is set to that rule's `id`, and `forward_delay_seconds_applied` is copied from the rule's `forward_delay_seconds`."
        PRD §3.5: "The effective `relay_class_applied` is `MANDATORY` when either the selected rule's `relay_class` is `MANDATORY` **or** the alert's `event_code` appears in the governing plan's `mandatory_relay_event_codes`; otherwise it is `OPTIONAL`."

        Design: Corner/entities/relay_rule_forward_delay_defaults_to_zero_when_omitted
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_active_plan(("PEP",), mandatory_relay_event_codes=())
        station = register_station(plan["id"], call_sign="KWEA", service_type="TV")

        payload = relay_rule_payload(
            plan["id"], event_code="RWT", fips_codes=[], relay_class="OPTIONAL", priority=40
        )
        payload.pop("forward_delay_seconds")
        rule = validate_success(api.create_relay_rule(payload, ADMIN), 201)

        assert_relay_rule(rule)
        assert rule["forward_delay_seconds"] == 0, (
            f"omitted forward_delay_seconds must store 0, got {rule['forward_delay_seconds']!r}"
        )
        assert rule["status"] == "ACTIVE"
        assert rule["specificity"] == 1, "an empty fips_codes array is statewide"

        alert = log_alert(
            station["id"],
            "2026-08-01T00:00:00Z",
            event_code="RWT",
            originator_sequence="KSDEF-0001",
            fips_codes=["20173"],
        )
        assert_matched_rule(alert, rule["id"], "OPTIONAL", 0)

    def test_relay_rule_specificity_derived_from_the_fips_scope(self, api):
        """PRD §3.1: "The server derives `specificity` from the location scope: 2 when `fips_codes` holds at least one entry, meaning the rule is county-scoped, and 1 when `fips_codes` is empty, meaning the rule is statewide."

        Design: Corner/entities/relay_rule_specificity_computed_from_fips_codes
        """
        plan = create_active_plan(("PEP",))

        county_rule = create_relay_rule(
            plan["id"],
            event_code="TOR",
            fips_codes=["20173", "20177"],
            relay_class="MANDATORY",
            priority=10,
            forward_delay_seconds=30,
        )
        statewide_rule = create_relay_rule(
            plan["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=20,
            forward_delay_seconds=0,
        )

        county = validate_success(api.get_relay_rule(county_rule["id"], INSPECTOR))
        statewide = validate_success(api.get_relay_rule(statewide_rule["id"], INSPECTOR))

        assert_relay_rule(county)
        assert_relay_rule(statewide)
        assert county["fips_codes"] == ["20173", "20177"]
        assert county["specificity"] == 2, (
            f"a county-scoped rule stores specificity 2, got {county['specificity']}"
        )
        assert statewide["fips_codes"] == []
        assert statewide["specificity"] == 1, (
            f"a statewide rule stores specificity 1, got {statewide['specificity']}"
        )
        assert county["status"] == "ACTIVE" and statewide["status"] == "ACTIVE"
        assert county["version"] == 1 and statewide["version"] == 1


class TestServerMintedAuditFields:
    def test_state_plan_audit_fields_are_server_minted_and_version_increments(self, api):
        """PRD §2.5: "Every stored row carries an `id` that the server mints as a UUID with no type prefix, and a `created_at` that is an ISO 8601 UTC timestamp with three fractional digits taken from the logical clock at insert time."
        PRD §2.5: "Most resources — state plans, stations, relay rules, EAS devices, monitoring assignments, equipment outages, alert events, test events, filing records and inspection requests — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the row, and `version`, an integer that starts at 1 when the row is created and increases by one on every mutation of that row."
        PRD §3.1: "Activation stamps `activated_at` from the logical clock and then fires the plan-supersede cascade described in §2.11: any other plan for the same `state_code` sitting in `ACTIVE` is pushed `ACTIVE` → `SUPERSEDED`, its `superseded_at` is stamped, its stations get `plan_revalidation_required` set to true and rescored, and any `RESPONDED` inspection request of those stations falls back to `RESPONSE_DRAFTED`."

        Design: Corner/entities/state_plan_system_fields_minted_by_the_server
        """
        set_clock("2026-08-01T00:00:00Z")
        created = create_plan(("PEP",))

        assert_versioned_audit_fields(created)
        assert is_valid_uuid(created["id"]), f"id must be a bare UUID, got {created['id']!r}"
        assert "_" not in created["id"], "the id carries no type prefix"
        assert created["version"] == 1, f"version starts at 1, got {created['version']}"
        assert _instant(created["created_at"]) == "2026-08-01T00:00:00", (
            f"created_at comes from the logical clock, got {created['created_at']}"
        )

        set_clock("2026-08-05T09:00:00Z")
        activated = validate_success(api.activate_state_plan(created["id"], ADMIN))

        assert activated["version"] == created["version"] + 1, (
            f"the activate mutation increments version, got {activated['version']}"
        )
        assert _instant(activated["created_at"]) == "2026-08-01T00:00:00", (
            "created_at is not touched by a later mutation"
        )
        assert _instant(activated["updated_at"]) == "2026-08-05T09:00:00", (
            f"updated_at is refreshed on mutation, got {activated['updated_at']}"
        )
        assert activated["status"] == "ACTIVE"
        assert _instant(activated["activated_at"]) == "2026-08-05T09:00:00", (
            f"activated_at is stamped from the logical clock, got {activated['activated_at']}"
        )

        fetched = validate_success(api.get_state_plan(created["id"], ADMIN))
        assert fetched["version"] == 2
        assert _instant(fetched["created_at"]) == "2026-08-01T00:00:00"
        assert _instant(fetched["updated_at"]) == "2026-08-05T09:00:00"
        assert _instant(fetched["activated_at"]) == "2026-08-05T09:00:00"


class TestImmutableResources:
    def test_wireless_alert_notice_carries_no_version_and_no_updated_at(self, api):
        """PRD §2.5: "Two resources are immutable once written and therefore carry **neither** `updated_at` **nor** `version`: `WirelessAlertNotice` and `TestLogEntry`."
        PRD §2.5: "Both expose only `id` and `created_at` among the audit fields."

        Design: Corner/entities/wireless_alert_notice_is_immutable_with_no_version_field
        """
        set_clock("2026-08-12T13:00:00Z")
        plan = create_active_plan(("PEP",))
        station = register_station(plan["id"], call_sign="KWEA", service_type="TV")

        payload = wireless_alert_notice_payload(
            station["id"],
            "2026-08-12T12:00:00Z",
            originator_sequence="KSIMM-0001",
            event_code="TOR",
            fips_codes=["20173"],
        )
        notice = validate_success(api.create_wireless_alert_notice(payload, ADMIN), 201)

        assert_wireless_alert_notice(notice)
        assert_immutable_audit_fields(notice)

        fetched = validate_success(api.get_wireless_alert_notice(notice["id"], INSPECTOR))
        assert_immutable_audit_fields(fetched)
        assert _instant(fetched["wea_sent_at"]) == "2026-08-12T12:00:00"
        assert fetched["fips_codes"] == ["20173"]

    def test_second_wireless_alert_notice_for_the_same_triple_is_an_independent_row(self, api):
        """PRD §3.5: "Recording a notice mutates no other row; it simply enters phase B for every alert logged afterwards."
        PRD §2.5: "A wireless alert notice is a recorded fact about a carrier transmission and is never edited; a test log line is append-only, which is why the penalty calculation in §3.7 can treat the log as a fixed, status-free set of rows."
        PRD §3.5: "Notices can be listed filtered by `station_id`, `originator_sequence` and `event_code`."

        Design: Corner/entities/wireless_alert_notice_is_immutable_with_no_version_field
        """
        set_clock("2026-08-12T13:00:00Z")
        plan = create_active_plan(("PEP",))
        station = register_station(plan["id"], call_sign="KWEA", service_type="TV")

        first = record_wireless_notice(
            station["id"],
            "2026-08-12T12:00:00Z",
            originator_sequence="KSIMM-0001",
            event_code="TOR",
            fips_codes=["20173"],
        )
        second = record_wireless_notice(
            station["id"],
            "2026-08-12T12:30:00Z",
            originator_sequence="KSIMM-0001",
            event_code="TOR",
            fips_codes=["20177"],
        )

        assert first["id"] != second["id"], "the second notice is its own row"

        reread = validate_success(api.get_wireless_alert_notice(first["id"], INSPECTOR))
        assert _instant(reread["wea_sent_at"]) == "2026-08-12T12:00:00", (
            "the second notice did not overwrite the first"
        )
        assert reread["fips_codes"] == ["20173"]

        rows, meta = validate_paginated(
            api.list_wireless_alert_notices(
                INSPECTOR,
                params={"station_id": station["id"], "originator_sequence": "KSIMM-0001"},
            )
        )
        assert meta["total_count"] == 2, (
            f"the immutable notice log is additive, got total_count {meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {first["id"], second["id"]}

    def test_test_log_entry_is_append_only_and_records_the_acting_operator(self, api):
        """PRD §2.5: "Two resources are immutable once written and therefore carry **neither** `updated_at` **nor** `version`: `WirelessAlertNotice` and `TestLogEntry`."
        PRD §3.6: "An accepted line stamps `logged_at` from the logical clock and records the acting `X-User-ID` as `logged_by_user_id` — the value the segregation-of-duties check of §2.12 later compares against."
        PRD §3.6: "It raises the event's `logged_entry_count` by one."
        PRD §3.6: "`source_call_sign` is required on a `RECEIPT` line, naming the monitored source's call sign, and is forbidden on a `TRANSMISSION` line; violating either half of that rule is a schema failure."

        Design: Corner/entities/test_log_entry_carries_no_version_and_no_mutating_endpoint
        """
        ctx = setup_ready_test_event(engineer_user_ids=["eng-1", "eng-2"])

        entry = validate_success(
            api.create_test_log_entry(
                factories.test_log_entry_payload(ctx["test_event_id"], ctx["device_id"], "TRANSMISSION"),
                make_engineer_headers("eng-2"),
            ),
            201,
        )

        assert_test_log_entry(entry)
        assert_immutable_audit_fields(entry)
        assert entry["logged_by_user_id"] == "eng-2", (
            f"logged_by_user_id comes from the acting header, got {entry['logged_by_user_id']!r}"
        )
        assert _instant(entry["logged_at"]) == "2026-08-12T00:30:00", (
            f"logged_at is stamped from the logical clock, got {entry['logged_at']}"
        )
        assert not entry.get("source_call_sign"), (
            "source_call_sign is forbidden on a TRANSMISSION line"
        )

        event = validate_success(api.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["logged_entry_count"] == 1, (
            f"expected logged_entry_count 1, got {event['logged_entry_count']}"
        )

    def test_test_log_entry_retention_is_frozen_at_append_time(self, api):
        """PRD §3.6: "The base term is 1095 days — three years — when the owning event's `test_type` is `NATIONAL`, and 730 days — two years — for `WEEKLY` and `MONTHLY` alike."
        PRD §3.6: "The resulting figure is stored as `retention_days_applied`, and `retention_until` is `logged_at` advanced by that many whole calendar days in UTC."

        Design: Corner/entities/test_log_entry_carries_no_version_and_no_mutating_endpoint
        """
        ctx = setup_ready_test_event(engineer_user_ids=["eng-1", "eng-2"], test_type="WEEKLY")

        entry = validate_success(
            api.create_test_log_entry(
                factories.test_log_entry_payload(ctx["test_event_id"], ctx["device_id"], "TRANSMISSION"),
                make_engineer_headers("eng-2"),
            ),
            201,
        )

        assert entry["retention_days_applied"] == 730, (
            f"a WEEKLY test retains for 730 days, got {entry['retention_days_applied']}"
        )
        assert _instant(entry["logged_at"]) == "2026-08-12T00:30:00"
        assert _instant(entry["retention_until"]) == "2028-08-11T00:30:00", (
            f"expected logged_at plus 730 whole days, got {entry['retention_until']}"
        )

        reread = validate_success(api.get_test_log_entry(entry["id"], INSPECTOR))
        assert reread["retention_days_applied"] == 730
        assert _instant(reread["retention_until"]) == "2028-08-11T00:30:00"


class TestListingAndRetrieval:
    def test_relay_rule_list_filters_by_plan_before_paginating(self, api):
        """PRD §2.3: "Every list response repeats `limit` and `offset` in the `meta` object alongside `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current page)."
        PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."
        PRD §3.1: "Rules can be listed filtered by `state_plan_id`, `event_code`, `relay_class` and `status`."

        Design: Corner/entities/relay_rule_listing_paginates_and_filters_by_plan
        """
        set_clock("2026-08-01T00:00:00Z")
        plan_ks = create_active_plan(("PEP",), state_code="KS", plan_version_label="2026-R1")
        plan_ne = create_active_plan(("PEP",), state_code="NE", plan_version_label="2026-R1")

        # Distinct created_at instants so the ascending order is unambiguous.
        set_clock("2026-08-01T01:00:00Z")
        rule_one = create_relay_rule(
            plan_ks["id"],
            event_code="TOR",
            fips_codes=["20173"],
            relay_class="MANDATORY",
            priority=10,
            forward_delay_seconds=30,
        )
        set_clock("2026-08-01T02:00:00Z")
        rule_two = create_relay_rule(
            plan_ks["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=20,
            forward_delay_seconds=0,
        )
        set_clock("2026-08-01T03:00:00Z")
        rule_three = create_relay_rule(
            plan_ks["id"],
            event_code="RWT",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=30,
            forward_delay_seconds=0,
        )
        set_clock("2026-08-01T04:00:00Z")
        rule_other_plan = create_relay_rule(
            plan_ne["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="MANDATORY",
            priority=10,
            forward_delay_seconds=0,
        )

        first_rows, first_meta = validate_paginated(
            api.list_relay_rules(
                INSPECTOR, params={"state_plan_id": plan_ks["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(first_rows) == 2, f"expected 2 rows on the first page, got {len(first_rows)}"
        assert first_meta["total_count"] == 3, (
            f"total_count counts the filtered rows, got {first_meta['total_count']}"
        )
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert [row["id"] for row in first_rows] == [rule_one["id"], rule_two["id"]]

        second_rows, second_meta = validate_paginated(
            api.list_relay_rules(
                INSPECTOR, params={"state_plan_id": plan_ks["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(second_rows) == 1, f"expected 1 row on the second page, got {len(second_rows)}"
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2
        assert [row["id"] for row in second_rows] == [rule_three["id"]]

        paged_ids = {row["id"] for row in first_rows} | {row["id"] for row in second_rows}
        assert rule_other_plan["id"] not in paged_ids, (
            "the state_plan_id filter is applied before the page window is taken"
        )

        filtered_rows, filtered_meta = validate_paginated(
            api.list_relay_rules(
                INSPECTOR,
                params={
                    "state_plan_id": plan_ks["id"],
                    "event_code": "TOR",
                    "status": "ACTIVE",
                },
            )
        )
        assert filtered_meta["total_count"] == 2, (
            f"two ACTIVE TOR rules match, got total_count {filtered_meta['total_count']}"
        )
        assert filtered_meta["has_more"] is False
        assert {row["id"] for row in filtered_rows} == {rule_one["id"], rule_two["id"]}

    def test_state_plan_get_with_unknown_id_returns_not_found(self, api):
        """PRD §2.8: "**Existence** — the 404 family. Applies to every endpoint that carries an id in its path or a foreign-key id in its body."
        PRD §2.9: "Each entity type has its own not-found code so that a caller can tell which reference broke: `ERR_STATE_PLAN_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_RELAY_RULE_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, `ERR_ALERT_EVENT_NOT_FOUND`, `ERR_WEA_NOTICE_NOT_FOUND`, `ERR_TEST_EVENT_NOT_FOUND`, `ERR_LOG_ENTRY_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and `ERR_INSPECTION_NOT_FOUND`."
        PRD §2.9: "All twelve carry HTTP 404."

        Design: Corner/entities/state_plan_get_with_unknown_id_not_found
        """
        existing = create_plan(("PEP",))

        response = api.get_state_plan(UNKNOWN_PLAN_ID, ADMIN)
        validate_error(response, ApiErrorId.ERR_STATE_PLAN_NOT_FOUND, 404)
        assert response.json()["response_type"] == "error", (
            "a 4xx response uses the error envelope"
        )

        still_there = validate_success(api.get_state_plan(existing["id"], ADMIN))
        assert still_there["id"] == existing["id"], "the unrelated plan is untouched"
        assert still_there["status"] == "DRAFT"


class TestRequestShapeAndReferenceIntegrity:
    def test_station_create_without_service_type_is_rejected(self, api):
        """PRD §2.8: "**Request schema** — `ERR_INVALID_REQUEST`, 400. Applies to every write endpoint. This check covers presence of every required body field, membership of every enum value in its declared set, numeric ranges, array shapes, the requirement that `window_start_at` be strictly earlier than `window_end_at`, and the rule that `source_call_sign` is present on a `RECEIPT` log line and absent on a `TRANSMISSION` log line."
        PRD §3.2: "Stations can be listed filtered by `state_plan_id`, `compliance_posture` and `call_sign`."

        Design: Corner/entities/station_create_without_service_type_returns_invalid_request
        """
        plan = create_active_plan(("PEP",))

        payload = station_payload(
            plan["id"],
            call_sign="KWEA",
            engineer_user_ids=["eng-1"],
            certification_officer_user_id="cert-1",
        )
        payload.pop("service_type")

        validate_error(
            api.create_station(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST, 400
        )

        _rows, meta = validate_paginated(
            api.list_stations(ADMIN, params={"state_plan_id": plan["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the rejected create persisted nothing, got total_count {meta['total_count']}"
        )

    def test_station_create_with_unknown_plan_id_returns_not_found(self, api):
        """PRD §2.8: "**Existence** — the 404 family. Applies to every endpoint that carries an id in its path or a foreign-key id in its body."
        PRD §2.9: "Each entity type has its own not-found code so that a caller can tell which reference broke: `ERR_STATE_PLAN_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_RELAY_RULE_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, `ERR_ALERT_EVENT_NOT_FOUND`, `ERR_WEA_NOTICE_NOT_FOUND`, `ERR_TEST_EVENT_NOT_FOUND`, `ERR_LOG_ENTRY_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and `ERR_INSPECTION_NOT_FOUND`."
        PRD §2.9: "All twelve carry HTTP 404."

        Design: Corner/entities/station_create_with_unknown_plan_id_not_found
        """
        create_active_plan(("PEP",))

        payload = station_payload(
            UNKNOWN_PLAN_ID_ON_CREATE,
            call_sign="KWEZ",
            service_type="AM",
            engineer_user_ids=["eng-1"],
            certification_officer_user_id="cert-1",
        )
        validate_error(
            api.create_station(payload, ADMIN), ApiErrorId.ERR_STATE_PLAN_NOT_FOUND, 404
        )

        _rows, meta = validate_paginated(api.list_stations(ADMIN, params={"call_sign": "KWEZ"}))
        assert meta["total_count"] == 0, (
            f"the call sign is still free, got total_count {meta['total_count']}"
        )

    def test_monitoring_assignment_naming_another_stations_device_is_rejected(self, api):
        """PRD §3.3: "The referenced unit must currently be in `READY`, otherwise the create is rejected with `ERR_DEVICE_NOT_READY`, and the unit's `station_id` must equal the `station_id` in the payload, otherwise `ERR_DEVICE_STATION_MISMATCH`."
        PRD §2.7: "A successful create increments the station's `version` by one, so a client that reads the station once and then creates two assignments must re-read between them."

        Design: Corner/entities/cross_station_device_reference_rejected_on_flat_topology
        """
        ctx = setup_station(required_source_types=("PEP",), call_sign="KWEA")
        other_station = register_station(
            ctx["plan_id"], call_sign="KWEB", service_type="FM"
        )
        other_device = create_ready_device(other_station["id"])

        version_before = station_version(ctx["station_id"])
        payload = monitoring_assignment_payload(
            ctx["station_id"],
            other_device["id"],
            version_before,
            source_type="NWS",
            source_call_sign="WXNWS",
        )
        validate_error(
            api.create_monitoring_assignment(payload, ENGINEER),
            ApiErrorId.ERR_DEVICE_STATION_MISMATCH,
            422,
        )

        _rows, meta = validate_paginated(
            api.list_monitoring_assignments(ADMIN, params={"station_id": ctx["station_id"]})
        )
        assert meta["total_count"] == 1, (
            f"only the legitimate assignment survives, got total_count {meta['total_count']}"
        )
        assert station_version(ctx["station_id"]) == version_before, (
            "only a successful create increments the station's version"
        )

    def test_test_log_entry_naming_another_stations_device_is_rejected(self, api):
        """PRD §3.6: "The named unit must belong to the event's station, otherwise `ERR_DEVICE_STATION_MISMATCH`."

        Design: Corner/entities/cross_station_device_reference_rejected_on_flat_topology
        """
        ctx = setup_station(required_source_types=("PEP",), call_sign="KWEA")
        other_station = register_station(
            ctx["plan_id"], call_sign="KWEB", service_type="FM"
        )
        other_device = create_ready_device(other_station["id"])
        ctx = setup_ready_test_event(ctx)

        validate_error(
            api.create_test_log_entry(
                factories.test_log_entry_payload(ctx["test_event_id"], other_device["id"], "TRANSMISSION"),
                ENGINEER,
            ),
            ApiErrorId.ERR_DEVICE_STATION_MISMATCH,
            422,
        )

        event = validate_success(api.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["logged_entry_count"] == 0, (
            f"the rejected line was not appended, got {event['logged_entry_count']}"
        )
        assert event["status"] == "READY", f"the event is still READY, got {event['status']}"


class TestMeasurementConstraints:
    @pytest.mark.parametrize(
        "measurements",
        [
            {"visual_crawl_seconds": 601, "audio_loudness_lufs": -24.0, "caption_interaction": "NONE"},
            {"visual_crawl_seconds": 60, "audio_loudness_lufs": 1.0, "caption_interaction": "NONE"},
            {
                "visual_crawl_seconds": 60,
                "audio_loudness_lufs": -24.0,
                "caption_interaction": "CAPTIONS_OFF",
            },
        ],
        ids=["crawl_above_600", "loudness_above_zero", "unknown_caption_interaction"],
    )
    def test_verify_accessibility_rejects_out_of_range_measurements(self, api, measurements):
        """PRD §3.5: "A `StationEngineer` supplies three measurements: `visual_crawl_seconds`, an integer from 0 to 600 inclusive giving the measured on-screen crawl duration; `audio_loudness_lufs`, a number from -60.0 to 0.0 inclusive giving measured loudness; and `caption_interaction`, one of `NONE`, `CAPTION_SUPPRESSED` or `CRAWL_OVERLAP`, describing how the crawl interacted with closed captions."
        PRD §2.8: "**Request schema** — `ERR_INVALID_REQUEST`, 400. Applies to every write endpoint. This check covers presence of every required body field, membership of every enum value in its declared set, numeric ranges, array shapes, the requirement that `window_start_at` be strictly earlier than `window_end_at`, and the rule that `source_call_sign` is present on a `RECEIPT` log line and absent on a `TRANSMISSION` log line."
        PRD §3.5: "The accessibility dimension is `accessibility_state`, which begins at `ACCESSIBILITY_UNVERIFIED` and ends at either `ACCESSIBILITY_PASSED` or `ACCESSIBILITY_FAILED`."

        Design: Corner/entities/verify_accessibility_out_of_range_measurements_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_active_plan(("PEP",))
        station = register_station(plan["id"], call_sign="KWEA", service_type="TV")
        alert = log_alert(
            station["id"],
            "2026-08-01T00:00:00Z",
            event_code="TOR",
            originator_sequence="KSRNG-0001",
            fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
        )

        validate_error(
            api.verify_accessibility(alert["id"], measurements, ENGINEER),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        reread = validate_success(api.get_alert_event(alert["id"], INSPECTOR))
        assert reread["accessibility_state"] == "ACCESSIBILITY_UNVERIFIED", (
            f"a rejected measurement leaves the dimension unverified, "
            f"got {reread['accessibility_state']}"
        )

    def test_verify_accessibility_accepts_the_extreme_legal_bounds(self, api):
        """PRD §3.5: "A `StationEngineer` supplies three measurements: `visual_crawl_seconds`, an integer from 0 to 600 inclusive giving the measured on-screen crawl duration; `audio_loudness_lufs`, a number from -60.0 to 0.0 inclusive giving measured loudness; and `caption_interaction`, one of `NONE`, `CAPTION_SUPPRESSED` or `CRAWL_OVERLAP`, describing how the crawl interacted with closed captions."
        PRD §3.5: "The loudness excess in loudness units is the absolute difference between `audio_loudness_lufs` and the -24.0 LUFS target, reduced by the 2.0-unit tolerance and floored at zero — so a reading of -25.0 is inside tolerance and yields zero excess, while a reading of -30.0 deviates by 6.0 and yields an excess of 4.0."
        PRD §3.5: "Add the base term, the capped coupling term and the caption penalty; take the smaller of that sum and the overall deficiency ceiling of 8.00 points; and round the result half-up to two decimal places."
        PRD §3.5: "The verdict is inclusive at the boundary: `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_PASSED` when `accessibility_deficiency_points` is 1.00 or less, and `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_FAILED` when it is strictly greater than 1.00."

        Design: Corner/entities/verify_accessibility_out_of_range_measurements_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_active_plan(("PEP",))
        station = register_station(plan["id"], call_sign="KWEA", service_type="TV")
        alert = log_alert(
            station["id"],
            "2026-08-01T00:00:00Z",
            event_code="TOR",
            originator_sequence="KSRNG-0001",
            fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
        )

        for rejected in (
            {"visual_crawl_seconds": 601, "audio_loudness_lufs": -24.0, "caption_interaction": "NONE"},
            {"visual_crawl_seconds": 60, "audio_loudness_lufs": 1.0, "caption_interaction": "NONE"},
            {
                "visual_crawl_seconds": 60,
                "audio_loudness_lufs": -24.0,
                "caption_interaction": "CAPTIONS_OFF",
            },
        ):
            validate_error(
                api.verify_accessibility(alert["id"], rejected, ENGINEER),
                ApiErrorId.ERR_INVALID_REQUEST,
                400,
            )

        verified = validate_success(
            api.verify_accessibility(
                alert["id"],
                {
                    "visual_crawl_seconds": 600,
                    "audio_loudness_lufs": -60.0,
                    "caption_interaction": "NONE",
                },
                ENGINEER,
            )
        )

        assert verified["visual_crawl_seconds"] == 600
        assert verified["audio_loudness_lufs"] == pytest.approx(-60.0, abs=0.01)
        assert verified["caption_interaction"] == "NONE"
        assert verified["accessibility_deficiency_points"] == pytest.approx(3.40, abs=0.01), (
            "zero crawl shortfall plus a loudness excess of 34.0 scores 3.40 points, got "
            f"{verified['accessibility_deficiency_points']}"
        )
        assert verified["accessibility_state"] == "ACCESSIBILITY_FAILED", (
            f"3.40 is strictly greater than 1.00, got {verified['accessibility_state']}"
        )
