"""Effective-dated attribute timeline: date-range validation, adjacency, truncation,
retro split, retro-approval OCC, and as-of filtering (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    add_attribute,
    assert_interval_set,
    create_provider,
    create_provider_attribute_payload,
    create_source,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDateRangeValidation:
    def test_term_equal_to_effective_rejected(self, api, data_steward_headers):
        """PRD §3.4: "when `term_date` is present it must fall strictly after
        `effective_date`, or the request fails with `ERR_INVALID_DATE_RANGE`
        (HTTP 422)."

        Design: Corner/entities/provider_attribute_term_before_effective_rejected
        """
        set_clock()
        provider = create_provider()
        res = api.create_provider_attribute(
            provider["id"],
            create_provider_attribute_payload(
                effective_date="2026-01-01", term_date="2026-01-01"
            ),
            data_steward_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestAdjacency:
    def test_adjacent_insert_keeps_incumbent(self, api, data_steward_headers):
        """PRD §3.4: "One boundary case is deliberately gentle: when the incoming
        `effective_date` equals an existing interval's `term_date` exactly, the two
        intervals are adjacent rather than overlapping, so nothing is superseded, no
        conflict is raised, and both remain `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/attribute_interval_adjacency_no_supersede
        """
        set_clock()
        create_source(source_code="SRC_O", precedence_rank=1)
        provider = create_provider()
        a1 = add_attribute(
            provider["id"], attribute_value="V1",
            effective_date="2026-01-01", term_date="2026-06-01",
        )
        add_attribute(provider["id"], attribute_value="V2", effective_date="2026-06-01")
        a1_after = validate_success(
            api.get_provider_attribute(a1["id"], data_steward_headers)
        )
        assert a1_after["status"] == "ACTIVE", (
            f"Adjacent insert must not supersede the incumbent, got {a1_after['status']}"
        )
        assert a1_after["term_date"] == "2026-06-01", (
            f"Incumbent term_date must be untouched, got {a1_after['term_date']}"
        )

    def test_adjacent_insert_lands_active(self, api, data_steward_headers):
        """PRD §3.4: "when the incoming `effective_date` equals an existing interval's
        `term_date` exactly, the two intervals are adjacent rather than overlapping, so
        nothing is superseded, no conflict is raised, and both remain `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/attribute_interval_adjacency_no_supersede
        """
        set_clock()
        create_source(source_code="SRC_O2", precedence_rank=1)
        provider = create_provider()
        add_attribute(
            provider["id"], attribute_value="V1",
            effective_date="2026-01-01", term_date="2026-06-01",
        )
        a2 = add_attribute(provider["id"], attribute_value="V2", effective_date="2026-06-01")
        assert a2["status"] == "ACTIVE", (
            f"Adjacent incoming interval must land ACTIVE, got {a2['status']}"
        )
        assert a2["effective_date"] == "2026-06-01"


class TestTruncationInvariant:
    def test_forward_insert_truncates_open_incumbent(self, api, data_steward_headers):
        """PRD §3.4: "Any existing interval that begins strictly before the incoming
        `effective_date` and extends past it — open-ended, or with a `term_date` later
        than the incoming `effective_date` — is truncated instead: its `term_date` is
        rewritten to the incoming `effective_date` and it remains `ACTIVE` over the
        shortened span."

        Design: Difficulty/compensating_invariant/attribute_timeline_no_gap_no_overlap
        """
        set_clock()
        create_source(source_code="SRC_I", precedence_rank=1)
        provider = create_provider()
        a1 = add_attribute(provider["id"], attribute_value="V1", effective_date="2026-01-01")
        add_attribute(provider["id"], attribute_value="V2", effective_date="2026-06-01")
        a1_after = validate_success(
            api.get_provider_attribute(a1["id"], data_steward_headers)
        )
        assert a1_after["status"] == "ACTIVE"
        assert a1_after["term_date"] == "2026-06-01", (
            "Open-ended incumbent must be truncated at the incoming start, "
            f"got term_date={a1_after['term_date']}"
        )

    def test_timeline_covers_without_gap_or_overlap(self, api, data_steward_headers):
        """PRD §3.4: "Attribute values are effective-dated as half-open intervals: a
        value applies from its `effective_date`, inclusive, until its `term_date`,
        exclusive, and a null `term_date` means the value is open-ended." A forward
        insert plus its compensating truncation leaves the ACTIVE timeline gapless and
        overlap-free.

        Design: Difficulty/compensating_invariant/attribute_timeline_no_gap_no_overlap
        """
        set_clock()
        create_source(source_code="SRC_I2", precedence_rank=1)
        provider = create_provider()
        add_attribute(provider["id"], attribute_value="V1", effective_date="2026-01-01")
        add_attribute(provider["id"], attribute_value="V2", effective_date="2026-06-01")
        attrs, _ = validate_paginated(
            api.list_provider_attributes(provider["id"], data_steward_headers)
        )
        assert_interval_set(
            attrs,
            {("2026-01-01", "2026-06-01", "V1"), ("2026-06-01", None, "V2")},
        )


class TestRetroSplit:
    def test_retro_insert_splits_interval(self, api, data_steward_headers):
        """PRD §3.4: "When the incoming `effective_date` lies in the past relative to
        the logical clock and falls strictly inside an existing interval, the existing
        interval divides into two `ACTIVE` halves around the newcomer — a left half
        spanning from the original start up to but not including the incoming start,
        and a right half spanning from the incoming end up to but not including the
        original end, with the right half carrying the old value and an `effective_date`
        equal to the incoming `term_date`."

        Design: Corner/calculations/retro_variant_split_creates_right_half
        """
        set_clock()
        create_source(source_code="C5", precedence_rank=1)
        provider = create_provider()
        add_attribute(
            provider["id"], attribute_value="V1",
            effective_date="2026-01-01", term_date="2026-12-31",
        )
        add_attribute(
            provider["id"], attribute_value="V2",
            effective_date="2026-04-01", term_date="2026-07-01",
        )
        attrs, _ = validate_paginated(
            api.list_provider_attributes(provider["id"], data_steward_headers)
        )
        assert_interval_set(
            attrs,
            {
                ("2026-01-01", "2026-04-01", "V1"),
                ("2026-04-01", "2026-07-01", "V2"),
                ("2026-07-01", "2026-12-31", "V1"),
            },
        )


class TestRetroApprovalOcc:
    def test_approve_retro_stale_version_rejected(self, api, data_steward_headers):
        """PRD §2.7: "Approving a retro-effective attribute — `POST
        /pdm/provider-attributes/{id}/approve-retro` — requires the non-optional field
        `expected_provider_version`, carrying the last observed `version` of the owning
        provider. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412): the
        interval timeline the approver reviewed no longer matches the stored timeline."
        PRD §3.4: "when the incoming interval's `effective_date` precedes every existing
        effective date in the group and applying it would rewrite the historically-first
        value, the incoming interval does not apply at all — it enters `RETRO_PENDING`
        and waits for steward adjudication."

        Design: Corner/complexity_layers/occ_retro_approve_stale_provider_version
        """
        set_clock()
        create_source(source_code="CL1", precedence_rank=1)
        provider = create_provider()
        captured_version = provider["version"]
        # First value in the group applies immediately.
        add_attribute(provider["id"], attribute_value="V1", effective_date="2026-02-01")
        # Earlier-starting value rewriting the historically-first value -> RETRO_PENDING.
        retro = add_attribute(provider["id"], attribute_value="V0", effective_date="2026-01-01")
        assert retro["status"] == "RETRO_PENDING", (
            f"Setup: retro rewrite must land RETRO_PENDING, got {retro['status']}"
        )
        # Intervening write advances the provider version (PRD §3.4).
        add_attribute(
            provider["id"], attribute_key="fax", attribute_value="F1",
            effective_date="2026-08-01",
        )
        res = api.approve_retro_attribute(
            retro["id"],
            {"expected_provider_version": captured_version},
            data_steward_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)


class TestAsOfFiltering:
    def test_as_of_date_returns_interval_in_force(self, api, data_steward_headers):
        """PRD §3.4: "Attribute listings support point-in-time review: the per-provider
        listing accepts optional `attribute_group`, `status`, and `as_of_date` filters"
        and "a value applies from its `effective_date`, inclusive, until its
        `term_date`, exclusive, and a null `term_date` means the value is open-ended."

        Design: Corner/complexity_layers/soft_delete_term_dated_attribute_excluded_from_as_of
        """
        set_clock()
        provider = create_provider()
        a1 = add_attribute(
            provider["id"], attribute_value="V1",
            effective_date="2026-01-01", term_date="2026-04-01",
        )
        a2 = add_attribute(provider["id"], attribute_value="V2", effective_date="2026-04-01")
        attrs, _ = validate_paginated(
            api.list_provider_attributes(
                provider["id"], data_steward_headers, params={"as_of_date": "2026-03-01"}
            )
        )
        returned_ids = {a["id"] for a in attrs}
        assert a1["id"] in returned_ids, (
            "The [2026-01-01, 2026-04-01) interval applies on 2026-03-01 and must be listed"
        )
        assert a2["id"] not in returned_ids, (
            "The interval starting 2026-04-01 does not yet apply on 2026-03-01"
        )
