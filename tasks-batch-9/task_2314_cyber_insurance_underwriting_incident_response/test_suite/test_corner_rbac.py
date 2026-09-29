"""Role authorisation: the five declared roles, the endpoints each may reach,
the account binding of the `Insured` role and the proof-acceptance segregation
of duties.

Every test builds its own world through the public API; the harness restarts
the server with an empty database before each test.
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ACTUARY_HEADERS,
    ADJUSTER_2_HEADERS,
    ADJUSTER_HEADERS,
    PANEL_ADMIN_HEADERS,
    UNDERWRITER_HEADERS,
    ErrorId,
    constants as C,
    factories as F,
    fixtures as X,
    make_insured_headers,
)
from test_helpers.assertions import assert_money


# --------------------------------------------------------------------------
# Local helpers
# --------------------------------------------------------------------------
def _instant(value):
    """Parse an ISO 8601 UTC timestamp so two spellings of one instant compare
    equal regardless of fractional-digit formatting."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _email_filtering_partial():
    """A single scan finding that observes EMAIL_FILTERING at PARTIAL."""
    return [F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")]


def _quotable_application(api):
    """Aurora Health carried to UNDERWRITING with a COMPLETED scan.

    Catalog -> account -> application -> five attestations -> submit -> scan
    ordered and completed with EMAIL_FILTERING observed at PARTIAL, leaving a
    verified score of 87.50 and a bindable premium of 28,458.00 waiting to be
    written by the quote.
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    catalog = X.seed_catalog(api)
    account = X.create_account(api)
    application = X.create_application(api, account["id"])
    X.attest_controls(api, application["id"], C.ATTEST_95)
    X.submit_application(api, application["id"])
    scan = X.order_scan(api, application["id"])
    X.complete_scan(api, scan["id"], findings=_email_filtering_partial())
    return {
        "catalog": catalog,
        "account": account,
        "application": X.read_application(api, application["id"]),
        "scan": scan,
    }


def _bound_aurora_policy(api):
    """Aurora Health taken from the empty database to an INFORCE policy with a
    five-section tower on a 5,000,000 aggregate and a 250,000 retention."""
    return X.bound_policy(api, findings=_email_filtering_partial())


def _forensics_vendor(api):
    """Ironclad Forensics empanelled at 500.00 an hour, tier 1, version 1."""
    return X.create_vendor(
        api,
        vendor_name="Ironclad Forensics",
        vendor_type="FORENSICS",
        pre_approved_hourly_rate_usd=500,
        per_record_notification_rate_usd=0,
        specialty_sectors=["HEALTHCARE", "FINANCIAL"],
        tier=1,
        capacity_concurrent_engagements=2,
    )


# --------------------------------------------------------------------------
# Role denials
# --------------------------------------------------------------------------
def test_claims_adjuster_cannot_quote_an_application(api):
    """PRD §4: "| POST | `/cyber/applications/{application_id}/quote` | Issue or supersede a bindable quote priced off the verified score. Guarded by OCC rule quote-issue-stale-application. | `Underwriter` |"
    PRD §2.1: "A value of `X-User-Role` that is not one of these five, or that is not among the roles authorised for the endpoint being called (see §4), is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.10: "The practical consequence worth internalising: a request that is both unauthorised and malformed reports the authorisation failure, and a request that would both breach a sublimit and be filed by the wrong role reports the role failure."

    Design: Corner/rbac/claims_adjuster_cannot_quote_an_application_returns_403
    """
    chain = _quotable_application(api)
    application_id = chain["application"]["id"]
    version_before = chain["application"]["version"]

    denied = api.quote_application(
        application_id,
        {"expected_application_version": version_before},
        ADJUSTER_HEADERS,
    )
    validate_error(denied, ErrorId.UNAUTHORIZED)

    unchanged = X.read_application(api, application_id)
    assert unchanged["status"] == "UNDERWRITING", (
        f"a refused quote must leave the application in UNDERWRITING, got {unchanged['status']}"
    )
    assert unchanged.get("premium_usd") is None, (
        f"premium_usd must stay null after a refused quote, got {unchanged.get('premium_usd')}"
    )
    assert unchanged["version"] == version_before, (
        f"version must not move: expected {version_before}, got {unchanged['version']}"
    )

    allowed = api.quote_application(
        application_id,
        {"expected_application_version": version_before},
        UNDERWRITER_HEADERS,
    )
    quoted = validate_success(allowed, expected_status=200)
    assert quoted["status"] == "QUOTED", (
        f"the identical call as an Underwriter must succeed, got status {quoted['status']}"
    )
    assert_money(quoted["premium_usd"], 28458.00, "premium_usd")


def test_underwriter_cannot_confirm_coverage_on_a_claim(api):
    """PRD §4: "| POST | `/cyber/incident-claims/{claim_id}/confirm-coverage` | Confirm which tower sections respond and set the case reserve. Blocked while the policy's warranty_status is LAPSED. | `ClaimsAdjuster` |"
    PRD §2.1: "A value of `X-User-Role` that is not one of these five, or that is not among the roles authorised for the endpoint being called (see §4), is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.6: "The claim opens in `NOTIFIED` with `reserved_amount_usd`, `retention_absorbed_usd`, `paid_total_usd`, and `unallocated_loss_usd` all at 0.00 and `proof_review_round` at 0."

    Design: Corner/rbac/underwriter_cannot_confirm_coverage_returns_403
    """
    chain = _bound_aurora_policy(api)
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.notify_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
    )
    triaged = X.triage_claim(api, claim["id"])
    assert triaged["status"] == "TRIAGE", (
        f"claim should be in TRIAGE before the trigger, got {triaged['status']}"
    )

    payload = {
        "covered_section_keys": ["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        "initial_reserve_usd": 300000,
    }
    denied = api.confirm_coverage(claim["id"], payload, UNDERWRITER_HEADERS)
    validate_error(denied, ErrorId.UNAUTHORIZED)

    unchanged = X.read_claim(api, claim["id"])
    assert unchanged["status"] == "TRIAGE", (
        f"a refused confirmation must leave the claim in TRIAGE, got {unchanged['status']}"
    )
    assert_money(unchanged["reserved_amount_usd"], 0.00, "reserved_amount_usd")
    assert unchanged["version"] == triaged["version"], (
        f"version must not move: expected {triaged['version']}, got {unchanged['version']}"
    )

    allowed = api.confirm_coverage(claim["id"], payload, ADJUSTER_HEADERS)
    confirmed = validate_success(allowed, expected_status=200)
    assert confirmed["status"] == "COVERAGE_CONFIRMED", (
        f"the identical call as a ClaimsAdjuster must succeed, got {confirmed['status']}"
    )
    assert_money(confirmed["reserved_amount_usd"], 300000.00, "reserved_amount_usd")


def test_panel_admin_cannot_draft_a_systemic_scenario(api):
    """PRD §4: "| POST | `/cyber/systemic-scenarios` | Draft a systemic dependency-failure scenario with an assumed outage, an impact footprint and the portfolio capacity held for it. | `PortfolioActuary` |"
    PRD §2.1: "A value of `X-User-Role` that is not one of these five, or that is not among the roles authorised for the endpoint being called (see §4), is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/rbac/panel_admin_cannot_create_a_systemic_scenario_returns_403
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    _forensics_vendor(api)

    payload = {
        "dependency_key": "CSP_ALPHA",
        "assumed_outage_hours": 240,
        "footprint_pct": 0.5,
        "portfolio_capacity_usd": 100000,
        "qualifying_definitions": ["NAMED_PLUS_SUPPLY_CHAIN"],
    }
    denied = api.create_systemic_scenario(payload, PANEL_ADMIN_HEADERS)
    validate_error(denied, ErrorId.UNAUTHORIZED)

    _rows, meta = validate_paginated(
        api.list_systemic_scenarios(ACTUARY_HEADERS, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, (
        f"a refused draft must create nothing, got total_count {meta['total_count']}"
    )

    allowed = api.create_systemic_scenario(payload, ACTUARY_HEADERS)
    scenario = validate_success(allowed, expected_status=201)
    assert scenario["dependency_key"] == "CSP_ALPHA", (
        f"the identical call as a PortfolioActuary must succeed, got {scenario}"
    )


def test_claims_adjuster_cannot_amend_a_panel_vendor(api):
    """PRD §4: "| PATCH | `/cyber/panel-vendors/{vendor_id}` | Amend panel standing, pre-approved rates, tier, sectors or capacity. Never rewrites rates already pinned on an existing VendorEngagement. | `PanelAdmin` |"
    PRD §2.1: "A value of `X-User-Role` that is not one of these five, or that is not among the roles authorised for the endpoint being called (see §4), is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp refreshed on every change to the row, and `version` is an integer that starts at 1 and increments by exactly 1 on every mutation."

    Design: Corner/rbac/claims_adjuster_cannot_patch_a_panel_vendor_returns_403
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    vendor = _forensics_vendor(api)
    assert vendor["version"] == 1, f"a new panel firm starts at version 1, got {vendor['version']}"

    denied = api.update_panel_vendor(
        vendor["id"], {"pre_approved_hourly_rate_usd": 900}, ADJUSTER_HEADERS
    )
    validate_error(denied, ErrorId.UNAUTHORIZED)

    unchanged = validate_success(
        api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS), expected_status=200
    )
    assert_money(unchanged["pre_approved_hourly_rate_usd"], 500.00, "pre_approved_hourly_rate_usd")
    assert unchanged["version"] == 1, (
        f"a refused amendment must not increment version, got {unchanged['version']}"
    )

    allowed = api.update_panel_vendor(
        vendor["id"], {"pre_approved_hourly_rate_usd": 900}, PANEL_ADMIN_HEADERS
    )
    amended = validate_success(allowed, expected_status=200)
    assert_money(amended["pre_approved_hourly_rate_usd"], 900.00, "pre_approved_hourly_rate_usd")
    assert amended["version"] == 2, (
        f"the identical call as a PanelAdmin must succeed and reach version 2, got {amended['version']}"
    )


def test_insured_cannot_verify_its_own_remediation(api):
    """PRD §4: "| POST | `/cyber/renewal-assessments/{assessment_id}/verify-remediation` | Verify the submitted evidence. Full coverage of required_control_keys reaches CONDITIONS_MET; a partial pass returns to CONDITIONS_ISSUED until MAX_VERIFICATION_ROUNDS is spent, after which the policy is non-renewed. | `Underwriter` |"
    PRD §2.1: "A value of `X-User-Role` that is not one of these five, or that is not among the roles authorised for the endpoint being called (see §4), is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.10: "2. **Role authorisation** — `X-User-Role` is one of the five declared roles and is permitted for this endpoint; otherwise `ERR_UNAUTHORIZED` (403). Raised before any path identifier is resolved."
    PRD §2.10: "4. **Account scope** — an `Insured` caller may only touch rows owned by its own account; otherwise `ERR_ACCOUNT_SCOPE_VIOLATION` (403). Deliberately after existence, so a foreign row that exists is 403."
    PRD §3.9: "Either way `verification_round` starts at 0."

    Design: Corner/rbac/insured_cannot_verify_its_own_remediation_returns_403
    """
    chain = _bound_aurora_policy(api)
    insured_headers = make_insured_headers(chain["account"]["id"])
    X.set_clock(api, "2027-05-05T00:00:00Z")
    assessment = X.open_renewal_assessment(
        api,
        chain["policy"]["id"],
        required_control_keys=["EMAIL_FILTERING"],
        remediation_due_at="2027-06-01T00:00:00Z",
    )
    submitted = validate_success(
        api.submit_remediation(
            assessment["id"], {"submitted_control_keys": ["EMAIL_FILTERING"]}, insured_headers
        ),
        expected_status=200,
    )
    assert submitted["status"] == "REMEDIATION_SUBMITTED", (
        f"the insured's own submission should be accepted, got {submitted['status']}"
    )
    verified_before = submitted["verified_control_keys"]

    denied = api.verify_remediation(
        assessment["id"], {"verified_control_keys": ["EMAIL_FILTERING"]}, insured_headers
    )
    # The role check at priority 2 fires before the account-scope check at
    # priority 4, so the account-owning insured still sees the role failure.
    validate_error(denied, ErrorId.UNAUTHORIZED)

    unchanged = validate_success(
        api.get_renewal_assessment(assessment["id"], UNDERWRITER_HEADERS), expected_status=200
    )
    assert unchanged["status"] == "REMEDIATION_SUBMITTED", (
        f"a refused verification must leave the assessment in REMEDIATION_SUBMITTED, got {unchanged['status']}"
    )
    assert unchanged["verified_control_keys"] == verified_before, (
        "verified_control_keys must not move: "
        f"{verified_before} became {unchanged['verified_control_keys']}"
    )
    assert unchanged["verification_round"] == 0, (
        f"verification_round must stay at 0, got {unchanged['verification_round']}"
    )
    assert unchanged["version"] == submitted["version"], (
        f"version must not move: expected {submitted['version']}, got {unchanged['version']}"
    )


def test_panel_admin_cannot_read_a_policy(api):
    """PRD §4: "| GET | `/cyber/policies/{policy_id}` | Read one policy with both state dimensions, remaining aggregate and warranty posture. | `Underwriter`, `ClaimsAdjuster`, `PortfolioActuary`, `Insured` |"
    PRD §2.1: "A value of `X-User-Role` that is not one of these five, or that is not among the roles authorised for the endpoint being called (see §4), is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.7: "The panel register is readable by all five roles, ordered `tier` ascending, then `pre_approved_hourly_rate_usd` ascending, then `created_at` ascending — the very order the selector applies — and filterable by `vendor_type` and `status`; individual firms are readable by `vendor_id` including the live `active_engagement_count`."

    Design: Corner/rbac/panel_admin_cannot_read_a_policy_returns_403
    """
    chain = _bound_aurora_policy(api)
    vendor = _forensics_vendor(api)

    denied = api.get_policy(chain["policy"]["id"], PANEL_ADMIN_HEADERS)
    validate_error(denied, ErrorId.UNAUTHORIZED)

    readable = validate_success(
        api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS), expected_status=200
    )
    assert readable["id"] == vendor["id"], (
        "the same PanelAdmin must still reach the panel register it owns"
    )

    engagements, meta = validate_paginated(
        api.list_vendor_engagements(PANEL_ADMIN_HEADERS, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, (
        f"no engagement has been authorised, got total_count {meta['total_count']}"
    )
    assert engagements == [], f"expected an empty engagement list, got {engagements}"


def test_unrecognised_role_header_is_refused_before_the_path_id_resolves(api):
    """PRD §2.1: "Five roles exist, and their spelling is exact: `Underwriter`, `ClaimsAdjuster`, `PortfolioActuary`, `PanelAdmin`, and `Insured`. A value of `X-User-Role` that is not one of these five, or that is not among the roles authorised for the endpoint being called (see §4), is rejected with `ERR_UNAUTHORIZED` (HTTP 403). This check runs before any identifier in the URL is resolved, so an unauthorised role calling an endpoint with a path id that does not exist still receives 403, never 404."
    PRD §2.1: "Both must be present and non-empty; a missing or blank header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before the request body is parsed at all."

    Design: Corner/rbac/unrecognised_role_header_returns_403
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    X.seed_catalog(api)
    account = X.create_account(api)
    application = X.create_application(api, account["id"])
    assert application["status"] == "DRAFT", (
        f"a new application opens in DRAFT, got {application['status']}"
    )

    denied = api.raw_get(
        f"/applications/{application['id']}",
        headers={"X-User-ID": "u-risk-1", "X-User-Role": "RiskEngineer"},
    )
    # Both headers are present and non-empty, so this is a role failure and not
    # an authentication failure; the path id is never resolved either way.
    validate_error(denied, ErrorId.UNAUTHORIZED)

    readable = validate_success(
        api.get_application(application["id"], UNDERWRITER_HEADERS), expected_status=200
    )
    assert readable["id"] == application["id"], (
        "the same read by a declared, authorised role must succeed"
    )


# --------------------------------------------------------------------------
# Role grants
# --------------------------------------------------------------------------
def test_insured_submits_its_own_application(api):
    """PRD §4: "| POST | `/cyber/applications/{application_id}/submit` | Submit the application for underwriting; prices the indicative premium off the attested score. | `Underwriter`, `Insured` |"
    PRD §2.1: "The fifth role is account-bound. When `X-User-Role` is `Insured`, `X-User-ID` is the `id` of the acting insured account; the value returned when an insured account is registered is precisely what that policyholder then presents as `X-User-ID`."
    PRD §3.2: "On success the server recomputes `attested_control_score` on the attested basis, writes `indicative_premium_usd` from the attested-basis pricing run, and increments the application's `version` by 1."
    PRD §3.4: "The **indicative run** fires at submission, consumes `attested_control_score`, and writes `indicative_premium_usd` — a figure issued before any scan can contradict the applicant. The **bindable run** fires at quote issuance, consumes `verified_control_score`, and writes `premium_usd`."
    PRD §3.2: "Each attestation write recomputes the application's `attested_control_score` and increments the application's `version` by 1."

    Design: Corner/rbac/insured_submits_its_own_application
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    X.seed_catalog(api)
    account = X.create_account(api)
    insured_headers = make_insured_headers(account["id"])
    application = X.create_application(api, account["id"])
    X.attest_controls(api, application["id"], C.ATTEST_95)

    resp = api.submit_application(application["id"], insured_headers)
    submitted = validate_success(resp, expected_status=200)

    assert submitted["status"] == "SUBMITTED", (
        f"status: expected SUBMITTED, got {submitted['status']}"
    )
    assert round(float(submitted["attested_control_score"]), 2) == 95.00, (
        f"attested_control_score: expected 95.00, got {submitted['attested_control_score']}"
    )
    assert_money(submitted["indicative_premium_usd"], 25398.00, "indicative_premium_usd")
    assert submitted.get("premium_usd") is None, (
        "premium_usd must stay null until the bindable run at quote issuance, got "
        f"{submitted.get('premium_usd')}"
    )
    # Version 1 at creation, one increment for each of the five attestations,
    # one more for the submission itself.
    assert submitted["version"] == 7, (
        f"version: expected 7 after five attestations and the submit, got {submitted['version']}"
    )


def test_insured_notifies_an_incident_on_its_own_policy(api):
    """PRD §4: "| POST | `/cyber/incident-claims` | Notify an incident against an in-force policy; the claim opens in NOTIFIED with notified_at stamped from the logical clock. | `ClaimsAdjuster`, `Insured` |"
    PRD §2.1: "Ownership checks compare the resource's owning account to `X-User-ID`: directly through `insured_account_id` on an application or a policy, and transitively for coverage sections, incident claims, vendor engagements, proofs of loss, claim payments, and renewal assessments, each of which reaches an insured account through its parent chain."
    PRD §2.1: "A read or write by an `Insured` against a row belonging to another account is rejected with `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP 403). Ownership is evaluated **after** existence, so a foreign row that does exist yields 403, not 404."
    PRD §3.6: "And the notification must be timely: `notified_at` is stamped from the logical clock at acceptance, and the elapsed time from `incident_discovered_at` to `notified_at` must be no more than 30 days, a longer delay yielding `ERR_LATE_NOTIFICATION`."
    PRD §3.6: "The claim opens in `NOTIFIED` with `reserved_amount_usd`, `retention_absorbed_usd`, `paid_total_usd`, and `unallocated_loss_usd` all at 0.00 and `proof_review_round` at 0."

    Design: Corner/rbac/insured_notifies_an_incident_on_its_own_policy
    """
    chain = _bound_aurora_policy(api)
    owner_headers = make_insured_headers(chain["account"]["id"])
    stranger = X.create_account(api, C.ACCOUNT_REDSTONE)
    stranger_headers = make_insured_headers(stranger["id"])
    X.set_clock(api, "2026-09-10T00:00:00Z")

    payload = F.incident_claim_payload(
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
    )
    resp = api.create_incident_claim(payload, owner_headers)
    claim = validate_success(resp, expected_status=201)

    assert claim["status"] == "NOTIFIED", f"status: expected NOTIFIED, got {claim['status']}"
    assert _instant(claim["notified_at"]) == _instant("2026-09-10T00:00:00Z"), (
        f"notified_at must be stamped from the logical clock, got {claim['notified_at']}"
    )
    assert_money(claim["reserved_amount_usd"], 0.00, "reserved_amount_usd")
    assert_money(claim["retention_absorbed_usd"], 0.00, "retention_absorbed_usd")
    assert_money(claim["paid_total_usd"], 0.00, "paid_total_usd")
    assert_money(claim["unallocated_loss_usd"], 0.00, "unallocated_loss_usd")
    assert claim["proof_review_round"] == 0, (
        f"proof_review_round: expected 0, got {claim['proof_review_round']}"
    )

    foreign = api.create_incident_claim(payload, stranger_headers)
    validate_error(foreign, ErrorId.ACCOUNT_SCOPE_VIOLATION)


def test_portfolio_actuary_runs_the_epoch_sweep(api):
    """PRD §4: "| POST | `/cyber/_ops/run-epoch` | Advance the system epoch at the current logical clock instant: expire stale quotes, expire matured policies and non-renew assessments past their remediation deadline. | `Underwriter`, `PortfolioActuary` |"
    PRD §2.5: "Its response reports `expired_application_count`, `expired_policy_count`, `non_renewed_assessment_count`, and `run_at`."
    PRD §3.5: "On success the bindable pricing run writes `premium_usd`, `quoted_by_user_id` is stamped with the acting `X-User-ID`, `quote_expires_at` is set to the current logical clock instant plus 30 days, and the application's `version` is incremented by 1. A quote left unbound does not linger indefinitely: when the epoch sweep runs at or after `quote_expires_at`, a `QUOTED` application moves to `EXPIRED` with `premium_usd` cleared to null and its `version` incremented by 1."

    Design: Corner/rbac/portfolio_actuary_runs_the_epoch_sweep
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = X.quoted_application(api, findings=_email_filtering_partial())
    application_id = chain["application"]["id"]
    assert _instant(chain["application"]["quote_expires_at"]) == _instant(
        "2026-08-31T00:00:00Z"
    ), f"quote_expires_at: expected 2026-08-31T00:00:00Z, got {chain['application']['quote_expires_at']}"

    X.set_clock(api, "2026-08-31T00:00:00Z")
    resp = api.run_epoch(ACTUARY_HEADERS)
    report = validate_success(resp, expected_status=200)

    assert report["expired_application_count"] == 1, (
        f"expired_application_count: expected 1, got {report['expired_application_count']}"
    )
    assert report["expired_policy_count"] == 0, (
        f"expired_policy_count: expected 0, got {report['expired_policy_count']}"
    )
    assert report["non_renewed_assessment_count"] == 0, (
        "non_renewed_assessment_count: expected 0, got "
        f"{report['non_renewed_assessment_count']}"
    )
    assert _instant(report["run_at"]) == _instant("2026-08-31T00:00:00Z"), (
        f"run_at: expected the current clock instant, got {report['run_at']}"
    )

    swept = X.read_application(api, application_id)
    assert swept["status"] == "EXPIRED", (
        f"the quote lapses at exactly its expiry instant, got {swept['status']}"
    )
    assert swept.get("premium_usd") is None, (
        f"premium_usd should be cleared on expiry, got {swept.get('premium_usd')}"
    )


# --------------------------------------------------------------------------
# Segregation of duties
# --------------------------------------------------------------------------
def test_proof_cannot_be_accepted_by_the_adjuster_who_hired_the_vendor(api):
    """PRD §2.11: "Accepting a proof of loss is refused when `X-User-ID` appears as `authorized_by_user_id` on **any** vendor engagement of the same incident claim. The adjuster who hired the response firms may not be the one who signs off the indemnity that pays them."
    PRD §2.10: "5. **Segregation of duties** — the two rules in §2.11; otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §2.1: "It is, however, recorded in two places where segregation of duties depends on it: the `Underwriter` who issues a live quote has its `X-User-ID` written to the application's `quoted_by_user_id`, and the `ClaimsAdjuster` who authorises a panel deployment has its `X-User-ID` written to the engagement's `authorized_by_user_id`."

    Design: Corner/rbac/proof_accepted_by_the_engagement_authorizer_returns_403
    """
    chain = _bound_aurora_policy(api)
    vendor = _forensics_vendor(api)
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    engagement = X.authorize_engagement(
        api,
        claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
        headers=ADJUSTER_HEADERS,
    )
    proof = X.file_proof(
        api,
        claim["id"],
        headers=ADJUSTER_HEADERS,
        claimed_bi_loss_usd=300000,
        trailing_12m_revenue_usd=43800000,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=1.0,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    assert proof["status"] == "UNDER_REVIEW", (
        f"the filed proof should sit UNDER_REVIEW, got {proof['status']}"
    )

    # The adjuster that authorised the forensics deployment is exactly the one
    # now trying to sign off the indemnity that pays it.
    denied = api.accept_proof_of_loss(proof["id"], ADJUSTER_HEADERS)
    validate_error(denied, ErrorId.SEGREGATION_OF_DUTIES)

    unchanged_proof = validate_success(
        api.get_proof_of_loss(proof["id"], ADJUSTER_HEADERS), expected_status=200
    )
    assert unchanged_proof["status"] == "UNDER_REVIEW", (
        f"a refused acceptance must leave the proof UNDER_REVIEW, got {unchanged_proof['status']}"
    )
    assert unchanged_proof.get("assessed_indemnity_usd") is None, (
        "assessed_indemnity_usd must stay null after a refused acceptance, got "
        f"{unchanged_proof.get('assessed_indemnity_usd')}"
    )
    unchanged_claim = X.read_claim(api, claim["id"])
    assert unchanged_claim["status"] == "PROOF_REVIEW", (
        f"the claim must stay in PROOF_REVIEW, got {unchanged_claim['status']}"
    )
    assert_money(unchanged_claim["paid_total_usd"], 0.00, "paid_total_usd")

    accepted = validate_success(
        api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS), expected_status=200
    )
    assert accepted["status"] == "ACCEPTED", (
        "an adjuster that authorised nothing on this claim must be able to accept, got "
        f"{accepted['status']}"
    )
    assert engagement["authorized_by_user_id"] is not None, (
        "the engagement must record the authorising adjuster"
    )
