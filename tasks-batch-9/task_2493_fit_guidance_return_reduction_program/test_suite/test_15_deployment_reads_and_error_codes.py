"""Deployment endpoints and the error identifiers the program answers with.

The first group works the deployment endpoints at their quiet edges: a report on a
lever that has not started, a stop on a deployment that has not started, and a
manual stop that shortens the very window the later measurement reads.  The second
group is about identifiers: which code comes back for an unresolvable path, and
which one comes back when the request is well formed but the program refuses it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    VIOLATING_TWO_POINT_RUN,
    create_size_chart_mapping_payload,
    make_customer_headers,
    make_fit_analyst_headers,
    make_merch_ops_admin_headers,
    make_vendor_user_headers,
    resubmit_measurement_spec_payload,
    retract_fit_feedback_payload,
    terminate_deployment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

SCENARIO_START = "2026-06-01T00:00:00Z"

MODEL_MEASUREMENTS_LEVER = {
    "name": "Model measurements rollout",
    "lever": "PDP_MODEL_MEASUREMENTS",
    "unit_cost_cents": 3000,
}


def test_a_report_on_a_still_scheduled_deployment_recognizes_nothing(api):
    """PRD §3.9: "A lever whose only deployment is still running therefore reports 0 net
    savings and stays `FUNDED`, because neither savings nor spend has been recognized."
    The deployment has not even been activated, so the 4,000 cents committed to it are
    not yet recognized spend and there is nothing to offset: the computed read answers
    with zeros under the default variant, the stored lever row holds the same zeros
    beside a deployment count of 1, and the deployment's own measurement fields are
    still absent.

    Design: Corner/endpoints/savings_report_ignores_a_still_scheduled_deployment
    """
    built = fx.setup_scheduled_deployment(
        api,
        SCENARIO_START,
        intervention_overrides={
            "name": "Detail imagery refresh",
            "lever": "DETAIL_IMAGERY",
            "unit_cost_cents": 4000,
        },
        deployment_overrides={"spend_cents": 4000},
    )
    assert built["deployment"]["status"] == "SCHEDULED"

    report = validate_success(
        api.get_savings_report(built["intervention"]["id"], make_fit_analyst_headers())
    )
    assert report["variant_applied"] == "deployment_attributed"
    assert report["gross_savings_cents"] == 0
    assert report["spend_cents"] == 0
    assert report["net_savings_cents"] == 0
    assert report["measured_deployment_count"] == 0
    assert report["avoided_return_count"] == 0
    assert report["funding_posture"] == "FUNDED"

    lever = fx.read_intervention(api, built["intervention"]["id"])
    assert lever["gross_savings_cents"] == 0
    assert lever["spend_cents"] == 0
    assert lever["net_savings_cents"] == 0
    assert lever["funding_posture"] == "FUNDED"
    assert lever["deployment_count"] == 1

    deployment = fx.read_deployment(api, built["deployment"]["id"])
    assert deployment["baseline_units_count"] is None
    assert deployment["window_units_count"] is None


def test_stopping_a_deployment_that_never_started_is_refused(api):
    """PRD §3.9: "An early stop is permitted only from `ACTIVE`, otherwise
    `ERR_INVALID_DEPLOYMENT_STATE`."  Only the checkpoint can make a deployment active,
    and none has run, so there is no running deployment to stop early: the reason code
    the request carried is not recorded, the window keeps the end date it was scheduled
    with, and the lever still recognizes no spend.

    Design: Corner/endpoints/terminate_on_a_scheduled_deployment_returns_invalid_deployment_state
    """
    built = fx.setup_scheduled_deployment(
        api,
        SCENARIO_START,
        intervention_overrides=dict(MODEL_MEASUREMENTS_LEVER),
        deployment_overrides={"spend_cents": 3000},
    )

    response = api.terminate_intervention_deployment(
        built["deployment"]["id"],
        terminate_deployment_payload(terminated_reason_code="MANUAL_STOP"),
        make_merch_ops_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DEPLOYMENT_STATE.value, 409)

    deployment = fx.read_deployment(api, built["deployment"]["id"])
    assert deployment["status"] == "SCHEDULED"
    assert deployment["terminated_reason_code"] is None
    assert deployment["window_end"].startswith("2026-08-01T00:00:00")

    lever = fx.read_intervention(api, built["intervention"]["id"])
    assert lever["spend_cents"] == 0
    assert lever["funding_posture"] == "FUNDED"


def _build_manually_stopped_deployment(api: ApiClient) -> dict:
    """A deployment on an item that never sold anything: activated the day its window
    opens, then stopped by hand on the tenth, three weeks before the window was
    scheduled to close."""
    built = fx.setup_scheduled_deployment(
        api,
        SCENARIO_START,
        intervention_overrides=dict(MODEL_MEASUREMENTS_LEVER),
        deployment_overrides={
            "window_start": "2026-07-01T00:00:00Z",
            "window_end": "2026-08-01T00:00:00Z",
            "spend_cents": 3000,
        },
    )
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    built["activation_run"] = fx.run_ops_run(api)
    built["active"] = fx.read_deployment(api, built["deployment"]["id"])

    fx.set_clock(api, "2026-07-10T00:00:00Z")
    built["termination"] = fx.terminate_deployment(
        api, built["deployment"]["id"], terminated_reason_code="MANUAL_STOP"
    )
    built["lever_mid"] = fx.read_intervention(api, built["intervention"]["id"])
    return built


def test_a_manual_stop_shortens_the_window_to_the_clock(api):
    """PRD §3.9: "In every closure, where the logical clock is earlier than the stored
    `window_end`, the `window_end` is rewritten to the clock, so the measured window is
    never longer than the deployment actually ran."  The stop is also the moment the
    3,000 cents become real: before it the lever recognized nothing, and after it the
    spend stands alone against no savings at all, which is a shortfall small enough to
    be questioned rather than cut.

    Design: Corner/endpoints/manual_terminate_rewrites_window_end_and_empty_window_measures_zero
    """
    built = _build_manually_stopped_deployment(api)

    assert built["activation_run"]["deployments_activated"] == 1
    assert built["active"]["status"] == "ACTIVE"
    assert built["active"]["baseline_units_count"] == 0
    assert built["active"]["baseline_return_rate_bp"] == 0

    assert built["termination"]["status"] == "TERMINATED"
    assert built["termination"]["window_end"].startswith("2026-07-10T00:00:00")
    assert built["termination"]["terminated_reason_code"] == "MANUAL_STOP"

    assert built["lever_mid"]["spend_cents"] == 3000
    assert built["lever_mid"]["net_savings_cents"] == -3000
    assert built["lever_mid"]["funding_posture"] == "UNDER_REVIEW"


def test_the_shortened_window_measures_zero_rather_than_failing(api):
    """PRD §3.9: "A window in which nothing was delivered yields a measured rate of 0, an
    avoided count of 0, and attributed savings of 0 rather than an arithmetic error."
    The measurement reads the rewritten nine-day window rather than the scheduled month,
    and that window holds no delivered units at all, so every measured figure is zero
    and the report agrees with the stored lever row.

    Design: Corner/endpoints/manual_terminate_rewrites_window_end_and_empty_window_measures_zero
    """
    built = _build_manually_stopped_deployment(api)

    measurement_run = fx.run_ops_run(api)
    assert measurement_run["deployments_measured"] == 1
    assert measurement_run["deployments_terminated"] == 0

    deployment = fx.read_deployment(api, built["deployment"]["id"])
    assert deployment["status"] == "MEASURED"
    assert deployment["window_units_count"] == 0
    assert deployment["measured_return_rate_bp"] == 0
    assert deployment["avoided_return_count"] == 0
    assert deployment["attributed_savings_cents"] == 0

    report = fx.read_savings_report(
        api, built["intervention"]["id"], variant="deployment_attributed"
    )
    assert report["variant_applied"] == "deployment_attributed"
    assert report["gross_savings_cents"] == 0
    assert report["spend_cents"] == 3000
    assert report["net_savings_cents"] == -3000
    assert report["measured_deployment_count"] == 1
    assert report["funding_posture"] == "UNDER_REVIEW"

    lever = fx.read_intervention(api, built["intervention"]["id"])
    assert lever["measured_deployment_count"] == 1


def test_each_unresolvable_catalog_path_names_its_own_entity(api):
    """PRD §2.9: "**Path existence.** Every identifier in the URL resolves, validated
    left to right, so the leftmost unresolvable identifier decides the error:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_SPEC_NOT_FOUND`,
    `ERR_CHART_NOT_FOUND`, `ERR_MAPPING_NOT_FOUND`, `ERR_CUSTOMER_PROFILE_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_RETURN_CASE_NOT_FOUND`,
    `ERR_FEEDBACK_NOT_FOUND`, `ERR_INTERVENTION_NOT_FOUND`, or
    `ERR_DEPLOYMENT_NOT_FOUND`, each HTTP 404."  Against an empty database the five
    reference-data reads each answer with the code keyed to the entity named in their
    own path segment, never one shared not-found code and never a 400 for a
    syntactically valid identifier.

    Design: Corner/errors/unresolvable_path_ids_return_entity_specific_not_found_codes
    """
    fx.set_clock(api, SCENARIO_START)
    headers = make_merch_ops_admin_headers()

    validate_error(
        api.get_vendor(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_VENDOR_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_size_chart(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_CHART_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_size_chart_mapping(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_MAPPING_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_customer_profile(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_CUSTOMER_PROFILE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_return_policy(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_POLICY_NOT_FOUND.value,
        404,
    )


def test_each_unresolvable_transaction_path_names_its_own_entity(api):
    """PRD §2.9: "**Path existence.** Every identifier in the URL resolves, validated
    left to right, so the leftmost unresolvable identifier decides the error:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_SPEC_NOT_FOUND`,
    `ERR_CHART_NOT_FOUND`, `ERR_MAPPING_NOT_FOUND`, `ERR_CUSTOMER_PROFILE_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_RETURN_CASE_NOT_FOUND`,
    `ERR_FEEDBACK_NOT_FOUND`, `ERR_INTERVENTION_NOT_FOUND`, or
    `ERR_DEPLOYMENT_NOT_FOUND`, each HTTP 404."  The same discipline holds on the
    transactional side of the program: purchases, returns, reviews, levers and
    deployments each carry their own code, so a client can tell which segment of the
    path it got wrong.

    Design: Corner/errors/unresolvable_path_ids_return_entity_specific_not_found_codes
    """
    fx.set_clock(api, SCENARIO_START)
    headers = make_merch_ops_admin_headers()

    validate_error(
        api.get_order_line(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_ORDER_LINE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_return_case(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_RETURN_CASE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_fit_feedback(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_FEEDBACK_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_intervention(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_INTERVENTION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_intervention_deployment(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_DEPLOYMENT_NOT_FOUND.value,
        404,
    )


def test_a_mapping_cannot_be_built_on_a_specification_awaiting_verification(api):
    """PRD §2.9: "**Verified specification present.** The item has exactly one
    measurement specification in `VERIFIED`, otherwise `ERR_SPEC_NOT_VERIFIED` (409).
    Applies to size-chart-mapping creation and guidance publication."  Everything else
    about the request is in order — the chart is standardized, the pinned item version
    is current, and both pairs name labels the stored specification really declares —
    so the refusal is about the specification's standing alone and no coverage figure is
    ever computed.

    Design: Corner/errors/mapping_creation_without_a_verified_specification_returns_spec_not_verified
    """
    built = fx.setup_submitted_spec(api, SCENARIO_START)
    chart = fx.setup_standardized_chart(
        api, chart_code="STD-TOPS-E2", category_code="TOPS"
    )
    assert built["spec"]["status"] == "SUBMITTED"
    assert chart["status"] == "STANDARDIZED"

    item_version = fx.read_item(api, built["item"]["id"])["version"]
    assert item_version == 2

    response = api.create_size_chart_mapping(
        create_size_chart_mapping_payload(built["item"]["id"], chart["id"], item_version),
        make_fit_analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_SPEC_NOT_VERIFIED.value, 409)

    _, meta = validate_paginated(
        api.list_size_chart_mappings(
            make_merch_ops_admin_headers(),
            {"item_id": built["item"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "UNVERIFIED"
    assert item["version"] == 2


def test_a_listed_item_without_guidance_refuses_the_recommendation_read(api):
    """PRD §2.9: "**Guidance servable.** The item's `fit_readiness` is `GUIDANCE_READY`,
    otherwise `ERR_GUIDANCE_NOT_READY` (409). Applies to the fit-recommendation read."
    The item is on the storefront and perfectly sellable, but the two state axes are
    independent, so a read that cannot be served is a refusal on a GET rather than a
    missing resource or an empty answer.

    Design: Corner/errors/fit_recommendation_on_an_unpublished_item_returns_guidance_not_ready
    """
    built = fx.setup_listed_item(api, SCENARIO_START)
    assert built["item"]["listing_status"] == "LISTED"
    assert built["item"]["fit_readiness"] == "UNVERIFIED"

    response = api.get_fit_recommendation(
        built["item"]["id"], make_fit_analyst_headers()
    )
    validate_error(response, ApiErrorId.ERR_GUIDANCE_NOT_READY.value, 409)


def test_retracting_the_same_review_twice_is_refused(api):
    """PRD §2.9: "**Feedback still active.** The fit feedback row's `status` is `ACTIVE`,
    otherwise `ERR_FEEDBACK_ALREADY_RETRACTED` (409). Applies to fit-feedback
    retraction."  The first withdrawal drains the item's signal pool from 100 back to 0;
    the second is refused rather than quietly repeated, which is what keeps the pool
    from being driven negative by a duplicate request.

    Design: Corner/errors/retracting_feedback_twice_returns_already_retracted
    """
    built = fx.setup_listed_item(api, SCENARIO_START)
    customer = fx.create_customer(api, email="shopper-e4@example.com")

    feedback = fx.post_feedback(
        api,
        built["item"]["id"],
        customer["id"],
        purchased_size_label="M",
        fit_verdict="TOO_LARGE",
    )
    assert feedback["signal_weight"] == 100
    assert feedback["verdict_offset_centi"] == -100

    retracted = fx.retract_feedback(
        api, feedback["id"], customer["id"], retract_reason="AUTHOR_WITHDRAWN"
    )
    assert retracted["status"] == "RETRACTED"

    drained = fx.read_item(api, built["item"]["id"])
    assert drained["fit_signal_weight_total"] == 0
    assert drained["active_fit_feedback_count"] == 0

    response = api.retract_fit_feedback(
        feedback["id"],
        retract_fit_feedback_payload(retract_reason="AUTHOR_WITHDRAWN"),
        make_customer_headers(customer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FEEDBACK_ALREADY_RETRACTED.value, 409)

    stored = validate_success(
        api.get_fit_feedback(feedback["id"], make_merch_ops_admin_headers())
    )
    assert stored["status"] == "RETRACTED"
    assert stored["retract_reason"] == "AUTHOR_WITHDRAWN"
    assert fx.read_item(api, built["item"]["id"])["fit_signal_weight_total"] == 0


def test_a_resubmit_on_an_overdrawn_allowance_is_refused_as_payment_required(api):
    """PRD §2.11: "The debit is applied unconditionally, including when it pushes the
    running spend past the funded budget; the consequence of overspending is felt at the
    *next* resubmission attempt, which is refused with
    `ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED`, and in the `PROBATION` standing that
    overspending forces regardless of the reliability score."  A single failed
    verification takes a brand that funded 2,000 cents to 2,500 of spend, and the
    correction it now owes is exactly the thing it can no longer pay for: the reliability
    score is still an unremarkable 9,700, so the refusal is fiscal rather than a
    suspension, and the corrected measurements the request carried are not stored.

    Design: Corner/errors/resubmit_beyond_the_correction_budget_returns_budget_exhausted
    """
    fx.set_clock(api, SCENARIO_START)
    vendor = fx.create_vendor(api, correction_budget_cents=2000)
    item = fx.create_item(api, vendor["id"])
    spec = fx.create_spec(
        api, item["id"], vendor["id"], size_points=VIOLATING_TWO_POINT_RUN
    )
    fx.submit_spec(api, spec["id"], vendor["id"])
    verified = fx.verify_spec(api, spec["id"])
    assert verified["status"] == "CORRECTION_REQUESTED"
    assert verified["violation_count"] == 1

    standing = fx.read_vendor(api, vendor["id"])
    assert standing["correction_spend_cents"] == 2500
    assert standing["reliability_score_bp"] == 9700
    assert standing["status"] == "PROBATION"

    response = api.resubmit_measurement_spec(
        spec["id"],
        resubmit_measurement_spec_payload(),
        make_vendor_user_headers(vendor["id"]),
    )
    validate_error(
        response, ApiErrorId.ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED.value, 402
    )

    stored = fx.read_spec(api, spec["id"])
    assert stored["status"] == "CORRECTION_REQUESTED"
    assert stored["revision_round"] == 0
    assert stored["correction_reason"] == "GRADE_TOLERANCE_VIOLATION"

    assert fx.read_vendor(api, vendor["id"])["correction_round_count"] == 1
