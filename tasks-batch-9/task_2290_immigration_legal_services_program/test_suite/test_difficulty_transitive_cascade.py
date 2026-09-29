"""Depth tests for the two four-hop cascades.

Each cascade is fired by exactly ONE request. What makes them hard is not the
depth but the reach: the recognition lapse must key on the re-derived
authorization status rather than on the matter, and the screening withdrawal must
let hop 4 re-consume the very slot hop 3 released.
"""

from test_helpers import factories
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields,
    assert_slot_conservation,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import accept_intake, minimal_world, new_client
from test_helpers.test_users import program_director_headers

# ---------------------------------------------------------------------------
# recognition_lapse_depth4_suspends_accreditation_assignment_matter_declaration
# ---------------------------------------------------------------------------


def _setup_lapse_cascade(api):
    """A USCIS matter led by an accredited rep under a staff-attorney supervisor.

    The LEAD's supervision is AUTO_SELECTED, so the supervisor assignment must be
    created and activated first. The declaration sits IN_REVIEW and two events
    straddle the 14-day coverage-gap lookahead.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=20,
        reserved_detained_slots=4,
    )
    director = program_director_headers()

    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                recognition_number="R-2290-002",
                effective_date="2026-01-01",
                expiry_date="2033-12-31",
                authorized_forums=["USCIS", "ASYLUM_OFFICE"],
            ),
            headers=director,
        )
    )
    accredited_rep = created(
        api.create_representative(
            factories.accredited_rep_payload(
                full_name="Yusra Bekele",
                languages=["en", "am"],
                max_case_load=15,
                max_supervisees=0,
                weekly_capacity_hours=35,
            ),
            headers=director,
        )
    )
    accreditation = created(
        api.create_accreditation(
            factories.accreditation_payload(
                accredited_rep["id"],
                recognition["id"],
                accreditation_type="PARTIAL",
                requested_forums=["USCIS"],
            ),
            headers=director,
        )
    )
    ok(
        api.transition_accreditation(
            accreditation["id"],
            {"action": "APPROVE", "decision_reason_code": "CREDENTIALS_VERIFIED"},
            headers=env.attorney_headers(env["atty_a_id"]),
        )
    )

    client_id = new_client(
        env,
        full_name="Ivo Petrov",
        preferred_language_code="en",
        country_of_birth_code="BG",
        date_of_birth="1991-06-14",
        household_size=1,
        annual_household_income_cents=2000000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    matter = accept_intake(
        env, client_id, case_type="ADJUSTMENT_OF_STATUS", detained=False
    )

    supervisor = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                env["atty_a_id"],
                matter["version"],
                role_on_case="SUPERVISOR",
            ),
            headers=director,
        )
    )
    ok(
        api.transition_assignment(
            supervisor["id"], {"action": "ACTIVATE"}, headers=director
        )
    )
    lead = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                accredited_rep["id"],
                env.matter_version(matter["id"]),
                role_on_case="LEAD",
            ),
            headers=director,
        )
    )
    ok(api.transition_assignment(lead["id"], {"action": "ACTIVATE"}, headers=director))

    declaration = created(
        api.create_declaration(
            factories.declaration_payload(
                matter["id"], lead["id"], language_code="en", word_count=800
            ),
            headers=director,
        )
    )
    ok(
        api.transition_declaration(
            declaration["id"],
            {"action": "SUBMIT_FOR_REVIEW"},
            headers=env.rep_headers(accredited_rep["id"]),
        )
    )

    events = {}
    for key, day in (("ce_near_id", "2026-09-08"), ("ce_far_id", "2026-11-20")):
        row = created(
            api.create_event(
                factories.event_payload(
                    matter["id"],
                    event_type="BIOMETRICS",
                    starts_at_utc="{0}T14:00:00.000Z".format(day),
                    ends_at_utc="{0}T15:00:00.000Z".format(day),
                    location_code="USCISPHX",
                    assigned_representative_id=env["atty_a_id"],
                ),
                headers=director,
            )
        )
        events[key] = row["id"]

    env.set(
        client_id=client_id,
        matter_id=matter["id"],
        rec_id=recognition["id"],
        acc_id=accreditation["id"],
        arep_id=accredited_rep["id"],
        asg_sup_id=supervisor["id"],
        asg_lead_id=lead["id"],
        dec_id=declaration["id"],
        **events
    )
    return env


def test_one_lapse_request_walks_all_four_hops_to_the_declaration(api):
    """Recognition -> accreditation -> assignment -> matter -> declaration and events.

    Hop 4 is the tell: the IN_REVIEW declaration is pushed to REVISION_REQUESTED
    with SUPERVISION_REQUIRED and only the event inside the 14-day lookahead is
    flagged. An implementation that stops at hop 2 leaves the matter staffed.

    Design: Difficulty/transitive_cascade/recognition_lapse_depth4_suspends_accreditation_assignment_matter_declaration
    """
    env = _setup_lapse_cascade(api)

    before = env.matter()
    assert before["representation_status"] == "SUPERVISED_STAFFED"
    assert_fields(
        env.assignment(env["asg_lead_id"]),
        supervision_source="AUTO_SELECTED",
        supervision_link_id=env["asg_sup_id"],
    )
    assert env.representative(env["arep_id"])["active_case_load"] == 1
    assert env.representative(env["atty_a_id"])["supervisee_count"] == 1

    lapsed = ok(
        api.transition_recognition(
            env["rec_id"], {"action": "LAPSE"}, headers=env.director
        )
    )

    # hop 0
    assert_fields(
        lapsed,
        status="LAPSED",
        lapsed_at_utc="2026-09-01T00:00:00.000Z",
        conditional_reason_code=None,
        suspended_accreditation_count=1,
    )
    # hop 1
    assert_fields(
        env.accreditation(env["acc_id"]),
        status="SUSPENDED_BY_RECOGNITION",
        decision_reason_code="RECOGNITION_LAPSE",
    )
    # hop 2
    assert (
        env.representative(env["arep_id"])["authorization_status"]
        == "AUTHORIZATION_SUSPENDED"
    )
    assert_fields(
        env.assignment(env["asg_lead_id"]),
        status="SUSPENDED",
        release_reason_code="RECOGNITION_LAPSE",
    )
    assert env.representative(env["arep_id"])["active_case_load"] == 0
    assert env.representative(env["atty_a_id"])["supervisee_count"] == 0
    # hop 3
    assert_fields(
        env.matter(),
        representation_status="COVERAGE_GAP",
        coverage_gap_flag=True,
        filing_status="PRE_FILING",
    )
    # hop 4
    assert_fields(
        env.declaration(env["dec_id"]),
        status="REVISION_REQUESTED",
        revision_round=1,
        revision_reason_code="SUPERVISION_REQUIRED",
    )
    assert env.event(env["ce_near_id"])["coverage_gap_flag"] is True
    assert env.event(env["ce_far_id"])["coverage_gap_flag"] is False


def test_the_lapse_leaves_the_staff_attorney_supervisor_on_the_matter_untouched(api):
    """Reach is keyed on authorization status, not on the matter.

    The supervisor's authority comes from the bar, so the same request that
    suspends the accredited lead must leave the SUPERVISOR assignment ACTIVE.

    Design: Difficulty/transitive_cascade/recognition_lapse_depth4_suspends_accreditation_assignment_matter_declaration
    """
    env = _setup_lapse_cascade(api)

    ok(api.transition_recognition(env["rec_id"], {"action": "LAPSE"}, headers=env.director))

    assert_fields(
        env.assignment(env["asg_sup_id"]),
        status="ACTIVE",
        release_reason_code=None,
    )
    assert (
        env.representative(env["atty_a_id"])["authorization_status"]
        == "AUTHORIZED_ATTORNEY"
    )
    # And the far event was never in range, so its version-bearing flag is clean.
    assert env.event(env["ce_far_id"])["coverage_gap_flag"] is False


# ---------------------------------------------------------------------------
# accepted_intake_withdrawal_depth4_releases_slot_and_promotes_waitlist_head
# ---------------------------------------------------------------------------

_WITHDRAWAL_CLIENTS = (
    ("c1_id", "Client One", "MX", "1985-01-05"),
    ("c2_id", "Client Two", "HN", "1986-02-06"),
    ("c3_id", "Client Three", "SV", "1987-03-07"),
    ("c4_id", "Client Four", "GT", "1988-04-08"),
    ("c5_id", "Client Five", "NI", "1989-05-09"),
    ("c6_id", "Client Six", "EC", "1990-06-10"),
)


def _screen_one(env, client_id):
    """Open and screen one non-detained ADJUSTMENT_OF_STATUS intake."""
    intake = created(
        env.api.create_intake(
            factories.intake_payload(
                client_id,
                env["cycle_id"],
                case_type="ADJUSTMENT_OF_STATUS",
                detained=False,
            ),
            headers=env.director,
        )
    )
    ok(env.api.screen_intake(intake["id"], headers=env.screener))
    return intake["id"]


def _setup_withdrawal_cascade(api):
    """A four-slot cycle driven to 4/4 FROZEN with two waitlisted rows behind it.

    The LEAD on the first matter is activated while the cycle is still OPEN,
    because a frozen cycle refuses new assignment work. The two waitlisted rows
    take ranks 1 and 2 in creation order.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        cycle_label="TIGHT4",
        total_case_slots=4,
        reserved_detained_slots=0,
    )
    director = program_director_headers()

    for key, name, country, dob in _WITHDRAWAL_CLIENTS:
        env[key] = new_client(
            env,
            full_name=name,
            preferred_language_code="en",
            country_of_birth_code=country,
            date_of_birth=dob,
            household_size=1,
            annual_household_income_cents=2000000,
            confidentiality_consent_scope="PROGRAM_ONLY",
        )

    # i1..i4 fill the cycle. i1's matter also takes an ACTIVE LEAD.
    for index, key in enumerate(("c1_id", "c2_id", "c3_id", "c4_id"), start=1):
        intake_id = _screen_one(env, env[key])
        ok(
            api.decide_intake(
                intake_id,
                {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
                headers=env.supervisor,
            )
        )
        env["i{0}_id".format(index)] = intake_id
        if index == 1:
            matter = only_row(
                api.list_matters(params={"intake_id": intake_id}, headers=director)
            )
            assignment = created(
                api.create_assignment(
                    factories.assignment_payload(
                        matter["id"],
                        env["atty_a_id"],
                        matter["version"],
                        role_on_case="LEAD",
                    ),
                    headers=director,
                )
            )
            ok(
                api.transition_assignment(
                    assignment["id"], {"action": "ACTIVATE"}, headers=director
                )
            )
            env.set(m1_id=matter["id"], asg1_id=assignment["id"])

    # i5 and i6 arrive after the freeze and are waitlisted.
    for index, key in ((5, "c5_id"), (6, "c6_id")):
        intake_id = _screen_one(env, env[key])
        ok(
            api.decide_intake(
                intake_id,
                {"decision": "WAITLIST", "decision_reason_code": "CAPACITY_FULL"},
                headers=env.supervisor,
            )
        )
        env["i{0}_id".format(index)] = intake_id
    return env


def test_withdrawing_one_accepted_screening_closes_its_matter_and_frees_its_lead(api):
    """Hops 1 and 2: the matter closes on both dimensions and the lead is released.

    The withdrawal is a screening act, so the matter's outcome is recorded as
    WITHDRAWN and the assignment's release reason is CLIENT_WITHDREW rather than
    MATTER_CLOSED.

    Design: Difficulty/transitive_cascade/accepted_intake_withdrawal_depth4_releases_slot_and_promotes_waitlist_head
    """
    env = _setup_withdrawal_cascade(api)

    before = env.cycle()
    assert_fields(
        before,
        general_slots_consumed=4,
        detained_slots_consumed=0,
        available_slot_count=0,
        capacity_posture="FROZEN",
        waitlisted_count=2,
    )
    assert_decimal_equals(before["utilization_ratio"], "1.0000", 4)
    assert env.intake(env["i5_id"])["waitlist_rank"] == 1
    assert env.intake(env["i6_id"])["waitlist_rank"] == 2

    withdrawn = ok(api.withdraw_intake(env["i1_id"], headers=env.screener))
    assert_fields(withdrawn, status="WITHDRAWN", decision_reason_code="CLIENT_WITHDREW")

    assert_fields(
        env.matter(env["m1_id"]),
        representation_status="WITHDRAWN_FROM",
        filing_status="CLOSED_NO_FILING",
        outcome="WITHDRAWN",
        closed_at_utc="2026-09-01T00:00:00.000Z",
    )
    assert_fields(
        env.assignment(env["asg1_id"]),
        status="RELEASED",
        release_reason_code="CLIENT_WITHDREW",
        released_at_utc="2026-09-01T00:00:00.000Z",
    )
    assert env.representative(env["atty_a_id"])["active_case_load"] == 0
    assert_fields(env.client_row(env["c1_id"]), open_matter_count=0, status="CLOSED")


def test_the_freed_slot_is_immediately_re_consumed_by_the_promoted_waitlist_head(api):
    """Hop 4 is caused by hop 3, so the cycle lands back on 4/4 FROZEN.

    Observing available_slot_count 1 with waitlisted_count 2 would prove the
    promotion never ran; promoting both rows would overflow the four-seat pool.
    The runner-up is re-ranked from 2 down to 1 so ranks stay dense from 1.

    Design: Difficulty/transitive_cascade/accepted_intake_withdrawal_depth4_releases_slot_and_promotes_waitlist_head
    """
    env = _setup_withdrawal_cascade(api)

    ok(api.withdraw_intake(env["i1_id"], headers=env.screener))

    promoted = env.intake(env["i5_id"])
    assert_fields(
        promoted,
        status="ACCEPTED",
        decision_reason_code="ACCEPTED_ON_MERIT",
        waitlist_rank=None,
        waitlist_expires_at_utc=None,
    )
    promoted_matter = only_row(
        api.list_matters(params={"intake_id": env["i5_id"]}, headers=env.director)
    )
    assert_fields(
        promoted_matter,
        representation_status="UNSTAFFED",
        filing_status="PRE_FILING",
        slot_pool_consumed="GENERAL",
    )
    assert_fields(env.intake(env["i6_id"]), status="WAITLISTED", waitlist_rank=1)

    after = env.cycle()
    assert_fields(
        after,
        general_slots_consumed=4,
        detained_slots_consumed=0,
        available_slot_count=0,
        capacity_posture="FROZEN",
        waitlisted_count=1,
    )
    assert_decimal_equals(after["utilization_ratio"], "1.0000", 4)
    assert_slot_conservation(after)
    assert_fields(env.client_row(env["c5_id"]), open_matter_count=1, status="ACTIVE")
