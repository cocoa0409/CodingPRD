"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods for the mushroom-farm API."""

    # --- Logical clock / ops-run checkpoint ---

    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/api/operations/run-daily-sweep", {}, headers)

    # --- Variety ---

    def create_variety(self, payload, headers):
        return self._request("POST", "/api/varieties", payload, headers)

    def get_variety(self, variety_id, headers):
        return self._request("GET", f"/api/varieties/{variety_id}", headers=headers)

    # --- Buyer ---

    def create_buyer(self, payload, headers):
        return self._request("POST", "/api/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/api/buyers/{buyer_id}", headers=headers)

    def patch_buyer(self, buyer_id, payload, headers):
        return self._request("PATCH", f"/api/buyers/{buyer_id}", payload, headers)

    # --- BuyerCommitment ---

    def create_buyer_commitment(self, payload, headers):
        return self._request("POST", "/api/buyer-commitments", payload, headers)

    def list_buyer_commitments(self, headers, params=None):
        return self._request("GET", "/api/buyer-commitments", headers=headers, params=params)

    def get_buyer_commitment(self, commitment_id, headers):
        return self._request("GET", f"/api/buyer-commitments/{commitment_id}", headers=headers)

    def activate_commitment(self, commitment_id, payload, headers):
        return self._request("POST", f"/api/buyer-commitments/{commitment_id}/activate", payload, headers)

    def cancel_commitment(self, commitment_id, headers):
        return self._request("POST", f"/api/buyer-commitments/{commitment_id}/cancel", {}, headers)

    def add_commitment_line(self, commitment_id, payload, headers):
        return self._request("POST", f"/api/buyer-commitments/{commitment_id}/lines", payload, headers)

    # --- CommitmentLine ---

    def list_commitment_lines(self, headers, params=None):
        return self._request("GET", "/api/commitment-lines", headers=headers, params=params)

    def get_commitment_line(self, line_id, headers):
        return self._request("GET", f"/api/commitment-lines/{line_id}", headers=headers)

    def allocate_commitment_line(self, line_id, payload, headers):
        return self._request("POST", f"/api/commitment-lines/{line_id}/allocate", payload, headers)

    # --- SubstrateBatch ---

    def create_substrate_batch(self, payload, headers):
        return self._request("POST", "/api/substrate-batches", payload, headers)

    def list_substrate_batches(self, headers, params=None):
        return self._request("GET", "/api/substrate-batches", headers=headers, params=params)

    def get_substrate_batch(self, batch_id, headers):
        return self._request("GET", f"/api/substrate-batches/{batch_id}", headers=headers)

    def spawn_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/substrate-batches/{batch_id}/spawn", payload, headers)

    def retire_batch(self, batch_id, headers):
        return self._request("POST", f"/api/substrate-batches/{batch_id}/retire", {}, headers)

    # --- PasteurizationTunnel ---

    def create_tunnel(self, payload, headers):
        return self._request("POST", "/api/pasteurization-tunnels", payload, headers)

    def get_tunnel(self, tunnel_id, headers):
        return self._request("GET", f"/api/pasteurization-tunnels/{tunnel_id}", headers=headers)

    def sanitize_tunnel(self, tunnel_id, headers):
        return self._request("POST", f"/api/pasteurization-tunnels/{tunnel_id}/sanitize", {}, headers)

    # --- PasteurizationCycle ---

    def create_pasteurization_cycle(self, payload, headers):
        return self._request("POST", "/api/pasteurization-cycles", payload, headers)

    def list_pasteurization_cycles(self, headers, params=None):
        return self._request("GET", "/api/pasteurization-cycles", headers=headers, params=params)

    def get_pasteurization_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/pasteurization-cycles/{cycle_id}", headers=headers)

    def start_pasteurization_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/pasteurization-cycles/{cycle_id}/start", {}, headers)

    def complete_pasteurization_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/api/pasteurization-cycles/{cycle_id}/complete", payload, headers)

    def fail_pasteurization_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/pasteurization-cycles/{cycle_id}/fail", {}, headers)

    def abort_pasteurization_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/pasteurization-cycles/{cycle_id}/abort", {}, headers)

    # --- GrowingRoom ---

    def create_room(self, payload, headers):
        return self._request("POST", "/api/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/api/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/api/rooms/{room_id}", headers=headers)

    # --- RoomCycle ---

    def create_room_cycle(self, payload, headers):
        return self._request("POST", "/api/room-cycles", payload, headers)

    def list_room_cycles(self, headers, params=None):
        return self._request("GET", "/api/room-cycles", headers=headers, params=params)

    def get_room_cycle(self, room_cycle_id, headers):
        return self._request("GET", f"/api/room-cycles/{room_cycle_id}", headers=headers)

    def place_room_cycle(self, room_cycle_id, headers):
        return self._request("POST", f"/api/room-cycles/{room_cycle_id}/place", {}, headers)

    def advance_room_cycle(self, room_cycle_id, headers):
        return self._request("POST", f"/api/room-cycles/{room_cycle_id}/advance", {}, headers)

    def end_cropping_room_cycle(self, room_cycle_id, headers):
        return self._request("POST", f"/api/room-cycles/{room_cycle_id}/end-cropping", {}, headers)

    def certify_cleanout_room_cycle(self, room_cycle_id, headers):
        return self._request("POST", f"/api/room-cycles/{room_cycle_id}/certify-cleanout", {}, headers)

    def cancel_room_cycle(self, room_cycle_id, headers):
        return self._request("POST", f"/api/room-cycles/{room_cycle_id}/cancel", {}, headers)

    def abort_room_cycle(self, room_cycle_id, headers):
        return self._request("POST", f"/api/room-cycles/{room_cycle_id}/abort", {}, headers)

    # --- FlushHarvest ---

    def record_flush(self, room_cycle_id, payload, headers):
        return self._request("POST", f"/api/room-cycles/{room_cycle_id}/flushes", payload, headers)

    def list_flushes_of_cycle(self, room_cycle_id, headers, params=None):
        return self._request("GET", f"/api/room-cycles/{room_cycle_id}/flushes", headers=headers, params=params)

    def list_flushes(self, headers, params=None):
        return self._request("GET", "/api/flushes", headers=headers, params=params)

    def get_flush(self, flush_id, headers):
        return self._request("GET", f"/api/flushes/{flush_id}", headers=headers)

    def grade_flush(self, flush_id, payload, headers):
        return self._request("POST", f"/api/flushes/{flush_id}/grade", payload, headers)

    def reopen_flush(self, flush_id, headers):
        return self._request("POST", f"/api/flushes/{flush_id}/reopen", {}, headers)

    # --- PackagedLot ---

    def pack_flush(self, flush_id, payload, headers):
        return self._request("POST", f"/api/flushes/{flush_id}/packaged-lots", payload, headers)

    def list_packaged_lots(self, headers, params=None):
        return self._request("GET", "/api/packaged-lots", headers=headers, params=params)

    def get_packaged_lot(self, lot_id, headers):
        return self._request("GET", f"/api/packaged-lots/{lot_id}", headers=headers)

    def deallocate_packaged_lot(self, lot_id, headers):
        return self._request("POST", f"/api/packaged-lots/{lot_id}/deallocate", {}, headers)

    def ship_packaged_lot(self, lot_id, headers):
        return self._request("POST", f"/api/packaged-lots/{lot_id}/ship", {}, headers)

    # --- HarvestPiece ---

    def log_piece(self, flush_id, payload, headers):
        return self._request("POST", f"/api/flushes/{flush_id}/pieces", payload, headers)

    def list_pieces_of_flush(self, flush_id, headers, params=None):
        return self._request("GET", f"/api/flushes/{flush_id}/pieces", headers=headers, params=params)

    def list_pieces(self, headers, params=None):
        return self._request("GET", "/api/pieces", headers=headers, params=params)

    def get_piece(self, piece_id, headers):
        return self._request("GET", f"/api/pieces/{piece_id}", headers=headers)

    def approve_piece(self, piece_id, headers):
        return self._request("POST", f"/api/pieces/{piece_id}/approve", {}, headers)

    def dispute_piece(self, piece_id, headers):
        return self._request("POST", f"/api/pieces/{piece_id}/dispute", {}, headers)

    # --- Worker ---

    def create_worker(self, payload, headers):
        return self._request("POST", "/api/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/api/workers/{worker_id}", headers=headers)

    def patch_worker(self, worker_id, payload, headers):
        return self._request("PATCH", f"/api/workers/{worker_id}", payload, headers)

    def payout_worker(self, worker_id, headers):
        return self._request("POST", f"/api/workers/{worker_id}/payout", {}, headers)

    # --- ContaminationEvent ---

    def report_contamination_event(self, payload, headers):
        return self._request("POST", "/api/contamination-events", payload, headers)

    def list_contamination_events(self, headers, params=None):
        return self._request("GET", "/api/contamination-events", headers=headers, params=params)

    def get_contamination_event(self, event_id, headers):
        return self._request("GET", f"/api/contamination-events/{event_id}", headers=headers)

    def confirm_contamination_event(self, event_id, headers):
        return self._request("POST", f"/api/contamination-events/{event_id}/confirm", {}, headers)

    def dismiss_contamination_event(self, event_id, headers):
        return self._request("POST", f"/api/contamination-events/{event_id}/dismiss", {}, headers)

    def remediate_contamination_event(self, event_id, headers):
        return self._request("POST", f"/api/contamination-events/{event_id}/remediate", {}, headers)

    def clear_contamination_event(self, event_id, headers):
        return self._request("POST", f"/api/contamination-events/{event_id}/clear", {}, headers)

    # --- SpentSubstrateLot ---

    def list_spent_lots(self, headers, params=None):
        return self._request("GET", "/api/spent-substrate-lots", headers=headers, params=params)

    def get_spent_lot(self, lot_id, headers):
        return self._request("GET", f"/api/spent-substrate-lots/{lot_id}", headers=headers)

    def reserve_spent_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/spent-substrate-lots/{lot_id}/reserve", payload, headers)

    def release_spent_lot(self, lot_id, headers):
        return self._request("POST", f"/api/spent-substrate-lots/{lot_id}/release", {}, headers)

    def sell_spent_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/spent-substrate-lots/{lot_id}/sell", payload, headers)

    def dispose_spent_lot(self, lot_id, headers):
        return self._request("POST", f"/api/spent-substrate-lots/{lot_id}/dispose", {}, headers)


api_client = ApiClient()
