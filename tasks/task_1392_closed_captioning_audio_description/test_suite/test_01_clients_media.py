"""Client administration and media intake: creation defaults, request-shape
rules, intake state machine, and not-found handling (PRD §2.1, §2.4, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_client,
    assert_media_asset,
    assert_same_instant,
    create_client,
    create_client_payload,
    create_media,
    create_media_asset_payload,
    get_success_data,
    is_valid_uuid,
    make_client_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import INTAKE, OPS


class TestClientCreation:
    def test_client_creation_starts_active_with_zero_ytd(self, api):
        """PRD §3.1: "A new client starts with `client_status` `ACTIVE` and
        `ytd_completed_minutes` zero."

        Design: Corner/entities/client_creation_defaults_applied
        """
        resp = api.create_client(
            create_client_payload(name="Acme Broadcasting",
                                  compliance_standard="FCC_BROADCAST"),
            OPS,
        )
        data = validate_success(resp, expected_status=201)
        assert_client(data)
        assert data["client_status"] == "ACTIVE", "new client must start ACTIVE"
        assert data["ytd_completed_minutes"] == 0, "new client must start with ytd 0"

        fetched = validate_success(api.get_client(data["id"], OPS))
        assert fetched["client_status"] == "ACTIVE"
        assert fetched["ytd_completed_minutes"] == 0

    def test_client_system_fields_are_server_minted(self, api):
        """PRD §2.4: "Every persisted resource carries an `id` that is a
        server-minted UUID with no type prefix, and a `created_at` timestamp in
        ISO 8601 UTC with three fractional digits."
        PRD §2.7: "At startup, before any adjustment, the logical clock reads
        exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/client_system_fields_input_ignored
        """
        set_clock("2026-08-03T10:00:00Z")
        payload = create_client_payload(name="Acme", compliance_standard="INTERNAL")
        payload["id"] = "custom-id-1"
        payload["created_at"] = "1999-01-01T00:00:00Z"
        resp = api.create_client(payload, OPS)
        data = validate_success(resp, expected_status=201)
        assert data["id"] != "custom-id-1", "server must mint its own id"
        assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data['id']!r}"
        assert_same_instant(data["created_at"], "2026-08-03T10:00:00.000Z")


class TestMediaIntake:
    def test_media_asset_create_missing_required_duration(self, api):
        """PRD §3.1: "An `IntakeCoordinator` ... registers each asset with its
        owning `client_id`, the program `title`, a `media_kind` of `FILE_BASED`
        or `LIVE_RECORDING`, the `duration_seconds` runtime (which must be
        greater than zero), and the `frame_rate`."
        PRD §2.4: "then request shape and field constraints (`ERR_VALIDATION`)".

        Design: Corner/entities/media_asset_create_missing_required_duration
        """
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        payload = {
            "client_id": client["id"],
            "title": "No Duration",
            "media_kind": "FILE_BASED",
            "frame_rate": "FPS_30",
        }
        resp = api.create_media_asset(payload, INTAKE)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        listing = get_success_data(
            api.list_media_assets(OPS, params={"client_id": client["id"]}))
        assert isinstance(listing, list) and len(listing) == 0, (
            "no MediaAsset row may be created by a rejected payload"
        )

    def test_media_asset_invalid_frame_rate_enum_rejected(self, api):
        """PRD §3.1: "the `frame_rate` — one of `FPS_23_976`, `FPS_24`, `FPS_25`,
        `FPS_29_97_DF`, `FPS_29_97_NDF`, or `FPS_30`, where `DF` denotes
        drop-frame."
        PRD §2.4: "then request shape and field constraints (`ERR_VALIDATION`)".

        Design: Corner/entities/media_asset_invalid_enum_rejected
        """
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        payload = create_media_asset_payload(
            client_id=client["id"], title="Bad FPS", duration_seconds=600,
            frame_rate="FPS_60",
        )
        resp = api.create_media_asset(payload, INTAKE)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_media_reject_missing_required_reason(self, api):
        """PRD §3.1: "From `INSPECTING` the coordinator either clears the asset
        (`INSPECTING` → `CLEARED`) or rejects it (`INSPECTING` →
        `REJECTED_INTAKE`); rejection requires a non-empty `rejection_reason`,
        which is otherwise null."

        Design: Corner/state_machines/media_reject_missing_required_reason
        """
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        asset = create_media(client["id"], duration_seconds=600)
        get_success_data(api.begin_inspection(asset["id"], INTAKE))
        resp = api.reject_media(asset["id"], INTAKE, payload={})
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        after = validate_success(api.get_media_asset(asset["id"], INTAKE))
        assert after["intake_status"] == "INSPECTING", (
            "a rejected reject call must not move the asset out of INSPECTING"
        )

    def test_media_terminal_rejected_lockdown(self, api):
        """PRD §3.1: "`REJECTED_INTAKE` is terminal, and a work order referencing
        such an asset can never be quoted."
        PRD §2.4: "then state-machine admissibility (`ERR_INVALID_TRANSITION`)".

        Design: Corner/state_machines/media_terminal_rejected_lockdown
        """
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        asset = create_media(client["id"], duration_seconds=600)
        get_success_data(api.begin_inspection(asset["id"], INTAKE))
        rejected = validate_success(
            api.reject_media(asset["id"], INTAKE,
                             payload={"rejection_reason": "corrupt container"}))
        assert rejected["intake_status"] == "REJECTED_INTAKE"

        resp = api.begin_inspection(asset["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        after = validate_success(api.get_media_asset(asset["id"], INTAKE))
        assert after["intake_status"] == "REJECTED_INTAKE"
        assert after["rejection_reason"] == "corrupt container"


class TestNotFound:
    def test_work_order_unknown_media_fk_not_found(self, api):
        """PRD §2.4: "then resolution of path identifiers and body foreign keys
        from left to right (a dangling reference yields `ERR_NOT_FOUND`)".

        Design: Corner/entities/work_order_unknown_media_not_found
        """
        client = create_client(name="Acme", compliance_standard="INTERNAL")
        payload = {
            "client_id": client["id"],
            "media_asset_id": NON_EXISTENT_UUID,
            "service_type": "CAPTIONS",
            "turnaround_tier": "STANDARD",
            "language": "en-US",
        }
        resp = api.create_work_order(payload, INTAKE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_caption_track_get_not_found(self, api):
        """PRD §2.4: "then resolution of path identifiers and body foreign keys
        from left to right (a dangling reference yields `ERR_NOT_FOUND`)".

        Design: Corner/entities/caption_track_get_not_found
        """
        resp = api.get_caption_track(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
