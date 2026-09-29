"""Two independent state dimensions on a shipment, and the cyclic payable machine."""
from test_helpers import (
    assert_intake,
    assert_settlement,
    fixtures as fx,
    validate_success,
)


# --------------------------------------------------------------------------
# Custody and compliance advance on their own triggers
# --------------------------------------------------------------------------

def test_custody_dimension_advances_while_the_paperwork_stays_in_draft(api):
    """Identification and discharge move the physical dimension forward and leave
    the paperwork dimension untouched.

    PRD §3.2: "A newly booked shipment starts on **two independent state dimensions
    carried on the same row**."

    Design: Difficulty/non_linear_state_machine/intake_parallel_custody_and_compliance_dimensions_evolve_independently
    """
    ctx = fx.bootstrap_network(api)
    booked = fx.book_intake(
        api,
        ctx["supplier"]["id"],
        ctx["facility"]["id"],
        gross_mass_kg=850.0,
        packaging_tare_kg=50.0,
    )
    assert_intake(booked)
    assert (booked["custody_state"], booked["compliance_state"]) == (
        "RECEIVED",
        "MANIFEST_DRAFT",
    )

    identified = fx.identify_chemistry(api, booked["id"])
    assert (identified["custody_state"], identified["compliance_state"]) == (
        "IDENTIFIED",
        "MANIFEST_DRAFT",
    )

    discharged = fx.discharge(api, booked["id"])
    assert (discharged["custody_state"], discharged["compliance_state"]) == (
        "DISCHARGED",
        "MANIFEST_DRAFT",
    )
    assert discharged["hold_reason"] is None


def test_compliance_dimension_advances_while_custody_stays_where_it_is(api):
    """Submitting the manifest from DISCHARGED moves only the paperwork dimension;
    packaging then moves only the physical one; closing moves only the paperwork.

    PRD §3.2: "Neither dimension is a function of the other; they advance on their
    own triggers"

    Design: Difficulty/non_linear_state_machine/intake_parallel_custody_and_compliance_dimensions_evolve_independently
    """
    ctx = fx.bootstrap_network(api)
    intake = fx.book_intake(
        api,
        ctx["supplier"]["id"],
        ctx["facility"]["id"],
        gross_mass_kg=850.0,
        packaging_tare_kg=50.0,
    )
    fx.identify_chemistry(api, intake["id"])
    fx.discharge(api, intake["id"])

    manifest = fx.submit_manifest(api, intake["id"])
    after_submit = fx.read_intake(api, intake["id"])
    assert (after_submit["custody_state"], after_submit["compliance_state"]) == (
        "DISCHARGED",
        "MANIFEST_SUBMITTED",
    )

    packaged = fx.package(api, intake["id"])
    assert (packaged["custody_state"], packaged["compliance_state"]) == (
        "PACKAGED",
        "MANIFEST_SUBMITTED",
    )

    closed = fx.close_manifest(api, intake["id"], manifest["id"])
    assert closed["status"] == "CLOSED"
    assert closed["revision"] == 1
    after_close = fx.read_intake(api, intake["id"])
    assert (after_close["custody_state"], after_close["compliance_state"]) == (
        "PACKAGED",
        "MANIFEST_CLOSED",
    )
    assert after_close["hold_reason"] is None


# --------------------------------------------------------------------------
# DRAFT -> POSTED -> DISPUTED -> UMPIRE_ROUND -> DRAFT
# --------------------------------------------------------------------------

def test_dispute_moves_posted_to_disputed_and_leaves_the_payable_untouched(api):
    """The counterparty's dispute records the reason and advances the round counter
    without touching the money already owed.

    PRD §3.9: "Critically, the supplier's `payable_balance_cents` is left
    **untouched**: a disputed amount is still owed until it is re-priced or paid."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_umpire_cycle_returns_to_draft
    """
    ctx = fx.large_four_metal_posted(api)
    assert ctx["settlement"]["state"] == "POSTED"
    assert ctx["settlement"]["posted_amount_cents"] == 213727

    disputed = fx.dispute_settlement(
        api,
        ctx["settlement"]["id"],
        ctx["supplier"]["id"],
        "Nickel assay 3.50 pp below declared",
    )

    assert_settlement(disputed)
    assert disputed["state"] == "DISPUTED"
    assert disputed["dispute_round"] == 1
    assert disputed["dispute_reason"] == "Nickel assay 3.50 pp below declared"
    assert disputed["posted_amount_cents"] == 213727

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["payable_balance_cents"] == 213727


def test_umpire_assay_moves_the_disputed_settlement_into_the_umpire_round(api):
    """The independent laboratory figure is recorded against the metal in argument
    and the settlement advances DISPUTED -> UMPIRE_ROUND.

    PRD §3.9: "On success `umpire_metal` and `umpire_contained_kg` are recorded, the
    settlement moves `DISPUTED → UMPIRE_ROUND`, and its `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_umpire_cycle_returns_to_draft
    """
    ctx = fx.large_four_metal_disputed(api)
    before = ctx["settlement"]

    umpire = fx.record_umpire_assay(api, before["id"], "NI", 80.000)

    assert umpire["state"] == "UMPIRE_ROUND"
    assert umpire["umpire_metal"] == "NI"
    assert float(umpire["umpire_contained_kg"]) == 80.000
    assert umpire["version"] == before["version"] + 1
    assert umpire["posted_amount_cents"] == 213727, (
        "the umpire result alone does not move the payable ledger"
    )


def test_applying_the_umpire_result_reprices_and_returns_the_settlement_to_draft(api):
    """The umpire figure is substituted for the ledger figure of the re-assayed
    metal, the waterfall reruns, the posted amount is reversed and the settlement
    lands back in DRAFT.

    PRD §3.9: "The settlement is re-priced under the `FINAL` rules with one
    substitution: for the metal named in `umpire_metal`, the lot's recovered figure
    is replaced by `umpire_contained_kg` before apportionment"

    Design: Difficulty/non_linear_state_machine/settlement_dispute_umpire_cycle_returns_to_draft
    """
    ctx = fx.large_four_metal_umpire_round(api)

    applied = fx.apply_umpire(api, ctx["settlement"]["id"])

    assert_settlement(applied)
    assert applied["state"] == "DRAFT"
    assert applied["variant"] == "FINAL"
    assert applied["dispute_round"] == 1
    assert applied["gross_cents"] == 271706
    assert applied["processing_fee_cents"] == 32605
    assert applied["quality_deduction_cents"] == 5434
    assert applied["pre_surcharge_net_cents"] == 233667
    assert applied["hazmat_surcharge_cents"] == 7300
    assert applied["net_payable_cents"] == 226367
    assert applied["posted_amount_cents"] == 0
    assert float(applied["max_variance_pp"]) == 2.00

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["payable_balance_cents"] == 0
    assert supplier["credit_hold"] is False


def test_the_reopened_draft_settlement_can_be_posted_again(api):
    """Returning to DRAFT closes the commercial cycle: the settlement is postable
    once more, now at the umpire figure.

    PRD §3.9: "The settlement itself moves `UMPIRE_ROUND → DRAFT`, ready to be
    posted again at the new figure."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_umpire_cycle_returns_to_draft
    """
    ctx = fx.large_four_metal_umpire_round(api)
    fx.apply_umpire(api, ctx["settlement"]["id"])

    reposted = validate_success(
        api.post_settlement(ctx["settlement"]["id"], fx.ACCOUNTANT)
    )
    assert reposted["state"] == "POSTED"
    assert reposted["posted_amount_cents"] == 226367

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["payable_balance_cents"] == 226367
