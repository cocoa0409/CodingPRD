"""Consent grant gates: snapshots, age safety, uniqueness, coverage windows."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_consent_record,
    create_property, create_active_policy, create_visitor, create_adult_visitor,
    create_visitor_payload, age_attestation_payload, create_consent_record_payload,
    make_visitor_headers,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
ANY = TEST_USERS["any_headers"]

GDPR = dict(
    jurisdiction_code="EU-GDPR", banner_regime="OPT_IN_REQUIRED",
    min_consent_age=16, retention_days=30, gpc_honored=False,
    effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
)


def test_consent_create_snapshots_policy_and_config(api):
    """PRD section 3.5: "A consent record is born `GRANTED`, stamped with the
    currently `PUBLISHED` banner configuration for the visitor's jurisdiction in
    `banner_config_id` (null when none is published), the policy snapshot, and
    `source_of_decision` `EXPLICIT_GRANT`."
    PRD section 2.10: "Every transition into `GRANTED` snapshots the governing
    policy's `retention_days` into `policy_snapshot_retention_days`".

    Design: Corner/entities/consent_create_snapshots_policy_and_config
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(prop["id"], external_ref="s@x.com", jurisdiction_code="EU-GDPR")
    rec = validate_success(
        api.create_consent_record(
            vis["id"], create_consent_record_payload("ANALYTICS"),
            make_visitor_headers(vis["id"]),
        ),
        201,
    )
    assert_consent_record(rec)
    assert rec["policy_snapshot_retention_days"] == 30
    assert rec["banner_config_id"] is None, "no PUBLISHED config for the jurisdiction"
    assert rec["source_of_decision"] == "EXPLICIT_GRANT"
    assert rec["status"] == "GRANTED"


def test_consent_without_attestation_returns_age_unverified(api):
    """PRD section 2.8: "Safety — age verification — consent grant or re-grant
    requires a completed age attestation (`ERR_AGE_UNVERIFIED`)."

    Design: Corner/validations/consent_without_attestation_returns_age_unverified
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], **GDPR)
    vis = create_visitor(prop["id"], external_ref="u@x.com", jurisdiction_code="EU-GDPR")
    res = api.create_consent_record(
        vis["id"], create_consent_record_payload("ANALYTICS"),
        make_visitor_headers(vis["id"]),
    )
    validate_error(res, ApiErrorId.ERR_AGE_UNVERIFIED)


def test_child_consent_blocked_directly(api):
    """PRD section 3.4: "A `CHILD` visitor may grant only the `NECESSARY`
    purpose; any other purpose is refused with `ERR_CHILD_CONSENT_FORBIDDEN`."

    Design: Corner/validations/child_consent_blocked_directly
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    create_active_policy(
        prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_OUT_ALLOWED",
        min_consent_age=16, retention_days=30, gpc_honored=True,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    vis = create_visitor(prop["id"], external_ref="k@x.com", jurisdiction_code="US-CA")
    child = get_success_data(
        api.attest_age(vis["id"], age_attestation_payload("2015-06-01T00:00:00Z"),
                       make_visitor_headers(vis["id"]))
    )
    assert child["age_status"] == "CHILD"

    res = api.create_consent_record(
        vis["id"], create_consent_record_payload("ADVERTISING"),
        make_visitor_headers(vis["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CHILD_CONSENT_FORBIDDEN)

    nec = validate_success(
        api.create_consent_record(
            vis["id"], create_consent_record_payload("NECESSARY"),
            make_visitor_headers(vis["id"]),
        ),
        201,
    )
    assert nec["status"] == "GRANTED", "NECESSARY is exempt from the child restriction"


def test_duplicate_consent_purpose_rejected(api):
    """PRD section 3.5: "a visitor may hold only one record per purpose in
    `GRANTED` or `WITHDRAWN`, so a duplicate grant is rejected with
    `ERR_DUPLICATE_CONSENT_PURPOSE`."

    Design: Corner/validations/duplicate_consent_purpose_rejected
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(prop["id"], external_ref="d@x.com", jurisdiction_code="EU-GDPR")
    vh = make_visitor_headers(vis["id"])
    get_success_data(api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh))
    res = api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CONSENT_PURPOSE)


def test_expired_record_allows_fresh_create(api):
    """PRD section 3.5: "Once a record has reached `EXPIRED`, however, the gate
    releases and a fresh grant for the same purpose creates a new record."

    Design: Corner/validations/expired_record_allows_fresh_create
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(prop["id"], external_ref="x@x.com", jurisdiction_code="EU-GDPR")
    vh = make_visitor_headers(vis["id"])
    rec1 = get_success_data(
        api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh)
    )
    # Granted at default clock 2026-05-01 with retention 30 -> pinned 2026-05-31.
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN))
    stale = get_success_data(api.get_consent_record(rec1["id"], ANY))
    assert stale["status"] == "EXPIRED"

    rec2 = validate_success(
        api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh), 201
    )
    assert rec2["status"] == "GRANTED"
    assert rec2["id"] != rec1["id"]


def test_consent_after_policy_window_rejected(api):
    """PRD section 2.8: "Temporal — coverage window — the logical clock must
    fall inside the active policy's coverage window
    (`ERR_POLICY_OUTSIDE_COVERAGE_WINDOW`)."

    Design: Corner/validations/consent_after_policy_window_rejected
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(
        prop["id"], jurisdiction_code="EU-GDPR", banner_regime="OPT_IN_REQUIRED",
        min_consent_age=16, retention_days=30, gpc_honored=False,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-03-01T00:00:00Z",
    )
    # Default clock is 2026-05-01, past the window end.
    vis = create_adult_visitor(prop["id"], external_ref="t@x.com", jurisdiction_code="EU-GDPR")
    res = api.create_consent_record(
        vis["id"], create_consent_record_payload("ANALYTICS"),
        make_visitor_headers(vis["id"]),
    )
    validate_error(res, ApiErrorId.ERR_POLICY_OUTSIDE_COVERAGE_WINDOW)


def test_consent_after_policy_retire_no_active_policy(api):
    """PRD section 3.1: "Retiring a policy does not disturb consent records
    already granted under it (their pinned retention horizon survives), but with
    no `ACTIVE` policy left for the jurisdiction, new consent grants fail with
    `ERR_NO_ACTIVE_POLICY`."

    Design: Corner/validations/consent_after_policy_retire_no_active_policy
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    pol = create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(prop["id"], external_ref="r@x.com", jurisdiction_code="EU-GDPR")
    vh = make_visitor_headers(vis["id"])
    rec = get_success_data(
        api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh)
    )
    get_success_data(api.update_jurisdiction_policy(pol["id"], {"status": "RETIRED"}, ADMIN))

    res = api.create_consent_record(vis["id"], create_consent_record_payload("ADVERTISING"), vh)
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_POLICY)

    after = get_success_data(api.get_consent_record(rec["id"], ANY))
    assert after["status"] == "GRANTED", "retirement does not retroactively kill records"


def test_consent_withdraw_twice_rejected(api):
    """PRD section 3.5: "Attempting a withdrawal on an already-withdrawn record,
    or a re-grant on a granted one, fails with `ERR_CONSENT_INVALID_TRANSITION`."

    Design: Corner/state_machines/consent_withdraw_twice_rejected
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(prop["id"], **GDPR)
    vis = create_adult_visitor(prop["id"], external_ref="w@x.com", jurisdiction_code="EU-GDPR")
    vh = make_visitor_headers(vis["id"])
    rec = get_success_data(
        api.create_consent_record(vis["id"], create_consent_record_payload("ANALYTICS"), vh)
    )
    get_success_data(api.withdraw_consent_record(rec["id"], vh))
    res = api.withdraw_consent_record(rec["id"], vh)
    validate_error(res, ApiErrorId.ERR_CONSENT_INVALID_TRANSITION)


def test_consent_record_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_CONSENT_RECORD_NOT_FOUND`, ...)."

    Design: Corner/errors/consent_record_get_not_found_returns_404
    """
    res = api.get_consent_record(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_CONSENT_RECORD_NOT_FOUND)
