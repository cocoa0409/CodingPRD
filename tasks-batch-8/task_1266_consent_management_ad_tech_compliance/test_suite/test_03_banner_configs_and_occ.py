"""Banner configuration publication, supersede side effects, and OCC."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_property, create_active_policy,
    create_property_payload, create_jurisdiction_policy_payload,
    create_banner_config_payload, create_vendor_payload, create_tag_rule_payload,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
VM = TEST_USERS["vendor_manager_headers"]
ANY = TEST_USERS["any_headers"]

POLICY_WINDOW = dict(
    banner_regime="OPT_OUT_ALLOWED", min_consent_age=16, retention_days=30,
    gpc_honored=True, effective_from="2026-01-01T00:00:00Z",
    effective_to="2027-01-01T00:00:00Z",
)


def _fresh_version(api, prop_id):
    return get_success_data(api.get_property(prop_id, ANY))["version"]


def test_publish_supersedes_previous_config(api):
    """PRD section 3.2: "On success the publication stamps `published_at`,
    increments the property's `version` by one, and supersedes whichever
    configuration was previously `PUBLISHED` for the same property and
    jurisdiction: the old configuration moves to `SUPERSEDED` and every
    `ENABLED` tag rule bound to it drops to `DISABLED`."

    Design: Corner/state_machines/publish_supersedes_previous_config
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    create_active_policy(prop["id"], jurisdiction_code="US-CA", **POLICY_WINDOW)
    cfg_a = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ADVERTISING"], config_label="A"),
            ADMIN,
        )
    )
    get_success_data(
        api.publish_banner_config(
            cfg_a["id"], {"expected_property_version": _fresh_version(api, prop["id"])}, ADMIN
        )
    )
    vend = get_success_data(
        api.create_vendor(create_vendor_payload(prop["id"], legal_name="V"), VM)
    )
    get_success_data(api.approve_vendor(vend["id"], ADMIN))
    rule = get_success_data(
        api.create_tag_rule(
            create_tag_rule_payload(vend["id"], cfg_a["id"], purpose_category="ADVERTISING"), VM
        )
    )
    cfg_b = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ADVERTISING", "SALE_SHARE"],
                                         config_label="B"),
            ADMIN,
        )
    )
    pub_b = validate_success(
        api.publish_banner_config(
            cfg_b["id"], {"expected_property_version": _fresh_version(api, prop["id"])}, ADMIN
        ),
        200,
    )
    assert pub_b["status"] == "PUBLISHED"
    cfg_a_after = get_success_data(api.get_banner_config(cfg_a["id"], ANY))
    assert cfg_a_after["status"] == "SUPERSEDED"
    rule_after = get_success_data(api.get_tag_rule(rule["id"], ANY))
    assert rule_after["status"] == "DISABLED", "supersede cascade disables ENABLED tag rules"


def test_banner_archive_then_publish_rejected(api):
    """PRD section 3.2: "Archival applies only to `DRAFT` configurations;
    archiving a published one, or publishing an archived one, is rejected with
    `ERR_BANNER_CONFIG_NOT_PUBLISHABLE`."

    Design: Corner/state_machines/banner_archive_then_publish_rejected
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_IN_REQUIRED",
                         min_consent_age=16, retention_days=30, gpc_honored=False,
                         effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z")
    cfg = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ANALYTICS"], config_label="c"),
            ADMIN,
        )
    )
    get_success_data(api.archive_banner_config(cfg["id"], ADMIN))
    res = api.publish_banner_config(
        cfg["id"], {"expected_property_version": _fresh_version(api, prop["id"])}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_BANNER_CONFIG_NOT_PUBLISHABLE)


def test_banner_publish_occ_stale_then_fresh(api):
    """PRD section 2.7: "If the property's version has advanced since — whether
    through another publication, a consent cascade, or a posture flip — the
    request is rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP 412). A
    successful publication increments the property's `version` by exactly one."

    Design: Corner/cross_cutting_layers/banner_publish_occ_stale_then_fresh
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    pv = prop["version"]
    create_active_policy(prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_IN_REQUIRED",
                         min_consent_age=16, retention_days=30, gpc_honored=False,
                         effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z")
    cfg_a = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ANALYTICS"], config_label="A"),
            ADMIN,
        )
    )
    cfg_b = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ANALYTICS"], config_label="B"),
            ADMIN,
        )
    )
    pub_a = validate_success(
        api.publish_banner_config(cfg_a["id"], {"expected_property_version": pv}, ADMIN), 200
    )
    assert pub_a["status"] == "PUBLISHED", "fresh version accepted"

    stale = api.publish_banner_config(cfg_b["id"], {"expected_property_version": pv}, ADMIN)
    validate_error(stale, ApiErrorId.ERR_STALE_PROPERTY_VERSION)

    pv2 = get_success_data(api.get_property(prop["id"], ANY))["version"]
    assert pv2 == pv + 1, "publish bumped version by exactly 1"
    pub_b = validate_success(
        api.publish_banner_config(cfg_b["id"], {"expected_property_version": pv2}, ADMIN), 200
    )
    assert pub_b["status"] == "PUBLISHED", "re-read version and retry succeeds"


def test_publish_rejected_without_active_policy(api):
    """PRD section 3.2: "publication requires ... an `ACTIVE` policy to exist
    for the configuration's jurisdiction (`ERR_NO_ACTIVE_POLICY`)".

    Design: Difficulty/cross_entity_state_dependency/banner_publish_gated_by_active_policy
    """
    prop = create_property(name="PubGate Site", sale_share_designation="NO_SALE_NO_SHARE")
    pv = prop["version"]
    # Only a DRAFT policy exists for US-CA (never activated).
    get_success_data(
        api.create_jurisdiction_policy(
            create_jurisdiction_policy_payload(
                prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_IN_REQUIRED",
                min_consent_age=16, retention_days=30, gpc_honored=False,
                effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
            ),
            ADMIN,
        )
    )
    cfg = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                         categories_shown=["ANALYTICS"], config_label="c1"),
            ADMIN,
        )
    )
    res = api.publish_banner_config(cfg["id"], {"expected_property_version": pv}, ADMIN)
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_POLICY)


def test_publish_rejected_outside_coverage_window(api):
    """PRD section 3.2: "publication requires ... the logical clock to fall
    inside that policy's coverage window (`ERR_POLICY_OUTSIDE_COVERAGE_WINDOW`)".

    Design: Difficulty/cross_entity_state_dependency/banner_publish_gated_by_active_policy
    """
    prop = create_property(name="PubGate Site", sale_share_designation="NO_SALE_NO_SHARE")
    pv = prop["version"]
    # ACTIVE EU-GDPR policy whose window ended before the default clock 2026-05-01.
    create_active_policy(
        prop["id"], jurisdiction_code="EU-GDPR", banner_regime="OPT_IN_REQUIRED",
        min_consent_age=16, retention_days=30, gpc_honored=False,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-03-01T00:00:00Z",
    )
    cfg = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(prop["id"], jurisdiction_code="EU-GDPR",
                                         categories_shown=["ANALYTICS"], config_label="c2"),
            ADMIN,
        )
    )
    res = api.publish_banner_config(cfg["id"], {"expected_property_version": pv}, ADMIN)
    validate_error(res, ApiErrorId.ERR_POLICY_OUTSIDE_COVERAGE_WINDOW)


def test_banner_config_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_BANNER_CONFIG_NOT_FOUND`, ...)."

    Design: Corner/errors/banner_config_get_not_found_returns_404
    """
    res = api.get_banner_config(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_BANNER_CONFIG_NOT_FOUND)
