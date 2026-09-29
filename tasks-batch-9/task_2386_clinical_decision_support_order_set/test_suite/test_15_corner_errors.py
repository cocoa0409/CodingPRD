"""Error coverage: each refusal reached on its own terms.

Every probe below drives one refusal family to its documented code and then
proves the refusal was inert — the target keeps its state, its version and its
counters, and no side record appears. Where two codes are close neighbours the
probe fires both so the distinction is visible.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assertions,
    factories,
    fixtures,
    make_clinical_sponsor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PASSIVE_ALERT_REQUEST = {
    "title": "Passive advisory bundle",
    "clinical_domain": "INTERNAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "evidence_citations": [
        factories.build_citation("Guideline A 2022", True),
        factories.build_citation("Guideline B 2023", True),
    ],
}


def _passive_alert(name: str, expression: str) -> dict:
    return {
        "name": name,
        "severity_tier": "TIER_3_PASSIVE",
        "override_reason_required": False,
        "override_reason_codes": [],
        "firing_criteria": {"trigger_event": "ORDER_ENTRY", "expression": expression},
    }


# ---------------------------------------------------------------------------
# The 404 family
# ---------------------------------------------------------------------------


def test_every_resource_family_answers_an_unknown_id_with_its_own_code(committee):
    """Ten routes, ten distinct not-found codes, and nothing touched.

    "Each collection has its own not-found code: a content request path yields
    `ERR_CONTENT_REQUEST_NOT_FOUND`, an order set path `ERR_ORDER_SET_NOT_FOUND`, an
    alert path `ERR_ALERT_NOT_FOUND`, a nested burden window
    `ERR_BURDEN_WINDOW_NOT_FOUND`, a review assignment
    `ERR_REVIEW_ASSIGNMENT_NOT_FOUND`, a vendor release
    `ERR_VENDOR_RELEASE_NOT_FOUND`, a vendor rule delta
    `ERR_VENDOR_RULE_DELTA_NOT_FOUND`, a downtime event
    `ERR_DOWNTIME_EVENT_NOT_FOUND`, an adherence measurement
    `ERR_ADHERENCE_MEASUREMENT_NOT_FOUND`, an annual review task
    `ERR_ANNUAL_REVIEW_TASK_NOT_FOUND`, and a clinician
    `ERR_CLINICIAN_NOT_FOUND`." "When a path carries more than one identifier, the
    identifiers are resolved strictly left to right and the first one that resolves
    to nothing determines the 404."

    Design: Corner/errors/error_unknown_ids_on_each_resource_return_the_matching_not_found_code
    """
    fixtures.reset_clock()
    # one real alert so the nested window route has an existing left-hand parent
    scenario = fixtures.setup_draft_alert(
        committee,
        request_overrides=PASSIVE_ALERT_REQUEST,
        alert_overrides=_passive_alert("Placeholder advisory", "always_false"),
    )
    alert_id = scenario["alert"]["id"]
    chair = committee["chair_headers"]
    missing = NON_EXISTENT_UUID

    validate_error(
        api_client.get_clinician(missing, chair), ApiErrorId.ERR_CLINICIAN_NOT_FOUND, 404
    )
    validate_error(
        api_client.get_content_request(missing, chair),
        ApiErrorId.ERR_CONTENT_REQUEST_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_order_set(missing, chair), ApiErrorId.ERR_ORDER_SET_NOT_FOUND, 404
    )
    validate_error(
        api_client.get_alert(missing, chair), ApiErrorId.ERR_ALERT_NOT_FOUND, 404
    )
    # the alert resolves; the window does not, so the window owns the 404
    validate_error(
        api_client.close_burden_window(
            alert_id, missing, factories.build_close_window_payload(), chair
        ),
        ApiErrorId.ERR_BURDEN_WINDOW_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_review_assignment(missing, chair),
        ApiErrorId.ERR_REVIEW_ASSIGNMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_vendor_release(missing, chair),
        ApiErrorId.ERR_VENDOR_RELEASE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.disposition_vendor_rule_delta(
            missing, factories.build_disposition_payload("ACCEPT"), chair
        ),
        ApiErrorId.ERR_VENDOR_RULE_DELTA_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_downtime_event(missing, chair),
        ApiErrorId.ERR_DOWNTIME_EVENT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.finalize_adherence_measurement(
            missing, factories.build_finalize_measurement_payload("REVISE"), chair
        ),
        ApiErrorId.ERR_ADHERENCE_MEASUREMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_annual_review_task(missing, chair),
        ApiErrorId.ERR_ANNUAL_REVIEW_TASK_NOT_FOUND,
        404,
    )

    untouched = fixtures.read_alert(committee, alert_id)
    assert untouched["version"] == 1
    assertions.assert_alert_states(untouched, "DRAFT", "UNPUBLISHED")


# ---------------------------------------------------------------------------
# Authentication ahead of everything else
# ---------------------------------------------------------------------------


def test_a_call_with_no_principal_header_is_unauthenticated_not_invalid():
    """The 401 wins even though the body would also fail the schema check.

    "A request that omits either header, or whose `X-User-ID` names no registered
    clinician, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This check runs
    before everything else — before path resolution included — so an unauthenticated
    call against an identifier that does not exist returns 401 and never 404."
    "**Authentication** — `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    Design: Corner/errors/error_missing_x_user_id_header_returns_unauthenticated
    """
    fixtures.reset_clock()

    response = api_client.create_content_request({}, {})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    _rows, meta = validate_paginated(
        api_client.list_content_requests(fixtures.ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Interval bounds
# ---------------------------------------------------------------------------


def test_a_downtime_window_must_be_strictly_longer_than_nothing():
    """Equal bounds and inverted bounds are the same refusal.

    "`window_end` must be strictly after `window_start`, or the request is refused
    with `ERR_INVALID_WINDOW_BOUNDS`." "**Interval bounds** —
    `ERR_INVALID_WINDOW_BOUNDS` (422) when an interval's start is not strictly before
    its end." "unlike burden windows, downtime intervals are treated as **closed**,
    so events whose endpoints merely touch do conflict, and the rejection is
    `ERR_DOWNTIME_WINDOW_OVERLAP`."

    Design: Corner/errors/error_zero_length_downtime_window_is_rejected
    """
    fixtures.reset_clock()

    zero_length = api_client.create_downtime_event(
        factories.build_downtime_event_payload(
            "2026-08-10T02:00:00Z",
            "2026-08-10T02:00:00Z",
            reason="Zero length by mistake",
        ),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(zero_length, ApiErrorId.ERR_INVALID_WINDOW_BOUNDS, 422)

    inverted = api_client.create_downtime_event(
        factories.build_downtime_event_payload(
            "2026-08-10T04:00:00Z",
            "2026-08-10T02:00:00Z",
            reason="Inverted by mistake",
        ),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(inverted, ApiErrorId.ERR_INVALID_WINDOW_BOUNDS, 422)

    # neither refusal left a record behind: a window touching both rejected
    # intervals is accepted, which a stored predecessor would have blocked
    accepted = fixtures.schedule_downtime(
        "2026-08-10T02:00:00Z", "2026-08-10T04:00:00Z", reason="The real maintenance slot"
    )
    assert accepted["state"] == "SCHEDULED"
    assert accepted["blocked_mutation_count"] == 0


# ---------------------------------------------------------------------------
# The two release gates
# ---------------------------------------------------------------------------


BRIDGE_REQUEST = {
    "title": "Anticoagulation bridge",
    "request_type": "BOTH",
    "clinical_domain": "CARDIOLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "evidence_citations": [
        factories.build_citation("CHEST 2020 bridging", True),
        factories.build_citation("Local protocol", False),
    ],
}


def test_neither_artifact_may_be_released_before_its_review_finishes(committee):
    """The order set and the alert each refuse with their own 409.

    "the order set's `publication_state` must be `UNPUBLISHED` and its `review_state`
    must be `APPROVED`, and a failure of either is `ERR_ORDER_SET_NOT_APPROVED`". "It
    takes an optional `activation_note`, and requires `lifecycle_state` `UNPUBLISHED`
    and `review_state` `APPROVED` — a failure of either is `ERR_ALERT_NOT_APPROVED`."

    Design: Corner/errors/error_publish_and_activate_before_approval_are_rejected
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_peer_review(
        committee,
        request_overrides=BRIDGE_REQUEST,
        order_set_overrides={"name": "Bridge protocol v1", "specialty": "CARDIOLOGY"},
        item_payloads=[
            factories.build_order_set_item_payload(
                orderable_code="MED-ENOX",
                display_name="Enoxaparin bridge",
                item_category="MEDICATION",
                sequence_index=1,
            )
        ],
    )
    order_set_id = scenario["order_set"]["id"]
    alert = fixtures.design_alert(
        committee,
        scenario["content_request"],
        **_passive_alert("Bridge advisory", "warfarin_hold and no_bridge_order"),
    )

    publication = api_client.publish_order_set(
        order_set_id,
        factories.build_publish_payload("2026-08-15T00:00:00Z"),
        committee["chair_headers"],
    )
    validate_error(publication, ApiErrorId.ERR_ORDER_SET_NOT_APPROVED, 409)

    activation = api_client.activate_alert(
        alert["id"],
        factories.build_activation_payload(activation_note="Too early"),
        committee["chair_headers"],
    )
    validate_error(activation, ApiErrorId.ERR_ALERT_NOT_APPROVED, 409)

    unpublished = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(unpublished, "PEER_REVIEW", "UNPUBLISHED")
    assert unpublished["go_live_at"] is None
    assert unpublished["review_due_date"] is None

    inert = fixtures.read_alert(committee, alert["id"])
    assertions.assert_alert_states(inert, "DRAFT", "UNPUBLISHED")
    # PRD §3.3/§3.5 declare no `activated_at` on an Alert (only on
    # VendorContentRelease and DowntimeEvent), so nothing is asserted about it.
    assert inert["review_due_date"] is None
    assert inert["expiration_at"] is None

    _tasks, meta = validate_paginated(
        api_client.list_annual_review_tasks(committee["chair_headers"])
    )
    # no review cycle opens until an artifact actually reaches production
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# The alert lifecycle pair
# ---------------------------------------------------------------------------


def test_suspend_needs_an_active_alert_and_resume_needs_a_suspended_one(committee):
    """Two opposite refusals, and the pause counter never leaves zero.

    "suspending an alert that is not `ACTIVE` is `ERR_ALERT_NOT_ACTIVE`." "Resuming
    reverses the pause: with an optional `resume_note`, an alert moves `SUSPENDED →
    ACTIVE` and `suspension_reason` is cleared, provided `lifecycle_state` is
    `SUSPENDED` (otherwise `ERR_ALERT_NOT_SUSPENDED`)". "with `approval_cast_count`,
    `lifetime_fire_count`, `windowed_fire_count`, `unwindowed_fire_count`,
    `lifetime_override_count`, `suspension_count` and `restage_count` all at 0."

    Design: Corner/errors/error_alert_lifecycle_guards_reject_suspend_before_activation_and_resume_while_active
    """
    fixtures.reset_clock()
    content_request = fixtures.setup_accepted_request(
        committee, request_type="ALERT", **PASSIVE_ALERT_REQUEST
    )
    idle = fixtures.design_alert(
        committee, content_request, **_passive_alert("Never activated advisory", "flag_a")
    )
    live = fixtures.design_alert(
        committee, content_request, **_passive_alert("Activated advisory", "flag_b")
    )
    fixtures.run_alert_approval_stage(committee, live["id"])
    activated = fixtures.activate_alert(committee, live["id"], activation_note="Go live")
    assertions.assert_alert_states(activated, "APPROVED", "ACTIVE")

    suspension = api_client.suspend_alert(
        idle["id"],
        factories.build_suspend_payload(suspension_reason="Never went live"),
        committee["chair_headers"],
    )
    validate_error(suspension, ApiErrorId.ERR_ALERT_NOT_ACTIVE, 409)

    resumption = api_client.resume_alert(
        live["id"],
        factories.build_resume_payload(resume_note="Already running"),
        committee["chair_headers"],
    )
    validate_error(resumption, ApiErrorId.ERR_ALERT_NOT_SUSPENDED, 409)

    never_ran = fixtures.read_alert(committee, idle["id"])
    assertions.assert_alert_states(never_ran, "DRAFT", "UNPUBLISHED")
    assert never_ran["suspension_count"] == 0

    still_running = fixtures.read_alert(committee, live["id"])
    assertions.assert_alert_states(still_running, "APPROVED", "ACTIVE")
    assert still_running["suspension_count"] == 0
    assert still_running["suspension_reason"] is None


# ---------------------------------------------------------------------------
# The three burden-window guards
# ---------------------------------------------------------------------------


def test_the_window_guards_tell_closed_from_open_from_blocked(committee):
    """A double close, a double reopen, and a reopen blocked by a sibling.

    "closing a window that is already `CLOSED` or `FINALIZED` is refused with
    `ERR_BURDEN_WINDOW_NOT_OPEN`." "A window may only be reopened from `CLOSED` —
    `OPEN` or `FINALIZED` yields `ERR_BURDEN_WINDOW_NOT_CLOSED` — and only while no
    other window of the same alert is `OPEN`, or the request is refused with
    `ERR_ANOTHER_WINDOW_OPEN`." "An existing `OPEN` window is never an overlap
    conflict — opening a new window legitimately supersedes it, closing that
    predecessor with `closure_reason` `SUPERSEDED_BY_NEW_WINDOW` and computing its
    burden index in the process."

    Design: Corner/errors/error_burden_window_guards_reject_double_close_double_reopen_and_reopen_while_another_is_open
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee,
        request_overrides={**PASSIVE_ALERT_REQUEST, "title": "Passive advisory for windows"},
        alert_overrides=_passive_alert("Window guard advisory", "flag_c"),
    )
    alert_id = scenario["alert"]["id"]
    first = fixtures.open_window(
        committee, alert_id, "2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"
    )

    closed = validate_success(
        api_client.close_burden_window(
            alert_id,
            first["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        )
    )
    assert closed["state"] == "CLOSED"
    validate_error(
        api_client.close_burden_window(
            alert_id,
            first["id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            fixtures.ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_BURDEN_WINDOW_NOT_OPEN,
        409,
    )

    reopened = validate_success(
        api_client.reopen_burden_window(
            alert_id,
            first["id"],
            factories.build_reopen_window_payload(reopen_reason="Ledger correction"),
            fixtures.ADMIN_HEADERS,
        )
    )
    assert reopened["state"] == "OPEN"
    assert reopened["reopen_count"] == 1
    validate_error(
        api_client.reopen_burden_window(
            alert_id,
            first["id"],
            factories.build_reopen_window_payload(reopen_reason="Second attempt"),
            fixtures.ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_BURDEN_WINDOW_NOT_CLOSED,
        409,
    )

    second = fixtures.open_window(
        committee, alert_id, "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z"
    )
    assert second["state"] == "OPEN"

    # the first window is genuinely CLOSED again, so the refusal names the sibling
    validate_error(
        api_client.reopen_burden_window(
            alert_id,
            first["id"],
            factories.build_reopen_window_payload(reopen_reason="Third attempt"),
            fixtures.ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_ANOTHER_WINDOW_OPEN,
        409,
    )

    open_windows, open_meta = validate_paginated(
        api_client.list_burden_windows(alert_id, committee["chair_headers"], {"state": "OPEN"})
    )
    assert open_meta["total_count"] == 1
    assert open_windows[0]["id"] == second["id"]

    by_id = {window["id"]: window for window in fixtures.read_windows(committee, alert_id)}
    superseded = by_id[first["id"]]
    assert superseded["state"] == "CLOSED"
    assert superseded["closure_reason"] == "SUPERSEDED_BY_NEW_WINDOW"
    assert superseded["reopen_count"] == 1


# ---------------------------------------------------------------------------
# The state of a second entity
# ---------------------------------------------------------------------------


SEPSIS_REQUEST = {
    "title": "Sepsis bundle order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "INTERNAL_MEDICINE",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("Surviving Sepsis 2021", True),
        factories.build_citation("JAMA sepsis bundles 2018", True),
    ],
}

LACTATE_ITEM = {
    "orderable_code": "LAB-LACT",
    "display_name": "Lactate, serum",
    "item_category": "LAB",
    "sequence_index": 1,
}


def test_an_inactive_reviewer_and_a_cast_assignment_are_both_out_of_reach(committee):
    """One refusal reads the reviewer's record, the other the assignment's state.

    "Only a clinician whose `employment_status` is `ACTIVE` may act or be assigned;
    assigning or casting as an inactive clinician is `ERR_CLINICIAN_NOT_ACTIVE`."
    "Only the clinician whose id equals the assignment's `reviewer_id` may cast, and
    only from state `ASSIGNED`; a `CAST`, `WITHDRAWN` or `VOIDED` assignment yields
    `ERR_ASSIGNMENT_NOT_ASSIGNED`." "Withdrawal, by contrast, is the chair's
    compensating action on an assignment still in state `ASSIGNED`." "Casting moves
    the assignment `ASSIGNED → CAST`, stores `vote`, `comment`, `evidence_concern`
    and `cast_at`, and leaves the workload debit in place".

    Design: Corner/errors/error_inactive_clinician_and_already_cast_assignment_are_rejected
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_peer_review(
        committee,
        request_overrides=SEPSIS_REQUEST,
        order_set_overrides={"name": "Sepsis bundle v1", "specialty": "INTERNAL_MEDICINE"},
        item_payloads=[LACTATE_ITEM],
    )
    order_set_id = scenario["order_set"]["id"]
    assert scenario["order_set"]["risk_class"] == "STANDARD"
    inactive = fixtures.register_clinician(
        ["PeerReviewer"],
        full_name="Lee Standby",
        specialty="INTERNAL_MEDICINE",
        employment_status="INACTIVE",
    )
    active = committee["peers"][0]

    refused = api_client.create_review_assignment(
        factories.build_review_assignment_payload(
            inactive["id"], "PEER_REVIEW", order_set_id=order_set_id
        ),
        committee["chair_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_CLINICIAN_NOT_ACTIVE, 409)

    assignment = validate_success(
        api_client.create_review_assignment(
            factories.build_review_assignment_payload(
                active["id"], "PEER_REVIEW", order_set_id=order_set_id
            ),
            committee["chair_headers"],
        ),
        201,
    )
    cast = validate_success(
        api_client.cast_review_vote(
            assignment["id"],
            factories.build_cast_payload("APPROVE", comment="Content accurate"),
            committee["peer_headers"][0],
        )
    )
    assert cast["state"] == "CAST"
    assert cast["vote"] == "APPROVE"

    recast = api_client.cast_review_vote(
        assignment["id"],
        factories.build_cast_payload("REVISE", comment="Changed my mind"),
        committee["peer_headers"][0],
    )
    validate_error(recast, ApiErrorId.ERR_ASSIGNMENT_NOT_ASSIGNED, 409)

    withdrawal = api_client.withdraw_review_assignment(
        assignment["id"],
        factories.build_withdraw_payload(withdrawal_reason="Too late"),
        committee["chair_headers"],
    )
    validate_error(withdrawal, ApiErrorId.ERR_ASSIGNMENT_NOT_ASSIGNED, 409)

    settled = validate_success(
        api_client.get_review_assignment(assignment["id"], committee["chair_headers"])
    )
    assert settled["state"] == "CAST"
    assert settled["vote"] == "APPROVE"

    reviewer = validate_success(
        api_client.get_clinician(active["id"], committee["chair_headers"])
    )
    # the standard peer reading was performed, so its 20 minutes stay spent
    assert reviewer["review_workload_assigned_minutes"] == 20
    assertions.assert_workload_identity(reviewer)
    assertions.assert_workload_ledger(
        validate_success(
            api_client.get_clinician(inactive["id"], committee["chair_headers"])
        ),
        0,
        480,
        0,
    )


# ---------------------------------------------------------------------------
# The vendor release stage guards
# ---------------------------------------------------------------------------


def test_the_release_stage_guards_separate_received_from_analysed(committee):
    """An empty release cannot be scored, and an unscored one cannot move on.

    "Impact analysis is the `PharmacyInformaticist`'s exclusive step, takes an
    optional `analysis_note`, and may run only on a release whose
    `review_cycle_state` is `RECEIVED` and which carries at least one delta;
    otherwise it is refused with `ERR_VENDOR_RELEASE_NOT_RECEIVED`." "Dispositioning
    against a release still in `RECEIVED`, or one already `ACTIVATED` or
    `SUPERSEDED`, is refused with `ERR_VENDOR_RELEASE_NOT_ANALYZED`." "A release
    still in `RECEIVED`, or already `ACTIVATED` or `SUPERSEDED`, is refused with
    `ERR_VENDOR_RELEASE_NOT_ANALYZED`."

    Design: Corner/errors/error_vendor_release_stage_guards_reject_empty_analysis_repeat_analysis_and_early_activation
    """
    fixtures.reset_clock()
    empty = fixtures.create_release(
        committee, release_label="2026.08-empty", received_at="2026-08-01T00:00:00Z"
    )
    loaded = fixtures.create_release(
        committee, release_label="2026.08-loaded", received_at="2026-08-01T00:00:00Z"
    )
    delta = fixtures.add_delta(
        committee,
        loaded["id"],
        rule_code="DDI-3001",
        change_type="NEW_INTERACTION",
        description="New moderate interaction",
        new_severity="MODERATE",
    )
    assert delta["weight"] == 3

    unscorable = api_client.run_vendor_release_impact_analysis(
        empty["id"],
        factories.build_impact_analysis_payload(analysis_note="Nothing to score"),
        committee["pharmacist_headers"],
    )
    validate_error(unscorable, ApiErrorId.ERR_VENDOR_RELEASE_NOT_RECEIVED, 409)
    still_empty = validate_success(
        api_client.get_vendor_release(empty["id"], committee["chair_headers"])
    )
    assert still_empty["review_cycle_state"] == "RECEIVED"
    assert still_empty["impact_score"] is None

    premature = api_client.activate_vendor_release(
        loaded["id"],
        factories.build_release_activation_payload(activation_note="Too early"),
        committee["pharmacist_headers"],
    )
    validate_error(premature, ApiErrorId.ERR_VENDOR_RELEASE_NOT_ANALYZED, 409)

    early_disposition = api_client.disposition_vendor_rule_delta(
        delta["id"],
        factories.build_disposition_payload("ACCEPT"),
        committee["pharmacist_headers"],
    )
    validate_error(early_disposition, ApiErrorId.ERR_VENDOR_RELEASE_NOT_ANALYZED, 409)
    deltas, _meta = validate_paginated(
        api_client.list_vendor_rule_deltas(loaded["id"], committee["chair_headers"])
    )
    assert deltas[0]["disposition"] is None
    assert deltas[0]["dispositioned_at"] is None

    analysed = validate_success(
        api_client.run_vendor_release_impact_analysis(
            loaded["id"],
            factories.build_impact_analysis_payload(analysis_note="Score it"),
            committee["pharmacist_headers"],
        )
    )
    assert analysed["impact_score"] == 3
    assert analysed["review_cycle_state"] == "IMPACT_ANALYZED_FAST_TRACK"

    repeat = api_client.run_vendor_release_impact_analysis(
        loaded["id"],
        factories.build_impact_analysis_payload(analysis_note="Score it again"),
        committee["pharmacist_headers"],
    )
    validate_error(repeat, ApiErrorId.ERR_VENDOR_RELEASE_NOT_RECEIVED, 409)
    unchanged = validate_success(
        api_client.get_vendor_release(loaded["id"], committee["chair_headers"])
    )
    assert unchanged["impact_score"] == 3
    assert unchanged["version"] == analysed["version"]


# ---------------------------------------------------------------------------
# The downtime event guards
# ---------------------------------------------------------------------------


def test_a_downtime_window_activates_only_inside_itself_and_closes_only_once(committee):
    """The clock gates activation and both terminal moves refuse a repeat.

    "Activation, with an optional `activation_note`, requires `state` `SCHEDULED` and
    requires the clock to be at or after `window_start` and at or before `window_end`;
    any other state, or a clock outside that span, is refused with
    `ERR_DOWNTIME_EVENT_NOT_SCHEDULED`." "Closing, with an optional `closure_note`,
    sets `closed_at` to the current instant and takes an `ACTIVE` event to `CLOSED` —
    which resumes in-scope mutations — or a `SCHEDULED` event to `CANCELLED`; both are
    terminal, and closing an event already `CLOSED` or `CANCELLED` is refused with
    `ERR_DOWNTIME_EVENT_NOT_CLOSEABLE`."

    Design: Corner/errors/error_downtime_event_guards_reject_early_activation_double_activation_and_double_close
    """
    fixtures.reset_clock()
    future = fixtures.schedule_downtime(
        "2026-08-10T02:00:00Z", "2026-08-10T04:00:00Z", reason="Planned engine upgrade"
    )
    current = fixtures.schedule_downtime(
        "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", reason="Unplanned engine outage"
    )

    too_early = api_client.activate_downtime_event(
        future["id"],
        factories.build_downtime_activation_payload(
            activation_note="Window has not started"
        ),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(too_early, ApiErrorId.ERR_DOWNTIME_EVENT_NOT_SCHEDULED, 409)
    assert fixtures.read_downtime(future["id"])["state"] == "SCHEDULED"
    assert fixtures.read_downtime(future["id"])["activated_at"] is None

    activated = validate_success(
        api_client.activate_downtime_event(
            current["id"],
            factories.build_downtime_activation_payload(activation_note="Engine down"),
            fixtures.ADMIN_HEADERS,
        )
    )
    assert activated["state"] == "ACTIVE"
    assert activated["activated_at"].startswith("2026-08-01T00:00:00")

    repeat_activation = api_client.activate_downtime_event(
        current["id"],
        factories.build_downtime_activation_payload(activation_note="Again"),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(repeat_activation, ApiErrorId.ERR_DOWNTIME_EVENT_NOT_SCHEDULED, 409)

    closed = validate_success(
        api_client.close_downtime_event(
            current["id"],
            factories.build_downtime_close_payload(closure_note="Engine restored"),
            fixtures.ADMIN_HEADERS,
        )
    )
    assert closed["state"] == "CLOSED"
    assert closed["closed_at"].startswith("2026-08-01T00:00:00")

    repeat_close = api_client.close_downtime_event(
        current["id"],
        factories.build_downtime_close_payload(closure_note="Again"),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(repeat_close, ApiErrorId.ERR_DOWNTIME_EVENT_NOT_CLOSEABLE, 409)

    # nothing in scope was ever attempted, so the after-action counter stayed put
    assert fixtures.read_downtime(current["id"])["blocked_mutation_count"] == 0


# ---------------------------------------------------------------------------
# The attestation guard
# ---------------------------------------------------------------------------


def test_a_task_may_be_attested_once_and_its_successor_stays_open(committee):
    """The second attestation is refused; the fresh cycle-2 task is a different row.

    "A task may be attested from `PENDING` or from `OVERDUE`; a task already
    `ATTESTED` or `EXPIRED` — both terminal — is refused with
    `ERR_REVIEW_TASK_NOT_OPEN`." "Attestation sets `attested_at` to the current
    instant, stores the `attestation_note`, and records `attested_by_clinician_id`. It
    then recomputes the governed artifact's `review_due_date` as the current instant
    plus the review interval for the artifact's `risk_class` — 365 days for
    `STANDARD`, 180 days for `HIGH` — with `expiration_at` 30 days after that ... and
    it creates a fresh annual review task in state `PENDING` whose `cycle_index` is
    the attested task's `cycle_index` plus 1, mirroring the new dates."

    Design: Corner/errors/error_repeat_attestation_of_an_annual_review_task_is_rejected
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee,
        request_overrides={**PASSIVE_ALERT_REQUEST, "title": "Beers advisory"},
        alert_overrides=_passive_alert("Beers passive advisory", "beers_medication"),
    )
    alert_id = scenario["alert"]["id"]
    task = fixtures.task_for_alert(committee, alert_id)
    assert task["state"] == "PENDING"
    assert task["cycle_index"] == 1

    attested = validate_success(
        api_client.attest_annual_review_task(
            task["id"],
            factories.build_attestation_payload(
                evidence_citations=[
                    factories.build_citation("Beers criteria 2025 update", True)
                ],
                attestation_note="Still current",
            ),
            committee["sponsor_headers"],
        )
    )
    assert attested["state"] == "ATTESTED"
    assert attested["attested_at"].startswith("2026-08-01T00:00:00")
    assert attested["attested_by_clinician_id"] == committee["sponsor"]["id"]
    assert attested["stale_content_triggered"] is False

    duplicate = api_client.attest_annual_review_task(
        task["id"],
        factories.build_attestation_payload(
            evidence_citations=[
                factories.build_citation("Beers criteria 2025 update", True)
            ],
            attestation_note="Duplicate attestation",
        ),
        committee["sponsor_headers"],
    )
    validate_error(duplicate, ApiErrorId.ERR_REVIEW_TASK_NOT_OPEN, 409)

    tasks, meta = validate_paginated(
        api_client.list_annual_review_tasks(
            committee["chair_headers"], {"alert_id": alert_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    by_cycle = {row["cycle_index"]: row for row in tasks}
    assert by_cycle[1]["state"] == "ATTESTED"
    successor = by_cycle[2]
    assert successor["state"] == "PENDING"
    assert successor["id"] != task["id"]
    # a passive alert is STANDARD risk, so the new cycle runs the 365-day clock
    assert successor["review_due_date"] == "2027-08-01T00:00:00Z"
    assert successor["expiration_at"] == "2027-08-31T00:00:00Z"


# ---------------------------------------------------------------------------
# The harshest downtime mode
# ---------------------------------------------------------------------------


def test_a_full_unavailable_freeze_takes_the_reads_down_with_the_writes(committee):
    """In-scope reads fail too, and a content request read still succeeds.

    "While the event's `state` is `ACTIVE`, every in-scope content mutation is
    refused: with `mode` `READ_ONLY` the refusal is `ERR_CDS_CONTENT_FROZEN` (409),
    and with `mode` `FULL_UNAVAILABLE` both mutations *and* reads of in-scope content
    are refused with `ERR_CDS_UNAVAILABLE` (409)." "Regardless of scope or mode, the
    freeze never blocks closing a downtime event, running the expiration sweep,
    ingesting alert firings, or setting the logical clock, and it never blocks writes
    to content requests, adherence measurements or annual review tasks." "Each
    in-scope mutation the freeze rejects increments that active event's
    `blocked_mutation_count` by 1".

    Design: Corner/errors/error_full_unavailable_downtime_blocks_in_scope_reads_with_cds_unavailable
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_draft_order_set(
        committee,
        request_overrides=SEPSIS_REQUEST,
        order_set_overrides={"name": "Sepsis bundle v1", "specialty": "INTERNAL_MEDICINE"},
        item_payloads=[],
    )
    order_set_id = scenario["order_set"]["id"]
    request_id = scenario["content_request"]["id"]
    assert scenario["order_set"]["item_count"] == 0

    outage = fixtures.setup_active_downtime(
        "2026-08-01T00:00:00Z",
        "2026-08-02T00:00:00Z",
        scope="SYSTEM_WIDE",
        mode="FULL_UNAVAILABLE",
        planned=False,
        reason="Rules engine unreachable",
    )
    assert outage["state"] == "ACTIVE"

    frozen_read = api_client.get_order_set(order_set_id, committee["chair_headers"])
    validate_error(frozen_read, ApiErrorId.ERR_CDS_UNAVAILABLE, 409)

    frozen_write = api_client.create_order_set_item(
        order_set_id,
        factories.build_order_set_item_payload(
            orderable_code="MED-X",
            display_name="Blocked item",
            item_category="MEDICATION",
            sequence_index=1,
        ),
        committee["builder_headers"],
    )
    validate_error(frozen_write, ApiErrorId.ERR_CDS_UNAVAILABLE, 409)

    # content requests are named as never in scope, whatever the mode
    still_readable = validate_success(
        api_client.get_content_request(request_id, committee["chair_headers"])
    )
    assert still_readable["id"] == request_id

    during = fixtures.read_downtime(outage["id"])
    assert during["state"] == "ACTIVE"
    # only the write counts; the refused read is not a blocked mutation
    assert during["blocked_mutation_count"] == 1

    validate_success(
        api_client.close_downtime_event(
            outage["id"],
            factories.build_downtime_close_payload(closure_note="Engine restored"),
            fixtures.ADMIN_HEADERS,
        )
    )
    _items, item_meta = validate_paginated(
        api_client.list_order_set_items(order_set_id, committee["chair_headers"])
    )
    assert item_meta["total_count"] == 0
    assert fixtures.read_order_set(committee, order_set_id)["item_count"] == 0


# ---------------------------------------------------------------------------
# The two assignment-time identity guards
# ---------------------------------------------------------------------------


def test_the_sponsor_cannot_review_their_own_request_and_no_reviewer_twice(committee):
    """One 403 on identity, one 409 on duplication, and one clean assignment.

    "Two further constraints are enforced with `ERR_SELF_REVIEW_FORBIDDEN` (403),
    both at assignment time: the `clinical_sponsor_id` of a content request may not
    review any artifact built from that request, and the clinician recorded in
    `pharmacy_signoff_by_clinician_id` on an order set may not review that order
    set." "A clinician may hold at most one assignment in state `ASSIGNED` or `CAST`
    per artifact-and-`review_kind` pair, and a second one is
    `ERR_DUPLICATE_REVIEW_ASSIGNMENT`". "An order-set peer review costs 20 minutes on
    a `STANDARD` build and 35 on a `HIGH` one".

    Design: Corner/errors/error_self_review_and_duplicate_assignment_are_rejected
    """
    fixtures.reset_clock()
    dual_role = fixtures.register_clinician(
        ["ClinicalSponsor", "PeerReviewer"],
        full_name="Sasha Sponsor Reviewer",
        specialty="CARDIOLOGY",
    )
    release = fixtures.setup_activated_release(committee)
    submitted = validate_success(
        api_client.create_content_request(
            factories.build_content_request_payload(dual_role["id"], **SEPSIS_REQUEST),
            make_clinical_sponsor_headers(dual_role["id"]),
        ),
        201,
    )
    accepted = fixtures.triage_request(
        committee, submitted["id"], "ACCEPT", triage_note="Accepted for build"
    )
    order_set = fixtures.build_order_set(
        committee,
        accepted,
        release["id"],
        name="Sepsis bundle v1",
        specialty="INTERNAL_MEDICINE",
    )
    fixtures.add_item(committee, order_set["id"], **LACTATE_ITEM)
    fixtures.submit_for_peer_review(committee, order_set["id"])
    order_set_id = order_set["id"]
    reviewer = committee["peers"][0]

    self_review = api_client.create_review_assignment(
        factories.build_review_assignment_payload(
            dual_role["id"], "PEER_REVIEW", order_set_id=order_set_id
        ),
        committee["chair_headers"],
    )
    validate_error(self_review, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN, 403)

    accepted_assignment = validate_success(
        api_client.create_review_assignment(
            factories.build_review_assignment_payload(
                reviewer["id"], "PEER_REVIEW", order_set_id=order_set_id
            ),
            committee["chair_headers"],
        ),
        201,
    )
    assert accepted_assignment["state"] == "ASSIGNED"
    assert accepted_assignment["estimated_minutes"] == 20

    duplicate = api_client.create_review_assignment(
        factories.build_review_assignment_payload(
            reviewer["id"], "PEER_REVIEW", order_set_id=order_set_id
        ),
        committee["chair_headers"],
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_REVIEW_ASSIGNMENT, 409)

    rows, meta = validate_paginated(
        api_client.list_review_assignments(
            committee["chair_headers"], {"order_set_id": order_set_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted_assignment["id"]

    # the refused duplicate debited nothing on top of the one live assignment
    assertions.assert_workload_ledger(
        validate_success(
            api_client.get_clinician(reviewer["id"], committee["chair_headers"])
        ),
        20,
        460,
        1,
    )
    assertions.assert_workload_ledger(
        validate_success(
            api_client.get_clinician(dual_role["id"], committee["chair_headers"])
        ),
        0,
        480,
        0,
    )


# ---------------------------------------------------------------------------
# The pharmacy gate on high-alert content
# ---------------------------------------------------------------------------


HEPARIN_REQUEST = {
    "title": "Heparin infusion order set",
    "request_type": "ORDER_SET",
    "clinical_domain": "CARDIOLOGY",
    "urgency": "ROUTINE",
    "evidence_grade": "B",
    "patient_safety_flag": False,
    "evidence_citations": [
        factories.build_citation("CHEST 2020 anticoagulation", True),
        factories.build_citation("ISMP heparin safety 2022", True),
    ],
}


def test_a_high_alert_build_waits_for_the_pharmacist_then_publishes(committee):
    """Approval is not enough; the same publish call succeeds after sign-off.

    "if `high_alert_item_count` is at least 1 then `pharmacy_signoff_at` must not be
    null, or the request is refused with
    `ERR_HIGH_ALERT_PHARMACY_SIGNOFF_REQUIRED`." "A `PharmacyInformaticist` records
    sign-off by supplying `pharmacy_signoff_by_clinician_id` and an optional
    `signoff_note`; the server stores that clinician reference and sets
    `pharmacy_signoff_at` to the current instant." "So `review_due_date` is the
    anchor plus the interval for the artifact's `risk_class`, `expiration_at` is
    `review_due_date` plus a 30-day grace period, and `archive_eligible_at` is
    `expiration_at` plus a further 90 days."

    Design: Corner/errors/error_high_alert_publication_without_pharmacy_signoff_is_rejected
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_approved_order_set(
        committee,
        request_overrides=HEPARIN_REQUEST,
        order_set_overrides={"name": "Heparin infusion v1", "specialty": "CARDIOLOGY"},
        item_payloads=[factories.build_high_alert_item_payload(sequence_index=1)],
    )
    order_set = scenario["order_set"]
    order_set_id = order_set["id"]
    assert order_set["risk_class"] == "HIGH"
    assert order_set["peer_required_votes"] == 3
    assertions.assert_order_set_states(order_set, "APPROVED", "UNPUBLISHED")
    assert order_set["pharmacy_signoff_at"] is None

    blocked = api_client.publish_order_set(
        order_set_id,
        factories.build_publish_payload("2026-08-15T00:00:00Z"),
        committee["chair_headers"],
    )
    validate_error(blocked, ApiErrorId.ERR_HIGH_ALERT_PHARMACY_SIGNOFF_REQUIRED, 409)
    held = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_order_set_states(held, "APPROVED", "UNPUBLISHED")
    assert held["go_live_at"] is None

    signed = fixtures.sign_off(
        committee,
        order_set_id,
        signoff_note="High-alert doses verified against the activated release",
    )
    assert signed["pharmacy_signoff_at"].startswith("2026-08-01T00:00:00")
    assert signed["pharmacy_signoff_by_clinician_id"] == committee["pharmacist"]["id"]

    published = validate_success(
        api_client.publish_order_set(
            order_set_id,
            factories.build_publish_payload("2026-08-15T00:00:00Z"),
            committee["chair_headers"],
        )
    )
    assertions.assert_order_set_states(published, "APPROVED", "PUBLISHED")
    # 180 days from go_live_at for a HIGH build, then 30, then a further 90
    assertions.assert_review_schedule(
        published,
        "2027-02-11T00:00:00Z",
        "2027-03-13T00:00:00Z",
        "2027-06-11T00:00:00Z",
    )

    tasks, meta = validate_paginated(
        api_client.list_annual_review_tasks(
            committee["chair_headers"], {"order_set_id": order_set_id}
        )
    )
    assert meta["total_count"] == 1
    assert tasks[0]["state"] == "PENDING"
    assert tasks[0]["cycle_index"] == 1


# ---------------------------------------------------------------------------
# The adherence measurement guards
# ---------------------------------------------------------------------------


def test_the_verdict_gate_reads_the_pooled_figure_not_the_stored_one(committee):
    """A stored 70.00 does not license SUSTAIN when the pooled value is 61.82.

    "Every row must satisfy three conditions: `eligible_orders` is at least 0,
    `adherent_orders` is at least 0 and no greater than `eligible_orders`, and
    `unintended_events` is at least 0. A row violating any of these is refused with
    `ERR_INVALID_OBSERVATION_COUNTS`." "The submitted verdict must be supported by
    those computed numbers, and the check runs against the intention-to-treat value
    computed in this very request, never against the per-protocol value stored at
    creation. `SUSTAIN` requires `adherence_pct_intention_to_treat` to be at least
    70.00 **and** `unintended_event_rate_per_100` to be at most 5.00. ... `REVISE` is
    always permitted. An unsupported verdict is refused with
    `ERR_ADHERENCE_VERDICT_UNSUPPORTED`." "Finalization is the chair's exclusive step
    and requires `measurement_state` `PROVISIONAL`; a measurement already `FINALIZED`
    or `INSUFFICIENT_DATA` is refused with `ERR_MEASUREMENT_NOT_PROVISIONAL`."

    Design: Corner/errors/error_adherence_measurement_guards_reject_bad_counts_unsupported_verdicts_and_repeat_finalize
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_published_order_set(
        committee,
        "2026-08-01T00:00:00Z",
        request_overrides=SEPSIS_REQUEST,
        order_set_overrides={"name": "Sepsis bundle v1", "specialty": "INTERNAL_MEDICINE"},
        item_payloads=[LACTATE_ITEM],
    )
    order_set_id = scenario["order_set"]["id"]
    fixtures.set_clock("2026-10-01T00:00:00Z")

    impossible = api_client.create_adherence_measurement(
        order_set_id,
        factories.build_adherence_measurement_payload(
            "2026-09-01T00:00:00Z",
            "2026-10-01T00:00:00Z",
            [
                factories.build_unit_observation(
                    "MED-A", eligible_orders=10, adherent_orders=12, unintended_events=0
                )
            ],
        ),
        committee["chair_headers"],
    )
    validate_error(impossible, ApiErrorId.ERR_INVALID_OBSERVATION_COUNTS, 422)

    measurement = validate_success(
        api_client.create_adherence_measurement(
            order_set_id,
            factories.build_adherence_measurement_payload(
                "2026-09-01T00:00:00Z",
                "2026-10-01T00:00:00Z",
                [
                    factories.build_unit_observation(
                        "MED-A",
                        eligible_orders=100,
                        adherent_orders=60,
                        unintended_events=3,
                    ),
                    factories.build_unit_observation(
                        "ICU-B",
                        eligible_orders=10,
                        adherent_orders=8,
                        unintended_events=1,
                    ),
                ],
            ),
            committee["chair_headers"],
        ),
        201,
    )
    # the unweighted mean of 0.6000 and 0.8000 sits exactly on the success floor
    assertions.assert_numeric_equals(measurement["adherence_pct_per_protocol"], 70.00, 2)
    assert measurement["included_unit_count"] == 2
    assert measurement["excluded_unit_count"] == 0
    assert measurement["measurement_state"] == "PROVISIONAL"
    assert measurement["adherence_pct_intention_to_treat"] is None

    unsupported = api_client.finalize_adherence_measurement(
        measurement["id"],
        factories.build_finalize_measurement_payload(
            "SUSTAIN", finalization_note="Looks like a pass on the stored number"
        ),
        committee["chair_headers"],
    )
    validate_error(unsupported, ApiErrorId.ERR_ADHERENCE_VERDICT_UNSUPPORTED, 422)

    finalized = validate_success(
        api_client.finalize_adherence_measurement(
            measurement["id"],
            factories.build_finalize_measurement_payload(
                "REVISE", finalization_note="Pooled adherence is below the floor"
            ),
            committee["chair_headers"],
        )
    )
    # 100 * 68 / 110 pooled, and 100 * 4 / 110 for the event rate
    assertions.assert_numeric_equals(
        finalized["adherence_pct_intention_to_treat"], 61.82, 2
    )
    assertions.assert_numeric_equals(finalized["unintended_event_rate_per_100"], 3.64, 2)
    assert finalized["unintended_event_count"] == 4
    assert finalized["verdict"] == "REVISE"
    assert finalized["measurement_state"] == "FINALIZED"

    governed = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_numeric_equals(governed["latest_adherence_pct"], 61.82, 2)
    # only a RETIRE verdict reopens the governance clock
    assertions.assert_order_set_states(governed, "APPROVED", "PUBLISHED")

    second_thoughts = api_client.finalize_adherence_measurement(
        measurement["id"],
        factories.build_finalize_measurement_payload(
            "RETIRE", finalization_note="Second thoughts"
        ),
        committee["chair_headers"],
    )
    validate_error(second_thoughts, ApiErrorId.ERR_MEASUREMENT_NOT_PROVISIONAL, 409)

    rows, meta = validate_paginated(
        api_client.list_adherence_measurements(order_set_id, committee["chair_headers"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["verdict"] == "REVISE"
