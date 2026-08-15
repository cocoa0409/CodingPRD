"""Return registration gates, re-presentment rules, and the bounded cycle."""
from test_helpers import (
    ApiErrorId,
    assert_ach_entry,
    assert_return_case,
    close_entry_ok,
    entry_payload,
    get_success_data,
    list_file_entries,
    read_entry,
    register_return_ok,
    represent_ok,
    setup_file_with_entries,
    setup_settled_file,
    setup_standard_environment,
    validate_error,
    validate_success,
)


def test_return_with_unknown_code_rejected(api, operations_headers):
    """PRD 3.6: "Only entries in `SETTLED` accept a return registration — from
    `WAREHOUSED`, `TRANSMITTED`, `CLOSED`, or `CANCELLED` the attempt is
    rejected with `ERR_ENTRY_NOT_SETTLED` — and the code must be one of `R01`,
    `R02`, `R05`, `R07`, or `R10`, with anything else rejected as
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/return_with_unknown_code_returns_invalid_request
    """
    org = setup_standard_environment("Enum Co")
    _, _, entries = setup_settled_file(org, [entry_payload("DEBIT", 100_000, "en-1")])
    entry = entries[0]

    res = api.register_return(entry["id"], {"return_code": "R99"},
                              operations_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    assert read_entry(entry["id"])["status"] == "SETTLED"
    cases = get_success_data(api.list_return_cases(entry["id"], operations_headers))
    assert cases == [], "a rejected registration must not persist a ReturnCase"


def test_return_on_warehoused_entry_rejected(api, operations_headers):
    """PRD 3.6: "Only entries in `SETTLED` accept a return registration — from
    `WAREHOUSED`, `TRANSMITTED`, `CLOSED`, or `CANCELLED` the attempt is
    rejected with `ERR_ENTRY_NOT_SETTLED`"

    Design: Corner/state_machines/return_on_warehoused_entry_returns_invalid_state
    """
    org = setup_standard_environment("Ware Co")
    ach_file = setup_file_with_entries(org, [entry_payload("DEBIT", 100_000, "wh-1")])
    entry = list_file_entries(ach_file["id"])[0]
    assert entry["status"] == "WAREHOUSED"

    res = api.register_return(entry["id"], {"return_code": "R01"},
                              operations_headers)
    validate_error(res, ApiErrorId.ERR_ENTRY_NOT_SETTLED, expected_status=409)
    assert read_entry(entry["id"])["status"] == "WAREHOUSED"


def test_represent_settled_entry_rejected(api, operations_headers):
    """PRD 3.6: "An `OdfiOperations` operator may re-present only an entry in
    `RETURNED` status (otherwise `ERR_ENTRY_NOT_RETURNED`)"

    Design: Corner/state_machines/represent_settled_entry_returns_invalid_state
    """
    org = setup_standard_environment("Rep Co")
    _, _, entries = setup_settled_file(org, [entry_payload("DEBIT", 100_000, "rp-1")])
    entry = entries[0]

    res = api.represent_entry(entry["id"], operations_headers)
    validate_error(res, ApiErrorId.ERR_ENTRY_NOT_RETURNED, expected_status=409)
    assert read_entry(entry["id"])["representment_count"] == 0


def test_represent_non_r01_return_prohibited(api, operations_headers):
    """PRD 3.6: "only when the entry's `last_return_code` is `R01` —
    insufficient-funds returns are the sole re-presentable kind, and any other
    code is rejected with `ERR_REPRESENTMENT_CODE_PROHIBITED`"
    PRD 3.6: "The entry itself moves to `RETURNED` for every return code —
    there is no code-specific bypass — its `last_return_code` records the code,
    and the only exits from `RETURNED` are re-presentment and closure."

    Design: Corner/state_machines/represent_r02_return_returns_code_prohibited
    """
    org = setup_standard_environment("R02 Co")
    _, _, entries = setup_settled_file(org, [entry_payload("DEBIT", 100_000, "r2-1")])
    entry = entries[0]
    case = register_return_ok(entry["id"], "R02")

    res = api.represent_entry(entry["id"], operations_headers)
    validate_error(res, ApiErrorId.ERR_REPRESENTMENT_CODE_PROHIBITED,
                   expected_status=422)

    # Non-R01 codes do not auto-close: the entry rests in RETURNED.
    rested = read_entry(entry["id"])
    assert rested["status"] == "RETURNED"
    assert rested["last_return_code"] == "R02"
    cases = get_success_data(api.list_return_cases(entry["id"], operations_headers))
    assert cases[0]["id"] == case["id"]
    assert cases[0]["disposition"] == "OPEN"


def test_return_on_closed_entry_rejected(api, operations_headers):
    """PRD 3.6: "Only entries in `SETTLED` accept a return registration — from
    `WAREHOUSED`, `TRANSMITTED`, `CLOSED`, or `CANCELLED` the attempt is
    rejected with `ERR_ENTRY_NOT_SETTLED`"
    PRD 3.6: "Closing moves the entry to the terminal `CLOSED` status and moves
    any `OPEN` ReturnCase on the entry to its terminal `FINAL` disposition."

    Design: Corner/state_machines/return_on_closed_entry_terminal_lockdown
    """
    org = setup_standard_environment("Close Co")
    _, _, entries = setup_settled_file(org, [entry_payload("DEBIT", 100_000, "cl-1")])
    entry = entries[0]
    closed = close_entry_ok(entry["id"], org["id"])
    assert closed["status"] == "CLOSED"

    res = api.register_return(entry["id"], {"return_code": "R01"},
                              operations_headers)
    validate_error(res, ApiErrorId.ERR_ENTRY_NOT_SETTLED, expected_status=409)
    assert read_entry(entry["id"])["status"] == "CLOSED"


def _setup_two_completed_cycles():
    """Entry X (DEBIT 2000000) run through two full SETTLED -> RETURNED ->
    TRANSMITTED -> SETTLED cycles, then returned R01 a third time.

    Helper files F2 and F3 supply the later batch settles that re-settle X via
    the originator-scoped re-flow sweep (PRD 3.5).
    Returns (org, x_id).
    """
    org = setup_standard_environment("Zeta LLC", exposure_limit_cents=100_000_000)
    _, _, entries = setup_settled_file(org, [entry_payload("DEBIT", 2_000_000, "z-x")])
    x_id = entries[0]["id"]

    for amount, account in ((700_000, "z-y"), (500_000, "z-z")):
        register_return_ok(x_id, "R01")
        represent_ok(x_id)
        # The helper file's batch settle sweeps the re-presented X to SETTLED.
        setup_settled_file(org, [entry_payload("DEBIT", amount, account)])

    register_return_ok(x_id, "R01")  # third return; X rests in RETURNED
    return org, x_id


class TestRepresentmentCycleExhaustion:
    def test_third_representment_rejected_at_cap(self, api, operations_headers):
        """PRD 3.6: "only while the entry's `representment_count` is still below
        the hard cap of two, with the attempt at a count of exactly two rejected
        as `ERR_REPRESENTMENT_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/ach_entry_representment_cycle_exhaustion
        """
        _, x_id = _setup_two_completed_cycles()
        assert read_entry(x_id)["representment_count"] == 2

        res = api.represent_entry(x_id, operations_headers)
        validate_error(res, ApiErrorId.ERR_REPRESENTMENT_EXHAUSTED,
                       expected_status=422)

        after = read_entry(x_id)
        assert_ach_entry(after)
        assert after["representment_count"] == 2
        assert after["status"] == "RETURNED"

    def test_close_after_exhaustion_finalizes_open_case(self, api,
                                                        operations_headers):
        """PRD 3.6: "A successful re-presentment increments
        `representment_count` by one, marks the entry's `OPEN` ReturnCase as
        `REPRESENTED` (a terminal disposition), and moves the entry itself back
        to `TRANSMITTED`"
        PRD 3.6: "Closing moves the entry to the terminal `CLOSED` status and
        moves any `OPEN` ReturnCase on the entry to its terminal `FINAL`
        disposition."

        Design: Difficulty/non_linear_state_machine/ach_entry_representment_cycle_exhaustion
        """
        org, x_id = _setup_two_completed_cycles()

        closed = close_entry_ok(x_id, org["id"])
        assert closed["status"] == "CLOSED"

        cases = get_success_data(api.list_return_cases(x_id, operations_headers))
        assert len(cases) == 3
        for case in cases:
            assert_return_case(case)
        # Listings are created_at ascending (insertion order, PRD 2.3).
        assert [c["disposition"] for c in cases] == [
            "REPRESENTED", "REPRESENTED", "FINAL"]
        assert [c["representment_number"] for c in cases] == [0, 1, 2]
