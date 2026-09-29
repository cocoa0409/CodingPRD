"""Who may do what on the shop floor, and the credential check that runs first.

The plant recognises six capacities, and each endpoint publishes the list of
capacities authorised to call it: a master-data administrator registers reference
data but never operates the process, a shipping clerk's writes stop at the loading
dock, the two quality capacities are peers that share only a drafting verb and a
hold verb, and the furnace is booked by one capacity but run by another. Ahead of
all of that sits the credential check on the two operator headers, which refuses a
missing or unrecognised capacity before any authorisation, state or existence rule
is consulted. Every capacity may read every resource, and an operator identifier is
opaque everywhere except the segregation-of-duties comparison.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_furnace_payload,
    create_heading_tool_payload,
    create_part_spec_payload,
    create_steel_heat_payload,
    create_wire_lot_payload,
    fixtures,
    headers_without_role,
    headers_without_user_id,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)

ROLE_NOT_PERMITTED = ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
UNAUTHENTICATED = ApiErrorId.ERR_UNAUTHENTICATED.value


# ---------------------------------------------------------------------------
# Shared local setup (inlined rather than added to the shared helpers)
# ---------------------------------------------------------------------------
def _setup_setup_lot(lot_code):
    """An unplated part's lot sitting in SETUP with released wire and a mounted die."""
    return fixtures.setup_lot_in_setup(
        unplated=True, lot_overrides={"lot_code": lot_code}
    )


# ---------------------------------------------------------------------------
# PlantAdmin: registers master data, operates nothing
# ---------------------------------------------------------------------------
PLANT_ADMIN_FORBIDDEN = [
    (
        "release_wire_lot",
        lambda api, env, h: api.release_wire_lot(env["wire"]["id"], h),
    ),
    (
        "mount_die_set",
        lambda api, env, h: api.mount_heading_tool(
            env["tool"]["id"], {"press_code": "PRESS-4"}, h
        ),
    ),
    (
        "complete_heading",
        lambda api, env, h: api.complete_heading(
            env["lot"]["id"], {"headed_count": 4900, "heading_scrap_count": 60}, h
        ),
    ),
    (
        "open_lot_test",
        lambda api, env, h: api.create_lot_test(
            {"production_lot_id": env["lot"]["id"]}, h
        ),
    ),
    (
        "place_hold",
        lambda api, env, h: api.hold_production_lot(
            env["lot"]["id"], {"reason": "ADMIN_CURIOSITY"}, h
        ),
    ),
]


class TestPlantAdminBoundary:
    """A master-data administrator registers and reads, and does nothing else."""

    def test_plant_admin_registers_and_revises_every_kind_of_reference_data(
        self, api, admin_headers
    ):
        """A PlantAdmin may register a part spec, revise it, and register a heat, a wire lot, a die set and a furnace.

        PRD: "A `PlantAdmin` is a master-data administrator: it may register reference data (part specifications and their revisions, steel heats, wire lots, die sets, furnaces) but may not operate the process, test, certify or ship."

        PRD: "Specifications may be revised later by a `ProcessEngineer` or a `PlantAdmin`, and a revision may touch `min_core_hardness_hv`, `max_core_hardness_hv`, `max_decarb_depth_mm`, `nominal_pack_count`, `count_tolerance_pct`, `plating_spec` and `proof_load_kn`, each optional."

        Design: Corner/rbac/plant_admin_registers_master_data_but_cannot_operate_the_process
        """
        validate_success(api.set_clock("2026-09-01T06:00:00Z", admin_headers))

        spec = validate_success(
            api.create_part_spec(
                create_part_spec_payload(
                    part_number="NP-M8-088",
                    plating_spec="NONE",
                    max_decarb_depth_mm=0.100,
                    pieces_per_kg=62.5,
                ),
                admin_headers,
            ),
            201,
        )
        assert spec["version"] == 1, f"A fresh part spec starts at version 1, got {spec['version']}"

        revised = validate_success(
            api.revise_part_spec(spec["id"], {"proof_load_kn": 35.0}, admin_headers)
        )
        assert revised["version"] == 2, (
            f"A PlantAdmin revision increments the spec version to 2, got {revised['version']}"
        )
        assert revised["proof_load_kn"] == pytest.approx(35.0, abs=0.001), (
            f"Expected proof_load_kn 35.0 after the PlantAdmin revision, got {revised['proof_load_kn']}"
        )

        heat = validate_success(
            api.create_steel_heat(create_steel_heat_payload(), admin_headers), 201
        )
        wire = validate_success(
            api.create_wire_lot(create_wire_lot_payload(heat["id"]), admin_headers), 201
        )
        tool = validate_success(
            api.create_heading_tool(create_heading_tool_payload(), admin_headers), 201
        )
        furnace = validate_success(
            api.create_furnace(create_furnace_payload(), admin_headers), 201
        )

        for label, entity in (
            ("steel heat", heat),
            ("wire lot", wire),
            ("die set", tool),
            ("furnace", furnace),
        ):
            assert entity["id"], f"The PlantAdmin registration of the {label} returned no id"

        assert validate_success(api.get_steel_heat(heat["id"], admin_headers))["id"] == heat["id"]
        assert validate_success(api.get_wire_lot(wire["id"], admin_headers))["id"] == wire["id"]
        assert validate_success(api.get_heading_tool(tool["id"], admin_headers))["id"] == tool["id"]
        assert validate_success(api.get_furnace(furnace["id"], admin_headers))["id"] == furnace["id"]

    @pytest.mark.parametrize(
        "attempt", [pair[1] for pair in PLANT_ADMIN_FORBIDDEN],
        ids=[pair[0] for pair in PLANT_ADMIN_FORBIDDEN],
    )
    def test_plant_admin_cannot_operate_the_process(self, api, admin_headers, attempt):
        """Wire release, die mounting, heading completion, destructive testing and holding all refuse a PlantAdmin.

        PRD: "A `PlantAdmin` is a master-data administrator: it may register reference data (part specifications and their revisions, steel heats, wire lots, die sets, furnaces) but may not operate the process, test, certify or ship."

        PRD: "When both headers are well formed but the declared role is not listed as authorised for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/plant_admin_registers_master_data_but_cannot_operate_the_process
        """
        env = _setup_setup_lot("L-RB01")

        validate_error(attempt(api, env, admin_headers), ROLE_NOT_PERMITTED)

        lot = validate_success(api.get_production_lot(env["lot"]["id"], admin_headers))
        assert lot["process_state"] == "SETUP", (
            f"Expected process_state SETUP after the refused PlantAdmin call, got {lot['process_state']}"
        )
        assert lot["disposition"] == "IN_PROCESS", (
            f"Expected disposition IN_PROCESS after the refused PlantAdmin call, got {lot['disposition']}"
        )
        assert lot["available_count"] == 0, (
            f"Expected available_count 0 on an untouched SETUP lot, got {lot['available_count']}"
        )
        assert lot["version"] == 1, (
            f"A refused call must not mutate the lot, so version stays 1, got {lot['version']}"
        )

        wire = validate_success(api.get_wire_lot(env["wire"]["id"], admin_headers))
        assert wire["status"] == "RELEASED", (
            f"Expected the wire lot still RELEASED, got {wire['status']}"
        )
        tool = validate_success(api.get_heading_tool(env["tool"]["id"], admin_headers))
        assert tool["mounted_press_code"] == "PRESS-3", (
            f"Expected the die set still mounted on PRESS-3, got {tool['mounted_press_code']}"
        )

    def test_plant_admin_lot_test_refusal_is_the_role_error_not_the_lot_state_error(
        self, api, admin_headers, inspector_headers
    ):
        """A PlantAdmin opening a test on a SETUP lot is refused for its role, while an inspector reaches the state gate.

        PRD: "When both headers are well formed but the declared role is not listed as authorised for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        PRD: "Rules are evaluated in a strict ascending ladder."

        PRD: "Anything else is refused with `ERR_INVALID_LOT_STATE`."

        Design: Corner/rbac/plant_admin_registers_master_data_but_cannot_operate_the_process
        """
        env = _setup_setup_lot("L-RB01")
        payload = {"production_lot_id": env["lot"]["id"]}

        admin_error = validate_error(
            api.create_lot_test(payload, admin_headers), ROLE_NOT_PERMITTED
        )
        assert admin_error["error_id"] == ROLE_NOT_PERMITTED, (
            f"A SETUP lot could never be tested, yet the role refusal must win: got {admin_error['error_id']}"
        )

        validate_error(
            api.create_lot_test(payload, inspector_headers),
            ApiErrorId.ERR_INVALID_LOT_STATE.value,
        )

    def test_plant_admin_may_read_every_resource(self, api, admin_headers):
        """Every read endpoint answers a PlantAdmin, even though it may operate nothing.

        PRD: "Every role may read every resource through the read endpoints, and every role may drive the logical clock."

        Design: Corner/rbac/plant_admin_registers_master_data_but_cannot_operate_the_process
        """
        env = _setup_setup_lot("L-RB01")

        lot = validate_success(api.get_production_lot(env["lot"]["id"], admin_headers))
        assert lot["id"] == env["lot"]["id"], (
            f"Expected the lot {env['lot']['id']} back from the PlantAdmin read, got {lot['id']}"
        )
        validate_success(api.get_part_spec(env["spec"]["id"], admin_headers))
        validate_success(api.get_wire_lot(env["wire"]["id"], admin_headers))
        validate_success(api.get_heading_tool(env["tool"]["id"], admin_headers))
        validate_success(api.get_furnace(env["furnace"]["id"], admin_headers))
        validate_success(api.get_lot_traceability(env["lot"]["id"], admin_headers))


# ---------------------------------------------------------------------------
# ShippingClerk: writes stop at the loading dock
# ---------------------------------------------------------------------------
SHIPPING_CLERK_FORBIDDEN = [
    (
        "complete_heading",
        lambda api, env, h: api.complete_heading(
            env["lot"]["id"], {"headed_count": 4900, "heading_scrap_count": 60}, h
        ),
    ),
    (
        "open_lot_test",
        lambda api, env, h: api.create_lot_test(
            {"production_lot_id": env["lot"]["id"]}, h
        ),
    ),
    (
        "draft_certificate",
        lambda api, env, h: api.create_certification_document(
            {
                "production_lot_id": env["lot"]["id"],
                "lot_test_id": env["lot"]["id"],
                "cert_serial": "CERT-RB02",
                "expected_production_lot_version": env["lot"]["version"],
            },
            h,
        ),
    ),
    (
        "mount_die_set",
        lambda api, env, h: api.mount_heading_tool(
            env["tool"]["id"], {"press_code": "PRESS-8"}, h
        ),
    ),
    (
        "queue_secondary_operation",
        lambda api, env, h: api.queue_secondary_operation(
            env["lot"]["id"],
            {"op_type": "THREAD_ROLL", "sequence_no": 1, "machine_code": "TR-1"},
            h,
        ),
    ),
]


class TestShippingClerkBoundary:
    """The clerk owns the dock; heading, testing, certifying and tooling are closed to it."""

    @pytest.mark.parametrize(
        "attempt", [pair[1] for pair in SHIPPING_CLERK_FORBIDDEN],
        ids=[pair[0] for pair in SHIPPING_CLERK_FORBIDDEN],
    )
    def test_shipping_clerk_cannot_head_test_or_certify_a_lot(
        self, api, clerk_headers, attempt
    ):
        """Heading completion, destructive testing, certificate drafting, die mounting and op queueing all refuse a clerk.

        PRD: "A `ShippingClerk` owns packaging and shipment."

        PRD: "When both headers are well formed but the declared role is not listed as authorised for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/shipping_clerk_cannot_head_test_or_certify_a_lot
        """
        env = _setup_setup_lot("L-RB02")

        validate_error(attempt(api, env, clerk_headers), ROLE_NOT_PERMITTED)

    def test_clerk_certificate_draft_is_refused_before_the_cited_test_is_resolved(
        self, api, clerk_headers, inspector_headers
    ):
        """The clerk's draft is a role refusal even though its lot_test_id names no lot test at all.

        PRD: "When both headers are well formed but the declared role is not listed as authorised for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        PRD: "Foreign keys supplied inside a request body are resolved after all path identifiers, and among themselves in the order in which the fields appear in the endpoint's declared input list."

        PRD: "5. **Body foreign-key existence**, in input-field order, yielding `ERR_PART_SPEC_NOT_FOUND`, `ERR_STEEL_HEAT_NOT_FOUND`, `ERR_WIRE_LOT_NOT_FOUND`, `ERR_HEADING_TOOL_NOT_FOUND`, `ERR_FURNACE_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`, `ERR_LOT_TEST_NOT_FOUND` or `ERR_CERT_DOCUMENT_NOT_FOUND`."

        Design: Corner/rbac/shipping_clerk_cannot_head_test_or_certify_a_lot
        """
        env = _setup_setup_lot("L-RB02")
        lot_id = env["lot"]["id"]
        body = {
            "production_lot_id": lot_id,
            "lot_test_id": lot_id,
            "cert_serial": "CERT-RB02",
            "expected_production_lot_version": env["lot"]["version"],
        }

        clerk_error = validate_error(
            api.create_certification_document(body, clerk_headers), ROLE_NOT_PERMITTED
        )
        assert clerk_error["error_id"] == ROLE_NOT_PERMITTED, (
            "The check is on the acting role, never on the target: expected "
            f"{ROLE_NOT_PERMITTED}, got {clerk_error['error_id']}"
        )

        body_again = dict(body, cert_serial="CERT-RB02B")
        validate_error(
            api.create_certification_document(body_again, inspector_headers),
            ApiErrorId.ERR_LOT_TEST_NOT_FOUND.value,
        )

    def test_clerk_refusals_leave_the_lot_and_the_die_set_untouched(
        self, api, clerk_headers
    ):
        """After five refused clerk writes the lot is still in SETUP at version 1 and the die is still on its press.

        PRD: "A `ShippingClerk` owns packaging and shipment."

        PRD: "When both headers are well formed but the declared role is not listed as authorised for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/shipping_clerk_cannot_head_test_or_certify_a_lot
        """
        env = _setup_setup_lot("L-RB02")

        for _label, attempt in SHIPPING_CLERK_FORBIDDEN:
            validate_error(attempt(api, env, clerk_headers), ROLE_NOT_PERMITTED)

        lot = validate_success(api.get_production_lot(env["lot"]["id"], clerk_headers))
        assert lot["process_state"] == "SETUP", (
            f"Expected process_state SETUP after the clerk's refused writes, got {lot['process_state']}"
        )
        assert lot["version"] == 1, (
            f"Expected the lot still at version 1 after five refusals, got {lot['version']}"
        )
        assert lot["headed_count"] == 0, (
            f"Expected headed_count 0 after the refused heading report, got {lot['headed_count']}"
        )

        tool = validate_success(api.get_heading_tool(env["tool"]["id"], clerk_headers))
        assert tool["mounted_press_code"] == "PRESS-3", (
            f"Expected mounted_press_code still PRESS-3, got {tool['mounted_press_code']}"
        )
        assert tool["status"] == "MOUNTED", (
            f"Expected the die set still MOUNTED, got {tool['status']}"
        )


# ---------------------------------------------------------------------------
# The two quality capacities: peers with two shared verbs
# ---------------------------------------------------------------------------
INSPECTOR_FORBIDDEN_CERT_VERBS = [
    ("issue", lambda api, cert_id, h: api.issue_certification_document(cert_id, h)),
    (
        "revoke",
        lambda api, cert_id, h: api.revoke_certification_document(
            cert_id, {"reason": "INSPECTOR_SECOND_THOUGHTS"}, h
        ),
    ),
]

MANAGER_FORBIDDEN_INSPECTION_VERBS = [
    (
        "open_lot_test",
        lambda api, env, h: api.create_lot_test(
            {"production_lot_id": env["lot"]["id"]}, h
        ),
    ),
    (
        "verify_mill_cert",
        lambda api, env, h: api.verify_mill_cert(
            env["second_heat"]["id"],
            {
                "outcome": "VERIFIED",
                "mill_cert_serial": "MC-2026-000482",
                "lab_report_reference": "LAB-0002",
            },
            h,
        ),
    ),
    (
        "release_wire_lot",
        lambda api, env, h: api.release_wire_lot(env["second_wire"]["id"], h),
    ),
]


def _add_second_material(api, inspector_headers, engineer_headers, env):
    """An unverified heat and its unreleased wire lot, for the manager's refused verbs."""
    heat = validate_success(
        api.create_steel_heat(
            create_steel_heat_payload(
                heat_number="H-77411",
                mill_cert_serial="MC-2026-000482",
                gross_mass_kg=200.0,
            ),
            inspector_headers,
        ),
        201,
    )
    wire = validate_success(
        api.create_wire_lot(
            create_wire_lot_payload(heat["id"], gross_mass_kg=200.0), engineer_headers
        ),
        201,
    )
    env["second_heat"] = heat
    env["second_wire"] = wire
    return env


class TestQualityRoleSplit:
    """Drafting and holding are shared; signing, withdrawing, testing and releasing wire are not."""

    def test_both_quality_roles_may_draft_a_certificate(
        self, api, manager_headers, inspector_headers
    ):
        """A manager's draft and an inspector's draft both succeed on the same accepted lot.

        PRD: "A certificate of conformance may be drafted by a `QualityInspector` or a `QualityManager`, citing the `production_lot_id` being certified and the `lot_test_id` whose evidence it rests on, printing a plant-unique `cert_serial`, and carrying the `expected_production_lot_version` of §2.7."

        Design: Corner/rbac/inspector_cannot_sign_and_manager_cannot_test
        """
        env = fixtures.setup_tested_lot(unplated=True)
        lot_id = env["lot"]["id"]
        test_id = env["lot_test"]["id"]

        by_manager = validate_success(
            api.create_certification_document(
                {
                    "production_lot_id": lot_id,
                    "lot_test_id": test_id,
                    "cert_serial": "CERT-RB03",
                    "expected_production_lot_version": fixtures.lot_version(lot_id),
                },
                manager_headers,
            ),
            201,
        )
        assert by_manager["status"] == "DRAFT", (
            f"A fresh draft starts in DRAFT, got {by_manager['status']}"
        )
        assert by_manager["revision"] == 1, (
            f"A fresh draft starts at revision 1, got {by_manager['revision']}"
        )
        assert by_manager["signed_by_user_id"] in (None, ""), (
            f"A draft carries no signer yet, got {by_manager['signed_by_user_id']}"
        )

        by_inspector = validate_success(
            api.create_certification_document(
                {
                    "production_lot_id": lot_id,
                    "lot_test_id": test_id,
                    "cert_serial": "CERT-RB03B",
                    "expected_production_lot_version": fixtures.lot_version(lot_id),
                },
                inspector_headers,
            ),
            201,
        )
        assert by_inspector["status"] == "DRAFT", (
            f"The inspector's draft is equally legal and starts DRAFT, got {by_inspector['status']}"
        )

    @pytest.mark.parametrize(
        "attempt", [pair[1] for pair in INSPECTOR_FORBIDDEN_CERT_VERBS],
        ids=[pair[0] for pair in INSPECTOR_FORBIDDEN_CERT_VERBS],
    )
    def test_an_inspector_cannot_sign_or_withdraw_a_certificate(
        self, api, inspector_alt_headers, manager_headers, attempt
    ):
        """Issue and revoke refuse a QualityInspector, and the certificate stays an unsigned DRAFT.

        PRD: "Signing is exclusively a `QualityManager` act, and it is where segregation of duties bites: the acting `X-User-ID` must differ from the `performed_by_user_id` of the cited test, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

        PRD: "Withdrawal is also a `QualityManager` act."

        Design: Corner/rbac/inspector_cannot_sign_and_manager_cannot_test
        """
        env = fixtures.setup_drafted_certificate(
            unplated=True, cert_serial="CERT-RB03", drafter_headers=manager_headers
        )
        cert_id = env["certificate"]["id"]

        error = validate_error(
            attempt(api, cert_id, inspector_alt_headers), ROLE_NOT_PERMITTED
        )
        assert error["error_id"] == ROLE_NOT_PERMITTED, (
            f"An inspector's certificate-lifecycle attempt is a role refusal, got {error['error_id']}"
        )

        cert = validate_success(
            api.get_certification_document(cert_id, inspector_alt_headers)
        )
        assert cert["status"] == "DRAFT", (
            f"Expected the certificate still DRAFT after the refusal, got {cert['status']}"
        )
        assert cert["signed_by_user_id"] in (None, ""), (
            f"Expected signed_by_user_id still empty, got {cert['signed_by_user_id']}"
        )

    @pytest.mark.parametrize(
        "attempt", [pair[1] for pair in MANAGER_FORBIDDEN_INSPECTION_VERBS],
        ids=[pair[0] for pair in MANAGER_FORBIDDEN_INSPECTION_VERBS],
    )
    def test_a_manager_cannot_test_verify_a_heat_or_release_wire(
        self, api, manager_headers, inspector_headers, engineer_headers, attempt
    ):
        """Destructive testing, mill-certificate adjudication and wire release all refuse a QualityManager.

        PRD: "Only a `QualityInspector` may open a destructive lot test, and the payload names nothing but the `production_lot_id`."

        PRD: "A `QualityInspector` adjudicates the paperwork by submitting an `outcome` of either `VERIFIED` or `REJECTED`, along with the `mill_cert_serial` being attested and a `lab_report_reference` naming the independent laboratory report relied on."

        PRD: "Only a `QualityInspector` can put wire on the heading floor, and three gates stand in the way of the `DRAWN → RELEASED` transition."

        Design: Corner/rbac/inspector_cannot_sign_and_manager_cannot_test
        """
        env = fixtures.setup_tested_lot(unplated=True)
        _add_second_material(api, inspector_headers, engineer_headers, env)

        validate_error(attempt(api, env, manager_headers), ROLE_NOT_PERMITTED)

        heat = validate_success(
            api.get_steel_heat(env["second_heat"]["id"], manager_headers)
        )
        assert heat["cert_status"] == "PENDING", (
            f"Expected the second heat still PENDING after the manager's refusal, got {heat['cert_status']}"
        )
        wire = validate_success(
            api.get_wire_lot(env["second_wire"]["id"], manager_headers)
        )
        assert wire["status"] == "DRAWN", (
            f"Expected the second wire lot still DRAWN after the manager's refusal, got {wire['status']}"
        )

    def test_a_hold_is_shared_but_only_a_manager_releases_it(
        self, api, inspector_alt_headers, manager_headers
    ):
        """An inspector may place the hold and cannot lift it; the manager lifts it.

        PRD: "A `QualityInspector` or `QualityManager` may place a hold with a `reason` on any lot whose `disposition` is `IN_PROCESS`, taking it `IN_PROCESS → HOLD` with `hold_source` of `QUALITY` and incrementing its `version` by 1."

        PRD: "Only a `QualityManager` releases a hold, optionally recording a `note`; the lot must be in `disposition` `HOLD`, and when the hold carries `hold_source` of `HEAT_COUNTERFEIT` the release additionally requires that the lot's traceability heat now has `cert_status` of `VERIFIED`, or it is refused with `ERR_STEEL_HEAT_NOT_VERIFIED`."

        PRD: "A successful release takes the lot `HOLD → IN_PROCESS`, resets `hold_source` to `NONE`, and increments the `version` by 1."

        Design: Corner/rbac/inspector_cannot_sign_and_manager_cannot_test
        """
        env = fixtures.setup_tested_lot(unplated=True)
        lot_id = env["lot"]["id"]
        version_before = fixtures.lot_version(lot_id)

        held = validate_success(
            api.hold_production_lot(lot_id, {"reason": "PEER_REVIEW"}, inspector_alt_headers)
        )
        assert held["disposition"] == "HOLD", (
            f"An inspector's hold is a shared verb and must land: got disposition {held['disposition']}"
        )
        assert held["hold_source"] == "QUALITY", (
            f"An operator hold tags hold_source QUALITY, got {held['hold_source']}"
        )
        assert held["version"] == version_before + 1, (
            f"Expected version {version_before + 1} after the hold, got {held['version']}"
        )

        validate_error(
            api.release_hold(lot_id, {"note": "INSPECTOR_ATTEMPT"}, inspector_alt_headers),
            ROLE_NOT_PERMITTED,
        )
        still_held = validate_success(api.get_production_lot(lot_id, manager_headers))
        assert still_held["disposition"] == "HOLD", (
            f"Expected the lot still on hold after the inspector's refused release, got {still_held['disposition']}"
        )
        assert still_held["version"] == held["version"], (
            f"A refused release mutates nothing: expected version {held['version']}, got {still_held['version']}"
        )

        released = validate_success(
            api.release_hold(lot_id, {"note": "MANAGER_CLEARS"}, manager_headers)
        )
        assert released["disposition"] == "IN_PROCESS", (
            f"Expected disposition IN_PROCESS after the manager's release, got {released['disposition']}"
        )
        assert released["hold_source"] == "NONE", (
            f"Expected hold_source reset to NONE, got {released['hold_source']}"
        )


# ---------------------------------------------------------------------------
# Booking versus running: furnace and plating verbs
# ---------------------------------------------------------------------------
class TestFurnaceAndPlatingVerbSplit:
    """The engineer books the furnace and the plating line; the operator runs them."""

    def test_engineer_may_book_a_furnace_run_but_only_the_operator_starts_it(
        self, api, engineer_headers, heat_treat_headers
    ):
        """The engineer's booking is accepted and its start is refused; the operator's start runs the furnace.

        PRD: "A `HeatTreatOperator` or `ProcessEngineer` books a run against a `production_lot_id` and a `furnace_id`, declaring an inclusive `window_start_at` and an inclusive `window_end_at` (the end strictly after the start), together with the recipe: `austenitize_temp_c`, the `quench_medium` (`OIL`, `WATER` or `POLYMER`), `temper_temp_c`, `temper_time_min` (at least 1 minute of soak), and `carbon_potential_pct`, the furnace atmosphere's carbon potential."

        PRD: "Starting the run is exclusively a `HeatTreatOperator` action and takes the run `PLANNED → RUNNING`."

        PRD: "On success `started_at` is stamped from the logical clock, the furnace flips `IDLE → OCCUPIED`, and both the run's `version` and the furnace's `version` increment by 1."

        Design: Corner/rbac/furnace_and_plating_verbs_split_between_operator_and_engineer
        """
        env = fixtures.setup_secondary_done_lot(lot_overrides={"lot_code": "L-RB04"})
        run = validate_success(
            api.create_heat_treat_run(
                {
                    "production_lot_id": env["lot"]["id"],
                    "furnace_id": env["furnace"]["id"],
                    "window_start_at": "2026-09-01T18:00:00Z",
                    "window_end_at": "2026-09-01T23:00:00Z",
                    "austenitize_temp_c": 870.0,
                    "quench_medium": "OIL",
                    "temper_temp_c": 420.0,
                    "temper_time_min": 60,
                    "carbon_potential_pct": 0.42,
                },
                engineer_headers,
            ),
            201,
        )
        assert run["status"] == "PLANNED", (
            f"The engineer's booking is a shared verb and starts PLANNED, got {run['status']}"
        )
        fixtures.set_clock("2026-09-01T19:00:00Z", engineer_headers)

        validate_error(
            api.start_heat_treat_run(run["id"], engineer_headers), ROLE_NOT_PERMITTED
        )
        refused = validate_success(api.get_heat_treat_run(run["id"], engineer_headers))
        assert refused["status"] == "PLANNED", (
            f"Expected the run still PLANNED after the engineer's refused start, got {refused['status']}"
        )
        furnace = validate_success(api.get_furnace(env["furnace"]["id"], engineer_headers))
        assert furnace["status"] == "IDLE", (
            f"Expected the furnace still IDLE after the refused start, got {furnace['status']}"
        )

        started = validate_success(
            api.start_heat_treat_run(run["id"], heat_treat_headers)
        )
        assert started["status"] == "RUNNING", (
            f"Expected the operator's start to take the run RUNNING, got {started['status']}"
        )
        assert is_iso8601_timestamp(started["started_at"]), (
            f"started_at must be an ISO 8601 UTC instant, got {started['started_at']}"
        )
        assert started["started_at"].startswith("2026-09-01T19:00:00"), (
            f"Expected started_at stamped at 2026-09-01T19:00:00Z, got {started['started_at']}"
        )
        occupied = validate_success(
            api.get_furnace(env["furnace"]["id"], heat_treat_headers)
        )
        assert occupied["status"] == "OCCUPIED", (
            f"Expected the furnace OCCUPIED once the run started, got {occupied['status']}"
        )

    def test_only_an_inspector_records_heat_treatment_results(
        self, api, heat_treat_headers, inspector_headers
    ):
        """The operator who ran the furnace may not read out the coupon; the inspector may.

        PRD: "Results are recorded by a `QualityInspector` on a `RUNNING` run, supplying the coupon's `core_hardness_hv` and its measured `surface_decarb_depth_mm`."

        PRD: "Recording results always takes the run `RUNNING → COMPLETED` (a terminal status), stamps `completed_at` from the logical clock, returns the furnace to `IDLE`, and sets the furnace's `last_run_end_at` to the same instant."

        PRD: "On `PASS`, the lot's `heat_treat_completed` flag becomes true and the lot moves `SECONDARY_DONE → HEAT_TREATED`."

        Design: Corner/rbac/furnace_and_plating_verbs_split_between_operator_and_engineer
        """
        env = fixtures.setup_secondary_done_lot(lot_overrides={"lot_code": "L-RB04"})
        run = fixtures.book_heat_treat(env["lot"]["id"], env["furnace"]["id"])
        fixtures.start_heat_treat(run["id"], at="2026-09-01T19:00:00Z")
        fixtures.set_clock("2026-09-01T22:00:00Z", heat_treat_headers)

        results_body = {"core_hardness_hv": 330.0, "surface_decarb_depth_mm": 0.020}
        validate_error(
            api.record_heat_treat_results(run["id"], results_body, heat_treat_headers),
            ROLE_NOT_PERMITTED,
        )
        refused = validate_success(api.get_heat_treat_run(run["id"], heat_treat_headers))
        assert refused["status"] == "RUNNING", (
            f"Expected the run still RUNNING after the operator's refused read-out, got {refused['status']}"
        )
        assert refused["result"] == "PENDING", (
            f"Expected result still PENDING after the refusal, got {refused['result']}"
        )

        recorded = validate_success(
            api.record_heat_treat_results(run["id"], results_body, inspector_headers)
        )
        assert recorded["status"] == "COMPLETED", (
            f"Expected the run COMPLETED after the inspector's read-out, got {recorded['status']}"
        )
        assert recorded["result"] == "PASS", (
            f"Expected result PASS for hardness 330.0 inside the band, got {recorded['result']}"
        )
        assert recorded["total_decarb_depth_mm"] == pytest.approx(0.020, abs=0.001), (
            "A carbon potential of 0.42 leaves no deficit, so total_decarb_depth_mm stays 0.020, got "
            f"{recorded['total_decarb_depth_mm']}"
        )

        furnace = validate_success(
            api.get_furnace(env["furnace"]["id"], inspector_headers)
        )
        assert furnace["status"] == "IDLE", (
            f"Expected the furnace back to IDLE after the results, got {furnace['status']}"
        )
        lot = validate_success(api.get_production_lot(env["lot"]["id"], inspector_headers))
        assert lot["process_state"] == "HEAT_TREATED", (
            f"Expected the lot at HEAT_TREATED after a PASS, got {lot['process_state']}"
        )
        assert lot["heat_treat_completed"] is True, (
            f"Expected heat_treat_completed true after a PASS, got {lot['heat_treat_completed']}"
        )

    def test_engineer_may_schedule_plating_but_only_the_operator_completes_it(
        self, api, engineer_headers, heat_treat_headers
    ):
        """Scheduling the plating line is shared; marking plating complete is the operator's alone.

        PRD: "Plating is scheduled by a `HeatTreatOperator` or `ProcessEngineer` against a `production_lot_id`, and it may not begin before metallurgy has been proven: the lot's `heat_treat_completed` flag must be true both when the run is scheduled and when plating is completed, or the request is refused with `ERR_HEAT_TREAT_NOT_PASSED`."

        PRD: "Completing plating is a `HeatTreatOperator` action on a `SCHEDULED` run whose lot has `disposition` `IN_PROCESS`."

        PRD: "The run moves `SCHEDULED → PLATED` and stamps `plated_at` from the logical clock, which starts the embrittlement relief clock ticking."

        Design: Corner/rbac/furnace_and_plating_verbs_split_between_operator_and_engineer
        """
        env = fixtures.setup_heat_treated_lot(lot_overrides={"lot_code": "L-RB04"})
        lot_id = env["lot"]["id"]

        run = validate_success(
            api.create_plating_run(
                {
                    "production_lot_id": lot_id,
                    "plating_spec": "ZINC_CLEAR",
                    "load_mass_kg": 0.0,
                },
                engineer_headers,
            ),
            201,
        )
        assert run["status"] == "SCHEDULED", (
            f"The engineer's plating booking is shared and starts SCHEDULED, got {run['status']}"
        )
        assert run["plating_spec"] == "ZINC_CLEAR", (
            f"plating_spec is copied from the part specification, got {run['plating_spec']}"
        )
        assert run["load_mass_kg"] == pytest.approx(97.000, abs=0.001), (
            f"Expected load_mass_kg 97.000 for 4850 pieces at 20.0 g, got {run['load_mass_kg']}"
        )

        validate_error(
            api.complete_plating(run["id"], engineer_headers), ROLE_NOT_PERMITTED
        )
        lot_after_refusal = validate_success(
            api.get_production_lot(lot_id, engineer_headers)
        )
        assert lot_after_refusal["process_state"] == "HEAT_TREATED", (
            "A refused complete-plating leaves the lot at HEAT_TREATED, got "
            f"{lot_after_refusal['process_state']}"
        )

        plated = validate_success(api.complete_plating(run["id"], heat_treat_headers))
        assert plated["status"] == "PLATED", (
            f"Expected the operator's complete-plating to take the run PLATED, got {plated['status']}"
        )
        lot = validate_success(api.get_production_lot(lot_id, heat_treat_headers))
        assert lot["process_state"] == "PLATED", (
            f"Expected the lot at PLATED after plating completed, got {lot['process_state']}"
        )


# ---------------------------------------------------------------------------
# The credential check that runs before everything else
# ---------------------------------------------------------------------------
BAD_CREDENTIALS = [
    ("no_role_header", headers_without_role("admin-1")),
    ("no_user_id_header", headers_without_user_id("QualityInspector")),
    ("undeclared_role", build_user_headers("aud-1", "Auditor")),
]


class TestUnauthenticatedRequests:
    """The two operator headers are checked before authorisation, state or existence."""

    @pytest.mark.parametrize(
        "headers", [pair[1] for pair in BAD_CREDENTIALS],
        ids=[pair[0] for pair in BAD_CREDENTIALS],
    )
    def test_a_read_every_role_may_call_still_needs_both_headers(self, api, headers):
        """A missing role, a missing operator id and an undeclared role each answer 401 on a shared read.

        PRD: "Every request must carry two headers: `X-User-ID`, identifying the operator performing the action, and `X-User-Role`, declaring the capacity in which they act."

        PRD: "If either header is absent, or if `X-User-Role` is not one of the six roles the plant recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD: "Every role may read every resource through the read endpoints, and every role may drive the logical clock."

        Design: Corner/rbac/unauthenticated_requests_are_refused_before_any_role_check
        """
        env = _setup_setup_lot("L-RB05")

        error = validate_error(
            api.get_production_lot(env["lot"]["id"], headers), UNAUTHENTICATED
        )
        assert error["error_id"] == UNAUTHENTICATED, (
            "An unrecognised capacity fails authentication, not authorisation: expected "
            f"{UNAUTHENTICATED}, got {error['error_id']}"
        )
        assert error["error_id"] != ROLE_NOT_PERMITTED, (
            f"A role outside the declared six must not surface as {ROLE_NOT_PERMITTED}"
        )

    def test_missing_headers_are_refused_before_the_path_id_is_resolved(
        self, api, inspector_headers
    ):
        """A hold on an id that resolves to nothing answers 401, not the lot 404, and holds nothing.

        PRD: "If either header is absent, or if `X-User-Role` is not one of the six roles the plant recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD: "Rules are evaluated in a strict ascending ladder."

        PRD: "This ordering is normative — it is what makes an error response predictable when a request breaks several rules at once."

        Design: Corner/rbac/unauthenticated_requests_are_refused_before_any_role_check
        """
        env = _setup_setup_lot("L-RB05")
        anonymous = {"Content-Type": "application/json"}

        error = validate_error(
            api.hold_production_lot(
                NON_EXISTENT_UUID, {"reason": "ANONYMOUS_ATTEMPT"}, anonymous
            ),
            UNAUTHENTICATED,
        )
        assert error["error_id"] != ApiErrorId.ERR_PRODUCTION_LOT_NOT_FOUND.value, (
            "Authentication precedes path existence, so an unknown id must not surface as a 404: got "
            f"{error['error_id']}"
        )

        lot = validate_success(
            api.get_production_lot(env["lot"]["id"], inspector_headers)
        )
        assert lot["disposition"] == "IN_PROCESS", (
            f"No lot may be placed on hold by an unauthenticated request, got {lot['disposition']}"
        )
        assert lot["version"] == 1, (
            f"An unauthenticated request changes no entity version, got {lot['version']}"
        )
