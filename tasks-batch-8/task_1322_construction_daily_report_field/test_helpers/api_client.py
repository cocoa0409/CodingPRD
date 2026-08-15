"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The per-test-server isolation kills and respawns the server before
        # every test. A pooled keep-alive connection can then be reused against
        # a dead socket and surface as a rare ConnectionResetError.
        # Connection: close forces a fresh TCP connection per request.
        self.session.headers["Connection"] = "close"

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def activate_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/activate", headers=headers)

    def suspend_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/suspend", headers=headers)

    def resume_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/resume", headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close", headers=headers)

    def get_progress_summary(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}/progress-summary", headers=headers)

    # --- WorkArea ---
    def create_work_area(self, payload, headers):
        return self._request("POST", "/work-areas", payload, headers)

    def get_work_area(self, work_area_id, headers):
        return self._request("GET", f"/work-areas/{work_area_id}", headers=headers)

    def list_work_areas(self, headers, params=None):
        return self._request("GET", "/work-areas", headers=headers, params=params)

    def close_work_area(self, work_area_id, headers):
        return self._request("POST", f"/work-areas/{work_area_id}/close", headers=headers)

    def reopen_work_area(self, work_area_id, headers):
        return self._request("POST", f"/work-areas/{work_area_id}/reopen", headers=headers)

    # --- DeliveryZone ---
    def create_delivery_zone(self, payload, headers):
        return self._request("POST", "/delivery-zones", payload, headers)

    def get_delivery_zone(self, zone_id, headers):
        return self._request("GET", f"/delivery-zones/{zone_id}", headers=headers)

    def list_delivery_zones(self, headers, params=None):
        return self._request("GET", "/delivery-zones", headers=headers, params=params)

    def close_delivery_zone(self, zone_id, headers):
        return self._request("POST", f"/delivery-zones/{zone_id}/close", headers=headers)

    def reopen_delivery_zone(self, zone_id, headers):
        return self._request("POST", f"/delivery-zones/{zone_id}/reopen", headers=headers)

    # --- WorkItem ---
    def create_work_item(self, payload, headers):
        return self._request("POST", "/work-items", payload, headers)

    def get_work_item(self, work_item_id, headers):
        return self._request("GET", f"/work-items/{work_item_id}", headers=headers)

    def list_work_items(self, headers, params=None):
        return self._request("GET", "/work-items", headers=headers, params=params)

    # --- DailyReport ---
    def create_daily_report(self, payload, headers):
        return self._request("POST", "/daily-reports", payload, headers)

    def get_daily_report(self, report_id, headers):
        return self._request("GET", f"/daily-reports/{report_id}", headers=headers)

    def list_daily_reports(self, headers, params=None):
        return self._request("GET", "/daily-reports", headers=headers, params=params)

    def update_daily_report(self, report_id, payload, headers):
        return self._request("PUT", f"/daily-reports/{report_id}", payload, headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/daily-reports/{report_id}/submit", headers=headers)

    def start_review_report(self, report_id, headers):
        return self._request("POST", f"/daily-reports/{report_id}/start-review", headers=headers)

    def approve_report(self, report_id, headers):
        return self._request("POST", f"/daily-reports/{report_id}/approve", headers=headers)

    def request_revision_report(self, report_id, payload, headers):
        return self._request("POST", f"/daily-reports/{report_id}/request-revision",
                             payload, headers)

    def return_to_draft_report(self, report_id, headers):
        return self._request("POST", f"/daily-reports/{report_id}/return-to-draft",
                             headers=headers)

    def recall_report(self, report_id, headers):
        return self._request("POST", f"/daily-reports/{report_id}/recall", headers=headers)

    def reopen_report(self, report_id, payload, headers):
        return self._request("POST", f"/daily-reports/{report_id}/reopen", payload, headers)

    def lock_report(self, report_id, headers):
        return self._request("POST", f"/daily-reports/{report_id}/lock", headers=headers)

    # --- CrewEntry ---
    def create_crew_entry(self, payload, headers):
        return self._request("POST", "/crew-entries", payload, headers)

    def get_crew_entry(self, entry_id, headers):
        return self._request("GET", f"/crew-entries/{entry_id}", headers=headers)

    def list_crew_entries(self, headers, params=None):
        return self._request("GET", "/crew-entries", headers=headers, params=params)

    def void_crew_entry(self, entry_id, headers):
        return self._request("POST", f"/crew-entries/{entry_id}/void", headers=headers)

    # --- EquipmentEntry ---
    def create_equipment_entry(self, payload, headers):
        return self._request("POST", "/equipment-entries", payload, headers)

    def get_equipment_entry(self, entry_id, headers):
        return self._request("GET", f"/equipment-entries/{entry_id}", headers=headers)

    def list_equipment_entries(self, headers, params=None):
        return self._request("GET", "/equipment-entries", headers=headers, params=params)

    def void_equipment_entry(self, entry_id, headers):
        return self._request("POST", f"/equipment-entries/{entry_id}/void", headers=headers)

    # --- WeatherObservation ---
    def create_weather_observation(self, payload, headers):
        return self._request("POST", "/weather-observations", payload, headers)

    def get_weather_observation(self, observation_id, headers):
        return self._request("GET", f"/weather-observations/{observation_id}", headers=headers)

    def list_weather_observations(self, headers, params=None):
        return self._request("GET", "/weather-observations", headers=headers, params=params)

    # --- DelayEvent ---
    def create_delay_event(self, payload, headers):
        return self._request("POST", "/delay-events", payload, headers)

    def get_delay_event(self, event_id, headers):
        return self._request("GET", f"/delay-events/{event_id}", headers=headers)

    def list_delay_events(self, headers, params=None):
        return self._request("GET", "/delay-events", headers=headers, params=params)

    def classify_delay_event(self, event_id, payload, headers):
        return self._request("POST", f"/delay-events/{event_id}/classify", payload, headers)

    def dispute_delay_event(self, event_id, payload, headers):
        return self._request("POST", f"/delay-events/{event_id}/dispute", payload, headers)

    def finalize_delay_event(self, event_id, headers):
        return self._request("POST", f"/delay-events/{event_id}/finalize", headers=headers)

    # --- SafetyObservation ---
    def create_safety_observation(self, payload, headers):
        return self._request("POST", "/safety-observations", payload, headers)

    def get_safety_observation(self, observation_id, headers):
        return self._request("GET", f"/safety-observations/{observation_id}", headers=headers)

    def list_safety_observations(self, headers, params=None):
        return self._request("GET", "/safety-observations", headers=headers, params=params)

    def mitigate_observation(self, observation_id, headers):
        return self._request("POST", f"/safety-observations/{observation_id}/mitigate",
                             headers=headers)

    def verify_close_observation(self, observation_id, headers):
        return self._request("POST", f"/safety-observations/{observation_id}/verify-close",
                             headers=headers)

    def reopen_observation(self, observation_id, headers):
        return self._request("POST", f"/safety-observations/{observation_id}/reopen",
                             headers=headers)

    def escalate_observation(self, observation_id, headers):
        return self._request("POST", f"/safety-observations/{observation_id}/escalate",
                             headers=headers)

    # --- Incident ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def begin_investigation(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/begin-investigation",
                             headers=headers)

    def notify_osha(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/notify-osha", headers=headers)

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/close", payload, headers)

    # --- MediaAttachment ---
    def create_media_attachment(self, payload, headers):
        return self._request("POST", "/media-attachments", payload, headers)

    def get_media_attachment(self, media_id, headers):
        return self._request("GET", f"/media-attachments/{media_id}", headers=headers)

    def list_media_attachments(self, headers, params=None):
        return self._request("GET", "/media-attachments", headers=headers, params=params)

    def purge_media_attachment(self, media_id, headers):
        return self._request("POST", f"/media-attachments/{media_id}/purge", headers=headers)

    # --- MaterialDelivery ---
    def create_delivery(self, payload, headers):
        return self._request("POST", "/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def inspect_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/inspect", payload, headers)

    def resolve_recount(self, delivery_id, payload, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/resolve-recount",
                             payload, headers)

    # --- QuantityEntry ---
    def create_quantity_entry(self, payload, headers):
        return self._request("POST", "/quantity-entries", payload, headers)

    def get_quantity_entry(self, entry_id, headers):
        return self._request("GET", f"/quantity-entries/{entry_id}", headers=headers)

    def list_quantity_entries(self, headers, params=None):
        return self._request("GET", "/quantity-entries", headers=headers, params=params)

    def void_quantity_entry(self, entry_id, headers):
        return self._request("POST", f"/quantity-entries/{entry_id}/void", headers=headers)

    # --- TmTicket ---
    def create_tm_ticket(self, payload, headers):
        return self._request("POST", "/tm-tickets", payload, headers)

    def get_tm_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tm-tickets/{ticket_id}", headers=headers)

    def list_tm_tickets(self, headers, params=None):
        return self._request("GET", "/tm-tickets", headers=headers, params=params)

    def update_tm_ticket(self, ticket_id, payload, headers):
        return self._request("PUT", f"/tm-tickets/{ticket_id}", payload, headers)

    def submit_ticket_for_signature(self, ticket_id, headers):
        return self._request("POST", f"/tm-tickets/{ticket_id}/submit-for-signature",
                             headers=headers)

    def sign_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tm-tickets/{ticket_id}/sign", payload, headers)

    def approve_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tm-tickets/{ticket_id}/approve", headers=headers)

    def reject_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/tm-tickets/{ticket_id}/reject", payload, headers)

    def revise_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tm-tickets/{ticket_id}/revise", headers=headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tm-tickets/{ticket_id}/void", headers=headers)

    # --- DistributionRecord ---
    def create_distribution_record(self, payload, headers):
        return self._request("POST", "/distribution-records", payload, headers)

    def get_distribution_record(self, record_id, headers):
        return self._request("GET", f"/distribution-records/{record_id}", headers=headers)

    def list_distribution_records(self, headers, params=None):
        return self._request("GET", "/distribution-records", headers=headers, params=params)

    def send_distribution_record(self, record_id, headers):
        return self._request("POST", f"/distribution-records/{record_id}/send", headers=headers)

    def acknowledge_distribution_record(self, record_id, headers):
        return self._request("POST", f"/distribution-records/{record_id}/acknowledge",
                             headers=headers)

    def delete_distribution_record(self, record_id, headers):
        return self._request("DELETE", f"/distribution-records/{record_id}", headers=headers)


api_client = ApiClient()
