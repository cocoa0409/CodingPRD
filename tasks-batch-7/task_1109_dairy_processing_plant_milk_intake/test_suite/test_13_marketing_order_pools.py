"""Marketing order pools: the FMMO announcement window and OCC on finalize."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_pool,
    get_success_data,
    make_pool,
    set_clock,
    validate_error,
    validate_success,
)

PC = TEST_USERS["plant_controller_headers"]


class TestAnnouncementWindow:
    def test_announce_before_23rd_rejected(self, api):
        """PRD §3.10: "And the current logical clock must be at or after the
        23rd of the month following `pool_month` at 00:00 UTC — the FMMO
        announcement date — otherwise `ERR_ANNOUNCEMENT_TOO_EARLY`."

        Design: Corner/state_machines/pool_announce_too_early_blocked
        """
        set_clock("2026-06-22T23:59:59Z")
        pool = make_pool(pool_month="2026-05")

        res = api.announce_pool(pool["id"], {}, PC)
        validate_error(res, ApiErrorId.ERR_ANNOUNCEMENT_TOO_EARLY)
        assert get_pool(pool["id"])["status"] == "DRAFT"

    def test_announce_on_23rd_succeeds(self, api):
        """PRD §3.10: "And the current logical clock must be at or after the
        23rd of the month following `pool_month` at 00:00 UTC — the FMMO
        announcement date — otherwise `ERR_ANNOUNCEMENT_TOO_EARLY`." At exactly
        the announcement instant the precondition is met ("at or after").

        Design: Corner/state_machines/pool_announce_too_early_blocked
        """
        set_clock("2026-06-23T00:00:00Z")
        pool = make_pool(pool_month="2026-05")

        announced = validate_success(api.announce_pool(pool["id"], {}, PC), 200)
        assert announced["status"] == "ANNOUNCED"


def test_finalize_with_stale_pool_version_rejected(api):
    """PRD §2.7: "the request must include `expected_pool_version` carrying the
    `version` value of the `MarketingOrderPool` the client most recently
    observed. If the pool's current `version` no longer matches — because
    another writer has since announced it, which legitimately bumps `version` —
    the finalize is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_pool_version_returns_412
    """
    set_clock("2026-05-01T00:00:00Z")
    pool = make_pool(pool_month="2026-05")
    stale_version = pool["version"]

    set_clock("2026-06-23T00:00:00Z")
    get_success_data(api.announce_pool(pool["id"], {}, PC))  # bumps version

    res = api.finalize_pool(pool["id"], {"expected_pool_version": stale_version}, PC)
    validate_error(res, ApiErrorId.ERR_STALE_POOL_VERSION)
