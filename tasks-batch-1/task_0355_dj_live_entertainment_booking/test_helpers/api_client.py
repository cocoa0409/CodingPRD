"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, now_utc, headers):
        return self._request("POST", "/_clock/set", {"now_utc": now_utc}, headers)

    # ---- TravelZone ----
    def create_travel_zone(self, payload, headers):
        return self._request("POST", "/travel-zones", payload, headers)

    def get_travel_zone(self, zone_id, headers):
        return self._request("GET", f"/travel-zones/{zone_id}", headers=headers)

    # ---- PackageOffering + EquipmentItem ----
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def retire_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/retire", {}, headers)

    def add_equipment(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/equipment", payload, headers)

    def list_equipment(self, package_id, headers, params=None):
        return self._request("GET", f"/packages/{package_id}/equipment", headers=headers, params=params)

    # ---- Performer ----
    def create_performer(self, payload, headers):
        return self._request("POST", "/performers", payload, headers)

    def get_performer(self, performer_id, headers):
        return self._request("GET", f"/performers/{performer_id}", headers=headers)

    def list_performers(self, headers, params=None):
        return self._request("GET", "/performers", headers=headers, params=params)

    def deactivate_performer(self, performer_id, headers):
        return self._request("POST", f"/performers/{performer_id}/deactivate", {}, headers)

    def create_blackout(self, performer_id, payload, headers):
        return self._request("POST", f"/performers/{performer_id}/blackouts", payload, headers)

    def list_blackouts(self, performer_id, headers, params=None):
        return self._request("GET", f"/performers/{performer_id}/blackouts", headers=headers, params=params)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # ---- Booking core ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def hold_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/hold", {}, headers)

    def issue_contract(self, booking_id, expected_booking_version, headers):
        return self._request(
            "POST",
            f"/bookings/{booking_id}/issue-contract",
            {"expected_booking_version": expected_booking_version},
            headers,
        )

    def request_revision(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/request-revision", {}, headers)

    def start_set(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/start-set", {}, headers)

    def complete_set(self, booking_id, actual_set_minutes, headers):
        return self._request(
            "POST",
            f"/bookings/{booking_id}/complete-set",
            {"actual_set_minutes": actual_set_minutes},
            headers,
        )

    def settle_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/settle", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def promote_backup(self, booking_id, backup_assignment_id, expected_booking_version, headers):
        return self._request(
            "POST",
            f"/bookings/{booking_id}/promote-backup",
            {
                "backup_assignment_id": backup_assignment_id,
                "expected_booking_version": expected_booking_version,
            },
            headers,
        )

    # ---- Contracts ----
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/contracts", headers=headers, params=params)

    def sign_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/sign", {}, headers)

    def decline_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/decline", {}, headers)

    # ---- Payments ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/payments", headers=headers, params=params)

    def capture_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/capture", {}, headers)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/void", {}, headers)

    # ---- Song requests / do-not-play ----
    def create_song_request(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/song-requests", payload, headers)

    def list_song_requests(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/song-requests", headers=headers, params=params)

    def get_song_request(self, song_request_id, headers):
        return self._request("GET", f"/song-requests/{song_request_id}", headers=headers)

    # ---- Backup assignments ----
    def create_backup_assignment(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/backup-assignments", payload, headers)

    def list_backup_assignments_for_booking(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/backup-assignments", headers=headers, params=params)

    def get_backup_assignment(self, backup_assignment_id, headers):
        return self._request("GET", f"/backup-assignments/{backup_assignment_id}", headers=headers)

    def accept_backup(self, backup_assignment_id, headers):
        return self._request("POST", f"/backup-assignments/{backup_assignment_id}/accept", {}, headers)

    def decline_backup(self, backup_assignment_id, headers):
        return self._request("POST", f"/backup-assignments/{backup_assignment_id}/decline", {}, headers)

    def list_backup_assignments(self, headers, params=None):
        return self._request("GET", "/backup-assignments", headers=headers, params=params)


api_client = ApiClient()
