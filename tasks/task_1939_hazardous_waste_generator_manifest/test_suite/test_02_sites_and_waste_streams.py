"""Generator sites and waste-stream profiling, characterization, and retirement."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, create_stream_payload, characterize_payload,
    create_container_payload, create_site, create_stream, characterize,
    activate_stream, create_active_stream, create_area, create_container,
    create_manifest_chain, ehs_headers, wc_headers, ca_headers,
    assert_generator_site, assert_waste_stream, assert_site_category_invariants,
    DEFAULT_MONTH_KEY,
)


class TestSiteRegistration:
    def test_generator_site_creation_defaults(self, api):
        """PRD §3.1: "A newly registered site starts with `current_month_key` set
        to the logical clock's calendar month, `current_month_generated_kg` at
        zero, `generator_category` of `VSQG`, and both `open_exception_count` and
        `open_discrepancy_count` at zero." PRD §2.5: "At startup the logical clock
        reads exactly 2026-08-01T00:00:00Z, and the clock never falls back to
        wall-clock time thereafter."

        Design: Corner/entities/generator_site_creation_defaults
        """
        site = validate_success(
            api.create_site(
                {"name": "Site A", "epa_id_number": "EPA-SITE-A"},
                ehs_headers()),
            201)
        assert_generator_site(site)
        assert site["current_month_generated_kg"] == 0.0
        assert site["generator_category"] == "VSQG"
        assert site["current_month_key"] == DEFAULT_MONTH_KEY
        assert site["open_exception_count"] == 0
        assert site["open_discrepancy_count"] == 0

    def test_duplicate_epa_id_rejected(self, api):
        """PRD §3.1: "The EPA identification number must be unique across all
        registered sites — a duplicate is rejected with `ERR_DUPLICATE_EPA_ID` —
        and must be non-empty."

        Design: Corner/validations/duplicate_epa_id_rejected
        """
        create_site("Site A", "EPA-SITE-A")
        res = api.create_site(
            {"name": "Site A2", "epa_id_number": "EPA-SITE-A"}, ehs_headers())
        validate_error(res, ApiErrorId.ERR_DUPLICATE_EPA_ID)


class TestStreamCreation:
    def test_waste_stream_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.9: "fifth, request shape — required fields present, types
        matching, enum members valid, unknown request fields rejected, quantities
        strictly positive, `coverage_to` strictly later than `coverage_from`
        (`ERR_INVALID_REQUEST`)". PRD §3.1: a stream is created "with a `name`
        (such as "spent solvent"), a `physical_state` of `LIQUID`, `SOLID`,
        `SLUDGE`, or `GAS`, and an initial `waste_codes` array".

        Design: Corner/entities/waste_stream_missing_required_field_returns_invalid_request
        """
        site = create_site()
        payload = create_stream_payload(site["id"])
        del payload["physical_state"]
        res = api.create_stream(payload, wc_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        _, meta = validate_paginated(
            api.list_streams(ehs_headers(), params={"site_id": site["id"]}))
        assert meta["total_count"] == 0

    def test_waste_streams_filtered_by_site(self, api):
        """PRD §4: "| GET | `/hazwaste/waste-streams` | List waste streams,
        optionally filtered by `site_id` | EHSManager, WasteCoordinator,
        ComplianceAuditor, TransporterAgent, TSDFAgent |".

        Design: Corner/endpoints/waste_streams_filtered_by_site
        """
        site_a = create_site("Site A", "EPA-SITE-A")
        site_b = create_site("Site B", "EPA-SITE-B")
        s_a = create_stream(site_a["id"], "solvent A")
        create_stream(site_b["id"], "solvent B")
        data, meta = validate_paginated(
            api.list_streams(ca_headers(), params={"site_id": site_a["id"]}))
        assert meta["total_count"] == 1
        assert [s["id"] for s in data] == [s_a["id"]]
        _, meta_all = validate_paginated(api.list_streams(ca_headers()))
        assert meta_all["total_count"] == 2


class TestStreamActivation:
    def test_waste_stream_activate_from_draft_rejected(self, api):
        """PRD §3.1: "attempting it from any state other than `CHARACTERIZED` is
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/waste_stream_activate_from_draft_rejected
        """
        site = create_site()
        stream = create_stream(site["id"])
        res = api.activate_stream(stream["id"], ehs_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        fresh = validate_success(api.get_stream(stream["id"], ehs_headers()))
        assert fresh["status"] == "DRAFT"
        assert fresh["characterization_version"] == 0

    def test_stream_activate_not_hazardous_rejected(self, api):
        """PRD §3.1: "An `EHSManager` activates a `CHARACTERIZED` stream, moving it
        to `ACTIVE`, only when its characterization concluded `is_hazardous` is
        true; attempting to activate a non-hazardous stream is rejected with
        `ERR_STREAM_NOT_HAZARDOUS`".

        Design: Corner/errors/stream_activate_not_hazardous_rejected
        """
        site = create_site()
        stream = create_stream(site["id"], "cardboard", [], "SOLID")
        stream = characterize(stream, is_hazardous=False, waste_codes=[],
                              ldr_treatment_standard="NONE")
        assert stream["status"] == "CHARACTERIZED"
        res = api.activate_stream(stream["id"], ehs_headers())
        validate_error(res, ApiErrorId.ERR_STREAM_NOT_HAZARDOUS)
        fresh = validate_success(api.get_stream(stream["id"], ehs_headers()))
        assert fresh["status"] == "CHARACTERIZED"


class TestStreamRetirement:
    def test_characterize_retired_stream_returns_already_terminal(self, api):
        """PRD §3.1: "A retired stream accepts no further transitions of any kind,
        per the terminal-state rule in §2.9." PRD §2.9: "an entity already in a
        terminal state (`RETIRED`, `EMPTIED`, `VOIDED`, `RETURNED`, `ACCEPTED`, or
        `REJECTED`) rejects every further transition with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/characterize_retired_stream_returns_already_terminal
        """
        site = create_site()
        stream = create_active_stream(site["id"])
        retired = validate_success(api.retire_stream(stream["id"], ehs_headers()))
        assert retired["status"] == "RETIRED"
        res = api.characterize_stream(
            stream["id"],
            characterize_payload(retired["version"], True, ["D001"], "TLV-01", 30.0),
            wc_headers())
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
        fresh = validate_success(api.get_stream(stream["id"], ehs_headers()))
        assert fresh["status"] == "RETIRED"
        assert fresh["characterization_version"] == 1

    def test_retire_stream_with_open_containers_rejected(self, api):
        """PRD §3.1: "an `EHSManager` may retire a stream from `DRAFT`,
        `CHARACTERIZED`, or `ACTIVE`, but only while no container of that stream
        sits in `ACCUMULATING_AT_SATELLITE`, `SATELLITE_LIMIT_EXCEEDED`,
        `IN_CENTRAL_ACCUMULATION`, or `STAGED_FOR_SHIPMENT` — otherwise the retire
        is rejected with `ERR_STREAM_HAS_OPEN_CONTAINERS`."

        Design: Corner/validations/retire_stream_with_open_containers_rejected
        """
        site = create_site()
        stream = create_active_stream(site["id"])
        area = create_area(site["id"])
        container = create_container(stream["id"], area["id"], 10, 50.0)
        res = api.retire_stream(stream["id"], ehs_headers())
        validate_error(res, ApiErrorId.ERR_STREAM_HAS_OPEN_CONTAINERS)
        validate_success(api.void_container(container["id"], wc_headers()))
        retired = validate_success(api.retire_stream(stream["id"], ehs_headers()))
        assert retired["status"] == "RETIRED"


class TestRecharacterizationCycle:
    def test_recharacterization_loops_active_back_to_characterized(self, api):
        """PRD §3.1: "on success the stream lands in `CHARACTERIZED`,
        `characterization_version` increments by one, the stream's `version`
        increments by one, and the five characterization fields (`is_hazardous`,
        `flash_point_c`, `ph`, `ldr_treatment_standard`, `waste_codes`) are
        overwritten wholesale with the new values. Recharacterizing an `ACTIVE`
        stream deliberately loops it back to `CHARACTERIZED`".

        Design: Difficulty/non_linear_state_machine/wastestream_recharacterization_cycle
        """
        site = create_site()
        stream = create_active_stream(site["id"])  # v after create+char+activate
        v_before = stream["version"]
        rechar = validate_success(api.characterize_stream(
            stream["id"],
            characterize_payload(v_before, True, ["D001", "F003"], "TLV-09", 25.0),
            wc_headers()))
        assert rechar["status"] == "CHARACTERIZED"
        assert rechar["characterization_version"] == 2
        assert rechar["version"] == v_before + 1, (
            "each mutation increments version by one (PRD §2.4)")
        assert rechar["waste_codes"] == ["D001", "F003"]
        assert rechar["ldr_treatment_standard"] == "TLV-09"
        assert rechar["flash_point_c"] == 25.0
        reactivated = validate_success(api.activate_stream(stream["id"], ehs_headers()))
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["version"] == v_before + 2

    def test_recharacterized_stream_refuses_new_containers_until_activated(self, api):
        """PRD §3.1: "Recharacterizing an `ACTIVE` stream deliberately loops it
        back to `CHARACTERIZED`, which pulls it out of service: until the stream
        is re-activated, new containers may not be created against it." PRD §3.2:
        "Creation requires the stream to be `ACTIVE` (otherwise
        `ERR_STREAM_NOT_ACTIVE`)".

        Design: Difficulty/non_linear_state_machine/wastestream_recharacterization_cycle
        """
        site = create_site()
        stream = create_active_stream(site["id"])
        area = create_area(site["id"])
        # Loop the ACTIVE stream back to CHARACTERIZED.
        validate_success(api.characterize_stream(
            stream["id"],
            characterize_payload(stream["version"], True, ["D001"], "TLV-01", 22.0),
            wc_headers()))
        res = api.create_container(
            create_container_payload(stream["id"], area["id"], 10, 50.0),
            wc_headers())
        validate_error(res, ApiErrorId.ERR_STREAM_NOT_ACTIVE)
        # Re-activation restores service.
        validate_success(api.activate_stream(stream["id"], ehs_headers()))
        container = validate_success(api.create_container(
            create_container_payload(stream["id"], area["id"], 10, 50.0),
            wc_headers()), 201)
        assert container["waste_stream_id"] == stream["id"]


class TestStreamOcc:
    def test_occ_stream_characterize_stale_version(self, api):
        """PRD §2.8: "If the stream's current `version` has advanced past that
        value — for instance because another writer has just recharacterized the
        same stream, legitimately superseding the prior characterization — the
        write is rejected with `ERR_STALE_VERSION` (HTTP 412)" and "The OCC check
        is evaluated after request-shape validation but before any state-machine
        or business-rule validation, so a stale write surfaces as
        `ERR_STALE_VERSION` even when the request would also have failed a later
        check."

        Design: Corner/cross_cutting_layers/occ_stream_characterize_stale_version
        """
        site = create_site()
        stream = create_stream(site["id"])
        first = validate_success(api.characterize_stream(
            stream["id"],
            characterize_payload(stream["version"], True, ["D001"], "TLV-01", 21.5),
            wc_headers()))
        assert first["status"] == "CHARACTERIZED"
        assert first["characterization_version"] == 1
        # Replay the pre-supersede version: stale even though the state changed.
        res = api.characterize_stream(
            stream["id"],
            characterize_payload(stream["version"], True, ["D001", "F003"],
                                 "TLV-09", 25.0),
            wc_headers())
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        fresh = validate_success(api.get_stream(stream["id"], ehs_headers()))
        assert fresh["characterization_version"] == 1, (
            "the rejected write changed nothing")
        assert fresh["waste_codes"] == ["D001"]
