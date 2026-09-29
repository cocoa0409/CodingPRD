"""Declared initial states, laps around a cycle, and the transitions that are refused."""
from test_helpers import (
    VERIFIED_REGISTRANT_EMAIL,
    ApiErrorId,
    CASE_MANAGER,
    CASE_MANAGER_ALT,
    PROVIDER_ADMIN,
    admit_eligible_panelists,
    admit_panelist,
    answer_verification,
    api_client,
    assert_notification,
    assert_verification,
    build_docket,
    cast_seat_vote,
    conflict_screening_payload,
    dispatch_notification,
    draft_decision,
    file_complaint,
    file_court_challenge,
    file_response,
    get_success_data,
    implement_decision,
    issue_decision,
    issue_deficiency_notice,
    make_complainant_headers,
    make_panelist_headers,
    make_registrar_headers,
    make_respondent_headers,
    nominate_seat,
    read_appointment,
    read_case,
    read_complainant,
    read_decision,
    read_domain,
    read_panelist,
    read_registrar,
    record_delivery,
    replace_seat,
    resolve_court_challenge,
    response_payload,
    run_sweep,
    seat_panelist_cleanly,
    set_clock,
    setup_commenced_case,
    setup_delivered_case,
    setup_notification_pending_case,
    setup_responded_case,
    setup_verification_pending_case,
    validate_error,
    validate_paginated,
    waiver_payload,
    withdraw_case,
)


class TestDeclaredInitialStates:
    def test_a_fresh_domain_case_and_notice_each_open_in_their_own_initial_state(self):
        """PRD §3.1: "A newly registered domain starts at `lock_status` `UNLOCKED` with
        both `locked_at` and `executed_at` null."
        PRD §3.2: "An accepted filing lands in `status` `FILED` with `version` 1, mints
        its `case_number`, and sets `respondent_panel_election` to `NONE`."
        PRD §3.4: "The notice is created in `status` `OPEN`, stamps `issued_at` from the
        logical clock, records the issuing case manager in `issued_by_user_id`, sets
        `round_number` to the case's `deficiency_round_count` plus one — never exceeding
        2 — and sets `correction_deadline_at` to `issued_at` plus `correction_days` days."
        PRD §3.4: "The case moves from `FILED` to `DEFICIENT`, its
        `deficiency_round_count` advances by one, and the issuer's identity is copied
        onto the case as `last_deficiency_issuer_user_id`."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        docket = build_docket(
            iana_id="IANA-9013", domain_name="init.example",
            country_code="GB", legal_name="Init Ltd", registrar_name="Init Registrar",
        )
        domain = docket["domain"]
        assert domain["lock_status"] == "UNLOCKED"
        assert domain["locked_at"] is None
        assert domain["executed_at"] is None

        case = file_complaint(docket["complainant"], domain)
        assert case["status"] == "FILED"
        assert case["version"] == 1
        assert case["closed_at"] is None
        assert case["refiling_bar_until"] is None
        assert case["deficiency_round_count"] == 0
        assert case["last_deficiency_issuer_user_id"] is None

        notice = issue_deficiency_notice(
            case["id"], deficiency_codes=["MISSING_MARK_EVIDENCE"]
        )
        assert notice["status"] == "OPEN"
        assert notice["round_number"] == 1
        assert notice["cured_at"] is None

        deficient = read_case(case["id"])
        assert deficient["status"] == "DEFICIENT", (
            "FILED really was the state the notice moved the case out of"
        )
        assert deficient["deficiency_round_count"] == 1
        assert read_domain(domain["id"])["lock_status"] == "UNLOCKED"


class TestVerificationLapsTheOverdueCycle:
    def test_two_laps_accumulate_escalations_while_the_registrar_counter_oscillates(self):
        """PRD §3.4: "When the deadline sweep finds a verification row still in
        `REQUESTED` whose `due_at` has passed, the row moves to `OVERDUE`, its own
        `escalation_count` advances by one, and the sponsoring registrar's
        `overdue_verification_count` advances by one as well."
        PRD §3.4: "The same row returns to `REQUESTED` with a fresh `requested_at` taken
        from the current clock and a fresh `due_at` that many hours later, again drawn
        from the registrar's `verification_response_hours`, and the registrar's
        `overdue_verification_count` drops back by one — the registrar is credited for
        the re-request even though the row's own `escalation_count` keeps accumulating
        across laps."
        PRD §2.4: "It is idempotent — running it twice at the same clock reading changes
        nothing on the second pass and returns all four counters as zero."
        PRD §3.4: "A valid answer moves the row to `RESPONDED` with `responded_at`
        stamped from the clock; if it was answered out of `OVERDUE`, the registrar's
        `overdue_verification_count` drops by one at that moment."

        Design: Corner/state_machines/verification_cycles_requested_overdue_requested_and_accumulates_escalations
        """
        bundle = setup_verification_pending_case(
            verification_response_hours=48, iana_id="IANA-9014",
            domain_name="verif.example", country_code="GB",
            legal_name="Verif Ltd", registrar_name="Verif Registrar",
        )
        case_id = bundle["case"]["id"]
        registrar_id = bundle["registrar"]["id"]
        verification = bundle["verification"]
        assert_verification(verification)
        assert verification["status"] == "REQUESTED"
        assert verification["requested_at"] == "2026-08-01T00:00:00.000Z"
        assert verification["due_at"] == "2026-08-03T00:00:00.000Z"
        assert verification["escalation_count"] == 0

        set_clock("2026-08-03T00:00:00Z")
        edge = run_sweep()
        assert edge["overdue_verification_count"] == 0
        rows, meta = validate_paginated(
            api_client.list_registrar_verifications(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "REQUESTED"
        assert rows[0]["escalation_count"] == 0

        set_clock("2026-08-03T00:00:01Z")
        first_lap = run_sweep()
        assert first_lap["overdue_verification_count"] == 1
        rows, _ = validate_paginated(
            api_client.list_registrar_verifications(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert rows[0]["status"] == "OVERDUE"
        assert rows[0]["escalation_count"] == 1
        assert read_registrar(registrar_id)["overdue_verification_count"] == 1
        assert read_case(case_id)["status"] == "VERIFICATION_PENDING"

        repeat = run_sweep()
        assert repeat["overdue_verification_count"] == 0
        assert repeat["expired_notice_count"] == 0
        assert repeat["defaulted_case_count"] == 0
        assert repeat["closed_case_count"] == 0
        rows, _ = validate_paginated(
            api_client.list_registrar_verifications(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert rows[0]["escalation_count"] == 1

        reactivated = get_success_data(
            api_client.rerequest_verification(case_id, {}, CASE_MANAGER)
        )
        assert reactivated["id"] == verification["id"], "the cycle reuses one row"
        assert reactivated["status"] == "REQUESTED"
        assert reactivated["requested_at"] == "2026-08-03T00:00:01.000Z"
        assert reactivated["due_at"] == "2026-08-05T00:00:01.000Z"
        assert reactivated["escalation_count"] == 1
        assert read_registrar(registrar_id)["overdue_verification_count"] == 0
        _, meta = validate_paginated(
            api_client.list_registrar_verifications(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1

        set_clock("2026-08-05T00:00:02Z")
        second_lap = run_sweep()
        assert second_lap["overdue_verification_count"] == 1
        rows, _ = validate_paginated(
            api_client.list_registrar_verifications(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert rows[0]["status"] == "OVERDUE"
        assert rows[0]["escalation_count"] == 2, "escalations accumulate across laps"
        assert read_registrar(registrar_id)["overdue_verification_count"] == 1

        answered = answer_verification(bundle)
        assert answered["status"] == "RESPONDED"
        assert answered["responded_at"] == "2026-08-05T00:00:02.000Z"
        assert answered["escalation_count"] == 2
        assert read_registrar(registrar_id)["overdue_verification_count"] == 0
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "LOCKED"
        assert read_case(case_id)["status"] == "NOTIFICATION_PENDING"


class TestUnansweredWindowDefaultsTheCase:
    def test_the_default_fires_one_second_past_the_grace_and_the_repeat_sweep_is_a_no_op(self):
        """PRD §3.5: "A respondent who never answers defaults."
        PRD §3.5: "When the deadline sweep finds a `COMMENCED` case with no answer on
        file and the clock past `response_due_at` plus the 24-hour grace, the case moves
        from `COMMENCED` to `DEFAULT` and `default_recorded` is set to true."
        PRD §2.4: "It is idempotent — running it twice at the same clock reading changes
        nothing on the second pass and returns all four counters as zero."

        Design: Corner/state_machines/unanswered_response_window_defaults_the_case_and_the_sweep_is_idempotent
        """
        bundle = setup_delivered_case(
            deemed_received_at="2026-08-01T00:00:00Z", iana_id="IANA-9015",
            domain_name="deflt.example", country_code="GB",
            legal_name="Deflt Ltd", registrar_name="Deflt Registrar",
        )
        case_id = bundle["case"]["id"]
        assert bundle["case"]["status"] == "COMMENCED"
        assert bundle["case"]["response_due_at"] == "2026-08-21T00:00:00.000Z"
        assert bundle["case"]["deadline_variant_applied"] == "FINAL"
        version_before = bundle["case"]["version"]

        set_clock("2026-08-22T00:00:00Z")
        edge = run_sweep()
        assert edge["defaulted_case_count"] == 0
        at_edge = read_case(case_id)
        assert at_edge["status"] == "COMMENCED"
        assert at_edge["default_recorded"] is False
        assert at_edge["version"] == version_before

        set_clock("2026-08-22T00:00:01Z")
        defaulting = run_sweep()
        assert defaulting["defaulted_case_count"] == 1
        defaulted = read_case(case_id)
        assert defaulted["status"] == "DEFAULT"
        assert defaulted["default_recorded"] is True
        assert defaulted["version"] == version_before + 1

        repeat = run_sweep()
        assert repeat["defaulted_case_count"] == 0
        assert repeat["expired_notice_count"] == 0
        assert repeat["overdue_verification_count"] == 0
        assert repeat["closed_case_count"] == 0
        after = read_case(case_id)
        assert after["status"] == "DEFAULT"
        assert after["version"] == defaulted["version"]
        assert after["response_due_at"] == "2026-08-21T00:00:00.000Z", (
            "recording a default does not move the deadline"
        )


class TestUndeliverableSelfLoop:
    def test_a_second_attempt_reprojects_from_itself_and_a_third_over_a_delivery_is_refused(self):
        """PRD §3.5: "The attempt is created in `status` `SENT` with `dispatched_at`
        stamped from the clock, `attempt_number` 1 on the first dispatch, and
        `transmission_allowance_days` fixed by the channel: 0 days for `EMAIL`, 2 days
        for `COURIER`, and 5 days for `POSTAL`."
        PRD §3.5: "On `UNDELIVERABLE`, the supplied `failure_reason` is stored and the
        deadline is left standing at the provisional value projected from that attempt,
        until and unless a further attempt is dispatched."
        PRD §3.5: "Because the new attempt becomes the highest-numbered one, the
        provisional projection is recomputed from its own `dispatched_at` and
        `transmission_allowance_days`, which is how a switch from email to postal service
        moves the deadline outward mid-proceeding."
        PRD §3.5: "It requires the case to be in `COMMENCED` and the highest-numbered
        attempt to be in `UNDELIVERABLE`; re-dispatching over an attempt still in `SENT`
        or already `DELIVERED` is refused with `ERR_INVALID_CASE_STATE`."

        Design: Corner/state_machines/undeliverable_attempt_loops_the_case_on_commenced_and_re_anchors_the_deadline
        """
        bundle = setup_commenced_case(
            channel="POSTAL", iana_id="IANA-9016", domain_name="undeliv.example",
            country_code="GB", legal_name="Undeliv Ltd", registrar_name="Undeliv Registrar",
        )
        case_id = bundle["case"]["id"]
        first = bundle["notification"]
        assert_notification(first)
        assert first["attempt_number"] == 1
        assert first["transmission_allowance_days"] == 5
        postal = read_case(case_id)
        assert postal["status"] == "COMMENCED"
        assert postal["response_due_at"] == "2026-08-26T00:00:00.000Z"
        assert postal["deadline_variant_applied"] == "PROVISIONAL"

        failed = record_delivery(
            bundle, "UNDELIVERABLE",
            failure_reason="Addressee unknown at the postal address.",
        )
        assert failed["status"] == "UNDELIVERABLE"
        assert failed["deemed_received_at"] is None
        assert read_case(case_id)["response_due_at"] == "2026-08-26T00:00:00.000Z"

        set_clock("2026-08-05T00:00:00Z")
        second = dispatch_notification(case_id, "EMAIL")
        assert second["attempt_number"] == 2
        assert second["transmission_allowance_days"] == 0
        looped = read_case(case_id)
        assert looped["status"] == "COMMENCED", "the self-loop does not leave the state"
        assert looped["response_due_at"] == "2026-08-25T00:00:00.000Z", (
            "the discarded postal projection is not retained as a floor"
        )

        bundle["notification"] = second
        delivered = record_delivery(bundle, "DELIVERED", deemed_received_at="2026-08-06T00:00:00Z")
        assert delivered["status"] == "DELIVERED"
        reanchored = read_case(case_id)
        assert reanchored["response_due_at"] == "2026-08-26T00:00:00.000Z"
        assert reanchored["deadline_variant_applied"] == "FINAL"

        refused = api_client.create_notification(
            case_id, {"channel": "EMAIL", "address": VERIFIED_REGISTRANT_EMAIL}, CASE_MANAGER
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_CASE_STATE.value, 409)
        rows, meta = validate_paginated(
            api_client.list_notifications(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == ["UNDELIVERABLE", "DELIVERED"]
        assert [row["attempt_number"] for row in rows] == [1, 2]


class TestWithdrawalBeforeCommencement:
    def test_the_fifty_percent_band_mints_one_refund_line_and_tidies_the_proceeding_up(self):
        """PRD §3.3: "A case in `VERIFICATION_PENDING` or `NOTIFICATION_PENDING` refunds
        half — 50 percent."
        PRD §3.3: "For each of those two payers, the provider sums that payer's
        contributions on the ledger, multiplies by the applicable percentage, rounds half
        up to a whole cent, and — only when the result is strictly greater than zero —
        mints one refund line for that payer carrying the negative of that amount and the
        reference `WITHDRAWAL-REFUND`."
        PRD §3.3: "The case moves to `WITHDRAWN`, its `closed_at` is stamped at the
        current logical-clock instant, and its `refiling_bar_until` is set 30 days later."
        PRD §3.3: "Any registrar verification in `REQUESTED` or in `OVERDUE` becomes
        `OVERDUE`. A domain sitting in `LOCKED` returns to `UNLOCKED`. The complainant's
        `open_case_count` drops by one."

        Design: Corner/state_machines/withdrawal_before_commencement_refunds_half_and_unlocks_the_domain
        """
        bundle = setup_notification_pending_case(
            iana_id="IANA-9017", domain_name="wdraw.example", country_code="GB",
            legal_name="Wdraw Ltd", registrar_name="Wdraw Registrar",
        )
        case_id = bundle["case"]["id"]
        complainant_id = bundle["complainant"]["id"]
        assert bundle["case"]["status"] == "NOTIFICATION_PENDING"
        assert bundle["case"]["paid_cents"] == 150000
        assert read_complainant(complainant_id)["open_case_count"] == 1
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "LOCKED"

        set_clock("2026-08-04T00:00:00Z")
        withdrawn = withdraw_case(
            case_id, complainant_id, reason="Settled directly with the registrant."
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["closed_at"] == "2026-08-04T00:00:00.000Z"
        assert withdrawn["refiling_bar_until"] == "2026-09-03T00:00:00.000Z"
        assert withdrawn["paid_cents"] == 75000
        assert withdrawn["complainant_paid_cents"] == 75000
        assert withdrawn["respondent_paid_cents"] == 0

        rows, meta = validate_paginated(
            api_client.list_fee_transactions(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2
        assert rows[0]["amount_cents"] == 150000
        assert rows[0]["kind"] == "FILING_FEE"
        assert rows[1]["amount_cents"] == -75000
        assert rows[1]["kind"] == "REFUND"
        assert rows[1]["payer"] == "COMPLAINANT"
        assert rows[1]["reference"] == "WITHDRAWAL-REFUND"
        assert all(row["payer"] != "RESPONDENT" for row in rows), (
            "a payer who contributed nothing gets no refund line"
        )

        assert read_domain(bundle["domain"]["id"])["lock_status"] == "UNLOCKED"
        assert read_complainant(complainant_id)["open_case_count"] == 0
        verifications, _ = validate_paginated(
            api_client.list_registrar_verifications(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert verifications[0]["status"] == "RESPONDED", (
            "only a request still open is pushed to overdue by a withdrawal"
        )


class TestWithdrawalWindowShutsAtAppointment:
    def test_a_nominated_seat_closes_the_window_with_its_own_refusal(self):
        """PRD §3.3: "Withdrawal is admitted from `FILED`, `DEFICIENT`,
        `VERIFICATION_PENDING`, `NOTIFICATION_PENDING`, `COMMENCED`, `RESPONSE_RECEIVED`
        and `DEFAULT`; attempting it from `PANEL_APPOINTMENT` or any later status is
        refused with `ERR_WITHDRAWAL_WINDOW_CLOSED`, and a complainant attempting it on
        someone else's case is refused with `ERR_NOT_OWNER`."
        PRD §3.6: "Nomination is a case manager's act on a case in `RESPONSE_RECEIVED` or
        `DEFAULT` for the first seat — which moves the case to `PANEL_APPOINTMENT` — or on
        a case already in `PANEL_APPOINTMENT` for the seats that follow."

        Design: Corner/state_machines/withdrawal_is_refused_once_the_panel_appointment_stage_is_reached
        """
        bundle = setup_responded_case(
            iana_id="IANA-9018", domain_name="wbar.example", country_code="GB",
            legal_name="Wbar Ltd", registrar_name="Wbar Registrar",
        )
        case_id = bundle["case"]["id"]
        complainant_id = bundle["complainant"]["id"]
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-04-01T00:00:00Z", firm_name="Bauer Legal",
        )
        appointment = nominate_seat(case_id, "SOLE", panelist["id"])
        assert appointment["status"] == "NOMINATED"
        before = read_case(case_id)
        assert before["status"] == "PANEL_APPOINTMENT"

        refused = api_client.withdraw_case(
            case_id,
            {"reason": "Complainant changed its mind after the panel was nominated."},
            make_complainant_headers(complainant_id),
        )
        validate_error(refused, ApiErrorId.ERR_WITHDRAWAL_WINDOW_CLOSED.value, 409)

        after = read_case(case_id)
        assert after["status"] == "PANEL_APPOINTMENT"
        assert after["version"] == before["version"]
        assert after["closed_at"] is None
        assert after["refiling_bar_until"] is None
        _, meta = validate_paginated(
            api_client.list_fee_transactions(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1, "no refund cascade ran"
        assert read_appointment(appointment["id"])["status"] == "NOMINATED"
        assert read_complainant(complainant_id)["open_case_count"] == 1


class TestSecondResponseIsADuplicate:
    def test_the_duplicate_guard_outranks_the_state_the_first_answer_created(self):
        """PRD §3.5: "At most one answer is ever accepted: a second attempt is refused
        with `ERR_RESPONSE_ALREADY_FILED`, and that refusal is deliberately checked ahead
        of the state gates, so the duplicate is reported as a duplicate even on a case
        that has already moved on to `RESPONSE_RECEIVED`."
        PRD §2.10: "**Duplicate response.** A case carries at most one response; a second
        filing is `ERR_RESPONSE_ALREADY_FILED`. This check deliberately sits ahead of the
        state gates that follow, because filing a response moves the case out of
        `COMMENCED`: were it ordered later, a duplicate filing would always surface as a
        state error and this rule would be unreachable."
        PRD §3.5: "When the answer elects a three-member panel, the case is re-shaped and
        **re-priced** on the spot."

        Design: Corner/state_machines/second_response_on_the_same_case_is_reported_as_a_duplicate
        """
        bundle = setup_responded_case(
            iana_id="IANA-9019", domain_name="dupresp.example", country_code="GB",
            legal_name="Dupresp Ltd", registrar_name="Dupresp Registrar",
        )
        case_id = bundle["case"]["id"]
        assert bundle["case"]["status"] == "RESPONSE_RECEIVED"

        refused = api_client.create_response(
            case_id,
            response_payload(
                VERIFIED_REGISTRANT_EMAIL,
                content_summary=(
                    "A second, longer submission that the registrant would prefer the "
                    "panel to read instead."
                ),
                requests_three_member_panel=True,
            ),
            make_respondent_headers(),
        )
        validate_error(refused, ApiErrorId.ERR_RESPONSE_ALREADY_FILED.value, 409)
        assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_CASE_NOT_IN_RESPONSE_WINDOW.value

        rows, meta = validate_paginated(
            api_client.list_responses(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert rows[0]["requests_three_member_panel"] is False
        after = read_case(case_id)
        assert after["status"] == "RESPONSE_RECEIVED"
        assert after["required_seat_count"] == 1
        assert after["assessed_fee_cents"] == 150000
        assert after["respondent_panel_election"] == "NONE"
        assert after["respondent_share_cents"] == 0


class TestSettledSeatsRefuseFurtherMoves:
    def test_a_waiver_a_rescreening_and_a_second_replace_all_hit_the_appointment_gate(self):
        """PRD §3.6: "A waivable conflict is cleared by a case manager, not by the
        neutral. The seat must be in `WAIVER_PENDING`, and its `conflict_score` must be
        below 60, or the request is refused with `ERR_CONFLICT_NOT_WAIVABLE`."
        PRD §3.6: "The nominated neutral then files conflict disclosures on their own
        seat; another panelist attempting it is refused with `ERR_NOT_SEAT_HOLDER`, and a
        seat not in `NOMINATED` is refused with `ERR_INVALID_APPOINTMENT_STATE`."
        PRD §2.10: "**State gates.** The target case must be in a status from which the
        operation is defined (`ERR_INVALID_CASE_STATE`); a response specifically requires
        a case in `COMMENCED` (`ERR_CASE_NOT_IN_RESPONSE_WINDOW`); the target appointment
        must be in an admitting status (`ERR_INVALID_APPOINTMENT_STATE`); the target
        decision must be in an admitting status (`ERR_INVALID_DECISION_STATE`); a decision
        may not be published twice (`ERR_ALREADY_PUBLISHED`); a case may only be withdrawn
        from a pre-appointment status (`ERR_WITHDRAWAL_WINDOW_CLOSED`)."
        PRD §3.6: "The predecessor's fate depends on where it stood: a seat in
        `NOMINATED` or `WAIVER_PENDING` becomes `DECLINED`, while a seat in `CONFLICTED`
        or `ACCEPTED` becomes `REPLACED`."

        Design: Corner/state_machines/waiver_rescreening_and_double_replacement_are_refused_on_settled_seats
        """
        bundle = setup_responded_case(
            iana_id="IANA-9020", domain_name="aptstate.example", country_code="GB",
            legal_name="Aptstate Ltd", registrar_name="Aptstate Registrar",
        )
        case_id = bundle["case"]["id"]
        incumbent, successor_panelist = admit_eligible_panelists(2)
        seat = seat_panelist_cleanly(case_id, "SOLE", incumbent)
        assert seat["status"] == "ACCEPTED"
        assert float(seat["conflict_score"]) == 0.00
        assert read_case(case_id)["status"] == "PANEL_CONSTITUTED"

        waiver = api_client.record_waiver(seat["id"], waiver_payload(), CASE_MANAGER)
        validate_error(waiver, ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409)

        rescreen = api_client.screen_conflict(
            seat["id"],
            conflict_screening_payload(
                disclosed_prior_representation=True, prior_appointments_with_complainant=4
            ),
            make_panelist_headers(incumbent["id"]),
        )
        validate_error(rescreen, ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409)
        mid = read_appointment(seat["id"])
        assert mid["status"] == "ACCEPTED"
        assert float(mid["conflict_score"]) == 0.00, (
            "the disclosures in the rejected body were never scored"
        )

        predecessor = replace_seat(
            seat["id"], replacement_panelist_id=successor_panelist["id"],
            reason="Panelist withdrew for personal reasons.",
        )
        assert predecessor["status"] == "REPLACED"
        successor = read_appointment(predecessor["replaced_by_appointment_id"])
        assert successor["status"] == "NOMINATED"
        assert successor["panelist_id"] == successor_panelist["id"]
        assert successor["seat"] == "SOLE"

        second_replace = api_client.replace_appointment(
            seat["id"], {"reason": "A second attempt to vacate the very same row."}, CASE_MANAGER
        )
        validate_error(second_replace, ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409)

        rows, meta = validate_paginated(
            api_client.list_appointments(CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2, "the refused second replace minted no third row"
        assert [row["status"] for row in rows] == ["REPLACED", "NOMINATED"]
        assert read_panelist(incumbent["id"])["active_case_load"] == 0
        assert read_case(case_id)["status"] == "PANEL_APPOINTMENT"


class TestDismissedChallengeRestartsTheWait:
    def _issued_then_stayed(self):
        bundle = setup_responded_case(
            iana_id="IANA-9021", domain_name="stay.example", country_code="GB",
            legal_name="Stay Ltd", registrar_name="Stay Registrar",
        )
        case_id = bundle["case"]["id"]
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-04-01T00:00:00Z",
        )
        appointment = seat_panelist_cleanly(case_id, "SOLE", panelist)
        decision = draft_decision(
            case_id, panelist["id"],
            draft_summary=(
                "The panel finds the name identical to the mark and registered in bad "
                "faith; transfer is ordered."
            ),
        )
        cast_seat_vote(
            decision["id"], panelist["id"], "SOLE", "TRANSFER",
            rationale="All three elements are made out on the record.",
        )
        set_clock("2026-08-10T09:00:00Z")
        bundle["decision"] = issue_decision(decision["id"])
        bundle["panelists"] = [panelist]
        bundle["appointments"] = [appointment]
        bundle["case"] = read_case(case_id)
        return bundle

    def test_the_lifted_stay_recomputes_ten_fresh_business_days_over_the_holiday(self):
        """PRD §3.8: "A `DISMISSED` or `WITHDRAWN` disposition lifts the stay. The
        challenge takes that status with `resolved_at` stamped from the clock, the
        decision returns from `STAYED` to `ISSUED`, and the waiting period is recomputed
        **in full** from `resolved_at` — a fresh ten business days, with no credit for the
        days that elapsed before the stay."
        PRD §2.4: "The implementation waiting period alone is counted in provider
        business days, which skips Saturdays, skips Sundays, and skips every date on the
        provider holiday calendar. That calendar contains exactly one date: `2026-09-07`."
        PRD §3.8: "A provider administrator records how the court disposed of a challenge
        still in `FILED`; a challenge already resolved is refused with
        `ERR_INVALID_CASE_STATE`."
        PRD §3.8: "Once the clock is strictly past it, the registrar may act and the
        challenge window has shut — an attempt to file is refused with
        `ERR_CHALLENGE_WINDOW_CLOSED`."

        Design: Corner/state_machines/dismissed_challenge_lifts_the_stay_and_restarts_the_full_waiting_period
        """
        bundle = self._issued_then_stayed()
        decision_id = bundle["decision"]["id"]
        case_id = bundle["case"]["id"]
        assert bundle["decision"]["outcome"] == "TRANSFER"
        assert bundle["decision"]["issued_at"] == "2026-08-10T09:00:00.000Z"
        assert bundle["decision"]["implementation_deadline_at"] == "2026-08-24T09:00:00.000Z"

        set_clock("2026-08-20T00:00:00Z")
        challenge = file_court_challenge(bundle, "RESPONDENT", docket_number="3:26-cv-00921")
        assert challenge["status"] == "FILED"
        assert challenge["filed_at"] == "2026-08-20T00:00:00.000Z"
        stayed = read_decision(decision_id)
        assert stayed["status"] == "STAYED"
        assert stayed["implementation_deadline_at"] == "2026-08-24T09:00:00.000Z"
        assert read_case(case_id)["status"] == "STAYED"

        set_clock("2026-08-25T12:00:00Z")
        resolved = resolve_court_challenge(
            challenge["id"], "DISMISSED",
            resolution_note="The court dismissed the action for want of jurisdiction.",
        )
        assert resolved["status"] == "DISMISSED"
        assert resolved["resolved_at"] == "2026-08-25T12:00:00.000Z"
        relifted = read_decision(decision_id)
        assert relifted["status"] == "ISSUED"
        assert relifted["voided_at"] is None
        assert relifted["implementation_deadline_at"] == "2026-09-09T12:00:00.000Z"
        assert read_case(case_id)["status"] == "IMPLEMENTATION_WAITING"

        again = api_client.resolve_court_challenge(
            challenge["id"],
            {"outcome": "SUSTAINED", "resolution_note": "A second bite at the same docket."},
            PROVIDER_ADMIN,
        )
        validate_error(again, ApiErrorId.ERR_INVALID_CASE_STATE.value, 409)
        rows, meta = validate_paginated(
            api_client.list_court_challenges(decision_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "DISMISSED"
        assert rows[0]["resolved_at"] == "2026-08-25T12:00:00.000Z"
        assert rows[0]["filed_by"] == "RESPONDENT"
        assert rows[0]["docket_number"] == "3:26-cv-00921"

        set_clock("2026-09-09T12:00:00Z")
        early = api_client.implement_decision(
            decision_id, {"registrar_action_reference": "TOO-EARLY-9021"},
            make_registrar_headers(bundle["registrar"]["id"]),
        )
        validate_error(early, ApiErrorId.ERR_IMPLEMENTATION_PERIOD_ACTIVE.value, 409)

        set_clock("2026-09-09T12:00:01Z")
        implemented = implement_decision(bundle, registrar_action_reference="TRANSFER-9021")
        assert implemented["status"] == "IMPLEMENTED"
        assert implemented["implemented_at"] == "2026-09-09T12:00:01.000Z"
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "TRANSFER_EXECUTED"
        assert read_appointment(bundle["appointments"][0]["id"])["status"] == "DISCHARGED"
        closed = read_case(case_id)
        assert closed["status"] == "IMPLEMENTED"
        assert closed["closed_at"] == "2026-09-09T12:00:01.000Z"
