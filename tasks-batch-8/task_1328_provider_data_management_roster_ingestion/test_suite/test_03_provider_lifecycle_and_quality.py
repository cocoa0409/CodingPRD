"""Provider lifecycle, manual creation, listing/pagination, quality scoring reads,
merges, and the associated guard errors (PRD §3.6, §3.7, §2.3, §2.7)."""
from test_helpers import (
    FRESH_PROVIDER_SCORE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_attribute,
    assert_data_quality_score,
    assert_provider,
    assert_provider_merge_record,
    create_open_campaign,
    create_provider,
    create_provider_merge_payload,
    create_provider_payload,
    create_sent_request,
    create_target,
    get_provider,
    merge_providers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestManualCreate:
    def test_create_provider_initial_score(self, api, data_steward_headers):
        """PRD §3.6: "A manually created provider starts with `lifecycle_status`
        `ACTIVE` and an initial quality-score run per §3.7."
        PRD §3.7: "a group holding no `ACTIVE` attributes at all counts as stale";
        "The `conflict_component` contributes up to 20 points, starting at 20 and
        forfeiting five points per unresolved conflict"; "The `attestation_component`
        contributes up to 10 points, starting at 10"; "The `total_score` is the sum of
        the four components."

        Design: Corner/entities/provider_manual_create_initial_score_zero
        """
        set_clock()
        res = api.create_provider(create_provider_payload(), data_steward_headers)
        provider = validate_success(res, 201)
        assert_provider(provider)
        assert provider["lifecycle_status"] == "ACTIVE"
        # No attributes, no conflicts, no outreach: 0 + 0 + 20 + 10 = 30.
        assert provider["current_quality_score"] == FRESH_PROVIDER_SCORE["total_score"], (
            "Fresh provider score must be 30, got "
            f"{provider['current_quality_score']}"
        )

    def test_get_provider_returns_stored_fields(self, api, data_steward_headers):
        """PRD §3.6: "a `DataSteward` may also create one directly — seeding the
        directory ahead of the first roster — by supplying the canonical `npi`, `tin`,
        and `location_key`."

        Design: Corner/endpoints/get_provider_by_id_returns_stored_fields
        """
        set_clock()
        created = create_provider()
        fetched = validate_success(api.get_provider(created["id"], data_steward_headers))
        assert_provider(fetched)
        assert fetched["id"] == created["id"]
        assert fetched["npi"] == "1234567893"
        assert fetched["tin"] == "123456789"
        assert fetched["location_key"] == "LOC1"
        assert fetched["lifecycle_status"] == "ACTIVE"

    def test_get_unknown_provider_not_found(self, api, data_steward_headers):
        """PRD §2.9: "the request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first `id` in the path that does not correspond to an
        existing resource"

        Design: Corner/errors/error_not_found_on_unknown_provider
        """
        set_clock()
        res = api.get_provider(NON_EXISTENT_UUID, data_steward_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestProviderListing:
    def test_pagination_defaults(self, api, data_steward_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return. If not provided, it defaults to 10, with a minimum of 1 and maximum of
        100. The `offset` parameter specifies the number of items to skip and defaults
        to 0." and "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_providers_pagination_defaults
        """
        set_clock()
        for i in range(12):
            create_provider(npi=f"1234567{i:03d}", location_key=f"LOC{i}")
        data, meta = validate_paginated(api.list_providers(data_steward_headers))
        assert meta["limit"] == 10, f"Default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert len(data) == 10
        assert meta["has_more"] is True

    def test_filter_and_pagination_combined(self, api, data_steward_headers):
        """PRD §3.6: "The provider listing accepts optional `lifecycle_status`, `npi`,
        `tin`, `staleness_flag`, `min_quality_score`, `merged_into_provider_id`, and
        `last_roster_file_id` filters."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return."

        Design: Corner/complexity_layers/pagination_filter_combination
        """
        set_clock()
        for i in range(3):
            create_provider(npi=f"1234567{i:03d}", location_key=f"LOC{i}")
        suspended = create_provider(npi="1234567896", location_key="LOC4")
        validate_success(
            api.suspend_provider(suspended["id"], data_steward_headers)
        )
        data, meta = validate_paginated(
            api.list_providers(
                data_steward_headers,
                params={"lifecycle_status": "ACTIVE", "limit": 1, "offset": 1},
            )
        )
        assert len(data) == 1, f"limit=1 must return exactly one provider, got {len(data)}"
        assert meta["total_count"] == 3, (
            f"SUSPENDED provider must be excluded by the filter, total_count={meta['total_count']}"
        )
        assert meta["has_more"] is True
        assert data[0]["lifecycle_status"] == "ACTIVE"


class TestQualityScoreReads:
    def test_recompute_returns_all_components(self, api, data_steward_headers):
        """PRD §3.7: "Each computation appends a new, immutable score row — never
        updating history — recording the `provider_id`, the logical-clock instant as
        `computed_at`, the four components, the resulting `total_score`, and, when a
        commit triggered the computation, the responsible `roster_file_id`."

        Design: Corner/endpoints/quality_score_recompute_computed_read
        """
        set_clock()
        provider = create_provider()
        res = api.recompute_quality_score(provider["id"], data_steward_headers)
        score = validate_success(res, 200)
        assert_data_quality_score(score)
        for field, expected in FRESH_PROVIDER_SCORE.items():
            assert score[field] == expected, (
                f"Fresh provider {field} must be {expected}, got {score[field]}"
            )

    def test_completeness_scales_with_required_keys(self, api, data_steward_headers):
        """PRD §3.7: "The component is forty points scaled by the fraction of those ten
        keys that hold an `ACTIVE`, non-terminated attribute, rounded half-up to a whole
        number — the system's single rounding step, applied only at this final
        multiplication per §2.10."

        Design: Corner/calculations/quality_score_completeness_rounding_half_up
        """
        set_clock()
        provider = create_provider()
        # Zero required keys present.
        score = validate_success(
            api.recompute_quality_score(provider["id"], data_steward_headers)
        )
        assert score["completeness_component"] == 0
        # Exactly 5 of the 10 required keys: name, dob, gender, primary_taxonomy, street1.
        for group, key in [
            ("DEMOGRAPHIC", "name"),
            ("DEMOGRAPHIC", "dob"),
            ("DEMOGRAPHIC", "gender"),
            ("SPECIALTY", "primary_taxonomy"),
            ("PRACTICE_ADDRESS", "street1"),
        ]:
            add_attribute(
                provider["id"],
                attribute_group=group,
                attribute_key=key,
                attribute_value="x",
                effective_date="2026-01-01",
            )
        score = validate_success(
            api.recompute_quality_score(provider["id"], data_steward_headers)
        )
        # round_half_up(40 * 5 / 10) == 20
        assert score["completeness_component"] == 20, (
            f"5 of 10 required keys must yield completeness 20, got {score['completeness_component']}"
        )


class TestProviderLifecycleGuards:
    def test_reinstate_below_quality_floor_rejected(self, api, data_steward_headers):
        """PRD §3.6: "the provider's `current_quality_score` must be at least the lowest
        `required_quality_floor` across all `ACTIVE` distribution targets, or the call
        is rejected with `ERR_QUALITY_FLOOR_NOT_MET` (HTTP 409)."

        Design: Corner/errors/error_quality_floor_not_met_on_reinstate
        """
        set_clock()
        provider = create_provider()  # score 30
        create_target(target_code="CLAIMS", required_quality_floor=50)
        validate_success(api.suspend_provider(provider["id"], data_steward_headers))
        res = api.reinstate_provider(provider["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_QUALITY_FLOOR_NOT_MET)

    def test_terminate_blocked_by_sent_attestation(self, api, data_steward_headers):
        """PRD §3.6: "Termination moves a provider `ACTIVE` → `TERMINATED` and is
        blocked while any attestation request for the provider remains in `SENT` —
        `ERR_OPEN_ATTESTATION_EXISTS` (HTTP 409) — so outreach is never orphaned
        mid-flight."

        Design: Corner/validations/terminate_with_open_attestation_blocked
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CV10")
        create_sent_request(campaign["id"], provider["id"])
        res = api.terminate_provider(provider["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_OPEN_ATTESTATION_EXISTS)


class TestProviderMerges:
    def test_merge_self_rejected(self, api, data_steward_headers):
        """PRD §3.6: "and finally the two parties must be distinct, failing as
        `ERR_MERGE_SELF` (HTTP 422)."

        Design: Corner/validations/merge_self_rejected
        """
        set_clock()
        provider = create_provider()
        res = api.create_provider_merge(
            create_provider_merge_payload(provider["id"], provider["id"], provider["version"]),
            data_steward_headers,
        )
        validate_error(res, ApiErrorId.ERR_MERGE_SELF)

    def test_merge_of_already_merged_rejected(self, api, data_steward_headers):
        """PRD §3.6: "then the merged provider must be `ACTIVE`, failing as
        `ERR_PROVIDER_NOT_LINKABLE`"

        Design: Corner/errors/error_provider_not_linkable_on_merge_of_merged
        """
        set_clock()
        a = create_provider()
        b = create_provider(npi="1234567894", location_key="LOC2")
        c = create_provider(npi="1234567895", location_key="LOC3")
        merge_providers(a["id"], b["id"], rationale="x")
        b_after = get_provider(b["id"])
        res = api.create_provider_merge(
            create_provider_merge_payload(c["id"], b["id"], b_after["version"], rationale="y"),
            data_steward_headers,
        )
        validate_error(res, ApiErrorId.ERR_PROVIDER_NOT_LINKABLE)

    def test_merge_stale_version_rejected(self, api, data_steward_headers):
        """PRD §2.7: "Executing a provider merge — `POST /pdm/provider-merges` —
        requires the non-optional field `expected_provider_version`, carrying the last
        observed `version` of the provider being folded in. A mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412): an intervening commit, retro approval, or merge
        has legitimately changed that provider's attribute set, and the merge decision
        was made against a snapshot the client can no longer defend."

        Design: Corner/complexity_layers/occ_merge_stale_version
        """
        set_clock()
        a = create_provider()
        b = create_provider(npi="1234567894", location_key="LOC2")
        stale_version = b["version"]
        # Intervening write: "Manually adding an attribute ... the provider's `version`
        # increments." (PRD §3.4)
        add_attribute(b["id"], attribute_value="X", effective_date="2026-08-01")
        res = api.create_provider_merge(
            create_provider_merge_payload(a["id"], b["id"], stale_version, rationale="x"),
            data_steward_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_merged_provider_terminal_lockdown(self, api, data_steward_headers):
        """PRD §3.6: "the merged provider itself settles into the terminal `MERGED`
        state with `merged_into_provider_id` naming the survivor"; "and only a
        `SUSPENDED` provider may be reinstated, with other states failing as
        `ERR_INVALID_STATE`".
        PRD §2.6: "a request that names a legal resource in an illegal state is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/provider_merged_terminal_no_reinstate
        """
        set_clock()
        a = create_provider()
        b = create_provider(npi="1234567894", location_key="LOC2")
        merge_providers(a["id"], b["id"])
        res = api.suspend_provider(b["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        res = api.reinstate_provider(b["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_merge_sets_merged_state_and_record(self, api, data_steward_headers):
        """PRD §3.6: "A successful merge creates a **provider merge record** — an
        append-only entry capturing `survivor_provider_id`, `merged_provider_id`, the
        deciding steward's opaque id as `decided_by_user_id`, the logical-clock instant
        as `decided_at`, and the `rationale`" and "the merged provider itself settles
        into the terminal `MERGED` state with `merged_into_provider_id` naming the
        survivor and its `version` incremented by one."

        Design: Difficulty/compensating_invariant/merge_preserves_provider_count_minus_one
        """
        set_clock()
        a = create_provider()
        b = create_provider(npi="1234567894", location_key="LOC2")
        add_attribute(a["id"], attribute_value="A1")
        add_attribute(b["id"], attribute_value="B1")
        record = merge_providers(a["id"], b["id"])
        assert_provider_merge_record(record)
        assert record["survivor_provider_id"] == a["id"]
        assert record["merged_provider_id"] == b["id"]
        merged_after = get_provider(b["id"])
        assert merged_after["lifecycle_status"] == "MERGED"
        assert merged_after["merged_into_provider_id"] == a["id"]

    def test_merge_repoints_attributes_and_preserves_population(
        self, api, data_steward_headers
    ):
        """PRD §3.6: "its attribute records re-point their `provider_id` to the
        survivor, with same-group overlapping intervals triggering re-resolution under
        the dating rules of §3.4". Merge is a status change, not a deletion — both
        providers remain listed.

        Design: Difficulty/compensating_invariant/merge_preserves_provider_count_minus_one
        """
        set_clock()
        a = create_provider()
        b = create_provider(npi="1234567894", location_key="LOC2")
        attr_a = add_attribute(a["id"], attribute_value="A1")
        attr_b = add_attribute(b["id"], attribute_value="B1")
        merge_providers(a["id"], b["id"])
        survivor_attrs, _ = validate_paginated(
            api.list_provider_attributes(a["id"], data_steward_headers)
        )
        survivor_attr_ids = {attr["id"] for attr in survivor_attrs}
        assert {attr_a["id"], attr_b["id"]} <= survivor_attr_ids, (
            "Both attribute records must remain attached to the survivor; "
            f"got {survivor_attr_ids}"
        )
        _, meta = validate_paginated(api.list_providers(data_steward_headers))
        assert meta["total_count"] == 2, (
            f"MERGED is a status, not a deletion: expected 2 providers, got {meta['total_count']}"
        )
