"""Requests that break two rules at once must report the earlier-numbered rule."""

from test_helpers import (
    ApiErrorId,
    agreement_version,
    create_interim_extension,
    create_interim_extension_payload,
    read_agreement,
    read_election,
    read_extensions,
    read_station,
    set_clock,
    setup_draft_election,
    setup_executed_agreement,
    validate_error,
    withdraw_election_payload,
)


def _draft_election_past_the_deadline():
    ctx = setup_draft_election()
    assert ctx["election"]["status"] == "DRAFT"
    set_clock("2026-10-02T00:00:00Z")
    return ctx


def test_withdrawing_a_draft_election_after_the_deadline_reports_the_state_rule(api):
    """State (409) outranks the temporal window (422) on a withdrawal.

    PRD §2.8: "Election is withdrawable, meaning its status is `NEGOTIATING` or
    `ELECTION_EFFECTIVE` - `ERR_ELECTION_NOT_WITHDRAWABLE`. Applies to withdrawing an
    election."

    Design: Difficulty/priority_pair_validation_conflict/withdraw_draft_election_after_deadline_state_beats_temporal
    """
    ctx = _draft_election_past_the_deadline()

    response = api.withdraw_election(
        ctx["election"]["id"],
        withdraw_election_payload(withdrawal_reason="Station group reconsidered the cycle"),
        ctx["negotiator_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_ELECTION_NOT_WITHDRAWABLE.value, 409)

    assert error["error_id"] != ApiErrorId.ERR_ELECTION_WINDOW_CLOSED.value


def test_the_refused_withdrawal_leaves_the_election_and_its_counter_untouched(api):
    """Nothing moves on a rejected withdrawal, not even the filed-election counter.

    PRD §2.9: "`Station.filed_election_count` counts that station's elections in
    status `NEGOTIATING`, `ELECTION_EFFECTIVE` or `CONSENT_GRANTED`."

    Design: Difficulty/priority_pair_validation_conflict/withdraw_draft_election_after_deadline_state_beats_temporal
    """
    ctx = _draft_election_past_the_deadline()

    validate_error(
        api.withdraw_election(
            ctx["election"]["id"],
            withdraw_election_payload(),
            ctx["negotiator_headers"],
        ),
        ApiErrorId.ERR_ELECTION_NOT_WITHDRAWABLE.value,
        409,
    )

    election = read_election(ctx["election"]["id"])
    assert election["status"] == "DRAFT"
    assert election["withdrawal_reason"] is None
    assert election["filed_at_utc"] is None
    assert read_station(ctx["station"]["id"])["filed_election_count"] == 0


def _executed_agreement_with_a_sixty_day_extension():
    ctx = setup_executed_agreement()
    ctx["extension"] = create_interim_extension(
        ctx["agreement"]["id"],
        ctx["station"]["id"],
        extension_days=60,
        extension_start_utc="2030-01-01T00:00:00Z",
        extension_rate_basis="PRIOR_RATE",
    )
    return ctx


def test_overlapping_and_over_budget_extension_reports_the_overlap(api):
    """Constraint (priority 32) outranks the fiscal budget check (priority 34).

    PRD §2.8: "The extension window does not overlap an existing one -
    `ERR_EXTENSION_WINDOW_OVERLAP`. Applies to creating an interim extension."

    Design: Difficulty/priority_pair_validation_conflict/extension_overlap_and_over_budget_constraint_beats_fiscal
    """
    ctx = _executed_agreement_with_a_sixty_day_extension()

    response = api.create_interim_extension(
        ctx["agreement"]["id"],
        create_interim_extension_payload(
            agreement_version(ctx["agreement"]["id"]),
            extension_days=45,
            extension_start_utc="2030-02-01T00:00:00Z",
            extension_rate_basis="PRIOR_RATE",
        ),
        ctx["negotiator_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_EXTENSION_WINDOW_OVERLAP.value, 422)

    assert error["error_id"] != ApiErrorId.ERR_EXTENSION_BUDGET_EXCEEDED.value


def test_the_refused_extension_draws_no_days_and_leaves_the_agreement_version(api):
    """A rejected create neither consumes budget nor bumps the parent version.

    PRD §3.8: "`consumed_extension_days` on the agreement is the sum of
    `extension_days` over that agreement's extensions in status `ACTIVE` or `LAPSED`,
    and the sum of that figure plus the newly requested `extension_days` may not
    exceed 90 days - a full quarter of interim carriage across the life of the
    agreement."

    Design: Difficulty/priority_pair_validation_conflict/extension_overlap_and_over_budget_constraint_beats_fiscal
    """
    ctx = _executed_agreement_with_a_sixty_day_extension()
    version_before = agreement_version(ctx["agreement"]["id"])

    validate_error(
        api.create_interim_extension(
            ctx["agreement"]["id"],
            create_interim_extension_payload(
                version_before,
                extension_days=45,
                extension_start_utc="2030-02-01T00:00:00Z",
                extension_rate_basis="PRIOR_RATE",
            ),
            ctx["negotiator_headers"],
        ),
        ApiErrorId.ERR_EXTENSION_WINDOW_OVERLAP.value,
        422,
    )

    extensions = read_extensions(ctx["agreement"]["id"])
    assert len(extensions) == 1
    assert extensions[0]["extension_end_utc"] == "2030-03-02T00:00:00Z"
    assert extensions[0]["effective_rate_per_sub_cents"] == 220
    assert extensions[0]["status"] == "ACTIVE"

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["consumed_extension_days"] == 60
    assert agreement["version"] == version_before
