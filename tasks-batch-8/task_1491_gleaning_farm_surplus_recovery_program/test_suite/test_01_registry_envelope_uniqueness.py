"""Registration, response envelope, pagination, and uniqueness claims (PRD §2.2-2.4, §3.1-3.3)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_farm,
    coordinator_headers,
    create_container_payload,
    create_farm_payload,
    create_offer_payload,
    create_vehicle_payload,
    create_volunteer_payload,
    get_success_data,
    new_farm,
    new_offer,
    new_vehicle,
    new_volunteer,
    new_container,
    new_event,
    new_crew_leader,
    sign_waiver,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFarmRegistration:
    def test_farm_creation_applies_defaults(self, api):
        """PRD §3.1: "The farm's `active_flag` defaults to true at registration"

        Design: Corner/entities/farm_creation_defaults_and_required_fields
        """
        resp = api.create_farm(
            create_farm_payload(
                farm_name="CornerFarm", contact_email="cf@x.com",
                county_code="CF1", donor_tin="20-1111111",
            ),
            coordinator_headers(),
        )
        farm = validate_success(resp, 201)
        assert_farm(farm)
        assert farm["active_flag"] is True, "active_flag must default to true"
        assert farm["lifetime_donated_lbs"] == 0

    def test_farm_creation_missing_donor_tin_rejected(self, api):
        """PRD §2.6: "26. **Request shape** — required fields present and typed per the
        resource model, enum values within their declared sets, failing with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/farm_creation_defaults_and_required_fields
        """
        resp = api.create_farm(
            {"farm_name": "NoTIN", "contact_email": "nt@x.com", "county_code": "CF1"},
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestEnvelopeAndPagination:
    def test_get_missing_farm_returns_not_found_envelope(self, api):
        """PRD §2.6: "3. **Existence** — every identifier in the path (validated left to
        right) and every foreign key in the body must reference an existing resource,
        failing with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/entity_not_found_envelope
        """
        resp = api.get_farm(NON_EXISTENT_UUID, coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)

    def test_list_volunteers_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry the following fields in the `meta` object of
        the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_pagination_envelope
        """
        emails = []
        for name in ("P A", "P B", "P C"):
            vol = new_volunteer(full_name=name)
            emails.append(vol["email"])
        resp = api.list_volunteers(coordinator_headers(), params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, "limit=2 must return exactly 2 rows"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2 and meta["offset"] == 0
        assert data[0]["email"] in emails


class TestReverseReachability:
    def test_fk_reverse_reachability_subresources(self, api):
        """PRD §3.2: "Waivers can be fetched individually, listed per volunteer through
        the volunteer's waiver listing, or listed per event."
        PRD §3.6: "Afterward, the receipt for a closed offer can be fetched directly —
        a list of zero or one entries — and all receipts issued to a farm can be listed
        through the farm's receipt listing, just as the farm's offers can be listed
        through its offer listing."

        Design: Corner/entities/fk_reverse_reachability_subresources
        """
        farm = new_farm(farm_name="RF", county_code="RF1")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        vol = new_volunteer(full_name="RV")
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"], crew_capacity=2)
        waiver = sign_waiver(event["id"], vol["id"], lead["id"])

        offers = get_success_data(api.list_farm_offers(farm["id"], coordinator_headers()))
        assert any(o["id"] == offer["id"] for o in offers), "farm -> offers must list the offer"

        event_waivers = get_success_data(api.list_event_waivers(event["id"], coordinator_headers()))
        assert any(w["id"] == waiver["id"] for w in event_waivers)
        assert event_waivers[0]["glean_event_id"] == event["id"]

        vol_waivers = get_success_data(api.list_volunteer_waivers(vol["id"], coordinator_headers()))
        assert any(w["id"] == waiver["id"] for w in vol_waivers)
        assert vol_waivers[0]["volunteer_id"] == vol["id"]

        receipts = get_success_data(api.get_offer_receipt(offer["id"], coordinator_headers()))
        assert receipts == [], "receipt listing must be an empty array before close"


class TestOfferInputConstraints:
    def test_offer_invalid_perishability_enum_rejected(self, api):
        """PRD §2.6: "26. **Request shape** — required fields present and typed per the
        resource model, enum values within their declared sets, failing with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "The offer also declares a `perishability_class` — `HIGH` for leafy
        greens and berries with a 24-hour cold-chain limit, `MEDIUM` for stone fruit
        with a 72-hour limit, or `LOW` for roots and winter squash with a 168-hour limit"

        Design: Corner/entities/offer_enum_and_window_type_constraints
        """
        farm = new_farm(farm_name="EF", county_code="EF1")
        resp = api.create_offer(
            create_offer_payload(farm["id"], perishability_class="TURBO"),
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_offer_window_end_before_start_rejected(self, api):
        """PRD §3.1: "`window_start` is inclusive, `window_end` is exclusive, and the
        end must fall strictly after the start."

        Design: Corner/entities/offer_enum_and_window_type_constraints
        """
        farm = new_farm(farm_name="EF2", county_code="EF2")
        resp = api.create_offer(
            create_offer_payload(
                farm["id"],
                window_start="2026-08-20T00:00:00Z",
                window_end="2026-08-05T00:00:00Z",
            ),
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestUniqueness:
    def test_duplicate_volunteer_email_rejected(self, api):
        """PRD §3.2: "Volunteers are registered by a coordinator with a `full_name` and
        an `email` that must be unique across all volunteers — a duplicate address is
        rejected with `ERR_DUPLICATE`."

        Design: Corner/errors/duplicate_volunteer_email
        """
        new_volunteer(full_name="Dup One", email="dup@x.com")
        resp = api.create_volunteer(
            create_volunteer_payload(full_name="Dup Two", email="dup@x.com"),
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, 409)

    def test_duplicate_container_label_and_vehicle_plate_rejected(self, api):
        """PRD §3.3: "A **Container** is registered with a human-readable `label` that
        must be unique (`ERR_DUPLICATE`)"
        PRD §3.3: "A **Vehicle** is registered with a unique `plate` (`ERR_DUPLICATE`)"

        Design: Corner/errors/duplicate_container_label_and_vehicle_plate
        """
        new_container(label="BIN-DUP")
        new_vehicle(plate="PL-DUP")
        resp_c = api.create_container(
            create_container_payload(label="BIN-DUP", tare_lbs=5.0, capacity_lbs=100.0,
                                     refrigerated=True),
            coordinator_headers(),
        )
        validate_error(resp_c, ApiErrorId.ERR_DUPLICATE, 409)
        resp_v = api.create_vehicle(
            create_vehicle_payload(plate="PL-DUP", payload_capacity_lbs=100.0,
                                   refrigerated=True),
            coordinator_headers(),
        )
        validate_error(resp_v, ApiErrorId.ERR_DUPLICATE, 409)
