"""Typed client covering every endpoint in PRD section 4.

One method per endpoint row. Every method takes an explicit ``headers``
argument because PRD 2.1 makes both X-User-ID and X-User-Role mandatory on
every request, and returns the raw response so that tests can assert on status
codes and error envelopes as well as on success payloads.
"""

from prd_bench_local_runner.testing.client import GenericApiClient


def _clean(params):
    """Drop unset filters so an omitted filter is genuinely absent."""
    if not params:
        return None
    out = {k: v for k, v in params.items() if v is not None}
    return out or None


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_current_utc(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------- standing plant config
    def create_spent_fuel_pool(self, payload, headers=None):
        return self._request("POST", "/spent-fuel-pools", payload, headers)

    def get_spent_fuel_pool(self, pool_id, headers=None):
        return self._request("GET", "/spent-fuel-pools/{}".format(pool_id), None, headers)

    def create_rad_area(self, payload, headers=None):
        return self._request("POST", "/rad-areas", payload, headers)

    def get_rad_area(self, rad_area_id, headers=None):
        return self._request("GET", "/rad-areas/{}".format(rad_area_id), None, headers)

    def create_safety_function(self, payload, headers=None):
        return self._request("POST", "/safety-functions", payload, headers)

    def get_safety_function(self, safety_function_id, headers=None):
        return self._request(
            "GET", "/safety-functions/{}".format(safety_function_id), None, headers
        )

    # -------------------------------------------------------------- outages
    def create_outage(self, payload, headers=None):
        return self._request("POST", "/outages", payload, headers)

    def get_outage(self, outage_id, headers=None):
        return self._request("GET", "/outages/{}".format(outage_id), None, headers)

    def lock_scope(self, outage_id, headers=None):
        return self._request("POST", "/outages/{}/lock-scope".format(outage_id), {}, headers)

    def commence_execution(self, outage_id, headers=None):
        return self._request(
            "POST", "/outages/{}/commence-execution".format(outage_id), {}, headers
        )

    def authorize_startup(self, outage_id, headers=None):
        return self._request(
            "POST", "/outages/{}/authorize-startup".format(outage_id), {}, headers
        )

    def post_outage_review(self, outage_id, payload, headers=None):
        return self._request(
            "POST", "/outages/{}/post-outage-review".format(outage_id), payload, headers
        )

    # ---------------------------------------------------------- work orders
    def create_work_order(self, outage_id, payload, headers=None):
        return self._request(
            "POST", "/outages/{}/work-orders".format(outage_id), payload, headers
        )

    def get_work_order(self, work_order_id, headers=None):
        return self._request("GET", "/work-orders/{}".format(work_order_id), None, headers)

    def list_work_orders(
        self,
        headers=None,
        outage_id=None,
        safety_function_id=None,
        status=None,
        priority=None,
        origin=None,
        limit=None,
        offset=None,
    ):
        params = _clean(
            {
                "outage_id": outage_id,
                "safety_function_id": safety_function_id,
                "status": status,
                "priority": priority,
                "origin": origin,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/work-orders", None, headers, params)

    def plan_work_order(self, work_order_id, headers=None):
        return self._request(
            "POST", "/work-orders/{}/plan".format(work_order_id), {}, headers
        )

    def approve_work_order_scope(self, work_order_id, headers=None):
        return self._request(
            "POST", "/work-orders/{}/approve-scope".format(work_order_id), {}, headers
        )

    def return_work_order_to_planning(self, work_order_id, return_reason, headers=None):
        return self._request(
            "POST",
            "/work-orders/{}/return-to-planning".format(work_order_id),
            {"return_reason": return_reason},
            headers,
        )

    def defer_work_order(self, work_order_id, deferral_reason, headers=None):
        return self._request(
            "POST",
            "/work-orders/{}/defer".format(work_order_id),
            {"deferral_reason": deferral_reason},
            headers,
        )

    # --------------------------------------------------- schedule activities
    def create_schedule_activity(self, outage_id, payload, headers=None):
        return self._request(
            "POST", "/outages/{}/schedule-activities".format(outage_id), payload, headers
        )

    def get_schedule_activity(self, activity_id, headers=None):
        return self._request(
            "GET", "/schedule-activities/{}".format(activity_id), None, headers
        )

    def list_schedule_activities(
        self,
        headers=None,
        outage_id=None,
        work_order_id=None,
        predecessor_activity_id=None,
        oos_safety_function_id=None,
        execution_status=None,
        constraint_status=None,
        limit=None,
        offset=None,
    ):
        params = _clean(
            {
                "outage_id": outage_id,
                "work_order_id": work_order_id,
                "predecessor_activity_id": predecessor_activity_id,
                "oos_safety_function_id": oos_safety_function_id,
                "execution_status": execution_status,
                "constraint_status": constraint_status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/schedule-activities", None, headers, params)

    def set_activity_predecessor(self, activity_id, predecessor_activity_id, headers=None):
        return self._request(
            "POST",
            "/schedule-activities/{}/set-predecessor".format(activity_id),
            {"predecessor_activity_id": predecessor_activity_id},
            headers,
        )

    def start_activity(self, activity_id, headers=None):
        return self._request(
            "POST", "/schedule-activities/{}/start".format(activity_id), {}, headers
        )

    def complete_activity(self, activity_id, headers=None):
        return self._request(
            "POST", "/schedule-activities/{}/complete".format(activity_id), {}, headers
        )

    # ---------------------------------------------------- core load patterns
    def create_core_load_pattern(self, outage_id, payload, headers=None):
        return self._request(
            "POST", "/outages/{}/core-load-patterns".format(outage_id), payload, headers
        )

    def get_core_load_pattern(self, pattern_id, headers=None):
        return self._request(
            "GET", "/core-load-patterns/{}".format(pattern_id), None, headers
        )

    def list_core_load_patterns(
        self, outage_id, headers=None, status=None, limit=None, offset=None
    ):
        params = _clean({"status": status, "limit": limit, "offset": offset})
        return self._request(
            "GET", "/outages/{}/core-load-patterns".format(outage_id), None, headers, params
        )

    def approve_core_load_pattern(self, pattern_id, headers=None):
        return self._request(
            "POST", "/core-load-patterns/{}/approve".format(pattern_id), {}, headers
        )

    # ------------------------------------------------- pool cell reservations
    def create_pool_cell_reservation(self, payload, headers=None):
        return self._request("POST", "/pool-cell-reservations", payload, headers)

    def get_pool_cell_reservation(self, reservation_id, headers=None):
        return self._request(
            "GET", "/pool-cell-reservations/{}".format(reservation_id), None, headers
        )

    def list_pool_cell_reservations(
        self,
        headers=None,
        outage_id=None,
        spent_fuel_pool_id=None,
        purpose=None,
        status=None,
        limit=None,
        offset=None,
    ):
        params = _clean(
            {
                "outage_id": outage_id,
                "spent_fuel_pool_id": spent_fuel_pool_id,
                "purpose": purpose,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/pool-cell-reservations", None, headers, params)

    def consume_pool_cell_reservation(self, reservation_id, headers=None):
        return self._request(
            "POST", "/pool-cell-reservations/{}/consume".format(reservation_id), {}, headers
        )

    def release_pool_cell_reservation(self, reservation_id, release_reason, headers=None):
        return self._request(
            "POST",
            "/pool-cell-reservations/{}/release".format(reservation_id),
            {"release_reason": release_reason},
            headers,
        )

    # ------------------------------------------------- supplemental workforce
    def create_supplemental_worker(self, outage_id, payload, headers=None):
        return self._request(
            "POST", "/outages/{}/supplemental-workers".format(outage_id), payload, headers
        )

    def get_supplemental_worker(self, worker_id, headers=None):
        return self._request(
            "GET", "/supplemental-workers/{}".format(worker_id), None, headers
        )

    def list_supplemental_workers(
        self, outage_id, headers=None, status=None, craft=None, limit=None, offset=None
    ):
        params = _clean(
            {"status": status, "craft": craft, "limit": limit, "offset": offset}
        )
        return self._request(
            "GET",
            "/outages/{}/supplemental-workers".format(outage_id),
            None,
            headers,
            params,
        )

    def record_background_result(self, worker_id, outcome, headers=None):
        return self._request(
            "POST",
            "/supplemental-workers/{}/background-result".format(worker_id),
            {"outcome": outcome},
            headers,
        )

    def record_training_completion(self, worker_id, modules_completed, headers=None):
        return self._request(
            "POST",
            "/supplemental-workers/{}/training-completion".format(worker_id),
            {"modules_completed": modules_completed},
            headers,
        )

    def badge_worker(self, worker_id, badge_number, headers=None):
        return self._request(
            "POST",
            "/supplemental-workers/{}/badge".format(worker_id),
            {"badge_number": badge_number},
            headers,
        )

    # ------------------------------------------ radiological work permits
    def draft_rwp(self, work_order_id, payload, headers=None):
        return self._request(
            "POST", "/work-orders/{}/rwps".format(work_order_id), payload, headers
        )

    def get_rwp(self, rwp_id, headers=None):
        return self._request("GET", "/rwps/{}".format(rwp_id), None, headers)

    def list_rwps(
        self,
        headers=None,
        outage_id=None,
        work_order_id=None,
        rad_area_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        params = _clean(
            {
                "outage_id": outage_id,
                "work_order_id": work_order_id,
                "rad_area_id": rad_area_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", "/rwps", None, headers, params)

    def approve_rwp(self, rwp_id, headers=None, alara_review_reference=None):
        payload = {}
        if alara_review_reference is not None:
            payload["alara_review_reference"] = alara_review_reference
        return self._request("POST", "/rwps/{}/approve".format(rwp_id), payload, headers)

    def close_rwp(self, rwp_id, actual_dose_mrem, headers=None):
        return self._request(
            "POST",
            "/rwps/{}/close".format(rwp_id),
            {"actual_dose_mrem": actual_dose_mrem},
            headers,
        )

    def void_rwp(self, rwp_id, void_reason, headers=None):
        return self._request(
            "POST", "/rwps/{}/void".format(rwp_id), {"void_reason": void_reason}, headers
        )

    def list_dose_transactions(
        self, rwp_id, headers=None, direction=None, limit=None, offset=None
    ):
        params = _clean({"direction": direction, "limit": limit, "offset": offset})
        return self._request(
            "GET", "/rwps/{}/dose-transactions".format(rwp_id), None, headers, params
        )

    # ------------------------------------------------------- emergent work
    def create_emergent_item(self, work_order_id, payload, headers=None):
        return self._request(
            "POST", "/work-orders/{}/emergent-items".format(work_order_id), payload, headers
        )

    def get_emergent_item(self, item_id, headers=None):
        return self._request("GET", "/emergent-items/{}".format(item_id), None, headers)

    def list_emergent_items(
        self, work_order_id, headers=None, status=None, limit=None, offset=None
    ):
        params = _clean({"status": status, "limit": limit, "offset": offset})
        return self._request(
            "GET",
            "/work-orders/{}/emergent-items".format(work_order_id),
            None,
            headers,
            params,
        )

    def dispose_emergent_item(self, item_id, disposition, headers=None, disposition_note=None):
        payload = {"disposition": disposition}
        if disposition_note is not None:
            payload["disposition_note"] = disposition_note
        return self._request(
            "POST", "/emergent-items/{}/dispose".format(item_id), payload, headers
        )

    # ------------------------------------------------------ startup testing
    def create_startup_test(self, outage_id, payload, headers=None):
        return self._request(
            "POST", "/outages/{}/startup-tests".format(outage_id), payload, headers
        )

    def get_startup_test(self, test_id, headers=None):
        return self._request("GET", "/startup-tests/{}".format(test_id), None, headers)

    def list_startup_tests(
        self, outage_id, headers=None, status=None, limit=None, offset=None
    ):
        params = _clean({"status": status, "limit": limit, "offset": offset})
        return self._request(
            "GET", "/outages/{}/startup-tests".format(outage_id), None, headers, params
        )

    def satisfy_startup_test(
        self, test_id, measured_reactivity_pcm, headers=None, nrc_release_reference=None
    ):
        payload = {"measured_reactivity_pcm": measured_reactivity_pcm}
        if nrc_release_reference is not None:
            payload["nrc_release_reference"] = nrc_release_reference
        return self._request(
            "POST", "/startup-tests/{}/satisfy".format(test_id), payload, headers
        )

    # ----------------------------------------------------------- raw escape
    def raw(self, method, path, payload=None, headers=None, params=None):
        """Escape hatch for shape tests that must send a payload the typed
        methods above deliberately do not model."""
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
