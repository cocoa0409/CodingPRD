"""Quarantine clearance: inclusive date boundary, pass-count and state preconditions."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    create_species, start_quarantine_animal,
)

_VET = TEST_USERS["vet_tech_headers"]
_SM = TEST_USERS["store_manager_headers"]


def _quarantined_with_two_passes(api, min_days, email_suffix):
    species = create_species(api, min_quarantine_days=min_days, warranty_days=30)
    animal, qr = start_quarantine_animal(api, species["id"],
                                         list_price_cents=15000, acquisition_cost_cents=6000)
    get_success_data(api.add_health_check(qr["id"], {"result": "PASS"}, headers=_VET))
    get_success_data(api.add_health_check(qr["id"], {"result": "PASS"}, headers=_VET))
    return animal, qr


class TestQuarantineClearBoundary:
    def test_clear_at_exact_required_until_succeeds(self, api):
        """PRD §3.2: "A `VetTech` may clear an `OPEN` quarantine record only when the logical clock has reached or passed `required_until` (the boundary is inclusive — the exact `required_until` instant qualifies) and `passed_checks_count` is at least 2."
        PRD §3.2: "that clearance bubbles up to move the animal from `QUARANTINE` to `AVAILABLE"

        Design: Difficulty/boundary_precision_check/quarantine_clear_at_exact_required_until
        """
        animal, qr = _quarantined_with_two_passes(api, 14, "exact")
        # start_at = default clock 2026-07-01, min 14 days -> required_until 2026-07-15
        get_success_data(api.set_clock("2026-07-15T00:00:00Z", headers=_SM))
        cleared = validate_success(api.clear_quarantine(qr["id"], headers=_VET))
        assert cleared["status"] == "CLEARED"
        after = get_success_data(api.get_animal(animal["id"], headers=_SM))
        assert after["status"] == "AVAILABLE"

    def test_clear_after_required_until_succeeds(self, api):
        """PRD §3.2: "A `VetTech` may clear an `OPEN` quarantine record only when the logical clock has reached or passed `required_until` (the boundary is inclusive — the exact `required_until` instant qualifies) and `passed_checks_count` is at least 2."

        Design: Difficulty/boundary_precision_check/quarantine_clear_at_exact_required_until
        """
        animal, qr = _quarantined_with_two_passes(api, 14, "after")
        get_success_data(api.set_clock("2026-07-16T00:00:00Z", headers=_SM))  # one day past
        cleared = validate_success(api.clear_quarantine(qr["id"], headers=_VET))
        assert cleared["status"] == "CLEARED"


class TestQuarantineClearPreconditions:
    def test_clear_before_required_until_returns_not_complete(self, api):
        """PRD §3.2: "If either condition fails, the clear is rejected with `ERR_QUARANTINE_NOT_COMPLETE`."

        Design: Corner/state_machines/clear_before_required_until_returns_quarantine_not_complete
        """
        animal, qr = _quarantined_with_two_passes(api, 14, "before")
        get_success_data(api.set_clock("2026-07-14T00:00:00Z", headers=_SM))  # one day early
        resp = api.clear_quarantine(qr["id"], headers=_VET)
        validate_error(resp, ApiErrorId.ERR_QUARANTINE_NOT_COMPLETE.value)
        after = get_success_data(api.get_animal(animal["id"], headers=_SM))
        assert after["status"] == "QUARANTINE"

    def test_clear_with_one_pass_check_returns_not_complete(self, api):
        """PRD §3.2: "A `VetTech` may clear an `OPEN` quarantine record only when the logical clock has reached or passed `required_until` (the boundary is inclusive — the exact `required_until` instant qualifies) and `passed_checks_count` is at least 2."

        Design: Corner/state_machines/clear_with_one_pass_check_returns_quarantine_not_complete
        """
        species = create_species(api, min_quarantine_days=0, warranty_days=30)
        animal, qr = start_quarantine_animal(api, species["id"],
                                             list_price_cents=18000, acquisition_cost_cents=5000)
        # required_until reached (min 0 days) but only ONE PASS check (< 2)
        get_success_data(api.add_health_check(qr["id"], {"result": "PASS"}, headers=_VET))
        resp = api.clear_quarantine(qr["id"], headers=_VET)
        validate_error(resp, ApiErrorId.ERR_QUARANTINE_NOT_COMPLETE.value)

    def test_start_quarantine_twice_returns_invalid_state(self, api):
        """PRD §3.2: "A `VetTech` starts quarantine on an animal that is in `INTAKE`, which creates a **quarantine record** and moves the animal from `INTAKE` to `QUARANTINE`."

        Design: Corner/state_machines/start_quarantine_twice_returns_invalid_state
        """
        species = create_species(api, min_quarantine_days=3, warranty_days=30)
        animal, qr = start_quarantine_animal(api, species["id"],
                                             list_price_cents=12000, acquisition_cost_cents=3000)
        resp = api.start_quarantine(animal["id"], headers=_VET)  # already QUARANTINE
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
