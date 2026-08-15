"""NOC due dates, the clock-driven overdue sweep, and late application."""
from test_helpers import (
    ApiErrorId,
    apply_noc_ok,
    assert_noc_record,
    entry_payload,
    get_success_data,
    make_originator_headers,
    register_noc_ok,
    set_clock,
    setup_settled_file,
    setup_standard_environment,
    validate_error,
)


def test_noc_overdue_sweep_and_late_apply(api, operations_headers):
    """PRD 3.6: "The resulting **NocRecord** is born in `RECEIVED` status with
    `received_at` stamped, `late_applied` false, and `due_date` computed as six
    banking days after the received date; the originator must apply the
    correction by the end of that banking day."
    PRD 2.4: "every notification-of-change record still in `RECEIVED` status
    whose `due_date` falls strictly before that banking day transitions to
    `OVERDUE`."
    PRD 3.6: "from `RECEIVED` the record becomes `APPLIED` outright, while from
    `OVERDUE` it likewise becomes `APPLIED` but with `late_applied` set true to
    record the tardy application; applying an already-`APPLIED` record is
    rejected with `ERR_NOC_NOT_ACTIONABLE`, and a non-owner with
    `ERR_RESOURCE_OWNERSHIP`."

    Design: Corner/state_machines/noc_overdue_sweep_and_late_apply
    """
    org = setup_standard_environment("Noc Co")
    _, _, entries = setup_settled_file(org, [
        entry_payload("DEBIT", 100_000, "nc-1"),
        entry_payload("DEBIT", 200_000, "nc-2"),
    ])
    e1_id, e2_id = entries[0]["id"], entries[1]["id"]

    set_clock("2026-08-03T11:00:00Z")
    n1 = register_noc_ok(e1_id, "C01", "acct=111222333")
    n2 = register_noc_ok(e2_id, "C02", "acct=444555666")

    # Received Monday 2026-08-03; six banking days later is Tuesday 2026-08-11.
    for noc in (n1, n2):
        assert_noc_record(noc)
        assert noc["status"] == "RECEIVED"
        assert noc["due_date"] == "2026-08-11"
        assert noc["late_applied"] is False

    # On-time application (Monday 2026-08-10 is not past the 08-11 due date).
    set_clock("2026-08-10T09:00:00Z")
    applied_n1 = apply_noc_ok(n1["id"], org["id"])
    assert applied_n1["status"] == "APPLIED"
    assert applied_n1["late_applied"] is False

    # The sweep flips N2 to OVERDUE once the banking day passes its due date.
    set_clock("2026-08-12T09:00:00Z")
    swept = get_success_data(api.list_noc_records(e2_id, operations_headers))
    assert swept[0]["id"] == n2["id"]
    assert swept[0]["status"] == "OVERDUE"

    applied_n2 = apply_noc_ok(n2["id"], org["id"])
    assert applied_n2["status"] == "APPLIED"
    assert applied_n2["late_applied"] is True

    # A second application of an already-APPLIED record is rejected.
    res = api.apply_noc(n1["id"], make_originator_headers(org["id"]))
    validate_error(res, ApiErrorId.ERR_NOC_NOT_ACTIONABLE, expected_status=409)
