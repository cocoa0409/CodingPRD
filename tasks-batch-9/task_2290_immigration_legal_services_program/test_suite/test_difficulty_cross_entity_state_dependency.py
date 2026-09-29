"""Depth tests for a gate that lives on a different entity than the transition.

Certifying a declaration is blocked by the state of an InterpretationSession that
the declaration does not even reference yet. Nothing about the declaration
changes between the refused CERTIFY and the accepted one -- what changes is a
session's status, and the flag it writes back onto the declaration.
"""

from test_helpers import factories
from test_helpers.api_errors import ERR_READBACK_NOT_COMPLETED
from test_helpers.assertions import assert_error, assert_fields, created, ok
from test_helpers.fixtures import accept_intake, minimal_world, new_client, set_clock

# ---------------------------------------------------------------------------
# declaration_certification_blocked_until_readback_session_completes
# ---------------------------------------------------------------------------

_READBACK_CLOCK_UTC = "2026-09-04T11:05:00.000Z"


def _setup_declaration_awaiting_readback(api):
    """An IN_REVIEW Armenian declaration with two readback sessions still SCHEDULED.

    The declaration's language_code equals the client's preferred_language_code,
    so SUBMIT_FOR_REVIEW passes on the language branch of the language-access
    rule: there is no qualifying completed session for the server to bind, and
    readback_completed therefore stays false. Because 'hy' is not 'en' the client
    carries interpreter_required true, which is exactly the condition that arms
    the certification-time readback requirement.

    Two representatives are needed: the preparer drafts and the reviewer
    certifies, and they must be different STAFF_ATTORNEY people. No evidence item
    is ever created, so the INCONSISTENT_WITH_DECLARATION precondition holds
    vacuously.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=20,
        reserved_detained_slots=4,
    )
    preparer = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Petros Sarkissian",
                languages=["en", "hy"],
                max_case_load=10,
                max_supervisees=4,
            ),
            headers=env.director,
        )
    )
    client_id = new_client(
        env,
        full_name="Anahit Grigoryan",
        preferred_language_code="hy",
        country_of_birth_code="AM",
        date_of_birth="1988-08-08",
        household_size=2,
        annual_household_income_cents=2400000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    matter = accept_intake(
        env, client_id, case_type="ASYLUM_AFFIRMATIVE", detained=False
    )

    lead = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                preparer["id"],
                matter["version"],
                role_on_case="LEAD",
            ),
            headers=env.director,
        )
    )
    ok(api.transition_assignment(lead["id"], {"action": "ACTIVATE"}, headers=env.director))
    reviewer = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                env["atty_a_id"],
                env.matter_version(matter["id"]),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.director,
        )
    )
    ok(
        api.transition_assignment(
            reviewer["id"], {"action": "ACTIVATE"}, headers=env.director
        )
    )

    declaration = created(
        api.create_declaration(
            factories.declaration_payload(
                matter["id"], lead["id"], language_code="hy", word_count=1800
            ),
            headers=env.rep_headers(preparer["id"]),
        )
    )
    ok(
        api.transition_declaration(
            declaration["id"],
            {"action": "SUBMIT_FOR_REVIEW"},
            headers=env.rep_headers(preparer["id"]),
        )
    )

    sessions = {}
    for key, day in (("s1_id", "2026-09-04"), ("s2_id", "2026-09-08")):
        row = created(
            api.create_session(
                factories.session_payload(
                    matter["id"],
                    language_code="hy",
                    interpreter_source="CONTRACT",
                    purpose="DECLARATION_READBACK",
                    scheduled_start_utc="{0}T10:00:00.000Z".format(day),
                    scheduled_end_utc="{0}T11:00:00.000Z".format(day),
                ),
                headers=env.director,
            )
        )
        sessions[key] = row["id"]

    env.set(
        client_id=client_id,
        matter_id=matter["id"],
        prep_id=preparer["id"],
        asg_p_id=lead["id"],
        asg_r_id=reviewer["id"],
        dec_id=declaration["id"],
        **sessions
    )
    return env


def test_certify_is_refused_while_the_readback_session_is_only_scheduled(api):
    """The declaration is flawless; the session it needs is merely SCHEDULED.

    The refusal must be ERR_READBACK_NOT_COMPLETED and not
    ERR_SEGREGATION_OF_DUTIES: the reviewer is a different person from the
    preparer, is a STAFF_ATTORNEY with AUTHORIZED_ATTORNEY status, and holds an
    ACTIVE assignment on the same matter. Completing the session then flips the
    flag from the other side of the join and the billing lands on the matter.

    Design: Difficulty/cross_entity_state_dependency/declaration_certification_blocked_until_readback_session_completes
    """
    env = _setup_declaration_awaiting_readback(api)

    assert_fields(
        env.declaration(env["dec_id"]),
        status="IN_REVIEW",
        readback_completed=False,
        readback_session_id=None,
    )

    refused = api.transition_declaration(
        env["dec_id"],
        {"action": "CERTIFY", "reviewer_assignment_id": env["asg_r_id"]},
        headers=env.attorney_headers(env["atty_a_id"]),
    )
    assert_error(refused, ERR_READBACK_NOT_COMPLETED)
    assert_fields(
        env.declaration(env["dec_id"]), status="IN_REVIEW", certified_at_utc=None
    )

    set_clock(api, _READBACK_CLOCK_UTC)
    completed = ok(
        api.transition_session(
            env["s1_id"],
            {"action": "COMPLETE", "actual_minutes": 45},
            headers=env.rep_headers(env["prep_id"]),
        )
    )
    # max(30, ceil(45/15)*15) == 45, and 9500 * 45/60 * 1.15 == 8193.75 -> 8194.
    assert_fields(
        completed, status="COMPLETED", actual_minutes=45, billed_minutes=45,
        billable_cents=8194,
    )
    assert_fields(
        env.declaration(env["dec_id"]),
        readback_completed=True,
        readback_session_id=env["s1_id"],
    )
    assert env.matter()["interpretation_cost_cents"] == 8194


def test_cancelling_an_unbound_second_session_does_not_revoke_the_readback(api):
    """The clearing rule is keyed on readback_session_id identity, not on purpose.

    S2 is another completed-language readback session for the same matter, but no
    declaration ever bound it, so its cancellation must leave readback_completed
    true and the binding pointed at S1 -- and must add nothing to the matter's
    interpretation cost. The certification that was refused a moment ago now
    passes on exactly the same payload.

    Design: Difficulty/cross_entity_state_dependency/declaration_certification_blocked_until_readback_session_completes
    """
    env = _setup_declaration_awaiting_readback(api)
    set_clock(api, _READBACK_CLOCK_UTC)
    ok(
        api.transition_session(
            env["s1_id"],
            {"action": "COMPLETE", "actual_minutes": 45},
            headers=env.rep_headers(env["prep_id"]),
        )
    )

    cancelled = ok(
        api.transition_session(
            env["s2_id"],
            {"action": "CANCEL", "closure_reason_code": "INTERPRETER_UNAVAILABLE"},
            headers=env.rep_headers(env["prep_id"]),
        )
    )
    assert_fields(cancelled, status="CANCELLED", billed_minutes=0, billable_cents=0)
    assert_fields(
        env.declaration(env["dec_id"]),
        readback_completed=True,
        readback_session_id=env["s1_id"],
    )
    assert env.matter()["interpretation_cost_cents"] == 8194

    certified = ok(
        api.transition_declaration(
            env["dec_id"],
            {"action": "CERTIFY", "reviewer_assignment_id": env["asg_r_id"]},
            headers=env.attorney_headers(env["atty_a_id"]),
        )
    )
    assert_fields(
        certified,
        status="CERTIFIED",
        reviewer_assignment_id=env["asg_r_id"],
        certified_at_utc=_READBACK_CLOCK_UTC,
    )
