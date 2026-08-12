"""Duplicate flags: auto-flag at registration, parallel Bicycle status dimensions,
confirm-merge cascade, dismiss, and merged-bicycle lockdown (PRD §2.10, §3.2, §3.8)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_owner,
    register_bicycle,
    file_theft_report,
    flag_report,
    setup_duplicate_suspect_pair,
    create_transfer_payload,
    make_owner_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestParallelDimensions:
    def test_parallel_dimensions_stolen_and_suspect_then_dismiss(self, api):
        """PRD §2.10: "The `integrity_status` dimension tracks database accuracy —
        `CLEAR`, `DUPLICATE_SUSPECT`, `MERGED` — and is independent of the theft
        lifecycle ... a `STOLEN` bicycle can simultaneously be `DUPLICATE_SUSPECT`."
        PRD §3.8: "Dismissing a flag, likewise from `OPEN`, exonerates the pair:
        both bicycles return from `DUPLICATE_SUSPECT` to `CLEAR`, each incrementing
        its `version`, and the flag moves to `DISMISSED`."

        Design: Difficulty/non_linear_state_machine/bicycle_parallel_dimensions_independent
        """
        owner, bicycle_a, _bicycle_b, flag = setup_duplicate_suspect_pair()
        # Theft lifecycle flips registry_status while integrity stays DUPLICATE_SUSPECT.
        report = file_theft_report(owner, bicycle_a)
        flag_report(report["id"])
        pre = validate_success(api.get_bicycle(bicycle_a["id"], REGISTRAR))
        assert pre["registry_status"] == "STOLEN"
        assert pre["integrity_status"] == "DUPLICATE_SUSPECT", (
            "both dimensions must coexist on one row: STOLEN and DUPLICATE_SUSPECT"
        )
        # Dismiss resolves integrity only; the theft lifecycle is untouched.
        dismissed = validate_success(api.dismiss_duplicate_flag(flag["id"], REGISTRAR))
        assert dismissed["status"] == "DISMISSED"
        post = validate_success(api.get_bicycle(bicycle_a["id"], REGISTRAR))
        assert post["integrity_status"] == "CLEAR", (
            f"dismiss must restore CLEAR, got {post['integrity_status']}"
        )
        assert post["registry_status"] == "STOLEN", (
            f"registry_status must stay STOLEN after dismiss, got {post['registry_status']}"
        )

    def test_auto_flag_pair_records_direction_and_confidence(self, api):
        """PRD §3.2: "A non-exact pair whose duplicate confidence reaches at least
        8500 basis points auto-creates a `DuplicateFlag` in `OPEN` status and flips
        both bicycles' `integrity_status` from `CLEAR` to `DUPLICATE_SUSPECT`
        (incrementing each bicycle's `version`); the auto-created flag records
        `bicycle_a_id` as the pre-existing bicycle and `bicycle_b_id` as the newly
        created one."
        PRD §3.2: "The confidence is the weighted sum — serial points at weight
        0.60, manufacturer points at 0.25, model points at 0.15 — multiplied by
        10000 and rounded half-up to an integer number of basis points between 0
        and 10000."

        DUP100 vs DUP101: serial_pts = 1 - 1/6, mfr and model full credit, so the
        confidence is round_half_up(10000 * (0.6 * 5/6 + 0.25 + 0.15)) == 9000.

        Design: Difficulty/non_linear_state_machine/bicycle_parallel_dimensions_independent
        """
        owner, bicycle_a, bicycle_b, flag = setup_duplicate_suspect_pair()
        assert flag["status"] == "OPEN"
        assert flag["bicycle_a_id"] == bicycle_a["id"], (
            "bicycle_a_id must be the pre-existing bicycle"
        )
        assert flag["bicycle_b_id"] == bicycle_b["id"], (
            "bicycle_b_id must be the newly created bicycle"
        )
        assert flag["confidence_score"] == 9000, (
            f"expected confidence 9000 for the DUP100/DUP101 pair, "
            f"got {flag['confidence_score']}"
        )
        read_a = validate_success(api.get_bicycle(bicycle_a["id"], REGISTRAR))
        read_b = validate_success(api.get_bicycle(bicycle_b["id"], REGISTRAR))
        assert read_a["integrity_status"] == "DUPLICATE_SUSPECT"
        assert read_b["integrity_status"] == "DUPLICATE_SUSPECT"


class TestDuplicateFlagResolution:
    def test_duplicate_flag_confirm_merges_loser(self, api):
        """PRD §3.8: "The other bicycle — the loser — moves from
        `DUPLICATE_SUSPECT` to `MERGED`, and the merge cascade strips its open
        obligations: every theft report on the loser still in `UNDER_REVIEW` or
        `NEEDS_INFO` moves to `WITHDRAWN`, and every `PENDING_ACCEPTANCE` transfer
        on the loser moves to `CANCELLED`. The survivor returns from
        `DUPLICATE_SUSPECT` to `CLEAR`. The flag stores the chosen
        `merged_into_bicycle_id` and moves to `CONFIRMED`;"

        Design: Corner/state_machines/duplicate_flag_confirm_merges_loser
        """
        owner, bicycle_a, bicycle_b, flag = setup_duplicate_suspect_pair()
        report_b = file_theft_report(owner, bicycle_b)
        assert report_b["status"] == "UNDER_REVIEW"
        confirmed = validate_success(
            api.confirm_duplicate_flag(
                flag["id"], {"merged_into_bicycle_id": bicycle_a["id"]}, REGISTRAR
            )
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["merged_into_bicycle_id"] == bicycle_a["id"]
        loser = validate_success(api.get_bicycle(bicycle_b["id"], REGISTRAR))
        survivor = validate_success(api.get_bicycle(bicycle_a["id"], REGISTRAR))
        assert loser["integrity_status"] == "MERGED", (
            f"loser must be MERGED, got {loser['integrity_status']}"
        )
        assert survivor["integrity_status"] == "CLEAR", (
            f"survivor must return to CLEAR, got {survivor['integrity_status']}"
        )
        report_b_after = validate_success(api.get_theft_report(report_b["id"], REGISTRAR))
        assert report_b_after["status"] == "WITHDRAWN", (
            f"loser's UNDER_REVIEW report must be auto-WITHDRAWN, got "
            f"{report_b_after['status']}"
        )

    def test_dismiss_dismissed_flag_rejected(self, api):
        """PRD §3.8: "Dismissing a flag, likewise from `OPEN`, exonerates the pair."
        PRD §2.6: "the target entity sits in a state from which the invoked action
        is defined; failures yield the action-specific conflict error" including
        `ERR_FLAG_NOT_OPEN`.

        Design: Corner/errors/dismiss_dismissed_flag_rejected
        """
        _owner, _a, _b, flag = setup_duplicate_suspect_pair()
        validate_success(api.dismiss_duplicate_flag(flag["id"], REGISTRAR))
        resp = api.dismiss_duplicate_flag(flag["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_FLAG_NOT_OPEN, expected_status=409)

    def test_transfer_on_merged_bicycle_rejected(self, api):
        """PRD §2.10: "Any business operation targeting a `MERGED` bicycle is
        rejected with `ERR_BICYCLE_MERGED` (HTTP 409);"
        PRD §3.3: "A `MERGED` bicycle rejects the operation with
        `ERR_BICYCLE_MERGED`,"

        Design: Corner/errors/transfer_on_merged_bicycle_rejected
        """
        owner, bicycle_a, bicycle_b, flag = setup_duplicate_suspect_pair()
        buyer = register_owner("o2@x.com", "O Two")
        validate_success(
            api.confirm_duplicate_flag(
                flag["id"], {"merged_into_bicycle_id": bicycle_a["id"]}, REGISTRAR
            )
        )
        resp = api.create_transfer(
            create_transfer_payload(bicycle_b["id"], "o2@x.com", sale_price_cents=10000),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BICYCLE_MERGED, expected_status=409)
