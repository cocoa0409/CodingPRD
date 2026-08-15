"""Disclosure events, the statutory-disqualification cascade (three links
plus the OBA fan-out), and representative termination (PRD §3.6, §3.1).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    close_inspection_now,
    create_disclosure_payload,
    create_plan_for_rep,
    decide_payload,
    get_branch,
    get_rep,
    make_active_plan,
    make_activity,
    make_branch,
    make_branch_with_rep,
    make_rep,
    make_sd_disclosure,
    acknowledge_disclosure,
    make_sd_rep,
    make_suspended_oba,
    schedule_and_start_inspection,
    schedule_inspection,
    set_clock,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
PRINCIPAL_A = TEST_USERS["principal_a_headers"]
ANY = TEST_USERS["any_headers"]

PST = "PRIVATE_SECURITIES_TRANSACTION"
OBA = "OUTSIDE_BUSINESS_ACTIVITY"


# ─── depth-3 SD cascade ───────────────────────────────

class TestSdAckCascadeChain:
    def _setup(self):
        """Branch (created at the default clock) + rep + a SCHEDULED
        inspection dated beyond the accelerated due date + FILED SD
        disclosure, ready for acknowledgement."""
        branch = make_branch(name="SD Branch", region="W")
        rep = make_rep(branch["id"], crd_number="200001", full_name="SD Rep")
        inspection = validate_success(
            schedule_inspection(branch["id"], scheduled_date="2027-03-15"), 201
        )
        event = make_sd_disclosure(rep["id"], event_type="REGULATORY_BAR",
                                   event_date="2026-08-02")
        return branch, rep, inspection, event

    def test_ack_sets_rep_flag_and_accelerates_branch_cycle(self, api,
                                                            any_headers):
        """PRD §3.6: "The cascade's first link acts on the representative:
        `is_statutorily_disqualified` becomes true (and never auto-reverts),
        `supervision_tier` becomes `HEIGHTENED`, and the representative's
        `version` increments by one." and "`sd_rep_count` is recomputed, and
        when the count is at least one the branch's inspection cycle
        accelerates — `inspection_cycle_months` is reduced to the lesser of
        its current value and 6, `next_inspection_due_date` is recomputed on
        the shortened cycle per §3.1". Base = branch creation date
        2026-08-01 (no closed inspection), so 2026-08-01 + 6 months =
        2027-02-01.

        Design: Difficulty/transitive_cascade/cascade_sd_ack_chain
        """
        branch, rep, _inspection, event = self._setup()
        acked = acknowledge_disclosure(event["id"])
        assert acked["status"] == "ACKNOWLEDGED"

        rep_after = get_rep(rep["id"])
        assert rep_after["is_statutorily_disqualified"] is True
        assert rep_after["supervision_tier"] == "HEIGHTENED"

        branch_after = get_branch(branch["id"])
        assert branch_after["inspection_cycle_months"] == 6
        assert branch_after["sd_rep_count"] == 1
        assert branch_after["next_inspection_due_date"] == "2027-02-01"

    def test_ack_pulls_in_scheduled_inspection_beyond_new_due_date(self, api,
                                                                   any_headers):
        """PRD §3.6: "if the branch has an inspection in `SCHEDULED` whose
        `scheduled_date` falls after the freshly computed
        `next_inspection_due_date`, that inspection's `scheduled_date` is
        pulled forward to the due date, and the inspection's `version`
        increments by one." The inspection scheduled 2027-03-15 is pulled to
        the recomputed due date 2027-02-01.

        Design: Difficulty/transitive_cascade/cascade_sd_ack_chain
        """
        branch, rep, inspection, event = self._setup()
        acknowledge_disclosure(event["id"])

        inspection_after = validate_success(
            api.get_inspection(inspection["id"], ANY), 200
        )
        assert inspection_after["scheduled_date"] == "2027-02-01"
        assert inspection_after["version"] == inspection["version"] + 1


# ─── cycle constant selection ─────────────────────────

def test_cycle_acceleration_recomputes_due_date_on_same_base(api, any_headers):
    """PRD §3.1: "Its base date is the `completed_date` of the branch's most
    recently closed inspection — ties broken by earliest inspection creation
    — or, when the branch has never had a closed inspection, the branch's
    creation date. The cycle length is 6 months whenever the branch's
    `sd_rep_count` is at least one, and the branch's
    `inspection_cycle_months` otherwise." The same completed date 2026-05-01
    yields 2027-05-01 under the 12-month cycle and 2026-11-01 after the
    cascade switches the branch to the accelerated 6-month cycle.

    Design: Corner/calculations/dual_branch_cycle_acceleration
    """
    branch = make_branch(name="CY Branch", region="W")
    rep = make_rep(branch["id"], crd_number="920002", full_name="CY Rep")
    set_clock("2026-05-01T09:00:00Z")
    inspection = schedule_and_start_inspection(branch["id"], "2026-05-01")
    closed = validate_success(close_inspection_now(inspection["id"]), 200)
    assert closed["status"] == "CLOSED"

    assert get_branch(branch["id"])["next_inspection_due_date"] == "2027-05-01"

    event = make_sd_disclosure(rep["id"], event_type="REGULATORY_BAR",
                               event_date="2026-05-01")
    acknowledge_disclosure(event["id"])

    branch_after = get_branch(branch["id"])
    assert branch_after["sd_rep_count"] == 1
    assert branch_after["inspection_cycle_months"] == 6
    assert branch_after["next_inspection_due_date"] == "2026-11-01"


# ─── derived-field reconciliation on termination ──────

def test_sd_count_decrements_but_cycle_stays_accelerated(api, any_headers):
    """PRD §3.1: "the branch's `sd_rep_count` is recomputed — decrementing if
    the terminated representative had been SD-flagged" and "Cycle
    acceleration is sticky: once `inspection_cycle_months` has been reduced
    to 6 by the disqualification cascade of §3.6, it never reverts
    automatically, even if the branch's `sd_rep_count` later falls back to
    zero."

    Design: Corner/calculations/sd_rep_count_decrement_on_termination
    """
    branch, rep, _event = make_sd_rep(crd_number="920006")
    assert get_branch(branch["id"])["sd_rep_count"] == 1
    assert get_branch(branch["id"])["inspection_cycle_months"] == 6

    validate_success(api.terminate_representative(rep["id"], PRINCIPAL_A), 200)

    branch_after = get_branch(branch["id"])
    assert branch_after["sd_rep_count"] == 0
    assert branch_after["inspection_cycle_months"] == 6


# ─── disclosure filing timeliness ─────────────────────

def test_file_disclosure_late_flag(api, any_headers):
    """PRD §3.6: "`filing_deadline`, which is the `event_date` plus 30 days"
    and "stamping `filed_at` from the logical clock and computing `is_late`,
    true when the calendar date of `filed_at` falls after the
    `filing_deadline`". At the default filing date 2026-08-01, an event dated
    2026-07-01 (deadline 2026-07-31) files late; one dated 2026-07-15
    (deadline 2026-08-14) does not.

    Design: Corner/state_machines/file_disclosure_late_flag
    """
    _branch, rep = make_branch_with_rep(region="S", crd_number="910013")
    late = make_sd_disclosure(rep["id"], event_type="CIVIL_JUDGMENT",
                              event_date="2026-07-01")
    on_time = make_sd_disclosure(rep["id"], event_type="BANKRUPTCY",
                                 event_date="2026-07-15")
    assert late["filing_deadline"] == "2026-07-31"
    assert on_time["filing_deadline"] == "2026-08-14"
    assert late["is_late"] is True
    assert on_time["is_late"] is False


def test_acknowledge_draft_disclosure_rejected(api, any_headers):
    """PRD §3.6: acknowledgement is "also guarded by
    `ERR_DISCLOSURE_INVALID_STATE` from non-`FILED` states" — a DRAFT event
    cannot be acknowledged, and the rejected call fires no cascade
    ("`is_statutorily_disqualified` becomes true" only on acknowledgement).

    Design: Corner/state_machines/disclosure_ack_from_draft_rejected
    """
    _branch, rep = make_branch_with_rep(region="E", crd_number="910014")
    event = validate_success(
        api.create_disclosure_event(
            create_disclosure_payload(rep["id"], event_type="FELONY_CONVICTION",
                                      event_date="2026-07-01"),
            ANALYST,
        ),
        201,
    )
    assert event["status"] == "DRAFT"

    res = api.acknowledge_disclosure_event(event["id"], PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_DISCLOSURE_INVALID_STATE)
    assert get_rep(rep["id"])["is_statutorily_disqualified"] is False


# ─── immediate consistency ────────────────────────────

def test_cascade_visible_on_immediately_following_reads(api, any_headers):
    """PRD §2.7: "Recomputation is atomic with the triggering event." PRD
    §3.6: acknowledgement moves the event to ACKNOWLEDGED, sets
    "`supervision_tier` becomes `HEIGHTENED`" on the representative, and
    reduces the branch cycle ("`inspection_cycle_months` is reduced to the
    lesser of its current value and 6") — all visible on the very next reads.

    Design: Corner/consistency/immediate_cascade_visibility
    """
    branch, rep = make_branch_with_rep(region="S", crd_number="970001")
    event = make_sd_disclosure(rep["id"], event_type="REGULATORY_BAR",
                               event_date="2026-08-01")
    acked = acknowledge_disclosure(event["id"])
    assert acked["status"] == "ACKNOWLEDGED"

    assert get_rep(rep["id"])["supervision_tier"] == "HEIGHTENED"
    assert get_branch(branch["id"])["inspection_cycle_months"] == 6


# ─── termination invariants and cascades ──────────────

def test_termination_preserves_pst_fee_history(api, any_headers):
    """PRD §3.1: on termination "every OutsideActivityRequest of the
    representative that sits in `SUBMITTED` or `SUSPENDED_REVIEW` is moved to
    `WITHDRAWN` (no count or fee adjustments apply, because none of those
    requests had been approved)" — already-approved requests are historical
    and their accrued fees and counts are not clawed back.

    Design: Corner/calculations/invariant_pst_fee_conservation
    """
    _branch, rep = make_branch_with_rep(region="E", crd_number="920003")
    for label in ("A", "B"):
        activity = make_activity(rep, activity_type=PST, description=label,
                                 compensation_expected=True,
                                 estimated_gross_comp_cents=33333)
        validate_success(
            api.decide_outside_activity(activity["id"], decide_payload("APPROVE"),
                                        PRINCIPAL_A),
            200,
        )
    assert get_rep(rep["id"])["pst_fee_total_cents"] == 1666
    assert get_rep(rep["id"])["active_approved_activity_count"] == 2

    validate_success(api.terminate_representative(rep["id"], PRINCIPAL_A), 200)

    rep_after = get_rep(rep["id"])
    assert rep_after["status"] == "TERMINATED"
    assert rep_after["pst_fee_total_cents"] == 1666
    assert rep_after["active_approved_activity_count"] == 2


def test_termination_withdraws_only_pending_activities(api, any_headers):
    """PRD §3.1: "every OutsideActivityRequest of the representative that
    sits in `SUBMITTED` or `SUSPENDED_REVIEW` is moved to `WITHDRAWN`" — an
    APPROVED request is not cascaded, and the approved-activity count keeps
    reflecting it.

    Design: Corner/cross_cutting/cascade_rep_terminate_withdraws_activities
    """
    _branch, rep = make_branch_with_rep(region="E", crd_number="960001")
    pending = make_activity(rep, activity_type=OBA, description="pending one")
    approved = make_activity(rep, activity_type=OBA, description="approved one")
    validate_success(
        api.decide_outside_activity(approved["id"], decide_payload("APPROVE"),
                                    PRINCIPAL_A),
        200,
    )

    validate_success(api.terminate_representative(rep["id"], PRINCIPAL_A), 200)

    assert validate_success(
        api.get_outside_activity(pending["id"], ANY), 200
    )["status"] == "WITHDRAWN"
    assert validate_success(
        api.get_outside_activity(approved["id"], ANY), 200
    )["status"] == "APPROVED"
    assert get_rep(rep["id"])["active_approved_activity_count"] == 1


def test_terminate_terminated_rep_rejected(api, any_headers):
    """PRD §3.1: "invoking termination on a representative in any other state
    — including an already `TERMINATED` one — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/errors/terminate_terminated_rep_rejected
    """
    _branch, rep = make_branch_with_rep(region="W", crd_number="980001")
    validate_success(api.terminate_representative(rep["id"], PRINCIPAL_A), 200)
    res = api.terminate_representative(rep["id"], PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


# ─── resume + conditional approval end to end ─────────

def test_heightened_plan_activate_resume_and_conditional_approval(api,
                                                                  any_headers):
    """PRD §3.7: "An activated plan is the key that unlocks the gates of
    §3.4: approval decisions for a disqualified representative, and
    resumption of suspended requests, both consult it." PRD §3.4: "An
    `APPROVE_WITH_CONDITIONS` decision applies the same gates and side
    effects, additionally requiring the payload's `conditions` to be a
    non-empty array, which is then recorded on the request; the resulting
    status is `APPROVED_WITH_CONDITIONS`."

    Design: Corner/state_machines/heightened_plan_activate_and_resume_oba
    """
    _branch, rep, activity = make_suspended_oba(
        crd_number="910012", event_type="SECURITIES_MISDEMEANOR",
        activity_overrides={"activity_type": OBA, "description": "advisory"},
    )
    assert activity["status"] == "SUSPENDED_REVIEW"

    plan = validate_success(
        create_plan_for_rep(rep["id"], start_date="2026-08-02",
                            end_date="2027-08-01"),
        201,
    )
    validate_success(api.activate_supervision_plan(plan["id"], PRINCIPAL_A), 200)

    resumed = validate_success(
        api.resume_outside_activity(activity["id"], PRINCIPAL_A), 200
    )
    assert resumed["status"] == "SUBMITTED"

    decided = validate_success(
        api.decide_outside_activity(
            activity["id"],
            {"decision": "APPROVE_WITH_CONDITIONS",
             "conditions": ["NO_SOLICITATION"]},
            PRINCIPAL_A,
        ),
        200,
    )
    assert decided["status"] == "APPROVED_WITH_CONDITIONS"
    assert decided.get("conditions") == ["NO_SOLICITATION"]
