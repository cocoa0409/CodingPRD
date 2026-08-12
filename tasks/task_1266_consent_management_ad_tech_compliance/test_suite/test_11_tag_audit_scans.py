"""Tag audit scans: cooldown windows, detection, findings, risk scores, SoD."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_property, create_approved_vendor,
    create_tag_audit_scan_payload, run_scan_payload, observed_tracker,
    make_auditor_headers,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
VM = TEST_USERS["vendor_manager_headers"]
ANY = TEST_USERS["any_headers"]
AUD1 = make_auditor_headers("aud-1")
AUD2 = make_auditor_headers("aud-2")


def test_scan_cooldown_one_minute_early_conflicts(api):
    """PRD section 3.7: "the new window, expanded by one hundred and twenty
    minutes on both sides, must not intersect any existing scan's raw window —
    a scan starting exactly one hundred and twenty minutes after the previous
    scan's end is allowed, one minute earlier is not, and violations are
    rejected with `ERR_SCAN_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/scan_cooldown_buffer_edge
    """
    prop = create_property(name="Scan Site", sale_share_designation="NO_SALE_NO_SHARE")
    get_success_data(
        api.create_tag_audit_scan(
            create_tag_audit_scan_payload(
                prop["id"], scheduled_start="2026-06-10T10:00:00Z", duration_minutes=60,
            ),
            AUD1,
        )
    )
    # Prior raw window [10:00, 11:00); 12:59 start expands to [10:59, 14:59) -> intersects.
    res = api.create_tag_audit_scan(
        create_tag_audit_scan_payload(
            prop["id"], scheduled_start="2026-06-10T12:59:00Z", duration_minutes=60,
        ),
        AUD1,
    )
    validate_error(res, ApiErrorId.ERR_SCAN_WINDOW_CONFLICT)


def test_scan_cooldown_exact_edge_allowed(api):
    """PRD section 3.7: "a scan starting exactly one hundred and twenty minutes
    after the previous scan's end is allowed, one minute earlier is not, and
    violations are rejected with `ERR_SCAN_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/scan_cooldown_buffer_edge
    """
    prop = create_property(name="Scan Site", sale_share_designation="NO_SALE_NO_SHARE")
    get_success_data(
        api.create_tag_audit_scan(
            create_tag_audit_scan_payload(
                prop["id"], scheduled_start="2026-06-10T10:00:00Z", duration_minutes=60,
            ),
            AUD1,
        )
    )
    # 13:00 start: expanded start 11:00 == prior raw end 11:00 -> buffer edge allowed.
    scan_b = validate_success(
        api.create_tag_audit_scan(
            create_tag_audit_scan_payload(
                prop["id"], scheduled_start="2026-06-10T13:00:00Z", duration_minutes=60,
            ),
            AUD1,
        ),
        201,
    )
    assert scan_b["status"] == "SCHEDULED"


def test_scan_run_twice_rejected(api):
    """PRD section 3.7: "Running the scan (again `ComplianceAuditor`-only, and
    only from `SCHEDULED`, else `ERR_SCAN_NOT_RUNNABLE`)".

    Design: Corner/state_machines/scan_run_twice_rejected
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    scan = get_success_data(
        api.create_tag_audit_scan(create_tag_audit_scan_payload(prop["id"]), AUD1)
    )
    get_success_data(api.run_tag_audit_scan(scan["id"], run_scan_payload([]), AUD1))
    res = api.run_tag_audit_scan(scan["id"], run_scan_payload([]), AUD1)
    validate_error(res, ApiErrorId.ERR_SCAN_NOT_RUNNABLE)


def test_scan_run_dedup_and_clean_tracker(api):
    """PRD section 3.7: "Detection deduplicates observations by signature, first
    observation winning, and then classifies each distinct tracker: if no
    `APPROVED` vendor of the property declares the signature, a
    `TrackerFinding` is created with `violation_type` `UNAUTHORIZED_TRACKER`,
    `severity` `HIGH`, and a null `vendor_id`; ... a fully conforming
    observation produces nothing."

    Design: Corner/cross_cutting_layers/scan_run_dedup_and_clean_tracker
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    create_approved_vendor(
        prop["id"], legal_name="OK", declared_purposes=["ADVERTISING"],
        tracker_signatures=["ok-1.com"],
    )
    scan = get_success_data(
        api.create_tag_audit_scan(create_tag_audit_scan_payload(prop["id"]), AUD1)
    )
    run = validate_success(
        api.run_tag_audit_scan(
            scan["id"],
            run_scan_payload([
                observed_tracker("ok-1.com", "ADVERTISING"),
                observed_tracker("ok-1.com", "ADVERTISING"),
                observed_tracker("sneaky.com", "ANALYTICS"),
            ]),
            AUD1,
        ),
        200,
    )
    assert run["findings_created_count"] == 1, (
        "duplicate ok-1.com observations and the clean match produce no finding"
    )
    assert run["unauthorized_findings_count"] == 1
    findings, _m = validate_paginated(api.list_scan_findings(scan["id"], ANY))
    assert len(findings) == 1
    f = findings[0]
    assert f["violation_type"] == "UNAUTHORIZED_TRACKER"
    assert f["severity"] == "HIGH"
    assert f["vendor_id"] is None


def _risk_site(api):
    prop = create_property(name="Risk Site", sale_share_designation="SELLS_AND_SHARES")
    vend = create_approved_vendor(
        prop["id"], legal_name="AdCorp", declared_purposes=["ADVERTISING"],
        tracker_signatures=["trk-a.com"],
    )
    scan = get_success_data(
        api.create_tag_audit_scan(
            create_tag_audit_scan_payload(
                prop["id"], scheduled_start="2026-06-01T10:00:00Z", duration_minutes=60,
            ),
            AUD1,
        )
    )
    get_success_data(
        api.run_tag_audit_scan(
            scan["id"],
            run_scan_payload([
                observed_tracker("trk-a.com", "ANALYTICS"),
                observed_tracker("rogue-x.com", "ADVERTISING"),
            ]),
            AUD1,
        )
    )
    findings, _m = validate_paginated(api.list_scan_findings(scan["id"], ANY))
    return prop, vend, scan, findings


def test_vendor_risk_strict_vs_weighted_after_confirm(api):
    """PRD section 3.7: "`risk_score_strict` is the binary posture: one hundred
    if any of the vendor's findings stands at `CONFIRMED_VIOLATION`, zero
    otherwise. `risk_score_weighted` is graduated: the sum of severity weights —
    fifty per `HIGH`, twenty-five per `MEDIUM` — over the vendor's findings in
    `OPEN` or `CONFIRMED_VIOLATION`, capped at one hundred". "The two variants
    legitimately disagree: a vendor with one confirmed `MEDIUM` violation reads
    one hundred strict against twenty-five weighted."

    Design: Difficulty/dual_variant_calc/vendor_risk_strict_vs_weighted
    """
    prop, vend, scan, findings = _risk_site(api)
    assert len(findings) == 2
    # First observation wins ordering: findings[0] is the trk-a.com PURPOSE_MISMATCH.
    mismatch = findings[0]
    assert mismatch["violation_type"] == "PURPOSE_MISMATCH"
    assert mismatch["vendor_id"] == vend["id"]

    validate_success(
        api.update_tracker_finding(mismatch["id"], {"status": "CONFIRMED_VIOLATION"}, AUD2), 200
    )
    vend_after = get_success_data(api.get_vendor(vend["id"], ANY))
    assert vend_after["risk_score_strict"] == 100, "a CONFIRMED_VIOLATION exists"
    assert vend_after["risk_score_weighted"] == 25, (
        "single MEDIUM weight; the HIGH finding has vendor_id null and does not count"
    )


def test_vendor_risk_scores_open_finding_before_confirm(api):
    """PRD section 3.7: "`risk_score_weighted` is graduated: the sum of severity
    weights — fifty per `HIGH`, twenty-five per `MEDIUM` — over the vendor's
    findings in `OPEN` or `CONFIRMED_VIOLATION`, capped at one hundred" and
    "`risk_score_strict` ... zero otherwise." Also: "The scan reports
    `findings_created_count` and `unauthorized_findings_count`."

    Design: Difficulty/dual_variant_calc/vendor_risk_strict_vs_weighted
    """
    prop, vend, scan, findings = _risk_site(api)
    vend_open = get_success_data(api.get_vendor(vend["id"], ANY))
    assert vend_open["risk_score_strict"] == 0, "no CONFIRMED_VIOLATION yet"
    assert vend_open["risk_score_weighted"] == 25, "one OPEN MEDIUM finding counts"
    scan_after = get_success_data(api.get_tag_audit_scan(scan["id"], ANY))
    assert scan_after["findings_created_count"] == 2
    assert scan_after["unauthorized_findings_count"] == 1
    assert scan_after["status"] == "COMPLETED"


def test_sod_scan_creator_cannot_confirm_own(api):
    """PRD section 3.7: "the auditor whose identifier is recorded as the scan's
    `created_by_user_id` may not confirm violations on their own scan; the
    attempt is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`, and a second
    auditor must confirm instead."

    Design: Corner/cross_cutting_layers/sod_scan_creator_cannot_confirm_own
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    scan = get_success_data(
        api.create_tag_audit_scan(create_tag_audit_scan_payload(prop["id"]), AUD1)
    )
    get_success_data(
        api.run_tag_audit_scan(
            scan["id"], run_scan_payload([observed_tracker("rogue.com", "ADVERTISING")]), AUD1
        )
    )
    findings, _m = validate_paginated(api.list_scan_findings(scan["id"], ANY))
    f1 = findings[0]["id"]

    res = api.update_tracker_finding(f1, {"status": "CONFIRMED_VIOLATION"}, AUD1)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    confirmed = validate_success(
        api.update_tracker_finding(f1, {"status": "CONFIRMED_VIOLATION"}, AUD2), 200
    )
    assert confirmed["status"] == "CONFIRMED_VIOLATION"
    assert confirmed["confirmed_by_user_id"] == "aud-2"


def test_finding_close_from_open_rejected(api):
    """PRD section 3.7: "Closing directly from `OPEN`, or any other unlisted
    hop, fails with `ERR_FINDING_INVALID_STATE`."

    Design: Corner/state_machines/finding_close_from_open_rejected
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    scan = get_success_data(
        api.create_tag_audit_scan(create_tag_audit_scan_payload(prop["id"]), AUD1)
    )
    get_success_data(
        api.run_tag_audit_scan(
            scan["id"], run_scan_payload([observed_tracker("rogue.com", "ADVERTISING")]), AUD1
        )
    )
    findings, _m = validate_paginated(api.list_scan_findings(scan["id"], ANY))
    res = api.update_tracker_finding(findings[0]["id"], {"status": "CLOSED"}, AUD2)
    validate_error(res, ApiErrorId.ERR_FINDING_INVALID_STATE)


def test_finding_confirm_role_restricted_to_auditor(api):
    """PRD section 3.7: "The adjudication operation is role-split by payload: a
    `VendorManager` may request remediation but a confirmation from them is
    refused with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/finding_confirm_role_restricted_to_auditor
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    scan = get_success_data(
        api.create_tag_audit_scan(create_tag_audit_scan_payload(prop["id"]), AUD1)
    )
    get_success_data(
        api.run_tag_audit_scan(
            scan["id"], run_scan_payload([observed_tracker("rogue.com", "ADVERTISING")]), AUD1
        )
    )
    findings, _m = validate_paginated(api.list_scan_findings(scan["id"], ANY))
    res = api.update_tracker_finding(findings[0]["id"], {"status": "CONFIRMED_VIOLATION"}, VM)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_scan_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_SCAN_NOT_FOUND`, ...)."

    Design: Corner/errors/scan_get_not_found_returns_404
    """
    res = api.get_tag_audit_scan(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_SCAN_NOT_FOUND)


def test_finding_put_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_FINDING_NOT_FOUND`, ...)."

    Design: Corner/errors/finding_put_not_found_returns_404
    """
    res = api.update_tracker_finding(NON_EXISTENT_UUID, {"status": "REMEDIATED"}, VM)
    validate_error(res, ApiErrorId.ERR_FINDING_NOT_FOUND)
