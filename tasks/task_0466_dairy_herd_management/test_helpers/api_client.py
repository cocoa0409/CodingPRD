"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/herds/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Herd ---
    def create_herd(self, payload, headers):
        return self._request("POST", "/herds", payload, headers)

    def list_herds(self, headers, params=None):
        return self._request("GET", "/herds", headers=headers, params=params)

    def get_herd(self, herd_id, headers):
        return self._request("GET", f"/herds/{herd_id}", headers=headers)

    # --- Parlor ---
    def create_parlor(self, payload, headers):
        return self._request("POST", "/herds/parlors", payload, headers)

    def list_parlors(self, headers, params=None):
        return self._request("GET", "/herds/parlors", headers=headers, params=params)

    def get_parlor(self, parlor_id, headers):
        return self._request("GET", f"/herds/parlors/{parlor_id}", headers=headers)

    # --- Ration ---
    def create_ration(self, payload, headers):
        return self._request("POST", "/herds/rations", payload, headers)

    def list_rations(self, headers, params=None):
        return self._request("GET", "/herds/rations", headers=headers, params=params)

    def get_ration(self, ration_id, headers):
        return self._request("GET", f"/herds/rations/{ration_id}", headers=headers)

    # --- CoopPriceSheet ---
    def create_price_sheet(self, payload, headers):
        return self._request("POST", "/herds/coop-price-sheets", payload, headers)

    def list_price_sheets(self, headers, params=None):
        return self._request("GET", "/herds/coop-price-sheets", headers=headers, params=params)

    def get_price_sheet(self, price_sheet_id, headers):
        return self._request("GET", f"/herds/coop-price-sheets/{price_sheet_id}", headers=headers)

    # --- Animal ---
    def create_animal(self, payload, headers):
        return self._request("POST", "/herds/animals", payload, headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/herds/animals", headers=headers, params=params)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/herds/animals/{animal_id}", headers=headers)

    def dry_off_animal(self, animal_id, headers):
        return self._request("POST", f"/herds/animals/{animal_id}/dry-off", {}, headers)

    def get_iofc(self, animal_id, headers, params=None):
        return self._request(
            "GET", f"/herds/animals/{animal_id}/iofc", headers=headers, params=params,
        )

    # --- Lactation ---
    def list_lactations(self, headers, params=None):
        return self._request("GET", "/herds/lactations", headers=headers, params=params)

    def get_lactation(self, lactation_id, headers):
        return self._request("GET", f"/herds/lactations/{lactation_id}", headers=headers)

    # --- TestDayRecord ---
    def create_test_day_record(self, payload, headers):
        return self._request("POST", "/herds/test-day-records", payload, headers)

    def list_test_day_records(self, headers, params=None):
        return self._request("GET", "/herds/test-day-records", headers=headers, params=params)

    def get_test_day_record(self, record_id, headers):
        return self._request("GET", f"/herds/test-day-records/{record_id}", headers=headers)

    # --- MilkingShift ---
    def create_milking_shift(self, payload, headers):
        return self._request("POST", "/herds/milking-shifts", payload, headers)

    def list_milking_shifts(self, headers, params=None):
        return self._request("GET", "/herds/milking-shifts", headers=headers, params=params)

    def get_milking_shift(self, shift_id, headers):
        return self._request("GET", f"/herds/milking-shifts/{shift_id}", headers=headers)

    def void_milking_shift(self, shift_id, headers):
        return self._request("POST", f"/herds/milking-shifts/{shift_id}/void", {}, headers)

    # --- BreedingEvent ---
    def create_breeding_event(self, payload, headers):
        return self._request("POST", "/herds/breeding-events", payload, headers)

    def list_breeding_events(self, headers, params=None):
        return self._request("GET", "/herds/breeding-events", headers=headers, params=params)

    def get_breeding_event(self, breeding_id, headers):
        return self._request("GET", f"/herds/breeding-events/{breeding_id}", headers=headers)

    def confirm_breeding_event(self, breeding_id, headers):
        return self._request("POST", f"/herds/breeding-events/{breeding_id}/confirm", {}, headers)

    def mark_open_breeding_event(self, breeding_id, headers):
        return self._request("POST", f"/herds/breeding-events/{breeding_id}/mark-open", {}, headers)

    # --- CalvingEvent ---
    def create_calving_event(self, payload, headers):
        return self._request("POST", "/herds/calving-events", payload, headers)

    def list_calving_events(self, headers, params=None):
        return self._request("GET", "/herds/calving-events", headers=headers, params=params)

    def get_calving_event(self, calving_event_id, headers):
        return self._request("GET", f"/herds/calving-events/{calving_event_id}", headers=headers)

    # --- HealthTreatment ---
    def create_health_treatment(self, payload, headers):
        return self._request("POST", "/herds/health-treatments", payload, headers)

    def list_health_treatments(self, headers, params=None):
        return self._request("GET", "/herds/health-treatments", headers=headers, params=params)

    def get_health_treatment(self, treatment_id, headers):
        return self._request("GET", f"/herds/health-treatments/{treatment_id}", headers=headers)

    def clear_health_treatment(self, treatment_id, headers):
        return self._request("POST", f"/herds/health-treatments/{treatment_id}/clear", {}, headers)

    def void_health_treatment(self, treatment_id, headers):
        return self._request("POST", f"/herds/health-treatments/{treatment_id}/void", {}, headers)

    # --- MilkCheck ---
    def create_milk_check(self, payload, headers):
        return self._request("POST", "/herds/milk-checks", payload, headers)

    def list_milk_checks(self, headers, params=None):
        return self._request("GET", "/herds/milk-checks", headers=headers, params=params)

    def get_milk_check(self, milk_check_id, headers):
        return self._request("GET", f"/herds/milk-checks/{milk_check_id}", headers=headers)

    def finalize_milk_check(self, milk_check_id, expected_version, headers):
        return self._request(
            "POST", f"/herds/milk-checks/{milk_check_id}/finalize",
            {"expected_milk_check_version": expected_version}, headers,
        )

    def cancel_milk_check(self, milk_check_id, expected_version, headers):
        return self._request(
            "POST", f"/herds/milk-checks/{milk_check_id}/cancel",
            {"expected_milk_check_version": expected_version}, headers,
        )

    # --- CullDecision ---
    def create_cull_decision(self, payload, headers):
        return self._request("POST", "/herds/cull-decisions", payload, headers)

    def list_cull_decisions(self, headers, params=None):
        return self._request("GET", "/herds/cull-decisions", headers=headers, params=params)

    def get_cull_decision(self, cull_decision_id, headers):
        return self._request("GET", f"/herds/cull-decisions/{cull_decision_id}", headers=headers)


api_client = ApiClient()
