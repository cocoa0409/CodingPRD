"""Data export/deletion branches, the grace-window temporal boundary, the
delete-then-cancel compensation, purge-in-progress precedence, and the
purge-finalize cascade.

Covers queue A (non_linear_state_machine download/delete, boundary_precision
grace purge, compensating_invariant delete-then-cancel, priority_pair
purge-in-progress) and queue B (state_machines purge-finalize cascade,
derived_field_reconciliation pet_count).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_pet,
    setup_delete_request_in_grace,
)
from test_helpers.fixtures import set_clock
from test_helpers.factories import (
    create_data_request_payload,
)
from test_helpers.test_users import make_account_headers

ADMIN = TEST_USERS["platform_admin_headers"]


# =========================================================================
# non_linear_state_machine: download vs delete branch divergence (queue A)
# =========================================================================

def test_download_request_advances_to_ready_with_payload(api):
    """PRD §3.8: "A `DOWNLOAD` request auto-advances from `PENDING` to `READY` on
    creation, assembling an `export_payload` bundle from the account's pets,
    reports, and matches; for a download the `grace_until` is null."

    Design: Difficulty/non_linear_state_machine/data_request_download_vs_delete_branch_divergent_effects
    """
    set_clock("2026-05-01T00:00:00Z")
    account = create_account()
    create_pet(account["id"])
    acct_h = make_account_headers(account["id"])

    resp = api.create_data_request(
        create_data_request_payload(account["id"], kind="DOWNLOAD"), acct_h
    )
    dr = validate_success(resp, expected_status=201)
    assert dr["status"] == "READY", f"DOWNLOAD must be READY, got {dr['status']}"
    assert dr["export_payload"] is not None, "DOWNLOAD must assemble export_payload"


def test_delete_request_opens_grace_and_freezes_account(api):
    """PRD §3.8: "A `DELETE` request instead opens a cool-off: it advances from
    `PENDING` to `GRACE`, sets `grace_until` to the current logical clock plus 30
    days, sets the account's `purge_pending` to true, and leaves `export_payload`
    null."
    PRD §3.8: "Cancelling a deletion during the cool-off rescinds it, moving the
    request from `GRACE` to `CANCELLED`, clearing the account's `purge_pending`
    back to false, and incrementing the request's `version`."

    Design: Difficulty/non_linear_state_machine/data_request_download_vs_delete_branch_divergent_effects
    """
    set_clock("2026-05-01T00:00:00Z")
    account = create_account()
    create_pet(account["id"])
    acct_h = make_account_headers(account["id"])

    resp = api.create_data_request(
        create_data_request_payload(account["id"], kind="DELETE"), acct_h
    )
    dr = validate_success(resp, expected_status=201)
    assert dr["status"] == "GRACE", f"DELETE must be GRACE, got {dr['status']}"
    assert dr["grace_until"] == "2026-05-31T00:00:00.000Z", \
        f"grace_until must be clock+30d, got {dr['grace_until']}"

    acct = validate_success(api.get_account(account["id"], acct_h))
    assert acct["purge_pending"] is True, "purge_pending must be true during DELETE GRACE"

    # Cancel restores purge_pending=false.
    cancelled = validate_success(api.cancel_data_request(dr["id"], acct_h))
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    acct2 = validate_success(api.get_account(account["id"], acct_h))
    assert acct2["purge_pending"] is False, "purge_pending must be false after cancel"


# =========================================================================
# boundary_precision: grace window >= grace_until on purge (queue A)
# =========================================================================

def test_purge_one_day_before_grace_until_rejected(api):
    """PRD §3.8: "once the logical clock reaches or passes `grace_until`, a
    platform operator may advance the deletion from `GRACE` to `PURGING`,
    incrementing its `version`; a purge requested before the clock reaches
    `grace_until` is rejected with `ERR_GRACE_NOT_ELAPSED`."

    Design: Difficulty/boundary_precision_check/grace_window_ge_boundary_on_data_request_purge
    """
    set_clock("2026-05-01T00:00:00Z")
    account = create_account()
    acct_h = make_account_headers(account["id"])
    dr = get_success_data(
        api.create_data_request(create_data_request_payload(account["id"], kind="DELETE"), acct_h)
    )
    set_clock("2026-05-30T00:00:00Z")  # one day before grace_until 2026-05-31

    resp = api.purge_data_request(dr["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_GRACE_NOT_ELAPSED.value)


def test_purge_one_day_before_grace_until_leaves_grace(api):
    """PRD §3.8: "a purge requested before the clock reaches `grace_until` is
    rejected with `ERR_GRACE_NOT_ELAPSED`."

    Design: Difficulty/boundary_precision_check/grace_window_ge_boundary_on_data_request_purge
    """
    set_clock("2026-05-01T00:00:00Z")
    account = create_account()
    acct_h = make_account_headers(account["id"])
    dr = get_success_data(
        api.create_data_request(create_data_request_payload(account["id"], kind="DELETE"), acct_h)
    )
    set_clock("2026-05-30T00:00:00Z")
    api.purge_data_request(dr["id"], ADMIN)

    fetched = validate_success(api.get_data_request(dr["id"], acct_h))
    assert fetched["status"] == "GRACE", f"request must stay GRACE, got {fetched['status']}"


# =========================================================================
# compensating_invariant: delete-then-cancel conserves pet_count (queue A)
# =========================================================================

def test_delete_then_cancel_conserves_pet_count(api):
    """PRD §3.8: "Cancelling a deletion during the cool-off rescinds it, moving
    the request from `GRACE` to `CANCELLED`, clearing the account's
    `purge_pending` back to false, and incrementing the request's `version`."
    PRD §3.1: "Its `pet_count` is the number of the account's pets whose status
    is not `ARCHIVED`."

    Design: Difficulty/compensating_invariant/delete_then_cancel_conserves_account_pet_count
    """
    base = setup_delete_request_in_grace(clock="2026-05-01T00:00:00Z", num_pets=2)
    acct_h = make_account_headers(base["account"]["id"])

    api.cancel_data_request(base["data_request"]["id"], acct_h)
    account = validate_success(api.get_account(base["account"]["id"], acct_h))
    assert account["pet_count"] == 2, \
        f"pet_count must be conserved at 2, got {account['pet_count']}"
    assert account["purge_pending"] is False, "purge_pending must be false after cancel"


def test_delete_then_cancel_sets_request_cancelled(api):
    """PRD §3.8: "Cancelling a deletion during the cool-off rescinds it, moving
    the request from `GRACE` to `CANCELLED`"

    Design: Difficulty/compensating_invariant/delete_then_cancel_conserves_account_pet_count
    """
    base = setup_delete_request_in_grace(clock="2026-05-01T00:00:00Z", num_pets=2)
    acct_h = make_account_headers(base["account"]["id"])

    cancelled = validate_success(api.cancel_data_request(base["data_request"]["id"], acct_h))
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"


# NOTE: The difficulty instance
# priority_pair_validation_conflict/purge_in_progress_beats_invalid_state_on_kit_activate
# is SKIPPED. PRD §2.8 fixes the order so that the state check
# (ERR_INVALID_STATE, the fifth framework check) is evaluated BEFORE the
# purge-in-progress freeze (a later business rule). A faithful PRD-only
# implementer activating an already-ACTIVATED kit under a pending deletion
# would therefore return ERR_INVALID_STATE, not ERR_PURGE_IN_PROGRESS. The
# instance's asserted precedence is the reverse of the PRD prose, so it fails
# unique derivability and is not translated (error-precedence silence pattern).


# =========================================================================
# not_resource_owner beats invalid_state on report revoke (queue A)
# =========================================================================

def test_nonowner_revoke_revoked_report_returns_not_resource_owner(api):
    """PRD §2.8: "fourth, ownership — that the acting account owns the targeted
    resource (`ERR_NOT_RESOURCE_OWNER`); fifth, that the target resource is in a
    state from which the requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/not_resource_owner_beats_invalid_state_on_report_revoke
    """
    from test_helpers.fixtures import setup_preliminary_report
    base = setup_preliminary_report(product_tier="BREED")
    owner_h = make_account_headers(base["account"]["id"])
    # Owner revokes the report -> now REVOKED.
    api.revoke_report(base["report"]["id"], owner_h)

    # A different account (account B) attempts to revoke the already-REVOKED report.
    other = create_account()
    other_h = make_account_headers(other["id"])
    resp = api.revoke_report(base["report"]["id"], other_h)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_nonowner_revoke_revoked_report_status_403(api):
    """PRD §2.8: "fourth, ownership — that the acting account owns the targeted
    resource (`ERR_NOT_RESOURCE_OWNER`)"
    PRD §5: the catalogue maps `ERR_NOT_RESOURCE_OWNER` to HTTP 403.

    Design: Difficulty/priority_pair_validation_conflict/not_resource_owner_beats_invalid_state_on_report_revoke
    """
    from test_helpers.fixtures import setup_preliminary_report
    base = setup_preliminary_report(product_tier="BREED")
    owner_h = make_account_headers(base["account"]["id"])
    api.revoke_report(base["report"]["id"], owner_h)

    other = create_account()
    other_h = make_account_headers(other["id"])
    resp = api.revoke_report(base["report"]["id"], other_h)
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}"


# =========================================================================
# Corner: purge-finalize cascade (state_machines)
# =========================================================================

def test_purge_finalize_archives_pets_and_clears_purge_pending(api):
    """PRD §3.8: "The purge-finalize is the irreversible cascade: every pet on the
    account is archived (each moving from `REGISTERED` to `ARCHIVED`, decrementing
    the account's `pet_count` and incrementing each pet's `version`)"
    PRD §3.8: "The cascade also clears the account's `purge_pending` to false and
    increments the request's `version`."

    Design: Corner/state_machines/purge_finalize_cascades_pet_archival_and_match_withdrawal
    """
    set_clock("2026-05-01T00:00:00Z")
    account = create_account()
    pet = create_pet(account["id"], name="Arch")
    acct_h = make_account_headers(account["id"])
    dr = get_success_data(
        api.create_data_request(create_data_request_payload(account["id"], kind="DELETE"), acct_h)
    )
    set_clock("2026-05-31T00:00:00Z")
    get_success_data(api.purge_data_request(dr["id"], ADMIN))  # GRACE -> PURGING

    resp = api.purge_finalize_data_request(dr["id"], ADMIN)
    finalized = validate_success(resp)
    assert finalized["status"] == "PURGED", f"expected PURGED, got {finalized['status']}"

    fetched_pet = validate_success(api.get_pet(pet["id"], ADMIN))
    assert fetched_pet["status"] == "ARCHIVED", f"pet must be ARCHIVED, got {fetched_pet['status']}"

    fetched_acct = validate_success(api.get_account(account["id"], ADMIN))
    assert fetched_acct["purge_pending"] is False, "purge_pending must be cleared"
    assert fetched_acct["pet_count"] == 0, \
        f"pet_count must be 0 after archival, got {fetched_acct['pet_count']}"


# =========================================================================
# Corner: derived pet_count reconciliation (cross_cutting_complexity_layers)
# =========================================================================

def test_pet_count_reconciled_to_two_after_two_creates(api):
    """PRD §3.1: "registering a pet increments the owning account's `pet_count`."
    PRD §3.1: "Its `pet_count` is the number of the account's pets whose status is
    not `ARCHIVED`."

    Design: Corner/cross_cutting_complexity_layers/derived_pet_count_reconciled_on_pet_create
    """
    account = create_account()
    acct_h = make_account_headers(account["id"])
    create_pet(account["id"], name="D1")
    create_pet(account["id"], name="D2", species="CAT")

    fetched = validate_success(api.get_account(account["id"], acct_h))
    assert fetched["pet_count"] == 2, f"pet_count must be 2, got {fetched['pet_count']}"
