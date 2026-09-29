"""
Endpoint-surface behaviour: the create / list / read triple that carries no
in-place edit, the computed rollforward read that persists nothing, the body
foreign keys of point-lot issuance and their resolution order, and the
conditional dispute action that only the owning partner may take.
"""

import pytest

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CLOCK_EPOCH,
    LOT_OUTSTANDING,
    PERIOD_AUG_END,
    PERIOD_OPEN,
    PERIOD_SOFT_CLOSED,
    STATE_DE,
    STATE_TX,
    STATEMENT_DISPUTED,
    STATEMENT_ISSUED,
    UNKNOWN_ID,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    make_partner_operator_headers,
)
from test_helpers.types import LIABILITY_ROLLFORWARD_FIELDS

# A second state of residence, so one programme can carry a rule that forbids
# expiry alongside two that permit it.
STATE_CA = "CA"

# The reference issuance used throughout: 1000 BASE points at 1200 millicents
# each, reserved at the seeded rate of 2500 basis points.
BASE_POINTS = 1000
GROSS_SSP_CENTS = 1200
BREAKAGE_RESERVE_CENTS = 300
DEFERRED_REVENUE_CENTS = 900

# The single cohort's observed redemption rate, and the liability it requires
# against the reference issuance.
ESTIMATED_REDEMPTION_RATE_BP = 8200
REQUIRED_LIABILITY_CENTS = 984
CATCH_UP_ADJUSTMENT_CENTS = 84

# The partner leg: 2000 points billed at 900 millicents per point.
PARTNER_BASE_POINTS = 2000
PARTNER_MIN_INVOICE_CENTS = 1000
PARTNER_NET_DUE_CENTS = 1800
DISPUTE_REASON = "Issued point volume does not match our feed."


def _ledger_ready(
    api,
    program_overrides=None,
    cohort_overrides=None,
    member_overrides=None,
    period_overrides=None,
    clock=CLOCK_EPOCH,
):
    """
    The state every ledger write needs: the clock placed, an ACTIVE programme
    carrying one state expiry rule and one cohort, one member and one OPEN
    period.
    """
    fixtures.set_clock(api, clock)
    program = fixtures.new_program(api, **(program_overrides or {}))
    rule = fixtures.new_state_expiry_rule(api, program["id"])
    cohort = fixtures.new_cohort(api, program["id"], **(cohort_overrides or {}))
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(api, program["id"], cohort["id"], **(member_overrides or {}))
    period = fixtures.new_period(api, program["id"], **(period_overrides or {}))
    return {
        "program": program,
        "rule": rule,
        "cohort": cohort,
        "member": member,
        "period": period,
    }


def _program_with_rules(api, rule_overrides):
    """A DRAFT programme carrying one state expiry rule per supplied override set."""
    program = fixtures.new_program(api)
    rules = [
        assertions.assert_created(
            api.create_state_expiry_rule(
                factories.state_expiry_rule_payload(program["id"], **overrides),
                PROGRAM_ADMIN_HEADERS,
            )
        )
        for overrides in rule_overrides
    ]
    return program, rules


def test_state_expiry_rule_create_list_and_read_compose(api):
    """
    Creating a state expiry rule returns a freshly minted resource at version 1,
    the collection read composes its programme and expiry-permission filters with
    the pagination window and never leaks another programme's rules, and the
    detail read echoes the escheatment policy exactly as written.

    "Expiry policy is expressed per US state as a **StateExpiryRule** attached to a programme through a `program_id` and identified by a `state_code` of exactly two uppercase letters; the combination of programme and state code must be unique, and a repeat is rejected with `ERR_DUPLICATE_CODE`."
    "And it declares `escheat_rate_bp`, the escheatable fraction of the expired lot's gross standalone selling price, defaulting to 10000 basis points — the whole amount — and accepted from 0 through 10000 inclusive."
    "State expiry rules may be filtered by `program_id`, `state_code` and `expiry_permitted`."
    "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."
    "Creation endpoints return HTTP 201 with the created resource in `data`."

    Design: Corner/endpoints/endpoint_standard_crud_state_expiry_rule_create_list_get
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program_a, (rule_tx, rule_ca, rule_de) = _program_with_rules(
        api,
        [
            {
                "state_code": STATE_TX,
                "expiry_permitted": True,
                "escheatment_required": False,
                "escheat_rate_bp": 0,
            },
            {
                "state_code": STATE_CA,
                "expiry_permitted": False,
                "min_dormancy_days": 1095,
                "escheatment_required": False,
                "escheat_rate_bp": 0,
            },
            {
                "state_code": STATE_DE,
                "expiry_permitted": True,
                "escheatment_required": True,
                "escheat_rate_bp": 6000,
            },
        ],
    )
    program_b, (rule_b,) = _program_with_rules(
        api,
        [{"state_code": STATE_TX, "escheatment_required": False, "escheat_rate_bp": 0}],
    )

    window = assertions.assert_page(
        api.list_state_expiry_rules(
            ACCOUNTANT_HEADERS, program_id=program_a["id"], limit=2, offset=0
        ),
        total_count=3,
        has_more=True,
        limit=2,
        offset=0,
    )
    assert len(window) == 2, f"Expected a two-row page, got {len(window)} rows"
    assert {row["program_id"] for row in window} == {program_a["id"]}

    permitted = assertions.assert_page(
        api.list_state_expiry_rules(
            CONTROLLER_HEADERS, program_id=program_a["id"], expiry_permitted="true"
        ),
        total_count=2,
    )
    assert {row["id"] for row in permitted} == {rule_tx["id"], rule_de["id"]}, (
        "The expiry_permitted filter must exclude the rule that forbids expiry"
    )

    detail_response = api.get_state_expiry_rule(rule_de["id"], CONTROLLER_HEADERS)
    detail = assertions.assert_envelope_object(detail_response)
    assertions.assert_fields(
        detail,
        program_id=program_a["id"],
        state_code=STATE_DE,
        expiry_permitted=True,
        escheatment_required=True,
        escheat_rate_bp=6000,
    )
    meta = detail_response.json()["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert "api_request_timestamp" in meta

    assertions.assert_page(
        api.list_state_expiry_rules(ACCOUNTANT_HEADERS, program_id=program_b["id"]),
        expected_ids=[rule_b["id"]],
        total_count=1,
    )


def test_liability_rollforward_previews_then_matches_the_close(api):
    """
    The rollforward read re-runs the whole close against current data and writes
    nothing: the period stays OPEN at the version it already held, and the soft
    close that follows persists precisely the twelve figures the preview
    reported, which the read then repeats unchanged.

    "A `LoyaltyAccountant` or `Controller` may ask an open period for its liability rollforward preview, which re-runs all eight steps against current data and **persists nothing** — no field is written, no `version` is bumped, and the period's `state` is unchanged."
    "The preview reports `opening_liability_cents`, `issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents`, `expiry_released_cents`, `pre_catchup_liability_cents`, `outstanding_gross_ssp_cents` (the at-close gross the required balance was measured on), `required_liability_cents`, `catch_up_adjustment_cents`, `closing_liability_cents`, `breakage_recognized_cents` and `approved_estimate_rate_bp`."
    "`required_liability_cents` is that at-close gross multiplied by `approved_estimate_rate_bp`, divided by 10000, rounded half up."
    "`catch_up_adjustment_cents` is `required_liability_cents` less `pre_catchup_liability_cents`, and may be negative."
    "`closing_liability_cents` is `pre_catchup_liability_cents` plus `catch_up_adjustment_cents`."
    "On success the eight steps run in the pinned order, `opening_liability_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `closing_liability_cents`, `breakage_recognized_cents` and `approved_estimate_rate_bp` are persisted, `soft_closed_at` is set to the clock reading, and `version` increments by 1."

    Design: Corner/endpoints/endpoint_computed_read_rollforward_previews_then_matches_the_close
    """
    bundle = _ledger_ready(api)
    period_id = bundle["period"]["id"]
    lot = fixtures.issue_lot(api, bundle["member"]["id"], period_id, BASE_POINTS)
    assertions.assert_fields(
        lot,
        gross_ssp_cents=GROSS_SSP_CENTS,
        breakage_reserve_cents=BREAKAGE_RESERVE_CENTS,
        deferred_revenue_cents=DEFERRED_REVENUE_CENTS,
    )
    fixtures.approved_estimate(api, bundle["program"]["id"], period_id)

    before = assertions.assert_ok(api.get_period(period_id, CONTROLLER_HEADERS))
    preview = assertions.assert_ok(
        api.get_liability_rollforward(period_id, ACCOUNTANT_HEADERS)
    )
    assertions.assert_rollforward(
        preview,
        opening_liability_cents=0,
        issuance_deferred_cents=DEFERRED_REVENUE_CENTS,
        redemption_recognized_cents=0,
        remeasurement_delta_cents=0,
        expiry_released_cents=0,
        pre_catchup_liability_cents=DEFERRED_REVENUE_CENTS,
        outstanding_gross_ssp_cents=GROSS_SSP_CENTS,
        required_liability_cents=REQUIRED_LIABILITY_CENTS,
        catch_up_adjustment_cents=CATCH_UP_ADJUSTMENT_CENTS,
        closing_liability_cents=REQUIRED_LIABILITY_CENTS,
        breakage_recognized_cents=-CATCH_UP_ADJUSTMENT_CENTS,
        approved_estimate_rate_bp=ESTIMATED_REDEMPTION_RATE_BP,
    )
    assertions.assert_rollforward_ties(preview)

    after = assertions.assert_ok(api.get_period(period_id, CONTROLLER_HEADERS))
    assertions.assert_fields(
        after,
        state=PERIOD_OPEN,
        version=before["version"],
        soft_closed_at=None,
        opening_liability_cents=0,
        pre_catchup_liability_cents=0,
        required_liability_cents=0,
        catch_up_adjustment_cents=0,
        closing_liability_cents=0,
        breakage_recognized_cents=0,
        approved_estimate_rate_bp=0,
    )

    fixtures.set_clock(api, PERIOD_AUG_END)
    closed = assertions.assert_ok(
        api.soft_close_period(period_id, None, CONTROLLER_HEADERS)
    )
    assertions.assert_fields(
        closed,
        state=PERIOD_SOFT_CLOSED,
        opening_liability_cents=0,
        pre_catchup_liability_cents=DEFERRED_REVENUE_CENTS,
        required_liability_cents=REQUIRED_LIABILITY_CENTS,
        catch_up_adjustment_cents=CATCH_UP_ADJUSTMENT_CENTS,
        closing_liability_cents=REQUIRED_LIABILITY_CENTS,
        breakage_recognized_cents=-CATCH_UP_ADJUSTMENT_CENTS,
        approved_estimate_rate_bp=ESTIMATED_REDEMPTION_RATE_BP,
        version=before["version"] + 1,
    )

    second = assertions.assert_ok(
        api.get_liability_rollforward(period_id, CONTROLLER_HEADERS)
    )
    assert {field: second[field] for field in LIABILITY_ROLLFORWARD_FIELDS} == {
        field: preview[field] for field in LIABILITY_ROLLFORWARD_FIELDS
    }, "The rollforward read must report the same figures the close persisted"

    read_lot = assertions.assert_ok(api.get_point_lot(lot["id"], ACCOUNTANT_HEADERS))
    assertions.assert_fields(
        read_lot, lifecycle_state=LOT_OUTSTANDING, points_remaining=BASE_POINTS
    )


@pytest.mark.parametrize(
    ("unknown_member", "unknown_period", "unknown_agreement", "expected_error_id"),
    [
        (False, True, False, ApiErrorId.PERIOD_NOT_FOUND.value),
        (True, False, False, ApiErrorId.MEMBER_NOT_FOUND.value),
        (True, True, False, ApiErrorId.MEMBER_NOT_FOUND.value),
        (False, False, True, ApiErrorId.PARTNER_AGREEMENT_NOT_FOUND.value),
    ],
    ids=[
        "unresolvable_period",
        "unresolvable_member",
        "both_unresolvable_reports_the_first_declared_field",
        "unresolvable_optional_partner_agreement",
    ],
)
def test_point_lot_body_foreign_keys_resolve_in_declared_order(
    api, unknown_member, unknown_period, unknown_agreement, expected_error_id
):
    """
    Issuance names its holder before it names its period, so when both body
    foreign keys are unresolvable the member decides the 404; an unresolvable
    optional partner agreement is still resolved and still refuses the issuance;
    and no rejected issuance leaves a lot behind or moves the period's deferral.

    "Foreign keys supplied in a request body are resolved after every path segment has resolved, and among themselves they are resolved in the order the endpoint declares its input fields."
    "The request names the holder through `member_id` and the period the issuance books to through `period_id`, optionally names a partner through `partner_agreement_id` (absent or null for programme-issued points), supplies `base_points` of at least 1, and may supply `promo_multiplier_bp`, a promotional multiplier of at least 10000 basis points that defaults to 10000 — meaning no promotion."
    "Each entity has its own not-found code — `ERR_PROGRAM_NOT_FOUND`, `ERR_STATE_EXPIRY_RULE_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_PARTNER_AGREEMENT_NOT_FOUND`, `ERR_POINT_LOT_NOT_FOUND`, `ERR_REDEMPTION_EVENT_NOT_FOUND`, `ERR_BREAKAGE_ESTIMATE_NOT_FOUND`, `ERR_SETTLEMENT_STATEMENT_NOT_FOUND` and `ERR_CHANGE_ORDER_NOT_FOUND` — and each carries HTTP 404."

    Design: Corner/endpoints/endpoint_cross_reference_body_foreign_keys_resolved_in_declared_order
    """
    bundle = _ledger_ready(api)
    period_id = bundle["period"]["id"]
    payload = factories.point_lot_payload(
        UNKNOWN_ID if unknown_member else bundle["member"]["id"],
        UNKNOWN_ID if unknown_period else period_id,
        base_points=BASE_POINTS,
    )
    if unknown_agreement:
        payload["partner_agreement_id"] = UNKNOWN_ID

    assertions.assert_error(
        api.create_point_lot(payload, ACCOUNTANT_HEADERS), expected_error_id
    )

    assertions.assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, period_id=period_id), total_count=0
    )
    period = assertions.assert_ok(api.get_period(period_id, CONTROLLER_HEADERS))
    assertions.assert_fields(period, issuance_deferred_cents=0, state=PERIOD_OPEN)


def test_settlement_statement_dispute_is_reserved_to_the_owning_partner(api):
    """
    Disputing an issued statement is a conditional action gated twice over: the
    accountant who issued it holds no dispute authority at all, the operator of a
    different agreement is an owner failure rather than a role failure, and only
    the operator whose identity is the statement's own agreement moves it to
    DISPUTED and increments the dispute count.

    "Once issued, the partner may push back."
    "A `PartnerOperator` whose `X-User-ID` is the statement's `partner_agreement_id` — and no one else, on pain of `ERR_NOT_RESOURCE_OWNER` — moves the statement `ISSUED → DISPUTED` with a `dispute_reason`, provided its `dispute_count` is below 2."
    "The dispute stores the reason, increments `dispute_count` by 1 and increments `version` by 1."
    "When the role is recognised but is not authorised for the endpoint being addressed, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    "Ownership is enforced on exactly six operations: requesting a redemption, reading one member record, reading one point lot, reading one redemption event, reading one settlement statement, and disputing a settlement statement."
    "Issuing a statement is a `LoyaltyAccountant` action that moves it `DRAFT → ISSUED`, requires the owning agreement to be `ACTIVE`, sets `issued_at` to the clock reading, adds the statement's `net_due_cents` to the agreement's `outstanding_settlement_cents`, and increments both the agreement's and the statement's `version` by 1."

    Design: Corner/endpoints/endpoint_conditional_action_dispute_only_by_the_owning_partner
    """
    bundle = _ledger_ready(api)
    period_id = bundle["period"]["id"]
    agreement_g = fixtures.new_agreement(
        api, bundle["program"]["id"], min_invoice_cents=PARTNER_MIN_INVOICE_CENTS
    )
    agreement_h = fixtures.new_agreement(
        api, bundle["program"]["id"], min_invoice_cents=PARTNER_MIN_INVOICE_CENTS
    )
    fixtures.issue_lot(
        api,
        bundle["member"]["id"],
        period_id,
        PARTNER_BASE_POINTS,
        partner_agreement_id=agreement_g["id"],
    )
    statement = fixtures.issued_statement(api, agreement_g["id"], period_id)
    assertions.assert_fields(
        statement, state=STATEMENT_ISSUED, net_due_cents=PARTNER_NET_DUE_CENTS
    )

    owner_headers = make_partner_operator_headers(agreement_g["id"])
    other_headers = make_partner_operator_headers(agreement_h["id"])

    assertions.assert_error(
        api.dispute_statement(
            statement["id"], factories.dispute_payload(DISPUTE_REASON), ACCOUNTANT_HEADERS
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    assertions.assert_error(
        api.dispute_statement(
            statement["id"], factories.dispute_payload(DISPUTE_REASON), other_headers
        ),
        ApiErrorId.NOT_RESOURCE_OWNER.value,
    )
    assertions.assert_error(
        api.get_statement(statement["id"], other_headers),
        ApiErrorId.NOT_RESOURCE_OWNER.value,
    )

    untouched = assertions.assert_ok(
        api.get_statement(statement["id"], ACCOUNTANT_HEADERS)
    )
    assertions.assert_fields(
        untouched,
        state=STATEMENT_ISSUED,
        dispute_count=0,
        dispute_reason=None,
        version=statement["version"],
    )

    disputed = assertions.assert_ok(
        api.dispute_statement(
            statement["id"], factories.dispute_payload(DISPUTE_REASON), owner_headers
        )
    )
    assertions.assert_fields(
        disputed,
        state=STATEMENT_DISPUTED,
        dispute_count=1,
        dispute_reason=DISPUTE_REASON,
        net_due_cents=PARTNER_NET_DUE_CENTS,
        version=statement["version"] + 1,
    )

    agreement = assertions.assert_ok(
        api.get_agreement(agreement_g["id"], ACCOUNTANT_HEADERS)
    )
    assertions.assert_fields(
        agreement, outstanding_settlement_cents=PARTNER_NET_DUE_CENTS
    )
