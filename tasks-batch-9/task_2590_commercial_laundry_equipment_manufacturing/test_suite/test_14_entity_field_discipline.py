"""Field discipline across the record set: which fields the server mints itself.

Covers the technician record's server-stamped identity and certification seeds,
the closed product-line enumeration, the append-only shape of a station log, a
dossier's dependence on its parent model, and the two reference topologies —
quote lines joining quotes to models, and a service part superseding another.
"""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID
from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    DOSSIER_PREPARER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    TRAINING_ADMIN,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp so one instant compares equal to itself."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _build_quote_junction(api, channel: dict) -> dict:
    """Two quotes for one distributor: the first carries both models, the second
    carries the on-premises model again."""
    on_premises = fx.make_model(api, model_code="OPL-60-A")
    vended = fx.make_vended_model(api)
    first = fx.make_quote(
        api,
        channel,
        customer_name="Sudz Express",
        laundromat_site_code="SITE-77",
        stated_credit_score=715,
        financing_program="NONE",
    )
    fx.add_quote_line(api, first["id"], channel, on_premises["id"], quantity=1)
    fx.add_quote_line(
        api, first["id"], channel, vended["id"], quantity=1, payment_module="COIN"
    )
    second = fx.make_quote(
        api,
        channel,
        customer_name="Wash Barn LLC",
        laundromat_site_code="SITE-88",
        stated_credit_score=700,
        financing_program="NONE",
    )
    fx.add_quote_line(api, second["id"], channel, on_premises["id"], quantity=2)
    return {"on_premises": on_premises, "vended": vended, "first": first, "second": second}


class TestTechnicianSystemFields:
    def test_01_identity_and_timestamps_are_server_stamped(self, api):
        """A newly registered technician carries a bare server-minted identifier, matching creation stamps taken from the logical clock, and version one.

        PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed on every mutation of the row, and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row."
        Design: Corner/entities/technician_system_fields_are_server_minted
        """
        payload = f.technician_payload(
            employee_code="T-100", full_name="Ann Ito", employer="FACTORY"
        )

        data = validate_success(api.create_technician(payload, TRAINING_ADMIN), 201)

        a.assert_common_fields(data)
        assert data["version"] == 1
        assert _instant(data["created_at"]) == _instant("2026-08-01T00:00:00.000Z")
        assert data["updated_at"] == data["created_at"]

    def test_02_certification_fields_start_uncertified(self, api):
        """A factory technician joins the roster uncertified, with no scopes, no expiry, no certification action on record and no revocations.

        PRD: "A new technician begins with `cert_state` at `UNCERTIFIED`, `cert_scopes` an empty array, `cert_expires_on` null, `last_cert_action_at` null and `revocation_count` at 0."
        Design: Corner/entities/technician_system_fields_are_server_minted
        """
        payload = f.technician_payload(
            employee_code="T-100", full_name="Ann Ito", employer="FACTORY"
        )

        data = validate_success(api.create_technician(payload, TRAINING_ADMIN), 201)

        assert data["cert_state"] == "UNCERTIFIED"
        assert data["cert_scopes"] == []
        assert data["cert_expires_on"] is None
        assert data["last_cert_action_at"] is None
        assert data["revocation_count"] == 0
        assert data["distributor_id"] is None


class TestMachineModelEnumDiscipline:
    def test_01_near_miss_product_line_is_refused(self, api):
        """A registration naming a product line that is one letter away from a declared one is refused and nothing enters the catalogue.

        PRD: "The request body parses, every required input field is present, every enum-typed value is a declared member of its enumeration, every integer sits inside its declared range, and every decimal carries no more than its declared scale."
        Design: Corner/entities/machine_model_unknown_product_line_enum_rejected
        """
        payload = f.machine_model_payload(
            model_code="OPL-60-B",
            product_line="ON_PREMISE",
            capacity_rating_lb=60,
            rated_water_gal_per_cwt=1.10,
            rated_kwh_per_cwt=0.42,
            drum_alloy_grade="AISI_304",
            payment_module_options=[],
            list_price_cents=1250000,
        )

        validate_error(
            api.create_machine_model(payload, PRODUCT_ENGINEER),
            E.ERR_INVALID_REQUEST,
            400,
        )

        rows, meta = validate_paginated(api.list_machine_models(PRODUCT_ENGINEER))
        assert rows == []
        assert meta["total_count"] == 0


class TestStationLogImmutability:
    def test_01_the_floor_record_carries_no_version_and_no_updated_at(
        self, api, floor_environment
    ):
        """A station log read back from the floor exposes only its identifier and creation stamp, with no revision fields on the row at all.

        PRD: "A `StationLog` and a `QuoteLine` are immutable journal rows: each carries only `id` and `created_at`."
        Design: Corner/entities/station_log_is_immutable_and_carries_no_version
        """
        env = floor_environment
        build = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0001")
        fx.release_build(api, build["id"])
        log = fx.log_station_pass(
            api,
            build["id"],
            env["stations"]["drum"],
            env["technician"]["id"],
            fx.DRUM_START,
            fx.DRUM_END,
        )

        data = validate_success(api.get_station_log(log["id"], PLANT_MANAGER), 200)

        a.assert_journal_fields(data)
        assert data["outcome"] == "PASS"
        assert data["defect_code"] == "NONE"


class TestCertificationDossierParent:
    def test_01_dossier_under_an_unknown_model_is_a_not_found(self, api):
        """Opening a certification dossier under a model that was never registered is refused as an unknown model.

        PRD: "A machine-model identifier in the path resolves to a stored model — otherwise `ERR_MODEL_NOT_FOUND`, HTTP 404."
        Design: Corner/entities/certification_dossier_under_unknown_model_not_found
        """
        payload = f.dossier_payload(
            measured_water_gal_per_cwt=1.05,
            measured_kwh_per_cwt=0.40,
            test_cycle_count=120,
        )

        validate_error(
            api.create_certification_dossier(
                NON_EXISTENT_UUID, payload, DOSSIER_PREPARER
            ),
            E.ERR_MODEL_NOT_FOUND,
            404,
        )


class TestQuoteLineJunction:
    def test_01_lines_are_queryable_from_both_ends_of_the_junction(
        self, api, pending_distributor
    ):
        """Filtering the line collection by the on-premises model returns its two lines across two different quotes, and filtering by the first quote returns that quote's two lines.

        PRD: "Quote lines may be read individually or listed with `quote_id` and `model_id` filters; quotes are listed newest-first with `distributor_id` and `quote_state` filters, and a `Distributor` sees only its own."
        Design: Corner/entities/quote_lines_link_many_quotes_to_many_models
        """
        env = _build_quote_junction(api, pending_distributor)

        rows, meta = validate_paginated(
            api.list_quote_lines(CHANNEL_MANAGER, model_id=env["on_premises"]["id"])
        )

        assert len(rows) == 2
        assert meta["total_count"] == 2
        assert {row["model_id"] for row in rows} == {env["on_premises"]["id"]}
        assert {row["quote_id"] for row in rows} == {
            env["first"]["id"],
            env["second"]["id"],
        }

        by_quote, by_quote_meta = validate_paginated(
            api.list_quote_lines(CHANNEL_MANAGER, quote_id=env["first"]["id"])
        )
        assert len(by_quote) == 2
        assert by_quote_meta["total_count"] == 2

    def test_02_each_quote_counts_only_its_own_lines(self, api, pending_distributor):
        """The two-model quote reports two lines while the single-model quote reports one.

        PRD: "`line_count` is the number of lines on the quote."
        Design: Corner/entities/quote_lines_link_many_quotes_to_many_models
        """
        env = _build_quote_junction(api, pending_distributor)

        first = validate_success(api.get_quote(env["first"]["id"], CHANNEL_MANAGER), 200)
        second = validate_success(
            api.get_quote(env["second"]["id"], CHANNEL_MANAGER), 200
        )

        assert first["line_count"] == 2
        assert second["line_count"] == 1


class TestServicePartSupersession:
    def test_01_the_supersession_edge_is_queryable_in_both_directions(self, api):
        """The successor bearing declares the part it replaces, the collection filtered on that predecessor returns exactly the successor, and the original declares no predecessor of its own.

        PRD: "Because the reference is self-referential, the supersession chain can be walked in either direction: the parts collection accepts a `supersedes_part_id` filter that returns every part declaring a given predecessor, alongside `component_class` and `stock_state` filters."
        Design: Corner/entities/service_part_supersedes_link_is_self_referential
        """
        predecessor = fx.make_service_part(api, part_number="BRG-2040")
        payload = f.service_part_payload(
            part_number="BRG-2041",
            rated_duty_cycles=36000,
            unit_price_cents=45000,
            supersedes_part_id=predecessor["id"],
        )

        successor = validate_success(
            api.create_service_part(payload, PRODUCT_ENGINEER), 201
        )
        assert successor["supersedes_part_id"] == predecessor["id"]

        rows, meta = validate_paginated(
            api.list_service_parts(
                PRODUCT_ENGINEER, supersedes_part_id=predecessor["id"]
            )
        )
        assert meta["total_count"] == 1
        a.assert_ids_in_order(rows, [successor["id"]])

        original = validate_success(
            api.get_service_part(predecessor["id"], PRODUCT_ENGINEER), 200
        )
        assert original["supersedes_part_id"] is None

    def test_02_the_successor_part_starts_with_an_empty_shelf(self, api):
        """The successor bearing is catalogued with nothing on the shelf and nothing reserved, so it reads as backordered from the moment it exists.

        PRD: "A freshly created part has `on_hand_qty` at 0 and `reserved_qty` at 0, and its derived `stock_state` therefore begins at `BACKORDERED`."
        Design: Corner/entities/service_part_supersedes_link_is_self_referential
        """
        predecessor = fx.make_service_part(api, part_number="BRG-2040")
        payload = f.service_part_payload(
            part_number="BRG-2041",
            rated_duty_cycles=36000,
            unit_price_cents=45000,
            supersedes_part_id=predecessor["id"],
        )

        successor = validate_success(
            api.create_service_part(payload, PRODUCT_ENGINEER), 201
        )

        assert successor["on_hand_qty"] == 0
        assert successor["reserved_qty"] == 0
        assert successor["stock_state"] == "BACKORDERED"
