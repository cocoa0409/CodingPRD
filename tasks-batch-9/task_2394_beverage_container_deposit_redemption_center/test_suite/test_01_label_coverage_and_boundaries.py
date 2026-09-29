"""Inclusive bounds and empty-collection edges.

The covered-container volume clause, the exemption radius test and the
empty-lot close-count all sit exactly on a declared bound; each test here pins
the value on the bound and the value one step past it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_account_standing,
    assert_center_pool,
    assert_coverage,
    assert_distance_precision,
    assert_fraud_posture,
    assert_stamped_at,
    assert_visit_valuation,
    make_center_headers,
    make_distributor_headers,
    make_retailer_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


class TestFillVolumeUpperBound:
    """The volume clause is inclusive at 3000 millilitres."""

    def test_label_of_exactly_three_thousand_millilitres_is_covered(self, api):
        """A 3000 ml label clears the volume clause and earns the standard deposit.

        PRD: "Otherwise, the labelled fill volume must fall between 118 millilitres
        and 3000 millilitres, **inclusive at both ends**." — "Exactly 118 and exactly
        3000 both pass."

        Design: Difficulty/boundary_precision_check/fill_volume_3000_covered_and_3001_not_covered
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_draft_product(
            api,
            distributor["id"],
            brand_name="Cascade Growler 3000",
            fill_volume_ml=3000,
            upc="011110003000",
        )

        response = api.post_registration_action(
            product["id"],
            f.registration_action_payload("SUBMIT"),
            make_distributor_headers(distributor["id"]),
        )
        submitted = validate_success(response)

        assert submitted["registration_state"] == "SUBMITTED"
        assert_coverage(submitted, "COVERED", "COVERED_STANDARD", 10)

    def test_label_of_three_thousand_and_one_millilitres_is_not_covered(self, api):
        """A 3001 ml label fails the volume clause and carries no deposit.

        PRD: "A volume below 118 or above 3000 yields `NOT_COVERED` with
        `coverage_reason` `VOLUME_OUT_OF_RANGE`."

        Design: Difficulty/boundary_precision_check/fill_volume_3000_covered_and_3001_not_covered
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_draft_product(
            api,
            distributor["id"],
            brand_name="Cascade Growler 3001",
            fill_volume_ml=3001,
            upc="011110003001",
        )

        response = api.post_registration_action(
            product["id"],
            f.registration_action_payload("SUBMIT"),
            make_distributor_headers(distributor["id"]),
        )
        submitted = validate_success(response)

        assert submitted["registration_state"] == "SUBMITTED"
        assert_coverage(submitted, "NOT_COVERED", "VOLUME_OUT_OF_RANGE", 0)


class TestExemptionRadius:
    """The exemption radius test is non-strict on the rounded distance."""

    CENTER_OVERRIDES = {
        "site_name": "Redmond Redemption Center",
        "x_miles": 2.10,
        "y_miles": 2.80,
        "accepts_all_materials": True,
        "daily_account_cap_containers": 300,
        "opening_cash_cents": 50000,
    }

    def test_store_at_exactly_three_and_a_half_miles_becomes_exempt(self, api):
        """A store 3.50 miles from the only candidate centre is granted relief.

        PRD: "the radius test is non-strict, so a centre at exactly 3.50 miles grants
        the exemption. On success the server writes `nearest_center_id` and
        `nearest_center_distance_miles` from the selected centre and stamps
        `exemption_granted_at` with the current logical instant."

        Design: Difficulty/boundary_precision_check/exemption_distance_boundary_3_50_grants_and_3_52_denied
        """
        h.set_clock(api, INSTANT)
        center = h.create_operational_center(api, dict(self.CENTER_OVERRIDES))["center"]
        retailer = h.create_retailer(
            api, store_name="Near Market", x_miles=0.00, y_miles=0.00, store_area_sqft=6000
        )

        response = api.post_exemption_action(
            retailer["id"],
            f.exemption_action_payload("CLAIM_EXEMPTION"),
            make_retailer_headers(retailer["id"]),
        )
        exempt = validate_success(response)

        assert exempt["obligation_status"] == "EXEMPT"
        assert exempt["nearest_center_id"] == center["id"]
        assert exempt["nearest_center_distance_miles"] == 3.5
        assert_distance_precision(exempt["nearest_center_distance_miles"])
        assert_stamped_at(exempt["exemption_granted_at"], INSTANT)

    def test_store_rounding_to_three_point_five_two_miles_is_refused(self, api):
        """A store whose rounded distance is 3.52 miles keeps its obligation.

        PRD: "If the selected centre's rounded distance is greater than 3.50 miles the
        claim is refused with `ERR_EXEMPTION_DISTANCE_EXCEEDED`".

        Design: Difficulty/boundary_precision_check/exemption_distance_boundary_3_50_grants_and_3_52_denied
        """
        h.set_clock(api, INSTANT)
        h.create_operational_center(api, dict(self.CENTER_OVERRIDES))
        retailer = h.create_retailer(
            api, store_name="Far Market", x_miles=0.00, y_miles=-0.03, store_area_sqft=6000
        )

        response = api.post_exemption_action(
            retailer["id"],
            f.exemption_action_payload("CLAIM_EXEMPTION"),
            make_retailer_headers(retailer["id"]),
        )
        validate_error(response, ApiErrorId.ERR_EXEMPTION_DISTANCE_EXCEEDED.value)

        stored = h.read_retailer(api, retailer["id"], make_retailer_headers(retailer["id"]))
        assert stored["obligation_status"] == "OBLIGATED"
        assert stored["nearest_center_id"] is None
        assert stored["nearest_center_distance_miles"] is None
        assert stored["daily_limit_containers"] == 50


class TestEmptyLotSetCloseCount:
    """Closing a visit that never received a lot is a legitimate zero valuation."""

    def test_close_count_with_no_lots_values_the_visit_at_zero(self, api, world):
        """An empty lot set closes the count and pays nothing.

        PRD: "a visit may legitimately be closed with no lots at all: closing from
        `OPEN → COUNTED` runs the same valuation over an empty lot set, yielding
        `capped_count` 0, `shrink_adjustment_count` 0, `payable_count` 0,
        `refused_over_limit_count` 0 and `payout_cents` 0".

        Design: Difficulty/boundary_precision_check/close_count_over_empty_lot_set_pays_zero
        """
        visit = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )

        response = api.close_count(visit["id"], world.center_headers)
        counted = validate_success(response)

        assert counted["count_status"] == "COUNTED"
        assert_stamped_at(counted["counted_at"], INSTANT)
        assert counted["presented_total"] == 0
        assert counted["raw_accepted_count"] == 0
        assert counted["out_of_state_ratio"] == 0
        assert_visit_valuation(
            counted,
            visit_limit_applied=240,
            capped_count=0,
            shrink_adjustment_count=0,
            payable_count=0,
            refused_over_limit_count=0,
            payout_cents=0,
        )

    def test_empty_close_count_records_no_strike_and_no_accepted_containers(
        self, api, world
    ):
        """The zero close leaves the day's allowance, standing and pool untouched.

        PRD: "No fraud strike is recorded in that case, because a zero
        `presented_total` gives an `out_of_state_ratio` of 0 and a `raw_accepted_count`
        of 0 cannot exceed any allowance."

        Design: Difficulty/boundary_precision_check/close_count_over_empty_lot_set_pays_zero
        """
        visit = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )
        counted = h.close_count(api, visit["id"], world.center_headers)

        assert_fraud_posture(
            counted, fraud_hold=False, withhold_reason=None, payout_status="PENDING"
        )

        account = h.read_account(api, world.account_id, world.account_headers)
        assert account["containers_redeemed_today"] == 0
        assert account["cap_reached_today"] is False
        assert_account_standing(account, "ACTIVE", 0, None)

        center = h.read_center(api, world.center_id, world.center_headers)
        assert_center_pool(center, accepted_container_count=0)


class TestSuspendedLabelGovernsLotAdmission:
    """A lot's admissibility is decided by a state that lives on the label."""

    @staticmethod
    def _suspended_label_world(api):
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(
            api, distributor["id"], brand_name="Cascade Spring"
        )
        fleet = h.create_operational_center(
            api,
            {
                "site_name": "Bend Redemption Center",
                "daily_account_cap_containers": 300,
                "opening_cash_cents": 50000,
            },
        )
        return product, fleet["center"], fleet["machine"]

    def test_lot_add_is_refused_once_the_label_is_suspended(self, api):
        """Suspending the label turns a previously good lot request into a refusal.

        PRD: "The label named by `product_id` has `registration_state` `REGISTERED` →
        otherwise `ERR_PRODUCT_NOT_REGISTERED` (HTTP 422). Applies to lot addition and
        deposit initiation."

        Design: Difficulty/cross_entity_state_dependency/lot_add_rejected_when_product_registration_suspended
        """
        product, center, machine = self._suspended_label_world(api)
        headers = make_center_headers(center["id"])
        api.post_registration_action(
            product["id"],
            f.registration_action_payload("SUSPEND", "label legend under review"),
            h.ADMIN_HEADERS,
        )
        visit = h.open_center_machine_visit(api, center["id"], machine["id"])

        response = api.create_container_lot(
            visit["id"],
            f.create_lot_payload(
                product["id"],
                40,
                visit["version"],
                out_of_state_marked_quantity=0,
                contaminated_quantity=0,
            ),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_REGISTERED.value)

        label = validate_success(api.get_beverage_product(product["id"], h.ADMIN_HEADERS))
        assert label["registration_state"] == "SUSPENDED"
        assert label["deposit_cents"] == 10

    def test_refused_lot_leaves_the_visit_open_with_nothing_presented(self, api):
        """The refusal writes nothing: the visit is still OPEN and holds no lot.

        PRD: "The first accepted lot moves the visit `OPEN → COUNTING`." — a refused
        lot is not an accepted lot, and "Every accepted lot increments the visit's
        `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/lot_add_rejected_when_product_registration_suspended
        """
        product, center, machine = self._suspended_label_world(api)
        headers = make_center_headers(center["id"])
        api.post_registration_action(
            product["id"],
            f.registration_action_payload("SUSPEND", "label legend under review"),
            h.ADMIN_HEADERS,
        )
        visit = h.open_center_machine_visit(api, center["id"], machine["id"])

        response = api.create_container_lot(
            visit["id"],
            f.create_lot_payload(product["id"], 40, visit["version"]),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_REGISTERED.value)

        stored = h.read_visit(api, visit["id"], headers)
        assert stored["count_status"] == "OPEN"
        assert stored["presented_total"] == 0

        lots, meta = validate_paginated(api.list_visit_lots(visit["id"], headers))
        assert meta["total_count"] == 0
        assert lots == []
