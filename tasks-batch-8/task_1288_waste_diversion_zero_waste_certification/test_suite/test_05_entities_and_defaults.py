"""Entity creation defaults, computed fields, immutability, not-found, and
initial states (PRD §2.4, §3.1–§3.4, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_site, create_vendor, create_active_contract, create_period,
    create_ticket, create_goal, create_audit, create_application_payload,
    set_clock, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_vendor_user_headers,
)

MGR = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_site_create_applies_computed_defaults(api):
    """PRD §3.1: "A new site starts with a certification_tier of NONE and a
    program_standing of GOOD_STANDING."
    PRD §2.4: "version, an integer that increments by one on every mutation."

    Design: Corner/entities/site_create_applies_computed_defaults
    """
    site = create_site("Site DEF")
    assert site["certification_tier"] == "NONE"
    assert site["program_standing"] == "GOOD_STANDING"
    assert site["version"] == 1


def test_site_get_not_found_returns_404(api):
    """PRD §2.8: "Existence — path identifiers and body foreign keys resolve
    to existing resources, with path identifiers checked left to right; the
    first missing resource yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/site_get_not_found_returns_404
    """
    validate_error(api.get_site(NON_EXISTENT_UUID, OFFICER), ApiErrorId.ERR_NOT_FOUND)


def test_ticket_create_computes_net_weight(api):
    """PRD §3.3: "A created ticket starts PENDING, with net_weight_lbs computed
    by the server as the gross weight minus the tare weight — any
    client-supplied value for it is ignored."

    Design: Corner/entities/ticket_create_computes_net_weight
    """
    site = create_site("Site NW")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])
    t = create_ticket(site["id"], vendor["id"], contract["id"],
                      gross_weight_lbs=4200, tare_weight_lbs=1200,
                      external_ticket_ref="NW-T1")
    assert t["net_weight_lbs"] == 3000
    assert t["validation_status"] == "PENDING"


def test_ticket_create_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "Payload well-formedness — required fields are present, no
    unknown fields are supplied, enum values belong to their declared sets,
    and numeric ranges hold ...; violations yield ERR_INVALID_REQUEST
    (HTTP 400)."

    Design: Corner/entities/ticket_create_missing_required_field_returns_invalid_request
    """
    site = create_site("Site MR")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])
    payload = {
        "site_id": site["id"], "vendor_id": vendor["id"],
        "contract_id": contract["id"], "material_stream": "MIXED_RECYCLABLES",
        "disposal_route": "RECYCLING", "gross_weight_lbs": 4200,
        "tare_weight_lbs": 1200, "ticket_date": "2026-08-05",
    }
    validate_error(
        api.create_ticket(payload, make_vendor_user_headers(vendor["id"])),
        ApiErrorId.ERR_INVALID_REQUEST,
    )


def test_ticket_create_invalid_enum_returns_invalid_request(api):
    """PRD §2.8: "Payload well-formedness — required fields are present, no
    unknown fields are supplied, enum values belong to their declared sets,
    and numeric ranges hold (a `contamination_pct` between 0 and 100, weights
    as positive integers); violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.3: "its `disposal_route` — `RECYCLING`, `COMPOSTING`, `REUSE`,
    `LANDFILL`, or `ENERGY_RECOVERY`."

    Design: Corner/entities/ticket_create_invalid_enum_returns_invalid_request
    """
    site = create_site("Site IE")
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"])
    payload = {
        "site_id": site["id"], "vendor_id": vendor["id"],
        "contract_id": contract["id"], "material_stream": "MIXED_RECYCLABLES",
        "disposal_route": "COMPOST", "gross_weight_lbs": 4200,
        "tare_weight_lbs": 1200, "ticket_date": "2026-08-05",
        "external_ticket_ref": "IE-T1",
    }
    validate_error(
        api.create_ticket(payload, make_vendor_user_headers(vendor["id"])),
        ApiErrorId.ERR_INVALID_REQUEST,
    )


def test_audit_immutable_common_fields_absent(api):
    """PRD §2.4: "The waste audit is the single exception: as an immutable
    measurement log it carries only id and created_at, both updated_at and
    version are absent, and it exposes no update or delete capability once
    recorded."

    Design: Corner/entities/audit_immutable_common_fields_false
    """
    site = create_site("Site AU")
    audit = create_audit(site["id"], audit_date="2026-08-06", auditor_name="Aud A",
                         stream_findings=[{
                             "material_stream": "CARDBOARD",
                             "sampled_weight_lbs": 300,
                             "contamination_pct": 4,
                         }])
    assert "id" in audit and "created_at" in audit
    assert "version" not in audit
    assert "updated_at" not in audit


def test_initial_states_on_create(api):
    """PRD §3.1: "every vendor enters the registry `ACTIVE`."
    PRD §3.2: "A newly created contract begins in `DRAFT`."
    PRD §3.3: "A created ticket starts `PENDING`."
    PRD §3.4: "A new period starts `OPEN` with every computed total initialized
    to 0."
    PRD §3.6: "New goals start `ACTIVE`."
    PRD §4: "Create a draft application (OCC on Site.version; supersedes an
    existing DRAFT of the same site+level to WITHDRAWN)."

    Design: Corner/state_machines/initial_states_on_create
    """
    set_clock()
    site = create_site("Site IN")
    vendor = create_vendor()
    assert vendor["status"] == "ACTIVE"
    contract = create_active_contract(site["id"], vendor["id"])
    # Re-create a fresh (non-activated) contract to observe DRAFT initial state.
    from test_helpers import create_contract
    draft = create_contract(site["id"], vendor["id"], material_stream="CARDBOARD")
    assert draft["status"] == "DRAFT"
    t = create_ticket(site["id"], vendor["id"], contract["id"],
                      external_ticket_ref="IN-T1")
    assert t["validation_status"] == "PENDING"
    goal = create_goal(site["id"], metric="DIVERSION_RATE", target_value=80)
    assert goal["status"] == "ACTIVE"
    period = create_period(site["id"])
    assert period["status"] == "OPEN"
    app = get_success_data(api.create_application(
        create_application_payload(site["id"], period["id"], site["version"]), MGR,
    ))
    assert app["status"] == "DRAFT"
