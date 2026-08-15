"""Owner/property registration and dormancy-rule configuration claims."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_owner,
    create_owner_payload,
    create_dormancy_rule_payload,
    create_property_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.fixtures import CO, HA, READER, create_owner, create_rule

CO_H = TEST_USERS["compliance_officer_headers"]
HA_H = TEST_USERS["holder_admin_headers"]


class TestOwnerRegistration:
    def test_owner_create_missing_full_name_rejected(self, api):
        """PRD §3.1: "A `ComplianceOfficer` registers an owner by supplying the
        `full_name`, the `last_known_address` as a free-form single line, and the
        `state_code` — the two-letter state of the last known address, which fixes
        the escheatment jurisdiction that will govern everything the owner later
        leaves behind."
        PRD §2.10: "third, request-body well-formedness — required fields present,
        types matching, enum values in range, date strings parseable, integers
        inside their declared ranges — with any violation rejected as
        `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/owner_create_missing_required_full_name_rejected
        """
        resp = api.create_owner(
            {"last_known_address": "1 Nowhere, CA", "state_code": "CA"}, CO_H
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        data, meta = validate_paginated(api.list_owners(CO_H))
        assert meta["total_count"] == 0, "Rejected create must not persist an owner"

    def test_owner_create_defaults_and_system_fields(self, api):
        """PRD §3.1: "An optional `deceased_date`, an ISO calendar date, may be
        recorded to support later estate claims; when omitted it remains null."
        PRD §2.4: "`id` (string): a unique, server-minted identifier for the
        resource, formatted as a bare UUID with no type prefix."

        Design: Corner/entities/owner_create_defaults_and_system_fields
        """
        resp = api.create_owner(
            create_owner_payload(
                full_name="Def Ault",
                last_known_address="2 A St, Davis, CA",
                state_code="CA",
            ),
            CO_H,
        )
        owner = validate_success(resp, 201)
        assert_owner(owner)
        assert owner["deceased_date"] is None, "omitted deceased_date stays null"
        assert owner["created_at"] == owner["updated_at"], (
            "at creation, updated_at records the same instant as created_at"
        )


class TestDormancyRuleDefaults:
    def test_dormancy_rule_defaults_applied(self, api):
        """PRD §3.2: "The due-diligence threshold `dd_threshold_cents` defaults to
        5000 — fifty dollars — and decides both whether a letter is required before
        reporting and how the sweep treats a dormant property. The letter send
        window is bounded by `dd_window_min_days` and `dd_window_max_days`,
        defaulting to 60 and 180"
        PRD §3.2: "The late-filing penalty schedule defaults to a
        `daily_penalty_cents` of 10000, one hundred dollars per day, escalating to
        a `gross_daily_penalty_cents` of 25000 once lateness runs strictly beyond
        the `gross_negligence_day_threshold` of 30 days, with the whole penalty
        capped at `penalty_cap_pct` — 25 percent by default — of the report's
        provisional total. Late remittance and claim interest accrue at
        `annual_interest_rate_bp` basis points per annum, defaulting to 1200, or
        twelve percent. The reporting calendar defaults to a
        `report_cutoff_month_day` of `06-30` and a `report_due_month_day` of
        `11-01`"

        Design: Corner/entities/dormancy_rule_defaults_applied
        """
        resp = api.create_dormancy_rule(
            create_dormancy_rule_payload(
                state_code="TX",
                property_type="CHECKING",
                dormancy_years=5,
                effective_from="2021-01-01",
            ),
            HA_H,
        )
        rule = validate_success(resp, 201)
        assert rule["dd_threshold_cents"] == 5000
        assert rule["dd_window_min_days"] == 60
        assert rule["dd_window_max_days"] == 180
        assert rule["annual_interest_rate_bp"] == 1200
        assert rule["daily_penalty_cents"] == 10000
        assert rule["gross_daily_penalty_cents"] == 25000
        assert rule["gross_negligence_day_threshold"] == 30
        assert rule["penalty_cap_pct"] == 25
        assert rule["report_cutoff_month_day"] == "06-30"
        assert rule["report_due_month_day"] == "11-01"
        assert rule["effective_to"] is None, "omitted effective_to is open-ended"


class TestPropertyRegistration:
    def test_property_create_invalid_property_type_rejected(self, api):
        """PRD §3.1: "The property type is one of `CHECKING`, `SAVINGS`,
        `BROKERAGE_SHARES`, `UNCASHED_CHECK`, or `INSURANCE_PROCEEDS`."
        PRD §2.10: "third, request-body well-formedness — required fields present,
        types matching, enum values in range, date strings parseable, integers
        inside their declared ranges — with any violation rejected as
        `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/errors/invalid_enum_property_type_rejected
        """
        create_rule()
        owner = create_owner()
        payload = create_property_payload(
            owner_id=owner["id"], property_type="CRYPTO", original_value_cents=5000
        )
        resp = api.create_property(payload, CO_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_property_create_without_applicable_rule_rejected(self, api):
        """PRD §3.1: "And an applicable dormancy rule — one covering the
        property's state and type, effective at the `last_contact_date` per the
        applicability test of §3.2 — must exist; without one, registration fails
        with `ERR_NO_APPLICABLE_DORMANCY_RULE`."

        Design: Corner/errors/property_create_without_rule_rejected
        """
        owner = create_owner()
        payload = create_property_payload(owner_id=owner["id"], original_value_cents=5000)
        resp = api.create_property(payload, CO_H)
        validate_error(resp, ApiErrorId.ERR_NO_APPLICABLE_DORMANCY_RULE, 422)

    def test_property_create_state_mismatch_rejected(self, api):
        """PRD §3.1: "The property's `state_code` must equal the owning owner's
        `state_code`; a mismatch is rejected with `ERR_OWNER_STATE_MISMATCH`."

        Design: Corner/errors/property_state_mismatch_rejected
        """
        create_rule(state_code="NV")  # NV SAVINGS rule exists, owner is CA
        owner = create_owner(state_code="CA")
        payload = create_property_payload(
            owner_id=owner["id"], state_code="NV", original_value_cents=5000
        )
        resp = api.create_property(payload, CO_H)
        validate_error(resp, ApiErrorId.ERR_OWNER_STATE_MISMATCH, 422)


class TestDormancyRuleWindowOverlap:
    def test_rule_adjacency_and_different_property_type_allowed(self, api):
        """PRD §3.2: "Adjacency is expressly permitted — an existing rule whose
        `effective_to` equals the new rule's `effective_from` hands off cleanly
        and is not an overlap."
        PRD §3.2: "Two rules for the same state and property type may not have
        overlapping windows; the attempt is rejected with
        `ERR_DORMANCY_RULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/dormancy_rule_half_open_adjacency_vs_overlap
        """
        create_rule(
            state_code="CA", property_type="CHECKING", dormancy_years=3,
            effective_from="2020-01-01", effective_to="2023-01-01",
        )
        # Adjacent successor: from == prior effective_to -> allowed.
        r2 = api.create_dormancy_rule(
            create_dormancy_rule_payload(
                state_code="CA", property_type="CHECKING", dormancy_years=5,
                effective_from="2023-01-01",
            ),
            HA_H,
        )
        validate_success(r2, 201)
        # Same window as an overlap attempt but a different property_type:
        # the constraint is scoped to the (state_code, property_type) pair.
        r4 = api.create_dormancy_rule(
            create_dormancy_rule_payload(
                state_code="CA", property_type="SAVINGS", dormancy_years=4,
                effective_from="2022-12-31",
            ),
            HA_H,
        )
        validate_success(r4, 201)

    def test_rule_overlapping_window_rejected(self, api):
        """PRD §3.2: "Two rules for the same state and property type may not have
        overlapping windows; the attempt is rejected with
        `ERR_DORMANCY_RULE_OVERLAP`."
        PRD §3.2: "The window is half-open: the rule governs contact dates on or
        after `effective_from` and strictly before `effective_to`, and a null
        `effective_to` leaves the rule open-ended."

        Design: Difficulty/resource_temporal_overlap/dormancy_rule_half_open_adjacency_vs_overlap
        """
        create_rule(
            state_code="CA", property_type="CHECKING", dormancy_years=3,
            effective_from="2020-01-01", effective_to="2023-01-01",
        )
        # effective_from 2022-12-31 falls inside [2020-01-01, 2023-01-01).
        resp = api.create_dormancy_rule(
            create_dormancy_rule_payload(
                state_code="CA", property_type="CHECKING", dormancy_years=4,
                effective_from="2022-12-31",
            ),
            HA_H,
        )
        validate_error(resp, ApiErrorId.ERR_DORMANCY_RULE_OVERLAP, 409)
