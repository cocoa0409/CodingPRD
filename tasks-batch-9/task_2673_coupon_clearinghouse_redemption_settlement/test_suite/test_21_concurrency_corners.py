"""Version tokens that a successful write of the same endpoint invalidated.

Two optimistic-concurrency rules over disjoint endpoints and disjoint parent
entities: one where nothing but the token stands in the way of a second write,
and one whose successful write changes no value at all yet still advances.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST,
    OFFICER,
    FeeTier,
    IntakeStatus,
    RetailerStatus,
    StatementStatus,
    api_errors as err,
    assert_fields,
    assert_millis_timestamp,
    assert_money,
    assert_rate_equals,
    assert_statement_waterfall,
)


def test_01_statement_issue_refuses_the_token_its_own_write_consumed(
        api, build):
    """One issue, one 412, then the refreshed token issues a second statement.

    "If that value does not equal the submission's current `version`, the
    request is rejected with `ERR_STALE_SUBMISSION_VERSION` (HTTP 412)."

    "Note that a successful issuance itself increments `Submission.version` by 1,
    so a client that wants to issue twice must re-read the submission in between."

    "A closed submission may legitimately receive a fresh statement that
    supersedes an earlier `DRAFT` one, which is exactly why the stale-version check
    rather than a state guard is what protects the operation."

    Design: Corner/cross_cutting_complexity_layers/statement_issue_refuses_a_submission_version_token_that_has_advanced
    """
    world = build.market()
    settled = build.settled_submission(world)
    submission_id = settled["submission_id"]

    before = validate_success(api.get_submission(submission_id, OFFICER))
    assert_fields(before, {"intake_status": IntakeStatus.CLOSED})
    assert_money(before, "settled_gross_face_value_cents", 50)
    first_token = before["version"]

    first = validate_success(
        api.issue_statement(submission_id, first_token, OFFICER), 201)
    assert_fields(first, {"status": StatementStatus.DRAFT})
    assert_statement_waterfall(first, gross=50, fee_total=7, offset=0,
                               provisional_net=57, holdback_pct="0.00",
                               holdback=0, net_payable=57)

    replay = api.issue_statement(submission_id, first_token, OFFICER)
    validate_error(replay, err.ERR_STALE_SUBMISSION_VERSION,
                   expected_status=412)

    rows, meta = validate_paginated(api.list_statements(
        OFFICER, submission_id=submission_id, limit=10))
    assert meta["total_count"] == 1, (
        "the refused issue wrote no statement at all"
    )
    assert rows[0]["id"] == first["id"]

    after = validate_success(api.get_submission(submission_id, OFFICER))
    assert after["version"] == first_token + 1, (
        "the one successful issue bumped the version once, and the refused call "
        f"did not bump it again, expected {first_token + 1}, got "
        f"{after['version']}"
    )

    superseding = validate_success(
        api.issue_statement(submission_id, after["version"], OFFICER), 201)
    assert_fields(superseding, {"status": StatementStatus.DRAFT})
    assert_money(superseding, "net_payable_cents", 57)
    assert superseding["id"] != first["id"]

    both, both_meta = validate_paginated(api.list_statements(
        OFFICER, submission_id=submission_id, limit=10))
    assert both_meta["total_count"] == 2, (
        "the identical body with the refreshed token was accepted, so the 412 "
        "was the token and not a state precondition"
    )
    for row in both:
        assert_fields(row, {"status": StatementStatus.DRAFT})
        assert_money(row, "net_payable_cents", 57)


def test_02_fraud_rescore_advances_the_version_even_when_no_score_moves(
        api, build):
    """An idempotent rescore still consumes its token, and the replay is a 412.

    "If that value does not equal the retailer's current `version`, the request
    is rejected with `ERR_STALE_RETAILER_VERSION` (HTTP 412)."

    "A rescore is idempotent under unchanged data and carries no state
    precondition, so nothing else prevents an analyst from writing a score derived
    from a retailer snapshot that a submission-close cascade has already
    superseded."

    "Either way the computation is identical and it always writes
    `last_rescored_at` from the logical clock."

    Design: Corner/cross_cutting_complexity_layers/fraud_rescore_refuses_a_retailer_version_token_that_has_advanced
    """
    world = build.market()
    build.settled_submission(world)
    retailer_id = world["retailer_id"]

    before = validate_success(api.get_retailer(retailer_id, ANALYST))
    first_token = before["version"]

    scored = validate_success(
        api.fraud_rescore(retailer_id, first_token, ANALYST))
    assert_fields(scored, {
        "status": RetailerStatus.ACTIVE,
        "handling_fee_tier": scored["base_fee_tier"],
        "rejected_submission_count": 0,
    })
    assert_fields(scored, {"base_fee_tier": FeeTier.STANDARD})
    for field in ("duplicate_rate", "misredemption_rate", "counterfeit_rate",
                  "fraud_score", "fraud_score_rolling_window",
                  "fraud_score_lifetime_weighted"):
        assert_rate_equals(scored[field], "0.00", field)
    assert_millis_timestamp(scored["last_rescored_at"], "last_rescored_at")
    assert scored["last_rescored_at"].startswith("2026-08-01"), (
        "the stamp is taken from the logical clock, which still reads "
        "2026-08-01"
    )
    assert scored["version"] == first_token + 1, (
        "the successful rescore advances the version even though no score field "
        f"changed value, expected {first_token + 1}, got {scored['version']}"
    )

    replay = api.fraud_rescore(retailer_id, first_token, ANALYST)
    validate_error(replay, err.ERR_STALE_RETAILER_VERSION, expected_status=412)

    unchanged = validate_success(api.get_retailer(retailer_id, ANALYST))
    assert unchanged["version"] == first_token + 1, (
        "the refused rescore neither bumped the version a second time nor "
        f"rewrote anything, expected {first_token + 1}, got "
        f"{unchanged['version']}"
    )
    assert unchanged["last_rescored_at"] == scored["last_rescored_at"], (
        "the refused rescore did not rewrite last_rescored_at"
    )

    again = validate_success(
        api.fraud_rescore(retailer_id, unchanged["version"], ANALYST))
    assert again["version"] == unchanged["version"] + 1, (
        "the refreshed token is accepted and advances the version once more"
    )
    assert_rate_equals(again["fraud_score"], "0.00", "fraud_score")
