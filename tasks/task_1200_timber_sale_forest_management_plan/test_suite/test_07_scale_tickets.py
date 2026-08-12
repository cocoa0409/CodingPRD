"""Scale tickets: Doyle vs International, overrun allowance, dispute loop (PRD §3.6)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    PINE_PLOTS_6_ALT,
    TEST_USERS,
    create_forester_payload,
    create_scale_ticket_payload,
    make_forester_headers,
    setup_contract_active,
    setup_contract_harvesting,
)

ADMIN = TEST_USERS["admin_headers"]


def test_doyle_vs_international_governing_volume(api):
    """PRD §3.6: "Under Doyle, the per-log figure takes the small-end diameter
    in inches, subtracts 4, divides by 4, squares the result, multiplies by
    the length in feet, and rounds the product *down* to a whole board foot;
    `bf_doyle` is that per-log value multiplied by `log_count`. Under
    International 1/4-inch, the per-log figure is 0.79 times the square of
    the diameter, minus twice the diameter, minus 4, the difference multiplied
    by the length and divided by 16, rounded half up to a whole board foot;
    `bf_international` is that per-log value multiplied by `log_count`."

    Design: Difficulty/dual_variant_calc/doyle_vs_international_governing_volume
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    ticket = validate_success(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-20", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=10),
        ch,
    ), 201)
    assert ticket["bf_doyle"] == 1000
    assert ticket["bf_international"] == 1230
    assert ticket["bf_governing"] == 1000
    assert ticket["bf_doyle"] != ticket["bf_international"]


def test_identical_logs_yield_different_bf_across_rules(api):
    """PRD §3.6: "identical log dimensions yield different figures under the
    two rules."

    Design: Difficulty/dual_variant_calc/doyle_vs_international_governing_volume
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "INTERNATIONAL_14"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    ticket = validate_success(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-20", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=10),
        ch,
    ), 201)
    # INTERNATIONAL_14 governs; bf_governing is the international figure.
    assert ticket["bf_doyle"] == 1000
    assert ticket["bf_international"] == 1230
    assert ticket["bf_governing"] == 1230


def test_ticket_create_requires_contract_harvesting(api):
    """PRD §3.6: "Tickets may only be recorded against a contract that is
    `HARVESTING`; a contract in `SUSPENDED` or any other state refuses the
    ticket with `ERR_CONTRACT_SUSPENDED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_contract_harvesting
    """
    base = setup_contract_active(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    # Pre-harvest (contract ACTIVE) -> refused.
    resp1 = api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-15", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        ch,
    )
    validate_error(resp1, ApiErrorId.ERR_CONTRACT_SUSPENDED)

    # Start harvest, create ticket (works), complete harvest, try again -> refused.
    get_success_data(api.set_clock({"to_iso8601": "2026-06-15T00:00:00Z"}, ADMIN))
    get_success_data(api.start_harvest(base["contract"]["id"], base["contractor_headers"]))
    ticket = validate_success(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-15", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        ch,
    ), 201)
    assert ticket["bf_governing"] == 100

    get_success_data(api.complete_harvest(base["contract"]["id"], base["contractor_headers"]))
    resp2 = api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-15", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        ch,
    )
    validate_error(resp2, ApiErrorId.ERR_CONTRACT_SUSPENDED)


def test_overrun_allowance_exact_boundary(api):
    """PRD §3.6: "If the running cumulative plus the new ticket's `bf_governing`
    would strictly exceed the allowance, the ticket is refused with
    `ERR_VOLUME_ALLOWANCE_EXCEEDED` (HTTP 422); landing exactly on the
    allowance is permitted."

    Design: Difficulty/boundary_precision_check/overrun_allowance_exact_boundary
    """
    # Certified volume for PINE = 339780 with PINE_PLOTS_6_ALT (sampling_error 2.92).
    # allowance = round_half_up(339780 * 1.10) = 373758.
    base = setup_contract_harvesting(
        plots=PINE_PLOTS_6_ALT,
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    # Ticket 1: 3700 logs * 100 bf = 370000.
    tk1 = validate_success(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=3700),
        ch,
    ), 201)
    # Ticket 2: 91 logs * bf_doyle(14, 6.08)=38 = 3458.
    tk2 = validate_success(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=6.08,
                                    log_count=91),
        ch,
    ), 201)
    assert tk2["bf_governing"] == 3458
    # Ticket 3: 3 logs * 100 = 300 -> cumulative = 370000 + 3458 + 300 = 373758 (== allowance).
    tk3 = validate_success(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=3),
        ch,
    ), 201)
    # Fourth ticket: 1 log at 38 bf would push cumulative to 373796 > 373758.
    resp = api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=6.08,
                                    log_count=1),
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_VOLUME_ALLOWANCE_EXCEEDED)


def test_overrun_allowance_allows_equal(api):
    """PRD §3.6: "landing exactly on the allowance is permitted."

    Design: Difficulty/boundary_precision_check/overrun_allowance_exact_boundary
    """
    base = setup_contract_harvesting(
        plots=PINE_PLOTS_6_ALT,
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    # Single ticket that lands exactly on the 373758 boundary: 3700*100 + 91*38 + 3*100 = 373758
    # Reaching exactly 373758 via three tickets demonstrates equal-is-allowed.
    get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=3700),
        ch,
    ))
    get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=6.08,
                                    log_count=91),
        ch,
    ))
    last = validate_success(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=16,
                                    log_count=3),
        ch,
    ), 201)
    assert last["bf_governing"] == 300


def test_scale_ticket_dispute_cycle(api):
    """PRD §3.6: "moving it `VERIFIED → DISPUTED` and recomputing the
    contract's cumulative verified figures with the disputed ticket excluded.
    Resolution belongs to the forester: resolving with `resolution` `ACCEPT`
    returns the ticket `DISPUTED → VERIFIED` and re-includes it in the
    cumulative figures".

    Design: Difficulty/non_linear_state_machine/scale_ticket_dispute_cycle
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    ticket = get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-20", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        ch,
    ))
    ticket = get_success_data(api.verify_scale_ticket(ticket["id"], fh))
    contract_mid0 = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract_mid0["cumulative_verified_bf"] == 100

    # Dispute (landowner owns the tract) -> DISPUTED, cumulative drops to 0.
    ticket = validate_success(api.dispute_scale_ticket(
        ticket["id"], {"reason": "diameter misread"}, lh
    ))
    assert ticket["status"] == "DISPUTED"
    contract_mid = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract_mid["cumulative_verified_bf"] == 0

    # Resolve ACCEPT -> VERIFIED, cumulative back to 100.
    ticket = validate_success(api.resolve_scale_ticket(
        ticket["id"], {"resolution": "ACCEPT"}, fh
    ))
    assert ticket["status"] == "VERIFIED"
    contract_end = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract_end["cumulative_verified_bf"] == 100


def test_scale_ticket_dispute_recomputes_cumulative(api):
    """PRD §3.6: "moving it `VERIFIED → DISPUTED` and recomputing the
    contract's cumulative verified figures with the disputed ticket excluded."

    Design: Difficulty/non_linear_state_machine/scale_ticket_dispute_cycle
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    ticket = get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-20", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        ch,
    ))
    get_success_data(api.verify_scale_ticket(ticket["id"], fh))
    get_success_data(api.dispute_scale_ticket(ticket["id"], {}, lh))
    contract = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract["cumulative_verified_bf"] == 0


def test_dispute_after_window_rejected(api):
    """PRD §3.6: "within 10 days of `verified_at`, the tract-owning landowner
    or the contract's buyer may dispute the ticket — later disputes are
    refused with `ERR_DISPUTE_WINDOW_PASSED` (HTTP 422)".

    Design: Corner/validations/dispute_after_window_rejected
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    ticket = get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        ch,
    ))
    get_success_data(api.set_clock({"to_iso8601": "2026-06-20T00:00:00Z"}, ADMIN))
    get_success_data(api.verify_scale_ticket(ticket["id"], fh))
    # 11 days later -> past the 10-day window.
    get_success_data(api.set_clock({"to_iso8601": "2026-07-01T00:00:00Z"}, ADMIN))
    resp = api.dispute_scale_ticket(ticket["id"], {}, lh)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_PASSED)


def test_immediate_read_after_write_ticket_fields(api):
    """PRD §3.6: "Board feet are computed once, at creation, and never
    recomputed."
    PRD §3.6: "The creator's `X-User-ID` is persisted as `recorded_by_id`,
    and the ticket is born in `DRAFT` with `flagged_for_review` false."

    Design: Corner/consistency/immediate_read_after_write_ticket_fields
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    ch = base["contractor_headers"]
    fh = base["forester_headers"]
    ticket = validate_success(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        ch,
    ), 201)
    assert ticket["bf_doyle"] == 100
    assert ticket["bf_international"] == 123
    assert ticket["bf_governing"] == 100
    # Read-after-write via GET.
    got = get_success_data(api.get_scale_ticket(ticket["id"], fh))
    assert got["bf_doyle"] == 100
    assert got["bf_governing"] == 100
    assert got["bf_international"] == 123
    assert got["recorded_by_id"] == base["contractor"]["id"]
    assert got["status"] == "DRAFT"


def test_forester_cannot_verify_own_recorded_ticket(api):
    """PRD §3.6: "the verifying forester's `X-User-ID` must differ from the
    ticket's `recorded_by_id`, or the verify is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/forester_cannot_verify_own_recorded_ticket
    """
    # Contract HARVESTING; ticket recorded by forester F1 (not the contractor).
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh1 = base["forester_headers"]
    # Register a second forester (the verifier).
    forester2 = get_success_data(api.create_forester(
        create_forester_payload(license_no="F-200", full_name="Fiona Second",
                                email="f2@x.com"),
        ADMIN,
    ))
    fh2 = make_forester_headers(forester2["id"])

    # F1 records the ticket.
    ticket = get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        fh1,
    ))
    # F1 cannot verify own ticket.
    resp = api.verify_scale_ticket(ticket["id"], fh1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # F2 (a different forester) can verify.
    verified = validate_success(api.verify_scale_ticket(ticket["id"], fh2))
    assert verified["status"] == "VERIFIED"


def test_ticket_create_blocked_while_suspended(api):
    """PRD §3.6: "Tickets may only be recorded against a contract that is
    `HARVESTING`; a contract in `SUSPENDED` or any other state refuses the
    ticket with `ERR_CONTRACT_SUSPENDED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_contract_harvesting
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    ch = base["contractor_headers"]
    # Suspend; ticket create must refuse.
    get_success_data(api.suspend_contract(base["contract"]["id"], fh))
    resp = api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-16", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_SUSPENDED)
