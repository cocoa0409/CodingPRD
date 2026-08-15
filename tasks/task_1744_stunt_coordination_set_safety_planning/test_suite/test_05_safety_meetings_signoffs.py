"""Safety meetings and department sign-off: the facility buffer rule, signoff
decision gates, meeting completion, and refusal semantics (PRD §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    COORD,
    DEPT_HEAD,
    SAFETY,
    create_active_production,
    create_locked_sequence,
    create_safety_meeting_payload,
    hold_safety_meeting,
    setup_locked_with_rehearsals,
    validate_error,
    validate_success,
)


def _locked_prod_seq(api, name="P"):
    prod = create_active_production(name=name, budget=5000000)
    seq = create_locked_sequence(prod["id"], name=f"{name} Seq", hazard_class="FIGHT", risk_category="LOW")
    return prod, seq


def _meeting_in_session(api, prod, seq, facility="Stage 2"):
    mtg = validate_success(
        api.create_safety_meeting(create_safety_meeting_payload(prod["id"], seq["id"], facility=facility), COORD),
        201,
    )
    validate_success(api.start_meeting(mtg["id"], SAFETY))
    return mtg


def _signoffs(api, meeting_id):
    return validate_success(api.list_signoffs(SAFETY, params={"meeting_id": meeting_id}))


class TestFacilityBuffer:
    """Symmetric 1800-second buffer between meetings at the same facility
    (PRD §3.4)."""

    def _setup_two_sequences_and_first_meeting(self, api):
        prod = create_active_production(name="Facility Prod", budget=10000000)
        seq1 = create_locked_sequence(prod["id"], name="Fac Seq 1", hazard_class="FIGHT", risk_category="LOW")
        seq2 = create_locked_sequence(prod["id"], name="Fac Seq 2", hazard_class="FIGHT", risk_category="LOW")
        validate_success(
            api.create_safety_meeting(
                create_safety_meeting_payload(
                    prod["id"], seq1["id"], facility="Stage 9",
                    scheduled_start="2026-08-03T10:00:00Z", scheduled_end="2026-08-03T11:00:00Z",
                ),
                COORD,
            ),
            201,
        )
        return prod, seq2

    def test_twenty_minute_gap_rejected(self, api):
        """PRD §3.4: "A new meeting conflicts with an existing meeting at the
        same facility — across all sequences of the production, considering only
        existing meetings in `SCHEDULED` or `IN_SESSION` — when the new meeting
        starts before thirty minutes after the existing meeting ends and the
        existing meeting starts before thirty minutes after the new meeting
        ends."

        Design: Difficulty/resource_temporal_overlap/ro_meeting_facility_buffered_gap
        """
        prod, seq2 = self._setup_two_sequences_and_first_meeting(api)
        payload = create_safety_meeting_payload(
            prod["id"], seq2["id"], facility="Stage 9",
            scheduled_start="2026-08-03T11:20:00Z", scheduled_end="2026-08-03T12:00:00Z",
        )
        resp = api.create_safety_meeting(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_FACILITY_BUFFER_CONFLICT)

    def test_exact_thirty_minute_gap_allowed(self, api):
        """PRD §3.4: "The buffer is a symmetric 1,800 seconds on both sides, and
        a gap of exactly thirty minutes between the two windows is allowed; a
        violation is rejected with `ERR_FACILITY_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/ro_meeting_facility_buffered_gap
        """
        prod, seq2 = self._setup_two_sequences_and_first_meeting(api)
        payload = create_safety_meeting_payload(
            prod["id"], seq2["id"], facility="Stage 9",
            scheduled_start="2026-08-03T11:30:00Z", scheduled_end="2026-08-03T12:00:00Z",
        )
        data = validate_success(api.create_safety_meeting(payload, COORD), 201)
        assert data["status"] == "SCHEDULED", "11:30 == 11:00 + 1800s is allowed (strict <)"


class TestSignoffGates:
    def test_decided_signoff_is_terminal(self, api):
        """PRD §3.4: "A signoff no longer `PENDING` rejects any further decision
        with `ERR_SIGNOFF_ALREADY_DECIDED`"

        Design: Corner/state_machines/sm_signoff_decided_lockout_rejected
        """
        prod, seq = _locked_prod_seq(api)
        mtg = _meeting_in_session(api, prod, seq)
        camera = next(s for s in _signoffs(api, mtg["id"]) if s["department"] == "CAMERA")
        signed = validate_success(api.sign_signoff(camera["id"], DEPT_HEAD))
        assert signed["status"] == "SIGNED"
        resp = api.refuse_signoff(camera["id"], {"reason": "changed my mind"}, DEPT_HEAD)
        validate_error(resp, ApiErrorId.ERR_SIGNOFF_ALREADY_DECIDED)

    def test_signoff_requires_in_session_meeting(self, api):
        """PRD §3.4: "decisions attempted while the meeting is not `IN_SESSION`
        are rejected with `ERR_MEETING_INVALID_STATE`"

        Design: Corner/state_machines/sm_signoff_requires_in_session_rejected
        """
        prod, seq = _locked_prod_seq(api)
        # Meeting created but NOT started.
        mtg = validate_success(
            api.create_safety_meeting(create_safety_meeting_payload(prod["id"], seq["id"]), COORD), 201
        )
        camera = next(s for s in _signoffs(api, mtg["id"]) if s["department"] == "CAMERA")
        resp = api.sign_signoff(camera["id"], DEPT_HEAD)
        validate_error(resp, ApiErrorId.ERR_MEETING_INVALID_STATE)

    def test_meeting_complete_blocked_by_pending_signoffs(self, api):
        """PRD §3.4: "Completing the meeting (`IN_SESSION → COMPLETED`) requires
        every signoff decided — `SIGNED`, `SIGNED_WITH_CONDITIONS`, or
        `REFUSED`; while any signoff remains `PENDING` the completion is
        rejected with `ERR_SIGNOFFS_PENDING`."

        Design: Corner/state_machines/sm_meeting_complete_blocked_pending_signoffs
        """
        prod, seq = _locked_prod_seq(api)
        mtg = _meeting_in_session(api, prod, seq)
        camera = next(s for s in _signoffs(api, mtg["id"]) if s["department"] == "CAMERA")
        validate_success(api.sign_signoff(camera["id"], DEPT_HEAD))
        # ELECTRIC / GRIP / STUNTS remain PENDING.
        resp = api.complete_meeting(mtg["id"], SAFETY)
        validate_error(resp, ApiErrorId.ERR_SIGNOFFS_PENDING)


class TestRefusedMeeting:
    def test_refusal_completes_meeting_but_blocks_readiness(self, api):
        """PRD §3.4: "A meeting containing a refusal still completes, but it
        does not satisfy the readiness gate of §3.6."
        PRD §3.6: "Meeting satisfaction: there must exist a safety meeting of
        this sequence in `COMPLETED` status whose pinned `design_revision`
        equals the sequence's current `design_revision` and all of whose
        department signoffs stand in `SIGNED` or `SIGNED_WITH_CONDITIONS` — a
        meeting containing any `REFUSED` signoff does not qualify — else
        `ERR_MEETING_REQUIREMENT_UNSATISFIED`."

        Design: Corner/state_machines/sm_meeting_refusal_completes_but_blocks_readiness
        """
        ctx = setup_locked_with_rehearsals(name="Ref", hazard_class="FIGHT", risk_category="LOW",
                                           acknowledge=False)
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        meeting, decisions = hold_safety_meeting(prod_id, seq_id, refuse_departments=("STUNTS",))
        assert meeting["status"] == "COMPLETED", "refusal is a decision; no PENDING remains"
        assert decisions["STUNTS"] == "REFUSED"
        resp = api.mark_ready(seq_id, COORD)
        validate_error(resp, ApiErrorId.ERR_MEETING_REQUIREMENT_UNSATISFIED)
