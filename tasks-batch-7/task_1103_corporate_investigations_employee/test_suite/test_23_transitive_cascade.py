"""Difficulty queue A — transitive_cascade instances."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case_in_fieldwork,
    create_collection_scope_payload, create_preservation_notice_payload,
    create_report_payload,
    setup_closed_case,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]


def test_case_reopen_depth3_cascade_findings_and_recommendation(api):
    """PRD §3.14: "Reopen triggers a three-hop cascade: every `Finding` of
    the case in `FINAL` moves to `CHALLENGED` (hop 1); every
    `DisciplinaryRecommendation` in `APPROVED` whose finding just became
    `CHALLENGED` moves to `RECALLED` (hop 2, caused by hop 1)..."

    Design: Difficulty/transitive_cascade/case_reopen_depth3_cascade
    """
    reset_clock()
    bundle = setup_closed_case()
    case = bundle["case"]
    finding = bundle["finding"]
    rec = bundle["recommendation"]
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    resp = api.transition_case(
        case["id"],
        {"to_status": "FIELDWORK", "rationale": "new whistleblower evidence"},
        mgr,
    )
    case_after = validate_success(resp, expected_status=200)
    assert case_after["status"] == "FIELDWORK"
    f_after = get_success_data(api.get_finding(finding["id"], INV))
    assert f_after["status"] == "CHALLENGED"
    r_after = get_success_data(api.get_disciplinary_recommendation(rec["id"], HR))
    assert r_after["status"] == "RECALLED"


def test_case_reopen_depth3_cascade_report_recall_and_remediation_untouched(api):
    """PRD §3.14: "Reopen triggers a three-hop cascade: every `Finding` of
    the case in `FINAL` moves to `CHALLENGED` (hop 1); every
    `DisciplinaryRecommendation` in `APPROVED` whose finding just became
    `CHALLENGED` moves to `RECALLED` (hop 2, caused by hop 1); and every
    `CaseReport` of the case in `DISTRIBUTED` moves to `RECALLED` because
    its findings basis is challenged (hop 3, also caused by hop 1). The
    case's derived fields are then recomputed."

    The remediation action remains VERIFIED: the cascade does not touch
    terminal remediation.

    Design: Difficulty/transitive_cascade/case_reopen_depth3_cascade
    """
    reset_clock()
    bundle = setup_closed_case()
    case = bundle["case"]
    report = bundle["report"]
    rem = bundle["remediation"]
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    get_success_data(api.transition_case(
        case["id"],
        {"to_status": "FIELDWORK", "rationale": "new whistleblower evidence"},
        mgr,
    ))
    rep_after = get_success_data(api.get_report(report["id"], GC))
    assert rep_after["status"] == "RECALLED"
    rem_after = get_success_data(api.get_remediation_action(rem["id"], HR))
    assert rem_after["status"] == "VERIFIED"


def _setup_notice_release_scenario(api):
    """Case FIELDWORK with: N1 (EMP-100, ALL_DATA) ACKNOWLEDGED + S1
    IN_PROGRESS; N2 (EMP-200, ALL_DATA) ISSUED + S2 PROPOSED. Ratio pre-release
    == 0.50."""
    bundle = create_case_in_fieldwork(
        title="Case TC-2", allegation_category="DATA_BREACH", severity="MEDIUM",
        department="IT",
    )
    case = bundle["case"]
    n1 = get_success_data(api.create_preservation_notice(
        case["id"],
        create_preservation_notice_payload(
            custodian_ref="EMP-100", scope="ALL_DATA", is_regulator_ordered=False,
        ),
        GC,
    ))
    get_success_data(api.transition_preservation_notice(n1["id"], {"to_status": "ACKNOWLEDGED"}, GC))
    n2 = get_success_data(api.create_preservation_notice(
        case["id"],
        create_preservation_notice_payload(
            custodian_ref="EMP-200", scope="ALL_DATA", is_regulator_ordered=False,
        ),
        GC,
    ))
    s1 = get_success_data(api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            planned_start="2026-05-05T00:00:00Z", planned_end="2026-05-10T00:00:00Z",
            preservation_notice_id=n1["id"],
        ),
        INV,
    ))
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_collection_scope(s1["id"], {"to_status": "APPROVED"}, mgr))
    get_success_data(api.transition_collection_scope(s1["id"], {"to_status": "IN_PROGRESS"}, inv1))
    s2 = get_success_data(api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-200", data_source="FILES",
            planned_start="2026-05-05T00:00:00Z", planned_end="2026-05-10T00:00:00Z",
            preservation_notice_id=n2["id"],
        ),
        INV,
    ))
    case_pre = get_success_data(api.get_case(case["id"], INV))
    return {"case": case_pre, "n1": n1, "n2": n2, "s1": s1, "s2": s2}


def test_notice_release_depth2_cascade_scope_withdrawn(api):
    """PRD §3.3: "Release has a two-hop cascade: every `CollectionScope` of
    the same case whose `custodian_ref` matches the released notice's
    `custodian_ref` and that is currently in `PROPOSED`, `APPROVED`, or
    `IN_PROGRESS` is moved to `WITHDRAWN` (hop 1)..."

    Design: Difficulty/transitive_cascade/notice_release_depth2_cascade
    """
    reset_clock()
    bundle = _setup_notice_release_scenario(api)
    case, n2, s1, s2 = bundle["case"], bundle["n2"], bundle["s1"], bundle["s2"]
    # Pre-condition: ratio is 0.50 (1 ACK + 1 ISSUED)
    assert case["preservation_completeness_ratio"] == pytest.approx(0.50, abs=0.001)
    get_success_data(api.transition_preservation_notice(n2["id"], {"to_status": "RELEASED"}, GC))
    s2_after = get_success_data(api.get_collection_scope(s2["id"], INV))
    assert s2_after["status"] == "WITHDRAWN"
    # S1 belongs to a different custodian — untouched
    s1_after = get_success_data(api.get_collection_scope(s1["id"], INV))
    assert s1_after["status"] == "IN_PROGRESS"


def test_notice_release_depth2_cascade_ratio_recompute(api):
    """PRD §3.3: "...the parent case's `preservation_completeness_ratio` is
    then recomputed, with `RELEASED` notices excluded from both numerator and
    denominator (hop 2)."
    PRD §3.3: "The `preservation_completeness_ratio` is the count of the
    case's notices in `ACKNOWLEDGED` divided by the sum of the counts in
    `ACKNOWLEDGED` and `ISSUED`; `RELEASED` notices are excluded from both
    terms."

    Pre-release: 1 ACK / (1 ACK + 1 ISSUED) = 0.50. After N2 RELEASED:
    1 / (1 + 0) = 1.00.

    Design: Difficulty/transitive_cascade/notice_release_depth2_cascade
    """
    reset_clock()
    bundle = _setup_notice_release_scenario(api)
    case, n2 = bundle["case"], bundle["n2"]
    ratio_pre = get_success_data(api.get_case(case["id"], INV))["preservation_completeness_ratio"]
    assert ratio_pre == pytest.approx(0.50, abs=0.001)
    get_success_data(api.transition_preservation_notice(n2["id"], {"to_status": "RELEASED"}, GC))
    case_post = get_success_data(api.get_case(case["id"], INV))
    assert case_post["preservation_completeness_ratio"] == pytest.approx(1.00, abs=0.001)
