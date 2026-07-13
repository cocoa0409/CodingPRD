"""Statements of work: countersign, the rate pin, and clock-driven expiry."""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    assert_sow,
    create_campaign_payload,
    create_sow_payload,
    create_time_entry_payload,
    log_time,
    make_account_manager_headers,
    make_agency_admin_headers,
    make_client_reviewer_headers,
    register_client,
    register_staff,
    set_clock,
    setup_base,
    validate_error,
    validate_success,
)


def _parse(instant: str) -> datetime:
    return datetime.fromisoformat(instant.replace("Z", "+00:00"))


def test_countersign_freezes_the_rate_card_against_a_later_revision(api):
    """PRD §3.2: "Countersigning moves the SOW `DRAFT → COUNTERSIGNED` and, in the same breath,
    **freezes the price list**: the rate card's `version` is copied into
    `pinned_rate_card_version` and its three live rate columns are copied into the three pinned
    rate columns. From that moment the SOW bills at the frozen rates for the rest of its life.
    An agency operator may revise the rate card afterwards as often as they like; not one cent
    of that revision reaches a SOW that has already been countersigned."
    PRD §3.5: "the server reaches through the campaign to its statement of work, selects the
    pinned rate column matching the staff member's `grade` — the pinned junior rate for
    `JUNIOR`, the pinned senior rate for `SENIOR`, the pinned director rate for `DIRECTOR` — and
    copies it into `pinned_rate_cents_per_hour`. The live rate card is never consulted."

    Design: Corner/entities/sow_pinned_rates_survive_a_later_rate_card_edit
    """
    base = setup_base()

    patched = validate_success(
        api.update_rate_card(
            base["rate_card_id"], {"rate_senior_cents_per_hour": 30_000}, base["admin_headers"]
        )
    )
    assert patched["rate_senior_cents_per_hour"] == 30_000
    assert patched["version"] == 2, "each rate-card revision bumps the card's version"

    sow = validate_success(api.get_sow(base["sow_id"], base["admin_headers"]))
    assert sow["pinned_rate_senior_cents_per_hour"] == 20_000
    assert sow["pinned_rate_card_version"] == 1

    entry = log_time(base, "dana", "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    assert entry["pinned_rate_cents_per_hour"] == 20_000
    assert entry["estimated_amount_cents"] == 20_000


def test_launching_a_campaign_under_an_unsigned_sow_is_rejected(api):
    """PRD §3.3: "Three preconditions apply beyond the campaign itself already being `DRAFT`:
    the `brief_summary` must be non-empty, the governing SOW must be `COUNTERSIGNED` (a `DRAFT`
    SOW raises `ERR_SOW_NOT_COUNTERSIGNED` and an `EXPIRED` one raises `ERR_SOW_EXPIRED`), and
    the owning advertiser must be `ACTIVE` — an advertiser sitting in `CREDIT_HOLD` raises
    `ERR_CAMPAIGN_ON_HOLD`."
    PRD §3.2: "A new SOW has `status` `DRAFT`, a `consumed_labor_cents` of 0, and all four of
    its pinned columns — `pinned_rate_card_version`, `pinned_rate_junior_cents_per_hour`,
    `pinned_rate_senior_cents_per_hour` and `pinned_rate_director_cents_per_hour` — set to null."

    Design: Corner/state_machines/campaign_launch_with_draft_sow_returns_sow_not_countersigned
    """
    base = setup_base(countersign=False, launch=False)

    resp = api.launch_campaign(base["campaign_id"], base["am_headers"])
    validate_error(resp, ApiErrorId.ERR_SOW_NOT_COUNTERSIGNED.value)
    assert resp.status_code == 409

    campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
    assert campaign["status"] == "DRAFT"

    sow = validate_success(api.get_sow(base["sow_id"], base["am_headers"]))
    assert_sow(sow)
    assert sow["status"] == "DRAFT"
    assert sow["pinned_rate_card_version"] is None


def test_countersigning_an_already_signed_sow_is_rejected(api):
    """PRD §3.2: "Countersigning is the client's act, performed by the `ClientReviewer` whose
    `X-User-ID` is the advertiser the SOW names, and it is legal only from `DRAFT` and only
    while the logical clock still reads earlier than the SOW's `effective_end`; a countersign
    attempted at or after that instant is rejected with `ERR_SOW_EXPIRED`."
    PRD §2.8: "The target entity is in a state from which the requested transition is legal —
    otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/countersign_twice_second_call_returns_invalid_state
    """
    base = setup_base(launch=False)
    assert base["sow"]["version"] == 2, "create (v1) then countersign (v2)"

    resp = api.countersign_sow(base["sow_id"], base["reviewer_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409

    sow = validate_success(api.get_sow(base["sow_id"], base["reviewer_headers"]))
    assert sow["status"] == "COUNTERSIGNED"
    assert sow["version"] == 2, "a rejected call must not bump the version"


def test_fresh_server_logical_clock_reads_2026_05_01(api):
    """PRD §2.5: "It keeps a logical clock which, before any caller has moved it, reads exactly
    `2026-05-01T00:00:00Z`, and which never falls back to real time."
    PRD §3.2: "it is legal only from `DRAFT` and only while the logical clock still reads
    earlier than the SOW's `effective_end`; a countersign attempted at or after that instant is
    rejected with `ERR_SOW_EXPIRED`."
    PRD §3.2: "When the logical clock is moved to or past a `COUNTERSIGNED` SOW's
    `effective_end`, that SOW transitions `COUNTERSIGNED → EXPIRED` and its identifier appears
    in the clock call's `expired_sow_ids`."

    Design: Corner/endpoints/logical_clock_default_is_2026_05_01_on_a_fresh_server
    """
    admin = make_agency_admin_headers()
    client = register_client()
    rate_card = validate_success(api.create_rate_card(
        {"name": "Standard 2026", "rate_junior_cents_per_hour": 12_000,
         "rate_senior_cents_per_hour": 20_000, "rate_director_cents_per_hour": 32_000}, admin), 201)
    ravi = register_staff(full_name="Ravi Iyer", grade="JUNIOR", cost_rate_cents_per_hour=3_000)
    am = make_account_manager_headers(ravi["id"])
    reviewer = make_client_reviewer_headers(client["id"])

    sow_a = validate_success(api.create_sow(create_sow_payload(
        client["id"], rate_card["id"], title="Ends 2026-05-01",
        effective_start="2026-04-01", effective_end="2026-05-01"), am), 201)
    sow_b = validate_success(api.create_sow(create_sow_payload(
        client["id"], rate_card["id"], title="Ends 2026-05-02",
        effective_start="2026-04-01", effective_end="2026-05-02"), am), 201)

    # The default clock sits exactly on SOW A's effective_end, so it is already too late.
    resp = api.countersign_sow(sow_a["id"], reviewer)
    validate_error(resp, ApiErrorId.ERR_SOW_EXPIRED.value)
    assert resp.status_code == 409
    assert validate_success(api.get_sow(sow_a["id"], admin))["status"] == "DRAFT"

    # SOW B ends one day later, so the very same clock still permits the signature.
    signed_b = validate_success(api.countersign_sow(sow_b["id"], reviewer))
    assert signed_b["status"] == "COUNTERSIGNED"
    assert signed_b["pinned_rate_senior_cents_per_hour"] == 20_000

    clock = validate_success(api.set_clock("2026-05-02T00:00:00Z", admin))
    assert _parse(clock["now_utc"]) == _parse("2026-05-02T00:00:00Z")
    assert sow_b["id"] in clock["expired_sow_ids"]
    assert validate_success(api.get_sow(sow_b["id"], admin))["status"] == "EXPIRED"


class TestTimeEntryBlockedByExpiredSow:
    """Difficulty: cross_entity_state_dependency / time_entry_creation_gated_by_expired_sow."""

    @staticmethod
    def _setup(api):
        base = setup_base()
        set_clock("2026-09-01T00:00:00Z")
        return base

    def test_logging_time_under_an_expired_sow_is_rejected(self, api):
        """PRD §3.2: "Expiry does not cascade to campaigns — a campaign under an expired SOW
        stays exactly where it was — but no further time may be logged against it: such an
        attempt is rejected with `ERR_SOW_EXPIRED`."
        PRD §2.8: "The cross-entity state gate on the governing statement of work: it must be
        `COUNTERSIGNED`. A `DRAFT` SOW rejects with `ERR_SOW_NOT_COUNTERSIGNED` (HTTP 409) and
        an `EXPIRED` SOW rejects with `ERR_SOW_EXPIRED` (HTTP 409). This gate guards two
        operations: time-entry creation and campaign launch."

        Design: Difficulty/cross_entity_state_dependency/time_entry_creation_gated_by_expired_sow
        """
        base = self._setup(api)

        resp = api.create_time_entry(
            create_time_entry_payload(
                base["campaign_id"], base["dana_id"],
                "2026-08-31T09:00:00Z", "2026-08-31T10:00:00Z",
            ),
            base["dana_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SOW_EXPIRED.value)
        assert resp.status_code == 409

        sow = validate_success(api.get_sow(base["sow_id"], base["admin_headers"]))
        assert sow["status"] == "EXPIRED"
        assert sow["consumed_labor_cents"] == 0, "the rejected entry must not be booked"

    def test_expiry_leaves_the_campaign_in_flight(self, api):
        """PRD §3.2: "Expiry does not cascade to campaigns — a campaign under an expired SOW
        stays exactly where it was — but no further time may be logged against it: such an
        attempt is rejected with `ERR_SOW_EXPIRED`."
        PRD §3.2: "A statement of work retires by clock, not by request."

        Design: Difficulty/cross_entity_state_dependency/time_entry_creation_gated_by_expired_sow
        """
        base = self._setup(api)

        campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
        assert campaign["status"] == "IN_FLIGHT", (
            "SOW expiry must not cascade into the campaign's own state machine"
        )
        assert validate_success(api.get_sow(base["sow_id"], base["am_headers"]))["status"] == "EXPIRED"
