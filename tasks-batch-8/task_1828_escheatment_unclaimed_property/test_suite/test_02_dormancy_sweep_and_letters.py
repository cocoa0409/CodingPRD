"""Dormancy sweep boundaries, the due-diligence letter machine, and the
letter send window (PRD §3.2, §3.3)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.fixtures import (
    CO,
    READER,
    create_dormant_property,
    create_owner,
    create_property,
    create_rule,
    get_property,
    record_contact,
    run_sweep,
    send_letter,
    set_clock,
)

CO_H = TEST_USERS["compliance_officer_headers"]


class TestDormancyAnniversaryBoundary:
    def test_sweep_exactly_on_anniversary_stays_active(self, api):
        """PRD §3.2: "A sweep running exactly on the anniversary changes
        nothing; the property remains `ACTIVE`."

        Design: Difficulty/boundary_precision_check/dormancy_anniversary_strictly_greater_boundary
        """
        create_rule()
        owner = create_owner()
        prop = create_property(owner["id"], original_value_cents=40000)
        set_clock("2026-03-15T00:00:00Z")  # exactly the 3-year anniversary
        run_sweep()
        after = get_property(prop["id"])
        assert after["status"] == "ACTIVE", (
            "strictly-greater comparison excludes the anniversary itself"
        )
        assert after["dormancy_date"] is None

    def test_sweep_one_day_after_anniversary_flips_dormant(self, api):
        """PRD §3.2: "when the sweep date is strictly later than that
        anniversary, the property transitions `ACTIVE → DORMANT` and its
        `dormancy_date` is set to the day immediately following the
        anniversary."

        Design: Difficulty/boundary_precision_check/dormancy_anniversary_strictly_greater_boundary
        """
        create_rule()
        owner = create_owner()
        prop = create_property(owner["id"], original_value_cents=40000)
        set_clock("2026-03-16T00:00:00Z")  # one day past the anniversary
        run_sweep()
        after = get_property(prop["id"])
        assert after["status"] == "DORMANT"
        assert after["dormancy_date"] == "2026-03-16"


class TestDueDiligenceThresholdBoundary:
    def _two_properties_straddling_threshold(self):
        create_rule(state_code="CA", property_type="UNCASHED_CHECK")
        owner = create_owner()
        prop_a = create_property(
            owner["id"], property_type="UNCASHED_CHECK", original_value_cents=5000
        )
        prop_b = create_property(
            owner["id"], property_type="UNCASHED_CHECK", original_value_cents=4999
        )
        run_sweep()  # both ACTIVE -> DORMANT at the default clock
        return owner, prop_a, prop_b

    def test_letter_required_at_exactly_threshold_not_below(self, api):
        """PRD §3.3: "And the property's `original_value_cents` must be at or
        above the rule's `dd_threshold_cents`; below it, due diligence is not
        required and creation is refused with `ERR_DUE_DILIGENCE_NOT_REQUIRED`."

        Design: Difficulty/boundary_precision_check/dd_threshold_exact_5000_boundary
        """
        _, prop_a, prop_b = self._two_properties_straddling_threshold()
        ok = api.create_letter(prop_a["id"], CO_H)
        letter = validate_success(ok, 201)
        assert letter["property_id"] == prop_a["id"]
        assert get_property(prop_a["id"])["status"] == "DUE_DILIGENCE"
        err = api.create_letter(prop_b["id"], CO_H)
        validate_error(err, ApiErrorId.ERR_DUE_DILIGENCE_NOT_REQUIRED, 422)

    def test_under_threshold_property_auto_advances_on_later_sweep(self, api):
        """PRD §3.2: "The second pass considers only properties that were
        already `DORMANT` when the sweep started: any of them whose
        `original_value_cents` falls below the applicable rule's
        `dd_threshold_cents` — due diligence not required — advances
        `DORMANT → REPORTABLE` at once."

        Design: Difficulty/boundary_precision_check/dd_threshold_exact_5000_boundary
        """
        _, prop_a, prop_b = self._two_properties_straddling_threshold()
        get_success_data(api.create_letter(prop_a["id"], CO_H), 201)
        run_sweep()  # second sweep at the same clock
        assert get_property(prop_b["id"])["status"] == "REPORTABLE"
        assert get_property(prop_a["id"])["status"] == "DUE_DILIGENCE", (
            "the letter path is mandatory at/above the threshold; the sweep "
            "does not auto-advance a DUE_DILIGENCE property"
        )


class TestPropertyDormancyReactivationCycle:
    def _cycled_property(self):
        rule, owner, prop = create_dormant_property(original_value_cents=60000)
        # property is DORMANT with dormancy_date 2026-03-16
        event = record_contact(prop["id"], contact_date="2026-08-01",
                               evidence_ref="stmt-881")
        resp = api_client.reactivate_property(
            prop["id"], {"evidence_contact_event_id": event["id"]}, CO_H
        )
        reactivated = validate_success(resp, 200)
        return prop, event, reactivated

    def test_reactivation_returns_active_and_clears_dormancy_date(self, api):
        """PRD §3.3: "The property returns to `ACTIVE`, its `last_contact_date`
        advances to the later of its current value and the evidence's
        `contact_date`, and its `dormancy_date` is cleared back to null."

        Design: Difficulty/non_linear_state_machine/property_dormancy_reactivation_cycle
        """
        prop, event, reactivated = self._cycled_property()
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["dormancy_date"] is None
        assert reactivated["last_contact_date"] == "2026-08-01"

    def test_second_dormancy_uses_new_contact_anniversary(self, api):
        """PRD §3.2: "The first pass examines every `ACTIVE` property that has
        an applicable rule: it computes the anniversary of the
        `last_contact_date` after adding the rule's `dormancy_years` — the same
        month and day, that many years later — and when the sweep date is
        strictly later than that anniversary, the property transitions
        `ACTIVE → DORMANT`"

        Design: Difficulty/non_linear_state_machine/property_dormancy_reactivation_cycle
        """
        prop, event, _ = self._cycled_property()
        set_clock("2029-08-01T00:00:00Z")  # new anniversary: 2026-08-01 + 3y
        run_sweep()
        assert get_property(prop["id"])["status"] == "ACTIVE", (
            "sweep exactly on the new anniversary must not flip the property"
        )
        set_clock("2029-08-02T00:00:00Z")
        run_sweep()
        after = get_property(prop["id"])
        assert after["status"] == "DORMANT"
        assert after["dormancy_date"] == "2029-08-02"


class TestLetterCreationGates:
    def test_letter_on_active_property_rejected(self, api):
        """PRD §3.3: "The property must be `DORMANT` or `DUE_DILIGENCE`, else
        `ERR_PROPERTY_NOT_DORMANT`"

        Design: Difficulty/cross_entity_state_dependency/letter_create_requires_property_dormant
        """
        create_rule()
        owner = create_owner()
        prop = create_property(owner["id"], original_value_cents=90000)
        # No sweep: the property is still ACTIVE.
        resp = api.create_letter(prop["id"], CO_H)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_DORMANT, 409)

    def test_rejected_letter_attempt_persists_nothing(self, api):
        """PRD §3.3: "Four checks guard creation, evaluated in a fixed order —
        state first, then uniqueness, then the send window, then the threshold —
        so that, for example, a letter attempt on an `ACTIVE` property surfaces
        `ERR_PROPERTY_NOT_DORMANT` rather than being masked by a later check."

        Design: Difficulty/cross_entity_state_dependency/letter_create_requires_property_dormant
        """
        create_rule()
        owner = create_owner()
        prop = create_property(owner["id"], original_value_cents=90000)
        validate_error(
            api.create_letter(prop["id"], CO_H),
            ApiErrorId.ERR_PROPERTY_NOT_DORMANT,
            409,
        )
        letters, meta = validate_paginated(api.list_property_letters(prop["id"], CO_H))
        assert meta["total_count"] == 0, "no letter row may be created"


class TestDuplicateLetterBeatsWindow:
    def _property_with_active_letter(self):
        rule, owner, prop = create_dormant_property(original_value_cents=75000)
        letter = send_letter(prop["id"])  # sent 2026-08-01, inside the window
        set_clock("2026-09-10T00:00:00Z")  # outside the window; no sweep run
        return prop, letter

    def test_second_letter_outside_window_reports_duplicate(self, api):
        """PRD §3.3: "No other letter for the property may be `SENT` or
        `DELIVERED`, else `ERR_DUPLICATE_ACTIVE_LETTER`."
        PRD §3.3: "Four checks guard creation, evaluated in a fixed order —
        state first, then uniqueness, then the send window, then the threshold"

        Design: Difficulty/priority_pair_validation_conflict/duplicate_letter_constraint_beats_window_temporal
        """
        prop, letter1 = self._property_with_active_letter()
        resp = api.create_letter(prop["id"], CO_H)
        # 2026-09-10 is also outside the send window, but the uniqueness check
        # (earlier layer) masks the temporal check.
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_LETTER, 409)

    def test_failed_second_attempt_leaves_first_letter_sent(self, api):
        """PRD §3.3: "`DUE_DILIGENCE` is admitted deliberately so that a second
        letter attempt reaches the duplicate check, since a property in that
        state always has an active letter on file."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_letter_constraint_beats_window_temporal
        """
        prop, letter1 = self._property_with_active_letter()
        validate_error(
            api.create_letter(prop["id"], CO_H),
            ApiErrorId.ERR_DUPLICATE_ACTIVE_LETTER,
            409,
        )
        letters, meta = validate_paginated(api.list_property_letters(prop["id"], CO_H))
        assert meta["total_count"] == 1
        assert letters[0]["id"] == letter1["id"]
        assert letters[0]["status"] == "SENT"


class TestLetterLifecycle:
    def _dormant_with_letter(self, value=60000):
        rule, owner, prop = create_dormant_property(original_value_cents=value)
        letter = send_letter(prop["id"])
        return prop, letter

    def test_letter_created_sent_with_derived_dates(self, api):
        """PRD §3.3: "A created letter starts `SENT`, stamped with a
        `sent_date` equal to the clock date, a `response_deadline` exactly
        thirty days after the `sent_date`, the `applicable_due_date` derived
        per §3.2, the `property_id` of its property, and
        `response_contact_event_id` null."

        Design: Corner/state_machines/letter_initial_state_and_deadline
        """
        prop, letter = self._dormant_with_letter()
        assert letter["status"] == "SENT"
        assert letter["sent_date"] == "2026-08-01"
        assert letter["response_deadline"] == "2026-08-31"
        assert letter["applicable_due_date"] == "2026-11-01"
        assert letter["property_id"] == prop["id"]
        assert letter["response_contact_event_id"] is None
        assert get_property(prop["id"])["status"] == "DUE_DILIGENCE"

    def test_mark_delivered_twice_rejected(self, api):
        """PRD §3.3: "A `ComplianceOfficer` may mark a `SENT` letter delivered,
        moving it `SENT → DELIVERED`"
        PRD §3.3: "Any of these actions attempted on a letter not in an
        acceptable state is refused with `ERR_LETTER_NOT_ACTIONABLE`."

        Design: Corner/state_machines/letter_mark_delivered_twice_rejected
        """
        prop, letter = self._dormant_with_letter()
        delivered = get_success_data(api.mark_letter_delivered(letter["id"], CO_H), 200)
        assert delivered["status"] == "DELIVERED"
        resp = api.mark_letter_delivered(letter["id"], CO_H)
        validate_error(resp, ApiErrorId.ERR_LETTER_NOT_ACTIONABLE, 409)
        still = get_success_data(api.get_letter(letter["id"], READER), 200)
        assert still["status"] == "DELIVERED"

    def test_mark_undeliverable_advances_property_to_reportable(self, api):
        """PRD §3.3: "may mark a letter undeliverable from either `SENT` or
        `DELIVERED`, moving it to `UNDELIVERABLE` and dropping its property
        `DUE_DILIGENCE → REPORTABLE`"

        Design: Corner/state_machines/letter_undeliverable_makes_property_reportable
        """
        prop, letter = self._dormant_with_letter()
        get_success_data(api.mark_letter_delivered(letter["id"], CO_H), 200)
        resp = api.mark_letter_undeliverable(letter["id"], CO_H)
        gone = validate_success(resp, 200)
        assert gone["status"] == "UNDELIVERABLE"
        assert get_property(prop["id"])["status"] == "REPORTABLE"

    def test_record_response_reactivates_property(self, api):
        """PRD §3.3: "On success the letter becomes `RESPONDED` with
        `response_contact_event_id` recorded, and the property returns
        `DUE_DILIGENCE → ACTIVE` with the full reactivation cascade below: the
        property's `last_contact_date` advances to the later of its current
        value and the evidence event's `contact_date`."

        Design: Corner/state_machines/letter_response_reactivates_property
        """
        prop, letter = self._dormant_with_letter()
        get_success_data(api.mark_letter_delivered(letter["id"], CO_H), 200)
        event = record_contact(
            prop["id"], contact_type="WRITTEN_CORRESPONDENCE",
            contact_date="2026-08-20", evidence_ref="letter-back-1",
        )
        resp = api.record_letter_response(
            letter["id"], {"response_contact_event_id": event["id"]}, CO_H
        )
        responded = validate_success(resp, 200)
        assert responded["status"] == "RESPONDED"
        assert responded["response_contact_event_id"] == event["id"]
        after = get_property(prop["id"])
        assert after["status"] == "ACTIVE"
        assert after["last_contact_date"] == "2026-08-20"

    def test_sweep_expires_letter_only_after_deadline(self, api):
        """PRD §3.2: "The third pass expires letters: any due-diligence letter
        still `SENT` or `DELIVERED` whose `response_deadline` is strictly
        before the sweep date becomes `EXPIRED` — on the deadline day itself
        the letter remains open — and its property falls from `DUE_DILIGENCE`
        to `REPORTABLE`."
        PRD §3.2: "The sweep response enumerates what it touched, as
        `transitioned_property_ids`, `expired_letter_ids`, and
        `reportable_property_ids`."

        Design: Corner/state_machines/sweep_expires_letter_and_advances_property
        """
        prop, letter = self._dormant_with_letter()
        set_clock("2026-08-31T00:00:00Z")  # exactly the response deadline
        run_sweep()
        on_day = get_success_data(api.get_letter(letter["id"], READER), 200)
        assert on_day["status"] == "SENT", "deadline day itself stays open"
        set_clock("2026-09-01T00:00:00Z")
        result = run_sweep()
        assert letter["id"] in result["expired_letter_ids"]
        assert prop["id"] in result["reportable_property_ids"]
        expired = get_success_data(api.get_letter(letter["id"], READER), 200)
        assert expired["status"] == "EXPIRED"
        assert get_property(prop["id"])["status"] == "REPORTABLE"


class TestCustomRuleConstants:
    def test_custom_years_and_threshold_applied(self, api):
        """PRD §3.2: "Dormancy policy is configuration, not code. A
        `HolderAdmin` authors a **dormancy rule** for a pairing of
        `state_code` and `property_type`, setting `dormancy_years` — the years
        of owner silence, an integer from 1 to 15 inclusive, after which
        property is presumed abandoned — together with an effective window
        delimited by `effective_from` and an optional `effective_to`"
        PRD §3.3: "And the property's `original_value_cents` must be at or
        above the rule's `dd_threshold_cents`; below it, due diligence is not
        required and creation is refused with `ERR_DUE_DILIGENCE_NOT_REQUIRED`."

        Design: Corner/calculations/custom_rule_constants_applied
        """
        create_rule(
            property_type="INSURANCE_PROCEEDS", dormancy_years=5,
            effective_from="2019-01-01", dd_threshold_cents=25000,
        )
        owner = create_owner()
        prop = create_property(
            owner["id"], property_type="INSURANCE_PROCEEDS",
            original_value_cents=20000, last_contact_date="2020-06-01",
        )
        set_clock("2025-06-01T00:00:00Z")  # exact 5-year anniversary
        run_sweep()
        assert get_property(prop["id"])["status"] == "ACTIVE"
        set_clock("2025-06-02T00:00:00Z")
        run_sweep()
        after = get_property(prop["id"])
        assert after["status"] == "DORMANT"
        assert after["dormancy_date"] == "2025-06-02"
        resp = api.create_letter(prop["id"], CO_H)
        validate_error(resp, ApiErrorId.ERR_DUE_DILIGENCE_NOT_REQUIRED, 422)


class TestApplicableReportWindowRollForward:
    def test_missed_cycle_rolls_window_forward(self, api):
        """PRD §3.2: "If that cycle's due date is already in the past relative
        to the current logical date, the cycle rolls forward one year at a time
        until the due date is no longer in the past — on or after the current
        date — and that cycle's due date becomes the `applicable_due_date`."
        PRD §3.2: "A due-diligence letter's permitted send window then opens
        `dd_window_max_days` before the applicable due date and closes
        `dd_window_min_days` before it, both boundary days inclusive."

        Design: Corner/calculations/applicable_report_window_rolls_forward
        """
        create_rule()
        owner = create_owner()
        prop = create_property(owner["id"])
        run_sweep()  # DORMANT, dormancy_date 2026-03-16
        set_clock("2026-12-01T00:00:00Z")  # due 2026-11-01 already past
        early = api.create_letter(prop["id"], CO_H)
        validate_error(early, ApiErrorId.ERR_DUE_DILIGENCE_WINDOW_VIOLATION, 409)
        set_clock("2027-06-01T00:00:00Z")  # inside the rolled 2027 window
        letter = validate_success(api.create_letter(prop["id"], CO_H), 201)
        assert letter["applicable_due_date"] == "2027-11-01"
        assert letter["sent_date"] == "2027-06-01"
        assert letter["response_deadline"] == "2027-07-01"
