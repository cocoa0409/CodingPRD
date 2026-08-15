"""Statutory lien filing, amendment gates, freeze window, release, and OCC (PRD §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_expense_claim,
    assert_lien,
    create_case,
    create_member,
    factories,
    file_lien,
    get_case,
    get_lien,
    notify_attorney,
    set_clock,
    setup_accepted_settlement,
    setup_case_with_lien,
    setup_settlement_offered,
    validate_error,
    validate_paginated,
    validate_success,
)

SPEC = TEST_USERS["specialist_headers"]
SUP1 = TEST_USERS["supervisor_headers"]
ACCT = TEST_USERS["accountant_headers"]


class TestLienFilingPreconditions:
    def test_lien_filing_before_attorney_notification_rejected(self, api):
        """PRD §3.3: "The case must stand at `ATTORNEY_NOTIFIED`: filing while the case is still `IDENTIFIED` — attorney notification not yet recorded — is rejected with `ERR_ATTORNEY_NOT_NOTIFIED` (HTTP 409), while filing from any later or terminal status is a generic state error."

        Design: Difficulty/cross_entity_state_dependency/lien_filing_requires_attorney_notified
        """
        member = create_member(state_code="CA", medicaid_id="M-CE-1")
        case = create_case(member["id"], injury_date="2026-01-01")
        resp = api.file_lien(case["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_ATTORNEY_NOT_NOTIFIED)
        assert get_case(case["id"])["status"] == "IDENTIFIED", (
            "A rejected lien filing must not advance the case"
        )

    def test_lien_filing_rejection_creates_no_lien(self, api):
        """PRD §3.3: "The case must stand at `ATTORNEY_NOTIFIED`: filing while the case is still `IDENTIFIED` — attorney notification not yet recorded — is rejected with `ERR_ATTORNEY_NOT_NOTIFIED` (HTTP 409), while filing from any later or terminal status is a generic state error."

        Design: Difficulty/cross_entity_state_dependency/lien_filing_requires_attorney_notified
        """
        member = create_member(state_code="CA", medicaid_id="M-CE-1B")
        case = create_case(member["id"], injury_date="2026-01-01")
        validate_error(
            api.file_lien(case["id"], SPEC), ApiErrorId.ERR_ATTORNEY_NOT_NOTIFIED
        )
        data, meta = validate_paginated(
            api.list_liens(SPEC, params={"case_id": case["id"]})
        )
        assert data == [] and meta["total_count"] == 0, (
            "No lien may persist after a rejected filing"
        )

    def test_second_lien_filing_rejected(self, api):
        """PRD §3.3: "Only one active lien may exist per case; if a lien in `FILED` or `AMENDED` status already exists for the case, the filing is rejected with `ERR_LIEN_ALREADY_EXISTS` (HTTP 409)."

        Design: Corner/validations/second_lien_filing_rejected
        """
        ctx = setup_case_with_lien(claims=[("2026-01-10", 100000)])
        resp = api.file_lien(ctx["case"]["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_LIEN_ALREADY_EXISTS)
        data, meta = validate_paginated(
            api.list_liens(SPEC, params={"case_id": ctx["case"]["id"]})
        )
        assert meta["total_count"] == 1, (
            f"Exactly one lien may exist for the case, got {meta['total_count']}"
        )

    def test_accountant_cannot_file_lien(self, api):
        """PRD §2.1: "A request whose role is valid but not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/accountant_cannot_file_lien_forbidden
        """
        member = create_member(state_code="CA", medicaid_id="M-RD-1")
        case = create_case(member["id"])
        notify_attorney(case["id"])
        add_expense_claim(case["id"], "2026-01-10", 100000)
        resp = api.file_lien(case["id"], ACCT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_case(case["id"])["status"] == "ATTORNEY_NOTIFIED"


class TestLienPerfectedAmount:
    def test_lien_amount_below_cap_is_exact_basis_sum(self, api):
        """PRD §3.3: "The lien basis is the sum of `paid_amount_cents` over the case's expense claims whose `included_in_lien_basis` is true — that is, claims dated on or after the injury. The recorded `lien_amount_cents` is the lesser of that basis and the statutory lien cap of 250,000 cents (two thousand five hundred dollars)."

        Design: Corner/calculations/lien_amount_below_cap_exact_sum
        """
        ctx = setup_case_with_lien(
            claims=[("2026-01-10", 100000), ("2026-02-01", 50000)]
        )
        lien = ctx["lien"]
        assert_lien(lien)
        assert lien["lien_amount_cents"] == 150000, (
            f"Basis 150000 below the cap must not be clamped, got {lien['lien_amount_cents']}"
        )
        assert lien["statutory_cap_cents"] == 250000
        assert lien["outstanding_cents"] == 150000
        assert ctx["case"]["total_paid_claims_cents"] == 150000

    def test_pre_injury_claim_excluded_from_lien_basis(self, api):
        """PRD §3.2: "The server derives `included_in_lien_basis` for each claim: true exactly when the claim's `service_date` falls on or after the case's `injury_date`, compared as calendar dates; claims dated before the injury never feed the lien."
        PRD §3.2: "The case's `total_paid_claims_cents` is then recomputed as the sum of `paid_amount_cents` over all of the case's expense claims — included in the lien basis or not — and each addition increments the case's `version`"

        Design: Corner/calculations/expense_claim_before_injury_excluded_from_lien_basis
        """
        member = create_member(state_code="CA", medicaid_id="M-IB-1")
        case = create_case(member["id"], injury_date="2026-01-01")
        notify_attorney(case["id"])
        old_claim = add_expense_claim(case["id"], "2025-12-31", 80000)
        add_expense_claim(case["id"], "2026-02-01", 70000)
        assert old_claim["included_in_lien_basis"] is False, (
            "A claim dated before the injury must be excluded from the lien basis"
        )
        lien = get_lien(file_lien(case["id"])["id"])
        assert lien["lien_amount_cents"] == 70000, (
            f"Only post-injury claims feed the lien, got {lien['lien_amount_cents']}"
        )
        assert get_case(case["id"])["total_paid_claims_cents"] == 150000


class TestLienCapBoundary:
    def test_basis_exactly_at_cap_files_at_cap(self, api):
        """PRD §3.3: "The recorded `lien_amount_cents` is the lesser of that basis and the statutory lien cap of 250,000 cents (two thousand five hundred dollars)."

        Design: Difficulty/boundary_precision_check/lien_cap_exact_boundary
        """
        ctx = setup_case_with_lien(
            medicaid_id="M-CB-A",
            claims=[("2026-01-10", 150000), ("2026-01-11", 100000)],
        )
        lien = ctx["lien"]
        assert lien["lien_amount_cents"] == 250000, (
            f"A basis exactly at the cap files at the cap, got {lien['lien_amount_cents']}"
        )
        assert lien["outstanding_cents"] == 250000
        assert lien["status"] == "FILED"

    def test_basis_one_cent_over_cap_is_capped(self, api):
        """PRD §3.3: "The recorded `lien_amount_cents` is the lesser of that basis and the statutory lien cap of 250,000 cents (two thousand five hundred dollars)."

        Design: Difficulty/boundary_precision_check/lien_cap_exact_boundary
        """
        ctx = setup_case_with_lien(
            medicaid_id="M-CB-B", claims=[("2026-01-10", 250001)]
        )
        lien = ctx["lien"]
        assert lien["lien_amount_cents"] == 250000, (
            f"A 250001 basis must be capped to 250000, got {lien['lien_amount_cents']}"
        )
        assert lien["statutory_cap_cents"] == 250000


class TestLienAmendment:
    def test_amend_above_statutory_cap_rejected(self, api):
        """PRD §3.3: "Third, the cap: `new_amount_cents` must not exceed the lien's `statutory_cap_cents` snapshot, or the amendment is rejected with `ERR_LIEN_EXCEEDS_CAP` (HTTP 409)."

        Design: Corner/validations/lien_amend_over_cap_returns_fiscal_error
        """
        ctx = setup_case_with_lien(claims=[("2026-01-10", 100000)])
        lien = ctx["lien"]
        resp = api.amend_lien(
            lien["id"],
            factories.amend_lien_payload(
                lien["version"], new_amount_cents=250001
            ),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_LIEN_EXCEEDS_CAP)
        after = get_lien(lien["id"])
        assert after["lien_amount_cents"] == 100000
        assert after["status"] == "FILED"

    def test_amend_with_stale_version_rejected(self, api):
        """PRD §2.7: "`POST /recovery/liens/{lienId}/amend` requires the input field `expected_lien_version`, carrying the client's last observed `version` of the lien. If the lien's current `version` has advanced since the client last read it — for example, because another writer has just amended the same lien, and each amendment legitimately supersedes the prior amount — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a lien state it has not observed."

        Design: Corner/cross_cutting_complexity_layers/lien_amend_stale_version_returns_412
        """
        ctx = setup_case_with_lien(claims=[("2026-01-10", 100000)])
        lien = ctx["lien"]
        observed_version = lien["version"]
        amended = validate_success(
            api.amend_lien(
                lien["id"],
                factories.amend_lien_payload(
                    observed_version, new_amount_cents=90000
                ),
                SPEC,
            ),
            200,
        )
        assert amended["lien_amount_cents"] == 90000
        resp = api.amend_lien(
            lien["id"],
            factories.amend_lien_payload(observed_version, new_amount_cents=80000),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_lien(lien["id"])
        assert after["lien_amount_cents"] == 90000, (
            "The stale replay must not overwrite the newer amendment"
        )
        assert after["amended_count"] == 1


class TestNegotiationFreeze:
    def test_amend_exactly_fourteen_days_after_offer_still_frozen(self, api):
        """PRD §3.3: "First, the negotiation freeze: for every settlement on the case in `OFFERED` or `COUNTERED` status, the current logical timestamp must be strictly later than fourteen days after that settlement's `updated_at`; the interval is closed, so a lien whose open negotiation was updated exactly fourteen days ago remains frozen, and a blocked amendment is rejected with `ERR_NEGOTIATION_FREEZE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/lien_amend_negotiation_freeze_closed_interval
        """
        ctx = setup_settlement_offered(
            claims=[("2026-01-10", 200000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000,
        )
        lien = ctx["lien"]
        # Settlement was tabled at the default clock 2026-08-01T00:00:00Z;
        # exactly fourteen days later the interval is still closed.
        set_clock("2026-08-15T00:00:00Z")
        resp = api.amend_lien(
            lien["id"],
            factories.amend_lien_payload(lien["version"], new_amount_cents=180000),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_FREEZE)
        after = get_lien(lien["id"])
        assert after["lien_amount_cents"] == 200000
        assert after["status"] == "FILED"

    def test_amend_fifteen_days_after_offer_succeeds(self, api):
        """PRD §3.3: "the current logical timestamp must be strictly later than fourteen days after that settlement's `updated_at`"
        PRD §3.3: "A successful amendment replaces `lien_amount_cents` with `new_amount_cents`, recomputes `outstanding_cents`, increments `amended_count` by one, and increments the lien's `version` by one."

        Design: Difficulty/resource_temporal_overlap/lien_amend_negotiation_freeze_closed_interval
        """
        ctx = setup_settlement_offered(
            claims=[("2026-01-10", 200000)],
            gross_amount_cents=500000, attorney_fee_pct=0.20,
            litigation_costs_cents=50000,
        )
        lien = ctx["lien"]
        set_clock("2026-08-16T00:00:00Z")
        amended = validate_success(
            api.amend_lien(
                lien["id"],
                factories.amend_lien_payload(lien["version"], new_amount_cents=180000),
                SPEC,
            ),
            200,
        )
        assert amended["status"] == "AMENDED"
        assert amended["lien_amount_cents"] == 180000
        assert amended["outstanding_cents"] == 180000
        assert amended["amended_count"] == 1


class TestLienStateBeatsFiscal:
    def test_amend_on_satisfied_lien_returns_not_amendable(self, api):
        """PRD §3.3: "Amendment is defined from `FILED` to `AMENDED` and again from `AMENDED` to `AMENDED`; attempting it on a lien in `SATISFIED`, `RELEASED`, or `EXPIRED` status is rejected with `ERR_LIEN_NOT_AMENDABLE` (HTTP 409)."
        PRD §2.8: "Validation failures are reported against a fixed evaluation order, so the error a client receives is always the earliest applicable check rather than an arbitrary one."

        Design: Difficulty/priority_pair_validation_conflict/lien_amend_state_beats_fiscal
        """
        # Fully resolved case: the lien is SATISFIED; the amend amount also
        # exceeds the cap, and the state check (earlier) must win.
        ctx = setup_accepted_settlement(claims=[("2026-01-10", 200000)])
        posting = _post_full_recovery(api, ctx)
        lien = get_lien(ctx["lien"]["id"])
        assert lien["status"] == "SATISFIED"
        resp = api.amend_lien(
            lien["id"],
            factories.amend_lien_payload(lien["version"], new_amount_cents=300000),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_LIEN_NOT_AMENDABLE)

    def test_rejected_amend_leaves_satisfied_lien_unchanged(self, api):
        """PRD §3.3: "A successful amendment replaces `lien_amount_cents` with `new_amount_cents`, recomputes `outstanding_cents`, increments `amended_count` by one, and increments the lien's `version` by one."

        Design: Difficulty/priority_pair_validation_conflict/lien_amend_state_beats_fiscal
        """
        ctx = setup_accepted_settlement(claims=[("2026-01-10", 200000)])
        _post_full_recovery(api, ctx)
        lien = get_lien(ctx["lien"]["id"])
        validate_error(
            api.amend_lien(
                lien["id"],
                factories.amend_lien_payload(lien["version"], new_amount_cents=300000),
                SPEC,
            ),
            ApiErrorId.ERR_LIEN_NOT_AMENDABLE,
        )
        after = get_lien(lien["id"])
        assert after["lien_amount_cents"] == 200000, (
            "A rejected amendment must not replace the lien amount"
        )
        assert after["status"] == "SATISFIED"


class TestLienRelease:
    def test_release_reverts_lien_filed_case_to_attorney_notified(self, api):
        """PRD §3.3: "Release feeds back into the case: when the case stands at `LIEN_FILED`, it reverts to `ATTORNEY_NOTIFIED`; when the case stands at `SETTLEMENT_PENDING`, its status is left unchanged."

        Design: Corner/state_machines/lien_release_reverts_case_to_attorney_notified
        """
        ctx = setup_case_with_lien(claims=[("2026-01-10", 150000)])
        released = validate_success(api.release_lien(ctx["lien"]["id"], SUP1), 200)
        assert released["status"] == "RELEASED"
        assert get_case(ctx["case"]["id"])["status"] == "ATTORNEY_NOTIFIED"


def _post_full_recovery(api, ctx):
    """Post a posting equal to the accepted settlement's recovery (test-local helper)."""
    posting = validate_success(
        api.create_posting(
            ctx["settlement"]["id"],
            factories.posting_payload(
                gross_recovery_cents=ctx["settlement"]["state_recovery_cents"]
            ),
            ACCT,
        ),
        201,
    )
    return validate_success(api.post_posting(posting["id"], ACCT), 200)
