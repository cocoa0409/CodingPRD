"""Proxy material generation, householding consolidation, and delivery
outcomes (PRD §3.3)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_material_distribution,
    add_proposal,
    generate_distributions, setup_locked_meeting, setup_materials_distributed,
)


class TestMaterialGeneration:
    def test_distribution_generation_activates_draft_proposals(self, api, proxy_admin_headers):
        """PRD §3.3: "The first generation for a meeting is additionally a
        lifecycle event: it requires the meeting to be in `RECORD_DATE_LOCKED`
        or `MATERIALS_DISTRIBUTED` (otherwise `ERR_INVALID_MEETING_STATE`),
        requires at least one proposal to exist for the meeting, moves the
        meeting `RECORD_DATE_LOCKED → MATERIALS_DISTRIBUTED`, flips every
        `DRAFT` proposal of the meeting to `ACTIVE`, and increments the
        meeting's `version`."
        PRD §3.3: "Packages are created in ascending order of their
        representative's creation time, and each new package starts in `ACTIVE`
        status."

        Design: Corner/state_machines/distribution_generation_activates_draft_proposals
        """
        ctx = setup_locked_meeting(account_specs=[{"shares_held": 6000}])
        m_id = ctx["meeting"]["id"]
        proposal = add_proposal(m_id, 1)
        packages = generate_distributions(m_id)
        assert len(packages) >= 1, "generation must create at least one package"
        for pkg in packages:
            assert_material_distribution(pkg)
            assert pkg["status"] == "ACTIVE", f"package must start ACTIVE, got {pkg['status']}"
        meeting = validate_success(api.get_meeting(m_id, proxy_admin_headers), 200)
        assert meeting["status"] == "MATERIALS_DISTRIBUTED"
        prop = validate_success(api.get_proposal(proposal["id"], proxy_admin_headers), 200)
        assert prop["status"] == "ACTIVE", f"DRAFT proposal must flip to ACTIVE, got {prop['status']}"

    def test_householding_opt_out_forces_individual_packages(self, api, proxy_admin_headers):
        """PRD §3.3: "Accounts whose `delivery_preference` is
        `NOTICE_AND_ACCESS` or `FULL_MAIL`, that have not set
        `householding_opt_out`, and that have a non-null `address_key` are
        grouped by the combination of their `address_key` and
        `delivery_preference`."
        PRD §3.2: "a `householding_opt_out` flag (defaulting to `false`) which,
        when true, guarantees the holder always receives an individual package."

        Design: Corner/calculations/householding_opt_out_forces_individual_packages
        """
        ctx = setup_locked_meeting(account_specs=[
            {"shares_held": 3000, "address_key": "ADDR-1", "delivery_preference": "NOTICE_AND_ACCESS"},
            {"shares_held": 2000, "address_key": "ADDR-1", "delivery_preference": "NOTICE_AND_ACCESS",
             "householding_opt_out": True},
        ])
        m_id = ctx["meeting"]["id"]
        add_proposal(m_id, 1)
        packages = generate_distributions(m_id)
        assert len(packages) == 2, (
            f"opt-out defeats householding: expected 2 individual packages, got {len(packages)}"
        )
        for pkg in packages:
            assert len(pkg["covered_account_ids"]) == 1, (
                "each package must cover exactly one account when a holder opts out"
            )
        listed, meta = validate_paginated(api.list_material_distributions(
            proxy_admin_headers, params={"meeting_id": m_id, "status": "ACTIVE"}
        ))
        assert meta["total_count"] == 2
        total_shares = sum(p["covered_shares"] for p in listed)
        assert total_shares == 5000, f"covered shares must sum to 5000, got {total_shares}"

    def test_distribution_outcome_lifecycle_and_terminal_rejection(self, api, proxy_admin_headers):
        """PRD §3.3: "The administrator records a package's `delivery_outcome`
        as `DELIVERED` or `BOUNCED`; only an `ACTIVE` package accepts an
        outcome, and recording against a package in any other state is rejected
        with `ERR_DISTRIBUTION_NOT_ACTIVE`."

        Design: Corner/state_machines/distribution_outcome_lifecycle_and_terminal_rejection
        """
        ctx = setup_materials_distributed(
            account_specs=[{"shares_held": 6000, "address_key": "ADDR-9"}]
        )
        pkg_id = ctx["packages"][0]["id"]
        first = api.patch_material_distribution(pkg_id, {"delivery_outcome": "DELIVERED"}, proxy_admin_headers)
        data = validate_success(first, 200)
        assert data["status"] == "DELIVERED", f"expected DELIVERED, got {data['status']}"
        second = api.patch_material_distribution(pkg_id, {"delivery_outcome": "BOUNCED"}, proxy_admin_headers)
        validate_error(second, ApiErrorId.ERR_DISTRIBUTION_NOT_ACTIVE, 409)


class TestPreferenceRoundtripRegeneration:
    """A delivery-preference change followed by regeneration must be a true
    compensating pair: the ACTIVE package set is rebuilt with no leakage."""

    def _setup(self):
        ctx = setup_locked_meeting(account_specs=[
            {"holder_name": "Household A", "shares_held": 3000, "address_key": "ADDR-1",
             "delivery_preference": "NOTICE_AND_ACCESS"},
            {"holder_name": "Household B", "shares_held": 2000, "address_key": "ADDR-1",
             "delivery_preference": "NOTICE_AND_ACCESS"},
            {"holder_name": "Solo C", "shares_held": 1000, "delivery_preference": "E_DELIVERY",
             "email": "c@example.com"},
        ])
        add_proposal(ctx["meeting"]["id"], 1)
        return ctx

    def test_initial_generation_consolidates_household(self, api, proxy_admin_headers):
        """PRD §3.3: "Each group yields a single **MaterialDistribution**
        package: its `channel` is the group's shared delivery preference, its
        `representative_account_id` is the earliest-created account in the
        group (the household representative), its `covered_account_ids` lists
        every member account, and its `covered_shares` is the sum of
        `shares_held` across those members."
        PRD §3.3: "Packages are created in ascending order of their
        representative's creation time".

        Design: Difficulty/compensating_invariant/preference_roundtrip_regeneration_restores_distribution_set
        """
        ctx = self._setup()
        m_id = ctx["meeting"]["id"]
        packages = generate_distributions(m_id)
        assert len(packages) == 2, (
            f"expected 2 packages (household + E_DELIVERY solo), got {len(packages)}"
        )
        household = packages[0]
        assert household["covered_shares"] == 5000, (
            f"household package covers a1+a2 = 5000 shares, got {household['covered_shares']}"
        )
        assert sorted(household["covered_account_ids"]) == sorted(
            [ctx["accounts"][0]["id"], ctx["accounts"][1]["id"]]
        ), "household package must cover both same-address accounts"
        assert household["representative_account_id"] == ctx["accounts"][0]["id"], (
            "earliest-created account is the household representative"
        )
        listed, meta = validate_paginated(api.list_material_distributions(
            proxy_admin_headers, params={"meeting_id": m_id, "status": "ACTIVE"}
        ))
        assert meta["total_count"] == 2

    def test_preference_roundtrip_restores_distribution_set(self, api, proxy_admin_headers, transfer_agent_headers):
        """PRD §3.3: "Any regeneration supersedes all of the meeting's existing
        packages that are not already `SUPERSEDED` — whether they are `ACTIVE`,
        `DELIVERED`, or `BOUNCED` — and builds a fresh set per the grouping rule
        above."
        PRD §3.3: "Such an update does not itself rebuild any packages — it
        takes effect at the next generation."

        Design: Difficulty/compensating_invariant/preference_roundtrip_regeneration_restores_distribution_set
        """
        ctx = self._setup()
        m_id = ctx["meeting"]["id"]
        a2 = ctx["accounts"][1]
        generate_distributions(m_id)

        # Round trip: NOTICE_AND_ACCESS -> E_DELIVERY -> NOTICE_AND_ACCESS.
        resp = api.patch_shareholder_account(a2["id"], {"delivery_preference": "E_DELIVERY"}, transfer_agent_headers)
        validate_success(resp, 200)
        generate_distributions(m_id)
        listed, meta = validate_paginated(api.list_material_distributions(
            proxy_admin_headers, params={"meeting_id": m_id, "status": "ACTIVE", "limit": 100}
        ))
        assert meta["total_count"] == 3, (
            f"a2 leaving the household must yield 3 ACTIVE packages, got {meta['total_count']}"
        )

        resp = api.patch_shareholder_account(a2["id"], {"delivery_preference": "NOTICE_AND_ACCESS"}, transfer_agent_headers)
        validate_success(resp, 200)
        generate_distributions(m_id)
        listed, meta = validate_paginated(api.list_material_distributions(
            proxy_admin_headers, params={"meeting_id": m_id, "status": "ACTIVE", "limit": 100}
        ))
        assert meta["total_count"] == 2, (
            f"returning a2 to the household must restore 2 ACTIVE packages, got {meta['total_count']}"
        )
        total_shares = sum(p["covered_shares"] for p in listed)
        assert total_shares == 6000, (
            f"covered shares are conserved across the round trip: expected 6000, got {total_shares}"
        )
