"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Segregation-of-duties identities are
threaded deliberately: the material cert is registered by scm-1 and accepted
by insp-1; FAI characteristics are recorded by insp-1 and submitted by
insp-2; reports are discovered by insp-1 and dispositioned by mrb-1.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_characteristic_payload,
    create_delegation_payload,
    create_disposition_payload,
    create_fai_payload,
    create_lta_payload,
    create_material_cert_payload,
    create_ncr_payload,
    create_po_payload,
    create_process_approval_payload,
    create_serial_batch_payload,
    create_source_payload,
    create_spc_measurement_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS

CM = TEST_USERS["contracts_manager"]
SCM = TEST_USERS["supply_chain_manager"]
MP = TEST_USERS["manufacturing_planner"]
QI = TEST_USERS["quality_inspector"]  # insp-1
QI2 = TEST_USERS["quality_inspector_2"]  # insp-2
QI3 = TEST_USERS["quality_inspector_3"]  # insp-3
QI9 = TEST_USERS["quality_inspector_9"]  # insp-9
MRB = TEST_USERS["mrb_member"]
QM = TEST_USERS["quality_manager"]
CQR = TEST_USERS["customer_quality_rep"]
ADMIN = TEST_USERS["system_admin"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Set the server logical clock. Returns the clock payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 1: agreements and purchase orders
# ---------------------------------------------------------------------------

def create_lta(**overrides) -> dict:
    """Create a DRAFT long-term agreement. Returns the LTA."""
    return get_success_data(
        api_client.create_lta(create_lta_payload(**overrides), CM)
    )


def create_active_lta(**overrides) -> dict:
    """Create an LTA and activate it. Returns the ACTIVE LTA (fresh version)."""
    lta = create_lta(**overrides)
    return get_success_data(api_client.activate_lta(lta["id"], CM))


def get_lta(lta_id: str) -> dict:
    return get_success_data(api_client.get_lta(lta_id, CM))


def create_purchase_order(lta_id: str, expected_lta_version=None, **overrides) -> dict:
    """Create a PO against an LTA. When expected_lta_version is omitted the
    agreement's current version is fetched and used (OCC field, PRD §2.7)."""
    if expected_lta_version is None:
        expected_lta_version = get_lta(lta_id)["version"]
    payload = create_po_payload(
        lta_id=lta_id, expected_lta_version=expected_lta_version, **overrides
    )
    return get_success_data(api_client.create_purchase_order(payload, CM))


def create_released_po(lta_overrides=None, **po_overrides) -> dict:
    """Active LTA + PO walked RECEIVED -> ACCEPTED -> RELEASED.

    Returns {"lta": <refreshed LTA>, "po": <RELEASED PO>}.
    """
    lta = create_active_lta(**(lta_overrides or {}))
    po = create_purchase_order(lta["id"], **po_overrides)
    po = get_success_data(api_client.accept_purchase_order(po["id"], CM))
    po = get_success_data(api_client.release_purchase_order(po["id"], CM))
    return {"lta": get_lta(lta["id"]), "po": po}


# ---------------------------------------------------------------------------
# Tier 2: sources, material certs, process approvals
# ---------------------------------------------------------------------------

def create_approved_source(**overrides) -> dict:
    """Create a source (default RAW_MATERIAL / LOW) and approve it."""
    src = get_success_data(
        api_client.create_source(create_source_payload(**overrides), SCM)
    )
    return get_success_data(api_client.approve_source(src["id"], SCM))


def create_accepted_cert(source_id=None, creator=None, acceptor=None, **overrides) -> dict:
    """Register a material cert and accept it at receiving inspection.

    Segregation of duties (PRD §2.9): the acceptor's X-User-ID must differ
    from the creator's; defaults are scm-1 creating and insp-1 accepting.
    """
    creator = creator or SCM
    acceptor = acceptor or QI
    if source_id is None:
        source_id = create_approved_source()["id"]
    cert = get_success_data(
        api_client.create_material_cert(
            create_material_cert_payload(source_id=source_id, **overrides), creator
        )
    )
    return get_success_data(api_client.accept_material_cert(cert["id"], acceptor))


def create_process_approval(source_id, **overrides) -> dict:
    """Grant an ACTIVE special-process approval window."""
    return get_success_data(
        api_client.create_process_approval(
            create_process_approval_payload(source_id=source_id, **overrides), SCM
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: work orders, serials, production lifecycle
# ---------------------------------------------------------------------------

def create_work_order(po_id: str, **overrides) -> dict:
    """Create a PLANNED work order under a PO."""
    return get_success_data(
        api_client.create_work_order(create_work_order_payload(po_id=po_id, **overrides), MP)
    )


def get_work_order(wo_id: str) -> dict:
    return get_success_data(api_client.get_work_order(wo_id, QM))


def get_purchase_order(po_id: str) -> dict:
    return get_success_data(api_client.get_purchase_order(po_id, CM))


def setup_wo_in_production(
    wo_quantity: int = 5,
    serial_count=None,
    lta_overrides=None,
    cert_overrides=None,
    **po_overrides,
) -> dict:
    """Full chain: ACTIVE LTA + RELEASED PO + RELEASED WO + ACCEPTED cert +
    first serial batch (which moves the WO RELEASED -> IN_PRODUCTION).

    Returns {"lta", "po", "wo", "cert", "serials"} with the WO refreshed.
    """
    bundle = create_released_po(lta_overrides=lta_overrides, **po_overrides)
    wo = create_work_order(bundle["po"]["id"], quantity=wo_quantity)
    wo = get_success_data(api_client.release_work_order(wo["id"], MP))
    cert_kw = {"quantity_received": max(wo_quantity, 10)}
    cert_kw.update(cert_overrides or {})
    cert = create_accepted_cert(**cert_kw)
    serials = get_success_data(
        api_client.create_serial_batch(
            wo["id"],
            create_serial_batch_payload(
                material_cert_id=cert["id"], count=serial_count or wo_quantity
            ),
            MP,
        )
    )
    return {
        "lta": bundle["lta"],
        "po": get_purchase_order(bundle["po"]["id"]),
        "wo": get_work_order(wo["id"]),
        "cert": cert,
        "serials": serials,
    }


def setup_wo_completed(wo_quantity: int = 1, **kwargs) -> dict:
    """IN_PRODUCTION work order completed and accepted to COMPLETED
    (final acceptance by the customer quality rep — source inspection)."""
    bundle = setup_wo_in_production(wo_quantity=wo_quantity, **kwargs)
    get_success_data(api_client.complete_work_order(bundle["wo"]["id"], MP))
    bundle["wo"] = get_success_data(api_client.accept_work_order(bundle["wo"]["id"], CQR))
    return bundle


def setup_shipped_serial(wo_quantity: int = 1, **kwargs) -> dict:
    """COMPLETED work order with its first serial shipped."""
    bundle = setup_wo_completed(wo_quantity=wo_quantity, **kwargs)
    serial = bundle["serials"][0]
    bundle["serials"][0] = get_success_data(api_client.ship_serial(serial["id"], MP))
    return bundle


# ---------------------------------------------------------------------------
# Tier 3: first-article inspections
# ---------------------------------------------------------------------------

def create_fai(part_number=None, part_revision="A", fai_type="FULL", creator=None) -> dict:
    """Create a DRAFT first-article inspection."""
    creator = creator or QI
    kw = {"part_revision": part_revision, "fai_type": fai_type}
    if part_number is not None:
        kw["part_number"] = part_number
    return get_success_data(api_client.create_fai(create_fai_payload(**kw), creator))


def add_characteristic(fai_id: str, creator=None, **overrides) -> dict:
    """Add a ballooned characteristic to an FAI."""
    creator = creator or QI
    return get_success_data(
        api_client.add_characteristic(
            fai_id, create_characteristic_payload(**overrides), creator
        )
    )


def record_measurement(char_id: str, measured_value: float, recorder=None) -> dict:
    """Record an FAI measurement on a characteristic."""
    recorder = recorder or QI
    return get_success_data(
        api_client.record_measurement(char_id, {"measured_value": measured_value}, recorder)
    )


def setup_fai_with_measured_characteristic(
    part_number=None,
    part_revision="A",
    measured_value=10.0,
    recorder=None,
    **char_overrides,
):
    """FAI in IN_INSPECTION with one characteristic measured (PASS at 10.0
    under the default 10.0 +/- 0.1 limits). Returns (fai, characteristic)."""
    recorder = recorder or QI
    fai = create_fai(part_number=part_number, part_revision=part_revision, creator=recorder)
    char = add_characteristic(fai["id"], creator=recorder, **char_overrides)
    char = record_measurement(char["id"], measured_value, recorder=recorder)
    fai = get_success_data(api_client.get_fai(fai["id"], QM))
    return fai, char


def setup_fai_submitted(part_number=None, part_revision="A", recorder=None, submitter=None) -> dict:
    """FAI walked to SUBMITTED: one PASS characteristic recorded by one
    inspector, submitted by a different inspector (segregation of duties)."""
    recorder = recorder or QI
    submitter = submitter or QI2
    fai, _char = setup_fai_with_measured_characteristic(
        part_number=part_number, part_revision=part_revision, recorder=recorder
    )
    return get_success_data(api_client.submit_fai(fai["id"], submitter))


def setup_fai_approved(part_number=None, part_revision="A") -> dict:
    """FAI walked all the way to APPROVED."""
    fai = setup_fai_submitted(part_number=part_number, part_revision=part_revision)
    return get_success_data(api_client.approve_fai(fai["id"], CQR))


# ---------------------------------------------------------------------------
# Tier 4: nonconformance reports, dispositions, escapes
# ---------------------------------------------------------------------------

def create_ncr(wo_id: str, discoverer=None, **overrides) -> dict:
    """Open an OPEN nonconformance report on a work order."""
    discoverer = discoverer or QI
    return get_success_data(
        api_client.create_ncr(create_ncr_payload(wo_id=wo_id, **overrides), discoverer)
    )


def setup_ncr_in_mrb(wo_id: str, discoverer=None, **overrides) -> dict:
    """NCR created and submitted to the Material Review Board (MRB_REVIEW)."""
    ncr = create_ncr(wo_id, discoverer=discoverer, **overrides)
    return get_success_data(api_client.submit_ncr_mrb(ncr["id"], QM))


def disposition_ncr(ncr_id: str, disposer=None, **overrides) -> dict:
    """MRB disposition. Default disposer is mrb-1, which never collides with
    the default discoverer insp-1 (segregation of duties, PRD §2.9)."""
    disposer = disposer or MRB
    return get_success_data(
        api_client.disposition_ncr(
            ncr_id, create_disposition_payload(**overrides), disposer
        )
    )


def get_ncr(ncr_id: str) -> dict:
    return get_success_data(api_client.get_ncr(ncr_id, QM))


def get_serial(serial_id: str) -> dict:
    return get_success_data(api_client.get_serial(serial_id, QM))


def get_escape_report_for_ncr(ncr_id: str) -> dict:
    """Return the single escape report linked to an NCR."""
    data = get_success_data(api_client.list_escape_reports(QM, params={"ncr_id": ncr_id}))
    assert isinstance(data, list) and len(data) >= 1, (
        f"Setup failed: expected an escape report for NCR {ncr_id}"
    )
    return data[0]


# ---------------------------------------------------------------------------
# Tier 4: SPC measurement series (distinct logical-clock timestamps)
# ---------------------------------------------------------------------------

def record_spc_series(
    wo_id: str,
    characteristic_id: str,
    values,
    recorder=None,
    start_iso: str = "2026-08-01T00:01:00Z",
) -> list:
    """Record SPC measurements one minute apart on the logical clock so each
    observation carries a distinct created_at (PRD §3.6 window ordering)."""
    recorder = recorder or QI
    base = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    out = []
    for i, value in enumerate(values):
        ts = (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        set_clock(ts)
        out.append(
            get_success_data(
                api_client.record_spc_measurement(
                    wo_id,
                    create_spc_measurement_payload(
                        characteristic_id=characteristic_id, measured_value=value
                    ),
                    recorder,
                )
            )
        )
    return out


def get_characteristic(char_id: str) -> dict:
    return get_success_data(api_client.get_characteristic(char_id, QM))


# ---------------------------------------------------------------------------
# Tier 5: delegations
# ---------------------------------------------------------------------------

def create_delegation(po_id: str, inspector_user_id: str, grantor=None, **overrides) -> dict:
    """Grant an ACTIVE delegated inspection authority."""
    grantor = grantor or CQR
    return get_success_data(
        api_client.create_delegation(
            create_delegation_payload(
                po_id=po_id, inspector_user_id=inspector_user_id, **overrides
            ),
            grantor,
        )
    )


# ---------------------------------------------------------------------------
# SPC scenario: released WO plus a key characteristic on a matching FAI
# ---------------------------------------------------------------------------

def setup_wo_with_key_characteristic(
    wo_quantity: int = 5,
    nominal: float = 10.0,
    tolerance: float = 0.1,
    **kwargs,
) -> dict:
    """IN_PRODUCTION work order (5 serials) plus a key characteristic
    (default limits usl 10.10 / lsl 9.90) declared on an FAI for the part.
    The PO carries no AS9102_FAI clause, so FAI approval is not a release
    gate here."""
    bundle = setup_wo_in_production(wo_quantity=wo_quantity, **kwargs)
    fai = create_fai(part_number=bundle["po"]["part_number"], part_revision=bundle["po"]["part_revision"])
    kc = add_characteristic(
        fai["id"],
        balloon_number=1,
        nominal=nominal,
        tolerance_plus=tolerance,
        tolerance_minus=tolerance,
        is_key_characteristic=True,
    )
    bundle["fai"] = fai
    bundle["kc"] = kc
    return bundle
