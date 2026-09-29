"""Two requests that each violate two rules at once. The response must name the
earlier rule on the rejection ladder, and the later rule is shown to have been
genuinely violated by a follow-up probe.
"""
from test_helpers import (
    NOV_START,
    OCT_START,
    SEP_START,
    TERM_START,
    api_client,
    bootstrap_partners,
    build_signed_contract,
    create_manufacturer,
    create_product,
    deviation_agreement_payload,
    read_contract_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, NAM


def _build_suspended_contract_world():
    """A signed contract taken straight to SUSPENDED, with the version re-read
    afterwards so the concurrency guard cannot answer first."""
    world = bootstrap_partners()
    product = create_product(world["manufacturer_id"])
    signed = build_signed_contract(
        world["operator_id"], world["manufacturer_id"], world["dc_id"]
    )
    world.update(signed)
    world["product_id"] = product["id"]
    world["suspended"] = validate_success(
        api_client.suspend_contract(
            signed["contract_id"], NAM, {"note": "Credit hold pending operator review"}
        )
    )
    world["contract_version"] = world["suspended"]["version"]
    return world


def _above_ceiling_payload(world):
    """Cost 4200 less a 100-cent protected discount resolves to 4100, which is
    above the 4000 ceiling this payload asks for."""
    return deviation_agreement_payload(
        world["contract_id"],
        world["product_id"],
        world["manufacturer_id"],
        world["contract_version"],
        4000,
        TERM_START,
        NOV_START,
        bill_back_basis="COST_PLUS_PROTECTED",
        protected_discount_cents=100,
    )


class TestSuspendedContractOutranksPriceCeiling:
    def test_suspension_answers_before_the_ceiling_is_ever_tested(self):
        """PRD §2.8: "Checks are evaluated in ascending priority order and the
        first failure wins; a later, more specific failure never masks an earlier
        one."

        Design: Difficulty/priority_pair_validation_conflict/suspended_contract_outranks_deviated_price_ceiling
        """
        world = _build_suspended_contract_world()
        assert world["suspended"]["status"] == "SUSPENDED"

        refused = api_client.create_deviation_agreement(
            _above_ceiling_payload(world), ANALYST
        )
        validate_error(refused, "ERR_CONTRACT_NOT_ACTIVE", 409)
        assert refused.json()["data"]["error_id"] != "ERR_DEVIATED_PRICE_ABOVE_CEILING"

    def test_the_refused_draft_leaves_no_trace_on_the_contract(self):
        """PRD §3.4: "Once resolved, the price is tested against the ceiling: a
        `deviated_price_cents` strictly greater than `max_operator_price_cents`
        at creation is rejected with `ERR_DEVIATED_PRICE_ABOVE_CEILING`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_contract_outranks_deviated_price_ceiling
        """
        world = _build_suspended_contract_world()

        api_client.create_deviation_agreement(_above_ceiling_payload(world), ANALYST)

        rows, meta = validate_paginated(
            api_client.list_deviation_agreements(
                ANALYST, {"contract_id": world["contract_id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        contract = validate_success(
            api_client.get_contract(world["contract_id"], NAM)
        )
        assert contract["version"] == world["contract_version"]


def _build_two_manufacturer_world():
    """A beef item owned by NWB on a contract funded by CPC, already carrying a
    DRAFT deviation over 2026-08-01 .. 2026-10-01."""
    world = bootstrap_partners()
    beef_maker = create_manufacturer(name="Northwest Beef", manufacturer_code="NWB")
    product = create_product(
        beef_maker["id"],
        sku="P-BEEF",
        description="Beef Chuck 4/10#",
        last_cost_cents=6000,
        avg_cost_cents=5900,
        replacement_cost_cents=6100,
    )
    signed = build_signed_contract(
        world["operator_id"], world["manufacturer_id"], world["dc_id"]
    )
    world.update(signed)
    world["beef_maker_id"] = beef_maker["id"]
    world["product_id"] = product["id"]

    world["first_deviation"] = validate_success(
        api_client.create_deviation_agreement(
            deviation_agreement_payload(
                signed["contract_id"],
                product["id"],
                beef_maker["id"],
                read_contract_version(signed["contract_id"]),
                6200,
                TERM_START,
                OCT_START,
                requested_net_price_cents=5800,
            ),
            ANALYST,
        ),
        201,
    )
    return world


def _overlapping_payload(world, manufacturer_id):
    """A window from 2026-09-01 to 2026-11-01, which intersects the existing
    2026-08-01 .. 2026-10-01 agreement on the same contract and product."""
    return deviation_agreement_payload(
        world["contract_id"],
        world["product_id"],
        manufacturer_id,
        read_contract_version(world["contract_id"]),
        6200,
        SEP_START,
        NOV_START,
        requested_net_price_cents=5800,
    )


class TestManufacturerMismatchOutranksWindowOverlap:
    def test_naming_the_wrong_funder_answers_before_the_window_is_compared(self):
        """PRD §3.4: "The named manufacturer must be the item's own funder: if the
        agreement's `manufacturer_id` differs from the product's
        `manufacturer_id`, the draft is refused with
        `ERR_DEVIATION_MANUFACTURER_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/manufacturer_mismatch_outranks_deviation_window_overlap
        """
        world = _build_two_manufacturer_world()
        assert world["first_deviation"]["status"] == "DRAFT"
        assert world["first_deviation"]["manufacturer_id"] == world["beef_maker_id"]

        # The contract's funding manufacturer, not the beef item's owner.
        refused = api_client.create_deviation_agreement(
            _overlapping_payload(world, world["manufacturer_id"]), ANALYST
        )
        validate_error(refused, "ERR_DEVIATION_MANUFACTURER_MISMATCH", 422)
        assert refused.json()["data"]["error_id"] != "ERR_DEVIATION_PERIOD_OVERLAP"

    def test_correcting_the_funder_reveals_the_window_conflict_underneath(self):
        """PRD §3.4: "The window itself must not collide with an existing
        agreement: the new half-open window may not intersect the window of any
        other agreement on the same contract and product whose status is not
        `REJECTED`, `EXPIRED` or `TERMINATED`."

        Design: Difficulty/priority_pair_validation_conflict/manufacturer_mismatch_outranks_deviation_window_overlap
        """
        world = _build_two_manufacturer_world()

        api_client.create_deviation_agreement(
            _overlapping_payload(world, world["manufacturer_id"]), ANALYST
        )
        refused = api_client.create_deviation_agreement(
            _overlapping_payload(world, world["beef_maker_id"]), ANALYST
        )
        validate_error(refused, "ERR_DEVIATION_PERIOD_OVERLAP", 409)

        rows, meta = validate_paginated(
            api_client.list_deviation_agreements(
                ANALYST, {"contract_id": world["contract_id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [world["first_deviation"]["id"]]
