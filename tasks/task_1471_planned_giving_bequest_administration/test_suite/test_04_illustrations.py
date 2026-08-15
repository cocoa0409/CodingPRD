"""Illustrations: computed provisional figures, supersession, booking, pinning."""
from test_helpers import (
    ILL_AGE105_DEDUCTION_CENTS,
    ILL_AGE70_DEDUCTION_CENTS,
    ILL_JOINT_75_70_DEDUCTION_CENTS,
    ApiErrorId,
    assert_illustration,
    make_active_rate_table,
    make_donor,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestIllustrationComputedFields:
    def test_illustration_computed_fields_on_create(self, api, gift_officer_headers):
        """PRD §3.2: "An illustration is born `OPEN` and immediately carries two
        computed figures: `illustrated_annual_annuity_cents` — the provisional
        annual annuity, null for `BEQUEST` — and `illustrated_deduction_cents`,
        the provisional charitable deduction computed under the pinned table at
        illustration time using the same actuarial method described for
        execution in §3.3."

        Design: Corner/entities/illustration_computed_fields_on_create
        """
        donor = make_donor(full_name="Computed")
        table = make_active_rate_table()
        resp = api.create_illustration(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CGA",
                "gift_amount_cents": 10000000,
                "payout_rate_bps": 600,
                "payment_frequency": "QUARTERLY",
                "lives": 1,
                "annuitant_1_age": 70,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        data = validate_success(resp, 201)
        assert_illustration(data)
        assert data["status"] == "OPEN"
        assert data["illustrated_annual_annuity_cents"] == 600000
        assert data["illustrated_deduction_cents"] == ILL_AGE70_DEDUCTION_CENTS
        assert data["rate_table_id"] == table["id"]

    def test_age_floor_constants_applied(self, api, gift_officer_headers):
        """PRD §3.3: "For an annuitant of a given age, the term length is 100
        minus that age, floored at a minimum of 1."

        Design: Corner/calculations/age_floor_constants_applied
        """
        donor = make_donor(full_name="Centenarian", date_of_birth="1921-01-01T00:00:00Z")
        make_active_rate_table()
        resp = api.create_illustration(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CGA",
                "gift_amount_cents": 10000000,
                "payout_rate_bps": 600,
                "lives": 1,
                "annuitant_1_age": 105,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        data = validate_success(resp, 201)
        # n = max(1, 100-105) = 1; factor a(1)@5% = 0.9523809524...;
        # pv = round_half_up(600000 * 0.9523809524) = 571429; deduction follows.
        assert data["illustrated_annual_annuity_cents"] == 600000
        assert data["illustrated_deduction_cents"] == ILL_AGE105_DEDUCTION_CENTS


class TestJointLivesDeduction:
    def _setup(self, api):
        donor = make_donor(full_name="Joint Lives", date_of_birth="1951-05-01T00:00:00Z")
        table = make_active_rate_table()
        return donor, table

    def test_joint_lives_deduction_value(self, api, gift_officer_headers):
        """PRD §3.3: "a two-life gift sums the two single-life factors and
        subtracts the factor evaluated at the older of the two ages."
        PRD §3.3: "The charitable deduction is `gift_amount_cents` minus that
        present value, floored at zero".

        Design: Difficulty/combinatorial_formula/charitable_deduction_joint_lives_mode_a
        """
        donor, _table = self._setup(api)
        resp = api.create_illustration(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CRT_ANNUITY",
                "gift_amount_cents": 10000000,
                "payout_rate_bps": 500,
                "payment_frequency": "ANNUAL",
                "lives": 2,
                "annuitant_1_age": 75,
                "annuitant_2_age": 70,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        data = validate_success(resp, 201)
        # factor = a(25) + a(30) - a(25) = a(30) = 15.3724510269 at 5%;
        # pv = round_half_up(500000 * factor) = 7686226; deduction = 2313774.
        assert data["illustrated_annual_annuity_cents"] == 500000
        assert data["illustrated_deduction_cents"] == ILL_JOINT_75_70_DEDUCTION_CENTS
        # The ten-percent remainder floor passes on these inputs.
        assert data["illustrated_deduction_cents"] * 10 >= data["gift_amount_cents"]

    def test_joint_lives_illustration_pins_covering_rate_table(
        self, api, gift_officer_headers
    ):
        """PRD §3.2: "At creation the system pins the `ACTIVE` rate table whose
        window covers `funding_month` into `rate_table_id`, or rejects the
        illustration with `ERR_RATE_TABLE_NOT_ACTIVE` when no table covers that
        month."

        Design: Difficulty/combinatorial_formula/charitable_deduction_joint_lives_mode_a
        """
        donor, table = self._setup(api)
        resp = api.create_illustration(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CRT_ANNUITY",
                "gift_amount_cents": 10000000,
                "payout_rate_bps": 500,
                "payment_frequency": "ANNUAL",
                "lives": 2,
                "annuitant_1_age": 75,
                "annuitant_2_age": 70,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        data = validate_success(resp, 201)
        assert data["rate_table_id"] == table["id"]
        assert data["status"] == "OPEN"


class TestIllustrationSupersession:
    def test_illustration_supersession_flips_predecessor(self, api, gift_officer_headers):
        """PRD §3.2: "If a new illustration is created with
        `supersedes_illustration_id` pointing at an existing `OPEN`
        illustration, the referenced illustration flips to `SUPERSEDED` as a
        side effect of the creation (its `version` increments)."

        Design: Corner/entities/illustration_supersession_flips_predecessor
        """
        donor = make_donor(full_name="Supersede")
        make_active_rate_table()
        first = validate_success(
            api.create_illustration(
                {
                    "donor_id": donor["id"],
                    "vehicle_type": "CGA",
                    "gift_amount_cents": 5000000,
                    "payout_rate_bps": 600,
                    "lives": 1,
                    "annuitant_1_age": 72,
                    "funding_month": "2026-08",
                },
                gift_officer_headers,
            ),
            201,
        )
        assert first["status"] == "OPEN"

        second = validate_success(
            api.create_illustration(
                {
                    "donor_id": donor["id"],
                    "vehicle_type": "CGA",
                    "gift_amount_cents": 6000000,
                    "payout_rate_bps": 600,
                    "lives": 1,
                    "annuitant_1_age": 72,
                    "funding_month": "2026-08",
                    "supersedes_illustration_id": first["id"],
                },
                gift_officer_headers,
            ),
            201,
        )
        assert second["status"] == "OPEN"
        predecessor = validate_success(
            api.get_illustration(first["id"], gift_officer_headers)
        )
        assert predecessor["status"] == "SUPERSEDED"


class TestIllustrationBooking:
    def test_illustration_book_is_single_shot(self, api, gift_officer_headers):
        """PRD §3.2: "Both terminal states — `BOOKED` and `SUPERSEDED` — are
        locked against further transitions with `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.2: booking "moves the illustration to the terminal `BOOKED`
        status and creates a `GiftAgreement` in `DRAFT`".

        Design: Corner/state_machines/illustration_book_is_single_shot
        """
        donor = make_donor(full_name="Book Once")
        make_active_rate_table()
        illustration = validate_success(
            api.create_illustration(
                {
                    "donor_id": donor["id"],
                    "vehicle_type": "CGA",
                    "gift_amount_cents": 5000000,
                    "payout_rate_bps": 600,
                    "lives": 1,
                    "annuitant_1_age": 72,
                    "funding_month": "2026-08",
                },
                gift_officer_headers,
            ),
            201,
        )
        agreement = validate_success(
            api.book_illustration(illustration["id"], gift_officer_headers), 201
        )
        assert agreement["status"] == "DRAFT"
        assert agreement["illustration_id"] == illustration["id"]

        resp = api.book_illustration(illustration["id"], gift_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        agreements, meta = validate_paginated(
            api.list_gift_agreements(
                gift_officer_headers, params={"illustration_id": illustration["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert agreements[0]["id"] == agreement["id"]

    def test_illustration_uncovered_funding_month_rejected(self, api, gift_officer_headers):
        """PRD §3.2: "At creation the system pins the `ACTIVE` rate table whose
        window covers `funding_month` into `rate_table_id`, or rejects the
        illustration with `ERR_RATE_TABLE_NOT_ACTIVE` when no table covers that
        month."

        Design: Corner/validations/illustration_uncovered_funding_month_rejected
        """
        donor = make_donor(full_name="Uncovered")
        make_active_rate_table(
            label="T",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-12-01T00:00:00Z",
        )
        resp = api.create_illustration(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CGA",
                "gift_amount_cents": 10000000,
                "payout_rate_bps": 600,
                "lives": 1,
                "annuitant_1_age": 70,
                "funding_month": "2027-03",
            },
            gift_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_TABLE_NOT_ACTIVE)
        assert resp.status_code == 409
