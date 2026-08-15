"""Workshop administration: OCC-guarded PATCH and request-shape validation
(PRD §3.1, §2.8)."""
from test_helpers import (
    ApiErrorId,
    create_workshop_payload,
    setup_workshop_scenario,
    validate_error,
    validate_success,
)


def test_occ_workshop_patch_stale_version_returns_412_and_version_increments(
    api, admin_headers
):
    """PRD §2.8: "Rescheduling or re-capacitating a workshop requires
    `expected_workshop_version`, carrying the client's last observed `version`
    of the workshop; a mismatch is likewise rejected with `ERR_STALE_VERSION`
    (HTTP 412)." PRD §2.8: "every successful workshop reschedule increments the
    workshop's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_workshop_patch_stale_version_returns_412_and_version_increments
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        module_overrides=dict(module_code="VP-100", session_count=1,
                              completion_threshold=1),
    )
    workshop = ctx["workshop"]
    observed_version = workshop["version"]
    assert observed_version == 1

    patched = validate_success(
        api.patch_workshop(
            workshop["id"],
            {"capacity": 8, "expected_workshop_version": observed_version},
            admin_headers,
        )
    )
    assert patched["version"] == observed_version + 1, (
        "a successful reschedule increments the workshop version by exactly 1"
    )
    assert patched["capacity"] == 8

    # Replaying the now-stale creation version is rejected and changes nothing.
    resp = api.patch_workshop(
        workshop["id"],
        {"capacity": 9, "expected_workshop_version": observed_version},
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    final = validate_success(api.get_workshop(workshop["id"], admin_headers))
    assert final["capacity"] == 8


def test_workshop_create_end_before_start_returns_400(api, admin_headers):
    """PRD §3.1: "An `end_at` that is not strictly after `start_at` is
    malformed (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/workshop_create_end_before_start_returns_400
    """
    ctx = setup_workshop_scenario(
        admin_headers,
        module_overrides=dict(module_code="EB-100", session_count=1,
                              completion_threshold=1),
    )
    resp = api.create_workshop(
        create_workshop_payload(
            ctx["module"]["id"], ctx["coach"]["id"],
            start_at="2026-08-10T11:00:00Z", end_at="2026-08-10T10:00:00Z",
        ),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
