"""Difficulty queue A — compensating_invariant instances."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case_in_fieldwork,
    create_interview_payload, create_collection_scope_payload,
    create_evidence_item_payload, create_privilege_designation_payload,
    add_acknowledged_notice,
    make_investigator_headers, make_manager_headers, make_gc_headers,
    TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
GC = TEST_USERS["gc_headers"]


def _setup_evidence_invariant_scene(api):
    """Case FIELDWORK; scope IN_PROGRESS with e1 (1000000 bytes, ADMITTED)
    and e2 (500000 bytes, LOGGED)."""
    bundle = create_case_in_fieldwork(
        title="Case CI-1", allegation_category="FRAUD", severity="HIGH",
        department="Finance",
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
    e1 = get_success_data(api.create_evidence_item(
        scope["id"],
        create_evidence_item_payload(
            custodian_ref="EMP-100", hash_value="h1", size_bytes=1_000_000,
            captured_at="2026-05-06T00:00:00Z",
        ),
        INV,
    ))
    e2 = get_success_data(api.create_evidence_item(
        scope["id"],
        create_evidence_item_payload(
            custodian_ref="EMP-100", hash_value="h2", size_bytes=500_000,
            captured_at="2026-05-06T01:00:00Z",
        ),
        INV,
    ))
    get_success_data(api.transition_evidence_item(e1["id"], {"to_status": "UNDER_REVIEW"}, inv1))
    get_success_data(api.transition_evidence_item(e1["id"], {"to_status": "ADMITTED"}, inv1))
    return {"case": case, "scope": scope, "e1": e1, "e2": e2}


def test_evidence_exclude_restore_bytes_invariant_baseline_and_drop(api):
    """PRD §3.4: "The custody totals count only items in `LOGGED`,
    `UNDER_REVIEW`, or `ADMITTED`; `EXCLUDED` items drop out of both terms
    and re-enter if restored."

    Baseline collected_bytes == 1500000 and count == 2; after e1 EXCLUDED,
    collected_bytes == 500000.

    Design: Difficulty/compensating_invariant/evidence_exclude_restore_bytes_invariant
    """
    reset_clock()
    bundle = _setup_evidence_invariant_scene(api)
    scope = bundle["scope"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    scope0 = get_success_data(api.get_collection_scope(scope["id"], INV))
    assert scope0["collected_bytes"] == 1_500_000
    assert scope0["collected_item_count"] == 2
    get_success_data(api.transition_evidence_item(
        bundle["e1"]["id"], {"to_status": "EXCLUDED"}, inv1
    ))
    scope_mid = get_success_data(api.get_collection_scope(scope["id"], INV))
    assert scope_mid["collected_bytes"] == 500_000


def test_evidence_exclude_restore_bytes_invariant_restored(api):
    """PRD §3.4: "The custody totals count only items in `LOGGED`,
    `UNDER_REVIEW`, or `ADMITTED`; `EXCLUDED` items drop out of both terms
    and re-enter if restored."
    PRD §3.4: "Every transition recomputes the parent scope's
    `collected_item_count` and `collected_bytes`."

    The forward EXCLUDED paired with its compensating restore leaves the
    conserved quantity unchanged: 1500000/2 before and after.

    Design: Difficulty/compensating_invariant/evidence_exclude_restore_bytes_invariant
    """
    reset_clock()
    bundle = _setup_evidence_invariant_scene(api)
    scope = bundle["scope"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_evidence_item(
        bundle["e1"]["id"], {"to_status": "EXCLUDED"}, inv1
    ))
    get_success_data(api.transition_evidence_item(
        bundle["e1"]["id"], {"to_status": "ADMITTED"}, inv1
    ))
    scope_end = get_success_data(api.get_collection_scope(scope["id"], INV))
    assert scope_end["collected_bytes"] == 1_500_000
    assert scope_end["collected_item_count"] == 2


def test_privilege_designate_waive_count_invariant_designated_and_confirmed(api):
    """PRD §3.6: "The designating counsel's `X-User-ID` is recorded as
    `designated_by`, the new designation enters `DESIGNATED`, and the case's
    `active_privileged_artifact_count` is incremented by 1."
    PRD §3.6: "Moving to `CONFIRMED` leaves the case's
    `active_privileged_artifact_count` unchanged because `CONFIRMED` still
    counts as active."

    Design: Difficulty/compensating_invariant/privilege_designate_waive_count_invariant
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Case CI-2", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:00:00Z",
            scheduled_end="2026-05-10T15:00:00Z",
        ),
        INV,
    ))
    cnt0 = get_success_data(api.get_case(case["id"], GC))["active_privileged_artifact_count"]
    assert cnt0 == 0
    pd = get_success_data(api.create_privilege_designation(
        case["id"],
        {"target_type": "INTERVIEW", "target_id": interview["id"],
         "privilege_type": "ACP", "rationale": "counsel-directed interview"},
        GC,
    ))
    cnt1 = get_success_data(api.get_case(case["id"], GC))["active_privileged_artifact_count"]
    assert cnt1 == 1
    get_success_data(api.transition_privilege_designation(pd["id"], {"to_status": "CONFIRMED"}, GC))
    cnt2 = get_success_data(api.get_case(case["id"], GC))["active_privileged_artifact_count"]
    assert cnt2 == 1


def test_privilege_designate_waive_count_invariant_waived(api):
    """PRD §3.6: "Moving to `WAIVED` from any of the three active states
    decrements the case's `active_privileged_artifact_count` by 1."
    PRD §3.6: "The count of a case's privileged artifacts equals the number
    of `PrivilegeDesignation` rows for the case in `DESIGNATED`, `CONFIRMED`,
    or `CHALLENGED`."

    Designation (+1) paired with its compensating waiver (-1) leaves the
    count at its original value 0.

    Design: Difficulty/compensating_invariant/privilege_designate_waive_count_invariant
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Case CI-2", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:00:00Z",
            scheduled_end="2026-05-10T15:00:00Z",
        ),
        INV,
    ))
    pd = get_success_data(api.create_privilege_designation(
        case["id"],
        {"target_type": "INTERVIEW", "target_id": interview["id"],
         "privilege_type": "ACP"},
        GC,
    ))
    get_success_data(api.transition_privilege_designation(pd["id"], {"to_status": "CONFIRMED"}, GC))
    get_success_data(api.transition_privilege_designation(pd["id"], {"to_status": "WAIVED"}, GC))
    cnt3 = get_success_data(api.get_case(case["id"], GC))["active_privileged_artifact_count"]
    assert cnt3 == 0
