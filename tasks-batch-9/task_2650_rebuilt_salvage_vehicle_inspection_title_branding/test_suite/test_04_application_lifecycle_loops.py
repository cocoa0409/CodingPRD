"""Backwards and sideways moves in the program's lifecycles.

Two machines in this program are deliberately non-linear. The documentation
review can walk a submitted application backwards to the initial `DRAFT` state
while the escrowed program charge stays exactly where it is, and a title row
carries two lifecycle dimensions at once so that the interstate-recognition
dimension can move while the row's own `status` never leaves `ACTIVE`.
"""

from test_helpers import (
    api_client,
    create_recognition_request_payload,
    decide_recognition_request,
    decide_recognition_request_payload,
    docs_review_payload,
    make_program_admin_headers,
    make_rebuilder_headers,
    make_state_title_clerk_headers,
    read_application,
    read_rebuilder,
    read_title,
    review_documentation,
    setup_rebuilt_title_issued,
    setup_salvage_titled_vehicle,
    setup_submitted_application,
    submit_application_payload,
    submit_recognition_request,
    validate_success,
)

api = api_client
CLERK_HEADERS = make_state_title_clerk_headers()

# The bare SEDAN package escrows the base application fee plus the one-off
# structural surcharge, and nothing else.
EXPECTED_ESCROW_CENTS = 20_000
EXPECTED_DEPOSIT_CENTS = 500_000
EXPECTED_BALANCE_AFTER_ESCROW_CENTS = 480_000


def _submitted_and_opened_for_review() -> dict:
    """A complete SEDAN package submitted and then opened for documentation review."""
    env = setup_submitted_application()
    opened = review_documentation(env["application_id"], "OPEN")
    assert opened["status"] == "DOCS_UNDER_REVIEW", (
        f"expected DOCS_UNDER_REVIEW before the return, got {opened['status']}"
    )
    return env


def test_returning_the_documentation_package_loops_the_application_back_to_draft():
    """A clerk's return for correction walks the application back to DRAFT.

    PRD: "A decision of `RETURN` sends a `DOCS_UNDER_REVIEW` application back to `DRAFT` so the rebuilder can file corrected paperwork; the note is recorded and, as §3.6 states, `fee_escrowed_cents` is retained in full — a return for correction is not a refund."

    Design: Difficulty/non_linear_state_machine/docs_review_return_loops_application_back_to_draft_with_escrow_retained
    """
    env = _submitted_and_opened_for_review()

    response = api.review_application_docs(
        env["application_id"],
        docs_review_payload("RETURN", review_note="photograph of the VIN plate is illegible"),
        CLERK_HEADERS,
    )
    returned = validate_success(response, expected_status=200)

    assert returned["status"] == "DRAFT", (
        f"expected DRAFT after the RETURN decision, got {returned['status']}"
    )
    assert returned["attempts_completed"] == 0, (
        f"expected 0 completed attempts after a return, got {returned['attempts_completed']}"
    )
    persisted = read_application(env["application_id"])
    assert persisted["status"] == "DRAFT", (
        f"expected the stored application to read DRAFT, got {persisted['status']}"
    )


def test_a_returned_package_keeps_the_program_charge_in_escrow():
    """A return for correction disposes of no money at all.

    PRD: "And a return of the documentation package for correction disposes of nothing: the escrow is retained in full, with no refund and no capture."

    Design: Difficulty/non_linear_state_machine/docs_review_return_loops_application_back_to_draft_with_escrow_retained
    """
    env = _submitted_and_opened_for_review()
    before = read_rebuilder(env["rebuilder_id"])
    assert before["fee_balance_cents"] == EXPECTED_BALANCE_AFTER_ESCROW_CENTS, (
        f"expected {EXPECTED_BALANCE_AFTER_ESCROW_CENTS} on deposit less escrow, "
        f"got {before['fee_balance_cents']} before the return"
    )

    review_documentation(
        env["application_id"], "RETURN", review_note="photograph of the VIN plate is illegible"
    )

    application = read_application(env["application_id"])
    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert application["fee_escrowed_cents"] == EXPECTED_ESCROW_CENTS, (
        f"expected the escrow retained at {EXPECTED_ESCROW_CENTS}, "
        f"got {application['fee_escrowed_cents']} after the return"
    )
    assert rebuilder["escrowed_fee_total_cents"] == EXPECTED_ESCROW_CENTS, (
        f"expected escrowed_fee_total_cents {EXPECTED_ESCROW_CENTS}, "
        f"got {rebuilder['escrowed_fee_total_cents']} after the return"
    )
    assert rebuilder["fee_balance_cents"] == EXPECTED_BALANCE_AFTER_ESCROW_CENTS, (
        f"a return is not a refund, so fee_balance_cents must stay at "
        f"{EXPECTED_BALANCE_AFTER_ESCROW_CENTS}, got {rebuilder['fee_balance_cents']}"
    )
    assert rebuilder["fees_consumed_cents"] == 0, (
        f"a return is not a capture, so fees_consumed_cents must stay 0, "
        f"got {rebuilder['fees_consumed_cents']}"
    )
    assert rebuilder["fees_deposited_cents"] == EXPECTED_DEPOSIT_CENTS, (
        f"expected fees_deposited_cents {EXPECTED_DEPOSIT_CENTS}, "
        f"got {rebuilder['fees_deposited_cents']}"
    )


def test_a_returned_application_can_be_submitted_a_second_time():
    """The corrected package re-enters the workflow through the same submit door.

    PRD: "It then sets `fee_escrowed_cents` equal to the freshly computed `total_program_charge_cents`, raises the rebuilder's `escrowed_fee_total_cents` by that charge, lowers the rebuilder's `fee_balance_cents` by the same charge, and moves the application `DRAFT → SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/docs_review_return_loops_application_back_to_draft_with_escrow_retained
    """
    env = _submitted_and_opened_for_review()
    review_documentation(
        env["application_id"], "RETURN", review_note="photograph of the VIN plate is illegible"
    )

    response = api.submit_application(
        env["application_id"],
        submit_application_payload(),
        make_rebuilder_headers(env["rebuilder_id"]),
    )
    resubmitted = validate_success(response, expected_status=200)

    assert resubmitted["status"] == "SUBMITTED", (
        f"expected SUBMITTED on the second submission, got {resubmitted['status']}"
    )
    assert resubmitted["assessed_fee_cents"] == EXPECTED_ESCROW_CENTS, (
        f"expected assessed_fee_cents {EXPECTED_ESCROW_CENTS}, "
        f"got {resubmitted['assessed_fee_cents']} on the second submission"
    )
    assert resubmitted["fee_escrowed_cents"] == EXPECTED_ESCROW_CENTS, (
        f"expected fee_escrowed_cents equal to the freshly computed charge "
        f"{EXPECTED_ESCROW_CENTS}, got {resubmitted['fee_escrowed_cents']}"
    )


def test_submitting_a_salvage_title_for_recognition_moves_only_the_recognition_dimension():
    """Offering a branded title to another state opens the second dimension.

    PRD: "A successful submission creates the request in `PENDING`, snapshots the title's `brand_code` into `submitted_brand_code`, leaves `mapped_brand_code`, `outcome` and `decided_at` null, moves any prior request for the same title that was still `PENDING` to `SUPERSEDED`, drives the title's `recognition_state` to `RECOGNITION_PENDING`, and increments the title's `version` by 1."

    Design: Difficulty/non_linear_state_machine/title_recognition_dimension_moves_while_status_stays_active
    """
    env = setup_salvage_titled_vehicle()
    salvage_title = env["salvage_title"]
    assert salvage_title["recognition_state"] == "NOT_SUBMITTED", (
        f"a freshly minted title has not been offered to anyone, "
        f"got {salvage_title['recognition_state']}"
    )

    response = api.create_recognition_request(
        create_recognition_request_payload(
            salvage_title["id"], salvage_title["version"], requesting_state_code="AZ"
        ),
        CLERK_HEADERS,
    )
    request = validate_success(response, expected_status=201)

    assert request["status"] == "PENDING", (
        f"expected the request to open in PENDING, got {request['status']}"
    )
    assert request["submitted_brand_code"] == "SALVAGE", (
        f"expected the snapshot brand SALVAGE, got {request['submitted_brand_code']}"
    )
    assert request["mapped_brand_code"] is None, (
        f"mapped_brand_code stays null until the state answers, got {request['mapped_brand_code']}"
    )
    assert request["outcome"] is None, (
        f"outcome stays null until the state answers, got {request['outcome']}"
    )
    assert request["decided_at"] is None, (
        f"decided_at stays null until the state answers, got {request['decided_at']}"
    )

    title = read_title(salvage_title["id"])
    assert title["recognition_state"] == "RECOGNITION_PENDING", (
        f"expected recognition_state RECOGNITION_PENDING, got {title['recognition_state']}"
    )
    assert title["version"] == salvage_title["version"] + 1, (
        f"expected the title version to move from {salvage_title['version']} to "
        f"{salvage_title['version'] + 1}, got {title['version']}"
    )
    assert title["status"] == "ACTIVE", (
        f"the row's own status must not move on a recognition submission, got {title['status']}"
    )
    assert title["is_current"] is True, (
        f"is_current must stay true while the row is ACTIVE, got {title['is_current']}"
    )


def test_a_state_that_carries_no_brand_records_a_rejected_outcome():
    """A jurisdiction refusing to carry any brand answers with a rejection.

    PRD: "The `outcome` follows mechanically from the comparison: it is `RECOGNIZED` when `mapped_brand_code` equals `submitted_brand_code`; it is `DOWNGRADED` when the mapped brand's severity is strictly lower than the submitted brand's but still above zero; and it is `REJECTED` when `mapped_brand_code` is `NONE`, meaning the state refuses to carry any brand at all."

    Design: Difficulty/non_linear_state_machine/title_recognition_dimension_moves_while_status_stays_active
    """
    env = setup_salvage_titled_vehicle()
    salvage_title = env["salvage_title"]
    request = submit_recognition_request(
        salvage_title["id"], salvage_title["version"], requesting_state_code="AZ"
    )

    response = api.decide_recognition_request(
        request["id"],
        decide_recognition_request_payload(
            "NONE", decision_note="AZ recognises no equivalent brand"
        ),
        make_program_admin_headers(),
    )
    decided = validate_success(response, expected_status=200)

    assert decided["status"] == "DECIDED", (
        f"expected the request to reach DECIDED, got {decided['status']}"
    )
    assert decided["mapped_brand_code"] == "NONE", (
        f"expected the mapped brand NONE to be recorded, got {decided['mapped_brand_code']}"
    )
    assert decided["outcome"] == "REJECTED", (
        f"a mapped brand of NONE is a refusal to carry any brand, so the outcome must be "
        f"REJECTED, got {decided['outcome']}"
    )
    assert decided["submitted_brand_code"] == "SALVAGE", (
        f"the submitted snapshot must survive the decision, got {decided['submitted_brand_code']}"
    )
    assert decided["decided_at"] is not None, "decided_at must be stamped on the decision"


def test_a_refused_brand_downgrades_the_recognition_state_while_the_title_stays_active():
    """The recognition dimension moves on its own; the title row does not.

    PRD: "The title's second dimension follows the outcome asymmetrically: `recognition_state` becomes `RECOGNIZED` when the outcome is `RECOGNIZED`, and becomes `DOWNGRADED` when the outcome is either `DOWNGRADED` or `REJECTED`."

    Design: Difficulty/non_linear_state_machine/title_recognition_dimension_moves_while_status_stays_active
    """
    env = setup_salvage_titled_vehicle()
    salvage_title = env["salvage_title"]
    request = submit_recognition_request(
        salvage_title["id"], salvage_title["version"], requesting_state_code="AZ"
    )
    decide_recognition_request(
        request["id"], "NONE", decision_note="AZ recognises no equivalent brand"
    )

    title = read_title(salvage_title["id"])
    assert title["recognition_state"] == "DOWNGRADED", (
        f"a REJECTED outcome drives recognition_state to DOWNGRADED, "
        f"got {title['recognition_state']}"
    )
    assert title["status"] == "ACTIVE", (
        f"the title's own lifecycle must not move on a foreign decision, got {title['status']}"
    )
    assert title["is_current"] is True, (
        f"expected is_current to stay true, got {title['is_current']}"
    )
    assert title["brand_code"] == "SALVAGE", (
        f"the home state's brand is untouched by the foreign answer, got {title['brand_code']}"
    )
    assert title["brand_severity"] == 30, (
        f"expected the SALVAGE severity 30 to survive, got {title['brand_severity']}"
    )


def test_a_foreign_downgrade_of_a_rebuilt_brand_leaves_the_row_active_and_current():
    """A softer foreign brand mapping moves one dimension of the row only.

    PRD: "A title record carries two lifecycle dimensions on the same row, and they evolve independently of one another."

    Design: Difficulty/non_linear_state_machine/title_recognition_dimension_moves_while_status_stays_active
    """
    env = setup_rebuilt_title_issued()
    rebuilt_title = env["rebuilt_title"]
    assert rebuilt_title["brand_code"] == "REBUILT", (
        f"expected the rebuilt instrument to carry REBUILT, got {rebuilt_title['brand_code']}"
    )
    request = submit_recognition_request(
        rebuilt_title["id"], rebuilt_title["version"], requesting_state_code="AZ"
    )

    decided = decide_recognition_request(
        request["id"], "SALVAGE", decision_note="AZ maps a rebuilt instrument onto salvage"
    )
    assert decided["outcome"] == "DOWNGRADED", (
        f"SALVAGE is strictly less severe than REBUILT, so the outcome must be DOWNGRADED, "
        f"got {decided['outcome']}"
    )

    title = read_title(rebuilt_title["id"])
    assert title["recognition_state"] == "DOWNGRADED", (
        f"expected recognition_state DOWNGRADED, got {title['recognition_state']}"
    )
    assert title["status"] == "ACTIVE", (
        f"the row's status dimension must stay ACTIVE, got {title['status']}"
    )
    assert title["is_current"] is True, (
        f"expected is_current to stay true, got {title['is_current']}"
    )
    assert title["brand_code"] == "REBUILT", (
        f"a foreign downgrade never rewrites the home brand, got {title['brand_code']}"
    )
