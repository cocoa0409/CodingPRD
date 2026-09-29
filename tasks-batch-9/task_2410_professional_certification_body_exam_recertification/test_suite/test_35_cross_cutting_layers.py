"""Three cross-cutting layers at once: the seat ledger's OCC token, the per-programme
statistics flag, and the strictly-after comparison that drives the lapse sweep."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success

IDENTICAL_PRETEST_BATCH = {
    "is_pretest": True,
    "response_count": 40,
    "correct_count": 24,
    "upper_n": 10,
    "upper_correct": 9,
    "lower_n": 10,
    "lower_correct": 3,
}


def _two_registrations_contending_for_one_session(api):
    """Candidate A holds a seat; candidate B is approved and unscheduled. Returns the
    session token observed before A's claim moved it."""
    state = fx.pipeline_through_approved_application(api)
    session = fx.create_test_center_session(api)
    observed_version = session["version"]
    seat_a = fx.create_registration(api, state.application_id, state.form_id)
    fx.schedule_seat(api, seat_a["id"], session["id"], observed_version)

    rival = fx.second_candidate_application(api, state)
    seat_b = fx.create_registration(api, rival["application"]["id"], state.form_id)
    assert seat_b["seat_status"] == "UNSCHEDULED"
    return state, session, observed_version, seat_a, seat_b


def _a_pooled_and_a_defaulted_programme(api):
    """CPX names POOLED explicitly; CPY omits the field and takes the declared default.
    Each carries one APPROVED item in D1."""
    pooled = fx.active_program(api)
    assert pooled["psychometric_stat_basis"] == "POOLED"
    pooled_item = fx.approved_item(api, pooled["id"], stem="CPX approved item")

    body = f.create_program_payload(name="Certified Practitioner Y", credential_code="CPY")
    body.pop("psychometric_stat_basis")
    created = validate_success(api.create_program(body, fx.PROGRAM_ADMIN), 201)
    validate_success(api.activate_program(created["id"], f.activate_program_payload(),
                                          fx.PROGRAM_ADMIN), 200)
    defaulted = fx.read_program(api, created["id"])
    defaulted_item = fx.approved_item(api, defaulted["id"], stem="CPY approved item")

    return (pooled, pooled_item), (defaulted, defaulted_item)


def _a_credential_at_its_grace_date(api):
    """An untended cycle whose grace ends on 2027-11-08, with the clock standing exactly
    there."""
    state = fx.pipeline_through_certificant(api)
    cycle = fx.read_cycle(api, state.cycle_id)
    assert str(cycle["ends_on"]).startswith("2027-08-10")
    assert str(cycle["grace_ends_on"]).startswith("2027-11-08")
    assert cycle["status"] == "OPEN"
    fx.set_clock(api, "2027-11-08T00:00:00Z")
    return state


class TestSeatSchedulingUnderContention:
    """The session's version is the seat ledger's token, and a rival's claim invalidates it."""

    def test_the_token_a_rival_seat_consumed_is_refused_though_four_seats_remain(self, api):
        """Capacity is not the objection — one of five seats is taken — so the refusal is the
        stale view of the ledger, and it neither seats candidate B nor moves the session.

        PRD §2.5: "Claiming a seat — `POST /exam-registrations/{id}/schedule` — requires
        `expected_session_version` carrying the client's last observed `version` of the target
        `ExamSession`. If the session's current `version` differs, the claim is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        PRD §2.5: "Seat claims from different registrations are all individually legitimate, so
        the remaining-capacity figure the client based its choice on is precisely the thing
        that can have moved underneath it; the stale version is the only deterministic signal
        that the client's view of the session is out of date."

        Design: Corner/cross_cutting_complexity_layers/seat_scheduling_refuses_the_session_version_that_a_rival_seat_already_consumed
        """
        _state, session, observed_version, _seat_a, seat_b = \
            _two_registrations_contending_for_one_session(api)

        refused = api.schedule_seat(
            seat_b["id"], f.schedule_seat_payload(session["id"], observed_version),
            fx.EXAM_OPERATIONS)

        error = validate_error(refused, ApiErrorId.ERR_STALE_VERSION.value, 412)
        assert error["error_id"] != ApiErrorId.ERR_SESSION_FULL.value
        assert fx.read_registration(api, seat_b["id"])["seat_status"] == "UNSCHEDULED"
        held = fx.read_session(api, session["id"])
        assert held["seats_reserved"] == 1
        assert held["seat_capacity"] == 5
        assert held["version"] == observed_version + 1

    def test_the_re_read_version_seats_the_rival_without_disturbing_the_incumbent(self, api):
        """Reading the session again yields the token the accepted claim left, and using it
        reserves the second seat, bumps the version exactly once more and leaves candidate A's
        seat where it was.

        PRD §3.7: "`seats_reserved` is the number of exam registrations pointing at the session
        whose `seat_status` is `SCHEDULED`, `CHECKED_IN`, or `COMPLETED`; the `UNSCHEDULED`,
        `NO_SHOW`, and `CANCELLED` states all release the seat."

        PRD §3.7: "The session's `status` is `CLOSED` when the logical clock has reached or
        passed `starts_at`; otherwise it is `FULL` when `seats_reserved` is greater than or
        equal to `seat_capacity`; otherwise it is `OPEN`."

        Design: Corner/cross_cutting_complexity_layers/seat_scheduling_refuses_the_session_version_that_a_rival_seat_already_consumed
        """
        _state, session, observed_version, seat_a, seat_b = \
            _two_registrations_contending_for_one_session(api)
        api.schedule_seat(seat_b["id"], f.schedule_seat_payload(session["id"],
                                                               observed_version),
                          fx.EXAM_OPERATIONS)
        current_version = fx.read_session(api, session["id"])["version"]

        scheduled = validate_success(api.schedule_seat(
            seat_b["id"], f.schedule_seat_payload(session["id"], current_version),
            fx.EXAM_OPERATIONS), 200)

        assert scheduled["seat_status"] == "SCHEDULED"
        assert scheduled["session_id"] == session["id"]

        settled = fx.read_session(api, session["id"])
        assert settled["seats_reserved"] == 2
        assert settled["status"] == "OPEN"
        assert settled["version"] == current_version + 1
        ax.assert_seat_ledger_within_bounds(settled)
        assert fx.read_registration(api, seat_a["id"])["seat_status"] == "SCHEDULED"


class TestPsychometricBasisFlagChangesWhatOneBatchProves:
    """The same forty responses promote an item under POOLED and prove nothing by default."""

    def test_the_pooled_programme_computes_both_statistics_and_promotes_the_item(self, api):
        """Merging the pretest pool in carries the item over the thirty-response floor, and the
        unflagged verdict promotes it and completes its programme's blueprint.

        PRD §3.3: "Under the `POOLED` basis, each working total is the sum of the corresponding
        pretest and operational accumulators"

        PRD §3.3: "From `PRETEST`, once `stat_basis_applied` is no longer `INSUFFICIENT_DATA`,
        one of two mutually exclusive outcomes follows: a null `flag_reason` moves the item
        `PRETEST → OPERATIONAL`, while a non-null `flag_reason` moves it `PRETEST → RETIRED`"

        PRD §3.3: "A `PRETEST → OPERATIONAL` or `FLAGGED → OPERATIONAL` move increases the
        program's `operational_item_count` by 1 and then recomputes `deficient_domain_codes`
        and `blueprint_posture`, which can flip the program `DEFICIENT → COMPLETE`."

        Design: Corner/cross_cutting_complexity_layers/psychometric_basis_flag_defaults_to_operational_only_and_changes_what_a_pretest_batch_proves
        """
        (pooled, pooled_item), _defaulted = _a_pooled_and_a_defaulted_programme(api)

        ingested = validate_success(api.ingest_response_batch(
            pooled_item["id"], IDENTICAL_PRETEST_BATCH, fx.PSYCHOMETRICIAN), 200)

        assert ingested["stat_basis_applied"] == "POOLED"
        assert float(ingested["p_value"]) == pytest.approx(0.6000, abs=0.00001)
        assert float(ingested["discrimination_index"]) == pytest.approx(0.6000, abs=0.00001)
        assert ingested["flag_reason"] is None
        assert ingested["status"] == "OPERATIONAL"
        ax.assert_item_stat_precision(ingested["p_value"])
        ax.assert_item_stat_precision(ingested["discrimination_index"])

        program = fx.read_program(api, pooled["id"])
        assert program["operational_item_count"] == 1
        assert program["deficient_domain_codes"] == []
        assert program["blueprint_posture"] == "COMPLETE"

    def test_the_defaulted_programme_withholds_both_statistics_from_the_same_batch(self, api):
        """CPY never named the flag, so the operational pool it reads still holds zero
        responses: the statistics are withheld, the item stays in pretest and the blueprint
        stays deficient.

        PRD §3.1: "Psychometric behaviour is set by `psychometric_stat_basis`, which is either
        `POOLED` or `OPERATIONAL_ONLY` and defaults to `OPERATIONAL_ONLY`"

        PRD §3.3: "Under the default `OPERATIONAL_ONLY` basis, the working totals are exactly
        the six operational accumulators"

        PRD §3.3: "If the working response total is strictly less than the program's
        `min_responses_for_stats`, or the upper-group size is zero, or the lower-group size is
        zero, then `stat_basis_applied` is set to `INSUFFICIENT_DATA` and both `p_value` and
        `discrimination_index` are set to null"

        Design: Corner/cross_cutting_complexity_layers/psychometric_basis_flag_defaults_to_operational_only_and_changes_what_a_pretest_batch_proves
        """
        _pooled, (defaulted, defaulted_item) = _a_pooled_and_a_defaulted_programme(api)
        assert defaulted["psychometric_stat_basis"] == "OPERATIONAL_ONLY"
        assert defaulted["min_responses_for_stats"] == 30

        ingested = validate_success(api.ingest_response_batch(
            defaulted_item["id"], IDENTICAL_PRETEST_BATCH, fx.PSYCHOMETRICIAN), 200)

        assert ingested["stat_basis_applied"] == "INSUFFICIENT_DATA"
        assert ingested["p_value"] is None
        assert ingested["discrimination_index"] is None
        assert ingested["flag_reason"] is None
        assert ingested["status"] == "PRETEST"
        assert ingested["pretest_response_count"] == 40
        assert ingested["operational_response_count"] == 0

        program = fx.read_program(api, defaulted["id"])
        assert program["operational_item_count"] == 0
        assert program["deficient_domain_codes"] == ["D1"]
        assert program["blueprint_posture"] == "DEFICIENT"
        ax.assert_blueprint_posture_agrees_with_counts(program)


class TestTheLapseSweepIsStrictlyAfterTheGraceDate:
    """On the grace date itself nothing lapses; one day later everything does."""

    def test_a_run_on_the_grace_date_lapses_nothing_yet_still_expires_the_eligibility(
            self, api):
        """The cycle comparison is strict, so step three finds no candidate while step two
        fires independently on an eligibility that passed in August.

        PRD §3.13: "**Step three — cycles.** Every cycle whose `status` is `OPEN` and whose
        `grace_ends_on` the logical clock is strictly past moves to `LAPSED`, has its
        `reinstatement_fee_cents` assessed as described in §3.11, and drags its owning
        certificant `ACTIVE → EXPIRED` with `publication_status` recomputed to `WITHHELD`."

        PRD §3.11: "`carryover_credits_out` is the surplus computed at close, `path` is `CEU`
        or `RE_EXAM`, and `reinstatement_fee_cents` is null unless the cycle is `LAPSED`."

        Design: Corner/cross_cutting_complexity_layers/the_ops_run_lapses_a_cycle_only_once_the_clock_is_strictly_past_the_grace_date
        """
        state = _a_credential_at_its_grace_date(api)

        report = fx.run_maintenance(api)

        assert report["lapsed_cycle_ids"] == []
        assert report["expired_certificant_ids"] == []
        assert report["expired_application_ids"] == [state.application_id]
        assert report["no_show_registration_ids"] == []
        assert report["reactivated_certificant_ids"] == []

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["status"] == "OPEN"
        assert cycle["reinstatement_fee_cents"] is None
        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "ACTIVE"
        assert certificant["publication_status"] == "PUBLISHED"

    def test_one_day_past_the_grace_date_lapses_the_cycle_and_hides_the_registry_entry(
            self, api):
        """A single day late assesses 250 cents of surcharge on the 25000 base, takes the two
        percent tier on the 25250 subtotal and totals 25755; the holder expires, the entry is
        withheld and the public lookup can no longer see it.

        PRD §3.11: "First take the whole days elapsed between `grace_ends_on` and the current
        date — at least one by construction — and compute the late surcharge as 250 cents per
        day late, capped at 30000 cents"

        PRD §3.11: "Then select the administrative rate from the subtotal: 2 percent when the
        subtotal is at most 30000 cents, 5 percent when it is above 30000 and at most 45000
        cents, and 8 percent when it is above 45000 cents."

        PRD §3.10: "Suppression is deliberately indistinguishable from non-existence: when the
        matched certificant's `publication_status` is `WITHHELD` or `REMOVED`, the verification
        answers `ERR_CERTIFICANT_NOT_FOUND` rather than revealing that a suppressed record
        exists."

        Design: Corner/cross_cutting_complexity_layers/the_ops_run_lapses_a_cycle_only_once_the_clock_is_strictly_past_the_grace_date
        """
        state = _a_credential_at_its_grace_date(api)
        fx.run_maintenance(api)
        fx.set_clock(api, "2027-11-09T00:00:00Z")

        report = fx.run_maintenance(api)

        assert report["lapsed_cycle_ids"] == [state.cycle_id]
        assert report["expired_certificant_ids"] == [state.certificant_id]
        assert report["expired_application_ids"] == []
        assert report["no_show_registration_ids"] == []
        assert report["reactivated_certificant_ids"] == []

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["status"] == "LAPSED"
        assert cycle["reinstatement_fee_cents"] == 25755
        ax.assert_integer_cents(cycle["reinstatement_fee_cents"])

        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "EXPIRED"
        assert certificant["publication_status"] == "WITHHELD"
        ax.assert_publication_status_agrees_with_status(certificant)

        hidden = api.verify_registry({"certificate_number": state.certificate_number})
        validate_error(hidden, ApiErrorId.ERR_CERTIFICANT_NOT_FOUND.value, 404)
