"""Transitive cascades from permit denial and dispute adjustment, cross-entity
state guards, and isolated space/credit/dispute-subject validations.

Queue A — transitive_cascade (permit-denied → invoice VOID → balance;
dispute-adjusted → invoice amount → balance), cross_entity_state_dependency
(finding legalize needs ACTIVE pole; invoice pay blocked by open dispute).
Queue B — validations (dispute subject invalid, insufficient pole space,
credit limit exceeded).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_attacher_headers, make_permit_officer_headers,
    setup_owner, setup_pole, setup_attacher, setup_base,
    create_accepted_application, create_estimate_issued_application,
    deny_permit, get_make_ready_invoice_for_application,
    create_finding, open_dispute_on_invoice, dispute_to_under_review,
    COMPLEX_SURVEY, api_client,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]
_SIMPLE_SURVEY = {"estimated_labor_hours": 4, "make_ready_required": True,
                  "existing_attacher_count": 0, "complexity_class": "SIMPLE"}


# ─── Queue A: transitive_cascade (permit denied → invoice → balance) ───────
def test_permit_denied_cascade_voids_make_ready_invoice(api):
    """PRD §3.4: "and cascades to the make-ready invoice: the invoice identified
    by `make_ready_invoice_id` transitions to `VOID`, and because a voided
    invoice leaves the outstanding set, the attacher's `account_balance_cents`
    is recomputed downward."

    Design: Difficulty/transitive_cascade/permit_denied_cascade_application_invoice_attacher
    """
    ctx = create_accepted_application(survey_overrides=COMPLEX_SURVEY)
    invoice = get_make_ready_invoice_for_application(ctx["app"]["id"])
    deny_permit(ctx["app"]["id"])
    after = get_success_data(api_client.get_invoice(invoice["id"], COORD))
    assert after["status"] == "VOID"


def test_permit_denied_cascade_recomputes_attacher_balance(api):
    """PRD §3.4: "and cascades to the make-ready invoice: the invoice identified
    by `make_ready_invoice_id` transitions to `VOID`, and because a voided
    invoice leaves the outstanding set, the attacher's `account_balance_cents`
    is recomputed downward."

    Design: Difficulty/transitive_cascade/permit_denied_cascade_application_invoice_attacher
    """
    ctx = create_accepted_application(survey_overrides=COMPLEX_SURVEY)
    deny_permit(ctx["app"]["id"])
    attacher = get_success_data(api_client.get_attacher(ctx["attacher"]["id"], COORD))
    assert attacher["account_balance_cents"] == 0


# ─── Queue A: transitive_cascade (dispute adjusted → invoice → balance) ────
def _bad_faith_finding_disputed_under_review():
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    finding = create_finding(pole["id"], attacher["id"], discovered_space_inches=12,
                             discovered_position_inches=150, good_faith=False,
                             estimated_install_years_ago=7)
    disp = open_dispute_on_invoice(attacher["id"], finding["penalty_invoice_id"])
    dispute_to_under_review(disp["id"])
    return attacher, finding, disp


def test_dispute_adjusted_cascade_sets_invoice_amount(api):
    """PRD §3.8: "An adjustment sets `resolution` to `ADJUSTED`, cascades by
    replacing the referenced invoice's `amount_cents` with the
    `adjusted_amount_cents`, and recomputes the attacher's `account_balance_cents`
    from the new invoice amount."

    Design: Difficulty/transitive_cascade/dispute_adjusted_cascade_invoice_attacher
    """
    attacher, finding, disp = _bad_faith_finding_disputed_under_review()
    api.transition_dispute(disp["id"], {"to_state": "RESOLVED_ADJUSTED",
                                        "adjusted_amount_cents": 30000}, COORD)
    invoice = get_success_data(api_client.get_invoice(finding["penalty_invoice_id"], COORD))
    assert invoice["amount_cents"] == 30000


def test_dispute_adjusted_cascade_recomputes_balance(api):
    """PRD §3.8: "An adjustment sets `resolution` to `ADJUSTED`, cascades by
    replacing the referenced invoice's `amount_cents` with the
    `adjusted_amount_cents`, and recomputes the attacher's `account_balance_cents`
    from the new invoice amount."

    Design: Difficulty/transitive_cascade/dispute_adjusted_cascade_invoice_attacher
    """
    attacher, finding, disp = _bad_faith_finding_disputed_under_review()
    api.transition_dispute(disp["id"], {"to_state": "RESOLVED_ADJUSTED",
                                        "adjusted_amount_cents": 30000}, COORD)
    refreshed = get_success_data(api_client.get_attacher(attacher["id"], COORD))
    assert refreshed["account_balance_cents"] == 30000


# ─── Queue A: cross_entity (finding legalize requires ACTIVE pole) ─────────
def test_finding_legalize_requires_pole_active(api):
    """PRD §3.9: "A `RETIRED` pole is terminal, and any operation that requires
    an `ACTIVE` pole — a survey or a finding legalization — will thereafter fail
    with `ERR_POLE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/finding_legalize_requires_pole_active
    """
    owner = setup_owner(owner_category="MUNICIPAL")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    finding = create_finding(pole["id"], attacher["id"], discovered_space_inches=8,
                             discovered_position_inches=150)
    get_success_data(api_client.retire_pole(pole["id"], COORD))
    res = api.resolve_finding(finding["id"], {"resolution": "LEGALIZE"}, COORD)
    validate_error(res, "ERR_POLE_NOT_ACTIVE", expected_status=409)


def test_finding_legalize_on_retired_pole_leaves_finding_flagged(api):
    """PRD §3.9: "A `RETIRED` pole is terminal, and any operation that requires
    an `ACTIVE` pole — a survey or a finding legalization — will thereafter fail
    with `ERR_POLE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/finding_legalize_requires_pole_active
    """
    owner = setup_owner(owner_category="MUNICIPAL")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    finding = create_finding(pole["id"], attacher["id"], discovered_space_inches=8,
                             discovered_position_inches=150)
    get_success_data(api_client.retire_pole(pole["id"], COORD))
    api.resolve_finding(finding["id"], {"resolution": "LEGALIZE"}, COORD)
    after = get_success_data(api_client.get_finding(finding["id"], COORD))
    assert after["status"] == "FLAGGED"


# ─── Queue A: cross_entity (invoice pay blocked by open dispute) ───────────
def test_invoice_pay_blocked_by_open_dispute(api):
    """PRD §3.7: "Payment requires ownership, or `ERR_UNAUTHORIZED`, and that no
    non-terminal dispute — one in `OPEN`, `UNDER_REVIEW`, or `INFO_REQUESTED` —
    currently references the invoice, or the payment is blocked with
    `ERR_INVOICE_UNDER_DISPUTE`."

    Design: Difficulty/cross_entity_state_dependency/invoice_pay_blocked_by_open_dispute
    """
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    finding = create_finding(pole["id"], attacher["id"], discovered_space_inches=8,
                             discovered_position_inches=150)
    inv_id = finding["penalty_invoice_id"]
    open_dispute_on_invoice(attacher["id"], inv_id, reason="wrong")
    res = api.pay_invoice(inv_id, make_attacher_headers(attacher["id"]))
    validate_error(res, "ERR_INVOICE_UNDER_DISPUTE", expected_status=409)


def test_invoice_under_open_dispute_stays_issued(api):
    """PRD §3.7: "Payment requires ownership, or `ERR_UNAUTHORIZED`, and that no
    non-terminal dispute — one in `OPEN`, `UNDER_REVIEW`, or `INFO_REQUESTED` —
    currently references the invoice, or the payment is blocked with
    `ERR_INVOICE_UNDER_DISPUTE`."

    Design: Difficulty/cross_entity_state_dependency/invoice_pay_blocked_by_open_dispute
    """
    owner = setup_owner(owner_category="ILEC")
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    finding = create_finding(pole["id"], attacher["id"], discovered_space_inches=8,
                             discovered_position_inches=150)
    inv_id = finding["penalty_invoice_id"]
    open_dispute_on_invoice(attacher["id"], inv_id, reason="wrong")
    api.pay_invoice(inv_id, make_attacher_headers(attacher["id"]))
    invoice = get_success_data(api_client.get_invoice(inv_id, COORD))
    assert invoice["status"] == "ISSUED"


# ─── Queue B: validations ──────────────────────────────────────────────────
def test_dispute_subject_neither_invoice_nor_finding_rejected(api):
    """PRD §3.8: "either an `invoice_id` or a `finding_id`, but never both and
    never neither — supplying zero or two subjects is rejected with
    `ERR_DISPUTE_SUBJECT_INVALID`."

    Design: Corner/validations/dispute_subject_neither_invoice_nor_finding_rejected
    """
    attacher = setup_attacher()
    res = api.create_dispute(
        {"attacher_id": attacher["id"], "reason": "no subject"},
        make_attacher_headers(attacher["id"]),
    )
    validate_error(res, "ERR_DISPUTE_SUBJECT_INVALID", expected_status=422)


def test_insufficient_pole_space_over_capacity_rejected(api):
    """PRD §3.3: "the `requested_space_inches` must be no greater than the pole's
    `usable_communication_space_inches` less its `occupied_space_inches` and less
    its `reserved_space_inches`, or `ERR_INSUFFICIENT_POLE_SPACE`".

    Design: Corner/validations/insufficient_pole_space_over_capacity_rejected
    """
    ctx = create_estimate_issued_application(
        pole_overrides={"usable_communication_space_inches": 6},
        app_overrides={"requested_space_inches": 7, "requested_position_inches": 240},
        survey_overrides=_SIMPLE_SURVEY,
    )
    res = api.estimate_decision_application(
        ctx["app"]["id"], {"decision": "ACCEPT"}, make_attacher_headers(ctx["attacher"]["id"])
    )
    validate_error(res, "ERR_INSUFFICIENT_POLE_SPACE", expected_status=409)


def test_credit_limit_exceeded_isolated_rejected(api):
    """PRD §3.3: "and the attacher's `account_balance_cents` plus the
    `make_ready_fee_estimate_cents` must not exceed its `credit_limit_cents`, or
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/credit_limit_exceeded_isolated_rejected
    """
    ctx = create_estimate_issued_application(
        attacher_overrides={"credit_limit_cents": 100},
        survey_overrides=COMPLEX_SURVEY,
    )
    res = api.estimate_decision_application(
        ctx["app"]["id"], {"decision": "ACCEPT"}, make_attacher_headers(ctx["attacher"]["id"])
    )
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=402)
