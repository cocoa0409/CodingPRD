"""Escrow file opening and holdback creation: defaults, sizing, and input shape."""
import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_STAMP,
    PARTIES,
    STANDARD,
    TEST_USERS,
    assert_escrow_file,
    assert_holdback,
    create_draft_holdback,
    create_dispute,
    create_draw,
    create_extension,
    create_file_payload,
    create_holdback_payload,
    get_approvals,
    list_ledger,
    schedule_inspection,
    select_bid,
    set_logical_clock,
    setup_active_holdback,
    setup_escrow_file,
    setup_pending_holdback,
    submit_bid,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestEscrowFileCreation:
    def test_escrow_file_creation_returns_open_with_echoed_parties(self, api):
        """PRD §3.1: "The file's `status` is derived rather than set directly: it reads `OPEN` while the file has no holdback or its holdback is in any non-terminal state, and it reads `CLOSED` once the holdback reaches `CLOSED_COMPLETED` or `CLOSED_EXPIRED`."

        A freshly created file echoes its parties, reads OPEN, and a GET re-read
        returns identical stored data; both responses carry the object envelope.

        Design: Corner/entities/escrow_file_creation_defaults
        """
        set_logical_clock()
        payload = create_file_payload()  # includes insurer_user_id
        created = validate_success(api.create_file(payload, OFFICER), 201)
        assert_escrow_file(created)
        assert created["status"] == "OPEN"
        assert isinstance(created["version"], int)
        for key in ("property_address", "closing_date", "buyer_user_id",
                    "seller_user_id", "lender_user_id", "insurer_user_id"):
            assert created[key] == payload[key], f"{key} must be echoed"

        fetched = validate_success(api.get_file(created["id"], OFFICER), 200)
        assert fetched["status"] == "OPEN"
        assert fetched["buyer_user_id"] == PARTIES["buyer"]
        assert fetched["insurer_user_id"] == PARTIES["insurer"]
        assert fetched["id"] == created["id"]

    def test_default_clock_fixed_at_epoch_without_any_set(self, api):
        """PRD §2.4: "Before any explicit set, the clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to the host's wall clock under any circumstances."
        PRD §2.4: "Timestamp fields — `created_at`, `updated_at`, `started_at`, `submitted_completion_at`, `reported_at`, `approved_at`, `paid_at`, `decided_at`, `resolved_at`, `deposited_at`, and the inspection scheduling bounds — are ISO 8601 UTC instants with three fractional digits."

        With no clock call issued, a created file's created_at is the fixed
        default epoch rendered with three fractional digits.

        Design: Corner/complexity_layers/default_clock_is_fixed_at_scaffold_epoch
        """
        payload = create_file_payload()
        payload.pop("insurer_user_id", None)
        created = validate_success(api.create_file(payload, OFFICER), 201)
        assert created["created_at"] == DEFAULT_CLOCK_STAMP, (
            f"expected the fixed default epoch, got {created['created_at']}"
        )


class TestHoldbackCreation:
    def test_holdback_creation_computes_amount_and_posts_funding(self, api):
        """PRD §3.1: "The `holdback_amount_cents` is the repair estimate scaled up by the contingency — the estimate multiplied by one hundred plus `contingency_pct`, divided by one hundred, rounded half-up to whole cents at this final multiplication."
        PRD §3.1: "creation immediately withholds the funds by appending a `FUNDING` entry for the positive holdback amount as the ledger's `seq` 1, so `trust_balance_cents` starts equal to `holdback_amount_cents`."
        PRD §3.1: "`granted_extension_days` starts at 0, so `effective_deadline_date` initially equals `work_deadline_date`; `selected_bid_id` and `disposition_override` start null; `work_verified` is false while no work order exists; `disbursement_frozen` is false while no dispute is `OPEN`; and `closeout_status` reads `NOT_READY`."

        Design: Corner/entities/holdback_creation_computes_amount_and_funding
        """
        set_logical_clock()
        file = setup_escrow_file()
        hb = validate_success(
            api.create_holdback(create_holdback_payload(escrow_file_id=file["id"]),
                                OFFICER),
            201,
        )
        assert_holdback(hb)
        assert hb["holdback_amount_cents"] == STANDARD["holdback_amount_cents"] == 230000
        assert hb["trust_balance_cents"] == 230000
        assert hb["status"] == "DRAFT"
        assert hb["granted_extension_days"] == 0
        assert hb["effective_deadline_date"] == STANDARD["work_deadline_date"]
        assert hb["lender_approval_required"] is True
        assert hb["insurer_approval_required"] is False
        assert hb["disbursement_frozen"] is False
        assert hb["closeout_status"] == "NOT_READY"
        assert hb["selected_bid_id"] is None
        assert hb["disposition_override"] is None
        assert hb["commitment_basis_cents"] is None
        assert hb["work_verified"] is False

        entries = list_ledger(hb["id"])
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "FUNDING"
        assert entries[0]["amount_cents"] == 230000
        assert entries[0]["running_balance_cents"] == 230000
        assert entries[0]["seq"] == 1

    def test_holdback_create_invalid_funding_source_rejected(self, api):
        """PRD §2.9: "Input shape, on every creation or action request: required fields present, enum members valid, integer ranges honored (the contingency percentage between 10 and 25 inclusive, requested extension days between 1 and 45 inclusive, monetary amounts strictly positive, a disputed amount zero or positive), `work_deadline_date` on or before `hard_stop_date`, `scheduled_start` strictly before `scheduled_end`, and no unknown body fields — otherwise `ERR_VALIDATION` (HTTP 400)."
        PRD §3.1: "a `funding_source` of `SELLER_PROCEEDS`, `BUYER_DEPOSIT`, or `SPLIT_EQUAL` recording who funded the holdback"

        Design: Corner/entities/holdback_create_invalid_enum_rejected
        """
        set_logical_clock()
        file = setup_escrow_file()
        payload = create_holdback_payload(escrow_file_id=file["id"],
                                          funding_source="SIDE_POCKET")
        resp = api.create_holdback(payload, OFFICER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_holdback_create_contingency_pct_bounds(self, api):
        """PRD §3.1: "a `contingency_pct` that must be an integer between 10 and 25 inclusive"
        PRD §2.9: "Violations of these shapes and ranges are `ERR_VALIDATION`."

        9 and 26 are rejected; the boundary value 10 is accepted and sizes to
        220000 (200000 x 1.10).

        Design: Corner/entities/holdback_create_contingency_bounds
        """
        set_logical_clock()
        file = setup_escrow_file()
        base = create_holdback_payload(escrow_file_id=file["id"])

        low = api.create_holdback({**base, "contingency_pct": 9}, OFFICER)
        validate_error(low, ApiErrorId.ERR_VALIDATION)

        high = api.create_holdback({**base, "contingency_pct": 26}, OFFICER)
        validate_error(high, ApiErrorId.ERR_VALIDATION)

        # Boundary value 10 accepted; consumes the file's single holdback slot.
        ok = validate_success(
            api.create_holdback({**base, "contingency_pct": 10}, OFFICER), 201)
        assert ok["holdback_amount_cents"] == 220000

    def test_holdback_create_deadline_after_hard_stop_rejected(self, api):
        """PRD §3.1: "The schedule is fixed by `work_deadline_date` — which must be on or before `hard_stop_date`, the absolute latest completion date that no extension may ever push the effective deadline past"
        PRD §2.9: "`work_deadline_date` on or before `hard_stop_date`, `scheduled_start` strictly before `scheduled_end`, and no unknown body fields — otherwise `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/holdback_create_deadline_after_hard_stop_rejected
        """
        set_logical_clock()
        file = setup_escrow_file()
        payload = create_holdback_payload(
            escrow_file_id=file["id"],
            work_deadline_date="2026-11-15",
            hard_stop_date="2026-10-15",
        )
        resp = api.create_holdback(payload, OFFICER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_holdback_create_unknown_computed_field_rejected(self, api):
        """PRD §2.9: "Input shape, on every creation or action request: required fields present, enum members valid, integer ranges honored (the contingency percentage between 10 and 25 inclusive, requested extension days between 1 and 45 inclusive, monetary amounts strictly positive, a disputed amount zero or positive), `work_deadline_date` on or before `hard_stop_date`, `scheduled_start` strictly before `scheduled_end`, and no unknown body fields — otherwise `ERR_VALIDATION` (HTTP 400)."

        trust_balance_cents is server-computed; sending it in the create body is
        an unknown-field validation failure.

        Design: Corner/entities/holdback_create_unknown_computed_field_rejected
        """
        set_logical_clock()
        file = setup_escrow_file()
        payload = create_holdback_payload(escrow_file_id=file["id"])
        payload["trust_balance_cents"] = 1
        resp = api.create_holdback(payload, OFFICER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_second_holdback_on_file_rejected(self, api):
        """PRD §3.1: "A file carries at most one holdback; attempting to create a second one on the same file fails with `ERR_HOLDBACK_ALREADY_EXISTS`."

        Design: Corner/validations/second_holdback_on_file_rejected
        """
        set_logical_clock()
        file = setup_escrow_file()
        create_draft_holdback(file["id"])
        second = api.create_holdback(
            create_holdback_payload(
                escrow_file_id=file["id"], repair_scope="Fence",
                repair_estimate_cents=50000, contingency_pct=10,
                funding_source="BUYER_DEPOSIT", overrun_responsibility="SELLER",
                expiration_terms="RELEASE_TO_BUYER", exterior_work_flag=False),
            OFFICER,
        )
        validate_error(second, ApiErrorId.ERR_HOLDBACK_ALREADY_EXISTS)

    def test_holdback_amount_rounding_half_up(self, api):
        """PRD §2.6: "Whenever a multiplication would produce a fractional cent, the result is rounded half-up to the nearest whole cent (a fractional part of exactly one half rounds up), and this rounding is applied at the final multiplication only, never to intermediate terms."

        10005 x 1.10 = 11005.5 must round half-up to 11006.

        Design: Corner/calculations/holdback_amount_rounding_half_up
        """
        set_logical_clock()
        file = setup_escrow_file()
        hb = validate_success(
            api.create_holdback(
                create_holdback_payload(escrow_file_id=file["id"],
                                        repair_scope="Half-cent case",
                                        repair_estimate_cents=10005,
                                        contingency_pct=10,
                                        exterior_work_flag=False),
                OFFICER),
            201,
        )
        assert hb["holdback_amount_cents"] == 11006, (
            "round_half_up(10005 * 110 / 100) == 11006"
        )


class TestInitialStates:
    def test_initial_states_visible_on_create(self, api):
        """PRD §3.1: "The holdback is born in `DRAFT`."
        PRD §3.2: "Each new approval begins in `REQUESTED` with `approver_user_id`, `holdback_version_at_decision`, and `decided_at` all null."
        PRD §3.3: "the server records the caller as the bid's `contractor_user_id` and the bid enters `SUBMITTED`."
        PRD §3.4: "A scheduled inspection begins in `PLANNED`."
        PRD §3.5: "the request enters `SUBMITTED` with `contractor_user_id` set to the caller and `approved_at` and `paid_at` null."
        PRD §3.6: "The request is born `PENDING`, records the caller as `requester_user_id`, and leaves `granted_days` null until granted and `decided_at` null until decided."
        PRD §3.7: "The moment a dispute stands `OPEN`, the holdback's `disbursement_frozen` recomputes to true"

        Each create response exposes its machine's initial state.

        Design: Corner/state_machines/initial_states_visible_on_create
        """
        set_logical_clock()
        ctx = setup_active_holdback(clock=None)
        file, hb = ctx["file"], ctx["holdback"]

        # Holdback initial state DRAFT was consumed by activation; re-observe on
        # a fresh file to assert the create response itself.
        fresh_file = setup_escrow_file()
        fresh_hb = create_draft_holdback(fresh_file["id"])
        assert fresh_hb["status"] == "DRAFT"

        # The REQUESTED initial state was consumed by activation; a fresh
        # pending holdback shows a REQUESTED approval in its birth state.
        pending = setup_pending_holdback(clock=None)
        requested = [a for a in pending["approvals"] if a["status"] == "REQUESTED"]
        assert len(requested) == 1
        assert requested[0]["approver_user_id"] is None
        assert requested[0]["holdback_version_at_decision"] is None
        assert requested[0]["decided_at"] is None

        bid = submit_bid(hb["id"])
        assert bid["status"] == "SUBMITTED"
        assert bid["contractor_user_id"] == PARTIES["contractor"]
        select_bid(bid["id"], file)

        from test_helpers import schedule_inspection
        ins = schedule_inspection(hb["id"], scheduled_start="2026-08-20T10:00:00Z",
                                  scheduled_end="2026-08-20T11:00:00Z")
        assert ins["status"] == "PLANNED"
        assert ins["reported_at"] is None

        draw = create_draw(hb["id"], 1000, description="Mobilization")
        assert draw["status"] == "SUBMITTED"
        assert draw["approved_at"] is None
        assert draw["paid_at"] is None

        ext = create_extension(hb["id"], TEST_USERS["seller_1_headers"],
                               reason="SUPPLY_DELAY", requested_days=3,
                               evidence_ref="supplier letter")
        assert ext["status"] == "PENDING"
        assert ext["granted_days"] is None
        assert ext["decided_at"] is None
        assert ext["requester_user_id"] == PARTIES["seller"]

        disp = create_dispute(hb["id"], TEST_USERS["buyer_1_headers"],
                              category="OTHER", claimed_amount_cents=0,
                              statement="Record request")
        assert disp["status"] == "OPEN"
        assert disp["resolved_at"] is None
