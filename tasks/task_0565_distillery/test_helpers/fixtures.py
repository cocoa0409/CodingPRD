"""Composite setup helpers.

Each test runs against a freshly restarted server with an empty database and the
logical clock at its 2026-05-01T00:00:00Z default, so every helper builds its
preconditions from scratch using only PRD-declared endpoints. Helpers use the
lenient get_success_data() so a setup failure surfaces clearly.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_customer_headers
from .factories import (
    create_distillery_payload,
    create_mash_batch_payload,
    create_distillation_run_payload,
    create_barrel_payload,
    create_label_application_payload,
    create_bottling_run_payload,
    create_customer_payload,
    create_sales_order_payload,
    create_tour_booking_payload,
)

_OC = TEST_USERS["compliance_headers"]
_PM = TEST_USERS["production_headers"]
_SM = TEST_USERS["sales_headers"]
_TRS = TEST_USERS["tasting_headers"]


# --- Tier 1: single-entity progression -------------------------------------
def create_distillery(api, dsp_permit_number="DSP-CA-1", name="Bench DSP", state_code="CA"):
    payload = create_distillery_payload(
        name=name, dsp_permit_number=dsp_permit_number, state_code=state_code
    )
    return get_success_data(api.create_distillery(payload, _OC))


def create_gauged_run(
    api,
    distillery_id,
    *,
    collected_wine_gallons=20,
    collected_proof=100,
    gauge_method="VOLUME",
    collected_weight_lbs=None,
    spirit_type="WHISKEY",
    grain_bill="corn",
    volume_gallons=200,
):
    """Create mash + distillation run and gauge it. Returns (gauged_run, mash_id)."""
    mash = get_success_data(
        api.create_mash_batch(
            create_mash_batch_payload(
                distillery_id, grain_bill=grain_bill, volume_gallons=volume_gallons
            ),
            _PM,
        )
    )
    run_payload = create_distillation_run_payload(
        distillery_id,
        mash["id"],
        spirit_type=spirit_type,
        gauge_method=gauge_method,
        collected_wine_gallons=collected_wine_gallons,
        collected_proof=collected_proof,
    )
    if collected_weight_lbs is not None:
        run_payload["collected_weight_lbs"] = collected_weight_lbs
    run = get_success_data(api.create_distillation_run(run_payload, _PM))
    gauged = get_success_data(api.gauge_run(run["id"], _PM))
    return gauged, mash["id"]


def fill_barrel(api, run_id, *, fill_proof_gallons=15, char_level="CHAR_3", rickhouse_position="A-1"):
    return get_success_data(
        api.create_barrel(
            create_barrel_payload(
                run_id,
                fill_proof_gallons=fill_proof_gallons,
                char_level=char_level,
                rickhouse_position=rickhouse_position,
            ),
            _PM,
        )
    )


def create_approved_label(api, distillery_id, *, label_proof=100, brand_name="Old Bench",
                          net_contents_ml=750, spirit_type="WHISKEY"):
    """Create -> submit -> APPROVE a label application. Returns the APPROVED label."""
    label = get_success_data(
        api.create_label_application(
            create_label_application_payload(
                distillery_id,
                label_proof=label_proof,
                brand_name=brand_name,
                net_contents_ml=net_contents_ml,
                spirit_type=spirit_type,
            ),
            _OC,
        )
    )
    api.submit_label(label["id"], _OC)
    return get_success_data(api.decide_label(label["id"], {"outcome": "APPROVE"}, _OC))


def create_submitted_label(api, distillery_id, *, label_proof=100):
    """Create -> submit (but NOT approve). Returns the SUBMITTED label."""
    label = get_success_data(
        api.create_label_application(
            create_label_application_payload(distillery_id, label_proof=label_proof), _OC
        )
    )
    return get_success_data(api.submit_label(label["id"], _OC))


# --- Tier 3: full lifecycle shortcut ---------------------------------------
def setup_completed_run(
    api,
    *,
    dsp_permit_number="DSP-CA-1",
    collected_wine_gallons=20,
    collected_proof=100,
    fill_proof_gallons=15,
    label_proof=100,
    bottle_size_ml=750,
    bottles_per_case=6,
    planned_cases=10,
    line_id="LINE_A",
    scheduled_start="2026-05-02T08:00:00Z",
    scheduled_end="2026-05-02T12:00:00Z",
):
    """Full production chain through a COMPLETED bottling run with finished-goods
    inventory. Returns a dict with distillery_id, distillery, mash_id, run, barrel,
    label, and bottling_run (the COMPLETED run)."""
    dist = create_distillery(api, dsp_permit_number=dsp_permit_number)
    run, mash_id = create_gauged_run(
        api,
        dist["id"],
        collected_wine_gallons=collected_wine_gallons,
        collected_proof=collected_proof,
    )
    barrel = fill_barrel(api, run["id"], fill_proof_gallons=fill_proof_gallons)
    label = create_approved_label(api, dist["id"], label_proof=label_proof)
    br = get_success_data(
        api.create_bottling_run(
            create_bottling_run_payload(
                barrel["id"],
                label["id"],
                line_id=line_id,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                bottle_size_ml=bottle_size_ml,
                bottles_per_case=bottles_per_case,
                planned_cases=planned_cases,
            ),
            _PM,
        )
    )
    api.start_bottling_run(br["id"], _PM)
    completed = get_success_data(api.complete_bottling_run(br["id"], _PM))
    return {
        "distillery_id": dist["id"],
        "distillery": dist,
        "mash_id": mash_id,
        "run": run,
        "barrel": barrel,
        "label": label,
        "bottling_run": completed,
    }


# --- Customers and sales orders --------------------------------------------
def create_customer(api, *, name="Ada Buyer", email="ada@x.com", state_code="CA",
                    club_tier=None, age_verified=True, as_headers=None):
    payload = create_customer_payload(
        name=name, email=email, state_code=state_code, age_verified=age_verified
    )
    if club_tier is not None:
        payload["club_tier"] = club_tier
    return get_success_data(api.create_customer(payload, as_headers or _SM))


def create_order(api, customer_id, bottling_run_id, *, channel="THREE_TIER", cases=1,
                 unit_price_cents=5000, includes_cocktail=None, as_headers=None):
    payload = create_sales_order_payload(
        customer_id, bottling_run_id, channel=channel, cases=cases,
        unit_price_cents=unit_price_cents,
    )
    if includes_cocktail is not None:
        payload["includes_cocktail"] = includes_cocktail
    return get_success_data(api.create_sales_order(payload, as_headers or _SM))


def setup_paid_allocated_order(api, *, cases=4, planned_cases=10, channel="THREE_TIER",
                               dsp_permit_number="DSP-CA-1"):
    """COMPLETED run + age-verified customer + a PAID (ALLOCATED) order. Returns a
    dict with the setup keys plus customer and order (the PAID/ALLOCATED order)."""
    ctx = setup_completed_run(api, planned_cases=planned_cases, dsp_permit_number=dsp_permit_number)
    cust = create_customer(api, age_verified=True)
    order = create_order(
        api, cust["id"], ctx["bottling_run"]["id"], channel=channel, cases=cases
    )
    paid = get_success_data(api.pay_order(order["id"], _SM))
    ctx["customer"] = cust
    ctx["order"] = paid
    return ctx


# --- Tour bookings ---------------------------------------------------------
def create_tour(api, distillery_id, *, customer_email="guest@x.com", start_time,
                end_time, party_size, customer_name="Guest"):
    cust = create_customer(api, name=customer_name, email=customer_email, as_headers=_TRS)
    booking = get_success_data(
        api.create_tour_booking(
            create_tour_booking_payload(
                cust["id"], distillery_id, start_time=start_time, end_time=end_time,
                party_size=party_size,
            ),
            _TRS,
        )
    )
    return booking, cust
