"""Entity CRUD, defaults, required-field and FK validation, calculations — breadth."""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, create_applicant_payload, create_property_payload,
)
from test_helpers.fixtures import (
    PM, create_owner, create_property, create_unit, create_approved_applicant,
    create_draft_lease, collect_deposit, post_rent_charge, fund_trust,
    setup_active_lease,
)
from test_helpers.api_client import api_client


class TestEntityCreation:
    def test_create_property_sets_computed_ledger_defaults(self, api):
        """PRD §2.8: "a freshly created property reports a trust balance of 0, a
        distributable amount of 0, a unit count of 0, and a version of 1."

        Design: Corner/entities/create_property_returns_201_with_computed_ledger_defaults
        """
        owner = create_owner()
        res = api.create_property(
            create_property_payload(owner["id"], name="Cedar", state_code="IL",
                                    address="9 Cedar"),
            PM,
        )
        prop = validate_success(res, 201)
        assert prop["trust_balance_cents"] == 0
        assert prop["distributable_cents"] == 0
        assert prop["unit_count"] == 0
        assert prop["version"] == 1

    def test_create_applicant_missing_credit_score_rejected(self, api):
        """PRD §3.2: "The credit score must be in the inclusive range 300 to 850".
        PRD §2.6: "Request-shape validation — required fields present ... — is
        checked fifth, yielding ERR_INVALID_REQUEST."

        Design: Corner/entities/create_applicant_missing_required_field_returns_invalid_request
        """
        unit = create_unit()
        payload = {
            "full_name": "NoScore", "email": "ns@x.com", "unit_id": unit["id"],
            "annual_income_cents": 12000000, "requested_rent_cents": 200000,
        }
        res = api.create_applicant(payload, PM)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_create_applicant_credit_score_out_of_range_rejected(self, api):
        """PRD §2.6: "required fields present, types and enum members valid, and
        numeric ranges respected (for example a credit_score between 300 and 850
        inclusive ...) — is checked fifth, yielding ERR_INVALID_REQUEST."

        Design: Corner/entities/create_applicant_credit_score_out_of_range_returns_invalid_request
        """
        unit = create_unit()
        res = api.create_applicant(
            create_applicant_payload(unit["id"], credit_score=900), PM)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_create_unit_defaults_to_vacant_ready(self, api):
        """PRD §3.1: "A unit's occupancy_status is system-managed and begins life
        as VACANT_READY". PRD §3.1: "A unit also exposes active_lease_id, a computed
        forward pointer to the id of the lease currently occupying it, or null when
        none does".

        Design: Corner/entities/create_unit_default_occupancy_vacant_ready
        """
        prop = create_property()
        res = api.create_unit(
            {"property_id": prop["id"], "label": "Apt 4", "market_rent_cents": 200000},
            PM)
        unit = validate_success(res, 201)
        assert unit["occupancy_status"] == "VACANT_READY"
        assert unit["active_lease_id"] is None

    def test_input_ledger_field_ignored_reserve_floor_kept(self, api):
        """PRD §2.8: "Because trust_balance_cents, distributable_cents, and
        unit_count on a property are server-computed, a freshly created property
        reports a trust balance of 0, a distributable amount of 0, a unit count of
        0". PRD §3.1: "At creation the operator may set reserve_floor_cents, the
        minimum trust balance the owner wants retained; it defaults to 0."

        Design: Corner/entities/system_fields_input_ignored_on_create_property
        """
        owner = create_owner()
        res = api.create_property(
            create_property_payload(owner["id"], name="Pr6", state_code="TX",
                                    address="Ad6", reserve_floor_cents=5000),
            PM)
        prop = validate_success(res, 201)
        assert prop["trust_balance_cents"] == 0
        assert prop["reserve_floor_cents"] == 5000
        assert prop["distributable_cents"] == 0


class TestNotFoundAndFk:
    def test_get_nonexistent_property_returns_not_found(self, api):
        """PRD §2.5: "When a request addresses a resource by an id in its path and
        no such resource exists, the request is rejected with ERR_NOT_FOUND."

        Design: Corner/entities/get_property_nonexistent_id_returns_not_found
        """
        res = api.get_property(NON_EXISTENT_UUID, PM)
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_property_unknown_owner_returns_fk_not_found(self, api):
        """PRD §2.5: "When a creation request carries a foreign key in its body that
        does not resolve to an existing record — any of owner_id, property_id,
        unit_id, applicant_id, lease_id, or renewed_from_lease_id — the request is
        rejected with ERR_FK_NOT_FOUND."

        Design: Corner/entities/create_property_unknown_owner_returns_fk_not_found
        """
        res = api.create_property(
            create_property_payload(NON_EXISTENT_UUID, name="Ghost",
                                    state_code="TX", address="Z"),
            PM)
        validate_error(res, "ERR_FK_NOT_FOUND")


class TestListing:
    def test_units_pagination_envelope(self, api):
        """PRD §2.3: "The limit parameter caps the number of items returned".
        PRD §2.3: "Every list response reports limit, offset, total_count, and
        has_more inside the meta object of the envelope."

        Two units, limit=1 -> one item returned, total_count 2, has_more true.

        Design: Corner/entities/list_units_paginated_envelope_shape
        """
        prop = create_property()
        create_unit(property_id=prop["id"], label="A", market_rent_cents=200000)
        create_unit(property_id=prop["id"], label="B", market_rent_cents=210000)
        res = api.list_units(PM, params={"property_id": prop["id"], "limit": 1,
                                         "offset": 0})
        data, meta = validate_paginated(res)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1


class TestCalculations:
    def test_deposit_interest_il_three_completed_years(self, api):
        """PRD §3.6: "Illinois at 0.0050". PRD §3.6: "the number of accruing years
        is the count of whole days between the collection date and the settlement
        date, divided by 365 and taken as the floor ... The accrued interest is the
        collected principal multiplied by the state rate multiplied by that
        whole-year count, rounded half-up to whole cents".

        IL 0.005, 400000 collected 2022-06-01, settled 2025-06-15 -> 3 full years
        -> interest round(400000*0.005*3)=6000; arrears 0 -> refund 406000.

        Design: Corner/calculations/deposit_interest_il_three_completed_years
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="IL",
                               reserve_floor_cents=0)
        fund_trust(prop["id"], 500000)
        unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
        app = create_approved_applicant(unit["id"])
        lease = create_draft_lease(unit["id"], app["id"], start_date="2022-06-01",
                                   end_date="2025-06-01", monthly_rent_cents=200000)
        dep = collect_deposit(lease["id"], collected_cents=400000,
                              collected_date="2022-06-01")
        get_success_data(api.sign_lease(lease["id"], PM))
        get_success_data(api.expire_lease(lease["id"], {"as_of_date": "2025-06-01"}, PM))
        settled = get_success_data(api.settle_security_deposit(
            dep["id"], {"settlement_date": "2025-06-15"}, PM))
        assert settled["interest_accrued_cents"] == 6000
        assert settled["refund_cents"] == 406000
        assert settled["status"] == "SETTLED"

    def test_deposit_interest_zero_in_ca(self, api):
        """PRD §3.6: "California, Florida, and Texas accrue nothing at all, so a
        deposit on a property in any of those three states earns zero interest no
        matter how long it was held."

        CA, 300000 collected 2023-06-01, settled 2026-06-15 (3 years) -> interest 0;
        arrears 0 -> refund 300000.

        Design: Corner/calculations/deposit_interest_zero_rate_state_ca
        """
        owner = create_owner()
        prop = create_property(owner_id=owner["id"], state_code="CA",
                               reserve_floor_cents=0)
        fund_trust(prop["id"], 400000)
        unit = create_unit(property_id=prop["id"], market_rent_cents=200000)
        app = create_approved_applicant(unit["id"])
        lease = create_draft_lease(unit["id"], app["id"], start_date="2023-06-01",
                                   end_date="2026-06-01", monthly_rent_cents=200000)
        dep = collect_deposit(lease["id"], collected_cents=300000,
                              collected_date="2023-06-01")
        get_success_data(api.sign_lease(lease["id"], PM))
        get_success_data(api.expire_lease(lease["id"], {"as_of_date": "2026-06-01"}, PM))
        settled = get_success_data(api.settle_security_deposit(
            dep["id"], {"settlement_date": "2026-06-15"}, PM))
        assert settled["interest_accrued_cents"] == 0
        assert settled["refund_cents"] == 300000

    def test_payment_overpayment_held_as_credit(self, api):
        """PRD §3.5: "Any money left after every open charge is fully covered is
        recorded as the payment's unapplied_cents and retained as a tenant credit —
        it is never automatically refunded." PRD §3.5: "the portion applied to RENT
        charges is summed into the payment's applied_to_rent_cents".

        250000 against a single 200000 OPEN RENT charge -> applied_to_rent 200000,
        unapplied 50000, lease balance 0.

        Design: Corner/calculations/payment_waterfall_overpayment_credit
        """
        world = setup_active_lease(state_code="TX", market_rent_cents=200000,
                                   deposit_cents=200000)
        lease_id = world["lease"]["id"]
        post_rent_charge(lease_id, amount_cents=200000, period_label="2026-06",
                         due_date="2026-06-01")
        res = api.create_payment(
            {"lease_id": lease_id, "amount_cents": 250000,
             "received_date": "2026-06-05"}, PM)
        payment = validate_success(res, 201)
        assert payment["unapplied_cents"] == 50000
        assert payment["applied_to_rent_cents"] == 200000
        lease = get_success_data(api.get_lease(lease_id, PM))
        assert lease["balance_due_cents"] == 0
