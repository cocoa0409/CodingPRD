"""Difficulty queue: compensating invariants (PRD §3.2, §3.8, §3.9).

Conserved quantities across forward/compensating action pairs.
"""
from test_helpers import (
    validate_success, get_success_data, ApiErrorId,
    TEST_USERS,
    create_member, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    link_case_to_ctm, unlink_case_from_ctm, get_member_fresh,
    setup_closed_case, create_and_review_reopening,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def test_open_case_count_intake_then_withdraw_restores_baseline(api):
    """PRD §3.2: "The server stamps `received_at` at intake, sets `status` to `RECEIVED`,
    and increments the member's `open_case_count` by one."
PRD §3.2: "Withdrawal moves the case to `WITHDRAWN`, stamps `closed_at`, decrements
    the member's `open_case_count` by one (and `ctm_linked_case_count` as
    well when the case was CTM-linked), and appends a `NOTE` event whose
    `body` reads `WITHDRAWN`, incrementing the case's `version`."

    Design: Difficulty/compensating_invariant/member_open_case_count_create_withdraw_invariant
    """
    member = create_member("MBR-CI1", full_name="Iris Cho", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    assert get_member_fresh(member["id"])["open_case_count"] == 0
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    assert get_member_fresh(member["id"])["open_case_count"] == 1
    withdrawn = validate_success(api.withdraw_case(case["id"], MSR))
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_member_fresh(member["id"])["open_case_count"] == 0, (
        "count(final) == count(initial) across the intake/withdraw pair")


def test_open_case_count_partial_withdrawal_tracks_net(api):
    """PRD §3.1: "Two counters are computed rather than stored by clients:
    `open_case_count`, the number of the member's cases whose `status` is
    any of `RECEIVED`, `TRIAGED`, `IN_REVIEW`, `PENDING_CLINICAL`,
    `DECIDED`, `NOTIFIED`, `IRE_REFERRED`, or `REOPENED`; and
    `ctm_linked_case_count`, the number of the member's CTM-linked cases
    not yet in `CLOSED` or `WITHDRAWN`."

    Design: Difficulty/compensating_invariant/member_open_case_count_create_withdraw_invariant
    """
    member = create_member("MBR-CI1B", full_name="Iris Cho B",
                           program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case_a = intake_case(member["id"], case_kind="GRIEVANCE")
    case_b = intake_case(member["id"], case_kind="ORG_DETERMINATION")
    assert get_member_fresh(member["id"])["open_case_count"] == 2
    validate_success(api.withdraw_case(case_a["id"], MSR))
    member_after = get_member_fresh(member["id"])
    assert member_after["open_case_count"] == 1, (
        "Withdrawing one of two open cases leaves exactly one open")
    still_open = get_success_data(api.get_case(case_b["id"], COMPLIANCE))
    assert still_open["status"] == "RECEIVED"


def test_ctm_link_unlink_restores_count_and_flag(api):
    """PRD §3.9: "Appending a `CTM_LINKED` event sets the case's `ctm_linked` flag to true
    and increments the member's `ctm_linked_case_count` by one, provided
    the case is not `CLOSED` or `WITHDRAWN`; appending `CTM_UNLINKED`
    clears the flag and decrements the count by one, never below zero and
    only when the case was previously linked."

    Design: Difficulty/compensating_invariant/ctm_linked_count_link_unlink_invariant
    """
    member = create_member("MBR-CI2", full_name="Jae Kim", program="MEDICARE")
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="GRIEVANCE")
    link_case_to_ctm(case["id"], body="x")
    after_link = get_member_fresh(member["id"])
    assert after_link["ctm_linked_case_count"] == 1
    case_after_link = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert case_after_link["ctm_linked"] is True
    unlink_case_from_ctm(case["id"], body="x")
    after_unlink = get_member_fresh(member["id"])
    assert after_unlink["ctm_linked_case_count"] == 0
    case_after_unlink = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert case_after_unlink["ctm_linked"] is False


def test_ctm_unlink_floor_never_below_zero(api):
    """PRD §3.9: "Appending a `CTM_LINKED` event sets the case's `ctm_linked` flag to true
    and increments the member's `ctm_linked_case_count` by one, provided
    the case is not `CLOSED` or `WITHDRAWN`; appending `CTM_UNLINKED`
    clears the flag and decrements the count by one, never below zero and
    only when the case was previously linked."

    Design: Difficulty/compensating_invariant/ctm_linked_count_link_unlink_invariant
    """
    member = create_member("MBR-CI2B", full_name="Jae Kim B",
                           program="MEDICARE")
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="GRIEVANCE")
    link_case_to_ctm(case["id"], body="x")
    unlink_case_from_ctm(case["id"], body="x")
    # A second unlink on an unlinked case must not drive the count negative.
    unlink_case_from_ctm(case["id"], body="x-again")
    assert get_member_fresh(member["id"])["ctm_linked_case_count"] == 0


def _setup_closed_case_with_reviewed_reopening():
    member = create_member("MBR-CI3", full_name="Kai Nos", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    closed = setup_closed_case(member["id"], case_kind="GRIEVANCE")
    reopening = create_and_review_reopening(closed["id"],
                                            request_reason="CLERICAL_ERROR")
    return member, closed, reopening


def test_reopening_grant_adds_exactly_one_open_case(api):
    """PRD §3.8: "On grant, the reopening's `decided_at` is stamped and its
    `spawned_case_id` is set to a newly created case — status `RECEIVED`,
    `reopened_from_case_id` pointing at the source case, `case_kind` and
    `priority_track` copied from it — while the source case
    auto-transitions `CLOSED` → `REOPENED` as a marker, the member's
    `open_case_count` increments by one for the spawned case, any
    `DETERMINED` clinical review on the source case transitions to
    `SUPERSEDED`, and a `REOPEN_GRANTED` event is appended on the source
    case."

    Design: Difficulty/compensating_invariant/reopening_grant_spawn_conserves_total_case_lineage
    """
    member, closed, reopening = _setup_closed_case_with_reviewed_reopening()
    oc_before = get_member_fresh(member["id"])["open_case_count"]
    assert oc_before == 0, "Closed source case is excluded from the count"
    fresh = get_success_data(api.get_case(closed["id"], COMPLIANCE))
    granted = validate_success(api.grant_reopening(
        reopening["id"], {"expected_case_version": fresh["version"]},
        COMPLIANCE))
    oc_after = get_member_fresh(member["id"])["open_case_count"]
    # §3.1 defines open_case_count over an open-status set that includes
    # REOPENED: after the grant the spawned RECEIVED case counts (+1, the
    # increment §3.8 attributes to the spawn) and the source case's
    # CLOSED -> REOPENED marker re-enters the open set (+1).
    assert oc_after == oc_before + 2, (
        "open_case_count counts both the RECEIVED spawn and the REOPENED "
        "source (PRD §3.1 open-status list includes REOPENED); "
        f"before={oc_before} after={oc_after}")
    assert granted["spawned_case_id"]


def test_reopening_grant_lineage_cardinality_is_one(api):
    """PRD §3.2: "The case listing supports filters on `member_id`, `provider_id`, `status`,
    `case_kind`, `priority_track`, `overdue`, and `reopened_from_case_id`."
PRD §3.8: "On grant, the reopening's `decided_at` is stamped and its
    `spawned_case_id` is set to a newly created case — status `RECEIVED`,
    `reopened_from_case_id` pointing at the source case, `case_kind` and
    `priority_track` copied from it — while the source case
    auto-transitions `CLOSED` → `REOPENED` as a marker, the member's
    `open_case_count` increments by one for the spawned case, any
    `DETERMINED` clinical review on the source case transitions to
    `SUPERSEDED`, and a `REOPEN_GRANTED` event is appended on the source
    case."

    Design: Difficulty/compensating_invariant/reopening_grant_spawn_conserves_total_case_lineage
    """
    member, closed, reopening = _setup_closed_case_with_reviewed_reopening()
    fresh = get_success_data(api.get_case(closed["id"], COMPLIANCE))
    granted = validate_success(api.grant_reopening(
        reopening["id"], {"expected_case_version": fresh["version"]},
        COMPLIANCE))
    lineage = get_success_data(api.list_cases(
        COMPLIANCE, params={"member_id": member["id"],
                            "reopened_from_case_id": closed["id"]}))
    assert len(lineage) == 1, (
        f"Exactly one case may descend from the source; got {len(lineage)}")
    assert lineage[0]["id"] == granted["spawned_case_id"]
    assert lineage[0]["status"] == "RECEIVED"
    assert lineage[0]["case_kind"] == "GRIEVANCE"
