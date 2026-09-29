"""Public JSON views. Clock-dependent fields are derived at read time."""
import calc


def _base(row):
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    return out


def employer(row):
    return _base(row)


def plan(row):
    return _base(row)


def vendor(row):
    return _base(row)


def isa(row):
    out = _base(row)
    out["data_stale"] = calc.isa_data_stale(row)
    return out


def participant(row):
    out = _base(row)
    out["attained_age_at_year_end"] = calc.attained_age_at_year_end(row)
    return out


def notice(row):
    return _base(row)


def determination(row):
    return _base(row)


def vendor_account(row):
    return _base(row)


def election(row):
    return _base(row)


def batch(row):
    return _base(row)


def correction(row):
    return _base(row)


def participant_request(row):
    return _base(row)


def movement(row):
    return _base(row)
