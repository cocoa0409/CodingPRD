"""Data element inventory: stored inputs, derived classification, and its guards.

Every test builds its own product and inventory from scratch, because the
server is relaunched against an empty database before each one.
"""

from __future__ import annotations

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    CLOCK_EPOCH,
    activate_mapping,
    assert_data_element,
    create_approved_assessment,
    create_data_element_payload,
    create_element,
    create_mapping,
    create_product,
    create_purpose,
    make_data_steward_headers,
    make_privacy_officer_headers,
    read_product,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_read_data_element_returns_stored_inputs_and_classification(api: ApiClient) -> None:
    """A single-element read echoes its inputs and exposes what create computed.

    PRD §3.2: "Creating an element runs this classification, writes
    `inference_depth` and `chd_classification`, and refreshes both
    `active_element_count` and `regulated_element_count` on the product."
    PRD §3.2: "Elements start with `status` at `ACTIVE` and a null
    `retired_reason`."
    PRD §3.2: "Otherwise, an element whose `health_signal_kind` is `DIAGNOSIS`,
    `TREATMENT`, `MEASUREMENT`, `REPRODUCTIVE`, or `BIOMETRIC` is `CHD`."

    Design: Corner/entities/retrieval_data_element_returns_stored_and_computed_fields
    """
    set_clock(CLOCK_EPOCH, api)
    product = create_product(api)
    element = create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )

    data = validate_success(api.get_data_element(element["id"], make_privacy_officer_headers()))

    assert_data_element(data)
    assert data["element_key"] == "apnea_dx"
    assert data["display_name"] == "Sleep apnea diagnosis"
    assert data["source_kind"] == "USER_PROVIDED"
    assert data["health_signal_kind"] == "DIAGNOSIS"
    assert data["derived_from_element_id"] is None
    assert data["hipaa_flow_only"] is False
    assert data["inference_depth"] == 0
    assert data["chd_classification"] == "CHD"
    assert data["status"] == "ACTIVE"
    assert data["retired_reason"] is None

    refreshed_product = read_product(product["id"], api)
    assert refreshed_product["active_element_count"] == 1
    assert refreshed_product["regulated_element_count"] == 1


def test_data_element_list_filters_by_status_and_paginates(api: ApiClient) -> None:
    """The status filter narrows the set that limit, offset and total_count describe.

    PRD §2.3: "Most list endpoints also accept domain filters, which are
    documented alongside the workflows in §3 and summarised here for
    convenience: app products by `applicability_status`; applicability
    assessments by `app_product_id` and `state`; data elements by
    `app_product_id`, `derived_from_element_id`, and `status`; processing
    purposes by `app_product_id` and `activity_kind`; element-purpose mappings
    by `data_element_id`, `processing_purpose_id`, `vendor_id`, and `status`;
    consumers by `app_product_id`; consent records by `consumer_id` and
    `record_state`; privacy policy versions by `app_product_id`,
    `applicability_assessment_id`, and `state`; consumer requests by
    `consumer_id`, `state`, and `request_kind`; deletion tasks by
    `consumer_request_id`, `vendor_id`, and `state`; vendors by
    `app_product_id`, `subprocessor_of_id`, and `agreement_state`; geofence
    zones by `app_product_id` and `prohibition_rule`; geofence campaigns by
    `geofence_zone_id`, `processing_purpose_id`, and `state`; breach incidents
    by `app_product_id` and `state`; and security risk assessments by
    `app_product_id`, `state`, and `risk_tier`."
    PRD §2.3: "`total_count` is the number of rows matching the filters before
    pagination; `has_more` is true when rows remain beyond the returned page."

    Design: Corner/entities/listing_data_elements_paginated_and_filtered_by_status
    """
    set_clock(CLOCK_EPOCH, api)
    product = create_product(api)
    create_element(
        product["id"],
        api,
        element_key="e1",
        display_name="Element one",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    create_element(
        product["id"],
        api,
        element_key="e2",
        display_name="Element two",
        source_kind="DEVICE_SENSOR",
        health_signal_kind="MEASUREMENT",
    )
    create_element(
        product["id"],
        api,
        element_key="e3",
        display_name="Element three",
        source_kind="USER_PROVIDED",
        health_signal_kind="NON_HEALTH",
    )
    retired = create_element(
        product["id"],
        api,
        element_key="e4",
        display_name="Element four",
        source_kind="USER_PROVIDED",
        health_signal_kind="NON_HEALTH",
    )
    validate_success(
        api.retire_data_element(
            retired["id"],
            {"retired_reason": "Dropped from the schema"},
            make_data_steward_headers(),
        )
    )

    rows, meta = validate_paginated(
        api.list_data_elements(
            make_data_steward_headers(),
            {"app_product_id": product["id"], "status": "ACTIVE", "limit": 2, "offset": 0},
        )
    )

    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert retired["id"] not in [row["id"] for row in rows]
    assert [row["status"] for row in rows] == ["ACTIVE", "ACTIVE"]


def test_declaring_element_without_element_key_is_malformed(api: ApiClient) -> None:
    """A missing required input fails the shape check before any inventory write.

    PRD §3.2: "A `DataSteward` declares each element the product collects with a
    stable machine key in `element_key`, a human-readable label in
    `display_name` that the privacy policy text will reuse, an acquisition
    channel in `source_kind` (`USER_PROVIDED`, `DEVICE_SENSOR`, `THIRD_PARTY`,
    or `DERIVED_INFERENCE`), and the health meaning the element itself carries
    in `health_signal_kind` (`DIAGNOSIS`, `TREATMENT`, `MEASUREMENT`,
    `REPRODUCTIVE`, `PRECISE_LOCATION`, `BIOMETRIC`, or `NON_HEALTH`),
    alongside the owning `app_product_id`."
    PRD §2.7: "Request-body shape: required fields present, enum values drawn
    from the declared members, integers inside their declared ranges,
    `named_third_party_count` not exceeding `disclosed_third_party_count`, and
    no computed or system field supplied — `ERR_INVALID_REQUEST`, 400, on every
    creation and amendment endpoint."

    Design: Corner/entities/required_fields_missing_element_key_returns_400
    """
    product = create_product(api)
    payload = create_data_element_payload(product["id"])
    payload.pop("element_key")

    validate_error(
        api.create_data_element(payload, make_data_steward_headers()),
        ApiErrorId.INVALID_REQUEST.value,
    )

    assert read_product(product["id"], api)["active_element_count"] == 0


def test_declaring_element_with_supplied_classification_is_malformed(api: ApiClient) -> None:
    """A caller-supplied computed field is rejected rather than quietly ignored.

    PRD §2.4: "Fields marked as computed or system-managed anywhere in this
    specification are never accepted from a request body. Supplying one is a
    malformed request and yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/computed_fields_supplied_chd_classification_returns_400
    """
    product = create_product(api)
    payload = create_data_element_payload(
        product["id"],
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
        chd_classification="NON_CHD",
    )

    validate_error(
        api.create_data_element(payload, make_data_steward_headers()),
        ApiErrorId.INVALID_REQUEST.value,
    )

    refreshed_product = read_product(product["id"], api)
    assert refreshed_product["regulated_element_count"] == 0
    assert refreshed_product["active_element_count"] == 0


def test_declaring_element_under_unknown_product_is_not_found(api: ApiClient) -> None:
    """An unresolvable owning product in the body yields the product's own 404 id.

    PRD §2.6: "Which 404 is returned depends on the entity the segment
    addresses: an unresolved app product yields `ERR_APP_PRODUCT_NOT_FOUND`, an
    unresolved consumer `ERR_CONSUMER_NOT_FOUND`, an unresolved vendor
    `ERR_VENDOR_NOT_FOUND`, an unresolved data element
    `ERR_DATA_ELEMENT_NOT_FOUND`, an unresolved processing purpose
    `ERR_PURPOSE_NOT_FOUND`, and an unresolved row of any other type —
    applicability assessment, element-purpose mapping, consent record, privacy
    policy version, consumer request, deletion task, geofence zone, geofence
    campaign, breach incident, or security risk assessment — yields the generic
    `ERR_RESOURCE_NOT_FOUND`."
    PRD §2.6: "Each unresolved key maps to the same per-entity 404 code listed
    above."

    Design: Corner/entities/parent_relationships_data_element_under_unknown_product_not_found
    """
    payload = create_data_element_payload(
        NON_EXISTENT_UUID,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )

    validate_error(
        api.create_data_element(payload, make_data_steward_headers()),
        ApiErrorId.APP_PRODUCT_NOT_FOUND.value,
    )


def test_two_hop_inference_chain_inherits_chd_by_inference(api: ApiClient) -> None:
    """A signal-free element two hops below a diagnosis inherits regulated status.

    PRD §3.2: "Elements are then classified in ascending `inference_depth`, ties
    broken by ascending `created_at`, so that a parent's classification is
    always already settled when its child is evaluated."
    PRD §3.2: "Otherwise — that is, for a derived element with no health signal
    of its own — the element is `CHD_BY_INFERENCE` when its parent element's
    `chd_classification` is `CHD` or `CHD_BY_INFERENCE`."

    Design: Corner/calculations/correct_result_chd_classification_two_hop_inference_chain
    """
    set_clock(CLOCK_EPOCH, api)
    product = create_product(api)
    root = create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    mid = create_element(
        product["id"],
        api,
        element_key="apnea_risk",
        display_name="Apnea risk score",
        source_kind="DERIVED_INFERENCE",
        health_signal_kind="NON_HEALTH",
        derived_from_element_id=root["id"],
    )

    leaf = validate_success(
        api.create_data_element(
            create_data_element_payload(
                product["id"],
                element_key="apnea_segment",
                display_name="Apnea marketing segment",
                source_kind="DERIVED_INFERENCE",
                health_signal_kind="NON_HEALTH",
                derived_from_element_id=mid["id"],
            ),
            make_data_steward_headers(),
        ),
        201,
    )

    assert leaf["inference_depth"] == 2
    assert leaf["chd_classification"] == "CHD_BY_INFERENCE"

    root_read = validate_success(api.get_data_element(root["id"], make_data_steward_headers()))
    assert root_read["inference_depth"] == 0
    assert root_read["chd_classification"] == "CHD"

    mid_read = validate_success(api.get_data_element(mid["id"], make_data_steward_headers()))
    assert mid_read["inference_depth"] == 1
    assert mid_read["chd_classification"] == "CHD_BY_INFERENCE"

    refreshed_product = read_product(product["id"], api)
    assert refreshed_product["active_element_count"] == 3
    assert refreshed_product["regulated_element_count"] == 3


def test_retiring_leaf_element_drops_counters_but_keeps_classification(api: ApiClient) -> None:
    """Retirement removes an element from the counters without unclassifying it.

    PRD §3.2: "Classification runs whenever an element is written, amended,
    retired or reinstated, and as step two of the applicability determination."
    PRD §2.11: "`active_element_count` is the number of that product's data
    elements whose `status` is `ACTIVE`."
    PRD §2.11: "`regulated_element_count` is the number of those `ACTIVE`
    elements whose `chd_classification` is `CHD` or `CHD_BY_INFERENCE`."

    Design: Corner/calculations/input_set_filtering_retired_element_leaves_counts_but_keeps_classification
    """
    set_clock(CLOCK_EPOCH, api)
    product = create_product(api)
    root = create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    child = create_element(
        product["id"],
        api,
        element_key="apnea_risk",
        display_name="Apnea risk score",
        source_kind="DERIVED_INFERENCE",
        health_signal_kind="NON_HEALTH",
        derived_from_element_id=root["id"],
    )

    retired = validate_success(
        api.retire_data_element(
            child["id"],
            {"retired_reason": "Inference model decommissioned"},
            make_data_steward_headers(),
        )
    )

    assert retired["status"] == "RETIRED"
    assert retired["chd_classification"] == "CHD_BY_INFERENCE"
    assert retired["inference_depth"] == 1

    refreshed_product = read_product(product["id"], api)
    assert refreshed_product["active_element_count"] == 1
    assert refreshed_product["regulated_element_count"] == 1


def test_derivation_chain_beyond_five_hops_is_refused(api: ApiClient) -> None:
    """Five hops is admitted and the element that would sit at six is refused.

    PRD §3.2: "A walk whose hop count would exceed five hops is refused with
    `ERR_INFERENCE_DEPTH_EXCEEDED`; five hops is the deepest inference chain the
    product may declare."

    Design: Corner/calculations/topological_derivation_walk_of_six_hops_rejected
    """
    set_clock(CLOCK_EPOCH, api)
    product = create_product(api)
    chain = [
        create_element(
            product["id"],
            api,
            element_key="d0",
            display_name="Depth zero",
            source_kind="USER_PROVIDED",
            health_signal_kind="DIAGNOSIS",
        )
    ]
    for depth in range(1, 6):
        chain.append(
            create_element(
                product["id"],
                api,
                element_key=f"d{depth}",
                display_name=f"Depth {depth}",
                source_kind="DERIVED_INFERENCE",
                health_signal_kind="NON_HEALTH",
                derived_from_element_id=chain[-1]["id"],
            )
        )

    validate_error(
        api.create_data_element(
            create_data_element_payload(
                product["id"],
                element_key="d6",
                display_name="Depth six",
                source_kind="DERIVED_INFERENCE",
                health_signal_kind="NON_HEALTH",
                derived_from_element_id=chain[-1]["id"],
            ),
            make_data_steward_headers(),
        ),
        ApiErrorId.INFERENCE_DEPTH_EXCEEDED.value,
    )

    deepest = validate_success(api.get_data_element(chain[-1]["id"], make_data_steward_headers()))
    assert deepest["inference_depth"] == 5
    assert deepest["chd_classification"] == "CHD_BY_INFERENCE"

    refreshed_product = read_product(product["id"], api)
    assert refreshed_product["active_element_count"] == 6
    assert refreshed_product["regulated_element_count"] == 6


def test_reinstating_child_under_retired_parent_is_refused(api: ApiClient) -> None:
    """A derived element cannot come back to life ahead of the signal it reads.

    PRD §3.2: "Reinstatement runs the loop backwards, `RETIRED → ACTIVE`, and is
    admitted only when the element's `derived_from_element_id` is null or the
    parent element it names currently has `status` `ACTIVE`; reinstating a child
    under a still-retired parent is refused with `ERR_ELEMENT_PARENT_RETIRED`."

    Design: Corner/state_machines/guarded_transitions_reinstate_child_element_requires_active_parent
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    parent = create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    child = create_element(
        product["id"],
        api,
        element_key="apnea_risk_score",
        display_name="Apnea risk score",
        source_kind="DERIVED_INFERENCE",
        health_signal_kind="NON_HEALTH",
        derived_from_element_id=parent["id"],
    )
    validate_success(
        api.retire_data_element(
            child["id"], {"retired_reason": "Model retired"}, make_data_steward_headers()
        )
    )
    validate_success(
        api.retire_data_element(
            parent["id"], {"retired_reason": "Field removed"}, make_data_steward_headers()
        )
    )

    validate_error(
        api.reinstate_data_element(child["id"], make_data_steward_headers()),
        ApiErrorId.ELEMENT_PARENT_RETIRED.value,
    )

    child_read = validate_success(api.get_data_element(child["id"], make_data_steward_headers()))
    parent_read = validate_success(api.get_data_element(parent["id"], make_data_steward_headers()))
    assert child_read["status"] == "RETIRED"
    assert parent_read["status"] == "RETIRED"
    assert read_product(product["id"], api)["active_element_count"] == 0


def test_retiring_element_cascades_to_its_dependent_mapping(api: ApiClient) -> None:
    """Retiring the element retires the live mapping that reads it, in one call.

    PRD §3.2: "The first hop moves the named element `ACTIVE → RETIRED` and
    records the supplied `retired_reason`."
    PRD §3.2: "The third hop follows from the second: because that set of
    elements became `RETIRED`, every element-purpose mapping whose
    `data_element_id` names any element retired by hops one or two, and whose
    `status` is `PROPOSED`, `ACTIVE` or `SUSPENDED`, is moved to `RETIRED`."
    PRD §3.3: "In every case, `suspension_reason` is set to the reason supplied
    in the body — or to `SOURCE_ELEMENT_RETIRED` when the retirement was driven
    by the data element cascade of §3.2."
    PRD §3.2: "The fourth hop follows from the third: because the retired
    mapping set changed, the product's `active_element_count` and
    `regulated_element_count` are both recomputed."

    Design: Corner/state_machines/cascade_down_element_retirement_retires_dependent_mapping
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    element = create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    purpose = create_purpose(
        product["id"],
        api,
        purpose_key="core_service",
        description_text="Deliver the service",
        purpose_kind="PRIMARY_SERVICE",
        activity_kind="COLLECT",
    )
    create_approved_assessment(product["id"], api)
    mapping = create_mapping(
        element["id"], purpose["id"], api, disclosure_specificity="ELEMENT_NAMED"
    )
    mapping = activate_mapping(mapping["id"], api)
    assert mapping["status"] == "ACTIVE"

    retired = validate_success(
        api.retire_data_element(
            element["id"],
            {"retired_reason": "Signal dropped from the app"},
            make_data_steward_headers(),
        )
    )

    assert retired["status"] == "RETIRED"
    assert retired["retired_reason"] == "Signal dropped from the app"

    mapping_read = validate_success(
        api.get_element_purpose_mapping(mapping["id"], make_data_steward_headers())
    )
    assert mapping_read["status"] == "RETIRED"
    assert mapping_read["suspension_reason"] == "SOURCE_ELEMENT_RETIRED"

    refreshed_product = read_product(product["id"], api)
    assert refreshed_product["active_element_count"] == 0
    assert refreshed_product["regulated_element_count"] == 0


def test_inference_element_without_derivation_source_is_refused(api: ApiClient) -> None:
    """An inference that names no parent is a coherence failure, not a shape one.

    PRD §3.2: "A `source_kind` of `DERIVED_INFERENCE` requires a non-null
    `derived_from_element_id`, and a non-null `derived_from_element_id` requires
    a `source_kind` of `DERIVED_INFERENCE`; either half violated is rejected
    with `ERR_DERIVATION_SOURCE_REQUIRED`."

    Design: Corner/errors/error_derivation_source_required_on_inference_element
    """
    product = create_product(api)

    validate_error(
        api.create_data_element(
            create_data_element_payload(
                product["id"],
                element_key="orphan_inference",
                display_name="Orphan inference",
                source_kind="DERIVED_INFERENCE",
                health_signal_kind="NON_HEALTH",
            ),
            make_data_steward_headers(),
        ),
        ApiErrorId.DERIVATION_SOURCE_REQUIRED.value,
    )

    assert read_product(product["id"], api)["active_element_count"] == 0


def test_repointing_root_at_its_own_child_is_an_inference_cycle(api: ApiClient) -> None:
    """An amendment that closes the derivation walk into a loop is refused.

    PRD §3.2: "A walk that revisits an element it has already visited is a cycle
    and the write is refused with `ERR_INFERENCE_CYCLE`."
    PRD §2.7: "Derivation acyclicity — `ERR_INFERENCE_CYCLE`, 422, on data
    element creation and amendment."

    Design: Corner/errors/error_inference_cycle_on_repointing_the_root_at_its_own_child
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    root = create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    child = create_element(
        product["id"],
        api,
        element_key="apnea_risk",
        display_name="Apnea risk score",
        source_kind="DERIVED_INFERENCE",
        health_signal_kind="NON_HEALTH",
        derived_from_element_id=root["id"],
    )

    validate_error(
        api.update_data_element(
            root["id"],
            {"source_kind": "DERIVED_INFERENCE", "derived_from_element_id": child["id"]},
            make_data_steward_headers(),
        ),
        ApiErrorId.INFERENCE_CYCLE.value,
    )

    root_read = validate_success(api.get_data_element(root["id"], make_data_steward_headers()))
    child_read = validate_success(api.get_data_element(child["id"], make_data_steward_headers()))
    assert root_read["source_kind"] == "USER_PROVIDED"
    assert root_read["derived_from_element_id"] is None
    assert root_read["inference_depth"] == 0
    assert child_read["inference_depth"] == 1


def test_reusing_element_key_of_retired_element_is_refused(api: ApiClient) -> None:
    """Key uniqueness spans retired rows, so a retired key is not freed for reuse.

    PRD §3.2: "Keys are unique within a product: an `element_key` already in use
    by another element of the same product whose `status` is `ACTIVE` or
    `RETIRED` is refused with `ERR_DUPLICATE_ELEMENT_KEY`."

    Design: Corner/errors/error_duplicate_element_key_within_product
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    element = create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    validate_success(
        api.retire_data_element(
            element["id"], {"retired_reason": "Schema rewrite"}, make_data_steward_headers()
        )
    )

    validate_error(
        api.create_data_element(
            create_data_element_payload(
                product["id"],
                element_key="apnea_dx",
                display_name="Sleep apnea diagnosis v2",
                source_kind="USER_PROVIDED",
                health_signal_kind="DIAGNOSIS",
            ),
            make_data_steward_headers(),
        ),
        ApiErrorId.DUPLICATE_ELEMENT_KEY.value,
    )

    assert read_product(product["id"], api)["active_element_count"] == 0
