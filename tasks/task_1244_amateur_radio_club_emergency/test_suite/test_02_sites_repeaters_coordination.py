"""Antenna site agreements, repeaters, and frequency coordination (PRD §3.2):
closed-interval lease overlap, OPERATIONAL gating, the revision loop, the
supersede cascade, and optimistic concurrency on coordination filing."""
from test_helpers import (
    ApiErrorId,
    assert_coordination_request,
    create_active_site_agreement,
    create_antenna_site_agreement_payload,
    create_coordination_request_payload,
    create_repeater,
    file_coordination_request,
    get_success_data,
    grant_coordination,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSiteWindowOverlap:
    def test_touching_lease_windows_conflict(self, api, admin_headers):
        """PRD §3.2: "The lease window is a *closed* interval: both endpoints
        are inclusive, so one agreement's `lease_end` falling exactly on
        another's `lease_start` counts as an overlap." and "a violation is
        rejected with `ERR_SITE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/site_agreement_closed_interval_touching_conflicts
        """
        first = get_success_data(api.create_antenna_site_agreement(
            create_antenna_site_agreement_payload(
                lease_start="2026-01-01T00:00:00Z", lease_end="2026-12-31T00:00:00Z"),
            admin_headers))
        assert first["status"] == "NEGOTIATION"
        touching = api.create_antenna_site_agreement(
            create_antenna_site_agreement_payload(
                lease_start="2026-12-31T00:00:00Z", lease_end="2027-06-30T00:00:00Z"),
            admin_headers)
        validate_error(touching, ApiErrorId.ERR_SITE_WINDOW_CONFLICT)

    def test_disjoint_lease_window_accepted(self, api, admin_headers):
        """PRD §3.2: "Two agreements for the same `site_name` may not have
        overlapping windows while both are in `NEGOTIATION` or `ACTIVE`; a
        violation is rejected with `ERR_SITE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/site_agreement_closed_interval_touching_conflicts
        """
        get_success_data(api.create_antenna_site_agreement(
            create_antenna_site_agreement_payload(
                lease_start="2026-01-01T00:00:00Z", lease_end="2026-12-31T00:00:00Z"),
            admin_headers))
        disjoint = api.create_antenna_site_agreement(
            create_antenna_site_agreement_payload(
                lease_start="2027-01-01T00:00:00Z", lease_end="2027-12-31T00:00:00Z"),
            admin_headers)
        agreement = validate_success(disjoint, 201)
        assert agreement["status"] == "NEGOTIATION"
        _, meta = validate_paginated(
            api.list_antenna_site_agreements(admin_headers, params={"site_name": "Hilltop"}))
        assert meta["total_count"] == 2


class TestRepeaterOperationalGates:
    def test_operational_requires_granted_coordination(self, api, admin_headers):
        """PRD §3.2: "the site agreement must currently be `ACTIVE` (otherwise
        `ERR_SITE_AGREEMENT_INACTIVE`), and at least one coordination request
        for this repeater must have reached `GRANTED` (otherwise
        `ERR_NO_COORDINATION_GRANT`)."

        Design: Corner/state_machines/repeater_operational_requires_grant
        """
        agreement = create_active_site_agreement()
        repeater = create_repeater(agreement["id"])
        resp = api.repeater_set_status(repeater["id"], {"to": "OPERATIONAL"}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NO_COORDINATION_GRANT)
        after = get_success_data(api.get_repeater(repeater["id"], admin_headers))
        assert after["status"] == "MAINTENANCE"

    def test_operational_requires_active_site_agreement(self, api, admin_headers):
        """PRD §3.2: "the site agreement must currently be `ACTIVE` (otherwise
        `ERR_SITE_AGREEMENT_INACTIVE`), and at least one coordination request
        for this repeater must have reached `GRANTED` (otherwise
        `ERR_NO_COORDINATION_GRANT`)."

        Design: Corner/state_machines/repeater_operational_requires_active_site
        """
        agreement = get_success_data(api.create_antenna_site_agreement(
            create_antenna_site_agreement_payload(), admin_headers))
        assert agreement["status"] == "NEGOTIATION"
        repeater = create_repeater(agreement["id"])
        request = file_coordination_request(repeater["id"], repeater["version"])
        grant_coordination(request["id"])
        resp = api.repeater_set_status(repeater["id"], {"to": "OPERATIONAL"}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_SITE_AGREEMENT_INACTIVE)
        after = get_success_data(api.get_repeater(repeater["id"], admin_headers))
        assert after["status"] == "MAINTENANCE"


class TestCoordinationLifecycle:
    def test_double_submit_rejected(self, api, admin_headers):
        """PRD §3.2: "Submission (`DRAFT` → `SUBMITTED`) stamps `submitted_at`
        with the current clock." — `SUBMITTED` is not a from-state for
        submission, and §2.10: "Fourth, the from-state of the primary resource
        for the requested transition — generic invalid-from rejections are
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/coordination_double_submit_rejected
        """
        agreement = create_active_site_agreement()
        repeater = create_repeater(agreement["id"])
        request = file_coordination_request(repeater["id"], repeater["version"])
        get_success_data(api.submit_coordination_request(request["id"], admin_headers))
        resp = api.submit_coordination_request(request["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_coordination_request(request["id"], admin_headers))
        assert after["status"] == "SUBMITTED"

    def test_revision_cycle_increments_revision_and_replaces_frequency(self, api, admin_headers):
        """PRD §3.2: "A `RETURNED` request re-enters `DRAFT` through the
        revision loop, which increments `revision_number` by one and, when a
        fresh `requested_frequency_mhz` is supplied, replaces the proposed
        frequency."

        Design: Difficulty/non_linear_state_machine/coordination_request_revision_cycle
        """
        agreement = create_active_site_agreement()
        repeater = create_repeater(agreement["id"])
        request = file_coordination_request(repeater["id"], repeater["version"], 146.94)
        get_success_data(api.submit_coordination_request(request["id"], admin_headers))
        get_success_data(api.record_coordination_decision(
            request["id"], {"outcome": "RETURNED", "council_reference": "C-101"}, admin_headers))
        revised = get_success_data(api.revise_coordination_request(
            request["id"], {"requested_frequency_mhz": 146.95}, admin_headers))
        assert revised["status"] == "DRAFT"
        assert revised["revision_number"] == 1
        assert revised["requested_frequency_mhz"] == 146.95

    def test_revision_cycle_completes_to_granted_with_latest_reference(self, api, admin_headers):
        """PRD §3.2: "Recording the council's decision moves a `SUBMITTED`
        request to `GRANTED` or `RETURNED` according to the supplied `outcome`,
        stores the supplied `council_reference`, and stamps `decision_at`."

        Design: Difficulty/non_linear_state_machine/coordination_request_revision_cycle
        """
        agreement = create_active_site_agreement()
        repeater = create_repeater(agreement["id"])
        request = file_coordination_request(repeater["id"], repeater["version"], 146.94)
        get_success_data(api.submit_coordination_request(request["id"], admin_headers))
        get_success_data(api.record_coordination_decision(
            request["id"], {"outcome": "RETURNED", "council_reference": "C-101"}, admin_headers))
        get_success_data(api.revise_coordination_request(
            request["id"], {"requested_frequency_mhz": 146.95}, admin_headers))
        get_success_data(api.submit_coordination_request(request["id"], admin_headers))
        granted = get_success_data(api.record_coordination_decision(
            request["id"], {"outcome": "GRANTED", "council_reference": "C-102"}, admin_headers))
        assert_coordination_request(granted)
        assert granted["status"] == "GRANTED"
        assert granted["council_reference"] == "C-102"
        assert granted["revision_number"] == 1


class TestCoordinationSupersede:
    def test_new_filing_withdraws_prior_draft(self, api, admin_headers):
        """PRD §3.2: "Filing a new request supersedes the repeater's paperwork:
        every existing request for the same repeater in `DRAFT` or `SUBMITTED`
        transitions to `WITHDRAWN`, and the repeater's `version` is bumped."

        Design: Corner/state_machines/coordination_supersede_withdraws_prior
        """
        agreement = create_active_site_agreement()
        repeater = create_repeater(agreement["id"])
        cr1 = file_coordination_request(repeater["id"], repeater["version"], 146.94)
        repeater_now = get_success_data(api.get_repeater(repeater["id"], admin_headers))
        cr2 = get_success_data(api.create_coordination_request(
            create_coordination_request_payload(
                repeater["id"], repeater_now["version"],
                requested_frequency_mhz=146.95),
            admin_headers))
        assert cr2["status"] == "DRAFT"
        cr1_after = get_success_data(api.get_coordination_request(cr1["id"], admin_headers))
        assert cr1_after["status"] == "WITHDRAWN"
        repeater_after = get_success_data(api.get_repeater(repeater["id"], admin_headers))
        assert repeater_after["version"] == repeater["version"] + 2


class TestCoordinationValidation:
    def test_frequency_out_of_band_rejected(self, api, admin_headers):
        """PRD §3.2: "The proposed frequency must lie inside one of the two
        recognized amateur allocations — from 144.0 to 148.0 MHz inclusive, or
        from 420.0 to 450.0 MHz inclusive — otherwise the filing is rejected
        with `ERR_FREQUENCY_OUT_OF_BAND`."

        Design: Corner/validations/coordination_frequency_out_of_band_rejected
        """
        agreement = create_active_site_agreement()
        repeater = create_repeater(agreement["id"])
        resp = api.create_coordination_request(
            create_coordination_request_payload(
                repeater["id"], repeater["version"],
                requested_frequency_mhz=150.0),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_FREQUENCY_OUT_OF_BAND)

    def test_stale_repeater_version_rejected(self, api, admin_headers):
        """PRD §2.9: "If the supplied value does not match the repeater's
        current `version`, the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/coordination_create_stale_version_rejected
        """
        agreement = create_active_site_agreement()
        repeater = create_repeater(agreement["id"])
        cr1 = file_coordination_request(repeater["id"], repeater["version"], 146.94)
        # The first filing bumped the repeater's version, so the version the
        # client holds is now stale.
        stale = api.create_coordination_request(
            create_coordination_request_payload(
                repeater["id"], repeater["version"],
                requested_frequency_mhz=146.95),
            admin_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        cr1_after = get_success_data(api.get_coordination_request(cr1["id"], admin_headers))
        assert cr1_after["status"] == "DRAFT"
