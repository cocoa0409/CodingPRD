"""Processing purposes, element-purpose mappings and vendor agreements.

Covers the purpose catalogue and its derived disclosure flags, the element-to-purpose
wiring and its activation gate, the vendor agreement lifecycle with its three execution
clauses, and the five-hop cascade that a vendor termination drives through mappings,
the published policy, the product's policy currency and running geofence campaigns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    REASON_POLICY_LAPSED,
    REASON_VENDOR_AGREEMENT_TERMINATED,
    activate_campaign,
    activate_mapping,
    assert_element_purpose_mapping,
    assert_vendor,
    create_approved_assessment,
    create_campaign,
    create_element,
    create_mapping,
    create_processing_purpose_payload,
    create_product,
    create_published_policy,
    create_purpose,
    create_vendor,
    create_vendor_payload,
    create_zone,
    make_data_steward_headers,
    make_privacy_officer_headers,
    read_product,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_AUG_05 = "2026-08-05T00:00:00Z"
CLOCK_AUG_06 = "2026-08-06T00:00:00Z"


def _instant(value: str) -> datetime:
    """Parse a stamped ISO 8601 UTC instant, tolerating any fractional rendering."""
    assert isinstance(value, str), f"expected a stamped instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _read_mapping(api: ApiClient, mapping_id: str) -> dict[str, Any]:
    return validate_success(
        api.get_element_purpose_mapping(mapping_id, make_data_steward_headers())
    )


def _read_vendor(api: ApiClient, vendor_id: str) -> dict[str, Any]:
    return validate_success(api.get_vendor(vendor_id, make_privacy_officer_headers()))


def _build_share_mapping_with_draft_vendor(api: ApiClient) -> dict[str, Any]:
    """A CHD_REGULATED product with a PROPOSED SHARE mapping naming a DRAFT vendor."""
    set_clock(CLOCK_AUG_05, api)
    product = create_product(api)
    element = create_element(product["id"], api, element_key="apnea_dx")
    purpose = create_purpose(
        product["id"],
        api,
        purpose_key="ad_partner_share",
        description_text="Share with advertising partners",
        purpose_kind="ADVERTISING",
        activity_kind="SHARE",
    )
    vendor = create_vendor(product["id"], api, vendor_name="AdCo")
    create_approved_assessment(product["id"], api)
    mapping = create_mapping(
        element["id"], purpose["id"], api, vendor_id=vendor["id"]
    )
    return {
        "product": read_product(product["id"], api),
        "element": element,
        "purpose": purpose,
        "vendor": vendor,
        "mapping": mapping,
    }


def _build_terminable_disclosure_estate(api: ApiClient) -> dict[str, Any]:
    """The whole estate a vendor termination cascades through.

    An EXECUTED vendor, an ACTIVE SHARE mapping naming it, a PUBLISHED policy that
    made the product CURRENT, and an ACTIVE campaign on a permitted TX zone.
    """
    set_clock(CLOCK_AUG_05, api)
    product = create_product(api)
    element = create_element(product["id"], api, element_key="apnea_dx")
    create_purpose(
        product["id"],
        api,
        purpose_key="core_service",
        description_text="Deliver the sleep coaching service",
    )
    share_purpose = create_purpose(
        product["id"],
        api,
        purpose_key="ad_partner_share",
        description_text="Share with advertising partners",
        purpose_kind="ADVERTISING",
        activity_kind="SHARE",
    )
    vendor = create_vendor(product["id"], api, vendor_name="AdCo")
    vendor = validate_success(
        api.execute_vendor_agreement(vendor["id"], make_privacy_officer_headers())
    )
    assessment = create_approved_assessment(product["id"], api)
    mapping = create_mapping(
        element["id"], share_purpose["id"], api, vendor_id=vendor["id"]
    )
    policy = create_published_policy(
        product["id"],
        assessment["id"],
        api,
        disclosed_purpose_count=2,
        disclosed_third_party_count=1,
        named_third_party_count=1,
    )
    mapping = activate_mapping(mapping["id"], api)
    zone = create_zone(
        product["id"],
        api,
        zone_name="Metro Clinic",
        state_code="TX",
        facility_kind="GENERAL_HEALTH",
        center_label="Downtown campus",
        radius_meters=300,
    )
    campaign = create_campaign(
        zone["id"], share_purpose["id"], api, campaign_name="Fall push"
    )
    campaign = activate_campaign(campaign["id"], api)
    return {
        "product": read_product(product["id"], api),
        "element": element,
        "share_purpose": share_purpose,
        "vendor": vendor,
        "mapping": mapping,
        "policy": policy,
        "zone": zone,
        "campaign": campaign,
    }


# ---------------------------------------------------------------------------
# A mapping's activation depends on the vendor agreement's own state
# ---------------------------------------------------------------------------


def test_share_mapping_activation_refused_while_vendor_agreement_is_still_draft(
    api: ApiClient,
) -> None:
    """A DRAFT vendor agreement blocks activation of the mapping that names it.

    PRD §3.3: "When the referenced purpose's `third_party_disclosure_required` is true,
    two further conditions apply: the mapping's `vendor_id` must be non-null, on pain of
    `ERR_VENDOR_REQUIRED_FOR_DISCLOSURE`, and the named vendor's `agreement_state` must
    be `EXECUTED` with `agreement_compliance` `COMPLIANT`, on pain of
    `ERR_VENDOR_AGREEMENT_DEFICIENT`."
    PRD §3.4: "Agreements begin with `agreement_state` at `DRAFT`, a null `executed_at`
    and a null `terminated_at`."

    Design: Difficulty/cross_entity_state_dependency/mapping_activation_requires_executed_vendor_agreement
    """
    estate = _build_share_mapping_with_draft_vendor(api)

    response = api.activate_element_purpose_mapping(
        estate["mapping"]["id"], make_data_steward_headers()
    )
    validate_error(response, ApiErrorId.VENDOR_AGREEMENT_DEFICIENT.value)

    vendor = _read_vendor(api, estate["vendor"]["id"])
    assert vendor["agreement_state"] == "DRAFT"
    assert vendor["executed_at"] is None
    assert _read_mapping(api, estate["mapping"]["id"])["status"] == "PROPOSED"


def test_share_mapping_activates_unchanged_once_the_vendor_agreement_is_executed(
    api: ApiClient,
) -> None:
    """The identical activate call succeeds the moment the vendor reaches EXECUTED.

    PRD §3.4: "Execution moves the vendor `DRAFT → EXECUTED`, stamps `executed_at` with
    the logical clock, and recomputes `agreement_compliance`."
    PRD §3.3: "When the referenced purpose's `third_party_disclosure_required` is true,
    two further conditions apply: the mapping's `vendor_id` must be non-null, on pain of
    `ERR_VENDOR_REQUIRED_FOR_DISCLOSURE`, and the named vendor's `agreement_state` must
    be `EXECUTED` with `agreement_compliance` `COMPLIANT`, on pain of
    `ERR_VENDOR_AGREEMENT_DEFICIENT`."
    PRD §3.3: "Activation from `PROPOSED` recomputes `regulated_flag` from the element's
    current `chd_classification`; resumption from `SUSPENDED` clears `suspension_reason`
    back to null."

    Design: Difficulty/cross_entity_state_dependency/mapping_activation_requires_executed_vendor_agreement
    """
    estate = _build_share_mapping_with_draft_vendor(api)

    blocked = api.activate_element_purpose_mapping(
        estate["mapping"]["id"], make_data_steward_headers()
    )
    validate_error(blocked, ApiErrorId.VENDOR_AGREEMENT_DEFICIENT.value)

    executed = validate_success(
        api.execute_vendor_agreement(
            estate["vendor"]["id"], make_privacy_officer_headers()
        )
    )
    assert executed["agreement_state"] == "EXECUTED"
    assert executed["agreement_compliance"] == "COMPLIANT"
    assert _instant(executed["executed_at"]) == _instant(CLOCK_AUG_05)

    activated = validate_success(
        api.activate_element_purpose_mapping(
            estate["mapping"]["id"], make_data_steward_headers()
        )
    )
    assert_element_purpose_mapping(activated)
    assert activated["status"] == "ACTIVE"
    assert activated["regulated_flag"] is True
    assert activated["suspension_reason"] is None


# ---------------------------------------------------------------------------
# The five-hop vendor-termination cascade
# ---------------------------------------------------------------------------


def test_vendor_termination_terminates_the_agreement_and_suspends_its_active_mapping(
    api: ApiClient,
) -> None:
    """Hops one and two: the vendor terminates and its ACTIVE mapping is suspended.

    PRD §3.4: "Hop one moves the vendor `EXECUTED → TERMINATED` and stamps
    `terminated_at` with the logical clock."
    PRD §3.4: "Hop two, because this vendor's agreement has ended, moves every
    element-purpose mapping whose `vendor_id` names this vendor and whose `status` is
    `ACTIVE` from `ACTIVE → SUSPENDED`, with `suspension_reason` set to
    `VENDOR_AGREEMENT_TERMINATED`."

    Design: Difficulty/transitive_cascade/vendor_termination_five_hop_cascade_pauses_geofence_campaign
    """
    estate = _build_terminable_disclosure_estate(api)

    terminated = validate_success(
        api.terminate_vendor_agreement(
            estate["vendor"]["id"], make_privacy_officer_headers()
        )
    )
    assert_vendor(terminated)
    assert terminated["agreement_state"] == "TERMINATED"
    assert _instant(terminated["terminated_at"]) == _instant(CLOCK_AUG_05)

    mapping = _read_mapping(api, estate["mapping"]["id"])
    assert mapping["status"] == "SUSPENDED"
    assert mapping["suspension_reason"] == REASON_VENDOR_AGREEMENT_TERMINATED


def test_vendor_termination_unseats_the_published_policy_and_pauses_the_active_campaign(
    api: ApiClient,
) -> None:
    """Hops three to five: the policy is unseated, the product lapses, the campaign pauses.

    PRD §3.4: "Hop three, because at least one `ACTIVE` mapping was suspended by hop two,
    moves the privacy policy version on the same product whose `state` is `PUBLISHED`
    from `PUBLISHED → SUPERSEDED_PENDING_UPDATE` — the published text now describes a
    disclosure that no longer exists, so it is no longer an accurate policy."
    PRD §3.4: "Hop four, because that policy left `PUBLISHED` in hop three, sets the
    product's `policy_compliance_state` to `LAPSED`."
    PRD §3.4: "Hop five, because the product's `policy_compliance_state` became `LAPSED`
    in hop four, moves every geofence campaign whose zone belongs to that same product
    and whose `state` is `ACTIVE` from `ACTIVE → PAUSED`, with `pause_reason` set to
    `POLICY_LAPSED`, processing those campaigns in ascending `created_at` order."

    Design: Difficulty/transitive_cascade/vendor_termination_five_hop_cascade_pauses_geofence_campaign
    """
    estate = _build_terminable_disclosure_estate(api)
    assert estate["product"]["policy_compliance_state"] == "CURRENT"

    validate_success(
        api.terminate_vendor_agreement(
            estate["vendor"]["id"], make_privacy_officer_headers()
        )
    )

    policy = validate_success(
        api.get_privacy_policy_version(
            estate["policy"]["id"], make_privacy_officer_headers()
        )
    )
    assert policy["state"] == "SUPERSEDED_PENDING_UPDATE"
    assert policy["effective_to"] is None

    product = read_product(estate["product"]["id"], api)
    assert product["policy_compliance_state"] == "LAPSED"

    campaign = validate_success(
        api.get_geofence_campaign(estate["campaign"]["id"], make_data_steward_headers())
    )
    assert campaign["state"] == "PAUSED"
    assert campaign["pause_reason"] == REASON_POLICY_LAPSED


# ---------------------------------------------------------------------------
# The product boundary around the element-purpose junction
# ---------------------------------------------------------------------------


def test_mapping_joining_an_element_and_a_purpose_of_different_products_is_rejected(
    api: ApiClient,
) -> None:
    """Both legs resolve, but they belong to different products, so the junction is refused.

    PRD §2.6: "Compliance artefacts never span products: the data element and the
    processing purpose named by one element-purpose mapping must share an app product,
    the vendor named by that mapping must belong to the same product, a derivation parent
    must be an element of the same product, a subprocessor's parent vendor must belong to
    the same product, and a geofence campaign's processing purpose must belong to the
    same product as its geofence zone."
    PRD §2.6: "A body that mixes products is rejected with `ERR_CROSS_PRODUCT_REFERENCE`
    (HTTP 409)."

    Design: Corner/entities/graph_topology_mapping_across_two_products_rejected
    """
    product_a = create_product(api)
    product_b = create_product(
        api,
        product_name="MoodTrack",
        company_legal_name="MoodTrack Inc",
        primary_state_code="TX",
        consumer_count=20000,
        annual_revenue_cents=400000000,
        hipaa_covered_transaction_ratio=0.00,
    )
    element_a = create_element(product_a["id"], api, element_key="apnea_dx")
    purpose_b = create_purpose(product_b["id"], api, purpose_key="core_service")

    response = api.create_element_purpose_mapping(
        {
            "data_element_id": element_a["id"],
            "processing_purpose_id": purpose_b["id"],
            "disclosure_specificity": "CATEGORY_NAMED",
        },
        make_data_steward_headers(),
    )
    validate_error(response, ApiErrorId.CROSS_PRODUCT_REFERENCE.value)

    _rows, meta = validate_paginated(
        api.list_element_purpose_mappings(
            make_data_steward_headers(), {"data_element_id": element_a["id"]}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Vendor registration defaults
# ---------------------------------------------------------------------------


def test_vendor_registered_without_clause_inputs_falls_back_to_declared_defaults(
    api: ApiClient,
) -> None:
    """Omitting the optional clause and SLA inputs leaves a DEFICIENT DRAFT agreement.

    PRD §3.4: "Three contract clauses are recorded as booleans, each defaulting to false
    when omitted: `flow_down_clause`, meaning the contract obliges the vendor to impose
    equivalent terms on its own subprocessors; `audit_rights_clause`, meaning the
    operator holds inspection and audit rights; and `sale_authorization_clause`, meaning
    the contract authorises the vendor to purchase consumer health data."
    PRD §3.4: "The number of days the vendor contractually has to confirm a deletion
    instruction is recorded in `deletion_sla_days`, which defaults to 30 and must be
    between 1 and 90 inclusive."
    PRD §3.4: "Agreements begin with `agreement_state` at `DRAFT`, a null `executed_at`
    and a null `terminated_at`."
    PRD §3.4: "Whenever a vendor is written, amended, or executed, its
    `agreement_compliance` is recomputed and is `COMPLIANT` only when `flow_down_clause`
    is true *and* `audit_rights_clause` is true *and*, additionally, either the
    `vendor_kind` is something other than `PURCHASER` or the `sale_authorization_clause`
    is true."

    Design: Corner/entities/defaults_vendor_clause_flags_and_sla_fall_back_to_declared_defaults
    """
    product = create_product(api)

    vendor = validate_success(
        api.create_vendor(
            {
                "app_product_id": product["id"],
                "vendor_name": "BareCo",
                "vendor_kind": "PROCESSOR",
            },
            make_privacy_officer_headers(),
        ),
        201,
    )
    assert_vendor(vendor)
    assert vendor["flow_down_clause"] is False
    assert vendor["audit_rights_clause"] is False
    assert vendor["sale_authorization_clause"] is False
    assert vendor["deletion_sla_days"] == 30
    assert vendor["agreement_state"] == "DRAFT"
    assert vendor["agreement_compliance"] == "DEFICIENT"
    assert vendor["executed_at"] is None
    assert vendor["terminated_at"] is None


# ---------------------------------------------------------------------------
# The vendor's own 404 identifier
# ---------------------------------------------------------------------------


def test_unresolved_vendor_path_segment_returns_the_vendor_specific_not_found_code(
    api: ApiClient,
) -> None:
    """An unknown vendor id yields the vendor's own 404, never the generic one.

    PRD §2.6: "Which 404 is returned depends on the entity the segment addresses: an
    unresolved app product yields `ERR_APP_PRODUCT_NOT_FOUND`, an unresolved consumer
    `ERR_CONSUMER_NOT_FOUND`, an unresolved vendor `ERR_VENDOR_NOT_FOUND`, an unresolved
    data element `ERR_DATA_ELEMENT_NOT_FOUND`, an unresolved processing purpose
    `ERR_PURPOSE_NOT_FOUND`, and an unresolved row of any other type — applicability
    assessment, element-purpose mapping, consent record, privacy policy version, consumer
    request, deletion task, geofence zone, geofence campaign, breach incident, or security
    risk assessment — yields the generic `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/not_found_vendor_path_segment_uses_per_entity_error_id
    """
    response = api.get_vendor(NON_EXISTENT_UUID, make_privacy_officer_headers())
    error = validate_error(response, ApiErrorId.VENDOR_NOT_FOUND.value)
    assert error["error_id"] != ApiErrorId.RESOURCE_NOT_FOUND.value


# ---------------------------------------------------------------------------
# regulated_flag is read off the element leg of the junction
# ---------------------------------------------------------------------------


def test_mapping_takes_its_regulated_flag_from_the_classification_of_its_element_leg(
    api: ApiClient,
) -> None:
    """Two mappings on one purpose diverge on regulated_flag because their elements do.

    PRD §3.3: "A mapping is created with `status` `PROPOSED`, a null
    `suspension_reason`, and `regulated_flag` computed from the referenced element: true
    when that element's `chd_classification` is `CHD` or `CHD_BY_INFERENCE`, false
    otherwise."
    PRD §3.3: "The `vendor_id` is null when the purpose's `activity_kind` is `COLLECT`;
    when the purpose's `third_party_disclosure_required` is true and no `vendor_id` is
    supplied, the proposal is refused with `ERR_VENDOR_REQUIRED_FOR_DISCLOSURE`."

    Design: Corner/endpoints/cross_reference_link_mapping_marks_the_regulated_flag_from_both_legs
    """
    set_clock(CLOCK_AUG_05, api)
    product = create_product(api)
    chd_element = create_element(product["id"], api, element_key="apnea_dx")
    plain_element = create_element(
        product["id"],
        api,
        element_key="app_theme",
        display_name="App theme preference",
        health_signal_kind="NON_HEALTH",
    )
    purpose = create_purpose(product["id"], api, purpose_key="core_service")

    plain_mapping = validate_success(
        api.create_element_purpose_mapping(
            {
                "data_element_id": plain_element["id"],
                "processing_purpose_id": purpose["id"],
                "disclosure_specificity": "CATEGORY_NAMED",
            },
            make_data_steward_headers(),
        ),
        201,
    )
    assert plain_mapping["regulated_flag"] is False

    chd_mapping = validate_success(
        api.create_element_purpose_mapping(
            {
                "data_element_id": chd_element["id"],
                "processing_purpose_id": purpose["id"],
                "disclosure_specificity": "ELEMENT_NAMED",
            },
            make_data_steward_headers(),
        ),
        201,
    )
    assert_element_purpose_mapping(chd_mapping)
    assert chd_mapping["regulated_flag"] is True
    assert chd_mapping["status"] == "PROPOSED"
    assert chd_mapping["vendor_id"] is None
    assert chd_mapping["suspension_reason"] is None


# ---------------------------------------------------------------------------
# Executing an agreement twice
# ---------------------------------------------------------------------------


def test_second_execute_agreement_is_refused_and_leaves_the_original_stamp_intact(
    api: ApiClient,
) -> None:
    """Execution is not idempotent: the second call finds no DRAFT from-state.

    PRD §3.4: "Execution moves the vendor `DRAFT → EXECUTED`, stamps `executed_at` with
    the logical clock, and recomputes `agreement_compliance`."
    PRD §2.7: "A data element action that requires an `ACTIVE` element fails with
    `ERR_ELEMENT_RETIRED`; a policy publish or return-to-draft on a version not in
    `IN_REVIEW` fails with `ERR_POLICY_NOT_IN_REVIEW`; a deletion-task notify or reissue
    whose vendor agreement is not `EXECUTED` fails with
    `ERR_VENDOR_AGREEMENT_NOT_EXECUTED`; a target already sitting in one of its terminal
    states fails with `ERR_ALREADY_TERMINAL`; every other from-state mismatch fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/idempotency_second_execute_agreement_rejected
    """
    set_clock(CLOCK_AUG_05, api)
    product = create_product(api)
    vendor = create_vendor(product["id"], api, vendor_name="AdCo")
    executed = validate_success(
        api.execute_vendor_agreement(vendor["id"], make_privacy_officer_headers())
    )
    assert executed["agreement_state"] == "EXECUTED"
    assert _instant(executed["executed_at"]) == _instant(CLOCK_AUG_05)

    set_clock(CLOCK_AUG_06, api)
    response = api.execute_vendor_agreement(
        vendor["id"], make_privacy_officer_headers()
    )
    validate_error(response, ApiErrorId.INVALID_STATE.value)

    unchanged = _read_vendor(api, vendor["id"])
    assert unchanged["agreement_state"] == "EXECUTED"
    assert _instant(unchanged["executed_at"]) == _instant(CLOCK_AUG_05)


# ---------------------------------------------------------------------------
# A disclosing purpose demands a recipient vendor
# ---------------------------------------------------------------------------


def test_mapping_onto_a_share_purpose_without_a_vendor_is_refused(
    api: ApiClient,
) -> None:
    """The vendor requirement fires only for purposes that disclose to a third party.

    PRD §3.3: "`third_party_disclosure_required` is true precisely when the
    `activity_kind` is `SHARE` or `SELL`, and when it is true, any mapping onto that
    purpose must name a recipient vendor."
    PRD §3.3: "The `vendor_id` is null when the purpose's `activity_kind` is `COLLECT`;
    when the purpose's `third_party_disclosure_required` is true and no `vendor_id` is
    supplied, the proposal is refused with `ERR_VENDOR_REQUIRED_FOR_DISCLOSURE`."

    Design: Corner/validations/conditional_validation_share_purpose_without_vendor_rejected
    """
    set_clock(CLOCK_AUG_05, api)
    product = create_product(api)
    element = create_element(product["id"], api, element_key="apnea_dx")
    collect_purpose = create_purpose(product["id"], api, purpose_key="core_service")
    share_purpose = create_purpose(
        product["id"],
        api,
        purpose_key="ad_partner_share",
        description_text="Share with advertising partners",
        purpose_kind="ADVERTISING",
        activity_kind="SHARE",
    )
    assert collect_purpose["third_party_disclosure_required"] is False
    assert share_purpose["third_party_disclosure_required"] is True

    collect_mapping = create_mapping(element["id"], collect_purpose["id"], api)
    assert collect_mapping["status"] == "PROPOSED"

    response = api.create_element_purpose_mapping(
        {
            "data_element_id": element["id"],
            "processing_purpose_id": share_purpose["id"],
            "disclosure_specificity": "ELEMENT_NAMED",
        },
        make_data_steward_headers(),
    )
    validate_error(response, ApiErrorId.VENDOR_REQUIRED_FOR_DISCLOSURE.value)

    assert _read_mapping(api, collect_mapping["id"])["status"] == "PROPOSED"
    _rows, meta = validate_paginated(
        api.list_element_purpose_mappings(
            make_data_steward_headers(),
            {"processing_purpose_id": share_purpose["id"]},
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Body foreign-key resolution order on mapping creation
# ---------------------------------------------------------------------------


def test_unknown_data_element_on_mapping_create_reports_the_element_not_found_code(
    api: ApiClient,
) -> None:
    """data_element_id resolves before processing_purpose_id, so the element 404 wins.

    PRD §2.6: "Foreign keys inside a request body are resolved after the body's shape has
    been validated, and they too are resolved in a fixed order rather than in whatever
    order the client happened to serialise them: `app_product_id`, then
    `applicability_assessment_id`, then `consumer_id`, then `data_element_id`, then
    `derived_from_element_id`, then `processing_purpose_id`, then `vendor_id`, then
    `subprocessor_of_id`, then `geofence_zone_id`, then `consumer_request_id`."
    PRD §2.6: "Each unresolved key maps to the same per-entity 404 code listed above."

    Design: Corner/errors/error_data_element_not_found_on_mapping_create
    """
    product = create_product(api)
    purpose = create_purpose(product["id"], api, purpose_key="core_service")

    response = api.create_element_purpose_mapping(
        {
            "data_element_id": NON_EXISTENT_UUID,
            "processing_purpose_id": purpose["id"],
            "disclosure_specificity": "CATEGORY_NAMED",
        },
        make_data_steward_headers(),
    )
    validate_error(response, ApiErrorId.DATA_ELEMENT_NOT_FOUND.value)


def test_unknown_processing_purpose_on_mapping_create_reports_the_purpose_not_found_code(
    api: ApiClient,
) -> None:
    """With the element leg resolvable, the next key in the order carries its own 404.

    PRD §2.6: "Foreign keys inside a request body are resolved after the body's shape has
    been validated, and they too are resolved in a fixed order rather than in whatever
    order the client happened to serialise them: `app_product_id`, then
    `applicability_assessment_id`, then `consumer_id`, then `data_element_id`, then
    `derived_from_element_id`, then `processing_purpose_id`, then `vendor_id`, then
    `subprocessor_of_id`, then `geofence_zone_id`, then `consumer_request_id`."
    PRD §2.6: "Each unresolved key maps to the same per-entity 404 code listed above."

    Design: Corner/errors/error_purpose_not_found_on_mapping_create
    """
    product = create_product(api)
    element = create_element(product["id"], api, element_key="apnea_dx")

    response = api.create_element_purpose_mapping(
        {
            "data_element_id": element["id"],
            "processing_purpose_id": NON_EXISTENT_UUID,
            "disclosure_specificity": "CATEGORY_NAMED",
        },
        make_data_steward_headers(),
    )
    validate_error(response, ApiErrorId.PURPOSE_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# The activation gate: element liveness and product applicability
# ---------------------------------------------------------------------------


def test_activating_a_mapping_over_a_retired_element_reports_the_element_retired_code(
    api: ApiClient,
) -> None:
    """A mapping proposed after the retirement escapes the cascade but cannot activate.

    PRD §3.3: "A mapping may be activated `PROPOSED → ACTIVE` or resumed
    `SUSPENDED → ACTIVE`; either way, the referenced data element's `status` must be
    `ACTIVE`, the product's `applicability_status` must be `DUAL_TRACK` or
    `CHD_REGULATED` — an `UNDETERMINED` or `HIPAA_ONLY` product has no
    consumer-health-data regime under which to authorise the flow, and the attempt is
    refused with `ERR_APPLICABILITY_UNDETERMINED` — and the product's
    `policy_compliance_state` must not be `LAPSED`, failing which the refusal is
    `ERR_POLICY_LAPSED`."
    PRD §2.7: "A data element action that requires an `ACTIVE` element fails with
    `ERR_ELEMENT_RETIRED`; a policy publish or return-to-draft on a version not in
    `IN_REVIEW` fails with `ERR_POLICY_NOT_IN_REVIEW`; a deletion-task notify or reissue
    whose vendor agreement is not `EXECUTED` fails with
    `ERR_VENDOR_AGREEMENT_NOT_EXECUTED`; a target already sitting in one of its terminal
    states fails with `ERR_ALREADY_TERMINAL`; every other from-state mismatch fails with
    `ERR_INVALID_STATE`."

    Design: Corner/errors/error_element_retired_on_mapping_activate
    """
    set_clock(CLOCK_AUG_05, api)
    product = create_product(api)
    element = create_element(product["id"], api, element_key="apnea_dx")
    purpose = create_purpose(product["id"], api, purpose_key="core_service")
    validate_success(
        api.retire_data_element(
            element["id"], {"retired_reason": "Signal dropped"}, make_data_steward_headers()
        )
    )
    mapping = create_mapping(element["id"], purpose["id"], api)

    response = api.activate_element_purpose_mapping(
        mapping["id"], make_data_steward_headers()
    )
    validate_error(response, ApiErrorId.ELEMENT_RETIRED.value)

    assert _read_mapping(api, mapping["id"])["status"] == "PROPOSED"
    retired = validate_success(
        api.get_data_element(element["id"], make_data_steward_headers())
    )
    assert retired["status"] == "RETIRED"


def test_activating_a_mapping_on_an_undetermined_product_reports_the_applicability_code(
    api: ApiClient,
) -> None:
    """Without an approved assessment there is no regime under which to authorise a flow.

    PRD §3.3: "A mapping may be activated `PROPOSED → ACTIVE` or resumed
    `SUSPENDED → ACTIVE`; either way, the referenced data element's `status` must be
    `ACTIVE`, the product's `applicability_status` must be `DUAL_TRACK` or
    `CHD_REGULATED` — an `UNDETERMINED` or `HIPAA_ONLY` product has no
    consumer-health-data regime under which to authorise the flow, and the attempt is
    refused with `ERR_APPLICABILITY_UNDETERMINED` — and the product's
    `policy_compliance_state` must not be `LAPSED`, failing which the refusal is
    `ERR_POLICY_LAPSED`."
    PRD §3.1: "The product begins life with `applicability_status` at `UNDETERMINED`,
    `regulated_scope` at `NONE`, `policy_compliance_state` at `NO_POLICY`,
    `security_program_state` at `NONE`, a null `compliance_deadline_date`, and every
    counter at zero."

    Design: Corner/errors/error_applicability_undetermined_on_mapping_activate
    """
    set_clock(CLOCK_AUG_05, api)
    product = create_product(api)
    element = create_element(product["id"], api, element_key="apnea_dx")
    purpose = create_purpose(product["id"], api, purpose_key="core_service")
    mapping = create_mapping(element["id"], purpose["id"], api)

    response = api.activate_element_purpose_mapping(
        mapping["id"], make_data_steward_headers()
    )
    validate_error(response, ApiErrorId.APPLICABILITY_UNDETERMINED.value)

    assert read_product(product["id"], api)["applicability_status"] == "UNDETERMINED"
    assert _read_mapping(api, mapping["id"])["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# The three gates on agreement execution
# ---------------------------------------------------------------------------


def test_execute_agreement_without_a_flow_down_clause_is_refused(api: ApiClient) -> None:
    """The flow-down gate bites first, before the audit-rights gate is reached.

    PRD §3.4: "Three conditions gate it, and each has its own code: `flow_down_clause`
    must be true, otherwise `ERR_FLOW_DOWN_CLAUSE_MISSING`; `audit_rights_clause` must be
    true, otherwise `ERR_AUDIT_RIGHTS_MISSING`; and `subprocessor_of_id` must be null or
    name a parent vendor whose own `agreement_state` is already `EXECUTED`, otherwise
    `ERR_SUBPROCESSOR_PARENT_NOT_EXECUTED`."

    Design: Corner/errors/error_flow_down_clause_missing_on_execute_agreement
    """
    product = create_product(api)
    vendor = create_vendor(
        product["id"],
        api,
        vendor_name="AdCo",
        flow_down_clause=False,
        audit_rights_clause=True,
    )

    response = api.execute_vendor_agreement(
        vendor["id"], make_privacy_officer_headers()
    )
    validate_error(response, ApiErrorId.FLOW_DOWN_CLAUSE_MISSING.value)

    unchanged = _read_vendor(api, vendor["id"])
    assert unchanged["agreement_state"] == "DRAFT"
    assert unchanged["agreement_compliance"] == "DEFICIENT"
    assert unchanged["executed_at"] is None


def test_execute_agreement_without_audit_rights_is_refused_after_the_flow_down_gate(
    api: ApiClient,
) -> None:
    """Amending the draft to carry flow-down alone exposes the audit-rights gate.

    PRD §3.4: "Three conditions gate it, and each has its own code: `flow_down_clause`
    must be true, otherwise `ERR_FLOW_DOWN_CLAUSE_MISSING`; `audit_rights_clause` must be
    true, otherwise `ERR_AUDIT_RIGHTS_MISSING`; and `subprocessor_of_id` must be null or
    name a parent vendor whose own `agreement_state` is already `EXECUTED`, otherwise
    `ERR_SUBPROCESSOR_PARENT_NOT_EXECUTED`."
    PRD §3.4: "The four clause and SLA fields remain amendable while the agreement is
    still in `DRAFT`."

    Design: Corner/errors/error_audit_rights_missing_on_execute_agreement
    """
    product = create_product(api)
    vendor = create_vendor(
        product["id"],
        api,
        vendor_name="AdCo",
        flow_down_clause=False,
        audit_rights_clause=False,
    )
    amended = validate_success(
        api.update_vendor(
            vendor["id"], {"flow_down_clause": True}, make_privacy_officer_headers()
        )
    )
    assert amended["flow_down_clause"] is True
    assert amended["audit_rights_clause"] is False

    response = api.execute_vendor_agreement(
        vendor["id"], make_privacy_officer_headers()
    )
    validate_error(response, ApiErrorId.AUDIT_RIGHTS_MISSING.value)

    unchanged = _read_vendor(api, vendor["id"])
    assert unchanged["flow_down_clause"] is True
    assert unchanged["audit_rights_clause"] is False
    assert unchanged["agreement_state"] == "DRAFT"


def test_subprocessor_cannot_execute_while_its_engaging_vendor_is_still_a_draft(
    api: ApiClient,
) -> None:
    """A fully claused subprocessor is still blocked by its parent's DRAFT agreement.

    PRD §3.4: "Three conditions gate it, and each has its own code: `flow_down_clause`
    must be true, otherwise `ERR_FLOW_DOWN_CLAUSE_MISSING`; `audit_rights_clause` must be
    true, otherwise `ERR_AUDIT_RIGHTS_MISSING`; and `subprocessor_of_id` must be null or
    name a parent vendor whose own `agreement_state` is already `EXECUTED`, otherwise
    `ERR_SUBPROCESSOR_PARENT_NOT_EXECUTED`."
    PRD §3.4: "A subprocessor can never be brought live ahead of the vendor that engaged
    it."

    Design: Corner/errors/error_subprocessor_parent_not_executed_on_execute_agreement
    """
    product = create_product(api)
    parent = create_vendor(product["id"], api, vendor_name="AdCo")
    child = create_vendor(
        product["id"],
        api,
        vendor_name="AdCo Analytics",
        vendor_kind="PROCESSOR",
        subprocessor_of_id=parent["id"],
    )

    response = api.execute_vendor_agreement(child["id"], make_privacy_officer_headers())
    validate_error(response, ApiErrorId.SUBPROCESSOR_PARENT_NOT_EXECUTED.value)

    assert _read_vendor(api, child["id"])["agreement_state"] == "DRAFT"
    assert _read_vendor(api, parent["id"])["agreement_state"] == "DRAFT"


# ---------------------------------------------------------------------------
# Per-product uniqueness of purpose keys and vendor names
# ---------------------------------------------------------------------------


def test_second_purpose_reusing_a_purpose_key_on_the_same_product_is_refused(
    api: ApiClient,
) -> None:
    """A purpose key already taken on the product is refused even under another activity.

    PRD §3.3: "A `purpose_key` already taken on the same product is refused with
    `ERR_DUPLICATE_PURPOSE_KEY`."

    Design: Corner/errors/error_duplicate_purpose_key_within_product
    """
    product = create_product(api)
    create_purpose(product["id"], api, purpose_key="core_service")

    response = api.create_processing_purpose(
        create_processing_purpose_payload(
            product["id"],
            purpose_key="core_service",
            description_text="Share for service delivery",
            purpose_kind="PRIMARY_SERVICE",
            activity_kind="SHARE",
        ),
        make_data_steward_headers(),
    )
    validate_error(response, ApiErrorId.DUPLICATE_PURPOSE_KEY.value)

    _rows, meta = validate_paginated(
        api.list_processing_purposes(
            make_data_steward_headers(), {"app_product_id": product["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_second_vendor_reusing_a_vendor_name_on_the_same_product_is_refused(
    api: ApiClient,
) -> None:
    """A vendor name already taken on the product is refused even under another kind.

    PRD §3.4: "A `PrivacyOfficer` registers each **vendor** the product engages against
    the owning `app_product_id`, with its legal name in `vendor_name` — unique within the
    product, on pain of `ERR_DUPLICATE_VENDOR_NAME` — and the role it plays with respect
    to the data in `vendor_kind` (`PROCESSOR`, `THIRD_PARTY_RECIPIENT`, or `PURCHASER`)."

    Design: Corner/errors/error_duplicate_vendor_name_within_product
    """
    product = create_product(api)
    incumbent = create_vendor(product["id"], api, vendor_name="AdCo")

    response = api.create_vendor(
        create_vendor_payload(
            product["id"], vendor_name="AdCo", vendor_kind="PROCESSOR"
        ),
        make_privacy_officer_headers(),
    )
    validate_error(response, ApiErrorId.DUPLICATE_VENDOR_NAME.value)

    assert _read_vendor(api, incumbent["id"])["vendor_kind"] == "THIRD_PARTY_RECIPIENT"
    _rows, meta = validate_paginated(
        api.list_vendors(
            make_privacy_officer_headers(), {"app_product_id": product["id"]}
        )
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The activation response and the product counters agree immediately
# ---------------------------------------------------------------------------


def test_activation_response_and_the_next_product_read_report_the_same_regulated_scope(
    api: ApiClient,
) -> None:
    """The activate response and the very next product read agree with no lag.

    PRD §3.3: "Activation from `PROPOSED` recomputes `regulated_flag` from the element's
    current `chd_classification`; resumption from `SUSPENDED` clears `suspension_reason`
    back to null."
    PRD §2.11: "`active_element_count` is the number of that product's data elements
    whose `status` is `ACTIVE`."
    PRD §2.11: "`regulated_element_count` is the number of those `ACTIVE` elements whose
    `chd_classification` is `CHD` or `CHD_BY_INFERENCE`."

    Design: Corner/consistency_model/immediate_visibility_activation_response_and_product_counters_agree
    """
    set_clock(CLOCK_AUG_05, api)
    product = create_product(api)
    element = create_element(product["id"], api, element_key="apnea_dx")
    purpose = create_purpose(product["id"], api, purpose_key="core_service")
    create_approved_assessment(product["id"], api)
    mapping = create_mapping(element["id"], purpose["id"], api)

    activated = validate_success(
        api.activate_element_purpose_mapping(
            mapping["id"], make_data_steward_headers()
        )
    )
    assert activated["status"] == "ACTIVE"
    assert activated["regulated_flag"] is True

    refreshed = read_product(product["id"], api)
    assert refreshed["regulated_element_count"] == 1
    assert refreshed["active_element_count"] == 1

    classified = validate_success(
        api.get_data_element(element["id"], make_data_steward_headers())
    )
    assert classified["chd_classification"] == "CHD"
