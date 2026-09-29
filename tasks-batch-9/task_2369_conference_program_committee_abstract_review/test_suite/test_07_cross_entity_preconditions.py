"""Preconditions that live on a neighbouring record.

Three gates in the program pipeline read the state of an entity other than the
one being written:

* an author may only turn an acceptance into a commitment once that author's
  own event registration is on file, so the confirmation of an abstract hangs
  on the presenting author's registration flag;
* a chair may only place an abstract into a running-order slot once its author
  has confirmed, so slot creation hangs on the abstract's confirmation;
* a chair may only validate continuing-education content once every disclosure
  filed against that accreditation has been adjudicated, so accreditation
  validation hangs on the disclosure adjudication.

Each gate is exercised twice over: once with the neighbouring record still in
the wrong state, and once after that record has reached the state the rule
demands, so the same payload is seen to fail and then to succeed.
"""

import pytest

from test_helpers import (
    ADMIN,
    accreditation_validation_payload,
    api_client,
    assert_accreditation,
    assert_cme_pool_conserved,
    assert_session_slot,
    create_accreditation_payload,
    create_disclosure_statement_payload,
    create_session,
    create_session_slot_payload,
    disclosure_adjudication_payload,
    get_success_data,
    register_author,
    register_author_payload,
    release_decisions,
    setup_confirmed_abstract,
    setup_decided_abstract,
    setup_scheduled_slot,
    setup_validated_accreditation,
    status_transition_payload,
    validate_error,
    validate_success,
)


# ─── local setup helpers (no fixture covers these exact states) ───────────


def _accepted_abstract_awaiting_confirmation() -> dict:
    """A decided ORAL abstract with decisions released and its author still
    unregistered."""
    world = setup_decided_abstract("ORAL")
    release_decisions(world)
    return world


def _pending_accreditation_with_unadjudicated_disclosure(
    content_minutes: int = 30,
) -> dict:
    """A PENDING accreditation whose single disclosure is still SUBMITTED."""
    world = setup_decided_abstract(
        "ORAL", category_overrides={"cme_eligible": True, "min_reviews_required": 2}
    )
    abstract = world["abstracts"][0]
    world["accreditation"] = get_success_data(
        api_client.create_accreditation(
            create_accreditation_payload(abstract["id"], content_minutes),
            world["second_chair_headers"],
        )
    )
    world["disclosure"] = get_success_data(
        api_client.create_disclosure_statement(
            create_disclosure_statement_payload(
                abstract["id"],
                world["accreditation"]["id"],
                world["authors"]["ada"]["id"],
                has_financial_relationship=False,
            ),
            world["author_headers"],
        )
    )
    return world


def _session_version(session_id: str, headers) -> int:
    return get_success_data(api_client.get_session(session_id, headers))["version"]


# ─── Confirmation gated on the presenting author's registration ───────────


def test_confirmation_rejected_while_presenting_author_is_unregistered():
    """An author converts an acceptance into a commitment by moving their abstract from `ACCEPTED` to `CONFIRMED`. Only the submitting author may do so; the conference must be `DECISIONS_RELEASED` or `PROGRAM_PUBLISHED`; the author's `is_registered` must be true, or the request fails with `ERR_AUTHOR_NOT_REGISTERED`; and the author's `sanction_status` must not be `BARRED`, or it fails with `ERR_AUTHOR_BARRED`.

    Presenter registration — `ERR_AUTHOR_NOT_REGISTERED` (422), enforced only on the `ACCEPTED` to `CONFIRMED` transition of `POST /abstracts/{abstractId}/status-transitions`. Unregistered authors may still submit and be reviewed.

    Later violations are never reported, and no partial write ever survives a rejection.

    Design: Difficulty/cross_entity_state_dependency/abstract_confirmation_depends_on_author_registration_state
    """
    world = _accepted_abstract_awaiting_confirmation()
    abstract = world["abstracts"][0]
    author = world["authors"]["ada"]

    live_author = get_success_data(api_client.get_author(author["id"], ADMIN))
    assert live_author["is_registered"] is False
    assert live_author["registered_at"] is None

    res = api_client.transition_abstract(
        abstract["id"],
        status_transition_payload("CONFIRMED"),
        world["author_headers"],
    )
    validate_error(res, "ERR_AUTHOR_NOT_REGISTERED", 422)

    after = get_success_data(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert after["status"] == "ACCEPTED"
    assert after["decision"] == "ORAL"


def test_confirmation_succeeds_once_presenting_author_is_registered():
    """An author converts an acceptance into a commitment by moving their abstract from `ACCEPTED` to `CONFIRMED`. Only the submitting author may do so; the conference must be `DECISIONS_RELEASED` or `PROGRAM_PUBLISHED`; the author's `is_registered` must be true, or the request fails with `ERR_AUTHOR_NOT_REGISTERED`; and the author's `sanction_status` must not be `BARRED`, or it fails with `ERR_AUTHOR_BARRED`.

    Event registration is recorded separately, by the author or by operations staff, through a boolean `is_registered`; when it becomes true the author's `registered_at` is stamped with the logical-clock instant, and when it is set back to false `registered_at` returns to null.

    This capability exists precisely because confirmation of an acceptance is gated on paid registration and nothing else can set the flag.

    Design: Difficulty/cross_entity_state_dependency/abstract_confirmation_depends_on_author_registration_state
    """
    world = _accepted_abstract_awaiting_confirmation()
    abstract = world["abstracts"][0]
    author = world["authors"]["ada"]

    blocked = api_client.transition_abstract(
        abstract["id"],
        status_transition_payload("CONFIRMED"),
        world["author_headers"],
    )
    validate_error(blocked, "ERR_AUTHOR_NOT_REGISTERED", 422)

    registered = validate_success(
        api_client.register_author(
            author["id"], register_author_payload(True), ADMIN
        )
    )
    assert registered["is_registered"] is True
    assert registered["registered_at"].startswith("2026-01-05T00:00:00")

    confirmed = validate_success(
        api_client.transition_abstract(
            abstract["id"],
            status_transition_payload("CONFIRMED"),
            world["author_headers"],
        )
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["decision"] == "ORAL"


def test_confirmation_rejected_again_after_registration_is_cleared():
    """An author converts an acceptance into a commitment by moving their abstract from `ACCEPTED` to `CONFIRMED`. Only the submitting author may do so; the conference must be `DECISIONS_RELEASED` or `PROGRAM_PUBLISHED`; the author's `is_registered` must be true, or the request fails with `ERR_AUTHOR_NOT_REGISTERED`; and the author's `sanction_status` must not be `BARRED`, or it fails with `ERR_AUTHOR_BARRED`.

    Event registration is recorded separately, by the author or by operations staff, through a boolean `is_registered`; when it becomes true the author's `registered_at` is stamped with the logical-clock instant, and when it is set back to false `registered_at` returns to null.

    Design: Difficulty/cross_entity_state_dependency/abstract_confirmation_depends_on_author_registration_state
    """
    world = _accepted_abstract_awaiting_confirmation()
    abstract = world["abstracts"][0]
    author = world["authors"]["ada"]

    register_author(author["id"], True)
    cleared = validate_success(
        api_client.register_author(
            author["id"], register_author_payload(False), ADMIN
        )
    )
    assert cleared["is_registered"] is False
    assert cleared["registered_at"] is None

    res = api_client.transition_abstract(
        abstract["id"],
        status_transition_payload("CONFIRMED"),
        world["author_headers"],
    )
    validate_error(res, "ERR_AUTHOR_NOT_REGISTERED", 422)

    after = get_success_data(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert after["status"] == "ACCEPTED"


# ─── Slot creation gated on the abstract being confirmed ──────────────────


def test_slot_creation_rejected_while_abstract_is_only_accepted():
    """The abstract must be `CONFIRMED`, with `ERR_ABSTRACT_STATE_INVALID` otherwise.

    A session's `committed_minutes` is the sum of `duration_minutes` over its counted slots plus a five-minute changeover allowance for each gap between consecutive counted slots — that is, five minutes multiplied by one less than the number of counted slots, and zero when there are no slots at all.

    Later violations are never reported, and no partial write ever survives a rejection.

    Design: Difficulty/cross_entity_state_dependency/slot_creation_depends_on_abstract_confirmation_state
    """
    world = _accepted_abstract_awaiting_confirmation()
    abstract = world["abstracts"][0]
    register_author(world["authors"]["ada"]["id"], True)
    session = create_session(world, capacity_slots=4)
    chair_headers = world["chair_headers"]

    res = api_client.create_session_slot(
        session["id"],
        create_session_slot_payload(
            abstract["id"],
            world["authors"]["ada"]["id"],
            1,
            30,
            session["version"],
        ),
        chair_headers,
    )
    validate_error(res, "ERR_ABSTRACT_STATE_INVALID", 409)

    after_session = get_success_data(api_client.get_session(session["id"], chair_headers))
    assert after_session["slot_count"] == 0
    assert after_session["committed_minutes"] == 0

    after_abstract = get_success_data(
        api_client.get_abstract(abstract["id"], chair_headers)
    )
    assert after_abstract["status"] == "ACCEPTED"


def test_slot_creation_succeeds_once_author_confirms_the_abstract():
    """The abstract must be `CONFIRMED`, with `ERR_ABSTRACT_STATE_INVALID` otherwise.

    A successful placement moves the abstract from `CONFIRMED` to `SCHEDULED`, raises the session's `slot_count` by one, recomputes `committed_minutes`, `accredited_credit_total` and `accreditation_posture`, and advances the session's `version`.

    The slot itself starts in `SCHEDULED` status with `swapped_with_slot_id` null.

    A session's `committed_minutes` is the sum of `duration_minutes` over its counted slots plus a five-minute changeover allowance for each gap between consecutive counted slots — that is, five minutes multiplied by one less than the number of counted slots, and zero when there are no slots at all.

    `NOT_APPLICABLE` whenever `cme_designated` is false, otherwise `COMPLIANT` when `accredited_credit_total` is at least 0.50 and `NON_COMPLIANT` when it is below that.

    Design: Difficulty/cross_entity_state_dependency/slot_creation_depends_on_abstract_confirmation_state
    """
    world = setup_confirmed_abstract("ORAL")
    abstract = world["abstracts"][0]
    assert abstract["status"] == "CONFIRMED"
    session = create_session(world, capacity_slots=4)
    chair_headers = world["chair_headers"]

    slot = validate_success(
        api_client.create_session_slot(
            session["id"],
            create_session_slot_payload(
                abstract["id"],
                world["authors"]["ada"]["id"],
                1,
                30,
                _session_version(session["id"], chair_headers),
            ),
            chair_headers,
        ),
        201,
    )
    assert_session_slot(slot)
    assert slot["status"] == "SCHEDULED"
    assert slot["position"] == 1
    assert slot["duration_minutes"] == 30
    assert slot["swapped_with_slot_id"] is None

    after_abstract = get_success_data(
        api_client.get_abstract(abstract["id"], chair_headers)
    )
    assert after_abstract["status"] == "SCHEDULED"

    after_session = get_success_data(api_client.get_session(session["id"], chair_headers))
    assert after_session["slot_count"] == 1
    assert after_session["committed_minutes"] == 30
    assert after_session["accreditation_posture"] == "NOT_APPLICABLE"


def test_slot_creation_rejected_once_abstract_has_moved_past_confirmed():
    """The abstract must be `CONFIRMED`, with `ERR_ABSTRACT_STATE_INVALID` otherwise.

    A successful placement moves the abstract from `CONFIRMED` to `SCHEDULED`, raises the session's `slot_count` by one, recomputes `committed_minutes`, `accredited_credit_total` and `accreditation_posture`, and advances the session's `version`.

    Design: Difficulty/cross_entity_state_dependency/slot_creation_depends_on_abstract_confirmation_state
    """
    world = setup_scheduled_slot()
    abstract = world["abstracts"][0]
    chair_headers = world["chair_headers"]
    assert (
        get_success_data(api_client.get_abstract(abstract["id"], chair_headers))["status"]
        == "SCHEDULED"
    )

    second_session = create_session(
        world,
        room_code="HALL-B",
        start_utc="2026-09-01T10:15:00Z",
        end_utc="2026-09-01T11:15:00Z",
        capacity_slots=4,
    )

    res = api_client.create_session_slot(
        second_session["id"],
        create_session_slot_payload(
            abstract["id"],
            world["authors"]["ada"]["id"],
            1,
            30,
            second_session["version"],
        ),
        chair_headers,
    )
    validate_error(res, "ERR_ABSTRACT_STATE_INVALID", 409)

    after = get_success_data(api_client.get_session(second_session["id"], chair_headers))
    assert after["slot_count"] == 0
    assert after["committed_minutes"] == 0


# ─── Accreditation validation gated on the disclosure adjudication ────────


def test_accreditation_validation_rejected_while_disclosure_awaits_adjudication():
    """Validation moves the row from `PENDING` to `VALIDATED` and has four preconditions: the acting chair must not be the member recorded in the abstract's `decided_by_member_id`, or the response is `ERR_ACCREDITATION_SELF_VALIDATION`; at least one disclosure must exist for the accreditation and every one of them must be `VALIDATED`, or the response is `ERR_DISCLOSURE_INCOMPLETE`; the accreditation's `commercial_bias_flag` must be false, which is the second trigger for that same error; and `content_minutes` must be less than or equal to the conference's `cme_minutes_available`, or the response is `ERR_CME_POOL_EXHAUSTED`.

    A conference's `cme_minutes_allocated` equals the sum of `content_minutes` over its accreditations whose `validation_status` is `VALIDATED`, and `cme_minutes_available` is always `cme_minutes_pool_total` minus `cme_minutes_allocated`.

    Later violations are never reported, and no partial write ever survives a rejection.

    Design: Difficulty/cross_entity_state_dependency/accreditation_validation_depends_on_disclosure_adjudication_state
    """
    world = _pending_accreditation_with_unadjudicated_disclosure(30)
    accreditation = world["accreditation"]
    assert world["disclosure"]["status"] == "SUBMITTED"
    assert world["disclosure"]["mitigation_required"] is False

    res = api_client.validate_accreditation(
        accreditation["id"],
        accreditation_validation_payload("VALIDATE"),
        world["second_chair_headers"],
    )
    validate_error(res, "ERR_DISCLOSURE_INCOMPLETE", 409)

    after = get_success_data(
        api_client.get_accreditation(accreditation["id"], ADMIN)
    )
    assert_accreditation(after)
    assert after["validation_status"] == "PENDING"
    assert float(after["awarded_credits"]) == pytest.approx(0.00, abs=0.01)

    conference = get_success_data(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert conference["cme_minutes_allocated"] == 0
    assert conference["cme_minutes_available"] == 600
    assert_cme_pool_conserved(conference)


def test_accreditation_validation_succeeds_once_disclosure_is_validated():
    """Validation moves the row from `PENDING` to `VALIDATED` and has four preconditions: the acting chair must not be the member recorded in the abstract's `decided_by_member_id`, or the response is `ERR_ACCREDITATION_SELF_VALIDATION`; at least one disclosure must exist for the accreditation and every one of them must be `VALIDATED`, or the response is `ERR_DISCLOSURE_INCOMPLETE`; the accreditation's `commercial_bias_flag` must be false, which is the second trigger for that same error; and `content_minutes` must be less than or equal to the conference's `cme_minutes_available`, or the response is `ERR_CME_POOL_EXHAUSTED`.

    On success the row's `awarded_credits` is computed, `validated_by_member_id` and `validated_at` are set, the conference's `cme_minutes_allocated` rises by `content_minutes` with `cme_minutes_available` recomputed and the conference's `version` advanced, and the session holding a counted slot for that abstract recomputes its `accredited_credit_total` and `accreditation_posture` with its own `version` advanced.

    On creation the row's `status` is `SUBMITTED`, its `mitigation_required` is set to exactly the value of `has_financial_relationship`, its `mitigation_completed` defaults to false, its `rejection_reason` is null, and the parent accreditation's `commercial_bias_flag` is recomputed.

    The **per-abstract award** is what an accreditation actually earns and what feeds a session's ledger: for each validated accreditation, divide its `content_minutes` by fifteen, discard the remainder by rounding down to a whole number, and multiply by 0.25; the total over a set is the sum of those individually floored awards.

    A conference's `cme_minutes_allocated` equals the sum of `content_minutes` over its accreditations whose `validation_status` is `VALIDATED`, and `cme_minutes_available` is always `cme_minutes_pool_total` minus `cme_minutes_allocated`.

    Design: Difficulty/cross_entity_state_dependency/accreditation_validation_depends_on_disclosure_adjudication_state
    """
    world = setup_validated_accreditation(content_minutes=30, validate=False)
    accreditation = world["accreditation"]
    validator = world["members"]["dana"]

    assert world["disclosure"]["status"] == "VALIDATED"
    assert world["disclosure"]["mitigation_required"] is False
    assert accreditation["validation_status"] == "PENDING"

    validated = validate_success(
        api_client.validate_accreditation(
            accreditation["id"],
            accreditation_validation_payload("VALIDATE"),
            world["second_chair_headers"],
        )
    )
    assert_accreditation(validated)
    assert validated["validation_status"] == "VALIDATED"
    assert float(validated["awarded_credits"]) == pytest.approx(0.50, abs=0.01)
    assert validated["validated_by_member_id"] == validator["id"]

    conference = get_success_data(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert conference["cme_minutes_allocated"] == 30
    assert conference["cme_minutes_available"] == 570
    assert_cme_pool_conserved(conference)


def test_accreditation_validation_rejected_when_disclosure_was_rejected():
    """Validation moves the row from `PENDING` to `VALIDATED` and has four preconditions: the acting chair must not be the member recorded in the abstract's `decided_by_member_id`, or the response is `ERR_ACCREDITATION_SELF_VALIDATION`; at least one disclosure must exist for the accreditation and every one of them must be `VALIDATED`, or the response is `ERR_DISCLOSURE_INCOMPLETE`; the accreditation's `commercial_bias_flag` must be false, which is the second trigger for that same error; and `content_minutes` must be less than or equal to the conference's `cme_minutes_available`, or the response is `ERR_CME_POOL_EXHAUSTED`.

    An outcome of `REJECTED` requires a `rejection_reason` and is reachable both from `SUBMITTED` and — as a post-hoc disclosure failure — from `VALIDATED`; the latter path is what triggers Cascade A in full.

    Design: Difficulty/cross_entity_state_dependency/accreditation_validation_depends_on_disclosure_adjudication_state
    """
    world = _pending_accreditation_with_unadjudicated_disclosure(30)
    accreditation = world["accreditation"]

    rejected = validate_success(
        api_client.adjudicate_disclosure_statement(
            world["disclosure"]["id"],
            disclosure_adjudication_payload(
                "REJECTED", rejection_reason="relationship could not be verified"
            ),
            world["second_chair_headers"],
        )
    )
    assert rejected["status"] == "REJECTED"

    res = api_client.validate_accreditation(
        accreditation["id"],
        accreditation_validation_payload("VALIDATE"),
        world["second_chair_headers"],
    )
    validate_error(res, "ERR_DISCLOSURE_INCOMPLETE", 409)

    after = get_success_data(api_client.get_accreditation(accreditation["id"], ADMIN))
    assert after["validation_status"] == "PENDING"
    assert float(after["awarded_credits"]) == pytest.approx(0.00, abs=0.01)

    conference = get_success_data(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert conference["cme_minutes_allocated"] == 0
    assert_cme_pool_conserved(conference)
