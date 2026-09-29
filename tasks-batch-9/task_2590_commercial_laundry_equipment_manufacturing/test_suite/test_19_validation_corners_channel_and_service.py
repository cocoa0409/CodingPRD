"""Channel, compliance and after-sales rejections at the edges of the rule set.

Territory exclusivity, the single open certification dossier per model, the
non-negative stock position, the distributor training ledger, warranty
coverability, the bearing preload window and quote ownership are each pinned at
the point where they refuse — or, at the preload lower bound, accept.
"""

from datetime import datetime

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    COMPLIANCE_OFFICER,
    DOSSIER_PREPARER,
    ENERGY_REVIEWER,
    PLANT_MANAGER,
    TRAINING_ADMIN,
    WARRANTY_ANALYST,
    make_distributor_headers,
    make_technician_headers,
)

# The lower edge of the acceptance window the AISI_304 drum shell selects.
LOWER_BOUND_PRELOAD_304 = c.PRELOAD_WINDOWS["AISI_304"][0]

# The bearing visit that follows the standard 08:00-09:00 drum visit.
BEARING_START = "2026-08-01T09:00:00Z"
BEARING_END = "2026-08-01T10:00:00Z"
BEARING_OCCUPATION_TO = "2026-08-01T10:15:00Z"


def _instant(value: str) -> datetime:
    """Read an ISO 8601 UTC stamp back as an instant, whatever its precision."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _unit_at_drum_done(api):
    """A certified AISI_304 model, a drum cell and a bearing cell, a technician
    holding both floor scopes, and one unit that has passed drum fabrication."""
    env = fx.make_certified_model(api)
    drum_cell = fx.make_station(
        api,
        station_code="DRUM-01",
        station_type="DRUM_FAB",
        parallel_capacity=1,
        changeover_buffer_minutes=30,
        supported_product_lines=["ON_PREMISES"],
    )
    bearing_cell = fx.make_station(
        api,
        station_code="BRG-01",
        station_type="BEARING_INSTALL",
        parallel_capacity=1,
        changeover_buffer_minutes=15,
        supported_product_lines=["ON_PREMISES"],
    )
    technician = fx.make_certified_technician(
        api,
        ["DRUM_FAB", "BEARING_INSTALL"],
        employee_code="T-100",
        full_name="Ann Ito",
        employer="FACTORY",
    )
    build = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0001")
    fx.release_build(api, build["id"])
    fx.log_station_pass(
        api,
        build["id"],
        drum_cell,
        technician["id"],
        "2026-08-01T08:00:00Z",
        "2026-08-01T09:00:00Z",
    )
    return {
        "model": env["model"],
        "bearing_cell": bearing_cell,
        "technician": technician,
        "build": build,
    }


class TestDistributorTerritoryExclusivity:
    """Admission to a territory another distributor already holds exclusively."""

    def test_01_exclusive_territory_blocks_second_distributor_rejected(self, api):
        """A non-exclusive applicant is still refused a territory an existing
        distributor holds exclusively, while a free territory admits it.

        PRD: "And creating any distributor at all — exclusive or not — in a `territory_code` that a non-terminated distributor already holds exclusively is likewise rejected."
        Design: Corner/validations/exclusive_territory_blocks_second_distributor_rejected
        """
        incumbent = fx.make_distributor(api)

        rejected = api.create_distributor(
            f.distributor_payload(
                distributor_code="D-02",
                legal_name="Gulf Coin Laundry",
                territory_code="TX-CENTRAL",
                territory_exclusive=False,
            ),
            CHANNEL_MANAGER,
        )
        validate_error(
            rejected, E.ERR_TERRITORY_EXCLUSIVITY_CONFLICT, expected_status=409
        )

        channel = validate_success(
            api.list_distributors(CHANNEL_MANAGER), expected_status=200
        )
        assert len(channel) == 1, channel
        assert channel[0]["id"] == incumbent["id"]

        accepted = validate_success(
            api.create_distributor(
                f.distributor_payload(
                    distributor_code="D-02",
                    legal_name="Gulf Coin Laundry",
                    territory_code="TX-NORTH",
                    territory_exclusive=False,
                ),
                CHANNEL_MANAGER,
            ),
            expected_status=201,
        )
        assert accepted["territory_code"] == "TX-NORTH"


class TestCertificationDossierOpening:
    """Only one dossier of a model may be in play at a time."""

    def test_01_second_open_dossier_for_same_model_rejected(self, api):
        """A second dossier is refused while the first is still in review, and
        becomes possible once that first dossier has been rejected.

        PRD: "A model may have only one dossier in play at a time: opening a dossier while the model already has one in `IN_REVIEW`, `CERTIFIED` or `RESURVEY_REQUIRED` is rejected with `ERR_DOSSIER_ALREADY_OPEN`."
        Design: Corner/validations/second_open_dossier_for_same_model_rejected
        """
        model = fx.make_model(api)
        first = fx.make_dossier(api, model["id"])
        assert first["dossier_state"] == "IN_REVIEW"

        second_payload = f.dossier_payload(
            measured_water_gal_per_cwt=1.00,
            measured_kwh_per_cwt=0.38,
            test_cycle_count=150,
        )
        rejected = api.create_certification_dossier(
            model["id"], second_payload, DOSSIER_PREPARER
        )
        validate_error(rejected, E.ERR_DOSSIER_ALREADY_OPEN, expected_status=409)

        dossiers = validate_success(
            api.list_model_certification_dossiers(model["id"], COMPLIANCE_OFFICER),
            expected_status=200,
        )
        assert len(dossiers) == 1, dossiers
        assert dossiers[0]["id"] == first["id"]

        # A rejected dossier is terminal but does not block a fresh attempt.
        rejection = validate_success(
            api.create_dossier_review(
                first["id"], f.review_payload("ENERGY", "REJECT"), ENERGY_REVIEWER
            ),
            expected_status=200,
        )
        assert rejection["dossier_state"] == "REJECTED"

        accepted = validate_success(
            api.create_certification_dossier(
                model["id"], second_payload, DOSSIER_PREPARER
            ),
            expected_status=201,
        )
        assert accepted["dossier_state"] == "IN_REVIEW"


class TestServicePartStockAdjustment:
    """A stock movement is judged on the position it leaves behind."""

    def test_01_stock_adjustment_below_zero_rejected(self, api):
        """Shrinking two units out of a one-unit shelf is refused and writes
        nothing, while shrinking one unit is accepted and empties the shelf.

        PRD: "The `on_hand_qty` changes by that delta; an adjustment that would drive it below zero is rejected with `ERR_STOCK_ADJUSTMENT_NEGATIVE` and nothing is written."
        Design: Corner/validations/stock_adjustment_below_zero_rejected
        """
        part = fx.make_service_part(api)
        received = fx.adjust_stock(api, part["id"], 1)
        version_before = received["version"]

        rejected = api.create_stock_adjustment(
            part["id"], f.stock_adjustment_payload(-2, "SCRAP"), PLANT_MANAGER
        )
        validate_error(rejected, E.ERR_STOCK_ADJUSTMENT_NEGATIVE, expected_status=422)

        unchanged = validate_success(
            api.get_service_part(part["id"], PLANT_MANAGER), expected_status=200
        )
        assert unchanged["on_hand_qty"] == 1
        assert unchanged["stock_state"] == "LOW"
        assert unchanged["version"] == version_before

        emptied = validate_success(
            api.create_stock_adjustment(
                part["id"], f.stock_adjustment_payload(-1, "SCRAP"), PLANT_MANAGER
            ),
            expected_status=200,
        )
        assert emptied["on_hand_qty"] == 0
        assert emptied["stock_state"] == "BACKORDERED"


class TestDistributorTrainingLedger:
    """The training ledger only credits the distributor's own technicians."""

    def test_01_factory_technician_on_distributor_training_rejected(self, api):
        """A factory technician's installation training cannot be credited to a
        distributor, so the ledger and its counters stay untouched.

        PRD: "Two further conditions apply: the distributor must still be in `PENDING_TRAINING`, or the request is `ERR_DISTRIBUTOR_STATE_INVALID`, and the named technician must have `employer` of `DISTRIBUTOR` with a `distributor_id` equal to the distributor being addressed, or the request is `ERR_TECHNICIAN_DISTRIBUTOR_MISMATCH` — a factory technician's training, or another distributor's technician, cannot be credited here."
        Design: Corner/validations/factory_technician_on_distributor_training_rejected
        """
        distributor = fx.make_distributor(api)
        factory_technician = fx.make_technician(api)
        assert factory_technician["employer"] == "FACTORY"

        rejected = api.create_training_completion(
            distributor["id"],
            f.training_completion_payload(
                factory_technician["id"], "INSTALLATION", "2026-07-20"
            ),
            TRAINING_ADMIN,
        )
        validate_error(
            rejected, E.ERR_TECHNICIAN_DISTRIBUTOR_MISMATCH, expected_status=422
        )

        unchanged = validate_success(
            api.get_distributor(distributor["id"], CHANNEL_MANAGER), expected_status=200
        )
        assert unchanged["completed_training_keys"] == []
        assert unchanged["trained_technician_count"] == 0
        assert unchanged["installation_training_state"] == "NOT_STARTED"
        assert unchanged["distributor_state"] == "PENDING_TRAINING"


class TestWarrantyClaimCoverability:
    """Coverability is checked at approval, not when the claim is filed."""

    def test_01_claim_beyond_warranty_months_not_coverable_rejected(
        self, api, warranty_environment
    ):
        """A bearing that failed forty months into a thirty-six month term cannot
        be approved even though its cycle count is far inside the adjusted life.

        PRD: "The claim must be coverable: `in_service_months` must not exceed the part's `warranty_months`, and `failure_cycle_count` must not exceed the computed `effective_rated_cycles`; a failure outside either bound is `ERR_CLAIM_NOT_COVERABLE`."
        Design: Corner/validations/claim_beyond_warranty_months_not_coverable_rejected
        """
        env = warranty_environment
        claim = fx.make_submitted_claim(
            api,
            env,
            failure_cycle_count=1000,
            in_service_months=40,
            duty_cycle_class="STANDARD",
            diagnostics_code="BRG-NOISE",
        )
        assert claim["claim_state"] == "SUBMITTED"
        assert claim["effective_rated_cycles"] == 30000

        part_version = fx.read_part_version(api, env["part"]["id"])
        rejected = api.adjudicate_warranty_claim(
            claim["id"],
            f.adjudicate_payload(part_version, "APPROVE"),
            WARRANTY_ANALYST,
        )
        validate_error(rejected, E.ERR_CLAIM_NOT_COVERABLE, expected_status=422)

        unchanged_claim = validate_success(
            api.get_warranty_claim(claim["id"], WARRANTY_ANALYST), expected_status=200
        )
        assert unchanged_claim["claim_state"] == "SUBMITTED"
        assert unchanged_claim["coverage_variant"] == "NONE"
        assert unchanged_claim["covered_amount_cents"] == 0

        unchanged_part = validate_success(
            api.get_service_part(env["part"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        assert unchanged_part["on_hand_qty"] == 3
        assert unchanged_part["reserved_qty"] == 0
        assert unchanged_part["version"] == part_version

        distributor = validate_success(
            api.get_distributor(env["distributor"]["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        assert distributor["warranty_credit_cents"] == 0
        assert distributor["open_claim_count"] == 1

        # The submitted row survives the refused approval and can still be denied.
        denied = validate_success(
            api.adjudicate_warranty_claim(
                claim["id"],
                f.adjudicate_payload(
                    part_version, "DENY", denial_reason="OUT_OF_WARRANTY"
                ),
                WARRANTY_ANALYST,
            ),
            expected_status=200,
        )
        assert denied["claim_state"] == "DENIED"


class TestBearingPreloadMeasurement:
    """The preload acceptance window and the conditional measurement field."""

    def test_01_bearing_preload_at_lower_bound_accepted(self, api):
        """A preload measured at exactly the lower edge of the AISI_304 window is
        accepted and carries the unit on to its final inspection queue.

        PRD: "For a drum of `AISI_304`, the measured `bearing_preload_micron` must fall between `18.00` and `32.00` inclusive."
        Design: Corner/validations/bearing_preload_at_lower_bound_accepted
        """
        env = _unit_at_drum_done(api)

        log = validate_success(
            api.create_station_log(
                env["build"]["id"],
                f.station_log_payload(
                    env["bearing_cell"]["id"],
                    "BEARING_INSTALL",
                    BEARING_START,
                    BEARING_END,
                    "PASS",
                    bearing_preload_micron=LOWER_BOUND_PRELOAD_304,
                ),
                make_technician_headers(env["technician"]["id"]),
            ),
            expected_status=201,
        )
        assert float(log["bearing_preload_micron"]) == pytest.approx(18.00, abs=0.01)
        assert _instant(log["occupation_to"]) == _instant(BEARING_OCCUPATION_TO)

        build = validate_success(
            api.get_build_order(env["build"]["id"], PLANT_MANAGER), expected_status=200
        )
        assert build["build_state"] == "BEARINGS_DONE"
        assert build["station_pass_count"] == 2
        assert build["labor_minutes_total"] == 120

    def test_02_bearing_install_without_preload_rejected(self, api):
        """A bearing-installation log that carries no measurement at all is
        refused, and the unit keeps waiting for its bearing operation.

        PRD: "`bearing_preload_micron` is required when the `station_type` is `BEARING_INSTALL` and must be null for every other station type, and it carries exactly two decimal places."
        Design: Corner/validations/bearing_install_without_preload_rejected
        """
        env = _unit_at_drum_done(api)

        rejected = api.create_station_log(
            env["build"]["id"],
            f.station_log_payload(
                env["bearing_cell"]["id"],
                "BEARING_INSTALL",
                BEARING_START,
                BEARING_END,
                "PASS",
            ),
            make_technician_headers(env["technician"]["id"]),
        )
        # The omission breaks the conditionally required field and the preload
        # window rule at once, and the PRD attaches an error id to each.
        error_id = validate_error_is_one_of(
            rejected, [E.ERR_INVALID_REQUEST, E.ERR_PRELOAD_OUT_OF_SPEC]
        )
        assert rejected.status_code == E.ERROR_HTTP_STATUS[error_id]

        build = validate_success(
            api.get_build_order(env["build"]["id"], PLANT_MANAGER), expected_status=200
        )
        assert build["build_state"] == "DRUM_DONE"
        assert build["station_pass_count"] == 1

        logs = validate_success(
            api.list_station_logs(PLANT_MANAGER, build_order_id=env["build"]["id"]),
            expected_status=200,
        )
        assert len(logs) == 1, logs


class TestQuoteOwnershipScope:
    """A distributor is scoped to its own quotes."""

    def test_01_distributor_reading_another_distributors_quote_rejected(self, api):
        """One distributor reading another's package quote is refused as an
        ownership violation, while the owning distributor reads it fine.

        PRD: "A `Distributor` that addresses a package quote or a warranty claim whose distributor reference is not its own `X-User-ID`, or that submits a creation body naming a different distributor, is rejected with `ERR_OWNERSHIP_VIOLATION` and HTTP 403."
        Design: Corner/validations/distributor_reading_another_distributors_quote_rejected
        """
        owner = fx.make_distributor(api)
        outsider = fx.make_distributor(
            api,
            distributor_code="D-02",
            legal_name="Gulf Coin Laundry",
            territory_code="TX-NORTH",
            territory_exclusive=True,
        )
        owner_headers = make_distributor_headers(owner["id"])
        outsider_headers = make_distributor_headers(outsider["id"])
        quote = validate_success(
            api.create_quote(
                f.quote_payload(owner["id"], financing_program="NONE"), owner_headers
            ),
            expected_status=201,
        )

        rejected = api.get_quote(quote["id"], outsider_headers)
        validate_error(rejected, E.ERR_OWNERSHIP_VIOLATION, expected_status=403)

        own_read = validate_success(
            api.get_quote(quote["id"], owner_headers), expected_status=200
        )
        assert own_read["id"] == quote["id"]

        channel_view = validate_success(
            api.list_quotes(CHANNEL_MANAGER), expected_status=200
        )
        assert len(channel_view) == 1, channel_view
