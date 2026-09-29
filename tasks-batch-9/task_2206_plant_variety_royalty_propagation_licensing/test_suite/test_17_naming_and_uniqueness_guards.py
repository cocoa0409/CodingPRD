"""Names, marks and live filing triples: what may not collide, and what may reuse.
"""

from test_helpers import (
    BREEDER,
    ApiErrorId,
    brand_register_payload,
    create_filing,
    create_protection_filing_payload,
    create_variety,
    create_variety_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheDenominationIsUniqueCaseInsensitively:
    """One registered variety of record, and the names that may follow it."""

    def _registered_variety(self, api):
        return create_variety(
            api, denomination="Aurora Bramble", species="Rubus idaeus",
            breeder_code="AB", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )

    def test_a_different_case_and_padded_name_is_the_same_name(self, api):
        """The comparison trims and folds case, so a lower-case padded restatement
        of an existing denomination collides even though the bytes differ.

        PRD 3.1: "The denomination is unique across every variety in the system, compared case-insensitively after trimming surrounding whitespace."

        Design: Corner/validations/duplicate_denomination_compared_case_insensitively_rejected
        """
        self._registered_variety(api)

        validate_error(
            api.create_variety(
                create_variety_payload(
                    denomination="  aurora bramble ", species="Vitis vinifera",
                    breeder_code="XX", base_royalty_cents_per_plant=50,
                    base_royalty_cents_per_acre=1500,
                ),
                BREEDER,
            ),
            ApiErrorId.ERR_DUPLICATE_DENOMINATION.value,
            409,
        )

    def test_the_rejected_registration_leaves_one_variety_of_record(self, api):
        """A rejected duplicate must not be half-written, so the register still
        holds exactly the one original row.

        PRD 3.1: "A second registration under a name that already exists in any letter case is rejected with `ERR_DUPLICATE_DENOMINATION` (HTTP 409)."

        Design: Corner/validations/duplicate_denomination_compared_case_insensitively_rejected
        """
        self._registered_variety(api)
        validate_error(
            api.create_variety(
                create_variety_payload(denomination="  aurora bramble ",
                                       breeder_code="XX"),
                BREEDER,
            ),
            ApiErrorId.ERR_DUPLICATE_DENOMINATION.value,
            409,
        )

        _rows, meta = validate_paginated(api.list_varieties(BREEDER))
        assert meta["total_count"] == 1

    def test_a_longer_name_sharing_a_prefix_is_a_different_name(self, api):
        """The rule is equality of the whole trimmed name, not containment, so a
        denomination that merely begins with the existing one is accepted.

        PRD 3.1: "This uniqueness check sits in the constraint tier, after the referential checks and before the temporal ones."

        Design: Corner/validations/duplicate_denomination_compared_case_insensitively_rejected
        """
        self._registered_variety(api)

        accepted = validate_success(
            api.create_variety(
                create_variety_payload(denomination="Aurora Brambleberry",
                                       breeder_code="ABB"),
                BREEDER,
            ),
            201,
        )
        assert accepted["denomination"] == "Aurora Brambleberry"

        _rows, meta = validate_paginated(api.list_varieties(BREEDER))
        assert meta["total_count"] == 2


class TestTheMarkMustBeSeparateFromEveryVarietyName:
    """Two varieties, one of them already carrying a registered mark."""

    def _two_varieties_one_marked(self, api):
        first = create_variety(
            api, denomination="Bracken Bramble", species="Rubus idaeus",
            breeder_code="BK", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        second = create_variety(
            api, denomination="Coral Bramble", species="Rubus idaeus",
            breeder_code="CR", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        validate_success(
            api.brand_register_variety(
                second["id"],
                brand_register_payload(
                    brand_mark_text="CORALSTAR", brand_registry_class=31,
                    brand_renewal_due_at="2027-08-01T00:00:00Z",
                ),
                BREEDER,
            )
        )
        return first, second

    def test_a_mark_equal_to_the_varietys_own_name_is_refused(self, api):
        """A trimmed, case-folded restatement of the variety's own denomination is
        the first of the three collisions, and the refusal writes nothing.

        PRD 3.3: "Compared case-insensitively after trimming, the proposed `brand_mark_text` must not equal this variety's own `denomination`, must not equal any other variety's `denomination`, and must not equal any other variety's `brand_mark_text`."

        Design: Corner/validations/brand_mark_equal_to_the_denomination_rejected
        """
        first, _second = self._two_varieties_one_marked(api)

        validate_error(
            api.brand_register_variety(
                first["id"],
                brand_register_payload(
                    brand_mark_text=" bracken bramble ", brand_registry_class=31,
                    brand_renewal_due_at="2027-08-01T00:00:00Z",
                ),
                BREEDER,
            ),
            ApiErrorId.ERR_BRAND_CONFLICTS_DENOMINATION.value,
            422,
        )

        refreshed = validate_success(api.get_variety(first["id"], BREEDER))
        assert refreshed["brand_status"] == "BRAND_NONE"
        assert refreshed["brand_mark_text"] is None

    def test_another_varietys_name_and_another_varietys_mark_are_refused_too(self, api):
        """The check reaches across the whole register, so the second variety's
        denomination and its registered mark are both barred as well.

        PRD 3.3: "Any of those three collisions is rejected with `ERR_BRAND_CONFLICTS_DENOMINATION` (HTTP 422)."

        Design: Corner/validations/brand_mark_equal_to_the_denomination_rejected
        """
        first, _second = self._two_varieties_one_marked(api)

        validate_error(
            api.brand_register_variety(
                first["id"],
                brand_register_payload(brand_mark_text="Coral Bramble"),
                BREEDER,
            ),
            ApiErrorId.ERR_BRAND_CONFLICTS_DENOMINATION.value,
            422,
        )
        validate_error(
            api.brand_register_variety(
                first["id"],
                brand_register_payload(brand_mark_text="coralstar"),
                BREEDER,
            ),
            ApiErrorId.ERR_BRAND_CONFLICTS_DENOMINATION.value,
            422,
        )

    def test_a_genuinely_distinct_mark_registers_normally(self, api):
        """Nothing about the check is a blanket ban on family resemblance: a mark
        that collides with no name and no other mark is registered.

        PRD 3.3: "Within the business tier this check sits among the referential cross-checks, after the territory and report-to-agreement cross-checks and before the uniqueness constraints."

        Design: Corner/validations/brand_mark_equal_to_the_denomination_rejected
        """
        first, _second = self._two_varieties_one_marked(api)

        registered = validate_success(
            api.brand_register_variety(
                first["id"],
                brand_register_payload(
                    brand_mark_text="BRACKENSTAR", brand_registry_class=31,
                    brand_renewal_due_at="2027-08-01T00:00:00Z",
                ),
                BREEDER,
            )
        )
        assert registered["brand_status"] == "BRAND_REGISTERED"
        assert registered["brand_mark_text"] == "BRACKENSTAR"


class TestALapsedFilingReleasesItsTriple:
    """The duplicate-filing guard spans the live statuses only."""

    def _lapsed_us_filing(self, api):
        variety = create_variety(
            api, denomination="Elmshade Bramble", species="Rubus idaeus",
            breeder_code="EL", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        filing = create_filing(
            api, variety["id"], instrument_type="PLANT_PATENT",
            jurisdiction_code="US", annuity_base_cents=200000,
        )
        validate_success(api.file_protection_filing(filing["id"], BREEDER))
        validate_success(api.grant_protection_filing(filing["id"], BREEDER))
        lapsed = validate_success(api.lapse_protection_filing(filing["id"], BREEDER))
        return variety, filing, lapsed

    def test_a_replacement_application_is_accepted_and_lifts_the_posture(self, api):
        """With the triple released the identical application may be opened again,
        and the fresh draft lifts the posture off LAPSED_PROTECTION to PENDING
        without restoring any jurisdiction, since nothing is in force yet.

        PRD 3.1: "Once a filing has reached `LAPSED` or `ABANDONED` the triple is released and a replacement filing for the same variety, instrument and jurisdiction may be opened."

        Design: Corner/validations/replacement_filing_allowed_once_the_earlier_one_lapsed
        """
        variety, _filing, lapsed = self._lapsed_us_filing(api)
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapse_reason"] == "VOLUNTARY_LAPSE"

        before = validate_success(api.get_variety(variety["id"], BREEDER))
        assert before["protection_posture"] == "LAPSED_PROTECTION"
        assert before["protected_jurisdictions"] == []

        replacement = validate_success(
            api.create_protection_filing(
                create_protection_filing_payload(
                    variety["id"], instrument_type="PLANT_PATENT",
                    jurisdiction_code="US", annuity_base_cents=250000,
                ),
                BREEDER,
            ),
            201,
        )
        assert replacement["status"] == "DRAFT"
        assert replacement["annuity_base_cents"] == 250000

        after = validate_success(api.get_variety(variety["id"], BREEDER))
        assert after["protection_posture"] == "PENDING"
        assert after["protected_jurisdictions"] == []

    def test_the_lapsed_row_is_retained_and_the_new_draft_holds_the_triple(self, api):
        """The portfolio keeps both rows rather than overwriting the dead one, and
        the replacement itself now occupies the triple, so a third application is
        refused while it is still a draft.

        PRD 3.1: "At most one filing may exist for any given combination of variety, instrument type and jurisdiction while it is still live — that is, while its status is `DRAFT`, `FILED`, `GRANTED` or `MAINTENANCE_DUE`."

        Design: Corner/validations/replacement_filing_allowed_once_the_earlier_one_lapsed
        """
        variety, _filing, _lapsed = self._lapsed_us_filing(api)
        validate_success(
            api.create_protection_filing(
                create_protection_filing_payload(
                    variety["id"], instrument_type="PLANT_PATENT",
                    jurisdiction_code="US", annuity_base_cents=250000,
                ),
                BREEDER,
            ),
            201,
        )

        _rows, meta = validate_paginated(
            api.list_protection_filings(BREEDER, {"variety_id": variety["id"]})
        )
        assert meta["total_count"] == 2

        validate_error(
            api.create_protection_filing(
                create_protection_filing_payload(
                    variety["id"], instrument_type="PLANT_PATENT",
                    jurisdiction_code="US", annuity_base_cents=250000,
                ),
                BREEDER,
            ),
            ApiErrorId.ERR_DUPLICATE_FILING_JURISDICTION.value,
            409,
        )
