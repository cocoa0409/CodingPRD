"""Version pinning, the two-family sweep and the selector on a re-run seat."""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    CASE_MANAGER_ALT,
    admit_panelist,
    api_client,
    appointment_payload,
    assert_all_mandatory_grounds,
    build_docket,
    case_version,
    clear_compliance,
    decision_payload,
    file_complaint,
    file_response,
    first_verification,
    fund_case_to_assessment,
    get_success_data,
    issue_deficiency_notice,
    load_of,
    nominate_seat,
    post_ledger_line,
    read_appointment,
    read_case,
    read_registrar,
    register_domain,
    replace_seat,
    run_sweep,
    screen_seat,
    set_clock,
    setup_delivered_case,
    setup_single_member_panel,
    validate_error,
    validate_paginated,
)

OCC1_DOCKET = {
    "iana_id": "IANA-9040",
    "domain_name": "occ1.example",
    "legal_name": "Occ Ltd",
    "country_code": "GB",
    "registrar_name": "Occ1 Registrar",
    "verification_response_hours": 48,
}
OCC2_DOCKET = {
    "iana_id": "IANA-9041",
    "domain_name": "occ2.example",
    "legal_name": "Occ2 Ltd",
    "country_code": "GB",
    "registrar_name": "Occ2 Registrar",
    "verification_response_hours": 48,
}
SWEEP_DOCKET = {
    "iana_id": "IANA-9042",
    "domain_name": "sweep-a.example",
    "legal_name": "Sweep Ltd",
    "country_code": "GB",
    "registrar_name": "Sweep Registrar",
    "verification_response_hours": 48,
}
SELREP_DOCKET = {
    "iana_id": "IANA-9043",
    "domain_name": "selrep.example",
    "legal_name": "Selrep Ltd",
    "country_code": "GB",
    "registrar_name": "Selrep Registrar",
    "verification_response_hours": 48,
}


class TestNominationPinnedToAPreElectionSnapshot:
    def test_the_version_read_before_the_three_member_election_is_refused_at_412(self):
        """PRD §2.7: "If the supplied value does not equal the case's current stored
        `version`, the write is refused with `ERR_STALE_CASE_VERSION` (HTTP 412) and
        nothing at all is persisted."
        PRD §3.5: "When the answer elects a three-member panel, the case is re-shaped
        and **re-priced** on the spot. `respondent_panel_election` moves from `NONE`
        to `THREE`, `required_seat_count` moves from 1 to 3, and the filing fee
        assessment is re-run in its **final** variant with the seat count now
        genuinely 3, setting `fee_variant_applied` to `FINAL`."
        PRD §3.6: "Because nomination competes with other writes on the same case, it
        is one of the two version-pinned operations: `expected_case_version` is
        mandatory and a mismatch is refused with `ERR_STALE_CASE_VERSION`."
        PRD §2.7: "On success the case's `version` advances by one, so a caller
        performing two nominations in sequence must re-read the case between them."

        Design: Corner/cross_cutting_complexity_layers/nomination_refuses_a_case_version_read_before_the_three_member_election
        """
        bundle = setup_delivered_case(
            deemed_received_at="2026-08-01T00:00:00Z", evidence_count=1, **OCC1_DOCKET
        )
        case_id = bundle["case"]["id"]
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-04-01T00:00:00Z", firm_name="Bauer Legal",
            specializations=["TRADEMARK"], max_overlapping_engagements=3,
        )
        before = read_case(case_id)
        cv_pre = before["version"]
        assert before["status"] == "COMMENCED"
        assert before["required_seat_count"] == 1
        assert before["assessed_fee_cents"] == 150000
        assert before["paid_cents"] == 150000

        file_response(bundle, requests_three_member_panel=True)
        after_election = read_case(case_id)
        assert after_election["respondent_panel_election"] == "THREE"
        assert after_election["required_seat_count"] == 3
        assert after_election["assessed_fee_cents"] == 400000
        assert after_election["fee_variant_applied"] == "FINAL"
        assert after_election["version"] > cv_pre

        stale = appointment_payload("PRESIDING", cv_pre, nominated_by="PROVIDER")
        stale["panelist_id"] = panelist["id"]
        refused = api_client.create_appointment(case_id, stale, CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_STALE_CASE_VERSION.value, 412)
        assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_SEAT_NOT_APPLICABLE.value, (
            "the pin is decided before the seat vocabulary is ever consulted"
        )
        _, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0, "a refused nomination writes no row"

        post_ledger_line(case_id, 125000, reference="WIRE-9040-TOPUP")
        post_ledger_line(
            case_id, 125000, payer="RESPONDENT", kind="PANEL_SUPPLEMENT",
            reference="WIRE-9040-SUPP",
        )
        funded = read_case(case_id)
        assert funded["paid_cents"] == 400000
        cv_now = funded["version"]

        fresh = appointment_payload("PRESIDING", cv_now, nominated_by="PROVIDER")
        fresh["panelist_id"] = panelist["id"]
        appointment = get_success_data(
            api_client.create_appointment(case_id, fresh, CASE_MANAGER), 201
        )
        assert appointment["seat"] == "PRESIDING"
        assert appointment["status"] == "NOMINATED"
        assert case_version(case_id) > cv_now


class TestDraftPinnedToAPreReplacementSnapshot:
    def test_the_version_read_before_the_seat_replacement_cannot_open_a_draft(self):
        """PRD §2.7: "A decision draft snapshots the constituted panel and the seat
        count that the eventual vote tally will be measured against; if a seat has
        been replaced since the caller's read, the stored version has moved and the
        draft is refused, so a draft can never be attached to a panel composition that
        no longer holds."
        PRD §3.6: "In every case a successor row for the same `seat` is created in
        `NOMINATED`, chosen by the provider's selector when `replacement_panelist_id`
        is omitted and by name when it is supplied, and the predecessor's
        `replaced_by_appointment_id` is set to point at that successor."
        PRD §3.6: "Vacating a seat that was in `ACCEPTED` unwinds everything that
        acceptance had built: the seat's `honoraria_cents` returns to 0, the neutral's
        `active_case_load` drops by one, the case falls back from `PANEL_CONSTITUTED`
        to `PANEL_APPOINTMENT`, and every decision on the case still in `DRAFT` is
        moved to `VOIDED` with `voided_at` stamped from the clock."
        PRD §2.7: "In both cases the field is mandatory, not optional. If the supplied
        value does not equal the case's current stored `version`, the write is refused
        with `ERR_STALE_CASE_VERSION` (HTTP 412) and nothing at all is persisted."

        Design: Corner/cross_cutting_complexity_layers/decision_draft_refuses_a_case_version_read_before_a_seat_replacement
        """
        bundle = setup_single_member_panel(evidence_count=1, **OCC2_DOCKET)
        case_id = bundle["case"]["id"]
        pan_a = bundle["panelists"][0]
        apt_a = bundle["appointments"][0]
        pan_b = admit_panelist(
            full_name="Luca Rossi", nationality_code="IT",
            roster_admitted_at="2020-06-01T00:00:00Z", max_overlapping_engagements=3,
        )
        constituted = read_case(case_id)
        assert constituted["status"] == "PANEL_CONSTITUTED"
        cv_constituted = constituted["version"]
        assert load_of(pan_a["id"]) == 1

        predecessor = replace_seat(
            apt_a["id"], replacement_panelist_id=pan_b["id"],
            reason="The sole panelist stepped down.",
        )
        assert predecessor["status"] == "REPLACED"
        assert predecessor["honoraria_cents"] == 0
        assert load_of(pan_a["id"]) == 0
        successor_id = predecessor["replaced_by_appointment_id"]
        successor = read_appointment(successor_id)
        assert successor["seat"] == "SOLE"
        assert successor["status"] == "NOMINATED"
        assert successor["panelist_id"] == pan_b["id"]
        assert read_case(case_id)["status"] == "PANEL_APPOINTMENT"

        accepted = screen_seat(successor_id, pan_b["id"])
        assert accepted["status"] == "ACCEPTED"
        reconstituted = read_case(case_id)
        assert reconstituted["status"] == "PANEL_CONSTITUTED"
        assert reconstituted["version"] > cv_constituted

        refused = api_client.create_decision(
            case_id,
            decision_payload(
                cv_constituted, pan_b["id"],
                draft_summary="A draft opened against the pre-replacement panel snapshot.",
            ),
            CASE_MANAGER,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_CASE_VERSION.value, 412)
        assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_CASE_STATE.value, (
            "the case state gate is satisfied, so only the pin can catch this draft"
        )
        _, meta = validate_paginated(
            api_client.list_decisions(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0

        draft = get_success_data(
            api_client.create_decision(
                case_id,
                decision_payload(
                    reconstituted["version"], pan_b["id"],
                    draft_summary="The successor panelist drafts the decision.",
                ),
                CASE_MANAGER,
            ),
            201,
        )
        assert draft["status"] == "DRAFT"
        assert draft["drafted_by_panelist_id"] == pan_b["id"]


class TestOneSweepAdvancesTwoDeadlineFamilies:
    def test_two_unrelated_families_fall_due_together_and_the_rerun_is_a_no_op(self):
        """PRD §2.4: "Time-driven transitions are therefore never spontaneous — they
        are applied by an explicit administrative sweep, which advances everything
        that has become due as of the current clock reading, in a fixed three-stage
        order: first, every `OPEN` deficiency notice whose correction deadline has
        passed expires and closes its case with a full refund; second, every
        `REQUESTED` registrar verification past its due instant becomes `OVERDUE`;
        third, every `COMMENCED` case whose response window and late grace have both
        lapsed without a response records a default."
        PRD §2.4: "It is idempotent — running it twice at the same clock reading
        changes nothing on the second pass and returns all four counters as zero."
        PRD §3.4: "When the deadline sweep finds a verification row still in
        `REQUESTED` whose `due_at` has passed, the row moves to `OVERDUE`, its own
        `escalation_count` advances by one, and the sponsoring registrar's
        `overdue_verification_count` advances by one as well."
        PRD §3.4: "The automatic close always refunds in full, at 100 percent,
        regardless of how far the case had travelled, and its refund lines carry the
        reference `AUTO-CLOSE-REFUND` instead of the withdrawal reference."
        PRD §3.3: "Inflows are positive and refund lines are negative; the magnitude
        must lie between -10000000 and 10000000 and may never be exactly 0."

        Design: Corner/cross_cutting_complexity_layers/one_sweep_advances_two_deadline_families_and_the_second_run_is_a_no_op
        """
        shared = build_docket(**SWEEP_DOCKET)
        registrar_id = shared["registrar"]["id"]
        complainant = shared["complainant"]

        case_a = file_complaint(complainant, shared["domain"])
        assert_all_mandatory_grounds(case_a, complainant, evidence_count=1)
        post_ledger_line(case_a["id"], case_a["complainant_share_cents"], reference="WIRE-9042-A")
        clear_compliance(case_a["id"], headers=CASE_MANAGER_ALT, reviewer_notes="Complete.")
        ver_a = first_verification(case_a["id"])
        assert ver_a["status"] == "REQUESTED"
        assert ver_a["due_at"] == "2026-08-03T00:00:00.000Z"
        assert ver_a["escalation_count"] == 0

        domain_b = register_domain(registrar_id, "sweep-b.example")
        case_b = file_complaint(complainant, domain_b, remedy_requested="CANCELLATION")
        post_ledger_line(case_b["id"], 150000, reference="WIRE-9042-B")
        notice_b = issue_deficiency_notice(
            case_b["id"],
            deficiency_codes=["MISSING_GROUND", "MISSING_SIGNATURE"],
            correction_days=5,
        )
        assert notice_b["status"] == "OPEN"
        assert notice_b["correction_deadline_at"] == "2026-08-06T00:00:00.000Z"

        set_clock("2026-08-06T00:00:01Z")
        first = run_sweep()
        assert first["expired_notice_count"] == 1
        assert first["overdue_verification_count"] == 1
        assert first["defaulted_case_count"] == 0, (
            "neither case ever commenced, so the third stage finds nothing"
        )
        assert first["closed_case_count"] == 1

        swept_ver = first_verification(case_a["id"])
        assert swept_ver["status"] == "OVERDUE"
        assert swept_ver["escalation_count"] == 1
        assert read_registrar(registrar_id)["overdue_verification_count"] == 1

        notices, notice_meta = validate_paginated(
            api_client.list_deficiency_notices(
                case_b["id"], CASE_MANAGER, params={"limit": 10, "offset": 0}
            )
        )
        assert notice_meta["total_count"] == 1
        assert notices[0]["status"] == "EXPIRED"
        closed_b = read_case(case_b["id"])
        assert closed_b["status"] == "ADMIN_CLOSED"
        assert closed_b["closed_at"] == "2026-08-06T00:00:01.000Z"
        assert closed_b["refiling_bar_until"] == "2026-09-05T00:00:01.000Z"
        assert closed_b["paid_cents"] == 0
        ledger, ledger_meta = validate_paginated(
            api_client.list_fee_transactions(
                case_b["id"], CASE_MANAGER, params={"limit": 10, "offset": 0}
            )
        )
        assert ledger_meta["total_count"] == 2
        assert ledger[1]["kind"] == "REFUND"
        assert ledger[1]["amount_cents"] == -150000, "a refund line carries the negative"
        assert ledger[1]["reference"] == "AUTO-CLOSE-REFUND"
        assert ledger[1]["payer"] == "COMPLAINANT"

        second = run_sweep()
        assert all(
            second[counter] == 0
            for counter in (
                "expired_notice_count", "overdue_verification_count",
                "defaulted_case_count", "closed_case_count",
            )
        ), "the second pass at the same clock reading changes nothing"
        assert read_case(case_a["id"])["status"] == "VERIFICATION_PENDING"
        assert first_verification(case_a["id"])["escalation_count"] == 1
        assert read_registrar(registrar_id)["overdue_verification_count"] == 1
        assert read_case(case_b["id"])["status"] == "ADMIN_CLOSED"


class TestUnnamedReplacementFallsToTheSelector:
    def test_the_vacated_holder_is_a_candidate_again_and_loses_only_on_seniority(self):
        """PRD §3.6: "In every case a successor row for the same `seat` is created in
        `NOMINATED`, chosen by the provider's selector when `replacement_panelist_id`
        is omitted and by name when it is supplied, and the predecessor's
        `replaced_by_appointment_id` is set to point at that successor."
        PRD §3.6: "When `panelist_id` is omitted the provider selects one itself, and
        the resulting row records `selected_by_provider` as true; when the caller names
        one, that flag is false, but the named candidate is still put through the
        identical eligibility filter."
        PRD §3.6: "And the candidate must not already hold a row on this same case in
        `NOMINATED`, `WAIVER_PENDING` or `ACCEPTED` — a neutral cannot occupy two seats
        on one panel, though a neutral whose earlier row on the case ended in
        `DECLINED`, `CONFLICTED` or `REPLACED` may be nominated afresh."
        PRD §3.6: "Otherwise the set is ordered by three keys in strict sequence:
        ascending `active_case_load` first, so the least-burdened neutral is preferred;
        ascending `roster_admitted_at` second, so seniority on the roster breaks a load
        tie; and ascending `created_at` third as the final tiebreak."
        PRD §3.6: "Vacating a seat that was in `ACCEPTED` unwinds everything that
        acceptance had built: the seat's `honoraria_cents` returns to 0, the neutral's
        `active_case_load` drops by one, the case falls back from `PANEL_CONSTITUTED`
        to `PANEL_APPOINTMENT`, and every decision on the case still in `DRAFT` is
        moved to `VOIDED` with `voided_at` stamped from the clock."

        Design: Corner/cross_cutting_complexity_layers/an_unnamed_replacement_falls_to_the_selector_and_the_vacated_seat_holder_loses_on_seniority
        """
        bundle = setup_delivered_case(
            deemed_received_at="2026-08-01T00:00:00Z", evidence_count=1, **SELREP_DOCKET
        )
        case_id = bundle["case"]["id"]
        file_response(bundle)
        fund_case_to_assessment(case_id)

        pan_a = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2022-01-01T00:00:00Z", firm_name="Bauer Legal",
            specializations=["TRADEMARK"], max_overlapping_engagements=3,
        )
        pan_b = admit_panelist(
            full_name="Luca Rossi", nationality_code="IT",
            roster_admitted_at="2019-01-01T00:00:00Z",
            specializations=["DOMAIN_NAMES"], max_overlapping_engagements=3,
        )
        pan_c = admit_panelist(
            full_name="Elena Ruiz", nationality_code="ES",
            roster_admitted_at="2021-01-01T00:00:00Z",
            specializations=["TRADEMARK"], max_overlapping_engagements=3,
        )
        assert [load_of(p["id"]) for p in (pan_a, pan_b, pan_c)] == [0, 0, 0]

        named = nominate_seat(case_id, "SOLE", pan_a["id"])
        assert named["selected_by_provider"] is False
        seated = screen_seat(named["id"], pan_a["id"])
        assert seated["status"] == "ACCEPTED"
        assert seated["honoraria_cents"] == 105000
        assert load_of(pan_a["id"]) == 1
        assert read_case(case_id)["status"] == "PANEL_CONSTITUTED"

        predecessor = replace_seat(
            named["id"],
            reason="The seated panelist withdrew and the provider takes the next eligible neutral.",
        )
        assert predecessor["id"] == named["id"], "the response reports the predecessor"
        assert predecessor["status"] == "REPLACED"
        assert predecessor["honoraria_cents"] == 0
        assert predecessor["panelist_id"] == pan_a["id"]
        assert load_of(pan_a["id"]) == 0, "the vacated holder is unburdened again"

        successor = read_appointment(predecessor["replaced_by_appointment_id"])
        assert successor["seat"] == "SOLE"
        assert successor["status"] == "NOMINATED"
        assert successor["selected_by_provider"] is True
        assert successor["panelist_id"] == pan_b["id"], (
            "all three sit at load 0, so the seniority key picks the 2019 admission"
        )
        assert successor["panelist_id"] != pan_a["id"]
        assert successor["panelist_id"] != pan_c["id"]
        assert load_of(pan_b["id"]) == 0, "a nominated seat is not yet an engagement"

        rows, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {named["id"], successor["id"]}
        assert read_case(case_id)["status"] == "PANEL_APPOINTMENT"
