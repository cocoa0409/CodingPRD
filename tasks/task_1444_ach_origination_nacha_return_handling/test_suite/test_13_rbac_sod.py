"""Role exclusivity, ownership scoping, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    create_active_originator,
    create_warehoused_file,
    define_next_day_window,
    dispatch_batch_ok,
    entry_payload,
    make_finance_headers,
    make_originator_headers,
    read_batch,
    read_file,
    set_clock,
    setup_file_with_entries,
    setup_released_file,
    setup_standard_environment,
    settle_batch_ok,
    validate_error,
    validate_success,
)


def test_originator_ops_cannot_release_file(api):
    """PRD 2.1: "Beyond authentication, every endpoint declares the roles
    permitted to call it; a caller whose role is not in the endpoint's list is
    rejected with `ERR_FORBIDDEN_ROLE`."
    PRD 4: `POST /ach/ach-files/{id}/release` lists OdfiOperations as its only
    authorized role.

    Design: Corner/rbac/originator_ops_cannot_release_file
    """
    org = setup_standard_environment("Rbac Co")
    ach_file = setup_file_with_entries(org, [entry_payload("DEBIT", 100_000, "rb-1")])

    # Even the file's own originator may not release: the role is not listed.
    res = api.release_file(ach_file["id"], make_originator_headers(org["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    assert read_file(ach_file["id"])["status"] == "WAREHOUSED"


def test_finance_cannot_dispatch_and_ops_cannot_reconcile(
        api, operations_headers, finance_headers):
    """PRD 2.1: "Beyond authentication, every endpoint declares the roles
    permitted to call it; a caller whose role is not in the endpoint's list is
    rejected with `ERR_FORBIDDEN_ROLE`."
    PRD 4: `POST /ach/settlement-batches/{id}/advance` authorizes OdfiOperations
    only; `POST /ach/settlement-batches/{id}/reconcile` authorizes OdfiFinance
    only.

    Design: Corner/rbac/finance_cannot_dispatch_and_ops_cannot_reconcile
    """
    org = setup_standard_environment("Sod Co")
    _, batch_id = setup_released_file(org, [entry_payload("DEBIT", 100_000, "sd-1")])

    res = api.advance_batch(batch_id, {"action": "DISPATCH"}, finance_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    assert read_batch(batch_id)["status"] == "OPEN"

    dispatch_batch_ok(batch_id)
    settle_batch_ok(batch_id)

    res = api.reconcile_batch(batch_id, operations_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    assert read_batch(batch_id)["status"] == "SETTLED"


def test_same_user_cannot_dispatch_and_reconcile(api):
    """PRD 3.5: "Segregation of duties is enforced: the reconciler's `X-User-ID`
    must differ from the recorded `dispatched_by_user_id`, otherwise
    `ERR_SOD_VIOLATION`."
    PRD 3.5: "A successful reconcile moves the batch to `RECONCILED` and records
    the caller as `reconciled_by_user_id`, which stays unset until that moment."

    Design: Corner/rbac/sod_same_user_cannot_dispatch_and_reconcile
    """
    org = setup_standard_environment("SoD2 Co")
    _, batch_id = setup_released_file(org, [entry_payload("DEBIT", 100_000, "s2-1")])
    dispatch_batch_ok(batch_id, user_id="ops-9")
    settle_batch_ok(batch_id, user_id="ops-9")

    # Same individual operator, even in the finance role: rejected.
    res = api.reconcile_batch(batch_id, make_finance_headers("ops-9"))
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

    reconciled = validate_success(
        api.reconcile_batch(batch_id, make_finance_headers("fin-7")), 200)
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["reconciled_by_user_id"] == "fin-7"


def test_originator_cannot_cancel_another_originators_file(
        api, operations_headers):
    """PRD 2.1: "When `X-User-Role` is `OriginatorOps`, `X-User-ID` is the `id`
    of the acting Originator; ownership checks on any resource that references
    an Originator compare the resource's originator linkage — a file's own
    originator reference, an entry's through its file, a NOC's or reversal's
    through its entry and that entry's file — to `X-User-ID`, and a mismatch is
    rejected with `ERR_RESOURCE_OWNERSHIP`."

    Design: Corner/rbac/originator_b_cannot_cancel_originator_a_file
    """
    org_a = create_active_originator("Own A", ["CCD"])
    org_b = create_active_originator("Own B", ["CCD"])
    set_clock("2026-08-03T10:00:00Z")
    define_next_day_window()
    file_a = create_warehoused_file(org_a, "CCD", "NEXT_DAY", "2026-08-03")

    res = api.cancel_file(file_a["id"], make_originator_headers(org_b["id"]))
    validate_error(res, ApiErrorId.ERR_RESOURCE_OWNERSHIP, expected_status=403)
    assert read_file(file_a["id"])["status"] == "WAREHOUSED"
