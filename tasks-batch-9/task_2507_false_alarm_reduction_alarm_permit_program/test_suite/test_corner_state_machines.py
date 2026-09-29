"""State machine behaviour of the alarm program: initial states, declared transitions, cascading side effects, terminal-state lockdown and the two independent invoice dimensions."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, get_success_data, validate_error,
    validate_error_is_one_of, validate_paginated, validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def test_alarm_system_registration_starts_in_submitted_initial_state(api):
    """A freshly lodged registration lands in SUBMITTED at version 1 with no permit row behind it, while the monitoring company already counts it.

    PRD §3.3: "The row is created in `SUBMITTED`, and the new-installation grace anchor is taken from `installed_at`."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."
    PRD §3.10: "The company is created in `ACTIVE` with `reporting_compliance_score` at 1.00, `probation_started_at`, `status_reason` and `last_status_action_at` all null, and its derived counters recomputed: `monitored_system_count` as the number of systems it monitors in `SUBMITTED`, `PERMITTED` or `UNPERMITTED`, `dispatch_request_count_lifetime` as the number of dispatch requests it has lodged across every status, and `consecutive_flagged_report_count` as the length of the most-recent unbroken run of its reports ending in `VARIANCE_FLAGGED`, taken in order of `period_start` ascending."

    A permit row is only minted by the approval chain, so a registration that has
    never been approved has zero permits; `permitted_at` and `unpermitted_since`
    are stamped by the permit branches, `rejection_reason` by the rejection
    branch and `decommissioned_at` by retirement, so all four are still null.
    The single SUBMITTED registration already counts as monitored, giving the
    company a monitored_system_count of 1.

    Design: Corner/state_machines/alarm_system_registration_starts_in_submitted_initial_state
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        system_count=0,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )

    response = api.create_alarm_system(
        F.alarm_system_payload(
            bundle.site_id,
            bundle.company_id,
            system_type="COMBINATION",
            zone_count=12,
            ecv_enabled=True,
            verified_response_mode="NONE",
            installed_at="2026-07-30T09:00:00Z",
        ),
        U.alarm_user(bundle.site_id),
    )
    system = A.data_of(response, 201)

    A.assert_entity_envelope(system)
    A.assert_status(system, "SUBMITTED")
    assert system["version"] == 1, f"a created registration is version 1, got {system['version']}"
    for field in ("permitted_at", "unpermitted_since", "rejection_reason", "decommissioned_at"):
        assert system[field] is None, f"{field} must still be null on a SUBMITTED registration, got {system[field]!r}"

    A.assert_total_count(
        api.list_alarm_permits(U.PERMIT_CLERK, {"alarm_system_id": system["id"]}), 0
    )
    company = X.get_company(api, bundle.company_id)
    assert company["monitored_system_count"] == 1, (
        f"a SUBMITTED registration counts as monitored, got {company['monitored_system_count']}"
    )


def test_dispatch_request_submission_freezes_its_verification_findings(api):
    """Submitting a dispatch request creates it in SUBMITTED with the verification findings computed once and frozen on the row.

    PRD §3.4: "On acceptance the row denormalizes `alarm_site_id` and `monitoring_company_id` from the system and is created in `SUBMITTED`."
    PRD §3.4: "`distinct_ecv_contact_count` is then the number of distinct contact identifiers surviving that filter, defaulting to 0 for an empty log."
    PRD §3.4: "From that count, `ecv_sufficient` is decided as follows: it is true whenever the `alarm_type` is `DURESS`, because a duress signal bypasses call verification entirely; otherwise it is true when the `verification_method` is `TWO_CALL_ECV` and `distinct_ecv_contact_count` is at least 2; otherwise it is true when the method is `AUDIO_VIDEO` and `audio_video_evidence` is true; otherwise it is true when the method is `GUARD_RESPONSE` and `guard_on_scene` is true; and in every remaining case it is false."
    PRD §3.4: "The same submission also freezes `system_permitted_at_occurrence`, which is true when the system's status was `PERMITTED` at that moment."
    PRD §3.4: "`refusal_reason` is null on any request that is not refused."

    Two attempts against two distinct ACTIVE ECV-callable contacts of the
    premises survive the eligibility filter, so distinct_ecv_contact_count is 2,
    which meets the inclusive two-contact threshold for TWO_CALL_ECV and makes
    ecv_sufficient true. The system was permitted on 2026-08-01, before the
    2026-09-15 signal, so system_permitted_at_occurrence is true.

    Design: Corner/state_machines/dispatch_request_submission_starts_in_submitted_with_frozen_findings
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    occurred_at = "2026-09-15T03:09:00Z"
    attempts = [
        F.call_attempt(bundle.contact_ids[0], "2026-09-15T03:10:00Z", "NO_ANSWER"),
        F.call_attempt(bundle.contact_ids[1], "2026-09-15T03:11:00Z", "NO_ANSWER"),
    ]

    response = api.create_dispatch_request(
        F.dispatch_request_payload(
            bundle.system_id,
            occurred_at,
            attempts,
            alarm_type="BURGLARY",
            verification_method="TWO_CALL_ECV",
            audio_video_evidence=False,
            guard_on_scene=False,
            idempotency_key="gsm-0915-a",
        ),
        bundle.operator_headers,
    )
    request = A.data_of(response, 201)

    A.assert_status(request, "SUBMITTED")
    assert request["version"] == 1, f"a created dispatch request is version 1, got {request['version']}"
    assert request["distinct_ecv_contact_count"] == 2, (
        f"two distinct callable contacts give a distinct count of 2, got {request['distinct_ecv_contact_count']}"
    )
    assert request["ecv_sufficient"] is True, (
        f"TWO_CALL_ECV with two distinct contacts is sufficient, got {request['ecv_sufficient']!r}"
    )
    assert request["system_permitted_at_occurrence"] is True, (
        f"the system was PERMITTED when the signal fired, got {request['system_permitted_at_occurrence']!r}"
    )
    assert request["alarm_site_id"] == bundle.site_id
    assert request["monitoring_company_id"] == bundle.company_id
    for field in ("validated_at", "validated_by_user_id", "dispatched_at", "refusal_reason"):
        assert request[field] is None, f"{field} must be null on a SUBMITTED request, got {request[field]!r}"


def test_dispatch_request_validation_stamps_the_validating_supervisor(api):
    """Validating a submitted request moves it to VALIDATED and stamps the logical clock and the acting supervisor onto the row.

    PRD §3.4: "A `PoliceDispatchSupervisor` may validate it, moving `SUBMITTED → VALIDATED` and stamping `validated_at` with the logical clock and `validated_by_user_id` with the acting `X-User-ID`."
    PRD §3.4: "Recording the dispatch moves `VALIDATED → DISPATCHED` and stamps `dispatched_at` with the logical clock; it requires that the premises posture is still not `RESPONSE_SUSPENDED` at the moment of dispatch, else `ERR_POLICE_RESPONSE_SUSPENDED`, because a suspension served between validation and dispatch must stop the patrol."

    The clock reads 2026-09-20T00:00:00Z at validation, so validated_at carries
    that instant and validated_by_user_id carries the supervisor identifier;
    dispatched_at belongs to the later, separate transition and is still null.

    Design: Corner/state_machines/dispatch_request_submitted_to_validated_stamps_validating_supervisor
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    occurred_at = "2026-09-15T03:09:00Z"
    request_id = X.submit_dispatch_request(api, bundle, bundle.system_id, occurred_at)

    request = A.data_of(api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR), 200)

    A.assert_status(request, "VALIDATED")
    assert request["validated_at"].startswith("2026-09-20T00:00:00"), (
        f"validated_at must carry the logical clock 2026-09-20T00:00:00Z, got {request['validated_at']!r}"
    )
    assert request["validated_by_user_id"] == U.DISPATCH_SUPERVISOR_ID, (
        f"validated_by_user_id must be the acting supervisor, got {request['validated_by_user_id']!r}"
    )
    assert request["dispatched_at"] is None, (
        f"dispatched_at belongs to the later transition and must still be null, got {request['dispatched_at']!r}"
    )


def test_dispatch_request_record_dispatch_stamps_dispatched_at(api):
    """Recording the dispatch is a second transition that stamps dispatched_at at the current clock without disturbing validated_at or any premises count.

    PRD §3.4: "Recording the dispatch moves `VALIDATED → DISPATCHED` and stamps `dispatched_at` with the logical clock; it requires that the premises posture is still not `RESPONSE_SUSPENDED` at the moment of dispatch, else `ERR_POLICE_RESPONSE_SUSPENDED`, because a suspension served between validation and dispatch must stop the patrol."
    PRD §3.5: "Only incidents in `COUNTED` or `APPEALED` are chargeable."

    Validation happens at 2026-09-20T00:00:00Z and the clock then advances an
    hour, so dispatched_at reads 2026-09-20T01:00:00Z while validated_at still
    reads 2026-09-20T00:00:00Z. No incident exists yet, so the premises'
    chargeable_count_window is still 0.

    Design: Corner/state_machines/dispatch_request_validated_to_dispatched_stamps_dispatched_at
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    request_id = X.submit_dispatch_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    validate_success(api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR), 200)
    X.set_clock(api, "2026-09-20T01:00:00Z")

    request = A.data_of(api.record_dispatch(request_id, U.DISPATCH_SUPERVISOR), 200)

    A.assert_status(request, "DISPATCHED")
    assert request["dispatched_at"].startswith("2026-09-20T01:00:00"), (
        f"dispatched_at must carry the clock at dispatch, got {request['dispatched_at']!r}"
    )
    assert request["validated_at"].startswith("2026-09-20T00:00:00"), (
        f"validated_at must keep its earlier value, got {request['validated_at']!r}"
    )
    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 0, (
        f"dispatching alone counts nothing, got {site['chargeable_count_window']}"
    )


def test_incident_creation_leaves_its_request_in_dispatched_self_loop(api):
    """Opening an incident bumps the dispatch request's revision while leaving it in DISPATCHED, and the incident itself starts unpriced.

    PRD §3.4: "Alternatively an incident is opened against it, which leaves the request in `DISPATCHED` — a deliberate self-loop, since the request is the evidence and does not itself change state — while requiring that no incident already references it and that the submitted `expected_dispatch_request_version` matches the request's current `version`, after which that `version` is bumped by 1."
    PRD §3.5: "The row denormalizes `alarm_site_id`, `alarm_system_id` and `occurred_at` from the request — the occurrence instant is the ordering key for all later numbering — and is created in `REPORTED`, not yet chargeable, with `occurrence_index` and `assessed_fee_cents` unset and `appeal_count` at 0."
    PRD §3.5: "Only incidents in `COUNTED` or `APPEALED` are chargeable."

    The request was created, validated and then dispatched, which is three
    mutations, so it stands at version 3; opening the incident is the fourth and
    takes it to 4 without moving its status out of DISPATCHED. A REPORTED
    incident has no determination and no occurrence number, so the premises'
    chargeable_count_window is still 0.

    Design: Corner/state_machines/false_alarm_incident_creation_leaves_the_request_in_dispatched_self_loop
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    occurred_at = "2026-09-15T03:09:00Z"
    request_id = X.submit_dispatch_request(api, bundle, bundle.system_id, occurred_at)
    validate_success(api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR), 200)
    X.set_clock(api, "2026-09-20T01:00:00Z")
    validate_success(api.record_dispatch(request_id, U.DISPATCH_SUPERVISOR), 200)

    before = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    assert before["version"] == 3, (
        f"submit, validate and record-dispatch are three mutations, got version {before['version']}"
    )

    incident = A.data_of(
        api.create_false_alarm_incident(
            F.false_alarm_incident_payload(
                request_id,
                cause_code="OPERATOR_ERROR",
                narrative="Closing employee armed the panel and re-entered through zone 4.",
            ),
            U.DISPATCH_SUPERVISOR,
        ),
        201,
    )

    after = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    A.assert_status(after, "DISPATCHED")
    assert after["version"] == 4, (
        f"opening an incident bumps the request from 3 to 4, got {after['version']}"
    )

    A.assert_status(incident, "REPORTED")
    assert incident["version"] == 1, f"a created incident is version 1, got {incident['version']}"
    assert incident["occurrence_index"] is None, (
        f"a REPORTED incident carries no occurrence number, got {incident['occurrence_index']!r}"
    )
    assert incident["determination"] is None, (
        f"a REPORTED incident carries no determination, got {incident['determination']!r}"
    )
    assert incident["appeal_count"] == 0, f"appeal_count starts at 0, got {incident['appeal_count']}"
    assert incident["occurred_at"].startswith("2026-09-15T03:09:00"), (
        f"occurred_at is denormalized from the request, got {incident['occurred_at']!r}"
    )
    assert incident["alarm_site_id"] == bundle.site_id
    assert incident["alarm_system_id"] == bundle.system_id

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 0, (
        f"a REPORTED incident is not chargeable, got {site['chargeable_count_window']}"
    )


def test_first_counted_occurrence_runs_the_declared_side_effects(api):
    """A first chargeable ruling numbers the incident 1, prices it at zero under the free allowance, raises no invoice at all and still moves the premises counters.

    PRD §3.5: "It then sets `determination` to `COUNTED`, stamps `determined_at` with the logical clock and `determined_by_user_id` with the acting `X-User-ID`, assigns the occurrence numbering, prices the incident, and bills it."
    PRD §3.5: "In either case the incident's `occurrence_index` is the size of the set it belongs to — the incident is already counted at that point, so it counts itself — and `counted_window_mode` records which variant produced the number."
    PRD §3.5: "First, the marginal tier: the tier base is the `base_fee_cents` of the single `fee_tiers` entry whose `from_index` is at or below the index and whose `to_index` is either null or at or above the index — this is a marginal lookup, never a cumulative sum of lower tiers — and the tier base is then forced to zero whenever the index is at or below `free_alarm_allowance`."
    PRD §3.5: "When the assessed fee is above zero a `FALSE_ALARM_FEE` invoice is issued; when the tier base is zero under the free allowance and no aggravation applies, no invoice row is created at all and no administrative fee is charged."
    PRD §3.5: "Otherwise, if `chargeable_count_window` is at or above `probation_threshold_count`, the posture is `RESPONSE_PROBATION`."
    PRD §3.9: "Third, `lifetime_assessed_cents` is the sum of `assessed_cents` over every invoice of the premises whose `payment_status` is not `VOIDED` — so a written-off invoice still counts toward lifetime assessment even though it has left the outstanding balance."

    This is the premises' first chargeable incident, so under the pinned
    ROLLING_365 variant the window holds exactly this one row and the
    occurrence_index is 1. An index of 1 is at or below the free_alarm_allowance
    of 2, so the tier base is forced to 0 and the rounded product of the
    occupancy, surcharge and unpermitted factors is 0 as well, which is not
    strictly greater than the 100000-cent cap, so cap_applied is false. A zero
    subtotal means no FALSE_ALARM_FEE invoice and no administrative fee, so the
    only assessment the premises carries is the 5500-cent permit issue invoice
    from its registration approval. A window count of 1 is below the
    probation_threshold_count of 4, so the posture stays RESPONSE_ACTIVE.

    Design: Corner/state_machines/false_alarm_incident_first_counted_occurrence_runs_the_declared_side_effects
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    occurred_at = "2026-09-15T03:09:00Z"
    reported = X.create_reported_incident(
        api, bundle, bundle.system_id, occurred_at, cause_code="OPERATOR_ERROR"
    )
    X.set_clock(api, "2026-09-20T01:00:00Z")

    incident = A.data_of(
        api.determine_incident(
            reported.incident_id,
            F.determination_payload(
                "COUNTED", review_notes="Operator error confirmed on the audio log."
            ),
            U.REVIEW_OFFICER,
        ),
        200,
    )

    A.assert_status(incident, "COUNTED")
    assert incident["determination"] == "COUNTED"
    assert incident["determined_at"].startswith("2026-09-20T01:00:00"), (
        f"determined_at must carry the logical clock, got {incident['determined_at']!r}"
    )
    assert incident["determined_by_user_id"] == U.REVIEW_OFFICER_ID, (
        f"determined_by_user_id must be the acting review officer, got {incident['determined_by_user_id']!r}"
    )
    assert incident["occurrence_index"] == 1, (
        f"the first chargeable incident is index 1, got {incident['occurrence_index']}"
    )
    assert incident["counted_window_mode"] == "ROLLING_365", (
        f"the pinned schedule counts under ROLLING_365, got {incident['counted_window_mode']!r}"
    )
    A.assert_money_cents(incident["assessed_fee_cents"], 0, "assessed_fee_cents")
    A.assert_fee_basis(incident["fee_basis"], tier_base_cents=0, cap_applied=False)

    A.assert_total_count(
        api.list_penalty_invoices(
            U.BILLING_CLERK, {"alarm_site_id": bundle.site_id, "kind": "FALSE_ALARM_FEE"}
        ),
        0,
    )

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_rolling_365"] == 1
    assert site["chargeable_count_permit_year"] == 1
    assert site["chargeable_count_window"] == 1
    A.assert_money_cents(
        site["lifetime_assessed_cents"],
        C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        "lifetime_assessed_cents",
    )
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")


def test_permit_revocation_cascades_the_system_to_unpermitted_with_a_penalty(api):
    """Revoking a permit for cause carries the whole downstream chain in one request: terminal REVOKED, the system out of permit, and a 21000-cent penalty on the premises.

    PRD §3.3: "Revoking a permit for cause produces the identical downstream chain: an administrator supplies `revocation_reason`, the permit moves from `ACTIVE`, `RENEWAL_DUE`, `RENEWAL_BLOCKED` or `GRACE` to `REVOKED` (terminal), the reason is stored, and the system falls to `UNPERMITTED` with the same penalty and the same fiscal knock-on."
    PRD §3.3: "Hop two: because the permit expired, the system moves `PERMITTED → UNPERMITTED` with `unpermitted_since` stamped at the logical clock, the premises' `unpermitted_system_count` is incremented, and an `UNPERMITTED_OPERATION_PENALTY` invoice is issued against the premises and that permit at `unpermitted_operation_penalty_cents`."
    PRD §3.9: "Fourth, the three derived counts are recomputed: `ecv_callable_contact_count` as the number of contacts that are `ACTIVE` with `is_ecv_callable` true, `unpermitted_system_count` as the number of systems in `UNPERMITTED`, and `lifted_suspension_count` as the number of suspension orders in `LIFTED`."
    PRD §3.9: "Fifth, `renewal_block_active` becomes true exactly when `outstanding_balance_cents` is at or above `delinquent_balance_block_cents` — the comparison is inclusive, so a balance of exactly 50000 cents blocks renewal."

    The penalty invoice takes the schedule's unpermitted_operation_penalty_cents
    of 20000 as its one line and therefore as its subtotal; the administrative
    charge is 20000 times the admin_fee_pct of 0.05 = 1000, which sits between
    the 500-cent floor and the 5000-cent ceiling so neither clamp binds, giving
    an assessed total of 20000 + 1000 = 21000. The premises
    already carried the 5500-cent permit issue invoice from approval, so its
    outstanding balance becomes 5500 + 21000 = 26500. That is strictly below the
    delinquent_balance_block_cents of 50000, so renewal_block_active stays false.

    Design: Corner/state_machines/alarm_permit_revoke_cascades_the_system_to_unpermitted_with_a_penalty
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )

    permit = A.data_of(
        api.revoke_permit(
            bundle.permit_id,
            {"revocation_reason": "Permit obtained with falsified monitoring contract."},
            U.PROGRAM_ADMIN,
        ),
        200,
    )

    A.assert_status(permit, "REVOKED")
    assert permit["revocation_reason"] == "Permit obtained with falsified monitoring contract.", (
        f"the supplied reason must be stored, got {permit['revocation_reason']!r}"
    )

    system = X.get_system(api, bundle.system_id)
    A.assert_status(system, "UNPERMITTED")
    assert system["unpermitted_since"].startswith("2026-08-01T00:00:00"), (
        f"unpermitted_since is stamped at the logical clock, got {system['unpermitted_since']!r}"
    )

    penalties = A.assert_total_count(
        api.list_penalty_invoices(
            U.BILLING_CLERK,
            {"alarm_site_id": bundle.site_id, "kind": "UNPERMITTED_OPERATION_PENALTY"},
        ),
        1,
    )
    A.assert_invoice_totals(
        penalties[0], subtotal_cents=20000, admin_fee_cents=1000, assessed_cents=21000
    )

    site = X.get_site(api, bundle.site_id)
    assert site["unpermitted_system_count"] == 1, (
        f"one system has fallen out of permit, got {site['unpermitted_system_count']}"
    )
    A.assert_money_cents(site["outstanding_balance_cents"], 26500, "outstanding_balance_cents")
    assert site["renewal_block_active"] is False, (
        f"26500 cents is below the 50000-cent blocking threshold, got {site['renewal_block_active']!r}"
    )


def test_counted_ruling_on_an_exempt_cause_code_is_refused(api):
    """A chargeable ruling on a cause code the ordinance lists as exempt is refused, and the incident does not move.

    PRD §3.5: "The chargeable branch, `UNDER_REVIEW → COUNTED`, requires three things: the `cause_code` must **not** be one of the governing schedule's `exempt_cause_codes`, else `ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT`; the incident's `occurred_at` must be strictly after the premises permit's `new_installation_grace_through` when that field is set, else the same code, because an incident inside the honeymoon cannot be counted; and the premises must be pinned to a governing schedule, else `ERR_NO_ACTIVE_FEE_SCHEDULE`."
    PRD §3.5: "Only incidents in `COUNTED` or `APPEALED` are chargeable."

    SEVERE_WEATHER is a member of the governing schedule's exempt_cause_codes, so
    the ruling is rejected with HTTP 422 and the row keeps its created state,
    determination and revision, leaving the premises' window count at 0.

    Design: Corner/state_machines/false_alarm_incident_counted_with_an_exempt_cause_code_is_refused
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    assert "SEVERE_WEATHER" in C.EXEMPT_CAUSE_CODES, (
        "the governing schedule's exempt list must contain SEVERE_WEATHER for this ruling to be refused"
    )
    reported = X.create_reported_incident(
        api,
        bundle,
        bundle.system_id,
        "2026-09-15T03:09:00Z",
        cause_code="SEVERE_WEATHER",
    )
    X.set_clock(api, "2026-09-20T01:00:00Z")
    before = X.get_incident(api, reported.incident_id)

    response = api.determine_incident(
        reported.incident_id,
        F.determination_payload("COUNTED", review_notes="Attempting to count a weather event."),
        U.REVIEW_OFFICER,
    )
    validate_error(response, E.ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT, expected_status=422)

    after = X.get_incident(api, reported.incident_id)
    A.assert_status(after, "REPORTED")
    assert after["determination"] is None, (
        f"a refused ruling leaves determination null, got {after['determination']!r}"
    )
    A.assert_version_unchanged(before, after)
    assert after["version"] == 1, f"the incident must still be at version 1, got {after['version']}"

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 0, (
        f"nothing became chargeable, got {site['chargeable_count_window']}"
    )


def test_counted_ruling_inside_the_new_installation_grace_is_refused(api):
    """An occurrence at or before the permit's new-installation grace end cannot be counted even on a non-exempt cause code, but it can be exempted under the grace itself.

    PRD §3.5: "The chargeable branch, `UNDER_REVIEW → COUNTED`, requires three things: the `cause_code` must **not** be one of the governing schedule's `exempt_cause_codes`, else `ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT`; the incident's `occurred_at` must be strictly after the premises permit's `new_installation_grace_through` when that field is set, else the same code, because an incident inside the honeymoon cannot be counted; and the premises must be pinned to a governing schedule, else `ERR_NO_ACTIVE_FEE_SCHEDULE`."
    PRD §3.5: "Coherence is required both ways: an `EXEMPT` ruling must supply a recognized exempt cause and a `COUNTED` ruling must supply none, else `ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT`; and any supplied cause must be a member of the governing schedule's `exempt_cause_codes`, else `ERR_EXEMPT_CAUSE_NOT_RECOGNIZED`."

    The permit was issued at 2026-08-01T00:00:00Z, so with the schedule's
    30-day new-installation grace its new_installation_grace_through falls at
    2026-08-31T00:00:00Z. The signal at 2026-08-20T02:00:00Z is inside that
    window and therefore not strictly after it, so the chargeable branch is
    refused with HTTP 422 and no occurrence number is assigned. The same row
    accepts an EXEMPT ruling carrying the recognized NEW_INSTALLATION_GRACE
    cause.

    Design: Corner/state_machines/false_alarm_incident_counted_inside_new_installation_grace_is_refused
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    permit = X.get_permit(api, bundle.permit_id)
    assert permit["new_installation_grace_through"].startswith("2026-08-31T00:00:00"), (
        "a permit issued on 2026-08-01 graces new installations through 2026-08-31, got "
        f"{permit['new_installation_grace_through']!r}"
    )

    X.set_clock(api, "2026-08-21T00:00:00Z")
    occurred_at = "2026-08-20T02:00:00Z"
    reported = X.create_reported_incident(
        api,
        bundle,
        bundle.system_id,
        occurred_at,
        cause_code="EQUIPMENT_MALFUNCTION",
        call_attempts=[
            F.call_attempt(bundle.contact_ids[0], "2026-08-20T02:01:00Z", "NO_ANSWER"),
            F.call_attempt(bundle.contact_ids[1], "2026-08-20T02:02:00Z", "VOICEMAIL"),
        ],
        idempotency_key="gsm-0820-a",
    )

    response = api.determine_incident(
        reported.incident_id,
        F.determination_payload(
            "COUNTED", review_notes="Counting a malfunction inside the installation grace window."
        ),
        U.REVIEW_OFFICER,
    )
    validate_error(response, E.ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT, expected_status=422)

    after = X.get_incident(api, reported.incident_id)
    A.assert_status(after, "REPORTED")
    assert after["occurrence_index"] is None, (
        f"a refused chargeable ruling assigns no occurrence number, got {after['occurrence_index']!r}"
    )

    exempted = X.determine_exempt(
        api,
        reported.incident_id,
        "NEW_INSTALLATION_GRACE",
        review_notes="Inside the new installation grace window.",
    )
    A.assert_status(exempted, "EXEMPT")
    assert exempted["exempt_cause_code"] == "NEW_INSTALLATION_GRACE", (
        f"the recognized exempt cause must be stored, got {exempted['exempt_cause_code']!r}"
    )


def test_validate_without_guard_proof_is_refused_despite_sufficient_ecv(api):
    """A system that demands a guard on scene cannot be validated on call verification alone, and the failed validation is not a refusal.

    PRD §3.4: "Validation requires the frozen `ecv_sufficient` to be true, else `ERR_ECV_REQUIREMENT_NOT_MET`; the premises posture not to be `RESPONSE_SUSPENDED`, else `ERR_POLICE_RESPONSE_SUSPENDED`; the monitoring company to be `ACTIVE` or `PROBATION`, else `ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED`; and the verified-response proof to match what the system demands — `audio_video_evidence` true when the system's `verified_response_mode` is `AUDIO_VIDEO_REQUIRED`, `guard_on_scene` true when it is `GUARD_REQUIRED` — else `ERR_VERIFIED_RESPONSE_NOT_CONFIRMED`."
    PRD §3.4: "`refusal_reason` is null on any request that is not refused."

    The request carries two attempts against two distinct callable contacts, so
    its frozen ecv_sufficient is true; that satisfies the earlier gate but not the
    verified-response gate, because the system was registered GUARD_REQUIRED and
    the submission asserted guard_on_scene false. The attempt therefore fails
    with HTTP 409, leaving the row in SUBMITTED with validated_at unset, and
    refusal_reason null because refusal is the sibling branch that was never
    taken.

    Design: Corner/state_machines/dispatch_request_validate_without_guard_proof_is_refused
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        system_count=0,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    guard_system_id, _permit_id = X.add_permitted_system(
        api,
        bundle,
        system_type="HOLDUP_PANIC",
        zone_count=3,
        verified_response_mode="GUARD_REQUIRED",
        installed_at="2026-08-01T00:00:00Z",
    )
    X.set_clock(api, C.CLOCK_PRESENT_UTC)
    occurred_at = "2026-09-16T22:30:00Z"
    request_id = X.submit_dispatch_request(
        api,
        bundle,
        guard_system_id,
        occurred_at,
        alarm_type="PANIC",
        verification_method="TWO_CALL_ECV",
        guard_on_scene=False,
        idempotency_key="gsm-0916-guard",
    )

    response = api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR)
    validate_error(response, E.ERR_VERIFIED_RESPONSE_NOT_CONFIRMED, expected_status=409)

    request = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    A.assert_status(request, "SUBMITTED")
    assert request["ecv_sufficient"] is True, (
        f"the call log was sufficient, so the failure is about guard proof, got {request['ecv_sufficient']!r}"
    )
    assert request["validated_at"] is None, (
        f"a failed validation stamps nothing, got {request['validated_at']!r}"
    )
    assert request["refusal_reason"] is None, (
        f"a failed validation is not a refusal, got {request['refusal_reason']!r}"
    )


def test_appeal_filing_freezes_the_incident_and_bumps_its_version(api):
    """Filing an appeal moves the incident to APPEALED while its numbering and fee stand, and the appeal itself opens unseated.

    PRD §3.6: "An accepted appeal is created in `FILED` with `filed_at` at the logical clock, `filed_by_user_id` set from the acting `X-User-ID`, `hearing_docket_id` null, `decision`, `decided_at`, `decided_by_user_id` and `findings` all null, and `alarm_site_id` denormalized from the incident."
    PRD §3.6: "The contested incident moves from `COUNTED` to `APPEALED`, its `appeal_count` and `version` each rise by 1, and — this is the point of the state — the fee **stands**."
    PRD §3.6: "The new row's `rehearing_depth` is the prior appeal's `rehearing_depth` plus 1, and an original appeal has depth 0."

    The incident was created and then ruled chargeable, which is two mutations,
    so it stands at version 2; the filing is the third and takes it to 3 while
    leaving occurrence_index at 1 and assessed_fee_cents at the 0 the free
    allowance produced. The permit holder acts as the premises, so
    filed_by_user_id is the premises identifier, and the filing happens on the
    determination day itself, well inside the filing window.

    Design: Corner/state_machines/appeal_filed_from_counted_freezes_the_incident_and_bumps_its_version
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    incident = X.create_counted_incident(
        api, bundle, bundle.system_id, "2026-09-15T03:09:00Z", cause_code="OPERATOR_ERROR"
    )
    X.set_clock(api, "2026-09-20T01:00:00Z")
    before = X.get_incident(api, incident.incident_id)
    assert before["version"] == 2, (
        f"creation plus determination are two mutations, got version {before['version']}"
    )

    appeal = A.data_of(
        api.create_appeal(
            F.appeal_payload(
                incident.incident_id,
                grounds="WRONG_CAUSE_CODE",
                narrative="The panel log shows a zone fault, not an operator error.",
                expected_false_alarm_incident_version=before["version"],
            ),
            bundle.holder_headers,
        ),
        201,
    )

    A.assert_status(appeal, "FILED")
    assert appeal["filed_at"].startswith("2026-09-20T01:00:00"), (
        f"filed_at carries the logical clock, got {appeal['filed_at']!r}"
    )
    assert appeal["hearing_docket_id"] is None, (
        f"a newly filed appeal is unseated, got {appeal['hearing_docket_id']!r}"
    )
    assert appeal["rehearing_depth"] == 0, (
        f"an original appeal has depth 0, got {appeal['rehearing_depth']}"
    )
    assert appeal["prior_appeal_id"] is None, (
        f"an original appeal links backwards to nothing, got {appeal['prior_appeal_id']!r}"
    )
    assert appeal["filed_by_user_id"] == bundle.site_id, (
        f"the permit holder acts as the premises, got {appeal['filed_by_user_id']!r}"
    )
    assert appeal["alarm_site_id"] == bundle.site_id

    after = X.get_incident(api, incident.incident_id)
    A.assert_status(after, "APPEALED")
    assert after["occurrence_index"] == 1, (
        f"the numbering is untouched by the appeal, got {after['occurrence_index']}"
    )
    A.assert_money_cents(after["assessed_fee_cents"], 0, "assessed_fee_cents")
    assert after["appeal_count"] == 1, f"appeal_count rises to 1, got {after['appeal_count']}"
    assert after["version"] == 3, (
        f"the incident's revision rose from 2 to 3, got {after['version']}"
    )


def test_appeal_seating_increments_the_docket_seat_count(api):
    """Seating a filed appeal consumes one of the session's seats and bumps the docket revision without closing a session that still has room.

    PRD §3.6: "On success the appeal moves to `SCHEDULED` with its `hearing_docket_id` set, and the docket's `scheduled_appeal_count` and `version` each rise by 1."
    PRD §3.6: "When the count reaches `capacity` the docket closes itself, `OPEN → CLOSED_FOR_SCHEDULING`, and further seating attempts meet `ERR_DOCKET_NOT_OPEN`."
    PRD §3.6: "The docket is created in `OPEN` with `scheduled_appeal_count` at 0 and `held_at` null."

    The docket opens with capacity 4 and no seats taken, so the single seating
    takes the count from 0 to 1 and the docket revision from 1 to 2. One seat of
    four is short of capacity, so the self-closing rule does not fire and the
    session stays OPEN.

    Design: Corner/state_machines/appeal_schedule_onto_open_docket_increments_the_seat_count
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    incident = X.create_counted_incident(
        api, bundle, bundle.system_id, "2026-09-15T03:09:00Z", cause_code="OPERATOR_ERROR"
    )
    X.set_clock(api, "2026-09-20T01:00:00Z")
    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    docket_id = X.create_docket(
        api,
        "2026-10-05T14:00:00Z",
        "2026-10-05T16:00:00Z",
        location="City Hall Room 210",
        capacity=4,
    )
    docket_before = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    assert docket_before["scheduled_appeal_count"] == 0, (
        f"a new session seats nobody, got {docket_before['scheduled_appeal_count']}"
    )
    assert docket_before["version"] == 1, (
        f"a created docket is version 1, got {docket_before['version']}"
    )

    appeal = A.data_of(
        api.schedule_appeal(
            appeal_id,
            {
                "hearing_docket_id": docket_id,
                "expected_hearing_docket_version": docket_before["version"],
            },
            U.HEARING_OFFICER,
        ),
        200,
    )

    A.assert_status(appeal, "SCHEDULED")
    assert appeal["hearing_docket_id"] == docket_id, (
        f"the seated appeal points at its session, got {appeal['hearing_docket_id']!r}"
    )

    docket = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    assert docket["scheduled_appeal_count"] == 1, (
        f"one seat of four is taken, got {docket['scheduled_appeal_count']}"
    )
    A.assert_status(docket, "OPEN")
    assert docket["version"] == 2, (
        f"the docket revision rose from 1 to 2, got {docket['version']}"
    )


def test_rejected_registration_cannot_later_be_approved(api):
    """A rejected registration is terminal: a later approval attempt is refused and no permit is ever minted.

    PRD §3.3: "Rejection is the sibling branch out of `SUBMITTED`. A clerk supplies `rejection_reason`, the row moves `SUBMITTED → REJECTED` — a terminal state — the reason is stored on `rejection_reason`, and the monitoring company's `monitored_system_count` is decremented."
    PRD §2.10: "The target resource must sit in a state from which the requested transition is declared. This covers every state machine in the program — alarm systems, permits, dispatch requests, incidents, hearing dockets, appeals, suspension orders, both invoice dimensions, monitoring companies and compliance reports — and any attempt to act on a resource already in a terminal state fails here with `ERR_INVALID_STATE`."

    Approval is declared only out of SUBMITTED, so the attempt on the terminal
    REJECTED row is refused with HTTP 409, the stored rejection reason survives,
    and the permit listing for that registration is still empty.

    Design: Corner/state_machines/alarm_system_rejected_terminal_state_refuses_approve_registration
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        system_count=0,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    system_id = X.create_submitted_system(api, bundle.site_id, bundle.company_id)
    rejected = A.data_of(
        api.reject_registration(
            system_id, {"rejection_reason": "Monitoring contract not on file."}, U.PERMIT_CLERK
        ),
        200,
    )
    A.assert_status(rejected, "REJECTED")

    response = api.approve_registration(system_id, U.PERMIT_CLERK)
    validate_error(response, E.ERR_INVALID_STATE, expected_status=409)

    system = X.get_system(api, system_id)
    A.assert_status(system, "REJECTED")
    assert system["rejection_reason"] == "Monitoring contract not on file.", (
        f"the recorded reason must survive the failed approval, got {system['rejection_reason']!r}"
    )
    A.assert_total_count(
        api.list_alarm_permits(U.PERMIT_CLERK, {"alarm_system_id": system_id}), 0
    )


def test_refused_dispatch_request_can_never_carry_an_incident(api):
    """A refused dispatch request is terminal evidence of a declined signal, so no incident may be opened against it.

    PRD §3.4: "The sibling branch is refusal: the supervisor supplies a coded `refusal_reason` of `ECV_DEFICIENT`, `RESPONSE_SUSPENDED`, `VERIFIED_RESPONSE_MISSING` or `DUPLICATE_SIGNAL`, the row moves `SUBMITTED → REFUSED` (terminal), the reason is stored, and no incident may ever reference that request."
    PRD §2.10: "The target resource must sit in a state from which the requested transition is declared. This covers every state machine in the program — alarm systems, permits, dispatch requests, incidents, hearing dockets, appeals, suspension orders, both invoice dimensions, monitoring companies and compliance reports — and any attempt to act on a resource already in a terminal state fails here with `ERR_INVALID_STATE`."

    Incident creation is declared only against a DISPATCHED request, so opening
    one on the terminal REFUSED row is refused with HTTP 409 and the premises
    still holds no incident at all.

    Design: Corner/state_machines/dispatch_request_refused_terminal_state_blocks_incident_creation
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    request_id = X.submit_dispatch_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    refused = A.data_of(
        api.refuse_dispatch_request(
            request_id, {"refusal_reason": "DUPLICATE_SIGNAL"}, U.DISPATCH_SUPERVISOR
        ),
        200,
    )
    A.assert_status(refused, "REFUSED")

    response = api.create_false_alarm_incident(
        F.false_alarm_incident_payload(
            request_id,
            cause_code="UNKNOWN",
            narrative="Attempting to open an incident on a refused request.",
        ),
        U.REVIEW_OFFICER,
    )
    validate_error(response, E.ERR_INVALID_STATE, expected_status=409)

    request = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    A.assert_status(request, "REFUSED")
    assert request["refusal_reason"] == "DUPLICATE_SIGNAL", (
        f"the coded refusal reason must be stored, got {request['refusal_reason']!r}"
    )
    A.assert_total_count(
        api.list_false_alarm_incidents(U.REVIEW_OFFICER, {"alarm_site_id": bundle.site_id}), 0
    )


def test_exempt_incident_cannot_be_administratively_voided(api):
    """An exempt determination is the final record of the occurrence and cannot be erased by an administrative void.

    PRD §3.5: "**Administrative void.** An administrator may void an incident recorded in error, supplying `void_reason`. The transition is available while the incident is in `REPORTED` or `UNDER_REVIEW` and lands in `VOIDED`, a terminal state."
    PRD §2.10: "The target resource must sit in a state from which the requested transition is declared. This covers every state machine in the program — alarm systems, permits, dispatch requests, incidents, hearing dockets, appeals, suspension orders, both invoice dimensions, monitoring companies and compliance reports — and any attempt to act on a resource already in a terminal state fails here with `ERR_INVALID_STATE`."

    Void is declared only from REPORTED or UNDER_REVIEW, so the attempt on the
    terminal EXEMPT row is refused with HTTP 409. An exempt ruling never assigns
    an occurrence number, so the premises' window count stayed at 0 throughout.

    Design: Corner/state_machines/false_alarm_incident_exempt_terminal_state_refuses_administrative_void
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    reported = X.create_reported_incident(
        api,
        bundle,
        bundle.system_id,
        "2026-09-15T03:09:00Z",
        cause_code="SEVERE_WEATHER",
    )
    X.set_clock(api, "2026-09-20T01:00:00Z")
    exempted = X.determine_exempt(
        api,
        reported.incident_id,
        "SEVERE_WEATHER",
        review_notes="NWS hail report matches the signal time.",
    )
    A.assert_status(exempted, "EXEMPT")

    response = api.void_incident(
        reported.incident_id,
        {"void_reason": "Records clerk wants the row removed entirely."},
        U.PROGRAM_ADMIN,
    )
    validate_error(response, E.ERR_INVALID_STATE, expected_status=409)

    incident = X.get_incident(api, reported.incident_id)
    A.assert_status(incident, "EXEMPT")
    assert incident["exempt_cause_code"] == "SEVERE_WEATHER", (
        f"the exempt cause must survive the failed void, got {incident['exempt_cause_code']!r}"
    )
    assert incident["occurrence_index"] is None, (
        f"an exempt incident never took an occurrence number, got {incident['occurrence_index']!r}"
    )
    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 0, (
        f"the exempt row never entered the counting set, got {site['chargeable_count_window']}"
    )


def test_validating_an_already_validated_request_is_refused(api):
    """Validation is not idempotent: a second call is refused and must not re-stamp the row with the retrying supervisor's identity.

    PRD §3.4: "A `PoliceDispatchSupervisor` may validate it, moving `SUBMITTED → VALIDATED` and stamping `validated_at` with the logical clock and `validated_by_user_id` with the acting `X-User-ID`."
    PRD §2.10: "The target resource must sit in a state from which the requested transition is declared. This covers every state machine in the program — alarm systems, permits, dispatch requests, incidents, hearing dockets, appeals, suspension orders, both invoice dimensions, monitoring companies and compliance reports — and any attempt to act on a resource already in a terminal state fails here with `ERR_INVALID_STATE`."

    Validation is declared only out of SUBMITTED, so the retry against the
    already VALIDATED row is refused with HTTP 409. The first validation happened
    at 2026-09-20T00:00:00Z and the clock has since moved on an hour, so a
    re-stamp would be visible; instead validated_at keeps the earlier instant,
    validated_by_user_id keeps the first supervisor, and the revision does not
    move.

    Design: Corner/state_machines/dispatch_request_validate_twice_second_call_returns_invalid_state
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    request_id = X.submit_dispatch_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    validate_success(api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR), 200)
    before = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    X.set_clock(api, "2026-09-20T01:00:00Z")

    response = api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR_2)
    validate_error(response, E.ERR_INVALID_STATE, expected_status=409)

    after = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    A.assert_status(after, "VALIDATED")
    assert after["validated_at"].startswith("2026-09-20T00:00:00"), (
        f"validated_at must not be re-stamped at the later clock, got {after['validated_at']!r}"
    )
    assert after["validated_by_user_id"] == U.DISPATCH_SUPERVISOR_ID, (
        f"the first validator must not be overwritten, got {after['validated_by_user_id']!r}"
    )
    A.assert_version_unchanged(before, after)


def test_cancelling_a_submitted_request_is_not_a_declared_transition(api):
    """Cancellation is declared only out of VALIDATED, so a company standing down a still-submitted request is refused and the row cannot jump straight to the terminal state.

    PRD §3.4: "Cancellation moves `VALIDATED → CANCELLED` (terminal) with an optional `cancellation_reason`; a company operator cancelling must be the request's own monitoring company, else `ERR_NOT_RESOURCE_OWNER`, and a cancelled request yields no chargeable incident and is excluded from the company's system-side dispatch count for reporting purposes."
    PRD §2.10: "The target resource must sit in a state from which the requested transition is declared. This covers every state machine in the program — alarm systems, permits, dispatch requests, incidents, hearing dockets, appeals, suspension orders, both invoice dimensions, monitoring companies and compliance reports — and any attempt to act on a resource already in a terminal state fails here with `ERR_INVALID_STATE`."

    The request has never been validated, so the cancel branch is not declared
    from where it stands; the attempt fails with HTTP 409 and the row is still
    SUBMITTED at its creation revision of 1.

    Design: Corner/state_machines/dispatch_request_cancel_from_submitted_is_not_a_declared_transition
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    request_id = X.submit_dispatch_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")

    response = api.cancel_dispatch_request(
        request_id,
        bundle.operator_headers,
        {"cancellation_reason": "Keyholder confirmed a false trip before units were assigned."},
    )
    validate_error(response, E.ERR_INVALID_STATE, expected_status=409)

    request = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    A.assert_status(request, "SUBMITTED")
    assert request["version"] == 1, (
        f"a refused cancellation leaves the request at version 1, got {request['version']}"
    )


def test_report_correction_cycles_flagged_through_corrected_back_to_submitted(api):
    """One correction traverses two transitions inside a single request, so the report is observably back in SUBMITTED with its reviewed fields cleared and its metrics recomputed.

    PRD §3.10: "The correction overwrites the reported counts, increments `correction_count`, and recomputes `variance_count`, `variance_pct`, `period_accuracy`, `period_ecv_rate` and `period_score` from scratch. The row then cycles onward inside the same request: `VARIANCE_FLAGGED → CORRECTED`, and immediately `CORRECTED → SUBMITTED` with `reviewed_at`, `reviewed_by_user_id` and `variance_notes` cleared, so the reviewer must rule again on the corrected figures."
    PRD §3.10: "`system_dispatch_count` is the number of dispatch requests attributed to that company whose `occurred_at` falls inside the closed period interval and whose status is not `CANCELLED` — a `REFUSED` request still counts, because the company did ask for dispatch even though the city declined, and only a cancellation removes the ask."
    PRD §3.10: "`variance_count` is the absolute difference between `reported_dispatch_count` and `system_dispatch_count`, so over-reporting and under-reporting are penalised identically. `variance_pct` is that count divided by the greater of 1 and `system_dispatch_count`, at four decimal places. `period_accuracy` is 1 minus the lesser of 1 and `variance_pct`, at four decimal places, so accuracy floors at zero however wild the claim. `period_ecv_rate` is the lesser of 1 and `ecv_attempt_count` divided by the greater of 1 and `reported_dispatch_count`, at four decimal places, so extra verification attempts earn no credit above a rate of 1. `period_score` is 0.6 times `period_accuracy` plus 0.4 times `period_ecv_rate`, rounded half up to two decimal places."
    PRD §3.10: "Flagging requires an actual discrepancy — `variance_pct` must be strictly above 0.1000, else `ERR_NO_REPORTABLE_VARIANCE` — and moves the report to `VARIANCE_FLAGGED`, storing the `variance_notes` and incrementing `consecutive_flagged_report_count`."

    Exactly one dispatch request sits inside the September period and it was not
    cancelled, so system_dispatch_count is 1 against a claim of 10:
    variance_count is the absolute difference 9, variance_pct is 9 divided by the
    greater of 1 and 1, that is 9.0000, and period_accuracy is 1 minus the lesser
    of 1 and 9.0000, flooring at 0.0000. The ECV rate is the lesser of 1 and 10
    divided by 10, which is 1.0000, so the period score is 0.6 times 0 plus 0.4
    times 1 = 0.40. That variance_pct of 9.0000 is strictly above 0.1000 so the
    flag is admissible. Correcting the claim down to a truthful 1 dispatch with 1
    ECV attempt makes variance_count 0, variance_pct 0.0000 and period_accuracy
    1.0000, and takes correction_count from 0 to 1, still strictly below the
    two-correction bound.

    Design: Corner/state_machines/compliance_report_cycles_variance_flagged_to_corrected_back_to_submitted
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    X.create_dispatched_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-30T00:00:00Z")
    report_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-09-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        reported_dispatch_count=10,
        reported_cancellation_count=0,
        ecv_attempt_count=10,
    )
    flagged = X.review_compliance_report(
        api,
        report_id,
        "FLAG_VARIANCE",
        variance_notes="Reported ten dispatches against one recorded request.",
    )

    A.assert_status(flagged, "VARIANCE_FLAGGED")
    assert flagged["system_dispatch_count"] == 1, (
        f"one uncancelled request sits in the period, got {flagged['system_dispatch_count']}"
    )
    assert flagged["variance_count"] == 9, (
        f"the absolute difference between 10 and 1 is 9, got {flagged['variance_count']}"
    )
    A.assert_ratio_4dp(flagged["variance_pct"], 9.0, "variance_pct")
    A.assert_ratio_4dp(flagged["period_accuracy"], 0.0, "period_accuracy")
    A.assert_ratio_4dp(flagged["period_ecv_rate"], 1.0, "period_ecv_rate")
    A.assert_score_2dp(flagged["period_score"], 0.40, "period_score")
    company_after_flag = X.get_company(api, bundle.company_id)
    assert company_after_flag["consecutive_flagged_report_count"] == 1, (
        "flagging increments the company's consecutive flagged run, got "
        f"{company_after_flag['consecutive_flagged_report_count']}"
    )

    corrected = A.data_of(
        api.correct_compliance_report(
            report_id,
            {
                "reported_dispatch_count": 1,
                "reported_cancellation_count": 0,
                "ecv_attempt_count": 1,
            },
            bundle.operator_headers,
        ),
        200,
    )

    A.assert_status(corrected, "SUBMITTED")
    assert corrected["correction_count"] == 1, (
        f"one correction has been taken, got {corrected['correction_count']}"
    )
    assert corrected["variance_count"] == 0, (
        f"the corrected claim matches the record, got {corrected['variance_count']}"
    )
    A.assert_ratio_4dp(corrected["variance_pct"], 0.0, "variance_pct")
    A.assert_ratio_4dp(corrected["period_accuracy"], 1.0, "period_accuracy")
    for field in ("reviewed_at", "reviewed_by_user_id", "variance_notes"):
        assert corrected[field] is None, (
            f"{field} must be cleared so the reviewer rules again, got {corrected[field]!r}"
        )


def test_invoice_money_and_dunning_dimensions_advance_independently(api):
    """The nightly run moves an overdue invoice's dunning axis and adds the one-time late penalty, then full settlement moves only the money axis, leaving the stage where it stood until the next run.

    PRD §3.8: "**Two dimensions on one row.** `payment_status` tracks the money and `collections_stage` tracks the dunning, and they advance independently. An invoice can be `REFERRED` and still reach `PAID`; it can be `PAID` while still sitting at `FINAL_NOTICE` until the next nightly run resettles the stage. Neither dimension is derivable from the other."
    PRD §3.8: "The dunning dimension starts at `CURRENT` and terminates at `WRITTEN_OFF`. `days_delinquent` is the whole days between `due_on` and the logical clock, floored at zero. The nightly run advances `CURRENT → NOTICE` once `days_delinquent` is at least 1, and `NOTICE → FINAL_NOTICE` once it is at least 30; both steps require `outstanding_cents` above zero and require that the linked incident, when there is one, is not in `APPEALED`. The first step is where the late penalty is added, exactly once per invoice; the second adds no further penalty and merely makes the invoice referral-eligible once `days_delinquent` reaches `delinquency_days`."
    PRD §3.8: "Step two: `late_penalty_cents` is that principal times `late_penalty_pct`, rounded half up, and is added into `assessed_cents` — once per invoice, never twice."
    PRD §3.8: "Settlement runs the ladder backwards: the nightly resettlement moves `NOTICE → CURRENT` or `FINAL_NOTICE → CURRENT` once `outstanding_cents` has become 0, dunning stops, and any late penalty already assessed is **not** refunded."
    PRD §3.8: "Settlement — `UNPAID → PAID` or `PARTIALLY_PAID → PAID` — occurs exactly when `paid_cents` plus `adjusted_cents` equals `assessed_cents` after the write, whether that is reached by an allocation covering the remainder or by a `WAIVE` adjustment; `outstanding_cents` becomes 0, the stage resettles to `CURRENT` on the next nightly run, and when every invoice for the premises is `PAID` a `REINSTATEMENT_PENDING` suspension order becomes liftable."

    The permit issue invoice was issued at 2026-08-01 for 5000 plus the 500-cent
    administrative floor, that is 5500, with due_on at 2026-08-01 plus the
    invoice_due_days of 30 whole days, which is 2026-08-31. At the clock of
    2026-09-05 that is 5 whole days past due, so days_delinquent is 5, which is at
    least 1 and pushes the stage from CURRENT to NOTICE; the late penalty is the
    5500-cent outstanding principal times the late_penalty_pct of 0.10 = 550,
    lifting assessed_cents to 5500 + 550 = 6050. A single tendered payment of
    exactly 6050 allocates in full, so paid_cents equals assessed_cents and the
    money axis settles to PAID with nothing credited, while the dunning axis is
    still sitting at NOTICE. Only the next nightly run resettles the stage to
    CURRENT, and it leaves the 550-cent penalty in place.

    Design: Corner/state_machines/penalty_invoice_payment_and_dunning_dimensions_advance_independently
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    issued = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(issued) == 1, f"approval issues exactly one permit fee invoice, got {len(issued)}"
    invoice_id = issued[0]["id"]
    assert issued[0]["due_on"].startswith("2026-08-31"), (
        f"due_on is the issue date plus 30 whole days, got {issued[0]['due_on']!r}"
    )

    X.set_clock(api, "2026-09-05T00:00:00Z")
    X.run_nightly(api)

    dunned = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(
        dunned,
        subtotal_cents=5000,
        admin_fee_cents=500,
        assessed_cents=6050,
        paid_cents=0,
        outstanding_cents=6050,
        payment_status="UNPAID",
        collections_stage="NOTICE",
    )
    A.assert_money_cents(dunned["late_penalty_cents"], 550, "late_penalty_cents")
    assert dunned["days_delinquent"] == 5, (
        f"2026-09-05 is five whole days after 2026-08-31, got {dunned['days_delinquent']}"
    )

    payment = A.data_of(
        api.create_payment_record(
            F.payment_record_payload(
                bundle.site_id,
                6050,
                "2026-09-05T00:00:00Z",
                X.site_version(api, bundle.site_id),
                method="ACH",
                allocation_mode="AUTO_WATERFALL",
            ),
            U.BILLING_CLERK,
        ),
        201,
    )
    A.assert_money_cents(payment["allocated_cents"], 6050, "allocated_cents")
    A.assert_money_cents(payment["credited_cents"], 0, "credited_cents")
    A.assert_cash_conservation(payment)

    settled = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(
        settled,
        assessed_cents=6050,
        paid_cents=6050,
        outstanding_cents=0,
        payment_status="PAID",
        collections_stage="NOTICE",
    )

    X.run_nightly(api)
    resettled = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(
        resettled, payment_status="PAID", outstanding_cents=0, collections_stage="CURRENT"
    )
    A.assert_money_cents(resettled["late_penalty_cents"], 550, "late_penalty_cents")
    A.assert_money_cents(resettled["assessed_cents"], 6050, "assessed_cents")
