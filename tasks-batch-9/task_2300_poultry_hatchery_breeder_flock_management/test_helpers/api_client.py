"""One method per endpoint of the Poultry Hatchery & Breeder Flock API.

All resources are mounted at the root path; there is no additional API prefix
(PRD 2). Every method returns the raw ``requests.Response`` so that tests can
assert on status codes as well as bodies.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the hatchery API."""

    # ------------------------------------------------------------------
    # Logical clock (PRD 2.4) — reachable without authentication
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Flock programmes (PRD 3.1)
    # ------------------------------------------------------------------

    def create_flock_program(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", "/flock-programs", payload, headers)

    def get_flock_program(self, program_id: str, headers) -> requests.Response:
        return self._request("GET", f"/flock-programs/{program_id}", None, headers)

    def retire_flock_program(self, program_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/flock-programs/{program_id}/retire", {}, headers
        )

    # ------------------------------------------------------------------
    # Incubation profiles (PRD 3.1)
    # ------------------------------------------------------------------

    def create_incubation_profile(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", "/incubation-profiles", payload, headers)

    def get_incubation_profile(self, profile_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/incubation-profiles/{profile_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Incubation units (PRD 3.1)
    # ------------------------------------------------------------------

    def create_incubation_unit(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", "/incubation-units", payload, headers)

    def get_incubation_unit(self, unit_id: str, headers) -> requests.Response:
        return self._request("GET", f"/incubation-units/{unit_id}", None, headers)

    def sanitize_incubation_unit(self, unit_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/incubation-units/{unit_id}/sanitize", {}, headers
        )

    # ------------------------------------------------------------------
    # Breeder flocks (PRD 3.2)
    # ------------------------------------------------------------------

    def create_breeder_flock(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", "/breeder-flocks", payload, headers)

    def get_breeder_flock(self, flock_id: str, headers) -> requests.Response:
        return self._request("GET", f"/breeder-flocks/{flock_id}", None, headers)

    def list_breeder_flocks(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/breeder-flocks", None, headers, params)

    def start_lay(self, flock_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/breeder-flocks/{flock_id}/start-lay", {}, headers
        )

    def deplete_flock(self, flock_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/breeder-flocks/{flock_id}/deplete", {}, headers
        )

    def release_egg_hold(self, flock_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/breeder-flocks/{flock_id}/release-hold", {}, headers
        )

    def recompute_forecast(self, flock_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/breeder-flocks/{flock_id}/recompute-forecast", {}, headers
        )

    # ------------------------------------------------------------------
    # Egg lots (PRD 3.4)
    # ------------------------------------------------------------------

    def create_egg_lot(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", "/egg-lots", payload, headers)

    def get_egg_lot(self, lot_id: str, headers) -> requests.Response:
        return self._request("GET", f"/egg-lots/{lot_id}", None, headers)

    def list_egg_lots(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/egg-lots", None, headers, params)

    def grade_egg_lot(self, lot_id: str, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"/egg-lots/{lot_id}/grade", payload, headers)

    def store_egg_lot(self, lot_id: str, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"/egg-lots/{lot_id}/store", payload, headers)

    def sanitation_hold_egg_lot(self, lot_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/egg-lots/{lot_id}/sanitation-hold", {}, headers
        )

    def sanitation_release_egg_lot(self, lot_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/egg-lots/{lot_id}/sanitation-release", {}, headers
        )

    def condemn_egg_lot(self, lot_id: str, reason: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/egg-lots/{lot_id}/condemn", {"reason": reason}, headers
        )

    def list_egg_lot_draws(
        self, lot_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/egg-lots/{lot_id}/setter-load-items", None, headers, params
        )

    # ------------------------------------------------------------------
    # Setter loads (PRD 3.5)
    # ------------------------------------------------------------------

    def create_setter_load(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", "/setter-loads", payload, headers)

    def get_setter_load(self, load_id: str, headers) -> requests.Response:
        return self._request("GET", f"/setter-loads/{load_id}", None, headers)

    def list_setter_loads(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/setter-loads", None, headers, params)

    def draw_eggs(self, load_id: str, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"/setter-loads/{load_id}/items", payload, headers)

    def list_setter_load_items(
        self, load_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/setter-loads/{load_id}/items", None, headers, params
        )

    def start_setter_load(self, load_id: str, headers) -> requests.Response:
        return self._request("POST", f"/setter-loads/{load_id}/start", {}, headers)

    def add_environment_reading(
        self, load_id: str, payload: Any, headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/setter-loads/{load_id}/environment-readings", payload, headers
        )

    def list_environment_readings(
        self, load_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/setter-loads/{load_id}/environment-readings", None, headers, params
        )

    def candle_setter_load(
        self, load_id: str, fertile_count: int, headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/setter-loads/{load_id}/candle",
            {"fertile_count": fertile_count},
            headers,
        )

    def abort_setter_load(
        self, load_id: str, reason: str, headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/setter-loads/{load_id}/abort", {"reason": reason}, headers
        )

    def transfer_setter_load(
        self, load_id: str, hatcher_unit_id: str, headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/setter-loads/{load_id}/transfer",
            {"hatcher_unit_id": hatcher_unit_id},
            headers,
        )

    # ------------------------------------------------------------------
    # Hatcher loads (PRD 3.6)
    # ------------------------------------------------------------------

    def get_hatcher_load(self, load_id: str, headers) -> requests.Response:
        return self._request("GET", f"/hatcher-loads/{load_id}", None, headers)

    def list_hatcher_loads(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/hatcher-loads", None, headers, params)

    def pull_chicks(
        self, load_id: str, hatched_count: int, headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/hatcher-loads/{load_id}/pull",
            {"hatched_count": hatched_count},
            headers,
        )

    # ------------------------------------------------------------------
    # Chick batches (PRD 3.7, 3.8)
    # ------------------------------------------------------------------

    def get_chick_batch(self, batch_id: str, headers) -> requests.Response:
        return self._request("GET", f"/chick-batches/{batch_id}", None, headers)

    def list_chick_batches(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/chick-batches", None, headers, params)

    def sex_chick_batch(self, batch_id: str, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"/chick-batches/{batch_id}/sex", payload, headers)

    def vaccinate_chick_batch(
        self, batch_id: str, vaccine_code: str, headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/chick-batches/{batch_id}/vaccinate",
            {"vaccine_code": vaccine_code},
            headers,
        )

    def box_chick_batch(self, batch_id: str, headers) -> requests.Response:
        return self._request("POST", f"/chick-batches/{batch_id}/box", {}, headers)

    def allocate_chicks(
        self, batch_id: str, expected_chick_batch_version: int, headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/chick-batches/{batch_id}/allocations",
            {"expected_chick_batch_version": expected_chick_batch_version},
            headers,
        )

    # ------------------------------------------------------------------
    # Grower farms (PRD 3.3)
    # ------------------------------------------------------------------

    def create_grower_farm(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", "/grower-farms", payload, headers)

    def get_grower_farm(self, farm_id: str, headers) -> requests.Response:
        return self._request("GET", f"/grower-farms/{farm_id}", None, headers)

    def clear_grower_farm(self, farm_id: str, headers) -> requests.Response:
        return self._request("POST", f"/grower-farms/{farm_id}/clear", {}, headers)

    # ------------------------------------------------------------------
    # Placement orders (PRD 3.8)
    # ------------------------------------------------------------------

    def create_placement_order(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", "/placement-orders", payload, headers)

    def get_placement_order(self, order_id: str, headers) -> requests.Response:
        return self._request("GET", f"/placement-orders/{order_id}", None, headers)

    def list_placement_orders(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/placement-orders", None, headers, params)

    def confirm_placement_order(self, order_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/placement-orders/{order_id}/confirm", {}, headers
        )

    # ------------------------------------------------------------------
    # Delivery assignments (PRD 3.9)
    # ------------------------------------------------------------------

    def get_delivery_assignment(self, assignment_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/delivery-assignments/{assignment_id}", None, headers
        )

    def list_delivery_assignments(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/delivery-assignments", None, headers, params)

    def deliver_assignment(self, assignment_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/delivery-assignments/{assignment_id}/deliver", {}, headers
        )

    def reverse_assignment(
        self, assignment_id: str, reason: str, headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/delivery-assignments/{assignment_id}/reverse",
            {"reason": reason},
            headers,
        )

    # ------------------------------------------------------------------
    # Laboratory tests (PRD 3.3)
    # ------------------------------------------------------------------

    def create_lab_test(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", "/lab-tests", payload, headers)

    def get_lab_test(self, test_id: str, headers) -> requests.Response:
        return self._request("GET", f"/lab-tests/{test_id}", None, headers)

    def list_lab_tests(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/lab-tests", None, headers, params)

    def release_lab_test(self, test_id: str, result: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/lab-tests/{test_id}/release", {"result": result}, headers
        )

    # ------------------------------------------------------------------
    # Corrective actions (PRD 3.9)
    # ------------------------------------------------------------------

    def get_corrective_action(self, action_id: str, headers) -> requests.Response:
        return self._request("GET", f"/corrective-actions/{action_id}", None, headers)

    def list_corrective_actions(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/corrective-actions", None, headers, params)

    def acknowledge_corrective_action(
        self, action_id: str, headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-actions/{action_id}/acknowledge", {}, headers
        )

    def implement_corrective_action(
        self, action_id: str, note: str, headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/corrective-actions/{action_id}/implement",
            {"note": note},
            headers,
        )

    def verify_corrective_action(
        self, action_id: str, outcome: str, headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/corrective-actions/{action_id}/verify",
            {"outcome": outcome},
            headers,
        )

    # ------------------------------------------------------------------
    # Generic escape hatches (used by the not-found and RBAC sweeps)
    # ------------------------------------------------------------------

    def get_path(
        self, path: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", path, None, headers, params)

    def post_path(self, path: str, payload: Any, headers) -> requests.Response:
        return self._request("POST", path, payload, headers)
