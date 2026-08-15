"""Bath lifecycle: quarantine gates, exhaustion, dump/renew cycle, abort semantics."""
from test_helpers import (
    ApiErrorId,
    CHEM,
    EHS,
    MGR,
    OP,
    abort_load_run,
    complete_load_run,
    create_compat_rule,
    create_customer,
    create_manifest,
    create_titrated_bath,
    get_bath,
    get_bath_version,
    get_manifest,
    get_success_data,
    get_work_order,
    prepare_work_order,
    route_work_order,
    setup_routed_order,
    start_load_run,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_ehs_officer_headers


def _make_exhausted_bath_with_waiting_order():
    """Bath capacity 100 Ah; a waiting order is routed; a driver order runs a 100 Ah
    load that exhausts the bath. Returns (bath, waiting_order, driver_order)."""
    customer = create_customer(company_name="Zeta Extrusions")
    create_compat_rule(alloy_code="AL6063", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    bath = create_titrated_bath(
        bath_code="ANO-6", routing_modes_supported=["BARREL"], amp_hour_capacity=100,
    )
    waiting = setup_routed_order(
        customer["id"], bath["id"], part_number="PN-600W",
        alloy_code="AL6063", part_count=10, surface_area_dm2_per_part=1.0,
        planned_duration_minutes=120, planned_current_density_a_dm2=0.5,
    )
    driver = setup_routed_order(
        customer["id"], bath["id"], part_number="PN-600Y",
        alloy_code="AL6063", part_count=10, surface_area_dm2_per_part=1.0,
        planned_duration_minutes=300, planned_current_density_a_dm2=2.0,
    )
    return bath, waiting, driver


def test_bath_exhaustion_at_exact_capacity_cascades_waiting_order():
    """PRD §3.3: "Exhaustion is automatic and inclusive: the moment a load completion
    makes `amp_hour_used` reach or exceed `amp_hour_capacity`, the bath transitions
    `ACTIVE` to `EXHAUSTED` and every `ROUTED` work order on it cascades to
    `ROUTE_HELD` within the same request (§3.5)."

    Design: Difficulty/non_linear_state_machine/bath_exhaust_dump_renew_cycle
    """
    bath, waiting, driver = _make_exhausted_bath_with_waiting_order()
    # 10 dm2 x 2.0 A/dm2 x 300 min / 60 = 100.0 Ah — exactly the 100 capacity.
    lr = start_load_run(driver["id"], bath_id=bath["id"],
                        duration_minutes=300, current_density_a_dm2=2.0)
    complete_load_run(lr["id"])
    detail = get_bath(bath["id"])
    assert detail["status"] == "EXHAUSTED"
    assert detail["amp_hour_used"] == 100.0
    assert get_work_order(waiting["id"])["status"] == "ROUTE_HELD"


def test_dump_writes_manifest_line_and_renew_restores_bath():
    """PRD §3.9: "The dump transitions the bath to `DUMPED`, creates a manifest line on
    that manifest with `waste_code` F006, `source_type` `BATH_DUMP`, the bath's
    `volume_liters` as its volume, and `origin_bath_id` pointing back at the bath; the
    manifest's `total_mass_kg` is recomputed and its `version` incremented, and the
    bath's `version` increments too, all atomically."
    PRD §3.9: "The renewal records a new BathTitration using the same equivalent-weight
    conversion as §3.2, sets the bath's `current_concentration_g_l` to the measured
    value, zeroes both `amp_hour_used` and `amp_hour_reserved`, clears
    `dose_verification_pending` and `quarantine_cause`, returns the bath to `ACTIVE`,
    increments its `version`, and cascades every work order `ROUTE_HELD` on the bath
    back to `ROUTED`."

    Design: Difficulty/non_linear_state_machine/bath_exhaust_dump_renew_cycle
    """
    bath, waiting, driver = _make_exhausted_bath_with_waiting_order()
    lr = start_load_run(driver["id"], bath_id=bath["id"],
                        duration_minutes=300, current_density_a_dm2=2.0)
    complete_load_run(lr["id"])
    assert get_bath(bath["id"])["status"] == "EXHAUSTED"
    manifest = create_manifest(creator_user_id="ehs-1", generator_epa_id="EPA-GEN-1")
    dumped = get_success_data(api_client.dump_bath(bath["id"], {"manifest_id": manifest["id"]}, MGR))
    assert dumped["status"] == "DUMPED"
    # 800 L x 1.2 kg/L = 960.0 kg on the manifest.
    m = get_manifest(manifest["id"])
    assert m["total_mass_kg"] == 960.0, (
        f"Manifest total: expected 960.0, got {m['total_mass_kg']}"
    )
    renewed = get_success_data(api_client.renew_bath(
        bath["id"],
        {"titrant_volume_ml": 50.0, "titrant_normality": 0.1, "sample_volume_ml": 49.0},
        MGR,
    ))
    assert renewed["status"] == "ACTIVE"
    assert renewed["amp_hour_used"] == 0
    assert renewed["current_concentration_g_l"] == 5.0
    assert get_work_order(waiting["id"])["status"] == "ROUTED"


def test_quarantine_state_gates():
    """PRD §3.3: "Releasing a quarantine — an `EHSOfficer` or `ShopManager` action —
    requires, in order of the validation cascade: the bath is `QUARANTINED` (else
    `ERR_BATH_NOT_QUARANTINED`)"
    PRD §3.3: "An `EHSOfficer` or `ShopManager` may manually quarantine an `ACTIVE`
    bath — any other status rejects with `ERR_BATH_NOT_ACTIVE`"

    Design: Corner/state_machines/bath_quarantine_state_gates
    """
    bath = create_titrated_bath(bath_code="ANO-Q", routing_modes_supported=["BARREL"])
    # Release from ACTIVE is rejected.
    resp_rel = api_client.release_quarantine(bath["id"], EHS)
    validate_error(resp_rel, ApiErrorId.ERR_BATH_NOT_QUARANTINED)
    # First quarantine succeeds.
    quarantined = get_success_data(api_client.quarantine_bath(bath["id"], EHS))
    assert quarantined["status"] == "QUARANTINED"
    # Second quarantine is rejected.
    resp_q2 = api_client.quarantine_bath(bath["id"], EHS)
    validate_error(resp_q2, ApiErrorId.ERR_BATH_NOT_ACTIVE)


def test_dump_renew_state_gates():
    """PRD §3.9: "A `ShopManager` renews a bath that is `DUMPED` — any other status
    rejects with `ERR_BATH_NOT_DUMPED`"
    PRD §3.9: "A `ShopManager` dumps a bath in `ACTIVE`, `QUARANTINED`, or `EXHAUSTED`
    status — a `DUMPED` or `DECOMMISSIONED` bath rejects with `ERR_BATH_NOT_DUMPABLE`"
    PRD §3.2: "titrating an `EXHAUSTED`, `DUMPED`, or `DECOMMISSIONED` bath is rejected
    with `ERR_BATH_NOT_DOSABLE`"

    Design: Corner/state_machines/bath_dump_renew_state_gates
    """
    bath = create_titrated_bath(bath_code="ANO-R", routing_modes_supported=["BARREL"])
    manifest = create_manifest(creator_user_id="ehs-r", generator_epa_id="EPA-GEN-R")
    # Renew on ACTIVE is rejected.
    resp_ren = api_client.renew_bath(
        bath["id"],
        {"titrant_volume_ml": 50.0, "titrant_normality": 0.1, "sample_volume_ml": 49.0},
        MGR,
    )
    validate_error(resp_ren, ApiErrorId.ERR_BATH_NOT_DUMPED)
    # First dump succeeds.
    dumped = get_success_data(api_client.dump_bath(bath["id"], {"manifest_id": manifest["id"]}, MGR))
    assert dumped["status"] == "DUMPED"
    # Second dump is rejected.
    resp_d2 = api_client.dump_bath(bath["id"], {"manifest_id": manifest["id"]}, MGR)
    validate_error(resp_d2, ApiErrorId.ERR_BATH_NOT_DUMPABLE)
    # Titration on a DUMPED bath is rejected.
    resp_tit = api_client.create_titration(
        bath["id"],
        {"titrant_volume_ml": 50.0, "titrant_normality": 0.1, "sample_volume_ml": 49.0},
        CHEM,
    )
    validate_error(resp_tit, ApiErrorId.ERR_BATH_NOT_DOSABLE)
    # Renew after dump succeeds.
    renewed = get_success_data(api_client.renew_bath(
        bath["id"],
        {"titrant_volume_ml": 50.0, "titrant_normality": 0.1, "sample_volume_ml": 49.0},
        MGR,
    ))
    assert renewed["status"] == "ACTIVE"


def test_dose_exhausted_bath_rejected():
    """PRD §3.2: "Recording a **DoseEvent** names the `chemical_code` (for example NISO4
    or H2SO4) and `quantity_g` added (greater than zero), and is allowed only while the
    bath is `ACTIVE` or `QUARANTINED` — `EXHAUSTED`, `DUMPED`, and `DECOMMISSIONED`
    baths reject dosing with `ERR_BATH_NOT_DOSABLE`."

    Design: Corner/state_machines/bath_dose_exhausted_rejected
    """
    customer = create_customer(company_name="Dose Co")
    create_compat_rule()
    bath = create_titrated_bath(
        bath_code="ANO-E", routing_modes_supported=["BARREL"], amp_hour_capacity=25,
    )
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-E")
    # 25 dm2 x 1.5 A/dm2 x 40 min / 60 = 25.0 Ah — exactly the 25 capacity.
    lr = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr["id"])
    detail = get_bath(bath["id"])
    assert detail["status"] == "EXHAUSTED"
    assert detail["amp_hour_used"] == 25.0
    resp = api_client.create_dose(
        bath["id"],
        {"chemical_code": "H2SO4", "quantity_g": 10.0,
         "expected_bath_version": detail["version"]},
        CHEM,
    )
    validate_error(resp, ApiErrorId.ERR_BATH_NOT_DOSABLE)


def test_load_run_abort_twice_rejected():
    """PRD §3.5: "Aborting — likewise only while `RUNNING`, else
    `ERR_LOAD_RUN_NOT_RUNNING`"
    PRD §3.3: "Aborted runs contribute to neither account: an abort releases its
    reservation and leaves `amp_hour_used` untouched, and these two identities hold as
    invariants at every instant."

    Design: Corner/state_machines/load_run_abort_twice_rejected
    """
    customer = create_customer(company_name="Abort Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-A", routing_modes_supported=["BARREL"])
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-A")
    lr = start_load_run(wo["id"], bath_id=bath["id"])
    abort_load_run(lr["id"])
    # Second abort rejected.
    resp = api_client.abort_load_run(lr["id"], OP)
    validate_error(resp, ApiErrorId.ERR_LOAD_RUN_NOT_RUNNING)
    # Reservation released exactly once.
    detail = get_bath(bath["id"])
    assert detail["amp_hour_reserved"] == 0, (
        f"Reservation must not double-release: got {detail['amp_hour_reserved']}"
    )
