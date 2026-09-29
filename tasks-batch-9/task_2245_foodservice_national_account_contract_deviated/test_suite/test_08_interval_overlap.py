"""Two windowed resources with deliberately different interval semantics: a
deviation window is half-open and may touch its neighbour, while a coverage
window is closed and needs a clear changeover gap of more than fourteen days.
"""
from test_helpers import (
    AUG_31,
    OCT_START,
    SEP_14,
    SEP_15,
    SEP_START,
    TERM_START,
    api_client,
    bootstrap_partners,
    build_active_deviation,
    build_signed_contract,
    create_product,
    dc_coverage_payload,
    deviation_agreement_payload,
    read_contract_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, NAM

SEP_30 = "2026-09-30T00:00:00Z"
OCT_31 = "2026-10-31T00:00:00Z"


def _build_incumbent_deviation_world():
    """One ACTIVE deviation over the half-open window 2026-08-01 .. 2026-09-01."""
    world = bootstrap_partners()
    product = create_product(world["manufacturer_id"])
    signed = build_signed_contract(
        world["operator_id"], world["manufacturer_id"], world["dc_id"]
    )
    world.update(signed)
    world["product_id"] = product["id"]
    world["incumbent"] = build_active_deviation(
        signed["contract_id"],
        product["id"],
        world["manufacturer_id"],
        4500,
        TERM_START,
        SEP_START,
        requested_net_price_cents=3900,
    )
    return world


def _deviation_window_payload(world, effective_from, effective_to, net_price):
    """The contract version is re-read every time so the concurrency guard can
    never answer ahead of the window comparison."""
    return deviation_agreement_payload(
        world["contract_id"],
        world["product_id"],
        world["manufacturer_id"],
        read_contract_version(world["contract_id"]),
        4500,
        effective_from,
        effective_to,
        requested_net_price_cents=net_price,
    )


class TestDeviationWindowsAreHalfOpen:
    def test_a_window_starting_where_the_incumbent_ends_is_accepted(self):
        """PRD §3.4: "Touching endpoints are explicitly fine — a previous
        agreement whose `effective_to` equals the new `effective_from` is not an
        overlap — while any true intersection is `ERR_DEVIATION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/deviation_windows_half_open_touching_endpoints_allowed
        """
        world = _build_incumbent_deviation_world()
        incumbent = world["incumbent"]
        assert incumbent["status"] == "ACTIVE"
        assert incumbent["effective_to"].startswith("2026-09-01T00:00:00")

        successor = validate_success(
            api_client.create_deviation_agreement(
                _deviation_window_payload(world, SEP_START, OCT_START, 3950), ANALYST
            ),
            201,
        )

        assert successor["status"] == "DRAFT"
        assert successor["effective_from"].startswith("2026-09-01T00:00:00")
        assert successor["deviated_price_cents"] == 3950

    def test_a_window_starting_one_day_earlier_truly_intersects(self):
        """PRD §2.5: "A `DeviationAgreement` window `[effective_from,
        effective_to)` is **half-open**: the deviated price applies from
        `effective_from` inclusive up to but excluding `effective_to`."

        Design: Difficulty/resource_temporal_overlap/deviation_windows_half_open_touching_endpoints_allowed
        """
        world = _build_incumbent_deviation_world()

        validate_success(
            api_client.create_deviation_agreement(
                _deviation_window_payload(world, SEP_START, OCT_START, 3950), ANALYST
            ),
            201,
        )
        refused = api_client.create_deviation_agreement(
            _deviation_window_payload(world, AUG_31, SEP_30, 3975), ANALYST
        )
        validate_error(refused, "ERR_DEVIATION_PERIOD_OVERLAP", 409)

        rows, meta = validate_paginated(
            api_client.list_deviation_agreements(
                ANALYST,
                {
                    "contract_id": world["contract_id"],
                    "product_id": world["product_id"],
                },
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


def _build_single_coverage_world():
    """An ACTIVE contract whose only coverage row on DC-SEA ends 2026-08-31, so
    every further coverage request is measured against that date."""
    world = bootstrap_partners()
    create_product(world["manufacturer_id"])
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        coverages=[{"coverage_from": TERM_START, "coverage_to": AUG_31}],
    )
    world.update(signed)
    world["first_coverage"] = signed["coverages"][0]
    return world


def _changeover_payload(world, coverage_from):
    return dc_coverage_payload(
        world["contract_id"],
        world["dc_id"],
        coverage_from=coverage_from,
        coverage_to=OCT_31,
    )


class TestCoverageChangeoverBuffer:
    def test_a_gap_of_exactly_fourteen_days_is_still_too_short(self):
        """PRD §3.2: "For every existing `ACTIVE` coverage row on the same
        contract and the same center, the two closed intervals must be disjoint
        **and** the clear gap between them, measured as the later row's
        `coverage_from` minus the earlier row's `coverage_to`, must be strictly
        greater than fourteen days."

        Design: Difficulty/resource_temporal_overlap/dc_coverage_intervals_closed_with_fourteen_day_changeover_buffer
        """
        world = _build_single_coverage_world()
        assert world["first_coverage"]["status"] == "ACTIVE"
        assert world["first_coverage"]["coverage_to"].startswith("2026-08-31T00:00:00")

        five_day_gap = api_client.create_dc_coverage(
            _changeover_payload(world, "2026-09-05T00:00:00Z"), NAM
        )
        validate_error(five_day_gap, "ERR_DC_COVERAGE_BUFFER_CONFLICT", 409)

        fourteen_day_gap = api_client.create_dc_coverage(
            _changeover_payload(world, SEP_14), NAM
        )
        validate_error(fourteen_day_gap, "ERR_DC_COVERAGE_BUFFER_CONFLICT", 409)

    def test_a_fifteen_day_gap_clears_the_buffer(self):
        """PRD §3.2: "Unlike deviation windows, coverage windows may not merely
        avoid overlapping — a distribution center needs a changeover buffer."

        Design: Difficulty/resource_temporal_overlap/dc_coverage_intervals_closed_with_fourteen_day_changeover_buffer
        """
        world = _build_single_coverage_world()

        api_client.create_dc_coverage(_changeover_payload(world, SEP_14), NAM)
        accepted = validate_success(
            api_client.create_dc_coverage(_changeover_payload(world, SEP_15), NAM), 201
        )

        assert accepted["status"] == "ACTIVE"
        assert accepted["coverage_from"].startswith("2026-09-15T00:00:00")

        rows, meta = validate_paginated(
            api_client.list_dc_coverages(
                NAM,
                {
                    "contract_id": world["contract_id"],
                    "distribution_center_id": world["dc_id"],
                },
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
