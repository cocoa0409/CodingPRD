"""Inclusive edges and rounding order: a listing sitting exactly on the queue gate,
and a health index whose two rounding stages disagree in the second decimal."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import assert_shelf_summary, assert_slot_ledger
from test_helpers.factories import create_syndication_job_payload
from test_helpers.fixtures import read_retailer_version
from test_helpers.test_users import (
    make_content_author_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)


def _subscore_values(summary):
    """The per-listing breakdown, reduced to the one blended subscore each entry
    contributes, in the order the aggregation produced them.

    PRD 3.9 names the quantity a *subscore* and says each qualifying listing
    "contributes exactly one subscore", so an entry that also spells out the four
    components it blends is read through the field that names the subscore itself.
    """
    values = []
    for entry in summary["retailer_subscores"]:
        if isinstance(entry, dict):
            numbers = {
                key: float(value)
                for key, value in entry.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
            assert numbers, "each breakdown entry must carry its numeric subscore"
            named = [value for key, value in numbers.items() if "subscore" in key]
            if named:
                assert len(named) == 1, "an entry contributes exactly one subscore"
                values.append(named[0])
            else:
                assert len(numbers) == 1, (
                    "a breakdown entry must name its blended subscore when it also "
                    "carries the components behind it"
                )
                values.append(next(iter(numbers.values())))
        else:
            values.append(float(entry))
    return values


def test_the_image_component_earns_partial_credit_at_three_of_four(bigbox_world):
    """Three approved images against a minimum of four credit three quarters of the
    image weight — 15.00 certified against the 20.00 the claimed image_count of 4
    earns on the declared side — which is what puts certified completeness on exactly
    85.00 rather than 80.00.

    PRD 3.4: "Given a count, the image component is the full image weight of 20 when the retailer's `min_image_count` is zero; otherwise it is 20 multiplied by the smaller of 1 and the ratio of the count to `min_image_count`."
    Design: Difficulty/boundary_precision_check/certified_completeness_exactly_at_85_passes_the_queue_gate
    """
    data = validate_success(
        api_client.get_listing_completeness(
            bigbox_world["listing"]["id"], make_syndication_operator_headers()
        )
    )
    assert float(data["certified_image_component"]) == pytest.approx(15.00, abs=0.01)
    assert float(data["declared_image_component"]) == pytest.approx(20.00, abs=0.01)
    assert float(data["certified_score"]) == pytest.approx(85.00, abs=0.01)
    assert float(data["declared_score"]) == pytest.approx(90.00, abs=0.01)
    assert data["missing_required_keys"] == ["brand"]
    assert data["over_limit_keys"] == []


def test_a_listing_sitting_exactly_on_the_threshold_may_be_queued(bigbox_world):
    """The gate is inclusive at 85.00, so the six-slot job is created rather than
    refused, and it freezes the 51.00 readiness and the 13500 fee — 15000 subtotal
    less the 10 percent volume tier, with no rush ten days out.

    PRD 3.6: "The listing's `completeness_score_certified` must be at least 85.00, otherwise `ERR_COMPLETENESS_BELOW_THRESHOLD`; a listing sitting at exactly 85.00 passes."
    Design: Difficulty/boundary_precision_check/certified_completeness_exactly_at_85_passes_the_queue_gate
    """
    payload = create_syndication_job_payload(
        bigbox_world["listing"]["id"],
        bigbox_world["revision"]["id"],
        6,
        "2026-08-20T00:00:00Z",
        "2026-08-21T00:00:00Z",
        read_retailer_version(bigbox_world["retailer"]["id"]),
    )
    response = api_client.create_syndication_job(payload, make_syndication_operator_headers())
    job = validate_success(response, 201)

    assert job["state"] == "QUEUED"
    assert job["slot_count"] == 6
    assert job["service_fee_cents"] == 13500
    assert float(job["readiness_at_queue"]) == pytest.approx(51.00, abs=0.01)

    retailer = get_success_data(
        api_client.get_retailer(bigbox_world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 6)
    assert retailer["version"] == 2


def test_each_subscore_is_rounded_before_the_index_averages_them(alpha_beta_world):
    """The two qualifying listings produce raw subscores of 60.0050 and 70.0150.
    Rounding each first gives (60.01 + 70.02) / 2 == 65.015, which rounds half up to
    65.02; averaging the raw values would have given 65.01.

    PRD 3.9: "The index is then the arithmetic mean of those already-rounded subscores, rounded half up to 2 decimal places again. The two-stage rounding order is mandatory and is not the same as averaging the unrounded subscores."
    Design: Difficulty/boundary_precision_check/shelf_health_index_rounds_each_subscore_before_averaging
    """
    summary = validate_success(
        api_client.get_shelf_summary(
            alpha_beta_world["product"]["id"], make_shelf_admin_headers()
        )
    )
    assert_shelf_summary(summary)
    assert float(summary["shelf_health_index"]) == pytest.approx(65.02, abs=0.001)
    assert float(summary["shelf_health_index"]) != pytest.approx(65.01, abs=0.001)
    assert summary["qualifying_listing_count"] == 2

    product = validate_success(
        api_client.get_product(alpha_beta_world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(65.02, abs=0.001)


def test_the_breakdown_lists_the_rounded_subscores_in_created_at_order(alpha_beta_world):
    """The AlphaMart listing was opened first, so its 60.01 subscore precedes
    BetaMart's 70.02 in the breakdown, and both are already rounded.

    PRD 3.9: "Qualifying listings are processed in ascending `created_at` order, and each contributes exactly one subscore regardless of how many observations it has accumulated."
    Design: Difficulty/boundary_precision_check/shelf_health_index_rounds_each_subscore_before_averaging
    """
    summary = validate_success(
        api_client.get_shelf_summary(
            alpha_beta_world["product"]["id"], make_shelf_admin_headers()
        )
    )
    values = _subscore_values(summary)
    assert len(values) == 2
    assert values[0] == pytest.approx(60.01, abs=0.001)
    assert values[1] == pytest.approx(70.02, abs=0.001)


def test_an_empty_base_group_forces_the_lift_to_zero(alpha_beta_world):
    """Both observations are stamped after the product's last pin, so the default
    variant puts both in HIGH and leaves BASE empty, which forces the 0.00 fallback
    rather than a division.

    PRD 3.9: "Those observations are split into a HIGH group and a BASE group by the selected variant. If either group is empty the lift is 0.00."
    Design: Difficulty/boundary_precision_check/shelf_health_index_rounds_each_subscore_before_averaging
    """
    summary = validate_success(
        api_client.get_shelf_summary(
            alpha_beta_world["product"]["id"], make_shelf_admin_headers()
        )
    )
    assert summary["lift_variant"] == "post_pin_window"
    assert float(summary["conversion_lift_pct"]) == pytest.approx(0.00, abs=0.01)
    assert summary["high_group_size"] == 2
    assert summary["base_group_size"] == 0


def test_the_two_listings_carry_their_own_penalised_readiness(alpha_beta_world):
    """AlphaMart blends 85.00 certified with its 40.10 accuracy for 67.04 with no
    penalty, while BetaMart blends 85.00 with 60.10 and then loses 5 points to its
    single open blocking row, landing on 70.04.

    PRD 3.4: "It blends 60 percent of the listing's `completeness_score_certified` with 40 percent of a floored accuracy figure, then subtracts a penalty for unresolved blocking feed errors and adds a bonus for live enhanced content, clamps the result to the range 0 to 100, and rounds half up to 2 decimal places."
    Design: Difficulty/boundary_precision_check/shelf_health_index_rounds_each_subscore_before_averaging
    """
    alpha_listing = validate_success(
        api_client.get_retailer_listing(
            alpha_beta_world["alpha_listing"]["id"], make_shelf_admin_headers()
        )
    )
    assert alpha_listing["syndication_state"] == "LIVE"
    assert alpha_listing["open_blocking_error_count"] == 0
    assert float(alpha_listing["readiness_score"]) == pytest.approx(67.04, abs=0.01)

    beta_listing = validate_success(
        api_client.get_retailer_listing(
            alpha_beta_world["beta_listing"]["id"], make_shelf_admin_headers()
        )
    )
    assert beta_listing["syndication_state"] == "ERROR_HOLD"
    assert beta_listing["open_blocking_error_count"] == 1
    assert float(beta_listing["readiness_score"]) == pytest.approx(70.04, abs=0.01)


def test_pinning_a_second_revision_onto_a_second_listing_supersedes_nothing(alpha_beta_world):
    """The BetaMart pin replaced a null pointer, so there was no previously pinned
    revision to demote: both revisions stay PINNED, each holding its single listing
    reference.

    PRD 3.5: "Whatever revision that listing's `pinned_content_version_id` previously named, if any, transitions `PINNED → SUPERSEDED` and has its `pin_count` recomputed downward, losing exactly the one listing reference it held."
    Design: Difficulty/boundary_precision_check/shelf_health_index_rounds_each_subscore_before_averaging
    """
    for key in ("revision_1", "revision_2"):
        revision = validate_success(
            api_client.get_content_version(
                alpha_beta_world[key]["id"], make_content_author_headers()
            )
        )
        assert revision["state"] == "PINNED"
        assert revision["pin_count"] == 1
