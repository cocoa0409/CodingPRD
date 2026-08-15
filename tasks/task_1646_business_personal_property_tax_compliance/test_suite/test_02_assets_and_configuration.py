"""Asset intake defaults, rendition initial state, and configuration rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_asset,
    assert_date_is,
    assert_rendition,
    client_headers_for,
    create_asset_for,
    create_asset_payload,
    create_class_rule_for,
    create_client_account,
    create_jurisdiction_account,
    create_rendition_payload,
    new_analyst,
    open_rendition,
    validate_error,
    validate_success,
)


def test_asset_create_applies_system_defaults(api):
    """PRD §3.2: "Every imported asset starts with `lifecycle_status` `ACTIVE` and
    `classification_status` `UNCLASSIFIED`, with `taxable_classification` unset
    until classification occurs."

    Design: Corner/entities/asset_create_applies_system_defaults
    """
    client = create_client_account(legal_name="DefCo", contact_email="def@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Def County")

    asset = validate_success(api.create_asset(
        create_asset_payload(client["id"], jurisdiction["id"], asset_tag="D1",
                             category="FURNITURE", acquisition_cost_cents=50000),
        analyst["headers"]), 201)
    assert_asset(asset)
    assert asset["lifecycle_status"] == "ACTIVE"
    assert asset["classification_status"] == "UNCLASSIFIED"
    assert asset.get("taxable_classification") is None
    assert asset.get("disposed_date") is None
    assert asset.get("disposal_proceeds_cents") is None


def test_rendition_created_in_draft_initial_state(api):
    """PRD §3.4: "A new rendition starts in `DRAFT` status with an empty `lines`
    array and a `deadline_date` computed from the jurisdiction's
    `base_deadline_mmdd` combined with the tax year." and "On filing, the system
    evaluates lateness against the current clock date, records `filed_at` and the
    filer's `filed_by_operator_id`"

    Design: Corner/state_machines/rendition_created_in_draft_initial_state
    """
    client = create_client_account(legal_name="InitCo", contact_email="init@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Init County")

    rendition = validate_success(api.create_rendition(
        create_rendition_payload(client["id"], jurisdiction["id"], 2027),
        analyst["headers"]), 201)
    assert_rendition(rendition)
    assert rendition["rendition_status"] == "DRAFT"
    assert rendition["lines"] == []
    assert rendition["total_assessed_value_cents"] == 0
    assert_date_is(rendition["deadline_date"], "2027-04-15", "deadline_date")
    # Lateness fields are only meaningful once a filing exists; accept their
    # zero values or unset, but never a non-zero lateness before any filing.
    assert not rendition.get("is_late_filing")
    assert rendition.get("late_days") in (None, 0)
    assert rendition.get("late_penalty_cents") in (None, 0)
    assert rendition.get("filed_at") is None
    assert rendition.get("filed_by_operator_id") is None


def test_classify_without_class_rule_rejected(api):
    """PRD §3.2: "Two preconditions guard every classification: the asset's
    `lifecycle_status` must be `ACTIVE` (classifying a `DISPOSED` asset is rejected
    with `ERR_INVALID_STATE_TRANSITION`), and a class rule must exist for the
    asset's jurisdiction and category (otherwise `ERR_CLASS_RULE_MISSING`,
    HTTP 422)."

    Design: Corner/validations/classify_without_class_rule_rejected
    """
    client = create_client_account(legal_name="NoRuleCo", contact_email="norule@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="NoRule County")
    create_class_rule_for(jurisdiction["id"], category="MACHINERY",
                          percent_good_vector=[80])
    asset = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                             asset_tag="NR1", category="FURNITURE")

    res = api.classify_asset(asset["id"], {"taxable_classification": "TAXABLE"},
                             analyst["headers"])
    validate_error(res, ApiErrorId.ERR_CLASS_RULE_MISSING, expected_status=422)

    after = validate_success(api.get_asset(asset["id"], analyst["headers"]), 200)
    assert after["classification_status"] == "UNCLASSIFIED"


def test_duplicate_class_rule_rejected(api, firm_admin_headers):
    """PRD §3.1: "at most one rule may exist for a given (jurisdiction, category)
    pair, and a duplicate registration is rejected with
    `ERR_DUPLICATE_CLASS_RULE` (HTTP 409)."

    Design: Corner/validations/duplicate_class_rule_rejected
    """
    jurisdiction = create_jurisdiction_account(county_name="DupRule County")
    create_class_rule_for(jurisdiction["id"], category="MACHINERY",
                          percent_good_vector=[80])
    res = api.create_class_rule(
        {
            "jurisdiction_id": jurisdiction["id"],
            "category": "MACHINERY",
            "is_taxable": False,
            "depreciation_convention": "HALF_YEAR",
            "percent_good_vector": [90],
            "percent_good_floor_pct": 20,
            "de_minimis_line_cents": 0,
        },
        firm_admin_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CLASS_RULE, expected_status=409)


def test_duplicate_rendition_rejected(api):
    """PRD §3.4: "At most one rendition may exist for any (client, jurisdiction,
    tax year) triple; a duplicate is rejected with `ERR_DUPLICATE_RENDITION`
    (HTTP 409)."

    Design: Corner/validations/duplicate_rendition_rejected
    """
    client = create_client_account(legal_name="DupCo", contact_email="dup@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Dup County")
    open_rendition(client["id"], jurisdiction["id"], 2027, analyst["headers"])

    res = api.create_rendition(
        create_rendition_payload(client["id"], jurisdiction["id"], 2027),
        analyst["headers"])
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RENDITION, expected_status=409)


def test_client_cannot_import_assets_forbidden(api):
    """PRD §2.1: "Authorization is then enforced per endpoint: a role outside the
    endpoint's permitted set, or a `Client` whose `X-User-ID` does not own the
    addressed resource through the foreign-key chain described below, is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)." and PRD §4: POST /bpp/assets is
    authorized for "TaxAnalyst" only.

    Design: Corner/rbac/client_cannot_import_assets_forbidden
    """
    client = create_client_account(legal_name="SelfCo", contact_email="self@x.com")
    jurisdiction = create_jurisdiction_account(county_name="Self County")

    res = api.create_asset(
        create_asset_payload(client["id"], jurisdiction["id"], asset_tag="SF1"),
        client_headers_for(client))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
