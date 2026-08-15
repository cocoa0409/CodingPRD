"""Machine registry: creation defaults, schema validation, lookup, listing,
modification log, and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_instant_equal,
    assert_machine,
    assert_machine_modification,
    bootstrap_manager,
    create_machine,
    create_machine_modification_payload,
    create_machine_payload,
    get_machine,
    is_valid_uuid,
    make_ehs_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMachineCreation:
    def test_machine_creation_applies_system_defaults(self, api):
        """PRD §3.1: "A new machine starts with `status` `IN_SERVICE`, a
        `risk_score` of 0, a `risk_tier` of `LOW`, an `open_session_count` of 0,
        and `version` 1."
        PRD §2.4: "Before the clock has been explicitly set, it reads exactly
        2026-08-01T00:00:00Z; the server must never fall back to wall-clock time."

        Design: Corner/entities/machine_creation_applies_defaults
        """
        mgr = bootstrap_manager("E-MGR-CD", "Mgr CD")
        resp = api.create_machine(
            create_machine_payload(asset_tag="A-CD-1", name="Lathe", area="Bay 1",
                                   risk_window_policy="ROLLING_12MO"),
            make_ehs_manager_headers(mgr["id"]))
        machine = validate_success(resp, expected_status=201)
        assert_machine(machine)
        assert machine["status"] == "IN_SERVICE"
        assert machine["risk_tier"] == "LOW"
        assert machine["risk_score"] == 0
        assert machine["open_session_count"] == 0
        assert machine["version"] == 1
        assert is_valid_uuid(machine["id"]), "id must be a server-minted UUID"
        assert_instant_equal(machine["created_at"], "2026-08-01T00:00:00Z")

    def test_machine_missing_required_asset_tag_returns_400(self, api):
        """PRD §2.8: "Request-body schema — required fields present, enum members
        valid, arrays honoring their minimum lengths, integer ranges honored
        (`severity` between 1 and 5 inclusive, `estimated_duration_min` at least
        1), and window starts strictly before window ends — otherwise
        `ERR_VALIDATION`."

        Design: Corner/entities/machine_missing_required_field_returns_invalid_request
        """
        mgr = bootstrap_manager("E-MGR-RF", "Mgr RF")
        headers = make_ehs_manager_headers(mgr["id"])
        payload = create_machine_payload(name="NoTag", area="Bay 2",
                                         risk_window_policy="ROLLING_12MO")
        del payload["asset_tag"]
        resp = api.create_machine(payload, headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _data, meta = validate_paginated(api.list_machines(headers))
        assert meta["total_count"] == 0, "No machine may be persisted by the rejected create"

    def test_machine_invalid_risk_window_policy_returns_400(self, api):
        """PRD §3.1: "An `EHSManager` registers a machine with a plant-unique
        `asset_tag`, a display `name`, the plant `area` or line it belongs to,
        and a `risk_window_policy` of `ROLLING_12MO` or
        `SINCE_PROCEDURE_ACTIVATION` that selects which risk-scoring window
        applies to the machine (§3.8)."
        PRD §2.8: "Request-body schema — required fields present, enum members
        valid, arrays honoring their minimum lengths, integer ranges honored
        (`severity` between 1 and 5 inclusive, `estimated_duration_min` at least
        1), and window starts strictly before window ends — otherwise
        `ERR_VALIDATION`."

        Design: Corner/entities/machine_invalid_enum_returns_invalid_request
        """
        mgr = bootstrap_manager("E-MGR-EN", "Mgr EN")
        resp = api.create_machine(
            create_machine_payload(asset_tag="A-EN-1", name="BadEnum", area="Bay 3",
                                   risk_window_policy="MONTHLY"),
            make_ehs_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_get_machine_not_found_returns_404(self, api):
        """PRD §2.9: "Where a path contains identifiers, the server validates
        them left to right and rejects with `ERR_NOT_FOUND` at the first
        identifier that does not resolve to an existing resource."

        Design: Corner/entities/machine_get_not_found_returns_404
        """
        mgr = bootstrap_manager("E-MGR-NF", "Mgr NF")
        resp = api.get_machine(NON_EXISTENT_UUID, make_ehs_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMachineListing:
    def test_machines_list_pagination_envelope(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of list responses carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/machines_list_pagination_envelope
        """
        mgr = bootstrap_manager("E-MGR-PG2", "Mgr PG2")
        headers = make_ehs_manager_headers(mgr["id"])
        for tag, name in (("A-PG-1", "M1"), ("A-PG-2", "M2"), ("A-PG-3", "M3")):
            create_machine(mgr, asset_tag=tag, name=name, area="Bay 7")
        page1, meta1 = validate_paginated(
            api.list_machines(headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert "api_request_id" in meta1, "list responses use the standard envelope"
        page2, meta2 = validate_paginated(
            api.list_machines(headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert "api_request_id" in meta2


class TestMachineModifications:
    def test_modification_logged_unreviewed_and_bumps_version(self, api):
        """PRD §3.3: "Second, the modification is logged with `review_status`
        `UNREVIEWED`, and if the machine has an `ACTIVE` procedure, that
        procedure is automatically pushed to `UNDER_REVISION`; that cascade in
        turn cancels every session of the machine still in `SETUP`, voids each
        cancelled session's `ISSUED` locks, and recomputes the machine's
        `open_session_count`."
        PRD §3.3: "First, the optimistic-concurrency rule of §2.7 applies: the
        request must carry `expected_machine_version` equal to the machine's
        current `version`, or it fails with `ERR_STALE_VERSION`, and a
        successful registration increments the machine's `version` by one."
        PRD §3.3: "A machine's modification history can be listed through the
        machine's own modification collection."
        PRD §2.5: "The `MachineModification` log is the single exception. As an
        append-only record it carries only `id` and `created_at`; both
        `updated_at` and `version` are absent from it."

        Design: Corner/entities/modification_log_entry_created_unreviewed
        """
        mgr = bootstrap_manager("E-MGR-IM", "Mgr IM")
        headers = make_ehs_manager_headers(mgr["id"])
        machine = create_machine(mgr, asset_tag="A-IM-1", name="Drill", area="Bay 6")
        assert machine["version"] == 1
        mod = validate_success(api.create_machine_modification(
            machine["id"],
            create_machine_modification_payload(
                description="Replaced guard interlock",
                expected_machine_version=machine["version"]),
            headers), expected_status=201)
        assert_machine_modification(mod)
        assert mod["review_status"] == "UNREVIEWED"
        mods, meta = validate_paginated(
            api.list_machine_modifications(machine["id"], headers))
        assert meta["total_count"] == 1
        assert mods[0]["id"] == mod["id"]
        machine_after = get_machine(mgr, machine["id"])
        assert machine_after["version"] == machine["version"] + 1, \
            "a successful registration increments the machine's version by one"

    def test_modification_stale_version_rejected_412(self, api):
        """PRD §2.7: "If the machine's current `version` has advanced past the
        supplied value — because another writer has registered a modification in
        the meantime, legitimately superseding the client's view of the
        machine's configuration baseline — the registration is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from recording a
        modification against a baseline it has not observed."
        PRD §3.3: "a successful registration increments the machine's `version`
        by one."

        Design: Corner/cross_cutting_layers/machine_modification_stale_version_rejected
        """
        mgr = bootstrap_manager("E-MGR-OCC", "Mgr OCC")
        headers = make_ehs_manager_headers(mgr["id"])
        machine = create_machine(mgr, asset_tag="A-OCC-1", name="Press", area="Bay 44")
        stale_version = machine["version"]

        first = validate_success(api.create_machine_modification(
            machine["id"],
            create_machine_modification_payload(
                description="First: new guard",
                expected_machine_version=stale_version),
            headers), expected_status=201)
        assert_machine_modification(first)
        assert get_machine(mgr, machine["id"])["version"] == stale_version + 1

        resp = api.create_machine_modification(
            machine["id"],
            create_machine_modification_payload(
                description="Second: stale view",
                expected_machine_version=stale_version),
            headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_machine(mgr, machine["id"])["version"]
        third = validate_success(api.create_machine_modification(
            machine["id"],
            create_machine_modification_payload(
                description="Third: fresh view",
                expected_machine_version=fresh_version),
            headers), expected_status=201)
        assert_machine_modification(third)
        _mods, meta = validate_paginated(
            api.list_machine_modifications(machine["id"], headers))
        assert meta["total_count"] == 2, "only the two successful registrations are logged"
