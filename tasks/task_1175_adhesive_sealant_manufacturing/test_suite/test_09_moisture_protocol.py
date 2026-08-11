"""Moisture protocol: dry-room requirement for moisture-sensitive formulations."""
from test_helpers import (
    ApiErrorId,
    create_formulation,
    create_mixed_batch,
    create_vessel,
    set_clock,
    validate_error,
)


def test_moisture_sensitive_run_without_dry_room_returns_422(api, batch_operator_headers):
    """PRD §3.4: "The `dry_room_id` field is optional in general but **required** when the batch's formulation is `moisture_sensitive`; omitting it for such a formulation is rejected with `ERR_MOISTURE_PROTOCOL_VIOLATION`."

    Design: Corner/errors/moisture_sensitive_run_without_dry_room_returns_422
    """
    set_clock()
    formulation = create_formulation(
        "SIL-MST", activate=True, chemistry_family="SILICONE", moisture_sensitive=True
    )
    vessel = create_vessel("V-MST", capacity_liters=100)
    batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)

    resp = api.create_packaging_run(
        {
            "batch_id": batch["id"],
            "pack_format": "CARTRIDGE",
            "unit_volume_ml": 310,
            "planned_units": 3,
            "planned_start_at": "2026-05-01T08:10:00Z",
            "planned_end_at": "2026-05-01T09:30:00Z",
        },
        batch_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_MOISTURE_PROTOCOL_VIOLATION)
