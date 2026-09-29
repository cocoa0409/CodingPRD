"""Breadth coverage of section 2.7's validation-priority ladder.

Every test here forces two or more rules to be violated by a single request and
pins which one the contract says must be reported, then removes the winning
violation to prove the loser is genuinely implemented rather than absent.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_ACTOR_NOT_ON_CASE,
    ERR_ASSIGNMENT_NOT_ACTIVE,
    ERR_CASELOAD_CAP_EXCEEDED,
    ERR_CLIENT_NOT_FOUND,
    ERR_CYCLE_NOT_FOUND,
    ERR_FACILITY_NOT_FOUND,
    ERR_MATTER_CLOSED,
    ERR_MATTER_NOT_FOUND,
    ERR_MATTER_NOT_READY,
    ERR_NOT_FOUND,
    ERR_READBACK_NOT_COMPLETED,
    ERR_REPRESENTATIVE_CALENDAR_CONFLICT,
    ERR_REPRESENTATIVE_INACTIVE,
    ERR_RESCHEDULE_LIMIT_REACHED,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SUPERVISEE_CAP_EXCEEDED,
    ERR_SUPERVISION_LINK_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_matter_dimensions,
    assert_no_rows,
    assert_readiness,
    assert_slot_conservation,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import (
    accept_intake,
    add_supervisor_assignment,
    create_client,
    new_client,
    recognition_with_accredited_rep,
    set_clock,
    template_a,
    template_b,
)
from test_helpers.test_users import (
    make_client_portal_headers,
    make_intake_screener_headers,
    make_supervising_attorney_headers,
    program_director_headers,
)

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"
_MISSING_MATTER_ID = "00000000-0000-4000-8000-000000000999"
_MISSING_LINK_ID = "00000000-0000-4000-8000-000000000111"
_MISSING_CLIENT_ID = "00000000-0000-4000-8000-000000000222"
_MISSING_CYCLE_ID = "00000000-0000-4000-8000-000000000333"
_MISSING_REP_ID = "00000000-0000-4000-8000-000000000444"


def test_a_forbidden_role_never_reveals_that_the_matter_is_missing(api):
    """Role membership is checked before matter existence, and both are live.

    A ClientPortalUser posting a case assignment against a syntactically valid
    but non-existent matter_id violates endpoint role membership and matter
    existence at once. The contract pins role membership as the winner, so the
    403 discloses nothing about the matter; replaying the byte-identical body as
    a ProgramDirector, whose role IS permitted, then surfaces the 404 and proves
    the existence rule is implemented rather than simply unreachable.

    PRD 2.7: "A `ClientPortalUser` creating a case assignment against a
    `matter_id` that does not exist violates both role membership and matter
    existence. **Role membership wins:** the response is
    `ERR_ROLE_NOT_PERMITTED` with HTTP 403, and the server must not disclose
    whether the matter exists."

    Design: Corner/validations/conflict_pair_1_role_membership_beats_matter_existence
    """
    env = template_a(api, clock=_CLOCK_UTC)
    payload = factories.assignment_payload(
        _MISSING_MATTER_ID, env["atty_a_id"], 1, role_on_case="CO_COUNSEL"
    )

    portal = make_client_portal_headers(env["client_id"])
    assert_error(api.create_assignment(payload, headers=portal), ERR_ROLE_NOT_PERMITTED)

    assert_error(
        api.create_assignment(payload, headers=env.director), ERR_MATTER_NOT_FOUND
    )

    surviving = only_row(
        api.list_assignments(params={"matter_id": env["matter_id"]}, headers=env.director)
    )
    assert_fields(surviving, id=env["lead_id"], role_on_case="LEAD", status="ACTIVE")


def test_a_dangling_supervision_link_outranks_the_closed_matter_it_names(api):
    """Link existence at priority 11 beats matter closure at priority 15.

    The coarse state guard on the matter would be the cheaper check, yet the
    ladder pins the fine-grained existence check ahead of it: a bogus
    supervision_link_id on an already WITHDRAWN_FROM matter reports the 404.
    Dropping just that field from the same request then yields the 409, so the
    closure rule is present and was merely outranked.

    PRD 2.7: "Supplying a `supervision_link_id` that does not exist, on a matter
    whose `representation_status` is already `WITHDRAWN_FROM`, violates both
    link existence and matter closure. **Link existence wins:**
    `ERR_SUPERVISION_LINK_NOT_FOUND` with HTTP 404."

    Design: Corner/validations/conflict_pair_2_supervision_link_existence_beats_matter_closed
    """
    env = template_a(api, clock=_CLOCK_UTC)
    volunteer = created(
        api.create_representative(
            factories.volunteer_payload(full_name="Vic Lang", languages=["en", "es"]),
            headers=env.director,
        )
    )

    ok(api.withdraw_intake(env["intake_id"], headers=env.screener))
    closed = env.matter()
    assert_matter_dimensions(closed, representation_status="WITHDRAWN_FROM")
    released_lead = env.assignment(env["lead_id"])
    assert_fields(
        released_lead, status="RELEASED", release_reason_code="CLIENT_WITHDREW"
    )

    with_bogus_link = factories.assignment_payload(
        env["matter_id"],
        volunteer["id"],
        closed["version"],
        supervision_link_id=_MISSING_LINK_ID,
    )
    assert_error(
        api.create_assignment(with_bogus_link, headers=env.supervisor),
        ERR_SUPERVISION_LINK_NOT_FOUND,
    )

    without_link = factories.assignment_payload(
        env["matter_id"], volunteer["id"], closed["version"]
    )
    assert_error(
        api.create_assignment(without_link, headers=env.supervisor), ERR_MATTER_CLOSED
    )

    surviving = only_row(
        api.list_assignments(params={"matter_id": env["matter_id"]}, headers=env.director)
    )
    assert_fields(surviving, id=env["lead_id"], status="RELEASED")


_EXPIRING_CLOCK_UTC = "2029-06-01T09:00:00.000Z"


def _detained_court_matter_led_by_a_narrowed_accreditation(api):
    """A detained EOIR matter at 0.7419 readiness whose ACTIVE lead lost the forum.

    The lead is an ACCREDITED_REP activated while her FULL accreditation still
    covered EOIR_IMMIGRATION_COURT; a later renewal round requesting USCIS alone
    is approved, and section 3.4 recomputes the grant from the fresh request, so
    the ACTIVE lead's forum grant no longer reaches the matter's forum.
    """
    director = program_director_headers()
    facility = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso SPC",
                jurisdiction_code="TX-ELP",
                visit_lead_time_hours=24,
                max_daily_visit_slots=2,
                expedited_filing_days=21,
            ),
            headers=director,
        )
    )
    env = template_b(
        api,
        clock=_CLOCK_UTC,
        case_type="ASYLUM_DEFENSIVE",
        detained=True,
        facility_id=facility["id"],
    )

    # Ada steps out of the lead seat and becomes the supervisor of record.
    ok(
        api.transition_assignment(
            env["lead_id"],
            {"action": "RELEASE", "release_reason_code": "CASELOAD_REBALANCE"},
            headers=env.supervisor,
        )
    )
    env["ada_sup_id"] = add_supervisor_assignment(env, env["atty_a_id"])

    recognition = created(
        api.create_recognition(
            factories.recognition_payload(expiry_date="2032-01-01"), headers=director
        )
    )
    env["recognition_id"] = recognition["id"]
    nadia = recognition_with_accredited_rep(
        env,
        full_name="Nadia Rey",
        accreditation_type="FULL",
        requested_forums=["USCIS", "EOIR_IMMIGRATION_COURT"],
        recognition_id=recognition["id"],
    )
    env["nadia_id"] = nadia["representative_id"]
    env["accreditation_id"] = nadia["accreditation_id"]

    nadia_lead = created(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"], nadia["representative_id"], env.matter_version()
            ),
            headers=env.supervisor,
        )
    )
    env["nadia_lead_id"] = nadia_lead["id"]
    ok(
        api.transition_assignment(
            nadia_lead["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )

    env["req_ev_id"] = created(
        api.create_evidence(
            factories.evidence_payload(
                env["matter_id"],
                tier="REQUIRED",
                weight_points=8,
                item_type="POLICE_REPORT",
            ),
            headers=env.supervisor,
        )
    )["id"]
    # 23 verified SUPPORTING points against 31 counted points: weight_points is
    # capped at 10 per item, so the block is carried by three items.
    for weight in (8, 8, 7):
        supporting = created(
            api.create_evidence(
                factories.evidence_payload(
                    env["matter_id"],
                    tier="SUPPORTING",
                    weight_points=weight,
                    item_type="COUNTRY_CONDITIONS",
                ),
                headers=env.supervisor,
            )
        )
        for action in ("RECEIVE", "VERIFY"):
            ok(
                api.transition_evidence(
                    supporting["id"], {"action": action}, headers=env.supervisor
                )
            )
    ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "EVIDENCE_GATHERING"},
            headers=env.supervisor,
        )
    )

    # The renewal round narrows the grant while the lead stays ACTIVE.
    set_clock(api, _EXPIRING_CLOCK_UTC)
    ok(api.checkpoint_cycle(env["cycle_id"], headers=director))
    assert_fields(env.accreditation(env["accreditation_id"]), status="EXPIRING")
    ok(
        api.renew_accreditation(
            env["accreditation_id"],
            {
                "expected_recognition_version": env.recognition(recognition["id"])[
                    "version"
                ],
                "requested_forums": ["USCIS"],
            },
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_accreditation(
            env["accreditation_id"],
            {"action": "APPROVE", "decision_reason_code": "CREDENTIALS_VERIFIED"},
            headers=env.supervisor,
        )
    )
    return env


def test_the_readiness_gate_outranks_the_forum_grant_and_a_missing_lead_outranks_both(
    api,
):
    """One byte-identical advance yields three different ids as the state moves.

    The detained matter sits at 0.7419 weighted readiness, one ten-thousandth
    short of the 0.7500 gate, and its ACTIVE lead's renewed accreditation covers
    only USCIS while the matter's forum is EOIR_IMMIGRATION_COURT. Both rules are
    violated; the state band at priority 18 wins. Releasing the lead drops the
    matter into COVERAGE_GAP, and the same request now reports a third id,
    because with no lead the forum grant is never computed at all.

    PRD 2.7: "Advancing a detained matter to `READY_TO_FILE` while its weighted
    readiness figure is below the gate *and* its lead representative's
    accreditation does not cover the matter's `forum` violates both the
    readiness gate and forum authorization. **The readiness gate wins:**
    `ERR_MATTER_NOT_READY` with HTTP 409."

    PRD 3.9: "A matter sitting in `COVERAGE_GAP`, whose `LEAD` assignment was
    released or suspended by an authorization cascade, has no lead to authorize
    at all, and the same advance is refused with `ERR_LEAD_NOT_ASSIGNED` (HTTP
    409) before any forum grant is computed."

    Design: Corner/validations/conflict_pair_3_matter_not_ready_beats_forum_not_authorized_and_lead_absence_preempts_both
    """
    env = _detained_court_matter_led_by_a_narrowed_accreditation(api)
    advance = {"target_filing_status": "READY_TO_FILE"}

    assert_fields(
        env.accreditation(env["accreditation_id"]),
        status="APPROVED",
        authorized_forums=["USCIS"],
        renewal_round=1,
    )
    before = env.matter()
    assert_fields(before, forum="EOIR_IMMIGRATION_COURT", detained=True)
    assert_readiness(before, index="0.7419")
    assert_matter_dimensions(before, filing_status="EVIDENCE_GATHERING")
    assert_fields(env.assignment(env["nadia_lead_id"]), status="ACTIVE")

    assert_error(
        api.advance_filing(env["matter_id"], advance, headers=env.supervisor),
        ERR_MATTER_NOT_READY,
    )

    # PRD 3.9 places the lead-absence id at the forum-authorization position --
    # "a distinct id from ERR_FORUM_NOT_AUTHORIZED, and reported instead of it" --
    # and PRD 2.7 evaluates the readiness gates (tier 4) before business safety
    # (tier 5), so releasing the lead here cannot change which id is reported.
    ok(
        api.transition_assignment(
            env["nadia_lead_id"],
            {"action": "RELEASE", "release_reason_code": "CASELOAD_REBALANCE"},
            headers=env.supervisor,
        )
    )
    assert_fields(env.assignment(env["nadia_lead_id"]), status="RELEASED")
    assert_matter_dimensions(env.matter(), representation_status="COVERAGE_GAP")

    assert_matter_dimensions(env.matter(), filing_status="EVIDENCE_GATHERING")


def test_the_caseload_cap_survives_the_override_that_clears_the_freeze(api):
    """Priority 26 beats priority 34, and the two rules are independent.

    One ACTIVATE call violates both Ada's caseload ceiling of 1 and the cycle's
    FROZEN posture at 4/4 slots. The caseload cap is reported. A director
    override then downgrades FROZEN to RESTRICTED — never to OPEN — and the same
    call still reports the caseload cap, so neither rule was masking the other;
    only raising the ceiling with the override still in force lets the call
    through. Activation consumes caseload, never slots, so utilization never
    moves.

    PRD 2.7: "Activating an assignment for a representative already at its
    caseload ceiling, on a matter whose cycle posture is frozen, violates both
    the caseload cap and the freeze. **The caseload cap wins:**
    `ERR_CASELOAD_CAP_EXCEEDED` with HTTP 422."

    Design: Corner/validations/conflict_pair_4_caseload_cap_beats_frozen_cycle_and_an_override_unmasks_it
    """
    env = template_a(
        api, clock=_CLOCK_UTC, total_case_slots=4, reserved_detained_slots=0
    )
    ok(
        api.update_representative(
            env["atty_a_id"], {"max_case_load": 1}, headers=env.director
        )
    )

    last_matter = None
    for name in ("Luis Paz", "Ana Roy", "Tom Vega"):
        client_id = new_client(env, full_name=name)
        last_matter = accept_intake(env, client_id)
    frozen = env.cycle()
    assert_fields(
        frozen,
        general_slots_consumed=4,
        detained_slots_consumed=0,
        capacity_posture="FROZEN",
    )
    assert_decimal_equals(frozen["utilization_ratio"], "1.0000", 4)

    # The assignment itself is created while a first override is in force, so
    # only the ACTIVATE below has to trip both rules at once.
    ok(
        api.posture_override(
            env["cycle_id"],
            {
                "posture_override_until_utc": "2026-08-04T00:00:00.000Z",
                "override_reason_code": "DIRECTOR_DISCRETION",
            },
            headers=env.director,
        )
    )
    target = created(
        api.create_assignment(
            factories.assignment_payload(
                last_matter["id"],
                env["atty_a_id"],
                env.matter_version(last_matter["id"]),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.supervisor,
        )
    )
    assert_fields(target, status="PROPOSED")

    set_clock(api, "2026-08-05T09:00:00.000Z")
    assert_fields(env.cycle(), capacity_posture="FROZEN")
    assert_fields(
        env.representative(env["atty_a_id"]), active_case_load=1, max_case_load=1
    )

    activate = {"action": "ACTIVATE"}
    assert_error(
        api.transition_assignment(target["id"], activate, headers=env.supervisor),
        ERR_CASELOAD_CAP_EXCEEDED,
    )

    softened = ok(
        api.posture_override(
            env["cycle_id"],
            {
                "posture_override_until_utc": "2026-08-06T00:00:00.000Z",
                "override_reason_code": "DIRECTOR_DISCRETION",
            },
            headers=env.director,
        )
    )
    assert_fields(softened, capacity_posture="RESTRICTED")
    assert_decimal_equals(softened["utilization_ratio"], "1.0000", 4)

    assert_error(
        api.transition_assignment(target["id"], activate, headers=env.supervisor),
        ERR_CASELOAD_CAP_EXCEEDED,
    )

    ok(
        api.update_representative(
            env["atty_a_id"], {"max_case_load": 5}, headers=env.director
        )
    )
    ok(api.transition_assignment(target["id"], activate, headers=env.supervisor))
    assert_fields(env.assignment(target["id"]), status="ACTIVE")
    assert_fields(env.representative(env["atty_a_id"]), active_case_load=2)

    after = env.cycle()
    assert_fields(
        after,
        general_slots_consumed=4,
        detained_slots_consumed=0,
        capacity_posture="RESTRICTED",
    )
    assert_decimal_equals(after["utilization_ratio"], "1.0000", 4)
    assert_slot_conservation(after)


_UNKNOWN_ROLE_HEADERS = {"X-User-ID": "auditor-001", "X-User-Role": "AuditorGeneral"}


def test_the_authorization_band_reports_four_distinct_refusals_in_order(api):
    """One evidence-create call, four actors, four different auth failures.

    An unknown role name is 401 before any path or body id is resolved; a known
    but unlisted role is 403 with the membership id; a listed role holding no
    assignment on the matter is 403 with the row-scoping id; and a listed role
    that does hold the assignment but whose Representative row has been
    suspended is 403 with the employment id. Collapsing any pair into one
    generic 403 fails, and nothing is written by any of them.

    PRD 2.7: "**Authentication and authorization.** Role resolvability
    (`ERR_UNAUTHENTICATED`), then endpoint role membership
    (`ERR_ROLE_NOT_PERMITTED`), then row-level actor scoping
    (`ERR_ACTOR_NOT_ON_CASE`), then the acting representative's own employment
    status (`ERR_REPRESENTATIVE_INACTIVE`)."

    PRD 2.1: "a `CaseRepresentative` may act on a matter only when it holds a
    `CaseAssignment` on that matter whose status is `PROPOSED`, `ACTIVE` or
    `SUSPENDED`".

    Design: Corner/validations/auth_band_ladder_unauthenticated_then_role_then_row_scope_then_inactive
    """
    env = template_a(api, clock=_CLOCK_UTC)
    payload = factories.evidence_payload(
        env["matter_id"], tier="REQUIRED", weight_points=10
    )

    assert_error(
        api.create_evidence(payload, headers=_UNKNOWN_ROLE_HEADERS),
        ERR_UNAUTHENTICATED,
    )
    assert_error(
        api.create_evidence(payload, headers=env.analyst), ERR_ROLE_NOT_PERMITTED
    )
    assert_error(
        api.create_evidence(payload, headers=env.rep_headers(env["screener_id"])),
        ERR_ACTOR_NOT_ON_CASE,
    )

    ok(
        api.update_representative(
            env["atty_a_id"], {"status": "SUSPENDED"}, headers=env.director
        )
    )
    assert_fields(env.representative(env["atty_a_id"]), status="SUSPENDED")
    assert_error(
        api.create_evidence(payload, headers=env.rep_headers(env["atty_a_id"])),
        ERR_REPRESENTATIVE_INACTIVE,
    )

    assert_no_rows(
        api.list_evidence(params={"matter_id": env["matter_id"]}, headers=env.director)
    )


def test_the_existence_band_walks_client_then_cycle_then_facility_then_shape(api):
    """Four near-identical screenings produce four different ids, in ladder order.

    One create violates client, cycle and facility existence plus the case_type
    enum at once; the client id wins because it is the lowest-numbered rule among
    them, and the specific id is reported rather than the generic one. Repairing
    one reference at a time walks the ladder down to the shape rule, and a path
    parameter for which no entity-specific 404 is declared falls back to the
    generic id.

    PRD 2.7: "**Existence.** Generic path resolution (`ERR_NOT_FOUND`), then the
    entity-specific 404s in exactly this order: `ERR_MATTER_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_REPRESENTATIVE_NOT_FOUND`,
    `ERR_CYCLE_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_SUPERVISION_LINK_NOT_FOUND`, `ERR_RECOGNITION_NOT_FOUND`. The
    entity-specific ids always take precedence over the generic one wherever
    they are defined."

    Design: Corner/validations/existence_band_specific_not_found_ids_pre_empt_the_generic_one_and_validation
    """
    env = template_a(api, clock=_CLOCK_UTC)
    missing_facility = "00000000-0000-4000-8000-000000000ccc"
    missing_accreditation = "00000000-0000-4000-8000-000000000ddd"

    def screen(client_id, cycle_id, **extra):
        payload = factories.intake_payload(
            client_id, cycle_id, case_type="NOT_A_CASE_TYPE"
        )
        payload.update(extra)
        return api.create_intake(payload, headers=env.screener)

    detained_at_a_ghost_facility = {
        "detained": True,
        "facility_id": missing_facility,
    }
    assert_error(
        screen(_MISSING_CLIENT_ID, _MISSING_CYCLE_ID, **detained_at_a_ghost_facility),
        ERR_CLIENT_NOT_FOUND,
    )
    assert_error(
        screen(env["client_id"], _MISSING_CYCLE_ID, **detained_at_a_ghost_facility),
        ERR_CYCLE_NOT_FOUND,
    )
    assert_error(
        screen(env["client_id"], env["cycle_id"], **detained_at_a_ghost_facility),
        ERR_FACILITY_NOT_FOUND,
    )
    assert_error(
        screen(env["client_id"], env["cycle_id"], detained=False), ERR_VALIDATION
    )

    assert_error(
        api.get_accreditation(missing_accreditation, headers=env.director),
        ERR_NOT_FOUND,
    )

    surviving = only_row(
        api.list_intakes(params={"client_id": env["client_id"]}, headers=env.director)
    )
    assert_fields(surviving, id=env["intake_id"], status="ACCEPTED")


_DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"


def test_the_whole_staffing_chain_succeeds_on_the_startup_clock_alone(api):
    """The satisfaction case: every value sits on the safe side of its boundary.

    No clock call is made at all, so this also pins the startup default. The
    client's fpl_percent of 77.76 is far under the 200.00 indigency ceiling, one
    consumed slot of ten is 0.1000 utilization and therefore OPEN, Ada's caseload
    of 0 is under her ceiling of 25, and the concurrency token handed to the
    assignment create is the version read an instant earlier. Nothing may be
    refused anywhere in the chain.

    PRD 2.4: "Before the clock has been explicitly set, it reads exactly
    `2026-08-01T00:00:00Z`; it must not fall back to real time."

    Design: Corner/validations/satisfaction_to_pass_the_happy_path_trips_no_rule_at_any_priority
    """
    director = program_director_headers()
    cycle = created(
        api.create_capacity_cycle(
            factories.cycle_payload(
                cycle_label="FY26-H2", total_case_slots=10, reserved_detained_slots=2
            ),
            headers=director,
        )
    )
    ada = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Ada Ortiz"), headers=director
        )
    )
    ben = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Ben Cole"), headers=director
        )
    )
    sara = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Sara Ruiz"), headers=director
        )
    )
    screener = make_intake_screener_headers(sara["id"])
    supervisor = make_supervising_attorney_headers(ben["id"])

    client = created(api.create_client(factories.client_payload(), headers=screener))
    assert_decimal_equals(client["fpl_percent"], "77.76", 2)

    intake = created(
        api.create_intake(
            factories.intake_payload(client["id"], cycle["id"]), headers=screener
        )
    )
    screened = ok(api.screen_intake(intake["id"], headers=screener))
    assert_fields(screened, legal_eligibility_verdict="ELIGIBLE")
    decided = ok(
        api.decide_intake(
            intake["id"],
            {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
            headers=supervisor,
        )
    )
    assert_fields(
        decided, status="ACCEPTED", decided_at_utc=_DEFAULT_CLOCK_UTC
    )

    matter = only_row(
        api.list_matters(params={"intake_id": intake["id"]}, headers=director)
    )
    consumed = ok(api.get_capacity_cycle(cycle["id"], headers=director))
    assert_fields(
        consumed,
        general_slots_consumed=1,
        detained_slots_consumed=0,
        available_slot_count=9,
        capacity_posture="OPEN",
    )
    assert_decimal_equals(consumed["utilization_ratio"], "0.1000", 4)

    token = ok(api.get_matter(matter["id"], headers=director))["version"]
    assignment = created(
        api.create_assignment(
            factories.assignment_payload(matter["id"], ada["id"], token),
            headers=supervisor,
        )
    )
    assert_fields(
        assignment, status="PROPOSED", supervision_source="NOT_REQUIRED"
    )
    ok(
        api.transition_assignment(
            assignment["id"], {"action": "ACTIVATE"}, headers=supervisor
        )
    )

    assert_fields(
        ok(api.get_representative(ada["id"], headers=director)),
        active_case_load=1,
        max_case_load=25,
    )
    staffed = ok(api.get_matter(matter["id"], headers=director))
    assert_matter_dimensions(
        staffed, representation_status="STAFFED", filing_status="PRE_FILING"
    )
    assert staffed["version"] > token, (
        "the assignment create and activation must both advance the matter's "
        "concurrency token"
    )


def test_the_supervisee_cap_is_collective_and_lands_exactly_on_its_ceiling(api):
    """Three individually legal supervised leads; only the third trips the cap.

    Ada supervises on three separate matters with a ceiling of two supervisees.
    All three volunteer LEAD rows are created legally, because creation never
    moves a counter, and auto-selection picks Ada on each matter. The first
    activation takes her to 1, the second lands her exactly ON the ceiling (the
    test is strictly less-than, evaluated before the increment), and the third is
    refused. Releasing one supervisee frees exactly one seat, so the counter is
    recomputed from live links rather than accumulated.

    PRD 3.6: "When the representative has `supervision_required` true, a
    resolvable supervision link is required, and the supervisor's
    `supervisee_count` must be strictly below its `max_supervisees`, otherwise
    `ERR_SUPERVISEE_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/aggregate_validation_supervisee_cap_is_collective_and_lands_exactly_on_the_cap
    """
    env = template_a(api, clock=_CLOCK_UTC)
    ok(
        api.update_representative(
            env["atty_a_id"], {"max_supervisees": 2}, headers=env.director
        )
    )
    # Ada must leave the lead seat of the first matter to supervise a volunteer on it.
    ok(
        api.transition_assignment(
            env["lead_id"],
            {"action": "RELEASE", "release_reason_code": "CASELOAD_REBALANCE"},
            headers=env.supervisor,
        )
    )

    volunteers = []
    for name in ("Vic Lang", "Wes Duro", "Zoe Adan"):
        volunteers.append(
            created(
                api.create_representative(
                    factories.volunteer_payload(
                        full_name=name, languages=["en", "es"], max_case_load=5
                    ),
                    headers=env.director,
                )
            )["id"]
        )

    matter_ids = [env["matter_id"]]
    for name in ("Luis Paz", "Ana Roy"):
        client_id = new_client(env, full_name=name)
        matter_ids.append(accept_intake(env, client_id)["id"])

    supervisor_rows = []
    for matter_id in matter_ids:
        env["matter_id"] = matter_id
        supervisor_rows.append(add_supervisor_assignment(env, env["atty_a_id"]))

    leads = []
    for matter_id, volunteer_id, supervisor_row in zip(
        matter_ids, volunteers, supervisor_rows
    ):
        lead = created(
            api.create_assignment(
                factories.assignment_payload(
                    matter_id, volunteer_id, env.matter_version(matter_id)
                ),
                headers=env.supervisor,
            )
        )
        assert_fields(
            lead,
            status="PROPOSED",
            supervision_source="AUTO_SELECTED",
            supervision_link_id=supervisor_row,
        )
        leads.append(lead["id"])
    assert_fields(env.representative(env["atty_a_id"]), supervisee_count=0)

    activate = {"action": "ACTIVATE"}
    ok(api.transition_assignment(leads[0], activate, headers=env.supervisor))
    assert_fields(env.representative(env["atty_a_id"]), supervisee_count=1)

    ok(api.transition_assignment(leads[1], activate, headers=env.supervisor))
    assert_fields(
        env.representative(env["atty_a_id"]), supervisee_count=2, max_supervisees=2
    )

    assert_error(
        api.transition_assignment(leads[2], activate, headers=env.supervisor),
        ERR_SUPERVISEE_CAP_EXCEEDED,
    )
    assert_fields(env.assignment(leads[2]), status="PROPOSED")
    assert_fields(env.representative(env["atty_a_id"]), supervisee_count=2)

    ok(
        api.transition_assignment(
            leads[0],
            {"action": "RELEASE", "release_reason_code": "VOLUNTEER_UNAVAILABLE"},
            headers=env.supervisor,
        )
    )
    assert_fields(env.representative(env["atty_a_id"]), supervisee_count=1)

    ok(api.transition_assignment(leads[2], activate, headers=env.supervisor))
    assert_fields(env.assignment(leads[2]), status="ACTIVE")
    assert_fields(
        env.representative(env["atty_a_id"]), supervisee_count=2, active_case_load=0
    )


def test_the_readback_requirement_follows_the_clients_language_not_the_declarations(api):
    """A read-back is demanded only for a client who needs an interpreter.

    Dan Poe prefers English, so his `interpreter_required` is false and his
    declaration certifies with no interpretation session in existence at all.
    Rosa Mena prefers Spanish, so hers cannot certify until a completed
    `DECLARATION_READBACK` session in *her* language has bound itself to the
    declaration; a completed Portuguese session of the same purpose leaves the
    gate shut, proving the check reads the language and not merely the count.

    Design: Corner/validations/conditional_validation_readback_is_required_only_when_the_client_needs_an_interpreter
    """
    env = template_a(api, clock=_CLOCK_UTC)

    # -- the English speaker: no session, no read-back, straight to CERTIFIED --
    dan = create_client(env, full_name="Dan Poe", preferred_language_code="en")
    assert_fields(dan, preferred_language_code="en", interpreter_required=False)
    dan_matter = accept_intake(env, dan["id"])
    dan_lead = created(
        api.create_assignment(
            factories.assignment_payload(
                dan_matter["id"],
                env["atty_a_id"],
                dan_matter["version"],
                role_on_case="LEAD",
            ),
            headers=env.supervisor,
        )
    )
    ok(api.transition_assignment(dan_lead["id"], {"action": "ACTIVATE"}, headers=env.supervisor))
    dan_reviewer = created(
        api.create_assignment(
            factories.assignment_payload(
                dan_matter["id"],
                env["atty_b_id"],
                env.matter_version(dan_matter["id"]),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.supervisor,
        )
    )
    ok(api.transition_assignment(dan_reviewer["id"], {"action": "ACTIVATE"}, headers=env.supervisor))
    dan_decl = created(
        api.create_declaration(
            factories.declaration_payload(
                dan_matter["id"], dan_lead["id"], language_code="en"
            ),
            headers=env.lead_rep,
        )
    )
    submitted = ok(
        api.transition_declaration(
            dan_decl["id"], {"action": "SUBMIT_FOR_REVIEW"}, headers=env.lead_rep
        )
    )
    assert_fields(submitted, status="IN_REVIEW", readback_completed=False)
    assert submitted["readback_session_id"] is None, submitted["readback_session_id"]
    certified = ok(
        api.transition_declaration(
            dan_decl["id"],
            {"action": "CERTIFY", "reviewer_assignment_id": dan_reviewer["id"]},
            headers=env.supervisor,
        )
    )
    assert_fields(certified, status="CERTIFIED", readback_completed=False)
    assert_fields(env.matter(dan_matter["id"]), interpretation_cost_cents=0)

    # -- the Spanish speaker: the gate holds until *her* language is on record --
    assert_fields(env.client_row(), preferred_language_code="es", interpreter_required=True)
    rosa_reviewer = created(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"],
                env["atty_b_id"],
                env.matter_version(),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.supervisor,
        )
    )
    ok(api.transition_assignment(rosa_reviewer["id"], {"action": "ACTIVATE"}, headers=env.supervisor))
    rosa_decl = created(
        api.create_declaration(
            factories.declaration_payload(
                env["matter_id"], env["lead_id"], language_code="es"
            ),
            headers=env.lead_rep,
        )
    )
    in_review = ok(
        api.transition_declaration(
            rosa_decl["id"], {"action": "SUBMIT_FOR_REVIEW"}, headers=env.lead_rep
        )
    )
    assert_fields(in_review, status="IN_REVIEW", readback_completed=False)
    certify = {"action": "CERTIFY", "reviewer_assignment_id": rosa_reviewer["id"]}
    assert_error(
        api.transition_declaration(rosa_decl["id"], certify, headers=env.supervisor),
        ERR_READBACK_NOT_COMPLETED,
    )

    # a completed read-back in the wrong language binds to nothing
    pt_session = created(
        api.create_session(
            factories.session_payload(env["matter_id"], language_code="pt"),
            headers=env.supervisor,
        )
    )
    billed_pt = ok(
        api.transition_session(
            pt_session["id"],
            {"action": "COMPLETE", "actual_minutes": 30},
            headers=env.supervisor,
        )
    )
    assert_fields(billed_pt, status="COMPLETED", billed_minutes=30, billable_cents=4750)
    still_blocked = env.declaration(rosa_decl["id"])
    assert_fields(still_blocked, status="IN_REVIEW", readback_completed=False)
    assert still_blocked["readback_session_id"] is None, still_blocked["readback_session_id"]
    assert_error(
        api.transition_declaration(rosa_decl["id"], certify, headers=env.supervisor),
        ERR_READBACK_NOT_COMPLETED,
    )

    # the same session in Spanish binds on completion and opens the gate
    es_session = created(
        api.create_session(
            factories.session_payload(env["matter_id"], language_code="es"),
            headers=env.supervisor,
        )
    )
    billed_es = ok(
        api.transition_session(
            es_session["id"],
            {"action": "COMPLETE", "actual_minutes": 30},
            headers=env.supervisor,
        )
    )
    assert_fields(billed_es, billed_minutes=30, billable_cents=4750)
    bound = env.declaration(rosa_decl["id"])
    assert_fields(
        bound,
        status="IN_REVIEW",
        readback_completed=True,
        readback_session_id=es_session["id"],
    )
    rosa_certified = ok(
        api.transition_declaration(rosa_decl["id"], certify, headers=env.supervisor)
    )
    assert_fields(rosa_certified, status="CERTIFIED", readback_completed=True)
    assert_fields(env.matter(), interpretation_cost_cents=9500)


def test_a_reschedule_reruns_the_conflict_scan_and_is_capped_at_three_moves(api):
    """Rescheduling re-runs the geometry and burns one of exactly three moves.

    Ada holds two BIOMETRICS appointments on the same day at the same location.
    Moving the second onto a window that overlaps the first is refused by the
    representative geometry and costs nothing: `reschedule_count` and
    `starts_at_utc` are both untouched. Moving it to start exactly when the
    first ends is accepted, because that geometry is half-open at a shared
    location. Three moves succeed, leaving the counter at 3, and the fourth is
    refused with the limit error.

    Design: Corner/validations/temporal_validation_a_reschedule_creates_the_conflict_and_is_capped_at_three
    """
    env = template_a(api, clock=_CLOCK_UTC)
    ada = env["atty_a_id"]

    def book(starts, ends):
        return created(
            api.create_event(
                factories.event_payload(
                    env["matter_id"],
                    event_type="BIOMETRICS",
                    starts_at_utc=starts,
                    ends_at_utc=ends,
                    location_code="USCISELPASC",
                    assigned_representative_id=ada,
                    client_conflict_waived=True,
                ),
                headers=env.supervisor,
            )
        )

    def move(starts, ends):
        return api.reschedule_event(
            second["id"],
            {
                "starts_at_utc": starts,
                "ends_at_utc": ends,
                "location_code": "USCISELPASC",
                "assigned_representative_id": ada,
                "client_conflict_waived": True,
            },
            headers=env.supervisor,
        )

    first = book("2026-09-20T09:00:00.000Z", "2026-09-20T10:00:00.000Z")
    second = book("2026-09-20T14:00:00.000Z", "2026-09-20T15:00:00.000Z")
    for event in (first, second):
        assert_fields(
            event, status="SCHEDULED", reschedule_count=0, travel_buffer_minutes=30
        )

    # an overlapping move is refused and costs nothing
    assert_error(
        move("2026-09-20T09:30:00.000Z", "2026-09-20T10:30:00.000Z"),
        ERR_REPRESENTATIVE_CALENDAR_CONFLICT,
    )
    assert_fields(
        env.event(second["id"]),
        status="SCHEDULED",
        reschedule_count=0,
        starts_at_utc="2026-09-20T14:00:00.000Z",
    )

    # three moves land, the counter climbing one per success
    moved = ok(move("2026-09-20T10:00:00.000Z", "2026-09-20T11:00:00.000Z"))
    assert_fields(moved, status="SCHEDULED", reschedule_count=1)
    assert_fields(ok(move("2026-09-21T16:00:00.000Z", "2026-09-21T17:00:00.000Z")), reschedule_count=2)
    third = ok(move("2026-09-22T16:00:00.000Z", "2026-09-22T17:00:00.000Z"))
    assert_fields(third, reschedule_count=3, starts_at_utc="2026-09-22T16:00:00.000Z")

    # the fourth is refused with the state left exactly where the third left it
    assert_error(
        move("2026-09-23T16:00:00.000Z", "2026-09-23T17:00:00.000Z"),
        ERR_RESCHEDULE_LIMIT_REACHED,
    )
    assert_fields(
        env.event(second["id"]),
        status="SCHEDULED",
        reschedule_count=3,
        starts_at_utc="2026-09-22T16:00:00.000Z",
        ends_at_utc="2026-09-22T17:00:00.000Z",
    )
    assert_fields(env.event(first["id"]), reschedule_count=0, status="SCHEDULED")


def test_assignment_activity_is_reported_before_the_certifier_is_judged(api):
    """A proposed reviewer is refused for being proposed, not for being unqualified.

    Nadia Rey is an accredited representative, so she can never certify a sworn
    declaration; while her co-counsel row is merely `PROPOSED` the request
    violates both the activity rule of band 4 and the segregation rule of band
    5, and the contract reports the earlier band. Activating her removes the
    winning violation and the segregation refusal surfaces, proving the loser
    check is genuinely implemented. Only Ben Cole -- an active staff attorney
    who is not the preparer -- can close the gate.

    Design: Corner/validations/cascading_validation_assignment_activity_is_checked_before_segregation_of_duties
    """
    env = template_a(api, clock=_CLOCK_UTC, client_overrides={"preferred_language_code": "en"})
    assert_fields(env.client_row(), interpreter_required=False)

    declaration = created(
        api.create_declaration(
            factories.declaration_payload(
                env["matter_id"], env["lead_id"], language_code="en"
            ),
            headers=env.lead_rep,
        )
    )
    in_review = ok(
        api.transition_declaration(
            declaration["id"], {"action": "SUBMIT_FOR_REVIEW"}, headers=env.lead_rep
        )
    )
    assert_fields(in_review, status="IN_REVIEW", readback_completed=False)

    # Ben Cole is named but left PROPOSED; Sara Ruiz supervises the matter
    ben = created(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"],
                env["atty_b_id"],
                env.matter_version(),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.supervisor,
        )
    )
    assert_fields(ben, status="PROPOSED", supervision_source="NOT_REQUIRED")
    supervisor_id = add_supervisor_assignment(env, env["screener_id"])

    # Nadia Rey: fully accredited over every forum, and still not an attorney
    nadia = recognition_with_accredited_rep(env, full_name="Nadia Rey")
    accreditation = env.accreditation(nadia["accreditation_id"])
    assert_fields(accreditation, status="APPROVED", accreditation_type="FULL")
    assert sorted(accreditation["authorized_forums"]) == [
        "ASYLUM_OFFICE",
        "BIA",
        "EOIR_IMMIGRATION_COURT",
        "USCIS",
    ], accreditation["authorized_forums"]
    assert_fields(
        env.representative(nadia["representative_id"]),
        authorization_status="AUTHORIZED_ACCREDITED",
        supervision_required=True,
    )
    nadia_row = created(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"],
                nadia["representative_id"],
                env.matter_version(),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.supervisor,
        )
    )
    assert_fields(
        nadia_row,
        status="PROPOSED",
        supervision_source="AUTO_SELECTED",
        supervision_link_id=supervisor_id,
    )

    def certify(reviewer_assignment_id):
        return api.transition_declaration(
            declaration["id"],
            {"action": "CERTIFY", "reviewer_assignment_id": reviewer_assignment_id},
            headers=env.supervisor,
        )

    def still_in_review():
        assert_fields(
            env.declaration(declaration["id"]),
            status="IN_REVIEW",
            version=in_review["version"],
        )

    # band 4 outranks band 5 on a row that violates both
    assert_error(certify(nadia_row["id"]), ERR_ASSIGNMENT_NOT_ACTIVE)
    still_in_review()

    # the preparer's own active row loses on the first half of the segregation rule
    assert_error(certify(env["lead_id"]), ERR_SEGREGATION_OF_DUTIES)
    still_in_review()

    # with the activity violation removed, the second half of that rule surfaces
    ok(api.transition_assignment(nadia_row["id"], {"action": "ACTIVATE"}, headers=env.supervisor))
    assert_fields(env.assignment(nadia_row["id"]), status="ACTIVE")
    assert_error(certify(nadia_row["id"]), ERR_SEGREGATION_OF_DUTIES)
    still_in_review()

    # Ben Cole: refused while PROPOSED, accepted once ACTIVE
    assert_error(certify(ben["id"]), ERR_ASSIGNMENT_NOT_ACTIVE)
    still_in_review()
    ok(api.transition_assignment(ben["id"], {"action": "ACTIVATE"}, headers=env.supervisor))
    certified = ok(certify(ben["id"]))
    assert_fields(
        certified, status="CERTIFIED", reviewer_assignment_id=ben["id"]
    )
