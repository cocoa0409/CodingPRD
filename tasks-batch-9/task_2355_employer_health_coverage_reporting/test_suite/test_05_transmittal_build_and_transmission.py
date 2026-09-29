"""Assembling, building and transmitting the 1094-C submission (PRD §3.8).

Covers the return-count arithmetic that decides the transmission channel, the
replacement round a rejected submission runs, the ladder order between the
transmittal-state rung and the electronic-channel rung, and the attach/detach
pair that conserves the member's generated statement count.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_form_1095c,
    assert_group_member,
    assert_transmittal,
    factories,
    fixtures,
    validate_error,
)

AGENT_1 = TEST_USERS["filing_agent"]
AGENT_2 = TEST_USERS["filing_agent_2"]


def _member_with_generated_forms(api, employee_count, season_overrides=None):
    """Season → determined-ALE group → one member → ``employee_count`` employees,
    each hired before the reporting year and each holding one original statement.

    Returns the prelude context with a ``forms`` list in generation order.
    """
    ctx = fixtures.determined_ale_group(api, season_overrides=season_overrides)
    ctx["forms"] = []
    for index in range(employee_count):
        employee = fixtures.create_employee(
            api,
            ctx["member"]["id"],
            full_name=f"Statement Holder {index + 1}",
            ssn_last4=f"10{index + 1:02d}",
        )
        ctx["forms"].append(fixtures.generate_form(api, employee["id"]))
    return ctx


# ---------------------------------------------------------------------------
# The return count: this submission alone versus the member's counted siblings
# ---------------------------------------------------------------------------
def test_first_submission_return_count_counts_its_own_forms_plus_the_1094c(api):
    """PRD §3.8: "`form_count` is this transmittal's attached statements whose filing
    dimension is not `VOIDED`."
    PRD §3.8: "To it are added the frozen `form_count` values of every *other*
    transmittal of the same member sitting in `BUILT`, `TRANSMITTED`, `ACCEPTED`,
    `ACCEPTED_WITH_ERRORS` or `PARTIALLY_ACCEPTED` — draft, rejected,
    correction-required and superseded siblings are excluded — plus one more for this
    1094-C itself."
    PRD §3.8: "The sum is `aggregate_return_count`, and `required_channel` becomes
    `ELECTRONIC` when it is at or above the season's `electronic_filing_threshold`,
    otherwise `ANY`."
    PRD §3.8: "A `PAPER` channel against a `required_channel` of `ELECTRONIC` is
    refused with `ERR_ELECTRONIC_FILING_REQUIRED`; a `required_channel` of `ANY`
    accepts either."
    PRD §3.8: "Success moves `DRAFT`-descended state `BUILT` → `TRANSMITTED`, stamps
    `channel`, `transmitted_by_user_id` and `transmitted_at`, and moves every attached
    statement `ATTACHED` → `PENDING_FILING`."

    Design: Difficulty/dual_variant_calc/cumulative_vs_single_submission_return_count
    """
    ctx = _member_with_generated_forms(
        api, 3, season_overrides={"electronic_filing_threshold": 4}
    )
    form_1, form_2, _form_3 = ctx["forms"]

    transmittal = fixtures.open_transmittal(api, ctx["member"]["id"])
    fixtures.attach_forms(api, transmittal["id"], [form_1["id"], form_2["id"]])
    built = fixtures.build_transmittal(api, transmittal["id"])

    assert_transmittal(
        built,
        form_count=2,
        aggregate_return_count=3,
        required_channel="ANY",
    )

    transmitted = fixtures.transmit_transmittal(api, transmittal["id"], "PAPER")
    assert_transmittal(transmitted, status="TRANSMITTED", channel="PAPER")
    assert transmitted["aggregate_return_count"] == 3, (
        "the first submission's two statements plus its own 1094-C give three returns, "
        f"got {transmitted['aggregate_return_count']}"
    )


def test_correction_build_adds_the_transmitted_siblings_frozen_form_count(api):
    """PRD §3.8: "To it are added the frozen `form_count` values of every *other*
    transmittal of the same member sitting in `BUILT`, `TRANSMITTED`, `ACCEPTED`,
    `ACCEPTED_WITH_ERRORS` or `PARTIALLY_ACCEPTED` — draft, rejected,
    correction-required and superseded siblings are excluded — plus one more for this
    1094-C itself."
    PRD §3.8: "The sum is `aggregate_return_count`, and `required_channel` becomes
    `ELECTRONIC` when it is at or above the season's `electronic_filing_threshold`,
    otherwise `ANY`."

    Design: Difficulty/dual_variant_calc/cumulative_vs_single_submission_return_count
    """
    ctx = _member_with_generated_forms(
        api, 3, season_overrides={"electronic_filing_threshold": 4}
    )
    member_id = ctx["member"]["id"]
    form_1, form_2, form_3 = ctx["forms"]

    first = fixtures.open_transmittal(api, member_id)
    fixtures.attach_forms(api, first["id"], [form_1["id"], form_2["id"]])
    fixtures.build_transmittal(api, first["id"])
    fixtures.transmit_transmittal(api, first["id"], "PAPER")

    correction = fixtures.open_transmittal(
        api, member_id, transmission_type="CORRECTION", authoritative_indicator=False
    )
    fixtures.attach_forms(api, correction["id"], [form_3["id"]])
    built_correction = fixtures.build_transmittal(api, correction["id"])

    assert_transmittal(
        built_correction,
        status="BUILT",
        form_count=1,
        aggregate_return_count=4,
        required_channel="ELECTRONIC",
    )

    still_transmitted = fixtures.read_transmittal(api, first["id"])
    assert_transmittal(
        still_transmitted,
        status="TRANSMITTED",
        form_count=2,
        aggregate_return_count=3,
        required_channel="ANY",
    )


# ---------------------------------------------------------------------------
# The replacement round: BUILT → TRANSMITTED → REJECTED → BUILT
# ---------------------------------------------------------------------------
def _rejected_transmittal(api):
    """Carry one statement through build, paper transmission and an agency
    rejection, leaving the transmittal at `REJECTED` with `cycle_number` 1."""
    ctx = _member_with_generated_forms(api, 1)
    form = ctx["forms"][0]
    transmittal = fixtures.open_transmittal(api, ctx["member"]["id"])
    fixtures.attach_forms(api, transmittal["id"], [form["id"]])
    fixtures.build_transmittal(api, transmittal["id"])
    fixtures.transmit_transmittal(api, transmittal["id"], "PAPER")
    rejected = fixtures.record_agency_response(
        api, transmittal["id"], "REJECTED", "AIR-2026-0002"
    )
    ctx["transmittal"] = rejected
    ctx["form"] = form
    return ctx


def test_rebuild_after_agency_rejection_increments_cycle_number(api):
    """PRD §3.8: "It is accepted from `DRAFT`, from `REJECTED` (a replacement round)
    and from `CORRECTION_REQUIRED` (a correction round); it requires at least one
    attached form, an `OPEN` season, and a controlled group in `DETERMINED_ALE` or
    `CORRECTION_OPEN`; and from `CORRECTION_REQUIRED` it additionally requires
    `open_error_count` of zero."
    PRD §3.8: "Building from `REJECTED` or `CORRECTION_REQUIRED` increments
    `cycle_number` by one, and both of those rounds — like starting a correction cycle
    — are refused with `ERR_CORRECTION_CYCLE_LIMIT` once `cycle_number` has reached
    the limit of 3."
    PRD §3.8: "A successful build stamps `built_by_user_id` and `built_at`, freezes
    `monthly_ft_counts` as the twelve reporting-year full-time employee counts of the
    member in calendar order starting with January, moves any *other* transmittal of
    the same member that was sitting at `BUILT` to `SUPERSEDED` (its attached forms
    keep their `ATTACHED` status and their `transmittal_id`), and computes the channel
    requirement."

    Design: Difficulty/non_linear_state_machine/transmittal_rejected_rebuild_increments_cycle_number
    """
    ctx = _rejected_transmittal(api)
    assert_transmittal(ctx["transmittal"], status="REJECTED", cycle_number=1)

    rebuilt = fixtures.build_transmittal(api, ctx["transmittal"]["id"])

    assert_transmittal(
        rebuilt,
        status="BUILT",
        cycle_number=2,
        form_count=1,
        aggregate_return_count=2,
        required_channel="ANY",
        built_by_user_id="preparer-1",
    )


def test_agency_rejection_returns_attached_statements_for_replacement(api):
    """PRD §3.8: "A rejection creates the error rows too but moves every attached
    statement `PENDING_FILING` → `ATTACHED`, so the whole submission can be replaced
    from scratch."
    PRD §3.8: "Success moves `DRAFT`-descended state `BUILT` → `TRANSMITTED`, stamps
    `channel`, `transmitted_by_user_id` and `transmitted_at`, and moves every attached
    statement `ATTACHED` → `PENDING_FILING`."

    Design: Difficulty/non_linear_state_machine/transmittal_rejected_rebuild_increments_cycle_number
    """
    ctx = _rejected_transmittal(api)
    transmittal_id = ctx["transmittal"]["id"]

    after_rejection = fixtures.read_form(api, ctx["form"]["id"])
    assert_form_1095c(
        after_rejection, filing_status="ATTACHED", transmittal_id=transmittal_id
    )

    fixtures.build_transmittal(api, transmittal_id)

    after_rebuild = fixtures.read_form(api, ctx["form"]["id"])
    assert_form_1095c(
        after_rebuild, filing_status="ATTACHED", transmittal_id=transmittal_id
    )
    assert_transmittal(
        fixtures.read_transmittal(api, transmittal_id), form_count=1, status="BUILT"
    )


# ---------------------------------------------------------------------------
# Ladder order: the transmittal-state rung outranks the electronic-channel rung
# ---------------------------------------------------------------------------
def _electronically_transmitted_transmittal(api):
    """One statement plus its 1094-C against an electronic-filing threshold of 2,
    so the build requires `ELECTRONIC`; transmitted electronically by agent-1."""
    ctx = _member_with_generated_forms(
        api, 1, season_overrides={"electronic_filing_threshold": 2}
    )
    transmittal = fixtures.open_transmittal(api, ctx["member"]["id"])
    fixtures.attach_forms(api, transmittal["id"], [ctx["forms"][0]["id"]])
    built = fixtures.build_transmittal(api, transmittal["id"])
    assert_transmittal(built, aggregate_return_count=2, required_channel="ELECTRONIC")
    ctx["transmittal"] = fixtures.transmit_transmittal(
        api, transmittal["id"], "ELECTRONIC"
    )
    return ctx


def test_second_transmission_of_a_transmitted_submission_answers_not_built(api):
    """PRD §2.6: "Every mutating endpoint runs one shared ladder from the top and
    returns the **first** rule it violates; lower numbers win."
    PRD §2.6: "Three consequences are worth naming up front: the request-shape rung
    sits **above** existence, so a body carrying both an out-of-range enum and a
    non-existent id answers `ERR_INVALID_REQUEST` and never a 404; the
    transmittal-state rung at 20 sits **above** the electronic-channel rung at 43, so
    a paper transmission attempt on a submission that is not built answers
    `ERR_TRANSMITTAL_NOT_BUILT`; and segregation of duties at 23 sits **above** every
    temporal window at 33 through 36, because it is a compliance control rather than a
    scheduling rule."
    PRD §2.6: "Transmit requires the transmittal to be `BUILT`, answering
    `ERR_TRANSMITTAL_NOT_BUILT`; submit-response and allocation reset require the
    notice to be `RECOMPUTED`, answering `ERR_NOTICE_NOT_RECOMPUTED` (both 409)."

    Design: Difficulty/priority_pair_validation_conflict/transmittal_state_beats_electronic_channel_rejected
    """
    ctx = _electronically_transmitted_transmittal(api)
    assert_transmittal(
        ctx["transmittal"], status="TRANSMITTED", required_channel="ELECTRONIC"
    )

    response = api.transmit_transmittal(
        ctx["transmittal"]["id"], factories.transmit_payload("PAPER"), AGENT_2
    )

    validate_error(response, ApiErrorId.ERR_TRANSMITTAL_NOT_BUILT, 409)


def test_refused_second_transmission_leaves_the_transmittal_untouched(api):
    """PRD §2.6: "Transmit requires the transmittal to be `BUILT`, answering
    `ERR_TRANSMITTAL_NOT_BUILT`; submit-response and allocation reset require the
    notice to be `RECOMPUTED`, answering `ERR_NOTICE_NOT_RECOMPUTED` (both 409)."
    PRD §3.8: "Success moves `DRAFT`-descended state `BUILT` → `TRANSMITTED`, stamps
    `channel`, `transmitted_by_user_id` and `transmitted_at`, and moves every attached
    statement `ATTACHED` → `PENDING_FILING`."

    Design: Difficulty/priority_pair_validation_conflict/transmittal_state_beats_electronic_channel_rejected
    """
    ctx = _electronically_transmitted_transmittal(api)
    transmittal_id = ctx["transmittal"]["id"]

    response = api.transmit_transmittal(
        transmittal_id, factories.transmit_payload("PAPER"), AGENT_2
    )
    validate_error(response, ApiErrorId.ERR_TRANSMITTAL_NOT_BUILT, 409)

    unchanged = fixtures.read_transmittal(api, transmittal_id)
    assert_transmittal(
        unchanged,
        status="TRANSMITTED",
        required_channel="ELECTRONIC",
        aggregate_return_count=2,
        channel="ELECTRONIC",
        transmitted_by_user_id="agent-1",
    )
    assert_form_1095c(
        fixtures.read_form(api, ctx["forms"][0]["id"]), filing_status="PENDING_FILING"
    )


# ---------------------------------------------------------------------------
# The channel threshold at its exact boundary, and the detach that clears it
# ---------------------------------------------------------------------------
def _built_at_return_count_three(api):
    """Two statements plus the 1094-C give exactly three returns against an
    electronic-filing threshold of three."""
    ctx = _member_with_generated_forms(
        api, 2, season_overrides={"electronic_filing_threshold": 3}
    )
    transmittal = fixtures.open_transmittal(api, ctx["member"]["id"])
    fixtures.attach_forms(
        api, transmittal["id"], [ctx["forms"][0]["id"], ctx["forms"][1]["id"]]
    )
    ctx["transmittal"] = fixtures.build_transmittal(api, transmittal["id"])
    return ctx


def test_paper_transmission_refused_when_return_count_equals_the_threshold(api):
    """PRD §2.9: "Threshold comparisons are inclusive unless stated otherwise: a count
    that exactly equals the applicable-large-employer threshold meets it, hours exactly
    equal to the monthly hours threshold make a month full time, a required
    contribution exactly equal to an affordability threshold is affordable, and an
    aggregate return count exactly equal to the electronic-filing threshold requires
    electronic transmission."
    PRD §3.8: "The sum is `aggregate_return_count`, and `required_channel` becomes
    `ELECTRONIC` when it is at or above the season's `electronic_filing_threshold`,
    otherwise `ANY`."
    PRD §3.8: "A `PAPER` channel against a `required_channel` of `ELECTRONIC` is
    refused with `ERR_ELECTRONIC_FILING_REQUIRED`; a `required_channel` of `ANY`
    accepts either."

    Design: Difficulty/boundary_precision_check/aggregate_return_count_exactly_at_threshold_rejects_paper
    """
    ctx = _built_at_return_count_three(api)

    assert_transmittal(
        ctx["transmittal"],
        form_count=2,
        aggregate_return_count=3,
        required_channel="ELECTRONIC",
    )

    response = api.transmit_transmittal(
        ctx["transmittal"]["id"], factories.transmit_payload("PAPER"), AGENT_1
    )

    validate_error(response, ApiErrorId.ERR_ELECTRONIC_FILING_REQUIRED, 409)


def test_paper_transmission_accepted_once_a_detach_drops_the_return_count(api):
    """PRD §3.8: "Detaching is permitted while the transmittal is `DRAFT` or `BUILT`,
    and detaching from a built transmittal reverts it `BUILT` → `DRAFT` and drops the
    build outputs it can no longer vouch for: `aggregate_return_count` back to 0,
    `required_channel` back to `ANY`, `monthly_ft_counts` back to an empty list and
    `built_at` cleared."
    PRD §3.8: "The sum is `aggregate_return_count`, and `required_channel` becomes
    `ELECTRONIC` when it is at or above the season's `electronic_filing_threshold`,
    otherwise `ANY`."
    PRD §3.8: "A `PAPER` channel against a `required_channel` of `ELECTRONIC` is
    refused with `ERR_ELECTRONIC_FILING_REQUIRED`; a `required_channel` of `ANY`
    accepts either."

    Design: Difficulty/boundary_precision_check/aggregate_return_count_exactly_at_threshold_rejects_paper
    """
    ctx = _built_at_return_count_three(api)
    transmittal_id = ctx["transmittal"]["id"]
    form_1, form_2 = ctx["forms"]

    reverted = fixtures.detach_form(api, transmittal_id, form_2["id"])
    assert_transmittal(
        reverted,
        status="DRAFT",
        form_count=1,
        aggregate_return_count=0,
        required_channel="ANY",
        monthly_ft_counts=[],
    )

    rebuilt = fixtures.build_transmittal(api, transmittal_id)
    assert_transmittal(
        rebuilt,
        status="BUILT",
        form_count=1,
        aggregate_return_count=2,
        required_channel="ANY",
        cycle_number=1,
    )

    transmitted = fixtures.transmit_transmittal(api, transmittal_id, "PAPER")
    assert_transmittal(transmitted, status="TRANSMITTED", channel="PAPER")

    assert_form_1095c(
        fixtures.read_form(api, form_1["id"]), filing_status="PENDING_FILING"
    )
    assert_form_1095c(
        fixtures.read_form(api, form_2["id"]),
        filing_status="NOT_FILED",
        transmittal_id=None,
    )


# ---------------------------------------------------------------------------
# Attach and detach conserve the member's generated statement count
# ---------------------------------------------------------------------------
def _draft_transmittal_with_two_generated_forms(api):
    ctx = _member_with_generated_forms(api, 2)
    ctx["transmittal"] = fixtures.open_transmittal(api, ctx["member"]["id"])
    return ctx


def test_attach_forms_moves_unattached_into_attached_without_changing_generated_count(api):
    """PRD §3.6: "Generation also requires the employee's controlled group to be in
    `DETERMINED_ALE` or `CORRECTION_OPEN`, and it increments the member's
    `generated_form_count` and `unattached_form_count`."
    PRD §3.8: "Each attached form moves `NOT_FILED` → `ATTACHED` and records the
    transmittal in its `transmittal_id`, the transmittal's `form_count` increments, and
    the member's `unattached_form_count` moves into `attached_form_count`; the member's
    `version` advances."

    Design: Difficulty/compensating_invariant/detach_form_conserves_generated_form_count
    """
    ctx = _draft_transmittal_with_two_generated_forms(api)
    member_id = ctx["member"]["id"]
    form_1, form_2 = ctx["forms"]

    before = fixtures.read_member(api, member_id)
    assert_group_member(
        before,
        generated_form_count=2,
        unattached_form_count=2,
        attached_form_count=0,
    )

    attached_transmittal = fixtures.attach_forms(
        api, ctx["transmittal"]["id"], [form_1["id"], form_2["id"]]
    )
    assert_transmittal(attached_transmittal, form_count=2, status="DRAFT")

    after = fixtures.read_member(api, member_id)
    assert_group_member(
        after,
        generated_form_count=2,
        unattached_form_count=0,
        attached_form_count=2,
    )
    assert (
        after["unattached_form_count"] + after["attached_form_count"]
        == after["generated_form_count"]
        == 2
    ), (
        "attaching must move statements between the member's counters without "
        f"changing generated_form_count, got {after!r}"
    )


def test_detach_form_returns_the_statement_and_conserves_generated_count(api):
    """PRD §3.8: "Detaching is the exact compensating action for one `form_id`: the
    form moves `ATTACHED` → `NOT_FILED` with its `transmittal_id` cleared, `form_count`
    decrements, the member's `attached_form_count` moves back into
    `unattached_form_count`, and the member's `version` advances again."
    PRD §3.8: "The conserved quantity across attach and detach is the member's
    `generated_form_count`, which neither operation changes."

    Design: Difficulty/compensating_invariant/detach_form_conserves_generated_form_count
    """
    ctx = _draft_transmittal_with_two_generated_forms(api)
    member_id = ctx["member"]["id"]
    transmittal_id = ctx["transmittal"]["id"]
    form_1, form_2 = ctx["forms"]

    fixtures.attach_forms(api, transmittal_id, [form_1["id"], form_2["id"]])
    detached_transmittal = fixtures.detach_form(api, transmittal_id, form_2["id"])

    assert_transmittal(detached_transmittal, form_count=1, status="DRAFT")

    member = fixtures.read_member(api, member_id)
    assert_group_member(
        member,
        generated_form_count=2,
        unattached_form_count=1,
        attached_form_count=1,
    )
    assert (
        member["unattached_form_count"] + member["attached_form_count"]
        == member["generated_form_count"]
        == 2
    ), (
        "detaching is the compensating action for attaching, so the two form counters "
        f"must still sum to generated_form_count, got {member!r}"
    )

    assert_form_1095c(
        fixtures.read_form(api, form_1["id"]),
        filing_status="ATTACHED",
        transmittal_id=transmittal_id,
    )
    assert_form_1095c(
        fixtures.read_form(api, form_2["id"]),
        filing_status="NOT_FILED",
        transmittal_id=None,
    )
