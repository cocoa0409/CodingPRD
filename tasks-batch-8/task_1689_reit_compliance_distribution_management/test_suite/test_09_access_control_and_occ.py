"""Role-based access control, OCC stale-version gates, and the validation
priority pairs of PRD §2.9."""
from test_helpers import (
    NO_ROLE_HEADERS,
    TEST_USERS,
    ApiErrorId,
    approve_dividend,
    create_approved_dividend,
    create_dividend,
    create_dividend_declaration_payload,
    create_ep_adjustment_payload,
    create_posted_ep_adjustment,
    create_posted_requirement,
    create_quarter,
    create_reit,
    current_reit_version,
    finalize_failing_snapshot,
    validate_error,
    validate_success,
)


# ─── RBAC (PRD §2.1, §4) ──────────────────────────────

def test_officer_cannot_approve_dividend(api, compliance_officer_headers):
    """PRD §2.1: "A request whose role is recognized but not permitted for
    the target endpoint is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: POST /reit-compliance/dividend-declarations/{id}/approve is listed
    with authorized role "BoardDirector".

    Design: Corner/roles/officer_cannot_approve_dividend
    """
    reit = create_reit(legal_name="RB1 REIT")
    dividend = create_dividend(reit["id"], taxable_year=2026,
                               amount_cents=10_000)
    resp = api.approve_dividend_declaration(dividend["id"],
                                            compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_director_cannot_post_ep_adjustment(api, board_director_headers):
    """PRD §2.1: "A request whose role is recognized but not permitted for
    the target endpoint is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: POST /reit-compliance/ep-adjustments/{id}/post is listed with
    authorized role "TaxDirector".

    Design: Corner/roles/director_cannot_post_ep_adjustment
    """
    reit = create_reit(legal_name="RB2 REIT")
    quarter = create_quarter(reit["id"])
    created = validate_success(
        api.create_ep_adjustment(
            create_ep_adjustment_payload(
                reit["id"], quarter["id"],
                expected_reit_version=current_reit_version(reit["id"]),
                kind="TAXABLE_INCOME", amount_cents=5000,
                effective_date="2026-01-10",
            ),
            TEST_USERS["tax_director_headers"],
        ),
        201,
    )
    resp = api.post_ep_adjustment(created["id"], board_director_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an
    `X-User-Role` outside the declared set, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/roles/missing_role_header_unauthenticated
    """
    resp = api.list_reits(NO_ROLE_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_officer_cannot_close_requirement(api, compliance_officer_headers):
    """PRD §2.1: "A request whose role is recognized but not permitted for
    the target endpoint is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: POST /reit-compliance/distribution-requirements/{id}/close is
    listed with authorized role "TaxDirector".

    Design: Corner/roles/officer_cannot_close_requirement
    """
    reit = create_reit(legal_name="RB3 REIT")
    req = create_posted_requirement(reit["id"], taxable_year=2026,
                                    taxable_income_cents=100_000,
                                    net_capital_gain_cents=0)
    resp = api.close_distribution_requirement(req["id"],
                                              compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ─── OCC stale-version gates (PRD §2.6) ───────────────

def test_stale_version_on_dividend_create_rejected(
        api, compliance_officer_headers, tax_director_headers):
    """PRD §2.6: "If the supplied value does not equal the REIT's current
    `version` at write time — because, for instance, another writer has since
    posted an adjustment or locked a report and legitimately advanced the
    version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "A fresh adjustment lands in `DRAFT`, and creating one
    increments the REIT's `version` by one."

    Design: Corner/validations/stale_version_on_dividend_create_rejected
    """
    reit = create_reit(legal_name="OCC REIT")
    quarter = create_quarter(reit["id"])
    stale_version = reit["version"]
    # The adjustment create legitimately advances the REIT version.
    create_ep = create_ep_adjustment_payload(
        reit["id"], quarter["id"], expected_reit_version=stale_version,
        kind="TAXABLE_INCOME", amount_cents=1000, effective_date="2026-01-10",
    )
    ok = api.create_ep_adjustment(create_ep, tax_director_headers)
    assert ok.status_code == 201, ok.text

    payload = create_dividend_declaration_payload(
        reit["id"], expected_reit_version=stale_version, taxable_year=2026,
        amount_cents=5000, declaration_date="2026-03-01",
        record_date="2026-03-10", payable_date="2026-03-20",
    )
    resp = api.create_dividend_declaration(payload, compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_stale_version_on_ep_adjustment_create_rejected(
        api, tax_director_headers):
    """PRD §2.6: "Two create operations mutate the REIT's fiscal baseline in
    ways that make a stale client view dangerous: drafting an E&P adjustment
    and drafting a dividend declaration. Both therefore require the caller to
    supply `expected_reit_version`, a non-optional input carrying the
    `version` of the parent `Reit` as the client last observed it."
    PRD §3.6: "On create the declaration lands in `PENDING_APPROVAL`, and the
    REIT's `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_ep_adjustment_stale_version_direct
    """
    reit = create_reit(legal_name="OC1 REIT")
    quarter = create_quarter(reit["id"])
    stale_version = reit["version"]
    # The dividend create legitimately advances the REIT version.
    create_dividend(reit["id"], taxable_year=2026, amount_cents=1000)

    payload = create_ep_adjustment_payload(
        reit["id"], quarter["id"], expected_reit_version=stale_version,
        kind="TAXABLE_INCOME", amount_cents=100, effective_date="2026-01-10",
    )
    resp = api.create_ep_adjustment(payload, tax_director_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ─── Validation priority pairs (PRD §2.9) ─────────────

_PRIORITY_ORDER_QUOTE = (
    "Authentication (`ERR_UNAUTHENTICATED`) comes first, then role "
    "authorization (`ERR_UNAUTHORIZED`), then path-id existence "
    "(`ERR_NOT_FOUND`), then body foreign-key existence (`ERR_NOT_FOUND`), "
    "then payload shape and enum/range checks (`ERR_VALIDATION`), then "
    "uniqueness (`ERR_DUPLICATE`), then state-machine legality "
    "(`ERR_INVALID_STATE`), then quarter-or-snapshot openness "
    "(`ERR_QUARTER_LOCKED`), then cross-REIT referential consistency "
    "(`ERR_CROSS_REIT_REFERENCE`), then date sanity "
    "(`ERR_INVALID_DATE_RANGE`), then quarter interval overlap "
    "(`ERR_QUARTER_OVERLAP`), then the suspended-REIT posture gate "
    "(`ERR_REIT_SUSPENDED`), then the 5/50 block (`ERR_FIVE_FIFTY_BLOCKED`), "
    "then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then the "
    "posted-requirement precondition (`ERR_REQUIREMENT_NOT_POSTED`), then "
    "OCC staleness (`ERR_STALE_VERSION`), and finally the open-declarations "
    "precondition on year close (`ERR_DECLARATIONS_OPEN`)."
)


class TestValidationVsStaleVersionPriority:
    def _setup_advanced_reit(self):
        """REIT whose version has advanced past its creation version."""
        reit, quarter = None, None
        reit = create_reit(legal_name="PR1 REIT")
        quarter = create_quarter(reit["id"])
        create_posted_ep_adjustment(reit["id"], quarter["id"],
                                    kind="TAXABLE_INCOME", amount_cents=1000,
                                    effective_date="2026-01-10")
        return reit, quarter

    def test_bad_enum_beats_stale_version(self, api, tax_director_headers):
        """PRD §2.9: "{priority_order}" and "A request that fails more than
        one rule surfaces the one with the earliest position in this list."
        PRD §3.7: "The `kind` must be one of `TAXABLE_INCOME`,
        `DISALLOWED_DEDUCTION`, or `FEDERAL_TAX`".

        Design: Difficulty/priority_pair_validation_conflict/create_adjustment_bad_enum_and_stale_version
        """.format(priority_order=_PRIORITY_ORDER_QUOTE)
        reit, quarter = self._setup_advanced_reit()
        assert current_reit_version(reit["id"]) != reit["version"]
        payload = create_ep_adjustment_payload(
            reit["id"], quarter["id"],
            expected_reit_version=reit["version"],  # stale
            kind="NOT_A_KIND", amount_cents=500, effective_date="2026-01-20",
        )
        resp = api.create_ep_adjustment(payload, tax_director_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_negative_amount_beats_stale_version(self, api,
                                                 tax_director_headers):
        """PRD §2.9: "{priority_order}" and "A request that fails more than
        one rule surfaces the one with the earliest position in this list."
        PRD §3.7: "the sign convention is that all three carry a non-negative
        `amount_cents`".

        Design: Difficulty/priority_pair_validation_conflict/create_adjustment_bad_enum_and_stale_version
        """.format(priority_order=_PRIORITY_ORDER_QUOTE)
        reit, quarter = self._setup_advanced_reit()
        assert current_reit_version(reit["id"]) != reit["version"]
        payload = create_ep_adjustment_payload(
            reit["id"], quarter["id"],
            expected_reit_version=reit["version"],  # stale
            kind="TAXABLE_INCOME", amount_cents=-500,
            effective_date="2026-01-20",
        )
        resp = api.create_ep_adjustment(payload, tax_director_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestStateVsFiveFiftyPriority:
    def _setup_blocked_reit_with_dividend(self):
        reit = create_reit(legal_name="PR2 REIT")
        create_posted_requirement(reit["id"], taxable_year=2026,
                                  taxable_income_cents=500_000,
                                  net_capital_gain_cents=0)
        dividend = create_dividend(reit["id"], taxable_year=2026,
                                   amount_cents=10_000)
        finalize_failing_snapshot(reit["id"])
        return reit, dividend

    def test_declare_pending_approval_while_blocked_returns_invalid_state(
            self, api, compliance_officer_headers):
        """PRD §2.9: "{priority_order}" and "A request that fails more than
        one rule surfaces the one with the earliest position in this list."
        PRD §3.6: "A `ComplianceOfficer` declares a dividend that is in
        `APPROVED`".

        Design: Difficulty/priority_pair_validation_conflict/declare_invalid_state_and_five_fifty_blocked
        """.format(priority_order=_PRIORITY_ORDER_QUOTE)
        _reit, dividend = self._setup_blocked_reit_with_dividend()
        # Dividend is still PENDING_APPROVAL while five_fifty_blocked is true.
        resp = api.declare_dividend_declaration(dividend["id"],
                                                compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_approved_while_blocked_returns_invalid_state(
            self, api, board_director_headers):
        """PRD §2.9: "{priority_order}" and "A request that fails more than
        one rule surfaces the one with the earliest position in this list."
        PRD §3.6: "Approval requires the declaration to be in
        `PENDING_APPROVAL`, the REIT to be `ACTIVE`, and `five_fifty_blocked`
        to be false."

        Design: Difficulty/priority_pair_validation_conflict/declare_invalid_state_and_five_fifty_blocked
        """.format(priority_order=_PRIORITY_ORDER_QUOTE)
        reit = create_reit(legal_name="PR2 REIT B")
        create_posted_requirement(reit["id"], taxable_year=2026,
                                  taxable_income_cents=500_000,
                                  net_capital_gain_cents=0)
        dividend = create_approved_dividend(reit["id"], taxable_year=2026,
                                            amount_cents=10_000)
        finalize_failing_snapshot(reit["id"])

        resp = api.approve_dividend_declaration(dividend["id"],
                                                board_director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
