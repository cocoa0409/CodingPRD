"""What a failure looks like on the wire, and which transport each family travels on."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_error_payload_is_bare,
    assert_fields,
    assert_ids_exactly,
    assert_meta_envelope,
    assert_page,
)

REFUSED_WELL_NUMBER = "49-001-20002"


def test_a_refused_call_answers_with_a_bare_error_and_writes_no_row(api):
    """A failure carries an identifier and a message, and never a half-built row.

    The missing-row read and the schema-violating create both answer with the error
    envelope and the same correlation metadata a success carries, and the refused create
    mints nothing: the operator still holds exactly the one well it started with.

    PRD: "The `error_id` is a unique, machine-readable string that identifies the specific
    error." ... "The `message` provides a human-readable explanation of what went wrong."
    ... "the total measured depth `total_depth_ft` (which must be strictly greater than
    zero)"

    Design: Corner/errors/error_responses_carry_the_error_envelope_and_persist_nothing
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=5000000,
    )
    well = fx.make_well(api, operator["id"])

    missing = api.get_well("w_does_not_exist", users.ADMIN)
    validate_error(missing, e.ERR_WELL_NOT_FOUND, 404)
    assert_error_payload_is_bare(missing)
    assert_meta_envelope(missing)

    refused = api.create_well(
        f.well_payload(
            operator["id"], api_well_number=REFUSED_WELL_NUMBER, total_depth_ft=0
        ),
        users.INSPECTOR,
    )
    validate_error(refused, e.ERR_INVALID_REQUEST, 422)
    assert_error_payload_is_bare(refused)
    assert_meta_envelope(refused)

    survivors = assert_page(
        api.list_wells(users.ADMIN, {"operator_id": operator["id"]}), 1, expected_total=1
    )
    assert_ids_exactly(survivors, [well["id"]])
    assert REFUSED_WELL_NUMBER not in [row["api_well_number"] for row in survivors], (
        "the refused create minted a well after all: %r" % (survivors,)
    )


def test_the_three_failure_families_travel_on_their_own_http_statuses(api):
    """A missing row, an undeclared edge and a schema violation are three transports.

    The same endpoint answers 409 when the action is declared but is not an edge out of
    `DRAFT`, and 422 when the action is not a declared value at all, so the two failures
    never collapse onto one status; the solicitation is left untouched by all three calls.

    PRD: "Closing is available only from `OPEN` and moves the row `OPEN → EVALUATING`,
    after which no further bids are accepted." ... "The new solicitation's `status` is
    `DRAFT`, its `reopen_round` is 0" ... "Advance a solicitation: OPEN it for bidding,
    CLOSE it for evaluation, REOPEN it once for more bids, or CANCEL it."

    Design: Corner/errors/each_error_family_answers_with_its_declared_http_status
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=5000000,
    )
    fx.make_well(api, operator["id"])
    solicitation = fx.make_solicitation(api)
    assert_fields(solicitation, status="DRAFT", reopen_round=0, version=1)

    validate_error(
        api.get_solicitation("sol_missing", users.PROCUREMENT),
        e.ERR_SOLICITATION_NOT_FOUND,
        404,
    )

    wrong_edge = api.solicitation_lifecycle(
        solicitation["id"], f.lifecycle_payload("CLOSE"), users.PROCUREMENT
    )
    validate_error(wrong_edge, e.ERR_INVALID_STATE_TRANSITION, 409)

    undeclared = api.solicitation_lifecycle(
        solicitation["id"], f.lifecycle_payload("ARCHIVE"), users.PROCUREMENT
    )
    validate_error(undeclared, e.ERR_INVALID_REQUEST, 422)

    assert wrong_edge.status_code != undeclared.status_code, (
        "the undeclared edge and the undeclared action must not share one status"
    )

    after = fx.read_solicitation(api, solicitation["id"])
    assert_fields(after, status="DRAFT", reopen_round=0, version=1)
