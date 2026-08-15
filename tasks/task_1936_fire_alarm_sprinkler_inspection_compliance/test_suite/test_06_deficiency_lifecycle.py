"""Deficiency correction loop: deadlines, late fees, rejection cycle,
segregation of duties, waivers, and the one-time extension."""
from test_helpers import (
    ApiErrorId,
    add_days,
    assert_deficiency,
    get_deficiency,
    iso_utc,
    make_fire_marshal_headers,
    parse_date,
    set_clock,
    setup_completed_event,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MARSHAL = TEST_USERS["fire_marshal_headers"]


def _completed_with_deficiency(api, classification="NONCRITICAL", **kwargs):
    """Completed event carrying one deficiency of the given classification."""
    ctx = setup_completed_event(deficiency_classifications=(classification,),
                                **kwargs)
    ctx["deficiency"] = ctx["defs"][0]
    return ctx


class TestCorrectionRejectionCycle:
    def test_reject_reopens_and_conserves_original_deadline(self, api):
        """PRD §3.5: "A marshal who disputes the correction rejects it, returning
        the deficiency from `CORRECTED` to `OPEN`: `corrected_at` is cleared to
        null and late-fee accrual resumes against the original
        `correction_deadline` — no reset is granted."

        Design: Difficulty/non_linear_state_machine/deficiency_correction_rejection_cycle
        """
        ctx = _completed_with_deficiency(api, legal_name="Cycle Test Co")
        d_id = ctx["deficiency"]["id"]
        original_deadline = get_deficiency(ctx["con"], d_id)["correction_deadline"]
        assert original_deadline, "deadline is stamped from the completion date"

        set_clock("2026-08-10T00:00:00Z")
        attested = validate_success(
            api.attest_correction(d_id, ctx["admin"]))
        assert attested["status"] == "CORRECTED"
        assert attested["correction_deadline"] == original_deadline

        rejected = validate_success(api.reject_correction(d_id, MARSHAL))
        assert rejected["status"] == "OPEN"
        assert rejected["corrected_at"] is None, "corrected_at is cleared to null"
        assert rejected["correction_deadline"] == original_deadline, (
            "the deadline is conserved byte-identically across the "
            "attest/reject pair — no reset is granted")

    def test_second_correction_accrues_against_original_deadline(self, api):
        """PRD §3.5: "late-fee accrual resumes against the original
        `correction_deadline` — no reset is granted."
        PRD §3.5: "The number of days late is the days between the relevant date
        — `corrected_at` when a correction is being attested, the current logical
        date during the daily sweep — and the `correction_deadline`, never below
        zero, and capped at thirty days. The fee is those days multiplied by
        20000 cents per day for `CRITICAL` or 5000 cents per day for
        `NONCRITICAL`, an integer-cents product with no rounding."

        Design: Difficulty/non_linear_state_machine/deficiency_correction_rejection_cycle
        """
        ctx = _completed_with_deficiency(api, legal_name="Cycle Test Co")
        d_id = ctx["deficiency"]["id"]
        deadline = parse_date(get_deficiency(ctx["con"], d_id)["correction_deadline"])

        set_clock("2026-08-10T00:00:00Z")
        validate_success(api.attest_correction(d_id, ctx["admin"]))
        validate_success(api.reject_correction(d_id, MARSHAL))

        set_clock("2026-09-07T00:00:00Z")
        re_attested = validate_success(api.attest_correction(d_id, ctx["admin"]))
        assert re_attested["status"] == "CORRECTED"
        days_late = max(0, (parse_date("2026-09-07") - deadline).days)
        expected_fee = min(days_late, 30) * 5000
        assert re_attested["late_fee_cents"] == expected_fee, (
            f"late fee accrues against the original deadline {deadline}: "
            f"{min(days_late, 30)} days x 5000 = {expected_fee}, "
            f"got {re_attested['late_fee_cents']}")


class TestRejectReopenInvariant:
    def test_reject_restores_open_with_null_corrected_at(self, api):
        """PRD §3.5: "A marshal who disputes the correction rejects it, returning
        the deficiency from `CORRECTED` to `OPEN`: `corrected_at` is cleared to
        null and late-fee accrual resumes against the original
        `correction_deadline` — no reset is granted."

        Design: Difficulty/compensating_invariant/deficiency_reject_reopens_with_fee_invariant
        """
        ctx = _completed_with_deficiency(api, legal_name="Invariant Co")
        d_id = ctx["deficiency"]["id"]
        set_clock("2026-08-20T00:00:00Z")
        attested = validate_success(api.attest_correction(d_id, ctx["admin"]))
        deadline_before = attested["correction_deadline"]

        rejected = validate_success(api.reject_correction(d_id, MARSHAL))
        assert_deficiency(rejected)
        assert rejected["status"] == "OPEN"
        assert rejected["corrected_at"] is None
        assert rejected["correction_deadline"] == deadline_before, (
            "correction_deadline is byte-identical to its pre-attest value")

    def test_sweep_resumes_accrual_against_original_deadline(self, api):
        """PRD §3.5: "late-fee accrual resumes against the original
        `correction_deadline` — no reset is granted."
        PRD §3.5: "The sweep keeps `late_fee_cents` current while a deficiency
        stands open past deadline"
        PRD §3.5: "The fee is those days multiplied by 20000 cents per day for
        `CRITICAL` or 5000 cents per day for `NONCRITICAL`, an integer-cents
        product with no rounding."

        Design: Difficulty/compensating_invariant/deficiency_reject_reopens_with_fee_invariant
        """
        ctx = _completed_with_deficiency(api, legal_name="Invariant Co")
        d_id = ctx["deficiency"]["id"]
        deadline = parse_date(get_deficiency(ctx["con"], d_id)["correction_deadline"])

        set_clock("2026-08-20T00:00:00Z")
        validate_success(api.attest_correction(d_id, ctx["admin"]))
        validate_success(api.reject_correction(d_id, MARSHAL))

        # The clock only advances; land strictly past both the attest date and
        # five days beyond the original deadline.
        target = max(parse_date("2026-08-21"), add_days(deadline, 5))
        set_clock(iso_utc(target))
        swept = get_deficiency(ctx["con"], d_id)
        assert swept["status"] == "OPEN"
        expected_fee = min((target - deadline).days, 30) * 5000
        assert swept["late_fee_cents"] == expected_fee, (
            f"accrual resumed against the original deadline {deadline}: "
            f"expected {expected_fee}, got {swept['late_fee_cents']}")


class TestInvalidTransitionsAndWaiver:
    def test_verify_directly_from_open_rejected(self, api):
        """PRD §2.6: "5. **Transition legality** — the target resource must be in
        a state from which the requested transition exists; failure yields
        `ERR_INVALID_STATE`."
        PRD §3.5: "Verification is then a `FireMarshal` action with a hard
        segregation-of-duties rule: the verifying marshal's `X-User-ID` must
        differ from the `X-User-ID` that performed the attestation, else
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/deficiency_invalid_transition_from_open_to_verified
        """
        ctx = _completed_with_deficiency(api, legal_name="Skip Co")
        d_id = ctx["deficiency"]["id"]
        resp = api.verify_deficiency(d_id, MARSHAL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_deficiency(ctx["con"], d_id)
        assert after["status"] == "OPEN", "verify from OPEN fires no side effects"

    def test_critical_deficiency_not_waivable(self, api):
        """PRD §3.5: "Alternatively, a marshal may waive a deficiency directly
        from `OPEN`, but only when `classification` is `NONCRITICAL`; waiving a
        critical finding is refused with `ERR_CRITICAL_NOT_WAIVABLE`."

        Design: Corner/errors/critical_deficiency_not_waivable
        """
        ctx = _completed_with_deficiency(api, classification="CRITICAL",
                                         legal_name="NoWaive Co")
        d_id = ctx["deficiency"]["id"]
        resp = api.waive_deficiency(d_id, MARSHAL)
        validate_error(resp, ApiErrorId.ERR_CRITICAL_NOT_WAIVABLE)
        assert resp.status_code == 422
        after = get_deficiency(ctx["con"], d_id)
        assert after["status"] == "OPEN", "the refused waiver changes nothing"


class TestDeadlineExtension:
    def test_extension_once_then_rejected_and_critical_never(self, api):
        """PRD §3.5: "A marshal may extend a deficiency's deadline by thirty days
        exactly once, and only for an `OPEN`, `NONCRITICAL` deficiency whose
        `extension_used` is still false; any other target — a critical finding,
        a non-open deficiency, or a second extension — is rejected with
        `ERR_DEFICIENCY_NOT_EXTENSIBLE`. A granted extension adds thirty days to
        `correction_deadline` and flips `extension_used` to true."

        Design: Corner/validations/extension_second_time_rejected
        """
        ctx = setup_completed_event(
            deficiency_classifications=("NONCRITICAL", "CRITICAL"),
            legal_name="Extend Co")
        noncrit, crit = ctx["defs"]

        crit_resp = api.extend_deadline(crit["id"], MARSHAL)
        validate_error(crit_resp, ApiErrorId.ERR_DEFICIENCY_NOT_EXTENSIBLE)

        before = parse_date(get_deficiency(ctx["con"], noncrit["id"])
                            ["correction_deadline"])
        extended = validate_success(api.extend_deadline(noncrit["id"], MARSHAL))
        assert extended["extension_used"] is True
        assert parse_date(extended["correction_deadline"]) == add_days(before, 30), (
            "a granted extension adds thirty days to correction_deadline")

        second = api.extend_deadline(noncrit["id"], MARSHAL)
        validate_error(second, ApiErrorId.ERR_DEFICIENCY_NOT_EXTENSIBLE)


class TestLateFeeCap:
    def test_late_fee_caps_at_thirty_days(self, api):
        """PRD §3.5: "The number of days late is the days between the relevant
        date — `corrected_at` when a correction is being attested, the current
        logical date during the daily sweep — and the `correction_deadline`,
        never below zero, and capped at thirty days. The fee is those days
        multiplied by 20000 cents per day for `CRITICAL` or 5000 cents per day
        for `NONCRITICAL`, an integer-cents product with no rounding."

        Design: Corner/calculations/deficiency_late_fee_cap_at_30_days
        """
        ctx = _completed_with_deficiency(api, classification="CRITICAL",
                                         legal_name="Cap Co")
        d_id = ctx["deficiency"]["id"]
        deadline = parse_date(get_deficiency(ctx["con"], d_id)["correction_deadline"])
        # Attest forty days past the deadline: the cap binds at thirty days.
        set_clock(iso_utc(add_days(deadline, 40)))
        attested = validate_success(api.attest_correction(d_id, ctx["admin"]))
        assert attested["status"] == "CORRECTED"
        assert attested["late_fee_cents"] == 600000, (
            f"30-day cap x 20000 = 600000, got {attested['late_fee_cents']}")


class TestSegregationOfDuties:
    def test_verify_by_attesting_actor_rejected_then_other_marshal_ok(self, api):
        """PRD §3.5: "Verification is then a `FireMarshal` action with a hard
        segregation-of-duties rule: the verifying marshal's `X-User-ID` must
        differ from the `X-User-ID` that performed the attestation, else
        `ERR_SEGREGATION_OF_DUTIES`. Verification lands in `VERIFIED`, the
        terminal-accepted state."
        PRD §2.1: "The server may record it — for example, as the verifying or
        attesting actor on a deficiency for segregation-of-duties comparison"

        Design: Corner/rbac/segregation_of_duties_verify_same_actor_rejected
        """
        ctx = _completed_with_deficiency(api, legal_name="SoD Co")
        d_id = ctx["deficiency"]["id"]
        attested = validate_success(api.attest_correction(d_id, ctx["admin"]))
        assert attested["status"] == "CORRECTED"

        # The attestation carried X-User-ID == contractor id; a verify presenting
        # the same identifier collides with the attesting actor.
        same_actor = api.verify_deficiency(
            d_id, make_fire_marshal_headers(ctx["con"]["id"]))
        validate_error(same_actor, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_deficiency(ctx["con"], d_id)
        assert after["status"] == "CORRECTED", "the rejected verify changes nothing"

        other = validate_success(
            api.verify_deficiency(d_id, make_fire_marshal_headers("fm-2")))
        assert other["status"] == "VERIFIED"
