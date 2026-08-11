"""Difficulty queue A — combinatorial_formula instances."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    reset_clock, create_case, create_case_in_fieldwork,
    create_subject_payload, create_collection_scope_payload,
    create_evidence_item_payload, add_acknowledged_notice,
    make_investigator_headers, make_manager_headers, make_auditor_headers,
    TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
GC = TEST_USERS["gc_headers"]
AUD = TEST_USERS["auditor_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _build_three_pattern_cases(api):
    """Three HIGH-severity FRAUD cases in Finance, each with subject EMP-100."""
    ids = []
    for title in ("Pattern-1", "Pattern-2", "Pattern-3"):
        c = get_success_data(api.create_case(
            {"title": title, "allegation_category": "FRAUD", "severity": "HIGH",
             "department": "Finance", "lead_investigator_id": "inv-lead-1"},
            IC,
        ))
        ids.append(c["id"])
    for cid in ids:
        get_success_data(api.create_subject(
            cid, create_subject_payload(employee_ref="EMP-100"), INV
        ))
    return ids


def test_pattern_score_multi_input_nonlinear_score(api):
    """PRD §3.15: "The score is 10 times `sev_max` times the volume factor
    times the recency factor times the spread factor, capped at 100 by an
    outer minimum, and rounded half-up to 2 decimal places after the cap. The
    `risk_tier` is `HIGH` when the score is at least 70, `MEDIUM` when it is
    at least 40 and below 70, and `LOW` when it is below 40."
    PRD §3.15: "`REPEAT_SUBJECT` fires when at least 2 cases in the window
    share a subject `employee_ref`."

    For 3 HIGH cases, all created at the default clock (so d=0), in one
    department: sev_max=3, volume=1+0.5*2=2.0, recency=max(0.2, 1-0/90)=1.0,
    spread=1+0.25*0=1.0; score = 10*3*2.0*1.0*1.0 = 60.00 => MEDIUM.

    Design: Difficulty/combinatorial_formula/pattern_score_multi_input_nonlinear
    """
    reset_clock()
    ids = _build_three_pattern_cases(api)
    resp = api.scan_pattern_alerts({}, make_auditor_headers("aud-1"))
    validate_success(resp, expected_status=200)
    data, meta = validate_paginated(api.list_pattern_alerts(
        make_auditor_headers("aud-1"),
        params={"alert_type": "REPEAT_SUBJECT"},
    ))
    assert len(data) == 1
    alert = data[0]
    assert alert["alert_key"] == "EMP-100"
    assert len(alert["case_ids"]) == 3
    assert alert["pattern_risk_score"] == pytest.approx(60.00, abs=0.01)
    assert alert["risk_tier"] == "MEDIUM"


def test_pattern_score_multi_input_nonlinear_idempotent(api):
    """PRD §3.15: "The scan is idempotent on (`alert_type`, `alert_key`,
    `window_start`): an existing `OPEN` or `ACKNOWLEDGED` alert with the same
    key is returned, not duplicated."

    Design: Difficulty/combinatorial_formula/pattern_score_multi_input_nonlinear
    """
    reset_clock()
    _build_three_pattern_cases(api)
    aud = make_auditor_headers("aud-1")
    get_success_data(api.scan_pattern_alerts({}, aud))
    # Second scan in the same clock window
    get_success_data(api.scan_pattern_alerts({}, aud))
    data, meta = validate_paginated(api.list_pattern_alerts(
        aud, params={"alert_type": "REPEAT_SUBJECT"},
    ))
    assert len(data) == 1, "idempotent scan must not duplicate the alert"
    assert data[0]["alert_key"] == "EMP-100"


def _build_three_item_in_progress_scope(api):
    """Case FIELDWORK, ACK notice, scope IN_PROGRESS with three LOGGED
    300000-byte items."""
    bundle = create_case_in_fieldwork(
        title="Case CF-b", allegation_category="DATA_BREACH", severity="MEDIUM",
        department="IT",
    )
    case = bundle["case"]
    notice = add_acknowledged_notice(case["id"], custodian_ref="EMP-100")
    scope = get_success_data(api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            planned_start="2026-05-05T00:00:00Z", planned_end="2026-05-10T00:00:00Z",
            preservation_notice_id=notice["id"],
        ),
        INV,
    ))
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "APPROVED"}, mgr))
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "IN_PROGRESS"}, inv1))
    for hash_suffix, captured in (("ha", "2026-05-06T00:00:00Z"),
                                  ("hb", "2026-05-06T01:00:00Z"),
                                  ("hc", "2026-05-06T02:00:00Z")):
        get_success_data(api.create_evidence_item(
            scope["id"],
            create_evidence_item_payload(
                custodian_ref="EMP-100", hash_value=hash_suffix,
                size_bytes=300000, captured_at=captured,
            ),
            inv1,
        ))
    return {"case": case, "scope": scope}


def test_effort_minutes_nested_rounding_order_value(api):
    """PRD §3.4: "The computation has a pinned rounding order: for each
    evidence item linked to the scope whose status at completion time is one
    of `LOGGED`, `UNDER_REVIEW`, `ADMITTED`, or `EXCLUDED`, the per-item raw
    effort is the item's `size_bytes` divided by one million and then
    multiplied by 2 (the minutes-per-megabyte constant); each per-item raw
    value is rounded UP to the next whole minute (ceiling); the rounded
    per-item minutes are summed to a subtotal; the subtotal is multiplied by
    1.15 (the overhead constant); and the product is rounded half-up to a
    whole number of minutes."

    Three 300,000-byte items: per-item raw = 0.3 * 2 = 0.6, ceil = 1 each,
    subtotal = 3, 3 * 1.15 = 3.45, round_half_up = 3.

    Design: Difficulty/combinatorial_formula/effort_minutes_nested_rounding_order
    """
    reset_clock()
    bundle = _build_three_item_in_progress_scope(api)
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    resp = api.transition_collection_scope(
        bundle["scope"]["id"], {"to_status": "COLLECTED"}, inv1
    )
    scope_after = validate_success(resp, expected_status=200)
    assert scope_after["review_effort_minutes"] == 3


def test_effort_minutes_nested_rounding_order_forbidden_alternative(api):
    """PRD §3.4: "The alternative order — summing raw sizes first and
    rounding once at the end — is forbidden because it produces a different
    result."

    For the three-item setup, the forbidden sum-first order would produce
    ceil-equivalent 1.8 * 1.15 = 2.07 -> round_half_up = 2. Asserting the
    actual pinned value 3 (and != 2) distinguishes the orders.
    Also asserts the custody totals: 3 items of 300000 bytes each.

    Design: Difficulty/combinatorial_formula/effort_minutes_nested_rounding_order
    """
    reset_clock()
    bundle = _build_three_item_in_progress_scope(api)
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    resp = api.transition_collection_scope(
        bundle["scope"]["id"], {"to_status": "COLLECTED"}, inv1
    )
    scope_after = validate_success(resp, expected_status=200)
    assert scope_after["review_effort_minutes"] != 2
    assert scope_after["review_effort_minutes"] == 3
    assert scope_after["collected_item_count"] == 3
    assert scope_after["collected_bytes"] == 900000


def test_priority_score_evaluation_order_pinned_escalated(api):
    """PRD §3.10: "The raw score is 10 times the severity weight (`LOW` 1,
    `MEDIUM` 2, `HIGH` 3, `CRITICAL` 4), plus 15 if `pattern_escalated` is
    true, plus 10 if there exists a `SelfDisclosureDecision` of this case in
    `PENDING` whose `decision_deadline` is no later than the current logical
    clock plus 7 days. The raw score depends only on severity and on these
    flags and deadlines; backlog never feeds it."
    PRD §3.15: "Escalation has a two-hop cascade: every case in `case_ids`
    whose status is one of `INTAKE`, `TRIAGED`, `PLANNING`, `FIELDWORK`,
    `FINDINGS`, `DISPOSITION`, or `REMEDIATION` has its `pattern_escalated`
    set to true (hop 1), and each such case recomputes its
    `case_priority_score` and `priority_tier` (hop 2, caused by hop 1)."

    CRITICAL escalated: raw = 40 + 15 = 55 => URGENT.

    Design: Difficulty/combinatorial_formula/priority_score_evaluation_order_pinned
    """
    reset_clock()
    c1 = get_success_data(api.create_case(
        {"title": "PatternX-1", "allegation_category": "BRIBERY",
         "severity": "CRITICAL", "department": "Sales",
         "lead_investigator_id": "inv-lead-1"},
        IC,
    ))
    c2 = get_success_data(api.create_case(
        {"title": "PatternX-2", "allegation_category": "BRIBERY",
         "severity": "CRITICAL", "department": "Sales",
         "lead_investigator_id": "inv-lead-1"},
        IC,
    ))
    for cid in (c1["id"], c2["id"]):
        get_success_data(api.create_subject(
            cid, create_subject_payload(employee_ref="EMP-500"), INV
        ))
    aud = make_auditor_headers("aud-1")
    get_success_data(api.scan_pattern_alerts({}, aud))
    data, _ = validate_paginated(api.list_pattern_alerts(aud))
    assert len(data) >= 1
    alert_id = data[0]["id"]
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    get_success_data(api.transition_pattern_alert(alert_id, {"to_status": "ACKNOWLEDGED"}, mgr))
    get_success_data(api.transition_pattern_alert(alert_id, {"to_status": "ESCALATED"}, mgr))
    case1_after = get_success_data(api.get_case(c1["id"], INV))
    assert case1_after["pattern_escalated"] is True
    assert case1_after["case_priority_score"] == 55
    assert case1_after["priority_tier"] == "URGENT"


def test_priority_score_evaluation_order_pinned_backlog_irrelevant(api):
    """PRD §3.10: "The raw score depends only on severity and on these flags
    and deadlines; backlog never feeds it."
    PRD §3.10: "The `priority_tier` is `URGENT` when the raw score is at
    least 40, `ELEVATED` when it is at least 20 and below 40, and `ROUTINE`
    when it is below 20."

    A non-escalated MEDIUM case keeps raw = 20 regardless of how many other
    cases share the tier: 10 * 2 = 20, no escalation, no pending-disclosure
    urgency; tier ELEVATED.

    Design: Difficulty/combinatorial_formula/priority_score_evaluation_order_pinned
    """
    reset_clock()
    # Build the same scene: two escalated CRITICAL cases plus one MEDIUM case
    c1 = get_success_data(api.create_case(
        {"title": "PatternX-1", "allegation_category": "BRIBERY",
         "severity": "CRITICAL", "department": "Sales",
         "lead_investigator_id": "inv-lead-1"},
        IC,
    ))
    c2 = get_success_data(api.create_case(
        {"title": "PatternX-2", "allegation_category": "BRIBERY",
         "severity": "CRITICAL", "department": "Sales",
         "lead_investigator_id": "inv-lead-1"},
        IC,
    ))
    for cid in (c1["id"], c2["id"]):
        get_success_data(api.create_subject(
            cid, create_subject_payload(employee_ref="EMP-500"), INV
        ))
    c3 = get_success_data(api.create_case(
        {"title": "Plain-Medium", "allegation_category": "POLICY_VIOLATION",
         "severity": "MEDIUM", "department": "HR",
         "lead_investigator_id": "inv-lead-1"},
        IC,
    ))
    aud = make_auditor_headers("aud-1")
    get_success_data(api.scan_pattern_alerts({}, aud))
    data, _ = validate_paginated(api.list_pattern_alerts(aud))
    alert_id = data[0]["id"]
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    get_success_data(api.transition_pattern_alert(alert_id, {"to_status": "ACKNOWLEDGED"}, mgr))
    get_success_data(api.transition_pattern_alert(alert_id, {"to_status": "ESCALATED"}, mgr))
    case3_after = get_success_data(api.get_case(c3["id"], INV))
    assert case3_after["case_priority_score"] == 20
    assert case3_after["priority_tier"] == "ELEVATED"
    assert case3_after["pattern_escalated"] is False
