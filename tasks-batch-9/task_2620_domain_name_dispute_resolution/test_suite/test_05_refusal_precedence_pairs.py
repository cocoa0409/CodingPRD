"""Pairs of live rules on one call, and the ladder that picks between them."""
from test_helpers import (
    VERIFIED_REGISTRANT_EMAIL,
    ApiErrorId,
    CASE_MANAGER,
    CASE_MANAGER_ALT,
    CASE_MANAGER_ONE,
    CASE_MANAGER_TWO,
    admit_panelist,
    answer_verification,
    api_client,
    appointment_payload,
    assert_all_mandatory_grounds,
    build_docket,
    case_version,
    clear_compliance,
    cure_deficiency,
    dispatch_notification,
    file_complaint,
    file_response,
    first_verification,
    get_success_data,
    issue_deficiency_notice,
    make_respondent_headers,
    nominate_seat,
    post_ledger_line,
    read_appointment,
    read_case,
    read_panelist,
    record_delivery,
    register_domain,
    response_payload,
    run_sweep,
    screen_seat,
    set_availability,
    set_clock,
    setup_filed_case,
    validate_error,
    validate_paginated,
)


def _commenced_chain(shared, domain, deemed_received_at, evidence_count=1):
    """Carry one domain of a shared docket to a delivered EMAIL notification."""
    case = file_complaint(shared["complainant"], domain)
    assert_all_mandatory_grounds(case, shared["complainant"], evidence_count=evidence_count)
    post_ledger_line(case["id"], case["complainant_share_cents"])
    bundle = {
        "registrar": shared["registrar"],
        "complainant": shared["complainant"],
        "domain": domain,
        "case": case,
    }
    clear_compliance(case["id"], headers=CASE_MANAGER_ALT)
    bundle["verification"] = first_verification(case["id"])
    answer_verification(bundle)
    bundle["notification"] = dispatch_notification(case["id"])
    record_delivery(bundle, "DELIVERED", deemed_received_at=deemed_received_at)
    bundle["case"] = read_case(case["id"])
    return bundle


class TestStateGateBeatsResponseDeadline:
    def _two_commenced_cases(self):
        shared = build_docket(
            iana_id="IANA-1404", domain_name="latea.example",
            legal_name="Late Filing AB", country_code="FR",
        )
        first = _commenced_chain(shared, shared["domain"], "2026-08-01T00:00:00Z")
        second = _commenced_chain(
            shared,
            register_domain(shared["registrar"]["id"], "lateb.example"),
            "2026-08-03T00:00:00Z",
        )
        return first, second

    def test_a_defaulted_case_reports_its_state_and_not_the_lapsed_deadline(self):
        """PRD §2.10: "The response-deadline check sits behind the state gates of
        band 7, so a case that has already defaulted reports its state rather than
        the lateness of the attempted filing."
        PRD §3.5: "When the deadline sweep finds a `COMMENCED` case with no answer
        on file and the clock past `response_due_at` plus the 24-hour grace, the
        case moves from `COMMENCED` to `DEFAULT` and `default_recorded` is set to
        true."

        Design: Difficulty/priority_pair_validation_conflict/case_state_gate_at_priority_40_beats_response_deadline_at_priority_71
        """
        first, second = self._two_commenced_cases()
        assert first["case"]["response_due_at"] == "2026-08-21T00:00:00.000Z"
        assert second["case"]["response_due_at"] == "2026-08-23T00:00:00.000Z"

        set_clock("2026-08-23T00:00:00Z")
        counters = run_sweep()
        assert counters["defaulted_case_count"] == 1
        defaulted = read_case(first["case"]["id"])
        assert defaulted["status"] == "DEFAULT"
        assert defaulted["default_recorded"] is True
        assert read_case(second["case"]["id"])["status"] == "COMMENCED"

        refused = api_client.create_response(
            first["case"]["id"],
            response_payload(
                VERIFIED_REGISTRANT_EMAIL,
                content_summary="A very late response on the defaulted case.",
            ),
            make_respondent_headers(),
        )
        validate_error(refused, ApiErrorId.ERR_CASE_NOT_IN_RESPONSE_WINDOW.value, 409)
        _, meta = validate_paginated(
            api_client.list_responses(first["case"]["id"], CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0
        assert read_case(first["case"]["id"])["version"] == defaulted["version"]

    def test_the_deadline_rule_still_fires_on_a_case_the_sweep_has_not_reached(self):
        """PRD §3.5: "Finally the answer must arrive within the 24-hour grace period
        that follows the deadline: when the clock is later than `response_due_at`
        plus 24 hours the answer is refused with `ERR_RESPONSE_DEADLINE_PASSED` and
        nothing at all is written."
        PRD §2.4: "Time-driven transitions are therefore never spontaneous — they
        are applied by an explicit administrative sweep, which advances everything
        that has become due as of the current clock reading, in a fixed three-stage
        order: first, every `OPEN` deficiency notice whose correction deadline has
        passed expires and closes its case with a full refund; second, every
        `REQUESTED` registrar verification past its due instant becomes `OVERDUE`;
        third, every `COMMENCED` case whose response window and late grace have
        both lapsed without a response records a default."

        Design: Difficulty/priority_pair_validation_conflict/case_state_gate_at_priority_40_beats_response_deadline_at_priority_71
        """
        _, second = self._two_commenced_cases()
        case_id = second["case"]["id"]
        set_clock("2026-08-25T00:00:00Z")
        refused = api_client.create_response(
            case_id,
            response_payload(
                VERIFIED_REGISTRANT_EMAIL,
                content_summary="A late response on a case that has not been swept yet.",
            ),
            make_respondent_headers(),
        )
        validate_error(refused, ApiErrorId.ERR_RESPONSE_DEADLINE_PASSED.value, 409)
        _, meta = validate_paginated(
            api_client.list_responses(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0
        assert read_case(case_id)["status"] == "COMMENCED"


class TestDutiesBarBeatsFeeShortfall:
    def _underpaid_case_with_a_cured_notice(self):
        bundle = setup_filed_case(
            pay_filing_fee=False, iana_id="IANA-1505",
            domain_name="sodcase.example", legal_name="Duties Ltd", country_code="FR",
        )
        case_id = bundle["case"]["id"]
        post_ledger_line(case_id, 100000, reference="WIRE-1505-PART")
        notice = issue_deficiency_notice(case_id, deficiency_codes=["MISSING_SIGNATURE"])
        cure_deficiency(
            case_id, notice["id"], bundle["complainant"]["id"],
            notes="Signature page filed.",
        )
        bundle["case"] = read_case(case_id)
        return bundle

    def test_the_duties_bar_is_reported_even_though_the_money_is_also_short(self):
        """PRD §3.4: "The clearing case manager may not be the person recorded in
        `last_deficiency_issuer_user_id`; if they are the same, the request is
        refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.4: "That refusal is checked ahead of the money check, so a case
        manager who issued the last notice is turned away for the conflict even
        when the complainant has also underpaid — the fee shortfall is never the
        reported reason in that situation."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_at_priority_50_beats_fee_shortfall_at_priority_80
        """
        bundle = self._underpaid_case_with_a_cured_notice()
        case = bundle["case"]
        case_id = case["id"]
        assert case["status"] == "FILED"
        assert case["complainant_share_cents"] == 150000
        assert case["complainant_paid_cents"] == 100000
        assert case["last_deficiency_issuer_user_id"] == CASE_MANAGER_ONE

        refused = api_client.clear_compliance(
            case_id,
            {"reviewer_notes": "Clearing my own deficiency notice on an underpaid case."},
            CASE_MANAGER,
        )
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        unchanged = read_case(case_id)
        assert unchanged["status"] == "FILED"
        assert unchanged["compliance_cleared_by_user_id"] is None
        assert unchanged["version"] == case["version"]

    def test_the_second_reviewer_surfaces_the_shortfall_and_clears_once_it_is_paid(self):
        """PRD §3.4: "the complainant must have paid at least their share, meaning
        `complainant_paid_cents` is greater than or equal to
        `complainant_share_cents`, or the request is refused with
        `ERR_FILING_FEE_SHORTFALL`"
        PRD §3.4: "A successful clearance records the clearing officer on the case
        as `compliance_cleared_by_user_id`, moves the case from `FILED` to
        `VERIFICATION_PENDING`, and cascades into the registrar: a verification
        request row is created for the case in `status` `REQUESTED`, with
        `requested_at` at the current logical-clock instant and `due_at` that many
        hours later, where the number of hours is the sponsoring registrar's own
        `verification_response_hours`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_at_priority_50_beats_fee_shortfall_at_priority_80
        """
        bundle = self._underpaid_case_with_a_cured_notice()
        case_id = bundle["case"]["id"]
        short = api_client.clear_compliance(
            case_id,
            {"reviewer_notes": "Second reviewer, but the money is still short."},
            CASE_MANAGER_ALT,
        )
        validate_error(short, ApiErrorId.ERR_FILING_FEE_SHORTFALL.value, 402)
        assert read_case(case_id)["status"] == "FILED"

        post_ledger_line(case_id, 50000, reference="WIRE-1505-BALANCE")
        funded = read_case(case_id)
        assert funded["complainant_paid_cents"] == 150000
        assert funded["paid_cents"] == 150000

        cleared = clear_compliance(
            case_id, headers=CASE_MANAGER_ALT,
            reviewer_notes="Second reviewer, fee now settled in full.",
        )
        assert cleared["status"] == "VERIFICATION_PENDING"
        assert cleared["compliance_cleared_by_user_id"] == CASE_MANAGER_TWO

        verifications, meta = validate_paginated(
            api_client.list_registrar_verifications(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert verifications[0]["status"] == "REQUESTED"
        assert verifications[0]["requested_at"] == "2026-08-01T00:00:00.000Z"
        assert verifications[0]["due_at"] == "2026-08-03T00:00:00.000Z"

        repeat = api_client.clear_compliance(
            case_id, {"reviewer_notes": "Already cleared."}, CASE_MANAGER_ALT
        )
        validate_error(repeat, ApiErrorId.ERR_INVALID_CASE_STATE.value, 409)


class TestWindowConflictBeatsCapacityCeiling:
    def _one_engaged_panelist_and_a_second_case(self):
        shared = build_docket(
            iana_id="IANA-1606", domain_name="busy1.example",
            legal_name="Busy Panel NV", country_code="FR",
        )
        first = _commenced_chain(shared, shared["domain"], "2026-08-01T00:00:00Z")
        file_response(first)
        first["case"] = read_case(first["case"]["id"])
        second = _commenced_chain(
            shared,
            register_domain(shared["registrar"]["id"], "busy2.example"),
            "2026-08-01T00:00:00Z",
        )
        file_response(second)
        second["case"] = read_case(second["case"]["id"])
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-01-15T00:00:00Z", max_overlapping_engagements=1,
        )
        set_clock("2026-08-10T00:00:00Z")
        appointment = nominate_seat(first["case"]["id"], "SOLE", panelist["id"])
        seated = screen_seat(appointment["id"], panelist["id"])
        assert seated["status"] == "ACCEPTED"
        assert seated["accepted_at"] == "2026-08-10T00:00:00.000Z"
        assert seated["decision_due_at"] == "2026-08-24T00:00:00.000Z"
        assert read_panelist(panelist["id"])["active_case_load"] == 1
        first["appointment"] = seated
        return panelist, first, second

    def test_the_overlapping_engagement_outranks_the_load_ceiling(self):
        """PRD §3.6: "After the window check, the load ceiling is tested and a
        candidate whose `active_case_load` has reached `max_overlapping_engagements`
        is refused with `ERR_PANELIST_CAPACITY_EXCEEDED` — the window conflict is
        deliberately reported in preference to the capacity ceiling when both are
        true."
        PRD §2.10: "The window check is ordered ahead of the capacity check on
        purpose: adjacent-but-legal windows are the only route by which the
        capacity error becomes observable, so ordering them this way makes each
        independently reachable."

        Design: Difficulty/priority_pair_validation_conflict/panelist_window_conflict_at_priority_66_beats_capacity_ceiling_at_priority_67
        """
        panelist, _, second = self._one_engaged_panelist_and_a_second_case()
        case_id = second["case"]["id"]
        set_clock("2026-08-15T00:00:00Z")
        version_before = case_version(case_id)
        payload = appointment_payload("SOLE", version_before, nominated_by="PROVIDER")
        payload["panelist_id"] = panelist["id"]
        refused = api_client.create_appointment(case_id, payload, CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_PANELIST_WINDOW_CONFLICT.value, 409)
        _, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
        assert case_version(case_id) == version_before

    def test_the_capacity_ceiling_becomes_reachable_once_the_engagement_window_closes(self):
        """PRD §3.6: "The first is an overlap with another engagement: every seat
        the candidate holds in `ACCEPTED` on some other non-terminal case occupies
        the interval from its `accepted_at` to its `decision_due_at`, also
        half-open, so a new window that begins exactly when an existing engagement
        ends does **not** collide — back-to-back engagements are allowed."
        PRD §3.1: "Any attribute omitted from the call is left exactly as it was,
        and supplying `unavailable_from` as null clears the declared blackout
        interval entirely."

        Design: Difficulty/priority_pair_validation_conflict/panelist_window_conflict_at_priority_66_beats_capacity_ceiling_at_priority_67
        """
        panelist, first, second = self._one_engaged_panelist_and_a_second_case()
        case_id = second["case"]["id"]
        set_clock("2026-08-24T00:00:00Z")
        version_before = case_version(case_id)
        payload = appointment_payload("SOLE", version_before, nominated_by="PROVIDER")
        payload["panelist_id"] = panelist["id"]
        refused = api_client.create_appointment(case_id, payload, CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_PANELIST_CAPACITY_EXCEEDED.value, 409)
        assert read_appointment(first["appointment"]["id"])["status"] == "ACCEPTED", (
            "case 1 is still live, so the engagement still occupies the load"
        )
        assert read_panelist(panelist["id"])["active_case_load"] == 1

        set_availability(panelist["id"], max_overlapping_engagements=2)
        accepted_payload = appointment_payload(
            "SOLE", case_version(case_id), nominated_by="PROVIDER"
        )
        accepted_payload["panelist_id"] = panelist["id"]
        seat = get_success_data(
            api_client.create_appointment(case_id, accepted_payload, CASE_MANAGER), 201
        )
        assert seat["status"] == "NOMINATED"
        assert seat["seat"] == "SOLE"
        assert seat["conflict_score"] is None
        assert read_panelist(panelist["id"])["active_case_load"] == 1
