"""Corner coverage: RBAC denials, OCC stale-version on order create, and
immediate consistency of computed money fields in the create response."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_program, create_patient, get_patient,
    api_client, make_admin_headers, make_nurse_headers,
    make_coordinator_headers, make_patient_headers,
    make_nephrologist_headers, TEST_USERS,
    create_program_payload, create_supply_order_payload,
    build_user_headers,
)


class TestRbacDenials:
    """Each role is denied another role's exclusive operation."""

    def test_patient_cannot_create_program(self, api):
        """PRD §2.1: "The API recognizes six roles: `Patient`, `HomeNurse`,
        `Nephrologist`, `SupplyCoordinator`, `BiomedTechnician`, and
        `ProgramAdmin`. Each endpoint admits a defined set of roles (see §4); a
        caller whose role is not admitted to an endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/patient_cannot_create_program
        """
        resp = api.create_program(
            create_program_payload(name="HD Program Z", supply_catalog=[]),
            build_user_headers("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                               "Patient"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_coordinator_cannot_register_machine(self, api):
        """PRD §2.1: "The API recognizes six roles: `Patient`, `HomeNurse`,
        `Nephrologist`, `SupplyCoordinator`, `BiomedTechnician`, and
        `ProgramAdmin`. Each endpoint admits a defined set of roles (see §4); a
        caller whose role is not admitted to an endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/coordinator_cannot_register_machine
        """
        program = create_program()
        resp = api.create_machine(
            {"program_id": program["id"], "serial_number": "SN-X",
             "model": "HomeX"},
            make_coordinator_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_admin_cannot_activate_patient(self, api):
        """PRD §2.1: "The API recognizes six roles: `Patient`, `HomeNurse`,
        `Nephrologist`, `SupplyCoordinator`, `BiomedTechnician`, and
        `ProgramAdmin`. Each endpoint admits a defined set of roles (see §4); a
        caller whose role is not admitted to an endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/admin_cannot_activate_patient
        """
        program = create_program()
        patient = create_patient(program["id"])
        resp = api.activate_patient(patient["id"],
                                    make_admin_headers("admin-1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_occ_order_create_stale_patient_version(api):
    """PRD §2.8: "Creating a monthly supply order (`POST /api/supply-orders`)
    requires the non-optional field `expected_patient_version`, carrying the
    client's last observed `version` of the target Patient. If the patient's
    current `version` has advanced beyond the supplied value, the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412). The check exists because
    order creation supersedes an existing `DRAFT` order for the same patient
    and month (§3.5), and a client holding an outdated patient view must not be
    allowed to supersede on that basis."
    PRD §2.8: "Note that the three guarded creations themselves advance the
    relevant parent `version` — creating an order or a plan increments the
    Patient's `version`, and assigning a machine increments the machine's
    `version` — so every successful supersede invalidates previously observed
    versions."

    Design: Corner/cross_cutting_layers/occ_order_create_stale_patient_version
    """
    program = create_program()
    patient = create_patient(program["id"])
    pat = patient["id"]
    stale_v = get_patient(pat)["version"]
    # The prescription PATCH bumps Patient.version.
    validate_success(api.patch_prescription(
        pat, {"prescription_units_per_treatment": 8},
        make_nephrologist_headers("nephro-1")))
    resp = api.create_supply_order(
        create_supply_order_payload(pat, "2026-05",
                                    [{"sku": "DIALYSATE_2L", "quantity": 2}],
                                    expected_patient_version=stale_v),
        make_patient_headers(pat))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    fresh_v = get_patient(pat)["version"]
    assert fresh_v == stale_v + 1, "PATCH advanced the patient version"
    created = validate_success(api.create_supply_order(
        create_supply_order_payload(pat, "2026-05",
                                    [{"sku": "DIALYSATE_2L", "quantity": 2}],
                                    expected_patient_version=fresh_v),
        make_patient_headers(pat)), 201)
    assert created["order_status"] == "DRAFT"
    assert get_patient(pat)["version"] == fresh_v + 1, (
        "the successful create increments the patient version again")


def test_immediate_consistency_money_visible_in_create_response(api):
    """PRD §3.5: "The order's money fields are computed on creation and
    recomputed on every line edit. `provisional_total_units` is the sum of the
    line quantities. `subtotal_cents` is each line's quantity multiplied by its
    catalog `unit_price_cents`, summed exactly. `handling_fee_cents` is a
    500-cent base plus a per-line charge: each line's quantity multiplied by
    its catalog `handling_rate_cents`, rounded half up to whole cents per line,
    and only then summed — the per-line rounding discipline of §2.9 is pinned,
    so two lines rated 10.5 and 12.5 cents contribute 11 and 13, never a
    rounded-down 23."

    Design: Corner/consistency_model/immediate_consistency_money_visible_in_create_response
    """
    program = create_program()
    patient = create_patient(program["id"])
    pat = patient["id"]
    pat_v = get_patient(pat)["version"]
    resp = api.create_supply_order(
        create_supply_order_payload(pat, "2026-05",
                                    [{"sku": "DIALYSATE_2L", "quantity": 2}],
                                    expected_patient_version=pat_v),
        make_patient_headers(pat))
    data = validate_success(resp, 201)
    assert data["subtotal_cents"] == 2400
    assert data["handling_fee_cents"] == 521, "500 + round_half_up(2 * 10.5)"
    assert data["discount_cents"] == 0
    assert data["grand_total_cents"] == 2921
