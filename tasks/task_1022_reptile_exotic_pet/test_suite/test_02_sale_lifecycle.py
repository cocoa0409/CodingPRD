"""Sale confirm/void lifecycle: animal-availability gate and conservation invariants."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    setup_available_animal, create_customer, create_draft_sale,
    intake_animal, create_species, start_quarantine_animal,
)

_SALES = TEST_USERS["sales_associate_headers"]


class TestSaleConfirmRequiresAvailableAnimal:
    def test_confirm_available_animal_reserves_it(self, api):
        """PRD §3.4: "On a successful confirm the sale moves from `DRAFT` to `CONFIRMED`, the animal moves from `AVAILABLE` to `RESERVED` (decrementing the store's available-animal count), the final `sale_price_cents` is pinned"

        Design: Difficulty/cross_entity_state_dependency/sale_confirm_requires_animal_available
        """
        _, animal = setup_available_animal(
            api, animal_overrides={"list_price_cents": 9000, "acquisition_cost_cents": 2000})
        customer = create_customer(api, email="confirm-ok@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"])
        confirmed = validate_success(api.confirm_sale(sale["id"], headers=_SALES))
        assert confirmed["status"] == "CONFIRMED"
        after_animal = get_success_data(api.get_animal(animal["id"], headers=_SALES))
        assert after_animal["status"] == "RESERVED"

    def test_confirm_rejected_when_animal_not_available(self, api):
        """PRD §3.4: "A `SalesAssociate` confirms a `DRAFT` sale only when the animal is `AVAILABLE`; if it is not, the confirm is rejected with `ERR_ANIMAL_NOT_AVAILABLE"

        Design: Difficulty/cross_entity_state_dependency/sale_confirm_requires_animal_available
        """
        species = create_species(api, is_regulated=False, permit_class="NONE",
                                 min_quarantine_days=0, warranty_days=30)
        # animal left in QUARANTINE (never cleared) -> not AVAILABLE
        animal, _qr = start_quarantine_animal(api, species["id"],
                                              list_price_cents=9000, acquisition_cost_cents=2000)
        customer = create_customer(api, email="confirm-notavail@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"])
        resp = api.confirm_sale(sale["id"], headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE.value)
        after = get_success_data(api.get_sale(sale["id"], headers=_SALES))
        assert after["status"] == "DRAFT"


class TestAvailableAnimalConservation:
    def test_void_confirmed_sale_releases_animal_to_available(self, api):
        """PRD §3.4: "or void it, moving the sale to `VOIDED` and releasing the animal from `RESERVED` back to `AVAILABLE` (restoring the available-animal count)."

        Design: Difficulty/compensating_invariant/available_animal_conservation_confirm_then_void
        """
        _, animal = setup_available_animal(
            api, animal_overrides={"list_price_cents": 11000, "acquisition_cost_cents": 3000})
        customer = create_customer(api, email="void1@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"])
        get_success_data(api.confirm_sale(sale["id"], headers=_SALES))
        voided = validate_success(api.void_sale(sale["id"], headers=_SALES))
        assert voided["status"] == "VOIDED"
        after = get_success_data(api.get_animal(animal["id"], headers=_SALES))
        assert after["status"] == "AVAILABLE"

    def test_confirm_then_void_returns_animal_to_starting_state(self, api):
        """PRD §3.4: "the animal moves from `AVAILABLE` to `RESERVED` (decrementing the store's available-animal count)"
        PRD §3.4: "releasing the animal from `RESERVED` back to `AVAILABLE` (restoring the available-animal count)."

        Design: Difficulty/compensating_invariant/available_animal_conservation_confirm_then_void
        """
        _, animal = setup_available_animal(
            api, animal_overrides={"list_price_cents": 11000, "acquisition_cost_cents": 3000})
        customer = create_customer(api, email="void2@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"])
        get_success_data(api.confirm_sale(sale["id"], headers=_SALES))
        reserved = get_success_data(api.get_animal(animal["id"], headers=_SALES))
        assert reserved["status"] == "RESERVED"
        get_success_data(api.void_sale(sale["id"], headers=_SALES))
        released = get_success_data(api.get_animal(animal["id"], headers=_SALES))
        assert released["status"] == "AVAILABLE"


class TestSaleInvalidTransitions:
    def test_fulfill_from_draft_returns_invalid_state(self, api):
        """PRD §3.4: "From `CONFIRMED`, a `SalesAssociate` may fulfill the sale — moving it to `FULFILLED` and the animal from `RESERVED` to `SOLD"

        Design: Corner/state_machines/fulfill_from_draft_returns_invalid_state
        """
        species = create_species(api, min_quarantine_days=0, warranty_days=30)
        animal = intake_animal(api, species["id"], list_price_cents=10000,
                               acquisition_cost_cents=3000)
        customer = create_customer(api, email="fulfill-draft@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"])
        resp = api.fulfill_sale(sale["id"], headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
