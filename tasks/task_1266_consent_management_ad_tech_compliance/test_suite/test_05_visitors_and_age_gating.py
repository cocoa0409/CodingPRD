"""Visitor registration defaults, age gating boundary, and ownership checks."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_visitor_profile,
    create_property, create_active_policy,
    create_visitor_payload, age_attestation_payload, create_consent_record_payload,
    make_visitor_headers,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
ANY = TEST_USERS["any_headers"]


def _site_with_policy(api):
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    create_active_policy(
        prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_OUT_ALLOWED",
        min_consent_age=16, retention_days=30, gpc_honored=True,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    return prop


def test_visitor_create_defaults_unverified(api):
    """PRD section 3.4: "A fresh profile carries `age_status` `UNVERIFIED`,
    `gpc_effective` `UNSET`, and `sale_share_opted_out` false."

    Design: Corner/entities/visitor_create_defaults_unverified
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    vis = validate_success(
        api.create_visitor(
            create_visitor_payload(prop["id"], external_ref="d@x.com", jurisdiction_code="US-CA"),
            ANON,
        ),
        201,
    )
    assert_visitor_profile(vis)
    assert vis["age_status"] == "UNVERIFIED"
    assert vis["gpc_effective"] == "UNSET"
    assert vis["sale_share_opted_out"] is False


def test_visitor_birthdate_at_registration_stays_unverified(api):
    """PRD section 3.4: "An `attested_birthdate` may be supplied at
    registration, but doing so only stores the value — the age gate is not
    evaluated until the visitor explicitly completes the age-attestation step."

    Design: Corner/entities/visitor_birthdate_at_registration_stays_unverified
    """
    prop = _site_with_policy(api)
    vis = validate_success(
        api.create_visitor(
            create_visitor_payload(
                prop["id"], external_ref="bd@x.com", jurisdiction_code="US-CA",
                attested_birthdate="1990-01-01T00:00:00Z",
            ),
            ANON,
        ),
        201,
    )
    assert vis["age_status"] == "UNVERIFIED", (
        "birthdate stored at registration but age gate not yet evaluated"
    )


def test_age_gate_exact_birthday_is_adult(api):
    """PRD section 3.4: "the visitor is `ADULT` when the date that is exactly
    `min_consent_age` years after the attested birthdate is on or before the
    current logical-clock date — a visitor whose qualifying birthday is today
    passes — and `CHILD` otherwise."

    Design: Difficulty/boundary_precision_check/age_gate_exact_min_age_birthday
    """
    prop = _site_with_policy(api)
    get_success_data(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    vis = get_success_data(
        api.create_visitor(
            create_visitor_payload(prop["id"], external_ref="exact@x.com", jurisdiction_code="US-CA"),
            ANON,
        )
    )
    res = api.attest_age(
        vis["id"], age_attestation_payload("2010-05-01T00:00:00Z"),
        make_visitor_headers(vis["id"]),
    )
    attested = validate_success(res, 200)
    assert attested["age_status"] == "ADULT", (
        "birthdate + 16 years == clock date exactly; on-or-before boundary qualifies"
    )


def test_age_gate_one_day_short_is_child(api):
    """PRD section 3.4: "the visitor is `ADULT` when the date that is exactly
    `min_consent_age` years after the attested birthdate is on or before the
    current logical-clock date — a visitor whose qualifying birthday is today
    passes — and `CHILD` otherwise."

    Design: Difficulty/boundary_precision_check/age_gate_exact_min_age_birthday
    """
    prop = _site_with_policy(api)
    get_success_data(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    vis = get_success_data(
        api.create_visitor(
            create_visitor_payload(prop["id"], external_ref="minus1@x.com", jurisdiction_code="US-CA"),
            ANON,
        )
    )
    res = api.attest_age(
        vis["id"], age_attestation_payload("2010-05-02T00:00:00Z"),
        make_visitor_headers(vis["id"]),
    )
    attested = validate_success(res, 200)
    assert attested["age_status"] == "CHILD", "one day short of the 16th birthday"


def test_visitor_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_VISITOR_NOT_FOUND`, ...)."

    Design: Corner/errors/visitor_get_not_found_returns_404
    """
    res = api.get_visitor(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_VISITOR_NOT_FOUND)


def test_visitor_cannot_act_on_other_visitor(api):
    """PRD section 2.1: "every visitor-scoped mutation (age attestation, GPC
    signals, consent records, do-not-sell requests, withdrawals and re-grants)
    compares the target visitor's `id` to `X-User-ID`, and a mismatch is
    rejected with `ERR_FORBIDDEN_OWNERSHIP` (403)."

    Design: Corner/rbac/visitor_cannot_act_on_other_visitor
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(
        prop["id"], jurisdiction_code="EU-GDPR", banner_regime="OPT_IN_REQUIRED",
        min_consent_age=16, retention_days=30, gpc_honored=False,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    vis_a = get_success_data(
        api.create_visitor(
            create_visitor_payload(prop["id"], external_ref="a@x.com", jurisdiction_code="EU-GDPR"),
            ANON,
        )
    )
    vis_b = get_success_data(
        api.create_visitor(
            create_visitor_payload(prop["id"], external_ref="b@x.com", jurisdiction_code="EU-GDPR"),
            ANON,
        )
    )
    res = api.create_consent_record(
        vis_b["id"], create_consent_record_payload("ANALYTICS"),
        make_visitor_headers(vis_a["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
