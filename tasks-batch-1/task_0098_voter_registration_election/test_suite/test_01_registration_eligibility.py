"""Registration eligibility, precinct assignment, and capacity.

Covers the approval eligibility gate (citizenship, age, residency, capacity),
the precinct selector's inclusive street range, the NEEDS_REVIEW revision loop,
and the validation-precedence pair that pins ERR_NOT_CITIZEN over ERR_PRECINCT_FULL.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    fixtures,
    factories,
)
from test_helpers.test_users import OFF1, ADMIN

ERR = ApiErrorId


# ---------------------------------------------------------------------------
# Age eligibility — completed-years boundary (Difficulty: boundary_precision_check)
# ---------------------------------------------------------------------------
def test_age_exactly_18_on_election_date_is_eligible(api):
    """PRD §3.9: "A voter whose eighteenth birthday falls exactly on the election
    date is eligible (their month and day equal the election's, so no year is
    subtracted); a voter whose birthday is one day later computes to 17 and is not."

    Design: Difficulty/boundary_precision_check/age_eligibility_exact_18_on_election_date
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"], date_of_birth="2008-11-03T00:00:00Z")
    resp = api.approve_registration(reg["id"], OFF1)
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE", "a voter turning 18 exactly on election_date must be approved"


def test_age_one_day_short_of_18_is_underage(api):
    """PRD §3.9: "A voter whose eighteenth birthday falls exactly on the election
    date is eligible (their month and day equal the election's, so no year is
    subtracted); a voter whose birthday is one day later computes to 17 and is not."
    PRD §3.2: "Age is checked next, using the completed-years rule described in
    §3.9, and must be at least the voting age, or the request is rejected with
    ERR_UNDERAGE."

    Design: Difficulty/boundary_precision_check/age_eligibility_exact_18_on_election_date
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"], date_of_birth="2008-11-04T00:00:00Z")
    resp = api.approve_registration(reg["id"], OFF1)
    validate_error(resp, ERR.ERR_UNDERAGE.value)
    after = validate_success(api.get_registration(reg["id"], OFF1), 200)
    assert after["status"] == "PENDING", "an underage rejection must leave the registration PENDING"


# ---------------------------------------------------------------------------
# Residency street range — inclusive both ends (Difficulty: resource_temporal_overlap)
# ---------------------------------------------------------------------------
def test_residency_upper_boundary_street_number_matches(api):
    """PRD §3.9: "the selector considers the precincts of the registration's
    election that match on county_fips, that cover the voter's street_number
    within their inclusive street_low-through-street_high range, and that are
    currently OPEN."

    Design: Difficulty/resource_temporal_overlap/residency_street_range_inclusive_boundary
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"street_low": 1, "street_high": 999}
    )
    reg = fixtures.create_registration(election["id"], street_number=999)
    data = validate_success(api.approve_registration(reg["id"], OFF1), 200)
    assert data["status"] == "ACTIVE"
    assert data["precinct_id"] == precinct["id"], "street_number==street_high must match (inclusive upper bound)"


def test_residency_above_upper_boundary_no_match(api):
    """PRD §3.9: "If no precinct of the election matches the county-and-street
    filter at all, approval fails with ERR_NO_PRECINCT_MATCH; if precincts match
    the filter but every one of them is FULL, approval fails with ERR_PRECINCT_FULL."

    Design: Difficulty/resource_temporal_overlap/residency_street_range_inclusive_boundary
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"street_low": 1, "street_high": 999}
    )
    reg = fixtures.create_registration(election["id"], street_number=1000)
    validate_error(api.approve_registration(reg["id"], OFF1), ERR.ERR_NO_PRECINCT_MATCH.value)


# ---------------------------------------------------------------------------
# Capacity posture read-then-mutate (Difficulty: combinatorial_formula)
# ---------------------------------------------------------------------------
def test_last_open_slot_approves_then_posture_flips_full(api):
    """PRD §3.1: "a computed capacity_posture, which reads OPEN while assigned_count
    is below max_registrations and FULL once assigned_count reaches or exceeds it."
    PRD §3.2: "Only after a covering precinct is found does capacity apply: the
    selected precinct must be OPEN, failing which the request is rejected with
    ERR_PRECINCT_FULL."

    Design: Difficulty/combinatorial_formula/precinct_capacity_posture_eval_order_then_mutate
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"max_registrations": 1}
    )
    reg = fixtures.create_registration(election["id"])
    data = validate_success(api.approve_registration(reg["id"], OFF1), 200)
    assert data["status"] == "ACTIVE"
    assert data["precinct_id"] == precinct["id"]
    after = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert after["assigned_count"] == 1, "the last OPEN slot must be consumed"
    assert after["capacity_posture"] == "FULL", "posture flips FULL after the increment"


def test_capacity_posture_open_before_last_slot_consumed(api):
    """PRD §3.1: "a computed capacity_posture, which reads OPEN while assigned_count
    is below max_registrations and FULL once assigned_count reaches or exceeds it."

    Design: Difficulty/combinatorial_formula/precinct_capacity_posture_eval_order_then_mutate
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"max_registrations": 2}
    )
    reg = fixtures.create_registration(election["id"])
    fixtures.approve_registration(reg["id"], OFF1)
    after = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert after["assigned_count"] == 1
    assert after["capacity_posture"] == "OPEN", "1 < max_registrations(2) keeps posture OPEN after the increment"


def test_full_precinct_blocks_subsequent_approval(api):
    """PRD §3.2: "Only after a covering precinct is found does capacity apply: the
    selected precinct must be OPEN, failing which the request is rejected with
    ERR_PRECINCT_FULL."

    Design: Corner/errors/error_precinct_full_standalone
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"max_registrations": 1}
    )
    first = fixtures.create_registration(election["id"], national_id="N1", street_number=10)
    fixtures.approve_registration(first["id"], OFF1)
    second = fixtures.create_registration(election["id"], national_id="N2", street_number=20)
    validate_error(api.approve_registration(second["id"], OFF1), ERR.ERR_PRECINCT_FULL.value)
    after = validate_success(api.get_registration(second["id"], OFF1), 200)
    assert after["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Validation precedence — citizenship beats capacity (Difficulty: priority_pair)
# ---------------------------------------------------------------------------
def test_not_citizen_beats_precinct_full(api):
    """PRD §2.9: "Business-constraint checks follow in this order: citizenship
    (ERR_NOT_CITIZEN), then age (ERR_UNDERAGE), then residency match
    (ERR_NO_PRECINCT_MATCH), then whether a referenced registration is active
    (ERR_REGISTRATION_NOT_ACTIVE), then the accept-time cure guard
    (ERR_BALLOT_NOT_CURED), then registration uniqueness (ERR_DUPLICATE_REGISTRATION),
    then the double-vote guard (ERR_ALREADY_VOTED), then the withdraw guard
    (ERR_BALLOT_BLOCKS_WITHDRAW), then the recount precondition
    (ERR_PRECINCT_NOT_TALLIED), then the machine-retire guard (ERR_BACKUP_IN_USE),
    and then precinct capacity (ERR_PRECINCT_FULL)."
    PRD §3.2: "Citizenship is checked first: the is_citizen flag must be true, or
    the request is rejected with ERR_NOT_CITIZEN."

    Design: Difficulty/priority_pair_validation_conflict/not_citizen_beats_precinct_full
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"max_registrations": 1}
    )
    # Fill the only matching precinct.
    first = fixtures.create_registration(election["id"], national_id="N1", street_number=10)
    fixtures.approve_registration(first["id"], OFF1)
    # A non-citizen whose only matching precinct is also FULL.
    second = fixtures.create_registration(
        election["id"], national_id="N2", street_number=20, is_citizen=False
    )
    validate_error(api.approve_registration(second["id"], OFF1), ERR.ERR_NOT_CITIZEN.value)
    after = validate_success(api.get_registration(second["id"], OFF1), 200)
    assert after["status"] == "PENDING"


def test_not_citizen_and_full_precinct_leaves_registration_pending(api):
    """PRD §3.2: "Citizenship is checked first: the is_citizen flag must be true,
    or the request is rejected with ERR_NOT_CITIZEN."
    PRD §2.9: "Business-constraint checks follow in this order: citizenship
    (ERR_NOT_CITIZEN), then age (ERR_UNDERAGE), then residency match
    (ERR_NO_PRECINCT_MATCH) ... and then precinct capacity (ERR_PRECINCT_FULL)."

    Design: Difficulty/priority_pair_validation_conflict/not_citizen_beats_precinct_full
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"max_registrations": 1}
    )
    first = fixtures.create_registration(election["id"], national_id="N1", street_number=10)
    fixtures.approve_registration(first["id"], OFF1)
    # Non-citizen against the now-FULL precinct: citizenship (lower priority number) wins.
    second = fixtures.create_registration(
        election["id"], national_id="N2", street_number=20, is_citizen=False
    )
    validate_error(api.approve_registration(second["id"], OFF1), ERR.ERR_NOT_CITIZEN.value)
    # The full precinct's count is untouched by the rejected approval.
    p = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert p["assigned_count"] == 1


def test_underage_registration_rejected(api):
    """PRD §3.2: "Age is checked next, using the completed-years rule described in
    §3.9, and must be at least the voting age, or the request is rejected with
    ERR_UNDERAGE."

    Design: Corner/validations/underage_registration_rejected
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"], date_of_birth="2008-11-04T00:00:00Z")
    validate_error(api.approve_registration(reg["id"], OFF1), ERR.ERR_UNDERAGE.value)
    after = validate_success(api.get_registration(reg["id"], OFF1), 200)
    assert after["status"] == "PENDING"


def test_no_precinct_match_when_street_out_of_range(api):
    """PRD §3.9: "If no precinct of the election matches the county-and-street
    filter at all, approval fails with ERR_NO_PRECINCT_MATCH; if precincts match
    the filter but every one of them is FULL, approval fails with ERR_PRECINCT_FULL."

    Design: Corner/validations/no_precinct_match_when_street_out_of_range
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"street_low": 1, "street_high": 999}
    )
    reg = fixtures.create_registration(election["id"], street_number=1000)
    validate_error(api.approve_registration(reg["id"], OFF1), ERR.ERR_NO_PRECINCT_MATCH.value)
    after = validate_success(api.get_registration(reg["id"], OFF1), 200)
    assert after["status"] == "PENDING"


# ---------------------------------------------------------------------------
# NEEDS_REVIEW revision loop (Difficulty: non_linear_state_machine)
# ---------------------------------------------------------------------------
def test_needs_review_resubmit_applies_corrected_fields(api):
    """PRD §3.2: "An official may send a PENDING registration to NEEDS_REVIEW and
    may send a NEEDS_REVIEW registration back to PENDING; on that return-to-pending
    resubmit, any corrected county_fips, street_number, or is_citizen value present
    in the payload is applied to the record."

    Design: Difficulty/non_linear_state_machine/voter_registration_needs_review_revision_loop
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"], is_citizen=False)
    validate_success(api.transition_registration(reg["id"], {"target_status": "NEEDS_REVIEW"}, OFF1), 200)
    data = validate_success(
        api.transition_registration(reg["id"], {"target_status": "PENDING", "is_citizen": True}, OFF1), 200
    )
    assert data["status"] == "PENDING", "NEEDS_REVIEW -> PENDING completes the revision loop"
    assert data["is_citizen"] is True, "corrected is_citizen must be applied on resubmit"


def test_pending_to_needs_review_then_back_to_pending_cycle(api):
    """PRD §3.2: "An official may send a PENDING registration to NEEDS_REVIEW and
    may send a NEEDS_REVIEW registration back to PENDING; on that return-to-pending
    resubmit, any corrected county_fips, street_number, or is_citizen value present
    in the payload is applied to the record."

    Design: Difficulty/non_linear_state_machine/voter_registration_needs_review_revision_loop
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"], street_number=10)
    nr = validate_success(api.transition_registration(reg["id"], {"target_status": "NEEDS_REVIEW"}, OFF1), 200)
    assert nr["status"] == "NEEDS_REVIEW"
    back = validate_success(
        api.transition_registration(reg["id"], {"target_status": "PENDING", "street_number": 42}, OFF1), 200
    )
    assert back["status"] == "PENDING"
    assert back["street_number"] == 42, "corrected street_number must be applied on resubmit"


# ---------------------------------------------------------------------------
# Approve-then-withdraw conserves precinct assigned_count (Difficulty: compensating_invariant)
# ---------------------------------------------------------------------------
def test_approve_then_withdraw_conserves_assigned_count(api):
    """PRD §3.2: "A permitted withdrawal is a compensating action: it decrements
    the assigned precinct's assigned_count by one and recomputes that precinct's
    capacity_posture, recomputes the election's total_registered, and increments
    the registration's version."

    Design: Difficulty/compensating_invariant/approve_then_withdraw_conserves_precinct_assigned_count
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"])
    fixtures.approve_registration(reg["id"], OFF1)
    mid = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert mid["assigned_count"] == 1
    validate_success(api.transition_registration(reg["id"], {"target_status": "WITHDRAWN"}, OFF1), 200)
    after = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert after["assigned_count"] == 0, "withdraw must restore assigned_count to its pre-approval value"
    assert after["capacity_posture"] == "OPEN"


def test_withdraw_cascades_precinct_count_and_election_total(api):
    """PRD §3.2: "A permitted withdrawal is a compensating action: it decrements
    the assigned precinct's assigned_count by one and recomputes that precinct's
    capacity_posture, recomputes the election's total_registered, and increments
    the registration's version."

    Design: Difficulty/transitive_cascade/withdraw_cascades_precinct_count_and_election_total
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"max_registrations": 1}
    )
    reg = fixtures.create_registration(election["id"])
    fixtures.approve_registration(reg["id"], OFF1)
    before_e = validate_success(api.get_election(election["id"], ADMIN), 200)
    assert before_e["total_registered"] == 1
    data = validate_success(api.transition_registration(reg["id"], {"target_status": "WITHDRAWN"}, OFF1), 200)
    assert data["status"] == "WITHDRAWN"
    p = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert p["assigned_count"] == 0
    assert p["capacity_posture"] == "OPEN"
    e = validate_success(api.get_election(election["id"], ADMIN), 200)
    assert e["total_registered"] == 0, "withdrawal must re-derive total_registered"


def test_withdraw_releases_full_precinct_back_to_open(api):
    """PRD §3.2: "A permitted withdrawal is a compensating action: it decrements
    the assigned precinct's assigned_count by one and recomputes that precinct's
    capacity_posture, recomputes the election's total_registered, and increments
    the registration's version."

    Design: Difficulty/compensating_invariant/approve_then_withdraw_conserves_precinct_assigned_count
    """
    election, precinct = fixtures.setup_election_with_precinct(
        "REGISTRATION_OPEN", precinct_overrides={"max_registrations": 1}
    )
    reg = fixtures.create_registration(election["id"])
    fixtures.approve_registration(reg["id"], OFF1)
    full = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert full["capacity_posture"] == "FULL"
    validate_success(api.transition_registration(reg["id"], {"target_status": "WITHDRAWN"}, OFF1), 200)
    after = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert after["assigned_count"] == 0, "withdraw conserves assigned_count back to 0"
    assert after["capacity_posture"] == "OPEN", "freed slot flips posture back to OPEN"


def test_withdrawn_registration_reaches_terminal_state(api):
    """PRD §3.2: "Withdrawal applies only to an ACTIVE registration and moves it
    ACTIVE -> WITHDRAWN ... A permitted withdrawal is a compensating action: it
    decrements the assigned precinct's assigned_count by one and recomputes that
    precinct's capacity_posture, recomputes the election's total_registered, and
    increments the registration's version."

    Design: Difficulty/transitive_cascade/withdraw_cascades_precinct_count_and_election_total
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"])
    fixtures.approve_registration(reg["id"], OFF1)
    data = validate_success(api.transition_registration(reg["id"], {"target_status": "WITHDRAWN"}, OFF1), 200)
    assert data["status"] == "WITHDRAWN"
    e = validate_success(api.get_election(election["id"], ADMIN), 200)
    assert e["total_registered"] == 0, "withdrawal re-derives the election's ACTIVE-count denominator"


# ---------------------------------------------------------------------------
# Corner: defaults, duplicate, window, voting-not-open, computed reads
# ---------------------------------------------------------------------------
def test_registration_party_defaults_unaffiliated(api):
    """PRD §3.2: "The party is one of DEMOCRAT, REPUBLICAN, INDEPENDENT, GREEN,
    LIBERTARIAN, or UNAFFILIATED, defaulting to UNAFFILIATED when omitted."

    Design: Corner/entities/registration_party_default_unaffiliated_applied
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    payload = factories.create_registration_payload(election["id"])
    payload.pop("party", None)  # party intentionally omitted
    data = validate_success(api.create_registration(payload, OFF1), 201)
    assert data["party"] == "UNAFFILIATED"
    assert data["status"] == "PENDING"


def test_registration_invalid_party_enum_rejected(api):
    """PRD §3.2: "The party is one of DEMOCRAT, REPUBLICAN, INDEPENDENT, GREEN,
    LIBERTARIAN, or UNAFFILIATED, defaulting to UNAFFILIATED when omitted."
    PRD §2.9: "generic body-shape validation (ERR_INVALID_REQUEST) — required
    fields present, enum values in range, and numeric constraints such as
    max_registrations being at least 1 and street_high being at least street_low."

    Design: Corner/entities/registration_invalid_party_enum_returns_invalid_request
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    payload = factories.create_registration_payload(election["id"], party="WHIG")
    validate_error(api.create_registration(payload, OFF1), ERR.ERR_INVALID_REQUEST.value)


def test_duplicate_registration_same_national_id_rejected(api):
    """PRD §3.2: "if any other registration for the same election shares the same
    national_id and sits in PENDING, NEEDS_REVIEW, or ACTIVE, the create fails
    with ERR_DUPLICATE_REGISTRATION (a previously REJECTED or WITHDRAWN
    registration does not block a fresh one)."

    Design: Corner/validations/duplicate_registration_same_national_id_returns_conflict
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    fixtures.create_registration(election["id"], national_id="N1", first_name="A")
    dup = factories.create_registration_payload(
        election["id"], national_id="N1", first_name="A2", last_name="A2",
        date_of_birth="1991-01-01T00:00:00Z", street_number=11,
    )
    validate_error(api.create_registration(dup, OFF1), ERR.ERR_DUPLICATE_REGISTRATION.value)


def test_approval_after_registration_deadline_window_closed(api):
    """PRD §3.2: "Approval is admissible only while the registration is PENDING,
    the election is in REGISTRATION_OPEN, and the simulated clock is strictly
    before the election's registration_deadline; a clock at or past that deadline
    yields ERR_WINDOW_CLOSED."

    Design: Corner/validations/registration_after_deadline_returns_window_closed
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"])
    fixtures.set_clock("2026-10-01T00:00:00Z")  # == registration_deadline
    validate_error(api.approve_registration(reg["id"], OFF1), ERR.ERR_WINDOW_CLOSED.value)
    after = validate_success(api.get_registration(reg["id"], OFF1), 200)
    assert after["status"] == "PENDING"


def test_open_voting_before_early_voting_start_rejected(api):
    """PRD §3.1: "Opening voting moves it REGISTRATION_OPEN -> VOTING_OPEN, but only
    once the simulated clock has reached or passed early_voting_start; an attempt
    before that instant is refused with ERR_VOTING_NOT_OPEN."

    Design: Corner/state_machines/election_open_voting_before_early_voting_start_returns_voting_not_open
    """
    election = fixtures.create_registration_open_election(clock="2026-09-01T00:00:00Z")
    resp = api.transition_election(election["id"], {"target_status": "VOTING_OPEN"}, ADMIN)
    validate_error(resp, ERR.ERR_VOTING_NOT_OPEN.value)
    after = validate_success(api.get_election(election["id"], ADMIN), 200)
    assert after["status"] == "REGISTRATION_OPEN"


def test_approve_already_active_registration_invalid_state(api):
    """PRD §3.2: "Approval is admissible only while the registration is PENDING,
    the election is in REGISTRATION_OPEN, and the simulated clock is strictly
    before the election's registration_deadline."
    PRD §2.9: "then whether the target resource is in a legal state for the
    requested transition (ERR_INVALID_STATE)."

    Design: Corner/state_machines/approve_already_active_registration_returns_invalid_state
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"])
    fixtures.approve_registration(reg["id"], OFF1)
    resp = api.approve_registration(reg["id"], OFF1)
    validate_error(resp, ERR.ERR_INVALID_STATE.value)
    p = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert p["assigned_count"] == 1, "a rejected second approval must not double-increment the precinct"


def test_total_registered_recomputed_on_approve(api):
    """PRD §3.8: "The denominator throughout is total_registered, the count of the
    election's registrations whose status is ACTIVE."

    Design: Corner/endpoints/registration_recompute_total_registered_on_approve
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    before = validate_success(api.get_election(election["id"], ADMIN), 200)
    assert before["total_registered"] == 0
    reg = fixtures.create_registration(election["id"])
    fixtures.approve_registration(reg["id"], OFF1)
    after = validate_success(api.get_election(election["id"], ADMIN), 200)
    assert after["total_registered"] == 1


def test_assigned_count_immediately_visible_after_approve(api):
    """PRD §2.5: "The governing rule is that no derived field is ever left
    inconsistent with the rows it summarizes once an operation completes."
    PRD §3.2: "increments that precinct's assigned_count by one and recomputes
    its capacity_posture."

    Design: Corner/consistency_model/immediate_visibility_of_precinct_count_after_approve
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"])
    fixtures.approve_registration(reg["id"], OFF1)
    p = validate_success(api.get_precinct(precinct["id"], OFF1), 200)
    assert p["assigned_count"] == 1
    assert p["capacity_posture"] == "OPEN"
