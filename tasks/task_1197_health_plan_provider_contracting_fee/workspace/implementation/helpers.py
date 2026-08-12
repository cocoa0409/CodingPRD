"""Shared lookup helpers for hierarchical existence resolution."""

from errors import ApiError
import store


def get_or_404(collection, resource_id, error_id, label):
    obj = collection.get(resource_id)
    if obj is None:
        raise ApiError(error_id, 404, f"{label} {resource_id} does not exist.")
    return obj


def get_provider(pid):
    return get_or_404(store.providers, pid, "ERR_PROVIDER_NOT_FOUND", "Provider")


def get_network(nid):
    return get_or_404(store.networks, nid, "ERR_NETWORK_NOT_FOUND", "Network")


def get_benchmark(bid):
    return get_or_404(store.benchmarks, bid, "ERR_BENCHMARK_NOT_FOUND", "MedicareBenchmark")


def get_parity_rule(rid):
    return get_or_404(store.parity_rules, rid, "ERR_PARITY_RULE_NOT_FOUND", "RateParityRule")


def get_contract(cid):
    return get_or_404(store.contracts, cid, "ERR_CONTRACT_NOT_FOUND", "Contract")


def get_version(vid):
    return get_or_404(store.versions, vid, "ERR_VERSION_NOT_FOUND", "ContractVersion")


def get_entry(eid):
    return get_or_404(store.entries, eid, "ERR_ENTRY_NOT_FOUND", "FeeScheduleEntry")


def get_carve_out(cid):
    return get_or_404(store.carve_outs, cid, "ERR_CARVE_OUT_NOT_FOUND", "CarveOut")


def get_batch(bid):
    return get_or_404(store.batches, bid, "ERR_BATCH_NOT_FOUND", "SimulationBatch")


def get_paid_claim(pid):
    return get_or_404(store.paid_claims, pid, "ERR_PAID_CLAIM_NOT_FOUND", "PaidClaimSnapshot")


def get_run(rid):
    return get_or_404(store.runs, rid, "ERR_RUN_NOT_FOUND", "RetroAdjustmentRun")


def get_adjustment(aid):
    return get_or_404(store.adjustments, aid, "ERR_ADJUSTMENT_NOT_FOUND", "RetroAdjustment")


def get_notice(nid):
    return get_or_404(store.notices, nid, "ERR_NOTICE_NOT_FOUND", "TerminationNotice")


def get_case(cid):
    return get_or_404(store.cases, cid, "ERR_CASE_NOT_FOUND", "ContinuityOfCareCase")


def get_audit_event(aid):
    return get_or_404(store.audit_events, aid, "ERR_AUDIT_EVENT_NOT_FOUND", "AuditEvent")


def contract_of_version(version):
    return store.contracts.get(version["contract_id"])


def provider_of_contract(contract):
    return store.providers.get(contract["provider_id"])


def sorted_by_created(items):
    return sorted(items, key=lambda o: o["created_at"])
