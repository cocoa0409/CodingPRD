"""Composite setup helpers.

Each helper drives the live API through a complete, PRD-legal chain of calls and
returns a dict of the entities it created, so a test can start from a realistic
state in one line. Every helper accepts keyword overrides that are forwarded to
the payload factory of the entity it creates, and uses the lenient
``get_success_data`` internally because a setup chain asserts nothing itself.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    BATCH_EXCHANGE_REFERENCE_OUT,
    DOCKET_INTERSTATE,
    DOCKET_INTRASTATE,
    DOCKET_LOCAL,
    LATA_HOUSTON,
    POI_CLLI_HOUSTON,
    RATE_INTRASTATE,
    RATE_LOCAL,
    T_2026_07_01,
    T_2026_07_25,
    T_2026_09_01,
)
from .test_users import (
    access_billing_analyst_headers,
    dispute_resolution_officer_headers,
    interconnection_manager_headers,
    make_carrier_representative_headers,
    network_planner_headers,
    platform_admin_headers,
    regulatory_affairs_specialist_headers,
    revenue_assurance_controller_headers,
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def advance_clock(api, target_utc):
    """Move the logical clock forward to ``target_utc``."""
    return get_success_data(
        api.set_clock(f.clock_payload(target_utc), platform_admin_headers())
    )


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------
def setup_carrier(api, **overrides):
    """Register the canonical counterparty carrier."""
    return get_success_data(
        api.create_carrier(f.carrier_payload(**overrides), platform_admin_headers())
    )


def setup_second_carrier(api, **overrides):
    """Register a second, unrelated carrier for cross-carrier scope checks."""
    return get_success_data(
        api.create_carrier(
            f.second_carrier_payload(**overrides), platform_admin_headers()
        )
    )


def read_carrier(api, carrier_id):
    """Re-read a carrier so a caller can quote its current version."""
    return get_success_data(api.get_carrier(carrier_id, platform_admin_headers()))


# ---------------------------------------------------------------------------
# Tariff rate book
# ---------------------------------------------------------------------------
def setup_tariff_filing(api, approve=True, **overrides):
    """File one tariffed rate element and, by default, approve it into EFFECTIVE."""
    headers = regulatory_affairs_specialist_headers()
    filing = get_success_data(
        api.create_tariff_filing(f.tariff_filing_payload(**overrides), headers)
    )
    if approve:
        filing = get_success_data(api.approve_tariff_filing(filing["id"], {}, headers))
    return filing


def setup_local_reciprocal_tariff(api, approve=True, **overrides):
    """Put the LOCAL_RECIPROCAL_COMP rate on file, which agreement activation needs."""
    return setup_tariff_filing(
        api,
        approve=approve,
        **f._merge(
            {
                "filing_docket": DOCKET_LOCAL,
                "rate_element": "LOCAL_RECIPROCAL_COMP",
                "rate_per_mou_usd": RATE_LOCAL,
            },
            overrides,
        ),
    )


def setup_tariff_book(api, approve_local=True, effective_date=None):
    """File and approve all three rate elements the rating engine reads."""
    window = {} if effective_date is None else {"effective_date": effective_date}
    interstate = setup_tariff_filing(api, filing_docket=DOCKET_INTERSTATE, **window)
    intrastate = setup_tariff_filing(
        api,
        filing_docket=DOCKET_INTRASTATE,
        rate_element="INTRASTATE_SWITCHED_ACCESS",
        rate_per_mou_usd=RATE_INTRASTATE,
        **window,
    )
    local = setup_local_reciprocal_tariff(api, approve=approve_local, **window)
    return {
        "INTERSTATE_SWITCHED_ACCESS": interstate,
        "INTRASTATE_SWITCHED_ACCESS": intrastate,
        "LOCAL_RECIPROCAL_COMP": local,
    }


# ---------------------------------------------------------------------------
# Traffic factor filings
# ---------------------------------------------------------------------------
def setup_factor_filing(api, carrier, **overrides):
    """File the carrier's quarterly PIU/PLU factors, quoting its current version."""
    return get_success_data(
        api.create_factor_filing(
            f.factor_filing_payload(carrier["id"], carrier["version"], **overrides),
            access_billing_analyst_headers(),
        )
    )


# ---------------------------------------------------------------------------
# Usage batches
# ---------------------------------------------------------------------------
CANONICAL_CDR_BUILDERS = (
    f.local_cdr_payload,
    f.interstate_cdr_payload,
    f.intrastate_cdr_payload,
    f.indeterminate_no_cpn_cdr_payload,
    f.indeterminate_no_origin_cdr_payload,
    f.indeterminate_cpn_without_origin_cdr_payload,
)


def setup_usage_batch(api, carrier_id, **overrides):
    """Open a usage batch over a closed exchange period."""
    return get_success_data(
        api.create_usage_batch(
            f.usage_batch_payload(carrier_id, **overrides),
            access_billing_analyst_headers(),
        )
    )


def append_canonical_cdrs(api, batch_id, builders=CANONICAL_CDR_BUILDERS):
    """Append the canonical six-record call sample in created_at order."""
    headers = access_billing_analyst_headers()
    records = []
    for build in builders:
        records.append(
            get_success_data(
                api.append_call_detail_record(batch_id, build(), headers)
            )
        )
    return records


def setup_submitted_batch(
    api,
    carrier=None,
    builders=CANONICAL_CDR_BUILDERS,
    approve_local=True,
    with_factor_filing=True,
    tariff_effective_date=None,
    clock=T_2026_09_01,
    filings=None,
    **overrides,
):
    """Carrier + rate book + factors + a SUBMITTED batch holding the call sample."""
    carrier = carrier or setup_carrier(api)
    if filings is None:
        filings = setup_tariff_book(
            api, approve_local=approve_local, effective_date=tariff_effective_date
        )
    factor_filing = setup_factor_filing(api, carrier) if with_factor_filing else None
    advance_clock(api, clock)
    batch = setup_usage_batch(api, carrier["id"], **overrides)
    records = append_canonical_cdrs(api, batch["id"], builders)
    return {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "rep_headers": make_carrier_representative_headers(carrier["id"]),
        "filings": filings,
        "factor_filing": factor_filing,
        "batch": batch,
        "batch_id": batch["id"],
        "records": records,
    }


def setup_jurisdictionalized_batch(api, **kwargs):
    """As ``setup_submitted_batch``, then run jurisdiction determination."""
    state = setup_submitted_batch(api, **kwargs)
    state["batch"] = get_success_data(
        api.jurisdictionalize_batch(state["batch_id"], {}, access_billing_analyst_headers())
    )
    return state


def setup_rated_batch(api, **kwargs):
    """As ``setup_jurisdictionalized_batch``, then rate the batch at the tariffed rates."""
    state = setup_jurisdictionalized_batch(api, **kwargs)
    state["batch"] = get_success_data(
        api.rate_batch(state["batch_id"], {}, access_billing_analyst_headers())
    )
    return state


def setup_outbound_rated_batch(api, carrier_id, **overrides):
    """A RATED batch of traffic we handed the counterparty, for settlement reads."""
    headers = access_billing_analyst_headers()
    batch = get_success_data(
        api.create_usage_batch(
            f.usage_batch_payload(
                carrier_id,
                **f._merge(
                    {
                        "period_start": T_2026_07_01,
                        "period_end": T_2026_07_25,
                        "direction": "ORIGINATING_FROM_US",
                        "exchange_reference": BATCH_EXCHANGE_REFERENCE_OUT,
                    },
                    overrides,
                ),
            ),
            headers,
        )
    )
    get_success_data(
        api.append_call_detail_record(
            batch["id"], f.local_cdr_payload(duration_seconds=3600), headers
        )
    )
    get_success_data(api.jurisdictionalize_batch(batch["id"], {}, headers))
    return get_success_data(api.rate_batch(batch["id"], {}, headers))


# ---------------------------------------------------------------------------
# Agreements and negotiation
# ---------------------------------------------------------------------------
def setup_draft_agreement(api, carrier=None, ensure_local_rate=True, **overrides):
    """A carrier plus a DRAFT agreement holding the opening ask."""
    carrier = carrier or setup_carrier(api)
    local_filing = setup_local_reciprocal_tariff(api) if ensure_local_rate else None
    agreement = get_success_data(
        api.create_agreement(
            f.agreement_payload(carrier["id"], **overrides),
            interconnection_manager_headers(),
        )
    )
    return {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "rep_headers": make_carrier_representative_headers(carrier["id"]),
        "local_filing": local_filing,
        "agreement": agreement,
        "agreement_id": agreement["id"],
        "offers": [],
    }


def append_proposal(api, state, **overrides):
    """Append a PROPOSAL from the CLEC side, quoting the agreement's current version."""
    agreement = read_agreement(api, state["agreement_id"])
    offer = get_success_data(
        api.append_offer(
            state["agreement_id"],
            f.proposal_offer_payload(agreement["version"], **overrides),
            interconnection_manager_headers(),
        )
    )
    state["offers"].append(offer)
    state["agreement"] = read_agreement(api, state["agreement_id"])
    return offer


def append_counter(api, state, from_counterparty=True, **overrides):
    """Append a COUNTER from either side, quoting the agreement's current version."""
    agreement = read_agreement(api, state["agreement_id"])
    headers = (
        state["rep_headers"] if from_counterparty else interconnection_manager_headers()
    )
    offer = get_success_data(
        api.append_offer(
            state["agreement_id"],
            f.counter_offer_payload(agreement["version"], **overrides),
            headers,
        )
    )
    state["offers"].append(offer)
    state["agreement"] = read_agreement(api, state["agreement_id"])
    return offer


def read_agreement(api, agreement_id):
    """Re-read an agreement so a caller can quote its current version."""
    return get_success_data(
        api.get_agreement(agreement_id, interconnection_manager_headers())
    )


def setup_proposed_agreement(api, carrier=None, offer_overrides=None, **overrides):
    """A DRAFT agreement carrying one standing PROPOSAL from the CLEC side."""
    state = setup_draft_agreement(api, carrier=carrier, **overrides)
    append_proposal(api, state, **(offer_overrides or {}))
    return state


def setup_executed_agreement(api, carrier=None, offer_overrides=None, **overrides):
    """An EXECUTED agreement whose commercial terms have been pinned by acceptance."""
    state = setup_proposed_agreement(
        api, carrier=carrier, offer_overrides=offer_overrides, **overrides
    )
    get_success_data(
        api.accept_offer(state["offers"][-1]["id"], {}, state["rep_headers"])
    )
    state["agreement"] = read_agreement(api, state["agreement_id"])
    return state


def setup_effective_agreement(api, carrier=None, offer_overrides=None, **overrides):
    """An EFFECTIVE agreement: executed, its date reached and a reciprocal rate on file."""
    state = setup_executed_agreement(
        api, carrier=carrier, offer_overrides=offer_overrides, **overrides
    )
    state["agreement"] = get_success_data(
        api.activate_agreement(
            state["agreement_id"], {}, interconnection_manager_headers()
        )
    )
    return state


# ---------------------------------------------------------------------------
# Trunk groups
# ---------------------------------------------------------------------------
def setup_requested_trunk_group(api, agreement_id, **overrides):
    """Request a trunk group at a point of interconnection."""
    return get_success_data(
        api.create_trunk_group(
            f.trunk_group_payload(agreement_id, **overrides),
            network_planner_headers(),
        )
    )


def setup_provisioned_trunk_group(api, agreement_id, provisioned_trunks=48, **overrides):
    """Request a trunk group and provision physical trunks on it."""
    trunk_group = setup_requested_trunk_group(api, agreement_id, **overrides)
    return get_success_data(
        api.provision_trunk_group(
            trunk_group["id"],
            f.provision_payload(provisioned_trunks),
            network_planner_headers(),
        )
    )


def setup_in_service_trunk_group(api, agreement_id, provisioned_trunks=48, **overrides):
    """Request, provision and activate a trunk group under an EFFECTIVE agreement."""
    trunk_group = setup_provisioned_trunk_group(
        api, agreement_id, provisioned_trunks, **overrides
    )
    return get_success_data(
        api.activate_trunk_group(trunk_group["id"], {}, network_planner_headers())
    )


def setup_second_poi_trunk_group(api, agreement_id, **overrides):
    """An in-service trunk group at a second point of interconnection."""
    return setup_in_service_trunk_group(
        api,
        agreement_id,
        **f._merge(
            {
                "trunk_group_serial": "TG-HSTN-TWOWAY-003",
                "poi_clli_code": POI_CLLI_HOUSTON,
                "lata_code": LATA_HOUSTON,
            },
            overrides,
        ),
    )


# ---------------------------------------------------------------------------
# Traffic studies and augment orders
# ---------------------------------------------------------------------------
def record_measurement(api, trunk_group_id, headers=None, **overrides):
    """Record a busy-hour traffic study against an in-service trunk group."""
    return get_success_data(
        api.create_traffic_measurement(
            trunk_group_id,
            f.measurement_payload(**overrides),
            headers or network_planner_headers(),
        )
    )


def latest_pending_order(api, trunk_group_id):
    """The PENDING augment order raised for a trunk group."""
    orders = get_success_data(
        api.list_augment_orders(
            network_planner_headers(),
            params={"trunk_group_id": trunk_group_id, "status": "PENDING"},
        )
    )
    assert orders, f"no PENDING augment order was raised for {trunk_group_id}"
    return orders[-1]


def setup_pending_augment_order(api, trunk_group_id, **overrides):
    """Drive a blocking breach that raises one PENDING augment order."""
    measurement = record_measurement(api, trunk_group_id, **overrides)
    return measurement, latest_pending_order(api, trunk_group_id)


def setup_accepted_augment_order(api, trunk_group_id, rep_headers, committed_due_date=None, **overrides):
    """A PENDING augment order the counterparty has committed to a due date for."""
    measurement, order = setup_pending_augment_order(api, trunk_group_id, **overrides)
    payload = (
        f.accept_augment_payload()
        if committed_due_date is None
        else f.accept_augment_payload(committed_due_date)
    )
    order = get_success_data(api.accept_augment_order(order["id"], payload, rep_headers))
    return measurement, order


def setup_completed_augment_order(api, trunk_group_id, rep_headers, installed_trunks=24, **overrides):
    """An ACCEPTED augment order whose installed trunks have been recorded."""
    measurement, order = setup_accepted_augment_order(
        api, trunk_group_id, rep_headers, **overrides
    )
    order = get_success_data(
        api.complete_augment_order(
            order["id"],
            f.complete_augment_payload(installed_trunks),
            network_planner_headers(),
        )
    )
    return measurement, order


# ---------------------------------------------------------------------------
# Access invoices
# ---------------------------------------------------------------------------
def setup_draft_invoice(api, state=None, **kwargs):
    """A RATED batch plus the DRAFT invoice raised from it."""
    state = state or setup_rated_batch(api, **kwargs)
    invoice = get_success_data(
        api.create_invoice(
            f.invoice_payload(state["batch_id"]), access_billing_analyst_headers()
        )
    )
    state["invoice"] = invoice
    state["invoice_id"] = invoice["id"]
    return state


def setup_issued_invoice(api, state=None, issuer=None, **kwargs):
    """An ISSUED invoice whose dispute filing window is open."""
    state = setup_draft_invoice(api, state=state, **kwargs)
    headers = (
        access_billing_analyst_headers()
        if issuer is None
        else access_billing_analyst_headers(issuer)
    )
    state["invoice"] = get_success_data(
        api.issue_invoice(state["invoice_id"], {}, headers)
    )
    state["issuer_headers"] = headers
    return state


def read_invoice(api, invoice_id):
    """Re-read an invoice through the platform admin view."""
    return get_success_data(api.get_invoice(invoice_id, platform_admin_headers()))


# ---------------------------------------------------------------------------
# Billing disputes
# ---------------------------------------------------------------------------
def setup_dispute(api, state=None, acknowledge=False, **kwargs):
    """A dispute filed by the carrier's own representative against an ISSUED invoice."""
    dispute_overrides = kwargs.pop("dispute_overrides", {})
    state = state or setup_issued_invoice(api, **kwargs)
    dispute = get_success_data(
        api.create_dispute(
            f.dispute_payload(state["invoice_id"], **dispute_overrides),
            state["rep_headers"],
        )
    )
    if acknowledge:
        dispute = get_success_data(
            api.acknowledge_dispute(
                dispute["id"], {}, dispute_resolution_officer_headers()
            )
        )
    state["dispute"] = dispute
    state["dispute_id"] = dispute["id"]
    return state


def read_dispute(api, dispute_id):
    """Re-read a dispute through the platform admin view."""
    return get_success_data(api.get_dispute(dispute_id, platform_admin_headers()))


# ---------------------------------------------------------------------------
# Reconciliation cases
# ---------------------------------------------------------------------------
def setup_reconciliation_case(api, state, evaluate=True, **overrides):
    """Open a mutual record-exchange case against the state's rated batch."""
    headers = revenue_assurance_controller_headers()
    case = get_success_data(
        api.create_reconciliation_case(
            f.reconciliation_case_payload(state["batch_id"], **overrides), headers
        )
    )
    if evaluate:
        case = get_success_data(api.evaluate_reconciliation_case(case["id"], {}, headers))
    state["case"] = case
    state["case_id"] = case["id"]
    return state


# ---------------------------------------------------------------------------
# Reserve reads
# ---------------------------------------------------------------------------
def read_reserve_summary(api, carrier_id):
    """Read the eight-figure reserve summary for a carrier."""
    return get_success_data(
        api.get_carrier_reserve_summary(carrier_id, revenue_assurance_controller_headers())
    )


def read_ledger(api, carrier_id=None, invoice_id=None, reserve_bucket=None, limit=100):
    """Read the append-only reserve ledger, optionally narrowed by filter."""
    params = {"limit": limit}
    if carrier_id is not None:
        params["carrier_id"] = carrier_id
    if invoice_id is not None:
        params["invoice_id"] = invoice_id
    if reserve_bucket is not None:
        params["reserve_bucket"] = reserve_bucket
    return get_success_data(
        api.list_reserve_ledger_entries(
            revenue_assurance_controller_headers(), params=params
        )
    )


def bucket_entries(entries, reserve_bucket):
    """Filter ledger entries down to one reserve bucket, preserving order."""
    return [entry for entry in entries if entry.get("reserve_bucket") == reserve_bucket]


# ---------------------------------------------------------------------------
# Combined chains
# ---------------------------------------------------------------------------
def setup_effective_agreement_with_rated_batch(api, tariff_effective_date=T_2026_07_01):
    """An EFFECTIVE agreement over a carrier that also has one RATED inbound batch."""
    carrier = setup_carrier(api)
    filings = setup_tariff_book(api, effective_date=tariff_effective_date)
    agreement_state = setup_draft_agreement(api, carrier=carrier, ensure_local_rate=False)
    append_proposal(api, agreement_state)
    get_success_data(
        api.accept_offer(
            agreement_state["offers"][-1]["id"], {}, agreement_state["rep_headers"]
        )
    )
    agreement_state["agreement"] = get_success_data(
        api.activate_agreement(
            agreement_state["agreement_id"], {}, interconnection_manager_headers()
        )
    )
    batch_state = setup_rated_batch(api, carrier=carrier, filings=filings)
    batch_state.update(
        {
            "agreement": agreement_state["agreement"],
            "agreement_id": agreement_state["agreement_id"],
            "offers": agreement_state["offers"],
        }
    )
    return batch_state


def setup_effective_agreement_with_in_service_trunks(
    api, provisioned_trunks=48, capacity_trunks=None, **overrides
):
    """An EFFECTIVE agreement carrying one in-service trunk group."""
    agreement_overrides = dict(overrides)
    if capacity_trunks is not None:
        agreement_overrides["poi_facility_capacity_trunks"] = capacity_trunks
    state = setup_effective_agreement(api, **agreement_overrides)
    state["trunk_group"] = setup_in_service_trunk_group(
        api, state["agreement_id"], provisioned_trunks
    )
    state["trunk_group_id"] = state["trunk_group"]["id"]
    state["agreement"] = read_agreement(api, state["agreement_id"])
    return state


def read_trunk_group(api, trunk_group_id):
    """Re-read a trunk group through the network planner view."""
    return get_success_data(
        api.get_trunk_group(trunk_group_id, network_planner_headers())
    )


def read_augment_order(api, order_id):
    """Re-read an augment order through the network planner view."""
    return get_success_data(
        api.get_augment_order(order_id, network_planner_headers())
    )


def read_usage_batch(api, batch_id):
    """Re-read a usage batch through the billing analyst view."""
    return get_success_data(
        api.get_usage_batch(batch_id, access_billing_analyst_headers())
    )


def read_tariff_filing(api, filing_id):
    """Re-read a tariff filing through the regulatory affairs view."""
    return get_success_data(
        api.get_tariff_filing(filing_id, regulatory_affairs_specialist_headers())
    )


def read_factor_filing(api, factor_filing_id):
    """Re-read a traffic factor filing through the billing analyst view."""
    return get_success_data(
        api.get_factor_filing(factor_filing_id, access_billing_analyst_headers())
    )


def read_reconciliation_case(api, case_id):
    """Re-read a reconciliation case through the revenue assurance view."""
    return get_success_data(
        api.get_reconciliation_case(case_id, revenue_assurance_controller_headers())
    )
