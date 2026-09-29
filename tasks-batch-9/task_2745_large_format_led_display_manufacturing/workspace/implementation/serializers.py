"""Entity serialisers: stored fields plus the derived fields (scaffold section 1.1)."""

import aggregates


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def display_model(rec):
    return _public(rec)


def burn_in_chamber(rec):
    out = _public(rec)
    out.update(aggregates.chamber_derived(rec))
    return out


def commissioning_crew(rec):
    out = _public(rec)
    out.update(aggregates.crew_derived(rec))
    return out


def display_project(rec):
    out = _public(rec)
    out.update(aggregates.project_derived(rec))
    return out


def drawing_revision(rec):
    return _public(rec)


def cabinet(rec):
    out = _public(rec)
    out.update(aggregates.cabinet_derived(rec))
    return out


def module(rec):
    return _public(rec)


def burn_in_run(rec):
    return _public(rec)


def commissioning_visit(rec):
    return _public(rec)


def service_contract(rec):
    out = _public(rec)
    out.update(aggregates.contract_derived(rec))
    return out


def service_case(rec):
    return _public(rec)
