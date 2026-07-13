"""Temporal windowing (inspector half-open occupancy, closed insurance coverage),
optimistic concurrency on certificate issuance, and the remaining authorization /
referential / fiscal single-failure gates.

Difficulty queue A: resource_temporal_overlap.
Corner queue B: cross_cutting (OCC) and validations sections.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_owner_headers,
    setup_registered_vessel,
    set_clock, new_jurisdiction, new_owner, new_inspector, commission, new_vessel,
    register_vessel, new_inspection, raise_deficiency, record_result,
    new_fee_invoice, pay_invoice, vessel_version, issue_certificate,
    new_insurance_company, new_policy, new_repair_order,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# resource_temporal_overlap / inspector_double_booked_halfopen_overlap
# ---------------------------------------------------------------------------
def test_inspector_double_booked_overlap_rejected(api):
    """PRD §3.4: "The assigned inspector must have no other non-cancelled inspection
    whose half-open window intersects the new one; because occupancy is half-open (see
    §2.5), a back-to-back booking where the previous inspection's `scheduled_end` equals
    this inspection's `scheduled_start` is permitted, but any true overlap is rejected
    with `ERR_INSPECTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/inspector_double_booked_halfopen_overlap
    """
    ctx = setup_registered_vessel()
    new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="EXTERNAL",
                   scheduled_start="2026-06-02T09:00:00Z", scheduled_end="2026-06-02T11:00:00Z")
    resp = api.create_inspection(
        {"vessel_id": ctx["vessel_id"], "inspector_id": ctx["insp_a_id"],
         "inspection_type": "INTERNAL", "scheduled_start": "2026-06-02T10:00:00Z",
         "scheduled_end": "2026-06-02T12:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED.value)


def test_inspector_back_to_back_booking_allowed(api):
    """PRD §3.4: "because occupancy is half-open (see §2.5), a back-to-back booking where
    the previous inspection's `scheduled_end` equals this inspection's `scheduled_start`
    is permitted".

    Design: Difficulty/resource_temporal_overlap/inspector_double_booked_halfopen_overlap
    """
    ctx = setup_registered_vessel()
    new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="EXTERNAL",
                   scheduled_start="2026-06-02T09:00:00Z", scheduled_end="2026-06-02T11:00:00Z")
    resp = api.create_inspection(
        {"vessel_id": ctx["vessel_id"], "inspector_id": ctx["insp_a_id"],
         "inspection_type": "INTERNAL", "scheduled_start": "2026-06-02T11:00:00Z",
         "scheduled_end": "2026-06-02T13:00:00Z"},
        ADMIN,
    )
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# resource_temporal_overlap / policy_coverage_overlap_closed_touching_endpoints
# ---------------------------------------------------------------------------
def _policy_base():
    set_clock("2026-06-01T00:00:00Z")
    jur = new_jurisdiction()
    owner = new_owner()
    ins_x = new_insurance_company()
    vessel = new_vessel(owner["id"], jur["id"], vessel_class="PRESSURE_VESSEL", mawp_psig=300)
    new_policy(vessel["id"], ins_x["id"], "2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z")
    return vessel["id"], ins_x["id"]


def test_policy_touching_endpoint_rejected(api):
    """PRD §3.3: "two windows that share an endpoint (where an existing policy's
    `coverage_end` equals the new policy's `coverage_start`) are treated as overlapping.
    A conflicting policy is rejected with `ERR_POLICY_COVERAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_coverage_overlap_closed_touching_endpoints
    """
    vessel_id, ins_x_id = _policy_base()
    resp = api.create_insurance_policy(
        {"vessel_id": vessel_id, "insurance_company_id": ins_x_id,
         "coverage_start": "2026-06-01T00:00:00Z", "coverage_end": "2026-12-01T00:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_POLICY_COVERAGE_OVERLAP.value)


def test_policy_strictly_after_existing_allowed(api):
    """PRD §3.3: "a new `ACTIVE` policy on a vessel may not overlap any existing `ACTIVE`
    policy on the same vessel, and two windows that share an endpoint (where an existing
    policy's `coverage_end` equals the new policy's `coverage_start`) are treated as
    overlapping."

    Design: Difficulty/resource_temporal_overlap/policy_coverage_overlap_closed_touching_endpoints
    """
    vessel_id, ins_x_id = _policy_base()
    resp = api.create_insurance_policy(
        {"vessel_id": vessel_id, "insurance_company_id": ins_x_id,
         "coverage_start": "2026-06-02T00:00:00Z", "coverage_end": "2026-12-01T00:00:00Z"},
        ADMIN,
    )
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Corner / cross_cutting / occ_stale_vessel_version_on_renewal_returns_412
# ---------------------------------------------------------------------------
def test_stale_vessel_version_on_renewal_rejected(api):
    """PRD §2.6: "Before the certificate is created, the server compares
    `expected_vessel_version` against the vessel's current `version`."
    PRD §2.6: "the issuance is rejected with `ERR_STALE_VESSEL_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_vessel_version_on_renewal_returns_412
    """
    ctx = setup_registered_vessel()
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])
    record_result(insp1["id"], ctx["insp_a_id"], "PASS")
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])
    pay_invoice(fee1["id"], ctx["owner_id"])
    v_ver_stale = vessel_version(ctx["vessel_id"])
    cert1 = issue_certificate(ctx["vessel_id"], insp1["id"], fee1["id"], v_ver_stale)
    # Second passing inspection + paid fee ready for renewal.
    insp2 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="EXTERNAL",
                           scheduled_start="2026-06-03T09:00:00Z", scheduled_end="2026-06-03T11:00:00Z")
    record_result(insp2["id"], ctx["insp_a_id"], "PASS")
    fee2 = new_fee_invoice(ctx["vessel_id"], insp2["id"])
    pay_invoice(fee2["id"], ctx["owner_id"])
    resp = api.create_certificate(
        {"vessel_id": ctx["vessel_id"], "inspection_id": insp2["id"], "fee_invoice_id": fee2["id"],
         "expected_vessel_version": v_ver_stale, "supersedes_certificate_id": cert1["id"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VESSEL_VERSION.value)


# ---------------------------------------------------------------------------
# Corner / validations
# ---------------------------------------------------------------------------
def test_pay_other_owners_invoice_returns_ownership_mismatch(api):
    """PRD §2.1: "When an entity-backed role acts on a resource it does not own — an
    `Owner` operating on a vessel, repair order, or fee invoice belonging to a different
    owner, or an `Inspector` recording the result of an inspection assigned to a different
    inspector — the request is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/validations/pay_other_owners_invoice_returns_ownership_mismatch
    """
    set_clock("2026-06-01T00:00:00Z")
    jur = new_jurisdiction()
    owner_a = new_owner(name="Owner A", contact_email="a@x.com")
    owner_b = new_owner(name="Owner B", contact_email="b@x.com")
    insp_a = new_inspector(jur["id"])
    commission(insp_a["id"])
    vessel = new_vessel(owner_a["id"], jur["id"])
    register_vessel(vessel["id"])
    insp1 = new_inspection(vessel["id"], insp_a["id"])
    fee1 = new_fee_invoice(vessel["id"], insp1["id"])
    resp = api.pay_fee_invoice(fee1["id"], make_owner_headers(owner_b["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)


def test_certificate_unpaid_fee_returns_fee_not_paid(api):
    """PRD §3.7: "the referenced fee invoice must be `PAID` with its `vessel_id` and
    `inspection_id` matching those on the request, else `ERR_FEE_NOT_PAID` (402)."

    Design: Corner/validations/certificate_issue_unpaid_fee_single_failure_returns_fee_not_paid
    """
    ctx = setup_registered_vessel()
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])
    record_result(insp1["id"], ctx["insp_a_id"], "PASS")
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])  # left UNPAID
    ver = vessel_version(ctx["vessel_id"])
    resp = api.create_certificate(
        {"vessel_id": ctx["vessel_id"], "inspection_id": insp1["id"],
         "fee_invoice_id": fee1["id"], "expected_vessel_version": ver},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_FEE_NOT_PAID.value)


def test_insurance_inspector_without_policy_returns_coordination_invalid(api):
    """PRD §3.3: "there must exist an `ACTIVE` insurance policy issued by the inspector's
    own insurer (its `insurance_company_id`) that covers the vessel with `coverage_start`
    at or before the inspection's `scheduled_start` and `coverage_end` at or after that
    same `scheduled_start`. If any of these conditions fails, the schedule attempt is
    rejected with `ERR_INSURANCE_COORDINATION_INVALID`."

    Design: Corner/validations/insurance_inspector_without_policy_returns_coordination_invalid
    """
    set_clock("2026-06-01T00:00:00Z")
    jur = new_jurisdiction()
    owner = new_owner()
    ins_x = new_insurance_company()
    insp_i = new_inspector(jur["id"], name="Insp I", commission_number="NBC-I",
                           inspector_type="INSURANCE", insurance_company_id=ins_x["id"])
    commission(insp_i["id"])
    vessel = new_vessel(owner["id"], jur["id"])
    register_vessel(vessel["id"])
    resp = api.create_inspection(
        {"vessel_id": vessel["id"], "inspector_id": insp_i["id"], "inspection_type": "EXTERNAL",
         "scheduled_start": "2026-06-02T09:00:00Z", "scheduled_end": "2026-06-02T11:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INSURANCE_COORDINATION_INVALID.value)


def test_repair_order_on_under_repair_deficiency_returns_not_repairable(api):
    """PRD §3.6: "Every listed deficiency must belong to that `vessel_id` and must
    currently be `OPEN`; if any does not, the order is rejected with
    `ERR_DEFICIENCY_NOT_REPAIRABLE`."

    Design: Corner/validations/repair_order_on_non_open_deficiency_returns_not_repairable
    """
    ctx = setup_registered_vessel()
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="INTERNAL")
    d1 = raise_deficiency(insp1["id"], ctx["insp_a_id"], severity="NON_CRITICAL", description="seepage")
    new_repair_order(ctx["vessel_id"], [d1["id"]], ctx["owner_id"], description="first order")
    resp = api.create_repair_order(
        {"vessel_id": ctx["vessel_id"], "deficiency_ids": [d1["id"]], "description": "second order"},
        make_owner_headers(ctx["owner_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEFICIENCY_NOT_REPAIRABLE.value)
