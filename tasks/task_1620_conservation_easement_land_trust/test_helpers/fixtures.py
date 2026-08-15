"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the public API —
each test runs against a freshly restarted server with an empty database and
the logical clock at its 2026-08-01T00:00:00Z default (PRD §2.10).

Setup calls use get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_amendment_request_payload,
    create_appraisal_payload,
    create_baseline_report_payload,
    create_easement_payload,
    create_endowment_fund_payload,
    create_landowner_payload,
    create_monitoring_visit_payload,
    create_succession_notice_payload,
    create_use_authorization_payload,
    create_violation_payload,
    deliver_appraisal_payload,
    execute_enforcement_payload,
    post_amount_payload,
    post_draw_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_appraiser_headers,
    make_board_reviewer_headers,
    make_coordinator_headers,
    make_field_monitor_headers,
    make_landowner_headers,
)

ADMIN = TEST_USERS["trust_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
BOARD = TEST_USERS["board_reviewer_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: easement + landowner + baseline chains
# ---------------------------------------------------------------------------

def create_draft_easement(name="Easement", parcel_acreage=500, matrix=None,
                          monitoring_interval_months=None):
    """Create an easement (born DRAFT). Returns the easement dict."""
    payload = create_easement_payload(
        easement_name=name,
        parcel_acreage=parcel_acreage,
        permitted_use_matrix=matrix,
        monitoring_interval_months=monitoring_interval_months,
    )
    return get_success_data(api_client.create_easement(payload, ADMIN))


def create_initial_landowner(easement_id, owner_name="Owner One",
                             contact_email="owner@example.org"):
    """Register the initial ACTIVE landowner on a DRAFT easement."""
    payload = create_landowner_payload(
        easement_id, owner_name=owner_name, contact_email=contact_email
    )
    return get_success_data(api_client.create_landowner(payload, ADMIN))


def create_baseline(easement_id, prepared_by="staff-prep-1", photo_point_count=5,
                    narrative="Intact forest and wetland values documented."):
    """Create the easement's single baseline report (born DRAFT)."""
    payload = create_baseline_report_payload(
        easement_id,
        prepared_by_user_id=prepared_by,
        condition_narrative=narrative,
        photo_point_count=photo_point_count,
    )
    return get_success_data(api_client.create_baseline_report(payload, COORD))


def submit_baseline(baseline_id):
    return get_success_data(api_client.submit_baseline_report(baseline_id, COORD))


def accept_baseline(baseline_id, acceptor_user_id="board-1"):
    headers = make_board_reviewer_headers(acceptor_user_id)
    return get_success_data(api_client.accept_baseline_report(baseline_id, headers))


def create_accepted_baseline(easement_id, prepared_by="staff-prep-1",
                             photo_point_count=5, acceptor_user_id="board-1"):
    """Baseline driven DRAFT -> SUBMITTED -> ACCEPTED."""
    baseline = create_baseline(
        easement_id, prepared_by=prepared_by, photo_point_count=photo_point_count
    )
    submit_baseline(baseline["id"])
    return accept_baseline(baseline["id"], acceptor_user_id=acceptor_user_id)


def create_recorded_easement(name="Easement", parcel_acreage=500, matrix=None,
                             monitoring_interval_months=12,
                             preparer="staff-prep-1", acceptor_user_id="board-1",
                             photo_point_count=None):
    """Full recordation chain: easement -> initial landowner -> baseline ->
    submit -> accept -> record.

    Returns dict(easement=<recorded easement>, landowner=..., baseline=...,
    version=<easement version after recordation>). The photo-point default is
    max(4, ceil(acreage/100)) so submission always clears the completeness bar.
    """
    if photo_point_count is None:
        photo_point_count = max(4, -(-parcel_acreage // 100))
    easement = create_draft_easement(
        name=name,
        parcel_acreage=parcel_acreage,
        matrix=matrix,
        monitoring_interval_months=monitoring_interval_months,
    )
    landowner = create_initial_landowner(easement["id"])
    baseline = create_accepted_baseline(
        easement["id"], prepared_by=preparer,
        photo_point_count=photo_point_count, acceptor_user_id=acceptor_user_id,
    )
    recorded = get_success_data(api_client.record_easement(easement["id"], ADMIN))
    return {
        "easement": recorded,
        "landowner": landowner,
        "baseline": baseline,
        "version": recorded["version"],
    }


def get_easement(easement_id):
    return get_success_data(api_client.get_easement(easement_id, ADMIN))


def easement_version(easement_id):
    return get_easement(easement_id)["version"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Set the server's logical clock and run the scheduled sweep."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# ---------------------------------------------------------------------------
# Monitoring visits
# ---------------------------------------------------------------------------

def schedule_visit(easement_id, monitor_user_id="mon-1",
                   window_start_on="2026-09-01", window_end_on="2026-09-10"):
    payload = create_monitoring_visit_payload(
        easement_id,
        monitor_user_id=monitor_user_id,
        window_start_on=window_start_on,
        window_end_on=window_end_on,
    )
    return get_success_data(api_client.create_monitoring_visit(payload, COORD))


# ---------------------------------------------------------------------------
# Violations & enforcement
# ---------------------------------------------------------------------------

def create_open_violation(easement_id, violation_type="SUBDIVISION", severity="MINOR",
                          detected_by="coord-9", detected_on="2026-08-02",
                          monitoring_visit_id=None):
    payload = create_violation_payload(
        easement_id,
        detected_by_user_id=detected_by,
        violation_type=violation_type,
        severity=severity,
        detected_on=detected_on,
        monitoring_visit_id=monitoring_visit_id,
    )
    return get_success_data(api_client.create_violation(payload, COORD))


def setup_open_violation(severity="MINOR", violation_type="SUBDIVISION",
                         detected_by="coord-9", detected_on="2026-08-02",
                         parcel_acreage=100, matrix=None, clock=None):
    """Recorded easement plus one OPEN violation.

    Returns dict(easement, landowner, violation, version).
    """
    ctx = create_recorded_easement(parcel_acreage=parcel_acreage, matrix=matrix)
    if clock is not None:
        set_clock(clock)
    violation = create_open_violation(
        ctx["easement"]["id"], violation_type=violation_type, severity=severity,
        detected_by=detected_by, detected_on=detected_on,
    )
    return {**ctx, "violation": violation}


def setup_violation_notice_sent(**kwargs):
    """OPEN violation escalated one step: notice served (NOTICE_SENT)."""
    ctx = setup_open_violation(**kwargs)
    violation = get_success_data(
        api_client.send_violation_notice(ctx["violation"]["id"], COORD)
    )
    ctx["violation"] = violation
    return ctx


def setup_violation_cure_in_progress(**kwargs):
    """NOTICE_SENT violation with the current landowner curing it."""
    ctx = setup_violation_notice_sent(**kwargs)
    violation = get_success_data(
        api_client.start_violation_cure(
            ctx["violation"]["id"],
            make_landowner_headers(ctx["landowner"]["id"]),
        )
    )
    ctx["violation"] = violation
    return ctx


def list_enforcement_actions(params=None):
    resp = api_client.list_enforcement_actions(ADMIN, params=params)
    data, _meta = validate_paginated(resp)
    return data


def the_only_enforcement_action():
    """In a freshly restarted database the escalated violation spawns exactly
    one enforcement action, so the unfiltered list has exactly one entry."""
    actions = list_enforcement_actions()
    assert len(actions) == 1, f"expected exactly one enforcement action, got {len(actions)}"
    return actions[0]


def setup_escalated_violation(severity="MATERIAL", violation_type="SUBDIVISION",
                              detected_by="coord-9", detected_on="2026-08-02",
                              parcel_acreage=100, matrix=None, clock=None):
    """Recorded easement + violation manually escalated from NOTICE_SENT.

    Returns dict(..., violation, enforcement_action) with the spawned PROPOSED
    enforcement action attached.
    """
    ctx = setup_violation_notice_sent(
        severity=severity, violation_type=violation_type, detected_by=detected_by,
        detected_on=detected_on, parcel_acreage=parcel_acreage, matrix=matrix,
        clock=clock,
    )
    violation = get_success_data(
        api_client.escalate_violation(ctx["violation"]["id"], COORD)
    )
    ctx["violation"] = violation
    ctx["enforcement_action"] = the_only_enforcement_action()
    return ctx


# ---------------------------------------------------------------------------
# Use authorizations
# ---------------------------------------------------------------------------

def create_requested_use_authorization(easement_id, landowner_id,
                                       use_type="TIMBER_HARVEST",
                                       justification="Selective thinning"):
    payload = create_use_authorization_payload(
        easement_id, use_type=use_type, justification=justification
    )
    return get_success_data(
        api_client.create_use_authorization(payload, make_landowner_headers(landowner_id))
    )


# ---------------------------------------------------------------------------
# Amendments
# ---------------------------------------------------------------------------

def create_submitted_amendment(easement_id, expected_easement_version,
                               requested_changes=None, affected_acreage=100,
                               submitted_by="coord-1"):
    if requested_changes is None:
        requested_changes = [{"use_type": "SUBDIVISION", "new_level": "DISCRETIONARY"}]
    payload = create_amendment_request_payload(
        easement_id,
        expected_easement_version,
        submitted_by_user_id=submitted_by,
        requested_changes=requested_changes,
        affected_acreage=affected_acreage,
    )
    return get_success_data(api_client.create_amendment_request(payload, COORD))


# ---------------------------------------------------------------------------
# Succession
# ---------------------------------------------------------------------------

def create_succession_notice(easement_id, landowner_id,
                             successor_owner_name="Owner Two",
                             successor_contact_email="successor@example.org",
                             transfer_on="2026-09-15"):
    payload = create_succession_notice_payload(
        easement_id,
        successor_owner_name=successor_owner_name,
        successor_contact_email=successor_contact_email,
        transfer_on=transfer_on,
    )
    return get_success_data(
        api_client.create_succession_notice(payload, make_landowner_headers(landowner_id))
    )


# ---------------------------------------------------------------------------
# Appraisals
# ---------------------------------------------------------------------------

def create_engaged_appraisal(easement_id, appraiser_user_id="appr-1",
                             effective_on="2026-08-15", gift_on="2026-09-01",
                             contiguous_enhancement_applies=False):
    payload = create_appraisal_payload(
        easement_id,
        appraiser_user_id=appraiser_user_id,
        effective_on=effective_on,
        gift_on=gift_on,
        contiguous_enhancement_applies=contiguous_enhancement_applies,
    )
    return get_success_data(api_client.create_appraisal(payload, COORD))


def deliver_appraisal(appraisal_id, appraiser_user_id, before_value_cents=90000000,
                      after_value_cents=55000000, enhancement_value_cents=None):
    payload = deliver_appraisal_payload(
        before_value_cents=before_value_cents,
        after_value_cents=after_value_cents,
        enhancement_value_cents=enhancement_value_cents,
    )
    return get_success_data(
        api_client.deliver_appraisal(
            appraisal_id, payload, make_appraiser_headers(appraiser_user_id)
        )
    )


def setup_delivered_appraisal(appraiser_user_id="appr-1", effective_on="2026-08-15",
                              gift_on="2026-09-01", contiguous_enhancement_applies=False,
                              before_value_cents=90000000, after_value_cents=55000000,
                              enhancement_value_cents=None, preparer="staff-prep-1"):
    """Recorded easement plus a DELIVERED appraisal. Returns dict(..., appraisal)."""
    ctx = create_recorded_easement(parcel_acreage=100, matrix={"AGRICULTURE": "PERMITTED"},
                                   preparer=preparer)
    appraisal = create_engaged_appraisal(
        ctx["easement"]["id"], appraiser_user_id=appraiser_user_id,
        effective_on=effective_on, gift_on=gift_on,
        contiguous_enhancement_applies=contiguous_enhancement_applies,
    )
    appraisal = deliver_appraisal(
        appraisal["id"], appraiser_user_id,
        before_value_cents=before_value_cents, after_value_cents=after_value_cents,
        enhancement_value_cents=enhancement_value_cents,
    )
    return {**ctx, "appraisal": appraisal}


# ---------------------------------------------------------------------------
# Endowment funds & ledger
# ---------------------------------------------------------------------------

def create_fund(easement_id, spending_rate_bps=400, principal_floor_cents=100000):
    payload = create_endowment_fund_payload(
        easement_id,
        spending_rate_bps=spending_rate_bps,
        principal_floor_cents=principal_floor_cents,
    )
    return get_success_data(api_client.create_endowment_fund(payload, ADMIN))


def setup_active_fund(spending_rate_bps=400, principal_floor_cents=100000,
                      contribution_cents=500000, parcel_acreage=500):
    """Easement + fund + first contribution (fund becomes ACTIVE).

    Fund creation needs only the easement's easement_id — the recordation gate
    of PRD §3.1 lists monitoring visits, violations, amendments, use
    authorizations, succession notices, and appraisals; the endowment is not
    among them.

    Returns dict(easement, fund, contribution_txn).
    """
    easement = create_draft_easement(parcel_acreage=parcel_acreage,
                                     matrix={"AGRICULTURE": "PERMITTED",
                                             "SUBDIVISION": "PROHIBITED"})
    fund = create_fund(easement["id"], spending_rate_bps=spending_rate_bps,
                       principal_floor_cents=principal_floor_cents)
    txn = post_contribution(fund["id"], contribution_cents)
    fund = get_fund(fund["id"])
    return {"easement": easement, "fund": fund, "contribution_txn": txn}


def get_fund(fund_id):
    return get_success_data(api_client.get_endowment_fund(fund_id, ADMIN))


def fund_version(fund_id):
    return get_fund(fund_id)["version"]


def post_contribution(fund_id, amount_cents):
    return get_success_data(
        api_client.post_contribution(fund_id, post_amount_payload(amount_cents), ADMIN)
    )


def post_return(fund_id, amount_cents):
    return get_success_data(
        api_client.post_return(fund_id, post_amount_payload(amount_cents), ADMIN)
    )


def post_draw(fund_id, amount_cents, purpose, expected_fund_version,
              actor="coordinator", actor_user_id=None):
    if actor == "board":
        headers = make_board_reviewer_headers(actor_user_id or "board-1")
    else:
        headers = make_coordinator_headers(actor_user_id or "coord-1")
    return get_success_data(
        api_client.post_draw(
            fund_id, post_draw_payload(amount_cents, purpose, expected_fund_version),
            headers,
        )
    )


def close_fund_year(fund_id):
    return get_success_data(api_client.close_fund_year(fund_id, BOARD))


def list_fund_transactions(fund_id, params=None):
    resp = api_client.list_fund_transactions(fund_id, ADMIN, params=params)
    data, _meta = validate_paginated(resp)
    return data
