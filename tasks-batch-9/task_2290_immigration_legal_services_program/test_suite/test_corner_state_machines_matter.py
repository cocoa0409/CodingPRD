"""State-machine coverage of the matter's two dimensions and its evidence rows.

A matter carries a representation dimension and a filing dimension on the same
row, driven by two different endpoints, and only one precondition crosses between
them. Evidence rows have their own machine underneath, whose translation gate and
unbounded rejection loop are what the readiness figures are computed over.

Each test translates exactly one instance of section 1.9 `state_machines`.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_LEAD_NOT_ASSIGNED,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_error,
    assert_fields,
    assert_matter_dimensions,
    assert_null_fields,
    assert_readiness,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import (
    accept_intake,
    create_client,
    minimal_world,
    template_a,
    template_b,
)

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"


def _required_item(env, **overrides):
    """One REQUIRED evidence item, created by the supervising attorney."""
    payload = factories.evidence_payload(
        env["matter_id"], tier="REQUIRED", weight_points=8, due_date="2026-09-01"
    )
    payload.update(overrides)
    return created(env.api.create_evidence(payload, headers=env.supervisor))


def test_the_filing_and_representation_dimensions_move_independently(api):
    """Two endpoints, two dimensions, and neither drags the other along.

    Advancing the filing dimension leaves the matter staffed, and suspending the
    only active lead drops the matter into a coverage gap while the filing
    dimension stays exactly where the advance left it.

    Design: Corner/state_machines/matter_filing_and_representation_dimensions_advance_independently
    """
    env = template_a(api, clock=_CLOCK_UTC)
    _required_item(env)

    advanced = ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "EVIDENCE_GATHERING"},
            headers=env.supervisor,
        )
    )
    assert_matter_dimensions(
        advanced, representation_status="STAFFED", filing_status="EVIDENCE_GATHERING"
    )

    suspended = ok(
        api.transition_assignment(
            env["lead_id"],
            # PRD 3.6: "Both require a release_reason_code when the actor is a
            # SupervisingAttorney", and the suspension here is a rebalance.
            {"action": "SUSPEND", "release_reason_code": "CASELOAD_REBALANCE"},
            headers=env.supervisor,
        )
    )
    assert_fields(suspended, status="SUSPENDED")
    after = env.matter()
    assert_matter_dimensions(
        after,
        representation_status="COVERAGE_GAP",
        # the filing dimension is untouched by the staffing cascade
        filing_status="EVIDENCE_GATHERING",
    )
    assert_fields(after, coverage_gap_flag=True)
    assert_fields(env.representative(env["atty_a_id"]), active_case_load=0)


def test_the_filing_dimension_will_not_move_on_an_unstaffed_matter(api):
    """The one genuine cross-dimension precondition, reported by its own id.

    The evidence precondition is already satisfied, so the refusal can only come
    from the missing lead.

    Design: Corner/state_machines/advance_filing_on_unstaffed_matter_returns_lead_not_assigned
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        cycle_label="FY26-H2",
        period_start_date="2026-07-01",
        period_end_date="2026-12-31",
        total_case_slots=10,
        reserved_detained_slots=2,
        languages=["en", "es"],
    )
    client = create_client(env)
    env["client_id"] = client["id"]
    matter = accept_intake(env, client["id"])
    env["matter_id"] = matter["id"]
    assert_matter_dimensions(
        matter, representation_status="UNSTAFFED", filing_status="PRE_FILING"
    )
    _required_item(env)

    assert_error(
        api.advance_filing(
            matter["id"],
            {"target_filing_status": "EVIDENCE_GATHERING"},
            headers=env.supervisor,
        ),
        ERR_LEAD_NOT_ASSIGNED,
    )
    assert_matter_dimensions(
        env.matter(matter["id"]),
        representation_status="UNSTAFFED",
        filing_status="PRE_FILING",
    )


def test_a_document_needing_translation_cannot_be_verified_straight_from_receipt(api):
    """Translation is a mandatory station, not an optional one.

    Design: Corner/state_machines/evidence_verify_before_translation_returns_invalid_state_transition
    """
    env = template_a(api, clock=_CLOCK_UTC)
    item = _required_item(
        env,
        item_type="COUNTRY_CONDITIONS",
        source_language_code="es",
        requires_translation=True,
    )
    ok(api.transition_evidence(item["id"], {"action": "RECEIVE"}, headers=env.lead_rep))

    assert_error(
        api.transition_evidence(item["id"], {"action": "VERIFY"}, headers=env.lead_rep),
        ERR_INVALID_STATE_TRANSITION,
    )
    stalled = only_row(
        api.list_evidence(params={"matter_id": env["matter_id"]}, headers=env.lead_rep)
    )
    assert_fields(stalled, status="RECEIVED", requires_translation=True)
    assert_null_fields(stalled, "verified_at_utc")
    assert_readiness(env.matter(), index="0.0000")

    # the same call succeeds once the document has passed through TRANSLATED
    ok(api.transition_evidence(item["id"], {"action": "TRANSLATE"}, headers=env.lead_rep))
    verified = ok(
        api.transition_evidence(item["id"], {"action": "VERIFY"}, headers=env.lead_rep)
    )
    assert_fields(verified, status="VERIFIED")
    assert_readiness(env.matter(), index="1.0000", ready_strict=True, blocking_count=0)


def test_rejecting_then_re_requesting_keeps_the_round_count_and_clears_the_receipt(api):
    """The rejection loop is unbounded and the round counter is its only trace.

    A rejected required item blocks twice over -- once as an open required row and
    once as a rejected one -- and re-requesting returns it to the queue with its
    receipt and disposition wiped but the round count intact.

    Design: Corner/state_machines/evidence_reject_then_rerequest_increments_rejection_round_and_clears_receipt
    """
    env = template_a(api, clock=_CLOCK_UTC)
    item = _required_item(env)
    ok(api.transition_evidence(item["id"], {"action": "RECEIVE"}, headers=env.lead_rep))

    rejected = ok(
        api.transition_evidence(
            item["id"],
            {"action": "REJECT", "disposition_reason_code": "ILLEGIBLE"},
            headers=env.lead_rep,
        )
    )
    assert_fields(
        rejected, status="REJECTED", rejection_round=1, disposition_reason_code="ILLEGIBLE"
    )
    # one open REQUIRED row plus one REJECTED row at any tier
    assert_readiness(env.matter(), blocking_count=2)

    rerequested = ok(
        api.transition_evidence(
            item["id"],
            {"action": "REREQUEST", "new_due_date": "2026-09-20"},
            headers=env.lead_rep,
        )
    )
    assert_fields(
        rerequested, status="REQUESTED", rejection_round=1, due_date="2026-09-20"
    )
    assert_null_fields(rerequested, "disposition_reason_code", "received_at_utc")
    assert_readiness(
        env.matter(), index="0.0000", ready_strict=False, blocking_count=1
    )


def test_re_requesting_with_a_due_date_already_past_is_a_shape_failure(api):
    """The new due date must be at or after the logical clock date.

    Design: Corner/state_machines/evidence_rerequest_with_past_due_date_returns_validation
    """
    env = template_a(api, clock=_CLOCK_UTC)
    item = _required_item(env)
    ok(api.transition_evidence(item["id"], {"action": "RECEIVE"}, headers=env.lead_rep))
    ok(
        api.transition_evidence(
            item["id"],
            {"action": "REJECT", "disposition_reason_code": "ILLEGIBLE"},
            headers=env.lead_rep,
        )
    )

    # one day before the clock date of 2026-08-03
    assert_error(
        api.transition_evidence(
            item["id"],
            {"action": "REREQUEST", "new_due_date": "2026-08-02"},
            headers=env.lead_rep,
        ),
        ERR_VALIDATION,
    )
    assert_fields(
        env.evidence_item(item["id"]), status="REJECTED", due_date="2026-09-01"
    )

    # the clock date itself is accepted
    assert_fields(
        ok(
            api.transition_evidence(
                item["id"],
                {"action": "REREQUEST", "new_due_date": "2026-08-03"},
                headers=env.lead_rep,
            )
        ),
        status="REQUESTED",
        due_date="2026-08-03",
    )


def test_the_declaration_revision_loop_counts_every_pass(api):
    """Draft, review, revision, draft: unbounded, with one monotonic counter.

    Resuming the draft clears the reason code and overwrites the word count, but
    it cannot walk the round counter back.

    Design: Corner/state_machines/declaration_revision_loop_increments_revision_round_twice
    """
    env = template_a(api, clock=_CLOCK_UTC)
    # the client prefers 'es' and the declaration is in 'es', so no read-back is owed
    declaration = created(
        api.create_declaration(
            factories.declaration_payload(
                env["matter_id"], env["lead_id"], language_code="es", word_count=800
            ),
            headers=env.lead_rep,
        )
    )

    def transition(action, headers=None, **payload):
        body = {"action": action}
        body.update(payload)
        return api.transition_declaration(
            declaration["id"], body, headers=headers or env.lead_rep
        )

    ok(transition("SUBMIT_FOR_REVIEW"))
    first = ok(
        transition(
            "REQUEST_REVISION",
            headers=env.supervisor,
            # PRD 3.7 draws the code from FACTUAL_GAP, LANGUAGE_MISMATCH,
            # MISSING_READBACK, EVIDENCE_INCONSISTENCY or SUPERVISION_REQUIRED.
            revision_reason_code="FACTUAL_GAP",
        )
    )
    assert_fields(first, status="REVISION_REQUESTED", revision_round=1)
    resumed = ok(transition("RESUME_DRAFT", word_count=1100))
    assert_fields(resumed, status="DRAFT", revision_round=1, word_count=1100)
    ok(transition("SUBMIT_FOR_REVIEW"))

    second = ok(
        transition(
            "REQUEST_REVISION",
            headers=env.supervisor,
            revision_reason_code="LANGUAGE_MISMATCH",
        )
    )
    assert_fields(
        second,
        status="REVISION_REQUESTED",
        revision_round=2,
        revision_reason_code="LANGUAGE_MISMATCH",
    )
    final = ok(transition("RESUME_DRAFT", word_count=1400))
    assert_fields(final, status="DRAFT", revision_round=2, word_count=1400)
    assert_null_fields(final, "revision_reason_code", "certified_at_utc")


def test_a_certified_declaration_cannot_be_withdrawn(api):
    """Withdrawal reaches the three working states, never the certified one.

    The refusal must also leave the read-back binding intact rather than clearing
    it as a side effect.

    Design: Corner/state_machines/certified_declaration_rejects_withdraw_as_terminal
    """
    env = template_b(api, clock=_CLOCK_UTC)
    assert_error(
        api.transition_declaration(
            env["decl_id"], {"action": "WITHDRAW"}, headers=env.supervisor
        ),
        ERR_INVALID_STATE_TRANSITION,
    )
    assert_fields(
        env.declaration(env["decl_id"]),
        status="CERTIFIED",
        readback_completed=True,
        readback_session_id=env["sess_id"],
        certified_at_utc=_CLOCK_UTC,
    )
    # a 45-minute CONTRACT 'es' read-back: 45 minutes at 9500 cents an hour
    assert_fields(env.matter(), interpretation_cost_cents=7125)
