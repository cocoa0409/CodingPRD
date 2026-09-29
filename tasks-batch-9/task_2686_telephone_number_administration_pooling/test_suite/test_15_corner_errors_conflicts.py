"""Errors: an ownership mismatch and the four uniqueness keys that answer with 409."""
from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    create_block_payload,
    create_carrier_payload,
    create_eligible_carrier,
    create_filing,
    create_npa,
    create_npa_payload,
    create_rate_center,
    create_utilization_filing_payload,
    load_block,
    make_carrier_representative_headers,
    read_filing,
    register_carrier,
    set_clock,
    setup_npa_with_rate_center,
    validate_error,
    validate_paginated,
)

SIBLING_NAME = "DUBLIN"
DUPLICATE_LABEL = "614-555-0"

# A well-formed half-year report: 1300 assigned over two blocks.
MODEST_PERIOD = dict(
    numbers_assigned=1300,
    numbers_intermediate=0,
    numbers_reserved=0,
    numbers_aging=0,
    numbers_administrative=0,
    blocks_held_at_period_end=2,
    forecast_quarters=[600, 600, 600, 600],
)


class TestFilingForAnotherCarrierIsNotOwnership:
    """Every payload key is valid and only the acting identity is wrong."""

    def test_the_second_carriers_representative_cannot_file_the_firsts_report(self):
        """Both carriers are fully eligible and the report itself would be accepted from the
        right headers, so the refusal is about the identity alone.

        a `CarrierRepresentative`'s `X-User-ID` matches the carrier foreign key of the resource being acted on, else `ERR_NOT_RESOURCE_OWNER`.

        the acting id must equal `carrier_id` on an allocation request or a utilization filing

        A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

        Design: Corner/errors/carrier_representative_filing_for_another_carrier_is_not_the_owner
        """
        set_clock()
        acme = create_eligible_carrier("A")
        buckeye = create_eligible_carrier("B")
        _npa, rate_center = setup_npa_with_rate_center()

        error = validate_error(
            api_client.create_utilization_filing(
                create_utilization_filing_payload(
                    acme["id"], rate_center["id"], **MODEST_PERIOD
                ),
                make_carrier_representative_headers(buckeye["id"]),
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

        _rows, meta = validate_paginated(
            api_client.list_utilization_filings(
                ADMIN_HEADERS, params={"carrier_id": acme["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestOcnUniquenessIsGlobalRatherThanPerState:
    """A different legal name, type and home state do not buy a second use of the OCN."""

    def test_the_second_carrier_reusing_the_ocn_is_refused_and_the_first_survives(self):
        """Every field on the second payload is individually legal, and the collision on the
        one shared field is what closes it out.

        must be unique across every carrier on file — a collision is rejected with `ERR_DUPLICATE_OCN`

        `carrier_type`, the service category, which must be one of `ILEC`, `CLEC`, `WIRELESS` or `VOIP_INTERCONNECTED`

        Design: Corner/errors/duplicate_ocn_on_a_second_carrier_create
        """
        set_clock()
        acme = register_carrier("A")
        assert acme["ocn"] == "1234"

        validate_error(
            api_client.create_carrier(
                create_carrier_payload(
                    "A", legal_name="Great Lakes Telecom LLC", carrier_type="ILEC",
                    home_state_code="MI", months_in_operation=4,
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_OCN,
            409,
        )

        rows, meta = validate_paginated(api_client.list_carriers(ADMIN_HEADERS))
        assert meta["total_count"] == 1
        assert rows[0]["legal_name"] == "Acme Telecom LLC"
        assert rows[0]["carrier_type"] == "CLEC"
        assert rows[0]["home_state_code"] == "OH"


class TestAreaCodeUniquenessSpansTheWholeNumberingPlan:
    """Re-declaring the code for another state and another type is still a collision."""

    def test_the_second_area_code_is_refused_and_the_first_keeps_its_attributes(self):
        """The surviving row is the original one, unchanged in both the state it regulates
        and the kind of code it is.

        `npa_code` must be unique across every area code on file, and a collision — including one arising from a `new_npa_code` minted by a relief order — is rejected with `ERR_DUPLICATE_NPA_CODE`.

        A new code opens at `status` `ACTIVE`, with `available_block_count` and `total_block_count` both 0

        Design: Corner/errors/duplicate_npa_code_on_a_second_npa_create
        """
        set_clock()
        original = create_npa()
        assert original["npa_code"] == "614"
        assert original["status"] == "ACTIVE"

        validate_error(
            api_client.create_npa(
                create_npa_payload(npa_code="614", state_code="MI", npa_type="OVERLAY"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_NPA_CODE,
            409,
        )

        rows, meta = validate_paginated(api_client.list_npas(ADMIN_HEADERS))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == original["id"]
        assert rows[0]["state_code"] == "OH"
        assert rows[0]["npa_type"] == "GEOGRAPHIC"


class TestBlockUniquenessIsOnTheComposedLabel:
    """The second load names a different rate center and is still the same label."""

    def test_the_sibling_rate_center_cannot_take_the_same_label(self):
        """Both rate centers hang off the same area code, so the computed label collides even
        though every field the client sent differs.

        the platform computes `block_label` as the concatenation NPA-NXX-D, which must be unique across every block on file; a duplicate is rejected with `ERR_DUPLICATE_BLOCK_LABEL`

        Block listings can be narrowed by `npa_id`, `rate_center_id`, `holder_carrier_id`, `allocation_status` and `routing_status`

        Design: Corner/errors/duplicate_block_label_on_a_second_block_create
        """
        set_clock()
        npa, columbus = setup_npa_with_rate_center()
        dublin = create_rate_center(npa, name=SIBLING_NAME)
        first = load_block(npa, columbus, nxx_code="555", thousands_digit=0)
        assert first["block_label"] == DUPLICATE_LABEL

        validate_error(
            api_client.create_block(
                create_block_payload(
                    npa["id"], dublin["id"], nxx_code="555", thousands_digit=0,
                    contaminated_count=0,
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_BLOCK_LABEL,
            409,
        )

        _empty, dublin_meta = validate_paginated(
            api_client.list_rate_center_blocks(dublin["id"], ADMIN_HEADERS)
        )
        assert dublin_meta["total_count"] == 0

        rows, columbus_meta = validate_paginated(
            api_client.list_rate_center_blocks(columbus["id"], ADMIN_HEADERS)
        )
        assert columbus_meta["total_count"] == 1
        assert rows[0]["block_label"] == DUPLICATE_LABEL


class TestTheFilingPeriodKeyCountsADraftRow:
    """A report that was never submitted still occupies its reporting period."""

    def test_the_second_report_for_the_period_is_refused_and_the_draft_is_untouched(self):
        """The first row is still sitting in draft with its original count, so the second
        create neither replaced nor amended it.

        A carrier may hold at most one filing per rate center and reporting period that is not in `REJECTED` status; a second one is refused with `ERR_DUPLICATE_FILING_PERIOD`.

        A newly created filing sits at `DRAFT` with `submitted_at` null, `amendment_count` at 0 and `audited_utilization_pct` null.

        Design: Corner/errors/duplicate_filing_period_for_the_same_carrier_and_rate_center
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        draft = create_filing(carrier, rate_center, **MODEST_PERIOD)
        assert draft["status"] == "DRAFT"
        assert draft["submitted_at"] is None

        validate_error(
            api_client.create_utilization_filing(
                create_utilization_filing_payload(
                    carrier["id"], rate_center["id"],
                    numbers_assigned=1900, numbers_intermediate=0, numbers_reserved=0,
                    numbers_aging=0, numbers_administrative=0,
                    blocks_held_at_period_end=2,
                    forecast_quarters=[900, 900, 900, 900],
                ),
                make_carrier_representative_headers(carrier["id"]),
            ),
            ApiErrorId.ERR_DUPLICATE_FILING_PERIOD,
            409,
        )

        untouched = read_filing(draft["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["numbers_assigned"] == 1300
        assert untouched["amendment_count"] == 0
        assert untouched["audited_utilization_pct"] is None

        _rows, meta = validate_paginated(
            api_client.list_utilization_filings(
                ADMIN_HEADERS, params={"carrier_id": carrier["id"]}
            )
        )
        assert meta["total_count"] == 1
