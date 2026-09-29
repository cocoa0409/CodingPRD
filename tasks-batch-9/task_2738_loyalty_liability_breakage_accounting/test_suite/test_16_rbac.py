"""
Who may do what: the configuration surface reserved to the programme
administrator, the approval and close surface reserved to the controller, the
ledger writes reserved to the accountant, the operations genuinely shared, the
two entity-backed roles confined to what they own, and the duty rule that
separates preparer from approver.
"""

import pytest

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CLOCK_EPOCH,
    DEFAULT_SEEDED_BREAKAGE_RATE_BP,
    ESTIMATE_APPROVED,
    ESTIMATE_SUBMITTED,
    LOT_OUTSTANDING,
    PERIOD_OPEN,
    PROGRAM_DRAFT,
    REDEMPTION_REQUESTED,
    STATEMENT_DRAFT,
    UNKNOWN_ID,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_2_HEADERS,
    CONTROLLER_2_ID,
    CONTROLLER_HEADERS,
    PREPARER_AS_CONTROLLER_HEADERS,
    ACCOUNTANT_ID,
    PROGRAM_ADMIN_HEADERS,
    make_member_headers,
    make_partner_operator_headers,
)

# A future instant a change order can be modelled against.
CHANGE_EFFECTIVE_AT = "2026-12-01T00:00:00Z"

# A version number that is deliberately wrong, to prove the role gate is reached
# before any version comparison.
NONSENSE_PROGRAM_VERSION = 999

# The reference issuance: 1000 BASE points at 1200 millicents, reserved at the
# seeded rate of 2500 basis points.
BASE_POINTS = 1000
GROSS_SSP_CENTS = 1200
DEFERRED_REVENUE_CENTS = 900

# The single cohort's observed rate, the liability it requires, and the live
# breakage rate an approval leaves behind.
OBSERVED_REDEMPTION_RATE_BP = 8200
REQUIRED_LIABILITY_CENTS = 984
APPROVED_BREAKAGE_RATE_BP = 1800

# The partner legs: 2000 and 3000 points billed at 900 millicents per point.
PARTNER_MIN_INVOICE_CENTS = 1000
PARTNER_G_POINTS = 2000
PARTNER_H_POINTS = 3000
PARTNER_G_NET_DUE_CENTS = 1800
PARTNER_H_NET_DUE_CENTS = 2700

REDEMPTION_POINTS = 400

# The clock instants the shared-capability probe walks through.
CLOCK_SECOND = "2026-08-02T00:00:00Z"
CLOCK_THIRD = "2026-08-03T00:00:00Z"
CLOCK_REFUSED = "2026-08-04T00:00:00Z"

_MEMBER_STRANGER_HEADERS = make_member_headers("member-x")
_PARTNER_STRANGER_HEADERS = make_partner_operator_headers("agreement-x")


def _ledger_ready(api, member_headers=None, clock=CLOCK_EPOCH):
    """
    The state every ledger write needs: an ACTIVE programme carrying one state
    expiry rule and one cohort, one member and one OPEN period.
    """
    fixtures.set_clock(api, clock)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(api, program["id"])
    cohort = fixtures.new_cohort(api, program["id"])
    program = fixtures.activate(api, program["id"])
    member = assertions.assert_created(
        api.create_member(
            factories.member_payload(program["id"], cohort["id"]),
            member_headers or ACCOUNTANT_HEADERS,
        )
    )
    period = fixtures.new_period(api, program["id"])
    return {
        "program": program,
        "cohort": cohort,
        "member": member,
        "period": period,
    }


def _admin_only_probes():
    """
    Every configuration operation the programme administrator holds alone, each
    attempted by one of the two back-office roles that does not hold it.
    """
    return {
        "programme_creation_by_the_accountant": lambda api, program_id: api.create_program(
            factories.program_payload(), ACCOUNTANT_HEADERS
        ),
        "state_expiry_rule_creation_by_the_accountant": lambda api, program_id: api.create_state_expiry_rule(
            factories.state_expiry_rule_payload(program_id), ACCOUNTANT_HEADERS
        ),
        "programme_activation_by_the_controller": lambda api, program_id: api.activate_program(
            program_id, None, CONTROLLER_HEADERS
        ),
        "partner_agreement_creation_by_the_controller": lambda api, program_id: api.create_agreement(
            factories.agreement_payload(program_id), CONTROLLER_HEADERS
        ),
        "partner_agreement_termination_by_the_accountant": lambda api, program_id: api.terminate_agreement(
            UNKNOWN_ID, None, ACCOUNTANT_HEADERS
        ),
        "change_order_modelling_by_the_controller": lambda api, program_id: api.create_change_order(
            factories.change_order_payload(program_id, CHANGE_EFFECTIVE_AT),
            CONTROLLER_HEADERS,
        ),
    }


_ADMIN_ONLY_PROBES = _admin_only_probes()


def _controller_only_probes():
    """
    Every approval-and-close operation the controller holds alone, each attempted
    by one of the two back-office roles that does not hold it, and each addressing
    an identifier that does not resolve so the role gate can be seen to fire
    first.
    """
    return {
        "period_creation_by_the_admin": lambda api, program_id: api.create_period(
            factories.period_payload(program_id), PROGRAM_ADMIN_HEADERS
        ),
        "period_soft_close_by_the_accountant": lambda api, program_id: api.soft_close_period(
            UNKNOWN_ID, None, ACCOUNTANT_HEADERS
        ),
        "period_reopen_by_the_accountant": lambda api, program_id: api.reopen_period(
            UNKNOWN_ID, None, ACCOUNTANT_HEADERS
        ),
        "period_hard_close_by_the_admin": lambda api, program_id: api.hard_close_period(
            UNKNOWN_ID, None, PROGRAM_ADMIN_HEADERS
        ),
        "estimate_approval_by_the_accountant": lambda api, program_id: api.approve_estimate(
            UNKNOWN_ID,
            factories.approval_payload(NONSENSE_PROGRAM_VERSION),
            ACCOUNTANT_HEADERS,
        ),
        "estimate_rejection_by_the_accountant": lambda api, program_id: api.reject_estimate(
            UNKNOWN_ID, factories.rejection_payload(), ACCOUNTANT_HEADERS
        ),
        "statement_payment_by_the_accountant": lambda api, program_id: api.pay_statement(
            UNKNOWN_ID, None, ACCOUNTANT_HEADERS
        ),
        "statement_write_off_by_the_accountant": lambda api, program_id: api.write_off_statement(
            UNKNOWN_ID, factories.write_off_payload(), ACCOUNTANT_HEADERS
        ),
        "change_order_approval_by_the_admin": lambda api, program_id: api.approve_change_order(
            UNKNOWN_ID, None, PROGRAM_ADMIN_HEADERS
        ),
        "change_order_application_by_the_admin": lambda api, program_id: api.apply_change_order(
            UNKNOWN_ID, None, PROGRAM_ADMIN_HEADERS
        ),
    }


_CONTROLLER_ONLY_PROBES = _controller_only_probes()


@pytest.mark.parametrize("probe_name", sorted(_ADMIN_ONLY_PROBES))
def test_programme_configuration_is_refused_to_every_other_role(api, probe_name):
    """
    Configuring the programme is the administrator's alone: neither the
    accountant who keeps the ledger nor the controller who closes the books may
    create a programme, attach a state expiry rule, activate, sign or terminate a
    partner agreement, or model a change order. Terminating an agreement that does
    not even exist is still a role refusal rather than a not-found, and no refusal
    leaves anything behind.

    "A `ProgramAdmin` configures the programme — programme creation, activation, suspension and closure; state expiry rules; partner agreements and their termination; and the modelling of programme change orders."
    "When the role is recognised but is not authorised for the endpoint being addressed, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."
    "**Role authorisation** — `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."

    Design: Corner/rbac/rbac_program_admin_exclusive_configuration_denied_to_others
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)

    assertions.assert_error(
        _ADMIN_ONLY_PROBES[probe_name](api, program["id"]),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    assertions.assert_page(
        api.list_programs(PROGRAM_ADMIN_HEADERS),
        expected_ids=[program["id"]],
        total_count=1,
    )
    after = assertions.assert_ok(api.get_program(program["id"], PROGRAM_ADMIN_HEADERS))
    assertions.assert_fields(after, status=PROGRAM_DRAFT, version=program["version"])
    assertions.assert_page(
        api.list_state_expiry_rules(PROGRAM_ADMIN_HEADERS, program_id=program["id"]),
        total_count=0,
    )
    assertions.assert_page(
        api.list_agreements(PROGRAM_ADMIN_HEADERS, program_id=program["id"]),
        total_count=0,
    )
    assertions.assert_page(
        api.list_change_orders(PROGRAM_ADMIN_HEADERS, program_id=program["id"]),
        total_count=0,
    )


def test_the_admin_configures_what_the_other_roles_could_not(api):
    """
    The refusals are about the role and nothing else: the very state expiry rule
    body the accountant was denied is accepted from the programme administrator,
    and it is the only rule on file afterwards.

    "A `ProgramAdmin` configures the programme — programme creation, activation, suspension and closure; state expiry rules; partner agreements and their termination; and the modelling of programme change orders."
    "Creation endpoints return HTTP 201 with the created resource in `data`."

    Design: Corner/rbac/rbac_program_admin_exclusive_configuration_denied_to_others
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    payload = factories.state_expiry_rule_payload(program["id"])

    assertions.assert_error(
        api.create_state_expiry_rule(payload, ACCOUNTANT_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    rule = assertions.assert_created(
        api.create_state_expiry_rule(payload, PROGRAM_ADMIN_HEADERS)
    )
    assertions.assert_fields(rule, program_id=program["id"])
    assertions.assert_page(
        api.list_state_expiry_rules(PROGRAM_ADMIN_HEADERS, program_id=program["id"]),
        expected_ids=[rule["id"]],
        total_count=1,
    )


@pytest.mark.parametrize("probe_name", sorted(_CONTROLLER_ONLY_PROBES))
def test_approval_and_close_are_refused_to_every_other_role(api, probe_name):
    """
    Opening, closing and reopening periods, approving and rejecting estimates,
    paying and writing off statements, and approving and applying change orders
    all belong to the controller alone. Each refusal is a role refusal: it is not
    a not-found even though the addressed identifier resolves to nothing, and not
    a stale-version failure even though the approval body carries a version that
    could never be right.

    "A `Controller` approves and closes — approving and rejecting breakage estimates, opening, soft-closing, reopening and hard-closing accounting periods, paying and writing off settlement statements, and approving and applying programme change orders."
    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."
    "**Role authorisation** — `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."
    "**Programme version match** — `ERR_STALE_PROGRAM_VERSION` (412), on estimate approval. This sits above every state check, so a stale approval is reported as 412 even when the estimate is also in the wrong state."

    Design: Corner/rbac/rbac_controller_exclusive_approval_and_close_denied_to_others
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)

    assertions.assert_error(
        _CONTROLLER_ONLY_PROBES[probe_name](api, program["id"]),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    assertions.assert_page(
        api.list_periods(CONTROLLER_HEADERS, program_id=program["id"]), total_count=0
    )
    assertions.assert_page(
        api.list_change_orders(PROGRAM_ADMIN_HEADERS, program_id=program["id"]),
        total_count=0,
    )


def test_the_controller_opens_the_period_the_others_could_not(api):
    """
    The identical period body the administrator was refused is accepted from the
    controller, and the period it opens starts life OPEN with no reopens spent.

    "Only a `Controller` opens an **AccountingPeriod**."
    "A new period is born in `state` `OPEN`, with `reopen_count` at 0, with `soft_closed_at` null, and with all eleven of its currency and rate rollforward figures at 0: `opening_liability_cents`, `issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents`, `expiry_released_cents`, `escheat_accrual_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `breakage_recognized_cents`, `closing_liability_cents` and `approved_estimate_rate_bp`."

    Design: Corner/rbac/rbac_controller_exclusive_approval_and_close_denied_to_others
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    payload = factories.period_payload(program["id"])

    assertions.assert_error(
        api.create_period(payload, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    period = assertions.assert_created(api.create_period(payload, CONTROLLER_HEADERS))
    assertions.assert_fields(
        period,
        program_id=program["id"],
        state=PERIOD_OPEN,
        reopen_count=0,
        soft_closed_at=None,
    )
    assertions.assert_page(
        api.list_periods(CONTROLLER_HEADERS, program_id=program["id"]),
        expected_ids=[period["id"]],
        total_count=1,
    )


def _accountant_only_probes():
    """
    The ledger writes the accountant holds alone, refused in both directions —
    once to the controller who approves and once to the administrator who
    configures — plus the analysis read the administrator alone is excluded from.
    """
    return {
        "point_issuance_by_the_controller": lambda api, bundle: api.create_point_lot(
            factories.point_lot_payload(
                bundle["member"]["id"], bundle["period"]["id"], BASE_POINTS
            ),
            CONTROLLER_HEADERS,
        ),
        "point_issuance_by_the_admin": lambda api, bundle: api.create_point_lot(
            factories.point_lot_payload(
                bundle["member"]["id"], bundle["period"]["id"], BASE_POINTS
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        "expiry_sweep_by_the_controller": lambda api, bundle: api.run_expiry_sweep(
            bundle["period"]["id"], None, CONTROLLER_HEADERS
        ),
        "estimate_preparation_by_the_controller": lambda api, bundle: api.create_estimate(
            bundle["program"]["id"],
            factories.estimate_payload(bundle["period"]["id"]),
            CONTROLLER_HEADERS,
        ),
        "redemption_allocation_by_the_controller": lambda api, bundle: api.allocate_redemption(
            UNKNOWN_ID, None, CONTROLLER_HEADERS
        ),
        "rollforward_preview_by_the_admin": lambda api, bundle: api.get_liability_rollforward(
            bundle["period"]["id"], PROGRAM_ADMIN_HEADERS
        ),
    }


_ACCOUNTANT_ONLY_PROBES = _accountant_only_probes()


@pytest.mark.parametrize("probe_name", sorted(_ACCOUNTANT_ONLY_PROBES))
def test_ledger_writes_are_refused_to_every_other_role(api, probe_name):
    """
    Issuing points, sweeping for expiry, preparing an estimate and allocating a
    redemption are the accountant's alone, refused to the controller who approves
    and to the administrator who configures alike; the rollforward preview is
    shared with the controller but still closed to the administrator. Nothing is
    issued and no deferral is booked by a refused call.

    "A `LoyaltyAccountant` prepares the ledger — issuing point lots, allocating, fulfilling and reversing redemptions, running the expiry sweep, preparing and submitting breakage estimates, and creating, issuing and resolving partner settlement statements."
    "A `ProgramAdmin` never touches the ledger."
    "Point issuance is exclusively a `LoyaltyAccountant` action, and it is where the liability is born."
    "A `LoyaltyAccountant` or `Controller` may ask an open period for its liability rollforward preview, which re-runs all eight steps against current data and **persists nothing** — no field is written, no `version` is bumped, and the period's `state` is unchanged."
    "**Role authorisation** — `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."

    Design: Corner/rbac/rbac_accountant_exclusive_ledger_writes_denied_to_others
    """
    bundle = _ledger_ready(api, member_headers=PROGRAM_ADMIN_HEADERS)

    assertions.assert_error(
        _ACCOUNTANT_ONLY_PROBES[probe_name](api, bundle),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    assertions.assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, period_id=bundle["period"]["id"]),
        total_count=0,
    )
    period = assertions.assert_ok(
        api.get_period(bundle["period"]["id"], CONTROLLER_HEADERS)
    )
    assertions.assert_fields(period, issuance_deferred_cents=0, state=PERIOD_OPEN)


def test_the_accountant_issues_the_lot_the_other_roles_could_not(api):
    """
    The administrator may read the period it may not analyse, and the identical
    issuance body both other roles were refused is accepted from the accountant:
    the lot is measured and its deferral — not its gross price — lands in the
    period's accumulator.

    "A `ProgramAdmin` never touches the ledger."
    "Members are enrolled by either a `ProgramAdmin` or a `LoyaltyAccountant` into a named cohort of a named programme, supplying `program_id`, `cohort_id`, an `external_member_ref` of at most 64 non-empty characters, a `state_code` of exactly two uppercase letters giving the state of residence that selects the governing expiry rule, and a `tier` of `BASE`, `SILVER`, `GOLD` or `PLATINUM` — `BASE` when omitted."
    "**Gross standalone selling price.** `gross_ssp_cents` is `points_issued` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."
    "`issuance_deferred_cents` grows by each issued lot's `deferred_revenue_cents`."

    Design: Corner/rbac/rbac_accountant_exclusive_ledger_writes_denied_to_others
    """
    bundle = _ledger_ready(api, member_headers=PROGRAM_ADMIN_HEADERS)
    period_id = bundle["period"]["id"]
    payload = factories.point_lot_payload(bundle["member"]["id"], period_id, BASE_POINTS)

    readable = assertions.assert_ok(api.get_period(period_id, PROGRAM_ADMIN_HEADERS))
    assertions.assert_fields(readable, state=PERIOD_OPEN)
    assertions.assert_error(
        api.get_liability_rollforward(period_id, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    assertions.assert_error(
        api.create_point_lot(payload, CONTROLLER_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    lot = assertions.assert_created(api.create_point_lot(payload, ACCOUNTANT_HEADERS))
    assertions.assert_fields(
        lot,
        points_issued=BASE_POINTS,
        gross_ssp_cents=GROSS_SSP_CENTS,
        deferred_revenue_cents=DEFERRED_REVENUE_CENTS,
        breakage_rate_bp_at_issue=DEFAULT_SEEDED_BREAKAGE_RATE_BP,
        lifecycle_state=LOT_OUTSTANDING,
    )

    period = assertions.assert_ok(api.get_period(period_id, CONTROLLER_HEADERS))
    assertions.assert_fields(period, issuance_deferred_cents=DEFERRED_REVENUE_CENTS)


def test_shared_operations_are_accepted_for_every_declared_holder(api):
    """
    A shared capability must work for each role that holds it and for no one else:
    cohort creation and member enrolment are accepted from both the administrator
    and the accountant but refused to the controller, while the clock is accepted
    from all three back-office roles and refused to both entity-backed ones — the
    refused attempt leaves the clock where the controller put it, as the next
    enrolment's timestamp shows.

    "| POST | `/cohorts` | Creates an enrolment Cohort carrying the historical redemption pattern used by breakage measurement. | ProgramAdmin, LoyaltyAccountant |"
    "Members are enrolled by either a `ProgramAdmin` or a `LoyaltyAccountant` into a named cohort of a named programme, supplying `program_id`, `cohort_id`, an `external_member_ref` of at most 64 non-empty characters, a `state_code` of exactly two uppercase letters giving the state of residence that selects the governing expiry rule, and a `tier` of `BASE`, `SILVER`, `GOLD` or `PLATINUM` — `BASE` when omitted."
    "A test-driving capability, available to `ProgramAdmin`, `LoyaltyAccountant` and `Controller` alike, sets the clock to a supplied `current_utc` instant."
    "A new member is born with `status` `ACTIVE`, with `enrolled_at` set to the current logical clock reading, and with `last_activity_at` initialised to that same instant."
    "When the role is recognised but is not authorised for the endpoint being addressed, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/rbac_shared_operations_accepted_for_every_declared_holder
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    program_id = program["id"]

    cohort_admin = assertions.assert_created(
        api.create_cohort(factories.cohort_payload(program_id), PROGRAM_ADMIN_HEADERS)
    )
    cohort_accountant = assertions.assert_created(
        api.create_cohort(factories.cohort_payload(program_id), ACCOUNTANT_HEADERS)
    )
    assertions.assert_error(
        api.create_cohort(factories.cohort_payload(program_id), CONTROLLER_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    assertions.assert_created(
        api.create_member(
            factories.member_payload(program_id, cohort_admin["id"]),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assertions.assert_created(
        api.create_member(
            factories.member_payload(program_id, cohort_accountant["id"]),
            ACCOUNTANT_HEADERS,
        )
    )
    assertions.assert_error(
        api.create_member(
            factories.member_payload(program_id, cohort_admin["id"]), CONTROLLER_HEADERS
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    assertions.assert_ok(api.set_clock(CLOCK_EPOCH, PROGRAM_ADMIN_HEADERS))
    assertions.assert_ok(api.set_clock(CLOCK_SECOND, ACCOUNTANT_HEADERS))
    assertions.assert_ok(api.set_clock(CLOCK_THIRD, CONTROLLER_HEADERS))
    assertions.assert_error(
        api.set_clock(CLOCK_REFUSED, _MEMBER_STRANGER_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    assertions.assert_error(
        api.set_clock(CLOCK_REFUSED, _PARTNER_STRANGER_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    late_member = assertions.assert_created(
        api.create_member(
            factories.member_payload(program_id, cohort_admin["id"]), ACCOUNTANT_HEADERS
        )
    )
    assertions.assert_fields(
        late_member, enrolled_at=CLOCK_THIRD, last_activity_at=CLOCK_THIRD
    )

    assertions.assert_page(
        api.list_cohorts(PROGRAM_ADMIN_HEADERS, program_id=program_id),
        expected_ids=[cohort_admin["id"], cohort_accountant["id"]],
        total_count=2,
    )
    assertions.assert_page(
        api.list_members(PROGRAM_ADMIN_HEADERS, program_id=program_id), total_count=3
    )


def test_a_member_may_act_only_on_its_own_account(api):
    """
    A member's authority is scoped by the identity it acts under: raising a
    request for another member, or reading that member's record or lots, is an
    ownership refusal, while the collection read of lots and the allocation that
    follows a request are refusals of a different kind, because the member holds
    no such capability at all. Its own request succeeds and consumes nothing.

    "A `Member` is a loyalty programme member acting on its own account."
    "A member may request a redemption for itself and read its own record, lots and events; it never allocates, fulfils or measures anything."
    "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on a member record, a point lot or a redemption event compare the resource's `member_id` (or, for the member record itself, its own `id`) to `X-User-ID`."
    "In all six the rejection for an entity-backed role addressing something it does not own is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    "A redemption begins as a request, which either a `LoyaltyAccountant` or the `Member` itself may raise; a `Member` may raise one only for its own account, and addressing another member's account is rejected with `ERR_NOT_RESOURCE_OWNER`."
    "The new **RedemptionEvent** is born in `state` `REQUESTED` with `requested_at` set to the clock reading, `allocated_at` null, `reversal_reason` null, and its four monetary figures — `provisional_release_cents`, `final_release_cents`, `remeasurement_delta_cents` and `partner_cost_cents` — all at 0."
    "No revenue is released by the request itself."
    "**Allocation** — a `LoyaltyAccountant` action that moves the event `REQUESTED → ALLOCATED` — is where lots are consumed."
    "| GET | `/point-lots` | Lists PointLots; filterable by member, period, partner agreement and either state dimension. | ProgramAdmin, LoyaltyAccountant, Controller |"

    Design: Corner/rbac/rbac_member_may_act_only_on_its_own_account
    """
    bundle = _ledger_ready(api)
    program_id = bundle["program"]["id"]
    period_id = bundle["period"]["id"]
    first = bundle["member"]
    second = assertions.assert_created(
        api.create_member(
            factories.member_payload(program_id, bundle["cohort"]["id"]),
            ACCOUNTANT_HEADERS,
        )
    )
    lot = fixtures.issue_lot(api, first["id"], period_id, BASE_POINTS)

    first_headers = make_member_headers(first["id"])
    second_headers = make_member_headers(second["id"])
    request_body = factories.redemption_payload(
        first["id"], period_id, REDEMPTION_POINTS
    )

    assertions.assert_error(
        api.create_redemption(request_body, second_headers),
        ApiErrorId.NOT_RESOURCE_OWNER.value,
    )
    assertions.assert_error(
        api.get_member(first["id"], second_headers),
        ApiErrorId.NOT_RESOURCE_OWNER.value,
    )
    assertions.assert_error(
        api.get_point_lot(lot["id"], second_headers),
        ApiErrorId.NOT_RESOURCE_OWNER.value,
    )
    assertions.assert_error(
        api.list_point_lots(first_headers), ApiErrorId.ROLE_NOT_PERMITTED.value
    )

    event = assertions.assert_created(
        api.create_redemption(request_body, first_headers)
    )
    assertions.assert_fields(
        event,
        state=REDEMPTION_REQUESTED,
        member_id=first["id"],
        points_requested=REDEMPTION_POINTS,
        provisional_release_cents=0,
        final_release_cents=0,
        allocated_at=None,
    )

    assertions.assert_error(
        api.allocate_redemption(event["id"], None, first_headers),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    untouched_lot = assertions.assert_ok(
        api.get_point_lot(lot["id"], ACCOUNTANT_HEADERS)
    )
    assertions.assert_fields(
        untouched_lot, points_remaining=BASE_POINTS, lifecycle_state=LOT_OUTSTANDING
    )
    period = assertions.assert_ok(api.get_period(period_id, CONTROLLER_HEADERS))
    assertions.assert_fields(period, redemption_recognized_cents=0)

    own_record = assertions.assert_ok(api.get_member(first["id"], first_headers))
    assertions.assert_fields(own_record, point_balance=BASE_POINTS)


def test_a_partner_operator_is_confined_to_its_own_agreement(api):
    """
    The partner's statement list is scoped rather than refused — it sees its own
    agreement's statement and not the other's — and it may read the agreement it
    acts as. Everything else is closed to it: it may not issue even the statement
    raised against it, may not mint the points it is paid for, and holds neither
    the collection read of lots nor the read of an accounting period.

    "A `PartnerOperator` is a third-party or intercompany partner acting on its own agreement."
    "Its only write capability is disputing a statement issued against that agreement."
    "A `PartnerOperator` listing settlement statements sees only the statements of the agreement it acts as; a `PartnerOperator` reading one agreement may read only the agreement it acts as."
    "When `X-User-Role` is `PartnerOperator`, `X-User-ID` is the `id` of the acting `PartnerAgreement`; ownership checks on any settlement statement compare the statement's `partner_agreement_id` to `X-User-ID`."
    "From those two counts, `issuance_receivable_cents` is `partner_issued_points` multiplied by the agreement's `issuance_rate_millicents_per_point`, divided by 1000, rounded half up, and `redemption_payable_cents` is `partner_redeemed_points` multiplied by the agreement's `redemption_rate_millicents_per_point`, divided by 1000, rounded half up."
    "Otherwise `net_due_cents` takes the candidate and `deferred_below_minimum_cents` is 0."
    "| GET | `/point-lots` | Lists PointLots; filterable by member, period, partner agreement and either state dimension. | ProgramAdmin, LoyaltyAccountant, Controller |"
    "| GET | `/accounting-periods/{id}` | Reads one AccountingPeriod with all eleven persisted rollforward figures. | ProgramAdmin, LoyaltyAccountant, Controller |"

    Design: Corner/rbac/rbac_partner_operator_confined_to_its_own_agreement
    """
    bundle = _ledger_ready(api)
    program_id = bundle["program"]["id"]
    period_id = bundle["period"]["id"]
    member_id = bundle["member"]["id"]

    agreement_g = fixtures.new_agreement(
        api, program_id, min_invoice_cents=PARTNER_MIN_INVOICE_CENTS
    )
    agreement_h = fixtures.new_agreement(
        api, program_id, min_invoice_cents=PARTNER_MIN_INVOICE_CENTS
    )
    fixtures.issue_lot(
        api,
        member_id,
        period_id,
        PARTNER_G_POINTS,
        partner_agreement_id=agreement_g["id"],
    )
    fixtures.issue_lot(
        api,
        member_id,
        period_id,
        PARTNER_H_POINTS,
        partner_agreement_id=agreement_h["id"],
    )
    statement_g = fixtures.draft_statement(api, agreement_g["id"], period_id)
    statement_h = fixtures.draft_statement(api, agreement_h["id"], period_id)
    assertions.assert_fields(
        statement_g,
        state=STATEMENT_DRAFT,
        partner_issued_points=PARTNER_G_POINTS,
        net_due_cents=PARTNER_G_NET_DUE_CENTS,
        deferred_below_minimum_cents=0,
    )
    assertions.assert_fields(
        statement_h,
        partner_issued_points=PARTNER_H_POINTS,
        net_due_cents=PARTNER_H_NET_DUE_CENTS,
    )

    operator_headers = make_partner_operator_headers(agreement_g["id"])

    assertions.assert_page(
        api.list_statements(operator_headers),
        expected_ids=[statement_g["id"]],
        total_count=1,
    )
    own_agreement = assertions.assert_ok(
        api.get_agreement(agreement_g["id"], operator_headers)
    )
    assertions.assert_fields(own_agreement, program_id=program_id)

    assertions.assert_error(
        api.issue_statement(statement_g["id"], None, operator_headers),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    assertions.assert_error(
        api.create_point_lot(
            factories.point_lot_payload(
                member_id,
                period_id,
                BASE_POINTS,
                partner_agreement_id=agreement_g["id"],
            ),
            operator_headers,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    assertions.assert_error(
        api.list_point_lots(operator_headers), ApiErrorId.ROLE_NOT_PERMITTED.value
    )
    assertions.assert_error(
        api.get_period(period_id, operator_headers),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    after = assertions.assert_ok(
        api.get_statement(statement_g["id"], ACCOUNTANT_HEADERS)
    )
    assertions.assert_fields(
        after, state=STATEMENT_DRAFT, version=statement_g["version"]
    )
    agreement = assertions.assert_ok(
        api.get_agreement(agreement_g["id"], ACCOUNTANT_HEADERS)
    )
    assertions.assert_fields(agreement, outstanding_settlement_cents=0)


def test_the_preparer_of_an_estimate_may_not_approve_it(api):
    """
    Approval is gated on identity, not on role: the controller who is the same
    human as the preparer is refused even though the role is right and the
    programme version supplied is exactly current, the estimate is left submitted
    and unapproved with the programme's live rate untouched, and a second
    controller then approves the identical body.

    "Segregation of duties adds one further constraint that is independent of role membership: the `X-User-ID` that approves a breakage estimate must differ from the `X-User-ID` recorded as that estimate's `prepared_by_user_id`."
    "Two distinct `Controller` users are perfectly acceptable; one human acting as both preparer and approver is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (409), on estimate approval."
    "**Programme version match** — `ERR_STALE_PROGRAM_VERSION` (412), on estimate approval. This sits above every state check, so a stale approval is reported as 412 even when the estimate is also in the wrong state."
    "The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment."
    "From the measured rate, `breakage_rate_bp` is 10000 basis points less `estimated_redemption_rate_bp`."
    "The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1."

    Design: Corner/rbac/rbac_segregation_of_duties_preparer_cannot_approve_own_estimate
    """
    bundle = _ledger_ready(api)
    program_id = bundle["program"]["id"]
    period_id = bundle["period"]["id"]
    fixtures.issue_lot(api, bundle["member"]["id"], period_id, BASE_POINTS)

    estimate = fixtures.submitted_estimate(api, program_id, period_id)
    assertions.assert_fields(
        estimate, state=ESTIMATE_SUBMITTED, prepared_by_user_id=ACCOUNTANT_ID
    )
    seeded = assertions.assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assertions.assert_fields(
        seeded, current_breakage_rate_bp=DEFAULT_SEEDED_BREAKAGE_RATE_BP
    )

    body = factories.approval_payload(seeded["version"])
    assertions.assert_error(
        api.approve_estimate(estimate["id"], body, PREPARER_AS_CONTROLLER_HEADERS),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
    )

    refused = assertions.assert_ok(api.get_estimate(estimate["id"], CONTROLLER_HEADERS))
    assertions.assert_fields(
        refused,
        state=ESTIMATE_SUBMITTED,
        approved_by_user_id=None,
        approved_at=None,
        version=estimate["version"],
    )
    unchanged = assertions.assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assertions.assert_fields(
        unchanged,
        current_breakage_rate_bp=DEFAULT_SEEDED_BREAKAGE_RATE_BP,
        version=seeded["version"],
    )

    approved = assertions.assert_ok(
        api.approve_estimate(estimate["id"], body, CONTROLLER_2_HEADERS)
    )
    assertions.assert_fields(
        approved,
        state=ESTIMATE_APPROVED,
        approved_by_user_id=CONTROLLER_2_ID,
        estimated_redemption_rate_bp=OBSERVED_REDEMPTION_RATE_BP,
        breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP,
        outstanding_gross_ssp_cents_at_estimate=GROSS_SSP_CENTS,
        required_liability_cents=REQUIRED_LIABILITY_CENTS,
    )
    after = assertions.assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assertions.assert_fields(
        after, current_breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP
    )
