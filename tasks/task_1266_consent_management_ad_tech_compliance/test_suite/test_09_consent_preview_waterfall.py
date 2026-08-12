"""Effective-consent resolution waterfall via the non-persisting preview read."""
from test_helpers import (
    validate_success, get_success_data,
    create_property, create_active_policy, create_adult_visitor,
    gpc_signal_payload,
    make_visitor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
ANY = TEST_USERS["any_headers"]


def _preview(api, visitor_id, purpose):
    return get_success_data(
        api.get_consent_preview(visitor_id, ANY, params={"purpose_category": purpose})
    )["decision"]


def _waterfall_site(api):
    prop = create_property(name="Preview Site", sale_share_designation="SELLS_AND_SHARES")
    create_active_policy(
        prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_IN_REQUIRED",
        min_consent_age=16, retention_days=30, gpc_honored=True,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    adult = create_adult_visitor(
        prop["id"], birthdate="2000-01-01T00:00:00Z",
        external_ref="adult@x.com", jurisdiction_code="US-CA",
    )
    from test_helpers import create_visitor
    child = create_visitor(prop["id"], external_ref="child@x.com", jurisdiction_code="US-CA")
    get_success_data(
        api.attest_age(child["id"], {"attested_birthdate": "2015-06-01T00:00:00Z"},
                       make_visitor_headers(child["id"]))
    )
    gpc = create_visitor(prop["id"], external_ref="gpc@x.com", jurisdiction_code="US-CA")
    get_success_data(
        api.attest_age(gpc["id"], {"attested_birthdate": "1990-01-01T00:00:00Z"},
                       make_visitor_headers(gpc["id"]))
    )
    get_success_data(
        api.create_gpc_signal(gpc["id"], gpc_signal_payload("ON"), make_visitor_headers(gpc["id"]))
    )
    return prop, adult, child, gpc


def test_waterfall_child_and_necessary_branches(api):
    """PRD section 3.5: "First, a `CHILD` visitor asking for anything other than
    `NECESSARY` yields `BLOCKED_CHILD`. Second, `NECESSARY` always yields
    `ALWAYS_GRANTED`."

    Design: Difficulty/combinatorial_formula/consent_resolution_waterfall_branches
    """
    prop, adult, child, gpc = _waterfall_site(api)
    assert _preview(api, child["id"], "ADVERTISING") == "BLOCKED_CHILD", (
        "CHILD + non-NECESSARY short-circuits everything"
    )
    assert _preview(api, adult["id"], "NECESSARY") == "ALWAYS_GRANTED", (
        "NECESSARY bypasses the regime"
    )


def test_waterfall_gpc_and_regime_default_branches(api):
    """PRD section 3.5: "Third, for `SALE_SHARE` under a `gpc_honored` policy
    with the signal `ON`, the signal wins unless the visitor re-granted after
    the signal arrived: when the record is `GRANTED` and its `last_changed_at`
    is strictly later than `gpc_updated_at`, the decision is `EXPLICIT_GRANT`;
    otherwise it is `FORCED_OPT_OUT`. ... Finally the regime default applies:
    `OPT_IN_REQUIRED` yields `DENIED_BY_DEFAULT`, while `OPT_OUT_ALLOWED` and
    `NOTICE_ONLY` yield `GRANTED_BY_DEFAULT`."

    Design: Difficulty/combinatorial_formula/consent_resolution_waterfall_branches
    """
    prop, adult, child, gpc = _waterfall_site(api)
    assert _preview(api, gpc["id"], "SALE_SHARE") == "FORCED_OPT_OUT", (
        "GPC ON + gpc_honored + SALE_SHARE, no later explicit grant"
    )
    assert _preview(api, gpc["id"], "ANALYTICS") == "DENIED_BY_DEFAULT", (
        "GPC does not touch ANALYTICS; falls to OPT_IN_REQUIRED default"
    )
    assert _preview(api, adult["id"], "ANALYTICS") == "DENIED_BY_DEFAULT", (
        "OPT_IN_REQUIRED with no record"
    )
