"""Campaign briefs, pitching, counters, and slot allocation (PRD §3.2, §3.3)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    accept_pitch,
    assert_brief,
    assert_pitch,
    brand_accept_terms,
    create_brief_payload,
    create_pitch_payload,
    creator_accept_terms,
    get_brief,
    make_accepted_deal,
    make_active_creator,
    make_brand,
    make_creator,
    make_draft_brief,
    make_open_brief,
    make_pitch,
    propose_terms,
    set_clock,
    shortlist_pitch,
    validate_error,
    validate_success,
)

TM = TEST_USERS["talent_manager_headers"]
BM = TEST_USERS["brand_manager_headers"]


class TestBriefCreation:
    def test_brief_defaults_applied_on_create(self, api):
        """PRD §3.2: "an optional `whitelisting_required` flag defaulting to
        false; an optional `revision_rounds_included` defaulting to two"
        PRD §3.2: "A new brief opens in `DRAFT`."
        PRD §3.2: "The `slots_committed` counter tracks how many of the
        brief's pitches are in `ACCEPTED` with a deal that has not been
        `TERMINATED`"

        Design: Corner/entities/brief_defaults_applied_on_create
        """
        brand = make_brand(name="BD", industry="CPG")
        payload = create_brief_payload(brand["id"], title="D")
        payload.pop("whitelisting_required")
        payload.pop("revision_rounds_included")
        brief = validate_success(api.create_brief(payload, BM), 201)
        assert_brief(brief)
        assert brief["whitelisting_required"] is False
        assert brief["revision_rounds_included"] == 2
        assert brief["status"] == "DRAFT"
        assert brief["slots_committed"] == 0

    def test_brief_get_not_found_returns_404(self, api):
        """PRD §2.8: "Existence: path resources exist, validated left to
        right (else `ERR_NOT_FOUND`)."

        Design: Corner/entities/brief_get_not_found_returns_404
        """
        res = api.get_brief(NON_EXISTENT_UUID, BM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_brief_create_suspended_brand_rejected(self, api):
        """PRD §3.2: "Brief creation is refused with `ERR_BRAND_SUSPENDED`
        when the owning brand is not `ACTIVE`."
        PRD §3.2: "A brand account opens in `ACTIVE` standing and can later
        be moved to `SUSPENDED` and back through a brand update, which may
        also set `credit_hold`."

        Design: Corner/validations/brief_create_suspended_brand_rejected
        """
        brand = make_brand(name="BV3")
        validate_success(api.patch_brand(brand["id"], {"status": "SUSPENDED"}, BM))
        res = api.create_brief(create_brief_payload(brand["id"]), BM)
        validate_error(res, ApiErrorId.ERR_BRAND_SUSPENDED, 422)


class TestPitchCreation:
    def test_pitch_before_submission_window_rejected(self, api):
        """PRD §3.3: "next the submission window — the logical clock must
        read at or after `submission_window_start` and at or before
        `submission_window_end`, both bounds inclusive, else
        `ERR_SUBMISSION_WINDOW_CLOSED`"
        PRD §2.5: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z"

        Design: Corner/validations/pitch_before_submission_window_rejected
        """
        creator = make_active_creator(handle="cv1")
        brand = make_brand(name="BV1")
        brief_ns = make_open_brief(
            brand["id"], submission_window_start="2026-08-10T00:00:00Z",
            submission_window_end="2026-08-31T23:59:59Z",
        )
        res = api.create_pitch(
            brief_ns.brief["id"],
            create_pitch_payload(creator["id"], brief_ns.version,
                                 proposed_fee_cents=90000),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED, 422)
        brief = validate_success(api.get_brief(brief_ns.brief["id"], BM))
        assert brief["status"] == "OPEN", (
            "the expiry sweep only closes briefs past their window end; "
            "a not-yet-open window leaves the brief OPEN"
        )

    def test_pitch_requirements_exact_boundary(self, api):
        """PRD §3.3: "the creator's `followers` must be at least the brief's
        `min_followers` and the creator's `engagement_rate_bps` at least the
        brief's `min_engagement_bps`, with exactly meeting a threshold
        qualifying, else `ERR_PITCH_REQUIREMENTS_NOT_MET`"

        Design: Corner/validations/pitch_requirements_exact_boundary
        """
        low = make_active_creator(handle="cv2", followers=49999,
                                  engagement_rate_bps=250)
        exact = make_active_creator(handle="cv3", followers=50000,
                                    engagement_rate_bps=250)
        brand = make_brand(name="BV2")
        brief_ns = make_open_brief(
            brand["id"], min_followers=50000, min_engagement_bps=250,
            slots_total=2,
        )
        res_low = api.create_pitch(
            brief_ns.brief["id"],
            create_pitch_payload(low["id"], brief_ns.version,
                                 proposed_fee_cents=90000),
            TM,
        )
        validate_error(res_low, ApiErrorId.ERR_PITCH_REQUIREMENTS_NOT_MET, 422)

        pitch = make_pitch(brief_ns.brief["id"], exact["id"],
                           proposed_fee_cents=90000)
        assert_pitch(pitch)
        assert pitch["status"] == "SUBMITTED", (
            "exactly meeting both thresholds qualifies"
        )

    def test_pitch_requires_active_creator(self, api):
        """PRD §3.3: "and finally the creator must currently be `ACTIVE`,
        else `ERR_CREATOR_NOT_ACTIVE`."

        Design: Corner/validations/pitch_requires_active_creator
        """
        creator = make_creator(handle="cv12")
        validate_success(
            api.transition_creator(creator["id"], {"to_state": "SCREENING"}, TM)
        )
        brand = make_brand(name="BV12")
        brief_ns = make_open_brief(brand["id"])
        res = api.create_pitch(
            brief_ns.brief["id"],
            create_pitch_payload(creator["id"], brief_ns.version,
                                 proposed_fee_cents=90000),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_CREATOR_NOT_ACTIVE, 422)

    def test_pitch_repitch_supersedes_prior(self, api):
        """PRD §3.3: "Pitch creation mutates the brief as well as creating
        the pitch: the brief's `version` advances by one, and if the same
        creator already holds a `SUBMITTED` pitch on this brief, that prior
        pitch auto-transitions to `SUPERSEDED` with its
        `superseded_by_pitch_id` pointing at the new pitch and its own
        `version` advancing."

        Design: Corner/entities/pitch_repitch_supersedes_prior
        """
        creator = make_active_creator(handle="ce3")
        brand = make_brand(name="BE")
        brief_ns = make_open_brief(brand["id"], usage_rights_days=30)
        p1 = make_pitch(brief_ns.brief["id"], creator["id"],
                        proposed_fee_cents=90000, concept_note="v1",
                        expected_brief_version=brief_ns.version)
        p2 = make_pitch(brief_ns.brief["id"], creator["id"],
                        proposed_fee_cents=95000, concept_note="v2")
        prior = validate_success(api.get_pitch(p1["id"], TM))
        assert prior["status"] == "SUPERSEDED"
        assert prior["superseded_by_pitch_id"] == p2["id"]
        assert p2["status"] == "SUBMITTED"
        assert p2["proposed_fee_cents"] == 95000

    def test_pitch_create_stale_brief_version_rejected(self, api):
        """PRD §2.7: "Creating a pitch against a brief requires
        `expected_brief_version`, carrying the brief's current `version` as
        last observed by the caller. ... A mismatch with the brief's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.3: "Pitch creation mutates the brief as well as creating the
        pitch: the brief's `version` advances by one"

        Design: Corner/cross_cutting_layers/pitch_create_stale_brief_version_rejected
        """
        c1 = make_active_creator(handle="cl1")
        c2 = make_active_creator(handle="cl2")
        brand = make_brand(name="BL1")
        brief_ns = make_open_brief(brand["id"], slots_total=2,
                                   usage_rights_days=30)
        p1 = make_pitch(brief_ns.brief["id"], c1["id"],
                        proposed_fee_cents=90000, concept_note="a",
                        expected_brief_version=brief_ns.version)
        # Second writer still holds the pre-P1 brief version.
        res = api.create_pitch(
            brief_ns.brief["id"],
            create_pitch_payload(c2["id"], brief_ns.version,
                                 proposed_fee_cents=90000, concept_note="b"),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)
        p1_after = validate_success(api.get_pitch(p1["id"], TM))
        assert p1_after["status"] == "SUBMITTED", (
            "the stale write left the first pitch unharmed"
        )


class TestPitchLifecycle:
    def test_pitch_terminal_lockdown_after_reject(self, api):
        """PRD §2.9: "Triggering an action from a terminal state is rejected
        with `ERR_ALREADY_TERMINAL` (HTTP 409)"
        PRD §2.9: "`ACCEPTED`, `REJECTED`, `WITHDRAWN`, and `SUPERSEDED` for
        a Pitch"

        Design: Corner/state_machines/pitch_terminal_lockdown_after_reject
        """
        creator = make_active_creator(handle="cs1")
        brand = make_brand(name="BS1")
        brief_ns = make_open_brief(brand["id"], usage_rights_days=30)
        pitch = make_pitch(brief_ns.brief["id"], creator["id"],
                           proposed_fee_cents=90000,
                           expected_brief_version=brief_ns.version)
        shortlist_pitch(pitch["id"])
        rejected = validate_success(
            api.pitch_brand_action(pitch["id"], {"action": "REJECT"}, BM)
        )
        assert rejected["status"] == "REJECTED"
        res = api.pitch_brand_action(pitch["id"], {"action": "SHORTLIST"}, BM)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        after = validate_success(api.get_pitch(pitch["id"], TM))
        assert after["status"] == "REJECTED"

    def test_pitch_negotiation_round_cap(self, api):
        """PRD §3.3: "Countering, carrying `counter_fee_cents`, moves
        `SHORTLISTED` → `COUNTERED`: the pitch's `proposed_fee_cents` is
        overwritten with the counter value and `negotiation_rounds`
        increments; a counter attempted after the pitch has consumed three
        negotiation rounds is rejected with
        `ERR_NEGOTIATION_LIMIT_EXCEEDED`."
        PRD §3.3: "the same three-round cap and the same
        `ERR_NEGOTIATION_LIMIT_EXCEEDED` apply"

        Design: Corner/validations/pitch_negotiation_round_cap
        """
        creator = make_active_creator(handle="cv6")
        brand = make_brand(name="BV6")
        brief_ns = make_open_brief(brand["id"], usage_rights_days=30)
        pitch = make_pitch(brief_ns.brief["id"], creator["id"],
                           proposed_fee_cents=90000,
                           expected_brief_version=brief_ns.version)
        shortlist_pitch(pitch["id"])
        validate_success(api.pitch_brand_action(
            pitch["id"], {"action": "COUNTER", "counter_fee_cents": 80000}, BM))
        validate_success(api.pitch_talent_action(
            pitch["id"], {"action": "RESUBMIT", "proposed_fee_cents": 85000}, TM))
        validate_success(api.pitch_brand_action(
            pitch["id"], {"action": "COUNTER", "counter_fee_cents": 82000}, BM))
        res = api.pitch_talent_action(
            pitch["id"], {"action": "RESUBMIT", "proposed_fee_cents": 84000}, TM)
        validate_error(res, ApiErrorId.ERR_NEGOTIATION_LIMIT_EXCEEDED, 422)
        after = validate_success(api.get_pitch(pitch["id"], TM))
        assert after["negotiation_rounds"] == 3
        assert after["status"] == "COUNTERED"


class TestBriefAcceptanceGuards:
    def test_budget_exceeded_on_accept(self, api):
        """PRD §3.3: "The budget check follows: the sum of
        `proposed_fee_cents` across the brief's `ACCEPTED` pitches whose
        deals are not `TERMINATED`, plus this pitch's `proposed_fee_cents`,
        must not exceed the brief's `budget_cents`, else
        `ERR_BRIEF_BUDGET_EXCEEDED`."

        Design: Corner/validations/budget_exceeded_on_accept
        """
        c1 = make_active_creator(handle="cv13")
        c2 = make_active_creator(handle="cv14")
        brand = make_brand(name="BV13")
        brief_ns = make_open_brief(brand["id"], slots_total=2,
                                   budget_cents=100000, usage_rights_days=30)
        p1 = make_pitch(brief_ns.brief["id"], c1["id"], proposed_fee_cents=80000,
                        concept_note="a", expected_brief_version=brief_ns.version)
        p2 = make_pitch(brief_ns.brief["id"], c2["id"], proposed_fee_cents=50000,
                        concept_note="b")
        shortlist_pitch(p1["id"])
        accept_pitch(p1["id"])
        shortlist_pitch(p2["id"])
        res = api.pitch_brand_action(p2["id"], {"action": "ACCEPT"}, BM)
        validate_error(res, ApiErrorId.ERR_BRIEF_BUDGET_EXCEEDED, 422)
        brief = validate_success(api.get_brief(brief_ns.brief["id"], BM))
        assert brief["slots_committed"] == 1
        p2_after = validate_success(api.get_pitch(p2["id"], TM))
        assert p2_after["status"] == "SHORTLISTED"

    def test_slots_full_on_accept(self, api):
        """PRD §3.3: "Acceptance by a `BrandManager` requires the pitch to be
        `SHORTLISTED`, and its brief must be `OPEN` or `AWARDED` — any other
        brief state is rejected with `ERR_INVALID_STATE`. Capacity is checked
        next: when `slots_committed` already equals `slots_total`, acceptance
        is rejected with `ERR_BRIEF_SLOTS_FULL`."
        PRD §3.2: "When an acceptance lifts `slots_committed` to equal
        `slots_total`, the brief bubble-up transitions from `OPEN` to
        `AWARDED` on its own."

        Design: Corner/validations/slots_full_on_accept
        """
        c1 = make_active_creator(handle="cv15")
        c2 = make_active_creator(handle="cv16")
        brand = make_brand(name="BV14")
        brief_ns = make_open_brief(brand["id"], slots_total=1,
                                   usage_rights_days=30)
        p1 = make_pitch(brief_ns.brief["id"], c1["id"], proposed_fee_cents=90000,
                        concept_note="a", expected_brief_version=brief_ns.version)
        p2 = make_pitch(brief_ns.brief["id"], c2["id"], proposed_fee_cents=90000,
                        concept_note="b")
        shortlist_pitch(p1["id"])
        shortlist_pitch(p2["id"])
        accept_pitch(p1["id"])
        brief = validate_success(api.get_brief(brief_ns.brief["id"], BM))
        assert brief["status"] == "AWARDED", "first accept fills the brief"
        res = api.pitch_brand_action(p2["id"], {"action": "ACCEPT"}, BM)
        validate_error(res, ApiErrorId.ERR_BRIEF_SLOTS_FULL, 422)
        p2_after = validate_success(api.get_pitch(p2["id"], TM))
        assert p2_after["status"] == "SHORTLISTED"

    def test_brief_close_with_committed_slots_rejected(self, api):
        """PRD §3.2: "A `BrandManager` closes a brief explicitly: an `OPEN`
        brief closes only while `slots_committed` is still zero — otherwise
        the close is rejected with `ERR_INVALID_STATE`"

        Design: Corner/state_machines/brief_close_with_committed_slots_rejected
        """
        ns = make_accepted_deal(brief_overrides={"slots_total": 2,
                                                 "usage_rights_days": 30})
        res = api.close_brief(ns.brief["id"], BM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
        brief = validate_success(api.get_brief(ns.brief["id"], BM))
        assert brief["status"] == "OPEN"
        assert brief["slots_committed"] == 1


class TestSlotConservation:
    def _setup_two_pitch_brief(self):
        c1 = make_active_creator(handle="cri1")
        c2 = make_active_creator(handle="cri2")
        brand = make_brand(name="B15")
        brief_ns = make_open_brief(brand["id"], slots_total=2)
        p1 = make_pitch(brief_ns.brief["id"], c1["id"],
                        proposed_fee_cents=100000, concept_note="a",
                        expected_brief_version=brief_ns.version)
        p2 = make_pitch(brief_ns.brief["id"], c2["id"],
                        proposed_fee_cents=100000, concept_note="b")
        shortlist_pitch(p1["id"])
        accepted = accept_pitch(p1["id"])
        return c1, c2, brand, brief_ns, p1, p2, accepted["deal_id"]

    def test_slots_committed_accept_then_terminate(self, api):
        """PRD §3.2: "The `slots_committed` counter tracks how many of the
        brief's pitches are in `ACCEPTED` with a deal that has not been
        `TERMINATED`; it is recomputed upward on every pitch acceptance and
        downward whenever such a deal terminates."
        PRD §3.4: "Termination is the hard stop and may be invoked by a
        `BrandManager` on an `ACTIVE` deal with a free-text `reason`."

        Accept commits a slot (0 -> 1); terminating the deal frees it (1 ->
        0).

        Design: Difficulty/compensating_invariant/brief_slots_conserved_accept_terminate
        """
        c1, c2, brand, brief_ns, p1, p2, deal_id = self._setup_two_pitch_brief()
        brief = get_brief(brief_ns.brief["id"])
        assert brief["slots_committed"] == 1, "acceptance commits one slot"

        # Walk the deal to ACTIVE, then terminate it (terminate requires
        # ACTIVE per PRD §3.4).
        propose_terms(deal_id, 100000)
        creator_accept_terms(deal_id, c1["id"])
        brand_accept_terms(deal_id, brand["id"])
        validate_success(
            api.terminate_deal(deal_id, {"reason": "compensation test"}, BM)
        )
        brief = get_brief(brief_ns.brief["id"])
        assert brief["slots_committed"] == 0, (
            "terminating the deal frees its committed slot"
        )
        assert brief["status"] == "OPEN", "brief never reached AWARDED"

    def test_slots_committed_reaccept_after_terminate(self, api):
        """PRD §3.2: "it is recomputed upward on every pitch acceptance and
        downward whenever such a deal terminates. When an acceptance lifts
        `slots_committed` to equal `slots_total`, the brief bubble-up
        transitions from `OPEN` to `AWARDED` on its own."
        PRD §3.3: "On success, acceptance creates the Deal in `DRAFT`"

        After the compensating terminate, a second acceptance re-commits the
        freed slot (0 -> 1) and spawns a fresh deal — no leak, no
        double-count.

        Design: Difficulty/compensating_invariant/brief_slots_conserved_accept_terminate
        """
        c1, c2, brand, brief_ns, p1, p2, deal_id = self._setup_two_pitch_brief()
        propose_terms(deal_id, 100000)
        creator_accept_terms(deal_id, c1["id"])
        brand_accept_terms(deal_id, brand["id"])
        validate_success(
            api.terminate_deal(deal_id, {"reason": "compensation test"}, BM)
        )
        assert get_brief(brief_ns.brief["id"])["slots_committed"] == 0

        shortlist_pitch(p2["id"])
        accepted2 = accept_pitch(p2["id"])
        assert accepted2["status"] == "ACCEPTED"
        assert accepted2["deal_id"], "second acceptance creates a new deal"
        brief = get_brief(brief_ns.brief["id"])
        assert brief["slots_committed"] == 1, (
            "slots sequence across accept/terminate/re-accept is 1 -> 0 -> 1"
        )
        assert brief["status"] == "OPEN", "one committed of two slots"


class TestTerminalAcceptPrecedence:
    def _setup_withdrawn_or_rejected_pitch(self, api, terminal_action: str):
        c1 = make_active_creator(handle="crp1")
        c2 = make_active_creator(handle="crp2")
        brand = make_brand(name="B9")
        brief_ns = make_open_brief(brand["id"], slots_total=2,
                                   budget_cents=100000)
        p1 = make_pitch(brief_ns.brief["id"], c1["id"],
                        proposed_fee_cents=80000, concept_note="a",
                        expected_brief_version=brief_ns.version)
        p2 = make_pitch(brief_ns.brief["id"], c2["id"],
                        proposed_fee_cents=50000, concept_note="b")
        shortlist_pitch(p1["id"])
        accept_pitch(p1["id"])
        shortlist_pitch(p2["id"])
        if terminal_action == "WITHDRAW":
            validate_success(
                api.pitch_talent_action(p2["id"], {"action": "WITHDRAW"}, TM)
            )
        else:
            validate_success(
                api.pitch_brand_action(p2["id"], {"action": "REJECT"}, BM)
            )
        return brief_ns, p2

    def test_accept_withdrawn_pitch_budget_exceeded_state_wins(self, api):
        """PRD §2.8: "A single request can violate several rules at once, so
        checks fire in a fixed global order and the first failing check
        determines the response."
        PRD §2.8: "7. Terminal lockdown: the action was triggered from a
        terminal state (else `ERR_ALREADY_TERMINAL`)."
        PRD §3.3: "withdrawing moves a pitch from any of `SUBMITTED`,
        `SHORTLISTED`, or `COUNTERED` to terminal `WITHDRAWN`."

        The withdrawn pitch's fee would also breach the budget (80,000 +
        50,000 > 100,000), but terminal lockdown fires first.

        Design: Difficulty/priority_pair_validation_conflict/accept_withdrawn_pitch_budget_exceeded_state_wins
        """
        brief_ns, p2 = self._setup_withdrawn_or_rejected_pitch(api, "WITHDRAW")
        res = api.pitch_brand_action(p2["id"], {"action": "ACCEPT"}, BM)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        brief = get_brief(brief_ns.brief["id"])
        assert brief["slots_committed"] == 1, "no partial slot commit"

    def test_accept_rejected_pitch_terminal_lockdown(self, api):
        """PRD §2.9: "Triggering an action from a terminal state is rejected
        with `ERR_ALREADY_TERMINAL` (HTTP 409); triggering one from a
        non-terminal state the transition does not allow is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.3: "Rejecting moves a pitch from `SUBMITTED`, `SHORTLISTED`,
        or `COUNTERED` to terminal `REJECTED`."

        Same lockdown from the REJECTED terminal state: the budget breach is
        never evaluated.

        Design: Difficulty/priority_pair_validation_conflict/accept_withdrawn_pitch_budget_exceeded_state_wins
        """
        brief_ns, p2 = self._setup_withdrawn_or_rejected_pitch(api, "REJECT")
        res = api.pitch_brand_action(p2["id"], {"action": "ACCEPT"}, BM)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        after = validate_success(api.get_pitch(p2["id"], TM))
        assert after["status"] == "REJECTED"


class TestBriefExpirySweep:
    def test_brief_expiry_sweep_cascade(self, api):
        """PRD §2.5: "First, every brief still `OPEN` whose
        `submission_window_end` lies behind the new clock reading transitions
        to `EXPIRED`, withdrawing its unresolved pitches as described in
        §3.2."
        PRD §3.2: "Once `OPEN`, the brief accepts pitches until the logical
        clock passes `submission_window_end`, at which point the clock sweep
        moves it to `EXPIRED` and withdraws every pitch still in `SUBMITTED`,
        `SHORTLISTED`, or `COUNTERED`."

        Design: Corner/cross_cutting_layers/brief_expiry_sweep_cascade
        """
        creator = make_active_creator(handle="cl6")
        brand = make_brand(name="BL5")
        brief_ns = make_open_brief(
            brand["id"], usage_rights_days=30,
            submission_window_end="2026-08-10T00:00:00Z",
        )
        pitch = make_pitch(brief_ns.brief["id"], creator["id"],
                           proposed_fee_cents=90000,
                           expected_brief_version=brief_ns.version)
        set_clock("2026-08-11T00:00:00Z")
        brief = get_brief(brief_ns.brief["id"])
        assert brief["status"] == "EXPIRED"
        pitch_after = validate_success(api.get_pitch(pitch["id"], TM))
        assert pitch_after["status"] == "WITHDRAWN", (
            "the expiry sweep withdraws unresolved pitches"
        )
