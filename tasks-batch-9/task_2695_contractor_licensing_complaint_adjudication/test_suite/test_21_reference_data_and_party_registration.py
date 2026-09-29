"""Reference data and party registration corners.

Covers the write surface the board opens before anything can be licensed: the
statutory trade classification and the fiscal-year appropriation, the derived
obligation counters that hang off a registered party, and the immutable
examination event log recorded against a qualifying individual. The concern
these tests share is what the server itself owns — the success envelope, the
server-minted identity and clock stamps, the computed counters a client may not
dictate, and the money-typing discipline every payload must respect.
"""

from test_helpers import (
    ExamType,
    assert_common_fields,
    assert_exam_result,
    assert_fields,
    assert_qualifying_individual,
    factories as F,
    fixtures as X,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_trade_classification_echoes_every_declared_field(api, board_admin_headers):
    """Creating a classification answers 201 and echoes the statutory parameters.

    "Endpoints that bring a new resource into existence answer with HTTP 201;
    every other successful operation — state transitions, decisions, sweeps,
    reads and lists — answers with HTTP 200."

    Design: Corner/entities/corner_create_trade_classification_returns_declared_fields_in_the_success_envelope
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")

    payload = {
        "code": "C-10",
        "name": "Electrical",
        "hazard_tier": 3,
        "min_experience_months": 48,
        "min_net_worth_cents": 250000,
        "required_bond_amount_cents": 1500000,
        "required_ce_hours": 8,
        "renewal_base_fee_cents": 45000,
        "mediation_required": True,
    }
    response = api.create_trade_classification(payload, board_admin_headers)
    created = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource answers response_type object, got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"], "meta.api_request_id must be present and non-empty"
    assert body["meta"]["api_request_timestamp"], (
        "meta.api_request_timestamp must be present and non-empty"
    )

    assert_common_fields(created)
    assert_fields(
        created,
        {
            "code": "C-10",
            "hazard_tier": 3,
            "min_experience_months": 48,
            "required_bond_amount_cents": 1500000,
            "renewal_base_fee_cents": 45000,
            "mediation_required": True,
        },
    )


def test_fund_account_balance_sent_as_a_json_string_is_rejected(api, board_admin_headers):
    """An appropriation whose money field arrives as a string is a schema violation.

    "They must be transmitted as JSON integers, never as decimal strings; a
    money field arriving as `"45000"` rather than `45000` is a schema violation
    and draws `ERR_INVALID_REQUEST`, as does a negative amount."

    Design: Corner/entities/corner_money_fields_supplied_as_json_strings_are_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")

    payload = F.fund_account_payload(initial_balance_cents="5000000")
    validate_error(
        api.create_fund_account(payload, board_admin_headers), "ERR_INVALID_REQUEST"
    )


def test_qualification_count_is_derived_and_ignores_the_declared_value(
    api, licensing_analyst_headers
):
    """A freshly registered qualifier holds no designations, whatever the payload claims.

    "A derived `active_qualification_count`, initialised to zero, tracks how
    many designations that person currently holds in `ACTIVE` status; it is the
    number the concurrent-qualification cap is measured against, and §2.8
    describes the cascade rules that move it."

    Design: Corner/entities/corner_active_qualification_count_is_computed_with_client_input_ignored
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")

    payload = {
        "full_name": "Cal Computed",
        "verified_experience_months": 60,
        "active_qualification_count": 7,
    }
    created = validate_success(
        api.create_qualifying_individual(payload, licensing_analyst_headers),
        expected_status=201,
    )
    assert created["active_qualification_count"] == 0, (
        "a qualifier holding no designations reads 0, got "
        f"{created['active_qualification_count']}"
    )

    stored = validate_success(
        api.get_qualifying_individual(created["id"], licensing_analyst_headers)
    )
    assert_qualifying_individual(
        stored, active_qualification_count=0, verified_experience_months=60
    )


def test_exam_result_identity_and_timestamp_come_from_the_server(
    api, licensing_analyst_headers
):
    """A sitting is stamped by the server, not by the client that reports it.

    "- `id` (string): a server-minted UUID. It carries no type prefix of any
    kind."

    "Creation timestamps, licence issuance dates, application submission
    timestamps, hearing decision timestamps, disbursement dates and the date
    stamped by a compliance sweep all derive from it."

    Design: Corner/entities/corner_exam_result_system_fields_stamped_with_client_input_ignored
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    individual = X.register_qualifying_individual(
        api, full_name="Sy Stem", verified_experience_months=60
    )

    payload = {
        "exam_type": "LAW_AND_BUSINESS",
        "score": 88,
        "taken_on": "2025-03-01",
        "id": "11111111-1111-4111-8111-111111111111",
        "created_at": "1999-01-01T00:00:00Z",
    }
    recorded = validate_success(
        api.create_exam_result(individual["id"], payload, licensing_analyst_headers),
        expected_status=201,
    )
    assert recorded["id"] != "11111111-1111-4111-8111-111111111111", (
        "the server mints its own identifier and discards the supplied one"
    )
    assert recorded["created_at"] == "2026-08-01T00:00:00.000Z", (
        f"created_at must be read from the clock, got {recorded['created_at']!r}"
    )

    rows, _ = validate_paginated(
        api.list_exam_results(individual["id"], licensing_analyst_headers)
    )
    stored = next(row for row in rows if row["id"] == recorded["id"])
    assert_exam_result(
        stored,
        qualifying_individual_id=individual["id"],
        taken_on="2025-03-01",
    )


def test_a_second_sitting_is_a_new_row_rather_than_an_edit(
    api, licensing_analyst_headers
):
    """Re-sitting an examination adds a row; the failed sitting stays on the record.

    "An `ExamResult` is an immutable event-log row hanging off a qualifying
    individual, and it carries **only** `id` and `created_at`."

    "`passed` is true when the `score` is at least 70; a score of exactly 70
    passes."

    Design: Corner/entities/corner_exam_result_is_immutable_with_no_version_field
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    individual = X.register_qualifying_individual(
        api, full_name="Ima Mutable", verified_experience_months=60
    )
    first = X.record_exam(
        api,
        individual["id"],
        ExamType.TRADE,
        trade_code="C-10",
        score=69,
        taken_on="2025-03-01",
    )

    second = validate_success(
        api.create_exam_result(
            individual["id"],
            F.trade_exam_payload("C-10", score=88, taken_on="2025-09-01"),
            licensing_analyst_headers,
        ),
        expected_status=201,
    )
    assert second["id"] != first["id"], (
        "a re-sitting must be written as its own row, not an edit of the first"
    )

    rows, meta = validate_paginated(
        api.list_exam_results(
            individual["id"], licensing_analyst_headers, {"exam_type": "TRADE"}
        )
    )
    assert meta["total_count"] == 2, (
        f"both sittings must survive, got total_count {meta['total_count']}"
    )
    stored_first = next(row for row in rows if row["id"] == first["id"])
    stored_second = next(row for row in rows if row["id"] == second["id"])
    assert_exam_result(stored_first, score=69, passed=False)
    assert_exam_result(stored_second, score=88, passed=True)


def test_recording_a_sitting_against_an_unknown_qualifier_is_not_found(
    api, licensing_analyst_headers
):
    """The parent in the path is resolved first, so an unknown qualifier is a 404.

    "When a path names a parent and then a child — a qualifying individual and
    then its examination records, for instance — the parent is resolved first,
    and a missing parent produces the parent's own not-found error before the
    child is ever looked for."

    Design: Corner/entities/corner_exam_result_requires_an_existing_qualifying_individual_parent
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    individual = X.register_qualifying_individual(
        api, full_name="Pat Parent", verified_experience_months=60
    )

    validate_error(
        api.create_exam_result(
            "22222222-2222-4222-8222-222222222222",
            F.law_and_business_exam_payload(score=88, taken_on="2025-03-01"),
            licensing_analyst_headers,
        ),
        "ERR_QUALIFYING_INDIVIDUAL_NOT_FOUND",
    )

    _, meta = validate_paginated(
        api.list_exam_results(individual["id"], licensing_analyst_headers)
    )
    assert meta["total_count"] == 0, (
        f"the real qualifier's history must stay empty, got {meta['total_count']} rows"
    )
