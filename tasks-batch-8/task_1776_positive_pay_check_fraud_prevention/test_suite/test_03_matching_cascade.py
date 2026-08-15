"""Presented-item ingestion: the ordered matching cascade, payee scoring,
amount tolerance boundary, and ingestion idempotency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_enrollment,
    get_check_by_number,
    get_enrollment,
    get_exception,
    make_check_row,
    present_item,
    setup_paid_item,
    upload_checks,
    validate_error,
    validate_paginated,
    validate_success,
)

BANK_MGR = TEST_USERS["bank_treasury_manager_headers"]
BANK_OPS = TEST_USERS["bank_ops_headers"]


class TestMatcherVerdicts:
    def test_no_issue_record_holds_item_with_null_check_link(self, api):
        """PRD §3.4: "The system looks for an `IssuedCheck` on the same account
        with the same `check_number`. If there is none, the verdict is
        `NO_ISSUE_RECORD`."
        PRD §3.5: "its `issued_check_id`, which stays null for the
        `NO_ISSUE_RECORD` and `REVERSE_REVIEW` reasons".

        Design: Corner/calculations/matcher_no_issue_record
        """
        b = create_active_enrollment("NoRecCo", "POSITIVE_PAY", "PAY",
                                     account_number="820001")
        item = present_item(b["account"]["id"], "4242", 100, "X",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["status"] == "EXCEPTION_HELD"
        assert item["match_result"] == "NO_ISSUE_RECORD"
        exc = get_exception(item["exception_id"])
        assert exc["reason"] == "NO_ISSUE_RECORD"
        assert exc["issued_check_id"] is None

    def test_voided_check_yields_voided_item(self, api):
        """PRD §3.4: "If the matched check is `VOIDED`, the verdict is
        `VOIDED_ITEM`."

        Design: Corner/calculations/matcher_voided_item
        """
        b = create_active_enrollment("VItCo", "POSITIVE_PAY", "PAY",
                                     account_number="820002")
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-VIT",
                      [make_check_row("301", 1000, "V PAYEE")],
                      b["headers"]["ADMIN"])
        check = get_check_by_number(b["account"]["id"], "301")
        validate_success(api.void_issued_check(check["id"],
                                               b["headers"]["ADMIN"]))
        item = present_item(b["account"]["id"], "301", 1000, "V PAYEE",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_result"] == "VOIDED_ITEM", (
            "exact amount and payee do not rescue a voided check")

    def test_representment_of_consumed_check_is_duplicate(self, api):
        """PRD §2.9: "A business-level re-presentment — the same account and
        check number presented again without reusing a key — is not an
        idempotency error at all; it flows through matching and ordinarily lands
        as `DUPLICATE_PRESENTMENT` (see §3.4)."
        PRD §3.4: "If the matched check is `CONSUMED`, the verdict is
        `DUPLICATE_PRESENTMENT`."

        Design: Corner/calculations/matcher_duplicate_presentment
        """
        b = create_active_enrollment("DupItCo", "POSITIVE_PAY", "PAY",
                                     account_number="820003")
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-DUP",
                      [make_check_row("401", 2000, "D CO")],
                      b["headers"]["ADMIN"])
        first = present_item(b["account"]["id"], "401", 2000, "D CO",
                             presented_at="2026-08-03T10:00:00Z")
        assert first["status"] == "PAID"
        second = present_item(b["account"]["id"], "401", 2000, "D CO",
                              channel="CLEARING",
                              presented_at="2026-08-04T10:00:00Z")
        assert second["status"] == "EXCEPTION_HELD"
        assert second["match_result"] == "DUPLICATE_PRESENTMENT"

    def test_check_status_rule_fires_before_amount_rule(self, api):
        """PRD §3.4: "The cascade is an ordered rule chain; the first rule that
        fires decides `match_result` and stops evaluation" — the voided rule
        (rule 4) precedes the amount rule (rule 7).

        Design: Corner/calculations/matcher_status_priority_over_amount
        """
        b = create_active_enrollment("PriCo", "POSITIVE_PAY", "PAY",
                                     account_number="820004")
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-PRI",
                      [make_check_row("501", 1000, "P CO")],
                      b["headers"]["ADMIN"])
        check = get_check_by_number(b["account"]["id"], "501")
        validate_success(api.void_issued_check(check["id"],
                                               b["headers"]["ADMIN"]))
        item = present_item(b["account"]["id"], "501", 9999, "WRONG NAME",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_result"] == "VOIDED_ITEM"

    def test_amount_rule_fires_before_payee_rule(self, api):
        """PRD §3.4: "The cascade is an ordered rule chain; the first rule that
        fires decides `match_result` and stops evaluation" — the amount rule
        (rule 7) precedes payee verification (rule 8), and "If the tier is
        `PAYEE_POSITIVE_PAY`, the payee-match score is computed (below) and
        recorded on the item as `match_score`" only when that rule runs.

        Design: Corner/calculations/matcher_amount_priority_over_payee
        """
        b = create_active_enrollment("PriPayCo", "PAYEE_POSITIVE_PAY", "PAY",
                                     account_number="820005")
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-PP",
                      [make_check_row("601", 1000, "RIGHT PAYEE")],
                      b["headers"]["ADMIN"])
        item = present_item(b["account"]["id"], "601", 2000, "WRONG PAYEE",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_result"] == "AMOUNT_MISMATCH"
        assert item.get("match_score") is None, (
            "payee verification never runs once the amount rule fires")

    def test_reverse_tier_holds_every_item(self, api):
        """PRD §3.4: "If the enrollment's `tier` is `REVERSE_POSITIVE_PAY`, the
        verdict is `REVERSE_REVIEW` — reverse-tier customers review everything,
        so no matching is attempted."

        Design: Corner/calculations/reverse_tier_every_item_reviewed
        """
        b = create_active_enrollment("RevAllCo", "REVERSE_POSITIVE_PAY", "PAY",
                                     account_number="820008")
        item = present_item(b["account"]["id"], "1", 100, "ANY",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["status"] == "EXCEPTION_HELD"
        assert item["match_result"] == "REVERSE_REVIEW"


class TestAmountToleranceBoundary:
    def _setup(self):
        b = create_active_enrollment("TolCo", "PAYEE_POSITIVE_PAY", "RETURN",
                                     account_number="990001",
                                     amount_tolerance_cents=100)
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-TOL",
                      [make_check_row("601", 50000, "OMEGA CO"),
                       make_check_row("602", 50000, "OMEGA CO")],
                      b["headers"]["ADMIN"])
        return b

    def test_difference_equal_to_tolerance_matches(self, api):
        """PRD §3.4: "If the absolute difference between the item's
        `amount_cents` and the check's `amount_cents` exceeds the enrollment's
        `amount_tolerance_cents`, the verdict is `AMOUNT_MISMATCH`. A difference
        exactly equal to the tolerance still counts as an amount match."

        Design: Difficulty/boundary_precision_check/amount_tolerance_boundary_cent
        """
        b = self._setup()
        item = present_item(b["account"]["id"], "601", 50100, "OMEGA CO",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["status"] == "PAID"
        assert item["match_result"] == "CLEAN"

    def test_difference_one_cent_over_tolerance_mismatches(self, api):
        """PRD §3.4: "If the absolute difference between the item's
        `amount_cents` and the check's `amount_cents` exceeds the enrollment's
        `amount_tolerance_cents`, the verdict is `AMOUNT_MISMATCH`."

        Design: Difficulty/boundary_precision_check/amount_tolerance_boundary_cent
        """
        b = self._setup()
        item = present_item(b["account"]["id"], "602", 50101, "OMEGA CO",
                            presented_at="2026-08-03T10:01:00Z")
        assert item["status"] == "EXCEPTION_HELD"
        assert item["match_result"] == "AMOUNT_MISMATCH"


class TestPayeeMatchScore:
    def _setup_payee(self, payee_name, check_number, business_name,
                     account_number):
        b = create_active_enrollment(business_name, "PAYEE_POSITIVE_PAY",
                                     "RETURN", account_number=account_number)
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-1",
                      [make_check_row(check_number, 5000, payee_name)],
                      b["headers"]["ADMIN"])
        return b

    def test_per_token_floor_gives_85(self, api):
        """PRD §3.4: "Each issued token's contribution is its own length
        multiplied by its similarity and divided by the total character length
        of all issued tokens, rounded down to a whole number — and this
        per-token rounding down is applied before summing."
        For 'ACME INDUSTRIES' vs 'ACM INDUSTRIES': issued tokens are ACME (4)
        and INDUSTRIES (10), total length 14. ACME earns 50 via the prefix
        rule (presented ACM is a prefix, shorter length 3); INDUSTRIES earns
        100 exactly. floor(4*50/14) + floor(10*100/14) = 14 + 71 = 85.

        Design: Difficulty/combinatorial_formula/payee_score_per_token_floor_rounding_order
        """
        b = self._setup_payee("ACME INDUSTRIES", "201", "RoundCo", "950001")
        item = present_item(b["account"]["id"], "201", 5000,
                            "ACM INDUSTRIES", channel="REMOTE_DEPOSIT",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_score"] == 85, (
            "per-token floor before summing; the sum is not re-rounded")

    def test_score_85_passes_at_default_threshold_85(self, api):
        """PRD §3.4: "a score below the enrollment's `payee_score_threshold`
        yields `PAYEE_MISMATCH`" — the PRD formula scores
        'ACME INDUSTRIES' vs 'ACM INDUSTRIES' at 85, which is NOT below the
        default threshold of 85, so the item pays clean.
        "If nothing above fired, the verdict is `CLEAN`."

        Design: Difficulty/combinatorial_formula/payee_score_per_token_floor_rounding_order
        """
        b = self._setup_payee("ACME INDUSTRIES", "201", "RoundCo2", "950002")
        item = present_item(b["account"]["id"], "201", 5000,
                            "ACM INDUSTRIES", channel="REMOTE_DEPOSIT",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_score"] == 85
        assert item["match_result"] == "CLEAN"
        assert item["status"] == "PAID"

    def test_score_exactly_at_threshold_passes(self, api):
        """PRD §3.4: "a score below the enrollment's `payee_score_threshold`
        yields `PAYEE_MISMATCH`" — so a score equal to the threshold passes.
        'ACM WIDGETS' vs 'ACME WIDGETS': floor(3*50/10) + floor(7*100/10) =
        15 + 70 = 85.

        Design: Corner/calculations/payee_exact_threshold_passes
        """
        b = self._setup_payee("ACM WIDGETS", "701", "ThrCo", "820006")
        item = present_item(b["account"]["id"], "701", 5000, "ACME WIDGETS",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_score"] == 85
        assert item["status"] == "PAID"

    def test_no_token_overlap_scores_zero(self, api):
        """PRD §3.4: "Otherwise each issued token earns a similarity: 100 when
        some presented token equals it exactly; otherwise 50 when some presented
        token is a prefix of it or it is a prefix of some presented token,
        provided the shorter of the two tokens has length at least 3; otherwise
        0."

        Design: Corner/calculations/payee_full_mismatch_scores_zero
        """
        b = self._setup_payee("ACME INDUSTRIES", "801", "ZeroCo", "820007")
        item = present_item(b["account"]["id"], "801", 5000, "XYZ CORP",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_score"] == 0
        assert item["match_result"] == "PAYEE_MISMATCH"


class TestIngestionIdempotency:
    def test_identical_replay_returns_original_item(self, api):
        """PRD §2.9: "Presented-item ingestion accepts an optional
        `idempotency_key`: a replay of the same key with an identical payload
        returns the original item".

        Design: Corner/complexity_layers/presented_item_idempotent_replay
        """
        b = create_active_enrollment("IdemCo", "REVERSE_POSITIVE_PAY", "PAY",
                                     account_number="860002")
        first = present_item(b["account"]["id"], "1", 100, "A",
                             presented_at="2026-08-03T10:00:00Z",
                             idempotency_key="K-1")
        second = present_item(b["account"]["id"], "1", 100, "A",
                              presented_at="2026-08-03T10:00:00Z",
                              idempotency_key="K-1")
        assert second["id"] == first["id"]
        enr = get_enrollment(b["enrollment"]["id"])
        assert enr["open_exception_count"] == 1, (
            "the replay must not create a duplicate exception")

    def test_same_key_different_payload_conflicts(self, api):
        """PRD §2.9: "the same key with a different payload is rejected with
        `ERR_IDEMPOTENCY_CONFLICT`."

        Design: Corner/complexity_layers/presented_item_idempotency_conflict
        """
        b = create_active_enrollment("Idem2Co", "REVERSE_POSITIVE_PAY", "PAY",
                                     account_number="860003")
        present_item(b["account"]["id"], "1", 100, "A",
                     presented_at="2026-08-03T10:00:00Z", idempotency_key="K-9")
        resp = api.ingest_presented_item(
            {"account_id": b["account"]["id"], "check_number": "1",
             "amount_cents": 101, "payee_name_raw": "A", "channel": "TELLER",
             "presented_at": "2026-08-03T10:00:00Z", "idempotency_key": "K-9"},
            BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)


class TestIngestionAccountGate:
    def test_ingestion_against_closed_account_rejected(self, api):
        """PRD §3.3: "the target account must belong to the named enrollment and
        be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE` — ingesting against a `CLOSED`
        account fails the same way)".

        Design: Corner/endpoints/presented_items_on_closed_account_rejected
        """
        b = create_active_enrollment("IngCo", "POSITIVE_PAY", "PAY",
                                     account_number="840008")
        validate_success(api.close_account(b["account"]["id"], BANK_MGR))
        resp = api.ingest_presented_item(
            {"account_id": b["account"]["id"], "check_number": "1",
             "amount_cents": 100, "payee_name_raw": "A", "channel": "TELLER",
             "presented_at": "2026-08-03T10:00:00Z"}, BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
