"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the server is restarted before each test, so each test starts from an empty
database). get_success_data() is used internally so setup failures surface as
clear "Setup step failed" errors.

Identity threading: entity-backed roles (Veterinarian, FeedMillOperator,
Producer) always use make_*_headers(entity["id"]) so ownership-gated calls
pass their identity checks (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_clinic_payload,
    create_veterinarian_payload,
    create_producer_payload,
    create_animal_group_payload,
    create_drug_payload,
    create_vcp_verification_payload,
    create_vfd_authorization_payload,
    create_feed_mill_payload,
    create_feed_order_payload,
    create_distributor_acknowledgment_payload,
    create_residue_case_payload,
    create_audit_bundle_payload,
)
from .test_users import (
    TEST_USERS,
    make_veterinarian_headers,
    make_feed_mill_operator_headers,
    make_producer_headers,
)

INSPECTOR = TEST_USERS["inspector_headers"]


def set_clock(to_iso8601: str):
    """Advance the logical clock (Inspector-only endpoint, PRD §2.5)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, INSPECTOR))


# ─── Tier 1/2: base entity builders ────────────────────

def setup_clinic_with_vet(clinic_overrides=None, vet_overrides=None):
    """Register a clinic and one ACTIVE veterinarian under it. Returns (clinic, vet)."""
    clinic = get_success_data(api_client.create_clinic(
        create_clinic_payload(**(clinic_overrides or {})), INSPECTOR))
    vet = get_success_data(api_client.create_veterinarian(
        clinic["id"], create_veterinarian_payload(**(vet_overrides or {})), INSPECTOR))
    return clinic, vet


def setup_producer_with_group(producer_overrides=None, group_overrides=None):
    """Register an ACTIVE producer and one animal group. Returns (producer, group)."""
    producer = get_success_data(api_client.create_producer(
        create_producer_payload(**(producer_overrides or {})), INSPECTOR))
    group = get_success_data(api_client.create_animal_group(
        producer["id"],
        create_animal_group_payload(**(group_overrides or {})),
        make_producer_headers(producer["id"])))
    return producer, group


def setup_drug(**overrides):
    """Register a VFD drug (prohibited_extra_label pinned true). Returns the drug."""
    return get_success_data(api_client.create_drug(create_drug_payload(**overrides), INSPECTOR))


def setup_feed_mill(mill_overrides=None):
    """Register a feed mill. Returns the mill."""
    return get_success_data(api_client.create_feed_mill(
        create_feed_mill_payload(**(mill_overrides or {})), INSPECTOR))


def setup_mill_with_ack(drug_id, mill_overrides=None, ack_overrides=None):
    """Register a feed mill plus an ACKNOWLEDGED distributor letter covering drug_id.

    Returns (mill, acknowledgment).
    """
    mill = setup_feed_mill(mill_overrides)
    ack = get_success_data(api_client.create_distributor_acknowledgment(
        mill["id"],
        create_distributor_acknowledgment_payload(drug_id, **(ack_overrides or {})),
        make_feed_mill_operator_headers(mill["id"])))
    return mill, ack


def record_vcpr(vet, producer, expires_on="2027-08-01T00:00:00Z"):
    """Record an ACTIVE VCPR covering (vet, producer). Returns the VcpVerification."""
    return get_success_data(api_client.create_vcp_verification(
        create_vcp_verification_payload(vet["id"], producer["id"], expires_on=expires_on),
        make_veterinarian_headers(vet["id"])))


def issue_vfd(vet, producer, group, drug, **overrides):
    """Issue a VFD authorization as the given vet. Returns the VfdAuthorization."""
    return get_success_data(api_client.create_vfd_authorization(
        create_vfd_authorization_payload(
            producer["id"], group["id"], vet["id"], drug["id"], **overrides),
        make_veterinarian_headers(vet["id"])))


def fresh_vfd(vfd_id):
    """Re-read a VFD (used to obtain its current version for OCC-guarded writes)."""
    return get_success_data(api_client.get_vfd_authorization(vfd_id, INSPECTOR))


# ─── Tier 3: full lifecycle composites ─────────────────

def setup_vfd_chain(
    group_overrides=None,
    drug_overrides=None,
    vfd_overrides=None,
    vcpr_expires_on="2027-08-01T00:00:00Z",
):
    """Clinic + vet + producer + animal group + drug + ACTIVE VCPR + ISSUED VFD.

    Returns a dict with keys: clinic, vet, producer, group, drug, vcpr, vfd.
    """
    clinic, vet = setup_clinic_with_vet()
    producer, group = setup_producer_with_group(group_overrides=group_overrides)
    drug = setup_drug(**(drug_overrides or {}))
    vcpr = record_vcpr(vet, producer, expires_on=vcpr_expires_on)
    vfd = issue_vfd(vet, producer, group, drug, **(vfd_overrides or {}))
    return {
        "clinic": clinic, "vet": vet, "producer": producer,
        "group": group, "drug": drug, "vcpr": vcpr, "vfd": vfd,
    }


def submit_order(mill, vfd, producer, **overrides):
    """Submit a feed order (SUBMITTED) as the mill operator. Returns the FeedOrder.

    PRD §3.5: "The `intended_use_label` must match the label indications of the
    VFD's drug". The drug's label identity is its `label_name` (the only label
    field the PRD declares, §3.1), so a lawful default order references the
    drug's `label_name`. Tests probing ERR_EXTRA_LABEL_USE override it.
    """
    if "intended_use_label" not in overrides:
        drug = get_success_data(api_client.get_drug(vfd["drug_id"], INSPECTOR))
        overrides["intended_use_label"] = drug["label_name"]
    return get_success_data(api_client.create_feed_order(
        mill["id"],
        create_feed_order_payload(vfd["id"], producer["id"], **overrides),
        make_feed_mill_operator_headers(mill["id"])))


def validate_order(mill, order, vfd_id, expected_version=None):
    """Validate an order against its VFD. If expected_version is omitted, the VFD's
    current version is read fresh (PRD §2.7 OCC guard). Returns validated order."""
    if expected_version is None:
        expected_version = fresh_vfd(vfd_id)["version"]
    return get_success_data(api_client.validate_feed_order(
        order["id"],
        {"expected_vfd_authorization_version": expected_version},
        make_feed_mill_operator_headers(mill["id"])))


def setup_order_chain(with_ack=True, order_overrides=None, **chain_kwargs):
    """VFD chain + feed mill (+ acknowledgment) + one SUBMITTED order.

    Returns dict with the chain keys plus: mill, ack (or None), order.
    """
    chain = setup_vfd_chain(**chain_kwargs)
    if with_ack:
        mill, ack = setup_mill_with_ack(chain["drug"]["id"])
    else:
        mill, ack = setup_feed_mill(), None
    order = submit_order(mill, chain["vfd"], chain["producer"], **(order_overrides or {}))
    chain.update({"mill": mill, "ack": ack, "order": order})
    return chain


def setup_validated_order(**kwargs):
    """Order chain walked through VALIDATED (WithdrawalPlan created PROVISIONAL)."""
    chain = setup_order_chain(**kwargs)
    validated = validate_order(chain["mill"], chain["order"], chain["vfd"]["id"])
    chain["order"] = validated
    chain["vfd"] = fresh_vfd(chain["vfd"]["id"])
    return chain


def setup_shipped_order(tons_shipped=1, **kwargs):
    """Order chain walked through SHIPPED. Adds key: shipment (IN_TRANSIT)."""
    chain = setup_validated_order(**kwargs)
    shipment = get_success_data(api_client.ship_feed_order(
        chain["order"]["id"], {"tons_shipped": tons_shipped},
        make_feed_mill_operator_headers(chain["mill"]["id"])))
    chain["shipment"] = shipment
    chain["order"] = get_success_data(
        api_client.get_feed_order(chain["order"]["id"], INSPECTOR))
    return chain


def setup_delivered_order(last_feed_consumed_at="2026-08-05T00:00:00Z", **kwargs):
    """Order chain walked through DELIVERED. Adds keys: shipment, order (DELIVERED)."""
    chain = setup_shipped_order(**kwargs)
    shipment = get_success_data(api_client.deliver_shipment(
        chain["shipment"]["id"], {"last_feed_consumed_at": last_feed_consumed_at},
        make_producer_headers(chain["producer"]["id"])))
    chain["shipment"] = shipment
    chain["order"] = get_success_data(
        api_client.get_feed_order(chain["order"]["id"], INSPECTOR))
    return chain


def get_withdrawal_plan_for_order(order_id):
    """Return the order's single WithdrawalPlan (list contains zero or one entry, PRD §3.11)."""
    plans = get_success_data(api_client.list_order_withdrawal_plans(order_id, INSPECTOR))
    assert isinstance(plans, list), f"Expected list of plans, got {type(plans)}"
    assert len(plans) == 1, f"Expected exactly one WithdrawalPlan for order {order_id}, got {len(plans)}"
    return plans[0]


# ─── Tier 5: residue cases / audits ────────────────────

def setup_case_under_investigation(**chain_kwargs):
    """Delivered order chain + a manual ResidueCase moved to UNDER_INVESTIGATION.

    Adds keys: case (UNDER_INVESTIGATION).
    """
    chain = setup_delivered_order(**chain_kwargs)
    case = get_success_data(api_client.create_residue_case(
        chain["producer"]["id"],
        create_residue_case_payload(chain["order"]["id"]),
        INSPECTOR))
    case = get_success_data(api_client.open_residue_investigation(case["id"], INSPECTOR))
    chain["case"] = case
    return chain


def setup_audit_bundle(producer_id, window_start="2026-07-01T00:00:00Z",
                       window_end="2026-09-01T00:00:00Z"):
    """Open an AuditBundle on a producer. Returns the bundle (OPEN)."""
    return get_success_data(api_client.create_audit_bundle(
        producer_id,
        create_audit_bundle_payload(window_start=window_start, window_end=window_end),
        INSPECTOR))
