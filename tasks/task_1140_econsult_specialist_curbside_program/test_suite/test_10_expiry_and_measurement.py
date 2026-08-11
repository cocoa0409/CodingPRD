"""Expiry sweep cascades and avoided-visit measurement variants."""
from test_helpers import (
    ApiErrorId, TEST_USERS, close_consult, create_consult, create_membership,
    create_provider, create_specialist, create_track, create_window,
    document_response, finalize_response, get_consult, get_membership,
    make_specialist_headers, set_clock, submit_response,
    validate_error, validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestExpirySweep:
    def _setup_two_track_expiry_scenario(self):
        """CARDIOLOGY track with a panel (consult A -> ASSIGNED at 2026-06-01 with a
        48h routine SLA) and NEUROLOGY track with no panel (consult B -> QUEUED)."""
        set_clock("2026-06-01T00:00:00Z")
        track_a = create_track("CARDIOLOGY")
        track_b = create_track("NEUROLOGY")
        provider = create_provider(npi="1000000071")
        specialist = create_specialist(npi="2000000071")
        membership = create_membership(specialist["id"], track_a["id"])
        create_window(membership["id"], specialist["id"])
        cons_a = create_consult(
            track_a["id"], provider["id"], patient_ref="PAT-TC2",
            question_text="Chronic stable angina, medication refill interaction question regarding ranolazine and simvastatin.",
            icd10_primary="I20",
        )
        cons_b = create_consult(
            track_b["id"], provider["id"], patient_ref="PAT-TC3",
            question_text="New onset migraine with aura; asks about starting triptan versus prophylaxis given frequency.",
            icd10_primary="G43",
        )
        return {
            "track_a": track_a, "track_b": track_b, "provider": provider,
            "specialist": specialist, "membership": membership,
            "cons_a": cons_a, "cons_b": cons_b,
        }

    def test_clock_sweep_expires_assigned_consult_and_moves_counters(self, api):
        """PRD §2.5: "Any consult still `ASSIGNED` or `CLARIFICATION_REQUESTED` whose
        deadline — its `sla_due_at` plus a 24-hour grace period — is strictly earlier
        than the new clock value transitions to `EXPIRED`"
        PRD §3.3: "the consult transitions to `EXPIRED`, its `sla_breached` flag is
        set to true, the membership's `expired_count` increases by one and its
        `open_consult_count` decreases by one, and the `billing_status` moves from
        `UNBILLABLE` to `VOID`."

        Design: Difficulty/transitive_cascade/clock_sweep_expiry_cascades_to_membership_counters
        """
        scenario = self._setup_two_track_expiry_scenario()
        assert scenario["cons_a"]["status"] == "ASSIGNED"
        # sla_due_at 2026-06-03T00:00:00Z + 24h grace = 2026-06-04T00:00:00Z;
        # the new clock value 2026-06-04T01:00:00Z is strictly later.
        set_clock("2026-06-04T01:00:00Z")
        cons_a = get_consult(scenario["cons_a"]["id"])
        assert cons_a["status"] == "EXPIRED"
        assert cons_a["sla_breached"] is True
        assert cons_a["billing_status"] == "VOID"
        membership = get_membership(scenario["membership"]["id"])
        assert membership["expired_count"] == 1
        assert membership["open_consult_count"] == 0

    def test_clock_sweep_expires_queued_consult_past_queue_ttl(self, api):
        """PRD §2.5: "any consult still `QUEUED` more than 72 hours after its creation
        — again a strictly-greater comparison — transitions to `EXPIRED` as well."
        PRD §3.3: "A consult that sits in `QUEUED` until the logical clock is strictly
        more than 72 hours past its creation expires the same way, voiding billing,
        though no membership counters move because none was ever assigned."

        Design: Difficulty/transitive_cascade/clock_sweep_expiry_cascades_to_membership_counters
        """
        scenario = self._setup_two_track_expiry_scenario()
        assert scenario["cons_b"]["status"] == "QUEUED"
        # Created 2026-06-01T00:00:00Z; 72h later is 2026-06-04T00:00:00Z and the
        # new clock value 2026-06-04T01:00:00Z is strictly greater.
        set_clock("2026-06-04T01:00:00Z")
        cons_b = get_consult(scenario["cons_b"]["id"])
        assert cons_b["status"] == "EXPIRED"
        assert cons_b["billing_status"] == "VOID"


class TestAvoidedVisitMeasurement:
    def _setup_june_population(self):
        """Three June consults on one ENDOCRINOLOGY track:
        A answered MANAGE_IN_PRIMARY_CARE and CLOSED;
        B answered MANAGE_WITH_PLAN and CLOSED;
        C answered CONVERT_TO_VISIT (left ANSWERED) with a SCHEDULED conversion."""
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("ENDOCRINOLOGY")
        provider = create_provider(npi="1000000011")
        specialist = create_specialist(npi="2000000011")
        membership = create_membership(specialist["id"], track["id"])
        create_window(membership["id"], specialist["id"])
        spec_h = make_specialist_headers(specialist["id"])

        cons_a = create_consult(
            track["id"], provider["id"], patient_ref="PAT-AV1",
            question_text="Type 2 diabetic with rising A1c despite metformin 1g BID; ask about adding SGLT2 inhibitor now.",
            icd10_primary="E11",
        )
        resp_a = submit_response(cons_a["id"], specialist["id"],
                                 disposition="MANAGE_IN_PRIMARY_CARE",
                                 recommendation_text="Add empagliflozin 10mg daily, recheck A1c in 12 weeks, counsel on hydration.")
        document_response(resp_a["id"], provider["id"], specialist["id"])
        finalize_response(resp_a["id"], specialist["id"])
        close_consult(cons_a["id"], provider["id"])

        cons_b = create_consult(
            track["id"], provider["id"], patient_ref="PAT-AV2",
            question_text="Hypothyroid patient with TSH creeping up on current levothyroxine dose; dose adjustment advice.",
            icd10_primary="E03",
        )
        resp_b = submit_response(cons_b["id"], specialist["id"],
                                 disposition="MANAGE_WITH_PLAN",
                                 recommendation_text="Increase levothyroxine by 12.5mcg daily and repeat TSH in 8 weeks before considering referral.")
        document_response(resp_b["id"], provider["id"], specialist["id"])
        finalize_response(resp_b["id"], specialist["id"])
        close_consult(cons_b["id"], provider["id"])

        cons_c = create_consult(
            track["id"], provider["id"], patient_ref="PAT-AV3",
            question_text="New adrenal incidentaloma on CT, biochemical workup equivocal; needs face-to-face endocrine evaluation?",
            icd10_primary="D35",
        )
        submit_response(cons_c["id"], specialist["id"], disposition="CONVERT_TO_VISIT",
                        recommendation_text="Incidentaloma with equivocal metanephrines requires in-person exam and dynamic testing; please convert.")
        return {"track": track, "provider": provider, "specialist": specialist,
                "cons_c": cons_c, "spec_h": spec_h}

    def test_attributed_avoided_visits_counts_responded_minus_converted(self, api):
        """PRD §3.9: "Within that population, `responded_count` counts consults whose
        `status` is `ANSWERED` or `CLOSED`, and `conversions_count` counts those among
        them that have a conversion in `SCHEDULED` or `COMPLETED` status. The
        attributed variant, `avoided_attributed_count`, is simply `responded_count`
        minus `conversions_count` — every responded consult counts as avoided unless a
        live conversion exists."

        Design: Difficulty/dual_variant_calc/attributed_vs_conservative_avoided_visits_diverge
        """
        scenario = self._setup_june_population()
        # Consult C's conversion is SCHEDULED (created by the responding specialist).
        validate_success(api.create_conversion(
            scenario["cons_c"]["id"],
            {"appointment_start": "2026-06-10T10:00:00Z",
             "appointment_end": "2026-06-10T10:30:00Z"},
            scenario["spec_h"],
        ), 201)
        measurement = validate_success(api.create_measurement(
            {"specialty_track_id": scenario["track"]["id"], "period_key": "2026-06"},
            COORD,
        ), 201)
        assert measurement["status"] == "OPEN"
        assert measurement["responded_count"] == 3
        assert measurement["conversions_count"] == 1
        assert measurement["avoided_attributed_count"] == 2, (
            "attributed = responded 3 - converted 1"
        )

    def test_conservative_avoided_visits_diverges_from_attributed(self, api):
        """PRD §3.9: "The conservative variant, `avoided_conservative_count`, counts
        only consults that are `CLOSED`, whose response's disposition is
        `MANAGE_IN_PRIMARY_CARE`, and for which no conversion exists in any status;
        identical data always yields a conservative number no larger than the
        attributed one."

        Design: Difficulty/dual_variant_calc/attributed_vs_conservative_avoided_visits_diverge
        """
        scenario = self._setup_june_population()
        validate_success(api.create_conversion(
            scenario["cons_c"]["id"],
            {"appointment_start": "2026-06-10T10:00:00Z",
             "appointment_end": "2026-06-10T10:30:00Z"},
            scenario["spec_h"],
        ), 201)
        measurement = validate_success(api.create_measurement(
            {"specialty_track_id": scenario["track"]["id"], "period_key": "2026-06"},
            COORD,
        ), 201)
        # Only consult A qualifies: CLOSED + MANAGE_IN_PRIMARY_CARE + no conversion.
        assert measurement["avoided_conservative_count"] == 1
        assert measurement["avoided_attributed_count"] == 2
        assert measurement["avoided_conservative_count"] != measurement["avoided_attributed_count"]

    def test_measurement_finalize_freezes_counts(self, api):
        """PRD §3.9: "The measurement is born `OPEN` and both variants are recomputed
        and frozen when the coordinator finalizes it, moving it to `FINALIZED`;
        finalizing an already-final measurement is rejected with
        `ERR_MEASUREMENT_ALREADY_FINALIZED`."

        Design: Corner/endpoints/measurement_finalize_freezes_counts
        """
        set_clock("2026-06-01T00:00:00Z")
        track = create_track("CARDIOLOGY")
        measurement = validate_success(api.create_measurement(
            {"specialty_track_id": track["id"], "period_key": "2026-06"}, COORD,
        ), 201)
        assert measurement["status"] == "OPEN"
        # Empty period: every count is zero.
        assert measurement["responded_count"] == 0
        assert measurement["conversions_count"] == 0
        assert measurement["avoided_attributed_count"] == 0
        assert measurement["avoided_conservative_count"] == 0

        finalized = validate_success(
            api.finalize_measurement(measurement["id"], COORD), 200
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["responded_count"] == 0
        assert finalized["avoided_attributed_count"] == 0
        assert finalized["avoided_conservative_count"] == 0

        res = api.finalize_measurement(measurement["id"], COORD)
        validate_error(res, ApiErrorId.ERR_MEASUREMENT_ALREADY_FINALIZED,
                       expected_status=409)
