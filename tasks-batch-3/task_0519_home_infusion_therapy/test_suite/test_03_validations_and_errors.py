"""Business validations and error paths: nurse licensure, inventory, auth units,
lab-overdue gate, stale order version.

Translates Queue B (Corner) instances from sections: validations, errors,
cross_cutting_complexity_layers (OCC version, negative AE boundary).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_visiting_nurse_headers,
    fixtures,
    factories as F,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
AUTH = TEST_USERS["auth_specialist_headers"]
BILLER = TEST_USERS["biller_headers"]


def test_nurse_license_state_must_match_patient_service_state(api):
    """PRD 3.6: "the nurse's `license_state` must equal the order's patient's `service_state` and the nurse's `status` must be `ACTIVE`; otherwise the request is rejected with `ERR_NURSE_NOT_LICENSED`."

    Design: Corner/validations/nurse_license_state_must_match_patient_service_state
    """
    ctx = fixtures.setup_released_nonspecialty_order(order_overrides={"daily_dose_mg": 1000})
    # patient is in CA; create a TX-licensed nurse
    nurse = fixtures.create_nurse(license_state="TX")
    resp = api.create_visit(
        F.create_visit_payload(
            order_id=ctx["order"]["id"], nurse_id=nurse["id"],
            start_at="2026-06-10T09:00:00Z", duration_min=120,
        ),
        make_visiting_nurse_headers(nurse["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NURSE_NOT_LICENSED.value)


def test_insufficient_inventory_on_compound(api):
    """PRD 3.4: "Compounding may not reserve more vials than the drug's current `on_hand_vials`; a shortfall is rejected with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Corner/validations/insufficient_inventory_on_compound
    """
    # needs ceil(2000*7/1000) = 14 vials, lot has only 10
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={"vial_size_mg": 1000, "awp_per_vial_cents": 4250, "lot_total_vials": 10},
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 7},
    )
    pump = fixtures.create_pump()
    compound = validate_success(
        api.create_compound(
            F.create_compound_payload(order_id=ctx["order"]["id"], pump_id=pump["id"]),
            PHARM,
        ),
        expected_status=201,
    )
    resp = api.compound_compound(compound["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)
    drug = validate_success(api.get_drug(ctx["drug"]["id"], PHARM))
    assert drug["on_hand_vials"] == 10, "inventory unchanged on rejected compound"


def test_auth_units_exceeded_on_compound(api):
    """PRD 3.4: "If the order went through authorization, the required vial count must not exceed the authorization's `approved_units`; needing more than was approved is rejected with `ERR_AUTH_UNITS_EXCEEDED`."

    Design: Corner/validations/auth_units_exceeded_on_compound
    """
    # specialty order, approved_units=10, but needs ceil(2000*7/1000)=14
    ctx = fixtures.setup_released_specialty_order(
        approved_units=10,
        requested_units=10,
        drug_overrides={"vial_size_mg": 1000, "awp_per_vial_cents": 4250, "lot_total_vials": 100},
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 7},
    )
    pump = fixtures.create_pump()
    compound = validate_success(
        api.create_compound(
            F.create_compound_payload(order_id=ctx["order"]["id"], pump_id=pump["id"]),
            PHARM,
        ),
        expected_status=201,
    )
    resp = api.compound_compound(compound["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_AUTH_UNITS_EXCEEDED.value)


def test_lab_overdue_blocks_fourth_visit(api):
    """PRD 3.7: "If the visit's `sequence_index` is at least 4 and the order's drug has `requires_trough_lab` set to true, the visit may complete only when a trough lab already exists in the monitoring window ... If no such trough lab exists when a fourth-or-later visit on a trough-monitored order tries to complete, the completion is blocked with `ERR_LAB_OVERDUE`"

    Design: Corner/validations/lab_overdue_blocks_fourth_visit
    """
    # Clock is advanced past all four visit dates (2026-06-10..13) so that the
    # PRD §3.9 future-only hold sweep — triggered when the lab-overdue block places
    # the ACTIVE order ON_HOLD — leaves the still-SCHEDULED, now past-dated 4th
    # visit untouched. (With the default 2026-06-09 clock the visits are future
    # and the PRD-faithful sweep would correctly mark the blocked 4th visit MISSED.)
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={"requires_trough_lab": True, "vial_size_mg": 1000, "awp_per_vial_cents": 4250},
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 5},
        clock="2026-06-20T00:00:00Z",
    )
    nurse = fixtures.add_nurse(ctx)
    nid = nurse["id"]
    visits = []
    for day in (10, 11, 12, 13):
        v = fixtures.schedule_visit(
            ctx["order"]["id"], nid, start_at=f"2026-06-{day:02d}T08:00:00Z", duration_min=60
        )
        visits.append(v)
    # first three complete fine
    for v in visits[:3]:
        fixtures.complete_visit(v["id"], nid)
    # 4th (sequence_index 4) blocked: no TROUGH lab on file
    resp = api.complete_visit(visits[3]["id"], make_visiting_nurse_headers(nid))
    validate_error(resp, ApiErrorId.ERR_LAB_OVERDUE.value)
    v4 = validate_success(api.get_visit(visits[3]["id"], make_visiting_nurse_headers(nid)))
    assert v4["status"] == "SCHEDULED", "blocked 4th visit stays SCHEDULED"


def test_error_stale_order_version_on_claim_create(api):
    """PRD 2.7: "If they differ — because some intervening operation (a visit completion, a hold, a discontinuation cascade, or any other mutation) has advanced the order's version since the client last read it — the create is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_order_version_on_claim_create
    """
    ctx = fixtures.setup_released_nonspecialty_order(order_overrides={"daily_dose_mg": 1000, "scheduled_days": 5})
    nurse = fixtures.add_nurse(ctx)
    nid = nurse["id"]
    v1 = fixtures.schedule_visit(
        ctx["order"]["id"], nid, start_at="2026-06-10T09:00:00Z", duration_min=120
    )
    v2 = fixtures.schedule_visit(
        ctx["order"]["id"], nid, start_at="2026-06-11T09:00:00Z", duration_min=120
    )
    fixtures.complete_visit(v1["id"], nid)
    stale_ver = fixtures.get_order_version(ctx["order"]["id"])
    # a SECOND completion advances the order version past stale_ver
    fixtures.complete_visit(v2["id"], nid)
    resp = api.create_claim(
        F.create_claim_payload(order_id=ctx["order"]["id"], expected_order_version=stale_ver),
        BILLER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value)


# --- cross-cutting complexity layers (non-stub) ---
def test_occ_version_increments_on_submit(api):
    """PRD 2.4: "The `version` begins at 1 when the resource is created and increments by exactly 1 on every mutation of that resource."
    PRD 3.3: "Both branches require the order to be in `DRAFT` and both increment the order's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_write
    """
    ctx = fixtures.setup_draft_order(drug_overrides={"is_specialty": False}, order_overrides={"daily_dose_mg": 1000})
    assert ctx["order"]["version"] == 1, "DRAFT order starts at version 1"
    validate_success(api.submit_order(ctx["order"]["id"], PHARM))
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["version"] == 2, f"version 2 after submit, got {order['version']}"


def test_ae_severity_threshold_below_boundary_no_hold(api):
    """PRD 3.9: "When this `severity_score` reaches or exceeds the auto-hold threshold of 7, the reporting cascade automatically holds the order:"
    PRD 3.9: "two times `severity_grade`, plus one times `reaction_count`, plus three times `vital_instability`."

    Design: Corner/cross_cutting_complexity_layers/ae_severity_threshold_below_boundary_no_hold
    """
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1, scheduled_days=5,
        drug_overrides={"vial_size_mg": 1000, "awp_per_vial_cents": 4250,
                        "therapy_category": "AMINOGLYCOSIDE_OR_VANCO"},
        plan_overrides={"per_diem_rate_cents": {"AMINOGLYCOSIDE_OR_VANCO": 12500}},
        order_overrides={"daily_dose_mg": 2000},
    )
    nurse = ctx["nurse"]
    # grade2 react2 vital0 => 2*2 + 1*2 + 3*0 = 6, below 7
    ae = fixtures.report_adverse_event(
        ctx["order"]["id"], nurse_id=nurse["id"],
        severity_grade=2, reaction_count=2, vital_instability=0,
    )
    assert ae["severity_score"] == 6, f"expected 6, got {ae['severity_score']}"
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "ACTIVE", "score 6 < 7 must not hold the order"
