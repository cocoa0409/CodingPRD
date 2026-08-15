"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical server clock (test-driving endpoint, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Terminals
    # ------------------------------------------------------------------
    def create_terminal(self, payload, headers):
        return self._request("POST", "/terminals", payload, headers)

    def get_terminal(self, tid, headers):
        return self._request("GET", f"/terminals/{tid}", headers=headers)

    def list_terminals(self, headers, params=None):
        return self._request("GET", "/terminals", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Chassis pools
    # ------------------------------------------------------------------
    def create_pool(self, tid, payload, headers):
        return self._request("POST", f"/terminals/{tid}/pools", payload, headers)

    def get_pool(self, tid, pid, headers):
        return self._request("GET", f"/terminals/{tid}/pools/{pid}", headers=headers)

    def list_pools(self, tid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/pools",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Chassis
    # ------------------------------------------------------------------
    def create_chassis(self, tid, pid, payload, headers):
        return self._request("POST", f"/terminals/{tid}/pools/{pid}/chassis",
                             payload, headers)

    def get_chassis(self, tid, pid, cid, headers):
        return self._request("GET", f"/terminals/{tid}/pools/{pid}/chassis/{cid}",
                             headers=headers)

    def list_chassis(self, tid, pid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/pools/{pid}/chassis",
                             headers=headers, params=params)

    def reserve_chassis(self, tid, pid, cid, payload, headers):
        return self._request(
            "POST", f"/terminals/{tid}/pools/{pid}/chassis/{cid}/reserve",
            payload, headers)

    def enter_maintenance(self, tid, pid, cid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/pools/{pid}/chassis/{cid}/enter_maintenance",
            {}, headers)

    def exit_maintenance(self, tid, pid, cid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/pools/{pid}/chassis/{cid}/exit_maintenance",
            {}, headers)

    def retire_chassis(self, tid, pid, cid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/pools/{pid}/chassis/{cid}/retire",
            {}, headers)

    # ------------------------------------------------------------------
    # Chassis memberships
    # ------------------------------------------------------------------
    def create_membership(self, tid, pid, payload, headers):
        return self._request("POST", f"/terminals/{tid}/pools/{pid}/memberships",
                             payload, headers)

    def get_membership(self, tid, pid, mid, headers):
        return self._request(
            "GET", f"/terminals/{tid}/pools/{pid}/memberships/{mid}", headers=headers)

    def list_memberships(self, tid, pid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/pools/{pid}/memberships",
                             headers=headers, params=params)

    def suspend_membership(self, tid, pid, mid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/pools/{pid}/memberships/{mid}/suspend",
            {}, headers)

    def reactivate_membership(self, tid, pid, mid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/pools/{pid}/memberships/{mid}/reactivate",
            {}, headers)

    def terminate_membership(self, tid, pid, mid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/pools/{pid}/memberships/{mid}/terminate",
            {}, headers)

    def load_flip_credit(self, tid, pid, mid, payload, headers):
        return self._request(
            "POST", f"/terminals/{tid}/pools/{pid}/memberships/{mid}/load_flip_credit",
            payload, headers)

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, cid, headers):
        return self._request("GET", f"/carriers/{cid}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Trains
    # ------------------------------------------------------------------
    def create_train(self, tid, payload, headers):
        return self._request("POST", f"/terminals/{tid}/trains", payload, headers)

    def get_train(self, tid, trid, headers):
        return self._request("GET", f"/terminals/{tid}/trains/{trid}", headers=headers)

    def list_trains(self, tid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/trains",
                             headers=headers, params=params)

    def mark_train_arrived(self, tid, trid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/trains/{trid}/mark_arrived", {}, headers)

    def begin_train_loading(self, tid, trid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/trains/{trid}/begin_loading", {}, headers)

    def mark_train_departed(self, tid, trid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/trains/{trid}/mark_departed", {}, headers)

    def cancel_train(self, tid, trid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/trains/{trid}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Yard slots
    # ------------------------------------------------------------------
    def create_slot(self, tid, payload, headers):
        return self._request("POST", f"/terminals/{tid}/slots", payload, headers)

    def get_slot(self, tid, sid, headers):
        return self._request("GET", f"/terminals/{tid}/slots/{sid}", headers=headers)

    def list_slots(self, tid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/slots",
                             headers=headers, params=params)

    def block_slot(self, tid, sid, headers):
        return self._request("POST", f"/terminals/{tid}/slots/{sid}/block",
                             {}, headers)

    def unblock_slot(self, tid, sid, headers):
        return self._request("POST", f"/terminals/{tid}/slots/{sid}/unblock",
                             {}, headers)

    def reserve_slot(self, tid, sid, headers):
        return self._request("POST", f"/terminals/{tid}/slots/{sid}/reserve",
                             {}, headers)

    def unreserve_slot(self, tid, sid, headers):
        return self._request("POST", f"/terminals/{tid}/slots/{sid}/unreserve",
                             {}, headers)

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------
    def create_container(self, tid, payload, headers):
        return self._request("POST", f"/terminals/{tid}/containers", payload, headers)

    def get_container(self, tid, cid, headers):
        return self._request("GET", f"/terminals/{tid}/containers/{cid}",
                             headers=headers)

    def list_containers(self, tid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/containers",
                             headers=headers, params=params)

    def ground_container(self, tid, cid, payload, headers):
        return self._request(
            "POST", f"/terminals/{tid}/containers/{cid}/ground", payload, headers)

    def void_container(self, tid, cid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/containers/{cid}/void", {}, headers)

    # ------------------------------------------------------------------
    # Gate appointments
    # ------------------------------------------------------------------
    def create_appointment(self, tid, payload, headers):
        return self._request("POST", f"/terminals/{tid}/appointments",
                             payload, headers)

    def get_appointment(self, tid, aid, headers):
        return self._request("GET", f"/terminals/{tid}/appointments/{aid}",
                             headers=headers)

    def list_appointments(self, tid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/appointments",
                             headers=headers, params=params)

    def check_in_appointment(self, tid, aid, payload, headers):
        return self._request(
            "POST", f"/terminals/{tid}/appointments/{aid}/check_in",
            payload, headers)

    def cancel_appointment(self, tid, aid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/appointments/{aid}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Gate transactions
    # ------------------------------------------------------------------
    def create_transaction(self, tid, payload, headers):
        return self._request("POST", f"/terminals/{tid}/transactions",
                             payload, headers)

    def get_transaction(self, tid, txid, headers):
        return self._request("GET", f"/terminals/{tid}/transactions/{txid}",
                             headers=headers)

    def list_transactions(self, tid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/transactions",
                             headers=headers, params=params)

    def complete_transaction(self, tid, txid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/transactions/{txid}/complete", {}, headers)

    def reject_transaction(self, tid, txid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/transactions/{txid}/reject", {}, headers)

    # ------------------------------------------------------------------
    # Damage inspections
    # ------------------------------------------------------------------
    def create_damage(self, tid, payload, headers):
        return self._request("POST", f"/terminals/{tid}/damage", payload, headers)

    def get_damage(self, tid, did, headers):
        return self._request("GET", f"/terminals/{tid}/damage/{did}", headers=headers)

    def list_damage(self, tid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/damage",
                             headers=headers, params=params)

    def schedule_damage_repair(self, tid, did, headers):
        return self._request(
            "POST", f"/terminals/{tid}/damage/{did}/schedule_repair", {}, headers)

    def mark_damage_repaired(self, tid, did, headers):
        return self._request(
            "POST", f"/terminals/{tid}/damage/{did}/mark_repaired", {}, headers)

    def waive_damage(self, tid, did, headers):
        return self._request(
            "POST", f"/terminals/{tid}/damage/{did}/waive", {}, headers)

    # ------------------------------------------------------------------
    # Billing ledger
    # ------------------------------------------------------------------
    def get_ledger_entry(self, tid, lid, headers):
        return self._request("GET", f"/terminals/{tid}/ledger/{lid}", headers=headers)

    def list_ledger_entries(self, tid, headers, params=None):
        return self._request("GET", f"/terminals/{tid}/ledger",
                             headers=headers, params=params)

    def apply_ledger_payment(self, tid, lid, payload, headers):
        return self._request(
            "POST", f"/terminals/{tid}/ledger/{lid}/apply", payload, headers)

    def waive_ledger_entry(self, tid, lid, headers):
        return self._request(
            "POST", f"/terminals/{tid}/ledger/{lid}/waive", {}, headers)

    # ------------------------------------------------------------------
    # Operations checkpoint
    # ------------------------------------------------------------------
    def run_ops(self, tid, headers):
        return self._request("POST", f"/terminals/{tid}/run_ops", {}, headers)

    # ------------------------------------------------------------------
    # Flat retrieval endpoints (PRD §2.6)
    # ------------------------------------------------------------------
    def get_pool_flat(self, pool_id, headers):
        return self._request("GET", f"/pools/{pool_id}", headers=headers)

    def list_pools_flat(self, headers, params=None):
        return self._request("GET", "/pools", headers=headers, params=params)

    def get_chassis_flat(self, chassis_id, headers):
        return self._request("GET", f"/chassis/{chassis_id}", headers=headers)

    def list_chassis_flat(self, headers, params=None):
        return self._request("GET", "/chassis", headers=headers, params=params)

    def get_membership_flat(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships_flat(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_train_flat(self, train_id, headers):
        return self._request("GET", f"/trains/{train_id}", headers=headers)

    def list_trains_flat(self, headers, params=None):
        return self._request("GET", "/trains", headers=headers, params=params)

    def get_slot_flat(self, slot_id, headers):
        return self._request("GET", f"/slots/{slot_id}", headers=headers)

    def list_slots_flat(self, headers, params=None):
        return self._request("GET", "/slots", headers=headers, params=params)

    def get_container_flat(self, container_id, headers):
        return self._request("GET", f"/containers/{container_id}", headers=headers)

    def list_containers_flat(self, headers, params=None):
        return self._request("GET", "/containers", headers=headers, params=params)

    def get_appointment_flat(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments_flat(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_transaction_flat(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions_flat(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def get_damage_flat(self, damage_id, headers):
        return self._request("GET", f"/damage/{damage_id}", headers=headers)

    def list_damage_flat(self, headers, params=None):
        return self._request("GET", "/damage", headers=headers, params=params)

    def get_ledger_entry_flat(self, ledger_id, headers):
        return self._request("GET", f"/ledger/{ledger_id}", headers=headers)

    def list_ledger_entries_flat(self, headers, params=None):
        return self._request("GET", "/ledger", headers=headers, params=params)


api_client = ApiClient()
