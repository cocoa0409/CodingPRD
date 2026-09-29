"""Entity shape, defaults, computed fields and not-found mapping."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    NOT_FOUND_UUID,
    NO_AUTH_HEADERS,
    OMIT,
    ApiErrorId,
    COACH_A_HEADERS,
    assert_common_record_fields,
    assert_pagination_meta,
    contract_version,
    create_enrollment,
    create_provider_payload,
    create_substitute,
    provider_with_contract,
)

# Local setup builders


def _apply(api, **overrides):
    """Apply as an unauthenticated prospective home and return the raw response."""
    return api.apply_provider(create_provider_payload(**overrides), NO_AUTH_HEADERS)


# Entities


def test_apply_returns_201_and_the_whole_provider_row(api):
    """A complete application returns 201 with every Provider field populated or nulled.

    The home lands in APPLICANT with a FROZEN posture, an UNRATED tier, a NONE variant, a
    zero score, no projected revenue, no open findings and version 1. The licensing details
    it volunteered are held back as null until the network verifies them.

    PRD: "The new provider lands in `APPLICANT` membership status with a `FROZEN` posture, a
    `quality_score` of 0, a `quality_tier` of `UNRATED`, a `quality_variant_applied` of
    `NONE`, a `network_fee_pct` of 0, an `open_finding_count` of 0, a
    `projected_monthly_revenue_cents` of 0, and a null `exit_reason`."

    Design: Corner/Entities/provider_apply_with_all_required_fields_returns_201_and_full_entity
    """
    provider = validate_success(
        _apply(
            api,
            legal_name="Alvarez Family Child Care",
            county_tier="STANDARD",
            license_number="FCC-1001",
            license_expires_on="2027-06-30T00:00:00Z",
            capacity_slots=6,
            fixed_monthly_cost_cents=237000,
        ),
        201,
    )
    assert_common_record_fields(provider, expected_version=1)
    assert provider["membership_status"] == "APPLICANT"
    assert provider["network_posture"] == "FROZEN"
    assert provider["quality_tier"] == "UNRATED"
    assert provider["quality_variant_applied"] == "NONE"
    assert float(provider["quality_score"]) == 0.00
    assert float(provider["network_fee_pct"]) == 0
    assert provider["legal_name"] == "Alvarez Family Child Care"
    assert provider["county_tier"] == "STANDARD"
    assert provider["fixed_monthly_cost_cents"] == 237000
    assert provider["projected_monthly_revenue_cents"] == 0
    assert provider["open_finding_count"] == 0
    assert provider["exit_reason"] is None
    assert provider["license_number"] is None
    assert provider["license_expires_on"] is None
    assert provider["capacity_slots"] is None


def test_reading_a_provider_back_returns_the_stored_row_without_writing(api):
    """The read returns the same id and the same version the application minted.

    Nothing about a GET mutates the row, so the version is still 1, and the omitted fixed
    monthly cost still carries the 180000-cent default that was applied at write time.

    PRD: "`version` is an integer that begins at 1 when the row is created and increases by
    exactly 1 on every mutation of that row, with `updated_at` refreshed to the same
    moment."

    Design: Corner/Entities/provider_get_by_id_returns_the_stored_entity_unchanged
    """
    applied = validate_success(_apply(api, fixed_monthly_cost_cents=OMIT), 201)

    read = validate_success(api.get_provider(applied["id"], NETWORK_ADMIN_HEADERS))
    assert read["id"] == applied["id"]
    assert read["version"] == applied["version"] == 1
    assert read["legal_name"] == "Alvarez Family Child Care"
    assert read["fixed_monthly_cost_cents"] == 180000
    assert read["license_number"] is None
    assert read["license_expires_on"] is None


def test_provider_listing_pages_and_filters_over_three_homes(api):
    """Two pages of two report total_count 3, and the tier filter narrows to one row.

    The first page carries the earliest-created home and reports more rows beyond it; the
    second page carries the last one and reports none. Filtering on the HIGH_NEED tier
    returns just the third home, and omitting `limit` falls back to a window of ten from
    offset zero.

    PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the
    number of rows matching the filters before the page window is applied) and `has_more`
    (true when rows remain beyond the current window)."

    Design: Corner/Entities/provider_list_returns_paginated_page_with_total_count_and_has_more
    """
    first = validate_success(_apply(api, fixed_monthly_cost_cents=OMIT), 201)
    validate_success(
        _apply(
            api,
            legal_name="Brookside Family Child Care",
            license_number="FCC-2002",
            license_expires_on="2027-09-30T00:00:00Z",
            fixed_monthly_cost_cents=OMIT,
        ),
        201,
    )
    third = validate_success(
        _apply(
            api,
            legal_name="Cedar Lane Family Child Care",
            county_tier="HIGH_NEED",
            license_number="FCC-3003",
            license_expires_on="2027-11-30T00:00:00Z",
            capacity_slots=8,
            fixed_monthly_cost_cents=OMIT,
        ),
        201,
    )

    page_one, meta_one = validate_paginated(
        api.list_providers({"limit": 2, "offset": 0}, NETWORK_ADMIN_HEADERS)
    )
    assert_pagination_meta(meta_one, limit=2, offset=0, total_count=3, has_more=True)
    assert len(page_one) == 2
    assert page_one[0]["id"] == first["id"]

    page_two, meta_two = validate_paginated(
        api.list_providers({"limit": 2, "offset": 2}, NETWORK_ADMIN_HEADERS)
    )
    assert_pagination_meta(meta_two, limit=2, offset=2, total_count=3, has_more=False)
    assert len(page_two) == 1
    assert page_two[0]["id"] == third["id"]

    filtered, meta_filtered = validate_paginated(
        api.list_providers({"county_tier": "HIGH_NEED"}, NETWORK_ADMIN_HEADERS)
    )
    assert meta_filtered["total_count"] == 1
    assert len(filtered) == 1
    assert filtered[0]["id"] == third["id"]

    _, meta_default = validate_paginated(api.list_providers(None, NETWORK_ADMIN_HEADERS))
    assert meta_default["limit"] == 10
    assert meta_default["offset"] == 0


def test_each_missing_path_id_reports_its_own_not_found_code(api):
    """Twelve resource types answer a missing id with twelve distinct 404 codes.

    A single generic not-found code would tell the caller nothing about which link in the
    URL was broken, so every path-parameterised resource names its own type.

    PRD: "**Path existence.** Every id embedded in the URL exists, validated left to right.
    HTTP 404, with the code naming the missing resource type: `ERR_PROVIDER_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_FOOD_CLAIM_NOT_FOUND`,
    `ERR_SUBSTITUTE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND` or `ERR_ORDER_NOT_FOUND`."

    Design: Corner/Entities/unknown_path_ids_return_the_entity_specific_not_found_error
    """
    probes = (
        (api.get_provider(NOT_FOUND_UUID, NETWORK_ADMIN_HEADERS), ApiErrorId.PROVIDER_NOT_FOUND),
        (
            api.get_agreement(NOT_FOUND_UUID, NETWORK_ADMIN_HEADERS),
            ApiErrorId.AGREEMENT_NOT_FOUND,
        ),
        (
            api.get_enrollment(NOT_FOUND_UUID, NETWORK_ADMIN_HEADERS),
            ApiErrorId.ENROLLMENT_NOT_FOUND,
        ),
        (api.get_contract(NOT_FOUND_UUID, NETWORK_ADMIN_HEADERS), ApiErrorId.CONTRACT_NOT_FOUND),
        (api.get_claim(NOT_FOUND_UUID, NETWORK_ADMIN_HEADERS), ApiErrorId.CLAIM_NOT_FOUND),
        (
            api.reverse_remittance(
                NOT_FOUND_UUID, {"reversal_reason": "probe"}, FISCAL_OFFICER_HEADERS
            ),
            ApiErrorId.REMITTANCE_NOT_FOUND,
        ),
        (
            api.get_food_claim(NOT_FOUND_UUID, FISCAL_OFFICER_HEADERS),
            ApiErrorId.FOOD_CLAIM_NOT_FOUND,
        ),
        (
            api.get_substitute(NOT_FOUND_UUID, NETWORK_ADMIN_HEADERS),
            ApiErrorId.SUBSTITUTE_NOT_FOUND,
        ),
        (
            api.get_assignment(NOT_FOUND_UUID, NETWORK_ADMIN_HEADERS),
            ApiErrorId.ASSIGNMENT_NOT_FOUND,
        ),
        (api.get_visit(NOT_FOUND_UUID, COACH_A_HEADERS), ApiErrorId.VISIT_NOT_FOUND),
        (api.get_review(NOT_FOUND_UUID, COACH_A_HEADERS), ApiErrorId.REVIEW_NOT_FOUND),
        (api.get_order(NOT_FOUND_UUID, NETWORK_ADMIN_HEADERS), ApiErrorId.ORDER_NOT_FOUND),
    )
    for response, expected in probes:
        body = validate_error(response, expected.value, 404)
        assert body["message"], f"{expected.value} carried an empty message"


def test_omitting_the_fixed_monthly_cost_stores_the_declared_default(api):
    """An application that stays silent about cost is stored at 180000 cents, not 0.

    The default is applied at write time rather than at read time, so a follow-up read of
    the same row reports the same figure.

    PRD: "A prospective home may also declare `fixed_monthly_cost_cents`, its reported fixed
    monthly operating cost, which must not be negative and defaults to 1,800 dollars — that
    is, 180000 cents — when the field is omitted; revenue modeling later leans on this
    figure heavily."

    Design: Corner/Entities/provider_apply_omitting_fixed_monthly_cost_applies_the_180000_default
    """
    applied = validate_success(_apply(api, fixed_monthly_cost_cents=OMIT), 201)
    assert applied["fixed_monthly_cost_cents"] == 180000

    read = validate_success(api.get_provider(applied["id"], NETWORK_ADMIN_HEADERS))
    assert read["fixed_monthly_cost_cents"] == 180000


def test_slot_commitment_is_derived_from_subsidy_certification_not_from_the_body(api):
    """A subsidy child commits a slot and a private child does not, whatever the body says.

    The private application even asks for `slot_committed` to be true; the field is derived
    from `subsidy_certified` and the request value is ignored. Only one of the two children
    consumes a slot, so the contract reports 1 committed and 3 available, and the omitted
    absence rate carries its 50 percent default.

    PRD: "When `subsidy_certified` is true, the enrollment commits a slot on the provider's
    `ACTIVE` subsidy contract — taking the earliest-created `ACTIVE` contract when more than
    one exists — by increasing the contract's `committed_slots` by one, decreasing its
    `available_slots` by one, and setting the enrollment's `slot_committed` to true."

    Design: Corner/Entities/enrollment_slot_committed_is_computed_and_client_supplied_value_is_ignored
    """
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
        contract_overrides={"contracted_slots": 4},
    )
    subsidy_child = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )
    private_child = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-2",
        family_name="Brody",
        days_per_week=3,
        private_monthly_tuition_cents=90000,
        subsidy_certified=False,
        slot_committed=True,
    )
    assert subsidy_child["slot_committed"] is True
    assert private_child["slot_committed"] is False

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["committed_slots"] == 1
    assert contract["available_slots"] == 3
    assert contract["absence_rate_pct"] == 50

    stored = validate_success(api.get_enrollment(private_child["id"], NETWORK_ADMIN_HEADERS))
    assert stored["slot_committed"] is False


def test_housekeeping_fields_are_minted_and_bumped_by_the_server_alone(api):
    """Verification raises version 1 to 2 and leaves created_at exactly where it was.

    The client cannot set any of the four housekeeping fields, and the id it was given is
    the id it keeps. Verification is also the point at which the authoritative licensing
    values overwrite whatever the applicant claimed.

    PRD: "Network staff record the state's verification result, supplying the authoritative
    `license_number` and `license_expires_on` and, when the state adjusted it, a revised
    `capacity_slots`; all supplied values overwrite whatever the applicant had claimed."

    Design: Corner/Entities/provider_system_fields_are_server_generated_and_body_values_ignored
    """
    applied = validate_success(_apply(api, fixed_monthly_cost_cents=OMIT), 201)
    assert applied["version"] == 1

    verified = validate_success(
        api.verify_license(
            applied["id"],
            {
                "license_number": "FCC-1001-R2",
                "license_expires_on": "2027-06-30T00:00:00Z",
                "capacity_slots": 8,
            },
            NETWORK_ADMIN_HEADERS,
        )
    )
    assert_common_record_fields(verified, expected_version=2)
    assert verified["created_at"] == applied["created_at"]
    assert verified["id"] == applied["id"]
    assert verified["license_number"] == "FCC-1001-R2"
    assert verified["capacity_slots"] == 8
    assert verified["membership_status"] == "PENDING_AGREEMENT"


def test_capacity_and_tier_constraints_reject_out_of_range_applications(api):
    """13, 0 and an unknown tier are all 400s while a capacity of exactly 12 is accepted.

    Capacity is bounded at both ends and the tier is an enum, so three of the four
    applications never create a row; the only surviving provider is the one that asked for
    the maximum licensed capacity.

    PRD: "**Request shape.** All required fields present; enum values inside their declared
    sets; integer amounts non-negative; `capacity_slots` between 1 and 12 inclusive;
    `days_per_week` between 1 and 5 inclusive; `observation_score` between 0 and 100
    inclusive; `end_at` strictly later than `start_at`; `period_month` matching a four-digit
    year, a hyphen, and a two-digit month between 01 and 12; and every array that is
    required to be non-empty actually non-empty."

    Design: Corner/Entities/provider_apply_capacity_slots_outside_one_to_twelve_is_rejected
    """
    for legal_name, license_number, tier, capacity in (
        ("Overcap Home", "FCC-9001", "STANDARD", 13),
        ("Zerocap Home", "FCC-9002", "STANDARD", 0),
        ("Badtier Home", "FCC-9003", "MEDIUM", 6),
    ):
        validate_error(
            _apply(
                api,
                legal_name=legal_name,
                county_tier=tier,
                license_number=license_number,
                capacity_slots=capacity,
                fixed_monthly_cost_cents=OMIT,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    accepted = validate_success(
        _apply(
            api,
            legal_name="Atcap Home",
            license_number="FCC-9004",
            capacity_slots=12,
            fixed_monthly_cost_cents=OMIT,
        ),
        201,
    )
    assert accepted["membership_status"] == "APPLICANT"

    _, meta = validate_paginated(api.list_providers(None, NETWORK_ADMIN_HEADERS))
    assert meta["total_count"] == 1


def test_a_coverage_window_that_does_not_move_forward_is_rejected(api):
    """Equal and inverted windows are both 400s, and no offer is ever made.

    The shape check runs long before substitute selection, so the pool member is never
    consulted and ends the test holding no assignments at all.

    PRD: "A request names the `provider_id`, the coverage window's `start_at` and `end_at`
    instants — the window is half-open, with `end_at` strictly later than `start_at` and
    treated as exclusive — the `reason` for coverage, which is `ILLNESS`, `VACATION` or
    `TRAINING`, and the `min_credential_level` the provider insists on, which defaults to
    `NONE`."

    Design: Corner/Entities/substitute_assignment_end_at_not_after_start_at_is_rejected
    """
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["SUBSTITUTE_POOL"]},
    )
    substitute = create_substitute(
        full_name="Rosa Nunez",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2000,
        service_county_tiers=["STANDARD"],
    )

    for start_at, end_at in (
        ("2026-08-10T08:00:00Z", "2026-08-10T08:00:00Z"),
        ("2026-08-10T12:00:00Z", "2026-08-10T08:00:00Z"),
    ):
        validate_error(
            api.create_assignment(
                {
                    "provider_id": ctx["provider_id"],
                    "start_at": start_at,
                    "end_at": end_at,
                    "reason": "ILLNESS",
                    "min_credential_level": "NONE",
                },
                ctx["headers"],
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    _, meta = validate_paginated(
        api.list_substitute_assignments(substitute["id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_claim_line_naming_another_homes_child_is_refused(api):
    """Every id in the request exists, yet the line crosses an aggregate boundary.

    The enrollment belongs to the second home while the contract belongs to the first, so
    the coherence check on the body collection rejects the draft at 422 and the first
    contract is left with no claims and an untouched version.

    PRD: "**Referential coherence of body collections.** Every claim line's `enrollment_id`
    must name an enrollment of the contract's provider that is `subsidy_certified`,
    returning `ERR_CLAIM_LINE_ENROLLMENT_MISMATCH` (HTTP 422)"

    Design: Corner/Entities/claim_line_enrollment_from_another_provider_breaks_cross_aggregate_association
    """
    first = provider_with_contract(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={"contracted_slots": 4},
    )
    second = provider_with_contract(
        apply_overrides={
            "legal_name": "Brookside Family Child Care",
            "license_number": "FCC-2002",
            "license_expires_on": "2027-09-30T00:00:00Z",
            "capacity_slots": 6,
        },
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={"agency_code": "CCDF-02", "contracted_slots": 4},
    )
    other_child = create_enrollment(
        second["provider_id"],
        child_ref="CH-9",
        family_name="Brody",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )

    before_version = contract_version(first["contract_id"])
    validate_error(
        api.create_claim(
            {
                "contract_id": first["contract_id"],
                "period_month": "2026-08",
                "lines": [
                    {
                        "enrollment_id": other_child["id"],
                        "attended_days": 20,
                        "absent_days": 0,
                    }
                ],
                "expected_contract_version": before_version,
            },
            first["headers"],
        ),
        ApiErrorId.CLAIM_LINE_ENROLLMENT_MISMATCH.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_contract_claims(first["contract_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0

    contract = validate_success(api.get_contract(first["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["claimed_amount_cents"] == 0
    assert contract["version"] == before_version
