"""Composite setup helpers.

Every helper builds its own preconditions from scratch through public endpoints,
because each test starts against an empty database with the logical clock at its
startup default of 2026-08-01T00:00:00Z.

Helpers use the lenient `get_success_data()` validator so a broken precondition
surfaces as a setup failure rather than as a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_UTC, TEST_DEFAULTS
from .factories import (
    create_care_plan_payload,
    create_device_order_payload,
    create_device_payload,
    create_firmware_campaign_payload,
    create_inventory_pool_payload,
    create_patient_payload,
    create_provider_payload,
    create_state_policy_payload,
    screening_measurements_payload,
    unique_suffix,
)
from .test_users import (
    ADMIN,
    CARE_OPS,
    COMPLIANCE,
    FIRMWARE_ENGINEER,
    REPAIR_TECH,
    make_licensed_audiologist_headers,
    make_patient_headers,
)


# ---------------------------------------------------------------------------
# Tier 0 — primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> None:
    """Move the logical clock."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    assert resp.status_code < 300, f"Setup failed: clock move to {to_iso8601}: {resp.text}"


def create_state_policy(**overrides) -> dict:
    return get_success_data(api_client.create_state_policy(create_state_policy_payload(**overrides), ADMIN))


def create_provider(**overrides) -> dict:
    return get_success_data(api_client.create_provider(create_provider_payload(**overrides), ADMIN))


def register_patient(state_policy_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_patient(create_patient_payload(state_policy_id, **overrides), CARE_OPS)
    )


def create_inventory_pool(restock_units: int = 5, **overrides) -> dict:
    pool = get_success_data(
        api_client.create_inventory_pool(create_inventory_pool_payload(**overrides), ADMIN)
    )
    if restock_units:
        pool = get_success_data(
            api_client.restock_inventory_pool(pool["id"], {"units": restock_units}, ADMIN)
        )
    return pool


def create_devices(count: int = 1, **overrides) -> list:
    return [
        get_success_data(api_client.create_device(create_device_payload(**overrides), ADMIN))
        for _ in range(count)
    ]


def screen_patient(patient_id: str, **measurements) -> dict:
    """Start, measure and submit one screening. Returns the scored session."""
    headers = make_patient_headers(patient_id)
    session = get_success_data(api_client.start_screening_session(patient_id, {}, headers))
    get_success_data(
        api_client.update_screening_session(
            session["id"], screening_measurements_payload(**measurements), headers
        )
    )
    return get_success_data(api_client.submit_screening_session(session["id"], headers))


def place_order(patient_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_device_order(
            patient_id, create_device_order_payload(**overrides), make_patient_headers(patient_id)
        )
    )


def simulate_payment(order_id: str, outcome: str = "AUTHORIZED") -> dict:
    return get_success_data(
        api_client.simulate_payment({"device_order_id": order_id, "outcome": outcome}, ADMIN)
    )


def confirm_and_ship(order_id: str) -> dict:
    get_success_data(api_client.confirm_fit(order_id, CARE_OPS))
    return get_success_data(api_client.ship_device_order(order_id, CARE_OPS))


def scan_shipment(order_id: str, event: str) -> dict:
    return get_success_data(
        api_client.scan_shipment({"device_order_id": order_id, "event": event}, ADMIN)
    )


def get_trial_for_order(order_id: str) -> dict:
    body = api_client.list_trial_periods(CARE_OPS, params={"device_order_id": order_id}).json()
    rows = body["data"]
    assert rows, f"Setup failed: no trial period exists for order {order_id}"
    return rows[0]


def get_referral_for_patient(patient_id: str) -> dict:
    body = api_client.list_provider_referrals(CARE_OPS, params={"patient_id": patient_id}).json()
    rows = body["data"]
    assert rows, f"Setup failed: no provider referral exists for patient {patient_id}"
    return rows[0]


def get_pool(pool_id: str) -> dict:
    body = api_client.list_inventory_pools(CARE_OPS).json()
    for row in body["data"]:
        if row["id"] == pool_id:
            return row
    raise AssertionError(f"Setup failed: inventory pool {pool_id} not listed")


# ---------------------------------------------------------------------------
# Tier 1 / 2 — environment and patient hierarchy
# ---------------------------------------------------------------------------
def bootstrap_environment(policy_overrides=None, pool_overrides=None,
                          restock_units: int = 5, device_count: int = 1,
                          clock: str = CLOCK_START_UTC) -> dict:
    """Clock + one state policy + one restocked pool + N minted devices."""
    set_clock(clock)
    policy = create_state_policy(**(policy_overrides or {}))
    pool_kwargs = dict(pool_overrides or {})
    pool = create_inventory_pool(restock_units=restock_units, **pool_kwargs)
    devices = create_devices(
        device_count,
        model=pool_kwargs.get("model", TEST_DEFAULTS["MODEL"]),
    )
    return {"policy": policy, "pool": pool, "devices": devices}


def setup_registered_patient(policy_overrides=None, patient_overrides=None, **env_kwargs) -> dict:
    env = bootstrap_environment(policy_overrides=policy_overrides, **env_kwargs)
    env["patient"] = register_patient(env["policy"]["id"], **(patient_overrides or {}))
    return env


def setup_screened_patient(measurements=None, **kwargs) -> dict:
    """Registered patient with one clean scored screening (CANDIDATE_APPROVED)."""
    env = setup_registered_patient(**kwargs)
    env["screening"] = screen_patient(env["patient"]["id"], **(measurements or {}))
    return env


def setup_red_flagged_patient(symptom_codes=("SUDDEN_LOSS",), measurements=None, **kwargs) -> dict:
    """Screening submitted with a mandatory symptom code, so a referral is opened."""
    env = setup_registered_patient(**kwargs)
    payload = dict(measurements or {})
    payload["symptom_codes"] = list(symptom_codes)
    env["screening"] = screen_patient(env["patient"]["id"], **payload)
    env["referral"] = get_referral_for_patient(env["patient"]["id"])
    return env


# ---------------------------------------------------------------------------
# Tier 3 — order lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_placed_order(order_overrides=None, **kwargs) -> dict:
    env = setup_screened_patient(**kwargs)
    env["order"] = place_order(env["patient"]["id"], **(order_overrides or {}))
    return env


def setup_authorized_order(order_overrides=None, **kwargs) -> dict:
    env = setup_placed_order(order_overrides=order_overrides, **kwargs)
    env["order"] = simulate_payment(env["order"]["id"])
    return env


def setup_shipped_order(order_overrides=None, **kwargs) -> dict:
    env = setup_authorized_order(order_overrides=order_overrides, **kwargs)
    env["order"] = confirm_and_ship(env["order"]["id"])
    return env


def setup_delivered_order(order_overrides=None, **kwargs) -> dict:
    """Full happy path to DELIVERED, which starts the trial period."""
    env = setup_shipped_order(order_overrides=order_overrides, **kwargs)
    env["order"] = scan_shipment(env["order"]["id"], "DELIVERED")
    env["trial"] = get_trial_for_order(env["order"]["id"])
    devices = api_client.list_devices(CARE_OPS, params={"device_order_id": env["order"]["id"]}).json()["data"]
    env["assigned_device"] = devices[0] if devices else None
    return env


# ---------------------------------------------------------------------------
# Tier 4 — trial / return progression
# ---------------------------------------------------------------------------
def issue_return_authorization(env: dict, at_iso: str = None) -> dict:
    """Read the trial version back, then issue the RMA under the version guard."""
    if at_iso:
        set_clock(at_iso)
    trial = get_success_data(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    env["trial"] = trial
    rma = get_success_data(
        api_client.create_return_authorization(
            trial["id"],
            {"expected_trial_period_version": trial["version"]},
            make_patient_headers(env["patient"]["id"]),
        )
    )
    env["rma"] = rma
    return rma


def setup_return_received(at_iso: str = None, **kwargs) -> dict:
    """Delivered order → RMA issued → picked up → received at the depot."""
    env = setup_delivered_order(**kwargs)
    issue_return_authorization(env, at_iso=at_iso)
    scan_shipment(env["order"]["id"], "RETURN_PICKED_UP")
    env["rma"] = get_success_data(api_client.receive_return_authorization(env["rma"]["id"], CARE_OPS))
    return env


def setup_return_inspected(inspection_grade: str = "RESELLABLE", at_iso: str = None, **kwargs) -> dict:
    env = setup_return_received(at_iso=at_iso, **kwargs)
    env["rma"] = get_success_data(
        api_client.inspect_return_authorization(
            env["rma"]["id"], {"inspection_grade": inspection_grade}, CARE_OPS
        )
    )
    return env


def setup_return_settled(inspection_grade: str = "RESELLABLE", at_iso: str = None, **kwargs) -> dict:
    env = setup_return_inspected(inspection_grade=inspection_grade, at_iso=at_iso, **kwargs)
    env["rma"] = get_success_data(api_client.settle_return_authorization(env["rma"]["id"], CARE_OPS))
    return env


# ---------------------------------------------------------------------------
# Tier 3 — care plan lifecycle
# ---------------------------------------------------------------------------
def enroll_care_plan(env: dict, **overrides) -> dict:
    plan = get_success_data(
        api_client.create_care_plan_subscription(
            create_care_plan_payload(env["patient"]["id"], env["order"]["id"], **overrides),
            make_patient_headers(env["patient"]["id"]),
        )
    )
    env["plan"] = plan
    return plan


def setup_active_care_plan(plan_overrides=None, order_overrides=None, **kwargs) -> dict:
    """Care plan enrolled before delivery, so the delivery scan activates it."""
    env = setup_shipped_order(order_overrides=order_overrides, **kwargs)
    enroll_care_plan(env, **(plan_overrides or {}))
    env["order"] = scan_shipment(env["order"]["id"], "DELIVERED")
    env["trial"] = get_trial_for_order(env["order"]["id"])
    env["plan"] = get_success_data(api_client.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
    devices = api_client.list_devices(CARE_OPS, params={"device_order_id": env["order"]["id"]}).json()["data"]
    env["assigned_device"] = devices[0] if devices else None
    return env


def run_billing_cycles(plan_id: str, count: int = 1, charge_outcome: str = "SUCCEEDED") -> dict:
    plan = None
    for _ in range(count):
        plan = get_success_data(
            api_client.run_billing_cycle(plan_id, {"charge_outcome": charge_outcome}, ADMIN)
        )
    return plan


# ---------------------------------------------------------------------------
# Tier 3 — repair lifecycle
# ---------------------------------------------------------------------------
def open_repair_order(env: dict, fault_code: str = "NO_SOUND") -> dict:
    repair = get_success_data(
        api_client.create_repair_order(
            {"device_id": env["assigned_device"]["id"], "fault_code": fault_code},
            make_patient_headers(env["patient"]["id"]),
        )
    )
    env["repair"] = repair
    return repair


def setup_repair_received(fault_code: str = "NO_SOUND", **kwargs) -> dict:
    """Delivered order → repair opened → kit sent → received at the depot."""
    env = kwargs.pop("env", None) or setup_delivered_order(**kwargs)
    open_repair_order(env, fault_code=fault_code)
    get_success_data(api_client.send_repair_kit(env["repair"]["id"], CARE_OPS))
    env["repair"] = get_success_data(api_client.receive_repair_order(env["repair"]["id"], REPAIR_TECH))
    return env


def setup_repair_in_progress(**kwargs) -> dict:
    env = setup_repair_received(**kwargs)
    env["repair"] = get_success_data(api_client.start_repair_order(env["repair"]["id"], REPAIR_TECH))
    return env


# ---------------------------------------------------------------------------
# Tier 3 — warranty lifecycle
# ---------------------------------------------------------------------------
def file_warranty_claim(env: dict, claim_kind: str = "DEFECT", **overrides) -> dict:
    payload = {"device_id": env["assigned_device"]["id"], "claim_kind": claim_kind}
    payload.update(overrides)
    claim = get_success_data(
        api_client.create_warranty_claim(payload, make_patient_headers(env["patient"]["id"]))
    )
    env["warranty_claim"] = claim
    return claim


def setup_triaged_warranty_claim(claim_kind: str = "DEFECT", **kwargs) -> dict:
    env = kwargs.pop("env", None) or setup_delivered_order(**kwargs)
    file_warranty_claim(env, claim_kind=claim_kind)
    env["warranty_claim"] = get_success_data(
        api_client.triage_warranty_claim(env["warranty_claim"]["id"], REPAIR_TECH)
    )
    return env


# ---------------------------------------------------------------------------
# Tier 3 — referral evaluation session
# ---------------------------------------------------------------------------
def setup_evaluated_referral(session_start: str = "2026-08-03T10:00:00Z",
                             session_end: str = "2026-08-03T10:30:00Z",
                             session_now: str = "2026-08-03T10:05:00Z",
                             provider_overrides=None, **kwargs) -> dict:
    """Red-flag screening → audiologist takes the REFERRAL_EVALUATION slot → session completed."""
    env = setup_red_flagged_patient(**kwargs)
    env["provider"] = create_provider(**(provider_overrides or {}))
    patient_headers = make_patient_headers(env["patient"]["id"])
    env["session"] = get_success_data(
        api_client.create_remote_fitting_session(
            {
                "patient_id": env["patient"]["id"],
                "session_type": "REFERRAL_EVALUATION",
                "scheduled_start_utc": session_start,
                "scheduled_end_utc": session_end,
                "provider_id": env["provider"]["id"],
                "provider_referral_id": env["referral"]["id"],
            },
            patient_headers,
        )
    )
    set_clock(session_now)
    provider_headers = make_licensed_audiologist_headers(env["provider"]["id"])
    get_success_data(api_client.start_fitting_session(env["session"]["id"], provider_headers))
    env["session"] = get_success_data(
        api_client.complete_fitting_session(env["session"]["id"], {}, provider_headers)
    )
    return env


def clear_referral(env: dict, outcome: str = "CLEARED", note: str = "no pathology") -> dict:
    payload = {"clearance_outcome": outcome, "clearance_note": note}
    env["referral"] = get_success_data(
        api_client.record_referral_determination(
            env["referral"]["id"], payload,
            make_licensed_audiologist_headers(env["provider"]["id"]),
        )
    )
    return env["referral"]


# ---------------------------------------------------------------------------
# Tier 3 — firmware lifecycle
# ---------------------------------------------------------------------------
def create_campaign(**overrides) -> dict:
    return get_success_data(
        api_client.create_firmware_campaign(create_firmware_campaign_payload(**overrides), FIRMWARE_ENGINEER)
    )


def setup_scheduled_campaign(**overrides) -> dict:
    campaign = create_campaign(**overrides)
    return get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))


def enroll_device_in_campaign(campaign_id: str, device_id: str) -> dict:
    device = get_success_data(api_client.get_device(device_id, FIRMWARE_ENGINEER))
    return get_success_data(
        api_client.create_manual_enrollment(
            campaign_id,
            {"device_id": device_id, "expected_device_version": device["version"]},
            FIRMWARE_ENGINEER,
        )
    )


def setup_offered_rollout(campaign_overrides=None, **kwargs) -> dict:
    """Delivered order with an active care plan, plus one OFFERED rollout on its device."""
    env = setup_active_care_plan(**kwargs)
    env["campaign"] = setup_scheduled_campaign(**(campaign_overrides or {}))
    env["rollout"] = enroll_device_in_campaign(env["campaign"]["id"], env["assigned_device"]["id"])
    env["rollout"] = get_success_data(
        api_client.offer_firmware_rollout(env["rollout"]["id"], FIRMWARE_ENGINEER)
    )
    return env


# ---------------------------------------------------------------------------
# Tier 5 — compliance override
# ---------------------------------------------------------------------------
def file_compliance_override(patient_id: str, justification: str = "clinical review complete") -> dict:
    return get_success_data(
        api_client.create_compliance_override(patient_id, {"justification": justification}, COMPLIANCE)
    )


def next_serial(prefix: str = "SN") -> str:
    return f"{prefix}-{unique_suffix()}"
