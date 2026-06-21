"""Resource serialization: strip internal fields, expose computed figures.

Internal-only keys (prefixed with '_') are never returned. Computed fields on
Case / Contract / FuneralHome are recomputed lazily at read time so a GET always
reflects current derived state.
"""
import services.calc as calc


def _public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def funeral_home(home):
    out = _public(home)
    out["trust_balance_cents"] = calc.home_trust_balance(home["id"])
    return out


def gpl_item(item):
    return _public(item)


def case(c):
    out = _public(c)
    prov, final = calc.case_statement_totals(c)
    out["statement_total_provisional_cents"] = prov
    # final is frozen at GFS issuance; before that it is 0
    if c.get("gfs_issued"):
        out["statement_total_final_cents"] = c.get("statement_total_final_cents", 0)
    else:
        out["statement_total_final_cents"] = 0
    return out


def statement_line(line):
    return _public(line)


def contract(con):
    out = _public(con)
    figs = calc.contract_figures(con)
    out.update(figs)
    return out


def trust_deposit(dep):
    return _public(dep)


def insurance_assignment(a):
    return _public(a)


def plot(p):
    return _public(p)


def venue(v):
    return _public(v)


def event(e):
    return _public(e)


def permit(p):
    return _public(p)
