"""Validation-priority conflicts: when two conditions could reject one request,
the higher-priority error is returned deterministically.

Covers:
  Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_insufficient_wallet
  Difficulty/priority_pair_validation_conflict/quote_file_not_printable_beats_wallet
"""
from test_helpers import (
    validate_error, get_success_data, api_client,
    setup_catalogue, upload_and_check_file, upload_file,
    create_order_payload, create_order_line_payload, FILE_B, TEST_USERS,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def test_confirm_draft_underfunded_returns_invalid_state_not_wallet(api):
    """PRD §2.11: "(6) state legality — the target resource is in a state from
    which the requested transition is permitted, else `ERR_INVALID_STATE`. Beyond
    this common prefix, endpoint-specific business rules ... and the
    optimistic-concurrency stale-version check is the last of them."
    PRD §3.5: "Confirming a quoted order is the moment money moves into escrow."

    A DRAFT (never QUOTED) order with a zero-wallet customer fails both the state
    precondition (p6) and the wallet check (p13, a business rule applied after the
    common prefix); the higher-priority state check wins.

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_insufficient_wallet
    """
    # Customer with wallet 0 (no deposit); DRAFT order with one ACTIVE printable line.
    env = setup_catalogue(funded=False, with_spool=False)
    f = upload_and_check_file(env["bureau"]["id"], env["customer"]["id"],
                              env["material"]["id"], geometry=FILE_B)
    order = get_success_data(api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        env["cust_headers"]))
    line = get_success_data(api.create_order_line(
        create_order_line_payload(order["id"], f["id"], env["material"]["id"],
                                  layer_height_mm=0.10, quantity=1),
        env["cust_headers"]))
    # Confirm a DRAFT order (never quoted). State check (p6) fires before wallet (p13).
    res = api.confirm_order(order["id"], {"expected_order_version": line["version"]},
                            env["cust_headers"])
    validate_error(res, "ERR_INVALID_STATE")


def test_confirm_invalid_state_fires_even_when_wallet_is_sufficient(api):
    """PRD §2.11: "(6) state legality — the target resource is in a state from
    which the requested transition is permitted, else `ERR_INVALID_STATE`."
    PRD §3.5: "Confirming a quoted order is the moment money moves into escrow."

    Confirming a DRAFT order (never quoted) is a pure state violation; the state
    check (p6) precedes any business rule regardless of wallet balance.

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_insufficient_wallet
    """
    # Funded customer this time: only the state precondition is violated.
    env = setup_catalogue(funded=True, with_spool=False)
    f = upload_and_check_file(env["bureau"]["id"], env["customer"]["id"],
                              env["material"]["id"], geometry=FILE_B)
    order = get_success_data(api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        env["cust_headers"]))
    line = get_success_data(api.create_order_line(
        create_order_line_payload(order["id"], f["id"], env["material"]["id"],
                                  layer_height_mm=0.10, quantity=1),
        env["cust_headers"]))
    res = api.confirm_order(order["id"], {"expected_order_version": line["version"]},
                            env["cust_headers"])
    validate_error(res, "ERR_INVALID_STATE")


def test_quote_nonprintable_file_underfunded_returns_file_not_printable_not_wallet(api):
    """PRD §3.5: "every `ACTIVE` line's `PrintFile` must be in status `PRINTABLE`,
    otherwise it is rejected with `ERR_FILE_NOT_PRINTABLE`. A `FLAGGED`, `UPLOADED`,
    or `REJECTED` file on any active line blocks the quote."

    Quoting an order whose only line uses an UPLOADED (never-checked) file, for a
    zero-wallet customer: the printability gate fires; quote never reaches any
    fiscal consideration (confirm is where the wallet is checked, not quote).

    Design: Difficulty/priority_pair_validation_conflict/quote_file_not_printable_beats_wallet
    """
    env = setup_catalogue(funded=False, with_spool=False)
    f = upload_file(env["bureau"]["id"], env["customer"]["id"], geometry=FILE_B)  # UPLOADED
    order = get_success_data(api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        env["cust_headers"]))
    get_success_data(api.create_order_line(
        create_order_line_payload(order["id"], f["id"], env["material"]["id"],
                                  layer_height_mm=0.10, quantity=1),
        env["cust_headers"]))
    res = api.quote_order(order["id"], env["cust_headers"])
    validate_error(res, "ERR_FILE_NOT_PRINTABLE")


def test_quote_flagged_file_blocks_quote_regardless_of_wallet(api):
    """PRD §3.5: "every `ACTIVE` line's `PrintFile` must be in status `PRINTABLE`,
    otherwise it is rejected with `ERR_FILE_NOT_PRINTABLE`. A `FLAGGED`, `UPLOADED`,
    or `REJECTED` file on any active line blocks the quote."

    A FLAGGED (not overridden) file on the only active line blocks the quote; this
    holds for a funded customer too, since quote never reaches a fiscal gate.

    Design: Difficulty/priority_pair_validation_conflict/quote_file_not_printable_beats_wallet
    """
    env = setup_catalogue(funded=True, with_spool=False)
    # bbox 200 (>185 fits 0) + overhang 90 (>45 ov 0): manifold 40 + wall 20 = 60 -> FLAGGED
    geo = {"volume_cm3": 4.00, "bbox_x_mm": 200, "bbox_y_mm": 20, "bbox_z_mm": 20,
           "min_wall_mm": 1.0, "max_overhang_deg": 90, "is_manifold": True}
    f = upload_and_check_file(env["bureau"]["id"], env["customer"]["id"],
                              env["material"]["id"], geometry=geo)
    assert f["status"] == "FLAGGED"
    order = get_success_data(api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"]),
        env["cust_headers"]))
    get_success_data(api.create_order_line(
        create_order_line_payload(order["id"], f["id"], env["material"]["id"],
                                  layer_height_mm=0.10, quantity=1),
        env["cust_headers"]))
    res = api.quote_order(order["id"], env["cust_headers"])
    validate_error(res, "ERR_FILE_NOT_PRINTABLE")
