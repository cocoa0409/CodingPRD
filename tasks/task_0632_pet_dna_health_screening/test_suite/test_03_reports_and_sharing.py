"""Report finalization, the health roll-up variants, report-revoke cascade,
report-finalize OCC, and the vet-shareable token view.

Covers queue A (dual_variant_calc health roll-up, transitive_cascade report
revoke) and queue B (cross_cutting OCC finalize, validations health gate,
endpoints token view).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_preliminary_report,
    setup_finalized_report_with_share_link,
)
from test_helpers.factories import (
    create_marker_payload,
    finalize_report_payload,
)
from test_helpers.test_users import make_account_headers, make_veterinarian_headers

LAB = TEST_USERS["lab_technician_headers"]


# =========================================================================
# dual_variant_calc: health roll-up preliminary vs finalized (queue A)
# =========================================================================

def test_at_risk_count_preliminary_excludes_reviewed(api):
    """PRD §3.4: "While the report is `PRELIMINARY`, the count includes only those
    marker results whose `genotype` is `AT_RISK` and whose `review_status` is
    `PASS`; reviewed markers are excluded."

    Design: Difficulty/dual_variant_calc/health_rollup_preliminary_vs_finalized_on_report
    """
    base = setup_preliminary_report(product_tier="BREED_HEALTH")
    rep_id = base["report"]["id"]

    api.create_marker(
        rep_id, create_marker_payload("M_A", "AT_RISK", review_status="PASS"), LAB
    )
    api.create_marker(
        rep_id, create_marker_payload("M_B", "AT_RISK", review_status="REVIEWED"), LAB
    )

    report = validate_success(api.get_report(rep_id, LAB))
    assert report["at_risk_marker_count"] == 1, \
        f"PRELIMINARY count must exclude REVIEWED, expected 1, got {report['at_risk_marker_count']}"


def test_at_risk_count_finalized_includes_reviewed(api):
    """PRD §3.4: "Once the report is `FINALIZED`, the count includes every marker
    result whose `genotype` is `AT_RISK` and whose `review_status` is either
    `PASS` or `REVIEWED`."
    PRD §3.4: "On success the system recomputes `at_risk_marker_count` under the
    finalized rule (now including reviewed markers)"

    Design: Difficulty/dual_variant_calc/health_rollup_preliminary_vs_finalized_on_report
    """
    base = setup_preliminary_report(product_tier="BREED_HEALTH")
    rep_id = base["report"]["id"]

    api.create_marker(
        rep_id, create_marker_payload("M_A", "AT_RISK", review_status="PASS"), LAB
    )
    api.create_marker(
        rep_id, create_marker_payload("M_B", "AT_RISK", review_status="REVIEWED"), LAB
    )
    rep = validate_success(api.get_report(rep_id, LAB))
    resp = api.finalize_report(rep_id, finalize_report_payload(rep["version"]), LAB)
    finalized = validate_success(resp)
    assert finalized["status"] == "FINALIZED", \
        f"expected FINALIZED, got {finalized['status']}"
    assert finalized["at_risk_marker_count"] == 2, \
        f"FINALIZED count must include REVIEWED, expected 2, got {finalized['at_risk_marker_count']}"


# =========================================================================
# transitive_cascade: report revoke -> share-link revocation (queue A)
# =========================================================================

def test_revoke_report_sets_report_revoked(api):
    """PRD §3.4: "A report may be revoked by its owning account from either
    `PRELIMINARY` or `FINALIZED`, moving it to the terminal `REVOKED` state."

    Design: Difficulty/transitive_cascade/report_revoke_cascades_sharelink_revocation_depth2
    """
    base = setup_finalized_report_with_share_link()
    acct_h = make_account_headers(base["account"]["id"])
    resp = api.revoke_report(base["report"]["id"], acct_h)
    report = validate_success(resp)
    assert report["status"] == "REVOKED", f"expected REVOKED, got {report['status']}"


def test_revoke_report_cascades_share_link_revocation(api):
    """PRD §3.4: "Revocation cascades: every `ACTIVE` share link for the report
    is revoked, moving each from `ACTIVE` to `REVOKED`."

    Design: Difficulty/transitive_cascade/report_revoke_cascades_sharelink_revocation_depth2
    """
    base = setup_finalized_report_with_share_link()
    acct_h = make_account_headers(base["account"]["id"])
    api.revoke_report(base["report"]["id"], acct_h)

    share = validate_success(api.get_share_link(base["share_link"]["id"], acct_h))
    assert share["status"] == "REVOKED", \
        f"share link must cascade to REVOKED, got {share['status']}"


# =========================================================================
# Corner: OCC finalize stale report (cross_cutting_complexity_layers)
# =========================================================================

def test_finalize_with_stale_version_after_marker_rejected(api):
    """PRD §2.9: "Because attaching a reviewed marker or revoking the report
    bumps its `version`, a finalize that carries an out-of-date version is
    operating on a stale report view and is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_finalize_stale_report_returns_412
    """
    base = setup_preliminary_report(product_tier="BREED_HEALTH")
    rep_id = base["report"]["id"]
    stale_version = base["report"]["version"]

    # Attaching a marker bumps report.version past the value read above.
    api.create_marker(rep_id, create_marker_payload("DM_SOD1", "CARRIER"), LAB)

    resp = api.finalize_report(rep_id, finalize_report_payload(stale_version), LAB)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# =========================================================================
# Corner: marker on BREED-only report rejected (validations)
# =========================================================================

def test_marker_on_breed_only_report_rejected(api):
    """PRD §3.4: "Attaching a marker to a report whose kit was only `BREED` —
    that is, whose `includes_health` is false — is rejected with
    `ERR_HEALTH_NOT_INCLUDED`."

    Design: Corner/validations/marker_on_breed_only_report_returns_health_not_included
    """
    base = setup_preliminary_report(product_tier="BREED")
    resp = api.create_marker(
        base["report"]["id"], create_marker_payload("MDR1", "AT_RISK"), LAB
    )
    validate_error(resp, ApiErrorId.ERR_HEALTH_NOT_INCLUDED.value)


# =========================================================================
# Corner: token view (endpoints)
# =========================================================================

def test_vet_fetches_shared_report_via_token(api):
    """PRD §3.5: "The token is the credential a vet uses to fetch the report
    without any authentication headers: the public shared-report view accepts a
    token and returns the underlying report, and it is the one endpoint open to
    the `Veterinarian` and `Anonymous` roles."

    Design: Corner/endpoints/vet_fetches_shared_report_via_token
    """
    base = setup_finalized_report_with_share_link(vet_email="vet2@example.com")
    token = base["share_link"]["token"]

    resp = api.get_shared_report(token, make_veterinarian_headers())
    report = validate_success(resp)
    assert report["id"] == base["report"]["id"], "token must return the underlying report"
    assert report["status"] == "FINALIZED", f"expected FINALIZED, got {report['status']}"


def test_revoked_share_link_token_returns_invalid_token(api):
    """PRD §3.5: "If the token does not correspond to any link, or the link it
    names has been revoked, the lookup is rejected with `ERR_INVALID_TOKEN`."

    Design: Corner/endpoints/revoked_share_link_token_returns_invalid_token
    """
    base = setup_finalized_report_with_share_link(vet_email="vet3@example.com")
    acct_h = make_account_headers(base["account"]["id"])
    api.revoke_share_link(base["share_link"]["id"], acct_h)

    resp = api.get_shared_report(base["share_link"]["token"], make_veterinarian_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_TOKEN.value)
