"""Three nested program-committee formulas, each exercised at the point where the
nesting decides the answer.

The first is the acceptance waterfall. A conference that can physically hold one
oral and one poster presentation receives three identical ORAL decisions from the
same chair: the first takes the oral slot outright, the second spills down into
the poster tier and is flagged as downgraded, and the third — with nothing left
below it — lands on the waitlist with no format at all. The accepted-format
counters and the waitlist depth left behind on the conference are checked
alongside the three abstracts.

The second is continuing-education credit, where the whole result turns on
whether the fifteen-minute floor sits inside the aggregate or outside it. Twenty
and forty content minutes are floored per accreditation to a quarter credit and a
half credit and then summed to three quarter credits on the session ledger, while
the same sixty minutes summed first and floored once buy a full credit on the
conference planning read.

The third is the late change fee, whose day count to the event is frozen the
instant the request is filed. A substitution filed eight days out and approved
five days later is charged on the near tier it was quoted against, not on the
imminent tier the approval instant would have implied.
"""

import pytest

from test_helpers import (
    accreditation_validation_payload,
    add_slot,
    api_client,
    assert_cme_pool_conserved,
    assert_format_capacity_within_bounds,
    assert_quarter_credit_step,
    change_request_adjudication_payload,
    close_review_phase,
    create_accreditation_payload,
    create_disclosure_statement_payload,
    create_program_change_request_payload,
    create_session,
    decide_abstract,
    decision_payload,
    disclosure_adjudication_payload,
    get_conference_version,
    get_success_data,
    make_author_headers,
    make_program_chair_headers,
    register_author,
    release_decisions,
    set_clock,
    setup_scheduled_slot,
    setup_scored_abstracts,
    status_transition_payload,
    validate_success,
)

# ─── Instance setup: three SCORED abstracts against one oral and one poster ──


def _trio_awaiting_decisions() -> dict:
    """Conference at REVIEW_CLOSED with oral capacity 1, poster capacity 1 and no
    workshop capacity, holding three SCORED ORAL submissions by the same author."""
    world = setup_scored_abstracts(
        3,
        conference_overrides={
            "oral_slot_capacity": 1,
            "poster_slot_capacity": 1,
            "workshop_slot_capacity": 0,
        },
        category_overrides={
            "allowed_formats": ["ORAL", "POSTER"],
            "min_reviews_required": 2,
            "discrepancy_threshold": 4.00,
            "cme_eligible": False,
        },
    )
    close_review_phase(world)
    return world


def _decide_oral_with_downgrade(world: dict, abstract_id: str):
    """One ORAL decision with the downgrade flag on, as the deciding chair."""
    version = get_conference_version(world["conference"]["id"], world["chair_headers"])
    return api_client.decide_abstract(
        abstract_id,
        decision_payload("ORAL", version, allow_format_downgrade=True),
        world["chair_headers"],
    )


def _conference(world: dict) -> dict:
    return get_success_data(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )


def test_oral_decision_commits_to_oral_while_oral_capacity_remains():
    """For each format, remaining capacity is that format's declared slot capacity minus the conference's accepted count for that format.
    An `ORAL` decision commits to `ORAL` when remaining oral capacity is at least one.
    A committed decision moves the abstract from `SCORED` to `ACCEPTED`, writes the waterfall-resolved format into `decision`, sets `decision_downgraded` to true exactly when that resolved format differs from the format the chair asked for, records `decided_by_member_id`, raises the matching accepted count on the conference and advances the conference's `version`.

    Design: Difficulty/combinatorial_formula/oral_to_poster_to_waitlist_waterfall_nested_branching
    """
    world = _trio_awaiting_decisions()
    chair = world["members"]["cho"]

    res = _decide_oral_with_downgrade(world, world["abstracts"][0]["id"])
    decided = validate_success(res)

    assert decided["status"] == "ACCEPTED"
    assert decided["decision"] == "ORAL"
    assert decided["decision_downgraded"] is False
    assert decided["decided_by_member_id"] == chair["id"]

    conference = _conference(world)
    assert conference["accepted_oral_count"] == 1
    assert conference["accepted_poster_count"] == 0
    assert conference["waitlisted_count"] == 0


def test_oral_decision_downgrades_to_poster_when_oral_capacity_is_spent():
    """When it is zero, `allow_format_downgrade` is true, `POSTER` is among the category's `allowed_formats` and remaining poster capacity is at least one, the abstract is committed as a `POSTER` and `decision_downgraded` is set to true.
    A committed decision moves the abstract from `SCORED` to `ACCEPTED`, writes the waterfall-resolved format into `decision`, sets `decision_downgraded` to true exactly when that resolved format differs from the format the chair asked for, records `decided_by_member_id`, raises the matching accepted count on the conference and advances the conference's `version`.

    Design: Difficulty/combinatorial_formula/oral_to_poster_to_waitlist_waterfall_nested_branching
    """
    world = _trio_awaiting_decisions()
    chair = world["members"]["cho"]
    validate_success(_decide_oral_with_downgrade(world, world["abstracts"][0]["id"]))

    res = _decide_oral_with_downgrade(world, world["abstracts"][1]["id"])
    downgraded = validate_success(res)

    assert downgraded["status"] == "ACCEPTED"
    assert downgraded["decision"] == "POSTER"
    assert downgraded["decision_downgraded"] is True
    assert downgraded["decided_by_member_id"] == chair["id"]
    assert downgraded["requested_format"] == "ORAL"

    conference = _conference(world)
    assert conference["accepted_oral_count"] == 1
    assert conference["accepted_poster_count"] == 1
    assert conference["waitlisted_count"] == 0


def test_oral_decision_waitlists_when_oral_and_poster_capacity_are_both_spent():
    """When none of those hold, the abstract is waitlisted.
    A waitlisted outcome moves the abstract from `SCORED` to `WAITLISTED`, leaves `decision` null, still records `decided_by_member_id`, raises the conference's `waitlisted_count` by one and advances the conference's `version`.

    Design: Difficulty/combinatorial_formula/oral_to_poster_to_waitlist_waterfall_nested_branching
    """
    world = _trio_awaiting_decisions()
    chair = world["members"]["cho"]
    validate_success(_decide_oral_with_downgrade(world, world["abstracts"][0]["id"]))
    validate_success(_decide_oral_with_downgrade(world, world["abstracts"][1]["id"]))

    res = _decide_oral_with_downgrade(world, world["abstracts"][2]["id"])
    waitlisted = validate_success(res)

    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["decision"] is None
    assert waitlisted["decided_by_member_id"] == chair["id"]


def test_capacity_ledger_after_the_oral_poster_waitlist_waterfall():
    """A conference's `accepted_oral_count`, `accepted_poster_count` and `accepted_workshop_count` each equal the number of that conference's abstracts whose `decision` is the matching format and whose `status` is one of `ACCEPTED`, `CONFIRMED`, `SCHEDULED`, `PRESENTED` or `NO_SHOW`.
    Its `waitlisted_count` equals the number of its abstracts whose `status` is `WAITLISTED`.

    Design: Difficulty/combinatorial_formula/oral_to_poster_to_waitlist_waterfall_nested_branching
    """
    world = _trio_awaiting_decisions()
    for abstract in world["abstracts"]:
        validate_success(_decide_oral_with_downgrade(world, abstract["id"]))

    conference = _conference(world)
    assert conference["accepted_oral_count"] == 1
    assert conference["accepted_poster_count"] == 1
    assert conference["accepted_workshop_count"] == 0
    assert conference["waitlisted_count"] == 1
    assert_format_capacity_within_bounds(conference)


# ─── Instance setup: two accredited slots inside one designated session ──────


def _two_scheduled_slots_awaiting_accreditation() -> dict:
    """One `cme_designated` session holding two SCHEDULED slots, each abstract
    carrying a PENDING accreditation (20 then 40 content minutes) whose single
    disclosure has already been validated by the non-deciding chair."""
    world = setup_scored_abstracts(
        2,
        conference_overrides={
            "oral_slot_capacity": 3,
            "poster_slot_capacity": 2,
            "workshop_slot_capacity": 1,
            "cme_minutes_pool_total": 600,
        },
        category_overrides={
            "allowed_formats": ["ORAL", "POSTER"],
            "min_reviews_required": 2,
            "discrepancy_threshold": 4.00,
            "cme_eligible": True,
        },
    )
    close_review_phase(world)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = decide_abstract(world, abstract["id"], "ORAL")
    release_decisions(world)

    ada = world["authors"]["ada"]
    register_author(ada["id"], True)
    author_headers = make_author_headers(ada["id"])
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = get_success_data(
            api_client.transition_abstract(
                abstract["id"], status_transition_payload("CONFIRMED"), author_headers
            )
        )

    session = create_session(world, cme_designated=True, capacity_slots=3)
    for index, abstract in enumerate(world["abstracts"]):
        add_slot(
            world,
            session,
            abstract["id"],
            ada["id"],
            position=index + 1,
            duration_minutes=20,
        )

    validator_headers = world["second_chair_headers"]
    world["accreditations"] = []
    for abstract, minutes in zip(world["abstracts"], (20, 40)):
        accreditation = get_success_data(
            api_client.create_accreditation(
                create_accreditation_payload(abstract["id"], minutes), validator_headers
            )
        )
        disclosure = get_success_data(
            api_client.create_disclosure_statement(
                create_disclosure_statement_payload(
                    abstract["id"], accreditation["id"], ada["id"]
                ),
                author_headers,
            )
        )
        get_success_data(
            api_client.adjudicate_disclosure_statement(
                disclosure["id"],
                disclosure_adjudication_payload("VALIDATED"),
                validator_headers,
            )
        )
        world["accreditations"].append(accreditation)
    return world


def _validate_both_accreditations(world: dict) -> list:
    validator = world["members"]["dana"]
    validated = []
    for accreditation in world["accreditations"]:
        res = api_client.validate_accreditation(
            accreditation["id"],
            accreditation_validation_payload("VALIDATE"),
            make_program_chair_headers(validator["id"]),
        )
        validated.append(validate_success(res))
    return validated


def test_awarded_credits_floor_each_accreditation_before_any_summing():
    """The **per-abstract award** is what an accreditation actually earns and what feeds a session's ledger: for each validated accreditation, divide its `content_minutes` by fifteen, discard the remainder by rounding down to a whole number, and multiply by 0.25; the total over a set is the sum of those individually floored awards.
    Leftover minutes below fifteen are lost per abstract.

    Design: Difficulty/combinatorial_formula/cme_floor_per_accreditation_before_sum_pins_nested_rounding_order
    """
    world = _two_scheduled_slots_awaiting_accreditation()

    first, second = _validate_both_accreditations(world)

    assert first["validation_status"] == "VALIDATED"
    assert second["validation_status"] == "VALIDATED"
    assert float(first["awarded_credits"]) == pytest.approx(0.25, abs=0.01)
    assert float(second["awarded_credits"]) == pytest.approx(0.50, abs=0.01)
    assert_quarter_credit_step(first["awarded_credits"])
    assert_quarter_credit_step(second["awarded_credits"])


def test_session_credit_total_sums_the_individually_floored_awards():
    """A session's `accredited_credit_total` uses the per-abstract route, summing the credits of its counted slots whose accreditation is `VALIDATED`, at two decimal places.
    A session's `accreditation_posture` follows from it: `NOT_APPLICABLE` whenever `cme_designated` is false, otherwise `COMPLIANT` when `accredited_credit_total` is at least 0.50 and `NON_COMPLIANT` when it is below that.

    Design: Difficulty/combinatorial_formula/cme_floor_per_accreditation_before_sum_pins_nested_rounding_order
    """
    world = _two_scheduled_slots_awaiting_accreditation()
    _validate_both_accreditations(world)

    session = get_success_data(
        api_client.get_session(world["sessions"][0]["id"], world["chair_headers"])
    )

    assert float(session["accredited_credit_total"]) == pytest.approx(0.75, abs=0.01)
    assert session["accreditation_posture"] == "COMPLIANT"


def test_bundle_credits_exceed_the_per_abstract_sum_on_the_capacity_read():
    """The **session bundle estimate** is a conference-level planning figure: sum the `content_minutes` of the validated set first, then divide that single total by fifteen, round down to a whole number once, and multiply by 0.25.
    Both figures are visible side by side on the conference capacity read, which reports the conference's identifier, remaining oral, poster and workshop capacity, the `waitlisted_count`, `cme_minutes_available`, the bundle figure as `cme_bundle_credits`, the plain sum of per-abstract `awarded_credits` as `awarded_credits_sum`, and the count of accredited sessions as `accredited_session_count`.
    The gap between `cme_bundle_credits` and `awarded_credits_sum` is expected, not a defect.

    Design: Difficulty/combinatorial_formula/cme_floor_per_accreditation_before_sum_pins_nested_rounding_order
    """
    world = _two_scheduled_slots_awaiting_accreditation()
    _validate_both_accreditations(world)

    summary = validate_success(
        api_client.get_capacity_summary(
            world["conference"]["id"], world["chair_headers"]
        )
    )

    assert float(summary["awarded_credits_sum"]) == pytest.approx(0.75, abs=0.01)
    assert float(summary["cme_bundle_credits"]) == pytest.approx(1.00, abs=0.01)
    assert float(summary["cme_bundle_credits"]) - float(
        summary["awarded_credits_sum"]
    ) == pytest.approx(0.25, abs=0.01)


def test_minute_pool_debited_by_the_validated_content_minutes():
    """A conference's `cme_minutes_allocated` equals the sum of `content_minutes` over its accreditations whose `validation_status` is `VALIDATED`, and `cme_minutes_available` is always `cme_minutes_pool_total` minus `cme_minutes_allocated`.

    Design: Difficulty/combinatorial_formula/cme_floor_per_accreditation_before_sum_pins_nested_rounding_order
    """
    world = _two_scheduled_slots_awaiting_accreditation()
    _validate_both_accreditations(world)

    conference = _conference(world)
    assert conference["cme_minutes_allocated"] == 60
    assert conference["cme_minutes_available"] == 540
    assert_cme_pool_conserved(conference)

    summary = validate_success(
        api_client.get_capacity_summary(
            world["conference"]["id"], world["chair_headers"]
        )
    )
    assert summary["cme_minutes_available"] == 540


# ─── Instance setup: one SCHEDULED slot and a late substitution request ──────

SUBMISSION_INSTANT = "2026-08-24T08:00:00Z"
APPROVAL_INSTANT = "2026-08-29T08:00:00Z"


def _slot_with_coauthor_standing_by() -> dict:
    """A SCHEDULED oral slot presented by Ada, whose abstract names Ben as a
    co-author, with the clock advanced past the program freeze to eight whole
    days before the event opens."""
    world = setup_scheduled_slot(
        abstract_overrides={"coauthor_emails": ["ben@lab.example"]}
    )
    set_clock(SUBMISSION_INSTANT)
    return world


def _open_substitution_request(world: dict):
    ada = world["authors"]["ada"]
    payload = create_program_change_request_payload(
        world["slots"][0]["id"],
        "SUBSTITUTE_PRESENTER",
        requested_by_author_id=ada["id"],
        substitute_presenter_author_id=world["authors"]["ben"]["id"],
        reason="visa refused",
    )
    return api_client.create_program_change_request(payload, make_author_headers(ada["id"]))


def test_change_request_freezes_the_day_count_and_quotes_the_gentler_estimate():
    """Creation stamps `submitted_at` from the logical clock and freezes `days_to_event` onto the row: the number of whole 86,400-second days from `submitted_at` to the conference's `event_start_utc`, rounded down, which may be negative for a request filed after the event has begun.
    The base fee depends only on `change_type`: 4,000 cents for a `MOVE`, 6,000 for a `SWAP`, 2,500 for a `SUBSTITUTE_PRESENTER` and nothing at all for a `WITHDRAW`.
    A rush percentage is then selected from the frozen `days_to_event`, using three bands: fourteen days or more out is the relaxed band, seven to thirteen days out inclusive is the near band, and fewer than seven days out is the imminent band.
    The **estimate quoted at submission** uses the gentler table — zero percent in the relaxed band, ten percent in the near band, twenty-five percent in the imminent band — applies it to the base fee, rounds half up to whole cents, and adds no surcharge of any kind.

    Design: Difficulty/combinatorial_formula/change_fee_days_to_event_frozen_at_submission_pins_evaluation_order
    """
    world = _slot_with_coauthor_standing_by()

    request = validate_success(_open_substitution_request(world), 201)

    assert request["submitted_at"].startswith("2026-08-24T08:00:00")
    assert request["days_to_event"] == 8
    assert request["estimated_fee_cents"] == 2750
    assert request["status"] == "PENDING"
    assert request["final_fee_cents"] is None
    assert request["rush_pct_applied"] is None


def test_final_fee_uses_the_frozen_day_count_not_the_approval_instant():
    """That figure is stored in `estimated_fee_cents` and is never revised afterwards.
    The **final fee charged at approval** uses the steeper table — zero percent relaxed, twenty percent near, fifty percent imminent — on the same frozen `days_to_event`, rounds the uplifted base half up to whole cents, and then adds a flat 1,500-cent post-freeze surcharge when the request's `submitted_at` is at or after the conference's `program_freeze_utc`.
    The result is stored in `final_fee_cents`, and the steeper percentage that was applied is recorded in `rush_pct_applied`.

    Design: Difficulty/combinatorial_formula/change_fee_days_to_event_frozen_at_submission_pins_evaluation_order
    """
    world = _slot_with_coauthor_standing_by()
    request = validate_success(_open_substitution_request(world), 201)

    set_clock(APPROVAL_INSTANT)
    res = api_client.adjudicate_program_change_request(
        request["id"],
        change_request_adjudication_payload(
            "APPROVED", note="approved five days after submission"
        ),
        world["chair_headers"],
    )
    approved = validate_success(res)

    assert approved["status"] == "APPLIED"
    assert approved["days_to_event"] == 8
    assert approved["estimated_fee_cents"] == 2750
    assert float(approved["rush_pct_applied"]) == pytest.approx(20, abs=0.01)
    assert approved["final_fee_cents"] == 4500, (
        "the near tier frozen at submission charges 2500 uplifted twenty percent "
        "plus the 1500 post-freeze surcharge, not the imminent tier of the "
        "approval instant"
    )
    assert approved["final_fee_cents"] != 5250


def test_approved_substitution_hands_the_slot_to_the_named_coauthor():
    """Approval moves it to `APPLIED` and requires that the referenced slot still be `SCHEDULED`; for a `MOVE` or a `SWAP` it additionally requires that the target session's `format` equal the slot abstract's `decision`, that the target session's `theme_code` be one of that abstract's `keywords`, and that the target session's `slot_count` be strictly less than its `capacity_slots`.
    A `SUBSTITUTE_PRESENTER` replaces the slot's `presenter_author_id` with the `substitute_presenter_author_id`.

    Design: Difficulty/combinatorial_formula/change_fee_days_to_event_frozen_at_submission_pins_evaluation_order
    """
    world = _slot_with_coauthor_standing_by()
    request = validate_success(_open_substitution_request(world), 201)

    set_clock(APPROVAL_INSTANT)
    approved = validate_success(
        api_client.adjudicate_program_change_request(
            request["id"],
            change_request_adjudication_payload("APPROVED"),
            world["chair_headers"],
        )
    )
    assert approved["status"] == "APPLIED"
    assert approved["approver_member_id"] == world["members"]["cho"]["id"]

    slot = get_success_data(
        api_client.get_session_slot(world["slots"][0]["id"], world["chair_headers"])
    )
    assert slot["presenter_author_id"] == world["authors"]["ben"]["id"]
