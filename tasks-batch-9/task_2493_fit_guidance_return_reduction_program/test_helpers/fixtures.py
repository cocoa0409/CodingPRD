"""Setup helpers that build preconditions through the public API only.

Every test starts against an empty program, so any state a test needs must be
created by real requests.  The helpers here are layered:

* Tier 1 — single-call wrappers that create or advance one resource and return
  its representation.
* Tier 2 — entity-hierarchy builders that walk a chain of foreign keys down to
  the resource a test actually cares about.
* Tier 3 — lifecycle shortcuts that drive a resource to a named state on one of
  its state machines.
* Tier 4 — accumulation builders that repeat a lifecycle until a declared
  threshold has been crossed, so a test can start from the far side of a
  watch, chronic, abuse or budget boundary.
* Tier 5 — terminal builders that reach a final state (voided case, retired
  chart, measured deployment) including the cascades that firing entails.

Setup calls use `get_success_data`, which accepts any success status and fails
loudly if a precondition step did not take, so a broken setup never masquerades
as a failed assertion.  Ownership-gated calls always thread the identity of the
row that owns the resource rather than a shared operator constant.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import TEST_DEFAULTS
from .test_users import (
    ANALYST_USER_ID,
    CLASSIFY_AUDITOR_USER_ID,
    RESOLVE_AUDITOR_USER_ID,
    VOID_AUDITOR_USER_ID,
    make_customer_headers,
    make_fit_analyst_headers,
    make_merch_ops_admin_headers,
    make_returns_auditor_headers,
    make_vendor_user_headers,
)

JsonDict = Dict[str, Any]

# The instant nearly every scenario runs at: after the sample policy takes
# effect and inside the sample delivery's return window.
SCENARIO_CLOCK = TEST_DEFAULTS["CLOCK"]


# ===========================================================================
# Tier 1 — single-call wrappers
# ===========================================================================


def set_clock(api: ApiClient, to_iso8601: str) -> JsonDict:
    """Move the logical clock.  Called first in every scenario so that no
    outcome depends on wall-clock time."""
    return get_success_data(
        api.set_clock(to_iso8601, make_merch_ops_admin_headers())
    )


def create_vendor(api: ApiClient, **overrides) -> JsonDict:
    return get_success_data(
        api.create_vendor(
            factories.create_vendor_payload(**overrides), make_merch_ops_admin_headers()
        )
    )


def create_item(api: ApiClient, vendor_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.create_catalog_item(
            factories.create_catalog_item_payload(vendor_id, **overrides),
            make_merch_ops_admin_headers(),
        )
    )


def list_item(api: ApiClient, item_id: str) -> JsonDict:
    return get_success_data(api.list_item(item_id, make_merch_ops_admin_headers()))


def delist_item(api: ApiClient, item_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.delist_item(
            item_id,
            factories.delist_item_payload(**overrides),
            make_merch_ops_admin_headers(),
        )
    )


def enhance_pdp(api: ApiClient, item_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.enhance_pdp(
            item_id,
            factories.pdp_enhancement_payload(**overrides),
            make_merch_ops_admin_headers(),
        )
    )


def publish_guidance(api: ApiClient, item_id: str) -> JsonDict:
    return get_success_data(api.publish_guidance(item_id, make_fit_analyst_headers()))


def read_item(api: ApiClient, item_id: str) -> JsonDict:
    return get_success_data(
        api.get_catalog_item(item_id, make_merch_ops_admin_headers())
    )


def read_vendor(api: ApiClient, vendor_id: str) -> JsonDict:
    return get_success_data(api.get_vendor(vendor_id, make_merch_ops_admin_headers()))


def create_spec(api: ApiClient, item_id: str, vendor_id: str, **overrides) -> JsonDict:
    """A specification is written by the vendor that owns the item described."""
    return get_success_data(
        api.create_measurement_spec(
            factories.create_measurement_spec_payload(item_id, **overrides),
            make_vendor_user_headers(vendor_id),
        )
    )


def submit_spec(api: ApiClient, spec_id: str, vendor_id: str) -> JsonDict:
    return get_success_data(
        api.submit_measurement_spec(spec_id, make_vendor_user_headers(vendor_id))
    )


def verify_spec(api: ApiClient, spec_id: str, user_id: str = ANALYST_USER_ID) -> JsonDict:
    """Verification is an analyst act and its verdict is computed, not chosen."""
    return get_success_data(
        api.verify_measurement_spec(spec_id, make_fit_analyst_headers(user_id))
    )


def resubmit_spec(
    api: ApiClient,
    spec_id: str,
    vendor_id: str,
    size_points: Optional[List[dict]] = None,
    **overrides,
) -> JsonDict:
    return get_success_data(
        api.resubmit_measurement_spec(
            spec_id,
            factories.resubmit_measurement_spec_payload(size_points, **overrides),
            make_vendor_user_headers(vendor_id),
        )
    )


def read_spec(api: ApiClient, spec_id: str) -> JsonDict:
    return get_success_data(
        api.get_measurement_spec(spec_id, make_merch_ops_admin_headers())
    )


def create_chart(api: ApiClient, **overrides) -> JsonDict:
    return get_success_data(
        api.create_size_chart(
            factories.create_size_chart_payload(**overrides),
            make_merch_ops_admin_headers(),
        )
    )


def standardize_chart(api: ApiClient, chart_id: str) -> JsonDict:
    return get_success_data(
        api.standardize_size_chart(chart_id, make_merch_ops_admin_headers())
    )


def retire_chart(api: ApiClient, chart_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.retire_size_chart(
            chart_id,
            factories.retire_size_chart_payload(**overrides),
            make_merch_ops_admin_headers(),
        )
    )


def read_chart(api: ApiClient, chart_id: str) -> JsonDict:
    return get_success_data(api.get_size_chart(chart_id, make_merch_ops_admin_headers()))


def create_mapping(
    api: ApiClient,
    item_id: str,
    chart_id: str,
    expected_item_version: Optional[int] = None,
    size_label_pairs: Optional[List[dict]] = None,
    **overrides,
) -> JsonDict:
    """Mapping is an analyst act guarded by the item's version.  When no version
    is supplied the item is re-read so the guard sees the current one."""
    if expected_item_version is None:
        expected_item_version = read_item(api, item_id)["version"]
    return get_success_data(
        api.create_size_chart_mapping(
            factories.create_size_chart_mapping_payload(
                item_id, chart_id, expected_item_version, size_label_pairs, **overrides
            ),
            make_fit_analyst_headers(),
        )
    )


def read_mapping(api: ApiClient, mapping_id: str) -> JsonDict:
    return get_success_data(
        api.get_size_chart_mapping(mapping_id, make_fit_analyst_headers())
    )


def create_customer(api: ApiClient, **overrides) -> JsonDict:
    return get_success_data(
        api.create_customer_profile(
            factories.create_customer_profile_payload(**overrides),
            make_merch_ops_admin_headers(),
        )
    )


def read_customer(api: ApiClient, customer_profile_id: str) -> JsonDict:
    return get_success_data(
        api.get_customer_profile(customer_profile_id, make_merch_ops_admin_headers())
    )


def create_policy(api: ApiClient, **overrides) -> JsonDict:
    return get_success_data(
        api.create_return_policy(
            factories.create_return_policy_payload(**overrides),
            make_merch_ops_admin_headers(),
        )
    )


def create_override(
    api: ApiClient,
    customer_profile_id: str,
    expected_customer_profile_version: Optional[int] = None,
    **overrides,
) -> JsonDict:
    """A customer-scoped override is guarded by the profile's version; re-read the
    profile when the caller has not pinned one."""
    if expected_customer_profile_version is None:
        expected_customer_profile_version = read_customer(api, customer_profile_id)[
            "version"
        ]
    return get_success_data(
        api.create_return_policy_override(
            customer_profile_id,
            factories.create_return_policy_override_payload(
                expected_customer_profile_version, **overrides
            ),
            make_merch_ops_admin_headers(),
        )
    )


def create_order_line(
    api: ApiClient, customer_profile_id: str, item_id: str, **overrides
) -> JsonDict:
    return get_success_data(
        api.create_order_line(
            factories.create_order_line_payload(
                customer_profile_id, item_id, **overrides
            ),
            make_merch_ops_admin_headers(),
        )
    )


def read_order_line(api: ApiClient, order_line_id: str) -> JsonDict:
    return get_success_data(
        api.get_order_line(order_line_id, make_merch_ops_admin_headers())
    )


def open_case(
    api: ApiClient, order_line_id: str, customer_profile_id: str, **overrides
) -> JsonDict:
    """Opening a return is a shopper act; the acting identity must be the shopper
    that owns the order line."""
    return get_success_data(
        api.create_return_case(
            factories.create_return_case_payload(order_line_id, **overrides),
            make_customer_headers(customer_profile_id),
        )
    )


def classify_case(
    api: ApiClient,
    case_id: str,
    reason_code: str = "FIT_TOO_SMALL",
    user_id: str = CLASSIFY_AUDITOR_USER_ID,
) -> JsonDict:
    return get_success_data(
        api.classify_return_case(
            case_id,
            factories.classify_return_case_payload(reason_code),
            make_returns_auditor_headers(user_id),
        )
    )


def resolve_case(
    api: ApiClient,
    case_id: str,
    item_condition: str = "RESELLABLE_A",
    user_id: str = RESOLVE_AUDITOR_USER_ID,
    **overrides,
) -> JsonDict:
    """Closing a case must be done by an auditor other than the one who coded it,
    so the default resolving identity differs from the default coding identity."""
    return get_success_data(
        api.resolve_return_case(
            case_id,
            factories.resolve_return_case_payload(item_condition, **overrides),
            make_returns_auditor_headers(user_id),
        )
    )


def void_case(
    api: ApiClient, case_id: str, user_id: str = VOID_AUDITOR_USER_ID, **overrides
) -> JsonDict:
    return get_success_data(
        api.void_return_case(
            case_id,
            factories.void_return_case_payload(**overrides),
            make_returns_auditor_headers(user_id),
        )
    )


def read_case(api: ApiClient, case_id: str) -> JsonDict:
    return get_success_data(
        api.get_return_case(case_id, make_returns_auditor_headers())
    )


def read_cost_postings(api: ApiClient, case_id: str, **params) -> List[dict]:
    """The append-only ledger of one case, oldest posting first."""
    body = get_success_data(
        api.list_cost_postings(
            case_id, make_returns_auditor_headers(), params or None
        )
    )
    return body if isinstance(body, list) else body["data"]


def post_feedback(
    api: ApiClient, item_id: str, customer_profile_id: str, **overrides
) -> JsonDict:
    return get_success_data(
        api.create_fit_feedback(
            factories.create_fit_feedback_payload(
                item_id, customer_profile_id, **overrides
            ),
            make_customer_headers(customer_profile_id),
        )
    )


def retract_feedback(
    api: ApiClient, feedback_id: str, customer_profile_id: str, **overrides
) -> JsonDict:
    return get_success_data(
        api.retract_fit_feedback(
            feedback_id,
            factories.retract_fit_feedback_payload(**overrides),
            make_customer_headers(customer_profile_id),
        )
    )


def create_intervention(api: ApiClient, **overrides) -> JsonDict:
    return get_success_data(
        api.create_intervention(
            factories.create_intervention_payload(**overrides),
            make_merch_ops_admin_headers(),
        )
    )


def read_intervention(api: ApiClient, intervention_id: str) -> JsonDict:
    return get_success_data(
        api.get_intervention(intervention_id, make_merch_ops_admin_headers())
    )


def create_deployment(
    api: ApiClient, intervention_id: str, item_id: str, **overrides
) -> JsonDict:
    return get_success_data(
        api.create_intervention_deployment(
            factories.create_intervention_deployment_payload(
                intervention_id, item_id, **overrides
            ),
            make_merch_ops_admin_headers(),
        )
    )


def terminate_deployment(api: ApiClient, deployment_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.terminate_intervention_deployment(
            deployment_id,
            factories.terminate_deployment_payload(**overrides),
            make_merch_ops_admin_headers(),
        )
    )


def read_deployment(api: ApiClient, deployment_id: str) -> JsonDict:
    return get_success_data(
        api.get_intervention_deployment(deployment_id, make_merch_ops_admin_headers())
    )


def run_ops_run(api: ApiClient) -> JsonDict:
    """The checkpoint that advances deployments, refreshes chronic scores and ages
    abuse strikes out of the trailing window."""
    return get_success_data(api.create_ops_run(make_merch_ops_admin_headers()))


def read_savings_report(api: ApiClient, intervention_id: str, **params) -> JsonDict:
    return get_success_data(
        api.get_savings_report(
            intervention_id, make_merch_ops_admin_headers(), params or None
        )
    )


def read_fit_recommendation(api: ApiClient, item_id: str, headers, **params) -> JsonDict:
    return get_success_data(
        api.get_fit_recommendation(item_id, headers, params or None)
    )


# ===========================================================================
# Tier 2 — entity-hierarchy builders
# ===========================================================================


def setup_vendor_and_item(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    vendor_overrides: Optional[dict] = None,
    item_overrides: Optional[dict] = None,
) -> JsonDict:
    """A vendor and one DRAFT catalog item beneath it."""
    set_clock(api, clock)
    vendor = create_vendor(api, **(vendor_overrides or {}))
    item = create_item(api, vendor["id"], **(item_overrides or {}))
    return {"vendor": vendor, "item": item}


def setup_listed_item(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    vendor_overrides: Optional[dict] = None,
    item_overrides: Optional[dict] = None,
) -> JsonDict:
    """A vendor and one LISTED item.  Listing advances only the storefront axis;
    fit readiness stays UNVERIFIED."""
    built = setup_vendor_and_item(api, clock, vendor_overrides, item_overrides)
    built["item"] = list_item(api, built["item"]["id"])
    return built


def setup_shopper_with_delivered_line(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    vendor_overrides: Optional[dict] = None,
    item_overrides: Optional[dict] = None,
    policy_overrides: Optional[dict] = None,
    customer_overrides: Optional[dict] = None,
    line_overrides: Optional[dict] = None,
) -> JsonDict:
    """The full purchase chain: vendor, listed item, category-default policy,
    shopper and one delivered order line.  This is the precondition every
    return-case scenario shares."""
    built = setup_listed_item(api, clock, vendor_overrides, item_overrides)
    category = built["item"]["category_code"]
    policy_kwargs = {"category_code": category}
    policy_kwargs.update(policy_overrides or {})
    built["policy"] = create_policy(api, **policy_kwargs)
    built["customer"] = create_customer(api, **(customer_overrides or {}))
    built["order_line"] = create_order_line(
        api,
        built["customer"]["id"],
        built["item"]["id"],
        **(line_overrides or {}),
    )
    return built


def setup_delivered_lines(
    api: ApiClient,
    count: int,
    clock: str = SCENARIO_CLOCK,
    vendor_overrides: Optional[dict] = None,
    item_overrides: Optional[dict] = None,
    policy_overrides: Optional[dict] = None,
    customer_overrides: Optional[dict] = None,
    line_overrides: Optional[dict] = None,
) -> JsonDict:
    """The same chain with several delivered lines on one item for one shopper, so
    a scenario can reach a rate denominator larger than one."""
    built = setup_shopper_with_delivered_line(
        api,
        clock,
        vendor_overrides,
        item_overrides,
        policy_overrides,
        customer_overrides,
        line_overrides,
    )
    lines = [built["order_line"]]
    for _ in range(count - 1):
        lines.append(
            create_order_line(
                api,
                built["customer"]["id"],
                built["item"]["id"],
                **(line_overrides or {}),
            )
        )
    built["order_lines"] = lines
    return built


def setup_two_vendors_one_item(
    api: ApiClient, clock: str = SCENARIO_CLOCK
) -> JsonDict:
    """Two vendors where only the first owns the item, for scenarios about who may
    write against that item."""
    set_clock(api, clock)
    owner = create_vendor(api)
    other = create_vendor(
        api, name="Southgate Textiles", brand_code="SOUT", correction_budget_cents=250000
    )
    item = create_item(api, owner["id"])
    return {"owner_vendor": owner, "other_vendor": other, "item": item}


# ===========================================================================
# Tier 3 — lifecycle shortcuts
# ===========================================================================


def setup_submitted_spec(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    size_points: Optional[List[dict]] = None,
    spec_overrides: Optional[dict] = None,
    **kwargs,
) -> JsonDict:
    """A LISTED item whose specification awaits verification."""
    built = setup_listed_item(api, clock, **kwargs)
    overrides = dict(spec_overrides or {})
    if size_points is not None:
        overrides["size_points"] = size_points
    spec = create_spec(api, built["item"]["id"], built["vendor"]["id"], **overrides)
    built["spec"] = submit_spec(api, spec["id"], built["vendor"]["id"])
    return built


def setup_verified_spec(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    size_points: Optional[List[dict]] = None,
    spec_overrides: Optional[dict] = None,
    **kwargs,
) -> JsonDict:
    """A LISTED item with a VERIFIED specification, the precondition for mapping.
    The default size points grade cleanly, so verification finds no violation."""
    built = setup_submitted_spec(api, clock, size_points, spec_overrides, **kwargs)
    built["spec"] = verify_spec(api, built["spec"]["id"])
    return built


def setup_correction_requested_spec(
    api: ApiClient, clock: str = SCENARIO_CLOCK, **kwargs
) -> JsonDict:
    """A specification whose verification found a tolerance violation, so the
    vendor now owes a correction."""
    built = setup_submitted_spec(
        api, clock, size_points=factories.VIOLATING_TWO_POINT_RUN, **kwargs
    )
    built["spec"] = verify_spec(api, built["spec"]["id"])
    return built


def setup_standardized_chart(api: ApiClient, **overrides) -> JsonDict:
    """A STANDARDIZED chart, the only kind a mapping may name."""
    chart = create_chart(api, **overrides)
    return standardize_chart(api, chart["id"])


def setup_mapped_item(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    size_points: Optional[List[dict]] = None,
    chart_overrides: Optional[dict] = None,
    size_label_pairs: Optional[List[dict]] = None,
    **kwargs,
) -> JsonDict:
    """An item at CHART_MAPPED: verified specification mapped onto a standardized
    chart at full coverage."""
    built = setup_verified_spec(api, clock, size_points, **kwargs)
    chart_kwargs = {"category_code": built["item"]["category_code"]}
    chart_kwargs.update(chart_overrides or {})
    built["chart"] = setup_standardized_chart(api, **chart_kwargs)
    built["mapping"] = create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=size_label_pairs,
    )
    built["item"] = read_item(api, built["item"]["id"])
    return built


def setup_guidance_ready_item(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    size_points: Optional[List[dict]] = None,
    chart_overrides: Optional[dict] = None,
    size_label_pairs: Optional[List[dict]] = None,
    pdp_overrides: Optional[dict] = None,
    **kwargs,
) -> JsonDict:
    """An item at GUIDANCE_READY: mapped, enhanced, and published.  This is the
    precondition for anything that reads fit guidance."""
    built = setup_mapped_item(
        api, clock, size_points, chart_overrides, size_label_pairs, **kwargs
    )
    enhance_pdp(api, built["item"]["id"], **(pdp_overrides or {}))
    built["item"] = publish_guidance(api, built["item"]["id"])
    return built


def setup_triage_case(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    case_overrides: Optional[dict] = None,
    **kwargs,
) -> JsonDict:
    """A return case at TRIAGE with its policy, window and deadline already
    frozen onto it."""
    built = setup_shopper_with_delivered_line(api, clock, **kwargs)
    built["case"] = open_case(
        api,
        built["order_line"]["id"],
        built["customer"]["id"],
        **(case_overrides or {}),
    )
    return built


def setup_classified_case(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    reason_code: str = "FIT_TOO_SMALL",
    case_overrides: Optional[dict] = None,
    classifier_user_id: str = CLASSIFY_AUDITOR_USER_ID,
    **kwargs,
) -> JsonDict:
    """A coded case sitting in the review branch its reason family selects."""
    built = setup_triage_case(api, clock, case_overrides, **kwargs)
    built["case"] = classify_case(
        api, built["case"]["id"], reason_code, classifier_user_id
    )
    return built


def setup_resolved_case(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    reason_code: str = "FIT_TOO_SMALL",
    item_condition: str = "RESELLABLE_A",
    case_overrides: Optional[dict] = None,
    classifier_user_id: str = CLASSIFY_AUDITOR_USER_ID,
    resolver_user_id: str = RESOLVE_AUDITOR_USER_ID,
    **kwargs,
) -> JsonDict:
    """A closed case: the refund, fee and cost postings are written and every
    aggregate the closure touches has moved."""
    built = setup_classified_case(
        api, clock, reason_code, case_overrides, classifier_user_id, **kwargs
    )
    built["case"] = resolve_case(
        api, built["case"]["id"], item_condition, resolver_user_id
    )
    return built


def setup_scheduled_deployment(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    intervention_overrides: Optional[dict] = None,
    deployment_overrides: Optional[dict] = None,
    **kwargs,
) -> JsonDict:
    """A lever with one SCHEDULED deployment on a listed item."""
    built = setup_listed_item(api, clock, **kwargs)
    built["intervention"] = create_intervention(api, **(intervention_overrides or {}))
    built["deployment"] = create_deployment(
        api,
        built["intervention"]["id"],
        built["item"]["id"],
        **(deployment_overrides or {}),
    )
    return built


def setup_active_deployment(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    window_start: str = "2026-06-01T00:00:00Z",
    window_end: str = "2026-07-01T00:00:00Z",
    intervention_overrides: Optional[dict] = None,
    deployment_overrides: Optional[dict] = None,
    **kwargs,
) -> JsonDict:
    """A deployment the checkpoint has advanced to ACTIVE because the clock has
    reached its window start."""
    deployment_kwargs = {"window_start": window_start, "window_end": window_end}
    deployment_kwargs.update(deployment_overrides or {})
    built = setup_scheduled_deployment(
        api, clock, intervention_overrides, deployment_kwargs, **kwargs
    )
    built["activation_run"] = run_ops_run(api)
    built["deployment"] = read_deployment(api, built["deployment"]["id"])
    built["intervention"] = read_intervention(api, built["intervention"]["id"])
    return built


# ===========================================================================
# Tier 4 — accumulation and threshold builders
# ===========================================================================


def setup_item_with_fit_returns(
    api: ApiClient,
    fit_return_count: int,
    line_count: int,
    clock: str = SCENARIO_CLOCK,
    item_condition: str = "RESELLABLE_A",
    reason_code: str = "FIT_TOO_SMALL",
    **kwargs,
) -> JsonDict:
    """Drive an item's chronic-return score by closing `fit_return_count` fit
    returns against `line_count` delivered lines.  One fit return over a small
    denominator reaches WATCH; two reach CHRONIC, which suspends the listing,
    reopens the specification and debits the vendor."""
    built = setup_delivered_lines(api, line_count, clock, **kwargs)
    cases = []
    for line in built["order_lines"][:fit_return_count]:
        case = open_case(
            api, line["id"], built["customer"]["id"], requested_reason_code=reason_code
        )
        classify_case(api, case["id"], reason_code)
        cases.append(resolve_case(api, case["id"], item_condition))
    built["cases"] = cases
    built["item"] = read_item(api, built["item"]["id"])
    built["vendor"] = read_vendor(api, built["vendor"]["id"])
    built["customer"] = read_customer(api, built["customer"]["id"])
    return built


def setup_watch_item(api: ApiClient, clock: str = SCENARIO_CLOCK, **kwargs) -> JsonDict:
    """An item that has crossed the watch threshold but not the chronic one."""
    return setup_item_with_fit_returns(api, 1, 4, clock, **kwargs)


def setup_chronic_item(
    api: ApiClient, clock: str = SCENARIO_CLOCK, **kwargs
) -> JsonDict:
    """An item on the far side of the chronic threshold, with the listing
    suspension, specification correction request and vendor debit that the flip
    cascades into."""
    return setup_item_with_fit_returns(api, 2, 4, clock, **kwargs)


def setup_shopper_with_strikes(
    api: ApiClient,
    strike_count: int,
    line_count: int,
    clock: str = SCENARIO_CLOCK,
    **kwargs,
) -> JsonDict:
    """Open `strike_count` change-of-mind returns for one shopper so their abuse
    standing and policy class move.  Change-of-mind closures are what earn a
    strike inside the trailing window."""
    built = setup_delivered_lines(api, line_count, clock, **kwargs)
    cases = []
    for line in built["order_lines"][:strike_count]:
        case = open_case(
            api,
            line["id"],
            built["customer"]["id"],
            requested_reason_code="CHANGE_OF_MIND",
        )
        classify_case(api, case["id"], "CHANGE_OF_MIND")
        cases.append(resolve_case(api, case["id"], "RESELLABLE_A"))
    built["cases"] = cases
    built["customer"] = read_customer(api, built["customer"]["id"])
    return built


def setup_blocked_shopper(
    api: ApiClient, clock: str = SCENARIO_CLOCK, **kwargs
) -> JsonDict:
    """A shopper whose standing has reached BLOCKED, so a further return request
    is refused before any window arithmetic is consulted."""
    return setup_shopper_with_strikes(api, 3, 4, clock, **kwargs)


def setup_vendor_at_correction_budget(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    budget_cents: int = 2000,
    **kwargs,
) -> JsonDict:
    """A vendor whose correction budget cannot fund the next round, reached by
    letting a verification request one correction against a budget smaller than a
    single round costs."""
    return setup_correction_requested_spec(
        api,
        clock,
        vendor_overrides={"correction_budget_cents": budget_cents},
        **kwargs,
    )


def setup_item_with_feedback(
    api: ApiClient,
    verdicts: List[str],
    clock: str = SCENARIO_CLOCK,
    **kwargs,
) -> JsonDict:
    """A listed item carrying one active fit-feedback row per named verdict, each
    from a different shopper, so the item's signal pool has a known total.  The
    first shopper has a delivered line on the item and therefore counts as a
    purchaser; the rest do not."""
    built = setup_shopper_with_delivered_line(api, clock, **kwargs)
    feedback = [
        post_feedback(
            api,
            built["item"]["id"],
            built["customer"]["id"],
            fit_verdict=verdicts[0],
        )
    ]
    shoppers = [built["customer"]]
    for index, verdict in enumerate(verdicts[1:], start=2):
        shopper = create_customer(api, email=f"shopper-{index}@example.com")
        shoppers.append(shopper)
        feedback.append(
            post_feedback(
                api, built["item"]["id"], shopper["id"], fit_verdict=verdict
            )
        )
    built["shoppers"] = shoppers
    built["feedback"] = feedback
    built["item"] = read_item(api, built["item"]["id"])
    return built


# ===========================================================================
# Tier 5 — terminal and finalization builders
# ===========================================================================


def setup_voided_case(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    reason_code: str = "FIT_TOO_SMALL",
    item_condition: str = "RESELLABLE_A",
    **kwargs,
) -> JsonDict:
    """A reversed case: every original posting has been offset and every aggregate
    the closure had moved has been returned to where it stood."""
    built = setup_resolved_case(
        api, clock, reason_code, item_condition, **kwargs
    )
    built["case"] = void_case(api, built["case"]["id"])
    built["postings"] = read_cost_postings(api, built["case"]["id"])
    built["item"] = read_item(api, built["item"]["id"])
    built["vendor"] = read_vendor(api, built["vendor"]["id"])
    built["customer"] = read_customer(api, built["customer"]["id"])
    built["order_line"] = read_order_line(api, built["order_line"]["id"])
    return built


def setup_retired_chart_cascade(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    retire_clock: Optional[str] = None,
    **kwargs,
) -> JsonDict:
    """A mapped item whose chart has since been retired, so the mapping is
    superseded, the item's readiness has fallen back and any deployment resting on
    that mapping has been terminated."""
    built = setup_mapped_item(api, clock, **kwargs)
    if retire_clock:
        set_clock(api, retire_clock)
    built["chart"] = retire_chart(api, built["chart"]["id"])
    built["mapping"] = read_mapping(api, built["mapping"]["id"])
    built["item"] = read_item(api, built["item"]["id"])
    return built


def setup_measured_deployment(
    api: ApiClient,
    clock: str = SCENARIO_CLOCK,
    window_start: str = "2026-06-01T00:00:00Z",
    window_end: str = "2026-07-01T00:00:00Z",
    after_window_clock: str = "2026-07-02T00:00:00Z",
    intervention_overrides: Optional[dict] = None,
    deployment_overrides: Optional[dict] = None,
    **kwargs,
) -> JsonDict:
    """A deployment carried all the way to MEASURED: scheduled, activated once the
    clock reaches its window start, then measured once the window has elapsed.
    The checkpoint advances a deployment by at most one hop, so each hop needs its
    own run."""
    built = setup_active_deployment(
        api,
        clock,
        window_start,
        window_end,
        intervention_overrides,
        deployment_overrides,
        **kwargs,
    )
    set_clock(api, after_window_clock)
    built["termination_run"] = run_ops_run(api)
    built["measurement_run"] = run_ops_run(api)
    built["deployment"] = read_deployment(api, built["deployment"]["id"])
    built["intervention"] = read_intervention(api, built["intervention"]["id"])
    return built


def setup_delisted_item(
    api: ApiClient, clock: str = SCENARIO_CLOCK, **kwargs
) -> JsonDict:
    """An item removed from the storefront permanently, the terminal state of the
    listing axis."""
    built = setup_listed_item(api, clock, **kwargs)
    built["item"] = delist_item(api, built["item"]["id"])
    return built


def setup_retracted_feedback(
    api: ApiClient, clock: str = SCENARIO_CLOCK, **kwargs
) -> JsonDict:
    """A fit-feedback row already withdrawn by its author, so the item's signal
    pool has returned to its prior total."""
    built = setup_item_with_feedback(api, ["TRUE_TO_SIZE"], clock, **kwargs)
    built["feedback"] = [
        retract_feedback(
            api, built["feedback"][0]["id"], built["shoppers"][0]["id"]
        )
    ]
    built["item"] = read_item(api, built["item"]["id"])
    return built
