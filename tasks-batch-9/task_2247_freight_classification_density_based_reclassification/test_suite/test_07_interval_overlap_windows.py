"""Two interval rules with deliberately opposite conventions.

Negotiated exception agreements reserve half-open intervals, so touching
endpoints coexist. Repricing sample windows are closed intervals that additionally
reserve a buffer, so windows that do not even touch can still collide.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exception_agreement,
    assert_repricing_run,
    factories,
    make_pricing_analyst_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx

ANALYST = make_pricing_analyst_headers()


def _two_commodity_scenario():
    """A published standard with two commodity items and one PENDING agreement on
    the first of them covering March."""
    fx.set_clock("2026-02-01T00:00:00Z")
    customer = fx.create_customer()
    draft = fx.create_draft_tariff_version()
    first_profile = fx.create_commodity_profile(draft["id"])
    second_profile = fx.create_commodity_profile(
        draft["id"], nmfc_item="049880", description="Assorted hardware"
    )
    fx.publish_tariff_version(draft["id"])
    march = fx.create_exception_agreement(
        customer["id"],
        first_profile["id"],
        "2026-03-01T00:00:00Z",
        "2026-04-01T00:00:00Z",
        agreed_class_code=92.5,
    )
    return {
        "customer_id": customer["id"],
        "profile_one_id": first_profile["id"],
        "profile_two_id": second_profile["id"],
        "march_agreement": march,
    }


def _list_agreements_for(customer_id):
    rows, _meta = validate_paginated(
        api_client.list_exception_agreements(
            ANALYST, params={"customer_id": customer_id, "limit": 100}
        )
    )
    return rows


def _two_standard_scenario():
    """Two published standards and one DRAFT repricing run on the newer of them
    sampling 2026-03-01 through 2026-03-31."""
    fx.set_clock("2026-02-15T00:00:00Z")
    older = fx.create_published_standard(
        code="NMFC-2026A", effective_at="2026-01-01T00:00:00Z"
    )
    newer = fx.create_published_standard(
        profile_overrides={"nmfc_item": "049880", "description": "Assorted hardware"},
        code="NMFC-2026B",
        effective_at="2026-02-01T00:00:00Z",
    )
    run = fx.create_repricing_run(
        newer["tariff_version_id"], "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z"
    )
    return {
        "older_tariff_version_id": older["tariff_version_id"],
        "newer_tariff_version_id": newer["tariff_version_id"],
        "run_id": run["id"],
    }


# ==========================================================================
# Exception agreements reserve half-open intervals
# ==========================================================================


def test_an_agreement_starting_where_the_previous_one_ends_is_accepted():
    """April may begin exactly where March's agreement stops covering.

    PRD: "no two agreements in `PENDING` or `ACTIVE` may overlap on the same
    shipper-and-commodity pair, evaluated with half-open semantics so that one
    agreement ending exactly where the next begins is permitted."

    Design: Difficulty/resource_temporal_overlap/exception_agreement_half_open_adjacency_allowed_overlap_rejected
    """
    scenario = _two_commodity_scenario()

    adjacent = fx.create_exception_agreement(
        scenario["customer_id"],
        scenario["profile_one_id"],
        "2026-04-01T00:00:00Z",
        "2026-05-01T00:00:00Z",
        agreed_class_code=100,
    )

    assert_exception_agreement(adjacent)
    assert adjacent["status"] == "PENDING"
    assert adjacent["effective_from"].startswith("2026-04-01T00:00:00"), (
        f"the second agreement starts exactly where the first ends, "
        f"got {adjacent['effective_from']}"
    )
    assert adjacent["approved_by_user_id"] is None


def test_an_agreement_starting_one_second_earlier_overlaps_the_pending_one():
    """One second of intersection with a merely `PENDING` agreement is enough.

    PRD: "A pending agreement already reserves its interval: no two agreements in
    `PENDING` or `ACTIVE` may overlap on the same shipper-and-commodity pair"

    Design: Difficulty/resource_temporal_overlap/exception_agreement_half_open_adjacency_allowed_overlap_rejected
    """
    scenario = _two_commodity_scenario()

    response = api_client.create_exception_agreement(
        factories.create_exception_agreement_payload(
            scenario["customer_id"],
            scenario["profile_one_id"],
            "2026-03-31T23:59:59Z",
            "2026-04-15T00:00:00Z",
            agreed_class_code=110,
        ),
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_EXCEPTION_OVERLAP.value)
    assert scenario["march_agreement"]["status"] == "PENDING"
    assert len(_list_agreements_for(scenario["customer_id"])) == 1, (
        "the rejected agreement must not have been persisted"
    )


def test_the_same_interval_on_a_second_commodity_is_a_different_scope():
    """The reservation is keyed by the shipper-and-commodity pair, not by shipper.

    PRD: "no two agreements in `PENDING` or `ACTIVE` may overlap on the same
    shipper-and-commodity pair"

    Design: Difficulty/resource_temporal_overlap/exception_agreement_half_open_adjacency_allowed_overlap_rejected
    """
    scenario = _two_commodity_scenario()
    fx.create_exception_agreement(
        scenario["customer_id"],
        scenario["profile_one_id"],
        "2026-04-01T00:00:00Z",
        "2026-05-01T00:00:00Z",
        agreed_class_code=100,
    )

    twin = fx.create_exception_agreement(
        scenario["customer_id"],
        scenario["profile_two_id"],
        "2026-03-01T00:00:00Z",
        "2026-04-01T00:00:00Z",
        agreement_type="FAK",
        agreed_class_code=92.5,
    )

    assert twin["status"] == "PENDING"
    assert twin["agreement_type"] == "FAK"
    assert twin["commodity_profile_id"] == scenario["profile_two_id"]
    assert len(_list_agreements_for(scenario["customer_id"])) == 3, (
        "the March agreement, the adjacent April one and the twin on the second "
        "commodity all coexist"
    )


# ==========================================================================
# Repricing sample windows reserve a buffer beyond the closed interval
# ==========================================================================


def test_a_window_twelve_hours_after_the_previous_one_collides():
    """The windows do not intersect, yet the buffer rejects the second run.

    PRD: "No two runs in `DRAFT` or `MODELED` against the same standard may have
    sample windows within 24 hours of one another, evaluated with closed-interval
    semantics on both endpoints; a collision is rejected with
    `ERR_REPRICING_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/repricing_run_closed_window_with_strict_24_hour_buffer
    """
    scenario = _two_standard_scenario()

    response = api_client.create_repricing_run(
        factories.create_repricing_run_payload(
            scenario["newer_tariff_version_id"],
            "2026-03-31T12:00:00Z",
            "2026-04-20T00:00:00Z",
        ),
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_REPRICING_WINDOW_OVERLAP.value)
    existing = fx.get_repricing_run(scenario["run_id"])
    assert existing["status"] == "DRAFT"
    assert existing["impacted_customer_count"] == 0
    assert existing["aggregate_delta_cents"] == 0
    assert existing["modeled_at"] is None


def test_the_rejected_window_is_accepted_against_a_different_standard():
    """The buffer is scoped to the standard under evaluation.

    PRD: "No two runs in `DRAFT` or `MODELED` against the same standard may have
    sample windows within 24 hours of one another"

    Design: Difficulty/resource_temporal_overlap/repricing_run_closed_window_with_strict_24_hour_buffer
    """
    scenario = _two_standard_scenario()

    other = fx.create_repricing_run(
        scenario["older_tariff_version_id"],
        "2026-03-31T12:00:00Z",
        "2026-04-20T00:00:00Z",
    )

    assert_repricing_run(other)
    assert other["status"] == "DRAFT"
    assert other["new_tariff_version_id"] == scenario["older_tariff_version_id"]
    older_standard = fx.get_tariff_version(scenario["older_tariff_version_id"])
    newer_standard = fx.get_tariff_version(scenario["newer_tariff_version_id"])
    assert older_standard["status"] == "SUPERSEDED", (
        "publishing NMFC-2026B superseded NMFC-2026A"
    )
    assert (
        older_standard["superseded_by_tariff_version_id"]
        == scenario["newer_tariff_version_id"]
    )
    assert newer_standard["status"] == "PUBLISHED"
