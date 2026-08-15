"""Edit approval guards: author SoD, role gating, optimistic concurrency on
the rule version, attestation-vs-overlap precedence, half-open window
adjacency, and permanent hit pinning."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_version,
    create_edit_rule,
    create_edit_version,
    create_provider,
    drive_hit_resolution,
    get_rule,
    get_version,
    list_claim_hits,
    make_approver_headers,
    make_librarian_headers,
    make_provider_headers,
    submit_version,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]
APPROVER = TEST_USERS["approver_headers"]


def test_sod_author_cannot_approve_own_version(api):
    """PRD §2.9: "The edit library separates authorship from activation: the
    operator who approves an edit version must not be the operator recorded as
    that version's `created_by_user_id`, and a self-approval attempt is
    rejected with `ERR_SOD_AUTHOR_APPROVAL` (HTTP 403)."

    Design: Corner/validations/sod_author_cannot_approve_own_version
    """
    rule = create_edit_rule(edit_code="SOD-01", category="POLICY",
                            librarian_id="librarian-1")
    version = create_edit_version(rule["id"], librarian_id="librarian-1")
    submit_version(version["id"], librarian_id="librarian-1")
    assert version["created_by_user_id"] == "librarian-1"

    resp = api.approve_edit_version(
        version["id"], {"expected_edit_rule_version": rule["version"]},
        make_approver_headers("librarian-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_AUTHOR_APPROVAL,
                   expected_status=403)
    assert get_version(version["id"])["status"] == "PENDING_APPROVAL"


def test_provider_cannot_approve_edit_version(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: approve is authorized for EditApprover only.

    Design: Corner/rbac/provider_cannot_approve_edit_version
    """
    provider = create_provider(npi="NPI-RB1", name="Rbac Prov")
    rule = create_edit_rule(edit_code="RB-01", category="POLICY")
    version = create_edit_version(rule["id"])
    submit_version(version["id"])

    resp = api.approve_edit_version(
        version["id"], {"expected_edit_rule_version": rule["version"]},
        make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    assert get_version(version["id"])["status"] == "PENDING_APPROVAL"


def test_librarian_cannot_approve_version(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: approve is authorized for EditApprover only.

    Design: Corner/rbac/librarian_cannot_approve_version
    """
    rule = create_edit_rule(edit_code="RB-02", category="POLICY",
                            librarian_id="librarian-1")
    version = create_edit_version(rule["id"], librarian_id="librarian-1")
    submit_version(version["id"], librarian_id="librarian-1")

    # librarian-9 did not author the version; the denial is role-level.
    resp = api.approve_edit_version(
        version["id"], {"expected_edit_rule_version": rule["version"]},
        make_librarian_headers("librarian-9"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    assert get_version(version["id"])["status"] == "PENDING_APPROVAL"


def test_occ_stale_rule_version_on_approve(api):
    """PRD §2.7: "If `expected_edit_rule_version` does not equal the
    EditRule's current `version`, the approval is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the rule
    before approving."
    PRD §3.2: "Finally the window check: the version's half-open effectiveness
    window must not overlap the window of any other `ACTIVE` version of the
    same rule"

    Design: Corner/cross_cutting_layers/occ_stale_rule_version_on_approve
    """
    rule = create_edit_rule(edit_code="OCC-01", category="POLICY")
    observed_v = rule["version"]
    ver_a = create_edit_version(rule["id"], logic_expression="deny A",
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2026-07-01T00:00:00Z")
    submit_version(ver_a["id"])
    approve_version(ver_a["id"], observed_v)

    ver_b = create_edit_version(rule["id"], logic_expression="deny B",
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2026-07-01T00:00:00Z")
    submit_version(ver_b["id"])

    stale = api.approve_edit_version(
        ver_b["id"], {"expected_edit_rule_version": observed_v}, APPROVER)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    fresh_rule = get_rule(rule["id"])
    assert fresh_rule["version"] == observed_v + 1
    overlap = api.approve_edit_version(
        ver_b["id"], {"expected_edit_rule_version": fresh_rule["version"]},
        APPROVER)
    validate_error(overlap, ApiErrorId.ERR_EDIT_WINDOW_OVERLAP,
                   expected_status=409)


def test_version_pinning_keeps_original_edit_version(api):
    """PRD §3.2: "Hits pinned to the version keep pointing at it — the
    pinning is permanent and is never re-pointed"
    PRD §3.4: "Each hit pins its `edit_version_id` permanently at screening
    time"

    Design: Corner/cross_cutting_layers/version_pinning_keeps_original_edit_version
    """
    provider = create_provider(npi="NPI-VP", name="Pin Prov")
    rule = create_edit_rule(edit_code="PIN-DENY", category="CODING")
    ver_a = create_edit_version(rule["id"], logic_expression="deny A")
    submit_version(ver_a["id"])
    approve_version(ver_a["id"], rule["version"])

    ctx = drive_hit_resolution(provider["id"], 30000, "VP1", "M-VP1", "uphold")
    hit = ctx["hit"]
    assert hit["edit_version_id"] == ver_a["id"]
    assert hit["status"] == "CONFIRMED"

    # Retire A (no FIRED hits) and bring B ACTIVE; the hit must not re-point.
    validate_success(api.retire_edit_version(ver_a["id"], APPROVER))
    ver_b = create_edit_version(rule["id"], logic_expression="deny B")
    submit_version(ver_b["id"])
    approve_version(ver_b["id"], get_rule(rule["id"])["version"])
    assert get_version(ver_b["id"])["status"] == "ACTIVE"

    hits = list_claim_hits(ctx["claim"]["id"])
    assert len(hits) == 1
    assert hits[0]["edit_version_id"] == ver_a["id"], (
        "hit stays pinned to the RETIRED version, never re-pointed to B"
    )
    assert hits[0]["status"] == "CONFIRMED"
    assert hits[0]["attributed_savings_cents"] == 30000


def test_approve_missing_attestation_safety_beats_window_overlap(api):
    """PRD §3.2: "Then clinical attestation: approving a `DENY` version whose
    `applies_to_claim_types` contains `INSTITUTIONAL_INPATIENT` requires the
    request's optional `clinical_review_attestation` to be true, else
    `ERR_CLINICAL_ATTESTATION_REQUIRED` (HTTP 422). Finally the window check"
    PRD §2.8: "validation runs in a fixed order of precedence bands, and a
    failure in an earlier band masks every later check."

    Design: Difficulty/priority_pair_validation_conflict/approve_missing_attestation_safety_beats_window_overlap
    """
    rule = create_edit_rule(edit_code="SAFE-01", category="CLINICAL")
    v1 = create_edit_version(
        rule["id"], severity="DENY",
        claim_types=("INSTITUTIONAL_INPATIENT",),
        logic_expression="deny inpatient line",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z")
    submit_version(v1["id"])
    approve_version(v1["id"], rule["version"], attestation=True)

    # v2 overlaps v1's ACTIVE window AND is missing the attestation.
    v2 = create_edit_version(
        rule["id"], severity="DENY",
        claim_types=("INSTITUTIONAL_INPATIENT",),
        logic_expression="deny inpatient line v2",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-12-01T00:00:00Z", librarian_id="librarian-2")
    submit_version(v2["id"], librarian_id="librarian-2")

    rule_now = get_rule(rule["id"])
    resp = api.approve_edit_version(
        v2["id"], {"expected_edit_rule_version": rule_now["version"]},
        APPROVER)
    validate_error(resp, ApiErrorId.ERR_CLINICAL_ATTESTATION_REQUIRED,
                   expected_status=422)
    assert get_version(v2["id"])["status"] == "PENDING_APPROVAL"


def test_approve_with_attestation_surfaces_window_overlap(api):
    """PRD §3.2: "Then clinical attestation: approving a `DENY` version whose
    `applies_to_claim_types` contains `INSTITUTIONAL_INPATIENT` requires the
    request's optional `clinical_review_attestation` to be true, else
    `ERR_CLINICAL_ATTESTATION_REQUIRED` (HTTP 422). Finally the window check:
    the version's half-open effectiveness window must not overlap the window
    of any other `ACTIVE` version of the same rule — adjacency, where one
    window's `effective_from` equals another's `effective_to`, is allowed
    because the end is exclusive — and an overlap is rejected with
    `ERR_EDIT_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/approve_missing_attestation_safety_beats_window_overlap
    """
    rule = create_edit_rule(edit_code="SAFE-02", category="CLINICAL")
    v1 = create_edit_version(
        rule["id"], severity="DENY",
        claim_types=("INSTITUTIONAL_INPATIENT",),
        logic_expression="deny inpatient line",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z")
    submit_version(v1["id"])
    approve_version(v1["id"], rule["version"], attestation=True)

    v2 = create_edit_version(
        rule["id"], severity="DENY",
        claim_types=("INSTITUTIONAL_INPATIENT",),
        logic_expression="deny inpatient line v2",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-12-01T00:00:00Z", librarian_id="librarian-2")
    submit_version(v2["id"], librarian_id="librarian-2")

    rule_now = get_rule(rule["id"])
    resp = api.approve_edit_version(
        v2["id"],
        {"expected_edit_rule_version": rule_now["version"],
         "clinical_review_attestation": True},
        APPROVER)
    validate_error(resp, ApiErrorId.ERR_EDIT_WINDOW_OVERLAP,
                   expected_status=409)
    # A rejected approve must not advance the rule's version.
    assert get_rule(rule["id"])["version"] == rule_now["version"]
    assert get_version(v2["id"])["status"] == "PENDING_APPROVAL"


def test_edit_window_overlap_rejected_without_bump(api):
    """PRD §3.2: "Finally the window check: the version's half-open
    effectiveness window must not overlap the window of any other `ACTIVE`
    version of the same rule — adjacency, where one window's `effective_from`
    equals another's `effective_to`, is allowed because the end is exclusive —
    and an overlap is rejected with `ERR_EDIT_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.2: "A successful approval marks the version `ACTIVE`, records the
    approver in `approved_by_user_id` — null until the version is first
    approved — recomputes the rule's `active_version_count`, and increments
    the rule's `version` by one."

    Design: Difficulty/resource_temporal_overlap/edit_windows_half_open_adjacency
    """
    rule = create_edit_rule(edit_code="WIN-01", category="POLICY")
    ver_a = create_edit_version(rule["id"], logic_expression="deny line A",
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2026-07-01T00:00:00Z")
    submit_version(ver_a["id"])
    approve_version(ver_a["id"], rule["version"])
    rule_v2 = get_rule(rule["id"])["version"]

    ver_b = create_edit_version(rule["id"], logic_expression="deny line B",
                                effective_from="2026-06-01T00:00:00Z",
                                effective_to="2026-12-01T00:00:00Z")
    submit_version(ver_b["id"])
    resp = api.approve_edit_version(
        ver_b["id"], {"expected_edit_rule_version": rule_v2}, APPROVER)
    validate_error(resp, ApiErrorId.ERR_EDIT_WINDOW_OVERLAP,
                   expected_status=409)

    # The failed approve does not bump the rule version, so the adjacent
    # window C approves with the same expected version.
    ver_c = create_edit_version(rule["id"], logic_expression="deny line C",
                                effective_from="2026-07-01T00:00:00Z",
                                effective_to="2027-01-01T00:00:00Z")
    submit_version(ver_c["id"])
    approved_c = validate_success(api.approve_edit_version(
        ver_c["id"], {"expected_edit_rule_version": rule_v2}, APPROVER))
    assert approved_c["status"] == "ACTIVE"


def test_edit_window_adjacency_allowed_and_counted(api):
    """PRD §3.2: "adjacency, where one window's `effective_from` equals
    another's `effective_to`, is allowed because the end is exclusive"
    PRD §3.2: "The rule's `active_version_count` is maintained across all four
    lifecycle events — approval, suspension, reactivation, and retirement — so
    it always equals the number of the rule's versions currently `ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/edit_windows_half_open_adjacency
    """
    rule = create_edit_rule(edit_code="WIN-02", category="POLICY")
    ver_a = create_edit_version(rule["id"], logic_expression="deny line A",
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2026-07-01T00:00:00Z")
    submit_version(ver_a["id"])
    approve_version(ver_a["id"], rule["version"])

    # Touches A's exclusive end at 2026-07-01: adjacency, not overlap.
    ver_c = create_edit_version(rule["id"], logic_expression="deny line C",
                                effective_from="2026-07-01T00:00:00Z",
                                effective_to="2027-01-01T00:00:00Z")
    submit_version(ver_c["id"])
    approved_c = validate_success(api.approve_edit_version(
        ver_c["id"], {"expected_edit_rule_version": get_rule(rule["id"])["version"]},
        APPROVER))
    assert approved_c["status"] == "ACTIVE"

    rule_after = get_rule(rule["id"])
    assert rule_after["active_version_count"] == 2, (
        "A and C coexist as ACTIVE versions with disjoint windows"
    )
