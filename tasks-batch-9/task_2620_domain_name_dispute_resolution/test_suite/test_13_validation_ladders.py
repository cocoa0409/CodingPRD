"""Refusals chosen from the ladder, and the writes they leave undone."""
from test_helpers import (
    VERIFIED_REGISTRANT_EMAIL,
    ApiErrorId,
    CASE_MANAGER,
    CASE_MANAGER_ALT,
    PROVIDER_ADMIN,
    admit_panelist,
    answer_verification,
    api_client,
    appointment_payload,
    assert_ground_on_case,
    build_docket,
    case_version,
    file_complaint,
    first_verification,
    get_success_data,
    ground_payload,
    issue_deficiency_notice,
    make_complainant_headers,
    make_registrar_headers,
    nominate_seat,
    post_ledger_line,
    read_appointment,
    read_case,
    read_domain,
    read_panelist,
    read_registrar,
    register_domain,
    screen_seat,
    set_clock,
    setup_filed_case,
    setup_responded_case,
    setup_verification_pending_case,
    suspend_registrar,
    validate_error,
    validate_paginated,
)


class TestSufficiencyBeforeCompleteness:
    def test_the_case_breaking_both_ground_rules_reports_the_unsupported_element(self):
        """PRD §3.4: "the case must carry exactly one asserted element of each of the
        three mandatory `ground_type` values, or it is refused with
        `ERR_MISSING_REQUIRED_GROUND`; and every one of those elements must be graded
        `SUFFICIENT`, or the request is refused with `ERR_GROUND_EVIDENCE_INSUFFICIENT`"
        PRD §3.2: "Its `sufficiency_status` is `SUFFICIENT` when `evidence_count` is at
        least 1, and `DEFICIENT` otherwise — the threshold is inclusive, so a single annex
        suffices and zero annexes does not."
        PRD §2.10: "**Business constraints**, in this internal order: the
        deficiency-round ceiling (`ERR_DEFICIENCY_ROUND_LIMIT`); insufficient evidence on
        some ground at clearance (`ERR_GROUND_EVIDENCE_INSUFFICIENT`); a seat the case's
        seat count does not admit (`ERR_SEAT_NOT_APPLICABLE`); a seat already held
        (`ERR_SEAT_ALREADY_FILLED`); a named panelist failing the non-temporal eligibility
        clauses (`ERR_PANELIST_INELIGIBLE`); an engagement-window collision
        (`ERR_PANELIST_WINDOW_CONFLICT`); the aggregate engagement ceiling
        (`ERR_PANELIST_CAPACITY_EXCEEDED`); a seat voting twice
        (`ERR_VOTE_ALREADY_CAST`)."
        PRD §3.4: "A successful clearance records the clearing officer on the case as
        `compliance_cleared_by_user_id`, moves the case from `FILED` to
        `VERIFICATION_PENDING`, and cascades into the registrar: a verification request row
        is created for the case in `status` `REQUESTED`, with `requested_at` at the current
        logical-clock instant and `due_at` that many hours later, where the number of hours
        is the sponsoring registrar's own `verification_response_hours`."

        Design: Corner/validations/ground_sufficiency_at_priority_62_is_reported_before_completeness_at_priority_90
        """
        shared = build_docket(
            iana_id="IANA-9025", domain_name="sufx.example", country_code="GB",
            legal_name="Suf Ltd", registrar_name="Suf Registrar",
        )
        complainant = shared["complainant"]
        both_broken = file_complaint(complainant, shared["domain"])
        supported = assert_ground_on_case(
            both_broken, complainant, "TRADEMARK_RIGHTS", evidence_count=2
        )
        unsupported = assert_ground_on_case(
            both_broken, complainant, "NO_LEGITIMATE_INTEREST", evidence_count=0
        )
        post_ledger_line(both_broken["id"], both_broken["complainant_share_cents"])
        assert supported["sufficiency_status"] == "SUFFICIENT"
        assert unsupported["sufficiency_status"] == "DEFICIENT"

        only_incomplete = file_complaint(
            complainant, register_domain(shared["registrar"]["id"], "sufy.example")
        )
        assert_ground_on_case(only_incomplete, complainant, "TRADEMARK_RIGHTS", evidence_count=2)
        second_supported = assert_ground_on_case(
            only_incomplete, complainant, "NO_LEGITIMATE_INTEREST", evidence_count=1
        )
        post_ledger_line(only_incomplete["id"], only_incomplete["complainant_share_cents"])
        assert second_supported["sufficiency_status"] == "SUFFICIENT"

        insufficient = api_client.clear_compliance(
            both_broken["id"], {"reviewer_notes": "First pass over the unsupported case."},
            CASE_MANAGER_ALT,
        )
        validate_error(insufficient, ApiErrorId.ERR_GROUND_EVIDENCE_INSUFFICIENT.value, 422)
        assert insufficient.json()["data"]["error_id"] != ApiErrorId.ERR_MISSING_REQUIRED_GROUND.value

        incomplete = api_client.clear_compliance(
            only_incomplete["id"], {"reviewer_notes": "First pass over the short case."},
            CASE_MANAGER_ALT,
        )
        validate_error(incomplete, ApiErrorId.ERR_MISSING_REQUIRED_GROUND.value, 422)

        for case_id in (both_broken["id"], only_incomplete["id"]):
            refused = read_case(case_id)
            assert refused["status"] == "FILED"
            assert refused["compliance_cleared_by_user_id"] is None
            _, meta = validate_paginated(
                api_client.list_registrar_verifications(
                    case_id, CASE_MANAGER, params={"limit": 10, "offset": 0}
                )
            )
            assert meta["total_count"] == 0, "a refused clearance mints no verification request"


class TestCorrectionWindowRightEndpoint:
    def test_a_cure_on_the_deadline_instant_lands_and_one_second_later_does_not(self):
        """PRD §3.4: "The cure must arrive no later than the notice's
        `correction_deadline_at` — the deadline is inclusive, so a cure filed at that exact
        instant is accepted and one instant later is refused with
        `ERR_CORRECTION_PERIOD_EXPIRED`."
        PRD §3.4: "It may also carry `correction_days`, the length of the cure window in
        days, which defaults to 5 when omitted and must be between 1 and 20."
        PRD §3.4: "The notice becomes `CURED` with `cured_at` stamped from the clock, and
        the case returns from `DEFICIENT` to `FILED`."

        Design: Corner/validations/correction_is_admissible_on_the_deadline_instant_and_refused_one_second_later
        """
        bundle = setup_filed_case(
            iana_id="IANA-9026", domain_name="corr.example", country_code="GB",
            legal_name="Corr Ltd", registrar_name="Corr Registrar",
        )
        case_id = bundle["case"]["id"]
        complainant_id = bundle["complainant"]["id"]
        headers = make_complainant_headers(complainant_id)

        first = issue_deficiency_notice(
            case_id, deficiency_codes=["MUTUAL_JURISDICTION_ABSENT"], correction_days=5
        )
        assert first["round_number"] == 1
        assert first["issued_at"] == "2026-08-01T00:00:00.000Z"
        assert first["correction_deadline_at"] == "2026-08-06T00:00:00.000Z"

        set_clock("2026-08-06T00:00:00Z")
        cured = get_success_data(
            api_client.create_correction(
                case_id,
                {
                    "notice_id": first["id"],
                    "correction_notes": "Consent to the mutual jurisdiction is filed as annex 3.",
                },
                headers,
            ),
            200,
        )
        assert cured["status"] == "CURED"
        assert cured["cured_at"] == "2026-08-06T00:00:00.000Z"
        back_to_filed = read_case(case_id)
        assert back_to_filed["status"] == "FILED"
        assert back_to_filed["deficiency_round_count"] == 1

        second = issue_deficiency_notice(
            case_id, CASE_MANAGER_ALT,
            deficiency_codes=["MISSING_GROUND", "MISSING_MARK_EVIDENCE"], correction_days=2,
        )
        assert second["round_number"] == 2
        assert second["issued_at"] == "2026-08-06T00:00:00.000Z"
        assert second["correction_deadline_at"] == "2026-08-08T00:00:00.000Z", (
            "the explicit two-day window overrides the five-day default"
        )

        set_clock("2026-08-08T00:00:01Z")
        too_late = api_client.create_correction(
            case_id,
            {
                "notice_id": second["id"],
                "correction_notes": "The two missing grounds are pleaded in annex 4.",
            },
            headers,
        )
        validate_error(too_late, ApiErrorId.ERR_CORRECTION_PERIOD_EXPIRED.value, 409)

        notices, notice_meta = validate_paginated(
            api_client.list_deficiency_notices(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert notice_meta["total_count"] == 2
        assert [notice["round_number"] for notice in notices] == [1, 2]
        assert notices[1]["status"] == "OPEN"
        assert notices[1]["cured_at"] is None
        still_deficient = read_case(case_id)
        assert still_deficient["status"] == "DEFICIENT"
        assert still_deficient["deficiency_round_count"] == 2
        _, ledger_meta = validate_paginated(
            api_client.list_fee_transactions(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert ledger_meta["total_count"] == 1


class TestGroundTypeUniqueness:
    def test_a_second_element_of_the_same_type_is_refused_while_a_new_type_is_taken(self):
        """PRD §3.2: "A case may carry at most one assertion per `ground_type`; a second
        attempt at the same element is refused with `ERR_DUPLICATE_GROUND_TYPE`."
        PRD §3.2: "Three further attributes are required when — and only when — the
        element being asserted is `TRADEMARK_RIGHTS`, and are ignored on the other two
        elements: `mark_registration_number`, the trademark registration number;
        `mark_jurisdiction`, the two-letter registry of the asserted mark; and
        `similarity_claim`, the confusion theory pleaded, which is either `IDENTICAL` or
        `CONFUSINGLY_SIMILAR`."

        Design: Corner/validations/a_second_ground_of_the_same_type_is_refused
        """
        shared = build_docket(
            iana_id="IANA-9027", domain_name="dupg.example", country_code="GB",
            legal_name="Dupg Ltd", registrar_name="Dupg Registrar",
        )
        complainant = shared["complainant"]
        case = file_complaint(complainant, shared["domain"])
        headers = make_complainant_headers(complainant["id"])
        stored = assert_ground_on_case(
            case, complainant, "TRADEMARK_RIGHTS", evidence_count=1,
            similarity_claim="IDENTICAL",
        )
        assert stored["evidence_count"] == 1
        assert stored["similarity_claim"] == "IDENTICAL"

        duplicate = api_client.create_ground(
            case["id"],
            ground_payload(
                "TRADEMARK_RIGHTS", evidence_count=5,
                assertion_text=(
                    "A second, fuller pleading of the same trademark rights with four "
                    "more exhibits."
                ),
                similarity_claim="CONFUSINGLY_SIMILAR",
            ),
            headers,
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_GROUND_TYPE.value, 409)

        different_type = get_success_data(
            api_client.create_ground(
                case["id"],
                ground_payload(
                    "BAD_FAITH", evidence_count=1,
                    assertion_text="The registrant offered the name for sale to the complainant.",
                ),
                headers,
            ),
            201,
        )
        assert different_type["ground_type"] == "BAD_FAITH"

        rows, meta = validate_paginated(
            api_client.list_grounds(case["id"], CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2
        assert [row["ground_type"] for row in rows] == ["TRADEMARK_RIGHTS", "BAD_FAITH"]
        assert rows[0]["evidence_count"] == 1, "the rejected body never touched the stored row"
        assert rows[0]["similarity_claim"] == "IDENTICAL"
        assert rows[0]["id"] == stored["id"]


class TestSuspensionOutranksTheLockAttestation:
    def test_the_same_unlocked_answer_earns_a_409_while_suspended_and_a_422_once_active(self):
        """PRD §3.4: "That registrar must be in `status` `ACTIVE`, or the answer is
        refused with `ERR_REGISTRAR_SUSPENDED` — a check that comes before the lock check,
        so a suspended registrar is turned away for suspension even when it also failed to
        apply the lock."
        PRD §3.4: "If `lock_applied` is not true, the answer is refused with
        `ERR_DOMAIN_LOCK_NOT_APPLIED` and nothing is written."
        PRD §3.4: "The disclosed identity is copied onto the case as its own
        `verified_registrant_name` and `verified_registrant_email` — this is the address
        against which the respondent's identity is later checked."

        Design: Corner/validations/suspended_registrar_outranks_the_lock_attestation_rule
        """
        bundle = setup_verification_pending_case(
            iana_id="IANA-9028", domain_name="rsusp.example", country_code="GB",
            legal_name="Rsusp Ltd", registrar_name="Rsusp Registrar",
        )
        case_id = bundle["case"]["id"]
        registrar_id = bundle["registrar"]["id"]
        verification_id = bundle["verification"]["id"]
        registrar_headers = make_registrar_headers(registrar_id)
        unlocked_answer = {
            "lock_applied": False,
            "verified_registrant_name": "Rsusp Underlying Holder",
            "verified_registrant_email": "registrant@rsusp.example",
            "registrar_remarks": "Answering while suspended and without a lock.",
        }
        assert suspend_registrar(registrar_id)["status"] == "SUSPENDED"

        while_suspended = api_client.respond_to_verification(
            case_id, verification_id, unlocked_answer, registrar_headers
        )
        validate_error(while_suspended, ApiErrorId.ERR_REGISTRAR_SUSPENDED.value, 409)
        assert while_suspended.json()["data"]["error_id"] != ApiErrorId.ERR_DOMAIN_LOCK_NOT_APPLIED.value

        reinstated = get_success_data(
            api_client.set_registrar_status(registrar_id, {"status": "ACTIVE"}, PROVIDER_ADMIN)
        )
        assert reinstated["status"] == "ACTIVE"
        assert read_registrar(registrar_id)["status"] == "ACTIVE"

        without_a_lock = api_client.respond_to_verification(
            case_id, verification_id, unlocked_answer, registrar_headers
        )
        validate_error(without_a_lock, ApiErrorId.ERR_DOMAIN_LOCK_NOT_APPLIED.value, 422)

        assert read_domain(bundle["domain"]["id"])["lock_status"] == "UNLOCKED"
        untouched = first_verification(case_id)
        assert untouched["status"] == "REQUESTED"
        assert untouched["lock_applied"] is False
        assert untouched["responded_at"] is None
        assert untouched["registrar_remarks"] is None
        mid_case = read_case(case_id)
        assert mid_case["status"] == "VERIFICATION_PENDING"
        assert mid_case["verified_registrant_email"] is None, (
            "a refused verification discloses nothing"
        )

        answered = answer_verification(bundle)
        assert answered["status"] == "RESPONDED"
        assert answered["lock_applied"] is True
        assert answered["responded_at"] == "2026-08-01T00:00:00.000Z"
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "LOCKED"
        disclosed = read_case(case_id)
        assert disclosed["status"] == "NOTIFICATION_PENDING"
        assert disclosed["verified_registrant_email"] == VERIFIED_REGISTRANT_EMAIL


class TestSeatApplicabilityBeforeOccupancy:
    def test_a_seat_the_panel_does_not_have_and_a_seat_it_already_filled_fail_apart(self):
        """PRD §3.6: "Nominating `SOLE` on a three-member case, or any of the three
        co-panelist seats on a single-member case, is refused with
        `ERR_SEAT_NOT_APPLICABLE`."
        PRD §3.6: "A seat already held by a nomination in `NOMINATED`, `WAIVER_PENDING` or
        `ACCEPTED` cannot be nominated again and is refused with
        `ERR_SEAT_ALREADY_FILLED`; seats whose previous holder ended in `DECLINED`,
        `CONFLICTED`, `REPLACED` or `DISCHARGED` are free."
        PRD §3.6: "Which seats exist is fixed by the case's `required_seat_count`: a
        single-member panel has exactly one seat, `SOLE`, and a three-member panel has
        exactly three, `PRESIDING`, `CO_PANELIST_1` and `CO_PANELIST_2`."

        Design: Corner/validations/seat_applicability_is_checked_before_seat_occupancy
        """
        bundle = setup_responded_case(
            iana_id="IANA-9029", domain_name="seat.example", country_code="GB",
            legal_name="Seat Ltd", registrar_name="Seat Registrar",
        )
        case_id = bundle["case"]["id"]
        assert bundle["case"]["required_seat_count"] == 1
        assert bundle["case"]["paid_cents"] == 150000
        incumbent = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-04-01T00:00:00Z",
        )
        rival = admit_panelist(
            full_name="Luca Rossi", nationality_code="IT",
            roster_admitted_at="2019-05-01T00:00:00Z",
        )

        pinned = case_version(case_id)
        wrong_seat = appointment_payload("PRESIDING", pinned)
        wrong_seat["panelist_id"] = incumbent["id"]
        refused_seat = api_client.create_appointment(case_id, wrong_seat, CASE_MANAGER)
        validate_error(refused_seat, ApiErrorId.ERR_SEAT_NOT_APPLICABLE.value, 422)

        first_payload = appointment_payload("SOLE", pinned)
        first_payload["panelist_id"] = incumbent["id"]
        seated = get_success_data(
            api_client.create_appointment(case_id, first_payload, CASE_MANAGER), 201
        )
        assert seated["seat"] == "SOLE"
        assert seated["panelist_id"] == incumbent["id"]
        assert seated["status"] == "NOMINATED"

        current = case_version(case_id)
        second_payload = appointment_payload("SOLE", current)
        second_payload["panelist_id"] = rival["id"]
        already_filled = api_client.create_appointment(case_id, second_payload, CASE_MANAGER)
        validate_error(already_filled, ApiErrorId.ERR_SEAT_ALREADY_FILLED.value, 409)
        assert already_filled.json()["data"]["error_id"] != ApiErrorId.ERR_STALE_CASE_VERSION.value

        rows, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["panelist_id"] == incumbent["id"]
        assert read_panelist(rival["id"])["active_case_load"] == 0


class TestWaiverNeedsBothConsents:
    def _waiver_pending_seat(self):
        bundle = setup_responded_case(
            iana_id="IANA-9030", domain_name="waiv.example", country_code="GB",
            legal_name="Waiv Ltd", registrar_name="Waiv Registrar",
        )
        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-04-01T00:00:00Z", firm_name="Bauer Legal",
        )
        nominated = nominate_seat(bundle["case"]["id"], "SOLE", panelist["id"])
        bundle["panelists"] = [panelist]
        bundle["appointments"] = [screen_seat(nominated["id"], panelist["id"], disclosed_same_firm=True)]
        bundle["case"] = read_case(bundle["case"]["id"])
        return bundle

    def test_an_omitted_and_a_false_consent_are_both_incomplete_on_a_participating_respondent(self):
        """PRD §3.6: "Both parties must consent: `waiver_complainant` must be true, and
        `waiver_respondent` must be true as well — unless the case carries a recorded
        default, meaning `default_recorded` is true and no answer was ever filed, in which
        case the respondent's consent may be omitted."
        PRD §3.6: "An incomplete waiver is refused with `ERR_WAIVER_INCOMPLETE`, the
        lowest-precedence refusal in the whole catalogue."
        PRD §3.6: "A score at or above the waiver threshold of 30 but below 60 sends the
        seat to `WAIVER_PENDING`, again taking no load, and the seat waits on the parties'
        consent — exactly 30.00 requires a waiver."
        PRD §3.6: "A `SOLE` seat takes 100 percent of the pool exactly."

        Design: Corner/validations/waiver_needs_both_consents_when_the_respondent_is_participating
        """
        bundle = self._waiver_pending_seat()
        seat = bundle["appointments"][0]
        panelist = bundle["panelists"][0]
        assert float(seat["conflict_score"]) == 35.00
        assert seat["status"] == "WAIVER_PENDING"
        assert seat["conflict_factors"] == ["SAME_FIRM"]
        assert bundle["case"]["default_recorded"] is False
        assert bundle["case"]["honoraria_pool_cents"] == 105000

        omitted = api_client.record_waiver(seat["id"], {"waiver_complainant": True}, CASE_MANAGER)
        validate_error(omitted, ApiErrorId.ERR_WAIVER_INCOMPLETE.value, 422)

        refused_by_complainant = api_client.record_waiver(
            seat["id"], {"waiver_complainant": False, "waiver_respondent": True}, CASE_MANAGER
        )
        validate_error(refused_by_complainant, ApiErrorId.ERR_WAIVER_INCOMPLETE.value, 422)

        untouched = read_appointment(seat["id"])
        assert untouched["status"] == "WAIVER_PENDING"
        assert untouched["waiver_complainant"] is False
        assert untouched["waiver_respondent"] is False
        assert untouched["accepted_at"] is None
        assert untouched["honoraria_cents"] == 0
        assert read_panelist(panelist["id"])["active_case_load"] == 0

        consented = get_success_data(
            api_client.record_waiver(
                seat["id"], {"waiver_complainant": True, "waiver_respondent": True}, CASE_MANAGER
            )
        )
        assert consented["status"] == "ACCEPTED"
        assert consented["accepted_at"] == "2026-08-01T00:00:00.000Z"
        assert consented["waiver_complainant"] is True
        assert consented["waiver_respondent"] is True
        assert consented["honoraria_cents"] == 105000
        assert read_panelist(panelist["id"])["active_case_load"] == 1
        assert read_case(bundle["case"]["id"])["status"] == "PANEL_CONSTITUTED"


class TestSupplementMustLandBeforeNomination:
    def test_the_fiscal_gate_reads_the_whole_case_total_and_not_the_complainant_share(self):
        """PRD §3.6: "The parties' money must also be in before neutrals are engaged:
        `paid_cents` must be greater than or equal to `assessed_fee_cents`, or the
        nomination is refused with `ERR_PANEL_SUPPLEMENT_UNPAID`."
        PRD §3.5: "The 250000-cent three-member supplement now enters
        `assessed_fee_cents`, `respondent_share_cents` becomes half of that supplement
        rounded down, or 125000 cents, and `complainant_share_cents` is the remainder."
        PRD §2.10: "**Fiscal**, in this internal order: the complainant's share unpaid at
        clearance (`ERR_FILING_FEE_SHORTFALL`); the assessed total unpaid at nomination
        (`ERR_PANEL_SUPPLEMENT_UNPAID`)."

        Design: Corner/validations/the_respondent_supplement_must_land_before_any_seat_is_nominated
        """
        bundle = setup_responded_case(
            requests_three_member_panel=True, iana_id="IANA-9045",
            domain_name="supp.example", country_code="GB", legal_name="Supp Ltd",
            registrar_name="Supp Registrar",
        )
        case_id = bundle["case"]["id"]
        repriced = bundle["case"]
        assert repriced["assessed_fee_cents"] == 400000
        assert repriced["complainant_share_cents"] == 275000
        assert repriced["respondent_share_cents"] == 125000

        post_ledger_line(
            case_id, 125000, payer="COMPLAINANT", kind="PANEL_SUPPLEMENT",
            reference="WIRE-9045-COMP",
        )
        complainant_settled = read_case(case_id)
        assert complainant_settled["complainant_paid_cents"] == 275000
        assert complainant_settled["paid_cents"] == 275000

        panelist = admit_panelist(
            full_name="Anna Bauer", nationality_code="DE",
            roster_admitted_at="2019-04-01T00:00:00Z",
        )
        short_payload = appointment_payload("PRESIDING", case_version(case_id))
        short_payload["panelist_id"] = panelist["id"]
        refused = api_client.create_appointment(case_id, short_payload, CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_PANEL_SUPPLEMENT_UNPAID.value, 402)
        _, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER, params={"case_id": case_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
        assert read_case(case_id)["status"] == "RESPONSE_RECEIVED"

        post_ledger_line(
            case_id, 125000, payer="RESPONDENT", kind="PANEL_SUPPLEMENT",
            reference="WIRE-9045-SUPP",
        )
        funded = read_case(case_id)
        assert funded["respondent_paid_cents"] == 125000
        assert funded["paid_cents"] == 400000

        paid_payload = appointment_payload("PRESIDING", case_version(case_id))
        paid_payload["panelist_id"] = panelist["id"]
        seated = get_success_data(
            api_client.create_appointment(case_id, paid_payload, CASE_MANAGER), 201
        )
        assert seated["seat"] == "PRESIDING"
        assert seated["status"] == "NOMINATED"
        assert read_case(case_id)["status"] == "PANEL_APPOINTMENT"
