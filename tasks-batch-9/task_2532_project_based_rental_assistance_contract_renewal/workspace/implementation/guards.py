"""Path/body reference resolution (ladder steps 4 and 5), ownership chains
(step 3), transition legality (step 13) and the shared list helper.
"""
import functools

from flask import g

from core import (
    ROLE_OWNER, fail, filter_arg, paginate, read_pagination, require_owner,
    require_roles, respond_array, table,
)
import calcs

# --------------------------------------------------------------------------
# Ladder step 4/5: existence, one dedicated 404 per resource kind
# --------------------------------------------------------------------------
_NOT_FOUND = {
    "owners": "ERR_OWNER_NOT_FOUND",
    "properties": "ERR_PROPERTY_NOT_FOUND",
    "contracts": "ERR_CONTRACT_NOT_FOUND",
    "cases": "ERR_RENEWAL_CASE_NOT_FOUND",
    "studies": "ERR_STUDY_NOT_FOUND",
    "comparables": "ERR_COMPARABLE_NOT_FOUND",
    "analyses": "ERR_UA_ANALYSIS_NOT_FOUND",
    "households": "ERR_TENANT_NOT_FOUND",
    "certifications": "ERR_CERTIFICATION_NOT_FOUND",
    "notices": "ERR_NOTICE_NOT_FOUND",
    "determinations": "ERR_DETERMINATION_NOT_FOUND",
    "vouchers": "ERR_ENHANCED_VOUCHER_NOT_FOUND",
    "submissions": "ERR_VOUCHER_SUBMISSION_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
}


def resolve(table_name, row_id):
    row = None
    if isinstance(row_id, str) and row_id:
        row = table(table_name).get(row_id)
    if row is None:
        fail(_NOT_FOUND[table_name], "%s could not be resolved." % table_name[:-1])
    return row


def body_fk(body, field, table_name):
    """Resolve a body foreign key.

    Returns None when the value is absent or not a usable string so that the
    later shape check (ladder step 6) reports ERR_INVALID_REQUEST instead.
    """
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    return resolve(table_name, value)


# --------------------------------------------------------------------------
# Ladder step 3: the owner reachable from the target resource
# --------------------------------------------------------------------------
def owner_id_of_property(prop):
    return prop["owner_id"]


def owner_id_of_contract(contract):
    prop = table("properties").get(contract["property_id"])
    return prop["owner_id"] if prop else None


def owner_id_of_case(case):
    contract = table("contracts").get(case["contract_id"])
    return owner_id_of_contract(contract) if contract else None


def owner_id_of_study(study):
    case = table("cases").get(study["renewal_case_id"])
    return owner_id_of_case(case) if case else None


def owner_id_of_household(household):
    prop = table("properties").get(household["property_id"])
    return prop["owner_id"] if prop else None


def owner_id_of_analysis(analysis):
    prop = table("properties").get(analysis["property_id"])
    return prop["owner_id"] if prop else None


def owner_id_of_notice(notice):
    case = table("cases").get(notice["renewal_case_id"])
    return owner_id_of_case(case) if case else None


def owner_id_of_submission(submission):
    contract = table("contracts").get(submission["contract_id"])
    return owner_id_of_contract(contract) if contract else None


def owner_id_of_claim(claim):
    contract = table("contracts").get(claim["contract_id"])
    return owner_id_of_contract(contract) if contract else None


def own_property(prop):
    require_owner(owner_id_of_property(prop))
    return prop


def own_contract(contract):
    require_owner(owner_id_of_contract(contract))
    return contract


def own_case(case):
    require_owner(owner_id_of_case(case))
    return case


def own_study(study):
    require_owner(owner_id_of_study(study))
    return study


def own_household(household):
    require_owner(owner_id_of_household(household))
    return household


def own_analysis(analysis):
    require_owner(owner_id_of_analysis(analysis))
    return analysis


def own_notice(notice):
    require_owner(owner_id_of_notice(notice))
    return notice


def own_submission(submission):
    require_owner(owner_id_of_submission(submission))
    return submission


def own_claim(claim):
    require_owner(owner_id_of_claim(claim))
    return claim


# --------------------------------------------------------------------------
# Ladder step 13: transition legality
# --------------------------------------------------------------------------
def require_state(row, field, *allowed):
    if row.get(field) not in allowed:
        fail("ERR_TRANSITION_NOT_ALLOWED",
             "Transition is not declared from state %s." % row.get(field))


def deny_transition(message="Transition is not declared from the current state."):
    fail("ERR_TRANSITION_NOT_ALLOWED", message)


# --------------------------------------------------------------------------
# Shared list plumbing (ladder step 7 plus §2.3 ordering)
# --------------------------------------------------------------------------
def list_response(items, sort_key=None):
    limit, offset = read_pagination()
    ordered = sorted(items, key=sort_key) if sort_key else calcs.by_seq(items)
    window, total = paginate(ordered, limit, offset)
    return respond_array(window, limit, offset, total)


def eq_filter(items, field, arg_name=None):
    wanted = filter_arg(arg_name or field)
    if wanted is None:
        return items
    return [row for row in items if row.get(field) == wanted]


def is_owner_role():
    return g.role == ROLE_OWNER


# --------------------------------------------------------------------------
# Ladder step 2 wrapper: the endpoint's authorized-role list from PRD section 4
# --------------------------------------------------------------------------
def endpoint(*allowed):
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            require_roles(*allowed)
            return view(*args, **kwargs)
        return wrapper
    return decorator
