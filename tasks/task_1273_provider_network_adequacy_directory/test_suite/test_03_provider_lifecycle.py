"""Provider lifecycle: suspend/reinstate compensation, terminate cascade (PRD §3.3)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    set_clock, create_region, create_standard, create_provider, create_location,
    create_listing, publish_listing, create_cycle, list_records, get_cycle,
    list_listings,
)

NM = TEST_USERS["network_manager_headers"]


def _setup_two_listed_listings(county_fips="06039", name="Mono"):
    set_clock("2026-05-01T00:00:00Z")
    region = create_region(county_fips=county_fips, name=name)
    create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
    provider = create_provider(legal_name="Heart 29")
    loc1 = create_location(provider["id"], region["id"], address_line="29 A St")
    loc2 = create_location(provider["id"], region["id"], address_line="29 B St")
    lst1 = publish_listing(create_listing(provider["id"], loc1["id"],
                                          display_name="29 A", phone="555-0129")["id"])
    lst2 = publish_listing(create_listing(provider["id"], loc2["id"],
                                          display_name="29 B", phone="555-0130")["id"])
    return {"region": region, "provider": provider, "listings": [lst1, lst2]}


def _listed_rows(provider_id):
    data, _meta = validate_paginated(api_client.list_listings(
        NM, params={"provider_id": provider_id, "status": "LISTED", "limit": 100}))
    return data


def _suppressed_rows(provider_id):
    data, _meta = validate_paginated(api_client.list_listings(
        NM, params={"provider_id": provider_id, "status": "SUPPRESSED", "limit": 100}))
    return data


class TestProviderSuspendReinstateInvariant:
    def test_suspend_suppresses_exactly_the_listed_set(self, api):
        """PRD §3.3: "Suspension (`EFFECTIVE` → `SUSPENDED`) cascades into the
        directory: every `DirectoryListing` of this provider currently in `LISTED`
        status transitions to `SUPPRESSED` with `suppress_reason` = `PROVIDER_SUSPENDED`,
        `suppressed_at` stamped to the current clock, and `version` incremented by 1."

        Design: Difficulty/compensating_invariant/provider_suspend_reinstate_restores_listed_count
        """
        ctx = _setup_two_listed_listings()
        assert len(_listed_rows(ctx["provider"]["id"])) == 2
        validate_success(api.patch_provider(ctx["provider"]["id"],
                                            {"to_status": "SUSPENDED"}, NM))
        suppressed = _suppressed_rows(ctx["provider"]["id"])
        assert len(suppressed) == 2
        for row in suppressed:
            assert row["suppress_reason"] == "PROVIDER_SUSPENDED"
        assert len(_listed_rows(ctx["provider"]["id"])) == 0, (
            "no LISTED listings may survive the suspend cascade")

    def test_reinstate_restores_exactly_the_suppressed_set(self, api):
        """PRD §3.3: "Reinstatement (`SUSPENDED` → `EFFECTIVE`) runs the compensating
        cascade: every listing of this provider in `SUPPRESSED` with `suppress_reason` =
        `PROVIDER_SUSPENDED` transitions back to `LISTED`, `suppress_reason` cleared to
        `NONE`, `version` incremented by 1."
        PRD §3.3: "The invariant that results is that for every `(region, specialty)`
        pair, the count of `LISTED` listings is unchanged across a suspend-then-reinstate
        pair."

        Design: Difficulty/compensating_invariant/provider_suspend_reinstate_restores_listed_count
        """
        ctx = _setup_two_listed_listings()
        before = len(_listed_rows(ctx["provider"]["id"]))
        validate_success(api.patch_provider(ctx["provider"]["id"],
                                            {"to_status": "SUSPENDED"}, NM))
        validate_success(api.patch_provider(ctx["provider"]["id"],
                                            {"to_status": "EFFECTIVE"}, NM))
        restored = _listed_rows(ctx["provider"]["id"])
        assert len(restored) == before == 2, "compensating pair must conserve listed_count"
        for row in restored:
            assert row["suppress_reason"] == "NONE"
        assert len(_suppressed_rows(ctx["provider"]["id"])) == 0


class TestProviderTerminateCascade:
    def _setup_terminate_scenario(self):
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06019", name="Kern")
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        provider = create_provider(legal_name="Heart Eleven")
        loc1 = create_location(provider["id"], region["id"], address_line="13 Ash St")
        loc2 = create_location(provider["id"], region["id"], address_line="15 Ash St")
        publish_listing(create_listing(provider["id"], loc1["id"],
                                       display_name="Eleven A", phone="555-0111")["id"])
        publish_listing(create_listing(provider["id"], loc2["id"],
                                       display_name="Eleven B", phone="555-0112")["id"])
        cycle = create_cycle(cycle_label="2026-Q2B")
        validate_success(api_client.advance_cycle(cycle["id"], NM))
        records = list_records({"cycle_id": cycle["id"], "limit": 100})
        assert len(records) == 2
        return {"region": region, "provider": provider, "cycle": cycle, "records": records}

    def test_terminate_removes_all_listings(self, api):
        """PRD §3.3: "Link 1: every listing of this provider in `DRAFT`, `LISTED`,
        `UNDER_REVIEW`, or `SUPPRESSED` transitions to `REMOVED`, `version` incremented."

        Design: Difficulty/transitive_cascade/provider_terminate_removes_listings_cancels_records_updates_cycle
        """
        ctx = self._setup_terminate_scenario()
        terminated = validate_success(api.patch_provider(ctx["provider"]["id"],
                                                         {"to_status": "TERMINATED"}, NM))
        assert terminated["status"] == "TERMINATED"
        assert terminated["terminated_at"] is not None
        removed = list_listings({"provider_id": ctx["provider"]["id"], "status": "REMOVED"})
        assert len(removed) == 2, "both listings must be REMOVED by the terminate cascade"

    def test_terminate_cancels_pending_records_and_recomputes_cycle_counters(self, api):
        """PRD §3.3: "Link 2: every `AttestationRecord` whose listing was just removed
        and whose status is `PENDING` transitions to `CANCELLED`, `version` incremented.
        Link 3: each owning `AttestationCycle`'s counters (`total_records`,
        `pending_count`, `responded_count`, `non_responsive_count`) recompute over
        records whose status is not `CANCELLED`."

        Design: Difficulty/transitive_cascade/provider_terminate_removes_listings_cancels_records_updates_cycle
        """
        ctx = self._setup_terminate_scenario()
        validate_success(api.patch_provider(ctx["provider"]["id"],
                                            {"to_status": "TERMINATED"}, NM))
        cancelled = list_records({"cycle_id": ctx["cycle"]["id"], "status": "CANCELLED",
                                  "limit": 100})
        assert len(cancelled) == 2, "both PENDING records must be CANCELLED"
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["total_records"] == 0, "CANCELLED records are excluded from total_records"
        assert cycle["pending_count"] == 0

    def test_terminated_provider_rejects_further_transitions(self, api):
        """PRD §3.3: "Termination from `TERMINATED` itself is rejected with
        `ERR_PROVIDER_INVALID_TRANSITION`."

        Design: Corner/state_machines/terminated_provider_rejects_further_transitions
        """
        set_clock("2026-05-01T00:00:00Z")
        provider = create_provider(legal_name="P41", specialty="PRIMARY_CARE")
        validate_success(api.patch_provider(provider["id"], {"to_status": "TERMINATED"}, NM))
        resp = api.patch_provider(provider["id"], {"to_status": "SUSPENDED"}, NM)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_INVALID_TRANSITION)
        current = validate_success(api.get_provider(provider["id"], NM))
        assert current["status"] == "TERMINATED"
