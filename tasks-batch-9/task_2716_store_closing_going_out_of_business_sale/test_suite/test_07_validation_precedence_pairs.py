"""Two requests that break several rules at once, and which error they report.

The validation order decides both cases: a suspended store with a dead licence
reports the state error, and an undisclosed consignment that would also breach the
cost cap reports the disclosure error first and the cap error only afterwards.
"""
from test_helpers import (
    ApiErrorId,
    activate_markdown_stage,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    create_engagement,
    create_jurisdiction,
    decide_license,
    file_consignment_disclosure,
    make_compliance_headers,
    make_consultant_headers,
    pin_clock,
    propose_consignment,
    read_engagement,
    read_store,
    revoke_license,
    submit_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
FEE_BASED_LIQUIDATOR = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "LIQUIDATOR",
    "shared_expense_liquidator_pct": 0, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}


def _read_stage(stage_id):
    return validate_success(
        api_client.get_markdown_stage(stage_id, make_consultant_headers())
    )


def _read_consignment(consignment_id):
    return validate_success(
        api_client.get_augmentation_consignment(
            consignment_id, make_consultant_headers()
        )
    )


def _suspended_store_with_a_revoked_licence_and_an_armed_stage():
    """A store whose licence was pulled while stage 2 was still armed behind it.

    The revocation leaves three rules broken by one activate call: the store is no
    longer SELLING, no APPROVED licence covers the window, and the engagement has
    taken a strike.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-901", address_line="60 Bay St",
    )
    add_inventory_lot(
        store["id"], category="APPAREL", source="ORIGINAL", units_initial=1000,
        unit_cost_cents=2000, unit_retail_cents=5000,
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0901",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    stage_one = add_markdown_stage(
        store["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.3,
        window_start_date="2026-09-15", window_end_date="2026-09-29",
    )
    stage_two = add_markdown_stage(
        store["id"], stage_index=2, discount_pct=0.4, sell_through_target_pct=0.6,
        window_start_date="2026-09-29", window_end_date="2026-10-13",
    )
    activate_markdown_stage(stage_one["id"])
    revoke_license(
        license_row["id"],
        revoked_reason="Licence pulled after advertising complaint",
    )
    return {
        "engagement": engagement,
        "store": store,
        "license": license_row,
        "stage_two": stage_two,
    }


class TestStoreStateBeatsLicenceCoverage:
    def test_the_activate_call_reports_the_store_state_error(self):
        """State admissibility is checked before licence coverage, so the refusal
        names the store.

        The PRD says: "When several rules could reject the same request, they are
        evaluated in one strict order and the first rule whose condition holds
        returns its error; no later rule is evaluated and no partial write occurs."

        Design: Difficulty/priority_pair_validation_conflict/store_state_error_precedes_license_safety_error_on_stage_activation
        """
        scenario = _suspended_store_with_a_revoked_licence_and_an_armed_stage()
        response = api_client.activate_markdown_stage(
            scenario["stage_two"]["id"], make_consultant_headers()
        )
        validate_error(response, ApiErrorId.ERR_STORE_NOT_SELLING.value, 409)

    def test_the_licence_coverage_error_is_never_reported_for_this_request(self):
        """No APPROVED licence covers the window, yet that rule never gets to speak.

        The PRD says: "Licence coverage on stage activation, sales-day review, and
        store resume — otherwise `ERR_LICENSE_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/store_state_error_precedes_license_safety_error_on_stage_activation
        """
        scenario = _suspended_store_with_a_revoked_licence_and_an_armed_stage()
        response = api_client.activate_markdown_stage(
            scenario["stage_two"]["id"], make_consultant_headers()
        )
        error = validate_error(response, ApiErrorId.ERR_STORE_NOT_SELLING.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value
        license_row = validate_success(
            api_client.get_gob_license(
                scenario["license"]["id"], make_compliance_headers()
            )
        )
        assert license_row["license_status"] == "REVOKED"
        assert read_store(scenario["store"]["id"])["store_status"] == "SUSPENDED"

    def test_the_restricted_posture_error_is_not_reported_either(self):
        """Activating an already-authored stage is not one of the restricted
        operations.

        The PRD says: "Activating a stage that was already authored remains
        permitted, and proposing a new consignment remains permitted."

        Design: Difficulty/priority_pair_validation_conflict/store_state_error_precedes_license_safety_error_on_stage_activation
        """
        scenario = _suspended_store_with_a_revoked_licence_and_an_armed_stage()
        response = api_client.activate_markdown_stage(
            scenario["stage_two"]["id"], make_consultant_headers()
        )
        error = validate_error(response, ApiErrorId.ERR_STORE_NOT_SELLING.value, 409)
        assert (
            error["error_id"] != ApiErrorId.ERR_ENGAGEMENT_COMPLIANCE_RESTRICTED.value
        )
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["compliance_posture"] == "RESTRICTED"

    def test_the_refused_activation_leaves_the_stage_exactly_as_it_was(self):
        """The stage stays ARMED and is never stamped with an activation instant.

        The PRD says: "Putting a stage into force takes it `ARMED → ACTIVE` and
        stamps `activated_at` with the current logical-clock instant."

        Design: Difficulty/priority_pair_validation_conflict/store_state_error_precedes_license_safety_error_on_stage_activation
        """
        scenario = _suspended_store_with_a_revoked_licence_and_an_armed_stage()
        api_client.activate_markdown_stage(
            scenario["stage_two"]["id"], make_consultant_headers()
        )
        stage_two = _read_stage(scenario["stage_two"]["id"])
        assert stage_two["stage_status"] == "ARMED"
        assert stage_two["activated_at"] is None


def _undisclosed_consignment_that_would_also_breach_the_cap():
    """One 800,000-cent consignment against a 5,000,000-cent original base.

    The store's jurisdiction both requires a disclosure and caps augmentation at
    0.10, and receiving these 400 units would take the ratio to 0.1600, so the
    single receive call breaks two rules at once.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-1001", address_line="30 Pier Ave",
    )
    add_inventory_lot(
        store["id"], category="APPAREL", source="ORIGINAL", units_initial=1000,
        unit_cost_cents=2000, unit_retail_cents=5000,
    )
    add_inventory_lot(
        store["id"], category="ELECTRONICS", source="ORIGINAL", units_initial=200,
        unit_cost_cents=15000, unit_retail_cents=30000,
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-1001",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    consignment = propose_consignment(
        store["id"], supplier_name="Overstock Partners", category="APPAREL",
        units_supplied=400, unit_cost_cents=2000, unit_retail_cents=5000,
        delivery_window_start_date="2026-09-20",
        delivery_window_end_date="2026-09-21",
    )
    return {"store": store, "consignment": consignment}


class TestDisclosureBeatsAugmentationCap:
    def test_the_undisclosed_receive_reports_the_missing_disclosure(self):
        """The disclosure gate is reached first, so the cap never speaks.

        The PRD says: "Augmentation disclosure on consignment receipt — otherwise
        `ERR_AUGMENTATION_DISCLOSURE_MISSING`."

        Design: Difficulty/priority_pair_validation_conflict/augmentation_disclosure_safety_precedes_cap_fiscal_error_on_receive
        """
        scenario = _undisclosed_consignment_that_would_also_breach_the_cap()
        response = api_client.receive_consignment(
            scenario["consignment"]["id"], make_consultant_headers()
        )
        error = validate_error(
            response, ApiErrorId.ERR_AUGMENTATION_DISCLOSURE_MISSING.value, 409
        )
        assert error["error_id"] != ApiErrorId.ERR_AUGMENTATION_CAP_EXCEEDED.value

    def test_only_after_the_disclosure_is_filed_does_the_cap_refuse_the_same_call(self):
        """The identical receive now reports the fiscal breach at 422.

        The PRD says: "The comparison is inclusive at the cap: a post-receipt ratio
        exactly equal to the jurisdiction's `max_augmentation_ratio` is accepted, and
        only a ratio strictly greater than it is refused, with
        `ERR_AUGMENTATION_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/augmentation_disclosure_safety_precedes_cap_fiscal_error_on_receive
        """
        scenario = _undisclosed_consignment_that_would_also_breach_the_cap()
        consignment_id = scenario["consignment"]["id"]
        api_client.receive_consignment(consignment_id, make_consultant_headers())
        disclosed = file_consignment_disclosure(consignment_id, "NY-AUG-99")
        assert disclosed["consignment_status"] == "DISCLOSURE_FILED"
        response = api_client.receive_consignment(
            consignment_id, make_consultant_headers()
        )
        validate_error(response, ApiErrorId.ERR_AUGMENTATION_CAP_EXCEEDED.value, 422)

    def test_neither_refusal_writes_a_single_byte_of_augmentation(self):
        """No lot, no cost value, no unit count — the consignment stays where it was.

        The PRD says: "The augmentation cap is then evaluated, and it is evaluated
        before a single byte is written, so a breach creates nothing at all."

        Design: Difficulty/priority_pair_validation_conflict/augmentation_disclosure_safety_precedes_cap_fiscal_error_on_receive
        """
        scenario = _undisclosed_consignment_that_would_also_breach_the_cap()
        consignment_id = scenario["consignment"]["id"]
        api_client.receive_consignment(consignment_id, make_consultant_headers())
        file_consignment_disclosure(consignment_id, "NY-AUG-99")
        api_client.receive_consignment(consignment_id, make_consultant_headers())
        consignment = _read_consignment(consignment_id)
        assert consignment["consignment_status"] == "DISCLOSURE_FILED"
        lots, _meta = validate_paginated(
            api_client.list_consignment_inventory_lots(
                consignment_id, make_consultant_headers()
            )
        )
        assert lots == []
        store = read_store(scenario["store"]["id"])
        assert store["augmentation_cost_value_cents"] == 0
        assert store["units_initial_total"] == 1200
