"""Requests that fail two ways at once and must report the earlier band.

Check precedence is part of the contract, so each of these builds a request with
two genuine violations in different bands and pins which one the response names.
"""

from test_helpers import (
    PLANNER,
    SEALER,
    STANDARD_KITS,
    accept_quote_payload,
    assert_credit_ledger_conserved,
    assert_order_dimensions,
    assert_weight,
    chain_accepted_order,
    chain_approved_design,
    chain_locked_configuration,
    connection_component_payload,
    create_drawing_package,
    create_quote,
    get_builder,
    get_design,
    get_drawing_package,
    get_order,
    get_quote,
    issue_quote,
    make_builder_headers,
    member_component_payload,
    release_payload,
    set_clock,
    validate_error,
)

#: A heavier bill than the parametric estimate, so the FINAL reprice at release
#: raises the price and needs credit the builder does not have.
HEAVY_BILL = [
    member_component_payload(
        mark="C-1", member_type="COLUMN", quantity=20, length_ft=24.5, weight_per_ft=62.35
    ),
    member_component_payload(
        mark="R-1", member_type="RAFTER", quantity=16, length_ft=51.25, weight_per_ft=48.7
    ),
    connection_component_payload(
        mark="K-1", connection_type="KNEE", capacity_moment_kip_ft=1100
    ),
    connection_component_payload(
        mark="B-1", connection_type="BASE", capacity_moment_kip_ft=900,
        erection_stage="ANCHORAGE",
    ),
]


def _order_with_an_unsealed_package_and_no_credit_headroom():
    """A BRONZE builder whose whole credit line is committed to this order."""
    chain = chain_accepted_order(
        builder_overrides={
            "name": "Thin Margin Erectors",
            "tier": "BRONZE",
            "credit_limit_cents": 10019831,
        },
        kits=STANDARD_KITS,
        accept_overrides={
            "job_site_code": "SITE-B",
            "requested_erection_start_date": "2026-09-20T00:00:00Z",
        },
    )
    chain_approved_design(chain, components=HEAVY_BILL)
    chain["package"] = create_drawing_package(
        chain["design"]["id"], chain["jurisdiction"]["id"],
        sealing_license_state="TX", sheet_count=18,
    )
    chain["order"] = get_order(chain["order"]["id"])
    return chain


def _approved_design_missing_its_base_detail_with_a_foreign_licence():
    """An approved design with a knee but no base, packaged under an OK licence."""
    chain = chain_locked_configuration()
    chain_approved_design(
        chain,
        components=[
            member_component_payload(),
            connection_component_payload(
                mark="K-1", connection_type="KNEE", capacity_moment_kip_ft=1100
            ),
        ],
    )
    chain["package"] = create_drawing_package(
        chain["design"]["id"], chain["jurisdiction"]["id"],
        sealing_license_state="OK", sheet_count=12,
    )
    return chain


def _issued_quote_past_its_validity_and_over_its_credit_line():
    """An issued quote read after its thirty-day window, on a tiny credit line."""
    chain = chain_locked_configuration(
        jurisdiction_overrides={
            "code": "TX-TRAVIS",
            "name": "Travis County TX",
            "territory_code": "TX-INLAND",
        },
        builder_overrides={
            "name": "Hill Country Metal",
            "tier": "BRONZE",
            "credit_limit_cents": 1000000,
        },
        kits=STANDARD_KITS,
    )
    quote = create_quote(chain["builder"]["id"], chain["configuration"]["id"])
    chain["quote"] = issue_quote(quote["id"])
    # Six days past the thirty-day validity window.
    set_clock("2026-09-10T00:00:00Z")
    return chain


def test_01_an_unsealed_package_is_reported_before_the_credit_ceiling(api):
    """Release names the seal problem even though the reprice also breaks credit.

    PRD §3.8: "The order's paperwork must be complete and unencumbered:
    ``engineering_status`` must be ``ENG_SEALED``, ``drawing_package_id`` must not
    be null, the package at that id must itself be ``SEALED``, and neither
    ``permit_hold`` nor ``commercial_hold`` may be raised — any of those four
    failing produces ``ERR_DRAWINGS_NOT_SEALED``."

    PRD §3.8: "Since the credit gate is the last band evaluated, an order that is
    both over its credit and missing a seal reports the seal problem."

    PRD §2.5: "Tenth are the states of related resources — a configuration that
    must be locked, a design that must be approved, drawings that must be sealed,
    an order that must be released, a fabrication lot that must be complete, an
    order that must be free of active work."

    Design: Difficulty/priority_pair_validation_conflict/drawings_not_sealed_beats_credit_exceeded_on_release
    """
    chain = _order_with_an_unsealed_package_and_no_credit_headroom()
    # The whole credit line is committed, so any positive reprice would break it.
    builder = get_builder(chain["builder"]["id"])
    assert chain["quote"]["quoted_price_cents"] == 10019831
    assert builder["credit_available_cents"] == 0
    # The detailed bill weighs far more than the 49680.00 parametric estimate.
    assert_weight(get_design(chain["design"]["id"])["frame_weight_lbs"], 70485.68)

    response = api.release_order_to_fabrication(
        chain["order"]["id"], release_payload(chain["order"]["version"]), PLANNER
    )

    validate_error(response, "ERR_DRAWINGS_NOT_SEALED", expected_status=409)


def test_02_the_refused_release_leaves_the_order_and_the_credit_ledger_untouched(api):
    """A short-circuited request changes nothing at all.

    PRD §2.5: "Checks are evaluated in a fixed global precedence, and the first
    failure short-circuits the request: no later check runs and no state
    changes."

    PRD §3.5: "Acceptance mints exactly one order and returns it. The new order
    copies ``quote_id``, ``builder_id`` and ``configuration_id`` from the quote;
    leaves ``engineering_design_id`` and ``drawing_package_id`` null; starts with
    ``engineering_status`` ``ENG_PENDING`` and ``production_status``
    ``PROD_NOT_RELEASED``; sets both ``permit_hold`` and ``commercial_hold`` to
    false; leaves ``final_price_cents``, ``price_delta_cents`` and ``released_at``
    null; and sets ``total_shippable_weight_lbs``, ``assigned_weight_lbs`` and
    ``unassigned_weight_lbs`` to 0."

    Design: Difficulty/priority_pair_validation_conflict/drawings_not_sealed_beats_credit_exceeded_on_release
    """
    chain = _order_with_an_unsealed_package_and_no_credit_headroom()

    api.release_order_to_fabrication(
        chain["order"]["id"], release_payload(chain["order"]["version"]), PLANNER
    )

    order = get_order(chain["order"]["id"])
    assert_order_dimensions(order, "ENG_APPROVED", "PROD_NOT_RELEASED")
    assert order["final_price_cents"] is None
    assert order["price_delta_cents"] is None
    assert order["released_at"] is None
    builder = get_builder(chain["builder"]["id"])
    assert builder["credit_used_cents"] == 10019831
    assert_credit_ledger_conserved(builder)


def test_03_a_missing_base_detail_is_reported_before_the_licence_state(api):
    """Connection completeness is band eleven; the licence match is band twelve.

    PRD §3.7: "The design must carry at least one connection detail whose
    ``connection_type`` is ``KNEE`` and at least one whose ``connection_type`` is
    ``BASE``; missing either kind fails with
    ``ERR_CONNECTION_DETAILS_INCOMPLETE``."

    PRD §3.7: "Finally, the package's ``sealing_license_state`` must equal the
    ``state_code`` of the jurisdiction at the package's ``jurisdiction_id``; a
    mismatch fails with ``ERR_SEAL_LICENSE_STATE_MISMATCH``."

    PRD §2.5: "Eleventh are the structural-safety checks on engineering content.
    Twelfth are cross-reference agreement checks: licence state against
    jurisdiction, marks against the design, stage against stage, paint colour
    against panel colour, lot type against line type."

    Design: Difficulty/priority_pair_validation_conflict/connection_details_incomplete_beats_seal_license_mismatch
    """
    chain = _approved_design_missing_its_base_detail_with_a_foreign_licence()

    response = api.seal_drawing_package(chain["package"]["id"], SEALER)

    validate_error(response, "ERR_CONNECTION_DETAILS_INCOMPLETE", expected_status=422)


def test_04_the_refused_seal_leaves_the_package_pending_and_unstamped(api):
    """None of the seal stamps are written when any of the five conditions fails.

    PRD §3.7: "A new package is ``PENDING``, with ``criteria_revision_at_seal``,
    ``sealed_at`` and ``sealed_by_user_id`` all null."

    PRD §3.7: "A successful seal stamps ``sealed_at`` with the current logical
    clock, records the acting ``X-User-ID`` as ``sealed_by_user_id``, captures the
    jurisdiction's current ``criteria_revision`` as ``criteria_revision_at_seal``,
    and sets ``status`` to ``SEALED``."

    Design: Difficulty/priority_pair_validation_conflict/connection_details_incomplete_beats_seal_license_mismatch
    """
    chain = _approved_design_missing_its_base_detail_with_a_foreign_licence()

    api.seal_drawing_package(chain["package"]["id"], SEALER)

    package = get_drawing_package(chain["package"]["id"])
    assert package["status"] == "PENDING"
    assert package["sealed_at"] is None
    assert package["sealed_by_user_id"] is None
    assert package["criteria_revision_at_seal"] is None


def test_05_an_expired_quote_is_reported_before_the_credit_ceiling(api):
    """Temporal checks are band thirteen; the fiscal checks are band fifteen.

    PRD §3.5: "The current logical clock must be at or before ``valid_until`` — an
    acceptance exactly at ``valid_until`` is still in time, one instant later is
    not — and a late acceptance fails with ``ERR_QUOTE_EXPIRED``."

    PRD §2.5: "Thirteenth are temporal checks: quote validity and window sanity.
    Fourteenth are uniqueness, capacity and sequencing constraints. Fifteenth,
    last, are the fiscal checks: the adjustment floor and the builder's credit."

    PRD §3.5: "On success ``issued_at`` is stamped with the current logical clock,
    ``valid_until`` is set to ``issued_at`` plus a validity window of thirty days,
    ``status`` becomes ``ISSUED``, and the quote's ``version`` increments."

    Design: Difficulty/priority_pair_validation_conflict/quote_expired_beats_credit_exceeded_on_accept
    """
    chain = _issued_quote_past_its_validity_and_over_its_credit_line()
    quote = get_quote(chain["quote"]["id"])
    # Issued on 2026-08-05, so the window closed on 2026-09-04.
    assert quote["valid_until"].startswith("2026-09-04T00:00:00")
    # The price is ten times the credit line, so credit would also have failed.
    assert quote["quoted_price_cents"] == 10019831
    assert get_builder(chain["builder"]["id"])["credit_available_cents"] == 1000000

    response = api.accept_quote(
        quote["id"],
        accept_quote_payload(
            job_site_code="SITE-C",
            requested_erection_start_date="2026-10-01T00:00:00Z",
        ),
        make_builder_headers(chain["builder"]["id"]),
    )

    validate_error(response, "ERR_QUOTE_EXPIRED", expected_status=422)


def test_06_the_refused_acceptance_mints_no_order_and_commits_no_credit(api):
    """The quote stays ISSUED and the credit ledger stays at zero used.

    PRD §3.5: "Acceptance is the only operation a ``Builder`` may perform, and it
    moves the quote from ``ISSUED`` to the terminal state ``ACCEPTED``."

    PRD §3.5: "In the same request the builder's ``credit_used_cents`` increases
    by the quote's ``quoted_price_cents`` and ``credit_available_cents`` is
    recomputed, the quote's ``status`` becomes ``ACCEPTED``, and both the quote's
    ``version`` and the builder's ``version`` increment."

    Design: Difficulty/priority_pair_validation_conflict/quote_expired_beats_credit_exceeded_on_accept
    """
    chain = _issued_quote_past_its_validity_and_over_its_credit_line()

    api.accept_quote(
        chain["quote"]["id"],
        accept_quote_payload(
            job_site_code="SITE-C",
            requested_erection_start_date="2026-10-01T00:00:00Z",
        ),
        make_builder_headers(chain["builder"]["id"]),
    )

    assert get_quote(chain["quote"]["id"])["status"] == "ISSUED"
    builder = get_builder(chain["builder"]["id"])
    assert builder["credit_used_cents"] == 0
    assert builder["credit_available_cents"] == 1000000
    assert_credit_ledger_conserved(builder)
