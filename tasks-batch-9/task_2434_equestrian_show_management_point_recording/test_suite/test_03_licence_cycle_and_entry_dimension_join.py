"""Non-linear lifecycles: the licence loop that escalates to denial, and the two entry dimensions."""

from test_helpers import api_client, validate_error, validate_success
from test_helpers.fixtures import (
    accept_entry,
    build_approved_show,
    build_entry,
    build_show_with_class_list,
    create_horse,
    create_rider,
    decide_license,
    get_class,
    get_class_entry,
    get_entry,
    get_show,
    invoice_entry,
    submit_license,
    verify_entry,
)
from test_helpers.test_users import TEST_USERS, make_exhibitor_headers

TWO_PLANNED_CLASSES = [
    {"class_number": 101, "name": "Open Jumper 1.20m"},
    {"class_number": 102, "name": "Open Jumper 1.10m", "jump_height_cm": 110},
]


def _show_returned_twice():
    """A DRAFT show driven around the correction loop until `revision_count` is 2."""
    ctx = build_show_with_class_list(class_specs=TWO_PLANNED_CLASSES)
    submit_license(ctx["show_id"])
    decide_license(ctx["show_id"], "RETURN", "First cycle.")
    submit_license(ctx["show_id"])
    decide_license(ctx["show_id"], "RETURN", "Second cycle.")
    ctx["show"] = submit_license(ctx["show_id"])
    return ctx


def _divisions(show_id):
    body = api_client.list_show_divisions(show_id, TEST_USERS["show_secretary_headers"]).json()
    return body["data"]


def test_third_return_escalates_the_same_request_to_denial_and_closes_the_prize_list():
    """Two correction cycles leave `revision_count` at 2 with the licence back in SUBMITTED.
    A third RETURN — byte-for-byte the same request that produced RETURNED_FOR_CORRECTION
    twice — now routes to DENIED instead, on the loop counter alone. The denial closes the
    prize list on the way out: the ACTIVE division becomes CLOSED and both PLANNED classes
    become VOIDED.

    PRD §3.1: "When the origin was `RETURNED_FOR_CORRECTION`, the transition `RETURNED_FOR_CORRECTION → SUBMITTED` additionally adds one to `revision_count`; that counter is the loop counter the federation will test on its next return decision."
    PRD §3.1: "While `revision_count` is strictly less than 2, the show moves `SUBMITTED → RETURNED_FOR_CORRECTION`, the supplied `correction_note` is stored against the licence record, and `version` increments."
    PRD §3.1: "Once `revision_count` has reached 2, the federation refuses a third correction cycle outright: the show moves `SUBMITTED → DENIED` instead, with the same consequences as an explicit denial."
    PRD §3.1: "This escalation is automatic and requires no different input from the officer."
    PRD §3.1: "Denial — whether explicit or escalated — closes the prize list: every `CompetitionDivision` of the show whose `status` is `ACTIVE` becomes `CLOSED`, and every class beneath those divisions whose `status` is `PLANNED` becomes `VOIDED`."

    Design: Difficulty/non_linear_state_machine/license_revision_cycle_escalates_to_denied
    """
    ctx = build_show_with_class_list(class_specs=TWO_PLANNED_CLASSES)

    submitted = submit_license(ctx["show_id"])
    assert submitted["license_status"] == "SUBMITTED"
    assert submitted["revision_count"] == 0

    first_return = decide_license(ctx["show_id"], "RETURN", "First cycle.")
    assert first_return["license_status"] == "RETURNED_FOR_CORRECTION"
    assert first_return["revision_count"] == 0

    assert submit_license(ctx["show_id"])["revision_count"] == 1
    second_return = decide_license(ctx["show_id"], "RETURN", "Second cycle.")
    assert second_return["license_status"] == "RETURNED_FOR_CORRECTION"

    resubmitted = submit_license(ctx["show_id"])
    assert resubmitted["license_status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 2

    denied = validate_success(
        api_client.decide_show_license(
            ctx["show_id"],
            {"decision": "RETURN", "correction_note": "Third cycle."},
            TEST_USERS["federation_officer_headers"],
        )
    )

    assert denied["license_status"] == "DENIED"

    divisions = _divisions(ctx["show_id"])
    assert [row["status"] for row in divisions] == ["CLOSED"]
    for class_id in ctx["class_ids"]:
        assert get_class(class_id)["status"] == "VOIDED"


def test_denied_licence_is_terminal_for_both_resubmission_and_a_later_decision():
    """The escalated denial is an exit, not a waypoint. Resubmitting the prize list is refused
    because submission is only accepted from DRAFT or RETURNED_FOR_CORRECTION, and a fresh
    APPROVE decision is refused because every decision requires SUBMITTED. Neither refusal
    moves the licence off DENIED.

    PRD §3.1: "`license_status` moves `DRAFT → SUBMITTED` when the secretary submits the prize list to the federation, and submission is only accepted from `DRAFT` or from `RETURNED_FOR_CORRECTION`; attempting it from `SUBMITTED`, `APPROVED` or `DENIED` yields `ERR_SHOW_LICENSE_NOT_DRAFT`."
    PRD §3.1: "All three require the show to be in `SUBMITTED`; from any other licence state the decision is refused with `ERR_SHOW_LICENSE_NOT_SUBMITTED`."
    PRD §3.1: "`APPROVED` and `DENIED` are terminal licence states."

    Design: Difficulty/non_linear_state_machine/license_revision_cycle_escalates_to_denied
    """
    ctx = _show_returned_twice()
    denied = decide_license(ctx["show_id"], "RETURN", "Third cycle.")
    assert denied["license_status"] == "DENIED"

    validate_error(
        api_client.submit_show_license(ctx["show_id"], TEST_USERS["show_secretary_headers"]),
        "ERR_SHOW_LICENSE_NOT_DRAFT",
        409,
    )
    validate_error(
        api_client.decide_show_license(
            ctx["show_id"], {"decision": "APPROVE"}, TEST_USERS["federation_officer_headers"]
        ),
        "ERR_SHOW_LICENSE_NOT_SUBMITTED",
        409,
    )

    assert get_show(ctx["show_id"])["license_status"] == "DENIED"


def test_money_dimension_reaches_paid_without_confirming_anything():
    """A single class entry at 25000 with no stalls invoices to a 30000-cent total, and the
    exhibitor pays it in full. The settlement dimension has now run to its end, yet the
    paperwork dimension is untouched at RECEIVED and the class entry is still ENTERED with the
    class counting zero confirmed starters. Payment alone confirms nothing.

    PRD §3.5: "An entry pairs one rider with one horse at one show, and it advances along two dimensions that do not wait for each other."
    PRD §3.5: "An entry may be invoiced while still `RECEIVED`, and it may be verified while still `UNBILLED`."
    PRD §3.5: "Payment increments the entry's `version` and, like acceptance, may complete the confirmation join."
    PRD §3.5: "A class entry starts life `ENTERED` and only reaches `CONFIRMED` when *both* entry dimensions have landed: `verification_status` of `ACCEPTED` and `settlement_status` of `PAID`."
    PRD §3.5: "Neither dimension alone confirms anything."

    Design: Difficulty/non_linear_state_machine/entry_parallel_dimensions_join_at_class_entry_confirmed
    """
    ctx = build_approved_show()
    rider = create_rider()
    horse = create_horse()
    row = build_entry(ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]])

    fresh = get_entry(row["entry_id"])
    assert fresh["verification_status"] == "RECEIVED"
    assert fresh["settlement_status"] == "UNBILLED"

    invoiced = invoice_entry(row["entry_id"])
    assert invoiced["settlement_status"] == "INVOICED"
    assert invoiced["verification_status"] == "RECEIVED"
    assert invoiced["total_due_cents"] == 30000

    paid = validate_success(
        api_client.pay_entry(
            row["entry_id"], {"amount_cents": 30000}, make_exhibitor_headers(rider["id"])
        )
    )
    assert paid["settlement_status"] == "PAID"
    assert paid["verification_status"] == "RECEIVED"

    assert get_class_entry(row["class_entry_id"])["status"] == "ENTERED"
    assert get_class(ctx["class_id"])["confirmed_entry_count"] == 0


def test_join_fires_on_whichever_dimension_lands_second():
    """With the money side already PAID, verification carries the paperwork dimension to
    VERIFIED — still not ACCEPTED, so the class entry stays ENTERED. Acceptance is the call
    that completes the pair, and the sweep confirms the class entry and lifts the class's
    confirmed count to one. Because the entry requested no stalls, the join leaves the stall
    ledger at zero, and one confirmed starter is short of the three a class needs to score.

    PRD §3.5: "**Verification.** A `ShowSecretary` verifies an entry, moving `RECEIVED → VERIFIED` and incrementing the entry's `version`."
    PRD §3.5: "**Acceptance.** Accepting a verified entry moves `VERIFIED → ACCEPTED` and is where stalls are actually committed."
    PRD §3.5: "Whichever of acceptance or payment completes the pair sweeps this entry's class entries whose `status` is `ENTERED`, moves each `ENTERED → CONFIRMED`, and recomputes the affected classes' `confirmed_entry_count` and `point_eligible`."
    PRD §3.5: "On success the entry's `assigned_stall_count` is set to its `requested_stall_count`, the show's `reserved_stall_count` and `available_stall_count` are recomputed per the stall ledger of §2.10, and both the entry's and the show's `version` increment."
    PRD §3.8: "The class's `point_eligible` is recomputed as true when its `confirmed_entry_count` is at least 3 and false otherwise."

    Design: Difficulty/non_linear_state_machine/entry_parallel_dimensions_join_at_class_entry_confirmed
    """
    ctx = build_approved_show()
    rider = create_rider()
    horse = create_horse()
    row = build_entry(ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]])
    invoice_entry(row["entry_id"])
    validate_success(
        api_client.pay_entry(
            row["entry_id"], {"amount_cents": 30000}, make_exhibitor_headers(rider["id"])
        )
    )

    verified = verify_entry(row["entry_id"])
    assert verified["verification_status"] == "VERIFIED"
    assert verified["settlement_status"] == "PAID"
    assert get_class_entry(row["class_entry_id"])["status"] == "ENTERED"
    assert get_class(ctx["class_id"])["confirmed_entry_count"] == 0

    accepted = accept_entry(row["entry_id"])
    assert accepted["verification_status"] == "ACCEPTED"

    assert get_class_entry(row["class_entry_id"])["status"] == "CONFIRMED"

    joined = get_class(ctx["class_id"])
    assert joined["confirmed_entry_count"] == 1
    assert joined["entry_count"] == 1
    assert joined["point_eligible"] is False

    assert accepted["assigned_stall_count"] == 0
    assert get_show(ctx["show_id"])["reserved_stall_count"] == 0
