"""Composite setup helpers.

These encapsulate the multi-step API sequences that the test claims require.
Every helper builds its preconditions from scratch (the server database is empty
before each test) using only PRD-declared endpoints, and uses get_success_data()
so setup problems surface as clear "Setup failed" errors.

Identity threading: Owner and Inspector are entity-backed roles, so any
ownership-gated call threads the real entity id through make_owner_headers /
make_inspector_headers. JurisdictionAdmin is opaque.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_owner_headers,
    make_inspector_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ============================================================================
# Low-level building blocks (each returns the created / updated resource dict)
# ============================================================================
def set_clock(iso: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def new_jurisdiction(code: str = "CA", name: str = "California", **overrides) -> dict:
    payload = {"code": code, "name": name}
    payload.update(overrides)
    return get_success_data(api_client.create_jurisdiction(payload, ADMIN))


def new_owner(name: str = "Acme Boilers", contact_email: str = "o@x.com") -> dict:
    return get_success_data(
        api_client.create_owner({"name": name, "contact_email": contact_email}, ADMIN)
    )


def new_insurance_company(name: str = "Insurer X", nb: str = "NBA-X") -> dict:
    return get_success_data(
        api_client.create_insurance_company(
            {"name": name, "nb_accreditation_number": nb}, ADMIN
        )
    )


def new_inspector(jur_id, name="Insp A", commission_number="NBC-A",
                  inspector_type="JURISDICTION", insurance_company_id=None) -> dict:
    payload = {
        "name": name,
        "commission_number": commission_number,
        "inspector_type": inspector_type,
        "commissioning_jurisdiction_id": jur_id,
    }
    if insurance_company_id is not None:
        payload["insurance_company_id"] = insurance_company_id
    return get_success_data(api_client.create_inspector(payload, ADMIN))


def commission(inspector_id: str) -> dict:
    return get_success_data(api_client.commission_inspector(inspector_id, ADMIN))


def new_vessel(owner_id, jur_id, national_board_number="NBV-1",
               vessel_class="POWER_BOILER", mawp_psig=120,
               installed_at="2020-01-01T00:00:00Z", manufacturer="M") -> dict:
    payload = {
        "owner_id": owner_id,
        "jurisdiction_id": jur_id,
        "manufacturer": manufacturer,
        "national_board_number": national_board_number,
        "vessel_class": vessel_class,
        "mawp_psig": mawp_psig,
        "installed_at": installed_at,
    }
    return get_success_data(api_client.create_vessel(payload, make_owner_headers(owner_id)))


def register_vessel(vessel_id: str) -> dict:
    return get_success_data(api_client.register_vessel(vessel_id, ADMIN))


def get_vessel(vessel_id: str) -> dict:
    return get_success_data(api_client.get_vessel(vessel_id, ADMIN))


def vessel_version(vessel_id: str) -> int:
    return get_vessel(vessel_id)["version"]


def new_inspection(vessel_id, inspector_id, inspection_type="EXTERNAL",
                   scheduled_start="2026-06-02T09:00:00Z",
                   scheduled_end="2026-06-02T11:00:00Z") -> dict:
    payload = {
        "vessel_id": vessel_id,
        "inspector_id": inspector_id,
        "inspection_type": inspection_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    return get_success_data(api_client.create_inspection(payload, ADMIN))


def raise_deficiency(inspection_id, inspector_id, severity="NON_CRITICAL",
                     description="finding") -> dict:
    return get_success_data(
        api_client.raise_deficiency(
            inspection_id,
            {"severity": severity, "description": description},
            make_inspector_headers(inspector_id),
        )
    )


def record_result(inspection_id, inspector_id, result) -> dict:
    return get_success_data(
        api_client.record_inspection_result(
            inspection_id, {"result": result}, make_inspector_headers(inspector_id)
        )
    )


def new_fee_invoice(vessel_id, inspection_id) -> dict:
    return get_success_data(
        api_client.create_fee_invoice(
            {"vessel_id": vessel_id, "inspection_id": inspection_id}, ADMIN
        )
    )


def pay_invoice(invoice_id, owner_id) -> dict:
    return get_success_data(
        api_client.pay_fee_invoice(invoice_id, make_owner_headers(owner_id))
    )


def issue_certificate(vessel_id, inspection_id, fee_invoice_id, version,
                      supersedes_certificate_id=None) -> dict:
    payload = {
        "vessel_id": vessel_id,
        "inspection_id": inspection_id,
        "fee_invoice_id": fee_invoice_id,
        "expected_vessel_version": version,
    }
    if supersedes_certificate_id is not None:
        payload["supersedes_certificate_id"] = supersedes_certificate_id
    return get_success_data(api_client.create_certificate(payload, ADMIN))


def new_repair_order(vessel_id, deficiency_ids, owner_id, description="repair") -> dict:
    return get_success_data(
        api_client.create_repair_order(
            {"vessel_id": vessel_id, "deficiency_ids": deficiency_ids, "description": description},
            make_owner_headers(owner_id),
        )
    )


def complete_repair_order(ro_id, owner_id) -> dict:
    return get_success_data(
        api_client.complete_repair_order(ro_id, make_owner_headers(owner_id))
    )


def new_policy(vessel_id, insurance_company_id, coverage_start, coverage_end) -> dict:
    return get_success_data(
        api_client.create_insurance_policy(
            {
                "vessel_id": vessel_id,
                "insurance_company_id": insurance_company_id,
                "coverage_start": coverage_start,
                "coverage_end": coverage_end,
            },
            ADMIN,
        )
    )


def file_incident(vessel_id, owner_id, severity="CRITICAL",
                  occurred_at="2026-05-30T00:00:00Z", narrative="incident") -> dict:
    return get_success_data(
        api_client.file_incident(
            vessel_id,
            {"severity": severity, "occurred_at": occurred_at, "narrative": narrative},
            make_owner_headers(owner_id),
        )
    )


# ============================================================================
# Composite setups
# ============================================================================
def setup_registered_vessel(clock="2026-06-01T00:00:00Z", vessel_class="POWER_BOILER",
                            mawp_psig=120, installed_at="2020-01-01T00:00:00Z",
                            national_board_number="NBV-1"):
    """Clock set + jurisdiction + owner + one COMMISSIONED jurisdiction inspector +
    a REGISTERED vessel. Returns dict of ids and the vessel dict."""
    set_clock(clock)
    jur = new_jurisdiction()
    owner = new_owner()
    insp_a = new_inspector(jur["id"])
    commission(insp_a["id"])
    vessel = new_vessel(owner["id"], jur["id"], national_board_number=national_board_number,
                        vessel_class=vessel_class, mawp_psig=mawp_psig, installed_at=installed_at)
    register_vessel(vessel["id"])
    return {
        "jur": jur, "owner": owner, "insp_a": insp_a,
        "jur_id": jur["id"], "owner_id": owner["id"], "insp_a_id": insp_a["id"],
        "vessel_id": vessel["id"],
    }


def setup_certified_vessel(clock="2026-06-01T00:00:00Z", vessel_class="POWER_BOILER",
                           mawp_psig=120, installed_at="2020-01-01T00:00:00Z"):
    """Registered vessel taken all the way to an ACTIVE certificate and IN_SERVICE
    via a PASS inspection + paid fee. Returns the id bundle plus insp1/fee1/cert1."""
    ctx = setup_registered_vessel(clock=clock, vessel_class=vessel_class,
                                  mawp_psig=mawp_psig, installed_at=installed_at)
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])
    record_result(insp1["id"], ctx["insp_a_id"], "PASS")
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])
    pay_invoice(fee1["id"], ctx["owner_id"])
    ver = vessel_version(ctx["vessel_id"])
    cert1 = issue_certificate(ctx["vessel_id"], insp1["id"], fee1["id"], ver)
    ctx.update({"insp1_id": insp1["id"], "fee1_id": fee1["id"], "cert1_id": cert1["id"]})
    return ctx


def setup_deficiency_in_reinspection(clock="2026-06-01T00:00:00Z", severity="NON_CRITICAL"):
    """Registered vessel + two commissioned inspectors (A originating, B independent);
    a deficiency raised by A, PASS_WITH_DEFICIENCIES (or FAIL for CRITICAL), repair order
    opened and completed so the deficiency reaches REINSPECTION. Returns ids incl. d1."""
    set_clock(clock)
    jur = new_jurisdiction()
    owner = new_owner()
    insp_a = new_inspector(jur["id"])
    commission(insp_a["id"])
    insp_b = new_inspector(jur["id"], name="Insp B", commission_number="NBC-B")
    commission(insp_b["id"])
    vessel = new_vessel(owner["id"], jur["id"])
    register_vessel(vessel["id"])
    insp1 = new_inspection(vessel["id"], insp_a["id"], inspection_type="INTERNAL")
    d1 = raise_deficiency(insp1["id"], insp_a["id"], severity=severity)
    result = "FAIL" if severity == "CRITICAL" else "PASS_WITH_DEFICIENCIES"
    record_result(insp1["id"], insp_a["id"], result)
    ro1 = new_repair_order(vessel["id"], [d1["id"]], owner["id"])
    complete_repair_order(ro1["id"], owner["id"])
    return {
        "jur_id": jur["id"], "owner_id": owner["id"],
        "insp_a_id": insp_a["id"], "insp_b_id": insp_b["id"],
        "vessel_id": vessel["id"], "insp1_id": insp1["id"],
        "d1_id": d1["id"], "ro1_id": ro1["id"],
    }
