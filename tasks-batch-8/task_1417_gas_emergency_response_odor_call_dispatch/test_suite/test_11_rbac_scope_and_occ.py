"""RBAC denials, read scoping, and optimistic concurrency control
(PRD §2.1, §2.6, §2.8)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    setup_territory, setup_territory_technician, intake_call, triage, dispatch,
    arrive, set_clock, get_incident, record_reading,
    create_emergency_call_payload, create_technician_payload,
    setup_on_scene_incident, setup_monitoring_incident,
    TEST_USERS, make_technician_headers, make_supervisor_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


class TestRbacExclusiveOperations:
    def test_technician_cannot_triage_returns_403(self, api):
        """PRD §2.1: "A request whose role is simply not permitted on the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." §3.3: "A `Dispatcher` or `Supervisor` confirms or sets
        the priority" — triage is not a FieldTechnician capability (§2.1 role
        roster, §4 endpoint table).

        Design: Corner/rbac/technician_cannot_triage_returns_403
        """
        terr = setup_territory()
        tech = validate_success(api_client.create_technician(
            create_technician_payload(full_name="Zoe T", badge_number="B115",
                                      home_territory_id=terr["id"]), ADMIN),
            expected_status=201)
        call = intake_call(terr["id"], address_line="7 Triage St",
                           caller_name="Z7", caller_phone="555-0231")

        resp = api_client.triage_incident(call["incident_id"], {"priority": "P2"},
                                          make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        assert get_incident(call["incident_id"])["lifecycle_status"] == "NEW"

    def test_regulator_cannot_write_returns_403(self, api):
        """PRD §2.1: "a `Regulator` never performs writes other than accepting
        or rejecting a submitted report" and "A request whose role is simply
        not permitted on the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/regulator_cannot_write_returns_403
        """
        terr = setup_territory()
        resp = api_client.create_emergency_call(
            create_emergency_call_payload(
                caller_name="Z8", caller_phone="555-0232",
                address_line="8 Reg St", territory_id=terr["id"],
                location_context="OUTSIDE_STRUCTURE"),
            REGULATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestReadScoping:
    def test_regulator_reading_open_incident_returns_403(self, api):
        """PRD §2.1: "A `Regulator` may read only incidents in `CLOSED` or
        `MERGED` lifecycle status and only regulatory reports that are not in
        `DRAFT`; any other access is rejected with
        `ERR_REGULATOR_SCOPE_RESTRICTED` (HTTP 403)".

        Design: Corner/rbac/regulator_reading_open_incident_returns_403
        """
        terr = setup_territory()
        call = intake_call(terr["id"], address_line="9 Scope St",
                           caller_name="Z9", caller_phone="555-0233",
                           location_context="OUTSIDE_STRUCTURE")
        triage(call["incident_id"], "P3")

        resp = api_client.get_incident(call["incident_id"], REGULATOR)
        validate_error(resp, ApiErrorId.ERR_REGULATOR_SCOPE_RESTRICTED)

        ok = validate_success(api_client.get_incident(call["incident_id"],
                                                      SUPERVISOR))
        assert ok["lifecycle_status"] == "TRIAGED"

    def test_technician_reading_unassigned_incident_returns_403(self, api):
        """PRD §2.1: "A `FieldTechnician` may read or annotate only incidents
        on which it holds — or previously held — a dispatch assignment, and
        may act only on its own assignments; violations are rejected with
        `ERR_NOT_ASSIGNED_TO_INCIDENT` (HTTP 403)." and "When `X-User-Role` is
        `FieldTechnician`, `X-User-ID` is the `id` of the acting
        `FieldTechnician` record".

        Design: Corner/rbac/technician_reading_unassigned_incident_returns_403
        """
        terr = setup_territory()
        tech_a = validate_success(api_client.create_technician(
            create_technician_payload(full_name="A", badge_number="B116",
                                      home_territory_id=terr["id"]), ADMIN),
            expected_status=201)
        tech_b = validate_success(api_client.create_technician(
            create_technician_payload(full_name="B", badge_number="B117",
                                      home_territory_id=terr["id"]), ADMIN),
            expected_status=201)
        from test_helpers import add_shift
        add_shift(tech_a["id"])

        call = intake_call(terr["id"], address_line="10 Scope St",
                           caller_name="Z10", caller_phone="555-0234")
        triage(call["incident_id"], "P2")
        dispatch(call["incident_id"], tech_a["id"])

        resp = api_client.get_incident(call["incident_id"],
                                       make_technician_headers(tech_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_TO_INCIDENT)

        ok = validate_success(api_client.get_incident(
            call["incident_id"], make_technician_headers(tech_a["id"])))
        assert ok["id"] == call["incident_id"]

    def test_technician_cannot_arrive_others_dispatch_returns_403(self, api):
        """PRD §3.4: "The arrival action requires the assignment to be
        `EN_ROUTE` (otherwise `ERR_INVALID_STATE`) and requires `X-User-ID` to
        equal the assignment's `technician_id` (otherwise
        `ERR_NOT_ASSIGNED_TO_INCIDENT`, HTTP 403)."

        Design: Corner/rbac/technician_cannot_arrive_others_dispatch_returns_403
        """
        terr = setup_territory()
        tech_a = validate_success(api_client.create_technician(
            create_technician_payload(full_name="D", badge_number="B119",
                                      home_territory_id=terr["id"]), ADMIN),
            expected_status=201)
        tech_b = validate_success(api_client.create_technician(
            create_technician_payload(full_name="E", badge_number="B120",
                                      home_territory_id=terr["id"]), ADMIN),
            expected_status=201)
        from test_helpers import add_shift
        add_shift(tech_a["id"])
        add_shift(tech_b["id"])

        call = intake_call(terr["id"], address_line="12 Own St",
                           caller_name="Z12", caller_phone="555-0236")
        triage(call["incident_id"], "P2")
        disp = dispatch(call["incident_id"], tech_a["id"])

        resp = api_client.arrive_dispatch(disp["id"],
                                          make_technician_headers(tech_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_TO_INCIDENT)

        current = validate_success(api_client.get_dispatch(disp["id"], SUPERVISOR))
        assert current["status"] == "EN_ROUTE"


class TestExistencePrecedesState:
    def test_arrive_on_nonexistent_dispatch_returns_404(self, api):
        """PRD §2.6: "The server evaluates every request against a fixed
        validation cascade, and the ordering matters because an earlier
        failure masks all later ones." with path existence (step 3,
        `ERR_DISPATCH_NOT_FOUND`) preceding state legality (step 6).

        Design: Corner/validations/existence_precedes_state_on_arrive
        """
        setup_territory()
        resp = api_client.arrive_dispatch(
            "11111111-2222-3333-4444-555555555555",
            make_technician_headers("11111111-2222-3333-4444-555555555556"))
        validate_error(resp, ApiErrorId.ERR_DISPATCH_NOT_FOUND)


class TestOptimisticConcurrency:
    def test_occ_stale_reclassify_returns_412(self, api):
        """PRD §2.8: "A priority reclassification request must include
        `expected_incident_version` holding the incident `version` the client
        last observed... If the supplied value does not match the incident's
        current `version` — meaning the incident has been mutated since the
        client last read it, whether by triage, automatic escalation, a
        make-safe completion, or any other version-advancing effect — the
        request is rejected with `ERR_STALE_INCIDENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_reclassify_returns_412
        """
        terr = setup_territory()
        call = intake_call(terr["id"], address_line="13 Occ St",
                           caller_name="Z13", caller_phone="555-0237",
                           location_context="OUTSIDE_STRUCTURE")
        triage(call["incident_id"], "P3")
        observed = get_incident(call["incident_id"])
        stale_version = observed["version"]

        # First reclassify with the observed version succeeds and bumps it.
        first = validate_success(api_client.reclassify_incident(
            call["incident_id"],
            {"new_priority": "P2", "expected_incident_version": stale_version,
             "reason": "first reclassify"},
            SUPERVISOR))
        assert first["version"] == stale_version + 1

        # The same (now stale) version is rejected; no partial mutation.
        resp = api_client.reclassify_incident(
            call["incident_id"],
            {"new_priority": "P1", "expected_incident_version": stale_version,
             "reason": "stale retry"},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_STALE_INCIDENT_VERSION)
        assert get_incident(call["incident_id"])["priority"] == "P2"

        # A fresh read + retry succeeds.
        fresh_version = get_incident(call["incident_id"])["version"]
        third = validate_success(api_client.reclassify_incident(
            call["incident_id"],
            {"new_priority": "P1", "expected_incident_version": fresh_version,
             "reason": "fresh retry"},
            SUPERVISOR))
        assert third["priority"] == "P1"

    def test_occ_stale_determination_create_returns_412(self, api):
        """PRD §2.8: "a request to draft a responsibility determination must
        likewise include `expected_incident_version`... If the supplied value
        does not match the incident's current `version` — meaning the incident
        has been mutated since the client last read it, whether by triage,
        automatic escalation, a make-safe completion, or any other
        version-advancing effect — the request is rejected with
        `ERR_STALE_INCIDENT_VERSION` (HTTP 412)." §3.7: "The draft is born in
        `DRAFT` status".

        Design: Corner/cross_cutting_layers/occ_stale_determination_create_returns_412
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_on_scene_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="14 Occ St", caller_name="Z14", caller_phone="555-0238",
            location_context="OUTSIDE_STRUCTURE", hissing_reported=True)
        inc_id = call["incident_id"]
        record_reading(inc_id, tech["id"], pct_lel=4.0, co_ppm=0,
                       reading_context="OUTSIDE")

        # Supervisor reads the version BEFORE make-safe completion.
        stale_version = get_incident(inc_id)["version"]

        # Make-safe completion advances the incident version (PRD §3.5).
        from test_helpers import complete_make_safe
        complete_make_safe(inc_id, tech["id"], leak_confirmed=True,
                           no_make_safe_required=True)

        # The pre-completion version is stale now.
        resp = api_client.create_determination(
            inc_id,
            {"responsibility": "OUTSIDE_COMPANY", "basis": "BARHOLE_SURVEY",
             "expected_incident_version": stale_version},
            make_supervisor_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_STALE_INCIDENT_VERSION)

        # A fresh read + create succeeds.
        fresh_version = get_incident(inc_id)["version"]
        det = validate_success(api_client.create_determination(
            inc_id,
            {"responsibility": "OUTSIDE_COMPANY", "basis": "BARHOLE_SURVEY",
             "expected_incident_version": fresh_version},
            make_supervisor_headers("sup-1")), expected_status=201)
        assert det["status"] == "DRAFT"
