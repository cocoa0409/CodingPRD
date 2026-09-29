"""Two time-window resources with opposite endpoint semantics.

A measurement window is half-open, so a new window may start on the instant an
existing one ends.  A customer policy override occupies a closed interval, so a new
override starting on the instant an existing one ends collides.  The same adjacency
is therefore legal on one resource and refused on the other.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    ApiErrorId,
    create_intervention_deployment_payload,
    create_return_policy_override_payload,
    make_merch_ops_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402


def _build_item_with_one_scheduled_window(api: ApiClient) -> dict:
    """A listed item carrying one scheduled July deployment of a detail-imagery
    lever, plus a second lever on a different mechanism that has never been
    deployed."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api,
        name="Overlap Outfitters",
        brand_code="OVLP",
        correction_budget_cents=10000,
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="OVLP-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    imagery = fx.create_intervention(
        api,
        name="Detail imagery refresh",
        lever="DETAIL_IMAGERY",
        unit_cost_cents=1200,
    )
    measurements = fx.create_intervention(
        api,
        name="Model measurements on PDP",
        lever="PDP_MODEL_MEASUREMENTS",
        unit_cost_cents=1500,
    )
    july = fx.create_deployment(
        api,
        imagery["id"],
        item["id"],
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-08-01T00:00:00Z",
        spend_cents=1200,
    )
    return {
        "item": item,
        "imagery": imagery,
        "measurements": measurements,
        "july": july,
    }


def _deployment_payload(built: dict, lever_key: str, start: str, end: str) -> dict:
    return create_intervention_deployment_payload(
        built[lever_key]["id"],
        built["item"]["id"],
        window_start=start,
        window_end=end,
        spend_cents=1200,
    )


def test_a_window_starting_where_the_previous_one_ends_is_admitted(api):
    """PRD §3.9: "Windows are unique per item and lever: for the same combination of
    `item_id` and the lever's `lever` value, the new half-open window must not
    intersect an existing window whose deployment is neither `TERMINATED` nor
    `MEASURED`, and because the window is half-open, a new `window_start` that exactly
    equals an existing `window_end` does **not** intersect and is accepted."  The July
    window runs up to but excludes the first of August, so an August window on the same
    item and the same lever shares no instant with it.

    Design: Difficulty/resource_temporal_overlap/deployment_half_open_window_adjacency_admitted
    """
    built = _build_item_with_one_scheduled_window(api)

    assert built["july"]["status"] == "SCHEDULED"

    august = validate_success(
        api.create_intervention_deployment(
            _deployment_payload(
                built, "imagery", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
            ),
            make_merch_ops_admin_headers(),
        ),
        201,
    )

    assert august["status"] == "SCHEDULED"
    assert august["window_start"].startswith("2026-08-01T00:00:00")
    assert august["window_end"].startswith("2026-09-01T00:00:00")


def test_a_window_that_reaches_inside_the_previous_one_is_refused(api):
    """PRD §2.9: "For the same combination of `item_id` and the intervention's `lever`,
    the new half-open window from `window_start` up to but excluding `window_end` does
    not intersect an existing window whose deployment is neither `TERMINATED` nor
    `MEASURED`; touching endpoints, where the new `window_start` equals an existing
    `window_end`, do not intersect; and `window_start` must be strictly earlier than
    `window_end`."  A mid-July start against the same item and lever genuinely shares
    instants with the scheduled window, so it is refused with HTTP 409.

    Design: Difficulty/resource_temporal_overlap/deployment_half_open_window_adjacency_admitted
    """
    built = _build_item_with_one_scheduled_window(api)

    response = api.create_intervention_deployment(
        _deployment_payload(
            built, "imagery", "2026-07-15T00:00:00Z", "2026-08-15T00:00:00Z"
        ),
        make_merch_ops_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DEPLOYMENT_WINDOW_OVERLAP.value, 409)

    rows, _ = validate_paginated(
        api.list_intervention_deployments(
            make_merch_ops_admin_headers(), {"intervention_id": built["imagery"]["id"]}
        )
    )
    assert len(rows) == 1


def test_the_same_overlapping_window_is_admitted_on_a_different_lever(api):
    """PRD §3.9: "An accepted deployment opens with `status` `SCHEDULED`, its lever's
    `deployment_count` grows by 1, and all six measurement fields —
    `baseline_units_count`, `baseline_return_rate_bp`, `window_units_count`,
    `measured_return_rate_bp`, `avoided_return_count`, and `attributed_savings_cents` —
    are null, because nothing has been observed yet."  The window that collided on the
    imagery lever is accepted verbatim on the model-measurements lever, because the
    resource being reserved is the item paired with a mechanism rather than the item
    alone.

    Design: Difficulty/resource_temporal_overlap/deployment_half_open_window_adjacency_admitted
    """
    built = _build_item_with_one_scheduled_window(api)

    other = validate_success(
        api.create_intervention_deployment(
            _deployment_payload(
                built, "measurements", "2026-07-15T00:00:00Z", "2026-08-15T00:00:00Z"
            ),
            make_merch_ops_admin_headers(),
        ),
        201,
    )

    assert other["status"] == "SCHEDULED"
    assert other["baseline_units_count"] is None
    assert other["baseline_return_rate_bp"] is None
    assert other["window_units_count"] is None
    assert other["measured_return_rate_bp"] is None
    assert other["avoided_return_count"] is None
    assert other["attributed_savings_cents"] is None

    assert fx.read_intervention(api, built["measurements"]["id"])["deployment_count"] == 1


def test_the_two_admitted_windows_are_counted_on_their_own_levers(api):
    """PRD §3.9: "A lever whose only deployment is still running therefore reports 0
    net savings and stays `FUNDED`, because neither savings nor spend has been
    recognized."  Two adjacent scheduled windows leave the imagery lever with a
    deployment count of 2 and every money figure still at 0, while the other lever
    counts only its own deployment.

    Design: Difficulty/resource_temporal_overlap/deployment_half_open_window_adjacency_admitted
    """
    built = _build_item_with_one_scheduled_window(api)
    fx.create_deployment(
        api,
        built["imagery"]["id"],
        built["item"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-09-01T00:00:00Z",
        spend_cents=1200,
    )
    fx.create_deployment(
        api,
        built["measurements"]["id"],
        built["item"]["id"],
        window_start="2026-07-15T00:00:00Z",
        window_end="2026-08-15T00:00:00Z",
        spend_cents=1500,
    )

    imagery = fx.read_intervention(api, built["imagery"]["id"])
    assert imagery["deployment_count"] == 2
    assert imagery["spend_cents"] == 0
    assert imagery["gross_savings_cents"] == 0
    assert imagery["net_savings_cents"] == 0
    assert imagery["funding_posture"] == "FUNDED"

    imagery_rows, _ = validate_paginated(
        api.list_intervention_deployments(
            make_merch_ops_admin_headers(), {"intervention_id": built["imagery"]["id"]}
        )
    )
    assert len(imagery_rows) == 2

    other_rows, _ = validate_paginated(
        api.list_intervention_deployments(
            make_merch_ops_admin_headers(),
            {"intervention_id": built["measurements"]["id"]},
        )
    )
    assert len(other_rows) == 1


def _build_shopper_with_one_override(api: ApiClient) -> dict:
    """A shopper carrying one tops override that runs from the first of January
    through the thirtieth of June inclusive."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    customer = fx.create_customer(api, email="shopper-r8b@example.com")
    version_before = customer["version"]
    override = fx.create_override(
        api,
        customer["id"],
        category_code="TOPS",
        window_days=45,
        restocking_applies=False,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-06-30T00:00:00Z",
    )
    return {
        "customer": customer,
        "version_before": version_before,
        "override": override,
    }


def _override_payload(api: ApiClient, customer_id: str, **fields) -> dict:
    """A tops override pinned to the profile version as it stands right now, so the
    stale-version guard never masks the overlap rule under test."""
    body = {
        "category_code": "TOPS",
        "window_days": 20,
        "restocking_applies": True,
        "non_refundable_shipping": False,
    }
    body.update(fields)
    return create_return_policy_override_payload(
        fx.read_customer(api, customer_id)["version"], **body
    )


def test_an_override_starting_on_the_day_another_ends_collides(api):
    """PRD §3.7: "The interval an override occupies is closed at both ends, a null
    `effective_to` extends without bound, and endpoints that merely touch **do** count
    as intersecting, so an override running through the 30th and another starting on the
    30th collide and the second is refused with `ERR_POLICY_WINDOW_OVERLAP`."  The
    stored override's last effective instant is the thirtieth of June, so a second
    override that begins on that instant is refused with HTTP 409 — the adjacency a
    measurement window would have accepted.

    Design: Difficulty/resource_temporal_overlap/policy_override_closed_interval_adjacency_rejected
    """
    built = _build_shopper_with_one_override(api)

    assert built["override"]["effective_to"].startswith("2026-06-30T00:00:00")

    response = api.create_return_policy_override(
        built["customer"]["id"],
        _override_payload(
            api,
            built["customer"]["id"],
            effective_from="2026-06-30T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z",
        ),
        make_merch_ops_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP.value, 409)


def test_writing_an_override_advances_the_profile_version_it_was_pinned_to(api):
    """PRD §3.7: "A customer override is authored against one shopper's profile; the
    row is stamped with `scope` `CUSTOMER_OVERRIDE`, its `customer_profile_id` is set to
    the profile it was authored under, and creating it increments that
    `CustomerProfile`'s `version` by 1 — which is exactly why the override write demands
    `expected_customer_profile_version` per §2.7."  Every accepted override therefore
    forces the next one to quote a fresh version, which is what makes a sequence of
    overlap attempts observable one at a time.

    Design: Difficulty/resource_temporal_overlap/policy_override_closed_interval_adjacency_rejected
    """
    built = _build_shopper_with_one_override(api)

    assert built["override"]["scope"] == "CUSTOMER_OVERRIDE"
    assert built["override"]["customer_profile_id"] == built["customer"]["id"]

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["version"] == built["version_before"] + 1


def test_an_override_starting_the_day_after_is_admitted_and_runs_open_ended(api):
    """PRD §3.7: "Either way the row declares the `category_code` it governs, a
    `window_days` base return window of at least 1 day, a `restocking_applies` boolean
    deciding whether change-of-mind resolutions withhold a restocking fee, a
    `non_refundable_shipping` boolean deciding whether the line's allocated shipping is
    withheld from the refund, an `effective_from` instant that is the first instant the
    row applies inclusive, and an optional `effective_to` instant that is the last
    instant it applies inclusive — a null `effective_to` means the row is open-ended."
    Starting on the first of July clears the stored interval's closed upper end, and
    omitting the upper end leaves the new row unbounded.

    Design: Difficulty/resource_temporal_overlap/policy_override_closed_interval_adjacency_rejected
    """
    built = _build_shopper_with_one_override(api)

    open_ended = validate_success(
        api.create_return_policy_override(
            built["customer"]["id"],
            _override_payload(
                api,
                built["customer"]["id"],
                effective_from="2026-07-01T00:00:00Z",
                effective_to=None,
            ),
            make_merch_ops_admin_headers(),
        ),
        201,
    )

    assert open_ended["effective_to"] is None
    assert open_ended["scope"] == "CUSTOMER_OVERRIDE"
    assert open_ended["customer_profile_id"] == built["customer"]["id"]
    assert open_ended["window_days"] == 20


def test_the_open_ended_override_collides_with_every_later_window(api):
    """PRD §2.9: "For the same combination of `customer_profile_id` and
    `category_code`, the new override's closed interval from `effective_from` through
    `effective_to` does not intersect an existing override's closed interval, where a
    null `effective_to` is treated as unbounded and touching endpoints do intersect."
    Once the July row runs without an upper bound there is no later interval left to
    claim, so a September override is refused and the shopper keeps exactly the two
    rows that were admitted.

    Design: Difficulty/resource_temporal_overlap/policy_override_closed_interval_adjacency_rejected
    """
    built = _build_shopper_with_one_override(api)
    fx.create_override(
        api,
        built["customer"]["id"],
        category_code="TOPS",
        window_days=20,
        restocking_applies=True,
        non_refundable_shipping=False,
        effective_from="2026-07-01T00:00:00Z",
        effective_to=None,
    )

    response = api.create_return_policy_override(
        built["customer"]["id"],
        _override_payload(
            api,
            built["customer"]["id"],
            window_days=10,
            effective_from="2026-09-01T00:00:00Z",
            effective_to=None,
        ),
        make_merch_ops_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP.value, 409)

    rows, _ = validate_paginated(
        api.list_return_policies(
            make_merch_ops_admin_headers(),
            {"customer_profile_id": built["customer"]["id"]},
        )
    )
    assert len(rows) == 2
