"""Stage gates, cross-entity preconditions, and validation-priority precedence."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    create_draft_project,
    add_milestone,
    setup_studio_client,
    create_project_in_concept,
    create_presented_concept,
    create_license_payload,
    create_change_order_payload,
    setup_open_care_cycle,
    set_clock,
)

SO = TEST_USERS["studio_ops_headers"]
DES = TEST_USERS["designer_headers"]
BO = TEST_USERS["billing_ops_headers"]


# --- cross_entity_state_dependency (difficulty) ---

def test_advance_to_delivery_blocked_until_concept_approved(api):
    """PRD §3.4: "This advance requires that at least one concept on the project has
    reached APPROVED; if none has, it is rejected with ERR_NO_APPROVED_CONCEPT."

    Design: Difficulty/cross_entity_state_dependency/project_concept_to_delivery_requires_approved_concept
    """
    studio, client, project, _ = create_project_in_concept([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    con = create_presented_concept(sid, pid, cid)  # PRESENTED, not approved

    resp = api.advance_project(sid, pid, SO)
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_CONCEPT.value)


def test_advance_to_delivery_succeeds_after_concept_approved(api):
    """PRD §3.4: "The client may approve, moving the concept from PRESENTED to
    APPROVED — a terminal state — which makes the parent project eligible to advance
    out of the concept phase."

    Design: Difficulty/cross_entity_state_dependency/project_concept_to_delivery_requires_approved_concept
    """
    studio, client, project, _ = create_project_in_concept([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    con = create_presented_concept(sid, pid, cid)
    get_success_data(api.approve_concept(sid, pid, con["id"], make_client_headers(cid)))
    advanced = validate_success(api.advance_project(sid, pid, SO))
    assert advanced["status"] == "DELIVERY"


def test_retainer_pause_blocked_by_open_cycle_then_allowed_after_close(api):
    """PRD §3.10: "Both pausing and cancelling are blocked while any care cycle on
    the retainer is still OPEN: such an attempt is rejected with ERR_OPEN_CYCLE."

    Design: Difficulty/cross_entity_state_dependency/retainer_pause_blocked_by_open_care_cycle
    """
    sid, retainer, cc = setup_open_care_cycle(
        period_start="2026-03-01T00:00:00Z", period_end="2026-04-01T00:00:00Z", hours_used=5,
    )
    rid = retainer["id"]
    resp = api.pause_retainer(sid, rid, SO)
    validate_error(resp, ApiErrorId.ERR_OPEN_CYCLE.value)

    set_clock("2026-04-01T00:00:00Z", SO)
    get_success_data(api.close_care_cycle(sid, rid, cc["id"], SO))
    paused = validate_success(api.pause_retainer(sid, rid, SO))
    assert paused["status"] == "PAUSED"


def test_retainer_pause_rejected_while_cycle_open(api):
    """PRD §3.10: "such an attempt is rejected with ERR_OPEN_CYCLE."

    Design: Difficulty/cross_entity_state_dependency/retainer_pause_blocked_by_open_care_cycle
    """
    sid, retainer, cc = setup_open_care_cycle(
        period_start="2026-03-01T00:00:00Z", period_end="2026-04-01T00:00:00Z", hours_used=5,
    )
    resp = api.pause_retainer(sid, retainer["id"], SO)
    validate_error(resp, ApiErrorId.ERR_OPEN_CYCLE.value)


# --- priority_pair_validation_conflict (difficulty) ---

def test_occ_stale_version_beats_activation_check_on_change_order_create(api):
    """PRD §2.7: "Before the change order is created, the server compares
    expected_project_version against the project's current version. If they do not
    match ... the creation is rejected with ERR_STALE_PROJECT_VERSION and HTTP
    status 412"
    PRD §2.12: "Only after these gates do the resource-specific checks run: the
    change-order concurrency check (ERR_STALE_PROJECT_VERSION), then the generic
    'is this transition defined from the current state' check (ERR_INVALID_STATE),
    then cross-stage gating (ERR_PROJECT_WRONG_STAGE)"

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_wrong_stage_on_change_order_create
    """
    studio, client = setup_studio_client()
    sid = studio["id"]
    project = create_draft_project(sid, client["id"], deposit_pct=0.30)
    pid, pv0 = project["id"], project["version"]
    # Recording a deposit mutates the project (deposit_collected_cents) and so
    # bumps Project.version per PRD §2.4; pv0 — the version the client last
    # observed — is now stale.
    get_success_data(api.record_deposit(sid, pid, {"amount_cents": 5000}, BO))

    resp = api.create_change_order(
        sid, create_change_order_payload(pid, 5000, pv0, reason="SCOPE_ADD"), SO
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)


def test_occ_stale_version_returns_412_not_activation_error(api):
    """PRD §2.7: "the creation is rejected with ERR_STALE_PROJECT_VERSION and HTTP
    status 412, and the client must re-read the project before proposing a new
    amount."

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_wrong_stage_on_change_order_create
    """
    studio, client = setup_studio_client()
    sid = studio["id"]
    project = create_draft_project(sid, client["id"], deposit_pct=0.30)
    pid, pv0 = project["id"], project["version"]
    # Recording a deposit bumps Project.version per PRD §2.4, so pv0 is stale.
    get_success_data(api.record_deposit(sid, pid, {"amount_cents": 5000}, BO))
    resp = api.create_change_order(
        sid, create_change_order_payload(pid, 5000, pv0, reason="SCOPE_ADD"), SO
    )
    body = validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)
    assert body["error_id"] != ApiErrorId.ERR_PROJECT_NOT_ACTIVATED.value


def test_license_overlap_and_revision_limit_yield_distinct_errors(api):
    """PRD §2.10: "two license windows on the same project overlap if they share any
    instant, and a creation that would overlap an existing project license is
    rejected with ERR_INTERVAL_OVERLAP."
    PRD §3.4: "If the concept has already used as many rounds as its effective limit
    allows, the request is rejected with ERR_REVISION_LIMIT_REACHED."

    Design: Difficulty/priority_pair_validation_conflict/interval_overlap_beats_revision_limit_distinct_category_pair
    """
    # Probe A: license overlap
    studio, client, project, _ = create_project_in_concept([20000], deposit_pct=0.30, service_type="WEB")
    sid, pid, cid = studio["id"], project["id"], client["id"]
    get_success_data(api.create_license(
        sid, create_license_payload(pid, "2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z", kind="STOCK", cost_cents=1000), SO
    ))
    resp_a = api.create_license(
        sid, create_license_payload(pid, "2026-03-05T00:00:00Z", "2026-03-15T00:00:00Z", kind="FONT", cost_cents=1000), SO
    )
    validate_error(resp_a, ApiErrorId.ERR_INTERVAL_OVERLAP.value)

    # Probe B: revision limit reached on the same project's concept (revision_limit=1)
    con = create_presented_concept(sid, pid, cid, revision_limit=1)
    ch = make_client_headers(cid)
    get_success_data(api.request_concept_revision(sid, pid, con["id"], ch))  # rounds_used -> 1
    get_success_data(api.present_concept(sid, pid, con["id"], DES))
    resp_b = api.request_concept_revision(sid, pid, con["id"], ch)
    validate_error(resp_b, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)


def test_revision_limit_distinct_from_interval_overlap(api):
    """PRD §3.4: "A revision request is permitted only while the concept's current
    rounds_used is strictly less than that effective revision limit; the comparison
    uses the count before this round is added."

    Design: Difficulty/priority_pair_validation_conflict/interval_overlap_beats_revision_limit_distinct_category_pair
    """
    studio, client, project, _ = create_project_in_concept([20000], deposit_pct=0.30, service_type="WEB")
    sid, pid, cid = studio["id"], project["id"], client["id"]
    con = create_presented_concept(sid, pid, cid, revision_limit=1)
    ch = make_client_headers(cid)
    get_success_data(api.request_concept_revision(sid, pid, con["id"], ch))
    get_success_data(api.present_concept(sid, pid, con["id"], DES))
    resp = api.request_concept_revision(sid, pid, con["id"], ch)
    body = validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)
    assert body["error_id"] != ApiErrorId.ERR_INTERVAL_OVERLAP.value


# --- boundary_precision_check: revision counter (difficulty) ---

def test_revision_request_at_exact_effective_limit_rejected(api):
    """PRD §3.4: "If the concept has already used as many rounds as its effective
    limit allows, the request is rejected with ERR_REVISION_LIMIT_REACHED."

    Design: Difficulty/boundary_precision_check/revision_request_at_exact_effective_limit_boundary
    """
    studio, client, project, _ = create_project_in_concept([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    con = create_presented_concept(sid, pid, cid, revision_limit=2)
    ch = make_client_headers(cid)
    # take two revision rounds -> rounds_used == 2 == limit
    get_success_data(api.request_concept_revision(sid, pid, con["id"], ch))
    get_success_data(api.present_concept(sid, pid, con["id"], DES))
    get_success_data(api.request_concept_revision(sid, pid, con["id"], ch))
    get_success_data(api.present_concept(sid, pid, con["id"], DES))

    resp = api.request_concept_revision(sid, pid, con["id"], ch)
    validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)


def test_rejected_revision_does_not_increment_rounds_used(api):
    """PRD §3.4: "the comparison uses the count before this round is added."

    Design: Difficulty/boundary_precision_check/revision_request_at_exact_effective_limit_boundary
    """
    studio, client, project, _ = create_project_in_concept([10000], deposit_pct=0.30)
    sid, pid, cid = studio["id"], project["id"], client["id"]
    con = create_presented_concept(sid, pid, cid, revision_limit=2)
    ch = make_client_headers(cid)
    get_success_data(api.request_concept_revision(sid, pid, con["id"], ch))
    get_success_data(api.present_concept(sid, pid, con["id"], DES))
    get_success_data(api.request_concept_revision(sid, pid, con["id"], ch))
    get_success_data(api.present_concept(sid, pid, con["id"], DES))
    api.request_concept_revision(sid, pid, con["id"], ch)  # rejected
    con_after = validate_success(api.get_concept(sid, pid, con["id"], SO))
    assert con_after["rounds_used"] == 2, "rejected request did not increment"
