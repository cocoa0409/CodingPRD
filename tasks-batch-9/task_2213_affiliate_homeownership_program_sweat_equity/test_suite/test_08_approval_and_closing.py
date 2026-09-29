"""Approval, the subsidy ledger, denial's compensating entry, and settlement."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import (
    ADMIN,
    APPROVER,
    COMMITTEE_ALICE_USER_ID,
    COORDINATOR,
    CREW_LEAD,
    OFFICER,
    make_headers,
)

_OFFICER_ROLE = "MortgageOfficer"


def test_crediting_the_final_hour_carries_the_member_ledger_up_to_the_household(api):
    """Hop one writes the member, hop two satisfies the household, hop three flips a dimension.

    "A successful credit then cascades four hops, all inside the same request. The
    member's `credited_hours_to_date` rises by the credited hours. The household's
    `sweat_equity_credited_hours` rises by the same amount, its
    `family_member_credited_hours` is recomputed, and `sweat_equity_satisfied` is
    re-derived as whether `sweat_equity_credited_hours` has reached
    `sweat_equity_required_hours` — equality satisfies the requirement. If the
    household's `selection_status` is `SELECTED` and its credited hours are now above
    zero, it advances `SELECTED → PARTNERSHIP_ACTIVE`; the first credited hour is
    what turns a selected family into an active partner."

    Design: Difficulty/transitive_cascade/credit_cascade_member_to_household_to_readiness_to_mortgage
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    X.setup_completed_education(api, household["id"])
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    X.approve_application(api, application["id"], program["id"])
    X.advance_clock(api, "2026-08-05T00:00:00.000Z")
    entry = X.claim_hours(api, household["id"], member["id"], hours_claimed=12.0, work_date="2026-08-04T00:00:00.000Z")
    X.verify_hours(api, entry["id"])

    credited = validate_success(api.credit_entry(entry["id"], headers=COORDINATOR))
    assert credited["status"] == C.ENTRY_CREDITED
    assert credited["credit_weight"] == 1.0
    assert credited["hours_credited"] == 12.0

    reread_member = validate_success(api.get_member(member["id"], headers=COORDINATOR))
    assert reread_member["credited_hours_to_date"] == 12.0

    reread_household = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert reread_household["sweat_equity_credited_hours"] == 12.0
    # Twelve credited against twelve required: equality satisfies.
    assert reread_household["sweat_equity_satisfied"] is True
    assert reread_household["selection_status"] == C.SELECTION_PARTNERSHIP_ACTIVE
    assert reread_household["partnership_readiness"] == C.READINESS_CLOSING_READY


def test_only_the_completed_cascade_clears_the_approved_mortgage_to_close(api):
    """The fourth hop is unreachable without the first three in the same request.

    "If the household's `partnership_readiness` is `EDUCATION_COMPLETE` and the
    requirement has just been satisfied, readiness advances `EDUCATION_COMPLETE →
    CLOSING_READY`, and that in turn drives every `APPROVED` mortgage application of
    the household to `CLEARED_TO_CLOSE`."

    The approval itself explains why the file was left waiting: "If the household is
    already `CLOSING_READY`, the application continues immediately to
    `CLEARED_TO_CLOSE` inside the same request; otherwise it waits in `APPROVED` for
    the readiness dimension to catch up, as §3.4 and §3.5 describe."

    Design: Difficulty/transitive_cascade/credit_cascade_member_to_household_to_readiness_to_mortgage
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    X.setup_completed_education(api, household["id"])
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    X.approve_application(api, application["id"], program["id"])
    X.advance_clock(api, "2026-08-05T00:00:00.000Z")
    entry = X.claim_hours(api, household["id"], member["id"], hours_claimed=12.0, work_date="2026-08-04T00:00:00.000Z")
    X.verify_hours(api, entry["id"])

    before = validate_success(api.get_application(application["id"], headers=OFFICER))
    # Education alone was not enough: the hours had not been credited yet.
    assert before["status"] == C.APP_APPROVED

    validate_success(api.credit_entry(entry["id"], headers=COORDINATOR))

    after = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert after["status"] == C.APP_CLEARED_TO_CLOSE

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["subsidy_committed_cents"] == 1_950_000
    assert reread_program["subsidy_available_cents"] == 3_050_000
    # The commitment was made at approval and the clearance does not re-book it.
    assert reread_program["program_posture"] == C.POSTURE_OPEN


def test_the_reviewer_who_scored_the_household_is_refused_before_the_pool_is_consulted(api):
    """Two gates fail on one call and the safety gate answers.

    "The program's posture must not be `FROZEN`; the acting officer must not have
    authored a submitted review on the household; and the program's
    `subsidy_available_cents` must be at least the application's
    `silent_second_amount_cents`."

    A 1,000,000-cent pool cannot carry a 1,950,000-cent silent second, so the
    fiscal gate is live too — but the acting identity authored the household's
    reviews, and that refusal is the one returned.

    Design: Difficulty/priority_pair_validation_conflict/segregation_priority_18_beats_subsidy_exhaustion_priority_38
    """
    program = X.setup_program(api, subsidy_pool_cents=1_000_000)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    assert application["silent_second_amount_cents"] == 1_950_000

    before = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert before["program_posture"] == C.POSTURE_OPEN
    assert before["subsidy_available_cents"] == 1_000_000

    response = api.approve_application(
        application["id"],
        F.approval_payload(before["version"]),
        headers=make_headers(COMMITTEE_ALICE_USER_ID, _OFFICER_ROLE),
    )
    validate_error(response, E.ERR_SEGREGATION_OF_DUTIES, 403)

    reread = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert reread["status"] == C.APP_UNDERWRITING
    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["subsidy_committed_cents"] == 0
    assert reread_program["subsidy_available_cents"] == 1_000_000


def test_a_clean_officer_on_the_same_short_pool_reaches_the_fiscal_refusal(api):
    """The losing rule was genuinely live; only the ordering hid it.

    "A silent second strictly larger than the available balance is refused with
    `ERR_SUBSIDY_POOL_EXHAUSTED`." Removing the conflicting reviewer identity — and
    changing nothing else about the money — surfaces exactly that refusal, so the
    first test's outcome was a priority decision rather than an absent condition.

    Design: Difficulty/priority_pair_validation_conflict/segregation_priority_18_beats_subsidy_exhaustion_priority_38
    """
    program = X.setup_program(api, subsidy_pool_cents=1_000_000)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])

    response = api.approve_application(
        application["id"],
        F.approval_payload(X.program_version(api, program["id"])),
        headers=APPROVER,
    )
    validate_error(response, E.ERR_SUBSIDY_POOL_EXHAUSTED, 409)

    reread = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert reread["status"] == C.APP_UNDERWRITING
    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["subsidy_committed_cents"] == 0
    assert reread_program["subsidy_available_cents"] == 1_000_000


def test_a_pool_one_cent_short_of_the_silent_second_refuses_the_approval(api):
    """One cent decides an approval, and the refusal bumps nothing.

    "The program's `subsidy_available_cents` must be at least the application's
    `silent_second_amount_cents`, where equality approves ... A silent second
    strictly larger than the available balance is refused with
    `ERR_SUBSIDY_POOL_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/subsidy_available_one_cent_below_versus_exactly_equal_to_silent_second
    """
    program = X.setup_program(api, subsidy_pool_cents=1_949_999)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    assert application["escrow_monthly_cents"] == 20_625
    assert application["affordable_pi_payment_cents"] == 54_375
    assert application["term_months"] == 240
    assert application["first_mortgage_principal_cents"] == 13_050_000
    assert application["silent_second_amount_cents"] == 1_950_000

    before = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert before["subsidy_available_cents"] == 1_949_999

    validate_error(
        api.approve_application(application["id"], F.approval_payload(before["version"]), headers=APPROVER),
        E.ERR_SUBSIDY_POOL_EXHAUSTED,
        409,
    )

    after = validate_success(api.get_program(program["id"], headers=ADMIN))
    # A refused approval books nothing, so the program row was never written.
    assert after["version"] == before["version"]
    assert after["subsidy_committed_cents"] == 0
    assert after["subsidy_available_cents"] == 1_949_999


def test_a_pool_exactly_equal_to_the_silent_second_approves_and_restricts_the_posture(api):
    """Equality approves, and it drains the pool to precisely zero.

    "An approval that consumes the pool down to exactly zero succeeds and drives
    `program_posture` to `SUBSIDY_RESTRICTED`. On success the program's
    `subsidy_committed_cents` rises by the silent second, `subsidy_available_cents`
    and `program_posture` are recomputed, and the program's `version` increments."

    Design: Difficulty/boundary_precision_check/subsidy_available_one_cent_below_versus_exactly_equal_to_silent_second
    """
    program = X.setup_program(api, subsidy_pool_cents=1_949_999)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    validate_error(
        api.approve_application(
            application["id"], F.approval_payload(X.program_version(api, program["id"])), headers=APPROVER
        ),
        E.ERR_SUBSIDY_POOL_EXHAUSTED,
        409,
    )

    topped_up = validate_success(
        api.adjust_subsidy_pool(
            program["id"],
            F.pool_adjustment_payload(
                C.POOL_ACTION_TOP_UP,
                X.program_version(api, program["id"]),
                delta_cents=1,
                memo="One-cent top-up to land the pool exactly on the silent second",
            ),
            headers=ADMIN,
        )
    )
    assert topped_up["subsidy_available_cents"] == 1_950_000

    approved = validate_success(
        api.approve_application(
            application["id"], F.approval_payload(X.program_version(api, program["id"])), headers=APPROVER
        )
    )
    assert approved["status"] == C.APP_APPROVED
    assert approved["silent_second_amount_cents"] == 1_950_000
    assert approved["resale_restriction_months"] == 240

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["subsidy_pool_cents"] == 1_950_000
    assert reread_program["subsidy_committed_cents"] == 1_950_000
    assert reread_program["subsidy_disbursed_cents"] == 0
    assert reread_program["subsidy_available_cents"] == 0
    assert reread_program["program_posture"] == C.POSTURE_SUBSIDY_RESTRICTED


def test_a_closing_waits_for_the_hold_to_lift_and_the_build_to_finish(api):
    """A cleared file is still blocked by a state two entities away.

    "Four conditions must hold: the build site's `readiness_status` must be
    `COMPLETED`, or the close is refused with `ERR_SITE_NOT_COMPLETED`."

    The hold is what keeps the site short of that: "The transition captures the
    outgoing readiness value into `pre_hold_readiness_status`, moves
    `readiness_status` to `SAFETY_HOLD`, and sets `safety_posture` to `HOLD`."
    Only a release restores it — "Releasing the hold with a `posture` of `CLEAR`
    restores `readiness_status` from `pre_hold_readiness_status`" — and only then can
    "The final `step` of `FINAL_INSPECTION`" close the build, "moving the site
    `UNDER_CONSTRUCTION → COMPLETED`".

    Design: Difficulty/cross_entity_state_dependency/mortgage_close_blocked_until_build_site_leaves_safety_hold_and_completes
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    X.approve_application(api, application["id"], program["id"])
    education = X.setup_completed_education(api, household["id"])
    assert education["expires_on"] == "2028-07-31T00:00:00.000Z"
    X.advance_clock(api, "2026-08-05T00:00:00.000Z")
    X.setup_credited_entry(
        api, household["id"], member["id"], hours_claimed=12.0, work_date="2026-08-04T00:00:00.000Z"
    )
    construction = X.start_construction(
        api, program["id"], site["id"], start_at="2026-08-20T08:00:00.000Z", end_at="2026-08-20T16:00:00.000Z"
    )
    validate_success(
        api.cancel_shift(construction["shift"]["id"], F.cancellation_payload(), headers=CREW_LEAD)
    )

    site_before = validate_success(api.get_build_site(site["id"], headers=OFFICER))
    assert site_before["readiness_status"] == C.SITE_UNDER_CONSTRUCTION
    assert site_before["safety_posture"] == C.POSTURE_CLEAR
    app_before = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert app_before["status"] == C.APP_CLEARED_TO_CLOSE

    held = validate_success(
        api.set_safety_posture(
            site["id"],
            F.safety_posture_payload(C.POSTURE_HOLD, incident_note="Trench collapse near the north footing"),
            headers=CREW_LEAD,
        )
    )
    assert held["readiness_status"] == C.SITE_SAFETY_HOLD
    assert held["pre_hold_readiness_status"] == C.SITE_UNDER_CONSTRUCTION

    validate_error(
        api.close_application(
            application["id"], F.closing_payload("2026-08-05T00:00:00.000Z"), headers=APPROVER
        ),
        E.ERR_SITE_NOT_COMPLETED,
        409,
    )
    app_mid = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert app_mid["status"] == C.APP_CLEARED_TO_CLOSE

    released = validate_success(
        api.set_safety_posture(
            site["id"],
            F.safety_posture_payload(C.POSTURE_CLEAR, incident_note="Trench shored and re-inspected"),
            headers=CREW_LEAD,
        )
    )
    assert released["readiness_status"] == C.SITE_UNDER_CONSTRUCTION

    finished = validate_success(
        api.advance_readiness(site["id"], F.readiness_payload(C.STEP_FINAL_INSPECTION), headers=CREW_LEAD)
    )
    assert finished["readiness_status"] == C.SITE_COMPLETED

    closed = validate_success(
        api.close_application(
            application["id"], F.closing_payload("2026-08-05T00:00:00.000Z"), headers=APPROVER
        )
    )
    assert closed["status"] == C.APP_CLOSED


def test_settlement_records_the_lien_and_moves_the_capital_between_buckets(api):
    """Closing does four things at once, across four rows.

    "The lien dimension moves `NONE → ACTIVE` ... with `lien_recorded_on` stamped at
    the logical clock instant, `lien_outstanding_cents` set to the full silent
    second, and `forgiven_amount_cents` at 0. The program's
    `subsidy_committed_cents` falls by the silent second while
    `subsidy_disbursed_cents` rises by the same figure ... The household transitions
    `PARTNERSHIP_ACTIVE → CLOSED` ... and the program's `households_served_count`
    rises by 1."

    Design: Difficulty/cross_entity_state_dependency/mortgage_close_blocked_until_build_site_leaves_safety_hold_and_completes
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    X.approve_application(api, application["id"], program["id"])
    X.setup_completed_education(api, household["id"])
    X.advance_clock(api, "2026-08-05T00:00:00.000Z")
    X.setup_credited_entry(
        api, household["id"], member["id"], hours_claimed=12.0, work_date="2026-08-04T00:00:00.000Z"
    )
    construction = X.start_construction(
        api, program["id"], site["id"], start_at="2026-08-20T08:00:00.000Z", end_at="2026-08-20T16:00:00.000Z"
    )
    validate_success(
        api.cancel_shift(construction["shift"]["id"], F.cancellation_payload(), headers=CREW_LEAD)
    )
    validate_success(
        api.advance_readiness(site["id"], F.readiness_payload(C.STEP_FINAL_INSPECTION), headers=CREW_LEAD)
    )

    closed = validate_success(
        api.close_application(
            application["id"], F.closing_payload("2026-08-05T00:00:00.000Z"), headers=APPROVER
        )
    )
    assert closed["status"] == C.APP_CLOSED
    assert closed["lien_status"] == C.LIEN_ACTIVE
    assert closed["lien_outstanding_cents"] == 1_950_000
    assert closed["forgiven_amount_cents"] == 0

    reread_household = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert reread_household["selection_status"] == C.SELECTION_CLOSED
    assert reread_household["sweat_equity_required_hours"] == 12
    assert reread_household["sweat_equity_credited_hours"] == 12.0
    assert reread_household["sweat_equity_satisfied"] is True

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["subsidy_committed_cents"] == 0
    assert reread_program["subsidy_disbursed_cents"] == 1_950_000
    assert reread_program["subsidy_available_cents"] == 3_050_000
    assert reread_program["households_served_count"] == 1

    reread_volunteer = validate_success(api.get_volunteer(construction["volunteer"]["id"], headers=CREW_LEAD))
    assert reread_volunteer["assigned_hours_committed"] == 0.0


def test_an_approval_followed_by_a_denial_restores_the_pool_to_the_cent(api):
    """The forward action really moves the money and the compensating one gives it all back.

    "A denial from `APPROVED` additionally performs the compensating fiscal action:
    `subsidy_committed_cents` falls by the silent second, restoring
    `subsidy_available_cents` to precisely its pre-approval value, `program_posture`
    is re-derived, and the program's `version` increments."

    Design: Difficulty/compensating_invariant/invariant_subsidy_pool_approve_then_deny_restores_available_cents
    """
    program = X.setup_program(api, subsidy_pool_cents=20_000_000)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])

    before = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert before["subsidy_pool_cents"] == 20_000_000
    assert before["subsidy_available_cents"] == 20_000_000
    assert before["subsidy_committed_cents"] == 0
    assert before["subsidy_disbursed_cents"] == 0
    assert before["program_posture"] == C.POSTURE_OPEN

    X.approve_application(api, application["id"], program["id"])

    mid = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert mid["subsidy_committed_cents"] == 1_950_000
    assert mid["subsidy_available_cents"] == 18_050_000
    assert mid["subsidy_disbursed_cents"] == 0
    assert mid["subsidy_pool_cents"] == 20_000_000
    assert mid["program_posture"] == C.POSTURE_OPEN

    validate_success(api.deny_application(application["id"], F.denial_payload(), headers=APPROVER))

    after = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert after["subsidy_available_cents"] == 20_000_000
    assert after["subsidy_committed_cents"] == 0
    assert after["subsidy_disbursed_cents"] == 0
    assert after["subsidy_pool_cents"] == 20_000_000
    assert after["program_posture"] == C.POSTURE_OPEN
    assert (
        after["subsidy_pool_cents"]
        == after["subsidy_available_cents"] + after["subsidy_committed_cents"] + after["subsidy_disbursed_cents"]
    )


def test_the_denied_file_keeps_its_structure_and_hands_the_site_back(api):
    """Only the pool entry is compensated; the sizing and the spending stay.

    "Any denial clears the build site's `assigned_household_id` back to null when it
    named this household, bumping the site's `version`, and leaves the site's
    recorded cost lines exactly where they are — the cost ledger is append-only and
    a failed placement does not erase spending."

    Design: Difficulty/compensating_invariant/invariant_subsidy_pool_approve_then_deny_restores_available_cents
    """
    program = X.setup_program(api, subsidy_pool_cents=20_000_000)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    X.approve_application(api, application["id"], program["id"])

    denied = validate_success(
        api.deny_application(
            application["id"], F.denial_payload(denial_reason_code=C.APP_DENIAL_READINESS), headers=APPROVER
        )
    )
    assert denied["status"] == C.APP_DENIED
    assert denied["denial_reason_code"] == C.APP_DENIAL_READINESS
    # The sized structure survives the denial.
    assert denied["silent_second_amount_cents"] == 1_950_000
    assert denied["affordable_pi_payment_cents"] == 54_375
    assert denied["term_months"] == 240
    assert denied["first_mortgage_principal_cents"] == 13_050_000
    assert denied["lien_status"] == C.LIEN_NONE

    reread_site = validate_success(api.get_build_site(site["id"], headers=ADMIN))
    assert reread_site["assigned_household_id"] is None


def test_a_structured_but_unapproved_silent_second_is_outside_the_committed_bucket(api):
    """The same application is read at three statuses and only one of them books money.

    "`subsidy_committed_cents` is the sum of the silent-second amounts of that
    program's applications in `APPROVED` or `CLEARED_TO_CLOSE` status ... and
    `subsidy_available_cents` is `subsidy_pool_cents` less committed less
    disbursed. ... Applications in `DRAFT`, `UNDERWRITING`, `DENIED`, or
    `SUPERSEDED` contribute nothing to either bucket."

    Design: Corner/calculations/subsidy_committed_counts_only_approved_and_cleared_applications
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_draft_application(api, household["id"], site["id"])

    at_draft = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert at_draft["subsidy_committed_cents"] == 0
    assert at_draft["subsidy_disbursed_cents"] == 0
    assert at_draft["subsidy_available_cents"] == 5_000_000
    assert at_draft["program_posture"] == C.POSTURE_OPEN

    underwritten = validate_success(api.submit_underwriting(application["id"], headers=OFFICER))
    assert underwritten["status"] == C.APP_UNDERWRITING
    assert underwritten["silent_second_amount_cents"] == 1_950_000

    at_underwriting = validate_success(api.get_program(program["id"], headers=ADMIN))
    # The silent second is computed and stored, and still outside the input set.
    assert at_underwriting["subsidy_committed_cents"] == 0
    assert at_underwriting["subsidy_available_cents"] == 5_000_000

    approved = validate_success(
        api.approve_application(
            application["id"], F.approval_payload(at_underwriting["version"]), headers=APPROVER
        )
    )
    # Readiness is NOT_READY, so the file stops at APPROVED rather than clearing.
    assert approved["status"] == C.APP_APPROVED

    at_approved = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert at_approved["subsidy_committed_cents"] == 1_950_000
    assert at_approved["subsidy_disbursed_cents"] == 0
    assert at_approved["subsidy_available_cents"] == 3_050_000
    assert at_approved["program_posture"] == C.POSTURE_OPEN
    for snapshot in (at_draft, at_underwriting, at_approved):
        assert snapshot["subsidy_pool_cents"] == (
            snapshot["subsidy_available_cents"]
            + snapshot["subsidy_committed_cents"]
            + snapshot["subsidy_disbursed_cents"]
        )


def test_the_approve_response_and_the_program_ledger_never_disagree(api):
    """What the child write reports, the parent's next read already knows.

    "On success the program's `subsidy_committed_cents` rises by the silent second,
    `subsidy_available_cents` and `program_posture` are recomputed, and the
    program's `version` increments." There is no interval in which the approve
    response's 1,950,000 and the program's ledger tell different stories, and the
    release runs just as promptly.

    Design: Corner/consistency_model/an_approval_and_the_program_ledger_agree_in_the_same_breath
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])

    approved = validate_success(
        api.approve_application(
            application["id"], F.approval_payload(X.program_version(api, program["id"])), headers=APPROVER
        )
    )
    assert approved["status"] == C.APP_APPROVED
    assert approved["silent_second_amount_cents"] == 1_950_000

    right_after = validate_success(api.get_program(program["id"], headers=APPROVER))
    assert right_after["subsidy_committed_cents"] == approved["silent_second_amount_cents"]
    assert right_after["subsidy_disbursed_cents"] == 0
    assert right_after["subsidy_available_cents"] == 3_050_000
    assert right_after["program_posture"] == C.POSTURE_OPEN

    denied = validate_success(
        api.deny_application(
            application["id"], F.denial_payload(denial_reason_code=C.APP_DENIAL_READINESS), headers=APPROVER
        )
    )
    assert denied["status"] == C.APP_DENIED
    assert denied["denial_reason_code"] == C.APP_DENIAL_READINESS

    right_after_denial = validate_success(api.get_program(program["id"], headers=APPROVER))
    assert right_after_denial["subsidy_committed_cents"] == 0
    assert right_after_denial["subsidy_available_cents"] == 5_000_000
