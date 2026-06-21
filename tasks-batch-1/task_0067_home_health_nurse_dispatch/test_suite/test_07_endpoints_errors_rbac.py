"""Corner: computed-read endpoints, error catalogue, RBAC, and cross-cutting
complexity layers (PRD §2.1, §2.7, §3, §4). Queue B endpoints/errors/rbac/
cross_cutting/consistency sections.
"""
from test_helpers import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import patient_payload
from test_helpers.fixtures import (
    BILLING,
    INTAKE,
    SCHEDULER,
    add_plan,
    file_mileage_claim,
    schedule_confirm_complete,
    schedule_visit,
    setup_active_episode,
    setup_draft_episode,
    setup_finalized_episode,
    set_clock,
)
from test_helpers.test_users import make_clinician_headers

WOUND_RATE = {
    "clinical_group": "WOUND", "base_30day_rate": 2000.00,
    "functional_weight_low": 0.95, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.05, "lupa_threshold": 5,
}
WOUND_OASIS = {"clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2}
MMTA_RATE = {
    "clinical_group": "MMTA_OTHER", "base_30day_rate": 1500.00,
    "functional_weight_low": 1.00, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.00, "lupa_threshold": 1,
}
MMTA_OASIS = {"clinical_group": "MMTA_OTHER", "functional_level": "LOW", "comorbidity_count": 0}


# --- endpoints section ---
def test_list_visits_by_clinician(api):
    """PRD §4: "GET /clinicians/{id}/visits | List visits assigned to a
    clinician". (Reverse-reachability for Visit.clinician_id.)

    Design: Corner/endpoints/list_visits_by_clinician_reverse_reachability
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    v = schedule_visit(ep_id, rn_id, api,
                       scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    rows, _ = validate_paginated(api.list_clinician_visits(rn_id, SCHEDULER))
    assert any(item["id"] == v["id"] for item in rows)


def test_episode_summary_returns_provisional_payment(api):
    """PRD §3.3: "if the planned total is greater than or equal to the episode's
    lupa_threshold, the provisional payment is the case-mix amount multiplied by 2
    (the episode spans two 30-day periods), rounded half-up to two decimal
    places". (Summary surfaces the same provisional_payment, 4452.00.)

    Design: Corner/endpoints/episode_summary_computed_read
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    summary = validate_success(api.get_episode_summary(base["episode"]["id"], BILLING))
    assert summary["provisional_payment"] == 4452.00


# --- errors section ---
def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "If either header is absent, or if X-User-Role is not one of the
    five recognized roles, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    resp = api.create_patient(patient_payload(), headers={})
    validate_error(resp, "ERR_UNAUTHENTICATED", 401)


def test_stale_episode_version_on_plan_create(api):
    """PRD §2.7: "If a different writer has advanced the episode's version since
    the client last read it ... the create is rejected with
    ERR_STALE_EPISODE_VERSION (HTTP 412)".

    Design: Corner/errors/stale_episode_version_on_plan_create
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep_id, v0 = base["episode"]["id"], base["version"]
    add_plan(ep_id, v0, api, planned_rn_visits=6)  # advances version
    resp = api.create_plan(ep_id, {
        "planned_rn_visits": 8, "planned_pt_visits": 0, "planned_ot_visits": 0,
        "planned_slp_visits": 0, "companion_hours_authorized": 0,
        "expected_episode_version": v0,
    }, INTAKE)
    validate_error(resp, "ERR_STALE_EPISODE_VERSION", 412)


def test_reopen_window_closed(api):
    """PRD §3.8: "Reopen is permitted only when the episode has a PaymentLedger
    row that has not already been reversed and the request arrives no later than
    30 days after the finalize event; a request that arrives beyond that 30-day
    window is rejected with ERR_REOPEN_WINDOW_CLOSED (HTTP 422)."

    Design: Corner/errors/reopen_window_closed
    """
    base = setup_finalized_episode(api)
    ep_id = base["episode"]["id"]
    set_clock("2026-04-15T08:00:00Z", api)  # >30 days after 2026-02-03 finalize
    resp = api.reopen_episode(ep_id, BILLING)
    validate_error(resp, "ERR_REOPEN_WINDOW_CLOSED", 422)


# --- rbac section ---
def test_scheduler_cannot_finalize_episode(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation per the authorization rules described
    throughout this document and summarized in §4, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)." PRD §4: finalize is BillingManager-only.

    Design: Corner/rbac/scheduler_cannot_finalize_episode
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 1},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    resp = api.finalize_episode(ep_id, SCHEDULER)
    validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)
    ep = validate_success(api.get_episode(ep_id, INTAKE))
    assert ep["status"] == "ACTIVE"


def test_clinician_cannot_confirm_others_visit(api):
    """PRD §2.1: "for the two clinician-owned actions — confirming a visit and
    completing a visit — the acting X-User-ID must equal the visit's clinician_id;
    a mismatch is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/clinician_cannot_confirm_others_visit
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        rn_overrides={"full_name": "RN A", "discipline": "RN"},
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id, rn_a = base["episode"]["id"], base["rn"]["id"]
    rn_b = validate_success(api.create_clinician(
        {"full_name": "RN B", "discipline": "RN", "license_active": True,
         "base_lat": 40.0, "base_lon": -75.0, "weekly_visit_cap": 40}, SCHEDULER), 201)
    v = schedule_visit(ep_id, rn_a, api,
                       scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    resp = api.confirm_visit(v["id"], make_clinician_headers(rn_b["id"]))
    validate_error(resp, "ERR_NOT_RESOURCE_OWNER", 403)
    fetched = validate_success(api.get_visit(v["id"], SCHEDULER))
    assert fetched["status"] == "SCHEDULED"


# --- cross_cutting_complexity_layers section ---
def test_occ_correct_version_succeeds_and_increments(api):
    """PRD §2.7: "The create-plan-of-care request must carry a non-optional
    expected_episode_version field holding the client's last-observed version of
    the target Episode." PRD §2.6: "creating a new plan of care ... increment
    Episode.version by 1".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep_id, v0 = base["episode"]["id"], base["version"]
    resp = api.create_plan(ep_id, {
        "planned_rn_visits": 6, "planned_pt_visits": 0, "planned_ot_visits": 0,
        "planned_slp_visits": 0, "companion_hours_authorized": 0,
        "expected_episode_version": v0,
    }, INTAKE)
    validate_success(resp, 201)
    ep = validate_success(api.get_episode(ep_id, INTAKE))
    assert ep["version"] == v0 + 1


def test_total_mileage_reimbursed_reconciles(api):
    """PRD §3.6: "The approved reimbursement is then added to the episode's
    running total_mileage_reimbursed, and the claim version is bumped."

    Design: Corner/cross_cutting_complexity_layers/total_mileage_reimbursed_derived_field_reconciliation
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 1},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    visit = schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    claim = file_mileage_claim(visit["id"], rn_id, api, claimed_miles=20.0)
    validate_success(api.approve_mileage_claim(claim["id"], BILLING))
    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["total_mileage_reimbursed"] == 10.05


# --- consistency_model section ---
def test_activate_response_reflects_provisional_payment(api):
    """PRD §3.2: "On success, activation appends an ACTIVATED audit event,
    recomputes the episode's forward-looking provisional payment from the active
    plan, and bumps the episode version." (The activate response carries the
    recomputed 4452.00.)

    Design: Corner/consistency_model/immediate_provisional_payment_visible_in_activate_response
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep_id, v0 = base["episode"]["id"], base["version"]
    add_plan(ep_id, v0, api, planned_rn_visits=6)
    activated = validate_success(api.activate_episode(ep_id, INTAKE))
    assert activated["provisional_payment"] == 4452.00
