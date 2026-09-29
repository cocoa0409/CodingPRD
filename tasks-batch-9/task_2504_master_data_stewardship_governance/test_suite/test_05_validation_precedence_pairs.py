"""Requests that break two governance rules at once, and which one is reported.

A steward assignment sent on a stale concurrency anchor that would also collide
with the sitting incumbent is refused on the anchor, and only once the caller
refreshes it does the interval collision surface. A merge proposal pairing
records from two different domains that would also score below the attention
floor is refused on the domain mismatch, and only a same-domain pairing is ever
judged on its score.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    add_master_record,
    assign_steward,
    create_domain,
    create_quality_rule,
    create_source_system,
    create_steward,
    domain_version,
    make_data_steward_headers,
    merge_proposal_payload,
    register_source,
    set_clock,
    setup_governed_domain,
    steward_assignment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _governed_domain_with_a_sitting_steward(api):
    """A live domain whose open-ended stewardship is held by one incumbent, plus a
    third steward waiting in the wings and the domain version as it read before
    activation moved it on."""
    set_clock()
    domain = create_domain()
    owner = create_steward(
        full_name="Olivia Owner",
        email="olivia@mdm.test",
        certification_level="PRINCIPAL",
    )
    incumbent_steward = create_steward(
        full_name="Sam Steward", email="sam@mdm.test", certification_level="SENIOR"
    )
    successor_steward = create_steward(
        full_name="Tina Third", email="tina@mdm.test", certification_level="JUNIOR"
    )
    assign_steward(domain["id"], owner["id"], "DATA_OWNER")
    incumbent = assign_steward(
        domain["id"], incumbent_steward["id"], "DATA_STEWARD"
    )
    erp = create_source_system(certify=True)
    register_source(domain["id"], erp["id"], role="AUTHORITATIVE", trust_rank=1)
    create_quality_rule(
        domain["id"],
        incumbent_steward["id"],
        make_data_steward_headers(incumbent_steward["id"]),
    )

    version_before_activation = domain_version(domain["id"])
    validate_success(api.activate_domain(domain["id"], GOVERNANCE_ADMIN_HEADERS))

    return domain, incumbent, successor_steward, version_before_activation


def _overlapping_assignment_payload(domain, successor_steward, expected_version):
    """A handover-less assignment that intersects the open-ended incumbent."""
    return steward_assignment_payload(
        domain["id"],
        successor_steward["id"],
        expected_version,
        steward_role="DATA_STEWARD",
        effective_from="2026-08-15T00:00:00Z",
    )


def _active_stewardship_of(api, domain):
    return validate_paginated(
        api.list_steward_assignments(
            GOVERNANCE_ADMIN_HEADERS,
            params={
                "domain_id": domain["id"],
                "steward_role": "DATA_STEWARD",
                "status": "ACTIVE",
            },
        )
    )


def _two_domains_sharing_one_certified_source(api):
    """A customer domain and a product domain, both live and both fed by the same
    certified authoritative system."""
    customer_ctx = setup_governed_domain()
    product = create_domain(code="PRODUCT", name="Product Master")
    assign_steward(product["id"], customer_ctx["owner"]["id"], "DATA_OWNER")
    assign_steward(product["id"], customer_ctx["steward"]["id"], "DATA_STEWARD")
    register_source(
        product["id"],
        customer_ctx["sources"]["ERP"]["id"],
        role="AUTHORITATIVE",
        trust_rank=1,
    )
    create_quality_rule(
        product["id"],
        customer_ctx["steward"]["id"],
        customer_ctx["steward_headers"],
        rule_code="PR1",
    )
    validate_success(api.activate_domain(product["id"], GOVERNANCE_ADMIN_HEADERS))

    product_ctx = dict(customer_ctx)
    product_ctx["domain"] = product
    return customer_ctx, product_ctx


def _thin_attributes():
    return {
        "legal_name": "Acme Industrial",
        "tax_id": "TX-77",
        "billing_city": "Austin",
    }


def _weak_similarity():
    return {"name_similarity_pct": 10.00, "key_overlap_pct": 10.00}


def test_the_stale_anchor_is_reported_ahead_of_the_interval_collision(api):
    """The refreshed-version complaint comes before the overlap complaint.

    Validations are evaluated in the following fifteen-step priority sequence, and the first failure determines the response — later checks are not reached and their errors are never returned in preference to an earlier one.
    7. **Domain version freshness.** `expected_domain_version` equals the current `Domain.version`. Violation: `ERR_STALE_DOMAIN_VERSION` (412). Applies to source-registration creation and steward-assignment creation only.
    13. **Interval and calendar geometry.** Steward-assignment intervals may not overlap for the same domain and accountability role unless the incoming assignment is explicitly superseding (`ERR_ASSIGNMENT_OVERLAP`, 409); a supplied `effective_to` must fall strictly after `effective_from` (`ERR_INVALID_INTERVAL`, 422); a freeze window must clear every other scheduled window on the domain by at least 72 hours (`ERR_FREEZE_WINDOW_CONFLICT`, 409); `scheduled_apply_at` must be at or after the computed `earliest_apply_at` (`ERR_LEAD_TIME_NOT_SATISFIED`, 409); and applying requires the logical clock to have reached `scheduled_apply_at` (`ERR_APPLY_WINDOW_NOT_REACHED`, 409).
    Creating a steward assignment is guarded identically: it too requires `expected_domain_version` matching the domain's current `version`, and a mismatch is rejected with `ERR_STALE_DOMAIN_VERSION` (HTTP 412).
    When all four hold, the `DRAFT → ACTIVE` transition sets `status` to `ACTIVE`, stamps `activated_at` from the logical clock, recomputes `governance_posture`, and advances the domain's `version` by one.

    Design: Difficulty/priority_pair_validation_conflict/stale_domain_version_precedes_assignment_overlap
    """
    (
        domain,
        _incumbent,
        successor_steward,
        version_before_activation,
    ) = _governed_domain_with_a_sitting_steward(api)

    assert domain_version(domain["id"]) == version_before_activation + 1, (
        "activation must advance the domain's concurrency anchor by exactly one, "
        f"got {domain_version(domain['id'])} from {version_before_activation}"
    )

    response = api.create_steward_assignment(
        _overlapping_assignment_payload(
            domain, successor_steward, version_before_activation
        ),
        GOVERNANCE_ADMIN_HEADERS,
    )

    validate_error(response, "ERR_STALE_DOMAIN_VERSION")


def test_the_rejected_handover_leaves_the_incumbent_and_the_anchor_alone(api):
    """A refused assignment writes nothing at all onto the accountability picture.

    A request that ends up mutating nothing on the domain leaves `version` untouched.
    The incoming assignment itself is created `ACTIVE` with a null `superseded_at`.
    A handover drives the incumbent from `ACTIVE` to `SUPERSEDED`, and it is only available when the incumbent is `ACTIVE` with a null `effective_to`, when the incumbent's `domain_id` and `steward_role` both match the incoming assignment's, and when the incumbent's `effective_from` is strictly earlier than the incoming assignment's `effective_from`.
    Assignments may be listed filtered by `domain_id`, by `steward_id`, by `steward_role` and by `status`.

    Design: Difficulty/priority_pair_validation_conflict/stale_domain_version_precedes_assignment_overlap
    """
    (
        domain,
        incumbent,
        successor_steward,
        version_before_activation,
    ) = _governed_domain_with_a_sitting_steward(api)
    anchor_before_attempt = domain_version(domain["id"])

    validate_error(
        api.create_steward_assignment(
            _overlapping_assignment_payload(
                domain, successor_steward, version_before_activation
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_STALE_DOMAIN_VERSION",
    )

    assignments, meta = _active_stewardship_of(api, domain)
    assert meta["total_count"] == 1, (
        "the refused assignment must not have joined the domain's active "
        f"stewardship, got {meta['total_count']} active steward assignments"
    )
    assert assignments[0]["id"] == incumbent["id"], (
        "the sitting incumbent must still be the one active steward, got "
        f"assignment {assignments[0]['id']}"
    )

    still_incumbent = validate_success(
        api.get_steward_assignment(incumbent["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert still_incumbent["status"] == "ACTIVE", (
        "no handover took place, so the incumbent must remain active, got "
        f"{still_incumbent['status']}"
    )
    assert still_incumbent["effective_to"] is None, (
        "no handover took place, so the incumbent's interval must stay open "
        f"ended, got {still_incumbent['effective_to']}"
    )
    assert still_incumbent["superseded_at"] is None, (
        "no handover took place, so the incumbent must carry no supersession "
        f"instant, got {still_incumbent['superseded_at']}"
    )
    assert domain_version(domain["id"]) == anchor_before_attempt, (
        "a request that mutated nothing must leave the domain's anchor where it "
        f"was at {anchor_before_attempt}, got {domain_version(domain['id'])}"
    )


def test_the_interval_collision_surfaces_once_the_anchor_is_current(api):
    """With the version refreshed, the overlap is what stands in the way.

    Two assignments for the same domain and the same `steward_role` may not have intersecting intervals; an incoming assignment that would intersect an `ACTIVE` incumbent is rejected with `ERR_ASSIGNMENT_OVERLAP` unless the caller explicitly asks to hand over by sending `supersede_incumbent` set to true.
    Because cascades make the exact number of intervening bumps hard for a client to predict, any client about to perform a version-checked write should read the domain immediately beforehand and send back the value it just observed.
    A request that ends up mutating nothing on the domain leaves `version` untouched.

    Design: Difficulty/priority_pair_validation_conflict/stale_domain_version_precedes_assignment_overlap
    """
    (
        domain,
        _incumbent,
        successor_steward,
        version_before_activation,
    ) = _governed_domain_with_a_sitting_steward(api)

    validate_error(
        api.create_steward_assignment(
            _overlapping_assignment_payload(
                domain, successor_steward, version_before_activation
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_STALE_DOMAIN_VERSION",
    )

    current_anchor = domain_version(domain["id"])
    retry = api.create_steward_assignment(
        _overlapping_assignment_payload(domain, successor_steward, current_anchor),
        GOVERNANCE_ADMIN_HEADERS,
    )

    validate_error(retry, "ERR_ASSIGNMENT_OVERLAP")

    _assignments, meta = _active_stewardship_of(api, domain)
    assert meta["total_count"] == 1, (
        "the overlapping assignment must not have been created either, got "
        f"{meta['total_count']} active steward assignments"
    )


def test_a_cross_domain_pairing_is_refused_before_its_score_is_weighed(api):
    """Records from two different domains never reach the attention floor check.

    Validations are evaluated in the following fifteen-step priority sequence, and the first failure determines the response — later checks are not reached and their errors are never returned in preference to an earlier one.
    9. **Cross-entity linkage integrity.** A merge proposal's two records must belong to the same domain (`ERR_CROSS_DOMAIN_MERGE`) and must be distinct (`ERR_SELF_MERGE`); a measurement's `rule_code` must name an `ACTIVE` rule of the scored domain (`ERR_UNKNOWN_RULE_CODE`); a hierarchy-restructure payload's `parent_node_key` must differ from its `child_node_key` (`ERR_HIERARCHY_CYCLE`); a `lineage_path` must begin at the domain's `authoritative_source_code` (`ERR_LINEAGE_SOURCE_MISMATCH`), end at the subscription's `reporting_asset_key` (`ERR_LINEAGE_TARGET_MISMATCH`) and repeat no node key (`ERR_LINEAGE_CYCLE`), and lineage documentation requires the domain to hold an `ACTIVE` `AUTHORITATIVE` registration at all (`ERR_AUTHORITATIVE_SOURCE_UNDEFINED`).
    14. **Capacity, uniqueness and confidence constraints.** This step covers the domain-specific business constraints described throughout §3: `ERR_DUPLICATE_RULE_CODE`, `ERR_DUPLICATE_DOMAIN_CODE`, `ERR_DUPLICATE_CONSUMER_CODE`, `ERR_DUPLICATE_NATURAL_KEY`, `ERR_DUPLICATE_SOURCE_CODE`, `ERR_DUPLICATE_STEWARD_EMAIL`, `ERR_MATCH_SCORE_BELOW_FLOOR`, `ERR_MATCH_CONFIDENCE_TOO_LOW`, `ERR_CHANGE_CALENDAR_CAPACITY`, `ERR_RECORD_INCOMPLETE`, `ERR_OWNER_NOT_PRINCIPAL`, `ERR_LINEAGE_INCOMPLETE`, `ERR_TIER1_ACK_MISSING`, `ERR_NO_QUALITY_RULES`, `ERR_STEWARDSHIP_INCOMPLETE`, `ERR_NO_CERTIFIED_AUTHORITATIVE_SOURCE`, `ERR_DUE_DATE_IN_PAST`, `ERR_ASSIGNMENT_STEWARD_NOT_ELIGIBLE` and `ERR_RESOLUTION_BELOW_THRESHOLD`.
    The two records must belong to the same domain, or the proposal is rejected with `ERR_CROSS_DOMAIN_MERGE`, and they must be distinct rows, a proposal naming the same record twice being rejected with `ERR_SELF_MERGE`.

    Design: Difficulty/priority_pair_validation_conflict/cross_domain_merge_precedes_match_score_floor
    """
    customer_ctx, product_ctx = _two_domains_sharing_one_certified_source(api)
    customer_record = add_master_record(
        customer_ctx,
        source_code="ERP",
        natural_key="ERP-CUST-1001",
        attributes=_thin_attributes(),
    )
    product_record = add_master_record(
        product_ctx,
        source_code="ERP",
        natural_key="ERP-PROD-9001",
        attributes=_thin_attributes(),
    )

    response = api.create_merge_proposal(
        merge_proposal_payload(
            customer_record["id"], product_record["id"], **_weak_similarity()
        ),
        customer_ctx["steward_headers"],
    )

    validate_error(response, "ERR_CROSS_DOMAIN_MERGE")


def test_a_same_domain_pairing_is_then_refused_on_its_match_score(api):
    """Once the domains agree, sixteen points of evidence is below the floor.

    The system first forms a weighted sum of three inputs: five tenths of the `name_similarity_pct`, plus three tenths of the `key_overlap_pct`, plus two tenths of the lesser of the two candidates' `completeness_pct` values as those values stand persisted at the moment of the call.
    That weighted sum is rounded half up to two decimal places.
    Then a structural discount applies: intra-source duplicates are inherently less trustworthy, so when the survivor candidate and the duplicate candidate share the same `source_system_id`, the whole rounded composite is multiplied by eight tenths and the product is rounded half up to two decimal places again — the discount is applied *after* the weighted sum has been rounded, not folded into it.
    A proposal whose computed `match_score` falls below 45.00 is not worth a human's attention and is refused outright with `ERR_MATCH_SCORE_BELOW_FLOOR`, both at creation and at rescoring.
    That count is divided by the domain's `expected_attribute_count`, multiplied by one hundred, and rounded half up to two decimal places; the result is then capped at 100.00, so a record carrying more populated keys than the domain expects reads as exactly complete rather than over-complete.

    Design: Difficulty/priority_pair_validation_conflict/cross_domain_merge_precedes_match_score_floor
    """
    customer_ctx, _product_ctx = _two_domains_sharing_one_certified_source(api)
    thin_record = add_master_record(
        customer_ctx,
        source_code="ERP",
        natural_key="ERP-CUST-1001",
        attributes=_thin_attributes(),
    )
    fuller_record = add_master_record(
        customer_ctx, source_code="ERP", natural_key="ERP-CUST-1002"
    )

    assert thin_record["completeness_pct"] == 60.00, (
        "three populated keys against an expected five must read 60.00, got "
        f"{thin_record['completeness_pct']}"
    )
    assert fuller_record["completeness_pct"] == 80.00, (
        "four populated keys against an expected five must read 80.00, got "
        f"{fuller_record['completeness_pct']}"
    )

    response = api.create_merge_proposal(
        merge_proposal_payload(
            thin_record["id"], fuller_record["id"], **_weak_similarity()
        ),
        customer_ctx["steward_headers"],
    )

    validate_error(response, "ERR_MATCH_SCORE_BELOW_FLOOR")


def test_neither_refused_pairing_leaves_a_proposal_behind(api):
    """Two rejected hypotheses leave both domains with an empty duplicate queue.

    A new proposal is created in `status` `PROPOSED` with `reviewer_steward_id`, `effective_survivor_master_record_id`, `survivorship_variant`, `survivorship_field_map`, `override_justification` and `decided_at` all null, `survivor_swapped` false, and `rework_count` at 0.
    Proposals may be listed filtered by `domain_id`, `survivor_master_record_id`, `duplicate_master_record_id`, `effective_survivor_master_record_id`, `proposer_steward_id`, `reviewer_steward_id` and `status`.
    The proposal's own `domain_id` is not supplied — it is copied from the survivor candidate's domain at creation — and `proposer_steward_id` is set from the acting `X-User-ID`.

    Design: Difficulty/priority_pair_validation_conflict/cross_domain_merge_precedes_match_score_floor
    """
    customer_ctx, product_ctx = _two_domains_sharing_one_certified_source(api)
    thin_record = add_master_record(
        customer_ctx,
        source_code="ERP",
        natural_key="ERP-CUST-1001",
        attributes=_thin_attributes(),
    )
    fuller_record = add_master_record(
        customer_ctx, source_code="ERP", natural_key="ERP-CUST-1002"
    )
    product_record = add_master_record(
        product_ctx,
        source_code="ERP",
        natural_key="ERP-PROD-9001",
        attributes=_thin_attributes(),
    )

    validate_error(
        api.create_merge_proposal(
            merge_proposal_payload(
                thin_record["id"], product_record["id"], **_weak_similarity()
            ),
            customer_ctx["steward_headers"],
        ),
        "ERR_CROSS_DOMAIN_MERGE",
    )
    validate_error(
        api.create_merge_proposal(
            merge_proposal_payload(
                thin_record["id"], fuller_record["id"], **_weak_similarity()
            ),
            customer_ctx["steward_headers"],
        ),
        "ERR_MATCH_SCORE_BELOW_FLOOR",
    )

    _customer_proposals, customer_meta = validate_paginated(
        api.list_merge_proposals(
            GOVERNANCE_ADMIN_HEADERS, params={"domain_id": customer_ctx["domain"]["id"]}
        )
    )
    assert customer_meta["total_count"] == 0, (
        "no merge proposal may exist for the customer domain, got "
        f"{customer_meta['total_count']}"
    )

    _product_proposals, product_meta = validate_paginated(
        api.list_merge_proposals(
            GOVERNANCE_ADMIN_HEADERS, params={"domain_id": product_ctx["domain"]["id"]}
        )
    )
    assert product_meta["total_count"] == 0, (
        "no merge proposal may exist for the product domain either, got "
        f"{product_meta['total_count']}"
    )
