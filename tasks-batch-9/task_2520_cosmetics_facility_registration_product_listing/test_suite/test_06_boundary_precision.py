"""Inclusive endpoints probed from both sides: the restricted-posture points
threshold reached by one lateness step, and the two fragrance-allergen
disclosure thresholds that depend on the product form.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import make_responsible_person_agent_headers
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X

INTAKE_INSTANT = "2026-08-06T00:00:00Z"
LOW_RECEIVED_AT = "2026-08-05T10:00:00Z"
HIGH_RECEIVED_AT = "2026-08-04T10:00:00Z"
FILING_INSTANT = "2026-08-29T12:00:00Z"


def _two_establishments_one_lateness_step_apart(api):
    """Two establishments, one serious event each, deadlines a day apart.

    Filed together at 2026-08-29T12:00:00Z, one report is nine whole days late
    and the other ten.
    """
    low = X.create_registered_facility(
        api, facility_name="Fenwick Low Line", owner_operator_name="Fenwick Co",
        state_or_province="MA",
    )
    high = X.create_registered_facility(
        api, facility_name="Fenwick High Line", owner_operator_name="Fenwick Co",
        state_or_province="MA",
    )
    person = X.create_responsible_person(api, legal_name="Fenwick Brands LLC")
    agent = make_responsible_person_agent_headers(person["id"])
    low_listing = X.create_draft_listing(
        api, low["id"], person["id"],
        product_name="Fenwick Suntan Gel", category_code="12A",
        label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
        label_contact_value="care@fenwick.example",
    )
    high_listing = X.create_draft_listing(
        api, high["id"], person["id"],
        product_name="Fenwick Baby Shampoo", category_code="01A",
        product_form=K.PRODUCT_FORM_RINSE_OFF,
        label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
        label_contact_value="care@fenwick.example",
    )

    X.set_clock(api, INTAKE_INSTANT)
    low_event = X.record_serious_event(api, low_listing["id"], agent, LOW_RECEIVED_AT)
    high_event = X.record_serious_event(api, high_listing["id"], agent, HIGH_RECEIVED_AT)
    assert low_event["report_status"] == K.EVENT_STATUS_REPORT_DUE
    assert high_event["report_status"] == K.EVENT_STATUS_REPORT_DUE

    X.set_clock(api, FILING_INSTANT)
    return {
        "low_facility_id": low["id"],
        "high_facility_id": high["id"],
        "low_filed": X.file_report(api, low_event["id"], agent),
        "high_filed": X.file_report(api, high_event["id"], agent),
    }


class TestSeriousEventPointsAtTheRestrictedThreshold:
    """9.50 stays open, 10.00 is restricted, and 0.50 separates them."""

    def test_nine_days_late_leaves_the_establishment_just_below_the_endpoint(self, api):
        """A deadline of 2026-08-20T23:59:59.999Z overrun to 2026-08-29T12:00:00Z is eight
        and a half days, which rounds up to nine, so the factor is 1.9 and the late base of
        five scores 9.50 — below the inclusive threshold, so the posture is untouched and
        the abbreviated renewal path is still open.

        PRD: "The lateness factor is one plus a tenth per day of lateness, capped at 2.0, so lateness stops accruing at ten days."
        PRD: "A newly created establishment begins with `registration_status` at `DRAFT`, `compliance_posture` at `OPEN`, `serious_event_points` at 0.00, `registration_cycle_count` at 0, `abbreviated_renewal_eligible` true, `listed_product_count` and `open_serious_event_count` at 0, and `facility_fei`, `gmp_readiness_score`, `last_inspection_outcome`, `current_period_start`, `current_period_end`, `renewal_window_open_date` and `grace_end_date` all null."

        Design: Difficulty/boundary_precision_check/serious_event_points_inclusive_at_restricted_threshold_across_two_facilities
        """
        state = _two_establishments_one_lateness_step_apart(api)

        filed = state["low_filed"]
        assert filed["lateness_days"] == 9
        A.assert_deadline_at_end_of_day(filed["deadline_at"], "2026-08-20")
        A.assert_two_decimal_value(filed["event_points"], 9.50, "event_points")

        facility = X.read_facility(api, state["low_facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 9.50, "serious_event_points")
        assert facility["serious_event_points"] != 10.00
        assert facility["compliance_posture"] == K.POSTURE_OPEN
        assert facility["abbreviated_renewal_eligible"] is True

    def test_ten_days_late_sits_exactly_on_the_inclusive_endpoint(self, api):
        """One day earlier in intake means one more day of lateness: the factor reaches its
        cap of 2.0, the event scores exactly 10.00, and the comparison being inclusive at
        the boundary makes the establishment restricted.

        PRD: "The points component of the posture is `FROZEN` at 25.00 or more, `RESTRICTED` at 10.00 or more, and `OPEN` below that, with both comparisons inclusive at the boundary and made against the two-decimal stored value: 9.50 leaves the establishment `OPEN`, 10.00 exactly makes it `RESTRICTED`, 24.99 is still `RESTRICTED` and 25.00 is `FROZEN`."

        Design: Difficulty/boundary_precision_check/serious_event_points_inclusive_at_restricted_threshold_across_two_facilities
        """
        state = _two_establishments_one_lateness_step_apart(api)

        filed = state["high_filed"]
        assert filed["lateness_days"] == 10
        A.assert_deadline_at_end_of_day(filed["deadline_at"], "2026-08-19")
        A.assert_two_decimal_value(filed["event_points"], 10.00, "event_points")

        facility = X.read_facility(api, state["high_facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 10.00, "serious_event_points")
        assert facility["compliance_posture"] == K.POSTURE_RESTRICTED

    def test_one_lateness_step_separates_two_otherwise_identical_establishments(self, api):
        """Both establishments carry one late serious report and nothing else, yet their
        postures differ: the whole difference is the half-point that one extra day of
        lateness adds.

        PRD: "An event contributes only while its `report_status` is `REPORTED_TIMELY`, `REPORTED_LATE` or `REPORT_OVERDUE`; events that are `RECORDED`, `RETAINED` or still `REPORT_DUE` contribute exactly 0.00, which is the important asymmetry — a serious event inside its deadline costs the establishment nothing, and the cost appears the moment the deadline is missed or the report is filed."

        Design: Difficulty/boundary_precision_check/serious_event_points_inclusive_at_restricted_threshold_across_two_facilities
        """
        state = _two_establishments_one_lateness_step_apart(api)

        assert state["low_filed"]["report_status"] == K.EVENT_STATUS_REPORTED_LATE
        assert state["high_filed"]["report_status"] == K.EVENT_STATUS_REPORTED_LATE
        A.assert_two_decimal_value(
            state["high_filed"]["event_points"] - state["low_filed"]["event_points"],
            0.50, "points spread",
        )

        low = X.read_facility(api, state["low_facility_id"])
        high = X.read_facility(api, state["high_facility_id"])
        assert low["open_serious_event_count"] == high["open_serious_event_count"] == 0
        assert low["compliance_posture"] != high["compliance_posture"]


def _three_listings_probing_both_thresholds(api):
    """A leave-on listing, a rinse-off listing and an empty listing.

    The leave-on listing is probed at 0.0010 and 0.0009 percent, the rinse-off
    listing at the same 0.0010 and at 0.0100 percent, and the third listing is
    left without ingredients at all.
    """
    facility = X.create_registered_facility(
        api, facility_name="Marlow Scent Works", owner_operator_name="Marlow Inc",
        facility_type="PROCESSOR", state_or_province="CA",
    )
    person = X.create_responsible_person(api, legal_name="Marlow Brands LLC")
    agent = make_responsible_person_agent_headers(person["id"])

    def _listing(product_name, category_code, product_form):
        return X.create_draft_listing(
            api, facility["id"], person["id"],
            product_name=product_name,
            category_code=category_code,
            product_form=product_form,
            label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            label_contact_value="care@marlow.example",
        )

    leave_on = _listing("Marlow Leave-On Blush", "07A", K.PRODUCT_FORM_LEAVE_ON)
    rinse_off = _listing("Marlow Rinse-Off Bath Oil", "02C", K.PRODUCT_FORM_RINSE_OFF)
    empty = _listing("Marlow Unscented Balm", "07A", K.PRODUCT_FORM_LEAVE_ON)

    return {
        "agent": agent,
        "leave_on_id": leave_on["id"],
        "rinse_off_id": rinse_off["id"],
        "empty_id": empty["id"],
        "leave_on_at_threshold": X.add_ingredient(
            api, leave_on["id"], agent,
            F.allergen_ingredient_payload("LINALOOL", 0.0010),
        ),
        "leave_on_below": X.add_ingredient(
            api, leave_on["id"], agent,
            F.allergen_ingredient_payload("CITRAL", 0.0009),
        ),
        "rinse_off_below": X.add_ingredient(
            api, rinse_off["id"], agent,
            F.allergen_ingredient_payload("LINALOOL", 0.0010),
        ),
        "rinse_off_at_threshold": X.add_ingredient(
            api, rinse_off["id"], agent,
            F.allergen_ingredient_payload("GERANIOL", 0.0100),
        ),
    }


class TestFragranceAllergenDisclosureThresholds:
    """Each product form's threshold, probed at it and one step below it."""

    def test_the_leave_on_threshold_is_inclusive_and_one_step_below_is_exempt(self, api):
        """On a leave-on product an undisclosed allergen at exactly 0.0010 percent must be
        named, while the same substance at 0.0009 percent need not be — the comparison is
        inclusive and made against the stored four-decimal value.

        PRD: "The disclosure threshold is a concentration of **0.001 percent** for a `LEAVE_ON` listing and **0.01 percent** for a `RINSE_OFF` listing."
        PRD: "For each ingredient of the listing, `disclosure_required` is true when all three of the following hold: `is_fragrance_allergen` is true, `concentration_pct` is at or above the applicable threshold — the comparison is inclusive, and it is made against the stored four-decimal value — and the listing's `professional_use_only` is false."

        Design: Difficulty/boundary_precision_check/fragrance_allergen_thresholds_inclusive_per_product_form_and_vacuous_set
        """
        state = _three_listings_probing_both_thresholds(api)

        assert state["leave_on_at_threshold"]["disclosure_required"] is True
        assert state["leave_on_below"]["disclosure_required"] is False

        listing = X.read_listing(api, state["leave_on_id"])
        assert listing["undisclosed_allergen_count"] == 1
        assert listing["allergen_disclosure_complete"] is False

    def test_the_same_concentration_is_exempt_on_a_rinse_off_product(self, api):
        """0.0010 percent crosses the leave-on threshold but not the rinse-off one, and the
        rinse-off threshold is itself inclusive at 0.0100 percent, so only the second row of
        the rinse-off listing has to be named.

        PRD: "Worked through concretely: a `LEAVE_ON` listing carrying an undisclosed allergen at 0.0010 percent has `disclosure_required` true on that row, `undisclosed_allergen_count` 1 and `allergen_disclosure_complete` false; the same row at 0.0009 percent falls below the leave-on threshold and the listing is complete; that same 0.0010 percent row inside a `RINSE_OFF` listing is also below its threshold and the listing is complete, while a `RINSE_OFF` listing with an undisclosed allergen at 0.0100 percent is incomplete; and an undisclosed allergen at 0.5000 percent on a professional-use-only listing is exempt, so the listing is complete."

        Design: Difficulty/boundary_precision_check/fragrance_allergen_thresholds_inclusive_per_product_form_and_vacuous_set
        """
        state = _three_listings_probing_both_thresholds(api)

        assert state["rinse_off_below"]["disclosure_required"] is False
        assert state["rinse_off_at_threshold"]["disclosure_required"] is True

        listing = X.read_listing(api, state["rinse_off_id"])
        assert listing["undisclosed_allergen_count"] == 1
        assert listing["allergen_disclosure_complete"] is False

    def test_a_listing_with_no_ingredients_at_all_is_complete(self, api):
        """The empty required set resolves to complete rather than incomplete: with nothing
        on the ingredient inventory there is nothing to disclose.

        PRD: "The vacuous case must resolve to complete, not incomplete: a listing with no ingredients at all, a listing whose fragrance allergens all sit below the threshold, and a professional-use-only listing all report `undisclosed_allergen_count` 0 and `allergen_disclosure_complete` true."

        Design: Difficulty/boundary_precision_check/fragrance_allergen_thresholds_inclusive_per_product_form_and_vacuous_set
        """
        state = _three_listings_probing_both_thresholds(api)

        listing = X.read_listing(api, state["empty_id"])
        assert listing["undisclosed_allergen_count"] == 0
        assert listing["allergen_disclosure_complete"] is True

        rows, _meta = validate_paginated(
            api.list_ingredients(state["empty_id"], state["agent"])
        )
        assert rows == []

    def test_the_allergen_filter_returns_both_rows_with_only_one_requiring_disclosure(
        self, api
    ):
        """Both leave-on rows are on the fragrance-allergen list, so the filtered read
        returns both in creation order, and the computed flag distinguishes them.

        PRD: "The listing's ingredients are read back in ascending `created_at` order, optionally narrowed by an `is_fragrance_allergen` filter, and each row carries its computed `disclosure_required`."

        Design: Difficulty/boundary_precision_check/fragrance_allergen_thresholds_inclusive_per_product_form_and_vacuous_set
        """
        state = _three_listings_probing_both_thresholds(api)

        rows, _meta = validate_paginated(
            api.list_ingredients(
                state["leave_on_id"], state["agent"], {"is_fragrance_allergen": True}
            )
        )

        assert [row["inci_name"] for row in rows] == ["LINALOOL", "CITRAL"]
        assert [row["disclosure_required"] for row in rows] == [True, False]
        assert all(row["label_disclosed"] is False for row in rows)
