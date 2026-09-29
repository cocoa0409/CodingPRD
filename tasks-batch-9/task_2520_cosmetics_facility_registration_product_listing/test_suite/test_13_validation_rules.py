"""Business rules that refuse a well-formed request: registry lookups,
case-folded uniqueness, the conditional labelling gates, the two temporal edges
of the renewal window, relational gates against a parent record, and the
aggregate ceilings that only a running total can breach.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    make_facility_registrant_headers,
    make_responsible_person_agent_headers,
)
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X


def _registered_establishment_and_designee(api):
    """An approved establishment and a designee holding no listing yet."""
    facility = X.create_registered_facility(
        api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        state_or_province="NJ",
    )
    person = X.create_responsible_person(api, legal_name="Aster Brands Inc")
    return facility, person, make_responsible_person_agent_headers(person["id"])


class TestAnUnknownCategoryCodeFailsTheRegistryLookup:
    """A well-shaped code that is simply not in the register of eight."""

    def test_a_code_outside_the_registry_of_eight_is_refused(self, api):
        """The code is the right shape and the establishment is properly approved, so what
        fails is the registry lookup itself.

        PRD: "The declared `category_code` must be one of exactly eight registry codes, matched as a case-sensitive exact string; anything else is `ERR_UNKNOWN_CATEGORY_CODE` (HTTP 422)."
        PRD: "The registry is `01A` (baby shampoos), `02C` (bath oils and salts), `03B` (eyeliner), `05G` (hair straighteners), `07A` (blushers), `08D` (nail extension preparations), `11E` (skin peels) and `12A` (suntan gels and lotions)."

        Design: Corner/validations/unknown_category_code_is_rejected_against_the_registry
        """
        facility, person, agent = _registered_establishment_and_designee(api)

        validate_error(
            api.create_listing(
                F.listing_payload(
                    facility["id"], person["id"],
                    product_name="Aster Mystery Serum", category_code="99Z",
                ),
                agent,
            ),
            E.ERR_UNKNOWN_CATEGORY_CODE,
        )

    def test_the_refused_creation_leaves_the_register_empty(self, api):
        """No product row was minted, so the establishment's listed tally is untouched and the
        register holds nothing for it.

        PRD: "Listings are browsed with any combination of a `facility_id` filter, a `responsible_person_id` filter, a `listing_status` filter and a `safety_status` filter — the two state dimensions are filtered independently because they evolve independently."

        Design: Corner/validations/unknown_category_code_is_rejected_against_the_registry
        """
        facility, person, agent = _registered_establishment_and_designee(api)
        validate_error(
            api.create_listing(
                F.listing_payload(
                    facility["id"], person["id"],
                    product_name="Aster Mystery Serum", category_code="99Z",
                ),
                agent,
            ),
            E.ERR_UNKNOWN_CATEGORY_CODE,
        )

        assert X.read_facility(api, facility["id"])["listed_product_count"] == 0
        rows, meta = validate_paginated(
            api.list_listings(agent, {"facility_id": facility["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestIngredientNamesAreUniquePerListingAndCaseFolded:
    """The same substance name, twice on one product and once on each of two."""

    def _two_products_one_carrying_glycerin(self, api):
        facility, person, agent = _registered_establishment_and_designee(api)
        first = X.create_draft_listing(
            api, facility["id"], person["id"],
            product_name="Aster Blush Powder", category_code="07A",
        )
        second = X.create_draft_listing(
            api, facility["id"], person["id"],
            product_name="Aster Cleansing Gel", category_code="07A",
            product_form=K.PRODUCT_FORM_RINSE_OFF,
        )
        X.add_ingredient(
            api, first["id"], agent, F.ingredient_payload(inci_name="GLYCERIN")
        )
        return agent, first, second

    def test_a_lowercase_repeat_of_a_stored_name_collides(self, api):
        """"glycerin" and the stored "GLYCERIN" differ only in letter case, and the comparison
        folds case, so the second row is refused.

        PRD: "Ingredient names are unique within a listing compared case-insensitively, so a second row whose `inci_name` differs only in letter case is rejected with `ERR_DUPLICATE_INGREDIENT` (HTTP 409)."

        Design: Corner/validations/duplicate_inci_name_is_rejected_case_insensitively_within_one_listing
        """
        agent, first, _second = self._two_products_one_carrying_glycerin(api)

        validate_error(
            api.add_ingredient(
                first["id"], F.ingredient_payload(inci_name="glycerin"), agent
            ),
            E.ERR_DUPLICATE_INGREDIENT,
        )

        rows, meta = validate_paginated(api.list_ingredients(first["id"], agent))
        assert len(rows) == 1
        assert meta["total_count"] == 1

    def test_the_same_name_is_free_on_a_sibling_product(self, api):
        """Uniqueness is scoped to the parent product, so the very name that just collided is
        accepted on the second listing of the same designee.

        PRD: "The listing's ingredients are read back in ascending `created_at` order, optionally narrowed by an `is_fragrance_allergen` filter, and each row carries its computed `disclosure_required`."

        Design: Corner/validations/duplicate_inci_name_is_rejected_case_insensitively_within_one_listing
        """
        agent, _first, second = self._two_products_one_carrying_glycerin(api)

        accepted = X.add_ingredient(
            api, second["id"], agent, F.ingredient_payload(inci_name="glycerin")
        )
        assert accepted["inci_name"] == "glycerin"

        rows, meta = validate_paginated(api.list_ingredients(second["id"], agent))
        assert len(rows) == 1
        assert meta["total_count"] == 1


class TestTheProfessionalUseLabellingConditionGuardsTwoThings:
    """One error code, two independent conditions, and both conditional on the flag."""

    def _substantiated_listing(self, api, facility, person, agent, **listing_overrides):
        listing = X.create_draft_listing(
            api, facility["id"], person["id"], **listing_overrides
        )
        X.dossier_at_decision(api, listing["id"], agent)
        return listing

    def test_a_professional_declaration_under_a_consumer_category_is_refused(self, api):
        """Blushers are not a professional-use category, so an impeccably labelled 07A product
        declared professional-use-only cannot be submitted.

        PRD: "The **professional-use labelling condition** is vacuously satisfied whenever `professional_use_only` is false. When it is true, two things must both hold: `professional_use_statement_present` must also be true, because the label has to actually carry the professional-use-only statement, and the listing's `category_code` must be one of the four professional-use-permitted codes of §3.3."
        PRD: "A listing declared professional-use-only under `07A` is refused however impeccable its label, because blushers are not a professional-use category; a listing under `03B` with the statement present passes."

        Design: Corner/validations/professional_use_labeling_is_rejected_for_the_wrong_category_and_the_missing_statement
        """
        facility, person, agent = _registered_establishment_and_designee(api)
        listing = self._substantiated_listing(
            api, facility, person, agent,
            product_name="Aster Pro Blush", category_code="07A",
            professional_use_only=True, professional_use_statement_present=True,
            label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            label_contact_value="safety@aster.example",
        )

        validate_error(
            api.submit_listing(listing["id"], agent),
            E.ERR_PROFESSIONAL_USE_LABEL_REQUIRED,
        )

        after = X.read_listing(api, listing["id"])
        assert after["listing_status"] == K.LISTING_STATUS_DRAFT
        assert X.read_responsible_person(api, person["id"])["active_designation_count"] == 0

    def test_a_permitted_category_without_the_statement_is_refused_the_same_way(self, api):
        """Skin peels are a professional-use category, but the label does not carry the
        professional-use-only statement, and the same single error code reports it.

        PRD: "Only then do the four safety gates run, in this fixed order: the listing's `safety_status` must be `SUBSTANTIATED`, failing which the submission is refused with `ERR_SUBSTANTIATION_NOT_ADEQUATE` (HTTP 422); `allergen_disclosure_complete` must be true, failing which it is refused with `ERR_ALLERGEN_DISCLOSURE_INCOMPLETE` (HTTP 422); the professional-use labelling condition must hold, failing which it is refused with `ERR_PROFESSIONAL_USE_LABEL_REQUIRED` (HTTP 422); and the label-contact condition must hold, failing which it is refused with `ERR_LABEL_CONTACT_REQUIRED` (HTTP 422)."

        Design: Corner/validations/professional_use_labeling_is_rejected_for_the_wrong_category_and_the_missing_statement
        """
        facility, person, agent = _registered_establishment_and_designee(api)
        listing = self._substantiated_listing(
            api, facility, person, agent,
            product_name="Aster Pro Peel 30", category_code="11E",
            professional_use_only=True, professional_use_statement_present=False,
            label_contact_type=K.LABEL_CONTACT_DOMESTIC_PHONE,
            label_contact_value="+1-202-555-0110",
        )

        validate_error(
            api.submit_listing(listing["id"], agent),
            E.ERR_PROFESSIONAL_USE_LABEL_REQUIRED,
        )

    def test_the_condition_is_vacuous_once_the_flag_is_false(self, api):
        """The identical consumer category passes the gate the moment the professional-use
        declaration is dropped, which is what makes the rule conditional rather than a flat
        restriction on the category.

        PRD: "On success the listing moves to `SUBMITTED`, the designee's `active_designation_count` rises by 1 and its `status` becomes `ACTIVE`, one `STATE_TRANSITION` ledger entry is appended against the listing, and the `version` of both the listing and the designee rises by exactly 1."

        Design: Corner/validations/professional_use_labeling_is_rejected_for_the_wrong_category_and_the_missing_statement
        """
        facility, person, agent = _registered_establishment_and_designee(api)
        listing = self._substantiated_listing(
            api, facility, person, agent,
            product_name="Aster Blush Powder", category_code="07A",
            label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
            label_contact_value="safety@aster.example",
        )

        submitted = get_success_data(api.submit_listing(listing["id"], agent))

        assert submitted["professional_use_only"] is False
        assert submitted["listing_status"] == K.LISTING_STATUS_SUBMITTED
        designee = X.read_responsible_person(api, person["id"])
        assert designee["active_designation_count"] == 1
        assert designee["status"] == K.RP_STATUS_ACTIVE


class TestAPhoneNumberAloneIsNotAConsumerIntakeChannel:
    """The contact channel rule is asymmetric between the two markets."""

    def _substantiated_listing(self, api, facility, person, agent, **listing_overrides):
        listing = X.create_draft_listing(
            api, facility["id"], person["id"], **listing_overrides
        )
        X.dossier_at_decision(api, listing["id"], agent)
        return listing

    def test_a_consumer_product_reachable_only_by_phone_cannot_be_submitted(self, api):
        """The phone number is perfectly well formed; it is simply not an acceptable
        adverse-event intake channel for a product sold to the public.

        PRD: "A consumer listing — `professional_use_only` false — satisfies the requirement only with `label_contact_type` `DOMESTIC_ADDRESS` or `ELECTRONIC_CONTACT`; a phone number alone is not an acceptable adverse-event intake channel for a consumer product, so `DOMESTIC_PHONE` on a consumer listing is refused."

        Design: Corner/validations/phone_only_label_contact_is_rejected_for_a_consumer_listing
        """
        facility, person, agent = _registered_establishment_and_designee(api)
        listing = self._substantiated_listing(
            api, facility, person, agent,
            product_name="Aster Blush Powder", category_code="07A",
            label_contact_type=K.LABEL_CONTACT_DOMESTIC_PHONE,
            label_contact_value="+1-202-555-0110",
        )

        validate_error(
            api.submit_listing(listing["id"], agent), E.ERR_LABEL_CONTACT_REQUIRED
        )
        assert X.read_listing(api, listing["id"])["listing_status"] == K.LISTING_STATUS_DRAFT

    def test_a_postal_address_carries_the_same_consumer_product_through(self, api):
        """Swapping the channel — and nothing else — satisfies the gate, so the channel was
        the whole objection.

        PRD: "In both cases `label_contact_value` must be non-blank."

        Design: Corner/validations/phone_only_label_contact_is_rejected_for_a_consumer_listing
        """
        facility, person, agent = _registered_establishment_and_designee(api)
        listing = self._substantiated_listing(
            api, facility, person, agent,
            product_name="Aster Blush Powder", category_code="07A",
            label_contact_type=K.LABEL_CONTACT_DOMESTIC_ADDRESS,
            label_contact_value="12 Market St, Newark NJ 07102",
        )

        submitted = get_success_data(api.submit_listing(listing["id"], agent))
        assert submitted["label_contact_type"] == K.LABEL_CONTACT_DOMESTIC_ADDRESS
        assert submitted["listing_status"] == K.LISTING_STATUS_SUBMITTED

    def test_the_trade_may_be_reached_by_telephone(self, api):
        """The very channel that was refused for the consumer product is accepted once the
        product is professional-use-only, because the trade is expected to be able to call.

        PRD: "A professional-use listing may use any of the three channels, `DOMESTIC_PHONE` included, since the trade is expected to be able to place a call."

        Design: Corner/validations/phone_only_label_contact_is_rejected_for_a_consumer_listing
        """
        facility, person, agent = _registered_establishment_and_designee(api)
        listing = self._substantiated_listing(
            api, facility, person, agent,
            product_name="Aster Pro Peel 30", category_code="11E",
            professional_use_only=True, professional_use_statement_present=True,
            label_contact_type=K.LABEL_CONTACT_DOMESTIC_PHONE,
            label_contact_value="+1-202-555-0110",
        )

        submitted = get_success_data(api.submit_listing(listing["id"], agent))
        assert submitted["label_contact_type"] == K.LABEL_CONTACT_DOMESTIC_PHONE
        assert submitted["professional_use_only"] is True
        assert submitted["listing_status"] == K.LISTING_STATUS_SUBMITTED


DAY_BEFORE_THE_WINDOW_OPENS = "2028-05-01T00:00:00Z"
THE_DAY_THE_WINDOW_OPENS = "2028-05-02T00:00:00Z"
DAY_AFTER_GRACE_ENDS = "2028-09-30T00:00:00Z"
SUCCESSOR_PERIOD_START = "2028-08-01"
SUCCESSOR_PERIOD_END = "2030-07-31"


def _file_renewal(api, facility_id, renewal_kind=K.RENEWAL_KIND_STANDARD):
    """The registrant files a renewal of the named kind for its own establishment."""
    return api.file_renewal(
        facility_id, F.renewal_payload(renewal_kind),
        make_facility_registrant_headers(facility_id),
    )


class TestBothTemporalEdgesOfTheRenewalWindow:
    """The window opens inclusively and the grace period closes the door."""

    def test_the_two_derived_dates_bracket_the_filing_season(self, api):
        """The establishment approved on 2026-08-01 is covered to 2028-07-31 and may file from
        2028-05-02 until 2028-09-29 inclusive.

        PRD: "The establishment mirrors the currently active period so that clients need not join: `current_period_start` and `current_period_end` copy the active period's bounds, and `renewal_window_open_date` and `grace_end_date` copy its two derived dates."

        Design: Corner/validations/renewal_window_opens_inclusively_and_the_grace_period_closes_the_door
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        )

        A.assert_facility_period_mirror(
            facility, K.CANONICAL_PERIOD_START, K.CANONICAL_PERIOD_END,
            K.CANONICAL_RENEWAL_WINDOW_OPEN_DATE, K.CANONICAL_GRACE_END_DATE,
        )

    def test_one_day_early_is_refused_and_the_open_date_itself_is_accepted(self, api):
        """2028-05-01 is outside the window and 2028-05-02 is inside it, so the boundary is
        inclusive of the open date itself.

        PRD: "then the UTC calendar date of the logical clock must be on or after `renewal_window_open_date`, or the request fails with `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 422); then that same date must be on or before `grace_end_date`, or the request fails with `ERR_GRACE_PERIOD_EXPIRED` (HTTP 422); and last, an `ABBREVIATED` renewal additionally requires `abbreviated_renewal_eligible` to be true, or the request fails with `ERR_ABBREVIATED_RENEWAL_NOT_ELIGIBLE` (HTTP 422)."

        Design: Corner/validations/renewal_window_opens_inclusively_and_the_grace_period_closes_the_door
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        )

        X.set_clock(api, DAY_BEFORE_THE_WINDOW_OPENS)
        validate_error(_file_renewal(api, facility["id"]), E.ERR_RENEWAL_WINDOW_NOT_OPEN)

        X.set_clock(api, THE_DAY_THE_WINDOW_OPENS)
        successor = get_success_data(_file_renewal(api, facility["id"]))

        assert successor["period_start"] == SUCCESSOR_PERIOD_START
        assert successor["period_kind"] == K.PERIOD_KIND_RENEWAL
        assert successor["sequence_index"] == 2
        assert X.read_facility(api, facility["id"])["registration_cycle_count"] == 2

    def test_one_day_past_the_grace_end_leaves_the_establishment_unrenewed(self, api):
        """A day beyond 2028-09-29 the door is shut: the refusal is not recoverable and the
        establishment still holds nothing but its first coverage period.

        PRD: "A `STANDARD` renewal is always available while the window and grace conditions hold."

        Design: Corner/validations/renewal_window_opens_inclusively_and_the_grace_period_closes_the_door
        """
        facility = X.create_registered_facility(
            api, facility_name="Bramble Compounding", owner_operator_name="Bramble Co",
            state_or_province="IN",
        )

        X.set_clock(api, DAY_AFTER_GRACE_ENDS)
        validate_error(_file_renewal(api, facility["id"]), E.ERR_GRACE_PERIOD_EXPIRED)

        rows, meta = validate_paginated(
            api.list_registration_periods(
                facility["id"], make_facility_registrant_headers(facility["id"])
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["sequence_index"] == 1
        assert X.read_facility(api, facility["id"])["registration_cycle_count"] == 1


NEW_OWNER = "Brightline Beauty Holdings"


class TestAnAcceptedOwnershipChangeBarsTheAbbreviatedPath:
    """A sibling entity's acceptance destroys eligibility inside an open window."""

    def _establishment_under_new_ownership(self, api):
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        )
        registrant = make_facility_registrant_headers(facility["id"])
        filing = get_success_data(
            api.file_ownership_change(
                facility["id"],
                F.ownership_change_payload(
                    facility["version"], new_owner_operator_name=NEW_OWNER
                ),
                registrant,
            )
        )
        get_success_data(
            api.decide_ownership_change(
                filing["id"], F.ownership_decision_payload("ACCEPT"), REVIEWER_HEADERS
            )
        )
        return facility, filing

    def test_a_fresh_establishment_starts_on_the_abbreviated_path(self, api):
        """Eligibility is the default, which is what makes its later loss attributable to the
        ownership change alone.

        PRD: "A newly created establishment begins with `registration_status` at `DRAFT`, `compliance_posture` at `OPEN`, `serious_event_points` at 0.00, `registration_cycle_count` at 0, `abbreviated_renewal_eligible` true, `listed_product_count` and `open_serious_event_count` at 0, and `facility_fei`, `gmp_readiness_score`, `last_inspection_outcome`, `current_period_start`, `current_period_end`, `renewal_window_open_date` and `grace_end_date` all null."

        Design: Corner/validations/abbreviated_renewal_is_barred_after_an_accepted_ownership_change
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        )
        assert facility["abbreviated_renewal_eligible"] is True

    def test_the_abbreviated_kind_is_refused_while_the_window_stands_open(self, api):
        """The window is open and the establishment is properly registered, so the only thing
        left to object to is the eligibility flag the ownership change cleared.

        PRD: "A change of ownership mid-period is therefore enough to force the establishment down the `STANDARD` path for the remainder of that period, and so is any posture escalation, since a `RESTRICTED` or `FROZEN` establishment is never abbreviated-eligible."

        Design: Corner/validations/abbreviated_renewal_is_barred_after_an_accepted_ownership_change
        """
        facility, _filing = self._establishment_under_new_ownership(api)

        X.set_clock(api, THE_DAY_THE_WINDOW_OPENS)
        validate_error(
            _file_renewal(api, facility["id"], K.RENEWAL_KIND_ABBREVIATED),
            E.ERR_ABBREVIATED_RENEWAL_NOT_ELIGIBLE,
        )

        after = X.read_facility(api, facility["id"])
        assert after["owner_operator_name"] == NEW_OWNER
        assert after["abbreviated_renewal_eligible"] is False

    def test_the_standard_kind_succeeds_at_the_very_same_instant(self, api):
        """The window was never the problem: the ordinary kind mints the successor period at
        the same logical instant the abbreviated kind was refused.

        PRD: "The successor's `period_start` is always the predecessor's `period_end` plus one day — the cadence is gap-free and never drifts, even when the filing itself arrives late — and its `period_end`, `renewal_window_open_date` and `grace_end_date` follow the same two-year derivation described above."

        Design: Corner/validations/abbreviated_renewal_is_barred_after_an_accepted_ownership_change
        """
        facility, _filing = self._establishment_under_new_ownership(api)
        X.set_clock(api, THE_DAY_THE_WINDOW_OPENS)
        validate_error(
            _file_renewal(api, facility["id"], K.RENEWAL_KIND_ABBREVIATED),
            E.ERR_ABBREVIATED_RENEWAL_NOT_ELIGIBLE,
        )

        successor = get_success_data(_file_renewal(api, facility["id"]))

        assert successor["period_start"] == SUCCESSOR_PERIOD_START
        assert successor["period_end"] == SUCCESSOR_PERIOD_END
        assert successor["period_kind"] == K.PERIOD_KIND_RENEWAL

        rows, meta = validate_paginated(
            api.list_registration_periods(
                facility["id"], make_facility_registrant_headers(facility["id"])
            )
        )
        assert meta["total_count"] == 2
        assert [row["sequence_index"] for row in rows] == [1, 2]


RECEIPT_INSTANT = "2026-08-05T08:00:00Z"
ONE_MILLISECOND_LATER = "2026-08-05T08:00:00.001Z"


class TestAnEventMayArriveNowButNeverLater:
    """The comparison against the logical clock is strictly greater-than."""

    def test_an_event_received_at_the_current_instant_is_recorded(self, api):
        """Receipt exactly at the logical clock is inside the allowed range, because nobody can
        have received a report from the future but they certainly can from the present.

        PRD: "One business condition applies: `received_at` must not be after the logical clock, since nobody can have received a report from the future; a later instant is refused with `ERR_RECEIVED_AT_IN_FUTURE` (HTTP 422)."

        Design: Corner/validations/adverse_event_received_at_may_equal_now_but_never_exceed_it
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={"facility_name": "Aster Labs Newark",
                                "owner_operator_name": "Aster Holdings LLC"},
            listing_overrides={"product_name": "Aster Blush Powder"},
        )
        X.set_clock(api, RECEIPT_INSTANT)

        event = X.record_retained_event(
            api, bundle["listing_id"], bundle["agent"], RECEIPT_INSTANT,
            event_description="Transient stinging reported by telephone", outcome_code="NONE",
        )

        assert event["received_at"] == RECEIPT_INSTANT
        assert event["report_status"] == K.EVENT_STATUS_RETAINED

    def test_one_millisecond_into_the_future_is_refused_and_stores_nothing(self, api):
        """A single millisecond past the clock is already the future, and the refusal leaves
        the product's intake register holding only the legitimate row.

        PRD: "Adverse-event recording is deliberately the least gated operation in the system."

        Design: Corner/validations/adverse_event_received_at_may_equal_now_but_never_exceed_it
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={"facility_name": "Aster Labs Newark",
                                "owner_operator_name": "Aster Holdings LLC"},
            listing_overrides={"product_name": "Aster Blush Powder"},
        )
        X.set_clock(api, RECEIPT_INSTANT)
        X.record_retained_event(
            api, bundle["listing_id"], bundle["agent"], RECEIPT_INSTANT,
            event_description="Transient stinging reported by telephone", outcome_code="NONE",
        )

        validate_error(
            api.record_adverse_event(
                bundle["listing_id"],
                F.adverse_event_payload(ONE_MILLISECOND_LATER, K.SERIOUSNESS_NON_SERIOUS),
                bundle["agent"],
            ),
            E.ERR_RECEIVED_AT_IN_FUTURE,
        )

        rows, meta = validate_paginated(
            api.list_adverse_events(bundle["listing_id"], bundle["agent"])
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert X.read_facility(api, bundle["facility_id"])["open_serious_event_count"] == 0


class TestTheInspectionWindowMustSitInsideCoverage:
    """A faultless window is still refused on a purely relational ground."""

    def test_a_window_that_pokes_past_the_period_end_is_refused(self, api):
        """The window overlaps nothing, is correctly ordered and is the right length, yet it
        starts one day after coverage ends.

        PRD: "Third the window must lie **entirely inside** the establishment's current coverage period: since `window_end` is exclusive, the last on-site day is the day before it, and that day must fall on or before `current_period_end`, while `window_start` must fall on or after `current_period_start`."

        Design: Corner/validations/inspection_window_must_sit_inside_the_current_registration_period
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        )
        assert facility["current_period_end"] == K.CANONICAL_PERIOD_END

        validate_error(
            api.schedule_inspection(
                facility["id"],
                F.inspection_payload("2028-08-01", "2028-08-05", K.INSPECTION_TYPE_GMP_ROUTINE),
                REVIEWER_HEADERS,
            ),
            E.ERR_INSPECTION_OUTSIDE_REGISTRATION_PERIOD,
        )

        after = X.read_facility(api, facility["id"])
        assert after["gmp_readiness_score"] is None
        assert after["last_inspection_outcome"] is None

    def test_the_same_shape_of_window_inside_the_period_is_booked(self, api):
        """Moved inside coverage the identical four-day booking is accepted, and the agency's
        calendar then holds exactly that one engagement.

        PRD: "A window that pokes past the period end is refused with `ERR_INSPECTION_OUTSIDE_REGISTRATION_PERIOD` (HTTP 422); the agency does not book on-site days it has no current registration to inspect against."

        Design: Corner/validations/inspection_window_must_sit_inside_the_current_registration_period
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        )
        validate_error(
            api.schedule_inspection(
                facility["id"],
                F.inspection_payload("2028-08-01", "2028-08-05", K.INSPECTION_TYPE_GMP_ROUTINE),
                REVIEWER_HEADERS,
            ),
            E.ERR_INSPECTION_OUTSIDE_REGISTRATION_PERIOD,
        )

        booked = X.schedule_inspection(
            api, facility["id"], "2026-09-01", "2026-09-05", K.INSPECTION_TYPE_GMP_ROUTINE
        )
        assert booked["status"] == K.INSPECTION_STATUS_SCHEDULED

        rows, meta = validate_paginated(api.list_inspections(facility["id"], REVIEWER_HEADERS))
        assert meta["total_count"] == 1
        assert len(rows) == 1


class TestListingsRequireAnAdmissiblyRegisteredEstablishment:
    """The gate reads the parent's registration status, not the identifier's existence."""

    def test_a_draft_establishment_cannot_acquire_a_listing(self, api):
        """The establishment identifier resolves perfectly well; what is missing is the
        approval, so the answer is the registration objection and not a not-found.

        PRD: "The governing establishment must have `registration_status` `REGISTERED` or `RENEWAL_DUE`; a `DRAFT`, `PENDING_REVIEW`, `REJECTED` or `LAPSED` establishment cannot acquire new listings, and the attempt is rejected with `ERR_FACILITY_NOT_REGISTERED` (HTTP 409)."

        Design: Corner/validations/listing_create_against_an_unapproved_facility_is_rejected
        """
        facility = X.create_draft_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        )
        person = X.create_responsible_person(api, legal_name="Aster Brands Inc")
        agent = make_responsible_person_agent_headers(person["id"])

        assert facility["registration_status"] == K.REGISTRATION_STATUS_DRAFT
        validate_error(
            api.create_listing(
                F.listing_payload(facility["id"], person["id"]), agent
            ),
            E.ERR_FACILITY_NOT_REGISTERED,
        )

    def test_a_file_merely_awaiting_review_is_equally_insufficient(self, api):
        """Submitting the registration is not the same as holding one, and the identical payload
        is accepted the moment the approval lands.

        PRD: "A freshly created listing answers 201 and begins with `listing_status` `DRAFT`, `safety_status` `UNSUBSTANTIATED`, `listing_number` and `suspension_reason` both null, `allergen_disclosure_complete` true, `undisclosed_allergen_count` 0, `distributed_units_total` 0, `open_recall_count` 0, `open_serious_event_count` 0, `marketable` false and `version` 1."
        PRD: "`active_designation_count` in turn counts the listings designated to that party whose `listing_status` is `SUBMITTED` or `LISTED` — no other listing state occupies a designation slot."

        Design: Corner/validations/listing_create_against_an_unapproved_facility_is_rejected
        """
        facility = X.create_pending_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        )
        person = X.create_responsible_person(api, legal_name="Aster Brands Inc")
        agent = make_responsible_person_agent_headers(person["id"])
        payload = F.listing_payload(facility["id"], person["id"])

        assert facility["registration_status"] == K.REGISTRATION_STATUS_PENDING_REVIEW
        validate_error(
            api.create_listing(payload, agent), E.ERR_FACILITY_NOT_REGISTERED
        )

        get_success_data(
            api.decide_registration(
                facility["id"], F.registration_decision_payload("APPROVE"), REVIEWER_HEADERS
            )
        )
        accepted = get_success_data(api.create_listing(payload, agent))

        assert accepted["listing_status"] == K.LISTING_STATUS_DRAFT
        assert accepted["version"] == 1
        assert X.read_responsible_person(api, person["id"])["active_designation_count"] == 0


class TestSubmissionDemandsAnAdequateDossier:
    """No dossier and a deficient dossier fail the very same gate."""

    def test_a_product_with_no_dossier_at_all_cannot_be_submitted(self, api):
        """The safety dimension starts unsubstantiated and that is a hard precondition, so the
        first submission attempt never reaches any later gate.

        PRD: "Only then do the four safety gates run, in this fixed order: the listing's `safety_status` must be `SUBSTANTIATED`, failing which the submission is refused with `ERR_SUBSTANTIATION_NOT_ADEQUATE` (HTTP 422); `allergen_disclosure_complete` must be true, failing which it is refused with `ERR_ALLERGEN_DISCLOSURE_INCOMPLETE` (HTTP 422); the professional-use labelling condition must hold, failing which it is refused with `ERR_PROFESSIONAL_USE_LABEL_REQUIRED` (HTTP 422); and the label-contact condition must hold, failing which it is refused with `ERR_LABEL_CONTACT_REQUIRED` (HTTP 422)."

        Design: Corner/validations/listing_submit_without_an_adequate_dossier_is_rejected
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={"facility_name": "Aster Labs Newark",
                                "owner_operator_name": "Aster Holdings LLC"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
        )

        assert bundle["listing"]["safety_status"] == K.SAFETY_STATUS_UNSUBSTANTIATED
        validate_error(
            api.submit_listing(bundle["listing_id"], bundle["agent"]),
            E.ERR_SUBSTANTIATION_NOT_ADEQUATE,
        )

    def test_a_deficient_dossier_is_no_better_than_none(self, api):
        """A trade-press summary attested by an unqualified assessor is worth 1.50, far under the
        pass mark, and the resulting deficiency leaves the submission gate exactly as shut.

        PRD: "Each evidence class carries a weight — 40 for `CLINICAL_SAFETY_STUDY`, 25 for `IN_VITRO_TOXICOLOGY`, 20 for `READ_ACROSS_ANALOG`, 10 for `HISTORICAL_USE_DOSSIER` and 5 for `LITERATURE_REVIEW` — and each credential carries a factor: 1.0 for both `BOARD_CERTIFIED_TOXICOLOGIST` and `ERT`, 0.6 for `QUALIFIED_SAFETY_ASSESSOR` and 0.3 for `OTHER`."

        Design: Corner/validations/listing_submit_without_an_adequate_dossier_is_rejected
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={"facility_name": "Aster Labs Newark",
                                "owner_operator_name": "Aster Holdings LLC"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
        )

        decided = X.dossier_at_decision(
            api, bundle["listing_id"], bundle["agent"],
            items=[(K.EVIDENCE_LITERATURE, K.CREDENTIAL_OTHER)],
            review_mode=K.REVIEW_MODE_FULL,
        )
        A.assert_two_decimal_value(decided["adequacy_score"], 1.50, "adequacy_score")
        assert decided["status"] == K.SUBSTANTIATION_STATUS_DEFICIENT

        validate_error(
            api.submit_listing(bundle["listing_id"], bundle["agent"]),
            E.ERR_SUBSTANTIATION_NOT_ADEQUATE,
        )

    def test_a_failed_submission_is_not_a_partial_transition(self, api):
        """The product stays in draft and the establishment counts no listed product, so
        nothing of the transition survived the refusal.

        PRD: "It is admissible from exactly two origins, `DRAFT` and `RETURNED`, and the two edges `DRAFT → SUBMITTED` and `RETURNED → SUBMITTED` share identical conditions and identical effects — the second is simply the resubmission that closes the submit-and-return cycle."

        Design: Corner/validations/listing_submit_without_an_adequate_dossier_is_rejected
        """
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={"facility_name": "Aster Labs Newark",
                                "owner_operator_name": "Aster Holdings LLC"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A"},
        )
        X.dossier_at_decision(
            api, bundle["listing_id"], bundle["agent"],
            items=[(K.EVIDENCE_LITERATURE, K.CREDENTIAL_OTHER)],
            review_mode=K.REVIEW_MODE_FULL,
        )
        validate_error(
            api.submit_listing(bundle["listing_id"], bundle["agent"]),
            E.ERR_SUBSTANTIATION_NOT_ADEQUATE,
        )

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["listing_status"] == K.LISTING_STATUS_DRAFT
        assert listing["safety_status"] == K.SAFETY_STATUS_SUBSTANTIATION_FAILED
        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 0


class TestTheCompleteLadderSatisfiesEveryGateAtOnce:
    """The positive counterpart to the whole submit stack, in one pass."""

    def _a_faultlessly_prepared_product(self, api):
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={"facility_name": "Aster Labs Newark",
                                "owner_operator_name": "Aster Holdings LLC"},
            person_overrides={"legal_name": "Aster Brands Inc"},
            listing_overrides={
                "product_name": "Aster Blush Powder", "category_code": "07A",
                "label_contact_type": K.LABEL_CONTACT_ELECTRONIC_CONTACT,
                "label_contact_value": "safety@aster.example",
            },
        )
        bundle["decided"] = X.dossier_at_decision(
            api, bundle["listing_id"], bundle["agent"], review_mode=K.REVIEW_MODE_FULL
        )
        return bundle

    def test_every_gate_holds_together_and_the_submission_passes(self, api):
        """An approved establishment at open posture, an adequate dossier, complete allergen
        disclosure and a legal consumer channel all hold at once, so the submission clears the
        whole stack in one call.

        PRD: "In either mode a score of **60.00 or more** rules the dossier `ADEQUATE` and anything below 60.00 rules it `DEFICIENT`; the pass mark is inclusive at the boundary."
        PRD: "A dossier holding a `CLINICAL_SAFETY_STUDY` item attested by a `BOARD_CERTIFIED_TOXICOLOGIST` (40.00) plus an `IN_VITRO_TOXICOLOGY` item attested by an `ERT` (25.00), with no data gap, scores 65.00 under both modes and passes under both."

        Design: Corner/validations/complete_ladder_satisfies_every_listing_submit_gate_at_once
        """
        bundle = self._a_faultlessly_prepared_product(api)

        A.assert_two_decimal_value(bundle["decided"]["adequacy_score"], 65.00, "adequacy_score")
        assert bundle["decided"]["status"] == K.SUBSTANTIATION_STATUS_ADEQUATE

        submitted = get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))
        assert submitted["listing_status"] == K.LISTING_STATUS_SUBMITTED
        assert submitted["allergen_disclosure_complete"] is True
        assert submitted["undisclosed_allergen_count"] == 0

    def test_the_register_number_is_minted_and_the_product_becomes_sellable(self, api):
        """The agency's decision mints the first register number and the product satisfies all
        four marketability inputs together.

        PRD: "`SUBMITTED → LISTED` mints the register number into `listing_number`, formatted as the literal prefix `CPL-` followed by a six-digit zero-padded ordinal that is the listing's position among all listed listings ordered by ascending `created_at`; the number is minted only on the **first** listing decision, so a product that is later suspended and restored, or delisted and re-registered, keeps the number it was first given."
        PRD: "The `marketable` flag is the single boolean a client can read to answer "may this product be sold?", and it is true only when four conditions hold together: `listing_status` is `LISTED`, `safety_status` is `SUBSTANTIATED`, `allergen_disclosure_complete` is true, and the governing establishment's `compliance_posture` is anything other than `FROZEN`."

        Design: Corner/validations/complete_ladder_satisfies_every_listing_submit_gate_at_once
        """
        bundle = self._a_faultlessly_prepared_product(api)
        get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))

        listed = get_success_data(
            api.decide_listing(
                bundle["listing_id"], F.listing_decision_payload("LIST"), REVIEWER_HEADERS
            )
        )

        assert listed["listing_status"] == K.LISTING_STATUS_LISTED
        assert listed["listing_number"] == "CPL-000001"
        assert listed["marketable"] is True
        assert X.read_facility(api, bundle["facility_id"])["listed_product_count"] == 1

    def test_the_listing_decision_is_recorded_against_the_product(self, api):
        """The decision leaves a transition entry in the establishment's ledger pointing at the
        product itself, which is where a reconciliation would look for it.

        PRD: "The compliance ledger of an establishment reads back in ascending `sequence_no` order and accepts an `entry_type` filter and a `subject_entity` filter for reconciliation work."
        PRD: "Listing also increments the establishment's `listed_product_count` by 1, recomputes `marketable`, appends a `STATE_TRANSITION` ledger entry and increments the listing's `version` by 1."

        Design: Corner/validations/complete_ladder_satisfies_every_listing_submit_gate_at_once
        """
        bundle = self._a_faultlessly_prepared_product(api)
        get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))
        get_success_data(
            api.decide_listing(
                bundle["listing_id"], F.listing_decision_payload("LIST"), REVIEWER_HEADERS
            )
        )

        rows, _meta = X.read_ledger(
            api, bundle["facility_id"],
            {"entry_type": K.ENTRY_TYPE_STATE_TRANSITION, "subject_entity": "ProductListing"},
        )
        assert [row["subject_id"] for row in rows] == [bundle["listing_id"]] * 3
        assert [row["sequence_no"] for row in rows] == sorted(
            row["sequence_no"] for row in rows
        )


REC_A1_UNITS = 400
REC_A2_UNITS = 250
REC_B1_UNITS = 100


class TestTwoRelationalGatesOverOneWithdrawalRound:
    """A foreign record cannot be produced, and a sibling record cannot be recovered."""

    def _round_over_the_first_product(self, api):
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={"facility_name": "Aster Labs Newark",
                                "owner_operator_name": "Aster Holdings LLC"},
            person_overrides={"legal_name": "Aster Brands Inc"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A",
                               "lot_authorized_units": 5000},
        )
        sibling = X.create_draft_listing(
            api, bundle["facility_id"], bundle["person_id"],
            product_name="Aster Cleansing Gel", category_code="07A",
            product_form=K.PRODUCT_FORM_RINSE_OFF, lot_authorized_units=5000,
        )
        rec_a1, rec_a2 = X.create_distribution_records(
            api, bundle["listing_id"], bundle["agent"],
            [{"lot_code": "LOT-A1", "ship_date": "2026-08-05", "delivery_date": "2026-08-08",
              "units_shipped": REC_A1_UNITS, "consignee_name": "Gulf Coast Retail Group",
              "consignee_class": "RETAIL"},
             {"lot_code": "LOT-A2", "ship_date": "2026-08-06", "delivery_date": "2026-08-09",
              "units_shipped": REC_A2_UNITS, "consignee_name": "Northway Wholesale",
              "consignee_class": "WHOLESALE"}],
        )
        rec_b1 = X.create_distribution_records(
            api, sibling["id"], bundle["agent"],
            [{"lot_code": "LOT-B1", "ship_date": "2026-08-05", "delivery_date": "2026-08-07",
              "units_shipped": REC_B1_UNITS, "consignee_name": "Harbor Drug Mart",
              "consignee_class": "RETAIL"}],
        )[0]
        recall = X.recall_with_accepted_plan(
            api, bundle["listing_id"], bundle["agent"], officer=OFFICER_HEADERS
        )
        withdrawal = X.open_withdrawal(api, recall, OFFICER_HEADERS)
        bundle.update({
            "sibling_id": sibling["id"], "rec_a1": rec_a1, "rec_a2": rec_a2,
            "rec_b1": rec_b1, "withdrawal_id": withdrawal["id"],
        })
        return bundle

    def test_a_record_belonging_to_a_sibling_product_cannot_be_produced(self, api):
        """The recall was opened against the first product, so a shipment of the second one has
        no business in this round however well its identifier resolves.

        PRD: "Every identifier in the list must resolve to a record — validated in payload order, so the first unresolvable identifier is the one reported as `ERR_DISTRIBUTION_RECORD_NOT_FOUND` (HTTP 404) — the list must name at least one record, or it is refused with `ERR_NO_DISTRIBUTION_RECORDS` (HTTP 422), and every named record must belong to the listing the recall was opened against, or it is refused with `ERR_DISTRIBUTION_RECORD_LISTING_MISMATCH` (HTTP 422)."

        Design: Corner/validations/record_production_rejects_a_foreign_listing_then_recovery_rejects_an_unlinked_record
        """
        bundle = self._round_over_the_first_product(api)

        validate_error(
            api.produce_records(
                bundle["withdrawal_id"],
                F.records_production_payload(
                    [bundle["rec_a1"]["id"], bundle["rec_b1"]["id"]]
                ),
                bundle["agent"],
            ),
            E.ERR_DISTRIBUTION_RECORD_LISTING_MISMATCH,
        )

        assert X.read_record(api, bundle["rec_a1"]["id"])["withdrawal_id"] is None
        rows, meta = validate_paginated(
            api.list_distribution_records(
                bundle["agent"], {"withdrawal_id": bundle["withdrawal_id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_sibling_record_of_the_right_product_is_still_not_in_the_round(self, api):
        """Belonging to the recalled product is not enough: the shipment must have been produced
        into this round before any movement may be posted against it.

        PRD: "The named record must currently be linked to the withdrawal in question, or the entry is refused with `ERR_RECORD_NOT_IN_WITHDRAWAL` (HTTP 422); that rule strictly outranks the outstanding-units guard below, so an unlinked record carrying an absurdly large unit count reports the linkage error rather than the quantity error."

        Design: Corner/validations/record_production_rejects_a_foreign_listing_then_recovery_rejects_an_unlinked_record
        """
        bundle = self._round_over_the_first_product(api)

        produced = X.produce_records(
            api, bundle["withdrawal_id"], [bundle["rec_a1"]["id"]], bundle["agent"]
        )
        assert produced["status"] == K.WITHDRAWAL_STATUS_RECORDS_PRODUCED
        assert produced["shipped_units_total"] == REC_A1_UNITS

        validate_error(
            api.post_recovery_entry(
                bundle["withdrawal_id"],
                F.recovery_entry_payload(bundle["rec_a2"]["id"], 10),
                bundle["agent"],
            ),
            E.ERR_RECORD_NOT_IN_WITHDRAWAL,
        )

        withdrawal = X.read_withdrawal(api, bundle["withdrawal_id"])
        assert withdrawal["reported_recovered_units"] == 0
        assert withdrawal["outstanding_units_total"] == REC_A1_UNITS

        untouched = X.read_record(api, bundle["rec_a2"]["id"])
        assert untouched["units_outstanding"] == REC_A2_UNITS
        assert untouched["withdrawal_id"] is None


class TestProductionRefusesAnEmptyRecordSet:
    """An empty list is a domain violation, and it leaves the round usable."""

    def _round_awaiting_its_records(self, api):
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={"facility_name": "Aster Labs Newark",
                                "owner_operator_name": "Aster Holdings LLC"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A",
                               "lot_authorized_units": 5000},
        )
        record = X.create_distribution_records(
            api, bundle["listing_id"], bundle["agent"],
            [{"lot_code": "LOT-A1", "ship_date": "2026-08-05", "delivery_date": "2026-08-08",
              "units_shipped": REC_A1_UNITS, "consignee_name": "Gulf Coast Retail Group",
              "consignee_class": "RETAIL"}],
        )[0]
        recall = X.recall_with_accepted_plan(
            api, bundle["listing_id"], bundle["agent"], officer=OFFICER_HEADERS
        )
        withdrawal = X.open_withdrawal(api, recall, OFFICER_HEADERS)
        bundle.update({"record": record, "withdrawal_id": withdrawal["id"]})
        return bundle

    def test_naming_no_records_at_all_is_a_domain_refusal(self, api):
        """The request is perfectly well formed; it simply asserts that the sponsor produced
        nothing, which the rule names in its own right.

        PRD: "the list must name at least one record, or it is refused with `ERR_NO_DISTRIBUTION_RECORDS` (HTTP 422)"

        Design: Corner/validations/records_production_refuses_an_empty_record_set
        """
        bundle = self._round_awaiting_its_records(api)

        validate_error(
            api.produce_records(
                bundle["withdrawal_id"], F.records_production_payload([]), bundle["agent"]
            ),
            E.ERR_NO_DISTRIBUTION_RECORDS,
        )

        withdrawal = X.read_withdrawal(api, bundle["withdrawal_id"])
        assert withdrawal["status"] == K.WITHDRAWAL_STATUS_OPEN
        assert withdrawal["shipped_units_total"] == 0
        assert withdrawal["records_produced_count"] == 0

    def test_the_round_remains_usable_for_a_real_production_call(self, api):
        """Because the refusal advanced nothing, the genuine production call that follows is
        still admissible and fixes the denominator the whole recall rests on.

        PRD: "Production sets each named record's `withdrawal_id` to this withdrawal, sets `records_produced_count` to the number of linked records and `shipped_units_total` to the sum of their `units_shipped`, sets `outstanding_units_total` equal to `shipped_units_total` because nothing has been verified yet, leaves both recovery rates at 0.00, and takes `OPEN → RECORDS_PRODUCED`."

        Design: Corner/validations/records_production_refuses_an_empty_record_set
        """
        bundle = self._round_awaiting_its_records(api)
        validate_error(
            api.produce_records(
                bundle["withdrawal_id"], F.records_production_payload([]), bundle["agent"]
            ),
            E.ERR_NO_DISTRIBUTION_RECORDS,
        )

        produced = X.produce_records(
            api, bundle["withdrawal_id"], [bundle["record"]["id"]], bundle["agent"]
        )
        assert produced["status"] == K.WITHDRAWAL_STATUS_RECORDS_PRODUCED
        assert produced["shipped_units_total"] == REC_A1_UNITS
        assert produced["outstanding_units_total"] == REC_A1_UNITS

        rows, meta = validate_paginated(
            api.list_distribution_records(
                bundle["agent"], {"withdrawal_id": bundle["withdrawal_id"]}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1


LOT_D_UNITS = 1000
FIRST_VERIFIED_RETURN = 600
OVERSIZED_SECOND_RETURN = 500
EXACT_REMAINDER = 400


class TestRecoveryIsBoundedByTheRunningOutstandingTotal:
    """The ceiling is what is left, not what was shipped."""

    def _round_with_six_hundred_units_already_verified(self, api):
        bundle = X.registered_facility_with_listing(
            api,
            facility_overrides={"facility_name": "Aster Labs Newark",
                                "owner_operator_name": "Aster Holdings LLC"},
            listing_overrides={"product_name": "Aster Blush Powder", "category_code": "07A",
                               "lot_authorized_units": 5000},
        )
        bundle = X.withdrawal_with_produced_records(
            api, bundle,
            specs=[{"lot_code": "LOT-D", "ship_date": "2026-08-05",
                    "delivery_date": "2026-08-08", "units_shipped": LOT_D_UNITS,
                    "consignee_name": "Gulf Coast Retail Group", "consignee_class": "RETAIL"}],
            officer=OFFICER_HEADERS,
        )
        bundle["after_first"] = X.post_recovery(
            api, bundle["withdrawal_id"], bundle["records"][0]["id"], FIRST_VERIFIED_RETURN,
            bundle["agent"],
        )
        return bundle

    def test_the_first_verified_return_moves_the_bound_down(self, api):
        """Six hundred of the thousand units are accounted for, so four hundred is what the
        record still owes and therefore what the guard now measures against.

        PRD: "Only the two verified buckets reduce `units_outstanding`, which is at all times `units_shipped` minus the sum of `units_verified_returned` and `units_verified_destroyed`: consignee assertions and in-transit claims are recorded but do not discharge the obligation, because units are only accounted for once someone has actually seen them come back or be destroyed."

        Design: Corner/validations/recovery_entries_are_bounded_by_the_records_outstanding_units
        """
        bundle = self._round_with_six_hundred_units_already_verified(api)

        record = X.read_record(api, bundle["records"][0]["id"])
        assert record["units_verified_returned"] == FIRST_VERIFIED_RETURN
        assert record["units_outstanding"] == LOT_D_UNITS - FIRST_VERIFIED_RETURN

    def test_a_five_hundred_unit_return_is_refused_though_the_shipment_held_a_thousand(self, api):
        """Five hundred is comfortably under the thousand that shipped and still too many,
        because the guard reads the balance before the entry rather than the original shipment.

        PRD: "A verified movement is therefore guarded: the `units` of a `VERIFIED_RETURN` or `VERIFIED_DESTRUCTION` entry must not exceed the record's `units_outstanding` **before** the entry, or it is refused with `ERR_RECOVERY_EXCEEDS_OUTSTANDING` (HTTP 422)."

        Design: Corner/validations/recovery_entries_are_bounded_by_the_records_outstanding_units
        """
        bundle = self._round_with_six_hundred_units_already_verified(api)

        validate_error(
            api.post_recovery_entry(
                bundle["withdrawal_id"],
                F.recovery_entry_payload(
                    bundle["records"][0]["id"], OVERSIZED_SECOND_RETURN,
                    K.ENTRY_KIND_VERIFIED_RETURN,
                ),
                bundle["agent"],
            ),
            E.ERR_RECOVERY_EXCEEDS_OUTSTANDING,
        )

        assert X.read_record(api, bundle["records"][0]["id"])["units_outstanding"] == (
            LOT_D_UNITS - FIRST_VERIFIED_RETURN
        )

    def test_exactly_the_remaining_balance_is_admitted_and_clears_the_record(self, api):
        """The bound is inclusive, so the four hundred units still owed may all come back at
        once, and the round's conservation identity closes at zero outstanding.

        PRD: "Per withdrawal, the sum over its linked records of verified-plus-outstanding units always equals `shipped_units_total`, and `outstanding_units_total` always equals the sum of the records' `units_outstanding`."

        Design: Corner/validations/recovery_entries_are_bounded_by_the_records_outstanding_units
        """
        bundle = self._round_with_six_hundred_units_already_verified(api)

        cleared = X.post_recovery(
            api, bundle["withdrawal_id"], bundle["records"][0]["id"], EXACT_REMAINDER,
            bundle["agent"],
        )
        assert cleared["units_outstanding"] == 0

        withdrawal = X.read_withdrawal(api, bundle["withdrawal_id"])
        assert withdrawal["verified_recovered_units"] == LOT_D_UNITS
        assert withdrawal["outstanding_units_total"] == 0


class TestTheDesignationCapIsPerPersonAggregateState:
    """A person at their ceiling blocks the submission; their neighbour does not."""

    def _two_designees_one_of_them_capped_at_one(self, api):
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC",
        )
        capped = X.create_responsible_person(
            api, legal_name="Aster Brands Inc", designation_cap=1
        )
        spare = X.create_responsible_person(api, legal_name="Aster Reserve Labels LLC")
        return facility, capped, spare

    def _submitted_listing_for(self, api, facility, person, **overrides):
        agent = make_responsible_person_agent_headers(person["id"])
        listing = X.create_draft_listing(api, facility["id"], person["id"], **overrides)
        X.dossier_at_decision(api, listing["id"], agent)
        return listing, agent

    def test_the_supplied_ceiling_overrides_the_declared_default(self, api):
        """The designee is created at a ceiling of one rather than the default, and holds no
        slot until a product of theirs is actually submitted.

        PRD: "When `designation_cap` is omitted it defaults to 25, and it may be set anywhere from 1 to 500."
        PRD: "A new responsible person starts with `active_designation_count` at 0 and `status` `DORMANT`."

        Design: Corner/validations/designation_cap_of_one_blocks_the_second_listing_for_that_person
        """
        _facility, capped, _spare = self._two_designees_one_of_them_capped_at_one(api)

        assert capped["designation_cap"] == 1
        assert capped["active_designation_count"] == 0
        assert capped["status"] == K.RP_STATUS_DORMANT

    def test_a_designee_sitting_at_its_cap_blocks_the_second_submission(self, api):
        """The first product occupies the only slot the designee has, so the second faultlessly
        prepared product cannot be submitted at all.

        PRD: "The **designation-slot capacity** check compares the designee that will hold the slot against its own ceiling: the current designee's `active_designation_count` must be strictly less than its `designation_cap`. A designee sitting at exactly its cap blocks the submission."

        Design: Corner/validations/designation_cap_of_one_blocks_the_second_listing_for_that_person
        """
        facility, capped, _spare = self._two_designees_one_of_them_capped_at_one(api)
        first, agent = self._submitted_listing_for(
            api, facility, capped, product_name="Aster Blush Powder",
        )
        get_success_data(api.submit_listing(first["id"], agent))

        second, _agent = self._submitted_listing_for(
            api, facility, capped, product_name="Aster Cleansing Gel",
            product_form=K.PRODUCT_FORM_RINSE_OFF,
        )
        validate_error(
            api.submit_listing(second["id"], agent), E.ERR_DESIGNATION_CAP_EXCEEDED
        )

        holder = X.read_responsible_person(api, capped["id"])
        assert holder["active_designation_count"] == 1
        assert holder["status"] == K.RP_STATUS_ACTIVE
        assert X.read_listing(api, second["id"])["listing_status"] == K.LISTING_STATUS_DRAFT

    def test_a_differently_capped_neighbour_takes_the_same_product_immediately(self, api):
        """The ceiling is the designee's own aggregate state, so a second party with room to
        spare submits the very product the capped one could not.

        PRD: "That `status` is never set directly. It is derived: a responsible person is `ACTIVE` whenever `active_designation_count` is 1 or more, and `DORMANT` when it is exactly 0."

        Design: Corner/validations/designation_cap_of_one_blocks_the_second_listing_for_that_person
        """
        facility, capped, spare = self._two_designees_one_of_them_capped_at_one(api)
        first, capped_agent = self._submitted_listing_for(
            api, facility, capped, product_name="Aster Blush Powder",
        )
        get_success_data(api.submit_listing(first["id"], capped_agent))

        third, spare_agent = self._submitted_listing_for(
            api, facility, spare, product_name="Aster Cleansing Gel",
            product_form=K.PRODUCT_FORM_RINSE_OFF,
        )
        submitted = get_success_data(api.submit_listing(third["id"], spare_agent))

        assert submitted["listing_status"] == K.LISTING_STATUS_SUBMITTED
        neighbour = X.read_responsible_person(api, spare["id"])
        assert neighbour["active_designation_count"] == 1
        assert neighbour["status"] == K.RP_STATUS_ACTIVE
