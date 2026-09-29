"""Depth tests for the three called-out validation-priority conflicts.

Each test drives a request that violates two rules at once and reads which
complaint the server reports. A control call in the same recipe breaks only the
losing rule, which proves the losing condition was genuinely live.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_CASELOAD_CAP_EXCEEDED,
    ERR_CYCLE_CAPACITY_FROZEN,
    ERR_MATTER_CLOSED,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SUPERVISION_LINK_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_row_count,
    created,
    ok,
)
from test_helpers.fixtures import accept_intake, minimal_world, new_client, set_clock
from test_helpers.test_users import (
    make_client_portal_headers,
    program_director_headers,
)

# ---------------------------------------------------------------------------
# caseload_cap_beats_cycle_frozen_after_posture_override_expires
# ---------------------------------------------------------------------------


def _setup_cap_versus_freeze(api):
    """A two-slot cycle at 2/2 whose softening override has just expired.

    The capped representative is put at exactly its ceiling of 1 by activating a
    LEAD on the first matter, and both CO_COUNSEL rows on the second matter are
    created while the override still holds. Moving the clock past the override
    instant restores the computed FROZEN posture with no further call.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        cycle_label="TIGHT2",
        total_case_slots=2,
        reserved_detained_slots=0,
        decider_max_case_load=5,
    )
    director = program_director_headers()

    # atty_c: ceiling of exactly 1. The control rep is minimal_world's decider,
    # which carries a ceiling of 5 and an active_case_load of 0.
    capped = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Ciara Nwosu",
                languages=["en"],
                max_case_load=1,
                max_supervisees=5,
            ),
            headers=director,
        )
    )

    matters = []
    for name, country, dob in (
        ("Client One", "MX", "1985-01-05"),
        ("Client Two", "HN", "1986-02-06"),
    ):
        client_id = new_client(
            env,
            full_name=name,
            preferred_language_code="en",
            country_of_birth_code=country,
            date_of_birth=dob,
            household_size=1,
            annual_household_income_cents=2000000,
            confidentiality_consent_scope="PROGRAM_ONLY",
        )
        matters.append(
            accept_intake(env, client_id, case_type="ADJUSTMENT_OF_STATUS", detained=False)
        )

    ok(
        api.posture_override(
            env["cycle_id"],
            {
                "posture_override_until_utc": "2026-09-05T00:00:00.000Z",
                "override_reason_code": "DIRECTOR_SURGE_AUTHORIZATION",
            },
            headers=director,
        )
    )

    m1, m2 = matters[0], matters[1]
    capped_cocounsel = created(
        api.create_assignment(
            factories.assignment_payload(
                m2["id"],
                capped["id"],
                env.matter_version(m2["id"]),
                role_on_case="CO_COUNSEL",
            ),
            headers=director,
        )
    )
    control_cocounsel = created(
        api.create_assignment(
            factories.assignment_payload(
                m2["id"],
                env["atty_a_id"],
                env.matter_version(m2["id"]),
                role_on_case="CO_COUNSEL",
            ),
            headers=director,
        )
    )
    capped_lead = created(
        api.create_assignment(
            factories.assignment_payload(
                m1["id"],
                capped["id"],
                env.matter_version(m1["id"]),
                role_on_case="LEAD",
            ),
            headers=director,
        )
    )
    ok(
        api.transition_assignment(
            capped_lead["id"], {"action": "ACTIVATE"}, headers=director
        )
    )

    set_clock(api, "2026-09-06T00:00:00.000Z")
    env.set(
        capped_id=capped["id"],
        m1_id=m1["id"],
        m2_id=m2["id"],
        asg_cc_id=capped_cocounsel["id"],
        asg_control_id=control_cocounsel["id"],
        asg_lead_id=capped_lead["id"],
    )
    return env


def test_caseload_cap_wins_over_the_restored_capacity_freeze(api):
    """Both rules are broken by one ACTIVATE; the 422 must be reported, not the 409.

    The representative sits at exactly its ceiling and the cycle is frozen again
    now that the override instant has passed, and the refusal mutates nothing.

    Design: Difficulty/priority_pair_validation_conflict/caseload_cap_beats_cycle_frozen_after_posture_override_expires
    """
    env = _setup_cap_versus_freeze(api)

    cycle = env.cycle()
    assert_decimal_equals(cycle["utilization_ratio"], "1.0000", 4)
    assert cycle["capacity_posture"] == "FROZEN", (
        "the override instant 2026-09-05T00:00:00.000Z is no longer strictly "
        "after the clock, so the computed posture is reported again"
    )
    capped = env.representative(env["capped_id"])
    assert capped["active_case_load"] == capped["max_case_load"] == 1

    refused = api.transition_assignment(
        env["asg_cc_id"], {"action": "ACTIVATE"}, headers=env.director
    )
    assert_error(refused, ERR_CASELOAD_CAP_EXCEEDED)

    assert env.assignment(env["asg_cc_id"])["status"] == "PROPOSED"
    assert env.representative(env["capped_id"])["active_case_load"] == 1


def test_the_control_activation_proves_the_freeze_was_live(api):
    """A representative with headroom hits the freeze alone and gets the 409.

    Without this control the winning 422 above could be produced by an
    implementation that never evaluates the capacity freeze at all.

    Design: Difficulty/priority_pair_validation_conflict/caseload_cap_beats_cycle_frozen_after_posture_override_expires
    """
    env = _setup_cap_versus_freeze(api)

    control = env.representative(env["atty_a_id"])
    assert control["active_case_load"] == 0
    assert control["active_case_load"] < control["max_case_load"]

    refused = api.transition_assignment(
        env["asg_control_id"], {"action": "ACTIVATE"}, headers=env.director
    )
    assert_error(refused, ERR_CYCLE_CAPACITY_FROZEN)

    assert env.assignment(env["asg_control_id"])["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# dangling_supervision_link_beats_withdrawn_matter_state
# ---------------------------------------------------------------------------

_MISSING_LINK_ID = "00000000-0000-4000-8000-000000000000"


def _setup_closed_matter(api):
    """One accepted matter whose screening is then withdrawn, with no waitlist.

    The cascade closes the matter on both dimensions and advances its version, so
    the concurrency token is re-read afterwards: the point of the test is the
    ordering of the existence and state checks, not a stale token.
    """
    env = minimal_world(api, clock="2026-09-01T00:00:00.000Z", total_case_slots=10,
                        reserved_detained_slots=2)
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
    ok(api.withdraw_intake(matter["intake_id_used"], headers=env.screener))
    env.set(client_id=client_id, matter_id=matter["id"])
    return env


def test_missing_supervision_link_wins_over_the_closed_matter(api):
    """Link existence is checked before matter closure, so the answer is 404.

    Both complaints are live: the named link resolves to no row at all and the
    matter is already WITHDRAWN_FROM.

    Design: Difficulty/priority_pair_validation_conflict/dangling_supervision_link_beats_withdrawn_matter_state
    """
    env = _setup_closed_matter(api)

    assert_fields(
        env.matter(),
        representation_status="WITHDRAWN_FROM",
        filing_status="CLOSED_NO_FILING",
    )

    refused = api.create_assignment(
        factories.assignment_payload(
            env["matter_id"],
            env["atty_a_id"],
            env.matter_version(),
            role_on_case="CO_COUNSEL",
            supervision_link_id=_MISSING_LINK_ID,
        ),
        headers=env.director,
    )
    assert_error(refused, ERR_SUPERVISION_LINK_NOT_FOUND)

    assert_row_count(
        api.list_assignments(params={"matter_id": env["matter_id"]}, headers=env.director),
        0,
    )


def test_the_control_create_without_a_link_reports_the_closed_matter(api):
    """Omitting the link leaves matter closure as the only violation, so 409.

    This is what proves the 404 above was a genuine ordering decision rather
    than an implementation that never notices closed matters.

    Design: Difficulty/priority_pair_validation_conflict/dangling_supervision_link_beats_withdrawn_matter_state
    """
    env = _setup_closed_matter(api)

    refused = api.create_assignment(
        factories.assignment_payload(
            env["matter_id"],
            env["atty_a_id"],
            env.matter_version(),
            role_on_case="CO_COUNSEL",
        ),
        headers=env.director,
    )
    assert_error(refused, ERR_MATTER_CLOSED)

    assert_row_count(
        api.list_assignments(params={"matter_id": env["matter_id"]}, headers=env.director),
        0,
    )


# ---------------------------------------------------------------------------
# role_not_permitted_beats_missing_matter_for_client_portal_user
# ---------------------------------------------------------------------------

_ABSENT_MATTER_ID = "11111111-1111-4111-8111-111111111111"


def test_role_membership_is_answered_before_the_matter_is_looked_up(api):
    """A ClientPortalUser posting an assignment must learn nothing about the matter.

    The role is absent from the endpoint's role list, so the refusal is 403 and
    must not disclose that the referenced matter does not exist -- nor may the
    concurrency token be evaluated first and reported as a 412.

    Design: Difficulty/priority_pair_validation_conflict/role_not_permitted_beats_missing_matter_for_client_portal_user
    """
    director = program_director_headers()
    set_clock(api, "2026-09-01T00:00:00.000Z")
    representative = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Dov Halberstam",
                languages=["en"],
                max_case_load=10,
                max_supervisees=5,
            ),
            headers=director,
        )
    )
    client = created(
        api.create_client(
            factories.client_payload(
                full_name="Ivo Petrov",
                preferred_language_code="en",
                country_of_birth_code="BG",
                date_of_birth="1991-06-14",
                household_size=1,
                annual_household_income_cents=2000000,
                confidentiality_consent_scope="PROGRAM_ONLY",
            ),
            headers=director,
        )
    )

    refused = api.create_assignment(
        factories.assignment_payload(
            _ABSENT_MATTER_ID, representative["id"], 1, role_on_case="LEAD"
        ),
        headers=make_client_portal_headers(client["id"]),
    )
    assert_error(refused, ERR_ROLE_NOT_PERMITTED)

    assert _ABSENT_MATTER_ID not in refused.text, (
        "the refusal must not echo the unresolvable matter id back to a caller "
        "that was never permitted on the endpoint"
    )
    assert_row_count(api.list_assignments(headers=director), 0)
