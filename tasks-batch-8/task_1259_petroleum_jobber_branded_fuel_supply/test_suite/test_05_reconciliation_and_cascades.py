"""Reconciliation cascade, gross-vs-net variance, losses, and SoD (PRD §3.4, §3.7)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_agreement,
    create_and_deliver_drop,
    create_gasoline_product,
    create_station,
    create_tank,
    gauge_tank,
    make_admin_headers,
    make_dealer_operator_headers,
    open_reconciliation,
    reconcile_drop,
    record_audit,
    report_loss,
    setup_full_drop_fixture,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Difficulty / dual_variant_calc / variance_gross_vs_net_temperature
# ---------------------------------------------------------------------------


def _variance_net_fixture():
    """Station with gasoline tank capacity 20000 opening physical 10000,
    gauged 10000 @ 80F (corrected 10130). A 200-gal drop delivered and
    reconciled lifts book to 10200."""
    fixture = setup_full_drop_fixture(
        state_code="TX",
        state_excise_tc_per_gal=200,
        price_tc_per_gal=2000,
        tank_capacity=20000,
        opening_physical=10000,
    )
    gauge_tank(fixture, fixture["tank"]["id"], reading_gallons=10000, observed_temp_f=80)
    create_and_reconcile_drop_with = create_and_deliver_drop(
        fixture, planned_gallons=200, delivered_gallons=200
    )
    get_success_data(api_client_reconcile(create_and_reconcile_drop_with["id"]))
    return fixture


def api_client_reconcile(drop_id):
    """Small indirection so _variance_net_fixture can call reconcile via the
    test-suite api fixture when bound. The module-level reconcile_drop helper
    is used by the tests below directly."""
    from test_helpers import reconcile_drop as _r
    return _r(drop_id)


def test_variance_gross_vs_net_temperature_gross_branch(api):
    """PRD §3.7: "The gross figure, `variance_gross_gallons`, is physical
    gross minus book — reported but never used for flagging. The net figure,
    `variance_net_gallons`, is temperature-corrected: for each tank, the
    physical gallons are multiplied by one plus the product's `temp_coeff`
    times the difference between the tank's `physical_temp_f` and the
    60-degree reference (tanks never gauged use 60), each tank's corrected
    figure is rounded half-up to whole gallons, and the corrected sum minus
    `book_gallons` is the net variance."

    Design: Difficulty/dual_variant_calc/variance_gross_vs_net_temperature
    """
    fixture = setup_full_drop_fixture(
        state_code="TX", state_excise_tc_per_gal=200, price_tc_per_gal=2000,
        tank_capacity=20000, opening_physical=10000,
    )
    gauge_tank(fixture, fixture["tank"]["id"], reading_gallons=10000, observed_temp_f=80)
    drop = create_and_deliver_drop(fixture, planned_gallons=200, delivered_gallons=200)
    reconcile_drop(drop["id"])
    rec = open_reconciliation(fixture["station"]["id"])
    assert rec["variance_gross_gallons"] == -200
    assert rec["variance_net_gallons"] == -70


def test_variance_gross_vs_net_temperature_flagging_uses_net(api):
    """PRD §3.7: "Flagging uses only the net figure: the reconciliation is
    `VARIANCE_FLAGGED` when the absolute value of `variance_net_gallons` is
    strictly greater than `threshold_gallons`, and `OPEN` otherwise — a net
    variance exactly equal to the threshold stays `OPEN`."
    PRD §3.7: "A `JobberAdmin` opens an `InventoryReconciliation` for a
    station and period by supplying `station_id`, an inclusive `period_start`
    and `period_end` (the end on or after the start), and an optional
    `threshold_gallons` that defaults to 130 and must be greater than zero."

    Design: Difficulty/dual_variant_calc/variance_gross_vs_net_temperature
    """
    fixture = setup_full_drop_fixture(
        state_code="TX", state_excise_tc_per_gal=200, price_tc_per_gal=2000,
        tank_capacity=20000, opening_physical=10000,
    )
    gauge_tank(fixture, fixture["tank"]["id"], reading_gallons=10000, observed_temp_f=80)
    drop = create_and_deliver_drop(fixture, planned_gallons=200, delivered_gallons=200)
    reconcile_drop(drop["id"])
    rec = open_reconciliation(fixture["station"]["id"])
    # abs(net) = 70 <= 130 (default) -> stays OPEN even though abs(gross)=200 > 130.
    assert rec["status"] == "OPEN"
    assert rec["threshold_gallons"] == 130


# ---------------------------------------------------------------------------
# Difficulty / transitive_cascade / reconcile_flags_recon_spawns_loss
# ---------------------------------------------------------------------------


def _cascade_fixture():
    """Station + ACTIVE agreement + POSTED price + tank opening physical
    10000 gauged 10000 @ 60F; reconciliation OPEN (variance 0); 5000-gal drop
    delivered but not yet reconciled."""
    fixture = setup_full_drop_fixture(
        state_code="TX", state_excise_tc_per_gal=200, price_tc_per_gal=2000,
        tank_capacity=20000, opening_physical=10000,
    )
    gauge_tank(fixture, fixture["tank"]["id"], reading_gallons=10000, observed_temp_f=60)
    rec = open_reconciliation(fixture["station"]["id"],
                              opener_headers=make_admin_headers("ops-alice"))
    drop = create_and_deliver_drop(
        fixture, planned_gallons=5000, delivered_gallons=5000
    )
    return fixture, rec, drop


def test_reconcile_flags_recon_spawns_loss_status_and_variance(api):
    """PRD §3.6: "First, the receiving tank's `book_inventory_gallons` is
    recomputed to include the drop's `delivered_gallons`. Second, any
    inventory reconciliation for the station in `OPEN` or `VARIANCE_FLAGGED`
    recomputes its book, physical, and variance figures. Third, that
    reconciliation flips between `OPEN` and `VARIANCE_FLAGGED` as its net
    variance crosses the threshold in either direction. Fourth, on every
    transition into `VARIANCE_FLAGGED`, an automatic shrinkage loss event is
    created, as detailed in §3.7."
    PRD §3.7: "the reconciliation is `VARIANCE_FLAGGED` when the absolute
    value of `variance_net_gallons` is strictly greater than
    `threshold_gallons`, and `OPEN` otherwise"

    Design: Difficulty/transitive_cascade/reconcile_flags_recon_spawns_loss
    """
    fixture, rec, drop = _cascade_fixture()
    reconcile_drop(drop["id"])
    tank_now = get_success_data(api.get_storage_tank(fixture["tank"]["id"], ADMIN))
    assert tank_now["book_inventory_gallons"] == 15_000
    rec_now = get_success_data(api.get_inventory_reconciliation(rec["id"], ADMIN))
    assert rec_now["variance_net_gallons"] == -5_000
    assert rec_now["status"] == "VARIANCE_FLAGGED"


def test_reconcile_flags_recon_spawns_loss_auto_loss_event(api):
    """PRD §3.7: "Every transition into `VARIANCE_FLAGGED` — at creation or
    on any later recompute — automatically creates a loss event with
    `loss_type` `SHRINKAGE`, status `REPORTED`, `auto_generated` true, the
    triggering reconciliation's id in `reconciliation_id`, and `gallons` equal
    to the absolute value of the net variance rounded half-up to whole
    gallons."

    Design: Difficulty/transitive_cascade/reconcile_flags_recon_spawns_loss
    """
    fixture, rec, drop = _cascade_fixture()
    reconcile_drop(drop["id"])
    losses_resp = api.list_loss_events(
        ADMIN, params={"reconciliation_id": rec["id"]}
    )
    losses = get_success_data(losses_resp)
    assert len(losses) == 1
    auto = losses[0]
    assert auto["loss_type"] == "SHRINKAGE"
    assert auto["gallons"] == 5_000
    assert auto["auto_generated"] is True
    assert auto["status"] == "REPORTED"


# ---------------------------------------------------------------------------
# Difficulty / transitive_cascade / audit_default_cascades_to_agreement
# ---------------------------------------------------------------------------


def _audit_default_fixture():
    """ACTIVE station + ACTIVE agreement; one FAIL audit (CURE_PERIOD);
    second FAIL audit pending."""
    station = create_station(state_code="TX", state_excise_tc_per_gal=200,
                             credit_limit_cents=100_000_000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01", term_end_date="2026-12-31",
        committed_gallons=100_000, imaging_allowance_cents=100_000,
        margin_tc_per_gal=25, shortfall_penalty_tc_per_gal=20,
    )
    record_audit(station["id"], score=60, audit_date="2026-05-10",
                 deficiencies=["CANOPY"])
    return station, agreement


def test_audit_default_cascades_station_to_default(api):
    """PRD §3.4: "if another `FAIL` is recorded while the station is already
    in `CURE_PERIOD`, the station falls into `DEFAULT`."
    PRD §3.4: "Falling into `DEFAULT` is the sharpest cascade in the system:
    at the same instant, every supply agreement of the station that is in
    `ACTIVE` moves to `DEFAULT_NOTICE`, and `cure_started_at` is cleared."

    Design: Difficulty/transitive_cascade/audit_default_cascades_to_agreement
    """
    station, agreement = _audit_default_fixture()
    second = record_audit(
        station["id"], score=55, audit_date="2026-05-20",
        deficiencies=["CANOPY", "SIGNAGE"],
    )
    assert second["result"] == "FAIL"
    station_now = get_success_data(api.get_dealer_station(station["id"], ADMIN))
    assert station_now["compliance_status"] == "DEFAULT"
    assert station_now["cure_started_at"] is None


def test_audit_default_cascades_agreement_to_default_notice(api):
    """PRD §3.4: "Falling into `DEFAULT` is the sharpest cascade in the
    system: at the same instant, every supply agreement of the station that
    is in `ACTIVE` moves to `DEFAULT_NOTICE`, and `cure_started_at` is
    cleared."

    Design: Difficulty/transitive_cascade/audit_default_cascades_to_agreement
    """
    station, agreement = _audit_default_fixture()
    record_audit(station["id"], score=55, audit_date="2026-05-20")
    agreement_now = get_success_data(api.get_supply_agreement(agreement["id"], ADMIN))
    assert agreement_now["status"] == "DEFAULT_NOTICE"


# ---------------------------------------------------------------------------
# Difficulty / cross_entity_state_dependency / recon_resolve_requires_loss_written_off
# ---------------------------------------------------------------------------


def _resolve_gate_fixture():
    """Cascade fixture: VARIANCE_FLAGGED reconciliation with a REPORTED
    linked auto loss; opener was ops-alice. Returns (fixture, rec, loss)."""
    from test_helpers import api_client as api
    fixture, rec, drop = _cascade_fixture()
    reconcile_drop(drop["id"])
    losses = get_success_data(api.list_loss_events(
        ADMIN, params={"reconciliation_id": rec["id"]}
    ))
    return fixture, rec, losses[0]


def test_recon_resolve_blocked_while_loss_reported(api):
    """PRD §3.7: "the resolver's `X-User-ID` must differ from
    `opener_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and every
    loss event linked through `reconciliation_id` must already be
    `WRITTEN_OFF` or `VOIDED`, else `ERR_LINKED_LOSS_NOT_WRITTEN_OFF`."

    Design: Difficulty/cross_entity_state_dependency/recon_resolve_requires_loss_written_off
    """
    fixture, rec, loss = _resolve_gate_fixture()
    # Loss is REPORTED -> resolve must be rejected.
    resp = api.resolve_inventory_reconciliation(
        rec["id"], {"resolution_note": "premature"}, make_admin_headers("ops-bob")
    )
    validate_error(resp, ApiErrorId.ERR_LINKED_LOSS_NOT_WRITTEN_OFF)


def test_recon_resolve_succeeds_after_loss_written_off(api):
    """PRD §3.7: "Resolution records the acting user in `resolver_user_id`
    and stores the note in `resolution_note` — both null until that moment —
    and moves the reconciliation to the terminal `RESOLVED` state."
    PRD §3.7: "every loss event linked through `reconciliation_id` must
    already be `WRITTEN_OFF` or `VOIDED`, else
    `ERR_LINKED_LOSS_NOT_WRITTEN_OFF`."

    Design: Difficulty/cross_entity_state_dependency/recon_resolve_requires_loss_written_off
    """
    fixture, rec, loss = _resolve_gate_fixture()
    get_success_data(api.verify_loss_event(loss["id"], ADMIN))
    get_success_data(api.write_off_loss_event(loss["id"], ADMIN))
    resolved = validate_success(api.resolve_inventory_reconciliation(
        rec["id"], {"resolution_note": "shrinkage written off"},
        make_admin_headers("ops-bob"),
    ))
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolver_user_id"] == "ops-bob"


# ---------------------------------------------------------------------------
# Corner / validations / sod_same_user_resolve_rejected
# ---------------------------------------------------------------------------


def test_sod_same_user_resolve_rejected(api):
    """PRD §3.7: "A `JobberAdmin` resolves a reconciliation from either
    `OPEN` or `VARIANCE_FLAGGED` by supplying a `resolution_note`; the
    resolver's `X-User-ID` must differ from `opener_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)..."
    PRD §3.7: "Resolution records the acting user in `resolver_user_id` and
    stores the note in `resolution_note` — both null until that moment — and
    moves the reconciliation to the terminal `RESOLVED` state."

    Design: Corner/validations/sod_same_user_resolve_rejected
    """
    station = create_station(credit_limit_cents=500000, activate=False)
    rec = open_reconciliation(station["id"], opener_headers=make_admin_headers("ops-alice"))
    # Self-resolve attempt.
    resp = api.resolve_inventory_reconciliation(
        rec["id"], {"resolution_note": "self-resolve attempt"},
        make_admin_headers("ops-alice"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # Independent resolver succeeds.
    resolved = validate_success(api.resolve_inventory_reconciliation(
        rec["id"], {"resolution_note": "independent review"},
        make_admin_headers("ops-bob"),
    ))
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolver_user_id"] == "ops-bob"


def test_second_open_reconciliation_rejected(api):
    """PRD §3.7: "a station may have only one reconciliation in `OPEN` or
    `VARIANCE_FLAGGED` at a time — opening a second is rejected with
    `ERR_RECONCILIATION_OPEN_EXISTS`."

    Design: Corner/validations/second_open_reconciliation_rejected
    """
    station = create_station(credit_limit_cents=500000, activate=False)
    open_reconciliation(station["id"], opener_headers=make_admin_headers("ops-alice"))
    resp = api.create_inventory_reconciliation(
        {
            "station_id": station["id"],
            "period_start": "2026-06-01",
            "period_end": "2026-06-30",
        },
        make_admin_headers("ops-alice"),
    )
    validate_error(resp, ApiErrorId.ERR_RECONCILIATION_OPEN_EXISTS)


# ---------------------------------------------------------------------------
# Difficulty / compensating_invariant / loss_verify_void_restores_book
# ---------------------------------------------------------------------------


def test_loss_verify_deducts_from_book(api):
    """PRD §3.7: "verification moves an event from `REPORTED` or `DISPUTED`
    to `VERIFIED`, deducting its gallons from the tank's book when a
    `tank_id` is present and recomputing the station's open reconciliation"

    Design: Difficulty/compensating_invariant/loss_verify_void_restores_book
    """
    product = create_gasoline_product()
    station = create_station(credit_limit_cents=500000, activate=False)
    tank = create_tank(station["id"], product["id"],
                       capacity_gallons=20000, opening_physical_gallons=10000)
    dealer = make_dealer_operator_headers(station["id"])
    loss = get_success_data(api.create_loss_event(
        {
            "station_id": station["id"],
            "tank_id": tank["id"],
            "loss_type": "SPILL",
            "gallons": 500,
            "occurred_at": "2026-05-03T09:00:00Z",
        },
        dealer,
    ))
    get_success_data(api.verify_loss_event(loss["id"], ADMIN))
    tank_now = get_success_data(api.get_storage_tank(tank["id"], ADMIN))
    assert tank_now["book_inventory_gallons"] == 9_500


def test_loss_void_restores_book(api):
    """PRD §3.7: "voiding moves a `VERIFIED` event to the terminal `VOIDED`
    as the compensating action, restoring the deducted gallons to the tank's
    book and recomputing the open reconciliation again."

    Design: Difficulty/compensating_invariant/loss_verify_void_restores_book
    """
    product = create_gasoline_product()
    station = create_station(credit_limit_cents=500000, activate=False)
    tank = create_tank(station["id"], product["id"],
                       capacity_gallons=20000, opening_physical_gallons=10000)
    dealer = make_dealer_operator_headers(station["id"])
    loss = get_success_data(api.create_loss_event(
        {
            "station_id": station["id"],
            "tank_id": tank["id"],
            "loss_type": "SPILL",
            "gallons": 500,
            "occurred_at": "2026-05-03T09:00:00Z",
        },
        dealer,
    ))
    get_success_data(api.verify_loss_event(loss["id"], ADMIN))
    voided = validate_success(api.void_loss_event(loss["id"], ADMIN))
    assert voided["status"] == "VOIDED"
    tank_now = get_success_data(api.get_storage_tank(tank["id"], ADMIN))
    assert tank_now["book_inventory_gallons"] == 10_000
