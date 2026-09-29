"""Resource serialisers -- stored fields plus derived (computed) fields."""

from services import calc


def _plain(row):
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def student(row):
    out = _plain(row)
    out.update(calc.student_computed(row))
    return out


def course(row):
    out = _plain(row)
    out.update(calc.course_computed(row))
    return out


def requisite(row):
    return _plain(row)


def rule(row):
    return _plain(row)


def administration(row):
    out = _plain(row)
    out.update(calc.admin_computed(row))
    return out


def attempt(row):
    return _plain(row)


def determination(row):
    return _plain(row)


def appeal(row):
    return _plain(row)


def section(row):
    out = _plain(row)
    out.update(calc.section_computed(row))
    return out


def registration(row):
    out = _plain(row)
    out["success"] = row["final_grade"] in ("A", "B", "C", "P")
    return out


def override(row):
    return _plain(row)


def study(row):
    return _plain(row)
