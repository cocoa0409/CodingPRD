"""Endpoint round trips, list envelopes, optimistic concurrency and immediate consistency."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    NETWORK_ADMIN_HEADERS,
    NOT_FOUND_UUID,
    ApiErrorId,
    active_provider,
    api_client,
    apply_provider,
    assert_common_record_fields,
    assert_no_error_envelope,
    assert_order_pricing,
    assert_pagination_meta,
    claim_line,
    create_agreement_payload,
    create_assignment_payload,
    create_claim_payload,
    create_enrollment,
    create_order_payload,
    create_substitute,
    create_substitute_payload,
    order_line,
    provider_with_contract,
    verify_license,
)

# Local setup builders


def _pool_home():
    """An ACTIVE STANDARD-tier home entitled to the substitute pool."""
    return active_provider(
        apply_overrides={"county_tier": "STANDARD", "capacity_slots": 6},
        agreement_overrides={"shared_services": ["SUBSTITUTE_POOL"]},
    )


def _purchasing_home():
    """An ACTIVE home entitled to group purchasing."""
    return active_provider(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["GROUP_PURCHASING"]},
    )


# Endpoint round trips and envelopes


def test_a_pool_member_reads_back_exactly_as_it_was_created(api):
    """Every field supplied when the member joined survives the round trip untouched.

    The create response carries the five supplied fields plus the two server-set ones, and
    the subsequent read returns the identical row with the same identifier, the same
    creation stamp and the same version, because reading is not a mutation.

    PRD: "A `NetworkAdmin` adds a member by supplying their `full_name`, their
    `credential_level` — one of `NONE`, `CDA` or `CHILD_DEV_TEACHER` — the
    `clearance_expires_on` instant at which their background clearance lapses, their base
    `hourly_rate_cents`, which must be greater than zero, and the `service_county_tiers`
    they are willing to travel to, a non-empty selection from `HIGH_NEED` and `STANDARD`."

    PRD: "New members are `AVAILABLE` with an `assignment_count_completed` of 0."

    Design: Corner/Endpoints/substitute_create_then_read_round_trip_preserves_every_stored_field
    """
    created = validate_success(
        api.create_substitute(
            create_substitute_payload(
                full_name="Ada Nkemelu",
                credential_level="CDA",
                clearance_expires_on="2026-12-31T00:00:00Z",
                hourly_rate_cents=2500,
                service_county_tiers=["HIGH_NEED", "STANDARD"],
            ),
            NETWORK_ADMIN_HEADERS,
        ),
        201,
    )
    assert_common_record_fields(created, expected_version=1)
    assert created["full_name"] == "Ada Nkemelu"
    assert created["credential_level"] == "CDA"
    assert created["clearance_expires_on"][:10] == "2026-12-31"
    assert created["hourly_rate_cents"] == 2500
    assert created["service_county_tiers"] == ["HIGH_NEED", "STANDARD"]
    assert created["pool_status"] == "AVAILABLE"
    assert created["assignment_count_completed"] == 0

    fetched = validate_success(api.get_substitute(created["id"], NETWORK_ADMIN_HEADERS))
    for field in (
        "id",
        "full_name",
        "credential_level",
        "clearance_expires_on",
        "hourly_rate_cents",
        "service_county_tiers",
        "pool_status",
        "assignment_count_completed",
        "created_at",
    ):
        assert fetched[field] == created[field], field
    assert fetched["version"] == 1


def test_the_provider_list_answers_with_a_window_and_a_full_count(api):
    """Two homes match the filter, one is returned, and the meta block explains the window.

    The filter matches both applicants, so `total_count` reports two even though the page
    window admits only one row, and `has_more` is true because a row remains beyond it. The
    single row returned is the earlier-created home, since list results are ordered by
    creation. Nothing about the success envelope looks like an error.

    PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the
    number of rows matching the filters before the page window is applied) and `has_more`
    (true when rows remain beyond the current window)."

    PRD: "List results are ordered by `created_at` ascending unless a calculation explicitly
    pins a different ordering for its own internal purposes."

    Design: Corner/Endpoints/provider_list_envelope_carries_data_and_pagination_keys_on_success
    """
    first = apply_provider(
        legal_name="Alvarez Family Child Care",
        county_tier="STANDARD",
        license_number="FCC-1001",
    )
    second = apply_provider(
        legal_name="Brody Family Child Care",
        county_tier="STANDARD",
        license_number="FCC-1002",
    )
    assert second["id"] != first["id"]

    rows, meta = validate_paginated(
        api.list_providers(
            {"county_tier": "STANDARD", "limit": 1, "offset": 0}, NETWORK_ADMIN_HEADERS
        )
    )
    assert_pagination_meta(meta, limit=1, offset=0, total_count=2, has_more=True)
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert_no_error_envelope(rows[0])


def test_one_commit_prices_every_line_and_one_bad_line_kills_the_whole_order(api):
    """Three lines are priced individually in one call, and a malformed line stores nothing.

    A total quantity of sixteen selects the five percent rung, and each line is discounted
    and rounded on its own: 4750, then 5694 from a gross of 5994, then 9500. Summing the
    gross first would have disagreed. A second order whose last line omits its quantity is
    a request-shape failure, so neither the malformed line nor its two well-formed
    companions are stored and the home still owns exactly one order.

    PRD: "**The rounding order is pinned:** walking the lines in the order they were
    supplied in the request body, which is also the order they are persisted in, each line's
    gross amount is its `unit_price_cents` multiplied by its `quantity`, the discounted
    amount is that gross multiplied by one minus the discount fraction and **then rounded
    half up to whole cents for that line alone**, and only those per-line rounded amounts are
    accumulated into `subtotal_cents`."

    PRD: "All required fields present; enum values inside their declared sets; integer
    amounts non-negative; `capacity_slots` between 1 and 12 inclusive; `days_per_week`
    between 1 and 5 inclusive; `observation_score` between 0 and 100 inclusive; `end_at`
    strictly later than `start_at`; `period_month` matching a four-digit year, a hyphen, and
    a two-digit month between 01 and 12; and every array that is required to be non-empty
    actually non-empty."

    Design: Corner/Endpoints/group_purchase_order_commit_prices_every_line_in_one_call_and_a_bad_line_rejects_the_whole_order
    """
    ctx = _purchasing_home()
    order = validate_success(
        api.create_order(
            create_order_payload(
                ctx["provider_id"],
                [
                    order_line("WIPES-12", 1000, 5),
                    order_line("PAPER-9", 999, 6),
                    order_line("MATS-4", 2000, 5),
                ],
                category="SUPPLIES",
            ),
            ctx["headers"],
        ),
        201,
    )

    committed = validate_success(api.commit_order(order["id"], None, ctx["headers"]))
    assert committed["status"] == "COMMITTED"
    assert_order_pricing(
        committed,
        total_quantity=16,
        discount_pct=0.05,
        subtotal_cents=19944,
        insurance_admin_fee_cents=0,
        total_cents=19944,
    )
    assert committed["subtotal_cents"] == 4750 + 5694 + 9500

    validate_error(
        api.create_order(
            {
                "provider_id": ctx["provider_id"],
                "category": "SUPPLIES",
                "lines": [
                    order_line("WIPES-12", 1000, 5),
                    order_line("PAPER-9", 999, 6),
                    {"sku": "MATS-4", "unit_price_cents": 2000},
                ],
            },
            ctx["headers"],
        ),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )

    _, meta = validate_paginated(
        api.list_provider_orders(ctx["provider_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1


def test_naming_a_pool_member_bypasses_the_selector_but_the_member_must_exist(api):
    """A named member is offered the work even when dearer, and an unknown name is a 404.

    The requested member costs 2600 against a 2000 alternative, so the selector would never
    have chosen them, yet naming them links them and leaves the cheaper member with no work
    at all. A second request naming an identifier that resolves to nothing is refused as a
    missing substitute, and the home is left with the one assignment it legitimately made.

    PRD: "A provider who has a particular pool member in mind may name a
    `requested_substitute_id`, in which case that member is honoured instead of running the
    selector."

    PRD: "Every foreign key supplied in the request body exists — `provider_id`,
    `contract_id`, `substitute_id` or `requested_substitute_id`, each `enrollment_id` named
    inside claim lines, and `receiving_provider_id`."

    Design: Corner/Endpoints/assignment_requested_substitute_link_needs_both_rows_and_returns_substitute_not_found_when_absent
    """
    ctx = _pool_home()
    cheap = create_substitute(
        full_name="Cheap Cheryl",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2000,
        service_county_tiers=["STANDARD"],
    )["id"]
    picked = create_substitute(
        full_name="Pick Petra",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2600,
        service_county_tiers=["STANDARD"],
    )["id"]

    assignment = validate_success(
        api.create_assignment(
            create_assignment_payload(
                ctx["provider_id"],
                "2026-08-05T08:00:00Z",
                "2026-08-05T12:00:00Z",
                reason="ILLNESS",
                min_credential_level="NONE",
                requested_substitute_id=picked,
            ),
            ctx["headers"],
        ),
        201,
    )
    assert assignment["substitute_id"] == picked
    assert assignment["substitute_id"] != cheap
    assert assignment["staffing_status"] == "OFFERED"

    _, picked_meta = validate_paginated(
        api.list_substitute_assignments(picked, None, NETWORK_ADMIN_HEADERS)
    )
    assert picked_meta["total_count"] == 1
    _, cheap_meta = validate_paginated(
        api.list_substitute_assignments(cheap, None, NETWORK_ADMIN_HEADERS)
    )
    assert cheap_meta["total_count"] == 0

    validate_error(
        api.create_assignment(
            create_assignment_payload(
                ctx["provider_id"],
                "2026-08-07T08:00:00Z",
                "2026-08-07T12:00:00Z",
                reason="ILLNESS",
                min_credential_level="NONE",
                requested_substitute_id=NOT_FOUND_UUID,
            ),
            ctx["headers"],
        ),
        ApiErrorId.SUBSTITUTE_NOT_FOUND.value,
        404,
    )

    _, home_meta = validate_paginated(
        api.list_provider_assignments(ctx["provider_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert home_meta["total_count"] == 1


# Optimistic concurrency


def test_re_using_the_provider_version_the_first_agreement_consumed_is_refused(api):
    """The version read before the first offer is already stale for the second one.

    Issuing the first agreement supersedes nothing but still bumps the provider's own
    version, so the number the caller held is no longer current and the second issue is
    refused. Crucially the supersede does not fire on the refused call: the live offer is
    still SENT. Re-reading the provider and retrying with the fresh number succeeds, and
    only then is the first offer withdrawn as superseded.

    PRD: "If the provider's `version` has advanced since the client last read it, the create
    is rejected with `ERR_STALE_PROVIDER_VERSION` (HTTP 412) and nothing is superseded."

    Design: Corner/Cross-Cutting Complexity Layers/stale_expected_provider_version_on_agreement_create_is_rejected_with_412
    """
    provider = apply_provider(legal_name="Alvarez Family Child Care")
    provider_id = provider["id"]
    verified = verify_license(provider_id)
    stale_version = verified["version"]

    first = validate_success(
        api.create_agreement(
            create_agreement_payload(
                provider_id,
                stale_version,
                network_fee_pct=6.0,
                shared_services=["ENROLLMENT"],
            ),
            NETWORK_ADMIN_HEADERS,
        ),
        201,
    )
    assert first["status"] == "SENT"

    validate_error(
        api.create_agreement(
            create_agreement_payload(
                provider_id,
                stale_version,
                network_fee_pct=5.0,
                shared_services=["ENROLLMENT"],
            ),
            NETWORK_ADMIN_HEADERS,
        ),
        ApiErrorId.STALE_PROVIDER_VERSION.value,
        412,
    )
    survivor = validate_success(api.get_agreement(first["id"], NETWORK_ADMIN_HEADERS))
    assert survivor["status"] == "SENT"
    assert survivor["superseded"] is False

    fresh = validate_success(api.get_provider(provider_id, NETWORK_ADMIN_HEADERS))
    assert fresh["version"] > stale_version

    second = validate_success(
        api.create_agreement(
            create_agreement_payload(
                provider_id,
                fresh["version"],
                network_fee_pct=5.0,
                shared_services=["ENROLLMENT"],
            ),
            NETWORK_ADMIN_HEADERS,
        ),
        201,
    )
    assert second["status"] == "SENT"

    superseded = validate_success(api.get_agreement(first["id"], NETWORK_ADMIN_HEADERS))
    assert superseded["status"] == "WITHDRAWN"
    assert superseded["superseded"] is True

    after = validate_success(api.get_provider(provider_id, NETWORK_ADMIN_HEADERS))
    assert after["version"] == fresh["version"] + 1


def test_a_contract_version_read_before_a_slot_commitment_no_longer_drafts_a_claim(api):
    """Committing a subsidy slot mutates the contract, so the earlier version is stale.

    The enrollment commits a slot, which changes the contract's own ledger columns and
    therefore advances its version. The claim create carrying the pre-enrollment number is
    refused and no draft is stored. Re-reading the contract and retrying with its current
    version drafts the claim, which advances the contract's version once more.

    PRD: "If the contract's `version` has advanced since the client last read it, the create
    is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

    PRD: "`version` is an integer that begins at 1 when the row is created and increases by
    exactly 1 on every mutation of that row, with `updated_at` refreshed to the same moment."

    Design: Corner/Cross-Cutting Complexity Layers/stale_expected_contract_version_on_claim_create_is_rejected_with_412
    """
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-08-01T00:00:00Z",
        },
    )
    stale_version = ctx["contract"]["version"]

    enrollment = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )
    assert enrollment["slot_committed"] is True

    validate_error(
        api.create_claim(
            create_claim_payload(
                ctx["contract_id"],
                "2026-08",
                [claim_line(enrollment["id"], 20, 0)],
                stale_version,
            ),
            ctx["headers"],
        ),
        ApiErrorId.STALE_CONTRACT_VERSION.value,
        412,
    )
    _, meta = validate_paginated(
        api.list_contract_claims(ctx["contract_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0

    fresh = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert fresh["version"] > stale_version
    assert fresh["committed_slots"] == 1

    claim = validate_success(
        api.create_claim(
            create_claim_payload(
                ctx["contract_id"],
                "2026-08",
                [claim_line(enrollment["id"], 20, 0)],
                fresh["version"],
            ),
            ctx["headers"],
        ),
        201,
    )
    assert claim["status"] == "DRAFT"

    after = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert after["version"] == fresh["version"] + 1


# Immediate consistency


def test_the_enrollment_response_already_shows_every_field_it_derived(api):
    """The write itself reports the committed slot, and the next reads need no settling time.

    The create response carries `slot_committed` true rather than leaving the caller to
    poll for it. Reading the contract immediately afterwards shows the slot ledger already
    moved to one committed and three available, and reading the home shows the projection
    already rebuilt: 99000 for the single subsidy child at 4500 a day over 22 authorized
    days, plus the 60000 the private family pays.

    PRD: "Cascades in this system are **immediate and synchronous**: by the time a response
    is returned, every hop has been applied, every touched row's `version` has advanced, and
    every derived counter is consistent with the rows it summarises."

    PRD: "`subsidy_component_cents` is the count of subsidy-bearing enrollments multiplied
    by the contract's `daily_rate_cents` — treated as zero when the provider has no such
    contract — multiplied by the 22 authorized care days in a month."

    Design: Corner/Consistency Model/enrollment_create_makes_every_derived_field_visible_in_the_same_response
    """
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-08-01T00:00:00Z",
        },
    )
    assert ctx["contract"]["committed_slots"] == 0

    create_enrollment(
        ctx["provider_id"],
        child_ref="CH-0",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=60000,
        subsidy_certified=False,
    )

    subsidy_child = validate_success(
        api_client.create_enrollment(
            {
                "provider_id": ctx["provider_id"],
                "child_ref": "CH-1",
                "family_name": "Brody",
                "days_per_week": 5,
                "private_monthly_tuition_cents": 0,
                "subsidy_certified": True,
                "start_on": "2026-08-01T00:00:00Z",
            },
            ctx["headers"],
        ),
        201,
    )
    assert subsidy_child["slot_committed"] is True
    assert subsidy_child["status"] == "ENROLLED"

    contract = validate_success(api.get_contract(ctx["contract_id"], ctx["headers"]))
    assert contract["committed_slots"] == 1
    assert contract["available_slots"] == 3

    provider = validate_success(api.get_provider(ctx["provider_id"], ctx["headers"]))
    assert provider["projected_monthly_revenue_cents"] == 159000
    assert provider["projected_monthly_revenue_cents"] == 1 * 4500 * 22 + 60000
