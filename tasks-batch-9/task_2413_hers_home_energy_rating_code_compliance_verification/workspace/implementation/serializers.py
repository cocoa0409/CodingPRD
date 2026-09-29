"""Resource serializers. Internal bookkeeping keys (prefixed with '_') are hidden."""

from derived import effective_certification_status


def _public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def builder_out(row):
    return _public(row)


def subdivision_out(row):
    return _public(row)


def plan_model_out(row):
    return _public(row)


def home_out(row):
    return _public(row)


def rater_out(row):
    data = _public(row)
    data["effective_certification_status"] = effective_certification_status(row)
    return data


def rating_out(row):
    return _public(row)


def inspection_out(row):
    return _public(row)


def diagnostic_test_out(row):
    return _public(row)


def sample_set_out(row):
    return _public(row)


def qa_review_out(row):
    return _public(row)


def corrective_action_out(row):
    return _public(row)


def document_package_out(row):
    return _public(row)
