"""Standing up a plan, a participant, an account and its valuation history.

Covers the response envelope, the declared defaults, the server-owned computed
and system fields, the append-only records, the by-id reads of every root
collection and the pagination contract of the list endpoints.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_success,
)

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_append_only_resource,
    assert_envelope_meta,
    assert_error_envelope,
    assert_list_response,
    assert_plan_account_figures,
    assert_single_resource,
    assert_versioned_resource,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS
from test_helpers.types import (
    CODE_AP_IDENTIFICATION_INCOMPLETE,
    CODE_MISSING_MODEL_LANGUAGE,
    DRAFT_UNDER_REVIEW,
    EMPLOYMENT_ACTIVE,
    EMPLOYMENT_TERMINATED,
    HOLD_HELD,
    ORIGIN_SYSTEM,
    PROCEDURES_DRAFT,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_HELD,
    SNAPSHOT_MANUAL_ADJUSTMENT,
    SOURCE_AFTER_TAX,
    SOURCE_LOAN_RECEIVABLE,
    SOURCE_PRE_TAX_DEFERRAL,
    TEMPLATE_DEFICIENCY_NOTICE,
    TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
)


def test_plan_registration_returns_its_declared_defaults_in_an_object_envelope(client):
    """A registration answers 201 with the whole plan nested under `data`.

    PRD: "Every plan is registered with `procedures_status` set to `DRAFT` and
    `participant_count` initialised to 0."

    Design: Corner/entities/plan_creation_returns_declared_defaults_inside_response_envelope
    """
    payload = factories.plan_payload(plan_name="Envelope Plan")
    response = client.create_plan(payload, ADMIN_HEADERS)

    data = assert_single_resource(response, 201)
    body = response.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}, (
        f"the envelope carries exactly meta, response_type and data: {body.keys()}"
    )
    assert_envelope_meta(body)
    assert data["procedures_status"] == PROCEDURES_DRAFT
    assert data["participant_count"] == 0
    assert_versioned_resource(data, expected_version=1)
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])

    # The submitted terms are echoed unmodified, arrays in the submitted order.
    assert data["plan_name"] == "Envelope Plan"
    assert data["plan_type"] == payload["plan_type"]
    assert data["model_language_version"] == payload["model_language_version"]
    assert data["acceptable_formula_codes"] == payload["acceptable_formula_codes"]
    assert data["allowed_approaches"] == payload["allowed_approaches"]

    reread = assert_single_resource(client.get_plan(data["id"], ADMIN_HEADERS))
    assert reread == data, "the by-id read returns the identical field set"


def test_omitted_optional_inputs_materialise_their_declared_defaults(client):
    """Every optional input lands on the row as its declared default.

    PRD: "`max_assignable_pct_bps` defaults to 5000 basis points — half the
    assignable base — and may be set anywhere from 1 to 10000."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    plan = fixtures.create_plan(client, plan_name="Default Plan")
    assert plan["requires_model_language"] is True
    assert plan["permits_benefit_not_otherwise_available"] is False
    assert plan["review_period_days"] == constants.DEFAULT_REVIEW_PERIOD_DAYS
    assert plan["segregation_period_days"] == constants.DEFAULT_SEGREGATION_PERIOD_DAYS
    assert plan["resubmission_window_days"] == constants.DEFAULT_RESUBMISSION_WINDOW_DAYS
    assert plan["max_revisions"] == constants.DEFAULT_MAX_REVISIONS
    assert plan["max_assignable_pct_bps"] == constants.DEFAULT_MAX_ASSIGNABLE_PCT_BPS
    assert (
        plan["max_assignable_amount_cents"]
        == constants.DEFAULT_MAX_ASSIGNABLE_AMOUNT_CENTS
    )

    fixtures.set_procedures(client, plan["id"], "PUBLISHED")
    participant = fixtures.enroll_participant(client, plan["id"])
    assert participant["employment_status"] == EMPLOYMENT_ACTIVE
    assert participant["benefit_commenced"] is False

    account = fixtures.open_plan_account(client, participant["id"])
    assert account["monthly_payment_cents"] == 0

    source = fixtures.add_money_source(
        client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
    )
    assert source["basis_cents"] == 0
    assert source["is_assignable"] is True

    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case_payload = factories.omit(
        factories.qdro_case_payload(
            participant["id"],
            alternate_payee_name="Chidi Okonkwo",
            valuation_date="2026-06-30",
            marital_period_start="2012-03-01",
        ),
        "marital_period_end",
        "alternate_payee_dob",
        "alternate_payee_address_on_file",
    )
    case = validate_success(
        client.create_qdro_case(case_payload, ANALYST_HEADERS), 201
    )
    assert case["marital_period_end"] is None, (
        "the marital window is unbounded forward, not coerced to a date"
    )
    assert case["alternate_payee_address_on_file"] is False

    draft = fixtures.receive_draft(
        client, case["id"], case["version"], document_reference="DRO-2663-DEF"
    )
    assert draft["provisions"] == []
    assert draft["revision_number"] == 1
    assert draft["attorney_authorization_id"] is None
    assert draft["reviewed_by_user_id"] is None
    assert draft["denial_reason"] is None

    # The defaults are load-bearing: the 548-day window and the 5000 bps ceiling
    # are both visible on the hold the receipt placed.
    hold = fixtures.hold_for_case(client, case["id"])
    assert hold["expires_at"] == "2028-03-02T00:00:00Z"
    assert hold["hold_amount_cents"] == 400000
    assert draft["deficiency_codes"] == [CODE_AP_IDENTIFICATION_INCOMPLETE], (
        "the defaulted address flag is itself a deficiency"
    )


def test_derived_balances_and_participant_count_are_server_owned(client):
    """Computed figures are derived from the rows that feed them, never supplied.

    PRD: "On a freshly opened account with no money sources and no holds, all
    five figures are zero."

    Design: Corner/entities/computed_and_system_fields_are_server_owned
    """
    plan = fixtures.create_plan(
        client, plan_name="Computed Plan", review_period_days=45
    )
    assert plan["participant_count"] == 0
    fixtures.set_procedures(client, plan["id"], "PUBLISHED")
    participant = fixtures.enroll_participant(client, plan["id"])
    account = fixtures.open_plan_account(client, participant["id"])
    assert_plan_account_figures(
        account,
        vested_balance_cents=0,
        assignable_base_cents=0,
        after_tax_basis_cents=0,
        held_amount_cents=0,
        available_balance_cents=0,
    )

    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    fixtures.add_money_source(
        client, account["id"], SOURCE_AFTER_TAX, 100000, basis_cents=60000
    )
    fixtures.add_money_source(
        client,
        account["id"],
        SOURCE_LOAN_RECEIVABLE,
        300000,
        basis_cents=0,
        is_assignable=False,
    )
    account = fixtures.read_plan_account(client, account["id"])
    assert_plan_account_figures(
        account,
        vested_balance_cents=400000,
        assignable_base_cents=100000,
        after_tax_basis_cents=60000,
        held_amount_cents=0,
        available_balance_cents=400000,
    )
    assert fixtures.read_plan_account(client, account["id"])["id"] == account["id"]
    reread_plan = validate_success(client.get_plan(plan["id"], ADMIN_HEADERS))
    assert reread_plan["participant_count"] == 1, "the count is a live derivation"

    case = fixtures.open_case(client, participant["id"])
    draft = fixtures.receive_draft(
        client, case["id"], case["version"], document_reference="DRO-2663-CMP"
    )
    assert draft["deficiency_codes"] == []
    assert draft["received_at"] == constants.CLOCK_2026_09_01
    assert draft["review_deadline_at"] == "2026-10-16T00:00:00Z", (
        "the receipt instant advanced by the plan's 45-day review period"
    )

    account = fixtures.read_plan_account(client, account["id"])
    assert_plan_account_figures(
        account, held_amount_cents=40000, available_balance_cents=360000
    )
    reread_draft = fixtures.read_draft(client, draft["id"])
    assert reread_draft["review_deadline_at"] == draft["review_deadline_at"]
    assert reread_draft["deficiency_codes"] == draft["deficiency_codes"]


def test_system_stamps_and_sequences_come_from_the_logical_clock(client):
    """Timestamps read the injectable clock and sequences are server-assigned.

    PRD: "a `notice_sequence` equal to the count of notices already on that
    draft order plus one"

    Design: Corner/entities/system_fields_are_generated_and_stamped_from_the_logical_clock
    """
    setup = fixtures.setup_plan_account(
        client,
        "Clock Plan",
        fixtures.SINGLE_SOURCE,
        plan_overrides={"requires_model_language": True},
    )
    clock = fixtures.set_clock(client, "2026-09-10T00:00:00Z")
    assert clock["current_utc"] == "2026-09-10T00:00:00Z"

    case = fixtures.open_case(client, setup["participant"]["id"])
    draft = fixtures.receive_draft(
        client,
        case["id"],
        case["version"],
        document_reference="DRO-2663-SYS",
        uses_model_language=False,
    )
    assert draft["received_at"] == "2026-09-10T00:00:00Z"
    assert draft["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]

    hold = fixtures.hold_for_case(client, case["id"])
    assert hold["placed_at"] == "2026-09-10T00:00:00Z"
    assert hold["expires_at"] == "2028-03-11T00:00:00Z", (
        "placement advanced by the plan's 548 whole days"
    )

    first = fixtures.issue_notice(client, draft["id"], reviewer_notes="first notice")
    assert first["notice_sequence"] == 1
    assert first["issued_at"] == "2026-09-10T00:00:00Z"
    assert first["resubmission_deadline_at"] == "2026-11-09T00:00:00Z"

    fixtures.set_clock(client, constants.CLOCK_2026_09_20)
    fixtures.resubmit(
        client,
        draft["id"],
        headers=fixtures.participant_headers(setup["participant"]),
        document_reference="DRO-2663-SYS-r2",
        uses_model_language=False,
    )
    second = fixtures.issue_notice(client, draft["id"], reviewer_notes="second notice")
    assert second["notice_sequence"] == 2, "the sequence counts within one draft order"
    assert second["issued_at"] == constants.CLOCK_2026_09_20
    assert second["resubmission_deadline_at"] == "2026-11-19T00:00:00Z", (
        "each notice's window runs from its own issuance"
    )

    reread = fixtures.read_draft(client, draft["id"])
    assert reread["received_at"] == "2026-09-10T00:00:00Z", (
        "the first receipt instant is never restamped"
    )
    assert reread["revision_number"] == 2

    receipts = fixtures.read_communications(
        client, case["id"], template_code=TEMPLATE_RECEIPT_ACKNOWLEDGMENT
    )
    assert [row["sent_at"] for row in receipts] == ["2026-09-10T00:00:00Z"]
    notices = fixtures.read_communications(
        client, case["id"], template_code=TEMPLATE_DEFICIENCY_NOTICE
    )
    assert [row["sent_at"] for row in notices] == [
        "2026-09-10T00:00:00Z",
        "2026-09-10T00:00:00Z",
        constants.CLOCK_2026_09_20,
        constants.CLOCK_2026_09_20,
    ]


def test_append_only_records_expose_no_version_and_no_mutator(client):
    """Valuation, reporting and correspondence rows are evidence, not state.

    PRD: "for `ValuationSnapshot`, `TaxReport`, and `Communication`, both
    `updated_at` and `version` are absent from the resource entirely."

    Design: Corner/entities/immutable_entities_expose_no_version_and_no_mutator
    """
    setup = fixtures.setup_plan_account(
        client,
        "Immutable Plan",
        fixtures.SINGLE_SOURCE,
        snapshots=(("2026-06-30", 1000000),),
    )
    account_version = setup["account"]["version"]
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case = fixtures.open_case(client, setup["participant"]["id"])
    draft = fixtures.receive_draft(
        client, case["id"], case["version"], document_reference="DRO-2663-IMM"
    )

    snapshots = validate_success(
        client.list_valuation_snapshots(
            setup["account"]["id"], ADMIN_HEADERS, {"as_of_date": "2026-06-30"}
        )
    )
    assert len(snapshots) == 1
    assert_append_only_resource(snapshots[0], "ValuationSnapshot")
    assert snapshots[0]["balance_cents"] == 1000000

    receipts = fixtures.read_communications(
        client, case["id"], template_code=TEMPLATE_RECEIPT_ACKNOWLEDGMENT
    )
    assert len(receipts) == 1
    assert_append_only_resource(receipts[0], "Communication")
    assert receipts[0]["origin"] == ORIGIN_SYSTEM
    assert receipts[0]["sent_at"] == constants.CLOCK_2026_09_01

    duplicate = client.create_valuation_snapshot(
        setup["account"]["id"],
        factories.valuation_snapshot_payload(
            "2026-06-30", 9999999, source=SNAPSHOT_MANUAL_ADJUSTMENT
        ),
        ADMIN_HEADERS,
    )
    assert_error_envelope(duplicate, api_errors.ERR_SNAPSHOT_DUPLICATE, 409)
    unchanged = validate_success(
        client.list_valuation_snapshots(setup["account"]["id"], ADMIN_HEADERS)
    )
    assert [row["balance_cents"] for row in unchanged] == [1000000], (
        "an in-place correction is impossible, even by re-posting the same date"
    )

    # The mutable neighbours do carry the pair the append-only rows omit.
    assert_versioned_resource(setup["account"], expected_version=account_version)
    assert_versioned_resource(draft, expected_version=1)
    assert fixtures.read_case(client, case["id"])["version"] == 2


def test_every_root_collection_echoes_its_stored_row(client):
    """Each root collection reads back the persisted row, cascades included.

    PRD: "Reverse-reachability list endpoints are the *only* discovery channel
    for rows this system creates by cascade rather than by client request."

    Design: Corner/entities/single_resource_reads_echo_stored_state_for_every_root_collection
    """
    setup = fixtures.setup_plan_account(
        client,
        "Readback Plan",
        fixtures.SINGLE_SOURCE,
        participant_overrides={
            "full_name": "Hanne Vos",
            "participation_start_date": "2005-06-01",
        },
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case = fixtures.open_case(client, setup["participant"]["id"])
    draft = fixtures.receive_draft(
        client,
        case["id"],
        case["version"],
        document_reference="DRO-2663-READ",
        proposed_percentage_bps=3000,
    )
    hold = fixtures.hold_for_case(client, case["id"])

    plan_row = assert_single_resource(
        client.get_plan(setup["plan"]["id"], ADMIN_HEADERS)
    )
    participant_row = assert_single_resource(
        client.get_participant(setup["participant"]["id"], ADMIN_HEADERS)
    )
    account_row = assert_single_resource(
        client.get_plan_account(setup["account"]["id"], ADMIN_HEADERS)
    )
    case_row = assert_single_resource(client.get_qdro_case(case["id"], ADMIN_HEADERS))
    draft_row = assert_single_resource(
        client.get_draft_order(draft["id"], ANALYST_HEADERS)
    )
    hold_row = assert_single_resource(
        client.get_segregation_hold(hold["id"], ADMIN_HEADERS)
    )

    assert plan_row["plan_name"] == "Readback Plan"
    assert participant_row["plan_id"] == setup["plan"]["id"]
    assert participant_row["participation_start_date"] == "2005-06-01"
    assert account_row["participant_id"] == setup["participant"]["id"]
    assert account_row["vested_balance_cents"] == 1000000
    assert case_row["review_status"] == REVIEW_UNDER_REVIEW
    assert case_row["segregation_status"] == SEGREGATION_HELD
    assert draft_row["qdro_case_id"] == case["id"]
    assert draft_row["proposed_percentage_bps"] == 3000

    # The hold has no POST of its own, so this read is the only proof the
    # cascade persisted a row bound to both branches of the topology.
    assert hold_row["id"] == hold["id"]
    assert hold_row["qdro_case_id"] == case["id"]
    assert hold_row["plan_account_id"] == setup["account"]["id"]
    assert hold_row["hold_amount_cents"] == 300000
    assert hold_row["status"] == HOLD_HELD


def test_list_endpoints_paginate_and_filter_within_declared_bounds(client):
    """Lists report the filtered total and refuse an out-of-range page size.

    PRD: "`limit` controls page size: its default is 10, its minimum accepted
    value is 1, and its maximum accepted value is 100."

    Design: Corner/entities/list_endpoints_paginate_and_filter_with_declared_bounds
    """
    plan = fixtures.create_published_plan(client, plan_name="Paging Plan")
    first = fixtures.enroll_participant(
        client, plan["id"], full_name="P One", ssn_last4="0001"
    )
    second = fixtures.enroll_participant(
        client, plan["id"], full_name="P Two", ssn_last4="0002"
    )
    third = fixtures.enroll_participant(
        client,
        plan["id"],
        full_name="P Three",
        ssn_last4="0003",
        employment_status=EMPLOYMENT_TERMINATED,
    )
    for participant, balance in ((first, 1000000), (second, 500000)):
        account = fixtures.open_plan_account(client, participant["id"])
        fixtures.add_money_source(
            client, account["id"], SOURCE_PRE_TAX_DEFERRAL, balance
        )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    for participant, bps in ((first, 3000), (second, 2000)):
        case = fixtures.open_case(client, participant["id"])
        fixtures.receive_draft(
            client, case["id"], case["version"], proposed_percentage_bps=bps
        )

    rows, meta = assert_list_response(
        client.list_plan_participants(plan["id"], ADMIN_HEADERS)
    )
    assert meta["limit"] == constants.DEFAULT_LIMIT
    assert meta["offset"] == constants.MIN_OFFSET
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 3

    rows, meta = assert_list_response(
        client.list_plan_participants(plan["id"], ADMIN_HEADERS, {"limit": 2})
    )
    assert (meta["total_count"], meta["has_more"], len(rows)) == (3, True, 2)

    rows, meta = assert_list_response(
        client.list_plan_participants(
            plan["id"], ADMIN_HEADERS, {"limit": 2, "offset": 2}
        )
    )
    assert (meta["total_count"], meta["has_more"], meta["offset"], len(rows)) == (
        3,
        False,
        2,
        1,
    )

    rows, meta = assert_list_response(
        client.list_plan_participants(
            plan["id"], ADMIN_HEADERS, {"limit": 2, "offset": 3}
        )
    )
    assert (meta["total_count"], meta["has_more"], len(rows)) == (3, False, 0), (
        "an offset beyond the total is an empty page, not a refusal"
    )

    rows, meta = assert_list_response(
        client.list_plan_participants(
            plan["id"], ADMIN_HEADERS, {"employment_status": EMPLOYMENT_TERMINATED}
        )
    )
    assert (meta["total_count"], meta["has_more"], len(rows)) == (1, False, 1)
    assert rows[0]["id"] == third["id"], "the total counts the filtered set"

    rows, meta = assert_list_response(
        client.list_draft_orders(
            ADMIN_HEADERS, {"status": DRAFT_UNDER_REVIEW, "limit": 1}
        )
    )
    assert (meta["total_count"], meta["has_more"], len(rows)) == (2, True, 1)

    for bad_limit in (constants.MAX_LIMIT + 1, constants.MIN_LIMIT - 1):
        refusal = client.list_plan_participants(
            plan["id"], ADMIN_HEADERS, {"limit": bad_limit}
        )
        assert_error_envelope(refusal, api_errors.ERR_INVALID_REQUEST, 400)
