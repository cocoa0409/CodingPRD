"""The error surface itself: every child entity's own not-found code, the
identity header that outranks every later check, the three payload-shape
failures that collapse into one code, and the immediate-consistency promise that
a late report's response already carries the consequences it caused.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
    headers_without_role,
    headers_without_user_id,
    make_facility_registrant_headers,
    make_responsible_person_agent_headers,
)
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X

ASTER_LABS = "Aster Labs Newark"
ASTER_HOLDINGS = "Aster Holdings LLC"
DESIGNEE_NAME = "Aster Brands Inc"


def _establishment_with_real_identities(api):
    """A registered establishment, a designee and a listing, so every caller identity resolves."""
    return X.registered_facility_with_listing(
        api,
        listing_overrides={"product_name": "Aster Blush Powder", "lot_authorized_units": 5000},
        person_overrides={"legal_name": DESIGNEE_NAME},
        facility_overrides={"facility_name": ASTER_LABS,
                            "owner_operator_name": ASTER_HOLDINGS},
    )


class TestEveryChildEntityLookupHasItsOwnNotFound:
    """A well-formed unknown identifier is answered by the code named for its entity."""

    def test_the_designee_dossier_and_filing_lookups_name_their_own_entity(self, api):
        """Four unknown identifiers across four different routes produce the code named for the
        entity each one addresses rather than one generic not-found.

        PRD: "A dossier identifier that resolves to nothing is `ERR_SUBSTANTIATION_NOT_FOUND` (HTTP 404)."
        PRD: "Either ruling requires the filing's `status` to be `FILED`; a filing that has already been decided or superseded yields `ERR_INVALID_OWNERSHIP_CHANGE_STATE` (HTTP 409), and a filing identifier that resolves to nothing yields `ERR_OWNERSHIP_CHANGE_NOT_FOUND` (HTTP 404)."
        PRD: "The transfer is admissible against any listing except a `DELISTED` one, and an incoming designee identifier that resolves to nothing is `ERR_RESPONSIBLE_PERSON_NOT_FOUND`."

        Design: Corner/errors/every_child_entity_lookup_is_reachable_as_not_found
        """
        bundle = _establishment_with_real_identities(api)

        validate_error(
            api.get_responsible_person(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            E.ERR_RESPONSIBLE_PERSON_NOT_FOUND,
        )
        validate_error(
            api.get_substantiation(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            E.ERR_SUBSTANTIATION_NOT_FOUND,
        )
        validate_error(
            api.decide_ownership_change(
                NON_EXISTENT_UUID, F.ownership_decision_payload("ACCEPT"), REVIEWER_HEADERS
            ),
            E.ERR_OWNERSHIP_CHANGE_NOT_FOUND,
        )
        validate_error(
            api.transfer_responsible_person(
                bundle["listing_id"],
                F.transfer_payload(NON_EXISTENT_UUID, bundle["listing"]["version"]),
                bundle["agent"],
            ),
            E.ERR_RESPONSIBLE_PERSON_NOT_FOUND,
        )

        assert X.read_listing(api, bundle["listing_id"])["responsible_person_id"] == \
            bundle["person_id"]

    def test_the_enforcement_side_lookups_name_their_own_entity(self, api):
        """The recall, the withdrawal round and the shipment record each answer with their own code,
        and none of the refused calls brings any of those entities into being.

        PRD: "Checks are evaluated in the fixed order below, and the first violated check produces the response."
        PRD: "Every identifier in the list must resolve to a record — validated in payload order, so the first unresolvable identifier is the one reported as `ERR_DISTRIBUTION_RECORD_NOT_FOUND` (HTTP 404) — the list must name at least one record, or it is refused with `ERR_NO_DISTRIBUTION_RECORDS` (HTTP 422), and every named record must belong to the listing the recall was opened against, or it is refused with `ERR_DISTRIBUTION_RECORD_LISTING_MISMATCH` (HTTP 422)."

        Design: Corner/errors/every_child_entity_lookup_is_reachable_as_not_found
        """
        bundle = _establishment_with_real_identities(api)

        validate_error(
            api.get_recall_action(NON_EXISTENT_UUID, OFFICER_HEADERS),
            E.ERR_RECALL_ACTION_NOT_FOUND,
        )
        validate_error(
            api.get_withdrawal(NON_EXISTENT_UUID, OFFICER_HEADERS),
            E.ERR_WITHDRAWAL_NOT_FOUND,
        )
        validate_error(
            api.get_distribution_record(NON_EXISTENT_UUID, OFFICER_HEADERS),
            E.ERR_DISTRIBUTION_RECORD_NOT_FOUND,
        )
        validate_error(
            api.file_adverse_event_report(NON_EXISTENT_UUID, bundle["agent"],
                                          F.report_payload()),
            E.ERR_ADVERSE_EVENT_NOT_FOUND,
        )

        recalls, recall_meta = validate_paginated(
            api.list_recall_actions(bundle["listing_id"], OFFICER_HEADERS,
                                    {"limit": K.MAX_LIMIT})
        )
        assert recall_meta["total_count"] == 0
        assert recalls == []
        events, event_meta = validate_paginated(
            api.list_adverse_events(bundle["listing_id"], REVIEWER_HEADERS,
                                    {"limit": K.MAX_LIMIT})
        )
        assert event_meta["total_count"] == 0
        assert events == []

    def test_an_existing_parent_does_not_mask_a_missing_child(self, api):
        """On the one nested path in this API the segments resolve left to right: a real
        establishment with an unknown engagement is an engagement miss, and an unknown
        establishment is reported before the engagement is ever looked up.

        PRD: "Paths in this API nest, and nested identifiers are resolved strictly **left to right**."
        PRD: "A request naming an inspection engagement beneath a facility that does not exist reports `ERR_FACILITY_NOT_FOUND` and never reaches the engagement lookup; a request naming an engagement that exists but belongs to a different facility than the one in the path reports `ERR_INSPECTION_NOT_FOUND`, because the engagement must resolve *within* the facility named to its left."

        Design: Corner/errors/every_child_entity_lookup_is_reachable_as_not_found
        """
        bundle = _establishment_with_real_identities(api)

        validate_error(
            api.submit_inspection_response(
                bundle["facility_id"], NON_EXISTENT_UUID,
                F.inspection_response_payload(), bundle["registrant"],
            ),
            E.ERR_INSPECTION_NOT_FOUND,
        )

        validate_error(
            api.submit_inspection_response(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                F.inspection_response_payload(),
                make_facility_registrant_headers(NON_EXISTENT_UUID),
            ),
            E.ERR_FACILITY_NOT_FOUND,
        )

        engagements, meta = validate_paginated(
            api.list_inspections(bundle["facility_id"], REVIEWER_HEADERS,
                                 {"limit": K.MAX_LIMIT})
        )
        assert meta["total_count"] == 0
        assert engagements == []


BLANK_IDENTITY_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": K.ROLE_REGULATORY_REVIEWER,
    "Content-Type": "application/json",
}


class TestTheIdentityHeaderOutranksEveryOtherCheck:
    """Priority 1 means authentication can never be inferred from a later error."""

    def test_a_read_without_an_acting_principal_is_unauthenticated(self, api):
        """Even a pure read of an existing establishment by an authorized role is refused when no
        principal is named, and the establishment is untouched by the refusal.

        PRD: "Every request to the service — reads included — must carry two headers."
        PRD: "If either header is absent or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."

        Design: Corner/errors/missing_user_header_is_unauthenticated_before_every_other_check
        """
        facility = X.create_registered_facility(
            api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
            state_or_province="NJ",
        )

        validate_error(
            api.get_facility(facility["id"],
                             headers_without_user_id(K.ROLE_REGULATORY_REVIEWER)),
            E.ERR_UNAUTHENTICATED,
        )

        assert X.read_facility(api, facility["id"])["registration_status"] == \
            K.REGISTRATION_STATUS_REGISTERED

    def test_the_identity_check_outranks_both_existence_and_schema(self, api):
        """A request that would also fail on a missing establishment and on an out-of-enum decision
        still answers on the header, and supplying the identity proves the later checks were real.

        PRD: "If either header is absent or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."
        PRD: "Checks are evaluated in the fixed order below, and the first violated check produces the response."
        PRD: "This ordering is normative — it is not a convenience and not \"roughly\" the order."

        Design: Corner/errors/missing_user_header_is_unauthenticated_before_every_other_check
        """
        facility = X.create_registered_facility(
            api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
            state_or_province="NJ",
        )

        validate_error(
            api.decide_registration(
                NON_EXISTENT_UUID,
                F.registration_decision_payload("NOT_A_DECISION"),
                headers_without_user_id(K.ROLE_REGULATORY_REVIEWER),
            ),
            E.ERR_UNAUTHENTICATED,
        )

        validate_error(
            api.decide_registration(
                NON_EXISTENT_UUID,
                F.registration_decision_payload("NOT_A_DECISION"),
                REVIEWER_HEADERS,
            ),
            E.ERR_FACILITY_NOT_FOUND,
        )

        assert X.read_facility(api, facility["id"])["registration_status"] == \
            K.REGISTRATION_STATUS_REGISTERED

    def test_a_blank_principal_and_a_missing_role_are_both_unauthenticated(self, api):
        """Blank counts as absent on either header, so neither a nameless caller nor a roleless one
        gets as far as the role check.

        PRD: "`X-User-ID` identifies the acting principal and `X-User-Role` names the role it is acting under."
        PRD: "If either header is absent or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."

        Design: Corner/errors/missing_user_header_is_unauthenticated_before_every_other_check
        """
        facility = X.create_registered_facility(
            api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
            state_or_province="NJ",
        )

        validate_error(
            api.get_facility(facility["id"], BLANK_IDENTITY_HEADERS),
            E.ERR_UNAUTHENTICATED,
        )
        validate_error(
            api.get_facility(facility["id"], headers_without_role(facility["id"])),
            E.ERR_UNAUTHENTICATED,
        )

        after = X.read_facility(api, facility["id"])
        assert after["registration_status"] == K.REGISTRATION_STATUS_REGISTERED
        assert after["version"] == facility["version"]


class TestMalformedPayloadsAllCollapseToInvalidRequest:
    """One code for three different shape failures, each decided before any domain rule."""

    def test_a_missing_required_field_is_a_schema_failure(self, api):
        """`product_name` is not one of the three optional fields, so a payload omitting it never
        reaches the category registry and no listing comes into being.

        PRD: "The payload names the manufacturing or processing establishment through `facility_id`, names the designee through `responsible_person_id`, and carries the trade `product_name`, the declared `category_code`, the `product_form` (`LEAVE_ON` or `RINSE_OFF`), the `label_contact_type` (`DOMESTIC_ADDRESS`, `DOMESTIC_PHONE` or `ELECTRONIC_CONTACT`) with its literal `label_contact_value`, and three optional fields: `professional_use_only` and `professional_use_statement_present`, each defaulting to false, and `lot_authorized_units`, the per-lot unit ceiling, defaulting to 0."
        PRD: "A value outside those bounds is a schema violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/errors/malformed_payloads_all_collapse_to_invalid_request
        """
        facility = X.create_registered_facility(
            api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
            state_or_province="NJ",
        )
        person = X.create_responsible_person(api, legal_name=DESIGNEE_NAME)
        agent = make_responsible_person_agent_headers(person["id"])

        nameless = F.listing_payload(facility["id"], person["id"])
        del nameless["product_name"]

        validate_error(api.create_listing(nameless, agent), E.ERR_INVALID_REQUEST)

        rows, meta = validate_paginated(
            api.list_listings(REVIEWER_HEADERS,
                              {"facility_id": facility["id"], "limit": K.MAX_LIMIT})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_an_out_of_enum_value_is_a_schema_failure(self, api):
        """A decision that is neither of the two permitted words is refused on shape at priority 5,
        so the establishment's own state is never even consulted.

        PRD: "A `RegulatoryReviewer` then decides the pending file, supplying `decision` — either `APPROVE` or `REJECT` — and optionally a `decision_note`."
        PRD: "A value outside those bounds is a schema violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/errors/malformed_payloads_all_collapse_to_invalid_request
        """
        facility = X.create_registered_facility(
            api, facility_name=ASTER_LABS, owner_operator_name=ASTER_HOLDINGS,
            state_or_province="NJ",
        )

        validate_error(
            api.decide_registration(
                facility["id"],
                F.registration_decision_payload("MAYBE_LATER"),
                REVIEWER_HEADERS,
            ),
            E.ERR_INVALID_REQUEST,
        )

        after = X.read_facility(api, facility["id"])
        assert after["registration_status"] == K.REGISTRATION_STATUS_REGISTERED
        assert after["version"] == facility["version"]

    def test_a_wrong_scalar_type_is_a_schema_failure(self, api):
        """`units_shipped` is a count of units, so a word where an integer belongs is the same one
        code again — and no shipment is recorded against the listing.

        PRD: "A `ResponsiblePersonAgent` records each shipment of a listed product as it happens, naming the `lot_code` (1 to 40 characters), the `consignee_name` (1 to 200 characters), the `consignee_class` (`WHOLESALE`, `RETAIL` or `CONSUMER`), the **closed-closed** distribution window `ship_date` to `delivery_date` — both days inclusive — and the `units_shipped`, which must be greater than zero."
        PRD: "A value outside those bounds is a schema violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/errors/malformed_payloads_all_collapse_to_invalid_request
        """
        bundle = _establishment_with_real_identities(api)

        validate_error(
            api.create_distribution_record(
                bundle["listing_id"],
                F.distribution_record_payload(lot_code="LOT-X", units_shipped="a lot"),
                bundle["agent"],
            ),
            E.ERR_INVALID_REQUEST,
        )

        rows, meta = validate_paginated(
            api.list_distribution_records(
                REVIEWER_HEADERS, {"listing_id": bundle["listing_id"], "limit": K.MAX_LIMIT}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert X.read_listing(api, bundle["listing_id"])["distributed_units_total"] == 0


INTAKE_CLOCK = "2026-08-05T08:00:00Z"
RECEIVED_AT = "2026-08-05T00:00:00Z"
DEADLINE_AT = "2026-08-20T23:59:59.999Z"
FILING_CLOCK = "2026-08-23T10:00:00Z"
LATE_DAYS = 3
LATE_POINTS = 6.50


class TestTheLateReportResponseAlreadyCarriesWhatItCaused:
    """No re-read, no sweep, no delay: the consequences are visible in the same window."""

    def _serious_event_two_days_past_its_deadline(self, api):
        """A serious event received 2026-08-05, with the clock moved to 2026-08-23T10:00:00Z."""
        bundle = _establishment_with_real_identities(api)
        X.set_clock(api, INTAKE_CLOCK)
        bundle["event"] = X.record_serious_event(
            api, bundle["listing_id"], bundle["agent"], received_at=RECEIVED_AT,
            event_description="Chemical burn requiring urgent care",
            outcome_code="HOSPITALIZATION",
        )
        assert bundle["event"]["deadline_at"] == DEADLINE_AT
        X.set_clock(api, FILING_CLOCK)
        return bundle

    def test_the_report_response_itself_carries_the_lateness_and_the_points(self, api):
        """Two days and a millisecond past the deadline rounds up to three days late, and the late
        base of 5 at a factor of 1.3 is already priced into the very response that filed it.

        PRD: "After it the event takes `REPORT_DUE → REPORTED_LATE` with `lateness_days` set to the number of whole days by which the filing overran, computed as the elapsed time from `deadline_at` to `submitted_at` divided by one day and rounded **up** to the next integer."
        PRD: "The base is 2 for a timely report, 5 for a late one and 9 for a report that is overdue and still unfiled — the unfiled state is deliberately the most expensive of the three."
        PRD: "The lateness factor is one plus a tenth per day of lateness, capped at 2.0, so lateness stops accruing at ten days."

        Design: Corner/consistency_model/the_late_report_response_already_carries_the_points_and_posture_it_caused
        """
        bundle = self._serious_event_two_days_past_its_deadline(api)

        filed = get_success_data(
            api.file_adverse_event_report(
                bundle["event"]["id"], bundle["agent"],
                F.report_payload(report_narrative="Filed after an internal review delay"),
            )
        )

        assert filed["report_status"] == K.EVENT_STATUS_REPORTED_LATE
        assert filed["lateness_days"] == LATE_DAYS
        A.assert_two_decimal_value(filed["event_points"], LATE_POINTS, "event points")
        assert filed["submitted_at"] == FILING_CLOCK
        assert filed["deadline_at"] == DEADLINE_AT

    def test_the_next_read_already_shows_the_points_and_the_posture(self, api):
        """The establishment's denormalized total does not lag by a request: the read immediately
        after the filing shows 6.50 points, a posture still short of the restricted threshold, and
        an open-event counter already discharged on both sides.

        PRD: "Hop 2 recomputes the establishment's `serious_event_points` and `compliance_posture`."
        PRD: "Independently of the cascade, both `open_serious_event_count` values fall by 1, because the event is no longer awaiting a report."
        PRD: "The points component of the posture is `FROZEN` at 25.00 or more, `RESTRICTED` at 10.00 or more, and `OPEN` below that, with both comparisons inclusive at the boundary and made against the two-decimal stored value: 9.50 leaves the establishment `OPEN`, 10.00 exactly makes it `RESTRICTED`, 24.99 is still `RESTRICTED` and 25.00 is `FROZEN`."

        Design: Corner/consistency_model/the_late_report_response_already_carries_the_points_and_posture_it_caused
        """
        bundle = self._serious_event_two_days_past_its_deadline(api)
        get_success_data(
            api.file_adverse_event_report(
                bundle["event"]["id"], bundle["agent"],
                F.report_payload(report_narrative="Filed after an internal review delay"),
            )
        )

        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], LATE_POINTS, "points")
        assert facility["compliance_posture"] == K.POSTURE_OPEN
        assert facility["open_serious_event_count"] == 0

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["open_serious_event_count"] == 0
        assert listing["marketable"] is False

    def test_the_ledger_entry_is_already_written_and_no_posture_entry_joins_it(self, api):
        """The compliance fact is appended inside the same request, and because 6.50 points left the
        dial where it was, the report entry stands alone.

        PRD: "The ledger records this in a fixed order: one `ADVERSE_EVENT_REPORT` entry against the event, then — only when the posture actually changed — one `POSTURE_CHANGE` entry carrying the before and after values, then one `STATE_TRANSITION` entry per revalidated listing."
        PRD: "Where §3 describes a cascade in numbered hops, the hops execute in the stated order within the same request, every resource each hop touches has its `updated_at` refreshed and its `version` incremented by exactly 1, and the ordering rule for multi-row hops (almost always ascending `created_at`) is part of the contract because the ledger entries the cascade appends must appear in that same order."

        Design: Corner/consistency_model/the_late_report_response_already_carries_the_points_and_posture_it_caused
        """
        bundle = self._serious_event_two_days_past_its_deadline(api)
        get_success_data(
            api.file_adverse_event_report(
                bundle["event"]["id"], bundle["agent"],
                F.report_payload(report_narrative="Filed after an internal review delay"),
            )
        )

        reports = X.ledger_entries(api, bundle["facility_id"],
                                   K.ENTRY_TYPE_ADVERSE_EVENT_REPORT)
        assert len(reports) == 1
        assert reports[0]["subject_entity"] == "AdverseEvent"
        assert reports[0]["subject_id"] == bundle["event"]["id"]
        assert reports[0]["occurred_at"] == FILING_CLOCK

        assert X.ledger_entries(api, bundle["facility_id"],
                                K.ENTRY_TYPE_POSTURE_CHANGE) == []
