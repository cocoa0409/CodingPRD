"""Conducting the walkthrough: checklist seeding and marking, attendee
identity rules, segregation of duties, and the completion gates/cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


class TestChecklistCountConservation:
    def test_mark_and_reset_preserve_partition(self, api):
        """PRD §3.3: "From this point the appointment reports
        `checklist_total_count` as 6 (it is 0 before the start), with
        `checklist_demonstrated_count`, `checklist_pending_count`, and
        `checklist_skipped_count` derived from the entries"
        PRD §3.3: "the last acting as a compensating reset when a demonstration
        must be unwound. ... every mark recomputes the checklist counters and
        increments the appointment's `version`."

        Design: Difficulty/compensating_invariant/checklist_mark_reset_count_conservation
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        # Seed-time partition: all six entries PENDING.
        assert appt["checklist_total_count"] == 6, (
            f"seeded checklist must total 6, got {appt['checklist_total_count']}"
        )
        assert appt["checklist_pending_count"] == 6
        assert appt["checklist_demonstrated_count"] == 0
        assert appt["checklist_skipped_count"] == 0

        marked = validate_success(api.mark_checklist_item(
            appt["id"], "HVAC", {"outcome": "DEMONSTRATED"},
            make_rep_headers(rep["id"]),
        ))
        assert marked["checklist_total_count"] == 6
        assert marked["checklist_pending_count"] == 5
        assert marked["checklist_demonstrated_count"] == 1

        reset = validate_success(api.mark_checklist_item(
            appt["id"], "HVAC", {"outcome": "PENDING"},
            make_rep_headers(rep["id"]),
        ))
        # The compensating reset restores the seed-time partition exactly.
        assert reset["checklist_total_count"] == 6
        assert reset["checklist_pending_count"] == 6
        assert reset["checklist_demonstrated_count"] == 0

    def test_every_mark_preserves_total_of_six(self, api):
        """PRD §3.3: "From this point the appointment reports
        `checklist_total_count` as 6 (it is 0 before the start), with
        `checklist_demonstrated_count`, `checklist_pending_count`, and
        `checklist_skipped_count` derived from the entries"
        PRD §3.3: "During the walkthrough the representative marks each entry's
        `outcome` as `DEMONSTRATED`, `SKIPPED`, or `PENDING`"

        Design: Difficulty/compensating_invariant/checklist_mark_reset_count_conservation
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        for key, outcome in [("PLUMBING", "DEMONSTRATED"), ("PLUMBING", "SKIPPED"),
                             ("PLUMBING", "PENDING")]:
            current = validate_success(api.mark_checklist_item(
                appt["id"], key, {"outcome": outcome}, make_rep_headers(rep["id"])
            ))
            total = (current["checklist_demonstrated_count"]
                     + current["checklist_pending_count"]
                     + current["checklist_skipped_count"])
            assert current["checklist_total_count"] == 6, (
                f"total must stay 6 after {key}->{outcome}, got {current['checklist_total_count']}"
            )
            assert total == 6, (
                f"partition must sum to 6 after {key}->{outcome}, got {total}"
            )


class TestCompletionGates:
    def test_complete_blocked_by_pending_checklist_item(self, api, manager_headers):
        """PRD §3.3: "First, every checklist entry with `is_required` true must be
        `DEMONSTRATED` and no entry may remain `PENDING`; the optional
        `APPLIANCES` entry may be `SKIPPED` but never left pending, and a
        shortfall is rejected with `ERR_CHECKLIST_INCOMPLETE`."

        Design: Corner/state_machines/complete_blocked_by_pending_checklist
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        # Four required systems demonstrated, APPLIANCES skipped; SAFETY stays
        # PENDING.
        for key in ("HVAC", "PLUMBING", "ELECTRICAL", "EXTERIOR"):
            resp = api.mark_checklist_item(
                appt["id"], key, {"outcome": "DEMONSTRATED"},
                make_rep_headers(rep["id"]),
            )
            assert resp.status_code == 200, f"Setup failed (mark {key}): {resp.text}"
        resp = api.mark_checklist_item(
            appt["id"], "APPLIANCES", {"outcome": "SKIPPED"},
            make_rep_headers(rep["id"]),
        )
        assert resp.status_code == 200, f"Setup failed (mark APPLIANCES): {resp.text}"

        validate_error(api.complete_appointment(appt["id"], make_rep_headers(rep["id"])),
                       ApiErrorId.ERR_CHECKLIST_INCOMPLETE)
        surveys, meta = validate_paginated(
            api.list_feedback_surveys(manager_headers, params={"home_id": home["id"]})
        )
        assert len(surveys) == 0, (
            f"failed completion must not fire survey side effects, got {len(surveys)}"
        )

    def test_complete_blocked_until_primary_attendee_verified(self, api, manager_headers):
        """PRD §3.3: "Second, at least one `VERIFIED` attendee must cover the
        primary buyer: either an attendee of type `BUYER` or `CO_BUYER` whose
        `buyer_id` equals the home's `primary_buyer_id`, or a `POA_PROXY`
        acting on the buyer's behalf; otherwise the completion is rejected with
        `ERR_ATTENDEE_REQUIREMENT_UNMET`."

        Design: Difficulty/cross_entity_state_dependency/complete_requires_verified_primary_attendee
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        attendee = get_success_data(api.create_attendee(
            {"appointment_id": appt["id"], "attendee_type": "BUYER",
             "buyer_id": buyer["id"]},
            make_rep_headers(rep["id"]),
        ))
        fx.mark_checklist(appt["id"], rep["id"])
        # Attendee still PENDING: completion must fail.
        validate_error(api.complete_appointment(appt["id"], make_rep_headers(rep["id"])),
                       ApiErrorId.ERR_ATTENDEE_REQUIREMENT_UNMET)
        resp = api.decide_attendee_verification(
            attendee["id"], {"decision": "VERIFIED"}, manager_headers
        )
        assert resp.status_code == 200, f"Setup failed (verify): {resp.text}"
        completed = validate_success(
            api.complete_appointment(appt["id"], make_rep_headers(rep["id"]))
        )
        assert completed["status"] == "COMPLETED", (
            f"verified attendee must unblock completion, got {completed['status']}"
        )

    def test_verified_poa_proxy_covers_primary_buyer(self, api, manager_headers):
        """PRD §3.3: "Second, at least one `VERIFIED` attendee must cover the
        primary buyer: either an attendee of type `BUYER` or `CO_BUYER` whose
        `buyer_id` equals the home's `primary_buyer_id`, or a `POA_PROXY`
        acting on the buyer's behalf; otherwise the completion is rejected with
        `ERR_ATTENDEE_REQUIREMENT_UNMET`."

        Design: Difficulty/cross_entity_state_dependency/complete_requires_verified_primary_attendee
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.setup_orientation_in_progress(
            home["id"], rep["id"], "2026-08-25T14:00:00Z"
        )
        attendee = get_success_data(api.create_attendee(
            {"appointment_id": appt["id"], "attendee_type": "POA_PROXY",
             "proxy_name": "Pat Proxy", "poa_document_ref": "poa-doc-1"},
            make_rep_headers(rep["id"]),
        ))
        fx.mark_checklist(appt["id"], rep["id"])
        resp = api.decide_attendee_verification(
            attendee["id"], {"decision": "VERIFIED"}, manager_headers
        )
        assert resp.status_code == 200, f"Setup failed (verify proxy): {resp.text}"
        completed = validate_success(
            api.complete_appointment(appt["id"], make_rep_headers(rep["id"]))
        )
        assert completed["status"] == "COMPLETED", (
            f"a verified POA proxy must satisfy the attendee gate, "
            f"got {completed['status']}"
        )

    def test_completion_cascade_fires_all_children(self, api, manager_headers):
        """PRD §3.3: "A successful completion stamps `completed_at` from the
        logical clock and fires a cascade within the same request: a
        `FeedbackSurvey` is created in `ISSUED` with its `window_closes_at` set
        to `completed_at` plus the community's `survey_window_days`; an
        `AcknowledgmentSignature` is created in `PENDING` only if none exists
        for the home, an existing record being left untouched; and the home
        moves from `ORIENTATION_SCHEDULED` to `ORIENTED`, which itself
        provisions the escrow holdback described in §3.7."

        Design: Difficulty/transitive_cascade/appointment_completion_escrow_provisioning_cascade
        """
        community, buyer, rep = fx.setup_base(
            community_overrides={"holdback_cost_multiplier": 2.0,
                                 "holdback_min_cents": 1_000,
                                 "holdback_max_cents": 10_000_000}
        )
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        fx.set_clock("2026-08-25T14:00:00Z")
        fx.start_appointment(appt["id"], rep["id"])
        # The after-closing decision lands BEFORE completion, so the
        # provisioning recompute activates the fresh escrow (20000 * 2.0).
        item = fx.create_deficiency(home["id"], appt["id"], rep["id"],
                                    title="Furnace ignition fault")
        fx.classify_deficiency(item["id"], rep["id"],
                               estimated_repair_cost_cents=20_000)
        fx.decide_deficiency(item["id"], "COMPLETE_AFTER_CLOSING")
        fx.add_verified_buyer_attendee(appt["id"], buyer["id"], acting_rep_id=rep["id"])
        fx.mark_checklist(appt["id"], rep["id"])

        completed = validate_success(
            api.complete_appointment(appt["id"], make_rep_headers(rep["id"]))
        )
        assert completed["status"] == "COMPLETED"

        home = get_success_data(api.get_home(home["id"], manager_headers))
        assert home["status"] == "ORIENTED", (
            f"completion must flip the home to ORIENTED, got {home['status']}"
        )
        escrow = fx.get_escrow_for_home(home["id"])
        assert escrow["status"] == "ACTIVE", (
            f"provisioning recompute must activate the fresh escrow, got {escrow['status']}"
        )
        assert escrow["holdback_amount_cents"] == 40_000, (
            f"2.0 * 20000 must yield 40000, got {escrow['holdback_amount_cents']}"
        )
        survey = fx.get_survey_for_home(home["id"])
        assert survey["status"] == "ISSUED"
        signature = fx.get_signature_for_home(home["id"])
        assert signature["status"] == "PENDING"

    def test_completion_stamps_completed_at_and_survey_window(self, api, manager_headers):
        """PRD §3.3: "A successful completion stamps `completed_at` from the
        logical clock and fires a cascade within the same request: a
        `FeedbackSurvey` is created in `ISSUED` with its `window_closes_at` set
        to `completed_at` plus the community's `survey_window_days`"

        Design: Difficulty/transitive_cascade/appointment_completion_escrow_provisioning_cascade
        """
        community, buyer, rep = fx.setup_base()  # survey_window_days default 14
        home = fx.setup_home(community["id"], buyer["id"])
        completed = fx.setup_completed_orientation(
            home["id"], rep["id"], buyer["id"], "2026-08-25T14:00:00Z"
        )
        assert completed["completed_at"].startswith("2026-08-25T14:00"), (
            f"completed_at must come from the logical clock, got {completed['completed_at']}"
        )
        survey = fx.get_survey_for_home(home["id"])
        assert survey["window_closes_at"].startswith("2026-09-08T14:00"), (
            f"window must close 14 days after completion, got {survey['window_closes_at']}"
        )


class TestAttendeeIdentityRules:
    def test_poa_proxy_requires_document_ref(self, api):
        """PRD §3.3: "A proxy missing its name or document reference is rejected
        with `ERR_POA_DOCUMENT_REQUIRED`"

        Design: Corner/validations/poa_proxy_requires_document
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        resp = api.create_attendee(
            {"appointment_id": appt["id"], "attendee_type": "POA_PROXY",
             "proxy_name": "Pat Proxy"},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_POA_DOCUMENT_REQUIRED)

    def test_proxy_with_buyer_id_rejected(self, api):
        """PRD §3.3: "a `buyer_id` present on a proxy, absent on a buyer-type
        attendee, or proxy fields present on a buyer-type attendee are all
        rejected with `ERR_ATTENDEE_IDENTITY_INVALID`."

        Design: Corner/validations/proxy_with_buyer_id_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        resp = api.create_attendee(
            {"appointment_id": appt["id"], "attendee_type": "POA_PROXY",
             "buyer_id": buyer["id"], "proxy_name": "Pat Proxy",
             "poa_document_ref": "poa-doc-1"},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ATTENDEE_IDENTITY_INVALID)


class TestSegregationOfDuties:
    def test_conducting_rep_cannot_verify_but_other_rep_can(self, api):
        """PRD §3.3: "Segregation of duties applies at this gate: when the actor
        is a `CustomerCareRep`, their `X-User-ID` must differ from the
        appointment's `rep_id`, and a violation is rejected with
        `ERR_SELF_VERIFICATION_FORBIDDEN`; a `CustomerCareManager` is exempt
        from the segregation rule."

        Design: Corner/rbac/segregation_conducting_rep_cannot_verify
        """
        community, buyer, rep = fx.setup_base()
        rep2 = fx.setup_rep()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        attendee = get_success_data(api.create_attendee(
            {"appointment_id": appt["id"], "attendee_type": "BUYER",
             "buyer_id": buyer["id"]},
            make_rep_headers(rep["id"]),
        ))
        validate_error(
            api.decide_attendee_verification(
                attendee["id"], {"decision": "VERIFIED"}, make_rep_headers(rep["id"])
            ),
            ApiErrorId.ERR_SELF_VERIFICATION_FORBIDDEN,
        )
        decided = validate_success(api.decide_attendee_verification(
            attendee["id"], {"decision": "VERIFIED"}, make_rep_headers(rep2["id"])
        ))
        assert decided["verification_status"] == "VERIFIED"
        assert decided["decided_by_user_id"] == rep2["id"], (
            f"deciding rep must be recorded, got {decided['decided_by_user_id']}"
        )


class TestAttendeeTerminalLockdown:
    def test_redeciding_verified_attendee_rejected(self, api, manager_headers):
        """PRD §3.3: "The appointment must be `CONFIRMED` or `IN_PROGRESS` —
        deciding against an appointment in any other status, or re-deciding an
        attendee who has already reached the terminal `VERIFIED` or `REJECTED`
        states, is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/attendee_redecision_rejected
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        fx.confirm_appointment(appt["id"])
        attendee = get_success_data(api.create_attendee(
            {"appointment_id": appt["id"], "attendee_type": "BUYER",
             "buyer_id": buyer["id"]},
            make_rep_headers(rep["id"]),
        ))
        resp = api.decide_attendee_verification(
            attendee["id"], {"decision": "VERIFIED"}, manager_headers
        )
        assert resp.status_code == 200, f"Setup failed (verify): {resp.text}"
        validate_error(
            api.decide_attendee_verification(
                attendee["id"],
                {"decision": "REJECTED", "rejection_reason": "changed mind"},
                manager_headers,
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
