"""Regulated-species permit compliance on sale confirm, and revoke cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    create_species, create_customer, create_draft_sale,
    setup_available_animal, start_quarantine_animal,
    create_permit, setup_verified_permit,
)

_SALES = TEST_USERS["sales_associate_headers"]
_SM = TEST_USERS["store_manager_headers"]


class TestConfirmStateBeatsPermit:
    def _regulated_quarantined_sale(self, api, email):
        species = create_species(api, is_regulated=True, permit_class="CLASS_I",
                                 min_quarantine_days=0, warranty_days=30)
        animal, _qr = start_quarantine_animal(api, species["id"],
                                              list_price_cents=40000, acquisition_cost_cents=12000)
        customer = create_customer(api, email=email)  # no permit at all
        sale = create_draft_sale(api, animal["id"], customer["id"])
        return animal, sale

    def test_animal_not_available_beats_missing_permit(self, api):
        """PRD §3.4: "A `SalesAssociate` confirms a `DRAFT` sale only when the animal is `AVAILABLE`; if it is not, the confirm is rejected with `ERR_ANIMAL_NOT_AVAILABLE`, and this check is evaluated before the permit checks."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_permit_referential
        """
        animal, sale = self._regulated_quarantined_sale(api, "state-permit-1@x.com")
        resp = api.confirm_sale(sale["id"], headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE.value)
        after = get_success_data(api.get_sale(sale["id"], headers=_SALES))
        assert after["status"] == "DRAFT"

    def test_state_error_preempts_permit_and_leaves_animal_in_quarantine(self, api):
        """PRD §3.4: "if it is not, the confirm is rejected with `ERR_ANIMAL_NOT_AVAILABLE`, and this check is evaluated before the permit checks."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_permit_referential
        """
        animal, sale = self._regulated_quarantined_sale(api, "state-permit-2@x.com")
        resp = api.confirm_sale(sale["id"], headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE.value)
        after = get_success_data(api.get_animal(animal["id"], headers=_SM))
        assert after["status"] == "QUARANTINE"


class TestPermitRevokeCascade:
    def test_revoke_verified_permit_voids_sale_and_releases_animal(self, api):
        """PRD §3.3: "Revocation cascades: every `CONFIRMED` sale of a regulated animal that cites this permit is moved to `VOIDED`, and each such sale's animal is released from `RESERVED` back to `AVAILABLE`."

        Design: Corner/state_machines/permit_revoke_cascade_voids_confirmed_sale
        """
        species, animal = setup_available_animal(
            api,
            species_overrides={"is_regulated": True, "permit_class": "CLASS_II",
                               "min_quarantine_days": 0, "warranty_days": 30},
            animal_overrides={"list_price_cents": 30000, "acquisition_cost_cents": 9000},
        )
        customer = create_customer(api, email="revoke@x.com")
        permit = setup_verified_permit(api, customer["id"], permit_class="CLASS_II")
        sale = create_draft_sale(api, animal["id"], customer["id"], permit_id=permit["id"])
        get_success_data(api.confirm_sale(sale["id"], headers=_SALES))
        revoked = validate_success(api.revoke_permit(permit["id"], headers=_SM))
        assert revoked["status"] == "REVOKED"
        after_sale = get_success_data(api.get_sale(sale["id"], headers=_SM))
        after_animal = get_success_data(api.get_animal(animal["id"], headers=_SM))
        assert after_sale["status"] == "VOIDED"
        assert after_animal["status"] == "AVAILABLE"


class TestPermitGatesOnConfirm:
    def test_confirm_regulated_without_permit_returns_permit_required(self, api):
        """PRD §3.4: "a missing permit yields `ERR_PERMIT_REQUIRED`, a permit that is not verified or whose class is insufficient yields `ERR_PERMIT_NOT_VERIFIED`, and a permit whose `expiry_date` is at or before the clock yields `ERR_PERMIT_EXPIRED`."

        Design: Corner/validations/confirm_regulated_without_permit_returns_permit_required
        """
        _, animal = setup_available_animal(
            api,
            species_overrides={"is_regulated": True, "permit_class": "CLASS_I",
                               "min_quarantine_days": 0, "warranty_days": 30},
            animal_overrides={"list_price_cents": 40000, "acquisition_cost_cents": 12000},
        )
        customer = create_customer(api, email="no-permit@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"])
        resp = api.confirm_sale(sale["id"], headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_PERMIT_REQUIRED.value)

    def test_confirm_with_unverified_permit_returns_not_verified(self, api):
        """PRD §3.4: "a permit that is not verified or whose class is insufficient yields `ERR_PERMIT_NOT_VERIFIED"

        Design: Corner/validations/confirm_with_unverified_permit_returns_permit_not_verified
        """
        _, animal = setup_available_animal(
            api,
            species_overrides={"is_regulated": True, "permit_class": "CLASS_I",
                               "min_quarantine_days": 0, "warranty_days": 30},
            animal_overrides={"list_price_cents": 45000, "acquisition_cost_cents": 15000},
        )
        customer = create_customer(api, email="unverified@x.com")
        permit = create_permit(api, customer["id"], permit_class="CLASS_I")  # PENDING_VERIFICATION
        sale = create_draft_sale(api, animal["id"], customer["id"], permit_id=permit["id"])
        resp = api.confirm_sale(sale["id"], headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_VERIFIED.value)
