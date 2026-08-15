"""Household eligibility cycling and the gated issuance-recording pipeline."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_issuance,
    create_agency,
    create_eligible_household,
    create_event,
    create_household,
    create_issuance_payload,
    get_household,
    get_inventory,
    init_inventory,
    make_agency_coordinator_headers,
    open_event,
    record_issuance,
    setup_completed_event,
    setup_event_with_issuance,
    setup_published_allocation,
    size_entry,
    supply_line,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]


class TestEligibilityCycle:
    def test_household_eligibility_redetermination_cycle(self, api):
        """PRD §3.6: "Four edges are legal: `PENDING_REVIEW` → `ELIGIBLE` and `INELIGIBLE` → `ELIGIBLE`, each requiring `consent_on_file` to be true (a decision without consent is rejected with `ERR_CONSENT_REQUIRED`); `PENDING_REVIEW` → `INELIGIBLE`; and `ELIGIBLE` → `INELIGIBLE`. The cycle is deliberate — eligibility re-determination loops between `ELIGIBLE` and `INELIGIBLE` are legal — and any transition outside these four edges is rejected with `ERR_INVALID_HOUSEHOLD_STATE`."
        PRD §3.6: "A `PrivacyOfficer` may revise `children_sizes` — which recomputes `monthly_allotment_units` — along with `consent_on_file` and `privacy_restricted`, and may request an eligibility decision by supplying `eligibility_status` with a free-text `eligibility_reason` that is stored with the decision."

        Design: Corner/state_machines/household_eligibility_redetermination_cycle
        """
        household = create_household(household_code="HH-CYC",
                                     children_sizes=["SIZE_2"],
                                     consent_on_file=True)
        assert household["eligibility_status"] == "PENDING_REVIEW"

        first = validate_success(
            api.patch_household(household["id"],
                                {"eligibility_status": "ELIGIBLE",
                                 "eligibility_reason": "intake verified"},
                                PRIVACY),
            200,
        )
        assert first["eligibility_status"] == "ELIGIBLE"
        assert first["eligibility_reason"] == "intake verified"

        second = validate_success(
            api.patch_household(household["id"],
                                {"eligibility_status": "INELIGIBLE",
                                 "eligibility_reason": "moved out of area"},
                                PRIVACY),
            200,
        )
        assert second["eligibility_status"] == "INELIGIBLE"

        third = validate_success(
            api.patch_household(household["id"],
                                {"eligibility_status": "ELIGIBLE",
                                 "eligibility_reason": "returned"},
                                PRIVACY),
            200,
        )
        assert third["eligibility_status"] == "ELIGIBLE", (
            "The INELIGIBLE → ELIGIBLE loop is a legal re-determination"
        )
        assert third["eligibility_reason"] == "returned", (
            "The reason stored is the one supplied with the latest decision"
        )

    def test_household_eligible_requires_consent_rejected(self, api):
        """PRD §3.6: "Four edges are legal: `PENDING_REVIEW` → `ELIGIBLE` and `INELIGIBLE` → `ELIGIBLE`, each requiring `consent_on_file` to be true (a decision without consent is rejected with `ERR_CONSENT_REQUIRED`); `PENDING_REVIEW` → `INELIGIBLE`; and `ELIGIBLE` → `INELIGIBLE`."

        Design: Corner/state_machines/household_eligible_requires_consent_rejected
        """
        household = create_household(household_code="HH-NC",
                                     children_sizes=["SIZE_1"])
        assert household["consent_on_file"] is False

        resp = api.patch_household(household["id"],
                                   {"eligibility_status": "ELIGIBLE"},
                                   PRIVACY)
        validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED)

        household_after = get_household(household["id"])
        assert household_after["eligibility_status"] == "PENDING_REVIEW"


class TestIssuanceSafetyGates:
    def test_issuance_for_ineligible_household_rejected(self, api):
        """PRD §3.5: "the household's `eligibility_status` must be `ELIGIBLE` (otherwise `ERR_HOUSEHOLD_NOT_ELIGIBLE`)"

        Design: Corner/validations/issuance_for_ineligible_household_rejected
        """
        allocation = setup_published_allocation(size_code="SIZE_1", stock_units=100)
        # Consent is on file but no eligibility decision has been made: the
        # household remains PENDING_REVIEW, which is not ELIGIBLE.
        household = create_household(household_code="HH-N1",
                                     children_sizes=["SIZE_1"],
                                     consent_on_file=True)
        event = create_event(allocation["agency"]["id"], site_name="N-Site")
        open_event(event["id"])

        resp = api.record_issuance(
            event["id"],
            create_issuance_payload(household["id"],
                                    lines=[supply_line("SIZE_1", 10)]),
            PRIVACY,
        )
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_NOT_ELIGIBLE)

    def test_privacy_error_beats_duplicate_error(self, api):
        """PRD §3.5: "The gates fire in the pipeline order of §2.6: the event must be `OPEN` (otherwise `ERR_EVENT_NOT_OPEN`); if the household is flagged `privacy_restricted`, only a `PrivacyOfficer` may record for it (otherwise `ERR_PRIVACY_RESTRICTED`); the household's `eligibility_status` must be `ELIGIBLE` (otherwise `ERR_HOUSEHOLD_NOT_ELIGIBLE`); and each household may receive at most one issuance per event (a second attempt yields `ERR_DUPLICATE_HOUSEHOLD_ISSUANCE`)."
        PRD §2.10: "A household flagged `privacy_restricted` carries a stricter rule: only the `PrivacyOfficer` may record supplies given to that household, even at events where an `AgencyCoordinator` would otherwise serve families."

        Design: Difficulty/priority_pair_validation_conflict/issuance_privacy_error_beats_duplicate_error
        """
        scenario = setup_event_with_issuance(
            size_code="SIZE_1", stock_units=500, issue_quantity=10,
            children_sizes=["SIZE_1", "SIZE_1"], privacy_restricted=True,
            record=True,
        )
        first = scenario["issuance"]
        assert first["recorded_by_role"] == "PrivacyOfficer", (
            "The privacy audit trail captures the recorder's role"
        )

        # A second issuance for the same household at the same event by the
        # hosting agency's coordinator trips both the privacy gate (safety) and
        # the duplicate gate (uniqueness); safety is evaluated first.
        resp = api.record_issuance(
            scenario["event"]["id"],
            create_issuance_payload(scenario["household"]["id"],
                                    lines=[supply_line("SIZE_1", 10)]),
            make_agency_coordinator_headers(scenario["agency"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRIVACY_RESTRICTED)

    def test_rejected_privacy_issuance_leaves_consumption_unchanged(self, api):
        """PRD §3.6: "`consumed_this_month_units` is the sum of `total_units` over the household's `FULFILLED` issuances whose `fulfilled_at` falls in that month, plus the sum over `RECORDED` issuances whose `created_at` falls in that month; `VOIDED` issuances are excluded entirely."

        Design: Difficulty/priority_pair_validation_conflict/issuance_privacy_error_beats_duplicate_error
        """
        scenario = setup_event_with_issuance(
            size_code="SIZE_1", stock_units=500, issue_quantity=10,
            children_sizes=["SIZE_1", "SIZE_1"], privacy_restricted=True,
            record=True,
        )

        resp = api.record_issuance(
            scenario["event"]["id"],
            create_issuance_payload(scenario["household"]["id"],
                                    lines=[supply_line("SIZE_1", 10)]),
            make_agency_coordinator_headers(scenario["agency"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRIVACY_RESTRICTED)

        household = get_household(scenario["household"]["id"])
        assert household["consumed_this_month_units"] == 10, (
            "Only the original 10-unit RECORDED issuance counts toward consumption"
        )
        _data, meta = validate_paginated(
            api.list_event_issuances(scenario["event"]["id"], ADMIN))
        assert meta["total_count"] == 1, "The rejected recording persists nothing"


class TestAllotmentBoundary:
    def _setup_at_boundary(self, api):
        """60 of a 100-unit allotment already FULFILLED; a second event OPEN."""
        scenario = setup_completed_event(
            size_code="SIZE_1", stock_units=1000, issue_quantity=60,
            children_sizes=["SIZE_1", "SIZE_1"], site_name="B-Site",
            event_starts="2026-08-10T09:00:00Z",
            event_ends="2026-08-10T10:00:00Z",
        )
        household = get_household(scenario["household"]["id"])
        assert household["monthly_allotment_units"] == 100
        assert household["consumed_this_month_units"] == 60
        event2 = create_event(
            scenario["agency"]["id"], site_name="B-Site",
            starts_at="2026-08-11T09:00:00Z", ends_at="2026-08-11T10:00:00Z",
        )
        open_event(event2["id"])
        return scenario, event2

    def test_issuance_exactly_at_remaining_allotment_succeeds(self, api):
        """PRD §3.6: "The household's remaining allotment is `monthly_allotment_units` minus that consumption, and an issuance whose requested total exceeds the remainder is rejected with `ERR_ALLOTMENT_EXCEEDED` — a request exactly equal to the remainder is allowed, and one unit above it is not."

        Design: Difficulty/boundary_precision_check/allotment_exact_remaining_boundary
        """
        scenario, event2 = self._setup_at_boundary(api)

        # remaining = 100 - 60 = 40; a request of exactly 40 is allowed.
        issuance = record_issuance(
            event2["id"], scenario["household"]["id"],
            [supply_line("SIZE_1", 40)],
        )
        assert_issuance(issuance)
        assert issuance["status"] == "RECORDED"
        assert issuance["total_units"] == 40

        household = get_household(scenario["household"]["id"])
        assert household["consumed_this_month_units"] == 100, (
            "60 fulfilled + 40 recorded exactly exhausts the 100-unit allotment"
        )

    def test_one_unit_above_remaining_allotment_rejected(self, api):
        """PRD §3.6: "The household's remaining allotment is `monthly_allotment_units` minus that consumption, and an issuance whose requested total exceeds the remainder is rejected with `ERR_ALLOTMENT_EXCEEDED` — a request exactly equal to the remainder is allowed, and one unit above it is not."

        Design: Difficulty/boundary_precision_check/allotment_exact_remaining_boundary
        """
        scenario, event2 = self._setup_at_boundary(api)
        record_issuance(event2["id"], scenario["household"]["id"],
                        [supply_line("SIZE_1", 40)])

        event3 = create_event(
            scenario["agency"]["id"], site_name="B-Site",
            starts_at="2026-08-12T09:00:00Z", ends_at="2026-08-12T10:00:00Z",
        )
        open_event(event3["id"])
        # remaining is now 0; one unit above it must fail.
        resp = api.record_issuance(
            event3["id"],
            create_issuance_payload(scenario["household"]["id"],
                                    lines=[supply_line("SIZE_1", 1)]),
            PRIVACY,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOTMENT_EXCEEDED)


class TestAllotmentCompensation:
    def test_issuance_void_compensation_restores_allotment(self, api):
        """PRD §3.5: "Either way, voiding increments the issuance's `version` and recomputes the household's `consumed_this_month_units`."
        PRD §3.6: "`consumed_this_month_units` is the sum of `total_units` over the household's `FULFILLED` issuances whose `fulfilled_at` falls in that month, plus the sum over `RECORDED` issuances whose `created_at` falls in that month; `VOIDED` issuances are excluded entirely."

        Design: Corner/state_machines/issuance_void_compensation_restores_allotment
        """
        scenario = setup_event_with_issuance(
            size_code="SIZE_1", stock_units=100, issue_quantity=30, record=True,
        )
        issuance = scenario["issuance"]
        assert get_household(scenario["household"]["id"])["consumed_this_month_units"] == 30

        voided = validate_success(
            api.void_issuance(issuance["id"], {"reason": "recorded in error"},
                              PRIVACY),
            200,
        )
        assert voided["status"] == "VOIDED"

        household = get_household(scenario["household"]["id"])
        assert household["consumed_this_month_units"] == 0, (
            "Voiding removes the issuance from the consumption set entirely"
        )

        entry = size_entry(get_inventory(), "SIZE_1")
        assert entry["on_hand_units"] == 100, "Stock moves only at fulfillment"
        assert entry["reserved_units"] == 100

    def test_issuance_no_allocation_beats_allotment_priority(self, api):
        """PRD §2.6: "Ninth, fiscal rules — and within the fiscal category the declared evaluation order is grant restriction first, then grant budget, then allocation existence, then allocation sufficiency, then stock sufficiency, then household allotment."
        PRD §3.5: "Then the fiscal chain runs per size, in order: a `PUBLISHED` allocation line must exist for the triple of the logical clock's current calendar month, the event's host agency, and the line's size (otherwise `ERR_NO_PUBLISHED_ALLOCATION`); the requested quantity must not exceed that line's unfulfilled remainder — `allocated_units` minus `fulfilled_units` (otherwise `ERR_ALLOCATION_EXCEEDED`); and the quantity must not exceed the inventory's `on_hand_units` for the size (otherwise `ERR_INSUFFICIENT_STOCK`)."

        Design: Corner/validations/issuance_no_allocation_beats_allotment_priority
        """
        init_inventory()
        agency = create_agency(name="Agency Q", agency_code="AG-Q",
                               contact_email="q@x.org", children_served_monthly=300,
                               storage_capacity_units=100000)
        household = create_eligible_household(children_sizes=["SIZE_1"])
        assert household["monthly_allotment_units"] == 50
        event = create_event(agency["id"], site_name="Q-Site")
        open_event(event["id"])

        # No allocation run exists at all, so allocation existence fires before
        # the household-allotment check even though 60 > 50 remaining.
        resp = api.record_issuance(
            event["id"],
            create_issuance_payload(household["id"],
                                    lines=[supply_line("SIZE_1", 60)]),
            PRIVACY,
        )
        validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_ALLOCATION)
