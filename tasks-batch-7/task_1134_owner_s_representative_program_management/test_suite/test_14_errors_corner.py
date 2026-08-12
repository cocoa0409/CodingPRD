"""Queue B — errors section corner tests (non-stub only)."""
from test_helpers import (
    api_client, validate_error, pm_headers, owner_headers,
    NON_EXISTENT_UUID, ApiErrorId,
)


def test_wave_not_found_on_confirm_returns_404(api):
    """PRD §2.10: "Existence failures surface the resource-specific 404 for
    the first identifier that cannot be resolved: ... ERR_WAVE_NOT_FOUND ...".

    Design: Corner/errors/wave_not_found_on_confirm_returns_404
    """
    resp = api_client.confirm_move_in_wave(NON_EXISTENT_UUID, pm_headers())
    validate_error(resp, ApiErrorId.ERR_WAVE_NOT_FOUND)


def test_report_not_found_returns_404(api):
    """PRD §2.10: "Existence failures surface the resource-specific 404 for
    the first identifier that cannot be resolved: ... ERR_REPORT_NOT_FOUND
    ...".

    Design: Corner/errors/report_not_found_returns_404
    """
    resp = api_client.get_owner_report(NON_EXISTENT_UUID, owner_headers())
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND)
