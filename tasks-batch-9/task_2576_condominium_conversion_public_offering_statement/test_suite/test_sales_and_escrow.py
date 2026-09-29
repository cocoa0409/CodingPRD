"""Purchase agreements: the junction row, the effectiveness gate, the rescission
window, the hardening precondition pair and escrow conservation.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_cents,
    assert_decimal_equals,
    assert_escrow_conserved,
    assert_instant,
    assert_page,
)
from test_helpers.factories import agreement_payload, component_payload, roof_standard
from test_helpers.fixtures import (
    build_registered_project,
    deliver_pos,
    fund_escrow,
    make_agreement,
    make_batch,
    make_household,
    make_package,
    make_project,
    make_unit,
    set_clock,
    unit_version,
)
from test_helpers.test_users import (
    escrow_headers,
    purchaser_headers,
    sponsor_headers,
)

STD_ADDRESS = "44 Cove Lane, Bangor ME"


def _effective_project(api, unit_specs=(("101", 10000),), expense_cents=1000000):
    """The golden path to an EFFECTIVE statement over the given unit set."""
    return build_registered_project(
        api,
        STD_ADDRESS,
        1968,
        unit_specs=unit_specs,
        components=[roof_standard()],
        annual_operating_expense_cents=expense_cents,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        total_unit_count=2,
        section_word_count=200,
        body_ref_prefix="s-ub",
    )


def test_purchase_agreement_junction_links_unit_pos_batch_and_household(api):
    """PRD: A purchase agreement is the junction of the sales pipeline: it references
    the unit being sold, the project, the public offering statement it was written
    against, optionally the tenant household exercising a right of first refusal, and
    optionally the closing batch it has been assigned to.

    Design: Corner/entities/purchase_agreement_junction_links_unit_pos_batch_and_household
    """
    built = _effective_project(api)
    project_id = built["project"]["id"]
    unit_id = built["units"][0]["id"]
    pos_id = built["pos"]["id"]
    household = make_household(
        api, project_id, "HH-1", "2026-01-01T00:00:00Z", 300000, occupied_unit_id=unit_id
    )

    agreement = validate_success(
        api.create_agreement(
            unit_id,
            agreement_payload(
                "Ada Byron",
                "TAX-001",
                "OWNER_OCCUPANT",
                25000000,
                2500000,
                unit_version(api, unit_id),
                household["id"],
            ),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    batch = make_batch(
        api,
        project_id,
        1,
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        51.0,
        1,
    )
    batch_before = validate_success(api.get_batch(batch["id"], sponsor_headers()))

    validate_success(
        api.assign_agreement(
            batch["id"],
            {
                "purchase_agreement_id": agreement["id"],
                "expected_closing_batch_version": batch_before["version"],
            },
            sponsor_headers(),
        ),
        expected_status=201,
    )

    row = validate_success(api.get_agreement(agreement["id"], sponsor_headers()))
    assert row["unit_id"] == unit_id
    assert row["conversion_project_id"] == project_id
    assert row["public_offering_statement_id"] == pos_id
    assert row["tenant_household_id"] == household["id"]
    assert row["closing_batch_id"] == batch["id"]
    assert row["contract_status"] == "SIGNED"
    assert row["escrow_status"] == "PENDING"
    assert_instant(row["signed_at"], "2026-08-01T00:00:00Z")

    after_batch = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert after_batch["status"] == "OPEN_FOR_ASSIGNMENT"
    assert after_batch["assigned_agreement_count"] == 1
    assert after_batch["qualifying_agreement_count"] == 0
    assert after_batch["version"] == batch_before["version"] + 1

    assert validate_success(api.get_unit(unit_id, sponsor_headers()))[
        "sale_status"
    ] == "UNDER_CONTRACT"

    rows, meta = validate_paginated(
        api.list_batch_agreements(batch["id"], sponsor_headers())
    )
    assert_page(meta, total_count=1)
    assert [item["id"] for item in rows] == [agreement["id"]]
    _, meta = validate_paginated(
        api.list_agreements(sponsor_headers(), params={"closing_batch_id": batch["id"]})
    )
    assert_page(meta, total_count=1)


def test_purchase_agreement_requires_an_effective_pos(api):
    """PRD: The unit must be `INCLUDED` and the project must have a statement at
    `EFFECTIVE`, refused otherwise with `ERR_POS_NOT_EFFECTIVE` (409).

    Design: Corner/validations/purchase_agreement_requires_an_effective_pos
    """
    project = make_project(api, STD_ADDRESS, 1968, 2)
    package = make_package(api, project["id"], "CENTERLINE", "decl/ref-a", "bylaws/ref-a")
    unit = make_unit(
        api, package["id"], "101", 10000, 1, 900, "interior finish surfaces"
    )

    validate_error(
        api.create_agreement(
            unit["id"],
            agreement_payload(
                "Dana Reyes",
                "TIN-1001",
                "OWNER_OCCUPANT",
                24000000,
                2400000,
                unit_version(api, unit["id"]),
            ),
            sponsor_headers(),
        ),
        "ERR_POS_NOT_EFFECTIVE",
        expected_status=409,
    )

    after = validate_success(api.get_unit(unit["id"], sponsor_headers()))
    assert after["sale_status"] == "UNSOLD"
    assert after["declaration_status"] == "INCLUDED"

    _, meta = validate_paginated(
        api.list_unit_agreements(unit["id"], sponsor_headers())
    )
    assert_page(meta, total_count=0)
    _, meta = validate_paginated(api.list_project_pos(project["id"], sponsor_headers()))
    assert_page(meta, total_count=0)


def test_rescission_window_length_selected_by_purchaser_type(api):
    """PRD: The sponsor records delivery of the effective statement to the purchaser,
    which stamps `pos_delivered_at` from the logical clock and computes
    `rescission_deadline_at` as that instant plus a window that depends entirely on
    `purchaser_type`: 15 days for an `OWNER_OCCUPANT`, 7 days for an `INVESTOR`, each
    expressed as an exact multiple of 86400 seconds with no calendar or business-day
    arithmetic.

    Design: Corner/calculations/rescission_window_length_selected_by_purchaser_type
    """
    built = _effective_project(api, unit_specs=(("101", 5000), ("102", 5000)))
    owner_unit, investor_unit = built["units"]
    owner = make_agreement(
        api, owner_unit["id"], "Ada Ling", "TX-1001", "OWNER_OCCUPANT", 30000000, 3000000
    )
    investor = make_agreement(
        api,
        investor_unit["id"],
        "Kestrel Holdings LLC",
        "TX-2002",
        "INVESTOR",
        30000000,
        3000000,
    )

    assert owner["pos_delivered_at"] is None
    assert owner["rescission_deadline_at"] is None
    assert validate_success(api.get_pos(built["pos"]["id"], sponsor_headers()))[
        "status"
    ] == "EFFECTIVE"

    delivered_owner = validate_success(
        api.deliver_pos(owner["id"], sponsor_headers()), expected_status=201
    )
    assert_instant(delivered_owner["pos_delivered_at"], "2026-08-01T00:00:00Z")
    assert_instant(delivered_owner["rescission_deadline_at"], "2026-08-16T00:00:00Z")
    assert delivered_owner["contract_status"] == "SIGNED"
    assert delivered_owner["rescission_restart_count"] == 0

    delivered_investor = validate_success(
        api.deliver_pos(investor["id"], sponsor_headers()), expected_status=201
    )
    assert_instant(delivered_investor["pos_delivered_at"], "2026-08-01T00:00:00Z")
    assert_instant(delivered_investor["rescission_deadline_at"], "2026-08-08T00:00:00Z")
    assert delivered_investor["escrow_status"] == "PENDING"


def test_stale_unit_version_is_rejected_before_the_pos_effectiveness_gate(api):
    """PRD: Because signing rewrites the unit's `sale_status`, the operation is guarded
    against stale reads of the unit: when `expected_unit_version` does not match the
    unit's current `version`, the request is rejected with `ERR_STALE_UNIT_VERSION` and
    HTTP status 412 and nothing is written.

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_is_rejected_before_the_pos_effectiveness_gate
    """
    project = make_project(api, STD_ADDRESS, 1968, 2)
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    unit = make_unit(api, package["id"], "101", 10000, 1, 900, "as-built")

    before = validate_success(api.get_unit(unit["id"], sponsor_headers()))
    assert before["version"] == 1
    assert before["sale_status"] == "UNSOLD"

    def sign(expected_version):
        return api.create_agreement(
            unit["id"],
            agreement_payload(
                "Ada Ling",
                "TX-1001",
                "OWNER_OCCUPANT",
                30000000,
                3000000,
                expected_version,
            ),
            sponsor_headers(),
        )

    validate_error(sign(before["version"] - 1), "ERR_STALE_UNIT_VERSION", 412)
    validate_error(sign(before["version"]), "ERR_POS_NOT_EFFECTIVE", 409)

    after = validate_success(api.get_unit(unit["id"], sponsor_headers()))
    assert after["version"] == 1
    assert after["sale_status"] == "UNSOLD"
    _, meta = validate_paginated(
        api.list_unit_agreements(unit["id"], sponsor_headers())
    )
    assert_page(meta, total_count=0)
    assert_decimal_equals(
        validate_success(api.get_project(project["id"], sponsor_headers()))[
            "owner_occupancy_pct_contract_basis"
        ],
        "0.00",
        "owner_occupancy_pct_contract_basis",
    )


def test_pos_not_delivered_beats_escrow_not_funded_on_hardening(api):
    """PRD: Five preconditions apply: `contract_status` is `SIGNED`; `pos_delivered_at`
    is non-null; the clock is at or after `rescission_deadline_at`; `escrow_status` is
    `FUNDED`, refused otherwise with `ERR_ESCROW_NOT_FUNDED` and HTTP status 402 — a
    payment-required refusal, since the money is genuinely absent rather than the
    request being malformed; and the project's `posture` is not `FROZEN`.

    Design: Difficulty/priority_pair_validation_conflict/pos_not_delivered_beats_escrow_not_funded_on_hardening
    """
    built = build_registered_project(
        api,
        "4 Cornice Lane, Salem MA",
        1971,
        unit_specs=(("C-1", 10000),),
        components=[
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            )
        ],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        total_unit_count=2,
    )
    project_id = built["project"]["id"]
    agreement = make_agreement(
        api,
        built["units"][0]["id"],
        "Gita Cornice",
        "TAX-OO-11",
        "OWNER_OCCUPANT",
        24000000,
        2400000,
    )

    validate_error(
        api.harden_agreement(agreement["id"], sponsor_headers()),
        "ERR_POS_NOT_DELIVERED",
        expected_status=409,
    )
    refused = validate_success(api.get_agreement(agreement["id"], sponsor_headers()))
    assert refused["contract_status"] == "SIGNED"
    assert refused["pos_delivered_at"] is None
    assert refused["escrow_status"] == "PENDING"
    assert refused["version"] == agreement["version"]
    project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(project["escrow_balance_cents"], 0, "escrow_balance_cents")
    assert_cents(project["escrow_deposits_received_cents"], 0, "received")
    assert_decimal_equals(project["presale_sold_pct"], "0.00", "presale_sold_pct")

    # repair the winner and the second-ranked violation surfaces on the same call
    delivered = validate_success(
        api.deliver_pos(agreement["id"], sponsor_headers()), expected_status=201
    )
    assert_instant(delivered["rescission_deadline_at"], "2026-08-16T00:00:00Z")
    set_clock(api, "2026-08-16T00:00:00Z")
    validate_error(
        api.harden_agreement(agreement["id"], sponsor_headers()),
        "ERR_ESCROW_NOT_FUNDED",
        expected_status=402,
    )
    still = validate_success(api.get_agreement(agreement["id"], sponsor_headers()))
    assert still["contract_status"] == "SIGNED"
    assert still["escrow_status"] == "PENDING"
    assert_escrow_conserved(
        validate_success(api.get_project(project_id, sponsor_headers()))
    )


def test_rescission_deadline_strict_vs_inclusive_at_same_instant(api):
    """PRD: Rescission is permitted while the logical clock is **strictly before**
    `rescission_deadline_at`; hardening is permitted while the clock is **at or after**
    it. At the exact deadline instant the two rules do not overlap and do not leave a
    gap: rescission is refused with `ERR_RESCISSION_PERIOD_CLOSED` (409) and hardening
    succeeds.

    Design: Difficulty/boundary_precision_check/rescission_deadline_strict_vs_inclusive_at_same_instant
    """
    built = build_registered_project(
        api,
        "9 Frieze Terrace, Everett MA",
        1966,
        unit_specs=(("F-1", 5000), ("F-2", 5000)),
        components=[
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            )
        ],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
    )
    project_id = built["project"]["id"]
    u1, u2 = built["units"]
    pa1 = make_agreement(
        api, u1["id"], "Ida Frieze", "TAX-OO-16", "OWNER_OCCUPANT", 24000000, 2400000
    )
    pa2 = make_agreement(
        api, u2["id"], "Jonas Frieze", "TAX-OO-17", "OWNER_OCCUPANT", 25000000, 2400000
    )
    for agreement in (pa1, pa2):
        deliver_pos(api, agreement["id"])
        fund_escrow(api, agreement["id"], 2400000)

    for agreement in (pa1, pa2):
        row = validate_success(api.get_agreement(agreement["id"], sponsor_headers()))
        assert_instant(row["rescission_deadline_at"], "2026-08-16T00:00:00Z")
        assert_instant(row["pos_delivered_at"], "2026-08-01T00:00:00Z")
        assert row["rescission_restart_count"] == 0

    # one second short of the deadline: hardening is refused, rescission succeeds
    set_clock(api, "2026-08-15T23:59:59Z")
    before_pa2 = validate_success(api.get_agreement(pa2["id"], sponsor_headers()))
    validate_error(
        api.harden_agreement(pa2["id"], sponsor_headers()),
        "ERR_RESCISSION_PERIOD_OPEN",
        expected_status=409,
    )
    unchanged = validate_success(api.get_agreement(pa2["id"], sponsor_headers()))
    assert unchanged["contract_status"] == "SIGNED"
    assert unchanged["version"] == before_pa2["version"]

    rescinded = validate_success(
        api.rescind_agreement(
            pa1["id"],
            purchaser_headers(pa1["id"]),
            {"rescission_reason": "buyer changed mind"},
        )
    )
    assert rescinded["contract_status"] == "RESCINDED"
    assert rescinded["escrow_status"] == "REFUNDED"

    # the deadline instant itself: rescission is closed, hardening is open
    set_clock(api, "2026-08-16T00:00:00Z")
    at_deadline = validate_success(api.get_agreement(pa2["id"], sponsor_headers()))
    validate_error(
        api.rescind_agreement(
            pa2["id"],
            purchaser_headers(pa2["id"]),
            {"rescission_reason": "buyer changed mind"},
        ),
        "ERR_RESCISSION_PERIOD_CLOSED",
        expected_status=409,
    )
    refused = validate_success(api.get_agreement(pa2["id"], sponsor_headers()))
    assert refused["contract_status"] == "SIGNED"
    assert refused["escrow_status"] == "FUNDED"
    assert refused["version"] == at_deadline["version"]

    hardened = validate_success(api.harden_agreement(pa2["id"], sponsor_headers()))
    assert hardened["contract_status"] == "HARD"

    assert validate_success(api.get_unit(u1["id"], sponsor_headers()))[
        "sale_status"
    ] == "UNSOLD"
    assert validate_success(api.get_unit(u2["id"], sponsor_headers()))[
        "sale_status"
    ] == "HARD_CONTRACT"

    project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(project["escrow_deposits_received_cents"], 4800000, "received")
    assert_cents(project["escrow_balance_cents"], 2400000, "balance")
    assert_cents(project["escrow_refunded_cents"], 2400000, "refunded")
    assert_cents(project["escrow_disbursed_cents"], 0, "disbursed")
    assert_escrow_conserved(project)


def test_escrow_cash_conserved_across_fund_then_rescind(api):
    """PRD: The compensating pair of funding followed by refund therefore leaves
    `escrow_balance_cents` where it began while `escrow_deposits_received_cents` and
    `escrow_refunded_cents` both rise by the deposit — the delta stays 0 throughout.

    Design: Difficulty/compensating_invariant/escrow_cash_conserved_across_fund_then_rescind
    """
    built = build_registered_project(
        api,
        "14 Keystone Court, Woburn MA",
        1969,
        unit_specs=(("K-1", 10000),),
        components=[
            component_payload(
                "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
            )
        ],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        total_unit_count=2,
    )
    project_id = built["project"]["id"]
    unit_id = built["units"][0]["id"]
    agreement = make_agreement(
        api, unit_id, "Lena Keystone", "TAX-OO-21", "OWNER_OCCUPANT", 24000000, 2400000
    )
    deliver_pos(api, agreement["id"])

    first = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(first["escrow_deposits_received_cents"], 0, "received")
    assert_cents(first["escrow_balance_cents"], 0, "balance")
    assert_cents(first["escrow_refunded_cents"], 0, "refunded")
    assert_cents(first["escrow_disbursed_cents"], 0, "disbursed")
    assert_escrow_conserved(first)

    funded = validate_success(
        api.deposit_escrow(agreement["id"], 2400000, escrow_headers()),
        expected_status=201,
    )
    assert funded["escrow_status"] == "FUNDED"

    second = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(second["escrow_deposits_received_cents"], 2400000, "received")
    assert_cents(second["escrow_balance_cents"], 2400000, "balance")
    assert_cents(second["escrow_refunded_cents"], 0, "refunded")
    assert_cents(second["escrow_disbursed_cents"], 0, "disbursed")
    assert_escrow_conserved(second)

    rescinded = validate_success(
        api.rescind_agreement(
            agreement["id"],
            purchaser_headers(agreement["id"]),
            {
                "rescission_reason": (
                    "purchaser exercised statutory rescission within the delivery window"
                )
            },
        )
    )
    assert rescinded["contract_status"] == "RESCINDED"
    assert rescinded["escrow_status"] == "REFUNDED"
    assert rescinded["closed_at"] is None

    third = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(third["escrow_balance_cents"], 0, "balance")
    assert_cents(third["escrow_refunded_cents"], 2400000, "refunded")
    assert_cents(third["escrow_disbursed_cents"], 0, "disbursed")
    assert_cents(third["escrow_deposits_received_cents"], 2400000, "received")
    assert_escrow_conserved(third)

    unit = validate_success(api.get_unit(unit_id, sponsor_headers()))
    assert unit["sale_status"] == "UNSOLD"
    assert unit["percentage_interest_bp"] == 10000
    assert third["posture"] == "OPEN"
    _, meta = validate_paginated(api.list_batches(project_id, sponsor_headers()))
    assert_page(meta, total_count=0)
