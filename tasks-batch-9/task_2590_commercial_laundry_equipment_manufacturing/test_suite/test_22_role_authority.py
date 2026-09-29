"""Role authority and the two segregation-of-duties controls.

Each role owns a slice of the plant: the channel manager admits distributors, the
product engineer owns the catalogue, and the warranty analyst adjudicates claims.
A role acting outside its slice is refused before the request touches any data,
and two further controls refuse an operator who is authorized in general but too
close to the specific work being judged — the officer who prepared a dossier and
the technician who built a unit.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    DOSSIER_PREPARER,
    ENERGY_REVIEWER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    TRAINING_ADMIN,
    UID_ENERGY_REVIEWER,
    WARRANTY_ANALYST,
    make_distributor_headers,
    make_quality_inspector_headers,
)


class TestDistributorAdmissionAuthority:
    """Only the channel manager admits a distributor to the network."""

    def test_01_training_administrator_cannot_create_a_distributor(self, api):
        """The administrator who owns training records may not admit the
        distributor whose training they will later record, but may read the
        network the channel manager admits.

        PRD: "A `ChannelManager` creates a distributor with a `distributor_code`, a `legal_name`, an assigned `territory_code` and a boolean `territory_exclusive` flag that defaults to false."
        Design: Corner/rbac/distributor_creation_outside_channel_manager_rejected
        """
        rejected = api.create_distributor(f.distributor_payload(), TRAINING_ADMIN)
        validate_error(rejected, E.ERR_UNAUTHORIZED, expected_status=403)

        empty_network = validate_success(
            api.list_distributors(CHANNEL_MANAGER), expected_status=200
        )
        assert empty_network == [], f"A refused admission stored a row: {empty_network}"

        admitted = validate_success(
            api.create_distributor(f.distributor_payload(), CHANNEL_MANAGER),
            expected_status=201,
        )
        assert admitted["distributor_state"] == "PENDING_TRAINING"
        assert admitted["installation_training_state"] == "NOT_STARTED"
        assert admitted["trained_technician_count"] == 0
        assert admitted["version"] == 1

        # Reading the network is inside the training administrator's authority.
        readable = validate_success(
            api.list_distributors(TRAINING_ADMIN), expected_status=200
        )
        assert len(readable) == 1
        assert readable[0]["id"] == admitted["id"]


class TestCatalogueAuthority:
    """A distributor sells from the catalogue but never writes to it."""

    def test_01_distributor_cannot_register_a_machine_model(self, api):
        """A distributor holding a real network identity still may not register a
        machine model, though it may browse the catalogue it sells from.

        PRD: "`ProductEngineer` owns the product catalogue: machine models, service parts, and the manual release and suspension of a model."
        Design: Corner/rbac/machine_model_creation_by_distributor_rejected
        """
        distributor = fx.make_distributor(api)
        distributor_headers = make_distributor_headers(distributor["id"])

        rejected = api.create_machine_model(
            f.machine_model_payload(), distributor_headers
        )
        validate_error(rejected, E.ERR_UNAUTHORIZED, expected_status=403)

        browsed = validate_success(
            api.list_machine_models(distributor_headers), expected_status=200
        )
        assert browsed == [], f"A refused registration stored a row: {browsed}"

        registered = fx.make_model(api)
        browsed_again = validate_success(
            api.list_machine_models(distributor_headers), expected_status=200
        )
        assert len(browsed_again) == 1
        assert browsed_again[0]["id"] == registered["id"]


class TestClaimAdjudicationAuthority:
    """Adjudication belongs to the warranty analyst alone."""

    def test_01_product_engineer_cannot_adjudicate_a_claim(self, api, submitted_claim):
        """The engineer who owns the failing part may not decide the claim against
        it, and the refusal moves neither the claim nor the part.

        PRD: "`WarrantyAnalyst` adjudicates and voids warranty claims and reads per-model warranty exposure."
        Design: Corner/rbac/claim_adjudication_by_product_engineer_rejected
        """
        part_id = submitted_claim["part"]["id"]
        part_before = validate_success(
            api.get_service_part(part_id, PRODUCT_ENGINEER), expected_status=200
        )

        # Authorization is settled before the path identifier is even resolved,
        # so an unknown claim reports the role failure rather than a 404.
        validate_error(
            api.adjudicate_warranty_claim(
                NON_EXISTENT_UUID,
                f.adjudicate_payload(part_before["version"], "APPROVE"),
                PRODUCT_ENGINEER,
            ),
            E.ERR_UNAUTHORIZED,
            expected_status=403,
        )

        rejected = api.adjudicate_warranty_claim(
            submitted_claim["claim"]["id"],
            f.adjudicate_payload(part_before["version"], "APPROVE"),
            PRODUCT_ENGINEER,
        )
        validate_error(rejected, E.ERR_UNAUTHORIZED, expected_status=403)

        claim = validate_success(
            api.get_warranty_claim(submitted_claim["claim"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        assert claim["claim_state"] == "SUBMITTED"
        assert claim["adjudicated_by_user_id"] is None
        assert claim["covered_amount_cents"] == 0
        assert claim["coverage_variant"] == "NONE"

        part_after = validate_success(
            api.get_service_part(part_id, PRODUCT_ENGINEER), expected_status=200
        )
        assert part_after["version"] == part_before["version"]
        assert part_after["on_hand_qty"] == part_before["on_hand_qty"]


class TestDossierPreparerCannotReview:
    """Nobody reviews the measurements they submitted."""

    def test_01_preparer_reviewing_its_own_dossier_rejected(self, api):
        """The compliance officer whose identifier is stamped on the dossier is
        barred from deciding either dimension, while a second officer decides the
        energy dimension without difficulty.

        PRD: "The acting `X-User-ID` must differ from `prepared_by_user_id`, and it must differ from the reviewer identifier already recorded on the other dimension whenever that identifier is set; either failure is `ERR_SEGREGATION_OF_DUTIES`."
        Design: Corner/rbac/dossier_review_by_its_own_preparer_rejected
        """
        model = fx.make_model(api)
        dossier = fx.make_dossier(api, model["id"])

        rejected = api.create_dossier_review(
            dossier["id"], f.review_payload("ENERGY", "APPROVE"), DOSSIER_PREPARER
        )
        validate_error(rejected, E.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        untouched = validate_success(
            api.get_certification_dossier(dossier["id"], DOSSIER_PREPARER),
            expected_status=200,
        )
        assert untouched["dossier_state"] == "IN_REVIEW"
        assert untouched["energy_review_state"] == "PENDING"
        assert untouched["water_review_state"] == "PENDING"
        assert untouched["energy_reviewer_user_id"] is None
        assert untouched["version"] == 1

        # A different officer is exactly what the control asks for.
        reviewed = validate_success(
            api.create_dossier_review(
                dossier["id"], f.review_payload("ENERGY", "APPROVE"), ENERGY_REVIEWER
            ),
            expected_status=200,
        )
        assert reviewed["energy_review_state"] == "APPROVED"
        assert reviewed["energy_reviewer_user_id"] == UID_ENERGY_REVIEWER
        assert reviewed["water_review_state"] == "PENDING"
        assert reviewed["dossier_state"] == "IN_REVIEW"
        assert reviewed["version"] == 2

        # One approved dimension is not a certification, so the model has not moved.
        parent = validate_success(
            api.get_machine_model(model["id"], PRODUCT_ENGINEER), expected_status=200
        )
        assert parent["certification_state"] == "DRAFT"


class TestInspectorCannotSignOffOwnWork:
    """Nobody inspects their own welds."""

    def test_01_signoff_by_a_technician_who_logged_the_unit_rejected(self, api):
        """A technician certified for QA sign-off who personally worked all three
        stations of the unit is refused, and an inspector who never touched it
        accepts the same unit.

        PRD: "And the inspector's own `X-User-ID` must not appear as `technician_id` on any station log of this unit, or the request is `ERR_SEGREGATION_OF_DUTIES` — nobody inspects their own welds."
        Design: Corner/rbac/qa_signoff_by_a_technician_who_logged_the_build_rejected
        """
        # The builder holds QA_SIGNOFF as well as the three floor scopes, so the
        # refusal cannot be a certification failure.
        env = fx.make_certified_model(api)
        env["stations"] = fx.make_three_stations(api)
        env["technician"] = fx.make_certified_technician(
            api,
            ["DRUM_FAB", "BEARING_INSTALL", "CONTROL_INTEGRATION", "QA_SIGNOFF"],
            employee_code="T-100",
            full_name="Ann Ito",
            employer="FACTORY",
        )
        unit = fx.make_unit_in_qa_hold(api, env)
        assert unit["build"]["build_state"] == "QA_HOLD"

        rejected = api.qa_signoff(
            unit["build"]["id"],
            f.qa_signoff_payload("APPROVE"),
            make_quality_inspector_headers(env["technician"]["id"]),
        )
        validate_error(rejected, E.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        held = validate_success(
            api.get_build_order(unit["build"]["id"], PLANT_MANAGER),
            expected_status=200,
        )
        assert held["build_state"] == "QA_HOLD"
        assert held["qa_inspector_user_id"] is None
        assert held["accepted_at"] is None

        # A second certified inspector never appears on the unit's logs.
        inspector = fx.make_qa_inspector(api)
        accepted = validate_success(
            api.qa_signoff(
                unit["build"]["id"],
                f.qa_signoff_payload("APPROVE"),
                make_quality_inspector_headers(inspector["id"]),
            ),
            expected_status=200,
        )
        assert accepted["build_state"] == "ACCEPTED"
        assert accepted["qa_inspector_user_id"] == inspector["id"]
        assert accepted["station_pass_count"] == 3
        assert accepted["labor_minutes_total"] == 180
        assert accepted["rework_count"] == 0
