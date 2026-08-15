"""Vendor registry lifecycle and tag-rule governance rules."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_property, create_approved_vendor,
    create_property_payload, create_vendor_payload, create_banner_config_payload,
    create_tag_rule_payload,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
VM = TEST_USERS["vendor_manager_headers"]
ANY = TEST_USERS["any_headers"]


def test_vendor_create_missing_required_field_rejected(api):
    """PRD section 2.8: "Malformed payloads — missing required fields, type
    mismatches, enum values outside the declared sets — are rejected with
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/vendor_create_missing_required_field_rejected
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    payload = {
        "property_id": prop["id"],
        "declared_purposes": ["ADVERTISING"],
        "tracker_signatures": ["t.com"],
    }
    res = api.create_vendor(payload, VM)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_vendor_approve_after_suspend_rejected(api):
    """PRD section 3.3: "Both actions require the vendor to be in the
    appropriate source state (`ERR_VENDOR_INVALID_TRANSITION` otherwise), and
    `SUSPENDED` is terminal — there is no path back."

    Design: Corner/state_machines/vendor_approve_after_suspend_rejected
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    vend = get_success_data(
        api.create_vendor(create_vendor_payload(prop["id"], legal_name="V"), VM)
    )
    get_success_data(api.approve_vendor(vend["id"], ADMIN))
    get_success_data(api.suspend_vendor(vend["id"], ADMIN))
    res = api.approve_vendor(vend["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_VENDOR_INVALID_TRANSITION)


def test_tag_rule_create_blocked_by_pending_vendor(api):
    """PRD section 3.3: "the vendor must be `APPROVED`
    (`ERR_VENDOR_NOT_APPROVED`)" for tag-rule creation.

    Design: Difficulty/cross_entity_state_dependency/tag_rule_gated_by_vendor_approval
    """
    prop = create_property(name="Gate Site", sale_share_designation="SELLS_AND_SHARES")
    cfg = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ADVERTISING"], config_label="c1"),
            ADMIN,
        )
    )
    vend = get_success_data(
        api.create_vendor(
            create_vendor_payload(prop["id"], legal_name="GateCo",
                                  declared_purposes=["ADVERTISING"],
                                  tracker_signatures=["gate-1.com"]),
            VM,
        )
    )
    assert vend["status"] == "PENDING_REVIEW"
    res = api.create_tag_rule(
        create_tag_rule_payload(vend["id"], cfg["id"], purpose_category="ADVERTISING"), VM
    )
    validate_error(res, ApiErrorId.ERR_VENDOR_NOT_APPROVED)

    # After approval the identical creation succeeds and starts ENABLED.
    get_success_data(api.approve_vendor(vend["id"], ADMIN))
    rule = validate_success(
        api.create_tag_rule(
            create_tag_rule_payload(vend["id"], cfg["id"], purpose_category="ADVERTISING"), VM
        ),
        201,
    )
    assert rule["status"] == "ENABLED"


def test_tag_rule_reenable_blocked_by_suspended_vendor(api):
    """PRD section 3.3: "Suspending a vendor is deliberately blunt: every
    `ENABLED` tag rule of that vendor cascades to `DISABLED`" and "Re-enabling a
    `DISABLED` rule re-checks the vendor's standing: if the vendor has since
    been suspended, the enable fails with `ERR_VENDOR_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/tag_rule_gated_by_vendor_approval
    """
    prop = create_property(name="Gate Site", sale_share_designation="SELLS_AND_SHARES")
    cfg = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ADVERTISING"], config_label="c1"),
            ADMIN,
        )
    )
    vend = create_approved_vendor(
        prop["id"], legal_name="GateCo", declared_purposes=["ADVERTISING"],
        tracker_signatures=["gate-1.com"],
    )
    rule = get_success_data(
        api.create_tag_rule(
            create_tag_rule_payload(vend["id"], cfg["id"], purpose_category="ADVERTISING"), VM
        )
    )
    get_success_data(api.suspend_vendor(vend["id"], ADMIN))
    mid = get_success_data(api.get_tag_rule(rule["id"], ANY))
    assert mid["status"] == "DISABLED", "suspend cascade flips ENABLED rules to DISABLED"
    res = api.update_tag_rule(rule["id"], {"status": "ENABLED"}, VM)
    validate_error(res, ApiErrorId.ERR_VENDOR_NOT_APPROVED)


def test_cross_property_reference_beats_duplicate_tag_rule(api):
    """PRD section 2.8: "The cross-property check outranks the uniqueness
    constraint below: a tag-rule creation that references a foreign-property
    vendor while duplicating an existing (configuration, purpose) pair fails
    with `ERR_CROSS_PROPERTY_REFERENCE`, not `ERR_DUPLICATE_TAG_RULE`."

    Design: Difficulty/priority_pair_validation_conflict/cross_property_reference_beats_duplicate_tag_rule
    """
    p1 = create_property(name="P1", sale_share_designation="SELLS_AND_SHARES")
    p2 = create_property(name="P2", sale_share_designation="SELLS_AND_SHARES")
    v1 = create_approved_vendor(p1["id"], legal_name="V1", declared_purposes=["ANALYTICS"],
                                tracker_signatures=["v1.com"])
    v2 = create_approved_vendor(p2["id"], legal_name="V2", declared_purposes=["ANALYTICS"],
                                tracker_signatures=["v2.com"])
    c1 = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(p1["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ANALYTICS"], config_label="c1"),
            ADMIN,
        )
    )
    get_success_data(
        api.create_tag_rule(create_tag_rule_payload(v1["id"], c1["id"], purpose_category="ANALYTICS"), VM)
    )
    # Foreign-property vendor AND duplicate (config, purpose): both rules fail.
    res = api.create_tag_rule(
        create_tag_rule_payload(v2["id"], c1["id"], purpose_category="ANALYTICS"), VM
    )
    validate_error(res, ApiErrorId.ERR_CROSS_PROPERTY_REFERENCE)


def test_cross_property_rejection_leaves_pair_available_for_duplicate_check(api):
    """PRD section 2.8: "The cross-property check outranks the uniqueness
    constraint below: a tag-rule creation that references a foreign-property
    vendor while duplicating an existing (configuration, purpose) pair fails
    with `ERR_CROSS_PROPERTY_REFERENCE`, not `ERR_DUPLICATE_TAG_RULE`."
    PRD section 3.3: "the pair (`banner_config_id`, `purpose_category`) must be
    unique (`ERR_DUPLICATE_TAG_RULE`)" — the constraint fires once the
    referential check passes.

    Design: Difficulty/priority_pair_validation_conflict/cross_property_reference_beats_duplicate_tag_rule
    """
    p1 = create_property(name="P1", sale_share_designation="SELLS_AND_SHARES")
    p2 = create_property(name="P2", sale_share_designation="SELLS_AND_SHARES")
    v1 = create_approved_vendor(p1["id"], legal_name="V1", declared_purposes=["ANALYTICS"],
                                tracker_signatures=["v1.com"])
    v2 = create_approved_vendor(p2["id"], legal_name="V2", declared_purposes=["ANALYTICS"],
                                tracker_signatures=["v2.com"])
    c1 = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(p1["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ANALYTICS"], config_label="c1"),
            ADMIN,
        )
    )
    rule = get_success_data(
        api.create_tag_rule(create_tag_rule_payload(v1["id"], c1["id"], purpose_category="ANALYTICS"), VM)
    )
    res = api.create_tag_rule(
        create_tag_rule_payload(v2["id"], c1["id"], purpose_category="ANALYTICS"), VM
    )
    err = validate_error(res, ApiErrorId.ERR_CROSS_PROPERTY_REFERENCE)
    assert err["error_id"] != "ERR_DUPLICATE_TAG_RULE"
    # The pre-existing rule is untouched by the rejected foreign-vendor attempt.
    after = get_success_data(api.get_tag_rule(rule["id"], ANY))
    assert after["status"] == "ENABLED"
    # Same-property duplicate now surfaces the uniqueness constraint.
    res2 = api.create_tag_rule(
        create_tag_rule_payload(v1["id"], c1["id"], purpose_category="ANALYTICS"), VM
    )
    validate_error(res2, ApiErrorId.ERR_DUPLICATE_TAG_RULE)


def test_duplicate_tag_rule_rejected(api):
    """PRD section 3.3: "the pair (`banner_config_id`, `purpose_category`) must
    be unique (`ERR_DUPLICATE_TAG_RULE`)."

    Design: Corner/validations/duplicate_tag_rule_rejected
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    cfg = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ANALYTICS"], config_label="c"),
            ADMIN,
        )
    )
    vend = create_approved_vendor(prop["id"], legal_name="V", declared_purposes=["ANALYTICS"],
                                  tracker_signatures=["v.com"])
    get_success_data(
        api.create_tag_rule(create_tag_rule_payload(vend["id"], cfg["id"], purpose_category="ANALYTICS"), VM)
    )
    res = api.create_tag_rule(
        create_tag_rule_payload(vend["id"], cfg["id"], purpose_category="ANALYTICS"), VM
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_TAG_RULE)


def test_tag_rule_enable_after_retire_rejected(api):
    """PRD section 3.3: "`RETIRED` is terminal, and any transition not present
    in the machine is rejected with `ERR_TAG_RULE_INVALID_TRANSITION`."

    Design: Corner/state_machines/tag_rule_enable_after_retire_rejected
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    cfg = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ANALYTICS"], config_label="c"),
            ADMIN,
        )
    )
    vend = create_approved_vendor(prop["id"], legal_name="V", declared_purposes=["ANALYTICS"],
                                  tracker_signatures=["v.com"])
    rule = get_success_data(
        api.create_tag_rule(create_tag_rule_payload(vend["id"], cfg["id"], purpose_category="ANALYTICS"), VM)
    )
    get_success_data(api.update_tag_rule(rule["id"], {"status": "RETIRED"}, VM))
    res = api.update_tag_rule(rule["id"], {"status": "ENABLED"}, VM)
    validate_error(res, ApiErrorId.ERR_TAG_RULE_INVALID_TRANSITION)


def test_vendor_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_VENDOR_NOT_FOUND`, ...)."

    Design: Corner/errors/vendor_get_not_found_returns_404
    """
    res = api.get_vendor(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_VENDOR_NOT_FOUND)


def test_tag_rule_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_TAG_RULE_NOT_FOUND`, ...)."

    Design: Corner/errors/tag_rule_get_not_found_returns_404
    """
    res = api.get_tag_rule(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_TAG_RULE_NOT_FOUND)
